"""Domain -> API view conversion, kept out of the route handlers."""

from __future__ import annotations

from ..domain.availability import Availability, AvailabilityProfile, DeckCoverage
from ..domain.cards import Card, Catalog
from ..domain.deck import Deck
from ..domain.meta import MetaDeck, Tournament
from ..domain.meta_scoring import ScoreBreakdown
from ..domain.validator import ValidationResult
from .schemas import (
    AvailabilityView,
    CardAvailabilityView,
    CardView,
    CostView,
    CoverageView,
    ExcludedCardView,
    ExclusionRuleView,
    IssueView,
    MetaDeckView,
    PrintingView,
    ProvenanceView,
    RepairDeckCardView,
    RepairView,
    RequirementRowView,
    ScoreView,
    SwapView,
    TournamentView,
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


def coverage_view(coverage: DeckCoverage, catalog: Catalog | None = None) -> CoverageView:
    """Coverage, with missing cards named.

    The server owns the catalogue, so it resolves these names rather than leaving the
    client to render a bare id for a card it has not happened to load. A card the
    bundle no longer knows falls back to its id, so it stays visible.
    """
    def name_of(card_id: str) -> str:
        card = catalog.get(card_id) if catalog is not None else None
        return card.name if card else card_id

    return CoverageView(
        cost=CostView(
            short=dict(coverage.cost.short),
            composition=dict(coverage.cost.composition),
            copies_short=coverage.cost.copies_short,
            scarce_short=coverage.cost.scarce_short,
            affordable=coverage.cost.is_affordable,
            summary=coverage.cost.describe(),
        ),
        total_copies=coverage.total_copies,
        available_copies=coverage.available_copies,
        penalised_copies=coverage.penalised_copies,
        ratio=round(coverage.ratio, 4),
        complete=coverage.is_complete,
        missing=[
            {
                "cardId": card_id,
                "name": name_of(card_id),
                "copies": copies,
                "reason": reason,
            }
            for card_id, copies, reason in coverage.missing
        ],
    )


def validation_view(
    result: ValidationResult, coverage: DeckCoverage, catalog: Catalog | None = None
) -> ValidationView:
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
        coverage=coverage_view(coverage, catalog),
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
        owned_rules=[
            ExclusionRuleView(kind=r.kind, value=r.value, description=r.describe())
            for r in profile.owned_rules
        ],
        owned_card_count=len(profile.owned),
    )


def tournament_view(t: Tournament) -> TournamentView:
    return TournamentView(
        slug=t.slug, name=t.name, date=t.date, format=t.format,
        players=t.players, winner=t.winner, decks_published=t.decks_published,
    )


def meta_deck_view(
    meta: MetaDeck,
    score: ScoreBreakdown,
    coverage: DeckCoverage,
    catalog: Catalog,
) -> MetaDeckView:
    p = meta.provenance
    legend = catalog.get(meta.deck.legend_id)
    champion = catalog.get(meta.deck.champion_id)
    return MetaDeckView(
        deck_id=meta.deck_id,
        name=meta.deck.name,
        legend_id=meta.deck.legend_id,
        legend_name=legend.name if legend else meta.deck.legend_id,
        champion_id=meta.deck.champion_id,
        champion_name=champion.name if champion else "",
        archetype_id=meta.archetype_id,
        domains=list(legend.domains) if legend else [],
        main_total=meta.deck.main_total,
        provenance=ProvenanceView(
            source=p.source, url=p.url, evidence=p.evidence, summary=p.describe(),
            author=p.author, published_at=p.published_at, views=p.views,
            tournament_slug=p.tournament_slug, tournament_name=p.tournament_name,
            tournament_date=p.tournament_date, placement=p.placement,
            field_size=p.field_size,
        ),
        score=ScoreView(
            total=score.total, evidence=score.evidence, placement=score.placement,
            recency=score.recency, popularity=score.popularity,
        ),
        coverage=coverage_view(coverage, catalog),
        unresolved=list(meta.unresolved),
        deck=deck_dict(meta.deck),
    )


