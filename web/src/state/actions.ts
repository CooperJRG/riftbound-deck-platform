/** Every state transition. Views call these; they never mutate state directly. */

import { ApiError, EXPECTED_API_CONTRACT, api } from "../api/client";
import type {
  Card,
  CardAvailability,
  DeckPayload,
  SmartSession,
  TrendBucket,
  Zone,
  AvailabilityMode,
} from "../api/types";
import { debounce } from "../ui/dom";
import { emptyDeck, store, type ExploreMode, type ViewName } from "./store";

/**
 * Where a card belongs, from its type. One "add" affordance, right zone.
 *
 * The chosen champion is not a placement: a champion is added to the main deck like
 * any other unit and then *nominated*, so it is not one of the outcomes here.
 */
export function zoneFor(card: Card): Zone | "legend" {
  if (card.cardType === "Legend") return "legend";
  if (card.cardType === "Rune") return "runes";
  if (card.cardType === "Battlefield") return "battlefields";
  return "main";
}

function reportError(error: unknown): void {
  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : String(error);
  store.set({ error: message });
}

export async function boot(): Promise<void> {
  try {
    const [health, formats, facets, availability, savedDecks] = await Promise.all([
      // Checked first, because everything after it can fail in confusing ways when the
      // answer is "your server is older than this page".
      api.health().catch(() => null),
      api.formats(),
      api.facets(),
      api.availability(),
      api.listDecks(),
    ]);
    const contract = health?.apiContract ?? 0;
    const staleServer =
      contract < EXPECTED_API_CONTRACT
        ? "This page is newer than the server it is talking to, so parts of it will " +
          "not work. Stop the server and start it again to pick up the current code."
        : "";
    store.set({
      formats, facets, availability, savedDecks, staleServer, ready: true, error: "",
    });
    await Promise.all([refreshCards(), revalidate()]);
  } catch (error) {
    reportError(error);
    store.set({ ready: true });
  }
}

// -- cards --------------------------------------------------------------------

export async function refreshCards(): Promise<void> {
  const { filters, cardLimit } = store.state;
  store.set({ cardsLoading: true });
  try {
    const page = await api.cards({ ...filters, limit: cardLimit });
    store.set({ cards: page.cards, cardTotal: page.total, cardsLoading: false });
    indexDeckCards(page.cards);
  } catch (error) {
    reportError(error);
    store.set({ cardsLoading: false });
  }
}

const refreshCardsDebounced = debounce(() => void refreshCards(), 180);

export function setFilter<K extends keyof typeof store.state.filters>(
  key: K,
  value: (typeof store.state.filters)[K],
): void {
  store.set({ filters: { ...store.state.filters, [key]: value }, cardLimit: 24 });
  refreshCardsDebounced();
}

export function showMoreCards(): void {
  store.set({ cardLimit: Math.min(store.state.cardLimit + 24, 120) });
  void refreshCards();
}

/**
 * Keep a lookup of the cards the deck references.
 *
 * Cards drop out of the filtered listing as the player searches, but the deck panel
 * still has to render them, so resolved cards are remembered rather than re-fetched.
 */
function indexDeckCards(rows: CardAvailability[]): void {
  const next = new Map(store.state.deckCards);
  for (const row of rows) next.set(row.card.cardId, row);
  store.set({ deckCards: next });
}

/** Fetch any deck card we have not seen, so a loaded deck renders fully. */
async function resolveDeckCards(deck: DeckPayload): Promise<void> {
  const needed = new Set<string>([
    ...Object.keys(deck.main),
    ...Object.keys(deck.runes),
    ...Object.keys(deck.sideboard),
    ...deck.battlefields,
    deck.legendId,
    deck.championId,
  ]);
  needed.delete("");

  const missing = [...needed].filter((id) => !store.state.deckCards.has(id));
  if (missing.length === 0) return;

  const found = await Promise.all(
    missing.map(async (id) => {
      try {
        const page = await api.cards({ q: id, limit: 1 });
        return page.cards[0] ?? null;
      } catch {
        return null;
      }
    }),
  );
  indexDeckCards(found.filter((row): row is CardAvailability => row !== null));
}

// -- deck editing -------------------------------------------------------------

function commit(deck: DeckPayload): void {
  store.set({ deck, dirty: true });
  revalidateDebounced();
}

