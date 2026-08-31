/**
 * Cards in the meta.
 *
 * The other Explore views answer "what is winning". This one answers "what is being
 * played", which is the question a deck actually gets built from -- and it is the same
 * data the builder fills from, shown to the player rather than only used behind their
 * back.
 *
 * One number here does not behave like the others, and the whole file is arranged
 * around saying so. A champion's *share* is a partition: every list has exactly one, so
 * the shares sum to 1. A card's *adoption* is not: a list plays forty of them. They are
 * never put side by side, never given the same label, and the wall says out loud what
 * its percentage is a percentage of.
 */

import type { CardDetail, CardHome, CardPartner, CardTrend } from "../api/types";
import { closeCard, openCard, setExploreCardType } from "../state/actions";
import { shareButton } from "./share";
import { store } from "../state/store";
import { h } from "../ui/dom";

const CARD_TYPES = ["", "Unit", "Spell", "Gear", "Rune", "Battlefield"] as const;
const CARD_WALL_PAGE = 30;
let cardWallExpanded = false;

function pct(value: number, digits = 0): string {
  // Something that happens should never render as "0%". A rare split is still a real
  // split, and rounding it away is the same class of small lie as everything else here.
  if (value > 0 && value * 100 < 0.5) return "<1%";
  return `${(value * 100).toFixed(digits)}%`;
}

function movement(value: number | null): HTMLElement | null {
  // No arrow when the sample cannot support one. A direction invented from three lists
  // is worse than no direction, because people act on arrows.
  if (value === null) return null;
  const up = value >= 0;
  return h(
    "span",
    { class: up ? "trend-up" : "trend-down" },
    `${up ? "▲" : "▼"} ${Math.abs(value * 100).toFixed(1)} pts`,
  );
}

function cardArt(imageUrl: string, name: string, className: string): HTMLElement {
  return h(
    "div",
    { class: className },
    imageUrl
      ? h("img", { src: imageUrl, alt: `${name} card`, loading: "lazy" })
      : h("div", { class: "full-card-fallback" }, name.slice(0, 2)),
  );
}

// -- the wall -----------------------------------------------------------------

function cardTile(card: CardTrend): HTMLElement {
  return h(
    "button",
    {
      class: "meta-card-tile",
      type: "button",
      on: { click: () => void openCard(card.cardId) },
    },
    cardArt(card.imageUrl, card.name, "meta-card-art"),
    h(
      "span",
      { class: "meta-card-body" },
      h("span", { class: "meta-card-name" }, card.name),
      h(
        "span",
        { class: "meta-card-stats" },
        h("strong", {}, pct(card.adoption)),
        h("span", {}, " of lists"),
      ),
      h(
        "span",
        { class: "meta-card-sub" },
        `${card.averageCopies.toFixed(1)} copies · ${card.decks} decks`,
        movement(card.momentum),
      ),
    ),
  );
}

function typeFilter(): HTMLElement {
  const current = store.state.exploreCardType;
  return h(
    "div",
    { class: "card-type-filter" },
    ...CARD_TYPES.map((type) =>
      h(
        "button",
        {
          class: `chip-toggle${current === type ? " is-active" : ""}`,
          type: "button",
          aria: { pressed: String(current === type) },
          on: {
            click: () => {
              cardWallExpanded = false;
              void setExploreCardType(type);
            },
          },
        },
        type || "All cards",
      ),
    ),
  );
}

export function cardWall(): HTMLElement {
  const { cardTrends, exploreLoading } = store.state;
  if (!cardTrends) {
    if (!exploreLoading) return h("p", { class: "empty" }, "No card data yet.");
    return h(
      "section",
      { class: "card-wall card-wall-loading", aria: { busy: "true", live: "polite" } },
      h(
        "header",
        { class: "page-hero" },
        h("p", { class: "eyebrow" }, "Cards in the field"),
        h("h1", {}, "Reading the field"),
        h("p", { class: "page-lede" }, "Counting adoption across complete tournament lists…"),
      ),
      h(
        "div",
        { class: "meta-card-grid", aria: { hidden: "true" } },
        ...Array.from({ length: 6 }, (_, index) =>
          h(
            "div",
            { class: "meta-card-skeleton", style: `--skeleton-delay:${index * 70}ms` },
            h("span", { class: "skeleton-art" }),
            h("span", { class: "skeleton-line" }),
            h("span", { class: "skeleton-line is-short" }),
          ),
        ),
      ),
    );
  }
  const visibleCards = cardWallExpanded
    ? cardTrends.series
    : cardTrends.series.slice(0, CARD_WALL_PAGE);
  const remaining = cardTrends.series.length - visibleCards.length;
  return h(
    "section",
    { class: "card-wall" },
    h(
      "header",
      { class: "page-hero" },
      h("p", { class: "eyebrow" }, "Cards in the field"),
      h("h1", {}, "What people are actually playing"),
      h(
        "p",
        { class: "page-lede" },
        "Adoption is the share of published lists that play a card. It is not a share " +
          "of the metagame — a list plays forty cards, so these do not add up to 100%.",
      ),
      h(
        "p",
        { class: "tier-honesty" },
        `${cardTrends.chartedDeckCount.toLocaleString()} complete lists from ` +
          `${cardTrends.tournamentCount} tournaments, ` +
          `${pct(cardTrends.publishedCoverage)} of the players who entered them.`,
      ),
    ),
    typeFilter(),
    h("div", { class: "meta-card-grid" }, ...visibleCards.map(cardTile)),
    remaining > 0
      ? h(
          "button",
          {
            class: "show-more",
            type: "button",
            on: {
              click: () => {
                cardWallExpanded = true;
                store.set({});
              },
            },
          },
          `Show ${remaining} more cards`,
        )
      : null,
  );
}

