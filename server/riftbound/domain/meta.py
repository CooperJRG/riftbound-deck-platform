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

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

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
    """A player's finish, and how they got there.

    The match record is the richest outcome signal in the corpus and the one that went
    unread longest. Upstream publishes ``wins``/``losses``/``draws`` as integers on
    every standing; they were being formatted into a ``"3-0"`` string at ingest and
    never parsed back, so 20,783 matches sat in the snapshot behind a display field.

    They are typed here, and ``record`` is kept as the display form. :attr:`match_record`
    prefers the integers and falls back to parsing the string, so a snapshot promoted
    before this change keeps working without a re-harvest.

    What is *not* here, and cannot be: the opponent. No source records who anyone
    played, so deck performance is available and head-to-head matchups are not.
    """
    tournament_slug: str
    place: int
    player_name: str
    deck_slug: str = ""       # empty when the list was not published
    record: str = ""
    wins: int = 0
    losses: int = 0
    draws: int = 0

    @property
    def match_record(self) -> tuple[int, int, int]:
        """``(wins, losses, draws)``, from the typed fields or the legacy string."""
        if self.wins or self.losses or self.draws:
            return (max(0, self.wins), max(0, self.losses), max(0, self.draws))
        return parse_record(self.record)

    @property
    def has_record(self) -> bool:
        return self.matches > 0

    @property
    def matches(self) -> int:
        """Matches this standing represents. Zero when the source recorded none."""
        wins, losses, draws = self.match_record
        return wins + losses + draws

    @property
    def decisive(self) -> int:
        """Matches with a winner -- the denominator for a win rate. Draws are neither."""
        wins, losses, _draws = self.match_record
        return wins + losses


def parse_record(value: str) -> tuple[int, int, int]:
    """Read a ``"3-1"`` or ``"3-1-1"`` record. Anything else is no record at all.

    Only needed for snapshots written before match counts were typed; new ingests carry
    the integers. Returns zeros rather than raising, because an unreadable record means
    "we do not know", and a standing without one is an ordinary thing.
    """
    parts = str(value or "").strip().split("-")
    if len(parts) not in (2, 3):
        return (0, 0, 0)
    try:
        numbers = [int(part.strip()) for part in parts]
    except ValueError:
        return (0, 0, 0)
    if any(number < 0 for number in numbers):
        return (0, 0, 0)
    while len(numbers) < 3:
        numbers.append(0)
    return (numbers[0], numbers[1], numbers[2])


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
    return datetime.now(UTC)


def shares_champion_identity(card, legend) -> bool:
    """Could this champion have been nominated for this legend?

    Champion-tag identity only. Whether the card is *banned* is a different question and
    a moving one: a deck played before a banning nominated a champion that was legal at
    the time, and rewriting its history to suit today's list would be a worse error than
    the one this guards against. 265 archived decks nominate Draven - Vanquisher, which
    is sound identity and a later ban.
    """
    if card is None or card.super_type != "Champion":
        return False
    if legend is None or not legend.champion_tags:
        return True
    return bool(
        {t.casefold() for t in card.champion_tags}
        & {t.casefold() for t in legend.champion_tags}
    )


def reattribute_champions(decks, catalog):
    """Correct decks credited to a champion their legend could never have nominated.

    The feeds do not check the nomination they report. One list arrives as a Kennen deck
    nominating Nocturne - Horrifying -- not a Kennen champion, never a legal choice --
    while Kennen - Storm of Shuriken sits in its own main deck. Taken at face value that
    deck is counted against the wrong champion on every trend that mentions it.

    Applied on load rather than only in the normaliser, because a normaliser fix cannot
    reach decks that are already stored: a harvest carries forward everything the sources
    no longer return, which is most of the archive. Correcting it here means the archive
    is right the moment the code is, without waiting for a re-harvest that may never
    re-emit those lists.

    A deck with no nominatable champion in its main deck keeps an empty nomination rather
    than a wrong one. Empty is a gap; wrong is a claim.
    """
    out = []
    for meta_deck in decks:
        legend = catalog.get(meta_deck.deck.legend_id)
        champion = catalog.get(meta_deck.deck.champion_id)
        if shares_champion_identity(champion, legend):
            out.append(meta_deck)
            continue
        best, best_copies = "", 0
        for card_id, copies in meta_deck.deck.main.items():
            if copies > best_copies and shares_champion_identity(catalog.get(card_id), legend):
                best, best_copies = card_id, copies
        out.append(
            replace(meta_deck, deck=replace(meta_deck.deck, champion_id=best))
        )
    return out
