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
