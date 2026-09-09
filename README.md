# Bot for Roguelike — a Balatro helper

A bot for [Balatro](https://www.playbalatro.com/) that computes rather than guesses. It reads
the state of the current run and ranks every possible move with an exact score breakdown —
which cards to play, what to discard, what to buy in the shop. No ML, no heuristics: all 218
hand subsets are brute-forced in about 20 ms, and random effects are resolved by exact
enumeration of outcomes, not sampling.

It runs in two modes, and you can switch between them mid-run:

- **Advisor** — you play, the bot shows the ranked moves and where each number came from.
- **Autopilot** — the bot plays, and you can take it back at any time with the `p` key.

## Status

Both modes work against the live game. The first autopilot win was run 7 (2026-09-01, Red
deck / White stake): it beat Ante 8 in 168 steps with no mod rejections, timeouts or stalls.

The first win-rate number: **1 win in 16 runs (6 %), mean ante 4.2** on Red/White. Read it as a
first measurement, not a result — it is 16 runs, and a batch of improvements landed together, so
it measures the combination. Finishing that batch is the current work; the ranked list of what
comes next is [PLAN.md](PLAN.md) item 9.8.

You can run the numbers right now, without the game:

```bash
uv run balatro-bot advise --hand "AH KH QH JH 9H 7C 7D 2S" --jokers "joker,droll" --blind 450
```

```
  1. AH KH QH JH 9H  flush                  1 530  хватает
  2. 7C 7D           pair                     144
```

The `--explain` flag shows how the score was assembled, step by step.

Against a running game, installing the mod stack is one command:

```bash
uv run balatro-bot install     # shows what it will download and asks for confirmation
uvx balatrobot serve           # launch the game
uv run balatro-bot doctor      # check the connection
uv run balatro-bot watch       # advice refreshes itself while you play
uv run balatro-bot autoplay    # the bot plays; press 'p' to take over
```

Details and the manual path — [docs/mac-setup.md](docs/mac-setup.md).

## The approach in brief

- **Core** — a score-computation simulator built as an event pipeline: the scorer announces
  each step, and jokers subscribe to events and return effects. That way retriggers and copy
  jokers fall out for free, with no special cases. 149 of the game's 150 jokers are
  implemented.
- **Solver** — an exhaustive search over the 218 hand subsets, about 20 ms. Random effects are
  resolved by exact enumeration of outcomes; what comes out is the expected value with bounds.
- **Honesty** — an unknown or unimplemented joker is not ignored; it marks the calculation
  inexact. Silently returning a plausible wrong number is worse than staying silent. The same
  rule holds for the game's own constants: the base hand values were checked against
  `game.lua` in the game's own source, all 24 of them, and a test now pins them.
- **State source** — swappable adapters: manual input (always works) and a bridge to the mod's
  JSON-RPC API.
- **No production dependencies.** `pyproject.toml` lists none, and about 1 130 tests plus
  strict `mypy` are the whole gate.

Platform: macOS, the Steam version of the game.

## Further reading

- **[PLAN.md](PLAN.md)** — the authoritative design doc: why this game, the exact
  score-computation order being replicated, the phase roadmap, and what is still open.
- **[docs/architecture.md](docs/architecture.md)** — one note per module: the invariants it
  holds and the deliberate refusals behind them.
- **[docs/improvements.md](docs/improvements.md)** — every defect a live run found, what was
  measured, and what changed.
- **[docs/measuring-runs.md](docs/measuring-runs.md)** — how a batch is run and post-mortemed.
