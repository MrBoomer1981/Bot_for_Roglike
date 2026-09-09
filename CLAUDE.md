# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**balatro-bot** — advisory bot for the roguelike deck-builder Balatro. It reads the current game state and ranks all possible card plays with exact score breakdowns. Brute-forces all 218 hand subsets (~20ms), never uses ML/heuristics. Code comments, docstrings, and test names are in Russian; prose documentation is in English — see **Language** below.

`PLAN.md` is the authoritative design doc: game-choice rationale, the exact score-computation order to replicate, the phased roadmap, the numbered assumptions/defects (sections 8.3/8.4) and the improvement roadmap (item 9.8, whose closed write-ups live in `docs/improvements.md`). Check it before making architectural changes.

**`N.M` in PLAN.md means one of two things**, and the file's own "How this document is numbered" note at the top is the authority. Sections are the `##` headings 1–11, and only section 8 has real subsections (`8.1`–`8.4`, cited from code as `§8.3 №5`). Phases 0–9 are described *inside section 6*, and Phase 9 has items `9.1`–`9.8` — so **`9.8` is a phase item, not a section**, which is why it appears between sections 6 and 7 rather than after section 9 (section 9 is "Risks" and is unrelated). Cite a phase item as "section 6, Autopilot, item 9.5", the way `core/bosses.py` does; a bare "9.1" is ambiguous on sight.

## Language

- **Talk to the user in Russian.** Every chat response in this repo — explanations, status updates, answers — is written in Russian.
- **Prose documentation is in English.** `CLAUDE.md`, `PLAN.md`, `README.md`, and `docs/*.md` were fully translated 2026-08-31; keep them English.
- **Keep code in Russian.** Comments, docstrings, and test names stay Russian; the ruff config that supports this (`RUF001/002/003` ignored, `pep8-naming` `ignore-names` for `test_*` and `Test*`) exists for that reason and must not be "cleaned up." Verbatim CLI-output samples quoted inside the docs also stay Russian (they mirror what `ui/render.py` actually prints).

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
uv run balatro-bot autoplay --deck RED --runs 20 --log runs/            # write one JSON decision journal per run (E1a) — needed to post-mortem an unattended batch
                                    # runs/ and logs/ are gitignored — journals stay local
uv run balatro-bot record NAME      # snapshot live state into tests/golden/ (see Testing Infrastructure)
# global --host/--port (default 127.0.0.1:12346) go before the subcommand: balatro-bot --port 12346 doctor
# watch/autoplay also take --no-joker-order / --no-discard / --no-shop (poll-budget escape hatches);
# autoplay --deck adds --stake (default WHITE) / --seed / --runs / --max-steps (default 2000)

# Test — full suite is ~3 min (the joker-order and discard-search tests dominate);
# scope with -k / a path while iterating, then run the whole suite before finishing
uv run pytest
uv run pytest tests/test_scoring.py -v   # single file
uv run pytest -k scoring                  # by pattern
uv run pytest "tests/test_scoring.py::TestОснова::test_пара" -v     # a single test (tests live in classes)
# ~1130 tests, no CI — ruff + mypy + pytest run locally are the only gate

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
  ("Where we are now") and the lettered improvement roadmap is item 9.8 — read them there,
  don't restate them here: a second copy of the status drifts silently.
- **Section 8.3** = the numbered assumptions/defects, ranked by impact; **section 8.4** = the
  write-ups of the closed ones, each with a regression test. Closing one means writing it up in
  8.4 and leaving a one-line pointer in its 8.3 row — **the numbers are permanent and are never
  reused**, because the code cites them (`§8.3 №5`). Deleting closed rows renumbered the
  survivors once already, which left all six cited numbers either dangling or resolving to the
  wrong row. Every open assumption is also flagged inline in the code where it is taken.
- **Item 9.8** (Phase 9, inside section 6) = the lettered improvement roadmap from live-run findings (A*, B*, C*, D*, E*,
  F*). It holds the intro, an index of every closed label, and the ranked open list; the full
  write-ups live in **[docs/improvements.md](docs/improvements.md)**. Closing an item means
  appending its write-up there and adding a row to the 9.8 index — that index is what keeps a
  citation like "§9.8 A12" resolving. Commit messages reference these labels.
- **Work lands directly on `main`.** Commit on `main` and `git push origin main` — no
  `phase-*` branches, no pull requests (the older branch-per-phase convention is retired).
  Pushing still happens only when the user asks for it.
- **End every reply with a short review of the step just taken.** A few lines, last thing in
  the message, separating three things that this project keeps conflating: what actually
  changed, what of it is **verified** (and by what — a test, a source file, a re-derived
  count) versus merely **plausible**, and what could still be wrong. It is a self-review, not
  a summary: if the step rests on an inference, name the inference; if a claim is one live
  observation generalised, say so. The whole §9.8 log exists because confident claims outran
  the data four times in one entry — this is the standing guard against a fifth.
- **Ask one concrete question, or none.** When a decision is genuinely the user's, state it as
  a decision with named options and a recommendation — not "скажешь — сделаю". When it isn't,
  proceed and report. Vague sign-offs cost a round trip and are how a session stalls.

### Module notes

