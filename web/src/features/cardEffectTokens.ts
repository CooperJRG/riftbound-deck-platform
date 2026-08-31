/**
 * Turning one line of rules text into a sequence of typed pieces.
 *
 * Deliberately has no DOM dependency -- not even `h()`. `cardSymbols.ts` vendors icon
 * SVGs via `DOMParser`, which does not exist under Node, so a browser-only module
 * cannot be imported from `node --test`. Splitting the parsing out here is what lets
 * the actual scanning logic -- the part with edge cases worth pinning -- run under
 * `npm test` rather than only ever being checked by eye in a browser.
 */

export type EffectToken =
  | { kind: "text"; value: string }
  | { kind: "energy"; amount: string }
  | { kind: "exhaust" }
  | { kind: "might" }
  | { kind: "rune"; domain: string }
  /** `trigger` is set when this keyword is immediately followed by `[>]` or `[>>]`
   * with nothing between them -- "[Action][>]", "[Empowered][>]", "[Level 6][>]".
   * On the printed card that pair is one continuous banner with a pointed trailing
   * edge, not a keyword followed by a literal ">" glyph; nothing in the vocabulary
   * this parser knows maps `>` to a real icon, so the marker is folded into this
   * token rather than emitted as its own, and the renderer draws the point as a
   * shape rather than guessing at an image for it. */
  | { kind: "keyword"; text: string; trigger: boolean }
  /** `[>]` or `[>>]` on its own, not immediately touching the keyword before it.
   * Three real cards chain two condition-keywords as
   * "[Keyword][>][>>][Keyword][>]" -- the doubled marker in the middle sits between
   * a folded keyword+marker pair and the next keyword, never adjacent to either, so
   * it cannot fold the way a single marker right after one keyword does. Recognised
   * on its own so it renders as a small connector instead of literal "[>>]" text. */
  | { kind: "connector"; doubled: boolean }
  /** A `:rb_...:` shortcode this parser does not recognise -- upstream added a new
   * one, or the id was mistyped. Kept as literal text rather than dropped, so a gap
   * is visible on the card and reportable instead of silently vanishing. */
  | { kind: "unknown-glyph"; text: string };

export const RUNE_DOMAINS = ["body", "calm", "chaos", "fury", "mind", "order"] as const;
const RUNE_DOMAIN_SET = new Set<string>(RUNE_DOMAINS);

// Matches any `:rb_...:` shape, not only the vocabulary this parser currently knows.
// A narrower alternation (`energy_\d+|exhaust|might|rune_\w+`) would leave an upstream
// addition -- a new keyword icon, a typo'd id -- unmatched entirely, which looks
// identical to matching it and choosing to show it literally: both leave the colons in
// the text. The difference only shows up in `unknown-glyph` actually being reachable,
// so a future card can be told apart from a parser that quietly stopped noticing it.
const GLYPH = /:rb_([a-z0-9_]+):/gi;
/** `[Action]`, `[Empowered]`, `[Level 6]`, `[Quick-Draw]` -- the game's named
 * keywords, as upstream writes them into the text. Digits are part of the
 * vocabulary ("Level 6", "Assault 2", "Predict 2"), not just letters/spaces/hyphens
 * -- a narrower character class here is what left those unstyled before. */
const KEYWORD = /\[([A-Za-z][A-Za-z0-9 \-]*)\]/g;
/** `[>]` or `[>>]`, matched as its own pattern wherever it appears in the line -- not
 * only immediately after a keyword. Participates in the same earliest-match scan as
 * GLYPH and KEYWORD below; a marker touching the keyword just matched is claimed by
 * that keyword's own fold instead (see `tokenizeEffectLine`), so this only ever
 * produces a standalone "connector" token for the cases that fold cannot explain. */
const MARKER = /\[(>{1,2})\]/g;
/** The single-arrow case specifically, checked with zero gap right after a keyword
 * match. Only a single arrow folds -- every doubled marker in the real archive sits
 * between two keyword+marker pairs, never touching a bare keyword, so there is no
 * evidence a keyword directly followed by "[>>]" should draw the same way. */
const ADJACENT_SINGLE_MARKER = /^\[>\]/;

function glyphToken(match: RegExpExecArray): EffectToken {
  const [full, id] = match;
  const name = (id ?? "").toLowerCase();
  if (name === "exhaust") return { kind: "exhaust" };
  if (name === "might") return { kind: "might" };
  if (name.startsWith("energy_")) {
    const amount = name.slice("energy_".length);
    if (/^\d+$/.test(amount)) return { kind: "energy", amount };
  } else if (name.startsWith("rune_")) {
    const domain = name.slice("rune_".length);
    if (domain === "rainbow" || RUNE_DOMAIN_SET.has(domain)) return { kind: "rune", domain };
  }
  return { kind: "unknown-glyph", text: full };
}

type Candidate =
  | { pattern: "glyph"; match: RegExpExecArray }
  | { pattern: "keyword"; match: RegExpExecArray }
  | { pattern: "marker"; match: RegExpExecArray };

function earliestMatch(line: string, cursor: number): Candidate | null {
  GLYPH.lastIndex = cursor;
  KEYWORD.lastIndex = cursor;
  MARKER.lastIndex = cursor;
  const candidates: Candidate[] = [];
  const glyph = GLYPH.exec(line);
  if (glyph) candidates.push({ pattern: "glyph", match: glyph });
  const keyword = KEYWORD.exec(line);
  if (keyword) candidates.push({ pattern: "keyword", match: keyword });
  const marker = MARKER.exec(line);
  if (marker) candidates.push({ pattern: "marker", match: marker });
  if (!candidates.length) return null;
  return candidates.reduce((a, b) => (a.match.index <= b.match.index ? a : b));
}

/**
 * One line, scanned once, left to right. `:rb_*:` glyphs, `[Keyword]` brackets and
 * `[>]`/`[>>]` markers are different syntax and cannot overlap, but they can appear in
 * any order on the same line -- "[Flow] :rb_energy_5::rb_rune_rainbow:" puts the
 * keyword first, while most cards put a glyph first ("+2 :rb_might: this turn"). A
 * version of this that scanned for `:rb_*:` across the whole line and only then looked
 * for keywords in what was left missed every keyword written before a glyph -- exactly
 * the `[Flow]` case. Scanning for whichever pattern matches earliest, one match at a
 * time, handles any order by construction instead of by which pattern happens to run
 * first.
 */
export function tokenizeEffectLine(line: string): EffectToken[] {
  const tokens: EffectToken[] = [];
  let cursor = 0;
  while (cursor < line.length) {
    const next = earliestMatch(line, cursor);
    if (!next) {
      tokens.push({ kind: "text", value: line.slice(cursor) });
      break;
    }
    if (next.match.index > cursor) {
      tokens.push({ kind: "text", value: line.slice(cursor, next.match.index) });
    }
    cursor = next.match.index + next.match[0].length;
    if (next.pattern === "glyph") {
      tokens.push(glyphToken(next.match));
      continue;
    }
    if (next.pattern === "marker") {
      tokens.push({ kind: "connector", doubled: next.match[1] === ">>" });
      continue;
    }
    const adjacent = ADJACENT_SINGLE_MARKER.exec(line.slice(cursor));
    const trigger = adjacent !== null;
    if (trigger) cursor += adjacent[0].length;
    tokens.push({ kind: "keyword", text: next.match[0], trigger });
  }
  return tokens;
}
