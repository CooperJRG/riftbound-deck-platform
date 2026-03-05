# Auto Builder Agent Handoff

## Purpose

This document is for a new agent taking over the Riftbound `Auto Builder` / model-observation work.

The system is trying to do two things at once:

1. Generate strong legal decks from a growing corpus of public decklists.
2. Make those recommendations collection-aware, including a strict `onlyBuildable` mode.

The current implementation is functional and materially improved over the initial version, but it is not final. The owner is roughly "80% happy" with the quality and expects another pass focused on both recommendation quality and runtime/training speed.

## High-level Product Goal

The Auto Builder should:

- learn deck structure from real public decklists
- identify many meaningful win conditions and synergy packages
- recommend decks the user can build now, or almost build
- suggest replacements and repairs for missing cards
- help surface the best deck a user can make from their collection
- expose internal model state in `/model-observation`
- support versioned training, promotion, and inspection of saved models

## Current Architecture

### Main files

- `app/domain/auto_builder_training.py`
- `app/domain/auto_builder_generation.py`
- `app/domain/auto_builder_features.py`
- `app/domain/auto_builder_scoring.py`
- `app/domain/auto_builder_types.py`
- `app/infra/auto_builder_repo.py`
- `app/infra/model_observation_repo.py`
- `app/api/routers/auto_builder.py`
- `app/api/routers/model_observation.py`
- `web/app.js`
- `web/index.html`
- `web/styles.css`

### Training pipeline

The main entrypoint is:

- `train_auto_builder_artifacts(...)` in `app/domain/auto_builder_training.py`

Current training stages:

1. Load card catalog, rules, and canonical meta index.
2. Build legal normalized training rows.
3. Build vocab and card features.
4. Train neural card embeddings with an Item2Vec-style objective.
5. Sweep candidate win-condition counts and select one.
6. Train final NMF win-condition model.
7. Sweep candidate synergy-cluster counts and select one.
8. Train final synergy clustering.
9. Train tree-based competitive and replacement models.
10. Train the MoE candidate scorer.
11. Build shell and archetype profiles.
12. Evaluate on held-out rows and synthetic collections.
13. Persist a versioned artifact bundle.

### Runtime recommendation pipeline

The main entrypoint is:

- `AutoBuilderRepository.recommend(...)` in `app/infra/auto_builder_repo.py`

Current runtime design:

- shell-first planning, not global-win-condition-first
- plans are built from shell profiles and archetype profiles
- two main generation paths:
  - pure generation
  - seed adaptation
- prototype backfill exists when candidate count is low
- diversity policy prefers shell diversity
- strict `onlyBuildable=true` mode exists and is enforced during generation, not only as a post-filter

### Model observation / model operations

The hidden admin workspace is available at:

- `/model-observation`

It supports:

- observation of production model state
- training with parameters
- live training progress
- synthetic collection config
- snapshotting current production model
- promoting saved models to production

Main runtime file:

- `app/infra/model_observation_repo.py`

## Current ML Stack

### What exists now

- neural card embeddings (`Item2Vec` style with PyTorch)
- NMF win-condition decomposition
- spectral clustering for synergy clusters
- k-NN retrieval over deck vectors
- MoE-like candidate scorer for generation
- tree-based competitive scoring
- tree-based replacement scoring

### What is learned

- win conditions
- synergy clusters
- shell profiles
- archetype profiles
- shell/archetype buildability priors
- replacement priors
- competitive score estimates

## Current Data Sources

Current source mix is public web deck data. The system already ingests:

- `riftboundgg`
- `piltoverarchive`
- Riot organized play / Bologna article data
- `mobalytics-tournament`
- optional / best-effort `riftdecks` support

The corpus is good enough to be useful, but still not broad enough to fully solve strict-buildable density.

## Synthetic Collection Training

Synthetic collections are now part of training/evaluation. They are intended to simulate realistic user collections.

Current config:

- packs range from `24` to `240`
- each pack:
  - `7` commons
  - `3` uncommons
  - `2` rare slots with epic upgrade probabilities
- rune ownership can be treated as effectively unlimited for synthetic training

Current relevant fields:

- `syntheticCollectionConfig`
- `syntheticCollectionSummary`
- `scenarioCount`

## Current Strong Points

- shell-first generation is materially better than the earlier global-win-condition-only approach
- strict buildable mode exists and is real
- win condition / synergy count selection no longer collapses to tiny values on medium corpora
- model registry and production promotion now exist
- training can use GPU for the PyTorch parts when launched from the correct environment
- observation/admin tooling exists and is usable

