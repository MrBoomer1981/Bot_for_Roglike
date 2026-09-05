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

from balatro_bot.core.cards import Card, Enhancement, Rank, Suit, effective_suits
from balatro_bot.core.hands import HandType
from balatro_bot.core.jokers import build_jokers, modifiers_from
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


#: Второй срез C1: Тароты, меняющие масть выбранных карт. Выписано из
#: `game.lua`'s `P_CENTERS` (`config.suit_conv`), механика — из
#: `card.lua`'s `Card:change_suit`: переписывается только `base`, то есть
#: **ранг, улучшение, издание и печать сохраняются**, меняется одна масть.
#: У всех четырёх `max_highlighted = 3`.
TAROT_SUIT_CONVERSIONS: Final[dict[str, Suit]] = {
    "c_star": Suit.DIAMONDS,
    "c_moon": Suit.CLUBS,
    "c_sun": Suit.HEARTS,
    "c_world": Suit.SPADES,
}

#: Сколько карт максимум берут Тароты второго среза (`max_highlighted`
#: из `game.lua`). У `c_death` это ещё и **минимум**: `min_highlighted = 2`,
#: то есть ровно две цели, а не «до двух», — единственный такой Тарот.
_SUIT_TAROT_TARGETS: Final[int] = 3

#: Оговорка к оценке масти под боссом, который бьёт по мастям. В игре
#: `change_suit` заново считает дебафф карты (`card.lua`), а в этом
#: проекте `Card.debuffed` — статичное поле от мода, которое никто не
#: пересчитывает. Значит под такими боссами прирост от смены масти
#: завышен: карта может стать дебаффнутой, а мы этого не увидим.
_SUIT_BOSS_NOTE: Final[str] = (
    "под боссом на масти оценка завышена: дебафф карты после смены масти не пересчитывается"
)

#: Боссы, чей дебафф завязан на масть карты (`core/bosses.py`).
_SUIT_BOSSES: Final[frozenset[str]] = frozenset({"The Club", "The Goad", "The Head", "The Window"})
_STRENGTH_TARGETS: Final[int] = 2
_DEATH_TARGETS: Final[int] = 2

#: `The Hermit`: `ease_dollars(max(0, min(dollars, extra)))`, `extra = 20` —
#: `card.lua` + `game.lua`, не по памяти.
_HERMIT_CAP: Final[int] = 20

#: `Temperance`: сумма `sell_cost` всех джокеров, ограниченная `extra = 50`
#: (`card.lua`'s `set_ability`, ветка Temperance).
_TEMPERANCE_CAP: Final[int] = 50

