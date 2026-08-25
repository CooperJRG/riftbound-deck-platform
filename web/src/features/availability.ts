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
  setAvailabilityMode,
  setStrict,
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
    hint: "Precise, but you have to record what you own first.",
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
    body.push(
      h(
        "p",
        { class: "muted small" },
        profile.ownedCardCount > 0
          ? `${profile.ownedCardCount} distinct cards recorded.`
          : "No collection recorded yet — every card counts as missing until you add some.",
      ),
    );
  }

  replace(root, ...body);
}
