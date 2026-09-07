"""Нормализованное состояние игры.

Это граница между внешним миром и ядром: солвер работает только с этими
типами и не знает, пришло состояние из мода, из ручного ввода или из теста.

Здесь же живёт механизм честности. Любой объект, которого нет в справочнике,
попадает в `unknown_keys`, и состояние перестаёт считаться точным. Молча
проигнорировать незнакомого джокера нельзя: расчёт останется правдоподобным,
но неверным, а это худший исход для советника.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from balatro_bot.core.cards import Card, Edition, Rank, Suit
from balatro_bot.core.catalogue import is_known_joker
from balatro_bot.core.hands import HandType, HandValues, base_values

__all__ = ["BlindInfo", "GameState", "JokerCard", "PokerHandInfo", "ShopItem"]


@dataclass(frozen=True, slots=True)
class PokerHandInfo:
    """Состояние одного типа руки в текущем ране.

    `chips` и `mult` игра присылает уже с учётом уровня, поэтому таблицы из
    `hands.py` при работе через мод не нужны вовсе.
    """

    level: int
    chips: int
    mult: int
    played: int = 0
    played_this_round: int = 0
    """Сколько раз этот тип руки уже сыгран в текущем раунде — нужно
    `Card Sharp` (`j_card_sharp`)."""


@dataclass(frozen=True, slots=True)
class JokerCard:
    """Джокер в слоте. Порядок слотов важен: он влияет на счёт."""

    key: str
    label: str = ""
    edition: Edition = Edition.BASE
    eternal: bool = False
    debuffed: bool = False
    """Джокер отключён игрой (`state.debuff` мода) — эффекта не даёт вовсе, но
    слот занимает. В базовой игре это бывает только когда у «портящегося»
    (`perishable`) джокера истёк счётчик раундов (`card.lua`'s
    `Card:calculate_perishable` → `set_debuff`; ставка `ORANGE`+). Движок
    подсчёта такого джокера пропускает — не реагирует на события, не
    применяет издание, не даёт правило-модификатор (`core/scoring.py`,
    `core/jokers/__init__.py`), но `Joker Stencil`/`Baseball Card` и т.п.
    по-прежнему видят его в списке (карта физически в слоте, как и в игре)."""
    sell_value: int | None = None
    """Цена продажи. Нужна `Swashbuckler` (`j_swashbuckler`); `None`, если
    источник состояния её не прислал (например, ручной ввод)."""
    current_value: float | None = None
    """Готовое текущее значение джокера-накопителя (`Green Joker`, `Square`,
    `Vampire`, ...), вытащенное мостом из текста эффекта — сама игра уже
    считает его и подставляет в описание («сейчас +15 множ.»), парсить
    историю событий (прошлые сбросы, прошлые сброшенные карты и т.д.) не
    нужно. `None`, если источник состояния его не прислал (ручной ввод) или
    в тексте эффекта не нашлось числа — джокер тогда помечает расчёт
    неточным вместо того, чтобы считать с нуля."""
    leading_value: float | None = None
    """То же самое, что `current_value`, но число не последнее в тексте
    эффекта, а первое (`Popcorn`, `Ramen`: игра подставляет текущее
    затухающее значение первым `var`, а статичный шаг угасания — вторым,
    см. `mod_bridge._extract_leading_value`)."""
    target_suit: Suit | None = None
    """Текущая масть-цель, которую игра подставляет прямо в текст эффекта
    (`Ancient Joker`, `The Idol`) — не история, а то, что видно сейчас.
    Опознаётся по слову в тексте, поэтому работает только на языках,
    которые распознаёт `mod_bridge._SUIT_WORDS` (сейчас — русский и
    английский); на прочих языках останется `None`, и джокер честно
    пометит расчёт неточным."""
    target_rank: Rank | None = None
    """Текущий ранг-цель (`The Idol`). То же ограничение по языку, что и
    у `target_suit`, см. `mod_bridge._RANK_WORDS`."""
    loyalty_active: bool | None = None
    """Сработает ли `Loyalty Card` в этот розыгрыш — распознаётся по
    словам «Активно!»/«Active!» или «осталось»/«remaining» в тексте
    эффекта (см. `mod_bridge._extract_loyalty_active`). `None`, если ни
    то ни другое слово не нашлось (не тот язык или ручной ввод)."""

    @property
    def is_known(self) -> bool:
        """Есть ли джокер в справочнике."""
        return is_known_joker(self.key)


@dataclass(frozen=True, slots=True)
class BlindInfo:
    """Один блайнд — не обязательно текущий, см. `GameState.blind` vs `GameState.blinds`."""

    kind: str
    name: str
    effect: str
    required_score: int

    status: str = ""
    """Статус этого блайнда в моде: `SELECT` (можно выбрать сейчас — играть
    или скипнуть), `CURRENT` (уже играется), `UPCOMING`, `DEFEATED`,
    `SKIPPED` (пропущен ради тега — играть его уже не придётся, но и
    побеждён он не был). Пустая
    строка — источник не прислал (например, ручной ввод)."""

    tag_name: str = ""
    """Имя тега, который достанется при скипе (только Small/Big). Пустая
    строка — блайнд уже сыгран/скипнут, тега не будет, либо это боссовый
    блайнд (скипнуть нельзя, тега не бывает)."""

    tag_effect: str = ""
    """Текст эффекта тега, как его показывает игра — так же, как эффекты
    джокеров, честнее не пересказывать своими словами, а показать как есть."""


@dataclass(frozen=True, slots=True)
class ShopItem:
    """Один предмет на продажу — джокер, ваучер, пак или таро/планета/спектр.

    `effect` берётся из того же поля мода, что и `JokerCard.current_value` —
    `value.effect`, уже посчитанный игрой текст. Для ваучеров и паков это
    единственный источник понимания, что предмет делает: отдельного
    справочника для них в проекте нет (в отличие от джокеров и тегов) —
    сама игра уже вернула готовый текст, пересказывать нечего."""

    key: str
    label: str
    kind: str
    """`JOKER`/`VOUCHER`/`BOOSTER`/`TAROT`/`PLANET`/`SPECTRAL` — значение
    поля `set` мода (`CardSet` в схеме)."""

    price: int
    effect: str = ""
    edition: Edition = Edition.BASE
    """Значимо только для `JOKER`: издание, за которое магазин просит цену
    в `price`, влияет на реальную ценность покупки (`solver/shop.py`)."""

    eternal: bool = False
    """Значимо только для `JOKER` (стикер ставки, `BLACK`+): вечного джокера
    нельзя продать — купив неудачного, слот уже не освободить продажей
    (`solver/shop.py`, «бюджет слотов при неудачной покупке»)."""
    perishable_rounds: int | None = None
    """Значимо только для `JOKER` (стикер ставки, `ORANGE`+): сколько раундов
    джокер ещё проработает, прежде чем игра его отключит — не уничтожит, слот
    останется занят неработающим джокером (`card.lua`'s
    `Card:calculate_perishable` → `set_debuff` на нуле счётчика). Мод
    присылает уже остаточный счётчик (`modifier.perishable`, «> 0 only»), а
    не стартовые пять. `None` — джокер не «портящийся»."""
    rental: bool = False
    """Значимо только для `JOKER` (стикер ставки, `GOLD`): арендный джокер
    стоит `economy.RENTAL_RATE` в конце каждого раунда владения (`card.lua`'s
    `Card:calculate_rental`). Цену покупки таких джокеров игра принудительно
    опускает до $1 (`Card:set_cost`), поэтому дешевизна `price` обманчива —
    реальная цена в постоянном оттоке (`solver/shop.py`)."""


@dataclass(frozen=True, slots=True)
class GameState:
    """Всё, что нужно солверу для выбора хода."""

    phase: str = "UNKNOWN"
    ante: int = 1
    round_number: int = 1
    money: int = 0

    won: bool = False
    """Победа в ране (`ante_num` дошёл до 8 и финальный босс побеждён) —
    поле `won` мода. Нужно ран-раннеру (`balatro_bot/runner.py`, Фаза 9.7),
    чтобы отличить победу от `phase == "GAME_OVER"` (поражение). В остальном
    коде не используется — обычный розыгрыш до победы не доходит."""

    hand: tuple[Card, ...] = ()
    jokers: tuple[JokerCard, ...] = ()
    hand_info: Mapping[HandType, PokerHandInfo] = field(default_factory=dict)
    blind: BlindInfo | None = None

    blinds: Mapping[str, BlindInfo] = field(default_factory=dict)
    """Все три блайнда анте — ключи `"small"`/`"big"`/`"boss"`, не только
    текущий. Нужно для решения «скипнуть или нет» (`solver/skip.py`): на
    экране выбора блайнда `blind` ещё `None` (`_parse_blind` ищет статус
    `CURRENT`, а на этом экране его ни у кого нет), но сами по себе
    требования и теги всех трёх блайндов уже известны."""

    shop: tuple[ShopItem, ...] = ()
    """Джокеры и таро/планета/спектр-карты на продажу — область `shop` мода,
    непустая только в фазе `SHOP` (`solver/shop.py`)."""

    shop_slots: int | None = None
    """Сколько карт вмещает витрина магазина (`G.GAME.shop.joker_max`, поле
    `limit` области `shop` мода — так же, как `joker_slots` берётся из
    `limit` области `jokers`). Обычно 2, больше с `Overstock`/`Overstock
    Plus`. `None` — источник не прислал (ручной ввод). Нужно `solver/shop.py`
    для оценки рерола (A5): реролл перезаполняет ровно столько слотов, а
    `len(shop)` после покупки уже меньше вместимости."""

    shop_vouchers: tuple[ShopItem, ...] = ()
    shop_packs: tuple[ShopItem, ...] = ()

    pack: tuple[ShopItem, ...] = ()
    """Карты открытого сейчас бустер-пака — область `pack` мода, непустая
    только в фазах `*_PACK` (`TAROT_PACK`/`PLANET_PACK`/`SPECTRAL_PACK`/
    `STANDARD_PACK`/`BUFFOON_PACK`). Те же `ShopItem` (одна и та же форма
    карты у мода что в магазине, что в паке), `price` тут просто 0 —
    выбор карты из пака ничего не стоит сам по себе, пак уже оплачен
    (`solver/pack.py`)."""

    consumables: tuple[ShopItem, ...] = ()
    """Taro/Planet/Spectral-карты в инвентаре игрока прямо сейчас — область
    `consumables` мода, живёт весь ран (не только в одной фазе, в отличие
    от `shop`/`pack`). Те же `ShopItem`, `price` тут тоже не имеет смысла —
    карта уже куплена/получена. Нужна `solver/consumables.py`: решить,
    применять ли лежащую в инвентаре Planet-карту перед розыгрышем текущей
    руки (Фаза 9.4)."""

    consumable_slots: int | None = None
    """Сколько расходников помещается в инвентарь (`limit` области
    `consumables` мода — так же, как `joker_slots` и `shop_slots` берутся из
    `limit` своих областей). Обычно 2, больше с `Crystal Ball` и колодой
    `Nebula`. `None` — источник не прислал (ручной ввод). Нужна
    `solver/shop.py` (улучшение C2): купить расходник с витрины при полном
    инвентаре игра не даст, и без этого поля бот получал бы отказ мода
    вместо решения."""

    reroll_cost: int | None = None
    """Текущая цена рерола магазина — область `round` мода (`reroll_cost`,
    та же, что даёт `hands_left`/`discards_left`), растёт с каждым роллом.
    `None` — источник состояния её не прислал (ручной ввод, либо не фаза
    `SHOP`). Нужна `solver/shop.py`: с Фазы 9.8 (улучшение A5) бот
    моделирует Монте-Карло сам ролл (`joker_rate`, редкости из `game.lua`)
    и сопоставляет ожидаемый прирост с этой ценой — см. `RerollOutlook`."""

    used_vouchers: frozenset[str] = frozenset()
    """Ключи уже выкупленных в этом ране ваучеров (`v_seed_money`,
    `v_clearance_sale`, ...) — область мода `used_vouchers` (ключ -> текст,
    берём только ключи). Единственный способ узнать текущий потолок
    процентов/скидку в магазине точно, а не предполагать значения по
    умолчанию (`core/economy.py`) — нужен `solver/shop.py` (`interest_lost`)
    и `solver/vouchers.py` (второй уровень честности, денежные ваучеры с
    горизонтом). Пуст по умолчанию — и когда ваучеров действительно нет, и
    при ручном вводе (история покупок рана не вводится вручную), различить
    эти два случая по этому полю нельзя, тот же принцип, что у `deck`/
    `full_deck`."""

    deck_type: str | None = None
    """Выбранная колода рана (`RED`, `ABANDONED`, …) — не путать с `deck`
    (оставшиеся для добора карты). Нужна только для того, чтобы узнать
    стартовый размер колоды (`j_erosion`): у большинства колод он 52 карты,
    но, например, `ABANDONED` начинает без картинок — 40."""

    deck: tuple[Card, ...] | None = None
    """Оставшаяся колода — карты, которые ещё можно добрать при сбросе.

    Известна точно только через мост к моду (Фаза 5): он присылает область
    `cards`, и `hand.count + cards.count` совпадает с размером всей колоды —
    то есть это буквально то, что осталось добирать прямо сейчас. При ручном
    вводе колода неизвестна: `solver/discard.py` сам подставляет вместо неё
    приближение (`core.cards.standard_deck`) и честно помечает результат
    неточным.
    """

    full_deck: tuple[Card, ...] | None = None
    """Весь набор карт в колоде: не то, что осталось добирать (`deck`), а все
    карты, которыми игрок владеет в этом ране. Нужен джокерам вида «X за
    каждую стальную/каменную карту в колоде» (`j_steel_joker`, `j_stone`,
    `j_drivers_license`).

    В спецификации мода (`openrpc.json`) отдельного поля для полного состава
    нет — область `cards` документирована именно как «Cards remaining in
    deck». Собрать полный список из одного снимка состояния получается
    только в узком случае: `hand ∪ cards` совпадает со всей колодой, только
    пока за раунд ничего не сыграно и не сброшено (`mod_bridge.py` строит
    это поле именно при этом условии, иначе оставляет `None` — часть карт,
    сыгранных или сброшенных этим раундом, до конца раунда лежит в стопке,
    которую мод не показывает ни в одной области состояния)."""

    hands_left: int = 0
    discards_left: int = 0
    hands_played: int = 0
    """Сколько рук уже сыграно в этом раунде — нужно `Ice Cream` (`j_ice_cream`)."""
    chips_scored: int = 0

    joker_slots: int | None = None
    """Вместимость слотов джокеров. Нужна `Joker Stencil` (`j_stencil`);
    `None`, если источник состояния её не прислал."""

    unknown_keys: tuple[str, ...] = ()
    """Всё, что не удалось опознать, в виде `вид:ключ`."""

    @property
    def is_exact(self) -> bool:
        """Можно ли доверять расчёту по этому состоянию до последней единицы."""
        return not self.unknown_keys

    @property
    def has_authoritative_hand_values(self) -> bool:
        """Прислала ли игра значения рук сама.

        Если нет — используются провизорные таблицы из `hands.py`, и расчёт
        точным считать нельзя.
        """
        return bool(self.hand_info)

    def hand_values(self, hand_type: HandType) -> HandValues:
        """Очки и множитель типа руки на текущем уровне.

        Приоритет у данных игры: она уже учла уровень, прокачанный
        Planet-картами. Запасной путь — провизорная таблица, нужная только
        при ручном вводе.
        """
        info = self.hand_info.get(hand_type)
        if info is not None:
            return HandValues(info.chips, info.mult)
        return base_values(hand_type, 1)

    @property
    def unknown_jokers(self) -> tuple[str, ...]:
        """Ключи джокеров, эффект которых ещё не реализован."""
        return tuple(joker.key for joker in self.jokers if not joker.is_known)
