"""Совет по покупкам в магазине — второй кусок Фазы 8 плана («Стратегия рана»).

Та же логика, что у `solver/skip.py`: не гадать эффект случайного будущего
магазина, а честно оценить тот, что игра уже показала (`GameState.shop`,
`shop_vouchers`, `shop_packs` — заполняются только в фазе `SHOP`).

Джокеры — единственный тип предмета, для которого можно посчитать реальный
прирост счёта: у нас уже есть точный движок подсчёта (`core/scoring.py`).
Оценка идёт тем же способом, что перебор порядка джокеров
(`solver.play.rank_joker_orders`) — контрфактум: «насколько вырастет лучший
счёт, если добавить этого джокера к текущим», — только не на одной руке
игрока (её в фазе `SHOP` попросту нет: `GameState.hand` пуст), а по
нескольким представительным рукам из колоды. Это тот же принцип
сэмплирования, что в `solver/discard.py._representative_draws` — точный
`advise()` на каждой выборке, не приближённый подсчёт, приближена только
сама выборка рук, а не сам счёт.

Ваучеры и паки не переводятся в очки: ваучер — это постоянное изменение
правил рана (скидки, слоты, шансы), а не прибавка к конкретной руке, и
считать это тем же контрфактумом не на чем. Здесь честный текст важнее
выдуманного числа (раздел 8 CLAUDE.md — то же решение, что для тегов в
`core/tags.py`, только эффект уже даёт сама игра текстом, а не наша
таблица).

Поправка на экономику (раздел 8.1 плана, было отложено при закрытии
основной части Фазы 7): покупка джокера — это не только `item.price`
долларов, но и упущенные проценты в конце ближайшего раунда. Формула
процентов (`_interest`) выписана из исходника игры, не по памяти —
`functions/state_events.lua`: `interest_amount * min(floor(dollars/5),
interest_cap/5)`, с константами по умолчанию `interest_amount=1`,
`interest_cap=25` из `game.lua`'s `GAME_MOD.interest_cap`/`interest_amount`.
Это не сводится к самой оценке счёта (`expected_uplift`) — доллары и очки
несоизмеримы без произвольного курса обмена, тот же принцип, что и у
`core/tags.py`/`solver/skip.py`. `JokerOffer.interest_lost` — честная,
но заведомо **неполная** цифра: она про упущенные проценты только
ближайшего конца раунда, а не про весь остаток рана (для этого нужно было
бы знать число оставшихся раундов и весь будущий денежный поток — это уже
не размер задачи витрины магазина, а Фаза 9). Она также предполагает
`interest_cap=25` по умолчанию — `GameState` не хранит уже выкупленные
ваучеры (`Seed Money`/`Money Tree` поднимают потолок до $50/$100), поэтому
на раскачанной экономике эта цифра — не переоценка, а честная нижняя
граница. Единственное исключение, которое код различает явно, — `Green
Deck` (`deck_type == "GREEN"`), где `game.lua` отключает проценты вовсе
(`no_interest=true`): там `interest_lost` всегда 0, а не догадка."""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Final

from balatro_bot.core.cards import Card, standard_deck
from balatro_bot.core.catalogue import is_known_joker
from balatro_bot.core.state import GameState, JokerCard, ShopItem
from balatro_bot.solver.play import advise

__all__ = ["JokerOffer", "ShopAdvice", "evaluate_shop"]

#: Сколько представительных рук сэмплировать на джокера. Каждая — полный
#: точный `advise()` (перебор 218 подмножеств, ~13 мс) дважды — с текущими
#: джокерами и с добавленным кандидатом, поэтому цена растёт линейно с этим
#: числом: 12 × 2 × 13 мс ≈ 300 мс на джокера, разумно для захода в магазин
#: (нечастое событие, не полсекунды на каждый опрос `watch`, как у бросков
#: карт), но не бесплатно — потому и вынесено в константу, а не зашито.
SAMPLE_HANDS: Final[int] = 12

#: Столько карт добирается на пробную руку — как в реальной игре.
_HAND_SIZE: Final[int] = 8

#: Тот же принцип, что `solver.discard._SAMPLE_SEED`: результат должен быть
#: воспроизводимым при одном и том же состоянии, а не дребезжать между
#: вызовами.
_SAMPLE_SEED: Final[int] = 0

#: Формула и константы процентов на конец раунда — выписаны из
#: `functions/state_events.lua` игры, не по памяти:
#: `interest_amount * min(floor(dollars/5), interest_cap/5)`. Значения по
#: умолчанию (без выкупленных ваучеров) — из `game.lua`'s `GAME_MOD`.
#: `Seed Money`/`Money Tree` поднимают `interest_cap` до 50/100, но
#: `GameState` не хранит уже выкупленные ваучеры этого рана — числа ниже
#: поэтому дают нижнюю границу, а не переоценку, см. модульный докстринг.
_INTEREST_AMOUNT: Final[int] = 1
_INTEREST_CAP: Final[int] = 25
_INTEREST_STEP: Final[int] = 5

