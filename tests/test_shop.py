"""Тесты совета по магазину (`balatro_bot/solver/shop.py`).

Проверяется второй кусок Фазы 8 плана («Стратегия рана»): контрфактум для
джокеров (реальный прирост счёта по представительным рукам) и честный текст
для ваучеров/паков, без выдуманной оценки того, что не с чем сравнить.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from balatro_bot.adapters.manual import build_state
from balatro_bot.core.cards import parse_cards, standard_deck
from balatro_bot.core.jokers import implemented_keys
from balatro_bot.core.scoring import score_play
from balatro_bot.core.state import GameState, JokerCard, ShopItem
from balatro_bot.solver import shop as shop_module
from balatro_bot.solver.shop import (
    _MONEY_SENSITIVE_JOKER_KEYS,
    SAMPLE_HANDS,
    clear_shop_cache,
    evaluate_shop,
    joker_contributions,
)


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

        def counting(state: GameState, joker: JokerCard, deck: object, samples: int) -> float:
            seen.append(joker.key)
            return real(state, joker, deck, samples)  # type: ignore[arg-type]

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
