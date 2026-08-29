"""Оценка выбора карты при вскрытии пака — последний кусок Фазы 9.2 плана.

Единственный сейчас честно замкнутый случай — Celestial/Planet Pack
(`GameState.phase == "PLANET_PACK"`): эффект детерминирован (level-up
конкретного типа руки на `core.hands.PER_LEVEL_VALUES`) и уже полностью
объясним существующим движком, без RNG и без новых допущений — в отличие
от Arcana/Tarot и Spectral, которые трансформируют конкретные карты и по
объёму сравнимы с добавлением новых джокеров (см. PLAN.md, «9.3»/«9.4»,
сознательно не тронуты здесь), и от Buffoon/Standard паков, которые этот
модуль тоже пока не оценивает.

`PLANET_HAND_TYPES` — соответствие ключа планеты типу руки, выписанное из
`core/catalogue.py` (тексты эффектов там уже подтверждены игрой через
`enums.lua`, не по памяти): «Pluto: Increases High Card...», «Mercury:
Increases Pair...» и так далее для всех 12 типов руки — ровно по одной
планете на тип, без пропусков и дублей (покрытие проверяет
`tests/test_pack.py`).

Оценка — тот же контрфактум, что `solver.shop._evaluate_joker_offer`:
поднять уровень нужного типа руки в копии `GameState.hand_info`,
пересчитать `advise()` на выборке представительных рук (вскрытие пака
происходит вне розыгрыша, `GameState.hand` там пуст, так же как в
магазине — тот же источник выборки, `GameState.full_deck`, если он
известен точно, иначе стандартная колода) и взять разницу с исходным.
Поднятие уровня руки не может понизить лучший достижимый счёт — это
строго дополнительные фишки/множитель одного конкретного типа руки, не
отбирающие ничего у остальных типов, — поэтому прирост по построению
неотрицателен: не эвристика вроде «бери самый играемый тип», а прямое
следствие того, как считает `advise()`."""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Final

from balatro_bot.core.cards import Card, standard_deck
from balatro_bot.core.hands import PER_LEVEL_VALUES, HandType
from balatro_bot.core.state import GameState, PokerHandInfo, ShopItem
from balatro_bot.solver.play import advise

__all__ = ["PLANET_HAND_TYPES", "PlanetOffer", "evaluate_pack", "level_up"]

#: Ключ планеты -> тип руки, который она прокачивает. Выписано из текстов
#: эффектов в `core/catalogue.py` (`c_pluto`, `c_mercury`, ...), а не по
#: памяти — те же тексты уже сверены с игрой при генерации каталога.
PLANET_HAND_TYPES: Final[dict[str, HandType]] = {
    "c_pluto": HandType.HIGH_CARD,
    "c_mercury": HandType.PAIR,
    "c_uranus": HandType.TWO_PAIR,
    "c_venus": HandType.THREE_OF_A_KIND,
    "c_saturn": HandType.STRAIGHT,
    "c_jupiter": HandType.FLUSH,
    "c_earth": HandType.FULL_HOUSE,
    "c_mars": HandType.FOUR_OF_A_KIND,
    "c_neptune": HandType.STRAIGHT_FLUSH,
    "c_planet_x": HandType.FIVE_OF_A_KIND,
    "c_ceres": HandType.FLUSH_HOUSE,
    "c_eris": HandType.FLUSH_FIVE,
}

#: Фаза мода, в которой открыт именно Celestial/Planet Pack (`core.state`,
#: `State` схемы мода).
PLANET_PACK: Final[str] = "PLANET_PACK"

#: Тот же принцип сэмплирования, что `solver.shop.SAMPLE_HANDS`/`_HAND_SIZE`
#: и `solver.discard._SAMPLE_SEED`: воспроизводимая выборка представительных
#: рук вместо честного, но неподъёмного перебора всей колоды.
SAMPLE_HANDS: Final[int] = 12
_HAND_SIZE: Final[int] = 8
_SAMPLE_SEED: Final[int] = 0


@dataclass(frozen=True, slots=True)
class PlanetOffer:
    """Одна карта из открытого пака — с оценкой прироста от её взятия."""

    item: ShopItem
    hand_type: HandType

    expected_uplift: float | None
    """Средний прирост лучшего счёта по представительным рукам. `None` —
    колода для сэмплирования пуста (см. модульный докстринг `solver/shop.py`
    про тот же случай у джокеров)."""

    exact_deck: bool
    samples: int


def level_up(state: GameState, hand_type: HandType) -> GameState:
    """Состояние с этим типом руки, прокачанным на один уровень.

    Публична и переиспользуется `solver/consumables.py` (использование
    Planet-карты из инвентаря перед розыгрышем — тот же самый механический
    эффект, что и выбор Planet-карты в паке, просто другой вызывающий
    контекст) — общая формула вместо второй копии."""
    current = state.hand_values(hand_type)
    step = PER_LEVEL_VALUES[hand_type]
    info = state.hand_info.get(hand_type)
    boosted = PokerHandInfo(
        level=(info.level + 1) if info is not None else 2,
        chips=current.chips + step.chips,
        mult=current.mult + step.mult,
        played=info.played if info is not None else 0,
        played_this_round=info.played_this_round if info is not None else 0,
    )
    new_hand_info = dict(state.hand_info)
    new_hand_info[hand_type] = boosted
    return replace(state, hand_info=new_hand_info)


def evaluate_pack(state: GameState, samples: int = SAMPLE_HANDS) -> tuple[PlanetOffer, ...]:
    """Оценить карты открытого Celestial/Planet Pack, отсортированные по
    прибыли по убыванию — пустой кортеж, если сейчас открыт не он
    (`GameState.phase != "PLANET_PACK"`) или в паке нет ни одной опознанной
    планеты."""
    if state.phase != PLANET_PACK or not state.pack:
        return ()

    deck_source = state.full_deck if state.full_deck else standard_deck()
    exact_deck = state.full_deck is not None

    offers = [
        _evaluate_planet_offer(state, item, hand_type, deck_source, exact_deck, samples)
        for item in state.pack
        if (hand_type := PLANET_HAND_TYPES.get(item.key)) is not None
    ]
    offers.sort(
        key=lambda offer: (
            offer.expected_uplift is not None,
            offer.expected_uplift if offer.expected_uplift is not None else 0.0,
        ),
        reverse=True,
    )
    return tuple(offers)


def _evaluate_planet_offer(
    state: GameState,
    item: ShopItem,
    hand_type: HandType,
    deck_source: tuple[Card, ...],
    exact_deck: bool,
    samples: int,
) -> PlanetOffer:
    if len(deck_source) < _HAND_SIZE:
        return PlanetOffer(item, hand_type, None, exact_deck, 0)

    boosted_state = level_up(state, hand_type)

    rng = random.Random(_SAMPLE_SEED)
    pool = list(deck_source)
    total_delta = 0.0
    for _ in range(samples):
        hand = tuple(rng.sample(pool, _HAND_SIZE))
        baseline = advise(replace(state, hand=hand), limit=1).best.score
        boosted = advise(replace(boosted_state, hand=hand), limit=1).best.score
        total_delta += boosted - baseline

    return PlanetOffer(item, hand_type, total_delta / samples, exact_deck, samples)
