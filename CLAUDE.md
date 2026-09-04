# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**balatro-bot** — advisory bot for the roguelike deck-builder Balatro. It reads the current game state and ranks all possible card plays with exact score breakdowns. Brute-forces all 218 hand subsets (~20ms), never uses ML/heuristics. Code comments, docstrings, and test names are in Russian; prose documentation is in English — see **Language** below.

`PLAN.md` is the authoritative design doc: game-choice rationale, the exact score-computation order to replicate, the phased roadmap, and a running list of open assumptions/defects (section 8.3) and fixed ones (8.4). Check it before making architectural changes.

## Language

- **Talk to the user in Russian.** Every chat response in this repo — explanations, status updates, answers — is written in Russian.
- **Prose documentation is in English.** `CLAUDE.md`, `PLAN.md`, `README.md`, and `docs/*.md` were fully translated 2026-08-31; keep them English.
- **Keep code in Russian.** Comments, docstrings, and test names stay Russian; the ruff config that supports this (`RUF001/002/003` ignored, `pep8-naming` `ignore-names` for `test_*`) exists for that reason and must not be "cleaned up." Verbatim CLI-output samples quoted inside the docs also stay Russian (they mirror what `ui/render.py` actually prints).

## Commands

```bash
# Setup
uv sync

# Run (manual, no game required)
uv run balatro-bot advise --hand "AH KH QH JH 9H 7C 7D 2S" --jokers "joker,droll" --blind 450 --explain
uv run balatro-bot advise --hand "..." --joker-order         # try every joker order for a bigger score
uv run balatro-bot advise --hand "..." --discard "3S 2S"     # exact EV: play now vs. discard these cards
uv run balatro-bot advise --hand "..." --discard-search      # exact search over all discards of 1-5 cards

# Run against the live game — see docs/mac-setup.md for the manual fallback
uv run balatro-bot install          # one-shot installer for the macOS mod stack
                                    # --check: report what is already installed; --dry-run: show the plan;
                                    # --yes: skip confirmation; --game-dir DIR / --force (run off macOS)
uvx balatrobot serve                # launch Balatro with the mod's JSON-RPC server (not via Steam); writes logs/<timestamp>/12346.log (gitignored)
uv run balatro-bot doctor           # check the connection and dump current game state
uv run balatro-bot watch            # live terminal advisor: polls and redraws while you play
uv run balatro-bot autoplay         # live mode: watch + play the running game; press 'p' to pause/take over
uv run balatro-bot autoplay --deck RED --stake WHITE          # managed run: start a fresh run, play it to the end, print a report + decision log
uv run balatro-bot autoplay --deck RED --all-stakes --runs 20 # batch: 20 runs per stake, WHITE→GOLD, win-rate table (Phase 9.7)
uv run balatro-bot autoplay --deck RED --stake WHITE --runs 50 --adopt  # adopt the run already in progress, then keep playing
uv run balatro-bot record NAME      # snapshot live state into tests/golden/ (see Testing Infrastructure)
# global --host/--port (default 127.0.0.1:12346) go before the subcommand: balatro-bot --port 12346 doctor
# watch/autoplay also take --no-joker-order / --no-discard / --no-shop (poll-budget escape hatches);
# autoplay --deck adds --stake (default WHITE) / --seed / --runs / --max-steps (default 2000)

# Test — full suite is ~2 min (the joker-order and discard-search tests dominate);
# scope with -k / a path while iterating, then run the whole suite before finishing
uv run pytest
uv run pytest tests/test_scoring.py -v   # single file
uv run pytest -k scoring                  # by pattern
uv run pytest "tests/test_scoring.py::TestОснова::test_пара" -v     # a single test (tests live in classes)
# 827 tests, no CI — ruff + mypy + pytest run locally are the only gate

# Lint & type-check
uv run ruff check balatro_bot tests
uv run ruff format balatro_bot tests
uv run mypy

# Regenerate catalogue (after updating the BalatroBot mod)
uv run python tools/generate_catalogue.py path/to/balatrobot/src/lua/utils/enums.lua
```

## Architecture

Two data flows share one `GameState` and one scoring engine:

- **Advisory** (`advise`/`doctor`/`watch`): `adapter → GameState → solver/* → ranked *Advice → ui/render`
- **Autopilot** (`autoplay`): `GameState → autopilot.decide_action → Action → dispatch_action → mod_bridge RPC` (driven per-run by `runner.py`, or live by `ui/tui.autoplay`)

```
adapters/manual.py      CLI strings  ─┐
adapters/mod_bridge.py  JSON-RPC     ─┼─► GameState ─┬─► solver/play.py      ─► Advice ──────► ui/render
tests/fake_mod.py       test fixture ─┘              │   solver/actions.py    (play+discard merge)
                                                     │   solver/{skip,shop,vouchers,pack,consumables}.py
                                                     │        │
                                                     │        ▼
                                                     │   core/scoring.py (event pipeline) ─► core/jokers/implementations.py
                                                     │
                                                     └─► autopilot.decide_action ─► Action ─► dispatch_action ─► mod_bridge RPC
                                                              ▲                                                        │
                                                              └───────────────── runner.play_run / ui.tui.autoplay ◄──┘
```

