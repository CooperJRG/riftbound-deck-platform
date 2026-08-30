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
import { openCardPreview } from "./cardPreview";

/**
 * The playmat is the default overview; the forty-card wall is an intentional detail
 * view. These are presentation choices, not deck data, so they stay local instead of
 * being persisted with the list or triggering API work when toggled.
 */
let renderedRoot: HTMLElement | null = null;
let deckExpanded = false;
let mainSuggestionsVisible = true;
let sideboardSuggestionsVisible = true;

function repaintDeck(): void {
  if (renderedRoot) renderDeckPanel(renderedRoot);
}

function setDeckExpanded(expanded: boolean, focus = ""): void {
  deckExpanded = expanded;
  repaintDeck();
  if (!focus) return;
  requestAnimationFrame(() => {
    document.querySelector<HTMLElement>(focus)?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  });
}

function openCardFinder(): void {
  if (!store.state.drawerOpen) toggleDrawer();
  requestAnimationFrame(() => {
    document.querySelector<HTMLInputElement>("#browser input[type='search']")?.focus();
  });
}

function cardName(cardId: string): string {
  return store.state.deckCards.get(cardId)?.card.name ?? cardId;
}

function isPenalised(cardId: string): boolean {
  const row = store.state.deckCards.get(cardId);
  return row !== undefined && row.weight < 1;
}

/**
 * Four VEN battlefields are supplied as portrait files whose card face is turned on
 * its side; the rest of the battlefield catalog is already landscape. Marking the
 * exceptional files after they load lets CSS turn only those cards, instead of
 * forcing one orientation onto two different source shapes.
 */
function markPortraitBattlefield(image: HTMLImageElement): void {
  if (!image.naturalWidth || !image.naturalHeight) return;
  image.classList.toggle("is-portrait-source", image.naturalHeight > image.naturalWidth);
}

