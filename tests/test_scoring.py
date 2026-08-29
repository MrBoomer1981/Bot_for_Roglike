"""Тесты симулятора подсчёта очков.

Числа посчитаны вручную от базовых значений руки. Базовые таблицы пока
провизорные, поэтому тесты проверяют не их, а **логику сборки счёта**:
порядок шагов, срабатывание эффектов, ретриггеры, копирование.

Когда в Фазе 3 появятся эталонные случаи из настоящей игры, они проверят
уже сами числа.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from balatro_bot.core.cards import (
    Card,
    Edition,
    Enhancement,
    Rank,
    Seal,
    Suit,
    parse_cards,
    standard_deck,
)
from balatro_bot.core.catalogue import JOKERS
from balatro_bot.core.hands import HandType
from balatro_bot.core.jokers.implementations import _JOKER_RARITY
from balatro_bot.core.scoring import ScoreOutcome, score_play
from balatro_bot.core.state import BlindInfo, GameState, JokerCard, PokerHandInfo


def сыграть(
    hand: Sequence[Card],
    play: Sequence[int],
    jokers: Sequence[str] = (),
    joker_values: dict[str, float] | None = None,
    **state_kwargs: object,
) -> ScoreOutcome:
    """Разыграть карты руки по индексам. Остальные считаются оставшимися в руке."""
    values = joker_values or {}
    state = GameState(
        hand=tuple(hand),
        jokers=tuple(JokerCard(key, current_value=values.get(key)) for key in jokers),
        **state_kwargs,  # type: ignore[arg-type]
    )
    return score_play(state, [state.hand[index] for index in play])


def карта(rank: Rank = Rank.ACE, suit: Suit = Suit.HEARTS, **kwargs: object) -> Card:
    return Card(rank, suit, **kwargs)  # type: ignore[arg-type]


class TestОснова:
    def test_старшая_карта(self) -> None:
        # База 5/1, туз даёт 11 очков: (5 + 11) × 1
        assert сыграть(parse_cards("AH"), [0]).expected == 16

    def test_пара(self) -> None:
        # База 10/2, два туза по 11: (10 + 22) × 2
        assert сыграть(parse_cards("AH AD"), [0, 1]).expected == 64

    def test_картинки_дают_десять(self) -> None:
        assert сыграть(parse_cards("KH"), [0]).expected == 15

    def test_тип_руки_попадает_в_итог(self) -> None:
        assert сыграть(parse_cards("AH AD"), [0, 1]).hand_type is HandType.PAIR

    def test_разбор_не_пустой(self) -> None:
        assert len(сыграть(parse_cards("AH AD"), [0, 1]).trace) > 0

    def test_прокачанный_уровень_виден_в_разборе(self) -> None:
        info = {HandType.PAIR: PokerHandInfo(level=3, chips=10, mult=2)}
        outcome = сыграть(parse_cards("AH AD"), [0, 1], hand_info=info)
        assert "уровень 3" in outcome.trace[0].detail

    def test_первый_уровень_не_упоминается_в_разборе(self) -> None:
        assert "уровень" not in сыграть(parse_cards("AH AD"), [0, 1]).trace[0].detail


class TestУлучшенияКарт:
    def test_bonus_даёт_очки(self) -> None:
        # (5 + 11 + 30) × 1
        assert сыграть([карта(enhancement=Enhancement.BONUS)], [0]).expected == 46

    def test_mult_даёт_множитель(self) -> None:
        # (5 + 11) × (1 + 4)
        assert сыграть([карта(enhancement=Enhancement.MULT)], [0]).expected == 80

    def test_glass_умножает(self) -> None:
        # (5 + 11) × (1 × 2)
        assert сыграть([карта(enhancement=Enhancement.GLASS)], [0]).expected == 32

    def test_stone_даёт_очки_но_не_ранг(self) -> None:
        # Каменная карта не имеет ранга: (5 + 50) × 1
        assert сыграть([карта(enhancement=Enhancement.STONE)], [0]).expected == 55

    def test_steel_работает_только_в_руке(self) -> None:
        # Сыграна обычная карта, steel остался в руке: (5 + 11) × (1 × 1.5)
        hand = [карта(), карта(Rank.KING, Suit.SPADES, enhancement=Enhancement.STEEL)]
        assert сыграть(hand, [0]).expected == 24

    def test_steel_не_срабатывает_если_сыгран(self) -> None:
        assert сыграть([карта(enhancement=Enhancement.STEEL)], [0]).expected == 16


class TestИздания:
    def test_foil(self) -> None:
        assert сыграть([карта(edition=Edition.FOIL)], [0]).expected == 66

    def test_holographic(self) -> None:
        assert сыграть([карта(edition=Edition.HOLOGRAPHIC)], [0]).expected == 176

    def test_polychrome(self) -> None:
        assert сыграть([карта(edition=Edition.POLYCHROME)], [0]).expected == 24


class TestПорядокВажен:
    def test_умножение_карты_идёт_до_прибавок_джокера(self) -> None:
        # Polychrome умножает множитель на шаге карты: (1 × 1.5) + 4 = 5.5
        # Если бы джокер успевал раньше, вышло бы (1 + 4) × 1.5 = 7.5.
        outcome = сыграть([карта(edition=Edition.POLYCHROME)], [0], ["j_joker"])
        assert outcome.expected == 16 * 5.5

    def test_джокеры_срабатывают_слева_направо(self) -> None:
        # Blueprint слева копирует соседа справа, значит +4 дважды.
        left = сыграть(parse_cards("AH AD"), [0, 1], ["j_blueprint", "j_joker"])
        # Справа копировать некого — только собственные +4.
        right = сыграть(parse_cards("AH AD"), [0, 1], ["j_joker", "j_blueprint"])
        assert left.expected == 320
        assert right.expected == 192


class TestДебафф:
    def test_отключённая_карта_не_даёт_очков(self) -> None:
        # Обе карты образуют пару, но одна отключена боссом: (10 + 11) × 2
        hand = [карта(), карта(Rank.ACE, Suit.DIAMONDS, debuffed=True)]
        assert сыграть(hand, [0, 1]).expected == 42


class TestОтключённыйДжокер:
    """`JokerCard.debuffed` — джокер отключён игрой (истёкший `perishable`
    на ставке `ORANGE`+). Эффекта не даёт, но слот занимает — как в самой
    игре (`card.lua`'s `calculate_joker`: `if self.debuff then return nil`)."""

    def test_отключённый_джокер_не_даёт_эффекта(self) -> None:
        hand = parse_cards("AH KD")
        base = score_play(GameState(hand=hand), [hand[0]]).expected
        with_active = score_play(
            GameState(hand=hand, jokers=(JokerCard("j_joker"),)), [hand[0]]
        ).expected
        with_debuffed = score_play(
            GameState(hand=hand, jokers=(JokerCard("j_joker", debuffed=True),)), [hand[0]]
        ).expected
        assert with_active > base  # +4 множителя от активного
        assert with_debuffed == base  # отключённый не считается

    def test_отключённый_нереализованный_джокер_не_добавляет_причину_неточности(self) -> None:
        # Отключённый джокер эффекта не даёт независимо от того, реализован
        # ли он — значит `UnimplementedJoker` за него `unknown` не ставит
        # (провизорная таблица рук — отдельная, не связанная причина).
        hand = parse_cards("AH KD")
        outcome = score_play(
            GameState(hand=hand, jokers=(JokerCard("j_совсем_новый", debuffed=True),)), [hand[0]]
        )
        assert not any("реализован" in reason for reason in outcome.unknown)

    def test_отключённое_издание_джокера_не_применяется(self) -> None:
        hand = parse_cards("AH KD")
        base = score_play(GameState(hand=hand), [hand[0]]).expected
        outcome = score_play(
            GameState(
                hand=hand,
                jokers=(JokerCard("j_joker", edition=Edition.FOIL, debuffed=True),),
            ),
            [hand[0]],
        )
        assert outcome.expected == base  # ни +4 множителя, ни +50 очков от Foil

    def test_отключённый_правило_модификатор_не_меняет_правил(self) -> None:
        # j_four_fingers обычно разрешает флеш из 4 карт. Отключённый — нет:
        # 4 несмежные червы дают хай-карту, а не флеш.
        hand = parse_cards("AH KH QH 9H")
        active = score_play(GameState(hand=hand, jokers=(JokerCard("j_four_fingers"),)), list(hand))
        debuffed = score_play(
            GameState(hand=hand, jokers=(JokerCard("j_four_fingers", debuffed=True),)), list(hand)
        )
        assert active.hand_type is HandType.FLUSH
        assert debuffed.hand_type is HandType.HIGH_CARD

    def test_отключённый_джокер_виден_считающим_джокеров(self) -> None:
        # j_abstract: «+3 множителя за каждую карту-джокер». Отключённый
        # джокер физически в слоте — как и в игре (`#G.jokers.cards`), он
        # входит в счёт, хотя своего эффекта не даёт.
        hand = parse_cards("AH KD")
        alone = score_play(GameState(hand=hand, jokers=(JokerCard("j_abstract"),)), [hand[0]])
        pair = (JokerCard("j_abstract"), JokerCard("j_joker", debuffed=True))
        with_debuffed = score_play(GameState(hand=hand, jokers=pair), [hand[0]])
        # alone: +3 множителя (1 джокер). with_debuffed: +6 (2 джокера),
        # и ничего от отключённого j_joker.
        assert with_debuffed.expected > alone.expected


def _flint(required_score: int = 300) -> BlindInfo:
    return BlindInfo("BOSS", "The Flint", "", required_score)


def _other_boss(required_score: int = 300) -> BlindInfo:
    return BlindInfo("BOSS", "The Wall", "", required_score)


class TestБоссФлинт:
    """`The Flint` уполовинивает базовые фишки/множитель руки — формула из
    `blind.lua`'s `Blind:modify_hand`, см. `core/bosses.py` и
    `core/scoring.py._apply_boss_score_modifier`."""

    def test_уполовинивает_базовые_фишки_и_множитель(self) -> None:
        # Пара: база 10/2 -> уполовинена до 5/1. Две карты по 11 очков:
        # (5 + 11 + 11) × 1 = 27, вместо (10 + 11 + 11) × 2 = 64 без Флинта.
        hand = parse_cards("AH AD")
        assert сыграть(hand, [0, 1], blind=_flint()).expected == 27
        assert сыграть(hand, [0, 1]).expected == 64

    def test_минимум_один_у_множителя_и_ноль_у_фишек(self) -> None:
        # Высокая карта: база 5/1 -> floor(5*0.5+0.5)=3, floor(1*0.5+0.5)=1
        # (минимум мультипликатора и так 1). (3 + 11) × 1 = 14.
        assert сыграть(parse_cards("AH"), [0], blind=_flint()).expected == 14

    def test_другой_босс_не_уполовинивает(self) -> None:
        hand = parse_cards("AH AD")
        assert сыграть(hand, [0, 1], blind=_other_boss()).expected == 64

    def test_без_блайнда_не_уполовинивает(self) -> None:
        assert сыграть(parse_cards("AH"), [0]).expected == 16

    def test_без_джокеров_расчёт_точный(self) -> None:
        info = {HandType.PAIR: PokerHandInfo(level=1, chips=10, mult=2)}
        outcome = сыграть(parse_cards("AH AD"), [0, 1], blind=_flint(), hand_info=info)
        assert outcome.exact is True

    def test_с_джокером_расчёт_честно_помечен_неточным(self) -> None:
        # Наш конвейер считает джокеров последним шагом (раздел 5 плана), а
        # в игре The Flint срабатывает до хендовых джокеров вроде "Joker" —
        # точно воспроизвести порядок нельзя, поэтому это честно unknown,
        # а не тихо неверное число.
        info = {HandType.PAIR: PokerHandInfo(level=1, chips=10, mult=2)}
        outcome = сыграть(parse_cards("AH AD"), [0, 1], ["j_joker"], blind=_flint(), hand_info=info)
        assert outcome.exact is False


class TestРетриггеры:
    def test_красная_печать_повторяет_карту(self) -> None:
        # (5 + 11 + 11) × 1
        assert сыграть([карта(seal=Seal.RED)], [0]).expected == 27

    def test_hack_повторяет_мелкие_карты(self) -> None:
        # (5 + 2 + 2) × 1
        assert сыграть(parse_cards("2H"), [0], ["j_hack"]).expected == 9

    def test_hack_не_трогает_старшие(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_hack"]).expected == 16

    def test_hanging_chad_повторяет_первую_дважды(self) -> None:
        # (5 + 11 × 3) × 1
        assert сыграть(parse_cards("AH KH"), [0, 1], ["j_hanging_chad"]).expected == 38

    def test_dusk_срабатывает_в_последней_руке(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_dusk"], hands_left=1).expected == 27

    def test_dusk_молчит_если_руки_остались(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_dusk"], hands_left=3).expected == 16

    def test_mime_повторяет_карты_в_руке(self) -> None:
        # Steel в руке срабатывает дважды: (5 + 11) × 1 × 1.5 × 1.5
        hand = [карта(), карта(Rank.KING, Suit.SPADES, enhancement=Enhancement.STEEL)]
        assert сыграть(hand, [0], ["j_mime"]).expected == 36

    def test_selzer_ретригерит_все_сыгранные(self) -> None:
        # Туз засчитан дважды: (5 + 11 + 11) × 1
        assert сыграть(parse_cards("AH"), [0], ["j_selzer"]).expected == 27

    def test_sock_and_buskin_ретригерит_картинки(self) -> None:
        # Король засчитан дважды: (5 + 10 + 10) × 1
        assert сыграть(parse_cards("KH"), [0], ["j_sock_and_buskin"]).expected == 25

    def test_sock_and_buskin_молчит_на_обычной_карте(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_sock_and_buskin"]).expected == 16


class TestДжокерыНаКарты:
    def test_масть_даёт_множитель(self) -> None:
        # Greedy: +3 за каждую бубну. Пара семёрок, бубна одна: (10 + 14) × (2 + 3)
        assert сыграть(parse_cards("7D 7H"), [0, 1], ["j_greedy_joker"]).expected == 120

    def test_scholar_на_тузах(self) -> None:
        # (10 + 22 + 40) × (2 + 8)
        assert сыграть(parse_cards("AH AD"), [0, 1], ["j_scholar"]).expected == 720

    def test_odd_todd_на_нечётных(self) -> None:
        # (10 + 22 + 62) × 2
        assert сыграть(parse_cards("AH AD"), [0, 1], ["j_odd_todd"]).expected == 188

    def test_even_steven_на_чётных(self) -> None:
        # (10 + 16) × (2 + 8)
        assert сыграть(parse_cards("8H 8D"), [0, 1], ["j_even_steven"]).expected == 260

    def test_photograph_только_на_первой_картинке(self) -> None:
        # (10 + 20) × (2 × 2) — умножение один раз, на первом короле
        assert сыграть(parse_cards("KH KD"), [0, 1], ["j_photograph"]).expected == 120

    def test_baron_считает_королей_в_руке(self) -> None:
        # Король остался в руке: (5 + 11) × (1 × 1.5)
        assert сыграть(parse_cards("AH KD"), [0], ["j_baron"]).expected == 24

    def test_arrowhead_на_пиках(self) -> None:
        # Пара семёрок, одна пиковая: (10 + 14 + 50) × 2
        assert сыграть(parse_cards("7S 7H"), [0, 1], ["j_arrowhead"]).expected == 148

    def test_onyx_agate_на_трефах(self) -> None:
        # Пара семёрок, одна трефовая: (10 + 14) × (2 + 7)
        assert сыграть(parse_cards("7C 7H"), [0, 1], ["j_onyx_agate"]).expected == 216

    def test_scary_face_на_картинках(self) -> None:
        # Пара королей, обе картинки: (10 + 20 + 60) × 2
        assert сыграть(parse_cards("KH KD"), [0, 1], ["j_scary_face"]).expected == 180

    def test_smiley_на_картинках(self) -> None:
        # Пара королей, обе картинки: (10 + 20) × (2 + 10)
        assert сыграть(parse_cards("KH KD"), [0, 1], ["j_smiley"]).expected == 360

    def test_walkie_talkie_на_четвёрке(self) -> None:
        # (5 + 4 + 10) × (1 + 4)
        assert сыграть(parse_cards("4H"), [0], ["j_walkie_talkie"]).expected == 95

    def test_walkie_talkie_молчит_на_чужом_ранге(self) -> None:
        assert сыграть(parse_cards("2H"), [0], ["j_walkie_talkie"]).expected == 7

    def test_triboulet_умножает_за_каждую_картинку(self) -> None:
        # Пара королей: (10 + 20) × 2 × 2 × 2
        assert сыграть(parse_cards("KH KD"), [0, 1], ["j_triboulet"]).expected == 240

    def test_shoot_the_moon_считает_дам_в_руке(self) -> None:
        # Дама осталась в руке: (5 + 11) × (1 + 13)
        assert сыграть(parse_cards("AH QD"), [0], ["j_shoot_the_moon"]).expected == 224

    def test_raised_fist_берёт_младшую_карту_в_руке(self) -> None:
        # Младшая в руке — двойка: (5 + 11) × (1 + 2 × 2)
        assert сыграть(parse_cards("AH 2D 5S"), [0], ["j_raised_fist"]).expected == 80

    def test_raised_fist_игнорирует_каменные(self) -> None:
        hand = [
            карта(Rank.ACE),
            карта(Rank.TWO, Suit.SPADES, enhancement=Enhancement.STONE),
            карта(Rank.FIVE, Suit.CLUBS),
        ]
        # Каменная двойка не в счёт — младшая среди обычных: пятёрка.
        assert сыграть(hand, [0], ["j_raised_fist"]).expected == (5 + 11) * (1 + 2 * 5)

    def test_raised_fist_молчит_без_карт_в_руке(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_raised_fist"]).expected == 16

    def test_blackboard_на_пиках_и_трефах(self) -> None:
        # (5 + 11) × (1 × 3)
        assert сыграть(parse_cards("AH 2S 3C"), [0], ["j_blackboard"]).expected == 48

    def test_blackboard_молчит_на_чужой_масти(self) -> None:
        assert сыграть(parse_cards("AH 2S 3H"), [0], ["j_blackboard"]).expected == 16

    def test_blackboard_срабатывает_на_пустой_руке(self) -> None:
        # Условие «все карты в руке — пики или трефы» выполняется на пустом множестве.
        assert сыграть(parse_cards("AH"), [0], ["j_blackboard"]).expected == 48

    def test_flower_pot_на_всех_мастях(self) -> None:
        # Четыре туза, по одному на масть — каре, все 4 масти представлены.
        outcome = сыграть(parse_cards("AH AD AC AS"), [0, 1, 2, 3], ["j_flower_pot"])
        assert outcome.expected == 2184

    def test_flower_pot_молчит_без_всех_мастей(self) -> None:
        outcome = сыграть(parse_cards("AH AD AC"), [0, 1, 2], ["j_flower_pot"])
        assert outcome.expected == 189

    def test_seeing_double_треф_и_другая_масть(self) -> None:
        # (10 + 22) × (2 × 2)
        assert сыграть(parse_cards("AC AH"), [0, 1], ["j_seeing_double"]).expected == 128

    def test_seeing_double_молчит_без_треф(self) -> None:
        assert сыграть(parse_cards("AH KH"), [0, 1], ["j_seeing_double"]).expected == 16

    def test_bloodstone_разброс(self) -> None:
        outcome = сыграть(parse_cards("AH"), [0], ["j_bloodstone"])
        assert outcome.minimum == 16
        assert outcome.maximum == 24
        assert outcome.expected == pytest.approx(20.0)

    def test_bloodstone_молчит_на_чужой_масти(self) -> None:
        outcome = сыграть(parse_cards("AC"), [0], ["j_bloodstone"])
        assert outcome.certain
        assert outcome.expected == 16


class TestУсловныеДжокеры:
    def test_jolly_на_паре(self) -> None:
        assert сыграть(parse_cards("AH AD"), [0, 1], ["j_jolly"]).expected == 320

    def test_jolly_молчит_без_пары(self) -> None:
        assert сыграть(parse_cards("AH KD"), [0, 1], ["j_jolly"]).expected == 16

    def test_sly_даёт_очки(self) -> None:
        # (10 + 22 + 50) × 2
        assert сыграть(parse_cards("AH AD"), [0, 1], ["j_sly"]).expected == 164

    def test_half_joker_на_коротких_руках(self) -> None:
        assert сыграть(parse_cards("AH AD"), [0, 1], ["j_half"]).expected == 704

    def test_half_joker_молчит_на_пяти_картах(self) -> None:
        outcome = сыграть(parse_cards("AH AD AC 2S 3D"), [0, 1, 2, 3, 4], ["j_half"])
        assert outcome.hand_type is HandType.THREE_OF_A_KIND
        assert outcome.expected == (30 + 33) * 3

    def test_duo_на_паре(self) -> None:
        # (10 + 22) × (2 × 2)
        assert сыграть(parse_cards("AH AD"), [0, 1], ["j_duo"]).expected == 128

    def test_duo_молчит_без_пары(self) -> None:
        assert сыграть(parse_cards("AH KD"), [0, 1], ["j_duo"]).expected == 16

    def test_trio_на_тройке(self) -> None:
        # (30 + 33) × (3 × 3)
        assert сыграть(parse_cards("AH AD AC"), [0, 1, 2], ["j_trio"]).expected == 567

    def test_family_на_каре(self) -> None:
        # (60 + 44) × (7 × 4)
        assert сыграть(parse_cards("AH AD AC AS"), [0, 1, 2, 3], ["j_family"]).expected == 2912

    def test_order_на_стрите(self) -> None:
        # 9-10-J-Q-K вразнобой по мастям: (30 + 49) × (4 × 3)
        outcome = сыграть(parse_cards("9H TC JD QS KH"), [0, 1, 2, 3, 4], ["j_order"])
        assert outcome.hand_type is HandType.STRAIGHT
        assert outcome.expected == 948

    def test_tribe_на_флеше(self) -> None:
        # Пять черв не подряд: (35 + 40) × (4 × 2)
        outcome = сыграть(parse_cards("AH KH TH 7H 2H"), [0, 1, 2, 3, 4], ["j_tribe"])
        assert outcome.hand_type is HandType.FLUSH
        assert outcome.expected == 600


class TestРедкостьДжокеров:
    """Целостность захардкоженной таблицы `_JOKER_RARITY` (150 джокеров,
    сверена по справочнику сообщества — см. комментарий рядом с таблицей).
    Один пропуск или опечатка здесь тихо испортит `Baseball Card`, поэтому
    проверяем структуру таблицы отдельно от самого джокера."""

    def test_накрывает_каждый_джокер_каталога_ровно_один_раз(self) -> None:
        assert set(_JOKER_RARITY) == set(JOKERS)

    def test_количество_по_редкостям_совпадает_с_официальным(self) -> None:
        counts: dict[str, int] = {}
        for rarity in _JOKER_RARITY.values():
            counts[rarity] = counts.get(rarity, 0) + 1
        assert counts == {"common": 61, "uncommon": 64, "rare": 20, "legendary": 5}


class TestBaseballCard:
    def test_умножает_за_каждого_uncommon_джокера(self) -> None:
        # j_rough_gem и j_cloud_9 — Uncommon без вклада в счёт (см.
        # TestДжокерыБезЭффектаНаСчёт), j_joker — Common, не считается.
        # (5 + 11) × ((1 × 1.5 × 1.5) + 4)
        outcome = сыграть(
            parse_cards("AH"), [0], ["j_baseball", "j_rough_gem", "j_cloud_9", "j_joker"]
        )
        assert outcome.expected == 100

    def test_молчит_без_uncommon_джокеров(self) -> None:
        база = сыграть(parse_cards("AH"), [0], ["j_joker"])
        с_baseball = сыграть(parse_cards("AH"), [0], ["j_baseball", "j_joker"])
        assert с_baseball.expected == база.expected

    def test_расчёт_остаётся_точным(self) -> None:
        info = {HandType.HIGH_CARD: PokerHandInfo(level=1, chips=5, mult=1)}
        outcome = сыграть(parse_cards("AH"), [0], ["j_baseball", "j_seeing_double"], hand_info=info)
        assert outcome.exact


class TestНакопителиИзТекстаЭффекта:
    """Джокеры, реальный эффект которых копится по истории, недоступной
    состоянию игры (прошлые сбросы, продажи, рероллы...). Число вместо
    этого читается готовым из `JokerCard.current_value` — мост вытаскивает
    его из текста эффекта живого мода. Без него (ручной ввод, парсинг не
    удался) расчёт честно помечается неточным, а не считается с нуля."""

    def test_chips_накопитель(self) -> None:
        # (5 + 11 + 8) × 1 — j_square: current_value уже готовое число фишек.
        outcome = сыграть(parse_cards("AH"), [0], ["j_square"], joker_values={"j_square": 8})
        assert outcome.expected == 24

    def test_mult_накопитель(self) -> None:
        # (5 + 11) × (1 + 12) — j_green_joker: current_value уже готовый мульт.
        outcome = сыграть(
            parse_cards("AH"), [0], ["j_green_joker"], joker_values={"j_green_joker": 12}
        )
        assert outcome.expected == 208

    def test_mult_накопитель_может_быть_отрицательным(self) -> None:
        # Больше сбросов, чем рук: (5 + 11) × (1 − 2) — при mult < 0 итог
        # не должен «уходить в минус бесконечность», игра просто считает как есть.
        outcome = сыграть(
            parse_cards("AH"), [0], ["j_green_joker"], joker_values={"j_green_joker": -2}
        )
        assert outcome.expected == -16

    def test_xmult_накопитель(self) -> None:
        # (5 + 11) × (1 × 2.5) — j_glass: current_value уже готовый Х-множитель.
        outcome = сыграть(parse_cards("AH"), [0], ["j_glass"], joker_values={"j_glass": 2.5})
        assert outcome.expected == 40

    def test_без_текущего_значения_расчёт_неточный(self) -> None:
        # Ручной ввод или не распознанный текст эффекта — current_value = None.
        outcome = сыграть(parse_cards("AH"), [0], ["j_square"])
        assert not outcome.exact
        assert any("j_square" in reason for reason in outcome.unknown)

    def test_без_текущего_значения_счёт_как_без_джокера(self) -> None:
        база = сыграть(parse_cards("AH"), [0])
        с_джокером = сыграть(parse_cards("AH"), [0], ["j_square"])
        assert с_джокером.expected == база.expected


class TestPopcornRamen:
    """У этих двух живое значение — не последнее число в тексте эффекта, а
    первое (`JokerCard.leading_value`), сверено с `card.lua`."""

    def test_popcorn_добавляет_текущий_множитель(self) -> None:
        state = GameState(hand=parse_cards("AH"), jokers=(JokerCard("j_popcorn", leading_value=8),))
        # (5 + 11) × (1 + 8)
        assert score_play(state, list(state.hand)).expected == 144

    def test_ramen_умножает_на_текущий_множитель(self) -> None:
        state = GameState(hand=parse_cards("AH"), jokers=(JokerCard("j_ramen", leading_value=1.5),))
        # (5 + 11) × (1 × 1.5)
        assert score_play(state, list(state.hand)).expected == 24

    def test_без_leading_value_расчёт_неточный(self) -> None:
        state = GameState(hand=parse_cards("AH"), jokers=(JokerCard("j_popcorn"),))
        assert not score_play(state, list(state.hand)).exact


class TestAncientIdol:
    """Текущая цель (масть/ранг) распознаётся словом в тексте эффекта
    (`JokerCard.target_suit`/`target_rank`), структурного поля под неё нет."""

    def test_ancient_умножает_только_карты_нужной_масти(self) -> None:
        state = GameState(
            hand=parse_cards("AH AD"),
            jokers=(JokerCard("j_ancient", target_suit=Suit.HEARTS),),
        )
        # (10 + 11 + 11) × (2 × 1.5) — из пары тузов только AH подходит по масти
        assert score_play(state, list(state.hand)).expected == 96

    def test_ancient_без_target_suit_расчёт_неточный(self) -> None:
        state = GameState(hand=parse_cards("AH"), jokers=(JokerCard("j_ancient"),))
        assert not score_play(state, list(state.hand)).exact

    def test_idol_срабатывает_только_на_нужном_ранге_и_масти(self) -> None:
        state = GameState(
            hand=parse_cards("KH KD"),
            jokers=(JokerCard("j_idol", target_suit=Suit.HEARTS, target_rank=Rank.KING),),
        )
        # (10 + 10 + 10) × (2 × 2) — из пары королей только KH подходит и по рангу, и по масти
        assert score_play(state, list(state.hand)).expected == 120

    def test_idol_без_цели_расчёт_неточный(self) -> None:
        state = GameState(hand=parse_cards("KH"), jokers=(JokerCard("j_idol"),))
        assert not score_play(state, list(state.hand)).exact


class TestLoyaltyCard:
    def test_срабатывает_когда_активно(self) -> None:
        state = GameState(
            hand=parse_cards("AH"), jokers=(JokerCard("j_loyalty_card", loyalty_active=True),)
        )
        # (5 + 11) × (1 × 4)
        assert score_play(state, list(state.hand)).expected == 64

    def test_молчит_когда_не_активно(self) -> None:
        state = GameState(
            hand=parse_cards("AH"), jokers=(JokerCard("j_loyalty_card", loyalty_active=False),)
        )
        assert score_play(state, list(state.hand)).expected == 16

    def test_без_состояния_расчёт_неточный(self) -> None:
        state = GameState(hand=parse_cards("AH"), jokers=(JokerCard("j_loyalty_card"),))
        assert not score_play(state, list(state.hand)).exact


class TestСостояниеРана:
    def test_bull_считает_деньги(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_bull"], money=10).expected == 36

    def test_banner_считает_сбросы(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_banner"], discards_left=2).expected == 76

    def test_abstract_считает_джокеров(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_abstract"]).expected == 64

    def test_supernova_без_данных_помечает_неточность(self) -> None:
        outcome = сыграть(parse_cards("AH"), [0], ["j_supernova"])
        assert any("Supernova" in reason for reason in outcome.unknown)

    def test_supernova_с_данными(self) -> None:
        info = {HandType.HIGH_CARD: PokerHandInfo(level=1, chips=5, mult=1, played=5)}
        outcome = сыграть(parse_cards("AH"), [0], ["j_supernova"], hand_info=info)
        assert outcome.expected == 16 * 6

    def test_mystic_summit_без_сбросов(self) -> None:
        outcome = сыграть(parse_cards("AH"), [0], ["j_mystic_summit"], discards_left=0)
        assert outcome.expected == 16 * 16

    def test_mystic_summit_молчит_если_сбросы_остались(self) -> None:
        outcome = сыграть(parse_cards("AH"), [0], ["j_mystic_summit"], discards_left=2)
        assert outcome.expected == 16

    def test_acrobat_на_последней_руке(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_acrobat"], hands_left=1).expected == 48

    def test_acrobat_молчит_если_руки_остались(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_acrobat"], hands_left=3).expected == 16

    def test_cavendish_x3_безусловно(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_cavendish"]).expected == 48

    def test_gros_michel_флэт_мульт(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_gros_michel"]).expected == 256

    def test_stuntman_флэт_фишки(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_stuntman"]).expected == 266

    def test_card_sharp_на_уже_сыгранной_руке(self) -> None:
        info = {HandType.HIGH_CARD: PokerHandInfo(level=1, chips=5, mult=1, played_this_round=1)}
        outcome = сыграть(parse_cards("AH"), [0], ["j_card_sharp"], hand_info=info)
        assert outcome.expected == 48

    def test_card_sharp_молчит_если_рука_ещё_не_игралась(self) -> None:
        info = {HandType.HIGH_CARD: PokerHandInfo(level=1, chips=5, mult=1, played_this_round=0)}
        outcome = сыграть(parse_cards("AH"), [0], ["j_card_sharp"], hand_info=info)
        assert outcome.expected == 16

    def test_card_sharp_без_данных_неточно(self) -> None:
        outcome = сыграть(parse_cards("AH"), [0], ["j_card_sharp"])
        assert any("Card Sharp" in reason for reason in outcome.unknown)

    def test_bootstraps_считает_пятёрки_денег(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_bootstraps"], money=12).expected == 80

    def test_bootstraps_молчит_без_денег(self) -> None:
        assert сыграть(parse_cards("AH"), [0], ["j_bootstraps"], money=0).expected == 16

    def test_blue_joker_считает_колоду(self) -> None:
        outcome = сыграть(parse_cards("AH"), [0], ["j_blue_joker"], deck=parse_cards("2H 3H 4H"))
        assert outcome.expected == 22

    def test_blue_joker_без_колоды_неточно(self) -> None:
        outcome = сыграть(parse_cards("AH"), [0], ["j_blue_joker"])
        assert any("Blue Joker" in reason for reason in outcome.unknown)

    def test_ice_cream_уменьшается_с_розыгрышами(self) -> None:
        outcome = сыграть(parse_cards("AH"), [0], ["j_ice_cream"], hands_played=3)
        assert outcome.expected == 101

    def test_ice_cream_без_розыгрышей(self) -> None:
        outcome = сыграть(parse_cards("AH"), [0], ["j_ice_cream"], hands_played=0)
        assert outcome.expected == 116

    def test_stencil_считает_пустые_слоты(self) -> None:
        # Один слот занят самим Stencil'ом, 4 свободны: X(1+4)
        outcome = сыграть(parse_cards("AH"), [0], ["j_stencil"], joker_slots=5)
        assert outcome.expected == 80

    def test_stencil_без_вместимости_неточно(self) -> None:
        outcome = сыграть(parse_cards("AH"), [0], ["j_stencil"])
        assert any("Stencil" in reason for reason in outcome.unknown)

    def test_swashbuckler_складывает_цену_продажи_других(self) -> None:
        from balatro_bot.core.scoring import score_play

        jokers = (
            JokerCard("j_swashbuckler"),
            JokerCard("j_burnt", sell_value=3),
            JokerCard("j_rough_gem", sell_value=5),
        )
        state = GameState(hand=parse_cards("AH"), jokers=jokers)
        outcome = score_play(state, [state.hand[0]])
        assert outcome.expected == 144

    def test_swashbuckler_без_цены_продажи_неточно(self) -> None:
        from balatro_bot.core.scoring import score_play

        jokers = (JokerCard("j_swashbuckler"), JokerCard("j_burnt"))
        state = GameState(hand=parse_cards("AH"), jokers=jokers)
        outcome = score_play(state, [state.hand[0]])
        assert any("Swashbuckler" in reason for reason in outcome.unknown)

    def test_steel_joker_считает_стальные_карты_в_полной_колоде(self) -> None:
        full_deck = (
            карта(Rank.TWO, Suit.SPADES, enhancement=Enhancement.STEEL),
            карта(Rank.THREE, Suit.SPADES, enhancement=Enhancement.STEEL),
            карта(Rank.FOUR, Suit.SPADES),
        )
        outcome = сыграть(parse_cards("AH"), [0], ["j_steel_joker"], full_deck=full_deck)
        assert outcome.expected == pytest.approx(16 * 1.4)

    def test_steel_joker_без_полной_колоды_неточно(self) -> None:
        outcome = сыграть(parse_cards("AH"), [0], ["j_steel_joker"])
        assert any("Steel Joker" in reason for reason in outcome.unknown)

    def test_stone_joker_считает_каменные_карты_в_полной_колоде(self) -> None:
        full_deck = (
            карта(Rank.TWO, Suit.SPADES, enhancement=Enhancement.STONE),
            карта(Rank.THREE, Suit.SPADES),
        )
        outcome = сыграть(parse_cards("AH"), [0], ["j_stone"], full_deck=full_deck)
        assert outcome.expected == (16 + 25) * 1

    def test_stone_joker_без_полной_колоды_неточно(self) -> None:
        outcome = сыграть(parse_cards("AH"), [0], ["j_stone"])
        assert any("Stone Joker" in reason for reason in outcome.unknown)

    def test_drivers_license_с_16_улучшенными(self) -> None:
        full_deck = tuple(
            карта(Rank.TWO, Suit.SPADES, enhancement=Enhancement.BONUS) for _ in range(16)
        )
        outcome = сыграть(parse_cards("AH"), [0], ["j_drivers_license"], full_deck=full_deck)
        assert outcome.expected == 48

    def test_drivers_license_молчит_меньше_16(self) -> None:
        full_deck = tuple(
            карта(Rank.TWO, Suit.SPADES, enhancement=Enhancement.BONUS) for _ in range(15)
        )
        outcome = сыграть(parse_cards("AH"), [0], ["j_drivers_license"], full_deck=full_deck)
        assert outcome.expected == 16

    def test_drivers_license_без_полной_колоды_неточно(self) -> None:
        outcome = сыграть(parse_cards("AH"), [0], ["j_drivers_license"])
        assert any("Driver's License" in reason for reason in outcome.unknown)

    def test_erosion_считает_недостающие_карты(self) -> None:
        # 50 из 52 стартовых — не хватает двух: +4×2 множителя
        full_deck = standard_deck()[:50]
        outcome = сыграть(
            parse_cards("AH"), [0], ["j_erosion"], full_deck=full_deck, deck_type="RED"
        )
        assert outcome.expected == 144

    def test_erosion_молчит_на_полной_колоде(self) -> None:
        outcome = сыграть(
            parse_cards("AH"), [0], ["j_erosion"], full_deck=standard_deck(), deck_type="RED"
        )
        assert outcome.expected == 16

    def test_erosion_без_типа_колоды_неточно(self) -> None:
        outcome = сыграть(parse_cards("AH"), [0], ["j_erosion"], full_deck=standard_deck())
        assert any("Erosion" in reason for reason in outcome.unknown)

    def test_erosion_без_полной_колоды_неточно(self) -> None:
        outcome = сыграть(parse_cards("AH"), [0], ["j_erosion"], deck_type="RED")
        assert any("Erosion" in reason for reason in outcome.unknown)


class TestКопирующие:
    def test_blueprint_копирует_покарточный_эффект(self) -> None:
        outcome = сыграть(parse_cards("7D 7H"), [0, 1], ["j_blueprint", "j_greedy_joker"])
        assert outcome.expected == 24 * 8

    def test_blueprint_без_соседа_ничего_не_делает(self) -> None:
        assert сыграть(parse_cards("AH AD"), [0, 1], ["j_blueprint"]).expected == 64

    def test_brainstorm_копирует_самого_левого(self) -> None:
        assert сыграть(parse_cards("AH AD"), [0, 1], ["j_joker", "j_brainstorm"]).expected == 320

    def test_brainstorm_слева_копировать_некого(self) -> None:
        assert сыграть(parse_cards("AH AD"), [0, 1], ["j_brainstorm", "j_joker"]).expected == 192

    def test_два_blueprint_подряд(self) -> None:
        # Каждый копирует соседа справа, эффект утраивается: 2 + 4 × 3
        outcome = сыграть(parse_cards("AH AD"), [0, 1], ["j_blueprint", "j_blueprint", "j_joker"])
        assert outcome.expected == 32 * 14


class TestПравилаРаспознавания:
    def test_four_fingers_даёт_флеш_из_четырёх(self) -> None:
        # Четыре червы вразнобой (не стрит) и одна трефа: с джокером это флеш.
        outcome = сыграть(parse_cards("AH KH QH 9H 2C"), [0, 1, 2, 3, 4], ["j_four_fingers"])
        assert outcome.hand_type is HandType.FLUSH
        assert len(outcome.scoring_cards) == 4

    def test_без_four_fingers_это_старшая_карта(self) -> None:
        карты = parse_cards("AH KH QH 9H 2C")
        assert сыграть(карты, [0, 1, 2, 3, 4]).hand_type is HandType.HIGH_CARD

    def test_smeared_склеивает_масти(self) -> None:
        outcome = сыграть(parse_cards("AH KD QH JD 9H"), [0, 1, 2, 3, 4], ["j_smeared"])
        assert outcome.hand_type is HandType.FLUSH

    def test_splash_считает_все_сыгранные_карты(self) -> None:
        # Без Splash тройка в счёт не идёт: пара только из тузов.
        # (10 + 22 + 2) × 2
        outcome = сыграть(parse_cards("AH AD 2C"), [0, 1, 2], ["j_splash"])
        assert outcome.hand_type is HandType.PAIR
        assert len(outcome.scoring_cards) == 3
        assert outcome.expected == 68

    def test_без_splash_лишняя_карта_не_считается(self) -> None:
        outcome = сыграть(parse_cards("AH AD 2C"), [0, 1, 2])
        assert len(outcome.scoring_cards) == 2
        assert outcome.expected == 64

    def test_pareidolia_делает_все_карты_картинками(self) -> None:
        # Двойка — не картинка, но Pareidolia это снимает: (5 + 2 + 30) × 1
        outcome = сыграть(parse_cards("2H"), [0], ["j_pareidolia", "j_scary_face"])
        assert outcome.expected == 37

    def test_без_pareidolia_обычная_карта_не_картинка(self) -> None:
        assert сыграть(parse_cards("2H"), [0], ["j_scary_face"]).expected == 7

    def test_chicot_отключает_дебафф(self) -> None:
        hand = [карта(debuffed=True)]
        assert сыграть(hand, [0], ["j_chicot"]).expected == 16

    def test_без_chicot_дебафф_действует(self) -> None:
        assert сыграть([карта(debuffed=True)], [0]).expected == 5

    def test_chicot_снимает_дебафф_и_у_карт_в_руке(self) -> None:
        # Дебаффнутый король в руке: с Chicot Baron всё равно даёт ×1.5.
        hand = [карта(), карта(Rank.KING, Suit.SPADES, debuffed=True)]
        assert сыграть(hand, [0], ["j_baron", "j_chicot"]).expected == 24

    def test_oops_удваивает_lucky(self) -> None:
        # Значение бонуса не меняется (+20 множителя), только вероятность: 0.4 вместо 0.2.
        outcome = сыграть([карта(enhancement=Enhancement.LUCKY)], [0], ["j_oops"])
        assert outcome.minimum == 16
        assert outcome.maximum == 336
        assert outcome.expected == pytest.approx(0.6 * 16 + 0.4 * 336)

    def test_oops_доводит_bloodstone_до_гарантии(self) -> None:
        # 1 к 2 удвоенный — это уже гарантия, разброса не остаётся.
        outcome = сыграть(parse_cards("AH"), [0], ["j_bloodstone", "j_oops"])
        assert outcome.certain
        assert outcome.expected == 24

    def test_без_oops_bloodstone_как_обычно(self) -> None:
        outcome = сыграть(parse_cards("AH"), [0], ["j_bloodstone"])
        assert not outcome.certain
        assert outcome.maximum == 24


class TestСлучайность:
    def test_lucky_даёт_разброс(self) -> None:
        outcome = сыграть([карта(enhancement=Enhancement.LUCKY)], [0])
        assert not outcome.certain
        assert outcome.minimum == 16
        assert outcome.maximum == 16 * 21

    def test_lucky_матожидание(self) -> None:
        # 0.8 × 16 + 0.2 × 336
        outcome = сыграть([карта(enhancement=Enhancement.LUCKY)], [0])
        assert outcome.expected == pytest.approx(80.0)

    def test_misprint_перебирает_все_исходы(self) -> None:
        outcome = сыграть(parse_cards("AH AD"), [0, 1], ["j_misprint"])
        assert outcome.minimum == 64
        assert outcome.maximum == 800
        assert outcome.expected == pytest.approx(32 * 13.5)

    def test_детерминированная_рука_без_разброса(self) -> None:
        assert сыграть(parse_cards("AH AD"), [0, 1]).certain


class TestЧестность:
    def test_нереализованный_джокер_помечает_неточность(self) -> None:
        outcome = сыграть(parse_cards("AH AD"), [0, 1], ["j_hiker"])
        assert not outcome.exact
        assert any("j_hiker" in reason for reason in outcome.unknown)

    def test_провизорные_таблицы_помечают_неточность(self) -> None:
        outcome = сыграть(parse_cards("AH AD"), [0, 1])
        assert not outcome.exact
        assert any("провизорн" in reason for reason in outcome.unknown)

    def test_с_данными_игры_расчёт_точен(self) -> None:
        info = {HandType.PAIR: PokerHandInfo(level=1, chips=10, mult=2)}
        outcome = сыграть(parse_cards("AH AD"), [0, 1], ["j_joker"], hand_info=info)
        assert outcome.exact
        assert outcome.unknown == ()


#: Известные джокеры, чей эффект заведомо не трогает chips/mult розыгрыша —
#: деньги, расходники, размер руки/сбросов (уже отражённые в состоянии) или
#: события после подсчёта. Список не исчерпывающий, это выборка по одной
#: из каждой категории в `implementations.py`.
_NO_SCORE_EFFECT_JOKERS = [
    "j_burnt",
    "j_rough_gem",
    "j_business",
    "j_reserved_parking",
    "j_ticket",
    "j_cloud_9",
    "j_golden",
    "j_juggler",
    "j_burglar",
    "j_certificate",
    "j_astronomer",
    "j_mr_bones",
    "j_midas_mask",
    "j_space",
    "j_8_ball",
]


class TestДжокерыБезЭффектаНаСчёт:
    """Известные джокеры, чей эффект заведомо не трогает chips/mult розыгрыша.

    Не «нереализовано»: деньги и прокачка уровня руки не входят в счёт этого
    хода, поэтому молчаливый эффект — честный итог, а не догадка.
    """

    @pytest.mark.parametrize("joker", _NO_SCORE_EFFECT_JOKERS)
    def test_не_меняет_счёт(self, joker: str) -> None:
        info = {HandType.PAIR: PokerHandInfo(level=1, chips=10, mult=2)}
        база = сыграть(parse_cards("AH AD"), [0, 1], hand_info=info)
        с_джокером = сыграть(parse_cards("AH AD"), [0, 1], [joker], hand_info=info)
        assert с_джокером.expected == база.expected

    @pytest.mark.parametrize("joker", _NO_SCORE_EFFECT_JOKERS)
    def test_известен_расчёт_остаётся_точным(self, joker: str) -> None:
        info = {HandType.PAIR: PokerHandInfo(level=1, chips=10, mult=2)}
        outcome = сыграть(parse_cards("AH AD"), [0, 1], [joker], hand_info=info)
        assert outcome.exact
        assert outcome.unknown == ()


class TestРегрессии:
    """Дефекты, которые уже случались. Пусть не возвращаются."""

    def test_копирующие_джокеры_не_зацикливаются(self) -> None:
        # Blueprint копирует соседа справа, Brainstorm — самого левого.
        # Поставленные рядом, они копировали друг друга до переполнения стека.
        outcome = сыграть(parse_cards("AH AD"), [0, 1], ["j_blueprint", "j_brainstorm"])
        assert outcome.expected == 64

    def test_цикл_не_ломает_остальных_джокеров(self) -> None:
        # Обрыв цикла не должен глушить джокера, стоящего рядом.
        outcome = сыграть(parse_cards("AH AD"), [0, 1], ["j_blueprint", "j_brainstorm", "j_joker"])
        assert outcome.expected > 64

    def test_причина_неточности_не_дублируется(self) -> None:
        outcome = сыграть(parse_cards("AH AD"), [0, 1], ["j_hiker"])
        про_джокера = [reason for reason in outcome.unknown if "hiker" in reason]
        assert len(про_джокера) == 1

    def test_детерминированная_рука_считается_один_раз(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Раньше конвейер прогонялся дважды: сначала на разведку случайностей,
        # потом набело. Для руки без случайностей это была двойная работа.
        import balatro_bot.core.scoring as модуль

        прогоны = 0
        исходный = модуль._run_once

        def счётчик(*args: Any, **kwargs: Any) -> Any:
            nonlocal прогоны
            прогоны += 1
            return исходный(*args, **kwargs)

        monkeypatch.setattr(модуль, "_run_once", счётчик)
        сыграть(parse_cards("AH AD"), [0, 1])

        assert прогоны == 1

    def test_чужие_карты_отвергаются(self) -> None:
        # Оставшиеся в руке ищутся по тождеству объектов. Карта «со стороны»
        # считалась и сыгранной, и оставшейся: Steel молча давал ×1.5 лишний раз.
        from balatro_bot.core.scoring import score_play

        steel = карта(enhancement=Enhancement.STEEL)
        state = GameState(hand=(steel, *parse_cards("AD KH")))
        двойник = карта(enhancement=Enhancement.STEEL)

        with pytest.raises(ValueError, match="не из руки"):
            score_play(state, [двойник, state.hand[1]])

    def test_свои_карты_проходят(self) -> None:
        from balatro_bot.core.scoring import score_play

        steel = карта(enhancement=Enhancement.STEEL)
        state = GameState(hand=(steel, *parse_cards("AD KH")))
        # Steel сыгран, значит в руке его нет и множителя он не даёт.
        assert score_play(state, list(state.hand[:2])).expected == 64

    def test_издание_на_самом_джокере_учитывается(self) -> None:
        # mod_bridge парсил edition карты-джокера, но подсчёт его нигде не
        # читал: Foil/Holographic/Polychrome на самом джокере молча пропадали,
        # даже когда джокер честно помечал расчёт точным. Найдено вживую:
        # у "8 Ball" с Foil-изданием пропадали +50 очков каждый розыгрыш.
        state = GameState(
            hand=parse_cards("AH"),
            jokers=(JokerCard("j_8_ball", edition=Edition.FOIL),),
        )
        # (5 + 11 + 50) × 1 — сам джокер эффекта на счёт не даёт, издание даёт.
        assert score_play(state, list(state.hand)).expected == 66
