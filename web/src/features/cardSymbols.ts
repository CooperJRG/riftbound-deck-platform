/**
 * Rules text carries its own markup, and until now nothing read it.
 *
 * Upstream's `effect` field embeds two conventions verbatim: `:rb_energy_5:`-style
 * shortcodes for icons the printed card shows as pips and glyphs, and `[Keyword]`
 * tags for the game's named abilities. Rendered as plain text -- which is all
 * `cardPreview.ts` did before this module -- a card reads "+2 :rb_might: this turn"
 * instead of showing the might icon, and every reminder-text keyword sits in the same
 * weight as the sentence around it.
 *
 * The icon set is vendored rather than hot-linked. Card art is hot-linked throughout
 * this app because it lives on a stable game CDN this project doesn't control either
 * way; these are a dozen icons under 2KB combined, sourced from the League of Legends
 * wiki's `Category:RB_icons` (file names `RB_might_icon.svg`, `RB_exhaust_icon.svg`,
 * `RB_wild_rune_icon.svg` -- a direct match to the `rb_*` token vocabulary, confirming
 * these are extracted from the game's own icon set rather than a wiki editor's
 * approximation). Vendoring means no third-party request on every card read, and no
 * blank glyph if that wiki reorganizes its files.
 *
 * Rune-domain glyphs deliberately do *not* re-derive their own palette. `.card-glyph-
 * rune` (in riftdesk.css) is combined with the same `.domain-{name}` classes
 * `domainMarks()` already renders domain pills with in `explore.ts`, so the color comes
 * from there -- a second, almost-but-not-quite-matching palette pulled from the wiki's
 * raw SVGs would be a worse outcome than sharing the one this app already settled on,
 * in the one dimension it doesn't already have to be pixel-identical.
 */

import { h } from "../ui/dom";
import { tokenizeEffectLine, type EffectToken } from "./cardEffectTokens";

/**
 * Parsed once from a trusted, hardcoded string -- never from card text or any other
 * value that reaches this module from outside it. That is what makes this different
 * from the `innerHTML`-free rule the rest of the UI follows: nothing here interprets
 * data as markup, only these fixed literals, matching how a bundled image asset would
 * be trusted if the build could import SVGs directly.
 */
function parseSvg(source: string): SVGSVGElement {
  const doc = new DOMParser().parseFromString(source, "image/svg+xml");
  const node = doc.documentElement;
  if (!(node instanceof SVGSVGElement)) {
    throw new Error("cardSymbols: a vendored icon failed to parse as SVG");
  }
  return node;
}

// Both recolored to `currentColor` in place of the wiki source's fixed `white` fill,
// so the glyph reads correctly in both themes and inside colored text without a
// second copy of the asset.
const MIGHT_SVG = parseSvg(`<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
<path d="M15.7938 7.88519L16.7882 15.8057L11.8849 21.0175L6.98178 15.8057L7.97616 7.88519C4.30733 6.95941 2.25 4.35352 2.25 4.35352V11.3825C2.25 13.4055 2.86722 15.4286 3.99873 17.2116C5.54169 19.6117 8.11326 22.629 11.8849 24.0005C15.6566 22.629 18.2283 19.6117 19.7713 17.2116C20.9371 15.4286 21.5199 13.4055 21.5199 11.3825V4.45638C21.5199 4.45638 19.2226 6.95937 15.7252 7.85087L15.7938 7.88519Z" fill="currentColor"/>
<path d="M15.7942 5.93188C15.7942 4.80037 14.8684 3.87457 13.7369 3.87457H13.0169L12.6055 1.57733C12.9826 1.44018 13.257 1.1658 13.257 0.857203C13.257 0.377169 12.6397 0 11.8854 0C11.131 0 10.5138 0.377169 10.5138 0.857203C10.5138 1.1658 10.7882 1.44018 11.1653 1.57733L10.7539 3.87457H10.0339C8.90236 3.87457 7.97656 4.80037 7.97656 5.93188H10.5138L9.45093 14.9153L11.8511 17.4184L14.2512 14.9153L13.1883 5.93188H15.7599H15.7942Z" fill="currentColor"/>
</svg>`);

