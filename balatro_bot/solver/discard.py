"""EV розыгрыша после сброса: точный перебор добора для набора(ов) карт, и
поиск лучшего сброса по целям (`docs/Discard Spec.md`, Фаза 6).

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

`advise_discard` закрывает общий случай — «что сбрасывать» без задания
конкретного набора — не перебором сбросов, а перебором **целей** (флеш,
стрит, N одинаковых, фулл-хаус, «оставить как есть»): сброс — это следствие
цели, а не то, что нужно искать отдельно. Полное обоснование алгоритма и
критерии приёмки — в `docs/Discard Spec.md`, здесь только реализация.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from itertools import combinations

from balatro_bot.core.cards import Card, Rank, Suit, effective_suits, standard_deck
from balatro_bot.core.hands import HandModifiers, evaluate
from balatro_bot.core.jokers import Joker, build_jokers, modifiers_from
from balatro_bot.core.scoring import score_play
from balatro_bot.core.state import GameState
from balatro_bot.solver.play import MAX_PLAYED, advise

__all__ = [
    "MAX_DISCARD_SIZE",
    "MAX_DRAW_COMBINATIONS",
    "SAMPLE_HANDS_PER_BUCKET",
    "DiscardOption",
    "DiscardOutcome",
    "OutcomeBucket",
    "Target",
    "advise_discard",
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


#: Больше пяти карт сбросить нельзя — игровое правило, не запас
#: производительности (в отличие от `MAX_DRAW_COMBINATIONS` выше).
MAX_DISCARD_SIZE = 5

#: Сколько представительных рук перебирать на одну корзину «пришло ровно i
#: аутов» (раздел 4.5 спеки). Прототип спеки использовал 6 и получал до 16%
#: отклонения от честного перебора; на этом числе отклонение на проверочных
#: руках (`tests/test_discard.py`) доходило до 25% — мало для корзин в
#: сотни комбинаций. 16 держит отклонение обычно в пределах 10% ценой
#: времени: полный `advise_discard` на восемь карт и пару джокеров — около
#: 80 мс, в разы меньше бюджета в 200 мс из раздела 7 критерия 3.
SAMPLE_HANDS_PER_BUCKET = 16

#: Общий для всех попыток посэмплировать сид: результат должен быть
#: воспроизводимым (тот же сброс с тем же состоянием даёт тот же ответ), а не
#: дребезжать между запусками — это единственное место в проекте, где вообще
#: используется сэмплирование, и оно не должно вносить лишний источник шума.
_SAMPLE_SEED = 0


@dataclass(frozen=True, slots=True)
class Target:
    """Тройка «что держим, что нам нужно, сколько штук» (раздел 4.2 спеки).

    Цель — это не сброс: сброс получается как дополнение `keep` до всей руки.
    Разные цели могут давать один и тот же сброс — это разбирается на этапе
    группировки в `advise_discard`, а не здесь.
    """

    name: str
    keep: tuple[Card, ...]
    outs: tuple[Card, ...]
    needed: int


@dataclass(frozen=True, slots=True)
class OutcomeBucket:
    """Один член суммы из раздела 4.5: пришло ровно `outs_hit` аутов."""

    outs_hit: int
    probability: float
    score: float


@dataclass(frozen=True, slots=True)
class DiscardOption:
    """Вариант сброса: что оставить, чего ждать и во что это оценивается."""

    discard: tuple[Card, ...]
    keep: tuple[Card, ...]
    expected: float
    """Матожидание счёта после добора — сумма по `distribution`."""

    distribution: tuple[OutcomeBucket, ...]
    targets: tuple[str, ...]
    """Имена целей, которым служит этот сброс — для объяснения человеку."""

    needed: int
    """Сколько аутов нужно было хотя бы одной из объединённых целей — порог
    для `success_probability`."""

    exact: bool = False
    """Всегда `False`: это оценка по представительной выборке, а не точный
    перебор (раздел 8 спеки — честность обязательна, не пожелание)."""

    exact_deck: bool = False
    """Была ли колода известна точно (мост), а не приближена стандартной."""

    @property
    def success_probability(self) -> float:
        """Вероятность прихода нужной карты: P(пришло не меньше `needed` аутов).

        Сумма по корзинам `distribution` — каждая уже точная гипергеометрическая
        вероятность (раздел 4.5 спеки), поэтому сумма точна тоже, даже если
        сам счёт в каждой корзине — оценка по выборке."""
        return sum(
            bucket.probability for bucket in self.distribution if bucket.outs_hit >= self.needed
        )


#: Пары мастей, которые считаются одной мастью при `Smeared Joker`.
_SMEARED_GROUPS: tuple[frozenset[Suit], ...] = (
    frozenset({Suit.HEARTS, Suit.DIAMONDS}),
    frozenset({Suit.CLUBS, Suit.SPADES}),
)

#: Символ ранга для отображения окна стрита. Туз-младший (значение 1) не
#: совпадает ни с одним `Rank.order`, поэтому его подписываем отдельно.
_STRAIGHT_VALUE_LABEL: dict[int, str] = {rank.order: rank.value for rank in Rank}
_STRAIGHT_VALUE_LABEL[1] = "A"

#: Русские названия мастей для имён целей — как везде в проекте
#: (см. `adapters/mod_bridge._SUIT_WORDS`), а не английские `Suit.name`.
_SUIT_LABEL: dict[Suit, str] = {
    Suit.HEARTS: "черви",
    Suit.DIAMONDS: "бубны",
    Suit.CLUBS: "трефы",
    Suit.SPADES: "пики",
}


def advise_discard(state: GameState, limit: int = 5) -> tuple[DiscardOption, ...]:
    """Посоветовать, что сбрасывать — без перебора всех наборов сброса.

    Реализация раздела 4 `docs/Discard Spec.md`: цели перечисляются, а не
    сбросы, вероятность цели считается точно (гипергеометрически), и только
    ожидаемый счёт при каждом числе пришедших аутов оценивается по нескольким
    представительным рукам вместо честного перебора всех доборов (см.
    `_fast_best_score` — раздел 10 спеки прямо разрешает приближение здесь,
    в отличие от `advise`/`rank_plays`, которые обязаны остаться точными).

    Возвращает пустой кортеж, если сбросов не осталось или в руке меньше
    двух карт (раздел 6 — сброс тогда бессмыслен).
    """
    if state.discards_left <= 0 or len(state.hand) < 2:
        return ()

    unseen, exact_deck = known_deck(state)
    if not unseen:
        return ()

    jokers = build_jokers(state)
    mods = modifiers_from(jokers)

    targets = _enumerate_targets(state.hand, unseen, mods)
    groups = _group_by_keep(targets)

    options: list[DiscardOption] = []
    for keep_set, members in groups.items():
        keep, outs, needed, names = _merge_targets(members)
        discard = tuple(card for card in state.hand if card not in keep_set)
        if not discard or len(discard) > MAX_DISCARD_SIZE or len(discard) > len(unseen):
            continue
        option = _evaluate_variant(
            state, jokers, mods, unseen, discard, keep, outs, needed, names, exact_deck
        )
        if option is not None:
            options.append(option)

    options.sort(key=lambda item: -item.expected)
    return tuple(options[:limit])


def _enumerate_targets(
    hand: tuple[Card, ...], unseen: tuple[Card, ...], mods: HandModifiers
) -> list[Target]:
    """Все цели раздела 4.2, уже отфильтрованные по 4.3."""
    playable = tuple(card for card in hand if not card.is_stone)
    unseen_playable = tuple(card for card in unseen if not card.is_stone)

    targets = [
        *_flush_targets(playable, unseen_playable, mods),
        *_straight_targets(playable, unseen_playable, mods),
        *_n_of_a_kind_targets(playable, unseen_playable),
        *_full_house_targets(playable, unseen_playable),
    ]
    baseline = _keep_as_is_target(hand, mods)
    if baseline is not None:
        targets.append(baseline)
    return targets


def _flush_targets(
    hand: tuple[Card, ...], unseen: tuple[Card, ...], mods: HandModifiers
) -> list[Target]:
    needed_size = 4 if mods.four_fingers else 5
    groups = _SMEARED_GROUPS if mods.smeared else tuple(frozenset({suit}) for suit in Suit)

    targets = []
    for group in groups:
        keep = tuple(card for card in hand if effective_suits(card, smeared=mods.smeared) & group)
        needed = needed_size - len(keep)
        if needed <= 0 or needed > MAX_DISCARD_SIZE:
            continue
        outs = tuple(card for card in unseen if effective_suits(card, smeared=mods.smeared) & group)
        if needed > len(outs):
            continue
        label = "/".join(_SUIT_LABEL[suit] for suit in sorted(group, key=lambda s: s.value))
        targets.append(Target(f"флеш {label}", keep, outs, needed))
    return targets


def _straight_windows(mods: HandModifiers) -> list[frozenset[int]]:
    """Все окна стрита: обычно 10 подряд идущих пятёрок значений 1..14.

    С `Shortcut` окно допускает шаг между соседними значениями в 1 или 2
    (раздел 4.2), поэтому набор окон уже не сводится к сдвигу подряд идущего
    диапазона — строится честным перебором цепочек шагов.
    """
    size = 4 if mods.four_fingers else 5
    gaps = (1, 2) if mods.shortcut else (1,)

    windows: set[frozenset[int]] = set()

    def extend(values: tuple[int, ...]) -> None:
        if len(values) == size:
            windows.add(frozenset(values))
            return
        for gap in gaps:
            nxt = values[-1] + gap
            if nxt <= 14:
                extend((*values, nxt))

    for start in range(1, 15):
        extend((start,))

    return sorted(windows, key=lambda window: (max(window), min(window)))


def _straight_targets(
    hand: tuple[Card, ...], unseen: tuple[Card, ...], mods: HandModifiers
) -> list[Target]:
    targets = []
    for window in _straight_windows(mods):
        keep: list[Card] = []
        matched: set[int] = set()
        for card in hand:
            available = (card.rank.straight_values & window) - matched
            if available:
                keep.append(card)
                matched.add(next(iter(available)))

        missing = window - matched
        needed = len(missing)
        if needed <= 0 or needed > MAX_DISCARD_SIZE:
            continue
        outs = tuple(card for card in unseen if card.rank.straight_values & missing)
        if needed > len(outs):
            continue

        label = "-".join(_STRAIGHT_VALUE_LABEL[value] for value in sorted(window))
        targets.append(Target(f"стрит {label}", tuple(keep), outs, needed))
    return targets


def _n_of_a_kind_targets(hand: tuple[Card, ...], unseen: tuple[Card, ...]) -> list[Target]:
    by_rank: dict[Rank, list[Card]] = {}
    for card in hand:
        by_rank.setdefault(card.rank, []).append(card)

    targets = []
    for rank, cards in by_rank.items():
        outs = tuple(card for card in unseen if card.rank is rank)
        for size, label in ((3, "трипл"), (4, "каре"), (5, "пятёрка")):
            needed = size - len(cards)
            if needed <= 0 or needed > MAX_DISCARD_SIZE or needed > len(outs):
                continue
            targets.append(Target(f"{label} {rank.value}", tuple(cards), outs, needed))
    return targets


def _full_house_targets(hand: tuple[Card, ...], unseen: tuple[Card, ...]) -> list[Target]:
    """Лучшая тройка + лучшая пара, и симметричный вариант (раздел 4.2)."""
    by_rank: dict[Rank, list[Card]] = {}
    for card in hand:
        by_rank.setdefault(card.rank, []).append(card)
    groups = sorted(by_rank.items(), key=lambda item: (len(item[1]), item[0].order), reverse=True)
    if len(groups) < 2:
        return []

    def outs_for(rank: Rank) -> tuple[Card, ...]:
        return tuple(card for card in unseen if card.rank is rank)

    def build(
        triple_rank: Rank, triple_cards: list[Card], pair_rank: Rank, pair_cards: list[Card]
    ) -> Target | None:
        needed = max(0, 3 - len(triple_cards)) + max(0, 2 - len(pair_cards))
        if needed <= 0 or needed > MAX_DISCARD_SIZE:
            return None
        outs = tuple(dict.fromkeys((*outs_for(triple_rank), *outs_for(pair_rank))))
        if needed > len(outs):
            return None
        keep = (*triple_cards, *pair_cards)
        return Target(f"фулл-хаус {triple_rank.value}+{pair_rank.value}", keep, outs, needed)

    (rank_a, cards_a), (rank_b, cards_b) = groups[0], groups[1]
    targets = [build(rank_a, cards_a, rank_b, cards_b), build(rank_b, cards_b, rank_a, cards_a)]
    return [target for target in targets if target is not None]


def _keep_as_is_target(hand: tuple[Card, ...], mods: HandModifiers) -> Target | None:
    """«Оставить как есть»: держим лучший текущий розыгрыш, сбрасываем остальное.

    В отличие от остальных семейств, `needed` тут всегда 0 не потому, что
    цель уже случайно достигнута (это исключало бы её по 4.3), а потому, что
    сама цель — «докинуть в те же карты что-нибудь получше», без конкретного
    недостающего ранга или масти. Формула раздела 4.5 всё равно работает: при
    пустом `outs` и `needed = 0` единственная корзина — «пришло 0 аутов» с
    вероятностью 1, и представительные руки берутся из всей невидимой колоды.
    """
    if len(hand) < 2:
        return None
    result = evaluate(hand, mods)
    scoring = result.scoring_cards
    if len(scoring) > MAX_PLAYED:
        # Единственный способ превысить лимит розыгрыша — необрезанный флеш
        # (`hands._find_flush` отдаёт всю масть целиком). Оставляем самые
        # дорогие по фишкам карты — при равном типе руки они увеличивают чипы.
        scoring = tuple(sorted(scoring, key=lambda card: card.rank.chips, reverse=True))
        scoring = scoring[:MAX_PLAYED]
    if len(scoring) >= len(hand):
        return None
    return Target("оставить лучшую руку как есть", scoring, (), 0)


def _group_by_keep(targets: list[Target]) -> dict[frozenset[Card], list[Target]]:
    groups: dict[frozenset[Card], list[Target]] = {}
    for target in targets:
        groups.setdefault(frozenset(target.keep), []).append(target)
    return groups


def _merge_targets(
    members: list[Target],
) -> tuple[tuple[Card, ...], tuple[Card, ...], int, tuple[str, ...]]:
    """Схлопнуть цели с одинаковым `keep` в один вариант сброса (раздел 4.4).

    Аут-лист объединяется (любая цель группы засчитывается), нужное число —
    минимальное среди целей: приблизительно, но самосогласованно с тем, что
    сама оценка `E[счёт | i]` считается по настоящему добору и настоящему
    подсчёту — если один из аутов на деле не завершил именно эту цель, это
    честно отразится в счёте выбранной представительной руки.
    """
    keep = members[0].keep
    outs = tuple(dict.fromkeys(card for member in members for card in member.outs))
    needed = min(member.needed for member in members)
    names = tuple(member.name for member in members)
    return keep, outs, needed, names


def _evaluate_variant(
    state: GameState,
    jokers: tuple[Joker, ...],
    mods: HandModifiers,
    unseen: tuple[Card, ...],
    discard: tuple[Card, ...],
    keep: tuple[Card, ...],
    outs: tuple[Card, ...],
    needed: int,
    names: tuple[str, ...],
    exact_deck: bool,
) -> DiscardOption | None:
    """Оценка одного варианта сброса — раздел 4.5 спеки."""
    k = len(discard)
    n = len(unseen)
    s = len(outs)
    outs_set = set(outs)
    rest = tuple(card for card in unseen if card not in outs_set)

    rng = random.Random(_SAMPLE_SEED)
    buckets: list[OutcomeBucket] = []
    expected = 0.0

    lo = max(0, k - (n - s))
    hi = min(k, s)
    for hits in range(lo, hi + 1):
        probability = math.comb(s, hits) * math.comb(n - s, k - hits) / math.comb(n, k)
        if probability <= 0:
            continue
        draws = _representative_draws(outs, rest, hits, k, SAMPLE_HANDS_PER_BUCKET, rng)
        if not draws:
            continue
        score = sum(
            _fast_best_score(replace(state, hand=keep + draw), jokers, mods) for draw in draws
        ) / len(draws)
        buckets.append(OutcomeBucket(hits, probability, score))
        expected += probability * score

    if not buckets:
        return None

    return DiscardOption(
        discard=discard,
        keep=keep,
        expected=expected,
        distribution=tuple(buckets),
        targets=names,
        needed=needed,
        exact=False,
        exact_deck=exact_deck,
    )


def _representative_draws(
    outs: tuple[Card, ...],
    rest: tuple[Card, ...],
    hits: int,
    k: int,
    cap: int,
    rng: random.Random,
) -> list[tuple[Card, ...]]:
    """Несколько представительных доборов с ровно `hits` аутами (раздел 4.5).

    Полный перебор, когда он дешёвый — тогда результат не приближение вовсе;
    сэмплирование только когда комбинаций больше `cap`. Сид фиксирован
    (`_SAMPLE_SEED`), поэтому один и тот же расклад всегда даёт один ответ.
    """
    rest_needed = k - hits
    total = math.comb(len(outs), hits) * math.comb(len(rest), rest_needed)
    if total <= 0:
        return []
    if total <= cap:
        return [
            (*out_combo, *rest_combo)
            for out_combo in combinations(outs, hits)
            for rest_combo in combinations(rest, rest_needed)
        ]

    seen: set[frozenset[Card]] = set()
    draws: list[tuple[Card, ...]] = []
    attempts = 0
    while len(draws) < cap and attempts < cap * 20:
        attempts += 1
        out_combo = tuple(rng.sample(outs, hits)) if hits else ()
        rest_combo = tuple(rng.sample(rest, rest_needed)) if rest_needed else ()
        combo = (*out_combo, *rest_combo)
        key = frozenset(combo)
        if key in seen:
            continue
        seen.add(key)
        draws.append(combo)
    return draws


def _fast_best_score(state: GameState, jokers: tuple[Joker, ...], mods: HandModifiers) -> float:
    """Дешёвая (не исчерпывающая) оценка лучшего счёта по руке до 8 карт.

    Не `rank_plays`: тот перебирает все 218 подмножеств честно, а здесь этот
    перебор вызывался бы `вариантов × корзин × представительных_рук` раз —
    слишком медленно для бюджета в 200 мс (раздел 7, критерий 3). Вместо
    этого строится пара разумных кандидатов на розыгрыш и считается точный
    `score_play` (со всеми джокерами) только по ним — экономит перебор
    подмножеств, но не подменяет сам подсчёт очков приближением. Раздел 10
    спеки прямо разрешает такое приближение внутри оценки сброса.
    """
    candidates = _fast_candidates(state.hand, mods)
    if not candidates:
        return 0.0
    return max(score_play(state, subset, jokers, mods).expected for subset in candidates)


def _fast_candidates(hand: tuple[Card, ...], mods: HandModifiers) -> list[tuple[Card, ...]]:
    """Пара кандидатов на розыгрыш вместо перебора всех подмножеств.

    Первый — естественная лучшая структура по всей руке сразу: включение
    лишних карт в `evaluate` может только помочь найти комбинацию (флеш,
    стрит, группу), не помешать, поэтому это не хуже полного перебора по
    структуре руки — только не гарантированно лучшее по итоговому счёту
    (джокеры могут сделать не самый сильный тип руки не самым выгодным).
    Второй кандидат — просто пять самых дорогих по фишкам карт, страховка от
    этого случая. Обрезка `evaluate` до пяти карт нужна только флешу:
    `hands._find_flush` отдаёт всю масть целиком, не только пять карт.
    """
    if not hand:
        return []

    result = evaluate(hand, mods)
    scoring = result.scoring_cards
    if len(scoring) > MAX_PLAYED:
        scoring = tuple(sorted(scoring, key=lambda card: card.rank.chips, reverse=True))
        scoring = scoring[:MAX_PLAYED]

    candidates = [scoring] if scoring else []

    by_chips = tuple(
        sorted(
            (card for card in hand if not card.is_stone),
            key=lambda card: card.rank.chips,
            reverse=True,
        )[:MAX_PLAYED]
    )
    if by_chips and by_chips != scoring:
        candidates.append(by_chips)

    return candidates
