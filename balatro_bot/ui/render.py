"""Отображение состояния и советов в терминале.

Общий слой между одноразовыми командами (`advise`, `doctor`) и живым окном
(`watch`, см. `ui/tui.py`) — оба показывают одни и те же данные, поэтому
форматирование живёт в одном месте, а не дублируется в двух.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from balatro_bot.core.cards import Card, Edition, Enhancement, Seal
from balatro_bot.core.state import GameState
from balatro_bot.solver.discard import MAX_DRAW_COMBINATIONS, DiscardOutcome
from balatro_bot.solver.play import (
    MAX_JOKERS_FOR_ORDER_SEARCH,
    Advice,
    Candidate,
    rank_joker_orders,
)

__all__ = [
    "format_card",
    "format_cards",
    "format_number",
    "render_advice",
    "render_discard_outcome",
    "render_explanation",
    "render_joker_order",
    "render_single_discard_ranking",
    "render_state",
]

#: Однобуквенные пометки улучшений. Steel и Stone нарочно разведены:
#: первая буква у них общая, а путать их нельзя — одно работает в руке,
#: другое при розыгрыше.
_ENHANCEMENT_MARKS: Final[dict[Enhancement, str]] = {
    Enhancement.BONUS: "B",
    Enhancement.MULT: "M",
    Enhancement.WILD: "W",
    Enhancement.GLASS: "G",
    Enhancement.STEEL: "T",
    Enhancement.STONE: "S",
    Enhancement.GOLD: "$",
    Enhancement.LUCKY: "L",
}

#: Пометки изданий. Буквы не пересекаются с `_ENHANCEMENT_MARKS` — обе
#: группы делят одни скобки, поэтому важно не спутать пометку издания
#: с пометкой улучшения.
_EDITION_MARKS: Final[dict[Edition, str]] = {
    Edition.FOIL: "F",
    Edition.HOLOGRAPHIC: "H",
    Edition.POLYCHROME: "P",
    Edition.NEGATIVE: "N",
}

#: Пометки печатей. Печать — отдельное от улучшения и издания свойство
#: карты, поэтому у неё свой значок `!` вместо общих скобок.
_SEAL_MARKS: Final[dict[Seal, str]] = {
    Seal.RED: "R",
    Seal.GOLD: "G",
    Seal.BLUE: "U",
    Seal.PURPLE: "P",
}


def format_card(card: Card) -> str:
    """Компактная запись карты с пометками, если она не обычная."""
    text = f"{card.rank.value}{card.suit.value}"
    marks = _ENHANCEMENT_MARKS.get(card.enhancement, "")
    marks += _EDITION_MARKS.get(card.edition, "")
    if card.debuffed:
        marks += "x"
    if marks:
        text += f"({marks})"
    if seal := _SEAL_MARKS.get(card.seal, ""):
        text += f"!{seal}"
    return text


def format_cards(cards: Sequence[Card]) -> str:
    return " ".join(format_card(card) for card in cards)


def format_number(value: float) -> str:
    """Число с пробелами между разрядами: 1530 -> `1 530`."""
    return f"{value:,.0f}".replace(",", " ")


def render_state(state: GameState) -> None:
    """Показать состояние человеку."""
    print(f"фаза:        {state.phase}")
    print(f"анте/раунд:  {state.ante} / {state.round_number}")
    print(f"деньги:      ${state.money}")

    blind = state.blind
    if blind is not None:
        print(f"блайнд:      {blind.name} ({blind.kind}), нужно {blind.required_score}")
        print(f"             эффект: {blind.effect or '—'}")
    else:
        print("блайнд:      сейчас не выбран")

    print(f"осталось:    рук {state.hands_left}, сбросов {state.discards_left}")
    print(f"рука:        {' '.join(format_card(card) for card in state.hand) or '—'}")

    if state.jokers:
        print("джокеры:")
        for position, joker in enumerate(state.jokers, start=1):
            edition = _EDITION_MARKS.get(joker.edition, "")
            edition_mark = f" ({edition})" if edition else ""
            mark = "" if joker.is_known else "  <- эффект не реализован"
            print(f"  {position}. {joker.label or joker.key} [{joker.key}]{edition_mark}{mark}")
    else:
        print("джокеры:     нет")

    источник = "от игры" if state.has_authoritative_hand_values else "провизорные таблицы"
    print(f"значения рук: {источник}")

    прокачано = sorted(
        ((hand_type, info) for hand_type, info in state.hand_info.items() if info.level > 1),
        key=lambda item: item[1].level,
        reverse=True,
    )
    if прокачано:
        # Уровень поднимают не только Planet-карты, но и награда Big Blind
        # тега (Orbital Tag) — источник в данных не различается, поэтому
        # причину не называем, только сам факт и уровень.
        строка = ", ".join(f"{hand_type.value} ур.{info.level}" for hand_type, info in прокачано)
        print(f"уровни рук выше первого: {строка}")

    if state.is_exact:
        print("\nрасчёт по этому состоянию будет точным")
    else:
        print("\nрасчёт будет НЕТОЧНЫМ, не опознано:")
        for key in state.unknown_keys:
            print(f"  - {key}")


def render_advice(advice: Advice, top: int, explain: bool) -> None:
    """Показать ранжированный список ходов."""
    remaining = None if advice.required is None else advice.required - advice.already_scored
    if remaining is not None:
        добрано = (
            f" (уже набрано {format_number(advice.already_scored)})"
            if advice.already_scored
            else ""
        )
        print(f"нужно набрать: {format_number(remaining)}{добрано}\n")

    показать = advice.candidates[: max(top, 1)]
    ширина = max(len(format_cards(item.cards)) for item in показать)
    for позиция, item in enumerate(показать, start=1):
        отметка = ""
        if remaining is not None:
            отметка = "  хватает" if item.beats(remaining) else ""
        счёт = str(item.outcome) if not item.outcome.certain else format_number(item.score)
        строка = f"  {позиция}. {format_cards(item.cards):<{ширина}}  "
        print(f"{строка}{item.outcome.hand_type.value:<15} {счёт:>12}{отметка}")

    экономный = advice.cheapest_sufficient
    if remaining is not None:
        if экономный is None:
            print("\nни один ход не перебивает блайнд гарантированно")
        elif экономный is not advice.best:
            print(f"\nхватит и меньшего: {экономный.describe()}")
            print("он тратит меньше карт и сохраняет колоду")

    if explain:
        render_explanation(advice.best)

    if not advice.exact:
        причины = sorted({reason for item in advice.candidates for reason in item.outcome.unknown})
        print("\nчисла НЕТОЧНЫЕ:")
        for причина in причины:
            print(f"  - {причина}")


def render_joker_order(state: GameState, current: Advice) -> None:
    """Проверить, не даст ли другой порядок джокеров счёт больше."""
    result = rank_joker_orders(state)
    if result is None:
        print(f"\nджокеров больше {MAX_JOKERS_FOR_ORDER_SEARCH} — честный перебор порядка пропущен")
        return

    order, order_advice = result
    if order == state.jokers or order_advice.best.score <= current.best.score:
        print("\nтекущий порядок джокеров уже лучший")
        return

    имена = " → ".join(joker.label or joker.key for joker in order)
    print(f"\nдругой порядок джокеров даст больше: {имена}")
    print(f"  сейчас:          {format_number(current.best.score)}")
    print(f"  с этим порядком: {format_number(order_advice.best.score)}")


def render_discard_outcome(
    outcome: DiscardOutcome | None, discard: Sequence[Card], play_now: Candidate
) -> None:
    """Сравнить «сыграть сейчас» с «сбросить и доиграть добором»."""
    print(f"\nсброс {format_cards(discard)}:")
    if outcome is None:
        print(
            f"  перебор добора недоступен: либо комбинаций больше {MAX_DRAW_COMBINATIONS}, "
            "либо в колоде нечего добирать — не гадаю"
        )
        return

    источник = "точная колода" if outcome.exact else "колода приближена (52 минус рука)"
    print(f"  средний счёт после добора: {format_number(outcome.expected)} ({источник})")
    print(f"  переборано доборов: {outcome.draws_considered}")
    print(f"  сыграть сейчас:            {format_number(play_now.score)}")

    if outcome.expected > play_now.score:
        print("  в среднем выгоднее сбросить" + ("" if outcome.exact else " (но это приближение)"))
    else:
        print("  в среднем выгоднее сыграть сейчас")


def render_single_discard_ranking(
    outcomes: Sequence[DiscardOutcome], play_now: Candidate, top: int = 3
) -> None:
    """Показать лучшие сбросы одной карты, отсортированные по EV.

    Только сбросы размера 1 — единственный размер, который `watch` может
    честно пересчитывать на каждое изменение состояния (см. `solver.discard`).
    """
    if not outcomes:
        return

    print("\nчто выгоднее сбросить (одна карта):")
    for позиция, outcome in enumerate(outcomes[: max(top, 1)], start=1):
        отметка = "  выгоднее, чем сыграть сейчас" if outcome.expected > play_now.score else ""
        источник = "" if outcome.exact else "  (колода приближена)"
        print(
            f"  {позиция}. {format_cards(outcome.discarded):<4} "
            f"среднее {format_number(outcome.expected):>8}{отметка}{источник}"
        )


def render_explanation(candidate: Candidate) -> None:
    """Показать, из чего сложился счёт."""
    print(f"\nразбор варианта {format_cards(candidate.cards)}:")
    for step in candidate.outcome.trace:
        chips = format_number(step.chips)
        print(f"  {step.source:<12} {step.detail:<38} {chips:>8} × {step.mult:g}")
    outcome = candidate.outcome
    print(f"  {'итог':<12} {'':<38} {format_number(outcome.expected):>8}")
