"""Тесты EV сброса: `solver/discard.py`.

Проверяется узкий срез Фазы 6 (раздел 8.1 плана): точный перебор добора для
одного заданного набора карт на сброс, не полный перебор по всем наборам —
и `advise_discard`, поиск лучшего сброса по целям без перебора всех наборов
сброса (`docs/Discard Spec.md`).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

import balatro_bot.solver.discard as discard_module
from balatro_bot.adapters.manual import build_state
from balatro_bot.core.cards import Suit, parse_cards, standard_deck
from balatro_bot.core.hands import HandModifiers
from balatro_bot.core.state import GameState
from balatro_bot.solver.discard import (
    MAX_DISCARD_SIZE,
    _flush_targets,
    _full_house_targets,
    _keep_as_is_target,
    _n_of_a_kind_targets,
    _straight_targets,
    _straight_windows,
    advise_discard,
    discard_outcome,
    known_deck,
    rank_single_discards,
)
from balatro_bot.solver.play import advise


class TestИзвестнаяКолода:
    def test_с_колодой_из_моста_точная(self) -> None:
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        state = replace(state, deck=parse_cards("2H 3H"))
        deck, exact = known_deck(state)
        assert exact is True
        assert deck == parse_cards("2H 3H")

    def test_без_колоды_приближение_из_52_минус_рука(self) -> None:
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        deck, exact = known_deck(state)
        assert exact is False
        assert len(deck) == 52 - len(state.hand)
        assert not set(deck) & set(state.hand)


class TestEVСброса:
    def test_среднее_совпадает_с_ручным_перебором(self) -> None:
        # Маленькая контролируемая колода: держим 7 карт, добираем 1 из двух.
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        state = replace(state, deck=parse_cards("2H 3C"))
        discard = parse_cards("2S")

        outcome = discard_outcome(state, discard)
        assert outcome is not None
        assert outcome.exact is True
        assert outcome.draws_considered == 2
        assert outcome.kept == state.hand[:-1]

        kept = state.hand[:-1]
        ожидаемое = (
            sum(
                advise(replace(state, hand=kept + draw)).best.score
                for draw in (parse_cards("2H"), parse_cards("3C"))
            )
            / 2
        )
        assert outcome.expected == ожидаемое

    def test_превышение_лимита_возвращает_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(discard_module, "MAX_DRAW_COMBINATIONS", 1)
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        state = replace(state, deck=parse_cards("2H 3C"))

        assert discard_outcome(state, parse_cards("2S")) is None

    def test_пустая_известная_колода_возвращает_none(self) -> None:
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        state = replace(state, deck=())

        assert discard_outcome(state, parse_cards("2S")) is None

    def test_несколько_карт_на_сброс(self) -> None:
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        state = replace(state, deck=parse_cards("2H 3C 4D"))
        discard = parse_cards("7C 7D")

        outcome = discard_outcome(state, discard)
        assert outcome is not None
        # C(3, 2) = 3 комбинации добора.
        assert outcome.draws_considered == 3


class TestRankSingleDiscards:
    def test_отсортировано_по_убыванию_ev(self) -> None:
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        ranking = rank_single_discards(state)
        значения = [outcome.expected for outcome in ranking]
        assert значения == sorted(значения, reverse=True)

    def test_каждая_карта_руки_свой_кандидат(self) -> None:
        state = build_state("AH KH QH JH 9H 7C 7D 2S")
        ranking = rank_single_discards(state)
        сброшенные = {outcome.discarded[0] for outcome in ranking}
        assert сброшенные == set(state.hand)
        assert all(len(outcome.discarded) == 1 for outcome in ranking)

    def test_пустая_рука_даёт_пустой_список(self) -> None:
        state = build_state("AH KH QH JH 9H")
        state = replace(state, hand=())
        assert rank_single_discards(state) == ()


class TestОкнаСтрита:
    def test_без_модификаторов_десять_окон(self) -> None:
        windows = _straight_windows(HandModifiers())
        assert len(windows) == 10
        assert frozenset({1, 2, 3, 4, 5}) in windows  # A-2-3-4-5
        assert frozenset({10, 11, 12, 13, 14}) in windows  # 10-J-Q-K-A
        assert all(max(w) - min(w) == 4 for w in windows)  # подряд, без дыр

    def test_four_fingers_окна_из_четырёх_карт(self) -> None:
        windows = _straight_windows(HandModifiers(four_fingers=True))
        assert len(windows) == 11
        assert all(len(w) == 4 for w in windows)

    def test_shortcut_допускает_окна_с_пропуском(self) -> None:
        base = set(_straight_windows(HandModifiers()))
        with_shortcut = set(_straight_windows(HandModifiers(shortcut=True)))
        assert base <= with_shortcut  # обычные окна тоже валидны
        assert frozenset({1, 3, 5, 7, 9}) in with_shortcut  # шаг 2 везде
        assert frozenset({1, 3, 5, 7, 9}) not in base


class TestЦелиФлеш:
    def test_нужна_одна_карта_масти(self) -> None:
        hand = parse_cards("AH KH QH 9H 2C 7D 3S 4S")
        unseen = tuple(c for c in standard_deck() if c not in hand)
        targets = _flush_targets(hand, unseen, HandModifiers())

        червы = next(t for t in targets if t.name == "флеш черви")
        assert червы.needed == 1
        assert set(червы.keep) == set(parse_cards("AH KH QH 9H"))
        assert all(c.suit is Suit.HEARTS for c in червы.outs)

    def test_smeared_объединяет_масти(self) -> None:
        # 4 карты черви/бубны + 4 карты трефы/пики: обе смешанные группы
        # остаются целями (нужна ровно одна карта каждой).
        hand = parse_cards("AH KH QH 9D 2C 3S 4S 5C")
        unseen = tuple(c for c in standard_deck() if c not in hand)
        targets = _flush_targets(hand, unseen, HandModifiers(smeared=True))

        assert len(targets) == 2  # черви+бубны, трефы+пики
        сборная = next(t for t in targets if "черви" in t.name)
        assert сборная.needed == 1
        assert set(сборная.keep) == set(parse_cards("AH KH QH 9D"))

    def test_уже_собранный_флеш_не_цель_остальные_масти_остаются(self) -> None:
        hand = parse_cards("AH KH QH TH 9H 2C 3S 4S")
        unseen = tuple(c for c in standard_deck() if c not in hand)
        targets = _flush_targets(hand, unseen, HandModifiers())
        имена = {t.name for t in targets}
        assert "флеш черви" not in имена  # уже собран — не цель (раздел 4.3)
        assert имена == {"флеш бубны", "флеш трефы", "флеш пики"}


class TestЦелиСтрит:
    def test_нужна_одна_карта_для_окна(self) -> None:
        hand = parse_cards("AH KH QH 9H 2C 7D 3S 4S")
        unseen = tuple(c for c in standard_deck() if c not in hand)
        targets = _straight_targets(hand, unseen, HandModifiers())

        цель = next(t for t in targets if t.name == "стрит T-J-Q-K-A")
        assert цель.needed == 2
        assert set(цель.keep) == set(parse_cards("AH KH QH"))


class TestЦелиНОдинаковых:
    def test_до_трипла_и_каре(self) -> None:
        hand = parse_cards("7H 7D 2C 3S 4S 5D 6C 9H")
        unseen = tuple(c for c in standard_deck() if c not in hand)
        targets = _n_of_a_kind_targets(hand, unseen)

        by_name = {t.name: t for t in targets}
        assert by_name["трипл 7"].needed == 1
        assert by_name["каре 7"].needed == 2
        assert set(by_name["трипл 7"].keep) == set(parse_cards("7H 7D"))
        # Пятёрка одинаковых недостижима из стандартной колоды: всего 4
        # карты каждого ранга, а у нас уже 2 на руках — аутов не хватает
        # (нужно 3, доступно 2), цель отсекается по 4.3.
        assert "пятёрка 7" not in by_name


class TestЦелиФуллХаус:
    def test_две_пары_дают_два_варианта(self) -> None:
        hand = parse_cards("AH AD KH KD 2C 3S 4S 5D")
        unseen = tuple(c for c in standard_deck() if c not in hand)
        targets = _full_house_targets(hand, unseen)

        assert {t.needed for t in targets} == {1}
        keeps = {frozenset(t.keep) for t in targets}
        assert keeps == {frozenset(parse_cards("AH AD KH KD"))}  # один и тот же сброс

    def test_меньше_двух_рангов_нет_целей(self) -> None:
        # Только один ранг в руке (вырожденный случай) — фулл-хаусу нужны
        # два разных ранга, строить не из чего.
        hand = parse_cards("AH AH")
        unseen = tuple(c for c in standard_deck() if c not in hand)
        assert _full_house_targets(hand, unseen) == []


class TestЦельОставитьКакЕсть:
    def test_needed_всегда_ноль(self) -> None:
        hand = parse_cards("AH KH QH 9H 2C 7D 3S 4S")
        цель = _keep_as_is_target(hand, HandModifiers())
        assert цель is not None
        assert цель.needed == 0
        assert цель.outs == ()

    def test_если_держать_нечего_сбрасывать_цели_нет(self) -> None:
        hand = parse_cards("AH KH")
        цель = _keep_as_is_target(hand, HandModifiers())
        assert цель is None or len(цель.keep) < len(hand)


class TestAdviseDiscard:
    def test_сбросов_не_осталось_пустой_результат(self) -> None:
        state = build_state("AH KH QH 9H 2C 7D 3S 4S", discards_left=0)
        assert advise_discard(state) == ()

    def test_мало_карт_в_руке_пустой_результат(self) -> None:
        state = build_state("AH", discards_left=1)
        assert advise_discard(state) == ()

    def test_ни_один_вариант_не_сбрасывает_больше_лимита(self) -> None:
        state = build_state("AH KH QH 9H 2C 7D 3S 4S", discards_left=1)
        for option in advise_discard(state):
            assert 1 <= len(option.discard) <= MAX_DISCARD_SIZE
            assert option.exact is False

    def test_вероятность_прихода_карты_в_пределах_нуля_и_единицы(self) -> None:
        state = build_state("AH KH QH 9H 2C 7D 3S 4S", discards_left=1)
        for option in advise_discard(state):
            assert 0.0 <= option.success_probability <= 1.0

    def test_вероятность_прихода_карты_это_сумма_подходящих_корзин(self) -> None:
        option = advise_discard(build_state("AH KH QH 9H 2C 7D 3S 4S", discards_left=1))[0]
        ожидаемая = sum(
            bucket.probability for bucket in option.distribution if bucket.outs_hit >= option.needed
        )
        assert option.success_probability == ожидаемая

    def test_отсортировано_по_убыванию_ожидания(self) -> None:
        state = build_state("AH KH QH 9H 2C 7D 3S 4S", discards_left=1)
        options = advise_discard(state)
        значения = [o.expected for o in options]
        assert значения == sorted(значения, reverse=True)

    def test_лимит_обрезает_список(self) -> None:
        state = build_state("AH KH QH 9H 2C 7D 3S 4S", discards_left=1)
        assert len(advise_discard(state, limit=2)) <= 2

    def test_детерминирован(self) -> None:
        state = build_state("AH KH QH 9H 2C 7D 3S 4S", discards_left=1)
        assert advise_discard(state) == advise_discard(state)

    def test_группировка_объединяет_имена_целей(self) -> None:
        # Держа 9H TH JH QH, тот же сброс (всё остальное) служит и флешу
        # червей, и стриту 9-T-J-Q-K (раздел 4.4 спеки, тот же пример).
        state = build_state("9H TH JH QH 2C 3D 4S 5C", discards_left=1)
        keep = frozenset(state.hand[:4])
        options = advise_discard(state)
        merged = next(o for o in options if frozenset(o.keep) == keep)
        assert len(merged.targets) > 1
        assert "флеш черви" in merged.targets


class TestAdviseDiscardПротивЭталона:
    """Критерии приёмки из раздела 7 спеки, на укороченной колоде.

    `discard_outcome` — честный перебор без сэмплирования, эталон для
    сверки. Колода взята укороченной (13 карт), чтобы держать перебор
    внутри `MAX_DRAW_COMBINATIONS` для сбросов размера вплоть до пяти.
    """

    @staticmethod
    def _state(hand: str) -> GameState:
        state = build_state(hand, discards_left=1)
        unseen = tuple(c for c in standard_deck() if c not in state.hand)[:13]
        return replace(state, deck=unseen)

    def test_порядок_и_отклонение_в_пределах_допуска(self) -> None:
        state = self._state("AH KH QH 9H 2C 7D 3S 4S")
        options = advise_discard(state, limit=5)
        assert options

        # Каждый вариант сверяется с честным перебором того же сброса.
        сверено = 0
        for option in options:
            эталон = discard_outcome(state, option.discard)
            if эталон is None:
                continue
            сверено += 1
            отклонение = abs(option.expected - эталон.expected) / max(эталон.expected, 1)
            assert отклонение <= 0.15, (option.discard, option.expected, эталон.expected)
        assert сверено >= 1

    def test_лучший_вариант_среди_лучших_по_эталону(self) -> None:
        state = self._state("AH KH QH 9H 2C 7D 3S 4S")
        options = advise_discard(state, limit=5)
        assert options

        эталоны = [
            (option, discard_outcome(state, option.discard))
            for option in options
            if discard_outcome(state, option.discard) is not None
        ]
        эталоны_отсортированы = sorted(эталоны, key=lambda item: -item[1].expected)  # type: ignore[union-attr]
        топ_по_эталону = {
            tuple(sorted(map(repr, item[0].discard))) for item in эталоны_отсортированы[:3]
        }
        лучший_по_аналитике = tuple(sorted(map(repr, options[0].discard)))
        assert лучший_по_аналитике in топ_по_эталону
