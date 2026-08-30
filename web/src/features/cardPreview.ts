/**
 * The card, big enough to read.
 *
 * Forty pieces of art at 130px are a deck you can recognise but not a deck you can
 * check. Every card on the mat opens this: the full picture uncropped, the cost line
 * spelled out, and the rules text -- the one thing the mat cannot show at any size.
 *
 * A real `<dialog>` rather than a positioned div. `showModal()` brings Escape-to-close,
 * a focus trap, inertness for the page behind it and a top-layer stacking context that
 * no `z-index` on the mat can beat. Hand-rolling those is how a lightbox ends up
 * trapping the tab key in the page behind it.
 */

import type { Card, Zone } from "../api/types";
import { api } from "../api/client";
import { adjustCard } from "../state/actions";
import { store } from "../state/store";
import { h, replace } from "../ui/dom";

/** One dialog, reused. Building a new one per card leaks a node per click. */
let dialog: HTMLDialogElement | null = null;

/** What the dialog is currently showing, so re-renders can refresh it in place. */
let showing: { cardId: string; zone: Zone | null } | null = null;

/** Cards opened from lightweight recommendations are resolved lazily and reused. */
const resolvedCards = new Map<string, Card>();

function findCard(cardId: string): Card | undefined {
  return store.state.deckCards.get(cardId)?.card
    ?? store.state.cards.find((row) => row.card.cardId === cardId)?.card
    ?? resolvedCards.get(cardId);
}

/**
 * The cost line, in the game's own terms.
 *
 * Energy is the generic half of a cost and power the domain-specific half: a card
 * asking for four Body power cannot be cast off three Body runes, which is exactly the
 * thing a player is trying to work out when they open a card. Shown separately for that
 * reason rather than added into one number.
 */
function costLine(card: Card): HTMLElement | null {
  const parts: HTMLElement[] = [];
  if (card.cost !== null) {
    parts.push(h("span", { class: "peek-stat" }, h("b", {}, String(card.cost)), " energy"));
  }
  if (card.power !== null && card.power > 0) {
    parts.push(
      h(
        "span",
        { class: "peek-stat" },
        h("b", {}, String(card.power)),
        ` ${card.domains.join("/") || ""} power`.trimEnd(),
      ),
    );
  }
  if (card.might !== null) {
    parts.push(h("span", { class: "peek-stat" }, h("b", {}, String(card.might)), " might"));
  }
  return parts.length ? h("div", { class: "peek-stats" }, ...parts) : null;
}

/** "Champion Unit - Fury / Calm", the line printed under the art. */
function typeLine(card: Card): string {
  const left = [card.superType, card.cardType].filter(Boolean).join(" ");
  const right = card.domains.join(" / ");
  return [left, right].filter(Boolean).join("  -  ");
}

function copiesInZone(cardId: string, zone: Zone): number {
  if (zone === "battlefields") return store.state.deck.battlefields.includes(cardId) ? 1 : 0;
  return store.state.deck[zone][cardId] ?? 0;
}

