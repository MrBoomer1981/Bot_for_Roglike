"""Разбор журналов ранов: пять вопросов, записанных до прогона.

Метод описан в `docs/measuring-runs.md` — короткий скрипт по всему каталогу,
а не чтение файлов глазами. Порядок разделов здесь повторяет раздел
«The next batch — what it has to answer» этого документа, чтобы вопросы
нельзя было переписать под уже полученный ответ.

Запуск:

    python tools/analyze_runs.py runs/decks2
    python tools/analyze_runs.py runs/decks2 runs/decks   # сравнить два корпуса

Скрипт ничего не чинит и ничего не предлагает — он только считает. Там, где
поля в журнале нет (старые корпуса не писали `pack`/`offered_tag`), раздел
честно печатает «нет данных», а не пустой ноль: это разные вещи.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

#: Семейство пака -> вид карт, который в нём обязан лежать (`ShopItem.kind`,
#: поле `set` мода). Standard-паки сюда не входят намеренно: в них игральные
#: карты, у бота ветки для них нет, и «ожидаемого вида» у них не будет.
PACK_CONTENTS: dict[str, str] = {
    "Celestial": "PLANET",
    "Buffoon": "JOKER",
    "Arcana": "TAROT",
    "Spectral": "SPECTRAL",
}

BOUGHT_PACK = re.compile(r"^купил пак:\s*(.+?)\s*$")

#: «гарантированный ход: нижний предел N уже перекрывает остаток M» —
#: обещание солвера, что этот розыгрыш даст не меньше N. Единственное
#: число в журнале, которое можно поставить против факта: прогноз «на K рук»
#: относится к нескольким рукам сразу и так не проверяется.
FLOOR_PROMISE = re.compile(r"нижний предел (\d+)")


@dataclass
class Run:
    """Один журнал рана."""

    path: Path
    data: dict[str, Any]

    @property
    def deck(self) -> str:
        return str(self.data.get("deck", "?"))

    @property
    def outcome(self) -> str:
        return str(self.data.get("outcome", "?"))

    @property
    def decisions(self) -> list[dict[str, Any]]:
        got = self.data.get("decisions")
        return got if isinstance(got, list) else []


@dataclass
class Corpus:
    """Каталог журналов целиком."""

    name: str
    runs: list[Run] = field(default_factory=list)

    @property
    def decisions(self) -> list[dict[str, Any]]:
        return [d for r in self.runs for d in r.decisions]

    def has_field(self, name: str) -> bool:
        """Пишет ли этот корпус такое поле вообще. Отличает «поля не было»
        от «поле было и всегда пустое» — второе уже результат."""
        return any(name in d for d in self.decisions)


def load(directory: Path) -> Corpus:
    corpus = Corpus(name=str(directory))
    for path in sorted(directory.rglob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "decisions" in raw:
            corpus.runs.append(Run(path, raw))
    return corpus


# --------------------------------------------------------------------------
# Свод
# --------------------------------------------------------------------------


def section_overview(corpus: Corpus) -> None:
    print(f"\n{'=' * 78}\nКОРПУС {corpus.name}\n{'=' * 78}")
    runs, decisions = corpus.runs, corpus.decisions
    if not runs:
        print("  журналов не найдено")
        return
    outcomes = Counter(r.outcome for r in runs)
    print(f"  ранов: {len(runs)}   решений: {len(decisions)}")
    print(f"  исходы: {dict(outcomes)}")
    stakes = {str(r.data.get("stake")) for r in runs}
    print(f"  ставки: {sorted(stakes)}")
    unobserved = [r for r in runs if not r.data.get("stake_observed", True)]
    if unobserved:
        print(f"  ВНИМАНИЕ: у {len(unobserved)} ранов ставка только заявленная (подхваченные)")
    seeds = {str(r.data.get("seed")) for r in runs}
    print(f"  уникальных сидов: {len(seeds)} из {len(runs)}", end="")
    print("  <-- ОДИН СИД НА ВСЕХ, это не винрейт (E1c)" if len(seeds) == 1 < len(runs) else "")

    print("\n  по колодам:")
    print(f"    {'колода':<12} {'ранов':>5} {'побед':>6} {'ср.анте':>8} {'макс':>5}")
    for deck in sorted({r.deck for r in runs}):
        got = [r for r in runs if r.deck == deck]
        antes = [int(r.data.get("ante", 0)) for r in got]
        wins = sum(1 for r in got if r.outcome == "won")
        print(
            f"    {deck:<12} {len(got):>5} {wins:>6} "
            f"{statistics.mean(antes):>8.1f} {max(antes):>5}"
        )


# --------------------------------------------------------------------------
# Вопрос 1 — отказы мода
# --------------------------------------------------------------------------


def section_rejections(corpus: Corpus) -> None:
    print(f"\n{'-' * 78}\n1. ОТКАЗЫ МОДА (сработал ли повторный опрос после пака)\n{'-' * 78}")
    decisions = corpus.decisions
    rejected = [d for d in decisions if d.get("rejected")]
    print(f"  отказов: {len(rejected)} из {len(decisions)} решений")
    print("  база до правки: 6 из 3121, и все шесть — работа с паком")
    if not rejected:
        print("  -> класс отказов исчез")
        return
    by_phase = Counter(str(d.get("phase")) for d in rejected)
    print(f"  по фазам: {dict(by_phase)}")
    pack_related = sum(1 for d in rejected if "пак" in str(d.get("action", "")).lower())
    print(f"  из них про пак: {pack_related} из {len(rejected)}")
    print("\n  каждый отказ:")
    for d in rejected:
        print(f"    анте {d.get('ante')} шаг {d.get('step'):>3} [{d.get('phase')}] "
              f"{str(d.get('action'))[:88]}")


# --------------------------------------------------------------------------
# Вопрос 2 — чужой пак: держится или отстаёт
# --------------------------------------------------------------------------


def _pack_family(label: str) -> str | None:
    """Семейство пака по его названию: «Jumbo Celestial Pack» -> Celestial."""
    for family in PACK_CONTENTS:
        if family.lower() in label.lower():
            return family
    return None


def section_foreign_pack(corpus: Corpus) -> None:
    print(f"\n{'-' * 78}")
    print("2. ЧУЖОЙ ПАК: ДЕРЖИТСЯ ИЛИ ОТСТАЁТ (вопрос, ради которого заведён `pack`)")
    print("-" * 78)
    if not corpus.has_field("pack"):
        print("  НЕТ ДАННЫХ: в этом корпусе поля `pack` нет — журналы старше E1f.")
        print("  Вопрос на нём принципиально не проверяется, это не ноль.")
        return
    episodes = 0
    for run in corpus.runs:
        expected: str | None = None
        streak = 0
        for d in run.decisions:
            action = str(d.get("action", ""))
            bought = BOUGHT_PACK.match(action)
            if bought:
                family = _pack_family(bought.group(1))
                expected = PACK_CONTENTS.get(family or "")
                streak = 0
                continue
            cards = d.get("pack") or []
            if not cards or expected is None:
                continue
            kinds = {str(c.get("kind")) for c in cards}
            if kinds and expected not in kinds:
                streak += 1
                episodes += 1
                print(f"    {run.path.name[:28]} шаг {d.get('step'):>3} "
                      f"ждали {expected}, лежит {sorted(kinds)} — подряд {streak}")
            else:
                streak = 0
    if not episodes:
        print("  расхождений вид-к-виду не найдено: содержимое пака всегда совпадало с купленным")
    else:
        print(f"\n  эпизодов расхождения: {episodes}")
        print("  «подряд 1» = отстало и починилось повторным опросом;")
        print("  «подряд 2+» = держится, повторный опрос не помогает.")


# --------------------------------------------------------------------------
# Вопрос 3 — таблица поражений
# --------------------------------------------------------------------------


@dataclass
class LossSnapshot:
    """Чем кончилось поражение. `share` — нижняя граница, и вот почему.

    Запись в журнал делается ПЕРЕД действием, поэтому счёт финальной руки в
    журнал не попадает никогда. Берём максимум `chips_scored` внутри
    последнего сыгранного раунда: внутри раунда очки накапливаются, а брать
    просто последнюю запись нельзя — ею может оказаться первая рука уже
    следующего раунда, и доля выйдет нулевой на ровном месте (поймано на
    GREEN-ране, где так получился 0 %).

    `hands_logged` — сколько рук этого раунда вообще попало в журнал. При
    единице граница почти пустая: одна незаписанная рука и есть весь раунд.
    """

    share: float
    discards_left: int
    money: int
    hands_logged: int


def _loss_snapshot(run: Run) -> LossSnapshot | None:
    scored_entries = [d for d in run.decisions if int(d.get("requirement") or 0) > 0]
    if not scored_entries:
        return None
    last = scored_entries[-1]
    final_round = (last.get("ante"), last.get("round"))
    in_round = [
        d for d in scored_entries if (d.get("ante"), d.get("round")) == final_round
    ]
    requirement = int(last.get("requirement") or 0)
    scored = max(int(d.get("chips_scored") or 0) for d in in_round)
    hands = sum(1 for d in in_round if str(d.get("action", "")).startswith("сыграл"))
    return LossSnapshot(
        share=scored / requirement,
        discards_left=int(last.get("discards_left") or 0),
        money=int(last.get("money") or 0),
        hands_logged=hands,
    )


def section_loss_table(corpus: Corpus) -> None:
    print(f"\n{'-' * 78}")
    print("3. ТАБЛИЦА ПОРАЖЕНИЙ (то, чем ранжируется весь открытый список)")
    print("-" * 78)
    losses = [r for r in corpus.runs if r.outcome == "lost"]
    if not losses:
        print("  поражений нет")
        return
    snaps = [s for s in (_loss_snapshot(r) for r in losses) if s is not None]
    shares = [s.share for s in snaps]
    discards = [s.discards_left for s in snaps]
    moneys = [s.money for s in snaps]
    thin = sum(1 for s in snaps if s.hands_logged <= 1)
    print(f"  поражений: {len(losses)} (замерено {len(shares)})")
    print("  ДОЛЯ ТРЕБОВАНИЯ — нижняя граница: счёт последней руки в журнал не пишется")
    print(f"    из них со слабой границей (в финальном раунде <=1 записанной руки): {thin}")
    print(f"    медиана: {statistics.median(shares):.0%}   среднее: {statistics.mean(shares):.0%}")
    print(f"    доля поражений ниже половины требования: "
          f"{sum(1 for s in shares if s < 0.5) / len(shares):.0%}")
    print(f"  сбросов осталось на поражении: медиана {statistics.median(discards):.1f}, "
          f"нетронутыми {sum(1 for d in discards if d > 0)} из {len(discards)}")
    print(f"  денег на поражении: медиана ${statistics.median(moneys):.0f}, "
          f"максимум ${max(moneys)}")
    print("\n  по колодам (медианная доля требования):")
    for deck in sorted({r.deck for r in losses}):
        got = [s for r in losses if r.deck == deck for s in [_loss_snapshot(r)] if s]
        if got:
            print(f"    {deck:<12} {statistics.median([g.share for g in got]):>6.0%}  "
                  f"({len(got)} поражений)")


# --------------------------------------------------------------------------
# Вопрос 4 — сбросы (B3)
# --------------------------------------------------------------------------


def section_discards(corpus: Corpus) -> None:
    print(f"\n{'-' * 78}\n4. СБРОСЫ, B3 (что сброс отдал против того, что получил)\n{'-' * 78}")
    discards, zero_rounds = [], []
    for run in corpus.runs:
        for d in run.decisions:
            action = str(d.get("action", ""))
            look = d.get("outlook") or {}
            if action.startswith("сбросил"):
                best_play = look.get("best_play")
                best_discard = look.get("best_discard")
                if best_play is not None and best_discard is not None:
                    discards.append((float(best_play), float(best_discard)))
            elif action.startswith("сыграл") and int(d.get("discards_left") or 0) > 0:
                if look.get("best_discard") is not None:
                    zero_rounds.append((float(look["best_play"]), float(look["best_discard"])))
    print(f"  сбросов с обеими оценками: {len(discards)}")
    if discards:
        gains = [dsc - play for play, dsc in discards]
        print(f"    прибавка сброса над игрой сейчас: медиана {statistics.median(gains):+.0f}, "
              f"среднее {statistics.mean(gains):+.0f}")
        print(f"    сбросов, отдавших больше, чем получили: "
              f"{sum(1 for g in gains if g < 0)} из {len(gains)}")
    print(f"\n  сыграно при доступном сбросе: {len(zero_rounds)}")
    if zero_rounds:
        margins = [play - dsc for play, dsc in zero_rounds]
        print(f"    игра была выше сброса на: медиана {statistics.median(margins):+.0f}")
        print(f"    из них сброс был ВЫШЕ игры (сброс отвергнут порогом): "
              f"{sum(1 for m in margins if m < 0)} из {len(margins)}")
    unspent = sum(int(r.data.get("rounds_with_discards_unspent") or 0) for r in corpus.runs)
    print(f"\n  раундов, где сбросы вовсе не тронуты (из отчётов): {unspent}")


# --------------------------------------------------------------------------
# Вопрос 5 — приход паков (C3)
# --------------------------------------------------------------------------


def section_pack_arrival(corpus: Corpus) -> None:
    print(f"\n{'-' * 78}\n5. ПРИХОД ПАКОВ, C3 (купленный пак против пака от тега)\n{'-' * 78}")
    bought: Counter[str] = Counter()
    opened_runs = 0
    for run in corpus.runs:
        opened = False
        for d in run.decisions:
            match = BOUGHT_PACK.match(str(d.get("action", "")))
            if match:
                bought[_pack_family(match.group(1)) or "?"] += 1
            if str(d.get("phase")) == "SMODS_BOOSTER_OPENED":
                opened = True
        opened_runs += int(opened)
    total_bought = sum(bought.values())
    opened_entries = sum(
        1 for d in corpus.decisions if str(d.get("phase")) == "SMODS_BOOSTER_OPENED"
    )
    print(f"  куплено паков: {total_bought} {dict(bought)}")
    print(f"  решений в фазе открытого пака: {opened_entries} (в {opened_runs} ранах)")
    if not corpus.has_field("offered_tag"):
        print("  НЕТ ДАННЫХ по тегам: поля `offered_tag` в корпусе нет (журналы старше E1f).")
        print("  Отделить пак от тега от купленного на этом корпусе нельзя.")
        return
    tags = Counter(
        str(d["offered_tag"]) for d in corpus.decisions if d.get("offered_tag")
    )
    print(f"  предложенных тегов (это НЕ теги на руках — мод их не отдаёт): {sum(tags.values())}")
    for tag, count in tags.most_common(10):
        print(f"    {tag:<28} {count}")


# --------------------------------------------------------------------------
# Аномалии — числа, которых не может быть
# --------------------------------------------------------------------------


@dataclass
class Finding:
    """Одна пойманная аномалия."""

    code: str
    title: str
    hits: list[str] = field(default_factory=list)

    def report(self, runs: int, note: str = "") -> None:
        """`runs` обязателен: абсолютные числа между корпусами разного
        размера несравнимы, и «167 против 2» без «на ран» читается как
        восьмидесятикратное улучшение там, где его может не быть."""
        rate = len(self.hits) / runs if runs else 0.0
        print(f"\n  [{self.code}] {self.title}")
        print(
            f"        случаев: {len(self.hits)}  ({rate:.2f} на ран)"
            + (f"   {note}" if note else "")
        )
        for line in self.hits[:6]:
            print(f"          {line}")
        if len(self.hits) > 6:
            print(f"          ... ещё {len(self.hits) - 6}")


def _blinds(run: Run) -> Iterable[list[dict[str, Any]]]:
    """Решения, разрезанные по блайндам: подряд идущие `SELECTING_HAND` с
    одним и тем же требованием.

    Резать по `(ante, round)` НЕЛЬЗЯ, хотя это первое, что приходит в
    голову: пара Small/Big лежит под одним и тем же номером раунда, и на
    таком ключе «очки упали до нуля» срабатывает на каждом втором блайнде —
    поймано на базовом корпусе, где так набралось 363 ложных срабатывания.
    Фазы кроме `SELECTING_HAND` выброшены намеренно: в магазине `chips` уже
    ноль, а `requirement` ещё от прошлого блайнда, и любой инвариант о
    накоплении очков там бессмыслен."""
    segment: list[dict[str, Any]] = []
    current: int | None = None
    for d in run.decisions:
        if str(d.get("phase")) != "SELECTING_HAND":
            continue
        req = int(d.get("requirement") or 0)
        if current is not None and req != current and segment:
            yield segment
            segment = []
        current = req
        segment.append(d)
    if segment:
        yield segment


def section_anomalies(corpus: Corpus) -> list[Finding]:
    """Инварианты, нарушение которых — дефект, а не неудачная игра.

    Каждый пункт сформулирован так, чтобы срабатывание нельзя было объяснить
    «просто плохо сыграл»: очки внутри раунда не могут убывать, рук не может
    становиться больше, купить дороже, чем есть денег, нельзя.
    """
    print(f"\n{'-' * 78}")
    print("6. АНОМАЛИИ (числа, которых не может быть)")
    print("-" * 78)

    chips = Finding("X1", "очки внутри раунда убывают")
    hands = Finding("X2", "рук внутри раунда становится больше")
    discards = Finding("X3", "сбросов внутри раунда становится больше")
    requirement = Finding("X4", "требование убывает ВНУТРИ одного анте")
    overshoot = Finding("X5", "очки уже перекрыли требование, но раунд не засчитан")
    negmoney = Finding("X6", "деньги ушли в минус")
    dead_play = Finding("X7", "рука сыграна, очки не изменились")
    ghost_discard = Finding("X8", "сброс оценивался при нуле сбросов")
    full_board_roll = Finding("X9", "реролл при полной доске (сигнатура A22)")
    bad_outcome = Finding("X10", "ран кончился не игрой (stuck/error)")
    broken_floor = Finding("X11", "факт ниже заявленного «нижнего предела» хода")

    for run in corpus.runs:
        tag = run.path.name[:26]
        if run.outcome in ("stuck", "error"):
            bad_outcome.hits.append(f"{tag} -> {run.outcome}: {run.data.get('note') or '-'}")
        # Внутри одного анте требования только растут: малый -> большой -> босс.
        # ПОПЕРЁК анте — нет: босс анте N (2x базы) бывает выше малого блайнда
        # анте N+1, и «22000 -> 20000» это норма игры, а не дефект. Ловилось
        # на базовом корпусе, где такая проверка дала 24 ложных попадания.
        by_ante: dict[Any, list[int]] = {}
        for segment in _blinds(run):
            head = segment[0]
            by_ante.setdefault(head.get("ante"), []).append(int(head.get("requirement") or 0))
        for ante, reqs in by_ante.items():
            for before, after in pairwise(reqs):
                if after < before:
                    requirement.hits.append(f"{tag} анте {ante}: {before} -> {after}")
        for d in run.decisions:
            rolled = str(d.get("phase")) == "SHOP" and str(
                d.get("action", "")
            ).startswith("перекатил")
            if rolled and len(d.get("board") or []) >= 5:
                full_board_roll.hits.append(
                    f"{tag} анте {d.get('ante')} шаг {d.get('step')} ${d.get('money')}"
                )
        for entries in _blinds(run):
            head = entries[0]
            where = f"{tag} анте {head.get('ante')} треб {head.get('requirement')}"
            prev_chips = prev_hands = prev_disc = None
            for d in entries:
                got_chips = int(d.get("chips_scored") or 0)
                got_hands = int(d.get("hands_left") or 0)
                got_disc = int(d.get("discards_left") or 0)
                req = int(d.get("requirement") or 0)
                if prev_chips is not None and got_chips < prev_chips:
                    chips.hits.append(f"{where} шаг {d.get('step')}: {prev_chips} -> {got_chips}")
                if prev_hands is not None and got_hands > prev_hands:
                    hands.hits.append(f"{where} шаг {d.get('step')}: {prev_hands} -> {got_hands}")
                if prev_disc is not None and got_disc > prev_disc:
                    discards.hits.append(f"{where} шаг {d.get('step')}: {prev_disc} -> {got_disc}")
                if req > 0 and got_chips >= req and d.get("blind_beaten") is False:
                    overshoot.hits.append(f"{where} шаг {d.get('step')}: {got_chips} >= {req}")
                if int(d.get("money") or 0) < 0:
                    negmoney.hits.append(f"{where} шаг {d.get('step')}: ${d.get('money')}")
                look = d.get("outlook") or {}
                if look.get("best_discard") is not None and got_disc == 0:
                    ghost_discard.hits.append(f"{where} шаг {d.get('step')}")
                prev_chips, prev_hands, prev_disc = got_chips, got_hands, got_disc
            plays = [d for d in entries if str(d.get("action", "")).startswith("сыграл")]
            for first, second in pairwise(plays):
                gained = int(second.get("chips_scored") or 0) - int(first.get("chips_scored") or 0)
                if gained == 0:
                    dead_play.hits.append(
                        f"{where} шаг {second.get('step')}: {str(first.get('action'))[:40]}"
                    )
                promise = FLOOR_PROMISE.search(str(first.get("reason") or ""))
                if promise is not None and gained < int(promise.group(1)):
                    floor = int(promise.group(1))
                    broken_floor.hits.append(
                        f"{where} шаг {first.get('step')}: обещано >={floor}, "
                        f"получено {gained} ({floor / max(gained, 1):.0f}x) "
                        f"| {str(first.get('action'))[:30]}"
                    )

    found = [
        f
        for f in (
            chips, hands, discards, requirement, overshoot, negmoney,
            dead_play, ghost_discard, full_board_roll, bad_outcome, broken_floor,
        )
        if f.hits
    ]
    if not found:
        print("\n  ни один инвариант не нарушен")
    for finding in found:
        notes = {
            "X9": "база runs/decks: 167 = 4.77 на ран",
            "X11": "база runs/decks: 24 = 0.69 на ран",
            "X7": "база runs/decks: 6 = 0.17 на ран",
        }
        finding.report(len(corpus.runs), notes.get(finding.code, ""))
    return found


def main(argv: Sequence[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    for name in argv[1:]:
        directory = Path(name)
        if not directory.is_dir():
            print(f"нет каталога: {directory}")
            return 1
        corpus = load(directory)
        section_overview(corpus)
        section_rejections(corpus)
        section_foreign_pack(corpus)
        section_loss_table(corpus)
        section_discards(corpus)
        section_pack_arrival(corpus)
        section_anomalies(corpus)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
