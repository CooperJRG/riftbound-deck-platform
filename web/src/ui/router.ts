/**
 * Addressable pages.
 *
 * Every view worth linking to has a URL, and the URL is enough to rebuild it. That
 * makes the back button work, makes a reload land where you were, and -- the reason it
 * exists -- makes a page something you can paste to somebody else.
 *
 * The sync runs one way at a time, guarded, because the two directions are not
 * symmetrical:
 *
 * * **URL to state** happens on load and on `popstate`. It calls the same actions the
 *   buttons call, so a link and a click reach the same place by the same path.
 * * **State to URL** happens after every render. It *derives* the address from what is
 *   on screen rather than asking each action to remember to update it -- there are
 *   thirty-odd actions and any one of them forgetting would leave a stale address in
 *   the bar, which is worse than none at all.
 *
 * Deck links carry the deck itself. A deck somebody built is not on the server for
 * anyone else to read, so `/deck?...` spells the list out in card ids -- which are
 * already URL-safe, and which make the link legible: you can see it is an Irelia deck
 * without opening it.
 */

import type { DeckPayload } from "../api/types";
import type { DeckSearchSort, ExploreMode, ViewName } from "../state/store";

export type Route =
  | { name: "find" }
  | { name: "smartSession"; sessionId: string }
  | { name: "explore"; mode: ExploreMode }
  | { name: "legend"; legendId: string }
  | { name: "champion"; championId: string }
  | { name: "card"; cardId: string }
  | { name: "event"; slug: string }
  | { name: "archetype"; archetypeId: string }
  | { name: "build" }
  | { name: "decks" }
  | { name: "search"; cardIds: string[]; sort: DeckSearchSort }
  | { name: "savedDeck"; deckId: string }
  | { name: "metaDeck"; deckId: string }
  | { name: "sharedDeck"; deck: DeckPayload };

/**
 * The field size Explore filters to unless told otherwise.
 *
 * Kept here as well as in the store so the router can leave a default out of the
 * address. Writing it produces `?players=16` on every Explore link, which is noise on
 * a link people are meant to paste -- and omitting it is safe because a URL that says
 * nothing about a filter lets the store's own default stand.
 */
export const DEFAULT_MIN_PLAYERS = 16;

/** Explore's filters ride along on any Explore route, so a filtered view is shareable. */
export interface ExploreQuery {
  range?: string;
  format?: string;
  minPlayers?: number;
}

export interface Location {
  route: Route;
  explore: ExploreQuery;
}

const HOME: Route = { name: "find" };

/** Which top-level view a route belongs to, for the tab strip. */
export function viewFor(route: Route): ViewName {
  switch (route.name) {
    case "find":
    case "smartSession":
      return "find";
    case "explore":
    case "legend":
    case "champion":
    case "card":
    case "event":
    case "archetype":
      return "explore";
    case "decks":
      return "decks";
    case "search":
      return "search";
    default:
      return "build";
  }
}

// -- deck <-> query string ----------------------------------------------------

/** ``id:3,id:2`` -- counts omitted when they are 1, which most zones are. */
function packCounts(counts: Record<string, number>): string {
  return Object.entries(counts)
    .filter(([, n]) => n > 0)
    .map(([id, n]) => (n === 1 ? id : `${id}:${n}`))
    .join(",");
}

function unpackCounts(raw: string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const part of raw.split(",")) {
    const entry = part.trim();
    if (!entry) continue;
    const [id, count] = entry.split(":");
    const key = (id ?? "").trim();
    if (!key) continue;
    const n = count ? Number.parseInt(count, 10) : 1;
    if (Number.isFinite(n) && n > 0) out[key] = (out[key] ?? 0) + n;
  }
  return out;
}

export function deckToQuery(deck: DeckPayload): URLSearchParams {
  const params = new URLSearchParams();
  if (deck.name && deck.name !== "Untitled Deck") params.set("n", deck.name);
  if (deck.format && deck.format !== "constructed") params.set("f", deck.format);
  if (deck.legendId) params.set("l", deck.legendId);
  if (deck.championId) params.set("c", deck.championId);
  const main = packCounts(deck.main);
  if (main) params.set("m", main);
  const runes = packCounts(deck.runes);
  if (runes) params.set("r", runes);
  if (deck.battlefields.length) params.set("b", deck.battlefields.join(","));
  const side = packCounts(deck.sideboard);
  if (side) params.set("s", side);
  return params;
}

export function deckFromQuery(params: URLSearchParams): DeckPayload {
  return {
    name: params.get("n") || "Shared deck",
    format: params.get("f") || "constructed",
    legendId: params.get("l") || "",
    championId: params.get("c") || "",
    main: unpackCounts(params.get("m") || ""),
    runes: unpackCounts(params.get("r") || ""),
    battlefields: (params.get("b") || "").split(",").map((s) => s.trim()).filter(Boolean),
    sideboard: unpackCounts(params.get("s") || ""),
  };
}

// -- parsing ------------------------------------------------------------------

function exploreFrom(params: URLSearchParams): ExploreQuery {
  const query: ExploreQuery = {};
  const range = params.get("range");
  if (range) query.range = range;
  const format = params.get("format");
  if (format) query.format = format;
  const players = params.get("players");
  if (players && Number.isFinite(Number(players))) query.minPlayers = Number(players);
  return query;
}