### Module map

One line per module; the deep prose for each is in [docs/architecture.md](docs/architecture.md).

| Module | Role |
|---|---|
| `core/state.py` | `GameState` + all boundary types (`BlindInfo`, `ShopItem`, `JokerCard`); everything external parses into it, everything internal consumes it |
| `core/cards.py` | `Card` and its `Suit`/`Rank`/`Enhancement`/`Edition`/`Seal` enums; CLI card-string parsing; `standard_deck()` |
| `core/hands.py` | poker-hand classification (`evaluate`); chip/mult base per hand type and level |
| `core/scoring.py` | event-driven scoring pipeline; exact EV over random outcomes (a wide single chance point is folded analytically, the rest enumerated); `_apply_boss_score_modifier` (The Flint) |
| `core/economy.py` | money formulas shared by shop/vouchers (`interest`, `interest_cap`, `discount_percent`, `RENTAL_RATE`) |
| `core/catalogue.py` | auto-generated joker/consumable/voucher/booster registry from the mod's `enums.lua` — **do not edit** |
| `core/tags.py` | hardcoded catalogue of all 24 blind-skip tags |
| `core/bosses.py` | hardcoded catalogue of all 28 boss blinds; `restricts_legal_plays` is the one actionable field |
| `core/jokers/` | joker registry (`__init__.py`) + effect implementations (`implementations.py`) |
| `solver/play.py` | `rank_plays()` (all hand subsets), `advise()` (ranked candidates), `rank_joker_orders()`, boss-legality filter |
| `solver/discard.py` | exact discard EV (`discard_outcome`, `rank_discards`) + the cheap target-based `advise_discard` |
| `solver/actions.py` | `rank_actions()` — merges plays and discards into one score-sorted list (the `advise`/`watch` headline) |
| `solver/skip.py` | `evaluate_skip()` — play-or-skip the currently selectable blind (`BLIND_SELECT`) |
| `solver/shop.py` | `evaluate_shop()` — joker buy / sell-replace / pack / voucher evaluation for the `SHOP` screen |
| `solver/vouchers.py` | `evaluate_vouchers()` — 3-tier voucher valuation; feeds `solver/shop.py` |
| `solver/pack.py` | `evaluate_pack()` — which card to take from an open Celestial/Buffoon pack |
| `solver/consumables.py` | `evaluate_planet_consumables()` — use a Planet card from inventory before playing |
| `adapters/manual.py` | CLI-string state input; always available, cannot execute actions |
| `adapters/mod_bridge.py` | JSON-RPC client to the mod (`127.0.0.1:12346`); honest game-action methods + `parse_game_state` |
| `ui/render.py` | terminal formatting shared by `advise`/`doctor`/`watch`/`autoplay` |
| `ui/tui.py` | `watch()` poll+redraw loop; `autoplay()` — the same loop with the right to act (pause on `p`) |
| `autopilot.py` | `decide_action(state) → Action`; `dispatch_action`/`describe_action` shared with the runner |
| `runner.py` | `play_run()` / `run_batch()` — drive whole runs / batches for win-rate measurement (Phase 9.7) |
| `cli.py` | subcommands: `install` / `advise` / `watch` / `autoplay` / `doctor` / `record` |
| `install.py` | one-shot macOS mod-stack installer (Lovely + Steamodded + BalatroBot) |

### Working rhythm

- **Plan before writing code.** Any implementation task — fix, feature, refactor — starts in
  plan mode: read and measure first, write the plan, get it approved, then edit. Only a typo
  or a dictated one-line correction skips this. A plan here names the files it touches, reuses
  what exists, states its own limitations, and ends with how it will be verified; profiling
  belongs in the plan, not after it (see how F1 and F2 were done).
- `PLAN.md` is the authoritative design doc and is kept in lockstep with the code — check it before any architectural change.
- **Phases are the unit of work.** The current per-phase status is `PLAN.md` section 8.1
  ("Where we are now") and the lettered improvement roadmap is section 9.8 — read them there,
  don't restate them here: a second copy of the status drifts silently.
- **Section 8.3** = open assumptions/defects, ranked by impact. **Section 8.4** = fixed defects, each with a regression test. Closing a defect means moving its entry 8.3 → 8.4 and adding the test. Every 8.3 assumption is also flagged inline in the code where it is taken.
- **Section 9.8** = the lettered "improvement" roadmap from live-run findings (A*, B*, C*, D*, E*, F*). Commit messages reference these labels — which are done and which are open is tracked there, not here.
- Work lands on `phase-*` branches (e.g. `phase-9.6-9.7-runner`); PRs target `main`.

### Module notes

