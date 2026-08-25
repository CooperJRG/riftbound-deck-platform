"""Card data bundles: versioned, hashed, and never overwritten in place.

v2 refreshed its card data by overwriting a JSON file from a scraper that lived
outside the repository. There was no way to tell a good refresh from a broken one, no
provenance, and no way back. A scraper returning garbage silently became the truth.

A **bundle** is one immutable, dated snapshot of the card data:

    data/bundles/
      2026-08-25T1730Z-a3f19c/   <- an ingest, never modified after it is written
        manifest.json            <- provenance, counts, content hash, source health
        cards.json               <- normalised oracle cards + printings
      current -> 2026-08-25T1730Z-a3f19c

Promotion is a separate, deliberate step (see ``gate``), so a bundle that fails
validation is kept on disk for inspection but never becomes ``current``. Rolling back
is repointing a symlink.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from ..domain.cards import Card, Catalog, Printing, build_catalog

BUNDLE_FORMAT_VERSION = 1
CURRENT_LINK_NAME = "current"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def content_hash(payload: object) -> str:
    """Stable hash of bundle content, used to detect no-op refreshes."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceHealth:
    """Per-source outcome of one ingest run.

    Recorded per source so a single broken scraper is visible as *that source*
    failing, rather than silently shrinking the card pool.
    """
    name: str
    ok: bool
    fetched: int
    accepted: int
    duration_ms: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BundleManifest:
    """Everything needed to judge whether a bundle is trustworthy."""
    bundle_id: str
    format_version: int
    created_at: str
    card_count: int
    printing_count: int
    set_codes: tuple[str, ...]
    content_sha256: str
    sources: tuple[SourceHealth, ...] = ()
    warnings: tuple[str, ...] = ()
    promoted: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundleId": self.bundle_id,
            "formatVersion": self.format_version,
            "createdAt": self.created_at,
            "cardCount": self.card_count,
            "printingCount": self.printing_count,
            "setCodes": list(self.set_codes),
            "contentSha256": self.content_sha256,
            "sources": [s.to_dict() for s in self.sources],
            "warnings": list(self.warnings),
            "promoted": self.promoted,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BundleManifest":
        return cls(
            bundle_id=str(raw.get("bundleId") or ""),
            format_version=int(raw.get("formatVersion") or 0),
            created_at=str(raw.get("createdAt") or ""),
            card_count=int(raw.get("cardCount") or 0),
            printing_count=int(raw.get("printingCount") or 0),
            set_codes=tuple(raw.get("setCodes") or ()),
            content_sha256=str(raw.get("contentSha256") or ""),
            sources=tuple(
                SourceHealth(
                    name=str(s.get("name") or ""),
                    ok=bool(s.get("ok")),
                    fetched=int(s.get("fetched") or 0),
                    accepted=int(s.get("accepted") or 0),
                    duration_ms=int(s.get("duration_ms") or 0),
                    error=str(s.get("error") or ""),
                )
                for s in (raw.get("sources") or [])
            ),
            warnings=tuple(raw.get("warnings") or ()),
            promoted=bool(raw.get("promoted")),
            notes=str(raw.get("notes") or ""),
        )


@dataclass(frozen=True)
class Bundle:
    """A loaded bundle: its manifest plus the catalog it contains."""
    manifest: BundleManifest
    catalog: Catalog
    path: Path


# -- serialisation ------------------------------------------------------------


def card_to_dict(card: Card) -> dict[str, Any]:
    return {
        "cardId": card.card_id,
        "name": card.name,
        "cardType": card.card_type,
        "superType": card.super_type,
        "domains": list(card.domains),
        "domainsOk": card.domains_ok,
        "cost": card.cost,
        "might": card.might,
        "tags": list(card.tags),
        "championTags": list(card.champion_tags),
        "effect": card.effect,
        "flavor": card.flavor,
        "unique": card.unique,
        "printings": [
            {
                "printId": p.print_id,
                "title": p.title,
                "setCode": p.set_code,
                "setName": p.set_name,
                "cardNumber": p.card_number,
                "rarity": p.rarity,
                "promo": p.promo,
                "imageUrl": p.image_url,
            }
            for p in card.printings
        ],
    }


def card_from_dict(raw: dict[str, Any]) -> Card:
    card_id = str(raw.get("cardId") or "")
    printings = tuple(
        Printing(
            print_id=str(p.get("printId") or ""),
            card_id=card_id,
            title=str(p.get("title") or ""),
            set_code=str(p.get("setCode") or ""),
            set_name=str(p.get("setName") or ""),
            card_number=str(p.get("cardNumber") or ""),
            rarity=str(p.get("rarity") or ""),
            promo=bool(p.get("promo")),
            image_url=str(p.get("imageUrl") or ""),
        )
        for p in (raw.get("printings") or [])
    )
    return Card(
        card_id=card_id,
        name=str(raw.get("name") or ""),
        card_type=str(raw.get("cardType") or ""),
        super_type=str(raw.get("superType") or ""),
        domains=tuple(raw.get("domains") or ()),
        domains_ok=bool(raw.get("domainsOk")),
        cost=raw.get("cost"),
        might=raw.get("might"),
        tags=tuple(raw.get("tags") or ()),
        champion_tags=tuple(raw.get("championTags") or ()),
        effect=str(raw.get("effect") or ""),
        flavor=str(raw.get("flavor") or ""),
        unique=bool(raw.get("unique")),
        printings=printings,
    )


