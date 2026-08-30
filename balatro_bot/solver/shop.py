"""Совет по покупкам в магазине — второй кусок Фазы 8 плана («Стратегия рана»).

Та же логика, что у `solver/skip.py`: не гадать эффект случайного будущего
магазина, а честно оценить тот, что игра уже показала (`GameState.shop`,
`shop_vouchers`, `shop_packs` — заполняются только в фазе `SHOP`).

Джокеры — единственный тип предмета, для которого можно посчитать реальный
прирост счёта: у нас уже есть точный движок подсчёта (`core/scoring.py`).
Оценка идёт тем же способом, что перебор порядка джокеров
(`solver.play.rank_joker_orders`) — контрфактум: «насколько вырастет лучший
счёт, если добавить этого джокера к текущим», — только не на одной руке
игрока (её в фазе `SHOP` попросту нет: `GameState.hand` пуст), а по
нескольким представительным рукам из колоды. Это тот же принцип
сэмплирования, что в `solver/discard.py._representative_draws` — точный
`advise()` на каждой выборке, не приближённый подсчёт, приближена только
сама выборка рук, а не сам счёт.

Когда все слоты джокеров заняты (`GameState.joker_slots`), обычная покупка
невозможна — но её место занимает продажа-замена. `joker_contributions`
считает зеркальный контрфактум: «насколько **упадёт** лучший счёт, если
убрать этого джокера из слотов» — по каждому джокеру, по тем же
представительным рукам. `evaluate_shop` цепляет самого слабого невечного
кандидата на вылет (`ReplaceCandidate`) к каждому оценённому офферу;
вердикт «менять или нет» (мёртвый груз против кратного превосходства) —
в `autopilot._decide_shop_action`, не здесь.

Часть ваучеров теперь тоже переводится в очки — Фаза 9.3, первый (самый
честный) из трёх уровней: `solver/vouchers.py`'s `evaluate_vouchers` считает
контрфактум для прямых игровых ресурсов (лишняя рука/сброс за раунд, лишняя
карта в руке), тем же способом, что джокеры здесь. Остальные ваучеры —
которые меняют не счёт конкретной руки, а правила рана целиком (скидки,
слоты, шансы редких изданий, будущий горизонт денег) — по-прежнему получают
`expected_uplift = None` с честным пояснением вместо выдуманного числа
(`VoucherOffer.note`), см. модульный докстринг `solver/vouchers.py` и
PLAN.md, 9.3, для оставшихся двух уровней. Buffoon-пак в витрине получает
оценку (`PackPurchaseOffer`, `_evaluate_pack_purchase`) — Монте-Карло
самого механизма пака: `joker_uplift` для выборки случайных реализованных
джокеров, затем дешёвый пересэмплинг «лучшие `choose` из `extra`» по
размеру пака. Контрфактум «до покупки» тут невозможен (содержимое ещё не
сгенерировано), но смоделировать распределение честного розыгрыша можно —
тот же класс, что сэмплирование сброса в `solver/discard.py`. Celestial-пак
в витрине и Arcana/Spectral/Standard — по-прежнему `None` (первый доступен
тем же приёмом по 12 планетам, отдельный кусок; остальным нужны механики
консумаблов).

Поправка на экономику (раздел 8.1 плана, было отложено при закрытии
основной части Фазы 7): покупка джокера — это не только `item.price`
долларов, но и упущенные проценты в конце ближайшего раунда. Формула
процентов и потолка (`core/economy.py`, теперь общая с `solver/vouchers.py`)
выписана из исходника игры, не по памяти. Это не сводится к самой оценке
счёта (`expected_uplift`) — доллары и очки несоизмеримы без произвольного
курса обмена, тот же принцип, что и у `core/tags.py`/`solver/skip.py`.
`JokerOffer.interest_lost` — честная, но заведомо **неполная** цифра: она
про упущенные проценты только ближайшего конца раунда, а не про весь
остаток рана (для этого нужно было бы знать число оставшихся раундов и
весь будущий денежный поток — это уже не размер задачи витрины магазина, а
Фаза 9). Потолок процентов теперь берётся точно, не по умолчанию: раньше
здесь предполагался `interest_cap=25` всегда, потому что `GameState` не
хранил уже выкупленные ваучеры — начиная с Фазы 9.3 мост парсит область
мода `used_vouchers`, и `core.economy.interest_cap(state.used_vouchers)`
честно поднимает потолок до $50/$100, если `Seed Money`/`Money Tree` уже
выкуплены. Приближением к умолчанию это остаётся только при ручном вводе
(`used_vouchers` тогда всегда пуст, тот же принцип неразличимости, что у
`GameState.deck`). Единственное исключение, которое код различает явно
независимо от ваучеров, — `Green Deck` (`deck_type == "GREEN"`), где
`game.lua` отключает проценты вовсе (`no_interest=true`): там
`interest_lost` всегда 0, а не догадка.

Второй кусок «экономики» из раздела 8.1 плана — момент рерола магазина.
`ShopAdvice.reroll_cost` (из `GameState.reroll_cost`, область `round` мода —
та же, что даёт `hands_left`/`discards_left`) — это честная цена рерола
прямо сейчас, показанная рядом с оценкой текущего предложения. Дальше этого
бот сознательно не идёт: настоящая оценка «стоит ли рероллить» требовала бы
знать распределение того, что может выпасть **вместо** текущего предложения
(шансы редкости джокера, `joker_rate` и т.п. из `game.lua`), то есть считать
не по тому, что игра уже показала, а по вероятностной модели того, чего
ещё нет, — другой по духу расчёт, чем весь остальной этот модуль (никакого
RNG сверх того, что уже видно) и более рискованный по объёму. Тот же
принцип, что `solver/skip.py`: показать разложенные числа и не сводить
решение к придуманному вердикту, а не притвориться, что оценка не нужна
вовсе.

Стикеры ставок (Фаза 9.6). На ставках `BLACK`+/`ORANGE`+/`GOLD` джокеры в
магазине приходят со стикерами `eternal`/`perishable`/`rental` — мост
парсит их в `ShopItem` из той же области `modifier`, что и издание.
`JokerOffer` показывает каждый отдельным полем, по образцу `interest_lost`:
`rental_cost_per_round` ($3 за раунд владения, `card.lua`'s
`Card:calculate_rental` — ловушка при опущенном до $1 ценнике покупки),
`perishable_rounds` (через сколько раундов игра отключит джокера, слот при
этом не освободив), `eternal` (купленного не продать — риск «бюджета слотов
при неудачной покупке»). Ни один не сворачивается в `expected_uplift`
(доллары/срок против очков — та же несоизмеримость, что у `interest_lost`) и
ни один пока не влияет на автопокупку: сделать ли `rental`/`eternal`
стоп-фактором для `autopilot._decide_shop_action` — отдельное, ещё не
принятое решение политики, ровно как с автопокупкой ваучеров."""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Final

