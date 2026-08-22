"""Совет по скипу блайнда: играть его или пропустить ради тега.

Раздел 8 плана («Стратегия рана») начинается с этого куска, а не с полной
симуляции рана: экран выбора блайнда — реальное, уже случившееся состояние
(требования очков и текст тега известны точно из `GameState.blinds`), а не
то, что нужно предсказывать по вероятностям. Полная симуляция ранов остаётся
отдельной, более поздней задачей (см. `PLAN.md`, раздел 8.1) — здесь честно
оцениваем только то решение, которое игра уже показала.

Числа, которые не сходятся с реальностью в один клик, — просто не
показываем как число: `_tag_dollars` возвращает `None`, если формула тега
(`core/tags.py`) требует счётчик уровня всего рана (сыгранные руки,
неиспользованные сбросы, число скипов), а мод его не присылает нигде в
схеме (`openrpc.json` — только `round.*`, per-раунд). Показывать текст
формулы вместо выдуманного числа — тот же принцип честности, что и
`ScoreOutcome.exact`/`DiscardOption.exact` в остальном проекте.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from balatro_bot.core.state import GameState
from balatro_bot.core.tags import TAGS, TagEffect

__all__ = ["SkipAdvice", "evaluate_skip"]

#: Базовая денежная награда за победу (game.lua: `bl_small.dollars = 3`,
#: `bl_big.dollars = 4`). Боссовый блайнд скипнуть нельзя, поэтому здесь его
#: намеренно нет.
_BASE_REWARD: Final[dict[str, int]] = {"SMALL": 3, "BIG": 4}

#: $1 за каждую руку из тех, что останутся неиспользованными при победе
#: (`state_events.lua`: `hands_left * (money_per_hand or 1)`).
_MONEY_PER_HAND: Final[int] = 1

#: Investment Tag — фиксированная сумма (`game.lua`: `tag_investment.config.dollars`).
_INVESTMENT_DOLLARS: Final[float] = 25.0

#: Economy Tag — потолок прибавки (`game.lua`: `tag_economy.config.max`).
_ECONOMY_CAP: Final[float] = 40.0

#: Порядок блайндов анте — нужен, чтобы найти «следующий» относительно
#: выбираемого сейчас.
_ORDER: Final[tuple[str, str, str]] = ("small", "big", "boss")

_TAGS_BY_NAME: Final[dict[str, TagEffect]] = {effect.name: effect for effect in TAGS.values()}


@dataclass(frozen=True, slots=True)
class SkipAdvice:
    """Разложенные числа для решения «играть или скипнуть» — без готового
    вердикта: часть тегов принципиально не сводится к одному числу
    (раздел `core/tags.py`), поэтому вердикт — за человеком."""

    blind_kind: str
    """`SMALL` или `BIG` — какой блайнд сейчас можно скипнуть."""

    required_score: int
    next_blind_kind: str
    next_required_score: int
    requirement_ratio: float
    """`next_required_score / required_score` — во сколько раз следующий
    блайнд анте тяжелее этого. Не требует руки: чистая арифметика по уже
    известным требованиям (раздел 4.3 обсуждения — идея «запас прочности»
    без симуляции руки, которой на этом экране всё равно ещё нет)."""

    play_reward_min: int
    """Гарантированная часть денежной награды за победу — без бонуса за
    неиспользованные руки: их точное число для ещё не начатого блайнда мод
    не показывает, поэтому в само число не включаем, только в подсказку."""

    play_reward_hint: str

    tag_name: str
    tag_effect: str
    tag: TagEffect | None
    """`None`, если тег не опознан (`core/tags.py` не содержит такого имени —
    честно, а не молча игнорировать, тот же принцип, что и с джокерами)."""

    tag_dollars: float | None
    tag_dollars_note: str


def evaluate_skip(state: GameState) -> SkipAdvice | None:
    """Собрать разложенные числа для решения — или `None`, если сейчас не
    экран выбора блайнда.

    Боссовый блайнд не участвует в поиске: его нельзя скипнуть, и статус
    `SELECT` у него означает «нужно сыграть», а не «можно выбрать скип».
    """
    for key in ("small", "big"):
        blind = state.blinds.get(key)
        if blind is not None and blind.status == "SELECT":
            selectable_key, selectable = key, blind
            break
    else:
        return None

    next_key = _ORDER[_ORDER.index(selectable_key) + 1]
    next_blind = state.blinds.get(next_key)
    ratio = (
        next_blind.required_score / selectable.required_score
        if next_blind is not None and selectable.required_score > 0
        else float("nan")
    )

    tag = _TAGS_BY_NAME.get(selectable.tag_name)
    dollars, note = _tag_dollars(selectable.tag_name, state)

    return SkipAdvice(
        blind_kind=selectable.kind,
        required_score=selectable.required_score,
        next_blind_kind=next_blind.kind if next_blind else "",
        next_required_score=next_blind.required_score if next_blind else 0,
        requirement_ratio=ratio,
        play_reward_min=_BASE_REWARD.get(selectable.kind, 0),
        play_reward_hint=(
            f"+ ${_MONEY_PER_HAND} за каждую неиспользованную руку сверху "
            "(сколько рук останется — известно только после начала блайнда)"
        ),
        tag_name=selectable.tag_name,
        tag_effect=selectable.tag_effect,
        tag=tag,
        tag_dollars=dollars,
        tag_dollars_note=note,
    )


def _tag_dollars(name: str, state: GameState) -> tuple[float | None, str]:
    """Точная денежная цена тега — только где формула не требует счётчика
    уровня рана, которого мод не присылает (см. модульный докстринг)."""
    if name == "Investment Tag":
        return _INVESTMENT_DOLLARS, "после победы над Boss Blind этого анте — условие, не гарантия"
    if name == "Economy Tag":
        bonus = min(_ECONOMY_CAP, max(0, state.money))
        return bonus, f"удвоение текущих ${state.money}, прибавка не больше ${_ECONOMY_CAP:g}"
    if not name:
        return None, ""
    return None, "формула требует счётчик уровня рана (см. core/tags.py) — мод его не присылает"
