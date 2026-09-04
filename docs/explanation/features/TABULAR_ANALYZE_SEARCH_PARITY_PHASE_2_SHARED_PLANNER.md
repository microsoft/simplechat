# Tabular Analyze/Search Parity Phase 2 Shared Planner

Implemented in version: **0.250.158**

## Overview

Phase 2 introduces a route-neutral tabular request planner for the Analyze/Search parity roadmap. The planner classifies explicit full-source tabular intent before row retrieval and returns a normalized execution contract that Search and Analyze adapters can compare without changing production behavior yet.

The new shared facade is disabled by default. Search and Analyze continue to use their legacy paths until later phases enable adapter-specific rollout gates.

## Dependencies

- Existing durable tabular generated-output runner in `application/single_app/functions_tabular_generated_exports.py`
- Existing structured artifact intent helpers in `application/single_app/functions_generated_file_exports.py`
- Existing assistant-table CSV intent helper in `application/single_app/functions_assistant_table_exports.py`
- Current application version from `application/single_app/config.py`: **0.250.158**

## Technical Specifications

The shared planner lives in `application/single_app/functions_tabular_orchestration.py` and exposes:

- `plan_tabular_request(...)` for pure request classification.
- `orchestrate_tabular_request(...)` for `off`, `shadow`, and callback-backed `active` mode orchestration.
- `execute_tabular_plan(...)` for the active side-effect boundary used by future route adapters.

The planner maps deterministic tabular intent to these contracts:

- `foreground_aggregate` for bounded aggregate or inspection requests.
- `structured_export` for explicit generated CSV, JSON, XML, or workbook-style output.
- `hierarchical_analysis` for exhaustive analysis-only requests when hierarchical analysis is enabled.
- `combined` for exhaustive analysis plus structured artifact requests.

The facade records a versioned planner contract, source coverage, safe reason code, request fingerprint, output format, generated-output metadata placeholder, citations, token usage placeholder, and deferred-composition placeholder. It does not return Flask responses, stream frames, rendered prose, or frontend structures.

## Rollout Controls

The following backend-only settings were added with safe defaults:

- `tabular_request_planner_mode`: defaults to `off`.
- `enable_tabular_search_shared_preflight`: defaults to `False`.
- `enable_tabular_analyze_durable_preflight`: defaults to `False`.

These controls are included in the existing tabular backend settings denylist used by `sanitize_settings_for_user(...)`, so they are not sent to non-admin frontend settings payloads.

## Usage Instructions

Operators do not need to enable anything for Phase 2. The shared planner can be exercised in tests and future adapter work through shadow mode. Active mode requires an explicit durable execution callback and idempotency cache, so it cannot create durable work unless a server-side caller deliberately supplies that boundary.

## Testing and Validation

Functional coverage is in `functional_tests/test_tabular_shared_request_planner.py`.

The test validates:

- Equivalent Search and Analyze caller metadata produce the same contract.
- Explicit artifact, exhaustive analysis-only, combined, and bounded aggregate requests classify as expected.
- Missing and multi-context durable source cases return safe non-success reason codes.
- Shadow mode has zero durable side effects.
- Active mode queues exactly once through a callback and reuses metadata through the idempotency cache.
- Backend-only rollout settings are covered by the sanitization denylist.

Known limitation: Phase 2 does not switch production Search or Analyze ownership to the shared planner. That adapter work begins in later phases.
