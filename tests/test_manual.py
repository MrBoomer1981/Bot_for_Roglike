"""Тесты ручного ввода состояния."""

from __future__ import annotations

import pytest

from balatro_bot.adapters.manual import build_state, parse_joker, parse_jokers
from balatro_bot.core.hands import HandType


class TestРазборДжокеров:
    def test_по_внутреннему_ключу(self) -> None:
        assert parse_joker("j_blueprint").key == "j_blueprint"

    def test_по_человеческому_названию(self) -> None:
        assert parse_joker("blueprint").key == "j_blueprint"

    def test_составное_название(self) -> None:
        assert parse_joker("greedy joker").key == "j_greedy_joker"

    def test_через_дефис_тоже_понимается(self) -> None:
        assert parse_joker("greedy-joker").key == "j_greedy_joker"

    def test_регистр_не_важен(self) -> None:
        assert parse_joker("BluePrint").key == "j_blueprint"

    def test_опечатка_подсказывает_похожее(self) -> None:
        with pytest.raises(ValueError, match="blueprint"):
            parse_joker("bluprint")

    def test_полная_бессмыслица_отвергается(self) -> None:
        with pytest.raises(ValueError, match="неизвестный джокер"):
            parse_joker("щщщщщ")

    def test_порядок_джокеров_сохраняется(self) -> None:
        джокеры = parse_jokers(["blueprint", "joker"])
        assert [joker.key for joker in джокеры] == ["j_blueprint", "j_joker"]

    def test_пустые_элементы_пропускаются(self) -> None:
        assert len(parse_jokers(["joker", "", "  "])) == 1


class TestСборкаСостояния:
    def test_рука_разбирается(self) -> None:
        state = build_state("AH KH QH JH 9H")
        assert len(state.hand) == 5

    def test_блайнд_необязателен(self) -> None:
        assert build_state("AH KH").blind is None

    def test_блайнд_задаётся(self) -> None:
        blind = build_state("AH KH", blind=450).blind
        assert blind is not None
        assert blind.required_score == 450

    def test_без_уровней_расчёт_неточен(self) -> None:
        assert not build_state("AH KH").has_authoritative_hand_values

    def test_уровни_рук_учитываются(self) -> None:
        state = build_state("AH AD", hand_levels={HandType.PAIR: 3})
        assert state.has_authoritative_hand_values
        assert state.hand_info[HandType.PAIR].level == 3
        # Третий уровень должен давать больше первого.
        assert state.hand_values(HandType.PAIR).chips > 10

    def test_ресурсы_раунда_переносятся(self) -> None:
        state = build_state("AH KH", hands_left=3, discards_left=2, money=12, chips_scored=100)
        assert (state.hands_left, state.discards_left) == (3, 2)
        assert (state.money, state.chips_scored) == (12, 100)
