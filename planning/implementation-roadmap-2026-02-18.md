# Riftbound v2 Implementation Roadmap

Date: 2026-02-18  
Source: Consolidated from the prior `Client Agent <-> Dev Team Agent` review dialog

## Goal

Move Riftbound Deck Platform v2 from a strong local builder into a complete, release-ready product by executing the agreed priorities in order:

1. Sideboard + format readiness
2. Deck search inspectability + meta freshness
3. Data lifecycle UX (backup/recovery confidence)
4. Reliability hardening (tests + ops)
5. Multi-user/cloud foundation

## Context Snapshot

Recent polish already completed:
- Deck Search performance + refresh behavior upgraded.
- Scrollbars themed to match UI direction.
- Built/Saved library interaction simplified (double-click open, drag-drop move, reduced controls).

Remaining roadmap below focuses on high-impact completeness gaps.

## Decision Log (From Conversation)

- `Priority 1`: Add sideboard as a first-class UI workflow (already supported by domain/API rules).
- `Priority 2`: Expose format selection and profile switching.
- `Priority 3`: Add deck inspection before committing in Deck Search.
- `Priority 4`: Add meta ingest/refresh pathway and freshness visibility.
- `Priority 5`: Add collection export + safer recovery flows.
- `Parallel hardening`: front-end/e2e test layer + stronger production diagnostics.

## Phase Plan

## Phase 1 - Product Completeness Core (2-3 sprints)

### Epic 1.1 - Sideboard Worktable Integration
Outcome:
- Users can add/edit sideboard cards with the same card-first UX as main deck.

Scope:
- New sideboard section in worktable.
- Sideboard card picker + steppers.
- Sideboard totals, copy-limit messaging, and rule visibility in validation panel.
- Save/load/import/export parity with sideboard state.

Acceptance Criteria:
- Sideboard persists correctly through save/load/import/export.
- Validation surfaces sideboard violations inline.
- Combined main+sideboard copy limit errors are understandable in UI.

### Epic 1.2 - Format Selection
Outcome:
- Users can choose supported format profiles instead of hard-coded constructed only.

Scope:
- Format selector in UI and deck payload.
- Backend profile resolution by format.
- Eligibility/validation/analyze honor selected profile.

Acceptance Criteria:
- Format switch updates limits/eligibility without app reload.
- Deck library rows retain format identity.
- Tests cover at least one non-constructed profile path.

## Phase 2 - Search and Discovery Quality (2 sprints)

### Epic 2.1 - Meta Deck Detail Inspection
Outcome:
- Users can inspect a full meta deck before using/saving.

Scope:
- Deck Search card/modal detail view.
- Sectioned deck composition display (legend/champion/main/runes/battlefields).
- "Use" and "Save" actions from detail context.

Acceptance Criteria:
- Every search result has a detail view with complete deck contents.
- No extra network delay beyond existing result fetch path.

### Epic 2.2 - Meta Freshness Workflow
Outcome:
- Users/admins can refresh meta source data and see freshness status.

Scope:
- Ingest trigger (manual first; scheduled optional next).
- Last-refresh metadata and row count in UI.
- Failure reporting and fallback to last good index.

Acceptance Criteria:
- Refresh updates searchable deck set without restart.
- Freshness timestamp visible and accurate.
- Failed refresh does not break existing search.

## Phase 3 - Data Lifecycle and Trust (1-2 sprints)

### Epic 3.1 - Collection Export/Import Parity
Outcome:
- Users can back up and restore collection state safely.

Scope:
- Export collection CSV/JSON.
- Import modes: merge vs replace.
- Clear collection with confirmation + undo window (or backup prompt).

Acceptance Criteria:
- Exported file re-imports to identical totals.
- Replace mode clearly communicates destructive effect.

### Epic 3.2 - Safer Destructive Actions
Outcome:
- Reduced accidental loss and better recovery confidence.

Scope:
- Consistent confirmation UX for deletes/resets.
- Optional soft-delete or short undo for deck deletion.

Acceptance Criteria:
- Destructive actions are reversible or explicitly acknowledged.

## Phase 4 - Engineering Hardening (parallel, starts immediately)

### Epic 4.1 - Frontend Regression Protection
Outcome:
- High-confidence UI changes with lower manual QA load.

Scope:
- Playwright smoke + critical interaction suites:
  - build/edit/save/load,
  - sideboard flows,
  - deck search inspect/use/save,
  - library drag/drop,
  - collection import/export.

Acceptance Criteria:
- CI gate includes frontend integration tests.
- Critical user paths are covered end-to-end.

### Epic 4.2 - Production Diagnostics and Operational Readiness
Outcome:
- Faster incident diagnosis and safer deployments.

Scope:
- Expanded health endpoint (dependency checks, build/version, data index status).
- Structured request/error logging.
- Lightweight schema migration/version policy for SQLite.

Acceptance Criteria:
- Operators can identify catalog/meta/storage health from API.
- Breaking schema drift is prevented by version checks.

## Phase 5 - Multi-User / Cloud Foundation (future track)

### Epic 5.1 - Identity and User Scoping
Outcome:
- Account-based ownership of decks/collections.

Scope:
- Auth baseline.
- User-scoped storage tables and API filtering.

### Epic 5.2 - Sync and Collaboration
Outcome:
- Cross-device continuity and optional team workflows.

Scope:
- Cloud sync for deck library and collection.
- Optional shared collections/workspaces.

## Delivery Sequence

1. Phase 1 (sideboard + format selector)
2. Phase 2 (meta detail + freshness)
3. Phase 3 (data lifecycle safety)
4. Phase 4 runs in parallel from Sprint 1 onward
5. Phase 5 starts only after Phase 1-4 stabilization

## Ownership Model

- Product/UX:
  - Sideboard interaction design
  - Deck detail inspection UX
  - destructive action safety patterns

- Frontend:
  - Worktable + library + search UX implementation
  - format selector and state handling
  - accessibility + keyboard pathways

- Backend:
  - format profile routing
  - meta ingest/freshness services
  - export endpoints + health diagnostics

- QA/Automation:
  - Playwright e2e suite
  - regression baseline for high-risk flows

## Milestone Exit Criteria

`M1` (end Phase 1):
- Sideboard fully usable in UI
- format is selectable
- no regression in validation/analyze/save/load

`M2` (end Phase 2):
- Search results are inspectable and freshness-managed
- users can trust "what they see is current enough"

`M3` (end Phase 3 + 4):
- users can backup/recover data
- CI has backend + frontend confidence gates
- minimum production diagnostics available

`M4` (Phase 5 kickoff readiness):
- stable release cadence
- clear multi-user requirements and data model approved