export function adjustCard(cardId: string, zone: Zone, delta: number): void {
  const deck = store.state.deck;
  if (zone === "battlefields") {
    const present = deck.battlefields.includes(cardId);
    const battlefields =
      delta > 0
        ? present
          ? deck.battlefields
          : [...deck.battlefields, cardId]
        : deck.battlefields.filter((id) => id !== cardId);
    commit({ ...deck, battlefields });
    return;
  }
  const counts = { ...deck[zone] };
  const next = (counts[cardId] ?? 0) + delta;
  if (next > 0) counts[cardId] = next;
  else delete counts[cardId];
  commit({ ...deck, [zone]: counts });
}

/** Add a card to wherever it belongs. */
export function addCard(card: Card): void {
  const target = zoneFor(card);
  if (target === "legend") {
    commit({ ...store.state.deck, legendId: card.cardId });
    return;
  }
  adjustCard(card.cardId, target, 1);
}

export function setChampion(cardId: string): void {
  commit({ ...store.state.deck, championId: cardId });
}

export function setLegend(cardId: string): void {
  commit({ ...store.state.deck, legendId: cardId });
}

export function setDeckName(name: string): void {
  commit({ ...store.state.deck, name });
}

export function setDeckFormat(format: string): void {
  commit({ ...store.state.deck, format });
}

export async function revalidate(): Promise<void> {
  try {
    const validation = await api.validateDeck(store.state.deck);
    store.set({ validation, error: "" });
    void resolveDeckCards(store.state.deck);
  } catch (error) {
    reportError(error);
  }
}

const revalidateDebounced = debounce(() => void revalidate(), 200);

// -- deck persistence ---------------------------------------------------------

export async function saveDeck(): Promise<void> {
  const { deck, deckId } = store.state;
  try {
    const saved = deckId
      ? await api.updateDeck(deckId, deck)
      : await api.createDeck(deck);
    store.set({
      deckId: saved.deckId,
      validation: saved.validation,
      dirty: false,
      savedDecks: await api.listDecks(),
      error: "",
    });
  } catch (error) {
    reportError(error);
  }
}

export async function loadDeck(deckId: string): Promise<void> {
  try {
    const view = await api.getDeck(deckId);
    store.set({
      deckId: view.deckId,
      deck: view.deck,
      validation: view.validation,
      dirty: false,
      error: "",
    });
    await resolveDeckCards(view.deck);
  } catch (error) {
    reportError(error);
  }
}

export async function deleteDeck(deckId: string): Promise<void> {
  try {
    await api.deleteDeck(deckId);
    const savedDecks = await api.listDecks();
    if (store.state.deckId === deckId) newDeck();
    store.set({ savedDecks });
  } catch (error) {
    reportError(error);
  }
}

export function newDeck(): void {
  store.set({ deckId: "", deck: emptyDeck(), dirty: false, builderReview: false });
  void revalidate();
}

export function setBuilderReview(reviewing: boolean): void {
  store.set({ builderReview: reviewing });
}

// -- availability -------------------------------------------------------------

async function applyAvailability(
  next: Promise<Awaited<ReturnType<typeof api.availability>>>,
): Promise<void> {
  try {
    store.set({ availability: await next, error: "" });
    await Promise.all([refreshCards(), revalidate()]);
  } catch (error) {
    reportError(error);
  }
}

export async function setAvailabilityMode(mode: AvailabilityMode): Promise<void> {
  const current = store.state.availability;
  await applyAvailability(
    api.setAvailability({
      mode,
      strict: current?.strict ?? false,
      excludedCardIds: (current?.excludedCards ?? []).map((c) => c.cardId),
      rules: (current?.rules ?? []).map((r) => ({ kind: r.kind, value: r.value })),
    }),
  );
}

export async function setStrict(strict: boolean): Promise<void> {
  const current = store.state.availability;
  if (!current) return;
  await applyAvailability(
    api.setAvailability({
      mode: current.mode,
      strict,
      excludedCardIds: current.excludedCards.map((c) => c.cardId),
      rules: current.rules.map((r) => ({ kind: r.kind, value: r.value })),
    }),
  );
}

export async function excludeCard(cardId: string): Promise<void> {
  await applyAvailability(api.excludeCard(cardId));
}

export async function unexcludeCard(cardId: string): Promise<void> {
  await applyAvailability(api.unexcludeCard(cardId));
}

