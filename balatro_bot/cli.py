"""Командная строка бота.

Пока здесь только то, что нужно для первого запуска рядом с игрой:

    balatro-bot doctor          проверить, что мод отвечает, и показать состояние
    balatro-bot record ИМЯ      записать текущее состояние как эталонный случай

Обе команды бесполезны без запущенной игры, поэтому `doctor` объясняет, что
именно не так, вместо того чтобы падать с трассировкой.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from balatro_bot.adapters.mod_bridge import DEFAULT_HOST, DEFAULT_PORT, ModBridge, ModBridgeError
from balatro_bot.core.cards import Card, Enhancement
from balatro_bot.core.state import GameState

GOLDEN_DIR = Path("tests/golden")

NOT_RUNNING_HINT = """
Мод не отвечает. Проверь по порядку:

  1. Игра запущена? Её нужно стартовать через мод, а не через Steam:
         uvx balatrobot serve
  2. В окне Balatro видно, что Steamodded загрузил моды?
  3. Порт совпадает? Сейчас пробуем {port}, по умолчанию у мода {default}.
     Сменить: balatro-bot doctor --port ДРУГОЙ
"""


def _format_card(card: Card) -> str:
    """Компактная запись карты с пометками, если она не обычная."""
    text = f"{card.rank.value}{card.suit.value}"
    marks = ""
    if card.enhancement is not Enhancement.NONE:
        marks += card.enhancement.value[0].upper()
    if card.debuffed:
        marks += "x"
    return f"{text}({marks})" if marks else text


def _report(state: GameState) -> None:
    """Показать состояние человеку."""
    print(f"фаза:        {state.phase}")
    print(f"анте/раунд:  {state.ante} / {state.round_number}")
    print(f"деньги:      ${state.money}")

    blind = state.blind
    if blind is not None:
        print(f"блайнд:      {blind.name} ({blind.kind}), нужно {blind.required_score}")
        print(f"             эффект: {blind.effect or '—'}")
    else:
        print("блайнд:      сейчас не выбран")

    print(f"осталось:    рук {state.hands_left}, сбросов {state.discards_left}")
    print(f"рука:        {' '.join(_format_card(card) for card in state.hand) or '—'}")

    if state.jokers:
        print("джокеры:")
        for position, joker in enumerate(state.jokers, start=1):
            mark = "" if joker.is_known else "  <- эффект не реализован"
            print(f"  {position}. {joker.label or joker.key} [{joker.key}]{mark}")
    else:
        print("джокеры:     нет")

    источник = "от игры" if state.has_authoritative_hand_values else "провизорные таблицы"
    print(f"значения рук: {источник}")

    if state.is_exact:
        print("\nрасчёт по этому состоянию будет точным")
    else:
        print("\nрасчёт будет НЕТОЧНЫМ, не опознано:")
        for key in state.unknown_keys:
            print(f"  - {key}")


def _doctor(bridge: ModBridge) -> int:
    print(f"мод: {bridge.url}")
    try:
        state = bridge.game_state()
    except ModBridgeError as error:
        print(f"\nНЕ ВЫШЛО: {error}")
        print(NOT_RUNNING_HINT.format(port=bridge.port, default=DEFAULT_PORT))
        return 1

    print("связь есть\n")
    _report(state)
    return 0


def _record(bridge: ModBridge, name: str) -> int:
    try:
        raw = bridge.raw_game_state()
    except ModBridgeError as error:
        print(f"НЕ ВЫШЛО: {error}")
        print(NOT_RUNNING_HINT.format(port=bridge.port, default=DEFAULT_PORT))
        return 1

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = GOLDEN_DIR / f"{stamp}-{name}.json"
    target.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"записано: {target}")
    print("не забудь дописать рядом счёт, который показала игра, — без него случай бесполезен")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="balatro-bot", description="Бот-советник для Balatro")
    parser.add_argument("--host", default=DEFAULT_HOST, help="хост мода")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="порт мода")

    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="проверить связь с игрой и показать состояние")
    record = commands.add_parser("record", help="записать состояние как эталонный случай")
    record.add_argument("name", help="короткое имя случая, например flush-with-blueprint")

    args = parser.parse_args(argv)
    bridge = ModBridge(host=args.host, port=args.port)

    if args.command == "record":
        return _record(bridge, str(args.name))
    return _doctor(bridge)


if __name__ == "__main__":
    raise SystemExit(main())
