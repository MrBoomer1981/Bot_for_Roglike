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

**Магазин (`SHOP`, п. 9.2, второй кусок) и `ROUND_EVAL`.** Между «выиграл
раунд» и «зашёл в магазин» есть фаза `ROUND_EVAL` («забрать награду за
раунд») — решать там нечего (`cash_out` всегда нужен, чтобы вообще
продолжить), но без явного вызова автопилот застрял бы там навсегда, ровно
как без `select`/`skip` на выборе блайнда. В магазине решение — покупать
джокеров: `solver.shop.evaluate_shop` уже считает `expected_uplift` (прирост
счёта) на каждого, отсортированных по убыванию. Политика максимально
простая и честная — купить лучшего по приросту, если он известен движку
(`known`), карман потянет (`affordable`), есть слот (`has_slot`) и прирост
строго положителен; ни один из этих четырёх флагов не эвристика, все уже
посчитаны в `evaluate_shop`. `interest_lost` (упущенные проценты, раздел
«Магазин и порядок джокеров» плана) сознательно не участвует в самом
решении «покупать ли» — это несоизмеримая с приростом счёта величина
(доллары против очков, тот же принцип, что у `decide_skip`), только
показывается человеку рядом. Покупка — не более одной за вызов
`decide_action`: `evaluate_shop`'s контрфактум для второго джокера не
учитывает уже купленного первого (a `Blueprint`, например, зависит от
соседей), поэтому правильно пересчитывать заново после каждой покупки, а
не набирать корзину по одному-единственному снимку `evaluate_shop` — цикл
опроса (`ui/tui.py.autoplay`) и так перечитывает состояние на каждой
итерации, задача `decide_action` тут не в том, чтобы копить решения, а
в том, чтобы каждый раз отвечать честно по свежим числам. Когда покупать
больше нечего — решение `next_round`, уйти из магазина. Ваучеры, паки и
реролл намеренно не тронуты вовсе (раздел 6, «Автопилот», п. 9.2/9.3
плана): `evaluate_shop` не даёт им числовой оценки, а `ShopAdvice.reroll_cost`
— цена без вердикта (раздел 8 плана, «Момент рерола») — оценивать их
здесь значило бы гадать.

Любая другая фаза (`*_PACK`, ...) намеренно не закрыта — решения там ещё
не замкнуты до вердикта (раздел 6, «Автопилот», п. 9.2: вскрытие паков не
реализовано вовсе). `decide_action` честно возвращает `None` на этих
фазах, и цикл (`ui/tui.py.autoplay`) на них ведёт себя как обычный `watch`
— показывает состояние и ничего не трогает, пока эти решения не будут
закрыты отдельно.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from balatro_bot.core.cards import Card
from balatro_bot.core.state import GameState, ShopItem
from balatro_bot.solver.actions import rank_actions
from balatro_bot.solver.shop import evaluate_shop
from balatro_bot.solver.skip import SkipAdvice, evaluate_skip

__all__ = [
    "BLIND_SELECT",
    "ROUND_EVAL",
    "SELECTING_HAND",
    "SHOP",
    "Action",
    "decide_action",
    "decide_skip",
]

#: Фаза мода (`GameState.phase`, значение `state` в схеме мода), где в руке
#: есть карты для розыгрыша или сброса.
SELECTING_HAND = "SELECTING_HAND"

#: Фаза мода, где показывается экран выбора блайнда (сыграть или скипнуть
#: Small/Big; Boss нужно только выбрать — скипнуть нельзя).
BLIND_SELECT = "BLIND_SELECT"

#: Фаза мода сразу после победы над блайндом, до магазина — нужен `cash_out`,
#: чтобы вообще продолжить (см. модульный докстринг).
ROUND_EVAL = "ROUND_EVAL"

#: Фаза мода внутри магазина.
SHOP = "SHOP"


@dataclass(frozen=True, slots=True)
class Action:
    """Одно решённое действие: что вызвать у моста и с каким параметром.

    Только одно из `cards`/`indices`/`shop_index` заполнено осмысленно —
    какое именно, зависит от `kind`; для `select`/`skip`/`next_round`/
    `cash_out` не нужно ничего, RPC мода вообще не принимает параметров."""

    kind: Literal["play", "discard", "select", "skip", "buy", "next_round", "cash_out"]
    cards: tuple[Card, ...] = field(default=())
    indices: tuple[int, ...] = field(default=())
    """0-based индексы `cards` в `GameState.hand` — то, что реально ждёт RPC
    мода (`play`/`discard` принимают индексы в руке, не сами карты)."""

    shop_index: int | None = None
    """0-based индекс предмета в `GameState.shop` — то, что ждёт `buy` (см.
    `openrpc.json`'s `buy`: `card`/`voucher`/`pack`, здесь всегда `card`,
    покупка ваучеров/паков не входит в этот срез)."""

    label: str = ""
    """Название купленного предмета для лога автопилота (`buy` — иначе
    показать было бы нечего, `shop_index` сам по себе не читается человеком)."""


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


def _shop_index_of(shop: tuple[ShopItem, ...], item: ShopItem) -> int:
    for index, candidate in enumerate(shop):
        if candidate == item:
            return index
    raise ValueError(f"{item!r} не найден в текущем предложении магазина")


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


def _decide_shop_action(state: GameState) -> Action:
    """В магазине решение — купить лучшего по приросту джокера или уйти
    (`next_round`), см. модульный докстринг про политику и её границы."""
    advice = evaluate_shop(state)
    if advice is not None:
        for offer in advice.jokers:
            if (
                offer.known
                and offer.affordable
                and offer.has_slot
                and offer.expected_uplift is not None
                and offer.expected_uplift > 0
            ):
                return Action(
                    kind="buy",
                    shop_index=_shop_index_of(state.shop, offer.item),
                    label=offer.item.label,
                )
    return Action(kind="next_round")


def decide_action(state: GameState, *, include_discards: bool = True) -> Action | None:
    """Решить, что сделать прямо сейчас — `None`, если эта фаза ещё не закрыта.

    `include_discards=False` — то же самое, что `--no-discard` у `watch`/
    `advise` (переиспользует тот же параметр `rank_actions`, не отдельный
    флаг): автопилот тогда никогда не решает сбросить, только играть."""
    if state.phase == BLIND_SELECT:
        return _decide_blind_action(state)

    if state.phase == ROUND_EVAL:
        return Action(kind="cash_out")

    if state.phase == SHOP:
        return _decide_shop_action(state)

    if state.phase == SELECTING_HAND:
        if not state.hand:
            return None
        options = rank_actions(state, top=1, include_discards=include_discards)
        if not options:
            return None
        best = options[0]
        return Action(kind=best.kind, cards=best.cards, indices=_indices_of(state.hand, best.cards))

    return None
