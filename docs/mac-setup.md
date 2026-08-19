# Запуск на Mac: пошагово

Игру скачивать и распаковывать не нужно — она у тебя уже есть в Steam.
Устанавливаются три вещи поверх неё: инжектор, загрузчик модов и сам мод.

## Сразу о главном: две разные папки

Их постоянно путают, потому что обе называются `Balatro` и обе лежат
в `Application Support`.

| Что | Где | Что туда кладём |
| --- | --- | --- |
| **Папка игры** (Steam) | `~/Library/Application Support/Steam/steamapps/common/Balatro/` | `liblovely.dylib` |
| **Папка сохранений** | `~/Library/Application Support/Balatro/Mods/` | `smods/`, `balatrobot/` |

Обе скрыты в Finder. Показать: `Shift-Cmd-.`

Удобно один раз задать переменные и дальше копировать команды как есть:

```bash
GAME=~/"Library/Application Support/Steam/steamapps/common/Balatro"
MODS=~/"Library/Application Support/Balatro/Mods"
mkdir -p "$MODS"
ls "$GAME"      # должен быть виден Balatro.app
```

## Шаг 0. Подготовка

```bash
uname -m                                        # arm64 = Apple Silicon, x86_64 = Intel
uv --version || curl -LsSf https://astral.sh/uv/install.sh | sh
```

Обнови Balatro в Steam. Steamodded поддерживает только актуальную версию —
на старой моды просто не загрузятся.

## Шаг 1. Lovely Injector

Инжектор Lua, без него моды не подключаются. Нужна версия 0.8.0+,
[страница релизов](https://github.com/ethangreen-dev/lovely-injector/releases).

Качай архив под свой процессор:

- Apple Silicon → `lovely-aarch64-apple-darwin.tar.gz`
- Intel → `lovely-x86_64-apple-darwin.tar.gz`

```bash
cd ~/Downloads
tar -xzf lovely-aarch64-apple-darwin.tar.gz     # подставь своё имя файла
cp liblovely.dylib "$GAME/"
ls "$GAME/liblovely.dylib"                      # проверка: файл на месте
```

Второй файл из архива, `run_lovely_macos.sh`, **не нужен**: запускать игру
будет CLI мода, и внедрение он делает сам.

## Шаг 2. Steamodded

Загрузчик модов, нужна версия 1.0.0-beta-1221a+.
На [странице релизов](https://github.com/Steamodded/smods/releases) бери
**Source code (zip)**, распакуй и положи содержимое в `$MODS/smods`:

```bash
ls "$MODS/smods"        # внутри должны быть .lua файлы загрузчика
```

Итоговая раскладка:

```
~/Library/Application Support/Balatro/Mods/
├── smods/
└── balatrobot/          # следующий шаг
```

## Шаг 3. Мод BalatroBot

Скачай релиз с [releases](https://github.com/coder/balatrobot/releases)
и положи так, чтобы получилось:

```
$MODS/balatrobot/
├── balatrobot.json
├── balatrobot.lua
└── src/lua/
```

```bash
ls "$MODS/balatrobot/balatrobot.lua"    # проверка
```

## Шаг 4. Запуск игры

**Не через Steam.** На macOS в клиенте Steam есть баг, из-за которого
внедрение не срабатывает — это написано прямо в документации Lovely.
Игру запускает CLI мода:

```bash
uvx balatrobot serve
```

Он найдёт `Balatro.app/Contents/MacOS/love` и `liblovely.dylib` в папке игры,
подставит `DYLD_INSERT_LIBRARIES` и стартует игру с JSON-RPC сервером
на `127.0.0.1:12346`.

Если пути нестандартные, их можно задать явно:
`uvx balatrobot serve --love-path ... --lovely-path ...`

Проверка, что сервер жив (игра при этом запущена):

```bash
curl -X POST http://127.0.0.1:12346 \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "health", "id": 1}'
```

Ожидаемо: `{"jsonrpc":"2.0","result":{"status":"ok"},"id":1}`

## Шаг 5. Проверка нашим ботом

Начни ран и дойди до выбора карт (не главное меню). Затем из каталога
этого репозитория:

```bash
uv run balatro-bot doctor
```

Пример вывода:

```
связь есть

фаза:        SELECTING_HAND
анте/раунд:  1 / 2
деньги:      $12
блайнд:      Big Blind (BIG), нужно 450
осталось:    рук 3, сбросов 2
рука:        AH KH QH 7C 7D(B) 3S 2S(x) TD(S)
джокеры:
  1. Joker [j_joker]
  2. Blueprint [j_blueprint]
значения рук: от игры

расчёт по этому состоянию будет точным
```

Скобки в записи руки — пометки: `(B)` улучшение Bonus, `(S)` Stone,
`(x)` карта отключена боссом.

## Шаг 6. Эталонные случаи

Играй как обычно. Перед тем как разыграть интересную руку:

```bash
uv run balatro-bot record flush-with-blueprint
```

Состояние ляжет в `tests/golden/`. **Разыграй руку и допиши рядом счёт,
который показала игра** — без него случай бесполезен.

Ценнее всего руки с джокерами, меняющими правила: `Blueprint`, `Mime`,
`Four Fingers`, `Shortcut`, `Smeared Joker`, и карты с улучшениями и изданиями.

## Про достижения

Steamodded по умолчанию гасит достижения Steam — защита от случайной
накрутки. Вернуть: в игре `Mods → config`. Учти, что тумблер снимает
защиту и для сид-ранов. Если достижения важны — заведи отдельный профиль.

## Если не работает

| Симптом | Что делать |
| --- | --- |
| `Connection refused` | Игра не запущена, либо запущена через Steam вместо `uvx balatrobot serve` |
| `liblovely.dylib not found` | Файл лёг не в папку игры, а в папку сохранений — это разные места, см. таблицу вверху |
| `LOVE executable not found` | Нестандартный путь установки Steam, задай `--love-path` |
| Моды не грузятся | Balatro не обновлён, либо `smods` распакован уровнем глубже (внутри лежит ещё одна папка) |
| macOS ругается на неподписанную библиотеку | Не описано в документации Lovely, но встречается: `xattr -d com.apple.quarantine "$GAME/liblovely.dylib"` |
| Порт занят | `uvx balatrobot serve --port 12347`, затем `uv run balatro-bot doctor --port 12347` |
| `doctor`: «расчёт будет НЕТОЧНЫМ» | Штатно: эффекты джокеров ещё не реализованы, это Фаза 3 |

Застрял — пришли вывод команды, разберёмся.
