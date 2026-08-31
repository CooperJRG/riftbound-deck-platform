import type {
  BuildSuggestions,
  CardAvailability,
  DeckPayload,
  Validation,
} from "../api/types";

export type ReadinessTone = "building" | "legal" | "shaped" | "custom";

export interface DeckAnalysisModel {
  status: string;
  tone: ReadinessTone;
  explanation: string;
  curve: { label: string; copies: number }[];
  types: { label: string; copies: number }[];
  averageCost: number | null;
  knownCopies: number;
  totalCopies: number;
  reachedSteps: number;
}

/** The format's own targets. Defaults are constructed's; every real caller passes its
 * own, sourced the same place the playmat's zone headers get theirs -- so a smaller
 * format like skirmish is never told it is 10 cards short of a deck it has finished. */
export interface DeckTargets {
  mainTarget: number;
  runeTarget: number;
  battlefieldTarget: number;
}

const DEFAULT_TARGETS: DeckTargets = { mainTarget: 40, runeTarget: 12, battlefieldTarget: 3 };

function nextNeed(deck: DeckPayload, validation: Validation, targets: DeckTargets): string {
  const { mainTarget, runeTarget, battlefieldTarget } = targets;
  if (!deck.legendId) return "Choose a legend to establish the deck's domains.";
  if (!deck.championId) return "Choose a champion to establish the deck's game plan.";
  if (validation.mainTotal !== mainTarget) return `${Math.abs(mainTarget - validation.mainTotal)} main-deck cards ${validation.mainTotal < mainTarget ? "still needed" : "over the limit"}.`;
  if (validation.battlefieldCount !== battlefieldTarget) return `${Math.abs(battlefieldTarget - validation.battlefieldCount)} battlefields ${validation.battlefieldCount < battlefieldTarget ? "still needed" : "over the limit"}.`;
  if (validation.runeTotal !== runeTarget) return `${Math.abs(runeTarget - validation.runeTotal)} runes ${validation.runeTotal < runeTarget ? "still needed" : "over the limit"}.`;
  return validation.issues.find((issue) => issue.severity !== "notice")?.message
    ?? "The list still has a rules issue to resolve.";
}

export function analyzeDeck(
  deck: DeckPayload,
  cards: Map<string, CardAvailability>,
  validation: Validation | null,
  suggestions: BuildSuggestions | null,
  targets: DeckTargets = DEFAULT_TARGETS,
): DeckAnalysisModel {
  const curve = [
    { label: "0–1", copies: 0 }, { label: "2", copies: 0 },
    { label: "3", copies: 0 }, { label: "4", copies: 0 },
    { label: "5", copies: 0 }, { label: "6", copies: 0 },
    { label: "7+", copies: 0 },
  ];
  const typeCounts = new Map<string, number>();
  let knownCopies = 0;
  let weightedCost = 0;
  let costCopies = 0;
  for (const [cardId, copies] of Object.entries(deck.main)) {
    const card = cards.get(cardId)?.card;
    if (!card) continue;
    knownCopies += copies;
    const type = card.cardType || "Other";
    typeCounts.set(type, (typeCounts.get(type) ?? 0) + copies);
    if (card.cost === null) continue;
    const bucket = card.cost <= 1 ? 0 : card.cost >= 7 ? 6 : card.cost - 1;
    curve[bucket]!.copies += copies;
    weightedCost += card.cost * copies;
    costCopies += copies;
  }
  const preferred = ["Unit", "Spell", "Gear"];
  const types = [...typeCounts].map(([label, copies]) => ({ label, copies })).sort((a, b) => {
    const ai = preferred.indexOf(a.label);
    const bi = preferred.indexOf(b.label);
    return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi) || a.label.localeCompare(b.label);
  });

  let status = "In progress";
  let tone: ReadinessTone = "building";
  let explanation = validation ? nextNeed(deck, validation, targets) : "Checking the deck's structure.";
  const match = suggestions?.fieldMatch;
  if (validation?.legal) {
    if (match?.available && match.similarity >= match.threshold) {
      if (match.copyChanges === 0) {
        status = "Tournament-shaped";
        tone = "shaped";
        explanation = "Legal and an exact copy-count match for the closest published list.";
      } else {
        status = "Field-shaped · personal";
        tone = "custom";
        explanation = `Legal, above the measured same-family threshold, with ${match.copyChanges} copy slot${match.copyChanges === 1 ? "" : "s"} changed from the closest published list.`;
      }
    } else {
      status = "Legal · original shape";
      tone = "legal";
      explanation = match?.available
        ? `Rules-ready; its ${(match.similarity * 100).toFixed(0)}% overlap is below the ${(match.threshold * 100).toFixed(0)}% same-family benchmark.`
        : "Rules-ready. There is not enough comparable published data to judge its field shape.";
    }
  }

  return {
    status, tone, explanation, curve, types,
    averageCost: costCopies ? weightedCost / costCopies : null,
    knownCopies,
    totalCopies: Object.values(deck.main).reduce((sum, copies) => sum + copies, 0),
    reachedSteps: validation?.legal && match?.available && match.similarity >= match.threshold
      ? 3
      : validation?.legal
        ? 1
        : deck.legendId && deck.championId
          ? 0
          : -1,
  };
}
