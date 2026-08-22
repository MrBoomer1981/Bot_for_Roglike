"""Тесты совета по скипу блайнда (`balatro_bot/solver/skip.py`).

Проверяется первый кусок Фазы 8 плана («Стратегия рана»): разложенные числа
для решения «играть или скипнуть», без единого вердикта — часть тегов
принципиально не сводится к одному числу (см. `core/tags.py`).
"""

from __future__ import annotations

from dataclasses import replace

from balatro_bot.core.state import BlindInfo, GameState
from balatro_bot.solver.skip import evaluate_skip


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


class TestEvaluateSkip:
    def test_нет_блайнда_на_выбор_даёт_none(self) -> None:
        state = GameState(
            phase="SELECTING_HAND",
            blinds={
                "small": _blind("SMALL", "DEFEATED", 300),
                "big": _blind("BIG", "CURRENT", 450),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        assert evaluate_skip(state) is None

    def test_пустые_blinds_дают_none(self) -> None:
        assert evaluate_skip(GameState()) is None

    def test_boss_select_не_даёт_совета_по_скипу(self) -> None:
        # Боссовый блайнд нельзя скипнуть — даже если статус SELECT.
        state = GameState(
            phase="BLIND_SELECT",
            blinds={
                "small": _blind("SMALL", "DEFEATED", 300),
                "big": _blind("BIG", "DEFEATED", 450),
                "boss": _blind("BOSS", "SELECT", 600),
            },
        )
        assert evaluate_skip(state) is None

    def test_big_blind_выбираем_следующий_boss(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            money=5,
            blinds={
                "small": _blind("SMALL", "DEFEATED", 300),
                "big": _blind(
                    "BIG", "SELECT", 450, "Investment Tag", "После победы над Боссом даёт $25"
                ),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert advice.blind_kind == "BIG"
        assert advice.required_score == 450
        assert advice.next_blind_kind == "BOSS"
        assert advice.next_required_score == 600
        assert advice.requirement_ratio == 600 / 450
        assert advice.play_reward_min == 4  # game.lua: bl_big.dollars = 4

    def test_small_blind_выбираем_следующий_big(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            blinds={
                "small": _blind("SMALL", "SELECT", 300, "Voucher Tag", "Добавляет ваучер"),
                "big": _blind("BIG", "UPCOMING", 450),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert advice.blind_kind == "SMALL"
        assert advice.next_blind_kind == "BIG"
        assert advice.next_required_score == 450
        assert advice.play_reward_min == 3  # game.lua: bl_small.dollars = 3

    def test_investment_tag_даёт_25_долларов_с_условием(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            blinds={
                "small": _blind("SMALL", "DEFEATED", 300),
                "big": _blind("BIG", "SELECT", 450, "Investment Tag", "..."),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert advice.tag_dollars == 25.0
        assert (
            "боссом" in advice.tag_dollars_note.lower() or "boss" in advice.tag_dollars_note.lower()
        )
        assert advice.tag is not None
        assert advice.tag.key == "tag_investment"

    def test_economy_tag_удваивает_деньги_с_потолком(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            money=15,
            blinds={
                "small": _blind("SMALL", "SELECT", 300, "Economy Tag", "..."),
                "big": _blind("BIG", "UPCOMING", 450),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert advice.tag_dollars == 15.0  # min(40, 15)

    def test_economy_tag_упирается_в_потолок(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            money=100,
            blinds={
                "small": _blind("SMALL", "SELECT", 300, "Economy Tag", "..."),
                "big": _blind("BIG", "UPCOMING", 450),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert advice.tag_dollars == 40.0  # min(40, 100)

    def test_тег_без_доступной_формулы_возвращает_none_с_объяснением(self) -> None:
        # Handy Tag требует счётчик рук за весь ран — мод его не присылает.
        state = GameState(
            phase="BLIND_SELECT",
            blinds={
                "small": _blind("SMALL", "SELECT", 300, "Handy Tag", "..."),
                "big": _blind("BIG", "UPCOMING", 450),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert advice.tag_dollars is None
        assert advice.tag_dollars_note

    def test_неизвестный_тег_не_роняет_и_помечает_none(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            blinds={
                "small": _blind("SMALL", "SELECT", 300, "Совершенно Новый Tag", "..."),
                "big": _blind("BIG", "UPCOMING", 450),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert advice.tag is None
        assert advice.tag_dollars is None

    def test_без_следующего_блайнда_в_данных_соотношение_не_считается(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            blinds={"big": _blind("BIG", "SELECT", 450, "Investment Tag", "...")},
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert advice.next_required_score == 0
        assert advice.requirement_ratio != advice.requirement_ratio  # NaN != NaN

    def test_replace_на_реальном_состоянии_не_ломает_остальное(self) -> None:
        # Убеждаемся, что новое поле `blinds` не мешает старому `blind`.
        base = GameState(phase="BLIND_SELECT")
        state = replace(
            base,
            blinds={"big": _blind("BIG", "SELECT", 450, "Investment Tag", "...")},
        )
        assert state.blind is None
        assert evaluate_skip(state) is not None
