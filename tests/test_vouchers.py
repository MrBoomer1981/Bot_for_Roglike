"""Тесты оценки ваучеров (`balatro_bot/solver/vouchers.py`).

Фаза 9.3, первый (самый честный) из трёх уровней: только прямые игровые
ресурсы (лишняя рука/сброс за раунд, лишняя карта в руке) получают числовую
оценку без новых допущений; остальные 26 ваучеров сознательно получают
`expected_uplift = None` с пояснением, не молчание и не выдуманное число."""

from __future__ import annotations

from balatro_bot.core.cards import parse_cards, standard_deck
from balatro_bot.core.state import GameState, ShopItem
from balatro_bot.solver.vouchers import evaluate_vouchers


def _voucher_state(**overrides: object) -> GameState:
    return GameState(phase="SHOP", **overrides)  # type: ignore[arg-type]


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
