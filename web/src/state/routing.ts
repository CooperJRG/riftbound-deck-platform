/**
 * The join between the address bar and the store.
 *
 * Two functions, deliberately kept apart from the router itself: the router knows about
 * URLs and nothing about the app, and this knows about the app.
 *
 * :func:`routeForState` reads what is on screen. :func:`applyLocation` puts it back.
 * They are inverses for everything worth linking to, and the round trip is what the
 * tests check.
 */

import { api } from "../api/client";
import type { DeckPayload } from "../api/types";
import {
  loadCardTrends,
  openCard,
  openChampion,
  openLegend,
  openTournament,
  setExploreMode,
} from "./actions/explore";
import { setView } from "./actions/app";
import { resolveDeckCards } from "./actions/cards";
import { loadDeck } from "./actions/library";
import { openArchetype, loadMeta } from "./actions/meta";
import { refreshSuggestions, revalidate } from "./actions/deck";
import { store } from "./store";
import { deckToQuery, type ExploreQuery, type Location, type Route } from "../ui/router";

/**
 * The address for the state as it stands.
 *
 * Derived rather than pushed by each action: the detail views are opened from a dozen
 * places, and an address that is only correct when every one of them remembers to
 * update it is an address nobody can trust.
 */
export function routeForState(): Route {
  const state = store.state;
  switch (state.view) {
    case "explore":
      // Innermost first: a card can be open while a legend is loaded behind it.
      if (state.cardDetail) return { name: "card", cardId: state.cardDetail.trend.cardId };
      if (state.tournamentDetail) return { name: "event", slug: state.tournamentDetail.slug };
      if (state.championMeta) return { name: "champion", championId: state.championMeta.championId };
      if (state.legendMeta) return { name: "legend", legendId: state.legendMeta.legendId };
      if (state.metaArchetype) return { name: "archetype", archetypeId: state.metaArchetype };
      return { name: "explore", mode: state.exploreMode };
    case "decks":
      return { name: "decks" };
    case "build":
      // A saved deck is addressable by id; anything else has to carry itself.
      if (state.deckId && !state.dirty) return { name: "savedDeck", deckId: state.deckId };
      if (
        state.benchSource &&
        deckToQuery(state.deck).toString() === state.benchSource.signature
      ) {
        return { name: "metaDeck", deckId: state.benchSource.deckId };
      }
      if (hasContent(state.deck)) return { name: "sharedDeck", deck: state.deck };
      return { name: "build" };
    default:
      return { name: "find" };
  }
}

export function exploreForState(): ExploreQuery {
  const state = store.state;
  const query: ExploreQuery = {};
  if (state.exploreRange) query.range = state.exploreRange;
  if (state.exploreFormat) query.format = state.exploreFormat;
  if (state.exploreMinPlayers) query.minPlayers = state.exploreMinPlayers;
  return query;
}

function hasContent(deck: DeckPayload): boolean {
  return Boolean(
    deck.legendId ||
      deck.championId ||
      Object.keys(deck.main).length ||
      Object.keys(deck.runes).length ||
      deck.battlefields.length ||
      Object.keys(deck.sideboard).length,
  );
}

/** Put a deck on the builder's bench, hydrated enough to draw. */
async function benchDeck(
  deck: DeckPayload,
  { source }: { source?: string } = {},
): Promise<void> {
  store.set({
    deck,
    deckId: "",
    dirty: true,
    view: "build",
    benchSource: source ? { deckId: source, signature: deckToQuery(deck).toString() } : null,
  });
  await resolveDeckCards(deck);
  await Promise.all([revalidate(), refreshSuggestions()]);
}

/**
 * Rebuild the app from an address.
 *
 * Uses the same actions the buttons use, so a link and a click end in the same state by
 * the same route -- a second code path that merely *looks* equivalent is how a shared
 * link ends up subtly different from the page it was copied from.
 */
export async function applyLocation(location: Location): Promise<void> {
  const { route, explore } = location;

  // Filters first: the detail loaders read them when they build their request, so
  // applying them afterwards would fetch the wrong window and then relabel it.
  store.set({
    exploreRange: explore.range ?? "",
    ...(explore.format === undefined ? {} : { exploreFormat: explore.format }),
    ...(explore.minPlayers === undefined ? {} : { exploreMinPlayers: explore.minPlayers }),
  });

  switch (route.name) {
    case "find":
      setView("find");
      return;

    case "explore":
      setView("explore");
      await setExploreMode(route.mode);
      return;

    case "legend":
      setView("explore");
      await openLegend(route.legendId);
      return;

    case "champion":
      setView("explore");
      await openChampion(route.championId);
      return;

    case "card":
      setView("explore");
      // The card wall is the backdrop this detail sits on; without it, closing the card
      // leaves an empty page.
      if (!store.state.cardTrends) await loadCardTrends();
      store.set({ exploreMode: "cards" });
      await openCard(route.cardId);
      return;

    case "event":
      setView("explore");
      await openTournament(route.slug);
      return;

    case "archetype":
      setView("explore");
      if (!store.state.archetypes.length) await loadMeta();
      await openArchetype(route.archetypeId);
      return;

    case "decks":
      setView("decks");
      return;

    case "build":
      setView("build");
      return;

    case "savedDeck":
      await loadDeck(route.deckId);
      setView("build");
      return;

    case "metaDeck": {
      // A deck found in Explore. Read-only upstream, so it lands on the bench as an
      // unsaved deck rather than pretending to be one of yours.
      const found = await api.metaDeck(route.deckId);
      await benchDeck(
        { ...found.deck, name: found.deck.name || "Shared deck" },
        { source: route.deckId },
      );
      return;
    }

    case "sharedDeck":
      await benchDeck(route.deck);
      return;
  }
}
