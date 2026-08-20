"""Тесты установщика.

Ни сети, ни macOS здесь нет, поэтому закачка подменяется, а архивы
собираются на месте. Смысл тот же, что и с фальшивым модом: к первому
запуску на настоящей машине вся раскладка уже отлажена, и остаётся
проверить только сеть и права доступа.
"""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path
from typing import Any

import pytest

from balatro_bot.install import (
    Fetcher,
    InstallError,
    components,
    find_game_dir,
    install,
    plan,
    resolve_paths,
    steam_libraries,
    verify,
)

STEAM = "Library/Application Support/Steam"


def сделать_дом(tmp_path: Path, *, вторая_библиотека: Path | None = None) -> Path:
    """Собрать подобие домашнего каталога macOS с установленной игрой."""
    home = tmp_path / "home"
    место = вторая_библиотека or (home / STEAM)
    игра = место / "steamapps" / "common" / "Balatro"
    (игра / "Balatro.app" / "Contents" / "MacOS").mkdir(parents=True)

    steamapps = home / STEAM / "steamapps"
    steamapps.mkdir(parents=True, exist_ok=True)
    (steamapps / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n'
        f'    "0"\n    {{\n        "path"\t\t"{home / STEAM}"\n    }}\n'
        f'    "1"\n    {{\n        "path"\t\t"{вторая_библиотека or home / STEAM}"\n    }}\n}}\n',
        encoding="utf-8",
    )
    return home


def собрать_архивы(tmp_path: Path) -> dict[str, Path]:
    """Поддельные релизы, повторяющие устройство настоящих."""
    склад = tmp_path / "releases"
    склад.mkdir()

    lovely = склад / "lovely-aarch64-apple-darwin.tar.gz"
    сырьё = tmp_path / "lovely-src"
    сырьё.mkdir()
    (сырьё / "liblovely.dylib").write_bytes(b"\xcf\xfa\xed\xfe fake dylib")
    (сырьё / "run_lovely_macos.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    with tarfile.open(lovely, "w:gz") as tar:
        for item in сырьё.iterdir():
            tar.add(item, arcname=item.name)

    smods = склад / "smods.zip"
    with zipfile.ZipFile(smods, "w") as zipped:
        zipped.writestr("Steamodded-smods-abc123/core/core.lua", "-- загрузчик")
        zipped.writestr("Steamodded-smods-abc123/version.lua", "-- версия")

    bot = склад / "balatrobot.zip"
    with zipfile.ZipFile(bot, "w") as zipped:
        zipped.writestr("coder-balatrobot-def456/balatrobot.json", "{}")
        zipped.writestr("coder-balatrobot-def456/balatrobot.lua", "-- точка входа")
        zipped.writestr("coder-balatrobot-def456/src/lua/settings.lua", "-- настройки")
        zipped.writestr("coder-balatrobot-def456/src/lua/core/server.lua", "-- сервер")

    return {"lovely": lovely, "smods": smods, "balatrobot": bot}


class ПоддельнаяЗакачка(Fetcher):
    """Отдаёт заранее собранные архивы вместо обращения к сети."""

    def __init__(self, архивы: dict[str, Path], *, без_маковских_сборок: bool = False) -> None:
        self.архивы = архивы
        self.без_маковских_сборок = без_маковских_сборок
        self.запросы: list[str] = []

    def json(self, url: str) -> Any:
        self.запросы.append(url)
        if "lovely-injector" in url:
            if self.без_маковских_сборок:
                return {
                    "tag_name": "0.8.0",
                    "assets": [
                        {"name": "lovely-x86_64-pc-windows-msvc.zip", "browser_download_url": "x"}
                    ],
                }
            return {
                "tag_name": "0.8.0",
                "assets": [
                    {
                        "name": "lovely-aarch64-apple-darwin.tar.gz",
                        "browser_download_url": "fake://lovely-arm",
                    },
                    {
                        "name": "lovely-x86_64-apple-darwin.tar.gz",
                        "browser_download_url": "fake://lovely-intel",
                    },
                ],
            }
        if "smods" in url:
            return {"tag_name": "1.0.0-beta", "zipball_url": "fake://smods"}
        return {"tag_name": "1.5.2", "zipball_url": "fake://balatrobot"}

    def download(self, url: str, target: Path) -> None:
        ключ = {
            "fake://lovely-arm": "lovely",
            "fake://lovely-intel": "lovely",
            "fake://smods": "smods",
            "fake://balatrobot": "balatrobot",
        }[url]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.архивы[ключ].read_bytes())


