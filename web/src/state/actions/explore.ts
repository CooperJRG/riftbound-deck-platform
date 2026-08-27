/**
 * Explore: the tier wall, the card wall, and the drill-downs behind both.
 *
 * The filters are shared between the two modes but the data is not, so a refresh has to
 * follow the mode -- reloading only the legends is why changing a date while reading the
 * card wall used to do nothing at all.
 */

import { api } from "../../api/client";
import type { TrendBucket } from "../../api/types";
import { scrollToTop } from "../../ui/scroll";
import { store, type ExploreMode } from "../store";

function exploreParams(): {
  from?: string;
  to?: string;
  format?: string;
  minPlayers: number;
  bucket: TrendBucket;
} {
  const state = store.state;
  return {
    ...(state.exploreFrom ? { from: state.exploreFrom } : {}),
    ...(state.exploreTo ? { to: state.exploreTo } : {}),
    ...(state.exploreFormat ? { format: state.exploreFormat } : {}),
    minPlayers: state.exploreMinPlayers,
    bucket: state.exploreBucket,
    ...(state.exploreRange ? { range: state.exploreRange } : {}),
  };
}

export async function loadExplore(): Promise<void> {
  store.set({ exploreLoading: true, exploreError: "", championMeta: null, legendMeta: null, tournamentDetail: null });
  try {
    const [trendOverview, smartLegends] = await Promise.all([
      // The tier wall ranks the whole field, so it asks for the legends this window
      // cannot see as well as the ones it can.
      api.trendOverview({ dimension: "legend", ...exploreParams(), limit: 50, includeDormant: true }),
      store.state.smartLegends.length ? Promise.resolve(store.state.smartLegends) : api.smartLegends(),
    ]);
    store.set({ trendOverview, smartLegends, smartLegendsLoaded: true, exploreLoading: false });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    store.set({ exploreLoading: false, exploreError: message });
  }
}

export function setExploreFilter(
  key: "exploreFormat" | "exploreFrom" | "exploreTo" | "exploreMinPlayers" | "exploreBucket",
  value: string | number,
): void {
  // Picking a date by hand means leaving the preset behind, or the preset would
  // override the date and the control would look broken.
  const clearRange = key === "exploreFrom" || key === "exploreTo" ? { exploreRange: "" } : {};
  store.set({ [key]: value, ...clearRange } as Partial<typeof store.state>);
  void refreshExplore();
}

/**
 * Reload whichever view is on screen.
 *
 * The filters are shared between the two Explore modes but the data is not, so a
 * refresh has to follow the mode. Reloading only the legends meant changing the date
 * range while reading the card wall did nothing at all, which reads as a broken
 * control rather than a missing branch.
 */
function refreshExplore(): Promise<void> {
  return store.state.exploreMode === "cards" ? loadCardTrends() : loadExplore();
}

/**
 * Jump the window to a whole span rather than making somebody pick two dates.
 *
 * `days` of 0 means the entire archive. Most of what has been harvested sits outside
 * the default ninety days -- 333 events against 58 -- and a range you have to type is
 * a range nobody uses, so the history may as well not exist.
 */
export function setExploreRange(range: string): void {
  // Sent as a request, not as dates. Resolving "all" here would mean knowing the
  // archive's span first, and when the page had not loaded it yet the range came out
  // empty -- which the server reads as "use the default", i.e. ninety days. "All time"
  // silently meant "90 days" whenever you clicked it before the first load finished.
  const days = Number(range);
  store.set({
    exploreRange: range,
    // An explicit range replaces any hand-picked dates; leaving them set would win.
    exploreFrom: "",
    exploreTo: "",
    // Weekly buckets across a year is a chart nobody can read.
    exploreBucket: range === "all" || (Number.isFinite(days) && days > 180) ? "month" : "week",
  });
  void refreshExplore();
}

export async function openChampion(championId: string): Promise<void> {
  scrollToTop();
  store.set({ exploreLoading: true, exploreError: "", legendMeta: null, tournamentDetail: null });
  try {
    const championMeta = await api.championTrend(championId, exploreParams());
    store.set({ championMeta, exploreLoading: false });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    store.set({ exploreLoading: false, exploreError: message });
  }
}

export async function openLegend(legendId: string): Promise<void> {
  scrollToTop();
  store.set({ exploreLoading: true, exploreError: "", championMeta: null, tournamentDetail: null });
  try {
    const legendMeta = await api.legendTrend(legendId, exploreParams());
    store.set({ legendMeta, exploreLoading: false });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    store.set({ exploreLoading: false, exploreError: message });
  }
}

export async function openTournament(slug: string): Promise<void> {
  scrollToTop();
  store.set({ exploreLoading: true, exploreError: "" });
  try {
    const tournamentDetail = await api.tournamentDetail(slug);
    store.set({ tournamentDetail, exploreLoading: false });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    store.set({ exploreLoading: false, exploreError: message });
  }
}

export function closeExploreDetail(): void {
  scrollToTop();
  store.set({ championMeta: null, legendMeta: null, tournamentDetail: null });
}

/**
 * The card wall.
 *
 * Tracked separately from legends and champions because the numbers mean different
 * things: a champion's share is a partition of the field, a card's adoption is not.
 * Keeping them in different state, fetched from different endpoints, is what stops one
 * being rendered with the other's labels.
 */
export async function loadCardTrends(): Promise<void> {
  store.set({ exploreLoading: true, exploreError: "", cardDetail: null });
  try {
    const cardTrends = await api.cardTrends({
      ...exploreParams(),
      ...(store.state.exploreCardType ? { cardType: store.state.exploreCardType } : {}),
      limit: 60,
    });
    store.set({ cardTrends, exploreLoading: false });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    store.set({ exploreLoading: false, exploreError: message });
  }
}

export async function openCard(cardId: string): Promise<void> {
  store.set({
    exploreLoading: true, exploreError: "",
    legendMeta: null, championMeta: null, tournamentDetail: null,
  });
  try {
    const cardDetail = await api.cardTrendDetail(cardId, exploreParams());
    store.set({ cardDetail, exploreLoading: false });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    store.set({ exploreLoading: false, exploreError: message });
  }
}

export function setExploreCardType(cardType: string): Promise<void> {
  store.set({ exploreCardType: cardType });
  return loadCardTrends();
}

export function closeCard(): void {
  store.set({ cardDetail: null });
}

export async function setExploreMode(mode: ExploreMode): Promise<void> {
  store.set({ exploreMode: mode, cardDetail: null });
  if (mode === "cards" && !store.state.cardTrends) await loadCardTrends();
}
