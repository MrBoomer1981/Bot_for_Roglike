"""Тесты EV сброса: `solver/discard.py`.

Проверяется узкий срез Фазы 6 (раздел 8.1 плана): точный перебор добора для
одного заданного набора карт на сброс, не полный перебор по всем наборам.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

import balatro_bot.solver.discard as discard_module
from balatro_bot.adapters.manual import build_state
from balatro_bot.core.cards import parse_cards
from balatro_bot.solver.discard import discard_outcome, known_deck, rank_single_discards
from balatro_bot.solver.play import advise


class TestИзвестнаяКолода:
    def test_с_колодой_из_моста_точная(self) -> None:
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        state = replace(state, deck=parse_cards("2H 3H"))
        deck, exact = known_deck(state)
        assert exact is True
        assert deck == parse_cards("2H 3H")

    def test_без_колоды_приближение_из_52_минус_рука(self) -> None:
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        deck, exact = known_deck(state)
        assert exact is False
        assert len(deck) == 52 - len(state.hand)
        assert not set(deck) & set(state.hand)


class TestEVСброса:
    def test_среднее_совпадает_с_ручным_перебором(self) -> None:
        # Маленькая контролируемая колода: держим 7 карт, добираем 1 из двух.
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        state = replace(state, deck=parse_cards("2H 3C"))
        discard = parse_cards("2S")

        outcome = discard_outcome(state, discard)
        assert outcome is not None
        assert outcome.exact is True
        assert outcome.draws_considered == 2
        assert outcome.kept == state.hand[:-1]

        kept = state.hand[:-1]
        ожидаемое = (
            sum(
                advise(replace(state, hand=kept + draw)).best.score
                for draw in (parse_cards("2H"), parse_cards("3C"))
            )
            / 2
        )
        assert outcome.expected == ожидаемое

    def test_превышение_лимита_возвращает_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(discard_module, "MAX_DRAW_COMBINATIONS", 1)
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        state = replace(state, deck=parse_cards("2H 3C"))

        assert discard_outcome(state, parse_cards("2S")) is None

    def test_пустая_известная_колода_возвращает_none(self) -> None:
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        state = replace(state, deck=())

        assert discard_outcome(state, parse_cards("2S")) is None

    def test_несколько_карт_на_сброс(self) -> None:
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        state = replace(state, deck=parse_cards("2H 3C 4D"))
        discard = parse_cards("7C 7D")

        outcome = discard_outcome(state, discard)
        assert outcome is not None
        # C(3, 2) = 3 комбинации добора.
        assert outcome.draws_considered == 3


class TestRankSingleDiscards:
    def test_отсортировано_по_убыванию_ev(self) -> None:
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        ranking = rank_single_discards(state)
        значения = [outcome.expected for outcome in ranking]
        assert значения == sorted(значения, reverse=True)

    def test_каждая_карта_руки_свой_кандидат(self) -> None:
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        ranking = rank_single_discards(state)
        сброшенные = {outcome.discarded[0] for outcome in ranking}
        assert сброшенные == set(state.hand)
        assert all(len(outcome.discarded) == 1 for outcome in ranking)

    def test_пустая_рука_даёт_пустой_список(self) -> None:
        state = build_state("AH KH QH JH 9H")
        state = replace(state, hand=())
        assert rank_single_discards(state) == ()
