# Running on Mac: step by step

You don't need to download or unpack the game — you already have it on Steam.
Three things get installed on top of it: an injector, a mod loader, and the mod itself.

## The fast path

```bash
uv run balatro-bot install     # install everything
uvx balatrobot serve           # launch the game (not through Steam!)
uv run balatro-bot doctor      # check the connection, already in a round
```

The installer detects the CPU, finds the game directory (including one on an
external drive), downloads the latest releases of all three components, and
places them in the right directories. Before downloading it shows exactly what
it will fetch and from where, and asks for confirmation.

Useful flags:

| Flag | Purpose |
| --- | --- |
| `--dry-run` | show the plan and exit, touching nothing |
| `--check` | only verify what is already installed |
| `--yes` | don't ask for confirmation |
| `--game-dir PATH` | if Steam is in a non-standard location |

The installer runs nothing from what it downloads — it only unpacks, and it
checks file names inside the archives so nothing gets written outside the target
directory.

If it all went through, jump straight to [step 4](#step-4-launching-the-game).
If not — below are the same actions done by hand.

---

# Manual installation

You'll need this if the installer couldn't reach GitHub or something went wrong.

## First, the key point: two different folders

People confuse them constantly, because both are called `Balatro` and both live
in `Application Support`.

| What | Where | What goes there |
| --- | --- | --- |
| **Game folder** (Steam) | `~/Library/Application Support/Steam/steamapps/common/Balatro/` | `liblovely.dylib` |
| **Save folder** | `~/Library/Application Support/Balatro/Mods/` | `smods/`, `balatrobot/` |

Both are hidden in Finder. To show them: `Shift-Cmd-.`

It's convenient to set the variables once and then copy the commands as-is:

```bash
GAME=~/"Library/Application Support/Steam/steamapps/common/Balatro"
MODS=~/"Library/Application Support/Balatro/Mods"
mkdir -p "$MODS"
ls "$GAME"      # Balatro.app should be visible
```

## Step 0. Preparation

```bash
uname -m                                        # arm64 = Apple Silicon, x86_64 = Intel
uv --version || curl -LsSf https://astral.sh/uv/install.sh | sh
```

Update Balatro on Steam. Steamodded supports only the current version — on an
older one the mods simply won't load.

## Step 1. Lovely Injector

A Lua injector; without it the mods don't get hooked in. You need version 0.8.0+,
[releases page](https://github.com/ethangreen-dev/lovely-injector/releases).

Download the archive for your CPU:

- Apple Silicon → `lovely-aarch64-apple-darwin.tar.gz`
- Intel → `lovely-x86_64-apple-darwin.tar.gz`

```bash
cd ~/Downloads
tar -xzf lovely-aarch64-apple-darwin.tar.gz     # substitute your own file name
cp liblovely.dylib "$GAME/"
ls "$GAME/liblovely.dylib"                      # check: the file is in place
```

The second file in the archive, `run_lovely_macos.sh`, is **not needed**: the
mod's CLI will launch the game, and it does the injection itself.

## Step 2. Steamodded

The mod loader; you need version 1.0.0-beta-1221a+.
On the [releases page](https://github.com/Steamodded/smods/releases) take
**Source code (zip)**, unpack it, and put the contents into `$MODS/smods`:

```bash
ls "$MODS/smods"        # should contain the loader's .lua files
```

The resulting layout:

```
~/Library/Application Support/Balatro/Mods/
├── smods/
└── balatrobot/          # next step
```

## Step 3. The BalatroBot mod

Download a release from [releases](https://github.com/coder/balatrobot/releases)
and place it so that you get:

```
$MODS/balatrobot/
├── balatrobot.json
├── balatrobot.lua
└── src/lua/
```

```bash
ls "$MODS/balatrobot/balatrobot.lua"    # check
```

<a id="step-4-launching-the-game"></a>

## Step 4. Launching the game

**Not through Steam.** On macOS the Steam client has a bug that keeps the
injection from taking effect — this is stated directly in the Lovely docs.
The mod's CLI launches the game:

```bash
uvx balatrobot serve
```

It finds `Balatro.app/Contents/MacOS/love` and `liblovely.dylib` in the game
folder, sets `DYLD_INSERT_LIBRARIES`, and starts the game with a JSON-RPC server
on `127.0.0.1:12346`.

If the paths are non-standard, you can set them explicitly:
`uvx balatrobot serve --love-path ... --lovely-path ...`

To check the server is alive (with the game running):

```bash
curl -X POST http://127.0.0.1:12346 \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "health", "id": 1}'
```

Expected: `{"jsonrpc":"2.0","result":{"status":"ok"},"id":1}`

## Step 5. Checking with our bot

Start a run and get to the card-selection screen (not the main menu). Then, from
this repository's directory:

```bash
uv run balatro-bot doctor
```

Example output:

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

The brackets in the hand notation are enhancement markers (`B` Bonus, `M` Mult, `W` Wild,
`G` Glass, `T` Steel, `S` Stone, `$` Gold, `L` Lucky) and edition markers (`F` Foil,
`H` Holographic, `P` Polychrome, `N` Negative) in the same brackets, e.g. `TD(BF)` — Bonus
and Foil at once; an `x` in the same brackets means the card is disabled by the boss. The
seal is shown as a separate marker after the brackets: `!R` red, `!G` gold, `!U` blue,
`!P` purple — for example `TD(B)!R`. The same edition is also shown on the jokers themselves
in the `джокеры:` list — `(F)` next to the name.

## Step 6. The live advisor (`watch`)

`doctor` shows the state once. `watch` is the same thing, but it refreshes itself
as the game goes: you don't need to re-run the command after every move.

```bash
uv run balatro-bot watch
```

Keep this in a separate terminal window next to the game. The screen clears and
redraws only when the state actually changed (you played a hand, discarded,
entered the shop) — as long as nothing changed, nothing flickers.

Useful flags:

| Flag | Purpose |
| --- | --- |
| `--interval SEC` | how often to poll the mod (default 1 second) |
| `--explain` | show the score breakdown for the best option |
| `--top N` | how many options to show (default 5) |
| `--no-joker-order` | don't search joker orders — on by default (up to 720 permutations with 2+ jokers per poll; in `advise` it's the other way round, turned on with `--joker-order`) |
| `--no-discard` | don't consider discards in the merged action list — by default they are always there, together with plays, in one list sorted by descending score |

Stop at any moment with `Ctrl+C`. `watch` only reads state and presses nothing
for you: you play, it keeps the advice on screen.

## Step 7. Golden cases

Play as usual. Just before you play an interesting hand:

```bash
uv run balatro-bot record flush-with-blueprint
```

The state lands in `tests/golden/`. **Play the hand and write the score the game
showed next to it** — without that, the case is useless.

The most valuable hands are ones with rule-changing jokers: `Blueprint`, `Mime`,
`Four Fingers`, `Shortcut`, `Smeared Joker`, and cards with enhancements and editions.

## About achievements

Steamodded disables Steam achievements by default — protection against accidental
farming. To restore them: in-game, `Mods → config`. Note that the toggle also
removes the protection for seeded runs. If achievements matter to you — set up a
separate profile.

## If it doesn't work

| Symptom | What to do |
| --- | --- |
| `Connection refused` | The game isn't running, or it's running through Steam instead of `uvx balatrobot serve` |
| `liblovely.dylib not found` | The file went into the save folder, not the game folder — these are different places, see the table at the top |
| `LOVE executable not found` | Non-standard Steam install path, set `--love-path` |
| Mods don't load | Balatro isn't updated, or `smods` was unpacked one level too deep (another folder inside it) |
| macOS complains about an unsigned library | Not in the Lovely docs, but it happens: `xattr -d com.apple.quarantine "$GAME/liblovely.dylib"` |
| Port is taken | `uvx balatrobot serve --port 12347`, then `uv run balatro-bot doctor --port 12347` |
| The installer didn't find the game | `uv run balatro-bot install --game-dir PATH` |
| The installer couldn't reach GitHub | Install by hand using the steps above; the plan is visible via `--dry-run` |
| `doctor`: "расчёт будет НЕТОЧНЫМ" | Normal: joker effects aren't implemented yet, that's Phase 3 |

Stuck — send the command's output and we'll sort it out.
