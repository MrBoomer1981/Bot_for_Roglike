"""Решение «что сделать прямо сейчас» — первый, узкий срез Фазы 9 плана
(«Автопилот», п. 9.1: «цикл действий и честные вызовы моста»).

Закрывает только фазу `SELECTING_HAND` (розыгрыш/сброс): это решение уже
полностью посчитано существующим солвером (`solver.actions.rank_actions`) —
тем же самым списком, что видит человек в `advise`/`watch`. Автопилот не
считает по-своему и не вводит отдельную политику поверх счёта: `decide_action`
буквально берёт первый пункт того же ранжированного списка и переводит его в
вызов RPC мода (`ModBridge.play`/`.discard`, индексы карт в руке, не сами
карты — так требует схема мода, `openrpc.json`'s `play`/`discard`).

Любая другая фаза (`BLIND_SELECT`, `SHOP`, `*_PACK`, ...) намеренно не
закрыта — решения там ещё не замкнуты до вердикта (раздел 6, «Автопилот»,
пп. 9.2–9.4: скип блайнда и магазин по-прежнему просто показывают числа,
не выбор; вскрытие паков не реализовано вовсе). `decide_action` честно
возвращает `None` на этих фазах, и цикл (`ui/tui.py.autoplay`) на них ведёт
себя как обычный `watch` — показывает состояние и ничего не трогает, пока
эти решения не будут закрыты отдельно.

Одна честно отмеченная особенность, не дефект: `rank_actions` сравнивает
`play` (точный счёт) и `discard` (оценка по построению, `ActionOption.exact
= False` для сбросов — раздел 8 `docs/Discard Spec.md`) в одном списке по
числу. Автопилот действует по тому же самому топ-1, что видел бы человек в
`watch`, — если сброс окажется наверху списка, это та же самая оценка,
которая и раньше показывалась как совет, автопилот не добавляет новой
неопределённости, только исполняет то же решение сам.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from balatro_bot.core.cards import Card
from balatro_bot.core.state import GameState
from balatro_bot.solver.actions import rank_actions

__all__ = ["SELECTING_HAND", "Action", "decide_action"]

#: Фаза мода (`GameState.phase`, значение `state` в схеме мода), где в руке
#: есть карты для розыгрыша или сброса — единственная, которую закрывает
#: этот срез. Остальные 14 значений `State` из `openrpc.json` (магазин,
#: выбор блайнда, вскрытие паков, ...) сюда не входят.
SELECTING_HAND = "SELECTING_HAND"


@dataclass(frozen=True, slots=True)
class Action:
    """Одно решённое действие: что вызвать у моста и какими картами."""

    kind: Literal["play", "discard"]
    cards: tuple[Card, ...]
    indices: tuple[int, ...]
    """0-based индексы `cards` в `GameState.hand` — то, что реально ждёт RPC
    мода (`play`/`discard` принимают индексы в руке, не сами карты)."""


def _indices_of(hand: tuple[Card, ...], cards: tuple[Card, ...]) -> tuple[int, ...]:
    """Индексы `cards` в `hand` — устойчиво к совпадающим по значению картам
    (если такие вообще есть в руке): каждая позиция руки используется под
    свой индекс не больше одного раза, а не через `hand.index(card)`,
    который на дублях всегда нашёл бы один и тот же первый индекс дважды.
    """
    available = list(enumerate(hand))
    indices = []
    for card in cards:
        for position, (index, candidate) in enumerate(available):
            if candidate == card:
                indices.append(index)
                del available[position]
                break
        else:
            raise ValueError(f"карта {card!r} из решения не найдена в руке")
    return tuple(indices)


def decide_action(state: GameState, *, include_discards: bool = True) -> Action | None:
    """Решить, что сделать прямо сейчас — `None`, если эта фаза ещё не закрыта.

    Единственное решаемое здесь действие — розыгрыш/сброс на фазе
    `SELECTING_HAND`, через уже готовый `solver.actions.rank_actions`
    (`top=1` — нужен только лучший вариант, не весь список).
    `include_discards=False` — то же самое, что `--no-discard` у `watch`/
    `advise` (переиспользует тот же параметр `rank_actions`, не отдельный
    флаг): автопилот тогда никогда не решает сбросить, только играть."""
    if state.phase != SELECTING_HAND or not state.hand:
        return None
    options = rank_actions(state, top=1, include_discards=include_discards)
    if not options:
        return None
    best = options[0]
    return Action(kind=best.kind, cards=best.cards, indices=_indices_of(state.hand, best.cards))
