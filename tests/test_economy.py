"""Тесты денежных формул (`balatro_bot/core/economy.py`).

Формулы выписаны из исходника игры, не по памяти — см. модульный докстринг
`core/economy.py`. Раньше жили как приватные тесты `solver/shop.py`;
вынесены сюда вместе с самими формулами, когда `solver/vouchers.py`
понадобилась та же логика (Фаза 9.3, второй уровень честности)."""

from __future__ import annotations

from balatro_bot.core.economy import RENTAL_RATE, discount_percent, interest, interest_cap


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


class TestDiscountPercent:
    def test_без_ваучеров_скидки_нет(self) -> None:
        assert discount_percent(frozenset()) == 0

    def test_clearance_sale_даёт_25(self) -> None:
        assert discount_percent(frozenset({"v_clearance_sale"})) == 25

    def test_liquidation_даёт_50(self) -> None:
        assert discount_percent(frozenset({"v_clearance_sale", "v_liquidation"})) == 50
