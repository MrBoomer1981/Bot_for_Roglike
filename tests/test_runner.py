"""Тесты ран-раннера (`balatro_bot/runner.py`), Фаза 9.7.

Ядро решений (`autopilot.decide_action`/`dispatch_action`) уже покрыто
своими тестами — здесь проверяется только логика самого цикла `play_run`:
распознавание терминального состояния, затыка, прерывания, лог решений,
пережидание переходной фазы, — и пакетная обвязка `run_batch`.

Фальшивый мод из `tests/fake_mod.py` статичен (один и тот же ответ на всё),
поэтому вместо него — `ScriptedBridge` с заранее заданной последовательностью
состояний, а `decide_action`/`dispatch_action` подменяются в пространстве
имён `runner`, чтобы не тащить в тест реальный солвер.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from balatro_bot import runner
from balatro_bot.adapters.mod_bridge import ModBridge, ModBridgeError
from balatro_bot.autopilot import Action
from balatro_bot.core.state import GameState
from balatro_bot.runner import StakeSummary, play_run, run_batch


def _state(phase: str, *, ante: int = 1, round_number: int = 1, won: bool = False) -> GameState:
    return GameState(phase=phase, ante=ante, round_number=round_number, won=won)


class ScriptedBridge(ModBridge):
    """Мост с заранее заданной лентой состояний. `start`/каждое действие
    отдаёт следующее состояние ленты; `game_state` — текущее, не сдвигая
    указатель (повторный опрос переходной фазы)."""

    def __init__(self, timeline: Sequence[GameState]) -> None:
        self._timeline = list(timeline)
        self._i = 0
        self.actions: list[Action] = []
        self.menu_calls = 0
        self.start_calls: list[tuple[str, str, str | None]] = []

    def _current(self) -> GameState:
        return self._timeline[min(self._i, len(self._timeline) - 1)]

    def _advance(self) -> GameState:
        state = self._current()
        self._i += 1
        return state

    def menu(self) -> GameState:
        self.menu_calls += 1
        return _state("MENU")

    def start(self, deck: str, stake: str, *, seed: str | None = None) -> GameState:
        self.start_calls.append((deck, stake, seed))
        return self._advance()

    def game_state(self) -> GameState:
        return self._current()


@pytest.fixture
def patch_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Заменить `decide_action` на «всегда сыграть» и `dispatch_action` на
    «сдвинуть ленту `ScriptedBridge`». Отдельные тесты переопределяют
    `runner.decide_action` под себя после этой фикстуры."""

    def fake_decide(state: GameState, *, include_discards: bool = True) -> Action | None:
        return Action(kind="play", cards=(), indices=())

    def fake_dispatch(bridge: ModBridge, action: Action) -> GameState:
        assert isinstance(bridge, ScriptedBridge)
        bridge.actions.append(action)
        return bridge._advance()

    monkeypatch.setattr(runner, "decide_action", fake_decide)
    monkeypatch.setattr(runner, "dispatch_action", fake_dispatch)