const EXHAUST_SVG = parseSvg(`<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
<path d="M18.7085 8.47119H20.2591C20.6636 8.47119 20.967 8.80824 20.967 9.17903V10.4263H24.0006V9.17903C24.0006 7.12284 22.3153 5.4375 20.2591 5.4375H17.6973C18.1355 6.38132 18.4725 7.39254 18.7085 8.47119Z" fill="currentColor"/>
<path d="M20.968 15.6172V20.2016C20.968 20.6061 20.6308 20.9094 20.26 20.9094H16.451L14.2264 23.4712L12.0353 20.9094H4.28254C3.87805 20.9094 3.5746 20.5724 3.5746 20.2016V10.9319L3.17012 10.4599H3.5746V9.21277C3.5746 8.80827 3.87805 8.50493 4.28254 8.50493H9.00152C8.9004 7.9656 8.76555 7.42627 8.5633 6.92066C8.32735 6.31391 8.05772 5.84199 7.75435 5.4375H4.28254C2.22636 5.4375 0.541016 7.12284 0.541016 9.17903V20.1678C0.541016 22.224 2.22636 23.9095 4.28254 23.9095H20.26C22.3162 23.9095 24.0016 22.224 24.0016 20.1678V12.0442L20.968 15.5836V15.6172Z" fill="currentColor"/>
<path d="M16.9887 12.6183C16.9887 10.0565 16.5169 7.89925 15.6068 6.11273C14.427 3.75318 12.6067 2.10148 10.3146 1.25879C3.91011 -0.763689 0.0337079 3.82051 0 3.92163C2.46068 1.93287 6.43825 2.06769 7.41578 2.5396C9.03376 3.28117 9.97762 4.49475 10.6181 6.11273C11.4608 8.27003 11.5955 10.8992 11.5618 12.6183H7.88774L14.2248 20.1015L20.6292 12.6183H16.9887Z" fill="currentColor"/>
<path d="M3.5389 9.88672H2.89844V11.471H3.5389V9.88672Z" fill="currentColor"/>
</svg>`);

// The wild/rainbow rune keeps its source gradient rather than moving to
// `currentColor`: it represents "any domain", so unlike the might/exhaust glyphs it
// has no single ink color that would mean the same thing.
const WILD_RUNE_SVG = parseSvg(`<svg viewBox="0 0 13 16" xmlns="http://www.w3.org/2000/svg">
<defs>
<linearGradient id="rb-wild-g1" x2="1" gradientUnits="userSpaceOnUse" gradientTransform="matrix(5.325,7.607,-7.766,5.436,2.693,2.662)">
<stop offset=".14" stop-color="#e5362c"/><stop offset=".38" stop-color="#ec6812"/><stop offset=".54" stop-color="#e4bf00"/><stop offset=".68" stop-color="#22ac39"/><stop offset=".83" stop-color="#056fb8"/>
</linearGradient>
<linearGradient id="rb-wild-g2" x2="1" gradientUnits="userSpaceOnUse" gradientTransform="matrix(5.04,7.179,-7.768,5.453,5.713,6.159)">
<stop offset=".14" stop-color="#e5362c"/><stop offset=".38" stop-color="#ec6812"/><stop offset=".54" stop-color="#e4bf00"/><stop offset=".68" stop-color="#22ac39"/><stop offset=".83" stop-color="#056fb8"/>
</linearGradient>
</defs>
<path fill="url(#rb-wild-g1)" d="m6.59 0.02q0.18 0.08 0.22 0.27 0.07 0.42 0.11 0.87c0.05 0.5 0.05 1 0.1 1.5q-0.01 0.38-0.19 0.69c-0.21 0.33-0.5 0.64-0.79 0.93-0.54 0.55-1.11 1.07-1.66 1.62-0.28 0.28-0.57 0.61-0.81 0.92q-0.21 0.26-0.31 0.6-0.13 0.31 0.1 0.59c0.14 0.24 0.36 0.41 0.57 0.57q0.86 0.62 1.9 0.88c0.26 0.07 0.52 0 0.74-0.17q0.47-0.34 0.62-0.9 0.06-0.29-0.1-0.55c-0.09-0.14-0.24-0.23-0.4-0.21q-0.35 0.04-0.69 0.12c-0.12 0-0.22 0-0.34-0.05q-0.25-0.11-0.42-0.33c-0.12-0.17-0.12-0.29 0-0.45q0.42-0.65 1.02-1.12c0.12-0.09 0.24-0.14 0.38-0.21 0.14-0.07 0.26-0.05 0.4 0.02q0.22 0.14 0.43 0.31c0.52 0.47 1.05 1 1.4 1.62q0.14 0.26 0.24 0.52 0.07 0.15 0 0.33-0.1 0.26-0.24 0.52-0.54 0.96-1.33 1.69c-0.43 0.41-0.95 0.55-1.52 0.48-0.93-0.1-1.76-0.41-2.59-0.79-0.64-0.31-1.24-0.66-1.76-1.14-0.26-0.24-0.5-0.47-0.66-0.76q-0.18-0.29-0.24-0.62v-0.28c0.09-0.5 0.4-0.88 0.71-1.24 0.26-0.26 0.5-0.54 0.79-0.78 0.97-0.91 1.87-1.86 2.63-2.95q0.9-1.21 1.64-2.52h0.15z"/>
<path fill="url(#rb-wild-g2)" d="m6.88 15.95c-0.19-0.05-0.26-0.19-0.31-0.35q-0.15-0.52-0.26-1.03c-0.07-0.38-0.07-0.76 0.09-1.11 0.1-0.24 0.29-0.46 0.45-0.65q0.66-0.7 1.38-1.3c0.72-0.62 1.4-1.24 1.95-2.02q0.26-0.37 0.48-0.74c0.12-0.17 0.09-0.36 0-0.55-0.22-0.45-0.5-0.88-0.79-1.28-0.35-0.52-0.81-0.98-1.23-1.45q-0.23-0.25-0.46-0.5-0.07-0.11-0.14-0.21c-0.07-0.12 0-0.27 0.12-0.29q0.14 0 0.29 0 0.29 0.1 0.54 0.24c0.98 0.57 1.93 1.21 2.76 2.02q0.39 0.39 0.74 0.85 0.28 0.33 0.38 0.77v0.23c-0.12 0.43-0.36 0.79-0.62 1.12q-0.29 0.35-0.57 0.67-0.97 1.09-1.9 2.18-1.39 1.73-2.78 3.45h-0.15z"/>
</svg>`);