// -- one card -----------------------------------------------------------------

/**
 * How many copies people run.
 *
 * The average is the number everyone quotes and the one that misleads: a card split
 * evenly between one-ofs and three-ofs averages two, which is the one count nobody
 * plays. The split is the shape of the decision.
 */
function copiesSplit(detail: CardDetail): HTMLElement {
  const total = detail.trend.decks || 1;
  const rows = detail.copiesSplit;
  const peak = Math.max(...rows.map(([, decks]) => decks ?? 0), 1);
  return h(
    "section",
    { class: "atlas-panel" },
    h("h3", {}, "Copies people run"),
    h(
      "ul",
      { class: "copies-split" },
      ...rows.map(([copies, decks]) =>
        h(
          "li",
          {},
          h("span", { class: "copies-label" }, `${copies}×`),
          h(
            "span",
            { class: "copies-track" },
            h("span", {
              class: "copies-fill",
              style: `width:${Math.round(((decks ?? 0) / peak) * 100)}%`,
            }),
          ),
          h("span", { class: "copies-value" }, `${pct((decks ?? 0) / total)}`),
        ),
      ),
    ),
    h(
      "p",
      { class: "atlas-note" },
      `Averages ${detail.trend.averageCopies.toFixed(2)}, which is worth less than the split above.`,
    ),
  );
}

function homeList(title: string, homes: CardHome[]): HTMLElement | null {
  if (!homes.length) return null;
  return h(
    "section",
    { class: "atlas-panel" },
    h("h3", {}, title),
    h(
      "ul",
      { class: "home-list" },
      ...homes.map((home) =>
        h(
          "li",
          { class: "home-row" },
          cardArt(home.imageUrl, home.name, "home-art"),
          h(
            "span",
            { class: "home-copy" },
            h("span", { class: "home-name" }, home.name),
            h("span", { class: "home-meta" }, `${home.decks} decks · ${pct(home.shareOfCard)} of its use`),
          ),
        ),
      ),
    ),
  );
}

/**
 * What the field plays alongside it.
 *
 * Ranked by lift rather than raw co-occurrence, so the most-played card in the format
 * does not top every list and tell nobody anything. This is the deck-building payoff:
 * these are the cards the builder itself reaches for when it fills around this one.
 */
function partnerList(partners: CardPartner[]): HTMLElement | null {
  if (!partners.length) return null;
  return h(
    "section",
    { class: "atlas-panel" },
    h("h3", {}, "Played alongside"),
    h(
      "p",
      { class: "atlas-note" },
      "Ranked by how much more often these appear together than chance would give, so " +
        "format staples do not crowd out real pairings.",
    ),
    h(
      "ul",
      { class: "partner-list" },
      ...partners.map((partner) =>
        h(
          "li",
          {
            class: "partner-row",
            on: { click: () => void openCard(partner.cardId) },
          },
          cardArt(partner.imageUrl, partner.name, "home-art"),
          h(
            "span",
            { class: "home-copy" },
            h("span", { class: "home-name" }, partner.name),
            h(
              "span",
              { class: "home-meta" },
              `in ${pct(partner.togetherRate)} of its decks`,
              h(
                "span",
                { class: partner.lift >= 1.5 ? "lift-strong" : "lift-mild" },
                ` · ${partner.lift.toFixed(1)}× chance`,
              ),
            ),
          ),
        ),
      ),
    ),
  );
}

export function cardView(detail: CardDetail): HTMLElement {
  const card = detail.trend;
  return h(
    "article",
    { class: "detail-page dossier-page" },
    h(
      "div",
      { class: "detail-bar" },
      h(
        "button",
        { class: "quiet-button back-link", type: "button", on: { click: closeCard } },
        "← All cards",
      ),
      shareButton("this card"),
    ),
    h(
      "header",
      { class: "dossier-hero" },
      cardArt(card.imageUrl, card.name, "dossier-card"),
      h(
        "div",
        { class: "dossier-copy" },
        h("p", { class: "eyebrow" }, "RiftDesk · card intelligence"),
        h("h1", {}, card.name),
        h(
          "p",
          { class: "dossier-domains" },
          [card.cardType, card.rarity, card.cost === null ? "" : `Cost ${card.cost}`]
            .filter(Boolean)
            .join(" · "),
        ),
        h(
          "p",
          { class: "page-lede" },
          `Played in ${card.decks} complete lists across ${card.eventCount} tournaments.`,
        ),
        h(
          "div",
          { class: "dossier-signal" },
          h("span", { class: `confidence confidence-${card.confidence}` },
            card.confidence === "high" ? "Strong sample"
              : card.confidence === "moderate" ? "Useful sample" : "Limited sample"),
          h("span", {}, `${pct(card.adoption, 1)} of published lists`),
          movement(card.momentum),
        ),
      ),
    ),
    h(
      "div",
      { class: "explore-columns" },
      copiesSplit(detail),
      partnerList(detail.partners),
      homeList("Legends that play it", detail.legends),
      homeList("Champions that play it", detail.champions),
    ),
  );
}
