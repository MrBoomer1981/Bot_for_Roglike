"""Тесты распознавания покерных рук.

Здесь проверяется *логика*, а не таблицы значений: числа очков выписаны
по памяти и сверяются с игрой только в Фазе 3, поэтому утверждать про них
что-то конкретное было бы самообманом.
"""

from __future__ import annotations

import pytest

from balatro_bot.core.cards import Card, Enhancement, Rank, Suit, parse_cards
from balatro_bot.core.hands import (
    BASE_VALUES,
    HAND_VALUES_ARE_PROVISIONAL,
    PER_LEVEL_VALUES,
    HandModifiers,
    HandType,
    base_values,
    evaluate,
)

FOUR_FINGERS = HandModifiers(four_fingers=True)
SHORTCUT = HandModifiers(shortcut=True)
SMEARED = HandModifiers(smeared=True)


def stone() -> Card:
    return Card(Rank.SEVEN, Suit.CLUBS, Enhancement.STONE)


class TestБазовыеТипыРук:
    @pytest.mark.parametrize(
        ("cards", "expected", "scoring_count"),
        [
            ("AH KD 9C 7S 3H", HandType.HIGH_CARD, 1),
            ("AH AD 9C 7S 3H", HandType.PAIR, 2),
            ("AH AD 9C 9S 3H", HandType.TWO_PAIR, 4),
            ("AH AD AC 9S 3H", HandType.THREE_OF_A_KIND, 3),
            ("5H 6D 7C 8S 9H", HandType.STRAIGHT, 5),
            ("AH 9H 7H 5H 3H", HandType.FLUSH, 5),
            ("AH AD AC 9S 9H", HandType.FULL_HOUSE, 5),
            ("AH AD AC AS 9H", HandType.FOUR_OF_A_KIND, 4),
            ("5H 6H 7H 8H 9H", HandType.STRAIGHT_FLUSH, 5),
        ],
    )
    def test_распознаёт(self, cards: str, expected: HandType, scoring_count: int) -> None:
        result = evaluate(parse_cards(cards))
        assert result.hand_type is expected
        assert len(result.scoring_cards) == scoring_count


class TestСекретныеРуки:
    def test_пять_одинаковых(self) -> None:
        result = evaluate(parse_cards("AH AD AC AS AH"))
        assert result.hand_type is HandType.FIVE_OF_A_KIND
        assert len(result.scoring_cards) == 5

    def test_флеш_хаус(self) -> None:
        result = evaluate(parse_cards("AH AH AH 9H 9H"))
        assert result.hand_type is HandType.FLUSH_HOUSE
        assert len(result.scoring_cards) == 5

    def test_флеш_пятёрка(self) -> None:
        result = evaluate(parse_cards("AH AH AH AH AH"))
        assert result.hand_type is HandType.FLUSH_FIVE
        assert len(result.scoring_cards) == 5

    def test_пять_одинаковых_разных_мастей_не_флеш(self) -> None:
        assert evaluate(parse_cards("AH AD AC AS AH")).hand_type is HandType.FIVE_OF_A_KIND


class TestПограничныеСтриты:
    def test_туз_младший(self) -> None:
        assert evaluate(parse_cards("AH 2D 3C 4S 5H")).hand_type is HandType.STRAIGHT

    def test_туз_старший(self) -> None:
        assert evaluate(parse_cards("TH JD QC KS AH")).hand_type is HandType.STRAIGHT

    def test_через_туза_не_заворачивается(self) -> None:
        # Q-K-A-2-3 стритом не является ни при каком положении туза.
        assert evaluate(parse_cards("QH KD AC 2S 3H")).hand_type is HandType.HIGH_CARD

    def test_дырка_в_середине_не_стрит(self) -> None:
        assert evaluate(parse_cards("5H 6D 7C 9S TH")).hand_type is HandType.HIGH_CARD

    def test_младший_стрит_флеш(self) -> None:
        assert evaluate(parse_cards("AH 2H 3H 4H 5H")).hand_type is HandType.STRAIGHT_FLUSH


class TestFourFingers:
    def test_флеш_из_четырёх(self) -> None:
        cards = parse_cards("AH 9H 7H 5H 3C")
        assert evaluate(cards).hand_type is HandType.HIGH_CARD
        result = evaluate(cards, FOUR_FINGERS)
        assert result.hand_type is HandType.FLUSH
        assert len(result.scoring_cards) == 4

    def test_стрит_из_четырёх(self) -> None:
        cards = parse_cards("5H 6D 7C 8S KH")
        assert evaluate(cards).hand_type is HandType.HIGH_CARD
        result = evaluate(cards, FOUR_FINGERS)
        assert result.hand_type is HandType.STRAIGHT
        assert len(result.scoring_cards) == 4

    def test_пятая_карта_в_флеше_не_засчитывается(self) -> None:
        result = evaluate(parse_cards("AH 9H 7H 5H 3C"), FOUR_FINGERS)
        assert all(card.suit is Suit.HEARTS for card in result.scoring_cards)

    def test_флеш_и_стрит_на_разных_картах_не_дают_стрит_флеш(self) -> None:
        # Флеш собирают четыре червы (2,3,4,9), стрит — 2-3-4-5, но пятёрка треф.
        # Общих четырёх карт нет, значит стрит-флеша тоже нет.
        result = evaluate(parse_cards("2H 3H 4H 9H 5C"), FOUR_FINGERS)
        assert result.hand_type is HandType.FLUSH

    def test_настоящий_стрит_флеш_из_четырёх(self) -> None:
        result = evaluate(parse_cards("2H 3H 4H 5H 9C"), FOUR_FINGERS)
        assert result.hand_type is HandType.STRAIGHT_FLUSH
        assert len(result.scoring_cards) == 4


