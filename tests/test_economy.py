"""Тесты денежных формул (`balatro_bot/core/economy.py`).

Формулы выписаны из исходника игры, не по памяти — см. модульный докстринг
`core/economy.py`. Раньше жили как приватные тесты `solver/shop.py`;
вынесены сюда вместе с самими формулами, когда `solver/vouchers.py`
понадобилась та же логика (Фаза 9.3, второй уровень честности)."""

from __future__ import annotations

from balatro_bot.core.economy import (
    BASE_REROLL_COST,
    RENTAL_RATE,
    SHOP_JOKER_RATE,
    SHOP_PLANET_RATE,
    SHOP_TAROT_RATE,
    discount_percent,
    interest,
    interest_cap,
    reroll_base_cost,
    rerolls_done,
)


class TestInterest:
    """`interest_amount * min(floor(dollars/5), cap/5)`. По умолчанию
    `interest_amount=1`, `cap=25` → максимум $5 за раунд, шаг — $1 за
    каждые $5."""

    def test_меньше_пяти_долларов_без_процентов(self) -> None:
        assert interest(0, None) == 0
        assert interest(4, None) == 0

    def test_шаг_один_доллар_на_каждые_пять(self) -> None:
        assert interest(5, None) == 1
        assert interest(9, None) == 1
        assert interest(24, None) == 4

    def test_потолок_на_25_долларах_по_умолчанию(self) -> None:
        assert interest(25, None) == 5
        assert interest(1000, None) == 5  # выше потолка не растёт

    def test_явный_потолок_поднимает_максимум(self) -> None:
        assert interest(1000, None, cap=50) == 10
        assert interest(1000, None, cap=100) == 20

    def test_green_deck_отключает_проценты_полностью(self) -> None:
        assert interest(1000, "GREEN") == 0

    def test_отрицательные_деньги_не_ломают_формулу(self) -> None:
        # Гипотетическая покупка дороже кошелька — не должно случиться в
        # реальной игре, но формула не должна давать отрицательные проценты.
        assert interest(-3, None) == 0


class TestInterestCap:
    """`Seed Money`/`Money Tree` задают потолок абсолютным значением, не
    прибавляют — см. `card.lua`'s `Card:add_to_deck`."""

    def test_без_ваучеров_потолок_по_умолчанию(self) -> None:
        assert interest_cap(frozenset()) == 25

    def test_seed_money_поднимает_до_50(self) -> None:
        assert interest_cap(frozenset({"v_seed_money"})) == 50

    def test_money_tree_поднимает_до_100(self) -> None:
        assert interest_cap(frozenset({"v_seed_money", "v_money_tree"})) == 100

    def test_money_tree_без_seed_money_всё_равно_100(self) -> None:
        # В реальной игре Money Tree требует Seed Money заранее, но сама
        # формула не складывает — берёт большее значение напрямую.
        assert interest_cap(frozenset({"v_money_tree"})) == 100


class TestRentalRate:
    """`game.lua`'s `GAME_MOD.rental_rate = 3` — постоянная величина,
    нигде в исходнике не переприсваивается (см. модульный докстринг
    `core/economy.py`). Отдельный тест-«якорь», чтобы правка константы
    не прошла молча."""

    def test_ставка_аренды_три_доллара(self) -> None:
        assert RENTAL_RATE == 3


class TestShopRates:
    """`game.lua`'s `GAME_MOD`: `joker_rate = 20`, `tarot_rate = 4`,
    `planet_rate = 4` — веса типов карт в слоте витрины, нужны оценке
    рерола (`solver/shop.py`, A5). Тест-«якорь» на случай молчаливой
    правки."""

    def test_веса_типов_карт_в_слоте(self) -> None:
        assert (SHOP_JOKER_RATE, SHOP_TAROT_RATE, SHOP_PLANET_RATE) == (20, 4, 4)

    def test_джокер_выпадает_чуть_чаще_двух_третей(self) -> None:
        total = SHOP_JOKER_RATE + SHOP_TAROT_RATE + SHOP_PLANET_RATE
        assert SHOP_JOKER_RATE / total == 20 / 28


class TestDiscountPercent:
    def test_без_ваучеров_скидки_нет(self) -> None:
        assert discount_percent(frozenset()) == 0

    def test_clearance_sale_даёт_25(self) -> None:
        assert discount_percent(frozenset({"v_clearance_sale"})) == 25

    def test_liquidation_даёт_50(self) -> None:
        assert discount_percent(frozenset({"v_clearance_sale", "v_liquidation"})) == 50


class TestЦенаРерола:
    """Улучшение A8. Цена ролла = база + число уже сделанных роллов
    (`functions/common_events.lua`'s `calculate_reroll_cost`), счётчик
    обнуляется каждый раунд — значит по наблюдаемой цене восстанавливается
    число роллов этого захода в магазин."""

    def test_база_из_исходника_игры(self) -> None:
        # `game.lua`: `starting_params.reroll_cost = 5`.
        assert BASE_REROLL_COST == 5
        assert reroll_base_cost(frozenset()) == 5

    def test_реролльные_ваучеры_вычитают_и_складываются(self) -> None:
        # В отличие от `interest_cap`, эти два не «задают», а вычитают по $2
        # каждый (`card.lua`, ветка Reroll Surplus/Reroll Glut).
        assert reroll_base_cost(frozenset({"v_reroll_surplus"})) == 3
        assert reroll_base_cost(frozenset({"v_reroll_glut"})) == 3
        assert reroll_base_cost(frozenset({"v_reroll_surplus", "v_reroll_glut"})) == 1

    def test_на_свежей_витрине_роллов_ноль(self) -> None:
        assert rerolls_done(5, frozenset()) == 0

    def test_каждый_ролл_поднимает_счётчик_на_один(self) -> None:
        assert rerolls_done(6, frozenset()) == 1
        assert rerolls_done(7, frozenset()) == 2
        assert rerolls_done(9, frozenset()) == 4

    def test_счётчик_учитывает_удешевляющие_ваучеры(self) -> None:
        # С Reroll Surplus база $3, значит цена $5 — это уже два ролла,
        # а не ноль, как было бы при базе $5.
        assert rerolls_done(5, frozenset({"v_reroll_surplus"})) == 2

    def test_цена_ниже_базы_не_даёт_отрицательный_счётчик(self) -> None:
        # Reroll-тег и Chaos the Clown временно опускают цену; оценка
        # занижается, но не уходит в минус — ограничение честно ослабляется,
        # а не ломается.
        assert rerolls_done(0, frozenset()) == 0
        assert rerolls_done(2, frozenset()) == 0
