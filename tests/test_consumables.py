"""Тесты использования консумаблей перед розыгрышем
(`balatro_bot/solver/consumables.py`) — Фаза 9.4: Planet-кусок и первый срез
Tarot (улучшение C1, карты вида «улучшить выбранные карты руки»)."""

from __future__ import annotations

from dataclasses import replace

from balatro_bot.adapters.manual import build_state
from balatro_bot.core.cards import Enhancement
from balatro_bot.core.hands import HandType
from balatro_bot.core.state import GameState, JokerCard, ShopItem
from balatro_bot.solver.consumables import (
    TAROT_ENHANCEMENTS,
    evaluate_planet_consumables,
    evaluate_tarot_consumables,
)

#: Та же детерминированная рука без флеша/стрита/троек, что в
#: `tests/test_pack.py` — единственная собираемая рука сильнее хай-карты
#: здесь пара тузов.
_ПАРА_ТУЗОВ = "AH AS 2C 4D 6S 9H TC KD"


def _consumable_state(hand: str = _ПАРА_ТУЗОВ, **overrides: object) -> GameState:
    state = build_state(hand)
    return replace(state, phase="SELECTING_HAND", **overrides)  # type: ignore[arg-type]


class TestEvaluatePlanetConsumables:
    def test_не_selecting_hand_возвращает_пусто(self) -> None:
        state = _consumable_state(consumables=(ShopItem("c_mercury", "Mercury", "PLANET", 0),))
        state = replace(state, phase="SHOP")
        assert evaluate_planet_consumables(state) == ()

    def test_без_руки_возвращает_пусто(self) -> None:
        state = _consumable_state(
            hand="", consumables=(ShopItem("c_mercury", "Mercury", "PLANET", 0),)
        )
        assert evaluate_planet_consumables(state) == ()

    def test_подходящая_планета_даёт_положительный_прирост(self) -> None:
        state = _consumable_state(consumables=(ShopItem("c_mercury", "Mercury", "PLANET", 0),))
        offers = evaluate_planet_consumables(state)
        assert len(offers) == 1
        assert offers[0].hand_type is HandType.PAIR
        assert offers[0].expected_uplift > 0

    def test_недостижимая_планета_даёт_нулевой_прирост(self) -> None:
        # Флеш в этой руке не собрать никогда.
        state = _consumable_state(consumables=(ShopItem("c_jupiter", "Jupiter", "PLANET", 0),))
        offers = evaluate_planet_consumables(state)
        assert offers[0].expected_uplift == 0.0

    def test_неопознанная_карта_пропускается(self) -> None:
        state = _consumable_state(consumables=(ShopItem("c_совсем_новый", "???", "TAROT", 0),))
        assert evaluate_planet_consumables(state) == ()

    def test_сортировка_по_убыванию_прироста(self) -> None:
        state = _consumable_state(
            consumables=(
                ShopItem("c_jupiter", "Jupiter", "PLANET", 0),
                ShopItem("c_mercury", "Mercury", "PLANET", 0),
            )
        )
        offers = evaluate_planet_consumables(state)
        assert offers[0].hand_type is HandType.PAIR

    def test_observatory_добавляет_примечание(self) -> None:
        state = _consumable_state(
            consumables=(ShopItem("c_mercury", "Mercury", "PLANET", 0),),
            used_vouchers=frozenset({"v_observatory"}),
        )
        offers = evaluate_planet_consumables(state)
        assert "Observatory" in offers[0].note

    def test_без_observatory_нет_примечания(self) -> None:
        state = _consumable_state(consumables=(ShopItem("c_mercury", "Mercury", "PLANET", 0),))
        offers = evaluate_planet_consumables(state)
        assert offers[0].note == ""


#: Флеш червей: у него есть и явные цели для улучшений, и карты, остающиеся
#: в руке (для `Steel`, который считается при удержании, а не при розыгрыше).
_ФЛЕШ = "AH KH QH JH 9H 7C 7D 2S"


def _таро(*ключи: str) -> tuple[ShopItem, ...]:
    return tuple(ShopItem(key, key, "TAROT", 0) for key in ключи)


class TestТаблицаТаротов:
    """Таблица выписана из `game.lua`'s `P_CENTERS` (`config.mod_conv` и
    `config.max_highlighted`). Одна неверная строка — молча неправильный
    счёт, поэтому покрытие проверяется тестом, как у `PLANET_HAND_TYPES`."""

    def test_ровно_восемь_карт_первого_среза(self) -> None:
        assert len(TAROT_ENHANCEMENTS) == 8

    def test_улучшения_не_повторяются(self) -> None:
        улучшения = [enhancement for enhancement, _ in TAROT_ENHANCEMENTS.values()]
        assert len(set(улучшения)) == len(улучшения)

    def test_двухцелевые_ровно_три(self) -> None:
        # Magician/Empress/Hierophant — `max_highlighted = 2`, остальные 1.
        двухцелевые = {key for key, (_, n) in TAROT_ENHANCEMENTS.items() if n == 2}
        assert двухцелевые == {"c_magician", "c_empress", "c_heirophant"}

    def test_все_целевые_числа_осмысленны(self) -> None:
        assert all(n in (1, 2) for _, n in TAROT_ENHANCEMENTS.values())


