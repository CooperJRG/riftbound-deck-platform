/**
 * Deck search: find published lists by the cards they run.
 *
 * Picking a card is two steps -- type to narrow, click to confirm -- because a card
 * name alone is not a card id, and "abandon" the effect text and "Abandon" the card
 * are different rows in the archive. The result list only ever runs against ids.
 */

import { api } from "../../api/client";
import type { Card } from "../../api/types";
import { debounce } from "../../ui/dom";
import type { DeckSearchSort } from "../store";
import { store } from "../store";
import { reportError } from "./shared";

/** Below this, every card in the bundle matches something and the dropdown is noise. */
const MIN_QUERY_LENGTH = 2;

async function loadCandidates(): Promise<void> {
  const q = store.state.searchQuery.trim();
  if (q.length < MIN_QUERY_LENGTH) {
    store.set({ searchCandidates: [] });
    return;
  }
  try {
    const page = await api.cards({ q, limit: 8 });
    // A slower search resolving after a faster one would flash a stale dropdown back
    // in; only apply the result if the box still holds the text that produced it.
    if (store.state.searchQuery.trim() !== q) return;
    const chosen = new Set(store.state.searchCards.map((c) => c.cardId));
    store.set({ searchCandidates: page.cards.map((row) => row.card).filter((c) => !chosen.has(c.cardId)) });
  } catch (error) {
    reportError(error);
  }
}

const loadCandidatesDebounced = debounce(() => void loadCandidates(), 180);

export function setSearchQuery(query: string): void {
  store.set({ searchQuery: query });
  loadCandidatesDebounced();
}

export async function runDeckSearch(): Promise<void> {
  const cards = store.state.searchCards;
  if (cards.length === 0) {
    store.set({ searchResults: [], searchSearched: false });
    return;
  }
  store.set({ searchLoading: true });
  try {
    const results = await api.metaDecks({
      cardId: cards.map((c) => c.cardId),
      sort: store.state.searchSort,
      limit: 40,
    });
    store.set({ searchResults: results, searchLoading: false, searchSearched: true });
  } catch (error) {
    reportError(error);
    store.set({ searchLoading: false });
  }
}

export function pickSearchCard(card: Card): void {
  if (store.state.searchCards.some((c) => c.cardId === card.cardId)) return;
  store.set({
    searchCards: [...store.state.searchCards, card],
    searchQuery: "",
    searchCandidates: [],
  });
  void runDeckSearch();
}

export function removeSearchCard(cardId: string): void {
  store.set({ searchCards: store.state.searchCards.filter((c) => c.cardId !== cardId) });
  void runDeckSearch();
}

export function setSearchSort(sort: DeckSearchSort): void {
  if (sort === store.state.searchSort) return;
  store.set({ searchSort: sort });
  void runDeckSearch();
}
