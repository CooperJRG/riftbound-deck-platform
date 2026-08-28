/**
 * The deck itself, plus legality and coverage.
 *
 * Legality and coverage are shown as two separate readouts, because they are two
 * different problems: "this deck breaks a rule" and "this deck is legal but you're
 * missing four cards" need different responses from the player.
 */

import type {
  CardSuggestion,
  ChampionOption,
  Issue,
  Validation,
  Zone,
} from "../api/types";
import {
  adjustCard,
  applySuggestedRunes,
  setBuilderReview,
  setChampion,
  setDeckName,
  setLegend,
  toggleDrawer,
} from "../state/actions";
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

function runeZone(
  counts: Record<string, number>,
  total: number,
  target: number,
  canSuggest: boolean,
): HTMLElement {
  const zone = matZone("Runes", "runes", counts, total, target);
  if (canSuggest) {
    zone.querySelector(".mat-zone-head")?.appendChild(
      h(
        "button",
        {
          class: "quiet-button rune-auto",
          type: "button",
          title: "Fill the rune base from this deck's power costs",
          on: { click: applySuggestedRunes },
        },
        total ? "Redo runes" : "Fill runes",
      ),
    );
  }
  return zone;
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

/**
 * The champions this legend may nominate, with how the field has fared on each.
 *
 * Shown as the next step rather than as a hint, because it is one: the nomination is
 * required, the menu is short -- a median of two per legend -- and until it is made the
 * deck cannot be legal. The score is presence and win rate together, normalised so the
 * strongest reads 100.
 */
function championChooser(options: ChampionOption[]): HTMLElement | null {
  if (!options.length) return null;
  return h(
    "section",
    { class: "suggest suggest-champions" },
    h(
      "header",
      { class: "suggest-head" },
      h("h3", {}, "Pick a champion"),
      h("p", {}, "Required, and it decides which cards the rest of the deck can use."),
    ),
    h(
      "div",
      { class: "suggest-row" },
      ...options.map((option) =>
        h(
          "button",
          {
            class: "suggest-card",
            type: "button",
            title: option.summary,
            on: { click: () => setChampion(option.cardId) },
          },
          option.imageUrl
            ? h("img", { src: option.imageUrl, alt: option.name, loading: "lazy" })
            : h("span", { class: "mat-card-blank" }, option.name),
          h("span", { class: "suggest-score" }, String(Math.round(option.score))),
          h("span", { class: "suggest-name" }, option.name),
          h("span", { class: "suggest-why" }, option.summary),
        ),
      ),
    ),
  );
}

/**
 * A shortlist of cards to add, at the foot of the deck.
 *
 * The search box is still there and still the way to find a particular card. This is
 * for the other case: knowing roughly what the deck wants and not which card that is.
 * Five at a time, each with the reason it is on the list -- a suggestion that cannot say
 * why it is there is a slot machine.
 */
function suggestionStrip(
  title: string,
  note: string,
  rows: CardSuggestion[],
  zone: Zone,
): HTMLElement | null {
  if (!rows.length) return null;
  return h(
    "section",
    { class: "suggest" },
    h("header", { class: "suggest-head" }, h("h3", {}, title), h("p", {}, note)),
    h(
      "div",
      { class: "suggest-row" },
      ...rows.map((row) =>
        h(
          "button",
          {
            class: "suggest-card",
            type: "button",
            title: `Add ${row.copies}x ${row.name}`,
            on: { click: () => adjustCard(row.cardId, zone, row.copies) },
          },
          row.imageUrl
            ? h("img", { src: row.imageUrl, alt: row.name, loading: "lazy" })
            : h("span", { class: "mat-card-blank" }, row.name),
          row.copies > 1
            ? h("span", { class: "suggest-copies" }, `+${row.copies}`)
            : null,
          h("span", { class: "suggest-name" }, row.name),
          h("span", { class: "suggest-why" }, row.reason),
        ),
      ),
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
  const { deck, validation, builderReview, suggestions } = store.state;
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
    // The way back to the drawer once it is closed. It lives on the deck because that
    // is the only thing on screen at that point.
    store.state.drawerOpen
      ? null
      : h(
          "button",
          {
            class: "quiet-button",
            type: "button",
            on: { click: toggleDrawer },
          },
          "Find cards",
        ),
    validation
      ? h("span", { class: `legal-badge${validation.legal ? " is-legal" : ""}` },
          validation.legal ? "Ready to play" : builderReview ? "Needs attention" : `${completedSteps} / 5 ready`)
      : null,
  );

  if (!hasStarted) {
    replace(
      root,
      header,
      // A wall of legends rather than an instruction to go and find one. The legend is
      // the first decision and the one every other decision hangs off, so it is worth
      // the whole screen -- and it is a decision made by looking, not by reading.
      h(
        "section",
        { class: "builder-onboarding" },
        h("h2", {}, "Start with a legend."),
        h(
          "p",
          {},
          "It decides which domains the deck may play, which champions it may nominate, "
            + "and what the card drawer will offer you.",
        ),
        store.state.smartLegends.length
          ? h(
              "div",
              { class: "legend-wall" },
              ...store.state.smartLegends.map((legend) =>
                h(
                  "button",
                  {
                    class: "legend-pick",
                    type: "button",
                    title: `Build with ${legend.name}`,
                    on: { click: () => setLegend(legend.legendId) },
                  },
                  legend.imageUrl
                    ? h("img", { src: legend.imageUrl, alt: legend.name, loading: "lazy" })
                    : h("span", { class: "mat-card-blank" }, legend.name),
                  h("span", { class: "legend-pick-name" }, legend.name),
                  h(
                    "span",
                    { class: "legend-pick-meta" },
                    legend.domains.join(" / "),
                  ),
                ),
              ),
            )
          : h("p", { class: "muted small" }, "Loading legends..."),
      ),
    );
    return;
  }

  const champCandidates = Object.keys(deck.main).filter((id) => {
    const row = store.state.deckCards.get(id);
    return row?.card.superType === "Champion";
  });

  // The field's champions for this legend, with how it has fared on each. Falls back to
  // whatever champions are already in the main deck when there is no meta data -- the
  // builder has to work with none at all.
  const chooseChampion = deck.championId
    ? null
    : championChooser(suggestions?.champions ?? [])
      ?? (champCandidates.length
        ? h("div", { class: "hint-box" },
            h("span", {}, "Choose your champion: "),
            ...champCandidates.map((id) =>
              h("button", { class: "pill", type: "button",
                on: { click: () => setChampion(id) } }, cardName(id))))
        : null);

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
    runeZone(deck.runes, validation?.runeTotal ?? 0, 12, Boolean(suggestions?.runes)),
    battlefieldRow(deck.battlefields, 3),
  );

  replace(
    root,
    header,
    setup,
    chooseChampion,
    matZone("Main deck", "main", deck.main, validation?.mainTotal ?? 0, 40, deck.championId),
    // A shortlist under the deck, the way a playlist offers more of what is already in
    // it. The search box is still the way to find a particular card; this is for
    // knowing what the deck wants without knowing which card that is.
    suggestionStrip(
      "Add to this deck",
      "What the field plays alongside the cards you already have.",
      suggestions?.main ?? [],
      "main",
    ),
    // Always present, empty or not. The sideboard is part of a legal list and a zone
    // that only appears once it is non-empty is a zone nobody discovers.
    matZone("Sideboard", "sideboard", deck.sideboard, validation?.sideboardTotal ?? 0, null),
    deck.battlefields.length < 3
      ? suggestionStrip(
          "Battlefields to consider",
          "Played with this legend and these cards.",
          suggestions?.battlefields ?? [],
          "battlefields",
        )
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