export async function toggleRule(kind: string, value: string): Promise<void> {
  const current = store.state.availability;
  if (!current) return;
  const exists = current.rules.some((r) => r.kind === kind && r.value === value);
  const rules = exists
    ? current.rules.filter((r) => !(r.kind === kind && r.value === value))
    : [...current.rules, { kind, value, description: "" }];
  await applyAvailability(
    api.setAvailability({
      mode: "exclusion",
      strict: current.strict,
      excludedCardIds: current.excludedCards.map((c) => c.cardId),
      rules: rules.map((r) => ({ kind: r.kind, value: r.value })),
    }),
  );
}

export function dismissError(): void {
  store.set({ error: "" });
}

// -- views --------------------------------------------------------------------

export function setView(view: ViewName): void {
  store.set({ view });
  if (view === "find") void openSmartDecks();
  if (view === "explore" && store.state.trendOverview === null) void loadExplore();
}

export function dismissNotice(): void {
  store.set({ notice: "" });
}

// -- explorer ----------------------------------------------------------------

function exploreParams(): {
  from?: string;
  to?: string;
  format?: string;
  minPlayers: number;
  bucket: TrendBucket;
} {
  const state = store.state;
  return {
    ...(state.exploreFrom ? { from: state.exploreFrom } : {}),
    ...(state.exploreTo ? { to: state.exploreTo } : {}),
    ...(state.exploreFormat ? { format: state.exploreFormat } : {}),
    minPlayers: state.exploreMinPlayers,
    bucket: state.exploreBucket,
  };
}

export async function loadExplore(): Promise<void> {
  store.set({ exploreLoading: true, exploreError: "", championMeta: null, legendMeta: null, tournamentDetail: null });
  try {
    const [trendOverview, smartLegends] = await Promise.all([
      api.trendOverview({ dimension: "legend", ...exploreParams(), limit: 50 }),
      store.state.smartLegends.length ? Promise.resolve(store.state.smartLegends) : api.smartLegends(),
    ]);
    store.set({ trendOverview, smartLegends, smartLegendsLoaded: true, exploreLoading: false });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    store.set({ exploreLoading: false, exploreError: message });
  }
}

export function setExploreFilter(
  key: "exploreFormat" | "exploreFrom" | "exploreTo" | "exploreMinPlayers" | "exploreBucket",
  value: string | number,
): void {
  store.set({ [key]: value } as Partial<typeof store.state>);
  void loadExplore();
}

export async function openChampion(championId: string): Promise<void> {
  store.set({ exploreLoading: true, exploreError: "", legendMeta: null, tournamentDetail: null });
  try {
    const championMeta = await api.championTrend(championId, exploreParams());
    store.set({ championMeta, exploreLoading: false });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    store.set({ exploreLoading: false, exploreError: message });
  }
}

export async function openLegend(legendId: string): Promise<void> {
  store.set({ exploreLoading: true, exploreError: "", championMeta: null, tournamentDetail: null });
  try {
    const legendMeta = await api.legendTrend(legendId, exploreParams());
    store.set({ legendMeta, exploreLoading: false });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    store.set({ exploreLoading: false, exploreError: message });
  }
}

export async function openTournament(slug: string): Promise<void> {
  store.set({ exploreLoading: true, exploreError: "" });
  try {
    const tournamentDetail = await api.tournamentDetail(slug);
    store.set({ tournamentDetail, exploreLoading: false });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    store.set({ exploreLoading: false, exploreError: message });
  }
}

export function closeExploreDetail(): void {
  store.set({ championMeta: null, legendMeta: null, tournamentDetail: null });
}

// -- meta ---------------------------------------------------------------------

export async function loadMeta(): Promise<void> {
  store.set({ metaLoading: true });
  try {
    const status = await api.metaStatus();
    if (!status.available) {
      store.set({ metaStatus: status, archetypes: [], metaDecks: [], metaLoading: false });
      return;
    }
    const [archetypes, metaDecks] = await Promise.all([
      api.metaArchetypes(20),
      api.metaDecks({ limit: 40, buildableOnly: store.state.metaBuildableOnly }),
    ]);
    store.set({ metaStatus: status, archetypes, metaDecks, metaLoading: false, error: "" });
  } catch (error) {
    reportError(error);
    store.set({ metaLoading: false });
  }
}

export async function openArchetype(archetypeId: string): Promise<void> {
  store.set({ metaArchetype: archetypeId, metaLoading: true });
  try {
    const metaDecks = await api.metaDecks({
      archetype: archetypeId || undefined,
      limit: 40,
      buildableOnly: store.state.metaBuildableOnly,
    } as Parameters<typeof api.metaDecks>[0]);
    store.set({ metaDecks, metaLoading: false });
  } catch (error) {
    reportError(error);
    store.set({ metaLoading: false });
  }
}

