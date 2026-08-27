# Deck performance — plan

What is actually winning, as opposed to what is being played. A win rate on every
archetype the evidence can support one for, an explicit refusal on the rest, and no
learned model anywhere in it.

---

## 1. Why this, and why not a model

The question behind this feature was open: *is there a user-facing problem here that
genuinely needs a learned model, or would a legible statistic do the same job better?*
Four candidates were measured against the live snapshot before anything was built. Two
did not survive contact.

| claim | verdict |
| --- | --- |
| "No matchup or win-rate data exists anywhere in the corpus" | **false** — 20,783 matches were already in the database, unread |
| "Generated decks are more scattered than human ones" | **false against a full pool** — 17 distinct cards / 2 one-ofs vs a real-list 18 / 4 |
| "~46% of a built deck pairs below chance" | **true for thin and mid collections, false for deep ones** |
| "The archive spans a ban with no notion of era" | **true**, and it is a constant, not an inference |

The decisive measurement is the first. Every TopDeck standing carries the player's
`wins`/`losses`/`draws` as integers. `meta_normalize` was formatting them into a `"3-0"`
string, `meta_snapshot` was persisting it, and **no module in the codebase ever read it
back**. 3,491 of those standings join to a published list — 82.8% of the corpus.

So the ceiling the brief assumed could not be lifted was never a ceiling. It was a field
nobody had opened.

### 1.1 Why not Bradley-Terry

The obvious ML-shaped follow-up: a raw win rate is confounded by strength of schedule, so
fit latent archetype strengths instead. Measured, the confound is nearly absent.

| | |
| --- | --- |
| spread of mean opponent quality across qualifying archetypes | **2.04 points** |
| spread of the win rates themselves | **28.5 points** |
| largest possible schedule correction | **±1 point** |
| split-half noise floor at the shipping threshold | 3.8 points |

The correction is smaller than the noise. And it is not identifiable in any case: no row
carries an opponent, so 2,281 deck-event observations would be used to estimate 92
archetype strengths from marginals alone — and the marginals *are* the win rate. Such a
fit reconstructs its own input, adds a training step, a serialised artifact and a
version-skew failure mode, and moves no number by more than rounding.

This is the v2 pattern exactly: a sophisticated architecture whose own evaluation shows
it is indistinguishable from the simple thing. `AUTOPSY.md` §2.9.

**What is genuinely unavailable**: the opponent. Matchup tables are out of scope
permanently unless a source begins publishing pairings, and no model manufactures them.

---

## 2. What it has to do

1. Give each archetype, legend and champion a win rate where the sample supports one.
2. **Refuse** where it does not, and say which threshold was missed.
3. Scope every rate to a declared banned-list era, because a rate averaged across a ban
   describes a format nobody plays.
4. Never let the rate become a ranking term. Presence and performance stay two numbers.
5. Carry the selection bias in the response, not in a footnote.

Point 4 is the one most likely to erode. It is stated again in §5.

---

## 3. Eras

`data/rules/constructed.json` gains an `eras` block beside the ban list it belongs to —
rules-as-data, the best idea carried forward from v2.

The boundary is a step function with no ambiguity at all. Across 4,218 published lists:

```
month      2025-11  2026-01  2026-02  2026-03  2026-04  2026-05  2026-07  2026-08
banned %     62.5     86.5     84.6     82.4      0.0      0.0      0.0      0.0
```

Last deck playing a now-banned card: **2026-03-28**. First clean list: **2026-03-29**.
Exceptions on either side: **zero**. Change-point detection would return that date and
charge a dependency for it.

The contamination it fixes is not small. Built over the whole archive, 12 of 49 legends
carry a banned card inside their top-25 play rates and 85 of 1,040 archetype clusters
have one in the *core* that defines them — a family the builder can never assemble.

**On citations.** Every other constraint in that profile points at a rulebook section.
This one cannot yet: the date was derived from the corpus, not read off an announcement.
So each period carries an `evidence` string saying exactly how it was established and an
empty `source` waiting for the real one, `Era.is_cited` reports which it is, and the UI
prints "derived from the archive rather than a published announcement" until it changes.
A derived date must not be allowed to pass as a cited one by being quietly forgotten.

---

## 4. Thresholds, and how they were chosen

