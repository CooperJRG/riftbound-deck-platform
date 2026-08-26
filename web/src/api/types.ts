/**
 * Wire types, mirroring `server/riftbound/api/schemas.py`.
 *
 * Card references are always `cardId`. Nothing in the UI stores a card by name.
 */

export type CardType =
  | "Unit"
  | "Spell"
  | "Gear"
  | "Battlefield"
  | "Legend"
  | "Rune"
  | "Token";

export type Zone = "main" | "runes" | "battlefields" | "sideboard";

export type AvailabilityMode = "open" | "collection" | "exclusion";

export interface Printing {
  printId: string;
  title: string;
  setCode: string;
  cardNumber: string;
  rarity: string;
  promo: boolean;
  imageUrl: string;
}

export interface Card {
  cardId: string;
  name: string;
  cardType: string;
  superType: string;
  domains: string[];
  cost: number | null;
  might: number | null;
  tags: string[];
  championTags: string[];
  effect: string;
  unique: boolean;
  rarity: string;
  setCodes: string[];
  imageUrl: string;
  printings: Printing[];
}

/** A card together with how available it is under the active profile. */
export interface CardAvailability {
  card: Card;
  weight: number;
  available: boolean;
  ownedCopies: number;
  maxCopies: number | null;
  reason: string;
}

export interface CardPage {
  total: number;
  offset: number;
  limit: number;
  cards: CardAvailability[];
}

export interface CardFacets {
  cardTypes: string[];
  superTypes: string[];
  domains: string[];
  setCodes: string[];
  rarities: string[];
}

export interface DeckPayload {
  name: string;
  format: string;
  legendId: string;
  championId: string;
  main: Record<string, number>;
  runes: Record<string, number>;
  battlefields: string[];
  sideboard: Record<string, number>;
}

export interface Issue {
  code: string;
  field: string;
  message: string;
  ruleRefs: string[];
  cardId: string;
  /** `notice` is legal-but-worth-knowing and never blocks a deck. */
  severity: "error" | "warning" | "notice";
}

export interface MissingEntry {
  cardId: string;
  /** Resolved by the server, so the UI never renders a bare id. */
  name: string;
  copies: number;
  reason: string;
}

export interface Coverage {
  totalCopies: number;
  availableCopies: number;
  penalisedCopies: number;
  ratio: number;
  complete: boolean;
  missing: MissingEntry[];
}

export interface Validation {
  legal: boolean;
  issues: Issue[];
  mainTotal: number;
  runeTotal: number;
  sideboardTotal: number;
  battlefieldCount: number;
  legendDomains: string[];
  coverage: Coverage;
}

export interface DeckSummary {
  deckId: string;
  name: string;
  format: string;
  legendId: string;
  championId: string;
  mainTotal: number;
  createdAt: string;
  updatedAt: string;
}

export interface DeckView {
  deckId: string;
  deck: DeckPayload;
  validation: Validation;
}

export interface ExclusionRuleView {
  kind: string;
  value: string;
  description: string;
}

/** An excluded card, named by the server so the client never shows a bare id. */
export interface ExcludedCard {
  cardId: string;
  name: string;
}

export interface AvailabilityProfile {
  mode: AvailabilityMode;
  strict: boolean;
  penalty: number;
  description: string;
  excludedCards: ExcludedCard[];
  rules: ExclusionRuleView[];
  ownedCardCount: number;
}

export interface AvailabilityUpdate {
  mode: AvailabilityMode;
  strict?: boolean;
  penalty?: number;
  excludedCardIds?: string[];
  rules?: { kind: string; value: string }[];
}

export interface RuleKinds {
  kinds: string[];
  values: Record<string, string[]>;
}

export interface FormatView {
  format: string;
  description: string;
  constraints: Record<string, unknown>;
  bannedCardIds: string[];
}

export interface Health {
  ok: boolean;
  mode: string;
  bundleId: string;
  cardCount: number;
  formats: string[];
  migrations: string[];
}


