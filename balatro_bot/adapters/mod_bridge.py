"""Клиент к JSON-RPC API мода BalatroBot.

Мод `coder/balatrobot` (MIT) поднимает внутри игры HTTP-сервер с JSON-RPC 2.0
и отдаёт полное состояние рана. Здесь — тонкий клиент к нему и разбор ответа
в наши доменные типы.

Схема ответа взята из спецификации мода (`src/lua/utils/openrpc.json`), а не
угадана. Совпадения не случайны: масти и ранги в моде кодируются теми же
символами, что и в нашей компактной записи.

Зависимостей нет намеренно: стандартной библиотеки хватает, а лишняя
зависимость в адаптере усложнила бы установку на Mac.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

from balatro_bot.core.cards import Card, Edition, Enhancement, Rank, Seal, Suit
from balatro_bot.core.hands import HandType
from balatro_bot.core.state import BlindInfo, GameState, JokerCard, PokerHandInfo, ShopItem

__all__ = [
    "DEFAULT_PORT",
    "ModBridge",
    "ModBridgeError",
    "NotConnectedError",
    "RpcError",
    "parse_game_state",
]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 12346


class ModBridgeError(RuntimeError):
    """Общая ошибка работы с модом."""


class NotConnectedError(ModBridgeError):
    """Игра не запущена или мод не отвечает."""


class RpcError(ModBridgeError):
    """Мод вернул ошибку JSON-RPC."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.data = data


#: Мод именует издание `HOLO`, у нас оно называется полностью.
_EDITION_ALIASES = {"HOLO": Edition.HOLOGRAPHIC}


def _pick(
    raw: str | None,
    enum: type[Enhancement] | type[Edition] | type[Seal],
    kind: str,
    unknown: list[str],
) -> Any:
    """Опознать значение перечисления, запомнив незнакомое вместо падения."""
    if not raw:
        return enum.NONE if hasattr(enum, "NONE") else Edition.BASE
    if enum is Edition and raw in _EDITION_ALIASES:
        return _EDITION_ALIASES[raw]
    try:
        return enum[raw]
    except KeyError:
        unknown.append(f"{kind}:{raw}")
        return enum.NONE if hasattr(enum, "NONE") else Edition.BASE


def _parse_playing_card(payload: Mapping[str, Any], unknown: list[str]) -> Card | None:
    """Разобрать игральную карту. Джокеры и расходники сюда не попадают."""
    value = payload.get("value") or {}
    suit_symbol = value.get("suit")
    rank_symbol = value.get("rank")
    if not suit_symbol or not rank_symbol:
        return None

    try:
        suit = Suit(suit_symbol)
        rank = Rank(rank_symbol)
    except ValueError:
        unknown.append(f"card:{rank_symbol}{suit_symbol}")
        return None

    modifier = payload.get("modifier") or {}
    state = payload.get("state") or {}
    return Card(
        rank=rank,
        suit=suit,
        enhancement=_pick(modifier.get("enhancement"), Enhancement, "enhancement", unknown),
        edition=_pick(modifier.get("edition"), Edition, "edition", unknown),
        seal=_pick(modifier.get("seal"), Seal, "seal", unknown),
        debuffed=bool(state.get("debuff", False)),
    )


#: Скобочная группа с числом внутри — последняя в тексте эффекта. Игра сама
#: подставляет туда уже посчитанное текущее значение накопителя («сейчас
#: +15 множ.», «(Currently X2.5 Mult)») вне зависимости от языка игры, само
#: слово «сейчас»/«currently» не при чём — важна только позиция и цифра.
_PAREN_GROUP_RE = re.compile(r"\(([^()]*)\)")
_SIGNED_NUMBER_RE = re.compile(r"[+\-−]?\d+(?:[.,]\d+)?")


