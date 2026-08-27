"""Тесты оценки выбора карты при вскрытии пака (`balatro_bot/solver/pack.py`).

Единственный проверяемый здесь случай — Celestial/Planet Pack (Фаза 9.2,
последний кусок): остальные типы паков (Arcana/Tarot, Spectral, Standard,
Buffoon) этот модуль сознательно не оценивает."""

from __future__ import annotations

from balatro_bot.core.cards import parse_cards
from balatro_bot.core.hands import HandType
from balatro_bot.core.state import GameState, ShopItem
from balatro_bot.solver.pack import PLANET_HAND_TYPES, evaluate_pack

#: Рука без флеша, стрита и троек — единственная собираемая рука сильнее
#: хай-карты это пара тузов, детерминированно и однозначно.
_ПАРА_ТУЗОВ = parse_cards("AH AS 2C 4D 6S 9H TC KD")


class TestТаблицаПланет:
    def test_все_12_типов_руки_покрыты_ровно_один_раз(self) -> None:
        assert len(PLANET_HAND_TYPES) == 12
        assert set(PLANET_HAND_TYPES.values()) == set(HandType)


class TestEvaluatePack:
    def test_не_planet_pack_возвращает_пусто(self) -> None:
        state = GameState(
            phase="SHOP",
            full_deck=_ПАРА_ТУЗОВ,
            pack=(ShopItem("c_mercury", "Mercury", "PLANET", 0),),
        )
        assert evaluate_pack(state) == ()

    def test_пустой_пак_возвращает_пусто(self) -> None:
        state = GameState(phase="PLANET_PACK", full_deck=_ПАРА_ТУЗОВ)
        assert evaluate_pack(state) == ()

    def test_неопознанная_карта_пропускается(self) -> None:
        state = GameState(
            phase="PLANET_PACK",
            full_deck=_ПАРА_ТУЗОВ,
            pack=(ShopItem("c_совсем_новый", "???", "PLANET", 0),),
        )
        assert evaluate_pack(state) == ()

    def test_подходящий_тип_руки_даёт_положительный_прирост(self) -> None:
        state = GameState(
            phase="PLANET_PACK",
            full_deck=_ПАРА_ТУЗОВ,
            pack=(
                ShopItem("c_mercury", "Mercury", "PLANET", 0),
                ShopItem("c_jupiter", "Jupiter", "PLANET", 0),
            ),
        )
        offers = evaluate_pack(state, samples=1)
        assert len(offers) == 2
        by_type = {offer.hand_type: offer for offer in offers}
        pair_uplift = by_type[HandType.PAIR].expected_uplift
        assert pair_uplift is not None
        assert pair_uplift > 0
        # Флеш в этой руке не собрать никогда — прокачка ничего не меняет.
        assert by_type[HandType.FLUSH].expected_uplift == 0.0

    def test_сортировка_по_убыванию_прироста(self) -> None:
        state = GameState(
            phase="PLANET_PACK",
            full_deck=_ПАРА_ТУЗОВ,
            pack=(
                ShopItem("c_jupiter", "Jupiter", "PLANET", 0),
                ShopItem("c_mercury", "Mercury", "PLANET", 0),
            ),
        )
        offers = evaluate_pack(state, samples=1)
        assert offers[0].hand_type is HandType.PAIR

    def test_маленькая_колода_честно_не_оценивает(self) -> None:
        state = GameState(
            phase="PLANET_PACK",
            full_deck=parse_cards("AH AS 2C"),
            pack=(ShopItem("c_mercury", "Mercury", "PLANET", 0),),
        )
        offers = evaluate_pack(state, samples=1)
        assert offers[0].expected_uplift is None

    def test_без_full_deck_использует_стандартную_колоду(self) -> None:
        state = GameState(
            phase="PLANET_PACK",
            pack=(ShopItem("c_mercury", "Mercury", "PLANET", 0),),
        )
        offers = evaluate_pack(state, samples=1)
        assert offers[0].exact_deck is False
        assert offers[0].expected_uplift is not None
