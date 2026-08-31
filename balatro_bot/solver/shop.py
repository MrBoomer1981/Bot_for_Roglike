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
PLAN.md, 9.3, для оставшихся двух уровней. Buffoon- и Celestial-пак в
витрине получают оценку (`PackPurchaseOffer`, `_evaluate_pack_purchase`) —
Монте-Карло самого механизма пака: для Buffoon — `joker_uplift` по выборке
случайных реализованных джокеров, для Celestial (улучшение A3) — прирост от
подъёма уровня каждого из 12 типов руки (`_planet_uplift_pool`, общий
`solver.pack.level_up`); затем в обоих случаях дешёвый пересэмплинг «лучшие
`choose` из `extra`» по размеру пака (`_monte_carlo_pack`). Контрфактум «до
покупки» тут невозможен (содержимое ещё не сгенерировано), но смоделировать
распределение честного розыгрыша можно — тот же класс, что сэмплирование
сброса в `solver/discard.py`. Планеты слот консумабля не занимают (берутся
и применяются сразу), поэтому `has_slot` у Celestial-оффера всегда `True`.
Arcana/Spectral/Standard-паки — по-прежнему `None` (нужен пласт механик
консумаблов/карт колоды).

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

Второй кусок «экономики» из раздела 8.1 плана — момент рерола магазина
(улучшение A5). `RerollOutlook` (`ShopAdvice.reroll`) — это уже оценка, а не
только цена: единственное место в модуле, где считается не то, что игра
показала, а вероятностная модель того, что выпадет **вместо**. Монте-Карло
самого механизма ролла: каждый из `shop_slots` слотов витрины независимо
становится джокером с вероятностью `SHOP_JOKER_RATE / сумма ставок`
(`core/economy.py`, из `game.lua`'s `GAME_MOD`), а прирост джокера берётся
из той же выборки случайных реализованных джокеров, что и оценка Buffoon-
пака (`random_joker_uplifts`, считается один раз на заход). Тот же класс
честности, что у сэмплирования сброса: приближены выборка и вероятностная
модель, не сам счёт. Ограничение, честно вынесенное в `RerollOutlook.note`:
редкости (`game.lua`: 70/25/5 Common/Uncommon/Rare) выборка отражает лишь
усреднением по реализованным джокерам, без стратификации по трём пулам —
дораскладка следующим шагом, если живые прогоны покажут смещение. Сам
вердикт «рероллить или нет» — в `autopilot._decide_reroll_action` (запас
денег над ценой, ожидаемый прирост против той же доли требования блайнда,
что у покупки джокера), не здесь.

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
    "RerollOutlook",
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

#: Ключ Celestial-пака (`p_celestial_normal_*`/`_jumbo_*`/`_mega_*`).
_CELESTIAL_PACK_PREFIX: Final[str] = "p_celestial"

#: Размер Celestial-пака: (сколько планет показывают, сколько можно взять) —
#: из `game.lua`'s `P_CENTERS`. Normal — 3/1, Jumbo — 5/1, Mega — 5/2.
_CELESTIAL_PACK_SIZES: Final[dict[str, tuple[int, int]]] = {
    "mega": (5, 2),
    "jumbo": (5, 1),
    "normal": (3, 1),
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

#: Вместимость витрины по умолчанию, если источник состояния её не прислал
#: (`GameState.shop_slots is None` — ручной ввод). `game.lua`: `joker_max`
#: стартует с 2.
_DEFAULT_SHOP_SLOTS: Final[int] = 2

#: Сумма весов типов карт в слоте витрины (`core.economy`) — джокер выпадает
#: с вероятностью `SHOP_JOKER_RATE / _SHOP_TOTAL_RATE`.
_SHOP_TOTAL_RATE: Final[int] = (
    economy.SHOP_JOKER_RATE + economy.SHOP_TAROT_RATE + economy.SHOP_PLANET_RATE
)


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
class RerollOutlook:
    """Стоит ли рероллить витрину — улучшение A5. В отличие от всего
    остального в этом модуле, здесь оценивается не то, что игра уже
    показала, а вероятностная модель того, что выпадет **вместо**: Монте-
    Карло самого механизма ролла. Каждый из `slots` слотов витрины
    независимо становится джокером с вероятностью
    `economy.SHOP_JOKER_RATE / сумма ставок` (иначе Таро/Планета — их вклад
    в счёт тут не моделируется, консервативный ноль), а прирост джокера
    берётся из той же выборки случайных реализованных джокеров, что и оценка
    Buffoon-пака. Редкости (`game.lua`: 70/25/5 Common/Uncommon/Rare) выборка
    отражает лишь косвенно — усреднением по реализованным джокерам, без
    стратификации (`note` про это говорит); дораскладка по редкости —
    следующий шаг, если живые прогоны покажут смещение."""

    cost: int
    """Цена рерола прямо сейчас (`GameState.reroll_cost`) — растёт на $1
    после каждого ролла в этом заходе."""

    affordable: bool
    """Хватает ли денег (`GameState.money >= cost`)."""

    expected_best_uplift: float | None
    """Матожидание лучшего прироста среди `slots` свежих слотов (Монте-Карло,
    `PACK_SIM_TRIALS` розыгрышей). `None` — колода для выборки неизвестна
    (`GameState.full_deck` пуст и стандартной не хватило) либо нет ни одного
    реализованного джокера. Матожидание может быть перекошено хвостом
    (5 % шанс редкого сильного джокера тянет среднее вверх) — политика
    автопилота это учитывает запасом."""

    slots: int
    """Сколько слотов витрины перезаполнит реролл (`GameState.shop_slots`
    или `_DEFAULT_SHOP_SLOTS`)."""

    samples: int
    """Размер выборки джокеров, по которой считалась оценка (0, если не
    считалась)."""

    exact_deck: bool
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

    reroll: RerollOutlook | None
    """Оценка рерола витрины (улучшение A5) — Монте-Карло самого механизма
    ролла, см. `RerollOutlook`. `None` — не в фазе `SHOP` либо источник не
    прислал `reroll_cost` (ручной ввод)."""


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

    # Выборка «прирост случайного реализованного джокера» — общая для оценки
    # Buffoon-пака и оценки рерола (A5, реролл — тот же механизм «свежие
    # случайные джокеры»). Считается один раз на весь заход (каждый
    # `joker_uplift` — два `advise()`, ~26 мс), а не заново на каждый пак и не
    # ради каждой прикидки рерола. Нужна, если есть Buffoon-пак либо реролл
    # по карману прямо сейчас (`money >= reroll_cost`); если денег на ролл нет,
    # оценку не считаем вовсе — это лишние ~24 × 2 `advise()` на каждый заход.
    reroll_affordable = state.reroll_cost is not None and state.money >= state.reroll_cost
    random_joker_uplifts: list[float] | None = None
    if len(deck_source) >= _HAND_SIZE and (
        reroll_affordable
        or any(p.key.startswith(_BUFFOON_PACK_PREFIX) for p in state.shop_packs)
    ):
        rng = random.Random(_SAMPLE_SEED)
        keys = sorted(implemented_keys())
        pool = rng.sample(keys, min(PACK_JOKER_SAMPLE, len(keys)))
        random_joker_uplifts = [
            joker_uplift(state, JokerCard(key=key), deck_source, PACK_SAMPLE_HANDS) for key in pool
        ]

    # То же самое для Celestial-паков — прирост от подъёма уровня каждого из
    # 12 типов руки на общей выборке рук (один baseline, 12 «прокачанных»).
    planet_uplifts = (
        _planet_uplift_pool(state, deck_source)
        if any(p.key.startswith(_CELESTIAL_PACK_PREFIX) for p in state.shop_packs)
        and len(deck_source) >= _HAND_SIZE
        else None
    )

    return ShopAdvice(
        jokers=tuple(offers),
        vouchers=evaluate_vouchers(state, samples),
        packs=tuple(
            _evaluate_pack_purchase(state, item, exact_deck, random_joker_uplifts, planet_uplifts)
            for item in state.shop_packs
        ),
        money=state.money,
        reroll=_evaluate_reroll(state, random_joker_uplifts, exact_deck),
    )


def _planet_uplift_pool(state: GameState, deck_source: tuple[Card, ...]) -> list[float]:
    """Прирост лучшего счёта от подъёма уровня каждого из 12 типов руки на
    один — по `PACK_SAMPLE_HANDS` представительным рукам. Базовый счёт
    считается один раз, затем по разу на каждый прокачанный тип. Нужен для
    Монте-Карло покупки Celestial-пака (`_evaluate_pack_purchase`)."""
    # shop <-> pack — обоюдный цикл (pack берёт отсюда `joker_uplift`),
    # поэтому импорт отложенный, на месте.
    from balatro_bot.solver.pack import PLANET_HAND_TYPES, level_up

    rng = random.Random(_SAMPLE_SEED)
    pool = list(deck_source)
    hands = [tuple(rng.sample(pool, _HAND_SIZE)) for _ in range(PACK_SAMPLE_HANDS)]
    baselines = [advise(replace(state, hand=hand), limit=1).best.score for hand in hands]
    uplifts: list[float] = []
    for hand_type in PLANET_HAND_TYPES.values():
        leveled = level_up(state, hand_type)
        delta = sum(
            advise(replace(leveled, hand=hand), limit=1).best.score - base
            for hand, base in zip(hands, baselines, strict=True)
        )
        uplifts.append(delta / len(hands))
    return uplifts


def _pack_size(key: str, sizes: dict[str, tuple[int, int]]) -> tuple[int, int]:
    """`(extra, choose)` — сколько карт пак показывает и сколько можно взять.
    По подстроке в ключе (`p_buffoon_mega_1` и т.п.); по умолчанию — normal."""
    for tag, size in sizes.items():
        if tag in key:
            return size
    return sizes["normal"]


def _monte_carlo_pack(uplifts: list[float], extra: int, choose: int) -> float:
    """Среднее от «взять лучшие `choose` из `extra` случайных карт» —
    `PACK_SIM_TRIALS` пересэмплирований без возврата. Общий механизм для
    Buffoon (джокеры) и Celestial (планеты)."""
    extra = min(extra, len(uplifts))
    sim = random.Random(_SAMPLE_SEED)
    total = 0.0
    for _ in range(PACK_SIM_TRIALS):
        drawn = sorted(sim.sample(uplifts, extra), reverse=True)
        total += sum(drawn[:choose])
    return total / PACK_SIM_TRIALS


def _monte_carlo_reroll(uplifts: list[float], slots: int) -> float:
    """Матожидание лучшего прироста среди `slots` свежих слотов витрины
    после рерола (улучшение A5). Каждый слот независимо: джокер с
    вероятностью `SHOP_JOKER_RATE / _SHOP_TOTAL_RATE` (прирост — случайный
    из `uplifts`, с возвратом: слоты роллятся независимо), иначе Таро/
    Планета — их вклад в счёт тут ноль (не моделируется, консервативно
    занижает). `PACK_SIM_TRIALS` розыгрышей, сид фиксирован."""
    p_joker = economy.SHOP_JOKER_RATE / _SHOP_TOTAL_RATE
    sim = random.Random(_SAMPLE_SEED)
    total = 0.0
    for _ in range(PACK_SIM_TRIALS):
        best = 0.0
        for _ in range(slots):
            if sim.random() < p_joker:
                best = max(best, sim.choice(uplifts))
        total += best
    return total / PACK_SIM_TRIALS


def _evaluate_reroll(
    state: GameState, random_joker_uplifts: list[float] | None, exact_deck: bool
) -> RerollOutlook | None:
    """Оценить рерол витрины — Монте-Карло самого механизма ролла, см.
    `RerollOutlook`. `None`, если `GameState.reroll_cost` не прислан (ручной
    ввод либо не фаза `SHOP`) — рероллить тогда всё равно нечем."""
    if state.reroll_cost is None:
        return None
    cost = state.reroll_cost
    affordable = state.money >= cost
    slots = state.shop_slots if state.shop_slots is not None else _DEFAULT_SHOP_SLOTS
    if not random_joker_uplifts:
        # Выборка не считалась: либо реролл не по карману (тогда оценка ролла
        # всё равно ни на что не влияет), либо колода для выборки мала.
        note = "не по карману — оценка ролла не считалась" if not affordable else (
            "колода для выборки неизвестна"
        )
        return RerollOutlook(
            cost=cost,
            affordable=affordable,
            expected_best_uplift=None,
            slots=slots,
            samples=0,
            exact_deck=exact_deck,
            note=note,
        )
    expected_best = _monte_carlo_reroll(random_joker_uplifts, slots)
    note = (
        f"оценка: лучший из {slots} слот(ов), джокер с вероятностью "
        f"{economy.SHOP_JOKER_RATE}/{_SHOP_TOTAL_RATE} "
        f"(выборка {len(random_joker_uplifts)} джокеров, редкости не стратифицированы)"
    )
    return RerollOutlook(
        cost=cost,
        affordable=affordable,
        expected_best_uplift=expected_best,
        slots=slots,
        samples=len(random_joker_uplifts),
        exact_deck=exact_deck,
        note=note,
    )


def _evaluate_pack_purchase(
    state: GameState,
    item: ShopItem,
    exact_deck: bool,
    buffoon_uplifts: list[float] | None,
    planet_uplifts: list[float] | None,
) -> PackPurchaseOffer:
    """Оценить покупку одного пака из витрины — Монте-Карло механизма пака
    (лучшие `choose` из `extra` случайных карт, `PACK_SIM_TRIALS` розыгрышей).
    Работает для Buffoon (джокеры, `buffoon_uplifts`) и Celestial (планеты,
    `planet_uplifts`) — обе выборки `evaluate_shop` считает по разу на заход.
    Прочие типы (Arcana/Spectral/Standard) — честный `None`."""
    affordable = state.money >= item.price
    # Планеты из пака используются сразу, слот консумабля им не нужен —
    # `has_slot` осмыслен только для Buffoon.
    is_buffoon = item.key.startswith(_BUFFOON_PACK_PREFIX)
    has_slot = (
        state.joker_slots is None or len(state.jokers) < state.joker_slots if is_buffoon else True
    )

    def _offer(uplift: float | None, used: int, note: str) -> PackPurchaseOffer:
        return PackPurchaseOffer(item, affordable, has_slot, uplift, exact_deck, used, note)

    if is_buffoon:
        if buffoon_uplifts is None:
            return _offer(None, 0, "колода для выборки неизвестна")
        extra, choose = _pack_size(item.key, _BUFFOON_PACK_SIZES)
        uplift = _monte_carlo_pack(buffoon_uplifts, extra, choose)
        note = (
            f"оценка: лучшие {choose} из {min(extra, len(buffoon_uplifts))} "
            f"случайных джокеров (выборка {len(buffoon_uplifts)})"
        )
        if choose > 1:
            note += "; сумма верхних без учёта их взаимодействия"
        return _offer(uplift, len(buffoon_uplifts), note)

    if item.key.startswith(_CELESTIAL_PACK_PREFIX):
        if planet_uplifts is None:
            return _offer(None, 0, "колода для выборки неизвестна")
        extra, choose = _pack_size(item.key, _CELESTIAL_PACK_SIZES)
        uplift = _monte_carlo_pack(planet_uplifts, extra, choose)
        shown = min(extra, len(planet_uplifts))
        note = f"оценка: лучшие {choose} из {shown} случайных планет (из 12)"
        if choose > 1:
            note += "; сумма верхних без учёта их взаимодействия"
        return _offer(uplift, len(planet_uplifts), note)

    return _offer(None, 0, "оценивается только Buffoon/Celestial — прочим нужен пласт консумаблов")


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