from balatro_bot.core import economy
from balatro_bot.core.cards import Card, standard_deck
from balatro_bot.core.catalogue import is_known_joker
from balatro_bot.core.jokers import implemented_keys
from balatro_bot.core.state import GameState, JokerCard, ShopItem
from balatro_bot.solver.play import advise
from balatro_bot.solver.vouchers import VoucherOffer, evaluate_vouchers

__all__ = [
    "JokerOffer",
    "PackPurchaseOffer",
    "ReplaceCandidate",
    "ShopAdvice",
    "evaluate_shop",
    "joker_contributions",
    "joker_uplift",
]

#: Ключ Buffoon-пака в каталоге (`p_buffoon_normal_*`/`_jumbo_*`/`_mega_*`).
_BUFFOON_PACK_PREFIX: Final[str] = "p_buffoon"

#: Размер Buffoon-пака: (сколько джокеров показывают, сколько можно взять) —
#: из `game.lua`'s `P_CENTERS` (`config = {extra, choose}`). Normal — 2/1,
#: Jumbo — 4/1, Mega — 4/2.
_BUFFOON_PACK_SIZES: Final[dict[str, tuple[int, int]]] = {
    "mega": (4, 2),
    "jumbo": (4, 1),
    "normal": (2, 1),
}

#: Оценка покупки Buffoon-пака — Монте-Карло самого механизма пака:
#: считаем `joker_uplift` для `PACK_JOKER_SAMPLE` случайных реализованных
#: джокеров (по `PACK_SAMPLE_HANDS` рук каждый), затем дёшево пересэмплируем
#: в Python `PACK_SIM_TRIALS` раз — в каждом «розыгрыше» берём `extra`
#: джокеров без возврата и суммируем лучшие `choose`. Тот же класс
#: честности, что у сэмплирования сброса: приближена выборка, не сам счёт.
PACK_JOKER_SAMPLE: Final[int] = 24
PACK_SAMPLE_HANDS: Final[int] = 5
PACK_SIM_TRIALS: Final[int] = 400