export async function setMetaBuildableOnly(only: boolean): Promise<void> {
  store.set({ metaBuildableOnly: only });
  await openArchetype(store.state.metaArchetype);
}

/** Copy a meta deck into the library and open it in the builder. */
export async function importMetaDeck(deckId: string): Promise<void> {
  try {
    const created = await api.importMetaDeck(deckId);
    store.set({
      savedDecks: await api.listDecks(),
      notice: `Imported "${created.name}" into your decks.`,
    });
    await loadDeck(created.deckId);
    store.set({ view: "build" });
  } catch (error) {
    reportError(error);
  }
}

// -- smart decks --------------------------------------------------------------

/**
 * The answers for the round on screen.
 *
 * Seeded from the requirement rows, which default to "you have what this asks for".
 * That default is the whole ergonomic argument: the common answer is yes, so the
 * common answer should cost no clicks, and the player only touches the rows where
 * they are short.
 */
function seedAnswers(session: SmartSession | null): Map<string, number> {
  const answers = new Map<string, number>();
  const proposal = session?.proposal;
  if (!proposal) return answers;
  const rows = proposal.question ? proposal.question.cards : proposal.requirements;
  for (const row of rows) answers.set(row.cardId, row.have);
  return answers;
}

export async function openSmartDecks(options: { retry?: boolean } = {}): Promise<void> {
  store.set({ view: "find" });
  if (store.state.smartLegendsLoaded && store.state.smartLegends.length) return;

  // A retry keeps the error panel on screen and marks the button busy, rather than
  // swapping in a loading state. Against a local server the request finishes in
  // milliseconds, so a flash of "Loading..." followed by the identical error reads as
  // a button that did nothing at all -- which is how a working retry got reported as
  // broken.
  store.set(
    options.retry
      ? { smartLegendsRetrying: true }
      : { smartBusy: true, smartLegendsError: "" },
  );
  try {
    const [smartLegends, refresh] = await Promise.all([
      api.smartLegends(),
      // Best-effort: the picker is still usable without it.
      api.refreshStatus().catch(() => null),
    ]);
    store.set({
      smartLegends,
      refresh,
      smartBusy: false,
      smartLegendsRetrying: false,
      smartLegendsLoaded: true,
      smartLegendsError: "",
      smartLegendsAttempts: 0,
    });
  } catch (error) {
    // Record why rather than falling through to an empty list. An empty picker after
    // a failed request is not "no decks are loaded", and saying so sends somebody to
    // run a pipeline that was never the problem.
    const message = error instanceof Error ? error.message : String(error);
    store.set({
      smartBusy: false,
      smartLegendsRetrying: false,
      smartLegendsLoaded: true,
      smartLegendsError: message,
      smartLegendsAttempts: store.state.smartLegendsAttempts + 1,
    });
  }
}

export function retrySmartLegends(): Promise<void> {
  return openSmartDecks({ retry: true });
}

/**
 * Harvest now rather than waiting for the timer.
 *
 * The answer to "run the meta pipeline" for somebody looking at a web page who does
 * not want to go and find a terminal.
 */
export async function refreshMetaNow(): Promise<void> {
  store.set({ refreshBusy: true });
  try {
    const refresh = await api.refreshNow();
    const run = refresh.lastRun;
    store.set({
      refresh,
      refreshBusy: false,
      smartLegendsLoaded: false,
      notice: run?.ok
        ? `Meta updated: ${run.deckCount} decks.`
        : `Refresh did not complete. ${run?.message ?? ""}`.trim(),
    });
    // The snapshot changed underneath us, so anything derived from it is stale.
    await Promise.all([openSmartDecks(), loadMeta()]);
  } catch (error) {
    reportError(error);
    store.set({ refreshBusy: false });
  }
}

export function setSmartLegendQuery(query: string): void {
  store.set({ smartLegendQuery: query });
}

export async function startSmartSession(legendId: string): Promise<void> {
  store.set({ smartBusy: true, smartFinished: false });
  try {
    const session = await api.startSmartSession(legendId);
    store.set({ smartSession: session, smartAnswers: seedAnswers(session), smartBusy: false });
  } catch (error) {
    reportError(error);
    store.set({ smartBusy: false });
  }
}

