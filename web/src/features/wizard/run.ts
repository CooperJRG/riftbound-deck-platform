/**
 * A round of the wizard, and the two things that stay on screen throughout.
 *
 * The **floor** -- the best deck we can already promise -- so a player can stop at any
 * round and leave with something real rather than being held hostage to finishing. And
 * **why** we are asking, in plain words, because a wizard that cannot explain itself is
 * indistinguishable from one that is guessing.
 */

import type { BanNotice, DeckCost, Proposal, SmartSession } from "../../api/types";
import {
  acceptSmartDeck,
  closeSmartSession,
  refineSmartDeck,
  saveSmartCollection,
  setView,
  showSmartReadyDeck,
  submitSmartRound,
} from "../../state/actions";
import { store } from "../../state/store";
import { h, replace } from "../../ui/dom";
import { legendPicker } from "./picker";
import { repairPanel, scorePanel } from "./repairs";
import { requirementList } from "./rows";
import { ownershipProgress } from "./ownership";

/**
 * The one successful outcome Smart Decks promises.
 *
 * A floor is already a complete deck. Showing the candidate still being investigated,
 * a repaired version and this floor at once makes one answer look like three competing
 * decks. Stop here instead: one deck, one strength, one save action. Looking for a
 * stronger option remains available, but only after somebody asks for it.
 */
function readyDeck(session: SmartSession, proposal: Proposal, busy: boolean): HTMLElement {
  const floor = proposal.floor!;
  const strength = floor.score?.scored ? Math.round(floor.score.meta) : null;

  return h(
    "section",
    { class: "smart-ready" },
    h("p", { class: "eyebrow" }, "Deck ready"),
    h("h2", {}, session.legendName),
    h(
      "p",
      { class: "smart-ready-lede" },
      "A complete list based on your answers and collection shortcuts. Check the cards below before you play.",
    ),
    strength === null
      ? null
      : h(
          "p",
          { class: "smart-ready-score" },
          h("strong", {}, `${strength}/100`),
          h("span", {}, "estimated strength"),
        ),
    h("p", { class: "smart-ready-summary" }, floor.summary),
    h("div", { class: "ready-card-list" },
      ...["legend", "main", "runes", "battlefields", "sideboard"].map((zone) => {
        const cards = floor.cards.filter((card) => card.zone === zone);
        if (!cards.length) return null;
        const label = { legend: "Legend", main: "Main deck · includes your chosen champion", runes: "Runes", battlefields: "Battlefields", sideboard: "Sideboard" }[zone] ?? zone;
        return h("details", { class: "ready-zone", open: zone === "main" },
          h("summary", {}, label, h("span", {}, `${cards.reduce((sum, card) => sum + card.copies, 0)} copies`)),
          h("ul", {}, ...cards.map((card) => h("li", {},
            card.imageUrl ? h("img", { src: card.imageUrl, alt: "", loading: "lazy" }) : null,
            h("strong", {}, `${card.copies}×`), h("span", {}, card.name)))));
      })),
    banPanel(proposal.banNotices),
    sideboardNotice(),
    h(
      "button",
      {
        class: "primary smart-ready-save",
        type: "button",
        disabled: busy,
        on: { click: () => void acceptSmartDeck("floor") },
      },
      busy ? "Saving…" : "Save & open this deck",
    ),
    h(
      "div",
      { class: "smart-ready-secondary" },
      proposal.phase !== "done"
        ? h(
            "button",
            { class: "step", type: "button", disabled: busy, on: { click: refineSmartDeck } },
            "Keep checking for a stronger option",
          )
        : null,
      h(
        "button",
        { class: "step", type: "button", disabled: busy, on: { click: closeSmartSession } },
        "Try another legend",
      ),
    ),
    h("div", { class: "ready-collection-save" },
      h("button", { class: "quiet-button", type: "button", disabled: busy, on: { click: () => void saveSmartCollection() } }, "Save counts & use my collection"),
      h("p", { class: "smart-optin" }, "Save the exact counts you supplied for next time. Assumed playsets are not recorded as exact counts.")),
  );
}

/** Honest progress before there is a deck to save. */
function noDeckYet(proposal: Proposal, knownCards: number): HTMLElement {
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
    "Constructed: 40 main-deck cards including your chosen champion, 12 runes, 3 different battlefields, and up to 10 sideboard cards. ",
    h("a", { href: "https://playriftbound.com/en-us/rules-hub/", target: "_blank", rel: "noopener noreferrer" }, "Official rules"),
  );
}

