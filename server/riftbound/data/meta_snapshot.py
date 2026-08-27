"""Meta snapshots: the same discipline as card bundles, applied to the meta.

Dated, hashed, immutable, promoted deliberately. The meta moves faster than the card
pool, so this is the thing that will be refreshed most often — which is exactly why it
needs a gate rather than an overwrite.

The pointer helpers (`promote`, `resolve_current`) are shared with card bundles; only
the payload and the validation rules differ.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..domain.cards import Catalog
from ..domain.deck import Deck
from ..domain.meta import (
    EVIDENCE_TOURNAMENT_PLACED,
    MetaDeck,
    Provenance,
    Standing,
    Tournament,
)
from .bundle import CURRENT_LINK_NAME, content_hash, promote, resolve_current

META_FORMAT_VERSION = 1

#: A refresh that loses most of the previous meta is a broken source, not a quiet week.
MAX_DECK_LOSS_RATIO = 0.5
#: Below this, the snapshot is not worth promoting over whatever is already live.
MIN_PLAUSIBLE_DECKS = 10

#: How much of the previous promoted snapshot the merged archive may lose before it is
#: refused rather than warned about.
#:
#: This is the check that was missing. `run_meta_gate` deliberately runs *before*
#: carry-forward, so it sees only the fresh harvest -- which legitimately covers a
#: shorter window than the archive and is expected to look smaller. That left nothing at
#: all watching the number that matters: whether the thing about to be promoted holds
#: less than the thing already live.
#:
#: It cost a real outage. A refresh that could not reach one source carried its decks
#: forward and dropped its standings, so the deck count matched exactly -- 4,359 both
#: sides -- while 13% of the standings and 2,030 match records disappeared, and the
#: snapshot was promoted with `sourceOk: true`.
#:
#: Small tolerance rather than zero, because rows genuinely age out past ARCHIVE_DAYS.
MAX_ARCHIVE_LOSS_RATIO = 0.02


@dataclass(frozen=True)
class MetaManifest:
    snapshot_id: str
    format_version: int
    created_at: str
    deck_count: int
    tournament_count: int
    standing_count: int
    evidence_counts: dict[str, int]
    content_sha256: str
    source_ok: bool = True
    source_error: str = ""
    notes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    #: Credits required by the sources this snapshot came from. TopDeck.gg's API terms
    #: require a visible credit and link back on any project that uses it, so the
    #: obligation travels with the data rather than living only in a docs page.
    attribution: tuple[dict[str, str], ...] = ()
    promoted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshotId": self.snapshot_id,
            "formatVersion": self.format_version,
            "createdAt": self.created_at,
            "deckCount": self.deck_count,
            "tournamentCount": self.tournament_count,
            "standingCount": self.standing_count,
            "evidenceCounts": dict(self.evidence_counts),
            "contentSha256": self.content_sha256,
            "sourceOk": self.source_ok,
            "sourceError": self.source_error,
            "notes": list(self.notes),
            "warnings": list(self.warnings),
            "attribution": [dict(a) for a in self.attribution],
            "promoted": self.promoted,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> MetaManifest:
        return cls(
            snapshot_id=str(raw.get("snapshotId") or ""),
            format_version=int(raw.get("formatVersion") or 0),
            created_at=str(raw.get("createdAt") or ""),
            deck_count=int(raw.get("deckCount") or 0),
            tournament_count=int(raw.get("tournamentCount") or 0),
            standing_count=int(raw.get("standingCount") or 0),
            evidence_counts=dict(raw.get("evidenceCounts") or {}),
            content_sha256=str(raw.get("contentSha256") or ""),
            source_ok=bool(raw.get("sourceOk", True)),
            source_error=str(raw.get("sourceError") or ""),
            notes=tuple(raw.get("notes") or ()),
            warnings=tuple(raw.get("warnings") or ()),
            attribution=tuple(
                {str(k): str(v) for k, v in a.items()}
                for a in (raw.get("attribution") or [])
                if isinstance(a, dict)
            ),
            promoted=bool(raw.get("promoted")),
        )


@dataclass(frozen=True)
class MetaSnapshot:
    manifest: MetaManifest
    decks: tuple[MetaDeck, ...]
    tournaments: tuple[Tournament, ...]
    standings: tuple[Standing, ...]
    path: Path


# -- serialisation ------------------------------------------------------------


def deck_to_dict(deck: MetaDeck) -> dict[str, Any]:
    p = deck.provenance
    return {
        "deckId": deck.deck_id,
        "deck": {
            "name": deck.deck.name,
            "format": deck.deck.format,
            "legendId": deck.deck.legend_id,
            "championId": deck.deck.champion_id,
            "main": dict(deck.deck.main),
            "runes": dict(deck.deck.runes),
            "battlefields": list(deck.deck.battlefields),
            "sideboard": dict(deck.deck.sideboard),
        },
        "unresolved": list(deck.unresolved),
        "provenance": {
            "source": p.source, "sourceSlug": p.source_slug, "url": p.url,
            "publishedAt": p.published_at, "author": p.author, "views": p.views,
            "quality": p.quality,
            "evidence": p.evidence, "tournamentSlug": p.tournament_slug,
            "tournamentName": p.tournament_name, "tournamentDate": p.tournament_date,
            "placement": p.placement, "fieldSize": p.field_size,
        },
    }


def deck_from_dict(raw: dict[str, Any]) -> MetaDeck:
    d = raw.get("deck") or {}
    p = raw.get("provenance") or {}
    return MetaDeck(
        deck=Deck.make(
            name=str(d.get("name") or ""), format=str(d.get("format") or "constructed"),
            legend_id=str(d.get("legendId") or ""), champion_id=str(d.get("championId") or ""),
            main=d.get("main") or {}, runes=d.get("runes") or {},
            battlefields=d.get("battlefields") or [], sideboard=d.get("sideboard") or {},
        ),
        unresolved=tuple(raw.get("unresolved") or ()),
        provenance=Provenance(
            source=str(p.get("source") or ""), source_slug=str(p.get("sourceSlug") or ""),
            url=str(p.get("url") or ""), published_at=str(p.get("publishedAt") or ""),
            author=str(p.get("author") or ""), views=int(p.get("views") or 0),
            quality=float(p.get("quality") or 0.0),
            evidence=str(p.get("evidence") or "community"),
            tournament_slug=str(p.get("tournamentSlug") or ""),
            tournament_name=str(p.get("tournamentName") or ""),
            tournament_date=str(p.get("tournamentDate") or ""),
            placement=int(p.get("placement") or 0), field_size=int(p.get("fieldSize") or 0),
        ),
    )


def _tournament_to_dict(t: Tournament) -> dict[str, Any]:
    return {
        "tournamentId": t.tournament_id, "slug": t.slug, "name": t.name, "date": t.date,
        "format": t.format, "players": t.players, "organizer": t.organizer,
        "winner": t.winner, "decksPublished": t.decks_published,
    }


def _tournament_from_dict(raw: dict[str, Any]) -> Tournament:
    return Tournament(
        tournament_id=str(raw.get("tournamentId") or ""), slug=str(raw.get("slug") or ""),
        name=str(raw.get("name") or ""), date=str(raw.get("date") or ""),
        format=str(raw.get("format") or ""), players=int(raw.get("players") or 0),
        organizer=str(raw.get("organizer") or ""), winner=str(raw.get("winner") or ""),
        decks_published=int(raw.get("decksPublished") or 0),
    )


def _standing_to_dict(s: Standing) -> dict[str, Any]:
    wins, losses, draws = s.match_record
    return {
        "tournamentSlug": s.tournament_slug, "place": s.place,
        "playerName": s.player_name, "deckSlug": s.deck_slug, "record": s.record,
        "wins": wins, "losses": losses, "draws": draws,
    }


def _standing_from_dict(raw: dict[str, Any]) -> Standing:
    # A snapshot written before match counts were typed carries only the string. The
    # zeros fall through to Standing.match_record, which parses it -- so an older
    # promoted snapshot keeps its records without a re-harvest.
    return Standing(
        tournament_slug=str(raw.get("tournamentSlug") or ""), place=int(raw.get("place") or 0),
        player_name=str(raw.get("playerName") or ""), deck_slug=str(raw.get("deckSlug") or ""),
        record=str(raw.get("record") or ""),
        wins=int(raw.get("wins") or 0), losses=int(raw.get("losses") or 0),
        draws=int(raw.get("draws") or 0),
    )


# -- write / read -------------------------------------------------------------


def write_snapshot(
    meta_dir: Path,
    decks: Sequence[MetaDeck],
    tournaments: Sequence[Tournament],
    standings: Sequence[Standing],
    *,
    source_ok: bool = True,
    source_error: str = "",
    notes: Sequence[str] = (),
    warnings: Sequence[str] = (),
    attribution: Sequence[dict[str, str]] = (),
) -> MetaSnapshot:
    ordered = sorted(decks, key=lambda d: d.deck_id)
    payload = {
        "decks": [deck_to_dict(d) for d in ordered],
        "tournaments": [_tournament_to_dict(t) for t in tournaments],
        "standings": [_standing_to_dict(s) for s in standings],
    }
    digest = content_hash(payload)
    now = datetime.now(UTC)
    snapshot_id = f"{now.strftime('%Y-%m-%dT%H%MZ')}-{digest[:6]}"

    counts: dict[str, int] = {}
    for deck in ordered:
        counts[deck.provenance.evidence] = counts.get(deck.provenance.evidence, 0) + 1

    manifest = MetaManifest(
        snapshot_id=snapshot_id,
        format_version=META_FORMAT_VERSION,
        created_at=now.isoformat(),
        deck_count=len(ordered),
        tournament_count=len(tournaments),
        standing_count=len(standings),
        evidence_counts=counts,
        content_sha256=digest,
        source_ok=source_ok,
        source_error=source_error,
        notes=tuple(notes),
        warnings=tuple(warnings),
        attribution=tuple(dict(a) for a in attribution),
    )

    target = meta_dir / snapshot_id
    target.mkdir(parents=True, exist_ok=True)
    (target / "meta.json").write_text(
        json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (target / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return MetaSnapshot(
        manifest=manifest, decks=tuple(ordered), tournaments=tuple(tournaments),
        standings=tuple(standings), path=target,
    )


def read_snapshot(path: Path) -> MetaSnapshot:
    manifest_path, data_path = path / "manifest.json", path / "meta.json"
    if not manifest_path.is_file() or not data_path.is_file():
        raise FileNotFoundError(f"{path} is not a meta snapshot")
    manifest = MetaManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
    if manifest.format_version > META_FORMAT_VERSION:
        raise ValueError(
            f"Meta snapshot {manifest.snapshot_id} uses format version "
            f"{manifest.format_version}; this build understands at most {META_FORMAT_VERSION}."
        )
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    actual = content_hash(payload)
    if manifest.content_sha256 and actual != manifest.content_sha256:
        raise ValueError(
            f"Meta snapshot {manifest.snapshot_id} failed its integrity check; rebuild it."
        )
    return MetaSnapshot(
        manifest=manifest,
        decks=tuple(deck_from_dict(r) for r in payload.get("decks") or []),
        tournaments=tuple(_tournament_from_dict(r) for r in payload.get("tournaments") or []),
        standings=tuple(_standing_from_dict(r) for r in payload.get("standings") or []),
        path=path,
    )


def load_current_meta(meta_dir: Path) -> MetaSnapshot | None:
    """The live snapshot, or None. Meta is optional — the builder works without it."""
    path = resolve_current(meta_dir)
    if path is None:
        return None
    return read_snapshot(path)


def promote_meta(meta_dir: Path, snapshot_id: str) -> Path:
    target = promote(meta_dir, snapshot_id)
    return target


def list_snapshots(meta_dir: Path) -> list[MetaManifest]:
    out: list[MetaManifest] = []
    if not meta_dir.is_dir():
        return out
    for child in sorted(meta_dir.iterdir(), reverse=True):
        if not child.is_dir() or child.name == CURRENT_LINK_NAME:
            continue
        manifest_path = child / "manifest.json"
        if manifest_path.is_file():
            try:
                out.append(MetaManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, ValueError):
                continue
    return out


# -- gate ---------------------------------------------------------------------


@dataclass
class MetaGateReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors

    def render(self) -> str:
        lines = [f"  FAIL  {e}" for e in self.errors]
        lines += [f"  warn  {w}" for w in self.warnings]
        return "\n".join(lines) if lines else "  all checks passed"


def check_archive_retention(
    decks: Sequence[MetaDeck],
    tournaments: Sequence[Tournament],
    standings: Sequence[Standing],
    previous: MetaSnapshot | None,
) -> MetaGateReport:
    """Refuse a snapshot that holds materially less than the one already promoted.

    Run *after* carry-forward, unlike :func:`run_meta_gate`, and that is the whole point:
    the two ask different questions. The gate asks "is this harvest plausible"; this asks
    "is the archive about to go backwards". Carry-forward is supposed to make the second
    impossible, so a failure here means carry-forward has a hole in it -- which is
    exactly how this check came to exist.

    Each population is checked separately. Counting only decks is what let 2,030 match
    records vanish behind an unchanged deck count.
    """
    report = MetaGateReport()
    if previous is None:
        return report

    for label, fresh, before in (
        ("decks", len(decks), previous.manifest.deck_count),
        ("tournaments", len(tournaments), previous.manifest.tournament_count),
        ("standings", len(standings), previous.manifest.standing_count),
    ):
        if before <= 0:
            continue
        lost = 1.0 - fresh / before
        if lost > MAX_ARCHIVE_LOSS_RATIO:
            report.errors.append(
                f"the archive would lose {lost:.0%} of its {label} "
                f"({before:,} -> {fresh:,}) — a promoted snapshot must not hold less "
                f"than the one it replaces; check whether a source failed and its rows "
                f"were carried forward"
            )
    return report


def run_meta_gate(
    decks: Sequence[MetaDeck],
    tournaments: Sequence[Tournament],
    *,
    source_ok: bool,
    source_error: str = "",
    previous: MetaSnapshot | None = None,
    catalog: Catalog | None = None,
) -> MetaGateReport:
    """Validate a candidate meta snapshot before it can be promoted."""
    report = MetaGateReport()

    if not source_ok:
        report.errors.append(f"source failed: {source_error}")
        return report
    if len(decks) < MIN_PLAUSIBLE_DECKS:
        report.errors.append(
            f"only {len(decks)} usable deck(s), below the floor of {MIN_PLAUSIBLE_DECKS} — "
            f"treating as a failed harvest rather than a shrunken meta"
        )
    if not tournaments:
        report.warnings.append("no tournaments in this snapshot")

    placed = sum(1 for d in decks if d.provenance.evidence == EVIDENCE_TOURNAMENT_PLACED)
    if decks and placed == 0:
        report.warnings.append(
            "no deck has a known tournament finish — rankings will rest on recency and "
            "popularity alone"
        )

    incomplete = [d for d in decks if not d.is_complete]
    if incomplete:
        report.warnings.append(
            f"{len(incomplete)} deck(s) reference cards the current card bundle lacks; "
            f"rebuild card data if a new set just released"
        )

    duplicates = len(decks) - len({d.deck_id for d in decks})
    if duplicates:
        report.errors.append(f"{duplicates} duplicate deck id(s)")

    if previous is not None and previous.manifest.deck_count:
        kept = len({d.deck_id for d in decks} & {d.deck_id for d in previous.decks})
        lost_ratio = 1.0 - kept / previous.manifest.deck_count
        if lost_ratio > MAX_DECK_LOSS_RATIO:
            report.warnings.append(
                f"{lost_ratio:.0%} of the previous snapshot's decks are absent — expected "
                f"when the harvest window moves, but check the source if it repeats"
            )
    return report
