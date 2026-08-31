# Bot for Roguelike — a Balatro helper

An advisory bot for [Balatro](https://www.playbalatro.com/): it reads the state of the
current run and shows a ranked list of moves with an exact score breakdown — which cards to
play, what to discard, what to buy in the shop.

The player plays and decides. The bot computes and explains where the number came from.

## Status

Score computation and move selection work. You can run the numbers right now, without the
game:

```bash
uv run balatro-bot advise --hand "AH KH QH JH 9H 7C 7D 2S" --jokers "joker,droll" --blind 450
```

```
  1. AH KH QH JH 9H  flush                  1 530  хватает
  2. 7C 7D           pair                     144
```

The `--explain` flag shows how the score was assembled, step by step.

The connection to a running game is ready but has never been tested on a live Mac — that is
the next step. Installing the mod stack is reduced to a single command:

```bash
uv run balatro-bot install     # shows what it will download and asks for confirmation
uvx balatrobot serve           # launch the game
uv run balatro-bot doctor      # check the connection
uv run balatro-bot watch       # advice refreshes itself while you play
```

Details and the manual path — [docs/mac-setup.md](docs/mac-setup.md).
Numbers produced before that check are marked inexact: the base hand values were
written from memory and still need to be verified against the game.

The roadmap is in **[PLAN.md](PLAN.md)**.

## The approach in brief

- **Core** — a score-computation simulator built as an event pipeline: the scorer announces
  each step, and jokers subscribe to events and return effects. That way retriggers and
  copy jokers fall out for free, with no special cases.
- **Solver** — an exhaustive search over the 218 hand subsets, about 20 ms. Random effects
  are resolved by exact enumeration of outcomes; what comes out is the expected value with
  bounds.
- **Honesty** — an unknown or unimplemented joker is not ignored; it marks the calculation
  inexact. Silently returning a plausible wrong number is worse than staying silent.
- **State source** — swappable adapters: manual input (always works) and a bridge to the
  mod's JSON-RPC API.

Platform: macOS, the Steam version of the game.

## Further reading

The rationale for the game choice, the architecture, the score-computation order, and the
phased roadmap — in [PLAN.md](PLAN.md).
