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
from dataclasses import dataclass, field
import math
from typing import Iterable, Mapping, Sequence

from .cards import Catalog
from .deck_builder import Preference
from .meta import MetaDeck

#: Two decks belong to the same family above this main-deck overlap. Chosen from the
#: measured distribution: the median pair sits at 0.57 and the p90 near 0.85, so 0.62
#: separates "the same deck with different flex" from "a different plan entirely".
CLUSTER_THRESHOLD = 0.62

#: A card is part of a cluster's identity when this much of the cluster plays it.
CORE_SHARE = 0.8

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
    _pair_counts: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    _card_weight: Mapping[str, float] = field(default_factory=dict)
    _total_weight: float = 0.0

    def preference(self) -> Preference:
        """The signal :func:`deck_builder.build` fills from."""
        return Preference(play_rate=self.play_rate, copies=self.copies)

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
    legend_id: str, decks: Sequence[MetaDeck], scores: Mapping[str, float]
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
        play_rate=play_rate,
        copies=copies,
        clusters=_cluster(decks, scores),
        _pair_counts={k: dict(v) for k, v in pairs.items()},
        _card_weight=dict(played_weight),
        _total_weight=total,
    )


def build_index(
    decks: Iterable[MetaDeck], scores: Mapping[str, float]
) -> LegendIndex:
    """Profile every legend present in a meta snapshot."""
    by_legend: dict[str, list[MetaDeck]] = defaultdict(list)
    for deck in decks:
        if deck.deck.legend_id:
            by_legend[deck.deck.legend_id].append(deck)
    return LegendIndex(
        profiles={
            legend_id: build_profile(legend_id, group, scores)
            for legend_id, group in by_legend.items()
        }
    )


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
