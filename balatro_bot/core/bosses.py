"""Каталог боссовых блайндов — что реально меняют правила игры, не только chips/mult.

Выписано из исходника игры (`Balatro.love`): `game.lua` — таблица `P_BLINDS` с `bl_*`
ключами (28 боссов — `bl_small`/`bl_big` туда не входят, это обычные блайнды, не боссы);
`blind.lua` — что каждый эффект реально делает (`Blind:debuff_hand`/`modify_hand`/
`press_play`/`set_blind`/`disable`, дёргаются по `self.name`, английскому имени из
`game.lua`, не зависящему от локали — то же имя мод отдаёт в `BlindInfo.name`);
`functions/state_events.lua` — довесок для `The Serpent`. Тот же принцип, что для
`core/tags.py`/`_JOKER_RARITY`/`_DECK_STARTING_SIZE`: не по памяти и не по статичному
тексту, а по реальному коду игры.

`summary` — что босс **механически** делает, без оценки последствий (тот же принцип,
что `TagEffect.summary`). Показывать игроку эффект как есть уже умеет мод
(`BlindInfo.effect`) — каталог здесь не для того, чтобы пересказать то же самое текстом,
а чтобы **знать структурно**, какие боссы вообще меняют правила розыгрыша (не только
дебаффят карты по масти/рангу — это уже общий случай, `Card.debuffed`, отдельного учёта
не требует).

`restricts_legal_plays` — честная, узкая пометка: может ли из-за этого босса подмножество
карт, которое `rank_plays` в остальном честно посчитал бы лучшим, оказаться физически
нелегальным ходом (мод откажет). Сейчас это `The Mouth` (только один тип руки за раунд),
`The Eye` (нельзя повторять уже сыгранный тип руки) и `The Psychic` (нельзя играть меньше
5 карт) — единственные три, где ограничение бьёт по *составу конкретного розыгрыша*, а не
по числу попыток (`The Water`/`The Needle` уже честно отражены живыми
`discards_left`/`hands_left` из мода — фильтровать нечего) и не по картам как таковым
(суть-дебаффы — общий случай `Card.debuffed`). Сам фильтр в `solver/play.py` — следующий
шаг (раздел 6 плана, «Автопилот», п. 9.5): каталог обязан появиться первым, чтобы было что
фильтровать по имени, а не гадать.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = ["BOSSES", "BossEffect", "is_known_boss"]


@dataclass(frozen=True, slots=True)
class BossEffect:
    """Структурное описание боссового блайнда: что происходит, а не что с этим делать."""

    key: str
    name: str
    summary: str

    restricts_legal_plays: bool = False
    """Может ли этот босс сделать честно лучший по `rank_plays` розыгрыш нелегальным
    ходом — см. модульный докстринг. `False` не значит «босс безобиден», только то, что
    он не бьёт по составу конкретного розыгрыша карт."""


#: Ключ — `bl_*` из `game.lua`'s `P_BLINDS`. Имя (`name`) совпадает с тем, что мод
#: присылает в `BlindInfo.name` (английский идентификатор `self.name` игры, тот же,
#: по которому дёргается вся логика в `blind.lua` — не зависит от локали интерфейса).
BOSSES: Final[dict[str, BossEffect]] = {
    "bl_ox": BossEffect(
        "bl_ox",
        "The Ox",
        "розыгрыш типа руки, который чаще всего играли за весь ран, обнуляет все деньги",
    ),
    "bl_hook": BossEffect(
        "bl_hook",
        "The Hook",
        "после каждого розыгрыша руки автоматически сбрасывает 2 случайные карты из руки",
    ),
    "bl_mouth": BossEffect(
        "bl_mouth",
        "The Mouth",
        "за весь раунд можно играть только один тип руки — первый сыгранный тип "
        "фиксируется, остальные становятся нелегальным ходом",
        restricts_legal_plays=True,
    ),
    "bl_fish": BossEffect(
        "bl_fish",
        "The Fish",
        "после каждого розыгрыша добор ложится рубашкой вверх — не меняет состав руки, "
        "только видимость на экране",
    ),
    "bl_club": BossEffect(
        "bl_club", "The Club", "все карты трефовой масти дебаффнуты (общий случай Card.debuffed)"
    ),
    "bl_manacle": BossEffect(
        "bl_manacle",
        "The Manacle",
        "размер руки на весь раунд −1 — уже отражено количеством карт в живом `GameState.hand`",
    ),
    "bl_tooth": BossEffect(
        "bl_tooth", "The Tooth", "за каждую сыгранную карту −$1 (не влияет на счёт, только деньги)"
    ),
    "bl_wall": BossEffect(
        "bl_wall",
        "The Wall",
        "обычный блайнд, просто с более высоким требованием (×4 к базовому) — "
        "особых правил розыгрыша нет",
    ),
    "bl_house": BossEffect(
        "bl_house",
        "The House",
        "первая рука за раунд раздаётся рубашкой вверх — не меняет состав руки, только видимость",
    ),
    "bl_mark": BossEffect(
        "bl_mark",
        "The Mark",
        "все карты-картинки раздаются рубашкой вверх — не меняет состав руки, только видимость",
    ),
    "bl_final_bell": BossEffect(
        "bl_final_bell",
        "Cerulean Bell",
        "одна случайная карта в руке обязана быть включена в каждый розыгрыш",
    ),
    "bl_wheel": BossEffect(
        "bl_wheel",
        "The Wheel",
        "шанс 1 из 7, что добранная карта останется рубашкой вверх — не меняет состав руки, "
        "только видимость",
    ),
    "bl_arm": BossEffect(
        "bl_arm",
        "The Arm",
        "каждый розыгрыш типа руки выше первого уровня НАВСЕГДА понижает его уровень на 1 "
        "(`level_up_hand(..., -1)` в исходнике — тот же счётчик, что у Planet-карт)",
    ),
    "bl_psychic": BossEffect(
        "bl_psychic",
        "The Psychic",
        "нельзя играть меньше 5 карт за раз",
        restricts_legal_plays=True,
    ),
    "bl_goad": BossEffect(
        "bl_goad", "The Goad", "все карты пиковой масти дебаффнуты (общий случай Card.debuffed)"
    ),
    "bl_water": BossEffect(
        "bl_water",
        "The Water",
        "сбросов на весь раунд — ноль, уже отражено живым `GameState.discards_left`",
    ),
    "bl_eye": BossEffect(
        "bl_eye",
        "The Eye",
        "за раунд нельзя повторно играть уже сыгранный тип руки",
        restricts_legal_plays=True,
    ),
    "bl_plant": BossEffect(
        "bl_plant", "The Plant", "все карты-картинки дебаффнуты (общий случай Card.debuffed)"
    ),
    "bl_needle": BossEffect(
        "bl_needle",
        "The Needle",
        "за весь раунд можно сыграть только одну руку, уже отражено живым `GameState.hands_left`",
    ),
    "bl_head": BossEffect(
        "bl_head", "The Head", "все карты червовой масти дебаффнуты (общий случай Card.debuffed)"
    ),
    "bl_final_leaf": BossEffect(
        "bl_final_leaf",
        "Verdant Leaf",
        "все игральные карты дебаффнуты, пока за этот раунд не продан хотя бы один джокер",
    ),
    "bl_final_vessel": BossEffect(
        "bl_final_vessel",
        "Violet Vessel",
        "обычный блайнд, просто с очень высоким требованием (×6 к базовому) — "
        "особых правил розыгрыша нет",
    ),
    "bl_window": BossEffect(
        "bl_window",
        "The Window",
        "все карты бубновой масти дебаффнуты (общий случай Card.debuffed)",
    ),
    "bl_serpent": BossEffect(
        "bl_serpent",
        "The Serpent",
        "после первого розыгрыша или сброса за раунд каждый следующий добор — не больше "
        "3 карт вместо полной руки",
    ),
    "bl_pillar": BossEffect(
        "bl_pillar",
        "The Pillar",
        "карты, уже сыгранные ранее в этом анте, дебаффнуты на весь ант "
        "(общий случай Card.debuffed, только с историей на уровне анте, а не раунда)",
    ),
    "bl_flint": BossEffect(
        "bl_flint",
        "The Flint",
        "базовые фишки и множитель руки уполовинены (`floor(x*0.5+0.5)`, минимум "
        "1 у множителя и 0 у фишек) — не реализовано в `core/scoring.py`, см. раздел 8.3",
    ),
    "bl_final_acorn": BossEffect(
        "bl_final_acorn",
        "Amber Acorn",
        "в начале раунда все джокеры переворачиваются рубашкой вверх и тасуются "
        "в случайном порядке — реальный порядок джокеров перестаёт быть тем, что видел игрок",
    ),
    "bl_final_heart": BossEffect(
        "bl_final_heart",
        "Crimson Heart",
        "каждый раунд один случайный джокер дебаффится игрой (не выбором игрока)",
    ),
}


def is_known_boss(name: str) -> bool:
    """Известен ли босс по имени, которое присылает мод (`BlindInfo.name`)."""
    return any(boss.name == name for boss in BOSSES.values())
