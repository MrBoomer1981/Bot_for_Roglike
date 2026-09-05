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
    _discard_edge_is_noise,
    _indices_of,
    _on_pace_without_discard,
    _pace_projection,
    _reorder_indices,
    decide_action,
    decide_skip,
    describe_action,
    dispatch_action,
)
from balatro_bot.core.cards import Card, Rank, Suit, parse_cards
from balatro_bot.core.hands import HandType, base_values
from balatro_bot.core.scoring import ScoreOutcome
from balatro_bot.core.state import (
    BlindInfo,
    GameState,
    JokerCard,
    PokerHandInfo,
    ShopItem,
)
from balatro_bot.solver.actions import ActionOption, rank_actions
from balatro_bot.solver.play import Advice, Candidate
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
        assert _без_повода(decide_action(state)) == Action(kind="skip_pack")

    def test_пустой_пак_скипается(self) -> None:
        state = build_state("AH KH QH JH 9H")
        state = replace(state, phase="SMODS_BOOSTER_OPENED", pack=())
        assert _без_повода(decide_action(state)) == Action(kind="skip_pack")

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


def _outcome(expected: float) -> ScoreOutcome:
    """Заглушка результата подсчёта с заданным матожиданием — юнит-тестам
    гард B1 важно только `.score`/`.expected`, остальное не читается."""
    return ScoreOutcome(
        hand_type=HandType.HIGH_CARD,
        scoring_cards=(),
        expected=expected,
        minimum=expected,
        maximum=expected,
        trace=(),
        exact=True,
        unknown=(),
    )


class TestOnPaceWithoutDiscard:
    """`_on_pace_without_discard` — B1: добьём ли блайнд одними розыгрышами."""

    def _advice(self, *, best: float, required: int | None, scored: int) -> Advice:
        return Advice(
            candidates=(Candidate(parse_cards("AH"), _outcome(best)),),
            required=required,
            already_scored=scored,
        )

    def _state(self, hands_left: int, *, hands_played: int = 0, scored: int = 0) -> GameState:
        return replace(
            build_state("AH KH QH JH 9H", hands_left=hands_left),
            phase="SELECTING_HAND",
            hands_played=hands_played,
            chips_scored=scored,
        )

    def test_без_требования_не_на_темпе(self) -> None:
        advice = self._advice(best=9999, required=None, scored=0)
        assert _on_pace_without_discard(self._state(5), advice) is False

    def test_одна_рука_в_запасе_не_на_темпе(self) -> None:
        advice = self._advice(best=9999, required=100, scored=0)
        assert _on_pace_without_discard(self._state(1), advice) is False

    def test_требование_уже_набрано(self) -> None:
        advice = self._advice(best=1, required=100, scored=100)
        assert _on_pace_without_discard(self._state(2), advice) is True

    def test_на_темпе_когда_рук_с_запасом_хватает(self) -> None:
        # Прогноз без истории: 300 + 300×0.75×2 = 750 >= (500-0)×1.5 = 750.
        advice = self._advice(best=300, required=500, scored=0)
        assert _on_pace_without_discard(self._state(3), advice) is True

    def test_не_на_темпе_когда_рук_не_хватает(self) -> None:
        # 750 < (700-0)×1.5 = 1050.
        advice = self._advice(best=300, required=700, scored=0)
        assert _on_pace_without_discard(self._state(3), advice) is False

    def test_прогноз_строго_осторожнее_прежней_формулы(self) -> None:
        # Прежде было `лучшая × рук` — 300×3 = 900, и на требовании 600
        # (порог 900) guard срабатывал. Он завышал по построению: лучшую
        # руку играют первой, дальше карта хуже. Теперь не срабатывает.
        advice = self._advice(best=300, required=600, scored=0)
        assert _pace_projection(self._state(3), advice) < 300 * 3
        assert _on_pace_without_discard(self._state(3), advice) is False

    def test_с_историей_раунда_берётся_наблюдённое_среднее(self) -> None:
        # Раунд уже показал по 100 за руку — будущие руки считаются по
        # этому, а не по текущей лучшей. 300 + 100×2 = 500.
        advice = self._advice(best=300, required=600, scored=200)
        state = self._state(3, hands_played=2, scored=200)
        assert _pace_projection(state, advice) == 500

    def test_наблюдённое_среднее_не_завышает_текущую_руку(self) -> None:
        # Если раньше в раунде шли крупные руки, будущие всё равно не
        # считаются выше текущей лучшей — иначе прогноз снова поедет вверх.
        advice = self._advice(best=100, required=9999, scored=1000)
        state = self._state(3, hands_played=1, scored=1000)
        assert _pace_projection(state, advice) == 100 * 3

    def test_последняя_рука_считается_одна(self) -> None:
        advice = self._advice(best=250, required=9999, scored=0)
        assert _pace_projection(self._state(1), advice) == 250


