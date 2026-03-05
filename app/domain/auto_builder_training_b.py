"""Model B — Training, Evaluation, and Artifact Export.

Trains a single end-to-end Transformer (CandidateScorerB) jointly on three objectives:
  L_bce   (weight 1.00) — next-card BCE with hard + easy negatives
  L_bpr   (weight 0.40) — Bayesian Personalized Ranking
  L_mask  (weight 0.30) — masked deck reconstruction over full vocab

Entry point: train_auto_builder_b_artifacts(...)
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
import os
import platform
import random
from pathlib import Path
from typing import Any, Callable

import numpy as np
from sklearn.cluster import SpectralClustering
from sklearn.decomposition import TruncatedSVD
from sklearn.linear_model import Ridge
import torch
import torch.nn.functional as F
from torch.optim.lr_scheduler import OneCycleLR

from app.domain.auto_builder_features import (
    build_card_static_features,
    build_card_text_features,
    build_training_rows,
    legend_domains_for_title,
    pearson_rank_correlation,
    shell_id_for_titles,
    shell_label_for_titles,
)
from app.domain.auto_builder_model_b import (
    CandidateScorerB,
    ModelBArtifact,
    _deck_archetype_idx,
    deck_to_tensors,
    generate_deck_b,
)
from app.domain.auto_builder_types import TrainingDeckRow
from app.domain.normalization import normalize_card_key
from app.domain.rules import load_format_rules
from app.infra.cards_repo import BASE_DOMAINS, CardCatalog, load_card_catalog
from app.infra.meta_repo import MetaDeckRepository

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_B_TEXT_SVD_DIM: int = 32
_B_ARCH_CLUSTERS: int = 32  # number of archetype clusters from co-occurrence graph
_B_VAL_FRAC: float = 0.18
_B_BCE_WEIGHT: float = 1.00
_B_BPR_WEIGHT: float = 0.40
_B_MASK_WEIGHT: float = 0.30
_B_MASK_FRAC: float = 0.25       # fraction of training rows used for mask loss per epoch
_B_MASK_CARDS: int = 2            # cards masked per row (2–3 random)
_B_HARD_NEG: int = 5
_B_EASY_NEG: int = 8
_B_TARGET_REMOVALS: int = 3       # distinct target cards sampled per training deck
_B_LABEL_SMOOTH: float = 0.05     # label smoothing: pos target = 1-eps, neg target = eps
_B_DEFAULT_EPOCHS: int = 40
_B_EVAL_SCENARIOS: int = 3
_TORCH_DEVICE_ENV = "RB_AUTO_BUILDER_TORCH_DEVICE"

_CARD_TYPES = ("Unit", "Gear", "Spell", "Legend", "Rune", "Battlefield")
_SUPER_TYPES = ("Champion", "Signature", "")

_DEFAULT_SYNTHETIC_PACK_MIN = 24
_DEFAULT_SYNTHETIC_PACK_MAX = 240
_DEFAULT_SYNTHETIC_SCENARIO_COUNT = 4


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _resolve_torch_device(requested: str | None = None) -> torch.device:
    choice = str(requested or os.environ.get(_TORCH_DEVICE_ENV, "auto")).strip().lower()
    if choice in {"", "auto"}:
        if torch.cuda.is_available():
            return torch.device("cuda")
        mps_backend = getattr(torch.backends, "mps", None)
        if mps_backend is not None and getattr(mps_backend, "is_available", lambda: False)():
            return torch.device("mps")
        return torch.device("cpu")
    return torch.device(choice)


def _batch_size_for_device(device: torch.device) -> int:
    name = device.type
    if name == "cuda":
        return 1024
    if name == "mps":
        return 512
    return 256


def _main_deck_size(rules) -> int:
    try:
        return max(1, int(rules.int_constraint("main_deck_size_exact", 40)))
    except Exception:
        return 40


def _emit_progress(
    cb: Callable[..., None] | None,
    *,
    stage: str,
    step: int,
    total_steps: int,
    message: str,
    extra: dict[str, Any] | None = None,
) -> None:
    if cb is None:
        return
    try:
        payload: dict[str, Any] = {
            "stage": str(stage or "").strip(),
            "step": max(0, int(step)),
            "totalSteps": max(1, int(total_steps)),
            "progressPct": round(100.0 * float(max(0, int(step))) / float(max(1, int(total_steps))), 2),
            "message": str(message or "").strip(),
        }
        if extra:
            payload.update(extra)
        cb(payload)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Temporal train/val split
# ---------------------------------------------------------------------------

def _temporal_split(rows: list[TrainingDeckRow], val_frac: float = _B_VAL_FRAC) -> tuple[list[TrainingDeckRow], list[TrainingDeckRow]]:
    """Sort by age_days descending (oldest first), use newest val_frac as validation."""
    sorted_rows = sorted(rows, key=lambda r: float(r.age_days or 0.0), reverse=True)
    n_val = max(1, int(len(sorted_rows) * val_frac))
    train = sorted_rows[:-n_val] if n_val < len(sorted_rows) else sorted_rows
    valid = sorted_rows[-n_val:] if n_val < len(sorted_rows) else []
    return train, valid


# ---------------------------------------------------------------------------
# Card feature matrix (59-dim)
# ---------------------------------------------------------------------------

def _build_card_feat_matrix(
    vocab_keys: list[str],
    static_features: dict,
    text_svd_matrix: np.ndarray,  # [V, 32]
    text_svd_key_order: list[str],
) -> np.ndarray:
    """Build the [V, 59] static feature matrix.

    Layout:
      cost_onehot(11)  — cost clamped 0–10
      domain_onehot(6) — multi-hot over BASE_DOMAINS
      type_onehot(6)   — one-hot card type
      supertype_oh(3)  — one-hot supertype
      is_unique(1)     — float
      text_svd(32)     — TruncatedSVD of TF-IDF
    Total: 11 + 6 + 6 + 3 + 1 + 32 = 59
    """
    V = len(vocab_keys)
    feat_dim = 11 + 6 + 6 + 3 + 1 + _B_TEXT_SVD_DIM
    assert feat_dim == 59
    mat = np.zeros((V, feat_dim), dtype=np.float32)

    domain_list = list(BASE_DOMAINS)
    type_list = list(_CARD_TYPES)
    super_list = list(_SUPER_TYPES)
    text_key_to_row = {k: i for i, k in enumerate(text_svd_key_order)}

    for i, key in enumerate(vocab_keys):
        sf = static_features.get(key)
        if sf is None:
            continue
        offset = 0
        # cost one-hot [0..10]
        cost = min(10, max(0, int(getattr(sf, "cost", 0) or 0)))
        mat[i, offset + cost] = 1.0
        offset += 11
        # domain multi-hot
        for d_idx, d_name in enumerate(domain_list):
            if d_name in (getattr(sf, "domains", ()) or ()):
                mat[i, offset + d_idx] = 1.0
        offset += 6
        # card type one-hot
        ct = str(getattr(sf, "card_type", "") or "")
        if ct in type_list:
            mat[i, offset + type_list.index(ct)] = 1.0
        offset += 6
        # supertype one-hot
        st = str(getattr(sf, "super_type", "") or "")
        if st in super_list:
            mat[i, offset + super_list.index(st)] = 1.0
        offset += 3
        # is_unique
        mat[i, offset] = 1.0 if getattr(sf, "is_unique", False) else 0.0
        offset += 1
        # text SVD
        txt_row = text_key_to_row.get(key)
        if txt_row is not None and txt_row < text_svd_matrix.shape[0]:
            mat[i, offset: offset + _B_TEXT_SVD_DIM] = text_svd_matrix[txt_row]

    return mat


# ---------------------------------------------------------------------------
# Training sample generation
# ---------------------------------------------------------------------------

def _build_legend_domain_map(train_rows: list[TrainingDeckRow], cards: CardCatalog) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for row in train_rows:
        domains = legend_domains_for_title(cards=cards, legend_title=row.leader_title)
        out[row.leader_title].update(domains)
    return dict(out)


def _build_legend_legal_keys(
    train_rows: list[TrainingDeckRow],
    legend_domain_map: dict[str, set[str]],
    static_features: dict,
    vocab_to_idx: dict[str, int],
) -> dict[str, list[str]]:
    """All vocab keys legally playable under each legend."""
    legend_titles = list({row.leader_title for row in train_rows})
    out: dict[str, list[str]] = {}
    all_keys = list(vocab_to_idx.keys())
    for title in legend_titles:
        domains = legend_domain_map.get(title, set())
        legal: list[str] = []
        for key in all_keys:
            sf = static_features.get(key)
            if sf is None:
                continue
            card_domains = set(getattr(sf, "domains", ()) or ())
            if card_domains and domains and not card_domains.issubset(domains):
                continue
            legal.append(key)
        out[title] = legal
    return out


def _build_cooccurrence_matrix(
    train_rows: list[TrainingDeckRow],
    vocab_to_idx: dict[str, int],
) -> np.ndarray:
    """Build V×V weighted co-occurrence matrix.

    W[i,j] = sum of sample_weights of decks where card i and card j both appear.
    Uses binary presence (not quantity). Symmetric, diagonal = 0.
    """
    V = len(vocab_to_idx)
    W = np.zeros((V, V), dtype=np.float32)
    for row in train_rows:
        keys = [k for k, v in row.main_by_key.items() if k in vocab_to_idx and int(v) > 0]
        if len(keys) < 2:
            continue
        idxs = [vocab_to_idx[k] - 1 for k in keys]  # 0-indexed
        weight = float(row.sample_weight)
        presence = np.zeros(V, dtype=np.float32)
        for idx in idxs:
            presence[idx] = 1.0
        W += weight * np.outer(presence, presence)
    np.fill_diagonal(W, 0.0)
    return W


def _cluster_cards_by_cooccurrence(
    cooc_mat: np.ndarray,
    n_clusters: int,
    random_state: int = 42,
) -> np.ndarray:
    """Cluster V cards into n_clusters archetypes using spectral clustering.

    Returns int64 array [V] with 0-indexed cluster labels.
    Cards with zero co-occurrence (never seen in training) get label 0.
    """
    V = cooc_mat.shape[0]
    max_val = float(cooc_mat.max())
    if max_val <= 0.0 or n_clusters >= V:
        return np.zeros(V, dtype=np.int64)
    affinity = (cooc_mat / max_val).astype(np.float32)
    # Clamp n_clusters to at most V - 1
    k = min(n_clusters, V - 1)
    import warnings
    clf = SpectralClustering(
        n_clusters=k,
        affinity="precomputed",
        random_state=random_state,
        n_jobs=-1,
        assign_labels="kmeans",
    )
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Graph is not fully connected")
        labels = clf.fit_predict(affinity)
    return labels.astype(np.int64)


def _make_completion_stage_samples(
    row: TrainingDeckRow,
    pool: list[str],
    n_remove: int,
    static_features: dict,
    vocab_to_idx: dict[str, int],
    legal_pool: list[str],
    main_deck_size: int,
    rng: random.Random,
    card_cluster_labels: np.ndarray,
) -> list[dict]:
    """Build BCE/BPR samples for one completion stage (n_remove cards removed from pool)."""
    stage_samples: list[dict] = []
    rng.shuffle(pool)
    removed: list[str] = pool[:n_remove]
    if not removed:
        return stage_samples

    # Build partial deck by removing `removed` cards (one copy each)
    partial: dict[str, int] = dict(row.main_by_key)
    for k in removed:
        partial[k] = partial.get(k, 0) - 1
        if partial[k] <= 0:
            partial.pop(k, None)

    archetype_idx = _deck_archetype_idx(partial, vocab_to_idx, card_cluster_labels)

    # Train on each removed card as a distinct positive target
    seen: set[str] = set()
    for target_key in removed:
        if target_key in seen or target_key not in vocab_to_idx:
            continue
        seen.add(target_key)

        target_sf = static_features.get(target_key)
        target_domains = set(getattr(target_sf, "domains", ()) or ()) if target_sf else set()

        hard_neg_pool = [
            k for k in legal_pool
            if k != target_key
            and target_domains
            and k in static_features
            and set(getattr(static_features[k], "domains", ()) or ()) & target_domains
        ]
        easy_neg_pool = [k for k in legal_pool if k != target_key and k not in set(hard_neg_pool)]
        rng.shuffle(hard_neg_pool)
        rng.shuffle(easy_neg_pool)
        selected = hard_neg_pool[:_B_HARD_NEG] + easy_neg_pool[:_B_EASY_NEG]
        if not selected:
            continue

        rem_frac = max(0.0, min(1.0, (main_deck_size - sum(partial.values())) / max(1, main_deck_size)))
        for neg_key in selected:
            stage_samples.append({
                "partial": partial,
                "pos_key": target_key,
                "neg_key": neg_key,
                "is_hard_neg": neg_key in hard_neg_pool[:_B_HARD_NEG],
                "legend_title": row.leader_title,
                "champion_title": row.chosen_champion_title,
                "rem_frac": rem_frac,
                "weight": float(row.sample_weight),
                "archetype_idx": archetype_idx,
            })
    return stage_samples


def _generate_bce_bpr_samples(
    rows: list[TrainingDeckRow],
    static_features: dict,
    vocab_to_idx: dict[str, int],
    legend_legal_keys: dict[str, list[str]],
    main_deck_size: int,
    rng: random.Random,
    card_cluster_labels: np.ndarray,
) -> list[dict]:
    """Generate BCE/BPR samples at near-complete stage (1-3 removals) per deck.

    Uses archetype conditioning from co-occurrence cluster labels.
    """
    samples = []
    for row in rows:
        keys_with_qty = [(k, v) for k, v in row.main_by_key.items() if k in vocab_to_idx and v > 0]
        if len(keys_with_qty) < 2:
            continue
        pool = []
        for k, v in keys_with_qty:
            pool.extend([k] * int(v))
        if len(pool) < 4:
            continue
        legal_pool = legend_legal_keys.get(row.leader_title) or list(vocab_to_idx.keys())

        # Near-complete stage: remove 1-3 cards (matches eval scenario)
        n_remove = rng.randint(1, min(3, len(pool) - 1))
        samples.extend(_make_completion_stage_samples(
            row, list(pool), n_remove, static_features, vocab_to_idx, legal_pool,
            main_deck_size, rng, card_cluster_labels,
        ))

    rng.shuffle(samples)
    return samples


def _generate_mask_samples(
    rows: list[TrainingDeckRow],
    vocab_to_idx: dict[str, int],
    main_deck_size: int,
    rng: random.Random,
    card_cluster_labels: np.ndarray,
    mask_frac: float = _B_MASK_FRAC,
    n_mask: int = _B_MASK_CARDS,
) -> list[dict]:
    """Generate masked reconstruction samples (25% of rows)."""
    subset_size = max(1, int(len(rows) * mask_frac))
    subset = rng.sample(rows, min(subset_size, len(rows)))
    samples = []
    for row in subset:
        keys_with_qty = [(k, v) for k, v in row.main_by_key.items() if k in vocab_to_idx and v > 0]
        if len(keys_with_qty) < n_mask + 1:
            continue
        pool = []
        for k, v in keys_with_qty:
            pool.extend([k] * int(v))
        actual_mask = min(n_mask + rng.randint(0, 1), len(pool) - 1)
        rng.shuffle(pool)
        masked_keys: set[str] = set(pool[:actual_mask])

        partial: dict[str, int] = {}
        for k, v in row.main_by_key.items():
            if k in masked_keys:
                # Keep remaining copies (qty - 1 masked)
                remaining = max(0, int(v) - pool[:actual_mask].count(k))
                if remaining > 0:
                    partial[k] = remaining
            else:
                partial[k] = int(v)

        rem_frac = max(0.0, min(1.0, (main_deck_size - sum(partial.values())) / max(1, main_deck_size)))
        archetype_idx = _deck_archetype_idx(partial, vocab_to_idx, card_cluster_labels)
        samples.append({
            "partial": partial,
            "masked_keys": masked_keys,
            "legend_title": row.leader_title,
            "champion_title": row.chosen_champion_title,
            "rem_frac": rem_frac,
            "weight": float(row.sample_weight),
            "archetype_idx": archetype_idx,
        })
    return samples


# ---------------------------------------------------------------------------
# Batch tensor builders
# ---------------------------------------------------------------------------

def _deck_to_arrays(
    partial: dict[str, int],
    vocab_to_idx: dict[str, int],
    card_feat_matrix: np.ndarray,
    max_deck: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Convert partial deck → (card_ids[max_deck], feats[max_deck,59], qty_fracs[max_deck], pad_mask_cards[max_deck])."""
    V, D = card_feat_matrix.shape
    card_ids = np.zeros(max_deck, dtype=np.int64)
    feats = np.zeros((max_deck, D), dtype=np.float32)
    qty_fracs = np.zeros(max_deck, dtype=np.float32)
    pad_mask_cards = np.ones(max_deck, dtype=bool)

    for pos, key in enumerate(sorted(partial.keys())[:max_deck]):
        idx = vocab_to_idx.get(key, 0)
        if idx == 0:
            continue
        card_ids[pos] = idx
        feats[pos] = card_feat_matrix[idx - 1]
        qty_fracs[pos] = min(1.0, partial[key] / 3.0)
        pad_mask_cards[pos] = False

    return card_ids, feats, qty_fracs, pad_mask_cards