// -- meta ---------------------------------------------------------------------

/** How strongly a deck's placement in the meta is evidenced. */
export type Evidence = "tournament-placed" | "tournament-entry" | "community";

export interface Provenance {
  source: string;
  url: string;
  evidence: Evidence;
  /** Human-readable, e.g. "3rd of 257 at Convergence #2". */
  summary: string;
  author: string;
  publishedAt: string;
  views: number;
  tournamentSlug: string;
  tournamentName: string;
  tournamentDate: string;
  placement: number;
  fieldSize: number;
}

export interface Score {
  total: number;
  evidence: number;
  placement: number;
  recency: number;
  popularity: number;
}

export interface MetaDeck {
  deckId: string;
  name: string;
  legendId: string;
  legendName: string;
  championId: string;
  championName: string;
  archetypeId: string;
  domains: string[];
  mainTotal: number;
  provenance: Provenance;
  score: Score;
  coverage: Coverage;
  unresolved: string[];
  deck: DeckPayload;
}

export interface Archetype {
  archetypeId: string;
  name: string;
  legendId: string;
  championId: string;
  deckCount: number;
  tournamentDeckCount: number;
  bestPlacement: number;
  /** Field size the best placement came from; a placement alone says little. */
  bestFieldSize: number;
  latestDate: string;
  score: number;
  bestDeck: MetaDeck | null;
}

export interface Tournament {
  slug: string;
  name: string;
  date: string;
  format: string;
  players: number;
  winner: string;
  decksPublished: number;
}

/** A credit the meta data's source requires the app to display. */
export interface Attribution {
  source: string;
  url: string;
  text: string;
}

export interface MetaStatus {
  available: boolean;
  snapshotId: string;
  createdAt: string;
  deckCount: number;
  tournamentCount: number;
  evidenceCounts: Record<string, number>;
  warnings: string[];
  attribution: Attribution[];
}

// -- smart decks --------------------------------------------------------------

export interface LegendChoice {
  legendId: string;
  name: string;
  domains: string[];
  imageUrl: string;
  deckCount: number;
  tournamentDeckCount: number;
  bestScore: number;
  /** Share of the legend's staples already in the collection. A hint, never a filter. */
  familiarity: number;
}

/** One row of the review screen: `Need 3 - You have [0][1][2][3]`. */
export interface RequirementRow {
  cardId: string;
  name: string;
  zone: "legend" | "main" | "runes" | "battlefields" | "ask";
  needed: number;
  imageUrl: string;
  rarity: string;
  known: boolean;
  exact: boolean;
  have: number;
}

export interface Swap {
  outCardId: string;
  outName: string;
  inCardId: string;
  inName: string;
  copies: number;
  reason: string;
}

export interface Repair {
  kind: "none" | "conservative" | "free";
  drift: number;
  swaps: Swap[];
  deck: DeckPayload;
  legal: boolean;
}

export interface Gap {
  cardId: string;
  name: string;
  needed: number;
  have: number;
  short: number;
}

export interface Floor {
  deck: DeckPayload;
  quality: number;
  summary: string;
}

export interface Question {
  reason: string;
  cards: RequirementRow[];
}

export interface Proposal {
  phase: "propose" | "checklist" | "done";
  reason: string;
  round: number;
  deck: MetaDeck | null;
  requirements: RequirementRow[];
  gaps: Gap[];
  conservative: Repair | null;
  free: Repair | null;
  question: Question | null;
  floor: Floor | null;
  feasibility: string;
  canBuild: boolean;
}

export interface SmartSession {
  sessionId: string;
  legendId: string;
  legendName: string;
  phase: "propose" | "checklist" | "done";
  rounds: number;
  knownCards: number;
  savedDeckId: string;
  createdAt: string;
  updatedAt: string;
  proposal: Proposal | null;
}

export interface SaveCollectionResult {
  cardsWritten: number;
  copiesWritten: number;
  cardsCleared: number;
  skippedLowerBounds: number;
}
