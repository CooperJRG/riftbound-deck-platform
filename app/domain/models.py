from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

_CAMEL_SEGMENT_RE = re.compile(r"(?<!^)(?=[A-Z])")
_CAMEL_KEY_RE = re.compile(r"^[a-z]+(?:[A-Z][A-Za-z0-9]*)+$")


def _camel_to_snake(value: str) -> str:
    text = str(value or "").strip()
    if not text or "_" in text or not _CAMEL_KEY_RE.fullmatch(text):
        return text
    return _CAMEL_SEGMENT_RE.sub("_", text).lower()


def _normalize_input_keys(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            normalized_key = _camel_to_snake(key) if isinstance(key, str) else key
            out[normalized_key] = _normalize_input_keys(item)
        return out
    if isinstance(value, list):
        return [_normalize_input_keys(item) for item in value]
    return value


class StrictInputModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def normalize_input_keys(cls, value: Any) -> Any:
        return _normalize_input_keys(value)


class VisibilityMixin(BaseModel):
    visibility: str = "private"


class DeckPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str = "Untitled Deck"
    source: str = "builder"
    format: str = "constructed"
    legend_title: str = Field(default="", alias="legendTitle")
    chosen_champion_title: str = Field(default="", alias="chosenChampionTitle")
    main: dict[str, int] = Field(default_factory=dict)
    runes: dict[str, int] = Field(default_factory=dict)
    battlefields: list[str] = Field(default_factory=list)
    sideboard: dict[str, int] = Field(default_factory=dict)

    def main_total(self) -> int:
        return sum(max(0, int(v)) for v in self.main.values())

    def runes_total(self) -> int:
        return sum(max(0, int(v)) for v in self.runes.values())

    def sideboard_total(self) -> int:
        return sum(max(0, int(v)) for v in self.sideboard.values())


class ValidationIssue(BaseModel):
    code: str
    field: str
    message: str
    rule_refs: list[str] = Field(default_factory=list)


class DeckValidationResult(BaseModel):
    is_valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    summary: str = ""


class CardNeed(BaseModel):
    card: str
    required: int
    owned: int
    missing: int
    estimated_unit_price: float | None = None
    estimated_missing_cost: float | None = None
    tcgplayer_url: str = ""


class ReplacementOption(BaseModel):
    card: str
    owned: int
    available: int
    score: float = 0.0
    source: str = "heuristic"
    reason: str = ""
    win_condition_match: float = Field(default=0.0, alias="winConditionMatch")
    synergy_match: float = Field(default=0.0, alias="synergyMatch")


class CardReplacementSuggestion(BaseModel):
    card: str
    missing: int
    options: list[ReplacementOption] = Field(default_factory=list)


class DeckAnalysisResult(BaseModel):
    total_required: int
    total_owned_for_deck: int
    missing_copies: int
    missing_unique_cards: int
    completion_pct: float
    is_buildable: bool
    estimated_completion_cost: float | None = None
    missing_cards_priced: int = 0
    missing_cards_unpriced: int = 0
    missing_cards: list[CardNeed] = Field(default_factory=list)
    shopping_list: list[CardNeed] = Field(default_factory=list)
    replacement_suggestions: list[CardReplacementSuggestion] = Field(default_factory=list)
    win_condition_label: str = Field(default="", alias="winConditionLabel")


class CollectionSnapshot(BaseModel):
    cards: dict[str, int]
    total_unique_cards: int
    total_copies: int
    in_use_cards: dict[str, int] = Field(default_factory=dict)
    available_cards: dict[str, int] = Field(default_factory=dict)
    total_in_use_copies: int = 0
    total_available_copies: int = 0


class CollectionItemRequest(StrictInputModel):
    card: str
    quantity: int


class CollectionCsvImportRequest(StrictInputModel):
    csv_text: str
    replace_existing: bool = False


class CollectionJsonImportRequest(StrictInputModel):
    json_text: str
    replace_existing: bool = False


class CollectionResetRequest(StrictInputModel):
    confirm_phrase: str
    create_backup: bool = True


class DeckValidationRequest(StrictInputModel):
    deck: DeckPayload


class DeckAnalyzeRequest(StrictInputModel):
    deck: DeckPayload
    collection_override: dict[str, int] | None = None


class DeckLibraryRow(BaseModel):
    id: str
    name: str
    source: str
    format: str
    bucket: str = "saved"
    visibility: str = "private"
    owner_display_name: str = Field(default="", alias="ownerDisplayName")
    is_owner: bool = Field(default=True, alias="isOwner")
    published_at: str | None = Field(default=None, alias="publishedAt")
    updated_at: str = Field(alias="updatedAt")
    created_at: str = Field(alias="createdAt")
    like_count: int = Field(default=0, alias="likeCount")
    liked_by_me: bool = Field(default=False, alias="likedByMe")
    deck: DeckPayload


class DeckLibraryUpsertRequest(StrictInputModel):
    deck: DeckPayload
    name: str | None = None
    source: str | None = None
    bucket: str | None = None
    visibility: str | None = None


class DeckImportRequest(StrictInputModel):
    raw_text: str
    name: str | None = None
    source: str | None = None
    bucket: str | None = None
    visibility: str | None = None


class DeckLibraryBucketRequest(StrictInputModel):
    bucket: str


class DeckVisibilityRequest(StrictInputModel):
    visibility: str


class MetaDeckSummary(BaseModel):
    source: str
    deck_id: str = Field(alias="deckId")
    deck_name: str = Field(alias="deckName")
    deck_url: str = Field(default="", alias="deckUrl")
    meta_score: float | None = Field(default=None, alias="metaScore")
    deck_price: float | None = Field(default=None, alias="deckPrice")
    views: float | None = None
    likes: int | None = None
    age_days: float | None = Field(default=None, alias="ageDays")
    leader_title: str = Field(default="", alias="leaderTitle")
    is_buildable: bool | None = Field(default=None, alias="isBuildable")
    completion_pct: float | None = Field(default=None, alias="completionPct")
    missing_copies: int | None = Field(default=None, alias="missingCopies")
    missing_unique_cards: int | None = Field(default=None, alias="missingUniqueCards")
    recommendation_score: float | None = Field(default=None, alias="recommendationScore")
    competitive_score: float | None = Field(default=None, alias="competitiveScore")
    win_condition_id: int | None = Field(default=None, alias="winConditionId")
    win_condition_label: str = Field(default="", alias="winConditionLabel")
    deck: DeckPayload


class CardView(BaseModel):
    title: str
    card_type: str = Field(alias="cardType")
    super_type: str = Field(alias="superType")
    domains: list[str]
    champion_tags: list[str] = Field(default_factory=list, alias="championTags")
    cost: int | None = None
    might: int | None = None
    is_unique: bool = Field(default=False, alias="isUnique")
    image_url: str = Field(default="", alias="imageUrl")
    rarity: str = ""
    set_name: str = Field(default="", alias="set")
    card_number: str = Field(default="", alias="cardNumber")
    effect: str = ""
    flavor: str = ""
    tags: list[str] = Field(default_factory=list)
    promo: bool = False


class DeckEligibilityResponse(BaseModel):
    legend_title: str = Field(default="", alias="legendTitle")
    legend_domains: list[str] = Field(default_factory=list, alias="legendDomains")
    legends: list[CardView] = Field(default_factory=list)
    champions: list[CardView] = Field(default_factory=list)
    battlefields: list[CardView] = Field(default_factory=list)
    runes: list[CardView] = Field(default_factory=list)
    recommended_runes: dict[str, int] = Field(default_factory=dict, alias="recommendedRunes")
    main_deck_size: int = Field(default=40, alias="mainDeckSize")
    rune_deck_size: int = Field(default=12, alias="runeDeckSize")
    battlefield_count: int = Field(default=3, alias="battlefieldCount")
    main_copy_limit: int = Field(default=3, alias="mainCopyLimit")
    allowed_main_card_types: list[str] = Field(default_factory=list, alias="allowedMainCardTypes")
    sideboard_max: int = Field(default=8, alias="sideboardMax")
    allowed_sideboard_card_types: list[str] = Field(default_factory=list, alias="allowedSideboardCardTypes")


class FormatProfileSummary(BaseModel):
    format_name: str = Field(alias="format")
    description: str = ""
    is_default: bool = Field(default=False, alias="isDefault")
    main_deck_size: int = Field(default=40, alias="mainDeckSize")
    rune_deck_size: int = Field(default=12, alias="runeDeckSize")
    battlefield_count: int = Field(default=3, alias="battlefieldCount")
    sideboard_max: int = Field(default=8, alias="sideboardMax")
    main_copy_limit: int = Field(default=3, alias="mainCopyLimit")


class MetaIndexStatus(BaseModel):
    source_path: str = Field(alias="sourcePath")
    indexed_decks: int = Field(alias="indexedDecks")
    raw_rows: int = Field(alias="rawRows")
    last_refreshed_at: str | None = Field(default=None, alias="lastRefreshedAt")
    last_refresh_attempt_at: str | None = Field(default=None, alias="lastRefreshAttemptAt")
    last_error: str | None = Field(default=None, alias="lastError")


class AutoBuilderStatus(BaseModel):
    enabled: bool = True
    model_dir: str = Field(alias="modelDir")
    generated_at: str | None = Field(default=None, alias="generatedAt")
    training_deck_count: int = Field(default=0, alias="trainingDeckCount")
    card_count: int = Field(default=0, alias="cardCount")
    win_condition_count: int = Field(default=0, alias="winConditionCount")
    synergy_cluster_count: int = Field(default=0, alias="synergyClusterCount")
    source_counts: dict[str, int] = Field(default_factory=dict, alias="sourceCounts")
    unique_shell_count: int = Field(default=0, alias="uniqueShellCount")
    archetype_count: int = Field(default=0, alias="archetypeCount")
    default_min_results: int = Field(default=12, alias="defaultMinResults")
    max_variants_per_shell: int = Field(default=2, alias="maxVariantsPerShell")
    artifact_sklearn_version: str = Field(default="", alias="artifactSklearnVersion")
    runtime_sklearn_version: str = Field(default="", alias="runtimeSklearnVersion")
    artifact_torch_version: str = Field(default="", alias="artifactTorchVersion")
    runtime_torch_version: str = Field(default="", alias="runtimeTorchVersion")
    training_torch_device: str = Field(default="", alias="trainingTorchDevice")
    runtime_torch_device: str = Field(default="", alias="runtimeTorchDevice")
    training_metrics: dict[str, Any] = Field(default_factory=dict, alias="trainingMetrics")
    selected_win_condition_count: int = Field(default=0, alias="selectedWinConditionCount")
    selected_synergy_cluster_count: int = Field(default=0, alias="selectedSynergyClusterCount")
    candidate_win_condition_counts: list[int] = Field(default_factory=list, alias="candidateWinConditionCounts")
    candidate_synergy_cluster_counts: list[int] = Field(default_factory=list, alias="candidateSynergyClusterCounts")
    win_condition_selection_metrics: dict[str, dict[str, float]] = Field(default_factory=dict, alias="winConditionSelectionMetrics")
    synergy_selection_metrics: dict[str, dict[str, float]] = Field(default_factory=dict, alias="synergySelectionMetrics")
    resolution_selection_mode: str = Field(default="", alias="resolutionSelectionMode")
    resolution_reference_artifact: str = Field(default="", alias="resolutionReferenceArtifact")
    generator_win_vector_size: int = Field(default=0, alias="generatorWinVectorSize")
    generator_cluster_vector_size: int = Field(default=0, alias="generatorClusterVectorSize")
    embedding_neighbor_count: int = Field(default=0, alias="embeddingNeighborCount")
    strict_buildable_recommendation_hit_rate: float = Field(default=0.0, alias="strictBuildableRecommendationHitRate")
    strict_buildable_empty_result_rate: float = Field(default=0.0, alias="strictBuildableEmptyResultRate")
    source_health: dict[str, dict[str, object]] = Field(default_factory=dict, alias="sourceHealth")
    last_loaded_at: str | None = Field(default=None, alias="lastLoadedAt")
    runtime_warnings: list[str] = Field(default_factory=list, alias="runtimeWarnings")
    last_error: str | None = Field(default=None, alias="lastError")


class AutoBuilderRecommendationRequest(StrictInputModel):
    top: int = 24
    ranking_mode: str = "collection"
    strategy_mode: str = "hybrid"
    legend_title: str = ""
    chosen_champion_title: str = ""
    only_buildable: bool = False
    min_results: int = 12
    diversity_mode: str = "shells"
    collection_override: dict[str, int] | None = None


class AutoBuilderCompleteRequest(StrictInputModel):
    deck: DeckPayload
    ranking_mode: str = "collection"
    strategy_mode: str = "hybrid"
    collection_override: dict[str, int] | None = None


class AutoBuilderExplanation(BaseModel):
    kind: str = ""
    label: str = ""
    value: str = ""


class SeedDeckReference(BaseModel):
    source: str = ""
    deck_id: str = Field(default="", alias="deckId")
    deck_name: str = Field(default="", alias="deckName")
    score: float = 0.0


class WinConditionSummary(BaseModel):
    id: int
    label: str
    top_cards: list[str] = Field(default_factory=list, alias="topCards")
    top_effect_tokens: list[str] = Field(default_factory=list, alias="topEffectTokens")
    sample_deck_count: int = Field(default=0, alias="sampleDeckCount")
    avg_competitive_score: float = Field(default=0.0, alias="avgCompetitiveScore")
    shell_coverage_count: int = Field(default=0, alias="shellCoverageCount")
    archetype_count: int = Field(default=0, alias="archetypeCount")


class SynergyClusterSummary(BaseModel):
    id: int
    label: str
    top_cards: list[str] = Field(default_factory=list, alias="topCards")
    avg_competitive_score: float = Field(default=0.0, alias="avgCompetitiveScore")


class AutoBuilderCandidate(BaseModel):
    build_mode: str = Field(default="hybrid", alias="buildMode")
    shell_id: str = Field(default="", alias="shellId")
    shell_label: str = Field(default="", alias="shellLabel")
    archetype_id: str = Field(default="", alias="archetypeId")
    archetype_name: str = Field(default="", alias="archetypeName")
    archetype_confidence: float = Field(default=0.0, alias="archetypeConfidence")
    win_condition_id: int = Field(default=0, alias="winConditionId")
    win_condition_label: str = Field(default="", alias="winConditionLabel")
    win_condition_confidence: float = Field(default=0.0, alias="winConditionConfidence")
    synergy_cluster_ids: list[int] = Field(default_factory=list, alias="synergyClusterIds")
    synergy_cluster_labels: list[str] = Field(default_factory=list, alias="synergyClusterLabels")
    competitive_score: float = Field(default=0.0, alias="competitiveScore")
    ranking_score: float = Field(default=0.0, alias="rankingScore")
    source_breakdown: dict[str, int] = Field(default_factory=dict, alias="sourceBreakdown")
    validation_fallback: str = Field(default="", alias="validationFallback")
    is_buildable: bool = Field(default=False, alias="isBuildable")
    completion_pct: float = Field(default=0.0, alias="completionPct")
    estimated_completion_cost: float | None = Field(default=None, alias="estimatedCompletionCost")
    missing_copies: int = Field(default=0, alias="missingCopies")
    missing_unique_cards: int = Field(default=0, alias="missingUniqueCards")
    missing_cards: list[CardNeed] = Field(default_factory=list, alias="missingCards")
    replacement_suggestions: list[CardReplacementSuggestion] = Field(default_factory=list, alias="replacementSuggestions")
    seed_decks: list[SeedDeckReference] = Field(default_factory=list, alias="seedDecks")
    explanations: list[AutoBuilderExplanation] = Field(default_factory=list)
    deck: DeckPayload


class AutoBuilderRecommendation(AutoBuilderCandidate):
    rank: int = 0


class SyntheticCollectionConfig(StrictInputModel):
    pack_min: int | None = None
    pack_max: int | None = None
    scenario_count: int | None = None
    rune_unlimited: bool | None = None


class ModelObservationTrainingRequest(StrictInputModel):
    label: str = ""
    epochs: int | None = None
    torch_device: str | None = Field(default=None, alias="torchDevice")
    min_win_condition_count: int | None = Field(default=None, alias="minWinConditionCount")
    synthetic_collection: SyntheticCollectionConfig | None = Field(default=None, alias="syntheticCollection")



class ModelVersionActionRequest(StrictInputModel):
    label: str = ""


class ModelTrainingStatus(BaseModel):
    is_running: bool = Field(default=False, alias="isRunning")
    job_id: str = Field(default="", alias="jobId")
    label: str = ""
    status: str = ""
    started_at: str | None = Field(default=None, alias="startedAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")
    finished_at: str | None = Field(default=None, alias="finishedAt")
    stage: str = ""
    step: int = 0
    total_steps: int = Field(default=0, alias="totalSteps")
    progress_pct: float = Field(default=0.0, alias="progressPct")
    message: str = ""
    error: str = ""
    output_dir: str = Field(default="", alias="outputDir")
    model_id: str = Field(default="", alias="modelId")
    params: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)


