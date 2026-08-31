import type { DeckScore } from "../api/types";
import { h } from "../ui/dom";

let tooltipSerial = 0;

/** The same two-number rating wherever a deck appears: meta first, legend second. */
export function deckStrength(
  score: DeckScore | null,
  { compact = false }: { compact?: boolean } = {},
): HTMLElement | null {
  if (!score) return null;
  const tooltipId = `deck-strength-help-${++tooltipSerial}`;
  const value = (rating: number): string => score.scored && rating >= 0
    ? String(Math.round(rating))
    : "—";
  return h(
    "section",
    { class: `deck-strength${compact ? " is-compact" : ""}`, aria: { label: "Deck strength ratings" } },
    h(
      "header",
      { class: "deck-strength-head" },
      h("strong", {}, "Deck strength"),
      h(
        "span",
        { class: "strength-help" },
        h("button", {
          class: "strength-help-trigger", type: "button",
          aria: { label: "How deck strength is calculated", describedby: tooltipId },
        }, "?"),
        h(
          "span",
          { class: "strength-tooltip", id: tooltipId, role: "tooltip" },
          h("b", {}, "What these numbers mean"),
          h("span", {}, "Meta strength compares this list with the strongest competitively evidenced deck in the current field. Legend strength compares it with the strongest evidenced list using this legend."),
          h("span", {}, "Both combine deck-list overlap with tournament evidence, placement relative to field size, recency, and limited community-quality signals."),
          h("em", {}, score.disclaimer),
        ),
      ),
    ),
    h(
      "div",
      { class: `deck-strength-values${score.scored ? "" : " is-unscored"}` },
      h("span", { class: "strength-value is-meta" }, h("b", {}, value(score.meta)), h("i", {}, "/100 meta")),
      h("span", { class: "strength-value is-legend" }, h("b", {}, value(score.legend)), h("i", {}, "/100 legend")),
    ),
    h("p", { class: "strength-summary" }, score.summary),
    h("p", { class: "strength-disclaimer" }, "Estimate, not a guarantee."),
  );
}
