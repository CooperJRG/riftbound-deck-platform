/**
 * The availability control — how the player tells the app what they can field.
 *
 * Exclusion mode is presented first and needs no setup: name a card you don't have,
 * or tick a whole class ("no Epics"), and every card list and deck readout updates.
 * Collection mode is the precise-but-expensive option, offered second.
 */

import type {
  AvailabilityMode,
  AvailabilityProfile,
  CardFacets,
  ExcludedCard,
} from "../api/types";
import {
  forgetCollection,
  setAvailabilityMode,
  setStrict,
  toggleOwnedRule,
  toggleRule,
  unexcludeCard,
} from "../state/actions";
import { store } from "../state/store";
import { h, replace } from "../ui/dom";

const MODE_LABELS: Record<AvailabilityMode, { title: string; hint: string }> = {
  exclusion: {
    title: "Cards I don't have",
    hint: "Name what you're missing. Everything else is fair game — including new sets.",
  },
  collection: {
    title: "My collection",
    // Was "Precise, but you have to record what you own first" -- true when the only
    // writer was the wizard's opt-in write-back, and a dead end: the mode told the
    // player to record something and gave them nowhere to do it.
    hint: "Say roughly what you have — a whole rarity or set at a time.",
  },
  open: {
    title: "Everything",
    hint: "Build with the whole card pool.",
  },
};

const MODE_ORDER: AvailabilityMode[] = ["exclusion", "collection", "open"];

function modeButton(mode: AvailabilityMode, active: boolean): HTMLElement {
  const label = MODE_LABELS[mode];
  return h(
    "button",
    {
      class: `mode-btn${active ? " is-active" : ""}`,
      type: "button",
      title: label.hint,
      aria: { pressed: String(active) },
      on: { click: () => void setAvailabilityMode(mode) },
    },
    label.title,
  );
}

function excludedChip(entry: ExcludedCard): HTMLElement {
  return h(
    "span",
    { class: "chip" },
    entry.name,
    h(
      "button",
      {
        class: "chip-x",
        type: "button",
        title: "I do have this after all",
        aria: { label: `Remove ${entry.name}` },
        on: { click: () => void unexcludeCard(entry.cardId) },
      },
      "×",
    ),
  );
}

/** One-click rules, built from the values actually present in the bundle. */
function quickRules(profile: AvailabilityProfile, facets: CardFacets | null): HTMLElement {
  const active = (kind: string, value: string) =>
    profile.rules.some((r) => r.kind === kind && r.value === value);

  const options: { kind: string; value: string; label: string }[] = [
    ...(facets?.rarities ?? [])
      .filter((r) => r === "Epic" || r === "Rare" || r === "Showcase")
      .map((r) => ({ kind: "rarity", value: r, label: `No ${r}s` })),
    { kind: "promo_only", value: "", label: "No promo-only cards" },
    ...(facets?.setCodes ?? []).map((s) => ({
      kind: "set",
      value: s,
      label: `No ${s}`,
    })),
  ];

  return h(
    "div",
    { class: "quick-rules" },
    ...options.map((option) =>
      h(
        "button",
        {
          class: `pill${active(option.kind, option.value) ? " is-on" : ""}`,
          type: "button",
          on: { click: () => void toggleRule(option.kind, option.value) },
        },
        option.label,
      ),
    ),
  );
}

/**
 * One-click rules for what the player *does* have.
 *
 * The mirror of `quickRules`, and the half that was missing. Until this existed,
 * "My collection" told the player to record what they own and gave them nowhere to do
 * it: the only writer in the app was the wizard's opt-in write-back, so a collection
 * could only ever contain cards some session happened to ask about. Naming what you
 * lack is the right shape for somebody who owns nearly everything; a casual player
 * would have to list thousands of cards to say something true about a few hundred.
 */
function ownedRules(profile: AvailabilityProfile, facets: CardFacets | null): HTMLElement {
  const active = (kind: string, value: string) =>
    profile.ownedRules.some((r) => r.kind === kind && r.value === value);

  const options: { kind: string; value: string; label: string }[] = [
    // Rarity first: it is the axis a collection actually thins out along.
    ...(facets?.rarities ?? [])
      .filter((r) => r === "Common" || r === "Uncommon" || r === "Rare")
      .map((r) => ({ kind: "rarity", value: r, label: `All ${r}s` })),
    ...(facets?.setCodes ?? []).map((code) => ({
      kind: "set",
      value: code,
      label: `All of ${code}`,
    })),
  ];

  return h(
    "div",
    { class: "quick-rules" },
    ...options.map((option) =>
      h(
        "button",
        {
          class: `pill${active(option.kind, option.value) ? " is-on" : ""}`,
          type: "button",
          on: { click: () => void toggleOwnedRule(option.kind, option.value) },
        },
        option.label,
      ),
    ),
  );
}


export function renderAvailability(root: HTMLElement): void {
  const { availability: profile, facets } = store.state;
  if (!profile) {
    replace(root, h("p", { class: "muted" }, "Loading…"));
    return;
  }

  const body: HTMLElement[] = [
    h(
      "div",
      { class: "mode-row" },
      h("div", { class: "mode-group", role: "group" },
        ...MODE_ORDER.map((mode) => modeButton(mode, profile.mode === mode))),
      h(
        "label",
        { class: "strict-toggle", title: "Hide unavailable cards entirely instead of ranking them lower" },
        h("input", {
          type: "checkbox",
          checked: profile.strict,
          on: { change: (e) => void setStrict((e.target as HTMLInputElement).checked) },
        }),
        " Only what I can build now",
      ),
    ),
    h("p", { class: "mode-hint" }, MODE_LABELS[profile.mode].hint),
  ];

  if (profile.mode === "exclusion") {
    body.push(
      h(
        "div",
        { class: "exclusions" },
        profile.excludedCards.length > 0
          ? h(
              "div",
              { class: "chips" },
              h("span", { class: "chips-label" }, "Missing:"),
              ...profile.excludedCards.map(excludedChip),
            )
          : h(
              "p",
              { class: "muted small" },
              "Click “I don't have this” on any card to start.",
            ),
        quickRules(profile, facets),
      ),
    );
  } else if (profile.mode === "collection") {
    const counted =
      profile.ownedCardCount > 0
        ? `${profile.ownedCardCount} distinct cards recorded`
        : "";
    const declared = profile.ownedRules.length
      ? profile.ownedRules.map((r) => r.description).join(", ")
      : "";
    body.push(
      h(
        "div",
        { class: "exclusions" },
        h(
          "p",
          { class: "muted small" },
          counted && declared
            ? `You have ${declared}, plus ${counted}.`
            : declared
              ? `You have ${declared}.`
              : counted
                ? `${counted}.`
                : "Tell us roughly what you have — a whole rarity or a whole set at a time.",
        ),
        ownedRules(profile, facets),
      ),
    );
  }

  // The way back out. The wizard offers to write what a session learned into the
  // collection, which is much the fastest way to record one — and a one-way door into
  // that is not a fair trade for the convenience. Always offered, not only in collection
  // mode, because a session's answers outlive the mode that produced them.
  body.push(
    h(
      "div",
      { class: "forget-collection" },
      h(
        "button",
        {
          class: "quiet-button",
          type: "button",
          title: "Delete the recorded collection and every Smart Decks session",
          on: { click: () => void forgetCollection() },
        },
        "Forget what I have told you",
      ),
      h(
        "span",
        { class: "muted small" },
        "Removes the recorded collection and every saved wizard session.",
      ),
    ),
  );

  replace(root, ...body);
}
