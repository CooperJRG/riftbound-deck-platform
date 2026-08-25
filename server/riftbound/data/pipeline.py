"""Ingest pipeline CLI: fetch -> normalise -> gate -> write -> (maybe) promote.

    python -m riftbound.data.pipeline build [--promote] [--source PATH]
    python -m riftbound.data.pipeline list
    python -m riftbound.data.pipeline promote <bundle-id>
    python -m riftbound.data.pipeline show [<bundle-id>]

Unlike v2 -- where the equivalent scripts lived outside the repository and the app
shelled out to them -- this is an ordinary module inside the package, so a fresh
clone can rebuild its own data.

Promotion is deliberate. ``build`` alone writes a bundle and reports what changed;
only ``--promote`` (and only when the gate passes) points the app at it.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from ..config import ROOT, load_config
from .bundle import (
    Bundle,
    SourceHealth,
    list_bundles,
    load_current,
    promote,
    read_bundle,
    resolve_current,
    write_bundle,
)
from .gate import diff_summary, run_gate
from .normalize import normalize
from .sources.base import CardSource, FetchResult
from .sources.dotgg import DotGGSource
from .sources.json_export import JsonExportSource

#: Raw source responses are kept here for replay and diffing. Gitignored: cache, not
#: source code. v2 committed 2,268 scraped files.
INGEST_CACHE = ROOT / "var" / "ingest"


def default_sources(local_export: Path | None = None) -> list[CardSource]:
    """The sources an ordinary ``build`` runs.

    ``--source PATH`` swaps in a local export instead, for working offline. Additional
    network adapters (Piltover Archive, riftbound.gg) register here as they are
    written; each is independent, so one going down cannot break the others.
    """
    if local_export is not None:
        return [JsonExportSource(local_export, name="json-export")]
    return [DotGGSource(cache_dir=INGEST_CACHE)]


def _current_bundle(bundles_dir: Path) -> Bundle | None:
    try:
        return load_current(bundles_dir) if resolve_current(bundles_dir) else None
    except (FileNotFoundError, ValueError) as exc:
        print(f"  note: could not read current bundle ({exc}); comparing against nothing")
        return None


def cmd_build(args: argparse.Namespace) -> int:
    cfg = load_config()
    cfg.bundles_dir.mkdir(parents=True, exist_ok=True)

    sources = default_sources(Path(args.source) if args.source else None)
    print(f"Ingesting from {len(sources)} source(s)...")

    results: list[FetchResult] = []
    for source in sources:
        result = source.fetch()
        results.append(result)
        status = "ok" if result.ok else "FAILED"
        print(f"  {source.name:<16} {status:>6}  {result.fetched:>5} rows  {result.duration_ms:>5} ms")
        if not result.ok:
            print(f"      {result.error}")

    raws = [card for result in results for card in result.cards]
    warnings: list[str] = []
    cards = normalize(raws, warnings=warnings)

    health = tuple(
        SourceHealth(
            name=r.name,
            ok=r.ok,
            fetched=r.fetched,
            accepted=sum(1 for c in r.cards),
            duration_ms=r.duration_ms,
            error=r.error,
        )
        for r in results
    )

    previous = _current_bundle(cfg.bundles_dir)
    print(f"\nNormalised: {diff_summary(cards, previous)}")
    print(f"            {len(raws)} printings -> {len(cards)} gameplay cards")

    by_set: dict[str, int] = {}
    for card in cards:
        for code in card.set_codes:
            by_set[code] = by_set.get(code, 0) + 1
    print("            sets: " + ", ".join(f"{k} {v}" for k, v in sorted(by_set.items())))

    drift = _ban_drift(cards, cfg)
    if drift:
        print("\nBan list drift - the source and your rules profile disagree:")
        for line in drift:
            print(f"  {line}")
        print("  Rules profiles decide legality, so edit data/rules/*.json to act on this.")

    report = run_gate(cards, sources=health, previous=previous)
    print("\nValidation gate:")
    print(report.render())

    bundle = write_bundle(
        cfg.bundles_dir,
        cards,
        sources=health,
        warnings=tuple(warnings) + tuple(report.warnings),
        notes=args.notes or "",
    )
    print(f"\nWrote bundle {bundle.manifest.bundle_id} -> {bundle.path}")

    if not report.passed:
        print("\nGate FAILED - bundle written for inspection but not promoted.")
        return 1

    if args.promote:
        promote(cfg.bundles_dir, bundle.manifest.bundle_id)
        print(f"Promoted {bundle.manifest.bundle_id} to current.")
    else:
        print(
            "Not promoted. Review it, then:\n"
            f"  python -m riftbound.data.pipeline promote {bundle.manifest.bundle_id}"
        )
    return 0


def _ban_drift(cards: Sequence, cfg) -> list[str]:
    """Compare the source's ban flags against each format's authored ban list.

    Ban lists go stale the same way set lists do. The rules profile stays the authority
    on legality -- this only reports the difference so a human can act on it.
    """
    try:
        from ..domain.rules import load_format_rules_dir
        profiles = load_format_rules_dir(cfg.rules_dir)
    except (FileNotFoundError, ValueError):
        return []

    by_id = {c.card_id: c for c in cards}
    upstream = {c.card_id for c in cards if c.banned_upstream}
    lines: list[str] = []
    for name, profile in sorted(profiles.items()):
        authored: set[str] = set()
        unknown: list[str] = []
        for raw_name in profile.list_constraint("banned_cards"):
            from ..domain.ids import card_id_for
            cid = card_id_for(raw_name)
            (authored.add(cid) if cid in by_id else unknown.append(raw_name))
        for cid in sorted(upstream - authored):
            lines.append(f"{name}: source bans {by_id[cid].name!r}, profile does not")
        for raw_name in unknown:
            lines.append(f"{name}: profile bans {raw_name!r}, which is not in the card data")
    return lines


def cmd_list(args: argparse.Namespace) -> int:
    cfg = load_config()
    current = resolve_current(cfg.bundles_dir)
    current_name = current.name if current else ""
    manifests = list_bundles(cfg.bundles_dir)
    if not manifests:
        print(f"No bundles in {cfg.bundles_dir}")
        return 0
    print(f"{'':2} {'BUNDLE':<26} {'CARDS':>6} {'PRINTS':>7}  SETS")
    for m in manifests:
        marker = "->" if m.bundle_id == current_name else "  "
        print(f"{marker} {m.bundle_id:<26} {m.card_count:>6} {m.printing_count:>7}  {','.join(m.set_codes)}")
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    cfg = load_config()
    target = cfg.bundles_dir / args.bundle_id
    try:
        candidate = read_bundle(target)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Cannot promote: {exc}")
        return 1
    previous = _current_bundle(cfg.bundles_dir)
    report = run_gate(list(candidate.catalog), sources=candidate.manifest.sources, previous=previous)
    print("Validation gate:")
    print(report.render())
    if not report.passed and not args.force:
        print("\nGate FAILED - refusing to promote. Pass --force to override.")
        return 1
    promote(cfg.bundles_dir, args.bundle_id)
    print(f"\nPromoted {args.bundle_id} to current.")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    cfg = load_config()
    path = (cfg.bundles_dir / args.bundle_id) if args.bundle_id else resolve_current(cfg.bundles_dir)
    if path is None:
        print("No current bundle.")
        return 1
    bundle = read_bundle(path)
    m = bundle.manifest
    print(f"bundle      {m.bundle_id}")
    print(f"created     {m.created_at}")
    print(f"cards       {m.card_count}  ({m.printing_count} printings)")
    print(f"sets        {', '.join(m.set_codes)}")
    print(f"sha256      {m.content_sha256[:16]}...")
    print(f"promoted    {m.promoted}")
    if m.sources:
        print("sources")
        for s in m.sources:
            print(f"  {s.name:<16} {'ok' if s.ok else 'FAILED':>6}  {s.accepted}/{s.fetched} rows")
    if m.warnings:
        print("warnings")
        for w in m.warnings[:20]:
            print(f"  - {w}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="riftbound.data.pipeline", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="ingest, normalise, validate, write a bundle")
    p_build.add_argument("--promote", action="store_true", help="promote if the gate passes")
    p_build.add_argument(
        "--source", help="build from a local JSON export instead of the network"
    )
    p_build.add_argument("--notes", help="note recorded in the manifest")
    p_build.set_defaults(func=cmd_build)

    p_list = sub.add_parser("list", help="list bundles on disk")
    p_list.set_defaults(func=cmd_list)

    p_promote = sub.add_parser("promote", help="point current at a bundle")
    p_promote.add_argument("bundle_id")
    p_promote.add_argument("--force", action="store_true", help="promote despite gate failure")
    p_promote.set_defaults(func=cmd_promote)

    p_show = sub.add_parser("show", help="show a bundle manifest")
    p_show.add_argument("bundle_id", nargs="?")
    p_show.set_defaults(func=cmd_show)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
