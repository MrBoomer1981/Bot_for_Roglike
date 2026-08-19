"""Определение типа покерной руки по правилам Balatro.

Отличий от обычного покера достаточно, чтобы не пытаться переиспользовать
готовый эвалюатор:

- есть три «секретных» руки: Five of a Kind, Flush House, Flush Five;
- джокеры меняют сами правила распознавания (`HandModifiers`);
- каменные карты не имеют ни ранга, ни масти, но всегда засчитываются;
- важно не только *какая* рука собралась, но и *какие карты* в ней
  засчитываются: при паре очки дают две карты, а не все пять сыгранных.

Модификаторы намеренно описаны абстрактными флагами, а не именами джокеров:
джокеры появятся в Фазе 3 и будут выставлять эти флаги сами.

К сверке в Фазе 3 (сейчас принято допущение):

- роял-флеш считается обычным стрит-флешем, отдельного типа руки нет;
- дебафф карты боссовым блайндом на определение типа руки не влияет;
- все числовые таблицы ниже выписаны по памяти.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from itertools import combinations, pairwise, product
from typing import Final

from balatro_bot.core.cards import Card, Rank, Suit, effective_suits

__all__ = [
    "BASE_VALUES",
    "HAND_VALUES_ARE_PROVISIONAL",
    "PER_LEVEL_VALUES",
    "HandModifiers",
    "HandResult",
    "HandType",
    "HandValues",
    "base_values",
    "evaluate",
]


class HandType(Enum):
    """Тип покерной руки. Порядок объявления — от слабой к сильной."""

    HIGH_CARD = "high_card"
    PAIR = "pair"
    TWO_PAIR = "two_pair"
    THREE_OF_A_KIND = "three_of_a_kind"
    STRAIGHT = "straight"
    FLUSH = "flush"
    FULL_HOUSE = "full_house"
    FOUR_OF_A_KIND = "four_of_a_kind"
    STRAIGHT_FLUSH = "straight_flush"
    FIVE_OF_A_KIND = "five_of_a_kind"
    FLUSH_HOUSE = "flush_house"
    FLUSH_FIVE = "flush_five"


@dataclass(frozen=True, slots=True)
class HandModifiers:
    """Изменения правил распознавания, приходящие от джокеров.

    Флаги абстрактные: модуль не знает, какой именно джокер их выставил.
    """

    four_fingers: bool = False
    """Флеш и стрит собираются из четырёх карт вместо пяти (`Four Fingers`)."""

    shortcut: bool = False
    """Стрит допускает пропуск одного ранга между картами (`Shortcut`)."""

    smeared: bool = False
    """Червы равны бубнам, трефы равны пикам (`Smeared Joker`)."""


@dataclass(frozen=True, slots=True)
class HandValues:
    """Базовые очки и множитель типа руки."""

    chips: int
    mult: int


@dataclass(frozen=True, slots=True)
class HandResult:
    """Что распозналось в сыгранных картах."""

    hand_type: HandType

    scoring_cards: tuple[Card, ...]
    """Карты, которые дадут очки, в порядке, в котором они были сыграны.

    Порядок важен: в Фазе 3 карты засчитываются слева направо, и от него
    зависят джокеры, реагирующие на отдельные карты.
    """


#: Значения рук первого уровня.
#:
#: ВНИМАНИЕ: выписаны по памяти и **не сверены с игрой**. В Фазе 3 таблица
#: генерируется из `Balatro.love` скриптом `tools/extract_game_data.py` и
#: заменяется целиком. До тех пор любой расчёт, опирающийся на эти числа,
#: обязан помечаться неточным.
BASE_VALUES: Final[dict[HandType, HandValues]] = {
    HandType.HIGH_CARD: HandValues(5, 1),
    HandType.PAIR: HandValues(10, 2),
    HandType.TWO_PAIR: HandValues(20, 2),
    HandType.THREE_OF_A_KIND: HandValues(30, 3),
    HandType.STRAIGHT: HandValues(30, 4),
    HandType.FLUSH: HandValues(35, 4),
    HandType.FULL_HOUSE: HandValues(40, 4),
    HandType.FOUR_OF_A_KIND: HandValues(60, 7),
    HandType.STRAIGHT_FLUSH: HandValues(100, 8),
    HandType.FIVE_OF_A_KIND: HandValues(120, 12),
    HandType.FLUSH_HOUSE: HandValues(140, 14),
    HandType.FLUSH_FIVE: HandValues(160, 16),
}

#: Прибавка за каждый уровень руки выше первого. Та же оговорка, что и выше,
#: но уверенности здесь ещё меньше — числа обязательны к сверке.
PER_LEVEL_VALUES: Final[dict[HandType, HandValues]] = {
    HandType.HIGH_CARD: HandValues(10, 1),
    HandType.PAIR: HandValues(15, 1),
    HandType.TWO_PAIR: HandValues(20, 1),
    HandType.THREE_OF_A_KIND: HandValues(20, 2),
    HandType.STRAIGHT: HandValues(30, 3),
    HandType.FLUSH: HandValues(15, 2),
    HandType.FULL_HOUSE: HandValues(25, 2),
    HandType.FOUR_OF_A_KIND: HandValues(30, 3),
    HandType.STRAIGHT_FLUSH: HandValues(40, 4),
    HandType.FIVE_OF_A_KIND: HandValues(35, 3),
    HandType.FLUSH_HOUSE: HandValues(40, 4),
    HandType.FLUSH_FIVE: HandValues(50, 3),
}

HAND_VALUES_ARE_PROVISIONAL: Final[bool] = True
"""Флаг для механизма честности: значения рук ещё не сверены с игрой.