#: Сколько представительных рук сэмплировать на джокера. Каждая — полный
#: точный `advise()` (перебор 218 подмножеств, ~13 мс) дважды — с текущими
#: джокерами и с добавленным кандидатом, поэтому цена растёт линейно с этим
#: числом: 12 × 2 × 13 мс ≈ 300 мс на джокера, разумно для захода в магазин
#: (нечастое событие, не полсекунды на каждый опрос `watch`, как у бросков
#: карт), но не бесплатно — потому и вынесено в константу, а не зашито.
SAMPLE_HANDS: Final[int] = 12

#: Столько карт добирается на пробную руку — как в реальной игре.
_HAND_SIZE: Final[int] = 8

#: Тот же принцип, что `solver.discard._SAMPLE_SEED`: результат должен быть
#: воспроизводимым при одном и том же состоянии, а не дребезжать между
#: вызовами.
_SAMPLE_SEED: Final[int] = 0


def _interest_lost(state: GameState, price: int) -> int:
    """Упущенные проценты в конце ближайшего раунда, если потратить `price`
    прямо сейчас — потолок процентов берётся точно, по уже выкупленным
    ваучерам (`core.economy.interest_cap`), см. модульный докстринг."""
    cap = economy.interest_cap(state.used_vouchers)
    return economy.interest(state.money, state.deck_type, cap) - economy.interest(
        state.money - price, state.deck_type, cap
    )


def joker_uplift(
    state: GameState, joker: JokerCard, deck_source: tuple[Card, ...], samples: int
) -> float:
    """Средний прирост лучшего счёта от добавления `joker` к текущим — по
    `samples` представительным рукам из `deck_source` (детерминированная,
    сеянная выборка). Общий контрфактум: оценка джокера в витрине
    (`_evaluate_joker_offer`) и оценка джокера из Buffoon-пака
    (`solver/pack.py`, `_evaluate_pack_purchase` ниже) считают одно и то же."""
    with_candidate = (*state.jokers, joker)
    rng = random.Random(_SAMPLE_SEED)
    pool = list(deck_source)
    total = 0.0
    for _ in range(samples):
        hand = tuple(rng.sample(pool, _HAND_SIZE))
        baseline = advise(replace(state, hand=hand, jokers=state.jokers), limit=1).best.score
        boosted = advise(replace(state, hand=hand, jokers=with_candidate), limit=1).best.score
        total += boosted - baseline
    return total / samples


def joker_contributions(
    state: GameState, deck_source: tuple[Card, ...], samples: int
) -> tuple[float, ...]:
    """Вклад каждого джокера в слоте — на сколько в среднем упадёт лучший
    счёт, если убрать именно его (по `samples` представительным рукам,
    сеянная выборка, как `joker_uplift`). Индекс в результате соответствует
    индексу в `state.jokers`; пустой кортеж, если джокеров нет или колода для
    сэмплирования мала.

    Зеркало `joker_uplift`: тот меряет «плюс новый джокер», этот — «минус
    существующий». Базовый счёт полного набора усредняется один раз, затем по
    разу на каждый вынутый джокер (нужно `autopilot`'у для продажи-замены,
    когда все слоты заняты — какой джокер не жалко продать под лучший оффер)."""
    if not state.jokers or len(deck_source) < _HAND_SIZE:
        return ()
    rng = random.Random(_SAMPLE_SEED)
    pool = list(deck_source)
    hands = [tuple(rng.sample(pool, _HAND_SIZE)) for _ in range(samples)]
    baselines = [advise(replace(state, hand=hand), limit=1).best.score for hand in hands]
    contributions: list[float] = []
    for i in range(len(state.jokers)):
        without = state.jokers[:i] + state.jokers[i + 1 :]
        drop = 0.0
        for hand, base in zip(hands, baselines, strict=True):
            reduced = advise(replace(state, hand=hand, jokers=without), limit=1).best.score
            drop += base - reduced
        contributions.append(drop / samples)
    return tuple(contributions)


