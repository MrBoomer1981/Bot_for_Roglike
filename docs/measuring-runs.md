# Measuring runs

How this project finds its defects. Almost every entry in the
[improvement log](improvements.md) was found by playing runs against the real game and then
reading what the bot recorded about its own decisions — not by review, and not by the test
suite. The suite has never caught one of these on its own, because they are all the same shape:
the bot computes a *correct* number from a state the game is never in, and only a live run puts
it in that state.

This file is the loop itself: how to run a batch, what the journal holds, and how it gets read.

## Running

```bash
uvx balatrobot serve                       # launch the game with the mod's JSON-RPC server
uv run balatro-bot doctor                  # confirm the connection before committing to a batch

# one managed run
uv run balatro-bot autoplay --deck RED --stake WHITE

# a batch, with a journal per run
uv run balatro-bot autoplay --deck RED --stake WHITE --runs 20 --log runs/

# win-rate across all eight stakes, cumulative order WHITE → GOLD
uv run balatro-bot autoplay --deck RED --all-stakes --runs 20 --log runs/

# attach to the run already on screen instead of starting a fresh one
uv run balatro-bot autoplay --deck RED --stake WHITE --runs 50 --adopt --log runs/
```

`--seed` fixes the run's seed; leaving it off is what you want for a win-rate number, since a
fixed seed measures one run repeatedly. That is not hypothetical — improvement **E1c** is the
batch that passed a single seed to every run and silently measured the same run twenty times.
`--max-steps` (default 2000) is the stall guard.

**The deck, the stake and the run mode are the user's call, never a default.** A batch is hours
of a real machine playing a real game; do not pick them on the user's behalf.

## What a journal holds

`--log DIR` writes one JSON file per run, named `<timestamp>-<deck>-<outcome>.json`. The report
level carries `deck`, `stake`, `stake_observed`, `seed`, `outcome`, `ante`, `round`, `steps`,
`plays`, `discards_used`, `rounds_with_discards_unspent`, `note` and `adopted`; `decisions` is
the list of every decision the autopilot made.

Each decision entry holds:

| Field | What it is |
|---|---|
| `step`, `phase`, `ante`, `round`, `money` | where in the run this decision happened |
| `action` | what was done, as `describe_action` renders it |
| `reason` | the numbers the decision was actually made on (improvement **E1a**) |
| `rejected` | whether the mod refused the action |
| `chips_scored`, `requirement`, `hands_left`, `discards_left`, `blind_beaten` | the round's state |
| `jokers` | the joker labels held at that moment |
| `outlook` | `best_play` / `best_discard` / `discards_left` — why a play beat a discard (**B2**) |
| `shelf` | every shop offer with `label`, `kind`, `price`, `uplift`, `affordable`, `has_slot` (**E1e**) |
| `board` | every held joker with its measured `contribution` and `sell_value` (**E1b**) |
| `pack` | the open pack's cards, each with `label` **and** `kind` (**E1f**) |
| `offered_tag` | the tag on offer for skipping the selectable blind (**E1f**) |

Those last five exist because a question could not be answered without them. `outlook` was
added when a run stopped discarding and the journal could not say whether the discard had been
rejected or never considered. `board` and `shelf` were added when two separate items needed the
same missing numbers — what the bot held, and what it was offered.

`pack` and `offered_tag` differ from the three above in where they are filled, and it matters
when reading them. `outlook`/`shelf`/`board` are computed valuations attached to the `Action`, so
they exist only on the branch that computes them; `pack` and `offered_tag` are raw `GameState`
read in `_entry`, so they appear on **every** entry — including entries where the mod refused and
no `Action` survived. That is the point: every failed action in the deck rotation is pack
handling. Two cautions. `pack` carries `kind` because the defect it exists for is a disagreement
by card *type*, not by count. And **`offered_tag` is not the list of tags the run holds** — the
mod reports only what each blind offers (`G.GAME.round_resets.blind_tags`), never `G.GAME.tags`,
so tag *ownership* is not observable through this API at all.

`Action.reason` is filled at each `return` site, not once at the end, and that is deliberate:
the shop branch alone has eight exits, several inside helpers, and a field filled in one place
covers one of them. It is also the field most likely to lie — improvement **A13** was a reason
line that named a plausible cause the code had not actually used. A reason line that guesses at
causation is worse than no reason line.

## Reading one

The journals are plain JSON; the working method is a short script over a whole directory, not
reading files by eye. Count the thing you suspect, across every decision of every run, before
changing anything:

```python
import json, pathlib
runs = [json.loads(p.read_text()) for p in pathlib.Path("runs/").rglob("*.json")]
decisions = [d for r in runs for d in r["decisions"]]
```

From there it is ordinary counting, and the counting is what produced the findings:

