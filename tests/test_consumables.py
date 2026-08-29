"""Тесты использования Planet-консумаблей перед розыгрышем
(`balatro_bot/solver/consumables.py`) — Фаза 9.4, первый (Planet) кусок.

Tarot-карты этот модуль сознательно не оценивает (см. модульный докстринг)."""

from __future__ import annotations

from dataclasses import replace

from balatro_bot.adapters.manual import build_state
from balatro_bot.core.hands import HandType
from balatro_bot.core.state import GameState, ShopItem
from balatro_bot.solver.consumables import evaluate_planet_consumables

#: Та же детерминированная рука без флеша/стрита/троек, что в
#: `tests/test_pack.py` — единственная собираемая рука сильнее хай-карты
#: здесь пара тузов.
_ПАРА_ТУЗОВ = "AH AS 2C 4D 6S 9H TC KD"


def _consumable_state(hand: str = _ПАРА_ТУЗОВ, **overrides: object) -> GameState:
    state = build_state(hand)
    return replace(state, phase="SELECTING_HAND", **overrides)  # type: ignore[arg-type]


class TestEvaluatePlanetConsumables:
    def test_не_selecting_hand_возвращает_пусто(self) -> None:
        state = _consumable_state(consumables=(ShopItem("c_mercury", "Mercury", "PLANET", 0),))
        state = replace(state, phase="SHOP")
        assert evaluate_planet_consumables(state) == ()

    def test_без_руки_возвращает_пусто(self) -> None:
        state = _consumable_state(
            hand="", consumables=(ShopItem("c_mercury", "Mercury", "PLANET", 0),)
        )
        assert evaluate_planet_consumables(state) == ()

    def test_подходящая_планета_даёт_положительный_прирост(self) -> None:
        state = _consumable_state(consumables=(ShopItem("c_mercury", "Mercury", "PLANET", 0),))
        offers = evaluate_planet_consumables(state)
        assert len(offers) == 1
        assert offers[0].hand_type is HandType.PAIR
        assert offers[0].expected_uplift > 0

    def test_недостижимая_планета_даёт_нулевой_прирост(self) -> None:
        # Флеш в этой руке не собрать никогда.
        state = _consumable_state(consumables=(ShopItem("c_jupiter", "Jupiter", "PLANET", 0),))
        offers = evaluate_planet_consumables(state)
        assert offers[0].expected_uplift == 0.0

    def test_неопознанная_карта_пропускается(self) -> None:
        state = _consumable_state(consumables=(ShopItem("c_совсем_новый", "???", "TAROT", 0),))
        assert evaluate_planet_consumables(state) == ()

    def test_сортировка_по_убыванию_прироста(self) -> None:
        state = _consumable_state(
            consumables=(
                ShopItem("c_jupiter", "Jupiter", "PLANET", 0),
                ShopItem("c_mercury", "Mercury", "PLANET", 0),
            )
        )
        offers = evaluate_planet_consumables(state)
        assert offers[0].hand_type is HandType.PAIR

    def test_observatory_добавляет_примечание(self) -> None:
        state = _consumable_state(
            consumables=(ShopItem("c_mercury", "Mercury", "PLANET", 0),),
            used_vouchers=frozenset({"v_observatory"}),
        )
        offers = evaluate_planet_consumables(state)
        assert "Observatory" in offers[0].note

    def test_без_observatory_нет_примечания(self) -> None:
        state = _consumable_state(consumables=(ShopItem("c_mercury", "Mercury", "PLANET", 0),))
        offers = evaluate_planet_consumables(state)
        assert offers[0].note == ""
