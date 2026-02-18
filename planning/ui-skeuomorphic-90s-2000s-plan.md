# UI Plan: Skeuomorphic 90s/2000s

Date: 2026-02-17  
Status: Active (pre-implementation refresh)

## Goal

Deliver a deck-builder interface with a tactile, old-software feel inspired by late-90s and early-2000s desktop applications:
- Physical materials (wood, leather, brushed metal, paper, glass)
- Deep bevels and subtle gloss
- Layered "desk object" composition instead of flat cards on flat panels

## Product Intent

Primary UX outcomes:
1. Deck building should feel hands-on and object-driven.
2. Card art remains central, with richer tactile framing.
3. Validation/completeness remains clear while fitting a classic skeuomorphic look.

## Visual Direction

Atmosphere:
- Warm desk environment with controlled studio lighting
- Classic software chrome, beveled controls, inset wells, raised buttons
- Rich textures, restrained color palette, readable contrast

Style rules:
- Use textures as functional surfaces, not decorative noise.
- Keep labels crisp and modern enough for readability.
- Avoid cartoon/exaggerated skeuo; target "premium desktop utility" style.

## Information Architecture

Workspace zones remain:
1. Collection Browser (left)
2. Deck Worktable (center)
3. Inspector (right)

But each zone becomes a physical "module":
- Collection: inset tray with card bins
- Worktable: raised tabletop with grouped deck wells
- Inspector: leather or paper noteboard with pinned summaries

## Phase Roadmap

## Phase 1 - Skeuomorphic Foundations

Scope:
- Replace golden-hour glass system with skeuomorphic material system
- Build reusable card tile frame with bevel/shadow/gloss layers
- Add hover preview as a "lifted card" object
- Add loading skeletons that match material styling
- Integrate generated textures/background assets from prompt pack

Deliverables:
- Updated layout shell in `web/index.html`
- Material token system in `web/styles.css`
- Reusable card render + preview utility in `web/app.js`
- Asset hooks and fallback paths for missing textures

Exit criteria:
- Collection, Meta, and Library render card-image tiles within skeuomorphic frames.
- UI clearly reads as 90s/2000s tactile software style.

## Phase 2 - Core Deck-Building UX

Scope:
- Click/drag interactions to add cards to deck trays
- Quantity controls with tactile button states
- Visual state overlays for missing/invalid/complete
- Real-time legality/completeness in inspector module

Deliverables:
- Interactive deck manipulation from collection tiles
- Visual rule feedback tied to deck wells

Exit criteria:
- End-to-end deck build/edit can be done visually.
- Invalid states are obvious without breaking the skeuo tone.

## Phase 3 - Material Polish and Responsive Pass

Scope:
- Fine-tune material balance (contrast, texture scale, shadow depth)
- Mobile/tablet adaptation while preserving tactile hierarchy
- Performance pass (image loading, caching, asset weight)

Deliverables:
- Responsive skeuomorphic layout
- Stable performance with card-heavy views

Exit criteria:
- Style intent remains intact on desktop and mobile.
- No heavy jank from texture/image loading.

## Phase 4 - Accessibility and Hardening

Scope:
- Keyboard navigation and focus visibility for textured controls
- Contrast validation against textured backgrounds
- Visual regression baselines for key UI states

Deliverables:
- Accessible interactive controls and readable text layers

Exit criteria:
- Core workflows keyboard-accessible.
- Material styling does not reduce usability.

## Asset Dependency

Required image assets are documented in:
- `planning/imagegen-asset-prompts-skeuomorphic.md`

Implementation should not proceed past foundational styling until required assets are generated and placed.

## Definition of Done (UI Track)

1. Card imagery is present across collection/deck/meta/compare contexts.
2. Surfaces, controls, and panels consistently reflect skeuomorphic material design.
3. Deck editing and feedback loops remain fast and clear.
4. Desktop and mobile preserve usability and atmosphere.
5. Accessibility baseline is maintained.
