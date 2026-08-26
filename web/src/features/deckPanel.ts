/**
 * The deck itself, plus legality and coverage.
 *
 * Legality and coverage are shown as two separate readouts, because they are two
 * different problems: "this deck breaks a rule" and "this deck is legal but you're
 * missing four cards" need different responses from the player.
 */

import type { Issue, Validation, Zone } from "../api/types";
import { adjustCard, setChampion, setDeckName, setLegend } from "../state/actions";
import { store } from "../state/store";
import { h, replace } from "../ui/dom";

function cardName(cardId: string): string {
  return store.state.deckCards.get(cardId)?.card.name ?? cardId;
}

function isPenalised(cardId: string): boolean {
  const row = store.state.deckCards.get(cardId);
  return row !== undefined && row.weight < 1;
}

function deckRow(cardId: string, qty: number, zone: Zone): HTMLElement {
  return h(
    "li",
    { class: `deck-row${isPenalised(cardId) ? " is-dim" : ""}` },
    h("span", { class: "qty" }, `${qty}×`),
    h("span", { class: "deck-card-name", title: cardName(cardId) }, cardName(cardId)),
    h(
      "span",
      { class: "row-actions" },
      h("button", {
        class: "step", type: "button", aria: { label: `Remove one ${cardName(cardId)}` },
        on: { click: () => adjustCard(cardId, zone, -1) },
      }, "−"),
      h("button", {
        class: "step", type: "button", aria: { label: `Add one ${cardName(cardId)}` },
        on: { click: () => adjustCard(cardId, zone, 1) },
      }, "+"),
    ),
  );
}

function zoneSection(
  title: string,
  zone: Zone,
  counts: Record<string, number>,
  total: number,
  target: number | null,
): HTMLElement {
  const entries = Object.entries(counts).sort(([a], [b]) =>
    cardName(a).localeCompare(cardName(b)),
  );
  const ok = target === null || total === target;
  return h(
    "section",
    { class: "zone" },
    h(
      "h3",
      { class: "zone-title" },
      title,
      h("span", { class: `zone-count${ok ? "" : " is-off"}` },
        target === null ? String(total) : `${total} / ${target}`),
    ),
    entries.length === 0
      ? h("p", { class: "muted small" }, "Empty")
      : h("ul", { class: "deck-list" },
          ...entries.map(([cardId, qty]) => deckRow(cardId, qty, zone))),
  );
}

function battlefieldSection(ids: string[], target: number): HTMLElement {
  return h(
    "section",
    { class: "zone" },
    h("h3", { class: "zone-title" }, "Battlefields",
      h("span", { class: `zone-count${ids.length === target ? "" : " is-off"}` },
        `${ids.length} / ${target}`)),
    ids.length === 0
      ? h("p", { class: "muted small" }, "Empty")
      : h("ul", { class: "deck-list" },
          ...ids.map((id) =>
            h("li", { class: `deck-row${isPenalised(id) ? " is-dim" : ""}` },
              h("span", { class: "deck-card-name" }, cardName(id)),
              h("button", {
                class: "step", type: "button",
                aria: { label: `Remove ${cardName(id)}` },
                on: { click: () => adjustCard(id, "battlefields", -1) },
              }, "−")))),
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
  const { deck, validation } = store.state;

  const header = h(
    "div",
    { class: "deck-header" },
    deckNameInput(deck.name),
    validation
      ? h("span", { class: `legal-badge${validation.legal ? " is-legal" : ""}` },
          validation.legal ? "Legal" : "Not legal")
      : null,
  );

  const identity = h(
    "section",
    { class: "zone identity" },
    h("h3", { class: "zone-title" }, "Legend & champion"),
    h("p", { class: "identity-row" },
      h("span", { class: "identity-label" }, "Legend"),
      h("span", { class: "identity-value" },
        deck.legendId ? cardName(deck.legendId) : "—"),
      deck.legendId
        ? h("button", { class: "step", type: "button", on: { click: () => setLegend("") } }, "×")
        : null),
    h("p", { class: "identity-row" },
      h("span", { class: "identity-label" }, "Champion"),
      h("span", { class: "identity-value" },
        deck.championId ? cardName(deck.championId) : "—"),
      deck.championId
        ? h("button", { class: "step", type: "button", on: { click: () => setChampion("") } }, "×")
        : null),
    validation && validation.legendDomains.length > 0
      ? h("p", { class: "muted small" },
          `Domain identity: ${validation.legendDomains.join(" / ")}`)
      : null,
  );

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

  const issues = problems.length > 0
    ? h("section", { class: "issues" },
        h("h3", { class: "zone-title" }, "Legality"),
        h("ul", { class: "issue-list" }, ...problems.map(issueItem)))
    : null;

  const beforeYouPlay = notices.length > 0
    ? h("section", { class: "issues" },
        h("h3", { class: "zone-title" }, "Before you play"),
        h("ul", { class: "issue-list" }, ...notices.map(issueItem)))
    : null;

  replace(
    root,
    header,
    identity,
    chooseChampion,
    zoneSection("Main deck", "main", deck.main, validation?.mainTotal ?? 0, 40),
    zoneSection("Runes", "runes", deck.runes, validation?.runeTotal ?? 0, 12),
    battlefieldSection(deck.battlefields, 3),
    zoneSection("Sideboard", "sideboard", deck.sideboard, validation?.sideboardTotal ?? 0, null),
    validation ? coveragePanel(validation) : null,
    issues,
    beforeYouPlay,
  );
}
