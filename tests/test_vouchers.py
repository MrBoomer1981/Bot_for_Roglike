"""Тесты оценки ваучеров (`balatro_bot/solver/vouchers.py`).

Фаза 9.3, первый (самый честный) из трёх уровней: только прямые игровые
ресурсы (лишняя рука/сброс за раунд, лишняя карта в руке) получают числовую
оценку без новых допущений; остальные 26 ваучеров сознательно получают
`expected_uplift = None` с пояснением, не молчание и не выдуманное число."""

from __future__ import annotations

from balatro_bot.core.cards import parse_cards, standard_deck
from balatro_bot.core.state import BlindInfo, GameState, ShopItem
from balatro_bot.solver.vouchers import evaluate_vouchers


def _voucher_state(**overrides: object) -> GameState:
    return GameState(phase="SHOP", **overrides)  # type: ignore[arg-type]


def _blind(status: str) -> BlindInfo:
    return BlindInfo(kind="SMALL", name="Small Blind", effect="", required_score=300, status=status)


class TestEvaluateVouchers:
    def test_без_ваучеров_в_магазине_пусто(self) -> None:
        assert evaluate_vouchers(_voucher_state()) == ()

    def test_лишняя_рука_даёт_положительную_оценку(self) -> None:
        state = _voucher_state(shop_vouchers=(ShopItem("v_grabber", "Grabber", "VOUCHER", 10),))
        offers = evaluate_vouchers(state, samples=4)
        assert len(offers) == 1
        offer = offers[0]
        assert offer.expected_uplift is not None
        assert offer.expected_uplift > 0
        assert offer.samples == 4

    def test_nacho_tong_тоже_оценивается_как_лишняя_рука(self) -> None:
        state = _voucher_state(
            shop_vouchers=(ShopItem("v_nacho_tong", "Nacho Tong", "VOUCHER", 10),)
        )
        offers = evaluate_vouchers(state, samples=4)
        assert offers[0].expected_uplift is not None
        assert offers[0].expected_uplift > 0

    def test_лишний_размер_руки_даёт_неотрицательную_оценку(self) -> None:
        state = _voucher_state(
            shop_vouchers=(ShopItem("v_paint_brush", "Paint Brush", "VOUCHER", 10),)
        )
        offers = evaluate_vouchers(state, samples=4)
        offer = offers[0]
        assert offer.expected_uplift is not None
        assert offer.expected_uplift >= 0

    def test_лишний_сброс_даёт_нижнюю_границу_с_примечанием(self) -> None:
        state = _voucher_state(shop_vouchers=(ShopItem("v_wasteful", "Wasteful", "VOUCHER", 10),))
        offers = evaluate_vouchers(state)
        offer = offers[0]
        assert offer.expected_uplift is not None
        assert offer.expected_uplift >= 0
        assert "одиночный сброс" in offer.note

    def test_recyclomancy_тоже_оценивается_как_лишний_сброс(self) -> None:
        state = _voucher_state(
            shop_vouchers=(ShopItem("v_recyclomancy", "Recyclomancy", "VOUCHER", 10),)
        )
        offers = evaluate_vouchers(state)
        assert offers[0].expected_uplift is not None
        assert offers[0].note

    def test_ваучер_вне_среза_получает_none_с_пояснением(self) -> None:
        state = _voucher_state(
            shop_vouchers=(ShopItem("v_hieroglyph", "Hieroglyph", "VOUCHER", 10),)
        )
        offers = evaluate_vouchers(state)
        offer = offers[0]
        assert offer.expected_uplift is None
        assert offer.note

    def test_несколько_ваучеров_сохраняют_порядок_как_в_состоянии(self) -> None:
        state = _voucher_state(
            shop_vouchers=(
                ShopItem("v_overstock_norm", "Overstock", "VOUCHER", 10),
                ShopItem("v_grabber", "Grabber", "VOUCHER", 10),
            )
        )
        offers = evaluate_vouchers(state, samples=4)
        assert [offer.item.key for offer in offers] == ["v_overstock_norm", "v_grabber"]

    def test_точная_колода_помечена_через_full_deck(self) -> None:
        state = _voucher_state(
            full_deck=standard_deck(),
            shop_vouchers=(ShopItem("v_grabber", "Grabber", "VOUCHER", 10),),
        )
        offers = evaluate_vouchers(state, samples=4)
        assert offers[0].exact_deck is True

    def test_без_full_deck_колода_приближена(self) -> None:
        state = _voucher_state(shop_vouchers=(ShopItem("v_grabber", "Grabber", "VOUCHER", 10),))
        offers = evaluate_vouchers(state, samples=4)
        assert offers[0].exact_deck is False

    def test_слишком_маленькая_колода_честно_не_оценивает(self) -> None:
        state = _voucher_state(
            full_deck=parse_cards("AH AS 2C"),
            shop_vouchers=(ShopItem("v_grabber", "Grabber", "VOUCHER", 10),),
        )
        offers = evaluate_vouchers(state, samples=4)
        assert offers[0].expected_uplift is None


