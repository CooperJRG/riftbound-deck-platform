"""Repositories: decks, collections, availability profiles."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from ..domain.availability import (
    AvailabilityProfile,
    ExclusionRule,
    MODE_COLLECTION,
    MODE_EXCLUSION,
    MODE_OPEN,
)
from ..domain.deck import Deck, ZONE_BATTLEFIELDS, ZONES
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

        if head is None:
            return AvailabilityProfile.open_profile()

        mode = head["mode"]
        strict = bool(head["strict"])
        penalty = float(head["penalty"])

        if mode == MODE_COLLECTION:
            return AvailabilityProfile.from_collection(
                self._collections.owned_by_card(user_id=user_id), strict=strict, penalty=penalty
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
