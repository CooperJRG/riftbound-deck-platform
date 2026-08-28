"""Repositories: decks, collections, availability profiles."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import uuid4

from ..domain.availability import (
    MODE_COLLECTION,
    MODE_EXCLUSION,
    AvailabilityProfile,
    ExclusionRule,
    OwnedRule,
)
from ..domain.deck import ZONE_BATTLEFIELDS, ZONES, Deck
from .db import Database, utc_now_iso


@dataclass(frozen=True)
class DeckSummary:
    deck_id: str
    name: str
    format: str
    legend_id: str
    champion_id: str
    main_total: int
    created_at: str
    updated_at: str


class DeckRepository:
    def __init__(self, db: Database):
        self._db = db

    def list(self, *, user_id: str) -> list[DeckSummary]:
        with self._db.reading() as conn:
            rows = conn.execute(
                """
                SELECT d.deck_id, d.name, d.format, d.legend_id, d.champion_id,
                       d.created_at, d.updated_at,
                       COALESCE((SELECT SUM(qty) FROM deck_cards c
                                 WHERE c.deck_id = d.deck_id AND c.zone = 'main'), 0) AS main_total
                FROM decks d
                WHERE d.user_id = ?
                ORDER BY d.updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            DeckSummary(
                deck_id=r["deck_id"], name=r["name"], format=r["format"],
                legend_id=r["legend_id"], champion_id=r["champion_id"],
                main_total=int(r["main_total"]),
                created_at=r["created_at"], updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def get(self, deck_id: str, *, user_id: str) -> Deck | None:
        with self._db.reading() as conn:
            head = conn.execute(
                "SELECT * FROM decks WHERE deck_id = ? AND user_id = ?", (deck_id, user_id)
            ).fetchone()
            if head is None:
                return None
            rows = conn.execute(
                "SELECT zone, card_id, qty FROM deck_cards WHERE deck_id = ?", (deck_id,)
            ).fetchall()
        zones: dict[str, dict[str, int]] = {z: {} for z in ZONES}
        for row in rows:
            zones[row["zone"]][row["card_id"]] = int(row["qty"])
        return Deck.make(
            name=head["name"],
            format=head["format"],
            legend_id=head["legend_id"],
            champion_id=head["champion_id"],
            main=zones["main"],
            runes=zones["runes"],
            battlefields=sorted(zones["battlefields"]),
            sideboard=zones["sideboard"],
        )

    def save(self, deck: Deck, *, user_id: str, deck_id: str = "") -> str:
        """Insert or replace a deck. Returns its id."""
        now = utc_now_iso()
        target = deck_id or str(uuid4())
        with self._db.transaction() as conn:
            existing = conn.execute(
                "SELECT deck_id FROM decks WHERE deck_id = ? AND user_id = ?", (target, user_id)
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO decks (deck_id, user_id, name, format, legend_id, champion_id,
                                       created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (target, user_id, deck.name, deck.format, deck.legend_id,
                     deck.champion_id, now, now),
                )
            else:
                conn.execute(
                    """
                    UPDATE decks SET name = ?, format = ?, legend_id = ?, champion_id = ?,
                                     updated_at = ?
                    WHERE deck_id = ? AND user_id = ?
                    """,
                    (deck.name, deck.format, deck.legend_id, deck.champion_id, now,
                     target, user_id),
                )
            conn.execute("DELETE FROM deck_cards WHERE deck_id = ?", (target,))
            rows = [
                (target, zone, card_id, qty)
                for zone in ZONES
                for card_id, qty in (
                    {b: 1 for b in deck.battlefields}
                    if zone == ZONE_BATTLEFIELDS
                    else deck.zone(zone)
                ).items()
                if qty > 0
            ]
            conn.executemany(
                "INSERT INTO deck_cards (deck_id, zone, card_id, qty) VALUES (?, ?, ?, ?)", rows
            )
        return target

    def delete(self, deck_id: str, *, user_id: str) -> bool:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM decks WHERE deck_id = ? AND user_id = ?", (deck_id, user_id)
            )
            return cursor.rowcount > 0

    def decks_using(self, card_id: str, *, user_id: str) -> list[str]:
        """Which of this user's decks contain a card. Cheap because of the row model."""
        with self._db.reading() as conn:
            return [
                row["deck_id"]
                for row in conn.execute(
                    """
                    SELECT DISTINCT d.deck_id FROM decks d
                    JOIN deck_cards c ON c.deck_id = d.deck_id
                    WHERE d.user_id = ? AND c.card_id = ?
                    """,
                    (user_id, card_id),
                )
            ]


class CollectionRepository:
    """Owned printings, aggregated to card_id for availability."""

    def __init__(self, db: Database):
        self._db = db

    def owned_by_card(self, *, user_id: str) -> dict[str, int]:
        with self._db.reading() as conn:
            rows = conn.execute(
                """
                SELECT card_id, SUM(qty) AS total FROM collection_items
                WHERE user_id = ? GROUP BY card_id HAVING total > 0
                """,
                (user_id,),
            ).fetchall()
        return {row["card_id"]: int(row["total"]) for row in rows}

    def set_quantity(self, *, user_id: str, print_id: str, card_id: str, qty: int) -> None:
        with self._db.transaction() as conn:
            if qty <= 0:
                conn.execute(
                    "DELETE FROM collection_items WHERE user_id = ? AND print_id = ?",
                    (user_id, print_id),
                )
                return
            conn.execute(
                """
                INSERT INTO collection_items (user_id, print_id, card_id, qty, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, print_id)
                DO UPDATE SET qty = excluded.qty, updated_at = excluded.updated_at
                """,
                (user_id, print_id, card_id, int(qty), utc_now_iso()),
            )

    def total_copies(self, *, user_id: str) -> int:
        with self._db.reading() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(qty), 0) AS total FROM collection_items WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return int(row["total"])

    def clear(self, *, user_id: str) -> int:
        """Forget everything recorded about what this user owns. Returns rows removed.

        There was no way to do this at all. The wizard offers to write what a session
        learned into the collection -- which is the fastest way in by a distance -- and a
        one-way door into recording what you own is not a fair trade for that
        convenience. Someone who tried it should be able to take it back without going
        card by card, or reaching for the database.
        """
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM collection_items WHERE user_id = ?", (user_id,)
            )
            return int(cursor.rowcount or 0)