class TestПотолокПроцентов:
    """Второй уровень честности: горизонт — реальное число оставшихся
    раундов анте (`GameState.blinds`), не выдуманная константа."""

    def test_seed_money_с_известным_горизонтом(self) -> None:
        # $30 -> потолок 25 даёт $5, потолок 50 даёт $6: +$1 за раунд, 2 раунда осталось.
        state = _voucher_state(
            money=30,
            blinds={"big": _blind("SELECT"), "boss": _blind("UPCOMING")},
            shop_vouchers=(ShopItem("v_seed_money", "Seed Money", "VOUCHER", 10),),
        )
        offers = evaluate_vouchers(state)
        offer = offers[0]
        assert offer.expected_uplift == 2.0
        assert "горизонт" in offer.note

    def test_money_tree_учитывает_уже_выкупленный_seed_money(self) -> None:
        # $60: потолок 50 -> $10, потолок 100 -> $12: +$2 за раунд, 1 раунд осталось.
        state = _voucher_state(
            money=60,
            used_vouchers=frozenset({"v_seed_money"}),
            blinds={"boss": _blind("SELECT")},
            shop_vouchers=(ShopItem("v_money_tree", "Money Tree", "VOUCHER", 10),),
        )
        offers = evaluate_vouchers(state)
        assert offers[0].expected_uplift == 2.0

    def test_без_области_blinds_честно_не_оценивает(self) -> None:
        state = _voucher_state(
            money=30, shop_vouchers=(ShopItem("v_seed_money", "Seed Money", "VOUCHER", 10),)
        )
        offers = evaluate_vouchers(state)
        assert offers[0].expected_uplift is None
        assert "раундов осталось" in offers[0].note

    def test_уже_defeated_блайнды_не_считаются_в_горизонт(self) -> None:
        state = _voucher_state(
            money=30,
            blinds={"small": _blind("DEFEATED"), "big": _blind("SELECT")},
            shop_vouchers=(ShopItem("v_seed_money", "Seed Money", "VOUCHER", 10),),
        )
        offers = evaluate_vouchers(state)
        assert offers[0].expected_uplift == 1.0


class TestСкидкаНаРероллы:
    def test_экономия_ограничена_текущей_ценой(self) -> None:
        state = _voucher_state(
            reroll_cost=1,
            shop_vouchers=(ShopItem("v_reroll_surplus", "Reroll Surplus", "VOUCHER", 10),),
        )
        offers = evaluate_vouchers(state)
        assert offers[0].expected_uplift == 1.0

    def test_полная_экономия_когда_цена_выше_шага(self) -> None:
        state = _voucher_state(
            reroll_cost=5,
            shop_vouchers=(ShopItem("v_reroll_glut", "Reroll Glut", "VOUCHER", 10),),
        )
        offers = evaluate_vouchers(state)
        assert offers[0].expected_uplift == 2.0

    def test_без_известной_цены_рерола_честно_не_оценивает(self) -> None:
        state = _voucher_state(
            shop_vouchers=(ShopItem("v_reroll_surplus", "Reroll Surplus", "VOUCHER", 10),)
        )
        offers = evaluate_vouchers(state)
        assert offers[0].expected_uplift is None


class TestСкидкаВМагазине:
    def test_clearance_sale_на_видимом_товаре(self) -> None:
        state = _voucher_state(
            shop=(
                ShopItem("j_joker", "Joker", "JOKER", 10),
                ShopItem("j_greedy_joker", "Greedy Joker", "JOKER", 20),
            ),
            shop_vouchers=(ShopItem("v_clearance_sale", "Clearance Sale", "VOUCHER", 10),),
        )
        offers = evaluate_vouchers(state)
        assert offers[0].expected_uplift == 8.0

    def test_liquidation_даёт_бОльшую_скидку(self) -> None:
        state = _voucher_state(
            shop=(
                ShopItem("j_joker", "Joker", "JOKER", 10),
                ShopItem("j_greedy_joker", "Greedy Joker", "JOKER", 20),
            ),
            shop_vouchers=(ShopItem("v_liquidation", "Liquidation", "VOUCHER", 10),),
        )
        offers = evaluate_vouchers(state)
        assert offers[0].expected_uplift == 15.0

    def test_паки_тоже_считаются(self) -> None:
        state = _voucher_state(
            shop_packs=(ShopItem("p_arcana", "Arcana Pack", "BOOSTER", 10),),
            shop_vouchers=(ShopItem("v_clearance_sale", "Clearance Sale", "VOUCHER", 10),),
        )
        offers = evaluate_vouchers(state)
        assert offers[0].expected_uplift == 3.0

    def test_пустой_магазин_даёт_ноль_а_не_none(self) -> None:
        state = _voucher_state(
            shop_vouchers=(ShopItem("v_clearance_sale", "Clearance Sale", "VOUCHER", 10),)
        )
        offers = evaluate_vouchers(state)
        assert offers[0].expected_uplift == 0.0
