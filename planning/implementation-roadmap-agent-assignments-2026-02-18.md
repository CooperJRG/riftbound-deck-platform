# Riftbound v2 Agent Assignment Plan

Date: 2026-02-18  
Inspired by: `planning/implementation-roadmap-2026-02-18.md`

## Agent Roles

- `PM Agent`: scope, sequencing, acceptance criteria
- `Frontend Agent`: UI and interaction implementation
- `Backend Agent`: API, domain, persistence work
- `QA Agent`: test coverage and release verification

## Phase 1 - Core Product Completeness

### Tasks

| Task | Owner Agent |
|---|---|
| Finalize sideboard UX requirements and done criteria | PM Agent |
| Build sideboard worktable UI (picker, quantity controls, totals) | Frontend Agent |
| Ensure sideboard validation/analysis API behavior is stable | Backend Agent |
| Add/expand tests for sideboard save/load/validate flows | QA Agent |

## Phase 2 - Search and Discovery

### Tasks

| Task | Owner Agent |
|---|---|
| Define deck-detail inspection UX for search results | PM Agent |
| Implement meta deck detail modal and actions | Frontend Agent |
| Add meta refresh endpoint/service and freshness metadata | Backend Agent |
| Add regression tests for search, detail view, and refresh | QA Agent |

## Phase 3 - Data Lifecycle and Trust

### Tasks

| Task | Owner Agent |
|---|---|
| Define backup/recovery UX rules (export/import/reset) | PM Agent |
| Implement collection export/import/reset UI pathways | Frontend Agent |
| Add collection export endpoint and safe reset handling | Backend Agent |
| Validate destructive-flow safeguards and data integrity tests | QA Agent |

## Phase 4 - Reliability and Release Readiness

### Tasks

| Task | Owner Agent |
|---|---|
| Lock release checklist and quality gates | PM Agent |
| Fix final UX defects and accessibility gaps | Frontend Agent |
| Add operational diagnostics (health/detail logs/schema version checks) | Backend Agent |
| Run e2e suite and sign-off report | QA Agent |