function battlefieldImage(src: string, name: string): HTMLImageElement {
  const image = h("img", {
    src,
    alt: name,
    loading: "lazy",
    on: {
      load: (event) => markPortraitBattlefield(event.currentTarget as HTMLImageElement),
    },
  });
  // A cached image can be complete before the listener is attached.
  if (image.complete) queueMicrotask(() => markPortraitBattlefield(image));
  return image;
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
  zone: Zone | null,
  opts: { landscape?: boolean; champion?: boolean; identity?: boolean } = {},
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
        + `${opts.champion ? " is-champion" : ""}`
        + `${opts.identity ? " is-identity-card" : ""}`,
      title: name,
    },
    h(
      "button",
      {
        class: "mat-card-open",
        type: "button",
        aria: { label: `Open ${name} card detail` },
        on: { click: () => openCardPreview(cardId, zone) },
      },
      art
        ? opts.landscape
          ? battlefieldImage(art, name)
          : h("img", { src: art, alt: name, loading: "lazy" })
        : h("span", { class: "mat-card-blank" }, name),
    ),
    card?.cost !== null && card?.cost !== undefined
      ? h("span", { class: "mat-cost" }, String(card.cost))
      : null,
    qty > 1 ? h("span", { class: "mat-qty" }, `${qty}`) : null,
    opts.champion ? h("span", { class: "mat-flag" }, "Champion") : null,
    h(
      "figcaption",
      {},
      h("span", { class: "mat-name" }, name),
      zone
        ? h(
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
          )
        : h("span", { class: "mat-read" }, "Read card"),
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
  const cards: HTMLElement[] = [];
  const ids = Object.keys(counts).sort(byCurve);
  for (const id of ids) {
    for (let copy = 0; copy < (counts[id] ?? 0); copy += 1) {
      cards.push(boardCard(id, 1, "runes"));
    }
  }
  const middle = (cards.length - 1) / 2;
  cards.forEach((card, index) => {
    const distance = index - middle;
    card.classList.add("rune-card");
    card.style.setProperty("--rune-tilt", `${distance * 0.82}deg`);
    card.style.setProperty("--rune-lift", `${Math.abs(distance) * 1.15}px`);
  });

  const head = zoneHead("Runes", total, target);
  if (canSuggest) {
    head.appendChild(
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
  return h(
    "section",
    { class: "mat-zone mat-zone-runes" },
    head,
    cards.length
      ? h("div", { class: "mat-grid rune-fan" }, ...cards)
      : h("div", { class: "mat-grid rune-fan is-empty" }, ghost("Nothing here yet")),
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
function suggestedBattlefield(row: CardSuggestion): HTMLElement {
  return h(
    "article",
    {
      class: "mat-card is-wide battlefield-pick",
      title: `Add ${row.name}: ${row.reason}`,
    },
    h(
      "button",
      {
        class: "battlefield-read",
        type: "button",
        aria: { label: `Read suggested battlefield ${row.name}` },
        on: { click: () => openCardPreview(row.cardId, "battlefields") },
      },
      h(
        "span",
        { class: "battlefield-art" },
        row.imageUrl
          ? battlefieldImage(row.imageUrl, row.name)
          : h("span", { class: "mat-card-blank" }, row.name),
      ),
      h("span", { class: "battlefield-read-label" }, "Read"),
    ),
    h(
      "button",
      {
        class: "battlefield-add",
        type: "button",
        aria: { label: `Add suggested battlefield ${row.name}` },
        on: { click: () => adjustCard(row.cardId, "battlefields", 1) },
      },
      "+ Add",
    ),
    h("span", { class: "battlefield-pick-name" }, row.name),
  );
}

function battlefieldRow(
  ids: string[],
  target: number,
  suggestions: CardSuggestion[] = [],
): HTMLElement {
  const slots: HTMLElement[] = ids.map((id) =>
    boardCard(id, 1, "battlefields", { landscape: true }),
  );
  for (const row of suggestions) {
    if (slots.length >= target) break;
    slots.push(suggestedBattlefield(row));
  }
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
            h("span", { class: "playmat-slot-label" }, "Legend"),
            boardCard(legendId, 1, null, { identity: true }),
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
            h("span", { class: "playmat-slot-label" }, "Champion"),
            boardCard(championId, 1, null, { champion: true, identity: true }),
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
          "article",
          {
            class: "suggest-card",
            title: option.summary,
          },
          h(
            "button",
            {
              class: "suggest-card-preview",
              type: "button",
              aria: { label: `Read ${option.name}` },
              on: { click: () => openCardPreview(option.cardId) },
            },
            option.imageUrl
              ? h("img", { src: option.imageUrl, alt: option.name, loading: "lazy" })
              : h("span", { class: "mat-card-blank" }, option.name),
          ),
          h("span", { class: "suggest-score" }, String(Math.round(option.score))),
          h("span", { class: "suggest-name" }, option.name),
          h("span", { class: "suggest-why" }, option.summary),
          h(
            "span",
            { class: "suggest-card-actions" },
            h("button", {
              class: "suggest-read", type: "button",
              on: { click: () => openCardPreview(option.cardId) },
            }, "Read"),
            h("button", {
              class: "suggest-add", type: "button",
              on: { click: () => setChampion(option.cardId) },
            }, "Choose"),
          ),
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
  visible: boolean,
  onToggle: () => void,
): HTMLElement | null {
  if (!rows.length) return null;
  return h(
    "section",
    { class: `suggest suggest-${zone}${visible ? "" : " is-collapsed"}` },
    h(
      "header",
      { class: "suggest-head" },
      h("div", {}, h("h3", {}, title), h("p", {}, note)),
      h(
        "button",
        {
          class: "quiet-button suggest-toggle",
          type: "button",
          aria: { expanded: String(visible) },
          on: { click: onToggle },
        },
        visible ? "Hide suggestions" : "Show suggestions",
      ),
    ),
    visible
      ? h(
          "div",
          { class: "suggest-row" },
          ...rows.map((row) =>
            h(
              "article",
              {
                class: "suggest-card",
                title: `Add ${row.copies}x ${row.name} to ${zone === "sideboard" ? "the sideboard" : "the main deck"}`,
              },
              h(
                "button",
                {
                  class: "suggest-card-preview",
                  type: "button",
                  aria: { label: `Read ${row.name}` },
                  on: { click: () => openCardPreview(row.cardId, zone) },
                },
                row.imageUrl
                  ? h("img", { src: row.imageUrl, alt: row.name, loading: "lazy" })
                  : h("span", { class: "mat-card-blank" }, row.name),
              ),
              row.copies > 1
                ? h("span", { class: "suggest-copies" }, `+${row.copies}`)
                : null,
              h("span", { class: "suggest-name" }, row.name),
              h("span", { class: "suggest-why" }, row.reason),
              h(
                "span",
                { class: "suggest-card-actions" },
                h("button", {
                  class: "suggest-read", type: "button",
                  on: { click: () => openCardPreview(row.cardId, zone) },
                }, "Read"),
                h("button", {
                  class: "suggest-add", type: "button",
                  on: { click: () => adjustCard(row.cardId, zone, row.copies) },
                }, `Add +${row.copies}`),
              ),
            ),
          ),
        )
      : null,
  );
}

/** A handful of visible faces turn an abstract count into a deck sitting on the mat. */
function cardStack(ids: string[], limit: number): HTMLElement {
  const shown = ids.filter((id) => store.state.deckCards.get(id)?.card.imageUrl).slice(0, limit);
  return h(
    "span",
    { class: "deck-stack-cards", aria: { hidden: "true" } },
    ...shown.map((id, index) => {
      const card = store.state.deckCards.get(id)?.card;
      return h(
        "span",
        {
          class: "deck-stack-card",
          style: `--stack-i:${index};--stack-n:${shown.length}`,
        },
        card?.imageUrl ? h("img", { src: card.imageUrl, alt: "", loading: "lazy" }) : null,
      );
    }),
  );
}

/** The curve remains useful even while the full deck is folded away. */
function costCurve(counts: Record<string, number>): HTMLElement {
  const buckets = Array.from({ length: 8 }, () => 0);
  for (const [cardId, copies] of Object.entries(counts)) {
    const cost = store.state.deckCards.get(cardId)?.card.cost ?? 8;
    const index = Math.min(7, Math.max(0, cost - 1));
    buckets[index] = (buckets[index] ?? 0) + copies;
  }
  const tallest = Math.max(1, ...buckets);
  return h(
    "span",
    { class: "deck-curve", aria: { label: "Deck cost curve" } },
    ...buckets.map((copies, index) =>
      h(
        "span",
        { class: "deck-curve-step", title: `${index === 7 ? "8+" : index + 1} cost: ${copies}` },
        h("i", { style: `--curve:${copies / tallest}` }),
        h("b", {}, index === 7 ? "8+" : String(index + 1)),
      ),
    ),
  );
}

function starterSuggestions(rows: CardSuggestion[]): HTMLElement | null {
  const shown = rows.slice(0, 4);
  if (!shown.length) return null;
  return h(
    "div",
    { class: "starter-suggestions" },
    h(
      "div",
      { class: "starter-suggestion-copy" },
      h("span", { class: "eyebrow" }, "A proven opening"),
      h("strong", {}, "Start with suggestions"),
      h("span", {}, "Cards repeatedly played beside this legend, ready to add."),
      h(
        "button",
        {
          class: "quiet-button starter-suggestion-all",
          type: "button",
          on: { click: () => setDeckExpanded(true, "#deck-workbench") },
        },
        "See every suggestion",
      ),
    ),
    h(
      "div",
      { class: "starter-card-fan" },
      ...shown.map((row, index) =>
        h(
          "article",
          {
            class: "starter-suggest-card",
            title: `Add ${row.copies}x ${row.name}: ${row.reason}`,
            style: `--starter-i:${index};--starter-n:${shown.length}`,
          },
          h(
            "button",
            {
              class: "starter-suggest-preview",
              type: "button",
              aria: { label: `Read suggested card ${row.name}` },
              on: { click: () => openCardPreview(row.cardId, "main") },
            },
            row.imageUrl
              ? h("img", { src: row.imageUrl, alt: row.name, loading: "lazy" })
              : h("span", { class: "mat-card-blank" }, row.name),
            h("span", { class: "starter-suggest-read" }, "Read"),
          ),
          h(
            "button",
            {
              class: "starter-suggest-add",
              type: "button",
              aria: { label: `Add ${row.copies} copies of ${row.name} to the main deck` },
              on: { click: () => adjustCard(row.cardId, "main", row.copies) },
            },
            `+${row.copies}`,
          ),
        ),
      ),
    ),
  );
}

function mainDeckSpot(
  counts: Record<string, number>,
  total: number,
  suggestions: CardSuggestion[] = [],
): HTMLElement {
  const ids = Object.keys(counts).sort(byCurve);
  const empty = ids.length === 0;
  const suggestedStart = empty ? starterSuggestions(suggestions) : null;
  return h(
    "section",
    { class: `playmat-zone playmat-main${empty ? " is-empty" : ""}` },
    zoneHead("Main deck", total, 40),
    suggestedStart
      ?? h(
        "button",
        {
          class: `deck-zone-button${empty ? " is-empty" : ""}`,
          type: "button",
          aria: {
            expanded: String(deckExpanded),
            controls: "deck-workbench",
            label: empty ? "Find cards for the empty main deck" : "Expand the full main deck",
          },
          on: {
            click: () => empty
              ? openCardFinder()
              : setDeckExpanded(!deckExpanded, !deckExpanded ? "#deck-workbench" : ".playmat"),
          },
        },
        empty
          ? h(
              "span",
              { class: "deck-zone-empty" },
              h("b", {}, "+"),
              h("strong", {}, "No recommendations yet"),
              h("span", {}, "Open the card drawer while the field data catches up."),
            )
          : cardStack(ids, 6),
        empty
          ? null
          : h(
              "span",
              { class: "deck-zone-copy" },
              h("strong", {}, `${total} cards · ${ids.length} unique`),
              h("span", {}, deckExpanded ? "Fold the deck away" : "Open the full deck and suggestions"),
            ),
        empty ? null : costCurve(counts),
      ),
  );
}

function sideboardSpot(
  counts: Record<string, number>,
  total: number,
  target: number | null,
  hasSuggestions: boolean,
): HTMLElement {
  const ids = Object.keys(counts).sort(byCurve);
  return h(
    "section",
    { class: "playmat-zone playmat-sideboard" },
    zoneHead("Sideboard", total, target),
    h(
      "button",
      {
        class: `sideboard-zone-button${ids.length ? "" : " is-empty"}`,
        type: "button",
        aria: { expanded: String(deckExpanded), controls: "deck-workbench" },
        on: { click: () => setDeckExpanded(true, "#sideboard-workbench") },
      },
      ids.length
        ? cardStack(ids, 5)
        : h("span", { class: "sideboard-empty-mark", aria: { hidden: "true" } }, "SB"),
      h(
        "span",
        { class: "sideboard-zone-copy" },
        h("strong", {}, ids.length ? `${total} cards ready` : "Plan for game two"),
        h("span", {}, ids.length
          ? "Open and tune the sideboard"
          : hasSuggestions ? "See tournament sideboard suggestions" : "Open the sideboard workspace"),
      ),
    ),
  );
}

function deckWorkbench(
  mainTarget: number,
  sideboardTarget: number | null,
  championId: string,
  suggestions: { main: CardSuggestion[]; sideboard: CardSuggestion[] },
): HTMLElement {
  const { deck, validation } = store.state;
  const mainSuggestions = suggestionStrip(
    "Cards that fit this build",
    "Drawn from what comparable lists play alongside your current cards.",
    suggestions.main,
    "main",
    mainSuggestionsVisible,
    () => {
      mainSuggestionsVisible = !mainSuggestionsVisible;
      repaintDeck();
    },
  );
  const sideboardSuggestions = suggestionStrip(
    "Sideboard answers",
    "Cards comparable published lists actually held in reserve.",
    suggestions.sideboard,
    "sideboard",
    sideboardSuggestionsVisible,
    () => {
      sideboardSuggestionsVisible = !sideboardSuggestionsVisible;
      repaintDeck();
    },
  );
  return h(
    "section",
    { class: "deck-workbench", id: "deck-workbench" },
    h(
      "header",
      { class: "workbench-head" },
      h(
        "div",
        {},
        h("p", { class: "eyebrow" }, "Deck opened"),
        h("h2", {}, "The full list"),
        h("p", {}, "Read the curve, tune individual copies, and prepare the cards you want after game one."),
      ),
      h(
        "button",
        { class: "quiet-button", type: "button", on: { click: () => setDeckExpanded(false, ".playmat") } },
        "Collapse deck",
      ),
    ),
      h(
        "div",
        { class: "workbench-grid" },
        h(
          "div",
          { class: "workbench-main" },
          mainSuggestions,
          matZone("Main deck", "main", deck.main, validation?.mainTotal ?? 0, mainTarget, championId),
        ),
        h(
          "aside",
          { class: "workbench-side", id: "sideboard-workbench" },
          sideboardSuggestions
            ?? h("p", { class: "suggest-empty" }, "No comparable sideboards are available yet. You can still add any legal card from the drawer."),
          matZone("Sideboard", "sideboard", deck.sideboard, validation?.sideboardTotal ?? 0, sideboardTarget),
          h(
            "button",
            { class: "quiet-button sideboard-find", type: "button", on: { click: openCardFinder } },
            "Find a sideboard card",
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
  renderedRoot = root;
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

  const format = store.state.formats.find((row) => row.format === deck.format);
  const constraint = (name: string, fallback: number): number => {
    const parsed = Number(format?.constraints[name]);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
  };
  const mainTarget = constraint("main_deck_size_exact", 40);
  const runeTarget = constraint("rune_count_exact", 12);
  const battlefieldTarget = constraint("battlefield_count_exact", 3);
  const rawSideboardTarget = Number(format?.constraints.sideboard_max);
  const sideboardTarget = Number.isFinite(rawSideboardTarget) && rawSideboardTarget > 0
    ? rawSideboardTarget
    : null;

  // The page is a play surface before it is a card wall. Every zone has the same
  // spatial relationship it has during a game, and the forty-card list only unfolds
  // when the player asks to edit it in detail.
  const playmat = h(
    "section",
    { class: "playmat", aria: { label: "Deck playmat" } },
    h("span", { class: "playmat-seam", aria: { hidden: "true" } }),
    battlefieldRow(
      deck.battlefields,
      battlefieldTarget,
      deck.battlefields.length < battlefieldTarget ? suggestions?.battlefields ?? [] : [],
    ),
    identityRow(deck.legendId, deck.championId),
    mainDeckSpot(deck.main, validation?.mainTotal ?? 0, suggestions?.main ?? []),
    runeZone(
      deck.runes,
      validation?.runeTotal ?? 0,
      runeTarget,
      Boolean(suggestions?.runes),
    ),
    sideboardSpot(
      deck.sideboard,
      validation?.sideboardTotal ?? 0,
      sideboardTarget,
      Boolean(suggestions?.sideboard?.length),
    ),
  );

  replace(
    root,
    header,
    playmat,
    chooseChampion,
    deckExpanded
      ? deckWorkbench(
          mainTarget,
          sideboardTarget,
          deck.championId,
          {
            main: suggestions?.main ?? [],
            sideboard: suggestions?.sideboard ?? [],
          },
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
