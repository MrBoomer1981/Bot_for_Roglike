"""Тесты живого окна советника (`balatro-bot watch`).

Фальшивый мод отдаёт одно и то же состояние на каждый запрос, поэтому
«состояние не изменилось» проверяется прогоном нескольких опросов подряд.
Смену состояния имитирует сам `sleep`: он подменяется на функцию, которая
между опросами переписывает `FakeMod.state`, — так тест не ждёт реальное
время и не зависит от таймингов.
"""

from __future__ import annotations

import pytest

from balatro_bot.adapters.mod_bridge import ModBridge
from balatro_bot.ui import tui
from tests.fake_mod import FakeMod, sample_state


class TestWatch:
    def test_показывает_состояние_и_совет(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tui.watch(bridge, iterations=1, sleep=lambda _: None)
        out = capsys.readouterr().out
        assert "AH KH QH" in out
        assert "pair" in out
        assert "4 352" in out

    def test_без_карт_в_руке_совет_не_считается(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        empty_hand = sample_state()
        empty_hand["hand"]["cards"] = []
        FakeMod.state = empty_hand

        tui.watch(bridge, iterations=1, sleep=lambda _: None)
        out = capsys.readouterr().out
        assert "рука:        —" in out
        assert "нужно набрать" not in out

    def test_не_перерисовывает_если_состояние_не_изменилось(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tui.watch(bridge, iterations=3, sleep=lambda _: None)
        out = capsys.readouterr().out
        assert out.count(tui._CLEAR) == 1

    def test_перерисовывает_при_смене_состояния(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        calls = 0

        def bump_money_once(_: float) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                changed = sample_state()
                changed["money"] = 999
                FakeMod.state = changed

        tui.watch(bridge, iterations=2, sleep=bump_money_once)
        out = capsys.readouterr().out
        assert out.count(tui._CLEAR) == 2
        assert "$999" in out

    def test_сообщает_если_мод_не_отвечает(self, capsys: pytest.CaptureFixture[str]) -> None:
        offline = ModBridge(port=1)
        tui.watch(offline, iterations=1, sleep=lambda _: None)
        assert "не отвечает" in capsys.readouterr().out

    def test_не_дублирует_сообщение_об_ошибке(self, capsys: pytest.CaptureFixture[str]) -> None:
        offline = ModBridge(port=1)
        tui.watch(offline, iterations=3, sleep=lambda _: None)
        out = capsys.readouterr().out
        assert out.count(tui._CLEAR) == 1

    def test_порядок_джокеров_проверяется_по_умолчанию(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # В отличие от `advise`, где `--joker-order` — опция, `watch` считает
        # порядок сам: живая сессия — как раз тот случай, где выгодно узнать
        # об этом сразу, а не когда игрок сам вспомнит про флаг.
        tui.watch(bridge, iterations=1, sleep=lambda _: None)
        assert "порядок джокеров" in capsys.readouterr().out

    def test_можно_отключить_порядок_джокеров(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tui.watch(bridge, iterations=1, sleep=lambda _: None, joker_order=False)
        assert "порядок джокеров" not in capsys.readouterr().out

    def test_показывает_совет_по_сбросу_одной_карты(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tui.watch(bridge, iterations=1, sleep=lambda _: None)
        assert "что выгоднее сбросить" in capsys.readouterr().out

    def test_можно_отключить_совет_по_сбросу(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tui.watch(bridge, iterations=1, sleep=lambda _: None, discard_tips=False)
        assert "что выгоднее сбросить" not in capsys.readouterr().out

    def test_без_сбросов_совет_не_считается(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        no_discards = sample_state()
        no_discards["round"]["discards_left"] = 0
        FakeMod.state = no_discards

        tui.watch(bridge, iterations=1, sleep=lambda _: None)
        assert "что выгоднее сбросить" not in capsys.readouterr().out

    def test_восстанавливается_после_обрыва_связи(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Первый опрос фальшивый мод бьёт ошибкой, второй — уже отвечает.
        # Переключение между ними делает сам `sleep`, вызываемый между опросами.
        FakeMod.error_for = "gamestate"

        def reconnect_once(_: float) -> None:
            FakeMod.error_for = None

        tui.watch(bridge, iterations=2, sleep=reconnect_once)
        out = capsys.readouterr().out
        assert "не отвечает" in out
        assert out.count(tui._CLEAR) == 2
