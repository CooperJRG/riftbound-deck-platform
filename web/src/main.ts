/** Entry point: wire the store to the views, then boot. */

import { boot, dismissError, dismissNotice, setView } from "./state/actions";
import { store } from "./state/store";
import { renderAvailability } from "./features/availability";
import { renderCardBrowser } from "./features/cardBrowser";
import { renderDeckLibrary } from "./features/deckLibrary";
import { renderDeckPanel } from "./features/deckPanel";
import { renderMeta } from "./features/meta";
import { h, query, replace } from "./ui/dom";
import "./styles.css";

const availabilityRoot = query("#availability");
const browserRoot = query("#browser");
const deckRoot = query("#deck");
const libraryRoot = query("#library");
const errorRoot = query("#error");
const noticeRoot = query("#notice");
const metaRoot = query("#meta");
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
  const tab = (name: "build" | "meta", label: string) =>
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
  replace(tabsRoot, tab("build", "Build"), tab("meta", "Meta"));
}

store.subscribe((state) => {
  renderError(state.error);
  renderNotice(state.notice);
  if (!state.ready) return;

  renderTabs(state.view);
  buildRoot.hidden = state.view !== "build";
  metaRoot.hidden = state.view !== "meta";

  // The availability control drives both views, so it always renders.
  renderAvailability(availabilityRoot);
  if (state.view === "build") {
    renderCardBrowser(browserRoot);
    renderDeckPanel(deckRoot);
    renderDeckLibrary(libraryRoot);
  } else {
    renderMeta(metaRoot);
  }
});

void boot();