export function parseLocation(pathname: string, search: string): Location {
  const params = new URLSearchParams(search);
  const explore = exploreFrom(params);
  const parts = pathname.split("/").filter(Boolean).map(decodeURIComponent);
  const [head, second, third] = parts;

  if (!head) return { route: HOME, explore };

  if (head === "explore") {
    if (second === "legend" && third) return { route: { name: "legend", legendId: third }, explore };
    if (second === "champion" && third) return { route: { name: "champion", championId: third }, explore };
    if (second === "card" && third) return { route: { name: "card", cardId: third }, explore };
    if (second === "event" && third) return { route: { name: "event", slug: third }, explore };
    if (second === "archetype" && third) return { route: { name: "archetype", archetypeId: third }, explore };
    const mode: ExploreMode = second === "cards" ? "cards" : "legends";
    return { route: { name: "explore", mode }, explore };
  }

  if (head === "meta" && second === "deck" && third) {
    return { route: { name: "metaDeck", deckId: third }, explore };
  }

  if (head === "deck") {
    return { route: { name: "sharedDeck", deck: deckFromQuery(params) }, explore };
  }

  if (head === "decks") {
    return second
      ? { route: { name: "savedDeck", deckId: second }, explore }
      : { route: { name: "decks" }, explore };
  }

  if (head === "search") {
    const cardIds = (params.get("cards") || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const sort: DeckSearchSort = params.get("sort") === "recency" ? "recency" : "rank";
    return { route: { name: "search", cardIds, sort }, explore };
  }

  if (head === "build") return { route: { name: "build" }, explore };
  if (head === "find") {
    return second
      ? { route: { name: "smartSession", sessionId: second }, explore }
      : { route: HOME, explore };
  }

  // An address we do not recognise is the front page, not an error screen. A link that
  // has rotted should still land somewhere useful.
  return { route: HOME, explore };
}

// -- writing ------------------------------------------------------------------

function exploreSuffix(explore: ExploreQuery): string {
  const params = new URLSearchParams();
  if (explore.range) params.set("range", explore.range);
  if (explore.format) params.set("format", explore.format);
  if (explore.minPlayers && explore.minPlayers !== DEFAULT_MIN_PLAYERS) {
    params.set("players", String(explore.minPlayers));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function pathFor(route: Route, explore: ExploreQuery = {}): string {
  const enc = encodeURIComponent;
  switch (route.name) {
    case "find":
      return "/";
    case "smartSession":
      return `/find/${enc(route.sessionId)}`;
    case "explore":
      return (route.mode === "cards" ? "/explore/cards" : "/explore") + exploreSuffix(explore);
    case "legend":
      return `/explore/legend/${enc(route.legendId)}${exploreSuffix(explore)}`;
    case "champion":
      return `/explore/champion/${enc(route.championId)}${exploreSuffix(explore)}`;
    case "card":
      return `/explore/card/${enc(route.cardId)}${exploreSuffix(explore)}`;
    case "event":
      return `/explore/event/${enc(route.slug)}${exploreSuffix(explore)}`;
    case "archetype":
      return `/explore/archetype/${enc(route.archetypeId)}${exploreSuffix(explore)}`;
    case "build":
      return "/build";
    case "decks":
      return "/decks";
    case "search": {
      const params = new URLSearchParams();
      if (route.cardIds.length) params.set("cards", route.cardIds.map(enc).join(","));
      if (route.sort !== "rank") params.set("sort", route.sort);
      const query = params.toString();
      return query ? `/search?${query}` : "/search";
    }
    case "savedDeck":
      return `/decks/${enc(route.deckId)}`;
    case "metaDeck":
      return `/meta/deck/${enc(route.deckId)}`;
    case "sharedDeck":
      return `/deck?${deckToQuery(route.deck)}`;
  }
}

/**
 * What makes this route a different *place*, for the back button.
 *
 * Opening a legend is somewhere you should be able to come back from, so it is pushed.
 * Editing the deck on the bench, or nudging a filter, refines the page you are already
 * on -- pushing those would bury the back button under one entry per keystroke, so they
 * replace. Hence the key: the route's name and whatever it is *of*, never its contents.
 */
export function routeKey(route: Route): string {
  switch (route.name) {
    case "legend":
      return `legend:${route.legendId}`;
    case "champion":
      return `champion:${route.championId}`;
    case "card":
      return `card:${route.cardId}`;
    case "event":
      return `event:${route.slug}`;
    case "archetype":
      return `archetype:${route.archetypeId}`;
    case "smartSession":
      return `smartSession:${route.sessionId}`;
    case "explore":
      return `explore:${route.mode}`;
    case "savedDeck":
      return `savedDeck:${route.deckId}`;
    case "metaDeck":
      return `metaDeck:${route.deckId}`;
    // A deck being edited is one place, however much it changes.
    default:
      return route.name;
  }
}

export function absoluteUrl(path: string): string {
  return new URL(path, window.location.origin).toString();
}

// -- history ------------------------------------------------------------------

/**
 * True while a route is being applied to the store.
 *
 * The derive-from-state pass runs on every render, including the renders that applying
 * a route causes. Without this it would rewrite the address mid-navigation and, worse,
 * push a duplicate entry for the page you just arrived at.
 */
let applying = false;

export function isApplying(): boolean {
  return applying;
}

export async function whileApplying(work: () => void | Promise<void>): Promise<void> {
  applying = true;
  try {
    await work();
  } finally {
    applying = false;
  }
}

/** Write an address without touching the store. */
export function writeUrl(path: string, { push }: { push: boolean }): void {
  const current = window.location.pathname + window.location.search;
  if (current === path) return;
  if (push) window.history.pushState({}, "", path);
  else window.history.replaceState({}, "", path);
}

export function onPopState(handler: (location: Location) => void): void {
  window.addEventListener("popstate", () => {
    handler(parseLocation(window.location.pathname, window.location.search));
  });
}

export function currentLocation(): Location {
  return parseLocation(window.location.pathname, window.location.search);
}