class TestDiscardEdgeIsNoise:
    """`_discard_edge_is_noise` — B1: перевес сброса в пределах его же погрешности."""

    def _discard(self, score: float) -> ActionOption:
        return ActionOption(kind="discard", cards=(), score=score, label="", exact=False)

    def _play(self, score: float) -> Candidate:
        return Candidate(parse_cards("AH"), _outcome(score))

    def test_перевес_меньше_погрешности_это_шум(self) -> None:
        # живой прогон: разменивал флеш ~7371 на цель ~7427 (+0.7 %)
        assert _discard_edge_is_noise(self._discard(7427), self._play(7371)) is True

    def test_перевес_больше_погрешности_это_сигнал(self) -> None:
        assert _discard_edge_is_noise(self._discard(9000), self._play(7371)) is False

    def test_играть_нечего_любой_сброс_сигнал(self) -> None:
        assert _discard_edge_is_noise(self._discard(50), self._play(0)) is False


class TestDecideActionB1:
    """Автопилот не разменивает верный темп/розыгрыш на жадный сброс (B1)."""

    def test_на_темпе_играет_а_не_сбрасывает(self) -> None:
        # Готовый стрит-флеш ~1120; на 2 руки при блайнде 1400 темп есть
        # (1120 * 2 >= 1400 * 1.5), спекулятивный сброс не нужен.
        state = build_state("AH KH QH JH TH 2C 3D 4S", hands_left=2, discards_left=1, blind=1400)
        state = replace(state, phase="SELECTING_HAND")
        action = decide_action(state)
        assert action is not None
        assert action.kind == "play"
        assert set(action.cards) == set(parse_cards("AH KH QH JH TH"))

    def test_без_темпа_готовый_роял_не_разменивается_на_сброс(self) -> None:
        # Одна рука в запасе (гарда темпа не работает), блайнд огромный (нет
        # cheapest_sufficient). Готовый роял-флеш — добор ничего не улучшит,
        # оценка сброса «оставить как есть» упирается в тот же счёт: перевес в
        # пределах погрешности → играем руку, а не жжём сброс.
        state = build_state("AH KH QH JH TH 2C 3D 4S", hands_left=1, discards_left=1, blind=100_000)
        state = replace(state, phase="SELECTING_HAND")
        action = decide_action(state)
        assert action is not None
        assert action.kind == "play"
        assert set(action.cards) == set(parse_cards("AH KH QH JH TH"))

    def test_реальный_перевес_сброса_всё_ещё_сбрасывает(self) -> None:
        # Не на темпе (одна слабая рука, блайнд огромный), флеш-дро даёт
        # кратно больше тройки — сброс остаётся правильным решением.
        state = build_state("AH KH QH 7H 7C 7D 2S 3S", hands_left=1, discards_left=1, blind=100_000)
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
        assert _без_повода(action) == Action(kind="use", item_index=0, label="Mercury")

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
        assert _без_повода(action) == Action(kind="use", item_index=1, label="Mercury")


class TestReorderIndices:
    def test_новый_порядок_как_перестановка_текущих_индексов(self) -> None:
        current = ("a", "b", "c")
        assert _reorder_indices(current, ("c", "a", "b")) == (2, 0, 1)

    def test_устойчив_к_равным_элементам(self) -> None:
        current = ("j", "j", "k")
        assert _reorder_indices(current, ("k", "j", "j")) == (2, 0, 1)


class TestDecideActionПереставляетДжокеров:
    """D1: перед розыгрышем автопилот перебирает порядок джокеров и
    переставляет их, если для текущей руки есть заметно лучший порядок."""

    def _hand(self, jokers: tuple[JokerCard, ...]) -> GameState:
        state = build_state("AH AS KH QH 2C", blind=300)
        return replace(state, phase="SELECTING_HAND", jokers=jokers)

    def test_переставляет_когда_порядок_сильно_меняет_счёт(self) -> None:
        # (j_joker, j_blueprint): blueprint копирует соседа справа = ничего.
        # (j_blueprint, j_joker): копирует j_joker — счёт заметно выше.
        state = self._hand((JokerCard(key="j_joker"), JokerCard(key="j_blueprint")))
        action = decide_action(state)
        assert action is not None
        assert action.kind == "rearrange"
        assert action.indices == (1, 0)

    def test_не_переставляет_когда_порядок_уже_лучший(self) -> None:
        state = self._hand((JokerCard(key="j_blueprint"), JokerCard(key="j_joker")))
        action = decide_action(state)
        assert action is not None
        assert action.kind == "play"

    def test_один_джокер_нечего_переставлять(self) -> None:
        state = self._hand((JokerCard(key="j_joker"),))
        action = decide_action(state)
        assert action is not None
        assert action.kind == "play"

    def test_больше_шести_джокеров_не_перебирает(self) -> None:
        # rank_joker_orders возвращает None выше кап-а — просто играем.
        jokers = tuple(JokerCard(key="j_joker") for _ in range(7))
        state = self._hand(jokers)
        action = decide_action(state)
        assert action is not None
        assert action.kind == "play"


