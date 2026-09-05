import assert from "node:assert/strict";
import { test } from "node:test";
import { ownershipProgress, rowState } from "./wizard/ownership.ts";

const row = { cardId: "unit", have: 0, needed: 3, known: false };

test("explicitly choosing zero settles an untouched checklist row", () => {
  assert.equal(rowState(row, 0), "awaiting");
  assert.equal(rowState(row, 0, true), "gap");
});
test("returning to the initial quantity remains an explicit answer", () => {
  assert.equal(rowState({ ...row, have: 1 }, 1, true), "gap");
});
test("known shortages do not become unanswered questions", () => {
  assert.equal(rowState({ ...row, known: true }, 0), "gap");
});
test("missing copies count quantities and exclude unanswered zeros", () => {
  const other = { ...row, cardId: "other" };
  const progress = ownershipProgress([row, other], new Map([[row.cardId, 1]]), new Set([row.cardId]));
  assert.deepEqual(progress, { confirmed: 1, missingCopies: 2, assumed: 0, total: 2, unanswered: 1 });
});
test("an assumed playset does not increase confirmed ownership", () => {
  assert.deepEqual(ownershipProgress([{ ...row, have: 3 }], new Map(), new Set()),
    { confirmed: 0, missingCopies: 0, assumed: 1, total: 1, unanswered: 0 });
});
test("explicit zero contributes the entire shortage", () => {
  const progress = ownershipProgress([row], new Map([[row.cardId, 0]]), new Set([row.cardId]));
  assert.equal(progress.missingCopies, 3);
  assert.equal(progress.unanswered, 0);
});
