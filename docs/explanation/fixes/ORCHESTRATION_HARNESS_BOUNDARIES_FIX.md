# Orchestration Harness Boundaries Fix (v0.261.445)

Fixed in version: **0.261.445** (`application/single_app/config.py`).

## Issue Description

SimpleChat's governed Gather / Reason / Render flow had several boundary defects
between model planning, generation, recovery metadata, and execution fallbacks:

- the ordinary model invocation wrapper retained text from known incomplete
  generations, including provider `finish_reason="length"` responses;
- ordinary planning did not consistently show its effective limits and could not
  correct malformed protocol responses or a valid over-budget draft;
- evaluation fixtures had stale AST dependencies and success fixtures, obscuring
  the real planner/compiler behavior;
- failed runtime hints could be lost during result normalization, and zero did
  not disable summary hint collection;
- missing timeout settings used 120/600-second fallbacks even though shipped
  defaults were 180/900 seconds.

## Root Cause Analysis

The planner and executor already owned bounded validation, retry and recovery
contracts, but several policy projections were inconsistent. Provider
completion metadata was checked for refusals and empty text, not for other
non-final finish reasons. The plan-limits section was only attached to workflow
hand-off requests, while only selected validation codes entered the shared
correction allowance. Runtime hints were reconstructed in the failure path
without the original hint, and the positive-only setting helper treated zero as
missing. Timeout defaults had duplicated literals in separate owners.

## Technical Details

### Files Modified

- `application/single_app/functions_orchestration_execution.py`: rejects known
  non-final generations after usage accounting and source revalidation, while
  retaining ordinary missing/`None` and `stop` compatibility.
- `application/single_app/functions_orchestration_planner.py` and
  `functions_orchestration_schema.py`: share the effective step limit, project
  limits for every planner request, and route oversized and malformed
  model-owned drafts through the existing two-correction allowance.
- `application/single_app/functions_orchestration_adapters.py`,
  `functions_orchestration_executor.py`, and the associated admin presentations:
  retain safe per-step hints, honor a zero summary cap, and describe hints as
  inert metadata rather than automatic replanning.
- `application/single_app/functions_orchestration_timing.py`,
  `functions_settings.py`, and `functions_orchestration_workflow_runs.py`:
  centralize 180-second step and 900-second run fallbacks without changing
  explicit settings or persisted deadlines.
- `functional_tests/` and
  `ui_tests/test_admin_orchestration_planner_model.py`: repair the offline AST
  and tabular fixtures and add boundary regressions for completion markers,
  planner correction, hints, timeouts, and admin copy.
- `functional_tests/cosmos_response_boundaries.json`: renew module-only owner
  fingerprints after reviewing the unchanged Cosmos owner and fault-injection
  bodies.

### Behavior Before and After

Before, a syntactically valid answer or assessment could survive a length-
terminated provider response, an oversized draft could fail before its
correction allowance, and runtime hints could disappear while zero still
collected summaries. Standalone timing paths also used shorter limits than the
admin defaults.

After, known incomplete generations cannot become retained prepared content,
certify completeness, replace a saved candidate, or reach Render. Ordinary
compatible marker handling remains unchanged. Eligible plan errors still use
only the initial proposal plus two shared corrections. Hints remain bounded
diagnostic metadata and cause no planner, tool, or revision call. New execution
uses 180/900-second fallbacks, while an existing run keeps its persisted
deadline.

## Validation

- The approved focused owner command passed **1,131 tests** with network and
  provider I/O isolated.
- The focused completion/planner/hint/timeout discriminator matrix passed
  **67 tests**.
- The real completeness checkpoint regression passed the truncated-correction
  case without replacing the retained candidate.
- The refreshed Cosmos inventory retained **0 review gaps**. Its runtime command
  passed 1,564 tests; the one stale 120-second workflow-wait expectation was
  corrected to the shipped 180-second default, and that exact owner test then
  passed.
- Documentation coverage passed **7/7** checks and site quality passed **6/6**.
- The local Admin Settings Playwright regression passed **1 test**.
- The offline research evaluator completed with **0 network calls** and its
  capture completed with **0 requests**.
- Changed Python owners compiled and `git diff --check` passed.

No production source or user-data outcome is inferred from these offline
contract tests.

## Impact and Limitations

This repair hardens call, draft and metadata boundaries without changing
authorization, approval, exact-result retention, publication, effect fencing,
dependency-plan contract version 2, or saved-run recovery. It does not add
automatic replanning, evaluator configuration, a new UI state machine, token
increases, provider retries, or TRE-05's strict opt-in completion mode.

The change establishes deterministic boundary behavior, not semantic factual
quality. Production incidence and the original broad live symptoms remain
unmeasured without an authorized trace or deployed retest.
