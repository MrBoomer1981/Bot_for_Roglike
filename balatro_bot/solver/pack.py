"""Оценка выбора карты при вскрытии открытого пака.

Два честно замкнутых случая — по тому же принципу, что везде в проекте:
считаем то, что уже видно, без моделирования RNG.

- **Celestial/Planet Pack** (`PLANET_PACK`): эффект детерминирован (level-up
  конкретного типа руки на `core.hands.PER_LEVEL_VALUES`) и полностью
  объясним движком. `PLANET_HAND_TYPES` — соответствие ключа планеты типу
  руки, выписанное из `core/catalogue.py` (тексты сверены с игрой через
  `enums.lua`), по одной планете на тип (покрытие — `tests/test_pack.py`).
  Поднятие уровня не может понизить лучший достижимый счёт, поэтому прирост
  по построению неотрицателен.

- **Buffoon Pack** (`BUFFOON_PACK`): джокеры *видны* в паке — никакого RNG,
  тот же контрфактум, что для джокера в витрине (`solver.shop.joker_uplift`,
  общий код): добавить джокера к текущим, пересчитать `advise()` на выборке
  представительных рук, взять разницу. В отличие от планеты плохой джокер
  прирост дать не обязан, поэтому автопилот берёт карту только при
  строго положительном приросте и свободном слоте (`autopilot`).

Arcana/Tarot, Spectral и Standard паки этот модуль не оценивает — им нужен
пласт механик консумаблов/карт колоды (PLAN.md «9.3»/«9.4»); автопилот на
них честно берёт `skip_pack`, чтобы ран не застревал.

Вскрытие пака происходит вне розыгрыша (`GameState.hand` пуст), поэтому
выборка рук — из `GameState.full_deck`, если он известен точно, иначе
стандартная колода, ровно как в `solver/shop.py`."""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Final, Literal

from balatro_bot.core.cards import Card, standard_deck
from balatro_bot.core.catalogue import is_known_joker
from balatro_bot.core.hands import PER_LEVEL_VALUES, HandType
from balatro_bot.core.state import GameState, JokerCard, PokerHandInfo, ShopItem
from balatro_bot.solver.play import advise
from balatro_bot.solver.shop import joker_uplift

__all__ = [
    "BUFFOON_PACK",
    "PLANET_HAND_TYPES",
    "PLANET_PACK",
    "PackOffer",
    "evaluate_pack",
    "level_up",
]

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

#: Фазы мода с открытым паком, которые этот модуль оценивает (`core.state`,
#: `State` схемы мода).
PLANET_PACK: Final[str] = "PLANET_PACK"
BUFFOON_PACK: Final[str] = "BUFFOON_PACK"

#: Тот же принцип сэмплирования, что `solver.shop.SAMPLE_HANDS`/`_HAND_SIZE`
#: и `solver.discard._SAMPLE_SEED`: воспроизводимая выборка представительных
#: рук вместо честного, но неподъёмного перебора всей колоды.
SAMPLE_HANDS: Final[int] = 12
_HAND_SIZE: Final[int] = 8
_SAMPLE_SEED: Final[int] = 0


@dataclass(frozen=True, slots=True)
class PackOffer:
    """Одна карта из открытого пака — с оценкой прироста от её взятия.

    `kind` различает Planet-карту (детерминированный level-up, прирост
    неотрицателен по построению) и джокера из Buffoon-пака (обычный
    контрфактум, прирост может быть и нулевым/отрицательным)."""

    item: ShopItem
    kind: Literal["planet", "joker"]
    detail: str
    """Тип руки для планеты, имя джокера для Buffoon-пака — для рендера."""

    expected_uplift: float | None
    """Средний прирост лучшего счёта по представительным рукам. `None` —
    колода для сэмплирования пуста, либо (Buffoon) джокер не реализован."""

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


def evaluate_pack(state: GameState, samples: int = SAMPLE_HANDS) -> tuple[PackOffer, ...]:
    """Оценить карты открытого пака, отсортированные по прибыли по убыванию.

    Пустой кортеж, если открыт не оцениваемый тип пака
    (`PLANET_PACK`/`BUFFOON_PACK`) или в паке нет ни одной опознанной карты.
    Арканы/Спектр/Стандарт сюда не попадают — по ним честный `skip_pack` в
    `autopilot`, не оценка (см. модульный докстринг)."""
    if not state.pack or state.phase not in (PLANET_PACK, BUFFOON_PACK):
        return ()

    deck_source = state.full_deck if state.full_deck else standard_deck()
    exact_deck = state.full_deck is not None

    if state.phase == PLANET_PACK:
        offers = [
            _planet_offer(state, item, hand_type, deck_source, exact_deck, samples)
            for item in state.pack
            if (hand_type := PLANET_HAND_TYPES.get(item.key)) is not None
        ]
    else:
        offers = [
            _buffoon_offer(state, item, deck_source, exact_deck, samples)
            for item in state.pack
            if item.key.startswith("j_")
        ]

    offers.sort(
        key=lambda offer: (
            offer.expected_uplift is not None,
            offer.expected_uplift if offer.expected_uplift is not None else 0.0,
        ),
        reverse=True,
    )
    return tuple(offers)


def _planet_offer(
    state: GameState,
    item: ShopItem,
    hand_type: HandType,
    deck_source: tuple[Card, ...],
    exact_deck: bool,
    samples: int,
) -> PackOffer:
    if len(deck_source) < _HAND_SIZE:
        return PackOffer(item, "planet", hand_type.value, None, exact_deck, 0)

    boosted_state = level_up(state, hand_type)
    rng = random.Random(_SAMPLE_SEED)
    pool = list(deck_source)
    total_delta = 0.0
    for _ in range(samples):
        hand = tuple(rng.sample(pool, _HAND_SIZE))
        baseline = advise(replace(state, hand=hand), limit=1).best.score
        boosted = advise(replace(boosted_state, hand=hand), limit=1).best.score
        total_delta += boosted - baseline

    return PackOffer(item, "planet", hand_type.value, total_delta / samples, exact_deck, samples)


def _buffoon_offer(
    state: GameState,
    item: ShopItem,
    deck_source: tuple[Card, ...],
    exact_deck: bool,
    samples: int,
) -> PackOffer:
    """Джокер из Buffoon-пака — тот же контрфактум, что джокер в витрине
    (`solver.shop.joker_uplift`). Нереализованный джокер → `None`, честно."""
    if not is_known_joker(item.key) or len(deck_source) < _HAND_SIZE:
        return PackOffer(item, "joker", item.label, None, exact_deck, 0)

    joker = JokerCard(key=item.key, label=item.label, edition=item.edition)
    uplift = joker_uplift(state, joker, deck_source, samples)
    return PackOffer(item, "joker", item.label, uplift, exact_deck, samples)
