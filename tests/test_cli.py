"""Тесты командной строки.

Проверяется то, что человек увидит на Mac: понятная диагностика, когда игра
не запущена, и честное предупреждение, когда состояние опознано не полностью.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from balatro_bot import cli
from tests.fake_mod import FakeMod, sample_state


class TestDoctor:
    def test_успех_возвращает_ноль(self, fake_mod_port: int) -> None:
        assert cli.main(["--port", str(fake_mod_port), "doctor"]) == 0

    def test_показывает_руку_и_блайнд(
        self, fake_mod_port: int, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli.main(["--port", str(fake_mod_port), "doctor"])
        out = capsys.readouterr().out
        assert "AH KH QH" in out
        assert "Big Blind" in out
        assert "нужно 450" in out

    def test_сообщает_что_значения_рук_от_игры(
        self, fake_mod_port: int, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli.main(["--port", str(fake_mod_port), "doctor"])
        assert "значения рук: от игры" in capsys.readouterr().out

    def test_показывает_уровень_прокачанной_руки(
        self, fake_mod_port: int, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # В эталонной фикстуре Pair уже второго уровня.
        cli.main(["--port", str(fake_mod_port), "doctor"])
        assert "уровни рук выше первого: pair ур.2" in capsys.readouterr().out

    def test_предупреждает_о_незнакомом_джокере(
        self, fake_mod_port: int, capsys: pytest.CaptureFixture[str]
    ) -> None:
        state = sample_state()
        state["jokers"]["cards"].append(
            {"key": "j_модовый", "label": "Из мода", "modifier": {}, "state": {}}
        )
        FakeMod.state = state

        cli.main(["--port", str(fake_mod_port), "doctor"])
        out = capsys.readouterr().out
        assert "НЕТОЧНЫМ" in out
        assert "joker:j_модовый" in out

    def test_без_игры_объясняет_что_делать(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["--port", "1", "doctor"]) == 1
        out = capsys.readouterr().out
        assert "uvx balatrobot serve" in out


class TestRecord:
    def test_записывает_состояние(
        self, fake_mod_port: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli, "GOLDEN_DIR", tmp_path / "golden")

        assert cli.main(["--port", str(fake_mod_port), "record", "проба"]) == 0

        files = list((tmp_path / "golden").glob("*-проба.json"))
        assert len(files) == 1
        saved = json.loads(files[0].read_text(encoding="utf-8"))
        assert saved["state"] == "SELECTING_HAND"

    def test_напоминает_дописать_счёт(
        self,
        fake_mod_port: int,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(cli, "GOLDEN_DIR", tmp_path / "golden")
        cli.main(["--port", str(fake_mod_port), "record", "проба"])
        assert "счёт" in capsys.readouterr().out

    def test_без_игры_не_создаёт_файл(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli, "GOLDEN_DIR", tmp_path / "golden")
        assert cli.main(["--port", "1", "record", "проба"]) == 1
        assert not (tmp_path / "golden").exists()


class TestAdvise:
    def test_ручная_рука_считается_без_игры(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["advise", "--hand", "AH KH QH JH 9H"]) == 0
        assert "flush" in capsys.readouterr().out

    def test_показывает_ранжированный_список(self, capsys: pytest.CaptureFixture[str]) -> None:
        cli.main(["advise", "--hand", "AH KH QH JH 9H 7C 7D 2S", "--top", "3"])
        строки = [s for s in capsys.readouterr().out.splitlines() if s.startswith("  ")]
        assert len([s for s in строки if s.strip()[0].isdigit()]) == 3

    def test_отмечает_достаточные_ходы(self, capsys: pytest.CaptureFixture[str]) -> None:
        cli.main(["advise", "--hand", "8H 8D 8C 2S 3D", "--blind", "50"])
        out = capsys.readouterr().out
        assert "нужно набрать: 50" in out
        assert "хватает" in out

    def test_предлагает_экономный_вариант(self, capsys: pytest.CaptureFixture[str]) -> None:
        cli.main(["advise", "--hand", "8H 8D 8C 2S 3D", "--blind", "50"])
        assert "хватит и меньшего" in capsys.readouterr().out

    def test_сообщает_если_не_хватает(self, capsys: pytest.CaptureFixture[str]) -> None:
        cli.main(["advise", "--hand", "2H 3D 4C 5S 7D", "--blind", "999999"])
        assert "ни один ход не перебивает" in capsys.readouterr().out

    def test_джокеры_учитываются(self, capsys: pytest.CaptureFixture[str]) -> None:
        без = cli.main(["advise", "--hand", "AH AD", "--top", "1"])
        первый = capsys.readouterr().out
        с_джокером = cli.main(["advise", "--hand", "AH AD", "--jokers", "joker", "--top", "1"])
        второй = capsys.readouterr().out
        assert без == с_джокером == 0
        assert первый != второй

    def test_опечатка_в_джокере_подсказывает(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["advise", "--hand", "AH AD", "--jokers", "bluprint"]) == 2
        assert "blueprint" in capsys.readouterr().out

    def test_разбор_по_флагу(self, capsys: pytest.CaptureFixture[str]) -> None:
        cli.main(["advise", "--hand", "AH AD", "--jokers", "scholar", "--explain"])
        out = capsys.readouterr().out
        assert "разбор варианта" in out
        assert "scholar" in out

    def test_предупреждает_о_неточности(self, capsys: pytest.CaptureFixture[str]) -> None:
        cli.main(["advise", "--hand", "AH AD", "--jokers", "cavendish"])
        assert "НЕТОЧНЫЕ" in capsys.readouterr().out

    def test_берёт_руку_из_игры(
        self, fake_mod_port: int, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["--port", str(fake_mod_port), "advise", "--top", "2"]) == 0
        assert "AH KH QH" in capsys.readouterr().out

    def test_без_игры_предлагает_ручной_режим(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["--port", "1", "advise"]) == 1
        assert "--hand" in capsys.readouterr().out


class TestInstall:
    """Установщик через командную строку.

    Сети нет, поэтому закачка подменяется теми же поддельными архивами,
    что и в тестах самого установщика.
    """

    @staticmethod
    def _подготовить(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, с_закачкой: bool = True
    ) -> Path:
        from tests.test_install import ПоддельнаяЗакачка, сделать_дом, собрать_архивы

        home = сделать_дом(tmp_path)
        monkeypatch.setattr("pathlib.Path.home", staticmethod(lambda: home))
        if с_закачкой:
            архивы = собрать_архивы(tmp_path)
            monkeypatch.setattr(
                "balatro_bot.cli.UrlFetcher", lambda *a, **k: ПоддельнаяЗакачка(архивы)
            )
        return home

    def test_проверка_сообщает_чего_не_хватает(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._подготовить(tmp_path, monkeypatch, с_закачкой=False)
        assert cli.main(["install", "--check", "--force"]) == 1
        out = capsys.readouterr().out
        assert "НЕТ" in out
        assert "balatro-bot install" in out

    def test_показ_плана_ничего_не_меняет(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = self._подготовить(tmp_path, monkeypatch)
        assert cli.main(["install", "--dry-run", "--force"]) == 0
        out = capsys.readouterr().out
        assert "будет скачано" in out
        assert "ничего не скачано" in out
        assert not (home / "Library/Application Support/Balatro/Mods").exists()

    def test_план_называет_адреса_и_назначение(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Установка трогает чужую машину, поэтому список источников
        # показывается до, а не после.
        self._подготовить(tmp_path, monkeypatch)
        cli.main(["install", "--dry-run", "--force"])
        out = capsys.readouterr().out
        assert "откуда:" in out
        assert "зачем:" in out

    def test_установка_раскладывает_файлы(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = self._подготовить(tmp_path, monkeypatch)
        assert cli.main(["install", "--force", "--yes"]) == 0

        моды = home / "Library/Application Support/Balatro/Mods"
        assert (моды / "smods").is_dir()
        assert (моды / "balatrobot" / "balatrobot.lua").is_file()
        assert "uvx balatrobot serve" in capsys.readouterr().out

    def test_без_подтверждения_отменяется(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = self._подготовить(tmp_path, monkeypatch)
        monkeypatch.setattr("builtins.input", lambda *_: "n")

        assert cli.main(["install", "--force"]) == 1
        assert "отменено" in capsys.readouterr().out
        assert not (home / "Library/Application Support/Balatro/Mods").exists()

    def test_подтверждение_принимается(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = self._подготовить(tmp_path, monkeypatch)
        monkeypatch.setattr("builtins.input", lambda *_: "да")

        assert cli.main(["install", "--force"]) == 0
        assert (home / "Library/Application Support/Balatro/Mods" / "smods").is_dir()

    def test_не_на_маке_без_force_отказывается(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr("platform.system", lambda: "Linux")
        assert cli.main(["install"]) == 2
        assert "--force" in capsys.readouterr().out

    def test_без_игры_объясняет_как_быть(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        пусто = tmp_path / "пусто"
        пусто.mkdir()
        monkeypatch.setattr("pathlib.Path.home", staticmethod(lambda: пусто))
        assert cli.main(["install", "--check", "--force"]) == 1
        assert "--game-dir" in capsys.readouterr().out


class TestРегрессииВыводе:
    """Мелочи, на которых вывод уже ломался."""

    def test_steel_и_stone_различаются(self) -> None:
        # Обе начинаются на «s», и раньше обе печатались как (S). Путать их
        # нельзя: одно работает в руке, другое при розыгрыше.
        from balatro_bot.core.cards import Card, Enhancement, Rank, Suit

        steel = cli._format_card(Card(Rank.ACE, Suit.HEARTS, Enhancement.STEEL))
        stone = cli._format_card(Card(Rank.ACE, Suit.HEARTS, Enhancement.STONE))
        assert steel != stone

    def test_нулевой_top_не_роняет(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["advise", "--hand", "AH AD", "--top", "0"]) == 0
        assert "pair" in capsys.readouterr().out
