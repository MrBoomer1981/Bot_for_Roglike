"""Тесты живого окна советника (`balatro-bot watch`).

Фальшивый мод отдаёт одно и то же состояние на каждый запрос, поэтому
«состояние не изменилось» проверяется прогоном нескольких опросов подряд.
Смену состояния имитирует сам `sleep`: он подменяется на функцию, которая
между опросами переписывает `FakeMod.state`, — так тест не ждёт реальное
время и не зависит от таймингов.
"""

from __future__ import annotations

from typing import Any

import pytest

from balatro_bot.adapters.mod_bridge import ModBridge, parse_game_state
from balatro_bot.autopilot import decide_action
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

    def test_единый_список_включает_сбросы(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tui.watch(bridge, iterations=1, sleep=lambda _: None)
        assert "сбросить" in capsys.readouterr().out

    def test_можно_отключить_рассмотрение_сбросов(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tui.watch(bridge, iterations=1, sleep=lambda _: None, consider_discards=False)
        assert "сбросить" not in capsys.readouterr().out

    def test_без_сбросов_вариантов_сброса_в_списке_нет(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        no_discards = sample_state()
        no_discards["round"]["discards_left"] = 0
        FakeMod.state = no_discards

        tui.watch(bridge, iterations=1, sleep=lambda _: None)
        assert "сбросить" not in capsys.readouterr().out

    def test_показывает_совет_по_магазину(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        state = sample_state()
        state["shop"] = {
            "count": 1,
            "limit": 2,
            "cards": [
                {
                    "id": 1,
                    "key": "j_joker",
                    "set": "JOKER",
                    "label": "Joker",
                    "value": {"effect": "+4 Mult"},
                    "modifier": {"seal": None, "edition": None, "enhancement": None},
                    "state": {"debuff": False, "hidden": False, "highlight": False},
                    "cost": {"sell": 1, "buy": 3},
                }
            ],
        }
        FakeMod.state = state

        tui.watch(bridge, iterations=1, sleep=lambda _: None)
        out = capsys.readouterr().out
        assert "магазин" in out
        assert "Joker" in out

    def test_можно_отключить_совет_по_магазину(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        state = sample_state()
        state["shop"] = {
            "count": 1,
            "limit": 2,
            "cards": [
                {
                    "id": 1,
                    "key": "j_joker",
                    "set": "JOKER",
                    "label": "Joker",
                    "value": {"effect": "+4 Mult"},
                    "modifier": {"seal": None, "edition": None, "enhancement": None},
                    "state": {"debuff": False, "hidden": False, "highlight": False},
                    "cost": {"sell": 1, "buy": 3},
                }
            ],
        }
        FakeMod.state = state

        tui.watch(bridge, iterations=1, sleep=lambda _: None, consider_shop=False)
        assert "магазин" not in capsys.readouterr().out

    def test_без_магазина_совет_не_показывается(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tui.watch(bridge, iterations=1, sleep=lambda _: None)
        assert "магазин" not in capsys.readouterr().out

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


def _state_jokers_already_ordered() -> dict[str, Any]:
    """`sample_state()`, но джокеры уже в лучшем порядке (`Blueprint` перед
    `Joker`) — иначе автопилот сперва делает `rearrange` (улучшение D1), и
    тесты «первое действие — розыгрыш/сброс» не про то ловят."""
    state = sample_state()
    state["jokers"]["cards"] = list(reversed(state["jokers"]["cards"]))
    return state


class TestAutoplay:
    """`balatro-bot autoplay` — Фаза 9, п. 9.1 (узкий срез: только
    `SELECTING_HAND`). Фальшивый мод не симулирует реальный розыгрыш — на
    любой вызов отвечает тем же `FakeMod.state`, — поэтому проверяется не
    смена состояния, а сам факт и содержимое RPC-вызова (`FakeMod.calls`)."""

    def test_по_умолчанию_играет_сам(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        FakeMod.state = _state_jokers_already_ordered()
        tui.autoplay(bridge, iterations=1, sleep=lambda _: None, key_reader=lambda: None)
        методы = [call["method"] for call in FakeMod.calls]
        assert "play" in методы or "discard" in методы
        out = capsys.readouterr().out
        assert "автопилот" in out
        assert "АВТОПИЛОТ" in out

    def test_пауза_останавливает_действия(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tui.autoplay(bridge, iterations=1, sleep=lambda _: None, key_reader=lambda: "p")
        методы = [call["method"] for call in FakeMod.calls]
        assert "play" not in методы
        assert "discard" not in методы
        out = capsys.readouterr().out
        assert "ПАУЗА" in out

    def test_снятие_паузы_возвращает_действия(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        FakeMod.state = _state_jokers_already_ordered()
        # Первое нажатие 'p' ставит на паузу, второе — снимает.
        нажатия = iter(["p", "p"])
        tui.autoplay(
            bridge,
            iterations=2,
            sleep=lambda _: None,
            key_reader=lambda: next(нажатия, None),
        )
        методы = [call["method"] for call in FakeMod.calls]
        assert "play" in методы or "discard" in методы

    def test_не_selecting_hand_не_действует(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        shop_state = sample_state()
        shop_state["state"] = "SHOP"
        FakeMod.state = shop_state

        tui.autoplay(bridge, iterations=1, sleep=lambda _: None, key_reader=lambda: None)
        методы = [call["method"] for call in FakeMod.calls]
        assert "play" not in методы
        assert "discard" not in методы

    def test_отказ_мода_не_роняет_цикл(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        action = decide_action(parse_game_state(sample_state()))
        assert action is not None
        FakeMod.error_for = action.kind

        tui.autoplay(bridge, iterations=1, sleep=lambda _: None, key_reader=lambda: None)
        out = capsys.readouterr().out
        assert "мод отказал в ходе" in out

    def test_на_выборе_блайнда_скипает_ради_доказанного_тега(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        state = sample_state()
        state["state"] = "BLIND_SELECT"
        state["blinds"]["big"]["status"] = "SELECT"
        state["blinds"]["big"]["tag_name"] = "Investment Tag"
        FakeMod.state = state

        tui.autoplay(bridge, iterations=1, sleep=lambda _: None, key_reader=lambda: None)
        методы = [call["method"] for call in FakeMod.calls]
        assert "skip" in методы
        assert "select" not in методы
        out = capsys.readouterr().out
        assert "скипнул блайнд" in out

    def test_на_выборе_блайнда_играет_без_оценимого_тега(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # `Handy Tag` не оценивается ни на одном из трёх уровней A14 —
        # его формула требует счётчика уровня рана, которого мод не шлёт.
        # (`Rare Tag` тут стоял до A14 и теперь оценивается структурно.)
        state = sample_state()
        state["state"] = "BLIND_SELECT"
        state["blinds"]["big"]["status"] = "SELECT"
        state["blinds"]["big"]["tag_name"] = "Handy Tag"
        FakeMod.state = state

        tui.autoplay(bridge, iterations=1, sleep=lambda _: None, key_reader=lambda: None)
        методы = [call["method"] for call in FakeMod.calls]
        assert "select" in методы
        assert "skip" not in методы
        out = capsys.readouterr().out
        assert "выбрал блайнд" in out

    def test_на_round_eval_забирает_награду(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        state = sample_state()
        state["state"] = "ROUND_EVAL"
        FakeMod.state = state

        tui.autoplay(bridge, iterations=1, sleep=lambda _: None, key_reader=lambda: None)
        методы = [call["method"] for call in FakeMod.calls]
        assert "cash_out" in методы
        out = capsys.readouterr().out
        assert "забрал награду" in out

    def test_в_магазине_покупает_доступного_джокера(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        state = sample_state()
        state["state"] = "SHOP"
        state["shop"] = {
            "count": 1,
            "limit": 2,
            "cards": [
                {
                    "id": 1,
                    "key": "j_joker",
                    "set": "JOKER",
                    "label": "Joker",
                    "value": {"effect": "+4 Mult"},
                    "modifier": {"seal": None, "edition": None, "enhancement": None},
                    "state": {"debuff": False, "hidden": False, "highlight": False},
                    "cost": {"sell": 1, "buy": 3},
                }
            ],
        }
        FakeMod.state = state

        tui.autoplay(bridge, iterations=1, sleep=lambda _: None, key_reader=lambda: None)
        методы = [call["method"] for call in FakeMod.calls]
        assert "buy" in методы
        buy_call = next(call for call in FakeMod.calls if call["method"] == "buy")
        assert buy_call["params"] == {"card": 0}
        out = capsys.readouterr().out
        assert "купил в магазине: Joker" in out

    def test_в_магазине_без_покупок_уходит(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        state = sample_state()
        state["state"] = "SHOP"
        FakeMod.state = state

        tui.autoplay(bridge, iterations=1, sleep=lambda _: None, key_reader=lambda: None)
        методы = [call["method"] for call in FakeMod.calls]
        assert "next_round" in методы
        assert "buy" not in методы
        out = capsys.readouterr().out
        assert "ушёл из магазина" in out

    def test_planet_консумабль_используется_раньше_розыгрыша(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        state = sample_state()
        state["consumables"] = {
            "count": 1,
            "limit": 2,
            "cards": [
                {
                    "id": 5,
                    "key": "c_mercury",
                    "set": "PLANET",
                    "label": "Mercury",
                    "value": {"effect": "Increases Pair hand value by +1 Mult and +15 Chips"},
                    "modifier": {"seal": None, "edition": None, "enhancement": None},
                    "state": {"debuff": False, "hidden": False, "highlight": False},
                    "cost": {"sell": 0, "buy": 0},
                }
            ],
        }
        FakeMod.state = state

        tui.autoplay(bridge, iterations=1, sleep=lambda _: None, key_reader=lambda: None)
        методы = [call["method"] for call in FakeMod.calls]
        assert "use" in методы
        assert "play" not in методы
        use_call = next(call for call in FakeMod.calls if call["method"] == "use")
        assert use_call["params"] == {"consumable": 0}
        out = capsys.readouterr().out
        assert "использовал консумабль: Mercury" in out

    def test_на_вскрытии_пака_берёт_лучшую_планету(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        state = sample_state()
        state["state"] = "PLANET_PACK"
        state["pack"] = {
            "count": 1,
            "limit": 3,
            "cards": [
                {
                    "id": 1,
                    "key": "c_mercury",
                    "set": "PLANET",
                    "label": "Mercury",
                    "value": {"effect": "Increases Pair hand value by +1 Mult and +15 Chips"},
                    "modifier": {"seal": None, "edition": None, "enhancement": None},
                    "state": {"debuff": False, "hidden": False, "highlight": False},
                    "cost": {"sell": 0, "buy": 0},
                }
            ],
        }
        FakeMod.state = state

        tui.autoplay(bridge, iterations=1, sleep=lambda _: None, key_reader=lambda: None)
        методы = [call["method"] for call in FakeMod.calls]
        assert "pack" in методы
        pack_call = next(call for call in FakeMod.calls if call["method"] == "pack")
        assert pack_call["params"] == {"card": 0}
        out = capsys.readouterr().out
        assert "взял из пака: Mercury" in out

    def test_на_вскрытии_пака_без_опознанных_планет_скипает(
        self, bridge: ModBridge, capsys: pytest.CaptureFixture[str]
    ) -> None:
        state = sample_state()
        state["state"] = "PLANET_PACK"
        state["pack"] = {
            "count": 1,
            "limit": 3,
            "cards": [
                {
                    "id": 1,
                    "key": "c_совсем_новый",
                    "set": "PLANET",
                    "label": "???",
                    "value": {"effect": ""},
                    "modifier": {"seal": None, "edition": None, "enhancement": None},
                    "state": {"debuff": False, "hidden": False, "highlight": False},
                    "cost": {"sell": 0, "buy": 0},
                }
            ],
        }
        FakeMod.state = state

        tui.autoplay(bridge, iterations=1, sleep=lambda _: None, key_reader=lambda: None)
        pack_call = next(call for call in FakeMod.calls if call["method"] == "pack")
        assert pack_call["params"] == {"skip": True}
        out = capsys.readouterr().out
        assert "скипнул пак" in out