def _extract_current_value(effect: object) -> float | None:
    """Вытащить готовое число из последней скобочной группы текста эффекта.

    Не история событий — само значение уже посчитано игрой и просто
    отображается человеку. Не привязано к языку: ищет по структуре
    (последние скобки + число внутри), а не по конкретному слову.
    """
    if not isinstance(effect, str):
        return None
    groups = _PAREN_GROUP_RE.findall(effect)
    for group in reversed(groups):
        if match := _SIGNED_NUMBER_RE.search(group):
            return float(match.group().replace(",", ".").replace("−", "-"))
    return None


def _extract_leading_value(effect: object) -> float | None:
    """Вытащить первое число из текста эффекта — не в скобках, а вообще.

    Нужен `Popcorn`/`Ramen`: игра подставляет их текущее (затухающее)
    значение самым первым `var`, а статичный шаг угасания — уже вторым
    (сверено с `card.lua`: `loc_vars = {self.ability.mult, self.ability.extra}`
    у Popcorn), в отличие от `_extract_current_value`, где живое значение —
    последнее. Раз число первое, до него ничего своего в тексте ещё нет, так
    что дополнительно проверять позицию не нужно — как и там, само слово
    неважно, важна структура.
    """
    if not isinstance(effect, str):
        return None
    if match := _SIGNED_NUMBER_RE.search(effect):
        return float(match.group().replace(",", ".").replace("−", "-"))
    return None


#: Слова-названия мастей из `localization/{ru,en-us}.lua` (`suits_singular`
#: и `suits_plural` — в русской локализации они совпадают, в английской
#: расходятся окончанием, поэтому в словаре обе формы). Нужны `Ancient
#: Joker`: текущая масть-цель нигде не отдаётся полем, только этим словом
#: прямо в тексте эффекта. Работает только на этих двух языках — на прочих
#: `target_suit` останется `None`, и джокер честно пометит расчёт неточным.
_SUIT_WORDS: dict[str, Suit] = {
    "club": Suit.CLUBS,
    "clubs": Suit.CLUBS,
    "diamond": Suit.DIAMONDS,
    "diamonds": Suit.DIAMONDS,
    "heart": Suit.HEARTS,
    "hearts": Suit.HEARTS,
    "spade": Suit.SPADES,
    "spades": Suit.SPADES,
    "трефы": Suit.CLUBS,
    "бубны": Suit.DIAMONDS,
    "черви": Suit.HEARTS,
    "пики": Suit.SPADES,
}

#: Слова-названия рангов из `localization/{ru,en-us}.lua` (`ranks`). Нужны
#: `The Idol`. `2`/«2» намеренно не включён: у `The Idol` множитель всегда
#: X2 (`config.extra = 2`), поэтому цифра «2» есть в тексте эффекта
#: постоянно, независимо от того, какой ранг сейчас на самом деле цель —
#: как индикатор ранга она неоднозначна. Если цель — именно двойка, честнее
#: не найти её вовсе (`target_rank = None`), чем один раз случайно угадать.
_RANK_WORDS: dict[str, Rank] = {
    "ace": Rank.ACE,
    "jack": Rank.JACK,
    "queen": Rank.QUEEN,
    "king": Rank.KING,
    "туз": Rank.ACE,
    "валет": Rank.JACK,
    "дама": Rank.QUEEN,
    "король": Rank.KING,
    "3": Rank.THREE,
    "4": Rank.FOUR,
    "5": Rank.FIVE,
    "6": Rank.SIX,
    "7": Rank.SEVEN,
    "8": Rank.EIGHT,
    "9": Rank.NINE,
    "10": Rank.TEN,
}


def _extract_word[T](effect: object, words: Mapping[str, T]) -> T | None:
    """Найти первое известное слово из словаря в тексте эффекта (без учёта
    регистра, по границе слова — чтобы «10» не подошло под середину другого
    числа)."""
    if not isinstance(effect, str):
        return None
    lowered = effect.lower()
    for word, value in words.items():
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return value
    return None


