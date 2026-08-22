"""Тесты каталога тегов (`balatro_bot/core/tags.py`).

Целостность захардкоженной таблицы — та же логика, что у `TestРедкостьДжокеров`
в `test_scoring.py`: один пропуск здесь тихо испортит совет по скипу, поэтому
структура таблицы проверяется отдельно от `solver/skip.py`.
"""

from __future__ import annotations

from balatro_bot.core.tags import TAGS, is_known_tag

#: Все `tag_*` ключи из `game.lua` (таблица тегов) — независимый список для
#: сверки, чтобы опечатка в `TAGS` не прошла тест, который сверяет саму себя
#: с собой.
_EXPECTED_KEYS = frozenset(
    {
        "tag_uncommon",
        "tag_rare",
        "tag_negative",
        "tag_foil",
        "tag_holo",
        "tag_polychrome",
        "tag_investment",
        "tag_voucher",
        "tag_boss",
        "tag_standard",
        "tag_charm",
        "tag_meteor",
        "tag_buffoon",
        "tag_handy",
        "tag_garbage",
        "tag_ethereal",
        "tag_coupon",
        "tag_double",
        "tag_juggle",
        "tag_d_six",
        "tag_top_up",
        "tag_skip",
        "tag_orbital",
        "tag_economy",
    }
)


class TestКаталогТегов:
    def test_накрывает_все_24_тега_ровно_один_раз(self) -> None:
        assert set(TAGS) == _EXPECTED_KEYS
        assert len(TAGS) == 24

    def test_ключ_словаря_совпадает_с_ключом_записи(self) -> None:
        for key, effect in TAGS.items():
            assert effect.key == key

    def test_имена_уникальны(self) -> None:
        names = [effect.name for effect in TAGS.values()]
        assert len(names) == len(set(names))

    def test_у_каждого_тега_есть_описание(self) -> None:
        assert all(effect.summary.strip() for effect in TAGS.values())


class TestIsKnownTag:
    def test_известный_тег_по_имени_из_мода(self) -> None:
        assert is_known_tag("Investment Tag") is True

    def test_неизвестное_имя(self) -> None:
        assert is_known_tag("Совершенно Новый Tag") is False

    def test_пустая_строка(self) -> None:
        assert is_known_tag("") is False
