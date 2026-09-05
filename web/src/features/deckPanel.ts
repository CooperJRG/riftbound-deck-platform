/**
 * The deck itself, plus legality and coverage.
 *
 * Legality and coverage are shown as two separate readouts, because they are two
 * different problems: "this deck breaks a rule" and "this deck is legal but you're
 * missing four cards" need different responses from the player.
 */

import type {
  BuildSuggestions,
  CardSuggestion,
  ChampionOption,
  Issue,
  SideboardPlan,
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
import { collectionSummary } from "./collectionSummary";
import { openAvailabilityMenu } from "../ui/availabilityMenu";
import { openCardPreview } from "./cardPreview";
import { deckAnalysisRail } from "./deckAnalysis";
import { renderOpeningHand } from "./openingHand";
import { analyzeDeck } from "./deckAnalysisModel";
import {
  dismissSuggestion,
  type DismissibleSuggestionZone,
  visibleSuggestions,
} from "./suggestionPreferences";

/**
 * The playmat is the default overview; the forty-card wall is an intentional detail
 * view. These are presentation choices, not deck data, so they stay local instead of
 * being persisted with the list or triggering API work when toggled.
 */
let renderedRoot: HTMLElement | null = null;
let deckExpanded = false;
let mainSuggestionsVisible = true;
let sideboardSuggestionsVisible = true;
const VISIBLE_SUGGESTIONS = 5;

function repaintDeck(): void {
  if (renderedRoot) renderDeckPanel(renderedRoot);
}

function dismissSuggestedCard(cardId: string, zone: DismissibleSuggestionZone): void {
  dismissSuggestion(cardId, store.state.deck.legendId, zone);
  repaintDeck();
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
  reason = "Fill the rune base from this deck's power costs",
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
          title: reason,
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
    h(
      "button",
      {
        class: "battlefield-dismiss",
        type: "button",
        title: `Do not suggest ${row.name} again for this legend`,
        aria: { label: `Dismiss ${row.name} battlefield suggestion` },
        on: { click: () => dismissSuggestedCard(row.cardId, "battlefields") },
      },
      "×",
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
  zone: "main" | "sideboard",
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
                  class: "suggest-dismiss", type: "button",
                  title: `Do not suggest ${row.name} again for this legend`,
                  on: { click: () => dismissSuggestedCard(row.cardId, zone) },
                }, "Dismiss"),
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
          h(
            "button",
            {
              class: "starter-suggest-dismiss",
              type: "button",
              title: `Do not suggest ${row.name} again for this legend`,
              aria: { label: `Dismiss ${row.name} suggestion` },
              on: { click: () => dismissSuggestedCard(row.cardId, "main") },
            },
            "×",
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


/** The current suggestion payload, for the parts of the workbench that need more of it. */
function suggestionsFor(): BuildSuggestions | null {
  return store.state.suggestions;
}

/**
 * What to prepare for after game one.
 *
 * The order is the whole point, and it is not the order of worst matchups. A matchup
 * costs you `share x (winRate - 0.5)` of expected win rate, so losing badly to a deck
 * nobody brings costs almost nothing while a mediocre matchup against the most popular
 * legend in the format costs a great deal. The server ranks on that; this renders it.
 *
 * What it deliberately does **not** claim: that any particular card answers any
 * particular matchup. No source available to this project records which card won which
 * game, so a "counter card" list could only be invented. What is shown instead is what
 * the opponent reliably plays -- a fact -- next to the sideboard cards comparable lists
 * actually hold, and the player draws the line between them.
 */
function boardingPlan(plan: SideboardPlan | null | undefined): HTMLElement | null {
  if (!plan || !plan.available || !plan.outlook) return null;
  const { outlook, plans } = plan;

  const header = h(
    "header",
    { class: "suggest-head" },
    h("h3", {}, "Board for"),
    h(
      "p",
      {},
      plans.length
        ? "Ranked by what each matchup costs you across the whole field, not by how "
          + "badly it goes. They are what the opponent brings -- the answer is yours to pick."
        : "No matchup costs enough to be worth spending slots on. This legend sits well "
          + "in the current field.",
    ),
  );

  const outlookLine = h(
    "p",
    { class: "board-outlook" },
    h(
      "span",
      { class: `board-rate${outlook.expectedWinRate >= 0.5 ? " is-good" : " is-bad"}` },
      `${(outlook.expectedWinRate * 100).toFixed(1)}%`,
    ),
    h("span", { class: "muted small" }, ` expected into the field, over ${(outlook.coverage * 100).toFixed(0)}% of it`),
  );

  return h(
    "section",
    { class: "suggest board-plan" },
    header,
    outlookLine,
    ...plans.map((entry) =>
      h(
        "article",
        { class: "board-matchup" },
        h(
          "header",
          { class: "board-matchup-head" },
          entry.matchup.imageUrl
            ? h("img", {
                class: "board-matchup-art",
                src: entry.matchup.imageUrl,
                alt: "",
                loading: "lazy",
              })
            : null,
          h(
            "span",
            {},
            h("strong", {}, entry.matchup.opponentName),
            h("small", {}, entry.matchup.summary),
          ),
        ),
        entry.threats.length
          ? h(
              "p",
              { class: "board-threats" },
              h("span", { class: "board-threats-label" }, "They bring: "),
              entry.threats
                .slice(0, 6)
                .map((t) => `${t.name} (${Math.round(t.playRate * 100)}%)`)
                .join(", "),
            )
          : null,
      ),
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
          boardingPlan(suggestionsFor()?.sideboardPlan),
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
    return h("p", { class: "coverage is-ok" }, store.state.availability?.mode === "collection"
      ? "Every copy is covered by your collection settings."
      : "No missing cards under your current settings. Check quantities before you play.");
  }
  const short = coverage.missing.reduce((sum, m) => sum + m.copies, 0);
  return h(
    "div",
    { class: "coverage is-short" },
    h("p", { class: "coverage-head" },
      `${short} missing ${short === 1 ? "copy" : "copies"} across ${coverage.missing.length} card${coverage.missing.length === 1 ? "" : "s"}:`),
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
 * The whole header row is kept across renders, not just the name input inside it.
 *
 * The input alone used to be cached, on the reasoning below -- but it was still being
 * handed to a brand-new `h("div", ..., nameInput, ...)` wrapper on every render. `h()`
 * appends its children, and appending an already-connected node removes it from its
 * current parent first: for one instant the input is detached from the document
 * entirely, which blurs it the same as deleting and recreating it would. Typing a
 * second character meant refocusing the field by hand, every time. The fix is to stop
 * building a new wrapper at all -- keep the row itself, and only touch the two things
 * in it that actually change.
 *
 * Typing a name updates the deck, which re-renders this panel; re-creating the input
 * each time would blur it after the first character. Its value is written back only
 * when the field is not focused, so a deck loaded from the library still updates it.
 */
interface HeaderRow {
  root: HTMLElement;
  name: HTMLInputElement;
  findCards: HTMLButtonElement;
  badge: HTMLElement;
}
let headerRow: HeaderRow | null = null;

function deckHeader(name: string): HeaderRow {
  if (headerRow === null) {
    const nameField = h("input", {
      class: "deck-name",
      aria: { label: "Deck name" },
      on: { input: (e) => setDeckName((e.target as HTMLInputElement).value) },
    });
    // The way back to the drawer once it is closed. It lives on the deck because
    // that is the only thing on screen at that point. Hidden rather than only ever
    // added when needed, for the same reason the row itself is no longer rebuilt.
    const findCards = h(
      "button",
      { class: "quiet-button", type: "button", on: { click: toggleDrawer } },
      "Find cards",
    );
    const badge = h("span", { class: "legal-badge" });
    const root = h("div", { class: "deck-header" }, nameField, findCards, badge);
    headerRow = { root, name: nameField, findCards, badge };
  }
  if (document.activeElement !== headerRow.name) headerRow.name.value = name;
  return headerRow;
}

/**
 * `header.root` is mounted into `root` exactly once here, never again through
 * `replace()`.
 *
 * Caching the header (above) stopped the input itself from being torn down and
 * recreated -- but `replace(root, header.root, ...restOfThePanel)` was still called on
 * every render, and `replace()` always does `root.replaceChildren()` before adding its
 * arguments back. That removes every current child of `root`, including `header.root`,
 * before re-adding the very same node a moment later: the same disconnect-then-
 * reconnect that blurs a focused input as tearing it down would, just one level higher
 * in the tree. `deckHeader()` alone was necessary but not sufficient; the header's
 * *parent* has to stop being rebuilt too. Everything that legitimately changes every
 * render -- the wall, the playmat, all of it -- goes through the returned slot instead,
 * so `header.root`'s position in `root` is set once and never disturbed again.
 */
let deckMount: { root: HTMLElement; slot: HTMLElement } | null = null;

function ensureDeckMount(root: HTMLElement, header: HeaderRow): HTMLElement {
  if (deckMount === null || deckMount.root !== root) {
    const slot = h("div", { class: "deck-body-slot" });
    root.replaceChildren(header.root, slot);
    deckMount = { root, slot };
  }
  return deckMount.slot;
}

export function renderDeckPanel(root: HTMLElement): void {
  renderedRoot = root;
  const { deck, validation, builderReview, suggestions } = store.state;
  const hasStarted = Boolean(
    deck.legendId || deck.championId || Object.keys(deck.main).length ||
      Object.keys(deck.runes).length || deck.battlefields.length || Object.keys(deck.sideboard).length,
  );

  // Computed here, ahead of the early-return legend wall below, because the header's
  // readiness badge needs the deck's real targets whether or not a legend is chosen
  // yet -- and because analyzeDeck needs the same numbers rather than assuming the
  // constructed format's 40/12/3, which skirmish's own rules already say are wrong.
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
  // The API sends a ranked reserve. Keep five readable choices on screen and promote
  // the next non-dismissed card into the window as soon as one is rejected.
  const offeredMain = visibleSuggestions(
    suggestions?.main ?? [], deck.legendId, "main",
  ).slice(0, VISIBLE_SUGGESTIONS);
  const offeredBattlefields = visibleSuggestions(
    suggestions?.battlefields ?? [], deck.legendId, "battlefields",
  );
  const offeredSideboard = visibleSuggestions(
    suggestions?.sideboard ?? [], deck.legendId, "sideboard",
  ).slice(0, VISIBLE_SUGGESTIONS);

  const analysis = analyzeDeck(
    deck, store.state.deckCards, validation, suggestions,
    { mainTarget, runeTarget, battlefieldTarget },
  );

  const header = deckHeader(deck.name);
  header.findCards.hidden = store.state.drawerOpen;
  header.badge.hidden = !validation;
  if (validation) {
    header.badge.className = `legal-badge${validation.legal ? " is-legal" : ""}`;
    header.badge.textContent =
      builderReview && !validation.legal ? "Needs attention" : analysis.status;
  }

  const slot = ensureDeckMount(root, header);

  if (!hasStarted) {
    const legends = store.state.smartLegends;
    const legendStatus = h("span", { class: "legend-filter-status", aria: { live: "polite" } });
    const showAll = h("button", { class: "quiet-button legend-show-all", type: "button" }, "Show all legends");
    const cards = legends.map((legend, index) =>
      h(
        "button",
        {
          class: "legend-pick",
          type: "button",
          title: `Build with ${legend.name}`,
          data: { legendName: legend.name.toLowerCase(), leading: String(index < 18) },
          on: { click: () => setLegend(legend.legendId) },
        },
        legend.imageUrl
          ? h("img", { src: legend.imageUrl, alt: legend.name, loading: "lazy" })
          : h("span", { class: "mat-card-blank" }, legend.name),
        h("span", { class: "legend-pick-name" }, legend.name),
        h("span", { class: "legend-pick-meta" }, legend.domains.join(" / ")),
      ),
    );
    let expanded = false;
    const applyLegendFilter = (value = "") => {
      const needle = value.trim().toLowerCase();
      let visible = 0;
      for (const card of cards) {
        const matches = !needle || card.dataset.legendName?.includes(needle);
        const inLeadingSet = card.dataset.leading === "true";
        card.hidden = !matches || (!needle && !expanded && !inLeadingSet);
        if (!card.hidden) visible += 1;
      }
      legendStatus.textContent = needle
        ? `${visible} matching legend${visible === 1 ? "" : "s"}`
        : expanded
          ? `All ${legends.length} legends`
          : `Showing 18 of ${legends.length}`;
      showAll.hidden = Boolean(needle) || legends.length <= 18;
      showAll.textContent = expanded ? "Show fewer" : "Show all legends";
    };
    const legendSearch = h("input", {
      class: "legend-filter",
      type: "search",
      placeholder: "Search legends",
      aria: { label: "Search legends" },
      on: {
        input: (event) => applyLegendFilter((event.target as HTMLInputElement).value),
      },
    });
    showAll.addEventListener("click", () => {
      expanded = !expanded;
      applyLegendFilter(legendSearch.value);
    });
    applyLegendFilter();

    replace(
      slot,
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
        legends.length
          ? h(
              "div",
              { class: "legend-browser" },
              h("div", { class: "legend-filter-row" }, legendSearch, legendStatus, showAll),
              h("div", { class: "legend-wall" }, ...cards),
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
      deck.battlefields.length < battlefieldTarget ? offeredBattlefields : [],
    ),
    identityRow(deck.legendId, deck.championId),
    mainDeckSpot(deck.main, validation?.mainTotal ?? 0, offeredMain),
    runeZone(
      deck.runes,
      validation?.runeTotal ?? 0,
      runeTarget,
      Boolean(suggestions?.runes),
      suggestions?.runeReason,
    ),
    sideboardSpot(
      deck.sideboard,
      validation?.sideboardTotal ?? 0,
      sideboardTarget,
      Boolean(offeredSideboard.length),
    ),
  );

  // Its own mount rather than a rendered subtree: the simulator holds a dealt hand in
  // module state and repaints itself, so it must not be rebuilt every time the deck
  // panel re-renders -- that would reshuffle the board under the player mid-mulligan.
  const openingSlot = h("div", { class: "opening-slot" });

  replace(
    slot,
    h(
      "div",
      { class: "builder-stage" },
      playmat,
      deckAnalysisRail(deck, store.state.deckCards, validation, suggestions),
    ),
    openingSlot,
    chooseChampion,
    deckExpanded
      ? deckWorkbench(
          mainTarget,
          sideboardTarget,
          deck.championId,
          {
            main: offeredMain,
            sideboard: offeredSideboard,
          },
        )
      : null,
    h(
      "section",
      { class: "review-callout" },
      h("div", {}, h("strong", {}, builderReview ? (problems.length ? "Your list needs attention" : "Rules check complete") : "Ready for a rules check?"), h("span", {}, builderReview ? (problems.length ? "Review the items below before you play." : "No rules issues found. Check your card quantities and any notes below.") : "Check deck legality and your missing copies.")),
      h("button", { type: "button", class: builderReview ? "quiet-button" : "primary", on: { click: () => setBuilderReview(!builderReview) } }, builderReview ? "Hide review" : "Review deck"),
    ),
    validation && validation.coverage.totalCopies > 0
      ? h("section", { class: "collection-coverage" },
          h("h3", {}, "Your cards for this deck"),
          h("p", {}, collectionSummary(store.state.availability).detail),
          coveragePanel(validation),
          h("button", { class: "quiet-button", type: "button", on: { click: openAvailabilityMenu } }, "Edit collection settings"))
      : null,
    issues,
    beforeYouPlay,
  );

  // After the slot is in the document, so the simulator's own repaints have a mounted
  // node to write into.
  renderOpeningHand(openingSlot);
}
