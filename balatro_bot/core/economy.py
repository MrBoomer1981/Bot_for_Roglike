"""Денежные формулы игры — проценты в конце раунда, скидки в магазине.

Общий источник для `solver/shop.py` и `solver/vouchers.py`, чтобы формулы
не расходились по двум независимо поддерживаемым копиям (тот же риск, что
любое дублирование нетривиальной логики, — в отличие от простых констант
сэмплирования вроде `SAMPLE_HANDS`, которые каждый солверный модуль честно
держит у себя). Все числа и формулы — из собственного исходника игры
(`Balatro.love`), не по памяти:

- `game.lua`'s `GAME_MOD`: `interest_cap = 25`, `interest_amount = 1`,
  `discount_percent = 0` — значения по умолчанию без выкупленных ваучеров.
- `functions/state_events.lua`: `interest_amount * min(floor(dollars/5),
  interest_cap/5)` — начисление процентов в конце раунда.
- `card.lua`'s `Card:add_to_deck`: `Seed Money`/`Money Tree` **задают**
  `G.GAME.interest_cap` абсолютным значением (`center_table.extra` — 50 и
  100 соответственно), не прибавляют к текущему; `Clearance Sale`/
  `Liquidation` так же задают `discount_percent` (25 и 50).
- `card.lua`'s `Card:calculate_cost`: `cost = max(1, floor((base_cost +
  extra_cost + 0.5) * (100 - discount_percent) / 100))` — как скидка
  применяется к цене товара.
- `game.lua`'s `GAME_MOD`: `rental_rate = 3`, `perishable_rounds = 5` —
  значения по умолчанию; ни то, ни другое нигде в исходнике игры не
  переприсваивается (ставка `GOLD`/`ORANGE` включает *появление* стикера,
  но не меняет ставку аренды или срок). `card.lua`'s `Card:calculate_rental`
  снимает `rental_rate` долларов в конце каждого раунда, пока джокером
  владеешь; `Card:calculate_perishable` каждый раунд уменьшает остаточный
  счётчик и на нуле отключает джокера (`set_debuff`, слот не освобождается).

`used_vouchers` (ключи уже выкупленных ваучеров, `GameState.used_vouchers`
— область мода `used_vouchers`, доступна только через мост, см.
`adapters/mod_bridge.py`) — единственный способ узнать текущий процент/
потолок точно, а не предполагать базовые значения по умолчанию всегда;
раньше `solver/shop.py`'s `interest_lost` был честно помечен как
допущение по этой причине (`GameState` не хранил уже выкупленные
ваучеры) — теперь, когда мост эту область парсит, допущение снято для
живой игры и остаётся только при ручном вводе (`used_vouchers` тогда
пуст по определению, т.к. вводится не всё состояние рана)."""

from __future__ import annotations

from typing import Final

__all__ = [
    "BASE_REROLL_COST",
    "INTEREST_AMOUNT",
    "INTEREST_CAP_DEFAULT",
    "INTEREST_STEP",
    "NO_INTEREST_DECK",
    "RENTAL_RATE",
    "SHOP_JOKER_RATE",
    "SHOP_PLANET_RATE",
    "SHOP_TAROT_RATE",
    "discount_percent",
    "interest",
    "interest_cap",
    "reroll_base_cost",
    "rerolls_done",
]

INTEREST_AMOUNT: Final[int] = 1
INTEREST_CAP_DEFAULT: Final[int] = 25
INTEREST_STEP: Final[int] = 5

#: Веса типов карт в одном слоте витрины магазина — `game.lua`'s `GAME_MOD`
#: (`joker_rate = 20`, `tarot_rate = 4`, `planet_rate = 4`,
#: `playing_card_rate = 0`, `spectral_rate = 0`); слот заполняется джокером
#: с вероятностью `joker_rate / сумма всех`. Реролл (`solver/shop.py`,
#: улучшение A5) перезаполняет слоты по этому распределению. Значения по
#: умолчанию: ваучеры-мерчанты (`v_tarot_merchant`/`v_planet_merchant` и
#: т.п.) и Ghost Deck (`spectral_rate = 2`) их меняют, но `GameState`
#: текущие ставки не отдаёт — та же оговорка про умолчание, что была у
#: `interest_cap` до появления `used_vouchers`.
SHOP_JOKER_RATE: Final[int] = 20
SHOP_TAROT_RATE: Final[int] = 4
SHOP_PLANET_RATE: Final[int] = 4

#: Сколько долларов снимается в конце каждого раунда за каждого арендного
#: джокера (`game.lua`'s `GAME_MOD.rental_rate = 3`, `card.lua`'s
#: `Card:calculate_rental`). Постоянная величина: в исходнике игры нигде не
#: переприсваивается. Остаточный срок «портящегося» джокера (`perishable`)
#: константой не нужен — мод присылает уже актуальный счётчик, а не
#: стартовые `perishable_rounds = 5`.
RENTAL_RATE: Final[int] = 3

