# Spec: choosing a discard without enumerating every option

This document is self-contained: you can implement the task from it without reading the
conversation. This is **Phase 6** of the project (see `PLAN.md`).

## 1. What already exists

Python 3.12, no core dependencies. Everything works and is covered by 249 tests.

| Module | What it provides |
|---|---|
| `core/cards.py` | `Card`, `Rank`, `Suit`, `Enhancement`, `parse_cards`, `effective_suits` |
| `core/hands.py` | `HandType`, `HandModifiers`, `evaluate(cards, mods) -> HandResult` |
| `core/scoring.py` | `score_play(state, played, jokers, mods) -> ScoreOutcome` |
| `core/state.py` | `GameState`: hand, jokers, hand levels, blind, round resources |
| `core/jokers/` | `build_jokers(state)`, `modifiers_from(jokers)` |
| `solver/play.py` | `rank_plays(state, limit)` — all 218 plays, sorted by score |

The key performance constraint: **`rank_plays` costs ~13 ms.** That's a full search over
the 218 subsets. It, not the probability arithmetic, sets the price of the whole decision.

## 2. The task

The hand has 8 cards. You can discard 1 to 5, draw the same number, and then play.
We need to advise **what to discard**.

The naive path — enumerate the 218 discard subsets, run a Monte-Carlo over the draw for
each, and call `rank_plays` inside every sample. That's 218 × 1000 × 13 ms — on the order
of an hour. Unacceptable.

## 3. The idea: enumerate targets, not discards

**A discard is a consequence of a target.** If you decided to build a heart flush, you keep
the hearts and discard everything else. The discard doesn't need to be searched for: the
target determines it uniquely.

A hand has about 30–40 targets versus 218 discards, and most discards are pointless.

The probability of hitting a target is computed **exactly** with the hypergeometric
distribution, with no sampling at all.

## 4. Algorithm

### 4.1. The unseen deck

`unseen = deck composition − the cards we can see`.

- **Via the mod**: the deck composition is known exactly, together with all enhancements.
- **With manual input**: there's no exact composition. We take the standard 52 cards minus
  what's in the hand, and **mark the result inexact**. This is required behaviour, not a
  wish: see section 8.

### 4.2. Enumerating targets

A target is a triple "what we keep, what we need, how many".

```
Target = (name: str, keep: tuple[Card, ...], outs: tuple[Card, ...], needed: int)
```

`outs` — cards of the unseen deck that advance the target. `needed` — how many of them are
required.

To enumerate:

| Family | How it's built | How many targets |
|---|---|---|
| Flush | per suit: keep the cards of that suit | 4 (or 2 with `smeared`) |
| Straight | per window of 5 consecutive ranks, from `A-2-3-4-5` to `10-J-Q-K-A` | 10 |
| N of a kind | per rank in the hand: up to three, four, five | ≤ 24 |
| Full house | best three of a kind + best pair | 1–2 |
| Keep as is | keep the cards of the best current play | 1 |

**Modifiers must be taken into account** (`HandModifiers` from `modifiers_from`):

- `four_fingers` — a flush and a straight need 4 cards, not 5. It changes `needed` **and**
  the list of targets: some of them are already complete;
- `shortcut` — a straight may skip a rank, the windows are enumerated differently;
- `smeared` — hearts equal diamonds, clubs equal spades: effectively two suits;
- `Wild` cards match any suit — take suits via `effective_suits`.

Targets are built **after** the modifiers are applied, otherwise the list will be wrong.

### 4.3. Filtering

A target is dropped if:

