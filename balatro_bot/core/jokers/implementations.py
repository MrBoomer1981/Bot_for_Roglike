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

from balatro_bot.core.cards import Card, Enhancement, Rank, Suit
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
    double_chance,
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


@register("j_gros_michel")
class GrosMichel(_OwnTurn):
    """+15 Mult 1 in 6 chance this is destroyed at the end of round.

    Уничтожение — эффект конца раунда, к счёту этого розыгрыша отношения не
    имеет: пока джокер в раскладке (а он в ней, раз мод его прислал), +15
    срабатывает безусловно.
    """

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        yield AddMult(15)


@register("j_cavendish")
class Cavendish(_OwnTurn):
    """X3 Mult 1 in 1000 chance this card is destroyed at the end of round.

    Та же логика, что у Gros Michel: уничтожение решается после подсчёта.
    """

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        yield XMult(3)


@register("j_stuntman")
class Stuntman(_OwnTurn):
    """+250 Chips, -2 hand size.

    Уменьшенный размер руки уже виден в самой руке, которую прислал мод —
    отдельно считать не нужно.
    """

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        yield AddChips(250)


# ---------------------------------------------------------------------------
# «Если рука содержит …»
# ---------------------------------------------------------------------------


class _ConditionalJoker(_OwnTurn):
    """Прибавка, если состав руки удовлетворяет условию."""

    condition: str = ""
    chips: float = 0.0
    mult: float = 0.0
    xmult: float = 0.0

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        if not self._holds(ctx):
            return
        if self.chips:
            yield AddChips(self.chips)
        if self.mult:
            yield AddMult(self.mult)
        if self.xmult:
            yield XMult(self.xmult)

    def _holds(self, ctx: ScoreContext) -> bool:
        match self.condition:
            case "pair":
                return ctx.contains_pair
            case "two_pair":
                return ctx.contains_two_pair
            case "three":
                return ctx.contains_three
            case "four":
                return ctx.contains_four
            case "straight":
                return ctx.contains_straight
            case "flush":
                return ctx.contains_flush
        return False


def _conditional(
    condition: str, *, chips: float = 0.0, mult: float = 0.0, xmult: float = 0.0
) -> type[_ConditionalJoker]:
    """Собрать класс джокера «если рука содержит …»."""

    class Built(_ConditionalJoker):
        pass

    Built.condition = condition
    Built.chips = chips
    Built.mult = mult
    Built.xmult = xmult
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

# X2/X3/X4/X3/X2 Mult если рука содержит пару / тройку / каре / стрит / флеш
register("j_duo")(_conditional("pair", xmult=2))
register("j_trio")(_conditional("three", xmult=3))
register("j_family")(_conditional("four", xmult=4))
register("j_order")(_conditional("straight", xmult=3))
register("j_tribe")(_conditional("flush", xmult=2))


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


class _SuitBonus(_PerScoredCard):
    """Played cards with <suit> suit give +chips/+mult when scored."""

    suit: Suit = Suit.HEARTS
    chips: float = 0.0
    mult: float = 0.0

    def on_card(self, event: CardScored, ctx: ScoreContext) -> Iterable[Effect]:
        if not ctx.has_suit(event.card, self.suit):
            return
        if self.chips:
            yield AddChips(self.chips)
        if self.mult:
            yield AddMult(self.mult)


def _suit_joker(suit: Suit, *, chips: float = 0.0, mult: float = 0.0) -> type[_SuitBonus]:
    class Built(_SuitBonus):
        pass

    Built.suit = suit
    Built.chips = chips
    Built.mult = mult
    return Built


register("j_greedy_joker")(_suit_joker(Suit.DIAMONDS, mult=3))
register("j_lusty_joker")(_suit_joker(Suit.HEARTS, mult=3))
register("j_wrathful_joker")(_suit_joker(Suit.SPADES, mult=3))
register("j_gluttenous_joker")(_suit_joker(Suit.CLUBS, mult=3))

register("j_arrowhead")(_suit_joker(Suit.SPADES, chips=50))
register("j_onyx_agate")(_suit_joker(Suit.CLUBS, mult=7))


