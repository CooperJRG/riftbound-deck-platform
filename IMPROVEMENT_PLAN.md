# Riftbound Deck Auto-Builder — ML Improvement Plan

_Generated 2026-03-04 based on full audit of `riftbound-deck-platform-v2`._

---

## 1. Codebase Audit — Module-by-Module

### `app/domain/auto_builder_types.py`
**Purpose:** Frozen dataclasses that are the shared vocabulary for the whole pipeline — `TrainingDeckRow`, `ShellProfile`, `ArchetypeProfile`, `WinConditionComponent`, `SynergyCluster`, `GenerationPlan`, `CandidateDeck`, `LoadedAutoBuilderBundle`.

**Notes:** Clean, no smells. The only flag is that `LoadedAutoBuilderBundle` carries `card_embeddings` as `dict[str, list[float]]` (not `np.ndarray`), forcing a conversion on every hot path in generation. Minor performance concern at scale.

---

### `app/domain/auto_builder_features.py`
**Purpose:** All pure feature-engineering functions: tokenizing card text, building vocab, constructing the TF-IDF-dampened deck matrix, per-deck feature vectors (cost curve, domain balance, type ratios, special counts), mean-embedding aggregation, co-occurrence metrics, and sample-weight computation.

**Code Smells:**
- `sample_weight_for_entry`: The age half-life is hard-coded at 120 days (`age_factor = 1/(1 + age/120)`). This means decks from ~8 months ago retain 50% weight. For a competitive TCG where metas shift quarterly, this is too slow to decay.
- `build_card_text_features` computes a 1024-dim TF-IDF matrix for every card in the vocab, but this output (`CardTextFeatures`) is built, stored in the bundle, and **never used** in the MoE state vector, replacement features, or generation pool — it is dead weight at inference time.
- `deck_domain_balance` and `deck_cost_curve` iterate over `main_by_key` twice instead of once.
- `pearson_rank_correlation` computes rank correlation but is never called anywhere in the training pipeline — possibly leftover code.

---

### `app/domain/auto_builder_training.py`
**Purpose:** The full ML training pipeline: Item2Vec card embeddings, NMF win-condition decomposition, spectral synergy clustering, shell/archetype profile construction, MoE generator training, replacement model training, final artifact assembly.

**Architecture — Key Facts:**
- **Item2Vec (`_Item2VecModel`):** Skip-gram with negative sampling. Positive pairs are random co-occurrences within a deck (up to 8 per card). Negatives are uniform random. 64-dim embeddings, Adam lr=0.01, weighted by `sample_weight`.
- **Win Conditions (NMF):** Sklearn `NMF(init="nndsvda")` on TF-IDF-dampened deck-card matrix. Component count auto-selected via grid search (candidate set from `_NMF_CANDIDATE_GRID`).
- **Synergy Clusters (Spectral Clustering):** Affinity = 0.7 × PMI + 0.3 × cosine_similarity of Item2Vec embeddings. Cluster count auto-selected via grid search.
- **MoE Generator (`_MoECandidateScorer`):** 8 experts, each a 3-layer MLP (→128→128→1). Gate input: `state_vec + legend_emb(16) + champion_emb(16)`. Expert input: `state_vec + candidate_emb(64) + legend_emb + champion_emb`. Routing: **soft** (full softmax over all 8 experts, weighted sum). Training: binary cross-entropy (1 = card belongs in deck, 0 = random negative).
- **Replacement Model:** `HistGradientBoostingRegressor` on 8 hand-crafted features (cosine sim, type match, domain match, cluster match, cost delta, might delta, win-condition frequency, availability).
- **State Vector:** `mean_emb(64) + cost_curve(8) + domain_balance(6) + type_ratios(3) + special_counts(3) + win_vec(dynamic) + cluster_vec(dynamic) + remaining_slots(1)`.