function body(cardId: string, zone: Zone | null): HTMLElement[] {
  const card = findCard(cardId);
  if (!card) {
    return [
      h(
        "div",
        { class: "dialog-loading" },
        h("h2", { id: "card-preview-title" }, "Card unavailable"),
        h("p", { class: "muted" }, "This card is not in the current card data."),
        h("button", { class: "quiet-button", type: "button", on: { click: closeCardPreview } }, "Close"),
      ),
    ];
  }
  const copies = zone ? copiesInZone(cardId, zone) : 0;

  return [
    h(
      "div",
      { class: "peek-art" },
      card.imageUrl
        ? h("img", { src: card.imageUrl, alt: card.name })
        : h("span", { class: "mat-card-blank" }, card.name),
    ),
    h(
      "div",
      { class: "peek-detail" },
      h(
        "header",
        { class: "peek-head" },
        h("div", {}, h("p", { class: "eyebrow" }, "Card detail"), h("h2", { class: "peek-name", id: "card-preview-title" }, card.name)),
        h("button", { class: "dialog-x", type: "button", aria: { label: "Close card preview" }, on: { click: closeCardPreview } }, "×"),
      ),
      h("p", { class: "peek-type" }, typeLine(card)),
      costLine(card),
      // The one thing the mat cannot show at any size.
      card.effect
        ? h("div", { class: "peek-text" }, ...card.effect.split("\n").map((line) => h("p", {}, line)))
        : h("p", { class: "peek-text muted" }, "No rules text."),
      card.tags.length
        ? h("div", { class: "peek-tags" }, ...card.tags.map((tag) => h("span", { class: "pill" }, tag)))
        : null,
      h(
        "p",
        { class: "peek-meta" },
        [card.rarity, card.setCodes.join(", ")].filter(Boolean).join("  -  "),
        card.unique ? "  -  Unique" : null,
      ),
      // Adjusting from here saves a round trip to the card on the mat, which is the
      // whole reason somebody opened it to read the text in the first place.
      zone
        ? h(
            "div",
            { class: "peek-actions" },
            h(
              "button",
              {
                class: "step", type: "button", aria: { label: `Remove one ${card.name}` },
                disabled: copies === 0,
                on: { click: () => adjustCard(cardId, zone, -1) },
              },
              "−",
            ),
            h("span", { class: "peek-count" }, `${copies} in ${zone === "sideboard" ? "sideboard" : zone === "battlefields" ? "battlefields" : zone === "runes" ? "runes" : "main deck"}`),
            h(
              "button",
              {
                class: "step", type: "button", aria: { label: `Add one ${card.name}` },
                on: { click: () => adjustCard(cardId, zone, 1) },
              },
              "+",
            ),
          )
        : h("button", { class: "quiet-button peek-close", type: "button", on: { click: closeCardPreview } }, "Close"),
    ),
  ];
}

function loadingBody(): HTMLElement[] {
  return [
    h(
      "div",
      { class: "dialog-loading" },
      h("p", { class: "eyebrow" }, "Card detail"),
      h("h2", { id: "card-preview-title" }, "Opening card…"),
      h("p", { class: "muted" }, "Fetching the full-resolution card and rules text."),
      h("button", { class: "quiet-button", type: "button", on: { click: closeCardPreview } }, "Close"),
    ),
  ];
}

function ensureDialog(): HTMLDialogElement {
  if (dialog) return dialog;
  dialog = h("dialog", { class: "peek", aria: { labelledby: "card-preview-title" } }) as HTMLDialogElement;
  // Clicking outside the card closes it. `<dialog>` reports backdrop clicks as clicks
  // on the dialog itself, so the check is "did this land on the element and not on
  // anything inside it".
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) closeCardPreview();
  });
  dialog.addEventListener("close", () => {
    showing = null;
  });
  document.body.appendChild(dialog);
  return dialog;
}

export function openCardPreview(cardId: string, zone: Zone | null = null): void {
  const node = ensureDialog();
  showing = { cardId, zone };
  const known = findCard(cardId);
  replace(node, ...(known ? body(cardId, zone) : loadingBody()));
  if (!node.open) node.showModal();
  if (known) return;

  void api.card(cardId).then((card) => {
    resolvedCards.set(card.cardId, card);
    if (showing?.cardId === cardId && node.open) replace(node, ...body(cardId, zone));
  }).catch(() => {
    if (showing?.cardId === cardId && node.open) replace(node, ...body(cardId, zone));
  });
}

export function closeCardPreview(): void {
  if (dialog?.open) dialog.close();
  showing = null;
}

/**
 * Keep an open preview in step with the deck.
 *
 * Adding a copy from inside the dialog changes the deck, which re-renders the mat
 * underneath; without this the count in the dialog would stay at whatever it was when
 * it opened, which is the number the player is looking at while pressing the button.
 */
export function refreshCardPreview(): void {
  if (!showing || !dialog?.open) return;
  replace(dialog, ...body(showing.cardId, showing.zone));
}
