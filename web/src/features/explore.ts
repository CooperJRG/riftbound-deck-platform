import type {
  CardAdoption,
  ChampionMeta,
  LegendChoice,
  LegendMeta,
  Pairing,
  TournamentDetail,
  TrendDeck,
  TrendSeries,
} from "../api/types";
import {
  closeExploreDetail,
  importMetaDeck,
  loadExplore,
  openChampion,
  openLegend,
  openTournament,
  setExploreFilter,
} from "../state/actions";
import { store } from "../state/store";
import { h, replace } from "../ui/dom";

type Tier = "S" | "A" | "B" | "C" | "U";

interface RankedLegend {
  legend: LegendChoice;
  trend: TrendSeries | null;
  score: number;
  tier: Tier;
}

const TIER_COPY: Record<Tier, { title: string; note: string }> = {
  S: { title: "S", note: "Defining the field" },
  A: { title: "A", note: "Established contenders" },
  B: { title: "B", note: "Firmly in the mix" },
  C: { title: "C", note: "Rogue and emerging" },
  U: { title: "—", note: "No complete lists in range" },
};

function pct(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}

function ordinal(value: number): string {
  if (value <= 0) return "Unplaced";
  const mod100 = value % 100;
  const suffix = mod100 >= 11 && mod100 <= 13
    ? "th"
    : value % 10 === 1
      ? "st"
      : value % 10 === 2
        ? "nd"
        : value % 10 === 3
          ? "rd"
          : "th";
  return `${value}${suffix}`;
}

function fullCard(imageUrl: string, name: string, className = "full-card"): HTMLElement {
  return h(
    "div",
    { class: className },
    imageUrl
      ? h("img", { src: imageUrl, alt: `${name} card`, loading: "lazy" })
      : h("div", { class: "full-card-fallback" }, name.slice(0, 2)),
  );
}

function domainMarks(domains: string[]): HTMLElement {
  return h(
    "span",
    { class: "dossier-domains" },
    ...domains.map((domain) =>
      h("span", { class: `domain-mark domain-${domain.toLowerCase()}` }, domain),
    ),
  );
}

function confidence(value: string): HTMLElement {
  const label = value === "high"
    ? "Strong sample"
    : value === "moderate"
      ? "Useful sample"
      : "Limited sample";
  return h("span", { class: `confidence confidence-${value}` }, label);
}

function metric(label: string, value: string, note = ""): HTMLElement {
  return h(
    "div",
    { class: "atlas-metric" },
    h("span", { class: "atlas-metric-label" }, label),
    h("strong", { class: "atlas-metric-value" }, value),
    note ? h("span", { class: "atlas-metric-note" }, note) : null,
  );
}

function rankLegends(legends: LegendChoice[], trends: TrendSeries[]): RankedLegend[] {
  const byId = new Map(trends.map((trend) => [trend.entityId, trend]));
  const maxShare = Math.max(...trends.map((trend) => trend.share), 0.01);
  const maxEvents = Math.max(...trends.map((trend) => trend.eventCount), 1);
  const ranked = legends.map((legend) => {
    const trend = byId.get(legend.legendId) ?? null;
    if (!trend) return { legend, trend, score: -1, tier: "U" as Tier };
    const movement = trend.momentum === null
      ? 0.5
      : (Math.max(-0.05, Math.min(0.05, trend.momentum)) + 0.05) / 0.1;
    const score = (trend.share / maxShare) * 0.58 +
      (trend.eventCount / maxEvents) * 0.27 + movement * 0.15;
    return { legend, trend, score, tier: "C" as Tier };
  });
  const evidenced = ranked.filter((row) => row.trend).sort((a, b) => b.score - a.score);
  evidenced.forEach((row, index) => {
    const position = index / Math.max(1, evidenced.length);
    row.tier = position < 0.125 ? "S" : position < 0.35 ? "A" : position < 0.67 ? "B" : "C";
  });
  return [...evidenced, ...ranked.filter((row) => !row.trend)];
}

