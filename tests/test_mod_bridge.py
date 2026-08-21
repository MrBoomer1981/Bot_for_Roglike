"""Тесты моста к моду.

Игры здесь нет, поэтому проверка идёт против фальшивого JSON-RPC сервера,
отвечающего по схеме из спецификации мода (`src/lua/utils/openrpc.json`).
Смысл в том, чтобы к моменту первого запуска на Mac клиент был уже отлажен
и оставалось проверить только саму установку.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from balatro_bot.adapters.mod_bridge import (
    ModBridge,
    NotConnectedError,
    RpcError,
    parse_game_state,
)
from balatro_bot.core.cards import Edition, Enhancement, Rank, Seal, Suit
from balatro_bot.core.hands import HandType
from tests.fake_mod import FakeMod, sample_state


class TestРазборСостояния:
    def test_рука_разбирается_целиком(self) -> None:
        state = parse_game_state(sample_state())
        assert len(state.hand) == 8
        assert state.hand[0].rank is Rank.ACE
        assert state.hand[0].suit is Suit.HEARTS

    def test_десятка_приходит_как_T(self) -> None:
        state = parse_game_state(sample_state())
        assert state.hand[-1].rank is Rank.TEN

    def test_модификаторы_карты(self) -> None:
        card = parse_game_state(sample_state()).hand[4]
        assert card.enhancement is Enhancement.BONUS
        assert card.edition is Edition.FOIL
        assert card.seal is Seal.RED

    def test_дебафф_переносится(self) -> None:
        assert parse_game_state(sample_state()).hand[6].debuffed is True

    def test_джокеры_в_порядке_слотов(self) -> None:
        jokers = parse_game_state(sample_state()).jokers
        assert [joker.key for joker in jokers] == ["j_joker", "j_blueprint"]

    def test_издание_holo_переименовано(self) -> None:
        # Мод называет издание `HOLO`, у нас оно `HOLOGRAPHIC`.
        assert parse_game_state(sample_state()).jokers[1].edition is Edition.HOLOGRAPHIC

    def test_текущий_блайнд_выбирается_по_статусу(self) -> None:
        blind = parse_game_state(sample_state()).blind
        assert blind is not None
        assert blind.kind == "BIG"
        assert blind.required_score == 450

    def test_ресурсы_раунда(self) -> None:
        state = parse_game_state(sample_state())
        assert state.hands_left == 3
        assert state.discards_left == 2

    def test_пустое_состояние_не_падает(self) -> None:
        state = parse_game_state({})
        assert state.hand == ()
        assert state.blind is None


class TestТекущееЗначениеДжокера:
    """Джокеры-накопители (Green Joker, Square, ...) сами не хранят историю
    событий — их текущий вклад читается из текста эффекта, который игра уже
    сама посчитала и отрендерила. Мост вытаскивает число из последней
    скобочной группы, независимо от языка игры."""

    @staticmethod
    def _state_with_joker(effect: str) -> Mapping[str, object]:
        return {
            "jokers": {
                "cards": [{"key": "j_square", "label": "Square Joker", "value": {"effect": effect}}]
            }
        }

    def test_число_из_русского_текста(self) -> None:
        state = parse_game_state(
            self._state_with_joker("+4 фишки, если рука из 4 карт (сейчас +8 фишек)")
        )
        assert state.jokers[0].current_value == 8

    def test_число_из_английского_текста(self) -> None:
        state = parse_game_state(
            self._state_with_joker(
                "+4 Chips if played hand has exactly 4 cards (Currently +8 Chips)"
            )
        )
        assert state.jokers[0].current_value == 8

    def test_отрицательное_число(self) -> None:
        state = parse_game_state(self._state_with_joker("+1 за руку, −1 за сброс (сейчас −3)"))
        assert state.jokers[0].current_value == -3

    def test_без_скобочной_группы_с_числом(self) -> None:
        state = parse_game_state(
            self._state_with_joker("За каждую 8 есть шанс (должно быть место)")
        )
        assert state.jokers[0].current_value is None

    def test_без_текста_эффекта(self) -> None:
        state = parse_game_state({"jokers": {"cards": [{"key": "j_square"}]}})
        assert state.jokers[0].current_value is None


class TestЗначенияРук:
    def test_берутся_из_игры(self) -> None:
        state = parse_game_state(sample_state())
        assert state.has_authoritative_hand_values
        assert state.hand_values(HandType.PAIR).chips == 25

    def test_уровень_руки_доступен(self) -> None:
        info = parse_game_state(sample_state()).hand_info[HandType.PAIR]
        assert info.level == 2

    def test_имена_рук_сопоставляются_без_учёта_пробелов(self) -> None:
        assert HandType.THREE_OF_A_KIND in parse_game_state(sample_state()).hand_info

    def test_запасной_путь_для_отсутствующей_руки(self) -> None:
        # Full House игра в этом состоянии не прислала — берём провизорную таблицу.
        assert parse_game_state(sample_state()).hand_values(HandType.FULL_HOUSE).chips > 0


class TestМеханизмЧестности:
    def test_известные_джокеры_дают_точное_состояние(self) -> None:
        assert parse_game_state(sample_state()).is_exact

    def test_незнакомый_джокер_делает_состояние_неточным(self) -> None:
        raw = sample_state()
        raw["jokers"]["cards"][0]["key"] = "j_выдуманный"
        state = parse_game_state(raw)
        assert not state.is_exact
        assert state.unknown_jokers == ("j_выдуманный",)

    def test_незнакомое_улучшение_запоминается(self) -> None:
        raw = sample_state()
        raw["hand"]["cards"][0]["modifier"]["enhancement"] = "ПЛАЗМЕННОЕ"
        state = parse_game_state(raw)
        assert not state.is_exact
        assert any("ПЛАЗМЕННОЕ" in key for key in state.unknown_keys)

    def test_незнакомое_улучшение_не_роняет_разбор(self) -> None:
        raw = sample_state()
        raw["hand"]["cards"][0]["modifier"]["enhancement"] = "ПЛАЗМЕННОЕ"
        assert len(parse_game_state(raw).hand) == 8

    def test_незнакомый_тип_руки_запоминается(self) -> None:
        raw = sample_state()
        raw["hands"]["Небывалая Рука"] = {"level": 1, "chips": 1, "mult": 1}
        assert "hand:Небывалая Рука" in parse_game_state(raw).unknown_keys


class TestКлиент:
    def test_проверка_живости(self, bridge: ModBridge) -> None:
        assert bridge.is_alive()

    def test_запрос_состояния(self, bridge: ModBridge) -> None:
        state = bridge.game_state()
        assert state.phase == "SELECTING_HAND"
        assert len(state.hand) == 8

    def test_сырое_состояние_доступно(self, bridge: ModBridge) -> None:
        # Нужно для записи эталонных случаев: сохраняем ровно то, что прислала игра.
        assert bridge.raw_game_state()["state"] == "SELECTING_HAND"

    def test_розыгрыш_передаёт_индексы(self, bridge: ModBridge) -> None:
        bridge.play([0, 2, 4])
        assert FakeMod.calls[-1]["method"] == "play"
        assert FakeMod.calls[-1]["params"] == {"cards": [0, 2, 4]}

    def test_сброс_передаёт_индексы(self, bridge: ModBridge) -> None:
        bridge.discard([1, 3])
        assert FakeMod.calls[-1]["params"] == {"cards": [1, 3]}

    def test_идентификаторы_запросов_растут(self, bridge: ModBridge) -> None:
        bridge.is_alive()
        bridge.is_alive()
        assert FakeMod.calls[0]["id"] < FakeMod.calls[1]["id"]

    def test_запросы_валидны_по_jsonrpc(self, bridge: ModBridge) -> None:
        bridge.is_alive()
        assert FakeMod.calls[0]["jsonrpc"] == "2.0"

    def test_ошибка_мода_превращается_в_исключение(self, bridge: ModBridge) -> None:
        FakeMod.error_for = "play"
        with pytest.raises(RpcError) as info:
            bridge.play([0])
        assert info.value.code == -32602

    def test_живость_не_бросает_при_ошибке(self, bridge: ModBridge) -> None:
        FakeMod.error_for = "health"
        assert bridge.is_alive() is False


class TestНетСоединения:
    def test_понятная_ошибка_если_игра_не_запущена(self) -> None:
        # Порт, на котором заведомо никто не слушает.
        bridge = ModBridge(port=1, timeout=1.0)
        with pytest.raises(NotConnectedError, match="balatrobot serve"):
            bridge.game_state()

    def test_живость_возвращает_ложь(self) -> None:
        assert ModBridge(port=1, timeout=1.0).is_alive() is False


class TestКолода:
    def test_тип_колоды_разбирается(self) -> None:
        assert parse_game_state(sample_state()).deck_type == "RED"

    def test_без_области_cards_колода_неизвестна(self) -> None:
        assert parse_game_state(sample_state()).deck is None

    def test_область_cards_разбирается_в_колоду(self) -> None:
        raw = sample_state()
        raw["cards"] = {
            "count": 2,
            "cards": [
                {"value": {"suit": "C", "rank": "2"}, "modifier": {}, "state": {}},
                {"value": {"suit": "D", "rank": "3"}, "modifier": {}, "state": {}},
            ],
        }
        state = parse_game_state(raw)
        assert state.deck is not None
        assert len(state.deck) == 2
        assert state.deck[0].rank is Rank.TWO
        assert state.deck[1].suit is Suit.DIAMONDS

    def test_пустая_область_cards_это_известная_пустая_колода(self) -> None:
        # Отличаем «мод прислал: доборов нет» от «мод вообще не прислал колоду».
        raw = sample_state()
        raw["cards"] = {"count": 0, "cards": []}
        assert parse_game_state(raw).deck == ()

    def test_полная_колода_в_начале_раунда(self) -> None:
        # Ничего не сыграно и не сброшено — hand ∪ cards и есть вся колода.
        raw = sample_state()
        raw["round"]["hands_played"] = 0
        raw["round"]["discards_used"] = 0
        raw["cards"] = {
            "count": 1,
            "cards": [{"value": {"suit": "C", "rank": "2"}, "modifier": {}, "state": {}}],
        }
        state = parse_game_state(raw)
        assert state.full_deck is not None
        assert len(state.full_deck) == len(state.hand) + 1

    def test_полная_колода_неизвестна_если_уже_сыграно(self) -> None:
        raw = sample_state()
        raw["round"]["hands_played"] = 1
        raw["round"]["discards_used"] = 0
        raw["cards"] = {"count": 0, "cards": []}
        assert parse_game_state(raw).full_deck is None

    def test_полная_колода_неизвестна_если_уже_сброшено(self) -> None:
        raw = sample_state()
        raw["round"]["hands_played"] = 0
        raw["round"]["discards_used"] = 1
        raw["cards"] = {"count": 0, "cards": []}
        assert parse_game_state(raw).full_deck is None

    def test_полная_колода_неизвестна_без_cards(self) -> None:
        raw = sample_state()
        raw["round"]["hands_played"] = 0
        raw["round"]["discards_used"] = 0
        assert parse_game_state(raw).full_deck is None


def test_эталон_копируется_для_каждого_теста() -> None:
    first = sample_state()
    first["money"] = 999
    assert sample_state()["money"] != 999
