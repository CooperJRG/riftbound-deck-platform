"""Model B — End-to-End Transformer Deck Recommender.

Architecture:
  CardFeatureEmbedder  — maps card id + 59-dim static features → d_model
  DeckContextEncoder   — Set-Transformer (CLS + cards), shell-conditioned
  CandidateScorerB     — full model: encodes deck, scores candidate via MLP

Inference:
  score_candidates_batch — one Transformer pass + one matmul over full vocab
  generate_deck_b        — beam search using the above scorer
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_B_CARD_FEAT_DIM: int = 91   # cost_oh(11)+domain_oh(6)+type_oh(6)+supertype_oh(3)+is_unique(1)+text_svd(64)
_B_D_MODEL: int = 128
_B_N_HEADS: int = 4
_B_N_LAYERS: int = 3
_B_FFN_DIM: int = 256
_B_DROPOUT: float = 0.25
_B_MAX_DECK: int = 42        # 40 main + CLS slot + 1 buffer
_B_LEGEND_EMB_DIM: int = 24
_B_CHAMP_EMB_DIM: int = 24
_B_SCORE_HIDDEN: int = 128
_B_PAD_IDX: int = 0          # vocabulary index 0 reserved for padding
_B_ARCH_EMB_DIM: int = 24   # archetype embedding dimension (co-occurrence cluster conditioning)


# ---------------------------------------------------------------------------
# Sub-modules
# ---------------------------------------------------------------------------

class _CardFeatureEmbedder(nn.Module):
    """Maps (card_id, static_feat_vec) → d_model embedding."""

    def __init__(self, vocab_size: int, card_feat_dim: int, d_model: int) -> None:
        super().__init__()
        id_dim = 32
        self.card_emb = nn.Embedding(vocab_size + 1, id_dim, padding_idx=_B_PAD_IDX)
        self.static_proj = nn.Linear(card_feat_dim, d_model - id_dim, bias=False)
        self.norm = nn.LayerNorm(d_model)

    def forward(
        self,
        card_ids: torch.Tensor,       # [B, S]
        static_feats: torch.Tensor,   # [B, S, card_feat_dim]
    ) -> torch.Tensor:                # [B, S, d_model]
        id_vecs = self.card_emb(card_ids)                        # [B, S, 32]
        stat_vecs = self.static_proj(static_feats)               # [B, S, d_model-32]
        return self.norm(torch.cat([id_vecs, stat_vecs], dim=-1))


class DeckContextEncoder(nn.Module):
    """Encodes a partial deck (multiset of cards) into a single context vector.

    Input sequence: [CLS, card_1, ..., card_S, <padding>]
    CLS token is conditioned on the shell identity (legend + champion).
    Output: CLS position vector = deck context embedding [B, d_model].
    """

    def __init__(
        self,
        vocab_size: int,
        card_feat_dim: int,
        d_model: int,
        n_heads: int,
        n_layers: int,
        ffn_dim: int,
        legend_count: int,
        champion_count: int,
        max_deck: int,
        dropout: float,
        arch_count: int = 1,
    ) -> None:
        super().__init__()
        self.card_embedder = _CardFeatureEmbedder(vocab_size, card_feat_dim, d_model)
        self.cls_token = nn.Parameter(torch.zeros(1, 1, d_model))
        self.pos_emb = nn.Embedding(max_deck + 1, d_model)   # pos 0 = CLS
        self.legend_emb = nn.Embedding(max(1, legend_count) + 1, _B_LEGEND_EMB_DIM)
        self.champion_emb = nn.Embedding(max(1, champion_count) + 1, _B_CHAMP_EMB_DIM)
        self.arch_emb = nn.Embedding(max(1, arch_count) + 1, _B_ARCH_EMB_DIM, padding_idx=0)
        self.shell_proj = nn.Linear(_B_LEGEND_EMB_DIM + _B_CHAMP_EMB_DIM + _B_ARCH_EMB_DIM, d_model)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=n_heads,
            dim_feedforward=ffn_dim,
            dropout=dropout,
            batch_first=True,
            norm_first=True,   # Pre-norm (more stable for small models)
        )
        self.transformer = nn.TransformerEncoder(
            encoder_layer, num_layers=n_layers, norm=nn.LayerNorm(d_model)
        )
        nn.init.trunc_normal_(self.cls_token, std=0.02)

    def forward(
        self,
        card_ids: torch.Tensor,       # [B, S]
        static_feats: torch.Tensor,   # [B, S, card_feat_dim]
        qty_fracs: torch.Tensor,      # [B, S]  quantity / 3.0
        legend_idx: torch.Tensor,     # [B]
        champion_idx: torch.Tensor,   # [B]
        pad_mask: torch.Tensor,       # [B, S+1]  True = ignore (padding)
        archetype_idx: torch.Tensor,  # [B]  1-based cluster id; 0 = unknown
    ) -> torch.Tensor:                # [B, d_model]
        B, S = card_ids.shape
        device = card_ids.device

        card_vecs = self.card_embedder(card_ids, static_feats)           # [B, S, d]
        card_vecs = card_vecs * (1.0 + qty_fracs.unsqueeze(-1))          # scale by copies

        shell_vec = torch.cat(
            [self.legend_emb(legend_idx), self.champion_emb(champion_idx),
             self.arch_emb(archetype_idx)], dim=-1
        )                                                                 # [B, 72]
        cls = self.cls_token.expand(B, -1, -1) + self.shell_proj(shell_vec).unsqueeze(1)
        # [B, 1, d]

        seq = torch.cat([cls, card_vecs], dim=1)                         # [B, S+1, d]
        positions = torch.arange(S + 1, device=device)
        seq = seq + self.pos_emb(positions)

        out = self.transformer(seq, src_key_padding_mask=pad_mask)       # [B, S+1, d]
        return out[:, 0, :]                                              # CLS [B, d]


class CandidateScorerB(nn.Module):
    """Full Model B: encodes deck via DeckContextEncoder, scores a candidate card.

    Public API:
      forward(...)                    — standard training forward, returns logit [B]
      score_candidates_batch(...)     — efficient inference over all V vocab cards
    """

    def __init__(
        self,
        vocab_size: int,
        card_feat_dim: int,
        d_model: int,
        n_heads: int,
        n_layers: int,
        ffn_dim: int,
        legend_count: int,
        champion_count: int,
        max_deck: int,
        dropout: float,
        score_hidden: int,
        arch_count: int = 1,
    ) -> None:
        super().__init__()
        self.encoder = DeckContextEncoder(
            vocab_size, card_feat_dim, d_model, n_heads, n_layers,
            ffn_dim, legend_count, champion_count, max_deck, dropout, arch_count,
        )
        cand_in_dim = 32 + card_feat_dim     # id_emb(32) + static_feat(59)
        self.cand_id_emb = nn.Embedding(vocab_size + 1, 32, padding_idx=_B_PAD_IDX)
        self.cand_proj = nn.Linear(cand_in_dim, d_model, bias=False)
        self.cand_norm = nn.LayerNorm(d_model)
        self.rem_proj = nn.Linear(1, 16)
        combined_dim = d_model * 2 + 16
        self.score_head = nn.Sequential(
            nn.Linear(combined_dim, score_hidden),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(score_hidden, score_hidden // 2),
            nn.GELU(),
            nn.Linear(score_hidden // 2, 1),
        )

    # -- helpers ---------------------------------------------------------------

    def _encode_deck(
        self,
        card_ids: torch.Tensor,
        static_feats: torch.Tensor,
        qty_fracs: torch.Tensor,
        legend_idx: torch.Tensor,
        champion_idx: torch.Tensor,
        pad_mask: torch.Tensor,
        archetype_idx: torch.Tensor,
    ) -> torch.Tensor:
        return self.encoder(card_ids, static_feats, qty_fracs, legend_idx, champion_idx,
                            pad_mask, archetype_idx)

    def _project_candidate(
        self,
        cand_ids: torch.Tensor,      # [N]
        cand_feats: torch.Tensor,    # [N, 59]
    ) -> torch.Tensor:               # [N, d_model]
        id_vecs = self.cand_id_emb(cand_ids)                    # [N, 32]
        concat = torch.cat([id_vecs, cand_feats], dim=-1)        # [N, 91]
        return self.cand_norm(self.cand_proj(concat))            # [N, d_model]

    def _score_from_parts(
        self,
        cls_vec: torch.Tensor,       # [B, d_model]
        cand_vecs: torch.Tensor,     # [B or V, d_model]
        rem_vec: torch.Tensor,       # [B, 16]  or expanded
    ) -> torch.Tensor:
        combined = torch.cat([cls_vec, cand_vecs, rem_vec], dim=-1)
        return self.score_head(combined).squeeze(-1)

    # -- forward (training) ---------------------------------------------------

    def forward(
        self,
        card_ids: torch.Tensor,       # [B, S]
        static_feats: torch.Tensor,   # [B, S, 59]
        qty_fracs: torch.Tensor,      # [B, S]
        legend_idx: torch.Tensor,     # [B]
        champion_idx: torch.Tensor,   # [B]
        pad_mask: torch.Tensor,       # [B, S+1]
        cand_ids: torch.Tensor,       # [B]
        cand_feats: torch.Tensor,     # [B, 59]
        remaining_frac: torch.Tensor, # [B]
        archetype_idx: torch.Tensor,  # [B]  1-based cluster id; 0 = unknown
    ) -> torch.Tensor:                # logit [B]
        cls = self._encode_deck(card_ids, static_feats, qty_fracs,
                                legend_idx, champion_idx, pad_mask, archetype_idx)
        cand_vecs = self._project_candidate(cand_ids, cand_feats)
        rem = self.rem_proj(remaining_frac.unsqueeze(-1))
        return self._score_from_parts(cls, cand_vecs, rem)

    # -- batch inference (eval / beam search) ---------------------------------

    @torch.inference_mode()
    def score_candidates_batch(
        self,
        card_ids: torch.Tensor,       # [1, S]
        static_feats: torch.Tensor,   # [1, S, 59]
        qty_fracs: torch.Tensor,      # [1, S]
        legend_idx: torch.Tensor,     # [1]
        champion_idx: torch.Tensor,   # [1]
        pad_mask: torch.Tensor,       # [1, S+1]
        remaining_frac: torch.Tensor, # [1]
        archetype_idx: torch.Tensor,  # [1]  1-based cluster id; 0 = unknown
        all_cand_ids: torch.Tensor,   # [V]
        all_cand_feats: torch.Tensor, # [V, 59]
    ) -> torch.Tensor:                # logits [V]
        V = all_cand_ids.shape[0]
        cls = self._encode_deck(card_ids, static_feats, qty_fracs,
                                legend_idx, champion_idx, pad_mask, archetype_idx)  # [1, d]
        cand_vecs = self._project_candidate(all_cand_ids, all_cand_feats)  # [V, d]
        cls_exp = cls.expand(V, -1)                                        # [V, d]
        rem = self.rem_proj(remaining_frac.unsqueeze(-1)).expand(V, -1)    # [V, 16]
        return self._score_from_parts(cls_exp, cand_vecs, rem)             # [V]


# ---------------------------------------------------------------------------
# Archetype inference from partial deck
# ---------------------------------------------------------------------------

def _deck_archetype_idx(
    main_by_key: dict[str, int],
    vocab_to_idx: dict[str, int],
    card_cluster_labels: np.ndarray,  # [V] int64, 0-indexed clusters
) -> int:
    """Return 1-based archetype embedding index (0 = unknown) from deck card set.

    Uses weighted majority vote: each card copy votes for its cluster.
    """
    from collections import Counter
    counts: Counter = Counter()
    for k, v in main_by_key.items():
        idx = vocab_to_idx.get(k, 0)
        if idx > 0 and (idx - 1) < len(card_cluster_labels):
            counts[int(card_cluster_labels[idx - 1])] += int(v)
    if not counts:
        return 0  # unknown — padding_idx
    return counts.most_common(1)[0][0] + 1  # 1-based (0 reserved for unknown)


# ---------------------------------------------------------------------------
# Artifact dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelBArtifact:
    """Runtime bundle for Model B inference."""
    vocab_to_idx: dict[str, int]
    index_to_key: list[str]
    legend_to_idx: dict[str, int]
    champion_to_idx: dict[str, int]
    card_feat_matrix: np.ndarray          # [V, 59] float32
    card_feat_matrix_tensor: torch.Tensor # [V, 59] on device
    all_cand_ids_tensor: torch.Tensor     # [V] long, on device
    main_deck_size: int
    card_freq_by_legend: dict[str, dict[str, float]]
    static_features: dict[str, Any]
    shell_profiles: list[dict[str, Any]]
    archetypes: list[dict[str, Any]]
    deck_profiles: list[dict[str, Any]]
    model_params: dict[str, Any]
    card_cluster_labels: np.ndarray       # [V] int64, 0-indexed cluster per card
    arch_count: int                       # K, number of co-occurrence archetypes


# ---------------------------------------------------------------------------
# Artifact I/O
# ---------------------------------------------------------------------------

def load_model_b_artifact(
    pt_path: Path,
    metadata_path: Path,
    device: torch.device | None = None,
) -> tuple[CandidateScorerB, ModelBArtifact]:
    """Load generator_b.pt + model_b_metadata.json into model + artifact."""
    import json
    if device is None:
        device = torch.device("cpu")

    pt = torch.load(pt_path, map_location="cpu", weights_only=False)
    with open(metadata_path, encoding="utf-8") as fh:
        meta = json.load(fh)

    vocab_size = int(pt["vocabSize"])
    arch_count = int(pt.get("archCount", 1))
    params = {
        "vocab_size": vocab_size,
        "card_feat_dim": int(pt["cardFeatDim"]),
        "d_model": int(pt["dModel"]),
        "n_heads": int(pt["nHeads"]),
        "n_layers": int(pt["nLayers"]),
        "ffn_dim": int(pt["ffnDim"]),
        "legend_count": int(pt["legendCount"]),
        "champion_count": int(pt["championCount"]),
        "max_deck": int(pt["maxDeck"]),
        "dropout": 0.0,   # eval mode — no dropout
        "score_hidden": _B_SCORE_HIDDEN,
        "arch_count": arch_count,
    }
    model = CandidateScorerB(**params)
    model.load_state_dict(pt["stateDict"])
    model.to(device).eval()

    card_feat_matrix = pt["cardFeatMatrix"].numpy().astype(np.float32)
    all_cand_ids = torch.arange(1, vocab_size + 1, dtype=torch.long, device=device)
    card_feat_t = torch.from_numpy(card_feat_matrix).to(device)

    raw_labels = pt.get("cardClusterLabels")
    if raw_labels is not None:
        card_cluster_labels = raw_labels.numpy().astype(np.int64)
    else:
        card_cluster_labels = np.zeros(vocab_size, dtype=np.int64)

    artifact = ModelBArtifact(
        vocab_to_idx=pt["vocabToIdx"],
        index_to_key=pt["indexToKey"],
        legend_to_idx=pt["legendToIdx"],
        champion_to_idx=pt["championToIdx"],
        card_feat_matrix=card_feat_matrix,
        card_feat_matrix_tensor=card_feat_t,
        all_cand_ids_tensor=all_cand_ids,
        main_deck_size=int(pt["mainDeckSize"]),
        card_freq_by_legend=pt.get("cardFreqByLegend", {}),
        static_features=meta.get("staticFeatures", {}),
        shell_profiles=meta.get("shellProfiles", []),
        archetypes=meta.get("archetypes", []),
        deck_profiles=meta.get("deckProfiles", []),
        model_params=params,
        card_cluster_labels=card_cluster_labels,
        arch_count=arch_count,
    )
    return model, artifact


# ---------------------------------------------------------------------------
# Deck → tensor conversion
# ---------------------------------------------------------------------------

def deck_to_tensors(
    main_by_key: dict[str, int],
    vocab_to_idx: dict[str, int],
    card_feat_matrix: np.ndarray,   # [V, 59]
    max_deck: int,
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Convert a partial deck dict to model input tensors (batch size 1).

    Returns:
        card_ids   [1, max_deck]  long
        feats      [1, max_deck, 59]  float32
        qty_fracs  [1, max_deck]  float32
        pad_mask   [1, max_deck+1]  bool (True = pad/ignore)
    """
    card_ids = np.zeros(max_deck, dtype=np.int64)
    feats = np.zeros((max_deck, card_feat_matrix.shape[1]), dtype=np.float32)
    qty_fracs = np.zeros(max_deck, dtype=np.float32)
    pad_mask_cards = np.ones(max_deck, dtype=bool)

    sorted_keys = sorted(main_by_key.keys())
    for pos, key in enumerate(sorted_keys[:max_deck]):
        idx = vocab_to_idx.get(key, 0)
        if idx == 0:
            continue
        card_ids[pos] = idx
        feats[pos] = card_feat_matrix[idx - 1]  # idx is 1-based
        qty_fracs[pos] = min(1.0, main_by_key[key] / 3.0)
        pad_mask_cards[pos] = False

    # CLS slot is never masked → prepend False
    pad_mask = np.concatenate([[False], pad_mask_cards])

    return (
        torch.from_numpy(card_ids).unsqueeze(0).to(device),
        torch.from_numpy(feats).unsqueeze(0).to(device),
        torch.from_numpy(qty_fracs).unsqueeze(0).to(device),
        torch.from_numpy(pad_mask).unsqueeze(0).to(device),
    )


