from __future__ import annotations

from app.api.routers.meta import _candidate_pool_limit, _recommendation_score, _sort_meta_rows
from app.domain.models import DeckPayload, MetaDeckSummary


def _deck_row(
    name: str,
    *,
    price: float | None,
    recommendation: float,
    completion: float = 100.0,
    missing_copies: int = 0,
    missing_unique: int = 0,
    is_buildable: bool = True,
    meta_score: float = 20.0,
) -> MetaDeckSummary:
    return MetaDeckSummary(
        source="meta",
        deckId=name.lower().replace(" ", "-"),
        deckName=name,
        deckUrl="",
        metaScore=meta_score,
        deckPrice=price,
        isBuildable=is_buildable,
        completionPct=completion,
        missingCopies=missing_copies,
        missingUniqueCards=missing_unique,
        recommendationScore=recommendation,
        deck=DeckPayload(name=name, main={}, runes={}, battlefields=[], sideboard={}),
    )


def test_recommendation_score_matches_legacy_formula() -> None:
    score = _recommendation_score(
        completion_pct=82.5,
        missing_copies=4,
        missing_unique_cards=2,
        meta_score=27.0,
        is_buildable=False,
    )
    # Hand-computed from legacy riftbound/deck_matcher formula.
    assert score == 54.5611


def test_price_sort_descending_by_default_and_none_last() -> None:
    rows = [
        _deck_row("Budget", price=22.5, recommendation=10.0),
        _deck_row("Premium", price=180.0, recommendation=9.0),
        _deck_row("Unknown", price=None, recommendation=99.0),
    ]
    ranked = _sort_meta_rows(rows, sort_by="price", sort_dir="desc")
    assert [row.deck_name for row in ranked] == ["Premium", "Budget", "Unknown"]


def test_candidate_pool_uses_thousands_of_decks() -> None:
    assert _candidate_pool_limit(60) >= 5000
    assert _candidate_pool_limit(300) == 15000
