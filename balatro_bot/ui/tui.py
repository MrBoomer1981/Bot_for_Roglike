"""Живое окно советника и цикл автопилота.

`watch` опрашивает мод по JSON-RPC на фиксированном интервале и
перерисовывает терминал только тогда, когда состояние действительно
изменилось — иначе экран мигал бы на каждый опрос впустую, хотя рука та же
самая. Реализует DoD Фазы 5 из PLAN.md: играю, не трогая бота, — советы
появляются сами. Только читает состояние: `ModBridge.play`/`.discard` здесь
не вызываются вовсе.

`autoplay` — тот же цикл опроса, но с правом действовать (Фаза 9): на фазе
`SELECTING_HAND` сперва проверяет Planet-консумабли (`ModBridge.use`), затем
вызывает `ModBridge.play`/`.discard`, на `BLIND_SELECT` — `.select`/`.skip`,
на `SHOP`/`ROUND_EVAL` — `.buy`/`.next_round`/`.cash_out`, на
`PLANET_PACK`/`BUFFOON_PACK` — `.open_pack`, на Tarot/Spectral/Standard-паке
— `.open_pack(skip=True)` (оценить нечем, но застревать нельзя), всё по
решению `autopilot.decide_action`; на прочих фазах ведёт себя как `watch`.
Переключатель «пауза/перехват» (клавиша `p`, раздел 2 и раздел 6 п. 9.1
плана — обязательное требование, не побочный эффект) проверяется на каждой
итерации, то есть между каждым отдельным действием, а не только между
ранами: на паузе цикл — тот же `watch`, ничего не трогает, пока паузу не
снимут той же клавишей."""

from __future__ import annotations

import select
import sys
import termios
import time
import tty
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from balatro_bot.adapters.mod_bridge import ModBridge, ModBridgeError
from balatro_bot.autopilot import Action, decide_action, describe_action, dispatch_action
from balatro_bot.core.state import GameState
from balatro_bot.solver.actions import rank_actions
from balatro_bot.solver.consumables import evaluate_planet_consumables
from balatro_bot.solver.pack import evaluate_pack
from balatro_bot.solver.play import advise
from balatro_bot.solver.shop import evaluate_shop
from balatro_bot.solver.skip import evaluate_skip
from balatro_bot.ui.render import (
    render_consumable_advice,
    render_joker_order,
    render_pack_advice,
    render_shop_advice,
    render_skip_advice,
    render_state,
    render_top_actions,
)

__all__ = ["autoplay", "watch"]

#: Очистка экрана и перевод курсора в левый верхний угол — обычный ANSI,
#: без curses/textual: у проекта правило нулевых зависимостей (CLAUDE.md).
_CLEAR = "\x1b[2J\x1b[H"

#: Клавиша переключения «автопилот ⇄ пауза» в `autoplay`.
_PAUSE_KEY = "p"