def _без_повода(action: Action | None) -> Action | None:
    """Действие без поля `reason` — для сравнения на равенство.

    `Action.reason` (улучшение E1a) хранит числа, по которым решение принято,
    и меняется при каждой правке порогов. Тесты здесь про **выбор**, а не про
    формулировку обоснования, поэтому сравнивают действие без него; сам
    `reason` проверяется отдельно в `TestОбоснованиеРешения`."""
    return None if action is None else replace(action, reason="")


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
        assert _без_повода(action) == Action(kind="skip")

    def test_играть_когда_скип_не_доказан(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            blinds={
                "big": _blind("BIG", "SELECT", 450, "Rare Tag", "..."),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        action = decide_action(state)
        assert _без_повода(action) == Action(kind="select")

    def test_boss_нельзя_скипнуть_решение_select(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            blinds={"boss": _blind("BOSS", "SELECT", 600)},
        )
        action = decide_action(state)
        assert _без_повода(action) == Action(kind="select")


class TestDecideActionНаRoundEval:
    def test_всегда_cash_out(self) -> None:
        # Решать нечего — без явного вызова автопилот застрял бы здесь
        # навсегда (модульный докстринг, раздел про ROUND_EVAL).
        assert _без_повода(decide_action(GameState(phase="ROUND_EVAL"))) == Action(kind="cash_out")


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
        assert _без_повода(decide_action(state)) == Action(kind="next_round")

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
        assert _без_повода(decide_action(state)) == Action(kind="next_round")

    def test_не_хватает_денег_уходит(self) -> None:
        state = GameState(
            phase="SHOP",
            money=1,
            joker_slots=5,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 99, "+4 Mult"),),
        )
        assert _без_повода(decide_action(state)) == Action(kind="next_round")

    def test_нет_слота_уходит(self) -> None:
        existing = tuple(JokerCard(key="j_joker") for _ in range(3))
        state = GameState(
            phase="SHOP",
            money=10,
            jokers=existing,
            joker_slots=3,
            shop=(ShopItem("j_greedy_joker", "Greedy Joker", "JOKER", 4),),
        )
        assert _без_повода(decide_action(state)) == Action(kind="next_round")

    def test_неизвестный_джокер_не_покупается(self) -> None:
        state = GameState(
            phase="SHOP",
            money=10,
            joker_slots=5,
            shop=(ShopItem("j_совсем_новый", "???", "JOKER", 5),),
        )
        assert _без_повода(decide_action(state)) == Action(kind="next_round")

    def test_неоценённый_ваучер_и_arcana_пак_не_покупаются(self) -> None:
        # Ваучер вне всех трёх уровней (`v_omen_globe`) и Arcana-пак не
        # получают ни оценки, ни heuristic_value — decide_action не выдумывает.
        state = GameState(
            phase="SHOP",
            money=100,
            shop_vouchers=(ShopItem("v_omen_globe", "Omen Globe", "VOUCHER", 10),),
            shop_packs=(ShopItem("p_arcana_normal_1", "Arcana Pack", "BOOSTER", 4),),
        )
        assert _без_повода(decide_action(state)) == Action(kind="next_round")

    def test_a4_покупает_ваучер_прямого_ресурса(self) -> None:
        # v_grabber (+1 рука) — expected_uplift в очках, порог как у джокера.
        state = GameState(
            phase="SHOP",
            money=20,
            joker_slots=5,
            shop_vouchers=(ShopItem("v_grabber", "Grabber", "VOUCHER", 10),),
        )
        action = decide_action(state)
        assert _без_повода(action) == Action(kind="buy_voucher", item_index=0, label="Grabber")

    def test_a4_покупает_структурный_эвристический_ваучер(self) -> None:
        # v_antimatter (+1 слот джокера), heuristic_value 8.0 >= 5.0.
        state = GameState(
            phase="SHOP",
            money=20,
            joker_slots=5,
            shop_vouchers=(ShopItem("v_antimatter", "Antimatter", "VOUCHER", 10),),
        )
        action = decide_action(state)
        assert _без_повода(action) == Action(kind="buy_voucher", item_index=0, label="Antimatter")

    def test_a4_слабый_эвристический_ваучер_не_покупается(self) -> None:
        # v_telescope heuristic_value 3.0 < порог 5.0 — не структурный апгрейд.
        state = GameState(
            phase="SHOP",
            money=20,
            joker_slots=5,
            shop_vouchers=(ShopItem("v_telescope", "Telescope", "VOUCHER", 10),),
        )
        assert _без_повода(decide_action(state)) == Action(kind="next_round")

    def test_a4_не_покупает_ваучер_не_по_карману(self) -> None:
        state = GameState(
            phase="SHOP",
            money=5,
            joker_slots=5,
            shop_vouchers=(ShopItem("v_antimatter", "Antimatter", "VOUCHER", 10),),
        )
        assert _без_повода(decide_action(state)) == Action(kind="next_round")

    def test_a4_денежный_ваучер_с_отрицательным_нетто_не_покупается(self) -> None:
        # v_seed_money: при $10 на руках прирост процентов ≈ 0 за горизонт,
        # это < цены 10 — чистого плюса в долларах нет.
        state = GameState(
            phase="SHOP",
            money=10,
            joker_slots=5,
            blinds={
                "small": _blind("SMALL", "DEFEATED", 300),
                "big": _blind("BIG", "UPCOMING", 450),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
            shop_vouchers=(ShopItem("v_seed_money", "Seed Money", "VOUCHER", 10),),
        )
        assert _без_повода(decide_action(state)) == Action(kind="next_round")

    def test_покупает_buffoon_пак_когда_джокеров_брать_нечего(self) -> None:
        state = GameState(
            phase="SHOP",
            money=20,
            joker_slots=5,
            full_deck=_ПАРА_ТУЗОВ,
            shop_packs=(ShopItem("p_buffoon_normal_1", "Buffoon Pack", "BOOSTER", 4),),
        )
        action = decide_action(state)
        assert _без_повода(action) == Action(kind="buy_pack", item_index=0, label="Buffoon Pack")

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
        assert _без_повода(action) == Action(kind="buy_pack", item_index=0, label="Celestial Pack")

    def test_buffoon_пак_без_слота_не_покупается(self) -> None:
        state = GameState(
            phase="SHOP",
            money=20,
            jokers=tuple(JokerCard(key="j_joker") for _ in range(5)),
            joker_slots=5,
            full_deck=_ПАРА_ТУЗОВ,
            shop_packs=(ShopItem("p_buffoon_normal_1", "Buffoon Pack", "BOOSTER", 4),),
        )
        assert _без_повода(decide_action(state)) == Action(kind="next_round")

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
        assert _без_повода(decide_action(state)) == Action(kind="next_round")

    def test_не_продаёт_если_денег_не_хватит_даже_с_продажей(self) -> None:
        state = GameState(
            phase="SHOP",
            money=1,
            jokers=(JokerCard(key="j_joker"), JokerCard(key="j_joker", debuffed=True)),
            joker_slots=2,
            shop=(ShopItem("j_joker", "Joker", "JOKER", 9),),  # 1 + 0 возврата < 9
        )
        assert _без_повода(decide_action(state)) == Action(kind="next_round")

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

    def test_a7_богатый_бот_с_пустыми_слотами_берёт_overstock(self) -> None:
        # Overstock (heuristic_value 3.0) ниже базового порога 5.0, но при $29
        # и трёх пустых слотах джокеров планка опускается до пола 3.0 —
        # берём (случай из run 6).
        state = GameState(
            phase="SHOP",
            money=29,
            joker_slots=5,
            jokers=(JokerCard(key="j_joker"), JokerCard(key="j_joker")),
            shop_vouchers=(ShopItem("v_overstock_norm", "Overstock", "VOUCHER", 10),),
        )
        action = decide_action(state)
        assert _без_повода(action) == Action(kind="buy_voucher", item_index=0, label="Overstock")

    def test_a7_при_нехватке_денег_порог_overstock_базовый(self) -> None:
        # $15 − $10 = $5 < _REROLL_MONEY_RESERVE (12): запаса нет, планка 5.0,
        # Overstock (3.0) не проходит.
        state = GameState(
            phase="SHOP",
            money=15,
            joker_slots=5,
            jokers=(JokerCard(key="j_joker"), JokerCard(key="j_joker")),
            shop_vouchers=(ShopItem("v_overstock_norm", "Overstock", "VOUCHER", 10),),
        )
        assert _без_повода(decide_action(state)) == Action(kind="next_round")

    def test_a7_при_полных_слотах_джокеров_порог_overstock_базовый(self) -> None:
        # Слоты джокеров заняты — лишний слот витрины некуда девать, планка 5.0.
        state = GameState(
            phase="SHOP",
            money=29,
            joker_slots=2,
            jokers=(JokerCard(key="j_joker"), JokerCard(key="j_joker")),
            shop_vouchers=(ShopItem("v_overstock_norm", "Overstock", "VOUCHER", 10),),
        )
        assert _без_повода(decide_action(state)) == Action(kind="next_round")

    def test_a7_не_трогает_неструктурный_ваучер(self) -> None:
        # v_telescope тоже heuristic_value 3.0, но это не +слот витрины —
        # планка остаётся 5.0 даже при богатом кармане и пустых слотах.
        state = GameState(
            phase="SHOP",
            money=29,
            joker_slots=5,
            jokers=(JokerCard(key="j_joker"), JokerCard(key="j_joker")),
            shop_vouchers=(ShopItem("v_telescope", "Telescope", "VOUCHER", 10),),
        )
        assert _без_повода(decide_action(state)) == Action(kind="next_round")


class TestDecideActionРазменДоПаков:
    """Улучшение A6: размен, захватывающий явно сильного джокера (оффер сам
    прошёл бы порог покупки в слот), решается ДО ветки паков — пак это
    низший приоритет, а в run 6 дешёвый Celestial-пак раз за разом опережал
    крупный размен."""

    def _state(self, requirement: int) -> GameState:
        # Слоты полны, оба джокера отключены (вклад 0), в витрине рабочий
        # j_joker и дешёвый Celestial-пак с положительной оценкой.
        return GameState(
            phase="SHOP",
            money=20,
            joker_slots=2,
            jokers=(
                JokerCard(key="j_joker", debuffed=True),
                JokerCard(key="j_joker", debuffed=True),
            ),
            full_deck=_ПАРА_ТУЗОВ,
            blinds={"small": _blind("SMALL", "UPCOMING", requirement)},
            shop=(ShopItem("j_joker", "Joker", "JOKER", 3),),
            shop_packs=(ShopItem("p_celestial_normal_1", "Celestial Pack", "BOOSTER", 4),),
        )

    def test_крупный_размен_опережает_дешёвый_пак(self) -> None:
        # Требование 300: прирост j_joker (+4 множ.) сильно выше 3% (9 очков),
        # оффер прошёл бы порог покупки — продаём мёртвый груз до пака.
        action = decide_action(self._state(300))
        assert action is not None
        assert action.kind == "sell"
        assert action.item_index == 0

    def test_мелкий_размен_не_опережает_пак(self) -> None:
        # Требование 100000: тот же прирост — доли процента от 3%, оффер порог
        # покупки не проходит, strong-проход пуст → покупаем пак (как раньше).
        action = decide_action(self._state(100_000))
        assert action is not None
        assert action.kind == "buy_pack"
        assert action.label == "Celestial Pack"


class TestDecideActionРеролМагазина:
    """Улучшение A5: когда в витрине брать нечего, перекатить её — если
    Монте-Карло рерола обещает годного джокера и остаётся денежный запас."""

    def _junk_shop(self, **overrides: object) -> GameState:
        # Неизвестный джокер — ветка покупки его пропускает, ваучеров и
        # паков нет, слоты свободны (продажи-замены не будет).
        base: dict[str, object] = {
            "phase": "SHOP",
            "money": 25,
            "joker_slots": 5,
            "shop_slots": 2,
            "reroll_cost": 5,
            "blinds": {"small": _blind("SMALL", "UPCOMING", 300)},
            "shop": (ShopItem("j_совсем_новый", "???", "JOKER", 5),),
        }
        return GameState(**{**base, **overrides})  # type: ignore[arg-type]

    def test_рероллит_когда_витрина_мусор_а_денег_с_запасом(self) -> None:
        assert _без_повода(decide_action(self._junk_shop())) == Action(kind="reroll")

    def test_не_рероллит_без_денежного_запаса(self) -> None:
        # $15 − $5 = $10 < _REROLL_MONEY_RESERVE (12).
        assert _без_повода(decide_action(self._junk_shop(money=15))) == Action(kind="next_round")

    def test_не_рероллит_без_известного_требования_блайнда(self) -> None:
        assert _без_повода(decide_action(self._junk_shop(blinds={}))) == Action(kind="next_round")

    def test_не_рероллит_когда_нечем_платить(self) -> None:
        assert _без_повода(decide_action(self._junk_shop(money=3))) == Action(kind="next_round")

    def test_не_рероллит_против_неподъёмного_блайнда(self) -> None:
        # 3% от 1_000_000 = 30_000 — реролл столько не наберёт.
        state = self._junk_shop(blinds={"small": _blind("SMALL", "UPCOMING", 1_000_000)})
        assert _без_повода(decide_action(state)) == Action(kind="next_round")

    def test_покупка_джокера_приоритетнее_рерола(self) -> None:
        # j_joker "+4 Mult" проходит порог покупки — рероллить не нужно.
        state = self._junk_shop(shop=(ShopItem("j_joker", "Joker", "JOKER", 3, "+4 Mult"),))
        action = decide_action(state)
        assert action is not None
        assert action.kind == "buy"

    # --- улучшение A8: две границы поверх прежней политики ---

    def test_не_скатывает_витрину_с_сильным_но_недоступным_оффером(self) -> None:
        # j_joker даёт ~193 прироста, но стоит $100 при $25 на руках. Прежняя
        # политика сравнивала оценку ролла (~138) только с абсолютной планкой
        # (3% от 300 = 9) и скатывала витрину; копить на уже лежащий оффер
        # выгоднее, чем платить за ролл.
        state = self._junk_shop(shop=(ShopItem("j_joker", "Joker", "JOKER", 100, "+4 Mult"),))
        assert _без_повода(decide_action(state)) == Action(kind="next_round")

    def test_не_рероллит_при_исчерпанном_лимите_роллов(self) -> None:
        # Цена $7 при базе $5 — два ролла в этом заходе уже сделаны.
        assert _без_повода(decide_action(self._junk_shop(reroll_cost=7))) == Action(
            kind="next_round"
        )

    def test_рероллит_пока_лимит_не_исчерпан(self) -> None:
        # Цена $6 — сделан один ролл, лимит (2) ещё не выбран.
        assert _без_повода(decide_action(self._junk_shop(reroll_cost=6))) == Action(kind="reroll")

    def test_лимит_роллов_учитывает_удешевляющий_ваучер(self) -> None:
        # С Reroll Surplus база $3, поэтому цена $5 означает уже два ролла —
        # лимит выбран, хотя без ваучера та же цена означала бы ноль роллов.
        state = self._junk_shop(used_vouchers=frozenset({"v_reroll_surplus"}))
        assert _без_повода(decide_action(state)) == Action(kind="next_round")


class TestDecideActionПродажаБалласта:
    """Улучшение A9: джокер с отрицательным вкладом стоит меньше пустого
    слота, и продать его выгодно даже когда в витрине брать нечего. До A9
    вклады считались только при полных слотах, и со свободным слотом бот
    такого джокера не видел вовсе — ран 8 довёз `Hit the Road` до анте 7."""

    def _board(self, **overrides: object) -> GameState:
        # `Joker Stencil` даёт множитель за каждый пустой слот, `Rough Gem`
        # на счёт розыгрыша не влияет вовсе — значит держать его хуже, чем
        # оставить слот пустым.
        base: dict[str, object] = {
            "phase": "SHOP",
            "money": 25,
            "joker_slots": 5,  # слоты НЕ полны: размен не сработает
            "shop_slots": 2,
            "reroll_cost": 5,
            "discards_left": 4,
            "blinds": {"small": _blind("SMALL", "UPCOMING", 300)},
            "jokers": (
                JokerCard(key="j_stencil", label="Joker Stencil", sell_value=4),
                JokerCard(key="j_joker", label="Joker", sell_value=2),
                JokerCard(key="j_rough_gem", label="Rough Gem", sell_value=3),
            ),
            "shop": (ShopItem("j_совсем_новый", "???", "JOKER", 5),),
        }
        return GameState(**{**base, **overrides})  # type: ignore[arg-type]

    def test_продаёт_джокера_хуже_пустого_слота(self) -> None:
        action = decide_action(self._board())
        assert _без_повода(action) == Action(kind="sell", item_index=2, label="Rough Gem")

    def test_не_продаёт_когда_все_вклады_положительны(self) -> None:
        state = self._board(
            jokers=(
                JokerCard(key="j_joker", label="Joker", sell_value=2),
                JokerCard(key="j_droll", label="Droll Joker", sell_value=2),
                JokerCard(key="j_banner", label="Banner", sell_value=2),
            )
        )
        action = decide_action(state)
        assert action is not None
        assert action.kind != "sell"

    def test_вечный_балласт_не_продаётся(self) -> None:
        # Мод откажет в продаже вечного джокера, поэтому он не кандидат.
        state = self._board(
            jokers=(
                JokerCard(key="j_stencil", label="Joker Stencil", sell_value=4),
                JokerCard(key="j_joker", label="Joker", sell_value=2),
                JokerCard(key="j_rough_gem", label="Rough Gem", sell_value=3, eternal=True),
            )
        )
        action = decide_action(state)
        assert action is not None
        assert action.kind != "sell"

    def test_не_опускается_ниже_нижней_границы_джокеров(self) -> None:
        # Продажа оставила бы одного джокера — страховка от каскада.
        state = self._board(
            jokers=(
                JokerCard(key="j_stencil", label="Joker Stencil", sell_value=4),
                JokerCard(key="j_rough_gem", label="Rough Gem", sell_value=3),
            )
        )
        action = decide_action(state)
        assert action is not None
        assert action.kind != "sell"

    def test_покупка_приоритетнее_продажи_балласта(self) -> None:
        # Оффер должен быть достаточно сильным, чтобы перебить штраф за
        # занятый слот, который накладывает `Joker Stencil`: слабый джокер
        # тут честно уходит в минус и покупкой не становится.
        state = self._board(shop=(ShopItem("j_cavendish", "Cavendish", "JOKER", 3),))
        action = decide_action(state)
        assert action is not None
        assert action.kind == "buy"

    def test_продажа_балласта_приоритетнее_рерола(self) -> None:
        # Денег хватает и на ролл, но сначала избавляемся от балласта.
        action = decide_action(self._board(money=40))
        assert _без_повода(action) == Action(kind="sell", item_index=2, label="Rough Gem")


class TestDecideActionТаро:
    """Улучшение C1. Политика Таротов намеренно строже, чем у планет:
    планета применяется сразу (level-up не портит ничего), а Тарот
    необратимо переписывает карту колоды на весь ран, поэтому требует
    строго положительного прироста, прошедшего порог покупки джокера."""

    def _рука(self, **overrides: object) -> GameState:
        base: dict[str, object] = {
            "phase": "SELECTING_HAND",
            "hands_left": 4,
            "discards_left": 0,
            "consumables": (ShopItem("c_empress", "The Empress", "TAROT", 0),),
        }
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        return replace(state, **{**base, **overrides})  # type: ignore[arg-type]

    def test_применяет_тарот_прошедший_порог(self) -> None:
        action = decide_action(self._рука())
        assert action is not None
        assert action.kind == "use"
        assert action.label == "The Empress"
        # Цели обязаны быть — мод ждёт индексы карт руки.
        assert len(action.indices) == 2

    def test_не_применяет_тарот_ниже_порога(self) -> None:
        # 3% от 1 000 000 = 30 000 — прирост Empress столько не набирает.
        state = self._рука(blinds={"small": _blind("SMALL", "UPCOMING", 1_000_000)})
        action = decide_action(state)
        assert action is None or action.kind != "use"

    def test_денежный_тарот_автопилот_не_трогает(self) -> None:
        # Доллары против очков без курса обмена не сравнить — показываем
        # человеку, но сами не применяем.
        state = self._рука(consumables=(ShopItem("c_hermit", "The Hermit", "TAROT", 0),), money=20)
        action = decide_action(state)
        assert action is None or action.kind != "use"

    def test_неоценённый_тарот_автопилот_не_трогает(self) -> None:
        state = self._рука(consumables=(ShopItem("c_judgement", "Judgement", "TAROT", 0),))
        action = decide_action(state)
        assert action is None or action.kind != "use"

    def test_планета_приоритетнее_тарота(self) -> None:
        state = self._рука(
            consumables=(
                ShopItem("c_empress", "The Empress", "TAROT", 0),
                ShopItem("c_mercury", "Mercury", "PLANET", 0),
            )
        )
        action = decide_action(state)
        assert action is not None
        assert action.kind == "use"
        assert action.label == "Mercury"
        assert action.indices == ()  # планете цели не нужны


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
        assert _без_повода(action) == Action(kind="pack", item_index=1, label="Mercury")

    def test_planet_неопознанные_карты_приводят_к_скипу_пака(self) -> None:
        state = GameState(
            phase=self._OPENED,
            full_deck=_ПАРА_ТУЗОВ,
            pack=(ShopItem("c_fool", "The Fool", "TAROT", 0),),  # таро, не планета
        )
        assert _без_повода(decide_action(state)) == Action(kind="skip_pack")

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
        assert _без_повода(action) == Action(kind="pack", item_index=1, label="Joker")

    def test_buffoon_без_положительного_прироста_скипает(self) -> None:
        # Только нереализованный джокер → оценки нет → skip_pack.
        state = GameState(
            phase=self._OPENED,
            full_deck=_ПАРА_ТУЗОВ,
            pack=(ShopItem("j_совсем_новый", "???", "JOKER", 0),),
        )
        assert _без_повода(decide_action(state)) == Action(kind="skip_pack")

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

    def test_buy_voucher_зовёт_buy_с_индексом_ваучера(self, bridge: ModBridge) -> None:
        dispatch_action(bridge, Action(kind="buy_voucher", item_index=0, label="Grabber"))
        assert FakeMod.calls[-1]["method"] == "buy"
        assert FakeMod.calls[-1]["params"] == {"voucher": 0}

    def test_rearrange_зовёт_rearrange_с_порядком_джокеров(self, bridge: ModBridge) -> None:
        dispatch_action(bridge, Action(kind="rearrange", indices=(1, 0)))
        assert FakeMod.calls[-1]["method"] == "rearrange"
        assert FakeMod.calls[-1]["params"] == {"jokers": [1, 0]}

    def test_reroll_зовёт_reroll_без_параметров(self, bridge: ModBridge) -> None:
        dispatch_action(bridge, Action(kind="reroll"))
        assert FakeMod.calls[-1]["method"] == "reroll"
        assert "params" not in FakeMod.calls[-1]

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
        # Планете цели не нужны — `cards` в запрос не кладётся вовсе.
        dispatch_action(bridge, Action(kind="use", item_index=1, label="Mercury"))
        assert FakeMod.calls[-1]["method"] == "use"
        assert FakeMod.calls[-1]["params"] == {"consumable": 1}

    def test_use_передаёт_цели_тарота(self, bridge: ModBridge) -> None:
        # Улучшение C1: Тароту нужны карты-цели, они едут в `cards`.
        dispatch_action(
            bridge, Action(kind="use", item_index=0, indices=(1, 3), label="The Empress")
        )
        assert FakeMod.calls[-1]["params"] == {"consumable": 0, "cards": [1, 3]}

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
            Action(kind="buy_voucher"),
            Action(kind="sell"),
            Action(kind="rearrange"),
            Action(kind="reroll"),
            Action(kind="next_round"),
            Action(kind="cash_out"),
            Action(kind="pack"),
            Action(kind="skip_pack"),
            Action(kind="use"),
        ):
            assert describe_action(action)


