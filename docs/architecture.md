# Architecture — module notes

One entry per module of `balatro_bot/`, expanding the Module map table in [CLAUDE.md](../CLAUDE.md):
the invariants each module holds and why it is built the way it is. **Read the entry for a module
before changing it** — most entries record a deliberate refusal (a number this project will not
guess, a value it will not fold into another) that is not obvious from the code alone.

Scope: this file says *what the code does and why it is shaped that way*. The design rationale for
the project as a whole, the phase roadmap, and the running list of open assumptions live in
[PLAN.md](../PLAN.md) (sections 8.1, 8.3, 8.4, 9.8) — the authoritative design doc. Keep this file
in lockstep with the code; keep PLAN.md in lockstep with the plan.

## Index

One entry per module below. Three modules in CLAUDE.md's module map have no note here yet —
`adapters/manual.py`, `ui/tui.py` and `cli.py`; they are thin enough that the code reads as its own
documentation, and the omission is recorded rather than hidden.

- [`core/state.py`](#corestatepy)
- [`core/economy.py`](#coreeconomypy)
- [`core/cards.py`](#corecardspy)
- [`core/hands.py`](#corehandspy)
- [`core/scoring.py`](#corescoringpy)
- [`core/jokers/`](#corejokers)
- [`core/catalogue.py`](#corecataloguepy)
- [`core/tags.py`](#coretagspy)
- [`core/bosses.py`](#corebossespy)
- [`solver/skip.py`](#solverskippy)
- [`solver/shop.py`](#solvershoppy)
- [`solver/vouchers.py`](#solvervoucherspy)
- [`solver/pack.py`](#solverpackpy)
- [`solver/consumables.py`](#solverconsumablespy)
- [`solver/play.py`](#solverplaypy)
- [`solver/discard.py`](#solverdiscardpy)
- [`solver/actions.py`](#solveractionspy)
- [`adapters/mod_bridge.py`](#adaptersmod_bridgepy)
- [`balatro_bot/autopilot.py`](#balatro_botautopilotpy)
- [`ui/render.py`](#uirenderpy)
- [`balatro_bot/runner.py`](#balatro_botrunnerpy)
- [`install.py`](#installpy)

## Modules

### `core/state.py`

`GameState` is the normalized boundary type. Everything external must be parsed into it; everything
internal consumes it. `BlindInfo` now carries `status`/`tag_name`/`tag_effect` in addition to the
original `kind`/`name`/`effect`/`required_score`; `GameState.blind` stays "the currently active
blind" (status `CURRENT`, unchanged meaning) while the new `GameState.blinds: Mapping[str,
BlindInfo]` (keys `"small"`/`"big"`/`"boss"`) carries all three regardless of status — needed
because on the blind-select screen none of them is `CURRENT` yet (`blind` is `None` there), but
their requirements and tags are already known. `ShopItem` (key/label/`kind`/price/effect/edition,
plus the joker-only stake-sticker fields `eternal`/`perishable_rounds`/`rental` parsed from the
mod's `modifier` area — Phase 9.6) is the analogous boundary type for the shop screen —
`GameState.shop`/`shop_vouchers`/`shop_packs`, see `solver/shop.py`. The same type also covers
`GameState.pack` — the cards of a currently *open* booster pack (`*_PACK` phases, the mod's `pack`
area, same per-card shape as the shop's), `price` just isn't meaningful there (a pack's contents are
already paid for) — see `solver/pack.py`. `GameState.consumables` is the same type again for the
mod's `consumables` area — Tarot/Planet/Spectral cards already sitting in the player's inventory,
live across the whole run rather than scoped to one phase like `shop`/`pack` — see
`solver/consumables.py`; its capacity rides alongside as `GameState.consumable_slots`, read from
that area's `limit` exactly as `joker_slots` and `shop_slots` are read from theirs (improvement C2 —
the game refuses a purchase into a full inventory, and a mod refusal is not a decision).
`GameState.used_vouchers: frozenset[str]` (mod area `used_vouchers`, keys only — the mod's own
descriptions aren't needed) is the run's redeemed-voucher history, parsed starting Phase 9.3; see
`core/economy.py` for why it mattered enough to add.

### `core/economy.py`

money formulas shared by `solver/shop.py` and `solver/vouchers.py` (`interest`, `interest_cap`,
`discount_percent`), extracted from the game's own source rather than kept as two
independently-drifting copies — unlike small sampling constants (`SAMPLE_HANDS`, `_HAND_SIZE`),
which each solver module still duplicates on its own by established convention, a real formula is
worth sharing. `RENTAL_RATE = 3` (dollars drained per round per rental joker, from `game.lua`'s
`GAME_MOD.rental_rate` / `card.lua`'s `Card:calculate_rental`) lives here too as a verified game
constant, with its own anchor test — Phase 9.6. `interest_cap`/`discount_percent` take
`GameState.used_vouchers` and return the *actual* current cap/discount (`Seed Money`/`Money Tree`
*set* the interest cap to 50/100, not add to it — confirmed from `card.lua`'s `Card:add_to_deck`;
same "sets, doesn't add" shape for `Clearance Sale`/`Liquidation`'s discount). Adding
`used_vouchers` closed a real, previously-documented gap: `solver/shop.py`'s
`JokerOffer.interest_lost` used to assume the default $25 cap always, explicitly flagged as a lower
bound because `GameState` didn't track which economy vouchers a run had already redeemed — now it
doesn't have to guess, for any run played through the mod (manual/CLI input still can't supply run
history, so the assumption survives only there, the same asymmetry as `GameState.deck`/`full_deck`).

### `core/cards.py`

`Card` and its `Suit`/`Rank`/`Enhancement`/`Edition`/`Seal` enums, plus
`parse_card(s)`/`parse_cards(s)` for the CLI string format (e.g. `"AH"`, `"7C"`) and
`standard_deck()`.

### `core/hands.py`

poker-hand classification: `evaluate(cards, modifiers)` picks the best `HandType` (straight/flush
detection respects `HandModifiers` like `four_fingers`/`splash`) and returns the scoring
`HandResult`; `base_values()` gives the chip/mult base for a hand type and level. `BASE_VALUES` and
`PER_LEVEL_VALUES` were written from memory and were, for most of this project's life, the
**top-ranked open assumption** — "distorts every calculation", and marked as needing a running game
to close. **Improvement A12 closed it by reading**: `game.lua` carries the whole `G.GAME.hands`
table, and a mechanical check of all 24 numbers (12 base chip/mult pairs, 12 per-level increments)
found zero discrepancies. `HAND_VALUES_ARE_PROVISIONAL` is therefore `False` and results are no
longer marked inexact on account of these tables. The numbers are still hand-written — what changed
is that `tests/test_hands.py` now pins every one of them against values transcribed from `game.lua`
with the source cited, the same discipline as `_JOKER_RARITY`, so a future "correction from memory"
fails a test rather than skewing every score in the project.

### `core/scoring.py`

Event-driven pipeline. Each scoring step emits events (`HandDetermined`, `CardScored`, `CardHeld`,
`JokerTurn`, `RetriggerQuery`); jokers react with effects (`AddChips`, `AddMult`, `XMult`,
`Retrigger`). Resolves random outcomes to **exact** expected values and bounds — never a sample. It
used to do that by enumerating the whole probability tree, re-running the entire pipeline once per
branch, and that turned out to be the project's single performance bottleneck: profiling put
`advise()` at 8.7 ms with no variance joker and 164 ms with `Misprint`, whose uniform `+0..+23`
spread costs 24 branches — 19× for one joker, while all 218 subsets and the whole event dispatch
accounted for the other 8.7 ms. **Improvement F3** removes it without giving up a digit. A chance
point resolves to a *number* (`ChancePicker.pick`), and that number reaches the accumulator only
through `AddChips(v)` / `AddMult(v)` / `XMult(v)` — each linear in `v` — so `chips` and `mult` are
affine in it and the total `chips × mult` is a polynomial of degree at most 2. `_fold_single_chance`
therefore runs the engine at three outcomes, interpolates, and then evaluates every remaining
outcome *arithmetically*: `Σ pᵢ·P(vᵢ)` for the expectation, min and max of `P` for the bounds. Same
numbers as enumeration, four engine passes instead of 25. The polynomial claim is **checked, not
asserted** — a fourth evaluation verifies the fit and any disagreement drops straight back to the
existing full enumeration, so an effect that branched on the drawn value would be caught rather than
silently mispriced. The fold applies only to a single chance point wide enough to pay for itself
(`_FIT_MIN_OUTCOMES`); Lucky's two branches and multi-point trees enumerate as before, and
`MAX_CHANCE_BRANCHES` with its likeliest-outcome fallback is untouched. Measured: `advise()` 164 →
36 ms, a cold shop visit 80.2 → 17.7 s, a repeat shop poll 2.23 → 0.48 s. The play-with-discards
decision barely moved (7.0 → 6.5 s) — its cost is in `solver/discard.py`'s own sampling, not here,
and it is now the slowest single decision the autopilot makes. **Two steps now run before the event
loop at all (improvement A17)**, because the game has a `context.before` pass that resolves ahead of
reading base chips and mult, and nothing raised from inside the loop can reach that far back.
`_space_level_bonus` raises a chance point for `Space Joker` there — its 1-in-4 upgrade applies to
the play it is made on, which is the opposite of what this project believed until A12 read
`card.lua` — and the picker is already in hand, so `score_play` enumerates it like any other point
(two outcomes, so F3's folding correctly ignores it). `_vampire_feast` strips the enhancement off
every enhanced scoring card and records the count on `ScoreContext.vampire_eaten`, because `Vampire`
eats the cards *and then* pays itself 0.1 per card; the project previously did neither, scoring the
cards with their enhancements while applying the pre-play `current_value`. Held cards are left
alone, matching the game. Safe to substitute cards into the scoring set because `ctx.played` is read
by two jokers for its length only and `ctx.scoring_cards` by three for suits only — checked before
the change, since this is the only place that alters how cards reach the scoring loop. The game's
stripping is permanent for the rest of the run; this engine scores one hand and has no deck-mutation
model, so only the current hand is made correct, the same limit `The Hanged Man` declares.
`_apply_boss_score_modifier` is the one step so far that reacts to the *boss itself* rather than to
cards or jokers: when `state.blind.name` is `"The Flint"` (see `core/bosses.py`), it halves the base
hand chips/mult (`floor(x*0.5+0.5)`, matching `blind.lua`'s `Blind:modify_hand`) right after the
base value is set, before `HandDetermined` fires. That placement used to carry a caveat — the belief
that the game halves *after* hand-level jokers but before card scoring, which this pipeline (jokers
last) could not reproduce, so any hand with a joker was marked `unknown`. **Improvement A12 read the
source and disproved it**: `Blind:modify_hand` is called at `functions/state_events.lua`'s
`evaluate_play` immediately after the base values are read and before a single card or joker scores,
which is exactly where `_apply_boss_score_modifier` already ran. The `unknown` was pure loss — every
Flint hand with a joker reported as inexact for a reason that was not true — and it is gone. The
same read caught a second, real bug: `modify_hand` opens with `if self.disabled then return mult,
hand_chips, false end`, and `Chicot` disables the boss blind, so the halving must be skipped
entirely under `ctx.modifiers.chicot` — it was not.

### `core/jokers/`

Joker registry (`__init__.py`) + implementations (`implementations.py`). Unimplemented jokers use
`UnimplementedJoker`, which marks `ScoreOutcome.exact = False` rather than silently giving wrong
answers. A joker the game has *disabled* (`JokerCard.debuffed` — in base Balatro only a Perishable
joker whose round counter hit 0, ORANGE+ stake; `mod_bridge` reads it from the joker's
`state.debuff`) is skipped entirely by the scoring pipeline — no `react()` to any event, no edition,
no `HandModifiers` flag (`ScoreContext.emit`/`ask_retriggers`, `modifiers_from`) — but it still
counts as a physically present joker for `Joker Stencil` / `Baseball Card` / "+N per Joker",
matching `#G.jokers.cards` in the real game.

**The `before` pass (improvement A12).** Before reading the hand's base chips and mult,
`G.FUNCS.evaluate_play` runs a separate pass over the jokers with `context.before = true`
(`functions/state_events.lua`), and several accumulators do their increment *there* — so the hand
being scored already includes it, while `JokerCard.current_value` was snapshotted by the mod before
the play and does not. `_LiveAccumulator` was therefore understating every one of them by exactly
one step on qualifying hands. `_BeforePassAccumulator` (built via `_before_accumulator(kind,
condition, increment)`) adds that step when its condition holds: `j_trousers` +2 Mult when the
played cards contain Two Pair or a Full House, `j_runner` +15 chips on a Straight, `j_square` +4
chips on exactly 4 cards played — each increment read from that joker's `config` in `game.lua` and
each condition from `card.lua`, never from memory, and each checked through the existing
`ctx.contains_*` vocabulary rather than a second way of asking the same question. A missing
`current_value` still marks the result unknown; the increment never invents a number. This is the
same shape of defect as A11 in `solver/shop.py` — a value taken from a state that is not the moment
being scored — which is why the two improvements are worth reading together. `Supernova` was fixed
in the same pass for the same underlying reason: it reads `G.GAME.hands[...].played`, incremented
for the current hand at the top of `evaluate_play`, so the mod's pre-play snapshot needs `+ 1` and
the joker had been understated by 1 Mult on every play ever scored. Two jokers found by this audit
are **not** fixed and are recorded as PLAN.md §8.3 rows 3 and 4 instead: `j_vampire` strips
enhancements off the scoring cards in that same pass (wrong in both directions at once, and needing
mid-pipeline card mutation the engine has no mechanism for), and `j_space` levels up the very hand
it is played on (needing a chance point over the *base values*, which are set before the event loop
starts, so `double_chance` cannot reach it).

### `core/catalogue.py`

Auto-generated from the BalatroBot mod's `enums.lua`. **Do not edit manually.**

### `core/tags.py`

hardcoded catalogue of all 24 blind-skip tags (`TAGS: dict[str, TagEffect]`), extracted from the
game's own Lua source (`game.lua`'s `tag_*` definitions, `tag.lua`'s `Tag:apply_to_run`) rather than
guessed — same rigor and verification discipline as `_JOKER_RARITY`/`_DECK_STARTING_SIZE` in
`implementations.py`, with its own coverage test (`tests/test_tags.py`) asserting all 24 keys are
present exactly once. `TagEffect.summary` is a structural description only ("what happens"), never a
value judgment — valuing a tag belongs in `solver/skip.py`, and only for the subset where that's
honestly possible.

### `core/bosses.py`

hardcoded catalogue of all 28 boss blinds (`BOSSES: dict[str, BossEffect]`), same discipline as
`core/tags.py`: extracted from `game.lua`'s `P_BLINDS` table (`bl_*` keys — `bl_small`/`bl_big`
aren't bosses, excluded) and from `blind.lua`'s dispatch methods
(`Blind:debuff_hand`/`modify_hand`/`press_play`/`set_blind`/`disable`, all keyed on `self.name`, the
game's own English identifier — the same string the mod sends as `BlindInfo.name`,
locale-independent), plus `functions/state_events.lua` for `The Serpent`'s draw-cap. Coverage test
in `tests/test_bosses.py` (28 keys, exactly once). `BossEffect.summary` is structural only, same as
`TagEffect.summary` — the mod's own `BlindInfo.effect` already handles display text.
`BossEffect.restricts_legal_plays` is the one actionable field: `True` only for the three bosses
whose restriction can make an otherwise-best `rank_plays` candidate an illegal move — `The Mouth`
(one hand type per round), `The Eye` (can't repeat a hand type), `The Psychic` (can't play fewer
than 5 cards). Every other boss is already handled without new code: card-suit/rank/face debuffs are
the existing generic `Card.debuffed` path; `The Water`/`The Needle`/`The Manacle` are already
reflected live in `GameState.discards_left`/`hands_left`/`hand` size; several (`The Fish`/`The
House`/`The Mark`/`The Wheel`) are purely visual (cards dealt face-down) and don't change what the
mod reports; `The Tooth`/`The Ox`/`The Hook` are money/hand-composition side effects the catalogue
records but that don't block any move. Building this catalogue also surfaced a real, previously
untracked scoring bug (PLAN.md section 8.3 assumption #10): `The Flint` halves final chips and mult
and that step didn't exist anywhere in `core/scoring.py` — fixed there
(`_apply_boss_score_modifier`), not in this module, which stays catalogue-only. The filter for the
three `restricts_legal_plays` bosses now lives in `solver/play.py` (`_is_legal_play`, using
`PokerHandInfo.played_this_round`); with that plus the `The Flint` fix, assumption #10 is fully
closed.

### `solver/skip.py`

`evaluate_skip(state)` is the first slice of PLAN.md's Phase 8 ("run strategy"): whether to play or
skip the currently-selectable blind (`GameState.blinds["small"|"big"]` with `status == "SELECT"`;
boss blinds are never skippable and are excluded even if selectable). Deliberately doesn't collapse
the decision to one fabricated score — a real design choice, not a shortcut: many tags (a free
joker, a voucher, a pack) don't reduce to a comparable unit at all, so `SkipAdvice` reports both
sides' real numbers (requirement ratio to the next blind, the guaranteed money floor for playing,
the tag's own text) and leaves the comparison to the human, mirroring `docs/Discard Spec.md`'s "idea
3/4" resolution rather than idea 2 (convert-everything-to-score). Money-denominated tags get an
exact dollar figure only when the formula's inputs are actually present in the mod's schema —
`Investment Tag` ($25, conditional on later beating the ante's boss) and `Economy Tag` (`min(40,
money)`) qualify; `Handy`/`Garbage`/`Skip` Tags do not, because their formulas need run-lifetime
counters (total hands played, total unused discards, total skips) that `openrpc.json`'s `GameState`
schema simply doesn't expose anywhere (only per-round equivalents) — `tag_dollars` is honestly
`None` with a text explanation in that case, not a guess. Wired into `doctor` and `watch` (via
`render_skip_advice`) rather than `advise`, since the blind-select screen has no hand to run
`advise` against at all (`GameState.hand` is empty there).

**Three honesty tiers (improvement A14), and why the old single tier had to go.** The original
design skipped only when `tag_dollars` was an exact number, which is true for two of the 24 tags —
so twenty-two tags could never be chosen no matter how strong, and run 12 duly made 20 blind
selections with **zero** skips, walking past `Negative`, `Rare`, `Polychrome` and three `Buffoon`
tags. Every individual refusal was correct, which is why no test caught it; the module was written
in Phase 9.2, before the pack, shop and voucher valuation existed, and a principled `None` stops
being principled once the machinery to compute it arrives. Tags now use the same three-tier shape as
`solver/vouchers.py`, in separate fields (`tag_uplift` / `tag_dollars` / `tag_heuristic`) so a
computed number and an assigned one can never be confused: **score** for `Meteor` and `Buffoon`
(each is a free Mega pack, priced by `shop.monte_carlo_pack` over the existing pools) and `Orbital`
(+3 hand levels through `pack.level_up`) — no new formulas, only wiring; **dollars** for
`Investment`/`Economy`, unchanged; **structural** on the voucher 1–8 scale, sharing its anchor
deliberately — a Negative edition is +1 joker slot, exactly what `v_antimatter` grants, so `Negative
Tag` takes `v_antimatter`'s 8.0 rather than an independently invented number, and a test pins them
together. `Handy`/`Garbage`/`Skip` keep an honest `None` (run-level counters the mod never sends) as
do `Standard`/`Charm`/`Ethereal` (Arcana/Spectral/Standard packs, which this project values nowhere
— the same gap `solver/pack.py` declares). A coverage test asserts all 24 tags get an answer or a
stated reason.

**Tier 1 is computed lazily, and the cost is why.** The pools measure 2.4 s (planets) and 9.8 s
(jokers) while this screen recurs about twenty times a run, so they are touched only when one of the
three pack tags is actually on offer — measured after the change: `Negative` and `Handy` 0.00 s,
`Orbital` 2.43 s, `Meteor` 2.45 s, `Buffoon` 10.19 s. The shop's `_SampleCache` is deliberately not
reused here: its key does not model the blind-select screen, and widening a cache key past what it
describes is precisely how A11's stale-samples defect arose. **Known calibration risk:** replaying
run 12's passed tags, the bot now skips 4 of 9 with full slots and 6 of 9 with slots free, and **no
tier accounts for the score progress a skip forfeits** — only the $3–4 reward.
`_MIN_HEURISTIC_TAG_VALUE` / `_HEURISTIC_TAG_FLOOR` in `autopilot.py` are the knobs if live runs
show it is too eager.

### `solver/shop.py`

`evaluate_shop(state)` is the second slice of Phase 8: which shop jokers are worth buying.
`GameState.shop`/`shop_vouchers`/`shop_packs` (three separate `ShopItem` tuples, populated only in
phase `SHOP` from the mod's like-named areas) mirror the real, already-generated shop — not a
hypothetical one, so there's no RNG to model here either, same as `solver/skip.py`. Jokers are the
only item type that gets a computed value: `_evaluate_joker_offer` reuses the real scoring engine as
a counterfactual (add the candidate `JokerCard` — with whatever edition the shop is charging for —
to `state.jokers`, keep everything else fixed, diff `advise().best.score`), the same shape as
`rank_joker_orders`'s permutation search, just for "would adding this help" instead of "what order
helps." The one adaptation: the shop screen has no hand either, so the diff is averaged over
`SAMPLE_HANDS = 12` hands sampled from `GameState.full_deck` when the narrow case applies or
`standard_deck()` otherwise (flagged via `JokerOffer.exact_deck`) — deterministic, seeded sampling,
same pattern as `solver.discard._SAMPLE_SEED`. **Improvement A10 added the second dimension**: the
samples also span the *moment of the round*. They used not to, and that was a real defect — every
sample was scored in the shop's own state, where the round has not started, so the six jokers that
read `hands_left` / `discards_left` / `hands_played` were all priced at one wrong point.
`j_acrobat`, `j_dusk`, `j_mystic_summit` and `j_card_sharp` could never fire and measured exactly 0
— unbuyable by every threshold and first in line to be sold — while `j_banner` and `j_ice_cream`
were measured at their maximum. Run 9 lost `Acrobat` to this (contribution 0, sold as dead weight)
and overpaid for `Ice Cream` in the same run. `_round_moment(state, step, hands)` now walks
`hands_left` from `H` down to 1, `hands_played` from 0 up, and decays `discards_left` to 0 on the
last hand; `_round_budget` takes `H` from the state rather than guessing. Crucially the sample
*count* is unchanged, so the fix is free (a cold visit measured 80.2 s against 80.6 s before), and
`joker_uplift` and `joker_contributions` share the schedule — they have to, because `autopilot`
compares an uplift against a contribution directly — with both sides of every diff on the same
moment, so only the joker differs. One honest limit stays: discards are modelled as spent evenly
(real play front-loads them, so `j_banner` reads a little high). `j_card_sharp` was the sixth joker
A10 knowingly left at 0, and run 10 sold it — closed by **improvement A11**, which audited the whole
class rather than waiting for the next run to surface the next instance of it.

**Invariants (improvement A20).** Alongside that table, `tests/test_shop.py`'s
`TestИнвариантыКонтрфактума` asserts what this counterfactual may never output: an unconditionally
beneficial joker cannot have negative uplift, a provably inert one moves the number by exactly zero,
and exactness survives adding a candidate. Written because four defects of one class (A9, A10, A11,
A18) were all found by live runs and none by the suite — every existing test asked what a joker
computes, none asked what the valuation may never produce. Two honest exceptions are encoded rather
than worked around: on a board that counts jokers (`j_abstract`, `j_swashbuckler`) even an inert
joker legitimately raises the score, and `Joker Stencil` legitimately makes a weak candidate
negative, which is A9's finding.

**The A11 audit — which jokers read `GameState`, and does the counterfactual model that field?** A8,
A9, A10 and the Card Sharp gap were all the same defect: not a joker implemented wrongly, but the
counterfactual scoring from a state the round is never in. Each cost a live run to find. Exactly
nine implemented jokers read a state field, so the class is small enough to enumerate — and this
table is the point of A11 as much as the code is. Check any new state-reading joker against it:

| field | jokers | modelled |
|---|---|---|
| `hands_left` | `j_acrobat`, `j_dusk` | ✅ A10 |
| `discards_left` | `j_banner`, `j_mystic_summit` | ✅ A10 (stated assumption) |
| `hands_played` | `j_ice_cream` | ✅ A10 |
| `joker_slots` | `j_stencil` | ✅ (`len(ctx.jokers)` grows with the candidate) |
| `deck`, `deck_type`, `full_deck` | `j_blue_joker`, `j_erosion`, the `_FullDeckJoker` family | ✅ static within a round |
| `hand_info.played_this_round` | `j_card_sharp` | ✅ A11 |
| `money` | `j_bull`, `j_bootstraps` | ✅ A11 |

**A11, gap 1 — `played_this_round`.** `_round_moment` gains `repeat: bool`; when set it marks
*every* hand type as played, so whichever type the solver picks counts as a repeat and the caller
never has to predict which one — levels, chips and mult carry through untouched. The share of
samples that repeat is **measured, not guessed**: the run 9 and run 10 decision logs were parsed and
every played hand re-evaluated through `core.hands.evaluate` — 13 of 19 non-first plays in a round
repeated a type already played, 68 % (`_CARD_SHARP_REPEAT_RATE`, with the 19-observation sample size
in its docstring and due for re-measurement by the E1 batch). `_repeats_hand_type` spreads that
share across sample cycles the way Bresenham's algorithm splits a slope — exactly `int(C × rate)`
firings over `C` cycles, deterministic, no second RNG — and the averaging the two samplers already
do turns it into an estimate at the measured share. `j_card_sharp` 0 → 184. **The boss guard is
load-bearing**: `solver/play.py._is_legal_play` reads the same field, so under `The Eye` "every type
has been played" would make *every* play illegal; the marking is skipped under the three bosses with
`restricts_legal_plays` (`_RESTRICTING_BOSS_NAMES`, taken straight from `core/bosses.py` rather than
re-listed), which puts `j_card_sharp` back at 0 under those three — a narrow explicit refusal, not a
silently wrong number.

**A11, gap 2 — money was counted before the purchase**, and this one was not previously known.
`joker_uplift` scored the boosted side with `state.money` untouched while buying costs `item.price`,
and `j_bull`/`j_bootstraps` read that field directly — so the bias grew with price and the most
expensive offers ignored their own cost the most. `money_delta` applies the shift to the **modified
side only**, which is the shape of a counterfactual rather than an oversight: not buying costs
nothing. Measured on a `j_bull` offer, 206.7 at $0 / 175.7 at $6 / 144.7 at $12.
`joker_contributions` takes the mirror (money moves by the sold joker's `sell_value`), because
`autopilot._decide_replace_action` compares the two numbers directly and must not weigh an uplift
priced after the spend against a contribution priced before the refund — the A10 lesson applied.
`solver/pack.py` keeps `money_delta = 0`: the pack is already paid for. **Gap 2b**, found by the
same audit, is a correctness defect F2 itself introduced: `_sample_cache_key`'s `money_matters`
scanned held jokers only while the key blanks `shop`, so with a `Bull` on the shelf but not in a
slot, buying something else moved money without moving the key and served a stale uplift. The scan
now covers the shelf, and the per-offer memo id gains the price. Cost of all of it: none — cold
visit 17.4 s against 17.7 s, 1.48 s after a reroll, 0.48 s on a repeat poll. An unregistered joker
key (`core.catalogue.is_known_joker` false) gets `expected_uplift = None` rather than a guess,
exactly like `UnimplementedJoker` elsewhere. `JokerOffer.interest_lost` is the other half of a
purchase's real cost: buying reduces `state.money`, which reduces the interest paid at the next
round's end — `_interest()` implements the formula straight from the game's own
`functions/state_events.lua` (`interest_amount * min(floor(dollars/5), interest_cap/5)`, defaults
`1`/`25` from `game.lua`), not from memory. It's shown next to `expected_uplift`, never folded into
it — dollars and score points aren't commensurable without an arbitrary exchange rate, the same
reasoning as `core/tags.py`'s refusal to collapse a tag to one number. It's also honestly partial in
two ways: it only prices in the *next* round-end, not the whole rest of the run (that needs knowing
how many rounds remain — Phase 9 territory, not a shop-screen computation), and it assumes the
default $25 cap because `GameState` doesn't track which vouchers this run has already redeemed
(`Seed Money`/`Money Tree` raise it to $50/$100) — so on an economy-heavy run it's a real lower
bound on the loss, not an overstatement. The one case it does track exactly is `Green Deck`
(`GameState.deck_type == "GREEN"`), where the game disables interest outright and `interest_lost` is
a genuine, not approximated, zero. Phase 9.6 adds three more per-offer fields in the same "shown
next to `expected_uplift`, never folded into it" shape — the mod sends stake stickers on high-stake
shop jokers: `JokerOffer.rental_cost_per_round` (`economy.RENTAL_RATE` if `ShopItem.rental`, else 0
— a *recurring* $3/round drain, and a trap because the game force-drops a rental joker's purchase
price to $1), `perishable_rounds` (rounds until the game *disables* the joker — not destroys it; the
slot stays occupied by a dead card), and `eternal` (can't be sold once bought — a slot-budget risk).
None of the three gates the autonomous buy in `autopilot._decide_shop_action` yet — an unresolved
policy question (dollars/rounds vs. score points, the same incommensurability as `interest_lost`),
and PLAN.md section 8.1 still lists it as open. `JokerCard` (jokers already in slots) deliberately
did *not* get these fields: rent drain / perish countdown on owned jokers is future-round planning,
i.e. Phase 9.7 (run-runner), not a shop-screen computation. **Sell-replace (improvement A1, from the
live-run roadmap):** when every joker slot is full, a plain buy is impossible, so
`joker_contributions(state, deck_source, samples)` computes the mirror counterfactual of
`joker_uplift` — how much the best score *drops* if each held joker is removed, over the same
sampled hands. `evaluate_shop` attaches the weakest **non-eternal** held joker as a
`ReplaceCandidate` (index / label / its contribution / its `sell_value`) to every priced
`JokerOffer` via `JokerOffer.replaces`; the verdict (is the trade worth it) lives in `autopilot`,
not here. **Improvement A9** widened when that measurement happens: contributions are computed
whenever `state.jokers` is non-empty, not only when the slots are full, and are reported as
`ShopAdvice.held: tuple[HeldJoker, ...]` (index / label / contribution / sell_value / eternal, in
`state.jokers` order). The old gate made the bot blind to the situation `Joker Stencil` creates — it
pays `X1 Mult per *empty* slot`, so a joker can be worth *less than an empty slot* and its
contribution goes negative. Run 8 carried `Hit the Road` at −722 to Ante 7 and lost with $59
unspent, because with 4 of 5 slots filled the number was never computed at all. `ReplaceCandidate`
is now derived from `held` and is still attached only when slots are full, so replace semantics are
unchanged. The added work is 5.0 s on a 4-joker board against a 60.6 s cold visit (~9 %), and
nothing on warm polls or after a reroll — the F2 memo covers it, since a reroll does not change the
held stack. A debuffed joker's contribution is exactly `0.0` (the engine already skips it), which
makes an expired-perishable joker the natural first thing to sell. `ShopAdvice.vouchers` is no
longer raw `ShopItem`s — see `solver/vouchers.py` below (Phase 9.3, now all three honesty tiers),
which values most of the 32 vouchers and leaves the rest an honest `None`. `ShopAdvice.packs` is now
`PackPurchaseOffer`s, not raw `ShopItem`s: the shop only shows a pack's type and price, not
contents, so a pre-buy counterfactual is impossible — but a **Buffoon** pack gets an estimated
`expected_uplift` from a Monte-Carlo of the pack mechanic itself: `joker_uplift` over
`PACK_JOKER_SAMPLE = 24` random *implemented* jokers (computed once per shop visit, hoisted into
`evaluate_shop`), then a cheap Python resample `PACK_SIM_TRIALS` times drawing `extra` jokers
without replacement and summing the best `choose` — `(extra, choose)` from `_BUFFOON_PACK_SIZES` per
the game's own pack config (Normal 2/1, Jumbo 4/1, Mega 4/2). This is an honest expected value, not
a deliberate lower bound (an earlier version was: mean of one random joker, which is always positive
so the autopilot always bought — 3 of 4 live-bought packs were then skipped). Mega's `choose = 2`
sums the top two independent uplifts, ignoring their interaction — noted, slight overestimate. **A
Celestial pack now gets the same treatment (improvement A3):** `_planet_uplift_pool` computes the
uplift of leveling each of the 12 hand types once per shop visit (reusing `solver.pack.level_up` via
a deferred import — `shop`↔`pack` is a genuine two-way cycle), then the shared `_monte_carlo_pack`
resamples best-`choose`-of-`extra` per `_CELESTIAL_PACK_SIZES` (Normal 3/1, Jumbo 5/1, Mega 5/2,
from `P_CENTERS`). Planets from a pack are used immediately (no consumable slot), so a Celestial
offer's `has_slot` is always `True`. Arcana/Spectral/Standard packs stay an honest `None` (need the
consumable/deck-card mechanic layer). `ShopAdvice.reroll` (`RerollOutlook`, improvement A5) is the
one place this module *does* model a fresh, unseen roll: a Monte-Carlo of the roll mechanic — each
of `GameState.shop_slots` slots is a joker with probability `economy.SHOP_JOKER_RATE /
(joker+tarot+planet rate)` (20/28, from `game.lua`'s `GAME_MOD`), the joker's uplift drawn from the
same `random_joker_uplifts` sample the Buffoon-pack estimate uses (24 random implemented jokers,
computed once per shop visit). Non-joker slots contribute 0 (tarot/planet not modeled —
conservative). Documented simplification in `RerollOutlook.note`: rarity (`game.lua` 70/25/5
Common/Uncommon/Rare) is only reflected by averaging over implemented jokers, not stratified into
three pools. `expected_best_uplift` (mean of the best slot over `PACK_SIM_TRIALS`) is tail-inflated
— a rare strong joker pulls the mean up — and, more importantly, it is **stationary**: it is
computed from a fixed pool of random jokers, so it neither sees the current shelf nor shrinks as
money is spent. Measured on a 5-joker stack against a 300-requirement blind it reads ~138 whatever
is on the shelf, against a buy bar of 9. A5 leaned on `_REROLL_MONEY_RESERVE` alone to end a streak;
run 7 showed that only running out of money ever did, which is what improvement A8 fixes in
`autopilot.py` — this module's number is honest, the policy built on it was not.
`GameState.shop_slots` is a new parsed field (mod's `shop` area `limit`, mirrors `joker_slots`).
**Sample memo (improvement F2):** one shop decision on a 5-joker stack with a variance joker
measured **78 s**, and a reroll rebuilt all of it — that is the "hangs in the shop" from run 7 (a
4-reroll streak ≈ 6.5 minutes). The game's own `button_callbacks.lua::G.FUNCS.reroll_shop` replaces
**only the shop cards**, leaving vouchers, packs and the held jokers alone, so nearly all of that
work is re-done for nothing: `random_joker_uplifts` (46.5 s), `_planet_uplift_pool` (11.7 s),
`joker_contributions` (8.7 s) and each shelf joker's own uplift are cached in a one-entry
`_SampleCache`. The key (`_sample_cache_key`) is the whole `GameState` with only the shelf,
`reroll_cost` and — when no `_MONEY_SENSITIVE_JOKER_KEYS` joker is held — `money` blanked, compared
by `==`: any field *not* blanked invalidates the cache by itself, so the design is safe by
construction rather than by remembering to list every dependency. `money` needs the exception
because exactly two jokers read it while scoring (`j_bull`, `j_bootstraps`), and that key set is
pinned by a *behavioural* test over every implemented joker — the same discipline as
`solver/discard.py::_SUIT_SENSITIVE_JOKER_KEYS`. Everything cheap (`affordable`, `has_slot`,
`interest_lost`, stake stickers, the sort) is still recomputed from the live state every call, so
stale money cannot reach an offer. Result: 78 s → **6.9 s** after a reroll, **2.2 s** on a repeat
poll of an unchanged shelf. `evaluate_vouchers` is deliberately left out — `_evaluate_shop_discount`
prices Clearance Sale / Liquidation against the current shelf, which a reroll does change; it is
what remains of the repeat-poll cost. `clear_shop_cache()` and `evaluate_shop(..., use_cache=False)`
exist for tests and for a deliberately cold computation. Wired into `doctor` and `watch`
(`--no-shop` to skip it in `watch`, matching `--no-joker-order`/`--no-discard`'s cost/benefit
escape-hatch pattern — a handful of jokers × 12 samples × two `advise()` calls each is on the order
of a second, not free).

**Improvement C2 — the shelf is not only jokers.** `evaluate_shop` used to filter `state.shop` down
to `item.kind == "JOKER"`, so consumables sitting on the same shelf never reached a decision at all.
Measured over the 15-deck rotation that was not a missing convenience but the root of the loss
pattern: the shelves held **243 consumables of which 239 (98 %) were affordable**, the bot bought
**zero**, so Planets arrived only from Celestial packs (~1.3 per run), hand levels stayed at 1–2,
and at those levels the counterfactual **correctly** prefers additive jokers
(multiplicative/additive uplift ratio 0.42× at level 1, crossing 1.0 around level 5) — boards filled
with additive jokers and stopped tracking a requirement growing ×2.5 per ante, exactly at antes 4–5
where the runs die. `ShopAdvice.consumables` now carries a `ConsumableOffer` per shelf consumable.
**Only Planets get a number**, from the same `level_up` the Celestial pack uses — one quantity, one
source, asserted by a test that the shelf figure equals the pool's entry for that hand type. Tarot
and Spectral get an honest `None` with a reason, and the reason is a measurement, not a shrug:
`evaluate_tarot_consumables` costs **334 ms on an empty board and 8977 ms on five jokers** for a
single card against a real hand, and the shop screen has no hand at all, so a shelf valuation would
have to sample hands — roughly 45 s per shop visit. The same number rules out buying a Tarot
speculatively and deciding at use time: making Tarots reachable would put that nine-second stall on
every hand.

The sampling was split rather than duplicated. `planet_uplifts(state, hand_types, deck_source)`
computes one shared baseline for whatever set of hand types is asked for; `planet_uplift_pool` is
now a thin wrapper returning all twelve in `PLANET_HAND_TYPES` order, the shape `monte_carlo_pack`
wants. The set is a parameter because the cost is real: **807 ms for one hand type, 1198 ms for two,
5174 ms for all twelve** on a five-joker board. A Celestial pack needs all twelve (the card is not
drawn yet); a Planet already lying on the shelf needs exactly its own. `_SampleCache.planet_uplifts`
became a `dict[HandType, float]` filled incrementally, shared by both paths — two stores of one
quantity would drift apart. **Improvement A22** added one more already-computed value to the
boundary: `ShopAdvice.replace_candidate`, the weakest non-eternal held joker when slots are full.
`evaluate_shop` computed it before but attached it only to *priced* offers as `JokerOffer.replaces`;
the reroll gate needs the replace bar precisely when no shelf offer is priced at all — which is the
situation a reroll exists for. `ConsumableOffer.has_slot` reads the new `GameState.consumable_slots`
(the mod's `consumables` area `limit`, usually 2): the game refuses a purchase into a full
inventory, and a mod refusal is not a decision.

### `solver/vouchers.py`

`evaluate_vouchers(state)` is Phase 9.3's first (most honest) of three tiers from the plan: only
vouchers whose effect is a direct game resource get a computed score, no new assumptions needed.
Three groups: `v_grabber`/`v_nacho_tong` (+1 hand per round each) are valued as the plain average
`advise().best.score` over `SAMPLE_HANDS` sampled hands — no baseline to subtract, since without the
voucher that extra play simply wouldn't happen at all (contributing zero, not some other score).
`v_paint_brush`/`v_palette` (+1 hand size each) use the exact same counterfactual shape as a shop
joker: sample one hand of `_HAND_SIZE + 1` cards, score it, score the first `_HAND_SIZE` of the
*same* sample as the baseline, diff — isolating the marginal value of the one specific added card
rather than comparing two independently-sampled hands. `v_wasteful`/`v_recyclomancy` (+1 discard per
round each) are the one case honestly narrower than "no new assumptions" sounds: their value is
measured only through `solver.discard.rank_single_discards` (the one discard size whose exact search
is always cheap) rather than the fully general `rank_discards` (which would multiply an
already-nontrivial per-sample cost by up to 218 candidates — no longer a shop-screen-sized
computation) — `VoucherOffer.note` says so explicitly, and the number is a genuine lower bound, not
an overstatement, since a real multi-card discard could be worth more. Six more vouchers now form
Phase 9.3's second tier — a real dollar formula, but one that needs an explicit, stated horizon
rather than reducing to a score: `v_seed_money`/`v_money_tree` (interest cap to 50/100) are valued
as `(interest at the new cap − interest at the current cap) × rounds left in this ante` — the
horizon isn't invented, it's counted from `GameState.blinds` (every blind not yet `DEFEATED`), with
one explicit, noted assumption: today's money holds roughly steady for those future round-ends.
`v_reroll_surplus`/`v_reroll_glut` (reroll $2 cheaper each) only price the *next* reroll at the
current `GameState.reroll_cost` — the same "next occurrence only, not the whole run" partiality as
`JokerOffer.interest_lost`. `v_clearance_sale`/`v_liquidation` (25%/50% off cards and packs) are
valued against what's already visible in *this* shop visit (`GameState.shop` + `shop_packs`,
vouchers excluded — the game's own text says "cards and packs") rather than projecting future
visits; inverting today's already-discounted price back to a pre-discount base (needed only when a
discount voucher is already active) is a few-dollar approximation because the game's own cost
formula rounds with `floor()`, and `VoucherOffer.note` says so. `Hieroglyph`/`Petroglyph` stay
excluded from even this tier — its "−1 Ante" side would need an ante-based blind-requirement
formula, which turned out not to exist anywhere in the codebase yet despite an earlier planning note
assuming it did.

The third and last tier — plan section 2's "Third category," introduced specifically because the
autopilot can't treat silence as neutral the way a human reading `advise` output could — is an
expert-judgment constant for 12 vouchers whose real value depends on future shop RNG this project
doesn't model (`Antimatter`, `Hone`/`Glow Up`, `Tarot`/`Planet Merchant`/`Tycoon`,
`Overstock`/`Overstock Plus`, `Crystal Ball`, `Telescope`/`Observatory`). This is structurally
distinct from `expected_uplift` — never the same field with an approximation flag, a dedicated
`VoucherOffer.heuristic_value` field instead, precisely because the dishonesty here is a different
kind (a number never computed at all, not a computed number that's merely approximate).
`expected_uplift` stays `None` for these regardless. The twelve numbers are hand-ranked by game
sense (a Joker slot outranks everything, `Glow Up` outranks its own prerequisite `Hone`,
`Observatory` ranks lowest since it only helps while an unused Planet card happens to sit in
inventory) — plainly not measured, and `render_shop_advice` labels them "экспертно" rather than
"прирост" so they can never be mistaken for the first two tiers at a glance. `v_blank` looks like it
belongs here but doesn't: `card.lua` confirms its `apply_to_run` does nothing but trip an
achievement check, so it gets a genuine `expected_uplift = 0.0` instead of a guessed
`heuristic_value` — a verified fact, not an estimate. The remaining vouchers (`Director's
Cut`/`Retcon`, `Illusion`/`Magic Trick`, `Omen Globe` — never named in the plan's own tier-3 list
either) stay `None` with a note, since even an approximate game-sense ranking isn't available for
them yet. All remaining vouchers get `expected_uplift = None` with a `VoucherOffer.note` explaining
which tier they belong to, the same honest-`None`-over-a-guess shape as `JokerOffer`'s unregistered
jokers. Wired into `solver/shop.py`'s `ShopAdvice.vouchers` (replacing the old raw `ShopItem`
tuple), so `doctor`/`watch`/`autoplay` show it automatically through the existing
`render_shop_advice` — no new render function, no new CLI flag. **`VoucherOffer.value_unit`
(`"score"` / `"dollars"` / `None`)** was added because `expected_uplift` is overloaded — score
points for tier 1, real dollars for tier 2 — and only `note` distinguished them (fine for a human,
useless to code). `render_shop_advice` now prints tier-2 as "в деньгах ~$N" instead of "прирост ~N".
**`autopilot._decide_shop_action` now buys vouchers (improvement A4)** via `_decide_voucher_action`,
per an explicit user decision that all three tiers may drive a purchase: `value_unit == "score"` →
same `_worth_buying` bar as a joker; `value_unit == "dollars"` → net-positive (`expected_uplift >=
item.price`, dollar-to-dollar); `heuristic_value` → only structural upgrades (`>=
_MIN_HEURISTIC_VOUCHER_VALUE = 5.0`, so Antimatter/Glow Up but not the merchant-rate ones;
improvement A7 scales that bar down to a floor of 3.0 for a shop-slot `Overstock` voucher when the
bot is cash-rich with idle joker slots — `Overstock` rates 3.0, same as merchant-rate `Telescope`,
so the relief is keyed on voucher identity, not the number). Acting on tier 3 at all is the user's
call — it's a ranked guess, not a computed number — and the threshold is deliberately high. Vouchers
occupy no slot, so only `affordable` gates them; the branch runs after the joker buy (jokers are the
core engine and fill scarce slots) but before packs (packs are a gamble).

### `solver/pack.py`

`evaluate_pack(state)` — which card to take from an *open* booster pack. Two pack types are closed:
**Celestial/Planet** (`PLANET_PACK`) — a Planet card levels up one `HandType` by a fixed known
amount (`core.hands.PER_LEVEL_VALUES`), fully deterministic; `PLANET_HAND_TYPES` maps each of the 12
planet keys to its `HandType`, straight from `core/catalogue.py`'s effect text (coverage test in
`tests/test_pack.py`). And **Buffoon** (`BUFFOON_PACK`) — the jokers are *visible* in the pack, no
RNG, so each gets `solver.shop.joker_uplift` (the shop-joker counterfactual, extracted as a shared
helper). Both reuse the sampled-hands approach (`GameState.full_deck` when known, `standard_deck()`
otherwise — a pack is opened outside a hand). `PackOffer.kind` (`"planet"` | `"joker"`)
distinguishes them because the guarantee differs: leveling a hand type can't lower the best
achievable score (`expected_uplift` never negative *by construction*), so the autopilot always takes
the best planet; a bad joker *can* hurt (dead slot), so it takes a joker only on strictly positive
uplift + free slot, else `skip_pack`. `level_up` is public (also reused by `solver/consumables.py`).
`evaluate_pack` returns `()` outside those two phases or when nothing in `GameState.pack` is
recognized — Arcana/Spectral/Standard packs need the consumable-mechanic layer and are left to
`autopilot`'s `skip_pack` fallback (don't get the run stuck), not evaluated here. Jumbo/Mega packs
(choose 1 of 5 / up to 2 of 5) need no special-casing: the mod's `pack` endpoint takes one selection
at a time and reports whether the pack is still open afterward, and since the poll loop
(`ui/tui.py`) already re-reads state every iteration, a still-open pack just gets evaluated again
fresh on the next poll. Wired into `doctor`/`watch`/`autoplay` via `ui/render.render_pack_advice`,
unconditionally (no `--no-pack` flag) — a real `PLANET_PACK` phase is rare and the item count is
small (≤5), so the cost is comparable to a single shop-advice render, not worth gating.

### `solver/consumables.py`

two halves of Phase 9.4, sharing only their context (the inventory and the current hand): the Planet
slice, and the first slice of the Tarot work (improvement **C1**). **Tarot (C1, slice 1):** unlike a
Planet card, a Tarot needs a *target*, so the search runs over subsets of the hand — and cost
decided the shape. `advise()` on an 8-card hand measures 4 ms with no jokers and 163 ms on a 5-joker
stack with `Misprint`, so "up to 3 cards" (92 subsets) would be ~15 s per card against the 0.6 s F1
achieved for a whole decision. Slice 1 therefore covers only the eight "Enhance selected card(s)"
Tarots, at most `C(8,1)+C(8,2) = 36` subsets. `TAROT_ENHANCEMENTS` is a hardcoded table transcribed
from `game.lua`'s `P_CENTERS` (`config.mod_conv` + `config.max_highlighted`, all eight sharing
`effect = "Enhance"`), with a coverage test like `PLANET_HAND_TYPES`'s. `max_highlighted` is a
*maximum*, so sizes 1..N are all searched. The uplift cannot be negative by construction — the
search starts at the baseline, so "nothing improves this hand" comes back as `0.0` with empty
targets, meaning *no reason to spend the card*, not *spending it hurts*; that distinction matters
for `The Tower`, which erases a card's rank and suit and can genuinely ruin a flush. Three honesty
tiers with a `value_unit` field, copied from `VoucherOffer` because points and dollars must not
share one field: score for the eight, dollars for `c_hermit` (`max(0, min(money, 20))`) and
`c_temperance` (`min(Σ sell_value, 50)`) — both read off `card.lua`/`game.lua` — and an honest
`None` with a reason for the other twelve, split between `_DEFERRED_TAROTS` (slice 2) and
`_RANDOM_TAROTS` (create cards or roll on jokers). `The Devil` is a *computed* zero, not a gap: Gold
pays money for a card held at end of round and never touches a play's score, the same honest zero as
the economy jokers. `MAX_TAROT_CANDIDATES = 64` bounds the subset count and yields an honest `None`
above it, the same refusal as `rank_joker_orders`. Measured cost: 0.19 s for six Tarots on an empty
stack, 7.9 s for two on the heavy one — within "seconds", but a real regression on that path and the
obvious next performance item. **Slice 2 (2026-09-05)** closes the remaining seven, and three of
their mechanics differ from what the names suggest — `card.lua` was read rather than guessed.
`change_suit` rebuilds only `base`, so rank, enhancement, edition and seal all survive a suit
conversion (`TAROT_SUIT_CONVERSIONS`: Star→Diamonds, Moon→Clubs, Sun→Hearts, World→Spades).
`Strength` **wraps an Ace to a 2** rather than capping at Ace (`id == 14 and 2 or min(id+1, 14)`).
`Death` carries `min_highlighted = 2` as well as max — exactly two targets — and clones the
rightmost onto the other *whole*, base and enhancement and edition and seal, not merely its rank.
`The Hanged Man` is a **computed zero**: destroying cards can only shrink the set `advise` chooses
from, so this hand's best score can never rise — the same honest zero as `The Devil`, with its real
deck-thinning value named in the note as unmodelled. **The reachability filter is load-bearing, not
decoration:** three targets out of eight is 92 subsets, past `MAX_TAROT_CANDIDATES`, so slice 1's
budget gate would have refused these cards outright. Converting suits only matters for a flush, so
`_suit_conversion_targets` computes how many cards short of one the hand is — through the existing
`core.cards.effective_suits`, which already knows `Wild` and `Smeared` — and searches subsets of
exactly that size among cards not already that suit; unreachable, or a flush already in hand, is an
honest `0.0`. The shape is `solver/discard.py`'s `_flush_targets`. No autopilot change was needed,
which is the payoff of slice 1's design: `_decide_consumable_action` already iterates offers
generically. One stated limitation rides in the offer's `note` — the game re-derives a card's debuff
after a suit change (`change_suit` calls `debuff_card`) while `Card.debuffed` here is a static field
from the mod that nothing recomputes, so under a suit-restricting boss the uplift reads optimistic.
Measured: four Tarots on the 5-joker `Misprint` stack 2.56 s, on an empty stack 0.22 s. **Planet:**
`evaluate_planet_consumables(state)` is Phase 9.4's first (Planet) slice: whether to use a Planet
card already sitting in inventory (`GameState.consumables`, the mod's `consumables` area, parsed the
same way as `shop`/`pack`) before playing the current hand. Tarot cards (~22 different effects, many
transforming specific cards — `Death` needs a donor/target pair, a new search dimension on top of
the existing one) are deliberately untouched, comparable in scope to adding ~22 new jokers.
Mechanically identical to picking a card from a Celestial/Planet Pack — same deterministic level-up,
same `solver.pack.level_up` helper reused rather than duplicated — but the context is richer here:
`SELECTING_HAND` always has a real current hand, so the counterfactual runs `advise()` on the actual
hand twice (baseline vs. leveled) instead of `solver/pack.py`'s sampled-hands average. That
precision is deliberately partial, not a smaller version of the same idea: `expected_uplift` only
measures the benefit to *this* hand, not the level's real value across every future hand this run
(the same "next occurrence only" honesty as `JokerOffer.interest_lost`) — a Planet card whose hand
type this hand doesn't happen to make shows `0.0`, never negative, even though the permanent
level-up is still worth having. `v_observatory` (see `solver/vouchers.py`'s third tier) complicates
this in one specific way this module surfaces but can't resolve: it grants X1.5 Mult from a matching
*unused* Planet card sitting in inventory, so using the card trades that (unimplemented in the
scoring engine — a bare catalogue fact, not a formula) for the permanent level-up —
`PlanetConsumableOffer.note` says so explicitly whenever `v_observatory` is redeemed, rather than
silently ignoring a real but uncomputed trade-off. `ModBridge.use(consumable, *, cards=None)` wraps
the mod's `use` RPC. `autopilot.decide_action` checks this before play/discard on `SELECTING_HAND`
and, mirroring `_decide_pack_action`'s reasoning, uses whatever Planet card it finds without waiting
for a positive number — leveling can't hurt, so there's nothing to weigh, only "which one" (ranked
by `expected_uplift`, though as noted that ranking is itself an approximation when it's 0 for more
than one candidate). One consumable per `decide_action` call, same "recompute fresh next poll"
pattern as shop purchases and pack picks.

### `solver/play.py`

`rank_plays()` brute-forces all hand subsets; `advise()` returns ranked `Candidate` list.
`rank_joker_orders()` (CLI: `advise --joker-order`; also used by `watch` every redraw and by the
autopilot per hand — improvement D1) searches joker permutations too — order matters because
`Blueprint`/`Brainstorm` copy neighbors and `AddMult`/`XMult` don't commute; capped at
`MAX_JOKERS_FOR_ORDER_SEARCH = 6`, returning `None` above that instead of guessing. The naive form
(a full `advise()` per permutation) was the F1 bottleneck — 5 jokers + a variance joker like
`Misprint` (whose `score_play` unrolls a ≤4096-branch probability tree) hit **194 s**. Now two
layers: a **cheap gate** returns the current order untouched when there's no copy joker and
reversing the stack gives the same top score (`math.isclose`) — an additive-only stack is provably
order-invariant; and a **surrogate search** for the rest scores only the base order's top
`_ORDER_SURROGATE_SUBSETS = 5` subsets under each permutation via `score_play` (the best *subset*
almost never changes with joker order — only its score), then runs one real `advise()` for the
winning permutation. Verified against the exhaustive search (0 deviations on 12 order-sensitive
stacks); `rank_joker_orders` stays exact for order-invariant stacks, the surrogate is a documented
approximation for the rest. `decide_action` also now computes `advise(state)` once and threads it
through (`base_advice` to the rearrange check, then the sufficient-play and B1 guards) instead of
2–3 separate calls — together this brings a 5-joker `SELECTING_HAND` decision from 15–40 s to ~0.6
s. `_is_legal_play()` filters out candidates illegal under the three
`core.bosses.BossEffect.restricts_legal_plays` bosses (`The Mouth`: only the first hand type played
this round stays legal, via `PokerHandInfo.played_this_round`; `The Eye`: can't repeat an
already-played type; `The Psychic`: can't play fewer than 5 cards) before they ever reach the ranked
list — closing PLAN.md assumption #10, since recommending an illegal move is worse than just an
imprecise number. The three boss names are hardcoded but cross-checked by a test against
`core.bosses.BOSSES`'s `restricts_legal_plays` set so the two can't silently drift apart. If
filtering would leave zero candidates (a degenerate case, e.g. `The Psychic` with fewer than 5 cards
in hand at all), `rank_plays` falls back to the unfiltered list rather than returning nothing —
showing a move of doubtful legality beats `Advice.best` crashing on an empty list.

### `solver/discard.py`

`discard_outcome()` (CLI: `advise --discard "cards"`) computes the exact EV of discarding one
*caller-specified* set of hand cards. It used to brute-force every raw draw from the remaining deck,
which collapses fast (`C(44, 5) ≈ 1,086,008` for a 5-card discard) — PLAN.md section 8.3 assumption
#9 flagged this as too slow even for Monte Carlo. It's now exact *and* fast:
`_build_classes`/`_enumerate_compositions` group draw cards into equivalence classes (rank, relevant
suit, enhancement, edition, seal, debuff — the only fields that can affect `score_play`) and
enumerate weighted *compositions* of those classes instead of raw combinations. Two cards in the
same class are provably interchangeable — swapping one for the other in a draw yields the identical
score — so each class is scored once via `advise()` and weighted by a binomial coefficient instead
of being re-scored per raw combination. Suit collapses into one class only when doing so is provably
safe: either no drawable card of that suit could complete a flush within this discard's size
(mirrors `_flush_targets`'s own reachability check), or no joker in play discriminates by suit at
all (`_SUIT_SENSITIVE_JOKER_KEYS`, 12 keys hand-verified against every `Suit`/`has_suit`/`suits_of`
use in `implementations.py`, coverage enforced by behavioral tests — not a source scan — in
`tests/test_discard.py`). This raises the practical exactness ceiling from "barely 2 cards" to
"usually all 5" without ever sampling. Capped at `MAX_DISCARD_COMPOSITIONS = 2000` *compositions*
(not raw draws) per candidate, returning `None` above that — same honest-refusal pattern as
`rank_joker_orders`; an optional `max_compositions` argument lets callers tighten that budget (see
`rank_discards` below). Deck knowledge comes from `GameState.deck`: exact when the mod bridge parsed
it from the mod's `cards` area (confirmed against golden dumps to be the literal remaining draw pile
— `hand.count + cards.count` equals the full deck size), approximated as a standard 52-card deck
minus the current hand otherwise (manual input), with the result honestly flagged either way.
`rank_single_discards()` ranks every single-card discard (≤8 candidates, always cheap) and stays
available as a narrow, always-exact building block. `rank_discards()` (CLI: `advise
--discard-search`) is the new general exact path: it brute-forces every one of up to 218 possible
discard sets of size 1–5 (the same subset space `rank_plays` searches for plays) and scores each
through `discard_outcome`, so every result is exact, not sampled — unlike `advise_discard()` below.
It uses a stricter per-candidate composition budget (`_RANK_DISCARDS_MAX_COMPOSITIONS = 200`) than a
one-off `--discard` call, because it's paying that cost up to 218 times over — a candidate whose
compressed search still exceeds that budget silently drops out of the ranking rather than being
guessed, so the top result is the best *among candidates that resolved*, not a guaranteed global
optimum. Heavy enough (and rare enough to need) that it's opt-in only — never the default in
`advise`, never called from `watch`.

`advise_discard()` (`docs/Discard Spec.md`; folded into `advise`'s default output via
`solver/actions.py`) remains the cheap default for the general case — *which* cards to discard, not
just a caller-given set. It enumerates *targets* (flush/straight/N-of-a-kind/full-house/"keep as
is") rather than discards, computes each target's hit probability exactly via the hypergeometric
distribution, and estimates the expected score per outs-count bucket from a capped sample of
representative draws (`SAMPLE_HANDS_PER_BUCKET = 16`) scored through a cheap heuristic
(`_fast_best_score`: 1-2 candidate subsets through the real `score_play`, not all 218) instead of
the exact `rank_plays`. `DiscardOption.exact` is therefore always `False` — this is a deliberate,
documented approximation (Discard Spec section 10 explicitly allows it here, unlike the final play
recommendation), verified against `discard_outcome` as ground truth to stay within the spec's 15%
tolerance. `DiscardOption.success_probability` sums the hypergeometric buckets whose outs-count
meets the merged target's `needed` — that part **is** exact, even though the per-bucket score isn't.
`rank_discards()` is the real (if slower, and itself budget-limited) alternative when
`advise_discard`'s approximation isn't good enough.

### `solver/actions.py`

`rank_actions()` merges `rank_plays()` and `advise_discard()` into one score-sorted list
(`ActionOption`, `kind: "play" | "discard"`), because playing now and discarding toward a target are
the same decision from the player's chair and used to be two lists the CLI made you compare by eye.
`ActionOption.minimum` (a real lower bound) is populated only for `"play"` — discards only have an
average (`score`) and a `success_probability`, never a guarantee, so `"hits the blind"` markers in
the renderer only ever apply to plays. Top-`top` from each source before merging is provably
sufficient for a correct top-`top` merge, so neither source is computed in full.

### `adapters/mod_bridge.py`

JSON-RPC client connecting to the mod server at `127.0.0.1:12346`. `play()`/`discard()` (0-based
card indices, matching the mod's `openrpc.json` schema) are called for real now, by
`balatro_bot/autopilot.py` via `balatro-bot autoplay` — the "read-only, no autoplay" rule from
earlier revisions of PLAN.md was itself revised (section 2: the bot's role is "advisor *and*
autopilot," not advisor-only) once the core decision engine (Phases 4–8) was solid enough to act on.
`advise`/`doctor`/`watch` remain fully read-only; only the `autoplay` path issues actions, and only
through this client's honest game-action methods
(`select`/`skip`/`play`/`discard`/`buy`/`sell`/`reroll`/`use`/`rearrange`/`start`/`menu`/`open_pack`/...)
— the mod's cheat-class methods (`set`/`add`/`load`, which set money/ante/hands directly or spawn
arbitrary cards) are deliberately never called outside test infrastructure (`tests/fake_mod.py`).
`start(deck, stake, seed=None)` and `menu()` were added for `runner.py` (Phase 9.7) — `start`
returns state already at `BLIND_SELECT`; `parse_game_state` now also reads the mod's `won` flag into
`GameState.won`, the one thing that distinguishes a won run from a `GAME_OVER` loss. `sell(*,
joker=None, consumable=None)` (mod's `sell(joker, consumable)`, exactly one index) was added for the
shop sell-replace policy (improvement A1) — an eternal joker can't be sold and the mod errors if
asked, so `evaluate_shop` never nominates one. `rearrange(*, hand=None, jokers=None,
consumables=None)` (mod's `rearrange`, exactly one area, arg is a permutation of that area's current
0-based indices) was added for improvement D1 — the autopilot only ever reorders `jokers`.
`open_pack(*, card=None, skip=None)` wraps the mod's RPC method literally named `pack` — renamed on
the client side specifically to avoid reading as the same concept as `buy(pack=...)`'s `pack`
keyword, which indexes a *booster pack in the shop*, a completely different area
(`GameState.shop_packs`) from the one `open_pack` indexes (`GameState.pack`, the currently open
pack's contents).

### `balatro_bot/autopilot.py`

`decide_action(state)` dispatches by `GameState.phase`, closing the Phase 9 decisions that reduce to
a verdict (plan section 6, "Autopilot (Phase 9)"). Two companion functions sit next to it:
`dispatch_action(bridge, action)` — the single `Action.kind` → RPC-method translation
(`play`→`bridge.play`, `buy`→`bridge.buy(card=…)`, …), extracted from the `ui/tui.py` loop so the
live loop and `runner.py` share one copy; and `describe_action(action)` — the short log line
("сыграл 5H 5S", "купил в магазине: Joker"), likewise shared. On `SELECTING_HAND` (9.1) it starts
from `solver.actions.rank_actions`, the same merged list a human sees, then applies one correction:
`rank_actions` sorts plays and discards by expected value, and a discard's EV is optimistic by
construction (`ActionOption.exact = False`), so "discard toward a flush" can outrank "play this pair
now" even when the pair already *guarantees* clearing the blind. A human reading the list sees the
"hits the blind" marker and isn't fooled; the raw top-1 would trade a certain win for a gamble. So
`decide_action` first checks `advise(state).cheapest_sufficient` — the most economical play whose
*minimum* (not mean) already covers the remaining requirement — and plays that if it exists. Two
more guards then sit between that check and taking `rank_actions`'s top-1 (improvement B1,
run-6-confirmed): `_on_pace_without_discard` plays the best hand outright (skipping `advise_discard`
entirely) when `_pace_projection` already covers the remaining requirement with a
`_DISCARD_PACE_MARGIN = 1.5` cushion and ≥ 2 hands are left. **That projection used to be `best ×
hands_left`, and improvement B2 replaced it**: repeating the best hand assumes every remaining hand
scores like it, when the best hand is played *first* and the rest are drawn from what is left — run
11's last round went 2 754, 2 052, 2 240 against a projection of four hands at 2 754, and the error
always favoured not discarding. Future hands are now valued at the round's observed average once
there is history, and at `best × _PACE_DECAY` before then (0.75, measured from that round, sample
size stated, due for re-measurement by the batch). The projection can only shrink, so the guard is
strictly more conservative than the version B1 shipped — the case where `cheapest_sufficient` came
back empty only because a variance joker (`Misprint`) dragged a play's floor under the bar while its
mean sits well over; and `_discard_edge_is_noise` overrides a top-1 discard back to the best play
when the discard's EV beats it by less than `_DISCARD_EDGE_MARGIN = 1.15`, i.e. by less than the
±15% tolerance `advise_discard` documents for its own estimate (§7 `docs/Discard Spec.md`) — run 6
spent its last discard on a 10,000 boss to trade a 7,371 flush for a 7,427 target. Both guards live
only in the autopilot; `rank_actions`/`advise`/`watch` output is untouched. Only otherwise does it
take `rank_actions`'s top-1 (which may then be a discard). Chosen `Card`s are translated to 0-based
hand indices via `_indices_of` (robust against duplicate-valued cards). On `BLIND_SELECT` (9.2, the
skip-or-play slice) `decide_skip(advice)` is a deliberately conservative *policy* over
`solver.skip.evaluate_skip`'s already-honest numbers, not a new calculation: skip only when
`SkipAdvice.tag_dollars` is known exactly (currently only `Investment`/`Economy Tag`) and strictly
exceeds `play_reward_min`. Structural tags (a free joker/voucher/pack) never trigger a skip on their
own — not because they're worthless (experienced players often skip *for* exactly those), but
because putting a dollar figure on them here would mean guessing, and this project doesn't. When
skip isn't proven by a number — including when skipping isn't even legal, the Boss Blind is up next
— the decision is `select`, play it. On `ROUND_EVAL` (the screen between winning a round and
reaching the shop) there's nothing to decide — `cash_out` unconditionally, or the loop would simply
get stuck there, the same reason `select`/`skip` exist for `BLIND_SELECT`. On `SHOP` the policy is
equally narrow: buy the single highest-`expected_uplift` joker offer from
`solver.shop.evaluate_shop` that's `known`, `affordable`, has a free slot, and clears
`_worth_buying` (improvement A2: uplift ≥ `_MIN_BUY_REQ_FRACTION = 0.03` of the next blind's
requirement, not merely > 0 — a joker adding near-nothing would just be sold as dead weight next
shop; when the requirement is unknown, e.g. manual input, it falls back to > 0).
`JokerOffer.interest_lost` deliberately plays no part in the buy decision (dollars vs. score points,
same incommensurability as `decide_skip`) — it's informational only. At most one purchase per
`decide_action` call, never a shopping list computed from a single stale snapshot: `evaluate_shop`'s
counterfactual for a second joker doesn't account for the first one just bought (order-sensitive
jokers like `Blueprint` would make that silently wrong), so the next purchase is decided fresh on
the next poll instead. Then a **voucher** (improvement A4, `_decide_voucher_action`): tier-1
(`value_unit == "score"`) uses the same `_worth_buying` bar as a joker; tier-2 (`value_unit ==
"dollars"`) buys only when net-positive in dollars (`expected_uplift >= item.price`); tier-3
(`heuristic_value`) buys only structural upgrades, `>= _heuristic_voucher_bar` — normally
`_MIN_HEURISTIC_VOUCHER_VALUE = 5.0`, but for a shop-slot `Overstock` voucher that bar scales down
(−1.0 per idle joker slot, floored at 3.0) when the bot is cash-rich (improvement A7). Acting on
tier 3 is an explicit user decision. Vouchers take no slot, so only `affordable` gates them; ordered
after the joker buy, before packs. Then a **Planet from the shelf**
(`_decide_consumable_buy_action`, improvement C2), which is where the single largest measured defect
of the deck rotation is repaired: consumables never reached this function at all, and 239 affordable
offers went unbought across 32 runs, starving the hand-level channel the whole joker economy depends
on (see the `solver/shop.py` entry for the chain). The gate is deliberately **not** A2's
`_worth_buying`. A2 asks "is this worth a permanent slot" — a Planet takes no permanent slot (the
consumable slot frees on the next hand, since `_decide_consumable_action` uses any held Planet
without a bar), and its uplift is measured on hands dealt now while the level-up lasts the run, so
the number is a known under-estimate; applying a bar calibrated for a complete measurement on top of
an incomplete one doubles the error. So `_worth_buying_consumable` uses
`_CONSUMABLE_NOISE_FRACTION`, assigned from `_DEAD_WEIGHT_REQ_FRACTION` (0.5 %) as the same object
for the same reason `_PACK_MONEY_RESERVE` is assigned from `_REROLL_MONEY_RESERVE`: the
justification is word-for-word identical (the sign already carries the meaning; the fraction only
guards sampling noise) and two constants with one justification drift apart. **Both bars were
measured before choosing**, on 22 shelf-Planet decisions replayed from the journals: A2's 3 % fires
5 times and never past ante 4 — that is, never where the runs actually die — against 9 for the noise
bar, which fires at antes 6 and 7 too. The purchase must still leave `_PACK_MONEY_RESERVE`, and that
reserve is not free: replaying all 135 shelf-Planet decisions from the rotation, 67 clear the bar,
35 are bought and **the reserve blocks 32 — 48 % of what the bar admits**, concentrated in antes 1–2
(10 of 11, then 12 of 19) where the bot is poorest and where a level-up would compound longest.
Reusing the constant was the deliberate choice (one justification, one object); whether a cheaper
item deserves a smaller reserve is an open batch question, recorded in PLAN.md §9.8 rather than
guessed at here. Ordered after the joker and voucher buys (both claim permanent resources and are
already calibrated) but **before** packs and reroll: a Celestial pack is the hedged version of this
same channel at twice the price with less information, and reroll is where this money currently goes
(A22: $603 of $800 rolled into a full board). One purchase per call, same discipline as the joker
buy and for the same reason. Tarots cannot reach this branch — `solver/shop.py` gives them no number
— so no separate guard is needed. Then a **strong sell-replace** (improvement A6): a full-slots
sell-replace whose captured offer itself clears the `_worth_buying` bar runs here, *before* the pack
branch — a cheap hedge pack shouldn't pre-empt swapping in a clearly better joker (run 6 left a
+3576 offer untaken for 2–3 polls). No qualifying strong replace → try a **Buffoon or Celestial
pack** (improvement A3 added Celestial): the generic pack loop buys the pack (`Action.kind =
"buy_pack"` → `bridge.buy(pack=…)`) if `PackPurchaseOffer.expected_uplift` (the Monte-Carlo estimate
above) is positive, affordable, and `has_slot` (always `True` for Celestial). The pack branch used
to keep a `> 0` bar rather than A2's fraction, on the reasoning that a pack is a hedged choice of
several cards — **improvement A13 removed that exception, and the reasoning is recorded here so it
is not restored on the strength of the old argument.** Run 12 showed the consequence: on antes 6–7
the bot bought four packs worth 408–873 while a joker that visit had to clear 1 050–2 100, i.e. it
paid the same dollars from the same pocket for a third of the return it demanded elsewhere, and
twice spent down to $2 doing it. Being a hedge explains why a pack's *outcome* varies around its
expectation; it does not justify accepting a lower expectation. A pack now faces `_worth_buying`
exactly as a joker buy does, and must leave `_PACK_MONEY_RESERVE` behind — deliberately the same
object as `_REROLL_MONEY_RESERVE`, since the justification (money under the $25 interest cap earns
$1 per $5 per round, so spending it costs more than it looks, and the purchase must leave enough to
act on what it was *for*) is word-for-word the same and two copies would drift apart. No qualifying
pack either → the **ordinary sell-replace** pass (`_decide_replace_action` with `strong_only=False`,
improvement A1; the A6 strong pass above already ran before packs): when slots are full, sell the
weakest held joker (`JokerOffer.replaces`, computed in `evaluate_shop`) if the best shop offer
strictly beats the victim's contribution **and** either the victim is dead weight (contribution
below `_DEAD_JOKER_REQ_FRACTION = 0.03` of the next blind's requirement, via
`_next_blind_requirement`) or the offer is at least `_REPLACE_UPLIFT_RATIO = 2.0`× stronger (guard
against churn on sampling noise). `Action.kind = "sell"` → `bridge.sell(joker=…)`; it's a standalone
action — the freed slot lets the next `decide_action` call buy the replacement fresh, same
one-action-per-call discipline as the rest of the shop. Both threshold constants are calibrated on
live runs. Then **dead weight** (`_decide_dead_weight_action`, improvement A9): a held joker whose
measured contribution is *negative* is worth less than an empty slot, so selling it raises the score
and returns money — no shop offer required, and it works with slots free, which is exactly what the
old full-slots-only gate could not see. Sells the most-negative non-eternal joker when its
contribution is below `-_DEAD_WEIGHT_REQ_FRACTION × requirement` and at least `_MIN_JOKERS_KEPT = 2`
jokers remain. The 0.005 fraction is an order of magnitude below `_DEAD_JOKER_REQ_FRACTION` on
purpose: that one judges strength, this one is only a noise guard, since the sign already carries
the meaning. The floor guards a cascade (each sale makes the next look better while Stencil is
held), though measured on run 8's board the cascade terminates by itself after one sale. Honest
limitation: the contribution is measured on hands sampled *now* and a sold joker does not come back,
so a joker that would scale later reads at its current value — the same horizon problem
`interest_lost` carries and does not solve. No qualifying replacement either → **reroll**
(`_decide_reroll_action`, improvement A5): the last branch before leaving, so it only fires when
nothing in this shop is worth buying/selling. Reroll when the blind requirement is known,
`RerollOutlook.expected_best_uplift` clears the same `_worth_buying` bar as a joker buy, and
`state.money − reroll_cost ≥ _REROLL_MONEY_RESERVE = 12` (leaves cash for the buy the reroll is
*for*, and stops a drain to $0 — run 4's bug). A5 assumed the escalating price plus that reserve
would end a streak on its own; run 7 disproved it — 21 rerolls in one run, two streaks of 4 that
drained a whole visit and bought nothing — because `expected_best_uplift` is stationary (see
`solver/shop.py`): it clears an absolute bar identically on every poll, so only running out of money
ever stopped it. **Improvement A8** adds the two conditions that were missing, both staying inside
the project's refusal to price points in dollars: an **opportunity cost** — `expected_best_uplift`
must beat the best `expected_uplift` already on the shelf by `_REROLL_SHELF_MARGIN = 1.5`, so a
strong offer that failed only on `affordable` or `has_slot` is saved for rather than rolled away —
and a **structural bound**, `economy.rerolls_done(cost, used_vouchers) < _MAX_REROLLS_PER_SHOP = 2`.
That roll count is recovered from observed state rather than tracked across calls, keeping
`decide_action` a pure function: the game's `calculate_reroll_cost` makes `reroll_cost = base +
rolls this visit` with the counter reset each round, and the base is $5 less $2 per redeemed Reroll
Surplus / Glut. A Reroll tag or Chaos the Clown temporarily lowers the price and makes the derived
count an under-estimate — it errs toward allowing a roll, never toward blocking one. **Improvements
A22 and A21 then fixed the same policy in opposite directions**, because the 35-run rotation showed
it failing both ways at once. **A22**: the reroll branch never asked whether a find could be *used*.
It is the last branch, reached only after buy, voucher, Planet, replace and dead-weight sell have
all declined — precisely when the board is full and staying full. Measured: **167 of 216 rerolls (77
%) were made with a full board, $887 of $1 141**, and of 16 shop exits holding an offer worth over
200, all 16 read «слоты полны» and none read «дорого» — the roll found exactly what it was asked
for, at trivial prices, and the find was unusable. `_reroll_target_bar` now answers what a find
would actually have to clear: with a free slot, `_worth_buying` as before; with full slots, the bar
`_decide_replace_action` itself applies (strictly above the victim's contribution, and either the
victim is dead weight or the offer is `_REPLACE_UPLIFT_RATIO`× stronger) — read from the same
constants rather than restated, or the gate would license rolls the replace would then refuse; with
full slots and nothing sellable, `None`, meaning no result could help. Replaying the journals
through the real gate: **123 of 167 blocked (74 %), ~$657**. **A21** is the same contradiction
inverted: 87 shop exits with a *free* joker slot and no purchase, **84 of them (97 %) holding under
$17**, median $11, 63 of those at antes 1–2 where the board is laid down — the $12 reserve let 3 of
87 roll. The reserve was $12 because it was the *same object* as `_PACK_MONEY_RESERVE`, justified as
"one justification, one constant." A21 showed the justifications are not one: a reroll is the only
purchase whose money is needed **afterwards** — it buys nothing, it only reveals what could be
bought — while a pack or a Planet is complete in itself. So `_REROLL_MONEY_RESERVE` is now
`TYPICAL_JOKER_PRICE` ($5, and the rotation's 575 shelf offers put the median joker price at exactly
$5), `_PACK_MONEY_RESERVE` stands alone at $12, and the victim's `sell_value` counts toward
available money when slots are full (not counting it would compare the two sides in different states
— the A11 mistake). This does not restore run 4's drain: back then the reserve was the only brake,
whereas A8's `_MAX_REROLLS_PER_SHOP` now bounds the streak and the "reserve remains after paying"
condition makes the floor constructive. **A third consumer surfaced during implementation and is
worth recording**: `_heuristic_voucher_bar` (A7) also read `_REROLL_MONEY_RESERVE`, using it for a
third question again — "is the bot cash-rich" — so lowering the reroll reserve would have silently
moved A7's wealth test from $12 to $5. A test caught it; A7 now has `_CASH_RICH_RESERVE = 12` and
its behaviour is unchanged. One number answering three different questions was not economy, it was
the defect. `Action.kind = "reroll"` → `bridge.reroll()`, a standalone action, re-decided fresh each
poll. No qualifying reroll either → `next_round`, carrying a reason built by `_shop_nothing_reason`
and, since A22, by `_reroll_block_reason` — without which a journal line cannot separate "did not
roll because the find had nowhere to go" from "did not roll because the money was short," the same
indistinguishability that let A13 draw a wrong conclusion and let A22 itself sit unnoticed for
twelve runs. **That helper's first version (E1a) was wrong in an instructive way**: it named the buy
bar as the cause of leaving empty-handed regardless of whether the bar was the obstacle, so run 12's
journal contains lines like `лучший оффер 8145 не берёт порог 2100` about an offer clearing that bar
fourfold. A wrong conclusion was drawn from it before the error was spotted. It now *determines* the
blocker from `JokerOffer`'s existing `has_slot` / `affordable` / `replaces` instead of asserting
one, and says "below the bar" only when that is true. The general rule the episode illustrates: a
reason line that guesses at causation is worse than no reason line, because the journal exists
precisely so its statements need not be re-derived. **C2 found the same defect wearing new
clothes**: with consumables invisible to the shop branch, `на витрине нет оценённых джокеров`
printed while a $3 Saturn lay on the shelf — literally true, practically false, the exact A13
failure. `_consumable_block_reason` now appends the consumable half, determining its blocker the
same way (bar, then consumable slot, money, reserve) from the same fields
`_decide_consumable_buy_action` decides on. It is appended rather than merged into the joker
sentence because the two sides run different bars, so "the best offer" across them is not defined;
un-priced Tarots are counted rather than described, since there is nothing to say about them but
they were on the shelf. Arcana/Spectral/Standard packs stay untouched — no computed number. On an
open pack (`PACK_OPEN_PHASES` — Steamodded collapses the vanilla per-type states into one
`SMODS_BOOSTER_OPENED`, so the *type* is read from `state.pack` contents, not the phase name)
`_decide_pack_action` takes the top `solver.pack.evaluate_pack` result: a planet always (leveling
can't hurt); a joker as long as there's a free slot — **no** strictly-positive-uplift bar here
(unlike a shop-joker buy), because the pack is already paid for so the slot is the only cost, and
`joker_uplift` over ~12 sampled hands routinely reads exactly `0.0` for conditional jokers that just
didn't fire in the sample, not because they're worthless. `skip_pack` is the fallback when nothing
qualifies (no free slot, only unimplemented jokers, or an Arcana/Spectral/Standard pack —
`evaluate_pack` returns empty since those need the consumable-mechanic layer), so the run declines
rather than stalling — a deliberate small loss. On `SELECTING_HAND`, before the play/discard step
described above, `decide_action` now also checks `solver.consumables.evaluate_planet_consumables`
(Phase 9.4's first slice) and uses whatever Planet card it finds — same non-conservative shape as
`_decide_pack_action`, since a level-up still can't hurt regardless of context. **Tarot cards
(improvement C1) then get the opposite policy, and the difference is the point:** a Planet card
costs nothing but itself, while a Tarot permanently rewrites a *deck card* for the rest of the run —
`The Tower` erases its rank and suit outright. So a Tarot is used only on a strictly positive
score-tier uplift that also clears `_worth_buying`, the same fraction-of-requirement bar as a joker
buy (A2), for the same reason: spending a one-shot resource and permanently altering the deck for a
marginal gain is a bad trade. Dollar-tier offers (`Hermit`/`Temperance`) never drive an automatic
use — dollars versus points, the usual refusal — and `render_tarot_advice` shows them to the human
instead. `Action(kind="use")` now carries the target hand indices and `dispatch_action` forwards
them as `ModBridge.use(cards=…)`, which the bridge already accepted but was never passed, since
Planet cards need no targets. The honest limitation mirrors the Planet one and is sharper here: the
uplift is measured on *this* hand while the change lasts the whole run, and a level-up keeps paying
where a Stone card can ruin later hands. Then `_decide_rearrange_action` (improvement D1) runs
`rank_joker_orders` on the current hand (handing it the already-computed `advise(state)` as
`base_advice` — F1) and, if the best permutation beats the current order by ≥
`_MIN_REORDER_GAIN_FRAC = 0.02` relative score, emits `Action(kind="rearrange")` (→
`bridge.rearrange(jokers=…)`, a permutation of current joker indices); the autopilot used to always
play in slot order even though `watch` searches orderings by default. Standalone action, one per
call; re-checked each hand (best order can differ per hand), the threshold prevents flip-flopping on
noise. Genuinely unhandled phases (animation states, ...) return `None` — the loop does nothing
there, same as `watch`. `include_discards` mirrors `watch`'s `--no-discard`/`rank_actions`'s own
flag, not a separate switch.

### `ui/render.py`

terminal formatting shared by `advise`/`doctor`/`watch`/`autoplay`, so the commands can't drift into
inconsistent output. `render_top_actions()` is the default headline for both `advise` and `watch` —
the merged play+discard list is always shown, never behind a flag (a standing product requirement,
not just today's default). `render_advice()` (plays only) is kept around as a lower-level building
block, not wired into either command's default path anymore. **`ui/tui.py`** — `watch()` polls
`ModBridge.game_state()` on an interval and only clears/redraws when the returned `GameState`
compares unequal to the last one (frozen dataclasses give this for free), so an idle screen doesn't
flicker. No dependency on `textual`/`rich` despite PLAN.md's original stack section — plain ANSI
(`\x1b[2J\x1b[H`) instead, to keep the zero-dependency rule intact. Unlike `advise` (where
`--joker-order` is opt-in), `watch` runs the joker-order search on every redraw by default —
`--no-joker-order` opts back out — since a live session is exactly where catching a suboptimal joker
order matters most; the tradeoff is up to 720 extra `advise()` calls per poll when 2+ jokers are
held. Discards are considered in the merged list by default too — `--no-discard` opts back out
purely for poll-interval budget, not because the feature is optional; `state.discards_left <= 0`
already yields zero discard options on its own, no flag needed for that case.

`autoplay()` is the same polling loop with the right to act: on each iteration it calls
`autopilot.decide_action()` and, if it returns something, hands it to
`autopilot.dispatch_action(bridge, action)` before rendering — otherwise it behaves exactly like
`watch`. The pause/handoff switch (key `p`) is checked every iteration, i.e. between every
individual action, not just between runs — an explicit standing requirement (PLAN.md section 2 and
section 6's 9.1), not a nice-to-have: the human must be able to grab the wheel mid-run. Real
single-keypress input (no Enter) comes from putting stdin into cbreak mode via `termios`/`tty`
(stdlib, no new dependency) inside a context manager that always restores the original terminal
settings, even on exceptions or `Ctrl+C`; if stdin isn't a TTY (piped, or under test), it silently
disables the key-reading side rather than failing — `autoplay` still runs, just without a way to
pause. Tests never touch the real terminal at all: passing a `key_reader` callable bypasses the
cbreak context manager entirely, matching the existing `sleep` injection pattern for
`iterations`-bounded test loops. If the mod rejects an action the engine honestly computed (e.g. a
boss restriction `_is_legal_play` doesn't cover yet), the loop prints the error and keeps polling
with the last known state rather than crashing or retrying the same call forever.

### `balatro_bot/runner.py`

Phase 9.7, the run-runner. `play_run(bridge, *, deck, stake, seed=None, …)` drives one whole run:
`ModBridge.menu()` then `.start(deck, stake)`, then a loop of `decide_action` → `dispatch_action` →
next state until a terminal state — `GameState.won` (outcome `"won"`), `phase == "GAME_OVER"`
(`"lost"`), or a stall (`"stuck"`). It is *not* a polling loop: every action RPC returns the settled
next state, so `game_state()` is only re-polled to wait out an animation phase
(`HAND_PLAYED`/`DRAW_TO_HAND`/`NEW_ROUND`/`PLAY_TAROT`), the only phases where `decide_action`
returning `None` is not a stall. `None` on any other phase means an unclosed decision
(Tarot/Spectral/Standard/Buffoon packs) — the run stops as `"stuck"` with that phase in
`RunReport.note`, rather than guessing. `"stuck"` also covers `stall_limit` (default 3) consecutive
no-progress steps or mod rejections, and `max_steps` (default 2000). A single managed run prints one line per decision via the `on_step`
callback and a batch one line per run via `on_run`, so a long run never looks hung. Any keypress via `key_reader`
ends the run `"aborted"` and stops the batch — the human took the wheel. `RunReport` carries the
outcome, how far it got (ante/round), and a `DecisionEntry` log (the golden-test idea, but for a
whole run). `play_run(..., adopt=True)` skips the `menu()`/`start()` pair when the game is already
mid-run (phase neither `MENU` nor `GAME_OVER`) and continues from that state instead — without it
the runner overwrote whatever run the player had just set up, which made the only play-many-runs
mode unusable on a live game (E2, first slice). `RunReport.adopted` marks such a run, and it has to:
the deck is recovered from `GameState.deck_type`, but the stake is not in `GameState` at all, so for
an adopted run the stake is only what the caller asked for and must not be reported as observed.
`run_batch(...)` runs N per stake across `STAKES` (`WHITE`→`GOLD`, cumulative order verified against
`game.lua`'s `stake_level`) and `render_batch_summary` prints the win-rate table. Exposed via
`balatro-bot autoplay --deck …` (managed run) / `--all-stakes --runs N` (batch); without `--deck`,
`autoplay` stays the live `ui/tui.py` loop. The whole 9.1–9.7 loop has only ever run against
`tests/fake_mod.py` (which doesn't simulate real play or phase transitions) — the actual win-rate
measurement still needs a Mac with the game.

**The run journal (improvement E1a).** `DecisionEntry` held step / phase / ante / round / money /
action — enough to watch a run, nothing like enough to *diagnose* one afterwards. Every diagnosis in
runs 8–10 came from reading a live terminal, and E1, the win-rate batch, consists entirely of runs
nobody watches. It now also carries `chips_scored`, `requirement` (from
`autopilot._next_blind_requirement`), `hands_left`, `discards_left`, the jokers in slot order, and
`reason` — the numbers the decision was actually taken on, carried out of `decide_action` on the new
`Action.reason` and filled at the six sites that already computed them. Nothing is recomputed; those
values were simply being discarded. Without `requirement`, `chips_scored` has nothing to be measured
against, and the gap between the two is what explains a lost run. `play_run(log_dir=…)` writes one
JSON file per run (`report_to_json` + `write_run_log`, naming and dump settings taken from
`balatro-bot record`), exposed as `autoplay --log DIR`. `play_run` is a thin wrapper over
`_play_run` specifically so the log is written on *every* exit — the crash and stall paths are the
ones it exists for, and hanging a write off each of a dozen `return`s would eventually miss one.
`report_to_json` builds its dict by hand rather than through `asdict`, because the file is read a
month after the run and its field set should change deliberately. **`DecisionEntry.board`
(improvement E1b)** carries what the board was *worth*, not just its labels: a `BoardEntry` per slot
with contribution and sell value, lifted from the `ShopAdvice.held` that `evaluate_shop` already
computes for the sell decision and used to throw away. Two open questions were stuck on exactly that
omission — whether run 12's declined 8 145 offer was refused legitimately (A13 would not claim
either way without it) and what the run's joker churn cost. It is attached by a wrapper rather than
at each `return`: the shop branch has eight exits, several inside helper functions, and per-site
filling is how E1a ended up covering six of fourteen decision sites — the same reasoning that makes
`play_run` a wrapper over `_play_run`. Non-shop actions keep an empty tuple, since contribution is a
shop-screen measurement, and the JSON always emits the key, because a missing key and an empty list
mean different things to whoever parses the file later. **`Action.outlook` (E1d)** does the same for
the hand screen: `best_play`, `best_discard` and `discards_left` on every `SELECTING_HAND` decision,
because the journal used to record only the chosen action's score and, in `reason`, the runner-up —
usually another discard — so "what did this discard give up" was not answerable. Extracting it over
a 16-run batch matched 2 cases of ~81, which is why B3 could not be decided and had to be corrected
rather than implemented. `best_discard` is `None` rather than `0` when `rank_actions` was skipped,
since the `_on_pace_without_discard` shortcut skips it on purpose (F1) and "not considered" is not
"nothing to discard". Note also that `chips_scored` is recorded *before* each action, so a round's
last play never appears — `blind_beaten` on the closing entry is what a round-level analysis must
use instead. `stake_observed` is `true` exactly when the runner started the run — it passed the
stake to `start` itself — and `false` only for an adopted run, whose stake the mod never sends.

**What the first journalled run taught (improvement B2).** Run 11 (ZODIAC, lost at ante 5) showed
the journal explaining every shop decision and no gameplay decision at all: 19 of 98 entries carried
a reason and all 19 were shop actions, while 31 plays, 7 discards, 12 blind selects, 5 pack picks
and 12 shop exits carried none. The field existed to answer "why" without a live terminal and
answered it for a third of the run. Every branch with numbers behind it now records them, and
`rank_actions` is asked for `top=2` so the runner-up rides along — it ranks everything and slices at
the end, so that is free. The same run also produced the counters `RunReport` now exposes —
`plays_made`, `discards_used`, `rounds_with_discards_unspent` — because its central symptom
(discarding fell to zero from ante 3, ten rounds closed with the full allowance unspent, the losing
round leaving three discards in hand) was found by a human reading ninety-eight lines. It is now the
summary's second line.

**Reconnecting rather than failing (improvement E2, second half).** Every `ModBridgeError` inside
the loop used to end the run `error`, but the bridge drops for reasons that are not a dead game —
the mod is mid-animation, the window is backgrounded, a socket blips. `_reconnect` polls
`game_state` with doubling backoff up to `_RECONNECT_DEADLINE` and returns a **fresh** state: the
game may have advanced while the connection was gone, so resuming from the pre-outage state would
act on a stale picture. There is deliberately no new exception type — "the mod refused this action"
and "the bridge is gone" arrive as the same `ModBridgeError` yet need opposite treatment (a stall
versus a wait), and the honest discriminator is whether `game_state` answers, which is what
`_bridge_alive` asks. That also fixed a real misclassification: a dropped connection during
`dispatch_action` was being recorded as a *rejected action* and counted toward `stall_limit`.
`run_batch` gained the matching guard — it did not stop when a run errored, it appended the report
and started the next one, so a dead bridge produced N useless `error` reports in seconds; PLAN.md
had claimed the batch stopped, and it did not. **What this does not do is restart a crashed game.**
Nothing in this project launches the game — `subprocess` appears only in `install.py` — so that
would mean spawning the game and then choosing a deck and stake to start a run, which is the user's
decision, not the bot's. This half survives a blip, not a crash.

### `install.py`

one-shot installer for the macOS mod stack (Lovely Injector, Steamodded, the BalatroBot mod).
Locates Steam libraries (including ones on secondary drives via `libraryfolders.vdf`), downloads the
latest GitHub release of each component behind a `Fetcher` protocol, and unpacks defensively
(rejects archive members with absolute or `..` paths). Driven by the `install`/`doctor`/`record`
subcommands in `cli.py`; manual step-by-step fallback lives in `docs/mac-setup.md`.