def watch(
    bridge: ModBridge,
    *,
    interval: float = 1.0,
    top: int = 5,
    explain: bool = False,
    joker_order: bool = True,
    consider_discards: bool = True,
    consider_shop: bool = True,
    iterations: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Цикл опроса игры.

    `iterations=None` — бесконечный цикл для реального использования из CLI,
    останавливается снаружи по `KeyboardInterrupt`. Конечное число вместе с
    подменённым `sleep` — для тестов, чтобы не ждать реальное время и не
    зависнуть на живом опросе.
    """
    last_state: GameState | None = None
    last_error: str | None = None
    polls = 0

    while iterations is None or polls < iterations:
        polls += 1
        try:
            state = bridge.game_state()
        except ModBridgeError as error:
            last_state = None
            message = str(error)
            if message != last_error:
                print(_CLEAR, end="")
                print("мод не отвечает, жду...\n")
                print(f"  {message}")
                last_error = message
        else:
            last_error = None
            if state != last_state:
                print(_CLEAR, end="")
                print(f"balatro-bot следит за игрой — опрос раз в {interval:g} с, Ctrl+C — выйти\n")
                render_state(state)
                skip_advice = evaluate_skip(state)
                if skip_advice is not None:
                    render_skip_advice(skip_advice)
                if consider_shop:
                    shop_advice = evaluate_shop(state)
                    if shop_advice is not None:
                        render_shop_advice(shop_advice)
                render_pack_advice(evaluate_pack(state))
                render_consumable_advice(evaluate_planet_consumables(state))
                if state.hand:
                    print()
                    result = advise(state)
                    actions = rank_actions(state, top=top, include_discards=consider_discards)
                    render_top_actions(result, actions, explain)
                    if joker_order and len(state.jokers) >= 2:
                        render_joker_order(state, result)
                last_state = state

        sleep(interval)


@contextmanager
def _cbreak_stdin() -> Iterator[bool]:
    """Переводит терминал в cbreak-режим на время `autoplay`, чтобы читать
    одиночные нажатия без Enter, и гарантированно возвращает исходный режим
    при выходе — даже по исключению или `Ctrl+C`. Если stdin не терминал
    (перенаправлен, тесты) — тихо отключается вместо падения: тумблер паузы
    просто станет недоступен, сам автопилот при этом продолжает работать.
    """
    if not sys.stdin.isatty():
        yield False
        return
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield True
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _read_key() -> str | None:
    """Клавиша, если она уже ждёт во входном буфере, иначе `None` — не
    блокирует цикл опроса."""
    ready, _, _ = select.select([sys.stdin], [], [], 0)
    if not ready:
        return None
    return sys.stdin.read(1)


def autoplay(
    bridge: ModBridge,
    *,
    interval: float = 1.0,
    top: int = 5,
    explain: bool = False,
    joker_order: bool = True,
    consider_discards: bool = True,
    consider_shop: bool = True,
    iterations: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    key_reader: Callable[[], str | None] | None = None,
) -> None:
    """Тот же цикл, что `watch`, но с правом действовать — см. модульный
    докстринг. `key_reader=None` (по умолчанию, реальный запуск из CLI)
    переводит терминал в cbreak-режим и слушает настоящую клавиатуру;
    переданный явно `key_reader` (тесты) — уже готовый источник клавиш,
    реальный терминал вообще не трогается.
    """
    if key_reader is not None:
        _autoplay_loop(
            bridge,
            interval=interval,
            top=top,
            explain=explain,
            joker_order=joker_order,
            consider_discards=consider_discards,
            consider_shop=consider_shop,
            iterations=iterations,
            sleep=sleep,
            key_reader=key_reader,
        )
        return

    with _cbreak_stdin() as enabled:
        _autoplay_loop(
            bridge,
            interval=interval,
            top=top,
            explain=explain,
            joker_order=joker_order,
            consider_discards=consider_discards,
            consider_shop=consider_shop,
            iterations=iterations,
            sleep=sleep,
            key_reader=_read_key if enabled else (lambda: None),
        )


def _autoplay_loop(
    bridge: ModBridge,
    *,
    interval: float,
    top: int,
    explain: bool,
    joker_order: bool,
    consider_discards: bool,
    consider_shop: bool,
    iterations: int | None,
    sleep: Callable[[float], None],
    key_reader: Callable[[], str | None],
) -> None:
    active = True
    last_state: GameState | None = None
    last_error: str | None = None
    polls = 0

    while iterations is None or polls < iterations:
        polls += 1

        key = key_reader()
        if key and key.lower() == _PAUSE_KEY:
            active = not active

        try:
            state = bridge.game_state()
        except ModBridgeError as error:
            last_state = None
            message = str(error)
            if message != last_error:
                print(_CLEAR, end="")
                print("мод не отвечает, жду...\n")
                print(f"  {message}")
                last_error = message
            sleep(interval)
            continue

        last_error = None
        action_taken: Action | None = None

        if active:
            action = decide_action(state, include_discards=consider_discards)
            if action is not None:
                try:
                    state = dispatch_action(bridge, action)
                except ModBridgeError as error:
                    # Мод отказал в честно посчитанном ходе — например,
                    # ограничение босса, которое `_is_legal_play` ещё не
                    # покрывает (раздел 6, «Автопилот», п. 9.5). Не падать
                    # и не повторять один и тот же ход бесконечно — просто
                    # показать ошибку и продолжить опрос тем же состоянием.
                    print(f"\nавтопилот: мод отказал в ходе — {error}")
                else:
                    action_taken = action

        if action_taken is not None or state != last_state:
            print(_CLEAR, end="")
            режим = "АВТОПИЛОТ" if active else "ПАУЗА (перехват управления)"
            print(
                f"balatro-bot [{режим}] — опрос раз в {interval:g} с, "
                f"«{_PAUSE_KEY}» — пауза/продолжить, Ctrl+C — выйти\n"
            )
            if action_taken is not None:
                print(f"автопилот: {describe_action(action_taken)}\n")
            render_state(state)
            skip_advice = evaluate_skip(state)
            if skip_advice is not None:
                render_skip_advice(skip_advice)
            if consider_shop:
                shop_advice = evaluate_shop(state)
                if shop_advice is not None:
                    render_shop_advice(shop_advice)
            render_pack_advice(evaluate_pack(state))
            render_consumable_advice(evaluate_planet_consumables(state))
            if state.hand:
                print()
                result = advise(state)
                actions = rank_actions(state, top=top, include_discards=consider_discards)
                render_top_actions(result, actions, explain)
                if joker_order and len(state.jokers) >= 2:
                    render_joker_order(state, result)
            last_state = state

        sleep(interval)
