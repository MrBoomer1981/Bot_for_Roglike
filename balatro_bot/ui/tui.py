"""Живое окно советника.

Опрашивает мод по JSON-RPC на фиксированном интервале и перерисовывает
терминал только тогда, когда состояние действительно изменилось — иначе
экран мигал бы на каждый опрос впустую, хотя рука та же самая.

Реализует DoD Фазы 5 из PLAN.md: играю, не трогая бота, — советы появляются
сами. Только читает состояние: `ModBridge.play`/`.discard` здесь нарочно не
вызываются — автоигра сознательно не входит в задачу (раздел 2 плана).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from balatro_bot.adapters.mod_bridge import ModBridge, ModBridgeError
from balatro_bot.core.state import GameState
from balatro_bot.solver.actions import rank_actions
from balatro_bot.solver.play import advise
from balatro_bot.solver.shop import evaluate_shop
from balatro_bot.solver.skip import evaluate_skip
from balatro_bot.ui.render import (
    render_joker_order,
    render_shop_advice,
    render_skip_advice,
    render_state,
    render_top_actions,
)

__all__ = ["watch"]

#: Очистка экрана и перевод курсора в левый верхний угол — обычный ANSI,
#: без curses/textual: у проекта правило нулевых зависимостей (CLAUDE.md).
_CLEAR = "\x1b[2J\x1b[H"


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
                if state.hand:
                    print()
                    result = advise(state)
                    actions = rank_actions(state, top=top, include_discards=consider_discards)
                    render_top_actions(result, actions, explain)
                    if joker_order and len(state.jokers) >= 2:
                        render_joker_order(state, result)
                last_state = state

        sleep(interval)
