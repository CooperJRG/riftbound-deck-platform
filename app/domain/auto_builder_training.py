from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import platform
import pickle
import random
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Callable

import numpy as np
import sklearn
from sklearn.cluster import SpectralClustering
from sklearn.decomposition import NMF, TruncatedSVD
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import silhouette_score
from sklearn.neighbors import NearestNeighbors
from sklearn.tree import DecisionTreeRegressor
import torch
from torch import nn
from torch.nn import functional as F

from app.domain.auto_builder_features import (
    CardStaticFeatures,
    apply_tfidf_dampening,
    build_card_static_features,
    build_card_text_features,
    build_deck_matrix,
    build_main_vocab,
    build_training_rows,
    component_confidence,
    cosine_similarity,
    deck_cost_curve,
    deck_domain_balance,
    deck_special_counts,
    deck_type_ratios,
    deck_vector,
    legend_domains_for_title,
    mean_embedding_for_main,
    pearson_rank_correlation,
    shell_id_for_titles,
    shell_label_for_titles,
    tokenize_effect_text,
)
from app.domain.auto_builder_types import ArchetypeProfile, PlanSeed, ShellProfile, SynergyCluster, TrainingDeckRow, WinConditionComponent
from app.domain.normalization import normalize_card_key
from app.domain.rules import load_format_rules
from app.infra.cards_repo import CardCatalog, load_card_catalog
from app.infra.meta_repo import MetaDeckRepository

_EMBEDDING_DIM = 64
_NEGATIVE_SAMPLES = 15
_MAX_WIN_CONDITION_COMPONENTS = 96
_MAX_SYNERGY_CLUSTERS = 192
_NMF_CANDIDATE_GRID = (20,)
_SYNERGY_CANDIDATE_GRID = (24, 28, 32, 36, 40, 48)
_KNN_NEIGHBORS = 25
_MOE_EXPERTS = 8
_CLUSTER_VECTOR_SIZE = 64
_WIN_VECTOR_SIZE = 32
_ARCHETYPE_JACCARD_THRESHOLD = 0.78
_ARCHETYPE_MIN_DECKS = 4
_DEFAULT_MIN_RESULTS = 12
_DEFAULT_MAX_VARIANTS_PER_SHELL = 2
_EVAL_COLLECTION_SCENARIOS = 3
_TORCH_DEVICE_ENV = "RB_AUTO_BUILDER_TORCH_DEVICE"
_DEFAULT_MIN_WIN_CONDITION_COUNT = 56
_DEFAULT_MIN_SYNERGY_CLUSTER_COUNT = 112
_DEFAULT_SYNTHETIC_PACK_MIN = 24
_DEFAULT_SYNTHETIC_PACK_MAX = 240
_DEFAULT_SYNTHETIC_SCENARIO_COUNT = 4
_EMBEDDING_NEIGHBOR_COUNT = 12
_MOE_TOP_K = 2
_MOE_LOAD_BALANCE_ALPHA = 0.08
_TEXT_EMB_DIM = 32
_RESOLUTION_MODE_AUTO = "auto"
_RESOLUTION_MODE_SEARCH = "search"
_RESOLUTION_MODE_REUSE = "reuse"


def _main_deck_target_size(rules) -> int:
    try:
        return max(1, int(rules.int_constraint("main_deck_size_exact", 40)))
    except Exception:
        return 40


def _runtime_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": str(np.__version__),
        "sklearn": str(getattr(sklearn, "__version__", "")),
        "torch": str(getattr(torch, "__version__", "")),
    }


def _resolve_torch_device(requested: str | None = None) -> torch.device:
    choice = str(requested or os.environ.get(_TORCH_DEVICE_ENV, "auto")).strip().lower()
    if choice in {"", "auto"}:
        if torch.cuda.is_available():
            return torch.device("cuda")
        mps_backend = getattr(torch.backends, "mps", None)
        if mps_backend is not None and mps_backend.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    if choice in {"cuda", "gpu"}:
        return torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
    if choice == "mps":
        mps_backend = getattr(torch.backends, "mps", None)
        return torch.device("mps") if mps_backend is not None and mps_backend.is_available() else torch.device("cpu")
    return torch.device("cpu")


def _prepare_torch_runtime(device: torch.device) -> None:
    if hasattr(torch, "set_float32_matmul_precision"):
        try:
            torch.set_float32_matmul_precision("high")
        except Exception:
            pass
    if device.type == "cuda":
        try:
            torch.backends.cuda.matmul.allow_tf32 = True
        except Exception:
            pass
        try:
            torch.backends.cudnn.allow_tf32 = True
        except Exception:
            pass
        try:
            torch.backends.cudnn.benchmark = True
        except Exception:
            pass


def _emit_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    *,
    stage: str,
    step: int,
    total_steps: int,
    message: str,
    extra: dict[str, Any] | None = None,
) -> None:
    if callback is None:
        return
    payload = {
        "stage": str(stage or "").strip(),
        "step": max(0, int(step)),
        "totalSteps": max(1, int(total_steps)),
        "progressPct": round(100.0 * float(max(0, int(step))) / float(max(1, int(total_steps))), 2),
        "message": str(message or "").strip(),
    }
    if extra:
        payload.update(dict(extra))
    try:
        callback(payload)
    except Exception:
        pass


def _progress_checkpoints(total: int, *, target_updates: int = 5) -> set[int]:
    total = max(1, int(total))
    if total <= max(2, int(target_updates)):
        return set(range(1, total + 1))
    checkpoints = {
        1,
        total,
        int(math.ceil(total * 0.25)),
        int(math.ceil(total * 0.50)),
        int(math.ceil(total * 0.75)),
    }
    return {min(total, max(1, int(value))) for value in checkpoints}


def _emit_stage_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    *,
    stage: str,
    step: int,
    total_steps: int,
    message: str,
    current: int,
    total: int,
    extra: dict[str, Any] | None = None,
) -> None:
    total = max(1, int(total))
    current = min(total, max(1, int(current)))
    payload = {
        "stageCurrent": current,
        "stageTotal": total,
        "stageProgressPct": round(100.0 * float(current) / float(total), 2),
    }
    if extra:
        payload.update(dict(extra))
    _emit_progress(
        callback,
        stage=stage,
        step=step,
        total_steps=total_steps,
        message=message,
        extra=payload,
    )


def _rarity_bucket(card) -> str:
    rarity = str(getattr(card, "rarity", "") or "").strip().lower()
    if "common" in rarity:
        return "common"
    if "uncommon" in rarity:
        return "uncommon"
    if "epic" in rarity or "showcase" in rarity:
        return "epic"
    if "rare" in rarity:
        return "rare"
    return "common"


