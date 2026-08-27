"""Решение «что сделать прямо сейчас» — Фаза 9 плана («Автопилот»).

**Розыгрыш/сброс (`SELECTING_HAND`, п. 9.1)** — решение уже полностью
посчитано существующим солвером (`solver.actions.rank_actions`) — тем же
самым списком, что видит человек в `advise`/`watch`. Автопилот не считает
по-своему и не вводит отдельную политику поверх счёта: `decide_action`
буквально берёт первый пункт того же ранжированного списка и переводит его в
вызов RPC мода (`ModBridge.play`/`.discard`, индексы карт в руке, не сами
карты — так требует схема мода, `openrpc.json`'s `play`/`discard`).

Одна честно отмеченная особенность, не дефект: `rank_actions` сравнивает
`play` (точный счёт) и `discard` (оценка по построению, `ActionOption.exact
= False` для сбросов — раздел 8 `docs/Discard Spec.md`) в одном списке по
числу. Автопилот действует по тому же самому топ-1, что видел бы человек в
`watch`, — если сброс окажется наверху списка, это та же самая оценка,
которая и раньше показывалась как совет, автопилот не добавляет новой
неопределённости, только исполняет то же решение сам.

**Скип блайнда (`BLIND_SELECT`, п. 9.2, первый из трёх кусков)** —
`solver.skip.evaluate_skip` сознательно не даёт вердикта: часть тегов
(бесплатный джокер/ваучер/пак) принципиально не переводится в доллары без
выдумки (`core/tags.py`). Автопилоту нужен вердикт, и `decide_skip` даёт
его предельно консервативной политикой поверх уже посчитанных чисел, не
новым расчётом: скип только если у тега есть точная денежная цена
(`SkipAdvice.tag_dollars` — сейчас только `Investment`/`Economy Tag`) и она
строго больше гарантированной награды за игру (`play_reward_min`).
Структурные теги никогда не вызывают скип сами по себе — не потому что они
неважны (частый опытный выбор — как раз скипать ради них), а потому что
здесь их ценность в долларах пришлось бы выдумывать, а этот проект не
гадает. Когда скип не обоснован числом (включая случай, когда скипать
вообще нельзя — на очереди Boss Blind), решение — выбрать блайнд и играть.

Любая другая фаза (`SHOP`, `*_PACK`, ...) намеренно не закрыта — решения там
ещё не замкнуты до вердикта (раздел 6, «Автопилот», пп. 9.2–9.4: магазин
по-прежнему просто показывает числа, не выбор; вскрытие паков не
реализовано вовсе). `decide_action` честно возвращает `None` на этих
фазах, и цикл (`ui/tui.py.autoplay`) на них ведёт себя как обычный `watch`
— показывает состояние и ничего не трогает, пока эти решения не будут
закрыты отдельно.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from balatro_bot.core.cards import Card
from balatro_bot.core.state import GameState
from balatro_bot.solver.actions import rank_actions
from balatro_bot.solver.skip import SkipAdvice, evaluate_skip

__all__ = ["BLIND_SELECT", "SELECTING_HAND", "Action", "decide_action", "decide_skip"]

#: Фаза мода (`GameState.phase`, значение `state` в схеме мода), где в руке
#: есть карты для розыгрыша или сброса. Остальные значения `State` из
#: `openrpc.json` (магазин, вскрытие паков, ...) сюда не входят.
SELECTING_HAND = "SELECTING_HAND"

#: Фаза мода, где показывается экран выбора блайнда (сыграть или скипнуть
#: Small/Big; Boss нужно только выбрать — скипнуть нельзя).
BLIND_SELECT = "BLIND_SELECT"


@dataclass(frozen=True, slots=True)
class Action:
    """Одно решённое действие: что вызвать у моста и какими картами.

    `cards`/`indices` пустые для `select`/`skip` — там RPC мода вообще не
    принимает параметров (см. `ModBridge.select`/`.skip`), решать нечего,
    кроме самого факта вызова."""

    kind: Literal["play", "discard", "select", "skip"]
    cards: tuple[Card, ...] = field(default=())
    indices: tuple[int, ...] = field(default=())
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


def decide_skip(advice: SkipAdvice) -> bool:
    """Скипнуть ли блайнд — предельно консервативная политика, см. модульный
    докстринг. `True` только когда денежная цена тега точно известна и
    строго больше гарантированной награды за игру."""
    return advice.tag_dollars is not None and advice.tag_dollars > advice.play_reward_min


def _decide_blind_action(state: GameState) -> Action:
    """На экране выбора блайнда решение — `select` или `skip` (см. `decide_skip`).

    `evaluate_skip` возвращает `None`, когда скипать вообще нельзя (на
    очереди Boss Blind) — тогда решение единственное, тоже `select`."""
    advice = evaluate_skip(state)
    if advice is not None and decide_skip(advice):
        return Action(kind="skip")
    return Action(kind="select")


def decide_action(state: GameState, *, include_discards: bool = True) -> Action | None:
    """Решить, что сделать прямо сейчас — `None`, если эта фаза ещё не закрыта.

    `include_discards=False` — то же самое, что `--no-discard` у `watch`/
    `advise` (переиспользует тот же параметр `rank_actions`, не отдельный
    флаг): автопилот тогда никогда не решает сбросить, только играть."""
    if state.phase == BLIND_SELECT:
        return _decide_blind_action(state)

    if state.phase == SELECTING_HAND:
        if not state.hand:
            return None
        options = rank_actions(state, top=1, include_discards=include_discards)
        if not options:
            return None
        best = options[0]
        return Action(kind=best.kind, cards=best.cards, indices=_indices_of(state.hand, best.cards))

    return None