def _collate_bce_bpr_batch(
    samples: list[dict],
    vocab_to_idx: dict[str, int],
    card_feat_matrix: np.ndarray,
    legend_to_idx: dict[str, int],
    champion_to_idx: dict[str, int],
    max_deck: int,
    device: torch.device,
) -> tuple[dict[str, torch.Tensor], torch.Tensor]:
    """Build batch tensors for BCE+BPR pass.

    Returns (inputs_dict, weights_tensor).
    inputs_dict keys: deck_card_ids, deck_feats, deck_qty_fracs, legend_idx, champion_idx,
                      pad_mask, cand_ids_pos, cand_feats_pos, cand_ids_neg, cand_feats_neg, rem_frac
    """
    B = len(samples)
    D = card_feat_matrix.shape[1]

    deck_card_ids = np.zeros((B, max_deck), dtype=np.int64)
    deck_feats = np.zeros((B, max_deck, D), dtype=np.float32)
    deck_qty_fracs = np.zeros((B, max_deck), dtype=np.float32)
    pad_mask = np.ones((B, max_deck + 1), dtype=bool)
    pad_mask[:, 0] = False  # CLS never masked

    legend_idx = np.zeros(B, dtype=np.int64)
    champion_idx = np.zeros(B, dtype=np.int64)
    rem_frac = np.zeros(B, dtype=np.float32)
    archetype_idx = np.zeros(B, dtype=np.int64)

    cand_ids_pos = np.zeros(B, dtype=np.int64)
    cand_feats_pos = np.zeros((B, D), dtype=np.float32)
    cand_ids_neg = np.zeros(B, dtype=np.int64)
    cand_feats_neg = np.zeros((B, D), dtype=np.float32)
    weights = np.ones(B, dtype=np.float32)

    for i, s in enumerate(samples):
        cids, fts, qtys, pm = _deck_to_arrays(s["partial"], vocab_to_idx, card_feat_matrix, max_deck)
        deck_card_ids[i] = cids
        deck_feats[i] = fts
        deck_qty_fracs[i] = qtys
        pad_mask[i, 1:] = pm

        legend_idx[i] = legend_to_idx.get(s["legend_title"], 0)
        champion_idx[i] = champion_to_idx.get(s["champion_title"], 0)
        rem_frac[i] = s["rem_frac"]
        archetype_idx[i] = int(s.get("archetype_idx", 0))

        pos_idx = vocab_to_idx.get(s["pos_key"], 0)
        neg_idx = vocab_to_idx.get(s["neg_key"], 0)
        cand_ids_pos[i] = pos_idx
        cand_feats_pos[i] = card_feat_matrix[pos_idx - 1] if pos_idx > 0 else 0.0
        cand_ids_neg[i] = neg_idx
        cand_feats_neg[i] = card_feat_matrix[neg_idx - 1] if neg_idx > 0 else 0.0
        weights[i] = s["weight"]

    def t(arr, dtype=None):
        tt = torch.from_numpy(arr)
        return tt.to(device=device, dtype=dtype) if dtype else tt.to(device)

    inputs = {
        "deck_card_ids": t(deck_card_ids),
        "deck_feats": t(deck_feats),
        "deck_qty_fracs": t(deck_qty_fracs),
        "legend_idx": t(legend_idx),
        "champion_idx": t(champion_idx),
        "pad_mask": t(pad_mask),
        "cand_ids_pos": t(cand_ids_pos),
        "cand_feats_pos": t(cand_feats_pos),
        "cand_ids_neg": t(cand_ids_neg),
        "cand_feats_neg": t(cand_feats_neg),
        "rem_frac": t(rem_frac),
        "archetype_idx": t(archetype_idx),
        "weights": t(weights),
    }
    return inputs, t(weights)


