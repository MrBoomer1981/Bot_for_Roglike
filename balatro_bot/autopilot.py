"""Решение «что сделать прямо сейчас» — Фаза 9 плана («Автопилот»).

**Розыгрыш/сброс (`SELECTING_HAND`, п. 9.1)** — в основе тот же
ранжированный список, что видит человек в `advise`/`watch`
(`solver.actions.rank_actions`), но с одной поправкой поверх него.

`rank_actions` сравнивает розыгрыши и сбросы по матожиданию счёта, а у
сброса матожидание **оптимистично по построению** (`ActionOption.exact =
False` — раздел 8 `docs/Discard Spec.md`: это оценка по представительной
выборке через быструю эвристику, не точный перебор). Поэтому «сбросить к
флешу» нередко показывает число больше, чем «сыграть эту двойную пару» —
даже когда пара уже гарантированно закрывает блайнд. Человек, глядя на
список, видит пометку «хватает на блайнд» и не купится; автопилот же брал
бы голый топ-1 и разменивал верную победу на ставку. Поэтому
`decide_action` сначала проверяет `advise(state).cheapest_sufficient` —
самый экономный ход, чей **нижний предел** (`Candidate.beats`, не среднее)
уже перекрывает оставшееся требование блайнда, — и если такой есть, играет
его.

Когда гарантированного хода нет, решение всё равно не отдаётся топ-1
`rank_actions` вслепую — над ним ещё две поправки против чрезмерно
жадного сброса (улучшение B1, подтверждено живым прогоном):

- **на темпе** (`_on_pace_without_discard`): если `лучшая рука × осталось
  рук` уже перекрывает остаток требования с запасом
  (`_DISCARD_PACE_MARGIN`), блайнд добивается одними розыгрышами — играем
  лучшую руку, `advise_discard` даже не зовём. Это ловит случай, где
  `cheapest_sufficient` пуст лишь потому, что джокер с разбросом (Misprint)
  утянул нижний предел под требование, хотя матожидание вдвое выше;
- **перевес — шум** (`_discard_edge_is_noise`): если топ-1 всё-таки сброс,
  но его матожидание превосходит лучшую руку меньше чем на
  задокументированную погрешность самой оценки сброса (`_DISCARD_EDGE_MARGIN`,
  ±15 % из раздела 7 `docs/Discard Spec.md`) — играем руку. В живом прогоне
  автопилот так спускал последний сброс, разменивая флеш ~7 371 на цель
  ~7 427 (+0,7 %).

Обе поправки — не новый расчёт счёта, а приоритет «верное над вероятным»,
тот же принцип, что у `decide_skip`.

**Скип блайнда (`BLIND_SELECT`, п. 9.2, первый из трёх кусков)** —
`solver.skip.evaluate_skip` сознательно не даёт вердикта: часть тегов
(бесплатный джокер/ваучер/пак) принципиально не переводится в доллары без
выдумки (`core/tags.py`). Автопилоту нужен вердикт, и `decide_skip` даёт
его предельно консервативной политикой поверх уже посчитанных чисел, не
новым расчётом: скип только если у тега есть точная денежная цена
(`SkipAdvice.tag_dollars` — сейчас только `Investment`/`Economy Tag`) и она
строго больше гарантированной награды за игру (`play_reward_min`).
Структурные теги никогда не вызывают скип сами по себе — не потому что они
неважны (частый опытный выбор — как раз скипать ради них), а потому что
здесь их ценность в долларах пришлось бы выдумывать, а этот проект не
гадает. Когда скип не обоснован числом (включая случай, когда скипать
вообще нельзя — на очереди Boss Blind), решение — выбрать блайнд и играть.

**Магазин (`SHOP`, п. 9.2, второй кусок) и `ROUND_EVAL`.** Между «выиграл
раунд» и «зашёл в магазин» есть фаза `ROUND_EVAL` («забрать награду за
раунд») — решать там нечего (`cash_out` всегда нужен, чтобы вообще
продолжить), но без явного вызова автопилот застрял бы там навсегда, ровно
как без `select`/`skip` на выборе блайнда. В магазине решение — покупать
джокеров: `solver.shop.evaluate_shop` уже считает `expected_uplift` (прирост
счёта) на каждого, отсортированных по убыванию. Политика максимально
простая и честная — купить лучшего по приросту, если он известен движку
(`known`), карман потянет (`affordable`), есть слот (`has_slot`) и прирост
оправдывает слот (`_worth_buying` — улучшение A2: не просто > 0, а не ниже
`_MIN_BUY_REQ_FRACTION` от требования ближайшего блайнда, чтобы не занимать
слот почти-нулём, который тут же сочли бы мёртвым грузом; при неизвестном
требовании — откат к «> 0»). Первые три флага уже посчитаны в
`evaluate_shop`, порог A2 — единственная поправка политики.
`interest_lost` (упущенные проценты, раздел
«Магазин и порядок джокеров» плана) сознательно не участвует в самом
решении «покупать ли» — это несоизмеримая с приростом счёта величина
(доллары против очков, тот же принцип, что у `decide_skip`), только
показывается человеку рядом. Покупка — не более одной за вызов
`decide_action`: `evaluate_shop`'s контрфактум для второго джокера не
учитывает уже купленного первого (a `Blueprint`, например, зависит от
соседей), поэтому правильно пересчитывать заново после каждой покупки, а
не набирать корзину по одному-единственному снимку `evaluate_shop` — цикл
опроса (`ui/tui.py.autoplay`) и так перечитывает состояние на каждой
итерации, задача `decide_action` тут не в том, чтобы копить решения, а
в том, чтобы каждый раз отвечать честно по свежим числам.

Следом (улучшение A4) — ваучер (`_decide_voucher_action`, порог по уровню
честности оценки из `solver.vouchers`, поле `value_unit`): 1-й уровень
(`"score"`, прямой ресурс в очках) — тот же порог `_worth_buying`, что у
джокера; 2-й (`"dollars"`, денежная формула с горизонтом) — чистый плюс в
долларах, оценка не ниже цены; 3-й (`heuristic_value`, экспертная
константа — не посчитанное число) — только структурные апгрейды,
`>= _MIN_HEURISTIC_VOUCHER_VALUE`. Действовать по 3-му уровню — явное
решение пользователя (иначе это было бы то самое «гадать вместо `None`»,
что проект запрещает). Порог 3-го уровня не совсем плоский (улучшение A7):
для структурного апгрейда самого магазина (`Overstock`, +слот витрины) он
снижается, когда бот богат деньгами и у него простаивают слоты джокеров
(`_heuristic_voucher_bar`) — больше слотов витрины даёт больше шансов эти
слоты джокеров занять. Ваучер идёт после джокера (джокер — ядро стратегии
и занимает дефицитный слот), но перед паком (пак — гэмбл). Ваучер слота
не занимает.

Когда покупать джокеров брать нечего (либо ни один не проходит порог A2) —
пробуем купить Buffoon/Celestial-пак: `ShopAdvice.packs` несёт оценку
прироста (Монте-Карло «лучшие choose из extra», `PackPurchaseOffer`),
покупаем при положительной оценке, `has_slot` (у Celestial всегда `True`) и
по карману. Порог здесь остаётся «> 0», а не A2-шная доля требования: пак —
это выбор из нескольких карт (хедж), задирать ему планку сейчас значило бы
снова копить деньги впустую.

Когда все слоты заняты (`joker_slots`), обычная покупка невозможна — но
`evaluate_shop` посчитал вклад каждого джокера в слоте и прицепил самого
слабого невечного кандидата на вылет (`JokerOffer.replaces`). Политика
продажи-замены: продать жертву, если оффер строго лучше её вклада **и**
либо жертва — мёртвый груз (вклад ниже `_DEAD_JOKER_REQ_FRACTION` от
требования ближайшего блайнда), либо оффер кратно сильнее
(`_REPLACE_UPLIFT_RATIO` — защита от прокрутки продажи-покупки на шуме).
Продажа — отдельное действие: слот освободится, покупку решим на следующем
шаге по свежим числам, как и всё остальное в магазине. Ветка раздвоена
(улучшение A6): размен, захватывающий джокера, который сам прошёл бы порог
покупки в слот (`_worth_buying`), решается ДО ветки паков — пак это
низкоприоритетный хедж, а в run 6 дешёвый Celestial-пак раз за разом
опережал размен под оффер +3576. Остальные размены — после паков, как
раньше.

Когда и менять нечего — пробуем перекатить витрину (улучшение A5,
`_decide_reroll_action`). `ShopAdvice.reroll` (`RerollOutlook`) — Монте-Карло
самого механизма ролла (`joker_rate`/редкости из `game.lua`), первое место,
где бот считает не по показанному, а по вероятностной модели того, что
выпадет вместо. Рероллим, только когда: требование блайнда известно (иначе
порог не масштабировать); ожидаемый лучший прирост свежих слотов не ниже
той же доли требования, что нужна для покупки джокера в слот
(`_worth_buying`); и после оплаты остаётся запас `_REROLL_MONEY_RESERVE` —
и на саму покупку, и чтобы не спустить карман на серию роллов. Растущая
цена рерола плюс запас гасят серию за несколько ходов. Когда и рероллить не
стоит — `next_round`, уйти. Arcana/Spectral/Standard-паки по-прежнему не
тронуты: `evaluate_shop` не даёт им числа.

**Вскрытие пака (Celestial — кусок 9.2; Buffoon — 9.3).** Фаза открытого
пака у Steamodded — одна общая `SMODS_BOOSTER_OPENED` (не ванильные
`PLANET_PACK`/`BUFFOON_PACK`/...), поэтому тип пака `_decide_pack_action`
определяет по *содержимому* `state.pack` (`solver.pack.evaluate_pack`), не
по имени фазы. Celestial (карты-планеты): контрфактум level-up типа руки
на представительных руках — поднятие не может ухудшить счёт, значит
вопроса «а вдруг не нужна» нет, берём карту с максимальным приростом.
Buffoon (карты `j_*`): джокеры *видны*, тот же контрфактум через
`solver.shop.joker_uplift` (общий код), но плохой джокер прирост дать не
обязан — берём только при **строго положительном** приросте (слот
проверяется тем же условием в `_decide_shop_action` при покупке пака).
Джамбо/мега-паки не требуют отдельной ветки: если после выбора одной
карты пак остаётся открытым, `decide_action` посчитает следующий выбор
заново на следующем опросе.

Arcana/Tarot/Spectral/Standard-пак (в `state.pack` нет ни планет, ни
`j_*`): `evaluate_pack` возвращает пусто — оценить нечем, нужен пласт
механик консумаблов/карт колоды (раздел 6, п. 9.4). Но застревать нельзя:
`_decide_pack_action` возвращает `skip_pack` (взять ничего), а не `None` —
иначе ран-раннер честно фиксировал бы затык. Осознанная маленькая потеря
(иногда в паке лежит полезная карта) ради того, чтобы ран продолжался.

**Consumables перед розыгрышем (`SELECTING_HAND`, первый кусок 9.4).**
Перед тем как решать play/discard, `decide_action` сперва проверяет
`solver.consumables.evaluate_planet_consumables` — использование
Planet-карты из инвентаря политически устроено так же просто, как выбор
карты из Celestial Pack (`_decide_pack_action`): применить карту нельзя
себе во вред (level-up только добавляет фишки/множитель одному типу руки),
поэтому политика — использовать любую найденную Planet-карту сразу, не
дожидаясь положительного числа (в отличие от магазина/скипа, здесь нечего
взвешивать). Ровно одна карта за вызов `decide_action`, тем же паттерном,
что «одна покупка за вызов» в магазине: `ModBridge.use()` сразу меняет
инвентарь, а следующая карта (если такая есть) решится на уже свежем
состоянии на следующем опросе. Tarot-карты в инвентаре эта проверка не
трогает вовсе — намеренно, см. модульный докстринг `solver/consumables.py`.

**Перестановка джокеров (`SELECTING_HAND`, улучшение D1).** Следом за
проверкой консумаблов, но перед play/discard: `_decide_rearrange_action`
гоняет `solver.play.rank_joker_orders` на текущей руке и, если лучший
порядок даёт относительный прирост счёта >= `_MIN_REORDER_GAIN_FRAC`,
возвращает `Action(kind="rearrange")` (→ `ModBridge.rearrange(jokers=...)`).
Порядок влияет на счёт у копирующих (`Blueprint`/`Brainstorm`) и на
смешении `+mult`/`×mult` — раньше автопилот всегда играл в порядке слотов,
хотя `watch` перебор порядка делает по умолчанию. Отдельное действие,
розыгрыш — следующим вызовом; проверяется на каждой руке, порог отсекает
дёрганье на шуме. Кап `MAX_JOKERS_FOR_ORDER_SEARCH` (6): выше — `None`, не
гадаем."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from balatro_bot.adapters.mod_bridge import ModBridge
from balatro_bot.core.cards import Card
from balatro_bot.core.state import GameState, ShopItem
from balatro_bot.solver.actions import ActionOption, rank_actions
from balatro_bot.solver.consumables import evaluate_planet_consumables
from balatro_bot.solver.pack import PACK_OPEN_PHASES, evaluate_pack
from balatro_bot.solver.play import Advice, Candidate, advise, rank_joker_orders
from balatro_bot.solver.shop import ShopAdvice, evaluate_shop
from balatro_bot.solver.skip import SkipAdvice, evaluate_skip

__all__ = [
    "BLIND_SELECT",
    "ROUND_EVAL",
    "SELECTING_HAND",
    "SHOP",
    "Action",
    "decide_action",
    "decide_skip",
    "describe_action",
    "dispatch_action",
]

#: Фаза мода (`GameState.phase`, значение `state` в схеме мода), где в руке
#: есть карты для розыгрыша или сброса.
SELECTING_HAND = "SELECTING_HAND"

#: Фаза мода, где показывается экран выбора блайнда (сыграть или скипнуть
#: Small/Big; Boss нужно только выбрать — скипнуть нельзя).
BLIND_SELECT = "BLIND_SELECT"

#: Фаза мода сразу после победы над блайндом, до магазина — нужен `cash_out`,
#: чтобы вообще продолжить (см. модульный докстринг).
ROUND_EVAL = "ROUND_EVAL"

#: Фаза мода внутри магазина.
SHOP = "SHOP"

#: Продажа-замена джокера (`_decide_shop_action`, когда слоты полны).
#: Вклад жертвы ниже этой доли требования ближайшего блайнда — «мёртвый
#: груз», меняется на любой оффер с положительным приростом. Калибруется на
#: живых прогонах.
_DEAD_JOKER_REQ_FRACTION = 0.03

#: Если жертва не мёртвый груз — размен только когда оффер даёт как минимум
#: во столько раз больший прирост, чем её вклад. Защита от бесконечной
#: прокрутки продажи-покупки на шумных оценках.
_REPLACE_UPLIFT_RATIO = 2.0

#: Минимальный прирост джокера (`expected_uplift`), при котором его вообще
#: стоит покупать в свободный слот — та же доля требования ближайшего
#: блайнда, что и `_DEAD_JOKER_REQ_FRACTION` (улучшение A2): не занимать
#: слот тем, что тут же сочли бы мёртвым грузом. При неизвестном требовании
#: (ручной ввод, нет блайндов) откат к старому порогу «строго > 0».
#: Калибруется на живых прогонах.
_MIN_BUY_REQ_FRACTION = 0.03

#: Минимальная экспертная оценка ваучера третьего уровня
#: (`VoucherOffer.heuristic_value`, шкала ~2..8), при которой автопилот его
#: покупает (улучшение A4). Действовать по этому числу — явное решение
#: пользователя: это ранжирная оценка «по игровому смыслу», не результат
#: расчёта. Планка намеренно высокая — только структурные апгрейды
#: (`Antimatter` +слот джокера 8.0, `Glow Up` 6.0), не «чаще нужный тип в
#: магазине» (2..4). Калибруется на живых прогонах.
_MIN_HEURISTIC_VOUCHER_VALUE = 5.0

#: Улучшение A7. Структурные апгрейды самого магазина (+1 слот витрины).
#: Только для них `_heuristic_voucher_bar` снижает порог 3-го уровня, когда
#: бот богат деньгами и у него простаивают слоты джокеров — прочие
#: эвристические ваучеры остаются на базовом пороге, даже если их
#: `heuristic_value` совпадает с `Overstock` (у `v_telescope` тоже 3.0).
_STRUCTURAL_SHOP_VOUCHERS = frozenset({"v_overstock_norm", "v_overstock_plus"})

#: Улучшение A7. На сколько `_heuristic_voucher_bar` снижает
#: `_MIN_HEURISTIC_VOUCHER_VALUE` за каждый простаивающий слот джокера — но
#: не ниже `_HEURISTIC_VOUCHER_FLOOR`. В run 6 бот пропустил `Overstock`
#: ($10, +1 слот витрины, оценка 3.0) при $29 и трёх пустых слотах джокеров:
#: 5.0 − 3×1.0 = 2.0, ограничено полом 3.0 — ваучер проходит. Снижение
#: считается только когда после покупки остаётся запас `_REROLL_MONEY_RESERVE`.
#: Калибруется на живых прогонах.
_HEURISTIC_RELIEF_PER_EMPTY_SLOT = 1.0
_HEURISTIC_VOUCHER_FLOOR = 3.0

#: Улучшение A5. Сколько денег автопилот оставляет себе после рерола: реролл
#: разрешён, только если `деньги − цена_рерола >= этого`. Мешает спустить
#: весь карман на серию роллов (в живом прогоне бот доходил до $0) и
#: оставляет на саму покупку джокера, ради которого рероллят. Растущая цена
#: рерола (+$1 за ролл) плюс этот порог быстро гасят серию. ~половина
#: базового потолка процентов ($25) — деньги ниже потолка приносят $1 за
#: $5/раунд, тратить их на реролл дороже, чем кажется. Калибруется на живых
#: прогонах.
_REROLL_MONEY_RESERVE = 12

#: Минимальный относительный прирост счёта текущей руки, при котором
#: автопилот тратит ход на перестановку джокеров (улучшение D1). Ниже —
#: это шум перебора, перестановка не окупает потраченного хода. Порядок
#: влияет на счёт у копирующих (`Blueprint`/`Brainstorm`) и на смешении
#: `+mult`/`×mult`. Калибруется на живых прогонах.
_MIN_REORDER_GAIN_FRAC = 0.02

#: Улучшение B1. Запас над «голым» требованием блайнда, при котором
#: автопилот считает, что добьёт блайнд одними розыгрышами и спекулятивный
#: сброс не нужен: `лучшая рука × осталось рук` должно перекрывать остаток
#: требования хотя бы с этим множителем. Линейная экстраполяция оптимистична
#: (добор из обеднённой колоды слабее, свою лучшую руку не всегда
#: пересоберёшь), отсюда запас в половину. Калибруется на живых прогонах.
_DISCARD_PACE_MARGIN = 1.5

#: Улучшение B1. Во сколько раз матожидание сброса должно превосходить
#: лучшую доступную руку, чтобы перевес считался сигналом, а не шумом самой
#: оценки. Порог = задокументированный допуск `advise_discard` (раздел 7
#: `docs/Discard Spec.md`: отклонение до 15 %, оценка оптимистична по
#: построению) — если «преимущество» сброса меньше его же погрешности,
#: разменивать на него верный розыгрыш значит гадать. Калибруется на живых
#: прогонах.
_DISCARD_EDGE_MARGIN = 1.15


@dataclass(frozen=True, slots=True)
class Action:
    """Одно решённое действие: что вызвать у моста и с каким параметром.

    Только одно из `cards`/`indices`/`item_index` заполнено осмысленно —
    какое именно, зависит от `kind`; для `select`/`skip`/`next_round`/
    `cash_out`/`skip_pack` не нужно ничего, RPC мода вообще не принимает
    параметров (кроме самого факта скипа у `skip_pack` — `open_pack(skip=True)`,
    без индекса)."""

    kind: Literal[
        "play",
        "discard",
        "select",
        "skip",
        "buy",
        "buy_pack",
        "buy_voucher",
        "sell",
        "rearrange",
        "reroll",
        "next_round",
        "cash_out",
        "pack",
        "skip_pack",
        "use",
    ]
    cards: tuple[Card, ...] = field(default=())
    indices: tuple[int, ...] = field(default=())
    """0-based индексы `cards` в `GameState.hand` — то, что реально ждёт RPC
    мода (`play`/`discard` принимают индексы в руке, не сами карты). Для
    `rearrange` — новый порядок джокеров как перестановка их текущих
    индексов (`GameState.jokers`), карт при этом нет."""

    item_index: int | None = None
    """0-based индекс предмета в `GameState.shop` (`buy`), `GameState.shop_packs`
    (`buy_pack`), `GameState.shop_vouchers` (`buy_voucher`), `GameState.pack`
    (`pack`), `GameState.consumables` (`use`) или `GameState.jokers`
    (`sell` — какого джокера в слоте продать) — во всех случаях просто
    индекс в одноимённый кортеж состояния, поэтому поле общее, не отдельное
    на каждый RPC-метод."""

    label: str = ""
    """Название выбранного предмета для лога автопилота (`buy`/`pack` —
    иначе показать было бы нечего, `item_index` сам по себе не читается
    человеком)."""


def _indices_of(hand: tuple[Card, ...], cards: tuple[Card, ...]) -> tuple[int, ...]:
    """Индексы `cards` в `hand` — устойчиво к совпадающим по значению картам
    (если такие вообще есть в руке): каждая позиция руки используется под
    свой индекс не больше одного раза, а не через `hand.index(card)`,
    который на дублях всегда нашёл бы один и тот же первый индекс дважды.
    """
    available = list(enumerate(hand))
    indices = []
    for card in cards:
        for position, (index, candidate) in enumerate(available):
            if candidate == card:
                indices.append(index)
                del available[position]
                break
        else:
            raise ValueError(f"карта {card!r} из решения не найдена в руке")
    return tuple(indices)


def _item_index_of(items: tuple[ShopItem, ...], item: ShopItem) -> int:
    for index, candidate in enumerate(items):
        if candidate == item:
            return index
    raise ValueError(f"{item!r} не найден в текущем предложении")


def _reorder_indices(current: tuple[object, ...], desired: tuple[object, ...]) -> tuple[int, ...]:
    """Новый порядок как перестановку текущих индексов: для каждого элемента
    `desired` — его позиция в `current`, каждая позиция расходуется один раз
    (устойчиво к равным джокерам, та же идея, что `_indices_of`)."""
    available = list(enumerate(current))
    order: list[int] = []
    for element in desired:
        for position, (index, candidate) in enumerate(available):
            if candidate == element:
                order.append(index)
                del available[position]
                break
        else:
            raise ValueError(f"{element!r} из нового порядка не найден в текущем")
    return tuple(order)


def decide_skip(advice: SkipAdvice) -> bool:
    """Скипнуть ли блайнд — предельно консервативная политика, см. модульный
    докстринг. `True` только когда денежная цена тега точно известна и
    строго больше гарантированной награды за игру."""
    return advice.tag_dollars is not None and advice.tag_dollars > advice.play_reward_min


def _decide_blind_action(state: GameState) -> Action:
    """На экране выбора блайнда решение — `select` или `skip` (см. `decide_skip`).

    `evaluate_skip` возвращает `None`, когда скипать вообще нельзя (на
    очереди Boss Blind) — тогда решение единственное, тоже `select`."""
    advice = evaluate_skip(state)
    if advice is not None and decide_skip(advice):
        return Action(kind="skip")
    return Action(kind="select")


def _next_blind_requirement(state: GameState) -> int | None:
    """Требование по очкам ближайшего ещё не побеждённого блайнда — чтобы
    масштабировать пороги, не завязывая их на абсолютные очки (на анте 6
    требование в разы больше, чем на анте 2). `None`, если мод не прислал
    блайнды или их требования."""
    for key in ("small", "big", "boss"):
        info = state.blinds.get(key)
        if info is not None and info.status != "DEFEATED" and info.required_score > 0:
            return info.required_score
    return None


def _worth_buying(uplift: float, requirement: int | None) -> bool:
    """Стоит ли покупать джокера с таким приростом в свободный слот
    (улучшение A2). При известном требовании блайнда — прирост не ниже
    `_MIN_BUY_REQ_FRACTION` от него (не занимать слот почти-нулём); без
    требования — откат к старому «строго > 0»."""
    if requirement is None:
        return uplift > 0
    return uplift >= _MIN_BUY_REQ_FRACTION * requirement


def _decide_replace_action(
    state: GameState, advice: ShopAdvice, requirement: int | None, *, strong_only: bool = False
) -> Action | None:
    """Все слоты джокеров заняты — продать самого слабого, если в витрине
    есть заметно лучший (`JokerOffer.replaces`, посчитан в `evaluate_shop`).
    Размен, если оффер строго лучше вклада жертвы **и** либо жертва —
    мёртвый груз (вклад мал в доле требования блайнда), либо оффер кратно
    сильнее (`_REPLACE_UPLIFT_RATIO`). `None` — менять нечего.

    `strong_only=True` (улучшение A6) — брать только размен, чей
    захватываемый оффер сам прошёл бы порог покупки джокера в слот
    (`_worth_buying`): такой размен ценнее дешёвого пака и решается ДО ветки
    паков (в run 6 оффер +3576 висел незанятым 2–3 опроса, пока его раз за
    разом опережал Celestial-пак на ~44). Требует известного требования
    блайнда — иначе `_worth_buying` вырождается в «> 0» и strong-проход
    поглотил бы любой положительный размен. `strong_only=False` — прежнее
    поведение (любой проходящий размен, вызывается уже после паков).

    `advice.jokers` отсортирован по приросту убыванию, так что первый
    подходящий оффер и есть лучший доступный под размен. Покупку решит
    следующий вызов — слот к тому моменту освободится."""
    if strong_only and requirement is None:
        return None
    for offer in advice.jokers:
        victim = offer.replaces
        if victim is None or offer.expected_uplift is None:
            continue
        if state.money + victim.sell_value < offer.item.price:
            continue
        if offer.expected_uplift <= victim.contribution:
            continue
        if strong_only and not _worth_buying(offer.expected_uplift, requirement):
            continue
        dead_weight = requirement is not None and (
            victim.contribution < _DEAD_JOKER_REQ_FRACTION * requirement
        )
        multiple = offer.expected_uplift >= _REPLACE_UPLIFT_RATIO * max(victim.contribution, 0.0)
        if dead_weight or multiple:
            return Action(kind="sell", item_index=victim.index, label=victim.label)
    return None


def _heuristic_voucher_bar(state: GameState, key: str, price: int) -> float:
    """Порог экспертной оценки ваучера 3-го уровня (`heuristic_value`, шкала
    ~2..8). База — `_MIN_HEURISTIC_VOUCHER_VALUE`. Для структурного апгрейда
    самого магазина (`_STRUCTURAL_SHOP_VOUCHERS` — `Overstock`, +слот
    витрины) планка снижается, когда бот богат деньгами (после покупки
    остаётся запас `_REROLL_MONEY_RESERVE`) и у него простаивают слоты
    джокеров: больше слотов витрины — больше шансов эти слоты джокеров занять
    (улучшение A7, случай из run 6 — `Overstock` за $10, оценка 3.0,
    пропущен при $29 и трёх пустых слотах джокеров). Снижение —
    `_HEURISTIC_RELIEF_PER_EMPTY_SLOT` за пустой слот, но не ниже
    `_HEURISTIC_VOUCHER_FLOOR`. Прочие эвристические ваучеры (частота
    изданий, ставка мерчантов) планку не снижают — даже когда их
    `heuristic_value` совпадает с `Overstock`."""
    if key not in _STRUCTURAL_SHOP_VOUCHERS or state.joker_slots is None:
        return _MIN_HEURISTIC_VOUCHER_VALUE
    empty = max(state.joker_slots - len(state.jokers), 0)
    if empty == 0 or state.money - price < _REROLL_MONEY_RESERVE:
        return _MIN_HEURISTIC_VOUCHER_VALUE
    relief = _HEURISTIC_RELIEF_PER_EMPTY_SLOT * empty
    return max(_HEURISTIC_VOUCHER_FLOOR, _MIN_HEURISTIC_VOUCHER_VALUE - relief)


def _decide_voucher_action(
    state: GameState, advice: ShopAdvice, requirement: int | None
) -> Action | None:
    """Купить ваучер (улучшение A4). Порог зависит от уровня честности
    оценки (`solver.vouchers`, поле `value_unit`):

    - `"score"` (1-й уровень — прямой ресурс в очках, +рука/+сброс/+размер
      руки): тот же порог, что у джокера (`_worth_buying`);
    - `"dollars"` (2-й уровень — денежная формула с горизонтом: потолок
      процентов, скидки): чистый плюс в долларах, оценка не ниже цены;
    - `heuristic_value` (3-й уровень — экспертная константа, НЕ посчитанное
      число): только структурные апгрейды, `>= _heuristic_voucher_bar` (по
      умолчанию `_MIN_HEURISTIC_VOUCHER_VALUE`, но для +слота витрины планка
      снижается при богатом кармане и простое слотов джокеров — улучшение A7).
      Действовать по этому уровню — явное решение пользователя.

    Ваучер слота не занимает — проверяется только `affordable`. `None`,
    если брать нечего."""
    for offer in advice.vouchers:
        if state.money < offer.item.price:
            continue
        take = False
        if offer.value_unit == "score" and offer.expected_uplift is not None:
            take = _worth_buying(offer.expected_uplift, requirement)
        elif offer.value_unit == "dollars" and offer.expected_uplift is not None:
            take = offer.expected_uplift >= offer.item.price
        elif offer.heuristic_value is not None:
            take = offer.heuristic_value >= _heuristic_voucher_bar(
                state, offer.item.key, offer.item.price
            )
        if take:
            return Action(
                kind="buy_voucher",
                item_index=_item_index_of(state.shop_vouchers, offer.item),
                label=offer.item.label,
            )
    return None


def _decide_reroll_action(
    state: GameState, advice: ShopAdvice, requirement: int | None
) -> Action | None:
    """Перекатить витрину (улучшение A5) — последняя попытка перед уходом,
    когда ни покупка, ни ваучер, ни пак, ни продажа-замена не сработали, то
    есть в текущей витрине автопилоту брать нечего.

    Рероллим, только когда: требование блайнда известно (иначе порог не
    масштабировать — тот же случай, что у `_worth_buying`); Монте-Карло
    рерола (`RerollOutlook.expected_best_uplift`) обещает джокера не хуже
    той же доли требования, что нужна для покупки в слот (`_worth_buying`);
    и после оплаты остаётся денежный запас (`_REROLL_MONEY_RESERVE`) — и на
    саму покупку, и чтобы не спустить карман на серию роллов. Растущая цена
    рерола плюс запас сходят серию на нет за несколько ходов; отдельного
    счётчика роллов не нужно."""
    outlook = advice.reroll
    if outlook is None or requirement is None:
        return None
    if not outlook.affordable or outlook.expected_best_uplift is None:
        return None
    if state.money - outlook.cost < _REROLL_MONEY_RESERVE:
        return None
    if not _worth_buying(outlook.expected_best_uplift, requirement):
        return None
    return Action(kind="reroll")


def _decide_shop_action(state: GameState) -> Action:
    """В магазине решение — купить лучшего по приросту джокера (порог A2:
    прирост не ниже доли требования блайнда, не просто > 0), затем ваучер
    (порог по уровню честности оценки, улучшение A4), затем продажа-замена,
    захватывающая явно сильного джокера (улучшение A6: оффер сам прошёл бы
    порог покупки в слот — ценнее дешёвого пака, потому решается до него),
    затем (если джокеров брать нечего) Buffoon/Celestial-пак с положительной
    оценкой, затем обычная продажа-замена слабейшего под лучший оффер, затем —
    если в витрине так и нечего взять — перекатить её (улучшение A5,
    `_decide_reroll_action`: Монте-Карло рерола обещает годного джокера и
    остаётся денежный запас), иначе уйти (`next_round`). См. модульный
    докстринг про политику и её границы."""
    advice = evaluate_shop(state)
    if advice is not None:
        requirement = _next_blind_requirement(state)
        for offer in advice.jokers:
            if (
                offer.known
                and offer.affordable
                and offer.has_slot
                and offer.expected_uplift is not None
                and _worth_buying(offer.expected_uplift, requirement)
            ):
                return Action(
                    kind="buy",
                    item_index=_item_index_of(state.shop, offer.item),
                    label=offer.item.label,
                )
        voucher_action = _decide_voucher_action(state, advice, requirement)
        if voucher_action is not None:
            return voucher_action
        # Улучшение A6: размен, захватывающий явно сильного джокера (оффер сам
        # прошёл бы порог покупки в слот), решается до паков — пак это хедж и
        # низший приоритет, а в run 6 дешёвый Celestial-пак раз за разом
        # опережал размен под оффер +3576, тот висел незанятым 2–3 опроса.
        strong_replace = _decide_replace_action(state, advice, requirement, strong_only=True)
        if strong_replace is not None:
            return strong_replace
        for pack in advice.packs:
            if (
                pack.affordable
                and pack.has_slot
                and pack.expected_uplift is not None
                and pack.expected_uplift > 0
            ):
                return Action(
                    kind="buy_pack",
                    item_index=_item_index_of(state.shop_packs, pack.item),
                    label=pack.item.label,
                )
        replace_action = _decide_replace_action(state, advice, requirement)
        if replace_action is not None:
            return replace_action
        reroll_action = _decide_reroll_action(state, advice, requirement)
        if reroll_action is not None:
            return reroll_action
    return Action(kind="next_round")


def _decide_pack_action(state: GameState) -> Action:
    """Вскрытие *уже оплаченного* открытого пака. Тип определяется по
    содержимому (`solver.pack.evaluate_pack`), не по имени фазы.

    Планета (`offer.kind == "planet"`): взять карту с наибольшим приростом —
    подъём уровня руки не может ухудшить счёт, вопрос только «какую».

    Джокер из Buffoon-пака (`"joker"`): взять с наибольшим приростом, если
    есть свободный слот. Здесь **нет** порога «строго положительный прирост»,
    в отличие от покупки джокера в витрине: пак уже оплачен, слот — его
    единственная цена, а оценка `joker_uplift` по 12 случайным рукам у
    условных джокеров (Gluttonous — по трефам, Even Steven — по чётным, Sly
    — по паре) сплошь и рядом выходит ровно `0.0` просто потому, что условие
    в этой маленькой выборке не сработало — это не «бесполезен». Занятый
    слот в ранней игре бьёт пустой, а поздней (слоты кончились) `has_slot`
    сам отсечёт. Только `None` (джокер не реализован) пропускаем.

    `skip_pack` — если брать нечего: пак пуст, только нереализованные
    джокеры, нет свободного слота, либо это Arcana/Spectral/Standard
    (`evaluate_pack` тогда возвращает пусто). Нужен, чтобы ран не застревал."""
    has_slot = state.joker_slots is None or len(state.jokers) < state.joker_slots
    for offer in evaluate_pack(state):
        if offer.expected_uplift is None:
            continue
        if offer.kind == "joker" and not has_slot:
            continue
        return Action(
            kind="pack",
            item_index=_item_index_of(state.pack, offer.item),
            label=offer.item.label,
        )
    return Action(kind="skip_pack")


def _decide_consumable_action(state: GameState) -> Action | None:
    """Использовать Planet-карту из инвентаря, если такая есть — см.
    модульный докстринг про то, почему тут не нужно ждать положительного
    числа. `None`, если Planet-карт в инвентаре нет — тогда решение
    переходит к play/discard как обычно."""
    offers = evaluate_planet_consumables(state)
    if not offers:
        return None
    item = offers[0].item
    return Action(kind="use", item_index=_item_index_of(state.consumables, item), label=item.label)


def _decide_rearrange_action(state: GameState, plays: Advice) -> Action | None:
    """Переставить джокеров, если для текущей руки есть заметно лучший
    порядок (улучшение D1). `rank_joker_orders` перебирает перестановки
    (кап `MAX_JOKERS_FOR_ORDER_SEARCH`, выше — `None`, не гадаем; внутри —
    дешёвый вентиль + суррогатный перебор, улучшение F1). Меняем только при
    относительном приросте счёта >= `_MIN_REORDER_GAIN_FRAC` — иначе ход
    тратится впустую на шум перебора. Перестановка — отдельное действие:
    розыгрыш решит следующий вызов на уже верном порядке (тот же паттерн
    «одно действие за вызов», что в магазине). Проверяется на каждой руке
    заново — лучший порядок для разных рук может отличаться, порог не даёт
    этому вылиться в дёрганье туда-сюда.

    `plays` — уже посчитанный `advise(state)` (исходный порядок): отдаётся
    в `rank_joker_orders` как `base_advice`, чтобы не гонять `advise` дважды,
    и служит базой сравнения `current_score`."""
    if len(state.jokers) < 2:
        return None
    result = rank_joker_orders(state, limit=1, base_advice=plays)
    if result is None:
        return None
    best_order, best_advice = result
    if best_order == state.jokers:
        return None
    current_score = plays.best.score
    gain = best_advice.best.score - current_score
    if gain <= 0 or gain < _MIN_REORDER_GAIN_FRAC * current_score:
        return None
    return Action(kind="rearrange", indices=_reorder_indices(state.jokers, best_order))


def _on_pace_without_discard(state: GameState, plays: Advice) -> bool:
    """Улучшение B1: добьёт ли автопилот блайнд одними розыгрышами, без
    спекулятивных сбросов. `лучшая рука × осталось рук` (с запасом
    `_DISCARD_PACE_MARGIN`) уже перекрывает остаток требования.

    Требует минимум двух рук в запасе: с единственной оставшейся рукой сброс —
    это выжимание последнего хода, а не спекуляция от избытка, и решать его
    должен общий список `rank_actions`. `plays` — уже посчитанный
    `advise(state)`, заново не считаем."""
    if plays.required is None or state.hands_left < 2:
        return False
    remaining = plays.required - plays.already_scored
    if remaining <= 0:
        return True
    return plays.best.score * state.hands_left >= remaining * _DISCARD_PACE_MARGIN


def _discard_edge_is_noise(discard: ActionOption, best_play: Candidate) -> bool:
    """Улучшение B1: перевес сброса над лучшей рукой меньше собственной
    погрешности его оценки (`_DISCARD_EDGE_MARGIN`) — разменивать розыгрыш на
    такой сброс значит действовать по шуму (в живом прогоне автопилот так
    тратил последний сброс, меняя флеш ~7 371 на цель ~7 427). Если играть
    нечего (`best_play.score <= 0`), любой положительный сброс — не шум."""
    if best_play.score <= 0:
        return False
    return discard.score < best_play.score * _DISCARD_EDGE_MARGIN


def decide_action(state: GameState, *, include_discards: bool = True) -> Action | None:
    """Решить, что сделать прямо сейчас — `None`, если эта фаза ещё не закрыта.

    `include_discards=False` — то же самое, что `--no-discard` у `watch`/
    `advise` (переиспользует тот же параметр `rank_actions`, не отдельный
    флаг): автопилот тогда никогда не решает сбросить, только играть."""
    if state.phase == BLIND_SELECT:
        return _decide_blind_action(state)

    if state.phase == ROUND_EVAL:
        return Action(kind="cash_out")

    if state.phase == SHOP:
        return _decide_shop_action(state)

    if state.phase in PACK_OPEN_PHASES:
        # Тип пака решается по содержимому: Celestial/Buffoon оцениваются,
        # Arcana/Spectral/Standard — `skip_pack` внутри (см. `_decide_pack_action`).
        return _decide_pack_action(state)

    if state.phase == SELECTING_HAND:
        if not state.hand:
            return None
        consumable_action = _decide_consumable_action(state)
        if consumable_action is not None:
            return consumable_action

        # `advise(state)` для исходного порядка джокеров считается один раз и
        # переиспользуется: перестановкой (`base_advice`), гарантированным
        # ходом и гардами B1 ниже (улучшение F1 — раньше это было 2–3
        # отдельных `advise()` на один вызов).
        plays = advise(state)

        rearrange_action = _decide_rearrange_action(state, plays)
        if rearrange_action is not None:
            return rearrange_action

        # Гарантированная победа бьёт любую ставку на сброс. `rank_actions`
        # сравнивает розыгрыши и сбросы по матожиданию, а у сброса оно
        # оптимистично по построению (`ActionOption.exact = False`) — поэтому
        # «сбросить к флешу» нередко показывает число больше, чем «сыграть
        # эту двойную пару», даже когда пара уже закрывает блайнд. Если есть
        # ход, чей нижний предел (`Candidate.beats`) уже перекрывает
        # оставшееся требование, играем его — не гадаем.
        sure = plays.cheapest_sufficient
        if sure is not None:
            return Action(
                kind="play",
                cards=sure.cards,
                indices=_indices_of(state.hand, sure.cards),
            )

        # Улучшение B1. `cheapest_sufficient` ловит только «закрыть блайнд
        # одной этой рукой»; когда джокер с разбросом (Misprint) утягивает
        # нижний предел под требование, он не находит ничего, и автопилот
        # уходит в сброс на каждом блайнде. Но если запаса рук хватает добить
        # блайнд одними розыгрышами (`_on_pace_without_discard`), спекулятивный
        # сброс не нужен — играем лучшую руку. Заодно экономит дорогой
        # `advise_discard` внутри `rank_actions` (см. F1).
        if include_discards and _on_pace_without_discard(state, plays):
            best_play = plays.best
            return Action(
                kind="play",
                cards=best_play.cards,
                indices=_indices_of(state.hand, best_play.cards),
            )

        options = rank_actions(state, top=1, include_discards=include_discards)
        if not options:
            return None
        best = options[0]

        # Улучшение B1. Даже без гарантии и без запаса рук — не менять
        # розыгрыш на сброс, чей перевес по матожиданию меньше
        # задокументированной погрешности самой оценки сброса
        # (`_discard_edge_is_noise`): такой перевес — шум, а сброс ещё и
        # тратит ресурс и добавляет разброс к результату.
        if best.kind == "discard" and _discard_edge_is_noise(best, plays.best):
            best_play = plays.best
            return Action(
                kind="play",
                cards=best_play.cards,
                indices=_indices_of(state.hand, best_play.cards),
            )

        return Action(kind=best.kind, cards=best.cards, indices=_indices_of(state.hand, best.cards))

    return None


def dispatch_action(bridge: ModBridge, action: Action) -> GameState:
    """Исполнить `action` через мост и вернуть новое состояние.

    Один перевод `Action.kind` -> RPC-метод, общий для живого цикла
    (`ui/tui.py.autoplay`) и ран-раннера (`balatro_bot/runner.py`) — раньше
    жил только внутри цикла `tui`. Ошибки моста (`ModBridgeError`) не
    глотает: и цикл, и раннер обрабатывают отказ по-своему (цикл печатает и
    продолжает опрос, раннер фиксирует затык в логе решений). Несогласованный
    `Action` (например, `buy` без `item_index`) — это ошибка в
    `decide_action`, а не отказ игры: падаем с `ValueError`, не `assert`
    (который вырезается под `python -O`)."""

    def _index() -> int:
        if action.item_index is None:
            raise ValueError(f"{action.kind}: не задан item_index")
        return action.item_index

    match action.kind:
        case "play":
            return bridge.play(action.indices)
        case "discard":
            return bridge.discard(action.indices)
        case "select":
            return bridge.select()
        case "skip":
            return bridge.skip()
        case "buy":
            return bridge.buy(card=_index())
        case "buy_pack":
            return bridge.buy(pack=_index())
        case "buy_voucher":
            return bridge.buy(voucher=_index())
        case "sell":
            return bridge.sell(joker=_index())
        case "rearrange":
            return bridge.rearrange(jokers=action.indices)
        case "reroll":
            return bridge.reroll()
        case "next_round":
            return bridge.next_round()
        case "cash_out":
            return bridge.cash_out()
        case "pack":
            return bridge.open_pack(card=_index())
        case "skip_pack":
            return bridge.open_pack(skip=True)
        case "use":
            return bridge.use(_index())


def describe_action(action: Action) -> str:
    """Короткая человекочитаемая строка о том, что автопилот сделал — для
    лога живого цикла (`ui/tui.py`) и лога решений ран-раннера
    (`balatro_bot/runner.py`). Карты — компактно, ранг+масть, без пометок
    улучшений: полный разбор варианта и так печатает `render_top_actions`."""
    cards = " ".join(f"{c.rank.value}{c.suit.value}" for c in action.cards)
    named = f": {action.label}" if action.label else ""
    match action.kind:
        case "play":
            return f"сыграл {cards}"
        case "discard":
            return f"сбросил {cards}"
        case "select":
            return "выбрал блайнд — играет"
        case "skip":
            return "скипнул блайнд ради тега"
        case "cash_out":
            return "забрал награду за раунд"
        case "buy":
            return f"купил в магазине{named}"
        case "buy_pack":
            return f"купил пак{named}"
        case "buy_voucher":
            return f"купил ваучер{named}"
        case "sell":
            return f"продал джокера{named}"
        case "rearrange":
            return "переставил джокеров"
        case "reroll":
            return "перекатил витрину"
        case "next_round":
            return "ушёл из магазина"
        case "pack":
            return f"взял из пака{named}"
        case "skip_pack":
            return "скипнул пак"
        case "use":
            return f"использовал консумабль{named}"
