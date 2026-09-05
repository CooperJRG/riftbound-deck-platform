import assert from "node:assert/strict";
import { test } from "node:test";
import { collectionSummary } from "./collectionSummary.ts";

const base = { mode: "open" as const, strict: false, ownedCardCount: 0, ownedRules: [], excludedCards: [], rules: [] };

test("a full card pool never claims ownership", () => {
  assert.match(collectionSummary(base).detail, /Ownership has not been checked/);
});
test("inactive collection data does not claim coverage in exclusion mode", () => {
  const result = collectionSummary({ ...base, mode: "exclusion", ownedCardCount: 10 });
  assert.match(result.detail, /No cards ruled out/);
});
test("bulk declarations stay distinct from recorded quantities", () => {
  const result = collectionSummary({ ...base, mode: "collection", ownedCardCount: 12, ownedRules: [{}] });
  assert.equal(result.label, "12 cards recorded");
  assert.match(result.detail, /plus 1 collection shortcut/);
  assert.match(result.detail, /assume/);
});
test("an empty collection offers a route to recording quantities", () => {
  assert.match(collectionSummary({ ...base, mode: "collection" }).detail, /Start with a legend/);
});
test("missing settings are never reported as an empty collection", () => {
  assert.match(collectionSummary(null).detail, /unavailable/);
});
