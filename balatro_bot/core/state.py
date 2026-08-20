"""Нормализованное состояние игры.

Это граница между внешним миром и ядром: солвер работает только с этими
типами и не знает, пришло состояние из мода, из ручного ввода или из теста.

Здесь же живёт механизм честности. Любой объект, которого нет в справочнике,
попадает в `unknown_keys`, и состояние перестаёт считаться точным. Молча
проигнорировать незнакомого джокера нельзя: расчёт останется правдоподобным,
но неверным, а это худший исход для советника.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from balatro_bot.core.cards import Card, Edition
from balatro_bot.core.catalogue import is_known_joker
from balatro_bot.core.hands import HandType, HandValues, base_values

__all__ = ["BlindInfo", "GameState", "JokerCard", "PokerHandInfo"]


@dataclass(frozen=True, slots=True)
class PokerHandInfo:
    """Состояние одного типа руки в текущем ране.

    `chips` и `mult` игра присылает уже с учётом уровня, поэтому таблицы из
    `hands.py` при работе через мод не нужны вовсе.
    """

    level: int
    chips: int
    mult: int
    played: int = 0


@dataclass(frozen=True, slots=True)
class JokerCard:
    """Джокер в слоте. Порядок слотов важен: он влияет на счёт."""

    key: str
    label: str = ""
    edition: Edition = Edition.BASE
    eternal: bool = False

    @property
    def is_known(self) -> bool:
        """Есть ли джокер в справочнике."""
        return is_known_joker(self.key)


@dataclass(frozen=True, slots=True)
class BlindInfo:
    """Блайнд, который сейчас нужно пробить."""

    kind: str
    name: str
    effect: str
    required_score: int


@dataclass(frozen=True, slots=True)
class GameState:
    """Всё, что нужно солверу для выбора хода."""

    phase: str = "UNKNOWN"
    ante: int = 1
    round_number: int = 1
    money: int = 0

    hand: tuple[Card, ...] = ()
    jokers: tuple[JokerCard, ...] = ()
    hand_info: Mapping[HandType, PokerHandInfo] = field(default_factory=dict)
    blind: BlindInfo | None = None

    hands_left: int = 0
    discards_left: int = 0
    chips_scored: int = 0

    unknown_keys: tuple[str, ...] = ()
    """Всё, что не удалось опознать, в виде `вид:ключ`."""

    @property
    def is_exact(self) -> bool:
        """Можно ли доверять расчёту по этому состоянию до последней единицы."""
        return not self.unknown_keys

    @property
    def has_authoritative_hand_values(self) -> bool:
        """Прислала ли игра значения рук сама.

        Если нет — используются провизорные таблицы из `hands.py`, и расчёт
        точным считать нельзя.
        """
        return bool(self.hand_info)

    def hand_values(self, hand_type: HandType) -> HandValues:
        """Очки и множитель типа руки на текущем уровне.

        Приоритет у данных игры: она уже учла уровень, прокачанный
        Planet-картами. Запасной путь — провизорная таблица, нужная только
        при ручном вводе.
        """
        info = self.hand_info.get(hand_type)
        if info is not None:
            return HandValues(info.chips, info.mult)
        return base_values(hand_type, 1)

    @property
    def unknown_jokers(self) -> tuple[str, ...]:
        """Ключи джокеров, эффект которых ещё не реализован."""
        return tuple(joker.key for joker in self.jokers if not joker.is_known)
