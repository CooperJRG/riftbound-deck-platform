from __future__ import annotations

from dataclasses import dataclass

from app.api.routers.meta import _candidate_pool_limit, _recommendation_score, _sort_meta_rows
from app.domain.meta_scoring import (
    collection_neutral_recommendation_score,
    deck_competitive_rank_score,
    deck_meta_sort_score,
    legend_profile,
    resolve_legend_profile_key,
)
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


@dataclass
class _RankRow:
    deck_name: str
    meta_score: float | None = None
    recommendation_score: float | None = None
    competitive_score: float | None = None
    completion_pct: float | None = None
    missing_copies: int | None = None
    missing_unique_cards: int | None = None
    is_buildable: bool | None = None
    deck_price: float | None = None
    age_days: float | None = None
    views: float | None = None
    likes: int | None = None
    leader_title: str = ""


def test_meta_sort_uses_legend_popularity_not_recommendation() -> None:
    rows = [
        _RankRow(
            "HighRecLowPop",
            meta_score=35.0,
            recommendation_score=200.0,
            leader_title="Vi, Piltover Enforcer",
        ),
        _RankRow(
            "LowRecHighPop",
            meta_score=10.0,
            recommendation_score=1.0,
            leader_title="LeBlanc, the Deceiver",
        ),
    ]
    ranked = _sort_meta_rows(rows, sort_by="meta", sort_dir="desc")
    assert [row.deck_name for row in ranked] == ["LowRecHighPop", "HighRecLowPop"]


def test_competitive_sort_prefers_tier_one_legend_at_equal_meta() -> None:
    leblanc = deck_competitive_rank_score(leader_title="LeBlanc, the Deceiver", meta_score=22.0, age_days=5.0, views=100.0)
    garen = deck_competitive_rank_score(leader_title="Garen, Might of Demacia", meta_score=22.0, age_days=5.0, views=100.0)
    assert leblanc > garen
    rows = [
        _RankRow("GarenDeck", competitive_score=garen, meta_score=22.0, leader_title="Garen"),
        _RankRow("LeblancDeck", competitive_score=leblanc, meta_score=22.0, leader_title="LeBlanc"),
    ]
    ranked = _sort_meta_rows(rows, sort_by="competitive", sort_dir="desc")
    assert ranked[0].deck_name == "LeblancDeck"


def test_collection_neutral_recommendation_ignores_missing_cards() -> None:
    with_collection = _recommendation_score(
        completion_pct=20.0,
        missing_copies=40,
        missing_unique_cards=20,
        meta_score=25.0,
        is_buildable=False,
    )
    without_collection = collection_neutral_recommendation_score(
        leader_title="LeBlanc, the Deceiver",
        meta_score=25.0,
        age_days=3.0,
        views=50.0,
    )
    assert without_collection > with_collection


def test_master_yi_variant_resolution() -> None:
    assert resolve_legend_profile_key("Master Yi, Wuju Bladesman") == "originsmasteryi"
    assert resolve_legend_profile_key("Master Yi, Wuju Master") == "unleashedyi"
    assert legend_profile("Master Yi, Wuju Master").tier == 4
    assert legend_profile("Master Yi, Wuju Bladesman").tier == 1


def test_meta_sort_score_orders_popular_tier_one_legends() -> None:
    leblanc = deck_meta_sort_score(leader_title="LeBlanc, the Deceiver", meta_score=20.0)
    vi = deck_meta_sort_score(leader_title="Vi, Piltover Enforcer", meta_score=35.0)
    assert leblanc > vi
