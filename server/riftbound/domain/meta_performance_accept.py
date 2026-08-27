"""The win-rate acceptance run, against the live snapshot.

``python -m riftbound.domain.meta_performance_accept``

Exits non-zero when a target is missed, so it can gate a release the way the bundle gate
and the Smart Decks acceptance run already do. Prints the table it would publish and,
underneath, the entities it is refusing to rank and why — because "we cannot say" is the
half of this feature most likely to be quietly dropped.

Like the Smart Decks run this is a **command, never a fixture**. Nothing in ``tests/``
imports it or the snapshot it reads. v2's API fixture trained a model before every test
and one numerical bug took down sixteen tests covering auth and collection import; the
rule that came out of it is that the fast suite must not be able to be taken hostage by
the slow subsystem.
"""

from __future__ import annotations

import argparse
import random
import sys
import time

from ..services import get_services
from .eras import eras_for_format
from .meta_performance_harness import evaluate
from .meta_trends.common import TrendFilter, archive_span, parse_date


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--era", default="",
        help="era id to measure (default: the current one; 'all' for the whole archive)",
    )
    parser.add_argument(
        "--dimension", default="archetype", choices=("archetype", "legend", "champion"),
    )
    parser.add_argument(
        "--min-players", type=int, default=0,
        help="ignore events smaller than this (default 0: every event)",
    )
    parser.add_argument("--seed", type=int, default=20260826)
    parser.add_argument(
        "--show", type=int, default=12, help="rows of the published table to print",
    )
    args = parser.parse_args(argv)

    services = get_services()
    snapshot = services.meta
    if snapshot is None:
        print("No meta snapshot. Run the meta pipeline first.", file=sys.stderr)
        return 1

    rules = services.rules_for("constructed")
    eras = eras_for_format(rules)
    if not len(eras):
        print(
            "The constructed profile declares no eras. Add an 'eras' block to "
            "data/rules/constructed.json — a win rate averaged across a ban list "
            "change is a number about a format nobody is playing.",
            file=sys.stderr,
        )
        return 1

    span_from, span_to, _count = archive_span(snapshot.tournaments)
    start, end = parse_date(span_from), parse_date(span_to)
    if start is None or end is None:
        print("The snapshot has no dated tournaments.", file=sys.stderr)
        return 1

    trend_filter = TrendFilter(
        from_date=start, to_date=end, min_players=max(0, args.min_players)
    )

    started = time.perf_counter()
    report, table = evaluate(
        decks=list(snapshot.decks),
        tournaments=list(snapshot.tournaments),
        standings=list(snapshot.standings),
        catalog=services.catalog,
        trend_filter=trend_filter,
        eras=eras,
        era_id=args.era,
        dimension=args.dimension,
        rng=random.Random(args.seed),
    )
    elapsed = time.perf_counter() - started

    era = eras.resolve(args.era)
    print(f"snapshot                {snapshot.path.name}")
    print(report.render())
    if not era.is_cited and era.era_id != "all":
        print(
            "era boundary            DERIVED, not cited — "
            "add the announcement URL to the profile when one is to hand"
        )
    print(f"elapsed                 {elapsed:.2f}s")

    published = table.ranked()
    if published:
        print()
        print(f"would publish ({len(published)}):")
        for row in published[: max(0, args.show)]:
            flag = "  *" if row.separated else "   "
            print(
                f"{flag} {row.name[:42]:42s} {row.win_rate:6.1%}  "
                f"[{row.interval_low:5.1%}-{row.interval_high:5.1%}]  "
                f"{row.decisive:5d} matches  {row.events:3d} events  {row.pilots:4d} pilots"
            )
        if len(published) > args.show:
            print(f"    ... and {len(published) - args.show} more")
        print("  * whole interval above even")

    withheld = sorted(
        (row for row in table.rows.values() if not row.shown),
        key=lambda row: -row.decisive,
    )
    if withheld:
        print()
        print(f"would withhold ({len(withheld)}), closest first:")
        for row in withheld[:5]:
            print(f"    {row.name[:42]:42s} {row.explain_withheld()}")
        if len(withheld) > 5:
            print(f"    ... and {len(withheld) - 5} more")

    print()
    print(f"basis: {table.basis.caveat}")
    print()
    if report.passes:
        print("PASS")
        return 0

    print("FAIL", file=sys.stderr)
    for failure in report.failures:
        print(f"  {failure}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
