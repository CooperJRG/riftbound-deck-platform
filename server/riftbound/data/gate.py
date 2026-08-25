"""The promotion gate.

A freshly built bundle is *not* trusted. It has to pass this gate before it can
become ``current``. This is the single control v2 lacked: its refresh overwrote the
live card file directly, so a scraper that started returning an error page quietly
replaced the card database with nothing and the app just showed empty screens.

The rule that matters most is :func:`check_against_previous` -- a new bundle that
loses a meaningful share of the previous bundle's cards is rejected outright. Card
games add cards; a sudden drop means the source broke, not that the game shrank.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from ..domain.cards import Card
from .bundle import Bundle, SourceHealth

# A healthy ingest should never lose more than a rounding error of the previous
# catalogue. Errata can remove the odd card; a broken scraper removes hundreds.
MAX_CARD_LOSS_RATIO = 0.02
# Floor guarding the very first ingest, when there is no previous bundle to compare.
MIN_PLAUSIBLE_CARDS = 200

KNOWN_CARD_TYPES = {"Unit", "Spell", "Gear", "Battlefield", "Legend", "Rune", "Token"}
KNOWN_RARITIES = {"Common", "Uncommon", "Rare", "Epic", "Showcase"}


@dataclass
class GateReport:
    """Outcome of validating a candidate bundle."""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors

    def merge(self, other: "GateReport") -> "GateReport":
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        return self

    def render(self) -> str:
        lines: list[str] = []
        for err in self.errors:
            lines.append(f"  FAIL  {err}")
        for warn in self.warnings:
            lines.append(f"  warn  {warn}")
        if not lines:
            lines.append("  all checks passed")
        return "\n".join(lines)


def check_structure(cards: Sequence[Card]) -> GateReport:
    """Every card must be identifiable and typed; ids must be unique."""
    report = GateReport()
    if not cards:
        report.errors.append("bundle contains no cards")
        return report

    seen_card_ids: set[str] = set()
    seen_print_ids: dict[str, str] = {}
    untyped: list[str] = []
    unknown_types: dict[str, str] = {}
    unknown_rarities: set[str] = set()
    no_printings: list[str] = []

    for card in cards:
        if not card.card_id:
            report.errors.append(f"card {card.name!r} has no card_id")
            continue
        if card.card_id in seen_card_ids:
            report.errors.append(f"duplicate card_id {card.card_id!r}")
        seen_card_ids.add(card.card_id)

        if not card.name:
            report.errors.append(f"card {card.card_id!r} has no name")
        if not card.card_type:
            untyped.append(card.card_id)
        elif card.card_type not in KNOWN_CARD_TYPES:
            unknown_types[card.card_id] = card.card_type
        if not card.printings:
            no_printings.append(card.card_id)

        for printing in card.printings:
            if printing.print_id in seen_print_ids:
                report.errors.append(
                    f"print_id {printing.print_id!r} claimed by both "
                    f"{seen_print_ids[printing.print_id]!r} and {card.card_id!r}"
                )
            seen_print_ids[printing.print_id] = card.card_id
            if printing.rarity and printing.rarity not in KNOWN_RARITIES:
                unknown_rarities.add(printing.rarity)

    # These are data-quality signals, not corruption -- warn, do not block.
    if untyped:
        report.warnings.append(
            f"{len(untyped)} card(s) have no card type: {', '.join(sorted(untyped)[:5])}"
            + (" ..." if len(untyped) > 5 else "")
        )
    if unknown_types:
        report.warnings.append(
            "unrecognised card types (new mechanic, or upstream change): "
            + ", ".join(f"{k}={v!r}" for k, v in sorted(unknown_types.items())[:5])
        )
    if unknown_rarities:
        report.warnings.append(f"unrecognised rarities: {', '.join(sorted(unknown_rarities))}")
    if no_printings:
        report.warnings.append(f"{len(no_printings)} card(s) have no printings")
    return report


def check_sources(sources: Sequence[SourceHealth]) -> GateReport:
    """At least one source must have worked; failures are always reported."""
    report = GateReport()
    if not sources:
        report.warnings.append("no source health recorded for this bundle")
        return report
    healthy = [s for s in sources if s.ok]
    if not healthy:
        report.errors.append(
            "every source failed: " + "; ".join(f"{s.name}: {s.error}" for s in sources)
        )
    for source in sources:
        if not source.ok:
            report.warnings.append(f"source {source.name!r} failed: {source.error}")
        elif source.fetched and source.accepted < source.fetched * 0.5:
            report.warnings.append(
                f"source {source.name!r} kept only {source.accepted}/{source.fetched} rows "
                f"-- its shape may have changed"
            )
    return report


def check_against_previous(cards: Sequence[Card], previous: Bundle | None) -> GateReport:
    """Reject a bundle that loses cards. The check v2 most needed.

    Without a previous bundle this falls back to a plausibility floor, so the very
    first ingest cannot promote an error page either.
    """
    report = GateReport()
    if previous is None:
        if len(cards) < MIN_PLAUSIBLE_CARDS:
            report.errors.append(
                f"first bundle has only {len(cards)} cards, below the plausibility "
                f"floor of {MIN_PLAUSIBLE_CARDS}. Refusing to promote what is probably "
                f"a failed fetch."
            )
        return report

    old_ids = {c.card_id for c in previous.catalog}
    new_ids = {c.card_id for c in cards}
    lost = old_ids - new_ids
    gained = new_ids - old_ids

    if lost:
        ratio = len(lost) / max(1, len(old_ids))
        sample = ", ".join(sorted(lost)[:5]) + (" ..." if len(lost) > 5 else "")
        if ratio > MAX_CARD_LOSS_RATIO:
            report.errors.append(
                f"{len(lost)} of {len(old_ids)} cards ({ratio:.1%}) disappeared since "
                f"bundle {previous.manifest.bundle_id}, above the {MAX_CARD_LOSS_RATIO:.0%} "
                f"limit. This is what a broken source looks like. Missing: {sample}"
            )
        else:
            report.warnings.append(f"{len(lost)} card(s) removed since last bundle: {sample}")
    if gained:
        report.warnings.append(
            f"{len(gained)} new card(s): "
            + ", ".join(sorted(gained)[:8])
            + (" ..." if len(gained) > 8 else "")
        )
    return report


def run_gate(
    cards: Sequence[Card],
    *,
    sources: Sequence[SourceHealth] = (),
    previous: Bundle | None = None,
) -> GateReport:
    """Run every check. A bundle may be promoted only if ``passed`` is True."""
    report = GateReport()
    report.merge(check_structure(cards))
    report.merge(check_sources(sources))
    report.merge(check_against_previous(cards, previous))
    return report


def diff_summary(cards: Sequence[Card], previous: Bundle | None) -> str:
    """One-line human summary of what changed, for the pipeline's output."""
    if previous is None:
        return f"{len(cards)} cards (first bundle)"
    old = {c.card_id: c for c in previous.catalog}
    new = {c.card_id: c for c in cards}
    added = len(set(new) - set(old))
    removed = len(set(old) - set(new))
    changed = sum(
        1
        for cid in set(old) & set(new)
        if (old[cid].effect, old[cid].cost, old[cid].might, old[cid].card_type)
        != (new[cid].effect, new[cid].cost, new[cid].might, new[cid].card_type)
    )
    return f"{len(cards)} cards (+{added} new, -{removed} removed, ~{changed} changed)"
