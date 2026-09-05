/** Collection edits are serialized so a quick second click cannot undo the first. */
import { api } from "../../api/client";
import type { AvailabilityMode, AvailabilityUpdate } from "../../api/types";
import { store } from "../store";
import { createSerialQueue } from "../serialQueue";
import { reportError } from "./shared";
import { refreshCards } from "./cards";
import { revalidate } from "./deck";

const enqueue = createSerialQueue();

export async function refreshAvailabilityViews(): Promise<void> {
  store.set({ smartLegendsLoaded: false });
  await Promise.all([
    refreshCards(),
    revalidate(),
    api.smartLegends(store.state.smartLegendSort).then((smartLegends) => {
      store.set({ smartLegends, smartLegendsLoaded: true });
    }).catch(reportError),
  ]);
}

function edit(operation: () => Promise<void>): Promise<void> {
  return enqueue(async () => {
    try {
      await operation();
      await refreshAvailabilityViews();
    } catch (error) { reportError(error); }
  });
}

/** Read the profile when the queued write starts, never when it was clicked. */
function currentUpdate(): AvailabilityUpdate | null {
  const current = store.state.availability;
  if (!current) return null;
  return {
    mode: current.mode,
    strict: current.strict,
    penalty: current.penalty,
    excludedCardIds: current.excludedCards.map((card) => card.cardId),
    rules: current.rules.map(({ kind, value }) => ({ kind, value })),
    ownedRules: current.ownedRules.map(({ kind, value }) => ({ kind, value })),
  };
}

function update(change: (current: AvailabilityUpdate) => AvailabilityUpdate): Promise<void> {
  return edit(async () => {
    const current = currentUpdate();
    if (!current) return;
    store.set({ availability: await api.setAvailability(change(current)), error: "" });
  });
}

export function setAvailabilityMode(mode: AvailabilityMode): Promise<void> {
  return update((current) => ({ ...current, mode }));
}

export function setStrict(strict: boolean): Promise<void> {
  return update((current) => ({ ...current, strict }));
}

export function excludeCard(cardId: string): Promise<void> {
  return edit(async () => { store.set({ availability: await api.excludeCard(cardId), error: "" }); });
}

export function unexcludeCard(cardId: string): Promise<void> {
  return edit(async () => { store.set({ availability: await api.unexcludeCard(cardId), error: "" }); });
}

export function toggleRule(kind: string, value: string): Promise<void> {
  return update((current) => {
    const rules = current.rules ?? [];
    return { ...current, mode: "exclusion", rules: rules.some((r) => r.kind === kind && r.value === value)
      ? rules.filter((r) => !(r.kind === kind && r.value === value)) : [...rules, { kind, value }] };
  });
}

export function toggleOwnedRule(kind: string, value: string): Promise<void> {
  return update((current) => {
    const rules = current.ownedRules ?? [];
    return { ...current, mode: "collection", ownedRules: rules.some((r) => r.kind === kind && r.value === value)
      ? rules.filter((r) => !(r.kind === kind && r.value === value)) : [...rules, { kind, value }] };
  });
}

export function forgetCollection(): Promise<void> {
  return edit(async () => {
    const result = await api.forgetCollection();
    store.set({
      availability: result.availability,
      smartResumable: [], smartSession: null, smartAnswers: new Map(), smartTouched: new Set(),
      smartFinished: false, smartShowing: "rounds", error: "",
      notice: `Reset ${result.collectionRows} collection entries and ${result.sessions} finder sessions. Your saved decks are kept.`,
    });
  });
}
