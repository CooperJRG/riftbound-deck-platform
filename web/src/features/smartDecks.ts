/**
 * Smart Decks: the deck-building wizard.
 *
 * The interaction the whole feature turns on is one row: `Need 3 - You have [0][1][2][3]`,
 * pre-set to "all of them". Being short one copy of a three-of is the normal case, not
 * an edge case, so it is the default affordance rather than something to discover; and
 * because the common answer is yes, the common answer costs no clicks.
 *
 * Two things stay on screen at all times:
 *
 * - the **floor**, the best deck we can already promise, so a player can stop at any
 *   round and leave with something real rather than being held hostage to finishing;
 * - **why** the wizard is asking this, in plain words, because a wizard that cannot
 *   explain itself is indistinguishable from one that is guessing.
 */

import type {
  BanNotice,
  LegendChoice,
  Proposal,
  Repair,
  RequirementRow,
  SmartSession,
} from "../api/types";
import {
  acceptSmartDeck,
  closeSmartSession,
  saveSmartCollection,
  setSmartAnswer,
  setSmartLegendQuery,
  startSmartSession,
  submitSmartRound,
} from "../state/actions";
import { store } from "../state/store";
import { h, replace } from "../ui/dom";

/** Battlefield art is landscape; the tile rotates it to match every other card. */
function isLandscape(zone: string): boolean {
  return zone === "battlefields";
}

function cardThumb(row: RequirementRow): HTMLElement {
  const art = row.imageUrl
    ? h("img", { src: row.imageUrl, alt: "", loading: "lazy" })
    : h("div", { class: "tile-art-empty" }, row.name.slice(0, 1));
  return h(
    "div",
    { class: `req-art${isLandscape(row.zone) ? " tile-art is-landscape" : " tile-art"}` },
    art,
  );
}

// -- the counter --------------------------------------------------------------

/**
 * `Need 3 - You have [0][1][2][3]`.
 *
 * Discrete buttons rather than a number input: the range is tiny, every value is one
 * click away, and there is no way to type something that is not a legal answer.
 * Twelve-rune rows fall back to a stepper, because thirteen buttons is not a row.
 */
function counter(row: RequirementRow, value: number): HTMLElement {
  const choose = (next: number) => setSmartAnswer(row.cardId, next);

  if (row.needed > 4) {
    return h(
      "div",
      { class: "req-counter req-counter-wide" },
      h(
        "button",
        {
          class: "step",
          type: "button",
          disabled: value <= 0,
          aria: { label: `One fewer ${row.name}` },
          on: { click: () => choose(value - 1) },
        },
        "-",
      ),
      h("span", { class: "req-count" }, `${value} / ${row.needed}`),
      h(
        "button",
        {
          class: "step",
          type: "button",
          disabled: value >= row.needed,
          aria: { label: `One more ${row.name}` },
          on: { click: () => choose(value + 1) },
        },
        "+",
      ),
    );
  }

  const options: HTMLElement[] = [];
  for (let n = 0; n <= row.needed; n += 1) {
    options.push(
      h(
        "button",
        {
          class: `req-pip${n === value ? " is-selected" : ""}`,
          type: "button",
          aria: {
            label: `${n} of ${row.name}`,
            pressed: String(n === value),
          },
          on: { click: () => choose(n) },
        },
        String(n),
      ),
    );
  }
  return h("div", { class: "req-counter" }, ...options);
}

function requirementRow(row: RequirementRow, value: number): HTMLElement {
  const short = value < row.needed;
  return h(
    "li",
    { class: `req${short ? " is-short" : ""}${row.known ? " is-known" : ""}` },
    cardThumb(row),
    h(
      "div",
      { class: "req-body" },
      h("span", { class: "req-name" }, row.name),
      h(
        "span",
        { class: "req-meta" },
        row.needed === 1 ? "Need 1" : `Need ${row.needed}`,
        row.rarity ? ` · ${row.rarity}` : "",
        row.known ? " · already answered" : "",
      ),
    ),
    counter(row, value),
  );
}

