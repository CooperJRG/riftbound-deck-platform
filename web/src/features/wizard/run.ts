/**
 * A round of the wizard, and the two things that stay on screen throughout.
 *
 * The **floor** -- the best deck we can already promise -- so a player can stop at any
 * round and leave with something real rather than being held hostage to finishing. And
 * **why** we are asking, in plain words, because a wizard that cannot explain itself is
 * indistinguishable from one that is guessing.
 */

import type { BanNotice, Proposal, SmartSession } from "../../api/types";
import {
  acceptSmartDeck,
  closeSmartSession,
  saveSmartCollection,
  setView,
  submitSmartRound,
} from "../../state/actions";
import { store } from "../../state/store";
import { h, replace } from "../../ui/dom";
import { legendPicker } from "./picker";
import { repairPanel } from "./repairs";
import { requirementList } from "./rows";

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
      : "Mark any shortages in the complete list and we will tell you what you can build.";
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
      h("span", { class: "smart-round" }, "Whole deck"),
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
      "Open it in the builder when you are ready. You can also keep what this session learned, " +
        "which is usually far quicker than entering a collection by hand.",
    ),
    h(
      "div",
      { class: "smart-finish-actions" },
      h(
        "button",
        { class: "primary", type: "button", on: { click: () => setView("build") } },
        "Open in builder",
      ),
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
      h("p", { class: "decision-instruction" }, "This is the whole list. Every card starts at the requested count—change only the cards you are short of, with the surrounding package still visible."),
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
