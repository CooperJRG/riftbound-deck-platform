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

/**
 * How an entity actually fared, as opposed to how much of the field it occupies.
 *
 * `shown` is the field to branch on. When it is false the rate and interval are still
 * populated but are not fit to print -- render `withheldDetail` instead, which is
 * already written in plain English by the server. Do not re-derive the thresholds
 * here; a client holding its own copy is a second policy and only one of them is
 * tested.
 */
export interface Performance {
  entityId: string;
  name: string;
  decksWithRecords: number;
  /** Every match, draws included. The sample size. */
  matches: number;
  /** Matches with a winner: the win-rate denominator. Draws are neither. */
  decisive: number;
  wins: number;
  losses: number;
  draws: number;
  events: number;
  pilots: number;
  topPilotShare: number;
  winRate: number;
  intervalLow: number;
  intervalHigh: number;
  /** The whole 95% interval sits above even — the only safe "this wins". */
  separated: boolean;
  shown: boolean;
  withheldReason: "" | "matches" | "events" | "pilot-concentration";
  withheldDetail: string;
}

/** What the win rates are a rate *of*. Render it beside them, never in a tooltip. */
export interface PerformanceBasis {
  eraId: string;
  eraName: string;
  eraFrom: string;
  eraTo: string;
  /** False while the era boundary is derived from the archive, not cited. */
  eraCited: boolean;
  eraEvidence: string;
  entitiesMeasured: number;
  entitiesShown: number;
  entitiesWithheld: number;
  decksWithRecords: number;
  totalMatches: number;
  publishedWinRate: number;
  unpublishedWinRate: number;
  publishedStandings: number;
  unpublishedStandings: number;
  publicationGap: number;
  /** The sentence that has to appear wherever a rate does. */
  caveat: string;
}

export interface Era {
  eraId: string;
  name: string;
  fromDate: string;
  toDate: string;
  isOpen: boolean;
  isCited: boolean;
  evidence: string;
  bansIntroduced: string[];
}

/**
 * Where an entity placed, as a number a reader can act on.
 *
 * 0-100, and both ends mean something: 100 is leading the field on presence, event
 * breadth and momentum at once; 0 is having no lists in the selected range. The three
 * component fields sum to `score`, so a card can show its own working.
 *
 * Computed by the server. Do not re-derive it here — this ranking used to live in the
 * client, which made it the one piece of ranking policy with no tests behind it.
 */
export interface Rank {
  position: number;
  score: number;
  tier: "S" | "A" | "B" | "C" | "D";
  /** False when the entity had no lists in range: score 0, ordered by the archive. */
  ranked: boolean;
  presencePoints: number;
  breadthPoints: number;
  momentumPoints: number;
  /** Only meaningful when `ranked` is false — what orders the dormant tail. */
  priorShare: number;
  priorMomentum: number | null;
  lastSeen: string;
  /** The line to print under the number, phrased server-side. */
  summary: string;
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
  /**
   * `null` means no match records reached this entity at all — a different statement
   * from "we have records and they are too thin", which arrives as an object with
   * `shown: false`. Render the two differently.
   */
  performance: Performance | null;
  /** Rank, rating and tier. `series` arrives already in rank order. */
  rank: Rank | null;
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
  /** Null when the caller asked for presence only. */
  performanceBasis: PerformanceBasis | null;
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
