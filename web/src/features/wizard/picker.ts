/**
 * Choosing a legend, and the states where there is nothing to choose from.
 *
 * Familiarity is shown but never filters: the point of the wizard is to find out what
 * somebody can build, and pre-judging it from a collection they may not have entered
 * would rebuild the barrier the two-mode design removes.
 */

import type { LegendChoice, LegendSort } from "../../api/types";
import {
  discardSmartSession,
  refreshMetaNow,
  resumeSmartSession,
  retrySmartLegends,
  setSmartLegendQuery,
  setSmartLegendSort,
  startSmartSession,
  toggleOwnedRule,
} from "../../state/actions";
import { store } from "../../state/store";
import { h, replace } from "../../ui/dom";

const NUDGE_DISMISSED = "riftdesk.collection-nudge-dismissed";
const LEGACY_NUDGE_DISMISSED = "atlas.collection-nudge-dismissed";

function nudgeDismissed(): boolean {
  try {
    return localStorage.getItem(NUDGE_DISMISSED) === "1" ||
      localStorage.getItem(LEGACY_NUDGE_DISMISSED) === "1";
  } catch {
    // Private windows and blocked site data both throw here. A nudge that cannot
    // remember being dismissed is better than a page that will not render.
    return false;
  }
}

function dismissNudge(): void {
  try {
    localStorage.setItem(NUDGE_DISMISSED, "1");
  } catch {
    /* nothing to do -- it will simply appear again next visit */
  }
  // An empty patch still notifies, which is what re-renders the picker. The flag lives
  // in localStorage rather than the store because it is a per-browser convenience, not
  // something the server has any business knowing.
  store.set({});
}

/**
 * The offer to say what you own, where somebody would actually see it.
 *
 * The bulk rules live in the header's "Card access" panel, which is a disclosure that
 * starts closed -- so the feature that turns a 24-card checklist into a 10-card one was
 * reachable only by people who already knew it was there. This is the same two clicks,
 * on the screen a new player lands on.
 *
 * Shown only when they have told us nothing at all. Declaring anything removes it, and
 * so does dismissing it: "everything" is a legitimate answer and should not be asked
 * twice.
 */
/**
 * Which question the picker answers first.
 *
 * Strength alone is the right order for somebody who owns everything, and the wrong one
 * for the player this whole review is about: it leads with the decks they are least able
 * to build. Offered rather than imposed, and a sort rather than a filter -- every legend
 * stays in the list either way, because hiding one somebody could build with a little
 * effort rebuilds the barrier the two-mode design exists to remove.
 */
function sortControl(): HTMLElement | null {
  const { smartLegendSort, availability, smartBusy } = store.state;
  // Nothing to sort by until they have told us something.
  const knows =
    (availability?.ownedRules.length ?? 0) > 0 ||
    (availability?.ownedCardCount ?? 0) > 0;
  if (!knows) return null;

  const option = (value: LegendSort, label: string) =>
    h(
      "button",
      {
        class: `pill${smartLegendSort === value ? " is-on" : ""}`,
        type: "button",
        disabled: smartBusy,
        aria: { pressed: String(smartLegendSort === value) },
        on: { click: () => void setSmartLegendSort(value) },
      },
      label,
    );

  return h(
    "div",
    { class: "picker-sort" },
    h("span", { class: "picker-sort-label" }, "Order by"),
    option("strength", "Strongest"),
    option("buildable", "Closest to my cards"),
  );
}

