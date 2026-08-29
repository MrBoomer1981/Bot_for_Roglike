"""Использование консумабля перед розыгрышем — Фаза 9.4 плана, первый (Planet) кусок.

Только Planet-карты в инвентаре обрабатываются здесь — Tarot-карты (~22
разных эффекта, многие трансформируют конкретные карты, `Death` —
донор/цель) по объёму сравнимы с добавлением новых джокеров и намеренно
не тронуты (см. PLAN.md, 9.4).

Механически применение Planet-карты — то же самое, что выбор карты из
Celestial/Planet Pack (`solver/pack.py`): level-up конкретного типа руки
на `core.hands.PER_LEVEL_VALUES`, детерминированно, без RNG. `level_up`
переиспользуется оттуда, а не дублируется. Единственное отличие контекста
— здесь есть настоящая текущая рука (`GameState.hand`, фаза
`SELECTING_HAND`), поэтому оценка не сэмплирует представительные руки из
колоды, как `solver/pack.py`/`solver/shop.py` (там раздать нечего — руки
попросту нет), а считает точный `advise()` прямо на этой руке.

Эта точность — намеренно частичная: `expected_uplift` — прирост только к
*этой одной* руке, не ко всем будущим рукам рана (уровень руки, в отличие
от одноразового эффекта, работает и в следующих раундах тоже — это здесь
не считается) — тот же принцип неполноты, что у `JokerOffer.interest_lost`
(только ближайший конец раунда, не весь ран). Прирост может быть 0, но не
отрицателен — level-up никогда не портит счёт: если текущая рука вообще не
собирает такой тип, прирост честно 0 именно для *этой* руки, при том что
реальная (не посчитанная здесь) польза для будущих раз всё равно есть.
Поэтому политика автопилота (`autopilot._decide_consumable_action`) не
ждёт положительного числа — использует любую найденную Planet-карту сразу,
тот же принцип, что в `solver/pack.py`.

`v_observatory` (см. `solver/vouchers.py`, третий уровень честности) даёт
X1.5 множителя за каждую Planet-карту в инвентаре, совпадающую по типу с
разыгрываемой рукой, — то есть у решения «использовать сейчас» может быть
реальная цена: карта, лежащая неиспользованной, продолжает давать этот
бонус, а после применения перестаёт (превращается в постоянный level-up
вместо повторяемого множителя). Сам этот бонус нигде не реализован в
движке подсчёта (голый факт из `core/catalogue.py`, не формула в
`core/scoring.py`) — сравнить «использовать» и «придержать» здесь не на
чем, и `PlanetConsumableOffer.note` честно предупреждает об этом, если
`v_observatory` выкуплен, вместо того чтобы молчать о реальном, но
непосчитанном компромиссе."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from balatro_bot.core.hands import HandType
from balatro_bot.core.state import GameState, ShopItem
from balatro_bot.solver.pack import PLANET_HAND_TYPES, level_up
from balatro_bot.solver.play import advise

__all__ = ["PlanetConsumableOffer", "evaluate_planet_consumables"]

_SELECTING_HAND: Final[str] = "SELECTING_HAND"
_OBSERVATORY_VOUCHER: Final[str] = "v_observatory"
_OBSERVATORY_NOTE: Final[str] = (
    "выкуплен Observatory: неиспользованная карта этого типа руки в инвентаре сама "
    "даёт X1.5 множителя — не учтено ни на одной стороне сравнения (эффект не "
    "реализован в движке подсчёта)"
)


@dataclass(frozen=True, slots=True)
class PlanetConsumableOffer:
    """Одна Planet-карта в инвентаре — с оценкой прироста от использования
    прямо сейчас, перед розыгрышем текущей руки."""

    item: ShopItem
    hand_type: HandType

    expected_uplift: float
    """Точный прирост счёта текущей руки (`advise()` на настоящих картах
    руки, не выборка) — честная, но неполная цифра: только про *эту* руку,
    не про все будущие розыгрыши этого типа в оставшемся ране (см.
    модульный докстринг)."""

    note: str = ""


def evaluate_planet_consumables(state: GameState) -> tuple[PlanetConsumableOffer, ...]:
    """Оценить все Planet-карты в инвентаре, отсортированные по приросту по
    убыванию — пустой кортеж вне фазы `SELECTING_HAND` или без текущей руки
    (сравнивать не с чем)."""
    if state.phase != _SELECTING_HAND or not state.hand:
        return ()

    baseline = advise(state, limit=1).best.score
    note = _OBSERVATORY_NOTE if _OBSERVATORY_VOUCHER in state.used_vouchers else ""

    offers = [
        PlanetConsumableOffer(
            item, hand_type, advise(level_up(state, hand_type), limit=1).best.score - baseline, note
        )
        for item in state.consumables
        if (hand_type := PLANET_HAND_TYPES.get(item.key)) is not None
    ]
    offers.sort(key=lambda offer: offer.expected_uplift, reverse=True)
    return tuple(offers)