Split-half resampling decides everything here: rank the archetypes on a random half of
the events, again on the other half, and compare. 400 resamples per floor, six seeds.

```
floor      100     150     200     250     300     400     500
tau     +0.460  +0.522  +0.534  +0.523  +0.499  +0.378  +0.306
error    4.40%   3.94%   3.76%   3.60%   3.46%   3.18%   2.92%
shown       25      19      18      17      14       9       7
```

Per-rate precision improves monotonically with the floor. Rank agreement **does not**:
it peaks at 200 and collapses above 300, because the survivors become too few and too
tightly bunched for an ordering to mean anything. At a 500-match floor, seven archetypes
remain and τ falls below its value at 100. *A higher bar is not automatically a safer
number* — that was the surprise in the sweep and it is the reason the constant is 200
rather than "as high as we can stand".

Shipped: **200 decisive matches, 8 distinct events, no pilot above 20% of the matches.**
Eighteen of ninety-two archetypes clear it. That is the honest size of this feature and
it is reported in the API response rather than left to be inferred from a short list.

---

## 5. Architecture

```
domain/eras.py                        Era, Eras — windows of stable rules
domain/meta_trends/performance.py     the aggregation, Wilson, refusal, basis
domain/meta_performance_harness.py    the acceptance metrics
domain/meta_performance_accept.py     the gate: python -m …, exits non-zero
```

`Standing` gains typed `wins`/`losses`/`draws`. `record` stays as the display form, and
`Standing.match_record` prefers the integers and falls back to parsing the string — so a
snapshot promoted before this change keeps its records **without a re-harvest**.

`EntityTrend` gains `performance`, `TrendOverview` gains `performance_basis`. Both
default to `None`, so every existing caller keeps working and gets "not measured" rather
than a zero.

### 5.1 Presence is not blended with performance

The tier score stays `share × 0.58 + events × 0.27 + movement × 0.15`. It was
deliberately left alone.

The two orderings agree only moderately — Kendall τ of +0.587 — and where they disagree
they disagree usefully:

| | presence | win rate |
| --- | --- | --- |
| Master Yi | **#1** (10.9% of the field) | #8, 55.2% over 1,392 matches |
| Viktor | #14 | **#2**, 61.9% over 333 matches, 30 events, 49 pilots |
| Rengar | #13 (legend view) | **#3**, 61.1% |

Averaging those into one number would destroy exactly the information that makes the
column worth adding. The most-played deck in the format is not the best one, and a player
deserves to be able to see that.

---

## 6. The honest case against

**Publication bias is real and is not constant.** Standings whose list was published win
50.7% of their matches; those without win 46.3%. Per event the median gap is +18 points,
because at large events the unpublished population is mostly players who dropped — one
event shows that cohort at a 0.0% win rate. Median list coverage is 16.3%, and 51 of 108
events publish nothing.

What this permits: comparisons *between* archetypes inside the published population,
whose own baseline is 50.7% — near-exactly even. What it forbids: calling the figure a
win rate "in the field". `PerformanceBasis` carries both populations' rates so the client
shows the gap rather than being asked to trust a sentence.

**Placement and record are the same underlying fact.** `meta_scoring.placement_score`
already spends 25% of a deck's score on its finish. Folding win rate into `score_deck`
would double-count and silently re-weight every ranking in the app.

**Most of the field cannot be ranked.** 74 of 92 archetypes fall short. The response says
so explicitly and the UI renders their match count instead, so a reader watches the
sample fill rather than meeting a blank.

---

## 7. How we know it works

`python -m riftbound.domain.meta_performance_accept` — a command, never a fixture,
exiting non-zero so it can gate a release the way the bundle gate and the Smart Decks run
already do.

| metric | target | measured |
| --- | --- | --- |
| split-half τ | ≥ +0.45 | **+0.534** |
| split-half error | ≤ 5% | **3.76%** |
| signal-to-noise | ≥ 2.0× | **4.39×** |
| max single-pilot share | ≤ 20% | **10.2%** |
| publication gap | reported, not bounded | **+4.9%** |
| archetypes withheld | reported | **74 of 92** |

