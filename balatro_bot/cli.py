"""Командная строка бота.

Пока здесь только то, что нужно для первого запуска рядом с игрой:

    balatro-bot install         поставить мод-стек одной командой
    balatro-bot advise          посоветовать ход: из игры или по набранной руке
    balatro-bot watch           следить за игрой — советы обновляются сами
    balatro-bot autoplay        играть самому — розыгрыш/сброс автоматически, пауза клавишей p
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

from balatro_bot.adapters.manual import build_state
from balatro_bot.adapters.mod_bridge import DEFAULT_HOST, DEFAULT_PORT, ModBridge, ModBridgeError
from balatro_bot.core.cards import parse_cards
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
from balatro_bot.runner import (
    DECKS,
    STAKES,
    DecisionEntry,
    play_run,
    render_batch_summary,
    render_run_report,
    run_batch,
)
from balatro_bot.solver.actions import rank_actions
from balatro_bot.solver.consumables import evaluate_planet_consumables
from balatro_bot.solver.discard import discard_outcome, rank_discards
from balatro_bot.solver.pack import evaluate_pack
from balatro_bot.solver.play import advise
from balatro_bot.solver.shop import evaluate_shop
from balatro_bot.solver.skip import evaluate_skip
from balatro_bot.ui import tui
from balatro_bot.ui.render import (
    format_cards,
    render_consumable_advice,
    render_discard_outcome,
    render_discard_ranking,
    render_joker_order,
    render_pack_advice,
    render_shop_advice,
    render_skip_advice,
    render_state,
    render_top_actions,
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
        print(f"рука: {format_cards(state.hand)}")
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
        print(f"рука: {format_cards(state.hand)}\n")

    advice = advise(state)
    actions = rank_actions(state, top=args.top)
    render_top_actions(advice, actions, args.explain)
    if args.joker_order and len(state.jokers) >= 2:
        render_joker_order(state, advice)
    if args.discard:
        try:
            discard = parse_cards(args.discard)
        except ValueError as error:
            print(f"НЕ ВЫШЛО: {error}")
            return 2
        missing = [card for card in discard if card not in state.hand]
        if missing:
            print(f"\nНЕ ВЫШЛО: этих карт нет в руке: {format_cards(missing)}")
            return 2
        if state.discards_left <= 0:
            print("\nсбросов не осталось — считаю чисто гипотетически")
        render_discard_outcome(discard_outcome(state, discard), discard, advice.best)
    if args.discard_search:
        print(
            "\nищу точный сброс честным перебором всех наборов до 5 карт (может занять время) — "
            "кандидат, где даже сжатый перебор добора не уложился в бюджет, тихо пропускается..."
        )
        render_discard_ranking(rank_discards(state), advice.best, top=args.top)
    return 0


def _watch(bridge: ModBridge, args: argparse.Namespace) -> int:
    """Следить за игрой: советы обновляются сами, пока не нажат Ctrl+C."""
    try:
        tui.watch(
            bridge,
            interval=args.interval,
            top=args.top,
            explain=args.explain,
            joker_order=args.joker_order,
            consider_discards=args.consider_discards,
            consider_shop=args.consider_shop,
        )
    except KeyboardInterrupt:
        print("\nостановлено")
    return 0


def _autoplay(bridge: ModBridge, args: argparse.Namespace) -> int:
    """Два режима одной команды (см. `--help`):

    - без `--deck` — живой режим: следить за уже идущей игрой и играть
      розыгрыш/сброс/магазин/паки автоматически, пауза/перехват клавишей
      `p` прямо во время работы (`ui/tui.py`);
    - с `--deck` — управляемый ран: начать новый ран через `ModBridge.start`
      и доиграть его автопилотом до конца с отчётом и логом решений
      (`balatro_bot/runner.py`, Фаза 9.7). `--all-stakes`/`--runs` — пакетный
      прогон с винрейтом по каждой ставке."""
    if args.deck is None:
        try:
            tui.autoplay(
                bridge,
                interval=args.interval,
                top=args.top,
                explain=args.explain,
                joker_order=args.joker_order,
                consider_discards=args.consider_discards,
                consider_shop=args.consider_shop,
            )
        except KeyboardInterrupt:
            print("\nостановлено")
        return 0

    return _autoplay_managed(bridge, args)


def _print_run_step(_state: GameState, entry: DecisionEntry) -> None:
    """Живой прогресс одиночного управляемого рана — по строке на решение,
    чтобы длинный ран не выглядел зависшим."""
    метка = " [отказ]" if entry.rejected else ""
    print(
        f"  [{entry.step:>3}] анте {entry.ante} р{entry.round_number} "
        f"${entry.money:<4} {entry.action}{метка}"
    )


def _autoplay_managed(bridge: ModBridge, args: argparse.Namespace) -> int:
    """Управляемый ран (или пакет ранов) — ветка `autoplay --deck`."""
    stakes = STAKES if args.all_stakes else (args.stake,)
    batch = args.all_stakes or args.runs > 1

    try:
        if batch:
            summaries = run_batch(
                bridge,
                deck=args.deck,
                stakes=stakes,
                runs_per_stake=args.runs,
                seed=args.seed,
                include_discards=args.consider_discards,
                max_steps=args.max_steps,
                on_run=lambda report: render_run_report(report, verbose=args.explain),
            )
            render_batch_summary(summaries)
        else:
            report = play_run(
                bridge,
                deck=args.deck,
                stake=args.stake,
                seed=args.seed,
                include_discards=args.consider_discards,
                max_steps=args.max_steps,
                on_step=_print_run_step,
            )
            render_run_report(report, verbose=args.explain)
    except KeyboardInterrupt:
        print("\nостановлено")
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
    render_state(state)
    skip_advice = evaluate_skip(state)
    if skip_advice is not None:
        render_skip_advice(skip_advice)
    shop_advice = evaluate_shop(state)
    if shop_advice is not None:
        render_shop_advice(shop_advice)
    render_pack_advice(evaluate_pack(state))
    render_consumable_advice(evaluate_planet_consumables(state))
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
    tip.add_argument(
        "--discard",
        help='карты из руки для сравнения "сыграть сейчас" со сбросом, например "3S 2S"',
    )
    tip.add_argument(
        "--discard-search",
        action="store_true",
        help=(
            "точный перебор ВСЕХ сбросов до 5 карт (не только целей advise_discard) — "
            "медленнее, обычно секунды; кандидат вне бюджета честно пропускается"
        ),
    )

    follow = commands.add_parser("watch", help="следить за игрой — советы обновляются сами")
    follow.add_argument(
        "--interval", type=float, default=1.0, help="как часто опрашивать мод, в секундах"
    )
    follow.add_argument("--top", type=int, default=5, help="сколько вариантов показывать")
    follow.add_argument("--explain", action="store_true", help="показывать разбор лучшего варианта")
    follow.add_argument(
        "--no-joker-order",
        dest="joker_order",
        action="store_false",
        help="не проверять порядок джокеров (перебор до 720 перестановок на каждый опрос)",
    )
    follow.add_argument(
        "--no-discard",
        dest="consider_discards",
        action="store_false",
        help="не рассматривать сбросы в общем списке действий (пропустить advise_discard)",
    )
    follow.add_argument(
        "--no-shop",
        dest="consider_shop",
        action="store_false",
        help="не оценивать джокеров в магазине (несколько advise() на каждого предложенного)",
    )

    auto = commands.add_parser(
        "autoplay",
        help="играть самому — вживую (пауза клавишей p) либо управляемый ран целиком (--deck)",
    )
    auto.add_argument(
        "--interval", type=float, default=1.0, help="как часто опрашивать мод, в секундах"
    )
    auto.add_argument(
        "--deck",
        choices=DECKS,
        help="начать новый ран этой колодой и играть до конца (без --deck — живой режим)",
    )
    auto.add_argument(
        "--stake", choices=STAKES, default="WHITE", help="ставка для управляемого рана"
    )
    auto.add_argument(
        "--seed", help="сид рана (по умолчанию случайный — нужен для честного замера винрейта)"
    )
    auto.add_argument(
        "--runs",
        type=int,
        default=1,
        help="сколько ранов сыграть (на каждой ставке, если задан --all-stakes)",
    )
    auto.add_argument(
        "--all-stakes",
        action="store_true",
        help=f"прогнать все восемь ставок ({' → '.join(STAKES)}), по --runs на каждую",
    )
    auto.add_argument(
        "--max-steps",
        type=int,
        default=2000,
        help="потолок шагов на ран, чтобы зациклившийся ран не крутился вечно",
    )
    auto.add_argument("--top", type=int, default=5, help="сколько вариантов показывать")
    auto.add_argument("--explain", action="store_true", help="показывать разбор лучшего варианта")
    auto.add_argument(
        "--no-joker-order",
        dest="joker_order",
        action="store_false",
        help="не проверять порядок джокеров (перебор до 720 перестановок на каждый опрос)",
    )
    auto.add_argument(
        "--no-discard",
        dest="consider_discards",
        action="store_false",
        help="не рассматривать сбросы среди действий автопилота (пропустить advise_discard)",
    )
    auto.add_argument(
        "--no-shop",
        dest="consider_shop",
        action="store_false",
        help="не оценивать джокеров в магазине (несколько advise() на каждого предложенного)",
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
    if args.command == "watch":
        return _watch(bridge, args)
    if args.command == "autoplay":
        return _autoplay(bridge, args)
    if args.command == "record":
        return _record(bridge, str(args.name))
    return _doctor(bridge)


if __name__ == "__main__":
    raise SystemExit(main())
