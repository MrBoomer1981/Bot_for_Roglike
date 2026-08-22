"""Единый ранжированный список «что делать прямо сейчас».

Игрок за столом выбирает не между «топ розыгрышей» и «топ сбросов» по
отдельности — это один и тот же выбор: чем сыграть или что сбросить, оба
варианта тратят один и тот же ресурс (ход). Раньше `advise()` и
`advise_discard()` показывались как два отдельных списка, которые
приходилось сравнивать вручную; этот модуль сливает их в один,
отсортированный по матожиданию счёта — розыгрыши и сбросы сравниваются как
есть, оба уже в одних единицах (итоговый счёт после розыгрыша).

Не пересчитывает ничего заново: `rank_actions` — это просто слияние
`rank_plays()` и `advise_discard()`, каждая уже точна или честно приближена
в своей части (см. `solver/play.py`, `solver/discard.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from balatro_bot.core.cards import Card
from balatro_bot.core.state import GameState
from balatro_bot.solver.discard import DiscardOption, advise_discard
from balatro_bot.solver.play import rank_plays

__all__ = ["ActionOption", "rank_actions"]


@dataclass(frozen=True, slots=True)
class ActionOption:
    """Одно действие: сыграть эти карты сейчас или сбросить их ради цели."""

    kind: Literal["play", "discard"]
    cards: tuple[Card, ...]
    score: float
    """Матожидание итогового счёта: точное число для `play`, оценка для `discard`."""

    label: str
    """Тип руки для `play`; имена целей через запятую для `discard`."""

    exact: bool
    """Можно ли доверять `score` до единицы. У `discard` всегда `False`
    (раздел 8 `docs/Discard Spec.md` — это оценка по построению)."""

    minimum: float | None = None
    """Гарантированный счёт в худшем случайном исходе — только у `play`
    (`ScoreOutcome.minimum`). У `discard` нет гарантии вообще, `score` —
    среднее по доборам, а не нижняя граница, поэтому здесь `None`: подставлять
    `score` вместо гарантии значило бы называть «хватает» то, что может и не
    хватить."""

    success_probability: float | None = None
    """Вероятность дособрать цель — только у `discard` (`DiscardOption.success_probability`)."""

    exact_deck: bool | None = None
    """Была ли колода известна точно — только у `discard`."""


def rank_actions(
    state: GameState, top: int = 5, *, include_discards: bool = True
) -> tuple[ActionOption, ...]:
    """Слить розыгрыши и сбросы в один список, отсортированный по счёту.

    Топ-`top` из каждого источника достаточно для корректного топ-`top`
    слияния: ни один вариант за пределами топ-`top` своего источника не
    может попасть в итоговый топ-`top`, потому что тогда в объединённом
    списке уже нашлось бы `top` вариантов не хуже него из одних только
    источников целиком (либо от другого источника, либо от первых `top`
    этого же) — считать оба списка полностью незачем.

    `include_discards=False` — чистый запас производительности (аналог
    `--no-joker-order`): пропустить `advise_discard` целиком там, где на
    счету каждый опрос (`watch` на коротком интервале). Сбросы и так не
    попадут в список сами, если `state.discards_left <= 0` — `advise_discard`
    возвращает пустой кортеж, а не требует отдельного флага.

    `top` не опускается ниже 1: `--top 0` — скорее опечатка пользователя,
    чем запрос на пустой список, и молча возвращать «вариантов нет» на неё
    менее полезно, чем показать хотя бы лучший вариант.
    """
    top = max(top, 1)
    plays = [
        ActionOption(
            kind="play",
            cards=candidate.cards,
            score=candidate.score,
            label=candidate.outcome.hand_type.value,
            exact=candidate.outcome.exact,
            minimum=candidate.outcome.minimum,
        )
        for candidate in rank_plays(state, limit=top)
    ]
    discards = (
        [_from_discard_option(option) for option in advise_discard(state, limit=top)]
        if include_discards
        else []
    )

    merged = sorted(plays + discards, key=lambda action: -action.score)
    return tuple(merged[:top])


def _from_discard_option(option: DiscardOption) -> ActionOption:
    return ActionOption(
        kind="discard",
        cards=option.discard,
        score=option.expected,
        label=", ".join(option.targets),
        exact=option.exact,
        success_probability=option.success_probability,
        exact_deck=option.exact_deck,
    )