#: Стартовая цена рерола витрины — `game.lua`'s `starting_params.reroll_cost
#: = 5`, она же `G.GAME.round_resets.reroll_cost` на старте рана
#: (`game.lua`'s `Game:start_run`). Цена ролла внутри одного захода в магазин
#: считается как `база + число уже сделанных роллов`
#: (`functions/common_events.lua`'s `calculate_reroll_cost`:
#: `reroll_cost = round_resets.reroll_cost + current_round.reroll_cost_increase`,
#: где `reroll_cost_increase` растёт ровно на 1 за ролл и обнуляется в начале
#: каждого раунда — `functions/state_events.lua`). Нужна `autopilot`'у, чтобы
#: восстановить число роллов этого захода из наблюдаемой цены (улучшение A8).
BASE_REROLL_COST: Final[int] = 5

#: На сколько каждый из двух «реролльных» ваучеров удешевляет ролл —
#: `game.lua`: у `v_reroll_surplus` и `v_reroll_glut` обоих `config.extra = 2`.
_REROLL_VOUCHER_DISCOUNT: Final[int] = 2

#: `Green Deck` (`b_green` в `game.lua`) отключает проценты полностью
#: (`config.no_interest = true`) — единственный отслеживаемый в `GameState`
#: (`deck_type`) случай, где реальный ответ — гарантированный ноль.
NO_INTEREST_DECK: Final[str] = "GREEN"

_SEED_MONEY_CAP: Final[int] = 50
_MONEY_TREE_CAP: Final[int] = 100

_CLEARANCE_SALE_DISCOUNT: Final[int] = 25
_LIQUIDATION_DISCOUNT: Final[int] = 50


def interest_cap(used_vouchers: frozenset[str]) -> int:
    """Текущий потолок процентов с учётом уже выкупленных ваучеров.

    `Money Tree` в реальной игре требует уже выкупленного `Seed Money`
    (`game.lua`'s `v_money_tree.requires`), но проверка всё равно идёт по
    убыванию, а не суммированием — `card.lua` **задаёт** потолок абсолютным
    значением, не прибавляет к текущему."""
    if "v_money_tree" in used_vouchers:
        return _MONEY_TREE_CAP
    if "v_seed_money" in used_vouchers:
        return _SEED_MONEY_CAP
    return INTEREST_CAP_DEFAULT


def interest(money: int, deck_type: str | None, cap: int = INTEREST_CAP_DEFAULT) -> int:
    """Проценты, которые накапало бы в конце раунда при данной сумме денег
    и данном потолке (см. `interest_cap` — потолок зависит от выкупленных
    ваучеров, поэтому передаётся явно, а не читается отсюда самим)."""
    if deck_type == NO_INTEREST_DECK or money < INTEREST_STEP:
        return 0
    return INTEREST_AMOUNT * min(money // INTEREST_STEP, cap // INTEREST_STEP)


def reroll_base_cost(used_vouchers: frozenset[str]) -> int:
    """Базовая цена рерола (до надбавки за уже сделанные в этом заходе
    роллы) с учётом выкупленных ваучеров.

    В отличие от `interest_cap`/`discount_percent`, которые **задают**
    значение, эти два ваучера **вычитают** и складываются: `card.lua`
    (`Card:add_to_deck`, ветка `Reroll Surplus`/`Reroll Glut`) делает
    `round_resets.reroll_cost = round_resets.reroll_cost - extra` для
    каждого, поэтому с обоими база равна $1, а не $3."""
    base = BASE_REROLL_COST
    for key in ("v_reroll_surplus", "v_reroll_glut"):
        if key in used_vouchers:
            base -= _REROLL_VOUCHER_DISCOUNT
    return max(base, 0)


def rerolls_done(reroll_cost: int, used_vouchers: frozenset[str]) -> int:
    """Сколько роллов уже сделано в этом заходе в магазин — восстановлено из
    наблюдаемой цены: `reroll_cost - база` (см. `BASE_REROLL_COST`). Счётчик
    самой игры (`current_round.reroll_cost_increase`) в схеме мода не
    отдаётся, а цена — отдаётся, и растёт ровно на $1 за ролл, обнуляясь
    каждый раунд. Нужно `autopilot._decide_reroll_action` (улучшение A8):
    без ограничения по числу роллов политика вырождается в «рероллить, пока
    не кончатся деньги», потому что сама оценка ролла стационарна.

    Оценка честно **занижена** в двух случаях, и оба безопасны — они дают
    право на лишний ролл, а не запрещают нужный: `Reroll` -тег
    (`round_resets.temp_reroll_cost`) и `Chaos the Clown`
    (`current_round.free_rerolls`, цена принудительно 0) временно опускают
    цену, и восстановленный счётчик выходит меньше настоящего."""
    return max(reroll_cost - reroll_base_cost(used_vouchers), 0)


def discount_percent(used_vouchers: frozenset[str]) -> int:
    """Текущая скидка в магазине с учётом уже выкупленных ваучеров — та же
    логика «задаёт, не прибавляет», что у `interest_cap`."""
    if "v_liquidation" in used_vouchers:
        return _LIQUIDATION_DISCOUNT
    if "v_clearance_sale" in used_vouchers:
        return _CLEARANCE_SALE_DISCOUNT
    return 0
