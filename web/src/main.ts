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
import { renderDeckActions, renderDeckLibrary } from "./features/deckLibrary";
import { renderDeckPanel } from "./features/deckPanel";
import { renderExplore } from "./features/explore";
import { renderSmartDecks } from "./features/wizard/run";
import { h, query, replace } from "./ui/dom";
import { currentTheme, toggleTheme } from "./ui/theme";
import "./styles.css";
import "./bound-atlas.css";

const availabilityRoot = query("#availability");
const browserRoot = query("#browser");
const deckRoot = query("#deck");
const deckActionsRoot = query("#deck-actions");
const libraryRoot = query("#decks");
const errorRoot = query("#error");
const noticeRoot = query("#notice");
const exploreRoot = query("#explore");
const findRoot = query("#find");
const buildRoot = query("#build");
const tabsRoot = query("#tabs");
const themeRoot = query<HTMLButtonElement>("#theme-toggle");

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

function renderTabs(current: string): void {
  const tab = (name: "find" | "explore" | "build" | "decks", label: string) =>
    h(
      "button",
      {
        class: `tab${current === name ? " is-active" : ""}`,
        type: "button",
        aria: { pressed: String(current === name) },
        on: { click: () => setView(name) },
      },
      label,
    );
  replace(
    tabsRoot,
    tab("find", "Find a deck"),
    tab("explore", "Explore"),
    tab("build", "Build"),
    tab("decks", "My decks"),
  );
}

store.subscribe((state) => {
  renderError(state.error, state.staleServer);
  renderNotice(state.notice);
  if (!state.ready) return;

  renderTabs(state.view);
  buildRoot.hidden = state.view !== "build";
  exploreRoot.hidden = state.view !== "explore";
  findRoot.hidden = state.view !== "find";
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
  } else if (state.view === "find") {
    renderSmartDecks(findRoot);
  } else if (state.view === "explore") {
    renderExplore(exploreRoot);
  } else if (state.view === "decks") {
    renderDeckLibrary(libraryRoot);
  }
});

void boot().then(() => setView(store.state.view));
