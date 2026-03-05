from __future__ import annotations

from collections import Counter
import math
from typing import Any

import numpy as np
import torch
from sklearn.utils.validation import check_is_fitted

from app.domain.auto_builder_features import (
    CardStaticFeatures,
    build_card_static_features,
    cosine_similarity,
    deck_cost_curve,
    deck_main_from_payload,
    deck_signature_from_main,
    deck_vector,
    largest_remainder_round,
)
from app.domain.auto_builder_scoring import (
    candidate_score,
    curve_balance_from_curve,
    explanation_rows,
    legality_margin_from_issues,
    ranking_score,
    resolved_ranking_mode,
    synergy_cluster_coverage,
)
from app.domain.auto_builder_training import _MoECandidateScorer, _replacement_feature_row, _resolve_torch_device, _state_feature_vector
from app.domain.auto_builder_types import CandidateDeck, GenerationPlan, PlanSeed
from app.domain.eligibility import build_eligibility_snapshot
from app.domain.models import DeckPayload
from app.domain.normalization import normalize_card_key
from app.domain.validator import validate_deck

_MAIN_CARD_TYPES = {"Unit", "Gear", "Spell"}
_CANDIDATE_SHELL_LIMIT = 12
_CANDIDATE_ARCHETYPES_PER_SHELL = 2
_PURE_GENERATE_LIMIT = 6
_SEED_ADAPT_LIMIT = 16
_MIN_RESULTS_TARGET = 12
_MAX_VARIANTS_PER_SHELL = 2
_PURE_BEAM_WIDTH = 12
_PURE_EXPANSION_LIMIT = 6
_PURE_POOL_LIMIT = 48
_SUPPORT_ONLY_ISSUE_CODES = {
    "RUNE_DECK_SIZE",
    "RUNE_UNKNOWN_CARD",
    "RUNE_CARD_TYPE",
    "RUNE_DOMAIN",
    "BATTLEFIELD_UNKNOWN",
    "BATTLEFIELD_TYPE",
    "BATTLEFIELD_DOMAIN",
    "BATTLEFIELD_COUNT",
    "BATTLEFIELD_UNIQUE",
}


def generation_defaults() -> dict[str, int]:
    return {
        "candidateShellLimit": _CANDIDATE_SHELL_LIMIT,
        "candidateArchetypesPerShell": _CANDIDATE_ARCHETYPES_PER_SHELL,
        "pureGenerateLimit": _PURE_GENERATE_LIMIT,
        "seedAdaptLimit": _SEED_ADAPT_LIMIT,
        "minResultsTarget": _MIN_RESULTS_TARGET,
        "maxVariantsPerShell": _MAX_VARIANTS_PER_SHELL,
    }


def _main_deck_target_size(rules) -> int:
    try:
        return max(1, int(rules.int_constraint("main_deck_size_exact", 40)))
    except Exception:
        return 40


def _safe_model_predict(model, row: np.ndarray, *, default: float = 0.0) -> float:
    if model is None or not hasattr(model, "predict"):
        return float(default)
    try:
        check_is_fitted(model)
        return float(model.predict(np.array([row], dtype=np.float32))[0])
    except Exception:
        return float(default)


def _sigmoid(value: float) -> float:
    x = float(value)
    if not math.isfinite(x):
        return 0.0
    if x >= 0.0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _win_condition_vector_size(bundle: dict[str, Any]) -> int:
    raw = bundle.get("deckWinConditionVectors")
    deck_vectors = np.array(raw, dtype=np.float32) if raw is not None else np.zeros((0, 0), dtype=np.float32)
    if deck_vectors.ndim == 2 and deck_vectors.shape[1] > 0:
        return int(deck_vectors.shape[1])
    return max(1, len(bundle.get("winConditions") or []))


def _one_hot_win_condition(win_condition_id: int, *, bundle: dict[str, Any], size: int | None = None) -> np.ndarray:
    size = max(1, int(size or _win_condition_vector_size(bundle)))
    out = np.zeros((size,), dtype=np.float32)
    if 0 <= int(win_condition_id) < size:
        out[int(win_condition_id)] = 1.0
    return out


def _bundle_cluster_count(bundle: dict[str, Any]) -> int:
    cluster_by_card = dict(bundle.get("clusterByCard") or {})
    return max(1, max((int(value) for value in cluster_by_card.values()), default=-1) + 1)


def _generator_feature_sizes(generator_state: dict[str, Any]) -> tuple[int, int]:
    return (
        max(1, int(generator_state.get("winVectorSize") or 32)),
        max(1, int(generator_state.get("clusterVectorSize") or 64)),
    )


def _deck_vector_win_size(bundle: dict[str, Any]) -> int:
    cached = bundle.get("_runtimeCache")
    if isinstance(cached, dict) and int(cached.get("deckVectorWinSize") or 0) > 0:
        return int(cached["deckVectorWinSize"])
    raw = bundle.get("deckVectors")
    deck_vectors = np.array(raw, dtype=np.float32) if raw is not None else np.zeros((0, 0), dtype=np.float32)
    if deck_vectors.ndim == 2 and deck_vectors.shape[1] > 0:
        return max(1, int(deck_vectors.shape[1]) - (64 + 8 + 6 + 3 + 3))
    return _win_condition_vector_size(bundle)


def _static_features_from_bundle(bundle: dict[str, Any], cards) -> dict[str, CardStaticFeatures]:
    raw = dict(bundle.get("staticFeatures") or {})
    if not raw:
        return build_card_static_features(cards, vocab_keys=(bundle.get("indexToKey") or []))
    out: dict[str, CardStaticFeatures] = {}
    for key, row in raw.items():
        if not str(key):
            continue
        out[str(key)] = CardStaticFeatures(
            title=str(row.get("title") or ""),
            key=str(key),
            card_type=str(row.get("cardType", row.get("card_type", "")) or ""),
            super_type=str(row.get("superType", row.get("super_type", "")) or ""),
            domains=tuple(str(value) for value in list(row.get("domains") or []) if str(value)),
            cost=int(row.get("cost") or 0),
            might=int(row.get("might") or 0),
            is_unique=bool(row.get("isUnique", row.get("is_unique", False))),
            tags=tuple(str(value) for value in list(row.get("tags") or []) if str(value)),
            effect_tokens=tuple(str(value) for value in list(row.get("effectTokens", row.get("effect_tokens", [])) or []) if str(value)),
        )
    return out


def _bundle_runtime(bundle: dict[str, Any], cards) -> dict[str, Any]:
    cached = bundle.get("_runtimeCache")
    if isinstance(cached, dict) and cached.get("embeddings") is not None:
        return cached
    embeddings = {str(key): np.array(value, dtype=np.float32) for key, value in dict(bundle.get("cardEmbeddings") or {}).items()}
    cache = {
        "embeddings": embeddings,
        "textEmbeddings": {str(key): np.array(value, dtype=np.float32) for key, value in dict(bundle.get("cardTextEmbeddings") or {}).items()},
        "staticFeatures": _static_features_from_bundle(bundle, cards),
        "clusterByCard": {str(key): int(value) for key, value in dict(bundle.get("clusterByCard") or {}).items()},
        "shellProfiles": _shell_profiles(bundle),
        "archetypeProfiles": _archetype_profiles(bundle),
        "embeddingNeighbors": {str(key): [str(item) for item in list(value or []) if str(item)] for key, value in dict(bundle.get("embeddingNeighbors") or {}).items()},
        "vocab": {str(key): int(value) for key, value in dict(bundle.get("vocab") or {}).items()},
        "idf": np.array(bundle.get("idf"), dtype=np.float32) if bundle.get("idf") is not None else np.zeros((0,), dtype=np.float32),
        "winConditionMatrix": np.array(bundle.get("winConditionMatrix"), dtype=np.float32) if bundle.get("winConditionMatrix") is not None else np.zeros((0, 0), dtype=np.float32),
        "deckVectorWinSize": _deck_vector_win_size(bundle),
    }
    bundle["_runtimeCache"] = cache
    return cache