**Code Smells / Bugs:**
- `_moe_training_samples` samples up to 10 target keys per deck from the _first_ 10 keys of `main_by_key.keys()`. Python dict insertion order may produce a systematic bias toward certain card types (e.g., cards imported first from JSON). The training signal is uniform across all deck positions — no curriculum that prioritizes anchor cards first.
- **All 8 experts fire on every forward pass** (soft routing). This is not truly sparse MoE — all parameters are always active, negating the primary benefit of MoE (compute efficiency + specialization pressure). There is **no load-balancing loss**.
- Negative sampling is uniform over the full card vocabulary. Cards from other legend domains (which are hard-constrained to be illegal for a given legend) are included as negatives. The model wastes capacity on obviously-invalid cards.
- `_build_synergy_affinity` has an O(N²) inner Python loop over `vocab_size`. For a card set with 500+ playable cards this produces a 500×500 matrix computed in pure Python. This is the single biggest training bottleneck.
- `train/val split` uses `_hash_split_key` (FNV hash of `source:deck_id:leader_title`) with a fixed 82/18 ratio. There is **no temporal ordering** — decks from old metas are mixed into validation with new-meta decks, potentially causing misleading eval scores.
- `text_features` (TF-IDF) is built and stored but not wired into the MoE state vector.

---

### `app/domain/auto_builder_generation.py`
**Purpose:** Inference-time generation: building `GenerationPlan` from the bundle, beam search (`generate_pure_candidate`), seed adaptation (`adapt_seed_candidate`), greedy completion, candidate scoring with the MoE, support card selection (runes/battlefields), and replacement suggestion ranking.

**Code Smells:**
- `_candidate_card_pool` is capped at `_PURE_POOL_LIMIT = 48` candidates before scoring. The pool is assembled from archetype prototype, win-condition frequency, synergy cluster membership, seed deck cards, collection ownership, and embedding neighbors — but ordered by how the pool `set` iterates (arbitrary). Cards ranked 49+ in any reasonable ordering are systematically excluded.
- `generate_pure_candidate` beam search has `_PURE_EXPANSION_LIMIT = 6` branches per step. At 40 card slots, the beam can collapse to a single path very early. The beam-width of 8 is also very small relative to deck size.
- `_score_candidate_keys` returns `sigmoid(logit) + prior`, mixing a probability (0-1) with an unnormalized prior score. This conflates two scales and makes the prior weight implicit and untunable.
- The greedy fallback `_complete_main_greedily` is invoked when `adapt_seed_candidate` needs to fill missing slots, but it re-instantiates the pool and scoring on every slot independently — no forward-looking signal.

---

### `app/domain/auto_builder_scoring.py`
**Purpose:** Post-generation scoring and ranking of candidate decks.

**Notes:** The `candidate_score` weights are hardcoded magic numbers (0.35 competitive + 0.20 win_condition_match + 0.20 synergy_coverage + 0.15 legality_margin + 0.10 curve_balance). These have never been fit to actual user preference or outcome data. `curve_balance_from_curve` uses a hardcoded "ideal" curve `[0.08, 0.16, 0.18, 0.18, 0.16, 0.12, 0.08, 0.04]` — a bell curve that may not reflect any real archetype.

---

### `app/domain/validator.py`
**Purpose:** Hard-constraint deck validation against `FormatRules`. Checks legend/champion presence, card type legality, domain identity, copy limits, deck sizes.

**Notes:** Solid and well-structured. Domain identity enforcement (`_subset_of_identity`) is the primary legality gate. Unique card limit (1 copy) vs. non-unique (3 copies) is correctly enforced via `is_unique` flag. Validation is used **post-generation** as a filter, not as a constraint **during** generation.

---

### `app/infra/meta_repo.py`
**Purpose:** Loads and normalizes decks from the meta index JSON. Parses deck components (main/runes/battlefields), infers champion from main deck if not specified, normalizes card titles against the catalog.

**Notes:** No temporal partitioning or ban-list filtering. All decks in the index file are loaded regardless of meta period.

---

### `scripts/train_auto_builder.py` / `scripts/benchmark_auto_builder.py`
Both are thin wrappers that redirect to the workspace-level scripts directory via `runpy.run_path`. The actual training entry point appears to be in the workspace root's `scripts/` folder (outside this platform directory). This indirection is confusing and the real script was not found in the platform repo.

