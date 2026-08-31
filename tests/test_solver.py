"""Тесты выбора хода."""

from __future__ import annotations

import pytest

from balatro_bot.core.cards import Card, Enhancement, Rank, Suit, parse_cards
from balatro_bot.core.hands import HandType
from balatro_bot.core.scoring import score_play
from balatro_bot.core.state import BlindInfo, GameState, JokerCard, PokerHandInfo
from balatro_bot.solver.play import Candidate, advise, rank_joker_orders, rank_plays


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


def _boss_state(
    hand: str, boss_name: str, hand_info: dict[HandType, PokerHandInfo] | None = None
) -> GameState:
    return GameState(
        hand=parse_cards(hand),
        blind=BlindInfo("BOSS", boss_name, "", 300),
        hand_info=hand_info or {},
    )


class TestЛегальностьПодБоссом:
    """Три босса из `core/bosses.py` (`BossEffect.restricts_legal_plays`) бьют по
    составу конкретного розыгрыша — `rank_plays` обязан отфильтровать нелегальные
    варианты до того, как они попадут в ранжированный список (допущение №10 в
    PLAN.md)."""

    def test_psychic_отсекает_розыгрыш_короче_пяти_карт(self) -> None:
        плейс = rank_plays(_boss_state("AH KH QH JH 9H 7C 7D 2S", "The Psychic"))
        assert плейс  # C(8, 5) = 56 вариантов размера ровно 5
        assert all(len(item.cards) == 5 for item in плейс)

    def test_psychic_без_легальных_вариантов_честно_отступает(self) -> None:
        # В руке всего 4 карты — под Psychic (нужно ≥5) легальных вариантов
        # нет вовсе; фильтр отступает и отдаёт нефильтрованный список, а не
        # пустоту.
        плейс = rank_plays(_boss_state("AH KH QH JH", "The Psychic"))
        assert len(плейс) == 15  # 2^4 - 1 подмножеств
        assert any(len(item.cards) < 5 for item in плейс)

    def test_mouth_ничего_не_сыграно_легален_любой_тип(self) -> None:
        плейс = rank_plays(_boss_state("AH AD KH KD QC", "The Mouth"))
        assert len(плейс) == 31  # 2^5 - 1, фильтр ничего не убрал

    def test_mouth_запирает_на_уже_сыгранный_тип(self) -> None:
        info = {HandType.PAIR: PokerHandInfo(level=1, chips=10, mult=2, played_this_round=1)}
        плейс = rank_plays(_boss_state("AH AD KH KD QC", "The Mouth", info))
        assert плейс
        assert all(item.outcome.hand_type is HandType.PAIR for item in плейс)

    def test_eye_запрещает_повтор_уже_сыгранного_типа(self) -> None:
        info = {HandType.PAIR: PokerHandInfo(level=1, chips=10, mult=2, played_this_round=1)}
        плейс = rank_plays(_boss_state("AH AD KH KD QC", "The Eye", info))
        assert плейс
        assert not any(item.outcome.hand_type is HandType.PAIR for item in плейс)
        assert any(item.outcome.hand_type is HandType.TWO_PAIR for item in плейс)

    def test_другой_босс_не_фильтрует(self) -> None:
        плейс = rank_plays(_boss_state("AH KH QH JH", "The Wall"))
        assert len(плейс) == 15

    def test_без_блайнда_не_фильтрует(self) -> None:
        assert len(rank_plays(состояние("AH KH QH JH"))) == 15

    def test_список_боссов_совпадает_с_каталогом(self) -> None:
        # Тройка захардкожена и в solver/play.py, и здесь — если каталог
        # core/bosses.py когда-нибудь поменяется, этот тест не даст
        # разойтись молча.
        from balatro_bot.core.bosses import BOSSES
        from balatro_bot.solver.play import _THE_EYE, _THE_MOUTH, _THE_PSYCHIC

        restricting = {effect.name for effect in BOSSES.values() if effect.restricts_legal_plays}
        assert restricting == {_THE_MOUTH, _THE_EYE, _THE_PSYCHIC}


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


class TestПорядокДжокеров:
    def test_другой_порядок_меняет_счёт(self) -> None:
        # Blueprint копирует соседа справа: если Joker (+4 мульта) справа —
        # эффект копируется повторно, если слева — Blueprint копировать некого.
        blueprint_слева = advise(состояние("AH KH", "j_blueprint", "j_joker"))
        blueprint_справа = advise(состояние("AH KH", "j_joker", "j_blueprint"))
        assert blueprint_слева.best.score > blueprint_справа.best.score

    def test_находит_лучший_порядок(self) -> None:
        state = состояние("AH KH", "j_joker", "j_blueprint")
        result = rank_joker_orders(state)
        assert result is not None

        order, лучший_совет = result
        assert order == (JokerCard("j_blueprint"), JokerCard("j_joker"))
        assert лучший_совет.best.score > advise(state).best.score

    def test_текущий_порядок_уже_лучший_не_меняется(self) -> None:
        state = состояние("AH KH", "j_blueprint", "j_joker")
        result = rank_joker_orders(state)
        assert result is not None
        assert result[0] == state.jokers

    def test_слишком_много_джокеров_не_перебирается(self) -> None:
        state = состояние("AH", *["j_joker"] * 7)
        assert rank_joker_orders(state) is None

    def test_вентиль_чисто_аддитивный_стек_не_перебирается(self) -> None:
        # j_joker/j_abstract/j_banner — только прибавки, порядок не влияет:
        # дешёвый вентиль (реверс == исходный) возвращает исходный порядок
        # без суррогатного перебора (улучшение F1).
        state = состояние("AH KH QH JH 9H", "j_joker", "j_abstract", "j_banner")
        order, _ = rank_joker_orders(state)  # type: ignore[misc]
        assert order == state.jokers

    def test_base_advice_переиспользуется_и_возвращается(self) -> None:
        state = состояние("AH KH QH JH 9H", "j_joker", "j_abstract", "j_banner")
        предрасчёт = advise(state)
        order, совет = rank_joker_orders(state, base_advice=предрасчёт)  # type: ignore[misc]
        assert order == state.jokers
        assert совет is предрасчёт  # тот же объект, не пересчитан

    def test_суррогат_совпадает_с_честным_перебором(self) -> None:
        # Стек с копирующим и xmult — порядок влияет, вентиль пропускается,
        # идёт суррогатный перебор. Достигнутый им счёт равен честному.
        from dataclasses import replace
        from itertools import permutations

        state = состояние(
            "KS KH KD QC QH 9S 4D 2C", "j_blueprint", "j_baseball", "j_bull", "j_joker"
        )
        order, _ = rank_joker_orders(state, limit=1)  # type: ignore[misc]
        суррогат = advise(replace(state, jokers=order), limit=1).best.score
        честный = max(
            advise(replace(state, jokers=p), limit=1).best.score for p in permutations(state.jokers)
        )
        assert суррогат == pytest.approx(честный, rel=1e-6)


class TestЧестность:
    def test_нереализованный_джокер_делает_совет_неточным(self) -> None:
        совет = advise(состояние("AH KH QH JH 9H", "j_cavendish"))
        assert not совет.exact

    def test_описание_читаемо(self) -> None:
        совет = advise(состояние("AH KH QH JH 9H"))
        текст = совет.best.describe()
        assert "flush" in текст
        assert "AH" in текст
