from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from run import load_dotenv_defaults

from app.core.config import load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed meta deck index rows from a JSON file into the Postgres database."
    )
    parser.add_argument(
        "--source",
        default="",
        help="Path to meta-deck-index.json. Defaults to the path resolved by RB_META_INDEX_PATH / config.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate rows without writing to the database.",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv_defaults(ROOT / ".env")
    args = parse_args()
    config = load_config()

    if config.storage_backend != "postgres":
        print(f"Storage backend is '{config.storage_backend}' — seed only targets postgres. Set RB_DATABASE_URL and RB_STORAGE_BACKEND=postgres.")
        return 1

    from app.infra.postgres_storage import PostgresStorage

    source_path = Path(args.source).resolve() if args.source else config.meta_index_path
    if not source_path.is_file():
        # Also try workspace root
        alt = ROOT.parent / "artifacts" / "meta-deck-index.json"
        if alt.is_file():
            source_path = alt
        else:
            print(f"Source file not found: {source_path}")
            return 1

    print(f"Loading rows from: {source_path}")
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        print("Expected a JSON array at the top level.")
        return 1

    rows = [row for row in raw if isinstance(row, dict)]
    print(f"Found {len(rows)} rows.")

    if args.dry_run:
        print("Dry run — skipping database write.")
        return 0

    storage = PostgresStorage(config.database_url)
    storage.init_schema()

    count = storage.upsert_meta_deck_rows(rows)
    print(f"Upserted {count} rows into meta_deck_index.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