Снимается в Фазе 3, когда таблицы начнут генерироваться из исходников.
"""


def base_values(hand_type: HandType, level: int = 1) -> HandValues:
    """Очки и множитель руки на заданном уровне.

    Уровень повышается Planet-картами, поэтому это часть состояния игры,
    а не константа типа руки.
    """
    if level < 1:
        raise ValueError(f"уровень руки не может быть меньше 1, получен {level}")
    base = BASE_VALUES[hand_type]
    step = PER_LEVEL_VALUES[hand_type]
    extra = level - 1
    return HandValues(base.chips + step.chips * extra, base.mult + step.mult * extra)


def evaluate(cards: Sequence[Card], modifiers: HandModifiers | None = None) -> HandResult:
    """Определить тип руки и засчитываемые карты.

    На вход идут именно *сыгранные* карты (от одной до пяти), а не вся рука.
    """
    mods = modifiers or HandModifiers()
    stones = [card for card in cards if card.is_stone]
    playable = [card for card in cards if not card.is_stone]

    if not playable:
        # Одни каменные карты: тип руки определять не по чему, но очки они дают.
        return HandResult(HandType.HIGH_CARD, _ordered(cards, stones))

    hand_type, chosen = _classify(playable, mods)
    return HandResult(hand_type, _ordered(cards, chosen + stones))


def _classify(cards: list[Card], mods: HandModifiers) -> tuple[HandType, list[Card]]:
    """Выбрать сильнейшую руку из возможных. Порядок проверок — от сильной к слабой."""
    flush = _find_flush(cards, mods)
    straight = _find_straight(cards, mods)
    # Стрит-флеш — это стрит *среди карт одной масти*, а не совпадение двух
    # независимых находок: с `Four Fingers` флеш и стрит могут опираться на
    # разные четвёрки карт.
    straight_flush = _find_straight(list(flush), mods) if flush else None

    groups = _rank_groups(cards)
    five = _group_of_size(groups, 5)
    four = _group_of_size(groups, 4)
    three = _group_of_size(groups, 3)
    pair = _group_of_size(groups, 2, exclude=three)
    second_pair = _group_of_size(groups, 2, exclude=pair)

    if five and flush:
        return HandType.FLUSH_FIVE, five
    if three and pair and flush:
        return HandType.FLUSH_HOUSE, three + pair
    if five:
        return HandType.FIVE_OF_A_KIND, five
    if straight_flush:
        return HandType.STRAIGHT_FLUSH, list(straight_flush)
    if four:
        return HandType.FOUR_OF_A_KIND, four
    if three and pair:
        return HandType.FULL_HOUSE, three + pair
    if flush:
        return HandType.FLUSH, list(flush)
    if straight:
        return HandType.STRAIGHT, list(straight)
    if three:
        return HandType.THREE_OF_A_KIND, three
    if pair and second_pair:
        return HandType.TWO_PAIR, pair + second_pair
    if pair:
        return HandType.PAIR, pair
    return HandType.HIGH_CARD, [max(cards, key=lambda card: card.rank.order)]


def _rank_groups(cards: list[Card]) -> list[list[Card]]:
    """Карты, сгруппированные по рангу: сначала крупные группы, внутри — старшие ранги."""
    by_rank: dict[Rank, list[Card]] = {}
    for card in cards:
        by_rank.setdefault(card.rank, []).append(card)
    return sorted(
        by_rank.values(), key=lambda group: (len(group), group[0].rank.order), reverse=True
    )


def _group_of_size(
    groups: list[list[Card]], size: int, exclude: list[Card] | None = None
) -> list[Card]:
    """Первая группа нужного размера, не совпадающая с уже занятой."""
    excluded_rank = exclude[0].rank if exclude else None
    for group in groups:
        if len(group) >= size and group[0].rank is not excluded_rank:
            return group[:size]
    return []


def _find_flush(cards: list[Card], mods: HandModifiers) -> tuple[Card, ...] | None:
    """Наибольшая группа карт одной масти, если её хватает на флеш.

    Раскладка идёт за один проход по картам, а не по одному проходу на масть:
    флеш ищется для каждого из 218 подмножеств руки, и лишние обращения
    к `effective_suits` заметны в профиле.
    """
    needed = 4 if mods.four_fingers else 5
    if len(cards) < needed:
        return None

    groups: dict[Suit, list[Card]] = {}
    if not mods.smeared and not any(card.is_wild or card.is_stone for card in cards):
        # Обычный случай: у карты ровно одна масть, спрашивать не о чем.
        for card in cards:
            groups.setdefault(card.suit, []).append(card)
    else:
        for card in cards:
            for suit in effective_suits(card, smeared=mods.smeared):
                groups.setdefault(suit, []).append(card)

    if not groups:
        return None
    best = max(groups.values(), key=len)
    return tuple(best) if len(best) >= needed else None


def _find_straight(cards: Sequence[Card], mods: HandModifiers) -> tuple[Card, ...] | None:
    """Старший стрит, который удаётся собрать из карт.

    Перебор честный: карт не больше пяти, поэтому проверяются все сочетания
    и оба положения туза. Так надёжнее, чем угадывать частные случаи.
    """
    needed = 4 if mods.four_fingers else 5
    if len(cards) < needed:
        return None
    allowed_gaps = {1, 2} if mods.shortcut else {1}

    best: tuple[Card, ...] | None = None
    best_high = -1
    for combo in combinations(cards, needed):
        for values in product(*(card.rank.straight_values for card in combo)):
            ordered = sorted(values)
            if len(set(ordered)) != needed:
                continue
            if any(b - a not in allowed_gaps for a, b in pairwise(ordered)):
                continue
            if ordered[-1] > best_high:
                best_high, best = ordered[-1], combo
    return best


def _ordered(played: Sequence[Card], chosen: Sequence[Card]) -> tuple[Card, ...]:
    """Расставить засчитываемые карты в том порядке, в каком они были сыграны."""
    remaining = list(chosen)
    result: list[Card] = []
    for card in played:
        for i, candidate in enumerate(remaining):
            if candidate is card:
                result.append(remaining.pop(i))
                break
    return tuple(result)
