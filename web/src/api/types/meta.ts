/** The competitive meta: decks, archetypes, tournaments and trends. */

import type { Coverage, DeckPayload } from "./core";

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

export type TrendDimension = "champion" | "legend" | "archetype";

export type TrendBucket = "week" | "month";

export interface TrendPoint {
  period: string;
  decks: number;
  totalDecks: number;
  share: number;
  /**
   * Whether this interval carries enough lists to be worth drawing.
   *
   * Decided by the server, so the threshold lives next to the tests that pin it and
   * every client draws the same line. Do not re-derive it here.
   */
  charted: boolean;
}

export interface TrendSeries {
  entityId: string;
  name: string;
  deckCount: number;
  eventCount: number;
  share: number;
  momentum: number | null;
  confidence: "high" | "moderate" | "limited";
  points: TrendPoint[];
}

export interface TrendOverview {
  fromDate: string;
  toDate: string;
  format: string;
  dimension: TrendDimension;
  tournamentCount: number;
  standingCount: number;
  publishedDeckCount: number;
  /** The population the shares are divided by; may be lower than publishedDeckCount. */
  chartedDeckCount: number;
  knownFieldPlayers: number;
  publishedCoverage: number;
  formats: string[];
  /** The whole archive, not the window: what is available behind the current range. */
  archiveFrom: string;
  archiveTo: string;
  archiveTournamentCount: number;
  series: TrendSeries[];
}

export interface Pairing {
  entityId: string;
  name: string;
  imageUrl: string;
  decks: number;
  share: number;
}

export interface CardAdoption {
  cardId: string;
  name: string;
  imageUrl: string;
  decks: number;
  inclusion: number;
  averageCopies: number;
}

export interface TrendDeck {
  deckId: string;
  name: string;
  legendId: string;
  legendName: string;
  championId: string;
  championName: string;
  legendImageUrl: string;
  championImageUrl: string;
  tournamentSlug: string;
  tournamentName: string;
  tournamentDate: string;
  placement: number;
  fieldSize: number;
  placementStrength: number;
  sourceUrl: string;
}

export interface ChampionMeta {
  championId: string;
  championName: string;
  imageUrl: string;
  domains: string[];
  overview: TrendSeries;
  tournamentCount: number;
  topEight: number;
  topSixteen: number;
  bestPlacement: number;
  bestFieldSize: number;
  averagePlacementStrength: number;
  pairings: Pairing[];
  cards: CardAdoption[];
  recentDecks: TrendDeck[];
}

export interface LegendMeta {
  legendId: string;
  legendName: string;
  imageUrl: string;
  domains: string[];
  overview: TrendSeries;
  tournamentCount: number;
  topEight: number;
  topSixteen: number;
  bestPlacement: number;
  bestFieldSize: number;
  averagePlacementStrength: number;
  champions: Pairing[];
  cards: CardAdoption[];
  recentDecks: TrendDeck[];
}

export interface TournamentEntity {
  entityId: string;
  name: string;
  decks: number;
  share: number;
}

export interface TournamentDetail {
  slug: string;
  name: string;
  date: string;
  format: string;
  players: number;
  winner: string;
  decksPublished: number;
  knownDeckCount: number;
  /** Complete lists that named a champion; the denominator of every champion share. */
  chartedDeckCount: number;
  publishedCoverage: number;
  confidence: "high" | "moderate" | "limited";
  champions: TournamentEntity[];
  decks: TrendDeck[];
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

export interface RefreshRun {
  startedAt: string;
  finishedAt: string;
  ok: boolean;
  promoted: boolean;
  snapshotId: string;
  deckCount: number;
  durationMs: number;
  message: string;
}

export interface RefreshStatus {
  enabled: boolean;
  status: "idle" | "running" | "off";
  intervalHours: number;
  nextRunAt: string;
  runs: number;
  failures: number;
  consecutiveFailures: number;
  snapshotAgeHours: number;
  stale: boolean;
  lastRun: RefreshRun | null;
  history: RefreshRun[];
}