# ---------------------------------------------------------------------------
# Loss functions
# ---------------------------------------------------------------------------

def _bce_bpr_loss(
    model: CandidateScorerB,
    inputs: dict[str, torch.Tensor],
) -> tuple[torch.Tensor, torch.Tensor]:
    """Compute L_bce and L_bpr for a batch. Returns (L_bce, L_bpr)."""
    B = inputs["deck_card_ids"].shape[0]
    # Concatenate pos + neg for a single forward pass (2B samples)
    all_cand_ids = torch.cat([inputs["cand_ids_pos"], inputs["cand_ids_neg"]])        # [2B]
    all_cand_feats = torch.cat([inputs["cand_feats_pos"], inputs["cand_feats_neg"]])  # [2B, 59]
    deck_ids2 = inputs["deck_card_ids"].repeat(2, 1)
    deck_feats2 = inputs["deck_feats"].repeat(2, 1, 1)
    deck_qtys2 = inputs["deck_qty_fracs"].repeat(2, 1)
    leg2 = inputs["legend_idx"].repeat(2)
    champ2 = inputs["champion_idx"].repeat(2)
    pad2 = inputs["pad_mask"].repeat(2, 1)
    rem2 = inputs["rem_frac"].repeat(2)
    arch2 = inputs["archetype_idx"].repeat(2)

    logits = model(deck_ids2, deck_feats2, deck_qtys2, leg2, champ2, pad2,
                   all_cand_ids, all_cand_feats, rem2, arch2)   # [2B]
    logit_pos = logits[:B]
    logit_neg = logits[B:]
    w = inputs["weights"]

    # Label smoothing: positive target = 1-eps, negative target = eps
    eps = _B_LABEL_SMOOTH
    targets = torch.cat([
        torch.full((B,), 1.0 - eps, device=logit_pos.device),
        torch.full((B,), eps, device=logit_pos.device),
    ])
    w2 = torch.cat([w, w])
    l_bce = F.binary_cross_entropy_with_logits(logits, targets, weight=w2)

    l_bpr = (F.softplus(logit_neg - logit_pos) * w).mean()
    return l_bce, l_bpr


