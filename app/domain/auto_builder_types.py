from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.models import DeckPayload


@dataclass(frozen=True)
class TrainingDeckRow:
    source: str
    deck_id: str
    deck_name: str
    deck: DeckPayload
    leader_title: str
    chosen_champion_title: str
    main_by_key: dict[str, int]
    main_cards_multiset: tuple[str, ...]
    meta_score: float
    deck_price: float | None
    views: float | None
    likes: int | None
    age_days: float | None
    sample_weight: float
    duplicate_source_count: int = 1
    deck_signature: str = ""


@dataclass(frozen=True)
class WinConditionComponent:
    component_id: int
    label: str
    top_cards: tuple[str, ...] = ()
    top_effect_tokens: tuple[str, ...] = ()
    sample_deck_count: int = 0
    avg_competitive_score: float = 0.0
    shell_coverage_count: int = 0
    archetype_count: int = 0


@dataclass(frozen=True)
class SynergyCluster:
    cluster_id: int
    label: str
    top_cards: tuple[str, ...] = ()
    avg_competitive_score: float = 0.0


@dataclass(frozen=True)
class PlanSeed:
    source: str
    deck_id: str
    deck_name: str
    score: float


@dataclass(frozen=True)
class ShellProfile:
    shell_id: str
    shell_label: str
    legend_title: str
    chosen_champion_title: str
    legend_domains: tuple[str, ...] = ()
    training_deck_count: int = 0
    archetype_count: int = 0
    competitive_prior: float = 0.0
    buildability_prior: float = 0.0
    buildable_conversion: float = 0.0
    source_breakdown: dict[str, int] = field(default_factory=dict)
    rune_weights: dict[str, float] = field(default_factory=dict)
    battlefield_weights: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ArchetypeProfile:
    archetype_id: str
    shell_id: str
    archetype_name: str
    legend_title: str
    chosen_champion_title: str
    prototype_main: dict[str, int] = field(default_factory=dict)
    win_condition_vector: tuple[float, ...] = ()
    top_core_cards: tuple[str, ...] = ()
    top_flex_cards: tuple[str, ...] = ()
    nearest_seed_decks: tuple[PlanSeed, ...] = ()
    rune_weights: dict[str, float] = field(default_factory=dict)
    battlefield_weights: dict[str, float] = field(default_factory=dict)
    competitive_prior: float = 0.0
    buildability_prior: float = 0.0
    buildable_conversion: float = 0.0
    confidence: float = 0.0
    source_breakdown: dict[str, int] = field(default_factory=dict)
    win_condition_id: int = 0
    synergy_cluster_ids: tuple[int, ...] = ()
    synergy_cluster_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class GenerationPlan:
    shell_id: str
    shell_label: str
    archetype_id: str
    archetype_name: str
    archetype_confidence: float
    win_condition_id: int
    win_condition_label: str
    legend_title: str
    chosen_champion_title: str
    synergy_cluster_ids: tuple[int, ...]
    synergy_cluster_labels: tuple[str, ...]
    win_condition_vector: tuple[float, ...] = ()
    source_breakdown: dict[str, int] = field(default_factory=dict)
    seed_decks: tuple[PlanSeed, ...] = ()
    shell_buildability_prior: float = 0.0
    shell_buildable_conversion: float = 0.0
    archetype_buildability_prior: float = 0.0
    archetype_buildable_conversion: float = 0.0
    prior_score: float = 0.0


@dataclass
class CandidateDeck:
    build_mode: str
    deck: DeckPayload
    shell_id: str
    shell_label: str
    archetype_id: str
    archetype_name: str
    archetype_confidence: float
    win_condition_id: int
    win_condition_label: str
    win_condition_confidence: float
    synergy_cluster_ids: list[int] = field(default_factory=list)
    synergy_cluster_labels: list[str] = field(default_factory=list)
    competitive_score: float = 0.0
    candidate_score: float = 0.0
    ranking_score: float = 0.0
    source_breakdown: dict[str, int] = field(default_factory=dict)
    validation_fallback: str = ""
    completion_pct: float = 0.0
    is_buildable: bool = False
    estimated_completion_cost: float | None = None
    missing_copies: int = 0
    missing_unique_cards: int = 0
    missing_cards: list[dict[str, Any]] = field(default_factory=list)
    replacement_suggestions: list[dict[str, Any]] = field(default_factory=list)
    replacement_confidence: float = 0.0
    explanations: list[dict[str, str]] = field(default_factory=list)
    seed_decks: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class LoadedAutoBuilderBundle:
    metadata: dict[str, Any]
    bundle: dict[str, Any]
    card_embeddings: dict[str, list[float]]
    generator_state: dict[str, Any]
    win_conditions: tuple[WinConditionComponent, ...]
    synergy_clusters: tuple[SynergyCluster, ...]