class TestShortcut:
    def test_стрит_с_пропусками(self) -> None:
        cards = parse_cards("5H 7D 9C JS KH")
        assert evaluate(cards).hand_type is HandType.HIGH_CARD
        assert evaluate(cards, SHORTCUT).hand_type is HandType.STRAIGHT

    def test_пропуск_в_два_ранга_слишком_много(self) -> None:
        assert evaluate(parse_cards("5H 8D JC 2S 4H"), SHORTCUT).hand_type is HandType.HIGH_CARD

    def test_вместе_с_four_fingers(self) -> None:
        mods = HandModifiers(four_fingers=True, shortcut=True)
        # 5-7-9-J: четыре карты с шагом в два ранга каждая.
        result = evaluate(parse_cards("5H 7D 9C JS 2H"), mods)
        assert result.hand_type is HandType.STRAIGHT
        assert len(result.scoring_cards) == 4


class TestSmeared:
    def test_червы_и_бубны_дают_флеш(self) -> None:
        cards = parse_cards("AH 9D 7H 5D 3H")
        assert evaluate(cards).hand_type is HandType.HIGH_CARD
        assert evaluate(cards, SMEARED).hand_type is HandType.FLUSH

    def test_трефы_и_пики_дают_флеш(self) -> None:
        assert evaluate(parse_cards("AS 9C 7S 5C 3S"), SMEARED).hand_type is HandType.FLUSH

    def test_червы_с_трефами_не_склеиваются(self) -> None:
        assert evaluate(parse_cards("AH 9C 7H 5C 3H"), SMEARED).hand_type is HandType.HIGH_CARD


class TestWild:
    def test_wild_достраивает_флеш(self) -> None:
        wild = Card(Rank.THREE, Suit.CLUBS, Enhancement.WILD)
        cards = (*parse_cards("AH 9H 7H 5H"), wild)
        assert evaluate(cards).hand_type is HandType.FLUSH

    def test_wild_достраивает_стрит_флеш(self) -> None:
        wild = Card(Rank.NINE, Suit.CLUBS, Enhancement.WILD)
        cards = (*parse_cards("5H 6H 7H 8H"), wild)
        assert evaluate(cards).hand_type is HandType.STRAIGHT_FLUSH


class TestКаменныеКарты:
    def test_не_участвуют_в_определении_типа_но_засчитываются(self) -> None:
        cards = (*parse_cards("AH AD 9C 7S"), stone())
        result = evaluate(cards)
        assert result.hand_type is HandType.PAIR
        assert len(result.scoring_cards) == 3
        assert any(card.is_stone for card in result.scoring_cards)

    def test_не_ломают_флеш(self) -> None:
        cards = (*parse_cards("AH 9H 7H 5H 3H"), stone())
        result = evaluate(cards)
        assert result.hand_type is HandType.FLUSH
        assert len(result.scoring_cards) == 6

    def test_одни_камни_дают_старшую_карту(self) -> None:
        result = evaluate((stone(), stone()))
        assert result.hand_type is HandType.HIGH_CARD
        assert len(result.scoring_cards) == 2


class TestПорядокЗасчитываемыхКарт:
    def test_сохраняется_порядок_розыгрыша(self) -> None:
        cards = parse_cards("9C AH 3D AD 7S")
        result = evaluate(cards)
        assert result.hand_type is HandType.PAIR
        assert result.scoring_cards == (cards[1], cards[3])

    def test_камни_не_нарушают_порядок(self) -> None:
        cards = (parse_cards("AH")[0], stone(), parse_cards("AD")[0])
        result = evaluate(cards)
        assert result.scoring_cards == cards


class TestНеполныеРуки:
    @pytest.mark.parametrize(
        ("cards", "expected"),
        [
            ("AH", HandType.HIGH_CARD),
            ("AH AD", HandType.PAIR),
            ("AH AD AC", HandType.THREE_OF_A_KIND),
            ("5H 6H 7H 8H", HandType.HIGH_CARD),
        ],
    )
    def test_меньше_пяти_карт(self, cards: str, expected: HandType) -> None:
        assert evaluate(parse_cards(cards)).hand_type is expected


class TestЗначенияРук:
    def test_таблицы_покрывают_все_типы(self) -> None:
        assert set(BASE_VALUES) == set(HandType)
        assert set(PER_LEVEL_VALUES) == set(HandType)

    def test_значения_помечены_непроверенными(self) -> None:
        # Снимается в Фазе 3, когда таблицы начнут генерироваться из игры.
        assert HAND_VALUES_ARE_PROVISIONAL is True

    def test_уровень_повышает_очки_и_множитель(self) -> None:
        first = base_values(HandType.PAIR, 1)
        second = base_values(HandType.PAIR, 2)
        assert second.chips > first.chips
        assert second.mult > first.mult

    def test_первый_уровень_совпадает_с_базой(self) -> None:
        assert base_values(HandType.FLUSH, 1) == BASE_VALUES[HandType.FLUSH]

    def test_нулевой_уровень_отвергается(self) -> None:
        with pytest.raises(ValueError, match="уровень"):
            base_values(HandType.PAIR, 0)
