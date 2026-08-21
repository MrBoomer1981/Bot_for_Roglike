"""Тесты форматирования вывода (`balatro_bot/ui/render.py`)."""

from __future__ import annotations

import pytest

from balatro_bot.adapters.manual import build_state
from balatro_bot.core.cards import Card, Edition, Enhancement, Rank, Seal, Suit, parse_cards
from balatro_bot.solver.discard import DiscardOutcome
from balatro_bot.solver.play import advise
from balatro_bot.ui.render import format_card, render_single_discard_ranking


class TestРегрессииВыводе:
    """Мелочи, на которых вывод уже ломался."""

    def test_steel_и_stone_различаются(self) -> None:
        # Обе начинаются на «s», и раньше обе печатались как (S). Путать их
        # нельзя: одно работает в руке, другое при розыгрыше.
        steel = format_card(Card(Rank.ACE, Suit.HEARTS, Enhancement.STEEL))
        stone = format_card(Card(Rank.ACE, Suit.HEARTS, Enhancement.STONE))
        assert steel != stone


class TestИзданияИПечатиВВыводе:
    """Раньше `format_card` показывал только улучшение — Edition и Seal были
    не видны глазами, хотя движок их уже считал (см. регрессию про издание
    джокера в `test_scoring.py`)."""

    def test_издание_видно_в_записи_карты(self) -> None:
        card = Card(Rank.ACE, Suit.HEARTS, edition=Edition.FOIL)
        assert format_card(card) == "AH(F)"

    def test_улучшение_и_издание_в_одних_скобках(self) -> None:
        card = Card(Rank.ACE, Suit.HEARTS, Enhancement.BONUS, Edition.FOIL)
        assert format_card(card) == "AH(BF)"

    def test_печать_видна_отдельным_значком(self) -> None:
        card = Card(Rank.ACE, Suit.HEARTS, seal=Seal.RED)
        assert format_card(card) == "AH!R"

    def test_обычная_карта_без_пометок(self) -> None:
        assert format_card(Card(Rank.ACE, Suit.HEARTS)) == "AH"


class TestРанжированиеСброса:
    def test_пустой_список_ничего_не_печатает(self, capsys: pytest.CaptureFixture[str]) -> None:
        state = build_state("AH KH QH JH 9H")
        render_single_discard_ranking((), advise(state).best)
        assert capsys.readouterr().out == ""

    def test_показывает_карту_и_отметку_выгоднее(self, capsys: pytest.CaptureFixture[str]) -> None:
        state = build_state("AH KH QH JH 9H")
        play_now = advise(state).best
        выгодный = DiscardOutcome(
            discarded=parse_cards("2S"),
            kept=state.hand,
            expected=play_now.score + 100,
            exact=True,
            draws_considered=10,
        )
        render_single_discard_ranking((выгодный,), play_now)
        out = capsys.readouterr().out
        assert "2S" in out
        assert "выгоднее, чем сыграть сейчас" in out

    def test_приближённая_колода_помечена(self, capsys: pytest.CaptureFixture[str]) -> None:
        state = build_state("AH KH QH JH 9H")
        play_now = advise(state).best
        неточный = DiscardOutcome(
            discarded=parse_cards("2S"),
            kept=state.hand,
            expected=play_now.score - 10,
            exact=False,
            draws_considered=10,
        )
        render_single_discard_ranking((неточный,), play_now)
        assert "колода приближена" in capsys.readouterr().out
