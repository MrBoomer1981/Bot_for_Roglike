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
джокеров брать нечего — пробуем купить Buffoon-пак: `ShopAdvice.packs`
несёт для него нижнюю границу прироста (средний случайный реализованный
джокер, `PackPurchaseOffer` — настоящий пак даёт выбор лучшего из 2–4, так
что это заведомо не переоценка), покупаем при положительной оценке,
свободном слоте и по карману, той же формой, что джокера. Когда и паков
нет — `next_round`, уйти. Ваучеры, прочие типы паков (Celestial/Arcana/
Spectral/Standard) и реролл по-прежнему не тронуты: `evaluate_shop`/
`evaluate_vouchers` не дают им числа, а `reroll_cost` — цена без вердикта
(раздел 8 плана, «Момент рерола»).

**Вскрытие пака (Celestial — кусок 9.2; Buffoon — 9.3).** Фаза открытого
пака у Steamodded — одна общая `SMODS_BOOSTER_OPENED` (не ванильные
`PLANET_PACK`/`BUFFOON_PACK`/...), поэтому тип пака `_decide_pack_action`
определяет по *содержимому* `state.pack` (`solver.pack.evaluate_pack`), не
по имени фазы. Celestial (карты-планеты): контрфактум level-up типа руки
на представительных руках — поднятие не может ухудшить счёт, значит
вопроса «а вдруг не нужна» нет, берём карту с максимальным приростом.
Buffoon (карты `j_*`): джокеры *видны*, тот же контрфактум через
`solver.shop.joker_uplift` (общий код), но плохой джокер прирост дать не
обязан — берём только при **строго положительном** приросте (слот
проверяется тем же условием в `_decide_shop_action` при покупке пака).
Джамбо/мега-паки не требуют отдельной ветки: если после выбора одной
карты пак остаётся открытым, `decide_action` посчитает следующий выбор
заново на следующем опросе.

Arcana/Tarot/Spectral/Standard-пак (в `state.pack` нет ни планет, ни
`j_*`): `evaluate_pack` возвращает пусто — оценить нечем, нужен пласт
механик консумаблов/карт колоды (раздел 6, п. 9.4). Но застревать нельзя:
`_decide_pack_action` возвращает `skip_pack` (взять ничего), а не `None` —
иначе ран-раннер честно фиксировал бы затык. Осознанная маленькая потеря
(иногда в паке лежит полезная карта) ради того, чтобы ран продолжался.

