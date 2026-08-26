/**
 * The meta view.
 *
 * Two things every row makes visible, because a ranking nobody can argue with is a
 * ranking nobody should trust:
 *
 * 1. **What backs this deck** — a placed tournament finish, an entry, or just a
 *    published list. The tiers look different, and the weakest one says so.
 * 2. **What it would cost you** — the same availability profile that drives the card
 *    browser, applied to somebody else's deck. "3rd of 257" matters much less to a
 *    casual player than "and you're four cards short of it".
 */

import type { Archetype, Evidence, MetaDeck } from "../api/types";
import {
  importMetaDeck,
  loadMeta,
  openArchetype,
  setMetaBuildableOnly,
} from "../state/actions";
import { store } from "../state/store";
import { h, replace } from "../ui/dom";

const EVIDENCE_LABEL: Record<Evidence, string> = {
  "tournament-placed": "Tournament result",
  "tournament-entry": "Tournament entry",
  community: "Community deck",
};

function evidenceBadge(evidence: Evidence): HTMLElement {
  return h(
    "span",
    { class: `evidence evidence-${evidence}` },
    EVIDENCE_LABEL[evidence] ?? evidence,
  );
}

/** "You can build this" / "4 cards short", from the active availability profile. */
function coverageChip(deck: MetaDeck): HTMLElement {
  const { coverage } = deck;
  if (coverage.complete) {
    return h("span", { class: "gap gap-ok" }, "You can build this");
  }
  const short = coverage.missing.reduce((sum, m) => sum + m.copies, 0);
  return h(
    "span",
    { class: "gap gap-short", title: coverage.missing.map((m) => m.name).join(", ") },
    `${short} card${short === 1 ? "" : "s"} short`,
  );
}

function scoreBar(deck: MetaDeck): HTMLElement {
  const pct = Math.round(deck.score.total * 100);
  return h(
    "span",
    {
      class: "score",
      title:
        `score ${deck.score.total.toFixed(3)} — evidence ${deck.score.evidence.toFixed(2)}, ` +
        `placement ${deck.score.placement.toFixed(2)}, recency ${deck.score.recency.toFixed(2)}, ` +
        `popularity ${deck.score.popularity.toFixed(2)}`,
    },
    h("span", { class: "score-fill", style: `width:${pct}%` }),
  );
}

function missingList(deck: MetaDeck): HTMLElement | null {
  if (deck.coverage.complete || deck.coverage.missing.length === 0) return null;
  return h(
    "ul",
    { class: "missing-list" },
    ...deck.coverage.missing
      .slice(0, 6)
      .map((m) => h("li", {}, `${m.copies}× ${m.name}`)),
    deck.coverage.missing.length > 6
      ? h("li", { class: "muted" }, `+${deck.coverage.missing.length - 6} more`)
      : null,
  );
}

function deckRow(deck: MetaDeck): HTMLElement {
  return h(
    "article",
    { class: "meta-deck" },
    h(
      "div",
      { class: "meta-deck-head" },
      h("h4", { class: "meta-deck-name", title: deck.name }, deck.name || "Untitled"),
      scoreBar(deck),
    ),
    h(
      "p",
      { class: "meta-deck-meta" },
      evidenceBadge(deck.provenance.evidence),
      h("span", { class: "prov" }, deck.provenance.summary),
      coverageChip(deck),
    ),
    h(
      "p",
      { class: "meta-deck-identity muted small" },
      deck.legendName,
      deck.championName ? ` · ${deck.championName}` : "",
      ` · ${deck.mainTotal} cards`,
      deck.unresolved.length > 0
        ? h(
            "span",
            { class: "warn-inline", title: deck.unresolved.join(", ") },
            ` · ${deck.unresolved.length} unknown card${deck.unresolved.length === 1 ? "" : "s"}`,
          )
        : null,
    ),
    missingList(deck),
    h(
      "div",
      { class: "meta-deck-actions" },
      h(
        "button",
        {
          class: "btn btn-primary",
          type: "button",
          on: { click: () => void importMetaDeck(deck.deckId) },
        },
        "Open in builder",
      ),
      deck.provenance.url
        ? h(
            "a",
            {
              class: "btn btn-ghost",
              href: deck.provenance.url,
              // Deck pages are third-party; open them away from the app.
              target: "_blank",
              rel: "noopener noreferrer",
            },
            "Source",
          )
        : null,
    ),
  );
}

