"""SQLite access and a real migration runner.

v2's "migrations" incremented a version number and ran nothing -- there was no path
from schema v1 to v6, and the result was two parallel data models living in one
database, both being written. Here migrations are numbered SQL files applied in order
inside a transaction, and each application is recorded.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterator

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def split_statements(sql: str) -> list[str]:
    """Split a migration file into individual statements.

    Handles ``--`` comments and quoted strings. Migration files are plain DDL by
    convention; anything needing triggers or ``BEGIN...END`` bodies should be done in
    Python rather than smuggled through here.
    """
    statements: list[str] = []
    current: list[str] = []
    in_string = False
    i = 0
    while i < len(sql):
        char = sql[i]
        if in_string:
            current.append(char)
            if char == "'":
                if i + 1 < len(sql) and sql[i + 1] == "'":  # escaped quote
                    current.append(sql[i + 1])
                    i += 1
                else:
                    in_string = False
        elif char == "'":
            in_string = True
            current.append(char)
        elif char == "-" and sql[i : i + 2] == "--":
            while i < len(sql) and sql[i] != "\n":
                i += 1
            current.append("\n")
            continue
        elif char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)
        i += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


class Database:
    """A SQLite database with schema migrations applied on open."""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @contextmanager
    def reading(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    # -- migrations -------------------------------------------------------------

    def migrate(self, *, migrations_dir: Path | None = None) -> list[str]:
        """Apply pending migrations in order. Returns the ones applied."""
        directory = migrations_dir or MIGRATIONS_DIR
        conn = self.connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    name       TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}
            pending = sorted(
                p for p in directory.glob("*.sql") if p.name not in applied
            )
            done: list[str] = []
            for path in pending:
                sql = path.read_text(encoding="utf-8")
                try:
                    conn.execute("BEGIN")
                    # Statement at a time, not executescript: executescript issues an
                    # implicit COMMIT first, which would break this transaction and
                    # leave a half-applied migration recorded as done.
                    for statement in split_statements(sql):
                        conn.execute(statement)
                    conn.execute(
                        "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                        (path.name, utc_now_iso()),
                    )
                    conn.execute("COMMIT")
                except Exception as exc:
                    conn.execute("ROLLBACK")
                    raise RuntimeError(f"Migration {path.name} failed: {exc}") from exc
                done.append(path.name)
            return done
        finally:
            conn.close()

    def applied_migrations(self) -> list[str]:
        with self.reading() as conn:
            try:
                return [
                    row["name"]
                    for row in conn.execute("SELECT name FROM schema_migrations ORDER BY name")
                ]
            except sqlite3.OperationalError:
                return []

    def ensure_user(self, user_id: str, display_name: str = "") -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, display_name, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO NOTHING
                """,
                (user_id, display_name, utc_now_iso()),
            )
