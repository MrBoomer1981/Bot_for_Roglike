# Improvement log

Every improvement this project made after a live run: what was measured, what changed, and
which tests pin it. This is the *completed* half of [PLAN.md](../PLAN.md) item 9.8 — the
open half, and the ranking of what to do next, stay there.

**Why it is a separate file.** These entries were 85 KB of PLAN.md's 227 KB — 37 % of the
authoritative design doc was a changelog, growing by ~3 KB per improvement. PLAN.md is the
plan; this is the record.

**Order is chronological**, in the order the work was actually done, not alphabetical: labels
were assigned as items were *found*, so A3 predates A2 and F3 sits between A10 and C1. Read it
top to bottom and it is the project's history; search it by label and it is a reference.

**How to add one.** An open item lives in PLAN.md item 9.8 under "Open, ranked". When it
closes, append its write-up here in chronological order and add a row to the index table in
item 9.8 — that index is what keeps citations like "§9.8 A12" resolving.

**Labels that are not entries here**, so a search for them does not come up empty:

| Label | Where it is |
|---|---|
| A17 | PLAN.md section 8.4 — it closed three §8.3 rows, so it is written up as a defect fix |
| A18 | inside [A20](#a20-the-suite-now-refuses-the-impossible--done) — it is one of the four defects A20's invariants were built from |
| E1a | PLAN.md item 9.8, inside the still-open **E1** item — the journal it added is what the open batch work runs on |

## Index

| Label | Entry |
|---|---|
| **A1** | [Joker sell-replace — done.](#a1-joker-sell-replace--done) |
| **D1** | [Joker rearrange — done.](#d1-joker-rearrange--done) |
| **A3** | [Buying a Celestial pack from the shop — done.](#a3-buying-a-celestial-pack-from-the-shop--done) |
| **A2** | [A stricter joker-buy threshold — done.](#a2-a-stricter-joker-buy-threshold--done) |
| **A4** | [Buying vouchers — done.](#a4-buying-vouchers--done) |
| **B1** | [Temper the over-aggressive discarding — done (run 6 confirmed).](#b1-temper-the-over-aggressive-discarding--done-run-6-confirmed) |
| **A5** | [Shop reroll — done (run 6's economy ceiling).](#a5-shop-reroll--done-run-6s-economy-ceiling) |
| **F1** | [Decision-loop performance — done.](#f1-decision-loop-performance--done) |
| **A6** | [Shop branch order — sell-replace vs. a cheap pack — done.](#a6-shop-branch-order--sell-replace-vs-a-cheap-pack--done) |
| **A7** | [Voucher tier-3 threshold when cash-rich with empty joker slots — done.](#a7-voucher-tier-3-threshold-when-cash-rich-with-empty-joker-slots--done) |
| **A8** | [The reroll policy over-rerolls and burns whole shop visits — done.](#a8-the-reroll-policy-over-rerolls-and-burns-whole-shop-visits--done) |
| **F2** | [`evaluate_shop` rebuilt from scratch after every reroll — done.](#f2-evaluate_shop-rebuilt-from-scratch-after-every-reroll--done) |
| **A9** | [The autopilot cannot shed dead weight while a joker slot is free — done.](#a9-the-autopilot-cannot-shed-dead-weight-while-a-joker-slot-is-free--done) |
| **A10** | [The shop valued jokers at the wrong moment of the round — done.](#a10-the-shop-valued-jokers-at-the-wrong-moment-of-the-round--done) |
| **F3** | [The probability tree was the whole performance problem — done.](#f3-the-probability-tree-was-the-whole-performance-problem--done) |
| **C1** | [Tarot consumables](#c1-tarot-consumables) |
| **A11** | [An audit of the whole "wrong state to evaluate from" defect class — done.](#a11-an-audit-of-the-whole-wrong-state-to-evaluate-from-defect-class--done) |
| **A12** | [The §8.3 assumptions audited against the game's own source — done.](#a12-the-83-assumptions-audited-against-the-games-own-source--done) |
| **F4** | [Event dispatch — measured and rejected, not deferred.](#f4-event-dispatch--measured-and-rejected-not-deferred) |
| **B2** | [The autopilot stopped discarding, and the journal could not say why — done.](#b2-the-autopilot-stopped-discarding-and-the-journal-could-not-say-why--done) |
| **A13** | [The journal caught a lying explanation and a bad pack policy — done.](#a13-the-journal-caught-a-lying-explanation-and-a-bad-pack-policy--done) |
| **A14** | [Blind skipping was switched off, and nobody noticed for eleven runs — done.](#a14-blind-skipping-was-switched-off-and-nobody-noticed-for-eleven-runs--done) |
| **A15** | [A skipped blind is not a pending one — done.](#a15-a-skipped-blind-is-not-a-pending-one--done) |
| **A16** | [The tag bar was wrong by mechanism, not by number — done.](#a16-the-tag-bar-was-wrong-by-mechanism-not-by-number--done) |
| **E1b** | [Joker contributions in the journal — done.](#e1b-joker-contributions-in-the-journal--done) |
| **E1c** | [The batch was measuring one run N times — done, and it failed silently.](#e1c-the-batch-was-measuring-one-run-n-times--done-and-it-failed-silently) |
| **A19** | [A mod refusal often means «not yet», not «not allowed» — done.](#a19-a-mod-refusal-often-means-not-yet-not-not-allowed--done) |
| **A20** | [The suite now refuses the impossible — done.](#a20-the-suite-now-refuses-the-impossible--done) |
| **C2** | [The bot could not buy consumables at all, and that was the root of the loss pattern — done.](#c2-the-bot-could-not-buy-consumables-at-all-and-that-was-the-root-of-the-loss-pattern--done) |
| **A21 + A22** | [The reroll policy was wrong in both directions at once — done.](#a21--a22-the-reroll-policy-was-wrong-in-both-directions-at-once--done) |

## A1. Joker sell-replace — done.

`solver.shop.joker_contributions` computes the mirror
`joker_uplift` counterfactual (how much the best score drops if each joker is removed from
its slot). `evaluate_shop` attaches the weakest non-eternal joker as a `ReplaceCandidate`
to every priced offer (`JokerOffer.replaces`). `autopilot._decide_replace_action`: when
slots are full, sell the victim if the offer is strictly better than its contribution
**and** either the contribution is below `_DEAD_JOKER_REQ_FRACTION` (3%) of the next
blind's requirement (dead weight) or the offer is twice as strong
(`_REPLACE_UPLIFT_RATIO`, a guard against churn on noise). Selling is a standalone action
(`Action.kind="sell"` → `ModBridge.sell(joker=…)`), the purchase is decided by the next
call on the freed slot. Both thresholds are calibrated on live runs. A real trade (not
just dead weight) is explicitly allowed by the user. Tests —
`tests/test_shop.py::TestПродажаЗамена`, `tests/test_autopilot.py`,
`tests/test_mod_bridge.py`.

## D1. Joker rearrange — done.

`autopilot._decide_rearrange_action` on `SELECTING_HAND`
(after consumables, before play/discard) runs `rank_joker_orders` on the current hand; if
the best order gives a relative score uplift `>= _MIN_REORDER_GAIN_FRAC = 0.02`, it emits
`Action(kind="rearrange")` → `ModBridge.rearrange(jokers=…)` (a permutation of the current
indices). A standalone action, re-checked on every hand; the threshold cuts flip-flopping
on noise. Cap `MAX_JOKERS_FOR_ORDER_SEARCH` (6). Tests — `tests/test_autopilot.py`,
`tests/test_mod_bridge.py`.

## A3. Buying a Celestial pack from the shop — done.

`solver.shop._planet_uplift_pool`
computes the uplift of leveling each of the 12 hand types (shared `solver.pack.level_up`,
a deferred import — `shop`↔`pack` is a two-way cycle), then the shared `_monte_carlo_pack`
— "best choose of extra" by pack size (`_CELESTIAL_PACK_SIZES`: Normal 3/1, Jumbo 5/1,
Mega 5/2, checked against `game.lua`'s `P_CENTERS`). A planet needs no slot (it's taken
and applied immediately) → `has_slot` on a Celestial offer is always `True`. The autopilot
buys via the same pack branch as Buffoon (threshold "> 0"). Tests —
`tests/test_shop.py::TestПокупкаПака`, `tests/test_autopilot.py`.

## A2. A stricter joker-buy threshold — done.

`autopilot._worth_buying`: buy a joker into
a free slot only if `expected_uplift` is not below `_MIN_BUY_REQ_FRACTION` (3%, = A1's
dead-weight threshold) of the next blind's requirement — don't take up a slot with
something we'd immediately call dead weight. With an unknown requirement (manual input) —
fall back to the old "> 0". The threshold does **not** touch the Buffoon-pack branch (a
pack is a hedge of 2–4 and the only money sink before A3/A5). Tests —
`tests/test_autopilot.py::TestDecideActionВМагазине`.

## A4. Buying vouchers — done.

The user's verdict: buy across all three tiers.
`autopilot._decide_voucher_action` — a threshold per honesty tier (the new field
`VoucherOffer.value_unit`): `"score"` (tier 1) — the same `_worth_buying` as a joker;
`"dollars"` (tier 2) — a net dollar gain (estimate ≥ price); `heuristic_value` (tier 3, an
expert constant, not a computation) — only structural upgrades
`>= _MIN_HEURISTIC_VOUCHER_VALUE = 5.0` (Antimatter, Glow Up). A voucher takes no slot, it
goes after the joker, before the pack. `Action.kind = "buy_voucher"` →
`ModBridge.buy(voucher=…)`. `render_shop_advice` labels tier 2 "в деньгах ~$N". Tests —
`tests/test_vouchers.py::TestValueUnit`, `tests/test_autopilot.py`.

## B1. Temper the over-aggressive discarding — done (run 6 confirmed).

Two guards over
`rank_actions`'s top-1 in `autopilot.decide_action` on `SELECTING_HAND`, both sitting
after the existing `cheapest_sufficient` check:
- `_on_pace_without_discard` — if `best_play.score × hands_left` already covers the
  remaining requirement with a `_DISCARD_PACE_MARGIN = 1.5` cushion (and ≥ 2 hands are
  left), play the best hand and skip `advise_discard` entirely. Catches the case where
  `cheapest_sufficient` is empty only because a variance joker (`Misprint`) pulled a
  play's guaranteed floor under the requirement while its mean is comfortably over.
- `_discard_edge_is_noise` — if the top-1 is still a discard but its EV beats the best
  play by less than `_DISCARD_EDGE_MARGIN = 1.15` (the ±15 % tolerance `advise_discard`
  documents for itself, §7 `docs/Discard Spec.md`), play the hand: the "edge" is smaller
  than the estimator's own error. Kills run 6's 7,371→7,427 (+0.7 %) last-discard trade
  on a 10,000 boss directly.
Both constants are calibrated on live runs and live next to the other autopilot
thresholds. The guards touch only the autopilot — `rank_actions` / `advise` / `watch`
output is unchanged (a human reads the "hits the blind" markers and isn't fooled). Tests —
`tests/test_autopilot.py::TestOnPaceWithoutDiscard`, `::TestDiscardEdgeIsNoise`,
`::TestDecideActionB1`.

## A5. Shop reroll — done (run 6's economy ceiling).

`ModBridge.reroll` (mod's `reroll`
endpoint, no params) + `Action(kind="reroll")`. `RerollOutlook` (`ShopAdvice.reroll`,
`solver/shop.py`) is the first place the module reasons about the *unseen* roll rather than
the already-generated shop: a Monte-Carlo of the roll mechanic itself — each of
`GameState.shop_slots` slots is a joker with probability
`economy.SHOP_JOKER_RATE / (joker+tarot+planet rate)` (20/28, from `game.lua`'s
`GAME_MOD`), joker uplift drawn from the same random-implemented-joker sample the Buffoon
pack estimate uses (`random_joker_uplifts`, computed once per shop visit). Documented
simplification in `RerollOutlook.note`: rarity (`game.lua` 70/25/5 C/U/R) is only reflected
by averaging over implemented jokers, not stratified into three pools — a follow-up if live
runs show bias. New parsed field `GameState.shop_slots` (mod's `shop` area `limit`, mirrors
`joker_slots`). `autopilot._decide_reroll_action` — the verdict, last branch before
`next_round` (so only when nothing here is worth buying/selling): reroll when the blind
requirement is known, `expected_best_uplift` clears the same `_worth_buying` bar as a joker
buy, and `money − cost ≥ _REROLL_MONEY_RESERVE = 12` (leaves money for the buy itself and
stops a drain to $0 — run 4's bug; the escalating reroll cost plus this reserve end a
streak in a few steps). Tests — `tests/test_shop.py::TestОценкаРерола`,
`tests/test_autopilot.py::TestDecideActionРеролМагазина`, `tests/test_mod_bridge.py`,
`tests/test_economy.py::TestShopRates`. Calibration notes for live runs: `expected_best_uplift`
is a mean and tail-inflated (a 5 % Rare can dominate it), so the effective policy is closer
to "reroll while cash-rich and nothing to buy" than a tight EV compare — `_REROLL_MONEY_RESERVE`
is the real limiter and the knob to tune.

## F1. Decision-loop performance — done.

Profiled first: `decide_action` on
`SELECTING_HAND` was dominated by `rank_joker_orders` doing `N!` full `advise()` calls
(218 subsets each), and with a variance joker (`Misprint`) every `score_play` also unrolls
a probability tree up to 4096 branches. Measured on a 9-card hand: 3 jokers + Misprint
0.9 s, 4 jokers +Blueprint 42 s, 5 jokers +Blueprint+Baseball **194 s**. Fix, both halves
in `solver/play.rank_joker_orders`:
- **cheap gate** — if the stack has no copy joker (`Blueprint`/`Brainstorm`) and reversing
  it gives the same top score (`math.isclose`), joker order provably can't matter (an
  additive-only stack is order-invariant — addition commutes); return the current order
  without the `N!` search.
- **surrogate search** — when order *can* matter, score only the top
  `_ORDER_SURROGATE_SUBSETS = 5` subsets of the base order under each permutation via
  `score_play` (the best *subset* barely ever changes with joker order — only its score),
  then one full `advise()` for the winning permutation. Verified against the exhaustive
  search on 12 order-sensitive stacks: 0 deviations.
Plus `decide_action` now computes `advise(state)` once and threads it through the rearrange
check (`base_advice`), the sufficient-play check and the B1 guards, instead of 2–3 separate
calls. Result on the same hands: 5j+Misprint+Blueprint+Baseball `decide_action` 4.4 s
(from 194 s+), the run-6-shaped case (5j additive + Misprint) **0.6 s** (from 15–40 s).
`rank_joker_orders` stays exact for order-invariant stacks; the surrogate is a documented
approximation for the rest (PLAN sanctions it). Tests — `tests/test_solver.py::TestПорядокДжокеров`.

## A6. Shop branch order — sell-replace vs. a cheap pack — done.

`_decide_shop_action`'s
order was joker-buy → voucher → pack → sell-replace → reroll → leave; run 6 left a
+776/+3576 offer untaken for 2–3 shop polls because a positive Celestial pack (~44 uplift)
pre-empted the sell-replace branch every time (it self-corrects once packs are exhausted,
one action per poll, but wastes money and time). Fix: the branch is split.
`_decide_replace_action(..., strong_only=True)` — a replace whose captured offer would
itself clear the joker-buy bar (`_worth_buying`, i.e. ≥ `_MIN_BUY_REQ_FRACTION` of the
blind requirement) — now runs *before* the pack branch; the ordinary pass (any qualifying
replace) stays after it, unchanged. `strong_only` needs a known blind requirement, else
`_worth_buying` degrades to "> 0" and would swallow every positive replace. Tests —
`tests/test_autopilot.py::TestDecideActionРазменДоПаков`.

## A7. Voucher tier-3 threshold when cash-rich with empty joker slots — done.

Run 6
skipped `Overstock` ($10, +1 shop slot, `heuristic_value` 3.0 < the flat
`_MIN_HEURISTIC_VOUCHER_VALUE = 5.0`) on $29 with 3 empty joker slots. `Overstock`'s rated
value collides with merchant-rate vouchers (`Telescope` is also 3.0), so the number alone
can't single it out — `autopilot._heuristic_voucher_bar(state, key, price)` lowers the bar
only for `_STRUCTURAL_SHOP_VOUCHERS` (`v_overstock_norm`/`v_overstock_plus`), by
`_HEURISTIC_RELIEF_PER_EMPTY_SLOT = 1.0` per idle joker slot, floored at
`_HEURISTIC_VOUCHER_FLOOR = 3.0`, and only while the purchase still leaves the
`_REROLL_MONEY_RESERVE` cushion. Run-6 case: 5.0 − 3×1.0 = 2.0 → floored to 3.0 → 3.0 ≥ 3.0,
bought. Every other tier-3 voucher keeps the flat 5.0 bar. Tests —
`tests/test_autopilot.py` (`test_a7_*`).

## A8. The reroll policy over-rerolls and burns whole shop visits — done.

The first won
live run (RED/WHITE, run 7, 2026-09-01) rerolled **21 times**, including two stretches of 4
consecutive rerolls that drained a full shop visit ($39 → $13, $38 → $12) and bought nothing
afterwards — roughly $75+ across the run on empty rerolls, and the user, watching the game,
flagged the shop as visibly hung. **Root cause, measured:**
`RerollOutlook.expected_best_uplift` is computed from a fixed pool of 24 random implemented
jokers, so it neither sees the current shelf nor shrinks as money is spent — it is
**stationary**. On a 5-joker stack against a 300-requirement blind it reads ~138 whatever is
on the shelf, against a `_worth_buying` bar of 9. Clearing an absolute bar once therefore
means clearing it on every poll, and only running out of money ever ended a streak;
`_REROLL_MONEY_RESERVE` and the escalating price could never have been enough. **Fix** —
two conditions added to `autopilot._decide_reroll_action`, both staying inside the project's
refusal to price score points in dollars:
- *opportunity cost*: `expected_best_uplift` must exceed the best `JokerOffer.expected_uplift`
  already on the shelf by `_REROLL_SHELF_MARGIN = 1.5`. The old policy would roll away a
  strong offer that had merely failed on `affordable` or `has_slot`, instead of saving for
  it. Points against points, no exchange rate invented.
- *structural bound*: `economy.rerolls_done(cost, used_vouchers) < _MAX_REROLLS_PER_SHOP = 2`.
  Necessary precisely because the estimate is stationary — without a count, the policy is
  "reroll until broke" by construction, whatever the threshold.

The roll count is recovered from observed state rather than tracked across calls, so
`decide_action` stays a pure function of `GameState`: `functions/common_events.lua`'s
`calculate_reroll_cost` makes `reroll_cost = round_resets.reroll_cost + reroll_cost_increase`
with the increase growing by exactly 1 per roll and reset each round
(`functions/state_events.lua`), and the base is `BASE_REROLL_COST = 5` (`game.lua`) less $2
per redeemed Reroll Surplus / Glut — which *subtract and stack*, unlike `interest_cap`'s
"sets, doesn't add" (`card.lua`, both `config.extra = 2`). New in `core/economy.py`:
`BASE_REROLL_COST`, `reroll_base_cost`, `rerolls_done`. Honest caveat in the docstring: a
Reroll tag (`temp_reroll_cost`) or Chaos the Clown (`free_rerolls`) temporarily lowers the
price and makes the derived count an under-estimate — it errs toward allowing a roll, never
toward blocking a needed one. `_REROLL_MONEY_RESERVE` was deliberately left at 12: moving
three knobs at once would make the re-run unattributable. Tests —
`tests/test_economy.py::TestЦенаРерола`,
`tests/test_autopilot.py::TestDecideActionРеролМагазина` (shelf gate, visit cap, cap under
Reroll Surplus).

## F2. `evaluate_shop` rebuilt from scratch after every reroll — done.

Profiled first,
as F1 was. One shop decision on a 5-joker stack (`Misprint` + `Blueprint` + `Baseball`, so
every `advise()` unrolls a probability tree) against a full shelf with a Buffoon and a
Celestial pack: **78.5 s**, broken down as `random_joker_uplifts` 46.5 s (59 %),
`_planet_uplift_pool` 11.7 s (15 %), the two shelf jokers 9.2 s (12 %),
`joker_contributions` 8.7 s (11 %), `evaluate_vouchers` 2.2 s (3 %). A 4-reroll streak is
~6.5 minutes — the "hangs in the shop" the user watched. F1 had only touched the
`SELECTING_HAND` path.

The waste is provable from the game's own source: `functions/button_callbacks.lua`'s
`G.FUNCS.reroll_shop` removes and regenerates **only `G.shop_jokers`** — vouchers, booster
packs and the held jokers are untouched — so 97 % of that work is recomputed for nothing.
**Fix**: a one-entry `_SampleCache` in `solver/shop.py` memoising `random_joker_uplifts`,
`_planet_uplift_pool`, `joker_contributions` and each shelf joker's uplift (keyed by
`(key, edition)`, so a joker that reappears after a roll is not re-sampled). The cache key
(`_sample_cache_key`) is the whole `GameState` with only the shelf, `reroll_cost` and — when
no money-sensitive joker is held — `money` blanked, compared by `==` rather than hashed
(`blinds` is a `dict`). That direction matters: any field *not* blanked invalidates the
cache by itself, so the design is safe by construction instead of by remembering to list
every dependency. `money` needs an exception because exactly two jokers read it while
scoring — `j_bull` and `j_bootstraps` — and `_MONEY_SENSITIVE_JOKER_KEYS` is pinned by a
**behavioural** test that checks every implemented joker, the same discipline as
`solver/discard.py`'s `_SUIT_SENSITIVE_JOKER_KEYS`. Everything cheap (`affordable`,
`has_slot`, `interest_lost`, stake stickers, the sort) is still recomputed from live state
each call, so stale money cannot reach an offer.

**Result: 78.5 s → 6.9 s after a reroll (12×), → 2.2 s on a repeat poll of an unchanged
shelf (36×)**; a 4-reroll streak 398 s → 107 s, and with A8's cap it can no longer be four.
The cached and uncached paths were checked to return equal `ShopAdvice`. The cold first
visit is unchanged at ~78 s and stays that way by design — it is the sampling itself, not
redundant work, and cutting it would trade accuracy. `evaluate_vouchers` is deliberately not
cached: `_evaluate_shop_discount` prices Clearance Sale / Liquidation against the current
shelf, which a reroll does change; it is now essentially the whole of the remaining
repeat-poll cost, and splitting its shelf-dependent part from its sampled part is the
obvious follow-up if it ever matters. `clear_shop_cache()` and
`evaluate_shop(..., use_cache=False)` exist for tests and for a deliberately cold
computation. Tests — `tests/test_shop.py::TestКешВыборок`,
`::TestДенежноЧувствительныеДжокеры`.

## A9. The autopilot cannot shed dead weight while a joker slot is free — done.

Run 8 (RED/WHITE, 2026-09-04, the A8/F2 shakedown) lost at Ante 7 Big Blind: needed 52,500,
scored 36,362, **$59 unspent**, board frozen at 4 jokers since ~Ante 5 (Banner, Hit the
Road, Joker Stencil, Blue Joker). A8 and F2 both held up (see their entries), so the loss
came from somewhere else.

**Root cause.** `Joker Stencil` is `X1 Mult per empty joker slot` (`1 + empty_slots`), so
filling the last slot costs a whole multiplier step and every shop joker's counterfactual
carries a fixed penalty. The run's last two shops, from the log: `Rough Gem -2 355`,
`Burnt Joker -4 710`, `Gros Michel -90`, `Egg -4 710`. Refusing those buys was
arithmetically correct. The defect was the *second* link: measured on the same board,
`Hit the Road` contributed **−722** — it was worth **less than an empty slot**, so selling
it would have raised the score *and* returned money. The autopilot never looked, because
`evaluate_shop` computed `joker_contributions` only when `slots_full`; at 4 of 5 slots the
number was never produced, `JokerOffer.replaces` stayed `None`, and `_decide_replace_action`
had nothing to act on. The bot was structurally blind to exactly the situation Stencil
creates — a free slot plus a joker that is worse than leaving it empty.

**Fix.** `solver/shop.py` computes contributions whenever `state.jokers` is non-empty and
reports them as `ShopAdvice.held: tuple[HeldJoker, ...]` (index / label / contribution /
sell_value / eternal, in `state.jokers` order). The module still reports facts and no
verdict; `ReplaceCandidate` is now derived from `held` and is still attached to offers only
when slots are full, so replace semantics are unchanged. `autopilot._decide_dead_weight_action`
sells the most-negative held joker when it is not eternal, its contribution is below
`-_DEAD_WEIGHT_REQ_FRACTION × requirement`, and at least `_MIN_JOKERS_KEPT = 2` jokers
remain. It sits after the ordinary sell-replace pass and before the reroll — where "nothing
here is worth buying" already lives — leaving the calibrated A1–A7 ordering untouched.
`render_shop_advice` now prints a "джокеры в слотах" block with each contribution: the
number was invisible during run 8, which is part of why the run was lost quietly.

**Constants.** `_DEAD_WEIGHT_REQ_FRACTION = 0.005` is deliberately an order of magnitude
below `_DEAD_JOKER_REQ_FRACTION = 0.03` because it answers a different question: the 3 %
bar judges *strength* ("is this joker weak enough to trade away"), this one is only a
noise guard ("is this number reliably below zero") — the sign already carries the meaning.
`_MIN_JOKERS_KEPT = 2` guards a cascade, since each sale makes the next one look better
while Stencil is held; measured on run 8's board the cascade in fact terminates by itself
after the first sale (no contribution is negative afterwards), so the floor is a safety
net rather than the expected path.

**Cost.** Computing contributions when slots are *not* full is new work: measured 5.0 s on
a 4-joker board, against a 60.6 s cold shop visit (~9 %), and nothing on warm polls or
after a reroll — F2's memo already caches it and a reroll does not change the held stack.

**Honest limitation**, stated in the docstring: a contribution is measured on hands sampled
*now*, and a sold joker does not come back. A joker that would scale later reads at its
current value — `Hit the Road` needs discarded Jacks and honestly measures 0 until they
happen. The margin and the joker floor keep that from being reckless; the horizon problem
itself is the same one `JokerOffer.interest_lost` and `PlanetConsumableOffer` carry and do
not pretend to solve. Tests — `tests/test_shop.py::TestВкладыВСлотах`,
`tests/test_autopilot.py::TestDecideActionПродажаБалласта`,
`tests/test_render.py::TestВыводВкладовВСлотах`.

## A10. The shop valued jokers at the wrong moment of the round — done.

Run 9
(RED/WHITE, 2026-09-04) surfaced a systematic pricing error that cost real moves in both
directions in a single run. `joker_uplift`/`joker_contributions` sample representative
*hands*, but every sample was scored in the shop's own state, where the round has not
started: `hands_left`/`discards_left` at their reset maximums, `hands_played` zero. Six
implemented jokers read exactly those fields:

| joker | condition | measured in the shop |
|---|---|---|
| `j_acrobat` | `hands_left <= 1` → X3 Mult | never fires → **0** |
| `j_dusk` | `hands_left <= 1` → retrigger all | never fires → **0** |
| `j_mystic_summit` | `discards_left <= 0` → +15 Mult | never fires → **0** |
| `j_card_sharp` | `played_this_round > 0` → X3 Mult | never fires → **0** (closed by A11) |
| `j_banner` | `+30 chips × discards_left` | at its maximum → **over** |
| `j_ice_cream` | `+100 chips − 5 × hands_played` | at its maximum → **over** |

Both halves fired live: `Acrobat` measured a contribution of exactly 0 and was sold as dead
weight under the A1 replace rule, and `Ice Cream` was bought at an uplift of 3 531 taken at
its peak. None of the six is implemented wrongly — the sampling was one-dimensional.

**Fix**: spread the existing samples across the round instead of piling them on its opening
hand. `_round_moment(state, step, hands)` sets `hands_left = H - step`,
`hands_played = step` and decays `discards_left` linearly to 0 on the last hand;
`_round_budget` reads `H` from the state without guessing (a state that says one hand left
is modelled as the last hand, which is correct for it). Both `joker_uplift` and
`joker_contributions` follow the same schedule — they must, since
`autopilot._decide_replace_action` compares an uplift to a contribution directly — and both
sides of every diff use the *same* moment, so only the joker differs. Sample count is
unchanged, so **cost is unchanged**: a cold shop visit measured 80.2 s against 80.6 s
before, within noise.

**Measured effect** on run 9's own board (Misprint / Stuntman / Half Joker, candidate added):
`j_acrobat` 0 -> 4 796, `j_mystic_summit` 0 -> 1 062, `j_dusk` 0 -> 141, `j_ice_cream`
3 358 -> 3 105, `j_banner` 4 030 -> 2 008. `Acrobat`'s contribution on the four-joker board
went from 0 — sell it — to the second largest on the board. Other contributions rose too,
correctly: with `Acrobat` active on last-hand moments its X3 multiplies everyone else.

**Stated assumption**: discards are modelled as spent evenly across the round. Real play
front-loads them, so `j_banner` stays slightly high and `j_mystic_summit` slightly low —
an approximation of *when* discards are spent, not a guess at an effect, and strictly better
than the old "all discards always remain". **`j_card_sharp` was left at 0 by decision** —
five of six was the whole claim at the time. That debt came due immediately: run 10 sold
the joker, and **A11 below discharges it**.

**Out of scope, noted**: `solver/vouchers.py` prices `+1 hand`/`+1 discard` vouchers from the
same shop-moment snapshot, and `solver/pack.py`'s planet pool likewise. The same argument
applies; the observed harm was in joker pricing. Tests —
`tests/test_shop.py::TestМоментРаунда`, `::TestОценкаПоМоментуРаунда`.

## F3. The probability tree was the whole performance problem — done.

Profiled first, as
F1 and F2 were. The measurement was unusually clean:

```
advise() без вариативных джокеров    8.7 мс
advise() с Misprint                164.4 мс
```

All 218 subsets, the event dispatch and the copy-joker chains together cost 8.7 ms;
`Misprint` alone added 19× on top. `cProfile` counted 16 350 `_run_once` calls for 654
`score_play` calls — ~25 full pipeline passes per subset, because `score_play` re-ran
everything once per branch of the cartesian product, and `Misprint`'s uniform `+0..+23`
spread is 24 branches.

**Nothing was traded away for the fix — the user's explicit call, and the numbers stay exact
to the last digit.** A chance point resolves to a *number* (`ChancePicker.pick`), and that
number reaches the accumulator only through `AddChips(v)` / `AddMult(v)` / `XMult(v)`, each
linear in `v`. So `chips(v) = a + b·v`, `mult(v) = c + d·v`, and the total `chips × mult` is
a polynomial in `v` of degree at most two. Three engine passes determine it exactly, after
which every remaining outcome is evaluated by **arithmetic** rather than by re-running the
engine: `E = Σ pᵢ·P(vᵢ)`, and `minimum`/`maximum` as the extremes of `P` over the outcomes.
Four passes instead of 25, same answer.

The polynomial claim is **verified, not asserted**: a fourth evaluation checks the fit, and
any disagreement beyond `_FIT_TOLERANCE` abandons the fold and runs the existing full
enumeration. An effect that branched on the drawn value would break polynomiality, and the
check catches it instead of a promise that no such effect exists — `_fold_single_chance` also
bails out if the set of chance points turns out to depend on its own outcome, leaving that
case to the enumeration path that already marks it `unknown`. The fold applies only to a
single chance point with at least `_FIT_MIN_OUTCOMES = 6` outcomes; Lucky's two branches and
multi-point trees enumerate exactly as before, and `MAX_CHANCE_BRANCHES` with its
likeliest-outcome fallback is untouched.

**Measured, on the same stack that motivated the work:**

| | before | after |
|---|---|---|
| `advise()`, 5 jokers + `Misprint` | 164.4 ms | **36.3 ms** |
| cold `evaluate_shop` | 80.2 s | **17.7 s** |
| decision after a reroll | 6.9 s | **1.5 s** |
| repeat poll of an unchanged shelf | 2.23 s | **0.48 s** |
| `SELECTING_HAND` with two Tarots | 8.1 s | **2.0 s** |

**Where it does *not* help, stated plainly:** the play-with-discards decision went 7.02 s →
6.54 s, about 7 %. Its cost lives in `solver/discard.py`'s own target sampling, not in the
scoring tree, and it is now the slowest single decision the autopilot makes — the obvious
next performance item, and a separate one.

The acceptance criterion was that **no existing test moves**, since this changes the engine
every other module is built on; none did. The load-bearing new tests are differential —
`tests/test_scoring.py::TestСвёрткаТочкиСлучайности` runs the same calculation down both
paths (forced by monkeypatching `_FIT_MIN_OUTCOMES`) and compares expectation, bounds,
`exact` and `unknown` for `Misprint` alone, `Misprint` under `Blueprint`, a Glass card
putting an `XMult` downstream, a two-outcome Lucky point, two simultaneous chance points, and
a synthetic joker whose effect jumps rather than scales, which must fall back.

## C1. Tarot consumables

(Phase 9.4, the second slice) — **slice 1 done.** Unlike a Planet
card, a Tarot needs a *target*: the search is over subsets of the hand, and cost decided the
shape of the work. Measured on an 8-card hand, `advise()` runs **4 ms** with no jokers and
**163 ms** on a 5-joker stack with `Misprint`/`Blueprint`/`Baseball`, so "up to 3 cards"
(92 subsets) would be ~15 s per card — against the 0.6 s F1 brought a whole `SELECTING_HAND`
decision down to. C1 is therefore staged (the user's call):

**Slice 1 — the eight "Enhance selected card(s)" Tarots.** `TAROT_ENHANCEMENTS` in
`solver/consumables.py` is a hardcoded table transcribed from `game.lua`'s `P_CENTERS` —
all eight share `effect = "Enhance"`, and the two numbers that matter live in
`config.mod_conv` and `config.max_highlighted`: `c_magician`→Lucky/2, `c_empress`→Mult/2,
`c_heirophant`→Bonus/2, `c_lovers`→Wild/1, `c_chariot`→Steel/1, `c_justice`→Glass/1,
`c_devil`→Gold/1, `c_tower`→Stone/1. `max_highlighted` is a *maximum*, so the search covers
sizes 1..N — at most `C(8,1)+C(8,2) = 36` subsets. Coverage test as for `PLANET_HAND_TYPES`.
`evaluate_tarot_consumables` scores each subset with a real `advise()` on the transformed
hand and keeps the best against a baseline computed once. The uplift is never negative by
construction: the search starts *at* the baseline, so if nothing improves the hand the
answer is `0.0` with empty targets — "no reason to use it", not "using it hurts", since
nobody forces the card to be spent (this matters for `The Tower`, which erases a card's rank
and suit and can genuinely ruin a flush).

**Three honesty tiers**, the same shape as `solver/vouchers.py`, with `value_unit`
distinguishing them because points and dollars must not share one field: *score* for the
eight above; *dollars* for `c_hermit` (`max(0, min(money, 20))`) and `c_temperance`
(`min(Σ joker sell_value, 50)`) — both formulas read off `card.lua`/`game.lua`, not memory;
and an honest `None` with a reason for the rest — the four suit cards plus `Strength`,
`Death`, `The Hanged Man` (deferred to slice 2) and `The Fool`, `The High Priestess`,
`The Emperor`, `Judgement`, `The Wheel of Fortune` (create cards or roll on jokers — RNG this
project does not model). Every one of the 22 keys gets an answer, because silence is what the
autopilot cannot read.

**`The Devil` is a computed zero, not a gap:** Gold pays $3 for a card *held* at end of round
and does nothing to a play's score, so `0.0` is the right answer — the same honest zero as
the economy jokers in `implementations.py`, and the note says so, or a future reader files it
as a bug.

**The policy is deliberately the opposite of the Planet one.** A Planet card is used on
sight, because a level-up cannot hurt. A Tarot permanently rewrites a *deck card* for the
rest of the run, so `autopilot._decide_consumable_action` uses one only on a strictly
positive score-tier uplift that also clears `_worth_buying` — the same
fraction-of-requirement bar as a joker buy (A2), for the same reason: spending a one-shot
resource and permanently altering the deck for a marginal gain is a bad trade. Dollar-tier
offers never drive an automatic use (dollars vs. points, the usual refusal); the human sees
them via the new `render_tarot_advice`. `Action(kind="use")` now carries target indices and
`dispatch_action` forwards them as `ModBridge.use(cards=…)`, which the bridge already
accepted but was never passed.

**Cost, measured.** Six Tarots on an empty stack: 0.19 s. Two Tarots (2- and 1-target) on the
5-joker `Misprint` stack: 7.9 s, making the whole `SELECTING_HAND` decision 8.1 s against
F1's 0.6 s. That is within "seconds, not tens of seconds" but is a real regression on that
path, and it is the obvious next performance item if live runs make it felt —
`MAX_TAROT_CANDIDATES = 64` is the budget knob, and above it the offer is an honest `None`
rather than a guess (the same refusal as `rank_joker_orders`).

**Honest limitation:** the uplift is measured on *this* hand while the transformation lasts
the whole run — the mirror of the Planet slice's limitation and more dangerous, since a
level-up keeps paying while a Stone card can ruin later hands. The bar plus strict positivity
keep it conservative; the horizon itself is not solved, as with `JokerOffer.interest_lost`.
Tests — `tests/test_consumables.py::TestТаблицаТаротов`, `::TestОценкаТаротов`,
`tests/test_autopilot.py::TestDecideActionТаро`, `tests/test_render.py::TestВыводТаротов`.

**Slice 2 — done (2026-09-05).** All seven remaining cards are valued, and three of their
mechanics turned out to differ from what the names suggest, so `card.lua` was read rather
than guessed: `change_suit` rebuilds only `base`, so rank, enhancement, edition and seal all
survive a suit conversion; `Strength` **wraps an Ace to a 2** rather than capping at Ace
(`id == 14 and 2 or min(id+1, 14)`); and `Death` has `min_highlighted = 2` as well as max —
exactly two targets — with the rightmost cloned onto the other *whole* (base, enhancement,
edition, seal), not merely its rank. `The Hanged Man` is a **computed zero, not a gap**:
destroying cards can only shrink the set `advise` chooses from, so this hand's best score
can never rise — the same honest zero as `The Devil`, with the deck-thinning value it really
has named in the note as unmodelled.

**The reachability filter is load-bearing, not decoration.** Three targets out of eight is
`C(8,1)+C(8,2)+C(8,3) = 92` subsets, past `MAX_TAROT_CANDIDATES = 64`, so slice 1's budget
gate would have refused these cards outright. Converting suits only matters for a flush, so
`_suit_conversion_targets` computes how many cards short of one the hand is — through the
existing `core.cards.effective_suits`, which already knows `Wild` and `Smeared` — and
searches subsets of exactly that size among the cards not already that suit. Unreachable, or
a flush already in hand, is an honest `0.0`. Shape taken from `solver/discard.py`'s
`_flush_targets`, as planned.

**No autopilot change was needed**, which is the payoff of slice 1's design:
`_decide_consumable_action` already iterates every offer generically and gates on
`value_unit`/`targets`/`expected_uplift`/`_worth_buying`.

**Stated limitation**, carried in the offer's own `note`: the game re-derives a card's debuff
after a suit change (`card.lua`'s `change_suit` calls `debuff_card`), while `Card.debuffed`
here is a static field from the mod that nothing recomputes — so under a suit-restricting
boss the uplift reads optimistic. Cost measured: four Tarots on a 5-joker `Misprint` stack
2.56 s, on an empty stack 0.22 s. Tests — `tests/test_consumables.py`'s
`TestТаблицаМастевыхТаротов`, `TestПовышениеРанга`, `TestОценкаВторогоСреза`.

**`The Fool` — reported from a live run, to fix.** The bot never uses it. Slice 1 filed
`c_fool` under `_RANDOM_TAROTS` ("creates cards, depends on RNG"), and that classification
is wrong: The Fool recreates *the last Tarot or Planet used this run*, which is not random at
all — it is simply history the project does not track, and `GameState` has no field for it.
The route proposed here (read the copied card's name out of the live effect text, the way
`JokerCard.current_value` recovers accumulator values) was **checked against the game and is
disproved**: `localization/en-us.lua` renders `c_fool` as four lines of fixed text with no
substitution variable at all, so there is no name to read; the real target is
`G.GAME.last_tarot_planet` (`card.lua`, both the `use` and `can_use` paths), which the mod's
`utils/gamestate.lua` does not serialize. The honest `None` therefore stands, and its
*reason* changes from RNG to missing history. The one remaining route is for the bot to track
its own last-used Tarot/Planet in the run loop — workable, since the autopilot is normally
the one using them, but it is a new mechanism with a hole in it (a card used by the human
during a hand-over would be missed), not a text read.

**Re-reported by the user 2026-09-06, and the feasibility has changed since this was
written.** When C1 slice 1 shipped, the autopilot barely used consumables, so "track our own
last-used card" was a mechanism with nothing to track. It now uses them: the batch journals
show `The Chariot`, `The Moon` and `The Magician` actually played. So the remaining route is
live rather than theoretical — the run loop already dispatches every `use`, and recording the
key of the last Tarot/Planet it played is a few lines in `runner.py` plus a `GameState` field
the mod does not need to provide.

Two honest limits stay. The bot would only know about cards **it** used, so a card played by
the human during a hand-over, or before `--adopt` picked the run up, is invisible — the value
must then fall back to an honest `None`, not to a stale guess. And `G.GAME.last_tarot_planet`
is set by the game for *any* use, so the two can diverge; the field should therefore be named
for what it is (what the bot last used) rather than pretending to mirror the game's own
counter. Valuing the card once it is known reduces to valuing that card, which slices 1 and 2
already do for the eight enhance-Tarots, the four suit ones, `Strength`, `Death` and every
Planet.

**And it is not a rare miss on one deck.** The `MAGIC` deck *starts the run holding two*
`The Fool`. A rotation run on it (2026-09-06, lost at ante 6, 134 steps) used **zero**
consumables of any kind: both cards sat dead for the whole run. So on that deck the gap is
not an occasional skipped card but a starting condition — two of the run's opening resources
are unusable by construction, which also blocks the consumable slot they occupy.

## A11. An audit of the whole "wrong state to evaluate from" defect class — done.

A8, A9,
A10 and the `j_card_sharp` gap were, in retrospect, four instances of *one* defect: not a
joker implemented wrongly, but the shop counterfactual scoring jokers from a state the round
will never actually be in. Each cost a live run to find, one at a time. So instead of waiting
for run 11 to surface the next one, the class was audited directly — which implemented jokers
read a `GameState` field, and which of those fields does the counterfactual model? The audit
is small and complete; exactly nine jokers read state:

| field | jokers | modelled |
|---|---|---|
| `hands_left` | `j_acrobat`, `j_dusk` | ✅ A10 |
| `discards_left` | `j_banner`, `j_mystic_summit` | ✅ A10 (stated assumption) |
| `hands_played` | `j_ice_cream` | ✅ A10 |
| `joker_slots` | `j_stencil` | ✅ (`len(ctx.jokers)` grows with the candidate) |
| `deck`, `deck_type`, `full_deck` | `j_blue_joker`, `j_erosion`, the `_FullDeckJoker` family | ✅ static within a round |
| `hand_info.played_this_round` | `j_card_sharp` | ❌ **gap 1** |
| `money` | `j_bull`, `j_bootstraps` | ❌ **gap 2** |

Two gaps, and the second was not previously known. This table is the deliverable as much as
the code is: it is reproduced in `docs/architecture.md`, and `CLAUDE.md`'s "Adding a Joker"
now sends any new state-reading joker through it — so the next one gets checked instead of
costing a run.

**Gap 1 — `j_card_sharp`, the joker A10 knowingly left behind.** Run 10 sold it, exactly as
predicted. `_round_moment` aged `hands_left`/`hands_played`/`discards_left` but left
`hand_info` alone, so `played_this_round` was 0 in every sample. It now takes `repeat: bool`
and, when set, marks **every** hand type as played — whichever type the solver goes on to
pick then counts as a repeat, so the caller never has to know which one it will be, and
levels/chips/mult are carried through untouched.

The rate is **measured, not guessed**: the run 9 and run 10 decision logs were parsed and
every played hand re-evaluated through `core.hands.evaluate` — of 19 non-first plays in a
round, 13 repeated a type already played that round, **68 %** (by step: 7/12, 4/5, 2/2, so
the share rises through the round). `_CARD_SHARP_REPEAT_RATE = 0.68` carries that sample size
in its docstring; 19 observations is small, so it is a declared assumption of the same shape
as A10's "discards are spent evenly", to be re-measured by the E1 batch. `_repeats_hand_type`
allocates the mixture across sample cycles the way Bresenham's algorithm splits a slope —
exactly `int(C × rate)` firings over `C` cycles, deterministic, no second RNG — and the
averaging `joker_uplift`/`joker_contributions` already do turns it into an estimate at the
measured share. Measured: `j_card_sharp` 0 → **184**.

**Boss guard, required.** `solver/play.py._is_legal_play` reads the same field for `The Eye`
and `The Mouth`, so "every type has been played" would make *every* play illegal under
`The Eye`. The marking is therefore skipped under the three bosses whose
`restricts_legal_plays` is set (`_RESTRICTING_BOSS_NAMES`, read straight off `core/bosses.py`
rather than re-listed). The price is that `j_card_sharp` is back to 0 under those three —
a narrow, explicit refusal instead of a silently wrong number, and pinned by its own test.

**Gap 2 — money was counted before the purchase.** `joker_uplift` scored the boosted side
with `state.money` untouched, but buying costs `item.price`, and `j_bull` (+2 chips per $1)
and `j_bootstraps` (+2 Mult per $5) read that field directly. The bias grew with price, so
the more expensive the offer the more its own cost was ignored — `interest_lost` already
prices spending in dollars, the score side simply never did. `money_delta` is now applied to
the **modified side only**, which is the point of a counterfactual rather than an oversight:
not buying costs nothing. Measured on a `j_bull` offer: 206.7 at $0, 175.7 at $6, 144.7 at
$12. `joker_contributions` gets the mirror — money moves by the sold joker's `sell_value` —
so `autopilot._decide_replace_action` no longer compares an uplift priced after the spend
against a contribution priced before the refund. `solver/pack.py` keeps the default 0: a
pack is already paid for.

**Gap 2b — the F2 cache key ignored the shelf**, a correctness defect introduced by F2 and
found by this audit rather than by a run. `money_matters` scanned held jokers only, and the
key blanks `shop`, so with a `Bull` *on the shelf* but not in a slot, buying anything else
changed money without changing the key and the stale uplift was served from cache. The scan
now covers the shelf too. `_evaluate_joker_offer`'s memo id gains the price for the same
reason: the same joker at $4 and at $8 is no longer one entry.

**Cost: none.** Sample counts are unchanged and the extra `hand_info` rebuild is per sample,
not per score — cold shop visit 17.4 s against 17.7 s before, after a reroll 1.48 s, repeat
poll 0.48 s. F2 and F3 hold. Tests — `tests/test_shop.py::TestПовторТипаРуки`,
`::TestДеньгиПослеСделки`, `tests/test_autopilot.py::TestDecideActionCardSharpНеБалласт`.

**Not verified live yet**, along with A9's sell-on-negative branch, C1 and A10 — the next
run is the first chance to see any of the four.

## A12. The §8.3 assumptions audited against the game's own source — done.

A11 audited one
defect class (which `GameState` fields the shop counterfactual models) and found two gaps
without needing a run. The same question applied to §8.3 itself: six of the seven genuinely
open assumptions were marked **"needs a Mac"**, and that label was simply stale — it predates
this project learning that `Balatro.love` is a plain zip. Nothing there needed a running game
except `j_hiker`.

**Four assumptions verified correct and closed** (details and evidence in §8.4): base hand
values — *all 24 numbers match `game.lua`*, which retires the top-ranked "distorts every
calculation" item and lets `HAND_VALUES_ARE_PROVISIONAL` go to `False`; the scoring step
order, identical to `_run_once` step for step; `Photograph` on a retrigger; and the royal
flush being display-only.

A bonus confirmation landed for the improvement committed a day earlier: **A11's
`j_card_sharp` model is right.** The game tests `played_this_round > 1` *after* incrementing
the counter for the current hand, while we test `> 0` on the mod's pre-play snapshot — the
two are equivalent. It reads like an off-by-one and is not, so the code now says why.

**Four defects came out of the same read**, three of them never suspected. `The Flint` was
marking every hand with a joker inexact on a belief about ordering that the source
contradicts, and separately ignored `Chicot` disabling the blind. `Supernova` was understated
by 1 Mult on *every* play. And a whole class of accumulators — `j_trousers`, `j_runner`,
`j_square` — was understated by one increment on qualifying hands, because the game increments
them in a `context.before` pass that runs before base chips/mult are even read, while the
mod's `current_value` is snapshotted before the play. All four are fixed with regression
tests (§8.4).

**Two more defects were found and deliberately left open** as §8.3 rows 3 and 4, because they
need pipeline mechanisms rather than value fixes: `j_vampire` strips enhancements off scoring
cards in that same `before` pass (so we are wrong in both directions at once), and `j_space`
levels up the hand it is played on (we register it as an honest zero on the opposite,
now-disproved, belief). Characterising them precisely, with file and mechanism, is the
deliverable — an honest `None` beats a guess, but a *described* gap beats an unexamined one.

**The transferable lesson** is the one A11 already suggested and this confirms: the expensive
errors in this project are not wrong joker formulas but values read from the wrong moment or
the wrong state, and they are cheaper to find by auditing a class than by losing a run to each
instance. The second-order lesson is narrower and worth stating plainly — **"needs a Mac" was
wrong about six items for months.** Check the source before declaring something unknowable.

## F4. Event dispatch — measured and rejected, not deferred.

Profiling `rank_discards` on a
5-joker stack showed **37.8 M no-op `BaseJoker.react` calls**, which reads like an obvious win:
index jokers by the events they handle and stop walking the whole list for every event. It is
not a win. Patched experimentally — addressing a `JokerTurn` at the single joker it is for (an
invariant: both `_OwnTurn` and `_Copycat` check `event.joker is self`), plus skipping `_OwnTurn`
jokers on other events — the measurement is **15.0 s → 13.7 s, 1.09×**. cProfile's per-call
overhead had inflated the apparent cost of call-heavy code enormously; those 37.8 M calls are
worth about one second of real time.

The real cost is **454 k `_run_once` invocations**, i.e. the number of candidates the discard
search scores, not the dispatch under each. And all of it is on `advise --discard-search`, which
the autopilot never calls — its own decision path measures 0.24 s. So: 9 % on a path nobody
automated uses, bought with dispatch complexity and a standing risk that a joker silently drops
out of an event it needed. Recorded here with the numbers precisely so the idea is not
re-derived from the same misleading profile; if this path is ever attacked, the lever is the
candidate count, and that trades against exactness.

## B2. The autopilot stopped discarding, and the journal could not say why — done.

Run 11
(ZODIAC, 2026-09-05, the first run with `--log`) lost at ante 5 with a clean symptom and an
unanswerable question, and both halves were instructive.

**The symptom, straight from the journal:** ante 1 spent 6 discards; **ante 3 onward spent zero
across 20 plays**, and every round from ante 2 r5 closed with all three discards untouched. The
losing round scored ~9 000 of 11 000 over four hands while three free discards sat unused.

**The question that could not be answered, and why.** `Action.reason` — added by E1a the day
before, precisely so a run could be post-mortemed without a live terminal — turned out to be
filled at six sites, *all six in the shop*. Of 98 decisions, 19 carried a reason and all 19 were
purchases, rerolls, packs or sales; all 31 plays, 7 discards, 12 blind selects, 5 pack picks and
12 "left the shop" carried nothing. The journal explained the shop and not one moment of actual
play. That was a gap in the E1a work, not a limit of the design, and only a live run surfaced it.

A probe narrowed the mechanism without closing it. Replaying one hand at rising deck power shows
`_discard_edge_is_noise` is **not** the culprit — a discard's EV scales with power exactly as a
play's does, so its 1.15× margin is cleared at every level (levels 1→7: 659/1559/2823/4447
against 575/1346/2392/3714). `_on_pace_without_discard` does begin firing at high power, and its
projection is optimistic by construction, but in the losing round its own arithmetic says it
should not have fired. Reconstruction cannot settle it, because the journal does not record which
branch decided. Hence the fix below is *observability first*.

**Fixed:** every decision with numbers behind it now carries them — the guaranteed close (its
floor against the remaining requirement), the on-pace guard (its projection, its bar, and the
count of untouched discards), the noise override, the plain `rank_actions` top-1 together with
its runner-up so a near-tie is visible, plus blind select, pack picks and the "nothing was worth
buying" exit. `rank_actions` is now asked for `top=2` rather than 1 — it ranks everything and
slices at the end, so the runner-up costs nothing.

**Also fixed, independently of whether it caused this loss:** `_pace_projection` replaces
`best × hands_left`. That formula assumed every remaining hand scores like the current best, when
the best hand is played *first* and the rest come from what is left — this round went 2 754,
2 052, 2 240, a ~25 % fall, against a projection of four hands at 2 754, and the error always
favoured not discarding. Future hands are now valued at the round's **observed** average once
there is history (measurement, not assumption), and at a decayed best before then;
`_PACE_DECAY = 0.75` is measured from that one round, carries its sample size in the docstring,
and is due for re-measurement by the batch — the same treatment `_CARD_SHARP_REPEAT_RATE` got in
A11. The projection can only shrink, so the guard is strictly more conservative than before.

**And made self-reporting:** `RunReport` now counts plays, discards used, and rounds closed
without a single discard while discards were available. Replayed against run 11's own journal it
prints `розыгрышей 31, сбросов 7, раундов без единого сброса 8` — the symptom that took a human
reading ninety-eight lines is now the summary's second line.

**`stake_observed` corrected**: it was hardcoded `false`. The stake is known exactly when the
runner started the run, since it passed it to `start`; only an *adopted* run has an unknowable
stake. Marking a known stake unknown discards real knowledge and would have hollowed out the
win-rate table for every run the batch starts itself.

**Still open:** which branch actually declined to discard in run 11's last round. The next
journalled run answers it by reading one line, which is the whole point. Tests —
`tests/test_autopilot.py::TestОбоснованиеНаИгровомПути`, `::TestOnPaceWithoutDiscard`,
`tests/test_runner.py::TestСчётчикиСбросов`.

## A13. The journal caught a lying explanation and a bad pack policy — done.

Run 12 (ZODIAC,
2026-09-05, lost at ante 7 r20, 148 steps — the deepest non-winning run so far) was the first
run whose journal explained every decision, and it paid for itself twice within an hour.

**Defect 1, mine, introduced that morning.** `_shop_nothing_reason` named the buy bar as the
reason for leaving the shop empty-handed — always, whether or not the bar was the obstacle. The
run printed `лучший оффер 8145 не берёт порог 2100` and `лучший оффер 1937 не берёт порог 330`:
offers clearing those bars four- and six-fold. The genuine blockers are a full joker board, the
price, or a declined replace. A wrong conclusion was drawn and reported from that line before it
was caught, which is exactly the failure mode that matters: the journal's whole value is that a
line can be trusted without re-deriving it, so an explanation that asserts a cause instead of
determining one is worse than silence. The cause is now read off `JokerOffer`'s existing
`has_slot`/`affordable`/`replaces`, and "ниже порога" appears only when it is true.

**Defect 2, provable straight from the journal.** A joker must clear a fraction of the blind
requirement (A2); a pack only had to clear `> 0`. On antes 6–7 that bought four packs at value
the bot would have refused from a joker at the same price:

| ante | pack uplift bought | joker bar that visit | money left |
|---|---|---|---|
| 6 | 615 | 1 200 | $55 |
| 7 | 873 | 1 050 | $2 |
| 7 | 408 | 1 575 | $4 |
| 7 | 664 | 2 100 | $2 |

Packs now face the same `_worth_buying` bar as a joker and must leave the same cash reserve a
reroll does (`_PACK_MONEY_RESERVE = _REROLL_MONEY_RESERVE`, one constant reused deliberately —
the justification is identical and two copies of it would drift). Checked against the run's own
numbers: all four late packs fail the new bar, the two that ended at $2 also fail the reserve,
while the early packs (105/130/345 against bars 24/36/330) and ante 6's Jumbo Buffoon at 3 761
still pass. The change tightens exactly what the run showed to be wrong.

**A prior deliberate decision is overturned here, and the reasoning matters.** The `> 0` bar was
chosen on purpose and recorded in `docs/architecture.md` as "a pack is a hedged choice of several
cards". Being a hedge explains why the *outcome* varies; it does not explain accepting a third of
the expected return for the same dollars out of the same pocket. Run 12 is the first evidence
bearing on that choice and it points the other way.

**What is deliberately not claimed:** that this would have won the 8 145 offer that appeared two
steps after the last pack. `_decide_replace_action` may have declined it legitimately — a held
joker's contribution may genuinely have exceeded it — and **joker contributions are not in the
journal**. Establishing that needs the next journal extension — **done as E1b below**, so the
next run answers it from the file; asserting it now would repeat the exact error defect 1 was. Tests — `tests/test_autopilot.py::TestПравдиваяПричинаУхода`,
`::TestПорогИЗапасДляПаков`.

**Open from the same run, unranked:** the replace bar at full slots (needs contributions in the
journal first) and `_DISCARD_PACE_MARGIN` — run 12 made three pace calls with 5–9 % headroom
while play estimates missed by −18 % and +9 %, which suggests the margin ignores the spread of
its own inputs. Three observations is not a basis for moving a constant; the batch is.

## A14. Blind skipping was switched off, and nobody noticed for eleven runs — done.

Run 12
made **20 blind selections and skipped zero times**. The journal (E1a) finally said why: seven
were boss blinds, correctly unskippable, and thirteen were `цена тега числом не известна` —
among them `Negative Tag`, `Rare Tag`, `Polychrome Tag` and `Buffoon Tag` ×3. `decide_skip`
required an exact dollar price, `_tag_dollars` produces one for **two of the 24 tags**, so
twenty-two tags could never be chosen regardless of strength. An entire decision axis was inert,
and no test caught it because each individual refusal was correct.

The refusal was honest when written — `solver/skip.py` is Phase 9.2, older than the pack, shop
and voucher valuation this project has since built. It simply went stale, which is a failure mode
worth naming: a principled `None` does not stay principled once the machinery to compute it
arrives.

**It also connects to how run 12 died.** At antes 6–7 the bot sat on $69 with full joker slots
while offers of 3 880 went past, unable to convert money into board strength. `Negative Tag`
grants the next purchased joker a Negative edition — **+1 joker slot**, exactly that problem's
solution — and it walked past one.

**Three tiers, reusing the voucher pattern approved in A4**, in structurally separate fields so
computed and assigned numbers never mix: *score* for `Meteor`/`Buffoon` (each reduces to a free
Mega pack, priced by the existing `monte_carlo_pack` over the existing pools) and `Orbital` (+3
hand levels via `level_up`) — no new formulas; *dollars* for `Investment`/`Economy`, unchanged;
*structural* on the same 1–8 scale as vouchers with **deliberately the same anchor** — a Negative
edition is +1 joker slot, precisely what `v_antimatter` gives, so it takes `v_antimatter`'s 8.0
rather than an independently invented number, and a test pins the two together. Honest `None`
survives for `Handy`/`Garbage`/`Skip` (run-level counters the mod does not send) and
`Standard`/`Charm`/`Ethereal` (packs this project values nowhere). A coverage test asserts every
one of the 24 tags gets an answer or a stated reason, so the next tag cannot fall silently
through the hole these thirteen did.

**Lazy by measurement.** The pools cost 2.4 s (planets) and 9.8 s (jokers) while the blind screen
recurs ~20 times a run, so they are computed only when one of the three pack tags is actually on
offer. Measured after: `Negative`/`Handy` 0.00 s, `Orbital` 2.43 s, `Meteor` 2.45 s, `Buffoon`
10.19 s. The shop's `_SampleCache` is deliberately **not** stretched across screens — its key does
not describe this one, and stretching a cache key past what it models is exactly how A11's
stale-samples defect happened.

**Calibration risk, recorded rather than buried.** Replaying run 12's thirteen passed tags, the
bot now skips 4 of 9 with full slots and 6 of 9 with slots free. That is a large behavioural
swing resting on one run's evidence and on assigned numbers, and **no tier models the score
progress a skip forfeits** — only the $3–4 reward. The tier-1 bar being scaled to the next
blind's requirement is the guard, and it is an approximation. The next live runs are the
calibration; if skipping proves too eager, `_MIN_HEURISTIC_TAG_VALUE` and `_HEURISTIC_TAG_FLOOR`
are the knobs. Tests — `tests/test_skip.py::TestПокрытиеТегов`, `::TestЛенивостьОценкиТегов`.

## A15. A skipped blind is not a pending one — done.

Run 13 (ERRATIC) lost at **ante 1 in 15
steps**, the worst run in the project, and the journal named the cause in one line: `очки
344/300` on the round it lost. The bot had scored past its requirement and still lost, because
the requirement it was reading was not the one it was playing.

`_next_blind_requirement` filtered only `DEFEATED`, but a blind skipped for a tag returns as
**`SKIPPED`** (mod's `utils/gamestate.lua`, `convert_status_to_enum`). After the first skip the
function returned the *skipped* blind's requirement forever, so every threshold in the bot —
buy, pack, dead weight, pace, skip — scaled against a number 40 % of the real one. The pace
guard in particular saw a comfortable margin and played on without discarding. The same bug sat
in `solver/vouchers._rounds_left_in_ante`, inflating the dollar-tier horizon.

**The failure mode is the lesson, and it is A14's doing.** While skipping never fired — eleven
runs — `SKIPPED` could not appear in a state, so filtering on `DEFEATED` alone was correct *by
construction*. A14 turned the branch on and the old code kept reading its consequences under an
assumption that had quietly expired. The A14 notes state that exact lesson ("check who reads the
consequences"); it was then not applied. Both sites now share a named constant and a test walks
every status the mod can send, asserting each is deliberately classified — so a new status
cannot default into "still to play", which is precisely how this one did. Tests —
`tests/test_autopilot.py::TestПропущенныйБлайндНеСчитается`,
`tests/test_vouchers.py::TestГоризонтСоСкипом`.

## A16. The tag bar was wrong by mechanism, not by number — done.

The E1 batch was launched to
calibrate thresholds and answered in **two runs, both dead at ante 2**: the bot skipped every
skippable blind and played only bosses, arriving at each with no round income, no shop visits in
between, and the board it started the ante with. At the ante-2 boss it scored 328 of 1 600.

The bar was 2 because `_heuristic_tag_bar` was `max(6.0 − 1.0 × free_slots, 2.0)` and early game
has five free slots. Nothing on the 1–8 scale sits below 2, so **every** structural tag cleared
it. That relief came from vouchers, where the link is real — a voucher granting a slot is worth
more while slots idle — but **tags have no such link**: `D6` (free reroll), `Voucher` and
`Coupon` have nothing to do with slots. Worse, the sign came out backwards: the bar was lowest
exactly when the bot is weakest and most needs to play blinds to build money and a board. This
was an error of reasoning, not of calibration, which is why the relief was removed rather than
retuned. The flat 6.0 admits `Negative` (8), `Rare` (6) and `Polychrome` (6) — the tags A14
existed for.

Second, a **structural rule above all three tiers**: never skip a second blind in the same ante.
Forfeiting both small and big means reaching the boss with no income and no shop, and no tag
price offsets losing most of an ante. Detectable only because A15 taught this code to read
`SKIPPED`. Measured after: of the tags observed in runs 13–14 and the batch, only `Negative`,
`Rare`, `Polychrome` and the dollar-tier `Investment` still skip; `D6`, `Voucher`, `Uncommon`,
`Coupon`, `Holographic` no longer do. Tests — `tests/test_autopilot.py::TestКалибровкаСкипа`.

## E1b. Joker contributions in the journal — done.

Two items were blocked on the same missing
number: A13 could not say whether run 12's declined 8 145 offer was a mistake, and the joker-churn
question (10 bought, 5 sold in one run) had no evidence either way. `evaluate_shop` computed
`ShopAdvice.held` for the sell decision and threw it away, so the journal knew the board's labels
and nothing about what any of them was worth. `Action.board` now carries a `BoardEntry` per slot
(label, contribution, sell value) into `DecisionEntry` and the JSON.

**Attached by a wrapper, not at each `return`** — the shop branch has eight exits, several inside
helpers, and per-site filling is exactly how E1a ended up covering six of fourteen decision sites.
Same shape as `play_run` around `_play_run`. Confirmed live in run 14: `размен под Gros Michel:
оффер 4467 против вклада 2062` (accepted) and `Crafty Joker (1400) порог берёт, но слоты полны,
слабейший Hanging Chad (вклад 2639)` (declined) — both now checkable rather than taken on faith.
Tests — `tests/test_autopilot.py::TestСнимкаДоски`, `tests/test_runner.py::TestСнимкаДоскиВЖурнале`.

## E1c. The batch was measuring one run N times — done, and it failed silently.

After A16 the
relaunched batch produced **three runs identical to the digit** — discard estimates
430/577/640/692, final play 112, 16 steps each.

Cause, from the game's own source: `game.lua:2164` falls back to `generate_starting_seed()` when
no seed is given, and that builds the string from the **mouse cursor's position and hover time**
(`functions/misc_functions.lua:245`). When the runner starts runs over RPC the mouse never moves,
`cursor_hover` never changes, and every run gets the same seed. Not a defect in the mod or in this
project — **the game draws its randomness from human input, which unattended play does not
provide.**

Worth recording for the failure mode as much as the fix: nothing errored. The runs completed, the
reports printed, and a win-rate table would have looked entirely plausible while being one run
counted thirty times. It was caught only by diffing two journals against each other. `run_batch`
now draws a fresh seed per run from the game's own alphabet (8 chars of 1–9, A–N, P–Z; zero and O
excluded by the game itself, per `random_string`); an explicit `--seed` still pins every run,
which is the documented regression use. Tests — `tests/test_runner.py::TestСидыПакета`.

## A19. A mod refusal often means «not yet», not «not allowed» — done.

**This entry was written up from the code afterwards** — A19 was implemented and
tested but never got a §9.8 write-up, which is why the label appears in
`balatro_bot/runner.py` and `tests/test_runner.py` and nowhere in the documents. The
text below is a summary of the comment at `runner.py`'s retry site and of
`TestПаузаПередПовтором`'s docstring, not an independent account.

The mod checks the game's phase and state before acting — `endpoints/select.lua`
requires `BLIND_SELECT` and a non-empty `blind_on_deck` — and the game may still be
playing the transition animation when the runner asks. The runner retried
immediately, so it could exhaust `stall_limit` inside a second on a state that would
have settled by itself. A run in the big batch died exactly that way: the bot skipped
a blind and was refused three times in a row selecting the next one while the skip
animation ran. The retry now waits `_TRANSIENT_POLL_INTERVAL` — the same pause used
for a transitional phase, because it is the same case — and re-reads the state before
trying again. Tests — `tests/test_runner.py::TestПаузаПередПовтором`.

## A20. The suite now refuses the impossible — done.

Four defects this session were one class:
a joker valued from a state the game is never in — **A9** (contributions measured only with full
slots), **A10** (the wrong moment of the round), **A11** (money counted before the purchase),
**A18** (a candidate built with no sell value). Every one was found by a live run. None by
review, and none by a suite of a thousand tests — because they all asked *what a joker computes*
and none asked *what the counterfactual may never output*.

A18 is why this exists: its signature was visible without a game — `j_joker`, +4 Mult
unconditional, uplift **−1571**. That is arithmetic, not a judgement call. Three invariants now
assert it: an unconditionally beneficial joker never has negative uplift (the four such jokers
enumerated from the implementations rather than memory); a provably inert joker moves the number
by exactly `0.0`; and **exactness survives the counterfactual**, which A18 also broke and nothing
checked.

**Verified adversarially, not assumed.** Reverting A18's fix makes the new test fail at exactly
−1571 — the number from the journal. An invariant test that would not catch the bug it was
written for is worth nothing, and that is checkable in a minute.

**Two of the invariants were wrong as first written, and the tests caught it** — which is the
point of running them rather than reasoning about them. "An inert joker moves nothing" is false
on a board holding `j_abstract` (+3 Mult per joker) or `j_swashbuckler`: there, adding *any*
joker legitimately raises the score just by being in the list. And `Joker Stencil` is a real
exception — a joker can be worth less than an empty slot, which is A9's own finding — but not
against a strong candidate, whose flat bonus more than covers one lost multiplier. Both are now
scoped and pinned in both directions, so the exception stays a tested behaviour rather than an
untested excuse. Tests — `tests/test_shop.py::TestИнвариантыКонтрфактума`.

## C2. The bot could not buy consumables at all, and that was the root of the loss pattern — done.

The whole chain
below was measured over the full 15-deck rotation (32 runs) by following the question "why do
boards stop scaling at ante 4?", not by looking for this entry's confirmation. Three hypotheses
formed along the way were falsified by the next measurement and are kept at the end, because each
would otherwise look plausible enough to try again.

1. **The shelf offers consumables constantly and the bot buys none.** Across the rotation the
   shelves held **489 jokers, 123 Tarots and 120 Planets**; of the 243 consumables, **239 (98 %)
   were affordable at the moment they were offered**. The bot bought zero: `evaluate_shop`
   filtered `state.shop` to `item.kind == "JOKER"`, and `_shop_action` had branches for jokers,
   vouchers and packs and **no branch for a consumable at all**.
2. **Packs cannot make up the difference.** The bot does buy Celestial packs (45 of 55 packs
   bought) and does take Planets from them, but that yields **43 Planets across 32 runs — ~1.3
   per run**, scattered over hand types (Mercury 16, Earth 7, Uranus 6, Pluto 5, Venus/Saturn/
   Jupiter 3 each). A Planet raises **one** hand type by **one** level, so hand levels stay at
   1–2 for an entire run.
3. **At levels 1–3 the counterfactual correctly prefers additive jokers.** Sweeping hand level on
   one fixed board, the ratio of the best multiplicative candidate's uplift to the best additive
   one's is **0.42× at level 1, 0.74× at 3, 1.05× at 5, 1.52× at 8, 2.13× at 12** — monotone,
   crossing over around level 5. The valuation is not biased; it answers correctly for the hand
   levels it is given.
4. **So the boards fill with additive jokers.** On full boards the median count of multiplicative
   jokers is **0 at antes 3, 4 and 5**, and **56 %, 54 % and 54 %** of those boards hold none.
5. **And an additive board cannot track the blind.** Median board contribution grows **×5.05** at
   ante 3 against a requirement growing ×2.50, then **×2.17 vs ×2.50** at ante 4, **×1.69 vs
   ×2.20** at ante 5, **×1.30 vs ×1.75** at ante 7 — the stall lands exactly where the runs die
   (mean ante 4.6, median 56 % of requirement reached).

Plugging in the shop branch is therefore not "one more acquisition path" — it is the input the
whole joker economy was starved of, and it explains the otherwise confusing observation that
**joker valuation looks correct in isolation while producing losing boards**. That combination is
what made this hard to see from the code.

**What shipped.** `ShopAdvice.consumables` carries a `ConsumableOffer` per shelf consumable;
`autopilot._decide_consumable_buy_action` buys the best qualifying Planet, ordered after the
joker and voucher buys and before the strong replace, packs and reroll. `GameState.consumable_slots`
(the mod's `consumables` area `limit`) was added so a purchase into a full inventory is refused by
the bot rather than by the mod. `render_shop_advice` prints the shelf's consumables, because a
number the human cannot see is how this defect survived twelve runs.

**Only Planets are priced, and the refusal is measured rather than assumed.**
`evaluate_tarot_consumables` costs **334 ms on an empty board and 8 977 ms on five jokers** for a
single card against a real hand; the shop screen has no hand, so a shelf valuation would have to
sample hands — about 45 s per shop visit. The same number rules out the cheaper idea of buying a
Tarot speculatively and deciding at use time: making Tarots reachable at all would put that
nine-second stall on every hand of the run. Tarot/Spectral therefore get an honest `None` with the
reason attached, which the autopilot can read and silence would not give it.

**The Planet number comes from the same place the Celestial pack's does** — `solver.pack.level_up`
over `PACK_SAMPLE_HANDS = 5` representative hands — and a test pins the shelf figure to the pool's
entry for that hand type, so two routes to one quantity cannot drift. The sampling was split, not
duplicated: `planet_uplifts(state, hand_types, deck_source)` computes one shared baseline for the
set it is asked for, and `planet_uplift_pool` is now a wrapper over all twelve. The set is a
parameter because the cost is real — **807 ms for one hand type, 1 198 ms for two, 5 174 ms for
all twelve** on a five-joker board — and a Planet on the shelf needs exactly one of the twelve.

**The bar is deliberately not A2's, and both candidates were measured before choosing.** A2 asks
"is this worth a permanent slot"; a Planet takes no permanent slot, and its uplift is measured on
hands dealt now while the level-up lasts the run, so the figure is a known under-estimate —
applying a bar calibrated for a complete measurement on top of an incomplete one doubles the
error. `_CONSUMABLE_NOISE_FRACTION` is assigned from `_DEAD_WEIGHT_REQ_FRACTION` (0.5 %) as the
same object, for the same reason `_PACK_MONEY_RESERVE` is assigned from `_REROLL_MONEY_RESERVE`.
Replaying 22 shelf-Planet decisions out of the journals:

| bar | fires | latest ante it fires at |
|---|---|---|
| A2, 3 % of requirement | 5 of 22 | ante 4 |
| noise guard, 0.5 % | 9 of 22 | ante 7 |

A2 would have left the behaviour unchanged at exactly the antes where the runs die, which is the
outcome worth avoiding: a fix that measurement says will not fire.

**Honest limits, recorded rather than papered over.**

1. The uplift is measured on hands sampled **now** while a level-up is permanent, so the number is
   a lower bound. That is *why* the bar is a noise guard rather than a strength judgement, not a
   detail beside it.
2. The strategic effect this entry itself identified — higher levels make multiplicative jokers
   worth buying — is **not modelled**. The branch repairs the acquisition channel, not the
   valuation of its delayed consequence.
3. A Planet whose hand type does not appear in the five sampled hands reads exactly 0 and is
   refused. Correct now; not necessarily correct over the run's horizon.
4. **The $12 reserve is not free, and it costs the most where the purchase is worth the most.**
   Replaying all **135** shelf-Planet decisions from the rotation end-to-end: 67 clear the bar,
   **35 are bought, and the reserve blocks 32 — 48 % of everything the bar admits.** By ante:

   | ante | clears the bar | blocked by the reserve | bought |
   |---|---|---|---|
   | 1 | 11 | **10** | 1 |
   | 2 | 19 | **12** | 7 |
   | 3 | 12 | 5 | 7 |
   | 4 | 16 | 5 | 11 |
   | 5–7 | 9 | 0 | 9 |

   The blocking is concentrated in antes 1–2, where the bot is poorest — and a level bought at
   ante 1 is the one that compounds over the whole run, so this is the opposite of where a
   reserve should bite. The reserve itself is not wrong: run 4 died to a policy without one, and
   that reasoning is about *rerolls*, which need money afterwards to buy what they find, whereas
   a $3 Planet is complete in itself and costs at most $1 of interest. Reusing
   `_PACK_MONEY_RESERVE` was chosen deliberately to avoid a second constant with one
   justification, and this table is the price of that choice, recorded so the trade is visible.
   **Open question for the next batch**, not a defect to fix blind: whether a smaller reserve for
   an item this cheap wins more than it loses.

**Three hypotheses falsified on the way here**, kept so they are not re-tried:

- *"The bot starts slowly and never builds a board."* No — slots are full by ante 3 (median joker
  count 1 → 4 → 5) and stay full for the rest of every run.
- *"The board locks in early and never turns over."* No — 60 % of the first full board survives to
  the end, with a median of 3 new jokers arriving after the slots first fill; only 3 of 23 runs
  never changed composition.
- *"The counterfactual is biased against multiplicative jokers."* No — sweeping **board size** 0→4
  jokers, the multiplicative/additive ratio is **flat at 0.42×**. Added chips are multiplied by the
  board's mult just as XMult is, so both sides scale together. The variable is hand **level**, not
  board strength; an earlier single-pair result (Cavendish overtaking Gros Michel on a stronger
  board) was a property of that pair and I over-read it.

**Caveats on the measurement itself.** The ante ≥ 6 rows of the growth table are survivors — only
3 runs reach ante 8 — so only the ante 1–5 portion carries weight; that is the portion the argument
uses. The crossover sweep is one board and one hand, so "level ≈ 5" is the shape of the curve, not
a constant to hard-code.

**What this leaves open.** `The Fool` and the rest of C1's Tarot valuation are still unreachable —
the Tarot half of the channel is a separate slice, and it needs a cheap valuation before it needs a
branch. Whether the branch actually moves hand levels, and win rate, is a live-batch question, not
a test question: the tests pin the policy, only a run can price it.

**Tests** — `tests/test_shop.py::TestОценкаРасходников`,
`tests/test_autopilot.py::TestПокупкаПланетыВМагазине`,
`tests/test_render.py::TestРендерРасходниковМагазина`, and the two `consumable_slots` cases in
`tests/test_mod_bridge.py`.

## A21 + A22. The reroll policy was wrong in both directions at once — done.

PLAN.md had been calling these a contradiction inside one policy without writing A21 down at
all; it exists now because the two only make sense together. Both halves were re-measured on
the full 35-run rotation (`runs/decks`) rather than carried over from the earlier note.

**A22 — the bot rolled when a find had nowhere to go.** `_decide_reroll_action` is the last
shop branch, reached only after buy, voucher, Planet, replace and dead-weight sell have all
declined — which is precisely when the board is full and staying full. Measured: **167 of 216
rerolls (77 %) were made with a full board, and $887 of $1 141 went there.** Of the 16 shop
exits holding an offer worth more than 200, **all 16 read «слоты полны» and not one read
«дорого»**:

```
ante 5  $13  Splash     uplift 4089  price $3  NO SLOT
ante 6  $25  Arrowhead  uplift 4740  price $7  NO SLOT
ante 7  $29  Odd Todd   uplift 4571  price $4  NO SLOT
```

The roll found exactly what it was asked for — thousands of uplift, trivial prices, money in
hand — and the find was unusable. The bot paid $5 to search a shelf it had just established it
could not buy from.

**My first reading of these numbers was wrong** and is kept because the correction is the
useful part. I suspected the estimate: `RerollOutlook.expected_best_uplift` is stationary,
drawn from a fixed pool of 24 random jokers, so "the roll over-promises" was the natural
suspicion. E1e added the shelf to the journal and the shelf said otherwise — comparing before
and after each roll, the best offer improved in 5 of 9 early pairs, mean best going 88 → 263.
The roll does its job; the *policy around it* did not.

**The fix asks a question the policy never asked: what would a find have to clear to be
usable?** `_reroll_target_bar` answers it from the state, not from a new rule — with a free
slot, `_worth_buying` exactly as before; with full slots, the bar `_decide_replace_action`
itself applies (strictly above the victim's contribution, and either the victim is dead weight
or the offer is `_REPLACE_UPLIFT_RATIO`× stronger); with full slots and nothing sellable,
`None`, meaning no outcome could help. The replace rule is *read from the same constants*
rather than restated, because a gate that drifted from it would license rolls the replace then
refuses — this defect, back again.

**Replaying the journals through the real gate: 123 of 167 full-board rolls blocked (74 %),
about $657.** The 44 that survive are the ones whose expectation really could displace the
weakest joker. A typical blocked case is roll expectation 908 against a weakest contribution
of 1 368: no result could have been used, and $5 was paid to look.

Improvement C2 (shelf Planets) covers only **25 of those 167**, so it does not overlap this.

**A21 — the bot could not roll when it would have helped.** The same rotation shows **87 shop
exits with a free joker slot and no purchase; 84 of them (97 %) with under $17**, median $11,
and **63 of the 84 at antes 1–2**, where the board is laid down. Under the $12 reserve, 3 of
87 could have rolled.

**The root is one number answering three questions.** `_PACK_MONEY_RESERVE` was assigned from
`_REROLL_MONEY_RESERVE` with a comment arguing the justification was word-for-word identical
and two constants would drift. The argument was wrong on its premise: a reroll is the only
purchase whose money is needed **afterwards** — it buys nothing, it only reveals what could be
bought — while a pack or a Planet is complete in itself. Calibrated for the pack's question,
the shared number then refused the roll in exactly the situation the roll was for.

So the reserves are now separate, each with its own question:

| constant | question it answers | value |
|---|---|---|
| `_REROLL_MONEY_RESERVE` | will there be enough to buy what the roll finds? | `TYPICAL_JOKER_PRICE` = $5 |
| `_PACK_MONEY_RESERVE` | will this empty the pocket? (A13, run 12) | $12 |
| `_CASH_RICH_RESERVE` | is the bot wealthy enough for a structural upgrade? (A7) | $12 |

$5 is not a guess: over the rotation's **575 shelf joker offers the median price is exactly
$5** (quartiles $4–$6, 90th percentile $7), which is what "enough to buy what the roll was
for" means. Replayed through the real reserve, **48 of the 87 exits (55 %) can now roll.** When
slots are full the victim's `sell_value` counts toward available money — not counting it would
compare the two sides in different states, the mistake improvement A11 was written to close.

**This does not restore run 4's drain to $0.** Then the reserve was the only brake on a
streak; since A8 the streak is bounded by `_MAX_REROLLS_PER_SHOP = 2`, and the "reserve remains
after paying" condition makes the money floor constructive — the till cannot go below the
reserve. The honest edge stays the one A8 already recorded: `economy.rerolls_done` derives the
roll count from the price, and a Reroll tag or Chaos the Clown temporarily lowers that price,
so in those cases the count under-estimates and errs toward allowing a roll.

**A third consumer surfaced during implementation, and how it surfaced is the point.**
`_heuristic_voucher_bar` (A7) also read `_REROLL_MONEY_RESERVE` — for a *third* question, "is
the bot cash-rich" — so lowering the reroll reserve would have silently moved A7's wealth test
from $12 to $5. The plan for this work named three consumers and missed that one; the existing
test `test_a7_при_нехватке_денег_порог_overstock_базовый` caught it on the first run. A7 now
has `_CASH_RICH_RESERVE` and its behaviour is byte-identical. That a shared constant had spread
to a fourth meaning without anyone noticing is the strongest evidence for the split itself.

**The journal must name the refusal.** `_reroll_block_reason` appends to `_shop_nothing_reason`
the same way `_consumable_block_reason` does, and for the same reason: without it a
«ушёл из магазина» line cannot separate "did not roll because the find had nowhere to go" from
"did not roll because money was short". That indistinguishability is what let A13 draw a wrong
conclusion, and what let this defect sit unnoticed for twelve runs.

**One test was rewritten on purpose, which is worth flagging rather than hiding.**
`test_не_рероллит_без_денежного_запаса` encoded the old $12 (money = $15). It now checks the
same rule at the new number ($8 − $5 = $3 < $5), and a companion test pins that $15 *does* now
roll — the boundary moved, it did not disappear. Changing a test alongside a deliberate policy
change is legitimate; changing one to make a red suite green is not, and the difference is that
the new behaviour was predicted and measured before the test was touched.

**Honest limits.**

1. The full-slots bar checks only the *uplift* a find would need, never its price —
   `RerollOutlook` describes a card that has not been drawn, so no price exists. The sell
   refund compensates partly; it is not an exact account.
2. `expected_best_uplift` is still stationary (24 sampled jokers, blind to the shelf). This
   work changed the **bar**, not the estimate; whatever bias the estimate carries, it carries.
3. The $5 reserve is the *median* joker price, so roughly half the time a find will still be
   unaffordable. That skew toward looking is deliberate: A21 is a run that died because the bot
   did not look.
4. The "123 of 167" figure takes the weakest board joker without knowing whether it is eternal
   — `BoardEntry` does not record that — so a few boards with an eternal weakest may count
   slightly differently. Too few to move the figure.

**Tests** — `tests/test_autopilot.py::TestРероллКудаКластьНаходку`,
`tests/test_shop.py::TestКандидатНаРазмен`, plus the rewritten reserve pair in
`TestDecideActionРеролМагазина`.
