"""What the meta knows about one legend.

Everything Smart Decks needs to be *smart* is derived here, from real decks, with no
model to train and nothing that cannot be shown to a player:

* **play rate and copies** — how often the field plays a card for this legend and how
  many it runs. This is the preference signal the constructor fills from, and it is why
  a built deck takes three of a staple and one of a situational card.
* **clusters** — decks for one legend overlap heavily (median Jaccard 0.57 measured
  across the snapshot), so they fall into a handful of families. Each has a **core** that
  defines it and **flex** slots that vary. Repairs swap flex, never core, which is what
  keeps a repaired deck recognisably the deck that won.
* **affinity** — how often a card is played alongside a given set. Ranks substitutes by
  what the field actually pairs together rather than by raw power.
* **roles** — card type plus cost band, the last-resort bucket when nothing in the meta
  fits and a slot still needs filling.

Weighted by deck score throughout, so a card played in tournament-winning lists counts
for more than one played in an also-ran.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from .cards import Catalog
from .deck_builder import Preference
from .eras import Era
from .meta import MetaDeck

#: Two decks belong to the same family above this main-deck overlap. Chosen from the
#: measured distribution: the median pair sits at 0.57 and the p90 near 0.85, so 0.62
#: separates "the same deck with different flex" from "a different plan entirely".
CLUSTER_THRESHOLD = 0.62

#: A card is part of a cluster's identity when this much of the cluster plays it.
CORE_SHARE = 0.8

#: Archetype coherence is **not** applied when filling a deck, and this is the record of
#: why -- because the obvious change is to put it back.
#:
#: There used to be a ``CLUSTER_BOOST`` here that promoted a chosen family's cards above
#: the legend's general staples, and :meth:`LegendProfile.preference` took a cluster to
#: apply it. It did nothing: the boost multiplies ``play_rate``, and ``COHERENCE_WEIGHT``
#: leaves ``play_rate`` carrying 10% of a pick, measured never enough to flip a decision.
#:
#: Fixing it was worse than leaving it. Judged by ``deck_fidelity`` -- overlap with the
#: real lists of the current era -- every way of making the family matter more made the
#: deck less like the ones people actually play:
#:
#:   no cluster at all                    0.888
#:   the shipped boost                    0.879
#:   family used as the candidate pool     0.884
#:   coherence routed through the pairing term, at rising strength:
#:     x1  0.880   x3  0.877   x10  0.866   x30  0.864
#:
#: Monotonic in the wrong direction. And the harm lands where the old docstring claimed
#: protection: legends with fewer than 20 published lists scored 0.777 under the boost
#: against 0.806 without it.
#:
#: The reading is that greedy Jaccard families are not sharp enough to steer a build, and
#: that the pairing signal already carries archetype coherence better than a cluster label
#: does -- a card that belongs to the plan is a card the field plays alongside the plan.
#: Clusters keep their place in *selection* (which deck to show, which swap to offer);
#: they have no place in *construction*.

#: How much a same-type, same-cost-band card is worth when nothing better is owned.
#: Small on purpose: it should never outrank a card the field actually plays here.
ROLE_MATCH_BONUS = 0.05

#: Cost bands for role matching. A three-drop can stand in for a two-drop; it cannot
#: stand in for a seven-drop.
COST_BANDS: tuple[tuple[int, int], ...] = ((0, 2), (3, 4), (5, 6), (7, 99))


def cost_band(cost: int | None) -> tuple[int, int]:
    value = 0 if cost is None else int(cost)
    for band in COST_BANDS:
        if band[0] <= value <= band[1]:
            return band
    return COST_BANDS[-1]


@dataclass(frozen=True)
class Cluster:
    """A family of decks that share a plan."""
    cluster_id: str
    deck_ids: tuple[str, ...]
    core: frozenset[str]
    flex: frozenset[str]
    score: float

    @property
    def size(self) -> int:
        return len(self.deck_ids)


@dataclass(frozen=True)
class LegendProfile:
    """Everything the meta says about building with one legend."""
    legend_id: str
    deck_count: int
    play_rate: Mapping[str, float]
    copies: Mapping[str, int]
    clusters: tuple[Cluster, ...]
    #: The format era this profile's evidence comes from. Normally the current one; a
    #: legend with no lists since the last ban falls back to the whole archive and says
    #: so here, because a deck built from a format nobody plays is a different claim and
    #: the player is entitled to know which they are holding.
    era_id: str = ""
    _pair_counts: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    _card_weight: Mapping[str, float] = field(default_factory=dict)
    _total_weight: float = 0.0

    def preference(self) -> Preference:
        """The signal :func:`deck_builder.build` fills from.

        Play rate ranks which cards to reach for, copies says how many, and the pairing
        function decides everything else -- it carries 90% of each pick. There is
        deliberately no archetype argument; see the note above ``CORE_SHARE`` for the
        measurements that removed it.
        """
        return Preference(
            play_rate=self.play_rate, copies=self.copies, pair=self.pair_strength
        )

    def pair_strength(self, card_id: str, partner_id: str) -> float:
        """How often the field plays `card_id` in decks that contain `partner_id`.

        The single-partner term behind :meth:`affinity`, exposed so a builder can keep a
        running total instead of recomputing the average on every pick.
        """
        weight = self._card_weight.get(partner_id, 0.0)
        if weight <= 0:
            return 0.0
        return self._pair_counts.get(card_id, {}).get(partner_id, 0.0) / weight

    def coverage(self, cluster: Cluster, owned: Mapping[str, int]) -> float:
        """How much of a family's defining core this collection can actually field.

        Partial credit per card, because two of a three-of is most of the way there and
        scoring it as zero would discard a deck the player can very nearly play.
        """
        if not cluster.core:
            return 0.0
        total = 0.0
        for card_id in cluster.core:
            want = max(1, self.copies.get(card_id, 1))
            total += min(1.0, owned.get(card_id, 0) / want)
        return total / len(cluster.core)

    def cluster_of(self, deck_id: str) -> Cluster | None:
        return next((c for c in self.clusters if deck_id in c.deck_ids), None)

    def affinity(self, card_id: str, given: Iterable[str]) -> float:
        """How often this card shows up alongside the given cards, 0..1.

        Averaged conditional probability rather than raw co-occurrence, so a staple
        played in every deck does not dominate simply by being common.
        """
        partners = [c for c in given if c != card_id]
        if not partners:
            return self.play_rate.get(card_id, 0.0)
        together = self._pair_counts.get(card_id, {})
        total = 0.0
        for partner in partners:
            weight = self._card_weight.get(partner, 0.0)
            if weight > 0:
                total += together.get(partner, 0.0) / weight
        return total / len(partners)

    def lift(self, card_id: str, given: Iterable[str]) -> float:
        """Affinity relative to how often the card is played at all.

        Above 1 means the field pairs these deliberately; near 1 means coincidence.
        Kept separate from :meth:`affinity` because a UI explaining a substitution wants
        "played together more than chance", not a bare probability.
        """
        base = self.play_rate.get(card_id, 0.0)
        if base <= 0:
            return 0.0
        return self.affinity(card_id, given) / base


@dataclass(frozen=True)
class LegendIndex:
    """Profiles for every legend the meta has decks for."""
    profiles: Mapping[str, LegendProfile]

    def get(self, legend_id: str) -> LegendProfile | None:
        return self.profiles.get(legend_id)

    def legends(self) -> tuple[str, ...]:
        return tuple(
            sorted(self.profiles, key=lambda k: -self.profiles[k].deck_count)
        )

    def preference_for(self, legend_id: str) -> Preference:
        profile = self.get(legend_id)
        return profile.preference() if profile else Preference.empty()


def _deck_cards(deck: MetaDeck) -> dict[str, int]:
    """Every card a deck plays, across zones, with copies."""
    counts = dict(deck.deck.main)
    for card_id, qty in deck.deck.runes.items():
        counts[card_id] = counts.get(card_id, 0) + qty
    for card_id in deck.deck.battlefields:
        counts[card_id] = counts.get(card_id, 0) + 1
    return counts


def _jaccard(a: Sequence[str] | set[str], b: Sequence[str] | set[str]) -> float:
    left, right = set(a), set(b)
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _cluster(
    decks: Sequence[MetaDeck], scores: Mapping[str, float]
) -> tuple[Cluster, ...]:
    """Group decks into families, best-scoring deck seeding each.

    Greedy rather than agglomerative: with a few hundred decks per legend it is fast,
    deterministic, and — more useful — each cluster has an obvious representative, which
    is the deck the wizard shows.
    """
    unassigned = sorted(decks, key=lambda d: (-scores.get(d.deck_id, 0.0), d.deck_id))
    clusters: list[Cluster] = []

    while unassigned:
        seed = unassigned[0]
        seed_cards = set(seed.deck.main)
        members = [d for d in unassigned if _jaccard(seed_cards, set(d.deck.main)) >= CLUSTER_THRESHOLD]
        if seed not in members:
            members.append(seed)
        member_ids = {d.deck_id for d in members}
        unassigned = [d for d in unassigned if d.deck_id not in member_ids]

        played = defaultdict(int)
        for deck in members:
            for card_id in deck.deck.main:
                played[card_id] += 1
        core = frozenset(c for c, n in played.items() if n >= CORE_SHARE * len(members))
        flex = frozenset(played) - core
        clusters.append(
            Cluster(
                cluster_id=seed.deck_id,
                deck_ids=tuple(d.deck_id for d in members),
                core=core,
                flex=flex,
                score=max(scores.get(d.deck_id, 0.0) for d in members),
            )
        )
    clusters.sort(key=lambda c: (-c.score, -c.size, c.cluster_id))
    return tuple(clusters)


def build_profile(
    legend_id: str,
    decks: Sequence[MetaDeck],
    scores: Mapping[str, float],
    *,
    era_id: str = "",
) -> LegendProfile:
    """Summarise what the meta plays with one legend."""
    weights = {d.deck_id: max(1e-6, scores.get(d.deck_id, 0.0)) for d in decks}
    total = sum(weights.values())

    played_weight: dict[str, float] = defaultdict(float)
    copy_weight: dict[str, float] = defaultdict(float)
    pairs: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for deck in decks:
        weight = weights[deck.deck_id]
        cards = _deck_cards(deck)
        for card_id, copies in cards.items():
            played_weight[card_id] += weight
            copy_weight[card_id] += weight * copies
        # Main-deck pairs only: runes and battlefields co-occur with everything and
        # would flatten the signal.
        main = list(deck.deck.main)
        for i, left in enumerate(main):
            for right in main[i + 1:]:
                pairs[left][right] += weight
                pairs[right][left] += weight

    play_rate = {c: w / total for c, w in played_weight.items()} if total else {}
    copies = {
        c: max(1, round(copy_weight[c] / played_weight[c]))
        for c in played_weight
        if played_weight[c] > 0
    }

    return LegendProfile(
        legend_id=legend_id,
        deck_count=len(decks),
        era_id=era_id,
        play_rate=play_rate,
        copies=copies,
        clusters=_cluster(decks, scores),
        _pair_counts={k: dict(v) for k, v in pairs.items()},
        _card_weight=dict(played_weight),
        _total_weight=total,
    )


def build_index(
    decks: Iterable[MetaDeck], scores: Mapping[str, float], *, era_id: str = ""
) -> LegendIndex:
    """Profile every legend present in a meta snapshot."""
    by_legend: dict[str, list[MetaDeck]] = defaultdict(list)
    for deck in decks:
        if deck.deck.legend_id:
            by_legend[deck.deck.legend_id].append(deck)
    return LegendIndex(
        profiles={
            legend_id: build_profile(legend_id, group, scores, era_id=era_id)
            for legend_id, group in by_legend.items()
        }
    )


def build_scoped_index(
    decks: Sequence[MetaDeck], scores: Mapping[str, float], era: Era
) -> LegendIndex:
    """Profile every legend from **one era's** evidence, falling back only when there is
    none at all.

    The archive spans a banning, and a third of it describes a format that no longer
    exists. Built over everything, the signal this index carries -- play rates, clusters,
    the pairing counts a deck is filled from -- is an average of two formats, and the
    builder hands the player the average. Measured against the real lists of the current
    era, scoping the index moved the closest-match score from 0.837 to 0.879 and changed
    the deck for 43-54% of collections; for Annie the built deck was 68% different.

    **There is no evidence threshold, and that was a surprise worth recording.** The
    obvious design is to keep the all-time signal for legends with only a handful of
    recent lists. Measured, that is strictly worse: requiring 10 era decks before
    trusting them drops the closest match to 0.875, requiring 30 drops it to 0.855 and
    cuts the improved legends from 17 to 7. Eight current lists describe the current
    format better than thirty-seven pre-ban ones do. So the only fallback is the
    degenerate case -- a legend with *nothing* in this era, where there is no signal to
    prefer -- and that profile is tagged with ``era_id="all"`` rather than quietly
    passing as current.
    """
    scoped: list[MetaDeck] = []
    for deck in decks:
        when = deck.provenance.tournament_date or deck.provenance.published_at
        if era.era_id == "all" or era.contains(when):
            scoped.append(deck)

    current = build_index(scoped, scores, era_id=era.era_id)
    if era.era_id == "all":
        return current

    missing = build_index(
        [d for d in decks if d.deck.legend_id not in current.profiles],
        scores,
        era_id="all",
    )
    return LegendIndex(profiles={**missing.profiles, **current.profiles})


def role_of(card_id: str, catalog: Catalog) -> tuple[str, tuple[int, int]]:
    """The bucket a card can be substituted within when the meta offers nothing."""
    card = catalog.get(card_id)
    if card is None:
        return ("", COST_BANDS[-1])
    return (card.card_type, cost_band(card.cost))


def substitutes(
    hole: str,
    *,
    profile: LegendProfile,
    owned: Mapping[str, int],
    catalog: Catalog,
    context: Iterable[str],
    exclude: Iterable[str] = (),
) -> list[tuple[str, float]]:
    """Owned cards that could stand in for `hole`, best first.

    Ranked by how often the field plays them alongside the deck's existing cards, then
    by whether they fill the same role. Returns `(card_id, score)` so a caller can show
    *why* a swap was chosen.
    """
    banned = set(exclude)
    context_set = [c for c in context if c != hole]
    target_role = role_of(hole, catalog)

    ranked: list[tuple[str, float]] = []
    for card_id, count in owned.items():
        if count <= 0 or card_id == hole or card_id in banned:
            continue
        affinity = profile.affinity(card_id, context_set)
        same_role = role_of(card_id, catalog) == target_role
        if affinity <= 0 and profile.play_rate.get(card_id, 0.0) <= 0 and not same_role:
            # No meta history and the wrong shape: nothing recommends it.
            continue
        # Role match is the last resort, and it is worth having. A card the meta has
        # never played is still a legal card of the right type and cost, and a deck
        # that is one slot short is worth more to a player than a deck they cannot
        # build. It ranks below anything with real evidence behind it.
        ranked.append((card_id, affinity + (ROLE_MATCH_BONUS if same_role else 0.0)))
    ranked.sort(key=lambda row: (-row[1], row[0]))
    return ranked
