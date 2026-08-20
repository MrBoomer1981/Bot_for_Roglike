"""Установка мод-стека одной командой.

Руками это шесть шагов с двумя легко путаемыми папками. Здесь то же самое
делается автоматически: определяется процессор, находится каталог игры,
качаются нужные релизы и раскладываются по местам.

Осознанные ограничения, потому что установка трогает чужую машину:

- перед закачкой печатается, что именно и откуда будет скачано;
- `--dry-run` показывает план, ничего не делая;
- скачанный код никогда не запускается, только распаковывается;
- распаковка проверяет имена файлов: архив не может записать за пределы
  назначенного каталога.

Закачка вынесена за интерфейс `Fetcher`, поэтому вся раскладка проверяется
тестами на поддельных архивах, без сети и без macOS.
"""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

__all__ = [
    "Component",
    "Fetcher",
    "InstallError",
    "Paths",
    "UrlFetcher",
    "clear_quarantine",
    "components",
    "find_game_dir",
    "install",
    "resolve_paths",
    "verify",
]


class InstallError(RuntimeError):
    """Установка невозможна: не найдена игра, не скачался релиз и подобное."""


# ---------------------------------------------------------------------------
# Где что лежит
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Paths:
    """Два каталога, которые постоянно путают."""

    game: Path
    """Каталог игры в библиотеке Steam. Сюда кладётся `liblovely.dylib`."""

    mods: Path
    """Каталог сохранений Balatro. Сюда кладутся сами моды."""


#: Стандартное место библиотеки Steam на macOS.
_DEFAULT_STEAM = "Library/Application Support/Steam"

#: Каталог сохранений игры — он же каталог модов.
_SAVE_DIR = "Library/Application Support/Balatro"

_VDF_PATH = re.compile(r'"path"\s+"([^"]+)"')


def steam_libraries(home: Path) -> list[Path]:
    """Все библиотеки Steam, включая вынесенные на другие диски.

    Steam хранит их список в `libraryfolders.vdf`. Без разбора этого файла
    установка ломается у всех, кто держит игры на внешнем диске.
    """
    libraries = [home / _DEFAULT_STEAM]
    manifest = home / _DEFAULT_STEAM / "steamapps" / "libraryfolders.vdf"
    if manifest.is_file():
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return libraries
        for match in _VDF_PATH.finditer(text):
            candidate = Path(match.group(1))
            if candidate not in libraries:
                libraries.append(candidate)
    return libraries


def find_game_dir(home: Path) -> Path | None:
    """Найти каталог установленной Balatro."""
    for library in steam_libraries(home):
        candidate = library / "steamapps" / "common" / "Balatro"
        if (candidate / "Balatro.app").exists():
            return candidate
    return None


def resolve_paths(home: Path, game_dir: Path | None = None) -> Paths:
    """Определить оба каталога, при необходимости создав каталог модов."""
    game = game_dir or find_game_dir(home)
    if game is None:
        raise InstallError(
            "не нашёл установленную Balatro в библиотеках Steam. "
            "Если она стоит в нестандартном месте, укажи путь: --game-dir ПУТЬ"
        )
    if not (game / "Balatro.app").exists():
        raise InstallError(f"в {game} нет Balatro.app — это не каталог игры")
    return Paths(game=game, mods=home / _SAVE_DIR / "Mods")


# ---------------------------------------------------------------------------
# Закачка
# ---------------------------------------------------------------------------


class Fetcher(Protocol):
    """Как добываются релизы. Подменяется в тестах."""

    def json(self, url: str) -> Any:
        """Прочитать JSON по адресу."""
        ...

    def download(self, url: str, target: Path) -> None:
        """Скачать файл в `target`."""
        ...