# -- writing / reading --------------------------------------------------------


def new_bundle_id(payload_hash: str, *, at: datetime | None = None) -> str:
    stamp = (at or utc_now()).strftime("%Y-%m-%dT%H%MZ")
    return f"{stamp}-{payload_hash[:6]}"


def write_bundle(
    bundles_dir: Path,
    cards: Iterable[Card],
    *,
    sources: Iterable[SourceHealth] = (),
    warnings: Iterable[str] = (),
    notes: str = "",
) -> Bundle:
    """Write a new bundle directory. Never touches ``current``."""
    card_list = sorted(cards, key=lambda c: c.card_id)
    payload = [card_to_dict(c) for c in card_list]
    digest = content_hash(payload)
    bundle_id = new_bundle_id(digest)

    manifest = BundleManifest(
        bundle_id=bundle_id,
        format_version=BUNDLE_FORMAT_VERSION,
        created_at=utc_now().isoformat(),
        card_count=len(card_list),
        printing_count=sum(len(c.printings) for c in card_list),
        set_codes=tuple(sorted({p.set_code for c in card_list for p in c.printings if p.set_code})),
        content_sha256=digest,
        sources=tuple(sources),
        warnings=tuple(warnings),
        promoted=False,
        notes=notes,
    )

    target = bundles_dir / bundle_id
    target.mkdir(parents=True, exist_ok=True)
    (target / "cards.json").write_text(
        json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (target / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return Bundle(manifest=manifest, catalog=build_catalog(card_list), path=target)


def read_bundle(path: Path) -> Bundle:
    """Load a bundle directory, verifying its content hash."""
    manifest_path = path / "manifest.json"
    cards_path = path / "cards.json"
    if not manifest_path.is_file() or not cards_path.is_file():
        raise FileNotFoundError(
            f"{path} is not a bundle (expected manifest.json and cards.json)."
        )
    manifest = BundleManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
    if manifest.format_version > BUNDLE_FORMAT_VERSION:
        raise ValueError(
            f"Bundle {manifest.bundle_id} uses format version {manifest.format_version}, "
            f"but this build understands at most {BUNDLE_FORMAT_VERSION}. Upgrade the app."
        )
    payload = json.loads(cards_path.read_text(encoding="utf-8"))
    actual = content_hash(payload)
    if manifest.content_sha256 and actual != manifest.content_sha256:
        raise ValueError(
            f"Bundle {manifest.bundle_id} failed its integrity check "
            f"(manifest {manifest.content_sha256[:12]}, actual {actual[:12]}). "
            f"The bundle was modified after it was written; rebuild or re-download it."
        )
    return Bundle(
        manifest=manifest,
        catalog=build_catalog(card_from_dict(row) for row in payload),
        path=path,
    )


def promote(bundles_dir: Path, bundle_id: str) -> Path:
    """Point ``current`` at a bundle. The only way data reaches the app."""
    target = bundles_dir / bundle_id
    if not (target / "manifest.json").is_file():
        raise FileNotFoundError(f"No bundle {bundle_id!r} in {bundles_dir}")
    link = bundles_dir / CURRENT_LINK_NAME
    if link.is_symlink() or link.exists():
        if link.is_dir() and not link.is_symlink():
            # Windows without developer mode: a marker file stands in for a symlink.
            pass
        else:
            link.unlink()
    try:
        link.symlink_to(target.name, target_is_directory=True)
    except (OSError, NotImplementedError):
        # Symlinks need elevation on stock Windows; fall back to a pointer file.
        pointer = bundles_dir / f"{CURRENT_LINK_NAME}.txt"
        pointer.write_text(target.name, encoding="utf-8")
    manifest_path = target / "manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["promoted"] = True
    manifest_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def resolve_current(bundles_dir: Path) -> Path | None:
    """Where ``current`` points, honouring the Windows pointer-file fallback."""
    link = bundles_dir / CURRENT_LINK_NAME
    if link.is_dir():
        return link.resolve()
    pointer = bundles_dir / f"{CURRENT_LINK_NAME}.txt"
    if pointer.is_file():
        target = bundles_dir / pointer.read_text(encoding="utf-8").strip()
        return target if target.is_dir() else None
    return None


def load_current(bundles_dir: Path) -> Bundle:
    path = resolve_current(bundles_dir)
    if path is None:
        raise FileNotFoundError(
            f"No promoted card bundle in {bundles_dir}.\n"
            f"Build one with:  python -m riftbound.data.pipeline build --promote"
        )
    return read_bundle(path)


def list_bundles(bundles_dir: Path) -> list[BundleManifest]:
    out: list[BundleManifest] = []
    if not bundles_dir.is_dir():
        return out
    for child in sorted(bundles_dir.iterdir(), reverse=True):
        if not child.is_dir() or child.name == CURRENT_LINK_NAME:
            continue
        manifest_path = child / "manifest.json"
        if manifest_path.is_file():
            try:
                out.append(BundleManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, ValueError):
                continue
    return out
