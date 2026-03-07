from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from app.domain.models import BetaInviteSummary, DeckLibraryRow, DeckPayload, UserProfileSummary
from app.domain.normalization import normalize_card_key

_BUCKET_BUILT = "built"
_BUCKET_SAVED = "saved"
_VISIBILITY_PRIVATE = "private"
_VISIBILITY_PUBLIC = "public"
_ROLE_ADMIN = "admin"
_ROLE_USER = "user"
_INVITE_ACCEPTED = "accepted"
_INVITE_INVITED = "invited"
_INVITE_REVOKED = "revoked"
_PROFILE_ACTIVE = "active"
_PROFILE_DISABLED = "disabled"
_SCHEMA_VERSION = 6


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_bucket(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw == _BUCKET_BUILT:
        return _BUCKET_BUILT
    return _BUCKET_SAVED


def _normalize_visibility(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw == _VISIBILITY_PUBLIC:
        return _VISIBILITY_PUBLIC
    return _VISIBILITY_PRIVATE


def _normalize_role(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw == _ROLE_ADMIN:
        return _ROLE_ADMIN
    return _ROLE_USER


def _normalize_invite_status(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw == _INVITE_ACCEPTED:
        return _INVITE_ACCEPTED
    if raw == _INVITE_REVOKED:
        return _INVITE_REVOKED
    return _INVITE_INVITED


def _normalize_profile_status(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw == _PROFILE_DISABLED:
        return _PROFILE_DISABLED
    return _PROFILE_ACTIVE


class SqliteStorage:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @property
    def db_path(self) -> Path:
        return self._db_path

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

                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                );

                CREATE TABLE IF NOT EXISTS beta_invites (
                    email TEXT PRIMARY KEY,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    accepted_user_id TEXT,
                    invited_at TEXT NOT NULL,
                    accepted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS user_collection_cards (
                    user_id TEXT NOT NULL,
                    card_key TEXT NOT NULL,
                    card_title TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK(quantity >= 0),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, card_key),
                    FOREIGN KEY(user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS user_decks (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    format TEXT NOT NULL,
                    bucket TEXT NOT NULL DEFAULT 'saved',
                    visibility TEXT NOT NULL DEFAULT 'private',
                    legend_title TEXT NOT NULL DEFAULT '',
                    chosen_champion_title TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    published_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS deck_likes (
                    user_id TEXT NOT NULL,
                    deck_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, deck_id),
                    FOREIGN KEY(user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE,
                    FOREIGN KEY(deck_id) REFERENCES user_decks(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_user_collection_cards_user_id ON user_collection_cards (user_id);
                CREATE INDEX IF NOT EXISTS idx_user_decks_user_id_updated_at ON user_decks (user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_user_decks_visibility_updated_at ON user_decks (visibility, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_user_decks_visibility_format_updated_at ON user_decks (visibility, format, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_deck_likes_deck_id ON deck_likes (deck_id);

                CREATE TABLE IF NOT EXISTS schema_meta (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    schema_version INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            columns = {str(row["name"]).strip().lower() for row in conn.execute("PRAGMA table_info(deck_library)").fetchall()}
            if "bucket" not in columns:
                conn.execute("ALTER TABLE deck_library ADD COLUMN bucket TEXT NOT NULL DEFAULT 'saved'")
            now = _utc_now_iso()
            row = conn.execute("SELECT schema_version FROM schema_meta WHERE id = 1").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO schema_meta (id, schema_version, updated_at) VALUES (1, ?, ?)",
                    (_SCHEMA_VERSION, now),
                )
            else:
                current_version = int(row["schema_version"])
                if current_version > _SCHEMA_VERSION:
                    raise RuntimeError(
                        f"Database schema version {current_version} is newer than supported version {_SCHEMA_VERSION}."
                    )
                if current_version < _SCHEMA_VERSION:
                    conn.execute(
                        "UPDATE schema_meta SET schema_version = ?, updated_at = ? WHERE id = 1",
                        (_SCHEMA_VERSION, now),
                    )

    def schema_version(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT schema_version FROM schema_meta WHERE id = 1").fetchone()
        if row is None:
            return 0
        return int(row["schema_version"])

    def schema_status(self) -> dict[str, object]:
        actual = self.schema_version()
        return {
            "ok": actual == _SCHEMA_VERSION,
            "expectedVersion": _SCHEMA_VERSION,
            "actualVersion": actual,
            "dbPath": str(self._db_path),
            "backend": "sqlite",
        }

    def _profile_from_row(self, row: sqlite3.Row | None) -> UserProfileSummary | None:
        if row is None:
            return None
        return UserProfileSummary(
            userId=str(row["user_id"]),
            email=str(row["email"]),
            displayName=str(row["display_name"]),
            role=_normalize_role(row["role"]),
            status=_normalize_profile_status(row["status"]),
            createdAt=str(row["created_at"]),
            updatedAt=str(row["updated_at"]),
            lastLoginAt=str(row["last_login_at"]) if row["last_login_at"] is not None else None,
        )

    def _invite_from_row(self, row: sqlite3.Row | None) -> BetaInviteSummary | None:
        if row is None:
            return None
        return BetaInviteSummary(
            email=str(row["email"]),
            role=_normalize_role(row["role"]),
            status=_normalize_invite_status(row["status"]),
            acceptedUserId=str(row["accepted_user_id"]) if row["accepted_user_id"] is not None else None,
            invitedAt=str(row["invited_at"]),
            acceptedAt=str(row["accepted_at"]) if row["accepted_at"] is not None else None,
        )

    def get_profile(self, *, user_id: str) -> UserProfileSummary | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT user_id, email, display_name, role, status, created_at, updated_at, last_login_at
                FROM user_profiles
                WHERE user_id = ?
                """,
                (str(user_id or "").strip(),),
            ).fetchone()
        return self._profile_from_row(row)

    def get_profile_by_email(self, *, email: str) -> UserProfileSummary | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT user_id, email, display_name, role, status, created_at, updated_at, last_login_at
                FROM user_profiles
                WHERE lower(email) = ?
                """,
                (str(email or "").strip().lower(),),
            ).fetchone()
        return self._profile_from_row(row)

    def seed_beta_invite(self, *, email: str, role: str = "user", status: str = "invited") -> BetaInviteSummary:
        clean_email = str(email or "").strip().lower()
        if not clean_email:
            raise RuntimeError("Invite email is required.")
        now = _utc_now_iso()
        normalized_role = _normalize_role(role)
        normalized_status = _normalize_invite_status(status)
        accepted_at = now if normalized_status == _INVITE_ACCEPTED else None
        with self._connect() as conn:
            existing = conn.execute("SELECT invited_at FROM beta_invites WHERE email = ?", (clean_email,)).fetchone()
            invited_at = str(existing["invited_at"]) if existing is not None else now
            conn.execute(
                """
                INSERT INTO beta_invites (email, role, status, accepted_user_id, invited_at, accepted_at)
                VALUES (?, ?, ?, NULL, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    role = excluded.role,
                    status = excluded.status,
                    invited_at = excluded.invited_at,
                    accepted_at = CASE
                        WHEN excluded.status = 'accepted' THEN COALESCE(beta_invites.accepted_at, excluded.accepted_at)
                        ELSE NULL
                    END,
                    accepted_user_id = CASE
                        WHEN excluded.status = 'accepted' THEN beta_invites.accepted_user_id
                        ELSE NULL
                    END
                """,
                (clean_email, normalized_role, normalized_status, invited_at, accepted_at),
            )
            row = conn.execute(
                "SELECT email, role, status, accepted_user_id, invited_at, accepted_at FROM beta_invites WHERE email = ?",
                (clean_email,),
            ).fetchone()
        invite = self._invite_from_row(row)
        if invite is None:
            raise RuntimeError("Invite could not be created.")
        return invite

    def get_beta_invite(self, *, email: str) -> BetaInviteSummary | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT email, role, status, accepted_user_id, invited_at, accepted_at
                FROM beta_invites
                WHERE lower(email) = ?
                """,
                (str(email or "").strip().lower(),),
            ).fetchone()
        return self._invite_from_row(row)

    def bootstrap_user_from_invite(self, *, user_id: str, email: str, display_name: str) -> UserProfileSummary:
        clean_user_id = str(user_id or "").strip()
        clean_email = str(email or "").strip().lower()
        clean_display_name = str(display_name or "").strip() or clean_email.split("@", 1)[0] or "Riftbound User"
        if not clean_user_id or not clean_email:
            raise RuntimeError("Invite bootstrap requires a user id and email.")

        invite = self.get_beta_invite(email=clean_email)
        if invite is None:
            raise RuntimeError("This account is not invited to the closed beta.")
        if invite.status == _INVITE_REVOKED:
            raise RuntimeError("This beta invite has been revoked.")
        if invite.status == _INVITE_ACCEPTED and invite.accepted_user_id and invite.accepted_user_id != clean_user_id:
            raise RuntimeError("This beta invite is already linked to another account.")

        now = _utc_now_iso()
        with self._connect() as conn:
            by_user = conn.execute(
                """
                SELECT user_id, email, display_name, role, status, created_at, updated_at, last_login_at
                FROM user_profiles
                WHERE user_id = ?
                """,
                (clean_user_id,),
            ).fetchone()
            by_email = conn.execute(
                """
                SELECT user_id, email, display_name, role, status, created_at, updated_at, last_login_at
                FROM user_profiles
                WHERE lower(email) = ?
                """,
                (clean_email,),
            ).fetchone()
            existing = by_user or by_email
            if existing is not None and _normalize_profile_status(existing["status"]) == _PROFILE_DISABLED:
                raise RuntimeError("This account has been disabled.")

            role = _normalize_role(invite.role)
            if by_email is not None and str(by_email["user_id"]) != clean_user_id and by_user is None:
                conn.execute(
                    """
                    UPDATE user_profiles
                    SET user_id = ?, display_name = ?, role = ?, status = ?, updated_at = ?, last_login_at = ?
                    WHERE lower(email) = ?
                    """,
                    (clean_user_id, clean_display_name, role, _PROFILE_ACTIVE, now, now, clean_email),
                )
            elif by_user is not None:
                conn.execute(
                    """
                    UPDATE user_profiles
                    SET email = ?, display_name = ?, role = ?, status = ?, updated_at = ?, last_login_at = ?
                    WHERE user_id = ?
                    """,
                    (clean_email, clean_display_name, role, _PROFILE_ACTIVE, now, now, clean_user_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO user_profiles (user_id, email, display_name, role, status, created_at, updated_at, last_login_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (clean_user_id, clean_email, clean_display_name, role, _PROFILE_ACTIVE, now, now, now),
                )

            conn.execute(
                """
                UPDATE beta_invites
                SET status = ?, accepted_user_id = ?, accepted_at = COALESCE(accepted_at, ?)
                WHERE lower(email) = ?
                """,
                (_INVITE_ACCEPTED, clean_user_id, now, clean_email),
            )
            row = conn.execute(
                """
                SELECT user_id, email, display_name, role, status, created_at, updated_at, last_login_at
                FROM user_profiles
                WHERE user_id = ?
                """,
                (clean_user_id,),
            ).fetchone()

        profile = self._profile_from_row(row)
        if profile is None:
            raise RuntimeError("Profile bootstrap failed.")
        return profile

    def update_display_name(self, *, user_id: str, display_name: str) -> UserProfileSummary:
        clean_user_id = str(user_id or "").strip()
        clean_name = str(display_name or "").strip()[:32]
        if not clean_name:
            raise ValueError("Display name cannot be empty.")
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE user_profiles SET display_name = ?, updated_at = ? WHERE user_id = ?",
                (clean_name, now, clean_user_id),
            )
            row = conn.execute(
                "SELECT user_id, email, display_name, role, status, created_at, updated_at, last_login_at FROM user_profiles WHERE user_id = ?",
                (clean_user_id,),
            ).fetchone()
        profile = self._profile_from_row(row)
        if profile is None:
            raise RuntimeError("Profile not found.")
        return profile

    def like_deck(self, *, user_id: str, deck_id: str) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO deck_likes (user_id, deck_id, created_at)
                VALUES (?, ?, ?)
                """,
                (str(user_id or "").strip(), str(deck_id or "").strip(), now),
            )

    def unlike_deck(self, *, user_id: str, deck_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM deck_likes WHERE user_id = ? AND deck_id = ?",
                (str(user_id or "").strip(), str(deck_id or "").strip()),
            )

    def get_collection(self, *, user_id: str) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT card_title, quantity
                FROM user_collection_cards
                WHERE user_id = ? AND quantity > 0
                ORDER BY card_title COLLATE NOCASE
                """,
                (str(user_id or "").strip(),),
            ).fetchall()
        return {str(row["card_title"]): int(row["quantity"]) for row in rows}

    def set_collection_item(self, *, user_id: str, card_title: str, quantity: int) -> None:
        title = str(card_title or "").strip()
        key = normalize_card_key(title)
        qty = max(0, int(quantity))
        clean_user_id = str(user_id or "").strip()
        if not clean_user_id or not title or not key:
            return
        now = _utc_now_iso()
        with self._connect() as conn:
            if qty <= 0:
                conn.execute("DELETE FROM user_collection_cards WHERE user_id = ? AND card_key = ?", (clean_user_id, key))
                return
            conn.execute(
                """
                INSERT INTO user_collection_cards (user_id, card_key, card_title, quantity, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, card_key) DO UPDATE SET
                    card_title = excluded.card_title,
                    quantity = excluded.quantity,
                    updated_at = excluded.updated_at
                """,
                (clean_user_id, key, title, qty, now),
            )

    def upsert_collection(self, user_id: str, cards_map: dict[str, int], *, replace_existing: bool = False) -> None:
        clean_user_id = str(user_id or "").strip()
        now = _utc_now_iso()
        normalized_rows: dict[str, tuple[str, int]] = {}
        for raw_title, raw_qty in cards_map.items():
            title = str(raw_title or "").strip()
            key = normalize_card_key(title)
            qty = max(0, int(raw_qty))
            if title and key and qty > 0:
                normalized_rows[key] = (title, qty)

        with self._connect() as conn:
            if replace_existing:
                conn.execute("DELETE FROM user_collection_cards WHERE user_id = ?", (clean_user_id,))
            for key, (title, qty) in normalized_rows.items():
                conn.execute(
                    """
                    INSERT INTO user_collection_cards (user_id, card_key, card_title, quantity, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, card_key) DO UPDATE SET
                        card_title = excluded.card_title,
                        quantity = excluded.quantity,
                        updated_at = excluded.updated_at
                    """,
                    (clean_user_id, key, title, qty, now),
                )

    def clear_collection(self, *, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM user_collection_cards WHERE user_id = ?", (str(user_id or "").strip(),))

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

    def get_built_cards_in_use(self, *, user_id: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in self.list_decks(user_id=user_id, bucket=_BUCKET_BUILT):
            requirements = self._deck_requirement_map(row.deck)
            for title, qty in requirements.items():
                key = normalize_card_key(title)
                if not key:
                    continue
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

    def _deck_row_to_model(self, row: sqlite3.Row | None, *, viewer_user_id: str) -> DeckLibraryRow | None:
        if row is None:
            return None
        payload_raw = json.loads(str(row["payload_json"]))
        keys = row.keys()
        like_count = int(row["like_count"]) if "like_count" in keys else 0
        liked_by_me = bool(row["liked_by_me"]) if "liked_by_me" in keys else False
        return DeckLibraryRow(
            id=str(row["id"]),
            name=str(row["name"]),
            source=str(row["source"]),
            format=str(row["format"]),
            bucket=_normalize_bucket(row["bucket"]),
            visibility=_normalize_visibility(row["visibility"]),
            ownerDisplayName=str(row["owner_display_name"] or ""),
            isOwner=str(row["user_id"]) == str(viewer_user_id),
            publishedAt=str(row["published_at"]) if row["published_at"] is not None else None,
            createdAt=str(row["created_at"]),
            updatedAt=str(row["updated_at"]),
            likeCount=like_count,
            likedByMe=liked_by_me,
            deck=DeckPayload.model_validate(payload_raw),
        )

    def list_decks(self, *, user_id: str, bucket: str | None = None, query: str = "") -> list[DeckLibraryRow]:
        clean_user_id = str(user_id or "").strip()
        query_where = ""
        params: list[object] = [clean_user_id]
        if bucket is not None:
            query_where += " AND d.bucket = ?"
            params.append(_normalize_bucket(bucket))
        needle = str(query or "").strip().lower()
        if needle:
            query_where += " AND (lower(d.name) LIKE ? ESCAPE '\\' OR lower(d.source) LIKE ? ESCAPE '\\' OR lower(d.legend_title) LIKE ? ESCAPE '\\')"
            escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = f"%{escaped}%"
            params.extend([like, like, like])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT d.id, d.user_id, d.name, d.source, d.format, d.bucket, d.visibility, d.payload_json,
                       d.published_at, d.created_at, d.updated_at, p.display_name AS owner_display_name
                FROM user_decks d
                JOIN user_profiles p ON p.user_id = d.user_id
                WHERE d.user_id = ? {query_where}
                ORDER BY d.updated_at DESC
                """,
                tuple(params),
            ).fetchall()
        return [row for row in (self._deck_row_to_model(item, viewer_user_id=clean_user_id) for item in rows) if row is not None]

    def list_public_decks(
        self,
        *,
        viewer_user_id: str,
        query: str = "",
        format_name: str | None = None,
        limit: int = 60,
        offset: int = 0,
        sort_by: str = "updated",
    ) -> list[DeckLibraryRow]:
        needle = str(query or "").strip().lower()
        where = ["d.visibility = ?"]
        params: list[object] = [_VISIBILITY_PUBLIC]
        if needle:
            where.append("(lower(d.name) LIKE ? ESCAPE '\\' OR lower(d.source) LIKE ? ESCAPE '\\' OR lower(d.legend_title) LIKE ? ESCAPE '\\' OR lower(p.display_name) LIKE ? ESCAPE '\\')")
            escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = f"%{escaped}%"
            params.extend([like, like, like, like])
        clean_format = str(format_name or "").strip().lower()
        if clean_format:
            where.append("lower(d.format) = ?")
            params.append(clean_format)
        order_by = "d.updated_at DESC"
        if sort_by == "likes":
            order_by = "like_count DESC, d.updated_at DESC"
        elif sort_by == "name":
            order_by = "lower(d.name) ASC"
        params.extend([viewer_user_id, max(1, int(limit)), max(0, int(offset))])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT d.id, d.user_id, d.name, d.source, d.format, d.bucket, d.visibility, d.payload_json,
                       d.published_at, d.created_at, d.updated_at, p.display_name AS owner_display_name,
                       COUNT(lk.deck_id) AS like_count,
                       MAX(CASE WHEN lk.user_id = ? THEN 1 ELSE 0 END) AS liked_by_me
                FROM user_decks d
                JOIN user_profiles p ON p.user_id = d.user_id
                LEFT JOIN deck_likes lk ON lk.deck_id = d.id
                WHERE {' AND '.join(where)}
                GROUP BY d.id, d.user_id, d.name, d.source, d.format, d.bucket, d.visibility,
                         d.payload_json, d.published_at, d.created_at, d.updated_at, p.display_name
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
        return [row for row in (self._deck_row_to_model(item, viewer_user_id=viewer_user_id) for item in rows) if row is not None]

    def get_deck(self, *, user_id: str, deck_id: str) -> DeckLibraryRow | None:
        clean_user_id = str(user_id or "").strip()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT d.id, d.user_id, d.name, d.source, d.format, d.bucket, d.visibility, d.payload_json,
                       d.published_at, d.created_at, d.updated_at, p.display_name AS owner_display_name
                FROM user_decks d
                JOIN user_profiles p ON p.user_id = d.user_id
                WHERE d.id = ? AND d.user_id = ?
                """,
                (deck_id, clean_user_id),
            ).fetchone()
        return self._deck_row_to_model(row, viewer_user_id=clean_user_id)

    def get_public_deck(self, *, viewer_user_id: str, deck_id: str) -> DeckLibraryRow | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT d.id, d.user_id, d.name, d.source, d.format, d.bucket, d.visibility, d.payload_json,
                       d.published_at, d.created_at, d.updated_at, p.display_name AS owner_display_name,
                       COUNT(lk.deck_id) AS like_count,
                       MAX(CASE WHEN lk.user_id = ? THEN 1 ELSE 0 END) AS liked_by_me
                FROM user_decks d
                JOIN user_profiles p ON p.user_id = d.user_id
                LEFT JOIN deck_likes lk ON lk.deck_id = d.id
                WHERE d.id = ? AND d.visibility = ?
                GROUP BY d.id, d.user_id, d.name, d.source, d.format, d.bucket, d.visibility,
                         d.payload_json, d.published_at, d.created_at, d.updated_at, p.display_name
                """,
                (viewer_user_id, deck_id, _VISIBILITY_PUBLIC),
            ).fetchone()
        return self._deck_row_to_model(row, viewer_user_id=viewer_user_id)

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
        now = _utc_now_iso()
        deck_id = str(uuid4())
        row_name = str(name or deck.name or "Untitled Deck").strip() or "Untitled Deck"
        row_source = str(source or deck.source or "builder").strip() or "builder"
        row_bucket = _normalize_bucket(bucket)
        row_visibility = _normalize_visibility(visibility)
        published_at = now if row_visibility == _VISIBILITY_PUBLIC else None
        payload = deck.model_dump(by_alias=True)
        clean_user_id = str(user_id or "").strip()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_decks (
                    id, user_id, name, source, format, bucket, visibility,
                    legend_title, chosen_champion_title, payload_json,
                    published_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deck_id,
                    clean_user_id,
                    row_name,
                    row_source,
                    deck.format,
                    row_bucket,
                    row_visibility,
                    deck.legend_title,
                    deck.chosen_champion_title,
                    json.dumps(payload),
                    published_at,
                    now,
                    now,
                ),
            )
            profile_row = conn.execute(
                "SELECT display_name FROM user_profiles WHERE user_id = ?",
                (clean_user_id,),
            ).fetchone()
            owner_display_name = str(profile_row["display_name"]) if profile_row else ""
        return DeckLibraryRow(
            id=deck_id,
            name=row_name,
            source=row_source,
            format=deck.format,
            bucket=row_bucket,
            visibility=row_visibility,
            ownerDisplayName=owner_display_name,
            isOwner=True,
            publishedAt=published_at,
            createdAt=now,
            updatedAt=now,
            deck=deck,
        )

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
        row_name = str(name or existing.name).strip() or existing.name
        row_source = str(source or existing.source).strip() or existing.source
        row_bucket = _normalize_bucket(bucket or existing.bucket)
        row_visibility = _normalize_visibility(visibility or existing.visibility)
        payload = deck.model_dump(by_alias=True)
        published_at = existing.published_at if row_visibility == _VISIBILITY_PUBLIC else None
        if row_visibility == _VISIBILITY_PUBLIC and not published_at:
            published_at = now
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE user_decks
                SET name = ?, source = ?, format = ?, bucket = ?, visibility = ?,
                    legend_title = ?, chosen_champion_title = ?, payload_json = ?,
                    published_at = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    row_name,
                    row_source,
                    deck.format,
                    row_bucket,
                    row_visibility,
                    deck.legend_title,
                    deck.chosen_champion_title,
                    json.dumps(payload),
                    published_at,
                    now,
                    deck_id,
                    str(user_id or "").strip(),
                ),
            )
        return self.get_deck(user_id=user_id, deck_id=deck_id)

    def set_deck_bucket(self, *, user_id: str, deck_id: str, bucket: str) -> DeckLibraryRow | None:
        existing = self.get_deck(user_id=user_id, deck_id=deck_id)
        if existing is None:
            return None
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE user_decks
                SET bucket = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (_normalize_bucket(bucket), now, deck_id, str(user_id or "").strip()),
            )
        return self.get_deck(user_id=user_id, deck_id=deck_id)

    def delete_deck(self, *, user_id: str, deck_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM user_decks WHERE id = ? AND user_id = ?",
                (deck_id, str(user_id or "").strip()),
            )
            return int(cur.rowcount or 0) > 0