/**
 * The rows for this round, split into what is genuinely new and what we already know.
 *
 * Known rows are collapsed rather than dropped: they still need to be visible (a player
 * may have miscounted, or opened a booster since) but they should not be re-read every
 * round. Only the new rows carry attention.
 */
function requirementList(rows: RequirementRow[], answers: Map<string, number>): HTMLElement {
  const fresh = rows.filter((row) => !row.known);
  const known = rows.filter((row) => row.known);
  const render = (list: RequirementRow[]) =>
    list.map((row) => requirementRow(row, answers.get(row.cardId) ?? row.have));

  const parts: HTMLElement[] = [h("ul", { class: "req-list" }, ...render(fresh))];
  if (known.length) {
    parts.push(
      h(
        "details",
        { class: "req-known" },
        h(
          "summary",
          {},
          `${known.length} card${known.length === 1 ? "" : "s"} you have already answered for`,
        ),
        h("ul", { class: "req-list" }, ...render(known)),
      ),
    );
  }
  return h("div", { class: "req-groups" }, ...parts);
}

// -- the floor ----------------------------------------------------------------

/**
 * "Best deck you can build right now", or an honest statement that there is not one yet.
 *
 * Always rendered. A player who has answered two rounds and wants to stop should be
 * able to see, without hunting, whether stopping leaves them with a deck.
 */
function floorBanner(proposal: Proposal, knownCards: number, busy: boolean): HTMLElement {
  if (!proposal.floor) {
    // Before anything has been answered, the shortfall is the whole deck -- which is
    // true and useless. "Short by 1 legend, 1 champion, 40 main" reads as "you own
    // nothing" when what it means is "we have not asked yet".
    const detail = knownCards
      ? proposal.feasibility
      : "Answer this round and we will tell you what you can build.";
    return h(
      "div",
      { class: "floor floor-none" },
      h("strong", {}, knownCards ? "No complete deck yet." : "Nothing to go on yet."),
      h("span", { class: "floor-detail" }, detail),
    );
  }
  return h(
    "div",
    { class: "floor floor-ready" },
    h("strong", {}, "Best deck you can build right now"),
    h("span", { class: "floor-detail" }, proposal.floor.summary),
    h(
      "button",
      {
        class: "primary",
        type: "button",
        disabled: busy,
        on: { click: () => void acceptSmartDeck("floor") },
      },
      "Save this deck",
    ),
  );
}

// -- bans ---------------------------------------------------------------------

/**
 * Ban warnings, told rather than enforced.
 *
 * We do not know what the player is doing with the deck. Somebody building for a casual
 * pod, a local format, or an older event is not wrong to want a card that constructed
 * has banned, so removing it silently -- or keeping it silently -- makes the app the
 * least trustworthy thing in the room. Saying so costs a line; guessing costs a game.
 */
function banPanel(notices: BanNotice[]): HTMLElement | null {
  if (!notices.length) return null;
  const enforced = notices.filter((n) => n.enforced);
  return h(
    "section",
    { class: "bans" },
    h(
      "header",
      { class: "bans-head" },
      h("h4", {}, enforced.length ? "Banned cards" : "Worth checking"),
      h(
        "span",
        { class: "bans-count" },
        `${notices.length} card${notices.length === 1 ? "" : "s"}`,
      ),
    ),
    h(
      "ul",
      { class: "ban-list" },
      ...notices.map((notice) =>
        h(
          "li",
          { class: `ban ban-${notice.source}` },
          h("span", { class: "ban-name" }, notice.name),
          h("span", { class: "ban-why" }, notice.message),
        ),
      ),
    ),
    h(
      "p",
      { class: "smart-optin" },
      "Ban lists move, and this one is for constructed. If you are playing another " +
        "format these may be fine - we are telling you, not deciding for you.",
    ),
  );
}

// -- repairs ------------------------------------------------------------------