def _mask_loss(
    model: CandidateScorerB,
    mask_samples: list[dict],
    vocab_to_idx: dict[str, int],
    card_feat_matrix: np.ndarray,
    legend_to_idx: dict[str, int],
    champion_to_idx: dict[str, int],
    max_deck: int,
    device: torch.device,
) -> torch.Tensor:
    """Compute L_mask (masked deck reconstruction) over the mask batch.

    Scores all V vocab cards for each deck in one broadcast.
    """
    if not mask_samples:
        return torch.tensor(0.0, device=device)

    V = len(vocab_to_idx)
    D = card_feat_matrix.shape[1]
    B = len(mask_samples)

    deck_card_ids = np.zeros((B, max_deck), dtype=np.int64)
    deck_feats_arr = np.zeros((B, max_deck, D), dtype=np.float32)
    deck_qty_fracs = np.zeros((B, max_deck), dtype=np.float32)
    pad_mask = np.ones((B, max_deck + 1), dtype=bool)
    pad_mask[:, 0] = False
    legend_idx_arr = np.zeros(B, dtype=np.int64)
    champion_idx_arr = np.zeros(B, dtype=np.int64)
    rem_frac_arr = np.zeros(B, dtype=np.float32)
    archetype_idx_arr = np.zeros(B, dtype=np.int64)
    targets_arr = np.zeros((B, V), dtype=np.float32)

    for i, s in enumerate(mask_samples):
        cids, fts, qtys, pm = _deck_to_arrays(s["partial"], vocab_to_idx, card_feat_matrix, max_deck)
        deck_card_ids[i] = cids
        deck_feats_arr[i] = fts
        deck_qty_fracs[i] = qtys
        pad_mask[i, 1:] = pm
        legend_idx_arr[i] = legend_to_idx.get(s["legend_title"], 0)
        champion_idx_arr[i] = champion_to_idx.get(s["champion_title"], 0)
        rem_frac_arr[i] = s["rem_frac"]
        archetype_idx_arr[i] = int(s.get("archetype_idx", 0))
        for key in s["masked_keys"]:
            idx = vocab_to_idx.get(key, 0)
            if 0 < idx <= V:
                targets_arr[i, idx - 1] = 1.0

    deck_card_ids_t = torch.from_numpy(deck_card_ids).to(device)
    deck_feats_t = torch.from_numpy(deck_feats_arr).to(device)
    deck_qty_fracs_t = torch.from_numpy(deck_qty_fracs).to(device)
    pad_mask_t = torch.from_numpy(pad_mask).to(device)
    legend_t = torch.from_numpy(legend_idx_arr).to(device)
    champion_t = torch.from_numpy(champion_idx_arr).to(device)
    rem_frac_t = torch.from_numpy(rem_frac_arr).to(device, dtype=torch.float32)
    arch_t = torch.from_numpy(archetype_idx_arr).to(device)
    targets_t = torch.from_numpy(targets_arr).to(device)

    # Encode all B decks at once
    cls_vecs = model.encoder(deck_card_ids_t, deck_feats_t, deck_qty_fracs_t,
                             legend_t, champion_t, pad_mask_t, arch_t)  # [B, d]

    # Project all V candidate cards
    all_cand_ids = torch.arange(1, V + 1, dtype=torch.long, device=device)  # [V]
    all_cand_feats = torch.from_numpy(card_feat_matrix).to(device)           # [V, 59]
    cand_vecs = model.cand_norm(model.cand_proj(
        torch.cat([model.cand_id_emb(all_cand_ids), all_cand_feats], dim=-1)
    ))  # [V, d]

    # Broadcast score_head over [B, V]
    rem_vecs = model.rem_proj(rem_frac_t.unsqueeze(-1))  # [B, 16]
    cls_exp = cls_vecs.unsqueeze(1).expand(-1, V, -1)      # [B, V, d]
    cand_exp = cand_vecs.unsqueeze(0).expand(B, -1, -1)    # [B, V, d]
    rem_exp = rem_vecs.unsqueeze(1).expand(-1, V, -1)       # [B, V, 16]
    combined = torch.cat([cls_exp, cand_exp, rem_exp], dim=-1)  # [B, V, d*2+16]
    logits = model.score_head(combined).squeeze(-1)         # [B, V]

    return F.binary_cross_entropy_with_logits(logits, targets_t)


# ---------------------------------------------------------------------------
# Training loop
# ---------------------------------------------------------------------------

