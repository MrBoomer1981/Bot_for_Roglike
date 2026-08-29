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
from balatro_bot.solver.actions import ActionOption
from balatro_bot.solver.consumables import PlanetConsumableOffer
from balatro_bot.solver.discard import MAX_DISCARD_COMPOSITIONS, DiscardOutcome
from balatro_bot.solver.pack import PlanetOffer
from balatro_bot.solver.play import (
    MAX_JOKERS_FOR_ORDER_SEARCH,
    Advice,
    Candidate,
    rank_joker_orders,
)
from balatro_bot.solver.shop import ShopAdvice
from balatro_bot.solver.skip import SkipAdvice

__all__ = [
    "format_card",
    "format_cards",
    "format_number",
    "render_advice",
    "render_consumable_advice",
    "render_discard_outcome",
    "render_discard_ranking",
    "render_explanation",
    "render_joker_order",
    "render_pack_advice",
    "render_shop_advice",
    "render_skip_advice",
    "render_state",
    "render_top_actions",
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


def render_skip_advice(advice: SkipAdvice) -> None:
    """Показать разложенные числа для решения «играть или скипнуть».

    Не даёт единого вердикта — часть тегов принципиально не сводится к
    одному числу (`solver/skip.py`), поэтому показываем содержимое обеих
    сторон и оставляем сравнение человеку, как договорились."""
    print(f"\nвыбор блайнда: {advice.blind_kind.title()} Blind, нужно {advice.required_score}")
    if advice.next_required_score:
        print(
            f"  дальше — {advice.next_blind_kind.title()} Blind, "
            f"нужно {advice.next_required_score} "
            f"(в {advice.requirement_ratio:.2g}× больше этого)"
        )

    print(f"\n  играть: минимум ${advice.play_reward_min} за победу")
    print(f"          {advice.play_reward_hint}")

    print(f"\n  скипнуть: {advice.tag_name or '—'}")
    if advice.tag_effect:
        print(f"            {advice.tag_effect}")
    if advice.tag is None and advice.tag_name:
        print(f"            тег не опознан ботом: {advice.tag_name!r}")
    if advice.tag_dollars is not None:
        print(f"            в деньгах: ${advice.tag_dollars:g} ({advice.tag_dollars_note})")
    elif advice.tag_dollars_note:
        print(f"            в деньгах: не оценено — {advice.tag_dollars_note}")


def render_shop_advice(advice: ShopAdvice) -> None:
    """Показать, что предлагает магазин: джокеры и часть ваучеров — с
    оценкой прироста счёта, остальные ваучеры и паки — текстом как есть
    (раздел `solver/shop.py`/`solver/vouchers.py`: части из них не с чем
    сравнить контрфактум)."""
    print(f"\nмагазин: денег ${advice.money}")
    if advice.reroll_cost is not None:
        print(f"цена рерола: ${advice.reroll_cost}")

    if advice.jokers:
        print("\nджокеры:")
        ширина = max(len(offer.item.label) for offer in advice.jokers)
        for offer in advice.jokers:
            item = offer.item
            пометки = []
            if not offer.affordable:
                пометки.append("не хватает денег")
            if not offer.has_slot:
                пометки.append("нет слота")
            if offer.interest_lost:
                пометки.append(f"−${offer.interest_lost} процентов в конце раунда")
            хвост = f"  ({', '.join(пометки)})" if пометки else ""
            if offer.expected_uplift is None:
                оценка = "не оценено" if offer.known else "эффект не реализован"
            else:
                приближено = "" if offer.exact_deck else ", колода приближена"
                оценка = f"прирост ~{format_number(offer.expected_uplift)}{приближено}"
            print(f"  {item.label:<{ширина}}  ${item.price:<4} {оценка}{хвост}")

    if advice.vouchers:
        print("\nваучеры:")
        ширина_в = max(len(voucher.item.label) for voucher in advice.vouchers)
        for voucher in advice.vouchers:
            item = voucher.item
            if voucher.expected_uplift is not None:
                приближено = "" if voucher.exact_deck else ", колода приближена"
                оценка = f"прирост ~{format_number(voucher.expected_uplift)}{приближено}"
                if voucher.note:
                    оценка += f" ({voucher.note})"
            elif voucher.heuristic_value is not None:
                # Третья категория честности — экспертная оценка, не расчёт
                # (`solver/vouchers.py`): «~N» намеренно без слова «прирост»,
                # чтобы не читалось как то же самое, что точный расчёт выше.
                оценка = f"экспертно ~{format_number(voucher.heuristic_value)} ({voucher.note})"
            else:
                оценка = voucher.note or item.effect
            print(f"  {item.label:<{ширина_в}}  ${item.price:<4} {оценка}")

    if advice.packs:
        print("\nпаки:")
        for item in advice.packs:
            print(f"  {item.label:<24} ${item.price}")


def render_pack_advice(offers: Sequence[PlanetOffer]) -> None:
    """Показать оценку карт открытого Celestial/Planet Pack — пусто, если
    сейчас открыт не он (`solver/pack.py`: `evaluate_pack` тогда сама
    возвращает пустой кортеж, рисовать нечего)."""
    if not offers:
        return
    print("\nвскрытие пака:")
    ширина = max(len(offer.item.label) for offer in offers)
    for offer in offers:
        if offer.expected_uplift is None:
            оценка = "не оценено"
        else:
            приближено = "" if offer.exact_deck else ", колода приближена"
            оценка = f"прирост ~{format_number(offer.expected_uplift)}{приближено}"
        print(f"  {offer.item.label:<{ширина}}  {offer.hand_type.value:<15} {оценка}")


def render_consumable_advice(offers: Sequence[PlanetConsumableOffer]) -> None:
    """Показать оценку Planet-карт в инвентаре перед розыгрышем — пусто,
    если оценивать нечего (`solver/consumables.py`: не фаза `SELECTING_HAND`,
    нет текущей руки или нет ни одной Planet-карты)."""
    if not offers:
        return
    print("\nконсумабли (Planet) в инвентаре:")
    ширина = max(len(offer.item.label) for offer in offers)
    for offer in offers:
        оценка = f"прирост на этой руке ~{format_number(offer.expected_uplift)}"
        if offer.note:
            оценка += f" ({offer.note})"
        print(f"  {offer.item.label:<{ширина}}  {offer.hand_type.value:<15} {оценка}")


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


def render_top_actions(
    advice: Advice, actions: Sequence[ActionOption], explain: bool = False
) -> None:
    """Единый топ «что делать сейчас»: розыгрыши и сбросы в одном списке.

    Раньше розыгрыши и сбросы показывались двумя отдельными списками, и
    решить между ними приходилось вручную, сравнивая числа глазами. Здесь
    один список, отсортированный по тому же матожиданию счёта — топ-1 просто
    лучшее действие, розыгрыш это или сброс. `render_advice` не удалён:
    список только розыгрышей всё ещё может пригодиться, когда сбросов нет
    или они не нужны.
    """
    remaining = None if advice.required is None else advice.required - advice.already_scored
    if remaining is not None:
        добрано = (
            f" (уже набрано {format_number(advice.already_scored)})"
            if advice.already_scored
            else ""
        )
        print(f"нужно набрать: {format_number(remaining)}{добрано}\n")

    if not actions:
        print("вариантов нет")
        return

    ширина = max(len(format_cards(action.cards)) for action in actions)
    for позиция, action in enumerate(actions, start=1):
        карты = f"{format_cards(action.cards):<{ширина}}"
        if action.kind == "play":
            отметка = ""
            if remaining is not None and action.minimum is not None:
                отметка = "  хватает" if action.minimum >= remaining else ""
            print(
                f"  {позиция}. сыграть  {карты}  {action.label:<15} "
                f"{format_number(action.score):>10}{отметка}"
            )
        else:
            шанс = (
                ""
                if action.success_probability is None
                else f", шанс {action.success_probability:.0%}"
            )
            приближено = "" if action.exact_deck else " (колода приближена)"
            print(
                f"  {позиция}. сбросить {карты}  ждём {action.label} "
                f"~{format_number(action.score)}{шанс}{приближено}"
            )

    экономный = advice.cheapest_sufficient
    if remaining is not None:
        if экономный is None:
            print("\nни один ход не перебивает блайнд гарантированно")
        elif экономный is not advice.best:
            print(f"\nхватит и меньшего: {экономный.describe()}")
            print("он тратит меньше карт и сохраняет колоду")

    if explain:
        render_explanation(advice.best)

    неточные = [action for action in actions if not action.exact]
    if неточные:
        print("\nчисла НЕТОЧНЫЕ:")
        for action in неточные:
            if action.kind == "discard":
                print(f"  - сброс {format_cards(action.cards)}: оценка по выборке, не расчёт")
        причины = sorted({reason for c in advice.candidates for reason in c.outcome.unknown})
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
            f"  перебор добора недоступен: даже после сжатия по классам эквивалентности "
            f"карт композиций больше {MAX_DISCARD_COMPOSITIONS}, либо в колоде нечего "
            "добирать — не гадаю"
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


def render_discard_ranking(
    outcomes: Sequence[DiscardOutcome], play_now: Candidate, top: int = 3
) -> None:
    """Показать лучшие сбросы, отсортированные по точному EV.

    Годится и для `rank_single_discards` (только сбросы одной карты — самый
    дешёвый частный случай), и для `rank_discards` (все размеры 1..5) —
    сам рендер не завязан на размер сброса, `format_cards` показывает любой.
    """
    if not outcomes:
        return

    print("\nчто выгоднее сбросить:")
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
