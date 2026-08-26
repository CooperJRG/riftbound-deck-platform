"""The Smart Decks acceptance run, against the live snapshot.

``python -m riftbound.domain.smart_decks_accept``

The user's criterion was plain: *so long as the user has the cards to make a legal deck
with that legend, that minimum will be found after a couple of rounds.* This turns that
sentence into a pass/fail number over every legend the meta knows, and exits non-zero
when it fails, so it can sit in front of a release the same way the bundle gate does.

Two player populations, because they fail differently:

* **sampled** — rarity-weighted collections at several depths. Generates the awkward
  cases: enough commons to nearly build, missing the one epic that matters.
* **deck-shaped** — built from real lists then perturbed, which is what an actual player
  who has been buying singles looks like, and the source of the "have 2, need 3" case.
"""

from __future__ import annotations

import argparse
import random
import sys
import time

from ..services import get_services
from .legend_index import build_index
from .meta_scoring import score_all, totals
from .smart_decks_harness import Player, collection_from_decks, random_collection, simulate

#: Collection depths to sample, and how many players at each.
DEPTHS: tuple[tuple[str, float, int], ...] = (
    ("thin", 0.35, 4), ("mid", 0.6, 4), ("deep", 0.9, 4),
)
DECK_SHAPED = 8


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legends", type=int, default=0,
                        help="cap legends tested (0 = all); the full run takes ~a minute")
    parser.add_argument("--seed", type=int, default=20260825)
    args = parser.parse_args(argv)

    services = get_services()
    snapshot = services.meta
    if snapshot is None:
        print("No meta snapshot. Run the meta pipeline first.", file=sys.stderr)
        return 1

    catalog = services.catalog
    rules = services.rules_for("constructed")
    scores = totals(score_all(snapshot.decks))
    index = build_index(snapshot.decks, scores)

    legends = list(index.legends())
    if args.legends:
        legends = legends[: args.legends]

    rng = random.Random(args.seed)
    players = [
        Player(name=f"{label}-{i}", owned=random_collection(catalog, rng=rng, scale=scale))
        for label, scale, count in DEPTHS
        for i in range(count)
    ]
    pool = list(snapshot.decks)
    for i in range(DECK_SHAPED):
        picked = rng.sample(pool, min(3, len(pool)))
        players.append(
            Player(name=f"deck-shaped-{i}", owned=collection_from_decks(picked, rng=rng))
        )

    started = time.perf_counter()
    report = simulate(
        catalog=catalog, rules=rules, index=index, decks=snapshot.decks, scores=scores,
        legends=legends, players=players,
    )
    elapsed = time.perf_counter() - started

    print(f"snapshot                {snapshot.path.name}")
    print(f"legends x players       {len(legends)} x {len(players)}")
    print(report.render())
    print(f"elapsed                 {elapsed:.1f}s")
    print()
    if report.passes:
        print("PASS")
        return 0

    print("FAIL", file=sys.stderr)
    for outcome in report.outcomes:
        if outcome.false_negative:
            print(f"  false negative: {outcome.player} / {outcome.legend_id}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
