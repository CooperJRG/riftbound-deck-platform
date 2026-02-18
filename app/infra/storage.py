from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from app.domain.models import DeckLibraryRow, DeckPayload
from app.domain.normalization import normalize_card_key

_BUCKET_BUILT = "built"
_BUCKET_SAVED = "saved"


def _normalize_bucket(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw == _BUCKET_BUILT:
        return _BUCKET_BUILT
    return _BUCKET_SAVED


class SqliteStorage:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS collection_cards (
                    card_key TEXT PRIMARY KEY,
                    card_title TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK(quantity >= 0),
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS deck_library (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    format TEXT NOT NULL,
                    bucket TEXT NOT NULL DEFAULT 'saved',
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            columns = {str(row["name"]).strip().lower() for row in conn.execute("PRAGMA table_info(deck_library)").fetchall()}
            if "bucket" not in columns:
                conn.execute("ALTER TABLE deck_library ADD COLUMN bucket TEXT NOT NULL DEFAULT 'saved'")

    def get_collection(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT card_title, quantity FROM collection_cards WHERE quantity > 0 ORDER BY card_title COLLATE NOCASE"
            ).fetchall()
        out: dict[str, int] = {}
        for row in rows:
            out[str(row["card_title"])] = int(row["quantity"])
        return out

    def set_collection_item(self, *, card_title: str, quantity: int) -> None:
        title = str(card_title or "").strip()
        key = normalize_card_key(title)
        qty = max(0, int(quantity))
        if not title or not key:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            if qty <= 0:
                conn.execute("DELETE FROM collection_cards WHERE card_key = ?", (key,))
                return
            conn.execute(
                """
                INSERT INTO collection_cards (card_key, card_title, quantity, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(card_key) DO UPDATE SET
                    card_title = excluded.card_title,
                    quantity = excluded.quantity,
                    updated_at = excluded.updated_at
                """,
                (key, title, qty, now),
            )

    def upsert_collection(self, cards_map: dict[str, int], *, replace_existing: bool = False) -> None:
        now = datetime.now(timezone.utc).isoformat()
        normalized_rows: dict[str, tuple[str, int]] = {}
        for raw_title, raw_qty in cards_map.items():
            title = str(raw_title or "").strip()
            key = normalize_card_key(title)
            qty = max(0, int(raw_qty))
            if title and key and qty > 0:
                normalized_rows[key] = (title, qty)

        with self._connect() as conn:
            if replace_existing:
                conn.execute("DELETE FROM collection_cards")
            for key, (title, qty) in normalized_rows.items():
                conn.execute(
                    """
                    INSERT INTO collection_cards (card_key, card_title, quantity, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(card_key) DO UPDATE SET
                        card_title = excluded.card_title,
                        quantity = excluded.quantity,
                        updated_at = excluded.updated_at
                    """,
                    (key, title, qty, now),
                )

    def clear_collection(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM collection_cards")

    @staticmethod
    def _deck_requirement_map(deck: DeckPayload) -> dict[str, int]:
        out: dict[str, int] = {}

        def add(title: str, qty: int) -> None:
            t = str(title or "").strip()
            q = max(0, int(qty))
            if not t or q <= 0:
                return
            out[t] = out.get(t, 0) + q

        for title, qty in deck.main.items():
            add(title, qty)
        for title, qty in deck.runes.items():
            add(title, qty)
        for title in deck.battlefields:
            add(title, 1)
        for title, qty in deck.sideboard.items():
            add(title, qty)
        if deck.legend_title:
            add(deck.legend_title, 1)
        if deck.chosen_champion_title:
            current = out.get(deck.chosen_champion_title, 0)
            out[deck.chosen_champion_title] = max(1, current)
        return out

    def get_built_cards_in_use(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in self.list_decks(bucket=_BUCKET_BUILT):
            requirements = self._deck_requirement_map(row.deck)
            for title, qty in requirements.items():
                key = normalize_card_key(title)
                if not key:
                    continue
                out[key] = out.get(key, 0) + max(0, int(qty))
        return out

    def get_collection_in_use(self) -> dict[str, int]:
        owned = self.get_collection()
        in_use_by_key = self.get_built_cards_in_use()
        out: dict[str, int] = {}
        for title, qty in owned.items():
            key = normalize_card_key(title)
            used = min(max(0, int(qty)), max(0, int(in_use_by_key.get(key, 0))))
            if used > 0:
                out[title] = used
        return dict(sorted(out.items(), key=lambda item: item[0].casefold()))

    def get_effective_collection(self) -> dict[str, int]:
        owned = self.get_collection()
        in_use = self.get_collection_in_use()
        out: dict[str, int] = {}
        for title, qty in owned.items():
            available = max(0, int(qty) - int(in_use.get(title, 0)))
            if available > 0:
                out[title] = available
        return dict(sorted(out.items(), key=lambda item: item[0].casefold()))

    def list_decks(self, *, bucket: str | None = None) -> list[DeckLibraryRow]:
        where = ""
        params: tuple[object, ...] = ()
        if bucket is not None:
            where = "WHERE bucket = ?"
            params = (_normalize_bucket(bucket),)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, name, source, format, bucket, payload_json, created_at, updated_at
                FROM deck_library
                {where}
                ORDER BY updated_at DESC
                """,
                params,
            ).fetchall()

        out: list[DeckLibraryRow] = []
        for row in rows:
            payload_raw = json.loads(str(row["payload_json"]))
            deck = DeckPayload.model_validate(payload_raw)
            out.append(
                DeckLibraryRow(
                    id=str(row["id"]),
                    name=str(row["name"]),
                    source=str(row["source"]),
                    format=str(row["format"]),
                    bucket=_normalize_bucket(row["bucket"]),
                    createdAt=str(row["created_at"]),
                    updatedAt=str(row["updated_at"]),
                    deck=deck,
                )
            )
        return out

    def get_deck(self, deck_id: str) -> DeckLibraryRow | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, name, source, format, bucket, payload_json, created_at, updated_at
                FROM deck_library
                WHERE id = ?
                """,
                (deck_id,),
            ).fetchone()
        if row is None:
            return None
        payload_raw = json.loads(str(row["payload_json"]))
        return DeckLibraryRow(
            id=str(row["id"]),
            name=str(row["name"]),
            source=str(row["source"]),
            format=str(row["format"]),
            bucket=_normalize_bucket(row["bucket"]),
            createdAt=str(row["created_at"]),
            updatedAt=str(row["updated_at"]),
            deck=DeckPayload.model_validate(payload_raw),
        )

    def create_deck(self, *, deck: DeckPayload, name: str, source: str, bucket: str | None = None) -> DeckLibraryRow:
        now = datetime.now(timezone.utc).isoformat()
        deck_id = str(uuid4())
        row_name = str(name or deck.name or "Untitled Deck").strip() or "Untitled Deck"
        row_source = str(source or deck.source or "builder").strip() or "builder"
        row_bucket = _normalize_bucket(bucket)
        payload = deck.model_dump(by_alias=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO deck_library (id, name, source, format, bucket, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (deck_id, row_name, row_source, deck.format, row_bucket, json.dumps(payload), now, now),
            )
        return self.get_deck(deck_id)  # type: ignore[return-value]

    def update_deck(
        self,
        deck_id: str,
        *,
        deck: DeckPayload,
        name: str | None,
        source: str | None,
        bucket: str | None = None,
    ) -> DeckLibraryRow | None:
        existing = self.get_deck(deck_id)
        if existing is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        row_name = str(name or existing.name).strip() or existing.name
        row_source = str(source or existing.source).strip() or existing.source
        row_bucket = _normalize_bucket(bucket or existing.bucket)
        payload = deck.model_dump(by_alias=True)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE deck_library
                SET name = ?, source = ?, format = ?, bucket = ?, payload_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (row_name, row_source, deck.format, row_bucket, json.dumps(payload), now, deck_id),
            )
        return self.get_deck(deck_id)

    def set_deck_bucket(self, deck_id: str, bucket: str) -> DeckLibraryRow | None:
        existing = self.get_deck(deck_id)
        if existing is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE deck_library
                SET bucket = ?, updated_at = ?
                WHERE id = ?
                """,
                (_normalize_bucket(bucket), now, deck_id),
            )
        return self.get_deck(deck_id)

    def delete_deck(self, deck_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM deck_library WHERE id = ?", (deck_id,))
            return int(cur.rowcount or 0) > 0