class ModelVersionSummary(BaseModel):
    id: str
    label: str = ""
    kind: str = ""
    status: str = ""
    is_production: bool = Field(default=False, alias="isProduction")
    created_at: str | None = Field(default=None, alias="createdAt")
    promoted_at: str | None = Field(default=None, alias="promotedAt")
    model_dir: str = Field(default="", alias="modelDir")
    generated_at: str | None = Field(default=None, alias="generatedAt")
    training_deck_count: int = Field(default=0, alias="trainingDeckCount")
    win_condition_count: int = Field(default=0, alias="winConditionCount")
    synergy_cluster_count: int = Field(default=0, alias="synergyClusterCount")
    epochs: int = 0
    torch_device: str = Field(default="", alias="torchDevice")
    source_counts: dict[str, int] = Field(default_factory=dict, alias="sourceCounts")
    training_metrics: dict[str, Any] = Field(default_factory=dict, alias="trainingMetrics")


class ModelObservationOverview(BaseModel):
    status: AutoBuilderStatus
    training: ModelTrainingStatus
    models: list[ModelVersionSummary] = Field(default_factory=list)
    observation: dict[str, Any] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)


class UserProfileSummary(BaseModel):
    user_id: str = Field(alias="userId")
    email: str
    display_name: str = Field(alias="displayName")
    role: str = "user"
    status: str = "active"
    created_at: str | None = Field(default=None, alias="createdAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")
    last_login_at: str | None = Field(default=None, alias="lastLoginAt")


class FeatureFlags(BaseModel):
    auto_builder_enabled: bool = Field(default=False, alias="autoBuilderEnabled")
    model_observation_enabled: bool = Field(default=False, alias="modelObservationEnabled")
    community_gallery_enabled: bool = Field(default=True, alias="communityGalleryEnabled")


class UpdateDisplayNameRequest(BaseModel):
    display_name: str = Field(alias="displayName")


class MeResponse(BaseModel):
    user: UserProfileSummary
    feature_flags: FeatureFlags = Field(alias="featureFlags")


class PublicDeckListResponse(BaseModel):
    decks: list[DeckLibraryRow] = Field(default_factory=list)
    total: int = 0


class BetaInviteSummary(BaseModel):
    email: str
    role: str = "user"
    status: str = "invited"
    accepted_user_id: str | None = Field(default=None, alias="acceptedUserId")
    invited_at: str | None = Field(default=None, alias="invitedAt")
    accepted_at: str | None = Field(default=None, alias="acceptedAt")
