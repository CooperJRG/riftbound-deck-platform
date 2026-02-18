from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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


class ReplacementOption(BaseModel):
    card: str
    owned: int
    available: int
    score: float = 0.0


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
    missing_cards: list[CardNeed] = Field(default_factory=list)
    shopping_list: list[CardNeed] = Field(default_factory=list)
    replacement_suggestions: list[CardReplacementSuggestion] = Field(default_factory=list)


class CollectionSnapshot(BaseModel):
    cards: dict[str, int]
    total_unique_cards: int
    total_copies: int
    in_use_cards: dict[str, int] = Field(default_factory=dict)
    available_cards: dict[str, int] = Field(default_factory=dict)
    total_in_use_copies: int = 0
    total_available_copies: int = 0


class CollectionItemRequest(BaseModel):
    card: str
    quantity: int


class CollectionCsvImportRequest(BaseModel):
    csv_text: str = Field(alias="csvText")
    replace_existing: bool = Field(default=False, alias="replaceExisting")


class DeckValidationRequest(BaseModel):
    deck: DeckPayload


class DeckAnalyzeRequest(BaseModel):
    deck: DeckPayload
    collection_override: dict[str, int] | None = Field(default=None, alias="collectionOverride")


class DeckLibraryRow(BaseModel):
    id: str
    name: str
    source: str
    format: str
    bucket: str = "saved"
    updated_at: str = Field(alias="updatedAt")
    created_at: str = Field(alias="createdAt")
    deck: DeckPayload


class DeckLibraryUpsertRequest(BaseModel):
    deck: DeckPayload
    name: str | None = None
    source: str | None = None
    bucket: str | None = None


class DeckImportRequest(BaseModel):
    raw_text: str = Field(alias="rawText")
    name: str | None = None
    source: str | None = None
    bucket: str | None = None


class DeckLibraryBucketRequest(BaseModel):
    bucket: str


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
