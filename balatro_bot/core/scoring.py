"""Симулятор подсчёта очков Balatro.

Счёт — это `chips × mult`, но оба множителя собираются в строгом порядке,
и порядок важен: сложение до умножения даёт другой результат.

Устройство — конвейер событий. Подсчёт идёт по шагам и на каждом объявляет,
что произошло: рука определена, карта засчитана, карта осталась в руке,
очередь джокера. Джокеры не вызываются откуда-то — они подписаны на события
и возвращают эффекты. Благодаря этому порядок вычисления живёт в одном месте,
а сложные взаимодействия (ретриггеры, копирующие джокеры) получаются сами.

Порядок из плана, раздел 5:

1. тип руки → базовые chips/mult по текущему уровню;
2. дебафф боссового блайнда отключает карты;
3. сыгранные карты слева направо, с ретриггерами;
4. карты, оставшиеся в руке;
5. джокеры слева направо;
6. произведение.

Числовые значения улучшений и изданий взяты из документации мода BalatroBook
и потому проверены. Порядок шагов — пока допущение, сверяется в Фазе 3
по эталонным случаям.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import product
from typing import TYPE_CHECKING, Protocol

from balatro_bot.core.cards import Card, Edition, Enhancement, Rank, Seal, Suit, effective_suits
from balatro_bot.core.hands import HandModifiers, HandResult, HandType, evaluate
from balatro_bot.core.state import GameState

if TYPE_CHECKING:
    from balatro_bot.core.jokers import Joker

__all__ = [
    "AddChips",
    "AddMult",
    "CardHeld",
    "CardScored",
    "Effect",
    "Event",
    "HandDetermined",
    "JokerTurn",
    "Retrigger",
    "RetriggerQuery",
    "ScoreContext",
    "ScoreOutcome",
    "TraceStep",
    "XMult",
    "score_play",
]

#: Максимум ветвлений при точном переборе случайных исходов. Дальше — выборка.
MAX_CHANCE_BRANCHES = 4096

_FACE_RANKS = frozenset({Rank.JACK, Rank.QUEEN, Rank.KING})

_STRAIGHT_HANDS = frozenset({HandType.STRAIGHT, HandType.STRAIGHT_FLUSH})

_FLUSH_HANDS = frozenset(
    {HandType.FLUSH, HandType.STRAIGHT_FLUSH, HandType.FLUSH_HOUSE, HandType.FLUSH_FIVE}
)


# ---------------------------------------------------------------------------
# Эффекты: то, что карты и джокеры возвращают в ответ на события
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AddChips:
    """Прибавить очки."""

    amount: float


@dataclass(frozen=True, slots=True)
class AddMult:
    """Прибавить множитель."""

    amount: float


@dataclass(frozen=True, slots=True)
class XMult:
    """Умножить множитель. Всегда применяется после всех сложений в своём шаге."""

    factor: float


@dataclass(frozen=True, slots=True)
class Retrigger:
    """Дополнительные срабатывания карты. Ответ на `RetriggerQuery`."""

    times: int = 1


Effect = AddChips | AddMult | XMult | Retrigger


# ---------------------------------------------------------------------------
# События: моменты подсчёта
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HandDetermined:
    """Тип руки распознан, базовые значения уже в аккумуляторе."""

    hand_type: HandType
    scoring_cards: tuple[Card, ...]


@dataclass(frozen=True, slots=True)
class CardScored:
    """Засчитывается сыгранная карта. `index` — позиция среди засчитываемых."""

    card: Card
    index: int
    repeat: int = 0
    """Номер повторного срабатывания: 0 — первое, дальше ретриггеры."""


@dataclass(frozen=True, slots=True)
class CardHeld:
    """Карта осталась в руке и срабатывает как «удерживаемая»."""

    card: Card
    repeat: int = 0


@dataclass(frozen=True, slots=True)
class JokerTurn:
    """Очередь джокера в его слоте."""

    joker: Joker


@dataclass(frozen=True, slots=True)
class RetriggerQuery:
    """Запрос «сколько дополнительных срабатываний у этой карты».

    Отдельное событие, потому что число ретриггеров нужно знать *до* того,
    как карта начнёт засчитываться.
    """

    card: Card
    in_hand: bool
    index: int = 0


Event = HandDetermined | CardScored | CardHeld | JokerTurn | RetriggerQuery


# ---------------------------------------------------------------------------
# Результат
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TraceStep:
    """Один шаг разбора счёта — для объяснения человеку и для сверки с игрой."""

    source: str
    detail: str
    chips: float
    mult: float


@dataclass(frozen=True, slots=True)
class ScoreOutcome:
    """Итог подсчёта одного хода."""

    hand_type: HandType
    scoring_cards: tuple[Card, ...]

    expected: float
    """Матожидание счёта. Для детерминированной руки — просто счёт."""

    minimum: float
    maximum: float

    trace: tuple[TraceStep, ...]
    """Разбор одного показательного исхода (самого вероятного)."""

    exact: bool
    """Можно ли доверять числу до единицы."""

    unknown: tuple[str, ...]
    """Что помешало точности."""

    @property
    def certain(self) -> bool:
        """Есть ли в руке случайность."""
        return self.minimum == self.maximum

    def __str__(self) -> str:
        if self.certain:
            return f"{self.expected:,.0f}".replace(",", " ")
        return f"~{self.expected:,.0f} ({self.minimum:,.0f}…{self.maximum:,.0f})".replace(",", " ")


# ---------------------------------------------------------------------------
# Контекст подсчёта
# ---------------------------------------------------------------------------


class ChancePicker(Protocol):
    """Как разрешаются случайные эффекты."""

    def pick(self, outcomes: Sequence[tuple[float, float]]) -> float:
        """Выбрать значение из вариантов «(значение, вероятность)»."""
        ...


@dataclass
class _ScriptedPicker:
    """Разрешает случайности по заранее заданному сценарию.

    Нужен, чтобы перебрать все исходы точно, а не оценивать выборкой:
    случайных точек в руке единицы, поэтому полный перебор дешевле и честнее.
    """

    choices: tuple[int, ...] = ()
    seen: list[Sequence[tuple[float, float]]] = field(default_factory=list)

    def pick(self, outcomes: Sequence[tuple[float, float]]) -> float:
        position = len(self.seen)
        self.seen.append(outcomes)
        index = self.choices[position] if position < len(self.choices) else 0
        return outcomes[index][0]


class _LikeliestPicker:
    """Берёт самый вероятный исход. Нужен, когда ветвей слишком много для перебора."""

    def pick(self, outcomes: Sequence[tuple[float, float]]) -> float:
        return max(outcomes, key=lambda outcome: outcome[1])[0]


@dataclass
class ScoreContext:
    """Состояние подсчёта: аккумулятор, разбор и справки для джокеров."""

    state: GameState
    played: tuple[Card, ...]
    scoring_cards: tuple[Card, ...]
    held: tuple[Card, ...]
    hand_type: HandType
    jokers: tuple[Joker, ...]
    modifiers: HandModifiers

    chips: float = 0.0
    mult: float = 0.0
    trace: list[TraceStep] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    picker: ChancePicker | None = None

    copying: list[Joker] = field(default_factory=list)
    """Цепочка копирующих джокеров, раскручиваемая прямо сейчас.

    Blueprint копирует соседа справа, Brainstorm — самого левого. Поставленные
    рядом, они начинают копировать друг друга по кругу. Список обрывает цикл:
    джокер, уже находящийся в цепочке, второй раз не срабатывает.
    """

    # -- применение эффектов --------------------------------------------

    def apply(self, effect: Effect, source: str, detail: str = "") -> None:
        """Применить эффект к аккумулятору и записать шаг разбора."""
        match effect:
            case AddChips(amount):
                self.chips += amount
                note = detail or f"+{amount:g} очков"
            case AddMult(amount):
                self.mult += amount
                note = detail or f"+{amount:g} множителя"
            case XMult(factor):
                self.mult *= factor
                note = detail or f"×{factor:g} множителя"
            case Retrigger():
                return  # ретриггеры не меняют аккумулятор
        self.trace.append(TraceStep(source, note, self.chips, self.mult))

    def emit(self, event: Event) -> None:
        """Разослать событие джокерам по порядку слотов."""
        for joker in self.jokers:
            for effect in joker.react(event, self):
                if not isinstance(effect, Retrigger):
                    self.apply(effect, joker.name)

    def ask_retriggers(self, card: Card, *, in_hand: bool, index: int = 0) -> int:
        """Сколько дополнительных раз срабатывает карта."""
        extra = 1 if card.seal is Seal.RED else 0
        query = RetriggerQuery(card, in_hand=in_hand, index=index)
        for joker in self.jokers:
            for effect in joker.react(query, self):
                if isinstance(effect, Retrigger):
                    extra += effect.times
        return extra

    # -- справки для джокеров -------------------------------------------

    def suits_of(self, card: Card) -> frozenset[Suit]:
        """Масти, за которые карта может сойти, с учётом Wild и Smeared."""
        return effective_suits(card, smeared=self.modifiers.smeared)

    def has_suit(self, card: Card, suit: Suit) -> bool:
        return suit in self.suits_of(card)

    def joker_to_the_right(self, joker: Joker) -> Joker | None:
        """Сосед справа — нужен копирующим джокерам."""
        for position, candidate in enumerate(self.jokers):
            if candidate is joker:
                following = self.jokers[position + 1 :]
                return following[0] if following else None
        return None

    def leftmost_joker(self, joker: Joker) -> Joker | None:
        """Самый левый джокер. Если спрашивающий сам левый — копировать нечего."""
        if not self.jokers or self.jokers[0] is joker:
            return None
        return self.jokers[0]

    # -- состав руки: нужен джокерам вида «если рука содержит…» ---------

    def rank_counts(self) -> dict[Rank, int]:
        """Сколько карт каждого ранга среди засчитываемых."""
        counts: dict[Rank, int] = {}
        for card in self.scoring_cards:
            if not card.is_stone:
                counts[card.rank] = counts.get(card.rank, 0) + 1
        return counts

    @property
    def contains_pair(self) -> bool:
        return any(count >= 2 for count in self.rank_counts().values())

    @property
    def contains_two_pair(self) -> bool:
        return sum(1 for count in self.rank_counts().values() if count >= 2) >= 2

    @property
    def contains_three(self) -> bool:
        return any(count >= 3 for count in self.rank_counts().values())

    @property
    def contains_straight(self) -> bool:
        return self.hand_type in _STRAIGHT_HANDS

    @property
    def contains_flush(self) -> bool:
        return self.hand_type in _FLUSH_HANDS

    def is_face(self, card: Card) -> bool:
        """Картинка ли это: валет, дама, король."""
        return not card.is_stone and card.rank in _FACE_RANKS

    def first_face_index(self) -> int | None:
        """Позиция первой картинки среди засчитываемых карт."""
        for index, card in enumerate(self.scoring_cards):
            if self.is_face(card):
                return index
        return None

    def chance(self, outcomes: Sequence[tuple[float, float]]) -> float:
        """Разрешить случайный эффект."""
        if self.picker is None:
            return outcomes[0][0]
        return self.picker.pick(outcomes)

    def mark_unknown(self, what: str) -> None:
        """Пометить расчёт неточным."""
        if what not in self.unknown:
            self.unknown.append(what)


# ---------------------------------------------------------------------------
# Собственные эффекты карт
# ---------------------------------------------------------------------------

#: Улучшения, дающие очки при засчитывании. Значения из документации мода.
_ENHANCEMENT_CHIPS: dict[Enhancement, float] = {
    Enhancement.BONUS: 30.0,
    Enhancement.STONE: 50.0,
}

_ENHANCEMENT_MULT: dict[Enhancement, float] = {
    Enhancement.MULT: 4.0,
}

_EDITION_CHIPS: dict[Edition, float] = {Edition.FOIL: 50.0}
_EDITION_MULT: dict[Edition, float] = {Edition.HOLOGRAPHIC: 10.0}
_EDITION_XMULT: dict[Edition, float] = {Edition.POLYCHROME: 1.5}

#: Lucky: шанс 1 к 5 на +20 множителя.
_LUCKY_OUTCOMES: tuple[tuple[float, float], ...] = ((0.0, 0.8), (20.0, 0.2))


def _score_card(card: Card, ctx: ScoreContext) -> None:
    """Собственный вклад карты: очки ранга, улучшение, издание."""
    name = f"{card.rank.value}{card.suit.value}"

    if not card.is_stone:
        ctx.apply(AddChips(card.rank.chips), name, f"+{card.rank.chips} очков за ранг")

    if (chips := _ENHANCEMENT_CHIPS.get(card.enhancement)) is not None:
        ctx.apply(AddChips(chips), name, f"+{chips:g} очков ({card.enhancement.value})")
    if (mult := _ENHANCEMENT_MULT.get(card.enhancement)) is not None:
        ctx.apply(AddMult(mult), name, f"+{mult:g} множителя ({card.enhancement.value})")
    if card.enhancement is Enhancement.GLASS:
        ctx.apply(XMult(2.0), name, "×2 множителя (glass)")
    if card.enhancement is Enhancement.LUCKY:
        bonus = ctx.chance(_LUCKY_OUTCOMES)
        if bonus:
            ctx.apply(AddMult(bonus), name, f"+{bonus:g} множителя (lucky, повезло)")

    if (chips := _EDITION_CHIPS.get(card.edition)) is not None:
        ctx.apply(AddChips(chips), name, f"+{chips:g} очков ({card.edition.value})")
    if (mult := _EDITION_MULT.get(card.edition)) is not None:
        ctx.apply(AddMult(mult), name, f"+{mult:g} множителя ({card.edition.value})")
    if (factor := _EDITION_XMULT.get(card.edition)) is not None:
        ctx.apply(XMult(factor), name, f"×{factor:g} множителя ({card.edition.value})")


def _hold_card(card: Card, ctx: ScoreContext) -> None:
    """Вклад карты, оставшейся в руке."""
    if card.enhancement is Enhancement.STEEL:
        name = f"{card.rank.value}{card.suit.value}"
        ctx.apply(XMult(1.5), name, "×1.5 множителя (steel, в руке)")


# ---------------------------------------------------------------------------
# Конвейер
# ---------------------------------------------------------------------------


def _run_once(
    state: GameState,
    played: Sequence[Card],
    held: Sequence[Card],
    jokers: Sequence[Joker],
    modifiers: HandModifiers,
    result: HandResult,
    picker: ChancePicker | None,
) -> ScoreContext:
    """Один проход конвейера. Случайности разрешает `picker`."""
    values = state.hand_values(result.hand_type)
    ctx = ScoreContext(
        state=state,
        played=tuple(played),
        scoring_cards=result.scoring_cards,
        held=tuple(held),
        hand_type=result.hand_type,
        jokers=tuple(jokers),
        modifiers=modifiers,
        chips=float(values.chips),
        mult=float(values.mult),
        picker=picker,
    )
    ctx.trace.append(TraceStep("рука", f"{result.hand_type.value}: база", ctx.chips, ctx.mult))

    # 1-2. Тип руки объявлен, дебаффнутые карты выбывают.
    ctx.emit(HandDetermined(result.hand_type, result.scoring_cards))

    # 3. Сыгранные карты слева направо, с учётом ретриггеров.
    for index, card in enumerate(result.scoring_cards):
        if card.debuffed:
            name = f"{card.rank.value}{card.suit.value}"
            ctx.trace.append(TraceStep(name, "отключена боссом", ctx.chips, ctx.mult))
            continue
        triggers = 1 + ctx.ask_retriggers(card, in_hand=False, index=index)
        for repeat in range(triggers):
            _score_card(card, ctx)
            ctx.emit(CardScored(card, index, repeat))

    # 4. Карты, оставшиеся в руке.
    for card in held:
        if card.debuffed:
            continue
        triggers = 1 + ctx.ask_retriggers(card, in_hand=True)
        for repeat in range(triggers):
            _hold_card(card, ctx)
            ctx.emit(CardHeld(card, repeat))

    # 5. Джокеры слева направо.
    for joker in jokers:
        ctx.emit(JokerTurn(joker))

    return ctx


def score_play(
    state: GameState,
    played: Sequence[Card],
    jokers: Sequence[Joker] | None = None,
    modifiers: HandModifiers | None = None,
) -> ScoreOutcome:
    """Посчитать счёт за розыгрыш карт.

    Карты, оставшиеся в руке, берутся из состояния: это те карты руки,
    которые не были сыграны.

    Если в руке есть случайные эффекты, все исходы перебираются точно и
    возвращается матожидание вместе с границами. Точек случайности в одной
    руке единицы, поэтому перебор дешевле выборки и не врёт.
    """
    from balatro_bot.core.jokers import build_jokers, modifiers_from

    active = tuple(jokers) if jokers is not None else build_jokers(state)
    mods = modifiers if modifiers is not None else modifiers_from(active)

    played_tuple = tuple(played)

    # Оставшиеся в руке ищутся по тождеству объектов, поэтому сыграть можно
    # только карты из самой руки. Иначе карта посчиталась бы дважды — и как
    # сыгранная, и как оставшаяся, — и Steel молча завысил бы счёт.
    hand_ids = {id(card) for card in state.hand}
    посторонние = [card for card in played_tuple if id(card) not in hand_ids]
    if посторонние:
        raise ValueError(
            f"эти карты не из руки состояния: {посторонние}. "
            "Передавай именно объекты из `state.hand`"
        )

    result = evaluate(played_tuple, mods)
    played_ids = {id(card) for card in played_tuple}
    held = tuple(card for card in state.hand if id(card) not in played_ids)

    # Первый проход заодно показывает, где возникает случайность. Если её нет,
    # он же и есть окончательный расчёт — второй раз считать незачем.
    probe = _ScriptedPicker()
    ctx = _run_once(state, played_tuple, held, active, mods, result, probe)
    chance_points = list(probe.seen)

    if not chance_points:
        total = ctx.chips * ctx.mult
        return _outcome(result, ctx, total, total, total)

    branches = 1
    for outcomes in chance_points:
        branches *= len(outcomes)
    if branches > MAX_CHANCE_BRANCHES:
        # Слишком много ветвей для точного перебора: считаем по самому вероятному
        # исходу и честно признаём, что границы неизвестны.
        ctx = _run_once(state, played_tuple, held, active, mods, result, _LikeliestPicker())
        total = ctx.chips * ctx.mult
        ctx.mark_unknown("слишком много случайных эффектов для точного перебора")
        return _outcome(result, ctx, total, total, total)

    expected = 0.0
    lowest = float("inf")
    highest = float("-inf")
    best_ctx: ScoreContext | None = None
    best_probability = -1.0

    for indices in product(*(range(len(outcomes)) for outcomes in chance_points)):
        picker = _ScriptedPicker(choices=indices)
        ctx = _run_once(state, played_tuple, held, active, mods, result, picker)
        total = ctx.chips * ctx.mult

        if len(picker.seen) != len(chance_points):
            # Набор случайных точек зависит от исхода: сумма вероятностей
            # перестаёт быть единицей, и границам верить нельзя.
            ctx.mark_unknown("состав случайных эффектов зависит от их же исхода")

        probability = 1.0
        for outcomes, index in zip(picker.seen, indices, strict=False):
            probability *= outcomes[index][1]

        expected += total * probability
        lowest = min(lowest, total)
        highest = max(highest, total)
        if probability > best_probability:
            best_probability, best_ctx = probability, ctx

    assert best_ctx is not None
    return _outcome(result, best_ctx, expected, lowest, highest)


def _outcome(
    result: HandResult,
    ctx: ScoreContext,
    expected: float,
    lowest: float,
    highest: float,
) -> ScoreOutcome:
    # Про неопознанных джокеров уже сообщил `UnimplementedJoker`, поэтому из
    # состояния берём только остальное: улучшения, издания, типы рук.
    from_state = tuple(key for key in ctx.state.unknown_keys if not key.startswith("joker:"))
    unknown = tuple(dict.fromkeys(tuple(ctx.unknown) + from_state))
    if not ctx.state.has_authoritative_hand_values:
        unknown += ("значения рук взяты из провизорной таблицы",)
    return ScoreOutcome(
        hand_type=result.hand_type,
        scoring_cards=result.scoring_cards,
        expected=expected,
        minimum=lowest,
        maximum=highest,
        trace=tuple(ctx.trace),
        exact=not unknown,
        unknown=unknown,
    )
