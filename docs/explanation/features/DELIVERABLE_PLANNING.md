# Deliverable Planning

## Overview

Deliverable planning introduces a first-class output planning layer for orchestration. It separates capability and evidence planning from the decision about what SimpleChat should produce for the user, such as a complete inline answer, a concise summary, or a generated supporting artifact.

Implemented in version: **0.250.126**

## Purpose

The Phase 11A foundation records a server-authoritative `deliverable_intent` before execution and a `materialized_deliverable_plan` after evidence reaches a terminal state. This lets central synthesis distinguish the answer shape from evidence collection, preserve required explicit outputs, and avoid claiming generated artifacts before publication succeeds.

## Dependencies

*   `application/single_app/functions_deliverable_planner.py` for intent, adapter, directive, and materialized-plan contracts.
*   `application/single_app/functions_evidence_ledger.py` for persisted deliverable plan fields and evidence binding.
*   `application/single_app/functions_central_synthesis.py` for finalizer access to deliverable metadata.
*   `application/single_app/config.py` version `0.250.126` for this implementation slice.

## Technical Specifications

The initial implementation adds deterministic contracts for:

*   Inline response only.
*   Summary plus Markdown analysis artifact adapter metadata.
*   Summary plus CSV structured artifact adapter metadata.
*   Explicit generated-file requests that must fail visibly when unsupported instead of being silently removed.
*   Partial evidence override revisions that bind to missing or failed evidence ids.

The current adapter registry is intentionally small and server-owned. Existing Analyze and export heuristics can be migrated into this contract as hints and fallbacks in later Phase 11A work without making route-local marker checks the authoritative output decision.

## Usage

Backend orchestration creates or supplies a `deliverable_intent` when initializing an evidence ledger. After evidence collection reaches `ready`, `partial`, or `failed`, the ledger can materialize a plan with exact evidence snapshot ids, output roles, approval state, publication state, and partial-output disclosure metadata.

Central synthesis receives both plan stages in the finalizer request and must use them to separate complete inline answers, summaries, planned artifacts, and failed or unpublished artifacts.

## Testing And Validation

Functional coverage is in `functional_tests/test_deliverable_planner_contract.py`.

The test validates:

*   Inline-only requests do not create artifact deliverables.
*   Explicit CSV requests create required artifact plans and remain visible to central synthesis.
*   `ask_first` directives require approval on generated artifacts.
*   Partial evidence acceptance creates a distinct materialized-plan revision.
*   Unsupported explicit file requests fail visibly instead of being removed.

Known limitation: this first slice adds the persisted contract and synthesis handoff. Analyze/generated-export route migration and non-Analyze output adapter consumption remain follow-up implementation work in Phase 11A.