/** Saved decks: new, save, load, delete. */

import { deleteDeck, loadDeck, newDeck, saveDeck } from "../state/actions";
import { store } from "../state/store";
import { h, replace } from "../ui/dom";

export function renderDeckLibrary(root: HTMLElement): void {
  const { savedDecks, deckId, dirty } = store.state;

  replace(
    root,
    h(
      "div",
      { class: "library-actions" },
      h("button", { class: "btn", type: "button", on: { click: () => newDeck() } }, "New"),
      h(
        "button",
        {
          class: `btn btn-primary${dirty ? " is-dirty" : ""}`,
          type: "button",
          on: { click: () => void saveDeck() },
        },
        dirty ? "Save •" : "Save",
      ),
    ),
    savedDecks.length === 0
      ? h("p", { class: "muted small" }, "No saved decks yet.")
      : h(
          "ul",
          { class: "library-list" },
          ...savedDecks.map((deck) =>
            h(
              "li",
              { class: `library-row${deck.deckId === deckId ? " is-current" : ""}` },
              h(
                "button",
                {
                  class: "library-open",
                  type: "button",
                  on: { click: () => void loadDeck(deck.deckId) },
                },
                h("span", { class: "library-name" }, deck.name),
                h("span", { class: "muted small" }, `${deck.mainTotal} cards`),
              ),
              h(
                "button",
                {
                  class: "step",
                  type: "button",
                  aria: { label: `Delete ${deck.name}` },
                  on: { click: () => void deleteDeck(deck.deckId) },
                },
                "×",
              ),
            ),
          ),
        ),
  );
}