/**
 * What we changed, and why.
 *
 * Shown rather than summarised: a repaired deck is a cousin of the deck that won, not
 * the deck that won, and a player is owed the difference before they take it to an
 * event and wonder why it plays differently.
 */
function repairPanel(repair: Repair, label: string, note: string, busy: boolean): HTMLElement {
  return h(
    "section",
    { class: "repair" },
    h(
      "header",
      { class: "repair-head" },
      h("h4", {}, label),
      h(
        "span",
        { class: `gap ${repair.drift === 0 ? "gap-ok" : "gap-short"}` },
        repair.drift === 0
          ? "Unchanged"
          : `${repair.drift} card${repair.drift === 1 ? "" : "s"} changed`,
      ),
      !repair.legal && h("span", { class: "gap gap-short" }, "Not legal"),
    ),
    h("p", { class: "repair-note" }, note),
    repair.swaps.length
      ? h(
          "ul",
          { class: "swap-list" },
          ...repair.swaps.map((swap) =>
            h(
              "li",
              { class: "swap" },
              h("span", { class: "swap-out" }, `${swap.copies}x ${swap.outName}`),
              h("span", { class: "swap-arrow" }, "->"),
              h("span", { class: "swap-in" }, swap.inName),
              h("span", { class: "swap-why" }, swap.reason),
            ),
          ),
        )
      : null,
    h(
      "button",
      {
        type: "button",
        disabled: busy || !repair.legal,
        on: { click: () => void acceptSmartDeck(repair.kind === "free" ? "free" : "conservative") },
      },
      "Save this version",
    ),
  );
}

// -- the legend picker --------------------------------------------------------

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

function legendPicker(): HTMLElement {
  const { smartLegends, smartBusy, smartLegendQuery } = store.state;
  const needle = smartLegendQuery.trim().toLowerCase();
  const shown = needle
    ? smartLegends.filter((legend) => legend.name.toLowerCase().includes(needle))
    : smartLegends;

  return h(
    "section",
    { class: "smart-picker" },
    h("h2", {}, "Which legend do you want to build?"),
    h(
      "p",
      { class: "smart-lede" },
      "Pick a legend and answer a couple of rounds about what you own. " +
        "You do not need to have entered your collection.",
    ),
    h("input", {
      class: "smart-search",
      type: "search",
      placeholder: "Filter legends",
      value: smartLegendQuery,
      on: {
        input: (event) => setSmartLegendQuery((event.target as HTMLInputElement).value),
      },
    }),
    smartLegends.length === 0 && !smartBusy
      ? h(
          "p",
          { class: "empty" },
          "No meta decks are loaded, so there is nothing to build from yet. " +
            "Run the meta pipeline and this list fills in.",
        )
      : h("div", { class: "legend-grid" }, ...shown.map((l) => legendCard(l, smartBusy))),
  );
}

// -- the run ------------------------------------------------------------------

function roundHeader(session: SmartSession, proposal: Proposal): HTMLElement {
  return h(
    "header",
    { class: "smart-head" },
    h(
      "div",
      {},
      h("h2", {}, session.legendName),
      h(
        "p",
        { class: "smart-why" },
        proposal.reason || "Tell us what you own and we will find the best deck you can build.",
      ),
    ),
    h(
      "div",
      { class: "smart-progress" },
      h("span", { class: "smart-round" }, `Round ${proposal.round + 1}`),
      h("span", { class: "smart-known" }, `${session.knownCards} cards known`),
      h(
        "button",
        { class: "step", type: "button", on: { click: closeSmartSession } },
        "Start over",
      ),
    ),
  );
}

function finishedPanel(): HTMLElement {
  return h(
    "section",
    { class: "smart-finish" },
    h("h3", {}, "Saved to your decks."),
    h(
      "p",
      {},
      "It is open in the builder. You can also keep what this session learned, " +
        "which is usually far quicker than entering a collection by hand.",
    ),
    h(
      "div",
      { class: "smart-finish-actions" },
      h(
        "button",
        {
          type: "button",
          disabled: store.state.smartBusy,
          on: { click: () => void saveSmartCollection() },
        },
        "Save my answers to my collection",
      ),
      h(
        "button",
        { class: "step", type: "button", on: { click: closeSmartSession } },
        "Build another",
      ),
    ),
    h(
      "p",
      { class: "smart-optin" },
      "Nothing is written unless you press that button. Saying you are missing a card " +
        "for one deck is not the same as saying you do not own it.",
    ),
  );
}

