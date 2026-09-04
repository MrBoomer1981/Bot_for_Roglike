"""Ран-раннер: провести один ран автопилотом от `start` до конца и отчитаться.

Фаза 9.7 плана («Ран-раннер и измерение винрейта»). Всё готовое ядро
решений (Фазы 4–9.6) уже собрано в `autopilot.decide_action`; здесь —
только обвязка, которая:

- начинает ран честным `ModBridge.start(deck, stake)` (никаких читерских
  `set`/`add`/`load` — раздел 2 плана, «Только честные действия»);
- гоняет цикл «`decide_action` -> `dispatch_action` -> новое состояние» до
  победы (`GameState.won`), поражения (`phase == "GAME_OVER"`) или затыка;
- ведёт лог каждого решения (`DecisionEntry`) — тот же смысл, что у
  golden-тестов для скоринга, только для целого рана, для разбора
  неудачных прогонов;
- отдаёт `RunReport` со сводкой (исход, докуда дошёл, сколько шагов).

`run_batch` — обвязка поверх `play_run`: N ранов на каждой из 8 ставок
отдельно (`STAKES`, снизу вверх — на промежуточных ставках проще понять,
какой из кумулятивных модификаторов уронил прогон, раздел 2). Работа
сутками без присмотра (watchdog, автоперезапуск) намеренно не входит в
объём — `max_steps`/`stall_limit` здесь только чтобы один зависший ран не
подвесил весь пакет, а не полноценный демон.

Цикл `play_run` — не поллинг: каждое действие моста возвращает уже
осевшее следующее состояние, поэтому опрос (`game_state`) нужен только
чтобы переждать анимационную фазу, на которой `decide_action` честно
возвращает `None` (`_TRANSIENT_PHASES`). На любой другой фазе `None`
означает, что решение там ещё не замкнуто (Tarot/Spectral/Standard/Buffoon
-паки — Фаза 9.3/9.4) и ран честно фиксируется как «застрял здесь», а не
гадает."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from balatro_bot.adapters.mod_bridge import ModBridge, ModBridgeError
from balatro_bot.autopilot import decide_action, describe_action, dispatch_action
from balatro_bot.core.state import GameState

__all__ = [
    "DECKS",
    "STAKES",
    "DecisionEntry",
    "RunReport",
    "StakeSummary",
    "play_run",
    "render_batch_summary",
    "render_run_report",
    "run_batch",
]

#: Ставки в кумулятивном порядке (`game.lua`'s `stake_level` 1..8; тот же
#: порядок в `openrpc.json`'s `Stake`). `GOLD` включает все восемь
#: модификаторов разом, поэтому обкатка идёт снизу вверх — см. модульный
#: докстринг и раздел 2 плана.
STAKES: Final[tuple[str, ...]] = (
    "WHITE",
    "RED",
    "GREEN",
    "BLACK",
    "BLUE",
    "PURPLE",
    "ORANGE",
    "GOLD",
)

#: Колоды (`openrpc.json`'s `Deck`, ключи `b_*` в `game.lua`). В отличие от
#: ставок не кумулятивны — это просто выбор одной колоды на ран. `RED` —
#: базовая (`b_red`, единственная `unlocked = true`).
DECKS: Final[tuple[str, ...]] = (
    "RED",
    "BLUE",
    "YELLOW",
    "GREEN",
    "BLACK",
    "MAGIC",
    "NEBULA",
    "GHOST",
    "ABANDONED",
    "CHECKERED",
    "ZODIAC",
    "PAINTED",
    "ANAGLYPH",
    "PLASMA",
    "ERRATIC",
)

Outcome = Literal["won", "lost", "stuck", "aborted", "error"]

#: Фаза победы игры (`openrpc.json`'s `State`).
_GAME_OVER: Final[str] = "GAME_OVER"
_MENU: Final[str] = "MENU"

#: Анимационные/переходные фазы: `decide_action` возвращает на них `None`, но
#: ран не застрял — надо просто переждать и перечитать состояние. Всё
#: остальное, на чём `decide_action` даёт `None`, — незамкнутое решение,
#: честный «застрял».
_TRANSIENT_PHASES: Final[frozenset[str]] = frozenset(
    {"HAND_PLAYED", "DRAW_TO_HAND", "NEW_ROUND", "PLAY_TAROT"}
)

#: Разумный потолок шагов на ран: 8 ант × 3 блайнда × (~4 руки + магазин +
#: выбор блайнда + награда) ≈ 200 в идеале, с покупками и паками больше —
#: 2000 с огромным запасом, только чтобы зациклившийся ран не крутился
#: вечно.
_DEFAULT_MAX_STEPS: Final[int] = 2000

#: Столько подряд шагов без единого изменения состояния (или подряд
#: отклонённых модом действий) — считаем ран застрявшим.
_DEFAULT_STALL_LIMIT: Final[int] = 3

#: Пауза перед повторным опросом на переходной фазе.
_TRANSIENT_POLL_INTERVAL: Final[float] = 0.25


@dataclass(frozen=True, slots=True)
class DecisionEntry:
    """Один шаг лога решений — что автопилот решил и в каком положении."""

    step: int
    phase: str
    ante: int
    round_number: int
    money: int
    action: str
    """`describe_action` выбранного действия, либо пояснение затыка."""
    rejected: bool = False
    """Мод отказал в этом действии (`ModBridgeError`) — оно записано, но не
    исполнено."""


@dataclass(frozen=True, slots=True)
class RunReport:
    """Итог одного рана."""

    deck: str
    stake: str
    seed: str | None
    outcome: Outcome
    ante: int
    round_number: int
    steps: int
    decisions: tuple[DecisionEntry, ...] = ()
    note: str = ""
    """Причина не-победного исхода: сообщение моста для `error`, фаза затыка
    для `stuck`, пусто для `won`/`lost`."""

    adopted: bool = False
    """Ран не начат раннером, а подхвачен уже идущим (`play_run(adopt=True)`).
    Важно для честности сводки: `deck` в таком ране взят из состояния игры
    (`GameState.deck_type`), а вот **ставка в состоянии не приходит вовсе** —
    мод её не присылает, поэтому `stake` тут не наблюдение, а то, что
    попросили флагом. Подписать подхваченный ран «RED/WHITE» только потому,
    что так стояло в аргументах, значило бы испортить ту самую таблицу
    винрейта, ради которой всё и делается."""

    @property
    def won(self) -> bool:
        return self.outcome == "won"


@dataclass(frozen=True, slots=True)
class StakeSummary:
    """Сводка по всем ранам одной ставки."""

    stake: str
    reports: tuple[RunReport, ...] = ()

    @property
    def runs(self) -> int:
        return len(self.reports)

    @property
    def wins(self) -> int:
        return sum(1 for report in self.reports if report.won)

    @property
    def win_rate(self) -> float:
        return self.wins / self.runs if self.reports else 0.0

    @property
    def best_ante(self) -> int:
        return max((report.ante for report in self.reports), default=0)

    @property
    def mean_ante(self) -> float:
        return sum(report.ante for report in self.reports) / self.runs if self.reports else 0.0


def _terminal_outcome(state: GameState) -> Outcome | None:
    """Исход, если состояние терминальное, иначе `None` — ран продолжается."""
    if state.won:
        return "won"
    if state.phase == _GAME_OVER:
        return "lost"
    if state.phase == _MENU:
        # Вернулись в меню сами по себе (ран не начинался или мод сбросил
        # его) — не победа и не штатное поражение.
        return "stuck"
    return None


def play_run(
    bridge: ModBridge,
    *,
    deck: str,
    stake: str,
    seed: str | None = None,
    include_discards: bool = True,
    max_steps: int = _DEFAULT_MAX_STEPS,
    stall_limit: int = _DEFAULT_STALL_LIMIT,
    adopt: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    key_reader: Callable[[], str | None] = lambda: None,
    on_step: Callable[[GameState, DecisionEntry], None] | None = None,
) -> RunReport:
    """Провести один ран автопилотом и вернуть отчёт.

    `key_reader` — источник одиночных нажатий (тот же приём, что у
    `ui/tui.py.autoplay`): любое нажатие обрывает ран с исходом `aborted`,
    чтобы человек мог забрать управление (раздел 2 плана — переключение
    советник ⇄ автопилот по ходу дела). По умолчанию источника нет.
    `on_step` вызывается после каждого записанного решения — для живого
    прогресса в CLI; пакетный прогон не передаёт ничего.

    `adopt=True` — подхватить уже идущий ран вместо того, чтобы начинать
    свой. Без этого `play_run` всегда открывался парой `menu()` + `start()`,
    то есть затирал забег, который человек только что настроил сам, — а это
    как раз обычный случай: игру запускают руками, а автопилот подключают
    к ней. С флагом раннер сперва смотрит состояние: если игра не в меню и
    не на экране проигрыша, значит ран идёт, и он продолжается с этого
    места. Если игра всё-таки в меню — поведение прежнее, начинаем свой ран.
    См. `RunReport.adopted` про то, почему у подхваченного рана колода
    наблюдаемая, а ставка — только заявленная.
    """
    adopted = False
    try:
        if adopt:
            current = bridge.game_state()
            if current.phase not in (_MENU, _GAME_OVER):
                state = current
                adopted = True
                # Колоду игра сообщает сама; ставку она не присылает вовсе.
                deck = current.deck_type or deck
        if not adopted:
            bridge.menu()
            state = bridge.start(deck, stake, seed=seed)
    except ModBridgeError as error:
        return RunReport(deck, stake, seed, "error", 1, 1, 0, note=str(error))

    decisions: list[DecisionEntry] = []
    stall = 0
    transient_polls = 0

    for step in range(1, max_steps + 1):
        if key_reader() is not None:
            return _finish(
                deck,
                stake,
                seed,
                "aborted",
                state,
                decisions,
                note="перехват управления",
                adopted=adopted,
            )

        outcome = _terminal_outcome(state)
        if outcome is not None:
            note = f"вернулись в меню на шаге {step}" if outcome == "stuck" else ""
            return _finish(deck, stake, seed, outcome, state, decisions, note=note, adopted=adopted)

        action = decide_action(state, include_discards=include_discards)

        if action is None and state.phase in _TRANSIENT_PHASES:
            # Переходную фазу пережидаем — но не бесконечно: если мод завис
            # на ней (анимация не заканчивается), после `stall_limit` пустых
            # опросов подряд честно сдаёмся, а не крутимся до `max_steps` по
            # четверти секунды.
            transient_polls += 1
            if transient_polls >= stall_limit:
                return _finish(
                    deck,
                    stake,
                    seed,
                    "stuck",
                    state,
                    decisions,
                    note=f"мод завис на фазе {state.phase}",
                    adopted=adopted,
                )
            sleep(_TRANSIENT_POLL_INTERVAL)
            try:
                state = bridge.game_state()
            except ModBridgeError as error:
                return _finish(
                    deck,
                    stake,
                    seed,
                    "error",
                    state,
                    decisions,
                    note=str(error),
                    adopted=adopted,
                )
            continue

        transient_polls = 0

        if action is None:
            entry = _entry(step, state, f"нет решения для фазы {state.phase}")
            decisions.append(entry)
            if on_step is not None:
                on_step(state, entry)
            return _finish(
                deck,
                stake,
                seed,
                "stuck",
                state,
                decisions,
                note=f"decide_action вернул None на фазе {state.phase}",
                adopted=adopted,
            )

        try:
            new_state = dispatch_action(bridge, action)
        except ModBridgeError as error:
            entry = _entry(step, state, f"{describe_action(action)} — мод отказал: {error}", True)
            decisions.append(entry)
            if on_step is not None:
                on_step(state, entry)
            stall += 1
            if stall >= stall_limit:
                return _finish(
                    deck,
                    stake,
                    seed,
                    "stuck",
                    state,
                    decisions,
                    note=f"мод отказал ×{stall}",
                    adopted=adopted,
                )
            continue

        entry = _entry(step, state, describe_action(action))
        decisions.append(entry)
        if on_step is not None:
            on_step(state, entry)

        stall = stall + 1 if new_state == state else 0
        state = new_state
        if stall >= stall_limit:
            return _finish(
                deck,
                stake,
                seed,
                "stuck",
                state,
                decisions,
                note="состояние не меняется",
                adopted=adopted,
            )

    return _finish(
        deck,
        stake,
        seed,
        "stuck",
        state,
        decisions,
        note=f"превышен предел шагов ({max_steps})",
        adopted=adopted,
    )


def _entry(step: int, state: GameState, action: str, rejected: bool = False) -> DecisionEntry:
    return DecisionEntry(
        step=step,
        phase=state.phase,
        ante=state.ante,
        round_number=state.round_number,
        money=state.money,
        action=action,
        rejected=rejected,
    )


def _finish(
    deck: str,
    stake: str,
    seed: str | None,
    outcome: Outcome,
    state: GameState,
    decisions: list[DecisionEntry],
    *,
    note: str = "",
    adopted: bool = False,
) -> RunReport:
    return RunReport(
        deck=deck,
        stake=stake,
        seed=seed,
        outcome=outcome,
        ante=state.ante,
        round_number=state.round_number,
        steps=len(decisions),
        decisions=tuple(decisions),
        note=note,
        adopted=adopted,
    )


def run_batch(
    bridge: ModBridge,
    *,
    deck: str,
    stakes: Sequence[str] = STAKES,
    runs_per_stake: int = 1,
    seed: str | None = None,
    include_discards: bool = True,
    max_steps: int = _DEFAULT_MAX_STEPS,
    sleep: Callable[[float], None] = time.sleep,
    adopt_first: bool = False,
    key_reader: Callable[[], str | None] = lambda: None,
    on_run: Callable[[RunReport], None] | None = None,
) -> tuple[StakeSummary, ...]:
    """Прогнать `runs_per_stake` ранов на каждой ставке из `stakes` и собрать
    сводку по каждой. `seed` фиксированным делает N одинаковых ранов (полезно
    для регрессии, не для винрейта) — для замера винрейта оставить `None`.
    Любое нажатие (`key_reader`) обрывает и текущий ран, и весь пакет: раз
    человек вмешался, следующие раны не начинаем. `KeyboardInterrupt`
    (Ctrl+C) тоже не теряет уже собранное — возвращаем сводку по тому, что
    успели прогнать, а не всё насмарку.

    `adopt_first=True` — подхватить уже идущий ран **только первым** раном
    пакета (`play_run(adopt=...)`): к моменту второго предыдущий уже
    закончился, подхватывать нечего, и все последующие начинаются как
    обычно."""
    summaries: list[StakeSummary] = []
    adopt_next = adopt_first
    for stake in stakes:
        reports: list[RunReport] = []
        for _ in range(runs_per_stake):
            try:
                report = play_run(
                    bridge,
                    deck=deck,
                    stake=stake,
                    seed=seed,
                    include_discards=include_discards,
                    max_steps=max_steps,
                    adopt=adopt_next,
                    sleep=sleep,
                    key_reader=key_reader,
                )
            except KeyboardInterrupt:
                summaries.append(StakeSummary(stake, tuple(reports)))
                return tuple(summaries)
            # Подхватывать можно только первым раном: дальше подхватывать
            # уже нечего, предыдущий закончился.
            adopt_next = False
            reports.append(report)
            if on_run is not None:
                on_run(report)
            if report.outcome == "aborted":
                summaries.append(StakeSummary(stake, tuple(reports)))
                return tuple(summaries)
        summaries.append(StakeSummary(stake, tuple(reports)))
    return tuple(summaries)


_OUTCOME_LABEL: Final[dict[str, str]] = {
    "won": "победа",
    "lost": "поражение",
    "stuck": "застрял",
    "aborted": "перехват",
    "error": "ошибка",
}


def render_run_report(report: RunReport, *, verbose: bool = False) -> None:
    """Печать отчёта об одном ране. `verbose` — весь лог решений; иначе
    только сводка и последние десять шагов."""
    исход = _OUTCOME_LABEL.get(report.outcome, report.outcome)
    seed = f", сид {report.seed}" if report.seed else ""
    print(
        f"\n{report.deck} / {report.stake}{seed}: {исход} — "
        f"анте {report.ante}, раунд {report.round_number}, шагов {report.steps}"
    )
    if report.note:
        print(f"  {report.note}")

    if not report.decisions:
        return
    журнал = report.decisions if verbose else report.decisions[-10:]
    if not verbose and len(report.decisions) > len(журнал):
        print(f"  … ещё {len(report.decisions) - len(журнал)} выше (весь лог: --explain)")
    for entry in журнал:
        метка = " [отказ]" if entry.rejected else ""
        print(
            f"  [{entry.step:>3}] анте {entry.ante} р{entry.round_number} "
            f"${entry.money:<4} {entry.action}{метка}"
        )


def render_batch_summary(summaries: Sequence[StakeSummary]) -> None:
    """Таблица «ставка → винрейт» по всем прогонам пакета."""
    print("\nвинрейт по ставкам:")
    print(f"  {'ставка':<8} {'ранов':>6} {'побед':>6} {'винрейт':>8} {'средн. анте':>12}")
    for summary in summaries:
        print(
            f"  {summary.stake:<8} {summary.runs:>6} {summary.wins:>6} "
            f"{summary.win_rate:>7.0%} {summary.mean_ante:>12.1f}"
        )