class TestПоискИгры:
    def test_находит_в_стандартном_месте(self, tmp_path: Path) -> None:
        home = сделать_дом(tmp_path)
        найдено = find_game_dir(home)
        assert найдено is not None
        assert найдено.name == "Balatro"

    def test_находит_на_другом_диске(self, tmp_path: Path) -> None:
        # Игры часто держат на внешнем диске: без разбора libraryfolders.vdf
        # установщик их не увидит.
        внешний = tmp_path / "Volumes" / "SSD" / "SteamLibrary"
        home = сделать_дом(tmp_path, вторая_библиотека=внешний)
        найдено = find_game_dir(home)
        assert найдено is not None
        assert внешний in найдено.parents

    def test_перечисляет_библиотеки(self, tmp_path: Path) -> None:
        внешний = tmp_path / "Volumes" / "SSD" / "SteamLibrary"
        home = сделать_дом(tmp_path, вторая_библиотека=внешний)
        assert внешний in steam_libraries(home)

    def test_без_игры_понятная_ошибка(self, tmp_path: Path) -> None:
        пусто = tmp_path / "пусто"
        пусто.mkdir()
        with pytest.raises(InstallError, match="--game-dir"):
            resolve_paths(пусто)

    def test_чужой_каталог_отвергается(self, tmp_path: Path) -> None:
        home = сделать_дом(tmp_path)
        не_игра = tmp_path / "просто-папка"
        не_игра.mkdir()
        with pytest.raises(InstallError, match=r"Balatro\.app"):
            resolve_paths(home, не_игра)

    def test_каталог_модов_рядом_с_сохранениями(self, tmp_path: Path) -> None:
        paths = resolve_paths(сделать_дом(tmp_path))
        assert paths.mods.name == "Mods"
        assert "Steam" not in str(paths.mods)


class TestПлан:
    def test_выбирает_сборку_под_apple_silicon(self, tmp_path: Path) -> None:
        шаги = plan(ПоддельнаяЗакачка(собрать_архивы(tmp_path)), "arm64")
        assert шаги[0].url == "fake://lovely-arm"

    def test_выбирает_сборку_под_intel(self, tmp_path: Path) -> None:
        шаги = plan(ПоддельнаяЗакачка(собрать_архивы(tmp_path)), "x86_64")
        assert шаги[0].url == "fake://lovely-intel"

    def test_версии_попадают_в_план(self, tmp_path: Path) -> None:
        шаги = plan(ПоддельнаяЗакачка(собрать_архивы(tmp_path)), "arm64")
        assert [шаг.tag for шаг in шаги] == ["0.8.0", "1.0.0-beta", "1.5.2"]

    def test_план_ничего_не_качает(self, tmp_path: Path) -> None:
        закачка = ПоддельнаяЗакачка(собрать_архивы(tmp_path))
        plan(закачка, "arm64")
        assert all(адрес.startswith("https://api.github.com") for адрес in закачка.запросы)

    def test_нет_маковской_сборки_объясняет_куда_идти(self, tmp_path: Path) -> None:
        закачка = ПоддельнаяЗакачка(собрать_архивы(tmp_path), без_маковских_сборок=True)
        with pytest.raises(InstallError, match=r"lovely-injector/releases"):
            plan(закачка, "arm64")

    def test_неизвестная_архитектура_откатывается_на_intel(self, tmp_path: Path) -> None:
        # На неизвестном процессоре сборка под Intel — разумный запасной путь:
        # Rosetta её отработает.
        шаги = plan(ПоддельнаяЗакачка(собрать_архивы(tmp_path)), "powerpc")
        assert шаги[0].url == "fake://lovely-intel"