def _plan_win_condition_vector(plan: GenerationPlan, *, bundle: dict[str, Any], win_vector_size: int) -> np.ndarray:
    raw = np.array(list(plan.win_condition_vector or ()), dtype=np.float32)
    if raw.size <= 0:
        return _one_hot_win_condition(plan.win_condition_id, bundle=bundle, size=win_vector_size)
    out = np.zeros((max(1, int(win_vector_size)),), dtype=np.float32)
    limit = min(out.shape[0], raw.shape[0])
    out[:limit] = raw[:limit]
    total = float(out.sum())
    if total > 0:
        out /= total
    return out


def _project_win_condition_vector(main_by_key: dict[str, int], *, bundle: dict[str, Any], win_vector_size: int | None = None) -> np.ndarray:
    resolved_size = max(1, int(win_vector_size or _win_condition_vector_size(bundle)))
    cached = bundle.get("_runtimeCache") if isinstance(bundle.get("_runtimeCache"), dict) else None
    matrix = np.array(cached.get("winConditionMatrix"), dtype=np.float32, copy=False) if cached is not None else (np.array(bundle.get("winConditionMatrix"), dtype=np.float32) if bundle.get("winConditionMatrix") is not None else np.zeros((0, 0), dtype=np.float32))
    vocab = dict(cached.get("vocab") or {}) if cached is not None else {str(key): int(value) for key, value in dict(bundle.get("vocab") or {}).items()}
    if matrix.ndim != 2 or matrix.shape[0] <= 0 or matrix.shape[1] <= 0 or not vocab:
        return np.zeros((resolved_size,), dtype=np.float32)
    row = np.zeros((matrix.shape[1],), dtype=np.float32)
    for key, qty in main_by_key.items():
        col_idx = vocab.get(key)
        if col_idx is None or col_idx < 0 or col_idx >= row.shape[0]:
            continue
        row[col_idx] = float(max(0, int(qty)))
    idf = np.array(cached.get("idf"), dtype=np.float32, copy=False) if cached is not None else (np.array(bundle.get("idf"), dtype=np.float32) if bundle.get("idf") is not None else np.zeros((0,), dtype=np.float32))
    if idf.shape[0] == row.shape[0]:
        row *= idf
    activations = matrix @ row
    total = float(activations.sum())
    if total > 0:
        activations /= total
    out = np.zeros((resolved_size,), dtype=np.float32)
    out[: min(resolved_size, activations.shape[0])] = activations[: min(resolved_size, activations.shape[0])]
    return out