## Current Weak Points

These are the main problems still worth rethinking.

### 1. Quality still depends heavily on corpus breadth

The recommender is good, but still constrained by the number and diversity of input decks.

### 2. Strict-buildable density is still too low

Strict buildable mode works, but many realistic collections still produce too few viable recommendations.

### 3. Win conditions and synergy clusters may still be too coarse or too noisy

The current count selection is better than before, but it is still heuristic-guided. The owner explicitly wants many more meaningful win conditions and roughly `2x` or more synergy clusters relative to that scale. The real issue is not just bigger numbers; it is finding a resolution that is more semantically useful without fragmenting into garbage clusters.

### 4. Some stages are still CPU-heavy

PyTorch training/inference can use GPU, but major scikit-learn stages remain CPU-bound:

- NMF
- spectral clustering
- k-NN fitting
- tree fitting
- held-out sweeps

### 5. Evaluation metrics are still proxy-heavy

Held-out recommendation metrics and synthetic collection scenarios are better than the initial thin/full proxy split, but this is still a proxy setup. There is room to better simulate real ownership distributions and deck-building behavior.

### 6. Training-time parameter sweeps are expensive

The system does multiple candidate sweeps for win-condition and synergy counts. This improves robustness but also increases training time.

## What the Model Is Currently Seeking To Do

If you are rethinking the pipeline, the actual target behavior is:

- infer a deck's plan from shell + archetype + global strategy signals
- recommend multiple legal, diverse, collection-aware decks
- strongly prioritize fully buildable decks when asked
- maintain useful continuity between:
  - shells
  - archetypes
  - win conditions
  - synergy packages
- expose model state in a form a developer can inspect and reason about
- keep training and inference fast enough to remain practical for iterative use

This is not a generic recommender. It is a structured deck-synthesis and repair system.

## Suggested Improvement Axes

Do not assume the current stack is optimal. It is acceptable to retain parts of it and replace others.

Potential directions worth evaluating:

### Quality

- replace or augment NMF with a model that better captures sparse multi-plan decks
- build a more explicit shell-conditioned latent representation instead of using shell mostly as a planning hierarchy
- learn package-level retrieval directly rather than only card-level and archetype-level signals
- improve buildability modeling using ownership distributions by rarity/set/domain
- incorporate tournament placement / event strength more directly in scoring
- reduce noisy cluster fragmentation while preserving higher semantic resolution
- improve seed adaptation repair so buildable conversion is stronger under realistic collections

### Speed

- reduce repeated expensive sweeps with caching or coarse-to-fine selection
- precompute reusable matrices/features for count selection
- replace the slowest sklearn stages if justified
- batch more runtime candidate scoring
- simplify or prune generation search without sacrificing diversity
- tighten evaluation loops so admin retraining remains interactive

### Data

- increase source breadth only if signal quality stays high
- prefer structured, stable sources over fragile scraping
- preserve provenance and tournament metadata
- keep dedupe robust

## Operational Notes

- `python run.py` serves the current app entrypoint
- the hidden model workspace is on `/model-observation`
- when testing UI changes, hard-refresh the browser if route boot behavior looks wrong
- the training status UI depends on event history from `ModelObservationRepository`
- saved models live separately from the production artifact directory

## Validation Expectations For A New Agent

Any rethink should preserve:

- legal deck generation
- collection-aware ranking
- strict buildable correctness
- production model promotion / snapshot behavior
- model observation route and training controls

You should validate:

- API regressions
- route behavior for `/model-observation`
- training status and progress visibility
- recommendation breadth and buildability behavior
- training time before/after

## Short Prompt For A New Agent

Use this prompt as the next-agent handoff:

> Rethink the Riftbound Auto Builder pipeline from first principles. The current system works, but it is only about 80% satisfactory. Your goal is to improve both recommendation quality and training/runtime speed without breaking legality, collection-awareness, strict-buildable mode, or model versioning. Review the current training and generation pipeline, identify the real bottlenecks and proxy assumptions, and propose concrete changes to the representation learning, clustering/win-condition discovery, buildability modeling, retrieval/generation flow, and evaluation strategy. Prefer solutions that improve semantic resolution, buildable recommendation density, and speed. Then implement the highest-leverage changes and verify them with regression tests and measurable before/after outcomes.
