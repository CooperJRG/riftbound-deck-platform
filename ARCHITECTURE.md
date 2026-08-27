# Architecture

Every decision here answers something that went wrong in the previous version. The
findings are in `AUTOPSY.md` in the old repo; the short version is below, alongside what
replaced it.

---

## 1. Card identity: two levels, never a name

| | |
|---|---|
| **Was** | Decks stored as `{"Honest Broker": 3}` — display titles. Collections keyed on a normalised title. A card renamed upstream silently orphaned itself out of every saved deck. |
| **Now** | `card_id` (gameplay: `caitlyn-patrolling`) and `print_id` (one printing: `ogn-068a-caitlyn-patrolling`). Decks reference `card_id`; collections reference `print_id`. |

The upstream data is not internally consistent about names: the same card ships as both
`"Blitzcrank - Impassive"` and `"Blitzcrank, Impassive"` depending on the printing.
`card_id` is punctuation-insensitive, so both resolve to one card. Across the real
935-printing export this produces 769 gameplay cards with **zero** genuine collisions.

`Catalog.resolve()` exists for import boundaries only — accepting a name from a user or a
decklist — and never for storage.

## 2. Availability: one function, two ways to fill it

| | |
|---|---|
| **Was** | The collection was a hard constraint inside the deck generator. Its own evaluation recorded `strictBuildableEmptyResultRate: 0.814` — asked for a deck from your collection, it returned nothing four times in five. |
| **Now** | `AvailabilityProfile.resolve(card) -> Availability(weight, max_copies, …)`. |

Collection mode and exclusion mode differ only in how the profile is *populated*.
Everything downstream — card listings, deck coverage, and any future generator — consumes
the resolved function and has no idea which mode is active.

Both are **soft by default**: an unavailable card gets `weight = 0.15`, not removal, so
there is always a legal deck to return. `strict=True` is the opt-in hard version.

Exclusion mode also **self-heals across releases**. A new set is available by default, so
it can never invalidate your setup — where a recorded collection goes stale on release day.

## 3. Data as a subsystem, not a script

| | |
|---|---|
| **Was** | Scrapers lived *outside* the repository; three `scripts/` files were 20-line stubs that `runpy`'d files a clone doesn't have. 2,268 raw scraped files were committed. A refresh overwrote the live card file, so a scraper returning an error page silently became the truth. |
| **Now** | `data/` is a pipeline inside the package: **sources → normalise → gate → bundle → promote**. |

- **Sources** (`data/sources/`) are independent adapters that never raise. One site
  changing its markup shows up as *that source* unhealthy in the bundle manifest. The
  primary source is the dotgg card API (`data/sources/dotgg.py`), stdlib-only so the
  base install stays tiny; `json_export.py` reads a local file for offline builds.
- **No list of known sets gates ingestion.** Set codes are derived from the data, so a
  release that postdates the code flows through untouched. This was a real bug: the
  first cut of `set_code_for` checked the slug prefix against an allowlist, which would
  have silently blanked Vendetta's and Secret Garden's set codes even with the data in
  hand. `KNOWN_SET_ORDER` now affects only merge *ordering*, and
  `test_a_set_released_tomorrow_needs_no_code_change` guards the distinction.
- **Normalisation** (`data/normalize.py`) holds every piece of knowledge about how
  upstream data is broken, in one testable place. It merges reprints field by field
  rather than picking a "representative" row — which on the real data recovers ability
  symbols on 61 cards and field values that exist on only one printing.
- **The gate** (`data/gate.py`) is the control that was missing. A bundle that loses more
  than 2% of the previous bundle's cards is **rejected**. Card games add cards; a sudden
  drop means the source broke.
- **Retention** (`check_archive_retention`) is the same control for the meta archive, and
  it exists because its absence cost real data. The meta gate runs *before* carry-forward
  by design — so it only ever sees the fresh harvest, which legitimately covers a shorter
  window — which left nothing watching whether the snapshot about to be promoted holds
  less than the one already live. A refresh that could not reach one deck source carried
  its decks forward and dropped its standings: 4,359 decks either side, so nothing
  watching deck counts saw anything, while 13% of the standings and 2,530 match records
  disappeared and the win-rate gate went red. Each population is now counted separately,
  after the merge, and a shrinking archive is refused rather than promoted.
- **Bundles** are immutable, dated, and content-hashed. Promotion is a separate,
  deliberate step. Rolling back is repointing `current`.

Unknown cards degrade rather than crash: `validate()` reports a card the bundle doesn't
know as a *warning* and leaves the deck untouched, so a data refresh can never destroy a
saved list.

## 4. Nothing above the project root

`config.py` derives every path from one `ROOT` and rejects any configured path that
escapes it. v2 resolved its data paths to the repository's *parent* — which on the
author's machine was a different project — so the model committed to git was not the
model that ran, and a fresh clone was not a runnable system.

