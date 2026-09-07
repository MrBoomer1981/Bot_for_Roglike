"""Тесты совета по магазину (`balatro_bot/solver/shop.py`).

Проверяется второй кусок Фазы 8 плана («Стратегия рана»): контрфактум для
джокеров (реальный прирост счёта по представительным рукам) и честный текст
для ваучеров/паков, без выдуманной оценки того, что не с чем сравнить.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Final

import pytest

from balatro_bot.adapters.manual import build_state
from balatro_bot.core.cards import parse_cards, standard_deck
from balatro_bot.core.hands import HandType, base_values
from balatro_bot.core.jokers import implemented_keys
from balatro_bot.core.scoring import score_play
from balatro_bot.core.state import BlindInfo, GameState, JokerCard, PokerHandInfo, ShopItem
from balatro_bot.solver import shop as shop_module
from balatro_bot.solver.pack import PLANET_HAND_TYPES
from balatro_bot.solver.play import advise
from balatro_bot.solver.shop import (
    _CARD_SHARP_REPEAT_RATE,
    _MONEY_SENSITIVE_JOKER_KEYS,
    SAMPLE_HANDS,
    _repeats_hand_type,
    _round_budget,
    _round_moment,
    _sample_cache_key,
    clear_shop_cache,
    evaluate_shop,
    joker_contributions,
    joker_uplift,
    sell_value_of,
)


def _shop_state(**overrides: object) -> GameState:
    state = build_state("AH KH QH JH 9H 7C 7D 2S")
    state = replace(state, hand=())  # магазин: руки на этом экране нет
    return replace(state, **overrides)  # type: ignore[arg-type]


def _hand_info() -> dict[HandType, PokerHandInfo]:
    """Таблица типов рук, какую всегда присылает мод. Ручной ввод
    (`build_state`) её не заполняет вовсе, поэтому всё, что зависит от
    `played_this_round`, надо проверять на состоянии живого вида."""
    return {
        hand_type: PokerHandInfo(
            level=1,
            chips=base_values(hand_type, 1).chips,
            mult=base_values(hand_type, 1).mult,
        )
        for hand_type in HandType
    }


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
        assert advice.packs[0].item.label == "Arcana Pack"
        assert advice.packs[0].expected_uplift is None  # оценивается только Buffoon

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
    """Сама формула теперь в `core/economy.py` (`tests/test_economy.py`) —
    здесь только сквозные тесты через `evaluate_shop`."""

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

    def test_выкупленный_seed_money_поднимает_потолок_в_расчёте(self) -> None:
        # $60 при потолке 50 -> $10; после покупки за $3 всё ещё $57 -> $10.
        # Без учёта ваучера потолок 25 дал бы $5 -> $5 (тоже 0), поэтому
        # берём сумму, где разница между потолками 25 и 50 реально заметна.
        state = _shop_state(
            money=60,
            joker_slots=5,
            used_vouchers=frozenset({"v_seed_money"}),
            shop=(ShopItem("j_joker", "Joker", "JOKER", 15),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        # $60 -> $10 (потолок 50), после покупки за $15 -> $45 -> $9. Упущен $1.
        assert advice.jokers[0].interest_lost == 1


class TestОценкаРерола:
    """`ShopAdvice.reroll` (`RerollOutlook`) — Монте-Карло механизма ролла
    (улучшение A5), см. модульный докстринг `solver/shop.py`."""

    def test_цена_и_ожидаемый_прирост_посчитаны(self) -> None:
        state = _shop_state(
            money=10,
            joker_slots=5,
            shop_slots=2,
            reroll_cost=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.reroll is not None
        assert advice.reroll.cost == 5
        assert advice.reroll.affordable is True
        assert advice.reroll.slots == 2
        # j_joker безусловный "+4 Mult" — в выборке случайных реализованных
        # джокеров всегда есть положительные, значит E[лучший из 2] > 0.
        assert advice.reroll.expected_best_uplift is not None
        assert advice.reroll.expected_best_uplift > 0

    def test_меньше_слотов_витрины_меньше_ожидаемый_прирост(self) -> None:
        def _outlook(shop_slots: int) -> float:
            state = _shop_state(
                money=10,
                joker_slots=5,
                reroll_cost=5,
                shop_slots=shop_slots,
                shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
            )
            advice = evaluate_shop(state)
            assert advice is not None and advice.reroll is not None
            assert advice.reroll.expected_best_uplift is not None
            return advice.reroll.expected_best_uplift

        assert _outlook(4) > _outlook(1)

    def test_без_reroll_cost_в_состоянии_нет_оценки(self) -> None:
        state = _shop_state(
            money=10,
            joker_slots=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.reroll is None

    def test_дорогой_реролл_помечен_неподъёмным(self) -> None:
        state = _shop_state(
            money=3,
            joker_slots=5,
            reroll_cost=8,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.reroll is not None
        assert advice.reroll.affordable is False


class TestПокупкаПака:
    """`ShopAdvice.packs` — оценка есть у Buffoon- и Celestial-пака,
    Монте-Карло механизма пака (`PackPurchaseOffer`)."""

    def test_buffoon_пак_получает_положительную_оценку(self) -> None:
        state = _shop_state(
            money=10,
            joker_slots=5,
            shop_packs=(ShopItem("p_buffoon_normal_1", "Buffoon Pack", "BOOSTER", 4),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        pack = advice.packs[0]
        assert pack.affordable is True
        assert pack.has_slot is True
        assert pack.expected_uplift is not None
        assert pack.expected_uplift > 0
        assert "лучшие 1 из 2" in pack.note

    def test_mega_пак_оценивается_как_2_из_4(self) -> None:
        normal = _shop_state(
            money=20,
            joker_slots=5,
            shop_packs=(ShopItem("p_buffoon_normal_1", "Buffoon Pack", "BOOSTER", 4),),
        )
        mega = _shop_state(
            money=20,
            joker_slots=5,
            shop_packs=(ShopItem("p_buffoon_mega_1", "Mega Buffoon Pack", "BOOSTER", 8),),
        )
        n = evaluate_shop(normal)
        m = evaluate_shop(mega)
        assert n is not None and m is not None
        assert "лучшие 2 из 4" in m.packs[0].note
        # Mega показывает 4 и берёт 2 — оценка ощутимо выше normal (2 из 2 → 1).
        assert m.packs[0].expected_uplift is not None
        assert n.packs[0].expected_uplift is not None
        assert m.packs[0].expected_uplift > n.packs[0].expected_uplift

    def test_celestial_пак_получает_положительную_оценку(self) -> None:
        state = _shop_state(
            money=10,
            joker_slots=5,
            shop_packs=(ShopItem("p_celestial_normal_1", "Celestial Pack", "BOOSTER", 4),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        pack = advice.packs[0]
        assert pack.affordable is True
        assert pack.has_slot is True  # планетам слот не нужен
        assert pack.expected_uplift is not None
        assert pack.expected_uplift > 0
        assert "лучшие 1 из 3" in pack.note

    def test_mega_celestial_оценивается_как_2_из_5(self) -> None:
        normal = _shop_state(
            money=20,
            joker_slots=5,
            shop_packs=(ShopItem("p_celestial_normal_1", "Celestial Pack", "BOOSTER", 4),),
        )
        mega = _shop_state(
            money=20,
            joker_slots=5,
            shop_packs=(ShopItem("p_celestial_mega_1", "Mega Celestial Pack", "BOOSTER", 8),),
        )
        n = evaluate_shop(normal)
        m = evaluate_shop(mega)
        assert n is not None and m is not None
        assert "лучшие 2 из 5" in m.packs[0].note
        assert m.packs[0].expected_uplift is not None
        assert n.packs[0].expected_uplift is not None
        assert m.packs[0].expected_uplift > n.packs[0].expected_uplift

    def test_arcana_пак_не_оценивается(self) -> None:
        state = _shop_state(
            money=10,
            joker_slots=5,
            shop_packs=(ShopItem("p_arcana_normal_1", "Arcana Pack", "BOOSTER", 4),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.packs[0].expected_uplift is None

    def test_нет_слота_помечено_но_оценка_всё_равно_есть(self) -> None:
        state = _shop_state(
            money=10,
            joker_slots=0,  # слотов нет
            shop_packs=(ShopItem("p_buffoon_normal_1", "Buffoon Pack", "BOOSTER", 4),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.packs[0].has_slot is False
        assert advice.packs[0].expected_uplift is not None


class TestСтикерыСтавок:
    """Фаза 9.6: `eternal`/`perishable`/`rental` из `ShopItem` доходят до
    `JokerOffer` отдельными полями (по образцу `interest_lost`), не
    сворачиваясь в `expected_uplift`."""

    def test_без_стикеров_поля_по_умолчанию(self) -> None:
        state = _shop_state(
            money=10, joker_slots=5, shop=(ShopItem("j_joker", "Joker", "JOKER", 3),)
        )
        advice = evaluate_shop(state)
        assert advice is not None
        offer = advice.jokers[0]
        assert offer.rental_cost_per_round == 0
        assert offer.perishable_rounds is None
        assert offer.eternal is False

    def test_арендный_джокер_несёт_цену_за_раунд(self) -> None:
        state = _shop_state(
            money=10,
            joker_slots=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 1, rental=True),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        offer = advice.jokers[0]
        assert offer.rental_cost_per_round == 3
        # Оценка счёта считается как обычно — аренда в неё не вплавлена.
        assert offer.expected_uplift is not None
        assert offer.expected_uplift > 0

    def test_портящийся_джокер_несёт_остаточный_срок(self) -> None:
        state = _shop_state(
            money=10,
            joker_slots=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3, perishable_rounds=2),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.jokers[0].perishable_rounds == 2

    def test_вечный_джокер_помечен(self) -> None:
        state = _shop_state(
            money=10,
            joker_slots=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3, eternal=True),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.jokers[0].eternal is True

    def test_неоценённый_джокер_всё_равно_несёт_стикеры(self) -> None:
        state = _shop_state(
            money=10,
            joker_slots=5,
            shop=(ShopItem("j_совсем_новый", "???", "JOKER", 1, rental=True, eternal=True),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        offer = advice.jokers[0]
        assert offer.expected_uplift is None
        assert offer.rental_cost_per_round == 3
        assert offer.eternal is True


class TestПродажаЗамена:
    """`joker_contributions` + `JokerOffer.replaces` — когда все слоты
    заняты, `evaluate_shop` цепляет к оценённым офферам самого слабого
    невечного джокера в слотах (кандидата на вылет под размен)."""

    def test_вклад_отключённого_джокера_ровно_ноль(self) -> None:
        # Движок пропускает debuffed-джокера целиком, значит счёт с ним и
        # без него совпадает — вклад строго 0.0, без шума сэмплирования.
        state = _shop_state(
            jokers=(JokerCard(key="j_joker"), JokerCard(key="j_joker", debuffed=True)),
            joker_slots=2,
        )
        contributions = joker_contributions(state, standard_deck(), 4)
        assert len(contributions) == 2
        assert contributions[0] > 0  # рабочий "+4 Mult"
        assert contributions[1] == 0.0  # отключённый

    def test_нет_джокеров_пустой_кортеж(self) -> None:
        assert joker_contributions(_shop_state(), standard_deck(), 4) == ()

    def test_оффер_несёт_слабейшего_кандидата_на_вылет(self) -> None:
        state = _shop_state(
            money=10,
            jokers=(JokerCard(key="j_joker"), JokerCard(key="j_joker", debuffed=True)),
            joker_slots=2,  # слоты полны
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        cand = advice.jokers[0].replaces
        assert cand is not None
        assert cand.index == 1  # отключённый — самый слабый
        assert cand.contribution == 0.0

    def test_вечный_джокер_не_кандидат_на_вылет(self) -> None:
        # Отключённый джокер слабее, но он вечный — продать нельзя, значит
        # кандидат — рабочий j_joker в слоте 1.
        state = _shop_state(
            money=10,
            jokers=(
                JokerCard(key="j_joker", debuffed=True, eternal=True),
                JokerCard(key="j_joker"),
            ),
            joker_slots=2,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        cand = advice.jokers[0].replaces
        assert cand is not None
        assert cand.index == 1

    def test_есть_свободный_слот_замена_не_нужна(self) -> None:
        state = _shop_state(
            money=10,
            jokers=(JokerCard(key="j_joker"),),
            joker_slots=5,  # места полно
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.jokers[0].replaces is None

    def test_все_джокеры_вечные_кандидата_нет(self) -> None:
        state = _shop_state(
            money=10,
            jokers=(
                JokerCard(key="j_joker", eternal=True),
                JokerCard(key="j_joker", eternal=True),
            ),
            joker_slots=2,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.jokers[0].replaces is None


def _score_at_money(key: str, money: int) -> float:
    """Счёт фиксированного розыгрыша с одним джокером при заданных деньгах."""
    hand = parse_cards("AH KH QH JH 9H")
    state = GameState(hand=hand, jokers=(JokerCard(key=key),), money=money)
    return score_play(state, hand).expected


class TestДенежноЧувствительныеДжокеры:
    """Улучшение F2. `_MONEY_SENSITIVE_JOKER_KEYS` — единственная причина, по
    которой деньги нельзя выкинуть из ключа мемо. Список проверяется
    поведением (счёт реально меняется от денег), а не сканом исходника — тот
    же приём, что у `_SUIT_SENSITIVE_JOKER_KEYS` в `solver/discard.py`."""

    def test_каждый_ключ_из_списка_действительно_зависит_от_денег(self) -> None:
        for key in _MONEY_SENSITIVE_JOKER_KEYS:
            assert _score_at_money(key, 0) != _score_at_money(key, 40), key

    def test_список_полон_прочие_джокеры_от_денег_не_зависят(self) -> None:
        # Если кто-то добавит джокера, читающего `state.money`, и забудет
        # внести его сюда, кеш начнёт возвращать устаревшие выборки — этот
        # тест ловит именно такую поломку.
        for key in sorted(implemented_keys()):
            if key in _MONEY_SENSITIVE_JOKER_KEYS:
                continue
            assert _score_at_money(key, 0) == _score_at_money(key, 40), key


class TestКешВыборок:
    """Улучшение F2: дорогие выборки переживают реролл и повторный опрос, но
    не переживают смену того, что реально влияет на счёт."""

    def _state(self, **overrides: object) -> GameState:
        base: dict[str, object] = {
            "money": 25,
            "reroll_cost": 5,
            "shop_slots": 2,
            "shop": (ShopItem("j_joker", "Joker", "JOKER", 3, "+4 Mult"),),
        }
        return _shop_state(**{**base, **overrides})

    def _count_uplifts(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """Подменить `joker_uplift` считающей обёрткой — так «пересчитали
        или взяли из кеша» проверяется прямо, а не по времени."""
        seen: list[str] = []
        real = shop_module.joker_uplift

        def counting(
            state: GameState,
            joker: JokerCard,
            deck: object,
            samples: int,
            money_delta: int = 0,
        ) -> float:
            seen.append(joker.key)
            return real(state, joker, deck, samples, money_delta)  # type: ignore[arg-type]

        monkeypatch.setattr(shop_module, "joker_uplift", counting)
        return seen

    def test_кеш_не_меняет_ответ(self) -> None:
        state = self._state()
        clear_shop_cache()
        cached = evaluate_shop(state)
        clear_shop_cache()
        fresh = evaluate_shop(state, use_cache=False)
        assert cached == fresh

    def test_реролл_переиспользует_выборку_случайных_джокеров(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state = self._state()
        clear_shop_cache()
        evaluate_shop(state)  # прогрев

        seen = self._count_uplifts(monkeypatch)
        # Реролл меняет ровно три вещи: витрину, деньги и цену ролла.
        rerolled = replace(
            state,
            money=state.money - 5,
            reroll_cost=6,
            shop=(ShopItem("j_greedy_joker", "Greedy Joker", "JOKER", 5),),
        )
        evaluate_shop(rerolled)
        # Пересчитан только новый джокер витрины; выборка из 24 случайных —
        # нет, иначе список был бы на два десятка длиннее.
        assert seen == ["j_greedy_joker"]

    def test_повторный_опрос_той_же_витрины_ничего_не_считает(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state = self._state()
        clear_shop_cache()
        evaluate_shop(state)

        seen = self._count_uplifts(monkeypatch)
        evaluate_shop(state)
        assert seen == []

    def test_тот_же_джокер_после_реролла_не_пересэмплируется(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state = self._state()
        clear_shop_cache()
        evaluate_shop(state)

        seen = self._count_uplifts(monkeypatch)
        again = replace(state, money=20, reroll_cost=6)
        evaluate_shop(again)
        assert seen == []  # тот же `j_joker` — мемо по (ключ, издание)

    def test_смена_джокеров_в_слотах_сбрасывает_кеш(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = self._state()
        clear_shop_cache()
        evaluate_shop(state)

        seen = self._count_uplifts(monkeypatch)
        evaluate_shop(replace(state, jokers=(JokerCard(key="j_droll", label="Droll Joker"),)))
        # Контрфактум считается относительно другого набора — всё заново.
        assert "j_joker" in seen

    def test_без_денежного_джокера_смена_денег_не_сбрасывает_кеш(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state = self._state()
        clear_shop_cache()
        evaluate_shop(state)

        seen = self._count_uplifts(monkeypatch)
        evaluate_shop(replace(state, money=40))
        assert seen == []

    def test_с_денежным_джокером_смена_денег_сбрасывает_кеш(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state = self._state(jokers=(JokerCard(key="j_bull", label="Bull"),))
        clear_shop_cache()
        evaluate_shop(state)

        seen = self._count_uplifts(monkeypatch)
        evaluate_shop(replace(state, money=40))
        assert "j_joker" in seen


class TestВкладыВСлотах:
    """Улучшение A9: вклад джокеров в слотах меряется всегда, а не только
    при полных слотах — иначе бот не видит балласт, пока слот свободен."""

    def test_вклады_считаются_при_свободном_слоте(self) -> None:
        state = _shop_state(
            jokers=(JokerCard(key="j_joker", label="Joker"),),
            joker_slots=5,  # слоты НЕ полны
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert len(advice.held) == 1
        assert advice.held[0].label == "Joker"
        assert advice.held[0].contribution > 0

    def test_порядок_held_совпадает_с_порядком_джокеров(self) -> None:
        state = _shop_state(
            jokers=(
                JokerCard(key="j_joker", label="Первый"),
                JokerCard(key="j_droll", label="Второй"),
            ),
            joker_slots=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert [entry.index for entry in advice.held] == [0, 1]
        assert [entry.label for entry in advice.held] == ["Первый", "Второй"]

    def test_stencil_делает_вклад_балласта_отрицательным(self) -> None:
        # `Joker Stencil` даёт множитель за каждый пустой слот, поэтому
        # джокер с нулевым собственным вкладом стоит меньше пустого слота —
        # ровно случай рана 8.
        state = _shop_state(
            jokers=(
                JokerCard(key="j_stencil", label="Joker Stencil"),
                JokerCard(key="j_rough_gem", label="Rough Gem"),  # на счёт не влияет
            ),
            joker_slots=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        вклады = {entry.label: entry.contribution for entry in advice.held}
        assert вклады["Joker Stencil"] > 0
        assert вклады["Rough Gem"] < 0

    def test_вечный_джокер_помечен_в_held(self) -> None:
        state = _shop_state(
            jokers=(JokerCard(key="j_joker", label="Joker", eternal=True),),
            joker_slots=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.held[0].eternal is True

    def test_без_джокеров_held_пуст(self) -> None:
        advice = evaluate_shop(_shop_state(shop=(ShopItem("j_joker", "Joker", "JOKER", 3),)))
        assert advice is not None
        assert advice.held == ()

    def test_при_свободном_слоте_кандидата_на_вылет_нет(self) -> None:
        # Вклады теперь есть, но размен без полных слотов по-прежнему не
        # предлагается: менять не на что, покупают просто так.
        state = _shop_state(
            money=10,
            jokers=(JokerCard(key="j_joker"),),
            joker_slots=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.held != ()
        assert all(offer.replaces is None for offer in advice.jokers)


class TestМоментРаунда:
    """Улучшение A10: контрфактум сэмплирует не только руку, но и момент
    раунда. Раньше все выборки считались в состоянии витрины, где раунд не
    начинался, и шесть джокеров оценивались в одной неверной точке."""

    def _state(self, hands: int = 4, discards: int = 4) -> GameState:
        return _shop_state(hands_left=hands, discards_left=discards)

    def test_первый_шаг_это_начало_раунда(self) -> None:
        moment = _round_moment(self._state(), 0, 4)
        assert moment.hands_left == 4
        assert moment.hands_played == 0
        assert moment.discards_left == 4

    def test_последний_шаг_это_последняя_рука_без_сбросов(self) -> None:
        moment = _round_moment(self._state(), 3, 4)
        assert moment.hands_left == 1
        assert moment.hands_played == 3
        assert moment.discards_left == 0

    def test_бюджет_берётся_из_состояния_без_догадок(self) -> None:
        assert _round_budget(self._state(hands=4)) == 4
        assert _round_budget(self._state(hands=1)) == 1
        # Источник не прислал — единственный моделируемый момент, не выдумка.
        assert _round_budget(self._state(hands=0)) == 1


class TestОценкаПоМоментуРаунда:
    """Регрессия, ради которой A10 и делалась: в ране 9 `Acrobat` измерился
    ровно в 0 и был продан как балласт, а `Ice Cream` куплен по оценке,
    снятой в его максимуме."""

    def _state(self, *jokers: str) -> GameState:
        deck = standard_deck()
        return _shop_state(
            jokers=tuple(JokerCard(key=key) for key in jokers),
            hands_left=4,
            discards_left=4,
            deck=deck,
            full_deck=deck,
        )

    def _uplift(self, key: str) -> float:
        state = self._state("j_joker")
        return joker_uplift(state, JokerCard(key=key), standard_deck(), SAMPLE_HANDS)

    def test_acrobat_больше_не_ноль(self) -> None:
        # X3 множ. на последней руке раунда — раньше условие не выполнялось
        # ни в одной выборке, потому что hands_left всегда был полным.
        assert self._uplift("j_acrobat") > 0

    def test_mystic_summit_больше_не_ноль(self) -> None:
        # +15 множ. при нуле сбросов — нужен момент, где сбросы кончились.
        assert self._uplift("j_mystic_summit") > 0

    def test_banner_и_mystic_summit_положительны_одновременно(self) -> None:
        # Условия у них взаимоисключающие в пределах одного момента: у одного
        # сбросы есть, у другого их нет. Оба положительны только если график
        # действительно охватывает разные моменты раунда — это и есть прямая
        # проверка механизма, а не его следствий.
        assert self._uplift("j_banner") > 0
        assert self._uplift("j_mystic_summit") > 0

    def test_card_sharp_без_таблицы_рук_остаётся_нулём(self) -> None:
        # Ручной ввод не присылает `hand_info` вовсе, и тогда джокеру
        # нечего читать: он честно помечает счёт неизвестным, а не
        # выдумывает повтор. Момент раунда тут ни при чём — см. A11 и
        # `TestПовторТипаРуки` для живого случая.
        assert self._uplift("j_card_sharp") == 0

    def test_вклад_acrobat_на_доске_рана_9(self) -> None:
        # Та самая доска, с которой бот продал Acrobat как пустого.
        state = self._state("j_misprint", "j_stuntman", "j_half", "j_acrobat")
        contributions = joker_contributions(state, standard_deck(), SAMPLE_HANDS)
        assert contributions[3] > 0

    def test_раунд_в_одну_руку_считается_как_последняя(self) -> None:
        # Если состояние говорит «осталась одна рука», то единственный
        # честный момент — последняя рука, и Acrobat в ней работает всегда.
        state = replace(self._state("j_joker"), hands_left=1)
        many = joker_uplift(state, JokerCard(key="j_acrobat"), standard_deck(), SAMPLE_HANDS)
        assert many > self._uplift("j_acrobat")


class TestПовторТипаРуки:
    """Улучшение A11, пробел 1. `j_card_sharp` даёт X3 множ., если тип руки
    уже игрался в этом раунде, но `_round_moment` старил только
    `hands_left`/`hands_played`/`discards_left` — `played_this_round` во всех
    выборках оставался нулём, джокер стоил ровно 0 и в ране 10 был продан."""

    def _state(self, *jokers: str, **overrides: object) -> GameState:
        deck = standard_deck()
        return _shop_state(
            jokers=tuple(JokerCard(key=key) for key in jokers),
            hands_left=4,
            discards_left=4,
            deck=deck,
            full_deck=deck,
            hand_info=_hand_info(),
            **overrides,
        )

    def test_пометка_ставится_всем_типам_и_не_трогает_уровни(self) -> None:
        state = self._state()
        moment = _round_moment(state, 1, 4, repeat=True)
        assert all(info.played_this_round >= 1 for info in moment.hand_info.values())
        for hand_type, info in moment.hand_info.items():
            было = state.hand_info[hand_type]
            assert (info.level, info.chips, info.mult) == (было.level, было.chips, было.mult)

    def test_без_флага_таблица_не_меняется(self) -> None:
        state = self._state()
        assert _round_moment(state, 1, 4).hand_info == state.hand_info

    def test_первая_рука_раунда_никогда_не_повтор(self) -> None:
        # Повторять в начале раунда нечего — это факт правил, не допущение.
        assert not any(_repeats_hand_type(0, cycle) for cycle in range(10))

    def test_доля_повторов_сходится_к_измеренной(self) -> None:
        # Раскладка по циклам должна давать ровно `int(C * rate)` срабатываний.
        for циклов in (3, 10, 25, 100):
            сработало = sum(1 for c in range(циклов) if _repeats_hand_type(1, c))
            assert сработало == int(циклов * _CARD_SHARP_REPEAT_RATE), циклов

    def test_card_sharp_больше_не_ноль(self) -> None:
        # Прямая регрессия рана 10: джокер оценивался в 0 и продавался.
        state = self._state("j_joker")
        uplift = joker_uplift(state, JokerCard(key="j_card_sharp"), standard_deck(), SAMPLE_HANDS)
        assert uplift > 0

    def test_под_боссом_на_легальность_пометка_снимается(self) -> None:
        # `solver/play.py._is_legal_play` читает то же поле: под `The Eye`
        # «сыграны все типы» сделало бы нелегальным каждый розыгрыш. Значит
        # и оценка тут снова 0 — узкий явный отказ вместо неверного числа.
        глаз = BlindInfo(kind="Boss", name="The Eye", effect="", required_score=1000)
        state = self._state("j_joker", blind=глаз)
        moment = _round_moment(state, 1, 4, repeat=True)
        assert moment.hand_info == state.hand_info
        uplift = joker_uplift(state, JokerCard(key="j_card_sharp"), standard_deck(), SAMPLE_HANDS)
        assert uplift == 0


class TestДеньгиПослеСделки:
    """Улучшение A11, пробел 2. Прирост считался при деньгах ДО покупки, хотя
    `j_bull`/`j_bootstraps` читают `GameState.money` напрямую, — и тем
    сильнее завышал оффер, чем он дороже."""

    def _state(self, *jokers: str) -> GameState:
        deck = standard_deck()
        return _shop_state(
            jokers=tuple(JokerCard(key=key) for key in jokers),
            hands_left=4,
            discards_left=4,
            money=40,
            deck=deck,
            full_deck=deck,
            hand_info=_hand_info(),
        )

    def _uplift(self, key: str, money_delta: int = 0) -> float:
        return joker_uplift(
            self._state(), JokerCard(key=key), standard_deck(), SAMPLE_HANDS, money_delta
        )

    def test_цена_снижает_прирост_денежного_джокера(self) -> None:
        assert self._uplift("j_bull", -12) < self._uplift("j_bull", -6) < self._uplift("j_bull")

    def test_на_неденежном_джокере_сдвиг_ничего_не_меняет(self) -> None:
        # Сдвиг обязан быть виден ровно там, где деньги читаются, иначе это
        # не поправка, а шум по всей витрине.
        assert self._uplift("j_joker", -12) == self._uplift("j_joker")

    def test_вклад_считается_с_учётом_выручки_от_продажи(self) -> None:
        # Продажа возвращает деньги, а оставшийся в слоте `j_bull` их читает,
        # поэтому чистый вклад продаваемого джокера меньше: часть потери
        # компенсируется выручкой. Именно эта величина сравнивается с
        # приростом оффера, уже посчитанным после траты.
        deck = standard_deck()

        def вклад(sell_value: int | None) -> float:
            state = _shop_state(
                jokers=(JokerCard(key="j_bull"), JokerCard(key="j_joker", sell_value=sell_value)),
                hands_left=4,
                discards_left=4,
                money=10,
                deck=deck,
                full_deck=deck,
                hand_info=_hand_info(),
            )
            return joker_contributions(state, deck, SAMPLE_HANDS)[1]

        assert вклад(20) < вклад(None)

    def test_ключ_кеша_видит_денежного_джокера_на_витрине(self) -> None:
        # Пробел 2b: до A11 `money_matters` смотрел только на слоты, и с
        # Bull'ом на полке покупка чего-то другого меняла деньги, не меняя
        # ключа, — прирост Bull'а выдавался из кеша на старых деньгах.
        полка = (ShopItem("j_bull", "Bull", "JOKER", 6),)
        богатый = _shop_state(money=40, shop=полка)
        бедный = _shop_state(money=10, shop=полка)
        assert _sample_cache_key(богатый, SAMPLE_HANDS) != _sample_cache_key(бедный, SAMPLE_HANDS)

    def test_без_денежных_джокеров_ключ_по_прежнему_не_зависит_от_денег(self) -> None:
        полка = (ShopItem("j_joker", "Joker", "JOKER", 3),)
        богатый = _shop_state(money=40, shop=полка)
        бедный = _shop_state(money=10, shop=полка)
        assert _sample_cache_key(богатый, SAMPLE_HANDS) == _sample_cache_key(бедный, SAMPLE_HANDS)


class TestЦенаПродажиКандидата:
    """Улучшение A18. Кандидат в контрфактуме строился **без цены продажи**, а
    `j_swashbuckler` считает свой множитель по сумме цен продажи остальных
    джокеров. Неизвестное значение роняло и число, и точность: прирост
    безусловно полезного `j_joker` (+4 множ.) выходил **отрицательным** —
    −1571 на доске рана из большого батча, — то есть контрфактум был настроен
    против любой покупки, пока Swashbuckler на доске.

    Тот же класс, что A10 и A11: кандидат собирался в состоянии, в котором
    игра никогда не бывает."""

    def _state(self) -> GameState:
        доска = tuple(
            JokerCard(key=k, label=k, current_value=5, sell_value=3)
            for k in ("j_odd_todd", "j_greedy_joker", "j_swashbuckler", "j_jolly", "j_duo")
        )
        deck = standard_deck()
        return _shop_state(
            money=21,
            joker_slots=5,
            shop_slots=2,
            jokers=доска,
            deck=deck,
            full_deck=deck,
            hands_left=4,
            discards_left=4,
            hand_info=_hand_info(),
            shop=(ShopItem("j_joker", "Joker", "JOKER", 4),),
        )

    def test_безусловно_полезный_джокер_не_уходит_в_минус(self) -> None:
        # +4 множителя не могут уменьшить счёт: отрицательный прирост здесь
        # математически невозможен и означает дефект.
        advice = evaluate_shop(self._state())
        assert advice is not None
        (offer,) = advice.jokers
        assert offer.expected_uplift is not None
        assert offer.expected_uplift > 0, offer.expected_uplift

    def test_оценка_остаётся_точной_при_swashbuckler(self) -> None:
        # Раньше расчёт помечался неточным «цена продажи джокера неизвестна».
        state = self._state()
        кандидат = JokerCard(key="j_joker", label="Joker", sell_value=sell_value_of(4))
        assert joker_uplift(state, кандидат, standard_deck(), SAMPLE_HANDS) > 0

    def test_правило_цены_продажи_из_игры(self) -> None:
        # `card.lua`: sell_cost = max(1, floor(cost / 2)).
        assert sell_value_of(0) == 1
        assert sell_value_of(1) == 1
        assert sell_value_of(4) == 2
        assert sell_value_of(5) == 2
        assert sell_value_of(10) == 5


#: Улучшение A20. Джокеры, реализованные безусловной плоской прибавкой —
#: перечислены по самим реализациям, а не по памяти: у каждого `on_turn`
#: состоит из одного `yield` без единой проверки. Добавление такого джокера
#: не может уменьшить счёт ни на какой доске, и это арифметика, а не
#: суждение.
_ВСЕГДА_ПОЛЕЗНЫЕ: Final[tuple[str, ...]] = (
    "j_joker",  # +4 множ.
    "j_gros_michel",  # +15 множ.
    "j_cavendish",  # X3 множ.
    "j_stuntman",  # +250 фишек
)

#: Джокеры, читающие **других джокеров**, — именно там «состояние, в котором
#: игра не бывает» становится видимым, и именно там жили A9, A11 и A18.
_ДОСКИ_БЕЗ_STENCIL: Final[tuple[tuple[str, ...], ...]] = (
    (),
    ("j_joker",),
    ("j_swashbuckler",),  # сумма цен продажи остальных — спусковой крючок A18
    ("j_abstract",),  # +3 множ. за каждого джокера
    ("j_baseball",),  # X1.5 за каждого Uncommon
    ("j_swashbuckler", "j_abstract", "j_baseball"),
)

#: Доски, где **никто не считает джокеров**. Нужны отдельно: на доске с
#: `j_abstract` (+3 множ. за джокера) или `j_swashbuckler` даже
#: бездействующий джокер законно поднимает счёт — просто тем, что занял
#: место в списке. Это поведение игры, а не дефект, и первая версия
#: инварианта «бездействующий даёт ровно ноль» была из-за этого
#: сформулирована слишком широко и падала.
_ДОСКИ_БЕЗ_СЧЁТА_ДЖОКЕРОВ: Final[tuple[tuple[str, ...], ...]] = (
    (),
    ("j_joker",),
    ("j_joker", "j_droll"),
)


class TestИнвариантыКонтрфактума:
    """Улучшение A20: чего оценка джокера не имеет права выдавать никогда.

    Четыре дефекта этой сессии — A9, A10, A11, A18 — один класс: джокер
    оценивался из состояния, в котором игра не бывает. Все четыре нашла
    живая игра; ни одного не поймали ни ревью, ни тысяча тестов, потому что
    все они проверяли, **что джокер считает**, и ни один — **чего
    контрфактум выдать не может**.

    У A18 подпись была видна без игры: `j_joker` с безусловными +4
    множителя давал прирост −1571. Этот класс тестов и есть попытка ловить
    следующий такой случай на месте.
    """

    def _state(self, доска: tuple[str, ...], *, слотов: int = 5) -> GameState:
        deck = standard_deck()
        return _shop_state(
            money=25,
            joker_slots=слотов,
            jokers=tuple(JokerCard(key=k, label=k, current_value=5, sell_value=3) for k in доска),
            deck=deck,
            full_deck=deck,
            hands_left=4,
            discards_left=4,
            hand_info=_hand_info(),
        )

    def _прирост(self, доска: tuple[str, ...], ключ: str, **kw: object) -> float:
        кандидат = JokerCard(key=ключ, label=ключ, sell_value=sell_value_of(5))
        return joker_uplift(self._state(доска, **kw), кандидат, standard_deck(), 3)  # type: ignore[arg-type]

    @pytest.mark.parametrize("ключ", _ВСЕГДА_ПОЛЕЗНЫЕ)
    @pytest.mark.parametrize("доска", _ДОСКИ_БЕЗ_STENCIL)
    def test_безусловный_джокер_не_вредит(self, доска: tuple[str, ...], ключ: str) -> None:
        assert self._прирост(доска, ключ) >= 0, (доска, ключ)

    def test_случай_a18_на_доске_со_swashbuckler(self) -> None:
        # Прямая регрессия: тут было −1571.
        доска = ("j_odd_todd", "j_greedy_joker", "j_swashbuckler", "j_jolly", "j_duo")
        assert self._прирост(доска, "j_joker") > 0

    def test_stencil_законно_уходит_в_минус(self) -> None:
        # Единственное настоящее исключение, и это находка A9: `Joker Stencil`
        # множит за каждый **пустой** слот, поэтому джокер может стоить меньше
        # пустого слота. Инвариант обязан знать про этот случай, иначе он
        # ложно упадёт и его удалят как ненадёжный.
        #
        # Кандидат тут намеренно бездействующий: сильный джокер своей прибавкой
        # перекрывает потерю множителя, и знак не меняется — на чём две первые
        # версии этого теста и ошиблись.
        assert self._прирост(("j_stencil",), "j_rough_gem") < 0

    def test_stencil_сильного_джокера_всё_равно_берёт(self) -> None:
        # Контроль: исключение — про **слабых** кандидатов, а не про само
        # присутствие Stencil.
        assert self._прирост(("j_stencil",), "j_joker") > 0

    @pytest.mark.parametrize("доска", _ДОСКИ_БЕЗ_СЧЁТА_ДЖОКЕРОВ)
    def test_бездействующий_джокер_ровно_ноль(self, доска: tuple[str, ...]) -> None:
        # Не «около нуля»: обе стороны разности идентичны, и любое отличие
        # означало бы, что контрфактум ловит что-то помимо джокера.
        # Доски со счётчиками джокеров сюда не входят — см. комментарий
        # у `_ДОСКИ_БЕЗ_СЧЁТА_ДЖОКЕРОВ`.
        assert self._прирост(доска, "j_rough_gem") == 0.0

    def test_бездействующий_джокер_не_даёт_вклада(self) -> None:
        state = self._state(("j_joker", "j_rough_gem"))
        вклады = joker_contributions(state, standard_deck(), 3)
        assert вклады[1] == 0.0

    @pytest.mark.parametrize("ключ", _ВСЕГДА_ПОЛЕЗНЫЕ)
    def test_точность_переживает_контрфактум(self, ключ: str) -> None:
        # A18 ломал и это: расчёт становился неточным «цена продажи
        # неизвестна». Точность — несущее свойство проекта, и то, что она
        # переживает добавление кандидата, до сих пор ничем не проверялось.
        state = self._state(("j_swashbuckler",))
        с_кандидатом = replace(
            state,
            hand=parse_cards("AH KH QH JH 9H"),
            jokers=(*state.jokers, JokerCard(key=ключ, label=ключ, sell_value=sell_value_of(5))),
        )
        assert advise(с_кандидатом, limit=1).best.outcome.exact


class TestОценкаРасходников:
    """Улучшение C2: расходники с полки доходят до совета — планета с
    посчитанным приростом, Таро с честной причиной вместо числа.

    До C2 `evaluate_shop` фильтровала витрину по `item.kind == "JOKER"`, и
    расходников для бота не существовало: за ротацию по 15 колодам полки
    держали 275 таких предложений, 271 из них по карману, куплено ноль."""

    ПЛАНЕТА: Final = ShopItem("c_pluto", "Pluto", "PLANET", 3)
    ТАРОТ: Final = ShopItem("c_magician", "The Magician", "TAROT", 3)

    def _state(self, **overrides: object) -> GameState:
        base: dict[str, object] = {
            "money": 25,
            "consumable_slots": 2,
            "shop": (self.ПЛАНЕТА, self.ТАРОТ),
        }
        return _shop_state(**{**base, **overrides})

    def _считать_приросты(self, monkeypatch: pytest.MonkeyPatch) -> list[list[HandType]]:
        """Подменить `planet_uplifts` считающей обёрткой — так «какие типы
        руки пересчитали» проверяется прямо, а не по времени; тот же приём,
        что у `TestКешВыборок._count_uplifts`."""
        считано: list[list[HandType]] = []
        настоящий = shop_module.planet_uplifts

        def counting(state: GameState, hand_types: object, deck: object) -> dict[HandType, float]:
            типы = list(hand_types)  # type: ignore[call-overload]
            считано.append(типы)
            return настоящий(state, типы, deck)  # type: ignore[arg-type]

        monkeypatch.setattr(shop_module, "planet_uplifts", counting)
        return считано

    def test_планета_получает_оценку_и_свой_тип_руки(self) -> None:
        clear_shop_cache()
        advice = evaluate_shop(self._state())
        assert advice is not None
        планета = next(o for o in advice.consumables if o.item.key == "c_pluto")
        assert планета.hand_type is HandType.HIGH_CARD
        assert планета.expected_uplift is not None
        assert планета.expected_uplift > 0

    def test_прирост_совпадает_с_пулом_для_того_же_типа(self) -> None:
        # Одна величина — один источник: и Celestial-пак, и планета с полки
        # обязаны получать ровно то же число, иначе два пути к одному
        # уровню руки со временем разъедутся.
        state = self._state()
        clear_shop_cache()
        advice = evaluate_shop(state)
        assert advice is not None
        планета = next(o for o in advice.consumables if o.item.key == "c_pluto")

        пул = shop_module.planet_uplift_pool(state, standard_deck())
        порядок = list(PLANET_HAND_TYPES.values())
        assert планета.expected_uplift == пул[порядок.index(HandType.HIGH_CARD)]

    def test_тарот_получает_none_с_причиной(self) -> None:
        clear_shop_cache()
        advice = evaluate_shop(self._state())
        assert advice is not None
        тарот = next(o for o in advice.consumables if o.item.key == "c_magician")
        assert тарот.expected_uplift is None
        assert тарот.hand_type is None
        assert "рука" in тарот.note  # молчания автопилот прочитать не может

    def test_неоценённые_идут_последними(self) -> None:
        clear_shop_cache()
        advice = evaluate_shop(_shop_state(money=25, shop=(self.ТАРОТ, self.ПЛАНЕТА)))
        assert advice is not None
        assert [o.item.key for o in advice.consumables] == ["c_pluto", "c_magician"]

    def test_полный_инвентарь_снимает_слот(self) -> None:
        clear_shop_cache()
        advice = evaluate_shop(self._state(consumables=(self.ПЛАНЕТА, self.ПЛАНЕТА)))
        assert advice is not None
        assert all(not o.has_slot for o in advice.consumables)

    def test_неизвестная_вместимость_не_блокирует(self) -> None:
        # Ручной ввод не присылает `limit`; отсутствие числа — не «слотов
        # нет», а «не знаем», и запрещать по нему нельзя.
        clear_shop_cache()
        advice = evaluate_shop(self._state(consumable_slots=None, consumables=(self.ПЛАНЕТА,) * 5))
        assert advice is not None
        assert all(o.has_slot for o in advice.consumables)

    def test_нехватка_денег_видна_в_оффере(self) -> None:
        clear_shop_cache()
        advice = evaluate_shop(self._state(money=1))
        assert advice is not None
        assert all(not o.affordable for o in advice.consumables)

    def test_витрина_без_расходников_даёт_пусто(self) -> None:
        clear_shop_cache()
        advice = evaluate_shop(self._state(shop=(ShopItem("j_joker", "Joker", "JOKER", 3),)))
        assert advice is not None
        assert advice.consumables == ()

    def test_повторный_опрос_берёт_прирост_из_кеша(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = self._state()
        clear_shop_cache()
        evaluate_shop(state)

        считано = self._считать_приросты(monkeypatch)
        evaluate_shop(state)
        assert считано == []

    def test_без_celestial_пака_считается_только_тип_с_полки(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Цена вопроса замерена: 807 мс на один тип руки против 5174 мс на
        # все двенадцать (тяжёлый стек из пяти джокеров). Считать пул, когда
        # нужен один тип, — это восемь лишних секунд на заход в магазин.
        считано = self._считать_приросты(monkeypatch)
        clear_shop_cache()
        evaluate_shop(self._state())
        assert считано == [[HandType.HIGH_CARD]]

    def test_с_celestial_паком_считается_весь_пул(self, monkeypatch: pytest.MonkeyPatch) -> None:
        считано = self._считать_приросты(monkeypatch)
        clear_shop_cache()
        evaluate_shop(
            self._state(
                shop_packs=(ShopItem("p_celestial_normal_1", "Celestial Pack", "BOOSTER", 4),)
            )
        )
        assert считано == [list(PLANET_HAND_TYPES.values())]


class TestКандидатНаРазмен:
    """Улучшение A22: слабейший невечный джокер выставлен на `ShopAdvice`
    отдельно, а не только приклеен к оценённым офферам — вентилю реролла
    порог размена нужен именно тогда, когда оценённых офферов нет вовсе."""

    def _state(self, ключи: tuple[str, ...], **overrides: object) -> GameState:
        base: dict[str, object] = {
            "joker_slots": len(ключи),
            "jokers": tuple(JokerCard(key=k, label=k, sell_value=2) for k in ключи),
            "shop": (ShopItem("j_совсем_новый", "???", "JOKER", 5),),
            "money": 25,
        }
        return _shop_state(**{**base, **overrides})

    def test_при_полных_слотах_кандидат_есть_без_оценённых_офферов(self) -> None:
        clear_shop_cache()
        advice = evaluate_shop(self._state(("j_joker", "j_droll")))
        assert advice is not None
        # Витрина — один неизвестный движку джокер: оценённых офферов нет.
        assert all(offer.expected_uplift is None for offer in advice.jokers)
        assert advice.replace_candidate is not None
        assert advice.replace_candidate.label in {"j_joker", "j_droll"}

    def test_кандидат_это_слабейший(self) -> None:
        clear_shop_cache()
        advice = evaluate_shop(self._state(("j_joker", "j_rough_gem")))
        assert advice is not None and advice.replace_candidate is not None
        слабейший = min(advice.held, key=lambda entry: entry.contribution)
        assert advice.replace_candidate.index == слабейший.index
        assert advice.replace_candidate.contribution == слабейший.contribution

    def test_при_свободном_слоте_кандидата_нет(self) -> None:
        clear_shop_cache()
        advice = evaluate_shop(self._state(("j_joker",), joker_slots=5))
        assert advice is not None
        assert advice.replace_candidate is None

    def test_вечных_джокеров_продать_нельзя(self) -> None:
        clear_shop_cache()
        state = _shop_state(
            joker_slots=2,
            jokers=(
                JokerCard(key="j_joker", label="Joker", sell_value=2, eternal=True),
                JokerCard(key="j_droll", label="Droll", sell_value=2, eternal=True),
            ),
            shop=(ShopItem("j_совсем_новый", "???", "JOKER", 5),),
            money=25,
        )
        advice = evaluate_shop(state)
        assert advice is not None
        assert advice.replace_candidate is None