def _shell_profiles(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key, value in dict(bundle.get("shellProfiles") or {}).items():
        row = dict(value)
        shell_id = str(key or row.get("shell_id") or row.get("shellId") or "")
        out[shell_id] = {
            "shellId": shell_id,
            "shellLabel": row.get("shellLabel", row.get("shell_label", "")),
            "legendTitle": row.get("legendTitle", row.get("legend_title", "")),
            "chosenChampionTitle": row.get("chosenChampionTitle", row.get("chosen_champion_title", "")),
            "trainingDeckCount": row.get("trainingDeckCount", row.get("training_deck_count", 0)),
            "sourceBreakdown": row.get("sourceBreakdown", row.get("source_breakdown", {})),
            "competitivePrior": row.get("competitivePrior", row.get("competitive_prior", 0.0)),
            "buildabilityPrior": row.get("buildabilityPrior", row.get("buildability_prior", 0.0)),
            "buildableConversion": row.get("buildableConversion", row.get("buildable_conversion", 0.0)),
        }
    return out


def _archetype_profiles(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in list(bundle.get("archetypes") or []):
        row = dict(item)
        archetype_id = str(row.get("archetypeId") or row.get("archetype_id") or "")
        if not archetype_id:
            continue
        out[archetype_id] = {
            "archetypeId": archetype_id,
            "shellId": row.get("shellId", row.get("shell_id", "")),
            "archetypeName": row.get("archetypeName", row.get("archetype_name", "")),
            "prototypeMain": row.get("prototypeMain", row.get("prototype_main", {})),
            "winConditionVector": row.get("winConditionVector", row.get("win_condition_vector", [])),
            "nearestSeedDecks": row.get("nearestSeedDecks", row.get("nearest_seed_decks", [])),
            "competitivePrior": row.get("competitivePrior", row.get("competitive_prior", 0.0)),
            "buildabilityPrior": row.get("buildabilityPrior", row.get("buildability_prior", 0.0)),
            "buildableConversion": row.get("buildableConversion", row.get("buildable_conversion", 0.0)),
            "confidence": row.get("confidence", 0.0),
            "sourceBreakdown": row.get("sourceBreakdown", row.get("source_breakdown", {})),
            "winConditionId": row.get("winConditionId", row.get("win_condition_id", 0)),
            "synergyClusterIds": row.get("synergyClusterIds", row.get("synergy_cluster_ids", [])),
            "synergyClusterLabels": row.get("synergyClusterLabels", row.get("synergy_cluster_labels", [])),
        }
    return out


def _plan_seed_rows(bundle: dict[str, Any], plan: GenerationPlan) -> list[dict[str, Any]]:
    preferred = {(seed.source.lower(), seed.deck_id.lower()) for seed in plan.seed_decks}
    rows = []
    for row in list(bundle.get("deckProfiles") or []):
        shell_match = str(row.get("shellId") or "") == plan.shell_id
        archetype_match = str(row.get("archetypeId") or "") == plan.archetype_id
        if not shell_match and not archetype_match:
            continue
        rows.append(dict(row))
    rows.sort(
        key=lambda row: (
            0 if (str(row.get("source") or "").lower(), str(row.get("deckId") or "").lower()) in preferred else 1,
            0 if str(row.get("archetypeId") or "") == plan.archetype_id else 1,
            -float(row.get("competitiveScore") or 0.0),
            str(row.get("deckName") or "").lower(),
        )
    )
    return rows


def _collection_fit(main_by_key: dict[str, int], collection_by_key: dict[str, int]) -> float:
    total = sum(max(0, int(qty)) for qty in main_by_key.values())
    if total <= 0:
        return 0.0
    owned = 0
    for key, qty in main_by_key.items():
        owned += min(max(0, int(qty)), max(0, int(collection_by_key.get(key, 0))))
    return float(owned) / float(total)


def _owned_qty(collection_by_key: dict[str, int], key: str) -> int:
    return max(0, int(collection_by_key.get(str(key or ""), 0)))


def _title_owned_qty(collection_by_key: dict[str, int], title: str) -> int:
    key = normalize_card_key(title)
    if not key:
        return 0
    return _owned_qty(collection_by_key, key)


def _collection_supports_plan(plan: GenerationPlan, collection_by_key: dict[str, int]) -> bool:
    legend_key = normalize_card_key(plan.legend_title)
    champion_key = normalize_card_key(plan.chosen_champion_title)
    if legend_key and _owned_qty(collection_by_key, legend_key) <= 0:
        return False
    if champion_key and _owned_qty(collection_by_key, champion_key) <= 0:
        return False
    return True


def build_generation_plans(*, bundle: dict[str, Any], collection_by_key: dict[str, int], ranking_mode: str, legend_title: str = "", chosen_champion_title: str = "", strict_buildable: bool = False) -> list[GenerationPlan]:
    shell_profiles = _shell_profiles(bundle)
    archetype_profiles = _archetype_profiles(bundle)
    archetypes_by_shell = {str(key): list(value) for key, value in dict(bundle.get("archetypesByShell") or {}).items()}
    seed_examples_by_shell = {str(key): list(value) for key, value in dict(bundle.get("seedExamplesByShell") or {}).items()}
    plans: list[GenerationPlan] = []
    mode = resolved_ranking_mode(ranking_mode, only_buildable=bool(strict_buildable))

    shell_candidates: list[tuple[float, str]] = []
    for shell_id, shell in shell_profiles.items():
        shell_legend = str(shell.get("legendTitle") or "")
        shell_champion = str(shell.get("chosenChampionTitle") or "")
        if legend_title and normalize_card_key(shell_legend) != normalize_card_key(legend_title):
            continue
        if chosen_champion_title and normalize_card_key(shell_champion) != normalize_card_key(chosen_champion_title):
            continue
        collection_score = 0.0
        shell_archetype_ids = list(archetypes_by_shell.get(shell_id) or [])
        if not shell_archetype_ids:
            shell_archetype_ids = [arch_id for arch_id, archetype in archetype_profiles.items() if str(archetype.get("shellId") or "") == shell_id]
        if collection_by_key:
            matching_archetypes = [archetype_profiles[arch_id] for arch_id in shell_archetype_ids if arch_id in archetype_profiles]
            if matching_archetypes:
                collection_score = max(_collection_fit(dict(item.get("prototypeMain") or {}), collection_by_key) for item in matching_archetypes)
        source_diversity = len(dict(shell.get("sourceBreakdown") or {}))
        archetype_confidence = max((float(archetype_profiles[arch_id].get("confidence") or 0.0) for arch_id in shell_archetype_ids if arch_id in archetype_profiles), default=0.0)
        shell_buildability = max(0.0, min(1.0, float(shell.get("buildabilityPrior") or 0.0)))
        shell_conversion = max(0.0, min(1.0, float(shell.get("buildableConversion") or 0.0)))
        if mode == "competitive":
            score = (
                0.78 * float(shell.get("competitivePrior") or 0.0) / 40.0
                + 0.10 * shell_buildability
                + 0.05 * shell_conversion
                + 0.04 * min(1.0, source_diversity / 4.0)
                + 0.03 * archetype_confidence
            )
        elif mode == "hybrid":
            score = (
                0.42 * float(shell.get("competitivePrior") or 0.0) / 40.0
                + 0.20 * collection_score
                + 0.13 * shell_buildability
                + 0.05 * shell_conversion
                + 0.12 * min(1.0, source_diversity / 4.0)
                + 0.08 * archetype_confidence
            )
        else:
            score = (
                0.30 * float(shell.get("competitivePrior") or 0.0) / 40.0
                + 0.28 * collection_score
                + 0.18 * shell_buildability
                + 0.08 * shell_conversion
                + 0.12 * min(1.0, source_diversity / 4.0)
                + 0.04 * archetype_confidence
            )
        shell_candidates.append((score, shell_id))
    shell_candidates.sort(key=lambda item: (-item[0], str(shell_profiles[item[1]].get("shellLabel") or "").lower()))

    for shell_score, shell_id in shell_candidates[:_CANDIDATE_SHELL_LIMIT]:
        shell = shell_profiles[shell_id]
        ranked_archetypes: list[tuple[float, dict[str, Any]]] = []
        shell_archetype_ids = list(archetypes_by_shell.get(shell_id) or [])
        if not shell_archetype_ids:
            shell_archetype_ids = [arch_id for arch_id, archetype in archetype_profiles.items() if str(archetype.get("shellId") or "") == shell_id]
        for archetype_id in shell_archetype_ids:
            archetype = archetype_profiles.get(archetype_id)
            if archetype is None:
                continue
            prototype_main = dict(archetype.get("prototypeMain") or {})
            collection_fit = _collection_fit(prototype_main, collection_by_key) if collection_by_key else 0.0
            buildability_prior = max(0.0, min(1.0, float(archetype.get("buildabilityPrior") or 0.0)))
            buildable_conversion = max(0.0, min(1.0, float(archetype.get("buildableConversion") or 0.0)))
            confidence = float(archetype.get("confidence") or 0.0)
            source_diversity = min(1.0, len(dict(archetype.get("sourceBreakdown") or {})) / 3.0)
            if mode == "competitive":
                score = (
                    0.82 * float(archetype.get("competitivePrior") or 0.0) / 40.0
                    + 0.08 * buildability_prior
                    + 0.04 * buildable_conversion
                    + 0.04 * confidence
                    + 0.02 * source_diversity
                )
            elif mode == "hybrid":
                score = (
                    0.48 * float(archetype.get("competitivePrior") or 0.0) / 40.0
                    + 0.16 * collection_fit
                    + 0.14 * buildability_prior
                    + 0.06 * buildable_conversion
                    + 0.12 * source_diversity
                    + 0.04 * confidence
                )
            else:
                score = (
                    0.34 * float(archetype.get("competitivePrior") or 0.0) / 40.0
                    + 0.26 * collection_fit
                    + 0.18 * buildability_prior
                    + 0.10 * buildable_conversion
                    + 0.10 * source_diversity
                    + 0.02 * confidence
                )
            ranked_archetypes.append((score, archetype))
        ranked_archetypes.sort(key=lambda item: (-item[0], str(item[1].get("archetypeName") or "").lower()))
        for archetype_score, archetype in ranked_archetypes[:_CANDIDATE_ARCHETYPES_PER_SHELL]:
            wc_id = int(archetype.get("winConditionId") or 0)
            wc_rows = list(bundle.get("winConditions") or [])
            wc_label = f"WC{wc_id + 1:02d}"
            if 0 <= wc_id < len(wc_rows):
                wc_label = str(wc_rows[wc_id].get("label") or wc_label)
            seeds = []
            for row in list(archetype.get("nearestSeedDecks") or [])[:3]:
                seeds.append(PlanSeed(source=str(row.get("source") or "meta"), deck_id=str(row.get("deck_id", row.get("deckId", "")) or ""), deck_name=str(row.get("deck_name", row.get("deckName", "")) or ""), score=float(row.get("score") or row.get("metaScore") or 0.0)))
            if not seeds:
                for row in seed_examples_by_shell.get(shell_id, [])[:3]:
                    seeds.append(PlanSeed(source=str(row.get("source") or "meta"), deck_id=str(row.get("deckId") or ""), deck_name=str(row.get("deckName") or ""), score=float(row.get("metaScore") or 0.0)))
            plans.append(
                GenerationPlan(
                    shell_id=shell_id,
                    shell_label=str(shell.get("shellLabel") or ""),
                    archetype_id=str(archetype.get("archetypeId") or ""),
                    archetype_name=str(archetype.get("archetypeName") or ""),
                    archetype_confidence=float(archetype.get("confidence") or 0.0),
                    win_condition_id=wc_id,
                    win_condition_label=wc_label,
                    win_condition_vector=tuple(float(value) for value in list(archetype.get("winConditionVector") or [])),
                    legend_title=str(shell.get("legendTitle") or ""),
                    chosen_champion_title=str(shell.get("chosenChampionTitle") or ""),
                    synergy_cluster_ids=tuple(int(value) for value in list(archetype.get("synergyClusterIds") or [])[:4]),
                    synergy_cluster_labels=tuple(str(value) for value in list(archetype.get("synergyClusterLabels") or [])[:4]),
                    source_breakdown={key: int(value) for key, value in dict(archetype.get("sourceBreakdown") or {}).items() if key},
                    seed_decks=tuple(seeds),
                    shell_buildability_prior=shell_buildability,
                    shell_buildable_conversion=shell_conversion,
                    archetype_buildability_prior=buildability_prior,
                    archetype_buildable_conversion=buildable_conversion,
                    prior_score=round(float(shell_score + archetype_score), 4),
                )
            )
    plans.sort(key=lambda row: (-row.prior_score, row.shell_label.lower(), row.archetype_name.lower()))
    return plans


def _can_add_card(*, main_by_key: dict[str, int], candidate_key: str, cards, legend_title: str, collection_by_key: dict[str, int] | None = None, strict_buildable: bool = False) -> bool:
    card = cards.by_key.get(candidate_key)
    if card is None or card.card_type not in _MAIN_CARD_TYPES:
        return False
    legend = cards.get(legend_title) if legend_title else None
    legend_domains = set(legend.domains) if legend is not None else set()
    if legend_domains and (not card.domains or not set(card.domains).issubset(legend_domains)):
        return False
    next_qty = int(main_by_key.get(candidate_key, 0)) + 1
    if next_qty > (1 if bool(card.is_unique) else 3):
        return False
    if strict_buildable and collection_by_key is not None and next_qty > _owned_qty(collection_by_key, candidate_key):
        return False
    return True


def _candidate_card_pool(*, plan: GenerationPlan, partial_main: dict[str, int], bundle: dict[str, Any], cards, collection_by_key: dict[str, int], embedding_vectors: dict[str, np.ndarray] | None = None, cluster_by_card: dict[str, int] | None = None, strict_buildable: bool = False) -> list[str]:
    runtime_cache = _bundle_runtime(bundle, cards)
    cluster_by_card = cluster_by_card if cluster_by_card is not None else runtime_cache["clusterByCard"]
    archetype = runtime_cache["archetypeProfiles"].get(plan.archetype_id, {})
    pool: set[str] = set(str(key) for key in dict(archetype.get("prototypeMain") or {}).keys())
    freq = dict((bundle.get("winConditionCardFrequency") or {}).get(plan.win_condition_id) or {})
    pool.update(key for key, _score in sorted(freq.items(), key=lambda item: (-float(item[1]), item[0]))[:24])
    for key, cluster_id in cluster_by_card.items():
        if int(cluster_id) in set(plan.synergy_cluster_ids):
            pool.add(key)
    for seed_row in _plan_seed_rows(bundle, plan)[:6]:
        pool.update(str(key) for key in dict(seed_row.get("mainByKey") or {}).keys())
    if collection_by_key:
        pool.update(key for key, qty in collection_by_key.items() if int(qty) > 0)
    if partial_main:
        embedding_vectors = embedding_vectors if embedding_vectors is not None else runtime_cache["embeddings"]
        embedding_neighbors = runtime_cache["embeddingNeighbors"]
        for key in list(partial_main.keys())[:4]:
            if embedding_neighbors.get(key):
                pool.update(candidate for candidate in embedding_neighbors.get(key, [])[:6])
                continue
            source_vec = embedding_vectors.get(key)
            if source_vec is None:
                continue
            scored = []
            for candidate_key, candidate_vec in embedding_vectors.items():
                if candidate_key == key:
                    continue
                denom = float(np.linalg.norm(source_vec) * np.linalg.norm(candidate_vec))
                score = 0.0 if denom <= 0 else float(np.dot(source_vec, candidate_vec) / denom)
                scored.append((score, candidate_key))
            scored.sort(key=lambda row: (-row[0], row[1]))
            pool.update(candidate for _score, candidate in scored[:6])
    if strict_buildable:
        pool = {
            key
            for key in pool
            if _owned_qty(collection_by_key, key) > int(partial_main.get(key, 0))
        }
    return sorted(pool)


def _candidate_prior_score(candidate_key: str, *, plan: GenerationPlan, bundle: dict[str, Any], collection_by_key: dict[str, int], runtime_cache: dict[str, Any]) -> float:
    archetype = runtime_cache["archetypeProfiles"].get(plan.archetype_id, {})
    prototype_main = dict(archetype.get("prototypeMain") or {})
    freq = float(dict((bundle.get("winConditionCardFrequency") or {}).get(plan.win_condition_id) or {}).get(candidate_key, 0.0))
    archetype_bonus = min(1.0, float(prototype_main.get(candidate_key, 0)) / 3.0)
    cluster_by_card = runtime_cache["clusterByCard"]
    cluster_bonus = 0.15 if int(cluster_by_card.get(candidate_key, -1)) in set(plan.synergy_cluster_ids) else 0.0
    owned_bonus = 0.10 if int(collection_by_key.get(candidate_key, 0)) > 0 else 0.0
    return freq + 0.35 * archetype_bonus + cluster_bonus + owned_bonus


def _score_candidate_key(*, model, generator_state: dict[str, Any], plan: GenerationPlan, partial_main: dict[str, int], candidate_key: str, bundle: dict[str, Any], cards, embeddings: dict[str, np.ndarray], static_features, cluster_by_card: dict[str, int], collection_by_key: dict[str, int]) -> float:
    scores = _score_candidate_keys(
        model=model,
        generator_state=generator_state,
        plan=plan,
        partial_main=partial_main,
        candidate_keys=[candidate_key],
        bundle=bundle,
        cards=cards,
        embeddings=embeddings,
        static_features=static_features,
        cluster_by_card=cluster_by_card,
        collection_by_key=collection_by_key,
    )
    return scores[0][0] if scores else -1e9


def _score_candidate_keys(*, model, generator_state: dict[str, Any], plan: GenerationPlan, partial_main: dict[str, int], candidate_keys: list[str], bundle: dict[str, Any], cards, embeddings: dict[str, np.ndarray], static_features, cluster_by_card: dict[str, int], collection_by_key: dict[str, int], runtime_cache: dict[str, Any] | None = None) -> list[tuple[float, str]]:
    if not candidate_keys:
        return []
    total_main_slots = max(1, int(generator_state.get("mainDeckSize") or 40))
    win_vector_size, cluster_vector_size = _generator_feature_sizes(generator_state)
    text_emb_dim = max(0, int(generator_state.get("textEmbDim") or 0))
    if runtime_cache is None:
        runtime_cache = _bundle_runtime(bundle, cards)
    text_embeddings = runtime_cache.get("textEmbeddings") if text_emb_dim > 0 else None
    state_vec = _state_feature_vector(
        partial_main,
        card_embeddings=embeddings,
        static_features=static_features,
        win_condition_vector=_plan_win_condition_vector(plan, bundle=bundle, win_vector_size=win_vector_size),
        cluster_by_card=cluster_by_card,
        cluster_count=_bundle_cluster_count(bundle),
        remaining_slots=total_main_slots - sum(int(v) for v in partial_main.values()),
        total_main_slots=total_main_slots,
        win_vector_size=win_vector_size,
        cluster_vector_size=cluster_vector_size,
        card_text_embeddings=text_embeddings,
        text_emb_dim=text_emb_dim,
    )
    legend_idx = int((generator_state.get("legendToIdx") or {}).get(plan.legend_title, 0))
    champion_idx = int((generator_state.get("championToIdx") or {}).get(plan.chosen_champion_title, 0))
    runtime = _generator_runtime(generator_state, model=model)
    device = runtime["device"]
    valid_keys: list[str] = []
    candidate_rows: list[np.ndarray] = []
    priors: list[float] = []
    for key in candidate_keys:
        candidate_vec = embeddings.get(key)
        if candidate_vec is None:
            continue
        valid_keys.append(key)
        candidate_rows.append(np.asarray(candidate_vec, dtype=np.float32))
        priors.append(_candidate_prior_score(key, plan=plan, bundle=bundle, collection_by_key=collection_by_key, runtime_cache=runtime_cache))
    if not valid_keys:
        return []
    state_batch = np.repeat(state_vec.reshape((1, -1)), len(valid_keys), axis=0).astype(np.float32, copy=False)
    candidate_batch = np.vstack(candidate_rows).astype(np.float32, copy=False)
    with torch.inference_mode():
        logits = runtime["model"](
            torch.from_numpy(state_batch).to(device=device, dtype=torch.float32),
            torch.from_numpy(candidate_batch).to(device=device, dtype=torch.float32),
            torch.full((len(valid_keys),), legend_idx, dtype=torch.long, device=device),
            torch.full((len(valid_keys),), champion_idx, dtype=torch.long, device=device),
        ).detach().cpu().numpy()
    return [(0.70 * _sigmoid(float(logit)) + 0.30 * min(1.0, priors[idx] / 1.60), key) for idx, (logit, key) in enumerate(zip(logits.tolist(), valid_keys))]


def _eligible_weight_map(weights: dict[str, float], *, allowed_titles: set[str]) -> dict[str, float]:
    return {str(key): float(value) for key, value in weights.items() if str(key) in allowed_titles and float(value) > 0}


def _round_with_caps(weights: dict[str, float], *, total: int, collection_by_key: dict[str, int]) -> dict[str, int]:
    total = max(0, int(total))
    if total <= 0:
        return {}
    titles = [title for title in weights.keys() if _title_owned_qty(collection_by_key, title) > 0]
    if not titles:
        return {}
    capacities = {title: _title_owned_qty(collection_by_key, title) for title in titles}
    if sum(capacities.values()) < total:
        return {}
    weight_sum = float(sum(max(0.0, float(weights.get(title, 0.0))) for title in titles))
    allocations = {title: 0 for title in titles}
    quotas = {}
    if weight_sum > 0:
        for title in titles:
            quotas[title] = float(total) * max(0.0, float(weights.get(title, 0.0))) / weight_sum
            allocations[title] = min(capacities[title], int(math.floor(quotas[title])))
    assigned = sum(allocations.values())
    while assigned < total:
        ranked = sorted(
            (
                quotas.get(title, 0.0) - float(allocations[title]),
                max(0.0, float(weights.get(title, 0.0))),
                title,
            )
            for title in titles
            if allocations[title] < capacities[title]
        )
        if not ranked:
            break
        _fraction, _weight, title = ranked[-1]
        allocations[title] += 1
        assigned += 1
    return {title: qty for title, qty in allocations.items() if int(qty) > 0}


def _seed_support_weights(seed_row: dict[str, Any] | None) -> tuple[dict[str, float], dict[str, float]]:
    if not seed_row:
        return {}, {}
    return (
        {str(key): float(value) for key, value in dict(seed_row.get("runes") or {}).items() if int(value) > 0},
        {str(key): float(idx) for idx, key in enumerate(reversed(list(seed_row.get("battlefields") or [])), start=1) if str(key).strip()},
    )


def _ordered_battlefields(weights: dict[str, float], *, allowed_titles: set[str], count: int) -> list[str]:
    battlefields = [title for title, _weight in sorted(weights.items(), key=lambda item: (-float(item[1]), item[0])) if title in allowed_titles]
    unique: list[str] = []
    for title in battlefields:
        if title in unique:
            continue
        unique.append(title)
        if len(unique) >= count:
            break
    return unique


def _owned_support_weights(snapshot, collection_by_key: dict[str, int]) -> tuple[dict[str, float], dict[str, float]]:
    rune_weights = {}
    for card in snapshot.runes:
        owned = _title_owned_qty(collection_by_key, card.title)
        if owned > 0:
            rune_weights[card.title] = float(owned)
    battlefield_weights = {}
    for idx, card in enumerate(snapshot.battlefields):
        owned = _title_owned_qty(collection_by_key, card.title)
        if owned > 0:
            battlefield_weights[card.title] = float(len(snapshot.battlefields) - idx)
    return rune_weights, battlefield_weights


def _finish_support_cards(*, plan: GenerationPlan, main_by_key: dict[str, int], bundle: dict[str, Any], cards, rules, seed_row: dict[str, Any] | None = None, prefer_seed_first: bool = False, collection_by_key: dict[str, int] | None = None, strict_buildable: bool = False) -> tuple[dict[str, int], list[str], str]:
    snapshot = build_eligibility_snapshot(cards=cards, rules=rules, legend_title=plan.legend_title)
    allowed_runes = {card.title for card in snapshot.runes}
    allowed_battlefields = {card.title for card in snapshot.battlefields}
    archetype_weights = dict((bundle.get("runeWeightsByArchetype") or {}).get(plan.archetype_id) or {})
    shell_weights = dict((bundle.get("runeWeightsByShell") or {}).get(plan.shell_id) or {})
    wc_weights = dict((bundle.get("runeWeightsByWinCondition") or {}).get(plan.win_condition_id) or {})
    archetype_battlefields = dict((bundle.get("battlefieldWeightsByArchetype") or {}).get(plan.archetype_id) or {})
    shell_battlefields = dict((bundle.get("battlefieldWeightsByShell") or {}).get(plan.shell_id) or {})
    wc_battlefields = dict((bundle.get("battlefieldWeightsByWinCondition") or {}).get(plan.win_condition_id) or {})
    seed_runes, seed_battlefields = _seed_support_weights(seed_row)

    support_sources = [
        ("archetype", archetype_weights, archetype_battlefields),
        ("shell", shell_weights, shell_battlefields),
        ("seed", seed_runes, seed_battlefields),
        ("win-condition", wc_weights, wc_battlefields),
    ]
    if prefer_seed_first:
        support_sources = [support_sources[2], support_sources[0], support_sources[1], support_sources[3]]
    if strict_buildable:
        owned_runes, owned_battlefields = _owned_support_weights(snapshot, collection_by_key or {})
        support_sources.append(("owned", owned_runes, owned_battlefields))

    for label, rune_weights, battlefield_weights in support_sources:
        eligible_runes = _eligible_weight_map(rune_weights, allowed_titles=allowed_runes)
        if strict_buildable:
            runes = _round_with_caps(
                eligible_runes,
                total=max(1, snapshot.rune_deck_size),
                collection_by_key=collection_by_key or {},
            )
        else:
            runes = largest_remainder_round(eligible_runes, total=max(1, snapshot.rune_deck_size))
        battlefields = _ordered_battlefields(battlefield_weights, allowed_titles=allowed_battlefields, count=snapshot.battlefield_count)
        if strict_buildable:
            battlefields = [title for title in battlefields if _title_owned_qty(collection_by_key or {}, title) > 0]
        if runes and len(battlefields) >= snapshot.battlefield_count:
            return runes, battlefields[: snapshot.battlefield_count], label

    if strict_buildable:
        owned_runes, owned_battlefields = _owned_support_weights(snapshot, collection_by_key or {})
        fallback_runes = _round_with_caps(
            owned_runes,
            total=max(1, snapshot.rune_deck_size),
            collection_by_key=collection_by_key or {},
        )
        fallback_battlefields = _ordered_battlefields(
            owned_battlefields,
            allowed_titles=allowed_battlefields,
            count=snapshot.battlefield_count,
        )
        if fallback_runes and len(fallback_battlefields) >= snapshot.battlefield_count:
            return fallback_runes, fallback_battlefields[: snapshot.battlefield_count], "owned-eligibility"
        return {}, [], "strict-unavailable"

    fallback_runes = dict(snapshot.recommended_runes)
    fallback_battlefields = []
    for card in snapshot.battlefields:
        if card.title not in fallback_battlefields:
            fallback_battlefields.append(card.title)
        if len(fallback_battlefields) >= snapshot.battlefield_count:
            break
    return fallback_runes, fallback_battlefields[: snapshot.battlefield_count], "eligibility"


def _support_only_failure(validation) -> bool:
    issue_codes = {str(issue.code) for issue in validation.issues}
    return bool(issue_codes) and issue_codes.issubset(_SUPPORT_ONLY_ISSUE_CODES)


def _build_deck_payload(*, plan: GenerationPlan, main_by_key: dict[str, int], cards, runes: dict[str, int], battlefields: list[str]) -> DeckPayload:
    main = {cards.by_key[key].title: int(qty) for key, qty in main_by_key.items() if int(qty) > 0 and key in cards.by_key}
    return DeckPayload(
        name=f"{plan.archetype_name or plan.win_condition_label} Auto Deck",
        source="auto-builder",
        format="constructed",
        legendTitle=plan.legend_title,
        chosenChampionTitle=plan.chosen_champion_title,
        main=main,
        runes=runes,
        battlefields=battlefields,
        sideboard={},
    )


def _collection_supports_payload(deck: DeckPayload, *, collection_by_key: dict[str, int]) -> bool:
    requirements = Counter({str(title): max(0, int(qty)) for title, qty in deck.main.items() if int(qty) > 0})
    if deck.legend_title:
        requirements[deck.legend_title] += 1
    if deck.chosen_champion_title:
        requirements[deck.chosen_champion_title] = max(1, int(requirements.get(deck.chosen_champion_title, 0)))
    for title, qty in deck.runes.items():
        if int(qty) > 0:
            requirements[title] += int(qty)
    for title in deck.battlefields:
        if str(title or "").strip():
            requirements[str(title).strip()] += 1
    for title, qty in deck.sideboard.items():
        if int(qty) > 0:
            requirements[title] += int(qty)
    for title, qty in requirements.items():
        if _title_owned_qty(collection_by_key, title) < int(qty):
            return False
    return True


def _validate_completed_candidate(*, plan: GenerationPlan, main_by_key: dict[str, int], bundle: dict[str, Any], cards, rules, seed_row: dict[str, Any] | None = None, collection_by_key: dict[str, int] | None = None, strict_buildable: bool = False) -> tuple[DeckPayload | None, str]:
    runes, battlefields, fallback_label = _finish_support_cards(
        plan=plan,
        main_by_key=main_by_key,
        bundle=bundle,
        cards=cards,
        rules=rules,
        seed_row=seed_row,
        prefer_seed_first=False,
        collection_by_key=collection_by_key,
        strict_buildable=strict_buildable,
    )
    deck = _build_deck_payload(plan=plan, main_by_key=main_by_key, cards=cards, runes=runes, battlefields=battlefields)
    validation = validate_deck(deck, rules=rules, cards=cards)
    if validation.is_valid and (not strict_buildable or _collection_supports_payload(deck, collection_by_key=collection_by_key or {})):
        return deck, fallback_label
    if _support_only_failure(validation):
        runes, battlefields, retry_label = _finish_support_cards(
            plan=plan,
            main_by_key=main_by_key,
            bundle=bundle,
            cards=cards,
            rules=rules,
            seed_row=seed_row,
            prefer_seed_first=True,
            collection_by_key=collection_by_key,
            strict_buildable=strict_buildable,
        )
        retry_deck = _build_deck_payload(plan=plan, main_by_key=main_by_key, cards=cards, runes=runes, battlefields=battlefields)
        retry_validation = validate_deck(retry_deck, rules=rules, cards=cards)
        if retry_validation.is_valid and (not strict_buildable or _collection_supports_payload(retry_deck, collection_by_key=collection_by_key or {})):
            return retry_deck, f"{fallback_label}->{retry_label}"
    return None, fallback_label


def rank_replacements_for_missing_card(*, missing_key: str, deck: DeckPayload, bundle: dict[str, Any], cards, collection_by_key: dict[str, int], dominant_win_condition: int, top_k: int = 6) -> list[dict[str, Any]]:
    runtime_cache = _bundle_runtime(bundle, cards)
    static_features = runtime_cache["staticFeatures"]
    embeddings = runtime_cache["embeddings"]
    model = bundle.get("replacementModel")
    cluster_by_card = runtime_cache["clusterByCard"]
    wc_card_freq = {int(key): dict(value) for key, value in dict(bundle.get("winConditionCardFrequency") or {}).items()}
    target_title = cards.by_key.get(missing_key).title if missing_key in cards.by_key else missing_key
    main_by_key = deck_main_from_payload(deck, cards=cards)
    rows = []
    for candidate_key, qty in collection_by_key.items():
        if int(qty) <= 0 or candidate_key == missing_key:
            continue
        if not _can_add_card(main_by_key=main_by_key, candidate_key=candidate_key, cards=cards, legend_title=deck.legend_title):
            continue
        features = _replacement_feature_row(missing_key, candidate_key, static_features=static_features, card_embeddings=embeddings, dominant_component=dominant_win_condition, cluster_by_card=cluster_by_card, wc_card_freq=wc_card_freq, availability=float(qty))
        base_score = _safe_model_predict(model, np.array(features, dtype=np.float32), default=float(features[0] * 0.45 + features[2] * 0.2 + features[3] * 0.2 + features[6] * 0.15))
        rows.append({"card": cards.by_key[candidate_key].title if candidate_key in cards.by_key else candidate_key, "owned": int(qty), "available": int(qty), "score": round(base_score, 4), "source": "hybrid", "reason": f"Learned replacement for {target_title}", "winConditionMatch": round(float(features[6]), 4), "synergyMatch": round(float(features[3]), 4)})
    rows.sort(key=lambda row: (-float(row["score"]), row["card"].lower()))
    return rows[: max(1, int(top_k))]


def _load_generator_model(generator_state: dict[str, Any]) -> _MoECandidateScorer:
    return _generator_runtime(generator_state)["model"]


def prewarm_auto_builder_runtime(*, bundle: dict[str, Any], generator_state: dict[str, Any], cards) -> None:
    """Prime bundle and generator caches so first recommend() avoids one-time build cost."""
    _bundle_runtime(bundle, cards)
    _generator_runtime(generator_state)


def _generator_runtime(generator_state: dict[str, Any], *, model: _MoECandidateScorer | None = None) -> dict[str, Any]:
    requested_device = _resolve_torch_device(None).type
    cached = generator_state.get("_runtime")
    if isinstance(cached, dict) and cached.get("deviceType") == requested_device and cached.get("model") is not None:
        return cached
    runtime_model = model or _MoECandidateScorer(
        state_dim=int(generator_state.get("stateDim") or 0),
        candidate_dim=64,
        legend_count=max(1, len(generator_state.get("legendToIdx") or {})),
        champion_count=max(1, len(generator_state.get("championToIdx") or {})),
    )
    runtime_model.load_state_dict(generator_state.get("stateDict") or {})
    device = _resolve_torch_device(None)
    runtime_model.to(device)
    runtime_model.eval()
    runtime = {"model": runtime_model, "device": device, "deviceType": device.type}
    generator_state["_runtime"] = runtime
    return runtime


def _complete_main_greedily(*, plan: GenerationPlan, main_by_key: dict[str, int], target_main_size: int, bundle: dict[str, Any], cards, generator_state: dict[str, Any], collection_by_key: dict[str, int], strict_buildable: bool) -> dict[str, int] | None:
    model = _load_generator_model(generator_state)
    runtime_cache = _bundle_runtime(bundle, cards)
    embeddings = runtime_cache["embeddings"]
    static_features = runtime_cache["staticFeatures"]
    cluster_by_card = runtime_cache["clusterByCard"]
    working = {str(key): int(qty) for key, qty in main_by_key.items() if int(qty) > 0}
    while sum(int(value) for value in working.values()) < target_main_size:
        pool = _candidate_card_pool(
            plan=plan,
            partial_main=working,
            bundle=bundle,
            cards=cards,
            collection_by_key=collection_by_key,
            embedding_vectors=embeddings,
            cluster_by_card=cluster_by_card,
            strict_buildable=strict_buildable,
        )
        scored = []
        eligible_keys = []
        for candidate_key in pool[:_PURE_POOL_LIMIT]:
            if not _can_add_card(
                main_by_key=working,
                candidate_key=candidate_key,
                cards=cards,
                legend_title=plan.legend_title,
                collection_by_key=collection_by_key,
                strict_buildable=strict_buildable,
            ):
                continue
            eligible_keys.append(candidate_key)
        scored.extend(
            _score_candidate_keys(
                model=model,
                generator_state=generator_state,
                plan=plan,
                partial_main=working,
                candidate_keys=eligible_keys,
                bundle=bundle,
                cards=cards,
                embeddings=embeddings,
                static_features=static_features,
                cluster_by_card=cluster_by_card,
                collection_by_key=collection_by_key,
                runtime_cache=runtime_cache,
            )
        )
        scored.sort(key=lambda row: (-row[0], row[1]))
        if not scored:
            return None
        best_key = scored[0][1]
        working[best_key] = int(working.get(best_key, 0)) + 1
    return working if sum(int(value) for value in working.values()) == target_main_size else None


def generate_pure_candidate(*, plan: GenerationPlan, bundle: dict[str, Any], cards, rules, generator_state: dict[str, Any], collection_by_key: dict[str, int] | None = None, strict_buildable: bool = False) -> tuple[DeckPayload | None, str]:
    model = _load_generator_model(generator_state)
    collection_by_key = collection_by_key or {}
    target_main_size = _main_deck_target_size(rules)
    if strict_buildable and not _collection_supports_plan(plan, collection_by_key):
        return None, "strict-plan-unavailable"
    runtime_cache = _bundle_runtime(bundle, cards)
    embeddings = runtime_cache["embeddings"]
    static_features = runtime_cache["staticFeatures"]
    cluster_by_card = runtime_cache["clusterByCard"]
    champion_key = normalize_card_key(plan.chosen_champion_title)
    if strict_buildable and champion_key and _owned_qty(collection_by_key, champion_key) <= 0:
        return None, "strict-champion-unavailable"
    beam = [({champion_key: 1} if champion_key else {}, 0.0)]
    seed_rows = _plan_seed_rows(bundle, plan)
    for _step in range(max(0, target_main_size - (1 if champion_key else 0))):
        next_beam: list[tuple[dict[str, int], float]] = []
        for main_by_key, score in beam:
            pool = _candidate_card_pool(
                plan=plan,
                partial_main=main_by_key,
                bundle=bundle,
                cards=cards,
                collection_by_key=collection_by_key,
                embedding_vectors=embeddings,
                cluster_by_card=cluster_by_card,
                strict_buildable=strict_buildable,
            )
            eligible_keys = []
            for candidate_key in pool[:_PURE_POOL_LIMIT]:
                if not _can_add_card(
                    main_by_key=main_by_key,
                    candidate_key=candidate_key,
                    cards=cards,
                    legend_title=plan.legend_title,
                    collection_by_key=collection_by_key,
                    strict_buildable=strict_buildable,
                ):
                    continue
                eligible_keys.append(candidate_key)
            scored = _score_candidate_keys(
                model=model,
                generator_state=generator_state,
                plan=plan,
                partial_main=main_by_key,
                candidate_keys=eligible_keys,
                bundle=bundle,
                cards=cards,
                embeddings=embeddings,
                static_features=static_features,
                cluster_by_card=cluster_by_card,
                collection_by_key=collection_by_key,
                runtime_cache=runtime_cache,
            )
            scored.sort(key=lambda row: (-row[0], row[1]))
            for candidate_score_value, candidate_key in scored[:_PURE_EXPANSION_LIMIT]:
                updated = dict(main_by_key)
                updated[candidate_key] = int(updated.get(candidate_key, 0)) + 1
                next_beam.append((updated, score + float(candidate_score_value)))
        if not next_beam:
            break
        deduped: dict[str, tuple[dict[str, int], float]] = {}
        for main_by_key, score in next_beam:
            signature = deck_signature_from_main(main_by_key, leader_title=plan.legend_title, champion_title=plan.chosen_champion_title)
            existing = deduped.get(signature)
            if existing is None or score > existing[1]:
                deduped[signature] = (main_by_key, score)
        beam = sorted(deduped.values(), key=lambda row: (-row[1], deck_signature_from_main(row[0])))[:_PURE_BEAM_WIDTH]
    best_fallback = ""
    for main_by_key, _score in beam:
        if sum(int(value) for value in main_by_key.values()) != target_main_size:
            continue
        completed, fallback = _validate_completed_candidate(
            plan=plan,
            main_by_key=main_by_key,
            bundle=bundle,
            cards=cards,
            rules=rules,
            seed_row=seed_rows[0] if seed_rows else None,
            collection_by_key=collection_by_key,
            strict_buildable=strict_buildable,
        )
        if completed is not None:
            return completed, fallback
        best_fallback = fallback
    # Greedy repair: take highest-scoring partial beam state and greedily complete
    if beam:
        champion_main, _champ_score = beam[0]
        repaired = _complete_main_greedily(
            plan=plan,
            main_by_key=champion_main,
            target_main_size=target_main_size,
            bundle=bundle,
            cards=cards,
            generator_state=generator_state,
            collection_by_key=collection_by_key,
            strict_buildable=strict_buildable,
        )
        if repaired is not None:
            completed, fallback = _validate_completed_candidate(
                plan=plan,
                main_by_key=repaired,
                bundle=bundle,
                cards=cards,
                rules=rules,
                seed_row=seed_rows[0] if seed_rows else None,
                collection_by_key=collection_by_key,
                strict_buildable=strict_buildable,
            )
            if completed is not None:
                return completed, fallback
            best_fallback = fallback or best_fallback
    return None, best_fallback


def adapt_seed_candidate(*, plan: GenerationPlan, bundle: dict[str, Any], cards, rules, collection_by_key: dict[str, int], generator_state: dict[str, Any] | None = None, strict_buildable: bool = False) -> tuple[DeckPayload | None, str]:
    target_main_size = _main_deck_target_size(rules)
    candidate_rows = _plan_seed_rows(bundle, plan)
    if strict_buildable and not _collection_supports_plan(plan, collection_by_key):
        return None, "strict-plan-unavailable"
    best_fallback = ""
    for row in candidate_rows[:_SEED_ADAPT_LIMIT]:
        working = {str(key): int(qty) for key, qty in dict(row.get("mainByKey") or {}).items() if int(qty) > 0}
        if sum(int(value) for value in working.values()) != target_main_size:
            continue
        if strict_buildable:
            working = {
                key: min(int(qty), _owned_qty(collection_by_key, key))
                for key, qty in working.items()
                if min(int(qty), _owned_qty(collection_by_key, key)) > 0
            }
            champion_key = normalize_card_key(plan.chosen_champion_title)
            if champion_key and int(working.get(champion_key, 0)) <= 0:
                continue
            if sum(int(value) for value in working.values()) > target_main_size:
                continue
            if sum(int(value) for value in working.values()) < target_main_size:
                if generator_state is None:
                    continue
                completed_main = _complete_main_greedily(
                    plan=plan,
                    main_by_key=working,
                    target_main_size=target_main_size,
                    bundle=bundle,
                    cards=cards,
                    generator_state=generator_state,
                    collection_by_key=collection_by_key,
                    strict_buildable=True,
                )
                if completed_main is None:
                    continue
                working = completed_main
        completed, fallback = _validate_completed_candidate(
            plan=plan,
            main_by_key=working,
            bundle=bundle,
            cards=cards,
            rules=rules,
            seed_row=row,
            collection_by_key=collection_by_key,
            strict_buildable=strict_buildable,
        )
        if completed is not None:
            return completed, fallback
        best_fallback = fallback
    return None, best_fallback


def prototype_candidate(*, plan: GenerationPlan, bundle: dict[str, Any], cards, rules, collection_by_key: dict[str, int] | None = None, strict_buildable: bool = False) -> tuple[DeckPayload | None, str]:
    archetype = _bundle_runtime(bundle, cards)["archetypeProfiles"].get(plan.archetype_id, {})
    prototype_main = {str(key): int(qty) for key, qty in dict(archetype.get("prototypeMain") or {}).items() if int(qty) > 0}
    if not prototype_main:
        return None, ""
    if strict_buildable:
        collection_by_key = collection_by_key or {}
        if not _collection_supports_plan(plan, collection_by_key):
            return None, "strict-plan-unavailable"
        for key, qty in prototype_main.items():
            if _owned_qty(collection_by_key, key) < int(qty):
                return None, "strict-prototype-unavailable"
    seed_rows = _plan_seed_rows(bundle, plan)
    return _validate_completed_candidate(
        plan=plan,
        main_by_key=prototype_main,
        bundle=bundle,
        cards=cards,
        rules=rules,
        seed_row=seed_rows[0] if seed_rows else None,
        collection_by_key=collection_by_key,
        strict_buildable=strict_buildable,
    )


def build_candidate_payload(*, deck: DeckPayload, plan: GenerationPlan, build_mode: str, bundle: dict[str, Any], cards, rules, prices, collection: dict[str, int], ranking_mode: str, validation_fallback: str = "") -> CandidateDeck:
    analysis = __import__("app.domain.auto_builder_scoring", fromlist=["analysis_snapshot"]).analysis_snapshot(deck=deck, collection=collection, cards=cards, unit_price_for_title=prices.cheapest_price_for_title, buy_url_for_title=prices.tcgplayer_search_url)
    main_by_key = deck_main_from_payload(deck, cards=cards)
    runtime_cache = _bundle_runtime(bundle, cards)
    embeddings = runtime_cache["embeddings"]
    static_features = runtime_cache["staticFeatures"]
    cluster_by_card = runtime_cache["clusterByCard"]
    raw_profile_vectors = bundle.get("deckVectors")
    profile_vectors = np.array(raw_profile_vectors, dtype=np.float32) if raw_profile_vectors is not None else np.zeros((0,), dtype=np.float32)
    seed_decks = [{"source": seed.source, "deckId": seed.deck_id, "deckName": seed.deck_name, "score": round(float(seed.score), 4)} for seed in plan.seed_decks[:3]]
    deck_win_vector = _project_win_condition_vector(main_by_key, bundle=bundle, win_vector_size=int(runtime_cache.get("deckVectorWinSize") or _deck_vector_win_size(bundle)))
    target_win_vector = _plan_win_condition_vector(plan, bundle=bundle, win_vector_size=deck_win_vector.shape[0])
    if profile_vectors.size:
        query_vec = deck_vector(main_by_key=main_by_key, card_embeddings=embeddings, embedding_dim=64, win_condition_vector=deck_win_vector, static_features=static_features)
        competitive_model = bundle.get("competitiveModel")
        competitive_score = _safe_model_predict(competitive_model, query_vec, default=0.0)
    else:
        competitive_score = 0.0
    validation = validate_deck(deck, rules=rules, cards=cards)
    deck_cluster_ids = sorted({int(cluster_by_card.get(key, -1)) for key in main_by_key.keys() if int(cluster_by_card.get(key, -1)) >= 0})
    win_condition_match = max(0.0, min(1.0, cosine_similarity(deck_win_vector, target_win_vector)))
    candidate_score_value = candidate_score(competitive_score=competitive_score, win_condition_match=win_condition_match, synergy_cluster_coverage=synergy_cluster_coverage(selected_cluster_ids=list(plan.synergy_cluster_ids), deck_cluster_ids=deck_cluster_ids), legality_margin=legality_margin_from_issues(len(validation.issues)), curve_balance=curve_balance_from_curve(deck_cost_curve(main_by_key, static_features)))
    replacement_confidence = 1.0 if analysis.is_buildable else max(0.0, 1.0 - (float(analysis.missing_copies) / 12.0))
    ranking = ranking_score(ranking_mode=ranking_mode, candidate_score_value=candidate_score_value, competitive_score=competitive_score, buildable=analysis.is_buildable, completion_pct=analysis.completion_pct, replacement_confidence=replacement_confidence, estimated_completion_cost=analysis.estimated_completion_cost)
    buildable_conversion_signal = max(
        0.0,
        min(
            1.0,
            0.65 * float(getattr(plan, "archetype_buildable_conversion", 0.0))
            + 0.35 * float(getattr(plan, "shell_buildable_conversion", 0.0)),
        ),
    )
    buildability_prior_signal = max(
        0.0,
        min(
            1.0,
            0.60 * float(getattr(plan, "archetype_buildability_prior", 0.0))
            + 0.40 * float(getattr(plan, "shell_buildability_prior", 0.0)),
        ),
    )
    ranking += 0.05 * buildability_prior_signal
    if build_mode == "prototype":
        ranking += 0.10 * buildable_conversion_signal + 0.05 * buildability_prior_signal
    elif analysis.is_buildable:
        ranking += 0.04 * buildable_conversion_signal
    explanations = explanation_rows(win_condition_label=plan.win_condition_label, synergy_labels=list(plan.synergy_cluster_labels), build_mode=build_mode, seed_count=len(seed_decks))
    if build_mode == "prototype" or buildable_conversion_signal > 0.0:
        explanations.append({"kind": "buildability", "label": "Buildable Conversion", "value": f"{buildable_conversion_signal:.2f}"})
    if validation_fallback:
        explanations.append({"kind": "support", "label": "Support Finish", "value": validation_fallback})
    return CandidateDeck(build_mode=build_mode, deck=deck, shell_id=plan.shell_id, shell_label=plan.shell_label, archetype_id=plan.archetype_id, archetype_name=plan.archetype_name, archetype_confidence=plan.archetype_confidence, win_condition_id=plan.win_condition_id, win_condition_label=plan.win_condition_label, win_condition_confidence=round(win_condition_match, 4), synergy_cluster_ids=list(plan.synergy_cluster_ids), synergy_cluster_labels=list(plan.synergy_cluster_labels), competitive_score=round(competitive_score, 4), candidate_score=round(candidate_score_value, 4), ranking_score=round(ranking, 4), source_breakdown=dict(plan.source_breakdown), validation_fallback=validation_fallback, completion_pct=analysis.completion_pct, is_buildable=analysis.is_buildable, estimated_completion_cost=analysis.estimated_completion_cost, missing_copies=analysis.missing_copies, missing_unique_cards=analysis.missing_unique_cards, missing_cards=[row.model_dump() for row in analysis.missing_cards], replacement_suggestions=[row.model_dump() for row in analysis.replacement_suggestions], replacement_confidence=round(replacement_confidence, 4), explanations=explanations, seed_decks=seed_decks)