@pytest.mark.usefixtures("patch_engine")
class TestPlayRun:
    def test_победа_фиксируется(self) -> None:
        bridge = ScriptedBridge(
            [
                _state("BLIND_SELECT"),
                _state("SELECTING_HAND", ante=8),
                _state("SELECTING_HAND", ante=8, won=True),
            ]
        )
        report = play_run(bridge, deck="RED", stake="WHITE", sleep=lambda _: None)
        assert report.outcome == "won"
        assert report.won is True
        assert report.ante == 8
        assert bridge.menu_calls == 1
        assert bridge.start_calls == [("RED", "WHITE", None)]
        assert len(report.decisions) == 2

    def test_поражение_по_game_over(self) -> None:
        bridge = ScriptedBridge(
            [_state("BLIND_SELECT"), _state("SELECTING_HAND"), _state("GAME_OVER", ante=4)]
        )
        report = play_run(bridge, deck="RED", stake="WHITE", sleep=lambda _: None)
        assert report.outcome == "lost"
        assert report.ante == 4

    def test_сид_прокидывается_в_start(self) -> None:
        bridge = ScriptedBridge([_state("BLIND_SELECT"), _state("GAME_OVER")])
        play_run(bridge, deck="ERRATIC", stake="GOLD", seed="SEED42", sleep=lambda _: None)
        assert bridge.start_calls == [("ERRATIC", "GOLD", "SEED42")]

    def test_start_упал_даёт_исход_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bridge = ScriptedBridge([_state("BLIND_SELECT")])

        def boom(*_args: object, **_kw: object) -> GameState:
            raise ModBridgeError("start отклонён: BadRequest")

        monkeypatch.setattr(bridge, "start", boom)
        report = play_run(bridge, deck="RED", stake="WHITE", sleep=lambda _: None)
        assert report.outcome == "error"
        assert "BadRequest" in report.note

    def test_none_на_незамкнутой_фазе_это_затык(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # start сразу приводит на BUFFOON_PACK, а решение там ещё не замкнуто.
        monkeypatch.setattr(runner, "decide_action", lambda *_a, **_k: None)
        bridge = ScriptedBridge([_state("BUFFOON_PACK")])
        report = play_run(bridge, deck="RED", stake="WHITE", sleep=lambda _: None)
        assert report.outcome == "stuck"
        assert "BUFFOON_PACK" in report.note
        assert report.decisions[-1].action == "нет решения для фазы BUFFOON_PACK"

    def test_переходную_фазу_пережидает_и_продолжает(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # На HAND_PLAYED decide_action возвращает None, но это не затык:
        # цикл должен переопросить состояние и пойти дальше.
        seen: list[str] = []

        def decide(state: GameState, *, include_discards: bool = True) -> Action | None:
            seen.append(state.phase)
            if state.phase == "HAND_PLAYED":
                return None
            return Action(kind="play", cards=(), indices=())

        monkeypatch.setattr(runner, "decide_action", decide)
        monkeypatch.setattr(runner, "dispatch_action", lambda bridge, action: bridge._advance())
        bridge = ScriptedBridge(
            [
                _state("BLIND_SELECT"),
                _state("HAND_PLAYED"),
                _state("SELECTING_HAND"),
                _state("GAME_OVER"),
            ]
        )
        report = play_run(bridge, deck="RED", stake="WHITE", sleep=lambda _: None)
        assert report.outcome == "lost"
        assert "HAND_PLAYED" in seen

    def test_завис_на_переходной_фазе_это_затык(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Мод отдаёт HAND_PLAYED бесконечно — не крутимся до max_steps, а
        # честно сдаёмся после stall_limit пустых опросов.
        monkeypatch.setattr(runner, "decide_action", lambda *_a, **_k: None)
        bridge = ScriptedBridge([_state("HAND_PLAYED")])
        report = play_run(
            bridge, deck="RED", stake="WHITE", stall_limit=3, max_steps=999, sleep=lambda _: None
        )
        assert report.outcome == "stuck"
        assert "завис на фазе HAND_PLAYED" in report.note

    def test_неменяющееся_состояние_это_затык(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # dispatch отдаёт то же состояние каждый раз — прогресса нет.
        frozen = _state("SELECTING_HAND")
        monkeypatch.setattr(runner, "dispatch_action", lambda *_a, **_k: frozen)
        bridge = ScriptedBridge([frozen])
        report = play_run(bridge, deck="RED", stake="WHITE", stall_limit=3, sleep=lambda _: None)
        assert report.outcome == "stuck"
        assert "не меняется" in report.note

    def test_повторный_отказ_мода_это_затык(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def refuse(*_a: object, **_k: object) -> GameState:
            raise ModBridgeError("нелегальный ход")

        monkeypatch.setattr(runner, "dispatch_action", refuse)
        bridge = ScriptedBridge([_state("SELECTING_HAND")])
        report = play_run(bridge, deck="RED", stake="WHITE", stall_limit=3, sleep=lambda _: None)
        assert report.outcome == "stuck"
        assert all(entry.rejected for entry in report.decisions)
        assert len(report.decisions) == 3

    def test_нажатие_клавиши_обрывает_ран(self) -> None:
        bridge = ScriptedBridge([_state("BLIND_SELECT"), _state("SELECTING_HAND")])
        report = play_run(
            bridge, deck="RED", stake="WHITE", sleep=lambda _: None, key_reader=lambda: "q"
        )
        assert report.outcome == "aborted"
        assert "перехват" in report.note

    def test_потолок_шагов_завершает_ран(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Каждый шаг двигает ленту, но терминального состояния нет.
        loop = [_state("SELECTING_HAND", round_number=n) for n in range(1, 20)]
        bridge = ScriptedBridge(loop)
        report = play_run(bridge, deck="RED", stake="WHITE", max_steps=5, sleep=lambda _: None)
        assert report.outcome == "stuck"
        assert "предел шагов (5)" in report.note

    def test_on_step_вызывается_на_каждое_решение(self) -> None:
        bridge = ScriptedBridge(
            [_state("BLIND_SELECT"), _state("SELECTING_HAND"), _state("GAME_OVER")]
        )
        steps: list[int] = []
        play_run(
            bridge,
            deck="RED",
            stake="WHITE",
            sleep=lambda _: None,
            on_step=lambda state, entry: steps.append(entry.step),
        )
        assert steps == [1, 2]


class TestRunBatch:
    """`run_batch` — обвязка поверх `play_run`; сам `play_run` здесь
    подменён, проверяется только раскладка «ставка × ран» и остановка на
    прерывании."""

    def test_прогон_по_ставкам_и_ранам(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def fake_run(bridge: ModBridge, *, stake: str, **_kw: object) -> runner.RunReport:
            calls.append(stake)
            return runner.RunReport("RED", stake, None, "won", 8, 3, 10)

        monkeypatch.setattr(runner, "play_run", fake_run)
        summaries = run_batch(ModBridge(), deck="RED", stakes=("WHITE", "RED"), runs_per_stake=3)

        assert [s.stake for s in summaries] == ["WHITE", "RED"]
        assert all(s.runs == 3 for s in summaries)
        assert calls == ["WHITE", "WHITE", "WHITE", "RED", "RED", "RED"]

    def test_прерывание_останавливает_весь_пакет(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(bridge: ModBridge, *, stake: str, **_kw: object) -> runner.RunReport:
            return runner.RunReport("RED", stake, None, "aborted", 2, 1, 1)

        monkeypatch.setattr(runner, "play_run", fake_run)
        summaries = run_batch(
            ModBridge(), deck="RED", stakes=("WHITE", "RED", "GREEN"), runs_per_stake=5
        )

        assert len(summaries) == 1
        assert summaries[0].runs == 1

    def test_ctrl_c_сохраняет_уже_собранное(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # KeyboardInterrupt на третьем ране не должен терять два готовых.
        done = 0

        def fake_run(bridge: ModBridge, *, stake: str, **_kw: object) -> runner.RunReport:
            nonlocal done
            done += 1
            if done == 3:
                raise KeyboardInterrupt
            return runner.RunReport("RED", stake, None, "won", 8, 3, 10)

        monkeypatch.setattr(runner, "play_run", fake_run)
        summaries = run_batch(ModBridge(), deck="RED", stakes=("WHITE",), runs_per_stake=10)

        assert len(summaries) == 1
        assert summaries[0].runs == 2  # два успели до Ctrl+C
        assert summaries[0].wins == 2


class TestStakeSummary:
    def test_винрейт_и_средняя_анте(self) -> None:
        reports = (
            runner.RunReport("RED", "WHITE", None, "won", 8, 3, 100),
            runner.RunReport("RED", "WHITE", None, "lost", 4, 2, 60),
            runner.RunReport("RED", "WHITE", None, "lost", 6, 1, 80),
        )
        summary = StakeSummary("WHITE", reports)
        assert summary.runs == 3
        assert summary.wins == 1
        assert summary.win_rate == pytest.approx(1 / 3)
        assert summary.mean_ante == pytest.approx(6.0)
        assert summary.best_ante == 8

    def test_пустая_сводка_не_делит_на_ноль(self) -> None:
        summary = StakeSummary("WHITE")
        assert summary.win_rate == 0.0
        assert summary.mean_ante == 0.0


class TestРендер:
    def test_отчёт_о_ране_показывает_исход_и_лог(self, capsys: pytest.CaptureFixture[str]) -> None:
        report = runner.RunReport(
            "RED",
            "GOLD",
            "SEED1",
            "lost",
            5,
            2,
            2,
            decisions=(
                runner.DecisionEntry(1, "BLIND_SELECT", 5, 2, 12, "выбрал блайнд — играет"),
                runner.DecisionEntry(2, "SELECTING_HAND", 5, 2, 12, "сыграл AH KS"),
            ),
            note="проигрыш",
        )
        runner.render_run_report(report)
        out = capsys.readouterr().out
        assert "RED / GOLD" in out
        assert "поражение" in out
        assert "сыграл AH KS" in out

    def test_сводка_пакета_таблицей(self, capsys: pytest.CaptureFixture[str]) -> None:
        summaries = [
            StakeSummary(
                "WHITE",
                (runner.RunReport("RED", "WHITE", None, "won", 8, 3, 100),),
            ),
            StakeSummary(
                "RED",
                (runner.RunReport("RED", "RED", None, "lost", 5, 2, 60),),
            ),
        ]
        runner.render_batch_summary(summaries)
        out = capsys.readouterr().out
        assert "винрейт по ставкам" in out
        assert "WHITE" in out and "RED" in out
        assert "100%" in out
