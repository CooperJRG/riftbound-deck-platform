/**
 * The deck itself, plus legality and coverage.
 *
 * Legality and coverage are shown as two separate readouts, because they are two
 * different problems: "this deck breaks a rule" and "this deck is legal but you're
 * missing four cards" need different responses from the player.
 */

import type { Issue, Validation, Zone } from "../api/types";
import { adjustCard, setBuilderReview, setChampion, setDeckName, setLegend } from "../state/actions";
import { store } from "../state/store";
import { h, replace } from "../ui/dom";

function cardName(cardId: string): string {
  return store.state.deckCards.get(cardId)?.card.name ?? cardId;
}

function isPenalised(cardId: string): boolean {
  const row = store.state.deckCards.get(cardId);
  return row !== undefined && row.weight < 1;
}

/** Sorted the way a player reads a list: up the curve, then alphabetically. */
function byCurve(a: string, b: string): number {
  const left = store.state.deckCards.get(a)?.card;
  const right = store.state.deckCards.get(b)?.card;
  const lc = left?.cost ?? 99;
  const rc = right?.cost ?? 99;
  if (lc !== rc) return lc - rc;
  return (left?.name ?? a).localeCompare(right?.name ?? b);
}

/**
 * One card on the mat.
 *
 * The art is the card. A list of names is a spreadsheet of a deck, and the thing a
 * player actually recognises -- at a glance, across a table -- is the picture. Count and
 * cost ride on top of it rather than beside it, so forty cards still read as one object.
 */
function boardCard(
  cardId: string,
  qty: number,
  zone: Zone,
  opts: { landscape?: boolean; champion?: boolean } = {},
): HTMLElement {
  const row = store.state.deckCards.get(cardId);
  const card = row?.card;
  const name = card?.name ?? cardId;
  const art = card?.imageUrl;
  return h(
    "figure",
    {
      class: `mat-card${opts.landscape ? " is-wide" : ""}`
        + `${isPenalised(cardId) ? " is-dim" : ""}`
        + `${opts.champion ? " is-champion" : ""}`,
      title: name,
    },
    art
      ? h("img", { src: art, alt: name, loading: "lazy" })
      : h("span", { class: "mat-card-blank" }, name),
    card?.cost !== null && card?.cost !== undefined
      ? h("span", { class: "mat-cost" }, String(card.cost))
      : null,
    qty > 1 ? h("span", { class: "mat-qty" }, `${qty}`) : null,
    opts.champion ? h("span", { class: "mat-flag" }, "Champion") : null,
    h(
      "figcaption",
      {},
      h("span", { class: "mat-name" }, name),
      h(
        "span",
        { class: "mat-steps" },
        h("button", {
          class: "step", type: "button", aria: { label: `Remove one ${name}` },
          on: { click: () => adjustCard(cardId, zone, -1) },
        }, "−"),
        h("button", {
          class: "step", type: "button", aria: { label: `Add one ${name}` },
          on: { click: () => adjustCard(cardId, zone, 1) },
        }, "+"),
      ),
    ),
  );
}

/** An unfilled slot, so the shape of a legal deck is visible before it is finished. */
function ghost(label: string, landscape = false): HTMLElement {
  return h(
    "div",
    { class: `mat-card mat-ghost${landscape ? " is-wide" : ""}` },
    h("span", {}, label),
  );
}

function zoneHead(title: string, total: number, target: number | null): HTMLElement {
  const ok = target === null || total === target;
  return h(
    "header",
    { class: "mat-zone-head" },
    h("h3", {}, title),
    h(
      "span",
      { class: `mat-tally${ok ? " is-ok" : ""}` },
      target === null ? String(total) : `${total}/${target}`,
    ),
  );
}

function matZone(
  title: string,
  zone: Zone,
  counts: Record<string, number>,
  total: number,
  target: number | null,
  championId = "",
): HTMLElement {
  const ids = Object.keys(counts).sort(byCurve);
  return h(
    "section",
    { class: `mat-zone mat-zone-${zone}` },
    zoneHead(title, total, target),
    ids.length === 0
      ? h("div", { class: "mat-grid" }, ghost("Nothing here yet"))
      : h(
          "div",
          { class: "mat-grid" },
          ...ids.map((id) =>
            boardCard(id, counts[id] ?? 0, zone, { champion: id === championId }),
          ),
        ),
  );
}

