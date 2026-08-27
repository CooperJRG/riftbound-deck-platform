# Smart Decks — plan

A guided builder: pick a legend, get shown the best deck for it, mark what you're short,
and keep going until you have the best deck you can actually field.

---

## 1. What it has to do

1. User picks a legend.
2. We show the top-performing deck for that legend.
3. User marks what they're short — **per copy**, not per card. Missing one of a 3-of is a
   one-copy hole, not a whole slot.
4. We move on to a deck that isn't ruled out by what they've told us.
5. **Acceptance criterion:** if the user owns *any* legal deck for that legend, we find
   one within a few rounds.
6. Beyond the minimum, we should find the *best* deck they can build.

Point 5 is the hard one, and points 5 and 6 pull in different directions: one is
satisficing, the other optimising. The design runs them as two tracks rather than
pretending they are the same search.

---

## 2. Why picking decks off a list cannot satisfy point 5

Measured against the live snapshot (3,067 decks, 48 legends):

| | |
|---|---|
| decks per legend | median 34, max 314 |
| distinct cards used by *all* a legend's decks | 99–155 |
| cards legal for a legend (domain-filtered) | **~266 main, 2 runes, 67 battlefields** |
| main-deck overlap between two decks of one legend | median Jaccard **0.57** |
| staples (in ≥80% of that legend's decks) | 11–14 cards |

Two consequences.

**Selection has a ceiling.** A published deck is a 40-card exact list. The chance a casual
collection contains one exactly is low, and if none of the ~34 published decks fits, the
user is told "no" — even though they may well own enough cards to build something legal.
Only *construction* can answer point 5. Selection alone provably cannot.

**Ranked order is a bad question order.** Because decks for a legend overlap at ~0.57,
showing decks #1, #2, #3 by score asks about mostly the same cards three times. Greedy
information-first selection covers 50% of a legend's card pool in **3–4 decks**; score
order needs far more. The question *which deck to show next* is a real optimisation, and
getting it wrong is what would turn "a couple of rounds" into fifteen.

---

## 3. Architecture

### 3.1 Knowledge state

Every answer teaches something exact. Per card, we hold one of:

| state | meaning | source |
|---|---|---|
| `exact(n)` | user owns exactly n | they marked it in a shown deck |
| `at_least(n)` | user owns ≥ n | card appeared in a shown deck and was *not* marked |
| `unknown` | never asked | — |

The `at_least` case matters more than it looks: an unmarked 3-of tells us they own 3,
which is the copy limit, which is "as good as fully owned" for every future deck. After a
few rounds most of a legend's staples are pinned at the cap.

This is deliberately the same shape as the existing `AvailabilityProfile` in collection
mode, so the wizard's knowledge *is* an availability profile and everything already built
— `deck_coverage`, card shading, `buildableOnly` — works against it unchanged.

### 3.2 Two tracks, run every round

**Track A — the floor (guarantee).** After each answer, run the feasibility oracle over
known-owned cards. If a legal deck can be built, we have a definite answer and show it as
*"you can build this right now"*. This is what satisfies point 5, and it can only improve.

**Track B — the ceiling (optimise).** Keep proposing high-evidence decks to beat the
floor. This is what satisfies point 6.

The UI always shows the current floor, so the user is never left with nothing while we
keep looking.

### 3.3 Three phases

**Phase 1 — Propose** (rounds 1..N). Show a deck, learn from the gaps. Most users finish
here. Deck choice is information-aware (§4.1).

**Phase 2 — Repair.** When a deck is only a few copies short, don't discard it — fill the
holes from cards we know they own (§4.3). A deck four copies short is much closer to
buildable than a binary check suggests.

**Phase 3 — Complete** (fallback). If the floor is still empty, stop showing decks and
ask one compact, role-grouped question over the cards that would actually close the gap
(§4.5). This is what makes point 5 a guarantee rather than a hope.

---

## 4. The algorithms

### 4.1 Which deck to ask about next

Score each surviving candidate deck:

```
priority = w1 · quality        # existing meta score: evidence, placement, recency
         + w2 · plausibility   # P(user can field it), from what we know + rarity prior
         + w3 · information    # how much this answer resolves about other candidates
```

- **quality** — reuse `meta_scoring` unchanged.
- **plausibility** — fraction of the deck's copies already known-owned; unknown cards get
  a prior from **rarity** (a Common is likelier owned than a Showcase). If the user is
  already in exclusion mode, their exclusions seed this for free.
- **information** — for each unknown card in the deck, how many *other* candidate decks
  contain it. Asking about a card that appears in 40 candidates resolves far more than one
  that appears in 2. This is the term that turns 15 rounds into 4.

Round 1 ignores `information` and shows the straight best deck, because the first
impression should be "here is the best Draven deck", not a strange probe.

### 4.2 Ruling decks in and out

A deck is **ruled out** when it needs more copies of a card than the user is known to own
*and* the hole cannot be repaired (§4.3). Note this is per copy: needing 3 Charm when they
own 2 is a 1-copy hole, not a rejection.

### 4.3 Repair — the "fills"

Holes are measured in **copies**, not cards. For each hole:

1. **Same card, fewer copies** — if the deck runs 3 and they own 2, keep 2 and fill 1.
2. **Cluster substitution** — decks for a legend cluster tightly (Jaccard 0.57). Within a
   cluster, the *core* (≥80% frequency) is the identity and the rest is flex. Fill a flex
   hole from cards the user owns that the meta plays alongside this core, ranked by:
   co-occurrence with the core (PMI over the legend's decks), same card type, similar cost
   (preserve the curve), domain-legal, copy limit respected.
3. **Role fill** — if no meta substitute is owned, fall back to any owned legal card in
   the same type + cost band. The deck is legal and playable, just off-meta.

**Decided: offer both, labelled.** A proposal shows the conservative repair first — swaps
drawn only from cards the meta plays alongside this deck's core, so the result is still
recognisably the deck that won — and, when that is still not enough, a fuller build
underneath. Each carries how far it drifted from the original and which cards changed.

The two are genuinely different products and must not be blurred: one is "the tournament
deck, adapted"; the other is "a legal deck in the same colours". A player deserves to know
which one they are holding, so drift is disclosed on the card, not buried in a tooltip.

### 4.4 Feasibility oracle and construction

**Feasibility** (cheap, run every round). Given known-owned cards, filter to the legend's
legal pool (domain identity, card type, ban list), then check:

- ≥ 40 main-deck copies available (each card capped at 3, or 1 if unique)
- ≥ 12 rune copies in-domain — only 2 rune types per legend, so this is nearly always the
  binding question and is worth asking early
- ≥ 3 *distinct* in-domain battlefields
- the legend itself, and ≥1 champion sharing a champion tag with it, in the main deck

This is a counting check, not a search. It answers "is a legal deck possible?" in
milliseconds and tells us exactly which constraint is binding — which is what Phase 3
needs to ask a good question.

**Construction** (when feasible). Choose *which* 40 by greedy fill ordered by meta
frequency within the legend, then the co-occurrence signal, subject to the same
constraints. Not a solver; a sort and a greedy pass, because the constraints are
near-independent. If a later constraint binds (e.g. signature limits), backtrack the last
picks only.

Deliberately **not** an ML model. The autopsy's finding stands: v2's mixture-of-experts
could not explain a recommendation and its clusters scored a 0.026 silhouette. Frequency
and co-occurrence over 3,000 real decks is a stronger signal and can be shown to the user.

### 4.5 Phase 3 — the closing question

Driven by *which constraint is binding*, not by a generic checklist:

- short on main-deck copies → ask about the top-N most-played cards for this legend whose
  ownership is still unknown, grouped by role, N sized to close the gap with margin
- short on runes → one question, two rune types
- short on battlefields → the ~10 most-played legal battlefields
- no champion → the legal champions for that legend, usually a handful

Because the legal pool is ~266 cards but the *meta* pool is ~120, and we already know 60–75
after four rounds, this is typically one screen of 20–30 cards.

---

## 5. Data model

Precomputed per legend, from the meta snapshot (cheap; no ML):

- candidate decks + existing scores
- card frequency within the legend
- clusters by main-deck Jaccard, each with core / flex split
- co-occurrence (PMI) for substitution ranking
- role buckets: card type × cost band

Session state (new tables, following the existing migration discipline):

- `wizard_sessions` — id, user_id, legend_id, phase, created/updated
- `wizard_knowledge` — session_id, card_id, state (`exact`/`at_least`), count
- `wizard_rounds` — session_id, round_no, deck_id shown, answers

**Collection write-back — decided: opt-in at the end of a session.** The knowledge gathered
*is* collection data. Marking gaps in three decks pins down ~75 cards, far faster than any
collection-entry screen, which makes the wizard the cheapest path into collection mode —
exactly the onboarding cost the two-mode design exists to avoid.

It is offered once, on finishing, and never written silently. The reason is that the two
statements differ: "I don't have this" *about one deck, right now* is not the same claim as
"I do not own this card", and a user answering quickly to get a deck should not have a
permanent fact recorded on their behalf. Session state is authoritative during the run;
the collection only changes if they say so.

---

## 6. API

```
POST   /api/smart-decks/sessions           {legendId} -> session + first proposal
GET    /api/smart-decks/sessions/{id}      current proposal, floor, progress
POST   /api/smart-decks/sessions/{id}/answer
       {deckId, have: {cardId: n}}         -> next proposal (or floor / phase 3 question)
POST   /api/smart-decks/sessions/{id}/accept  {deckId} -> copy into the deck library
POST   /api/smart-decks/sessions/{id}/save-collection   opt-in write-back
GET    /api/smart-decks/legends            legends ranked by meta strength + deck count
```

Every proposal response carries: the deck, its provenance and score, the per-card
requirement, what we already know, whether it is repaired (and what changed), the current
floor, and a plain-English reason it was chosen.

---

## 7. UI

- **Legend picker** — legends ranked by meta strength, with deck counts; the availability
  profile shades which are realistic.
- **Review screen** — the deck, one row per card: `Need 3 · You have [0][1][2][3]`,
  defaulting to "all". **This is the partial-count case and it is the default interaction,
  not an edge case.** Known cards are pre-filled and collapsed so each round only asks
  what is genuinely new.
- **Floor banner** — "Best deck you can build right now: …" or "Not yet — two more
  questions".
- **Repair disclosure** — swapped cards shown inline against the original.
- **Finish** — accept into the library (reuses the existing meta-deck import), optionally
  save answers to the collection.

---

## 8. How we will know it works

An acceptance criterion that isn't measured is a hope. A simulation harness, in the spirit
of keeping metrics that are allowed to be embarrassing:

**Synthetic players.** Generate collections at several sizes (starter-ish, a few packs,
deep) by sampling the card pool with rarity-weighted probability; also replay *real* meta
decks as collections plus noise.

**Auto-answer.** Run the wizard end to end, answering each round truthfully from the
synthetic collection.

**Headline metrics** — reported by the harness, checked in CI:

| metric | target |
|---|---|
| **solved-when-feasible** — a legal deck found whenever one exists | **100%** (Phase 3 makes it a guarantee; anything less is a bug) |
| **rounds to floor** — questions until the first buildable deck | median ≤ 3, p90 ≤ 5 |
| **quality gap** — score of the deck we found vs the best theoretically buildable | median ≤ 10% |
| **false-negative rate** — we said "can't build" when they could | **0%** |

`solved-when-feasible` is the one that maps to the acceptance criterion, and it is the one
to put on the dashboard. The reference point: v2's equivalent number was
`strictBuildableEmptyResultRate: 0.814` — it failed four times in five.

### 8.1 Measured result (steps 1-4 complete)

`python -m riftbound.domain.smart_decks_accept` runs every legend in the snapshot against
20 synthetic players and exits non-zero on failure, so it can gate a release the same way
the bundle gate does. Against `2026-08-26T0713Z`, 49 legends x 20 players = 980 sessions:

| metric | target | result |
| --- | --- | --- |
| solved when feasible | 100% | **100%** |
| false negatives | 0 | **0** |
| rounds to answer | median <=3, p90 <=5 | **median 2, p90 2** |
| quality gap | <=10% | **median 0.0%** |

The one false negative this run did surface is worth recording, because it was invisible
to the earlier sweep and it was a real defect. The closing question sized itself from
rarity priors describing an *average* collection, and the players who most need that
question are the ones furthest from average: a thin collection over a wide legal pool got
the same dozen names every round, answered "none" to all of them, and the session ran out
of rounds still holding cards it had never asked about. Two changes:

* the estimate is now **calibrated** against what the player has actually reported, so a
  pessimistic collection widens the question instead of repeating it;
* once a question has come back short, the next one asks the **whole remaining pool**.
  Saying "you cannot build this" while holding unasked names is a guess, and it is the
  one failure the acceptance criterion does not allow.

The cost is question length, and it lands where it should. For players who *can* build —
the case the criterion is about — a question is a median of 22 cards, p90 45, and the full
sweep fires only 8% of the time. The long sweeps (p90 226) are concentrated in legends the
player genuinely cannot build, where asking everything is the price of an honest no. The
UI should render those as a grid rather than a list.

---

## 9. Build order

1. **Feasibility oracle + constructor** (`domain/deck_builder.py`). Pure, testable, no I/O.
   This is the guarantee; build it first and prove it before anything else.
2. **Legend index** (`domain/legend_index.py`) — frequency, clusters, cores, PMI, roles,
   precomputed from the snapshot.
3. **Simulation harness** (`tests/`) — synthetic players, the four metrics. Built *before*
   the interactive layer so the algorithm is tuned against evidence rather than vibes.
4. **Session engine** (`domain/smart_decks.py`) — knowledge state, deck selection,
   repair, phase transitions. Pure; takes the index and knowledge, returns the next
   proposal.

   *Steps 1-4 are done and passing; see 8.1 for the measured result.*

5. **Persistence + API** — migration, repository, routes. *Done.*
6. **UI** — legend picker, review screen, floor banner, finish. *Done.*
7. **Collection write-back** — opt-in. *Done.*

### 9.1 What the UI pass caught

Driving the finished wizard in a browser against the live snapshot found a defect the
whole test suite and the 980-session acceptance run could not: the checklist round
pre-selected three copies of every card. It asked "which of these do you own" and
answered "all of them" on the player's behalf, so anyone clicking through would be told
they can build a deck they cannot.

Worth recording because of *why* it was invisible. The harness answers every question
truthfully from a known collection, so it never exercises a default. The engine was
correct; the screen in front of it lied. It is a **false positive** — the exact mirror
of the false negative the engine is built to avoid — and the two need guarding in
different places.

The rule now: a **deck** round assumes you have its cards and asks for exceptions
(the list is real, the question is "what are you short of"); a **checklist** assumes
nothing (the cards are unasked, the question is "what do you own"). Cards an earlier
round established keep what was learned. Locked in by
`test_a_checklist_does_not_answer_itself`.

Steps 1–4 are where the difficulty lives and all of them are pure functions, so they can be
driven entirely by tests and the harness. Steps 5–7 are ordinary plumbing over the existing
patterns.

---

## 9.2 The signal, scoped to the format being played

The index in step 2 was built over the whole archive, which spans a banning: a third of
those lists describe a format nobody plays. The builder filtered *banned cards* out of the
pool, so every deck it produced was legal — and a third of the evidence deciding which
legal cards to pick came from a dead format. Nothing in §8 could see it. Solved-when-
feasible stayed at 100%, rounds stayed at a median of 2, and the deck was wrong anyway.

`legend_index` is now scoped to the current era (`domain/eras.py`), and the gap it closed
is not small:

| | all-time signal | current era |
| --- | --- | --- |
| closest real current list | 0.837 | **0.879** |
| average over the field | 0.581 | **0.606** |
| legends improved / unchanged / worse | — | 16 / 28 / 3 |

Annie's proposal changed by 68%. Three legends did get slightly worse (Irelia, Jax,
Rek'Sai) and the acceptance run prints them by name rather than reporting only the mean.

Measured and rejected: an evidence threshold, keeping the all-time signal for legends
with few recent lists. It is strictly worse at every level tested — requiring 30 recent
decks drops the closest match to 0.855 and cuts the improved legends from 17 to 7. Only a
legend with *no* current-era lists falls back, and it is labelled where the player can
see it.

The metric behind all of this is new, because none existed: `domain/deck_fidelity.py`,
gated by `python -m riftbound.domain.deck_fidelity_accept`. It measures conformity to the
field, not strength, so it is a regression guard and must never be optimised against —
a builder that copied the most-played list every time would score near 1.0 and help
nobody.

## 9.3 The archetype steer, removed

§4.3 and §5 describe building *within a cluster* — picking the strongest family a
collection can field and promoting its cards. That mechanism is gone, and the reason is
worth keeping because the instinct to add it back is a good one.

It never acted. The boost multiplied `play_rate`, and `COHERENCE_WEIGHT = 0.9` leaves
`play_rate` carrying 10% of a pick — measured, never enough to flip a decision. Flat and
cluster-aware builds produced identical decks at every collection depth.

Then fixing it turned out to be worse than leaving it. Judged by `deck_fidelity`:

| mechanism | closest real list |
| --- | --- |
| no archetype steer | **0.888** |
| the shipped boost | 0.879 |
| family used as the candidate pool | 0.884 |
| coherence routed through the pairing term, ×1 / ×3 / ×10 / ×30 | 0.880 / 0.877 / 0.866 / 0.864 |

Monotonic in the wrong direction — the harder the archetype is pushed, the less the deck
resembles what people play. And the harm lands precisely where the old comment claimed
protection: legends with fewer than 20 published lists scored 0.777 with the steer against
0.806 without it.

The reading is that greedy Jaccard families are not sharp enough to steer a build, and
that the pairing signal already carries archetype coherence better than a cluster label
does — a card that belongs to the plan is a card the field plays alongside the plan.
Clusters keep their place in **selection** (which deck to show, which swap to offer, and
`coverage` for "can they field this deck's own family"); they have no place in
**construction**.

## 10. Decisions taken

| question | decision | why |
|---|---|---|
| repair aggressiveness | ~~offer both, labelled~~ → **the app chooses, and labels what it chose** | superseded. The original reasoning stands — they *are* different products — but it does not follow that the player should arbitrate. See §9.4 |
| collection write-back | opt-in on finish | answering about one deck is not a permanent claim about the collection |

## 9.4 Two scores, and the wizard making the choice

Every deck the wizard shows now carries two numbers, and the wizard picks between the
repairs itself rather than asking.

**The scores.** `meta_scoring.score_deck` reads a deck's *pedigree* — evidence tier,
placement, recency — which a repaired deck does not have: the moment a card is swapped it
stops being the list that placed 3rd of 257. So a deck is scored by **what real list it
resembles, discounted by how much of that list it contains**:

    affinity(deck) = max over published R of [ meta_score(R) × coverage(deck, R) ]

- **meta score** — that affinity over the whole format, against the format's best;
- **champion score** — over the published lists for that champion, against the best of
  those, so the strongest list for a champion is 100 by construction.

Coverage is bounded by 1, which is the load-bearing property: **a repair can never
out-score the list it repaired.** If substituting a card you own for one you lack made
the deck stronger, the published list would have played your card.

The first attempt got this backwards and shipped, briefly. It scored a deck by summing
the format-wide play rate of its cards, so swapping any card for a more-played one always
raised the number — which is exactly what a repair does. Every repair scored at or above
its source, and the wizard reported a compromise as an improvement: a seven-card
substitution came back as *"100 for this champion"*. A second fault compounded it — the
denominator was the best play-rate mass among that champion's decks, which for a champion
with one published list was a bar any repair cleared instantly. Measuring against real
forty-card lists fixes both: a champion with one deck is scored against that deck, and
only an exact copy reaches 100.

A champion with no published lists is *unscored*, never zero.

**The choice.** The wizard used to render the conservative and the free repair side by
side with a button under each. That asked a player to arbitrate between two lists they had
never seen played, in the middle of telling us what they own — while the app was the one
holding the numbers to decide it. It now picks, on the **champion** score: a repair
competes with other ways of building the same deck, never with the format, and measuring
it against the format's best would let a swap that is clearly right for a fringe champion
lose on a denominator neither deck can influence.

What survives from §10's original reasoning is the disclosure. The two really are
different products — one is the tournament deck adapted, the other a legal deck in the
same colours — so the chosen deck still says which it is, along with how far it drifted
and what changed. Choosing for someone is not the same as not telling them what they are
holding.

## 11. Risks and open questions

- **Meta coverage per legend is uneven.** Median 34 decks, but the tail has legends with 2.
  For those, Phase 1 has almost nothing to propose and the wizard is effectively pure
  construction. That path must be good, not an afterthought — it is also what happens for
  any brand-new legend.
- **The `at_least` inference assumes honest, careful answers.** A user who skims and leaves
  a card unmarked teaches us they own 3 of it. Mitigation: a cheap confirmation on the
  binding cards before declaring a floor, and let any later answer overwrite an earlier
  inference.
- **Repaired decks can drift.** Bounded by a cap on swapped copies before we stop calling
  it the same deck, and always disclosed.
- ~~The rules profile is stale~~ — **resolved.** `sideboard_max` is now 10 with an
  advisory at 8, so the constructor can build what the field plays without producing decks
  the app then calls illegal. Meta-deck legality went 53% → 73%.
