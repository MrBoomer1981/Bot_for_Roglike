"""Модель игральной карты Balatro.

Здесь только данные и правила, не зависящие от подсчёта очков: ранг, масть,
улучшение, издание, печать. Эффекты всего перечисленного живут в `scoring`
(Фаза 3) — этот модуль о них не знает.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

__all__ = [
    "Card",
    "Edition",
    "Enhancement",
    "Rank",
    "Seal",
    "Suit",
    "effective_suits",
    "parse_card",
    "parse_cards",
    "standard_deck",
]


class Suit(Enum):
    """Масть. Значение — символ для компактной записи."""

    HEARTS = "H"
    DIAMONDS = "D"
    CLUBS = "C"
    SPADES = "S"


class Rank(Enum):
    """Ранг. Значение — символ для компактной записи (десятка — `T`)."""

    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"
    SIX = "6"
    SEVEN = "7"
    EIGHT = "8"
    NINE = "9"
    TEN = "T"
    JACK = "J"
    QUEEN = "Q"
    KING = "K"
    ACE = "A"

    @property
    def chips(self) -> int:
        """Очки, которые карта даёт сама по себе: 2-10 по номиналу, J/Q/K = 10, A = 11."""
        return _RANK_CHIPS[self]

    @property
    def order(self) -> int:
        """Старшинство для сравнения карт: туз всегда старший."""
        return _RANK_ORDER[self]

    @property
    def straight_values(self) -> frozenset[int]:
        """Позиции, которые ранг может занимать в стрите.

        Туз умеет быть и младшим (A-2-3-4-5), и старшим (10-J-Q-K-A), поэтому
        у него две позиции, у остальных — одна.
        """
        return _STRAIGHT_VALUES[self]


class Enhancement(Enum):
    """Улучшение карты."""

    NONE = "none"
    BONUS = "bonus"
    MULT = "mult"
    WILD = "wild"
    GLASS = "glass"
    STEEL = "steel"
    STONE = "stone"
    GOLD = "gold"
    LUCKY = "lucky"


class Edition(Enum):
    """Издание карты."""

    BASE = "base"
    FOIL = "foil"
    HOLOGRAPHIC = "holographic"
    POLYCHROME = "polychrome"
    NEGATIVE = "negative"
    """Встречается только у джокеров и расходников: даёт дополнительный слот."""


class Seal(Enum):
    """Печать на карте."""

    NONE = "none"
    GOLD = "gold"
    RED = "red"
    BLUE = "blue"
    PURPLE = "purple"


_RANK_CHIPS: Final[dict[Rank, int]] = {
    Rank.TWO: 2,
    Rank.THREE: 3,
    Rank.FOUR: 4,
    Rank.FIVE: 5,
    Rank.SIX: 6,
    Rank.SEVEN: 7,
    Rank.EIGHT: 8,
    Rank.NINE: 9,
    Rank.TEN: 10,
    Rank.JACK: 10,
    Rank.QUEEN: 10,
    Rank.KING: 10,
    Rank.ACE: 11,
}

_RANK_ORDER: Final[dict[Rank, int]] = {
    Rank.TWO: 2,
    Rank.THREE: 3,
    Rank.FOUR: 4,
    Rank.FIVE: 5,
    Rank.SIX: 6,
    Rank.SEVEN: 7,
    Rank.EIGHT: 8,
    Rank.NINE: 9,
    Rank.TEN: 10,
    Rank.JACK: 11,
    Rank.QUEEN: 12,
    Rank.KING: 13,
    Rank.ACE: 14,
}

_STRAIGHT_VALUES: Final[dict[Rank, frozenset[int]]] = {
    rank: frozenset({order}) for rank, order in _RANK_ORDER.items()
}
_STRAIGHT_VALUES[Rank.ACE] = frozenset({1, 14})

#: Пары мастей, которые `Smeared Joker` считает одной мастью.
_SMEARED_PARTNER: Final[dict[Suit, Suit]] = {
    Suit.HEARTS: Suit.DIAMONDS,
    Suit.DIAMONDS: Suit.HEARTS,
    Suit.CLUBS: Suit.SPADES,
    Suit.SPADES: Suit.CLUBS,
}


@dataclass(frozen=True, slots=True)
class Card:
    """Одна карта. Неизменяемая: любое изменение порождает новую карту."""

    rank: Rank
    suit: Suit
    enhancement: Enhancement = Enhancement.NONE
    edition: Edition = Edition.BASE
    seal: Seal = Seal.NONE
    debuffed: bool = False
    """Отключена боссовым блайндом.

    Поле хранится уже сейчас, но на определение типа руки пока не влияет:
    точное поведение дебаффа сверяется с исходниками игры в Фазе 3.
    """

    def __repr__(self) -> str:
        extra = ""
        if self.enhancement is not Enhancement.NONE:
            extra += f" {self.enhancement.value}"
        if self.edition is not Edition.BASE:
            extra += f" {self.edition.value}"
        if self.seal is not Seal.NONE:
            extra += f" {self.seal.value}-seal"
        if self.debuffed:
            extra += " debuffed"
        return f"<{self.rank.value}{self.suit.value}{extra}>"

    @property
    def is_stone(self) -> bool:
        """Каменная карта: не имеет ни ранга, ни масти для определения типа руки.

        Она всегда попадает в засчитываемые карты, но не участвует в поиске
        пар, стритов и флешей.
        """
        return self.enhancement is Enhancement.STONE

    @property
    def is_wild(self) -> bool:
        """Универсальная карта: считается любой мастью."""
        return self.enhancement is Enhancement.WILD


def effective_suits(card: Card, *, smeared: bool = False) -> frozenset[Suit]:
    """Масти, за которые карта может сойти при определении флеша.

    Здесь собрана вся логика «а какая это на самом деле масть», чтобы её не
    пришлось дублировать в каждом джокере и в каждой проверке.

    - каменная карта не имеет масти вовсе;
    - `Wild` подходит под любую масть;
    - `Smeared Joker` склеивает червы с бубнами, а трефы с пиками.
    """
    if card.is_stone:
        return frozenset()
    if card.is_wild:
        return frozenset(Suit)
    if smeared:
        return frozenset({card.suit, _SMEARED_PARTNER[card.suit]})
    return frozenset({card.suit})


_RANK_BY_SYMBOL: Final[dict[str, Rank]] = {rank.value: rank for rank in Rank}
_SUIT_BY_SYMBOL: Final[dict[str, Suit]] = {suit.value: suit for suit in Suit}


def parse_card(text: str) -> Card:
    """Разобрать компактную запись карты: `AH`, `7c`, `TD` или `10d`.

    Формат нужен и для тестов, и для ручного ввода: строку из восьми карт
    человек набирает быстрее, чем заполняет форму.
    """
    token = text.strip().upper()
    if token.startswith("10"):
        token = "T" + token[2:]
    if len(token) != 2:
        raise ValueError(f"не разобрать карту: {text!r}")

    rank = _RANK_BY_SYMBOL.get(token[0])
    suit = _SUIT_BY_SYMBOL.get(token[1])
    if rank is None:
        raise ValueError(f"неизвестный ранг {token[0]!r} в {text!r}")
    if suit is None:
        raise ValueError(f"неизвестная масть {token[1]!r} в {text!r}")
    return Card(rank, suit)


def parse_cards(text: str) -> tuple[Card, ...]:
    """Разобрать строку карт через пробел: `AH KH QH 7C 7D`."""
    return tuple(parse_card(token) for token in text.split())


def standard_deck() -> tuple[Card, ...]:
    """52 базовые карты без улучшений — приближение колоды при ручном вводе.

    Настоящая колода за ран меняется (карты добавляются, улучшаются,
    уничтожаются), а история ходов при ручном вводе не отслеживается.
    Это заведомо неточный запасной путь для `solver/discard.py`, не факт.
    """
    return tuple(Card(rank, suit) for suit in Suit for rank in Rank)
