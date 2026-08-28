/**
 * Wire types for cards, decks and availability.
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

/**
 * What a deck asks of a collection.
 *
 * `short` is what the player would have to acquire; `composition` is the deck's whole
 * rarity makeup, which stands alone with no collection recorded — the case that matters
 * on the release day of a new set, when rarity is the only accessibility signal that
 * exists yet.
 */
export interface DeckCost {
  short: Record<string, number>;
  composition: Record<string, number>;
  copiesShort: number;
  scarceShort: number;
  affordable: boolean;
  summary: string;
}

export interface Coverage {
  totalCopies: number;
  availableCopies: number;
  penalisedCopies: number;
  ratio: number;
  complete: boolean;
  missing: MissingEntry[];
  cost: DeckCost;
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
  /** Classes of card the player says they own. Collection mode's bulk entry. */
  ownedRules: ExclusionRuleView[];
  ownedCardCount: number;
}

export interface AvailabilityUpdate {
  mode: AvailabilityMode;
  strict?: boolean;
  penalty?: number;
  excludedCardIds?: string[];
  rules?: { kind: string; value: string }[];
  ownedRules?: { kind: string; value: string }[];
}

/**
 * How the legend picker is ordered.
 *
 * A sort, never a filter: every legend stays in the list either way. "buildable" reads
 * the familiarity figure the server already computes, so somebody short of cards can
 * ask which of these is closest to what they have rather than scrolling past the
 * decks they are least able to build.
 */
export type LegendSort = "strength" | "buildable";

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
  /**
   * The server's API contract number.
   *
   * Absent on a server old enough to predate this field, which is itself the answer:
   * anything below EXPECTED_API_CONTRACT means the page is newer than the server.
   */
  apiContract?: number;
  mode: string;
  bundleId: string;
  cardCount: number;
  formats: string[];
  migrations: string[];
}


/**
 * What erasing removed. Counted rather than assumed — a privacy control that says
 * "done" without saying what it did asks to be trusted exactly when it should be
 * showing its working.
 */
export interface ForgetResult {
  collectionRows: number;
  sessions: number;
  availability: AvailabilityProfile;
}
