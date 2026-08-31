/** The deck-building wizard. */

import type { DeckPayload } from "./core";
import type { MetaDeck } from "./meta";

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

export interface RepairDeckCard {
  cardId: string;
  name: string;
  imageUrl: string;
  zone: string;
  copies: number;
  /** Brought in by the repair, and therefore not anywhere in the deck on screen. */
  added: boolean;
}

/**
 * How strong a deck is, on the two scales a player can act on.
 *
 * Both measure the same thing — how much of what the field plays this list contains —
 * and differ only in what they are measured against. `meta` compares it to the strongest
 * deck in the format; `legend` compares it to the strongest published list for its
 * legend, which is 100 by construction.
 *
 * `scored` is false when that champion has no published lists at all. Render that as
 * "not scored", never as a zero: a legend without published references is unknown.
 */
export interface DeckScore {
  meta: number;
  legend: number;
  /** Share of the closest published list for this legend that this deck contains. */
  coverage: number;
  scored: boolean;
  summary: string;
  disclaimer: string;
}

export interface Repair {
  kind: "none" | "conservative" | "free";
  drift: number;
  swaps: Swap[];
  deck: DeckPayload;
  /** The finished list, named and illustrated, so a swap has somewhere to point. */
  cards: RepairDeckCard[];
  legal: boolean;
  score: DeckScore | null;
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
  score: DeckScore | null;
  /** The finished list, named and illustrated, so the finish screen can show it. */
  cards: RepairDeckCard[];
}

/** A card ruled out by preference, not by ownership. Reversible. */
export interface DeclinedCard {
  cardId: string;
  name: string;
  imageUrl: string;
}

export interface Question {
  reason: string;
  cards: RequirementRow[];
}

/** A ban worth telling the player about. Reported, not silently applied. */
export interface BanNotice {
  cardId: string;
  name: string;
  source: "profile" | "upstream";
  enforced: boolean;
  inDeck: boolean;
  message: string;
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
  /**
   * Which repair the wizard picked: the client renders that one instead of offering the
   * choice. Empty when no repair was needed.
   */
  chosen: "" | "conservative" | "free";
  deckScore: DeckScore | null;
  question: Question | null;
  floor: Floor | null;
  feasibility: string;
  canBuild: boolean;
  banNotices: BanNotice[];
}

export interface SmartSession {
  declined: DeclinedCard[];
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