---

## 2. Architecture Analysis

### Expert Specialization
Experts are defined as 8 identical 3-layer MLPs (128→128→1). There is **no explicit specialization** — the gate is expected to route specific contexts to specific experts through learning alone. Without load-balancing pressure, experts tend to converge to similar functions. Expert specialization could be made explicit by:
- Routing by shell/legend identity
- Routing by win-condition component
- Routing by mana-curve segment (early/mid/late)

### Gating / Routing
The gate is a 2-layer MLP producing a softmax distribution over 8 experts. **Full soft routing** — every expert processes every input. This is soft MoE, not sparse MoE. The gate inputs are `state_vec + legend_emb(16) + champion_emb(16)`. Legend and champion identity are the primary routing signals, which is reasonable. However, there is no `load_balancing_loss` term, so in practice the gate may collapse to routing all inputs to 1-2 dominant experts.

### Deck Validity Enforcement
Validity is enforced as a **hard post-generation filter** via `validate_deck()`. During generation, `_can_add_card()` enforces domain identity and copy limits at each step. This is correct — hard constraints are applied greedy-step-by-step. The validator is comprehensive and uses `FormatRules` profiles. No soft-penalty approach is used (which would be an alternative but inferior strategy for format rules that are binary).

### Training Objective
- **Item2Vec:** Skip-gram negative sampling — card-level co-occurrence learning. No win-rate signal.
- **MoE Generator:** Binary cross-entropy: "given this partial deck state, should card X be added?" Negative examples are uniform random cards. This is a **masked-card prediction** objective, similar to BERT's masked language model.
- **Replacement model:** Supervised binary (same-card = 1, random card = 0), fit with GBT. Pure card-feature similarity, no deck-context.
- **No win-rate, tournament-result, or matchup signal anywhere in training.**
- The `meta_score` field (from data sources) influences sample weighting but is not a direct training target.

### Card Embeddings
- **Source:** Item2Vec (skip-gram on deck co-occurrences), 64 dimensions.
- **Features encoded:** Co-occurrence patterns within competitive decklists, modulated by sample weight (recency and source quality). Does **not** encode card text, mana cost, or mechanics directly.
- **Supplementary:** TF-IDF 1024-dim text features are computed but not used in embeddings or the generator state.

---

## 3. Data Pipeline Review

### Data Sources
Decks are sourced from: `riot-bologna` (1.30×), `riot-organized-play` (1.35×), `mobalytics-tournaments` (1.10×), `riftdecks-tournaments` (1.15×), `riftboundgg` (1.00×), `piltoverarchive` (0.90×). The meta index is a pre-built JSON file — there is no real-time ingestion pipeline visible in this repo.

### Class Imbalance
- **Shell imbalance:** Popular legend+champion combinations will have 10-100× more decks than niche shells. The archetype detection requires `_ARCHETYPE_MIN_DECKS = 4` for a cluster to be registered, meaning rare archetypes below this threshold are silently excluded.
- **Card imbalance:** Core staples appearing in most decks will have very high co-occurrence frequency and dominate Item2Vec training pairs. Niche tech cards appear in few decks and will have noisy embeddings.
- Sample weighting (`sample_weight_for_entry`) partially mitigates this by upweighting tournament data, but it doesn't address raw count imbalance.

### Temporal Leakage
- The age weight decays with a **120-day half-life** — too slow for a quarterly competitive meta.
- **No hard temporal cutoff**: Data from old metas is included in validation. If a deck's card pool was banned and then the model validates on a deck from before the ban, `meta_score` could be misleadingly high for illegal post-ban configurations.
- Train/val split is by hash (random), not by date. A deck from 2 years ago could be in the validation set while recent variants of it are in training.

### New Card / Meta Shift Handling
- None. There is no mechanism to detect new set releases or flag cards for re-embedding. A new set's cards will have zero embeddings until a full retrain.
- The `resolution_mode = "reuse"` feature (fingerprinting training corpus) accelerates retraining on identical data, but does not handle incremental updates.

