"""Тесты совета по магазину (`balatro_bot/solver/shop.py`).

Проверяется второй кусок Фазы 8 плана («Стратегия рана»): контрфактум для
джокеров (реальный прирост счёта по представительным рукам) и честный текст
для ваучеров/паков, без выдуманной оценки того, что не с чем сравнить.
"""

from __future__ import annotations

from dataclasses import replace

from balatro_bot.adapters.manual import build_state
from balatro_bot.core.state import GameState, JokerCard, ShopItem
from balatro_bot.solver.shop import SAMPLE_HANDS, _interest, evaluate_shop


def _shop_state(**overrides: object) -> GameState:
    state = build_state("AH KH QH JH 9H 7C 7D 2S")
    state = replace(state, hand=())  # магазин: руки на этом экране нет
    return replace(state, **overrides)  # type: ignore[arg-type]


class TestEvaluateShop:
    def test_пустой_магазин_даёт_none(self) -> None:
        assert evaluate_shop(_shop_state()) is None

    def test_только_ваучеры_и_паки_без_джокеров(self) -> None:
        state = _shop_state(
            shop_vouchers=(
                ShopItem("v_overstock", "Overstock", "VOUCHER", 10, "+1 слот в магазине"),
            ),
            shop_packs=(ShopItem("p_arcana", "Arcana Pack", "BOOSTER", 4),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.jokers == ()
        assert advice.vouchers[0].item.label == "Overstock"
        assert advice.vouchers[0].expected_uplift is None
        assert advice.packs[0].label == "Arcana Pack"

    def test_известный_джокер_получает_положительную_оценку(self) -> None:
        # j_joker — "+4 Mult" безусловно, поэтому прирост почти всегда > 0
        # независимо от того, какая рука выпала при сэмплировании.
        state = _shop_state(
            money=10,
            joker_slots=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert len(advice.jokers) == 1
        offer = advice.jokers[0]
        assert offer.known is True
        assert offer.affordable is True
        assert offer.has_slot is True
        assert offer.expected_uplift is not None
        assert offer.expected_uplift > 0
        assert offer.samples == SAMPLE_HANDS

    def test_неизвестный_джокер_не_оценивается(self) -> None:
        state = _shop_state(
            money=10,
            shop=(ShopItem("j_совсем_новый", "???", "JOKER", 5),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        offer = advice.jokers[0]
        assert offer.known is False
        assert offer.expected_uplift is None
        assert offer.samples == 0

    def test_не_хватает_денег_помечено_но_всё_равно_оценено(self) -> None:
        state = _shop_state(
            money=1,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 99),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        offer = advice.jokers[0]
        assert offer.affordable is False
        assert offer.expected_uplift is not None  # оценка не зависит от кошелька

    def test_нет_свободного_слота(self) -> None:
        existing = tuple(JokerCard(key="j_joker") for _ in range(3))
        state = _shop_state(
            money=10,
            jokers=existing,
            joker_slots=3,
            shop=(ShopItem("j_greedy_joker", "Greedy Joker", "JOKER", 4),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.jokers[0].has_slot is False

    def test_без_ограничения_слотов_всегда_есть_место(self) -> None:
        state = _shop_state(
            money=10,
            joker_slots=None,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.jokers[0].has_slot is True

    def test_известные_идут_раньше_неизвестных(self) -> None:
        state = _shop_state(
            money=100,
            joker_slots=10,
            shop=(
                ShopItem("j_неизвестный", "???", "JOKER", 5),
                ShopItem("j_joker", "Joker", "JOKER", 3),
            ),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.jokers[0].item.key == "j_joker"
        assert advice.jokers[1].item.key == "j_неизвестный"

    def test_детерминирован(self) -> None:
        state = _shop_state(
            money=10,
            joker_slots=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        first = evaluate_shop(state)
        second = evaluate_shop(state)
        assert first == second

    def test_точная_колода_помечена_когда_full_deck_известен(self) -> None:
        state = _shop_state(
            money=10,
            joker_slots=5,
            full_deck=build_state("AH KH QH JH 9H 7C 7D 2S").hand + build_state("2H").hand,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.jokers[0].exact_deck is True

    def test_без_full_deck_колода_приближена(self) -> None:
        state = _shop_state(
            money=10,
            joker_slots=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.jokers[0].exact_deck is False

    def test_консумаблы_в_shop_не_считаются_джокерами(self) -> None:
        state = _shop_state(
            shop=(
                ShopItem("c_fool", "The Fool", "TAROT", 3, "Создаёт последнюю карту таро/планету"),
            ),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.jokers == ()


class TestПроценты:
    """Формула — `interest_amount * min(floor(dollars/5), interest_cap/5)`,
    выписана из `functions/state_events.lua` игры (`_interest` в
    `solver/shop.py`), не по памяти. По умолчанию `interest_amount=1`,
    `interest_cap=25` → максимум $5 за раунд, шаг — $1 за каждые $5."""

    def test_меньше_пяти_долларов_без_процентов(self) -> None:
        assert _interest(0, None) == 0
        assert _interest(4, None) == 0

    def test_шаг_один_доллар_на_каждые_пять(self) -> None:
        assert _interest(5, None) == 1
        assert _interest(9, None) == 1
        assert _interest(24, None) == 4

    def test_потолок_на_25_долларах(self) -> None:
        assert _interest(25, None) == 5
        assert _interest(1000, None) == 5  # выше потолка не растёт

    def test_green_deck_отключает_проценты_полностью(self) -> None:
        assert _interest(1000, "GREEN") == 0

    def test_отрицательные_деньги_не_ломают_формулу(self) -> None:
        # Гипотетическая покупка дороже кошелька — не должно случиться в
        # реальной игре, но формула не должна давать отрицательные проценты.
        assert _interest(-3, None) == 0

    def test_упущенные_проценты_джокера_в_общем_совете(self) -> None:
        # $10 -> $2 процента; после покупки за $3 останется $7 -> $1.
        # Упущено $1.
        state = _shop_state(
            money=10,
            joker_slots=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.jokers[0].interest_lost == 1

    def test_покупка_ниже_потолка_не_теряет_проценты(self) -> None:
        # $100 -> $5 (потолок), после покупки за $3 всё ещё $97 -> $5.
        state = _shop_state(
            money=100,
            joker_slots=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.jokers[0].interest_lost == 0

    def test_green_deck_в_общем_совете_тоже_ноль(self) -> None:
        state = _shop_state(
            money=10,
            joker_slots=5,
            deck_type="GREEN",
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.jokers[0].interest_lost == 0


class TestЦенаРерола:
    """`ShopAdvice.reroll_cost` — только показ живой цены (`GameState.reroll_cost`,
    область `round` мода), без вердикта «рероллить или нет» — см. модульный
    докстринг `solver/shop.py`."""

    def test_цена_рерола_передаётся_как_есть(self) -> None:
        state = _shop_state(
            money=10,
            joker_slots=5,
            reroll_cost=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.reroll_cost == 5

    def test_без_reroll_cost_в_состоянии_пусто(self) -> None:
        state = _shop_state(
            money=10,
            joker_slots=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.reroll_cost is None