**Consumables перед розыгрышем (`SELECTING_HAND`, первый кусок 9.4).**
Перед тем как решать play/discard, `decide_action` сперва проверяет
`solver.consumables.evaluate_planet_consumables` — использование
Planet-карты из инвентаря политически устроено так же просто, как выбор
карты из Celestial Pack (`_decide_pack_action`): применить карту нельзя
себе во вред (level-up только добавляет фишки/множитель одному типу руки),
поэтому политика — использовать любую найденную Planet-карту сразу, не
дожидаясь положительного числа (в отличие от магазина/скипа, здесь нечего
взвешивать). Ровно одна карта за вызов `decide_action`, тем же паттерном,
что «одна покупка за вызов» в магазине: `ModBridge.use()` сразу меняет
инвентарь, а следующая карта (если такая есть) решится на уже свежем
состоянии на следующем опросе. Tarot-карты в инвентаре эта проверка не
трогает вовсе — намеренно, см. модульный докстринг `solver/consumables.py`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from balatro_bot.adapters.mod_bridge import ModBridge
from balatro_bot.core.cards import Card
from balatro_bot.core.state import GameState, ShopItem
from balatro_bot.solver.actions import rank_actions
from balatro_bot.solver.consumables import evaluate_planet_consumables
from balatro_bot.solver.pack import PACK_OPEN_PHASES, evaluate_pack
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
    "describe_action",
    "dispatch_action",
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

    Только одно из `cards`/`indices`/`item_index` заполнено осмысленно —
    какое именно, зависит от `kind`; для `select`/`skip`/`next_round`/
    `cash_out`/`skip_pack` не нужно ничего, RPC мода вообще не принимает
    параметров (кроме самого факта скипа у `skip_pack` — `open_pack(skip=True)`,
    без индекса)."""

    kind: Literal[
        "play",
        "discard",
        "select",
        "skip",
        "buy",
        "buy_pack",
        "next_round",
        "cash_out",
        "pack",
        "skip_pack",
        "use",
    ]
    cards: tuple[Card, ...] = field(default=())
    indices: tuple[int, ...] = field(default=())
    """0-based индексы `cards` в `GameState.hand` — то, что реально ждёт RPC
    мода (`play`/`discard` принимают индексы в руке, не сами карты)."""

    item_index: int | None = None
    """0-based индекс предмета в `GameState.shop` (`buy`), `GameState.pack`
    (`pack`) или `GameState.consumables` (`use`) — во всех случаях один и
    тот же `ShopItem`, индексирующий один и тот же по форме
    `tuple[ShopItem, ...]`, поэтому поле общее, не отдельное на каждый
    RPC-метод."""

    label: str = ""
    """Название выбранного предмета для лога автопилота (`buy`/`pack` —
    иначе показать было бы нечего, `item_index` сам по себе не читается
    человеком)."""


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


def _item_index_of(items: tuple[ShopItem, ...], item: ShopItem) -> int:
    for index, candidate in enumerate(items):
        if candidate == item:
            return index
    raise ValueError(f"{item!r} не найден в текущем предложении")


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
    """В магазине решение — купить лучшего по приросту джокера, затем (если
    джокеров брать нечего) Buffoon-пак с положительной нижней границей, иначе
    уйти (`next_round`). См. модульный докстринг про политику и её границы."""
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
                    item_index=_item_index_of(state.shop, offer.item),
                    label=offer.item.label,
                )
        for pack in advice.packs:
            if (
                pack.affordable
                and pack.has_slot
                and pack.expected_uplift is not None
                and pack.expected_uplift > 0
            ):
                return Action(
                    kind="buy_pack",
                    item_index=_item_index_of(state.shop_packs, pack.item),
                    label=pack.item.label,
                )
    return Action(kind="next_round")


def _decide_pack_action(state: GameState) -> Action:
    """Вскрытие открытого пака. Тип определяется по содержимому
    (`solver.pack.evaluate_pack`), не по имени фазы.

    Планета (`offer.kind == "planet"`): взять карту с наибольшим приростом —
    подъём уровня руки не может ухудшить счёт, вопрос только «какую».
    Джокер из Buffoon-пака (`"joker"`): взять с наибольшим приростом, но лишь
    при строго положительной оценке — плохой джокер занял бы слот зря. Если
    брать нечего (пак пуст, только нереализованные джокеры, либо это
    Arcana/Spectral/Standard — `evaluate_pack` тогда возвращает пусто) —
    `skip_pack`, чтобы ран не застревал."""
    for offer in evaluate_pack(state):
        if offer.expected_uplift is None:
            continue
        if offer.kind == "joker" and offer.expected_uplift <= 0:
            continue
        return Action(
            kind="pack",
            item_index=_item_index_of(state.pack, offer.item),
            label=offer.item.label,
        )
    return Action(kind="skip_pack")


def _decide_consumable_action(state: GameState) -> Action | None:
    """Использовать Planet-карту из инвентаря, если такая есть — см.
    модульный докстринг про то, почему тут не нужно ждать положительного
    числа. `None`, если Planet-карт в инвентаре нет — тогда решение
    переходит к play/discard как обычно."""
    offers = evaluate_planet_consumables(state)
    if not offers:
        return None
    item = offers[0].item
    return Action(kind="use", item_index=_item_index_of(state.consumables, item), label=item.label)


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

    if state.phase in PACK_OPEN_PHASES:
        # Тип пака решается по содержимому: Celestial/Buffoon оцениваются,
        # Arcana/Spectral/Standard — `skip_pack` внутри (см. `_decide_pack_action`).
        return _decide_pack_action(state)

    if state.phase == SELECTING_HAND:
        if not state.hand:
            return None
        consumable_action = _decide_consumable_action(state)
        if consumable_action is not None:
            return consumable_action
        options = rank_actions(state, top=1, include_discards=include_discards)
        if not options:
            return None
        best = options[0]
        return Action(kind=best.kind, cards=best.cards, indices=_indices_of(state.hand, best.cards))

    return None


def dispatch_action(bridge: ModBridge, action: Action) -> GameState:
    """Исполнить `action` через мост и вернуть новое состояние.

    Один перевод `Action.kind` -> RPC-метод, общий для живого цикла
    (`ui/tui.py.autoplay`) и ран-раннера (`balatro_bot/runner.py`) — раньше
    жил только внутри цикла `tui`. Ошибки моста (`ModBridgeError`) не
    глотает: и цикл, и раннер обрабатывают отказ по-своему (цикл печатает и
    продолжает опрос, раннер фиксирует затык в логе решений). Несогласованный
    `Action` (например, `buy` без `item_index`) — это ошибка в
    `decide_action`, а не отказ игры: падаем с `ValueError`, не `assert`
    (который вырезается под `python -O`)."""

    def _index() -> int:
        if action.item_index is None:
            raise ValueError(f"{action.kind}: не задан item_index")
        return action.item_index

    match action.kind:
        case "play":
            return bridge.play(action.indices)
        case "discard":
            return bridge.discard(action.indices)
        case "select":
            return bridge.select()
        case "skip":
            return bridge.skip()
        case "buy":
            return bridge.buy(card=_index())
        case "buy_pack":
            return bridge.buy(pack=_index())
        case "next_round":
            return bridge.next_round()
        case "cash_out":
            return bridge.cash_out()
        case "pack":
            return bridge.open_pack(card=_index())
        case "skip_pack":
            return bridge.open_pack(skip=True)
        case "use":
            return bridge.use(_index())


def describe_action(action: Action) -> str:
    """Короткая человекочитаемая строка о том, что автопилот сделал — для
    лога живого цикла (`ui/tui.py`) и лога решений ран-раннера
    (`balatro_bot/runner.py`). Карты — компактно, ранг+масть, без пометок
    улучшений: полный разбор варианта и так печатает `render_top_actions`."""
    cards = " ".join(f"{c.rank.value}{c.suit.value}" for c in action.cards)
    named = f": {action.label}" if action.label else ""
    match action.kind:
        case "play":
            return f"сыграл {cards}"
        case "discard":
            return f"сбросил {cards}"
        case "select":
            return "выбрал блайнд — играет"
        case "skip":
            return "скипнул блайнд ради тега"
        case "cash_out":
            return "забрал награду за раунд"
        case "buy":
            return f"купил в магазине{named}"
        case "buy_pack":
            return f"купил пак{named}"
        case "next_round":
            return "ушёл из магазина"
        case "pack":
            return f"взял из пака{named}"
        case "skip_pack":
            return "скипнул пак"
        case "use":
            return f"использовал консумабль{named}"
