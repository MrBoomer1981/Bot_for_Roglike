"""Тесты выбора хода."""

from __future__ import annotations

import pytest

from balatro_bot.core.cards import Card, Enhancement, Rank, Suit, parse_cards
from balatro_bot.core.hands import HandType
from balatro_bot.core.scoring import score_play
from balatro_bot.core.state import BlindInfo, GameState, JokerCard
from balatro_bot.solver.play import Candidate, advise, rank_plays


def состояние(hand: str, *jokers: str, required: int | None = None, **kwargs: object) -> GameState:
    return GameState(
        hand=parse_cards(hand),
        jokers=tuple(JokerCard(key) for key in jokers),
        blind=BlindInfo("BIG", "Big Blind", "", required) if required is not None else None,
        **kwargs,  # type: ignore[arg-type]
    )


class TestПеребор:
    def test_из_восьми_карт_218_вариантов(self) -> None:
        # Сумма сочетаний по 1..5 из 8 карт.
        assert len(rank_plays(состояние("AH KH QH JH 9H 7C 7D 2S"))) == 218

    def test_из_четырёх_карт_пятнадцать(self) -> None:
        assert len(rank_plays(состояние("AH KH QH JH"))) == 15

    def test_отсортировано_по_убыванию(self) -> None:
        плейс = rank_plays(состояние("AH KH QH JH 9H 7C 7D 2S"))
        оценки = [item.score for item in плейс]
        assert оценки == sorted(оценки, reverse=True)

    def test_ограничение_количества(self) -> None:
        assert len(rank_plays(состояние("AH KH QH JH 9H 7C 7D 2S"), limit=5)) == 5

    def test_лучший_вариант_флеш(self) -> None:
        лучший = rank_plays(состояние("AH KH QH JH 9H 7C 7D 2S"))[0]
        assert лучший.outcome.hand_type is HandType.FLUSH

    def test_при_равном_счёте_короче_лучше(self) -> None:
        плейс = rank_plays(состояние("AH AD 2C 3D 4S"))
        лучшие = [item for item in плейс if item.score == плейс[0].score]
        assert len(лучшие[0].cards) == min(len(item.cards) for item in лучшие)


class TestРекомендация:
    def test_лучший_это_первый(self) -> None:
        совет = advise(состояние("AH KH QH JH 9H 7C 7D 2S"))
        assert совет.best is совет.candidates[0]

    def test_экономный_вариант_тратит_меньше_карт(self) -> None:
        # Тройка восьмёрок даёт 162, пара — 52. Порога в 50 хватает паре,
        # и она сохраняет колоду.
        совет = advise(состояние("8H 8D 8C 2S 3D", required=50))
        assert совет.best.outcome.hand_type is HandType.THREE_OF_A_KIND
        assert len(совет.best.cards) == 3
        экономный = совет.cheapest_sufficient
        assert экономный is not None
        assert len(экономный.cards) == 2

    def test_если_не_хватает_экономного_нет(self) -> None:
        совет = advise(состояние("2H 3D 4C 5S 7D", required=100_000))
        assert совет.cheapest_sufficient is None
        assert not совет.can_clear_now

    def test_учитывается_уже_набранное(self) -> None:
        без_набранного = advise(состояние("8H 8D 8C 2S 3D", required=200))
        с_набранным = advise(состояние("8H 8D 8C 2S 3D", required=200, chips_scored=150))
        assert без_набранного.cheapest_sufficient is None
        assert с_набранным.cheapest_sufficient is not None

    def test_без_блайнда_порога_нет(self) -> None:
        совет = advise(состояние("AH KH QH JH 9H"))
        assert совет.required is None
        assert совет.cheapest_sufficient is None

    def test_пустая_рука_это_ошибка(self) -> None:
        with pytest.raises(ValueError, match="нет карт"):
            advise(GameState())


class TestОсторожностьСоСлучайностью:
    def test_порог_считается_по_худшему_исходу(self) -> None:
        # Lucky-карта в среднем даёт 80, но может дать и 16. Советовать её
        # как «хватает» нельзя: проигрыш означает конец рана.
        карта = Card(Rank.ACE, Suit.HEARTS, Enhancement.LUCKY)
        state = GameState(hand=(карта,))
        outcome = score_play(state, [карта])
        кандидат = Candidate((карта,), outcome)

        assert outcome.expected == pytest.approx(80.0)
        assert not кандидат.beats(50)
        assert кандидат.beats(16)


class TestЧестность:
    def test_нереализованный_джокер_делает_совет_неточным(self) -> None:
        совет = advise(состояние("AH KH QH JH 9H", "j_cavendish"))
        assert not совет.exact

    def test_описание_читаемо(self) -> None:
        совет = advise(состояние("AH KH QH JH 9H"))
        текст = совет.best.describe()
        assert "flush" in текст
        assert "AH" in текст
