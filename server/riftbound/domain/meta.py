"""The competitive meta: tournaments, published decks, and how much to trust them.

The honest constraint this module is built around: **evidence quality varies enormously
between decks, and pretending otherwise is how a meta list becomes noise.**

Measured against the live sources:

* 30 tournaments are available with full standings — placements, player counts, records.
* Only about **1%** of those standings carry a decklist slug, and the ones that do are
  rarely the winners. Tournament *results* are rich; tournament *lists* are sparse.
* The public deck pool is large (5,000+ slugs) but roughly **14%** are public with a
  complete list. The rest are scratch decks people saved and abandoned.

So a deck's rank is driven by what backs it, not just by how recently it appeared.
:class:`Evidence` makes that tier explicit and it is carried all the way to the UI, so a
player can see *why* a deck is being recommended.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Mapping

from .cards import Catalog
from .deck import Deck

# Evidence tiers, strongest first. A deck is only ever placed in a tier the source data
# actually supports.
EVIDENCE_TOURNAMENT_PLACED = "tournament-placed"   # known finish in a known event
EVIDENCE_TOURNAMENT_ENTRY = "tournament-entry"     # played in an event, finish unknown
EVIDENCE_COMMUNITY = "community"                   # published deck, no event backing
EVIDENCE_TIERS = (
    EVIDENCE_TOURNAMENT_PLACED,
    EVIDENCE_TOURNAMENT_ENTRY,
    EVIDENCE_COMMUNITY,
)


@dataclass(frozen=True)
class Tournament:
    """One event. Results exist even when no decklist does."""
    tournament_id: str
    slug: str
    name: str
    date: str                 # ISO date
    format: str
    players: int
    organizer: str = ""
    winner: str = ""
    decks_published: int = 0  # standings that carried a decklist

    @property
    def timestamp(self) -> float:
        try:
            return datetime.fromisoformat(self.date).timestamp()
        except ValueError:
            return 0.0


@dataclass(frozen=True)
class Standing:
    """A player's finish. Present far more often than their decklist."""
    tournament_slug: str
    place: int
    player_name: str
    deck_slug: str = ""       # empty when the list was not published
    record: str = ""


@dataclass(frozen=True)
class Provenance:
    """Where a deck came from and what backs it."""
    source: str                       # "dotgg"
    source_slug: str
    url: str
    published_at: str = ""            # ISO date
    author: str = ""
    views: int = 0
    #: A 0-100 quality score where the source publishes one. A better popularity signal
    #: than a view count, but still only a tiebreak — it never outranks real evidence.
    quality: float = 0.0
    evidence: str = EVIDENCE_COMMUNITY
    tournament_slug: str = ""
    tournament_name: str = ""
    tournament_date: str = ""
    placement: int = 0                # 1 = won it; 0 = unknown
    field_size: int = 0               # players in the event

    @property
    def is_tournament(self) -> bool:
        return self.evidence in (EVIDENCE_TOURNAMENT_PLACED, EVIDENCE_TOURNAMENT_ENTRY)

    def describe(self) -> str:
        """One line a player can read to judge the deck's pedigree."""
        if self.evidence == EVIDENCE_TOURNAMENT_PLACED:
            place = _ordinal(self.placement)
            field = f" of {self.field_size}" if self.field_size else ""
            return f"{place}{field} at {self.tournament_name}"
        if self.evidence == EVIDENCE_TOURNAMENT_ENTRY:
            return f"Played at {self.tournament_name}"
        if self.quality:
            return f"Community deck · quality {self.quality:.0f}"
        return "Community deck" + (f" · {self.views} views" if self.views else "")


def _ordinal(n: int) -> str:
    if n <= 0:
        return "Unplaced"
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


@dataclass(frozen=True)
class MetaDeck:
    """A published deck plus where it came from.

    The deck itself is an ordinary :class:`Deck`, so everything that already works —
    validation, availability coverage, importing it into the builder — works unchanged.
    """
    deck: Deck
    provenance: Provenance
    #: Card codes the current bundle could not resolve. Reported, never dropped, so a
    #: list referencing an unreleased card is visibly incomplete rather than quietly wrong.
    unresolved: tuple[str, ...] = ()

    @property
    def deck_id(self) -> str:
        return self.provenance.source_slug

    @property
    def archetype_id(self) -> str:
        """Decks are grouped by their legend and chosen champion.

        That pairing is what a Riftbound player means by "a deck" — it fixes the domain
        identity and the core win condition — and unlike a scraped archetype label it
        needs no upstream field that might vanish.
        """
        return archetype_id_for(self.deck.legend_id, self.deck.champion_id)

    @property
    def is_complete(self) -> bool:
        return not self.unresolved and self.deck.main_total > 0


def archetype_id_for(legend_id: str, champion_id: str) -> str:
    legend = (legend_id or "unknown").strip().lower()
    champion = (champion_id or "").strip().lower()
    return f"{legend}::{champion}" if champion else legend


@dataclass(frozen=True)
class Archetype:
    """A legend + champion pairing, with the decks that back it."""
    archetype_id: str
    legend_id: str
    champion_id: str
    name: str
    deck_count: int
    tournament_deck_count: int
    best_placement: int          # 0 when never placed
    #: Field size of the event that best placement came from. A placement without it is
    #: meaningless — "111th" is a top-5% finish at a 2,224-player regional and a poor
    #: one at a 120-player local.
    best_field_size: int
    latest_date: str
    score: float
    decks: tuple[MetaDeck, ...] = field(default_factory=tuple)

    @property
    def has_tournament_backing(self) -> bool:
        return self.tournament_deck_count > 0


def build_archetypes(
    decks: Iterable[MetaDeck], *, catalog: Catalog, scores: Mapping[str, float]
) -> list[Archetype]:
    """Group decks into archetypes, ordered by their strongest evidence."""
    groups: dict[str, list[MetaDeck]] = {}
    for deck in decks:
        groups.setdefault(deck.archetype_id, []).append(deck)

    out: list[Archetype] = []
    for archetype_id, members in groups.items():
        first = members[0]
        legend = catalog.get(first.deck.legend_id)
        champion = catalog.get(first.deck.champion_id)
        name = " · ".join(
            part for part in (
                legend.name if legend else first.deck.legend_id or "Unknown legend",
                champion.name if champion else "",
            ) if part
        )
        placed = [m for m in members if m.provenance.placement > 0]
        # "Best" is the strongest *relative* finish, not the smallest number.
        best = min(
            placed,
            key=lambda m: m.provenance.placement / max(1, m.provenance.field_size),
            default=None,
        )
        ranked = sorted(members, key=lambda m: scores.get(m.deck_id, 0.0), reverse=True)
        out.append(
            Archetype(
                archetype_id=archetype_id,
                legend_id=first.deck.legend_id,
                champion_id=first.deck.champion_id,
                name=name,
                deck_count=len(members),
                tournament_deck_count=sum(1 for m in members if m.provenance.is_tournament),
                best_placement=best.provenance.placement if best else 0,
                best_field_size=best.provenance.field_size if best else 0,
                latest_date=max(
                    (m.provenance.published_at for m in members if m.provenance.published_at),
                    default="",
                ),
                # An archetype is as strong as its best-evidenced deck, not the sum of
                # its scratch copies — otherwise a popular starter list outranks a
                # tournament winner purely on volume.
                score=max((scores.get(m.deck_id, 0.0) for m in members), default=0.0),
                decks=tuple(ranked),
            )
        )
    out.sort(key=lambda a: a.score, reverse=True)
    return out


def utc_today() -> datetime:
    return datetime.now(timezone.utc)
