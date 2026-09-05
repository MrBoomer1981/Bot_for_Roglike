"""Совет по скипу блайнда: играть его или пропустить ради тега.

Раздел 8 плана («Стратегия рана») начинается с этого куска, а не с полной
симуляции рана: экран выбора блайнда — реальное, уже случившееся состояние
(требования очков и текст тега известны точно из `GameState.blinds`), а не
то, что нужно предсказывать по вероятностям. Полная симуляция ранов остаётся
отдельной, более поздней задачей (см. `PLAN.md`, раздел 8.1) — здесь честно
оцениваем только то решение, которое игра уже показала.

Числа, которые не сходятся с реальностью в один клик, — просто не
показываем как число: `_tag_dollars` возвращает `None`, если формула тега
(`core/tags.py`) требует счётчик уровня всего рана (сыгранные руки,
неиспользованные сбросы, число скипов), а мод его не присылает нигде в
схеме (`openrpc.json` — только `round.*`, per-раунд). Показывать текст
формулы вместо выдуманного числа — тот же принцип честности, что и
`ScoreOutcome.exact`/`DiscardOption.exact` в остальном проекте.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Final

from balatro_bot.core.cards import Card, standard_deck
from balatro_bot.core.state import GameState
from balatro_bot.core.tags import TAGS, TagEffect
from balatro_bot.solver.play import advise

__all__ = ["SkipAdvice", "evaluate_skip"]

#: Базовая денежная награда за победу (game.lua: `bl_small.dollars = 3`,
#: `bl_big.dollars = 4`). Боссовый блайнд скипнуть нельзя, поэтому здесь его
#: намеренно нет.
_BASE_REWARD: Final[dict[str, int]] = {"SMALL": 3, "BIG": 4}

#: $1 за каждую руку из тех, что останутся неиспользованными при победе
#: (`state_events.lua`: `hands_left * (money_per_hand or 1)`).
_MONEY_PER_HAND: Final[int] = 1

#: Investment Tag — фиксированная сумма (`game.lua`: `tag_investment.config.dollars`).
_INVESTMENT_DOLLARS: Final[float] = 25.0

#: Economy Tag — потолок прибавки (`game.lua`: `tag_economy.config.max`).
_ECONOMY_CAP: Final[float] = 40.0

#: Улучшение A14, уровень 1 — теги, чей эффект движок уже умеет считать.
#: Значение — как оценивать: паковые сводятся к бесплатному Mega-паку
#: соответствующего типа, `Orbital Tag` — к подъёму уровня руки.
#: Ключи по `game.lua`, размеры паков берутся из `solver/shop.py`, где
#: они уже выписаны (`_CELESTIAL_PACK_SIZES`/`_BUFFOON_PACK_SIZES`).
_SCORE_TAGS: Final[frozenset[str]] = frozenset({"Meteor Tag", "Buffoon Tag", "Orbital Tag"})

#: `Orbital Tag` поднимает уровень руки сразу на столько (`game.lua`:
#: `tag_orbital.config.levels`). Какой именно тип руки — случайный, поэтому
#: оценка усредняется по всем типам.
_ORBITAL_LEVELS: Final[int] = 3

#: Улучшение A14, уровень 3 — структурная ценность по той же условной
#: шкале 1–8, что у ваучеров (`solver/vouchers.py._HEURISTIC_VALUES`), и
#: **с тем же якорем**: `v_antimatter` (+1 слот джокера) там стоит 8.0 как
#: самое ценное структурное улучшение. `Negative Tag` даёт ровно это же —
#: следующий купленный джокер получает издание Negative, а оно и есть +1
#: слот, — поэтому у него та же восьмёрка, а не отдельно выдуманное число.
#:
#: Единицы сравнимы **друг с другом** и с ваучерной шкалой, но не
#: складываются ни с очками, ни с долларами: это назначенная оценка, а не
#: посчитанная, и живёт она в отдельном поле именно поэтому.
_HEURISTIC_TAGS: Final[dict[str, float]] = {
    "Negative Tag": 8.0,
    "Rare Tag": 6.0,
    "Polychrome Tag": 6.0,
    "Holographic Tag": 5.0,
    "Uncommon Tag": 4.0,
    "Voucher Tag": 4.0,
    "Coupon Tag": 4.0,
    "Foil Tag": 3.0,
    "D6 Tag": 3.0,
    "Double Tag": 3.0,
    "Top-up Tag": 3.0,
    "Boss Tag": 2.0,
    "Juggle Tag": 2.0,
}

#: Пояснение к каждой структурной оценке — как `_HEURISTIC_NOTES` у
#: ваучеров: назначенное число обязано быть объяснено, иначе его нельзя
#: ни проверить, ни пересмотреть.
_HEURISTIC_NOTES: Final[dict[str, str]] = {
    "Negative Tag": "издание Negative — это +1 слот джокера, как v_antimatter",
    "Rare Tag": "следующий джокер витрины гарантированно Rare",
    "Polychrome Tag": "издание Polychrome бесплатно (×1.5 множителя джокеру)",
    "Holographic Tag": "издание Holographic бесплатно (+10 множителя)",
    "Uncommon Tag": "следующий джокер витрины гарантированно Uncommon",
    "Voucher Tag": "в следующем магазине появится ещё один ваучер",
    "Coupon Tag": "джокеры и паки следующего магазина бесплатны",
    "Foil Tag": "издание Foil бесплатно (+50 фишек)",
    "D6 Tag": "первый реролл следующего магазина бесплатный",
    "Double Tag": "следующий тег сработает дважды",
    "Top-up Tag": "до двух обычных джокеров сразу, если есть слоты",
    "Boss Tag": "переброс боссового блайнда этого анте",
    "Juggle Tag": "+3 к размеру руки на один раунд",
}

#: Теги, чью ценность проект честно не берётся оценивать, и почему.
#: Не молчание — на экране всё равно печатается причина.
_UNVALUED_TAGS: Final[dict[str, str]] = {
    "Standard Tag": "бесплатный Mega Standard Pack — игральные карты проект не оценивает",
    "Charm Tag": "бесплатный Mega Arcana Pack — Таро из пака проект не оценивает",
    "Ethereal Tag": "бесплатный Spectral Pack — Spectral проект не оценивает",
}

#: Порядок блайндов анте — нужен, чтобы найти «следующий» относительно
#: выбираемого сейчас.
_ORDER: Final[tuple[str, str, str]] = ("small", "big", "boss")

_TAGS_BY_NAME: Final[dict[str, TagEffect]] = {effect.name: effect for effect in TAGS.values()}


@dataclass(frozen=True, slots=True)
class SkipAdvice:
    """Разложенные числа для решения «играть или скипнуть» — без готового
    вердикта: часть тегов принципиально не сводится к одному числу
    (раздел `core/tags.py`), поэтому вердикт — за человеком."""

    blind_kind: str
    """`SMALL` или `BIG` — какой блайнд сейчас можно скипнуть."""

    required_score: int
    next_blind_kind: str
    next_required_score: int
    requirement_ratio: float
    """`next_required_score / required_score` — во сколько раз следующий
    блайнд анте тяжелее этого. Не требует руки: чистая арифметика по уже
    известным требованиям (раздел 4.3 обсуждения — идея «запас прочности»
    без симуляции руки, которой на этом экране всё равно ещё нет)."""

    play_reward_min: int
    """Гарантированная часть денежной награды за победу — без бонуса за
    неиспользованные руки: их точное число для ещё не начатого блайнда мод
    не показывает, поэтому в само число не включаем, только в подсказку."""

    play_reward_hint: str

    tag_name: str
    tag_effect: str
    tag: TagEffect | None
    """`None`, если тег не опознан (`core/tags.py` не содержит такого имени —
    честно, а не молча игнорировать, тот же принцип, что и с джокерами)."""

    tag_dollars: float | None
    tag_dollars_note: str

    tag_uplift: float | None = None
    """Уровень 1 (улучшение A14): прирост лучшего счёта в **очках**, если
    эффект тега движок умеет посчитать — паковые теги сводятся к
    бесплатному Mega-паку, `Orbital Tag` к подъёму уровня руки. `None` у
    всех остальных."""

    tag_heuristic: float | None = None
    """Уровень 3: назначенная структурная оценка по условной шкале 1–8,
    общей с `VoucherOffer.heuristic_value`. Отдельным полем, а не флагом
    приближённости у `tag_uplift`, по той же причине, что у ваучеров:
    посчитанное и назначенное нельзя держать в одном поле."""


def evaluate_skip(state: GameState) -> SkipAdvice | None:
    """Собрать разложенные числа для решения — или `None`, если сейчас не
    экран выбора блайнда.

    Боссовый блайнд не участвует в поиске: его нельзя скипнуть, и статус
    `SELECT` у него означает «нужно сыграть», а не «можно выбрать скип».
    """
    for key in ("small", "big"):
        blind = state.blinds.get(key)
        if blind is not None and blind.status == "SELECT":
            selectable_key, selectable = key, blind
            break
    else:
        return None

    next_key = _ORDER[_ORDER.index(selectable_key) + 1]
    next_blind = state.blinds.get(next_key)
    ratio = (
        next_blind.required_score / selectable.required_score
        if next_blind is not None and selectable.required_score > 0
        else float("nan")
    )

    tag = _TAGS_BY_NAME.get(selectable.tag_name)
    dollars, note = _tag_dollars(selectable.tag_name, state)
    uplift, uplift_note = _tag_uplift(selectable.tag_name, state)
    heuristic = _HEURISTIC_TAGS.get(selectable.tag_name)
    if uplift_note:
        note = uplift_note
    elif heuristic is not None:
        note = _HEURISTIC_NOTES[selectable.tag_name]
    elif selectable.tag_name in _UNVALUED_TAGS:
        note = _UNVALUED_TAGS[selectable.tag_name]

    return SkipAdvice(
        blind_kind=selectable.kind,
        required_score=selectable.required_score,
        next_blind_kind=next_blind.kind if next_blind else "",
        next_required_score=next_blind.required_score if next_blind else 0,
        requirement_ratio=ratio,
        play_reward_min=_BASE_REWARD.get(selectable.kind, 0),
        play_reward_hint=(
            f"+ ${_MONEY_PER_HAND} за каждую неиспользованную руку сверху "
            "(сколько рук останется — известно только после начала блайнда)"
        ),
        tag_name=selectable.tag_name,
        tag_effect=selectable.tag_effect,
        tag=tag,
        tag_dollars=dollars,
        tag_dollars_note=note,
        tag_uplift=uplift,
        tag_heuristic=heuristic,
    )


def _tag_uplift(name: str, state: GameState) -> tuple[float | None, str]:
    """Уровень 1 (улучшение A14): ценность тега **в очках**, посчитанная тем
    же движком, что и всё остальное.

    Три тега сводятся к тому, что проект уже умеет оценивать:
    `Meteor Tag` — бесплатный Mega Celestial-пак, `Buffoon Tag` — бесплатный
    Mega Buffoon-пак, `Orbital Tag` — подъём уровня одного типа руки на
    `_ORBITAL_LEVELS`. Всё считается существующей машинерией
    `solver/shop.py` (`_monte_carlo_pack` по пулу приростов), новых формул
    здесь нет.

    **Считается лениво**: пул приростов стоит 2–10 секунд (замерено), а
    экран выбора блайнда случается за ран десятки раз. Поэтому дорогая часть
    трогается, только если на экране действительно лежит один из этих трёх
    тегов, — иначе функция возвращает `None` мгновенно.

    Кеш выборок из `solver/shop.py` намеренно **не** переиспользуется: его
    ключ не описывает состояние экрана выбора блайнда, а растягивание ключа
    под новый экран — это ровно тот дефект с устаревшими выборками, который
    ловило улучшение A11."""
    if name not in _SCORE_TAGS:
        return None, ""

    # Импорт на месте: `skip` -> `shop` нужен только этой ветке, а `shop`
    # тянет за собой весь солвер. На горячем пути (тега нет) его не будет.
    from balatro_bot.solver import shop

    deck_source = state.full_deck or state.deck or standard_deck()
    if len(deck_source) < shop.HAND_SIZE:
        return None, "колода для выборки слишком мала"

    if name == "Orbital Tag":
        return _orbital_uplift(state, deck_source), (
            f"+{_ORBITAL_LEVELS} уровня случайному типу руки — усреднено по всем типам"
        )

    if name == "Meteor Tag":
        пул = shop.planet_uplift_pool(state, deck_source)
        extra, choose = shop.CELESTIAL_PACK_SIZES["mega"]
        подпись = "бесплатный Mega Celestial-пак"
    else:  # Buffoon Tag
        пул = shop.random_joker_uplift_pool(state, deck_source)
        extra, choose = shop.BUFFOON_PACK_SIZES["mega"]
        подпись = "бесплатный Mega Buffoon-пак"
    if not пул:
        return None, "нечем оценить содержимое пака"
    return shop.monte_carlo_pack(пул, extra, choose), подпись


def _orbital_uplift(state: GameState, deck_source: tuple[Card, ...]) -> float:
    """Средний прирост от подъёма одного типа руки на `_ORBITAL_LEVELS`.

    Какой именно тип поднимет тег — случайно, поэтому берём среднее по всем
    типам: это матожидание, а не выбор лучшего, — выбирать бот тут не может.
    """
    from balatro_bot.solver import shop
    from balatro_bot.solver.pack import PLANET_HAND_TYPES, level_up

    rng = random.Random(shop.SAMPLE_SEED)
    pool = list(deck_source)
    hands = [tuple(rng.sample(pool, shop.HAND_SIZE)) for _ in range(shop.PACK_SAMPLE_HANDS)]
    baselines = [advise(replace(state, hand=hand), limit=1).best.score for hand in hands]

    total = 0.0
    for hand_type in PLANET_HAND_TYPES.values():
        поднятое = state
        for _ in range(_ORBITAL_LEVELS):
            поднятое = level_up(поднятое, hand_type)
        for hand, base in zip(hands, baselines, strict=True):
            total += advise(replace(поднятое, hand=hand), limit=1).best.score - base
    return total / (len(PLANET_HAND_TYPES) * len(hands))


def _tag_dollars(name: str, state: GameState) -> tuple[float | None, str]:
    """Точная денежная цена тега — только где формула не требует счётчика
    уровня рана, которого мод не присылает (см. модульный докстринг)."""
    if name == "Investment Tag":
        return _INVESTMENT_DOLLARS, "после победы над Boss Blind этого анте — условие, не гарантия"
    if name == "Economy Tag":
        bonus = min(_ECONOMY_CAP, max(0, state.money))
        return bonus, f"удвоение текущих ${state.money}, прибавка не больше ${_ECONOMY_CAP:g}"
    if not name:
        return None, ""
    return None, "формула требует счётчик уровня рана (см. core/tags.py) — мод его не присылает"