class UrlFetcher:
    """Настоящая закачка по сети."""

    def __init__(self, timeout: float = 60.0) -> None:
        self.timeout = timeout

    def json(self, url: str) -> Any:
        with urllib.request.urlopen(url, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def download(self, url: str, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with (
            urllib.request.urlopen(url, timeout=self.timeout) as response,
            target.open("wb") as out,
        ):
            shutil.copyfileobj(response, out)


# ---------------------------------------------------------------------------
# Безопасная распаковка
# ---------------------------------------------------------------------------


def _safe_members(names: Sequence[str], archive: str) -> None:
    """Убедиться, что архив не пытается записать за пределы каталога."""
    for name in names:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise InstallError(f"архив {archive} содержит подозрительный путь: {name}")


def _unpack(archive: Path, into: Path) -> Path:
    """Распаковать архив во временный каталог и вернуть его."""
    into.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive, "r:gz") as tar:
            _safe_members(tar.getnames(), archive.name)
            tar.extractall(into, filter="data")
    elif archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zipped:
            _safe_members(zipped.namelist(), archive.name)
            zipped.extractall(into)
    else:
        raise InstallError(f"не умею распаковывать {archive.name}")
    return into


def _find(root: Path, name: str) -> Path:
    """Найти файл или каталог по имени в распакованном архиве.

    Из нескольких совпадений берётся ближайшее к корню: в архиве может
    оказаться и вложенный каталог с тем же именем, и брать первый попавшийся
    от обхода — значит зависеть от порядка файлов в архиве.
    """
    if (direct := root / name).exists():
        return direct
    candidates = sorted(root.rglob(name), key=lambda path: len(path.parts))
    if candidates:
        return candidates[0]
    raise InstallError(f"в архиве нет {name}")


def _replace_dir(source: Path, target: Path) -> None:
    """Положить каталог на место, заменив прежний."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


# ---------------------------------------------------------------------------
# Компоненты
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Component:
    """Одна устанавливаемая часть стека."""

    name: str
    repo: str
    purpose: str
    place: Callable[[Path, Paths], list[Path]]
    """Раскладка распакованного архива. Возвращает созданные пути."""

    expect: tuple[str, ...] = ()
    """Что должно появиться после установки, относительно `expect_root`."""

    expect_root: str = "mods"
    """Куда смотреть при проверке: `game` — каталог игры, `mods` — каталог модов."""

    asset: Callable[[Sequence[dict[str, Any]], str], tuple[str, str]] | None = None
    """Как выбрать файл релиза. `None` — брать автоматический архив исходников."""


def _lovely_asset(assets: Sequence[dict[str, Any]], arch: str) -> tuple[str, str]:
    wanted = "aarch64-apple-darwin" if arch == "arm64" else "x86_64-apple-darwin"
    for asset in assets:
        name = str(asset.get("name", ""))
        if wanted in name and name.endswith((".tar.gz", ".tgz")):
            return name, str(asset["browser_download_url"])
    raise InstallError(
        f"в релизе Lovely нет файла для {wanted}. Скачай вручную: "
        "https://github.com/ethangreen-dev/lovely-injector/releases"
    )


def _place_lovely(unpacked: Path, paths: Paths) -> list[Path]:
    """Единственный нужный файл — библиотека. Скрипт запуска не нужен."""
    library = _find(unpacked, "liblovely.dylib")
    target = paths.game / "liblovely.dylib"
    shutil.copy2(library, target)
    return [target]


def _place_steamodded(unpacked: Path, paths: Paths) -> list[Path]:
    """Внутри архива исходников лежит один каталог — он и есть smods."""
    inner = _archive_root(unpacked)
    target = paths.mods / "smods"
    _replace_dir(inner, target)
    return [target]


def _place_balatrobot(unpacked: Path, paths: Paths) -> list[Path]:
    """Из исходников нужны манифест, точка входа и код на Lua."""
    inner = _archive_root(unpacked)
    target = paths.mods / "balatrobot"
    if target.exists():
        shutil.rmtree(target)
    (target / "src").mkdir(parents=True)

    created: list[Path] = []
    for name in ("balatrobot.json", "balatrobot.lua"):
        shutil.copy2(_find(inner, name), target / name)
        created.append(target / name)
    # Каталог "lua" в архиве неоднозначен: репозиторий держит зеркало тестов
    # `tests/lua/` (файлы .py) на той же глубине, что и настоящий `src/lua/`.
    # `_find(inner, "lua")` может выбрать любой из двух — привязываемся к
    # settings.lua, который существует только в настоящих исходниках.
    lua_source = _find(inner, "settings.lua").parent
    shutil.copytree(lua_source, target / "src" / "lua")
    created.append(target / "src" / "lua")
    return created


def _archive_root(unpacked: Path) -> Path:
    """Архивы исходников GitHub кладут всё в один каталог со случайным именем."""
    entries = [item for item in unpacked.iterdir() if item.is_dir()]
    if len(entries) == 1:
        return entries[0]
    return unpacked


def components() -> tuple[Component, ...]:
    """Из чего состоит установка, в порядке применения."""
    return (
        Component(
            name="Lovely Injector",
            repo="ethangreen-dev/lovely-injector",
            purpose="внедряет Lua в игру — без него моды не загружаются",
            place=_place_lovely,
            asset=_lovely_asset,
            expect=("liblovely.dylib",),
            expect_root="game",
        ),
        Component(
            name="Steamodded",
            repo="Steamodded/smods",
            purpose="загрузчик модов",
            place=_place_steamodded,
            expect=("smods",),
        ),
        Component(
            name="BalatroBot",
            repo="coder/balatrobot",
            purpose="отдаёт состояние игры наружу по JSON-RPC",
            place=_place_balatrobot,
            expect=("balatrobot/balatrobot.lua", "balatrobot/src/lua"),
        ),
    )


# ---------------------------------------------------------------------------
# Установка
# ---------------------------------------------------------------------------


@dataclass
class Step:
    """Что будет сделано с одним компонентом."""

    component: Component
    tag: str
    filename: str
    url: str


def architecture() -> str:
    """`arm64` для Apple Silicon, `x86_64` для Intel."""
    machine = platform.machine().lower()
    return "arm64" if machine in {"arm64", "aarch64"} else "x86_64"


def plan(fetcher: Fetcher, arch: str, chosen: Sequence[Component] | None = None) -> list[Step]:
    """Узнать, что именно будет скачано. Ничего не меняет на диске."""
    steps: list[Step] = []
    for component in chosen if chosen is not None else components():
        url = f"https://api.github.com/repos/{component.repo}/releases/latest"
        try:
            release = fetcher.json(url)
        except (OSError, ValueError) as error:
            raise InstallError(
                f"не удалось узнать последний релиз {component.name}: {error}. "
                f"Проверь сеть или поставь вручную: https://github.com/{component.repo}/releases"
            ) from error

        if not isinstance(release, dict):
            raise InstallError(f"GitHub вернул неожиданный ответ про {component.name}")
        tag = str(release.get("tag_name", "?"))
        if component.asset is None:
            zipball = release.get("zipball_url")
            if not zipball:
                raise InstallError(f"в релизе {component.name} нет архива исходников")
            steps.append(Step(component, tag, f"{component.repo.split('/')[-1]}.zip", str(zipball)))
        else:
            name, download = component.asset(release.get("assets") or [], arch)
            steps.append(Step(component, tag, name, download))
    return steps


def verify(paths: Paths, chosen: Sequence[Component] | None = None) -> dict[str, bool]:
    """Проверить, что всё на месте. Ключ — путь, значение — существует ли."""
    report: dict[str, bool] = {}
    for component in chosen if chosen is not None else components():
        for relative in component.expect:
            root = paths.game if component.expect_root == "game" else paths.mods
            target = root / relative
            report[str(target)] = target.exists()
    return report


@dataclass
class InstallResult:
    """Итог установки."""

    steps: list[Step] = field(default_factory=list)
    created: list[Path] = field(default_factory=list)
    report: dict[str, bool] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.report) and all(self.report.values())


def install(
    paths: Paths,
    fetcher: Fetcher,
    workdir: Path,
    arch: str,
    chosen: Sequence[Component] | None = None,
) -> InstallResult:
    """Скачать и разложить всё по местам."""
    steps = plan(fetcher, arch, chosen)
    result = InstallResult(steps=steps)

    for step in steps:
        archive = workdir / step.filename
        fetcher.download(step.url, archive)
        unpacked = _unpack(archive, workdir / f"{step.component.repo.replace('/', '_')}-out")
        result.created.extend(step.component.place(unpacked, paths))

    result.report = verify(paths, chosen)
    return result


def clear_quarantine(path: Path) -> bool:
    """Снять карантин macOS со скачанного файла.

    Библиотеку, скачанную из сети, система помечает и может отказаться
    загружать. Снятие метки — штатная операция, но если утилиты `xattr` нет
    (например, мы не на macOS), молча ничего не делаем: это не повод
    заваливать установку.
    """
    if platform.system() != "Darwin" or not path.exists():
        return False
    try:
        subprocess.run(
            ["xattr", "-d", "com.apple.quarantine", str(path)],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True