---

## 4. Evaluation & Metrics

### Existing Metrics

| Metric | What it measures |
|--------|-----------------|
| `nextCardTop10Recall` | Is the held-out card in the top-10 predictions? |
| `maskedDeckReconstructionExactCardRecall` | Same, exact single-card reconstruction |
| `winConditionClusterSilhouette` | How well NMF components separate decks (silhouette score) |
| `competitiveScoreSpearman` | Rank correlation of model's competitive score with meta_score |
| `collectionFirstRecommendationHitRate` | Does model recommend correct shell given a mixed collection? |
| `strictBuildableRecommendationHitRate` | Same but with full collection requirement |
| `strictBuildableCandidateCountP50/P90` | Number of fully-buildable candidates in results |
| `strictBuildableEmptyResultRate` | Rate of zero-result generation |

### Blind Spots

1. **No deck-validity-rate metric.** What % of generated decks pass `validate_deck()`? This is the most basic quality gate but is not reported in the evaluation.
2. **No generation diversity metric.** Are all generated decks near-identical? Self-BLEU or mean pairwise Jaccard distance across generated decks is absent.
3. **No holdout-archetype test.** The eval doesn't check whether the model generates reasonable decks for a shell it has only seen rarely (generalization test).
4. **`competitiveScoreSpearman = 0.0`** in smoke-env artifact — the rank correlation is zero, meaning the model's competitive score ranking is uncorrelated with actual meta scores. (May be a trivial dataset artifact, but this is a critical signal to track.)
5. **No win-rate proxy eval.** No synthetic matchup simulation or tournament-outcome correlation.
6. **Expert utilization is never measured.** Without this, gate collapse goes undetected.
7. **Archetype precision/recall** against a hand-labeled ground truth is absent.
8. **Inference latency** is not tracked.

---

## 5. Prioritized Improvement Plan

> Priority: **P1** = critical / highest leverage, **P2** = high value, **P3** = useful but non-urgent.
> Complexity: **S** = small (<1 day), **M** = medium (2-5 days), **L** = large (>1 week).

---

### P1-A — Fix Synergy Affinity Computation (O(N²) Vectorize)
**What:** Replace the pure-Python double loop in `_build_synergy_affinity` with vectorized NumPy operations: compute the weighted co-occurrence matrix as `(presence.T @ (presence * weights[:, None])) / total_weight`, then PMI from that.

**Why:** The current O(N²) Python loop is the training bottleneck for any realistically-sized card set (500+ cards). Vectorizing gives a 100-500× speedup and unblocks faster training iteration.

**Complexity:** S

**Dependencies:** None.

---

### P1-B — Eliminate Dead Code: Wire TF-IDF Text Features Into the MoE State
**What:** Include the per-card TF-IDF embedding as a supplementary feature in `_state_feature_vector`. Specifically, add a mean-aggregated TF-IDF component (projected to e.g. 32 dims via PCA or a small learned linear layer) alongside the Item2Vec mean embedding. Remove the dead `CardTextFeatures` computation if not used.

**Why:** Card effect text encodes mechanics (keywords, triggered abilities, synergy language) that Item2Vec co-occurrence cannot learn well for new or niche cards. Currently this data is computed at training time but discarded. Using it would improve recommendations for cards with few training examples.

**Complexity:** M

**Dependencies:** P1-A (faster training enables iteration).

---

### P1-C — Replace Soft MoE With Top-2 Sparse Routing + Load Balancing Loss
**What:** Change the gate to select the top-2 experts by gate score and only run those two. Add an auxiliary load-balancing loss term (following the Switch Transformer formulation: `loss += alpha * sum(fraction_tokens_per_expert * mean_gate_score_per_expert)`) weighted at ~0.01.

**Why:** Current soft routing means all 8 experts fire on every sample. Experts cannot specialize because they all receive all gradients. Without load-balancing loss, the gate collapses to 1-2 dominant experts. Sparse top-2 routing reduces compute, forces specialization, and the load-balancing loss prevents collapse.

