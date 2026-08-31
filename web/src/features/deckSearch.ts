/**
 * Search decks by the cards they run.
 *
 * A different question from Explore's tier list: "what's good" versus "what runs
 * this". Picking more than one card narrows with an "and" -- decks running every
 * card named, not any of them -- so comparing two pieces of a combo is one search
 * instead of two lists intersected by hand.
 *
 * The search box is built once and kept, same reason as the card browser's: rebuilding
 * it on every keystroke would tear the focused `<input>` out of the DOM mid-word.
 */

import type { Card, MetaDeck } from "../api/types";
import {
  importMetaDeck,
  pickSearchCard,
  removeSearchCard,
  setSearchQuery,
  setSearchSort,
} from "../state/actions";
import type { DeckSearchSort } from "../state/store";
import { store } from "../state/store";
import { h, replace } from "../ui/dom";

interface Controls {
  root: HTMLElement;
  input: HTMLInputElement;
  candidates: HTMLElement;
  chips: HTMLElement;
  sort: HTMLElement;
  results: HTMLElement;
}

let controls: Controls | null = null;

function fullCard(imageUrl: string, name: string, className: string): HTMLElement {
  return h(
    "div",
    { class: className },
    imageUrl
      ? h("img", { src: imageUrl, alt: `${name} card`, loading: "lazy" })
      : h("div", { class: "full-card-fallback" }, name.slice(0, 2)),
  );
}

function searchChip(card: Card): HTMLElement {
  return h(
    "span",
    { class: "chip" },
    card.name,
    h(
      "button",
      {
        class: "chip-x",
        type: "button",
        title: "Drop this card from the search",
        aria: { label: `Remove ${card.name}` },
        on: { click: () => removeSearchCard(card.cardId) },
      },
      "×",
    ),
  );
}

function candidateRow(card: Card): HTMLElement {
  return h(
    "button",
    { class: "search-candidate", type: "button", on: { click: () => pickSearchCard(card) } },
    fullCard(card.imageUrl, card.name, "search-candidate-art"),
    h(
      "span",
      {},
      h("strong", {}, card.name),
      h("small", {}, card.cardType + (card.cost !== null ? ` · Cost ${card.cost}` : "")),
    ),
  );
}

/** How many copies of a searched card this deck runs, so a match is visibly a match. */
function copiesOf(deck: MetaDeck, card: Card): number {
  const { main, runes } = deck.deck;
  if (card.cardId in main) return main[card.cardId] ?? 0;
  if (card.cardId in runes) return runes[card.cardId] ?? 0;
  if (deck.legendId === card.cardId || deck.championId === card.cardId) return 1;
  return 0;
}

function resultCard(deck: MetaDeck, rank: number, sort: DeckSearchSort, cards: Card[]): HTMLElement {
  const lead = sort === "recency"
    ? (deck.provenance.tournamentDate || deck.provenance.publishedAt || "Undated")
    : `#${rank}`;
  const runs = cards.map((c) => `${copiesOf(deck, c)}× ${c.name}`).join(" · ");
  return h(
    "article",
    { class: "evidence-deck" },
    h(
      "div",
      { class: "evidence-art-pair" },
      fullCard(deck.legendImageUrl, deck.legendName, "evidence-art legend-art"),
      fullCard(deck.championImageUrl, deck.championName, "evidence-art champion-art"),
    ),
    h(
      "div",
      { class: "evidence-body" },
      h("p", { class: "eyebrow" }, `${lead} · ${deck.provenance.summary}`),
      h("h3", {}, deck.name),
      h("p", { class: "evidence-identity" }, `${deck.legendName} · ${deck.championName}`),
      h("p", { class: "evidence-event", title: "Copies run of each card you searched" }, runs),
      h(
        "div",
        { class: "trend-deck-actions" },
        h(
          "button",
          { type: "button", class: "primary", on: { click: () => void importMetaDeck(deck.deckId) } },
          "Import full list",
        ),
        deck.provenance.url
          ? h("a", { href: deck.provenance.url, target: "_blank", rel: "noopener" }, "Source ↗")
          : null,
      ),
    ),
  );
}

function sortOption(value: DeckSearchSort, label: string, current: DeckSearchSort): HTMLElement {
  return h(
    "button",
    {
      class: `pill${current === value ? " is-on" : ""}`,
      type: "button",
      aria: { pressed: String(current === value) },
      on: { click: () => setSearchSort(value) },
    },
    label,
  );
}

function build(root: HTMLElement): Controls {
  const input = h("input", {
    type: "search",
    placeholder: "Search for a card…",
    aria: { label: "Search for a card to filter decks by" },
    on: { input: (e) => setSearchQuery((e.target as HTMLInputElement).value) },
  });

  const candidates = h("div", { class: "search-candidates" });
  const chips = h("div", { class: "chips" });
  const sort = h("div", { class: "quick-rules", role: "group", aria: { label: "Sort results" } });
  const results = h("div", {});

  replace(
    root,
    h(
      "header",
      { class: "visual-section-head" },
      h(
        "div",
        {},
        h("p", { class: "eyebrow" }, "Deck archive"),
        h("h2", {}, "Search decks by card"),
        h(
          "p",
          { class: "muted small" },
          "Name a card and see every published list that runs it. Add more than one to narrow to decks running all of them.",
        ),
      ),
    ),
    h("div", { class: "search-box" }, input, candidates),
    chips,
    sort,
    results,
  );

  return { root, input, candidates, chips, sort, results };
}

export function renderDeckSearch(root: HTMLElement): void {
  if (controls === null || controls.root !== root) {
    controls = build(root);
  }
  const c = controls;
  const {
    searchQuery, searchCandidates, searchCards, searchSort,
    searchResults, searchLoading, searchSearched,
  } = store.state;

  // Uncontrolled while focused, so a keystroke never fights the caret it just moved;
  // synced back only once nothing is mid-edit, which is when a pick or a chip removal
  // needs the box to actually clear.
  if (document.activeElement !== c.input && c.input.value !== searchQuery) {
    c.input.value = searchQuery;
  }

  replace(c.candidates, ...searchCandidates.map(candidateRow));

  replace(
    c.chips,
    ...(searchCards.length > 0
      ? [h("span", { class: "chips-label" }, "Running:"), ...searchCards.map(searchChip)]
      : []),
  );

  if (searchCards.length === 0) {
    replace(c.sort);
    replace(c.results, h("p", { class: "muted small" }, "Pick a card above to start."));
    return;
  }

  replace(
    c.sort,
    sortOption("rank", "Best rank", searchSort),
    sortOption("recency", "Most recent", searchSort),
  );

  if (searchLoading) {
    replace(c.results, h("p", { class: "muted" }, "Searching…"));
  } else if (searchSearched && searchResults.length === 0) {
    replace(
      c.results,
      h(
        "p",
        { class: "muted small" },
        "No decks in the archive run all of those cards together. Try dropping one.",
      ),
    );
  } else {
    replace(
      c.results,
      h(
        "div",
        { class: "evidence-deck-grid" },
        ...searchResults.map((deck, i) => resultCard(deck, i + 1, searchSort, searchCards)),
      ),
    );
  }
}