The per-module deep prose — the invariants each module holds and why it is built that way —
lives in **[docs/architecture.md](docs/architecture.md)**, one entry per module. Read the
entry for a module before changing it: most record a deliberate refusal (a number this
project will not guess, a value it will not fold into another) that the code alone doesn't
explain. Keep it in lockstep with the code the same way `PLAN.md` is kept in lockstep with
the plan.

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
4. If the joker's real effect is a permanent accumulator ("gains X per Y", "(Currently +N)") built up from events the game state doesn't expose a history of (past discards, past sells, past rerolls, etc.), don't reconstruct the history — the game already computes the running total and renders it into the joker's live effect text (`value.effect` in the mod's response, e.g. "+3 Mult for each Joker card (сейчас +15 множ.)"). `mod_bridge` pulls the live value out of that text into a few `JokerCard` fields, all `None` (manual input, or the text didn't have what was expected) auto-marking the calculation inexact instead of guessing — this only ever works live through the mod bridge:
   - `current_value: float | None`, via `_extract_current_value` — the number in the *last* parenthesized group (structurally, by position, not by matching the word "currently"/"сейчас", so it survives any game locale). Subclass `_LiveAccumulator` (or the `_accumulator("chips" | "mult" | "xmult")` factory) to apply it directly — the effect *type* is already known from the catalogue text, only the magnitude comes from the field.
   - `leading_value: float | None`, via `_extract_leading_value` — same idea but the *first* number in the text, not the last, for the handful of jokers (`j_popcorn`, `j_ramen`) whose live value renders first with a static decay-rate constant after it (confirmed from the game's own `card.lua`, see below). Subclass `_LeadingValueJoker`.
   - `target_suit`/`target_rank: Suit | Rank | None`, via `_extract_word` matching against `_SUIT_WORDS`/`_RANK_WORDS` — for jokers whose "current target" (a suit or rank that rotates) is round-level state (`G.GAME.current_round.*`) with no field in the mod's schema at all, only ever rendered as a word inline in the joker's own text (`j_ancient`, `j_idol`). This is the one place in the project where extraction is tied to game locale rather than text structure — the word dictionaries only cover Russian and English.
   - `loyalty_active: bool | None`, via `_extract_loyalty_active` matching literal "Active!"/"Активно!" vs "remaining"/"осталось" — for `j_loyalty_card`, whose trigger depends on which run-hand this joker was bought on (not tracked anywhere), but which the game itself renders as one or the other.
   
   If the joker's effect provably never touches chips/mult for the play being scored (pure economy, consumable creation, shop/meta effects, or a passive already reflected in the observed state like hand size or discards left), register it as a bare `BaseJoker` with a docstring quoting the catalogue text and a short comment explaining why it's a real zero, not a shortcut — see the "Известны, но на счёт розыгрыша не влияют" section at the bottom of `implementations.py` for the established pattern and precedent. Static game constants that never change at runtime (deck starting size, joker rarity) belong in a hardcoded table next to the joker that needs them (`_DECK_STARTING_SIZE`, `_JOKER_RARITY`) — verify such tables against an external source rather than from memory, and add a test asserting the table's coverage/counts, since a single bad entry produces a silently wrong score. For anything uncertain about a joker's *real* mechanic (not just its current numeric state) — exact trigger condition, what a var actually represents, whether a value is per-instance or round-level — the base game's own Lua source is extractable and authoritative: `Balatro.app/Contents/Resources/Balatro.love` is a plain zip (LÖVE engine format); `card.lua` has every joker's `calculate`/`loc_vars` logic (searched by `self.ability.name`, the display name, not the `j_key`), and `localization/{ru,en-us}.lua` have the exact text templates and word lists. Reading this beats guessing from the catalogue's static (English, un-substituted) text or from memory — that's how the `current_value`/`leading_value` split and the `target_suit`/`target_rank`/`loyalty_active` mechanisms above were each confirmed rather than assumed. Only `j_hiker` has no implementation at all: its bonus permanently attaches to individual *playing cards* (`context.other_card.ability.perma_bonus`), not the joker, which needs a new per-card mechanism this project doesn't have yet.
5. Add tests in `tests/test_scoring.py`.

## Testing Infrastructure

- `tests/fake_mod.py` — mock HTTP server serving `tests/fixtures/gamestate.json` for `ModBridge` tests. It's *static* (same reply to every method), so it can't drive a multi-step loop; `tests/test_runner.py` instead uses a `ScriptedBridge` (a `ModBridge` subclass returning a pre-set timeline of `GameState`s) and monkeypatches `runner.decide_action`/`dispatch_action` to keep the run-loop tests off the real solver.
- `tests/conftest.py` — `fake_mod_port` and `bridge` fixtures.
- `tests/fixtures/gamestate.json` — canonical game state snapshot used across tests.
- `tests/golden/` — full live-state dumps captured by `balatro-bot record` (a `.json`, optionally paired with a hand-written `.expected.json`). No test loads these yet — they're recorded for a future golden-diff layer, so `record` output is not automatically verified today.
- `tests/test_install.py` applies the same no-network, no-macOS approach to the installer: it fakes the `Fetcher` protocol and builds real tar/zip archives under `tmp_path`, exercising the full download → unpack → place flow against a synthetic home directory.
