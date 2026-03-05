from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import load_config
from app.domain.normalization import normalize_card_key
from app.infra.storage import SqliteStorage


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_target_storage(target_database_url: str = "", target_sqlite_path: str = ""):
    if target_database_url:
        from app.infra.postgres_storage import PostgresStorage

        storage = PostgresStorage(target_database_url)
        storage.init_schema()
        return storage, "postgres"
    if target_sqlite_path:
        storage = SqliteStorage(Path(target_sqlite_path))
        storage.init_schema()
        return storage, "sqlite"
    config = load_config()
    if config.storage_backend == "postgres":
        from app.infra.postgres_storage import PostgresStorage

        storage = PostgresStorage(config.database_url)
        storage.init_schema()
        return storage, "postgres"
    storage = SqliteStorage(config.db_path)
    storage.init_schema()
    return storage, "sqlite"


def open_source_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def source_collection_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    if not table_exists(conn, "collection_cards"):
        return []
    return conn.execute(
        """
        SELECT card_title, quantity
        FROM collection_cards
        WHERE quantity > 0
        ORDER BY card_title COLLATE NOCASE
        """
    ).fetchall()


def source_deck_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    if not table_exists(conn, "deck_library"):
        return []
    return conn.execute(
        """
        SELECT id, name, source, format, COALESCE(bucket, 'saved') AS bucket,
               payload_json, created_at, updated_at
        FROM deck_library
        ORDER BY updated_at DESC
        """
    ).fetchall()


def target_admin_profile(storage, *, admin_email: str = "", admin_user_id: str = ""):
    if admin_user_id:
        profile = storage.get_profile(user_id=admin_user_id)
        if profile is not None:
            return profile
    if admin_email:
        profile = storage.get_profile_by_email(email=admin_email)
        if profile is not None:
            return profile
    raise RuntimeError("Target admin profile was not found. Activate the admin account in Supabase before importing.")


def replace_sqlite_target_user_data(db_path: Path, user_id: str) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DELETE FROM user_collection_cards WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM user_decks WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def replace_postgres_target_user_data(database_url: str, user_id: str) -> None:
    import psycopg

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM user_collection_cards WHERE user_id = %s::uuid", (user_id,))
        cur.execute("DELETE FROM user_decks WHERE user_id = %s::uuid", (user_id,))
        conn.commit()


def insert_collection_sqlite(db_path: Path, *, user_id: str, rows: list[sqlite3.Row]) -> int:
    now = utc_now_iso()
    conn = sqlite3.connect(str(db_path))
    try:
        count = 0
        for row in rows:
            title = str(row["card_title"] or "").strip()
            quantity = max(0, int(row["quantity"] or 0))
            key = normalize_card_key(title)
            if not title or not key or quantity <= 0:
                continue
            conn.execute(
                """
                INSERT INTO user_collection_cards (user_id, card_key, card_title, quantity, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, card_key) DO UPDATE SET
                    card_title = excluded.card_title,
                    quantity = excluded.quantity,
                    updated_at = excluded.updated_at
                """,
                (user_id, key, title, quantity, now),
            )
            count += 1
        conn.commit()
        return count
    finally:
        conn.close()


def insert_collection_postgres(database_url: str, *, user_id: str, rows: list[sqlite3.Row]) -> int:
    import psycopg

    now = utc_now_iso()
    count = 0
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        for row in rows:
            title = str(row["card_title"] or "").strip()
            quantity = max(0, int(row["quantity"] or 0))
            key = normalize_card_key(title)
            if not title or not key or quantity <= 0:
                continue
            cur.execute(
                """
                INSERT INTO user_collection_cards (user_id, card_key, card_title, quantity, updated_at)
                VALUES (%s::uuid, %s, %s, %s, %s)
                ON CONFLICT(user_id, card_key) DO UPDATE SET
                    card_title = EXCLUDED.card_title,
                    quantity = EXCLUDED.quantity,
                    updated_at = EXCLUDED.updated_at
                """,
                (user_id, key, title, quantity, now),
            )
            count += 1
        conn.commit()
    return count


def payload_legend_title(payload: dict[str, Any]) -> str:
    return str(payload.get("legendTitle") or payload.get("legend_title") or "").strip()


def payload_champion_title(payload: dict[str, Any]) -> str:
    return str(payload.get("chosenChampionTitle") or payload.get("chosen_champion_title") or "").strip()


