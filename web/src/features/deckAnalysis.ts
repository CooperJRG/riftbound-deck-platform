import type {
  BuildSuggestions,
  CardAvailability,
  DeckPayload,
  Validation,
} from "../api/types";
import { h } from "../ui/dom";
import { analyzeDeck } from "./deckAnalysisModel";
import { deckStrength } from "./deckStrength";

function bars(
  rows: { label: string; copies: number }[],
  className: string,
): HTMLElement {
  const max = Math.max(1, ...rows.map((row) => row.copies));
  return h(
    "div",
    { class: className },
    ...rows.map((row) => h(
      "div",
      { class: "signal-bar", title: `${row.label}: ${row.copies}` },
      h("span", { class: "signal-bar-value", style: `--signal:${row.copies / max}` }, String(row.copies)),
      h("span", { class: "signal-bar-label" }, row.label),
    )),
  );
}

export function deckAnalysisRail(
  deck: DeckPayload,
  cards: Map<string, CardAvailability>,
  validation: Validation | null,
  suggestions: BuildSuggestions | null,
): HTMLElement {
  const model = analyzeDeck(deck, cards, validation, suggestions);
  const match = suggestions?.fieldMatch;
  const matchMeta = match?.available
    ? `${match.sampleDecks} comparable list${match.sampleDecks === 1 ? "" : "s"}`
      + (match.tournamentDecks ? ` · ${match.tournamentDecks} tournament-backed` : "")
    : "Waiting for a comparable list";
  return h(
    "aside",
    { class: "deck-analysis", aria: { label: "Live deck analysis" } },
    h("header", { class: "analysis-head" },
      h("div", {}, h("span", { class: "eyebrow" }, "Live deck signal"), h("h2", {}, model.status)),
      h("span", { class: `analysis-orb is-${model.tone}`, aria: { hidden: "true" } }),
    ),
    h("p", { class: "analysis-lead" }, model.explanation),
    h("div", { class: "readiness-path", aria: { label: "Readiness path" } },
      ...["Identity", "Legal list", "Field shape", "Your finish"].map((label, index) =>
        h("span", { class: index <= model.reachedSteps ? "is-reached" : "" }, label)),
    ),
    deckStrength(suggestions?.deckScore ?? null),
    h("section", { class: "analysis-section" },
      h("div", { class: "analysis-title" }, h("h3", {}, "Energy curve"), h("span", {}, model.averageCost === null ? "— avg" : `${model.averageCost.toFixed(1)} avg`)),
      bars(model.curve, "curve-bars"),
      model.knownCopies < model.totalCopies
        ? h("p", { class: "analysis-note" }, `${model.totalCopies - model.knownCopies} unresolved copies are omitted.`)
        : null,
    ),
    h("section", { class: "analysis-section" },
      h("div", { class: "analysis-title" }, h("h3", {}, "Card balance"), h("span", {}, `${model.totalCopies} main`)),
      model.types.length ? bars(model.types, "type-bars") : h("p", { class: "analysis-empty" }, "Card types will appear as you build."),
    ),
    h("section", { class: "analysis-section field-match" },
      h("div", { class: "analysis-title" }, h("h3", {}, "Closest field family"), h("strong", {}, match?.available ? `${Math.round(match.similarity * 100)}%` : "—")),
      h("p", { class: "analysis-family" }, match?.name || "No comparison yet"),
      h("p", { class: "analysis-note" }, match?.summary ?? "Suggestions are still loading."),
      h("p", { class: "analysis-source" }, `${matchMeta} · published lists, not matchup data`),
    ),
    h("section", { class: "analysis-section rune-plan" },
      h("div", { class: "analysis-title" }, h("h3", {}, "Rune plan")),
      h("p", { class: "analysis-note" }, suggestions?.runeReason ?? "Waiting for the deck's domain signal."),
    ),
  );
}
