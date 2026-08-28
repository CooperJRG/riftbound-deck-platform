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
import { fragment, h } from "../../ui/dom";

const NUDGE_DISMISSED = "atlas.collection-nudge-dismissed";

function nudgeDismissed(): boolean {
  try {
    return localStorage.getItem(NUDGE_DISMISSED) === "1";
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
    "section",
    { class: "collection-nudge" },
    h("h3", {}, "Short of a few cards?"),
    h(
      "p",
      {},
      "Say roughly what you have and the questions get shorter — we stop asking about " +
        "cards you have already accounted for. You can change it whenever you like.",
    ),
    h("div", { class: "quick-rules" }, rule("Common"), rule("Uncommon"), rule("Rare")),
    h(
      "button",
      {
        class: "quiet-button",
        type: "button",
        on: { click: dismissNudge },
      },
      "I have most cards — don't ask again",
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
        legend.tournamentDeckCount ? ` · ${legend.tournamentDeckCount} from tournaments` : "",
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

export function legendPicker(): HTMLElement {
  const { smartLegends, smartBusy, smartLegendQuery } = store.state;
  const needle = smartLegendQuery.trim().toLowerCase();
  const shown = needle
    ? smartLegends.filter((legend) => legend.name.toLowerCase().includes(needle))
    : smartLegends.slice(0, 18);

  return h(
    "section",
    { class: "smart-picker" },
    h("p", { class: "eyebrow" }, "Find a deck"),
    h("h2", {}, "Which legend do you want to build?"),
    h(
      "p",
      { class: "smart-lede" },
      "Pick a legend, then scan one complete candidate list with every card kept in context. " +
        "You do not need to have entered your collection.",
    ),
    freshnessLine(),
    // Before the picker: finishing something already started beats starting again.
    resumeStrip(),
    collectionNudge(),
    smartLegends.length === 0
      ? smartBusy
        ? h("p", { class: "empty" }, "Loading...")
        : emptyPicker()
      : fragment(
          h("input", {
            class: "smart-search",
            type: "search",
            placeholder: "Filter legends",
            value: smartLegendQuery,
            on: {
              input: (event) =>
                setSmartLegendQuery((event.target as HTMLInputElement).value),
            },
          }),
          sortControl(),
          !needle && smartLegends.length > shown.length
            ? h("p", { class: "picker-hint" }, `Showing the leading ${shown.length}. Search to explore all ${smartLegends.length} legends.`)
            : null,
          h("div", { class: "legend-grid" }, ...shown.map((l) => legendCard(l, smartBusy))),
        ),
  );
}
