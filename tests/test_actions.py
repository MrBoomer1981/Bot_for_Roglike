"""Тесты единого списка действий (`balatro_bot/solver/actions.py`).

Розыгрыш и сброс — одно и то же решение с точки зрения игрока (оба тратят
ход), поэтому `rank_actions` сливает их в один список вместо двух отдельных.
"""

from __future__ import annotations

import pytest

import balatro_bot.solver.actions as actions_module
from balatro_bot.adapters.manual import build_state
from balatro_bot.core.cards import parse_cards
from balatro_bot.core.hands import HandType
from balatro_bot.core.scoring import ScoreOutcome
from balatro_bot.core.state import GameState
from balatro_bot.solver.actions import rank_actions
from balatro_bot.solver.discard import DiscardOption, OutcomeBucket
from balatro_bot.solver.play import Candidate


def _play(cards: str, score: float) -> Candidate:
    parsed = parse_cards(cards)
    outcome = ScoreOutcome(
        hand_type=HandType.PAIR,
        scoring_cards=parsed,
        expected=score,
        minimum=score,
        maximum=score,
        trace=(),
        exact=True,
        unknown=(),
    )
    return Candidate(cards=parsed, outcome=outcome)


def _discard(cards: str, score: float) -> DiscardOption:
    parsed = parse_cards(cards)
    return DiscardOption(
        discard=parsed,
        keep=(),
        expected=score,
        distribution=(OutcomeBucket(outs_hit=1, probability=1.0, score=score),),
        targets=("тест",),
        needed=1,
        exact=False,
        exact_deck=True,
    )


class TestRankActions:
    def test_список_отсортирован_по_убыванию_счёта(self) -> None:
        state = build_state("AH KH QH 9H 2C 7D 3S 4S", discards_left=1)
        actions = rank_actions(state, top=6)
        значения = [action.score for action in actions]
        assert значения == sorted(значения, reverse=True)

    def test_смешивает_розыгрыши_и_сбросы_по_убыванию_счёта(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Подставные источники вместо реального решателя: слияние должно
        # сортировать по счёту независимо от того, розыгрыш это или сброс,
        # а не группировать сначала все розыгрыши, потом все сбросы.
        def fake_rank_plays(state: GameState, limit: int | None = None) -> tuple[Candidate, ...]:
            return (_play("AH KH", 300), _play("2S 3S", 50))

        def fake_advise_discard(state: GameState, limit: int = 5) -> tuple[DiscardOption, ...]:
            return (_discard("QH 9H", 200), _discard("7D 4S", 20))

        monkeypatch.setattr(actions_module, "rank_plays", fake_rank_plays)
        monkeypatch.setattr(actions_module, "advise_discard", fake_advise_discard)

        state = build_state("AH KH QH 9H 2C 7D 3S 4S", discards_left=1)
        actions = actions_module.rank_actions(state, top=4)

        assert [(a.kind, a.score) for a in actions] == [
            ("play", 300),
            ("discard", 200),
            ("play", 50),
            ("discard", 20),
        ]

    def test_top_обрезает_после_слияния_а_не_до(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_rank_plays(state: GameState, limit: int | None = None) -> tuple[Candidate, ...]:
            return (_play("AH KH", 300),)

        def fake_advise_discard(state: GameState, limit: int = 5) -> tuple[DiscardOption, ...]:
            return (_discard("QH 9H", 250), _discard("7D 4S", 20))

        monkeypatch.setattr(actions_module, "rank_plays", fake_rank_plays)
        monkeypatch.setattr(actions_module, "advise_discard", fake_advise_discard)

        state = build_state("AH KH QH 9H 2C 7D 3S 4S", discards_left=1)
        actions = actions_module.rank_actions(state, top=2)

        # Топ-2 по счёту — розыгрыш (300) и лучший сброс (250), а не оба
        # розыгрыша (тут он один) плюс худший сброс.
        assert [(a.kind, a.score) for a in actions] == [("play", 300), ("discard", 250)]

    def test_без_сбросов_только_розыгрыши(self) -> None:
        state = build_state("AH KH QH 9H 2C 7D 3S 4S", discards_left=0)
        actions = rank_actions(state, top=6)
        assert actions
        assert all(action.kind == "play" for action in actions)

    def test_include_discards_false_отключает_сбросы(self) -> None:
        state = build_state("AH KH QH 9H 2C 7D 3S 4S", discards_left=1)
        actions = rank_actions(state, top=6, include_discards=False)
        assert actions
        assert all(action.kind == "play" for action in actions)

    def test_top_ограничивает_длину(self) -> None:
        state = build_state("AH KH QH 9H 2C 7D 3S 4S", discards_left=1)
        assert len(rank_actions(state, top=2)) <= 2

    def test_top_ноль_даёт_хотя_бы_один_вариант(self) -> None:
        state = build_state("AH KH QH 9H 2C 7D 3S 4S", discards_left=1)
        assert len(rank_actions(state, top=0)) == 1

    def test_у_розыгрыша_есть_гарантия_у_сброса_нет(self) -> None:
        state = build_state("AH KH QH 9H 2C 7D 3S 4S", discards_left=1)
        actions = rank_actions(state, top=6)
        for action in actions:
            if action.kind == "play":
                assert action.minimum is not None
                assert action.success_probability is None
            else:
                assert action.minimum is None
                assert action.success_probability is not None
                assert 0.0 <= action.success_probability <= 1.0

    def test_сброс_всегда_неточен_даже_если_розыгрыш_точен(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_rank_plays(state: GameState, limit: int | None = None) -> tuple[Candidate, ...]:
            return (_play("AH KH", 300),)  # exact=True внутри _play

        def fake_advise_discard(state: GameState, limit: int = 5) -> tuple[DiscardOption, ...]:
            return (_discard("QH 9H", 200),)  # DiscardOption.exact всегда False

        monkeypatch.setattr(actions_module, "rank_plays", fake_rank_plays)
        monkeypatch.setattr(actions_module, "advise_discard", fake_advise_discard)

        state = build_state("AH KH QH 9H 2C 7D 3S 4S", discards_left=1)
        actions = actions_module.rank_actions(state, top=2)

        by_kind = {a.kind: a.exact for a in actions}
        assert by_kind == {"play": True, "discard": False}
