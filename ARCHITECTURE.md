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
- **Hosted multi-user.** `user_id` is threaded through; `HostedIdentityProvider` needs a
  real token verifier.
