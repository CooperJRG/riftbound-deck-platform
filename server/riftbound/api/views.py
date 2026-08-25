"""Domain -> API view conversion, kept out of the route handlers."""

from __future__ import annotations

from ..domain.availability import Availability, AvailabilityProfile, DeckCoverage
from ..domain.cards import Card, Catalog
from ..domain.deck import Deck
from ..domain.validator import ValidationResult
from .schemas import (
    AvailabilityView,
    CardAvailabilityView,
    CardView,
    CoverageView,
    ExcludedCardView,
    ExclusionRuleView,
    IssueView,
    PrintingView,
    ValidationView,
)


def card_view(card: Card) -> CardView:
    return CardView(
        card_id=card.card_id,
        name=card.name,
        card_type=card.card_type,
        super_type=card.super_type,
        domains=list(card.domains),
        cost=card.cost,
        might=card.might,
        tags=list(card.tags),
        champion_tags=list(card.champion_tags),
        effect=card.effect,
        unique=card.unique,
        rarity=card.rarity,
        set_codes=list(card.set_codes),
        image_url=card.image_url,
        printings=[
            PrintingView(
                print_id=p.print_id,
                title=p.title,
                set_code=p.set_code,
                card_number=p.card_number,
                rarity=p.rarity,
                promo=p.promo,
                image_url=p.image_url,
            )
            for p in card.printings
        ],
    )


def card_availability_view(card: Card, state: Availability) -> CardAvailabilityView:
    return CardAvailabilityView(
        card=card_view(card),
        weight=state.weight,
        available=state.available,
        owned_copies=state.owned_copies,
        max_copies=state.max_copies,
        reason=state.reason,
    )


def coverage_view(coverage: DeckCoverage) -> CoverageView:
    return CoverageView(
        total_copies=coverage.total_copies,
        available_copies=coverage.available_copies,
        penalised_copies=coverage.penalised_copies,
        ratio=round(coverage.ratio, 4),
        complete=coverage.is_complete,
        missing=[
            {"cardId": card_id, "copies": copies, "reason": reason}
            for card_id, copies, reason in coverage.missing
        ],
    )


def validation_view(result: ValidationResult, coverage: DeckCoverage) -> ValidationView:
    return ValidationView(
        legal=result.legal,
        issues=[
            IssueView(
                code=i.code,
                field=i.field,
                message=i.message,
                rule_refs=list(i.rule_refs),
                card_id=i.card_id,
                severity=i.severity,
            )
            for i in result.issues
        ],
        main_total=result.main_total,
        rune_total=result.rune_total,
        sideboard_total=result.sideboard_total,
        battlefield_count=result.battlefield_count,
        legend_domains=list(result.legend_domains),
        coverage=coverage_view(coverage),
    )


def deck_dict(deck: Deck) -> dict:
    return {
        "name": deck.name,
        "format": deck.format,
        "legendId": deck.legend_id,
        "championId": deck.champion_id,
        "main": dict(deck.main),
        "runes": dict(deck.runes),
        "battlefields": list(deck.battlefields),
        "sideboard": dict(deck.sideboard),
    }


def availability_view(
    profile: AvailabilityProfile, catalog: Catalog | None = None
) -> AvailabilityView:
    def named(card_id: str) -> ExcludedCardView:
        card = catalog.get(card_id) if catalog is not None else None
        # Fall back to the id when a bundle no longer knows the card, so an exclusion
        # made before a data refresh is still visible and removable.
        return ExcludedCardView(card_id=card_id, name=card.name if card else card_id)

    return AvailabilityView(
        mode=profile.mode,
        strict=profile.strict,
        penalty=profile.penalty,
        description=profile.describe(),
        excluded_cards=[named(cid) for cid in sorted(profile.excluded_cards)],
        rules=[
            ExclusionRuleView(kind=r.kind, value=r.value, description=r.describe())
            for r in profile.exclusion_rules
        ],
        owned_card_count=len(profile.owned),
    )
