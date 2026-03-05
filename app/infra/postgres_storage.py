from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.domain.models import BetaInviteSummary, DeckLibraryRow, DeckPayload, UserProfileSummary
from app.domain.normalization import normalize_card_key
from app.infra.storage import (
    _BUCKET_BUILT,
    _BUCKET_SAVED,
    _INVITE_ACCEPTED,
    _INVITE_INVITED,
    _INVITE_REVOKED,
    _PROFILE_ACTIVE,
    _PROFILE_DISABLED,
    _ROLE_ADMIN,
    _ROLE_USER,
    _SCHEMA_VERSION,
    _VISIBILITY_PRIVATE,
    _VISIBILITY_PUBLIC,
    _normalize_bucket,
    _normalize_invite_status,
    _normalize_profile_status,
    _normalize_role,
    _normalize_visibility,
    _utc_now_iso,
)


class PostgresStorage:
    def __init__(self, database_url: str):
        if not str(database_url or "").strip():
            raise RuntimeError("RB_DATABASE_URL is required when RB_STORAGE_BACKEND=postgres.")
        self._database_url = str(database_url).strip()
        self._pool = ConnectionPool(conninfo=self._database_url, kwargs={"row_factory": dict_row}, min_size=1, max_size=10)

    @property
    def db_path(self) -> Path | None:
        return None

    def _profile_from_row(self, row: dict[str, Any] | None) -> UserProfileSummary | None:
        if not row:
            return None
        return UserProfileSummary(
            userId=str(row["user_id"]),
            email=str(row["email"]),
            displayName=str(row["display_name"]),
            role=_normalize_role(row["role"]),
            status=_normalize_profile_status(row["status"]),
            createdAt=str(row["created_at"]),
            updatedAt=str(row["updated_at"]),
            lastLoginAt=str(row["last_login_at"]) if row.get("last_login_at") is not None else None,
        )

    def _invite_from_row(self, row: dict[str, Any] | None) -> BetaInviteSummary | None:
        if not row:
            return None
        return BetaInviteSummary(
            email=str(row["email"]),
            role=_normalize_role(row["role"]),
            status=_normalize_invite_status(row["status"]),
            acceptedUserId=str(row["accepted_user_id"]) if row.get("accepted_user_id") is not None else None,
            invitedAt=str(row["invited_at"]),
            acceptedAt=str(row["accepted_at"]) if row.get("accepted_at") is not None else None,
        )

    def _deck_row_to_model(self, row: dict[str, Any] | None, *, viewer_user_id: str) -> DeckLibraryRow | None:
        if not row:
            return None
        payload_raw = row["payload_json"] if isinstance(row.get("payload_json"), dict) else json.loads(str(row["payload_json"]))
        return DeckLibraryRow(
            id=str(row["id"]),
            name=str(row["name"]),
            source=str(row["source"]),
            format=str(row["format"]),
            bucket=_normalize_bucket(row["bucket"]),
            visibility=_normalize_visibility(row["visibility"]),
            ownerDisplayName=str(row.get("owner_display_name") or ""),
            isOwner=str(row["user_id"]) == str(viewer_user_id),
            publishedAt=str(row["published_at"]) if row.get("published_at") is not None else None,
            createdAt=str(row["created_at"]),
            updatedAt=str(row["updated_at"]),
            deck=DeckPayload.model_validate(payload_raw),
        )

    def init_schema(self) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id uuid PRIMARY KEY,
                    email text NOT NULL UNIQUE,
                    display_name text NOT NULL,
                    role text NOT NULL,
                    status text NOT NULL,
                    created_at timestamptz NOT NULL,
                    updated_at timestamptz NOT NULL,
                    last_login_at timestamptz
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS beta_invites (
                    email text PRIMARY KEY,
                    role text NOT NULL,
                    status text NOT NULL,
                    accepted_user_id uuid NULL,
                    invited_at timestamptz NOT NULL,
                    accepted_at timestamptz NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_collection_cards (
                    user_id uuid NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
                    card_key text NOT NULL,
                    card_title text NOT NULL,
                    quantity integer NOT NULL CHECK(quantity >= 0),
                    updated_at timestamptz NOT NULL,
                    PRIMARY KEY(user_id, card_key)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_decks (
                    id uuid PRIMARY KEY,
                    user_id uuid NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
                    name text NOT NULL,
                    source text NOT NULL,
                    format text NOT NULL,
                    bucket text NOT NULL DEFAULT 'saved',
                    visibility text NOT NULL DEFAULT 'private',
                    legend_title text NOT NULL DEFAULT '',
                    chosen_champion_title text NOT NULL DEFAULT '',
                    payload_json jsonb NOT NULL,
                    published_at timestamptz NULL,
                    created_at timestamptz NOT NULL,
                    updated_at timestamptz NOT NULL
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_collection_cards_user_id ON user_collection_cards (user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_decks_user_id_updated_at ON user_decks (user_id, updated_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_decks_visibility_updated_at ON user_decks (visibility, updated_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_decks_visibility_format_updated_at ON user_decks (visibility, format, updated_at DESC)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    id integer PRIMARY KEY,
                    schema_version integer NOT NULL,
                    updated_at timestamptz NOT NULL
                )
                """
            )
            now = _utc_now_iso()
            cur.execute("SELECT schema_version FROM schema_meta WHERE id = 1")
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO schema_meta (id, schema_version, updated_at) VALUES (1, %s, %s)",
                    (_SCHEMA_VERSION, now),
                )
            else:
                actual = int(row["schema_version"])
                if actual > _SCHEMA_VERSION:
                    raise RuntimeError(
                        f"Database schema version {actual} is newer than supported version {_SCHEMA_VERSION}."
                    )
                if actual < _SCHEMA_VERSION:
                    cur.execute(
                        "UPDATE schema_meta SET schema_version = %s, updated_at = %s WHERE id = 1",
                        (_SCHEMA_VERSION, now),
                    )
            conn.commit()

    def schema_version(self) -> int:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT schema_version FROM schema_meta WHERE id = 1")
            row = cur.fetchone()
        return int(row["schema_version"]) if row else 0

    def schema_status(self) -> dict[str, object]:
        actual = self.schema_version()
        return {
            "ok": actual == _SCHEMA_VERSION,
            "expectedVersion": _SCHEMA_VERSION,
            "actualVersion": actual,
            "backend": "postgres",
        }

    def get_profile(self, *, user_id: str) -> UserProfileSummary | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id::text AS user_id, email, display_name, role, status,
                       created_at::text AS created_at, updated_at::text AS updated_at, last_login_at::text AS last_login_at
                FROM user_profiles
                WHERE user_id = %s::uuid
                """,
                (str(user_id or "").strip(),),
            )
            row = cur.fetchone()
        return self._profile_from_row(row)

    def get_profile_by_email(self, *, email: str) -> UserProfileSummary | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id::text AS user_id, email, display_name, role, status,
                       created_at::text AS created_at, updated_at::text AS updated_at, last_login_at::text AS last_login_at
                FROM user_profiles
                WHERE lower(email) = lower(%s)
                """,
                (str(email or "").strip(),),
            )
            row = cur.fetchone()
        return self._profile_from_row(row)

    def seed_beta_invite(self, *, email: str, role: str = "user", status: str = "invited") -> BetaInviteSummary:
        clean_email = str(email or "").strip().lower()
        if not clean_email:
            raise RuntimeError("Invite email is required.")
        now = _utc_now_iso()
        normalized_role = _normalize_role(role)
        normalized_status = _normalize_invite_status(status)
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO beta_invites (email, role, status, accepted_user_id, invited_at, accepted_at)
                VALUES (%s, %s, %s, NULL, %s, %s)
                ON CONFLICT(email) DO UPDATE SET
                    role = EXCLUDED.role,
                    status = EXCLUDED.status,
                    invited_at = EXCLUDED.invited_at,
                    accepted_at = CASE
                        WHEN EXCLUDED.status = 'accepted' THEN COALESCE(beta_invites.accepted_at, EXCLUDED.accepted_at)
                        ELSE NULL
                    END,
                    accepted_user_id = CASE
                        WHEN EXCLUDED.status = 'accepted' THEN beta_invites.accepted_user_id
                        ELSE NULL
                    END
                RETURNING email, role, status, accepted_user_id::text AS accepted_user_id,
                          invited_at::text AS invited_at, accepted_at::text AS accepted_at
                """,
                (clean_email, normalized_role, normalized_status, now, now if normalized_status == _INVITE_ACCEPTED else None),
            )
            row = cur.fetchone()
            conn.commit()
        invite = self._invite_from_row(row)
        if invite is None:
            raise RuntimeError("Invite could not be created.")
        return invite

    def get_beta_invite(self, *, email: str) -> BetaInviteSummary | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT email, role, status, accepted_user_id::text AS accepted_user_id,
                       invited_at::text AS invited_at, accepted_at::text AS accepted_at
                FROM beta_invites
                WHERE lower(email) = lower(%s)
                """,
                (str(email or "").strip(),),
            )
            row = cur.fetchone()
        return self._invite_from_row(row)

    def bootstrap_user_from_invite(self, *, user_id: str, email: str, display_name: str) -> UserProfileSummary:
        clean_user_id = str(user_id or "").strip()
        clean_email = str(email or "").strip().lower()
        clean_display_name = str(display_name or "").strip() or clean_email.split("@", 1)[0] or "Riftbound User"
        invite = self.get_beta_invite(email=clean_email)
        if invite is None:
            raise RuntimeError("This account is not invited to the closed beta.")
        if invite.status == _INVITE_REVOKED:
            raise RuntimeError("This beta invite has been revoked.")
        if invite.status == _INVITE_ACCEPTED and invite.accepted_user_id and invite.accepted_user_id != clean_user_id:
            raise RuntimeError("This beta invite is already linked to another account.")

        now = _utc_now_iso()
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_profiles (user_id, email, display_name, role, status, created_at, updated_at, last_login_at)
                VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id) DO UPDATE SET
                    email = EXCLUDED.email,
                    display_name = EXCLUDED.display_name,
                    role = EXCLUDED.role,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at,
                    last_login_at = EXCLUDED.last_login_at
                """,
                (clean_user_id, clean_email, clean_display_name, _normalize_role(invite.role), _PROFILE_ACTIVE, now, now, now),
            )
            cur.execute(
                """
                UPDATE beta_invites
                SET status = %s, accepted_user_id = %s::uuid, accepted_at = COALESCE(accepted_at, %s)
                WHERE lower(email) = lower(%s)
                """,
                (_INVITE_ACCEPTED, clean_user_id, now, clean_email),
            )
            conn.commit()
        profile = self.get_profile(user_id=clean_user_id)
        if profile is None:
            raise RuntimeError("Profile bootstrap failed.")
        return profile

    def get_collection(self, *, user_id: str) -> dict[str, int]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT card_title, quantity
                FROM user_collection_cards
                WHERE user_id = %s::uuid AND quantity > 0
                ORDER BY lower(card_title)
                """,
                (str(user_id or "").strip(),),
            )
            rows = cur.fetchall()
        return {str(row["card_title"]): int(row["quantity"]) for row in rows}

    def set_collection_item(self, *, user_id: str, card_title: str, quantity: int) -> None:
        title = str(card_title or "").strip()
        key = normalize_card_key(title)
        qty = max(0, int(quantity))
        now = _utc_now_iso()
        with self._pool.connection() as conn, conn.cursor() as cur:
            if qty <= 0:
                cur.execute("DELETE FROM user_collection_cards WHERE user_id = %s::uuid AND card_key = %s", (user_id, key))
            else:
                cur.execute(
                    """
                    INSERT INTO user_collection_cards (user_id, card_key, card_title, quantity, updated_at)
                    VALUES (%s::uuid, %s, %s, %s, %s)
                    ON CONFLICT(user_id, card_key) DO UPDATE SET
                        card_title = EXCLUDED.card_title,
                        quantity = EXCLUDED.quantity,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (user_id, key, title, qty, now),
                )
            conn.commit()

    def upsert_collection(self, user_id: str, cards_map: dict[str, int], *, replace_existing: bool = False) -> None:
        now = _utc_now_iso()
        with self._pool.connection() as conn, conn.cursor() as cur:
            if replace_existing:
                cur.execute("DELETE FROM user_collection_cards WHERE user_id = %s::uuid", (user_id,))
            for raw_title, raw_qty in cards_map.items():
                title = str(raw_title or "").strip()
                key = normalize_card_key(title)
                qty = max(0, int(raw_qty))
                if not title or not key or qty <= 0:
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
                    (user_id, key, title, qty, now),
                )
            conn.commit()

    def clear_collection(self, *, user_id: str) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM user_collection_cards WHERE user_id = %s::uuid", (user_id,))
            conn.commit()

    @staticmethod
    def _deck_requirement_map(deck: DeckPayload) -> dict[str, int]:
        out: dict[str, int] = {}
        for title, qty in deck.main.items():
            if title and int(qty) > 0:
                out[title] = out.get(title, 0) + int(qty)
        for title, qty in deck.runes.items():
            if title and int(qty) > 0:
                out[title] = out.get(title, 0) + int(qty)
        for title in deck.battlefields:
            if str(title or "").strip():
                out[str(title)] = out.get(str(title), 0) + 1
        for title, qty in deck.sideboard.items():
            if title and int(qty) > 0:
                out[title] = out.get(title, 0) + int(qty)
        if deck.legend_title:
            out[deck.legend_title] = out.get(deck.legend_title, 0) + 1
        if deck.chosen_champion_title:
            out[deck.chosen_champion_title] = max(1, out.get(deck.chosen_champion_title, 0))
        return out

    def get_built_cards_in_use(self, *, user_id: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in self.list_decks(user_id=user_id, bucket=_BUCKET_BUILT):
            for title, qty in self._deck_requirement_map(row.deck).items():
                key = normalize_card_key(title)
                if key:
                    out[key] = out.get(key, 0) + max(0, int(qty))
        return out

    def get_collection_in_use(self, *, user_id: str) -> dict[str, int]:
        owned = self.get_collection(user_id=user_id)
        in_use_by_key = self.get_built_cards_in_use(user_id=user_id)
        out: dict[str, int] = {}
        for title, qty in owned.items():
            key = normalize_card_key(title)
            used = min(max(0, int(qty)), max(0, int(in_use_by_key.get(key, 0))))
            if used > 0:
                out[title] = used
        return dict(sorted(out.items(), key=lambda item: item[0].casefold()))

    def get_effective_collection(self, *, user_id: str) -> dict[str, int]:
        owned = self.get_collection(user_id=user_id)
        in_use = self.get_collection_in_use(user_id=user_id)
        out: dict[str, int] = {}
        for title, qty in owned.items():
            available = max(0, int(qty) - int(in_use.get(title, 0)))
            if available > 0:
                out[title] = available
        return dict(sorted(out.items(), key=lambda item: item[0].casefold()))

    def _deck_rows(self, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            return list(cur.fetchall())

    def list_decks(self, *, user_id: str, bucket: str | None = None, query: str = "") -> list[DeckLibraryRow]:
        clauses = ["d.user_id = %s::uuid"]
        params: list[Any] = [user_id]
        if bucket is not None:
            clauses.append("d.bucket = %s")
            params.append(_normalize_bucket(bucket))
        needle = str(query or "").strip().lower()
        if needle:
            clauses.append("(lower(d.name) LIKE %s OR lower(d.source) LIKE %s OR lower(d.legend_title) LIKE %s)")
            like = f"%{needle}%"
            params.extend([like, like, like])
        rows = self._deck_rows(
            f"""
            SELECT d.id::text AS id, d.user_id::text AS user_id, d.name, d.source, d.format, d.bucket, d.visibility,
                   d.payload_json, d.published_at::text AS published_at, d.created_at::text AS created_at,
                   d.updated_at::text AS updated_at, p.display_name AS owner_display_name
            FROM user_decks d
            JOIN user_profiles p ON p.user_id = d.user_id
            WHERE {' AND '.join(clauses)}
            ORDER BY d.updated_at DESC
            """,
            tuple(params),
        )
        return [row for row in (self._deck_row_to_model(item, viewer_user_id=user_id) for item in rows) if row is not None]

    def list_public_decks(
        self,
        *,
        viewer_user_id: str,
        query: str = "",
        format_name: str | None = None,
        limit: int = 60,
        offset: int = 0,
    ) -> list[DeckLibraryRow]:
        clauses = ["d.visibility = %s"]
        params: list[Any] = [_VISIBILITY_PUBLIC]
        needle = str(query or "").strip().lower()
        if needle:
            clauses.append("(lower(d.name) LIKE %s OR lower(d.source) LIKE %s OR lower(d.legend_title) LIKE %s OR lower(p.display_name) LIKE %s)")
            like = f"%{needle}%"
            params.extend([like, like, like, like])
        clean_format = str(format_name or "").strip().lower()
        if clean_format:
            clauses.append("lower(d.format) = %s")
            params.append(clean_format)
        params.extend([max(1, int(limit)), max(0, int(offset))])
        rows = self._deck_rows(
            f"""
            SELECT d.id::text AS id, d.user_id::text AS user_id, d.name, d.source, d.format, d.bucket, d.visibility,
                   d.payload_json, d.published_at::text AS published_at, d.created_at::text AS created_at,
                   d.updated_at::text AS updated_at, p.display_name AS owner_display_name
            FROM user_decks d
            JOIN user_profiles p ON p.user_id = d.user_id
            WHERE {' AND '.join(clauses)}
            ORDER BY d.updated_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params),
        )
        return [row for row in (self._deck_row_to_model(item, viewer_user_id=viewer_user_id) for item in rows) if row is not None]

    def get_deck(self, *, user_id: str, deck_id: str) -> DeckLibraryRow | None:
        rows = self._deck_rows(
            """
            SELECT d.id::text AS id, d.user_id::text AS user_id, d.name, d.source, d.format, d.bucket, d.visibility,
                   d.payload_json, d.published_at::text AS published_at, d.created_at::text AS created_at,
                   d.updated_at::text AS updated_at, p.display_name AS owner_display_name
            FROM user_decks d
            JOIN user_profiles p ON p.user_id = d.user_id
            WHERE d.id = %s::uuid AND d.user_id = %s::uuid
            """,
            (deck_id, user_id),
        )
        return self._deck_row_to_model(rows[0] if rows else None, viewer_user_id=user_id)

    def get_public_deck(self, *, viewer_user_id: str, deck_id: str) -> DeckLibraryRow | None:
        rows = self._deck_rows(
            """
            SELECT d.id::text AS id, d.user_id::text AS user_id, d.name, d.source, d.format, d.bucket, d.visibility,
                   d.payload_json, d.published_at::text AS published_at, d.created_at::text AS created_at,
                   d.updated_at::text AS updated_at, p.display_name AS owner_display_name
            FROM user_decks d
            JOIN user_profiles p ON p.user_id = d.user_id
            WHERE d.id = %s::uuid AND d.visibility = %s
            """,
            (deck_id, _VISIBILITY_PUBLIC),
        )
        return self._deck_row_to_model(rows[0] if rows else None, viewer_user_id=viewer_user_id)

    def create_deck(
        self,
        *,
        user_id: str,
        deck: DeckPayload,
        name: str,
        source: str,
        bucket: str | None = None,
        visibility: str | None = None,
    ) -> DeckLibraryRow:
        deck_id = str(uuid4())
        now = _utc_now_iso()
        row_visibility = _normalize_visibility(visibility)
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_decks (
                    id, user_id, name, source, format, bucket, visibility,
                    legend_title, chosen_champion_title, payload_json, published_at, created_at, updated_at
                )
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                """,
                (
                    deck_id,
                    user_id,
                    str(name or deck.name or "Untitled Deck").strip() or "Untitled Deck",
                    str(source or deck.source or "builder").strip() or "builder",
                    deck.format,
                    _normalize_bucket(bucket),
                    row_visibility,
                    deck.legend_title,
                    deck.chosen_champion_title,
                    json.dumps(deck.model_dump(by_alias=True)),
                    now if row_visibility == _VISIBILITY_PUBLIC else None,
                    now,
                    now,
                ),
            )
            conn.commit()
        return self.get_deck(user_id=user_id, deck_id=deck_id)  # type: ignore[return-value]

    def update_deck(
        self,
        deck_id: str,
        *,
        user_id: str,
        deck: DeckPayload,
        name: str | None,
        source: str | None,
        bucket: str | None = None,
        visibility: str | None = None,
    ) -> DeckLibraryRow | None:
        existing = self.get_deck(user_id=user_id, deck_id=deck_id)
        if existing is None:
            return None
        now = _utc_now_iso()
        row_visibility = _normalize_visibility(visibility or existing.visibility)
        published_at = existing.published_at if row_visibility == _VISIBILITY_PUBLIC else None
        if row_visibility == _VISIBILITY_PUBLIC and not published_at:
            published_at = now
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_decks
                SET name = %s, source = %s, format = %s, bucket = %s, visibility = %s,
                    legend_title = %s, chosen_champion_title = %s, payload_json = %s::jsonb,
                    published_at = %s, updated_at = %s
                WHERE id = %s::uuid AND user_id = %s::uuid
                """,
                (
                    str(name or existing.name).strip() or existing.name,
                    str(source or existing.source).strip() or existing.source,
                    deck.format,
                    _normalize_bucket(bucket or existing.bucket),
                    row_visibility,
                    deck.legend_title,
                    deck.chosen_champion_title,
                    json.dumps(deck.model_dump(by_alias=True)),
                    published_at,
                    now,
                    deck_id,
                    user_id,
                ),
            )
            conn.commit()
        return self.get_deck(user_id=user_id, deck_id=deck_id)

    def set_deck_bucket(self, *, user_id: str, deck_id: str, bucket: str) -> DeckLibraryRow | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE user_decks SET bucket = %s, updated_at = %s WHERE id = %s::uuid AND user_id = %s::uuid",
                (_normalize_bucket(bucket), _utc_now_iso(), deck_id, user_id),
            )
            conn.commit()
        return self.get_deck(user_id=user_id, deck_id=deck_id)

    def delete_deck(self, *, user_id: str, deck_id: str) -> bool:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM user_decks WHERE id = %s::uuid AND user_id = %s::uuid", (deck_id, user_id))
            deleted = int(cur.rowcount or 0) > 0
            conn.commit()
        return deleted
