/** The card browser: filters, paging, and resolving what a deck refers to. */

import { api } from "../../api/client";
import type { CardAvailability, DeckPayload } from "../../api/types";
import { debounce } from "../../ui/dom";
import { store } from "../store";
import { reportError } from "./shared";

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
export async function resolveDeckCards(deck: DeckPayload): Promise<void> {
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