The per-module deep prose — the invariants each module holds and why it is built that way —
lives in **[docs/architecture.md](docs/architecture.md)**, one entry per module. Read the
entry for a module before changing it: most record a deliberate refusal (a number this
project will not guess, a value it will not fold into another) that the code alone doesn't
explain. Keep it in lockstep with the code the same way `PLAN.md` is kept in lockstep with
the plan.

The rest of `docs/`, all still normative:

- **[docs/improvements.md](docs/improvements.md)** — the completed half of PLAN.md item 9.8:
  every defect a live run found, what was measured, what changed, which tests pin it.
- **[docs/measuring-runs.md](docs/measuring-runs.md)** — how a batch is run and post-mortemed,
  and what the run journal holds. This is the loop that produced almost everything in the log.
  Its "The next batch" section states, in reading order, what the pending batch has to answer —
  written before the run so the questions can't be invented afterwards to fit the result. Start
  there when a session opens on "let's run the tests". **Never launch a batch unprompted:** it is
  hours of a real machine playing a real game, and the deck, stake and mode are the user's call.
- **[docs/adding-a-joker.md](docs/adding-a-joker.md)** — the full procedure summarised in
  "Adding a Joker" below.
- **[docs/Discard Spec.md](docs/Discard%20Spec.md)** — the Phase 6 spec for `advise_discard`; its
  section 7 is the source of the documented ±15% tolerance that `autopilot.py`'s
  `_DISCARD_EDGE_MARGIN` is calibrated against, so read it before touching discard estimates.
- **[docs/mac-setup.md](docs/mac-setup.md)** — the manual fallback for the mod stack that
  `balatro-bot install` automates.

## Key Design Rules

- **Zero production dependencies** — `pyproject.toml` has none; keep it that way.
- **Strict mypy** — all code in `balatro_bot/` and `tests/` must pass strict type-checking.
- **Ruff line-length 100** — `catalogue.py` is per-file-exempt from `E501` only (its long lines are
  verbatim game text); every other rule still applies to it.
- **Ruff ignores RUF001/002/003** — suppresses false positives on Russian text; do not remove.
- **Frozen dataclasses** — all core types are immutable.
- **Honest accuracy** — when a joker or card property is unknown, set `exact=False`; never guess.
- **Python 3.12+** — `match` statements are used throughout; do not downgrade.

## Adding a Joker

1. Look up the joker key in `core/catalogue.py` (e.g. `j_joker`).
2. Implement in `core/jokers/implementations.py` with `BaseJoker` and `@register("j_key")`,
   overriding `react(self, event, ctx)`. Reuse a family base rather than a new shape —
   `_OwnTurn`, `_ConditionalJoker`, `_SuitBonus`, `_PerScoredCard`, `_RuleChanger`,
   `_FullDeckJoker`, `_LiveAccumulator`, `_LeadingValueJoker`, `_BeforePassAccumulator`.
3. Never guess a number. A permanent accumulator's running total is read out of the joker's
   live effect text by `mod_bridge`; anything unknown sets `exact=False` or stays `None`.
4. Add tests in `tests/test_scoring.py`.

Two rules that cost live runs when skipped, so they are here and not only in the guide:

- **If the joker reads any `GameState` field** (`hands_left`, `money`, `hand_info`, …), check it
  against the A11 audit table in [docs/architecture.md](docs/architecture.md)'s `solver/shop.py`
  entry. Four runs were lost to a joker priced from a state the round is never in (A8–A11).
- **Read the game's own source before calling anything unknowable.**
  `Balatro.app/Contents/Resources/Balatro.love` is a plain zip: `card.lua` has each joker's
  logic, `game.lua` the base tables and configs, `functions/state_events.lua` the authoritative
  scoring order, `blind.lua` each boss's `modify_hand`. Improvement A12 closed four assumptions
  that had sat for months labelled "needs a Mac" — a label that was wrong six times out of seven.

The full procedure, including every family base class, the live-value extraction fields and the
established pattern for a joker that is a real zero — **[docs/adding-a-joker.md](docs/adding-a-joker.md)**.

## Testing Infrastructure

- `tests/fake_mod.py` — mock HTTP server serving `tests/fixtures/gamestate.json` for `ModBridge` tests. It's *static* (same reply to every method), so it can't drive a multi-step loop; `tests/test_runner.py` instead uses a `ScriptedBridge` (a `ModBridge` subclass returning a pre-set timeline of `GameState`s) and monkeypatches `runner.decide_action`/`dispatch_action` to keep the run-loop tests off the real solver.
- `tests/conftest.py` — `fake_mod_port` and `bridge` fixtures.
- `tests/fixtures/gamestate.json` — canonical game state snapshot used across tests.
- `tests/golden/` — full live-state dumps captured by `balatro-bot record` (a `.json`, optionally paired with a hand-written `.expected.json`). No test loads these yet — they're recorded for a future golden-diff layer, so `record` output is not automatically verified today.
- `tests/test_install.py` applies the same no-network, no-macOS approach to the installer: it fakes the `Fetcher` protocol and builds real tar/zip archives under `tmp_path`, exercising the full download → unpack → place flow against a synthetic home directory.
