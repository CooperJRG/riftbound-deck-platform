import assert from "node:assert/strict";
import { test } from "node:test";
import { createSerialQueue } from "./serialQueue.ts";

test("rapid profile updates read the preceding saved result", async () => {
  const queue = createSerialQueue();
  let profile: string[] = [];
  let release!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  const first = queue(async () => { const before = [...profile]; await held; profile = [...before, "Common"]; });
  const second = queue(async () => { profile = [...profile, "Uncommon"]; });
  await Promise.resolve();
  assert.deepEqual(profile, []);
  release();
  await Promise.all([first, second]);
  assert.deepEqual(profile, ["Common", "Uncommon"]);
});
test("a rejected write does not block later profile changes", async () => {
  const queue = createSerialQueue();
  const first = queue(async () => { throw new Error("offline"); });
  const second = queue(async () => "saved");
  await assert.rejects(first, /offline/);
  assert.equal(await second, "saved");
});
