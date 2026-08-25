/** Entry point: wire the store to the views, then boot. */

import { boot, dismissError } from "./state/actions";
import { store } from "./state/store";
import { renderAvailability } from "./features/availability";
import { renderCardBrowser } from "./features/cardBrowser";
import { renderDeckLibrary } from "./features/deckLibrary";
import { renderDeckPanel } from "./features/deckPanel";
import { h, query, replace } from "./ui/dom";
import "./styles.css";

const availabilityRoot = query("#availability");
const browserRoot = query("#browser");
const deckRoot = query("#deck");
const libraryRoot = query("#library");
const errorRoot = query("#error");

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

store.subscribe((state) => {
  renderError(state.error);
  if (!state.ready) return;
  renderAvailability(availabilityRoot);
  renderCardBrowser(browserRoot);
  renderDeckPanel(deckRoot);
  renderDeckLibrary(libraryRoot);
});

void boot();
