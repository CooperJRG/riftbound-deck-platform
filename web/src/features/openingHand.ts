/**
 * The opening hand: odds, and a simulator to see them happen.
 *
 * Two halves that answer the same question differently, and they must not be confused
 * for one another. The percentages are **exact**, computed server-side from the
 * hypergeometric distribution; the simulator deals **real** hands with a real shuffle.
 * Watching hands is how a curve stops being abstract, but a hand count is never a
 * substitute for the arithmetic — the numbers here are the arithmetic, and dealing a
 * thousand hands would only approach them.
 *
 * The deal is client-side on purpose: a shuffle needs no server, and a round trip per
 * draw would make the one interaction on this page feel like a form submission.
 *
 * The rules it runs on come from the format profile via the server — hand size, how
 * many cards a mulligan may recycle, and where they go. Nothing here hardcodes them,
 * because every number on the page is a function of the hand size and a guess would
 * make all of them confidently wrong.
 */

import type { CardOdds, OpeningOdds } from "../api/types";
import { store } from "../state/store";
import { h, replace } from "../ui/dom";
import { openCardPreview } from "./cardPreview";

/**
 * The dealt game, held here rather than in the store.
 *
 * It is ephemeral presentation state — a shuffle nobody expects to survive a reload,
 * and one that must never be mistaken for part of the deck. Same reasoning as
 * `deckExpanded` in the deck panel.
 */
interface Simulation {
  /** The undrawn library, top first. One entry per copy. */
  library: string[];
  hand: string[];
  /** Hand positions the player has marked to send to the bottom. */
  marked: Set<number>;
  /** Turn number, 1 = the opening hand before any draw step. */
  turn: number;
  mulliganed: boolean;
  /** Cards bottomed this game, so the readout can say what was sent away. */
  bottomed: string[];
}

let sim: Simulation | null = null;
let root: HTMLElement | null = null;

function repaint(): void {
  if (root) renderOpeningHand(root);
}

function cardName(cardId: string): string {
  return store.state.deckCards.get(cardId)?.card.name ?? cardId;
}

function cardArt(cardId: string): string {
  return store.state.deckCards.get(cardId)?.card.imageUrl ?? "";
}

/**
 * Fisher-Yates, so every ordering is equally likely.
 *
 * `sort(() => Math.random() - 0.5)` is the tempting one-liner and it is biased: the
 * comparator is inconsistent, so the result depends on the engine's sort algorithm and
 * some orderings come up far more often than others. On a simulator whose whole purpose
 * is to show what a random draw looks like, that would be the one bug that matters.
 */
function shuffled(cards: string[]): string[] {
  const out = cards.slice();
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j]!, out[i]!];
  }
  return out;
}

/** The main deck as one entry per copy. Runes and battlefields are never drawn. */
function library(): string[] {
  const cards: string[] = [];
  for (const [cardId, copies] of Object.entries(store.state.deck.main)) {
    for (let i = 0; i < copies; i += 1) cards.push(cardId);
  }
  return cards;
}

function deal(handSize: number): void {
  const deck = shuffled(library());
  sim = {
    library: deck.slice(handSize),
    hand: deck.slice(0, handSize),
    marked: new Set(),
    turn: 1,
    mulliganed: false,
    bottomed: [],
  };
  repaint();
}

function toggleMark(index: number, max: number): void {
  if (!sim || sim.mulliganed) return;
  if (sim.marked.has(index)) sim.marked.delete(index);
  else if (sim.marked.size < max) sim.marked.add(index);
  repaint();
}

/**
 * Take the mulligan: marked cards go to the bottom, and that many are drawn.
 *
 * Bottom rather than shuffle, because that is what the profile records. It matters:
 * a bottomed card cannot come back, so the replacements are drawn from cards that were
 * never in hand. Shuffling instead would let a card you just sent away return
 * immediately, which is a different game and different odds.
 */
