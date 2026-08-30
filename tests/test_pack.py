"""Тесты оценки выбора карты при вскрытии пака (`balatro_bot/solver/pack.py`).

Оцениваемые случаи — Celestial/Planet Pack (детерминированный level-up) и
Buffoon Pack (джокеры видны, тот же контрфактум, что джокер в витрине).
Arcana/Spectral/Standard этот модуль сознательно не оценивает."""

from __future__ import annotations

from balatro_bot.core.cards import parse_cards
from balatro_bot.core.hands import HandType
from balatro_bot.core.state import GameState, ShopItem
from balatro_bot.solver.pack import PLANET_HAND_TYPES, evaluate_pack

#: Рука без флеша, стрита и троек — единственная собираемая рука сильнее
#: хай-карты это пара тузов, детерминированно и однозначно.
_ПАРА_ТУЗОВ = parse_cards("AH AS 2C 4D 6S 9H TC KD")


class TestТаблицаПланет:
    def test_все_12_типов_руки_покрыты_ровно_один_раз(self) -> None:
        assert len(PLANET_HAND_TYPES) == 12
        assert set(PLANET_HAND_TYPES.values()) == set(HandType)


class TestEvaluatePack:
    def test_не_planet_pack_возвращает_пусто(self) -> None:
        state = GameState(
            phase="SHOP",
            full_deck=_ПАРА_ТУЗОВ,
            pack=(ShopItem("c_mercury", "Mercury", "PLANET", 0),),
        )
        assert evaluate_pack(state) == ()

    def test_пустой_пак_возвращает_пусто(self) -> None:
        state = GameState(phase="PLANET_PACK", full_deck=_ПАРА_ТУЗОВ)
        assert evaluate_pack(state) == ()

    def test_неопознанная_карта_пропускается(self) -> None:
        state = GameState(
            phase="PLANET_PACK",
            full_deck=_ПАРА_ТУЗОВ,
            pack=(ShopItem("c_совсем_новый", "???", "PLANET", 0),),
        )
        assert evaluate_pack(state) == ()

    def test_подходящий_тип_руки_даёт_положительный_прирост(self) -> None:
        state = GameState(
            phase="PLANET_PACK",
            full_deck=_ПАРА_ТУЗОВ,
            pack=(
                ShopItem("c_mercury", "Mercury", "PLANET", 0),
                ShopItem("c_jupiter", "Jupiter", "PLANET", 0),
            ),
        )
        offers = evaluate_pack(state, samples=1)
        assert len(offers) == 2
        by_type = {offer.detail: offer for offer in offers}
        pair_uplift = by_type[HandType.PAIR.value].expected_uplift
        assert pair_uplift is not None
        assert pair_uplift > 0
        # Флеш в этой руке не собрать никогда — прокачка ничего не меняет.
        assert by_type[HandType.FLUSH.value].expected_uplift == 0.0

    def test_сортировка_по_убыванию_прироста(self) -> None:
        state = GameState(
            phase="PLANET_PACK",
            full_deck=_ПАРА_ТУЗОВ,
            pack=(
                ShopItem("c_jupiter", "Jupiter", "PLANET", 0),
                ShopItem("c_mercury", "Mercury", "PLANET", 0),
            ),
        )
        offers = evaluate_pack(state, samples=1)
        assert offers[0].detail == HandType.PAIR.value

    def test_маленькая_колода_честно_не_оценивает(self) -> None:
        state = GameState(
            phase="PLANET_PACK",
            full_deck=parse_cards("AH AS 2C"),
            pack=(ShopItem("c_mercury", "Mercury", "PLANET", 0),),
        )
        offers = evaluate_pack(state, samples=1)
        assert offers[0].expected_uplift is None

    def test_без_full_deck_использует_стандартную_колоду(self) -> None:
        state = GameState(
            phase="PLANET_PACK",
            pack=(ShopItem("c_mercury", "Mercury", "PLANET", 0),),
        )
        offers = evaluate_pack(state, samples=1)
        assert offers[0].exact_deck is False
        assert offers[0].expected_uplift is not None


