import type {
  CardAdoption,
  LegendRecord,
  Matchup,
  MatchupBasis,
  ChampionMeta,
  LegendChoice,
  LegendMeta,
  Pairing,
  TournamentDetail,
  TrendDeck,
  Performance,
  PerformanceBasis,
  Rank,
  TrendSeries,
} from "../api/types";
import {
  closeExploreDetail,
  closeLegendMatchups,
  openLegendMatchups,
  importMetaDeck,
  loadExplore,
  openChampion,
  openLegend,
  openTournament,
  setExploreFilter,
  setExploreMode,
  setExploreRange,
} from "../state/actions";
import { store, type ExploreMode } from "../state/store";
import { shareButton } from "./share";
import { h, replace } from "../ui/dom";
import { cardView, cardWall } from "./cardMeta";

type Tier = "S" | "A" | "B" | "C" | "D" | "U";

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
  D: { title: "D", note: "Rarely seen in the field" },
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

/**
 * Join the legend catalogue to the server's ranking.
 *
 * This function used to *compute* the ranking -- weights, tier cut points and all --
 * which made it the only piece of ranking policy outside the server and the only one
 * with no tests. It now does nothing but look the answer up and keep the order the
 * server sent, so a rating shown here and a rating shown anywhere else cannot differ.
 *
 * The tier list has no "uncharted" bucket any more. A legend with no lists in range
 * arrives ranked, scored 0, ordered against the other dormant ones by what the archive
 * still knows -- so shortening the range reorders the wall instead of emptying part of
 * it. `rank.ranked` is false for those, and the card says so rather than presenting a
 * zero as a measurement.
 */