_ALL_SUITS = frozenset(Suit)


@register("j_flower_pot")
class FlowerPot(_OwnTurn):
    """X3 Mult if poker hand contains a Diamond, Club, Heart, and Spade card."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        suits_present = {suit for card in ctx.scoring_cards for suit in ctx.suits_of(card)}
        if suits_present >= _ALL_SUITS:
            yield XMult(3)


@register("j_seeing_double")
class SeeingDouble(_OwnTurn):
    """X2 Mult if played hand has a scoring Club card and a scoring card of any other suit."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        has_club = any(ctx.has_suit(card, Suit.CLUBS) for card in ctx.scoring_cards)
        has_other = any(ctx.suits_of(card) - {Suit.CLUBS} for card in ctx.scoring_cards)
        if has_club and has_other:
            yield XMult(2)


#: Bloodstone: шанс 1 к 2 на X1.5 множителя.
_BLOODSTONE_OUTCOMES: tuple[tuple[float, float], ...] = ((1.0, 0.5), (1.5, 0.5))


@register("j_bloodstone")
class Bloodstone(_PerScoredCard):
    """1 in 2 chance for played cards with Heart suit to give X1.5 Mult when scored."""

    def on_card(self, event: CardScored, ctx: ScoreContext) -> Iterable[Effect]:
        if not ctx.has_suit(event.card, Suit.HEARTS):
            return
        outcomes = (
            double_chance(_BLOODSTONE_OUTCOMES) if ctx.modifiers.oops else _BLOODSTONE_OUTCOMES
        )
        factor = ctx.chance(outcomes)
        if factor != 1.0:
            yield XMult(factor)


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


@register("j_scary_face")
class ScaryFace(_PerScoredCard):
    """Played face cards give +30 Chips when scored."""

    def on_card(self, event: CardScored, ctx: ScoreContext) -> Iterable[Effect]:
        if ctx.is_face(event.card):
            yield AddChips(30)


@register("j_smiley")
class Smiley(_PerScoredCard):
    """Played face cards give +5 Mult when scored."""

    def on_card(self, event: CardScored, ctx: ScoreContext) -> Iterable[Effect]:
        if ctx.is_face(event.card):
            yield AddMult(5)


_WALKIE_TALKIE_RANKS = frozenset({Rank.TEN, Rank.FOUR})


@register("j_walkie_talkie")
class WalkieTalkie(_PerScoredCard):
    """Each played 10 or 4 gives +10 Chips and +4 Mult when scored."""

    def on_card(self, event: CardScored, ctx: ScoreContext) -> Iterable[Effect]:
        if not event.card.is_stone and event.card.rank in _WALKIE_TALKIE_RANKS:
            yield AddChips(10)
            yield AddMult(4)


_TRIBOULET_RANKS = frozenset({Rank.KING, Rank.QUEEN})


@register("j_triboulet")
class Triboulet(_PerScoredCard):
    """Played Kings and Queens each give X2 Mult when scored."""

    def on_card(self, event: CardScored, ctx: ScoreContext) -> Iterable[Effect]:
        if not event.card.is_stone and event.card.rank in _TRIBOULET_RANKS:
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


@register("j_shoot_the_moon")
class ShootTheMoon(BaseJoker):
    """Each Queen held in hand gives +13 Mult."""

    def react(self, event: Event, ctx: ScoreContext) -> Iterable[Effect]:
        if isinstance(event, CardHeld) and event.card.rank is Rank.QUEEN:
            yield AddMult(13)


@register("j_raised_fist")
class RaisedFist(_OwnTurn):
    """Adds double the rank of lowest ranked card held in hand to Mult."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        held = [card for card in ctx.held if not card.is_stone]
        if not held:
            return
        lowest = min(held, key=lambda card: card.rank.order)
        yield AddMult(2 * lowest.rank.chips)


@register("j_blackboard")
class Blackboard(_OwnTurn):
    """X3 Mult if all cards held in hand are Spades or Clubs."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        # Пустая рука в руке — условие выполняется на пустом множестве.
        if all(
            ctx.has_suit(card, Suit.SPADES) or ctx.has_suit(card, Suit.CLUBS) for card in ctx.held
        ):
            yield XMult(3)


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


