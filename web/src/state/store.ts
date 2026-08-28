/**
 * Application state.
 *
 * One store, but with a typed shape and a subscribe/notify boundary, so a feature
 * module reads what it needs and cannot silently reach into another's slice --
 * v2 had a single global mutable object that any of its 352 functions could rewrite.
 */

import type {
  Archetype,
  AvailabilityProfile,
  BuildSuggestions,
  CardAvailability,
  CardFacets,
  DeckPayload,
  DeckSummary,
  FormatView,
  LegendChoice,
  LegendSort,
  LegendMeta,
  MetaDeck,
  MetaStatus,
  RefreshStatus,
  SmartSession,
  CardDetail,
  CardTrendOverview,
  ChampionMeta,
  TournamentDetail,
  TrendBucket,
  TrendDimension,
  TrendOverview,
  Validation,
} from "../api/types";

export interface CardFilters {
  q: string;
  cardType: string;
  domain: string;
  setCode: string;
  rarity: string;
  availableOnly: boolean;
  sort: "name" | "cost" | "availability";
}

/** Which top-level view is showing. */
export type ViewName = "find" | "explore" | "build" | "decks";

/**
 * Explore answers two different questions and must not blur them.
 *
 * "legends" ranks the field by what is winning -- shares that partition the metagame.
 * "cards" reports what is being played -- adoption, which does not. Same page, same
 * filters, deliberately separate numbers.
 */
export type ExploreMode = "legends" | "cards";

export interface AppState {
  ready: boolean;
  error: string;
  /**
   * Set when the running server is older than this page.
   *
   * Sticky and non-dismissable: every feature added since that server started will
   * misbehave, and the failures look like unrelated bugs rather than one stale process.
   */
  staleServer: string;
  view: ViewName;
  notice: string;
  formats: FormatView[];
  facets: CardFacets | null;

  deckId: string;
  deck: DeckPayload;
  validation: Validation | null;
  dirty: boolean;
  savedDecks: DeckSummary[];

  availability: AvailabilityProfile | null;

  filters: CardFilters;
  cards: CardAvailability[];
  cardTotal: number;
  cardsLoading: boolean;
  cardLimit: number;
  builderReview: boolean;
  /** Cards referenced by the deck, resolved for display. */
  deckCards: Map<string, CardAvailability>;
  /** What to add next, for the deck as it stands. Null until the first fetch lands. */
  suggestions: BuildSuggestions | null;

  metaStatus: MetaStatus | null;
  archetypes: Archetype[];
  metaDecks: MetaDeck[];
  metaLoading: boolean;
  /** Archetype currently expanded in the meta view; "" shows the ranked overview. */
  metaArchetype: string;
  metaBuildableOnly: boolean;

  /** Smart Decks. `smartAnswers` is the in-progress round, keyed by cardId. */
  smartLegends: LegendChoice[];
  smartSession: SmartSession | null;
  smartAnswers: Map<string, number>;
  smartBusy: boolean;
  smartFinished: boolean;
  /**
   * Which wizard screen to show. "rounds" is the question flow; "finish" is the deck it
   * produced, with what changed and a last pass to rule cards out.
   */
  smartShowing: "rounds" | "finish";
  /**
   * Unfinished sessions, so one survives a closed tab. The answers are the expensive
   * part — three rounds pin down roughly 75 cards — and until this was surfaced they
   * were written to the database and then unreachable.
   */
  smartResumable: SmartSession[];
  /** Legend picker filter, so a 49-legend list stays navigable. */
  smartLegendQuery: string;
  smartLegendSort: LegendSort;
  /**
   * Why the legend list is empty, when it is.
   *
   * Distinct from "there are no legends": an empty list because the request failed is
   * a different problem with a different fix, and telling somebody to run the meta
   * pipeline when the real fault is a stale server sends them somewhere useless.
   */
  smartLegendsError: string;
  smartLegendsLoaded: boolean;
  /**
   * How many times loading the legends has failed in a row.
   *
   * Drives the difference between "that did not work, try again" and "that has not
   * worked twice, here is the thing to actually go and do". Without it a retry that
   * fails identically looks like a button that does nothing.
   */
  smartLegendsAttempts: number;
  smartLegendsRetrying: boolean;
  refresh: RefreshStatus | null;
  refreshBusy: boolean;

