"""Meta ingest CLI: harvest -> normalise -> gate -> snapshot -> (maybe) promote.

    python -m riftbound.data.meta_pipeline build [--promote] [--decks N] [--since YYYY-MM-DD]
    python -m riftbound.data.meta_pipeline list
    python -m riftbound.data.meta_pipeline promote <snapshot-id>
    python -m riftbound.data.meta_pipeline show [<snapshot-id>]

Meta data is optional: the deck builder works fine with no snapshot promoted. That is
deliberate — a source outage must degrade the meta view, never the builder.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from ..config import ROOT, ConfigError, load_config
from ..domain.meta import build_archetypes
from ..domain.meta_scoring import score_all, totals
from .bundle import load_current
from .meta_normalize import (
    normalize_meta_decks,
    standings_from,
    summarise,
    tournaments_from,
)
from .meta_snapshot import (
    list_snapshots,
    load_current_meta,
    promote_meta,
    read_snapshot,
    run_meta_gate,
    write_snapshot,
)
from .sources.dotgg_meta import DotGGMetaSource
from .sources.meta_replay import MetaReplaySource

INGEST_CACHE = ROOT / "var" / "ingest"


def _catalog(cfg):
    try:
        return load_current(cfg.bundles_dir).catalog
    except (FileNotFoundError, ValueError) as exc:
        raise ConfigError(
            f"Meta ingest needs card data first ({exc}).\n"
            f"  Run:  python -m riftbound.data.pipeline build --promote"
        ) from exc


def cmd_build(args: argparse.Namespace) -> int:
    cfg = load_config()
    cfg.meta_dir.mkdir(parents=True, exist_ok=True)
    catalog = _catalog(cfg)

    def progress(message: str) -> None:
        print(message, flush=True)

    if args.replay:
        source = MetaReplaySource(INGEST_CACHE)
        print(f"Replaying the cached harvest from {INGEST_CACHE} (no network)...")
    else:
        source = DotGGMetaSource(
            max_tournaments=args.tournaments,
            max_decks=args.decks,
            since=args.since or "",
            budget_seconds=args.budget,
            progress=progress,
            cache_dir=INGEST_CACHE,
        )
        print(
            f"Harvesting meta (up to {args.tournaments} tournaments, {args.decks} decks)..."
        )
    result = source.fetch()
    status = "ok" if result.ok else "FAILED"
    print(
        f"  {source.name:<14} {status:>6}  {len(result.tournaments):>3} tournaments  "
        f"{len(result.standings):>5} standings  {len(result.decks):>4} deck payloads  "
        f"{result.duration_ms:>6} ms"
    )
    if not result.ok:
        print(f"      {result.error}")
    for note in result.notes:
        print(f"      note: {note}")

    tournaments = tournaments_from(result.tournaments)
    standings = standings_from(result.standings)
    warnings: list[str] = []
    decks = normalize_meta_decks(
        result.decks, catalog=catalog, standings=standings,
        tournaments=tournaments, warnings=warnings,
    )

    counts = summarise(decks)
    print(
        f"\nNormalised: {counts['total']} usable decks "
        f"({counts['tournamentPlaced']} placed, {counts['tournamentEntry']} entered, "
        f"{counts['community']} community; {counts['incomplete']} incomplete)"
    )

    scores = score_all(decks)
    archetypes = build_archetypes(decks, catalog=catalog, scores=totals(scores))
    print(f"            {len(archetypes)} archetypes")
    if archetypes:
        print("\nTop archetypes:")
        for arch in archetypes[:8]:
            backing = (
                f"best {arch.best_placement}" if arch.best_placement
                else f"{arch.deck_count} deck{'s' if arch.deck_count != 1 else ''}"
            )
            print(f"  {arch.score:.3f}  {arch.name[:46]:<48} {backing}")

    previous = load_current_meta(cfg.meta_dir)
    report = run_meta_gate(
        decks, tournaments, source_ok=result.ok, source_error=result.error,
        previous=previous, catalog=catalog,
    )
    print("\nValidation gate:")
    print(report.render())

    snapshot = write_snapshot(
        cfg.meta_dir, decks, tournaments, standings,
        source_ok=result.ok, source_error=result.error,
        notes=result.notes, warnings=warnings[:40],
    )
    print(f"\nWrote snapshot {snapshot.manifest.snapshot_id} -> {snapshot.path}")

    if not report.passed:
        print("\nGate FAILED - snapshot written for inspection but not promoted.")
        return 1
    if args.promote:
        promote_meta(cfg.meta_dir, snapshot.manifest.snapshot_id)
        print(f"Promoted {snapshot.manifest.snapshot_id} to current.")
    else:
        print(
            "Not promoted. Review it, then:\n"
            f"  python -m riftbound.data.meta_pipeline promote {snapshot.manifest.snapshot_id}"
        )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    cfg = load_config()
    current = load_current_meta(cfg.meta_dir)
    current_id = current.manifest.snapshot_id if current else ""
    snapshots = list_snapshots(cfg.meta_dir)
    if not snapshots:
        print(f"No meta snapshots in {cfg.meta_dir}")
        return 0
    print(f"{'':2} {'SNAPSHOT':<26} {'DECKS':>6} {'EVENTS':>7} {'PLACED':>7}")
    for m in snapshots:
        marker = "->" if m.snapshot_id == current_id else "  "
        placed = m.evidence_counts.get("tournament-placed", 0)
        print(f"{marker} {m.snapshot_id:<26} {m.deck_count:>6} {m.tournament_count:>7} {placed:>7}")
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    cfg = load_config()
    try:
        candidate = read_snapshot(cfg.meta_dir / args.snapshot_id)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Cannot promote: {exc}")
        return 1
    report = run_meta_gate(
        list(candidate.decks), list(candidate.tournaments),
        source_ok=candidate.manifest.source_ok, source_error=candidate.manifest.source_error,
        previous=load_current_meta(cfg.meta_dir),
    )
    print("Validation gate:")
    print(report.render())
    if not report.passed and not args.force:
        print("\nGate FAILED - refusing to promote. Pass --force to override.")
        return 1
    promote_meta(cfg.meta_dir, args.snapshot_id)
    print(f"\nPromoted {args.snapshot_id} to current.")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    cfg = load_config()
    snapshot = (
        read_snapshot(cfg.meta_dir / args.snapshot_id)
        if args.snapshot_id
        else load_current_meta(cfg.meta_dir)
    )
    if snapshot is None:
        print("No current meta snapshot.")
        return 1
    m = snapshot.manifest
    print(f"snapshot    {m.snapshot_id}")
    print(f"created     {m.created_at}")
    print(f"decks       {m.deck_count}")
    print(f"tournaments {m.tournament_count}  ({m.standing_count} standings)")
    print(f"evidence    {m.evidence_counts}")
    print(f"sha256      {m.content_sha256[:16]}...")
    for note in m.notes[:10]:
        print(f"  note: {note}")
    for warning in m.warnings[:10]:
        print(f"  warn: {warning}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="riftbound.data.meta_pipeline", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="harvest tournaments and decks into a snapshot")
    p.add_argument("--promote", action="store_true", help="promote if the gate passes")
    p.add_argument(
        "--replay", action="store_true",
        help="rebuild from the cached harvest in var/ingest instead of fetching",
    )
    p.add_argument("--decks", type=int, default=400, help="max decklists to hydrate")
    p.add_argument("--tournaments", type=int, default=12, help="max tournaments to read")
    p.add_argument("--since", help="only decks modified on/after this date (YYYY-MM-DD)")
    p.add_argument(
        "--budget", type=float, default=240.0,
        help="wall-clock seconds before the harvest stops early with what it has",
    )
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("list", help="list snapshots on disk")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("promote", help="point current at a snapshot")
    p.add_argument("snapshot_id")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_promote)

    p = sub.add_parser("show", help="show a snapshot manifest")
    p.add_argument("snapshot_id", nargs="?")
    p.set_defaults(func=cmd_show)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # Card and archetype names contain characters a cp1252 console cannot render.
    # Fix the stream rather than degrading the data to ASCII.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except ConfigError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
