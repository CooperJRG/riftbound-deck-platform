# Main Deck Shelf Redo Handoff

## Objective
Rebuild the **Main Deck** visual area from scratch with a row-first skeuomorphic shelf model.

Current behavior is close, but the shelf illusion is inconsistent. The replacement should prioritize:
- one clear shelf plank per visible row
- strong 3D depth cues
- readable spacing between cards
- quantity toggles resting on the shared shelf lip (not floating per card)

## Why This Needs A Full Redo
The current implementation mixes:
- row-level shelf rendering
- per-card shelf-like chrome
- several generations of sizing overrides

This created "context rot" and makes simple changes unpredictable.

## Required End State
1. Shelf must be row-based.
2. Every row of cards must visibly map to one shelf plank.
3. If there are N rows, there must be N visible shelf planks.
4. Cards must have breathing room (visible horizontal and vertical spacing).
5. Card physics can remain, but only card art should move, not controls.
6. Quantity steppers must sit on top of the protruding shelf lip shared by the row.
7. Main Deck behavior and deck logic must remain intact.

## Non-Negotiable Constraints
- Keep existing assets. Use `--asset-walnut` for shelf planks and stain/tint in CSS.
- No external libraries.
- Do not move quantity controls onto the card face.
- Do not break existing add/remove quantity behavior.
- Do not break legality behavior (including "legend never in main").

## Scope
### In scope
- `web/styles.css` Main Deck shelf layout and visuals
- `web/app.js` Main Deck render structure for row-based shelves
- Main Deck-only card physics alignment after DOM/CSS changes

### Out of scope
- Collection panel visuals
- Library panel visuals
- Card data model
- API/backend logic

## Where Future Agent Should Look
### Markup entry point
- `web/index.html`
- Search for: `id="main-deck-list"`

### Main Deck rendering + interactions
- `web/app.js`
- Search for:
  - `renderMainDeckList`
  - `tileHtml`
  - `bindMainDeckShelfPhysics`
  - `adjustMainCard`
  - `sanitizeMainDeckLegendCards`

### Main Deck shelf styling (current brittle area)
- `web/styles.css`
- Search for:
  - `.main-deck-shelf`
  - `.main-deck-shelf::before`
  - `.main-deck-shelf::after`
  - `.card-tile.shelf-card`
  - `.main-shelf-stepper`
  - media query overrides touching `--main-deck-card-height`, `--tile-gap`, `--shelf-row`

## Recommended Rebuild Strategy
1. Replace Main Deck DOM rendering with explicit rows.
2. Render a dedicated row wrapper per shelf row.
3. Render one shelf plank/lip layer per row wrapper.
4. Place card tiles above plank.
5. Place stepper controls in a row-lip lane aligned under each card.
6. Keep card physics attached only to card art nodes.
7. Remove legacy Main Deck-only CSS that assumes global repeating backgrounds.

## Suggested DOM Shape (Main Deck area only)
Use this shape in JS rendering (example structure only):

```html
<div class="main-shelf-stack">
  <section class="main-shelf-row">
    <div class="main-shelf-row-cards">
      <article class="card-tile shelf-card">...</article>
      <article class="card-tile shelf-card">...</article>
    </div>
    <div class="main-shelf-row-lip">
      <div class="main-shelf-stepper-slot">[ - qty + ]</div>
      <div class="main-shelf-stepper-slot">[ - qty + ]</div>
    </div>
  </section>
</div>
```

Notes:
- This removes dependence on difficult background-repeat row math.
- Row count becomes explicit and always matches visual planks.
- Stepper placement on lip becomes deterministic.

## Acceptance Criteria
- With enough cards for 3 rows, user sees 3 distinct shelf planks.
- Cards have consistent gaps and no touching/crowding.
- Shelf lip appears protruding and 3D.
- Steppers rest on the lip, under their card, and remain clickable.
- Pointer hover: lift/tilt card art only; stepper remains stable.
- Expand mode still works for Main Deck.
- No regression in deck edit behavior.

## Regression Checklist
- Add card from Library to Main Deck.
- Drag card from Library to Main Deck.
- Increment/decrement quantity on all visible rows.
- Remove card down to zero and confirm row reflow still renders shelves correctly.
- Validate deck still updates legality indicator.
- Confirm legend card never appears in Main Deck list.
- Check desktop and narrow-width layout.

## Verification Commands
Run after changes:

```powershell
node --check web/app.js
$env:PYTHONPATH='.'; pytest -q
```

