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
from balatro_bot.autopilot import Action, _indices_of, decide_action, decide_skip
from balatro_bot.core.cards import Card, Rank, Suit, parse_cards
from balatro_bot.core.state import BlindInfo, GameState, JokerCard, ShopItem
from balatro_bot.solver.skip import evaluate_skip


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
    def test_не_фаза_selecting_hand_ничего_не_решает(self) -> None:
        # Вскрытие паков ещё не замкнуто до вердикта (раздел 6, п. 9.2).
        state = build_state("AH KH QH JH 9H")
        state = replace(state, phase="TAROT_PACK")
        assert decide_action(state) is None

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
        state = build_state("AH KH QH 9H 2C", discards_left=1)
        state = replace(state, phase="SELECTING_HAND")

        по_умолчанию = decide_action(state)
        assert по_умолчанию is not None
        assert по_умолчанию.kind == "discard"

        без_сбросов = decide_action(state, include_discards=False)
        assert без_сбросов is not None
        assert без_сбросов.kind == "play"


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
        assert action.shop_index == 0
        assert action.label == "Joker"

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

    def test_ваучеры_и_паки_не_покупаются(self) -> None:
        # Нет числовой оценки — evaluate_shop не даёт им expected_uplift,
        # decide_action не выдумывает вердикт.
        state = GameState(
            phase="SHOP",
            money=100,
            shop_vouchers=(ShopItem("v_overstock", "Overstock", "VOUCHER", 10),),
            shop_packs=(ShopItem("p_arcana", "Arcana Pack", "BOOSTER", 4),),
        )
        assert decide_action(state) == Action(kind="next_round")