- **A14** — 20 blind selections, **zero** skips, across eleven runs. Nobody had noticed that
  skipping was off, because each individual decision looked reasonable.
- **A16** — the E1 batch, launched to calibrate thresholds, answered in two runs instead: both
  dead at ante 2, having skipped every skippable blind and so arrived at each boss with no round
  income and no shop visit in between. The bar was numerically 2 and nothing on the scale sits
  below 2, so *every* structural tag cleared it — wrong by mechanism, not by number.
- **A21 / A22** — 216 rerolls, of which **167 (77 %) happened with a full board**, spending $887
  of $1141 on searching a shelf the bot could not buy from; and separately, 84 of 87 shop exits
  with a free joker slot happened under $17, where the money reserve made a reroll impossible.
- **C2** — shelves held 243 consumables, 239 of them affordable at the moment they were offered,
  and the bot bought **zero**: there was no branch for a consumable at all.

Two habits are worth copying. Measure the *cost* of the behaviour, not just its frequency —
"77 % of rerolls" is an observation, "$887 of $1141" is an argument. And when a change is
predicted to fire N times, re-run the count through the real code path afterwards: C2 was
predicted at 9 of 22 and fired 5, because the money reserve blocked four of them, and that gap
was the next finding rather than something to quietly re-calibrate.

## The next batch — what it has to answer

Written down on 2026-09-09, before the run, so that the questions are not invented afterwards to
fit whatever came out. The batch is the **deck rotation again** (the same shape as `runs/decks`,
35 runs across 15 decks), because that is the corpus behind the loss table that ranks every open
item, and PLAN.md item 9.8 says in as many words that the table is a pre-C2 baseline to be
re-taken rather than reused. The deck and mode are the user's call and the user will say when.

Four changes have landed since that corpus, so **this batch measures the combination, not any
one of them** — C2 (Planets are bought off the shelf), A21/A22 (the reroll policy), the pack-path
re-poll below, and the C3 pack-wait of 2026-09-10. Read the results in this order:

1. ~~**Did the pack re-poll work?**~~ **Answered on 2026-09-10 without waiting for a batch, and the
   answer was no.** The attempt to run this rotation crashed the game outright, eight times, and
   the cause was the bot skipping a pack whose cards the game had not created yet — see
   [C3](improvements.md#c3-the-autopilot-was-killing-the-game-process-by-skipping-a-pack-that-did-not-exist-yet--done).
   The re-poll settles the *phase* but not the *contents*, so it could not have fixed this class.
   What replaces the question: **count failed actions and crashes.** Any `booster_obj` crash in
   `logs/*/12346.log`, or any `pack({skip=true})` issued against an empty `pack`, means the
   2026-09-10 fix did not hold.
2. ~~**Does an abandoned tag pack persist, or did it merely lag?**~~ **It lagged.** The pack is
   empty because the game defers creating the cards by `1.3*sqrt(GAMESPEED)`; it fills on its own
   if the bot waits instead of acting. Measured 20 pack-phase decisions: the 5 with an empty
   `pack` were all inside that window, the 15 with a non-empty one were all real picks. The
   question that replaces it: **does the bot now actually collect tag packs?** After a skip for a
   `Meteor`/`Buffoon` tag, the journal should show `взял из пака`, not a refusal — that is the
   half of C3 that was about forfeited blind rewards, and it has never once been observed working.
3. **Re-take the loss table** — median share of the requirement reached, share of losses under
   half, discards and money left at the loss. That is the measurement that re-ranks everything
   below C3, and until it exists nothing in the open list is ranked on current evidence.
4. **B3, now that `outlook` carries `best_play`/`best_discard`.** Per discard: what it gave up
   against what it got. Per zero-discard round: whether a discard was available and which guard
   rejected it. No discard threshold moves before this count exists.
5. **C3's arrival rate**, which needed `pack` to be countable at all: a `SMODS_BOOSTER_OPENED`
   entry alone never said *which* pack it belonged to, so "the tag's pack reached the bot" could
   not be separated from "a bought pack was opened".

## Honest limits

- **A batch measures the combination, not the change.** The 16-run Red/White batch (1 win, 6 %)
  ran after A13–A16 and E1a–E1c had all landed together. No single one of them owns that number.
- **`runs/` and `logs/` are gitignored** — journals stay on the machine that produced them. Ten
  files under `runs/` are tracked anyway, from before the directory was ignored; they are the
  before/after reference sets for A16 and are worth keeping for exactly that reason.
- **A stopped batch is still data.** The E1 batch ended at 16 of 30 runs because the game was
  closed; the journals of those 16 are complete and were read as such.
- **`stake_observed`** is false for an adopted run: the mod does not report the stake, so the
  value is whatever the flag asked for. Do not fold adopted runs into a per-stake table without
  checking it.