def _build_synthetic_collection_config(cards: CardCatalog, config: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = dict(config or {})
    pack_min = max(24, min(240, int(raw.get("packMin") or _DEFAULT_SYNTHETIC_PACK_MIN)))
    pack_max = max(pack_min, min(240, int(raw.get("packMax") or _DEFAULT_SYNTHETIC_PACK_MAX)))
    scenario_count = max(1, int(raw.get("scenarioCount") or _DEFAULT_SYNTHETIC_SCENARIO_COUNT))
    rune_unlimited = bool(raw.get("runeUnlimited", True))
    pools: dict[str, list[str]] = {"common": [], "uncommon": [], "rare": [], "epic": []}
    rune_keys: list[str] = []
    for key, card in cards.by_key.items():
        if not key:
            continue
        pools[_rarity_bucket(card)].append(key)
        if str(getattr(card, "card_type", "") or "").strip() == "Rune":
            rune_keys.append(key)
    return {
        "packMin": pack_min,
        "packMax": pack_max,
        "scenarioCount": scenario_count,
        "runeUnlimited": rune_unlimited,
        "pools": {bucket: list(values) for bucket, values in pools.items()},
        "runeKeys": list(rune_keys),
        "summary": {
            "commonPool": len(pools["common"]),
            "uncommonPool": len(pools["uncommon"]),
            "rarePool": len(pools["rare"]),
            "epicPool": len(pools["epic"]),
        },
    }


def _sample_from_pool(rng: random.Random, pool: list[str], count: int, collection: Counter[str]) -> None:
    if not pool or count <= 0:
        return
    for _ in range(max(0, int(count))):
        collection[rng.choice(pool)] += 1


def _pack_simulated_collection(
    *,
    rng: random.Random,
    synthetic_config: dict[str, Any] | None,
) -> Counter[str]:
    config = dict(synthetic_config or {})
    pack_min = max(24, min(240, int(config.get("packMin") or _DEFAULT_SYNTHETIC_PACK_MIN)))
    pack_max = max(pack_min, min(240, int(config.get("packMax") or _DEFAULT_SYNTHETIC_PACK_MAX)))
    pools = {bucket: list(values) for bucket, values in dict(config.get("pools") or {}).items()}
    collection: Counter[str] = Counter()
    pack_count = rng.randint(pack_min, pack_max)
    for _pack_idx in range(pack_count):
        _sample_from_pool(rng, pools.get("common") or [], 7, collection)
        _sample_from_pool(rng, pools.get("uncommon") or [], 3, collection)
        rare_pool = pools.get("rare") or []
        epic_pool = pools.get("epic") or []
        if epic_pool and rng.random() < 0.25:
            collection[rng.choice(epic_pool)] += 1
        else:
            _sample_from_pool(rng, rare_pool or epic_pool, 1, collection)
        if epic_pool and rng.random() < (1.0 / 12.0):
            collection[rng.choice(epic_pool)] += 1
        else:
            _sample_from_pool(rng, rare_pool or epic_pool, 1, collection)
    if bool(config.get("runeUnlimited", True)):
        for key in list(config.get("runeKeys") or []):
            collection[key] = max(int(collection.get(key, 0)), 24)
    return collection


def _select_nmf_components(*, training_deck_count: int, card_vocab_size: int, min_count: int | None = None) -> int:
    return _select_nmf_components_from_metrics(
        training_deck_count=training_deck_count,
        card_vocab_size=card_vocab_size,
        shell_count=None,
        min_count=min_count,
        candidate_metrics=None,
    )


def _round_up_to_step(value: int, *, step: int) -> int:
    step = max(1, int(step))
    return max(step, int(math.ceil(float(max(1, value)) / float(step))) * step)


def _domain_min_win_condition_count(*, training_deck_count: int, card_vocab_size: int, shell_count: int | None = None, min_count: int | None = None) -> int:
    if training_deck_count < 800:
        target = 24
    elif training_deck_count < 1200:
        target = 40
    elif training_deck_count < 1800:
        target = 56
    elif training_deck_count < 2600:
        target = 64
    else:
        target = 72
    if shell_count:
        target = max(target, _round_up_to_step(int(math.ceil(float(shell_count) * 0.90)), step=8))
    if min_count:
        target = max(target, int(min_count))
    return max(1, min(_MAX_WIN_CONDITION_COMPONENTS, card_vocab_size - 1, training_deck_count - 1, _round_up_to_step(target, step=8)))


def _candidate_nmf_component_counts(*, training_deck_count: int, card_vocab_size: int, shell_count: int | None = None, min_count: int | None = None) -> list[int]:
    max_allowed = max(1, min(_MAX_WIN_CONDITION_COMPONENTS, card_vocab_size - 1, training_deck_count - 1))
    floor = _domain_min_win_condition_count(training_deck_count=training_deck_count, card_vocab_size=card_vocab_size, shell_count=shell_count, min_count=min_count)
    candidates = sorted({min(max_allowed, int(value)) for value in _NMF_CANDIDATE_GRID if int(value) <= max_allowed and int(value) > 0} | {min(max_allowed, floor)})
    return candidates or [max_allowed]


def _trim_candidate_counts(candidates: list[int], *, anchor: int, min_keep: int = 6) -> list[int]:
    ordered = sorted({max(1, int(value)) for value in candidates if int(value) > 0})
    if len(ordered) <= max(1, int(min_keep)):
        return ordered
    anchor_value = max(1, int(anchor))
    anchor_idx = min(range(len(ordered)), key=lambda idx: (abs(ordered[idx] - anchor_value), ordered[idx]))
    chosen = {
        ordered[0],
        ordered[min(1, len(ordered) - 1)],
        ordered[max(0, anchor_idx - 1)],
        ordered[anchor_idx],
        ordered[min(len(ordered) - 1, anchor_idx + 1)],
        ordered[-1],
    }
    return sorted(chosen)


def _select_nmf_components_from_metrics(*, training_deck_count: int, card_vocab_size: int, shell_count: int | None, min_count: int | None, candidate_metrics: dict[int, dict[str, float]] | None) -> int:
    fallback = _domain_min_win_condition_count(training_deck_count=training_deck_count, card_vocab_size=card_vocab_size, shell_count=shell_count, min_count=min_count)
    if not candidate_metrics:
        return fallback
    ranked = []
    for candidate, metrics in {int(candidate): metrics for candidate, metrics in candidate_metrics.items()}.items():
        ranked.append(
            (
                float(metrics.get("compositeScore") or 0.0),
                float(metrics.get("strictBuildableHitRate") or 0.0),
                -float(metrics.get("strictBuildableEmptyResultRate") or 0.0),
                float(metrics.get("strictBuildableCandidateDensity") or 0.0),
                float(metrics.get("recommendationHitRate") or 0.0),
                float(metrics.get("reconstructionRecall") or 0.0),
                -abs(int(candidate) - int(fallback)),
                -int(candidate),
                int(candidate),
            )
        )
    ranked.sort(reverse=True)
    return int(ranked[0][-1]) if ranked else fallback


def _select_synergy_cluster_count(*, training_deck_count: int, card_vocab_size: int, min_count: int | None = None) -> int:
    return _select_synergy_cluster_count_from_metrics(
        training_deck_count=training_deck_count,
        card_vocab_size=card_vocab_size,
        shell_count=None,
        win_condition_count=None,
        min_count=min_count,
        candidate_metrics=None,
    )


def _domain_min_synergy_cluster_count(*, training_deck_count: int, card_vocab_size: int, shell_count: int | None = None, win_condition_count: int | None = None, min_count: int | None = None) -> int:
    if training_deck_count < 800:
        target = 48
    elif training_deck_count < 1200:
        target = 80
    elif training_deck_count < 1800:
        target = 112
    elif training_deck_count < 2600:
        target = 128
    else:
        target = 144
    if win_condition_count:
        target = max(target, int(win_condition_count) * 2)
    if shell_count:
        target = max(target, _round_up_to_step(int(math.ceil(float(shell_count) * 2.0)), step=16))
    if min_count:
        target = max(target, int(min_count))
    return max(2, min(_MAX_SYNERGY_CLUSTERS, card_vocab_size, _round_up_to_step(target, step=16)))


def _candidate_synergy_cluster_counts(*, training_deck_count: int, card_vocab_size: int, shell_count: int | None = None, win_condition_count: int | None = None, min_count: int | None = None) -> list[int]:
    max_allowed = max(2, min(_MAX_SYNERGY_CLUSTERS, card_vocab_size))
    floor = _domain_min_synergy_cluster_count(training_deck_count=training_deck_count, card_vocab_size=card_vocab_size, shell_count=shell_count, win_condition_count=win_condition_count, min_count=min_count)
    candidates = sorted({min(max_allowed, int(value)) for value in _SYNERGY_CANDIDATE_GRID if int(value) <= max_allowed and int(value) > 1} | {min(max_allowed, floor)})
    return candidates or [max_allowed]


def _select_synergy_cluster_count_from_metrics(*, training_deck_count: int, card_vocab_size: int, shell_count: int | None, win_condition_count: int | None, min_count: int | None, candidate_metrics: dict[int, dict[str, float]] | None) -> int:
    fallback = _domain_min_synergy_cluster_count(training_deck_count=training_deck_count, card_vocab_size=card_vocab_size, shell_count=shell_count, win_condition_count=win_condition_count, min_count=min_count)
    if not candidate_metrics:
        return fallback
    ranked = []
    for candidate, metrics in {int(candidate): metrics for candidate, metrics in candidate_metrics.items()}.items():
        ranked.append(
            (
                float(metrics.get("compositeScore") or 0.0),
                float(metrics.get("replacementQuality") or 0.0),
                float(metrics.get("modularityProxy") or 0.0),
                float(metrics.get("coverageScore") or 0.0),
                -abs(int(candidate) - int(fallback)),
                -int(candidate),
                int(candidate),
            )
        )
    ranked.sort(reverse=True)
    return int(ranked[0][-1]) if ranked else fallback


def _training_corpus_fingerprint(
    *,
    train_rows: list[TrainingDeckRow],
    valid_rows: list[TrainingDeckRow],
    index_to_key: list[str],
    shell_count: int,
    main_deck_size: int,
) -> str:
    hasher = hashlib.sha256()
    hasher.update(
        (
            f"train={len(train_rows)}|valid={len(valid_rows)}|cards={len(index_to_key)}|"
            f"shells={int(shell_count)}|main={int(main_deck_size)}\n"
        ).encode("utf-8")
    )
    for label, rows in (("train", train_rows), ("valid", valid_rows)):
        for row in sorted(
            rows,
            key=lambda item: (
                str(item.source or "").lower(),
                str(item.deck_id or "").lower(),
                str(item.leader_title or "").lower(),
                str(item.chosen_champion_title or "").lower(),
                str(item.deck_signature or "").lower(),
            ),
        ):
            hasher.update(
                (
                    f"{label}|{str(row.source or '').lower()}|{str(row.deck_id or '').lower()}|"
                    f"{str(row.leader_title or '').lower()}|{str(row.chosen_champion_title or '').lower()}|"
                    f"{str(row.deck_signature or '').lower()}|{float(row.sample_weight):.6f}|"
                    f"{float(row.meta_score):.4f}\n"
                ).encode("utf-8")
            )
    for key in sorted(str(value or "").lower() for value in index_to_key):
        hasher.update(f"card|{key}\n".encode("utf-8"))
    return hasher.hexdigest()


def _load_reference_artifact_metadata(reference_artifact_dir: Path | None) -> dict[str, Any]:
    if reference_artifact_dir is None:
        return {}
    metadata_path = reference_artifact_dir / "metadata.json"
    if not metadata_path.is_file():
        return {}
    try:
        return dict(json.loads(metadata_path.read_text(encoding="utf-8")))
    except Exception:
        return {}


def _selected_metric_subset(raw_metrics: dict[str, Any] | None, *, selected_count: int) -> dict[int, dict[str, float]]:
    metrics = dict(raw_metrics or {})
    selected = metrics.get(str(int(selected_count)))
    if not isinstance(selected, dict):
        return {}
    return {int(selected_count): {str(key): float(value) for key, value in dict(selected).items()}}


def _resolve_reference_artifact_path(*, out_dir: Path, reference_artifact_dir: Path | None) -> Path | None:
    if reference_artifact_dir is not None:
        return reference_artifact_dir
    return out_dir if out_dir.is_dir() else None


def _resolve_reused_resolution_counts(
    *,
    reference_metadata: dict[str, Any],
    reference_artifact_dir: Path | None,
    training_corpus_fingerprint: str,
    resolution_mode: str,
    resolved_min_win_conditions: int,
    resolved_min_synergy_clusters: int,
    max_win_condition_count: int,
    max_synergy_cluster_count: int,
) -> dict[str, Any]:
    mode = str(resolution_mode or _RESOLUTION_MODE_AUTO).strip().lower() or _RESOLUTION_MODE_AUTO
    if mode not in {_RESOLUTION_MODE_AUTO, _RESOLUTION_MODE_SEARCH, _RESOLUTION_MODE_REUSE}:
        mode = _RESOLUTION_MODE_AUTO
    if mode == _RESOLUTION_MODE_SEARCH:
        return {"mode": _RESOLUTION_MODE_SEARCH, "selectedWinConditionCount": 0, "selectedSynergyClusterCount": 0, "referenceArtifact": ""}
    selected_win = int(reference_metadata.get("selectedWinConditionCount") or reference_metadata.get("winConditionCount") or 0)
    selected_synergy = int(reference_metadata.get("selectedSynergyClusterCount") or reference_metadata.get("synergyClusterCount") or 0)
    reference_fingerprint = str(reference_metadata.get("trainingCorpusFingerprint") or "").strip().lower()
    effective_min_win_conditions = min(max_win_condition_count, max(1, int(resolved_min_win_conditions)))
    effective_min_synergy_clusters = min(max_synergy_cluster_count, max(2, int(resolved_min_synergy_clusters)))
    compatible = bool(reference_fingerprint) and reference_fingerprint == str(training_corpus_fingerprint or "").strip().lower()
    compatible = compatible and effective_min_win_conditions <= selected_win <= max_win_condition_count
    compatible = compatible and effective_min_synergy_clusters <= selected_synergy <= max_synergy_cluster_count
    if compatible:
        return {
            "mode": _RESOLUTION_MODE_REUSE,
            "selectedWinConditionCount": int(selected_win),
            "selectedSynergyClusterCount": int(selected_synergy),
            "referenceArtifact": str(reference_artifact_dir) if reference_artifact_dir is not None else "",
        }
    if mode == _RESOLUTION_MODE_REUSE:
        raise RuntimeError(
            "Resolution reuse was requested, but the reference artifact is missing compatible selected counts "
            "for the current training corpus."
        )
    return {"mode": _RESOLUTION_MODE_SEARCH, "selectedWinConditionCount": 0, "selectedSynergyClusterCount": 0, "referenceArtifact": ""}


class _Item2VecModel(nn.Module):
    def __init__(self, vocab_size: int, embedding_dim: int):
        super().__init__()
        self.input_emb = nn.Embedding(vocab_size, embedding_dim)
        self.output_emb = nn.Embedding(vocab_size, embedding_dim)
        nn.init.xavier_uniform_(self.input_emb.weight)
        nn.init.xavier_uniform_(self.output_emb.weight)

    def forward(self, center: torch.Tensor, context: torch.Tensor, negative: torch.Tensor) -> torch.Tensor:
        center_vec = self.input_emb(center)
        context_vec = self.output_emb(context)
        negative_vec = self.output_emb(negative)
        pos_score = torch.sum(center_vec * context_vec, dim=1)
        pos_loss = F.binary_cross_entropy_with_logits(pos_score, torch.ones_like(pos_score), reduction="none")
        neg_score = torch.einsum("bd,bnd->bn", center_vec, negative_vec)
        neg_loss = F.binary_cross_entropy_with_logits(neg_score, torch.zeros_like(neg_score), reduction="none").sum(dim=1)
        return pos_loss + neg_loss


class _MoECandidateScorer(nn.Module):
    def __init__(self, state_dim: int, candidate_dim: int, legend_count: int, champion_count: int):
        super().__init__()
        self._last_gate_probs: torch.Tensor | None = None
        self._last_top_idx: torch.Tensor | None = None
        self.legend_emb = nn.Embedding(max(1, legend_count), 16)
        self.champion_emb = nn.Embedding(max(1, champion_count), 16)
        gate_in = state_dim + 32
        self.gate = nn.Sequential(
            nn.Linear(gate_in, 128),
            nn.ReLU(),
            nn.Linear(128, _MOE_EXPERTS),
        )
        self.experts = nn.ModuleList(
            [
                nn.Sequential(
                    nn.Linear(state_dim + candidate_dim + 32, 128),
                    nn.ReLU(),
                    nn.Linear(128, 128),
                    nn.ReLU(),
                    nn.Linear(128, 1),
                )
                for _ in range(_MOE_EXPERTS)
            ]
        )

    def forward(
        self,
        state: torch.Tensor,
        candidate: torch.Tensor,
        legend_idx: torch.Tensor,
        champion_idx: torch.Tensor,
    ) -> torch.Tensor:
        legend_vec = self.legend_emb(legend_idx)
        champion_vec = self.champion_emb(champion_idx)
        gate_input = torch.cat([state, legend_vec, champion_vec], dim=1)
        gate_logits = self.gate(gate_input)
        gate_probs = torch.softmax(gate_logits, dim=1)
        top_k = min(_MOE_TOP_K, _MOE_EXPERTS)
        top_k_logits, top_k_idx = torch.topk(gate_logits, k=top_k, dim=1)
        sparse_scores = torch.softmax(top_k_logits, dim=1)
        self._last_gate_probs = gate_probs
        self._last_top_idx = top_k_idx.detach()
        shared = torch.cat([state, candidate, legend_vec, champion_vec], dim=1)
        all_outputs = torch.cat([expert(shared) for expert in self.experts], dim=1)
        selected_outputs = torch.gather(all_outputs, 1, top_k_idx)
        return torch.sum(selected_outputs * sparse_scores, dim=1)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_split_key(text: str) -> float:
    total = 2166136261
    for ch in text:
        total ^= ord(ch)
        total = (total * 16777619) & 0xFFFFFFFF
    return float(total % 10000) / 10000.0


def _train_validation_split(rows: list[TrainingDeckRow]) -> tuple[list[TrainingDeckRow], list[TrainingDeckRow]]:
    if not rows:
        return [], []
    sorted_rows = sorted(rows, key=lambda row: float(row.age_days or 0.0), reverse=True)
    if len(sorted_rows) <= 6:
        return sorted_rows, []
    val_count = max(1, int(round(len(sorted_rows) * 0.18)))
    return sorted_rows[:-val_count], sorted_rows[-val_count:]


def _all_positive_pairs(rows: list[TrainingDeckRow], *, vocab: dict[str, int], seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = random.Random(seed)
    centers: list[int] = []
    contexts: list[int] = []
    weights: list[float] = []
    for row in rows:
        tokens = [vocab[key] for key in row.main_cards_multiset if key in vocab]
        if len(tokens) < 2:
            continue
        for idx, center in enumerate(tokens):
            other_positions = [pos for pos in range(len(tokens)) if pos != idx]
            rng.shuffle(other_positions)
            for pos in other_positions[:8]:
                centers.append(center)
                contexts.append(tokens[pos])
                weights.append(float(row.sample_weight))
    if not centers:
        return np.zeros((0,), dtype=np.int64), np.zeros((0,), dtype=np.int64), np.zeros((0,), dtype=np.float32)
    return (
        np.array(centers, dtype=np.int64),
        np.array(contexts, dtype=np.int64),
        np.array(weights, dtype=np.float32),
    )


def train_item2vec(
    rows: list[TrainingDeckRow],
    *,
    vocab: dict[str, int],
    index_to_key: list[str],
    epochs: int,
    embedding_dim: int = _EMBEDDING_DIM,
    negative_samples: int = _NEGATIVE_SAMPLES,
    seed: int = 13,
    torch_device: str | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    progress_step: int | None = None,
    progress_total_steps: int | None = None,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    if not vocab:
        return {}, {"epochs": 0, "loss": 0.0, "embeddingDim": embedding_dim}
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    np.random.seed(seed)
    random.seed(seed)
    device = _resolve_torch_device(torch_device)
    _prepare_torch_runtime(device)
    model = _Item2VecModel(len(vocab), embedding_dim).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    epoch_total_for_scheduler = max(1, int(epochs))
    scheduler_i2v = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epoch_total_for_scheduler, eta_min=1e-4)
    centers_np, contexts_np, weights_np = _all_positive_pairs(rows, vocab=vocab, seed=seed)
    if centers_np.size == 0:
        return {key: np.zeros((embedding_dim,), dtype=np.float32) for key in index_to_key}, {"epochs": 0, "loss": 0.0, "embeddingDim": embedding_dim, "torchDevice": device.type}
    batch_size = 4096 if device.type == "cuda" else 2048 if device.type == "mps" else 1024
    losses: list[float] = []
    vocab_size = len(vocab)
    epoch_total = max(1, int(epochs))
    epoch_checkpoints = _progress_checkpoints(epoch_total)
    for epoch_idx in range(epoch_total):
        if progress_callback is not None and progress_step is not None and progress_total_steps is not None and (epoch_idx + 1) in epoch_checkpoints:
            _emit_stage_progress(
                progress_callback,
                stage="item2vec",
                step=int(progress_step),
                total_steps=int(progress_total_steps),
                message=f"Training Item2Vec epoch {epoch_idx + 1}/{epoch_total}.",
                current=epoch_idx + 1,
                total=epoch_total,
                extra={"epoch": epoch_idx + 1, "epochs": epoch_total, "torchDevice": device.type},
            )
        order = np.arange(centers_np.shape[0])
        np.random.shuffle(order)
        running = 0.0
        running_count = 0
        for start in range(0, order.size, batch_size):
            idx = order[start : start + batch_size]
            center = torch.from_numpy(centers_np[idx]).to(device=device, dtype=torch.long)
            context = torch.from_numpy(contexts_np[idx]).to(device=device, dtype=torch.long)
            weights = torch.from_numpy(weights_np[idx]).to(device=device, dtype=torch.float32)
            negative = torch.randint(low=0, high=vocab_size, size=(center.shape[0], negative_samples), dtype=torch.long, device=device)
            loss = model(center, context, negative)
            weighted = (loss * weights).mean()
            optimizer.zero_grad()
            weighted.backward()
            optimizer.step()
            running += float(weighted.detach().cpu()) * center.shape[0]
            running_count += int(center.shape[0])
        epoch_loss = running / max(1, running_count)
        losses.append(epoch_loss)
        scheduler_i2v.step()
        if progress_callback is not None and progress_step is not None and progress_total_steps is not None and epoch_total > 1 and (epoch_idx + 1) in epoch_checkpoints:
            _emit_stage_progress(
                progress_callback,
                stage="item2vec",
                step=int(progress_step),
                total_steps=int(progress_total_steps),
                message=f"Completed Item2Vec epoch {epoch_idx + 1}/{epoch_total}.",
                current=epoch_idx + 1,
                total=epoch_total,
                extra={"epoch": epoch_idx + 1, "epochs": epoch_total, "loss": round(float(epoch_loss), 6), "torchDevice": device.type},
            )
    with torch.inference_mode():
        emb = model.input_emb.weight.detach().cpu().numpy().astype(np.float32)
    state_dict = {key: value.detach().cpu() for key, value in model.state_dict().items()}
    return {key: emb[idx] for idx, key in enumerate(index_to_key)}, {"epochs": max(1, int(epochs)), "loss": float(losses[-1]), "embeddingDim": embedding_dim, "torchDevice": device.type, "stateDict": state_dict}


def _component_labels(
    H: np.ndarray,
    W: np.ndarray,
    *,
    index_to_key: list[str],
    rows: list[TrainingDeckRow],
    cards: CardCatalog,
) -> list[WinConditionComponent]:
    out: list[WinConditionComponent] = []
    component_count = H.shape[0] if H.ndim == 2 else 0
    dominant_idx = np.argmax(W, axis=1) if W.size else np.zeros((len(rows),), dtype=np.int64)
    competitive_by_component: dict[int, list[float]] = defaultdict(list)
    for row_idx, comp_idx in enumerate(dominant_idx.tolist()):
        competitive_by_component[int(comp_idx)].append(float(rows[row_idx].meta_score))
    for comp_idx in range(component_count):
        weights = H[comp_idx]
        top_card_idx = np.argsort(weights)[::-1][:8]
        top_keys = [index_to_key[idx] for idx in top_card_idx if idx < len(index_to_key) and weights[idx] > 0]
        top_titles = [cards.by_key[key].title for key in top_keys if key in cards.by_key]
        deck_rows = [rows[i] for i, row_comp in enumerate(dominant_idx.tolist()) if int(row_comp) == comp_idx]
        leader_counts = Counter(row.leader_title for row in deck_rows if row.leader_title)
        champion_counts = Counter(row.chosen_champion_title for row in deck_rows if row.chosen_champion_title)
        effect_tokens = Counter()
        for key in top_keys[:5]:
            card = cards.by_key.get(key)
            if card is None:
                continue
            effect_tokens.update(tokenize_effect_text(card.effect))
        label_parts = [f"WC{comp_idx + 1:02d}"]
        if champion_counts:
            label_parts.append(champion_counts.most_common(1)[0][0].split(" - ")[0].split(",")[0].strip())
        elif leader_counts:
            label_parts.append(leader_counts.most_common(1)[0][0].split(" - ")[0].split(",")[0].strip())
        top_tokens = [tok for tok, _count in effect_tokens.most_common(2)]
        label_parts.extend(top_tokens)
        label = " | ".join(part for part in label_parts if part).strip() or f"WC{comp_idx + 1:02d}"
        avg_meta = float(np.mean(competitive_by_component.get(comp_idx, [0.0]))) if competitive_by_component.get(comp_idx) else 0.0
        out.append(
            WinConditionComponent(
                component_id=comp_idx,
                label=label,
                top_cards=tuple(top_titles[:8]),
                top_effect_tokens=tuple(top_tokens),
                sample_deck_count=len(deck_rows),
                avg_competitive_score=round(avg_meta, 4),
            )
        )
    return out


def _row_requirement_by_key(row: TrainingDeckRow) -> dict[str, int]:
    req = Counter({key: max(0, int(qty)) for key, qty in row.main_by_key.items() if int(qty) > 0})
    legend_key = normalize_card_key(row.leader_title)
    champion_key = normalize_card_key(row.chosen_champion_title)
    if legend_key:
        req[legend_key] += 1
    if champion_key:
        req[champion_key] = max(1, int(req.get(champion_key, 0)))
    for title, qty in row.deck.runes.items():
        key = normalize_card_key(title)
        if key and int(qty) > 0:
            req[key] += int(qty)
    for title in row.deck.battlefields:
        key = normalize_card_key(title)
        if key:
            req[key] += 1
    return dict(req)


def _essential_requirement_keys(row: TrainingDeckRow) -> set[str]:
    keys: set[str] = set()
    legend_key = normalize_card_key(row.leader_title)
    champion_key = normalize_card_key(row.chosen_champion_title)
    if legend_key:
        keys.add(legend_key)
    if champion_key:
        keys.add(champion_key)
    for title, qty in row.deck.runes.items():
        key = normalize_card_key(title)
        if key and int(qty) > 0:
            keys.add(key)
    for title in row.deck.battlefields:
        key = normalize_card_key(title)
        if key:
            keys.add(key)
    return keys


def _synthetic_collection_for_row(
    row: TrainingDeckRow,
    *,
    donor_rows: list[TrainingDeckRow],
    cards: CardCatalog,
    buildable_target: bool,
    synthetic_config: dict[str, Any] | None = None,
    salt: str = "",
) -> dict[str, int]:
    rng = random.Random(f"{row.source}:{row.deck_id}:{'buildable' if buildable_target else 'mixed'}:{salt}")
    target_req = Counter(_row_requirement_by_key(row))
    essential_keys = _essential_requirement_keys(row)
    collection: Counter[str] = _pack_simulated_collection(rng=rng, synthetic_config=synthetic_config)
    if buildable_target:
        collection.update(target_req)
    else:
        for key, qty in target_req.items():
            keep = int(qty)
            if key not in essential_keys and keep > 0:
                if rng.random() < 0.62:
                    keep = max(0, keep - 1)
                if keep > 1 and rng.random() < 0.18:
                    keep = max(0, keep - 1)
            if keep > 0:
                collection[key] += keep
    row_shell = shell_id_for_titles(cards=cards, legend_title=row.leader_title, chosen_champion_title=row.chosen_champion_title)
    same_shell_rows = [
        other
        for other in donor_rows
        if other.deck_signature != row.deck_signature
        and shell_id_for_titles(cards=cards, legend_title=other.leader_title, chosen_champion_title=other.chosen_champion_title) == row_shell
    ]
    other_shell_rows = [
        other
        for other in donor_rows
        if other.deck_signature != row.deck_signature
        and shell_id_for_titles(cards=cards, legend_title=other.leader_title, chosen_champion_title=other.chosen_champion_title) != row_shell
    ]
    rng.shuffle(same_shell_rows)
    rng.shuffle(other_shell_rows)
    donor_selection = same_shell_rows[:2] + other_shell_rows[:2]
    for donor_idx, donor in enumerate(donor_selection):
        donor_req = _row_requirement_by_key(donor)
        keep_prob = 0.58 if donor_idx < 2 else 0.34
        if not buildable_target:
            keep_prob *= 0.82
        for key, qty in donor_req.items():
            qty_int = max(0, int(qty))
            if qty_int <= 0:
                continue
            if key in essential_keys and key not in target_req and rng.random() > 0.25:
                continue
            if key not in essential_keys and rng.random() > keep_prob:
                continue
            add_qty = max(1, min(qty_int, 1 + (qty_int - 1 if buildable_target and rng.random() < 0.35 else 0)))
            collection[key] += add_qty
    return {key: int(qty) for key, qty in collection.items() if int(qty) > 0}


def _synthetic_collection_pair(
    row: TrainingDeckRow,
    *,
    donor_rows: list[TrainingDeckRow],
    cards: CardCatalog,
    synthetic_config: dict[str, Any] | None = None,
    salt: str = "",
) -> tuple[dict[str, int], dict[str, int]]:
    mixed = _synthetic_collection_for_row(
        row,
        donor_rows=donor_rows,
        cards=cards,
        buildable_target=False,
        synthetic_config=synthetic_config,
        salt=salt,
    )
    strict = _synthetic_collection_for_row(
        row,
        donor_rows=donor_rows,
        cards=cards,
        buildable_target=True,
        synthetic_config=synthetic_config,
        salt=salt,
    )
    return mixed, strict


def _synthetic_collection_scenarios(
    row: TrainingDeckRow,
    *,
    donor_rows: list[TrainingDeckRow],
    cards: CardCatalog,
    synthetic_config: dict[str, Any] | None = None,
    salt: str = "",
    scenario_count: int = _EVAL_COLLECTION_SCENARIOS,
) -> list[tuple[dict[str, int], dict[str, int]]]:
    derived_count = int((synthetic_config or {}).get("scenarioCount") or scenario_count)
    return [
        _synthetic_collection_pair(
            row,
            donor_rows=donor_rows,
            cards=cards,
            synthetic_config=synthetic_config,
            salt=f"{salt}:scenario-{idx}",
        )
        for idx in range(max(1, derived_count))
    ]


def _completion_against_collection(requirement_by_key: dict[str, int], collection_by_key: dict[str, int]) -> float:
    total = sum(max(0, int(qty)) for qty in requirement_by_key.values())
    if total <= 0:
        return 0.0
    owned = 0
    for key, qty in requirement_by_key.items():
        owned += min(max(0, int(qty)), max(0, int(collection_by_key.get(key, 0))))
    return float(owned) / float(total)


def _is_buildable_from_collection(requirement_by_key: dict[str, int], collection_by_key: dict[str, int]) -> bool:
    return all(max(0, int(collection_by_key.get(key, 0))) >= max(0, int(qty)) for key, qty in requirement_by_key.items())


def _component_topic_coherence(H: np.ndarray, *, index_to_key: list[str], rows: list[TrainingDeckRow]) -> float:
    if H.size <= 0 or not rows or not index_to_key:
        return 0.0
    row_sets = [set(row.main_by_key.keys()) for row in rows]
    weights = [float(row.sample_weight) for row in rows]
    total_weight = float(sum(weights)) or 1.0
    scores: list[float] = []
    for comp_idx in range(H.shape[0]):
        top_idx = [idx for idx in np.argsort(H[comp_idx])[::-1][:5] if idx < len(index_to_key) and H[comp_idx][idx] > 0]
        top_keys = [index_to_key[idx] for idx in top_idx]
        if len(top_keys) < 2:
            continue
        pair_scores: list[float] = []
        for left_idx in range(len(top_keys)):
            for right_idx in range(left_idx + 1, len(top_keys)):
                left = top_keys[left_idx]
                right = top_keys[right_idx]
                joint = 0.0
                union = 0.0
                for row_set, weight in zip(row_sets, weights):
                    if left in row_set or right in row_set:
                        union += weight
                    if left in row_set and right in row_set:
                        joint += weight
                pair_scores.append(0.0 if union <= 0 else joint / union)
        if pair_scores:
            scores.append(float(np.mean(pair_scores)))
    return float(np.mean(scores)) if scores else 0.0


def _component_shell_coverage_balance(*, rows: list[TrainingDeckRow], dominant_components: np.ndarray, cards: CardCatalog) -> float:
    if not rows or dominant_components.size <= 0:
        return 0.0
    total_shells = {
        shell_id_for_titles(cards=cards, legend_title=row.leader_title, chosen_champion_title=row.chosen_champion_title)
        for row in rows
    }
    denom = float(max(1, len(total_shells)))
    coverage_scores = []
    for component in sorted(set(int(value) for value in dominant_components.tolist())):
        shells = {
            shell_id_for_titles(cards=cards, legend_title=rows[idx].leader_title, chosen_champion_title=rows[idx].chosen_champion_title)
            for idx, value in enumerate(dominant_components.tolist())
            if int(value) == component
        }
        coverage_scores.append(min(1.0, float(len(shells)) / denom))
    return float(np.mean(coverage_scores)) if coverage_scores else 0.0


def _evaluate_nmf_candidate(
    *,
    candidate: int,
    train_rows: list[TrainingDeckRow],
    valid_rows: list[TrainingDeckRow],
    deck_matrix_weighted: np.ndarray,
    valid_weighted: np.ndarray,
    index_to_key: list[str],
    cards: CardCatalog,
    synthetic_config: dict[str, Any] | None = None,
) -> dict[str, float]:
    max_components = max(1, min(deck_matrix_weighted.shape[0], deck_matrix_weighted.shape[1]))
    component_count = max(1, min(max_components, int(candidate)))
    model = NMF(n_components=component_count, init="nndsvda", random_state=13, max_iter=600)
    W_train = model.fit_transform(np.maximum(deck_matrix_weighted, 0.0))
    H = model.components_
    W_valid = model.transform(np.maximum(valid_weighted, 0.0)) if valid_rows and valid_weighted.size else np.zeros((0, component_count), dtype=np.float32)
    dominant_train = np.argmax(W_train, axis=1) if W_train.size else np.zeros((len(train_rows),), dtype=np.int64)
    dominant_valid = np.argmax(W_valid, axis=1) if W_valid.size else np.zeros((len(valid_rows),), dtype=np.int64)
    try:
        silhouette = float(silhouette_score(W_train, dominant_train)) if len(set(dominant_train.tolist())) > 1 and W_train.shape[0] > len(set(dominant_train.tolist())) else 0.0
    except Exception:
        silhouette = 0.0
    recommendation_hits = 0
    strict_hits = 0
    reconstruction_hits = 0
    strict_candidate_counts: list[int] = []
    for row_idx, row in enumerate(valid_rows):
        row_shell = shell_id_for_titles(cards=cards, legend_title=row.leader_title, chosen_champion_title=row.chosen_champion_title)
        collection_scenarios = _synthetic_collection_scenarios(
            row,
            donor_rows=train_rows or valid_rows,
            cards=cards,
            synthetic_config=synthetic_config,
            salt=f"nmf-{candidate}",
        )
        component_vec = W_valid[row_idx] if row_idx < W_valid.shape[0] else np.zeros((component_count,), dtype=np.float32)
        scenario_recommendation_hits = 0.0
        scenario_strict_hits = 0.0
        for mixed_collection, strict_collection in collection_scenarios:
            best_score = -1.0
            best_shell = ""
            strict_score = -1.0
            strict_shell = ""
            strict_candidates = 0
            for train_idx, train_row in enumerate(train_rows):
                train_shell = shell_id_for_titles(cards=cards, legend_title=train_row.leader_title, chosen_champion_title=train_row.chosen_champion_title)
                requirement = _row_requirement_by_key(train_row)
                completion = _completion_against_collection(requirement, mixed_collection)
                component_match = cosine_similarity(component_vec, W_train[train_idx]) if row_idx < W_valid.shape[0] else 0.0
                score = 0.55 * completion + 0.25 * max(0.0, component_match) + 0.20 * (1.0 if train_shell == row_shell else 0.0)
                if score > best_score:
                    best_score = score
                    best_shell = train_shell
                if _is_buildable_from_collection(requirement, strict_collection):
                    strict_candidates += 1
                    strict_candidate_score = 0.60 * max(0.0, component_match) + 0.40 * (1.0 if train_shell == row_shell else 0.0)
                    if strict_candidate_score > strict_score:
                        strict_score = strict_candidate_score
                        strict_shell = train_shell
            strict_candidate_counts.append(strict_candidates)
            if best_shell == row_shell:
                scenario_recommendation_hits += 1.0
            if strict_shell == row_shell and strict_candidates > 0:
                scenario_strict_hits += 1.0
        scenario_denom = float(max(1, len(collection_scenarios)))
        recommendation_hits += scenario_recommendation_hits / scenario_denom
        strict_hits += scenario_strict_hits / scenario_denom
        target_key = next(iter(row.main_by_key.keys()), "")
        if target_key and row_idx < W_valid.shape[0]:
            ranked_idx = [idx for idx in np.argsort(H[int(dominant_valid[row_idx])])[::-1][:10] if idx < len(index_to_key)]
            ranked_keys = {index_to_key[idx] for idx in ranked_idx}
            if target_key in ranked_keys:
                reconstruction_hits += 1
    recommendation_hit_rate = float(recommendation_hits) / float(max(1, len(valid_rows)))
    strict_hit_rate = float(strict_hits) / float(max(1, len(valid_rows)))
    reconstruction_recall = float(reconstruction_hits) / float(max(1, len(valid_rows)))
    metrics = {
        "recommendationHitRate": round(recommendation_hit_rate, 4),
        "strictBuildableHitRate": round(strict_hit_rate, 4),
        "reconstructionRecall": round(reconstruction_recall, 4),
        "topicCoherence": round(_component_topic_coherence(H, index_to_key=index_to_key, rows=train_rows), 4),
        "shellCoverageBalance": round(_component_shell_coverage_balance(rows=train_rows, dominant_components=dominant_train, cards=cards), 4),
        "silhouette": round(float(silhouette), 4),
        "strictBuildableCandidateCountP50": round(float(np.percentile(strict_candidate_counts, 50)) if strict_candidate_counts else 0.0, 4),
        "strictBuildableCandidateCountP90": round(float(np.percentile(strict_candidate_counts, 90)) if strict_candidate_counts else 0.0, 4),
        "strictBuildableEmptyResultRate": round(float(sum(1 for value in strict_candidate_counts if value <= 0)) / float(max(1, len(strict_candidate_counts))), 4),
    }
    metrics["strictBuildableCandidateDensity"] = round(
        min(
            1.0,
            (
                0.55 * float(metrics["strictBuildableCandidateCountP50"])
                + 0.45 * float(metrics["strictBuildableCandidateCountP90"])
            )
            / 3.0,
        ),
        4,
    )
    metrics["compositeScore"] = round(
        0.24 * metrics["recommendationHitRate"]
        + 0.24 * metrics["strictBuildableHitRate"]
        + 0.08 * metrics["reconstructionRecall"]
        + 0.12 * metrics["topicCoherence"]
        + 0.08 * metrics["shellCoverageBalance"]
        + 0.08 * metrics["silhouette"]
        + 0.12 * metrics["strictBuildableCandidateDensity"]
        - 0.20 * metrics["strictBuildableEmptyResultRate"],
        4,
    )
    return metrics


def train_win_conditions(
    train_rows: list[TrainingDeckRow],
    *,
    deck_matrix_weighted: np.ndarray,
    index_to_key: list[str],
    cards: CardCatalog,
    component_count: int | None = None,
) -> tuple[NMF, np.ndarray, np.ndarray, list[WinConditionComponent]]:
    if deck_matrix_weighted.shape[0] <= 0 or deck_matrix_weighted.shape[1] <= 0:
        raise ValueError("Cannot train win conditions without a non-empty deck matrix.")
    max_components = max(1, min(deck_matrix_weighted.shape[0], deck_matrix_weighted.shape[1]))
    heuristic_components = int(component_count or _select_nmf_components(training_deck_count=len(train_rows), card_vocab_size=len(index_to_key)))
    component_count = max(1, min(max_components, heuristic_components))
    model = NMF(n_components=component_count, init="nndsvda", random_state=13, max_iter=600)
    W = model.fit_transform(np.maximum(deck_matrix_weighted, 0.0))
    H = model.components_
    components = _component_labels(H, W, index_to_key=index_to_key, rows=train_rows, cards=cards)
    return model, W.astype(np.float32), H.astype(np.float32), components

def _build_synergy_affinity(
    rows: list[TrainingDeckRow],
    *,
    index_to_key: list[str],
    card_embeddings: dict[str, np.ndarray],
) -> np.ndarray:
    vocab_size = len(index_to_key)
    if vocab_size <= 1:
        return np.eye(vocab_size, dtype=np.float32)
    key_to_idx = {key: idx for idx, key in enumerate(index_to_key)}
    presence = np.zeros((len(rows), vocab_size), dtype=np.float32)
    weights = np.array([row.sample_weight for row in rows], dtype=np.float32)
    for row_idx, row in enumerate(rows):
        for key in row.main_by_key.keys():
            col = key_to_idx.get(key)
            if col is not None:
                presence[row_idx, col] = 1.0
    total_weight = float(weights.sum()) or 1.0
    p_card = (presence * weights.reshape((-1, 1))).sum(axis=0) / total_weight
    # Vectorised cosine similarity
    emb_matrix = np.zeros((vocab_size, _EMBEDDING_DIM), dtype=np.float32)
    for idx, key in enumerate(index_to_key):
        vec = card_embeddings.get(key)
        if vec is not None:
            emb_matrix[idx] = np.asarray(vec, dtype=np.float32)
    norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
    norms[norms <= 0] = 1.0
    normalized = emb_matrix / norms
    cosine_matrix = normalized @ normalized.T
    cosine_norm = np.clip((cosine_matrix + 1.0) / 2.0, 0.0, 1.0)
    # Vectorised PMI
    w_presence = presence * weights.reshape((-1, 1))
    joint = (w_presence.T @ presence) / total_weight
    outer_p = np.outer(p_card, p_card)
    with np.errstate(divide="ignore", invalid="ignore"):
        pmi_raw = np.where(joint > 0, np.log(np.maximum(1e-6, joint) / np.maximum(1e-6, outer_p)), 0.0)
    pmi_norm = np.minimum(1.0, np.clip(pmi_raw, 0.0, None) / 4.0)
    affinity = (0.65 * pmi_norm + 0.35 * cosine_norm).astype(np.float32)
    np.fill_diagonal(affinity, 1.0)
    return affinity


def _build_embedding_neighbors(
    card_embeddings: dict[str, np.ndarray],
    *,
    index_to_key: list[str],
    top_k: int = _EMBEDDING_NEIGHBOR_COUNT,
) -> dict[str, list[str]]:
    keys = [key for key in index_to_key if key in card_embeddings]
    if not keys:
        return {}
    matrix = np.vstack([card_embeddings[key].astype(np.float32) for key in keys]).astype(np.float32, copy=False)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms <= 0] = 1.0
    normalized = matrix / norms
    similarity = normalized @ normalized.T
    np.fill_diagonal(similarity, -1.0)
    neighbor_count = max(1, min(int(top_k), max(1, similarity.shape[1] - 1)))
    top_idx = np.argpartition(-similarity, kth=min(neighbor_count - 1, similarity.shape[1] - 1), axis=1)[:, :neighbor_count]
    out: dict[str, list[str]] = {}
    for row_idx, key in enumerate(keys):
        ranked = sorted(
            ((float(similarity[row_idx, col_idx]), keys[col_idx]) for col_idx in top_idx[row_idx] if col_idx != row_idx),
            key=lambda item: (-item[0], item[1]),
        )
        out[key] = [neighbor_key for _score, neighbor_key in ranked[:neighbor_count]]
    return out


def _summarize_synergy_clusters(*, labels: np.ndarray, rows: list[TrainingDeckRow], index_to_key: list[str], cards: CardCatalog) -> list[SynergyCluster]:
    cluster_count = max(1, max((int(value) for value in labels.tolist()), default=-1) + 1)
    summaries: list[SynergyCluster] = []
    for cluster_id in range(cluster_count):
        member_idx = [idx for idx, label in enumerate(labels.tolist()) if int(label) == cluster_id]
        top_titles = [cards.by_key[index_to_key[idx]].title for idx in member_idx[:6] if index_to_key[idx] in cards.by_key]
        label = f"Cluster {cluster_id + 1}: " + ", ".join(title.split(" - ")[0] for title in top_titles[:2]) if top_titles else f"Cluster {cluster_id + 1}"
        comp_scores = [float(row.meta_score) for row in rows if {index_to_key[idx] for idx in member_idx} & set(row.main_by_key.keys())]
        summaries.append(
            SynergyCluster(
                cluster_id=cluster_id,
                label=label,
                top_cards=tuple(top_titles[:8]),
                avg_competitive_score=round(float(np.mean(comp_scores)) if comp_scores else 0.0, 4),
            )
        )
    return summaries


def _evaluate_synergy_candidate(
    *,
    candidate: int,
    rows: list[TrainingDeckRow],
    valid_rows: list[TrainingDeckRow],
    index_to_key: list[str],
    card_embeddings: dict[str, np.ndarray],
    cards: CardCatalog,
    static_features: dict[str, CardStaticFeatures],
    affinity: np.ndarray,
    synthetic_config: dict[str, Any] | None = None,
) -> tuple[np.ndarray, dict[str, float]]:
    cluster_count = max(2, min(int(candidate), len(index_to_key)))
    clustering = SpectralClustering(n_clusters=cluster_count, affinity="precomputed", random_state=13, assign_labels="kmeans")
    labels = clustering.fit_predict(affinity).astype(np.int64)
    cluster_by_card = {index_to_key[idx]: int(labels[idx]) for idx in range(len(index_to_key))}
    within = []
    across = []
    for left in range(len(index_to_key)):
        for right in range(left + 1, len(index_to_key)):
            score = float(affinity[left, right])
            if int(labels[left]) == int(labels[right]):
                within.append(score)
            else:
                across.append(score)
    modularity_proxy = max(0.0, float(np.mean(within)) - float(np.mean(across) if across else 0.0)) if within else 0.0
    replacement_scores = []
    for row in rows:
        row_keys = list(row.main_by_key.keys())
        if not row_keys:
            continue
        same_cluster_hits = 0
        for key in row_keys:
            key_cluster = cluster_by_card.get(key)
            if key_cluster is None:
                continue
            if any(other != key and cluster_by_card.get(other) == key_cluster for other in row_keys):
                same_cluster_hits += 1
        replacement_scores.append(float(same_cluster_hits) / float(max(1, len(row_keys))))
    coverage_scores = []
    for row in rows:
        distinct = len({cluster_by_card.get(key, -1) for key in row.main_by_key.keys() if key in cluster_by_card})
        coverage_scores.append(1.0 if 2 <= distinct <= min(6, cluster_count) else 0.0)
    repair_scores = []
    for row in valid_rows:
        scenario_scores: list[float] = []
        for _mixed_collection, strict_collection in _synthetic_collection_scenarios(
            row,
            donor_rows=rows,
            cards=cards,
            synthetic_config=synthetic_config,
            salt=f"synergy-{candidate}",
        ):
            owned_main = {key for key, qty in strict_collection.items() if int(qty) > 0}
            card_type_by_key = {key: static_features.get(key).card_type if static_features.get(key) is not None else "" for key in row.main_by_key.keys()}
            successes = 0
            attempts = 0
            for key in row.main_by_key.keys():
                attempts += 1
                target_cluster = cluster_by_card.get(key)
                if target_cluster is None:
                    continue
                target_type = card_type_by_key.get(key, "")
                if any(
                    other in owned_main
                    and other != key
                    and cluster_by_card.get(other) == target_cluster
                    and (static_features.get(other).card_type if static_features.get(other) is not None else "") == target_type
                    for other in row.main_by_key.keys()
                ):
                    successes += 1
            scenario_scores.append(float(successes) / float(max(1, attempts)))
        repair_scores.append(float(np.mean(scenario_scores)) if scenario_scores else 0.0)
    try:
        embedding_matrix = np.vstack([card_embeddings.get(key, np.zeros((_EMBEDDING_DIM,), dtype=np.float32)) for key in index_to_key]).astype(np.float32)
        silhouette = float(silhouette_score(embedding_matrix, labels)) if len(set(labels.tolist())) > 1 and embedding_matrix.shape[0] > len(set(labels.tolist())) else 0.0
    except Exception:
        silhouette = 0.0
    cluster_sizes = Counter(int(value) for value in labels.tolist())
    singleton_rate = float(sum(1 for value in cluster_sizes.values() if int(value) <= 1)) / float(max(1, len(cluster_sizes)))
    regularization = max(0.0, 1.0 - singleton_rate)
    metrics = {
        "replacementQuality": round(float(np.mean(replacement_scores)) if replacement_scores else 0.0, 4),
        "modularityProxy": round(float(modularity_proxy), 4),
        "coverageScore": round(float(np.mean(coverage_scores)) if coverage_scores else 0.0, 4),
        "buildableRepairSuccess": round(float(np.mean(repair_scores)) if repair_scores else 0.0, 4),
        "silhouette": round(float(silhouette), 4),
        "clusterSizeRegularization": round(float(regularization), 4),
    }
    metrics["compositeScore"] = round(
        0.25 * metrics["replacementQuality"]
        + 0.13 * metrics["modularityProxy"]
        + 0.20 * metrics["coverageScore"]
        + 0.22 * metrics["buildableRepairSuccess"]
        + 0.10 * metrics["silhouette"]
        + 0.10 * metrics["clusterSizeRegularization"],
        4,
    )
    return labels, metrics


def train_synergy_clusters(
    rows: list[TrainingDeckRow],
    *,
    index_to_key: list[str],
    card_embeddings: dict[str, np.ndarray],
    cards: CardCatalog,
    cluster_count: int | None = None,
    affinity: np.ndarray | None = None,
) -> tuple[np.ndarray, list[SynergyCluster], np.ndarray]:
    vocab_size = len(index_to_key)
    if vocab_size <= 1:
        labels = np.zeros((vocab_size,), dtype=np.int64)
        affinity = np.eye(vocab_size, dtype=np.float32)
        return labels, [], affinity
    affinity = np.array(affinity, dtype=np.float32, copy=False) if affinity is not None and np.size(affinity) else _build_synergy_affinity(rows, index_to_key=index_to_key, card_embeddings=card_embeddings)
    selected_count = max(2, min(vocab_size, int(cluster_count or _select_synergy_cluster_count(training_deck_count=len(rows), card_vocab_size=vocab_size))))
    clustering = SpectralClustering(n_clusters=selected_count, affinity="precomputed", random_state=13, assign_labels="kmeans")
    labels = clustering.fit_predict(affinity)
    summaries = _summarize_synergy_clusters(labels=labels, rows=rows, index_to_key=index_to_key, cards=cards)
    return labels.astype(np.int64), summaries, affinity


def _cluster_coverage(main_by_key: dict[str, int], *, cluster_by_card: dict[str, int], cluster_count: int) -> np.ndarray:
    vec = np.zeros((cluster_count,), dtype=np.float32)
    total = 0.0
    for key, qty in main_by_key.items():
        cluster_id = cluster_by_card.get(key)
        if cluster_id is None or cluster_id < 0 or cluster_id >= cluster_count:
            continue
        count = float(max(0, int(qty)))
        vec[cluster_id] += count
        total += count
    if total > 0:
        vec /= total
    return vec


def _deck_vectors(
    rows: list[TrainingDeckRow],
    *,
    card_embeddings: dict[str, np.ndarray],
    embedding_dim: int,
    win_condition_vectors: np.ndarray,
    static_features: dict[str, CardStaticFeatures],
) -> np.ndarray:
    out = []
    win_vector_size = int(win_condition_vectors.shape[1]) if win_condition_vectors.ndim == 2 and win_condition_vectors.shape[1] > 0 else _WIN_VECTOR_SIZE
    for row_idx, row in enumerate(rows):
        wc_vec = win_condition_vectors[row_idx] if row_idx < win_condition_vectors.shape[0] else np.zeros((win_vector_size,), dtype=np.float32)
        if wc_vec.shape[0] < win_vector_size:
            padded = np.zeros((win_vector_size,), dtype=np.float32)
            padded[: wc_vec.shape[0]] = wc_vec
            wc_vec = padded
        elif wc_vec.shape[0] > win_vector_size:
            wc_vec = wc_vec[:win_vector_size]
        out.append(deck_vector(main_by_key=row.main_by_key, card_embeddings=card_embeddings, embedding_dim=embedding_dim, win_condition_vector=wc_vec, static_features=static_features))
    return np.vstack(out).astype(np.float32) if out else np.zeros((0, embedding_dim + win_vector_size + 8 + 6 + 3 + 3), dtype=np.float32)


def _replacement_feature_row(
    target_key: str,
    candidate_key: str,
    *,
    static_features: dict[str, CardStaticFeatures],
    card_embeddings: dict[str, np.ndarray],
    dominant_component: int,
    cluster_by_card: dict[str, int],
    wc_card_freq: dict[int, dict[str, float]],
    availability: float,
) -> list[float]:
    target = static_features.get(target_key)
    candidate = static_features.get(candidate_key)
    target_vec = card_embeddings.get(target_key, np.zeros((_EMBEDDING_DIM,), dtype=np.float32))
    candidate_vec = card_embeddings.get(candidate_key, np.zeros((_EMBEDDING_DIM,), dtype=np.float32))
    cosine = cosine_similarity(target_vec, candidate_vec)
    domain_match = 0.0
    type_match = 0.0
    cluster_match = 0.0
    cost_delta = 1.0
    might_delta = 1.0
    same_wc = 0.0
    if target is not None and candidate is not None:
        type_match = 1.0 if target.card_type == candidate.card_type else 0.0
        t_domains = set(target.domains)
        c_domains = set(candidate.domains)
        domain_match = float(len(t_domains & c_domains)) / float(max(1, len(t_domains | c_domains)))
        cluster_match = 1.0 if cluster_by_card.get(target_key) == cluster_by_card.get(candidate_key) else 0.0
        cost_delta = max(0.0, 1.0 - (min(7.0, abs(float(target.cost) - float(candidate.cost))) / 7.0))
        might_delta = max(0.0, 1.0 - (min(8.0, abs(float(target.might) - float(candidate.might))) / 8.0))
    same_wc = float(wc_card_freq.get(dominant_component, {}).get(candidate_key, 0.0))
    return [float(cosine), type_match, domain_match, cluster_match, cost_delta, might_delta, same_wc, float(availability)]


def _replacement_training_examples(
    rows: list[TrainingDeckRow],
    *,
    static_features: dict[str, CardStaticFeatures],
    card_embeddings: dict[str, np.ndarray],
    dominant_components: np.ndarray,
    cluster_by_card: dict[str, int],
    wc_card_freq: dict[int, dict[str, float]],
    seed: int = 13,
) -> tuple[np.ndarray, np.ndarray]:
    rng = random.Random(seed)
    samples: list[list[float]] = []
    targets: list[float] = []
    card_keys = list(static_features.keys())
    for row_idx, row in enumerate(rows):
        dominant = int(dominant_components[row_idx]) if row_idx < dominant_components.shape[0] else 0
        for target_key in list(row.main_by_key.keys())[: min(6, len(row.main_by_key))]:
            samples.append(_replacement_feature_row(target_key, target_key, static_features=static_features, card_embeddings=card_embeddings, dominant_component=dominant, cluster_by_card=cluster_by_card, wc_card_freq=wc_card_freq, availability=1.0))
            targets.append(1.0)
            negatives = [key for key in card_keys if key != target_key]
            rng.shuffle(negatives)
            for neg_key in negatives[:8]:
                samples.append(_replacement_feature_row(target_key, neg_key, static_features=static_features, card_embeddings=card_embeddings, dominant_component=dominant, cluster_by_card=cluster_by_card, wc_card_freq=wc_card_freq, availability=1.0))
                targets.append(0.0)
    if not samples:
        return np.zeros((0, 8), dtype=np.float32), np.zeros((0,), dtype=np.float32)
    return np.array(samples, dtype=np.float32), np.array(targets, dtype=np.float32)


def _state_feature_vector(
    partial_main: dict[str, int],
    *,
    card_embeddings: dict[str, np.ndarray],
    static_features: dict[str, CardStaticFeatures],
    win_condition_vector: np.ndarray,
    cluster_by_card: dict[str, int],
    cluster_count: int,
    remaining_slots: int,
    total_main_slots: int = 40,
    win_vector_size: int | None = None,
    cluster_vector_size: int | None = None,
    card_text_embeddings: dict[str, np.ndarray] | None = None,
    text_emb_dim: int = 0,
) -> np.ndarray:
    emb = mean_embedding_for_main(partial_main, card_embeddings, dim=_EMBEDDING_DIM)
    resolved_win_size = max(1, int(win_vector_size or (win_condition_vector.shape[0] if win_condition_vector.ndim == 1 and win_condition_vector.shape[0] > 0 else _WIN_VECTOR_SIZE)))
    resolved_cluster_size = max(1, int(cluster_vector_size or cluster_count or _CLUSTER_VECTOR_SIZE))
    wc_vec = np.zeros((resolved_win_size,), dtype=np.float32)
    wc_vec[: min(resolved_win_size, win_condition_vector.shape[0])] = win_condition_vector[: min(resolved_win_size, win_condition_vector.shape[0])]
    cluster_vec = np.zeros((resolved_cluster_size,), dtype=np.float32)
    raw_cluster = _cluster_coverage(partial_main, cluster_by_card=cluster_by_card, cluster_count=cluster_count)
    cluster_vec[: min(resolved_cluster_size, raw_cluster.shape[0])] = raw_cluster[: min(resolved_cluster_size, raw_cluster.shape[0])]
    normalized_remaining = float(max(0, remaining_slots)) / float(max(1, total_main_slots))
    parts: list[np.ndarray] = [emb, deck_cost_curve(partial_main, static_features), deck_domain_balance(partial_main, static_features), deck_type_ratios(partial_main, static_features), deck_special_counts(partial_main, static_features), wc_vec, cluster_vec, np.array([normalized_remaining], dtype=np.float32)]
    if card_text_embeddings and text_emb_dim > 0:
        parts.append(mean_embedding_for_main(partial_main, card_text_embeddings, dim=text_emb_dim))
    return np.concatenate(parts).astype(np.float32)


def _moe_training_samples(
    rows: list[TrainingDeckRow],
    *,
    win_condition_vectors: np.ndarray,
    card_embeddings: dict[str, np.ndarray],
    static_features: dict[str, CardStaticFeatures],
    cluster_by_card: dict[str, int],
    legend_to_idx: dict[str, int],
    champion_to_idx: dict[str, int],
    total_main_slots: int,
    legend_to_legal_keys: dict[str, list[str]] | None = None,
    card_text_embeddings: dict[str, np.ndarray] | None = None,
    text_emb_dim: int = 0,
    seed: int = 13,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = random.Random(seed)
    state_rows: list[np.ndarray] = []
    candidate_rows: list[np.ndarray] = []
    legend_rows: list[int] = []
    champion_rows: list[int] = []
    targets: list[float] = []
    all_keys = list(card_embeddings.keys())
    cluster_count = max(1, max(cluster_by_card.values(), default=0) + 1)
    win_vector_size = int(win_condition_vectors.shape[1]) if win_condition_vectors.ndim == 2 and win_condition_vectors.shape[1] > 0 else _WIN_VECTOR_SIZE
    for row_idx, row in enumerate(rows):
        keys = list(row.main_by_key.keys())
        if len(keys) < 2:
            continue
        win_vec = win_condition_vectors[row_idx] if row_idx < win_condition_vectors.shape[0] else np.zeros((win_vector_size,), dtype=np.float32)
        for target_key in keys[: min(10, len(keys))]:
            partial = dict(row.main_by_key)
            partial[target_key] = max(0, int(partial.get(target_key, 0)) - 1)
            if partial[target_key] <= 0:
                del partial[target_key]
            remaining = total_main_slots - sum(partial.values())
            state_vec = _state_feature_vector(partial, card_embeddings=card_embeddings, static_features=static_features, win_condition_vector=win_vec, cluster_by_card=cluster_by_card, cluster_count=cluster_count, remaining_slots=remaining, total_main_slots=total_main_slots, win_vector_size=win_vector_size, cluster_vector_size=cluster_count, card_text_embeddings=card_text_embeddings, text_emb_dim=text_emb_dim)
            legend_idx = legend_to_idx.get(row.leader_title, 0)
            champion_idx = champion_to_idx.get(row.chosen_champion_title, 0)
            positive_candidate = card_embeddings.get(target_key)
            if positive_candidate is not None:
                state_rows.append(state_vec)
                candidate_rows.append(positive_candidate.astype(np.float32))
                legend_rows.append(legend_idx)
                champion_rows.append(champion_idx)
                targets.append(1.0)
            legal_pool = (legend_to_legal_keys.get(row.leader_title) or all_keys) if legend_to_legal_keys else all_keys
            target_cluster = cluster_by_card.get(target_key, -1)
            target_sf = static_features.get(target_key)
            target_domains = set(target_sf.domains) if target_sf is not None and target_sf.domains else set()
            hard_negatives = [
                key for key in legal_pool
                if key != target_key
                and cluster_by_card.get(key, -1) != target_cluster
                and target_domains
                and static_features.get(key) is not None
                and set(static_features[key].domains) & target_domains
            ]
            easy_negatives = [key for key in legal_pool if key != target_key and key not in set(hard_negatives)]
            rng.shuffle(hard_negatives)
            rng.shuffle(easy_negatives)
            selected_negatives = hard_negatives[:8] + easy_negatives[:7]
            for neg_key in selected_negatives:
                neg_vec = card_embeddings.get(neg_key)
                if neg_vec is None:
                    continue
                state_rows.append(state_vec)
                candidate_rows.append(neg_vec.astype(np.float32))
                legend_rows.append(legend_idx)
                champion_rows.append(champion_idx)
                targets.append(0.0)
    if not state_rows:
        state_dim = _EMBEDDING_DIM + 8 + 6 + 3 + 3 + win_vector_size + cluster_count + 1 + (text_emb_dim if text_emb_dim > 0 else 0)
        return (np.zeros((0, state_dim), dtype=np.float32), np.zeros((0, _EMBEDDING_DIM), dtype=np.float32), np.zeros((0,), dtype=np.int64), np.zeros((0,), dtype=np.int64), np.zeros((0,), dtype=np.float32))
    return (np.vstack(state_rows).astype(np.float32), np.vstack(candidate_rows).astype(np.float32), np.array(legend_rows, dtype=np.int64), np.array(champion_rows, dtype=np.int64), np.array(targets, dtype=np.float32))

def train_generator_moe(
    rows: list[TrainingDeckRow],
    *,
    win_condition_vectors: np.ndarray,
    card_embeddings: dict[str, np.ndarray],
    static_features: dict[str, CardStaticFeatures],
    cluster_by_card: dict[str, int],
    epochs: int,
    total_main_slots: int,
    legend_to_domains: dict[str, tuple[str, ...]] | None = None,
    card_text_embeddings: dict[str, np.ndarray] | None = None,
    text_emb_dim: int = _TEXT_EMB_DIM,
    torch_device: str | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    progress_step: int | None = None,
    progress_total_steps: int | None = None,
) -> dict[str, Any]:
    legends = sorted({row.leader_title for row in rows if row.leader_title})
    champions = sorted({row.chosen_champion_title for row in rows if row.chosen_champion_title})
    legend_to_idx = {title: idx for idx, title in enumerate(legends)}
    champion_to_idx = {title: idx for idx, title in enumerate(champions)}
    cluster_count = max(1, max(cluster_by_card.values(), default=0) + 1)
    win_vector_size = int(win_condition_vectors.shape[1]) if win_condition_vectors.ndim == 2 and win_condition_vectors.shape[1] > 0 else _WIN_VECTOR_SIZE
    resolved_text_emb_dim = max(0, int(text_emb_dim)) if card_text_embeddings else 0
    all_emb_keys = list(card_embeddings.keys())
    legend_to_legal_keys: dict[str, list[str]] | None = None
    if legend_to_domains:
        legend_to_legal_keys = {}
        for title, domains in legend_to_domains.items():
            dom_set = set(domains)
            if not dom_set:
                legend_to_legal_keys[title] = all_emb_keys
            else:
                legal = [k for k in all_emb_keys if not static_features.get(k) or not static_features[k].domains or set(static_features[k].domains).issubset(dom_set)]
                legend_to_legal_keys[title] = legal or all_emb_keys
    states, candidates, legend_idx, champion_idx, targets = _moe_training_samples(rows, win_condition_vectors=win_condition_vectors, card_embeddings=card_embeddings, static_features=static_features, cluster_by_card=cluster_by_card, legend_to_idx=legend_to_idx, champion_to_idx=champion_to_idx, total_main_slots=total_main_slots, legend_to_legal_keys=legend_to_legal_keys, card_text_embeddings=card_text_embeddings, text_emb_dim=resolved_text_emb_dim)
    state_dim = states.shape[1] if states.size else (_EMBEDDING_DIM + 8 + 6 + 3 + 3 + win_vector_size + cluster_count + 1 + resolved_text_emb_dim)
    device = _resolve_torch_device(torch_device)
    _prepare_torch_runtime(device)
    model = _MoECandidateScorer(state_dim=state_dim, candidate_dim=_EMBEDDING_DIM, legend_count=max(1, len(legends)), champion_count=max(1, len(champions))).to(device)
    if states.shape[0] <= 0:
        return {"stateDim": state_dim, "winVectorSize": win_vector_size, "clusterVectorSize": cluster_count, "textEmbDim": resolved_text_emb_dim, "legendToIdx": legend_to_idx, "championToIdx": champion_to_idx, "epochs": 0, "loss": 0.0, "avgLoadBalanceLoss": 0.0, "mainDeckSize": int(total_main_slots), "torchDevice": device.type, "stateDict": {key: value.detach().cpu() for key, value in model.state_dict().items()}}
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    epoch_total = max(1, int(epochs))
    scheduler_moe = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epoch_total, eta_min=1e-5)
    batch_size = 2048 if device.type == "cuda" else 1024 if device.type == "mps" else 512
    order = np.arange(states.shape[0])
    last_loss = 0.0
    lb_loss_sum = 0.0
    lb_loss_count = 0
    epoch_checkpoints = _progress_checkpoints(epoch_total)
    for epoch_idx in range(epoch_total):
        if progress_callback is not None and progress_step is not None and progress_total_steps is not None and (epoch_idx + 1) in epoch_checkpoints:
            _emit_stage_progress(
                progress_callback,
                stage="generator-train",
                step=int(progress_step),
                total_steps=int(progress_total_steps),
                message=f"Training generator epoch {epoch_idx + 1}/{epoch_total}.",
                current=epoch_idx + 1,
                total=epoch_total,
                extra={"epoch": epoch_idx + 1, "epochs": epoch_total, "torchDevice": device.type},
            )
        np.random.shuffle(order)
        for start in range(0, order.size, batch_size):
            idx = order[start : start + batch_size]
            batch_state = torch.from_numpy(states[idx]).to(device=device, dtype=torch.float32)
            batch_candidate = torch.from_numpy(candidates[idx]).to(device=device, dtype=torch.float32)
            batch_legend = torch.from_numpy(legend_idx[idx]).to(device=device, dtype=torch.long)
            batch_champion = torch.from_numpy(champion_idx[idx]).to(device=device, dtype=torch.long)
            batch_target = torch.from_numpy(targets[idx]).to(device=device, dtype=torch.float32)
            logits = model(batch_state, batch_candidate, batch_legend, batch_champion)
            bce_loss = F.binary_cross_entropy_with_logits(logits, batch_target)
            lb_loss = torch.tensor(0.0, device=device)
            if model._last_gate_probs is not None and model._last_top_idx is not None:
                n = _MOE_EXPERTS
                one_hot = torch.zeros(model._last_top_idx.shape[0], n, device=device)
                one_hot.scatter_(1, model._last_top_idx, 1.0)
                f_i = one_hot.mean(dim=0)
                P_i = model._last_gate_probs.mean(dim=0)
                lb_loss = n * (f_i * P_i).sum()
                lb_loss_sum += float(lb_loss.detach().cpu())
                lb_loss_count += 1
            loss = bce_loss + _MOE_LOAD_BALANCE_ALPHA * lb_loss
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            last_loss = float(bce_loss.detach().cpu())
        scheduler_moe.step()
        if progress_callback is not None and progress_step is not None and progress_total_steps is not None and epoch_total > 1 and (epoch_idx + 1) in epoch_checkpoints:
            _emit_stage_progress(
                progress_callback,
                stage="generator-train",
                step=int(progress_step),
                total_steps=int(progress_total_steps),
                message=f"Completed generator epoch {epoch_idx + 1}/{epoch_total}.",
                current=epoch_idx + 1,
                total=epoch_total,
                extra={"epoch": epoch_idx + 1, "epochs": epoch_total, "loss": round(float(last_loss), 6), "torchDevice": device.type},
            )
    avg_lb_loss = lb_loss_sum / max(1, lb_loss_count)
    return {"stateDim": state_dim, "winVectorSize": win_vector_size, "clusterVectorSize": cluster_count, "textEmbDim": resolved_text_emb_dim, "legendToIdx": legend_to_idx, "championToIdx": champion_to_idx, "epochs": max(1, int(epochs)), "loss": last_loss, "avgLoadBalanceLoss": round(avg_lb_loss, 6), "mainDeckSize": int(total_main_slots), "torchDevice": device.type, "stateDict": {key: value.detach().cpu() for key, value in model.state_dict().items()}}


def _win_condition_card_frequency(rows: list[TrainingDeckRow], dominant_components: np.ndarray) -> dict[int, dict[str, float]]:
    numerators: dict[int, Counter[str]] = defaultdict(Counter)
    denominators: Counter[int] = Counter()
    for row_idx, row in enumerate(rows):
        comp = int(dominant_components[row_idx]) if row_idx < dominant_components.shape[0] else 0
        denominators[comp] += 1
        for key, qty in row.main_by_key.items():
            numerators[comp][key] += max(0, int(qty))
    out: dict[int, dict[str, float]] = {}
    for comp, counter in numerators.items():
        denom = float(max(1, denominators[comp] * 3))
        out[comp] = {key: float(value) / denom for key, value in counter.items()}
    return out


def _weighted_jaccard(left: dict[str, int], right: dict[str, int]) -> float:
    keys = set(left.keys()) | set(right.keys())
    if not keys:
        return 0.0
    overlap = 0.0
    union = 0.0
    for key in keys:
        left_qty = max(0, int(left.get(key, 0)))
        right_qty = max(0, int(right.get(key, 0)))
        overlap += float(min(left_qty, right_qty))
        union += float(max(left_qty, right_qty))
    return 0.0 if union <= 0 else overlap / union


def _top_card_titles(keys: list[str], *, cards: CardCatalog, limit: int = 8) -> tuple[str, ...]:
    titles: list[str] = []
    for key in keys[:limit]:
        card = cards.by_key.get(key)
        titles.append(card.title if card is not None else key)
    return tuple(titles[:limit])


def _prototype_buildability_metrics(
    *,
    prototype_main: dict[str, int],
    rows: list[TrainingDeckRow],
    donor_rows: list[TrainingDeckRow],
    cards: CardCatalog,
    synthetic_config: dict[str, Any] | None = None,
    salt: str = "",
) -> tuple[float, float]:
    if not prototype_main or not rows:
        return 0.0, 0.0
    strict_completion_values: list[float] = []
    mixed_completion_values: list[float] = []
    strict_hits = 0
    strict_attempts = 0
    for row in rows:
        row_mixed_scores: list[float] = []
        row_strict_scores: list[float] = []
        for mixed_collection, strict_collection in _synthetic_collection_scenarios(
            row,
            donor_rows=donor_rows,
            cards=cards,
            synthetic_config=synthetic_config,
            salt=salt,
        ):
            strict_completion = _completion_against_collection(prototype_main, strict_collection)
            mixed_completion = _completion_against_collection(prototype_main, mixed_collection)
            row_strict_scores.append(strict_completion)
            row_mixed_scores.append(mixed_completion)
            strict_attempts += 1
            if _is_buildable_from_collection(prototype_main, strict_collection):
                strict_hits += 1
        strict_completion_values.append(float(np.mean(row_strict_scores)) if row_strict_scores else 0.0)
        mixed_completion_values.append(float(np.mean(row_mixed_scores)) if row_mixed_scores else 0.0)
    avg_strict_completion = float(np.mean(strict_completion_values)) if strict_completion_values else 0.0
    avg_mixed_completion = float(np.mean(mixed_completion_values)) if mixed_completion_values else 0.0
    conversion = float(strict_hits) / float(max(1, strict_attempts))
    prior = round(
        max(
            0.0,
            min(
                1.0,
                0.40 * avg_strict_completion
                + 0.30 * avg_mixed_completion
                + 0.30 * conversion,
            ),
        ),
        4,
    )
    return prior, round(conversion, 4)


def _build_shell_and_archetype_profiles(
    *,
    rows: list[TrainingDeckRow],
    cards: CardCatalog,
    dominant_components: np.ndarray,
    win_condition_vectors: np.ndarray,
    competitive_scores: np.ndarray,
    cluster_by_card: dict[str, int],
    win_conditions: list[WinConditionComponent],
    synergy_clusters: list[SynergyCluster],
    synthetic_config: dict[str, Any] | None = None,
) -> tuple[list[ShellProfile], list[ArchetypeProfile], dict[str, list[str]], dict[str, list[dict[str, Any]]], dict[int, str]]:
    shell_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row_idx, row in enumerate(rows):
        shell_id = shell_id_for_titles(
            cards=cards,
            legend_title=row.leader_title,
            chosen_champion_title=row.chosen_champion_title,
        )
        shell_label = shell_label_for_titles(
            legend_title=row.leader_title,
            chosen_champion_title=row.chosen_champion_title,
        )
        synergy_ids = sorted({int(cluster_by_card[key]) for key in row.main_by_key.keys() if key in cluster_by_card})
        shell_members[shell_id].append(
            {
                "row": row,
                "rowIdx": row_idx,
                "shellId": shell_id,
                "shellLabel": shell_label,
                "winConditionId": int(dominant_components[row_idx]) if row_idx < dominant_components.shape[0] else 0,
                "competitiveScore": float(competitive_scores[row_idx]) if row_idx < competitive_scores.shape[0] else float(row.meta_score),
                "synergyIds": synergy_ids,
            }
        )

    shell_profiles: list[ShellProfile] = []
    archetype_profiles: list[ArchetypeProfile] = []
    archetypes_by_shell: dict[str, list[str]] = defaultdict(list)
    seed_examples_by_shell: dict[str, list[dict[str, Any]]] = defaultdict(list)
    row_to_archetype_id: dict[int, str] = {}
    synergy_label_map = {cluster.cluster_id: cluster.label for cluster in synergy_clusters}

    for shell_id, members in shell_members.items():
        if not members:
            continue
        members.sort(
            key=lambda item: (
                -float(item["row"].sample_weight),
                -float(item["competitiveScore"]),
                str(item["row"].deck_name).lower(),
            )
        )
        clusters: list[list[dict[str, Any]]] = []
        for member in members:
            best_idx = -1
            best_score = -1.0
            for idx, cluster in enumerate(clusters):
                reference = cluster[0]["row"].main_by_key
                score = _weighted_jaccard(member["row"].main_by_key, reference)
                if score >= _ARCHETYPE_JACCARD_THRESHOLD and score > best_score:
                    best_idx = idx
                    best_score = score
            if best_idx >= 0:
                clusters[best_idx].append(member)
            else:
                clusters.append([member])

        legend_title = members[0]["row"].leader_title
        champion_title = members[0]["row"].chosen_champion_title
        shell_runes: Counter[str] = Counter()
        shell_battlefields: Counter[str] = Counter()
        shell_sources: Counter[str] = Counter()
        shell_competitive: list[float] = []

        for local_idx, cluster in enumerate(clusters, start=1):
            cluster_rows = [item["row"] for item in cluster]
            cluster_row_indices = [int(item["rowIdx"]) for item in cluster]
            cluster_sources = Counter(str(item["row"].source or "") for item in cluster)
            cluster_size = len(cluster_rows)
            best_seed_rows = sorted(
                cluster,
                key=lambda item: (
                    -float(item["competitiveScore"]),
                    -float(item["row"].meta_score),
                    str(item["row"].deck_name).lower(),
                ),
            )
            best_seed = best_seed_rows[0]
            weighted_presence: Counter[str] = Counter()
            card_weight_totals: Counter[str] = Counter()
            total_weight = 0.0
            rune_weights: Counter[str] = Counter()
            battlefield_weights: Counter[str] = Counter()
            wc_counts: Counter[int] = Counter()
            synergy_counts: Counter[int] = Counter()
            member_competitive: list[float] = []
            similarity_samples: list[float] = []
            for item in cluster:
                row = item["row"]
                weight = max(0.01, float(row.sample_weight))
                total_weight += weight
                wc_counts[int(item["winConditionId"])] += 1
                member_competitive.append(float(item["competitiveScore"]))
                similarity_samples.append(_weighted_jaccard(row.main_by_key, best_seed["row"].main_by_key))
                for key, qty in row.main_by_key.items():
                    if int(qty) <= 0:
                        continue
                    weighted_presence[key] += weight
                    card_weight_totals[key] += weight * float(max(0, int(qty)))
                for title, qty in row.deck.runes.items():
                    if int(qty) > 0:
                        rune_weights[title] += max(0, int(qty))
                        shell_runes[title] += max(0, int(qty))
                for title in row.deck.battlefields:
                    clean = str(title or "").strip()
                    if clean:
                        battlefield_weights[clean] += 1
                        shell_battlefields[clean] += 1
                for synergy_id in item["synergyIds"]:
                    synergy_counts[int(synergy_id)] += 1
                shell_sources[str(row.source or "")] += 1
                shell_competitive.append(float(item["competitiveScore"]))

            dominant_wc = wc_counts.most_common(1)[0][0] if wc_counts else 0
            mean_win_vector = np.zeros((win_condition_vectors.shape[1] if win_condition_vectors.ndim == 2 and win_condition_vectors.shape[1] > 0 else _WIN_VECTOR_SIZE,), dtype=np.float32)
            if cluster_row_indices and win_condition_vectors.ndim == 2 and win_condition_vectors.shape[0] > 0:
                member_vectors = [
                    win_condition_vectors[row_idx].astype(np.float32)
                    for row_idx in cluster_row_indices
                    if 0 <= int(row_idx) < win_condition_vectors.shape[0]
                ]
                if member_vectors:
                    mean_win_vector = np.mean(np.vstack(member_vectors), axis=0).astype(np.float32)
                    total = float(mean_win_vector.sum())
                    if total > 0:
                        mean_win_vector = (mean_win_vector / total).astype(np.float32)
            core_keys = [
                key
                for key, weight in weighted_presence.items()
                if total_weight > 0 and (float(weight) / total_weight) >= 0.65
            ]
            flex_keys = [
                key
                for key, weight in weighted_presence.items()
                if total_weight > 0 and 0.20 <= (float(weight) / total_weight) < 0.65
            ]
            top_synergy_ids = [cluster_id for cluster_id, _count in synergy_counts.most_common(4)]
            archetype_id = f"{shell_id}::{local_idx}"
            archetype_name = f"{champion_title or legend_title or 'Unknown'} Archetype {local_idx}"
            confidence = 0.0
            if similarity_samples:
                confidence = max(0.0, min(1.0, float(sum(similarity_samples)) / float(len(similarity_samples))))
            confidence = round(
                max(0.0, min(1.0, 0.65 * confidence + 0.35 * min(1.0, cluster_size / 6.0))),
                4,
            )
            seeds = tuple(
                PlanSeed(
                    source=str(item["row"].source or ""),
                    deck_id=str(item["row"].deck_id or ""),
                    deck_name=str(item["row"].deck_name or ""),
                    score=round(float(item["competitiveScore"]), 4),
                )
                for item in best_seed_rows[:3]
            )
            buildability_prior, buildable_conversion = _prototype_buildability_metrics(
                prototype_main={key: int(qty) for key, qty in best_seed["row"].main_by_key.items()},
                rows=cluster_rows,
                donor_rows=rows,
                cards=cards,
                synthetic_config=synthetic_config,
                salt=archetype_id,
            )
            archetype_profiles.append(
                ArchetypeProfile(
                    archetype_id=archetype_id,
                    shell_id=shell_id,
                    archetype_name=archetype_name,
                    legend_title=legend_title,
                    chosen_champion_title=champion_title,
                    prototype_main={key: int(qty) for key, qty in best_seed["row"].main_by_key.items()},
                    win_condition_vector=tuple(float(value) for value in mean_win_vector.tolist()),
                    top_core_cards=_top_card_titles(
                        [key for key, _weight in sorted(core_keys and [(key, weighted_presence[key]) for key in core_keys] or [], key=lambda item: (-float(item[1]), item[0]))],
                        cards=cards,
                        limit=8,
                    ),
                    top_flex_cards=_top_card_titles(
                        [key for key, _weight in sorted(flex_keys and [(key, weighted_presence[key]) for key in flex_keys] or [], key=lambda item: (-float(item[1]), item[0]))],
                        cards=cards,
                        limit=8,
                    ),
                    nearest_seed_decks=seeds,
                    rune_weights={key: float(value) for key, value in rune_weights.items()},
                    battlefield_weights={key: float(value) for key, value in battlefield_weights.items()},
                    competitive_prior=round(float(np.mean(member_competitive)) if member_competitive else 0.0, 4),
                    buildability_prior=buildability_prior,
                    buildable_conversion=buildable_conversion,
                    confidence=confidence,
                    source_breakdown={key: int(value) for key, value in cluster_sources.items() if key},
                    win_condition_id=int(dominant_wc),
                    synergy_cluster_ids=tuple(top_synergy_ids),
                    synergy_cluster_labels=tuple(synergy_label_map.get(cluster_id, f"Cluster {cluster_id + 1}") for cluster_id in top_synergy_ids),
                )
            )
            for item in cluster:
                row_to_archetype_id[int(item["rowIdx"])] = archetype_id
            if cluster_size >= _ARCHETYPE_MIN_DECKS:
                archetypes_by_shell[shell_id].append(archetype_id)
            for item in best_seed_rows[:3]:
                seed_examples_by_shell[shell_id].append(
                    {
                        "source": item["row"].source,
                        "deckId": item["row"].deck_id,
                        "deckName": item["row"].deck_name,
                        "leaderTitle": item["row"].leader_title,
                        "chosenChampionTitle": item["row"].chosen_champion_title,
                        "metaScore": item["row"].meta_score,
                    }
                )

        shell_archetype_rows = [profile for profile in archetype_profiles if profile.shell_id == shell_id]
        shell_profiles.append(
            ShellProfile(
                shell_id=shell_id,
                shell_label=members[0]["shellLabel"],
                legend_title=legend_title,
                chosen_champion_title=champion_title,
                legend_domains=legend_domains_for_title(cards=cards, legend_title=legend_title),
                training_deck_count=len(members),
                archetype_count=len(clusters),
                competitive_prior=round(float(np.mean(shell_competitive)) if shell_competitive else 0.0, 4),
                buildability_prior=round(
                    float(
                        np.mean(
                            [
                                profile.buildability_prior
                                for profile in shell_archetype_rows
                            ]
                        )
                    )
                    if shell_archetype_rows
                    else 0.0,
                    4,
                ),
                buildable_conversion=round(
                    float(np.mean([profile.buildable_conversion for profile in shell_archetype_rows])) if shell_archetype_rows else 0.0,
                    4,
                ),
                source_breakdown={key: int(value) for key, value in shell_sources.items() if key},
                rune_weights={key: float(value) for key, value in shell_runes.items()},
                battlefield_weights={key: float(value) for key, value in shell_battlefields.items()},
            )
        )

    shell_profiles.sort(key=lambda item: (-item.competitive_prior, item.shell_label.lower()))
    archetype_profiles.sort(key=lambda item: (-item.competitive_prior, item.archetype_name.lower()))
    for shell_id, rows_list in seed_examples_by_shell.items():
        unique_rows: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows_list:
            key = (str(row.get("source") or "").lower(), str(row.get("deckId") or "").lower())
            unique_rows.setdefault(key, row)
        seed_examples_by_shell[shell_id] = list(unique_rows.values())[:6]
    return shell_profiles, archetype_profiles, dict(archetypes_by_shell), dict(seed_examples_by_shell), row_to_archetype_id


def train_auto_builder_artifacts(
    *,
    cards_path: Path,
    meta_index_path: Path,
    rules_profile_path: Path,
    out_dir: Path,
    epochs: int = 12,
    source_health: dict[str, Any] | None = None,
    torch_device: str | None = None,
    min_win_condition_count: int | None = None,
    min_synergy_cluster_count: int | None = None,
    synthetic_collection_config: dict[str, Any] | None = None,
    resolution_mode: str = _RESOLUTION_MODE_AUTO,
    resolution_reference_artifact_dir: Path | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    total_steps = 11
    _emit_progress(progress_callback, stage="load", step=1, total_steps=total_steps, message="Loading cards, rules, and indexed decks.")
    cards = load_card_catalog(cards_path)
    rules = load_format_rules(rules_profile_path)
    runtime_versions = _runtime_versions()
    resolved_torch_device = _resolve_torch_device(torch_device)
    _prepare_torch_runtime(resolved_torch_device)
    resolved_min_win_conditions = max(1, int(min_win_condition_count or _DEFAULT_MIN_WIN_CONDITION_COUNT))
    resolved_min_synergy_clusters = max(2, int(min_synergy_cluster_count or _DEFAULT_MIN_SYNERGY_CLUSTER_COUNT))
    resolved_synthetic_config = _build_synthetic_collection_config(cards, synthetic_collection_config)
    main_deck_size = _main_deck_target_size(rules)
    meta_repo = MetaDeckRepository(meta_index_path, cards, rules)
    entries = meta_repo.search_entries(query="", limit=None, offset=0)
    rows = build_training_rows(entries, cards=cards)
    train_rows, valid_rows = _train_validation_split(rows)
    vocab, index_to_key = build_main_vocab(train_rows or rows)
    static_features = build_card_static_features(cards, vocab_keys=index_to_key)
    text_features = build_card_text_features(cards, vocab_keys=index_to_key)
    card_text_embeddings: dict[str, np.ndarray] = {}
    if text_features.matrix.shape[0] >= 2 and text_features.matrix.shape[1] > 0:
        n_components = min(_TEXT_EMB_DIM, text_features.matrix.shape[0] - 1, text_features.matrix.shape[1])
        if n_components >= 1:
            svd = TruncatedSVD(n_components=n_components, random_state=42)
            reduced = svd.fit_transform(text_features.matrix)
            for idx, key in enumerate(text_features.keys):
                vec = np.zeros((_TEXT_EMB_DIM,), dtype=np.float32)
                vec[:n_components] = reduced[idx].astype(np.float32)
                card_text_embeddings[key] = vec
    source_health = dict(source_health or {})
    if not rows or not index_to_key:
        metadata = {
            "generatedAt": _utc_now_iso(),
            "trainingDeckCount": 0,
            "validationDeckCount": 0,
            "cardCount": len(index_to_key),
            "winConditionCount": 0,
            "synergyClusterCount": 0,
            "embeddingDim": _EMBEDDING_DIM,
            "negativeSamples": _NEGATIVE_SAMPLES,
            "nmfComponents": 0,
            "spectralClusters": 0,
            "knnNeighbors": 0,
            "epochs": int(max(1, epochs)),
            "bundleVersion": 3,
            "sourceCounts": {},
            "uniqueShellCount": 0,
            "archetypeCount": 0,
            "pythonVersion": runtime_versions["python"],
            "numpyVersion": runtime_versions["numpy"],
            "sklearnVersion": runtime_versions["sklearn"],
            "torchVersion": runtime_versions["torch"],
            "torchDevice": resolved_torch_device.type,
            "minWinConditionCount": resolved_min_win_conditions,
            "minSynergyClusterCount": resolved_min_synergy_clusters,
            "syntheticCollectionConfig": {
                "packMin": int(resolved_synthetic_config["packMin"]),
                "packMax": int(resolved_synthetic_config["packMax"]),
                "scenarioCount": int(resolved_synthetic_config["scenarioCount"]),
                "runeUnlimited": bool(resolved_synthetic_config["runeUnlimited"]),
            },
            "syntheticCollectionSummary": dict(resolved_synthetic_config.get("summary") or {}),
            "defaultMinResults": _DEFAULT_MIN_RESULTS,
            "maxVariantsPerShell": _DEFAULT_MAX_VARIANTS_PER_SHELL,
            "selectedWinConditionCount": 0,
            "selectedSynergyClusterCount": 0,
            "candidateWinConditionCounts": [],
            "candidateSynergyClusterCounts": [],
            "winConditionSelectionMetrics": {},
            "synergySelectionMetrics": {},
            "trainingCorpusFingerprint": "",
            "resolutionSelectionMode": _RESOLUTION_MODE_SEARCH,
            "resolutionReferenceArtifact": "",
            "strictBuildableRecommendationHitRate": 0.0,
            "strictBuildableEmptyResultRate": 0.0,
            "sourceHealth": source_health,
            "artifactVersionHealth": {"runtimeMatches": True},
            "trainingMetrics": {},
        }
        evaluation = {"nextCardTop10Recall": 0.0, "maskedDeckReconstructionExactCardRecall": 0.0, "winConditionClusterSilhouette": 0.0, "competitiveScoreSpearman": 0.0, "collectionFirstRecommendationHitRate": 0.0, "strictBuildableRecommendationHitRate": 0.0, "strictBuildableCandidateCountP50": 0.0, "strictBuildableCandidateCountP90": 0.0, "strictBuildableEmptyResultRate": 0.0, "winConditionSelectionTable": {}, "synergySelectionTable": {}, "sourceCountsByAdapter": {}, "sourceFailuresByAdapter": {}}
        empty_model = _MoECandidateScorer(state_dim=_EMBEDDING_DIM + 8 + 6 + 3 + 3 + _WIN_VECTOR_SIZE + _CLUSTER_VECTOR_SIZE + 1, candidate_dim=_EMBEDDING_DIM, legend_count=1, champion_count=1)
        bundle = {
            "embeddingDim": _EMBEDDING_DIM,
            "vocab": {},
            "indexToKey": [],
            "idf": np.zeros((0,), dtype=np.float32),
            "staticFeatures": {},
            "cardTextKeys": list(text_features.keys),
            "cardTextMatrix": text_features.matrix,
            "cardTextVocab": getattr(text_features.vectorizer, "vocabulary_", {}),
            "winConditionMatrix": np.zeros((0, 0), dtype=np.float32),
            "deckWinConditionVectors": np.zeros((0, 0), dtype=np.float32),
            "deckProfiles": [],
            "clusterByCard": {},
            "deckVectors": np.zeros((0, _EMBEDDING_DIM + _WIN_VECTOR_SIZE + 8 + 6 + 3 + 3), dtype=np.float32),
            "knn": None,
            "competitiveModel": None,
            "surrogateModel": None,
            "replacementModel": None,
            "winConditionCardFrequency": {},
            "embeddingNeighbors": {},
            "runeWeightsByWinCondition": {},
            "battlefieldWeightsByWinCondition": {},
            "runeWeightsByShell": {},
            "battlefieldWeightsByShell": {},
            "runeWeightsByArchetype": {},
            "battlefieldWeightsByArchetype": {},
            "shellProfiles": {},
            "archetypes": [],
            "archetypesByShell": {},
            "shellsByWinCondition": {},
            "shellCoverageByWinCondition": {},
            "archetypeCountByWinCondition": {},
            "examplesByWinCondition": {},
            "seedExamplesByShell": {},
            "artifactVersions": runtime_versions,
            "affinity": np.zeros((0, 0), dtype=np.float32),
        }
        _emit_progress(progress_callback, stage="persist", step=total_steps, total_steps=total_steps, message="Persisting empty model bundle.")
        return _persist_artifacts(
            out_dir=out_dir,
            metadata=metadata,
            bundle=bundle,
            card_embeddings={},
            moe_payload={"stateDim": _EMBEDDING_DIM + 8 + 6 + 3 + 3 + _WIN_VECTOR_SIZE + _CLUSTER_VECTOR_SIZE + 1, "winVectorSize": _WIN_VECTOR_SIZE, "clusterVectorSize": _CLUSTER_VECTOR_SIZE, "legendToIdx": {}, "championToIdx": {}, "mainDeckSize": int(main_deck_size), "stateDict": empty_model.state_dict()},
            win_conditions=[],
            synergy_clusters=[],
            evaluation=evaluation,
            shell_profiles=[],
            archetypes=[],
        )
    sample_weights = np.array([row.sample_weight for row in train_rows], dtype=np.float32) if train_rows else np.zeros((0,), dtype=np.float32)
    _emit_progress(
        progress_callback,
        stage="prepare-corpus",
        step=2,
        total_steps=total_steps,
        message="Prepared canonical training corpus.",
        extra={"trainingDeckCount": len(train_rows), "validationDeckCount": len(valid_rows), "cardCount": len(index_to_key)},
    )
    training_shell_count = len(
        {
            shell_id_for_titles(cards=cards, legend_title=row.leader_title, chosen_champion_title=row.chosen_champion_title)
            for row in train_rows
        }
    )
    training_corpus_fingerprint = _training_corpus_fingerprint(
        train_rows=train_rows,
        valid_rows=valid_rows,
        index_to_key=index_to_key,
        shell_count=training_shell_count,
        main_deck_size=main_deck_size,
    )
    reference_artifact_dir = _resolve_reference_artifact_path(out_dir=out_dir, reference_artifact_dir=resolution_reference_artifact_dir)
    reference_metadata = _load_reference_artifact_metadata(reference_artifact_dir)
    max_win_condition_count = max(1, min(_MAX_WIN_CONDITION_COMPONENTS, max(1, len(index_to_key) - 1), max(1, len(train_rows) - 1)))
    max_synergy_cluster_count = max(2, min(_MAX_SYNERGY_CLUSTERS, max(2, len(index_to_key))))
    resolution_reuse = _resolve_reused_resolution_counts(
        reference_metadata=reference_metadata,
        reference_artifact_dir=reference_artifact_dir,
        training_corpus_fingerprint=training_corpus_fingerprint,
        resolution_mode=resolution_mode,
        resolved_min_win_conditions=resolved_min_win_conditions,
        resolved_min_synergy_clusters=resolved_min_synergy_clusters,
        max_win_condition_count=max_win_condition_count,
        max_synergy_cluster_count=max_synergy_cluster_count,
    )
    resolution_selection_mode = str(resolution_reuse.get("mode") or _RESOLUTION_MODE_SEARCH)
    resolved_reference_artifact = str(resolution_reuse.get("referenceArtifact") or "")
    deck_matrix = build_deck_matrix(train_rows, vocab) if train_rows else np.zeros((0, len(vocab)), dtype=np.float32)
    weighted_matrix, idf = apply_tfidf_dampening(deck_matrix, sample_weights=sample_weights if sample_weights.size else np.ones((deck_matrix.shape[0],), dtype=np.float32))
    _emit_progress(progress_callback, stage="item2vec", step=3, total_steps=total_steps, message="Training neural card embeddings.", extra={"torchDevice": resolved_torch_device.type})
    card_embeddings, embedding_payload = train_item2vec(
        train_rows,
        vocab=vocab,
        index_to_key=index_to_key,
        epochs=epochs,
        torch_device=resolved_torch_device.type,
        progress_callback=progress_callback,
        progress_step=3,
        progress_total_steps=total_steps,
    )
    valid_matrix = build_deck_matrix(valid_rows, vocab) if valid_rows else np.zeros((0, len(vocab)), dtype=np.float32)
    valid_weighted, _ = apply_tfidf_dampening(valid_matrix, sample_weights=np.array([row.sample_weight for row in valid_rows], dtype=np.float32) if valid_rows else np.zeros((0,), dtype=np.float32))
    preferred_win_condition_count = _domain_min_win_condition_count(training_deck_count=len(train_rows), card_vocab_size=len(index_to_key), shell_count=training_shell_count, min_count=resolved_min_win_conditions)
    if resolution_selection_mode == _RESOLUTION_MODE_REUSE:
        selected_win_condition_count = int(resolution_reuse["selectedWinConditionCount"])
        nmf_candidate_counts = [selected_win_condition_count]
        nmf_selection_metrics = _selected_metric_subset(
            reference_metadata.get("winConditionSelectionMetrics"),
            selected_count=selected_win_condition_count,
        )
        _emit_progress(
            progress_callback,
            stage="win-condition-selection",
            step=4,
            total_steps=total_steps,
            message="Reusing win condition resolution from reference artifact.",
            extra={
                "candidateCounts": list(nmf_candidate_counts),
                "selectedWinConditionCount": selected_win_condition_count,
                "referenceArtifact": resolved_reference_artifact,
            },
        )
    else:
        nmf_candidate_counts = _trim_candidate_counts(
            _candidate_nmf_component_counts(training_deck_count=len(train_rows), card_vocab_size=len(index_to_key), shell_count=training_shell_count, min_count=resolved_min_win_conditions),
            anchor=preferred_win_condition_count,
        )
        _emit_progress(progress_callback, stage="win-condition-selection", step=4, total_steps=total_steps, message="Evaluating win condition resolutions.", extra={"candidateCounts": list(nmf_candidate_counts)})
        nmf_selection_metrics = {}
        for candidate_idx, candidate in enumerate(nmf_candidate_counts, start=1):
            _emit_stage_progress(
                progress_callback,
                stage="win-condition-selection",
                step=4,
                total_steps=total_steps,
                message=f"Evaluating win condition candidate {candidate_idx}/{len(nmf_candidate_counts)} ({int(candidate)} components).",
                current=candidate_idx,
                total=len(nmf_candidate_counts),
                extra={"currentCandidate": int(candidate)},
            )
            nmf_selection_metrics[int(candidate)] = _evaluate_nmf_candidate(
                candidate=int(candidate),
                train_rows=train_rows,
                valid_rows=valid_rows,
                deck_matrix_weighted=weighted_matrix,
                valid_weighted=valid_weighted,
                index_to_key=index_to_key,
                cards=cards,
                synthetic_config=resolved_synthetic_config,
            )
        selected_win_condition_count = _select_nmf_components_from_metrics(
            training_deck_count=len(train_rows),
            card_vocab_size=len(index_to_key),
            shell_count=training_shell_count,
            min_count=resolved_min_win_conditions,
            candidate_metrics=nmf_selection_metrics,
        )
    _emit_progress(progress_callback, stage="win-condition-train", step=5, total_steps=total_steps, message="Training final win condition model.", extra={"selectedWinConditionCount": selected_win_condition_count})
    nmf_model, W_train, H, win_conditions = train_win_conditions(
        train_rows,
        deck_matrix_weighted=weighted_matrix,
        index_to_key=index_to_key,
        cards=cards,
        component_count=selected_win_condition_count,
    )
    dominant_train = np.argmax(W_train, axis=1) if W_train.size else np.zeros((len(train_rows),), dtype=np.int64)
    preferred_synergy_cluster_count = _domain_min_synergy_cluster_count(training_deck_count=len(train_rows), card_vocab_size=len(index_to_key), shell_count=training_shell_count, win_condition_count=selected_win_condition_count, min_count=resolved_min_synergy_clusters)
    synergy_affinity = _build_synergy_affinity(train_rows, index_to_key=index_to_key, card_embeddings=card_embeddings)
    if resolution_selection_mode == _RESOLUTION_MODE_REUSE:
        selected_synergy_cluster_count = int(resolution_reuse["selectedSynergyClusterCount"])
        synergy_candidate_counts = [selected_synergy_cluster_count]
        synergy_selection_metrics = _selected_metric_subset(
            reference_metadata.get("synergySelectionMetrics"),
            selected_count=selected_synergy_cluster_count,
        )
        _emit_progress(
            progress_callback,
            stage="synergy-selection",
            step=6,
            total_steps=total_steps,
            message="Reusing synergy cluster resolution from reference artifact.",
            extra={
                "candidateCounts": list(synergy_candidate_counts),
                "selectedSynergyClusterCount": selected_synergy_cluster_count,
                "referenceArtifact": resolved_reference_artifact,
            },
        )
    else:
        synergy_candidate_counts = _trim_candidate_counts(
            _candidate_synergy_cluster_counts(training_deck_count=len(train_rows), card_vocab_size=len(index_to_key), shell_count=training_shell_count, win_condition_count=selected_win_condition_count, min_count=resolved_min_synergy_clusters),
            anchor=preferred_synergy_cluster_count,
        )
        _emit_progress(progress_callback, stage="synergy-selection", step=6, total_steps=total_steps, message="Evaluating synergy cluster resolutions.", extra={"candidateCounts": list(synergy_candidate_counts)})
        synergy_selection_metrics = {}
        for candidate_idx, candidate in enumerate(synergy_candidate_counts, start=1):
            _emit_stage_progress(
                progress_callback,
                stage="synergy-selection",
                step=6,
                total_steps=total_steps,
                message=f"Evaluating synergy cluster candidate {candidate_idx}/{len(synergy_candidate_counts)} ({int(candidate)} clusters).",
                current=candidate_idx,
                total=len(synergy_candidate_counts),
                extra={"currentCandidate": int(candidate)},
            )
            _labels, metrics = _evaluate_synergy_candidate(
                candidate=int(candidate),
                rows=train_rows,
                valid_rows=valid_rows,
                index_to_key=index_to_key,
                card_embeddings=card_embeddings,
                cards=cards,
                static_features=static_features,
                affinity=synergy_affinity,
                synthetic_config=resolved_synthetic_config,
            )
            synergy_selection_metrics[int(candidate)] = metrics
        selected_synergy_cluster_count = _select_synergy_cluster_count_from_metrics(
            training_deck_count=len(train_rows),
            card_vocab_size=len(index_to_key),
            shell_count=training_shell_count,
            win_condition_count=selected_win_condition_count,
            min_count=resolved_min_synergy_clusters,
            candidate_metrics=synergy_selection_metrics,
        )
    _emit_progress(progress_callback, stage="synergy-train", step=7, total_steps=total_steps, message="Training final synergy graph.", extra={"selectedSynergyClusterCount": selected_synergy_cluster_count})
    cluster_labels, synergy_clusters, affinity = train_synergy_clusters(
        train_rows,
        index_to_key=index_to_key,
        card_embeddings=card_embeddings,
        cards=cards,
        cluster_count=selected_synergy_cluster_count,
        affinity=synergy_affinity,
    )
    cluster_by_card = {index_to_key[idx]: int(cluster_labels[idx]) for idx in range(len(index_to_key))}
    embedding_neighbors = _build_embedding_neighbors(card_embeddings, index_to_key=index_to_key)
    deck_vectors_train = _deck_vectors(train_rows, card_embeddings=card_embeddings, embedding_dim=_EMBEDDING_DIM, win_condition_vectors=W_train, static_features=static_features)
    knn = NearestNeighbors(metric="cosine", n_neighbors=max(1, min(_KNN_NEIGHBORS, max(1, len(train_rows)))))
    if len(train_rows) > 0:
        knn.fit(deck_vectors_train)
    tree_model = HistGradientBoostingRegressor(random_state=13, max_depth=5)
    surrogate = DecisionTreeRegressor(random_state=13, max_depth=5)
    y_train = np.array([max(0.0, min(40.0, float(row.meta_score))) for row in train_rows], dtype=np.float32)
    if len(train_rows) > 1:
        tree_model.fit(deck_vectors_train, y_train, sample_weight=sample_weights)
        pred_train = tree_model.predict(deck_vectors_train)
        surrogate.fit(deck_vectors_train, pred_train, sample_weight=sample_weights)
    else:
        tree_model = None
        surrogate = None
        pred_train = y_train.copy()
    wc_card_freq = _win_condition_card_frequency(train_rows, dominant_train)
    replacement_x, replacement_y = _replacement_training_examples(train_rows, static_features=static_features, card_embeddings=card_embeddings, dominant_components=dominant_train, cluster_by_card=cluster_by_card, wc_card_freq=wc_card_freq)
    replacement_model = HistGradientBoostingRegressor(random_state=13, max_depth=4)
    if replacement_x.shape[0] > 8:
        replacement_model.fit(replacement_x, replacement_y)
    else:
        replacement_model = None
    _emit_progress(progress_callback, stage="generator-train", step=8, total_steps=total_steps, message="Training generator and replacement models.", extra={"replacementSamples": int(replacement_x.shape[0])})
    legend_to_domains = {
        row.leader_title: legend_domains_for_title(cards=cards, legend_title=row.leader_title)
        for row in train_rows
        if row.leader_title
    }
    moe_payload = train_generator_moe(
        train_rows,
        win_condition_vectors=W_train,
        card_embeddings=card_embeddings,
        static_features=static_features,
        cluster_by_card=cluster_by_card,
        epochs=epochs,
        total_main_slots=main_deck_size,
        legend_to_domains=legend_to_domains,
        card_text_embeddings=card_text_embeddings,
        torch_device=resolved_torch_device.type,
        progress_callback=progress_callback,
        progress_step=8,
        progress_total_steps=total_steps,
    )

    component_rune_weights: dict[int, Counter[str]] = defaultdict(Counter)
    component_battlefield_weights: dict[int, Counter[str]] = defaultdict(Counter)
    component_shells: dict[int, Counter[tuple[str, str]]] = defaultdict(Counter)
    component_meta_rows: dict[int, list[tuple[float, TrainingDeckRow]]] = defaultdict(list)
    source_counts = Counter(str(row.source or "") for row in train_rows)
    (
        shell_profiles,
        archetype_profiles,
        archetypes_by_shell,
        seed_examples_by_shell,
        row_to_archetype_id,
    ) = _build_shell_and_archetype_profiles(
        rows=train_rows,
        cards=cards,
        dominant_components=dominant_train,
        win_condition_vectors=W_train,
        competitive_scores=pred_train.astype(np.float32) if hasattr(pred_train, "astype") else np.array(pred_train, dtype=np.float32),
        cluster_by_card=cluster_by_card,
        win_conditions=win_conditions,
        synergy_clusters=synergy_clusters,
        synthetic_config=resolved_synthetic_config,
    )
    _emit_progress(progress_callback, stage="profiles", step=9, total_steps=total_steps, message="Building shell and archetype profiles.", extra={"shellCount": len(shell_profiles), "archetypeCount": len(archetype_profiles)})
    shell_profile_by_id = {profile.shell_id: profile for profile in shell_profiles}
    archetype_profile_by_id = {profile.archetype_id: profile for profile in archetype_profiles}
    deck_profiles: list[dict[str, Any]] = []
    for row_idx, row in enumerate(train_rows):
        dominant = int(dominant_train[row_idx]) if row_idx < dominant_train.shape[0] else 0
        wc_vec = W_train[row_idx].astype(np.float32) if row_idx < W_train.shape[0] else np.zeros((W_train.shape[1] if W_train.ndim == 2 and W_train.shape[1] > 0 else _WIN_VECTOR_SIZE,), dtype=np.float32)
        confidence = component_confidence(wc_vec)
        synergy_ids = sorted({cluster_by_card[key] for key in row.main_by_key.keys() if key in cluster_by_card})
        synergy_labels = [summary.label for summary in synergy_clusters if summary.cluster_id in synergy_ids][:4]
        shell_id = shell_id_for_titles(
            cards=cards,
            legend_title=row.leader_title,
            chosen_champion_title=row.chosen_champion_title,
        )
        shell_label = shell_label_for_titles(
            legend_title=row.leader_title,
            chosen_champion_title=row.chosen_champion_title,
        )
        archetype_id = row_to_archetype_id.get(row_idx, "")
        archetype = archetype_profile_by_id.get(archetype_id)
        deck_profiles.append(
            {
                "source": row.source,
                "deckId": row.deck_id,
                "deckName": row.deck_name,
                "leaderTitle": row.leader_title,
                "chosenChampionTitle": row.chosen_champion_title,
                "mainByKey": {key: int(qty) for key, qty in row.main_by_key.items()},
                "winConditionId": dominant,
                "winConditionLabel": win_conditions[dominant].label if dominant < len(win_conditions) else f"WC{dominant + 1:02d}",
                "winConditionConfidence": round(confidence, 4),
                "synergyClusterIds": synergy_ids[:4],
                "synergyClusterLabels": synergy_labels,
                "competitiveScore": round(float(pred_train[row_idx]) if row_idx < len(pred_train) else float(row.meta_score), 4),
                "metaScore": round(float(row.meta_score), 4),
                "sampleWeight": float(row.sample_weight),
                "deckSignature": row.deck_signature,
                "runes": {title: int(qty) for title, qty in row.deck.runes.items()},
                "battlefields": list(row.deck.battlefields),
                "shellId": shell_id,
                "shellLabel": shell_label,
                "archetypeId": archetype_id,
                "archetypeName": archetype.archetype_name if archetype is not None else "",
                "archetypeConfidence": float(archetype.confidence) if archetype is not None else 0.0,
                "sourceBreakdown": dict(archetype.source_breakdown) if archetype is not None else {},
            }
        )
        for title, qty in row.deck.runes.items():
            component_rune_weights[dominant][title] += max(0, int(qty))
        for title in row.deck.battlefields:
            clean = str(title or "").strip()
            if clean:
                component_battlefield_weights[dominant][clean] += 1
        component_shells[dominant][(row.leader_title, row.chosen_champion_title)] += 1
        component_meta_rows[dominant].append((float(row.meta_score), row))
    shell_payload: dict[int, list[dict[str, Any]]] = {}
    example_payloads: dict[int, list[dict[str, Any]]] = {}
    for comp, counter in component_shells.items():
        shell_payload[comp] = []
        for (legend, champion), weight in counter.most_common(12):
            shell_id = shell_id_for_titles(cards=cards, legend_title=legend, chosen_champion_title=champion)
            shell_profile = shell_profile_by_id.get(shell_id)
            shell_payload[comp].append(
                {
                    "shellId": shell_id,
                    "shellLabel": shell_profile.shell_label if shell_profile is not None else shell_label_for_titles(legend_title=legend, chosen_champion_title=champion),
                    "legendTitle": legend,
                    "chosenChampionTitle": champion,
                    "legendDomains": list(shell_profile.legend_domains) if shell_profile is not None else [],
                    "weight": float(weight),
                    "competitivePrior": float(shell_profile.competitive_prior) if shell_profile is not None else 0.0,
                    "buildabilityPrior": float(shell_profile.buildability_prior) if shell_profile is not None else 0.0,
                    "buildableConversion": float(shell_profile.buildable_conversion) if shell_profile is not None else 0.0,
                }
            )
    for comp, values in component_meta_rows.items():
        values.sort(key=lambda item: (-item[0], item[1].deck_name.lower()))
        example_payloads[comp] = [{"source": row.source, "deckId": row.deck_id, "deckName": row.deck_name, "leaderTitle": row.leader_title, "chosenChampionTitle": row.chosen_champion_title, "metaScore": row.meta_score} for _score, row in values[:3]]

    win_condition_shell_coverage = {
        int(comp): len({item.get("shellId") for item in rows if item.get("shellId")})
        for comp, rows in shell_payload.items()
    }
    win_condition_archetype_count = {
        int(component.component_id): sum(1 for archetype in archetype_profiles if int(archetype.win_condition_id) == int(component.component_id))
        for component in win_conditions
    }
    win_conditions = [
        WinConditionComponent(
            component_id=int(component.component_id),
            label=component.label,
            top_cards=component.top_cards,
            top_effect_tokens=component.top_effect_tokens,
            sample_deck_count=int(component.sample_deck_count),
            avg_competitive_score=float(component.avg_competitive_score),
            shell_coverage_count=int(win_condition_shell_coverage.get(int(component.component_id), 0)),
            archetype_count=int(win_condition_archetype_count.get(int(component.component_id), 0)),
        )
        for component in win_conditions
    ]

    bundle = {
        "embeddingDim": _EMBEDDING_DIM,
        "vocab": vocab,
        "indexToKey": index_to_key,
        "idf": idf,
        "staticFeatures": {key: {"title": feat.title, "cardType": feat.card_type, "superType": feat.super_type, "domains": list(feat.domains), "cost": feat.cost, "might": feat.might, "isUnique": feat.is_unique, "tags": list(feat.tags), "effectTokens": list(feat.effect_tokens)} for key, feat in static_features.items()},
        "cardTextKeys": list(text_features.keys),
        "cardTextMatrix": text_features.matrix,
        "cardTextVocab": getattr(text_features.vectorizer, "vocabulary_", {}),
        "winConditionMatrix": H,
        "deckWinConditionVectors": W_train,
        "deckProfiles": deck_profiles,
        "clusterByCard": cluster_by_card,
        "deckVectors": deck_vectors_train,
        "knn": knn,
        "competitiveModel": tree_model,
        "surrogateModel": surrogate,
        "replacementModel": replacement_model,
        "winConditionCardFrequency": wc_card_freq,
        "embeddingNeighbors": embedding_neighbors,
        "runeWeightsByWinCondition": {comp: {key: float(value) for key, value in counter.items()} for comp, counter in component_rune_weights.items()},
        "battlefieldWeightsByWinCondition": {comp: {key: float(value) for key, value in counter.items()} for comp, counter in component_battlefield_weights.items()},
        "runeWeightsByShell": {profile.shell_id: {key: float(value) for key, value in profile.rune_weights.items()} for profile in shell_profiles},
        "battlefieldWeightsByShell": {profile.shell_id: {key: float(value) for key, value in profile.battlefield_weights.items()} for profile in shell_profiles},
        "runeWeightsByArchetype": {profile.archetype_id: {key: float(value) for key, value in profile.rune_weights.items()} for profile in archetype_profiles},
        "battlefieldWeightsByArchetype": {profile.archetype_id: {key: float(value) for key, value in profile.battlefield_weights.items()} for profile in archetype_profiles},
        "shellProfiles": {
            profile.shell_id: {
                "shellId": profile.shell_id,
                "shellLabel": profile.shell_label,
                "legendTitle": profile.legend_title,
                "chosenChampionTitle": profile.chosen_champion_title,
                "legendDomains": list(profile.legend_domains),
                "trainingDeckCount": int(profile.training_deck_count),
                "archetypeCount": int(profile.archetype_count),
                "competitivePrior": float(profile.competitive_prior),
                "buildabilityPrior": float(profile.buildability_prior),
                "buildableConversion": float(profile.buildable_conversion),
                "sourceBreakdown": dict(profile.source_breakdown),
            }
            for profile in shell_profiles
        },
        "archetypes": [
            {
                "archetypeId": profile.archetype_id,
                "shellId": profile.shell_id,
                "archetypeName": profile.archetype_name,
                "legendTitle": profile.legend_title,
                "chosenChampionTitle": profile.chosen_champion_title,
                "prototypeMain": {key: int(value) for key, value in profile.prototype_main.items()},
                "winConditionVector": list(profile.win_condition_vector),
                "topCoreCards": list(profile.top_core_cards),
                "topFlexCards": list(profile.top_flex_cards),
                "nearestSeedDecks": [asdict(seed) for seed in profile.nearest_seed_decks],
                "competitivePrior": float(profile.competitive_prior),
                "buildabilityPrior": float(profile.buildability_prior),
                "buildableConversion": float(profile.buildable_conversion),
                "confidence": float(profile.confidence),
                "sourceBreakdown": dict(profile.source_breakdown),
                "winConditionId": int(profile.win_condition_id),
                "synergyClusterIds": list(profile.synergy_cluster_ids),
                "synergyClusterLabels": list(profile.synergy_cluster_labels),
                "trainingDeckCount": int(sum(profile.source_breakdown.values())),
            }
            for profile in archetype_profiles
        ],
        "archetypesByShell": archetypes_by_shell,
        "shellsByWinCondition": shell_payload,
        "shellCoverageByWinCondition": win_condition_shell_coverage,
        "archetypeCountByWinCondition": win_condition_archetype_count,
        "examplesByWinCondition": example_payloads,
        "seedExamplesByShell": seed_examples_by_shell,
        "artifactVersions": runtime_versions,
        "affinity": affinity,
    }

    selected_nmf_metrics = dict(nmf_selection_metrics.get(int(selected_win_condition_count)) or {})
    selected_synergy_metrics = dict(synergy_selection_metrics.get(int(selected_synergy_cluster_count)) or {})
    W_valid = nmf_model.transform(np.maximum(valid_weighted, 0.0)) if valid_rows else np.zeros((0, W_train.shape[1] if W_train.ndim == 2 else _WIN_VECTOR_SIZE), dtype=np.float32)
    valid_vectors = _deck_vectors(valid_rows, card_embeddings=card_embeddings, embedding_dim=_EMBEDDING_DIM, win_condition_vectors=W_valid.astype(np.float32), static_features=static_features) if valid_rows else np.zeros((0, deck_vectors_train.shape[1] if deck_vectors_train.size else _EMBEDDING_DIM + _WIN_VECTOR_SIZE + 8 + 6 + 3 + 3), dtype=np.float32)
    if valid_rows and len(train_rows) > 1:
        comp_pred = tree_model.predict(valid_vectors)
        comp_true = [float(row.meta_score) for row in valid_rows]
        comp_corr = pearson_rank_correlation(list(comp_pred), comp_true)
    else:
        comp_corr = 0.0
    try:
        dominant_all = dominant_train.tolist()
        silhouette = float(silhouette_score(W_train, dominant_all)) if len(set(dominant_all)) > 1 and W_train.shape[0] > len(set(dominant_all)) else 0.0
    except Exception:
        silhouette = 0.0

    moe_eval_device = resolved_torch_device
    moe_model = _MoECandidateScorer(state_dim=moe_payload["stateDim"], candidate_dim=_EMBEDDING_DIM, legend_count=max(1, len(moe_payload.get("legendToIdx", {}))), champion_count=max(1, len(moe_payload.get("championToIdx", {})))).to(moe_eval_device)
    moe_model.load_state_dict(moe_payload["stateDict"])
    moe_model.eval()

    _emit_progress(
        progress_callback,
        stage="evaluate",
        step=10,
        total_steps=total_steps,
        message="Evaluating held-out recommendation quality.",
        extra={"validationDeckCount": len(valid_rows)},
    )
    next_card_recall = 0.0
    reconstruction_recall = 0.0
    collection_hit_rate = 0.0
    if valid_rows:
        hits_top10 = 0
        hits_top1 = 0
        collection_hits = 0
        attempts = 0
        cluster_count = max(1, max(cluster_by_card.values(), default=0) + 1)
        legend_to_idx = moe_payload.get("legendToIdx", {})
        champion_to_idx = moe_payload.get("championToIdx", {})
        all_candidate_keys = list(card_embeddings.keys())
        candidate_stack = np.vstack([card_embeddings[key] for key in all_candidate_keys]).astype(np.float32) if all_candidate_keys else np.zeros((0, _EMBEDDING_DIM), dtype=np.float32)
        for row_idx, row in enumerate(valid_rows[: min(64, len(valid_rows))]):
            if not row.main_by_key or not all_candidate_keys:
                continue
            target_key = next(iter(row.main_by_key.keys()))
            partial = dict(row.main_by_key)
            partial[target_key] = max(0, partial[target_key] - 1)
            if partial[target_key] <= 0:
                del partial[target_key]
            wc_vec = W_valid[row_idx].astype(np.float32) if row_idx < W_valid.shape[0] else np.zeros((W_valid.shape[1] if W_valid.ndim == 2 and W_valid.shape[1] > 0 else _WIN_VECTOR_SIZE,), dtype=np.float32)
            state_vec = _state_feature_vector(partial, card_embeddings=card_embeddings, static_features=static_features, win_condition_vector=wc_vec, cluster_by_card=cluster_by_card, cluster_count=cluster_count, remaining_slots=main_deck_size - sum(partial.values()), total_main_slots=main_deck_size, win_vector_size=wc_vec.shape[0], cluster_vector_size=cluster_count, card_text_embeddings=card_text_embeddings if card_text_embeddings else None, text_emb_dim=int(moe_payload.get("textEmbDim") or 0))
            state_tensor = torch.from_numpy(np.repeat(state_vec.reshape((1, -1)), len(all_candidate_keys), axis=0)).to(device=moe_eval_device, dtype=torch.float32)
            candidate_tensor = torch.from_numpy(candidate_stack).to(device=moe_eval_device, dtype=torch.float32)
            legend_tensor = torch.from_numpy(np.array([legend_to_idx.get(row.leader_title, 0)] * len(all_candidate_keys), dtype=np.int64)).to(device=moe_eval_device, dtype=torch.long)
            champion_tensor = torch.from_numpy(np.array([champion_to_idx.get(row.chosen_champion_title, 0)] * len(all_candidate_keys), dtype=np.int64)).to(device=moe_eval_device, dtype=torch.long)
            with torch.inference_mode():
                logits = moe_model(state_tensor, candidate_tensor, legend_tensor, champion_tensor).detach().cpu().numpy()
            ranked = [all_candidate_keys[idx] for idx in np.argsort(logits)[::-1][:10]]
            if target_key in ranked:
                hits_top10 += 1
            if ranked and ranked[0] == target_key:
                hits_top1 += 1
            attempts += 1
            owned_scores: list[float] = []
            for collection_owned, _strict_collection in _synthetic_collection_scenarios(
                row,
                donor_rows=train_rows,
                cards=cards,
                salt="heldout-collection",
                synthetic_config=resolved_synthetic_config,
            ):
                owned_score = 0.0
                for other in deck_profiles[:50]:
                    missing = 0
                    total = 0
                    for key, qty in other["mainByKey"].items():
                        total += int(qty)
                        missing += max(0, int(qty) - int(collection_owned.get(key, 0)))
                    completion = 1.0 - (missing / float(max(1, total)))
                    score = 0.65 * completion + 0.35 * (float(other["competitiveScore"]) / 40.0)
                    if other["deckId"] == row.deck_id and other["source"] == row.source:
                        owned_score = max(owned_score, score)
                owned_scores.append(owned_score)
            owned_score = float(np.mean(owned_scores)) if owned_scores else 0.0
            if owned_score > 0.65:
                collection_hits += 1
        next_card_recall = hits_top10 / float(max(1, attempts))
        reconstruction_recall = hits_top1 / float(max(1, attempts))
        collection_hit_rate = collection_hits / float(max(1, attempts))

    evaluation = {
        "nextCardTop10Recall": round(float(next_card_recall), 4),
        "maskedDeckReconstructionExactCardRecall": round(float(reconstruction_recall), 4),
        "winConditionClusterSilhouette": round(float(silhouette), 4),
        "competitiveScoreSpearman": round(float(comp_corr), 4),
        "moeLoadBalanceLoss": round(float(moe_payload.get("avgLoadBalanceLoss") or 0.0), 6),
        "collectionFirstRecommendationHitRate": round(max(float(collection_hit_rate), float(selected_nmf_metrics.get("recommendationHitRate") or 0.0)), 4),
        "strictBuildableRecommendationHitRate": round(float(selected_nmf_metrics.get("strictBuildableHitRate") or 0.0), 4),
        "strictBuildableCandidateCountP50": round(float(selected_nmf_metrics.get("strictBuildableCandidateCountP50") or 0.0), 4),
        "strictBuildableCandidateCountP90": round(float(selected_nmf_metrics.get("strictBuildableCandidateCountP90") or 0.0), 4),
        "strictBuildableEmptyResultRate": round(float(selected_nmf_metrics.get("strictBuildableEmptyResultRate") or 0.0), 4),
        "winConditionSelectionTable": {str(key): value for key, value in nmf_selection_metrics.items()},
        "synergySelectionTable": {str(key): value for key, value in synergy_selection_metrics.items()},
        "sourceCountsByAdapter": {key: int(value) for key, value in source_counts.items() if key},
        "sourceFailuresByAdapter": {
            key: int(value.get("failures", 0))
            for key, value in source_health.items()
            if isinstance(value, dict)
        },
    }
    metadata = {
        "generatedAt": _utc_now_iso(),
        "trainingDeckCount": len(train_rows),
        "validationDeckCount": len(valid_rows),
        "cardCount": len(index_to_key),
        "winConditionCount": len(win_conditions),
        "synergyClusterCount": len(synergy_clusters),
        "embeddingDim": _EMBEDDING_DIM,
        "negativeSamples": _NEGATIVE_SAMPLES,
        "nmfComponents": len(win_conditions),
        "spectralClusters": len(synergy_clusters),
        "knnNeighbors": max(1, min(_KNN_NEIGHBORS, max(1, len(train_rows)))),
        "epochs": int(max(1, epochs)),
        "bundleVersion": 3,
        "sourceCounts": {key: int(value) for key, value in source_counts.items() if key},
        "uniqueShellCount": len(shell_profiles),
        "archetypeCount": len(archetype_profiles),
        "pythonVersion": runtime_versions["python"],
        "numpyVersion": runtime_versions["numpy"],
        "sklearnVersion": runtime_versions["sklearn"],
        "torchVersion": runtime_versions["torch"],
        "torchDevice": resolved_torch_device.type,
        "minWinConditionCount": resolved_min_win_conditions,
        "minSynergyClusterCount": resolved_min_synergy_clusters,
        "syntheticCollectionConfig": {
            "packMin": int(resolved_synthetic_config["packMin"]),
            "packMax": int(resolved_synthetic_config["packMax"]),
            "scenarioCount": int(resolved_synthetic_config["scenarioCount"]),
            "runeUnlimited": bool(resolved_synthetic_config["runeUnlimited"]),
        },
        "syntheticCollectionSummary": dict(resolved_synthetic_config.get("summary") or {}),
        "defaultMinResults": _DEFAULT_MIN_RESULTS,
        "maxVariantsPerShell": _DEFAULT_MAX_VARIANTS_PER_SHELL,
        "selectedWinConditionCount": int(selected_win_condition_count),
        "selectedSynergyClusterCount": int(selected_synergy_cluster_count),
        "candidateWinConditionCounts": [int(value) for value in nmf_candidate_counts],
        "candidateSynergyClusterCounts": [int(value) for value in synergy_candidate_counts],
        "winConditionSelectionMetrics": {str(key): value for key, value in nmf_selection_metrics.items()},
        "synergySelectionMetrics": {str(key): value for key, value in synergy_selection_metrics.items()},
        "trainingCorpusFingerprint": training_corpus_fingerprint,
        "resolutionSelectionMode": resolution_selection_mode,
        "resolutionReferenceArtifact": resolved_reference_artifact,
        "strictBuildableRecommendationHitRate": float(selected_nmf_metrics.get("strictBuildableHitRate") or 0.0),
        "strictBuildableEmptyResultRate": float(selected_nmf_metrics.get("strictBuildableEmptyResultRate") or 0.0),
        "generatorWinVectorSize": int(moe_payload.get("winVectorSize") or _WIN_VECTOR_SIZE),
        "generatorClusterVectorSize": int(moe_payload.get("clusterVectorSize") or _CLUSTER_VECTOR_SIZE),
        "embeddingNeighborCount": _EMBEDDING_NEIGHBOR_COUNT,
        "sourceHealth": source_health,
        "artifactVersionHealth": {"runtimeMatches": True},
        "trainingMetrics": evaluation,
    }

    _emit_progress(
        progress_callback,
        stage="persist",
        step=total_steps,
        total_steps=total_steps,
        message="Persisting trained model artifacts.",
        extra={"outDir": str(out_dir)},
    )
    return _persist_artifacts(
        out_dir=out_dir,
        metadata=metadata,
        bundle=bundle,
        card_embeddings=card_embeddings,
        card_text_embeddings=card_text_embeddings,
        moe_payload=moe_payload,
        win_conditions=win_conditions,
        synergy_clusters=synergy_clusters,
        evaluation=evaluation,
        shell_profiles=shell_profiles,
        archetypes=archetype_profiles,
    )


def _persist_artifacts(
    *,
    out_dir: Path,
    metadata: dict[str, Any],
    bundle: dict[str, Any],
    card_embeddings: dict[str, np.ndarray],
    card_text_embeddings: dict[str, np.ndarray] | None = None,
    moe_payload: dict[str, Any],
    win_conditions: list[WinConditionComponent],
    synergy_clusters: list[SynergyCluster],
    evaluation: dict[str, Any],
    shell_profiles: list[ShellProfile],
    archetypes: list[ArchetypeProfile],
) -> dict[str, Any]:
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f"{out_dir.name}-tmp-", dir=str(out_dir.parent)))
    try:
        (temp_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        with (temp_dir / "sklearn_bundle.joblib").open("wb") as fh:
            pickle.dump(bundle, fh)
        emb_payload: dict[str, Any] = {"embeddingDim": _EMBEDDING_DIM, "vectors": {key: vec.tolist() for key, vec in card_embeddings.items()}}
        if card_text_embeddings:
            emb_payload["textVectors"] = {key: vec.tolist() for key, vec in card_text_embeddings.items()}
        torch.save(emb_payload, temp_dir / "card_embeddings.pt")
        torch.save({"stateDim": moe_payload["stateDim"], "winVectorSize": moe_payload.get("winVectorSize", _WIN_VECTOR_SIZE), "clusterVectorSize": moe_payload.get("clusterVectorSize", _CLUSTER_VECTOR_SIZE), "textEmbDim": moe_payload.get("textEmbDim", 0), "legendToIdx": moe_payload.get("legendToIdx", {}), "championToIdx": moe_payload.get("championToIdx", {}), "mainDeckSize": moe_payload.get("mainDeckSize", 40), "trainingTorchDevice": moe_payload.get("torchDevice", ""), "stateDict": moe_payload["stateDict"]}, temp_dir / "generator_moe.pt")
        (temp_dir / "win_condition_components.json").write_text(json.dumps([asdict(item) for item in win_conditions], indent=2), encoding="utf-8")
        (temp_dir / "synergy_clusters.json").write_text(json.dumps([asdict(item) for item in synergy_clusters], indent=2), encoding="utf-8")
        (temp_dir / "shell_profiles.json").write_text(json.dumps([asdict(item) for item in shell_profiles], indent=2), encoding="utf-8")
        (temp_dir / "archetypes.json").write_text(json.dumps([asdict(item) for item in archetypes], indent=2), encoding="utf-8")
        (temp_dir / "evaluation_report.json").write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
        if out_dir.exists():
            shutil.rmtree(out_dir)
        temp_dir.replace(out_dir)
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
    return {"metadata": metadata, "evaluation": evaluation, "outputDir": str(out_dir)}
