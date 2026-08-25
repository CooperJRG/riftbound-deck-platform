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
  severity: "error" | "warning";
}

export interface MissingEntry {
  cardId: string;
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