@dataclass(frozen=True, slots=True)
class ReplaceCandidate:
    """Кого продать, чтобы освободить слот под джокера из витрины, когда все
    слоты заняты. Всегда самый слабый джокер в слотах по вкладу в счёт — один
    и тот же для всех офферов захода, поэтому вынесен в общий объект, а не в
    отдельные поля на каждый `JokerOffer`."""

    index: int
    """Индекс в `GameState.jokers`."""

    label: str

    contribution: float
    """Средний вклад в лучший счёт (`joker_contributions`) — на сколько
    упадёт счёт, если этого джокера убрать. Автопилот сравнивает его с
    `JokerOffer.expected_uplift`, решая, оправдан ли размен."""

    sell_value: int
    """Сколько денег вернёт продажа (`JokerCard.sell_value`, 0 если источник
    не прислал) — добавляется к бюджету при проверке, потянет ли размен."""


@dataclass(frozen=True, slots=True)
class JokerOffer:
    """Джокер на продажу — с попыткой оценить, насколько он поднимет счёт."""

    item: ShopItem
    affordable: bool
    has_slot: bool
    known: bool
    """Есть ли реализация эффекта (`core.catalogue.is_known_joker`). Если
    нет — оценивать нечем, `expected_uplift` остаётся `None`, честно."""

    expected_uplift: float | None
    """Средний прирост лучшего счёта по представительным рукам. `None` —
    джокер не реализован либо колода для сэмплирования пуста."""

    exact_deck: bool
    """Сэмплировали по настоящей колоде рана (`GameState.full_deck`, только
    в узком случае — раздел 8.2 плана) или по стандартным 52 картам."""

    samples: int
    """Сколько рук реально усреднено — 0, если оценка не считалась."""

    interest_lost: int
    """Упущенные проценты в конце ближайшего раунда, если купить именно
    этого джокера (`_interest_lost`) — честная, но заведомо неполная цифра,
    см. модульный докстринг. Не переводится в единицы `expected_uplift`
    (доллары и очки несоизмеримы), показывается отдельно."""

    rental_cost_per_round: int
    """`economy.RENTAL_RATE` ($3), если джокер арендный (`ShopItem.rental`),
    иначе 0. Постоянный отток денег за каждый раунд владения, не разовый как
    `interest_lost`. По той же причине, что `interest_lost`, не сворачивается
    в `expected_uplift` и не участвует в автопокупке (`autopilot`) —
    показывается человеку рядом. Цена самой покупки (`item.price`) у арендных
    джокеров игрой опущена до $1, что и делает флаг важным: без этой пометки
    дешёвый ценник выглядит выгодной сделкой."""

    perishable_rounds: int | None
    """Сколько раундов «портящийся» джокер (`ShopItem.perishable_rounds`) ещё
    проработает до отключения; `None` — не портящийся. Слот после отключения
    не освобождается. `expected_uplift` меряется на текущих руках и остаётся
    верным для тех раундов, что джокер активен — срок показывается рядом
    отдельным фактом, а не вычитается из оценки (для этого нужен горизонт
    оставшихся раундов, за рамками расчёта витрины — тот же принцип неполноты,
    что у `interest_lost`)."""

    eternal: bool
    """Вечный джокер (`ShopItem.eternal`) — купленного нельзя продать. Риск
    «бюджета слотов при неудачной покупке», не величина счёта; показывается,
    но автопокупку не блокирует (открытый вопрос политики, как и ваучеры)."""

    replaces: ReplaceCandidate | None = None
    """Когда все слоты джокеров заняты — самый слабый джокер в слотах,
    которого этот оффер мог бы заменить (продать его, купить этот). `None`,
    если есть свободный слот (замена не нужна), джокеров нет, оффер не
    оценён (`known`/`expected_uplift`), либо все джокеры вечные. Автопилот
    сравнивает `expected_uplift` с `replaces.contribution`, решая размен."""