def _hand_info() -> dict[HandType, PokerHandInfo]:
    """Таблица типов рук, какую мод присылает всегда. Ручной ввод её не
    заполняет, а без неё `j_card_sharp` читать нечего."""
    return {
        hand_type: PokerHandInfo(
            level=1,
            chips=base_values(hand_type, 1).chips,
            mult=base_values(hand_type, 1).mult,
        )
        for hand_type in HandType
    }


class TestDecideActionCardSharpНеБалласт:
    """Улучшение A11: в ране 10 бот продал `Card Sharp`, потому что
    контрфактум магазина не старил `played_this_round` и джокер измерялся
    ровно в 0 — тот же класс ошибки, что A9 и A10, только последний из
    девяти читающих состояние джокеров."""

    def _board(self, *jokers: JokerCard) -> GameState:
        return GameState(
            phase="SHOP",
            money=25,
            joker_slots=5,  # слоты НЕ полны: работает именно ветка балласта
            shop_slots=2,
            reroll_cost=5,
            hands_left=4,
            discards_left=4,
            hand_info=_hand_info(),
            blinds={"small": _blind("SMALL", "UPCOMING", 300)},
            jokers=jokers,
            shop=(ShopItem("j_совсем_новый", "???", "JOKER", 5),),
        )

    def test_card_sharp_не_продаётся_как_балласт(self) -> None:
        board = self._board(
            JokerCard(key="j_stencil", label="Joker Stencil", sell_value=4),
            JokerCard(key="j_joker", label="Joker", sell_value=2),
            JokerCard(key="j_card_sharp", label="Card Sharp", sell_value=3),
        )
        action = decide_action(board)
        assert action is not None
        assert not (action.kind == "sell" and action.label == "Card Sharp")

    def test_настоящий_балласт_на_той_же_доске_по_прежнему_продаётся(self) -> None:
        # Контроль: сама ветка жива, изменилась только оценка Card Sharp.
        board = self._board(
            JokerCard(key="j_stencil", label="Joker Stencil", sell_value=4),
            JokerCard(key="j_joker", label="Joker", sell_value=2),
            JokerCard(key="j_rough_gem", label="Rough Gem", sell_value=3),
        )
        assert _без_повода(decide_action(board)) == Action(
            kind="sell", item_index=2, label="Rough Gem"
        )


