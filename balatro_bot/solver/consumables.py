"""Использование консумабля перед розыгрышем — Фаза 9.4 плана.

Две половины: Planet-карты (первый кусок) и Tarot-карты (улучшение C1,
первый срез). Общего у них только контекст — инвентарь и текущая рука;
механика и, что важнее, политика применения у них разные, см. ниже.

Tarot охватывает 22 карты, и они не сводятся к одному механизму. Форму
задал замер: `advise()` на руке из 8 карт — 4 мс на пустом стеке и 163 мс
на пяти джокерах с `Misprint`/`Blueprint`/`Baseball`. Тароту, в отличие от
планеты, нужно выбрать **цели**, то есть перебрать подмножества руки, а
«до трёх карт» — это 92 подмножества, 15 с на тяжёлом стеке против 0.6 с,
до которых F1 довёл всё решение хода. Поэтому C1 разбит на срезы:

* **этот срез** — восемь Таротов вида «улучшить выбранную карту»
  (`TAROT_ENHANCEMENTS`), где перебор не превышает `C(8,1)+C(8,2) = 36`;
* **следующий** — `Star`/`Moon`/`Sun`/`World` (до трёх карт в масть),
  `Strength`, `Death`, `The Hanged Man`: там нужен отбор целей по
  достижимости, как в `solver/discard.py`.

Ответ есть по каждой из 22 карт и в этом срезе — посчитанный, в долларах
или честный `None` с причиной: молчание автопилот прочитать не может, в
отличие от человека (тот же довод, что и у третьего уровня ваучеров).

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
тот же принцип, что в `solver/pack.py`. **У Таротов политика обратная**, и
разница тут содержательная: level-up ничего не портит, а Тарот необратимо
переписывает карту колоды на весь оставшийся ран (`The Tower` вовсе стирает
ей ранг и масть). Поэтому Тарот применяется только при строго положительном
приросте, прошедшем ту же долю требования блайнда, что и покупка джокера.

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

import math
from dataclasses import dataclass, replace
from itertools import combinations
from typing import Final, Literal

from balatro_bot.core.cards import Enhancement
from balatro_bot.core.hands import HandType
from balatro_bot.core.state import GameState, ShopItem
from balatro_bot.solver.pack import PLANET_HAND_TYPES, level_up
from balatro_bot.solver.play import advise

__all__ = [
    "MAX_TAROT_CANDIDATES",
    "TAROT_ENHANCEMENTS",
    "PlanetConsumableOffer",
    "TarotConsumableOffer",
    "evaluate_planet_consumables",
    "evaluate_tarot_consumables",
]

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


# ---------------------------------------------------------------------------
# Tarot — улучшение C1, первый срез: карты, улучшающие выбранные карты руки
# ---------------------------------------------------------------------------

#: Тароты вида «улучшить выбранные карты» — какое улучшение и сколько целей
#: максимум. Выписано из `game.lua`'s `P_CENTERS`: у всех восьми
#: `effect = "Enhance"`, а нужные числа лежат в `config.mod_conv`
#: (`m_lucky` -> `Enhancement.LUCKY` и т.д.) и `config.max_highlighted`.
#: `max_highlighted` — это **максимум**, а не точное число: игра разрешает
#: выделить и меньше, поэтому перебор идёт по размерам 1..N. Таблица
#: захардкожена и закрыта тестом на покрытие — тот же приём, что у
#: `PLANET_HAND_TYPES`, `core/tags.py` и `_JOKER_RARITY`: одна неверная
#: строка даёт молча неправильный счёт.
TAROT_ENHANCEMENTS: Final[dict[str, tuple[Enhancement, int]]] = {
    "c_magician": (Enhancement.LUCKY, 2),
    "c_empress": (Enhancement.MULT, 2),
    "c_heirophant": (Enhancement.BONUS, 2),
    "c_lovers": (Enhancement.WILD, 1),
    "c_chariot": (Enhancement.STEEL, 1),
    "c_justice": (Enhancement.GLASS, 1),
    "c_devil": (Enhancement.GOLD, 1),
    "c_tower": (Enhancement.STONE, 1),
}

#: Потолок перебора целей на одну карту. Считается по числу подмножеств руки
#: размеров 1..N, а не по времени: время зависит ещё и от стека джокеров
#: (`advise()` — 4 мс на пустом стеке и 163 мс на пяти джокерах с
#: `Misprint`). При обычной руке в 8 карт и двух целях подмножеств 8+28=36,
#: то есть до потолка далеко; он нужен на случай увеличенной руки
#: (`Paint Brush`/`Palette`) и для следующего среза C1, где целей до трёх и
#: подмножеств уже 92. Выше потолка — честный `None` с пояснением, а не
#: догадка: тот же отказ, что у `rank_joker_orders` выше
#: `MAX_JOKERS_FOR_ORDER_SEARCH`.
MAX_TAROT_CANDIDATES: Final[int] = 64

#: `The Hermit`: `ease_dollars(max(0, min(dollars, extra)))`, `extra = 20` —
#: `card.lua` + `game.lua`, не по памяти.
_HERMIT_CAP: Final[int] = 20

#: `Temperance`: сумма `sell_cost` всех джокеров, ограниченная `extra = 50`
#: (`card.lua`'s `set_ability`, ветка Temperance).
_TEMPERANCE_CAP: Final[int] = 50

#: Тароты, отложенные во второй срез C1: цели у них есть, но перебор шире
#: (до трёх карт — 92 подмножества) и требует отдельного отбора целей по
#: достижимости, как в `solver/discard.py`.
_DEFERRED_TAROTS: Final[frozenset[str]] = frozenset(
    {"c_star", "c_moon", "c_sun", "c_world", "c_strength", "c_death", "c_hanged_man"}
)

#: Тароты, которые создают карты или бросают кубик по джокерам. Их ценность
#: зависит от будущего RNG, который проект не моделирует, — честный `None`,
#: как у неоценённых ваучеров в `solver/vouchers.py`.
_RANDOM_TAROTS: Final[frozenset[str]] = frozenset(
    {"c_fool", "c_high_priestess", "c_emperor", "c_judgement", "c_wheel_of_fortune"}
)


@dataclass(frozen=True, slots=True)
class TarotConsumableOffer:
    """Одна Tarot-карта в инвентаре — стоит ли применять её прямо сейчас и к
    каким картам руки.

    В отличие от Planet-карты, применение Тарота **необратимо меняет карту
    колоды** на весь оставшийся ран: `The Tower` вовсе стирает у неё ранг и
    масть. Поэтому вердикт (`autopilot._decide_consumable_action`) здесь
    строже, чем у планет, — см. его докстринг."""

    item: ShopItem

    enhancement: Enhancement | None
    """Какое улучшение карта навешивает; `None` — не из таблицы
    `TAROT_ENHANCEMENTS` (денежная карта или неоценённая)."""

    targets: tuple[int, ...]
    """0-based индексы карт руки, к которым применять — ровно то, что ждёт
    `ModBridge.use(cards=...)`. Пустой кортеж — применять не к чему (или
    оценки нет): ни один набор целей не поднял счёт этой руки."""

    expected_uplift: float | None
    """Очки (`value_unit == "score"`) либо доллары (`"dollars"`), либо `None`
    — оценки нет. Никогда не отрицателен: если ни один набор целей не
    улучшает эту руку, ответ 0.0 и пустые `targets` — «применять незачем»,
    а не «применение навредит» (карту всегда можно не тратить)."""

    value_unit: Literal["score", "dollars"] | None
    """Единица `expected_uplift`. Отдельным полем по той же причине, что и у
    `VoucherOffer`: очки и доллары нельзя различать одной лишь прозой —
    коду это ничего не даёт."""

    note: str = ""


def _tarot_offer(
    item: ShopItem,
    *,
    enhancement: Enhancement | None = None,
    targets: tuple[int, ...] = (),
    uplift: float | None = None,
    unit: Literal["score", "dollars"] | None = None,
    note: str = "",
) -> TarotConsumableOffer:
    return TarotConsumableOffer(item, enhancement, targets, uplift, unit, note)


def _best_enhancement_targets(
    state: GameState, enhancement: Enhancement, max_targets: int, baseline: float
) -> tuple[tuple[int, ...], float]:
    """Перебрать все наборы целей размеров 1..`max_targets` и вернуть лучший
    вместе с приростом к `baseline`.

    Отсчёт ведётся от `baseline`, поэтому прирост не бывает отрицательным:
    если ни один набор не улучшает руку (а `The Tower`, стирающий ранг и
    масть, вполне может её испортить), ответ — пустые цели и 0.0, то есть
    «применять незачем». Карту ведь никто не обязывает тратить."""
    hand = state.hand
    best_targets: tuple[int, ...] = ()
    best_score = baseline
    for size in range(1, max_targets + 1):
        for combo in combinations(range(len(hand)), size):
            chosen = set(combo)
            changed = tuple(
                replace(card, enhancement=enhancement) if i in chosen else card
                for i, card in enumerate(hand)
            )
            score = advise(replace(state, hand=changed), limit=1).best.score
            if score > best_score:
                best_score = score
                best_targets = combo
    return best_targets, best_score - baseline


def _evaluate_tarot(state: GameState, item: ShopItem, baseline: float) -> TarotConsumableOffer:
    """Оценить одну Tarot-карту. Три уровня честности, как у ваучеров
    (`solver/vouchers.py`): точный расчёт в очках, точная формула в
    долларах, честный `None` с пояснением."""
    entry = TAROT_ENHANCEMENTS.get(item.key)
    if entry is not None:
        enhancement, max_targets = entry
        candidates = sum(math.comb(len(state.hand), size) for size in range(1, max_targets + 1))
        if candidates > MAX_TAROT_CANDIDATES:
            return _tarot_offer(
                item,
                enhancement=enhancement,
                note=f"перебор целей не влез в бюджет ({candidates} > {MAX_TAROT_CANDIDATES})",
            )
        targets, uplift = _best_enhancement_targets(state, enhancement, max_targets, baseline)
        note = ""
        if enhancement is Enhancement.GOLD:
            # Gold платит $3 за карту, оставшуюся в руке к концу раунда, и на
            # счёт розыгрыша не влияет вовсе. Ноль тут — посчитанный факт, а
            # не пробел в реализации; та же честная нулевая ценность, что у
            # «экономических» джокеров в `implementations.py`.
            note = "Gold даёт деньги в конце раунда, а не очки — ноль здесь посчитан, не пропущен"
        elif enhancement is Enhancement.STONE:
            note = "Stone стирает у карты ранг и масть — на будущих руках это может выйти боком"
        return _tarot_offer(
            item, enhancement=enhancement, targets=targets, uplift=uplift, unit="score", note=note
        )

    if item.key == "c_hermit":
        return _tarot_offer(
            item,
            uplift=float(max(0, min(state.money, _HERMIT_CAP))),
            unit="dollars",
            note=f"удвоение денег, потолок ${_HERMIT_CAP}",
        )
    if item.key == "c_temperance":
        total = sum(joker.sell_value or 0 for joker in state.jokers)
        return _tarot_offer(
            item,
            uplift=float(min(total, _TEMPERANCE_CAP)),
            unit="dollars",
            note=f"сумма цен продажи джокеров, потолок ${_TEMPERANCE_CAP}",
        )

    if item.key in _DEFERRED_TAROTS:
        return _tarot_offer(item, note="второй срез C1: целей до трёх, нужен отбор по достижимости")
    if item.key in _RANDOM_TAROTS:
        return _tarot_offer(
            item, note="создаёт карты/джокеров — зависит от RNG, который не моделируется"
        )
    return _tarot_offer(item, note="не Tarot либо неизвестная карта")


def evaluate_tarot_consumables(state: GameState) -> tuple[TarotConsumableOffer, ...]:
    """Оценить Tarot-карты в инвентаре — пустой кортеж вне фазы
    `SELECTING_HAND` или без руки (сравнивать не с чем), как и у планет.

    Порядок: сперва оценённые в очках по убыванию прироста, затем всё
    остальное. Складывать в один ряд очки и доллары нельзя — это разные
    величины без курса обмена, тот же отказ, что у `ShopAdvice.vouchers`."""
    if state.phase != _SELECTING_HAND or not state.hand:
        return ()

    known = {
        *TAROT_ENHANCEMENTS,
        "c_hermit",
        "c_temperance",
        *_DEFERRED_TAROTS,
        *_RANDOM_TAROTS,
    }
    items = [item for item in state.consumables if item.key in known]
    if not items:
        return ()

    baseline = advise(state, limit=1).best.score
    offers = [_evaluate_tarot(state, item, baseline) for item in items]
    offers.sort(
        key=lambda offer: (
            offer.value_unit == "score",
            offer.expected_uplift if offer.expected_uplift is not None else 0.0,
        ),
        reverse=True,
    )
    return tuple(offers)
