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

import contextlib
import json
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from balatro_bot.adapters.mod_bridge import ModBridge, ModBridgeError
from balatro_bot.autopilot import (
    Action,
    BoardEntry,
    HandOutlook,
    ShelfEntry,
    _next_blind_requirement,
    decide_action,
    describe_action,
    dispatch_action,
)
from balatro_bot.core.state import GameState
from balatro_bot.solver.pack import PACK_OPEN_PHASES

__all__ = [
    "DECKS",
    "STAKES",
    "DecisionEntry",
    "PackCard",
    "RunReport",
    "StakeSummary",
    "play_run",
    "render_batch_summary",
    "render_run_report",
    "report_to_json",
    "run_batch",
    "write_run_log",
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

#: Сколько пустых опросов подряд ждём, пока игра положит карты в открытый пак.
#: Отдельно от `stall_limit`, потому что бюджет тут нужен другой: игра создаёт
#: карты отложенным событием с задержкой `1.3*sqrt(GAMESPEED)` (пропатченный
#: `card.lua`), а обычные три опроса — это всего 0.75 с, то есть ран объявил бы
#: себя застрявшим ровно там, где надо подождать.
#:
#: Точную величину вычислить НЕЛЬЗЯ: `GAMESPEED` мод в состоянии не присылает.
#: Поэтому это не игровая константа, а заведомо больший сторожевой потолок —
#: 20 × 0.25 с = 5 с. Если пак не заполнился и за это время, ран честно
#: фиксируется как затык, а не крутится до `max_steps`.
_PACK_FILL_POLLS: Final[int] = 20


#: Сколько всего секунд ждать возвращения моста, прежде чем признать ран
#: провалившимся (вторая половина улучшения E2). Мост отваливается не
#: только когда игра умерла: она бывает занята анимацией, свёрнута,
#: приостановлена — а раньше **любой** такой обрыв заканчивал ран
#: исходом `error`. Полминуты покрывают заминку, но не дают пакету
#: молча висеть на действительно мёртвой игре.
_RECONNECT_DEADLINE: Final[float] = 30.0

#: Пауза между попытками: удваивается от первой до потолка, чтобы на
#: короткой заминке вернуться быстро, а на долгой не молотить опросами.
_RECONNECT_FIRST_DELAY: Final[float] = 0.5
_RECONNECT_MAX_DELAY: Final[float] = 4.0

#: Действия, после которых состояние из ответа мода нельзя брать основанием
#: следующего решения: игра в этот момент открывает пак, и `G.pack_cards`
#: не обязан ещё соответствовать тому паку, который бот считает открытым.
#:
#: Список не на глаз, а по исходнику игры. Все пять пак-тегов заведены с
#: `config.type = 'new_blind_choice'` (`game.lua`, строки 233–240), а этот
#: контекст рассылается из двух мест, до которых бот дотягивается сам:
#: кнопки скипа (`functions/button_callbacks.lua:2776`, в том же событии,
#: что и `add_tag`) и входа в состояние выбора блайнда (`Game:update_blind_select`,
#: `game.lua:3294`). Второй путь прослежен до конца, а не предположен:
#: `next_round` мода — это `G.FUNCS.toggle_shop` (`endpoints/next_round.lua:28`),
#: который ставит `G.STATE = G.STATES.BLIND_SELECT` (`button_callbacks.lua:2505`).
#: Третьего пути в это состояние нет — остаётся только `prep_stage` при
#: старте/загрузке рана (`game.lua:2024`), где тегов ещё не бывает.
#: То есть после `skip` и `next_round` пак может открыться сам, без всякой
#: покупки. `buy_pack` — обратный случай: пак заказан ботом, но его карты
#: могут ещё не доехать.
#:
#: Чем это кончалось без переопроса: бот решал по до-скиповому снимку и
#: получал `Method 'select' requires ... BLIND_SELECT`, а из пака, который
#: тег открыл и никто не забрал, тянул карту чужого типа — `Smiley Face`
#: из «Celestial»-пака и `Uranus` из «Buffoon». Разбор — C3 в PLAN.md.
_RESETTLE_AFTER: Final[frozenset[str]] = frozenset({"skip", "buy_pack", "next_round"})


@dataclass(frozen=True, slots=True)
class PackCard:
    """Одна карта открытого пака, как её видел бот (улучшение E1f).

    Тип везётся вместе с именем, потому что расходились именно типы:
    после Celestial-пака бот тянулся за `Smiley Face` (джокер), после
    Buffoon-пака — за `Uranus` (планета). `evaluate_pack` типизирует пак
    **по содержимому** `state.pack`, так что одного имени карты мало,
    чтобы сказать, чьё содержимое ему подсунули."""

    label: str
    kind: str
    """`JOKER`/`PLANET`/`TAROT`/... — то же поле, что у `ShopItem.kind`."""


@dataclass(frozen=True, slots=True)
class DecisionEntry:
    """Один шаг лога решений — что автопилот решил и в каком положении.

    Улучшение E1a расширило запись до разбираемой. Раньше здесь были
    только шаг, фаза, анте, раунд, деньги и действие — по такому логу
    нельзя сказать, **почему** бот сделал то, что сделал, и все разборы
    ранов 8–10 приходилось делать, глядя в живой терминал. Ради батча E1,
    где за ранами никто не смотрит, добавлены поля, которые на момент
    решения уже посчитаны и достаются даром."""

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

    reason: str = ""
    """`Action.reason` — числа, по которым решение принято (порог, прирост,
    вклад). Пусто, если действие без числового обоснования или записи об
    действии нет вовсе."""

    chips_scored: int = 0
    """Сколько очков набрано в этом раунде **до** этого действия.

    Именно «до»: запись собирается перед исполнением, поэтому очки
    последнего розыгрыша раунда в неё не попадают никогда. Разбор по
    раундам, не знающий об этом, недосчитывает каждому раунду последнюю
    руку — на чём один такой разбор уже поехал. Итог раунда смотреть по
    `blind_beaten` записи, которая раунд закрывает."""

    blind_beaten: bool | None = None
    """Взят ли блайнд — только на записи, закрывающей раунд (`ROUND_EVAL`
    означает победу над блайндом, иначе ран на этом и кончился). `None` на
    всех прочих шагах: там это ещё не известно."""

    requirement: int | None = None
    """Требование ближайшего блайнда (`autopilot._next_blind_requirement`) —
    без него `chips_scored` не с чем сравнить, а именно отставание от
    требования и объясняет проигранные раны."""

    hands_left: int = 0
    discards_left: int = 0

    jokers: tuple[str, ...] = ()
    """Джокеры в слотах по порядку — порядок влияет на счёт, поэтому
    именно кортеж, а не множество."""

    outlook: HandOutlook | None = None
    """Между чем выбирал автопилот на этой руке (улучшение E1d): лучший
    розыгрыш и лучшая оценка сброса. Без этих двух чисел нельзя сказать,
    чего стоил отданный ради сброса розыгрыш, — попытка достать это по
    журналам батча нашла 2 случая из ~81. `None` вне фазы руки."""

    shelf: tuple[ShelfEntry, ...] = ()
    """Витрина на момент решения (улучшение E1e). Нужна, чтобы понять,
    почему реролл не окупается: без состава полки до и после ролла три
    объяснения из A22 неразличимы."""

    board: tuple[BoardEntry, ...] = ()
    """Те же джокеры, но с измеренным вкладом каждого (улучшение E1b).

    Непусто только на решениях в магазине: вклад считается там
    (`ShopAdvice.held`) и больше нигде. Без этих чисел по журналу нельзя
    сказать ни законно ли отклонён размен, ни во что обошлась текучка
    джокеров — оба вопроса висели открытыми именно поэтому."""

    pack: tuple[PackCard, ...] = ()
    """Содержимое открытого пака на момент решения (улучшение E1f).

    Читается прямо из `state.pack`, а не привозится на `Action`, — и это
    сознательно. `board`/`shelf`/`outlook` везут **посчитанные** оценки,
    которые существуют только на своей ветке; `pack` же сырое состояние,
    как `jokers` и `chips_scored`. Взятое из состояния попадает в журнал
    на **каждом** шаге — включая отказы мода и шаги без решения вовсе, а
    все четыре отказа корпуса как раз в паках: три из них в
    `SMODS_BOOSTER_OPENED`, и на них `Action` не доживает."""

    offered_tag: str = ""
    """Тег, который дают за скип выбираемого сейчас блайнда — `tag_name`
    того из `small`/`big`, у кого статус `SELECT` (тот же поиск, что в
    `solver.skip.evaluate_skip`). Пусто вне экрана выбора.

    **Это не список взятых тегов, и заменить его им нельзя.** Игра держит
    взятые теги в `G.GAME.tags`, но мод их не отдаёт: его `gamestate.lua`
    читает только `G.GAME.round_resets.blind_tags`, то есть предложение, а
    не владение. Поэтому «дошёл ли тег до пака» по журналу по-прежнему не
    восстановить — см. разбор C3 в PLAN.md, где эта диагностика записана
    как возможная, и это неверно."""


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

    @property
    def discards_used(self) -> int:
        """Сколько раз за ран автопилот сбросил карты."""
        return sum(1 for entry in self.decisions if entry.action.startswith("сбросил"))

    @property
    def plays_made(self) -> int:
        """Сколько раз разыграл."""
        return sum(1 for entry in self.decisions if entry.action.startswith("сыграл"))

    @property
    def rounds_with_discards_unspent(self) -> int:
        """Раундов, закрытых без единого сброса при доступных сбросах.

        Ран ZODIAC (2026-09-05) проиграл, ни разу не сбросив с анте 3 и
        закрыв так десять раундов подряд — а заметил это человек, вручную
        читая сто строк журнала. Симптом такого веса отчёт обязан называть
        сам."""
        сколько = 0
        предыдущая: DecisionEntry | None = None
        for entry in self.decisions:
            if (
                entry.phase == "ROUND_EVAL"
                and предыдущая is not None
                and предыдущая.discards_left > 0
                and not _раунд_сбрасывал(self.decisions, entry.step)
            ):
                сколько += 1
            предыдущая = entry
        return сколько


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


def _play_run(
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
        # E2: в пакете следующий ран начинается сразу за предыдущим, и
        # игра ещё может доигрывать экран поражения. Подождать дешевле,
        # чем сжечь ран впустую.
        if _reconnect(bridge, sleep=sleep) is None:
            return RunReport(
                deck,
                stake,
                seed,
                "error",
                1,
                1,
                0,
                note=f"мост не вернулся за {_RECONNECT_DEADLINE:g} с: {error}",
            )
        try:
            if adopt:
                current = bridge.game_state()
                if current.phase not in (_MENU, _GAME_OVER):
                    state = current
                    adopted = True
                    deck = current.deck_type or deck
            if not adopted:
                bridge.menu()
                state = bridge.start(deck, stake, seed=seed)
        except ModBridgeError as повторно:
            return RunReport(deck, stake, seed, "error", 1, 1, 0, note=str(повторно))

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

        бюджет = _wait_budget(state.phase, stall_limit)
        if action is None and бюджет is not None:
            # Переходную фазу пережидаем — но не бесконечно: если мод завис
            # на ней (анимация не заканчивается), после `бюджет` пустых
            # опросов подряд честно сдаёмся, а не крутимся до `max_steps` по
            # четверти секунды. У пака бюджет свой, см. `_wait_budget`.
            transient_polls += 1
            if transient_polls >= бюджет:
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
                # E2: обрыв связи — не обязательно смерть игры. Ждём.
                вернулось = _reconnect(bridge, sleep=sleep)
                if вернулось is None:
                    return _finish(
                        deck,
                        stake,
                        seed,
                        "error",
                        state,
                        decisions,
                        note=f"мост не вернулся за {_RECONNECT_DEADLINE:g} с: {error}",
                        adopted=adopted,
                    )
                entry = _entry(step, вернулось, f"связь восстановлена после обрыва: {error}")
                decisions.append(entry)
                if on_step is not None:
                    on_step(вернулось, entry)
                state = вернулось
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
            # E2: «мод отказал в действии» и «моста больше нет» приходят
            # одним типом исключения, а лечатся по-разному: первое — это
            # затык (`stall`), второе — ожидание. Различаем опросом.
            if not _bridge_alive(bridge):
                вернулось = _reconnect(bridge, sleep=sleep)
                if вернулось is None:
                    return _finish(
                        deck,
                        stake,
                        seed,
                        "error",
                        state,
                        decisions,
                        note=f"мост не вернулся за {_RECONNECT_DEADLINE:g} с: {error}",
                        adopted=adopted,
                    )
                entry = _entry(step, вернулось, f"связь восстановлена после обрыва: {error}")
                decisions.append(entry)
                if on_step is not None:
                    on_step(вернулось, entry)
                state = вернулось
                continue
            entry = _entry(
                step,
                state,
                f"{describe_action(action)} — мод отказал: {error}",
                True,
                action,
            )
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
            # Улучшение A19: подождать перед повтором. Отказ часто означает
            # не «нельзя», а «ещё не готово»: мод проверяет фазу и состояние
            # игры (`endpoints/select.lua` требует `BLIND_SELECT` и непустой
            # `blind_on_deck`), а игра в этот момент доигрывает переход. В
            # большом батче ран так и умер: бот скипнул блайнд и трижды за
            # секунду попробовал выбрать следующий, пока шла анимация скипа,
            # исчерпав `stall_limit` на состоянии, которое устоялось бы само.
            # Пауза та же, что у ожидания переходной фазы, — это тот же случай.
            sleep(_TRANSIENT_POLL_INTERVAL)
            # Перечитать состояние: за паузу игра могла доиграть переход.
            # Не вышло — не беда, следующий круг решит по прежнему состоянию,
            # а мёртвый мост уже проверен выше.
            with contextlib.suppress(ModBridgeError):
                state = bridge.game_state()
            continue

        entry = _entry(step, state, describe_action(action), decided=action)
        decisions.append(entry)
        if on_step is not None:
            on_step(state, entry)

        if action.kind in _RESETTLE_AFTER:
            new_state = _resettle(bridge, new_state, sleep=sleep)

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


#: Алфавит сида Balatro — из `random_string` в `functions/misc_functions.lua`:
#: цифры 1–9 и буквы A–N, P–Z. Ноль и буква O исключены самой игрой,
#: чтобы их нельзя было спутать при вводе от руки.
_SEED_ALPHABET: Final[str] = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
_SEED_LENGTH: Final[int] = 8


def _случайный_сид(rng: random.Random) -> str:
    """Сид для одного рана пакета (улучшение E1c).

    Без него игра берёт сид сама — и **не случайно**: `game.lua` зовёт
    `generate_starting_seed()`, а тот строит строку из положения курсора
    мыши и времени наведения (`functions/misc_functions.lua`). Когда раны
    запускает бот через RPC, мышь не двигается, `cursor_hover` не
    меняется — и все раны пакета выходят **одной и той же партией**. Три
    первых рана пакета совпали до последней цифры (оценки сбросов
    430/577/640/692, итог 112, 16 шагов), что это и вскрыло.

    Это не дефект мода и не наш: игра черпает случайность из ввода
    человека, которого при автоигре нет. Поэтому сид выдаём мы, иначе
    винрейт по N ранам — это один ран, посчитанный N раз."""
    return "".join(rng.choice(_SEED_ALPHABET) for _ in range(_SEED_LENGTH))


def _раунд_сбрасывал(decisions: Sequence[DecisionEntry], до_шага: int) -> bool:
    """Был ли сброс в раунде, закончившемся на шаге `до_шага`."""
    for entry in reversed([e for e in decisions if e.step < до_шага]):
        if entry.phase == "ROUND_EVAL":
            break
        if entry.action.startswith("сбросил"):
            return True
    return False


def _reconnect(
    bridge: ModBridge,
    *,
    sleep: Callable[[float], None],
    deadline: float = _RECONNECT_DEADLINE,
) -> GameState | None:
    """Дождаться, пока мост снова начнёт отвечать. `None` — не дождались.

    Вторая половина улучшения E2. Отдельного типа исключения не заводим:
    единственный честный признак «мост жив» — что `game_state()` ответил,
    и он же отличает «мод отказал в действии» (состояние придёт) от
    «мост мёртв» (не придёт). Это дешевле и надёжнее, чем разбирать текст
    ошибки или расширять `ModBridgeError` полем, которое придётся
    выставлять во всех местах, где он поднимается.

    Возвращается **свежее** состояние, а не то, что было до обрыва: пока
    связи не было, игра могла уйти вперёд, и продолжать со старого
    состояния значило бы действовать по устаревшей картине."""
    прошло = 0.0
    пауза = _RECONNECT_FIRST_DELAY
    while прошло < deadline:
        sleep(пауза)
        прошло += пауза
        пауза = min(пауза * 2, _RECONNECT_MAX_DELAY)
        try:
            return bridge.game_state()
        except ModBridgeError:
            continue
    return None


def _bridge_alive(bridge: ModBridge) -> bool:
    """Отвечает ли мост прямо сейчас — одна попытка, без ожидания."""
    try:
        bridge.game_state()
    except ModBridgeError:
        return False
    return True


def _wait_budget(phase: str, stall_limit: int) -> int | None:
    """Сколько пустых опросов подряд пережидаем на этой фазе.

    `None` — не пережидаем вовсе: `None` от `decide_action` на такой фазе
    означает незамкнутое решение, и это честный «застрял».

    Фаза открытого пака получает свой, больший бюджет (`_PACK_FILL_POLLS`):
    там `None` значит «карты ещё не приехали», а ждать их приходится дольше,
    чем длится обычная анимация."""
    if phase in PACK_OPEN_PHASES:
        return _PACK_FILL_POLLS
    if phase in _TRANSIENT_PHASES:
        return stall_limit
    return None


def _resettle(bridge: ModBridge, state: GameState, *, sleep: Callable[[float], None]) -> GameState:
    """Переспросить состояние после действия из `_RESETTLE_AFTER`.

    Пауза та же, что у ожидания переходной фазы и у повтора после отказа
    (A19): все три — один и тот же случай «игра ещё доигрывает переход».
    Опрос не удался — возвращаем то, что было: следующий круг решит по
    нему, а мёртвый мост поймает общая ветка обрыва.

    Живой режим (`ui/tui.py.autoplay`) в этом не нуждается и не трогается:
    он и так опрашивает мод заново в начале каждого круга, а состояние из
    ответа на действие использует только для показа."""
    sleep(_TRANSIENT_POLL_INTERVAL)
    with contextlib.suppress(ModBridgeError):
        return bridge.game_state()
    return state


def _entry(
    step: int,
    state: GameState,
    action: str,
    rejected: bool = False,
    decided: Action | None = None,
) -> DecisionEntry:
    """Собрать запись журнала. `decided` — само решение, если оно было:
    из него берётся `reason`, остальное читается из состояния (улучшение
    E1a). Ничего не пересчитывается — все числа уже есть."""
    return DecisionEntry(
        step=step,
        phase=state.phase,
        ante=state.ante,
        round_number=state.round_number,
        money=state.money,
        action=action,
        rejected=rejected,
        reason=decided.reason if decided is not None else "",
        board=decided.board if decided is not None else (),
        shelf=decided.shelf if decided is not None else (),
        outlook=decided.outlook if decided is not None else None,
        chips_scored=state.chips_scored,
        requirement=_next_blind_requirement(state),
        hands_left=state.hands_left,
        discards_left=state.discards_left,
        jokers=tuple(joker.label or joker.key for joker in state.jokers),
        blind_beaten=True if state.phase == "ROUND_EVAL" else None,
        pack=tuple(PackCard(label=item.label, kind=item.kind) for item in state.pack),
        offered_tag=_offered_tag(state),
    )


def _offered_tag(state: GameState) -> str:
    """Тег за скип выбираемого блайнда. Босс не рассматривается: его не
    скипнуть, тега у него не бывает, а статус `SELECT` там значит «играть»
    — тот же порядок и та же причина, что в `solver.skip.evaluate_skip`."""
    for key in ("small", "big"):
        blind = state.blinds.get(key)
        if blind is not None and blind.status == "SELECT":
            return blind.tag_name
    return ""


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
    log_dir: Path | None = None,
) -> RunReport:
    """Провести ран (`_play_run`) и, если задан `log_dir`, записать журнал.

    Обёртка отдельно от самого прогона потому, что выходов у него больше
    десятка (победа, проигрыш, затык, отказ моста, перехват управления), и
    журнал должен писаться на **любом** из них — особенно на аварийных,
    ради которых он и заводился. Дописывать запись к каждому `return`
    значило бы однажды забыть про один из них."""
    report = _play_run(
        bridge,
        deck=deck,
        stake=stake,
        seed=seed,
        include_discards=include_discards,
        max_steps=max_steps,
        stall_limit=stall_limit,
        adopt=adopt,
        sleep=sleep,
        key_reader=key_reader,
        on_step=on_step,
    )
    if log_dir is not None:
        write_run_log(report, log_dir)
    return report


def report_to_json(report: RunReport) -> dict[str, object]:
    """Отчёт о ране в простые типы для JSON (улучшение E1a).

    Словари собираются руками, а не `dataclasses.asdict`: файл журнала
    читают через месяц после прогона, и набор полей должен меняться
    осознанно, а не следовать молча за перестановкой полей в датаклассе.
    Ничего, кроме простых типов, внутри нет — json это и требует."""
    return {
        "deck": report.deck,
        "stake": report.stake,
        # Ставка известна точно ровно тогда, когда ран начал раннер: он
        # сам передал её в `start`. У подхваченного рана мод ставку не
        # присылает вовсе, и она остаётся тем, что попросили флагом.
        "stake_observed": not report.adopted,
        "seed": report.seed,
        "outcome": report.outcome,
        "ante": report.ante,
        "round": report.round_number,
        "steps": report.steps,
        "plays": report.plays_made,
        "discards_used": report.discards_used,
        "rounds_with_discards_unspent": report.rounds_with_discards_unspent,
        "note": report.note,
        "adopted": report.adopted,
        "decisions": [
            {
                "step": entry.step,
                "phase": entry.phase,
                "ante": entry.ante,
                "round": entry.round_number,
                "money": entry.money,
                "action": entry.action,
                "reason": entry.reason,
                "rejected": entry.rejected,
                "chips_scored": entry.chips_scored,
                "requirement": entry.requirement,
                "hands_left": entry.hands_left,
                "discards_left": entry.discards_left,
                "jokers": list(entry.jokers),
                "blind_beaten": entry.blind_beaten,
                "outlook": (
                    {
                        "best_play": round(entry.outlook.best_play, 1),
                        "best_discard": (
                            None
                            if entry.outlook.best_discard is None
                            else round(entry.outlook.best_discard, 1)
                        ),
                        "discards_left": entry.outlook.discards_left,
                    }
                    if entry.outlook is not None
                    else None
                ),
                "shelf": [
                    {
                        "label": п.label,
                        "kind": п.kind,
                        "price": п.price,
                        "uplift": None if п.uplift is None else round(п.uplift, 1),
                        "affordable": п.affordable,
                        "has_slot": п.has_slot,
                    }
                    for п in entry.shelf
                ],
                "board": [
                    {
                        "label": место.label,
                        "contribution": round(место.contribution, 1),
                        "sell_value": место.sell_value,
                    }
                    for место in entry.board
                ],
                "pack": [{"label": карта.label, "kind": карта.kind} for карта in entry.pack],
                "offered_tag": entry.offered_tag,
            }
            for entry in report.decisions
        ],
    }


def write_run_log(report: RunReport, log_dir: Path) -> Path:
    """Записать журнал рана в `log_dir` и вернуть путь.

    Формат имени и способ записи — те же, что у `balatro-bot record`
    (`cli.py`): метка времени UTC впереди, `ensure_ascii=False`, отступ 2.
    Один файл на ран: пакет из полусотни ранов должен разбираться
    по одному, а не одним гигантским документом."""
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    target = log_dir / f"{stamp}-{report.deck.lower()}-{report.outcome}.json"
    target.write_text(
        json.dumps(report_to_json(report), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target


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
    log_dir: Path | None = None,
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
    # Явный `seed` от пользователя означает «прогнать N одинаковых ранов»
    # (регрессия), и тогда сид не трогаем. Без него каждый ран получает
    # свой — см. `_случайный_сид`, без этого пакет мерил один ран N раз.
    rng = random.Random()
    for stake in stakes:
        reports: list[RunReport] = []
        for _ in range(runs_per_stake):
            try:
                report = play_run(
                    bridge,
                    deck=deck,
                    stake=stake,
                    seed=seed if seed is not None else _случайный_сид(rng),
                    include_discards=include_discards,
                    max_steps=max_steps,
                    adopt=adopt_next,
                    sleep=sleep,
                    key_reader=key_reader,
                    log_dir=log_dir,
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
            # E2: раньше пакет на мёртвом мосте не останавливался, а
            # прогонял все оставшиеся раны за секунды, набивая отчёты
            # исходом `error`. Двадцать таких отчётов — не данные.
            if report.outcome == "error" and not _bridge_alive(bridge):
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
    нетронуто = report.rounds_with_discards_unspent
    хвост = f", раундов без единого сброса {нетронуто}" if нетронуто else ""
    print(f"  розыгрышей {report.plays_made}, сбросов {report.discards_used}{хвост}")
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
        # Обоснование — только в подробном режиме: в короткой сводке оно
        # утопило бы сами шаги, а нужно оно ровно тогда, когда ран разбирают.
        if verbose and entry.reason:
            print(f"        └ {entry.reason}")
        if verbose and entry.outlook is not None:
            o = entry.outlook
            сброс = "—" if o.best_discard is None else f"{o.best_discard:.0f}"
            print(
                f"          выбор: розыгрыш {o.best_play:.0f} против сброса {сброс}"
                f" (сбросов {o.discards_left})"
            )
        if verbose and entry.board:
            доска = ", ".join(f"{место.label} {место.contribution:.0f}" for место in entry.board)
            print(f"          доска: {доска}")


def render_batch_summary(summaries: Sequence[StakeSummary]) -> None:
    """Таблица «ставка → винрейт» по всем прогонам пакета."""
    print("\nвинрейт по ставкам:")
    print(f"  {'ставка':<8} {'ранов':>6} {'побед':>6} {'винрейт':>8} {'средн. анте':>12}")
    for summary in summaries:
        print(
            f"  {summary.stake:<8} {summary.runs:>6} {summary.wins:>6} "
            f"{summary.win_rate:>7.0%} {summary.mean_ante:>12.1f}"
        )
