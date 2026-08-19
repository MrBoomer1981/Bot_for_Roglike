"""Реализации эффектов джокеров.

Числа взяты из справочника `catalogue`, то есть из аннотаций мода, а не
по памяти. Рядом с каждым классом — исходный игровой текст, чтобы при
расхождении было видно, что именно реализовано.

Реализованы не все 150: сначала частые и те, что проверяют архитектуру
на прочность — копирующие, ретриггерящие и меняющие правила распознавания.
Остальные считаются нереализованными и честно помечают расчёт неточным.
"""

from __future__ import annotations

from collections.abc import Iterable

from balatro_bot.core.cards import Rank, Suit
from balatro_bot.core.jokers import BaseJoker, Joker, register
from balatro_bot.core.scoring import (
    AddChips,
    AddMult,
    CardHeld,
    CardScored,
    Effect,
    Event,
    JokerTurn,
    Retrigger,
    RetriggerQuery,
    ScoreContext,
    XMult,
)


class _OwnTurn(BaseJoker):
    """Джокер, срабатывающий один раз в свою очередь."""

    def react(self, event: Event, ctx: ScoreContext) -> Iterable[Effect]:
        if isinstance(event, JokerTurn) and event.joker is self:
            return self.on_turn(ctx)
        return ()

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        return ()


# ---------------------------------------------------------------------------
# Плоские прибавки
# ---------------------------------------------------------------------------


@register("j_joker")
class Joker4Mult(_OwnTurn):
    """+4 Mult."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        yield AddMult(4)


# ---------------------------------------------------------------------------
# «Если рука содержит …»
# ---------------------------------------------------------------------------


class _ConditionalJoker(_OwnTurn):
    """Прибавка, если состав руки удовлетворяет условию."""

    condition: str = ""
    chips: float = 0.0
    mult: float = 0.0

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        if not self._holds(ctx):
            return
        if self.chips:
            yield AddChips(self.chips)
        if self.mult:
            yield AddMult(self.mult)

    def _holds(self, ctx: ScoreContext) -> bool:
        match self.condition:
            case "pair":
                return ctx.contains_pair
            case "two_pair":
                return ctx.contains_two_pair
            case "three":
                return ctx.contains_three
            case "straight":
                return ctx.contains_straight
            case "flush":
                return ctx.contains_flush
        return False


def _conditional(
    condition: str, *, chips: float = 0.0, mult: float = 0.0
) -> type[_ConditionalJoker]:
    """Собрать класс джокера «если рука содержит …»."""

    class Built(_ConditionalJoker):
        pass

    Built.condition = condition
    Built.chips = chips
    Built.mult = mult
    return Built


# +8/+12/+10/+12/+10 Mult если рука содержит пару / тройку / две пары / стрит / флеш
register("j_jolly")(_conditional("pair", mult=8))
register("j_zany")(_conditional("three", mult=12))
register("j_mad")(_conditional("two_pair", mult=10))
register("j_crazy")(_conditional("straight", mult=12))
register("j_droll")(_conditional("flush", mult=10))

# +50/+100/+80/+100/+80 Chips по тем же условиям
register("j_sly")(_conditional("pair", chips=50))
register("j_wily")(_conditional("three", chips=100))
register("j_clever")(_conditional("two_pair", chips=80))
register("j_devious")(_conditional("straight", chips=100))
register("j_crafty")(_conditional("flush", chips=80))


@register("j_half")
class HalfJoker(_OwnTurn):
    """+20 Mult if played hand contains 3 or fewer cards."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        if len(ctx.played) <= 3:
            yield AddMult(20)


# ---------------------------------------------------------------------------
# Реакция на отдельные засчитываемые карты
# ---------------------------------------------------------------------------


class _PerScoredCard(BaseJoker):
    """Срабатывает на каждой подходящей засчитываемой карте."""

    def react(self, event: Event, ctx: ScoreContext) -> Iterable[Effect]:
        if isinstance(event, CardScored):
            return self.on_card(event, ctx)
        return ()

    def on_card(self, event: CardScored, ctx: ScoreContext) -> Iterable[Effect]:
        return ()


