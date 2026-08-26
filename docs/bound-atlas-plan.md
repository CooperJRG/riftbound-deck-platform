# Bound Atlas product plan

Status: implemented and verified on August 26, 2026.

## Product direction

Bound Atlas is a warm, editorial field guide for Riftbound players. It should help a
player answer one question at a time:

1. What can I build?
2. What is moving in tournaments?
3. How do I tune this list?
4. Where are the decks I saved?

The interface favors explanation over density. Competitive evidence stays visible, but
the product never presents a published-deck sample as if it described an entire field.

## Experience principles

- **One task per page.** Global navigation has four destinations and no nested product
  map to learn.
- **Context before compression.** A deck list stays visible as one grouped object;
  identity, main deck, runes, battlefields, and possible swaps are never split into
  arbitrary pages. Progressive disclosure is reserved for advanced filters and rule
  detail, not the cards themselves.
- **Card art is the interface.** Legends, champions, staples, and deck evidence use
  complete card proportions and readable art. Text explains the cards instead of
  replacing them with abstract rows.
- **Evidence before authority.** Placements, event counts, list coverage, source links,
  and confidence labels accompany meta claims.
- **Missing means unknown.** An incomplete or unresolved deck is dismissed gracefully;
  it does not become a zero, a loss, or evidence for an unknown champion.
- **Useful defaults.** The leading legends, recent 90-day trends, events with at least
  16 players, and weekly intervals form the initial view.
- **A calm first screen.** Empty builders provide a next step instead of five errors.

## Information architecture

### Find a deck

The default destination. It starts with a searchable, quality-ranked legend picker.
Selecting a legend opens the whole candidate deck as a visual decision map. Identity,
main-deck cards, runes, battlefields, and possible swaps are grouped into continuous
sections, with full card art and ownership controls in context. The strongest deck that
can already be promised remains visible, so a player can stop early and still leave
with a useful result.

### Explore

An interactive, full-art tier wall containing every legend in the local card catalog.
S, A, B, C, and uncharted rows are computed from relative published-list presence,
event breadth, and recent movement. The page explicitly does not claim a win rate.
Format, date range, minimum event size, and weekly/monthly controls live in one compact
filter drawer so the field remains the focus.

Selecting a legend opens a dedicated field guide containing:

- a large, uncropped legend card and domain identity;
- tournament-presence tier, sample confidence, and finishing evidence;
- every observed champion build as selectable full card art;
- the recurring core package as a visual card gallery;
- presence over time;
- recent complete decks with paired legend/champion art, placement, source, import,
  and tournament links.

Selecting a champion then opens its own guide containing:

- published-list share over time;
- sample confidence and event count;
- top-eight and top-sixteen finishes;
- full-art legend homes;
- card adoption and average copies;
- recent complete lists with placement, source, import, and tournament links.

Tournament links open an event guide with explicit list coverage, a champion
distribution for complete published lists only, and a bounded evidence list.

### Build

The builder starts with 24 cards and exposes search and type first. Domain, set, rarity,
and sorting live under **More filters**. More cards load in 24-card increments.

The deck panel opens with one instruction: choose a legend. It tracks five milestones
without showing structural rule failures as an error wall. Full legality and collection
coverage appear only after **Review deck** is selected.

### My decks

A dedicated library replaces the library embedded under every builder session. Each
saved deck has a clear open action and restrained secondary delete action. The empty
state points to either the guided finder or a blank builder.

## Design language

### Light palette

| Token | Value | Use |
| --- | --- | --- |
| Canvas | `#F5F1E8` | Page field |
| Surface | `#FFFDF8` | Cards and working panels |
| Raised | `#F1E9DC` | Secondary emphasis |
| Ink | `#20252B` | Primary type |
| Muted | `#66707A` | Explanations and metadata |
| Copper | `#B65A1A` | Primary action and editorial marker |
| Teal | `#237A75` | Evidence, links, and selected analysis controls |
| Border | `#DDD3C4` | Quiet structure |

### Dark palette

The dark theme uses canvas `#151718`, surface `#1E2223`, raised `#272C2D`, ink
`#F1EEE7`, copper `#E38A45`, teal `#62BDB4`, and border `#343B3C`. The light/dark
preference is stored locally and applied before the interface paints to prevent a theme
flash.

### Type and texture

Editorial headings use a readable serif stack; interface text uses a system sans stack.
Subtle radial color and low-opacity paper grain keep the field-guide character without
competing with cards and charts. Borders carry most structure; shadows are reserved for
menus and lifted interactive states.

## Tournament data contract

Trend shares use complete, tournament-sourced deck lists with a resolved champion,
legend, and date. They do not use total attendance as the denominator. Every overview
returns both populations:

- tournament and recorded-standing counts;
- complete published-list count;
- known field attendance;
- published-list coverage;
- per-entity list share, event count, momentum, and confidence.

Movement waits for two intervals containing at least 20 complete lists. Chart lines omit
intervals with fewer than 10 lists. The raw counts remain in the response so other local
clients can choose a different presentation while retaining the evidence.

## Responsive and accessibility behavior

- Navigation remains keyboard reachable and horizontally scrollable on narrow screens.
- All stateful controls expose pressed state or a visible label.
- Charts have an accessible name, point-level descriptions, and a complete table view.
- At mobile widths the deck checklist precedes card search in separate grid rows; no
  panel uses an overlapping nested scroll region.
- Color is never the only evidence signal: trend direction, confidence, legality, and
  coverage all include text.
- Focus rings use the analysis teal at sufficient visual weight in both themes.

## Delivery sequence

1. Baseline the existing Python and TypeScript builds.
2. Add Bound Atlas tokens, shell, navigation, and persistent theme control.
3. Add presentation-neutral trend aggregation and typed API schemas.
4. Cover honest denominators, champion details, and tournament details with tests.
5. Build the full-art tier wall plus legend, champion, and tournament drill-downs.
6. Replace paged finder decisions with a whole-deck visual map, then refine the
   progressive builder and deck library.
7. Verify complete card proportions, production behavior, theme handling, and the
   primary interaction paths in headed desktop and mobile browsers.

## Acceptance record

- Full Python test suite passes.
- TypeScript typecheck and Vite production build pass.
- Trend, legend, champion, and tournament endpoints respond from the live local service.
- Desktop Find, full tier wall, legend, champion, tournament, Build, and My decks flows
  were exercised.
- Explore renders all 49 legends in one continuous tier field, including an explicit
  uncharted state when no complete list exists in the selected range.
- Mobile builder layout was inspected at 390 × 844 with no panel overlap.
- Light/dark preference survives reload.
- Browser console reports no errors or warnings in final desktop and mobile passes.
