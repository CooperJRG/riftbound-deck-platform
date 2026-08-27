/**
 * Card-level meta tracking.
 *
 * Kept apart from `meta` for the reason the server keeps them apart: a champion's share
 * partitions the field and a card's adoption does not.
 */

import type { TrendDeck } from "./meta";

export interface CardPoint {
  period: string;
  decks: number;
  totalDecks: number;
  /** Decks playing this card over lists published. NOT a share of the metagame. */
  adoption: number;
  charted: boolean;
}

export interface CardTrend {
  cardId: string;
  name: string;
  imageUrl: string;
  cardType: string;
  rarity: string;
  cost: number | null;
  domains: string[];
  decks: number;
  adoption: number;
  averageCopies: number;
  eventCount: number;
  momentum: number | null;
  confidence: string;
  points: CardPoint[];
}

export interface CardTrendOverview {
  fromDate: string;
  toDate: string;
  format: string;
  tournamentCount: number;
  publishedDeckCount: number;
  chartedDeckCount: number;
  knownFieldPlayers: number;
  publishedCoverage: number;
  archiveFrom: string;
  archiveTo: string;
  archiveTournamentCount: number;
  series: CardTrend[];
}

export interface CardHome {
  entityId: string;
  name: string;
  imageUrl: string;
  decks: number;
  shareOfCard: number;
}

/** A card played alongside this one — the same signal the deck builder fills from. */
export interface CardPartner {
  cardId: string;
  name: string;
  imageUrl: string;
  together: number;
  togetherRate: number;
  lift: number;
}

export interface CardDetail {
  trend: CardTrend;
  /** `[copies, decks]` pairs: what the average hides. */
  copiesSplit: number[][];
  legends: CardHome[];
  champions: CardHome[];
  partners: CardPartner[];
  recentDecks: TrendDeck[];
}
