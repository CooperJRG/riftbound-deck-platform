/** Typed API client. One place that knows about HTTP. */

import type {
  AvailabilityProfile,
  AvailabilityUpdate,
  CardFacets,
  CardPage,
  DeckPayload,
  DeckSummary,
  DeckView,
  FormatView,
  Health,
  RuleKinds,
  Validation,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload: unknown = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : response.statusText;
    throw new ApiError(
      typeof detail === "string" ? detail : JSON.stringify(detail),
      response.status,
    );
  }
  return payload as T;
}

export interface CardQuery {
  q?: string;
  cardType?: string;
  domain?: string;
  setCode?: string;
  rarity?: string;
  availableOnly?: boolean;
  sort?: "name" | "cost" | "availability";
  offset?: number;
  limit?: number;
}

function queryString(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "" || value === false) continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  health: () => request<Health>("/api/health"),
  formats: () => request<FormatView[]>("/api/formats"),

  cards: (query: CardQuery = {}) =>
    request<CardPage>(`/api/cards${queryString({ ...query })}`),
  facets: () => request<CardFacets>("/api/cards/facets"),

  validateDeck: (deck: DeckPayload) =>
    request<Validation>("/api/decks/validate", {
      method: "POST",
      body: JSON.stringify(deck),
    }),

  listDecks: () => request<DeckSummary[]>("/api/decks"),
  createDeck: (deck: DeckPayload) =>
    request<DeckView>("/api/decks", { method: "POST", body: JSON.stringify(deck) }),
  getDeck: (deckId: string) => request<DeckView>(`/api/decks/${deckId}`),
  updateDeck: (deckId: string, deck: DeckPayload) =>
    request<DeckView>(`/api/decks/${deckId}`, {
      method: "PUT",
      body: JSON.stringify(deck),
    }),
  deleteDeck: (deckId: string) =>
    request<void>(`/api/decks/${deckId}`, { method: "DELETE" }),

  availability: () => request<AvailabilityProfile>("/api/availability"),
  setAvailability: (update: AvailabilityUpdate) =>
    request<AvailabilityProfile>("/api/availability", {
      method: "PUT",
      body: JSON.stringify(update),
    }),
  excludeCard: (cardId: string) =>
    request<AvailabilityProfile>(`/api/availability/exclude/${cardId}`, {
      method: "POST",
    }),
  unexcludeCard: (cardId: string) =>
    request<AvailabilityProfile>(`/api/availability/exclude/${cardId}`, {
      method: "DELETE",
    }),
  ruleKinds: () => request<RuleKinds>("/api/availability/rule-kinds"),
};
