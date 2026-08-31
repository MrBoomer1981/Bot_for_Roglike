"""Тесты форматирования вывода (`balatro_bot/ui/render.py`)."""

from __future__ import annotations

import pytest

from balatro_bot.adapters.manual import build_state
from balatro_bot.core.cards import Card, Edition, Enhancement, Rank, Seal, Suit, parse_cards
from balatro_bot.core.state import ShopItem
from balatro_bot.core.tags import TAGS
from balatro_bot.solver.actions import ActionOption
from balatro_bot.solver.discard import DiscardOutcome
from balatro_bot.solver.play import advise
from balatro_bot.solver.shop import JokerOffer, PackPurchaseOffer, RerollOutlook, ShopAdvice
from balatro_bot.solver.skip import SkipAdvice
from balatro_bot.solver.vouchers import VoucherOffer
from balatro_bot.ui.render import (
    format_card,
    render_discard_ranking,
    render_shop_advice,
    render_skip_advice,
    render_top_actions,
)


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
        render_discard_ranking((), advise(state).best)
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
        render_discard_ranking((выгодный,), play_now)
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
        render_discard_ranking((неточный,), play_now)
        assert "колода приближена" in capsys.readouterr().out


class TestЕдиныйСписокДействий:
    """`ActionOption` собираются вручную — рендер не должен зависеть от того,
    чем в реальности заканчивает решатель на конкретной руке."""

    def test_розыгрыш_и_сброс_в_одном_списке(self, capsys: pytest.CaptureFixture[str]) -> None:
        state = build_state("AH KH QH 9H 2C 7D 3S 4S")
        advice = advise(state)
        actions = (
            ActionOption(
                kind="play", cards=parse_cards("AH KH"), score=100, label="pair", exact=True
            ),
            ActionOption(
                kind="discard",
                cards=parse_cards("2C 7D"),
                score=90,
                label="флеш черви",
                exact=False,
                success_probability=0.61,
                exact_deck=True,
            ),
        )
        render_top_actions(advice, actions)
        out = capsys.readouterr().out
        assert "сыграть" in out
        assert "сбросить" in out

    def test_вероятность_показана_процентом(self, capsys: pytest.CaptureFixture[str]) -> None:
        state = build_state("AH KH QH 9H 2C 7D 3S 4S")
        advice = advise(state)
        actions = (
            ActionOption(
                kind="discard",
                cards=parse_cards("2C 7D"),
                score=90,
                label="флеш черви",
                exact=False,
                success_probability=0.6142938173567782,
                exact_deck=True,
            ),
        )
        render_top_actions(advice, actions)
        out = capsys.readouterr().out
        assert "шанс 61%" in out

    def test_пустой_список_не_падает(self, capsys: pytest.CaptureFixture[str]) -> None:
        state = build_state("AH KH QH 9H 2C 7D 3S 4S")
        advice = advise(state)
        render_top_actions(advice, ())
        assert "вариантов нет" in capsys.readouterr().out

    def test_неточные_сбросы_отмечены(self, capsys: pytest.CaptureFixture[str]) -> None:
        state = build_state("AH KH QH 9H 2C 7D 3S 4S")
        advice = advise(state)
        actions = (
            ActionOption(
                kind="discard",
                cards=parse_cards("2C 7D"),
                score=90,
                label="флеш черви",
                exact=False,
                success_probability=0.61,
                exact_deck=False,
            ),
        )
        render_top_actions(advice, actions)
        out = capsys.readouterr().out
        assert "числа НЕТОЧНЫЕ" in out
        assert "оценка по выборке" in out
        assert "колода приближена" in out

    def test_розыгрыш_с_гарантией_помечен_хватает(self, capsys: pytest.CaptureFixture[str]) -> None:
        state = build_state("AH KH QH 9H 2C 7D 3S 4S", blind=100)
        advice = advise(state)
        actions = (
            ActionOption(
                kind="play",
                cards=parse_cards("AH KH"),
                score=150,
                label="pair",
                exact=True,
                minimum=150,
            ),
        )
        render_top_actions(advice, actions)
        assert "хватает" in capsys.readouterr().out

    def test_среднее_у_сброса_не_считается_гарантией(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # У сброса нет `minimum` (см. `ActionOption.minimum`) — даже если
        # `score` перекрывает блайнд, «хватает» здесь означать нечего:
        # это среднее по доборам, а не гарантия.
        state = build_state("AH KH QH 9H 2C 7D 3S 4S", blind=100)
        advice = advise(state)
        actions = (
            ActionOption(
                kind="discard",
                cards=parse_cards("2C 7D"),
                score=150,
                label="флеш черви",
                exact=False,
                success_probability=0.5,
                exact_deck=True,
            ),
        )
        render_top_actions(advice, actions)
        assert "хватает" not in capsys.readouterr().out


class TestРендерСоветаПоСкипу:
    def test_денежный_тег_показывает_сумму(self, capsys: pytest.CaptureFixture[str]) -> None:
        advice = SkipAdvice(
            blind_kind="BIG",
            required_score=450,
            next_blind_kind="BOSS",
            next_required_score=600,
            requirement_ratio=600 / 450,
            play_reward_min=4,
            play_reward_hint="+ $1 за руку",
            tag_name="Investment Tag",
            tag_effect="После победы над Боссом даёт $25",
            tag=TAGS["tag_investment"],
            tag_dollars=25.0,
            tag_dollars_note="после победы над боссом",
        )
        render_skip_advice(advice)
        out = capsys.readouterr().out
        assert "Big Blind" in out
        assert "450" in out
        assert "Boss Blind" in out
        assert "$25" in out
        assert "Investment Tag" in out

    def test_тег_без_точной_суммы_помечен_не_оценено(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        advice = SkipAdvice(
            blind_kind="SMALL",
            required_score=300,
            next_blind_kind="BIG",
            next_required_score=450,
            requirement_ratio=1.5,
            play_reward_min=3,
            play_reward_hint="+ $1 за руку",
            tag_name="Handy Tag",
            tag_effect="...",
            tag=TAGS["tag_handy"],
            tag_dollars=None,
            tag_dollars_note="формула требует счётчик уровня рана",
        )
        render_skip_advice(advice)
        assert "не оценено" in capsys.readouterr().out

    def test_неопознанный_тег_помечен_честно(self, capsys: pytest.CaptureFixture[str]) -> None:
        advice = SkipAdvice(
            blind_kind="SMALL",
            required_score=300,
            next_blind_kind="BIG",
            next_required_score=450,
            requirement_ratio=1.5,
            play_reward_min=3,
            play_reward_hint="+ $1 за руку",
            tag_name="Совершенно Новый Tag",
            tag_effect="...",
            tag=None,
            tag_dollars=None,
            tag_dollars_note="",
        )
        render_skip_advice(advice)
        out = capsys.readouterr().out
        assert "не опознан" in out


class TestРендерСоветаПоМагазину:
    def test_оценённый_джокер_показывает_прирост(self, capsys: pytest.CaptureFixture[str]) -> None:
        advice = ShopAdvice(
            jokers=(
                JokerOffer(
                    item=ShopItem("j_joker", "Joker", "JOKER", 3, "+4 Mult"),
                    affordable=True,
                    has_slot=True,
                    known=True,
                    expected_uplift=12.5,
                    exact_deck=False,
                    samples=12,
                    interest_lost=0,
                    rental_cost_per_round=0,
                    perishable_rounds=None,
                    eternal=False,
                ),
            ),
            vouchers=(),
            packs=(),
            money=10,
            reroll=RerollOutlook(
                cost=5,
                affordable=True,
                expected_best_uplift=None,
                slots=2,
                samples=0,
                exact_deck=False,
            ),
        )
        render_shop_advice(advice)
        out = capsys.readouterr().out
        assert "Joker" in out
        assert "$3" in out
        assert "прирост" in out
        assert "колода приближена" in out
        assert "цена рерола: $5" in out

    def test_неизвестный_джокер_помечен(self, capsys: pytest.CaptureFixture[str]) -> None:
        advice = ShopAdvice(
            jokers=(
                JokerOffer(
                    item=ShopItem("j_новый", "???", "JOKER", 5, ""),
                    affordable=True,
                    has_slot=True,
                    known=False,
                    expected_uplift=None,
                    exact_deck=False,
                    samples=0,
                    interest_lost=0,
                    rental_cost_per_round=0,
                    perishable_rounds=None,
                    eternal=False,
                ),
            ),
            vouchers=(),
            packs=(),
            money=10,
            reroll=None,
        )
        render_shop_advice(advice)
        out = capsys.readouterr().out
        assert "эффект не реализован" in out
        assert "цена рерола" not in out

    def test_нехватка_денег_и_слота_отмечены(self, capsys: pytest.CaptureFixture[str]) -> None:
        advice = ShopAdvice(
            jokers=(
                JokerOffer(
                    item=ShopItem("j_joker", "Joker", "JOKER", 99, "+4 Mult"),
                    affordable=False,
                    has_slot=False,
                    known=True,
                    expected_uplift=4.0,
                    exact_deck=True,
                    samples=12,
                    interest_lost=1,
                    rental_cost_per_round=0,
                    perishable_rounds=None,
                    eternal=False,
                ),
            ),
            vouchers=(),
            packs=(),
            money=1,
            reroll=None,
        )
        render_shop_advice(advice)
        out = capsys.readouterr().out
        assert "не хватает денег" in out
        assert "нет слота" in out
        assert "−$1 процентов в конце раунда" in out

    def test_стикеры_ставок_отмечены(self, capsys: pytest.CaptureFixture[str]) -> None:
        advice = ShopAdvice(
            jokers=(
                JokerOffer(
                    item=ShopItem("j_joker", "Joker", "JOKER", 1, "+4 Mult"),
                    affordable=True,
                    has_slot=True,
                    known=True,
                    expected_uplift=4.0,
                    exact_deck=True,
                    samples=12,
                    interest_lost=0,
                    rental_cost_per_round=3,
                    perishable_rounds=5,
                    eternal=True,
                ),
            ),
            vouchers=(),
            packs=(),
            money=10,
            reroll=None,
        )
        render_shop_advice(advice)
        out = capsys.readouterr().out
        assert "аренда −$3 каждый раунд" in out
        assert "отключится через 5 раунд(ов)" in out
        assert "вечный — не продать" in out

    def test_ваучеры_без_оценки_показаны_текстом(self, capsys: pytest.CaptureFixture[str]) -> None:
        advice = ShopAdvice(
            jokers=(),
            vouchers=(
                VoucherOffer(
                    item=ShopItem("v_overstock", "Overstock", "VOUCHER", 10, "+1 слот в магазине"),
                    expected_uplift=None,
                    exact_deck=False,
                    samples=0,
                ),
            ),
            packs=(
                PackPurchaseOffer(
                    item=ShopItem("p_arcana_normal_1", "Arcana Pack", "BOOSTER", 4),
                    affordable=True,
                    has_slot=True,
                    expected_uplift=None,
                    exact_deck=False,
                    samples=0,
                    note="оценивается только Buffoon-пак",
                ),
            ),
            money=10,
            reroll=None,
        )
        render_shop_advice(advice)
        out = capsys.readouterr().out
        assert "Overstock" in out
        assert "+1 слот в магазине" in out
        assert "Arcana Pack" in out
        assert "Arcana Pack" in out

    def test_ваучер_с_оценкой_показывает_прирост_и_примечание(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        advice = ShopAdvice(
            jokers=(),
            vouchers=(
                VoucherOffer(
                    item=ShopItem("v_wasteful", "Wasteful", "VOUCHER", 10),
                    expected_uplift=15.0,
                    exact_deck=True,
                    samples=4,
                    note="нижняя граница: учтён только один лучший одиночный сброс",
                ),
            ),
            packs=(),
            money=10,
            reroll=None,
        )
        render_shop_advice(advice)
        out = capsys.readouterr().out
        assert "прирост ~15" in out
        assert "нижняя граница" in out

    def test_ваучер_с_эвристикой_показывает_экспертную_оценку(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        advice = ShopAdvice(
            jokers=(),
            vouchers=(
                VoucherOffer(
                    item=ShopItem("v_antimatter", "Antimatter", "VOUCHER", 10),
                    expected_uplift=None,
                    exact_deck=True,
                    samples=0,
                    note="лишний слот джокера",
                    heuristic_value=8.0,
                ),
            ),
            packs=(),
            money=10,
            reroll=None,
        )
        render_shop_advice(advice)
        out = capsys.readouterr().out
        assert "экспертно ~8" in out
        assert "лишний слот джокера" in out
        assert "прирост" not in out