export function collectionNudge(): HTMLElement | null {
  const { availability } = store.state;
  if (!availability || nudgeDismissed()) return null;
  const untouched =
    availability.ownedRules.length === 0 &&
    availability.rules.length === 0 &&
    availability.excludedCards.length === 0 &&
    availability.ownedCardCount === 0;
  if (!untouched) return null;

  const rule = (value: string) =>
    h(
      "button",
      {
        class: "pill",
        type: "button",
        on: { click: () => void toggleOwnedRule("rarity", value) },
      },
      `I have most ${value}s`,
    );

  return h(
    "details",
    { class: "collection-nudge" },
    h(
      "summary",
      {},
      h("strong", {}, "Using part of a collection?"),
      h("span", {}, "Optional · shorten the card questions"),
    ),
    h(
      "div",
      { class: "collection-nudge-body" },
      h(
        "p",
        {},
        "Tell us roughly what you own and RiftDesk will skip cards you have already covered.",
      ),
      h("div", { class: "quick-rules" }, rule("Common"), rule("Uncommon"), rule("Rare")),
      h(
        "button",
        {
          class: "quiet-button",
          type: "button",
          on: { click: dismissNudge },
        },
        "I use the full card pool",
      ),
    ),
  );
}

/**
 * Sessions still open, offered before the picker.
 *
 * The answers are the expensive part -- three rounds pin down roughly 75 cards -- and
 * they were being written to the database and then left unreachable: closing the tab
 * meant starting again from the first question. The API had listed them all along and
 * nothing called it.
 *
 * Discard is next to resume rather than buried, because an abandoned session is a record
 * of what somebody owns and they should not have to finish one to be rid of it.
 */
export function resumeStrip(): HTMLElement | null {
  const { smartResumable, smartBusy } = store.state;
  if (!smartResumable.length) return null;
  return h(
    "section",
    { class: "resume-strip" },
    h("h3", {}, smartResumable.length === 1 ? "Pick up where you left off" : "Sessions in progress"),
    h(
      "ul",
      {},
      ...smartResumable.slice(0, 4).map((session) =>
        h(
          "li",
          {},
          h(
            "button",
            {
              class: "resume-open",
              type: "button",
              disabled: smartBusy,
              on: { click: () => void resumeSmartSession(session.sessionId) },
            },
            h("strong", {}, session.legendName),
            h(
              "span",
              {},
              session.rounds === 0
                ? "Not started"
                : `${session.rounds} round${session.rounds === 1 ? "" : "s"} answered · ${session.knownCards} cards known`,
            ),
          ),
          h(
            "button",
            {
              class: "quiet-button",
              type: "button",
              disabled: smartBusy,
              title: "Delete this session and everything it learned",
              on: { click: () => void discardSmartSession(session.sessionId) },
            },
            "Discard",
          ),
        ),
      ),
    ),
  );
}

function legendCard(legend: LegendChoice, busy: boolean): HTMLElement {
  const known = Math.round(legend.familiarity * 100);
  return h(
    "button",
    {
      class: "legend-card",
      type: "button",
      disabled: busy,
      on: { click: () => void startSmartSession(legend.legendId) },
    },
    legend.imageUrl
      ? h("img", { class: "legend-art", src: legend.imageUrl, alt: "", loading: "lazy" })
      : h("div", { class: "tile-art-empty" }, legend.name.slice(0, 1)),
    h(
      "span",
      { class: "legend-body" },
      h("span", { class: "legend-name" }, legend.name),
      h(
        "span",
        { class: "legend-meta" },
        `${legend.deckCount} deck${legend.deckCount === 1 ? "" : "s"}`,
        // Only when it says something. Now the two counts are drawn from the same
        // population they are frequently equal, and "127 decks · 127 from tournaments"
        // is a clause that adds nothing.
        legend.tournamentDeckCount && legend.tournamentDeckCount < legend.deckCount
          ? ` · ${legend.tournamentDeckCount} from tournaments`
          : "",
      ),
      // Advisory only. The wizard exists to find out what someone can build, so a low
      // number must never hide a legend -- that would rebuild the barrier we removed.
      legend.familiarity > 0
        ? h("span", { class: "legend-known" }, `You own ${known}% of its staples`)
        : null,
    ),
  );
}

/**
 * Why there are no legends, when there are none.
 *
 * Three different causes with three different fixes, and telling them apart matters:
 * a failed request is not missing data, and sending somebody to run a pipeline when
 * the real fault was a stale server wastes their afternoon.
 */
