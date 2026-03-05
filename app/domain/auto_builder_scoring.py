from __future__ import annotations

from typing import Any

import numpy as np

from app.domain.analysis import analyze_collection_completion
from app.domain.auto_builder_features import cosine_similarity
from app.domain.models import DeckPayload


def resolved_ranking_mode(ranking_mode: str, *, only_buildable: bool = False) -> str:
    if only_buildable:
        return "competitive"
    mode = str(ranking_mode or "collection").strip().lower()
    if mode in {"competitive", "hybrid"}:
        return mode
    return "collection"


def candidate_score(
    *,
    competitive_score: float,
    win_condition_match: float,
    synergy_cluster_coverage: float,
    legality_margin: float,
    curve_balance: float,
) -> float:
    score = (
        0.35 * max(0.0, min(40.0, float(competitive_score))) / 40.0
        + 0.20 * max(0.0, min(1.0, float(win_condition_match)))
        + 0.20 * max(0.0, min(1.0, float(synergy_cluster_coverage)))
        + 0.15 * max(0.0, min(1.0, float(legality_margin)))
        + 0.10 * max(0.0, min(1.0, float(curve_balance)))
    )
    return round(score * 100.0, 4)


def ranking_score(
    *,
    ranking_mode: str,
    candidate_score_value: float,
    competitive_score: float,
    buildable: bool,
    completion_pct: float,
    replacement_confidence: float,
    estimated_completion_cost: float | None,
) -> float:
    buildability = 1.0 if buildable else 0.0
    completion = max(0.0, min(100.0, float(completion_pct))) / 100.0
    replacement = max(0.0, min(1.0, float(replacement_confidence)))
    cost_efficiency = 1.0 if estimated_completion_cost is None else 1.0 / (1.0 + (float(estimated_completion_cost) / 150.0))
    candidate_norm = max(0.0, min(100.0, float(candidate_score_value))) / 100.0
    competitive_norm = max(0.0, min(40.0, float(competitive_score))) / 40.0
    mode = resolved_ranking_mode(ranking_mode)
    if mode == "competitive":
        score = competitive_norm
    elif mode == "hybrid":
        score = (
            0.40 * candidate_norm
            + 0.20 * competitive_norm
            + 0.15 * buildability
            + 0.15 * completion
            + 0.10 * replacement
        )
    else:
        score = (
            0.35 * buildability
            + 0.25 * completion
            + 0.20 * candidate_norm
            + 0.10 * replacement
            + 0.10 * cost_efficiency
        )
    return round(score * 100.0, 4)


def win_condition_match(deck_vector: np.ndarray, reference_vector: np.ndarray) -> float:
    return max(0.0, min(1.0, cosine_similarity(deck_vector.astype(np.float32), reference_vector.astype(np.float32))))


def synergy_cluster_coverage(*, selected_cluster_ids: list[int], deck_cluster_ids: list[int]) -> float:
    if not selected_cluster_ids:
        return 0.0
    selected = set(int(value) for value in selected_cluster_ids)
    deck = set(int(value) for value in deck_cluster_ids)
    return float(len(selected & deck)) / float(max(1, len(selected)))


def legality_margin_from_issues(issue_count: int) -> float:
    if issue_count <= 0:
        return 1.0
    return max(0.0, 1.0 - (float(issue_count) / 8.0))


def curve_balance_from_curve(curve: np.ndarray, reference: np.ndarray | None = None) -> float:
    if curve.size <= 0:
        return 0.0
    target = reference if reference is not None and reference.shape == curve.shape else np.array([0.08, 0.16, 0.18, 0.18, 0.16, 0.12, 0.08, 0.04], dtype=np.float32)
    diff = float(np.abs(curve - target).mean())
    return max(0.0, min(1.0, 1.0 - diff * 2.0))


def analysis_snapshot(
    *,
    deck: DeckPayload,
    collection: dict[str, int],
    cards,
    unit_price_for_title,
    buy_url_for_title,
):
    return analyze_collection_completion(
        deck,
        collection=collection,
        cards=cards,
        unit_price_for_title=unit_price_for_title,
        buy_url_for_title=buy_url_for_title,
    )


def explanation_rows(*, win_condition_label: str, synergy_labels: list[str], build_mode: str, seed_count: int) -> list[dict[str, str]]:
    rows = [
        {"kind": "win_condition", "label": "Win Condition", "value": str(win_condition_label or "Unknown")},
        {"kind": "build_mode", "label": "Build Mode", "value": str(build_mode or "hybrid")},
    ]
    if synergy_labels:
        rows.append({"kind": "synergy", "label": "Synergy Packages", "value": ", ".join(synergy_labels[:4])})
    if seed_count > 0:
        rows.append({"kind": "seed_decks", "label": "Seed Decks", "value": f"{seed_count} retrieved shells informed this build."})
    return rows