/**
 * The three battlefields, shown as three slots whatever is in them.
 *
 * The format asks for exactly three and they must be different, so the empty ones are
 * as informative as the full ones -- a row with a gap in it says what a "0 / 3" counter
 * has to be read to learn. Landscape, because that is how they are printed and how they
 * sit on the table between the players.
 */
function battlefieldRow(ids: string[], target: number): HTMLElement {
  const slots: HTMLElement[] = ids.map((id) =>
    boardCard(id, 1, "battlefields", { landscape: true }),
  );
  while (slots.length < target) slots.push(ghost("Battlefield", true));
  return h(
    "section",
    { class: "mat-zone mat-zone-battlefields" },
    zoneHead("Battlefields", ids.length, target),
    h("div", { class: "mat-row mat-row-wide" }, ...slots),
  );
}

/** Legend and champion: the two cards that decide what the rest of the deck may be. */
function identityRow(legendId: string, championId: string): HTMLElement {
  return h(
    "section",
    { class: "mat-zone mat-zone-identity" },
    zoneHead("Legend & champion", Number(Boolean(legendId)) + Number(Boolean(championId)), 2),
    h(
      "div",
      { class: "mat-row mat-identity" },
      legendId
        ? h(
            "div",
            { class: "mat-slot" },
            boardCard(legendId, 1, "main"),
            h("button", {
              class: "quiet-button", type: "button",
              on: { click: () => setLegend("") },
            }, "Change legend"),
          )
        : h("div", { class: "mat-slot" }, ghost("Legend"),
            h("span", { class: "muted small" }, "Start here")),
      championId
        ? h(
            "div",
            { class: "mat-slot" },
            boardCard(championId, 1, "main", { champion: true }),
            h("button", {
              class: "quiet-button", type: "button",
              on: { click: () => setChampion("") },
            }, "Change champion"),
          )
        : h("div", { class: "mat-slot" }, ghost("Champion"),
            h("span", { class: "muted small" }, "One from your main deck")),
    ),
  );
}

function issueItem(issue: Issue): HTMLElement {
  return h(
    "li",
    { class: `issue issue-${issue.severity}` },
    h("span", { class: "issue-msg" }, issue.message),
    issue.ruleRefs.length > 0
      ? h("span", { class: "issue-refs", title: "Rulebook reference" },
          issue.ruleRefs.join(", "))
      : null,
  );
}

function coveragePanel(validation: Validation): HTMLElement | null {
  const { coverage } = validation;
  if (coverage.complete) {
    return h("p", { class: "coverage is-ok" }, "You can field every card in this deck.");
  }
  const short = coverage.missing.reduce((sum, m) => sum + m.copies, 0);
  return h(
    "div",
    { class: "coverage is-short" },
    h("p", { class: "coverage-head" },
      `${short} card${short === 1 ? "" : "s"} you may not have:`),
    h("ul", { class: "coverage-list" },
      ...coverage.missing.map((m) =>
        h("li", {},
          `${m.copies}× ${m.name || cardName(m.cardId)}`,
          m.reason === "unknown-card"
            ? h("span", { class: "issue-refs" }, "not in current card data")
            : null))),
  );
}

/**
 * The deck-name input is kept across renders.
 *
 * Typing a name updates the deck, which re-renders this panel; re-creating the input
 * each time would blur it after the first character. Its value is written back only
 * when the field is not focused, so a deck loaded from the library still updates it.
 */
let nameInput: HTMLInputElement | null = null;

function deckNameInput(name: string): HTMLInputElement {
  if (nameInput === null) {
    nameInput = h("input", {
      class: "deck-name",
      aria: { label: "Deck name" },
      on: { input: (e) => setDeckName((e.target as HTMLInputElement).value) },
    });
  }
  if (document.activeElement !== nameInput) nameInput.value = name;
  return nameInput;
}

