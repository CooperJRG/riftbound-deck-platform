from __future__ import annotations

import math
from dataclasses import dataclass

from app.domain.normalization import normalize_card_key

_MAX_POPULARITY_DECKS = 747


@dataclass(frozen=True)
class LegendProfile:
    """May 2026 riftbound.gg tournament tier + legend popularity snapshot."""

    key: str
    tier: int
    wins: int
    top8: int
    deck_count: int
    avg_price: float


# Tournament tiers (64+ events) + deck counts / avg prices from riftbound.gg (May 2026).
_LEGEND_PROFILES: dict[str, LegendProfile] = {
    # Tier 1
    "leblanc": LegendProfile("leblanc", 1, 2, 14, 747, 272.0),
    "originsmasteryi": LegendProfile("originsmasteryi", 1, 4, 35, 681, 251.0),
    "irelia": LegendProfile("irelia", 1, 6, 21, 670, 172.0),
    "diana": LegendProfile("diana", 1, 3, 13, 551, 239.0),
    "fiora": LegendProfile("fiora", 1, 1, 11, 520, 211.0),
    # Tier 2
    "missfortune": LegendProfile("missfortune", 2, 1, 4, 293, 476.0),
    "sivir": LegendProfile("sivir", 2, 0, 6, 210, 424.0),
    "sett": LegendProfile("sett", 2, 2, 0, 185, 123.0),
    "vex": LegendProfile("vex", 2, 0, 5, 490, 125.0),
    "rengar": LegendProfile("rengar", 2, 0, 5, 212, 221.0),
    "draven": LegendProfile("draven", 2, 0, 5, 240, 235.0),
    "azir": LegendProfile("azir", 2, 1, 2, 332, 88.0),
    # Tier 3
    "kaisa": LegendProfile("kaisa", 3, 0, 4, 370, 260.0),
    "ezreal": LegendProfile("ezreal", 3, 1, 1, 161, 194.0),
    "khazix": LegendProfile("khazix", 3, 0, 2, 257, 167.0),
    "viktor": LegendProfile("viktor", 3, 0, 3, 285, 99.0),
    "annie": LegendProfile("annie", 3, 0, 3, 126, 280.0),
    "leona": LegendProfile("leona", 3, 0, 3, 81, 109.0),
    "lillia": LegendProfile("lillia", 3, 0, 2, 476, 241.0),
    # Tier 4
    "unleashedyi": LegendProfile("unleashedyi", 4, 1, 1, 283, 83.0),
    "ornn": LegendProfile("ornn", 4, 0, 1, 155, 178.0),
    "reksai": LegendProfile("reksai", 4, 0, 1, 67, 110.0),
    "teemo": LegendProfile("teemo", 4, 0, 1, 78, 209.0),
    "yasuo": LegendProfile("yasuo", 4, 0, 1, 44, 134.0),
    "garen": LegendProfile("garen", 4, 0, 1, 25, 303.0),
    # Tier 5 (listed on tier page, low competitive relevance)
    "vi": LegendProfile("vi", 5, 0, 0, 103, 139.0),
    "poppy": LegendProfile("poppy", 5, 0, 0, 89, 197.0),
    "pyke": LegendProfile("pyke", 5, 0, 0, 186, 160.0),
    "volibear": LegendProfile("volibear", 5, 0, 0, 63, 182.0),
    "jhin": LegendProfile("jhin", 5, 0, 0, 111, 210.0),
    "ahri": LegendProfile("ahri", 5, 0, 0, 75, 228.0),
    "lucian": LegendProfile("lucian", 5, 0, 0, 59, 197.0),
    "jax": LegendProfile("jax", 5, 0, 0, 48, 101.0),
    "darius": LegendProfile("darius", 5, 0, 0, 46, 184.0),
    "jinx": LegendProfile("jinx", 5, 0, 0, 41, 132.0),
    "lux": LegendProfile("lux", 5, 0, 0, 53, 163.0),
    "leesin": LegendProfile("leesin", 5, 0, 0, 25, 141.0),
    "rumble": LegendProfile("rumble", 5, 0, 0, 26, 110.0),
    "renataglasc": LegendProfile("renataglasc", 5, 0, 0, 19, 166.0),
    "ivern": LegendProfile("ivern", 5, 0, 0, 99, 56.0),
}

# Alias short keys from card titles -> profile key.
_SHORT_KEY_ALIASES: dict[str, str] = {
    "masteryi": "originsmasteryi",
    "kaisa": "kaisa",
    "khazix": "khazix",
    "reksai": "reksai",
    "missfortune": "missfortune",
    "leesin": "leesin",
    "renataglasc": "renataglasc",
}

_TIER_BASE_SCORE = {1: 42.0, 2: 34.0, 3: 26.0, 4: 18.0, 5: 8.0}
_DEFAULT_PROFILE = LegendProfile("unknown", 5, 0, 0, 0, 0.0)


def _leader_norm_full(leader_title: str) -> str:
    return normalize_card_key(leader_title)


def _leader_short_key(leader_title: str) -> str:
    short = str(leader_title or "").split(" - ")[0].split(",")[0].strip()
    return normalize_card_key(short)


