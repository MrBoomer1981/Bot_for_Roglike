# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**balatro-bot** — advisory bot for the roguelike deck-builder Balatro. It reads the current game state and ranks all possible card plays with exact score breakdowns. Brute-forces all 2¹⁸ hand subsets (~20ms), never uses ML/heuristics. Code comments and documentation are in Russian.

`PLAN.md` is the authoritative design doc: game-choice rationale, the exact score-computation order to replicate, the phased roadmap, and a running list of open assumptions/defects (section 8.3) and fixed ones (8.4). Check it before making architectural changes.

## Commands

```bash
# Setup
uv sync

# Run (manual, no game required)
uv run balatro-bot advise --hand "AH KH QH JH 9H 7C 7D 2S" --jokers "joker,droll" --blind 450 --explain

# Run against the live game — see docs/mac-setup.md for the manual fallback
uv run balatro-bot install          # one-shot installer for the macOS mod stack; --dry-run to preview
uvx balatrobot serve                # launch Balatro with the mod's JSON-RPC server (not via Steam)
uv run balatro-bot doctor           # check the connection and dump current game state
uv run balatro-bot record NAME      # snapshot live state into tests/golden/ for a golden test

# Test
uv run pytest
uv run pytest tests/test_scoring.py -v   # single file
uv run pytest -k scoring                  # by pattern

# Lint & type-check
uv run ruff check balatro_bot tests
uv run ruff format balatro_bot tests
uv run mypy

# Regenerate catalogue (after updating enums.lua from BalatroBot mod)
python tools/generate_catalogue.py path/to/enums.lua
```

## Architecture

Data flow: **adapter → GameState → solver → scoring engine → ranked Advice**

```
adapters/manual.py      CLI strings  ─┐
adapters/mod_bridge.py  JSON-RPC     ─┼─► GameState ─► solver/play.py ─► Advice
tests/fake_mod.py       test fixture ─┘                     │
                                                             ▼
                                               core/scoring.py (event pipeline)
                                                             │
                                               core/jokers/implementations.py
```

**`core/state.py`** — `GameState` is the normalized boundary type. Everything external must be parsed into it; everything internal consumes it.

**`core/scoring.py`** — Event-driven pipeline. Each scoring step emits events (`HandDetermined`, `CardScored`, `CardHeld`, `JokerTurn`, `RetriggerQuery`); jokers react with effects (`AddChips`, `AddMult`, `XMult`, `Retrigger`). Enumerates the full probability tree (up to 4096 branches) for exact expected values.

**`core/jokers/`** — Joker registry (`__init__.py`) + implementations (`implementations.py`). Unimplemented jokers use `UnimplementedJoker`, which marks `ScoreOutcome.exact = False` rather than silently giving wrong answers.

**`core/catalogue.py`** — Auto-generated from the BalatroBot mod's `enums.lua`. **Do not edit manually.**

**`solver/play.py`** — `rank_plays()` brute-forces all hand subsets; `advise()` returns ranked `Candidate` list.

**`adapters/mod_bridge.py`** — JSON-RPC client connecting to the mod server at `127.0.0.1:12346`.

**`install.py`** — one-shot installer for the macOS mod stack (Lovely Injector, Steamodded, the BalatroBot mod). Locates Steam libraries (including ones on secondary drives via `libraryfolders.vdf`), downloads the latest GitHub release of each component behind a `Fetcher` protocol, and unpacks defensively (rejects archive members with absolute or `..` paths). Driven by the `install`/`doctor`/`record` subcommands in `cli.py`; manual step-by-step fallback lives in `docs/mac-setup.md`.

## Key Design Rules

- **Zero production dependencies** — `pyproject.toml` has none; keep it that way.
- **Strict mypy** — all code in `balatro_bot/` and `tests/` must pass strict type-checking.
- **Ruff line-length 100** — except `catalogue.py` (auto-generated, excluded).
- **Ruff ignores RUF001/002/003** — suppresses false positives on Russian text; do not remove.
- **Frozen dataclasses** — all core types are immutable.
- **Honest accuracy** — when a joker or card property is unknown, set `exact=False`; never guess.
- **Python 3.12+** — `match` statements are used throughout; do not downgrade.

## Adding a Joker

1. Look up the joker key in `core/catalogue.py` (e.g. `j_joker`).
2. Implement in `core/jokers/implementations.py` using `BaseJoker` and the `@register("j_key")` decorator.
3. Override `react(self, event: Event, ctx: ScoreContext) -> Iterable[Effect]` and `isinstance`-check for the event(s) you care about (`JokerTurn`, `CardScored`, `CardHeld`, `RetriggerQuery`) — there is no per-event method name to hook into. For the common "fires once on this joker's own turn" shape, subclass `_OwnTurn` and override `on_turn(self, ctx)` instead; most existing jokers do this.
4. Add tests in `tests/test_scoring.py`.

## Testing Infrastructure

- `tests/fake_mod.py` — mock HTTP server serving `tests/fixtures/gamestate.json` for `ModBridge` tests.
- `tests/conftest.py` — `fake_mod_port` and `bridge` fixtures.
- `tests/fixtures/gamestate.json` — canonical game state snapshot used across tests.
- `tests/test_install.py` applies the same no-network, no-macOS approach to the installer: it fakes the `Fetcher` protocol and builds real tar/zip archives under `tmp_path`, exercising the full download → unpack → place flow against a synthetic home directory.