  exploreDimension: TrendDimension;
  exploreFormat: string;
  exploreFrom: string;
  exploreTo: string;
  exploreMinPlayers: number;
  /**
   * The chosen range, resolved by the server: "" for its default, "all", or a day count.
   *
   * Held as the request rather than as two computed dates, because computing them here
   * needs the archive's span, and not having it yet is what made "All time" ask for
   * nothing and get ninety days back.
   */
  exploreRange: string;
  exploreBucket: TrendBucket;
  trendOverview: TrendOverview | null;
  /** Which question Explore is answering: what is winning, or what is being played. */
  exploreMode: ExploreMode;
  /** The card wall, and the one card being read. */
  cardTrends: CardTrendOverview | null;
  cardDetail: CardDetail | null;
  exploreCardType: string;
  championMeta: ChampionMeta | null;
  legendMeta: LegendMeta | null;
  tournamentDetail: TournamentDetail | null;
  exploreLoading: boolean;
  exploreError: string;

}

export function emptyDeck(): DeckPayload {
  return {
    name: "Untitled Deck",
    format: "constructed",
    legendId: "",
    championId: "",
    main: {},
    runes: {},
    battlefields: [],
    sideboard: {},
  };
}

const initial: AppState = {
  ready: false,
  error: "",
  staleServer: "",
  view: "find",
  notice: "",
  formats: [],
  facets: null,

  deckId: "",
  deck: emptyDeck(),
  validation: null,
  dirty: false,
  savedDecks: [],

  availability: null,

  filters: {
    q: "",
    cardType: "",
    domain: "",
    setCode: "",
    rarity: "",
    availableOnly: false,
    sort: "availability",
  },
  cards: [],
  cardTotal: 0,
  cardsLoading: false,
  cardLimit: 24,
  builderReview: false,
  deckCards: new Map(),
  suggestions: null,

  metaStatus: null,
  archetypes: [],
  metaDecks: [],
  metaLoading: false,
  metaArchetype: "",
  metaBuildableOnly: false,

  smartLegends: [],
  smartSession: null,
  smartAnswers: new Map(),
  smartBusy: false,
  smartFinished: false,
  smartShowing: "rounds",
  smartResumable: [],
  smartLegendQuery: "",
  smartLegendSort: "strength",
  smartLegendsError: "",
  smartLegendsLoaded: false,
  smartLegendsAttempts: 0,
  smartLegendsRetrying: false,
  refresh: null,
  refreshBusy: false,

  exploreMode: "legends",
  cardTrends: null,
  cardDetail: null,
  exploreCardType: "",
  exploreDimension: "champion",
  exploreFormat: "",
  exploreFrom: "",
  exploreTo: "",
  exploreMinPlayers: 16,
  exploreRange: "",
  exploreBucket: "week",
  trendOverview: null,
  championMeta: null,
  legendMeta: null,
  tournamentDetail: null,
  exploreLoading: false,
  exploreError: "",

};

type Listener = (state: AppState) => void;

class Store {
  #state: AppState = initial;
  #listeners = new Set<Listener>();

  get state(): Readonly<AppState> {
    return this.#state;
  }

  set(patch: Partial<AppState>): void {
    this.#state = { ...this.#state, ...patch };
    for (const listener of this.#listeners) listener(this.#state);
  }

  subscribe(listener: Listener): () => void {
    this.#listeners.add(listener);
    listener(this.#state);
    return () => this.#listeners.delete(listener);
  }
}

export const store = new Store();
