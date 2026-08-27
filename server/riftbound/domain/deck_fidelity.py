"""Does the deck we build resemble the deck the format actually plays?

The gap this fills. `smart_decks_harness` measures whether a legal deck can be *found* —
solved-when-feasible, rounds to answer, false negatives. All of that can be perfect while
the deck handed over is a good answer to last season's format. Nothing measured quality,
so nothing would have caught the builder's preference signal going stale.

The measure is deliberately blunt: build a deck, then compare it to the **real published
lists for that legend in the era being claimed**. Two numbers, because they answer
different questions:

* **best match** — how close we get to the single closest real list. This is "did we
  rediscover a deck somebody is actually winning with".
* **mean match** — average overlap across every real list for that legend. This is "are
  we in the right neighbourhood", and it is the more honest of the two, because a
  best-match can be flattered by one outlier list.

Jaccard over the main-deck card set, not over copies. Two lists that differ only in
whether a situational card is a 2-of or a 3-of are the same deck, and a metric that
called them different would spend its sensitivity on noise.

**A raw score cannot be read on its own, and the first version of this module invited
exactly that mistake.** It printed the legends with the lowest match as "furthest from the
field", which read as a list of the builder's failures. It was not. Renata Glasc scored
0.58 — the worst on the page — while Renata's own ten published lists agree with each
other only 0.34 of the time. There is no single Renata deck to match; ranked against what
is *achievable*, 0.58 was the strongest relative result in the format.

Measured across the field, the correlation between how much a legend's real lists agree
with each other and how well we match one of them is **+0.730**. A raw score is mostly a
measurement of how fragmented that legend's field is.

So every row carries its **ceiling**: how well a real list matches its own nearest real
peer. ``margin`` is the difference, and it is the number to read. We clear the ceiling on
**45 of 47** legends by an average of +0.132; the two that fall short — Irelia at -5% over
245 lists and Fiora at -4% over 67 — are the only entries on this report that are actually
about the builder, and neither appeared anywhere near the top of the raw list.

A negative margin is the failure signal: it means we built something less like the field
than the field is like itself.

**What this still cannot tell you.** It measures conformity, not strength. A builder that
copied the single most-played list every time would score near 1.0 and be useless to a
player who cannot field it. It is a regression guard on the *signal* — evidence going
stale, a weighting change quietly reshaping every deck — and it should never be optimised
against directly. That is why the acceptance run reports it beside the Smart Decks numbers
rather than replacing them.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .cards import Catalog
from .deck import Deck
from .deck_builder import build, copy_cap, legal_main_pool, legal_zone_pool
from .legend_index import LegendIndex
from .meta import MetaDeck
from .rules import BoundRules

#: Real lists a legend needs before its fidelity is worth measuring. Below this the
#: "field" it is being compared against is one or two decks, and the number says more
#: about those decks than about the builder.
MIN_REAL_LISTS = 5


@dataclass(frozen=True)
class LegendFidelity:
    """How closely one legend's built deck matches what the field plays."""
    legend_id: str
    name: str
    real_lists: int
    best_match: float
    mean_match: float
    #: What a *real* list scores by the same measure: the average, over this legend's
    #: published lists, of how well each matches its nearest peer. The achievable bar.
    ceiling: float = 0.0

    @property
    def margin(self) -> float:
        """How far above the achievable bar we sit. Negative is the failure signal."""
        return self.best_match - self.ceiling

    def describe(self) -> str:
        return (
            f"{self.name}: closest real list {self.best_match:.0%} against a "
            f"{self.ceiling:.0%} ceiling ({self.margin:+.0%}), over {self.real_lists} lists"
        )


@dataclass(frozen=True)
class FidelityReport:
    rows: tuple[LegendFidelity, ...]

    @property
    def legends(self) -> int:
        return len(self.rows)

    @property
    def best_match(self) -> float:
        return statistics.mean([r.best_match for r in self.rows]) if self.rows else 0.0

    @property
    def mean_match(self) -> float:
        return statistics.mean([r.mean_match for r in self.rows]) if self.rows else 0.0

    @property
    def ceiling(self) -> float:
        """What a real list achieves by the same measure, averaged over legends."""
        return statistics.mean([r.ceiling for r in self.rows]) if self.rows else 0.0

    @property
    def margin(self) -> float:
        return statistics.mean([r.margin for r in self.rows]) if self.rows else 0.0

    @property
    def below_ceiling(self) -> tuple[LegendFidelity, ...]:
        """Legends where we built something less like the field than the field is like
        itself. This, not a low raw score, is the list worth acting on."""
        return tuple(sorted((r for r in self.rows if r.margin < 0), key=lambda r: r.margin))

    def worst(self, count: int = 5) -> tuple[LegendFidelity, ...]:
        """Ranked by margin, not by raw score.

        Ranking by raw score put the legends with the most fragmented fields at the top
        and read as a list of our failures -- Renata Glasc led it while being our best
        relative result. Margin asks the question that has an answer: where did we do
        least well against what was achievable?
        """
        return tuple(sorted(self.rows, key=lambda r: r.margin)[:count])

    def render(self) -> str:
        return '\n'.join([
            f"legends measured        {self.legends}",
            f"closest real list       {self.best_match:.3f}",
            f"  a real list achieves  {self.ceiling:.3f}   (against its nearest peer)",
            f"  margin                {self.margin:+.3f}",
            f"field average           {self.mean_match:.3f}",
            f"below the ceiling       {len(self.below_ceiling)} of {self.legends}",
        ])


