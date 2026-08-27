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

Остальные 24 ваучера (второй и третий уровень честности — денежные формулы с
горизонтом и эвристические константы, `Hieroglyph`/`Petroglyph` в том числе:
их «−1 анте» требует формулы требований блайнда по анте, которой в проекте
пока нет вовсе, — см. PLAN.md, 9.3) получают `expected_uplift = None` с
поясняющим `note`, а не тихо пропускаются и не гадаются."""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Final

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

_DISCARD_NOTE: Final[str] = (
    "нижняя граница: учтён только один лучший одиночный сброс, не полный перебор до 5 карт сразу"
)
_NOT_YET_SCOPED_NOTE: Final[str] = "пока не оценивается — Фаза 9.3, следующие уровни честности"
_SMALL_DECK_NOTE: Final[str] = "колода для выборки слишком мала"


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
