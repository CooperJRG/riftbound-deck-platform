/** The availability profile -- the lens the whole builder sees the pool through. */

import { api } from "../../api/client";
import type { AvailabilityMode } from "../../api/types";
import { store } from "../store";
import { reportError } from "./shared";
import { refreshCards } from "./cards";
import { revalidate } from "./deck";

async function applyAvailability(
  next: Promise<Awaited<ReturnType<typeof api.availability>>>,
): Promise<void> {
  try {
    store.set({ availability: await next, error: "" });
    await Promise.all([refreshCards(), revalidate()]);
  } catch (error) {
    reportError(error);
  }
}

export async function setAvailabilityMode(mode: AvailabilityMode): Promise<void> {
  const current = store.state.availability;
  await applyAvailability(
    api.setAvailability({
      mode,
      strict: current?.strict ?? false,
      excludedCardIds: (current?.excludedCards ?? []).map((c) => c.cardId),
      rules: (current?.rules ?? []).map((r) => ({ kind: r.kind, value: r.value })),
    }),
  );
}

export async function setStrict(strict: boolean): Promise<void> {
  const current = store.state.availability;
  if (!current) return;
  await applyAvailability(
    api.setAvailability({
      mode: current.mode,
      strict,
      excludedCardIds: current.excludedCards.map((c) => c.cardId),
      rules: current.rules.map((r) => ({ kind: r.kind, value: r.value })),
    }),
  );
}

export async function excludeCard(cardId: string): Promise<void> {
  await applyAvailability(api.excludeCard(cardId));
}

export async function unexcludeCard(cardId: string): Promise<void> {
  await applyAvailability(api.unexcludeCard(cardId));
}

export async function toggleRule(kind: string, value: string): Promise<void> {
  const current = store.state.availability;
  if (!current) return;
  const exists = current.rules.some((r) => r.kind === kind && r.value === value);
  const rules = exists
    ? current.rules.filter((r) => !(r.kind === kind && r.value === value))
    : [...current.rules, { kind, value, description: "" }];
  await applyAvailability(
    api.setAvailability({
      mode: "exclusion",
      strict: current.strict,
      excludedCardIds: current.excludedCards.map((c) => c.cardId),
      rules: rules.map((r) => ({ kind: r.kind, value: r.value })),
    }),
  );
}
