"""EV розыгрыша после сброса: точный перебор добора для набора(ов) карт.

`discard_outcome` отвечает на вопрос «а что если сбросить вот эти карты?»
для одного набора, заданного вызывающим кодом (CLI, `advise --discard`).
Полный перебор по всем возможным наборам сброса, да ещё с Монте-Карло добора
внутри каждого, сам по себе не укладывается по времени (см. допущение №9 в
PLAN.md: 1000 выборок на один набор — уже 13 секунд). Полный перебор даже без
сэмплирования быстро упирается в ту же стену: уже для сбросов из двух карт
типичная колода даёт сотни комбинаций добора *на кандидата*, а кандидатов
(какие 2 из 8 карт сбросить) — 28.

`rank_single_discards` — компромисс: перебирает точно и честно, но только
сбросы **одной** карты. Кандидатов не больше, чем карт в руке (≤8), у каждого
до полусотни доборов — счёт укладывается в единицы секунд даже с джокерами
в конвейере, поэтому это единственный размер сброса, который можно честно
пересчитывать на каждое изменение состояния в `watch`. За более широким
перебором (2+ карты, конкретный кандидат) — `discard_outcome` явно.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations

from balatro_bot.core.cards import Card, standard_deck
from balatro_bot.core.state import GameState
from balatro_bot.solver.play import advise

__all__ = [
    "MAX_DRAW_COMBINATIONS",
    "DiscardOutcome",
    "discard_outcome",
    "known_deck",
    "rank_single_discards",
]

#: При таком числе комбинаций честный перебор укладывается в разумное время
#: (секунды, не минуты) даже с джокерами в конвейере. Больше — не гадать
#: эвристикой и не сэмплировать втихую, а честно отказаться, как и с
#: перебором порядка джокеров (`solver.play.MAX_JOKERS_FOR_ORDER_SEARCH`).
MAX_DRAW_COMBINATIONS = 2000


def known_deck(state: GameState) -> tuple[tuple[Card, ...], bool]:
    """Колода, из которой добираются карты, и точна ли она.

    Мост к моду (Фаза 5) знает точный состав оставшейся колоды — `state.deck`
    уже собран из области `cards`. Без него (ручной ввод) используем
    стандартную колоду из 52 карт минус то, что видно в руке прямо сейчас:
    это приближение, а не факт, потому что состав колоды за ран меняется, а
    история ходов при ручном вводе не отслеживается (раздел 6 плана).
    """
    if state.deck is not None:
        return state.deck, True
    seen = set(state.hand)
    approx = tuple(card for card in standard_deck() if card not in seen)
    return approx, False


@dataclass(frozen=True, slots=True)
class DiscardOutcome:
    """Матожидание счёта после сброса `discarded` и добора той же длины."""

    discarded: tuple[Card, ...]
    kept: tuple[Card, ...]
    expected: float
    """Средний лучший счёт по всем возможным доборам."""

    exact: bool
    """Колода была точно известна (мост), а не приближена стандартной."""

    draws_considered: int


def discard_outcome(state: GameState, discard: tuple[Card, ...]) -> DiscardOutcome | None:
    """EV розыгрыша после сброса `discard` и добора той же длины из колоды.

    Перебирает все возможные наборы добора точно — без повторов и без учёта
    порядка (порядок добора на итоговый счёт не влияет, важен только состав
    руки), и для каждого берёт лучший счёт из `advise`. Возвращает `None`,
    если число комбинаций добора больше `MAX_DRAW_COMBINATIONS`: перебор
    стал бы слишком долгим, а угадывать эвристикой в этом проекте не заведено.
    """
    kept = tuple(card for card in state.hand if card not in discard)
    deck, exact_deck = known_deck(state)

    draws = list(combinations(deck, len(discard)))
    if not draws or len(draws) > MAX_DRAW_COMBINATIONS:
        return None

    total = sum(advise(replace(state, hand=kept + draw), limit=1).best.score for draw in draws)

    return DiscardOutcome(
        discarded=discard,
        kept=kept,
        expected=total / len(draws),
        exact=exact_deck,
        draws_considered=len(draws),
    )


def rank_single_discards(state: GameState) -> tuple[DiscardOutcome, ...]:
    """EV сброса каждой одной карты из руки, по убыванию.

    Единственный размер сброса, для которого точный перебор дёшев независимо
    от числа джокеров в раскладке (см. модуль). Каждая карта руки — отдельный
    кандидат на сброс размера 1; для карт-дублей (два туза пик, например)
    результат один и тот же — дублировать в списке не нужно.
    """
    seen: set[Card] = set()
    outcomes: list[DiscardOutcome] = []
    for card in state.hand:
        if card in seen:
            continue
        seen.add(card)
        outcome = discard_outcome(state, (card,))
        if outcome is not None:
            outcomes.append(outcome)

    outcomes.sort(key=lambda item: -item.expected)
    return tuple(outcomes)