**Signal-to-noise is the kill switch.** It divides the observed variance between
archetypes by the variance binomial sampling alone would produce at these sample sizes.
At 1.0 the ranking is a ranking of coin flips. Today 77% of the spread is genuine. If a
future snapshot drops it below 2×, the gate fails and the column should withhold itself
rather than print an ordering of noise — the check `strictBuildableEmptyResultRate` was
never given.

### 7.1 The gate that flipped on its own seed

Worth recording, because it was the same class of mistake this project exists to avoid.

The first cut targeted τ ≥ 0.50 against a measurement of ~0.51, using 40 resamples. It
passed on seed 1 (+0.522), failed on seed 7 (+0.498), failed on seed 42 (+0.499), passed
on seed 99. A gate that flips on its own random seed is worse than no gate: it teaches
whoever hits it to re-run until it goes green, and after that nobody reads it.

The estimator was too noisy to judge the margin it was being asked to judge. Spread of
the mean across twelve seeds: 0.045 at 40 trials, 0.032 at 100, 0.025 at 200, **0.016 at
400**. Both halves were fixed — 400 resamples so the number is reproducible, and a
threshold with genuine margin under the measurement. It now returns +0.521 to +0.537
across every seed tried.

The lesson generalises: *a threshold set at the measured value is a coin flip, not a
gate.* Measure the estimator's own spread before choosing where the line goes.

---

## 8. Cost

- **Latency** — 6 ms to aggregate the full corpus; 15–30 ms for a warm trend request.
- **Dependencies** — none. Wilson is four lines of `math`. The base install is still
  `fastapi`, `uvicorn`, `pydantic`.
- **Test suite** — 490 tests in 7.80 s before, **526 in 8.8 s** after. The new code is
  pure functions over frozen dataclasses, tested on the existing twenty-card fixture
  catalogue. The acceptance run is a separate command and is imported by nothing in
  `tests/`. That is the v2 rule that mattered most: no test computes an expensive
  artifact.
- **Surface** — one field group on `EntityTrend`, one aggregation module, one era block
  in an existing data file, one chip and one caveat line in the UI. No new storage, no
  migration.

---

## 9. Rejected alternatives, ranked

**1 — Local-search repair of the greedy deck fill.** *Not rejected on merit; rejected on
ordering.* A plain 4,000-step hill climb over the pairwise affinity already exposed by
`LegendProfile.pair_strength` moves orphan share from 45.0% to 32.2% on mid-depth
collections at no cost in meta mass (17.26 → 16.51), and every swap it makes is
explainable as "played together 2.3× more often". It only helps the middle — on thin
collections it recovers 2.8 points because the pool genuinely runs out, and on full
collections there is nothing to fix — and it improves a deck the player was already going
to get, where this feature tells them something the product cannot currently say at all.
**Build it next.** Still no model.

> **One defect to fix regardless of ordering.** `CLUSTER_BOOST = 2.5` is inert. Building
> every legend with `preference(cluster)` against `preference(None)` produces identical
> decks — 55.7% vs 55.5% orphan share, same distinct count, same meta mass. The boost
> multiplies `play_rate`, but `COHERENCE_WEIGHT = 0.9` leaves `play_rate` carrying only
> 10% of the pick score, so a 2.5× boost on a 0.1-weighted term changes nothing. The
> archetype-coherence machinery the engine's docstring describes is not running.

**2 — A learned deck-completion model.** No headroom at either end. Against a full pool
the existing builder already matches real lists on distinct cards, one-ofs, curve at
every cost band and orphan share (16.9% vs 17.1%). On thin collections an exhaustive
local search — strictly stronger than any ranking model given the same pool — recovers
only 2.8 points. The band where improvement exists is the middle, and a deterministic
hill climb captures it.

**3 — Learned format-era detection.** See §3. It is a date.

---

## 10. Open questions

- **The era boundary is derived, not cited.** Replace `source` with the official ban
  announcement when one is to hand, and correct the date if it disagrees. Until then the
  UI says so on the page.
- **Champion- and legend-dimension rates are computed but only the legend view renders
  them.** The archetype dossier should carry the same chip.
- **Per-era play rates are not yet wired into `legend_index`.** The win rate is
  era-scoped; the *preference signal the builder fills from* is still computed over the
  whole archive, which is where the banned-core clusters in §3 live. That is the next
  place the era block earns its keep, and it is a bigger behavioural change than this
  feature — it moves what the builder builds, not just what a page reports.