# ---------------------------------------------------------------------------
# Beam search inference
# ---------------------------------------------------------------------------

_B_BEAM_WIDTH: int = 16
_B_EXPANSION_LIMIT: int = 8
_B_POOL_LIMIT: int = 64


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _can_add_card_b(
    key: str,
    partial: dict[str, int],
    static_features: dict[str, Any],
    legend_domains: tuple[str, ...],
    main_deck_size: int,
) -> bool:
    """Return True if `key` can legally be added to the partial deck."""
    sf = static_features.get(key)
    if sf is None:
        return False
    # Domain check: card domains must be a subset of legend domains (or empty)
    if sf.get("domains") and legend_domains:
        if not set(sf["domains"]).issubset(set(legend_domains)):
            return False
    # Copy-limit check
    max_copies = 1 if sf.get("isUnique") or sf.get("superType") in ("Champion", "Signature") else 3
    current = partial.get(key, 0)
    if current >= max_copies:
        return False
    # Deck size check
    if sum(partial.values()) >= main_deck_size:
        return False
    return True


def _prior_score(
    key: str,
    legend_title: str,
    card_freq_by_legend: dict[str, dict[str, float]],
) -> float:
    freq_map = card_freq_by_legend.get(legend_title) or card_freq_by_legend.get("__all__") or {}
    return float(freq_map.get(key, 0.0))


