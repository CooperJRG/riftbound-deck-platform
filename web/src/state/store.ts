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
  CardAvailability,
  CardFacets,
  DeckPayload,
  DeckSummary,
  FormatView,
  MetaDeck,
  MetaStatus,
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
export type ViewName = "build" | "meta";

export interface AppState {
  ready: boolean;
  error: string;
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
  /** Cards referenced by the deck, resolved for display. */
  deckCards: Map<string, CardAvailability>;

  metaStatus: MetaStatus | null;
  archetypes: Archetype[];
  metaDecks: MetaDeck[];
  metaLoading: boolean;
  /** Archetype currently expanded in the meta view; "" shows the ranked overview. */
  metaArchetype: string;
  metaBuildableOnly: boolean;
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
  view: "build",
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
  deckCards: new Map(),

  metaStatus: null,
  archetypes: [],
  metaDecks: [],
  metaLoading: false,
  metaArchetype: "",
  metaBuildableOnly: false,
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