class TestОценкаТаротов:
    def test_не_selecting_hand_возвращает_пусто(self) -> None:
        state = _consumable_state(_ФЛЕШ, consumables=_таро("c_empress"))
        assert evaluate_tarot_consumables(replace(state, phase="SHOP")) == ()

    def test_без_руки_возвращает_пусто(self) -> None:
        state = _consumable_state(hand="", consumables=_таро("c_empress"))
        assert evaluate_tarot_consumables(state) == ()

    def test_empress_улучшает_две_карты_розыгрыша(self) -> None:
        state = _consumable_state(_ФЛЕШ, consumables=_таро("c_empress"))
        (offer,) = evaluate_tarot_consumables(state)
        assert offer.enhancement is Enhancement.MULT
        assert offer.value_unit == "score"
        assert offer.expected_uplift is not None and offer.expected_uplift > 0
        # `max_highlighted = 2`, и на флеше обе цели работают.
        assert len(offer.targets) == 2

    def test_одноцелевой_тарот_берёт_одну_карту(self) -> None:
        state = _consumable_state(_ФЛЕШ, consumables=_таро("c_justice"))
        (offer,) = evaluate_tarot_consumables(state)
        assert len(offer.targets) <= 1

    def test_devil_честный_ноль_а_не_пробел(self) -> None:
        # Gold платит деньги за карту, оставшуюся в руке, и на счёт
        # розыгрыша не влияет — ноль тут посчитан, а не пропущен.
        state = _consumable_state(_ФЛЕШ, consumables=_таро("c_devil"))
        (offer,) = evaluate_tarot_consumables(state)
        assert offer.expected_uplift == 0.0
        assert offer.targets == ()
        assert "не очки" in offer.note

    def test_прирост_никогда_не_отрицателен(self) -> None:
        # `The Tower` стирает ранг и масть и вполне может испортить флеш —
        # тогда честный ответ «применять незачем», а не отрицательное число.
        state = _consumable_state(_ФЛЕШ, consumables=_таро("c_tower"))
        (offer,) = evaluate_tarot_consumables(state)
        assert offer.expected_uplift is not None and offer.expected_uplift >= 0

    def test_hermit_считает_деньги_с_потолком(self) -> None:
        state = _consumable_state(_ФЛЕШ, consumables=_таро("c_hermit"), money=15)
        (offer,) = evaluate_tarot_consumables(state)
        assert offer.value_unit == "dollars"
        assert offer.expected_uplift == 15.0
        # Потолок $20 из `game.lua` (`config.extra`).
        rich = _consumable_state(_ФЛЕШ, consumables=_таро("c_hermit"), money=100)
        assert evaluate_tarot_consumables(rich)[0].expected_uplift == 20.0

    def test_temperance_суммирует_цены_продажи_джокеров(self) -> None:
        state = _consumable_state(
            _ФЛЕШ,
            consumables=_таро("c_temperance"),
            jokers=(JokerCard(key="j_joker", sell_value=4), JokerCard(key="j_droll", sell_value=6)),
        )
        (offer,) = evaluate_tarot_consumables(state)
        assert offer.value_unit == "dollars"
        assert offer.expected_uplift == 10.0

    def test_отложенный_тарот_честно_не_оценён(self) -> None:
        state = _consumable_state(_ФЛЕШ, consumables=_таро("c_death"))
        (offer,) = evaluate_tarot_consumables(state)
        assert offer.expected_uplift is None
        assert offer.value_unit is None
        assert "второй срез" in offer.note

    def test_случайный_тарот_честно_не_оценён(self) -> None:
        state = _consumable_state(_ФЛЕШ, consumables=_таро("c_judgement"))
        (offer,) = evaluate_tarot_consumables(state)
        assert offer.expected_uplift is None
        assert "RNG" in offer.note

    def test_планеты_не_попадают_в_список_таротов(self) -> None:
        state = _consumable_state(_ФЛЕШ, consumables=_таро("c_mercury"))
        assert evaluate_tarot_consumables(state) == ()

    def test_оценённые_в_очках_идут_первыми(self) -> None:
        state = _consumable_state(
            _ФЛЕШ, consumables=_таро("c_judgement", "c_hermit", "c_empress"), money=10
        )
        offers = evaluate_tarot_consumables(state)
        assert offers[0].item.key == "c_empress"
        assert offers[-1].expected_uplift is None
