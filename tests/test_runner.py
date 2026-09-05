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

import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from balatro_bot import runner
from balatro_bot.adapters.mod_bridge import ModBridge, ModBridgeError
from balatro_bot.autopilot import Action, BoardEntry
from balatro_bot.core.state import BlindInfo, GameState, JokerCard
from balatro_bot.runner import DecisionEntry, RunReport, StakeSummary, play_run, run_batch


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
        # decide_action не знает, что делать на этой фазе — ран честно
        # фиксирует затык с именем фазы, а не гадает.
        monkeypatch.setattr(runner, "decide_action", lambda *_a, **_k: None)
        bridge = ScriptedBridge([_state("SOME_NEW_PHASE")])
        report = play_run(bridge, deck="RED", stake="WHITE", sleep=lambda _: None)
        assert report.outcome == "stuck"
        assert "SOME_NEW_PHASE" in report.note
        assert report.decisions[-1].action == "нет решения для фазы SOME_NEW_PHASE"

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


@pytest.mark.usefixtures("patch_engine")
class TestПодхватИдущегоРана:
    """E2, первый срез. Раньше `play_run` всегда открывался парой
    `menu()` + `start()` и затирал забег, который человек только что настроил
    сам, — а это как раз обычный случай: игру запускают руками, автопилот
    подключают к ней."""

    def test_подхватывает_и_не_трогает_меню(self) -> None:
        bridge = ScriptedBridge(
            [
                _state("SELECTING_HAND", ante=3),
                _state("SELECTING_HAND", ante=3),
                _state("GAME_OVER", ante=5),
            ]
        )
        report = play_run(bridge, deck="RED", stake="WHITE", adopt=True, sleep=lambda _: None)
        assert bridge.menu_calls == 0
        assert bridge.start_calls == []
        assert report.adopted is True
        assert report.outcome == "lost"
        assert report.ante == 5

    def test_из_меню_начинает_свой_ран(self) -> None:
        bridge = ScriptedBridge(
            [_state("MENU"), _state("SELECTING_HAND"), _state("GAME_OVER", ante=2)]
        )
        report = play_run(bridge, deck="RED", stake="WHITE", adopt=True, sleep=lambda _: None)
        assert bridge.menu_calls == 1
        assert bridge.start_calls == [("RED", "WHITE", None)]
        assert report.adopted is False

    def test_с_экрана_проигрыша_тоже_начинает_свой(self) -> None:
        bridge = ScriptedBridge(
            [_state("GAME_OVER"), _state("SELECTING_HAND"), _state("GAME_OVER", ante=2)]
        )
        report = play_run(bridge, deck="RED", stake="WHITE", adopt=True, sleep=lambda _: None)
        assert bridge.start_calls == [("RED", "WHITE", None)]
        assert report.adopted is False

    def test_без_флага_прежнее_поведение(self) -> None:
        # Старое поведение закреплено: без `adopt` идущий ран по-прежнему
        # затирается — чтобы это не «уехало» само собой.
        bridge = ScriptedBridge([_state("SELECTING_HAND", ante=3), _state("GAME_OVER", ante=3)])
        report = play_run(bridge, deck="RED", stake="WHITE", sleep=lambda _: None)
        assert bridge.menu_calls == 1
        assert bridge.start_calls == [("RED", "WHITE", None)]
        assert report.adopted is False

    def test_колода_подхваченного_рана_берётся_из_состояния(self) -> None:
        # Колоду игра сообщает сама, и она может не совпасть с флагом;
        # ставку игра не присылает вовсе, поэтому она остаётся заявленной,
        # а `adopted` предупреждает, что это не наблюдение.
        bridge = ScriptedBridge(
            [
                replace(_state("SELECTING_HAND"), deck_type="GREEN"),
                _state("GAME_OVER"),
            ]
        )
        report = play_run(bridge, deck="RED", stake="GOLD", adopt=True, sleep=lambda _: None)
        assert report.deck == "GREEN"
        assert report.stake == "GOLD"
        assert report.adopted is True

    def test_в_пакете_подхватывает_только_первый(self) -> None:
        bridge = ScriptedBridge([_state("SELECTING_HAND"), _state("GAME_OVER")] * 6)
        summaries = run_batch(
            bridge,
            deck="RED",
            stakes=("WHITE",),
            runs_per_stake=3,
            adopt_first=True,
            sleep=lambda _: None,
        )
        reports = summaries[0].reports
        assert [report.adopted for report in reports] == [True, False, False]
        # Первый ран не звал start, остальные два — звали.
        assert len(bridge.start_calls) == 2