export function renderDeckPanel(root: HTMLElement): void {
  const { deck, validation, builderReview } = store.state;
  const hasStarted = Boolean(
    deck.legendId || deck.championId || Object.keys(deck.main).length ||
      Object.keys(deck.runes).length || deck.battlefields.length || Object.keys(deck.sideboard).length,
  );
  const completedSteps = validation
    ? Number(Boolean(deck.legendId)) + Number(Boolean(deck.championId)) +
      Number(validation.mainTotal === 40) + Number(validation.runeTotal === 12) +
      Number(validation.battlefieldCount === 3)
    : 0;

  const header = h(
    "div",
    { class: "deck-header" },
    deckNameInput(deck.name),
    validation
      ? h("span", { class: `legal-badge${validation.legal ? " is-legal" : ""}` },
          validation.legal ? "Ready to play" : builderReview ? "Needs attention" : `${completedSteps} / 5 ready`)
      : null,
  );

  if (!hasStarted) {
    replace(
      root,
      header,
      h(
        "section",
        { class: "builder-onboarding" },
        h("span", { class: "onboarding-number" }, "01"),
        h("h2", {}, "Start with a legend."),
        h("p", {}, "Use the card search to choose a legend. Bound Atlas will keep the deck requirements in view as your list takes shape."),
        h("ol", {}, h("li", {}, "Choose a legend"), h("li", {}, "Add a champion and main deck"), h("li", {}, "Finish runes and battlefields"), h("li", {}, "Review before you play")),
      ),
    );
    return;
  }

  const champCandidates = Object.keys(deck.main).filter((id) => {
    const row = store.state.deckCards.get(id);
    return row?.card.superType === "Champion";
  });

  const chooseChampion =
    !deck.championId && champCandidates.length > 0
      ? h("div", { class: "hint-box" },
          h("span", {}, "Choose your champion: "),
          ...champCandidates.map((id) =>
            h("button", { class: "pill", type: "button",
              on: { click: () => setChampion(id) } }, cardName(id))))
      : null;

  // Notices are legal-but-worth-knowing, so they sit apart from real problems.
  // Mixing them in would teach players to ignore the legality list.
  const problems = (validation?.issues ?? []).filter((i) => i.severity !== "notice");
  const notices = (validation?.issues ?? []).filter((i) => i.severity === "notice");

  const issues = builderReview && problems.length > 0
    ? h("section", { class: "issues" },
        h("h3", { class: "zone-title" }, "Legality"),
        h("ul", { class: "issue-list" }, ...problems.map(issueItem)))
    : null;

  const beforeYouPlay = builderReview && notices.length > 0
    ? h("section", { class: "issues" },
        h("h3", { class: "zone-title" }, "Before you play"),
        h("ul", { class: "issue-list" }, ...notices.map(issueItem)))
    : null;

  // Laid out the way the deck is laid out on a table: what defines it, then the board
  // it is played on, then the resources, then the deck itself. A player who knows the
  // game can find any zone without reading a heading.
  // Everything that is not the main deck sits in one band across the top: the legend and
  // champion, the runes, the three battlefields. Eight cards between them, and stacking
  // them put the forty-card deck -- the part being worked on -- below the fold.
  const setup = h(
    "div",
    { class: "mat-setup" },
    identityRow(deck.legendId, deck.championId),
    matZone("Runes", "runes", deck.runes, validation?.runeTotal ?? 0, 12),
    battlefieldRow(deck.battlefields, 3),
  );

  replace(
    root,
    header,
    setup,
    chooseChampion,
    matZone("Main deck", "main", deck.main, validation?.mainTotal ?? 0, 40, deck.championId),
    Object.keys(deck.sideboard).length
      ? matZone("Sideboard", "sideboard", deck.sideboard, validation?.sideboardTotal ?? 0, null)
      : null,
    h(
      "section",
      { class: "review-callout" },
      h("div", {}, h("strong", {}, builderReview ? "Reviewing your list" : "Ready for a rules check?"), h("span", {}, builderReview ? "Fix the items below, then review again." : "Build freely; detailed rules stay out of the way until you ask.")),
      h("button", { type: "button", class: builderReview ? "quiet-button" : "primary", on: { click: () => setBuilderReview(!builderReview) } }, builderReview ? "Hide review" : "Review deck"),
    ),
    validation && validation.coverage.totalCopies > 0 && builderReview ? coveragePanel(validation) : null,
    issues,
    beforeYouPlay,
  );
}
