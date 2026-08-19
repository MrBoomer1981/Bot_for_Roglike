"""Командная строка бота.

Пока здесь только то, что нужно для первого запуска рядом с игрой:

    balatro-bot advise          посоветовать ход: из игры или по набранной руке
    balatro-bot doctor          проверить, что мод отвечает, и показать состояние
    balatro-bot record ИМЯ      записать текущее состояние как эталонный случай

`advise` работает и без игры — с рукой, набранной с клавиатуры. Команды,
которым игра нужна, объясняют, что именно не так, вместо трассировки.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from balatro_bot.adapters.manual import build_state
from balatro_bot.adapters.mod_bridge import DEFAULT_HOST, DEFAULT_PORT, ModBridge, ModBridgeError
from balatro_bot.core.cards import Card, Enhancement
from balatro_bot.core.state import GameState
from balatro_bot.solver.play import Advice, Candidate, advise

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


def _number(value: float) -> str:
    """Число с пробелами между разрядами: 1530 -> `1 530`."""
    return f"{value:,.0f}".replace(",", " ")


def _cards(cards: Sequence[Card]) -> str:
    return " ".join(_format_card(card) for card in cards)


def _show_advice(advice: Advice, top: int, explain: bool) -> None:
    """Показать ранжированный список ходов."""
    remaining = None if advice.required is None else advice.required - advice.already_scored
    if remaining is not None:
        добрано = (
            f" (уже набрано {_number(advice.already_scored)})" if advice.already_scored else ""
        )
        print(f"нужно набрать: {_number(remaining)}{добрано}\n")

    ширина = max(len(_cards(item.cards)) for item in advice.candidates[:top])
    for позиция, item in enumerate(advice.candidates[:top], start=1):
        отметка = ""
        if remaining is not None:
            отметка = "  хватает" if item.beats(remaining) else ""
        счёт = str(item.outcome) if not item.outcome.certain else _number(item.score)
        строка = f"  {позиция}. {_cards(item.cards):<{ширина}}  "
        print(f"{строка}{item.outcome.hand_type.value:<15} {счёт:>12}{отметка}")

    экономный = advice.cheapest_sufficient
    if remaining is not None:
        if экономный is None:
            print("\nни один ход не перебивает блайнд гарантированно")
        elif экономный is not advice.best:
            print(f"\nхватит и меньшего: {экономный.describe()}")
            print("он тратит меньше карт и сохраняет колоду")

    if explain:
        _explain(advice.best)

    if not advice.exact:
        причины = sorted({reason for item in advice.candidates for reason in item.outcome.unknown})
        print("\nчисла НЕТОЧНЫЕ:")
        for причина in причины:
            print(f"  - {причина}")


def _explain(candidate: Candidate) -> None:
    """Показать, из чего сложился счёт."""
    print(f"\nразбор варианта {_cards(candidate.cards)}:")
    for step in candidate.outcome.trace:
        print(f"  {step.source:<12} {step.detail:<38} {_number(step.chips):>8} × {step.mult:g}")
    outcome = candidate.outcome
    print(f"  {'итог':<12} {'':<38} {_number(outcome.expected):>8}")


def _advise(bridge: ModBridge, args: argparse.Namespace) -> int:
    """Посоветовать ход по руке из игры или с клавиатуры."""
    if args.hand:
        try:
            state = build_state(
                args.hand,
                [item for item in (args.jokers or "").split(",") if item.strip()],
                blind=args.blind,
                hands_left=args.hands_left,
                discards_left=args.discards_left,
                money=args.money,
                chips_scored=args.scored,
            )
        except ValueError as error:
            print(f"НЕ ВЫШЛО: {error}")
            return 2
        print(f"рука: {_cards(state.hand)}")
        if state.jokers:
            print(f"джокеры: {', '.join(joker.label or joker.key for joker in state.jokers)}")
        print()
    else:
        try:
            state = bridge.game_state()
        except ModBridgeError as error:
            print(f"НЕ ВЫШЛО: {error}")
            print(NOT_RUNNING_HINT.format(port=bridge.port, default=DEFAULT_PORT))
            print('Можно посчитать и без игры: balatro-bot advise --hand "AH KH QH JH 9H"')
            return 1
        if not state.hand:
            print("в руке нет карт — бот полезен на этапе выбора карт")
            return 1
        print(f"рука: {_cards(state.hand)}\n")

    _show_advice(advise(state), args.top, args.explain)
    return 0


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

    tip = commands.add_parser("advise", help="посоветовать ход")
    tip.add_argument("--hand", help='рука с клавиатуры, например "AH KH QH JH 9H 7C 7D 2S"')
    tip.add_argument("--jokers", help="джокеры через запятую, слева направо")
    tip.add_argument("--blind", type=int, help="сколько очков нужно набрать")
    tip.add_argument("--hands-left", type=int, default=1, help="сколько рук осталось")
    tip.add_argument("--discards-left", type=int, default=0, help="сколько сбросов осталось")
    tip.add_argument("--money", type=int, default=0, help="сколько денег на руках")
    tip.add_argument("--scored", type=int, default=0, help="сколько очков уже набрано в раунде")
    tip.add_argument("--top", type=int, default=5, help="сколько вариантов показать")
    tip.add_argument("--explain", action="store_true", help="показать разбор лучшего варианта")

    commands.add_parser("doctor", help="проверить связь с игрой и показать состояние")
    record = commands.add_parser("record", help="записать состояние как эталонный случай")
    record.add_argument("name", help="короткое имя случая, например flush-with-blueprint")

    args = parser.parse_args(argv)
    bridge = ModBridge(host=args.host, port=args.port)

    if args.command == "advise":
        return _advise(bridge, args)
    if args.command == "record":
        return _record(bridge, str(args.name))
    return _doctor(bridge)


if __name__ == "__main__":
    raise SystemExit(main())