def train_model_b(
    train_rows: list[TrainingDeckRow],
    cards: CardCatalog,
    device: torch.device,
    *,
    main_deck_size: int,
    card_feat_matrix: np.ndarray,
    vocab_to_idx: dict[str, int],
    index_to_key: list[str],
    legend_to_idx: dict[str, int],
    champion_to_idx: dict[str, int],
    static_features: dict,
    max_deck: int,
    card_cluster_labels: np.ndarray,
    arch_count: int,
    epochs: int = _B_DEFAULT_EPOCHS,
    progress_callback: Callable[..., None] | None = None,
    total_steps: int = 100,
    step_offset: int = 0,
) -> tuple[CandidateScorerB, dict[str, float]]:
    """Train CandidateScorerB and return (model, loss_history_dict)."""
    V = len(vocab_to_idx)
    legend_count = len(legend_to_idx)
    champion_count = len(champion_to_idx)
    card_feat_dim = card_feat_matrix.shape[1]
    batch_size = _batch_size_for_device(device)

    from app.domain.auto_builder_model_b import (
        _B_D_MODEL, _B_N_HEADS, _B_N_LAYERS, _B_FFN_DIM, _B_DROPOUT, _B_SCORE_HIDDEN,
    )

    model = CandidateScorerB(
        vocab_size=V,
        card_feat_dim=card_feat_dim,
        d_model=_B_D_MODEL,
        n_heads=_B_N_HEADS,
        n_layers=_B_N_LAYERS,
        ffn_dim=_B_FFN_DIM,
        legend_count=legend_count,
        champion_count=champion_count,
        max_deck=max_deck,
        dropout=_B_DROPOUT,
        score_hidden=_B_SCORE_HIDDEN,
        arch_count=arch_count,
    ).to(device)

    legend_legal_keys = _build_legend_legal_keys(
        train_rows, _build_legend_domain_map(train_rows, cards), static_features, vocab_to_idx
    )

    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=5e-4)

    rng = random.Random(42)
    loss_history: dict[str, list[float]] = {"bce": [], "bpr": [], "mask": []}
    final_losses: dict[str, float] = {"bce": 0.0, "bpr": 0.0, "mask": 0.0}

    # Pre-generate all BCE/BPR samples once (fast)
    _emit_progress(progress_callback, stage="train_b", step=step_offset + 1,
                   total_steps=total_steps, message="Building training samples.")
    all_bce_samples = _generate_bce_bpr_samples(
        train_rows, static_features, vocab_to_idx, legend_legal_keys, main_deck_size, rng,
        card_cluster_labels,
    )
    if not all_bce_samples:
        raise ValueError("No BCE/BPR training samples generated. Check training data.")

    # OneCycleLR requires total_steps upfront — compute accurately then add 10% buffer
    n_bce_batches = max(1, math.ceil(len(all_bce_samples) / batch_size))
    mask_batch_size_est = max(8, batch_size // 4)
    n_mask_samples_est = max(1, int(len(train_rows) * _B_MASK_FRAC))
    n_mask_batches = max(1, math.ceil(n_mask_samples_est / mask_batch_size_est))
    total_scheduler_steps = epochs * (n_bce_batches + n_mask_batches)
    # Add 15% buffer so we never overflow if batch counts vary slightly epoch-to-epoch
    total_scheduler_steps = int(total_scheduler_steps * 1.15) + epochs
    scheduler = OneCycleLR(optimizer, max_lr=3e-4, total_steps=total_scheduler_steps,
                           pct_start=0.10, anneal_strategy="cos")

    for epoch in range(epochs):
        model.train()
        epoch_bce_loss = 0.0
        epoch_bpr_loss = 0.0
        epoch_mask_loss = 0.0
        n_bce = 0
        n_mask = 0

        # Shuffle BCE/BPR samples each epoch
        rng.shuffle(all_bce_samples)

        for batch_start in range(0, len(all_bce_samples), batch_size):
            batch = all_bce_samples[batch_start: batch_start + batch_size]
            if not batch:
                continue
            inputs, _ = _collate_bce_bpr_batch(
                batch, vocab_to_idx, card_feat_matrix, legend_to_idx, champion_to_idx, max_deck, device
            )
            l_bce, l_bpr = _bce_bpr_loss(model, inputs)
            loss = _B_BCE_WEIGHT * l_bce + _B_BPR_WEIGHT * l_bpr
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            epoch_bce_loss += l_bce.item()
            epoch_bpr_loss += l_bpr.item()
            n_bce += 1

        # Masked reconstruction pass (25% of rows)
        mask_samples = _generate_mask_samples(train_rows, vocab_to_idx, main_deck_size, rng, card_cluster_labels)
        mask_batch_size = max(8, batch_size // 4)
        for batch_start in range(0, len(mask_samples), mask_batch_size):
            mask_batch = mask_samples[batch_start: batch_start + mask_batch_size]
            if not mask_batch:
                continue
            l_mask = _mask_loss(model, mask_batch, vocab_to_idx, card_feat_matrix,
                                legend_to_idx, champion_to_idx, max_deck, device)
            weighted_mask = _B_MASK_WEIGHT * l_mask
            optimizer.zero_grad()
            weighted_mask.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            epoch_mask_loss += l_mask.item()
            n_mask += 1

        avg_bce = epoch_bce_loss / max(1, n_bce)
        avg_bpr = epoch_bpr_loss / max(1, n_bce)
        avg_mask = epoch_mask_loss / max(1, n_mask)
        loss_history["bce"].append(avg_bce)
        loss_history["bpr"].append(avg_bpr)
        loss_history["mask"].append(avg_mask)
        final_losses = {"bce": avg_bce, "bpr": avg_bpr, "mask": avg_mask}

        progress_step = step_offset + 2 + int((epoch + 1) / epochs * (total_steps - step_offset - 4))
        _emit_progress(
            progress_callback,
            stage="train_b",
            step=min(progress_step, total_steps - 2),
            total_steps=total_steps,
            message=f"Epoch {epoch + 1}/{epochs} — bce={avg_bce:.4f} bpr={avg_bpr:.4f} mask={avg_mask:.4f}",
            extra={"epoch": epoch + 1, "bceLoss": round(avg_bce, 4),
                   "bprLoss": round(avg_bpr, 4), "maskLoss": round(avg_mask, 4)},
        )

    model.eval()
    return model, final_losses


# ---------------------------------------------------------------------------
# Collection simulation helpers (verbatim from auto_builder_training.py)
# ---------------------------------------------------------------------------

def _rarity_bucket(card) -> str:
    rarity = str(getattr(card, "rarity", "") or "").strip().lower()
    if "epic" in rarity:
        return "epic"
    if "uncommon" in rarity:
        return "uncommon"
    if "epic" in rarity:
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
    }


def _sample_from_pool(rng: random.Random, pool: list[str], count: int, collection: Counter) -> None:
    if not pool or count <= 0:
        return
    for _ in range(max(0, int(count))):
        collection[rng.choice(pool)] += 1


def _pack_simulated_collection(*, rng: random.Random, synthetic_config: dict[str, Any] | None) -> Counter:
    config = dict(synthetic_config or {})
    pack_min = max(24, min(240, int(config.get("packMin") or _DEFAULT_SYNTHETIC_PACK_MIN)))
    pack_max = max(pack_min, min(240, int(config.get("packMax") or _DEFAULT_SYNTHETIC_PACK_MAX)))
    pools = {bucket: list(values) for bucket, values in dict(config.get("pools") or {}).items()}
    collection: Counter = Counter()
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
    collection: Counter = _pack_simulated_collection(rng=rng, synthetic_config=synthetic_config)
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
        other for other in donor_rows
        if other.deck_signature != row.deck_signature
        and shell_id_for_titles(cards=cards, legend_title=other.leader_title, chosen_champion_title=other.chosen_champion_title) == row_shell
    ]
    other_shell_rows = [
        other for other in donor_rows
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
    mixed = _synthetic_collection_for_row(row, donor_rows=donor_rows, cards=cards,
                                          buildable_target=False, synthetic_config=synthetic_config, salt=salt)
    strict = _synthetic_collection_for_row(row, donor_rows=donor_rows, cards=cards,
                                           buildable_target=True, synthetic_config=synthetic_config, salt=salt)
    return mixed, strict


def _synthetic_collection_scenarios(
    row: TrainingDeckRow,
    *,
    donor_rows: list[TrainingDeckRow],
    cards: CardCatalog,
    synthetic_config: dict[str, Any] | None = None,
    salt: str = "",
    scenario_count: int = _B_EVAL_SCENARIOS,
) -> list[tuple[dict[str, int], dict[str, int]]]:
    derived_count = int((synthetic_config or {}).get("scenarioCount") or scenario_count)
    return [
        _synthetic_collection_pair(row, donor_rows=donor_rows, cards=cards,
                                   synthetic_config=synthetic_config, salt=f"{salt}:scenario-{idx}")
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


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _get_cls_vector(
    model: CandidateScorerB,
    row: TrainingDeckRow,
    vocab_to_idx: dict[str, int],
    card_feat_matrix: np.ndarray,
    legend_to_idx: dict[str, int],
    champion_to_idx: dict[str, int],
    max_deck: int,
    device: torch.device,
    card_cluster_labels: np.ndarray,
) -> np.ndarray:
    """Get the CLS vector for a training row."""
    card_ids_t, feats_t, qty_t, pad_t = deck_to_tensors(
        row.main_by_key, vocab_to_idx, card_feat_matrix, max_deck, device
    )
    leg_t = torch.tensor([legend_to_idx.get(row.leader_title, 0)], dtype=torch.long, device=device)
    champ_t = torch.tensor([champion_to_idx.get(row.chosen_champion_title, 0)], dtype=torch.long, device=device)
    arch_idx = _deck_archetype_idx(row.main_by_key, vocab_to_idx, card_cluster_labels)
    arch_t = torch.tensor([arch_idx], dtype=torch.long, device=device)
    with torch.inference_mode():
        cls = model.encoder(card_ids_t, feats_t, qty_t, leg_t, champ_t, pad_t, arch_t)
    return cls[0].cpu().numpy().astype(np.float32)


def evaluate_model_b(
    model: CandidateScorerB,
    valid_rows: list[TrainingDeckRow],
    train_rows: list[TrainingDeckRow],
    vocab_to_idx: dict[str, int],
    index_to_key: list[str],
    card_feat_matrix: np.ndarray,
    legend_to_idx: dict[str, int],
    champion_to_idx: dict[str, int],
    cards: CardCatalog,
    static_features: dict,
    main_deck_size: int,
    max_deck: int,
    device: torch.device,
    card_cluster_labels: np.ndarray,
    arch_count: int,
    synthetic_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate Model B on all 7 benchmark metrics."""
    model.eval()
    V = len(vocab_to_idx)
    all_cand_ids_t = torch.arange(1, V + 1, dtype=torch.long, device=device)
    card_feat_t = torch.from_numpy(card_feat_matrix).to(device)

    eval_rows = valid_rows[:64] if valid_rows else []

    # ------------------------------------------------------------------
    # 1. nextCardTop10Recall + maskedDeckReconstructionExactCardRecall
    # ------------------------------------------------------------------
    hits_top10 = 0
    hits_reconstruction = 0
    attempts = 0

    for row in eval_rows:
        if not row.main_by_key or len(row.main_by_key) < 2:
            continue
        target_key = next(iter(row.main_by_key.keys()))
        partial = dict(row.main_by_key)
        partial[target_key] = max(0, partial.get(target_key, 1) - 1)
        if partial[target_key] <= 0:
            del partial[target_key]

        card_ids_t, feats_t, qty_t, pad_t = deck_to_tensors(
            partial, vocab_to_idx, card_feat_matrix, max_deck, device
        )
        leg_t = torch.tensor([legend_to_idx.get(row.leader_title, 0)], dtype=torch.long, device=device)
        champ_t = torch.tensor([champion_to_idx.get(row.chosen_champion_title, 0)], dtype=torch.long, device=device)
        rem_t = torch.tensor(
            [(main_deck_size - sum(partial.values())) / max(1, main_deck_size)],
            dtype=torch.float32, device=device,
        )
        arch_val = _deck_archetype_idx(partial, vocab_to_idx, card_cluster_labels)
        arch_t = torch.tensor([arch_val], dtype=torch.long, device=device)
        logits = model.score_candidates_batch(
            card_ids_t, feats_t, qty_t, leg_t, champ_t, pad_t, rem_t, arch_t, all_cand_ids_t, card_feat_t,
        ).cpu().numpy()

        sorted_keys = [index_to_key[i] for i in np.argsort(logits)[::-1] if i < len(index_to_key)]
        if target_key in sorted_keys[:10]:
            hits_top10 += 1
        if sorted_keys and sorted_keys[0] == target_key:
            hits_reconstruction += 1
        attempts += 1

    next_card_top10 = hits_top10 / max(1, attempts)
    masked_reconstruction = hits_reconstruction / max(1, attempts)

    # ------------------------------------------------------------------
    # 2. competitiveScoreSpearman (Ridge probe on CLS vectors)
    # ------------------------------------------------------------------
    spearman = 0.0
    if train_rows and valid_rows:
        try:
            train_cls = np.array([
                _get_cls_vector(model, row, vocab_to_idx, card_feat_matrix,
                                legend_to_idx, champion_to_idx, max_deck, device, card_cluster_labels)
                for row in train_rows[:200]
            ], dtype=np.float32)
            train_scores = np.array([float(row.meta_score) for row in train_rows[:200]], dtype=np.float32)
            valid_cls = np.array([
                _get_cls_vector(model, row, vocab_to_idx, card_feat_matrix,
                                legend_to_idx, champion_to_idx, max_deck, device, card_cluster_labels)
                for row in valid_rows[:64]
            ], dtype=np.float32)
            valid_scores = [float(row.meta_score) for row in valid_rows[:64]]
            if len(train_cls) > 1 and len(valid_cls) > 1:
                ridge = Ridge(alpha=1.0)
                ridge.fit(train_cls, train_scores)
                pred = ridge.predict(valid_cls)
                spearman = pearson_rank_correlation(list(pred), valid_scores)
        except Exception:
            spearman = 0.0

    # ------------------------------------------------------------------
    # 3. Strict buildable metrics (generate deck → check completion)
    # ------------------------------------------------------------------
    hit_count = 0
    empty_count = 0
    candidate_counts: list[int] = []
    first_rec_hits = 0
    buildable_attempts = 0

    legend_domains_cache: dict[str, tuple[str, ...]] = {}

    for row in eval_rows:
        legend_title = row.leader_title
        champion_title = row.chosen_champion_title

        if legend_title not in legend_domains_cache:
            legend_domains_cache[legend_title] = legend_domains_for_title(
                cards=cards, legend_title=legend_title
            )
        legend_domains = legend_domains_cache[legend_title]

        for _mixed_col, strict_col in _synthetic_collection_scenarios(
            row, donor_rows=train_rows, cards=cards, synthetic_config=synthetic_config,
            salt="model-b-eval",
        ):
            buildable_attempts += 1

            # Count available candidates
            cand_count = sum(
                1 for k in vocab_to_idx
                if _can_add_b(k, {}, static_features, legend_domains, main_deck_size)
                and strict_col.get(k, 0) > 0
            )
            candidate_counts.append(cand_count)

            if cand_count == 0:
                empty_count += 1
                continue

            # Generate deck with collection constraint
            artifact_stub = _StubArtifact(
                vocab_to_idx=vocab_to_idx,
                index_to_key=index_to_key,
                legend_to_idx=legend_to_idx,
                champion_to_idx=champion_to_idx,
                card_feat_matrix=card_feat_matrix,
                card_feat_matrix_tensor=card_feat_t,
                all_cand_ids_tensor=all_cand_ids_t,
                main_deck_size=main_deck_size,
                card_freq_by_legend={},
                static_features=_static_features_as_dict(static_features),
                shell_profiles=[],
                archetypes=[],
                deck_profiles=[],
                model_params={"max_deck": max_deck},
                card_cluster_labels=card_cluster_labels,
                arch_count=arch_count,
            )
            generated, _ = generate_deck_b(
                legend_title=legend_title,
                champion_title=champion_title,
                model=model,
                artifact=artifact_stub,
                collection_by_key=strict_col,
                strict_buildable=True,
            )
            if generated is None:
                empty_count += 1
                continue

            completion = _completion_against_collection(generated, strict_col)
            if completion >= 0.65:
                hit_count += 1

    strict_hit_rate = hit_count / max(1, buildable_attempts)
    strict_empty_rate = empty_count / max(1, buildable_attempts)
    p50 = float(np.percentile(candidate_counts, 50)) if candidate_counts else 0.0
    p90 = float(np.percentile(candidate_counts, 90)) if candidate_counts else 0.0

    # collectionFirstRecommendationHitRate (top-1 match with completion > 0.65)
    collection_hit_attempts = 0
    collection_hits = 0
    for row in eval_rows:
        for mixed_col, _strict_col in _synthetic_collection_scenarios(
            row, donor_rows=train_rows, cards=cards, synthetic_config=synthetic_config,
            salt="model-b-coll-hit",
        ):
            collection_hit_attempts += 1
            card_ids_t2, feats_t2, qty_t2, pad_t2 = deck_to_tensors(
                {}, vocab_to_idx, card_feat_matrix, max_deck, device
            )
            leg_t2 = torch.tensor([legend_to_idx.get(row.leader_title, 0)], dtype=torch.long, device=device)
            champ_t2 = torch.tensor([champion_to_idx.get(row.chosen_champion_title, 0)], dtype=torch.long, device=device)
            rem_t2 = torch.tensor([1.0], dtype=torch.float32, device=device)
            arch_t2 = torch.tensor([0], dtype=torch.long, device=device)  # empty deck = unknown archetype
            logits2 = model.score_candidates_batch(
                card_ids_t2, feats_t2, qty_t2, leg_t2, champ_t2, pad_t2,
                rem_t2, arch_t2, all_cand_ids_t, card_feat_t,
            ).cpu().numpy()
            best_idx = int(np.argmax(logits2))
            best_key = index_to_key[best_idx] if best_idx < len(index_to_key) else ""
            if best_key and mixed_col.get(best_key, 0) > 0:
                collection_hits += 1

    collection_first_hit = collection_hits / max(1, collection_hit_attempts)

    return {
        "nextCardTop10Recall": round(float(next_card_top10), 4),
        "maskedDeckReconstructionExactCardRecall": round(float(masked_reconstruction), 4),
        "competitiveScoreSpearman": round(float(spearman), 4),
        "strictBuildableHitRate": round(float(strict_hit_rate), 4),
        "strictBuildableEmptyRate": round(float(strict_empty_rate), 4),
        "strictBuildableCandidateCountP50": round(float(p50), 4),
        "strictBuildableCandidateCountP90": round(float(p90), 4),
        "collectionFirstRecommendationHitRate": round(float(collection_first_hit), 4),
    }


def _can_add_b(key: str, partial: dict[str, int], static_features: dict, legend_domains: tuple, main_deck_size: int) -> bool:
    sf = static_features.get(key)
    if sf is None:
        return False
    sf_domains = getattr(sf, "domains", ()) or ()
    if sf_domains and legend_domains and not set(sf_domains).issubset(set(legend_domains)):
        return False
    is_unique = getattr(sf, "is_unique", False)
    st = str(getattr(sf, "super_type", "") or "")
    max_copies = 1 if is_unique or st in ("Champion", "Signature") else 3
    if partial.get(key, 0) >= max_copies:
        return False
    if sum(partial.values()) >= main_deck_size:
        return False
    return True


def _static_features_as_dict(static_features: dict) -> dict:
    """Convert CardStaticFeatures objects to plain dicts for ModelBArtifact."""
    out: dict[str, Any] = {}
    for key, sf in static_features.items():
        out[key] = {
            "title": getattr(sf, "title", ""),
            "domains": list(getattr(sf, "domains", ()) or ()),
            "card_type": getattr(sf, "card_type", ""),
            "super_type": getattr(sf, "super_type", ""),
            "is_unique": getattr(sf, "is_unique", False),
            "superType": getattr(sf, "super_type", ""),
            "isUnique": getattr(sf, "is_unique", False),
        }
    return out


class _StubArtifact:
    """Minimal duck-type of ModelBArtifact for generate_deck_b during evaluation."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


# ---------------------------------------------------------------------------
# Shell / archetype profile builders (simplified for Model B metadata)
# ---------------------------------------------------------------------------

def _build_shell_profiles(rows: list[TrainingDeckRow], cards: CardCatalog) -> list[dict[str, Any]]:
    shells: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = shell_id_for_titles(cards=cards, legend_title=row.leader_title,
                                  chosen_champion_title=row.chosen_champion_title)
        if sid not in shells:
            domains = legend_domains_for_title(cards=cards, legend_title=row.leader_title)
            shells[sid] = {
                "shellId": sid,
                "shellLabel": shell_label_for_titles(legend_title=row.leader_title,
                                                     chosen_champion_title=row.chosen_champion_title),
                "legendTitle": row.leader_title,
                "chosenChampionTitle": row.chosen_champion_title,
                "legendDomains": list(domains),
                "deckCount": 0,
                "avgMetaScore": 0.0,
                "metaScores": [],
                "sourceBreakdown": defaultdict(int),
            }
        shells[sid]["deckCount"] += 1
        shells[sid]["metaScores"].append(float(row.meta_score))
        shells[sid]["sourceBreakdown"][row.source] += 1

    result = []
    for sid, s in shells.items():
        scores = s.pop("metaScores")
        s["avgMetaScore"] = round(float(np.mean(scores)) if scores else 0.0, 4)
        s["sourceBreakdown"] = dict(s["sourceBreakdown"])
        result.append(s)
    return sorted(result, key=lambda x: -x["deckCount"])


def _build_archetype_profiles(
    rows: list[TrainingDeckRow],
    cards: CardCatalog,
) -> list[dict[str, Any]]:
    """Simplified: one archetype per shell (aggregate prototype)."""
    shells: dict[str, list[TrainingDeckRow]] = defaultdict(list)
    for row in rows:
        sid = shell_id_for_titles(cards=cards, legend_title=row.leader_title,
                                  chosen_champion_title=row.chosen_champion_title)
        shells[sid].append(row)

    result = []
    for sid, shell_rows in shells.items():
        if not shell_rows:
            continue
        # Prototype: average card counts
        card_totals: Counter = Counter()
        for row in shell_rows:
            for key, qty in row.main_by_key.items():
                card_totals[key] += int(qty)
        n = len(shell_rows)
        prototype = {k: round(v / n, 2) for k, v in card_totals.items() if v / n >= 0.5}
        top_core = sorted(prototype.keys(), key=lambda k: -prototype[k])[:8]
        example = shell_rows[0]
        result.append({
            "archetypeId": f"{sid}:default",
            "shellId": sid,
            "archetypeName": shell_label_for_titles(
                legend_title=example.leader_title, chosen_champion_title=example.chosen_champion_title
            ),
            "legendTitle": example.leader_title,
            "chosenChampionTitle": example.chosen_champion_title,
            "prototypeMain": prototype,
            "topCoreCards": top_core,
            "deckCount": n,
        })
    return result


def _build_deck_profiles(rows: list[TrainingDeckRow]) -> list[dict[str, Any]]:
    return [
        {
            "source": row.source,
            "deckId": row.deck_id,
            "deckName": row.deck_name,
            "legendTitle": row.leader_title,
            "chosenChampionTitle": row.chosen_champion_title,
            "mainByKey": dict(row.main_by_key),
            "competitiveScore": float(row.meta_score),
            "sampleWeight": float(row.sample_weight),
        }
        for row in rows
    ]


def _build_card_freq_by_legend(
    train_rows: list[TrainingDeckRow],
    vocab_to_idx: dict[str, int],
) -> dict[str, dict[str, float]]:
    """Frequency of each card in decks for each legend (normalized 0–1)."""
    legend_counts: dict[str, Counter] = defaultdict(Counter)
    legend_totals: Counter = Counter()
    for row in train_rows:
        legend_totals[row.leader_title] += 1
        for key in row.main_by_key:
            if key in vocab_to_idx:
                legend_counts[row.leader_title][key] += 1

    all_counts: Counter = Counter()
    all_total = max(1, len(train_rows))
    for row in train_rows:
        for key in row.main_by_key:
            if key in vocab_to_idx:
                all_counts[key] += 1

    out: dict[str, dict[str, float]] = {}
    for legend, counts in legend_counts.items():
        total = max(1, int(legend_totals[legend]))
        out[legend] = {k: round(v / total, 4) for k, v in counts.items()}
    out["__all__"] = {k: round(v / all_total, 4) for k, v in all_counts.items()}
    return out


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def train_auto_builder_b_artifacts(
    *,
    cards_path: Path,
    meta_index_path: Path,
    rules_profile_path: Path | None = None,
    out_dir: Path,
    epochs: int = _B_DEFAULT_EPOCHS,
    torch_device: str | None = None,
    progress_callback: Callable[..., None] | None = None,
    synthetic_collection_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full Model B training pipeline. Saves generator_b.pt + model_b_metadata.json."""
    from app.domain.auto_builder_model_b import _B_D_MODEL, _B_N_HEADS, _B_N_LAYERS, _B_FFN_DIM, _B_SCORE_HIDDEN
    import sklearn

    total_steps = 100
    step = 0

    device = _resolve_torch_device(torch_device)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    _emit_progress(progress_callback, stage="init", step=step, total_steps=total_steps,
                   message=f"Model B training starting on {device}.")
    step += 1

    # -- Load data -----------------------------------------------------------
    cards = load_card_catalog(cards_path)
    if rules_profile_path is None:
        rules_profile_path = Path(__file__).parents[2] / "rules_profiles" / "constructed.json"
    rules = load_format_rules(rules_profile_path)
    meta_repo = MetaDeckRepository(meta_index_path, cards, rules)
    all_entries = meta_repo.search_entries(query="", limit=None, offset=0)
    all_rows = build_training_rows(all_entries, cards=cards)
    if not all_rows:
        raise ValueError("No training rows found. Check meta-index and cards path.")

    main_deck_size = _main_deck_size(rules)
    _emit_progress(progress_callback, stage="init", step=step, total_steps=total_steps,
                   message=f"Loaded {len(all_rows)} training decks.", extra={"deckCount": len(all_rows)})
    step += 1

    # -- Train/val split -----------------------------------------------------
    train_rows, valid_rows = _temporal_split(all_rows)
    _emit_progress(progress_callback, stage="init", step=step, total_steps=total_steps,
                   message=f"Train={len(train_rows)} Val={len(valid_rows)} (temporal split).",
                   extra={"trainCount": len(train_rows), "validCount": len(valid_rows)})
    step += 1

    # -- Vocab ---------------------------------------------------------------
    from app.domain.auto_builder_features import build_main_vocab
    vocab_to_idx, index_to_key = build_main_vocab(all_rows)
    V = len(vocab_to_idx)
    _emit_progress(progress_callback, stage="init", step=step, total_steps=total_steps,
                   message=f"Vocab size: {V} cards.", extra={"vocabSize": V})
    step += 1

    # -- Static features -----------------------------------------------------
    static_features = build_card_static_features(cards, vocab_keys=list(vocab_to_idx.keys()))

    # -- Text features (TF-IDF → TruncatedSVD 32) ----------------------------
    text_feat = build_card_text_features(cards, vocab_keys=list(vocab_to_idx.keys()))
    text_svd_matrix = np.zeros((len(text_feat.keys), _B_TEXT_SVD_DIM), dtype=np.float32)
    if text_feat.matrix.shape[0] > 0:
        n_components = min(_B_TEXT_SVD_DIM, text_feat.matrix.shape[1], text_feat.matrix.shape[0])
        svd = TruncatedSVD(n_components=n_components, random_state=42)
        reduced = svd.fit_transform(text_feat.matrix).astype(np.float32)
        text_svd_matrix[:, :reduced.shape[1]] = reduced

    text_svd_key_order = list(text_feat.keys)

    # -- Card feature matrix [V, 59] -----------------------------------------
    card_feat_matrix = _build_card_feat_matrix(
        index_to_key, static_features, text_svd_matrix, text_svd_key_order
    )
    _emit_progress(progress_callback, stage="init", step=step, total_steps=total_steps,
                   message=f"Card feature matrix: {card_feat_matrix.shape}.",
                   extra={"featDim": card_feat_matrix.shape[1]})
    step += 1

    # -- Legend / champion indices -------------------------------------------
    legend_titles = sorted({row.leader_title for row in all_rows})
    champion_titles = sorted({row.chosen_champion_title for row in all_rows})
    legend_to_idx = {t: i + 1 for i, t in enumerate(legend_titles)}   # 1-based
    champion_to_idx = {t: i + 1 for i, t in enumerate(champion_titles)}

    max_deck = main_deck_size + 2   # 40 + 2 buffer = 42

    # -- Co-occurrence graph → archetype clusters ----------------------------
    _emit_progress(progress_callback, stage="init", step=step, total_steps=total_steps,
                   message=f"Building card co-occurrence graph ({V}×{V}) and clustering into {_B_ARCH_CLUSTERS} archetypes.")
    cooc_mat = _build_cooccurrence_matrix(train_rows, vocab_to_idx)
    card_cluster_labels = _cluster_cards_by_cooccurrence(cooc_mat, n_clusters=_B_ARCH_CLUSTERS)
    arch_count = _B_ARCH_CLUSTERS
    _emit_progress(progress_callback, stage="init", step=step, total_steps=total_steps,
                   message=f"Archetype clustering done. {arch_count} clusters over {V} cards.",
                   extra={"archCount": arch_count})
    step += 1

    # -- Train ---------------------------------------------------------------
    _emit_progress(progress_callback, stage="train_b", step=step, total_steps=total_steps,
                   message=f"Training Model B for {epochs} epochs on {device}.")

    model, final_losses = train_model_b(
        train_rows=train_rows,
        cards=cards,
        device=device,
        main_deck_size=main_deck_size,
        card_feat_matrix=card_feat_matrix,
        vocab_to_idx=vocab_to_idx,
        index_to_key=index_to_key,
        legend_to_idx=legend_to_idx,
        champion_to_idx=champion_to_idx,
        static_features=static_features,
        max_deck=max_deck,
        card_cluster_labels=card_cluster_labels,
        arch_count=arch_count,
        epochs=epochs,
        progress_callback=progress_callback,
        total_steps=total_steps,
        step_offset=step,
    )
    step = total_steps - 3

    # -- Evaluate ------------------------------------------------------------
    _emit_progress(progress_callback, stage="evaluate", step=step, total_steps=total_steps,
                   message="Evaluating Model B on held-out decks.")

    synthetic_config = _build_synthetic_collection_config(cards, synthetic_collection_config)
    evaluation = evaluate_model_b(
        model=model,
        valid_rows=valid_rows,
        train_rows=train_rows,
        vocab_to_idx=vocab_to_idx,
        index_to_key=index_to_key,
        card_feat_matrix=card_feat_matrix,
        legend_to_idx=legend_to_idx,
        champion_to_idx=champion_to_idx,
        cards=cards,
        static_features=static_features,
        main_deck_size=main_deck_size,
        max_deck=max_deck,
        device=device,
        card_cluster_labels=card_cluster_labels,
        arch_count=arch_count,
        synthetic_config=synthetic_config,
    )
    step += 1

    # -- Build metadata structures -------------------------------------------
    shell_profiles = _build_shell_profiles(all_rows, cards)
    archetype_profiles = _build_archetype_profiles(all_rows, cards)
    deck_profiles = _build_deck_profiles(all_rows)
    card_freq_by_legend = _build_card_freq_by_legend(train_rows, vocab_to_idx)
    static_features_serializable = _static_features_as_dict(static_features)

    # -- Save generator_b.pt -------------------------------------------------
    pt_path = out_dir / "generator_b.pt"
    card_feat_tensor = torch.from_numpy(card_feat_matrix)
    torch.save({
        "modelVersion": "B-1.0",
        "vocabSize": V,
        "cardFeatDim": card_feat_matrix.shape[1],
        "dModel": _B_D_MODEL,
        "nHeads": _B_N_HEADS,
        "nLayers": _B_N_LAYERS,
        "ffnDim": _B_FFN_DIM,
        "maxDeck": max_deck,
        "legendCount": len(legend_to_idx),
        "championCount": len(champion_to_idx),
        "legendToIdx": legend_to_idx,
        "championToIdx": champion_to_idx,
        "vocabToIdx": vocab_to_idx,
        "indexToKey": index_to_key,
        "cardFeatMatrix": card_feat_tensor,
        "mainDeckSize": main_deck_size,
        "cardFreqByLegend": card_freq_by_legend,
        "cardClusterLabels": torch.from_numpy(card_cluster_labels),
        "archCount": arch_count,
        "stateDict": model.state_dict(),
        "trainingEpochs": epochs,
        "finalBceLoss": final_losses.get("bce", 0.0),
        "finalBprLoss": final_losses.get("bpr", 0.0),
        "finalMaskLoss": final_losses.get("mask", 0.0),
        "torchDevice": str(device),
    }, pt_path)

    # -- Save model_b_metadata.json ------------------------------------------
    now_iso = datetime.now(timezone.utc).isoformat()
    metadata = {
        "modelVersion": "B-1.0",
        "trainedAt": now_iso,
        "vocabSize": V,
        "trainingDeckCount": len(train_rows),
        "validationDeckCount": len(valid_rows),
        "epochs": epochs,
        "device": str(device),
        "evaluation": evaluation,
        "finalLosses": final_losses,
        "runtimeVersions": {
            "python": platform.python_version(),
            "numpy": str(np.__version__),
            "sklearn": str(getattr(sklearn, "__version__", "")),
            "torch": str(getattr(torch, "__version__", "")),
        },
        "shellProfiles": shell_profiles,
        "archetypes": archetype_profiles,
        "deckProfiles": deck_profiles[:500],
        "staticFeatures": static_features_serializable,
    }
    meta_path = out_dir / "model_b_metadata.json"
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2)

    # -- Save evaluation_report.json -----------------------------------------
    report = {
        "modelVersion": "B-1.0",
        "trainedAt": now_iso,
        "trainingDeckCount": len(train_rows),
        "validationDeckCount": len(valid_rows),
        "epochs": epochs,
        "device": str(device),
        **evaluation,
        "finalBceLoss": round(final_losses.get("bce", 0.0), 6),
        "finalBprLoss": round(final_losses.get("bpr", 0.0), 6),
        "finalMaskLoss": round(final_losses.get("mask", 0.0), 6),
        "benchmarkComparison": {
            "nextCardTop10Recall_A": 0.563,
            "maskedDeckReconstructionExactCardRecall_A": 0.078,
            "competitiveScoreSpearman_A": 0.794,
            "strictBuildableHitRate_A": 0.548,
            "strictBuildableEmptyRate_A": 0.362,
        },
    }
    report_path = out_dir / "evaluation_report.json"
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    step += 1
    _emit_progress(progress_callback, stage="done", step=total_steps, total_steps=total_steps,
                   message=f"Model B training complete. Artifacts saved to {out_dir}.",
                   extra={"evaluation": evaluation})

    return {
        "ptPath": str(pt_path),
        "metadataPath": str(meta_path),
        "reportPath": str(report_path),
        "evaluation": evaluation,
        "finalLosses": final_losses,
    }
