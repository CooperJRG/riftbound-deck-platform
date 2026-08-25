"""Deck legality, checked against a data-driven format profile.

Every issue carries a machine-readable ``code``, the ``field`` it applies to, the
``card_id`` it concerns where relevant, and the rulebook sections it comes from -- so
the UI can point at the offending card and cite the rule.

Unknown cards are reported as an issue, never raised and never dropped. A deck saved
before a data refresh must survive one that renames or removes a card: the player
sees "this card is no longer in the card data" and keeps their list.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Mapping

from .cards import Card, Catalog
from .deck import Deck
from .rules import BoundRules

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    code: str
    field: str
    message: str
    rule_refs: tuple[str, ...] = ()
    card_id: str = ""
    severity: str = SEVERITY_ERROR


@dataclass(frozen=True)
class ValidationResult:
    legal: bool
    issues: tuple[Issue, ...]
    main_total: int
    rune_total: int
    sideboard_total: int
    battlefield_count: int
    legend_domains: tuple[str, ...]

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.severity == SEVERITY_ERROR)

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.severity == SEVERITY_WARNING)


class _Collector:
    def __init__(self, rules: BoundRules):
        self._rules = rules
        self.issues: list[Issue] = []

    def add(
        self,
        code: str,
        field_name: str,
        message: str,
        ref_key: str,
        *,
        card_id: str = "",
        severity: str = SEVERITY_ERROR,
    ) -> None:
        self.issues.append(
            Issue(
                code=code,
                field=field_name,
                message=message,
                rule_refs=self._rules.refs(ref_key),
                card_id=card_id,
                severity=severity,
            )
        )


def _lookup(
    catalog: Catalog, card_id: str, *, collector: _Collector, field_name: str
) -> Card | None:
    """Resolve a card, reporting rather than raising when the bundle lacks it."""
    if not card_id:
        return None
    card = catalog.get(card_id)
    if card is None:
        collector.add(
            "UNKNOWN_CARD",
            field_name,
            f"'{card_id}' is not in the current card data. It may have been renamed "
            f"or removed upstream; your deck is unchanged.",
            "",
            card_id=card_id,
            severity=SEVERITY_WARNING,
        )
    return card


def validate(deck: Deck, *, rules: BoundRules, catalog: Catalog) -> ValidationResult:
    """Check a deck against a format. Pure: no I/O, no mutation."""
    collector = _Collector(rules)

    legend_type = rules.str_constraint("legend_card_type", "Legend")
    champion_super = rules.str_constraint("champion_super_type", "Champion")
    rune_type = rules.str_constraint("rune_card_type", "Rune")
    battlefield_type = rules.str_constraint("battlefield_card_type", "Battlefield")
    domain_enforced = rules.bool_constraint("domain_identity_enforced", True)

    # -- legend -----------------------------------------------------------------
    legend = _lookup(catalog, deck.legend_id, collector=collector, field_name="legendId")
    legend_domains: tuple[str, ...] = ()
    legend_champion_tags: set[str] = set()

    if rules.bool_constraint("legend_required", True) and not deck.legend_id:
        collector.add("LEGEND_REQUIRED", "legendId", "A legend is required.", "legend_required")
    if legend is not None:
        if legend.card_type != legend_type:
            collector.add(
                "LEGEND_TYPE", "legendId",
                f"The legend slot must hold a {legend_type}; '{legend.name}' is a {legend.card_type}.",
                "legend_type", card_id=legend.card_id,
            )
        if legend.domains_ok:
            legend_domains = legend.domains
        legend_champion_tags = {t.casefold() for t in legend.champion_tags}

    allowed_domains = set(legend_domains) if domain_enforced else set()

    # -- chosen champion --------------------------------------------------------
    champion = _lookup(catalog, deck.champion_id, collector=collector, field_name="championId")
    if rules.bool_constraint("chosen_champion_required", True) and not deck.champion_id:
        collector.add(
            "CHAMPION_REQUIRED", "championId",
            "A chosen champion is required.", "chosen_champion_required",
        )
    if champion is not None:
        if champion.super_type != champion_super:
            collector.add(
                "CHAMPION_TYPE", "championId",
                f"The chosen champion must be a {champion_super}; '{champion.name}' is not.",
                "chosen_champion_type", card_id=champion.card_id,
            )
        if legend_champion_tags:
            tags = {t.casefold() for t in champion.champion_tags}
            if not (tags & legend_champion_tags):
                collector.add(
                    "CHAMPION_TAG_MISMATCH", "championId",
                    f"'{champion.name}' does not share a champion tag with your legend.",
                    "chosen_champion_tag_match", card_id=champion.card_id,
                )
        if deck.champion_id not in deck.main:
            collector.add(
                "CHAMPION_NOT_IN_MAIN", "championId",
                f"'{champion.name}' must also be in the main deck.",
                "chosen_champion_in_main", card_id=champion.card_id,
            )

    # -- main deck --------------------------------------------------------------
    main_size = rules.int_constraint("main_deck_size_exact", 0)
    if main_size and deck.main_total != main_size:
        collector.add(
            "MAIN_SIZE", "main",
            f"The main deck must contain exactly {main_size} cards; it has {deck.main_total}.",
            "main_deck_size",
        )

    allowed_main = set(rules.list_constraint("allowed_main_card_types"))
    copy_limit = rules.int_constraint("main_copy_limit", 3)
    combined_limit = rules.int_constraint("combined_main_sideboard_copy_limit", 0)

    _check_zone(
        deck.main, "main", catalog, collector,
        allowed_types=allowed_main, allowed_domains=allowed_domains,
        copy_limit=copy_limit, rules=rules,
        type_ref="main_card_types", domain_ref="domain_identity_main", copy_ref="main_copy_limit",
    )

    # -- runes ------------------------------------------------------------------
    rune_count = rules.int_constraint("rune_count_exact", 0)
    if rune_count and deck.rune_total != rune_count:
        collector.add(
            "RUNE_COUNT", "runes",
            f"You must play exactly {rune_count} runes; you have {deck.rune_total}.",
            "rune_count",
        )
    _check_zone(
        deck.runes, "runes", catalog, collector,
        allowed_types={rune_type}, allowed_domains=allowed_domains,
        copy_limit=0, rules=rules,
        type_ref="rune_card_type", domain_ref="domain_identity_runes", copy_ref="",
    )

    # -- battlefields -----------------------------------------------------------
    bf_count = rules.int_constraint("battlefield_count_exact", 0)
    if bf_count and len(deck.battlefields) != bf_count:
        collector.add(
            "BATTLEFIELD_COUNT", "battlefields",
            f"You must play exactly {bf_count} battlefields; you have {len(deck.battlefields)}.",
            "battlefield_count",
        )
    if rules.bool_constraint("battlefield_unique_required", False):
        for card_id, count in Counter(deck.battlefields).items():
            if count > 1:
                card = catalog.get(card_id)
                collector.add(
                    "BATTLEFIELD_DUPLICATE", "battlefields",
                    f"'{card.name if card else card_id}' is included {count} times; "
                    f"battlefields must all be different.",
                    "battlefield_unique", card_id=card_id,
                )
    for card_id in dict.fromkeys(deck.battlefields):
        card = _lookup(catalog, card_id, collector=collector, field_name="battlefields")
        if card is None:
            continue
        if card.card_type != battlefield_type:
            collector.add(
                "BATTLEFIELD_TYPE", "battlefields",
                f"'{card.name}' is a {card.card_type}, not a {battlefield_type}.",
                "battlefield_type", card_id=card_id,
            )
        if allowed_domains and not card.in_domains(allowed_domains):
            collector.add(
                "BATTLEFIELD_DOMAIN", "battlefields",
                f"'{card.name}' is outside your legend's domain identity.",
                "domain_identity_battlefields", card_id=card_id,
            )

    # -- sideboard --------------------------------------------------------------
    sideboard_max = rules.int_constraint("sideboard_max", 0)
    if sideboard_max and deck.sideboard_total > sideboard_max:
        collector.add(
            "SIDEBOARD_SIZE", "sideboard",
            f"The sideboard holds at most {sideboard_max} cards; you have {deck.sideboard_total}.",
            "sideboard_max",
        )
    _check_zone(
        deck.sideboard, "sideboard", catalog, collector,
        allowed_types=set(rules.list_constraint("allowed_sideboard_card_types")),
        allowed_domains=allowed_domains, copy_limit=0, rules=rules,
        type_ref="sideboard_card_types", domain_ref="domain_identity_sideboard", copy_ref="",
    )

    # -- combined copy limit across main + sideboard ----------------------------
    if combined_limit:
        combined: Counter[str] = Counter(deck.main)
        combined.update(deck.sideboard)
        for card_id, total in combined.items():
            card = catalog.get(card_id)
            limit = 1 if (card is not None and card.unique) else combined_limit
            if total > limit:
                collector.add(
                    "COMBINED_COPY_LIMIT", "sideboard",
                    f"'{card.name if card else card_id}' appears {total} times across the main "
                    f"deck and sideboard; the limit is {limit}.",
                    "combined_copy_limit", card_id=card_id,
                )

    # -- signature limit --------------------------------------------------------
    signature_max = rules.int_constraint("signature_max_total", 0)
    if signature_max:
        signature_total = sum(
            qty
            for card_id, qty in deck.main.items()
            if (c := catalog.get(card_id)) is not None and c.super_type == "Signature"
        )
        if signature_total > signature_max:
            collector.add(
                "SIGNATURE_LIMIT", "main",
                f"You may play at most {signature_max} signature cards; you have {signature_total}.",
                "signature_limit",
            )

    # -- bans -------------------------------------------------------------------
    for card_id in deck.all_card_ids():
        if rules.is_banned(card_id):
            card = catalog.get(card_id)
            collector.add(
                "BANNED", "main",
                f"'{card.name if card else card_id}' is banned in {rules.format_name}.",
                "banned_list", card_id=card_id,
            )

    issues = tuple(collector.issues)
    return ValidationResult(
        legal=not any(i.severity == SEVERITY_ERROR for i in issues),
        issues=issues,
        main_total=deck.main_total,
        rune_total=deck.rune_total,
        sideboard_total=deck.sideboard_total,
        battlefield_count=len(deck.battlefields),
        legend_domains=legend_domains,
    )


def _check_zone(
    counts: Mapping[str, int],
    zone: str,
    catalog: Catalog,
    collector: _Collector,
    *,
    allowed_types: set[str],
    allowed_domains: set[str],
    copy_limit: int,
    rules: BoundRules,
    type_ref: str,
    domain_ref: str,
    copy_ref: str,
) -> None:
    """Per-card checks shared by the main deck, runes and sideboard."""
    for card_id, qty in counts.items():
        card = _lookup(catalog, card_id, collector=collector, field_name=zone)
        if card is None:
            continue
        if allowed_types and card.card_type not in allowed_types:
            collector.add(
                f"{zone.upper()}_CARD_TYPE", zone,
                f"'{card.name}' is a {card.card_type or 'card with no type'} and cannot go in "
                f"the {zone}.",
                type_ref, card_id=card_id,
            )
        if allowed_domains and not card.in_domains(allowed_domains):
            collector.add(
                f"{zone.upper()}_DOMAIN", zone,
                f"'{card.name}' is outside your legend's domain identity.",
                domain_ref, card_id=card_id,
            )
        if copy_limit:
            limit = 1 if card.unique else copy_limit
            if qty > limit:
                collector.add(
                    f"{zone.upper()}_COPY_LIMIT", zone,
                    f"'{card.name}' is included {qty} times; the limit is {limit}"
                    + (" because it is unique." if card.unique else "."),
                    copy_ref, card_id=card_id,
                )
