/**
 * The rules-text tokenizer, pinned against the two cards that motivated it.
 *
 * Runs on Node's own runner (`node --test`), which is why `cardEffectTokens.ts` has no
 * DOM import: `cardSymbols.ts` needs `DOMParser` to vendor its icon SVGs, and Node has
 * no such global, so anything that needs testing without a browser lives here instead.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { RUNE_DOMAINS, tokenizeEffectLine, type EffectToken } from "./cardEffectTokens.ts";

function kinds(tokens: EffectToken[]): string[] {
  return tokens.map((t) => t.kind);
}

// -- the two cards that started this ------------------------------------------

test("a keyword before its glyphs is not swallowed as plain text", () => {
  // The bug an earlier, two-pass version of this parser had: it scanned the whole
  // line for :rb_*: glyphs first and only looked for [Keyword] in what was left over,
  // so anything written before the first glyph -- exactly this card -- never got
  // keyword-styled at all.
  const line = "[Flow] :rb_energy_5::rb_rune_rainbow::rb_rune_rainbow: "
    + "(You may play this from your trash for its Flow cost. Then banish it.)";
  const tokens = tokenizeEffectLine(line);

  assert.deepEqual(tokens[0], { kind: "keyword", text: "[Flow]", trigger: false });
  assert.deepEqual(tokens[1], { kind: "text", value: " " });
  assert.deepEqual(tokens[2], { kind: "energy", amount: "5" });
  assert.deepEqual(tokens[3], { kind: "rune", domain: "rainbow" });
  assert.deepEqual(tokens[4], { kind: "rune", domain: "rainbow" });
  // The reminder text repeats "Flow" with no brackets -- not a keyword this time.
  const tail = tokens[5];
  assert.equal(tail?.kind, "text");
  assert.ok(tail && tail.kind === "text" && tail.value.includes("its Flow cost"));
  assert.ok(!tokens.slice(5).some((t) => t.kind === "keyword"));
});

test("a keyword after its glyph, and a second bracketed keyword later in the line", () => {
  const line = "Give a unit +2 :rb_might: this turn. If it's [Empowered], give it "
    + "+4 :rb_might: this turn instead.";
  const tokens = tokenizeEffectLine(line);

  const mightCount = tokens.filter((t) => t.kind === "might").length;
  assert.equal(mightCount, 2);
  assert.ok(tokens.some((t) => t.kind === "keyword" && t.text === "[Empowered]"));
  // Order preserved: the first "might" appears before "[Empowered]", the second after.
  const firstMight = tokens.findIndex((t) => t.kind === "might");
  const empowered = tokens.findIndex((t) => t.kind === "keyword");
  const secondMight = tokens.findIndex((t, i) => t.kind === "might" && i > firstMight);
  assert.ok(firstMight < empowered);
  assert.ok(empowered < secondMight);
});

test("[Action] with its reminder text in parentheses passes through untouched", () => {
  const tokens = tokenizeEffectLine("[Action] (Play on your turn or in showdowns.)");
  assert.deepEqual(tokens[0], { kind: "keyword", text: "[Action]", trigger: false });
  assert.equal(tokens[1]?.kind, "text");
  assert.ok(tokens[1] && tokens[1].kind === "text" && tokens[1].value.startsWith(" (Play on your turn"));
});

// -- the trigger marker ----------------------------------------------------------
//
// "[Empowered][>]", "[Action][>]", "[Level 6][>]" -- on the printed card that pair is
// one continuous banner ending in a point, confirmed against real card art (Akali -
// Rogue Assassin, Akali - Deadly Weapon): there is no literal ">" character on either
// card, only the banner's own pointed edge. So the marker folds into the keyword
// token it follows rather than becoming a separate, literal "[>]" next to it.

test("a keyword immediately followed by [>] folds the marker into one token", () => {
  const tokens = tokenizeEffectLine("[Action][>]:rb_exhaust:: do a thing.");
  assert.deepEqual(tokens[0], { kind: "keyword", text: "[Action]", trigger: true });
  // The marker is consumed, not left behind as its own text token -- the very next
  // token is the glyph that followed it, with nothing "text"-shaped in between.
  assert.equal(tokens[1]?.kind, "exhaust");
});

test("the marker fold still leaves any real gap after it alone", () => {
  // Same shape as the real Akali - Rogue Assassin line, which does have a space
  // before the glyph -- that space must survive as its own token, not be eaten by
  // the fold along with the marker.
  const tokens = tokenizeEffectLine("[Action][>] :rb_exhaust:: do a thing.");
  assert.deepEqual(tokens[0], { kind: "keyword", text: "[Action]", trigger: true });
  assert.deepEqual(tokens[1], { kind: "text", value: " " });
  assert.equal(tokens[2]?.kind, "exhaust");
});

test("[>>] directly after a keyword does not fold -- no real card does that", () => {
  // Every doubled marker in the archive sits between two keyword+marker pairs, never
  // touching a bare keyword. Folding it here would be drawing a shape with no printed
  // card behind it; instead the keyword stays untriggered and the marker becomes its
  // own connector token, same as anywhere else it appears standalone.
  const tokens = tokenizeEffectLine("[Deathknell][>>] get the effect.");
  assert.deepEqual(tokens[0], { kind: "keyword", text: "[Deathknell]", trigger: false });
  assert.deepEqual(tokens[1], { kind: "connector", doubled: true });
});

test("a keyword not immediately followed by [>] is not marked as a trigger", () => {
  // The real Akali - Rogue Assassin line: "[Empowered]" here is followed by a comma
  // and the rest of the sentence, not by "[>]" -- the two are not the same shape and
  // must not be folded just because both are keywords.
  const tokens = tokenizeEffectLine("ready it if I'm [Empowered], ready it.");
  const keyword = tokens.find((t) => t.kind === "keyword");
  assert.deepEqual(keyword, { kind: "keyword", text: "[Empowered]", trigger: false });
});

test("a bare [>] with nothing before it is a standalone connector, not literal text", () => {
  // ">" does not start with a letter, so it was never going to match KEYWORD -- but it
  // is still a marker in its own right, matched by MARKER directly rather than only
  // ever appearing folded into a keyword that precedes it.
  assert.deepEqual(tokenizeEffectLine("[>] on its own"), [
    { kind: "connector", doubled: false },
    { kind: "text", value: " on its own" },
  ]);
});

test("the real chained-condition card: two keywords joined by a doubled connector", () => {
  // Baccai Witherclaw, Honeyfruit and Noxian Emissary all write this exact shape --
  // "[Keyword][>][>>][Keyword][>]" -- to mean "either condition triggers this". The
  // first pair folds; the lone "[>>]" in the middle becomes its own connector; the
  // second pair folds too.
  const tokens = tokenizeEffectLine(
    "[Empowered][>][>>][Deathknell][>] Channel 2 runes exhausted.",
  );
  assert.deepEqual(tokens[0], { kind: "keyword", text: "[Empowered]", trigger: true });
  assert.deepEqual(tokens[1], { kind: "connector", doubled: true });
  assert.deepEqual(tokens[2], { kind: "keyword", text: "[Deathknell]", trigger: true });
  assert.deepEqual(tokens[3], { kind: "text", value: " Channel 2 runes exhausted." });
});

test("the real card whose connector sits behind a space, not touching either side", () => {
  // Honeyfruit: "[Level 6][>] [>>][Reaction][>] ..." -- a literal space before "[>>]"
  // that the other two cards don't have. The connector must still be found and folded
  // correctly regardless of that gap.
  const tokens = tokenizeEffectLine("[Level 6][>] [>>][Reaction][>] :rb_exhaust::");
  assert.deepEqual(tokens[0], { kind: "keyword", text: "[Level 6]", trigger: true });
  assert.deepEqual(tokens[1], { kind: "text", value: " " });
  assert.deepEqual(tokens[2], { kind: "connector", doubled: true });
  assert.deepEqual(tokens[3], { kind: "keyword", text: "[Reaction]", trigger: true });
});

// -- keywords with digits in them --------------------------------------------------
//
// "[Level 6]", "[Assault 2]", "[Predict 2]" -- a character class of only letters,
// spaces and hyphens matched none of these; they rendered as plain, unstyled text,
// which is what "keywords are missing" turned out to mean.

test("a keyword containing a number is recognised", () => {
  assert.deepEqual(tokenizeEffectLine("[Level 6]"), [{ kind: "keyword", text: "[Level 6]", trigger: false }]);
  assert.deepEqual(tokenizeEffectLine("[Assault 2]"), [{ kind: "keyword", text: "[Assault 2]", trigger: false }]);
  assert.deepEqual(tokenizeEffectLine("[Level 11]"), [{ kind: "keyword", text: "[Level 11]", trigger: false }]);
});

test("a numbered keyword still folds an adjacent trigger marker", () => {
  const tokens = tokenizeEffectLine("[Level 6][>] I have +1 :rb_might:.");
  assert.deepEqual(tokens[0], { kind: "keyword", text: "[Level 6]", trigger: true });
});

// -- every glyph kind -----------------------------------------------------------

test("every known rune domain resolves, case-insensitively", () => {
  for (const domain of RUNE_DOMAINS) {
    assert.deepEqual(tokenizeEffectLine(`:rb_rune_${domain}:`), [{ kind: "rune", domain }]);
    assert.deepEqual(
      tokenizeEffectLine(`:RB_RUNE_${domain.toUpperCase()}:`),
      [{ kind: "rune", domain }],
      `uppercase source should still resolve ${domain}`,
    );
  }
});

test("the wild rune is its own kind, not a seventh domain", () => {
  assert.deepEqual(tokenizeEffectLine(":rb_rune_rainbow:"), [{ kind: "rune", domain: "rainbow" }]);
});

test("exhaust and might carry no payload", () => {
  assert.deepEqual(tokenizeEffectLine(":rb_exhaust:"), [{ kind: "exhaust" }]);
  assert.deepEqual(tokenizeEffectLine(":rb_might:"), [{ kind: "might" }]);
});

test("energy keeps its digits, including a double-digit cost", () => {
  assert.deepEqual(tokenizeEffectLine(":rb_energy_0:"), [{ kind: "energy", amount: "0" }]);
  assert.deepEqual(tokenizeEffectLine(":rb_energy_12:"), [{ kind: "energy", amount: "12" }]);
});

// -- what the parser refuses to guess about -------------------------------------

test("a rune domain outside the known six-plus-wild is flagged, not misread", () => {
  const tokens = tokenizeEffectLine(":rb_rune_bogus:");
  assert.deepEqual(tokens, [{ kind: "unknown-glyph", text: ":rb_rune_bogus:" }]);
});

test("an rb_ shortcode outside the whole known vocabulary is flagged the same way", () => {
  // Matters specifically because a narrower matcher (only the known alternatives)
  // would leave a genuinely new upstream token unmatched entirely -- which looks
  // identical, on screen, to a parser that silently stopped noticing new tokens.
  const tokens = tokenizeEffectLine(":rb_something_new:");
  assert.deepEqual(tokens, [{ kind: "unknown-glyph", text: ":rb_something_new:" }]);
});

test("energy with non-digit content is not accepted as a number", () => {
  const tokens = tokenizeEffectLine(":rb_energy_x:");
  assert.deepEqual(tokens, [{ kind: "unknown-glyph", text: ":rb_energy_x:" }]);
});

// -- boundaries -------------------------------------------------------------------

test("an empty line produces no tokens", () => {
  assert.deepEqual(tokenizeEffectLine(""), []);
});

test("plain text with nothing special stays one text token", () => {
  assert.deepEqual(
    tokenizeEffectLine("Deal 3 damage to an enemy unit."),
    [{ kind: "text", value: "Deal 3 damage to an enemy unit." }],
  );
});

test("adjacent glyphs with no text between them produce no empty text token", () => {
  assert.deepEqual(kinds(tokenizeEffectLine(":rb_energy_5::rb_rune_rainbow:")), ["energy", "rune"]);
});

test("brackets that never close are left as plain text, not a runaway match", () => {
  assert.deepEqual(
    tokenizeEffectLine("this has [an open bracket with no close"),
    [{ kind: "text", value: "this has [an open bracket with no close" }],
  );
});