@register("j_selzer")
class Selzer(BaseJoker):
    """Retrigger all cards played for the next 10 hands.

    Заряды («следующие 10 рук») мод отдельным числом не присылает. Раз
    джокер ещё в раскладке — заряды не кончились: когда они кончаются, игра
    сама убирает Selzer из джокеров. «Джокер есть» здесь и значит «активен».
    """

    def react(self, event: Event, ctx: ScoreContext) -> Iterable[Effect]:
        if isinstance(event, RetriggerQuery) and not event.in_hand:
            yield Retrigger(1)


@register("j_sock_and_buskin")
class SockAndBuskin(BaseJoker):
    """Retrigger all played face cards."""

    def react(self, event: Event, ctx: ScoreContext) -> Iterable[Effect]:
        if isinstance(event, RetriggerQuery) and not event.in_hand and ctx.is_face(event.card):
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
        if target is None or any(item is self for item in ctx.copying):
            # Мы уже в цепочке копирования: дальше идти нельзя, иначе
            # Blueprint и Brainstorm, поставленные рядом, зациклятся.
            return ()
        if isinstance(event, JokerTurn):
            if event.joker is not self:
                return ()
            # Подменяем очередь на очередь цели, иначе она себя не узнает.
            event = JokerTurn(target)

        ctx.copying.append(self)
        try:
            # Список, а не генератор: иначе цель отработает уже после того,
            # как защита снимется.
            return list(target.react(event, ctx))
        finally:
            ctx.copying.pop()


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
register("j_splash")(_RuleChanger)
register("j_pareidolia")(_RuleChanger)
register("j_chicot")(_RuleChanger)
register("j_oops")(_RuleChanger)


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


@register("j_mystic_summit")
class MysticSummit(_OwnTurn):
    """+15 Mult when 0 discards remaining."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        if ctx.state.discards_left <= 0:
            yield AddMult(15)


@register("j_acrobat")
class Acrobat(_OwnTurn):
    """X3 Mult on final hand of round."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        if ctx.state.hands_left <= 1:
            yield XMult(3)


