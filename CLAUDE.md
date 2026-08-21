# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**balatro-bot** — advisory bot for the roguelike deck-builder Balatro. It reads the current game state and ranks all possible card plays with exact score breakdowns. Brute-forces all 218 hand subsets (~20ms), never uses ML/heuristics. Code comments and documentation are in Russian.

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
uv run balatro-bot watch            # live terminal advisor: polls and redraws while you play
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

**`core/cards.py`** — `Card` and its `Suit`/`Rank`/`Enhancement`/`Edition`/`Seal` enums, plus `parse_card(s)`/`parse_cards(s)` for the CLI string format (e.g. `"AH"`, `"7C"`) and `standard_deck()`.

**`core/hands.py`** — poker-hand classification: `evaluate(cards, modifiers)` picks the best `HandType` (straight/flush detection respects `HandModifiers` like `four_fingers`/`splash`) and returns the scoring `HandResult`; `base_values()` gives the chip/mult base for a hand type and level.

**`core/scoring.py`** — Event-driven pipeline. Each scoring step emits events (`HandDetermined`, `CardScored`, `CardHeld`, `JokerTurn`, `RetriggerQuery`); jokers react with effects (`AddChips`, `AddMult`, `XMult`, `Retrigger`). Enumerates the full probability tree (up to 4096 branches) for exact expected values.

**`core/jokers/`** — Joker registry (`__init__.py`) + implementations (`implementations.py`). Unimplemented jokers use `UnimplementedJoker`, which marks `ScoreOutcome.exact = False` rather than silently giving wrong answers.

**`core/catalogue.py`** — Auto-generated from the BalatroBot mod's `enums.lua`. **Do not edit manually.**

**`solver/play.py`** — `rank_plays()` brute-forces all hand subsets; `advise()` returns ranked `Candidate` list. `rank_joker_orders()` (CLI: `advise --joker-order`) brute-forces joker permutations too — order matters because `Blueprint`/`Brainstorm` copy neighbors and `AddMult`/`XMult` don't commute; capped at `MAX_JOKERS_FOR_ORDER_SEARCH = 6` (720 permutations), returning `None` above that instead of guessing.

**`solver/discard.py`** — `discard_outcome()` (CLI: `advise --discard "cards"`) computes the exact EV of discarding one *caller-specified* set of hand cards: brute-forces every possible draw from the remaining deck (no sampling) and averages the best `advise()` score per draw. Deliberately doesn't search over *which* cards to discard — combined with the deck-draw search, that's what PLAN.md section 8.3 assumption #9 flags as too slow even for Monte Carlo. Capped at `MAX_DRAW_COMBINATIONS = 2000` draws, returning `None` above that — same honest-refusal pattern as `rank_joker_orders`. Deck knowledge comes from `GameState.deck`: exact when the mod bridge parsed it from the mod's `cards` area (confirmed against golden dumps to be the literal remaining draw pile — `hand.count + cards.count` equals the full deck size), approximated as a standard 52-card deck minus the current hand otherwise (manual input), with the result honestly flagged either way. `rank_single_discards()` is the one exception to "don't search which cards" — single-card discards have at most 8 candidates and a cheap enumeration each, so it's the only discard size cheap enough to brute-force automatically; `watch` calls it on every redraw (`--no-discard-tips` to skip it) to show the best card(s) to discard, but 2+ card discards are still left to `--discard` because a candidate of size 2 alone can already mean ~950 draws × 28 candidates.

**`adapters/mod_bridge.py`** — JSON-RPC client connecting to the mod server at `127.0.0.1:12346`. Read-only in practice: `play()`/`discard()` exist on the client, but nothing in the bot calls them — no autoplay is a deliberate product rule (PLAN.md section 2), not just an unfinished feature.