#: Слова состояния `Loyalty Card` из `localization/{ru,en-us}.lua`
#: (`loyalty_active`/`loyalty_inactive`) — сверено с `card.lua`: множитель
#: X4 срабатывает ровно тогда, когда игра показывает «Активно!»/«Active!»
#: вместо счётчика «N осталось»/«N remaining». Нужную циклическую формулу
#: (`(every - 1 - (hands_played - hands_played_at_create)) % (every + 1)`)
#: посчитать самим нельзя — она зависит от момента покупки джокера, которого
#: состояние игры не хранит, поэтому распознаём готовый текст, а не считаем.
_LOYALTY_ACTIVE_WORDS = ("active!", "активно!")
_LOYALTY_INACTIVE_WORDS = ("remaining", "осталось")


def _extract_loyalty_active(effect: object) -> bool | None:
    """`True`/`False`, если текст эффекта явно говорит «активно» или «ещё N
    осталось», иначе `None` — не тот язык или число ещё не пришло."""
    if not isinstance(effect, str):
        return None
    lowered = effect.lower()
    if any(word in lowered for word in _LOYALTY_ACTIVE_WORDS):
        return True
    if any(word in lowered for word in _LOYALTY_INACTIVE_WORDS):
        return False
    return None


def _parse_joker(payload: Mapping[str, Any], unknown: list[str]) -> JokerCard:
    modifier = payload.get("modifier") or {}
    cost = payload.get("cost")
    sell_value = cost.get("sell") if isinstance(cost, Mapping) else None
    value = payload.get("value") or {}
    effect = value.get("effect")
    joker = JokerCard(
        key=str(payload.get("key", "")),
        label=str(payload.get("label", "")),
        edition=_pick(modifier.get("edition"), Edition, "edition", unknown),
        eternal=bool(modifier.get("eternal", False)),
        sell_value=int(sell_value) if sell_value is not None else None,
        current_value=_extract_current_value(effect),
        leading_value=_extract_leading_value(effect),
        target_suit=_extract_word(effect, _SUIT_WORDS),
        target_rank=_extract_word(effect, _RANK_WORDS),
        loyalty_active=_extract_loyalty_active(effect),
    )
    if not joker.is_known:
        unknown.append(f"joker:{joker.key}")
    return joker


def _area_cards(area: Any) -> list[Mapping[str, Any]]:
    """Карты из области состояния (`hand`, `jokers`, `shop`…)."""
    if not isinstance(area, Mapping):
        return []
    cards = area.get("cards")
    return list(cards) if isinstance(cards, Sequence) else []


#: Названия рук в игре пишутся по-разному в разных местах, поэтому
#: сопоставляем по «схлопнутому» виду: `Three of a Kind` -> `threeofakind`.
def _squash(name: str) -> str:
    return "".join(char for char in name.lower() if char.isalnum())


_HAND_BY_NAME = {_squash(hand.name): hand for hand in HandType}


def _parse_hands(payload: Any, unknown: list[str]) -> dict[HandType, PokerHandInfo]:
    if not isinstance(payload, Mapping):
        return {}
    result: dict[HandType, PokerHandInfo] = {}
    for name, info in payload.items():
        hand_type = _HAND_BY_NAME.get(_squash(str(name)))
        if hand_type is None:
            unknown.append(f"hand:{name}")
            continue
        if not isinstance(info, Mapping):
            continue
        result[hand_type] = PokerHandInfo(
            level=int(info.get("level", 1)),
            chips=int(info.get("chips", 0)),
            mult=int(info.get("mult", 0)),
            played=int(info.get("played", 0)),
            played_this_round=int(info.get("played_this_round", 0)),
        )
    return result


def _parse_one_blind(blind: Mapping[str, Any]) -> BlindInfo:
    return BlindInfo(
        kind=str(blind.get("type", "")),
        name=str(blind.get("name", "")),
        effect=str(blind.get("effect", "")),
        required_score=int(blind.get("score", 0)),
        status=str(blind.get("status", "")),
        tag_name=str(blind.get("tag_name", "")),
        tag_effect=str(blind.get("tag_effect", "")),
    )