Missing required data is a startup error naming the file and the command that produces it,
never an empty screen.

## 5. Mode is declared; mode never weakens auth

v2 inferred "offline mode" from the absence of Supabase environment variables, and in that
mode its token check ignored the `Authorization` header entirely and granted callers
admin. A missing *configuration* silently became an *authorization* downgrade.

Here `RB_MODE` is explicit. `local` has no login and therefore **refuses to bind anything
but loopback**. Authentication is a port (`api/identity.py`) with one implementation per
mode; the hosted one fails closed rather than falling through to permissive.

`user_id` is in the schema from the first migration, so hosting later is a configuration
change rather than a data migration.

## 6. Real migrations

Numbered SQL files applied in order inside a transaction and recorded in
`schema_migrations`. v2 incremented a version number and ran nothing, which is how it
ended up with two parallel data models in one database, both being written.

Migrations execute statement at a time rather than via `executescript`, because
`executescript` issues an implicit `COMMIT` that would leave a half-applied migration
recorded as complete.

## 7. Tests that cannot be taken hostage

v2's API fixture called `train_auto_builder_artifacts(...)` — it trained a model before
every test — so one numerical bug in the ML pipeline failed sixteen tests covering auth,
deck visibility and collection import.

Here the fixtures are a hand-built twenty-card catalogue and a temporary SQLite file. The
whole suite runs in ~2 seconds and imports no heavy library. Warnings are errors
(`filterwarnings` in `pyproject.toml`), so dependency drift surfaces immediately instead
of accumulating.

## 8. Optional is optional at import time

v2's service container imported the auto-builder at module scope, which did a bare
`import torch`, so the documented install — which deliberately excluded torch — produced
an app that could not start.

The base dependency set here is `fastapi`, `uvicorn`, `pydantic`. That is genuinely
sufficient to browse cards, build decks and check legality. Anything heavier that arrives
later loads lazily behind an accessor, and its absence must be reportable, not fatal.

## 9. Frontend: modules, and escaping by construction

v2 was one 10,675-line IIFE with a 1,083-line `bindEvents()`, rendering through 67
`innerHTML` sites guarded by hand-rolled escape helpers.

Here the UI is TypeScript in feature modules under `web/src/`, and every DOM write goes
through `h()` in `ui/dom.ts`, which sets `textContent` and never parses markup — escaping
is structural rather than remembered. Strict compiler settings are on, including
`noUncheckedIndexedAccess` and `exactOptionalPropertyTypes`.

Views are pure renderers driven by a subscribe/notify store. The two inputs that must
survive re-render (card search, deck name) are built once and kept, since re-creating a
focused `<input>` on each keystroke blurs it.

## 10. A statistic before a model, and an era before a statistic

| | |
|---|---|
| **Was** | v2 answered "what should I play" with a 16-expert mixture-of-experts whose own evaluation put its synergy clusters at a silhouette of 0.026 and its headline promise at an 81% failure rate. It could not explain a single recommendation. |
| **Now** | The same question is answered by a win rate the player can check by hand, over match records that were already in the database. |

Every TopDeck standing carries `wins`/`losses`/`draws` as integers. `meta_normalize` was
formatting them into a `"3-0"` display string, `meta_snapshot` was persisting it, and no
module ever read it back — 20,783 matches, 82.8% of the corpus, behind a display field.
`Standing` now types them and keeps `record` as the rendering, with `match_record`
falling back to parsing the string so an already-promoted snapshot needs no re-harvest.

Three rules came out of building on it, and they are the ones a later change is most
likely to break:

**Presence is never blended with performance.** The tier score is still
`share x 0.58 + events x 0.27 + movement x 0.15`, untouched. The two orderings agree only
moderately (Kendall tau +0.587), and the disagreement is the useful part: the most-played
archetype in the format is the eighth-best performing, and the second-best performing sits
in B tier on presence alone. Averaging them destroys exactly what the column adds. Win
rate is a **reported column, never a scoring term** — `placement_score` already spends 25%
of a deck's score on the same underlying fact, so folding it in would double-count too.

**A statistic declares its era.** The archive spans a banning, and 26.4% of it is illegal
today. `data/rules/constructed.json` gained an `eras` block beside the ban list it belongs
to — rules-as-data again. The boundary is a step function with zero exceptions across
4,218 lists (last banned-card deck 2026-03-28, first clean list 2026-03-29), so it is a
constant, not an inference. It is also *derived rather than cited*: `Era.is_cited` reports
that, and the UI prints it, until an announcement URL replaces the evidence string. A
derived date must not be allowed to pass as a cited one by being quietly forgotten.