@register("j_card_sharp")
class CardSharp(_OwnTurn):
    """X3 Mult if played poker hand has already been played this round."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        info = ctx.state.hand_info.get(ctx.hand_type)
        if info is None:
            ctx.mark_unknown("Card Sharp: неизвестно, сыграна ли уже такая рука в этом раунде")
            return
        if info.played_this_round > 0:
            yield XMult(3)


@register("j_bootstraps")
class Bootstraps(_OwnTurn):
    """+2 Mult for every $5 you have."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        if ctx.state.money > 0:
            yield AddMult(2 * (ctx.state.money // 5))


@register("j_blue_joker")
class BlueJoker(_OwnTurn):
    """+2 Chips for each remaining card in deck."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        if ctx.state.deck is None:
            ctx.mark_unknown("Blue Joker: колода неизвестна без моста к моду")
            return
        yield AddChips(2 * len(ctx.state.deck))


@register("j_swashbuckler")
class Swashbuckler(_OwnTurn):
    """Adds the sell value of all other owned Jokers to Mult."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        others = [joker for joker in ctx.jokers if joker is not self]
        if any(joker.card.sell_value is None for joker in others):
            ctx.mark_unknown("Swashbuckler: цена продажи джокера неизвестна")
            return
        total = sum(joker.card.sell_value or 0 for joker in others)
        if total:
            yield AddMult(total)


@register("j_ice_cream")
class IceCream(_OwnTurn):
    """+100 Chips -5 Chips for every hand played.

    Не сверено с игрой (падает ли ниже нуля) — как и базовые значения рук,
    подлежит проверке golden-кейсом в Фазе 3a.
    """

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        yield AddChips(100 - 5 * ctx.state.hands_played)


@register("j_stencil")
class Stencil(_OwnTurn):
    """X1 Mult for each empty Joker slot. Joker Stencil included.

    Формула — `1 + пустые_слоты`, сам Stencil занимает слот и пустым не
    считается. Не сверено с игрой, как и базовые значения рук.
    """

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        if ctx.state.joker_slots is None:
            ctx.mark_unknown("Stencil: вместимость слотов джокеров неизвестна")
            return
        empty = max(ctx.state.joker_slots - len(ctx.jokers), 0)
        yield XMult(1 + empty)


class _FullDeckJoker(_OwnTurn):
    """Общая часть для джокеров, считающих по всей колоде.

    `state.full_deck` известен точно только в узком случае — см. его
    докстринг в `core/state.py`. Вне этого случая честно помечаем неточность
    вместо того, чтобы принять оставшуюся колоду (`state.deck`) за полную.
    """

    #: Человекочитаемое имя для сообщения о неточности. Не называть `name` —
    #: это свойство `Joker.name` (label/key), используемое в разборе счёта.
    label: str = ""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        if ctx.state.full_deck is None:
            ctx.mark_unknown(f"{self.label}: полный состав колоды неизвестен")
            return
        yield from self.on_full_deck(ctx.state.full_deck, ctx)

    def on_full_deck(self, full_deck: tuple[Card, ...], ctx: ScoreContext) -> Iterable[Effect]:
        return ()


@register("j_steel_joker")
class SteelJoker(_FullDeckJoker):
    """Gives X0.2 Mult for each Steel Card in your full deck."""

    label = "Steel Joker"

    def on_full_deck(self, full_deck: tuple[Card, ...], ctx: ScoreContext) -> Iterable[Effect]:
        steel = sum(1 for card in full_deck if card.enhancement is Enhancement.STEEL)
        if steel:
            yield XMult(1 + 0.2 * steel)


@register("j_stone")
class StoneJoker(_FullDeckJoker):
    """Gives +25 Chips for each Stone Card in your full deck."""

    label = "Stone Joker"

    def on_full_deck(self, full_deck: tuple[Card, ...], ctx: ScoreContext) -> Iterable[Effect]:
        stone = sum(1 for card in full_deck if card.is_stone)
        if stone:
            yield AddChips(25 * stone)


@register("j_drivers_license")
class DriversLicense(_FullDeckJoker):
    """X3 Mult if you have at least 16 Enhanced cards in your full deck."""

    label = "Driver's License"

    def on_full_deck(self, full_deck: tuple[Card, ...], ctx: ScoreContext) -> Iterable[Effect]:
        enhanced = sum(1 for card in full_deck if card.enhancement is not Enhancement.NONE)
        if enhanced >= 16:
            yield XMult(3)


#: Стартовый размер колоды по типу (поле `deck` в состоянии мода, не путать с
#: `state.deck` — оставшимся добором). У всех колод 52 карты, кроме
#: `ABANDONED`: она начинает без картинок (J/Q/K × 4 масти = 12 карт долой).
_DECK_STARTING_SIZE: dict[str, int] = {
    "RED": 52,
    "BLUE": 52,
    "YELLOW": 52,
    "GREEN": 52,
    "BLACK": 52,
    "MAGIC": 52,
    "NEBULA": 52,
    "GHOST": 52,
    "ABANDONED": 40,
    "CHECKERED": 52,
    "ZODIAC": 52,
    "PAINTED": 52,
    "ANAGLYPH": 52,
    "PLASMA": 52,
    "ERRATIC": 52,
}


@register("j_erosion")
class Erosion(_FullDeckJoker):
    """+4 Mult for each card below the deck's starting size in your full deck."""

    label = "Erosion"

    def on_full_deck(self, full_deck: tuple[Card, ...], ctx: ScoreContext) -> Iterable[Effect]:
        starting = _DECK_STARTING_SIZE.get(ctx.state.deck_type or "")
        if starting is None:
            ctx.mark_unknown(f"{self.label}: тип колоды неизвестен")
            return
        missing = max(starting - len(full_deck), 0)
        if missing:
            yield AddMult(4 * missing)


#: Misprint даёт равновероятно от 0 до 23 множителя.
_MISPRINT_OUTCOMES = tuple((float(value), 1 / 24) for value in range(24))


@register("j_misprint")
class Misprint(_OwnTurn):
    """+0-23 Mult."""

    def on_turn(self, ctx: ScoreContext) -> Iterable[Effect]:
        yield AddMult(ctx.chance(_MISPRINT_OUTCOMES))


# ---------------------------------------------------------------------------
# Известны, но на счёт розыгрыша не влияют
# ---------------------------------------------------------------------------
#
# Это не «нереализовано»: эффект этих джокеров прочитан из справочника и
# заведомо не трогает chips/mult текущего розыгрыша — деньги приходят помимо
# счёта, а прокачка уровня руки при сбросе уже видна через `state.hand_info`
# (мод присылает уровни сам). Отметить их молчаливым `BaseJoker` — не догадка,
# а честный итог: посчитан ноль, а не «не знаю».


@register("j_burnt")
class BurntJoker(BaseJoker):
    """Upgrade the level of the first discarded poker hand each round.

    Уровень руки, который это поднимает, солвер уже видит через
    `state.hand_info` — его присылает мод, а не мы его вычисляем. К счёту
    *этого* розыгрыша эффект отношения не имеет: он срабатывает на сбросе.
    """


@register("j_rough_gem")
class RoughGem(BaseJoker):
    """Played cards with Diamond suit earn $1 when scored."""


@register("j_business")
class BusinessCard(BaseJoker):
    """Played face cards have a 1 in 2 chance to give $2 when scored."""


@register("j_reserved_parking")
class ReservedParking(BaseJoker):
    """Each face card held in hand has a 1 in 2 chance to give $1."""


@register("j_ticket")
class GoldenTicket(BaseJoker):
    """Played Gold cards earn $4 when scored."""


# -- Деньги: приходят помимо счёта, когда бы триггер ни сработал -----------


@register("j_cloud_9")
class Cloud9(BaseJoker):
    """Earn $1 for each 9 in your full deck at end of round."""


@register("j_delayed_grat")
class DelayedGratification(BaseJoker):
    """Earn $2 per discard if no discards are used by end of the round."""


@register("j_egg")
class Egg(BaseJoker):
    """Gains $3 of sell value at end of round."""


@register("j_faceless")
class FacelessJoker(BaseJoker):
    """Earn $5 if 3 or more face cards are discarded at the same time."""


@register("j_gift")
class GiftCard(BaseJoker):
    """Add $1 of sell value to every Joker and Consumable card at end of round."""


@register("j_golden")
class GoldenJoker(BaseJoker):
    """Earn $4 at end of round."""


@register("j_mail")
class MailInRebate(BaseJoker):
    """Earn $5 for each discarded [rank], rank changes every round."""


@register("j_matador")
class Matador(BaseJoker):
    """Earn $8 if played hand triggers the Boss Blind ability."""


@register("j_rocket")
class Rocket(BaseJoker):
    """Earn $1 at end of round. Payout increases by $2 when Boss Blind is defeated."""


@register("j_satellite")
class Satellite(BaseJoker):
    """Earn $1 at end of round per unique Planet card used this run."""


@register("j_to_the_moon")
class ToTheMoon(BaseJoker):
    """Earn an extra $1 of interest for every $5 you have at end of round."""


@register("j_todo_list")
class TodoList(BaseJoker):
    """Earn $4 if poker hand is a [Poker Hand], poker hand changes at end of round."""


@register("j_trading")
class TradingCard(BaseJoker):
    """If first discard of round has only 1 card, destroy it and earn $3."""


# -- Расходники: создают Tarot/Spectral, не влияют на текущий счёт ---------


@register("j_8_ball")
class EightBall(BaseJoker):
    """1 in 4 chance for each played 8 to create a Tarot card when scored (Must have room)."""


@register("j_cartomancer")
class Cartomancer(BaseJoker):
    """Create a Tarot card when Blind is selected (Must have room)."""


@register("j_hallucination")
class Hallucination(BaseJoker):
    """1 in 2 chance to create a Tarot card when any Booster Pack is opened (Must have room)."""


@register("j_riff_raff")
class RiffRaff(BaseJoker):
    """When Blind is selected, create 2 Common Jokers (Must have room)."""


@register("j_seance")
class Seance(BaseJoker):
    """If poker hand is a Straight Flush, create a random Spectral card (Must have room)."""


@register("j_sixth_sense")
class SixthSense(BaseJoker):
    """If first hand of round is a single 6, destroy it and create a Spectral card."""


@register("j_superposition")
class Superposition(BaseJoker):
    """Create a Tarot card if poker hand contains an Ace and a Straight (Must have room)."""


@register("j_vagabond")
class Vagabond(BaseJoker):
    """Create a Tarot card if hand is played with $4 or less."""


@register("j_perkeo")
class Perkeo(BaseJoker):
    """Creates a Negative copy of 1 random consumable in your possession at the end of the shop."""


# -- Размер руки / сбросы: уже отражены в присланном состоянии -------------


@register("j_juggler")
class Juggler(BaseJoker):
    """+1 hand size."""


@register("j_drunkard")
class Drunkard(BaseJoker):
    """+1 discard each round."""


@register("j_merry_andy")
class MerryAndy(BaseJoker):
    """+3 discards each round, -1 hand size."""


@register("j_troubadour")
class Troubadour(BaseJoker):
    """+2 hand size, -1 hand each round."""


@register("j_turtle_bean")
class TurtleBean(BaseJoker):
    """+5 hand size, reduces by 1 each round."""


@register("j_burglar")
class Burglar(BaseJoker):
    """When Blind is selected, gain +3 Hands and lose all discards."""


@register("j_marble")
class MarbleJoker(BaseJoker):
    """Adds one Stone card to the deck when Blind is selected."""


@register("j_dna")
class DNA(BaseJoker):
    """If first hand of round has only 1 card, add a permanent copy to deck and draw it to hand."""


@register("j_certificate")
class Certificate(BaseJoker):
    """When round begins, add a random playing card with a random seal to your hand."""


# -- Магазин / метаигра: не про счёт розыгрыша ------------------------------


@register("j_astronomer")
class Astronomer(BaseJoker):
    """All Planet cards and Celestial Packs in the shop are free."""


@register("j_chaos")
class ChaosTheClown(BaseJoker):
    """1 free Reroll per shop."""


@register("j_credit_card")
class CreditCard(BaseJoker):
    """Go up to -$20 in debt."""


@register("j_diet_cola")
class DietCola(BaseJoker):
    """Sell this card to create a free Double Tag."""


@register("j_invisible")
class InvisibleJoker(BaseJoker):
    """After 2 rounds, sell this card to Duplicate a random Joker (Currently 0/2)."""


@register("j_luchador")
class Luchador(BaseJoker):
    """Sell this card to disable the current Boss Blind."""


@register("j_ring_master")
class RingMaster(BaseJoker):
    """Joker, Tarot, Planet, and Spectral cards may appear multiple times."""


@register("j_mr_bones")
class MrBones(BaseJoker):
    """Prevents Death if chips scored are at least 25% of required chips, self destructs."""


# -- Меняют карты, но не то, что они дают при подсчёте ----------------------


@register("j_midas_mask")
class MidasMask(BaseJoker):
    """All played face cards become Gold cards when scored.

    Gold — про деньги при удержании в конце раунда, не про chips/mult при
    подсчёте: см. `_ENHANCEMENT_CHIPS`/`_ENHANCEMENT_MULT` в `scoring.py`,
    там `Enhancement.GOLD` не значится. На счёт этого розыгрыша не влияет.
    """


@register("j_space")
class SpaceJoker(BaseJoker):
    """1 in 4 chance to upgrade level of played poker hand.

    Прокачка применяется после подсчёта текущего хода: на его счёт не
    влияет, а следующий уровень солвер и так увидит через `state.hand_info`.
    """