class _SuitMult(_PerScoredCard):
    """Played cards with <suit> suit give +3 Mult when scored."""

    suit: Suit = Suit.HEARTS

    def on_card(self, event: CardScored, ctx: ScoreContext) -> Iterable[Effect]:
        if ctx.has_suit(event.card, self.suit):
            yield AddMult(3)


def _suit_joker(suit: Suit) -> type[_SuitMult]:
    class Built(_SuitMult):
        pass

    Built.suit = suit
    return Built


register("j_greedy_joker")(_suit_joker(Suit.DIAMONDS))
register("j_lusty_joker")(_suit_joker(Suit.HEARTS))
register("j_wrathful_joker")(_suit_joker(Suit.SPADES))
register("j_gluttenous_joker")(_suit_joker(Suit.CLUBS))


@register("j_scholar")
class Scholar(_PerScoredCard):
    """Played Aces give +20 Chips and +4 Mult when scored."""

    def on_card(self, event: CardScored, ctx: ScoreContext) -> Iterable[Effect]:
        if event.card.rank is Rank.ACE:
            yield AddChips(20)
            yield AddMult(4)


_ODD_RANKS = frozenset({Rank.ACE, Rank.NINE, Rank.SEVEN, Rank.FIVE, Rank.THREE})
_EVEN_RANKS = frozenset({Rank.TEN, Rank.EIGHT, Rank.SIX, Rank.FOUR, Rank.TWO})
_FIBONACCI_RANKS = frozenset({Rank.ACE, Rank.TWO, Rank.THREE, Rank.FIVE, Rank.EIGHT})


@register("j_odd_todd")
class OddTodd(_PerScoredCard):
    """Played cards with odd rank give +31 Chips when scored (A, 9, 7, 5, 3)."""

    def on_card(self, event: CardScored, ctx: ScoreContext) -> Iterable[Effect]:
        if not event.card.is_stone and event.card.rank in _ODD_RANKS:
            yield AddChips(31)


@register("j_even_steven")
class EvenSteven(_PerScoredCard):
    """Played cards with even rank give +4 Mult when scored (10, 8, 6, 4, 2)."""

    def on_card(self, event: CardScored, ctx: ScoreContext) -> Iterable[Effect]:
        if not event.card.is_stone and event.card.rank in _EVEN_RANKS:
            yield AddMult(4)


@register("j_fibonacci")
class Fibonacci(_PerScoredCard):
    """Each played Ace, 2, 3, 5, or 8 gives +8 Mult when scored."""

    def on_card(self, event: CardScored, ctx: ScoreContext) -> Iterable[Effect]:
        if not event.card.is_stone and event.card.rank in _FIBONACCI_RANKS:
            yield AddMult(8)


@register("j_photograph")
class Photograph(_PerScoredCard):
    """First played face card gives X2 Mult when scored."""

    def on_card(self, event: CardScored, ctx: ScoreContext) -> Iterable[Effect]:
        if ctx.is_face(event.card) and event.index == ctx.first_face_index():
            yield XMult(2)


# ---------------------------------------------------------------------------
# Карты, удерживаемые в руке
# ---------------------------------------------------------------------------


@register("j_baron")
class Baron(BaseJoker):
    """Each King held in hand gives X1.5 Mult."""

    def react(self, event: Event, ctx: ScoreContext) -> Iterable[Effect]:
        if isinstance(event, CardHeld) and event.card.rank is Rank.KING:
            yield XMult(1.5)


# ---------------------------------------------------------------------------
# Ретриггеры
# ---------------------------------------------------------------------------


@register("j_mime")
class Mime(BaseJoker):
    """Retrigger all card held in hand abilities."""

    def react(self, event: Event, ctx: ScoreContext) -> Iterable[Effect]:
        if isinstance(event, RetriggerQuery) and event.in_hand:
            yield Retrigger(1)


