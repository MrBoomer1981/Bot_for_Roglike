"""Выбор карт для розыгрыша.

Перебор честный: из восьми карт есть 218 подмножеств размера от одного до
пяти, каждое прогоняется через симулятор целиком. Никаких эвристик — при
таком размере они только вносили бы ошибку.

Наружу отдаётся не «лучший ход», а ранжированный список. Максимум очков не
всегда правильное решение: иногда выгоднее еле перебить блайнд, сохранив
карты и сбросы, иногда — сыграть слабее ради прокачки уровня нужной руки.
Это выбор игрока, дело бота — показать варианты и объяснить числа.

Три босса из `core/bosses.py` (`BossEffect.restricts_legal_plays`) бьют по
составу конкретного розыгрыша — иначе честно лучший по счёту вариант может
физически оказаться нелегальным ходом, который мод откажется принять. Такие
кандидаты отфильтровываются до попадания в ранжированный список, а не после
того, как их попробуют сыграть (см. `_is_legal_play`), — прямое следствие
допущения №10 в PLAN.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from itertools import combinations, permutations

from balatro_bot.core.cards import Card
from balatro_bot.core.hands import HandType
from balatro_bot.core.jokers import build_jokers, modifiers_from
from balatro_bot.core.scoring import ScoreOutcome, score_play
from balatro_bot.core.state import GameState, JokerCard

__all__ = ["Advice", "Candidate", "advise", "rank_joker_orders", "rank_plays"]

#: Больше пяти карт за раз сыграть нельзя.
MAX_PLAYED = 5

#: Имена трёх боссов из `core/bosses.py`, чей `restricts_legal_plays=True` —
#: сверено тестом (`tests/test_solver.py`), что список не разошёлся с
#: каталогом. Строковые константы, не импорт `BOSSES`: сама проверка
#: легальности всё равно завязана на конкретную механику каждого босса,
#: единый флаг тут ничего не переиспользует, кроме имени.
_THE_MOUTH = "The Mouth"
_THE_EYE = "The Eye"
_THE_PSYCHIC = "The Psychic"

#: `The Psychic` не даёт играть меньше этого числа карт.
_PSYCHIC_MIN_CARDS = 5

#: 6! = 720 перестановок. Больше — не гадать эвристикой, а прямо сказать,
#: что перебор порядка пропущен.
MAX_JOKERS_FOR_ORDER_SEARCH = 6

#: Копирующие джокеры (`Blueprint`/`Brainstorm`) берут эффект соседа справа/
#: слева, поэтому реверс стека НЕ доказывает независимость от порядка — при
#: них суррогатный перебор запускается всегда, без дешёвого вентиля.
_COPY_JOKER_KEYS = frozenset({"j_blueprint", "j_brainstorm"})

#: Сколько верхних подмножеств базового порядка прогонять через `score_play`
#: под каждой перестановкой в суррогатном переборе (см. `rank_joker_orders`).
#: Полный `advise()` на перестановку — это перебор всех 218 подмножеств; но
#: какой *набор карт* лучший, от порядка джокеров почти никогда не зависит
#: (зависит его *счёт*), поэтому хватает верхушки. Компромисс скорость/охват:
#: с джокером-разбросом (Misprint) каждый `score_play` разворачивает дерево
#: до 4096 веток, так что цена — `перестановки × это_число × дерево`.
_ORDER_SURROGATE_SUBSETS = 5


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


def _played_hand_types(state: GameState) -> frozenset[HandType]:
    """Какие типы руки уже сыграны в текущем раунде (`played_this_round > 0`)."""
    return frozenset(
        hand_type for hand_type, info in state.hand_info.items() if info.played_this_round > 0
    )


def _is_legal_play(state: GameState, cards: tuple[Card, ...], hand_type: HandType) -> bool:
    """Легален ли этот конкретный розыгрыш под текущим боссовым блайндом.

    Только три босса (см. модульный докстринг) бьют по составу конкретного
    розыгрыша — остальные 25 либо общий случай дебаффа карт, либо уже
    честно отражены живыми `hands_left`/`discards_left`/размером руки, либо
    не влияют на подсчёт вовсе (см. докстринг `core/bosses.py`).
    """
    blind = state.blind
    if blind is None:
        return True
    if blind.name == _THE_PSYCHIC:
        return len(cards) >= _PSYCHIC_MIN_CARDS
    if blind.name == _THE_MOUTH:
        played = _played_hand_types(state)
        return not played or hand_type in played
    if blind.name == _THE_EYE:
        return hand_type not in _played_hand_types(state)
    return True


def rank_plays(state: GameState, limit: int | None = None) -> tuple[Candidate, ...]:
    """Перебрать все розыгрыши и отсортировать по убыванию счёта.

    При равном счёте выше идёт ход, тратящий меньше карт. Нелегальные под
    текущим боссом варианты (`_is_legal_play`) отфильтрованы — если это
    оставляет список пустым (вырожденный случай: например, `The Psychic`
    при руке короче 5 карт), фильтр честно отступает и отдаёт нефильтрованный
    список — промолчать было бы хуже, чем показать вариант, легальность
    которого под большим вопросом.
    """
    jokers = build_jokers(state)
    modifiers = modifiers_from(jokers)

    candidates: list[Candidate] = []
    legal_candidates: list[Candidate] = []
    for size in range(1, min(MAX_PLAYED, len(state.hand)) + 1):
        for subset in combinations(state.hand, size):
            outcome = score_play(state, subset, jokers, modifiers)
            candidate = Candidate(subset, outcome)
            candidates.append(candidate)
            if _is_legal_play(state, subset, outcome.hand_type):
                legal_candidates.append(candidate)

    candidates = legal_candidates or candidates
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
    state: GameState, limit: int | None = None, *, base_advice: Advice | None = None
) -> tuple[tuple[JokerCard, ...], Advice] | None:
    """Перебрать порядки джокеров и вернуть тот, что даёт больший счёт.

    Джокеры срабатывают слева направо, и порядок влияет на итог не только у
    копирующих (`Blueprint`, `Brainstorm`) — смешение прибавки и умножителя
    мульта тоже даёт разный результат в разном порядке: `(x+4)×2 ≠ (x×2)+4`.

    Возвращает `None`, если джокеров больше `MAX_JOKERS_FOR_ORDER_SEARCH`:
    перебор всех перестановок стал бы слишком долгим, а угадывать эвристикой
    в этом проекте не заведено.

    Наивный перебор — полный `advise()` на каждую из `N!` перестановок —
    взрывается на 5–6 джокерах с джокером-разбросом (перебор 218 подмножеств
    × дерево вероятностей до 4096 веток × `N!`): в живом прогоне 15–40 с на
    ход (PLAN.md, улучшение F1). Здесь два ускорителя, оба сохраняют
    точность там, где она есть:

    1. **Дешёвый вентиль.** Если в стеке нет копирующего джокера и реверс
       стека даёт тот же верхний счёт, что исходный порядок, — порядок
       (практически наверняка) ни на что не влияет: возвращаем исходный без
       перебора. Для стека из одних прибавок (`AddChips`/`AddMult`) это
       строго так — сложение коммутативно; для порядко-зависимых стеков
       реверс почти всегда уже отличается.
    2. **Суррогатный перебор.** Когда порядок влиять может, на каждую
       перестановку считаем не весь `advise()`, а только `score_play` по
       `_ORDER_SURROGATE_SUBSETS` лучшим подмножествам исходного порядка
       (лучший *набор карт* от порядка джокеров почти не зависит). Полный
       `advise()` — только один раз, для победившей перестановки, чтобы
       вернуть точный ранжированный список для неё.

    `base_advice` — уже посчитанный `advise(state)` исходного порядка (тот
    же `limit`), чтобы не считать дважды; если он с более широким `limit`,
    это только на пользу суррогату (больше подмножеств на выбор).
    """
    if len(state.jokers) > MAX_JOKERS_FOR_ORDER_SEARCH:
        return None

    current_advice = base_advice if base_advice is not None else advise(state, limit)
    if len(state.jokers) < 2:
        return state.jokers, current_advice

    has_copy = any(joker.key in _COPY_JOKER_KEYS for joker in state.jokers)
    if not has_copy:
        reversed_jokers = tuple(reversed(state.jokers))
        reversed_score = advise(replace(state, jokers=reversed_jokers), limit=1).best.score
        # `isclose`, а не `==`: у стека из одних прибавок счёт от порядка не
        # зависит математически, но сложение float не ассоциативно — прямой и
        # обратный порядок могут разойтись на последний бит. Реальный
        # порядковый эффект всегда крупнее этого допуска (и всё равно ниже
        # порога `_MIN_REORDER_GAIN_FRAC` в автопилоте, если так мал).
        if math.isclose(reversed_score, current_advice.best.score, rel_tol=1e-9):
            return state.jokers, current_advice

    subsets = [c.cards for c in current_advice.candidates[:_ORDER_SURROGATE_SUBSETS]]
    modifiers = modifiers_from(build_jokers(state))  # порядко-независимы
    best_order = state.jokers
    best_score = current_advice.best.score
    for order in permutations(state.jokers):
        if order == state.jokers:
            continue
        variant = replace(state, jokers=order)
        variant_jokers = build_jokers(variant)
        score = max(
            score_play(variant, subset, variant_jokers, modifiers).expected for subset in subsets
        )
        if score > best_score:
            best_order, best_score = order, score

    if best_order == state.jokers:
        return state.jokers, current_advice
    return best_order, advise(replace(state, jokers=best_order), limit)