function takeMulligan(): void {
  if (!sim || sim.mulliganed) return;
  const marked = [...sim.marked].sort((a, b) => a - b);
  const kept = sim.hand.filter((_, i) => !sim!.marked.has(i));
  const sent = marked.map((i) => sim!.hand[i]!);
  const drawn = sim.library.slice(0, sent.length);
  sim = {
    library: [...sim.library.slice(sent.length), ...sent],
    hand: [...kept, ...drawn],
    marked: new Set(),
    turn: 1,
    mulliganed: true,
    bottomed: sent,
  };
  repaint();
}

function keepHand(): void {
  if (!sim) return;
  sim = { ...sim, marked: new Set(), mulliganed: true };
  repaint();
}

function drawStep(perTurn: number): void {
  if (!sim) return;
  const drawn = sim.library.slice(0, perTurn);
  sim = {
    ...sim,
    library: sim.library.slice(drawn.length),
    hand: [...sim.hand, ...drawn],
    turn: sim.turn + 1,
    mulliganed: true,
  };
  repaint();
}

function reset(): void {
  sim = null;
  repaint();
}

// -- rendering ---------------------------------------------------------------

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function handCard(cardId: string, index: number, opts: { markable: boolean; max: number }): HTMLElement {
  const marked = sim?.marked.has(index) ?? false;
  const art = cardArt(cardId);
  const name = cardName(cardId);
  return h(
    "figure",
    { class: `sim-card${marked ? " is-marked" : ""}`, title: name },
    h(
      "button",
      {
        class: "sim-card-art",
        type: "button",
        aria: opts.markable
          ? {
              label: `${marked ? "Keep" : "Send to the bottom:"} ${name}`,
              pressed: String(marked),
            }
          : { label: `Read ${name}` },
        on: {
          click: () =>
            opts.markable ? toggleMark(index, opts.max) : openCardPreview(cardId, "main"),
        },
      },
      art
        ? h("img", { src: art, alt: name, loading: "lazy" })
        : h("span", { class: "mat-card-blank" }, name),
      marked ? h("span", { class: "sim-card-flag" }, "Bottom") : null,
    ),
    h("figcaption", {}, name),
  );
}

function simulator(odds: OpeningOdds): HTMLElement {
  const { handSize, mulliganMax, drawPerTurn } = odds.rules;

  if (!sim) {
    return h(
      "div",
      { class: "sim-empty" },
      h(
        "p",
        { class: "muted small" },
        `Deal a ${handSize}-card opening hand from your ${odds.deckSize}-card main deck, `
          + `then keep it or send up to ${mulliganMax} cards to the bottom.`,
      ),
      h(
        "button",
        { class: "primary", type: "button", on: { click: () => deal(handSize) } },
        "Deal a hand",
      ),
    );
  }

  const choosing = !sim.mulliganed;
  const marked = sim.marked.size;
  return h(
    "div",
    { class: "sim-board" },
    h(
      "div",
      { class: "sim-hand" },
      ...sim.hand.map((cardId, i) =>
        handCard(cardId, i, { markable: choosing, max: mulliganMax }),
      ),
    ),
    h(
      "p",
      { class: "sim-status muted small" },
      choosing
        ? marked
          ? `${marked} of ${mulliganMax} marked — they go to the bottom and you draw ${marked} back.`
          : `Click up to ${mulliganMax} cards to send to the bottom, or keep the hand as it is.`
        : `Turn ${sim.turn} · ${sim.hand.length} in hand · ${sim.library.length} left in deck`
          + (sim.bottomed.length
            ? ` · bottomed ${sim.bottomed.map(cardName).join(", ")}`
            : ""),
    ),
    h(
      "div",
      { class: "sim-actions" },
      choosing
        ? h(
            "button",
            {
              class: "primary",
              type: "button",
              disabled: marked === 0,
              on: { click: takeMulligan },
            },
            marked ? `Mulligan ${marked}` : "Mulligan",
          )
        : h(
            "button",
            {
              class: "primary",
              type: "button",
              disabled: sim.library.length === 0,
              on: { click: () => drawStep(drawPerTurn) },
            },
            sim.library.length ? `Draw for turn ${sim.turn + 1}` : "Deck empty",
          ),
      choosing
        ? h("button", { class: "quiet-button", type: "button", on: { click: keepHand } }, "Keep")
        : null,
      h(
        "button",
        { class: "quiet-button", type: "button", on: { click: () => deal(handSize) } },
        "New hand",
      ),
      h("button", { class: "quiet-button", type: "button", on: { click: reset } }, "Clear"),
    ),
  );
}

