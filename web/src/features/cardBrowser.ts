/**
 * Card browser.
 *
 * Every tile shows its availability: a card the player has said they lack is dimmed
 * and labelled, but stays selectable — the soft model, visible in the UI.
 *
 * The filter controls are built once and kept. Re-creating them on every state change
 * would tear the focused `<input>` out of the DOM on each keystroke, so search would
 * lose focus and the caret after the first character.
 */

import type { Card, CardAvailability, CardFacets } from "../api/types";
import {
  addCard,
  excludeCard,
  setFilter,
  showMoreCards,
  toggleDrawer,
  zoneFor,
} from "../state/actions";
import { store } from "../state/store";
import { h, replace } from "../ui/dom";

/**
 * The energy cost, for tiles that have no art to read it off.
 *
 * Every card that has a cost prints it in the top corner of its own illustration, so
 * over the art this badge was a second copy of the same number sitting on top of the
 * first. It still earns its place on the fallback tile, where there is no art at all.
 */
function costBadge(row: CardAvailability): HTMLElement | null {
  const { cost } = row.card;
  return cost === null ? null : h("span", { class: "cost" }, String(cost));
}

function domainDots(row: CardAvailability): HTMLElement {
  return h(
    "span",
    { class: "domains" },
    ...row.card.domains.map((d) =>
      h("i", { class: `dot dot-${d.toLowerCase()}`, title: d }),
    ),
  );
}

/**
 * Has the player told us anything about what they own?
 *
 * Collection mode resolves every unrecorded card as "not-owned", so an empty collection
 * stamped "Not in your collection" on all 948 cards and dimmed every tile in the
 * browser. That is not information -- it is the absence of information, rendered 948
 * times, and it reads as though the app has decided the player owns nothing.
 */
function collectionIsEmpty(): boolean {
  const profile = store.state.availability;
  if (!profile || profile.mode !== "collection") return false;
  return profile.ownedCardCount === 0 && profile.ownedRules.length === 0;
}

function availabilityNote(row: CardAvailability): HTMLElement | null {
  if (row.weight >= 1) return null;
  if (row.reason === "not-owned" && collectionIsEmpty()) return null;
  const detail = row.reason.split(":")[1] ?? "";
  const label = row.reason.startsWith("excluded:card")
    ? "You don't have this"
    : row.reason.startsWith("excluded:")
      ? `Excluded (${detail.replace("=", " ")})`
      : row.reason === "not-owned"
        ? "Not in your collection"
        : "Unavailable";
  return h("span", { class: "avail-note" }, label);
}

/**
 * Battlefields are printed landscape; every other card is portrait. The grid rotates
 * their art a quarter turn so every tile keeps the same silhouette (see `.is-landscape`
 * in styles.css). Keyed off the card type rather than measuring the image, so a tile
 * renders correctly on first paint instead of reflowing once the art loads.
 */
function hasLandscapeArt(card: Card): boolean {
  return card.cardType === "Battlefield";
}

function cardTile(row: CardAvailability): HTMLElement {
  const { card } = row;
  const target = zoneFor(card);

  return h(
    "article",
    {
      // Dimmed for a card the player probably cannot field -- but not when the only
      // reason is that they have recorded nothing, which would dim the whole pool.
      class: `tile${row.weight < 1 && !(row.reason === "not-owned" && collectionIsEmpty()) ? " is-dim" : ""}`,
      data: { cardId: card.cardId },
    },
    h(
      "div",
      { class: `tile-art${hasLandscapeArt(card) ? " is-landscape" : ""}` },
      card.imageUrl
        ? h("img", { src: card.imageUrl, alt: card.name, loading: "lazy" })
        : h("div", { class: "tile-art-empty" }, card.name.slice(0, 2)),
      card.imageUrl ? null : costBadge(row),
    ),
    h(
      "div",
      { class: "tile-body" },
      h("h4", { class: "tile-name", title: card.name }, card.name),
      h(
        "p",
        { class: "tile-meta" },
        card.superType ? `${card.superType} ` : "",
        card.cardType,
        domainDots(row),
      ),
      availabilityNote(row),
      h(
        "div",
        { class: "tile-actions" },
        h(
          "button",
          { class: "btn btn-add", type: "button", on: { click: () => addCard(card) } },
          target === "legend" ? "Set legend" : "Add",
        ),
        h(
          "button",
          {
            class: "btn btn-ghost",
            type: "button",
            title: "Mark this as a card you don't own",
            on: { click: () => void excludeCard(card.cardId) },
          },
          "I don't have this",
        ),
      ),
    ),
  );
}

