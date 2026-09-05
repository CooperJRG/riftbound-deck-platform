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
import { collectionSummary } from "./collectionSummary";

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
    hint: "Use recorded quantities, or count a complete rarity or set as available.",
  },
  open: {
    title: "Everything",
    hint: "Build with the whole card pool.",
  },
};

const MODE_ORDER: AvailabilityMode[] = ["exclusion", "collection", "open"];
let lastProfile: AvailabilityProfile | null = null;
let lastFacets: CardFacets | null = null;
let lastRoot: HTMLElement | null = null;

function modeButton(mode: AvailabilityMode, active: boolean): HTMLElement {
  const label = MODE_LABELS[mode];
  return h(
    "button",
    {
      class: `mode-btn${active ? " is-active" : ""}`,
      type: "button",
      data: { availabilityKey: `mode:${mode}` },
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
          aria: { pressed: String(active(option.kind, option.value)) },
          data: { availabilityKey: `excluded:${option.kind}:${option.value}` },
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
          aria: { pressed: String(active(option.kind, option.value)) },
          data: { availabilityKey: `owned:${option.kind}:${option.value}` },
          on: { click: () => void toggleOwnedRule(option.kind, option.value) },
        },
        option.label,
      ),
    ),
  );
}


export function renderAvailability(root: HTMLElement): void {
  const { availability: profile, facets } = store.state;
  if (root === lastRoot && profile === lastProfile && facets === lastFacets) return;
  lastRoot = root;
  lastProfile = profile;
  lastFacets = facets;
  const activeKey = (document.activeElement as HTMLElement | null)?.dataset.availabilityKey;
  if (!profile) {
    replace(root, h("p", { class: "muted" }, "Loading…"));
    return;
  }

  const summary = collectionSummary(profile);
  const body: HTMLElement[] = [
    h("p", { class: "availability-summary" }, h("strong", {}, summary.label), summary.detail),
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
          data: { availabilityKey: "strict" },
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
                : "Use the deck finder to record quantities as you go, or add a collection shortcut below.",
        ),
        ownedRules(profile, facets),
        h("p", { class: "muted small" }, "Shortcuts assume full quantities of every matching card, including future sets. They are combined: selecting a rarity and a set includes both groups."),
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
          on: { click: () => {
            if (window.confirm("Reset your recorded collection and delete all deck-finder sessions? Saved decks are kept. This cannot be undone.")) void forgetCollection();
          } },
        },
        "Reset collection & finder sessions…",
      ),
      h(
        "span",
        { class: "muted small" },
        "Removes the recorded collection and every saved wizard session.",
      ),
    ),
  );

  body.push(h("p", { class: "availability-storage-note" }, "Saved decks and collection records belong to this browser. Clearing site cookies loses access to them. Export decks or copy their links to keep a backup."));

  replace(root, ...body);
  if (activeKey) Array.from(root.querySelectorAll<HTMLElement>("[data-availability-key]"))
    .find((element) => element.dataset.availabilityKey === activeKey)?.focus({ preventScroll: true });
}