function tierFor(legendId: string): Tier {
  return rankLegends(store.state.smartLegends, store.state.trendOverview?.series ?? [])
    .find((row) => row.legend.legendId === legendId)?.tier ?? "U";
}

function selectControl(
  label: string,
  value: string,
  options: { value: string; label: string }[],
  onChange: (value: string) => void,
): HTMLElement {
  return h(
    "label",
    { class: "atlas-field" },
    h("span", {}, label),
    h(
      "select",
      { value, on: { change: (event) => onChange((event.target as HTMLSelectElement).value) } },
      ...options.map((option) =>
        h("option", { value: option.value, selected: option.value === value }, option.label),
      ),
    ),
  );
}

function dateControl(label: string, value: string, key: "exploreFrom" | "exploreTo"): HTMLElement {
  return h(
    "label",
    { class: "atlas-field" },
    h("span", {}, label),
    h("input", {
      type: "date",
      value,
      on: { change: (event) => setExploreFilter(key, (event.target as HTMLInputElement).value) },
    }),
  );
}

function filterDrawer(): HTMLElement {
  const state = store.state;
  const overview = state.trendOverview;
  return h(
    "details",
    { class: "tier-filters" },
    h(
      "summary",
      {},
      h("span", {}, "Tune the tier list"),
      h("small", {}, `${overview?.fromDate ?? "Recent"} — ${overview?.toDate ?? "now"} · ${state.exploreMinPlayers}+ players`),
    ),
    h(
      "div",
      { class: "atlas-filter-fields" },
      selectControl(
        "Format",
        state.exploreFormat,
        [{ value: "", label: "All formats" }, ...(overview?.formats ?? []).map((format) => ({ value: format, label: format }))],
        (value) => setExploreFilter("exploreFormat", value),
      ),
      dateControl("From", state.exploreFrom, "exploreFrom"),
      dateControl("To", state.exploreTo, "exploreTo"),
      selectControl(
        "Event size",
        String(state.exploreMinPlayers),
        [
          { value: "0", label: "Any size" },
          { value: "16", label: "16+ players" },
          { value: "32", label: "32+ players" },
          { value: "64", label: "64+ players" },
        ],
        (value) => setExploreFilter("exploreMinPlayers", Number(value)),
      ),
      selectControl(
        "Trend interval",
        state.exploreBucket,
        [{ value: "week", label: "Weekly" }, { value: "month", label: "Monthly" }],
        (value) => setExploreFilter("exploreBucket", value),
      ),
    ),
  );
}

