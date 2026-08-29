"""Джокеры: протокол, реестр реализаций и сборка по состоянию игры.

Джокер — это функция реакции на события подсчёта, а не запись в таблице.
Такая форма выбрана ради тех джокеров, которые ломают любую табличную
схему: `Blueprint` копирует соседа, `Mime` заставляет карты срабатывать
повторно, `Four Fingers` меняет сами правила распознавания руки.

Важное различие, которое легко упустить:

- джокер **известен** — есть в справочнике `catalogue`, мы знаем его текст;
- джокер **реализован** — есть класс, считающий его эффект.

Первое без второго не даёт права молчать: нереализованный джокер помечает
расчёт неточным ровно так же, как незнакомый.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from balatro_bot.core.cards import Edition
from balatro_bot.core.hands import HandModifiers
from balatro_bot.core.state import GameState, JokerCard

if TYPE_CHECKING:
    from balatro_bot.core.scoring import Effect, Event, ScoreContext

__all__ = [
    "REGISTRY",
    "BaseJoker",
    "Joker",
    "UnimplementedJoker",
    "build_jokers",
    "implemented_keys",
    "modifiers_from",
    "register",
]


@runtime_checkable
class Joker(Protocol):
    """Что обязан уметь джокер."""

    card: JokerCard

    @property
    def key(self) -> str: ...

    @property
    def name(self) -> str: ...

    def react(self, event: Event, ctx: ScoreContext) -> Iterable[Effect]:
        """Ответить эффектами на событие подсчёта."""
        ...


class BaseJoker:
    """Общая часть: имя, издание и молчание по умолчанию."""

    def __init__(self, card: JokerCard) -> None:
        self.card = card

    @property
    def key(self) -> str:
        return self.card.key

    @property
    def name(self) -> str:
        return self.card.label or self.card.key

    @property
    def edition(self) -> Edition:
        return self.card.edition

    def react(self, event: Event, ctx: ScoreContext) -> Iterable[Effect]:
        return ()

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.key}>"


class UnimplementedJoker(BaseJoker):
    """Джокер, эффект которого ещё не написан.

    Ничего не считает, но обязан отметиться: иначе бот выдаст правдоподобное
    и неверное число, а это худший исход для советника.
    """

    def react(self, event: Event, ctx: ScoreContext) -> Iterable[Effect]:
        from balatro_bot.core.scoring import JokerTurn

        if isinstance(event, JokerTurn) and event.joker is self:
            ctx.mark_unknown(f"джокер не реализован: {self.key}")
        return ()


#: Ключ джокера -> как построить его реализацию.
REGISTRY: dict[str, Callable[[JokerCard], Joker]] = {}


def register(*keys: str) -> Callable[[Callable[[JokerCard], Joker]], Callable[[JokerCard], Joker]]:
    """Привязать реализацию к ключам джокеров."""

    def decorate(factory: Callable[[JokerCard], Joker]) -> Callable[[JokerCard], Joker]:
        for key in keys:
            REGISTRY[key] = factory
        return factory

    return decorate


def build_jokers(state: GameState) -> tuple[Joker, ...]:
    """Собрать реализации по джокерам из состояния, сохраняя порядок слотов."""
    from balatro_bot.core.jokers import implementations  # noqa: F401 — регистрация

    return tuple(REGISTRY.get(card.key, UnimplementedJoker)(card) for card in state.jokers)


def modifiers_from(jokers: Iterable[Joker]) -> HandModifiers:
    """Собрать правила распознавания руки, которые меняют джокеры.

    Модуль `hands` о джокерах не знает — он принимает абстрактные флаги,
    и выставляются они здесь.
    """
    # Отключённый джокер (`JokerCard.debuffed`) не меняет и правил
    # распознавания руки — как и любого другого своего эффекта.
    keys = {joker.key for joker in jokers if not joker.card.debuffed}
    return HandModifiers(
        four_fingers="j_four_fingers" in keys,
        shortcut="j_shortcut" in keys,
        smeared="j_smeared" in keys,
        splash="j_splash" in keys,
        pareidolia="j_pareidolia" in keys,
        chicot="j_chicot" in keys,
        oops="j_oops" in keys,
    )


def implemented_keys() -> frozenset[str]:
    """Ключи джокеров, для которых есть реализация."""
    from balatro_bot.core.jokers import implementations  # noqa: F401 — регистрация

    return frozenset(REGISTRY)
