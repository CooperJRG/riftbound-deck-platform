/**
 * The deck the wizard built, and one more pass over it.
 *
 * What this replaced: the wizard used to hand the player straight to the builder — a
 * card-search workspace with a deck panel down one side. That is a place to *work on* a
 * deck, not a place to be shown one, and arriving there after answering questions made
 * it hard to tell what had happened or what the app had decided.
 *
 * So this page does three things the builder cannot:
 *
 * **It shows the deck.** Full card art, grouped by zone, brought-in cards first. A deck
 * is a thing you look at.
 *
 * **It says what changed and why.** Every swap, named on both sides, with the reason —
 * "the field plays this alongside the deck 73% of the time". A player is owed the
 * difference between the list that won and the list they are holding before they take it
 * to an event and wonder why it plays differently.
 *
 * **It lets them say no.** Not "I don't own this" — the wizard has asked that four times
 * already — but "I don't want to play this". Those are different claims and the app
 * keeps them apart: ownership is a fact about a collection it can offer to remember,
 * taste is a fact about a person it stores for this build and writes nowhere.
 *
 * That last one is the point of the screen. A tool that can only hear "I haven't got
 * that" can only ever build the meta back at you, and most people are not trying to
 * arrive at the same sixty cards as everyone else.
 */

import type { DeckScore, Repair, RepairDeckCard, SmartSession, Swap } from "../../api/types";
import { acceptSmartDeck, declineSmartCards } from "../../state/actions";
import { store } from "../../state/store";
import { h } from "../../ui/dom";
import { scorePanel } from "./repairs";

const ZONES: { zone: string; title: string }[] = [
  { zone: "main", title: "Main deck" },
  { zone: "runes", title: "Runes" },
  { zone: "battlefields", title: "Battlefields" },
];

/** Cards currently ruled out, so a decline is reversible rather than a disappearance. */
function declinedStrip(session: SmartSession, busy: boolean): HTMLElement | null {
  if (!session.declined.length) return null;
  const ids = session.declined.map((card) => card.cardId);
  return h(
    "section",
    { class: "finish-declined" },
    h("h4", {}, "Not playing"),
    h(
      "p",
      { class: "finish-note" },
      "Left out because you said so, not because you are short of them. The deck below is built around that.",
    ),
    h(
      "ul",
      {},
      ...session.declined.map((card) =>
        h(
          "li",
          {},
          h("span", {}, card.name),
          h(
            "button",
            {
              type: "button",
              class: "quiet-button",
              disabled: busy,
              on: {
                click: () =>
                  void declineSmartCards(ids.filter((id) => id !== card.cardId)),
              },
            },
            "Use it after all",
          ),
        ),
      ),
    ),
  );
}

function swapList(swaps: Swap[]): HTMLElement | null {
  if (!swaps.length) return null;
  return h(
    "section",
    { class: "finish-swaps" },
    h("h4", {}, "What changed"),
    h(
      "p",
      { class: "finish-note" },
      "You were short of these, so they were replaced with cards the field plays alongside the rest of the deck.",
    ),
    h(
      "ul",
      { class: "swap-list" },
      ...swaps.map((swap) =>
        h(
          "li",
          { class: "swap" },
          h("span", { class: "swap-out" }, `${swap.copies}x ${swap.outName}`),
          h("span", { class: "swap-arrow" }, "→"),
          h("span", { class: "swap-in" }, swap.inName),
          h("span", { class: "swap-why" }, swap.reason),
        ),
      ),
    ),
  );
}

/** One card, with the control that makes this screen worth having. */
function cardRow(card: RepairDeckCard, declined: string[], busy: boolean): HTMLElement {
  return h(
    "li",
    { class: `finish-card${card.added ? " is-new" : ""}` },
    card.imageUrl
      ? h("img", { src: card.imageUrl, alt: card.name, loading: "lazy" })
      : h("span", { class: "finish-card-art-empty" }, card.name.slice(0, 2)),
    h("span", { class: "finish-copies" }, `${card.copies}×`),
    h("span", { class: "finish-name" }, card.name),
    card.added ? h("span", { class: "finish-tag" }, "new") : null,
    h(
      "button",
      {
        type: "button",
        class: "finish-decline",
        disabled: busy,
        title: `Rebuild without ${card.name}`,
        aria: { label: `Do not play ${card.name}` },
        on: { click: () => void declineSmartCards([...declined, card.cardId]) },
      },
      "Not this",
    ),
  );
}

function deckPanel(cards: RepairDeckCard[], declined: string[], busy: boolean): HTMLElement {
  return h(
    "section",
    { class: "finish-deck" },
    ...ZONES.flatMap((group) => {
      const members = cards.filter((card) => card.zone === group.zone);
      if (!members.length) return [];
      const copies = members.reduce((sum, card) => sum + card.copies, 0);
      return [
        h(
          "div",
          { class: "finish-zone" },
          h(
            "h4",
            {},
            group.title,
            h("small", {}, `${members.length} cards · ${copies} copies`),
          ),
          h("ul", { class: "finish-cards" }, ...members.map((card) => cardRow(card, declined, busy))),
        ),
      ];
    }),
  );
}

/**
 * The deck being handed over, whichever route produced it.
 *
 * A repair when one was needed, the floor when the collection built something outright.
 * Both arrive with resolved names and art, so this screen never has to care which.
 */
export function finishedDeck(session: SmartSession): {
  cards: RepairDeckCard[];
  swaps: Swap[];
  score: DeckScore | null;
  kind: "floor" | "conservative" | "free";
} | null {
  const proposal = session.proposal;
  if (!proposal) return null;
  const repair: Repair | null =
    proposal.chosen === "free" ? proposal.free : proposal.chosen ? proposal.conservative : null;
  if (repair) {
    return {
      cards: repair.cards ?? [],
      swaps: repair.swaps ?? [],
      score: repair.score,
      kind: proposal.chosen === "free" ? "free" : "conservative",
    };
  }
  if (proposal.floor) {
    return {
      cards: proposal.floor.cards ?? [],
      swaps: [],
      score: proposal.floor.score,
      kind: "floor",
    };
  }
  return null;
}

export function finishView(session: SmartSession): HTMLElement | null {
  const result = finishedDeck(session);
  if (!result || !result.cards.length) return null;
  const busy = store.state.smartBusy;
  const declined = session.declined.map((card) => card.cardId);

  return h(
    "div",
    { class: "smart-finish" },
    h(
      "header",
      { class: "finish-head" },
      h("p", { class: "eyebrow" }, "Your deck"),
      h("h2", {}, `${session.legendName} — ready to play`),
      scorePanel(result.score),
      h(
        "p",
        { class: "finish-lede" },
        result.kind === "floor"
          ? "Built from the cards you told us you have."
          : result.kind === "free"
            ? "Built from what you own. Further from the published list, and the stronger of the two for your collection."
            : "The published list with your gaps filled from cards the field plays alongside it, so it still plays like the deck that won.",
      ),
    ),
    declinedStrip(session, busy),
    swapList(result.swaps),
    deckPanel(result.cards, declined, busy),
    h(
      "section",
      { class: "finish-actions" },
      h(
        "p",
        { class: "finish-note" },
        "Anything here you would rather not play? Say so and it will build around it — the best deck in the format is not everyone's best deck.",
      ),
      h(
        "button",
        {
          class: "primary",
          type: "button",
          disabled: busy,
          on: { click: () => void acceptSmartDeck(result.kind) },
        },
        busy ? "Working…" : "Save to my decks",
      ),
    ),
  );
}
