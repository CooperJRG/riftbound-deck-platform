# Riftbound Deck Platform v2

Ground-up rebuild focused on deck building and analysis only.

## Product Scope

This project intentionally excludes all gameplay simulation and match execution logic.

Primary capability set:
- Build and edit decks with rule validation.
- Manage card collections with persistent storage.
- Track `Built Decks` separately from `Saved Decks`; built lists reserve collection copies.
- Browse/import meta decks from local artifacts.
- Analyze deck completeness, missing cards, and shopping lists.

## Stack

- Backend: FastAPI + standard-library SQLite (`sqlite3`)
- Frontend: Single-page vanilla JS + skeuomorphic 90s/2000s CSS
- Data inputs:
  - `../riftbound-cards.json`
  - `../artifacts/meta-deck-index.json`
  - `../rules/*.txt` (source of truth references)

## Architecture

`app/domain/`: pure deck domain logic (rules loading, validation, analysis)  
`app/infra/`: adapters (card catalog loader, meta index loader, SQLite persistence)  
`app/api/`: HTTP routes only  
`web/`: SPA client

## Run

```bash
cd riftbound-deck-platform-v2
pip install -r requirements.txt
python run.py
```

Default URL: `http://127.0.0.1:8010`

## Hourly Meta Index Auto-Refresh

The API can run the full ingest + metascore rebuild pipeline in the background every hour.

PowerShell example:

```powershell
cd riftbound-deck-platform-v2
$env:RB_META_AUTO_REFRESH_ENABLED = "1"
$env:RB_META_AUTO_REFRESH_RUN_ON_STARTUP = "1"
$env:RB_META_AUTO_REFRESH_INTERVAL_SEC = "3600"
$env:RB_META_AUTO_REFRESH_TIMEOUT_SEC = "1800"
$env:RB_META_REFRESH_EXTRA_ARGS = "--price-weight 1.35 --piltover-pages 100 --riftboundgg-pages 40 --riot-bologna-weight 1.1"
python run.py
```

What this does:
- Runs `../scripts/refresh_meta_deck_index.py` on the configured interval.
- Pulls fresh deck sources and base-card prices.
- Imports Riot Bologna article decklists as a unique browse source (`source=riot-bologna`).
- Recomputes metascores (including price contribution) and writes updated artifacts.
- Reloads the in-memory API meta index immediately after each successful run.

Optional overrides:
- `RB_META_REFRESH_SCRIPT_PATH`
- `RB_META_INDEX_PATH`
- `RB_META_INDEX_CSV_PATH`
- `RB_BASE_CARD_PRICES_JSON_PATH`
- `RB_BASE_CARD_PRICES_CSV_PATH`
- `RB_DECK_SOURCES_CACHE_DIR`

Note: run a single API process for this mode, otherwise each process will run its own hourly job.

## Tests

```bash
cd riftbound-deck-platform-v2
python -m pytest -q
```

## Auto Builder Benchmark

Benchmark the current auto-builder artifact against a freshly trained artifact:

```bash
cd riftbound-deck-platform-v2
python scripts/benchmark_auto_builder.py --epochs 1 --torch-device cpu
```

This prints JSON with:
- baseline vs newly trained selected win-condition and synergy counts
- strict-buildable hit-rate and empty-result deltas
- recommendation latency for both artifacts
- fresh training wall-clock time

For repeated retrains on a stable corpus, the trainer can reuse previously discovered resolution counts instead of re-running the full NMF and spectral search:

```bash
cd riftbound-deck-platform-v2
python scripts/train_auto_builder.py --torch-device cuda --resolution-mode auto
```

`--resolution-mode auto` reuses the existing artifact's selected counts when the training corpus fingerprint matches. Use `--resolution-mode search` to force a full re-selection pass, or `--reference-artifact <dir>` to reuse counts from a different artifact bundle.

## Notes

- Rule constants are loaded from `rules_profiles/constructed.json` (not hardcoded in validator logic).
- Additional formats can be added by creating new profile files and wiring format selection.
- Current meta browsing is local-artifact driven. Live ingest pipeline can be added as a separate bounded context.

## UI Assets

- Source images are kept in `images/`.
- Normalized UI-ready assets are generated into `web/assets/skeuo/`.
- Regenerate and validate dimensions with:

```bash
cd riftbound-deck-platform-v2
python scripts/prepare_skeuo_assets.py
```
