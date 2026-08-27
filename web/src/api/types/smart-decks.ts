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

export interface Repair {
  kind: "none" | "conservative" | "free";
  drift: number;
  swaps: Swap[];
  deck: DeckPayload;
  /** The finished list, named and illustrated, so a swap has somewhere to point. */
  cards: RepairDeckCard[];
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
  question: Question | null;
  floor: Floor | null;
  feasibility: string;
  canBuild: boolean;
  banNotices: BanNotice[];
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
