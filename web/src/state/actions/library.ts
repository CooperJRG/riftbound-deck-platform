/** Saved decks: keeping them, opening them, and letting them go. */

import { api } from "../../api/client";
import { emptyDeck, store } from "../store";
import { reportError } from "./shared";
import { resolveDeckCards } from "./cards";
import { revalidate, refreshSuggestions } from "./deck";

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
    // Opening a deck is a deck change like any other; without this the shortlist stays
    // empty until the player edits something.
    await refreshSuggestions();
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