_HACK_RANKS = frozenset({Rank.TWO, Rank.THREE, Rank.FOUR, Rank.FIVE})


@register("j_hack")
class Hack(BaseJoker):
    """Retrigger each played 2, 3, 4, or 5."""

    def react(self, event: Event, ctx: ScoreContext) -> Iterable[Effect]:
        if (
            isinstance(event, RetriggerQuery)
            and not event.in_hand
            and not event.card.is_stone
            and event.card.rank in _HACK_RANKS
        ):
            yield Retrigger(1)


@register("j_hanging_chad")
class HangingChad(BaseJoker):
    """Retrigger first played card used in scoring 2 additional times."""

    def react(self, event: Event, ctx: ScoreContext) -> Iterable[Effect]:
        if isinstance(event, RetriggerQuery) and not event.in_hand and event.index == 0:
            yield Retrigger(2)


@register("j_dusk")
class Dusk(BaseJoker):
    """Retrigger all played cards in final hand of the round."""

    def react(self, event: Event, ctx: ScoreContext) -> Iterable[Effect]:
        if isinstance(event, RetriggerQuery) and not event.in_hand and ctx.state.hands_left <= 1:
            yield Retrigger(1)


# ---------------------------------------------------------------------------
# Копирующие: ради них джокер и сделан функцией, а не строкой таблицы
# ---------------------------------------------------------------------------


class _Copycat(BaseJoker):
    """Общая часть копирующих джокеров."""

    def target(self, ctx: ScoreContext) -> Joker | None:
        return None

    def react(self, event: Event, ctx: ScoreContext) -> Iterable[Effect]:
        target = self.target(ctx)
        if target is None:
            return ()
        if isinstance(event, JokerTurn):
            if event.joker is not self:
                return ()
            # Подменяем очередь на очередь цели, иначе она себя не узнает.
            event = JokerTurn(target)
        return target.react(event, ctx)


@register("j_blueprint")
class Blueprint(_Copycat):
    """Copies ability of Joker to the right."""

    def target(self, ctx: ScoreContext) -> Joker | None:
        return ctx.joker_to_the_right(self)


@register("j_brainstorm")
class Brainstorm(_Copycat):
    """Copies the ability of leftmost Joker."""

    def target(self, ctx: ScoreContext) -> Joker | None:
        return ctx.leftmost_joker(self)


# ---------------------------------------------------------------------------
# Меняющие правила распознавания руки
# ---------------------------------------------------------------------------


class _RuleChanger(BaseJoker):
    """Ничего не считает: флаг снимается в `modifiers_from` до подсчёта."""


register("j_four_fingers")(_RuleChanger)
register("j_shortcut")(_RuleChanger)
register("j_smeared")(_RuleChanger)


# ---------------------------------------------------------------------------
# Зависящие от состояния рана
# ---------------------------------------------------------------------------


@register("j_bull")
class Bull(_OwnTurn):
    """+2 Chips for each $1 you have."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        if ctx.state.money > 0:
            yield AddChips(2 * ctx.state.money)


@register("j_banner")
class Banner(_OwnTurn):
    """+30 Chips for each remaining discard."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        if ctx.state.discards_left > 0:
            yield AddChips(30 * ctx.state.discards_left)


@register("j_abstract")
class AbstractJoker(_OwnTurn):
    """+3 Mult for each Joker card."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        yield AddMult(3 * len(ctx.jokers))


@register("j_supernova")
class Supernova(_OwnTurn):
    """Adds the number of times poker hand has been played this run to Mult."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        info = ctx.state.hand_info.get(ctx.hand_type)
        if info is None:
            ctx.mark_unknown("Supernova: неизвестно, сколько раз рука уже игралась")
            return
        yield AddMult(info.played)


#: Misprint даёт равновероятно от 0 до 23 множителя.
_MISPRINT_OUTCOMES = tuple((float(value), 1 / 24) for value in range(24))


@register("j_misprint")
class Misprint(_OwnTurn):
    """+0-23 Mult."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        yield AddMult(ctx.chance(_MISPRINT_OUTCOMES))