function iconSpan(svg: SVGSVGElement, label: string): HTMLElement {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("aria-hidden", "true");
  clone.setAttribute("focusable", "false");
  return h("span", { class: "card-glyph", role: "img", aria: { label } }, clone);
}

/** `:rb_energy_5:` -> a small numbered pip, matching the cost badge already printed
 * on every card face elsewhere in this app. There is no per-number upstream asset --
 * the physical card doesn't need one, since it draws its own numeral -- so this reuses
 * that existing visual language instead of inventing a thirteenth icon file. */
function energyPip(amount: string): HTMLElement {
  return h(
    "span",
    { class: "card-glyph card-glyph-energy", role: "img", aria: { label: `${amount} energy` } },
    amount,
  );
}

function runeDot(domain: string): HTMLElement {
  if (domain === "rainbow") return iconSpan(WILD_RUNE_SVG, "any domain rune");
  const label = `${domain[0]?.toUpperCase()}${domain.slice(1)} rune`;
  return h("span", { class: `card-glyph card-glyph-rune domain-${domain}`, role: "img", aria: { label } });
}

/**
 * Power, the way the printed card actually shows it: one small colored pip per point,
 * stacked -- never a printed numeral. Checked against real card art rather than
 * assumed: Ahri - Alluring (1 Calm power) prints one green pip; Alpha Wildclaw
 * (2 Calm) prints two, stacked; a card in two domains (Daisy, 2 in Calm/Order) prints
 * two pips each split evenly between both domains' colors, not two single-color pips.
 * A text line reading "2 Calm/Order power" was correct in words and still looked wrong
 * next to it -- this is the fix, not a rewording.
 *
 * Each slice reuses `.domain-{name}` for its color, the same class `domainMarks()` and
 * the rune glyphs above it both already pull from -- so this never becomes a third,
 * slightly-different domain palette to keep in sync with the other two.
 */
function powerPip(domains: string[]): HTMLElement {
  const slices = domains.length ? domains : ["rainbow"];
  return h(
    "span",
    { class: "power-pip" },
    ...slices.map((domain) => h("span", { class: `power-pip-slice domain-${domain.toLowerCase()}` })),
  );
}

export function renderPowerPips(power: number, domains: string[]): HTMLElement {
  const names = domains.length ? domains.join("/") : "any domain";
  const label = `${power} ${names} power`;
  return h(
    "span",
    { class: "card-glyph card-glyph-power", role: "img", aria: { label } },
    ...Array.from({ length: Math.max(0, power) }, () => powerPip(domains)),
  );
}

/** One parsed token, rendered as the real DOM node a player should see. `text` and
 * `unknown-glyph` both come back as plain strings -- the literal source, exactly as
 * `:rb_...:` shortcodes not yet in this vocabulary or a keyword outside brackets. */
function renderToken(token: EffectToken): string | Node {
  switch (token.kind) {
    case "text":
      return token.value;
    case "unknown-glyph":
      return token.text;
    case "energy":
      return energyPip(token.amount);
    case "exhaust":
      return iconSpan(EXHAUST_SVG, "exhaust");
    case "might":
      return iconSpan(MIGHT_SVG, "might");
    case "rune":
      return runeDot(token.domain);
    case "keyword": {
      // Brackets stripped here, unlike an earlier version of this renderer: checked
      // against real printed cards (Akali - Rogue Assassin, Akali - Deadly Weapon),
      // "EMPOWER" and "ACTION" print as plain badge labels with no brackets shown,
      // so keeping them was the thing making this look wrong, not a safe hedge.
      const label = token.text.slice(1, -1);
      const cls = token.trigger ? "card-keyword card-keyword-trigger" : "card-keyword";
      return h("strong", { class: cls }, label);
    }
    case "connector":
      // "[Keyword][>][>>][Keyword][>]" chains two condition-keywords together; this
      // is the "[>>]" in the middle. There is no confirmed icon for it -- the
      // printed cards this module was checked against don't include this shape at
      // all -- so a plain typographic arrow stands in rather than a guessed image.
      // Two arrows for "[>>]" for the same reason the source used two brackets: it
      // reads as a stronger separator than one, without claiming to know why.
      return h(
        "span",
        { class: "card-connector", aria: { hidden: "true" } },
        token.doubled ? "››" : "›",
      );
  }
}

/** The full `effect` field, one paragraph per source line, glyphs and keywords live. */
export function renderCardEffect(text: string): HTMLElement[] {
  return text
    .split("\n")
    .map((line) => h("p", {}, ...tokenizeEffectLine(line).map(renderToken)));
}