function archetypeRow(arch: Archetype): HTMLElement {
  const best = arch.bestDeck;
  return h(
    "button",
    {
      class: "archetype",
      type: "button",
      on: { click: () => void openArchetype(arch.archetypeId) },
    },
    h(
      "div",
      { class: "archetype-head" },
      h("span", { class: "archetype-name" }, arch.name || "Unknown"),
      h("span", { class: "archetype-score muted small" }, arch.score.toFixed(2)),
    ),
    h(
      "p",
      { class: "archetype-meta muted small" },
      `${arch.deckCount} deck${arch.deckCount === 1 ? "" : "s"}`,
      arch.tournamentDeckCount > 0 ? ` · ${arch.tournamentDeckCount} from events` : "",
      arch.bestPlacement > 0
        ? ` · best #${arch.bestPlacement}${arch.bestFieldSize ? ` of ${arch.bestFieldSize}` : ""}`
        : "",
    ),
    best ? coverageChip(best) : null,
  );
}

function statusLine(): HTMLElement {
  const { metaStatus } = store.state;
  if (!metaStatus || !metaStatus.available) {
    return h("p", { class: "muted small" }, "No meta data.");
  }
  const placed = metaStatus.evidenceCounts["tournament-placed"] ?? 0;
  const date = metaStatus.createdAt.slice(0, 10);
  return h(
    "p",
    { class: "muted small" },
    `${metaStatus.deckCount} decks from ${metaStatus.tournamentCount} events`,
    placed > 0 ? ` · ${placed} with a known finish` : " · no known finishes",
    ` · harvested ${date}`,
  );
}

/**
 * Source credits.
 *
 * TopDeck.gg's API terms require a visible credit and a link back on any project that
 * uses it. The requirement travels with the snapshot, so this renders whatever the
 * data itself says is owed rather than a hardcoded line that could drift out of date.
 */
function attributionLine(): HTMLElement | null {
  const credits = store.state.metaStatus?.attribution ?? [];
  if (credits.length === 0) return null;
  return h(
    "p",
    { class: "attribution muted small" },
    ...credits.flatMap((credit, index) => [
      index > 0 ? h("span", {}, " · ") : null,
      h(
        "a",
        { href: credit.url, target: "_blank", rel: "noopener noreferrer" },
        credit.text || credit.source,
      ),
    ]),
  );
}

function emptyState(): HTMLElement {
  return h(
    "div",
    { class: "meta-empty" },
    h("h3", {}, "No meta data yet"),
    h(
      "p",
      { class: "muted" },
      "Harvest tournament results and published decklists with:",
    ),
    h("pre", { class: "cmd" }, "python -m riftbound.data.meta_pipeline build --promote"),
    h(
      "p",
      { class: "muted small" },
      "The builder works without this — meta data only adds the browse-and-copy view.",
    ),
    h(
      "button",
      { class: "btn", type: "button", on: { click: () => void loadMeta() } },
      "Check again",
    ),
  );
}

export function renderMeta(root: HTMLElement): void {
  const { metaStatus, archetypes, metaDecks, metaLoading, metaArchetype, metaBuildableOnly } =
    store.state;

  if (metaStatus && !metaStatus.available) {
    replace(root, emptyState());
    return;
  }

  const controls = h(
    "div",
    { class: "meta-controls" },
    h(
      "label",
      { class: "strict-toggle", title: "Hide decks you could not field" },
      h("input", {
        type: "checkbox",
        checked: metaBuildableOnly,
        on: {
          change: (e) =>
            void setMetaBuildableOnly((e.target as HTMLInputElement).checked),
        },
      }),
      " Only decks I can build",
    ),
    metaArchetype
      ? h(
          "button",
          { class: "btn", type: "button", on: { click: () => void openArchetype("") } },
          "← All archetypes",
        )
      : null,
  );

  replace(
    root,
    h(
      "div",
      { class: "meta-head" },
      h("h2", { class: "meta-title" }, "Meta"),
      statusLine(),
      attributionLine(),
    ),
    controls,
    metaLoading ? h("p", { class: "muted" }, "Loading…") : null,
    !metaArchetype && archetypes.length > 0
      ? h(
          "section",
          { class: "archetype-list" },
          h("h3", { class: "zone-title" }, "Top archetypes"),
          ...archetypes.map(archetypeRow),
        )
      : null,
    h(
      "section",
      { class: "meta-deck-list" },
      h(
        "h3",
        { class: "zone-title" },
        metaArchetype ? "Decks in this archetype" : "Top decks",
      ),
      metaDecks.length === 0 && !metaLoading
        ? h(
            "p",
            { class: "muted small" },
            metaBuildableOnly
              ? "No meta deck is fully buildable from what you have. Untick the filter to see how close you are."
              : "No decks in this snapshot.",
          )
        : h("div", { class: "meta-decks" }, ...metaDecks.map(deckRow)),
    ),
  );
}
