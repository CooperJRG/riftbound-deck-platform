/** The meta snapshot: loading it, and importing a deck out of it. */

import { api } from "../../api/client";
import { store } from "../store";
import { reportError } from "./shared";
import { loadDeck } from "./library";

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
