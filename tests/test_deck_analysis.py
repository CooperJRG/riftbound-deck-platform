from dataclasses import replace

from riftbound.domain.deck_analysis import nearest_field_match
from riftbound.domain.meta import (
    EVIDENCE_TOURNAMENT_ENTRY,
    MetaDeck,
    Provenance,
)


def _published(deck, slug: str, *, tournament: bool = False) -> MetaDeck:
    return MetaDeck(
        deck=deck,
        provenance=Provenance(
            source="test",
            source_slug=slug,
            url="",
            evidence=EVIDENCE_TOURNAMENT_ENTRY if tournament else "community",
        ),
    )


def test_exact_published_list_is_a_complete_field_match(legal_deck, catalog):
    match = nearest_field_match(
        legal_deck,
        [_published(legal_deck, "exact", tournament=True)],
        catalog,
        {"exact": 10.0},
    )

    assert match.available
    assert match.similarity == 1
    assert match.copy_changes == 0
    assert match.sample_decks == 1
    assert match.tournament_decks == 1


def test_closest_list_is_similarity_first_and_quality_only_breaks_ties(legal_deck, catalog):
    close = legal_deck.with_meta(main={**legal_deck.main, "filler-01": 2, "filler-10": 1})
    far = legal_deck.with_meta(main={"filler-10": 3, "filler-11": 3})
    match = nearest_field_match(
        legal_deck,
        [_published(close, "close"), _published(far, "popular")],
        catalog,
        {"close": 1.0, "popular": 999.0},
    )

    assert match.reference_deck_id == "close"
    assert match.copy_changes == 1


def test_completeness_follows_the_formats_own_main_deck_size(legal_deck, catalog, bound_rules):
    """40 is only ever true for constructed. A format with a smaller main deck -- e.g.
    skirmish's 30 -- must not be judged incomplete once it reaches its own size, and
    without passing `rules` in, the fallback default must not silently apply to a
    format that says otherwise."""
    small_format = replace(
        bound_rules.rules, constraints={**bound_rules.rules.constraints, "main_deck_size_exact": 30}
    ).bind(catalog)

    dropped = {"filler-07", "filler-08", "filler-09", "singular-relic"}
    thirty_card = legal_deck.with_meta(
        main={cid: n for cid, n in legal_deck.main.items() if cid not in dropped}
    )
    assert thirty_card.main_total == 30, "fixture must actually be at the smaller size"

    published = [_published(legal_deck, "the-forty-card-one", tournament=True)]

    # Judged against the small format's own rule: complete, so the similarity-percent
    # phrasing applies rather than "N of M chosen card names".
    match = nearest_field_match(thirty_card, published, catalog, rules=small_format)
    assert "card-family overlap" in match.summary

    # Judged with no rules supplied, or against the 40-card default: correctly read as
    # short, because nothing told it 30 was this deck's actual target.
    default_match = nearest_field_match(thirty_card, published, catalog)
    assert "chosen card names appear" in default_match.summary


def test_missing_identity_or_published_data_is_explained_not_raised(legal_deck, catalog):
    empty = legal_deck.with_meta(legend_id="", main={})
    assert not nearest_field_match(empty, (), catalog).available

    unknown_champion = legal_deck.with_meta(champion_id="missing-champion")
    match = nearest_field_match(
        unknown_champion,
        [_published(legal_deck, "known")],
        catalog,
    )
    assert not match.available
    assert "No complete published lists" in match.summary
