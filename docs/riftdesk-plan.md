# RiftDesk product plan

Status: implemented and verified on August 26, 2026.

## Product direction

RiftDesk is a tactile, focused deck studio for Riftbound players. It should help a
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

Each legend carries a **rating from 0 to 100** and its rank in the field. The rating is
relative published-list presence (58), event breadth (27) and recent movement (15), each
normalised against the field — so 100 means leading on all three at once and 0 means no
lists in the selected range. S/A/B/C/D rows are percentile slices of that one ordering,
which makes the tier a reading aid and the rating the ranking; two legends either side of
a cut can be a point apart.

The rating is then read through a curve so it lands where a reader expects a grade to.
Presence is power-law distributed — the leading legend holds three times the share of the
fifth — so measured linearly against the leader the whole field collapses into the bottom
quarter: a median of 18 and a top-five deck reading 37. The curve is applied to the total,
never to the components, because a monotonic curve on the total cannot reorder anything
while curving each component separately silently re-weights them against each other. The
field now spans roughly 47–99 with a median near 60, and the top five read 99 / 92 / 85 /
82 / 79.

The card shows the rating, the rank, the sample behind it (`303 lists · 68 events`) and
the win rate. It does not also print the share and the momentum delta the rating is made
of — three restatements of one number is not more information.

There is no "uncharted" row. A legend the range cannot see is rated 0 but still ranked,
ordered against the other dormant ones by what the whole archive still knows about it —
prior momentum first, then prior share, then how recently it was last seen — and its card
says "Last seen 2026-07-26" rather than presenting the zero as a measurement. Shortening
the range from 90 days to 30 therefore reorders the wall instead of emptying part of it.

Tiers remain presence only — win rate is shown beside them as a separate figure and is
never folded into the rating, because the two orderings disagree and the disagreement is
the useful part (see `docs/deck-performance-plan.md`). The rating is computed server-side
(`domain/meta_trends/ranking.py`); a client renders it and never re-derives it.
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

### Deck performance

Every ranked entity carries a win rate where the sample supports one: the rate, the match
count, and a 95% Wilson interval, scoped to a declared banned-list era. Roughly a third of
the field clears the bar; the rest show their match count and an explicit reason they
cannot yet be ranked. Every rate is labelled as a rate among *published lists*, with the
measured publication bias printed beside it rather than hidden in a tooltip.

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

Win rates come from the match records carried on tournament standings and obey the same
rule. The denominator is decisive matches; draws count as matches but not as losses; a
rate is withheld rather than shown small when the sample cannot support it. The
population is published lists, never the field — the response carries the win rate of
both the published and the unpublished halves of the same events, so a client can show
the gap rather than being asked to trust a caveat.

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
2. Add RiftDesk tokens, shell, navigation, and persistent theme control.
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