class TestОбоснованиеРешения:
    """Улучшение E1a: `Action.reason` несёт числа, по которым решение принято.

    Проверяется не формулировка, а то, что обоснование вообще есть и в нём
    стоят те самые величины — иначе журнал рана снова станет списком «купил,
    продал» без единого «почему», ради которого он и заводился."""

    def _shop(self, **overrides: object) -> GameState:
        base: dict[str, object] = {
            "phase": "SHOP",
            "money": 25,
            "joker_slots": 5,
            "shop_slots": 2,
            "reroll_cost": 5,
            "blinds": {"small": _blind("SMALL", "UPCOMING", 300)},
            "shop": (ShopItem("j_joker", "Joker", "JOKER", 3),),
        }
        return GameState(**{**base, **overrides})  # type: ignore[arg-type]

    def test_покупка_объясняет_прирост_и_порог(self) -> None:
        action = decide_action(self._shop())
        assert action is not None and action.kind == "buy"
        assert "прирост" in action.reason
        assert "порога" in action.reason
        assert "$3" in action.reason

    def test_продажа_балласта_объясняет_вклад(self) -> None:
        state = self._shop(
            jokers=(
                JokerCard(key="j_stencil", label="Joker Stencil", sell_value=4),
                JokerCard(key="j_joker", label="Joker", sell_value=2),
                JokerCard(key="j_rough_gem", label="Rough Gem", sell_value=3),
            ),
            shop=(ShopItem("j_совсем_новый", "???", "JOKER", 5),),
        )
        action = decide_action(state)
        assert action is not None and action.kind == "sell"
        assert "балласт" in action.reason
        assert "вклад" in action.reason

    def test_решение_без_чисел_остаётся_без_повода(self) -> None:
        # `cash_out` обосновывать нечем — поле обязано быть пустым, а не
        # содержать выдуманное объяснение.
        action = decide_action(GameState(phase="ROUND_EVAL"))
        assert action is not None
        assert action.reason == ""


