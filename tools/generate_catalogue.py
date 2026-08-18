"""Генератор справочника игровых объектов из аннотаций мода BalatroBot.

Мод `coder/balatrobot` (MIT) держит полный перечень джокеров, расходников,
ваучеров и бустеров в виде аннотаций LuaLS в `src/lua/utils/enums.lua`.
Это машиночитаемый и уже выверенный источник, поэтому справочник берём
оттуда, а не выписываем руками.

Запуск:

    python tools/generate_catalogue.py путь/к/balatrobot/src/lua/utils/enums.lua

Результат пишется в `balatro_bot/core/catalogue.py`. Файл сгенерирован —
править его руками нельзя, только перегенерировать.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ANNOTATION = re.compile(r'^---\|\s*"([a-z]_\w+)"\s*#\s*(.+?)\s*$', re.MULTILINE)

GROUPS: dict[str, tuple[str, str]] = {
    "j": ("JOKERS", "Джокеры"),
    "c": ("CONSUMABLES", "Расходники: таро, планеты, спектральные"),
    "v": ("VOUCHERS", "Ваучеры"),
    "p": ("BOOSTERS", "Бустерные наборы"),
}

HEADER = '''"""Справочник игровых объектов Balatro. ФАЙЛ СГЕНЕРИРОВАН, НЕ ПРАВИТЬ РУКАМИ.

Источник: аннотации мода `coder/balatrobot` (лицензия MIT),
`src/lua/utils/enums.lua`. Перегенерация — `tools/generate_catalogue.py`.

Описания эффектов — игровой текст Balatro. Здесь он нужен для опознания
объектов по ключу и как основа для реализации эффектов в Фазе 3: сам по себе
текст ничего не считает, но позволяет отличить известный объект от
неизвестного, а значит честно пометить расчёт неточным.
"""

from __future__ import annotations

from typing import Final

__all__ = ["BOOSTERS", "CONSUMABLES", "JOKERS", "VOUCHERS", "describe", "is_known_joker"]

'''

FOOTER = '''

def is_known_joker(key: str) -> bool:
    """Есть ли джокер в справочнике.

    Незнакомый джокер — не сбой, а штатная ситуация: он помечает расчёт
    неточным, пока его эффект не реализован.
    """
    return key in JOKERS


def describe(key: str) -> str | None:
    """Описание эффекта по ключу объекта любого вида."""
    for table in (JOKERS, CONSUMABLES, VOUCHERS, BOOSTERS):
        if key in table:
            return table[key]
    return None
'''


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    source = Path(sys.argv[1])
    if not source.is_file():
        print(f"не найден файл аннотаций: {source}", file=sys.stderr)
        return 1

    entries = ANNOTATION.findall(source.read_text(encoding="utf-8"))
    if not entries:
        print(f"в {source} не нашлось ни одной аннотации — формат изменился?", file=sys.stderr)
        return 1

    buckets: dict[str, list[tuple[str, str]]] = {prefix: [] for prefix in GROUPS}
    for key, description in entries:
        prefix = key.split("_", 1)[0]
        if prefix in buckets:
            buckets[prefix].append((key, description))

    parts = [HEADER]
    for prefix, (name, comment) in GROUPS.items():
        rows = sorted(buckets[prefix])
        parts.append(f"#: {comment} ({len(rows)} шт.)\n")
        parts.append(f"{name}: Final[dict[str, str]] = {{\n")
        parts.extend(f"    {key!r}: {description!r},\n" for key, description in rows)
        parts.append("}\n\n")
    parts.append(FOOTER.lstrip("\n"))

    target = Path(__file__).resolve().parent.parent / "balatro_bot" / "core" / "catalogue.py"
    target.write_text("".join(parts), encoding="utf-8")

    counts = ", ".join(f"{GROUPS[p][0].lower()}: {len(b)}" for p, b in buckets.items())
    print(f"записан {target.relative_to(Path.cwd())} — {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
