/** Saved decks: new, save, load, delete. */

import { deleteDeck, loadDeck, newDeck, saveDeck, setView } from "../state/actions";
import { store } from "../state/store";
import { h, replace } from "../ui/dom";
import { openDeckExport } from "./deckExport";

export function renderDeckActions(root: HTMLElement): void {
  const { deck, dirty } = store.state;
  const hasCards = Boolean(
    deck.legendId || deck.championId || Object.keys(deck.main).length ||
      Object.keys(deck.runes).length || deck.battlefields.length || Object.keys(deck.sideboard).length,
  );
  replace(
    root,
    h(
      "div",
      { class: "library-actions" },
      h("button", { class: "quiet-button", type: "button", on: { click: () => newDeck() } }, "New deck"),
      h(
        "button",
        { class: "quiet-button export-button", type: "button", disabled: !hasCards, on: { click: () => void openDeckExport() } },
        "Export deck",
      ),
      h(
        "button",
        { class: `primary${dirty ? " is-dirty" : ""}`, type: "button", on: { click: () => void saveDeck() } },
        dirty ? "Save changes •" : "Save deck",
      ),
    ),
  );
}

export function renderDeckLibrary(root: HTMLElement): void {
  const { savedDecks, deckId } = store.state;

  replace(
    root,
    h(
      "header",
      { class: "page-hero library-hero" },
      h("div", {}, h("p", { class: "eyebrow" }, "Your workshop"), h("h1", {}, "My decks"), h("p", { class: "page-lede" }, "Return to a list, make a copy your own, or start with a clean page.")),
      h("button", { class: "primary", type: "button", on: { click: () => { newDeck(); setView("build"); } } }, "New deck"),
    ),
    savedDecks.length === 0
      ? h("section", { class: "library-empty" }, h("span", { class: "onboarding-number" }, "01"), h("h2", {}, "Your first deck starts here."), h("p", {}, "Find a proven tournament list or build one from the card pool."), h("div", {}, h("button", { class: "primary", type: "button", on: { click: () => setView("find") } }, "Find a deck"), h("button", { class: "quiet-button", type: "button", on: { click: () => { newDeck(); setView("build"); } } }, "Build from scratch")))
      : h(
          "div",
          { class: "deck-library-grid" },
          ...savedDecks.map((deck) =>
            h(
              "article",
              { class: `library-card${deck.deckId === deckId ? " is-current" : ""}` },
              h("p", { class: "eyebrow" }, deck.format),
              h("h2", { class: "library-name" }, deck.name),
              h("p", { class: "library-card-meta" }, `${deck.mainTotal} main-deck cards`, deck.updatedAt ? ` · Updated ${new Date(deck.updatedAt).toLocaleDateString()}` : ""),
              h(
                "button",
                {
                  class: "primary",
                  type: "button",
                  on: { click: () => { void loadDeck(deck.deckId); setView("build"); } },
                },
                "Open in builder",
              ),
              h(
                "button",
                {
                  class: "quiet-button danger-button",
                  type: "button",
                  aria: { label: `Delete ${deck.name}` },
                  on: { click: () => void deleteDeck(deck.deckId) },
                },
                "Delete",
              ),
            ),
          ),
        ),
  );
}