function runView(session: SmartSession): HTMLElement {
  const proposal = session.proposal;
  const { smartAnswers, smartBusy, smartFinished } = store.state;

  if (smartFinished || session.savedDeckId) return finishedPanel();
  if (!proposal) return h("p", { class: "empty" }, "Loading...");
  if (proposal.floor && store.state.smartShowing === "ready") {
    return readyDeck(session, proposal, smartBusy);
  }

  const parts: HTMLElement[] = [roundHeader(session, proposal)];
  if (proposal.floor) {
    parts.push(
      h(
        "aside",
        { class: "smart-refining" },
        h("strong", {}, "A complete deck is already ready."),
        h("span", {}, "These questions are optional and only look for a stronger alternative."),
        h(
          "button",
          { class: "step", type: "button", on: { click: showSmartReadyDeck } },
          "Back to ready deck",
        ),
      ),
    );
  } else {
    parts.push(noDeckYet(proposal, session.knownCards));
  }

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

  const costLine = (cost: DeckCost | null): HTMLElement | null => {
    // The first question somebody short of cards asks, and until now the app had no
    // answer to it anywhere. Shown only when there is a bill: telling a player who can
    // field the deck that it costs them nothing is noise.
    if (!cost || cost.affordable) return null;
    return h(
      "p",
      { class: `deck-cost${cost.scarceShort > 0 ? " is-steep" : ""}` },
      cost.summary,
    );
  };

  const rows = proposal.question ? proposal.question.cards : proposal.requirements;
  const progress = ownershipProgress(rows, smartAnswers, store.state.smartTouched);
  // The two rounds ask opposite questions, so they say opposite things. A deck is a
  // real list to mark exceptions against; a checklist is a pool to tick from.
  const heading = proposal.question
    ? proposal.question.reason
    : // Not the list's own name. Those are submitted by whoever uploaded it and run
      // from the descriptive to the unreadable -- a heading of "喵喵喵" tells the player
      // nothing about what they are looking at. The champion does, and the provenance
      // line below already credits the list.
      `${proposal.deck?.championName || "This deck"} — mark anything you are short of`;
  const submitLabel = proposal.question ? "Use these quantities" : "Confirm cards & find my deck";

  parts.push(
    h(
      "section",
      { class: "smart-round-body" },
      h("h3", {}, heading),
      proposal.floor ? null : scorePanel(proposal.deckScore),
      costLine(proposal.deck?.coverage.cost ?? null),
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
      h("p", { class: "decision-instruction" }, proposal.question
        ? "These are possible replacements. Set how many copies you have. A card left at zero will be recorded as none when you continue."
        : "Check this complete list. Unconfirmed cards start at the requested quantity; reduce any you are missing. Continuing confirms the quantities shown."),
      requirementList(rows, smartAnswers),
      h(
        "div",
        { class: "smart-actions ownership-actions" },
        h("div", { class: "ownership-progress", role: "status", aria: { live: "polite", atomic: "true" } },
          h("strong", {}, `${progress.confirmed} of ${progress.total} card quantities confirmed`),
          h("span", {}, [
            progress.missingCopies ? `${progress.missingCopies} missing copies to work around` : "",
            progress.assumed ? `${progress.assumed} still assumed available` : "",
            progress.unanswered ? `${progress.unanswered} left at zero` : "",
          ].filter(Boolean).join(" · ") || "All shown quantities checked")),
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
        // The way out, offered exactly when the copy above starts promising it. Once a
        // deck is secured the round is optional -- "stop here and keep what you have"
        // is what the reason line says -- and until now there was no button that did it,
        // so the only way to stop was to answer another screen.
        proposal.floor
          ? h(
              "button",
              {
                class: "quiet-button",
                type: "button",
                disabled: smartBusy,
                on: { click: showSmartReadyDeck },
              },
              "Back to ready deck",
            )
          : null,
      ),
    ),
  );

  // One deck, already chosen.
  //
  // This used to render both repairs with a button under each and leave the player to
  // arbitrate between two lists they had never seen played, in the middle of telling us
  // what they own. The app is the one holding the numbers, so it decides -- on the
  // legend score, because a repair competes with other builds of the same legend rather
  // than with the format.
  //
  // It still says which kind it picked. Choosing for someone is not the same as not
  // telling them what they are holding, and the two are genuinely different products:
  // one is the tournament deck adapted, the other a legal deck in the same colours.
  const chosen = proposal.chosen === "free" ? proposal.free : proposal.conservative;
  if (!proposal.floor && chosen && (chosen.drift > 0 || proposal.chosen === "free")) {
    parts.push(
      repairPanel(
        chosen,
        "Your deck",
        proposal.chosen === "free"
          ? "Built from what you own. Further from the original list, and the stronger of the two for your collection."
          : "The same deck with your gaps filled from cards the field plays alongside it, so it still plays like the list that won.",
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
  const activeKey = (document.activeElement as HTMLElement | null)?.dataset.answerKey;
  const { smartSession } = store.state;
  const view = smartSession ? runView(smartSession) : legendPicker();
  // legendPicker() returns the same cached element on every call once it exists, so
  // this only actually swaps the DOM when the view genuinely changes (entering or
  // leaving a session). Calling replace() unconditionally would remove and re-add
  // that cached element on every render regardless -- disconnecting the search input
  // inside it, and its focus, exactly as often as never caching it at all would.
  if (root.firstElementChild !== view) replace(root, view);
  if (activeKey) {
    const buttons = Array.from(root.querySelectorAll<HTMLButtonElement>("[data-answer-key]"));
    const previous = buttons.find((button) => button.dataset.answerKey === activeKey);
    const next = previous?.disabled
      ? previous.closest(".req-counter")?.querySelector<HTMLButtonElement>("button:not(:disabled)")
      : previous;
    next?.focus({ preventScroll: true });
  }
}
