# UI Plan: Golden-Hour Glass Table

Date: 2026-02-17  
Status: Superseded

Superseded by:
- `planning/ui-skeuomorphic-90s-2000s-plan.md`

## Goal

Create a deck-building experience that feels like working with physical cards on a glass table in a modern home at golden hour:
- Warm, natural light
- Premium frosted-glass surfaces
- Tactile card-centric interactions
- High clarity for validation and collection decisions

## Product Intent

Primary UX outcomes:
1. Build a deck visually with card art, not text-first lists.
2. See legality/completeness instantly while editing.
3. Switch between collection, deck, and meta workflows with minimal friction.

## Visual Direction

Atmosphere:
- Warm neutrals + amber sunlight accents
- Frosted panels with subtle reflections
- Soft long shadows and layered depth

UI style rules:
- Card images are first-class in all deck/collection/meta views.
- Validation states are color and icon encoded (`ok`, `warn`, `error`).
- Motion is purposeful (drag transitions, card hover lift, panel reveal).

## Information Architecture

Workspace zones:
1. Collection Browser (left)
2. Deck Worktable (center): Main, Runes, Battlefields, Sideboard trays
3. Inspector (right): validation, completeness, shopping list, save/import/export

Compare workflow:
- Dedicated panel/tab with side-by-side visual diff cards.

## Phase Roadmap

## Phase 1 - Foundations

Scope:
- Build reusable card tile component in `web/app.js` + `web/styles.css`
- Golden-hour design tokens and glass surfaces
- Hover preview system (large art + metadata)
- Skeleton/loading states for image-heavy lists

Deliverables:
- New layout shell in `web/index.html`
- Shared visual token system in `web/styles.css`
- Card rendering utilities in `web/app.js`

Exit criteria:
- Collection, meta, and library views all render image tiles.
- Fallback art appears when `imageUrl` is missing.

## Phase 2 - Core Deck-Building UX

Scope:
- Drag-and-drop or click-to-add from Collection to deck trays
- Inline quantity controls (`+1`, `+3`, `-1`)
- Card state overlays:
  - Missing copies
  - Invalid by rule/domain/type
  - Collection-complete
- Real-time validation panel updates

Deliverables:
- Interactive deck table behavior
- Instant deck legality + completeness feedback loop

Exit criteria:
- A full deck can be built end-to-end without manual JSON editing.
- Illegal changes are surfaced immediately with actionable messaging.

## Phase 3 - Polish and Responsiveness

Scope:
- Motion refinement (staggered reveals, smooth transitions)
- Mobile/tablet responsive layout with preserved glass aesthetic
- Better empty/error/loading states
- Performance tuning (lazy image loading, list virtualization thresholds)

Deliverables:
- Production-ready responsive behavior
- Stable frame-rate interactions on typical laptop hardware

Exit criteria:
- Major workflows are smooth on desktop and mobile widths.
- No jarring layout jumps during data refreshes.

## Phase 4 - Quality and Accessibility

Scope:
- Keyboard navigation across list/grid controls
- Focus states and ARIA improvements
- Contrast checks for warm glass palette
- Regression snapshots for critical UI states

Deliverables:
- Accessibility pass + interaction hardening

Exit criteria:
- Core workflows fully keyboard operable.
- Validation and missing states are legible without relying only on color.

## Data/API Needs

Required (already available or partially available):
- Card catalog with `imageUrl`, type, domains
- Deck validation endpoint
- Deck analysis endpoint
- Meta deck browse endpoint
- Library CRUD endpoints

Potential additions:
- Enriched backend card row payloads for consistent rendering metadata
- Optional server-side pagination/filtering for large card sets

## Risks and Mitigations

Risk: inconsistent card image URLs  
Mitigation: robust fallback tile + alt text + graceful skeleton states

Risk: visual polish hurts readability  
Mitigation: strict typographic hierarchy and contrast checks per phase

Risk: card-heavy views become sluggish  
Mitigation: lazy loading, capped initial render, optional virtualized lists

## Definition of Done (UI Track)

1. Card art is visible in all core workflows (collection, deck, meta, compare).
2. Deck editing feels tactile and immediate (no page reloads).
3. Validation/completeness states are clear at a glance.
4. Visual tone matches golden-hour glass-table intent on desktop and mobile.
5. Interaction and accessibility baselines are met.