# -- smart decks --------------------------------------------------------------


def requirement_row(
    card_id: str,
    needed: int,
    zone: str,
    knowledge,
    catalog: Catalog,
    *,
    assume_owned: bool = True,
) -> RequirementRowView:
    """One card the player is being asked about.

    The default answer is the whole ergonomic argument of the review screen, and it is
    not the same in both places the screen is used:

    * Showing a **deck**, ``assume_owned`` is true. The list is a real deck somebody
      played; the question is "what are you short of", so the default is "I have these"
      and the player only touches the exceptions.
    * Showing a **checklist**, it is false. These are cards nobody has been asked about,
      the question reads "which of these do you own", and answering "all of them" on the
      player's behalf would hand someone a deck they cannot build. Defaulting to owned
      there is a false positive -- the mirror of the false negative the engine works so
      hard to avoid, and invisible to a harness that answers truthfully.
    """
    card = catalog.get(card_id)
    known = knowledge.is_known(card_id)
    if known:
        have = min(needed, knowledge.lower_bound(card_id))
    else:
        have = needed if assume_owned else 0
    return RequirementRowView(
        card_id=card_id,
        name=card.name if card else card_id,
        zone=zone,
        needed=needed,
        image_url=card.image_url if card else "",
        rarity=card.rarity if card else "",
        known=known,
        exact=knowledge.is_exact(card_id),
        have=have,
    )


def deck_card_rows(deck, catalog: Catalog, *, added: set[str] | None = None) -> list[RepairDeckCardView]:
    """A deck resolved to names and art, grouped by zone.

    Shared by the repair panel and the finish screen, so the deck a player is handed is
    rendered by one code path however they arrived at it.
    """
    brought_in = added or set()

    def rows(counts, zone: str) -> list[RepairDeckCardView]:
        out = []
        for card_id, copies in counts.items():
            card = catalog.get(card_id)
            out.append(
                RepairDeckCardView(
                    card_id=card_id,
                    name=card.name if card else card_id,
                    image_url=card.image_url if card else "",
                    zone=zone,
                    copies=int(copies),
                    added=card_id in brought_in,
                )
            )
        # Brought-in cards first: they are what the player has not seen before, and the
        # reason they are reading this list at all.
        out.sort(key=lambda row: (not row.added, row.name))
        return out

    return (
        rows(deck.main, "main")
        + rows(deck.runes, "runes")
        + rows({b: 1 for b in deck.battlefields}, "battlefields")
    )


def repair_view(repair, catalog: Catalog, *, legal: bool) -> RepairView:
    def name_of(card_id: str) -> str:
        card = catalog.get(card_id)
        return card.name if card else card_id

    added = {swap.in_card_id for swap in repair.swaps}

    def rows(counts, zone: str) -> list[RepairDeckCardView]:
        out = []
        for card_id, copies in counts.items():
            card = catalog.get(card_id)
            out.append(
                RepairDeckCardView(
                    card_id=card_id,
                    name=card.name if card else card_id,
                    image_url=card.image_url if card else "",
                    zone=zone,
                    copies=int(copies),
                    added=card_id in added,
                )
            )
        # Brought-in cards first: they are what the player has not seen before, and the
        # reason they are reading this list at all.
        out.sort(key=lambda row: (not row.added, row.name))
        return out

    deck = repair.deck
    cards = (
        rows(deck.main, "main")
        + rows(deck.runes, "runes")
        + rows({b: 1 for b in deck.battlefields}, "battlefields")
    )

    return RepairView(
        cards=cards,
        kind=repair.kind,
        drift=repair.drift,
        swaps=[
            SwapView(
                out_card_id=s.out_card_id, out_name=name_of(s.out_card_id),
                in_card_id=s.in_card_id, in_name=name_of(s.in_card_id),
                copies=s.copies, reason=s.reason,
            )
            for s in repair.swaps
        ],
        deck=deck_dict(repair.deck),
        legal=legal,
    )