- `needed <= 0` (already complete — not a target for discarding);
- `needed > 5` (can't be drawn in a single discard);
- `needed > len(outs)` (not that many left in the deck);
- it would require discarding more than 5 cards.

### 4.4. Collapsing identical discards

**Important and easy to miss.** Different targets often produce the same discard: holding
`AH KH QH 9H`, you're playing both toward a heart flush and toward a `9-10-J-Q-K` straight.
Such a discard serves both targets, and its value is higher than either one alone.

So after enumeration, targets are **grouped by the set of kept cards**. From then on it's a
discard option that's evaluated, not a target; the target names are kept for explaining to
the human.

### 4.5. Evaluating an option

For an option "keep `keep`, discard `k` cards" with a set of outs `outs`:

```
N = |unseen deck|
S = |outs|
P(exactly i drawn) = C(S,i) · C(N−S, k−i) / C(N,k)

EV = Σ_i  P(i) · E[score | i outs drawn]
```

The first part is exact arithmetic, `math.comb`, integers, instant.
The second is the only place where sampling is needed: assemble a few representative hands
with exactly `i` outs and average `rank_plays(...)[0]` over them.

**Do not replace the sum over `i` with "hit / missed".** Verified: the binary split gives an
error of up to 16%, because "missed" isn't zero, it's a wide spread (see section 7).

### 4.6. What to return

```
DiscardOption = (
    discard: tuple[Card, ...],       # what to discard
    keep: tuple[Card, ...],
    expected: float,                 # expected score after the draw
    distribution: tuple[(i, p, score), ...],   # breakdown by number of outs drawn
    targets: tuple[str, ...],        # which targets it serves
    exact: bool,                     # always False, this is an estimate
)
```

The list of options is sorted by `expected` and returned in full, not as a single piece of
advice — as in `solver/play.py`. `distribution` is there so the human can see what the
estimate is made of and disagree.

Comparing with "play now" must be honest: `advise(state).best.score` against the `expected`
of the best discard, adjusted for the fact that a discard spends a resource.

## 5. Where to plug it in

A new module `balatro_bot/solver/discard.py`. Existing files are not changed, except
`cli.py`, which gets the discard-advice output added.

The public function:

```python
def advise_discard(state: GameState, limit: int = 5) -> tuple[DiscardOption, ...]
```

If `state.discards_left <= 0` — return an empty tuple, don't compute.

## 6. Edge cases

- no discards left → empty result;
- fewer than 2 cards in hand → discarding is pointless;
- the unseen deck is smaller than the discard size → cut such options;
- stone cards have no rank or suit: they don't count toward "flush" and "straight" targets,
  but they take up space in the hand;
- debuffed cards — don't discard them automatically: the boss effect applies to the current
  round, not to the drawn cards;
- `needed == 0` after applying `four_fingers` — the target is already complete, it's not a
  discard.

## 7. Verification: a mandatory part, not a wish

**The slow Monte-Carlo stays — but in the tests, as the ground truth.** The fast analytic
path is checked against it, not taken on faith.

Reference implementation (tests only): discard, honestly draw from the unseen deck, call
`rank_plays`, average over 400 samples.

### Acceptance criteria

1. **Order matters more than numbers.** On a corpus of ~20 hands, the order of the top three
   options by the analytic path matches the order by the reference at least 90% of the time.
2. **The expected value** deviates from the reference by no more than 15%.
3. `advise_discard` runtime — no more than 200 ms per hand.

### What has already been measured

Prototype on the hand `AH KH QH 9H 2C 7D 3S 4S`, no jokers, 200–400 reference samples:

| option | chance | analytic | reference | deviation |
|---|---|---|---|---|
| keep `AH KH QH 9H` (flush ♥, need 1) | 61.4% | 273 | 268 | +2.0% |
| keep `AH 2C 3S 4S` (straight A-5, need 1) | 32.7% | 116 | 123 | −5.4% |
| keep `AH KH QH` (need 2) — binary | 26.7% | 227 | 196 | **+16.3%** |
| same, by the distribution from 4.5 | — | 179 | 197 | −9.2% |

**The order of the options matched the reference.** That is the main result of the check.

The residual 9% is not from the probabilities — those are exact — but from the score spread
**within** a bucket: only 6 representative hands were averaged. A larger sample reduces the
error, but runs into the cost of `rank_plays`.

## 8. The honesty requirement

The project has a project-wide rule: a calculation that can't be trusted to the last unit
must be marked. Here that means:

- `exact` on `DiscardOption` is **always** `False` — it's an estimate, not a computation;
- with manual input, additionally mark that the deck composition is assumed;
- in the output, show the spread, not a single number.

Silently returning a plausible but wrong estimate is the worst outcome for an advisor.

## 9. What's out of scope

We compute **one move ahead**: discard → draw → play.

Deliberately not doing:

- multi-step computation when several discards remain;
- accounting for how many hands are left before the blind, beyond the current one;
- the effect of the draw on future rounds and on the shop;
- jokers that change the draw itself.

The one-step estimate **underrates** the value of half-built targets: with two discards left
a player can build a target twice. This is a known limitation, and it must be stated in the
output, not hidden.

## 10. The main fork for the implementer

The cost of the decision is set not by the probabilities but by the function "how much does
this hand give". Right now that's `rank_plays` — 13 ms, a full search over the 218 subsets.

Estimating a discard needs a **cheap version of that same function**: the maximum is enough,
not the whole list. A reasonable path is to prune obviously weak subsets before the full
count. The exact search then stays where the final play recommendation is produced:
approximation is acceptable inside the discard estimate, where we're approximating anyway,
but not in the advice itself.
