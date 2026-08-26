"""Тесты каталога боссовых блайндов (`balatro_bot/core/bosses.py`).

Целостность захардкоженной таблицы — та же логика, что у `TestКаталогТегов`
в `test_tags.py`: один пропуск здесь тихо испортит любой будущий фильтр
нелегальных ходов, поэтому структура таблицы проверяется отдельно.
"""

from __future__ import annotations

from balatro_bot.core.bosses import BOSSES, is_known_boss

#: Все 28 `bl_*` ключей боссовых блайндов из `game.lua`'s `P_BLINDS`
#: (`bl_small`/`bl_big` туда не входят — это обычные блайнды, не боссы) —
#: независимый список для сверки, чтобы опечатка в `BOSSES` не прошла тест,
#: который сверяет саму себя с собой.
_EXPECTED_KEYS = frozenset(
    {
        "bl_ox",
        "bl_hook",
        "bl_mouth",
        "bl_fish",
        "bl_club",
        "bl_manacle",
        "bl_tooth",
        "bl_wall",
        "bl_house",
        "bl_mark",
        "bl_final_bell",
        "bl_wheel",
        "bl_arm",
        "bl_psychic",
        "bl_goad",
        "bl_water",
        "bl_eye",
        "bl_plant",
        "bl_needle",
        "bl_head",
        "bl_final_leaf",
        "bl_final_vessel",
        "bl_window",
        "bl_serpent",
        "bl_pillar",
        "bl_flint",
        "bl_final_acorn",
        "bl_final_heart",
    }
)

#: Три босса, чей эффект бьёт по составу конкретного розыгрыша карт (не по
#: числу попыток и не по мастям/рангам — это уже общий случай) — см.
#: модульный докстринг `core/bosses.py`.
_EXPECTED_RESTRICTING = frozenset({"bl_mouth", "bl_eye", "bl_psychic"})


class TestКаталогБоссов:
    def test_накрывает_все_28_боссов_ровно_один_раз(self) -> None:
        assert set(BOSSES) == _EXPECTED_KEYS
        assert len(BOSSES) == 28

    def test_ключ_словаря_совпадает_с_ключом_записи(self) -> None:
        for key, effect in BOSSES.items():
            assert effect.key == key

    def test_имена_уникальны(self) -> None:
        names = [effect.name for effect in BOSSES.values()]
        assert len(names) == len(set(names))

    def test_у_каждого_босса_есть_описание(self) -> None:
        assert all(effect.summary.strip() for effect in BOSSES.values())

    def test_ограничивающие_розыгрыш_боссы_помечены_ровно_эти_три(self) -> None:
        restricting = {key for key, effect in BOSSES.items() if effect.restricts_legal_plays}
        assert restricting == _EXPECTED_RESTRICTING


class TestIsKnownBoss:
    def test_известный_босс_по_имени_из_мода(self) -> None:
        assert is_known_boss("The Mouth") is True

    def test_неизвестное_имя(self) -> None:
        assert is_known_boss("Совершенно Новый Boss") is False

    def test_пустая_строка(self) -> None:
        assert is_known_boss("") is False