**`ui/render.py`** — terminal formatting shared by `advise`/`doctor`/`watch`, so the three commands can't drift into inconsistent output. **`ui/tui.py`** — `watch()` polls `ModBridge.game_state()` on an interval and only clears/redraws when the returned `GameState` compares unequal to the last one (frozen dataclasses give this for free), so an idle screen doesn't flicker. No dependency on `textual`/`rich` despite PLAN.md's original stack section — plain ANSI (`\x1b[2J\x1b[H`) instead, to keep the zero-dependency rule intact. Unlike `advise` (where `--joker-order` is opt-in), `watch` runs the joker-order search on every redraw by default — `--no-joker-order` opts back out — since a live session is exactly where catching a suboptimal joker order matters most; the tradeoff is up to 720 extra `advise()` calls per poll when 2+ jokers are held.

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
3. Override `react(self, event: Event, ctx: ScoreContext) -> Iterable[Effect]` and `isinstance`-check for the event(s) you care about (`JokerTurn`, `CardScored`, `CardHeld`, `RetriggerQuery`) — there is no per-event method name to hook into. For the common "fires once on this joker's own turn" shape, subclass `_OwnTurn` and override `on_turn(self, ctx)` instead; most existing jokers do this. Reusable family base classes already exist for common shapes: `_ConditionalJoker`/`_conditional(...)` for "if the hand contains X, add chips/mult/xmult"; `_SuitBonus`/`_suit_joker(...)` for "cards of suit X give +chips/+mult when scored"; `_PerScoredCard` for "react to each qualifying scored card"; `_RuleChanger` for jokers whose only effect is a `HandModifiers` flag (checked in `modifiers_from()`, e.g. `four_fingers`, `splash`, `pareidolia`, `chicot`, `oops`); `_FullDeckJoker` for "X per card of type Y in your full deck" (`j_steel_joker`, `j_stone`, `j_drivers_license`, `j_erosion`) — backed by `GameState.full_deck`, which the mod bridge can only fill in exactly when nothing has been played or discarded yet this round (the mod's `openrpc.json` has no field for the full deck, only the remaining draw pile — see PLAN.md section 8.2 for why), so treat it as `None`-checked optional data like `GameState.deck`, never as always-present. For a probabilistic joker/enhancement with a "no luck / bonus" two-outcome table (Lucky, `j_bloodstone`), route it through `core.scoring.double_chance(outcomes)` gated on `ctx.modifiers.oops` so `j_oops` (Oops! All 6s) doubles it automatically — don't hand-roll a second doubling formula.
4. If the joker's real effect is a permanent accumulator ("gains X per Y", "(Currently +N)") built up from events the game state doesn't expose a history of (past discards, past sells, past rerolls, etc.), don't reconstruct the history — the game already computes the running total and renders it into the joker's live effect text (`value.effect` in the mod's response, e.g. "+3 Mult for each Joker card (сейчас +15 множ.)"). `mod_bridge._extract_current_value` pulls the number out of the last parenthesized group in that text (structurally, by position — not by matching the word "currently", so it survives the game running in any locale) into `JokerCard.current_value: float | None`. Subclass `_LiveAccumulator` (or use the `_accumulator("chips" | "mult" | "xmult")` factory) to apply it directly as the matching effect — the effect *type* is already known from the catalogue text, only the magnitude comes from `current_value`; `None` (manual input, or the effect text had no parenthesized number) auto-marks the calculation inexact instead of guessing. This only works live through the mod bridge, never for manual input. A handful of accumulators (`j_hiker`, `j_loyalty_card`, `j_popcorn`, `j_ramen`) don't render a "currently" clause at all — nothing to extract — so those stay `UnimplementedJoker`. If the joker's effect provably never touches chips/mult for the play being scored (pure economy, consumable creation, shop/meta effects, or a passive already reflected in the observed state like hand size or discards left), register it as a bare `BaseJoker` with a docstring quoting the catalogue text and a short comment explaining why it's a real zero, not a shortcut — see the "Известны, но на счёт розыгрыша не влияют" section at the bottom of `implementations.py` for the established pattern and precedent. Static game constants that never change at runtime (deck starting size, joker rarity) belong in a hardcoded table next to the joker that needs them (`_DECK_STARTING_SIZE`, `_JOKER_RARITY`) — verify such tables against an external source (a wiki, the game itself) rather than from memory, and add a test asserting the table's coverage/counts, since a single bad entry produces a silently wrong score.
5. Add tests in `tests/test_scoring.py`.

## Testing Infrastructure

- `tests/fake_mod.py` — mock HTTP server serving `tests/fixtures/gamestate.json` for `ModBridge` tests.
- `tests/conftest.py` — `fake_mod_port` and `bridge` fixtures.
- `tests/fixtures/gamestate.json` — canonical game state snapshot used across tests.
- `tests/test_install.py` applies the same no-network, no-macOS approach to the installer: it fakes the `Fetcher` protocol and builds real tar/zip archives under `tmp_path`, exercising the full download → unpack → place flow against a synthetic home directory.
