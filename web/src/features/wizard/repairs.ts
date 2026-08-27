/**
 * What a repair changed, and the deck it produced.
 *
 * Shown rather than summarised: a repaired deck is a cousin of the deck that won, not
 * the deck that won. A swap list is a changelog, and a changelog is no substitute for
 * the thing it describes, so the finished list is here too.
 */

import type { DeckScore, Repair } from "../../api/types";
import { acceptSmartDeck } from "../../state/actions";
import { h } from "../../ui/dom";
import { plural } from "./rows";

/**
 * What we changed, and why.
 *
 * Shown rather than summarised: a repaired deck is a cousin of the deck that won, not
 * the deck that won, and a player is owed the difference before they take it to an
 * event and wonder why it plays differently.
 */
/**
 * The deck a repair actually produces.
 *
 * Collapsed, because most of it is the deck already on screen; open it and the swapped
 * cards are at the top of each zone, marked as new. The reported symptom was a swap
 * bringing in Rocket Barrage and Rocket Barrage appearing nowhere -- a swap list is a
 * changelog, and a changelog is no substitute for the thing it describes.
 */
function finishedDeck(repair: Repair): HTMLElement {
  const cards = repair.cards ?? [];
  const zones: { zone: string; title: string }[] = [
    { zone: "main", title: "Main deck" },
    { zone: "runes", title: "Runes" },
    { zone: "battlefields", title: "Battlefields" },
  ];
  const added = cards.filter((card) => card.added).length;

  return h(
    "details",
    { class: "finished-deck" },
    h(
      "summary",
      {},
      "See the finished deck",
      added
        ? h("span", { class: "finished-new" }, `${plural(added, "new card")}`)
        : null,
    ),
    ...zones.map((group) => {
      const members = cards.filter((card) => card.zone === group.zone);
      if (!members.length) return null;
      const copies = members.reduce((sum, card) => sum + card.copies, 0);
      return h(
        "div",
        { class: "finished-zone" },
        h(
          "h5",
          {},
          group.title,
          h("small", {}, `${plural(members.length, "card")} · ${plural(copies, "copy", "copies")}`),
        ),
        h(
          "ul",
          {},
          ...members.map((card) =>
            h(
              "li",
              { class: card.added ? "finished-card is-new" : "finished-card" },
              h("span", { class: "finished-copies" }, `${card.copies}x`),
              h("span", { class: "finished-name" }, card.name),
              card.added ? h("span", { class: "finished-tag" }, "new") : null,
            ),
          ),
        ),
      );
    }),
  );
}

/**
 * The two scores, side by side.
 *
 * The champion score leads because it is the one a player in the middle of a build is
 * asking about -- how close is this to the best version of the deck I am building -- and
 * it is the one the wizard used to choose this deck over the alternative. The format
 * score sits beside it because the two disagree in a way worth seeing: a good build of a
 * fringe champion reads 79 and 32, and only one of those numbers answers "should I take
 * this to an event".
 */
export function scorePanel(score: DeckScore | null): HTMLElement | null {
  if (!score) return null;
  if (!score.scored) {
    return h(
      "div",
      { class: "deck-scores is-unscored", title: score.summary },
      h("span", { class: "deck-score" }, h("b", {}, "—"), h("i", {}, "for this champion")),
      h("span", { class: "deck-score" }, h("b", {}, String(Math.round(score.meta))), h("i", {}, "in the format")),
    );
  }
  return h(
    "div",
    { class: "deck-scores", title: score.summary },
    h(
      "span",
      { class: "deck-score is-primary" },
      h("b", {}, String(Math.round(score.champion))),
      h("i", {}, "for this champion"),
    ),
    h(
      "span",
      { class: "deck-score" },
      h("b", {}, String(Math.round(score.meta))),
      h("i", {}, "in the format"),
    ),
  );
}

export function repairPanel(repair: Repair, label: string, note: string, busy: boolean): HTMLElement {
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
    scorePanel(repair.score),
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
    // The finished list. Without it a swap names a card that appears nowhere on the
    // page -- the wizard describing a deck it declines to show you.
    // `?? []` rather than a bare read: on a version skew this degrades to "no list"
    // instead of throwing `Cannot read properties of undefined`, which names the wrong
    // problem entirely.
    (repair.cards ?? []).length ? finishedDeck(repair) : null,
    h(
      "button",
      {
        type: "button",
        disabled: busy || !repair.legal,
        on: { click: () => void acceptSmartDeck(repair.kind === "free" ? "free" : "conservative") },
      },
      "Save this deck",
    ),
  );
}