#: Тароты, отложенные во второй срез C1: цели у них есть, но перебор шире
#: (до трёх карт — 92 подмножества) и требует отдельного отбора целей по
#: достижимости, как в `solver/discard.py`.
#: Второй срез C1 закрыт: все семь этих карт теперь оцениваются выше
#: (`TAROT_SUIT_CONVERSIONS`, `c_strength`, `c_death`, `c_hanged_man`).
#: Множество осталось затем, что `evaluate_tarot_consumables` собирает по
#: нему список известных ключей, и затем, что тест покрытия проверяет:
#: каждая карта отсюда получает численный ответ, а не молчание.
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
    `TAROT_ENHANCEMENTS` (денежная карта, карта второго среза или
    неоценённая)."""

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

    converts_to: Suit | None = None
    """В какую масть карта переводит цели (`TAROT_SUIT_CONVERSIONS`,
    второй срез). `None` у всех остальных, включая `Strength`/`Death`/
    `The Hanged Man` — у тех механика словами в `note`, отдельного поля
    на каждую заводить незачем. Стоит последним полем, чтобы позиционное
    построение оффера (тесты вывода) не поехало."""


def _tarot_offer(
    item: ShopItem,
    *,
    enhancement: Enhancement | None = None,
    converts_to: Suit | None = None,
    targets: tuple[int, ...] = (),
    uplift: float | None = None,
    unit: Literal["score", "dollars"] | None = None,
    note: str = "",
) -> TarotConsumableOffer:
    return TarotConsumableOffer(
        item=item,
        enhancement=enhancement,
        targets=targets,
        expected_uplift=uplift,
        value_unit=unit,
        note=note,
        converts_to=converts_to,
    )


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


def _боссовый_риск(state: GameState) -> bool:
    """Идёт ли босс, для которого масть карты решает, дебаффнута ли она."""
    blind = state.blind
    return blind is not None and blind.name in _SUIT_BOSSES


def _next_rank(rank: Rank) -> Rank:
    """Ранг на единицу выше — механика `Strength`.

    Туз **заворачивается в двойку**, а не упирается в потолок:
    `card.lua` считает `card.base.id == 14 and 2 or min(id + 1, 14)`.
    Это ровно тот случай, где догадка «ну, туз старший, значит останется» была бы
    неверна."""
    порядок = list(Rank)
    if rank is Rank.ACE:
        return Rank.TWO
    return порядок[порядок.index(rank) + 1]


def _suit_conversion_targets(
    state: GameState, suit: Suit, baseline: float
) -> tuple[tuple[int, ...], float]:
    """Лучший набор карт для перевода в масть `suit` и прирост к `baseline`.

    Сначала **отбор по достижимости**, в форме `solver/discard.py`'s
    `_flush_targets`, и он тут не украшение, а необходимость: три цели из
    восьми это `C(8,1)+C(8,2)+C(8,3) = 92` набора — больше бюджета
    `MAX_TAROT_CANDIDATES`, и без отбора карта честно отказалась бы
    оцениваться вовсе.

    Смысл перевода в масть один — собрать флеш, поэтому считаем, сколько
    карт до него не хватает (`effective_suits` уже знает про `Wild` и
    `Smeared`), и перебираем наборы **ровно этого размера** из карт, ещё
    не бывших этой мастью. Не хватает больше, чем карта берёт целей, или
    флеш уже собран — перебирать нечего, и ответ честный ноль: «применять
    незачем», как и у `_best_enhancement_targets`."""
    hand = state.hand
    mods = modifiers_from(build_jokers(state))
    нужно_всего = 4 if mods.four_fingers else 5
    свои = [i for i, card in enumerate(hand) if suit in effective_suits(card, smeared=mods.smeared)]
    чужие = [i for i in range(len(hand)) if i not in set(свои) and not hand[i].is_stone]
    нужно = нужно_всего - len(свои)
    if нужно <= 0 or нужно > _SUIT_TAROT_TARGETS or нужно > len(чужие):
        return (), 0.0

    best_targets: tuple[int, ...] = ()
    best_score = baseline
    for combo in combinations(чужие, нужно):
        chosen = set(combo)
        # `change_suit` переписывает только масть: улучшение, издание и
        # печать остаются на карте.
        changed = tuple(
            replace(card, suit=suit) if i in chosen else card for i, card in enumerate(hand)
        )
        score = advise(replace(state, hand=changed), limit=1).best.score
        if score > best_score:
            best_score = score
            best_targets = combo
    return best_targets, best_score - baseline


def _strength_targets(state: GameState, baseline: float) -> tuple[tuple[int, ...], float]:
    """Лучший набор карт для повышения ранга (`Strength`, до двух целей)."""
    hand = state.hand
    best_targets: tuple[int, ...] = ()
    best_score = baseline
    for size in range(1, _STRENGTH_TARGETS + 1):
        for combo in combinations(range(len(hand)), size):
            chosen = set(combo)
            changed = tuple(
                replace(card, rank=_next_rank(card.rank)) if i in chosen else card
                for i, card in enumerate(hand)
            )
            score = advise(replace(state, hand=changed), limit=1).best.score
            if score > best_score:
                best_score = score
                best_targets = combo
    return best_targets, best_score - baseline


def _clone(source: Card, onto: Card) -> Card:
    """Копия карты `source` на месте `onto` — механика `Death`.

    `functions/common_events.lua`'s `copy_card` переносит карту целиком:
    ранг с мастью, улучшение, издание, печать. Не только ранг — вот
    ради чего это отдельная функция с именем."""
    return replace(
        onto,
        rank=source.rank,
        suit=source.suit,
        enhancement=source.enhancement,
        edition=source.edition,
        seal=source.seal,
    )


def _death_targets(state: GameState, baseline: float) -> tuple[tuple[int, ...], float]:
    """Лучшая пара для `Death`: ровно две цели, правая копируется на левую.

    `min_highlighted = 2` — «до двух» тут не бывает. Правой игра считает
    карту с большей координатой (`card.lua`), то есть более позднюю по
    порядку руки; её копия и затирает вторую."""
    hand = state.hand
    best: tuple[int, ...] = ()
    best_score = baseline
    for левая, правая in combinations(range(len(hand)), _DEATH_TARGETS):
        changed = tuple(
            _clone(hand[правая], card) if i == левая else card for i, card in enumerate(hand)
        )
        score = advise(replace(state, hand=changed), limit=1).best.score
        if score > best_score:
            best_score = score
            best = (левая, правая)
    return best, best_score - baseline


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

    suit = TAROT_SUIT_CONVERSIONS.get(item.key)
    if suit is not None:
        targets, uplift = _suit_conversion_targets(state, suit, baseline)
        return _tarot_offer(
            item,
            converts_to=suit,
            targets=targets,
            uplift=uplift,
            unit="score",
            note=_SUIT_BOSS_NOTE if _боссовый_риск(state) else "",
        )

    if item.key == "c_strength":
        targets, uplift = _strength_targets(state, baseline)
        return _tarot_offer(
            item,
            targets=targets,
            uplift=uplift,
            unit="score",
            note="ранг +1, туз становится двойкой",
        )

    if item.key == "c_death":
        targets, uplift = _death_targets(state, baseline)
        return _tarot_offer(
            item,
            targets=targets,
            uplift=uplift,
            unit="score",
            note="ровно две цели: правая копируется на левую целиком",
        )

    if item.key == "c_hanged_man":
        # Посчитанный ноль, а не пробел: уничтожение карт может только
        # сузить выбор, из которого `advise` берёт лучший розыгрыш, —
        # счёт этой руки от него не вырастет никогда. Тот же честный
        # ноль, что у `The Devil` в первом срезе.
        return _tarot_offer(
            item,
            uplift=0.0,
            unit="score",
            note=(
                "уничтожает карты — счёт этой руки не поднимет никогда; "
                "прореживание колоды на весь ран проект не моделирует"
            ),
        )
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
