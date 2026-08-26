"""Ranking meta decks.

Deliberately a transparent formula rather than a learned model. v2 put a 16-expert
mixture-of-experts over 2,000 decks and could not explain a single recommendation; its
own evaluation put the synergy clusters that drove the whole architecture at a
silhouette of 0.026 — statistically indistinguishable from random. A handful of legible
terms beats that, and a player can argue with it.

Four things decide a deck's score:

**Evidence** dominates. Winning a 257-player event is a different kind of fact from
saving a deck on a website, and no amount of recency or popularity should let the second
outrank the first.

**Placement**, scaled by field size — 5th of 257 beats 1st of 9.

**Recency**, with a half-life, because a format moves. This is the term that keeps the
list current between rebuilds.

**Popularity**, weighted lowest and log-scaled, as a weak tiebreak among community decks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Iterable, Mapping

from .meta import (
    EVIDENCE_COMMUNITY,
    EVIDENCE_TOURNAMENT_ENTRY,
    EVIDENCE_TOURNAMENT_PLACED,
    MetaDeck,
)

#: Base weight per evidence tier. The gaps are wide on purpose: no combination of
#: recency and views should lift a community deck above a placed tournament deck.
EVIDENCE_WEIGHT: dict[str, float] = {
    EVIDENCE_TOURNAMENT_PLACED: 1.0,
    EVIDENCE_TOURNAMENT_ENTRY: 0.45,
    EVIDENCE_COMMUNITY: 0.15,
}

#: How fast a result stops being evidence about the *current* format.
RECENCY_HALF_LIFE_DAYS = 45.0

#: Term weights. They sum to 1 so a score is readable as a 0-1 quality estimate.
W_EVIDENCE = 0.55
W_PLACEMENT = 0.25
W_RECENCY = 0.15
W_POPULARITY = 0.05


@dataclass(frozen=True)
class ScoreBreakdown:
    """A score with its parts, so the UI can explain a ranking."""
    total: float
    evidence: float
    placement: float
    recency: float
    popularity: float

    def describe(self) -> str:
        return (
            f"evidence {self.evidence:.2f}, placement {self.placement:.2f}, "
            f"recency {self.recency:.2f}, popularity {self.popularity:.2f}"
        )


def placement_score(placement: int, field_size: int) -> float:
    """How good a finish was, relative to the field.

    Returns 0 for an unknown finish rather than guessing. Scaled by field size so a win
    in a nine-player side event does not outrank a deep run in a major.
    """
    if placement <= 0:
        return 0.0
    if field_size <= 1:
        # A finish with no field size is still evidence, just weak and unscalable.
        return 0.5 if placement == 1 else 0.25

    # Top fraction of the field, softened so the top few places stay well separated.
    fraction = 1.0 - (placement - 1) / max(1, field_size)
    sharpened = fraction ** 3

    # A small bonus for the podium, and a further one for the win, because "won it"
    # is qualitatively different from "top 8".
    if placement == 1:
        sharpened = min(1.0, sharpened + 0.15)
    elif placement <= 3:
        sharpened = min(1.0, sharpened + 0.08)

    # Bigger fields are stronger evidence at the same relative finish.
    field_factor = min(1.0, math.log10(max(10, field_size)) / 2.4)
    return max(0.0, min(1.0, sharpened * (0.6 + 0.4 * field_factor)))


def recency_score(published_at: str, *, now: datetime | None = None) -> float:
    """Exponential decay on age. Unknown dates score neutral-low rather than zero."""
    if not published_at:
        return 0.3
    try:
        when = datetime.fromisoformat(published_at)
    except ValueError:
        return 0.3
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    age_days = max(0.0, (reference - when).total_seconds() / 86400.0)
    return float(0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS))


#: Score for a deck whose source publishes no popularity signal at all. Neutral rather
#: than zero, for the same reason an unknown date is: absence of evidence must not be
#: scored as evidence of absence. Scoring it zero gave every deck from a source that
#: publishes a quality score a systematic edge over one that does not — a difference
#: between *sources*, not between decks.
NO_POPULARITY_SIGNAL = 0.3


def popularity_score(views: int, quality: float = 0.0) -> float:
    """The weakest term: how well others rate this deck.

    A curated quality score, where the source publishes one, answers that better than a
    view count, so it wins. Either way this term carries only 5% of the total and cannot
    lift a community deck past a real tournament result.
    """
    if quality > 0:
        return max(0.0, min(1.0, quality / 100.0))
    if views > 0:
        return min(1.0, math.log10(1 + views) / 3.0)  # ~1000 views saturates
    return NO_POPULARITY_SIGNAL


def score_deck(deck: MetaDeck, *, now: datetime | None = None) -> ScoreBreakdown:
    """Score one deck. Pure and explainable."""
    prov = deck.provenance
    evidence = EVIDENCE_WEIGHT.get(prov.evidence, EVIDENCE_WEIGHT[EVIDENCE_COMMUNITY])
    placement = placement_score(prov.placement, prov.field_size)
    recency = recency_score(prov.published_at or prov.tournament_date, now=now)
    popularity = popularity_score(prov.views, prov.quality)

    total = (
        W_EVIDENCE * evidence
        + W_PLACEMENT * placement
        + W_RECENCY * recency
        + W_POPULARITY * popularity
    )
    # An incomplete list is not a usable recommendation, whatever its pedigree.
    if not deck.is_complete:
        total *= 0.4
    return ScoreBreakdown(
        total=round(total, 4),
        evidence=round(evidence, 4),
        placement=round(placement, 4),
        recency=round(recency, 4),
        popularity=round(popularity, 4),
    )


def score_all(
    decks: Iterable[MetaDeck], *, now: datetime | None = None
) -> dict[str, ScoreBreakdown]:
    return {deck.deck_id: score_deck(deck, now=now) for deck in decks}


def totals(scores: Mapping[str, ScoreBreakdown]) -> dict[str, float]:
    return {deck_id: breakdown.total for deck_id, breakdown in scores.items()}