class TestОбоснованиеНаИгровомПути:
    """Доделка E1a по итогам рана ZODIAC. Вчерашняя версия заполняла
    `Action.reason` в шести местах, и все шесть были в магазине: из 98
    решений рана обоснование несли 19, а все 31 розыгрыш и все 7 сбросов —
    ни одного. Из-за этого вопрос «почему не сбросил» журналом не закрылся.

    Проверяется не формулировка, а что обоснование есть и в нём стоят
    величины именно той ветки, которая решила."""

    def _рука(self, **overrides: object) -> GameState:
        base: dict[str, object] = {
            "phase": "SELECTING_HAND",
            "hands_left": 4,
            "discards_left": 3,
            "blinds": {"small": _blind("SMALL", "CURRENT", 300)},
            "blind": _blind("SMALL", "CURRENT", 300),
            "hand_info": _hand_info(),
        }
        state = replace(build_state("AH KH QH JH 9H 7C 7D 2S"), **{**base, **overrides})  # type: ignore[arg-type]
        return state

    def test_гарантированный_ход_называет_свой_предел(self) -> None:
        # Требование низкое — флеш закрывает его с гарантией.
        state = self._рука(blind=_blind("SMALL", "CURRENT", 50), blinds={})
        action = decide_action(state)
        assert action is not None and action.kind == "play"
        assert "гарантированный ход" in action.reason
        assert "нижний предел" in action.reason

    def test_на_темпе_называет_прогноз_и_остаток_сбросов(self) -> None:
        # Прогноз перекрывает остаток с запасом — сброс не нужен, и в
        # журнале должно быть видно, что сбросы при этом целы.
        state = self._рука(blind=_blind("SMALL", "CURRENT", 200), blinds={}, chips_scored=0)
        action = decide_action(state)
        assert action is not None
        if "на темпе" in action.reason:
            assert "прогноз" in action.reason
            assert "сбросов не тронуто 3" in action.reason

    def test_выбор_блайнда_объясняется(self) -> None:
        state = replace(
            build_state("AH KH QH JH 9H"),
            phase="BLIND_SELECT",
            blinds={"small": _blind("SMALL", "SELECT", 300)},
        )
        action = decide_action(state)
        assert action is not None and action.kind in ("select", "skip")
        assert action.reason != ""

    def test_уход_из_магазина_называет_лучший_оффер_и_порог(self) -> None:
        state = GameState(
            phase="SHOP",
            money=2,
            joker_slots=5,
            shop_slots=2,
            blinds={"small": _blind("SMALL", "UPCOMING", 300)},
            shop=(ShopItem("j_joker", "Joker", "JOKER", 99),),
        )
        action = decide_action(state)
        assert action is not None and action.kind == "next_round"
        assert action.reason != ""
        assert "порог" in action.reason or "нет оценённых" in action.reason

    def test_каждое_игровое_решение_несёт_обоснование(self) -> None:
        # Прямая регрессия рана ZODIAC: пустых обоснований на игровом пути
        # быть не должно вовсе.
        for требование in (50, 200, 1000, 100000):
            state = self._рука(blind=_blind("SMALL", "CURRENT", требование), blinds={})
            action = decide_action(state)
            assert action is not None, требование
            assert action.reason != "", (требование, action.kind)
