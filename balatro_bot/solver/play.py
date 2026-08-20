"""Выбор карт для розыгрыша.

Перебор честный: из восьми карт есть 218 подмножеств размера от одного до
пяти, каждое прогоняется через симулятор целиком. Никаких эвристик — при
таком размере они только вносили бы ошибку.

Наружу отдаётся не «лучший ход», а ранжированный список. Максимум очков не
всегда правильное решение: иногда выгоднее еле перебить блайнд, сохранив
карты и сбросы, иногда — сыграть слабее ради прокачки уровня нужной руки.
Это выбор игрока, дело бота — показать варианты и объяснить числа.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations, permutations

from balatro_bot.core.cards import Card
from balatro_bot.core.jokers import build_jokers, modifiers_from
from balatro_bot.core.scoring import ScoreOutcome, score_play
from balatro_bot.core.state import GameState, JokerCard

__all__ = ["Advice", "Candidate", "advise", "rank_joker_orders", "rank_plays"]

#: Больше пяти карт за раз сыграть нельзя.
MAX_PLAYED = 5

#: 6! = 720 перестановок — секунды на честный перебор. Больше — не гадать
#: эвристикой, а прямо сказать, что перебор порядка пропущен.
MAX_JOKERS_FOR_ORDER_SEARCH = 6


@dataclass(frozen=True, slots=True)
class Candidate:
    """Один возможный ход."""

    cards: tuple[Card, ...]
    outcome: ScoreOutcome

    @property
    def score(self) -> float:
        """Матожидание счёта."""
        return self.outcome.expected

    def beats(self, required: int) -> bool:
        """Гарантированно ли перебивает порог.

        Берётся нижняя граница, а не среднее: «в среднем хватает» — плохой
        совет, когда проигрыш означает конец рана.
        """
        return self.outcome.minimum >= required

    def describe(self) -> str:
        cards = " ".join(f"{card.rank.value}{card.suit.value}" for card in self.cards)
        return f"{cards} → {self.outcome.hand_type.value} = {self.outcome}"


@dataclass(frozen=True, slots=True)
class Advice:
    """Что бот предлагает в текущем состоянии."""

    candidates: tuple[Candidate, ...]
    """Все варианты по убыванию счёта."""

    required: int | None
    """Сколько очков нужно, чтобы пробить блайнд."""

    already_scored: int = 0

    @property
    def best(self) -> Candidate:
        """Вариант с наибольшим счётом."""
        return self.candidates[0]

    @property
    def cheapest_sufficient(self) -> Candidate | None:
        """Самый экономный ход, которого гарантированно хватает на блайнд.

        Экономный — значит тратящий меньше карт: это сохраняет колоду и
        оставляет больше материала на следующие руки.
        """
        if self.required is None:
            return None
        remaining = self.required - self.already_scored
        enough = [item for item in self.candidates if item.beats(remaining)]
        if not enough:
            return None
        return min(enough, key=lambda item: (len(item.cards), -item.score))

    @property
    def can_clear_now(self) -> bool:
        """Есть ли ход, который прямо сейчас закрывает блайнд."""
        return self.cheapest_sufficient is not None

    @property
    def exact(self) -> bool:
        """Можно ли доверять числам до единицы."""
        return all(item.outcome.exact for item in self.candidates)


def rank_plays(state: GameState, limit: int | None = None) -> tuple[Candidate, ...]:
    """Перебрать все розыгрыши и отсортировать по убыванию счёта.

    При равном счёте выше идёт ход, тратящий меньше карт.
    """
    jokers = build_jokers(state)
    modifiers = modifiers_from(jokers)

    candidates: list[Candidate] = []
    for size in range(1, min(MAX_PLAYED, len(state.hand)) + 1):
        for subset in combinations(state.hand, size):
            outcome = score_play(state, subset, jokers, modifiers)
            candidates.append(Candidate(subset, outcome))

    candidates.sort(key=lambda item: (-item.score, len(item.cards)))
    return tuple(candidates[:limit] if limit is not None else candidates)


def advise(state: GameState, limit: int | None = None) -> Advice:
    """Собрать рекомендацию по текущему состоянию."""
    if not state.hand:
        raise ValueError("в руке нет карт — нечего советовать")

    return Advice(
        candidates=rank_plays(state, limit),
        required=state.blind.required_score if state.blind is not None else None,
        already_scored=state.chips_scored,
    )


def rank_joker_orders(
    state: GameState, limit: int | None = None
) -> tuple[tuple[JokerCard, ...], Advice] | None:
    """Перебрать порядки джокеров и вернуть тот, что даёт больший счёт.

    Джокеры срабатывают слева направо, и порядок влияет на итог не только у
    копирующих (`Blueprint`, `Brainstorm`) — смешение прибавки и умножителя
    мульта тоже даёт разный результат в разном порядке: `(x+4)×2 ≠ (x×2)+4`.

    Возвращает `None`, если джокеров больше `MAX_JOKERS_FOR_ORDER_SEARCH`:
    перебор всех перестановок стал бы слишком долгим, а угадывать эвристикой
    в этом проекте не заведено.
    """
    if len(state.jokers) > MAX_JOKERS_FOR_ORDER_SEARCH:
        return None

    best_order = state.jokers
    best_advice = advise(state, limit)

    for order in permutations(state.jokers):
        if order == state.jokers:
            continue
        variant_advice = advise(replace(state, jokers=order), limit)
        if variant_advice.best.score > best_advice.best.score:
            best_order, best_advice = order, variant_advice

    return best_order, best_advice
