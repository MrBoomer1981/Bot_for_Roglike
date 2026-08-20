"""Командная строка бота.

Пока здесь только то, что нужно для первого запуска рядом с игрой:

    balatro-bot install         поставить мод-стек одной командой
    balatro-bot advise          посоветовать ход: из игры или по набранной руке
    balatro-bot doctor          проверить, что мод отвечает, и показать состояние
    balatro-bot record ИМЯ      записать текущее состояние как эталонный случай

`advise` работает и без игры — с рукой, набранной с клавиатуры. Команды,
которым игра нужна, объясняют, что именно не так, вместо трассировки.
"""

from __future__ import annotations

import argparse
import json
import platform
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from balatro_bot.adapters.manual import build_state
from balatro_bot.adapters.mod_bridge import DEFAULT_HOST, DEFAULT_PORT, ModBridge, ModBridgeError
from balatro_bot.core.cards import Card, Enhancement
from balatro_bot.core.state import GameState
from balatro_bot.install import (
    InstallError,
    Paths,
    UrlFetcher,
    architecture,
    clear_quarantine,
    install,
    plan,
    resolve_paths,
    verify,
)
from balatro_bot.solver.play import (
    MAX_JOKERS_FOR_ORDER_SEARCH,
    Advice,
    Candidate,
    advise,
    rank_joker_orders,
)

GOLDEN_DIR = Path("tests/golden")

NOT_RUNNING_HINT = """
Мод не отвечает. Проверь по порядку:

  1. Игра запущена? Её нужно стартовать через мод, а не через Steam:
         uvx balatrobot serve
  2. В окне Balatro видно, что Steamodded загрузил моды?
  3. Порт совпадает? Сейчас пробуем {port}, по умолчанию у мода {default}.
     Сменить: balatro-bot doctor --port ДРУГОЙ
"""


#: Однобуквенные пометки улучшений. Steel и Stone нарочно разведены:
#: первая буква у них общая, а путать их нельзя — одно работает в руке,
#: другое при розыгрыше.
_ENHANCEMENT_MARKS: Final[dict[Enhancement, str]] = {
    Enhancement.BONUS: "B",
    Enhancement.MULT: "M",
    Enhancement.WILD: "W",
    Enhancement.GLASS: "G",
    Enhancement.STEEL: "T",
    Enhancement.STONE: "S",
    Enhancement.GOLD: "$",
    Enhancement.LUCKY: "L",
}


def _format_card(card: Card) -> str:
    """Компактная запись карты с пометками, если она не обычная."""
    text = f"{card.rank.value}{card.suit.value}"
    marks = _ENHANCEMENT_MARKS.get(card.enhancement, "")
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

    прокачано = sorted(
        ((hand_type, info) for hand_type, info in state.hand_info.items() if info.level > 1),
        key=lambda item: item[1].level,
        reverse=True,
    )
    if прокачано:
        # Уровень поднимают не только Planet-карты, но и награда Big Blind
        # тега (Orbital Tag) — источник в данных не различается, поэтому
        # причину не называем, только сам факт и уровень.
        строка = ", ".join(f"{hand_type.value} ур.{info.level}" for hand_type, info in прокачано)
        print(f"уровни рук выше первого: {строка}")

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

    показать = advice.candidates[: max(top, 1)]
    ширина = max(len(_cards(item.cards)) for item in показать)
    for позиция, item in enumerate(показать, start=1):
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


def _show_joker_order(state: GameState, current: Advice) -> None:
    """Проверить, не даст ли другой порядок джокеров счёт больше."""
    result = rank_joker_orders(state)
    if result is None:
        print(f"\nджокеров больше {MAX_JOKERS_FOR_ORDER_SEARCH} — честный перебор порядка пропущен")
        return

    order, order_advice = result
    if order == state.jokers or order_advice.best.score <= current.best.score:
        print("\nтекущий порядок джокеров уже лучший")
        return

    имена = " → ".join(joker.label or joker.key for joker in order)
    print(f"\nдругой порядок джокеров даст больше: {имена}")
    print(f"  сейчас:          {_number(current.best.score)}")
    print(f"  с этим порядком: {_number(order_advice.best.score)}")


def _explain(candidate: Candidate) -> None:
    """Показать, из чего сложился счёт."""
    print(f"\nразбор варианта {_cards(candidate.cards)}:")
    for step in candidate.outcome.trace:
        print(f"  {step.source:<12} {step.detail:<38} {_number(step.chips):>8} × {step.mult:g}")
    outcome = candidate.outcome
    print(f"  {'итог':<12} {'':<38} {_number(outcome.expected):>8}")


