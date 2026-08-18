"""Тесты модели карты."""

from __future__ import annotations

import pytest

from balatro_bot.core.cards import (
    Card,
    Enhancement,
    Rank,
    Suit,
    effective_suits,
    parse_card,
    parse_cards,
)


class TestParsing:
    def test_разбирает_ранг_и_масть(self) -> None:
        card = parse_card("AH")
        assert card.rank is Rank.ACE
        assert card.suit is Suit.HEARTS

    @pytest.mark.parametrize("text", ["TD", "10D", "10d", "td"])
    def test_десятка_пишется_двумя_способами(self, text: str) -> None:
        card = parse_card(text)
        assert card.rank is Rank.TEN
        assert card.suit is Suit.DIAMONDS

    def test_регистр_не_важен(self) -> None:
        assert parse_card("7c") == parse_card("7C")

    def test_разбирает_строку_карт(self) -> None:
        cards = parse_cards("AH KH QH 7C 7D")
        assert len(cards) == 5
        assert cards[0].rank is Rank.ACE
        assert cards[-1].suit is Suit.DIAMONDS

    @pytest.mark.parametrize("text", ["", "A", "AHH", "XH", "AZ", "1H"])
    def test_мусор_отвергается(self, text: str) -> None:
        with pytest.raises(ValueError):
            parse_card(text)


class TestОчкиРанга:
    @pytest.mark.parametrize(
        ("rank", "chips"),
        [(Rank.TWO, 2), (Rank.NINE, 9), (Rank.TEN, 10), (Rank.JACK, 10), (Rank.KING, 10)],
    )
    def test_номинал_и_картинки(self, rank: Rank, chips: int) -> None:
        assert rank.chips == chips

    def test_туз_даёт_одиннадцать(self) -> None:
        assert Rank.ACE.chips == 11

    def test_туз_старше_короля(self) -> None:
        assert Rank.ACE.order > Rank.KING.order


class TestПозицииВСтрите:
    def test_туз_бывает_младшим_и_старшим(self) -> None:
        assert Rank.ACE.straight_values == frozenset({1, 14})

    def test_у_остальных_одна_позиция(self) -> None:
        assert Rank.KING.straight_values == frozenset({13})


class TestЭффективныеМасти:
    def test_обычная_карта_одной_масти(self) -> None:
        assert effective_suits(parse_card("7C")) == frozenset({Suit.CLUBS})

    def test_wild_подходит_под_любую(self) -> None:
        wild = Card(Rank.SEVEN, Suit.CLUBS, Enhancement.WILD)
        assert effective_suits(wild) == frozenset(Suit)

    def test_каменная_карта_без_масти(self) -> None:
        stone = Card(Rank.SEVEN, Suit.CLUBS, Enhancement.STONE)
        assert effective_suits(stone) == frozenset()

    def test_smeared_склеивает_червы_с_бубнами(self) -> None:
        assert effective_suits(parse_card("7H"), smeared=True) == frozenset(
            {Suit.HEARTS, Suit.DIAMONDS}
        )

    def test_smeared_склеивает_трефы_с_пиками(self) -> None:
        assert effective_suits(parse_card("7S"), smeared=True) == frozenset(
            {Suit.SPADES, Suit.CLUBS}
        )


class TestНеизменяемость:
    def test_карту_нельзя_изменить(self) -> None:
        card = parse_card("AH")
        with pytest.raises(AttributeError):
            card.rank = Rank.KING  # type: ignore[misc]

    def test_одинаковые_карты_равны(self) -> None:
        assert parse_card("AH") == parse_card("AH")
        assert parse_card("AH") != parse_card("AD")
