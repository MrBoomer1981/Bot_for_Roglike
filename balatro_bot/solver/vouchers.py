"""Оценка ваучеров в магазине — Фаза 9.3, первый (самый честный) из трёх
уровней плана («точный расчёт, без новых допущений»).

Три группы прямых ресурсов уже понятны существующему движку — не нужно ни
постулировать горизонт (как денежным формулам второго уровня), ни выдумывать
константу (как третьему уровню):

- **`v_grabber`/`v_nacho_tong`** (+1 руке за раунд каждый) — лишняя рука
  создаёт целиком новую возможность розыгрыша, которой иначе не было бы: её
  ценность — просто средний лучший счёт (`advise().best.score`) по
  представительным рукам, без вычитания базы (без ваучера этот розыгрыш
  просто не случился бы, а не случился бы с нулевым счётом каким-то другим
  способом).
- **`v_paint_brush`/`v_palette`** (+1 к размеру руки каждый) — тот же
  контрфактум, что у джокеров в `solver/shop.py`: добавить карту к руке,
  пересчитать `advise()`, взять разницу с рукой без неё. Обе стороны берутся
  из одной и той же выборки (`_HAND_SIZE + 1` карт, база — первые
  `_HAND_SIZE` из них), чтобы прирост был по одной конкретной добавленной
  карте, а не по двум независимо насэмплированным рукам.
- **`v_wasteful`/`v_recyclomancy`** (+1 сбросу за раунд каждый) — здесь
  честный расчёт слегка ỳже, чем может показаться, и это явно
  проговаривается через `VoucherOffer.note`: ценность сброса меряется только
  по **одному** лучшему одиночному сбросу (`solver.discard.
  rank_single_discards` — единственный размер сброса, чей точный перебор
  всегда дёшев, см. `solver/discard.py`), а не по честному перебору наборов
  до пяти карт сразу (`rank_discards`), который на порядок дороже на каждый
  семпл и не укладывается в бюджет витрины магазина. Это не переоценка, а
  честная нижняя граница: настоящий выигрыш от сброса нескольких карт разом
  может быть больше.

Второй уровень честности — денежная формула с явным (постулированным)
горизонтом, а не сведение к очкам:

- **`v_seed_money`/`v_money_tree`** (потолок процентов до $50/$100) —
  горизонт здесь не выдуман, а взят из самого состояния: число оставшихся
  раундов **этого анте** (`_rounds_left_in_ante`, по статусам
  `GameState.blinds`, вплоть до `DEFEATED`), не «до конца рана» — дальше
  этого анте бот не знает даже, будут ли деньги на руках расти или падать.
  Ценность — `(проценты с новым потолком − проценты со старым) × горизонт`,
  при явном допущении, что сумма денег на конец каждого будущего раунда
  этого анте останется примерно такой же, как сейчас (`note` говорит об
  этом прямо) — реальная сумма может вырасти (тогда ценность выше) или
  упасть (тогда ниже).
- **`v_reroll_surplus`/`v_reroll_glut`** (дешевле реролл на $2 каждый) —
  честно ещё уже: считается только экономия на *ближайшем* реролле по
  текущей цене (`GameState.reroll_cost`), не на всех рероллах до конца
  рана — тот же принцип неполноты, что у `JokerOffer.interest_lost`
  (раздел выше), только для реролла, а не для процентов.
- **`v_clearance_sale`/`v_liquidation`** (скидка 25%/50% на карты и паки
  в магазине) — горизонт тоже не выдуман, а взят из уже показанного:
  сколько удалось бы сэкономить, купив *весь* товар, уже показанный в этом
  заходе в магазин (`GameState.shop` + `shop_packs`, ваучеры не входят —
  игра скидывает только «cards and packs»), а не спроецированный на
  будущие визиты. Обратный пересчёт цены без скидки из уже показанной
  (`core.economy.discount_percent(state.used_vouchers)`, если скидка уже
  частично активна) неточен из-за `floor()` в исходной формуле цены — на
  единицы долларов, не более, и `note` говорит об этом прямо.

`Hieroglyph`/`Petroglyph` (−1 анте, третья пара «точного» уровня по
изначальному плану) остаются честно отложенными: их «−1 анте» требует
формулы требований блайнда по анте, которой в проекте пока нет вовсе, —
см. PLAN.md, 9.3.

Третий уровень честности — явно помеченная эвристика (раздел 2 плана,
«Третья категория»): не результат счёта и не формула с горизонтом, а
экспертная оценка по игровому смыслу эффекта, назначенная, а не
посчитанная. Обязана быть отличима от точного числа не тем же полем с
флагом приближённости (как `DiscardOption.exact`), а структурно другим
полем — отсюда `VoucherOffer.heuristic_value`, отдельное от
`expected_uplift`, которое для этих ваучеров остаётся честным `None`.
Единицы — условные «доллары», сравнимые *друг с другом* (какой из этих
ваучеров важнее), но не складываемые с `expected_uplift`/ценой предмета:
  - **`v_antimatter`** (+1 слот джокера) — оценена выше всех: лишний слот
    джокера в реальной игре почти всегда самое ценное структурное
    улучшение, каждый следующий джокер обычно даёт больше очков, чем любой
    другой ресурс здесь.
  - **`v_hone`/`v_glow_up`** (Foil/Holo/Polychrome в магазине чаще: игра
    ставит `edition_rate` — 1 по умолчанию, 2 у `Hone`, 4 у `Glow Up`,
    выписано из `card.lua`) — реальные издания дают крупные бонусы к
    очкам, но какие конкретно карты выпадут — не считается, оценка ниже
    `Antimatter`, `Glow Up` выше `Hone` (стакается поверх него).
  - **`v_crystal_ball`** (+1 слот консумабля), **`v_telescope`** (Celestial
    Pack всегда содержит планету самой играемой руки — снимает удачу
    вскрытия) — оценены как заметный, но не структурный ресурс.
  - **`v_planet_merchant`/`v_planet_tycoon`**, **`v_tarot_merchant`/
    `v_tarot_tycoon`** (частота планет/таро в магазине — `tarot_rate`/
    `planet_rate` умножаются на `4×extra`, `card.lua`) — больше шансов
    целенаправленно докупить нужный тип, `Tycoon` оценен выше своего
    `Merchant` (стакается, требует его же).
  - **`v_overstock_norm`/`v_overstock_plus`** (+1 слот магазина каждый) —
    больше товара виден за один заход, но не гарантирует ничего конкретно
    нужного; `Overstock Plus` оценен ниже первого (убывающая отдача от
    третьего/четвёртого слота).
  - **`v_observatory`** (X1.5 множителя от Planet-карт в инвентаре под их
    тип руки, требует `Telescope`) — оценена ниже всех: помогает только
    пока в инвентаре реально лежит неиспользованная нужная планета,
    ситуативно.

Эти двенадцать чисел — не результат вычисления, и потому не претендуют на
точность в чём-либо, кроме относительного порядка; ран-раннер (Фаза 9.7)
даст измеримый винрейт, по которому их можно и нужно пересматривать (см.
таблицу рисков раздела 9).

**`v_blank` — не эвристика, а подтверждённый факт.** `card.lua`'s
`Card:apply_to_run` для него вызывает только `check_for_unlock` (открывает
достижение для другого контента), никакого игрового эффекта нет вовсе —
это не оценка «на глаз», а честный `expected_uplift = 0.0`, проверенный по
исходнику, поэтому он в первой (точной) категории, а не в этой.

Остальные ваучеры (`Director's Cut`/`Retcon` — переролл Boss Blind,
`Illusion`/`Magic Trick` — игральные карты в магазине, `Omen Globe` —
Spectral в Arcana Pack; ни один не упомянут даже в исходном списке
третьего уровня плана) по-прежнему получают честный `None` без
`heuristic_value` — не тихо пропускаются, но и не оцениваются наугад там,
где даже приблизительного игрового смысла недостаточно."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from typing import Final

from balatro_bot.core import economy
from balatro_bot.core.cards import Card, standard_deck
from balatro_bot.core.state import GameState, ShopItem
from balatro_bot.solver.discard import rank_single_discards
from balatro_bot.solver.play import advise

__all__ = ["VoucherOffer", "evaluate_vouchers"]

#: Тот же принцип сэмплирования, что `solver.shop.SAMPLE_HANDS`/`_HAND_SIZE`.
SAMPLE_HANDS: Final[int] = 12
_HAND_SIZE: Final[int] = 8
_SAMPLE_SEED: Final[int] = 0

#: Оценка ценности сброса — на порядок дороже на семпл, чем оценка руки
#: (`rank_single_discards` перебирает точный добор на каждую из ≤8 карт
#: руки), поэтому выборка меньше — иначе заход в магазин с этим ваучером
#: занимал бы многие секунды вместо долей секунды.
_DISCARD_SAMPLE_HANDS: Final[int] = 4

_EXTRA_HAND_VOUCHERS: Final[frozenset[str]] = frozenset({"v_grabber", "v_nacho_tong"})
_EXTRA_DISCARD_VOUCHERS: Final[frozenset[str]] = frozenset({"v_wasteful", "v_recyclomancy"})
_EXTRA_HAND_SIZE_VOUCHERS: Final[frozenset[str]] = frozenset({"v_paint_brush", "v_palette"})
_INTEREST_CAP_VOUCHERS: Final[frozenset[str]] = frozenset({"v_seed_money", "v_money_tree"})
_REROLL_DISCOUNT_VOUCHERS: Final[dict[str, int]] = {"v_reroll_surplus": 2, "v_reroll_glut": 2}
_SHOP_DISCOUNT_VOUCHERS: Final[frozenset[str]] = frozenset({"v_clearance_sale", "v_liquidation"})

_DISCARD_NOTE: Final[str] = (
    "нижняя граница: учтён только один лучший одиночный сброс, не полный перебор до 5 карт сразу"
)
_NOT_YET_SCOPED_NOTE: Final[str] = "пока не оценивается — Фаза 9.3, следующие уровни честности"
#: `Blank` — не эвристика и не будущий уровень: `card.lua`'s `Card:apply_to_run`
#: для него — только вызов `check_for_unlock` (открывает достижение для
#: другого контента), никакого игрового эффекта. Это подтверждённый факт из
#: исходника, а не оценка, поэтому нулевой `expected_uplift`, не `heuristic_value`.
_BLANK_NOTE: Final[str] = "буквально ничего не делает (подтверждено в card.lua)"
_SMALL_DECK_NOTE: Final[str] = "колода для выборки слишком мала"
_NO_ANTE_HORIZON_NOTE: Final[str] = (
    "не оценено — неизвестно, сколько раундов осталось в этом анте (нет области blinds)"
)
_NO_REROLL_COST_NOTE: Final[str] = "не оценено — текущая цена рерола неизвестна"
_REROLL_DISCOUNT_NOTE: Final[str] = (
    "только экономия на ближайшем реролле по текущей цене, не на всех до конца рана"
)
_SHOP_DISCOUNT_NOTE: Final[str] = (
    "оценено по товару, уже показанному в этом заходе в магазин, не по будущим визитам; "
    "обратный пересчёт исходной цены приближённый (округление в формуле игры)"
)

#: Третий уровень честности — экспертная оценка «по игровому смыслу», не
#: расчёт (см. модульный докстринг про обоснование каждого числа и почему
#: они вообще не должны попадать в `expected_uplift`). Порядок величин, не
#: точные доллары: `Antimatter` (слот джокера) заведомо выше всего
#: остального, `Observatory` — ниже всего, промежуточные — по относительной
#: важности эффекта.
_HEURISTIC_VALUES: Final[dict[str, float]] = {
    "v_antimatter": 8.0,
    "v_glow_up": 6.0,
    "v_hone": 4.0,
    "v_planet_tycoon": 4.0,
    "v_tarot_tycoon": 3.0,
    "v_planet_merchant": 3.0,
    "v_crystal_ball": 3.0,
    "v_telescope": 3.0,
    "v_overstock_norm": 3.0,
    "v_tarot_merchant": 2.0,
    "v_overstock_plus": 2.0,
    "v_observatory": 2.0,
}

_HEURISTIC_NOTES: Final[dict[str, str]] = {
    "v_antimatter": "лишний слот джокера — обычно самое ценное структурное улучшение",
    "v_hone": "издания (Foil/Holo/Polychrome) вдвое чаще — какие именно, не считается",
    "v_glow_up": "издания вчетверо чаще (требует Hone) — сильнее самого Hone",
    "v_tarot_merchant": "карты Таро вдвое чаще в магазине",
    "v_tarot_tycoon": "карты Таро значительно чаще (требует Tarot Merchant)",
    "v_planet_merchant": "Planet-карты вдвое чаще в магазине",
    "v_planet_tycoon": "Planet-карты значительно чаще (требует Planet Merchant)",
    "v_overstock_norm": "+1 слот в магазине — больше товара на просмотр за заход",
    "v_overstock_plus": "ещё +1 слот — убывающая отдача поверх Overstock",
    "v_crystal_ball": "+1 слот консумабля — держать больше карт про запас",
    "v_telescope": "Celestial Pack гарантированно даёт планету самой играемой руки",
    "v_observatory": "X1.5 множителя от Planet-карт в инвентаре, только пока лежат",
}


@dataclass(frozen=True, slots=True)
class VoucherOffer:
    """Один ваучер в магазине — с попыткой оценить его в очках, где это
    честно возможно (см. модульный докстринг про три группы)."""

    item: ShopItem

    expected_uplift: float | None
    """Средний прирост по представительным рукам. `None` — ваучер вне
    текущего среза (`note` объясняет, почему)."""

    exact_deck: bool
    samples: int
    note: str = ""

    heuristic_value: float | None = None
    """Экспертная оценка «по игровому смыслу» — третья категория честности
    (раздел 2 плана), структурно отдельная от `expected_uplift`: тот либо
    посчитан точно/по формуле с горизонтом, либо `None`, никогда не
    догадка. `None` здесь — либо ваучер вообще не в этом срезе, либо у него
    есть настоящая оценка в `expected_uplift` вместо этой. Условные
    «доллары», сравнимые только друг с другом, не с `expected_uplift`."""


def evaluate_vouchers(state: GameState, samples: int = SAMPLE_HANDS) -> tuple[VoucherOffer, ...]:
    """Оценить все ваучеры текущего магазина — пустой кортеж вне фазы `SHOP`
    (`GameState.shop_vouchers` тогда и так пуст)."""
    if not state.shop_vouchers:
        return ()

    deck_source = state.full_deck if state.full_deck else standard_deck()
    exact_deck = state.full_deck is not None

    return tuple(
        _evaluate_voucher(state, item, deck_source, exact_deck, samples)
        for item in state.shop_vouchers
    )


def _evaluate_voucher(
    state: GameState,
    item: ShopItem,
    deck_source: tuple[Card, ...],
    exact_deck: bool,
    samples: int,
) -> VoucherOffer:
    if item.key in _EXTRA_HAND_VOUCHERS:
        return _evaluate_extra_hand(state, item, deck_source, exact_deck, samples)
    if item.key in _EXTRA_HAND_SIZE_VOUCHERS:
        return _evaluate_extra_hand_size(state, item, deck_source, exact_deck, samples)
    if item.key in _EXTRA_DISCARD_VOUCHERS:
        return _evaluate_extra_discard(state, item, deck_source, exact_deck)
    if item.key in _INTEREST_CAP_VOUCHERS:
        return _evaluate_interest_cap(state, item)
    if item.key in _REROLL_DISCOUNT_VOUCHERS:
        return _evaluate_reroll_discount(state, item)
    if item.key in _SHOP_DISCOUNT_VOUCHERS:
        return _evaluate_shop_discount(state, item)
    if item.key == "v_blank":
        return VoucherOffer(item, 0.0, exact_deck, 0, _BLANK_NOTE)
    if item.key in _HEURISTIC_VALUES:
        return VoucherOffer(
            item, None, exact_deck, 0, _HEURISTIC_NOTES[item.key], _HEURISTIC_VALUES[item.key]
        )
    return VoucherOffer(item, None, exact_deck, 0, _NOT_YET_SCOPED_NOTE)


def _sample_hands(deck_source: tuple[Card, ...], size: int, samples: int) -> list[tuple[Card, ...]]:
    if len(deck_source) < size:
        return []
    rng = random.Random(_SAMPLE_SEED)
    pool = list(deck_source)
    return [tuple(rng.sample(pool, size)) for _ in range(samples)]


def _evaluate_extra_hand(
    state: GameState,
    item: ShopItem,
    deck_source: tuple[Card, ...],
    exact_deck: bool,
    samples: int,
) -> VoucherOffer:
    hands = _sample_hands(deck_source, _HAND_SIZE, samples)
    if not hands:
        return VoucherOffer(item, None, exact_deck, 0, _SMALL_DECK_NOTE)

    total = sum(advise(replace(state, hand=hand), limit=1).best.score for hand in hands)
    return VoucherOffer(item, total / len(hands), exact_deck, len(hands))


def _evaluate_extra_hand_size(
    state: GameState,
    item: ShopItem,
    deck_source: tuple[Card, ...],
    exact_deck: bool,
    samples: int,
) -> VoucherOffer:
    hands = _sample_hands(deck_source, _HAND_SIZE + 1, samples)
    if not hands:
        return VoucherOffer(item, None, exact_deck, 0, _SMALL_DECK_NOTE)

    total = 0.0
    for hand in hands:
        boosted = advise(replace(state, hand=hand), limit=1).best.score
        baseline = advise(replace(state, hand=hand[:_HAND_SIZE]), limit=1).best.score
        total += boosted - baseline
    return VoucherOffer(item, total / len(hands), exact_deck, len(hands))


def _sample_hand_and_rest(
    pool: list[Card], size: int, rng: random.Random
) -> tuple[tuple[Card, ...], tuple[Card, ...]]:
    """Разбить колоду на руку и остаток по индексам, а не по значению карты —
    так рука и остаток не пересекаются, даже если в колоде вдруг найдутся две
    карты с одинаковыми на вид полями (в стандартной колоде такого не бывает,
    но `GameState.full_deck` в принципе не гарантирует уникальность значений
    так же строго, как индексы)."""
    indices = rng.sample(range(len(pool)), size)
    chosen = set(indices)
    hand = tuple(pool[i] for i in indices)
    rest = tuple(pool[i] for i in range(len(pool)) if i not in chosen)
    return hand, rest


def _evaluate_extra_discard(
    state: GameState,
    item: ShopItem,
    deck_source: tuple[Card, ...],
    exact_deck: bool,
) -> VoucherOffer:
    if len(deck_source) < _HAND_SIZE:
        return VoucherOffer(item, None, exact_deck, 0, _SMALL_DECK_NOTE)

    rng = random.Random(_SAMPLE_SEED)
    pool = list(deck_source)
    total = 0.0
    counted = 0
    for _ in range(_DISCARD_SAMPLE_HANDS):
        hand, rest = _sample_hand_and_rest(pool, _HAND_SIZE, rng)
        sample_state = replace(state, hand=hand, deck=rest)
        baseline = advise(sample_state, limit=1).best.score
        outcomes = rank_single_discards(sample_state)
        best = outcomes[0].expected if outcomes else baseline
        total += max(0.0, best - baseline)
        counted += 1

    return VoucherOffer(item, total / counted, exact_deck, counted, _DISCARD_NOTE)


def _rounds_left_in_ante(state: GameState) -> int | None:
    """Сколько раундов этого анте ещё не сыграно (`small`/`big`/`boss`, все
    статусы кроме `DEFEATED`) — горизонт для денежных ваучеров второго
    уровня, взятый из самого состояния, а не выдуманный. `None`, если
    область `blinds` не пришла вовсе (ручной ввод) — тогда честно нечего
    посчитать, а не ноль или произвольная константа."""
    if not state.blinds:
        return None
    return sum(1 for blind in state.blinds.values() if blind.status != "DEFEATED")


def _evaluate_interest_cap(state: GameState, item: ShopItem) -> VoucherOffer:
    rounds_left = _rounds_left_in_ante(state)
    if rounds_left is None:
        return VoucherOffer(item, None, True, 0, _NO_ANTE_HORIZON_NOTE)

    current_cap = economy.interest_cap(state.used_vouchers)
    new_cap = economy.interest_cap(state.used_vouchers | {item.key})
    per_round = economy.interest(state.money, state.deck_type, new_cap) - economy.interest(
        state.money, state.deck_type, current_cap
    )
    note = (
        f"горизонт: {rounds_left} раунд(ов) до конца анте, при допущении, что сумма "
        "денег на конец раунда не изменится"
    )
    return VoucherOffer(item, float(per_round * rounds_left), True, 1, note)


def _evaluate_reroll_discount(state: GameState, item: ShopItem) -> VoucherOffer:
    if state.reroll_cost is None:
        return VoucherOffer(item, None, True, 0, _NO_REROLL_COST_NOTE)

    extra = _REROLL_DISCOUNT_VOUCHERS[item.key]
    savings = min(extra, state.reroll_cost)
    return VoucherOffer(item, float(savings), True, 1, _REROLL_DISCOUNT_NOTE)


def _evaluate_shop_discount(state: GameState, item: ShopItem) -> VoucherOffer:
    priced_items = tuple(state.shop) + tuple(state.shop_packs)
    if not priced_items:
        return VoucherOffer(item, 0.0, True, 0, _SHOP_DISCOUNT_NOTE)

    current_discount = economy.discount_percent(state.used_vouchers)
    new_discount = economy.discount_percent(state.used_vouchers | {item.key})

    total_savings = 0.0
    for shop_item in priced_items:
        base_cost = shop_item.price / (1 - current_discount / 100)
        new_price = max(1, math.floor((base_cost + 0.5) * (100 - new_discount) / 100))
        total_savings += max(0, shop_item.price - new_price)

    return VoucherOffer(item, total_savings, True, len(priced_items), _SHOP_DISCOUNT_NOTE)
