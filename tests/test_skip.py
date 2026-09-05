"""Тесты совета по скипу блайнда (`balatro_bot/solver/skip.py`).

Проверяется первый кусок Фазы 8 плана («Стратегия рана»): разложенные числа
для решения «играть или скипнуть», без единого вердикта — часть тегов
принципиально не сводится к одному числу (см. `core/tags.py`).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from balatro_bot.core.cards import standard_deck
from balatro_bot.core.state import BlindInfo, GameState
from balatro_bot.solver import shop as shop_module
from balatro_bot.solver.skip import evaluate_skip


def _blind(
    kind: str, status: str, score: int, tag_name: str = "", tag_effect: str = ""
) -> BlindInfo:
    return BlindInfo(
        kind=kind,
        name=f"{kind.title()} Blind",
        effect="",
        required_score=score,
        status=status,
        tag_name=tag_name,
        tag_effect=tag_effect,
    )


class TestEvaluateSkip:
    def test_нет_блайнда_на_выбор_даёт_none(self) -> None:
        state = GameState(
            phase="SELECTING_HAND",
            blinds={
                "small": _blind("SMALL", "DEFEATED", 300),
                "big": _blind("BIG", "CURRENT", 450),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        assert evaluate_skip(state) is None

    def test_пустые_blinds_дают_none(self) -> None:
        assert evaluate_skip(GameState()) is None

    def test_boss_select_не_даёт_совета_по_скипу(self) -> None:
        # Боссовый блайнд нельзя скипнуть — даже если статус SELECT.
        state = GameState(
            phase="BLIND_SELECT",
            blinds={
                "small": _blind("SMALL", "DEFEATED", 300),
                "big": _blind("BIG", "DEFEATED", 450),
                "boss": _blind("BOSS", "SELECT", 600),
            },
        )
        assert evaluate_skip(state) is None

    def test_big_blind_выбираем_следующий_boss(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            money=5,
            blinds={
                "small": _blind("SMALL", "DEFEATED", 300),
                "big": _blind(
                    "BIG", "SELECT", 450, "Investment Tag", "После победы над Боссом даёт $25"
                ),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert advice.blind_kind == "BIG"
        assert advice.required_score == 450
        assert advice.next_blind_kind == "BOSS"
        assert advice.next_required_score == 600
        assert advice.requirement_ratio == 600 / 450
        assert advice.play_reward_min == 4  # game.lua: bl_big.dollars = 4

    def test_small_blind_выбираем_следующий_big(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            blinds={
                "small": _blind("SMALL", "SELECT", 300, "Voucher Tag", "Добавляет ваучер"),
                "big": _blind("BIG", "UPCOMING", 450),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert advice.blind_kind == "SMALL"
        assert advice.next_blind_kind == "BIG"
        assert advice.next_required_score == 450
        assert advice.play_reward_min == 3  # game.lua: bl_small.dollars = 3

    def test_investment_tag_даёт_25_долларов_с_условием(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            blinds={
                "small": _blind("SMALL", "DEFEATED", 300),
                "big": _blind("BIG", "SELECT", 450, "Investment Tag", "..."),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert advice.tag_dollars == 25.0
        assert (
            "боссом" in advice.tag_dollars_note.lower() or "boss" in advice.tag_dollars_note.lower()
        )
        assert advice.tag is not None
        assert advice.tag.key == "tag_investment"

    def test_economy_tag_удваивает_деньги_с_потолком(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            money=15,
            blinds={
                "small": _blind("SMALL", "SELECT", 300, "Economy Tag", "..."),
                "big": _blind("BIG", "UPCOMING", 450),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert advice.tag_dollars == 15.0  # min(40, 15)

    def test_economy_tag_упирается_в_потолок(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            money=100,
            blinds={
                "small": _blind("SMALL", "SELECT", 300, "Economy Tag", "..."),
                "big": _blind("BIG", "UPCOMING", 450),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert advice.tag_dollars == 40.0  # min(40, 100)

    def test_тег_без_доступной_формулы_возвращает_none_с_объяснением(self) -> None:
        # Handy Tag требует счётчик рук за весь ран — мод его не присылает.
        state = GameState(
            phase="BLIND_SELECT",
            blinds={
                "small": _blind("SMALL", "SELECT", 300, "Handy Tag", "..."),
                "big": _blind("BIG", "UPCOMING", 450),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert advice.tag_dollars is None
        assert advice.tag_dollars_note

    def test_неизвестный_тег_не_роняет_и_помечает_none(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            blinds={
                "small": _blind("SMALL", "SELECT", 300, "Совершенно Новый Tag", "..."),
                "big": _blind("BIG", "UPCOMING", 450),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert advice.tag is None
        assert advice.tag_dollars is None

    def test_без_следующего_блайнда_в_данных_соотношение_не_считается(self) -> None:
        state = GameState(
            phase="BLIND_SELECT",
            blinds={"big": _blind("BIG", "SELECT", 450, "Investment Tag", "...")},
        )
        advice = evaluate_skip(state)
        assert advice is not None
        assert advice.next_required_score == 0
        assert advice.requirement_ratio != advice.requirement_ratio  # NaN != NaN

    def test_replace_на_реальном_состоянии_не_ломает_остальное(self) -> None:
        # Убеждаемся, что новое поле `blinds` не мешает старому `blind`.
        base = GameState(phase="BLIND_SELECT")
        state = replace(
            base,
            blinds={"big": _blind("BIG", "SELECT", 450, "Investment Tag", "...")},
        )
        assert state.blind is None
        assert evaluate_skip(state) is not None


class TestПокрытиеТегов:
    """Улучшение A14. До него скип требовал точной денежной цены, а она есть
    у двух тегов из двадцати четырёх — то есть двадцать два тега не могли
    быть выбраны никогда. Ран 12: 20 выборов блайнда, 0 скипов, мимо прошли
    `Negative Tag`, `Rare Tag`, `Polychrome Tag`.

    Главное здесь — покрытие: каждый тег обязан получить **какой-то** ответ,
    иначе новый тег молча провалится в «не оценивается», как это и было."""

    def _state(self, tag: str, **overrides: object) -> GameState:
        base: dict[str, object] = {
            "phase": "BLIND_SELECT",
            "blinds": {
                "small": _blind("SMALL", "SELECT", 300, tag, "..."),
                "big": _blind("BIG", "UPCOMING", 450),
                "boss": _blind("BOSS", "UPCOMING", 600),
            },
        }
        return GameState(**{**base, **overrides})  # type: ignore[arg-type]

    def test_каждый_тег_каталога_получает_ответ(self) -> None:
        from balatro_bot.core.tags import TAGS

        без_ответа = []
        for effect in TAGS.values():
            advice = evaluate_skip(self._state(effect.name))
            assert advice is not None, effect.name
            оценён = (
                advice.tag_uplift is not None
                or advice.tag_dollars is not None
                or advice.tag_heuristic is not None
            )
            # Не оценён — обязан объяснить почему, а не молчать.
            if not оценён and not advice.tag_dollars_note:
                без_ответа.append(effect.name)
        assert без_ответа == []

    def test_структурные_теги_на_шкале_ваучеров(self) -> None:
        from balatro_bot.solver.vouchers import _HEURISTIC_VALUES

        # `Negative Tag` даёт +1 слот джокера — ровно то же, что `v_antimatter`,
        # и оценка обязана быть той же, а не отдельно выдуманной.
        advice = evaluate_skip(self._state("Negative Tag"))
        assert advice is not None
        assert advice.tag_heuristic == _HEURISTIC_VALUES["v_antimatter"]

    def test_неоценимый_тег_называет_причину(self) -> None:
        advice = evaluate_skip(self._state("Handy Tag"))
        assert advice is not None
        assert advice.tag_heuristic is None
        assert advice.tag_uplift is None
        assert "счётчик" in advice.tag_dollars_note

    def test_пак_который_проект_не_оценивает_назван(self) -> None:
        advice = evaluate_skip(self._state("Charm Tag"))
        assert advice is not None
        assert advice.tag_uplift is None
        assert "не оценивает" in advice.tag_dollars_note


class TestЛенивостьОценкиТегов:
    """Оценка первого уровня требует пула приростов — замерено 2.4 с
    (планеты) и 9.8 с (джокеры). Экран выбора блайнда случается за ран
    десятки раз, поэтому пул обязан считаться, только когда на экране лежит
    тег, которому он действительно нужен."""

    def _state(self, tag: str) -> GameState:
        return GameState(
            phase="BLIND_SELECT",
            full_deck=standard_deck(),
            blinds={
                "small": _blind("SMALL", "SELECT", 300, tag, "..."),
                "big": _blind("BIG", "UPCOMING", 450),
            },
        )

    def _счётчик(
        self, monkeypatch: pytest.MonkeyPatch, *, настоящий_планетный: bool = False
    ) -> list[str]:
        """Подменить оба пула считающими обёртками. Планетный по желанию
        остаётся настоящим — чтобы проверить не только факт вызова, но и что
        число получилось."""
        вызовы: list[str] = []
        исходный = shop_module.planet_uplift_pool

        def планетный(state: GameState, deck: object) -> list[float]:
            вызовы.append("planet")
            return исходный(state, deck) if настоящий_планетный else []  # type: ignore[arg-type]

        def джокерный(state: GameState, deck: object) -> list[float]:
            вызовы.append("joker")
            return []

        monkeypatch.setattr(shop_module, "planet_uplift_pool", планетный)
        monkeypatch.setattr(shop_module, "random_joker_uplift_pool", джокерный)
        return вызовы

    def test_без_пакового_тега_пулы_не_трогаются(self, monkeypatch: pytest.MonkeyPatch) -> None:
        вызовы = self._счётчик(monkeypatch)
        for tag in ("Negative Tag", "Handy Tag", "Investment Tag", "Charm Tag"):
            evaluate_skip(self._state(tag))
        assert вызовы == []

    def test_meteor_считает_только_планетный_пул(self, monkeypatch: pytest.MonkeyPatch) -> None:
        вызовы = self._счётчик(monkeypatch, настоящий_планетный=True)
        advice = evaluate_skip(self._state("Meteor Tag"))
        assert advice is not None
        assert вызовы == ["planet"]
        assert advice.tag_uplift is not None and advice.tag_uplift > 0

    def test_buffoon_считает_только_джокерный_пул(self, monkeypatch: pytest.MonkeyPatch) -> None:
        вызовы = self._счётчик(monkeypatch)
        evaluate_skip(self._state("Buffoon Tag"))
        assert вызовы == ["joker"]

    def test_orbital_оценивается_в_очках(self) -> None:
        advice = evaluate_skip(self._state("Orbital Tag"))
        assert advice is not None
        assert advice.tag_uplift is not None and advice.tag_uplift > 0