type FilterKey = "cardType" | "domain" | "setCode" | "rarity";

function filterSelect(label: string, key: FilterKey): HTMLSelectElement {
  return h("select", {
    class: "filter",
    aria: { label },
    on: { change: (e) => setFilter(key, (e.target as HTMLSelectElement).value) },
  });
}

/** Populate a select once facets arrive, preserving the current choice. */
function fillSelect(select: HTMLSelectElement, label: string, values: string[]): void {
  const current = select.value;
  replace(
    select,
    h("option", { value: "" }, label),
    ...values.map((value) => h("option", { value }, value)),
  );
  select.value = current;
}

interface Controls {
  root: HTMLElement;
  count: HTMLElement;
  grid: HTMLElement;
  more: HTMLButtonElement;
  selects: Record<FilterKey, HTMLSelectElement>;
  facetsFilled: boolean;
}

let controls: Controls | null = null;

function buildControls(root: HTMLElement): Controls {
  const selects: Record<FilterKey, HTMLSelectElement> = {
    cardType: filterSelect("Type", "cardType"),
    domain: filterSelect("Domain", "domain"),
    setCode: filterSelect("Set", "setCode"),
    rarity: filterSelect("Rarity", "rarity"),
  };

  const search = h("input", {
    class: "search",
    type: "search",
    placeholder: "Search cards…",
    on: { input: (e) => setFilter("q", (e.target as HTMLInputElement).value) },
  });

  const sort = h(
    "select",
    {
      class: "filter",
      aria: { label: "Sort" },
      on: {
        change: (e) =>
          setFilter(
            "sort",
            (e.target as HTMLSelectElement).value as "name" | "cost" | "availability",
          ),
      },
    },
    h("option", { value: "availability" }, "Sort: available first"),
    h("option", { value: "name" }, "Sort: name"),
    h("option", { value: "cost" }, "Sort: cost"),
  );
  sort.value = store.state.filters.sort;

  const count = h("p", { class: "browser-count muted small" });
  const grid = h("div", { class: "tile-grid" });
  const more = h("button", {
    class: "show-more",
    type: "button",
    on: { click: showMoreCards },
  }, "Show more cards");

  replace(
    root,
    h(
      "header",
      { class: "builder-heading" },
      h("div", {}, h("p", { class: "eyebrow" }, "Deck workshop"), h("h1", {}, "Build one choice at a time.")),
      h("p", {}, "Search, add, and tune. Review legality when the list is ready."),
      // Out of the way when it is not being used. Most of building a deck is looking at
      // the deck, and the drawer was holding a fifth of the screen for the whole of it.
      h(
        "button",
        {
          class: "quiet-button drawer-toggle",
          type: "button",
          on: { click: toggleDrawer },
        },
        "Hide the drawer",
      ),
    ),
    h(
      "div",
      { class: "browser-controls" },
      search,
      selects.cardType,
      h(
        "details",
        { class: "advanced-filters" },
        h("summary", {}, "More filters"),
        h("div", { class: "advanced-filter-grid" }, selects.domain, selects.setCode, selects.rarity, sort),
      ),
    ),
    count,
    grid,
    more,
  );

  return { root, count, grid, more, selects, facetsFilled: false };
}

function applyFacets(state: Controls, facets: CardFacets): void {
  fillSelect(state.selects.cardType, "Type", facets.cardTypes);
  fillSelect(state.selects.domain, "Domain", facets.domains);
  fillSelect(state.selects.setCode, "Set", facets.setCodes);
  fillSelect(state.selects.rarity, "Rarity", facets.rarities);
  state.facetsFilled = true;
}

export function renderCardBrowser(root: HTMLElement): void {
  const { cards, cardTotal, cardsLoading, facets } = store.state;

  if (controls === null || controls.root !== root) {
    controls = buildControls(root);
  }
  if (!controls.facetsFilled && facets) {
    applyFacets(controls, facets);
  }

  replace(
    controls.count,
    cardsLoading
      ? "Searching…"
      : `${cardTotal} card${cardTotal === 1 ? "" : "s"}${
          cards.length < cardTotal ? ` (showing ${cards.length})` : ""
        }`,
  );

  if (cards.length === 0 && !cardsLoading) {
    replace(controls.grid, h("p", { class: "empty" }, "No cards match those filters."));
  } else {
    replace(controls.grid, ...cards.map(cardTile));
  }
  controls.more.hidden = cardsLoading || cards.length >= cardTotal;
}
