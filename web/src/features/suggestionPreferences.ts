import type { CardSuggestion } from "../api/types";

export type DismissibleSuggestionZone = "main" | "battlefields" | "sideboard";

const STORAGE_KEY = "riftdesk.dismissed-suggestions.v1";

function preferenceKey(legendId: string, zone: DismissibleSuggestionZone): string {
  return `${legendId.trim().toLowerCase()}::${zone}`;
}

function readPreferences(): Record<string, string[]> {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed).filter((entry): entry is [string, string[]] =>
        Array.isArray(entry[1]) && entry[1].every((value) => typeof value === "string")),
    );
  } catch {
    return {};
  }
}

export function visibleSuggestions(
  rows: CardSuggestion[],
  legendId: string,
  zone: DismissibleSuggestionZone,
): CardSuggestion[] {
  const dismissed = new Set(readPreferences()[preferenceKey(legendId, zone)] ?? []);
  return rows.filter((row) => !dismissed.has(row.cardId));
}

export function dismissSuggestion(
  cardId: string,
  legendId: string,
  zone: DismissibleSuggestionZone,
): void {
  if (!cardId || !legendId) return;
  const preferences = readPreferences();
  const key = preferenceKey(legendId, zone);
  preferences[key] = [...new Set([...(preferences[key] ?? []), cardId])];
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
  } catch {
    // Storage can be disabled. The button still fails safely; no deck state is touched.
  }
}
