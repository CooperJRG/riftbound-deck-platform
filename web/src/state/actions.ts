/** Every state transition. Views call these; they never mutate state directly. */

import { ApiError, api } from "../api/client";
import type {
  Card,
  CardAvailability,
  DeckPayload,
  Zone,
  AvailabilityMode,
} from "../api/types";
import { debounce } from "../ui/dom";
import { emptyDeck, store } from "./store";

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
    const [formats, facets, availability, savedDecks] = await Promise.all([
      api.formats(),
      api.facets(),
      api.availability(),
      api.listDecks(),
    ]);
    store.set({ formats, facets, availability, savedDecks, ready: true, error: "" });
    await Promise.all([refreshCards(), revalidate()]);
  } catch (error) {
    reportError(error);
    store.set({ ready: true });
  }
}

// -- cards --------------------------------------------------------------------

export async function refreshCards(): Promise<void> {
  const { filters } = store.state;
  store.set({ cardsLoading: true });
  try {
    const page = await api.cards({ ...filters, limit: 120 });
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
  store.set({ filters: { ...store.state.filters, [key]: value } });
  refreshCardsDebounced();
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
  store.set({ deckId: "", deck: emptyDeck(), dirty: false });
  void revalidate();
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