**Complexity:** M

**Dependencies:** None.

---

### P1-D — Temporal Train/Val Split
**What:** Replace `_hash_split_key` with a date-ordered split: sort decks by `age_days` (ascending age = most recent), use the most recent 18% as validation. Add a minimum temporal gap parameter (e.g., `val_cutoff_days = 30`) so that no validation deck is more recent than 30 days relative to the most recent training deck.

**Why:** Current hash-based split allows old-meta decks in validation and new-meta decks in training for the same archetype. This inflates eval scores and hides temporal generalization failures. For a TCG where metas shift quarterly, temporal evaluation is the most meaningful quality signal.

**Complexity:** S

**Dependencies:** None.

---

### P1-E — Domain-Filtered Negative Sampling
**What:** In `_moe_training_samples`, instead of sampling negatives uniformly from all cards, sample negatives only from cards that are **legal** for the current legend's domain. Hard-filtered negatives (wrong domain) give zero signal since `_can_add_card()` already removes them at inference time.

**Why:** Uniform negatives waste ≥50% of negative samples on domain-illegal cards. Focusing negatives on legally-eligible-but-wrong cards makes the discrimination task harder and teaches the model what actually matters for a given archetype.

**Complexity:** S

**Dependencies:** None.

---

### P2-A — Add Deck Validity Rate and Generation Diversity Metrics
**What:** After generating N candidate decks from a held-out plan, compute:
1. `validity_rate`: % of generated decks passing `validate_deck()`.
2. `mean_pairwise_jaccard`: Average weighted Jaccard distance across all pairs of generated decks for the same plan (measures diversity).
3. `top1_expert_fraction`: Fraction of MoE forward passes where one expert dominates (gate score >0.8) — load-balance indicator.

Report these in `evaluation_report.json`.

**Why:** The current eval suite has no check on whether generated decks are valid or diverse. Both failures are invisible in current metrics.

**Complexity:** S

**Dependencies:** None.

---

### P2-B — Archetype-Conditioned Expert Routing
**What:** In `_MoECandidateScorer`, add a third embedding lookup: `archetype_emb = nn.Embedding(max_archetypes, 16)`. Include `archetype_emb` in the gate input alongside `legend_emb` and `champion_emb`. At training time, pass the archetype index (from `row_to_archetype_id`). At inference time, pass the plan's `archetype_id` index.

**Why:** The current gate routes on legend+champion, which is a coarse signal. Two archetypes with the same legend/champion pair (e.g., aggressive vs. control variants) should route to different experts. Archetype-conditioned routing provides finer-grained specialization.

**Complexity:** M

**Dependencies:** P1-C (load-balancing loss should be in place before adding routing complexity).

---

### P2-C — Shorten Age Decay Half-Life and Add Hard Temporal Cutoff
**What:** In `sample_weight_for_entry`, reduce the age half-life from 120 days to 45 days: `age_factor = 1/(1 + age/45.0)`. Add an optional `max_age_days` hard cutoff parameter (default `None`, configurable per training run) that excludes decks older than the cutoff entirely.

**Why:** A 120-day half-life means the May meta still has 50% influence in September. Competitive TCGs shift significantly on that timescale. Reducing to 45 days focuses training on the current meta while retaining enough signal from recent sets.

**Complexity:** S

**Dependencies:** P1-D (temporal split should be consistent with weight decay).

---

### P2-D — Meta-Score as a Training Target (Surrogate Competitive Model)
**What:** Train a separate `surrogateModel` (`HistGradientBoostingRegressor` or small MLP) that predicts `meta_score` from the deck vector (`deck_vector()` output). Use the surrogate's predicted score to modulate the MoE training signal: weight positive examples for a target card by `sigmoid(surrogate_score(deck_with_card) - surrogate_score(partial_deck))`. This is a weak form of reward shaping — the model learns to prefer cards that increase predicted competitive strength.

