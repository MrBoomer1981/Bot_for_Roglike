# Adding a joker

The five steps for implementing a joker's effect, and the reasoning behind each. This used to
live in [CLAUDE.md](../CLAUDE.md), which loads into every session — it is 7 KB that matters only
when a joker is actually being added, so it moved here and CLAUDE.md keeps a pointer.

The short version: find the key, subclass the right family base, never guess a number, and read
the game's own Lua source before recording anything as unknowable.

1. Look up the joker key in `core/catalogue.py` (e.g. `j_joker`).
2. Implement in `core/jokers/implementations.py` using `BaseJoker` and the `@register("j_key")`
   decorator.
3. Override `react(self, event: Event, ctx: ScoreContext) -> Iterable[Effect]` and
   `isinstance`-check for the event(s) you care about (`JokerTurn`, `CardScored`, `CardHeld`,
   `RetriggerQuery`) — there is no per-event method name to hook into. For the common "fires once on
   this joker's own turn" shape, subclass `_OwnTurn` and override `on_turn(self, ctx)` instead; most
   existing jokers do this. Reusable family base classes already exist for common shapes:
   `_ConditionalJoker`/`_conditional(...)` for "if the hand contains X, add chips/mult/xmult";
   `_SuitBonus`/`_suit_joker(...)` for "cards of suit X give +chips/+mult when scored";
   `_PerScoredCard` for "react to each qualifying scored card"; `_RuleChanger` for jokers whose only
   effect is a `HandModifiers` flag (checked in `modifiers_from()`, e.g. `four_fingers`, `splash`,
   `pareidolia`, `chicot`, `oops`); `_FullDeckJoker` for "X per card of type Y in your full deck"
   (`j_steel_joker`, `j_stone`, `j_drivers_license`, `j_erosion`) — backed by `GameState.full_deck`,
   which the mod bridge can only fill in exactly when nothing has been played or discarded yet this
   round (the mod's `openrpc.json` has no field for the full deck, only the remaining draw pile —
   see PLAN.md section 8.2 for why), so treat it as `None`-checked optional data like
   `GameState.deck`, never as always-present. For a probabilistic joker/enhancement with a "no luck
   / bonus" two-outcome table (Lucky, `j_bloodstone`), route it through
   `core.scoring.double_chance(outcomes)` gated on `ctx.modifiers.oops` so `j_oops` (Oops! All 6s)
   doubles it automatically — don't hand-roll a second doubling formula. **If the joker reads any
   `GameState` field** (`hands_left`, `money`, `hand_info`, …), check it against the A11 audit table
   in `docs/architecture.md`'s `solver/shop.py` entry before finishing: the shop counterfactual has
   to model that field, or the joker is priced from a state the round is never in and the autopilot
   sells or overbuys it. Four separate live runs were lost to instances of exactly this (A8, A9,
   A10, A11) — the table exists so the fifth isn't.
4. If the joker's real effect is a permanent accumulator ("gains X per Y", "(Currently +N)") built
   up from events the game state doesn't expose a history of (past discards, past sells, past
   rerolls, etc.), don't reconstruct the history — the game already computes the running total and
   renders it into the joker's live effect text (`value.effect` in the mod's response, e.g. "+3 Mult
   for each Joker card (сейчас +15 множ.)"). `mod_bridge` pulls the live value out of that text into
   a few `JokerCard` fields, all `None` (manual input, or the text didn't have what was expected)
   auto-marking the calculation inexact instead of guessing — this only ever works live through the
   mod bridge:
   - `current_value: float | None`, via `_extract_current_value` — the number in the *last*
     parenthesized group (structurally, by position, not by matching the word "currently"/"сейчас",
     so it survives any game locale). Subclass `_LiveAccumulator` (or the `_accumulator("chips" |
     "mult" | "xmult")` factory) to apply it directly — the effect *type* is already known from the
     catalogue text, only the magnitude comes from the field.
   - `leading_value: float | None`, via `_extract_leading_value` — same idea but the *first* number
     in the text, not the last, for the handful of jokers (`j_popcorn`, `j_ramen`) whose live value
     renders first with a static decay-rate constant after it (confirmed from the game's own
     `card.lua`, see below). Subclass `_LeadingValueJoker`.
   - `target_suit`/`target_rank: Suit | Rank | None`, via `_extract_word` matching against
     `_SUIT_WORDS`/`_RANK_WORDS` — for jokers whose "current target" (a suit or rank that rotates)
     is round-level state (`G.GAME.current_round.*`) with no field in the mod's schema at all, only
     ever rendered as a word inline in the joker's own text (`j_ancient`, `j_idol`). This is the one
     place in the project where extraction is tied to game locale rather than text structure — the
     word dictionaries only cover Russian and English.
   - `loyalty_active: bool | None`, via `_extract_loyalty_active` matching literal
     "Active!"/"Активно!" vs "remaining"/"осталось" — for `j_loyalty_card`, whose trigger depends on
     which run-hand this joker was bought on (not tracked anywhere), but which the game itself
     renders as one or the other.

   If the joker's effect provably never touches chips/mult for the play being scored (pure economy,
   consumable creation, shop/meta effects, or a passive already reflected in the observed state like
   hand size or discards left), register it as a bare `BaseJoker` with a docstring quoting the
   catalogue text and a short comment explaining why it's a real zero, not a shortcut — see the
   "Известны, но на счёт розыгрыша не влияют" section at the bottom of `implementations.py` for the
   established pattern and precedent. Static game constants that never change at runtime (deck
   starting size, joker rarity) belong in a hardcoded table next to the joker that needs them
   (`_DECK_STARTING_SIZE`, `_JOKER_RARITY`) — verify such tables against an external source rather
   than from memory, and add a test asserting the table's coverage/counts, since a single bad entry
   produces a silently wrong score. For anything uncertain about a joker's *real* mechanic (not just
   its current numeric state) — exact trigger condition, what a var actually represents, whether a
   value is per-instance or round-level — the base game's own Lua source is extractable and
   authoritative: `Balatro.app/Contents/Resources/Balatro.love` is a plain zip (LÖVE engine format);
   `card.lua` has every joker's `calculate`/`loc_vars` logic (searched by `self.ability.name`, the
   display name, not the `j_key`), and `localization/{ru,en-us}.lua` have the exact text templates
   and word lists. Reading this beats guessing from the catalogue's static (English, un-substituted)
   text or from memory — that's how the `current_value`/`leading_value` split and the
   `target_suit`/`target_rank`/`loyalty_active` mechanisms above were each confirmed rather than
   assumed. **The same source settles ordering questions, not just per-joker ones**: `game.lua`
   holds the base hand-value table (`G.GAME.hands`) and every joker's `config`;
   `functions/state_events.lua`'s `G.FUNCS.evaluate_play` is the authoritative scoring order,
   including the `context.before` pass that runs *before* base chips/mult are read; and `blind.lua`
   has each boss's `modify_hand`. Improvement A12 used exactly these to close four long-standing
   PLAN.md §8.3 assumptions and to find four real defects, after those items had sat for months
   labelled "needs a Mac" — a label that was wrong about six of seven of them. Before recording
   anything as unknowable without a running game, read the source. Only `j_hiker` has no
   implementation at all: its bonus permanently attaches to individual *playing cards*
   (`context.other_card.ability.perma_bonus`), not the joker, which needs a new per-card mechanism
   this project doesn't have yet.
5. Add tests in `tests/test_scoring.py`.