@dataclass(frozen=True, slots=True)
class PackPurchaseOffer:
    """Бустер-пак в витрине — стоит ли платить за него. Магазин показывает
    только тип и цену, содержимое генерируется лишь при вскрытии, поэтому
    контрфактум «до покупки» невозможен (см. модульный докстринг). Оценка
    есть только у Buffoon-пака: Монте-Карло самого механизма пака — среднее
    от «взять лучшие `choose` из `extra` случайных реализованных джокеров»
    (`_evaluate_pack_purchase`), где `extra`/`choose` берутся из размера
    пака. Это уже не заведомая нижняя граница, а честная оценка ожидаемого
    прироста (у Mega-пака `choose=2` — сумма верхних двух без учёта их
    взаимодействия, чуть завышает). Прочие типы (Celestial/Arcana/Spectral/
    Standard) — честный `None`."""

    item: ShopItem
    affordable: bool
    has_slot: bool
    """Есть ли свободный слот джокера (для Buffoon-пака) — для прочих типов
    просто `True`, слот им не нужен."""

    expected_uplift: float | None
    """Ожидаемый прирост счёта от вскрытия пака (лучшие `choose` из `extra`),
    только для Buffoon-пака; `None` для остальных и когда колода для
    сэмплирования пуста."""

    exact_deck: bool
    samples: int
    note: str = ""


@dataclass(frozen=True, slots=True)
class ShopAdvice:
    """Всё, что предлагает магазин прямо сейчас, разложенное по типам."""

    jokers: tuple[JokerOffer, ...]
    """Отсортированы по `expected_uplift` по убыванию; неоценённые — в конце."""

    vouchers: tuple[VoucherOffer, ...]
    """В порядке `GameState.shop_vouchers`, без сортировки по приросту — в
    отличие от `jokers`, у половины ваучеров прироста нет вовсе (`None`, не
    ноль), сортировать по частично отсутствующей величине было бы честнее
    показать как есть, чем изобретать порядок."""

    packs: tuple[PackPurchaseOffer, ...]
    """В порядке `GameState.shop_packs`. Оценён только Buffoon-пак —
    Монте-Карло механизма пака, см. `PackPurchaseOffer`."""

    money: int

    reroll_cost: int | None
    """Текущая цена рерола (`GameState.reroll_cost`) — показывается рядом с
    оценкой текущего предложения, не как вердикт «рероллить или нет»: у
    случайной альтернативы нет честной оценки без таблицы шансов генерации
    магазина, которую бот не строит (см. модульный докстринг)."""


def evaluate_shop(state: GameState, samples: int = SAMPLE_HANDS) -> ShopAdvice | None:
    """Собрать совет по всему, что предлагает магазин — или `None`, если
    магазин сейчас пуст (не в фазе `SHOP`, либо мод ничего не прислал)."""
    if not state.shop and not state.shop_vouchers and not state.shop_packs:
        return None

    deck_source = state.full_deck if state.full_deck else standard_deck()
    exact_deck = state.full_deck is not None

    offers = [
        _evaluate_joker_offer(state, item, deck_source, exact_deck, samples)
        for item in state.shop
        if item.kind == "JOKER"
    ]
    # Неоценённые (uplift=None) должны идти последними, а не просто с
    # произвольным "маленьким" числом — сортируем парой (есть ли оценка,
    # сама оценка), а не подставляем сентинел, который мог бы случайно
    # оказаться больше настоящего отрицательного прироста.
    offers.sort(
        key=lambda offer: (
            offer.expected_uplift is not None,
            offer.expected_uplift if offer.expected_uplift is not None else 0.0,
        ),
        reverse=True,
    )

    # Все слоты заняты — купить джокера можно только через продажу-замену.
    # Вклад каждого джокера в слоте считаем один раз на заход (как выборку
    # для Buffoon-паков ниже) и цепляем самого слабого невечного кандидата
    # на вылет к каждому оценённому офферу — сам вердикт «менять или нет»
    # принимает `autopilot`.
    slots_full = state.joker_slots is not None and len(state.jokers) >= state.joker_slots
    contributions = joker_contributions(state, deck_source, samples) if slots_full else ()
    if contributions:
        sellable = [i for i, joker in enumerate(state.jokers) if not joker.eternal]
        if sellable:
            weakest = min(sellable, key=lambda i: contributions[i])
            victim = state.jokers[weakest]
            candidate = ReplaceCandidate(
                index=weakest,
                label=victim.label or victim.key,
                contribution=contributions[weakest],
                sell_value=victim.sell_value or 0,
            )
            offers = [
                replace(offer, replaces=candidate)
                if offer.known and offer.expected_uplift is not None
                else offer
                for offer in offers
            ]

    # Выборка джокеров для оценки Buffoon-паков считается один раз на весь
    # заход (каждый `joker_uplift` — два `advise()`, ~26 мс), а не заново
    # на каждый пак в витрине.
    buffoon_uplifts: list[float] | None = None
    if any(p.key.startswith(_BUFFOON_PACK_PREFIX) for p in state.shop_packs) and (
        len(deck_source) >= _HAND_SIZE
    ):
        rng = random.Random(_SAMPLE_SEED)
        keys = sorted(implemented_keys())
        pool = rng.sample(keys, min(PACK_JOKER_SAMPLE, len(keys)))
        buffoon_uplifts = [
            joker_uplift(state, JokerCard(key=key), deck_source, PACK_SAMPLE_HANDS) for key in pool
        ]

    return ShopAdvice(
        jokers=tuple(offers),
        vouchers=evaluate_vouchers(state, samples),
        packs=tuple(
            _evaluate_pack_purchase(state, item, exact_deck, buffoon_uplifts)
            for item in state.shop_packs
        ),
        money=state.money,
        reroll_cost=state.reroll_cost,
    )


