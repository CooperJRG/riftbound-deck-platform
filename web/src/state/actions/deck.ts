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
  refreshSuggestionsDebounced();
  refreshOpeningDebounced();
}

/**
 * What to add next, for the deck as it stands.
 *
 * Debounced alongside validation and on the same trigger: a suggestion computed against
 * a deck the player has already moved on from is worse than none, because they will
 * click it.
 */
export async function refreshSuggestions(): Promise<void> {
  const deck = store.state.deck;
  if (!deck.legendId) {
    store.set({ suggestions: null });
    return;
  }
  try {
    store.set({ suggestions: await api.buildSuggestions(deck) });
  } catch {
    // A shortlist that cannot be fetched is not an error worth interrupting a build
    // for. The search box still works.
    store.set({ suggestions: null });
  }
}

const refreshSuggestionsDebounced = debounce(() => void refreshSuggestions(), 200);

/**
 * Opening-hand odds for the deck as it stands.
 *
 * Debounced alongside validation for the same reason: the odds are a function of the
 * deck, and a table computed against a list the player has already changed is worse
 * than none, because they will read it.
 */
export async function refreshOpening(): Promise<void> {
  const deck = store.state.deck;
  if (!deck.legendId && Object.keys(deck.main).length === 0) {
    store.set({ opening: null });
    return;
  }
  try {
    store.set({ opening: await api.openingOdds(deck) });
  } catch {
    // Odds that cannot be fetched are not worth interrupting a build for.
    store.set({ opening: null });
  }
}

const refreshOpeningDebounced = debounce(() => void refreshOpening(), 250);

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
  const deck = store.state.deck;
  // A champion is added to the main deck like any other unit and then *nominated* (see
  // `zoneFor`) -- but the picker offers candidates from the meta, not only cards
  // already on the bench, so nominating one has to also place it. Without this the
  // deck comes out a card short of 40 until the player notices and finds the exact
  // same card in the drawer by hand.
  //
  // Only added, never removed: clearing or switching the nomination leaves whatever
  // copies are already in the main deck alone, because a player may run three copies
  // of a champion and nominate one -- the other two are not this action's to delete.
  const main = cardId && !(cardId in deck.main) ? { ...deck.main, [cardId]: 1 } : deck.main;
  commit({ ...deck, championId: cardId, main });
}

export function setLegend(cardId: string): void {
  commit({ ...store.state.deck, legendId: cardId });
  // The legend decides which domains the deck may play, so the drawer's contents change
  // with it. Without this the player picks a legend and keeps being offered cards that
  // cannot legally go in the deck.
  void refreshCards();
}

/**
 * Fill the rune base from the deck's own cost line.
 *
 * Always available, never automatic. Every domain gets at least the largest power any
 * one of its cards demands -- power is the domain-specific half of a cost, so a card
 * wanting four Body power cannot be cast from three Body runes -- and the rest goes by
 * how much of the deck each domain is. It is the one part of a list with a defensible
 * right answer, and also the part a player is most likely to want to overrule, so it
 * sits behind a button.
 */
export function applySuggestedRunes(): void {
  const runes = store.state.suggestions?.runes;
  if (!runes || !Object.keys(runes).length) return;
  commit({ ...store.state.deck, runes: { ...runes } });
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