class TestBuffoonPack:
    def test_джокеры_ранжируются_по_приросту(self) -> None:
        # j_joker (+4 множ. безусловно) должен обойти j_gros_michel? Нет —
        # берём заведомо разные: j_joker vs j_abstract (+3 множ. за джокера,
        # тут джокеров нет → +3). j_joker (+4) выше.
        state = GameState(
            phase="BUFFOON_PACK",
            full_deck=_ПАРА_ТУЗОВ,
            pack=(
                ShopItem("j_abstract", "Abstract Joker", "JOKER", 0),
                ShopItem("j_joker", "Joker", "JOKER", 0),
            ),
        )
        offers = evaluate_pack(state, samples=2)
        assert len(offers) == 2
        assert offers[0].item.key == "j_joker"
        assert offers[0].kind == "joker"
        assert offers[0].detail == "Joker"
        assert offers[0].expected_uplift is not None
        assert offers[0].expected_uplift > 0

    def test_нереализованный_джокер_не_оценивается(self) -> None:
        state = GameState(
            phase="BUFFOON_PACK",
            full_deck=_ПАРА_ТУЗОВ,
            pack=(ShopItem("j_совсем_новый", "???", "JOKER", 0),),
        )
        offers = evaluate_pack(state, samples=2)
        assert len(offers) == 1
        assert offers[0].expected_uplift is None

    def test_не_фаза_пака_не_трогает_джокеров(self) -> None:
        state = GameState(
            phase="SHOP",
            full_deck=_ПАРА_ТУЗОВ,
            pack=(ShopItem("j_joker", "Joker", "JOKER", 0),),
        )
        assert evaluate_pack(state) == ()


class TestДиспетчерПоСодержимому:
    """Тип пака определяется по картам внутри, не по имени фазы: Steamodded
    шлёт одну общую `SMODS_BOOSTER_OPENED` для всех типов."""

    def test_smods_фаза_с_планетами_оценивается_как_celestial(self) -> None:
        state = GameState(
            phase="SMODS_BOOSTER_OPENED",
            full_deck=_ПАРА_ТУЗОВ,
            pack=(ShopItem("c_mercury", "Mercury", "PLANET", 0),),
        )
        offers = evaluate_pack(state, samples=1)
        assert len(offers) == 1
        assert offers[0].kind == "planet"

    def test_smods_фаза_с_джокерами_оценивается_как_buffoon(self) -> None:
        state = GameState(
            phase="SMODS_BOOSTER_OPENED",
            full_deck=_ПАРА_ТУЗОВ,
            pack=(ShopItem("j_joker", "Joker", "JOKER", 0),),
        )
        offers = evaluate_pack(state, samples=1)
        assert len(offers) == 1
        assert offers[0].kind == "joker"

    def test_smods_фаза_с_таро_возвращает_пусто(self) -> None:
        state = GameState(
            phase="SMODS_BOOSTER_OPENED",
            full_deck=_ПАРА_ТУЗОВ,
            pack=(ShopItem("c_fool", "The Fool", "TAROT", 0),),
        )
        assert evaluate_pack(state) == ()

    def test_планеты_имеют_приоритет_над_джокерами_в_смешанном_паке(self) -> None:
        # Вырожденный случай (в игре не бывает), но диспетчер должен быть
        # детерминирован: планеты проверяются первыми.
        state = GameState(
            phase="SMODS_BOOSTER_OPENED",
            full_deck=_ПАРА_ТУЗОВ,
            pack=(
                ShopItem("j_joker", "Joker", "JOKER", 0),
                ShopItem("c_mercury", "Mercury", "PLANET", 0),
            ),
        )
        offers = evaluate_pack(state, samples=1)
        assert all(offer.kind == "planet" for offer in offers)
