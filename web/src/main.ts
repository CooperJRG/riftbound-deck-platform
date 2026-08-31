/** Entry point: wire the store to the views, then boot. */

import {
  boot,
  dismissError,
  dismissNotice,
  setView,
} from "./state/actions";
import { store } from "./state/store";
import { renderAvailability } from "./features/availability";
import { renderCardBrowser } from "./features/cardBrowser";
import { refreshCardPreview } from "./features/cardPreview";
import { renderDeckActions, renderDeckLibrary } from "./features/deckLibrary";
import { renderDeckPanel } from "./features/deckPanel";
import { renderExplore } from "./features/explore";
import { renderDeckSearch } from "./features/deckSearch";
import { renderSmartDecks } from "./features/wizard/run";
import { applyLocation, exploreForState, routeForState } from "./state/routing";
import { h, query, replace } from "./ui/dom";
import {
  currentLocation,
  isApplying,
  onPopState,
  pathFor,
  routeKey,
  whileApplying,
  writeUrl,
} from "./ui/router";
import { currentTheme, toggleTheme } from "./ui/theme";
import "./styles.css";
import "./riftdesk.css";
import "./polish.css";

const availabilityRoot = query("#availability");
const browserRoot = query("#browser");
const deckRoot = query("#deck");
const deckActionsRoot = query("#deck-actions");
const libraryRoot = query("#decks");
const errorRoot = query("#error");
const noticeRoot = query("#notice");
const exploreRoot = query("#explore");
const findRoot = query("#find");
const searchRoot = query("#search");
const buildRoot = query("#build");
const loadingRoot = query("#app-loading");
const tabsRoot = query("#tabs");
const themeRoot = query<HTMLButtonElement>("#theme-toggle");
const accessMenu = query<HTMLDetailsElement>(".access-menu");
const skipRoot = query<HTMLAnchorElement>(".skip-link");

function renderError(message: string, staleServer: string): void {
  // The stale-server warning outranks whatever error it caused, and cannot be
  // dismissed: every feature added since that server started will misbehave, and each
  // one looks like a separate bug until somebody restarts the process.
  if (staleServer) {
    errorRoot.hidden = false;
    replace(errorRoot, h("strong", {}, "Restart the server. "), h("span", {}, staleServer));
    return;
  }
  if (!message) {
    replace(errorRoot);
    errorRoot.hidden = true;
    return;
  }
  errorRoot.hidden = false;
  replace(
    errorRoot,
    h("span", {}, message),
    h("button", { class: "step", type: "button", on: { click: dismissError } }, "×"),
  );
}

function renderNotice(message: string): void {
  noticeRoot.hidden = !message;
  if (!message) {
    replace(noticeRoot);
    return;
  }
  replace(
    noticeRoot,
    h("span", {}, message),
    h("button", { class: "step", type: "button", on: { click: dismissNotice } }, "×"),
  );
}

function renderThemeButton(): void {
  const dark = currentTheme() === "dark";
  replace(themeRoot, h("span", { aria: { hidden: "true" } }, dark ? "☀" : "◐"), h("span", { class: "theme-label" }, dark ? "Light" : "Dark"));
  themeRoot.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
}

themeRoot.addEventListener("click", () => {
  toggleTheme();
  renderThemeButton();
});
renderThemeButton();

/**
 * A tab press is a navigation, not a state change.
 *
 * Going through the router means the tab, a pasted link and the back button all reach a
 * view the same way, and the address is right the moment the view changes rather than
 * one render later.
 */
function go(name: "find" | "explore" | "search" | "build" | "decks"): void {
  accessMenu.open = false;
  setView(name);
}

document.addEventListener("pointerdown", (event) => {
  if (accessMenu.open && !accessMenu.contains(event.target as Node)) accessMenu.open = false;
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && accessMenu.open) {
    accessMenu.open = false;
    accessMenu.querySelector<HTMLElement>("summary")?.focus();
  }
});

function renderTabs(current: string): void {
  const tab = (name: "find" | "explore" | "search" | "build" | "decks", label: string) =>
    h(
      "button",
      {
        class: `tab${current === name ? " is-active" : ""}`,
        type: "button",
        aria: { pressed: String(current === name) },
        on: { click: () => go(name) },
      },
      label,
    );
  replace(
    tabsRoot,
    tab("find", "Find a deck"),
    tab("explore", "Explore"),
    tab("search", "Search"),
    tab("build", "Build"),
    tab("decks", "My decks"),
  );
}

/**
 * Keep the address in step with the screen.
 *
 * Runs after the render rather than inside each action, because the detail views open
 * from a dozen places and an address that is only right when every one of them
 * remembers is an address nobody can trust. Suppressed while a route is being applied,
 * or arriving at a page would immediately push a second entry for it.
 */
function syncUrl(): void {
  if (isApplying() || !store.state.ready) return;
  const path = pathFor(routeForState(), exploreForState());
  const current = window.location.pathname + window.location.search;
  if (path === current) return;
  // A different place gets a history entry; a different *state of the same place* --
  // a filter nudged, a card added to the deck on the bench -- does not, or the back
  // button ends up buried under one entry per keystroke.
  const key = routeKey(routeForState());
  const push = key !== lastKey;
  lastKey = key;
  writeUrl(path, { push });
}

/**
 * The address as it was when the page opened.
 *
 * Read once, at module load. `boot()` fills the store and every one of those writes
 * renders, and a render syncs the URL -- so by the time `boot()` resolves the address
 * has already been rewritten to match the empty default state. Reading it here is the
 * difference between a deep link opening the page it names and opening the front page.
 */
const opened = currentLocation();

let lastKey = routeKey(opened.route);

store.subscribe((state) => {
  renderError(state.error, state.staleServer);
  renderNotice(state.notice);
  if (!state.ready) return;

  loadingRoot.hidden = true;
  loadingRoot.setAttribute("aria-busy", "false");

  renderTabs(state.view);
  skipRoot.href = `#${state.view}`;
  buildRoot.hidden = state.view !== "build";
  exploreRoot.hidden = state.view !== "explore";
  findRoot.hidden = state.view !== "find";
  searchRoot.hidden = state.view !== "search";
  libraryRoot.hidden = state.view !== "decks";

  // The availability control drives both views, so it always renders.
  renderAvailability(availabilityRoot);
  if (state.view === "build") {
    // The drawer is hidden rather than unmounted, so its search box keeps its text and
    // its scroll position across a close and reopen.
    buildRoot.classList.toggle("drawer-closed", !state.drawerOpen);
    browserRoot.hidden = !state.drawerOpen;
    if (state.drawerOpen) renderCardBrowser(browserRoot);
    renderDeckPanel(deckRoot);
    renderDeckActions(deckActionsRoot);
    refreshCardPreview();
  } else if (state.view === "find") {
    renderSmartDecks(findRoot);
  } else if (state.view === "explore") {
    renderExplore(exploreRoot);
  } else if (state.view === "search") {
    renderDeckSearch(searchRoot);
  } else if (state.view === "decks") {
    renderDeckLibrary(libraryRoot);
  }
  syncUrl();
});

onPopState((location) => {
  // The sync is suppressed while a route is being applied, so an address that does not
  // round-trip -- a link that has rotted, a legacy path -- would otherwise sit in the
  // bar describing a page it did not produce. Normalising afterwards replaces the
  // entry rather than adding one, so back still goes where it went before.
  void whileApplying(() => applyLocation(location)).then(syncUrl);
});

// The address is the source of truth on arrival: a reload, a bookmark and a pasted
// link all start the same way.
void boot().then(async () => {
  await whileApplying(() => applyLocation(opened));
  syncUrl();
});