def _parse_blind(payload: Any) -> BlindInfo | None:
    """Текущий блайнд — тот, что помечен статусом `CURRENT`."""
    if not isinstance(payload, Mapping):
        return None
    for blind in payload.values():
        if isinstance(blind, Mapping) and blind.get("status") == "CURRENT":
            return _parse_one_blind(blind)
    return None


def _parse_blinds_map(payload: Any) -> dict[str, BlindInfo]:
    """Все три блайнда анте — ключи `small`/`big`/`boss`, не только текущий.

    На экране выбора блайнда (`BLIND_SELECT`) `_parse_blind` выше вернёт
    `None` (статуса `CURRENT` там ни у кого нет), а требования и теги всех
    трёх уже известны — это то, на чём считается совет по скипу.
    """
    if not isinstance(payload, Mapping):
        return {}
    result: dict[str, BlindInfo] = {}
    for key in ("small", "big", "boss"):
        blind = payload.get(key)
        if isinstance(blind, Mapping):
            result[key] = _parse_one_blind(blind)
    return result


def _parse_shop_item(payload: Mapping[str, Any], unknown: list[str]) -> ShopItem:
    modifier = payload.get("modifier")
    cost = payload.get("cost")
    value = payload.get("value")
    return ShopItem(
        key=str(payload.get("key", "")),
        label=str(payload.get("label", "")),
        kind=str(payload.get("set", "")),
        price=int(cost.get("buy", 0)) if isinstance(cost, Mapping) else 0,
        effect=str(value.get("effect", "")) if isinstance(value, Mapping) else "",
        edition=_pick(modifier.get("edition"), Edition, "edition", unknown)
        if isinstance(modifier, Mapping)
        else Edition.BASE,
    )


def _parse_shop_area(area: Any, unknown: list[str]) -> tuple[ShopItem, ...]:
    """Один и тот же разбор для `shop`/`vouchers`/`packs` — три раздельные
    области мода (`GameState.shop`/`shop_vouchers`/`shop_packs`), непустые
    только в фазе `SHOP`."""
    return tuple(_parse_shop_item(raw, unknown) for raw in _area_cards(area))