function rankLegends(legends: LegendChoice[], trends: TrendSeries[]): RankedLegend[] {
  const byId = new Map(legends.map((legend) => [legend.legendId, legend]));
  const seen = new Set<string>();
  const rows: RankedLegend[] = [];

  for (const trend of trends) {
    const legend = byId.get(trend.entityId);
    if (!legend || !trend.rank) continue;
    seen.add(trend.entityId);
    rows.push({ legend, trend, score: trend.rank.score, tier: trend.rank.tier });
  }
  // A legend the meta has never heard of at all -- not dormant, absent from the
  // archive. It cannot be scored against a field it has never been in, so it keeps the
  // uncharted marker rather than being handed a zero it did not earn.
  for (const legend of legends) {
    if (seen.has(legend.legendId)) continue;
    rows.push({ legend, trend: null, score: -1, tier: "U" as Tier });
  }
  return rows;
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

const RANGES: { label: string; range: string }[] = [
  { label: "30 days", range: "30" },
  { label: "90 days", range: "90" },
  { label: "6 months", range: "182" },
  { label: "12 months", range: "365" },
  { label: "All time", range: "all" },
];

/**
 * The archive, said out loud.
 *
 * Most of what has been harvested sits outside the default window -- 333 events against
 * the 58 the last ninety days hold -- and there was nothing on the page to suggest it
 * existed. A range you have to type is a range nobody uses.
 */
export function rangeBar(overview: {
  fromDate: string; toDate: string; archiveFrom: string; archiveTo: string;
  archiveTournamentCount: number; tournamentCount: number;
} | null): HTMLElement | null {
  if (!overview) return null;
  const showingAll = overview.fromDate <= overview.archiveFrom;
  return h(
    "div",
    { class: "range-bar" },
    h(
      "div",
      { class: "range-chips" },
      ...RANGES.map((entry) =>
        h(
          "button",
          {
            // Without this a click that changes nothing visible looks like a dead
            // control, which is how the last one got reported.
            class: `chip-toggle${store.state.exploreRange === entry.range ? " is-active" : ""}`,
            type: "button",
            aria: { pressed: String(store.state.exploreRange === entry.range) },
            on: { click: () => setExploreRange(entry.range) },
          },
          entry.label,
        ),
      ),
    ),
    h(
      "p",
      { class: "range-note" },
      `Showing ${overview.tournamentCount} of ${overview.archiveTournamentCount} tournaments`,
      showingAll
        ? " — the whole archive."
        : `. The archive goes back to ${overview.archiveFrom}.`,
    ),
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

/**
 * The win rate, or an honest reason there isn't one.
 *
 * Deliberately *beside* the tier rather than inside it. The tier is presence and the
 * chip is performance, and the two orderings genuinely disagree -- Rengar is 13th by
 * presence and 3rd by win rate. Folding the chip into the tier score would average
 * away exactly the disagreement that makes it worth showing.
 *
 * Nothing here re-derives a threshold. `shown` and `withheldDetail` are decided by the
 * server, next to the tests that pin them.
 */
function winRateChip(performance: Performance | null): HTMLElement | null {
  if (!performance) return null;
  if (!performance.shown) {
    return h(
      "span",
      { class: "winrate-chip is-thin", title: performance.withheldDetail },
      `${performance.matches} matches`,
    );
  }
  return h(
    "span",
    {
      class: `winrate-chip${performance.separated ? " is-separated" : ""}`,
      title:
        `${pct(performance.winRate, 1)} of ${performance.decisive} decisive matches. ` +
        `95% confident the true rate is ${pct(performance.intervalLow, 1)}–` +
        `${pct(performance.intervalHigh, 1)}, from ${performance.events} events and ` +
        `${performance.pilots} pilots.`,
    },
    `${pct(performance.winRate, 1)} won`,
  );
}

/**
 * The rating, and its rank in the field.
 *
 * The score was previously computed, used to sort the wall, and then thrown away -- the
 * reader could see that one legend sat above another but never by how much. Showing the
 * number turns the tier letter from the only output into a grouping of a visible scale.
 *
 * A dormant legend shows `0` with a muted treatment and says why on hover, because a
 * zero that means "not played here" must not read the same as a measured floor.
 */
function ratingBadge(rank: Rank | null): HTMLElement | null {
  if (!rank) return null;
  return h(
    "span",
    {
      class: `tier-rating${rank.ranked ? "" : " is-dormant"}`,
      title: rank.ranked
        ? `${rank.summary}. Rank ${rank.position} in this range.`
        : rank.summary,
    },
    h("b", {}, rank.ranked ? String(Math.round(rank.score)) : "0"),
    h("i", {}, `#${rank.position}`),
  );
}

function legendTile(row: RankedLegend): HTMLElement {
  const rank = row.trend?.rank ?? null;
  const dormant = rank !== null && !rank.ranked;
  return h(
    "button",
    {
      class: `tier-card${dormant ? " is-dormant" : ""}`,
      type: "button",
      on: { click: () => row.trend ? void openLegend(row.legend.legendId) : undefined },
      disabled: !row.trend,
      aria: {
        label: [
          row.legend.name,
          rank ? `rated ${Math.round(rank.score)} of 100, rank ${rank.position}` : "",
          rank && !rank.ranked
            ? "no lists in this range"
            : row.trend
              ? `${pct(row.trend.share, 1)} of published lists`
              : "no complete lists in range",
          // Colour and position are never the only carrier of a claim this strong.
          row.trend?.performance?.shown
            ? `wins ${pct(row.trend.performance.winRate, 1)} of ${row.trend.performance.decisive} matches`
            : "",
        ].filter(Boolean).join(", "),
      },
    },
    fullCard(row.legend.imageUrl, row.legend.name, "tier-card-art"),
    h(
      "span",
      { class: "tier-card-context" },
      h("strong", {}, row.legend.name),
      ratingBadge(rank),
      dormant
        ? h(
            "span",
            {},
            rank.lastSeen ? `Last seen ${rank.lastSeen}` : "Not seen in this range",
          )
        : row.trend
          // Share and momentum are both already inside the rating above, and the card
          // was printing all three: a 0-100 number, then the share it is mostly made of,
          // then the delta that nudges it. The counts stay because they are the sample
          // behind the rating rather than a restatement of it.
          ? h("span", {}, `${row.trend.deckCount} lists · ${row.trend.eventCount} events`)
          : h("span", {}, "Uncharted in this range"),
      winRateChip(row.trend?.performance ?? null),
    ),
  );
}

function tierRow(tier: Tier, rows: RankedLegend[]): HTMLElement | null {
  if (!rows.length) return null;
  const copy = TIER_COPY[tier];
  return h(
    "details",
    { class: `tier-row tier-${tier.toLowerCase()}`, open: tier === "S" || tier === "A" || tier === "B" },
    h("summary", { class: "tier-label" }, h("strong", {}, copy.title), h("span", {}, copy.note), h("small", {}, `${rows.length} legend${rows.length === 1 ? "" : "s"}`)),
    h("div", { class: "tier-cards" }, ...rows.map(legendTile)),
  );
}

/**
 * What the win rates are a rate *of*.
 *
 * On the page rather than in a tooltip, on purpose. The difference between "this deck
 * wins 62% of its games" and "this deck wins 62% of the games we can see" is the whole
 * honesty of the column, and a caveat a reader has to hover for is a caveat most
 * readers never meet. Every sentence here is server-computed, so it cannot drift from
 * the numbers it qualifies.
 */
function performanceBasisNote(basis: PerformanceBasis | null): HTMLElement | null {
  if (!basis || basis.totalMatches <= 0) return null;
  return h(
    "p",
    { class: "winrate-basis" },
    h("strong", {}, `${basis.eraName}: `),
    `${basis.entitiesShown} of ${basis.entitiesMeasured} have enough matches to rank. `,
    basis.caveat,
    // The era boundary was derived from the archive, not read off an announcement.
    // Say so until it is, rather than letting a derived date pass as a cited one.
    basis.eraCited
      ? null
      : h(
          "span",
          { class: "winrate-basis-note", title: basis.eraEvidence },
          ` Era boundary from ${basis.eraFrom}, derived from the archive rather than a published announcement.`,
        ),
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
        h("p", { class: "eyebrow" }, "RiftDesk · live meta"),
        h("h1", {}, "Every legend. One field."),
        h("p", { class: "page-lede" }, "A full-card view of what is defining tournaments right now. Open any legend to see its champion builds, staples, trajectory, and the decks behind its tier."),
        // The tier is still presence and only presence: the ranking formula was
        // deliberately left alone when win rates arrived. Folding performance into the
        // tier would hide the disagreement between the two, which is the most useful
        // thing on this page.
        h("p", { class: "tier-honesty" }, "Tiers are relative tournament presence—published-list share, event breadth, and recent movement. Win rates are measured separately and shown where the sample supports one; a deck can sit low in the field and still win most of its matches."),
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
          overview.performanceBasis && overview.performanceBasis.totalMatches > 0
            ? h(
                "span",
                {
                  title:
                    `${overview.performanceBasis.entitiesShown} legends have enough ` +
                    `matches to rank; ${overview.performanceBasis.entitiesWithheld} do not yet.`,
                },
                h("strong", {}, overview.performanceBasis.totalMatches.toLocaleString()),
                " matches recorded",
              )
            : null,
        )
      : null,
    performanceBasisNote(overview?.performanceBasis ?? null),
    filterDrawer(),
    exploreError
      ? h("div", { class: "inline-error" }, h("strong", {}, "Couldn’t rebuild the field."), h("span", {}, exploreError), h("button", { type: "button", on: { click: () => void loadExplore() } }, "Try again"))
      : null,
    exploreLoading && !overview ? h("div", { class: "atlas-loading" }, "Laying out the field…") : null,
    overview
      ? h(
          "div",
          { class: `tier-board${exploreLoading ? " is-updating" : ""}` },
          ...(["S", "A", "B", "C", "D", "U"] as Tier[]).map((tier) =>
            tierRow(tier, ranked.filter((row) => row.tier === tier)),
          ),
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
      h("p", { class: "eyebrow" }, `${kind} meta desk`),
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
    h(
      "div",
      { class: "detail-bar" },
      h("button", { class: "back-link", type: "button", on: { click: closeExploreDetail } }, "← All legends"),
      shareButton("this legend"),
    ),
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
    h(
      "div",
      { class: "detail-bar" },
      h("button", { class: "back-link", type: "button", on: { click: closeExploreDetail } }, "← All legends"),
      shareButton("this champion"),
    ),
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
    h(
      "div",
      { class: "detail-bar" },
      h("button", { class: "back-link", type: "button", on: { click: () => store.set({ tournamentDetail: null }) } }, "← Back to guide"),
      shareButton("this event"),
    ),
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

/**
 * The two questions Explore answers, kept apart.
 *
 * "What is winning" and "what is being played" are measured differently -- one is a
 * share of the field, the other an adoption rate that does not sum to it -- so they get
 * separate modes rather than a shared table with a swapped column.
 */
/**
 * Matchups: what beats what, from recorded matches.
 *
 * The third question Explore answers, and the one the other two cannot. Presence is a
 * share of published lists; adoption is a rate within them; a matchup is the result of
 * an actual game against a named opponent. They come from different populations, so the
 * basis line is not decoration -- it is the difference between "wins 57% of its games"
 * and "wins 57% of the games this source recorded, over its own set window".
 *
 * Every rate is rendered with its interval and none is rendered without one. A matchup
 * that has not cleared the bar shows its sample and the threshold it missed, phrased
 * server-side, rather than a number in small type.
 */
function winPill(
  rate: number,
  low: number,
  high: number,
  separated: boolean,
): HTMLElement {
  const tone = !separated ? "is-even" : low > 0.5 ? "is-good" : "is-bad";
  return h(
    "span",
    { class: `wr-pill ${tone}`, title: `95% interval ${pct(low, 1)} to ${pct(high, 1)}` },
    h("b", {}, pct(rate, 1)),
    h("i", {}, `${pct(low, 0)}-${pct(high, 0)}`),
  );
}

function unratedPill(matches: number): HTMLElement {
  return h(
    "span",
    { class: "wr-pill is-unrated", title: "Not enough matches to publish a rate" },
    h("b", {}, "-"),
    h("i", {}, `${matches}`),
  );
}

function basisLine(basis: MatchupBasis): HTMLElement {
  const credit = basis.attribution;
  return h(
    "p",
    { class: "matchup-basis muted small" },
    h("span", {}, basis.summary),
    credit && credit.url
      ? h("a", { href: credit.url, target: "_blank", rel: "noopener" }, ` ${credit.source} \u2197`)
      : null,
    basis.sourceLabel ? h("em", {}, ` ${basis.sourceLabel}.`) : null,
  );
}

function legendRow(row: LegendRecord): HTMLElement {
  return h(
    "button",
    {
      class: `matchup-row${row.shown ? "" : " is-unrated"}`,
      type: "button",
      title: `Open the matchup spread for ${row.name}`,
      on: { click: () => void openLegendMatchups(row.legendId) },
    },
    fullCard(row.imageUrl, row.name, "matchup-row-art"),
    h(
      "span",
      { class: "matchup-row-body" },
      h("strong", {}, row.name),
      h("small", {}, row.summary),
    ),
    row.shown
      ? winPill(row.winRate, row.intervalLow, row.intervalHigh, row.separated)
      : unratedPill(row.matches),
  );
}

function matchupRow(row: Matchup): HTMLElement {
  return h(
    "article",
    { class: `matchup-cell${row.shown ? "" : " is-unrated"}` },
    h(
      "span",
      { class: "matchup-cell-body" },
      h("strong", {}, row.opponentName),
      h("small", {}, row.shown ? row.summary : row.withheldDetail),
    ),
    row.shown
      ? winPill(row.winRate, row.intervalLow, row.intervalHigh, row.separated)
      : unratedPill(row.matches),
  );
}

function matchupOverview(): HTMLElement {
  const { matchups, matchupsLoading } = store.state;
  if (matchupsLoading && !matchups) {
    return h("div", { class: "explore-page" }, h("p", { class: "muted" }, "Loading matchups..."));
  }
  if (!matchups || !matchups.available) {
    return h(
      "div",
      { class: "explore-page" },
      h("p", { class: "eyebrow" }, "Matchups"),
      h("h2", {}, "No matchup data yet"),
      h(
        "p",
        { class: "muted small" },
        "The matchup table is harvested alongside the meta snapshot. Run a refresh and it will appear here.",
      ),
    );
  }
  return h(
    "div",
    { class: "explore-page matchup-page" },
    h(
      "header",
      { class: "visual-section-head" },
      h(
        "div",
        {},
        h("p", { class: "eyebrow" }, "Recorded matches"),
        h("h2", {}, "Legend matchups"),
        h(
          "p",
          { class: "muted small" },
          "What actually beat what. Every rate carries its 95% interval, and a legend counts as favoured only when the whole interval clears even.",
        ),
      ),
    ),
    basisLine(matchups.basis),
    h("div", { class: "matchup-list" }, ...matchups.legends.map(legendRow)),
  );
}

function legendMatchupView(): HTMLElement {
  const detail = store.state.legendMatchups;
  if (!detail) return matchupOverview();
  const rated = detail.matchups.filter((m) => m.shown);
  const unrated = detail.matchups.filter((m) => !m.shown);
  return h(
    "div",
    { class: "explore-page matchup-page" },
    h(
      "button",
      { class: "quiet-button", type: "button", on: { click: closeLegendMatchups } },
      "\u2190 All legends",
    ),
    h(
      "header",
      { class: "dossier-hero" },
      fullCard(detail.imageUrl, detail.name, "dossier-card"),
      h(
        "div",
        { class: "dossier-copy" },
        h("p", { class: "eyebrow" }, "Matchup spread"),
        h("h1", {}, detail.name),
        detail.record
          ? h("p", { class: "page-lede" }, detail.record.summary)
          : h("p", { class: "muted small" }, "No overall record for this legend."),
      ),
    ),
    basisLine(detail.basis),
    rated.length
      ? h(
          "section",
          { class: "visual-section" },
          h(
            "div",
            { class: "visual-section-head" },
            h(
              "div",
              {},
              h("h2", {}, "Rated matchups"),
              h(
                "p",
                { class: "muted small" },
                "Hardest first, ordered by the optimistic end of the interval so a thin unlucky sample does not read as a bad matchup.",
              ),
            ),
          ),
          h("div", { class: "matchup-grid" }, ...rated.map(matchupRow)),
        )
      : h("p", { class: "muted small" }, "No matchup for this legend has cleared the bar yet."),
    unrated.length
      ? h(
          "details",
          { class: "matchup-unrated" },
          h("summary", {}, `${unrated.length} more without enough matches yet`),
          h("div", { class: "matchup-grid" }, ...unrated.map(matchupRow)),
        )
      : null,
  );
}

function modeSwitch(): HTMLElement {
  const current = store.state.exploreMode;
  const tab = (mode: ExploreMode, label: string, note: string) =>
    h(
      "button",
      {
        class: `mode-tab${current === mode ? " is-active" : ""}`,
        type: "button",
        aria: { pressed: String(current === mode) },
        on: { click: () => void setExploreMode(mode) },
      },
      h("strong", {}, label),
      h("span", {}, note),
    );
  return h(
    "nav",
    { class: "mode-switch", aria: { label: "Explore mode" } },
    tab("legends", "Legends & champions", "What is winning"),
    tab("cards", "Cards", "What is being played"),
    tab("matchups", "Matchups", "What beats what"),
  );
}

export function renderExplore(root: HTMLElement): void {
  const { championMeta, legendMeta, tournamentDetail, exploreMode, cardDetail } = store.state;

  // A drill-down owns the page; the switch belongs to the overviews it came from.
  if (tournamentDetail) return replace(root, tournamentView(tournamentDetail));
  if (championMeta) return replace(root, championView(championMeta));
  if (legendMeta) return replace(root, legendView(legendMeta));
  if (exploreMode === "cards" && cardDetail) return replace(root, cardView(cardDetail));

  // Matchups do not honour the date filters -- they are an aggregate computed over
  // the source's own set window -- so the range bar is left off rather than sitting
  // above numbers it cannot change.
  if (exploreMode === "matchups") {
    return replace(root, modeSwitch(), legendMatchupView());
  }

  replace(
    root,
    modeSwitch(),
    rangeBar(exploreMode === "cards" ? store.state.cardTrends : store.state.trendOverview),
    exploreMode === "cards" ? cardWall() : tierOverview(),
  );
}
