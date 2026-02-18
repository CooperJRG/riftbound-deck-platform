# Deck Worktable Interaction Plan

Date: 2026-02-17  
Status: Planned (ready for implementation)

## Objective

Rebuild the `Deck Worktable` into a card-first, interaction-first editor:
- card images for all deck slots
- `+/-` quantity controls for main/side/runes
- always-on legality validation
- status light in top-right: green = legal, red = illegal
- red status supports hover tooltip with issues, green has no hover behavior

## Rules Authority and Compliance

Use existing `rules_profiles/constructed.json` constraints and references as source of truth:
- main deck exact size 40
- runes exact size 12
- battlefields exact size 3 and unique
- champion required and must be present in main
- domain identity enforcement and tag matching

No rule logic duplicated in UI.  
UI shows constraints and runs live validation using API/domain output.

## Current Gaps (Implementation Reality)

1. Deck editor is text-area based; no card tiles or quantity controls.
2. Save/update APIs currently reject illegal decks (`POST/PUT /api/decks/library` returns `400`).
3. No API for filtered/eligible legends/champions/battlefields.
4. No persistent legality state surfaced in topbar status light.

## Target Worktable Layout

## Row 1: Deck Header + Identity + Runes

1. `Deck Name` (keep existing editable field)
2. `Legend` slot (single card tile)
   - click opens thumbnail picker modal with eligible legends
3. `Chosen Champion` slot (single card tile + qty in main)
   - click opens thumbnail picker modal with eligible champions for selected legend
4. `Rune Distribution` panel
   - six domain counters with colored chips
   - total always normalized/enforced to 12
   - increment one domain decrements others automatically

## Row 2: Battlefields

1. Exactly three battlefield slots in landscape row
2. Each slot uses card tile + picker modal
3. Picker constrained by battlefield eligibility and domain identity where applicable

## Row 3: Main Deck Contents

1. Card tile list/grid for main deck contents
2. Per-card controls: `-`, current qty, `+`
3. Add-card flow via searchable card picker (thumbnail list)
4. Optional grouped views (by type/cost/domain) deferred until later

## Interaction Model

## Legal Indicator

1. Indicator lives in top-right status area.
2. `green` when `validation.is_valid = true`.
3. `red` when invalid; hover/focus shows concise issue list.
4. Tooltip only active in red state.

## Validation Loop

1. Every deck edit triggers debounced validation call (`150-250ms`).
2. Last successful result stored in UI state:
   - `isValid`
   - `issues[]`
   - `summary`
3. UI never blocks editing.

## Save Behavior (Critical Change)

1. Save always allowed, including illegal decks.
2. Library row stores latest validation snapshot for quick status display.
3. Explicit warning copy shown near save action when invalid.

## Backend Plan

## Phase A - API Contract Changes

1. Add a tolerant save mode:
   - remove hard `400` validation gate from `POST/PUT /api/decks/library`
   - return stored deck plus `validation` payload (or compute on read)
2. Add deck status metadata in library payload:
   - `isValid`
   - `issueCount`
   - optional `updatedValidationAt`
3. Add card query filters for picker UX:
   - legends endpoint or filter (`cardType=Legend`)
   - champions endpoint/filter (`superType=Champion`, plus legend tag compatibility)
   - battlefields endpoint/filter (`cardType=Battlefield`)

## Phase B - Eligibility Services

1. Add pure helper functions in domain layer:
   - `eligible_legends(cards)`
   - `eligible_champions(cards, legend)`
   - `eligible_battlefields(cards, legend, selected)`
   - `rune_options_for_legend(cards, legend)`
2. Keep all eligibility logic centralized in domain helpers to avoid UI drift.

## Frontend Plan

## Phase C - State Refactor

1. Replace free-form text editing for core slots with structured deck state:
   - `legendTitle`
   - `chosenChampionTitle`
   - `battlefields[3]`
   - `runes{domain->qty}`
   - `main{title->qty}`
2. Keep text import/export compatibility by converting both directions.

## Phase D - Worktable Components

1. Build reusable components in vanilla JS:
   - `cardSlot` (single selected card with image)
   - `cardPickerModal` (thumbnail grid + search + select)
   - `quantityStepper` (`- qty +`)
   - `runeMeter` (domain chips + steppers + total badge)
2. Render structure:
   - header row (name + legend + champion + rune meter)
   - battlefield row
   - main deck row/grid

## Phase E - Live Validation + Status Light

1. Add debounced validator pipeline.
2. Wire top-right status LED:
   - green legal state
   - red illegal state + tooltip issue list
3. Ensure save button does not disable on invalid.

## Data and Migration Notes

1. Existing saved deck schema remains valid (`DeckPayload`).
2. New optional status metadata can be additive in API response.
3. No destructive DB migration required for first pass if validation computed on read.

## Testing Plan

## Backend

1. Save invalid deck returns `200/201` and persists deck.
2. Validation payload still reports correct issues for invalid deck.
3. Eligibility helper tests:
   - champion filtered by legend tag
   - battlefields count/uniqueness constraints respected
   - rune identity constraints reflected

## Frontend

1. Selecting legend updates eligible champion list.
2. Champion quantity adjustments reflect in main deck total.
3. Rune steppers always sum to 12.
4. Battlefield row enforces exactly 3 selected slots in UX.
5. Red status shows hover tooltip with issues; green status has no tooltip.

## Risks and Mitigations

1. Risk: frequent validation calls cause jitter.
   - Mitigation: debounce + only apply latest response.
2. Risk: eligibility mismatch between picker and final validator.
   - Mitigation: domain helper functions shared by API and tests.
3. Risk: invalid save behavior confuses users.
   - Mitigation: explicit warning near save and persistent status light.

## Implementation Sequence

1. Backend contract and eligibility helpers.
2. Frontend state refactor and component scaffolding.
3. Deck worktable layout + pickers + steppers.
4. Live validation + red/green indicator + tooltip.
5. Save-invalid behavior confirmation and end-to-end polish.