#: `Green Deck` (`b_green` в `game.lua`) отключает проценты полностью
#: (`config.no_interest = true`) — единственный отслеживаемый в `GameState`
#: (`deck_type`) случай, где реальный ответ — гарантированный ноль, а не
#: наше приближение по умолчанию.
_NO_INTEREST_DECK: Final[str] = "GREEN"


def _interest(money: int, deck_type: str | None) -> int:
    """Проценты, которые накапало бы в конце раунда при данной сумме денег."""
    if deck_type == _NO_INTEREST_DECK or money < _INTEREST_STEP:
        return 0
    return _INTEREST_AMOUNT * min(money // _INTEREST_STEP, _INTEREST_CAP // _INTEREST_STEP)


@dataclass(frozen=True, slots=True)
class JokerOffer:
    """Джокер на продажу — с попыткой оценить, насколько он поднимет счёт."""

    item: ShopItem
    affordable: bool
    has_slot: bool
    known: bool
    """Есть ли реализация эффекта (`core.catalogue.is_known_joker`). Если
    нет — оценивать нечем, `expected_uplift` остаётся `None`, честно."""

    expected_uplift: float | None
    """Средний прирост лучшего счёта по представительным рукам. `None` —
    джокер не реализован либо колода для сэмплирования пуста."""

    exact_deck: bool
    """Сэмплировали по настоящей колоде рана (`GameState.full_deck`, только
    в узком случае — раздел 8.2 плана) или по стандартным 52 картам."""

    samples: int
    """Сколько рук реально усреднено — 0, если оценка не считалась."""

    interest_lost: int
    """Упущенные проценты в конце ближайшего раунда, если купить именно
    этого джокера (`_interest(money) - _interest(money - price)`) — честная,
    но заведомо неполная цифра, см. модульный докстринг. Не переводится в
    единицы `expected_uplift` (доллары и очки несоизмеримы), показывается
    отдельно."""


@dataclass(frozen=True, slots=True)
class ShopAdvice:
    """Всё, что предлагает магазин прямо сейчас, разложенное по типам."""

    jokers: tuple[JokerOffer, ...]
    """Отсортированы по `expected_uplift` по убыванию; неоценённые — в конце."""

    vouchers: tuple[ShopItem, ...]
    packs: tuple[ShopItem, ...]
    money: int


def evaluate_shop(state: GameState, samples: int = SAMPLE_HANDS) -> ShopAdvice | None:
    """Собрать совет по всему, что предлагает магазин — или `None`, если
    магазин сейчас пуст (не в фазе `SHOP`, либо мод ничего не прислал)."""
    if not state.shop and not state.shop_vouchers and not state.shop_packs:
        return None

    deck_source = state.full_deck if state.full_deck else standard_deck()
    exact_deck = state.full_deck is not None

    offers = [
        _evaluate_joker_offer(state, item, deck_source, exact_deck, samples)
        for item in state.shop
        if item.kind == "JOKER"
    ]
    # Неоценённые (uplift=None) должны идти последними, а не просто с
    # произвольным "маленьким" числом — сортируем парой (есть ли оценка,
    # сама оценка), а не подставляем сентинел, который мог бы случайно
    # оказаться больше настоящего отрицательного прироста.
    offers.sort(
        key=lambda offer: (
            offer.expected_uplift is not None,
            offer.expected_uplift if offer.expected_uplift is not None else 0.0,
        ),
        reverse=True,
    )

    return ShopAdvice(
        jokers=tuple(offers),
        vouchers=state.shop_vouchers,
        packs=state.shop_packs,
        money=state.money,
    )


def _evaluate_joker_offer(
    state: GameState,
    item: ShopItem,
    deck_source: tuple[Card, ...],
    exact_deck: bool,
    samples: int,
) -> JokerOffer:
    affordable = state.money >= item.price
    has_slot = state.joker_slots is None or len(state.jokers) < state.joker_slots
    known = is_known_joker(item.key)
    interest_lost = _interest(state.money, state.deck_type) - _interest(
        state.money - item.price, state.deck_type
    )

    if not known or len(deck_source) < _HAND_SIZE:
        return JokerOffer(item, affordable, has_slot, known, None, exact_deck, 0, interest_lost)

    candidate = JokerCard(key=item.key, label=item.label, edition=item.edition)
    with_candidate = (*state.jokers, candidate)

    rng = random.Random(_SAMPLE_SEED)
    pool = list(deck_source)
    total_delta = 0.0
    for _ in range(samples):
        hand = tuple(rng.sample(pool, _HAND_SIZE))
        baseline = advise(replace(state, hand=hand, jokers=state.jokers), limit=1).best.score
        boosted = advise(replace(state, hand=hand, jokers=with_candidate), limit=1).best.score
        total_delta += boosted - baseline

    return JokerOffer(
        item, affordable, has_slot, known, total_delta / samples, exact_deck, samples, interest_lost
    )