/** Record one card's count for the round on screen. Nothing is sent until submit. */
export function setSmartAnswer(cardId: string, count: number): void {
  const answers = new Map(store.state.smartAnswers);
  answers.set(cardId, Math.max(0, count));
  store.set({ smartAnswers: answers });
}

export async function submitSmartRound(): Promise<void> {
  const { smartSession, smartAnswers } = store.state;
  const proposal = smartSession?.proposal;
  if (!smartSession || !proposal) return;

  const have: Record<string, number> = {};
  for (const [cardId, count] of smartAnswers) have[cardId] = count;

  store.set({ smartBusy: true });
  try {
    const next = await api.answerSmartSession(
      smartSession.sessionId,
      proposal.question
        ? // A checklist must name every card it showed. Without that, a card left at
          // zero is indistinguishable from one never asked about.
          { have, asked: proposal.question.cards.map((row) => row.cardId) }
        : { deckId: proposal.deck?.deckId ?? "", have },
    );
    store.set({ smartSession: next, smartAnswers: seedAnswers(next), smartBusy: false });
  } catch (error) {
    reportError(error);
    store.set({ smartBusy: false });
  }
}

/** Take one of the offered decks into the library and open it in the builder. */
export async function acceptSmartDeck(which: "floor" | "conservative" | "free"): Promise<void> {
  const { smartSession } = store.state;
  if (!smartSession) return;
  store.set({ smartBusy: true });
  try {
    const finished = await api.acceptSmartDeck(smartSession.sessionId, which);
    store.set({
      smartSession: finished,
      smartFinished: true,
      smartBusy: false,
      savedDecks: await api.listDecks(),
      notice: "Saved to your decks.",
    });
    await loadDeck(finished.savedDeckId);
  } catch (error) {
    reportError(error);
    store.set({ smartBusy: false });
  }
}

/**
 * Opt-in write-back of what the session learned.
 *
 * Only ever called from an explicit button. "I don't have this, for this deck, right
 * now" is not the same claim as "I do not own this card", and someone answering
 * quickly to get a deck should not have a permanent fact recorded on their behalf.
 */
export async function saveSmartCollection(): Promise<void> {
  const { smartSession } = store.state;
  if (!smartSession) return;
  store.set({ smartBusy: true });
  try {
    const result = await api.saveSmartCollection(smartSession.sessionId);
    const skipped = result.skippedLowerBounds
      ? ` ${result.skippedLowerBounds} left alone, because "I have them all" is not a count.`
      : "";
    store.set({
      smartBusy: false,
      availability: await api.availability(),
      notice: `Saved ${result.copiesWritten} copies of ${result.cardsWritten} cards to your collection.${skipped}`,
    });
  } catch (error) {
    reportError(error);
    store.set({ smartBusy: false });
  }
}

export function closeSmartSession(): void {
  store.set({
    smartSession: null,
    smartAnswers: new Map(),
    smartFinished: false,
  });
}

// -- cards in the meta --------------------------------------------------------

/**
 * The card wall.
 *
 * Tracked separately from legends and champions because the numbers mean different
 * things: a champion's share is a partition of the field, a card's adoption is not.
 * Keeping them in different state, fetched from different endpoints, is what stops one
 * being rendered with the other's labels.
 */
export async function loadCardTrends(): Promise<void> {
  store.set({ exploreLoading: true, exploreError: "", cardDetail: null });
  try {
    const cardTrends = await api.cardTrends({
      ...exploreParams(),
      ...(store.state.exploreCardType ? { cardType: store.state.exploreCardType } : {}),
      limit: 60,
    });
    store.set({ cardTrends, exploreLoading: false });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    store.set({ exploreLoading: false, exploreError: message });
  }
}

export async function openCard(cardId: string): Promise<void> {
  store.set({
    exploreLoading: true, exploreError: "",
    legendMeta: null, championMeta: null, tournamentDetail: null,
  });
  try {
    const cardDetail = await api.cardTrendDetail(cardId, exploreParams());
    store.set({ cardDetail, exploreLoading: false });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    store.set({ exploreLoading: false, exploreError: message });
  }
}

export function setExploreCardType(cardType: string): Promise<void> {
  store.set({ exploreCardType: cardType });
  return loadCardTrends();
}

export function closeCard(): void {
  store.set({ cardDetail: null });
}

export async function setExploreMode(mode: ExploreMode): Promise<void> {
  store.set({ exploreMode: mode, cardDetail: null });
  if (mode === "cards" && !store.state.cardTrends) await loadCardTrends();
}
