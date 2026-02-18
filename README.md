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

## Tests

```bash
cd riftbound-deck-platform-v2
python -m pytest -q
```

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