def peer_ceiling(lists: Sequence[frozenset[str]]) -> float:
    """What a real list scores by this measure: its overlap with its nearest real peer.

    The bar the builder is actually being asked to clear. Without it a score cannot be
    read: a legend whose field has splintered into three plans caps out far below one
    with a single settled list, and reporting the raw number ranks fragmentation while
    looking like it ranks quality.

    Exact rather than sampled -- 227,212 pairs across the live snapshot in 0.4s -- so the
    gate stays reproducible. A sampled ceiling would make the gate's own threshold move
    between runs, which is the failure the win-rate gate already taught us once.
    """
    if len(lists) < 2:
        return 0.0
    # Excluded by position, not by identity. Two identical published lists are two real
    # data points, and `other is not this` would have dropped both -- a caller holding
    # the same frozenset twice got an empty max and a crash rather than a ceiling of 1.0.
    return statistics.mean(
        max(jaccard(lists[i], lists[j]) for j in range(len(lists)) if j != i)
        for i in range(len(lists))
    )


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def full_collection(
    legend_id: str, *, catalog: Catalog, rules: BoundRules
) -> dict[str, int]:
    """Every legal card for a legend, at its copy limit.

    Fidelity is a property of the *signal*, so it is measured with the collection
    constraint removed. A thin collection makes every builder look alike -- there is
    only one deck to hand over -- and would mask exactly the regression this guards.
    """
    legend = catalog.get(legend_id)
    if legend is None:
        return {}
    owned: dict[str, int] = {
        card.card_id: copy_cap(card, rules=rules)
        for card in legal_main_pool(legend, catalog=catalog, rules=rules)
    }
    rune_type = rules.str_constraint("rune_card_type", "Rune")
    for card in legal_zone_pool(legend, rune_type, catalog=catalog, rules=rules):
        owned[card.card_id] = rules.int_constraint("rune_count_exact", 12)
    bf_type = rules.str_constraint("battlefield_card_type", "Battlefield")
    for card in legal_zone_pool(legend, bf_type, catalog=catalog, rules=rules):
        owned[card.card_id] = 1
    owned[legend_id] = 1
    return owned


def measure(
    *,
    index: LegendIndex,
    reference: Sequence[MetaDeck],
    catalog: Catalog,
    rules: BoundRules,
    minimum: int = MIN_REAL_LISTS,
) -> FidelityReport:
    """Build from ``index``, score against the real lists in ``reference``.

    ``reference`` is the population the built deck is claiming to represent -- normally
    the current era. Passing an all-time reference measures something different and
    mostly uninteresting: how well the builder reproduces history.
    """
    real: dict[str, list[frozenset[str]]] = defaultdict(list)
    for deck in reference:
        if deck.deck.legend_id and deck.deck.main:
            real[deck.deck.legend_id].append(frozenset(deck.deck.main))

    rows: list[LegendFidelity] = []
    for legend_id, lists in real.items():
        if len(lists) < minimum:
            continue
        profile = index.get(legend_id)
        if profile is None:
            continue
        owned = full_collection(legend_id, catalog=catalog, rules=rules)
        deck = _build_best(legend_id, owned, profile, catalog=catalog, rules=rules)
        if deck is None:
            continue
        built = frozenset(deck.main)
        overlaps = [jaccard(built, other) for other in lists]
        card = catalog.get(legend_id)
        rows.append(
            LegendFidelity(
                legend_id=legend_id,
                name=card.name if card else legend_id,
                real_lists=len(lists),
                best_match=max(overlaps),
                mean_match=statistics.mean(overlaps),
                ceiling=peer_ceiling(lists),
            )
        )
    rows.sort(key=lambda r: r.legend_id)
    return FidelityReport(rows=tuple(rows))


def _build_best(
    legend_id: str,
    owned: Mapping[str, int],
    profile,
    *,
    catalog: Catalog,
    rules: BoundRules,
) -> Deck | None:
    """Build the way the wizard's floor does, so the metric tracks the shipped path."""
    return build(
        legend_id, owned, catalog=catalog, rules=rules,
        preference=profile.preference(),
    )


def compare(before: FidelityReport, after: FidelityReport) -> dict[str, object]:
    """Two reports, per legend. Used to prove a signal change is an improvement."""
    left = {row.legend_id: row for row in before.rows}
    right = {row.legend_id: row for row in after.rows}
    shared = sorted(set(left) & set(right))
    wins = [k for k in shared if right[k].best_match > left[k].best_match + 1e-9]
    losses = [k for k in shared if right[k].best_match < left[k].best_match - 1e-9]
    return {
        "compared": len(shared),
        "wins": len(wins),
        "ties": len(shared) - len(wins) - len(losses),
        "losses": len(losses),
        "best_delta": after.best_match - before.best_match,
        "mean_delta": after.mean_match - before.mean_match,
        # The ceiling is a property of the published field, so it is identical on both
        # sides of any comparison of *our* signal -- which makes the margin delta the
        # same number as the best delta, and worth stating rather than recomputing.
        "margin_delta": after.margin - before.margin,
        "regressed": tuple(right[k].name for k in losses),
    }
