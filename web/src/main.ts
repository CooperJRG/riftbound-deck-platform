/** Entry point: wire the store to the views, then boot. */

import {
  boot,
  dismissError,
  dismissNotice,
  openSmartDecks,
  setView,
} from "./state/actions";
import { store } from "./state/store";
import { renderAvailability } from "./features/availability";
import { renderCardBrowser } from "./features/cardBrowser";
import { renderDeckLibrary } from "./features/deckLibrary";
import { renderDeckPanel } from "./features/deckPanel";
import { renderMeta } from "./features/meta";
import { renderSmartDecks } from "./features/smartDecks";
import { h, query, replace } from "./ui/dom";
import "./styles.css";

const availabilityRoot = query("#availability");
const browserRoot = query("#browser");
const deckRoot = query("#deck");
const libraryRoot = query("#library");
const errorRoot = query("#error");
const noticeRoot = query("#notice");
const metaRoot = query("#meta");
const smartRoot = query("#smart");
const buildRoot = query("#build");
const tabsRoot = query("#tabs");

function renderError(message: string): void {
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

function renderTabs(current: string): void {
  const tab = (name: "build" | "meta" | "smart", label: string) =>
    h(
      "button",
      {
        class: `tab${current === name ? " is-active" : ""}`,
        type: "button",
        aria: { pressed: String(current === name) },
        // Smart Decks loads its legend list on first open rather than at boot: it is
        // the one view that needs the meta snapshot, and boot must not depend on it.
        on: { click: () => (name === "smart" ? void openSmartDecks() : setView(name)) },
      },
      label,
    );
  replace(
    tabsRoot,
    tab("build", "Build"),
    tab("smart", "Smart Decks"),
    tab("meta", "Meta"),
  );
}

store.subscribe((state) => {
  renderError(state.error);
  renderNotice(state.notice);
  if (!state.ready) return;

  renderTabs(state.view);
  buildRoot.hidden = state.view !== "build";
  metaRoot.hidden = state.view !== "meta";
  smartRoot.hidden = state.view !== "smart";

  // The availability control drives both views, so it always renders.
  renderAvailability(availabilityRoot);
  if (state.view === "build") {
    renderCardBrowser(browserRoot);
    renderDeckPanel(deckRoot);
    renderDeckLibrary(libraryRoot);
  } else if (state.view === "smart") {
    renderSmartDecks(smartRoot);
  } else {
    renderMeta(metaRoot);
  }
});

void boot();
