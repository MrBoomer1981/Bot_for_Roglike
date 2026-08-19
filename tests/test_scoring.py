"""Тесты симулятора подсчёта очков.

Числа посчитаны вручную от базовых значений руки. Базовые таблицы пока
провизорные, поэтому тесты проверяют не их, а **логику сборки счёта**:
порядок шагов, срабатывание эффектов, ретриггеры, копирование.

Когда в Фазе 3 появятся эталонные случаи из настоящей игры, они проверят
уже сами числа.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from balatro_bot.core.cards import Card, Edition, Enhancement, Rank, Seal, Suit, parse_cards
from balatro_bot.core.hands import HandType
from balatro_bot.core.scoring import ScoreOutcome, score_play
from balatro_bot.core.state import GameState, JokerCard, PokerHandInfo


def сыграть(
    hand: Sequence[Card],
    play: Sequence[int],
    jokers: Sequence[str] = (),
    **state_kwargs: object,
) -> ScoreOutcome:
    """Разыграть карты руки по индексам. Остальные считаются оставшимися в руке."""
    state = GameState(
        hand=tuple(hand),
        jokers=tuple(JokerCard(key) for key in jokers),
        **state_kwargs,  # type: ignore[arg-type]
    )
    return score_play(state, [state.hand[index] for index in play])


def карта(rank: Rank = Rank.ACE, suit: Suit = Suit.HEARTS, **kwargs: object) -> Card:
    return Card(rank, suit, **kwargs)  # type: ignore[arg-type]


class TestОснова:
    def test_старшая_карта(self) -> None:
        # База 5/1, туз даёт 11 очков: (5 + 11) × 1
        assert сыграть(parse_cards("AH"), [0]).expected == 16

    def test_пара(self) -> None:
        # База 10/2, два туза по 11: (10 + 22) × 2
        assert сыграть(parse_cards("AH AD"), [0, 1]).expected == 64

    def test_картинки_дают_десять(self) -> None:
        assert сыграть(parse_cards("KH"), [0]).expected == 15

    def test_тип_руки_попадает_в_итог(self) -> None:
        assert сыграть(parse_cards("AH AD"), [0, 1]).hand_type is HandType.PAIR

    def test_разбор_не_пустой(self) -> None:
        assert len(сыграть(parse_cards("AH AD"), [0, 1]).trace) > 0


class TestУлучшенияКарт:
    def test_bonus_даёт_очки(self) -> None:
        # (5 + 11 + 30) × 1
        assert сыграть([карта(enhancement=Enhancement.BONUS)], [0]).expected == 46

    def test_mult_даёт_множитель(self) -> None:
        # (5 + 11) × (1 + 4)
        assert сыграть([карта(enhancement=Enhancement.MULT)], [0]).expected == 80

    def test_glass_умножает(self) -> None:
        # (5 + 11) × (1 × 2)
        assert сыграть([карта(enhancement=Enhancement.GLASS)], [0]).expected == 32

    def test_stone_даёт_очки_но_не_ранг(self) -> None:
        # Каменная карта не имеет ранга: (5 + 50) × 1
        assert сыграть([карта(enhancement=Enhancement.STONE)], [0]).expected == 55

    def test_steel_работает_только_в_руке(self) -> None:
        # Сыграна обычная карта, steel остался в руке: (5 + 11) × (1 × 1.5)
        hand = [карта(), карта(Rank.KING, Suit.SPADES, enhancement=Enhancement.STEEL)]
        assert сыграть(hand, [0]).expected == 24

    def test_steel_не_срабатывает_если_сыгран(self) -> None:
        assert сыграть([карта(enhancement=Enhancement.STEEL)], [0]).expected == 16


class TestИздания:
    def test_foil(self) -> None:
        assert сыграть([карта(edition=Edition.FOIL)], [0]).expected == 66

    def test_holographic(self) -> None:
        assert сыграть([карта(edition=Edition.HOLOGRAPHIC)], [0]).expected == 176

    def test_polychrome(self) -> None:
        assert сыграть([карта(edition=Edition.POLYCHROME)], [0]).expected == 24


class TestПорядокВажен:
    def test_умножение_карты_идёт_до_прибавок_джокера(self) -> None:
        # Polychrome умножает множитель на шаге карты: (1 × 1.5) + 4 = 5.5
        # Если бы джокер успевал раньше, вышло бы (1 + 4) × 1.5 = 7.5.
        outcome = сыграть([карта(edition=Edition.POLYCHROME)], [0], ["j_joker"])
        assert outcome.expected == 16 * 5.5

    def test_джокеры_срабатывают_слева_направо(self) -> None:
        # Blueprint слева копирует соседа справа, значит +4 дважды.
        left = сыграть(parse_cards("AH AD"), [0, 1], ["j_blueprint", "j_joker"])
        # Справа копировать некого — только собственные +4.
        right = сыграть(parse_cards("AH AD"), [0, 1], ["j_joker", "j_blueprint"])
        assert left.expected == 320
        assert right.expected == 192


class TestДебафф:
    def test_отключённая_карта_не_даёт_очков(self) -> None:
        # Обе карты образуют пару, но одна отключена боссом: (10 + 11) × 2
        hand = [карта(), карта(Rank.ACE, Suit.DIAMONDS, debuffed=True)]
        assert сыграть(hand, [0, 1]).expected == 42


class TestРетриггеры:
    def test_красная_печать_повторяет_карту(self) -> None:
        # (5 + 11 + 11) × 1
        assert сыграть([карта(seal=Seal.RED)], [0]).expected == 27

    def test_hack_повторяет_мелкие_карты(self) -> None:
        # (5 + 2 + 2) × 1
        assert сыграть(parse_cards("2H"), [0], ["j_hack"]).expected == 9

    def test_hack_не_трогает_старшие(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_hack"]).expected == 16

    def test_hanging_chad_повторяет_первую_дважды(self) -> None:
        # (5 + 11 × 3) × 1
        assert сыграть(parse_cards("AH KH"), [0, 1], ["j_hanging_chad"]).expected == 38

    def test_dusk_срабатывает_в_последней_руке(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_dusk"], hands_left=1).expected == 27

    def test_dusk_молчит_если_руки_остались(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_dusk"], hands_left=3).expected == 16

    def test_mime_повторяет_карты_в_руке(self) -> None:
        # Steel в руке срабатывает дважды: (5 + 11) × 1 × 1.5 × 1.5
        hand = [карта(), карта(Rank.KING, Suit.SPADES, enhancement=Enhancement.STEEL)]
        assert сыграть(hand, [0], ["j_mime"]).expected == 36


class TestДжокерыНаКарты:
    def test_масть_даёт_множитель(self) -> None:
        # Greedy: +3 за каждую бубну. Пара семёрок, бубна одна: (10 + 14) × (2 + 3)
        assert сыграть(parse_cards("7D 7H"), [0, 1], ["j_greedy_joker"]).expected == 120

    def test_scholar_на_тузах(self) -> None:
        # (10 + 22 + 40) × (2 + 8)
        assert сыграть(parse_cards("AH AD"), [0, 1], ["j_scholar"]).expected == 720

    def test_odd_todd_на_нечётных(self) -> None:
        # (10 + 22 + 62) × 2
        assert сыграть(parse_cards("AH AD"), [0, 1], ["j_odd_todd"]).expected == 188

    def test_even_steven_на_чётных(self) -> None:
        # (10 + 16) × (2 + 8)
        assert сыграть(parse_cards("8H 8D"), [0, 1], ["j_even_steven"]).expected == 260

    def test_photograph_только_на_первой_картинке(self) -> None:
        # (10 + 20) × (2 × 2) — умножение один раз, на первом короле
        assert сыграть(parse_cards("KH KD"), [0, 1], ["j_photograph"]).expected == 120

    def test_baron_считает_королей_в_руке(self) -> None:
        # Король остался в руке: (5 + 11) × (1 × 1.5)
        assert сыграть(parse_cards("AH KD"), [0], ["j_baron"]).expected == 24


class TestУсловныеДжокеры:
    def test_jolly_на_паре(self) -> None:
        assert сыграть(parse_cards("AH AD"), [0, 1], ["j_jolly"]).expected == 320

    def test_jolly_молчит_без_пары(self) -> None:
        assert сыграть(parse_cards("AH KD"), [0, 1], ["j_jolly"]).expected == 16

    def test_sly_даёт_очки(self) -> None:
        # (10 + 22 + 50) × 2
        assert сыграть(parse_cards("AH AD"), [0, 1], ["j_sly"]).expected == 164

    def test_half_joker_на_коротких_руках(self) -> None:
        assert сыграть(parse_cards("AH AD"), [0, 1], ["j_half"]).expected == 704

    def test_half_joker_молчит_на_пяти_картах(self) -> None:
        outcome = сыграть(parse_cards("AH AD AC 2S 3D"), [0, 1, 2, 3, 4], ["j_half"])
        assert outcome.hand_type is HandType.THREE_OF_A_KIND
        assert outcome.expected == (30 + 33) * 3


class TestСостояниеРана:
    def test_bull_считает_деньги(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_bull"], money=10).expected == 36

    def test_banner_считает_сбросы(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_banner"], discards_left=2).expected == 76

    def test_abstract_считает_джокеров(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_abstract"]).expected == 64

    def test_supernova_без_данных_помечает_неточность(self) -> None:
        outcome = сыграть(parse_cards("AH"), [0], ["j_supernova"])
        assert any("Supernova" in reason for reason in outcome.unknown)

    def test_supernova_с_данными(self) -> None:
        info = {HandType.HIGH_CARD: PokerHandInfo(level=1, chips=5, mult=1, played=5)}
        outcome = сыграть(parse_cards("AH"), [0], ["j_supernova"], hand_info=info)
        assert outcome.expected == 16 * 6


class TestКопирующие:
    def test_blueprint_копирует_покарточный_эффект(self) -> None:
        outcome = сыграть(parse_cards("7D 7H"), [0, 1], ["j_blueprint", "j_greedy_joker"])
        assert outcome.expected == 24 * 8

    def test_blueprint_без_соседа_ничего_не_делает(self) -> None:
        assert сыграть(parse_cards("AH AD"), [0, 1], ["j_blueprint"]).expected == 64

    def test_brainstorm_копирует_самого_левого(self) -> None:
        assert сыграть(parse_cards("AH AD"), [0, 1], ["j_joker", "j_brainstorm"]).expected == 320

    def test_brainstorm_слева_копировать_некого(self) -> None:
        assert сыграть(parse_cards("AH AD"), [0, 1], ["j_brainstorm", "j_joker"]).expected == 192

    def test_два_blueprint_подряд(self) -> None:
        # Каждый копирует соседа справа, эффект утраивается: 2 + 4 × 3
        outcome = сыграть(parse_cards("AH AD"), [0, 1], ["j_blueprint", "j_blueprint", "j_joker"])
        assert outcome.expected == 32 * 14


class TestПравилаРаспознавания:
    def test_four_fingers_даёт_флеш_из_четырёх(self) -> None:
        # Четыре червы вразнобой (не стрит) и одна трефа: с джокером это флеш.
        outcome = сыграть(parse_cards("AH KH QH 9H 2C"), [0, 1, 2, 3, 4], ["j_four_fingers"])
        assert outcome.hand_type is HandType.FLUSH
        assert len(outcome.scoring_cards) == 4

    def test_без_four_fingers_это_старшая_карта(self) -> None:
        карты = parse_cards("AH KH QH 9H 2C")
        assert сыграть(карты, [0, 1, 2, 3, 4]).hand_type is HandType.HIGH_CARD

    def test_smeared_склеивает_масти(self) -> None:
        outcome = сыграть(parse_cards("AH KD QH JD 9H"), [0, 1, 2, 3, 4], ["j_smeared"])
        assert outcome.hand_type is HandType.FLUSH


class TestСлучайность:
    def test_lucky_даёт_разброс(self) -> None:
        outcome = сыграть([карта(enhancement=Enhancement.LUCKY)], [0])
        assert not outcome.certain
        assert outcome.minimum == 16
        assert outcome.maximum == 16 * 21

    def test_lucky_матожидание(self) -> None:
        # 0.8 × 16 + 0.2 × 336
        outcome = сыграть([карта(enhancement=Enhancement.LUCKY)], [0])
        assert outcome.expected == pytest.approx(80.0)

    def test_misprint_перебирает_все_исходы(self) -> None:
        outcome = сыграть(parse_cards("AH AD"), [0, 1], ["j_misprint"])
        assert outcome.minimum == 64
        assert outcome.maximum == 800
        assert outcome.expected == pytest.approx(32 * 13.5)

    def test_детерминированная_рука_без_разброса(self) -> None:
        assert сыграть(parse_cards("AH AD"), [0, 1]).certain


class TestЧестность:
    def test_нереализованный_джокер_помечает_неточность(self) -> None:
        outcome = сыграть(parse_cards("AH AD"), [0, 1], ["j_cavendish"])
        assert not outcome.exact
        assert any("j_cavendish" in reason for reason in outcome.unknown)

    def test_провизорные_таблицы_помечают_неточность(self) -> None:
        outcome = сыграть(parse_cards("AH AD"), [0, 1])
        assert not outcome.exact
        assert any("провизорн" in reason for reason in outcome.unknown)

    def test_с_данными_игры_расчёт_точен(self) -> None:
        info = {HandType.PAIR: PokerHandInfo(level=1, chips=10, mult=2)}
        outcome = сыграть(parse_cards("AH AD"), [0, 1], ["j_joker"], hand_info=info)
        assert outcome.exact
        assert outcome.unknown == ()


class TestРегрессии:
    """Дефекты, которые уже случались. Пусть не возвращаются."""

    def test_копирующие_джокеры_не_зацикливаются(self) -> None:
        # Blueprint копирует соседа справа, Brainstorm — самого левого.
        # Поставленные рядом, они копировали друг друга до переполнения стека.
        outcome = сыграть(parse_cards("AH AD"), [0, 1], ["j_blueprint", "j_brainstorm"])
        assert outcome.expected == 64

    def test_цикл_не_ломает_остальных_джокеров(self) -> None:
        # Обрыв цикла не должен глушить джокера, стоящего рядом.
        outcome = сыграть(parse_cards("AH AD"), [0, 1], ["j_blueprint", "j_brainstorm", "j_joker"])
        assert outcome.expected > 64

    def test_причина_неточности_не_дублируется(self) -> None:
        outcome = сыграть(parse_cards("AH AD"), [0, 1], ["j_cavendish"])
        про_джокера = [reason for reason in outcome.unknown if "cavendish" in reason]
        assert len(про_джокера) == 1

    def test_детерминированная_рука_считается_один_раз(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Раньше конвейер прогонялся дважды: сначала на разведку случайностей,
        # потом набело. Для руки без случайностей это была двойная работа.
        import balatro_bot.core.scoring as модуль

        прогоны = 0
        исходный = модуль._run_once

        def счётчик(*args: Any, **kwargs: Any) -> Any:
            nonlocal прогоны
            прогоны += 1
            return исходный(*args, **kwargs)

        monkeypatch.setattr(модуль, "_run_once", счётчик)
        сыграть(parse_cards("AH AD"), [0, 1])

        assert прогоны == 1