def _install(args: argparse.Namespace) -> int:
    """Поставить мод-стек: Lovely, Steamodded и мод BalatroBot."""
    if platform.system() != "Darwin" and not args.force:
        print(f"установщик написан под macOS, а здесь {platform.system()}.")
        print("Продолжить всё равно: --force")
        return 2

    home = Path.home()
    try:
        paths = resolve_paths(home, Path(args.game_dir) if args.game_dir else None)
    except InstallError as error:
        print(f"НЕ ВЫШЛО: {error}")
        return 1

    print(f"игра:  {paths.game}")
    print(f"моды:  {paths.mods}")

    if args.check:
        return _print_check(paths)

    arch = architecture()
    print(f"процессор: {arch}\n")

    fetcher = UrlFetcher()
    try:
        steps = plan(fetcher, arch)
    except InstallError as error:
        print(f"НЕ ВЫШЛО: {error}")
        return 1

    print("будет скачано:")
    for step in steps:
        print(f"  {step.component.name} {step.tag}")
        print(f"      зачем: {step.component.purpose}")
        print(f"      откуда: {step.url}")

    if args.dry_run:
        print("\nэто был показ плана, ничего не скачано и не изменено")
        return 0

    if not args.yes:
        print("\nБудет изменён каталог игры и каталог модов.")
        try:
            ответ = input("Продолжить? [y/N] ").strip().lower()
        except EOFError:
            ответ = ""
        if ответ not in {"y", "yes", "д", "да"}:
            print("отменено")
            return 1

    print()
    with tempfile.TemporaryDirectory(prefix="balatro-bot-") as tmp:
        try:
            result = install(paths, fetcher, Path(tmp), arch)
        except InstallError as error:
            print(f"НЕ ВЫШЛО: {error}")
            return 1
        except OSError as error:
            print(f"НЕ ВЫШЛО при записи: {error}")
            return 1

    if clear_quarantine(paths.game / "liblovely.dylib"):
        print("снят карантин macOS с liblovely.dylib")

    for step in result.steps:
        print(f"поставлено: {step.component.name} {step.tag}")

    print()
    if not result.ok:
        return _print_check(paths)

    print("всё на месте. Дальше:")
    print("  1. запусти игру:      uvx balatrobot serve")
    print("  2. начни ран и дойди до выбора карт")
    print("  3. проверь связь:     balatro-bot doctor")
    return 0


def _print_check(paths: Paths) -> int:
    """Показать, что стоит, а чего не хватает."""
    report = verify(paths)
    print()
    for target, есть in report.items():
        print(f"  {'есть   ' if есть else 'НЕТ    '} {target}")
    if all(report.values()):
        print("\nвсё на месте")
        return 0
    print("\nчего-то не хватает — поставить: balatro-bot install")
    return 1


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

    advice = advise(state)
    _show_advice(advice, args.top, args.explain)
    if args.joker_order and len(state.jokers) >= 2:
        _show_joker_order(state, advice)
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

    setup = commands.add_parser("install", help="поставить мод-стек")
    setup.add_argument("--dry-run", action="store_true", help="показать план и выйти")
    setup.add_argument("--check", action="store_true", help="только проверить, что уже стоит")
    setup.add_argument("--yes", action="store_true", help="не спрашивать подтверждения")
    setup.add_argument("--game-dir", help="каталог игры, если он в нестандартном месте")
    setup.add_argument("--force", action="store_true", help="запустить не на macOS")

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
    tip.add_argument(
        "--joker-order",
        action="store_true",
        help="проверить, не даст ли другой порядок джокеров счёт больше",
    )

    commands.add_parser("doctor", help="проверить связь с игрой и показать состояние")
    record = commands.add_parser("record", help="записать состояние как эталонный случай")
    record.add_argument("name", help="короткое имя случая, например flush-with-blueprint")

    args = parser.parse_args(argv)
    bridge = ModBridge(host=args.host, port=args.port)

    if args.command == "install":
        return _install(args)
    if args.command == "advise":
        return _advise(bridge, args)
    if args.command == "record":
        return _record(bridge, str(args.name))
    return _doctor(bridge)


if __name__ == "__main__":
    raise SystemExit(main())