class AvailabilityRepository:
    """Persistence for the availability profile — the deck builder's lens."""

    def __init__(self, db: Database, collections: CollectionRepository):
        self._db = db
        self._collections = collections

    def load(self, *, user_id: str) -> AvailabilityProfile:
        with self._db.reading() as conn:
            head = conn.execute(
                "SELECT mode, strict, penalty FROM availability_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            exclusions = conn.execute(
                "SELECT kind, value FROM availability_exclusions WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            owned_rules = conn.execute(
                "SELECT kind, value FROM availability_owned_rules WHERE user_id = ?",
                (user_id,),
            ).fetchall()

        if head is None:
            return AvailabilityProfile.open_profile()

        mode = head["mode"]
        strict = bool(head["strict"])
        penalty = float(head["penalty"])

        if mode == MODE_COLLECTION:
            return AvailabilityProfile.from_collection(
                self._collections.owned_by_card(user_id=user_id),
                rules=[OwnedRule(kind=r["kind"], value=r["value"]) for r in owned_rules],
                strict=strict,
                penalty=penalty,
            )
        if mode == MODE_EXCLUSION:
            return AvailabilityProfile.from_exclusions(
                card_ids=[r["value"] for r in exclusions if r["kind"] == "card"],
                rules=[
                    ExclusionRule(kind=r["kind"], value=r["value"])
                    for r in exclusions
                    if r["kind"] != "card"
                ],
                strict=strict,
                penalty=penalty,
            )
        return AvailabilityProfile.open_profile()

    def save(self, profile: AvailabilityProfile, *, user_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO availability_profiles (user_id, mode, strict, penalty, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    mode = excluded.mode, strict = excluded.strict,
                    penalty = excluded.penalty, updated_at = excluded.updated_at
                """,
                (user_id, profile.mode, int(profile.strict), float(profile.penalty),
                 utc_now_iso()),
            )
            conn.execute("DELETE FROM availability_exclusions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM availability_owned_rules WHERE user_id = ?", (user_id,))
            if profile.mode == MODE_COLLECTION and profile.owned_rules:
                conn.executemany(
                    """
                    INSERT INTO availability_owned_rules (user_id, kind, value, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, kind, value) DO NOTHING
                    """,
                    [
                        (user_id, r.kind, r.value, utc_now_iso())
                        for r in profile.owned_rules
                    ],
                )
            if profile.mode == MODE_EXCLUSION:
                rows = [(user_id, "card", cid) for cid in sorted(profile.excluded_cards)]
                rows += [(user_id, r.kind, r.value) for r in profile.exclusion_rules]
                conn.executemany(
                    """
                    INSERT INTO availability_exclusions (user_id, kind, value)
                    VALUES (?, ?, ?) ON CONFLICT DO NOTHING
                    """,
                    rows,
                )


@dataclass(frozen=True)
class WizardSessionRecord:
    """A stored wizard session, ready to be turned back into a domain Session."""
    session_id: str
    legend_id: str
    phase: str
    checklists: int
    exact: dict[str, int]
    at_least: dict[str, int]
    #: Cards the player has ruled out by preference, not by ownership.
    declined: tuple[str, ...]
    asked_deck_ids: tuple[str, ...]
    saved_deck_id: str
    created_at: str
    updated_at: str


class SmartDeckRepository:
    """Wizard sessions.

    The answers are the expensive part of a session -- three deck rounds pin down
    roughly 75 cards -- so they are written every round rather than at the end. A closed
    tab costs nothing.
    """

    def __init__(self, db: Database):
        self._db = db

    def create(self, *, user_id: str, legend_id: str) -> str:
        now = utc_now_iso()
        session_id = str(uuid4())
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO wizard_sessions
                    (session_id, user_id, legend_id, phase, checklists, created_at, updated_at)
                VALUES (?, ?, ?, 'propose', 0, ?, ?)
                """,
                (session_id, user_id, legend_id, now, now),
            )
        return session_id

    def get(self, session_id: str, *, user_id: str) -> WizardSessionRecord | None:
        with self._db.reading() as conn:
            head = conn.execute(
                "SELECT * FROM wizard_sessions WHERE session_id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
            if head is None:
                return None
            knowledge = conn.execute(
                "SELECT card_id, state, qty FROM wizard_knowledge WHERE session_id = ?",
                (session_id,),
            ).fetchall()
            rounds = conn.execute(
                """
                SELECT deck_id FROM wizard_rounds
                WHERE session_id = ? AND kind = 'deck' AND deck_id <> ''
                ORDER BY round_no
                """,
                (session_id,),
            ).fetchall()
            declined = conn.execute(
                "SELECT card_id FROM wizard_declined WHERE session_id = ? ORDER BY card_id",
                (session_id,),
            ).fetchall()
        exact, at_least = {}, {}
        for row in knowledge:
            target = exact if row["state"] == "exact" else at_least
            target[row["card_id"]] = int(row["qty"])
        return WizardSessionRecord(
            session_id=head["session_id"],
            legend_id=head["legend_id"],
            phase=head["phase"],
            checklists=int(head["checklists"]),
            exact=exact,
            at_least=at_least,
            declined=tuple(r["card_id"] for r in declined),
            asked_deck_ids=tuple(r["deck_id"] for r in rounds),
            saved_deck_id=head["saved_deck_id"] or "",
            created_at=head["created_at"],
            updated_at=head["updated_at"],
        )

    def list(self, *, user_id: str, limit: int = 20) -> list[WizardSessionRecord]:
        with self._db.reading() as conn:
            ids = [
                row["session_id"]
                for row in conn.execute(
                    """
                    SELECT session_id FROM wizard_sessions
                    WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?
                    """,
                    (user_id, int(limit)),
                )
            ]
        found = (self.get(sid, user_id=user_id) for sid in ids)
        return [record for record in found if record is not None]

    def set_declined(
        self, session_id: str, *, user_id: str, declined: Iterable[str]
    ) -> None:
        """Replace the set of cards the player has ruled out.

        Replace rather than append, so taking a decline back is the same operation as
        adding one and the client never has to send a delta it might get wrong.
        """
        wanted = sorted({str(c) for c in declined if str(c)})
        now = utc_now_iso()
        with self._db.transaction() as conn:
            owned = conn.execute(
                "SELECT 1 FROM wizard_sessions WHERE session_id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
            if owned is None:
                return
            conn.execute("DELETE FROM wizard_declined WHERE session_id = ?", (session_id,))
            conn.executemany(
                "INSERT INTO wizard_declined (session_id, card_id, created_at) VALUES (?, ?, ?)",
                [(session_id, card_id, now) for card_id in wanted],
            )
            conn.execute(
                "UPDATE wizard_sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id),
            )

    def record_round(
        self,
        session_id: str,
        *,
        user_id: str,
        kind: str,
        deck_id: str,
        answers: dict[str, int],
        exact: dict[str, int],
        at_least: dict[str, int],
        phase: str,
        checklists: int,
    ) -> None:
        """Persist one answered round and the knowledge it produced.

        Knowledge is replaced wholesale rather than merged here: the domain
        :class:`Knowledge` has already done the merging, and it owns the rule for what
        an answer means. Two places deciding that is how they drift apart.
        """
        now = utc_now_iso()
        with self._db.transaction() as conn:
            owned = conn.execute(
                "SELECT 1 FROM wizard_sessions WHERE session_id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
            if owned is None:
                raise KeyError(session_id)
            row = conn.execute(
                "SELECT COALESCE(MAX(round_no), 0) AS n FROM wizard_rounds WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            round_no = int(row["n"]) + 1
            conn.execute(
                """
                INSERT INTO wizard_rounds (session_id, round_no, kind, deck_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, round_no, kind, deck_id, now),
            )
            conn.executemany(
                """
                INSERT INTO wizard_round_answers (session_id, round_no, card_id, qty)
                VALUES (?, ?, ?, ?)
                """,
                [(session_id, round_no, cid, int(n)) for cid, n in answers.items()],
            )
            conn.execute("DELETE FROM wizard_knowledge WHERE session_id = ?", (session_id,))
            conn.executemany(
                """
                INSERT INTO wizard_knowledge (session_id, card_id, state, qty)
                VALUES (?, ?, ?, ?)
                """,
                [(session_id, cid, "exact", int(n)) for cid, n in exact.items()]
                + [(session_id, cid, "at_least", int(n)) for cid, n in at_least.items()],
            )
            conn.execute(
                "UPDATE wizard_sessions SET phase = ?, checklists = ?, updated_at = ? "
                "WHERE session_id = ?",
                (phase, int(checklists), now, session_id),
            )

    def mark_saved(self, session_id: str, *, user_id: str, deck_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE wizard_sessions SET saved_deck_id = ?, phase = 'done', updated_at = ? "
                "WHERE session_id = ? AND user_id = ?",
                (deck_id, utc_now_iso(), session_id, user_id),
            )

    def clear_all(self, *, user_id: str) -> int:
        """Delete every wizard session this user has, and everything they learned.

        The answers are the point: three rounds pin down roughly 75 cards, and those rows
        say what somebody owns just as plainly as the collection does. Offering to erase
        one without the other would be a privacy control that only looks like one.
        """
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM wizard_sessions WHERE user_id = ?", (user_id,)
            )
            return int(cursor.rowcount or 0)

    def delete(self, session_id: str, *, user_id: str) -> bool:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM wizard_sessions WHERE session_id = ? AND user_id = ?",
                (session_id, user_id),
            )
            return cursor.rowcount > 0
