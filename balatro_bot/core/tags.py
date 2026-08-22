"""Каталог тегов — что реально происходит при скипе блайнда.

Выписано из исходника игры (`Balatro.love`: `game.lua` — таблица `P_CENTER_POOLS.Tag`
с `tag_*` ключами и их `config`; `tag.lua` — что каждый `config.type` делает
в `Tag:apply_to_run`), а не по памяти или из статичного текста каталога —
тот же принцип, что для `_JOKER_RARITY`/`_DECK_STARTING_SIZE` в
`core/jokers/implementations.py` (см. `CLAUDE.md`, раздел «Adding a Joker»).

`summary` — что тег **механически** делает, без оценки полезности: сколько
это стоит в очках или деньгах — решает `solver/skip.py._tag_dollars`, и то
не для всех тегов (см. там же, почему часть тегов принципиально не
переводится в точное число прямо сейчас — им нужен счётчик уровня рана,
которого мод не присылает)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = ["TAGS", "TagEffect", "is_known_tag"]


@dataclass(frozen=True, slots=True)
class TagEffect:
    """Структурное описание тега: что происходит, а не сколько это стоит."""

    key: str
    name: str
    summary: str


#: Ключ — `tag_*` из `game.lua`. Имя (`name`) совпадает с тем, что мод
#: присылает в `Blind.tag_name`, поэтому по нему и сопоставляем тег живому
#: состоянию (см. `solver/skip.py._lookup_tag`), а не по русскому названию —
#: оно зависит от локали игры, как и текст `tag_effect`.
TAGS: Final[dict[str, TagEffect]] = {
    "tag_uncommon": TagEffect(
        "tag_uncommon",
        "Uncommon Tag",
        "следующий созданный джокер в магазине — гарантированно Uncommon",
    ),
    "tag_rare": TagEffect(
        "tag_rare", "Rare Tag", "следующий созданный джокер в магазине — гарантированно Rare"
    ),
    "tag_negative": TagEffect(
        "tag_negative",
        "Negative Tag",
        "следующий купленный в магазине джокер получает издание Negative бесплатно",
    ),
    "tag_foil": TagEffect(
        "tag_foil",
        "Foil Tag",
        "следующий купленный в магазине джокер получает издание Foil бесплатно",
    ),
    "tag_holo": TagEffect(
        "tag_holo",
        "Holographic Tag",
        "следующий купленный в магазине джокер получает издание Holographic бесплатно",
    ),
    "tag_polychrome": TagEffect(
        "tag_polychrome",
        "Polychrome Tag",
        "следующий купленный в магазине джокер получает издание Polychrome бесплатно",
    ),
    "tag_investment": TagEffect(
        "tag_investment",
        "Investment Tag",
        "после победы над Boss Blind этого анте — деньги (сумма из `config.dollars`, сейчас $25)",
    ),
    "tag_voucher": TagEffect(
        "tag_voucher", "Voucher Tag", "в следующий магазин добавляется один ваучер"
    ),
    "tag_boss": TagEffect(
        "tag_boss", "Boss Tag", "перебрасывает Boss Blind этого анте на другой (реролл босса)"
    ),
    "tag_standard": TagEffect(
        "tag_standard", "Standard Tag", "сразу открывается бесплатный Mega Standard Pack"
    ),
    "tag_charm": TagEffect(
        "tag_charm", "Charm Tag", "сразу открывается бесплатный Mega Arcana Pack"
    ),
    "tag_meteor": TagEffect(
        "tag_meteor", "Meteor Tag", "сразу открывается бесплатный Mega Celestial Pack"
    ),
    "tag_buffoon": TagEffect(
        "tag_buffoon", "Buffoon Tag", "сразу открывается бесплатный Mega Buffoon Pack"
    ),
    "tag_handy": TagEffect(
        "tag_handy",
        "Handy Tag",
        "деньги: $1 за каждую руку, сыгранную за весь ран (счётчик уровня рана, "
        "не раунда — мод его не присылает, точное число недоступно)",
    ),
    "tag_garbage": TagEffect(
        "tag_garbage",
        "Garbage Tag",
        "деньги: $1 за каждый неиспользованный сброс за весь ран (тот же нюанс, "
        "что у Handy Tag — счётчик уровня рана, мод его не присылает)",
    ),
    "tag_ethereal": TagEffect(
        "tag_ethereal", "Ethereal Tag", "сразу открывается бесплатный обычный Spectral Pack"
    ),
    "tag_coupon": TagEffect(
        "tag_coupon",
        "Coupon Tag",
        "все начальные джокеры и паки в следующем магазине становятся бесплатными",
    ),
    "tag_double": TagEffect(
        "tag_double",
        "Double Tag",
        "следующий полученный тег (кроме ещё одного Double) срабатывает дважды",
    ),
    "tag_juggle": TagEffect(
        "tag_juggle", "Juggle Tag", "временно +3 к размеру руки на следующий раунд"
    ),
    "tag_d_six": TagEffect("tag_d_six", "D6 Tag", "первый реролл в следующем магазине бесплатный"),
    "tag_top_up": TagEffect(
        "tag_top_up",
        "Top-up Tag",
        "сразу создаёт до 2 обычных (Common) джокеров, если есть свободные слоты",
    ),
    "tag_skip": TagEffect(
        "tag_skip",
        "Skip Tag",
        "деньги: $5 за каждый скип блайнда за весь ран, включая этот (счётчик "
        "уровня рана, мод его не присылает — точное число недоступно)",
    ),
    "tag_orbital": TagEffect(
        "tag_orbital", "Orbital Tag", "поднимает уровень случайного типа руки на 3 сразу"
    ),
    "tag_economy": TagEffect(
        "tag_economy",
        "Economy Tag",
        "деньги: удваивает текущий баланс, прибавка не больше $40 (`min(40, деньги))`)",
    ),
}


def is_known_tag(name: str) -> bool:
    """Известен ли тег по имени, которое присылает мод (`Blind.tag_name`)."""
    return any(tag.name == name for tag in TAGS.values())