@pytest.mark.usefixtures("patch_engine")
class TestЖурналРана:
    """Улучшение E1a: запись решения должна быть разбираемой без живого
    терминала. Раньше в ней были только шаг/фаза/анте/раунд/деньги/действие,
    и ран, за которым никто не смотрел, разобрать было нечем — а батч E1
    именно из таких ранов и состоит."""

    def _bridge(self) -> ScriptedBridge:
        blind = BlindInfo(
            kind="SMALL", name="Small Blind", effect="", required_score=300, status="CURRENT"
        )
        играем = replace(
            _state("SELECTING_HAND"),
            chips_scored=120,
            hands_left=3,
            discards_left=2,
            money=17,
            jokers=(JokerCard(key="j_joker", label="Joker"),),
            blinds={"small": blind},
        )
        return ScriptedBridge([играем, _state("GAME_OVER")])

    def test_запись_несёт_положение_а_не_только_действие(self) -> None:
        report = play_run(self._bridge(), deck="RED", stake="WHITE")
        entry = report.decisions[0]
        assert entry.chips_scored == 120
        assert entry.requirement == 300
        assert entry.hands_left == 3
        assert entry.discards_left == 2
        assert entry.jokers == ("Joker",)

    def test_повод_берётся_из_решения(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def решение(state: GameState, *, include_discards: bool = True) -> Action:
            return Action(kind="play", reason="прирост 900 ≥ порога 9")

        monkeypatch.setattr(runner, "decide_action", решение)
        report = play_run(self._bridge(), deck="RED", stake="WHITE")
        assert report.decisions[0].reason == "прирост 900 ≥ порога 9"

    def test_запись_без_действия_остаётся_без_повода(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Затык: решения нет вовсе, значит и обосновывать нечего — поле
        # обязано быть пустым, а не унаследовать чужой текст.
        monkeypatch.setattr(runner, "decide_action", lambda state, **kw: None)
        report = play_run(self._bridge(), deck="RED", stake="WHITE")
        assert report.outcome == "stuck"
        assert report.decisions[-1].reason == ""

    def test_журнал_пишется_в_файл_и_читается_обратно(self, tmp_path: Path) -> None:
        report = play_run(self._bridge(), deck="RED", stake="WHITE", log_dir=tmp_path)
        (файл,) = list(tmp_path.glob("*.json"))
        данные = json.loads(файл.read_text(encoding="utf-8"))
        assert данные["deck"] == "RED"
        assert данные["outcome"] == report.outcome
        assert len(данные["decisions"]) == len(report.decisions)
        шаг = данные["decisions"][0]
        assert шаг["chips_scored"] == 120
        assert шаг["requirement"] == 300
        assert шаг["jokers"] == ["Joker"]

    def test_ставка_подхваченного_рана_не_наблюдаема(self, tmp_path: Path) -> None:
        # Мод ставку не присылает вовсе (см. `RunReport.adopted`), поэтому у
        # подхваченного рана она — то, что попросили флагом, не наблюдение.
        play_run(self._bridge(), deck="RED", stake="WHITE", adopt=True, log_dir=tmp_path)
        (файл,) = list(tmp_path.glob("*.json"))
        assert json.loads(файл.read_text(encoding="utf-8"))["stake_observed"] is False

    def test_ставка_начатого_раннером_рана_известна_точно(self, tmp_path: Path) -> None:
        # А вот когда ран начал сам раннер, он ставку и передал в `start` —
        # тут она известна точно, и помечать её неизвестной значило бы
        # выбрасывать знание, которое у нас есть.
        play_run(self._bridge(), deck="RED", stake="GOLD", log_dir=tmp_path)
        (файл,) = list(tmp_path.glob("*.json"))
        данные = json.loads(файл.read_text(encoding="utf-8"))
        assert данные["stake_observed"] is True
        assert данные["stake"] == "GOLD"

    def test_без_каталога_ничего_не_пишется(self, tmp_path: Path) -> None:
        play_run(self._bridge(), deck="RED", stake="WHITE")
        assert list(tmp_path.iterdir()) == []

    def test_аварийный_исход_тоже_попадает_в_журнал(self, tmp_path: Path) -> None:
        # Ради таких ранов журнал и заводился: упавший должен оставить след.
        monkeypatch_bridge = ScriptedBridge([_state("MENU")])
        play_run(monkeypatch_bridge, deck="RED", stake="WHITE", log_dir=tmp_path)
        (файл,) = list(tmp_path.glob("*.json"))
        assert json.loads(файл.read_text(encoding="utf-8"))["outcome"] == "stuck"


class FlakyBridge(ScriptedBridge):
    """Мост, который отваливается на первых `сбоев` опросах, а потом чинится.

    `сбоев=None` — не чинится никогда (игра действительно умерла)."""

    def __init__(self, timeline: Sequence[GameState], сбоев: int | None) -> None:
        super().__init__(timeline)
        self.осталось_сбоев = сбоев
        self.опросов = 0

    def _проверить(self) -> None:
        """Мёртвый мост не отвечает ни на что — не только на `game_state`."""
        if self.осталось_сбоев is None:
            raise ModBridgeError("мост мёртв")

    def game_state(self) -> GameState:
        self.опросов += 1
        self._проверить()
        if self.осталось_сбоев is not None and self.осталось_сбоев > 0:
            self.осталось_сбоев -= 1
            raise ModBridgeError("мост временно недоступен")
        return super().game_state()

    def menu(self) -> GameState:
        self._проверить()
        return super().menu()

    def start(self, deck: str, stake: str, *, seed: str | None = None) -> GameState:
        self._проверить()
        return super().start(deck, stake, seed=seed)


@pytest.mark.usefixtures("patch_engine")
class TestПереподключение:
    """Вторая половина улучшения E2. Раньше **любой** обрыв моста заканчивал
    ран исходом `error`, хотя мост отваливается и когда игра просто занята
    анимацией или свёрнута. Перезапуском упавшей игры watchdog намеренно не
    занимается: игру поднимает человек, и забег выбирает тоже он."""

    def test_короткий_обрыв_при_старте_переживается(self) -> None:
        bridge = FlakyBridge([_state("SELECTING_HAND"), _state("GAME_OVER")], сбоев=2)
        report = play_run(bridge, deck="RED", stake="WHITE", adopt=True, sleep=lambda _: None)
        assert report.outcome != "error"

    def test_мёртвый_мост_всё_равно_даёт_error(self) -> None:
        bridge = FlakyBridge([_state("SELECTING_HAND")], сбоев=None)
        report = play_run(bridge, deck="RED", stake="WHITE", adopt=True, sleep=lambda _: None)
        assert report.outcome == "error"
        assert "не вернулся" in report.note

    def test_обрыв_при_действии_не_считается_затыком(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Мод, отказавший в действии, и исчезнувший мост приходят одним
        # исключением, но лечатся по-разному: первое — затык, второе — ожидание.
        bridge = FlakyBridge([_state("SELECTING_HAND"), _state("GAME_OVER")], сбоев=0)
        падений = {"осталось": 1}

        def dispatch(_bridge: ModBridge, action: Action) -> GameState:
            if падений["осталось"]:
                падений["осталось"] -= 1
                bridge.осталось_сбоев = 1  # мост в этот момент действительно лежит
                raise ModBridgeError("соединение разорвано")
            return bridge._advance()

        monkeypatch.setattr(runner, "dispatch_action", dispatch)
        report = play_run(bridge, deck="RED", stake="WHITE", sleep=lambda _: None)
        assert report.outcome != "error"
        assert any("связь восстановлена" in entry.action for entry in report.decisions)
        # Восстановление — это не отказ мода, помечать запись отказом нельзя.
        assert not any(entry.rejected for entry in report.decisions)

    def test_отказ_мода_при_живом_мосте_остаётся_затыком(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bridge = ScriptedBridge([_state("SELECTING_HAND")])

        def dispatch(_bridge: ModBridge, action: Action) -> GameState:
            raise ModBridgeError("нельзя продать вечного джокера")

        monkeypatch.setattr(runner, "dispatch_action", dispatch)
        report = play_run(bridge, deck="RED", stake="WHITE", stall_limit=2, sleep=lambda _: None)
        assert report.outcome == "stuck"
        assert any(entry.rejected for entry in report.decisions)


@pytest.mark.usefixtures("patch_engine")
class TestПакетНеЖжётРаны:
    """Раньше `run_batch` на мёртвом мосте не останавливался: он дописывал
    отчёт с исходом `error` и начинал следующий ран, прогоняя все оставшиеся
    за секунды. Полсотни таких отчётов — не данные."""

    def test_мёртвый_мост_обрывает_пакет(self) -> None:
        bridge = FlakyBridge([_state("SELECTING_HAND")], сбоев=None)
        summaries = run_batch(
            bridge,
            deck="RED",
            stakes=("WHITE",),
            runs_per_stake=5,
            sleep=lambda _: None,
        )
        (сводка,) = summaries
        assert сводка.runs == 1  # а не 5

    def test_живой_мост_пакет_не_обрывает(self) -> None:
        bridge = ScriptedBridge([_state("GAME_OVER")])
        summaries = run_batch(
            bridge,
            deck="RED",
            stakes=("WHITE",),
            runs_per_stake=3,
            sleep=lambda _: None,
        )
        (сводка,) = summaries
        assert сводка.runs == 3


@pytest.mark.usefixtures("patch_engine")
class TestСчётчикиСбросов:
    """Ран ZODIAC проиграл, не сбросив ни разу с анте 3 и закрыв так десять
    раундов подряд, — и заметил это человек, читая сто строк журнала руками.
    Отчёт обязан называть такой симптом сам."""

    def _report(self, *действия: tuple[str, str, int]) -> RunReport:
        решения = tuple(
            DecisionEntry(
                step=i + 1,
                phase=фаза,
                ante=1,
                round_number=1,
                money=0,
                action=действие,
                discards_left=сбросов,
            )
            for i, (фаза, действие, сбросов) in enumerate(действия)
        )
        return RunReport("RED", "WHITE", None, "lost", 1, 1, len(решения), решения)

    def test_считает_розыгрыши_и_сбросы(self) -> None:
        отчёт = self._report(
            ("SELECTING_HAND", "сбросил AH KH", 3),
            ("SELECTING_HAND", "сыграл QH JH", 2),
            ("SELECTING_HAND", "сыграл 9H", 2),
        )
        assert отчёт.discards_used == 1
        assert отчёт.plays_made == 2

    def test_раунд_без_единого_сброса_замечен(self) -> None:
        отчёт = self._report(
            ("SELECTING_HAND", "сыграл QH JH", 3),
            ("SELECTING_HAND", "сыграл 9H", 3),
            ("ROUND_EVAL", "забрал награду за раунд", 3),
        )
        assert отчёт.rounds_with_discards_unspent == 1

    def test_раунд_со_сбросом_не_считается(self) -> None:
        отчёт = self._report(
            ("SELECTING_HAND", "сбросил AH", 3),
            ("SELECTING_HAND", "сыграл QH JH", 2),
            ("ROUND_EVAL", "забрал награду за раунд", 2),
        )
        assert отчёт.rounds_with_discards_unspent == 0

    def test_раунд_без_доступных_сбросов_не_считается(self) -> None:
        # Не сбросил, потому что было нечем, — это не симптом.
        отчёт = self._report(
            ("SELECTING_HAND", "сыграл QH JH", 0),
            ("ROUND_EVAL", "забрал награду за раунд", 0),
        )
        assert отчёт.rounds_with_discards_unspent == 0

    def test_счётчики_попадают_в_журнал(self, tmp_path: Path) -> None:
        bridge = ScriptedBridge([_state("SELECTING_HAND"), _state("GAME_OVER")])
        play_run(bridge, deck="RED", stake="WHITE", log_dir=tmp_path)
        (файл,) = list(tmp_path.glob("*.json"))
        данные = json.loads(файл.read_text(encoding="utf-8"))
        assert "discards_used" in данные
        assert "rounds_with_discards_unspent" in данные


@pytest.mark.usefixtures("patch_engine")
class TestСнимкаДоскиВЖурнале:
    """Улучшение E1b: вклады джокеров должны доезжать до файла, иначе они
    так же бесполезны, как когда их не считали вовсе."""

    def _bridge(self) -> ScriptedBridge:
        return ScriptedBridge([_state("SELECTING_HAND"), _state("GAME_OVER")])

    def test_запись_копирует_снимок_из_решения(self, monkeypatch: pytest.MonkeyPatch) -> None:
        доска = (
            BoardEntry(label="Joker Stencil", contribution=1200.0, sell_value=4),
            BoardEntry(label="Hit the Road", contribution=-722.0, sell_value=3),
        )

        def решение(state: GameState, *, include_discards: bool = True) -> Action:
            return Action(kind="play", board=доска)

        monkeypatch.setattr(runner, "decide_action", решение)
        report = play_run(self._bridge(), deck="RED", stake="WHITE")
        assert report.decisions[0].board == доска

    def test_журнал_везёт_вклады_в_файл(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def решение(state: GameState, *, include_discards: bool = True) -> Action:
            return Action(
                kind="play",
                board=(BoardEntry(label="Hit the Road", contribution=-722.0, sell_value=3),),
            )

        monkeypatch.setattr(runner, "decide_action", решение)
        play_run(self._bridge(), deck="RED", stake="WHITE", log_dir=tmp_path)
        (файл,) = list(tmp_path.glob("*.json"))
        шаг = json.loads(файл.read_text(encoding="utf-8"))["decisions"][0]
        assert шаг["board"] == [{"label": "Hit the Road", "contribution": -722.0, "sell_value": 3}]

    def test_без_магазина_поле_есть_но_пусто(self, tmp_path: Path) -> None:
        # Поле должно присутствовать всегда: отсутствующий ключ и пустой
        # список — разные вещи для того, кто потом разбирает журнал.
        play_run(self._bridge(), deck="RED", stake="WHITE", log_dir=tmp_path)
        (файл,) = list(tmp_path.glob("*.json"))
        for шаг in json.loads(файл.read_text(encoding="utf-8"))["decisions"]:
            assert шаг["board"] == []