def _buffoon_pack_size(key: str) -> tuple[int, int]:
    """`(extra, choose)` — сколько джокеров пак показывает и сколько можно
    взять. По подстроке в ключе (`p_buffoon_mega_1` и т.п.); по умолчанию —
    normal."""
    for tag, size in _BUFFOON_PACK_SIZES.items():
        if tag in key:
            return size
    return _BUFFOON_PACK_SIZES["normal"]


def _evaluate_pack_purchase(
    state: GameState, item: ShopItem, exact_deck: bool, buffoon_uplifts: list[float] | None
) -> PackPurchaseOffer:
    """Оценить покупку одного пака из витрины — Монте-Карло механизма пака,
    только для Buffoon (см. `PACK_SIM_TRIALS`). `buffoon_uplifts` — общая на
    весь заход выборка `joker_uplift` реализованных джокеров (`evaluate_shop`
    считает её один раз); `None` — не Buffoon-пак или колода неизвестна."""
    affordable = state.money >= item.price
    has_slot = state.joker_slots is None or len(state.jokers) < state.joker_slots

    def _offer(uplift: float | None, used: int, note: str) -> PackPurchaseOffer:
        return PackPurchaseOffer(item, affordable, has_slot, uplift, exact_deck, used, note)

    if not item.key.startswith(_BUFFOON_PACK_PREFIX):
        return _offer(None, 0, "оценивается только Buffoon-пак — прочие нужны механики консумаблов")
    if buffoon_uplifts is None:
        return _offer(None, 0, "колода для выборки неизвестна")

    extra, choose = _buffoon_pack_size(item.key)
    extra = min(extra, len(buffoon_uplifts))
    sim = random.Random(_SAMPLE_SEED)
    total = 0.0
    for _ in range(PACK_SIM_TRIALS):
        drawn = sorted(sim.sample(buffoon_uplifts, extra), reverse=True)
        total += sum(drawn[:choose])
    note = f"оценка: лучшие {choose} из {extra} случайных джокеров (выборка {len(buffoon_uplifts)})"
    if choose > 1:
        note += "; сумма верхних без учёта их взаимодействия"
    return _offer(total / PACK_SIM_TRIALS, len(buffoon_uplifts), note)


def _evaluate_joker_offer(
    state: GameState,
    item: ShopItem,
    deck_source: tuple[Card, ...],
    exact_deck: bool,
    samples: int,
) -> JokerOffer:
    affordable = state.money >= item.price
    has_slot = state.joker_slots is None or len(state.jokers) < state.joker_slots
    known = is_known_joker(item.key)

    def _offer(expected_uplift: float | None, used_samples: int) -> JokerOffer:
        return JokerOffer(
            item=item,
            affordable=affordable,
            has_slot=has_slot,
            known=known,
            expected_uplift=expected_uplift,
            exact_deck=exact_deck,
            samples=used_samples,
            interest_lost=_interest_lost(state, item.price),
            rental_cost_per_round=economy.RENTAL_RATE if item.rental else 0,
            perishable_rounds=item.perishable_rounds,
            eternal=item.eternal,
            replaces=None,
        )

    if not known or len(deck_source) < _HAND_SIZE:
        return _offer(None, 0)

    candidate = JokerCard(key=item.key, label=item.label, edition=item.edition)
    return _offer(joker_uplift(state, candidate, deck_source, samples), samples)