function oddsRow(row: CardOdds): HTMLElement {
  return h(
    "tr",
    {},
    h("th", { scope: "row" }, `${row.copies}× ${row.name}`),
    h("td", {}, pct(row.opening)),
    h("td", {}, pct(row.afterMulligan)),
    h("td", {}, pct(row.byTurnThree)),
  );
}

function oddsTable(odds: OpeningOdds): HTMLElement | null {
  if (!odds.cards.length) return null;
  return h(
    "div",
    { class: "sim-odds" },
    h(
      "table",
      { class: "odds-table" },
      h(
        "thead",
        {},
        h(
          "tr",
          {},
          h("th", { scope: "col" }, "Card"),
          h("th", { scope: "col", title: "At least one copy in the opening hand" }, "Opening"),
          h(
            "th",
            {
              scope: "col",
              title:
                "At least one copy after a mulligan that never bottoms a copy of it — "
                + "this assumes you are digging for the card",
            },
            "After mull",
          ),
          h("th", { scope: "col", title: "At least one copy by the start of turn 3" }, "By T3"),
        ),
      ),
      h("tbody", {}, ...odds.cards.map(oddsRow)),
    ),
  );
}

function headline(odds: OpeningOdds): HTMLElement {
  const chips: HTMLElement[] = [];
  for (const entry of odds.playableByCost) {
    const [cost, chance] = entry;
    if (cost === undefined || chance === undefined) continue;
    chips.push(
      h(
        "span",
        {
          class: "sim-chip",
          title: `Odds of opening with at least one card costing ${cost} or less`,
        },
        h("b", {}, pct(chance)),
        h("i", {}, `≤${cost} drop`),
      ),
    );
  }
  if (odds.champion) {
    chips.push(
      h(
        "span",
        { class: "sim-chip", title: "Odds of opening with your chosen champion" },
        h("b", {}, pct(odds.champion.opening)),
        h("i", {}, "champion"),
      ),
    );
  }
  return h("div", { class: "sim-chips" }, ...chips);
}

export function renderOpeningHand(target: HTMLElement): void {
  root = target;
  const odds = store.state.opening;

  if (!odds || !odds.available) {
    // Two different absences. A format that records no hand size cannot be simulated at
    // all and says so; an incomplete deck simply has nothing to deal yet.
    const noRules = Boolean(odds && odds.rules.handSize === 0);
    replace(
      target,
      h(
        "section",
        { class: "sim-panel" },
        h("header", { class: "suggest-head" }, h("h3", {}, "Opening hand")),
        h(
          "p",
          { class: "muted small" },
          noRules
            ? "This format does not record an opening hand size, so there is nothing to "
              + "simulate. Constructed does."
            : "Add cards to the main deck and the opening-hand odds appear here.",
        ),
      ),
    );
    return;
  }

  replace(
    target,
    h(
      "section",
      { class: "sim-panel" },
      h(
        "header",
        { class: "suggest-head" },
        h("h3", {}, "Opening hand"),
        h(
          "p",
          {},
          `${odds.rules.handSize} cards from ${odds.deckSize}, mulligan up to `
            + `${odds.rules.mulliganMax} to the ${odds.rules.mulliganDestination}. `
            + "Percentages are exact; the hands are dealt.",
        ),
      ),
      headline(odds),
      simulator(odds),
      oddsTable(odds),
      // The values these numbers depend on were corroborated from published rules
      // guides, not read off the rulebook the format profile cites. Saying so is the
      // same discipline the derived ban-era boundary gets, and for the same reason: a
      // derived value must not pass as a cited one by being quietly presented as fact.
      odds.rules.cited
        ? null
        : h(
            "p",
            { class: "sim-caveat muted small" },
            "Opening-hand and mulligan rules here are derived from published rules "
              + "guides rather than read off the official Core Rules document, which is "
              + "not bundled with this app. Check them against your event's rules.",
          ),
    ),
  );
}
