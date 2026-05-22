from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from app.api.routers.meta import _sort_meta_rows
from app.domain.meta_scoring import (
    deck_competitive_rank_score,
    deck_legend_meta_rank_score,
    deck_meta_sort_score,
    legend_profile,
    resolve_legend_profile_key,
)

_INDEX_PATH = Path(__file__).resolve().parents[1] / "artifacts" / "meta-deck-index.json"

_TIER1_LEGENDS = {"leblanc", "originsmasteryi", "irelia", "diana", "fiora"}
_TIER5_LEGENDS = {
    "vi",
    "poppy",
    "pyke",
    "volibear",
    "jhin",
    "ahri",
    "lucian",
    "jax",
    "darius",
    "jinx",
    "lux",
    "leesin",
    "rumble",
    "renataglasc",
    "ivern",
}


def _load_index_entries() -> list[dict]:
    if not _INDEX_PATH.is_file():
        pytest.skip("meta-deck-index.json not present")
    data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return list(data.get("entries") or data.get("decks") or [])


def _legend_short(leader_title: str) -> str:
    return resolve_legend_profile_key(leader_title)


class _SimRow:
    __slots__ = (
        "deck_name",
        "meta_score",
        "recommendation_score",
        "competitive_score",
        "completion_pct",
        "missing_copies",
        "missing_unique_cards",
        "is_buildable",
        "deck_price",
        "age_days",
        "views",
        "likes",
        "leader_title",
    )

    def __init__(self, leader_title: str, meta_score: float | None, **kwargs: object) -> None:
        self.leader_title = leader_title
        self.meta_score = meta_score
        self.deck_name = str(kwargs.get("deck_name") or leader_title)
        self.recommendation_score = kwargs.get("recommendation_score")
        self.competitive_score = kwargs.get("competitive_score")
        self.completion_pct = kwargs.get("completion_pct")
        self.missing_copies = kwargs.get("missing_copies")
        self.missing_unique_cards = kwargs.get("missing_unique_cards")
        self.is_buildable = kwargs.get("is_buildable")
        self.deck_price = kwargs.get("deck_price")
        self.age_days = kwargs.get("age_days")
        self.views = kwargs.get("views")
        self.likes = kwargs.get("likes")


def _rows_from_index(entries: list[dict]) -> list[_SimRow]:
    rows: list[_SimRow] = []
    for entry in entries:
        leader = str(entry.get("leaderTitle") or entry.get("leader_title") or "")
        ms = entry.get("metaScore") or entry.get("meta_score")
        rows.append(
            _SimRow(
                leader_title=leader,
                meta_score=float(ms) if ms is not None else None,
                age_days=entry.get("ageDays") or entry.get("age_days"),
                views=entry.get("views"),
                likes=entry.get("likes"),
                competitive_score=deck_competitive_rank_score(
                    leader_title=leader,
                    meta_score=ms,
                    age_days=entry.get("ageDays") or entry.get("age_days"),
                    views=entry.get("views"),
                ),
            )
        )
    return rows


def _first_unique_legend_keys(ranked: list[_SimRow], limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for row in ranked:
        key = _legend_short(row.leader_title)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
        if len(out) >= limit:
            break
    return out


def test_competitive_score_ordering_within_tiers() -> None:
    irelia = deck_competitive_rank_score(leader_title="Irelia, Blade Dancer", meta_score=22.0)
    fiora = deck_competitive_rank_score(leader_title="Fiora, Grand Duelist", meta_score=22.0)
    garen = deck_competitive_rank_score(leader_title="Garen, Might of Demacia", meta_score=22.0)
    vi = deck_competitive_rank_score(leader_title="Vi, Piltover Enforcer", meta_score=30.0)
    unleashed = deck_competitive_rank_score(leader_title="Master Yi, Wuju Master", meta_score=28.0)
    origins = deck_competitive_rank_score(leader_title="Master Yi, Wuju Bladesman", meta_score=22.0)
    assert irelia > fiora > garen
    assert origins > unleashed > vi
    assert irelia > unleashed


def test_meta_sort_score_reflects_popularity_leaderboard() -> None:
    scores = [
        ("leblanc", deck_legend_meta_rank_score("LeBlanc, the Deceiver")),
        ("originsmasteryi", deck_legend_meta_rank_score("Master Yi, Wuju Bladesman")),
        ("irelia", deck_legend_meta_rank_score("Irelia, Blade Dancer")),
        ("diana", deck_legend_meta_rank_score("Diana, Scorn of the Moon")),
        ("fiora", deck_legend_meta_rank_score("Fiora, Grand Duelist")),
        ("draven", deck_legend_meta_rank_score("Draven, Glorious Executioner")),
        ("vi", deck_legend_meta_rank_score("Vi, Piltover Enforcer")),
    ]
    ordered = [name for name, _ in sorted(scores, key=lambda row: -row[1])]
    assert ordered[:5] == ["leblanc", "originsmasteryi", "irelia", "diana", "fiora"]
    assert ordered.index("vi") > ordered.index("draven")
    assert deck_meta_sort_score(leader_title="Vi, Piltover Enforcer", meta_score=40.0) < deck_legend_meta_rank_score(
        "LeBlanc, the Deceiver"
    )


def test_index_meta_sort_surfaces_tier_one_popular_legends() -> None:
    entries = _load_index_entries()
    rows = _rows_from_index(entries)
    ranked = _sort_meta_rows(rows, sort_by="meta", sort_dir="desc")
    top_legends = _first_unique_legend_keys(ranked, 8)
    assert len(top_legends) >= 5
    assert top_legends[0] in {"leblanc", "originsmasteryi"}
    assert len([key for key in top_legends[:8] if key in _TIER1_LEGENDS]) >= 4
    assert not any(key in _TIER5_LEGENDS for key in top_legends[:6])


def test_index_competitive_sort_surfaces_multiple_tier_one_legends() -> None:
    entries = _load_index_entries()
    rows = _rows_from_index(entries)
    ranked = _sort_meta_rows(rows, sort_by="competitive", sort_dir="desc")
    top_legends = _first_unique_legend_keys(ranked, 10)
    tier1_hits = [key for key in top_legends if key in _TIER1_LEGENDS]
    assert len(tier1_hits) >= 4
    assert top_legends[0] in {"irelia", "originsmasteryi", "leblanc"}
    assert not any(key in _TIER5_LEGENDS for key in top_legends[:8])


def test_index_competitive_unleashed_yi_below_origins_master_yi() -> None:
    entries = _load_index_entries()
    origins_scores = []
    unleashed_scores = []
    for entry in entries:
        leader = str(entry.get("leaderTitle") or "")
        key = _legend_short(leader)
        ms = entry.get("metaScore") or entry.get("meta_score")
        score = deck_competitive_rank_score(leader_title=leader, meta_score=ms)
        if key == "originsmasteryi":
            origins_scores.append(score)
        elif key == "unleashedyi":
            unleashed_scores.append(score)
    assert origins_scores and unleashed_scores
    assert max(origins_scores) > max(unleashed_scores)


def test_tier_five_profiles_are_lowest_tier() -> None:
    for key in _TIER5_LEGENDS:
        assert legend_profile(key).tier == 5