function emptyPicker(): HTMLElement {
  const { smartLegendsError, refreshBusy } = store.state;

  if (smartLegendsError) {
    const { smartLegendsAttempts: attempts, smartLegendsRetrying: retrying } = store.state;
    // A server that answers an /api path with the app shell is running older code than
    // the page talking to it. Retrying cannot fix that, so after the first failure the
    // advice has to stop being "try again" and start being the thing that works.
    const staleServer = smartLegendsError.includes("instead of JSON");
    const repeated = attempts > 1;

    return h(
      "div",
      { class: "smart-empty" },
      h(
        "strong",
        {},
        repeated
          ? `Still could not load the legend list (${attempts} attempts).`
          : "Could not load the legend list.",
      ),
      staleServer
        ? h(
            "p",
            { class: "smart-lede" },
            "The server is running older code than this page: it answered an API " +
              "request with the app itself. Restart the server and this will clear.",
          )
        : h("p", { class: "smart-lede" }, smartLegendsError),
      staleServer
        ? h("details", { class: "req-known" }, h("summary", {}, "Details"), h("p", {}, smartLegendsError))
        : null,
      h(
        "p",
        { class: "smart-optin" },
        "This is a request that failed, not missing data - the meta may well be fine.",
      ),
      h(
        "button",
        {
          type: "button",
          disabled: retrying,
          on: { click: () => void retrySmartLegends() },
        },
        retrying ? "Trying..." : repeated ? "Try once more" : "Try again",
      ),
    );
  }

  return h(
    "div",
    { class: "smart-empty" },
    h("strong", {}, "No meta decks yet."),
    h(
      "p",
      { class: "smart-lede" },
      "The wizard builds from what the field is playing, so it needs a harvest first. " +
        "This normally happens on a timer.",
    ),
    h(
      "button",
      {
        class: "primary",
        type: "button",
        disabled: refreshBusy,
        on: { click: () => void refreshMetaNow() },
      },
      refreshBusy ? "Harvesting..." : "Fetch decks now",
    ),
    h(
      "p",
      { class: "smart-optin" },
      "It takes a few minutes and reads from the tournament and deck APIs.",
    ),
  );
}

/** How current the data behind all of this is, and when it will next be checked. */
function freshnessLine(): HTMLElement | null {
  const { refresh, refreshBusy } = store.state;
  if (!refresh) return null;

  const age = refresh.snapshotAgeHours;
  const when =
    age < 0
      ? "never harvested"
      : age < 1
        ? "updated in the last hour"
        : `updated ${Math.round(age)} hours ago`;
  const cadence = refresh.enabled
    ? `checking every ${refresh.intervalHours} hours`
    : "automatic refresh is off";

  return h(
    "p",
    { class: `smart-freshness${refresh.stale ? " is-stale" : ""}` },
    `Meta ${when}, ${cadence}.`,
    h(
      "button",
      {
        class: "step",
        type: "button",
        disabled: refreshBusy || refresh.status === "running",
        on: { click: () => void refreshMetaNow() },
      },
      refreshBusy || refresh.status === "running" ? "Harvesting..." : "Refresh now",
    ),
  );
}

/**
 * The picker is a persistent, mutated-in-place layout, not a tree rebuilt every render.
 *
 * It used to be the latter -- `legendPicker()` returned a brand-new `<section>`, with a
 * brand-new `<input>` inside it, on every store update. `setSmartLegendQuery` fires on
 * every keystroke, which is a store update, which rebuilt the section, which discarded
 * the input the player was still typing into. `h()`'s children are attached with
 * `appendChild`, and appending an element that is already connected to the document
 * detaches it from its current parent first -- so for one instant the field the player
 * was focused in did not exist in the document at all, which blurs it exactly as
 * deleting and recreating it would. One keystroke, one rebuild, one lost focus.
 *
 * The search input, the grid, the hint line and the sort control are the parts state
 * changes on every keystroke or filter -- so they are built once, cached below, and
 * only their *contents* are replaced on each call. Nothing that contains the input is
 * ever detached and reattached once it exists.
 */