class TestУстановка:
    def test_раскладывает_всё_по_местам(self, tmp_path: Path) -> None:
        home = сделать_дом(tmp_path)
        paths = resolve_paths(home)
        итог = install(
            paths, ПоддельнаяЗакачка(собрать_архивы(tmp_path)), tmp_path / "work", "arm64"
        )

        assert итог.ok
        assert (paths.game / "liblovely.dylib").is_file()
        assert (paths.mods / "smods" / "core" / "core.lua").is_file()
        assert (paths.mods / "balatrobot" / "balatrobot.lua").is_file()
        assert (paths.mods / "balatrobot" / "src" / "lua" / "core" / "server.lua").is_file()

    def test_библиотека_идёт_в_каталог_игры_а_не_модов(self, tmp_path: Path) -> None:
        # Именно на этом чаще всего спотыкаются при ручной установке.
        home = сделать_дом(tmp_path)
        paths = resolve_paths(home)
        install(paths, ПоддельнаяЗакачка(собрать_архивы(tmp_path)), tmp_path / "work", "arm64")
        assert not (paths.mods / "liblovely.dylib").exists()

    def test_скрипт_запуска_не_копируется(self, tmp_path: Path) -> None:
        # CLI мода внедряет библиотеку сам, скрипт не нужен.
        home = сделать_дом(tmp_path)
        paths = resolve_paths(home)
        install(paths, ПоддельнаяЗакачка(собрать_архивы(tmp_path)), tmp_path / "work", "arm64")
        assert not (paths.game / "run_lovely_macos.sh").exists()

    def test_каталог_со_случайным_именем_разворачивается(self, tmp_path: Path) -> None:
        # GitHub кладёт исходники в папку вида `Steamodded-smods-abc123`.
        home = сделать_дом(tmp_path)
        paths = resolve_paths(home)
        install(paths, ПоддельнаяЗакачка(собрать_архивы(tmp_path)), tmp_path / "work", "arm64")
        assert not list(paths.mods.glob("Steamodded-smods-*"))

    def test_повторная_установка_заменяет_прежнюю(self, tmp_path: Path) -> None:
        home = сделать_дом(tmp_path)
        paths = resolve_paths(home)
        архивы = собрать_архивы(tmp_path)

        install(paths, ПоддельнаяЗакачка(архивы), tmp_path / "work1", "arm64")
        мусор = paths.mods / "smods" / "старое.lua"
        мусор.write_text("остаток прошлой версии", encoding="utf-8")

        install(paths, ПоддельнаяЗакачка(архивы), tmp_path / "work2", "arm64")
        assert not мусор.exists()


class TestПроверка:
    def test_до_установки_ничего_нет(self, tmp_path: Path) -> None:
        paths = resolve_paths(сделать_дом(tmp_path))
        assert not any(verify(paths).values())

    def test_после_установки_всё_на_месте(self, tmp_path: Path) -> None:
        paths = resolve_paths(сделать_дом(tmp_path))
        install(paths, ПоддельнаяЗакачка(собрать_архивы(tmp_path)), tmp_path / "work", "arm64")
        assert all(verify(paths).values())

    def test_видит_пропажу_отдельного_файла(self, tmp_path: Path) -> None:
        paths = resolve_paths(сделать_дом(tmp_path))
        install(paths, ПоддельнаяЗакачка(собрать_архивы(tmp_path)), tmp_path / "work", "arm64")
        (paths.game / "liblovely.dylib").unlink()

        отчёт = verify(paths)
        assert not all(отчёт.values())
        assert отчёт[str(paths.game / "liblovely.dylib")] is False


