/** Typed API client. One place that knows about HTTP. */

import type {
  Archetype,
  AvailabilityProfile,
  BuildSuggestions,
  AvailabilityUpdate,
  CardFacets,
  CardPage,
  DeckPayload,
  DeckSummary,
  DeckView,
  Era,
  ForgetResult,
  FormatView,
  Health,
  MetaDeck,
  MetaStatus,
  CardDetail,
  CardTrendOverview,
  LegendChoice,
  LegendSort,
  LegendMeta,
  RefreshStatus,
  RuleKinds,
  SaveCollectionResult,
  SmartSession,
  Tournament,
  TournamentDetail,
  TrendBucket,
  TrendDimension,
  TrendOverview,
  ChampionMeta,
  Validation,
} from "./types";

/**
 * The API contract this page was built against.
 *
 * Must match `API_CONTRACT` in `server/riftbound/api/routes/system.py`. Raise both
 * together whenever a response gains a field the UI reads.
 */
export const EXPECTED_API_CONTRACT = 3;

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

  // A response that is not JSON is nearly always the SPA fallback catching an /api
  // path the server does not have -- a stale server, or a typo. Parsing it blind
  // reports `Unexpected token '<', "<!doctype "... is not valid JSON`, which sends
  // whoever reads it looking in entirely the wrong place.
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      throw new ApiError(
        `${path} returned ${response.status} as ${response.headers.get("content-type") ?? "an unknown type"} ` +
          "instead of JSON. If the page is newer than the server, restart the server.",
        response.status,
      );
    }
  }

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
  /** Restrict to what this legend may legally play. Its domains are a rule, not a filter. */
  legendId?: string;
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

  buildSuggestions: (deck: DeckPayload) =>
    request<BuildSuggestions>("/api/decks/suggestions", {
      method: "POST",
      body: JSON.stringify(deck),
    }),

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

  metaStatus: () => request<MetaStatus>("/api/meta/status"),
  metaArchetypes: (limit = 20) =>
    request<Archetype[]>(`/api/meta/archetypes${queryString({ limit })}`),
  metaDecks: (params: {
    archetype?: string;
    evidence?: string;
    buildableOnly?: boolean;
    limit?: number;
  } = {}) => request<MetaDeck[]>(`/api/meta/decks${queryString({ ...params })}`),
  metaTournaments: (limit = 30) =>
    request<Tournament[]>(`/api/meta/tournaments${queryString({ limit })}`),
  trendOverview: (params: {
    dimension: TrendDimension;
    from?: string;
    to?: string;
    format?: string;
    minPlayers?: number;
    /** "all" or a day count; resolved server-side against the archive. */
    range?: string;
    bucket?: TrendBucket;
    limit?: number;
    /** Banned-list window the win rates are scoped to; defaults to the current one. */
    era?: string;
    /** Append entities the archive knows but this window does not, scored 0. */
    includeDormant?: boolean;
  }) => request<TrendOverview>(`/api/meta/trends/overview${queryString({ ...params })}`),
  eras: () => request<Era[]>("/api/meta/eras"),
  championTrend: (championId: string, params: {
    from?: string;
    to?: string;
    format?: string;
    minPlayers?: number;
    /** "all" or a day count; resolved server-side against the archive. */
    range?: string;
    bucket?: TrendBucket;
  }) => request<ChampionMeta>(
    `/api/meta/trends/champions/${encodeURIComponent(championId)}${queryString({ ...params })}`,
  ),
  legendTrend: (legendId: string, params: {
    from?: string;
    to?: string;
    format?: string;
    minPlayers?: number;
    /** "all" or a day count; resolved server-side against the archive. */
    range?: string;
    bucket?: TrendBucket;
  }) => request<LegendMeta>(
    `/api/meta/trends/legends/${encodeURIComponent(legendId)}${queryString({ ...params })}`,
  ),
  tournamentDetail: (slug: string) =>
    request<TournamentDetail>(`/api/meta/tournaments/${encodeURIComponent(slug)}`),
  importMetaDeck: (deckId: string) =>
    request<{ deckId: string; name: string; source: string }>(
      `/api/meta/decks/${deckId}/import`,
      { method: "POST" },
    ),

  cardTrends: (params: {
    from?: string; to?: string; format?: string; minPlayers?: number;
    range?: string; bucket?: string; cardType?: string; limit?: number;
  } = {}) => request<CardTrendOverview>(`/api/meta/trends/cards${queryString({ ...params })}`),
  cardTrendDetail: (cardId: string, params: {
    from?: string; to?: string; format?: string; minPlayers?: number;
    range?: string; bucket?: string;
  } = {}) =>
    request<CardDetail>(
      `/api/meta/trends/cards/${encodeURIComponent(cardId)}${queryString({ ...params })}`,
    ),

  refreshStatus: () => request<RefreshStatus>("/api/meta/refresh"),
  refreshNow: () => request<RefreshStatus>("/api/meta/refresh", { method: "POST" }),

  smartLegends: (sort: LegendSort = "strength") =>
    request<LegendChoice[]>(`/api/smart-decks/legends?sort=${sort}`),
  smartSessions: () => request<SmartSession[]>("/api/smart-decks/sessions"),
  /** Erase the collection and every wizard session. Both, deliberately. */
  forgetCollection: () =>
    request<ForgetResult>("/api/availability/collection", { method: "DELETE" }),
  startSmartSession: (legendId: string) =>
    request<SmartSession>("/api/smart-decks/sessions", {
      method: "POST",
      body: JSON.stringify({ legendId }),
    }),
  getSmartSession: (sessionId: string) =>
    request<SmartSession>(`/api/smart-decks/sessions/${sessionId}`),
  /**
   * Answer one round.
   *
   * `asked` is required for a checklist and must list every card the question showed:
   * a card left at zero means "I own none", while a card that was never asked means
   * "we do not know". Dropping the distinction is what produces a wrong "you cannot
   * build this".
   */
  answerSmartSession: (
    sessionId: string,
    answer: { deckId?: string; have: Record<string, number>; asked?: string[] },
  ) =>
    request<SmartSession>(`/api/smart-decks/sessions/${sessionId}/answer`, {
      method: "POST",
      body: JSON.stringify(answer),
    }),
  /** Rule cards out by preference. The whole set, not a delta. */
  declineSmartCards: (sessionId: string, cardIds: string[]) =>
    request<SmartSession>(`/api/smart-decks/sessions/${sessionId}/decline`, {
      method: "POST",
      body: JSON.stringify({ cardIds }),
    }),
  acceptSmartDeck: (sessionId: string, which: string, name?: string) =>
    request<SmartSession>(`/api/smart-decks/sessions/${sessionId}/accept`, {
      method: "POST",
      body: JSON.stringify({ which, ...(name ? { name } : {}) }),
    }),
  saveSmartCollection: (sessionId: string) =>
    request<SaveCollectionResult>(
      `/api/smart-decks/sessions/${sessionId}/save-collection`,
      { method: "POST", body: JSON.stringify({}) },
    ),
  deleteSmartSession: (sessionId: string) =>
    request<void>(`/api/smart-decks/sessions/${sessionId}`, { method: "DELETE" }),
};
