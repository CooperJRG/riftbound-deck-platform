"""The tier list's ordering, as a number a player can read.

Three things were wrong with where this lived before.

It **lived in the client** (`web/src/features/explore.ts`), which made it the only piece
of ranking policy outside the server and the only one with no tests. The rest of this
package decides its own thresholds precisely so two clients cannot quote different
numbers for the same field.

It **had no user-facing value**. The score existed, ordered the wall, and was never
shown; a reader could see that Kennen sat above Irelia but not by how much, and the tier
letter was the only visible output of a continuous quantity.

And it **dropped everything it could not measure**. A legend with no lists in the
selected window scored `-1`, was labelled "U", and was appended in whatever order the
legend list happened to arrive in — so shortening the range from 90 days to 30 moved five
legends into an unordered heap at the bottom of the page.

---

**The scale is 0–100 and both ends mean something.** The three components are each
normalised against the field and the weights sum to 1, so the score is a percentage of
the best a legend could theoretically do: 100 is "leads the field on presence, breadth
and momentum at once", and 0 is "no lists in this window at all". Neither end is
decorative, and the parts are carried alongside the total so a card can explain itself.

**Dormant entities are ranked, not discarded.** They score 0 — they genuinely have no
presence — but they are ordered among themselves by what the wider archive still knows
about them, so the bottom of the list is an ordering rather than a heap.

**On ordering dormant entities by momentum.** Measured against the live snapshot, the
prior-window momentum of every dormant legend is exactly ``+0.00``: momentum is the
change in share between the last two usable intervals, and an entity absent from the
window has a share of zero in both, so the difference is zero by construction. It is kept
as the first sort key because it is the right signal when it does discriminate — a legend
that was climbing and then vanished should outrank one that was already flat — but
today's ordering is done by the key underneath it, prior share, which separates the same
five legends cleanly (0.67%, 0.67%, 0.35%, 0.31%, absent).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

#: Weights, carried over unchanged from the client implementation so the wall does not
#: reshuffle on the day this moved. They sum to 1, which is what makes the total
#: readable as a 0-100 rating rather than an arbitrary index.
W_PRESENCE = 0.58   # share of the published field
W_BREADTH = 0.27    # how many separate events it turned up at
W_MOMENTUM = 0.15   # which way it is moving

#: Momentum is clamped before scaling: a legend that gains five points of share in one
#: interval has told us everything a bigger number would, and without the clamp a single
#: small-sample swing would dominate a term meant to be a tiebreak.
MOMENTUM_CLAMP = 0.05

#: A legend with no computable momentum scores the middle of the band rather than the
#: bottom. Absence of evidence about direction is not evidence of decline -- scoring it
#: zero would push every thinly-played legend below every flat one for a reason that has
#: nothing to do with the legend.
MOMENTUM_UNKNOWN = 0.5

#: The curve that turns a share of the leader into something that reads like a grade.
#:
#: Presence is power-law distributed -- the leading legend holds 16% of the field and the
#: fifth-placed one 4.5% -- so a rating measured linearly against the leader crushes
#: everybody else into the bottom quarter of the scale. Measured on the live snapshot,
#: the raw weighted score had a median of 18 and put the fifth-best legend in the format
#: at 37, which reads as a failing mark for a deck that is doing well.
#:
#: The fix is a presentation curve, applied to the total:
#:
#:     rating = 100 * (raw / 100) ** GRADE_CURVE
#:
#: measured across three windows (30 / 90 / 365 days):
#:
#:   k       Kai'Sa (5th, 9th, 6th)      median         floor
#:   1.00      37 /  39 /  63            18 / 19 / 20    8
#:   0.40      67 /  69 /  83            51 / 51 / 53   37
#:   0.35      71 /  72 /  85            55 / 56 / 57   42
#:   0.30      74 /  75 /  87            60 / 61 / 62   47
#:   0.25      78 /  79 /  89            65 / 66 / 67   54
#:
#: 0.30 is the shallowest curve that clears a comfortable margin rather than landing on
#: the line, which matters because the underlying shares move with every harvest.
#:
#: **Applied to the total, never to the components.** Curving each component separately
#: compresses presence and breadth by different amounts, which silently re-weights them
#: against each other -- measured, it reordered 18 of 44 legends. A monotonic curve on
#: the total cannot change the order at all, so this is a change of scale and nothing
#: else. The parts are then scaled by the same factor, so they still sum to the total and
#: a card explaining itself stays arithmetically honest.
#:
#: Both endpoints survive: a raw 100 curves to 100, and a raw 0 to 0.
GRADE_CURVE = 0.30


def grade(raw: float) -> float:
    """Remap a raw 0-100 weighted score onto the grade-like scale."""
    if raw <= 0:
        return 0.0
    return 100.0 * (min(raw, 100.0) / 100.0) ** GRADE_CURVE

#: Tier cut points as fractions of the ranked field, and the letter each opens.
#:
#: Proportions rather than score thresholds, so the shape of the wall holds whatever the
#: date range returns. Note the consequence, which is visible in the live data: the cut
#: falls wherever the fraction lands, so two legends either side of a boundary can be
#: a thousandth of a point apart. The tier is a reading aid; the score is the ranking.
TIER_CUTS: tuple[tuple[float, str], ...] = (
    (0.12, "S"),
    (0.32, "A"),
    (0.58, "B"),
    (0.80, "C"),
)
TIER_LAST = "D"

#: Every tier letter, strongest first. Exported so a client renders the rows in a fixed
#: order instead of discovering them from the data and dropping the empty ones.
TIER_ORDER: tuple[str, ...] = (*(letter for _cut, letter in TIER_CUTS), TIER_LAST)


def momentum_points(momentum: float | None) -> float:
    """Momentum mapped onto 0..1. ``None`` lands in the middle, not at the bottom."""
    if momentum is None:
        return MOMENTUM_UNKNOWN
    clamped = max(-MOMENTUM_CLAMP, min(MOMENTUM_CLAMP, momentum))
    return (clamped + MOMENTUM_CLAMP) / (2 * MOMENTUM_CLAMP)


@dataclass(frozen=True)
class Candidate:
    """One entity's inputs to the ranking, gathered from wherever they came from."""
    entity_id: str
    name: str
    share: float
    event_count: int
    momentum: float | None
    #: True when the entity had at least one list inside the requested window. False
    #: means dormant: scored 0, ordered by the prior-evidence fields below.
    ranked: bool = True
    #: What the wider archive still knows, used only to order dormant entities.
    prior_share: float = 0.0
    prior_momentum: float | None = None
    last_seen: str = ""


