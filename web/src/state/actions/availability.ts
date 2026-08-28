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
      // Carried across a mode switch, so flipping to exclusion to look at something and
      // back does not silently erase what the player recorded.
      ownedRules: (current?.ownedRules ?? []).map((r) => ({ kind: r.kind, value: r.value })),
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
      ownedRules: current.ownedRules.map((r) => ({ kind: r.kind, value: r.value })),
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
      ownedRules: current.ownedRules.map((r) => ({ kind: r.kind, value: r.value })),
    }),
  );
}

/**
 * Say what you *do* have, a class at a time.
 *
 * The mirror of `toggleRule`, and the half that was missing. Naming what you lack only
 * scales for somebody who owns nearly everything; a player with a few hundred cards
 * would have to list thousands to say something true. "Everything Common from OGN" is
 * one click and covers hundreds.
 */
export async function toggleOwnedRule(kind: string, value: string): Promise<void> {
  const current = store.state.availability;
  if (!current) return;
  const exists = current.ownedRules.some((r) => r.kind === kind && r.value === value);
  const ownedRules = exists
    ? current.ownedRules.filter((r) => !(r.kind === kind && r.value === value))
    : [...current.ownedRules, { kind, value, description: "" }];
  await applyAvailability(
    api.setAvailability({
      mode: "collection",
      strict: current.strict,
      excludedCardIds: current.excludedCards.map((c) => c.cardId),
      rules: current.rules.map((r) => ({ kind: r.kind, value: r.value })),
      ownedRules: ownedRules.map((r) => ({ kind: r.kind, value: r.value })),
    }),
  );
}


/**
 * Erase the collection, and every wizard session with it.
 *
 * Both halves deliberately. The collection rows are the obvious ones, but a session's
 * answers say what somebody owns just as plainly -- three rounds pin down roughly 75
 * cards -- so erasing one and leaving the other would be a privacy control that only
 * looks like one.
 *
 * Reports what it removed rather than saying "done": a control that asks to be trusted
 * at this moment should be showing its working.
 */
export async function forgetCollection(): Promise<void> {
  try {
    const result = await api.forgetCollection();
    store.set({
      availability: result.availability,
      smartResumable: [],
      notice:
        result.collectionRows || result.sessions
          ? `Forgotten: ${result.collectionRows} collection ${result.collectionRows === 1 ? "entry" : "entries"}` +
            ` and ${result.sessions} wizard ${result.sessions === 1 ? "session" : "sessions"}.`
          : "Nothing was recorded, so there was nothing to forget.",
    });
    await refreshCards();
    await revalidate();
  } catch (error) {
    reportError(error);
  }
}
