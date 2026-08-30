"""Тесты решения автопилота (`balatro_bot/autopilot.py`).

Розыгрыш/сброс (`SELECTING_HAND`, Фаза 9 п. 9.1) уже полностью посчитан
`solver.actions.rank_actions` — здесь только перевод лучшего варианта в
индексы для RPC мода. Скип блайнда (`BLIND_SELECT`, п. 9.2) — первый
реальный вердикт поверх намеренно неоднозначного `solver.skip.evaluate_skip`:
`decide_skip` проверяется отдельно от самого расчёта чисел (те тесты — в
`test_skip.py`)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from balatro_bot.adapters.manual import build_state
from balatro_bot.adapters.mod_bridge import ModBridge
from balatro_bot.autopilot import (
    Action,
    _indices_of,
    decide_action,
    decide_skip,
    describe_action,
    dispatch_action,
)
from balatro_bot.core.cards import Card, Rank, Suit, parse_cards
from balatro_bot.core.state import BlindInfo, GameState, JokerCard, ShopItem
from balatro_bot.solver.actions import rank_actions
from balatro_bot.solver.skip import evaluate_skip
from tests.fake_mod import FakeMod

#: Та же детерминированная колода без флеша/стрита/троек, что в
#: `tests/test_pack.py` — единственная собираемая рука сильнее хай-карты
#: здесь пара тузов.
_ПАРА_ТУЗОВ = parse_cards("AH AS 2C 4D 6S 9H TC KD")


class TestIndicesOf:
    def test_находит_индексы_по_порядку(self) -> None:
        hand = parse_cards("AH KH QH JH 9H")
        cards = parse_cards("QH AH")
        assert _indices_of(hand, cards) == (2, 0)

    def test_дубли_по_значению_получают_разные_индексы(self) -> None:
        карта = Card(Rank.ACE, Suit.HEARTS)
        hand = (карта, карта, parse_cards("KH")[0])
        assert _indices_of(hand, (карта, карта)) == (0, 1)

    def test_карта_не_из_руки_бросает_ошибку(self) -> None:
        hand = parse_cards("AH KH")
        with pytest.raises(ValueError, match="не найдена в руке"):
            _indices_of(hand, parse_cards("2S"))


class TestDecideAction:
    def test_неизвестная_фаза_ничего_не_решает(self) -> None:
        state = build_state("AH KH QH JH 9H")
        state = replace(state, phase="HAND_PLAYED")
        assert decide_action(state) is None

    def test_неоценимый_пак_скипается_а_не_затыкается(self) -> None:
        # На SMODS_BOOSTER_OPENED тип пака определяется по содержимому.
        # Tarot-карты (c_fool и т.п.) оценить нечем — skip_pack, а не None.
        state = build_state("AH KH QH JH 9H")
        state = replace(
            state,
            phase="SMODS_BOOSTER_OPENED",
            pack=(ShopItem("c_fool", "The Fool", "TAROT", 0),),
        )
        assert decide_action(state) == Action(kind="skip_pack")

    def test_пустой_пак_скипается(self) -> None:
        state = build_state("AH KH QH JH 9H")
        state = replace(state, phase="SMODS_BOOSTER_OPENED", pack=())
        assert decide_action(state) == Action(kind="skip_pack")

    def test_пустая_рука_ничего_не_решает(self) -> None:
        state = build_state("AH KH QH JH 9H")
        state = replace(state, phase="SELECTING_HAND", hand=())
        assert decide_action(state) is None

    def test_флеш_дают_розыгрыш_с_верными_индексами(self) -> None:
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        state = replace(state, phase="SELECTING_HAND")
        action = decide_action(state)
        assert isinstance(action, Action)
        assert action.kind == "play"
        assert set(action.cards) == set(parse_cards("AH KH QH JH 9H"))
        # индексы обязаны указывать на те же карты в исходной руке
        assert tuple(state.hand[i] for i in action.indices) == action.cards

    def test_без_сбросов_и_без_явного_блайнда_всё_равно_решает_розыгрыш(self) -> None:
        state = build_state("AH KH QH JH 9H 7C 7D 2S", discards_left=0)
        state = replace(state, phase="SELECTING_HAND")
        action = decide_action(state)
        assert action is not None
        assert action.kind == "play"

    def test_include_discards_false_никогда_не_сбрасывает(self) -> None:
        # Рука явно тянется к флешу — лучший вариант обычно сброс 2C.
        # Блайнда нет, поэтому «гарантированная победа» не срабатывает.
        state = build_state("AH KH QH 9H 2C", discards_left=1)
        state = replace(state, phase="SELECTING_HAND")

        по_умолчанию = decide_action(state)
        assert по_умолчанию is not None
        assert по_умолчанию.kind == "discard"

        без_сбросов = decide_action(state, include_discards=False)
        assert без_сбросов is not None
        assert без_сбросов.kind == "play"

    def test_гарантированная_победа_бьёт_сброс(self) -> None:
        # Пара тузов даёт min 64 и закрывает блайнд 60. `rank_actions` при
        # этом ставит наверх сброс к триплу/каре тузов (оптимистичная оценка
        # сброса). Автопилот обязан сыграть верную пару, а не гадать.
        state = build_state("AH AS KH QH 2C", discards_left=1, blind=60)
        state = replace(state, phase="SELECTING_HAND")

        assert rank_actions(state, top=1)[0].kind == "discard"  # что было бы без поправки
        action = decide_action(state)
        assert action is not None
        assert action.kind == "play"

    def test_нет_гарантии_можно_и_сбросить(self) -> None:
        # Блайнд велик — ни один ход не закрывает его наверняка, поэтому
        # решение снова отдаётся общему списку (тут — сброс).
        state = build_state("AH AS KH QH 2C", discards_left=1, blind=100_000)
        state = replace(state, phase="SELECTING_HAND")
        action = decide_action(state)
        assert action is not None
        assert action.kind == "discard"


class TestDecideActionИспользуетКонсумабль:
    """Planet-консумабль перед розыгрышем (9.4, первый кусок) — решается
    раньше play/discard, см. модульный докстринг `autopilot.py`."""

    def test_planet_консумабль_используется_раньше_розыгрыша(self) -> None:
        state = build_state(
            "AH KH QH JH 9H 7C 7D 2S",
            hand_levels=None,
        )
        state = replace(
            state,
            phase="SELECTING_HAND",
            consumables=(ShopItem("c_mercury", "Mercury", "PLANET", 0),),
        )
        action = decide_action(state)
        assert action == Action(kind="use", item_index=0, label="Mercury")

    def test_без_planet_консумаблей_решает_розыгрыш_как_раньше(self) -> None:
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        state = replace(state, phase="SELECTING_HAND")
        action = decide_action(state)
        assert action is not None
        assert action.kind == "play"

    def test_несколько_консумаблей_выбирает_с_максимальным_приростом(self) -> None:
        state = build_state("AH AS 2C 4D 6S 9H TC KD")
        state = replace(
            state,
            phase="SELECTING_HAND",
            consumables=(
                ShopItem("c_jupiter", "Jupiter", "PLANET", 0),
                ShopItem("c_mercury", "Mercury", "PLANET", 0),
            ),
        )
        action = decide_action(state)
        assert action == Action(kind="use", item_index=1, label="Mercury")


def _blind(
    kind: str, status: str, score: int, tag_name: str = "", tag_effect: str = ""
) -> BlindInfo:
    return BlindInfo(
        kind=kind,
        name=f"{kind.title()} Blind",
        effect="",
        required_score=score,
        status=status,
        tag_name=tag_name,
        tag_effect=tag_effect,
    )


class TestDecideSkip:
    """Политика предельно консервативна: скип только когда `tag_dollars`
    точно известен и строго больше `play_reward_min` — см. модульный
    докстринг `autopilot.py`."""

    def test_investment_tag_на_big_окупается_и_даёт_скип(self) -> None:
        # Investment Tag = $25 гарантированно, play_reward_min у BIG = $4.
        state = GameState(
            phase="BLIND_SELECT",
            blinds={
                "big": _blind("BIG", "SELECT", 450, "Investment Tag", "..."),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert decide_skip(advice) is True

    def test_economy_tag_без_денег_не_окупается(self) -> None:
        # Economy Tag = min(40, money) = $0 при пустом кошельке, play_reward_min = $3.
        state = GameState(
            phase="BLIND_SELECT",
            money=0,
            blinds={
                "small": _blind("SMALL", "SELECT", 300, "Economy Tag", "..."),
                "big": _blind("BIG", "UPCOMING", 450),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert decide_skip(advice) is False

    def test_economy_tag_с_большими_деньгами_окупается(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            money=100,
            blinds={
                "small": _blind("SMALL", "SELECT", 300, "Economy Tag", "..."),
                "big": _blind("BIG", "UPCOMING", 450),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert decide_skip(advice) is True

    def test_структурный_тег_никогда_не_вызывает_скип(self) -> None:
        # Rare Tag не переводится в доллары — tag_dollars всегда None.
        state = GameState(
            phase="BLIND_SELECT",
            blinds={
                "big": _blind("BIG", "SELECT", 450, "Rare Tag", "..."),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert advice.tag_dollars is None
        assert decide_skip(advice) is False


class TestDecideActionНаВыбореБлайнда:
    def test_скип_когда_доказан_числом(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            blinds={
                "big": _blind("BIG", "SELECT", 450, "Investment Tag", "..."),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        action = decide_action(state)
        assert action == Action(kind="skip")

    def test_играть_когда_скип_не_доказан(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            blinds={
                "big": _blind("BIG", "SELECT", 450, "Rare Tag", "..."),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        action = decide_action(state)
        assert action == Action(kind="select")

    def test_boss_нельзя_скипнуть_решение_select(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            blinds={"boss": _blind("BOSS", "SELECT", 600)},
        )
        action = decide_action(state)
        assert action == Action(kind="select")


class TestDecideActionНаRoundEval:
    def test_всегда_cash_out(self) -> None:
        # Решать нечего — без явного вызова автопилот застрял бы здесь
        # навсегда (модульный докстринг, раздел про ROUND_EVAL).
        assert decide_action(GameState(phase="ROUND_EVAL")) == Action(kind="cash_out")


class TestDecideActionВМагазине:
    """Политика: купить лучшего по приросту джокера, если он известен движку,
    по карману и есть слот, и прирост строго положителен — иначе уйти
    (`next_round`). См. модульный докстринг про то, почему `interest_lost`
    не участвует в самом решении."""

    def test_покупает_известного_доступного_джокера(self) -> None:
        state = GameState(
            phase="SHOP",
            money=10,
            joker_slots=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3, "+4 Mult"),),
        )
        action = decide_action(state)
        assert action is not None
        assert action.kind == "buy"
        assert action.item_index == 0
        assert action.label == "Joker"

    def test_a2_не_покупает_джокера_на_фоне_огромного_требования(self) -> None:
        # Порог A2: прирост должен быть не ниже 3% требования блайнда.
        # Против блайнда на 100000 очков прирост "+4 Mult" — доли процента.
        state = GameState(
            phase="SHOP",
            money=10,
            joker_slots=5,
            blinds={"small": _blind("SMALL", "UPCOMING", 100_000)},
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3, "+4 Mult"),),
        )
        assert decide_action(state) == Action(kind="next_round")

    def test_a2_покупает_того_же_джокера_при_малом_требовании(self) -> None:
        # То же самое, но требование маленькое — 3% от 300 = 9 очков,
        # "+4 Mult" на любой руке это перекрывает.
        state = GameState(
            phase="SHOP",
            money=10,
            joker_slots=5,
            blinds={"small": _blind("SMALL", "UPCOMING", 300)},
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3, "+4 Mult"),),
        )
        action = decide_action(state)
        assert action is not None
        assert action.kind == "buy"

    def test_пустой_магазин_уходит(self) -> None:
        state = GameState(phase="SHOP", money=10, joker_slots=5)
        assert decide_action(state) == Action(kind="next_round")

    def test_не_хватает_денег_уходит(self) -> None:
        state = GameState(
            phase="SHOP",
            money=1,
            joker_slots=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 99, "+4 Mult"),),
        )
        assert decide_action(state) == Action(kind="next_round")

    def test_нет_слота_уходит(self) -> None:
        existing = tuple(JokerCard(key="j_joker") for _ in range(3))
        state = GameState(
            phase="SHOP",
            money=10,
            jokers=existing,
            joker_slots=3,
            shop=(ShopItem("j_greedy_joker", "Greedy Joker", "JOKER", 4),),
        )
        assert decide_action(state) == Action(kind="next_round")

    def test_неизвестный_джокер_не_покупается(self) -> None:
        state = GameState(
            phase="SHOP",
            money=10,
            joker_slots=5,
            shop=(ShopItem("j_совсем_новый", "???", "JOKER", 5),),
        )
        assert decide_action(state) == Action(kind="next_round")

    def test_ваучеры_и_arcana_паки_не_покупаются(self) -> None:
        # Ваучеры и не-Buffoon паки не получают expected_uplift —
        # decide_action не выдумывает вердикт.
        state = GameState(
            phase="SHOP",
            money=100,
            shop_vouchers=(ShopItem("v_overstock", "Overstock", "VOUCHER", 10),),
            shop_packs=(ShopItem("p_arcana_normal_1", "Arcana Pack", "BOOSTER", 4),),
        )
        assert decide_action(state) == Action(kind="next_round")

    def test_покупает_buffoon_пак_когда_джокеров_брать_нечего(self) -> None:
        state = GameState(
            phase="SHOP",
            money=20,
            joker_slots=5,
            full_deck=_ПАРА_ТУЗОВ,
            shop_packs=(ShopItem("p_buffoon_normal_1", "Buffoon Pack", "BOOSTER", 4),),
        )
        action = decide_action(state)
        assert action == Action(kind="buy_pack", item_index=0, label="Buffoon Pack")

    def test_покупает_celestial_пак(self) -> None:
        # Планеты слот не занимают; подъём уровня руки не может навредить —
        # оценка положительна, значит берём (A3).
        state = GameState(
            phase="SHOP",
            money=20,
            joker_slots=5,
            full_deck=_ПАРА_ТУЗОВ,
            shop_packs=(ShopItem("p_celestial_normal_1", "Celestial Pack", "BOOSTER", 4),),
        )
        action = decide_action(state)
        assert action == Action(kind="buy_pack", item_index=0, label="Celestial Pack")

    def test_buffoon_пак_без_слота_не_покупается(self) -> None:
        state = GameState(
            phase="SHOP",
            money=20,
            jokers=tuple(JokerCard(key="j_joker") for _ in range(5)),
            joker_slots=5,
            full_deck=_ПАРА_ТУЗОВ,
            shop_packs=(ShopItem("p_buffoon_normal_1", "Buffoon Pack", "BOOSTER", 4),),
        )
        assert decide_action(state) == Action(kind="next_round")

    def test_продаёт_мёртвый_груз_под_лучший_оффер(self) -> None:
        # Слоты полны (2/2), один джокер отключён (вклад ровно 0), в витрине
        # рабочий j_joker с положительным приростом — продаём отключённого.
        state = GameState(
            phase="SHOP",
            money=10,
            jokers=(JokerCard(key="j_joker"), JokerCard(key="j_joker", debuffed=True)),
            joker_slots=2,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        action = decide_action(state)
        assert action is not None
        assert action.kind == "sell"
        assert action.item_index == 1

    def test_не_разменивает_рабочих_джокеров_на_равный_оффер(self) -> None:
        # Оба джокера рабочие, оффер — ещё один такой же (+4 Mult), прирост
        # примерно равен вкладу каждого, не вдвое больше — размена нет.
        state = GameState(
            phase="SHOP",
            money=10,
            jokers=(JokerCard(key="j_joker"), JokerCard(key="j_joker")),
            joker_slots=2,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        assert decide_action(state) == Action(kind="next_round")

    def test_не_продаёт_если_денег_не_хватит_даже_с_продажей(self) -> None:
        state = GameState(
            phase="SHOP",
            money=1,
            jokers=(JokerCard(key="j_joker"), JokerCard(key="j_joker", debuffed=True)),
            joker_slots=2,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 9),),  # 1 + 0 возврата < 9
        )
        assert decide_action(state) == Action(kind="next_round")

    def test_возврат_за_продажу_учитывается_в_бюджете(self) -> None:
        # Денег мало, но продажа отключённого вернёт $3 — на оффер за $3 хватит.
        state = GameState(
            phase="SHOP",
            money=1,
            jokers=(
                JokerCard(key="j_joker"),
                JokerCard(key="j_joker", debuffed=True, sell_value=3),
            ),
            joker_slots=2,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
        )
        action = decide_action(state)
        assert action is not None
        assert action.kind == "sell"
        assert action.item_index == 1


class TestDecideActionНаВскрытииПака:
    """Тип пака — по содержимому `state.pack`, не по имени фазы (Steamodded
    шлёт одну общую `SMODS_BOOSTER_OPENED`). Planet: всегда берём лучшую карту
    (level-up не ухудшает счёт). Buffoon: берём лучшего джокера, но лишь при
    строго положительном приросте. Иначе `skip_pack`."""

    _OPENED = "SMODS_BOOSTER_OPENED"

    def test_planet_берёт_карту_с_максимальным_приростом(self) -> None:
        state = GameState(
            phase=self._OPENED,
            full_deck=_ПАРА_ТУЗОВ,
            pack=(
                ShopItem("c_jupiter", "Jupiter", "PLANET", 0),
                ShopItem("c_mercury", "Mercury", "PLANET", 0),
            ),
        )
        action = decide_action(state)
        assert action == Action(kind="pack", item_index=1, label="Mercury")

    def test_planet_неопознанные_карты_приводят_к_скипу_пака(self) -> None:
        state = GameState(
            phase=self._OPENED,
            full_deck=_ПАРА_ТУЗОВ,
            pack=(ShopItem("c_fool", "The Fool", "TAROT", 0),),  # таро, не планета
        )
        assert decide_action(state) == Action(kind="skip_pack")

    def test_buffoon_берёт_лучшего_джокера(self) -> None:
        state = GameState(
            phase=self._OPENED,
            full_deck=_ПАРА_ТУЗОВ,
            pack=(
                ShopItem("j_abstract", "Abstract Joker", "JOKER", 0),
                ShopItem("j_joker", "Joker", "JOKER", 0),
            ),
        )
        action = decide_action(state)
        assert action == Action(kind="pack", item_index=1, label="Joker")

    def test_buffoon_без_положительного_прироста_скипает(self) -> None:
        # Только нереализованный джокер → оценки нет → skip_pack.
        state = GameState(
            phase=self._OPENED,
            full_deck=_ПАРА_ТУЗОВ,
            pack=(ShopItem("j_совсем_новый", "???", "JOKER", 0),),
        )
        assert decide_action(state) == Action(kind="skip_pack")

    def test_ванильное_имя_фазы_тоже_работает(self) -> None:
        # На случай не-Steamodded окружения — PLANET_PACK всё ещё в наборе.
        state = GameState(
            phase="PLANET_PACK",
            full_deck=_ПАРА_ТУЗОВ,
            pack=(ShopItem("c_mercury", "Mercury", "PLANET", 0),),
        )
        assert decide_action(state).kind == "pack"  # type: ignore[union-attr]


class TestDispatchAction:
    """Общий перевод `Action.kind` -> RPC-метод (`autopilot.dispatch_action`),
    раньше жил внутри цикла `ui/tui.py`. Игры нет — проверяется имя вызванного
    метода и параметры (`FakeMod.calls`)."""

    def test_play_зовёт_play_с_индексами(self, bridge: ModBridge) -> None:
        dispatch_action(bridge, Action(kind="play", indices=(0, 2)))
        assert FakeMod.calls[-1]["method"] == "play"
        assert FakeMod.calls[-1]["params"] == {"cards": [0, 2]}

    def test_discard_зовёт_discard(self, bridge: ModBridge) -> None:
        dispatch_action(bridge, Action(kind="discard", indices=(1,)))
        assert FakeMod.calls[-1]["method"] == "discard"

    def test_select_и_skip_без_параметров(self, bridge: ModBridge) -> None:
        dispatch_action(bridge, Action(kind="select"))
        assert FakeMod.calls[-1]["method"] == "select"
        dispatch_action(bridge, Action(kind="skip"))
        assert FakeMod.calls[-1]["method"] == "skip"

    def test_buy_зовёт_buy_с_индексом_карты(self, bridge: ModBridge) -> None:
        dispatch_action(bridge, Action(kind="buy", item_index=2, label="Joker"))
        assert FakeMod.calls[-1]["method"] == "buy"
        assert FakeMod.calls[-1]["params"] == {"card": 2}

    def test_buy_pack_зовёт_buy_с_индексом_пака(self, bridge: ModBridge) -> None:
        dispatch_action(bridge, Action(kind="buy_pack", item_index=1, label="Buffoon Pack"))
        assert FakeMod.calls[-1]["method"] == "buy"
        assert FakeMod.calls[-1]["params"] == {"pack": 1}

    def test_next_round_и_cash_out(self, bridge: ModBridge) -> None:
        dispatch_action(bridge, Action(kind="next_round"))
        assert FakeMod.calls[-1]["method"] == "next_round"
        dispatch_action(bridge, Action(kind="cash_out"))
        assert FakeMod.calls[-1]["method"] == "cash_out"

    def test_pack_и_skip_pack_зовут_метод_pack(self, bridge: ModBridge) -> None:
        dispatch_action(bridge, Action(kind="pack", item_index=0, label="Mercury"))
        assert FakeMod.calls[-1]["method"] == "pack"
        assert FakeMod.calls[-1]["params"] == {"card": 0}
        dispatch_action(bridge, Action(kind="skip_pack"))
        assert FakeMod.calls[-1]["params"] == {"skip": True}

    def test_use_зовёт_use_с_индексом(self, bridge: ModBridge) -> None:
        dispatch_action(bridge, Action(kind="use", item_index=1, label="Mercury"))
        assert FakeMod.calls[-1]["method"] == "use"
        assert FakeMod.calls[-1]["params"] == {"consumable": 1}

    def test_sell_зовёт_sell_с_индексом_джокера(self, bridge: ModBridge) -> None:
        dispatch_action(bridge, Action(kind="sell", item_index=2, label="Abstract Joker"))
        assert FakeMod.calls[-1]["method"] == "sell"
        assert FakeMod.calls[-1]["params"] == {"joker": 2}


class TestDescribeAction:
    def test_розыгрыш_перечисляет_карты(self) -> None:
        cards = parse_cards("AH KS")
        assert describe_action(Action(kind="play", cards=cards)) == "сыграл AH KS"

    def test_покупка_называет_предмет(self) -> None:
        assert describe_action(Action(kind="buy", label="Joker")) == "купил в магазине: Joker"

    def test_каждый_вид_даёт_непустую_строку(self) -> None:
        for action in (
            Action(kind="play"),
            Action(kind="discard"),
            Action(kind="select"),
            Action(kind="skip"),
            Action(kind="buy"),
            Action(kind="buy_pack"),
            Action(kind="sell"),
            Action(kind="next_round"),
            Action(kind="cash_out"),
            Action(kind="pack"),
            Action(kind="skip_pack"),
            Action(kind="use"),
        ):
            assert describe_action(action)