class TestБезопасность:
    def test_архив_не_может_писать_наружу(self, tmp_path: Path) -> None:
        home = сделать_дом(tmp_path)
        paths = resolve_paths(home)
        архивы = собрать_архивы(tmp_path)

        # Подменяем архив загрузчика на злонамеренный.
        вредный = tmp_path / "releases" / "smods.zip"
        with zipfile.ZipFile(вредный, "w") as zipped:
            zipped.writestr("../../захвачено.lua", "-- запись мимо каталога")
        архивы["smods"] = вредный

        with pytest.raises(InstallError, match="подозрительный путь"):
            install(paths, ПоддельнаяЗакачка(архивы), tmp_path / "work", "arm64")
        assert not (tmp_path / "захвачено.lua").exists()

    def test_компоненты_описаны_и_объяснены(self) -> None:
        for component in components():
            assert component.purpose
            assert component.expect


class TestРегрессииУстановщика:
    def test_неожиданный_ответ_github_не_роняет(self, tmp_path: Path) -> None:
        class ЧужойОтвет(ПоддельнаяЗакачка):
            def json(self, url: str) -> Any:
                return {"message": "API rate limit exceeded"}

        with pytest.raises(InstallError):
            plan(ЧужойОтвет(собрать_архивы(tmp_path)), "arm64")

    def test_не_json_не_роняет(self, tmp_path: Path) -> None:
        class Мусор(ПоддельнаяЗакачка):
            def json(self, url: str) -> Any:
                raise ValueError("Expecting value: line 1 column 1")

        with pytest.raises(InstallError, match="поставь вручную"):
            plan(Мусор(собрать_архивы(tmp_path)), "arm64")

    def test_берётся_ближайший_к_корню_каталог(self, tmp_path: Path) -> None:
        # В архиве может оказаться вложенный каталог с тем же именем.
        # Брать первый попавшийся от обхода — значит зависеть от порядка файлов.
        архивы = собрать_архивы(tmp_path)
        подмена = tmp_path / "releases" / "balatrobot.zip"
        with zipfile.ZipFile(подмена, "w") as zipped:
            zipped.writestr("coder-balatrobot-def456/vendor/deep/lua/чужое.lua", "-- не то")
            zipped.writestr("coder-balatrobot-def456/balatrobot.json", "{}")
            zipped.writestr("coder-balatrobot-def456/balatrobot.lua", "-- точка входа")
            zipped.writestr("coder-balatrobot-def456/src/lua/settings.lua", "-- настройки")
            zipped.writestr("coder-balatrobot-def456/src/lua/core/server.lua", "-- сервер")
        архивы["balatrobot"] = подмена

        home = сделать_дом(tmp_path)
        paths = resolve_paths(home)
        install(paths, ПоддельнаяЗакачка(архивы), tmp_path / "work", "arm64")

        assert (paths.mods / "balatrobot" / "src" / "lua" / "core" / "server.lua").is_file()

    def test_каталог_lua_не_путается_с_тестовым_зеркалом(self, tmp_path: Path) -> None:
        # Найдено вживую: у coder/balatrobot есть tests/lua/ (Python-зеркало
        # тестов) на той же глубине, что и настоящий src/lua/. Поиск по
        # имени каталога "lua" в этом случае неоднозначен — установщик ловил
        # тестовое зеркало вместо исходников, и игра падала на старте.
        архивы = собрать_архивы(tmp_path)
        подмена = tmp_path / "releases" / "balatrobot.zip"
        with zipfile.ZipFile(подмена, "w") as zipped:
            zipped.writestr("coder-balatrobot-def456/balatrobot.json", "{}")
            zipped.writestr("coder-balatrobot-def456/balatrobot.lua", "-- точка входа")
            zipped.writestr("coder-balatrobot-def456/tests/lua/core/test_server.py", "# тест")
            zipped.writestr("coder-balatrobot-def456/src/lua/core/server.lua", "-- сервер")
            zipped.writestr("coder-balatrobot-def456/src/lua/settings.lua", "-- настройки")
        архивы["balatrobot"] = подмена

        home = сделать_дом(tmp_path)
        paths = resolve_paths(home)
        install(paths, ПоддельнаяЗакачка(архивы), tmp_path / "work", "arm64")

        целевой = paths.mods / "balatrobot" / "src" / "lua"
        assert (целевой / "settings.lua").is_file()
        assert (целевой / "core" / "server.lua").is_file()
        assert not list(целевой.rglob("*.py"))
