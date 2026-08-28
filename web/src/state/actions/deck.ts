/** Editing the deck in the builder, and validating it as it changes. */

import { api } from "../../api/client";
import type { Card, DeckPayload, Zone } from "../../api/types";
import { debounce } from "../../ui/dom";
import { store } from "../store";
import { reportError } from "./shared";
import { refreshCards, resolveDeckCards } from "./cards";

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
  // The legend decides which domains the deck may play, so the drawer's contents change
  // with it. Without this the player picks a legend and keeps being offered cards that
  // cannot legally go in the deck.
  void refreshCards();
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

export function setBuilderReview(reviewing: boolean): void {
  store.set({ builderReview: reviewing });
}
