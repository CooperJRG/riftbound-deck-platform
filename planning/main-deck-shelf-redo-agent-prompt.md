# Prompt For Future Agent: Main Deck Shelf Rebuild

You are taking over a partially working Main Deck shelf UI that must be rebuilt from scratch.

## Read First
- `planning/main-deck-shelf-redo-handoff.md`
- `web/index.html` (`#main-deck-list`)
- `web/app.js` (`renderMainDeckList`, `bindMainDeckShelfPhysics`, `adjustMainCard`)
- `web/styles.css` Main Deck shelf selectors

## Task
Replace the current Main Deck shelf implementation with a **row-first shelf system**.

The current issue is that shelf rendering behaves like a single/fragile background effect and not a real shelf per row. Fix this by using explicit row structure and row-level plank/lip rendering.

## Must-Have Outcomes
1. One visible shelf plank per card row.
2. If 1/2/3+ rows exist, shelf visuals scale exactly with that row count.
3. Card spacing is clear and readable.
4. Quantity controls remain under each card on the protruding shared row lip.
5. Card hover physics remains subtle and tactile (card art moves, not controls).
6. Existing deck logic remains intact (especially legend exclusion from main deck).

## Hard Constraints
- No external libraries.
- Keep existing assets; use `--asset-walnut` and stain/tint in CSS.
- Do not put controls on the card surface.
- Do not change APIs/backend for this task unless strictly necessary.

## Implementation Guidance
- Prefer building rows explicitly in `renderMainDeckList` (or a helper) instead of relying on a repeated background trick.
- Use dedicated row containers for:
  - card lane
  - shelf lip lane
- Bind existing add/remove handlers to the new controls.
- Update `bindMainDeckShelfPhysics` selectors if DOM changes.
- Remove now-obsolete Main Deck CSS blocks to reduce conflict.

## Deliverables
1. Updated Main Deck rendering code in `web/app.js`.
2. Updated Main Deck row/plank/lip CSS in `web/styles.css`.
3. No changes to asset files.
4. Verification output summary after running:
   - `node --check web/app.js`
   - `$env:PYTHONPATH='.'; pytest -q`

## Done Definition
- Visual: shelves are clearly per-row, 3D, and stable at different row counts.
- UX: steppers are correctly placed on shelf lip and stay usable.
- Behavior: no regressions in deck editing, validation updates, or legend filtering.

