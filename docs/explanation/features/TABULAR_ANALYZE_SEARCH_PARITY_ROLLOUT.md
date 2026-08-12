# Tabular Analyze Search Parity Rollout Metadata

Implemented in version: **0.250.164**

Related version update:
- `application/single_app/config.py` reports version `0.250.164`.

## Overview

Phase 8 of tabular Analyze/Search parity adds safe rollout, telemetry, and generated-output metadata so Search and Analyze can expose the same background tabular run lifecycle without duplicating the existing chat artifact card.

Dependencies:
- `application/single_app/functions_tabular_orchestration.py`
- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_settings.py`
- `application/single_app/static/js/chat/chat-messages.js`

## Technical Specifications

Architecture overview:
- The shared tabular planner now returns a deterministic `rollout_assignment` with a contract version, mode, planner mode, assigned flag, cohort bucket, rollout percentage, gate booleans, and legacy fallback mode.
- New durable generated-output runs created through the shared planner persist sanitized planner metadata in `tabular_planner_metadata`.
- Public generated-output run status includes `metadata_contract_version='phase8.v1'`, planner contract, execution contract, execution group id, source coverage summary, deferred composition reference, and rollout assignment.
- Source coverage metadata is summarized by counts and file format classes only. It does not expose source locators, blob paths, prompt text, raw source coverage arrays, or backend settings.
- Existing Search and Analyze shared-preflight telemetry emits safe rollout dimensions on `[TABULAR_SHARED_PREFLIGHT]` events.

Configuration options:
- `tabular_request_planner_mode`: `off`, `shadow`, or `active`.
- `enable_tabular_search_shared_preflight`: enables shared planner use in Search when planner mode allows it.
- `enable_tabular_analyze_durable_preflight`: enables pure tabular Analyze durable preflight when planner mode allows it.
- `enable_tabular_mixed_deferred_composition`: enables pending mixed-source composition handoff.
- `enable_tabular_multifile_durable_preflight`: enables explicit multi-table execution-unit planning.
- `tabular_analyze_parity_rollout_percent`: deterministic rollout percentage for new parity assignments.
- `tabular_legacy_post_tool_fallback_mode`: `enabled`, `observe`, or `disabled`.

All Phase 8 rollout controls are backend-only and are removed by `sanitize_settings_for_user()` before non-admin frontend settings are returned.

## Usage Instructions

How to enable/configure:
1. Keep the planner mode `off` for the default legacy behavior.
2. Use `shadow` mode to compare planner decisions without queueing shared-planner durable work.
3. Enable the relevant Search or Analyze gate before switching that mode to active traffic.
4. Adjust `tabular_analyze_parity_rollout_percent` for canary cohorts.
5. Keep `tabular_legacy_post_tool_fallback_mode='enabled'` until operator telemetry shows no required legacy recovery traffic.

Operator telemetry:
- Query `[TABULAR_SHARED_PREFLIGHT]` traces by `caller`, `planner_mode`, `execution_contract`, `execution_state`, `reason_code`, `rollout_assigned`, `rollout_percent`, and `legacy_post_tool_fallback_mode`.
- Alert on any foreground-after-durable-acceptance invariant violation, duplicate publication, cross-user ownership failure, elevated finalization failure rate, or stale deferred composition backlog.
- Treat prompts, file names, blob paths, source locators, raw exceptions, generated answers, and credentials as prohibited telemetry dimensions.

## Testing And Validation

Functional coverage:
- `functional_tests/test_tabular_phase8_ui_telemetry_rollout.py` verifies stable and redacted rollout assignment, backend settings sanitization, public generated-output metadata, and safe telemetry dimensions.
- `functional_tests/test_tabular_shared_request_planner.py` verifies shared planner behavior and backend rollout controls.
- `functional_tests/test_tabular_search_shared_preflight_adapter.py` and `functional_tests/test_tabular_analyze_shared_preflight_adapter.py` verify Search and Analyze adapter compatibility.
- `functional_tests/test_tabular_phase7_lifecycle_coverage.py` verifies lifecycle evidence states remain truthful.

Performance and limitations:
- Phase 8 does not introduce a second generated-output runner, source resolver, authorization path, or UI card.
- Existing frontend generated-output cards render the normalized metadata; no separate Analyze card or polling implementation is introduced.
- Existing runs without Phase 8 planner metadata remain readable and receive source coverage derived from their durable run state.