**A threshold is set from a measurement, not from taste — and the estimator gets measured
too.** The publishing floor (200 decisive matches, 8 events) comes from a split-half sweep,
which turned up something counter-intuitive: rank agreement *peaks* at 200 and collapses
above 300, because too few survivors are too tightly bunched to order. A higher bar is not
automatically a safer number. The acceptance gate's own first cut then failed on its own
random seed — passing at +0.522 and failing at +0.498 depending on the seed — because 40
resamples could not resolve the margin it was judging. Both halves were fixed: 400 trials
for reproducibility, and a threshold with real margin under the measurement.

`python -m riftbound.domain.meta_performance_accept` gates it, exits non-zero, and is
imported by nothing in `tests/`. Its kill switch is signal-to-noise: observed variance
between archetypes over the variance binomial sampling alone would produce. At 1.0 the
ranking is a ranking of coin flips; it currently reads 4.39x. That is the check
`strictBuildableEmptyResultRate` never had.

The full reasoning, including the alternatives that were measured and rejected, is in
`docs/deck-performance-plan.md`.

**A statistic declares its era — and so does the builder.** The win rate was scoped
first; the signal the *builder* fills from was not, and for a while `legend_index`
averaged two formats and handed the player the average. It was a defect with no symptom:
every Smart Decks target stayed green, the decks stayed legal, and they were simply built
from evidence for a format that ended in March. Scoping the index moved the closest-match
score against real current lists from 0.837 to 0.879, and changed the deck for 43-54% of
collections — Annie's proposal is now 68% different, dropping eight cards nobody plays any
more for eight the field actually runs.

Two things fell out of building it. There is **no evidence threshold**: the obvious design
keeps the all-time signal for legends with few recent lists, and measured, that is
strictly worse — requiring 10 recent decks drops the score to 0.875 and requiring 30 drops
it to 0.855. Eight current lists describe the current format better than thirty-seven
pre-ban ones. The only fallback is a legend with *nothing* in the era, and that profile is
tagged `era_id="all"` and surfaced on the API rather than passing as current.

And it needed a metric that did not exist. `smart_decks_harness` measures whether a deck
can be *found*, never whether it is the right one, which is exactly why this went
unnoticed. `deck_fidelity` compares built decks against the real lists of the era being
claimed, and `deck_fidelity_accept` gates both the level and the direction — widen the
index back to the archive and the run goes red with the reason attached.

**A ranking is policy, so it lives on the server too.** The tier wall's ordering was the
last piece of ranking logic in the client, and the only one with no tests: weights, tier
cut points and all, in `explore.ts`. It now sits in `domain/meta_trends/ranking.py` with
its own suite, and it emits a 0-100 rating rather than an internal sort key nobody could
see. Two behaviours came out of moving it. A legend the selected range cannot see is no
longer dropped into an unordered "uncharted" heap: it is rated 0 and ranked against the
other dormant ones on what the archive still knows, so narrowing the range reorders the
wall instead of emptying part of it. And the numbers a card shows now reconcile — the
three components sum to the total, which is asserted, because a card that explains itself
must not be able to explain itself wrongly.

---

## What isn't built yet

Deliberately out of scope for this milestone, with the seams already in place:

- **More card sources.** dotgg and a local-file adapter exist; Piltover Archive and
  riftbound.gg slot in beside them for cross-checking. Cross-source disagreement is not
  yet reconciled — today a single source is authoritative.
- **Scheduled refresh.** Ingest is a manual command. It should run on a timer, with the
  gate deciding whether the result gets promoted.
- **Ban-list automation.** Drift between the source's ban flags and the rules profiles
  is reported, not applied. Legality stays a deliberate human edit.
- **Meta deck tracking.** Ingesting decklists needs the same bundle-and-gate treatment,
  plus a name→`card_id` resolver that *reports* what it could not resolve rather than
  dropping it silently as v2 did.
- **Collection entry.** The schema and repository exist; the UI for it does not. When it
  arrives it should offer bulk paths (set-based, "I own the starter deck") rather than
  per-card entry.
- **Deck suggestions.** When this happens, buildability is a constraint-solving problem
  over the availability function, scored by a simple learned card-affinity signal — not a
  16-expert mixture-of-experts over 2,000 decks. Keep the evaluation harness; make
  `strictBuildableEmptyResultRate` the headline metric from day one.
- **Matchup win rates.** Not "not yet" — **not possible**. No source records who anyone
  played, so head-to-head numbers cannot be derived, and no model manufactures them. A
  latent-strength fit was measured and rejected: strength of schedule spans 2.04 points
  against win rates spanning 28.5, so its correction is smaller than the noise floor.
- **Hosted multi-user.** `user_id` is threaded through; `HostedIdentityProvider` needs a
  real token verifier.