def insert_decks_sqlite(db_path: Path, *, user_id: str, rows: list[sqlite3.Row]) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        count = 0
        for row in rows:
            payload = json.loads(str(row["payload_json"] or "{}"))
            deck_id = str(row["id"] or "").strip() or str(uuid4())
            created_at = str(row["created_at"] or "").strip() or utc_now_iso()
            updated_at = str(row["updated_at"] or "").strip() or created_at
            conn.execute(
                """
                INSERT INTO user_decks (
                    id, user_id, name, source, format, bucket, visibility,
                    legend_title, chosen_champion_title, payload_json,
                    published_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'private', ?, ?, ?, NULL, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    user_id = excluded.user_id,
                    name = excluded.name,
                    source = excluded.source,
                    format = excluded.format,
                    bucket = excluded.bucket,
                    visibility = excluded.visibility,
                    legend_title = excluded.legend_title,
                    chosen_champion_title = excluded.chosen_champion_title,
                    payload_json = excluded.payload_json,
                    published_at = excluded.published_at,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    deck_id,
                    user_id,
                    str(row["name"] or payload.get("name") or "Untitled Deck"),
                    str(row["source"] or payload.get("source") or "import"),
                    str(row["format"] or payload.get("format") or "constructed"),
                    str(row["bucket"] or "saved").strip().lower() == "built" and "built" or "saved",
                    payload_legend_title(payload),
                    payload_champion_title(payload),
                    json.dumps(payload),
                    created_at,
                    updated_at,
                ),
            )
            count += 1
        conn.commit()
        return count
    finally:
        conn.close()


def insert_decks_postgres(database_url: str, *, user_id: str, rows: list[sqlite3.Row]) -> int:
    import psycopg

    count = 0
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        for row in rows:
            payload = json.loads(str(row["payload_json"] or "{}"))
            deck_id = str(row["id"] or "").strip() or str(uuid4())
            created_at = str(row["created_at"] or "").strip() or utc_now_iso()
            updated_at = str(row["updated_at"] or "").strip() or created_at
            cur.execute(
                """
                INSERT INTO user_decks (
                    id, user_id, name, source, format, bucket, visibility,
                    legend_title, chosen_champion_title, payload_json,
                    published_at, created_at, updated_at
                )
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, 'private', %s, %s, %s::jsonb, NULL, %s, %s)
                ON CONFLICT(id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    name = EXCLUDED.name,
                    source = EXCLUDED.source,
                    format = EXCLUDED.format,
                    bucket = EXCLUDED.bucket,
                    visibility = EXCLUDED.visibility,
                    legend_title = EXCLUDED.legend_title,
                    chosen_champion_title = EXCLUDED.chosen_champion_title,
                    payload_json = EXCLUDED.payload_json,
                    published_at = EXCLUDED.published_at,
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    deck_id,
                    user_id,
                    str(row["name"] or payload.get("name") or "Untitled Deck"),
                    str(row["source"] or payload.get("source") or "import"),
                    str(row["format"] or payload.get("format") or "constructed"),
                    str(row["bucket"] or "saved").strip().lower() == "built" and "built" or "saved",
                    payload_legend_title(payload),
                    payload_champion_title(payload),
                    json.dumps(payload),
                    created_at,
                    updated_at,
                ),
            )
            count += 1
        conn.commit()
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import legacy SQLite collection/decks into a beta user account.")
    parser.add_argument("--source-sqlite", required=True, help="Path to the legacy SQLite database.")
    parser.add_argument("--target-database-url", default="", help="Target Postgres connection string. Overrides RB_DATABASE_URL.")
    parser.add_argument("--target-sqlite-path", default="", help="Target SQLite database path for local migration testing.")
    parser.add_argument("--admin-email", default="", help="Target admin email in user_profiles.")
    parser.add_argument("--admin-user-id", default="", help="Target admin user id in user_profiles.")
    parser.add_argument("--replace-existing", action="store_true", help="Delete the target user's current decks and collection before importing.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_path = Path(args.source_sqlite).resolve()
    if not source_path.is_file():
        print(f"Source database not found: {source_path}")
        return 1

    target_storage, target_kind = build_target_storage(args.target_database_url, args.target_sqlite_path)
    admin_profile = target_admin_profile(target_storage, admin_email=args.admin_email, admin_user_id=args.admin_user_id)
    print(f"target admin: user_id={admin_profile.user_id} email={admin_profile.email}")

    with open_source_db(source_path) as source_conn:
        collection_rows = source_collection_rows(source_conn)
        deck_rows = source_deck_rows(source_conn)

    if args.replace_existing:
        if target_kind == "postgres":
            replace_postgres_target_user_data(args.target_database_url or load_config().database_url, admin_profile.user_id)
        else:
            replace_sqlite_target_user_data(Path(args.target_sqlite_path or load_config().db_path), admin_profile.user_id)

    if target_kind == "postgres":
        target_url = args.target_database_url or load_config().database_url
        imported_collection = insert_collection_postgres(target_url, user_id=admin_profile.user_id, rows=collection_rows)
        imported_decks = insert_decks_postgres(target_url, user_id=admin_profile.user_id, rows=deck_rows)
    else:
        target_path = Path(args.target_sqlite_path or load_config().db_path)
        imported_collection = insert_collection_sqlite(target_path, user_id=admin_profile.user_id, rows=collection_rows)
        imported_decks = insert_decks_sqlite(target_path, user_id=admin_profile.user_id, rows=deck_rows)

    print(
        f"import complete: collection_rows={imported_collection} deck_rows={imported_decks} "
        f"source={source_path} target_user={admin_profile.user_id}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