**Why:** Currently the MoE is trained only on "is this card in the deck?" — a population-frequency signal. It cannot distinguish between a card that appears in decks because it's competitively necessary vs. because it's a budget substitute. Incorporating meta-score reward into training pushes the model toward competitive card choices.

**Complexity:** M

**Dependencies:** The `surrogateModel` training already exists in the codebase (it's called in the bundle as `surrogateModel`). The integration into MoE training weighting is new.

---

### P2-E — Candidate Pool Scoring: Decouple Prior and Model Score
**What:** In `_score_candidate_keys`, return `sigmoid(logit)` and `prior` as separate fields. In `generate_pure_candidate`, use a weighted combination `alpha * sigmoid(logit) + (1 - alpha) * prior` where `alpha` is a tunable inference parameter (default 0.7). Expose `alpha` as a generation parameter in the API.

**Why:** The current `sigmoid(logit) + prior` is an unnormalized sum that is hard to reason about. The prior (archetype frequency + cluster bonus + ownership bonus) is on a different scale than the model probability. Keeping them separate and linearly blending with a tunable weight gives interpretability and allows A/B testing prior vs. model emphasis.

**Complexity:** S

**Dependencies:** None.

---

### P2-F — Curriculum Learning: Anchor-First MoE Training
**What:** In `_moe_training_samples`, sort target cards by `weighted_presence` (how often a card appears across cluster decks, from the archetype profiling). Train the MoE for the first half of epochs using only core cards (high presence ≥ 0.65) as positive targets, and for the second half include flex cards (presence 0.20-0.65). This is a simple difficulty curriculum.

**Why:** The current sampling is uniform across all cards including 1-of tech cards. Training on low-frequency cards early introduces noisy signal. Anchoring on high-frequency core cards first gives the model a stable foundation before learning flex choices.

**Complexity:** M

**Dependencies:** Requires archetype profile data to be available before MoE training, which it currently is (`_build_shell_and_archetype_profiles` runs at step 7 before MoE training at step 8). The pipeline ordering already supports this.

---

### P2-G — Beam Width and Pool Scaling for Production
**What:** Increase `_PURE_BEAM_WIDTH` from 8 to 16 and `_PURE_EXPANSION_LIMIT` from 6 to 8. Add a fallback beam-repair step: if the beam collapses (no candidate reaches target deck size), restart from the top-3 archetype prototype cards as seeds and re-run greedy completion.

**Why:** Current beam width of 8 with 6 expansion branches per step at 40 card slots produces a very narrow search. Beam collapse (zero valid completions) is a real failure mode, especially for strict-buildable mode. Wider beams improve recall of valid decks. The beam repair adds robustness.

**Complexity:** S

**Dependencies:** None.

---

### P3-A — Card Text Embedding via Learned Projection
**What:** Instead of raw TF-IDF text features, train a small MLP that projects the TF-IDF vector (1024-dim) to 32 dims as part of the Item2Vec training: the final card embedding would be `Item2Vec(64) + Proj(TF-IDF(32)) = 96 dims`. Backpropagate through the projection during Item2Vec training.

**Why:** This gives the card embedding access to mechanic keywords (effect text) in addition to co-occurrence. Especially valuable for newly-released cards with few deck examples — their text embedding provides prior signal even with sparse co-occurrence data.

**Complexity:** L

**Dependencies:** P1-B (ensuring TF-IDF is properly wired up first).

---

### P3-B — Synergy Graph Embeddings (Graph Neural Network)
**What:** Model the card synergy graph explicitly: cards are nodes, edge weight = affinity score (from `_build_synergy_affinity`). Run 1-2 layers of message passing (Graph Attention Network or simple mean aggregation of neighbor embeddings) to produce context-aware card embeddings that incorporate neighborhood structure.

**Why:** Item2Vec embeddings represent average co-occurrence across all decks. A GNN over the synergy graph would allow a card's embedding to reflect its actual neighborhood in the synergy space — capturing multi-hop synergy chains that Item2Vec cannot (e.g., card A enables card B which enables card C).

**Complexity:** L

**Dependencies:** P1-A (need fast affinity matrix computation as prerequisite).

---

### P3-C — Matchup-Aware Meta Conditioning
**What:** If matchup data becomes available (tournament bracket results, win/loss records), add a `matchup_condition_vector` to the generation plan: a weighted average of opponent-archetype embeddings weighted by win-probability. Condition the MoE gate on this vector to generate meta-relevant tech choices.

**Why:** The current system treats all opponents equally. In a real meta, optimal card selection depends on the expected field (e.g., anti-aggro tech vs. anti-combo tech). Matchup conditioning enables contextual deck construction.

**Complexity:** L

**Dependencies:** Requires external matchup data source (not currently ingested). Would require data pipeline additions beyond this codebase.

---

### P3-D — Per-Format Expert Banks
**What:** If multi-format support is added (constructed + skirmish + limited), maintain separate expert banks per format rather than retraining from scratch. Share the card embeddings (Item2Vec) across formats but use format-specific MoE expert weights. Gate input includes a format embedding.

**Why:** Different formats have fundamentally different deck-building constraints (deck sizes, copy limits, card pools). Currently the system trains one model per format profile. Shared embeddings + format-specific experts is more parameter-efficient and allows cross-format transfer learning.

**Complexity:** L

**Dependencies:** P1-C (sparse routing should be in place before multiplying expert banks).

---

### P3-E — Inference-Time MCTS for Deck Construction
**What:** Replace the beam search in `generate_pure_candidate` with a Monte Carlo Tree Search: each tree node is a partial deck state, each edge is adding a card, and rollouts complete the deck greedily. The MCTS backpropagation signal is the `candidate_score` of the completed deck.

**Why:** Beam search is myopic — it commits to expansions greedily and prunes paths that might lead to better complete decks. MCTS explores more of the combination space and can recover from early suboptimal choices. For 40-card decks with a large card pool, MCTS provides substantially better exploration.

**Complexity:** L

**Dependencies:** P2-G (beam improvements give a baseline to compare against before implementing MCTS).

---

## Implementation Order Summary

```
Phase 1 (Quick Wins — 1-2 weeks):
  P1-D  Temporal train/val split
  P1-E  Domain-filtered negatives
  P2-C  Shorten age decay
  P2-E  Decouple prior/model score
  P2-G  Wider beam + repair
  P2-A  Add validity/diversity metrics

Phase 2 (Core Architecture — 3-5 weeks):
  P1-A  Vectorize synergy affinity (O(N²) → vectorized)
  P1-B  Wire TF-IDF text features into state
  P1-C  Sparse top-2 MoE routing + load balancing loss
  P2-D  Meta-score as training target
  P2-F  Curriculum learning for MoE

Phase 3 (Advanced — 6+ weeks, post-data validation):
  P2-B  Archetype-conditioned routing
  P3-A  Learned card text projection
  P3-B  Synergy GNN embeddings
  P3-C  Matchup-aware conditioning
  P3-D  Per-format expert banks
  P3-E  MCTS inference
```

---

## Appendix: Key Constants for Review

| Constant | Current Value | Recommendation |
|----------|--------------|----------------|
| `_EMBEDDING_DIM` | 64 | Consider 128 once data scale justifies |
| `_MOE_EXPERTS` | 8 | Keep; ensure load-balanced utilization |
| `_NEGATIVE_SAMPLES` (Item2Vec) | 10 | Increase to 15 after domain-filtering |
| `_ARCHETYPE_JACCARD_THRESHOLD` | 0.78 | Tune per shell; 0.72 for diverse shells |
| `_ARCHETYPE_MIN_DECKS` | 4 | Fine for now; document as a parameter |
| `_PURE_BEAM_WIDTH` | 8 | Increase to 16 (P2-G) |
| `_PURE_POOL_LIMIT` | 48 | Increase to 64 with P1-A speedup |
| Age half-life | 120 days | Reduce to 45 days (P2-C) |
| `_EMBEDDING_NEIGHBOR_COUNT` | 12 | Fine |