def generate_deck_b(
    *,
    legend_title: str,
    champion_title: str,
    model: CandidateScorerB,
    artifact: ModelBArtifact,
    collection_by_key: dict[str, int] | None = None,
    strict_buildable: bool = False,
    beam_width: int = _B_BEAM_WIDTH,
    expansion_limit: int = _B_EXPANSION_LIMIT,
    pool_limit: int = _B_POOL_LIMIT,
) -> tuple[dict[str, int] | None, str]:
    """Beam search that produces a main-deck dict using Model B scoring.

    Returns (main_by_key, fallback_reason). fallback_reason is "" on success.
    """
    device = next(model.parameters()).device
    vocab_to_idx = artifact.vocab_to_idx
    index_to_key = artifact.index_to_key
    card_feat_t = artifact.card_feat_matrix_tensor
    all_cand_ids = artifact.all_cand_ids_tensor
    static_features = artifact.static_features
    main_deck_size = artifact.main_deck_size
    legend_to_idx = artifact.legend_to_idx
    champion_to_idx = artifact.champion_to_idx
    freq_by_legend = artifact.card_freq_by_legend

    legend_idx_val = legend_to_idx.get(legend_title, 0)
    champion_idx_val = champion_to_idx.get(champion_title, 0)
    legend_idx_t = torch.tensor([legend_idx_val], dtype=torch.long, device=device)
    champion_idx_t = torch.tensor([champion_idx_val], dtype=torch.long, device=device)
    card_cluster_labels = getattr(artifact, "card_cluster_labels", np.zeros(1, dtype=np.int64))

    # Infer legend domains from static_features
    legend_domains: tuple[str, ...] = tuple()
    for sf in static_features.values():
        if isinstance(sf, dict) and sf.get("title") == legend_title:
            legend_domains = tuple(sf.get("domains") or ())
            break

    # Seed beam with champion if known
    champion_key = None
    for key, sf in static_features.items():
        if isinstance(sf, dict) and sf.get("title") == champion_title and sf.get("superType") == "Champion":
            champion_key = key
            break

    initial: dict[str, int] = {}
    if champion_key and champion_key in vocab_to_idx:
        initial = {champion_key: 1}

    # Beam: list of (partial_deck, cumulative_score)
    beam: list[tuple[dict[str, int], float]] = [(initial, 0.0)]
    fallback_reason = ""

    for _step in range(main_deck_size):
        if not beam:
            break
        next_beam: list[tuple[dict[str, int], float]] = []

        for partial, cum_score in beam:
            remaining = main_deck_size - sum(partial.values())
            if remaining <= 0:
                next_beam.append((partial, cum_score))
                continue

            # Build deck tensors
            card_ids_t, feats_t, qty_t, pad_mask_t = deck_to_tensors(
                partial, vocab_to_idx, artifact.card_feat_matrix, artifact.model_params["max_deck"], device
            )
            rem_frac_t = torch.tensor([remaining / main_deck_size], dtype=torch.float32, device=device)
            arch_idx_val = _deck_archetype_idx(partial, vocab_to_idx, card_cluster_labels)
            arch_idx_t = torch.tensor([arch_idx_val], dtype=torch.long, device=device)

            # Score all vocab cards
            logits = model.score_candidates_batch(
                card_ids_t, feats_t, qty_t, legend_idx_t, champion_idx_t,
                pad_mask_t, rem_frac_t, arch_idx_t, all_cand_ids, card_feat_t,
            ).cpu().numpy()

            # Build scored pool, filtering illegal / non-buildable
            scored: list[tuple[float, str]] = []
            for vocab_pos, logit in enumerate(logits):
                key = index_to_key[vocab_pos] if vocab_pos < len(index_to_key) else ""
                if not key:
                    continue
                if not _can_add_card_b(key, partial, static_features, legend_domains, main_deck_size):
                    continue
                if strict_buildable and collection_by_key is not None:
                    if collection_by_key.get(key, 0) <= partial.get(key, 0):
                        continue
                prior = _prior_score(key, legend_title, freq_by_legend)
                score = 0.75 * _sigmoid(float(logit)) + 0.25 * min(1.0, prior)
                scored.append((score, key))

            if not scored:
                fallback_reason = "no_legal_candidates"
                next_beam.append((partial, cum_score))
                continue

            scored.sort(reverse=True)
            top_pool = scored[:pool_limit]

            for rank, (card_score, key) in enumerate(top_pool[:expansion_limit]):
                new_partial = dict(partial)
                new_partial[key] = new_partial.get(key, 0) + 1
                next_beam.append((new_partial, cum_score + card_score))

        # Dedup by deck signature and keep top beam_width
        seen: set[str] = set()
        deduped: list[tuple[dict[str, int], float]] = []
        for partial, score in sorted(next_beam, key=lambda x: x[1], reverse=True):
            sig = "|".join(f"{k}:{v}" for k, v in sorted(partial.items()))
            if sig not in seen:
                seen.add(sig)
                deduped.append((partial, score))
            if len(deduped) >= beam_width:
                break
        beam = deduped

    # Find first complete valid deck from beam
    for partial, _ in beam:
        if sum(partial.values()) == main_deck_size:
            return partial, ""

    # Greedy repair fallback
    if beam:
        best_partial = dict(beam[0][0])
        rng = random.Random(42)
        attempts = 0
        while sum(best_partial.values()) < main_deck_size and attempts < main_deck_size * 3:
            attempts += 1
            remaining = main_deck_size - sum(best_partial.values())
            card_ids_t, feats_t, qty_t, pad_mask_t = deck_to_tensors(
                best_partial, vocab_to_idx, artifact.card_feat_matrix,
                artifact.model_params["max_deck"], device,
            )
            rem_frac_t = torch.tensor([remaining / main_deck_size], dtype=torch.float32, device=device)
            arch_idx_val2 = _deck_archetype_idx(best_partial, vocab_to_idx, card_cluster_labels)
            arch_idx_t2 = torch.tensor([arch_idx_val2], dtype=torch.long, device=device)
            logits = model.score_candidates_batch(
                card_ids_t, feats_t, qty_t, legend_idx_t, champion_idx_t,
                pad_mask_t, rem_frac_t, arch_idx_t2, all_cand_ids, card_feat_t,
            ).cpu().numpy()

            candidates = [
                (float(logits[i]), index_to_key[i])
                for i in range(min(len(index_to_key), len(logits)))
                if index_to_key[i]
                and _can_add_card_b(index_to_key[i], best_partial, static_features,
                                    legend_domains, main_deck_size)
                and (not strict_buildable or collection_by_key is None
                     or collection_by_key.get(index_to_key[i], 0) > best_partial.get(index_to_key[i], 0))
            ]
            if not candidates:
                break
            candidates.sort(reverse=True)
            best_partial[candidates[0][1]] = best_partial.get(candidates[0][1], 0) + 1

        if sum(best_partial.values()) == main_deck_size:
            return best_partial, "greedy_repair"

    return None, fallback_reason or "beam_failed"