interface PopulatedPicker {
  root: HTMLElement;
  search: HTMLInputElement;
  sort: HTMLElement;
  hint: HTMLElement;
  grid: HTMLElement;
}

interface PickerLayout {
  root: HTMLElement;
  freshness: HTMLElement;
  resume: HTMLElement;
  nudge: HTMLElement;
  body: HTMLElement;
  /** Which of loading / empty / populated the body slot currently holds. Rewriting
   * `body`'s contents is only safe when this actually changes -- doing it every render
   * would disconnect-and-reconnect the populated branch (and its input) exactly as
   * often as rebuilding the whole section did. */
  bodyMode: "loading" | "empty" | "populated" | null;
  populated: PopulatedPicker | null;
}

let layout: PickerLayout | null = null;

function ensureLayout(): PickerLayout {
  if (layout === null) {
    const freshness = h("div", { class: "freshness-slot" });
    const resume = h("div", { class: "resume-slot" });
    const nudge = h("div", { class: "nudge-slot" });
    const body = h("div", { class: "picker-body-slot" });
    const root = h(
      "section",
      { class: "smart-picker" },
      h("p", { class: "eyebrow" }, "RiftDesk · deck finder"),
      h("h2", {}, "Start with a legend."),
      h(
        "p",
        { class: "smart-lede" },
        "Choose a legend and RiftDesk will line up one complete candidate list with every card kept in context. " +
          "No collection setup required.",
      ),
      freshness,
      // Before the picker: finishing something already started beats starting again.
      resume,
      nudge,
      body,
    );
    layout = { root, freshness, resume, nudge, body, bodyMode: null, populated: null };
  }
  return layout;
}

function ensurePopulated(): PopulatedPicker {
  const search = h("input", {
    class: "smart-search",
    type: "search",
    placeholder: "Filter legends",
    on: {
      input: (event) => setSmartLegendQuery((event.target as HTMLInputElement).value),
    },
  });
  const sort = h("div", { class: "picker-sort-slot" });
  const hint = h("p", { class: "picker-hint" });
  const grid = h("div", { class: "legend-grid" });
  const root = h("div", { class: "picker-populated" }, search, sort, hint, grid);
  return { root, search, sort, hint, grid };
}

export function legendPicker(): HTMLElement {
  const { smartLegends, smartBusy, smartLegendQuery } = store.state;
  const state = ensureLayout();

  replace(state.freshness, freshnessLine());
  replace(state.resume, resumeStrip());
  replace(state.nudge, collectionNudge());

  if (smartLegends.length === 0) {
    const mode = smartBusy ? "loading" : "empty";
    if (state.bodyMode !== mode) {
      replace(state.body, smartBusy ? h("p", { class: "empty" }, "Loading...") : emptyPicker());
      state.bodyMode = mode;
    }
    return state.root;
  }

  if (state.bodyMode !== "populated") {
    state.populated = ensurePopulated();
    replace(state.body, state.populated.root);
    state.bodyMode = "populated";
  }
  const populated = state.populated!;

  // The one field synced from state rather than left to the DOM: a query typed here
  // has to survive this render, but a query arriving from elsewhere (a "clear search"
  // control, a restored session) still has to reach the field the player is looking at.
  if (document.activeElement !== populated.search) populated.search.value = smartLegendQuery;

  const needle = smartLegendQuery.trim().toLowerCase();
  const shown = needle
    ? smartLegends.filter((legend) => legend.name.toLowerCase().includes(needle))
    : smartLegends.slice(0, 18);

  replace(populated.sort, sortControl());
  replace(
    populated.hint,
    !needle && smartLegends.length > shown.length
      ? h("span", {}, `Showing the leading ${shown.length}. Search to explore all ${smartLegends.length} legends.`)
      : null,
  );
  replace(populated.grid, ...shown.map((l) => legendCard(l, smartBusy)));

  return state.root;
}
