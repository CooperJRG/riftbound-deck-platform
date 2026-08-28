/** Start-up, and the two banners that outrank everything else on the page. */

import { EXPECTED_API_CONTRACT, api } from "../../api/client";
import { scrollToTop } from "../../ui/scroll";
import { store, type ViewName } from "../store";
import { reportError } from "./shared";
import { refreshCards } from "./cards";
import { revalidate } from "./deck";
import { loadExplore } from "./explore";
import { ensureLegends, openSmartDecks } from "./wizard";

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

export function dismissError(): void {
  store.set({ error: "" });
}

export function dismissNotice(): void {
  store.set({ notice: "" });
}

/**
 * Show or hide the card drawer.
 *
 * Closed, the deck takes the whole width. Most of building a deck is looking at the
 * deck; the drawer is for the minutes you spend hunting a particular card, and it was
 * holding 520px of the screen for the rest of the time.
 */
export function toggleDrawer(): void {
  store.set({ drawerOpen: !store.state.drawerOpen });
}

export function setView(view: ViewName): void {
  // Views are toggled with `hidden` rather than navigated to, so nothing resets the
  // scroll position on our behalf.
  if (view !== store.state.view) scrollToTop();
  store.set({ view });
  if (view === "find") void openSmartDecks();
  // The builder opens on a gallery of legends when there is no deck yet, and that needs
  // the same list the wizard uses.
  if (view === "build" && !store.state.deck.legendId) void ensureLegends();
  if (view === "explore" && store.state.trendOverview === null) void loadExplore();
}
