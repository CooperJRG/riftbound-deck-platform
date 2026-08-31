import assert from "node:assert/strict";
import test from "node:test";
import type { BuildSuggestions, CardAvailability, DeckPayload, Validation } from "../api/types";
import { analyzeDeck } from "./deckAnalysisModel.ts";

const deck: DeckPayload = {
  name: "Test", format: "constructed", legendId: "legend", championId: "champion",
  main: { one: 3, seven: 2 }, runes: { rune: 12 }, battlefields: ["a", "b", "c"], sideboard: {},
};

function row(cardId: string, cost: number, cardType: string): CardAvailability {
  return {
    weight: 1, available: true, ownedCopies: 3, maxCopies: 3, reason: "",
    card: {
      cardId, name: cardId, cardType, superType: "", domains: ["Mind"], cost,
      power: 1, might: 1, tags: [], championTags: [], effect: "", unique: false,
      rarity: "Common", setCodes: [], imageUrl: "", printings: [],
    },
  };
}

const validation = {
  legal: true, issues: [], mainTotal: 40, runeTotal: 12, sideboardTotal: 0,
  battlefieldCount: 3, legendDomains: ["Mind"], coverage: {},
} as Validation;

function suggestions(similarity: number, copyChanges: number): BuildSuggestions {
  return {
    champions: [], main: [], battlefields: [], sideboard: [], runes: {}, runeReason: "",
    deckScore: { meta: 72, legend: 88, coverage: 0.8, scored: true, summary: "rated", disclaimer: "estimate" },
    fieldMatch: {
      available: true, archetypeId: "a", name: "A", sampleDecks: 2,
      tournamentDecks: 1, similarity, threshold: 0.62, chosenCards: 2,
      matchedCards: 2, copyChanges, referenceDeckId: "r", referenceDeckName: "R",
      summary: "close",
    },
  };
}

test("curve and type balance count copies rather than unique cards", () => {
  const cards = new Map([["one", row("one", 1, "Unit")], ["seven", row("seven", 7, "Spell")]]);
  const model = analyzeDeck(deck, cards, validation, suggestions(0.8, 2));

  assert.equal(model.curve[0]?.copies, 3);
  assert.equal(model.curve[6]?.copies, 2);
  assert.deepEqual(model.types, [{ label: "Unit", copies: 3 }, { label: "Spell", copies: 2 }]);
  assert.equal(model.averageCost, 3.4);
});

test("legal field-shaped lists keep personal changes visible", () => {
  const model = analyzeDeck(deck, new Map(), validation, suggestions(0.7, 3));
  assert.equal(model.status, "Field-shaped · personal");
  assert.match(model.explanation, /3 copy slots changed/);
});

test("legal lists below the measured threshold are not called tournament-shaped", () => {
  const model = analyzeDeck(deck, new Map(), validation, suggestions(0.5, 0));
  assert.equal(model.status, "Legal · original shape");
  assert.match(model.explanation, /below the 62%/);
});

test("a smaller format's own target is honoured, not the constructed default", () => {
  // A 30-card list is exactly the size a skirmish deck should be. Read against the
  // default 40-card target it looks 10 cards short; passed the real target it does not.
  const thirtyCardValidation = { ...validation, mainTotal: 30, legal: false } as Validation;
  const skirmish = analyzeDeck(deck, new Map(), thirtyCardValidation, null, {
    mainTarget: 30, runeTarget: 12, battlefieldTarget: 3,
  });
  assert.doesNotMatch(skirmish.explanation, /main-deck cards/);

  const asConstructed = analyzeDeck(deck, new Map(), thirtyCardValidation, null);
  assert.match(asConstructed.explanation, /10 main-deck cards still needed/);
});
