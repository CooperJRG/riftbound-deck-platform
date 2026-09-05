/** Describe the active card pool without turning assumptions into ownership. */
export interface CollectionProfile {
  mode: "open" | "exclusion" | "collection";
  strict: boolean;
  ownedCardCount: number;
  ownedRules: { description?: string }[];
  excludedCards: unknown[];
  rules: unknown[];
}

export function collectionSummary(profile: CollectionProfile | null): { label: string; detail: string } {
  if (!profile) return { label: "Your cards", detail: "Collection settings are unavailable. Try reloading the page." };
  if (profile.mode === "open") return {
    label: "Full card pool",
    detail: "All cards are available for suggestions. Ownership has not been checked.",
  };
  if (profile.mode === "exclusion") {
    const exclusions = profile.excludedCards.length + profile.rules.length;
    return {
      label: exclusions ? `${exclusions} exclusion${exclusions === 1 ? "" : "s"}` : "Missing cards mode",
      detail: exclusions
        ? "Using your exclusions. Cards you have not ruled out are assumed available."
        : "No cards ruled out yet. Tell us what you lack, or check quantities in the deck finder.",
    };
  }
  const count = profile.ownedCardCount;
  const rules = profile.ownedRules.length;
  return {
    label: count ? `${count} card${count === 1 ? "" : "s"} recorded` : rules ? "Collection shortcuts" : "Collection not entered",
    detail: rules
      ? `${count} distinct cards recorded, plus ${rules} collection shortcut${rules === 1 ? "" : "s"}. Shortcuts assume full quantities for matching cards.`
      : count
        ? "Using recorded quantities. Unrecorded cards count as missing; suggestions may still include them unless strict mode is on."
        : "Start with a legend and record cards as you go. You do not need to catalogue everything first.",
  };
}