@dataclass(frozen=True)
class Rank:
    """Where an entity placed, and enough of the arithmetic to explain it."""
    entity_id: str
    position: int           # 1-based, across the whole field
    score: float            # 0-100
    tier: str
    ranked: bool
    presence_points: float  # the three components, each already scaled to the 0-100 total
    breadth_points: float
    momentum_points: float
    prior_share: float
    prior_momentum: float | None
    last_seen: str

    @property
    def summary(self) -> str:
        """:meth:`describe`, as a field the API layer can read straight off."""
        return self.describe()

    def describe(self) -> str:
        """One line a card can show under the number."""
        if not self.ranked:
            if self.last_seen:
                return f"No lists in this range — last seen {self.last_seen}"
            return "No lists in this range"
        return (
            f"{self.score:.0f} of 100 — presence {self.presence_points:.0f}, "
            f"events {self.breadth_points:.0f}, momentum {self.momentum_points:.0f}"
        )


def tier_for(position: int, total: int) -> str:
    """The tier letter for a 1-based position in a field of ``total``."""
    if total <= 0:
        return TIER_LAST
    fraction = (position - 1) / total
    for cut, letter in TIER_CUTS:
        if fraction < cut:
            return letter
    return TIER_LAST


def rank_entities(candidates: Sequence[Candidate]) -> dict[str, Rank]:
    """Score and order a field, keyed by entity id.

    Ranked entities are scored against the field's own maxima, so the leader sets the
    top of the presence and breadth scales. Dormant entities take 0 and sort below every
    ranked one, ordered by what the archive still knows about them.

    Ties are broken by name so a rebuild of the same snapshot produces the same wall --
    without it the order depended on dictionary iteration, which is stable within a
    process and not across a restart.
    """
    ranked = [c for c in candidates if c.ranked]
    dormant = [c for c in candidates if not c.ranked]

    # Guard the denominators: an empty field, or one where every entity has a zero
    # share, must not divide by zero and must not hand everybody a perfect score.
    max_share = max((c.share for c in ranked), default=0.0) or 1.0
    max_events = max((c.event_count for c in ranked), default=0) or 1

    scored: list[tuple[Candidate, float, float, float]] = []
    for candidate in ranked:
        presence = (candidate.share / max_share) * W_PRESENCE * 100
        breadth = (candidate.event_count / max_events) * W_BREADTH * 100
        movement = momentum_points(candidate.momentum) * W_MOMENTUM * 100
        scored.append((candidate, presence, breadth, movement))

    scored.sort(key=lambda row: (-(row[1] + row[2] + row[3]), row[0].name))
    # Momentum first because that is the signal asked for; share underneath it because
    # that is the signal that currently separates them. Recency last, so a legend nobody
    # has played for eight months sits below one that dropped out last week.
    dormant_sorted = sorted(
        dormant,
        key=lambda c: (
            -(c.prior_momentum if c.prior_momentum is not None else 0.0),
            -c.prior_share,
            _recency_key(c.last_seen),
            c.name,
        ),
    )

    total = len(scored) + len(dormant_sorted)
    out: dict[str, Rank] = {}

    for index, (candidate, presence, breadth, movement) in enumerate(scored, start=1):
        raw = presence + breadth + movement
        rating = grade(raw)
        # The components carry the same curve as the total, so the breakdown a card
        # prints still adds up to the number above it.
        lift = rating / raw if raw > 0 else 0.0
        out[candidate.entity_id] = Rank(
            entity_id=candidate.entity_id,
            position=index,
            score=round(rating, 1),
            tier=tier_for(index, total),
            ranked=True,
            presence_points=round(presence * lift, 1),
            breadth_points=round(breadth * lift, 1),
            momentum_points=round(movement * lift, 1),
            prior_share=candidate.prior_share,
            prior_momentum=candidate.prior_momentum,
            last_seen=candidate.last_seen,
        )

    for offset, candidate in enumerate(dormant_sorted, start=1):
        position = len(scored) + offset
        out[candidate.entity_id] = Rank(
            entity_id=candidate.entity_id,
            position=position,
            score=0.0,
            # Always the bottom tier, never a percentile of it. Scoring zero *is* the
            # minimum, so the minimum tier is where it belongs -- and in a field small
            # enough for the bottom 20% to be one row, a percentile would otherwise put
            # an entity with no lists at all into B.
            tier=TIER_LAST,
            ranked=False,
            presence_points=0.0,
            breadth_points=0.0,
            momentum_points=0.0,
            prior_share=candidate.prior_share,
            prior_momentum=candidate.prior_momentum,
            last_seen=candidate.last_seen,
        )
    return out


def _recency_key(value: str) -> int:
    """Ascending sort key that puts the most recent first and the never-seen last.

    Negated day numbers rather than the ISO string, because the whole key tuple sorts
    ascending and a missing date has to land *after* every real one -- where an empty
    string would sort before them all.
    """
    try:
        return -date.fromisoformat(value).toordinal()
    except (TypeError, ValueError):
        return 0