function trendChart(series: TrendSeries): HTMLElement {
  // The server decides what is worth plotting; keeping a second copy of that threshold
  // here would be two policies drifting apart with only one of them tested.
  const sampled = series.points.filter((point) => point.charted);
  const shell = h("div", { class: "dossier-chart" });
  if (sampled.length < 2) {
    return h("div", { class: "dossier-chart empty-chart" }, "Not enough complete lists to draw a stable trend yet.");
  }
  const width = 860;
  const height = 260;
  const pad = { top: 20, right: 20, bottom: 38, left: 46 };
  const maxShare = Math.max(0.05, ...sampled.map((point) => point.share));
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${series.name} share of complete tournament lists over time`);
  svg.classList.add("trend-chart");
  const x = (index: number) => pad.left + (index / Math.max(1, sampled.length - 1)) * (width - pad.left - pad.right);
  const y = (value: number) => height - pad.bottom - (value / maxShare) * (height - pad.top - pad.bottom);
  const add = (name: string, attrs: Record<string, string>): SVGElement => {
    const element = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, value));
    svg.appendChild(element);
    return element;
  };
  for (let step = 0; step <= 3; step += 1) {
    const value = (maxShare / 3) * step;
    const yy = y(value);
    add("line", { x1: String(pad.left), x2: String(width - pad.right), y1: String(yy), y2: String(yy), class: "chart-grid" });
    const label = add("text", { x: String(pad.left - 9), y: String(yy + 4), class: "chart-axis", "text-anchor": "end" });
    label.textContent = pct(value);
  }
  const d = sampled.map((point, index) => `${index ? "L" : "M"}${x(index)},${y(point.share)}`).join(" ");
  add("path", { d, fill: "none", class: "dossier-line" });
  sampled.forEach((point, index) => {
    const circle = add("circle", { cx: String(x(index)), cy: String(y(point.share)), r: "5", class: "dossier-point" });
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = `${point.period}: ${pct(point.share, 1)} · ${point.decks} of ${point.totalDecks} lists`;
    circle.appendChild(title);
  });
  const first = sampled[0];
  const last = sampled[sampled.length - 1];
  if (first && last) {
    const firstLabel = add("text", { x: String(pad.left), y: String(height - 12), class: "chart-axis" });
    firstLabel.textContent = new Date(`${first.period}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    const lastLabel = add("text", { x: String(width - pad.right), y: String(height - 12), class: "chart-axis", "text-anchor": "end" });
    lastLabel.textContent = new Date(`${last.period}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  shell.appendChild(svg);
  return shell;
}

function legendTile(row: RankedLegend): HTMLElement {
  const movement = row.trend ? row.trend.momentum : null;
  return h(
    "button",
    {
      class: "tier-card",
      type: "button",
      on: { click: () => row.trend ? void openLegend(row.legend.legendId) : undefined },
      disabled: !row.trend,
      aria: { label: `${row.legend.name}, ${row.trend ? `${pct(row.trend.share, 1)} of published lists` : "no complete lists in range"}` },
    },
    fullCard(row.legend.imageUrl, row.legend.name, "tier-card-art"),
    h(
      "span",
      { class: "tier-card-context" },
      h("strong", {}, row.legend.name),
      row.trend
        ? h(
            "span",
            {},
            `${row.trend.deckCount} lists · ${row.trend.eventCount} events`,
            movement === null
              ? null
              : h("b", { class: movement >= 0 ? "trend-up" : "trend-down" }, `${movement >= 0 ? " ↑" : " ↓"}${Math.abs(movement * 100).toFixed(1)} pts`),
          )
        : h("span", {}, "Uncharted in this range"),
    ),
  );
}

function tierRow(tier: Tier, rows: RankedLegend[]): HTMLElement | null {
  if (!rows.length) return null;
  const copy = TIER_COPY[tier];
  return h(
    "section",
    { class: `tier-row tier-${tier.toLowerCase()}` },
    h("header", { class: "tier-label" }, h("strong", {}, copy.title), h("span", {}, copy.note), h("small", {}, `${rows.length} legend${rows.length === 1 ? "" : "s"}`)),
    h("div", { class: "tier-cards" }, ...rows.map(legendTile)),
  );
}

function tierOverview(): HTMLElement {
  const { trendOverview: overview, smartLegends, exploreLoading, exploreError } = store.state;
  const ranked = rankLegends(smartLegends, overview?.series ?? []);
  const top = ranked.filter((row) => row.trend).slice(0, 3);
  return h(
    "div",
    { class: "explore-page tier-page" },
    h(
      "header",
      { class: "tier-hero" },
      h(
        "div",
        { class: "tier-hero-copy" },
        h("p", { class: "eyebrow" }, "The living field"),
        h("h1", {}, "Every legend. One field."),
        h("p", { class: "page-lede" }, "A full-card view of what is defining tournaments right now. Open any legend to see its champion builds, staples, trajectory, and the decks behind its tier."),
        h("p", { class: "tier-honesty" }, "Relative tournament presence—not a win-rate claim. Tiers combine published-list share, event breadth, and recent movement."),
      ),
      h("div", { class: "tier-hero-cards", aria: { hidden: "true" } }, ...top.map((row) => fullCard(row.legend.imageUrl, row.legend.name, "hero-card"))),
    ),
    overview
      ? h(
          "section",
          { class: "field-ribbon" },
          h("span", {}, h("strong", {}, String(smartLegends.length)), " legends"),
          // Both populations, because they differ: a list whose champion the source
          // never recorded is a published list that no share can be measured from, and
          // showing only the larger number invites the reader to divide by it.
          h(
            "span",
            {
              title:
                overview.chartedDeckCount < overview.publishedDeckCount
                  ? `${overview.publishedDeckCount - overview.chartedDeckCount} published ` +
                    "lists did not resolve to a champion, so no share is measured from them."
                  : "Every published list resolved to a champion.",
            },
            h("strong", {}, overview.chartedDeckCount.toLocaleString()),
            overview.chartedDeckCount < overview.publishedDeckCount
              ? ` of ${overview.publishedDeckCount.toLocaleString()} complete lists`
              : " complete lists",
          ),
          h("span", {}, h("strong", {}, String(overview.tournamentCount)), " tournaments"),
          h("span", {}, h("strong", {}, pct(overview.publishedCoverage)), " field coverage"),
        )
      : null,
    filterDrawer(),
    exploreError
      ? h("div", { class: "inline-error" }, h("strong", {}, "Couldn’t rebuild the field."), h("span", {}, exploreError), h("button", { type: "button", on: { click: () => void loadExplore() } }, "Try again"))
      : null,
    exploreLoading && !overview ? h("div", { class: "atlas-loading" }, "Laying out the field…") : null,
    overview
      ? h(
          "div",
          { class: `tier-board${exploreLoading ? " is-updating" : ""}` },
          ...(["S", "A", "B", "C", "U"] as Tier[]).map((tier) => tierRow(tier, ranked.filter((row) => row.tier === tier))),
        )
      : null,
  );
}

function contextCard(pairing: Pairing, label: string, onOpen?: () => void): HTMLElement {
  return h(
    "button",
    { class: "context-card", type: "button", disabled: !onOpen, on: onOpen ? { click: onOpen } : {} },
    fullCard(pairing.imageUrl, pairing.name, "context-card-art"),
    h("span", {}, h("strong", {}, pairing.name), h("small", {}, `${pct(pairing.share)} · ${pairing.decks} ${label}`)),
  );
}

function adoptionCard(card: CardAdoption): HTMLElement {
  return h(
    "article",
    { class: "context-card adoption-card" },
    fullCard(card.imageUrl, card.name, "context-card-art"),
    h("span", {}, h("strong", {}, card.name), h("small", {}, `${pct(card.inclusion)} of lists · ${card.averageCopies.toFixed(1)} copies`)),
  );
}

function deckCard(deck: TrendDeck): HTMLElement {
  const placement = deck.placement > 0 ? `${ordinal(deck.placement)} of ${deck.fieldSize || "?"}` : "Published list";
  return h(
    "article",
    { class: "evidence-deck" },
    h(
      "div",
      { class: "evidence-art-pair" },
      fullCard(deck.legendImageUrl, deck.legendName, "evidence-art legend-art"),
      fullCard(deck.championImageUrl, deck.championName, "evidence-art champion-art"),
    ),
    h(
      "div",
      { class: "evidence-body" },
      h("p", { class: "eyebrow" }, `${deck.tournamentDate} · ${placement}`),
      h("h3", {}, deck.name),
      h("p", { class: "evidence-identity" }, `${deck.legendName} · ${deck.championName}`),
      h("p", { class: "evidence-event" }, deck.tournamentName),
      h(
        "div",
        { class: "trend-deck-actions" },
        h("button", { type: "button", class: "primary", on: { click: () => void importMetaDeck(deck.deckId) } }, "Import full list"),
        h("button", { type: "button", class: "quiet-button", on: { click: () => void openTournament(deck.tournamentSlug) } }, "Open event"),
        deck.sourceUrl ? h("a", { href: deck.sourceUrl, target: "_blank", rel: "noopener" }, "Source ↗") : null,
      ),
    ),
  );
}

function dossierHeader(
  kind: string,
  name: string,
  imageUrl: string,
  domains: string[],
  mark: Tier | "CH",
  series: TrendSeries,
): HTMLElement {
  return h(
    "header",
    { class: "dossier-hero" },
    fullCard(imageUrl, name, "dossier-card"),
    h(
      "div",
      { class: "dossier-copy" },
      h("p", { class: "eyebrow" }, `${kind} field guide`),
      h(
        "div",
        { class: "dossier-title-line" },
        h(
          "span",
          { class: `dossier-tier ${mark === "CH" ? "is-champion" : `tier-${mark.toLowerCase()}`}` },
          mark === "U" ? "—" : mark,
        ),
        h("h1", {}, name),
      ),
      domainMarks(domains),
      h("p", { class: "page-lede" }, `${series.deckCount} complete lists across ${series.eventCount} tournaments. Open the cards below to move from ranking to the builds and evidence that created it.`),
      h("div", { class: "dossier-signal" }, confidence(series.confidence), h("span", {}, `${pct(series.share, 1)} of published lists`), series.momentum === null ? null : h("span", { class: series.momentum >= 0 ? "trend-up" : "trend-down" }, `${series.momentum >= 0 ? "Up" : "Down"} ${Math.abs(series.momentum * 100).toFixed(1)} points`)),
    ),
  );
}

function legendView(meta: LegendMeta): HTMLElement {
  return h(
    "div",
    { class: "explore-page dossier-page" },
    h("button", { class: "back-link", type: "button", on: { click: closeExploreDetail } }, "← All legends"),
    dossierHeader("Legend", meta.legendName, meta.imageUrl, meta.domains, tierFor(meta.legendId), meta.overview),
    h(
      "section",
      { class: "atlas-metrics dossier-metrics" },
      metric("Published-list share", pct(meta.overview.share, 1)),
      metric("Top 8 finishes", String(meta.topEight)),
      metric("Top 16 finishes", String(meta.topSixteen)),
      metric("Best finish", meta.bestPlacement ? `${ordinal(meta.bestPlacement)} of ${meta.bestFieldSize}` : "No placement"),
    ),
    h(
      "section",
      { class: "visual-section champion-section" },
      h("div", { class: "visual-section-head" }, h("div", {}, h("p", { class: "eyebrow" }, "Champion builds"), h("h2", {}, "The ways people are playing it")), h("p", {}, "Each champion is its own build context. Open one for its dedicated meta.")),
      h("div", { class: "context-card-grid" }, ...meta.champions.map((row) => contextCard(row, row.decks === 1 ? "list" : "lists", () => void openChampion(row.entityId)))),
    ),
    h(
      "section",
      { class: "visual-section" },
      h("div", { class: "visual-section-head" }, h("div", {}, h("p", { class: "eyebrow" }, "Shared core"), h("h2", {}, "Cards tying the builds together")), h("p", {}, "Champion cards are separated above; these are the recurring main-deck pieces.")),
      h("div", { class: "context-card-grid adoption-grid" }, ...meta.cards.map(adoptionCard)),
    ),
    h("section", { class: "visual-section trend-section" }, h("div", { class: "visual-section-head" }, h("div", {}, h("p", { class: "eyebrow" }, "Trajectory"), h("h2", {}, "Presence across the season"))), trendChart(meta.overview)),
    h("section", { class: "visual-section" }, h("div", { class: "visual-section-head" }, h("div", {}, h("p", { class: "eyebrow" }, "Deck evidence"), h("h2", {}, "Lists behind the tier"))), h("div", { class: "evidence-deck-grid" }, ...meta.recentDecks.map(deckCard))),
  );
}

function championView(meta: ChampionMeta): HTMLElement {
  return h(
    "div",
    { class: "explore-page dossier-page" },
    h("button", { class: "back-link", type: "button", on: { click: closeExploreDetail } }, "← All legends"),
    dossierHeader("Champion", meta.championName, meta.imageUrl, meta.domains, "CH", meta.overview),
    h(
      "section",
      { class: "atlas-metrics dossier-metrics" },
      metric("Published-list share", pct(meta.overview.share, 1)),
      metric("Top 8 finishes", String(meta.topEight)),
      metric("Top 16 finishes", String(meta.topSixteen)),
      metric("Best finish", meta.bestPlacement ? `${ordinal(meta.bestPlacement)} of ${meta.bestFieldSize}` : "No placement"),
    ),
    h(
      "section",
      { class: "visual-section" },
      h("div", { class: "visual-section-head" }, h("div", {}, h("p", { class: "eyebrow" }, "Legend homes"), h("h2", {}, "Where this champion appears"))),
      h("div", { class: "context-card-grid" }, ...meta.pairings.map((row) => contextCard(row, row.decks === 1 ? "list" : "lists", () => void openLegend(row.entityId)))),
    ),
    h(
      "section",
      { class: "visual-section" },
      h("div", { class: "visual-section-head" }, h("div", {}, h("p", { class: "eyebrow" }, "Core package"), h("h2", {}, "Cards that travel with it"))),
      h("div", { class: "context-card-grid adoption-grid" }, ...meta.cards.map(adoptionCard)),
    ),
    h("section", { class: "visual-section trend-section" }, h("div", { class: "visual-section-head" }, h("div", {}, h("p", { class: "eyebrow" }, "Trajectory"), h("h2", {}, "Presence across the season"))), trendChart(meta.overview)),
    h("section", { class: "visual-section" }, h("div", { class: "visual-section-head" }, h("div", {}, h("p", { class: "eyebrow" }, "Deck evidence"), h("h2", {}, "Recent complete lists"))), h("div", { class: "evidence-deck-grid" }, ...meta.recentDecks.map(deckCard))),
  );
}

function tournamentView(tournament: TournamentDetail): HTMLElement {
  const leading = tournament.champions.slice(0, 12);
  return h(
    "div",
    { class: "explore-page dossier-page" },
    h("button", { class: "back-link", type: "button", on: { click: () => store.set({ tournamentDetail: null }) } }, "← Back to guide"),
    h(
      "header",
      { class: "event-hero" },
      h("p", { class: "eyebrow" }, `${tournament.format} · ${tournament.date}`),
      h("h1", {}, tournament.name),
      h(
        "p",
        { class: "page-lede" },
        `${tournament.players.toLocaleString()} players · ` +
          `${tournament.knownDeckCount} complete published lists represented` +
          // Say when the champion distribution below rests on fewer lists than the
          // sentence above quotes, rather than letting a reader assume they match.
          (tournament.chartedDeckCount < tournament.knownDeckCount
            ? `, ${tournament.chartedDeckCount} of which named a champion.`
            : "."),
      ),
      h("div", { class: "dossier-signal" }, confidence(tournament.confidence), h("span", {}, `${pct(tournament.publishedCoverage)} list coverage`)),
    ),
    h("aside", { class: "coverage-note" }, h("strong", {}, "This is a list sample, not the entire room."), h("span", {}, "Missing deck lists remain unknown. The cards and shares below describe only complete published lists.")),
    h(
      "section",
      { class: "visual-section" },
      h("div", { class: "visual-section-head" }, h("div", {}, h("p", { class: "eyebrow" }, "At this event"), h("h2", {}, "Champion spread"))),
      h("div", { class: "event-champion-grid" }, ...leading.map((row) => h("button", { type: "button", on: { click: () => void openChampion(row.entityId) } }, h("strong", {}, row.name), h("span", {}, `${row.decks} ${row.decks === 1 ? "list" : "lists"} · ${pct(row.share)}`)))),
    ),
    h("section", { class: "visual-section" }, h("div", { class: "visual-section-head" }, h("div", {}, h("p", { class: "eyebrow" }, "Known lists"), h("h2", {}, "Decks from the tournament"))), h("div", { class: "evidence-deck-grid" }, ...tournament.decks.map(deckCard))),
  );
}

export function renderExplore(root: HTMLElement): void {
  const { championMeta, legendMeta, tournamentDetail } = store.state;
  replace(
    root,
    tournamentDetail
      ? tournamentView(tournamentDetail)
      : championMeta
        ? championView(championMeta)
        : legendMeta
          ? legendView(legendMeta)
          : tierOverview(),
  );
}