function sideboardNotice(): HTMLElement {
  return h(
    "p",
    { class: "smart-optin" },
    "Sideboards here allow 10 cards because that is what current tournament lists play. " +
      "Official rules may still cap it at 8 - trim before you play.",
  );
}

function runView(session: SmartSession): HTMLElement {
  const proposal = session.proposal;
  const { smartAnswers, smartBusy, smartFinished } = store.state;

  if (smartFinished || session.savedDeckId) return finishedPanel();
  if (!proposal) return h("p", { class: "empty" }, "Loading...");

  const parts: HTMLElement[] = [
    roundHeader(session, proposal),
    floorBanner(proposal, session.knownCards, smartBusy),
  ];

  if (proposal.phase === "done") {
    parts.push(
      h(
        "section",
        { class: "smart-done" },
        h("h3", {}, proposal.canBuild ? "That is the best we can do for this legend." : "Not this time."),
        h("p", {}, proposal.feasibility),
        !proposal.canBuild
          ? h(
              "p",
              { class: "smart-optin" },
              "We asked about every card that could have helped, so this is a real answer " +
                "rather than a guess. Another legend may go better.",
            )
          : null,
        h(
          "button",
          { class: "step", type: "button", on: { click: closeSmartSession } },
          "Try another legend",
        ),
      ),
    );
    const doneBans = banPanel(proposal.banNotices);
    if (doneBans) parts.push(doneBans);
    return h("div", { class: "smart-run" }, ...parts);
  }

  const rows = proposal.question ? proposal.question.cards : proposal.requirements;
  // The two rounds ask opposite questions, so they say opposite things. A deck is a
  // real list to mark exceptions against; a checklist is a pool to tick from.
  const heading = proposal.question
    ? proposal.question.reason
    : `${proposal.deck?.name ?? "This deck"} - mark anything you are short of`;
  const submitLabel = proposal.question ? "That is what I own" : "I have the rest";

  parts.push(
    h(
      "section",
      { class: "smart-round-body" },
      h("h3", {}, heading),
      proposal.deck
        ? h(
            "p",
            { class: "smart-source" },
            proposal.deck.provenance.summary,
            proposal.deck.provenance.url
              ? h(
                  "a",
                  {
                    href: proposal.deck.provenance.url,
                    target: "_blank",
                    rel: "noopener noreferrer",
                  },
                  "source",
                )
              : null,
          )
        : null,
      requirementList(rows, smartAnswers),
      h(
        "div",
        { class: "smart-actions" },
        h(
          "button",
          {
            class: "primary",
            type: "button",
            disabled: smartBusy,
            on: { click: () => void submitSmartRound() },
          },
          smartBusy ? "Working..." : submitLabel,
        ),
      ),
    ),
  );

  if (proposal.conservative && proposal.conservative.drift > 0) {
    parts.push(
      repairPanel(
        proposal.conservative,
        "Closest to the original",
        "Swaps only the flexible slots, so it still plays like the deck that won.",
        smartBusy,
      ),
    );
  }
  if (proposal.free) {
    parts.push(
      repairPanel(
        proposal.free,
        "Best from what you own",
        "Uses anything legal in your collection. Further from the original, but stronger for you.",
        smartBusy,
      ),
    );
  }
  const bans = banPanel(proposal.banNotices);
  if (bans) parts.push(bans);
  parts.push(sideboardNotice());
  return h("div", { class: "smart-run" }, ...parts);
}

export function renderSmartDecks(root: HTMLElement): void {
  const { smartSession } = store.state;
  replace(root, smartSession ? runView(smartSession) : legendPicker());
}
