"""Focused tests for recommendations that do not belong in the legend index."""

from riftbound.domain.meta import MetaDeck, Provenance
from riftbound.domain.suggest import sideboard_suggestions


def _published(deck, slug: str, sideboard: dict[str, int]) -> MetaDeck:
    return MetaDeck(
        deck=deck.with_meta(sideboard=sideboard),
        provenance=Provenance(source="test", source_slug=slug, url=""),
    )


def test_sideboard_suggestions_come_from_published_sideboards(
    legal_deck, catalog, bound_rules,
):
    decks = [
        _published(legal_deck, "first", {"filler-10": 2, "filler-11": 1}),
        _published(legal_deck, "second", {"filler-10": 2, "filler-12": 2}),
    ]

    rows = sideboard_suggestions(
        legal_deck, decks, {"first": 2.0, "second": 1.0}, catalog, bound_rules
    )

    assert rows[0].card_id == "filler-10"
    assert rows[0].copies == 2
    assert rows[0].reason == "in 100% of comparable sideboards"


def test_sideboard_suggestions_respect_the_combined_copy_limit(
    legal_deck, catalog, bound_rules,
):
    published = _published(legal_deck, "field", {"filler-10": 2})
    player = legal_deck.with_meta(main={**legal_deck.main, "filler-10": 3})

    rows = sideboard_suggestions(
        player, [published], {"field": 1.0}, catalog, bound_rules
    )

    assert all(row.card_id != "filler-10" for row in rows)


def test_missing_published_sideboards_are_not_counted_as_empty_data(
    legal_deck, catalog, bound_rules,
):
    rows = sideboard_suggestions(
        legal_deck,
        [_published(legal_deck, "missing", {}), _published(legal_deck, "known", {"filler-11": 1})],
        {"missing": 50.0, "known": 1.0},
        catalog,
        bound_rules,
    )

    assert rows[0].reason == "in 100% of comparable sideboards"
