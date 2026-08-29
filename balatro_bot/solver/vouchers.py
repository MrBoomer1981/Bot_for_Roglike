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
изначальному плану) остаются честно отложенными, не третьим уровнем: их
«−1 анте» требует формулы требований блайнда по анте, которой в проекте
пока нет вовсе, — см. PLAN.md, 9.3. Третий уровень (эвристическая
константа — `Hone`/`Glow Up`, `Overstock`, `Crystal Ball`, `Antimatter`,
`Telescope`/`Observatory`, ...) тоже не начат. Все они получают
`expected_uplift = None` с поясняющим `note`, а не тихо пропускаются и не
гадаются."""

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