def parse_game_state(payload: Mapping[str, Any]) -> GameState:
    """Разобрать ответ метода `gamestate` в наше состояние.

    Ничего не выбрасывает на незнакомых значениях: они собираются в
    `unknown_keys`, и состояние помечается неточным.
    """
    unknown: list[str] = []

    hand: list[Card] = []
    for raw in _area_cards(payload.get("hand")):
        card = _parse_playing_card(raw, unknown)
        if card is not None:
            hand.append(card)

    jokers_area = payload.get("jokers")
    jokers = [_parse_joker(raw, unknown) for raw in _area_cards(jokers_area)]
    joker_slots = jokers_area.get("limit") if isinstance(jokers_area, Mapping) else None
    round_info = payload.get("round") or {}

    #: Область `cards` — это буквально оставшаяся колода, а не весь деск:
    #: `hand.count + cards.count` совпадает с размером всей колоды. Именно
    #: это нужно для точного EV сброса (`solver/discard.py`). Отсутствие
    #: области (старый мод, другая фаза) отличаем от пустой колоды: пустой
    #: список при отсутствующем ключе означал бы «доборов нет», хотя на
    #: самом деле мы просто не знаем колоду.
    cards_area = payload.get("cards")
    deck: tuple[Card, ...] | None = None
    if isinstance(cards_area, Mapping):
        parsed_deck: list[Card] = []
        for raw in _area_cards(cards_area):
            card = _parse_playing_card(raw, unknown)
            if card is not None:
                parsed_deck.append(card)
        deck = tuple(parsed_deck)

    #: Полный состав колоды восстановим точно только в узком случае: пока за
    #: раунд ничего не сыграно и не сброшено, `hand ∪ cards` и есть вся
    #: колода. Стоит сыграть или сбросить хоть раз — часть карт уходит в
    #: стопку, которую мод не показывает ни в одной области, и равенство
    #: перестаёт быть точным.
    round_is_fresh = (
        int(round_info.get("hands_played", 0)) == 0 and int(round_info.get("discards_used", 0)) == 0
    )
    full_deck: tuple[Card, ...] | None = None
    if deck is not None and round_is_fresh:
        full_deck = tuple(hand) + deck

    return GameState(
        phase=str(payload.get("state", "UNKNOWN")),
        ante=int(payload.get("ante_num", 1)),
        round_number=int(payload.get("round_num", 1)),
        money=int(payload.get("money", 0)),
        hand=tuple(hand),
        jokers=tuple(jokers),
        hand_info=_parse_hands(payload.get("hands"), unknown),
        blind=_parse_blind(payload.get("blinds")),
        blinds=_parse_blinds_map(payload.get("blinds")),
        shop=_parse_shop_area(payload.get("shop"), unknown),
        shop_vouchers=_parse_shop_area(payload.get("vouchers"), unknown),
        shop_packs=_parse_shop_area(payload.get("packs"), unknown),
        deck_type=str(payload["deck"]) if payload.get("deck") else None,
        deck=deck,
        full_deck=full_deck,
        hands_left=int(round_info.get("hands_left", 0)),
        discards_left=int(round_info.get("discards_left", 0)),
        hands_played=int(round_info.get("hands_played", 0)),
        chips_scored=int(round_info.get("chips", 0)),
        joker_slots=int(joker_slots) if joker_slots is not None else None,
        unknown_keys=tuple(unknown),
    )


class ModBridge:
    """Соединение с работающей игрой.

    Игра должна быть запущена вместе с модом: `uvx balatrobot serve`.
    """

    def __init__(
        self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._next_id = 0

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def call(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        """Вызвать метод API и вернуть поле `result`."""
        self._next_id += 1
        request_body: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "id": self._next_id,
        }
        if params:
            request_body["params"] = dict(params)

        request = urllib.request.Request(
            self.url,
            data=json.dumps(request_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as error:
            raise NotConnectedError(
                f"мод не отвечает на {self.url}: {error}. "
                "Игра запущена через `uvx balatrobot serve`?"
            ) from error
        except json.JSONDecodeError as error:
            raise ModBridgeError(f"мод вернул не JSON: {error}") from error

        if "error" in payload:
            error_body = payload["error"] or {}
            raise RpcError(
                int(error_body.get("code", -1)),
                str(error_body.get("message", "неизвестная ошибка")),
                error_body.get("data"),
            )
        return payload.get("result")

    def is_alive(self) -> bool:
        """Отвечает ли мод. Не бросает исключений — это проверка, а не действие."""
        try:
            return bool(self.call("health"))
        except ModBridgeError:
            return False

    def raw_game_state(self) -> Mapping[str, Any]:
        """Состояние как есть — нужно для записи эталонных случаев."""
        result = self.call("gamestate")
        if not isinstance(result, Mapping):
            raise ModBridgeError(f"gamestate вернул не объект: {type(result).__name__}")
        return result

    def game_state(self) -> GameState:
        """Текущее состояние в наших типах."""
        return parse_game_state(self.raw_game_state())

    def play(self, indices: Sequence[int]) -> GameState:
        """Сыграть карты по индексам в руке (нумерация с нуля)."""
        return parse_game_state(self.call("play", {"cards": list(indices)}))

    def discard(self, indices: Sequence[int]) -> GameState:
        """Сбросить карты по индексам в руке (нумерация с нуля)."""
        return parse_game_state(self.call("discard", {"cards": list(indices)}))
