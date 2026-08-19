"""Сборка состояния из того, что человек набрал руками.

Нужен всегда: он позволяет считать, когда игра не запущена, мод сломался
после патча или просто хочется прикинуть руку на бумаге. Он же — способ
разрабатывать ядро, не завися от игры.

Джокеров можно называть и внутренним ключом (`j_greedy_joker`), и по-людски
(`greedy joker`). При опечатке подсказываются близкие варианты: помнить
полторы сотни ключей наизусть никто не обязан.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from difflib import get_close_matches
from typing import Final

from balatro_bot.core.cards import parse_cards
from balatro_bot.core.catalogue import JOKERS
from balatro_bot.core.hands import HandType
from balatro_bot.core.state import BlindInfo, GameState, JokerCard, PokerHandInfo

__all__ = ["build_state", "parse_joker", "parse_jokers"]


def _friendly(key: str) -> str:
    """`j_greedy_joker` -> `greedy joker`."""
    return key.removeprefix("j_").replace("_", " ")


_BY_FRIENDLY: Final[dict[str, str]] = {_friendly(key): key for key in JOKERS}


def parse_joker(text: str) -> JokerCard:
    """Опознать джокера по ключу или человеческому названию."""
    token = text.strip().lower().replace("-", " ")
    if token in JOKERS:
        return JokerCard(key=token, label=_friendly(token))
    if token in _BY_FRIENDLY:
        key = _BY_FRIENDLY[token]
        return JokerCard(key=key, label=token)

    похожие = get_close_matches(token, _BY_FRIENDLY, n=3, cutoff=0.6)
    подсказка = f" Возможно: {', '.join(похожие)}." if похожие else ""
    raise ValueError(f"неизвестный джокер {text!r}.{подсказка}")


def parse_jokers(items: Iterable[str]) -> tuple[JokerCard, ...]:
    """Разобрать перечисление джокеров. Порядок сохраняется — он влияет на счёт."""
    return tuple(parse_joker(item) for item in items if item.strip())


def build_state(
    hand: str,
    jokers: Iterable[str] = (),
    *,
    blind: int | None = None,
    blind_name: str = "блайнд",
    hands_left: int = 1,
    discards_left: int = 0,
    money: int = 0,
    chips_scored: int = 0,
    hand_levels: Mapping[HandType, int] | None = None,
) -> GameState:
    """Собрать состояние из строк.

    `hand_levels` — уровни рук, если они известны. Без них используются
    провизорные таблицы, и расчёт честно помечается неточным.
    """
    info: dict[HandType, PokerHandInfo] = {}
    if hand_levels:
        from balatro_bot.core.hands import base_values

        for hand_type, level in hand_levels.items():
            values = base_values(hand_type, level)
            info[hand_type] = PokerHandInfo(level=level, chips=values.chips, mult=values.mult)

    return GameState(
        phase="MANUAL",
        hand=parse_cards(hand),
        jokers=parse_jokers(jokers),
        hand_info=info,
        blind=BlindInfo("MANUAL", blind_name, "", blind) if blind is not None else None,
        hands_left=hands_left,
        discards_left=discards_left,
        money=money,
        chips_scored=chips_scored,
    )
