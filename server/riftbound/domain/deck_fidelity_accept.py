"""Does the builder still build the format that is actually being played?

``python -m riftbound.domain.deck_fidelity_accept``

Exits non-zero when the answer degrades, so it can gate a release beside the bundle gate,
the Smart Decks run and the win-rate run.

It guards a failure with no symptoms. Smart Decks could hit every one of its targets --
solved-when-feasible 100%, no false negatives, two rounds to an answer -- while handing
players a deck assembled from evidence for a format that ended months ago. Nothing broke,
nothing errored, and the deck was legal. It was simply the wrong deck, and the only way to
see it is to compare what the builder produces against what the field currently plays.

Two things are checked:

* **the level** -- built decks resemble real current-era lists, in absolute terms;
* **the direction** -- the era-scoped signal beats the all-time one it replaced. That
  comparison is the actual regression guard: if somebody widens the index back to the
  whole archive, this run goes red with the reason attached.

Like the other acceptance runs this is a **command, never a fixture**. Nothing in
``tests/`` imports it or the snapshot it reads.
"""

from __future__ import annotations

import argparse
import sys
import time

from ..services import get_services
from .deck_fidelity import MIN_REAL_LISTS, compare, measure
from .eras import eras_for_format
from .legend_index import build_index, build_scoped_index
from .meta_scoring import score_all, totals

#: Overlap with the closest real list, averaged over legends. Measured on the live
#: snapshot with the era-scoped index: **0.879**. Set at 0.80 so ordinary churn in what
#: the field plays does not trip it while a signal regression does.
TARGET_BEST_MATCH = 0.80

#: Overlap averaged over *every* real list for a legend, not just the closest. The
#: stricter of the two and the harder to flatter. Measured: **0.606**.
TARGET_MEAN_MATCH = 0.55

#: How far below the all-time index the scoped one may sit before this is a regression.
#: Zero: the whole justification for scoping is that it is better, so it has to stay
#: better. A small tolerance absorbs a snapshot where the two happen to tie.
REGRESSION_TOLERANCE = 0.005

#: How far above the *achievable* bar the built decks have to sit, averaged over legends.
#:
#: The better of the two absolute checks, because it moves with the field instead of
#: being a number somebody picked. `TARGET_BEST_MATCH` says "score at least 0.80"; if the
#: format fragments and real lists stop resembling each other, 0.80 stops being possible
#: and the gate fails for a reason that is nothing to do with us. This asks the question
#: that always has an answer: did we build something more like the field than the field is
#: like itself? Measured: +0.132.
TARGET_MARGIN = 0.05

#: Legends allowed to sit below their own ceiling before it is treated as a defect rather
#: than a hard case. Measured: 2 of 47 (Irelia, Fiora).
MAX_BELOW_CEILING = 4


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--era", default="",
        help="era to measure against (default: the current one)",
    )
    parser.add_argument("--show", type=int, default=5, help="worst legends to list")
    args = parser.parse_args(argv)

    services = get_services()
    snapshot = services.meta
    if snapshot is None:
        print("No meta snapshot. Run the meta pipeline first.", file=sys.stderr)
        return 1

    catalog = services.catalog
    rules = services.rules_for("constructed")
    eras = eras_for_format(rules)
    era = eras.resolve(args.era)
    decks = list(snapshot.decks)
    scores = totals(score_all(decks))

    reference = [
        deck for deck in decks
        if era.era_id == "all"
        or era.contains(deck.provenance.tournament_date or deck.provenance.published_at)
    ]
    if not reference:
        print(f"No decks in era {era.era_id!r}.", file=sys.stderr)
        return 1

    started = time.perf_counter()
    scoped = measure(
        index=build_scoped_index(decks, scores, era),
        reference=reference, catalog=catalog, rules=rules,
    )
    archive = measure(
        index=build_index(decks, scores, era_id="all"),
        reference=reference, catalog=catalog, rules=rules,
    )
    elapsed = time.perf_counter() - started
    delta = compare(archive, scoped)

    print(f"snapshot                {snapshot.path.name}")
    print(f"era                     {era.describe()}")
    print(f"reference lists         {len(reference):,} (>= {MIN_REAL_LISTS} per legend)")
    print(scoped.render())
    print(f"  targets               best >= {TARGET_BEST_MATCH:.2f}, "
          f"mean >= {TARGET_MEAN_MATCH:.2f}, margin >= {TARGET_MARGIN:+.2f}")
    print()
    print("against the all-time signal it replaced:")
    print(f"  closest real list     {archive.best_match:.3f} -> {scoped.best_match:.3f}"
          f"   ({delta['best_delta']:+.3f})")
    print(f"  field average         {archive.mean_match:.3f} -> {scoped.mean_match:.3f}"
          f"   ({delta['mean_delta']:+.3f})")
    print(f"  per legend            {delta['wins']} better, {delta['ties']} unchanged, "
          f"{delta['losses']} worse")
    if delta["regressed"]:
        print(f"  worse                 {', '.join(delta['regressed'])}")
    print(f"elapsed                 {elapsed:.1f}s")

    worst = scoped.worst(max(0, args.show))
    if worst:
        print()
        # Ranked by margin. Ranked by raw score this listed the legends with the most
        # fragmented fields and read as a list of our failures -- the top entry was our
        # best relative result.
        print(f"least well built for what was achievable ({len(worst)}):")
        for row in worst:
            print(f"    {row.describe()}")

    failures: list[str] = []
    if scoped.best_match < TARGET_BEST_MATCH:
        failures.append(
            f"closest-match {scoped.best_match:.3f} below {TARGET_BEST_MATCH:.2f} — "
            f"built decks no longer resemble what the field plays"
        )
    if scoped.mean_match < TARGET_MEAN_MATCH:
        failures.append(
            f"field-average {scoped.mean_match:.3f} below {TARGET_MEAN_MATCH:.2f}"
        )
    if scoped.margin < TARGET_MARGIN:
        failures.append(
            f"margin {scoped.margin:+.3f} below {TARGET_MARGIN:+.2f} — built decks are no "
            f"more like the field than the field is like itself"
        )
    if len(scoped.below_ceiling) > MAX_BELOW_CEILING:
        names = ", ".join(row.name for row in scoped.below_ceiling[:5])
        failures.append(
            f"{len(scoped.below_ceiling)} legends built below their own ceiling, above "
            f"the {MAX_BELOW_CEILING} allowed: {names}"
        )
    if scoped.best_match < archive.best_match - REGRESSION_TOLERANCE:
        failures.append(
            f"the era-scoped signal ({scoped.best_match:.3f}) is worse than the all-time "
            f"one ({archive.best_match:.3f}) — scoping is no longer earning its place"
        )

    print()
    if not failures:
        print("PASS")
        return 0
    print("FAIL", file=sys.stderr)
    for failure in failures:
        print(f"  {failure}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
