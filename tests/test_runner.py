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

import http.client
import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from balatro_bot import runner
from balatro_bot.adapters.mod_bridge import ModBridge, ModBridgeError, TimedOutError
from balatro_bot.autopilot import Action, BoardEntry, HandOutlook
from balatro_bot.core.state import BlindInfo, GameState, JokerCard, ShopItem
from balatro_bot.runner import (
    DecisionEntry,
    PackCard,
    RunReport,
    StakeSummary,
    play_run,
    run_batch,
)


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


@pytest.mark.usefixtures("patch_engine")
class TestСидыПакета:
    """Улучшение E1c. Игра берёт сид из положения курсора мыши
    (`generate_starting_seed` в `functions/misc_functions.lua`), а при
    автоигре мышь не двигается — все раны пакета выходили одной и той же
    партией. Три первых рана совпали до последней цифры, и это вскрыло
    дефект: винрейт по N ранам был одним раном, посчитанным N раз."""

    def _bridge(self) -> ScriptedBridge:
        return ScriptedBridge([_state("GAME_OVER")])

    def test_без_сида_каждый_ран_получает_свой(self) -> None:
        bridge = self._bridge()
        run_batch(bridge, deck="RED", stakes=("WHITE",), runs_per_stake=5, sleep=lambda _: None)
        сиды = [сид for _, _, сид in bridge.start_calls]
        assert len(сиды) == 5
        assert all(сид is not None for сид in сиды)
        assert len(set(сиды)) == 5, сиды

    def test_явный_сид_повторяется_намеренно(self) -> None:
        # Заданный сид означает «N одинаковых ранов» — это регрессионный
        # прогон, и подменять его случайным нельзя.
        bridge = self._bridge()
        run_batch(
            bridge,
            deck="RED",
            stakes=("WHITE",),
            runs_per_stake=3,
            seed="ABCD1234",
            sleep=lambda _: None,
        )
        assert [сид for _, _, сид in bridge.start_calls] == ["ABCD1234"] * 3

    def test_сид_в_алфавите_игры(self) -> None:
        # Игра принимает только 1–9 и A–N, P–Z: ноль и O исключены ею самой.
        bridge = self._bridge()
        run_batch(bridge, deck="RED", stakes=("WHITE",), runs_per_stake=6, sleep=lambda _: None)
        for _, _, сид in bridge.start_calls:
            assert сид is not None
            assert len(сид) == 8, сид
            assert set(сид) <= set("123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"), сид


