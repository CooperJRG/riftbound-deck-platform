/**
 * The router's arithmetic.
 *
 * A router is judged on round trips: whatever `pathFor` writes, `parseLocation` has to
 * read back as the same route, or a link works once and then drifts. These run on
 * Node's own test runner with type stripping -- `node --test` in `web/` -- which is why
 * this module imports nothing but its subject.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_MIN_PLAYERS,
  deckFromQuery,
  deckToQuery,
  parseLocation,
  pathFor,
  routeKey,
  viewFor,
  type ExploreQuery,
  type Route,
} from "./router.ts";

function roundTrip(route: Route, explore: ExploreQuery = {}): Route {
  const path = pathFor(route, explore);
  const [pathname, search = ""] = path.split("?");
  return parseLocation(pathname ?? "/", search).route;
}

// -- every page survives the round trip ---------------------------------------

const ROUTES: Route[] = [
  { name: "find" },
  { name: "smartSession", sessionId: "session-abc123" },
  { name: "explore", mode: "legends" },
  { name: "explore", mode: "cards" },
  { name: "legend", legendId: "irelia-blade-dancer" },
  { name: "champion", championId: "irelia-fervent" },
  { name: "card", cardId: "scuttle-crab" },
  { name: "event", slug: "s4-wuhan-regional-open" },
  { name: "archetype", archetypeId: "irelia-blade-dancer::irelia-fervent" },
  { name: "build" },
  { name: "decks" },
  { name: "savedDeck", deckId: "abc123" },
  { name: "metaDeck", deckId: "wuhan::1" },
];

for (const route of ROUTES) {
  test(`round trip: ${route.name} -> ${pathFor(route)}`, () => {
    assert.deepEqual(roundTrip(route), route);
  });
}

test("an archetype id keeps its separator through the URL", () => {
  const route: Route = { name: "archetype", archetypeId: "a-legend::a-champion" };
  const path = pathFor(route);
  assert.ok(!path.includes("::"), "the separator is encoded, not left raw in the path");
  assert.deepEqual(roundTrip(route), route);
});

test("explore filters survive on every explore page", () => {
  const explore: ExploreQuery = { range: "90", format: "constructed", minPlayers: 32 };
  for (const route of ROUTES.filter((r) => viewFor(r) === "explore")) {
    const path = pathFor(route, explore);
    const [pathname, search = ""] = path.split("?");
    assert.deepEqual(
      parseLocation(pathname ?? "/", search).explore,
      explore,
      `filters lost on ${route.name}`,
    );
  }
});

test("a filter left at its default is not written into the address", () => {
  const explore: Route = { name: "explore", mode: "legends" };
  assert.equal(pathFor(explore, {}), "/explore");
  assert.equal(pathFor(explore, { minPlayers: 0 }), "/explore");
  // The common case: nobody touched the field-size filter, so a shared Explore link
  // should not carry `?players=16`.
  assert.equal(pathFor(explore, { minPlayers: DEFAULT_MIN_PLAYERS }), "/explore");
  assert.equal(pathFor(explore, { minPlayers: 32 }), "/explore?players=32");
});

// -- the tab strip -------------------------------------------------------------

test("every explore drill-down still belongs to the Explore tab", () => {
  assert.equal(viewFor({ name: "legend", legendId: "x" }), "explore");
  assert.equal(viewFor({ name: "card", cardId: "x" }), "explore");
  assert.equal(viewFor({ name: "event", slug: "x" }), "explore");
  assert.equal(viewFor({ name: "archetype", archetypeId: "x" }), "explore");
  assert.equal(viewFor({ name: "savedDeck", deckId: "x" }), "build");
  assert.equal(viewFor({ name: "metaDeck", deckId: "x" }), "build");
  assert.equal(viewFor({ name: "decks" }), "decks");
  assert.equal(viewFor({ name: "smartSession", sessionId: "x" }), "find");
});

// -- a deck in a link ----------------------------------------------------------

const DECK = {
  name: "Wuhan Irelia",
  format: "constructed",
  legendId: "irelia-blade-dancer",
  championId: "irelia-fervent",
  main: { "scuttle-crab": 3, tideturner: 3, "pyke-returned": 1 },
  runes: { "calm-rune": 5, "chaos-rune": 7 },
  battlefields: ["abandoned-hall", "sunken-temple", "targons-peak"],
  sideboard: { abandon: 2, rebuke: 1 },
};

test("a deck survives the round trip through a link", () => {
  const back = deckFromQuery(new URLSearchParams(deckToQuery(DECK).toString()));
  assert.deepEqual(back, DECK);
});

test("a shared deck route round trips whole", () => {
  const route: Route = { name: "sharedDeck", deck: DECK };
  assert.deepEqual(roundTrip(route), route);
});

test("single copies do not carry a count, so the link stays readable", () => {
  const main = deckToQuery(DECK).get("m") ?? "";
  assert.equal(main, "scuttle-crab:3,tideturner:3,pyke-returned");
  const battlefields = deckToQuery(DECK).get("b") ?? "";
  assert.equal(battlefields, "abandoned-hall,sunken-temple,targons-peak");
});

test("an empty deck writes almost nothing", () => {
  const params = deckToQuery({
    name: "Untitled Deck",
    format: "constructed",
    legendId: "",
    championId: "",
    main: {},
    runes: {},
    battlefields: [],
    sideboard: {},
  });
  assert.equal(params.toString(), "");
});

test("zero and negative counts are dropped rather than serialised", () => {
  const params = deckToQuery({ ...DECK, main: { "scuttle-crab": 0, tideturner: -1, defy: 2 } });
  assert.equal(params.get("m"), "defy:2");
});

test("a battlefield played twice keeps both slots", () => {
  const deck = { ...DECK, battlefields: ["sunken-temple", "sunken-temple", "targons-peak"] };
  const back = deckFromQuery(new URLSearchParams(deckToQuery(deck).toString()));
  assert.deepEqual(back.battlefields, deck.battlefields);
});

// -- links that have rotted ----------------------------------------------------

test("an address we do not recognise lands on the front page", () => {
  assert.deepEqual(parseLocation("/nonsense/deep/path", "").route, { name: "find" });
  assert.deepEqual(parseLocation("/explore/legend", "").route, { name: "explore", mode: "legends" });
});

test("a deck link with a mangled count still opens", () => {
  const deck = deckFromQuery(new URLSearchParams("l=irelia-blade-dancer&m=scuttle-crab:nope,defy:2"));
  assert.equal(deck.legendId, "irelia-blade-dancer");
  assert.deepEqual(deck.main, { defy: 2 }, "the unreadable entry goes, the rest survives");
});

test("an empty deck link opens the builder rather than failing", () => {
  const route = parseLocation("/deck", "").route;
  assert.equal(route.name, "sharedDeck");
  assert.equal(route.name === "sharedDeck" && route.deck.legendId, "");
});

test("trailing slashes and repeated separators are tolerated", () => {
  assert.deepEqual(parseLocation("/explore/", "").route, { name: "explore", mode: "legends" });
  assert.deepEqual(parseLocation("//explore//cards//", "").route, {
    name: "explore",
    mode: "cards",
  });
});


// -- what counts as a new place ------------------------------------------------

test("opening a different legend is a new place", () => {
  assert.notEqual(
    routeKey({ name: "legend", legendId: "a" }),
    routeKey({ name: "legend", legendId: "b" }),
  );
});

test("a Smart Deck session is a place the back button can leave", () => {
  assert.notEqual(
    routeKey({ name: "find" }),
    routeKey({ name: "smartSession", sessionId: "session-1" }),
  );
  assert.notEqual(
    routeKey({ name: "smartSession", sessionId: "session-1" }),
    routeKey({ name: "smartSession", sessionId: "session-2" }),
  );
});

test("editing the deck on the bench is not", () => {
  const one: Route = { name: "sharedDeck", deck: DECK };
  const two: Route = { name: "sharedDeck", deck: { ...DECK, main: { defy: 2 } } };
  assert.equal(routeKey(one), routeKey(two), "one entry for the deck, not one per card");
});

test("the two explore modes are different places", () => {
  assert.notEqual(
    routeKey({ name: "explore", mode: "legends" }),
    routeKey({ name: "explore", mode: "cards" }),
  );
});