def resolve_legend_profile_key(leader_title: str) -> str:
    full = _leader_norm_full(leader_title)
    if not full:
        return ""
    if "wujumaster" in full or full == "unleashedyi" or "unleashed" in full:
        return "unleashedyi"
    if "wujubladesman" in full:
        return "originsmasteryi"
    short = _leader_short_key(leader_title)
    if short in _LEGEND_PROFILES:
        return short
    if short in _SHORT_KEY_ALIASES:
        return _SHORT_KEY_ALIASES[short]
    for profile_key in _LEGEND_PROFILES:
        if profile_key in short or short.startswith(profile_key):
            return profile_key
    return short


def legend_profile(leader_title: str) -> LegendProfile:
    key = resolve_legend_profile_key(leader_title)
    if key in _LEGEND_PROFILES:
        return _LEGEND_PROFILES[key]
    return _DEFAULT_PROFILE


def _popularity_norm(deck_count: int) -> float:
    if deck_count <= 0 or _MAX_POPULARITY_DECKS <= 0:
        return 0.0
    return math.log1p(deck_count) / math.log1p(_MAX_POPULARITY_DECKS)


def _tournament_norm(wins: int, top8: int) -> float:
    raw = (max(0, wins) * 2.0) + (max(0, top8) * 0.45)
    return min(12.0, raw)


def legend_popularity_score(leader_title: str) -> float:
    profile = legend_profile(leader_title)
    return round(_popularity_norm(profile.deck_count) * 15.0, 4)


def legend_tournament_score(leader_title: str) -> float:
    profile = legend_profile(leader_title)
    return round(_tournament_norm(profile.wins, profile.top8), 4)


def legend_competitive_strength(leader_title: str) -> float:
    """Backward-compatible tier-ish signal (higher = stronger)."""
    profile = legend_profile(leader_title)
    tier_component = _TIER_BASE_SCORE.get(profile.tier, 8.0)
    return round(
        tier_component + legend_tournament_score(leader_title) * 0.35 + legend_popularity_score(leader_title) * 0.25,
        4,
    )


def normalize_meta_score(score: float | None) -> float:
    return max(0.0, min(40.0, float(score or 0.0)))


def recency_sort_bonus(age_days: float | None) -> float:
    if age_days is None:
        return 0.0
    age = max(0.0, float(age_days))
    if age > 30.0:
        return 0.0
    return round(2.5 * (1.0 - (age / 30.0)), 4)


def _views_bonus(views: float | None, *, cap: float, scale: float) -> float:
    return min(cap, math.log1p(max(0.0, float(views or 0.0))) * scale)


def deck_legend_meta_rank_score(leader_title: str) -> float:
    """Legend-level meta strength (popularity list + tier); used as primary Meta sort key."""
    profile = legend_profile(leader_title)
    tier_component = _TIER_BASE_SCORE.get(profile.tier, 8.0)
    popularity_linear = (profile.deck_count / float(_MAX_POPULARITY_DECKS)) * 20.0
    return round(
        popularity_linear
        + tier_component * 0.35
        + legend_tournament_score(leader_title) * 0.15,
        4,
    )


def deck_meta_sort_score(
    *,
    leader_title: str,
    meta_score: float | None,
    age_days: float | None = None,
    views: float | None = None,
) -> float:
    """Full Meta sort score: legend rank + within-legend deck engagement."""
    legend_signal = deck_legend_meta_rank_score(leader_title)
    deck_signal = min(8.0, normalize_meta_score(meta_score) * 0.22)
    return round(
        legend_signal + deck_signal + recency_sort_bonus(age_days) + _views_bonus(views, cap=1.2, scale=0.2),
        4,
    )


def collection_neutral_recommendation_score(
    *,
    leader_title: str,
    meta_score: float | None,
    age_days: float | None = None,
    views: float | None = None,
) -> float:
    """Meta fit without collection — aligns with legend popularity."""
    return deck_meta_sort_score(
        leader_title=leader_title,
        meta_score=meta_score,
        age_days=age_days,
        views=views,
    )


def deck_competitive_rank_score(
    *,
    leader_title: str,
    meta_score: float | None,
    age_days: float | None = None,
    views: float | None = None,
    profile_competitive: float | None = None,
) -> float:
    """Tournament tier + results + popularity (+ deck engagement)."""
    profile = legend_profile(leader_title)
    tier_component = _TIER_BASE_SCORE.get(profile.tier, 8.0)
    legend_signal = (
        tier_component
        + legend_tournament_score(leader_title) * 1.15
        + legend_popularity_score(leader_title) * 0.55
    )
    deck_signal = normalize_meta_score(meta_score) * 0.42
    base = legend_signal + deck_signal + recency_sort_bonus(age_days) + _views_bonus(views, cap=2.0, scale=0.35)
    profile = float(profile_competitive or 0.0)
    if profile > 0.0:
        base += min(6.0, profile * 0.06)
    return round(base, 4)


def legend_reference_price(leader_title: str) -> float | None:
    profile = legend_profile(leader_title)
    if profile.deck_count <= 0:
        return None
    return profile.avg_price


def iter_legend_profiles() -> list[LegendProfile]:
    return list(_LEGEND_PROFILES.values())