@pytest.mark.usefixtures("patch_engine")
class TestСнимкаВыбораВЖурнале:
    """E1d: оба числа должны доезжать до файла, иначе они бесполезны так же,
    как когда их не записывали."""

    def _bridge(self) -> ScriptedBridge:
        return ScriptedBridge([_state("SELECTING_HAND"), _state("ROUND_EVAL"), _state("GAME_OVER")])

    def test_журнал_везёт_оба_числа(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        обзор = HandOutlook(best_play=1200.0, best_discard=1450.0, discards_left=2)

        def решение(state: GameState, *, include_discards: bool = True) -> Action:
            return Action(kind="play", outlook=обзор)

        monkeypatch.setattr(runner, "decide_action", решение)
        play_run(self._bridge(), deck="RED", stake="WHITE", log_dir=tmp_path)
        (файл,) = list(tmp_path.glob("*.json"))
        шаг = json.loads(файл.read_text(encoding="utf-8"))["decisions"][0]
        assert шаг["outlook"] == {
            "best_play": 1200.0,
            "best_discard": 1450.0,
            "discards_left": 2,
        }

    def test_непосчитанный_сброс_остаётся_null(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # `null`, а не 0: «не считали» и «нечего сбрасывать» — разные вещи.
        def решение(state: GameState, *, include_discards: bool = True) -> Action:
            return Action(
                kind="play",
                outlook=HandOutlook(best_play=900.0, best_discard=None, discards_left=3),
            )

        monkeypatch.setattr(runner, "decide_action", решение)
        play_run(self._bridge(), deck="RED", stake="WHITE", log_dir=tmp_path)
        (файл,) = list(tmp_path.glob("*.json"))
        шаг = json.loads(файл.read_text(encoding="utf-8"))["decisions"][0]
        assert шаг["outlook"]["best_discard"] is None

    def test_закрывающая_раунд_запись_помечена(self, tmp_path: Path) -> None:
        # Очки последнего розыгрыша в журнал не попадают (запись собирается
        # до действия), поэтому итог раунда надо брать отсюда, а не из
        # `chips_scored` — на чём один разбор уже поехал.
        play_run(self._bridge(), deck="RED", stake="WHITE", log_dir=tmp_path)
        (файл,) = list(tmp_path.glob("*.json"))
        шаги = json.loads(файл.read_text(encoding="utf-8"))["decisions"]
        взятые = [ш for ш in шаги if ш["blind_beaten"]]
        assert взятые, "ни одна запись не помечена как закрывшая раунд"
        assert all(ш["phase"] == "ROUND_EVAL" for ш in взятые)
        assert all(ш["blind_beaten"] is None for ш in шаги if ш["phase"] != "ROUND_EVAL")


@pytest.mark.usefixtures("patch_engine")
class TestПаузаПередПовтором:
    """Улучшение A19. Отказ мода часто означает не «нельзя», а «ещё не
    готово»: `endpoints/select.lua` требует фазы `BLIND_SELECT` и непустого
    `blind_on_deck`, а игра в этот момент доигрывает переход. Раннер
    повторял немедленно и за секунду исчерпывал `stall_limit`.

    В большом батче ран так и умер: бот скипнул блайнд и трижды подряд
    получил отказ на выборе следующего, пока шла анимация скипа."""

    def test_отказ_переживается_если_состояние_устаканилось(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bridge = ScriptedBridge([_state("BLIND_SELECT"), _state("BLIND_SELECT")])
        отказов = {"осталось": 2}

        def dispatch(_b: ModBridge, action: Action) -> GameState:
            if отказов["осталось"]:
                отказов["осталось"] -= 1
                raise ModBridgeError("[-32002] игра ещё не готова")
            return _state("GAME_OVER")

        monkeypatch.setattr(runner, "dispatch_action", dispatch)
        паузы: list[float] = []
        report = play_run(bridge, deck="RED", stake="WHITE", stall_limit=3, sleep=паузы.append)

        # Два отказа пережиты: ран не умер с «мод отказал», а дошёл до конца.
        assert "отказал" not in report.note, report.note
        assert report.outcome == "lost"
        # И между попытками действительно была пауза — иначе повтор бьётся в
        # ту же дверь в пределах одной анимации.
        assert len(паузы) >= 2, паузы

    def test_настоящий_отказ_всё_ещё_даёт_затык(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Пауза не должна превращать неисполнимое действие в вечный цикл.
        bridge = ScriptedBridge([_state("BLIND_SELECT")])

        def dispatch(_b: ModBridge, action: Action) -> GameState:
            raise ModBridgeError("нельзя продать вечного джокера")

        monkeypatch.setattr(runner, "dispatch_action", dispatch)
        report = play_run(bridge, deck="RED", stake="WHITE", stall_limit=3, sleep=lambda _: None)
        assert report.outcome == "stuck"
        assert "отказал" in report.note


@pytest.mark.usefixtures("patch_engine")
class TestСнимкаПакаВЖурнале:
    """Улучшение E1f: содержимое открытого пака и предлагаемый тег.

    Оба поля читаются из состояния, а не привозятся на `Action`, — и
    проверяется здесь именно это: снимок обязан быть и на записи, до
    которой `Action` не доживает (отказ мода). Все четыре отказа корпуса —
    в паках, ради них поле и заводилось."""

    def _пак(self, *карты: tuple[str, str]) -> GameState:
        return replace(
            _state("SMODS_BOOSTER_OPENED"),
            pack=tuple(
                ShopItem(key=f"c_{label}", label=label, kind=kind, price=0) for label, kind in карты
            ),
        )

    def test_содержимое_пака_попадает_в_запись(self) -> None:
        bridge = ScriptedBridge([self._пак(("Uranus", "PLANET")), _state("GAME_OVER")])
        report = play_run(bridge, deck="RED", stake="WHITE")
        assert report.decisions[0].pack == (PackCard(label="Uranus", kind="PLANET"),)

    def test_снимок_есть_и_на_отказе_мода(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Ровно тот случай, ради которого поле читается из состояния:
        # решения нет, а знать, что бот видел в паке, необходимо.
        def refuse(*_a: object, **_k: object) -> GameState:
            raise ModBridgeError("Card index out of range. Index: 3, Available cards: 0")

        monkeypatch.setattr(runner, "dispatch_action", refuse)
        bridge = ScriptedBridge([self._пак(("Smiley Face", "JOKER"))])
        report = play_run(bridge, deck="RED", stake="WHITE", stall_limit=2, sleep=lambda _: None)
        отказ = report.decisions[0]
        assert отказ.rejected
        assert отказ.pack == (PackCard(label="Smiley Face", kind="JOKER"),)

    def test_пак_пуст_вне_вскрытия(self) -> None:
        bridge = ScriptedBridge([_state("SELECTING_HAND"), _state("GAME_OVER")])
        report = play_run(bridge, deck="RED", stake="WHITE")
        assert report.decisions[0].pack == ()

    def test_тег_берётся_у_выбираемого_блайнда(self) -> None:
        state = replace(
            _state("BLIND_SELECT"),
            blinds={
                "small": BlindInfo(
                    kind="SMALL",
                    name="Small Blind",
                    effect="",
                    required_score=300,
                    status="SKIPPED",
                    tag_name="D6 Tag",
                ),
                "big": BlindInfo(
                    kind="BIG",
                    name="Big Blind",
                    effect="",
                    required_score=450,
                    status="SELECT",
                    tag_name="Meteor Tag",
                ),
            },
        )
        bridge = ScriptedBridge([state, _state("GAME_OVER")])
        report = play_run(bridge, deck="RED", stake="WHITE")
        # Скипнутый Small уже не предлагается — берётся тег того, кто SELECT.
        assert report.decisions[0].offered_tag == "Meteor Tag"

    def test_у_босса_тега_не_бывает(self) -> None:
        # У боссового блайнда `SELECT` значит «играть», а не «можно скипнуть»:
        # тот же отказ, что в `solver.skip.evaluate_skip`.
        state = replace(
            _state("BLIND_SELECT"),
            blinds={
                "boss": BlindInfo(
                    kind="BOSS",
                    name="The Wall",
                    effect="",
                    required_score=900,
                    status="SELECT",
                    tag_name="Meteor Tag",
                )
            },
        )
        bridge = ScriptedBridge([state, _state("GAME_OVER")])
        report = play_run(bridge, deck="RED", stake="WHITE")
        assert report.decisions[0].offered_tag == ""

    def test_оба_поля_доезжают_до_файла(self, tmp_path: Path) -> None:
        bridge = ScriptedBridge([self._пак(("Uranus", "PLANET")), _state("GAME_OVER")])
        play_run(bridge, deck="RED", stake="WHITE", log_dir=tmp_path)
        (файл,) = list(tmp_path.glob("*.json"))
        шаг = json.loads(файл.read_text(encoding="utf-8"))["decisions"][0]
        assert шаг["pack"] == [{"label": "Uranus", "kind": "PLANET"}]
        assert шаг["offered_tag"] == ""


class TestПереспросПослеСкипа:
    """C3: после `skip`/`next_round`/`buy_pack` состояние из ответа мода
    брать нельзя — игра в этот момент может открывать пак сама. Раньше
    именно оно становилось основанием следующего решения, и бот решал по
    снимку, которого в игре уже не было."""

    def _decide(self, seen: list[int]) -> Callable[..., Action]:
        def решение(state: GameState, *, include_discards: bool = True) -> Action:
            seen.append(state.ante)
            return Action(kind="skip" if state.phase == "BLIND_SELECT" else "play")

        return решение

    def _dispatch(self, bridge: ModBridge, action: Action) -> GameState:
        assert isinstance(bridge, ScriptedBridge)
        bridge.actions.append(action)
        return bridge._advance()

    def test_после_скипа_состояние_перечитывается(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[int] = []
        monkeypatch.setattr(runner, "decide_action", self._decide(seen))
        monkeypatch.setattr(runner, "dispatch_action", self._dispatch)
        bridge = ScriptedBridge(
            [
                _state("BLIND_SELECT"),
                _state("SELECTING_HAND", ante=2),  # ответ мода на сам скип
                _state("SELECTING_HAND", ante=3),  # что игра отдаёт, когда устаканилась
                _state("GAME_OVER"),
            ]
        )
        паузы: list[float] = []
        play_run(bridge, deck="RED", stake="WHITE", sleep=паузы.append)

        # Решение после скипа принято по перечитанному состоянию (3), а не
        # по тому, что вернул сам вызов (2).
        assert 3 in seen, seen
        assert 2 not in seen, seen
        assert паузы, "переспрос должен идти после паузы, иначе он попадёт в ту же анимацию"

    def test_после_обычного_хода_не_перечитывается(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Переспрос стоит целого опроса мода: вешать его на каждый ход
        # значило бы удвоить бюджет опросов там, где пак открыться не может.
        seen: list[int] = []
        monkeypatch.setattr(runner, "decide_action", self._decide(seen))
        monkeypatch.setattr(runner, "dispatch_action", self._dispatch)
        bridge = ScriptedBridge(
            [
                _state("SELECTING_HAND"),
                _state("SELECTING_HAND", ante=2),
                _state("SELECTING_HAND", ante=3),
                _state("GAME_OVER"),
            ]
        )
        play_run(bridge, deck="RED", stake="WHITE", sleep=lambda _: None)
        assert 2 in seen, seen

    def test_неудавшийся_переспрос_не_ломает_ран(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[int] = []

        class МостБезОпроса(ScriptedBridge):
            def game_state(self) -> GameState:
                raise ModBridgeError("мод занят анимацией")

        monkeypatch.setattr(runner, "decide_action", self._decide(seen))
        monkeypatch.setattr(runner, "dispatch_action", self._dispatch)
        bridge = МостБезОпроса(
            [_state("BLIND_SELECT"), _state("SELECTING_HAND", ante=2), _state("GAME_OVER")]
        )
        report = play_run(bridge, deck="RED", stake="WHITE", sleep=lambda _: None)

        # Опрос не удался — работаем по тому, что вернул сам вызов.
        assert report.outcome == "lost"
        assert seen == [1, 2], seen


class TestОжиданиеЗаполненияПака:
    """C3, аварийная половина: пустой пак — это «карты ещё не приехали», и
    ждать их надо дольше обычной анимации.

    Раньше `decide_action` отдавал на пустом паке `skip_pack`, мод исполнял
    его как `G.FUNCS.skip_booster`, тот обнулял `booster_obj`, и отложенное
    событие создания карт роняло ПРОЦЕСС игры. Теперь решение — `None`, а
    раннер обязан переждать; бюджет тут свой (`_PACK_FILL_POLLS`), потому что
    обычных трёх опросов (0.75 с) не хватает на игровые ~1.3 с."""

    _ПАК = "SMODS_BOOSTER_OPENED"

    def _полный_пак(self) -> GameState:
        return replace(
            _state(self._ПАК),
            pack=(ShopItem(key="c_mars", label="Mars", kind="PLANET", price=0),),
        )

    def test_пустой_пак_пережидается_и_карта_берётся(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Лента: пустой пак, потом заполненный. Раннер должен дождаться
        # второго, а не решить по первому.
        видел: list[int] = []

        def решение(state: GameState, *, include_discards: bool = True) -> Action | None:
            видел.append(len(state.pack))
            if state.phase == self._ПАК and not state.pack:
                return None
            return Action(kind="pack", item_index=0, label="Mars")

        monkeypatch.setattr(runner, "decide_action", решение)
        monkeypatch.setattr(runner, "dispatch_action", lambda bridge, action: bridge._advance())
        bridge = ScriptedBridge([_state(self._ПАК), self._полный_пак(), _state("GAME_OVER")])
        паузы: list[float] = []
        report = play_run(bridge, deck="RED", stake="WHITE", sleep=паузы.append)

        assert report.outcome == "lost"
        assert 0 in видел and 1 in видел, видел
        assert паузы, "перед переопросом должна быть пауза"
        # И ни одного скипа пака: именно он и ронял игру.
        assert all(action.kind != "skip_pack" for action in bridge.actions), bridge.actions

    def test_пак_не_заполнился_никогда_это_затык(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Ждать бесконечно тоже нельзя: если карты не приехали за бюджет,
        # честный «застрял», а не крутёжка до max_steps.
        monkeypatch.setattr(runner, "decide_action", lambda state, **kwargs: None)
        bridge = ScriptedBridge([_state(self._ПАК)])
        report = play_run(bridge, deck="RED", stake="WHITE", max_steps=999, sleep=lambda _: None)

        assert report.outcome == "stuck"
        assert f"завис на фазе {self._ПАК}" in report.note, report.note

    def test_обычная_переходная_фаза_бюджет_не_меняет(self) -> None:
        # Правка не должна молча удлинять ожидание там, где его хватало:
        # у пака бюджет свой, у анимации — прежний `stall_limit`.
        assert runner._wait_budget(self._ПАК, 3) == runner._PACK_FILL_POLLS
        assert runner._wait_budget("HAND_PLAYED", 3) == 3
        assert runner._wait_budget("SELECTING_HAND", 3) is None


class TestСмертьИгрыНеТеряетЖурнал:
    """Главный регресс по вылетам: игра умирает посреди запроса, и раньше это
    улетало наружу необработанным `RemoteDisconnected`.

    Цена была не в самом исключении, а в том, что оно уносило: журнал рана —
    того единственного, который объясняет падение, — не записывался вовсе,
    `run_batch` не доходил до остановки пакета по мёртвому мосту, а наружу
    летела трасса. Теперь мост отдаёт `NotConnectedError`, то есть обычный
    `ModBridgeError`, и вся уже существующая машинерия отрабатывает."""

    def _мост(self) -> ScriptedBridge:
        return ScriptedBridge([_state("BLIND_SELECT"), _state("SELECTING_HAND")])

    def test_журнал_пишется_даже_когда_игра_умерла(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Сквозной, через НАСТОЯЩИЙ `ModBridge`: отображение транспортного
        # сбоя живёт в `ModBridge.call`, и подмена `dispatch_action` его бы
        # обошла. Рвём сам транспорт — так же, как это делает умирающая игра.
        def boom(*_a: object, **_kw: object) -> object:
            raise http.client.RemoteDisconnected("обрыв без ответа")

        monkeypatch.setattr("urllib.request.urlopen", boom)
        # Без ожидания возврата моста: он не вернётся, игра мертва.
        monkeypatch.setattr(runner, "_reconnect", lambda bridge, *, sleep: None)

        report = play_run(
            ModBridge(port=1, timeout=0.1),
            deck="RED",
            stake="WHITE",
            sleep=lambda _: None,
            log_dir=tmp_path,
        )

        # Раньше `RemoteDisconnected` улетал мимо `except ModBridgeError`, и
        # журнала не оставалось вовсе — терялся ровно тот ран, ради которого
        # его и заводили.
        assert report.outcome == "error"
        (файл,) = list(tmp_path.glob("*.json"))
        данные = json.loads(файл.read_text(encoding="utf-8"))
        assert данные["deck"] == "RED"
        assert данные["outcome"] == "error"
        assert "оборвал соединение" in (данные["note"] or "")

    def test_обрыв_не_улетает_исключением_наружу(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Через настоящий `ModBridge.call`, а не подменой `dispatch_action`:
        # проверяем именно отображение транспортного сбоя в `ModBridgeError`.
        def boom(*_a: object, **_kw: object) -> object:
            raise http.client.RemoteDisconnected("обрыв")

        monkeypatch.setattr("urllib.request.urlopen", boom)
        with pytest.raises(ModBridgeError):
            ModBridge(port=1, timeout=1.0).game_state()


class TestТаймаутЭтоНеОтказ:
    """Отказ и зависание лечатся противоположным образом, и раньше раннер их
    не различал.

    Отказ значит «мод не принял действие» — повтор после паузы уместен и
    закрыт улучшением A19. Таймаут значит «действие всё ещё выполняется
    внутри игры»: мод ждёт условие завершения, которое может не наступить
    никогда. Наблюдалось дважды — `pack` 95 372 мс и `select` 460 545 мс,
    и первое кончилось падением процесса игры. Повтор в этом случае шлёт
    второе действие поверх незакрытого первого.

    Прогон, которым дефект был найден, отправлял `['pack', 'pack', 'pack']`;
    здесь пиним, что уходит ровно одно."""

    _ПАК = "SMODS_BOOSTER_OPENED"

    def _мост(self) -> ScriptedBridge:
        return ScriptedBridge([_state(self._ПАК), _state("SELECTING_HAND")])

    def _зависает(self, отправлено: list[Action]) -> Callable[..., GameState]:
        def f(bridge: ModBridge, action: Action) -> GameState:
            отправлено.append(action)
            raise TimedOutError("мод не ответил за 20 с на «pack».")

        return f

    def test_зависшее_действие_не_повторяется(self, monkeypatch: pytest.MonkeyPatch) -> None:
        отправлено: list[Action] = []
        monkeypatch.setattr(
            runner, "decide_action", lambda state, **kw: Action(kind="pack", item_index=0)
        )
        monkeypatch.setattr(runner, "dispatch_action", self._зависает(отправлено))
        report = play_run(self._мост(), deck="RED", stake="WHITE", sleep=lambda _: None)

        assert len(отправлено) == 1, отправлено
        assert report.outcome == "error"

    def test_зависание_называет_действие_и_фазу(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            runner, "decide_action", lambda state, **kw: Action(kind="pack", item_index=0)
        )
        monkeypatch.setattr(runner, "dispatch_action", self._зависает([]))
        report = play_run(self._мост(), deck="RED", stake="WHITE", sleep=lambda _: None)

        # Префикс стабилен нарочно: без него разбор журналов не отличит
        # зависание от смерти моста — оба дают исход `error`.
        assert report.note.startswith(runner._HUNG_PREFIX)
        assert self._ПАК in report.note

    def test_журнал_пишется_при_зависании(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            runner, "decide_action", lambda state, **kw: Action(kind="pack", item_index=0)
        )
        monkeypatch.setattr(runner, "dispatch_action", self._зависает([]))
        play_run(self._мост(), deck="RED", stake="WHITE", sleep=lambda _: None, log_dir=tmp_path)

        (файл,) = list(tmp_path.glob("*.json"))
        данные = json.loads(файл.read_text(encoding="utf-8"))
        assert данные["outcome"] == "error"
        assert данные["decisions"][-1]["rejected"] is True

    def test_обычный_отказ_всё_ещё_повторяется(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Страховка от перехвата лишнего: если новая ветка заберёт себе и
        # обычный отказ, она тихо убьёт A19 — там повтор как раз нужен.
        попытки: list[Action] = []

        def отказ(bridge: ModBridge, action: Action) -> GameState:
            попытки.append(action)
            raise ModBridgeError("[-32002] игра ещё не готова")

        monkeypatch.setattr(
            runner, "decide_action", lambda state, **kw: Action(kind="pack", item_index=0)
        )
        monkeypatch.setattr(runner, "dispatch_action", отказ)
        monkeypatch.setattr(runner, "_bridge_alive", lambda bridge: True)
        report = play_run(self._мост(), deck="RED", stake="WHITE", sleep=lambda _: None)

        assert len(попытки) > 1, "обычный отказ обязан повторяться (A19)"
        assert report.outcome == "stuck"


class TestИмениБлайндаВЖурнале:
    """Улучшение E5: имя и вид текущего блайнда.

    Заведено под конкретный незакрытый вопрос: прогноз солвера расходится с
    фактом систематически, и все тяжёлые случаи пришлись на боссовые блайнды,
    а какой именно босс стоял — журнал не говорил. Проверяется здесь ровно
    то, ради чего поле читается из состояния, а не привозится на `Action`:
    оно обязано быть и на записи, до которой `Action` не доживает."""

    def _блайнд(self, phase: str = "SELECTING_HAND") -> GameState:
        return replace(
            _state(phase),
            blind=BlindInfo(
                kind="BOSS",
                name="The Psychic",
                effect="нельзя играть меньше 5 карт",
                required_score=4000,
                status="CURRENT",
            ),
        )

    def test_имя_и_вид_попадают_в_запись(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(runner, "decide_action", lambda state, **kw: Action(kind="play"))
        monkeypatch.setattr(runner, "dispatch_action", lambda bridge, action: bridge._advance())
        bridge = ScriptedBridge([self._блайнд(), _state("GAME_OVER")])
        report = play_run(bridge, deck="RED", stake="WHITE", sleep=lambda _: None)

        assert report.decisions[0].blind_name == "The Psychic"
        assert report.decisions[0].blind_kind == "BOSS"

    def test_поля_доезжают_до_json(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(runner, "decide_action", lambda state, **kw: Action(kind="play"))
        monkeypatch.setattr(runner, "dispatch_action", lambda bridge, action: bridge._advance())
        bridge = ScriptedBridge([self._блайнд(), _state("GAME_OVER")])
        play_run(bridge, deck="RED", stake="WHITE", sleep=lambda _: None, log_dir=tmp_path)

        (файл,) = list(tmp_path.glob("*.json"))
        решение = json.loads(файл.read_text(encoding="utf-8"))["decisions"][0]
        assert решение["blind_name"] == "The Psychic"
        assert решение["blind_kind"] == "BOSS"

    def test_без_текущего_блайнда_поля_пусты(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # На выборе блайнда и в магазине текущего блайнда нет вовсе. Пусто —
        # это честный ответ, а не пропуск: выдумывать тут нечего.
        monkeypatch.setattr(runner, "decide_action", lambda state, **kw: Action(kind="select"))
        monkeypatch.setattr(runner, "dispatch_action", lambda bridge, action: bridge._advance())
        bridge = ScriptedBridge([_state("BLIND_SELECT"), _state("GAME_OVER")])
        report = play_run(bridge, deck="RED", stake="WHITE", sleep=lambda _: None)

        assert report.decisions[0].blind_name == ""
        assert report.decisions[0].blind_kind == ""

    def test_снимок_есть_и_на_отказе_мода(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # То самое свойство, ради которого заполнение сидит в `_entry`:
        # на отказе `Action` не доживает, а состояние всё равно записано.
        def отказ(bridge: ModBridge, action: Action) -> GameState:
            raise ModBridgeError("[-32002] игра ещё не готова")

        monkeypatch.setattr(runner, "decide_action", lambda state, **kw: Action(kind="play"))
        monkeypatch.setattr(runner, "dispatch_action", отказ)
        monkeypatch.setattr(runner, "_bridge_alive", lambda bridge: True)
        bridge = ScriptedBridge([self._блайнд()])
        report = play_run(bridge, deck="RED", stake="WHITE", sleep=lambda _: None)

        assert report.decisions[0].rejected is True
        assert report.decisions[0].blind_name == "The Psychic"
