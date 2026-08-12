# Tabular Analyze Search Parity Phase 9 Legacy Retirement

Implemented in version: **0.250.165**

Related version update:
- `application/single_app/config.py` reports version `0.250.165`.

## Overview

Phase 9 adds evidence-backed retirement controls for the legacy post-tool generated-output fallback used by tabular Search and Analyze. The default remains compatible: `tabular_legacy_post_tool_fallback_mode='enabled'` keeps the existing fallback available for genuinely tool-derived outputs that are not covered by direct source preflight.

Dependencies:
- `application/single_app/functions_tabular_orchestration.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_phase9_legacy_retirement.py`

## Technical Specifications

Architecture overview:
- The shared tabular planner now records `legacy_post_tool_fallback_decision` using contract `tabular-legacy-fallback-retirement-v1`.
- Shared durable acceptance records `action='suppress'` and `reason_code='shared_durable_metadata_present'`, proving the legacy fallback must not create a duplicate run after generated-output metadata already exists.
- `observe` mode suppresses post-tool fallback side effects while emitting safe telemetry that the fallback would have been considered.
- `disabled` mode suppresses the same legacy post-tool fallback path without changing direct shared-preflight execution, old-run readers, status routes, cancel/resume behavior, or artifact rendering.

Telemetry fields:
- `legacy_post_tool_fallback_contract_version`
- `legacy_post_tool_fallback_mode`
- `legacy_post_tool_fallback_action`
- `legacy_post_tool_fallback_reason`
- `legacy_post_tool_fallback_should_invoke`

The decision intentionally excludes prompts, filenames, blob paths, raw source locators, row content, credentials, and raw provider errors.

Configuration options:
- `tabular_legacy_post_tool_fallback_mode='enabled'`: invoke the legacy post-tool fallback when no shared durable metadata already exists.
- `tabular_legacy_post_tool_fallback_mode='observe'`: suppress post-tool fallback side effects and emit observation telemetry.
- `tabular_legacy_post_tool_fallback_mode='disabled'`: suppress post-tool fallback side effects for eligible new requests.

## Usage Instructions

Operator workflow:
1. Keep `tabular_legacy_post_tool_fallback_mode='enabled'` until shared Search and Analyze preflight traffic has no planner mismatches or duplicate run incidents.
2. Switch to `observe` for a canary cohort after direct-source shared preflight has proven coverage for eligible generated-output requests.
3. Query `[TABULAR_SHARED_PREFLIGHT]`, `[TABULAR_PARITY_CONTRACT]`, and `[TABULAR_GENERATED_OUTPUT]` events for fallback action, reason, and invocation counts.
4. Move to `disabled` only when observe-mode telemetry shows no required tool-derived fallback cases for the supported classification matrix.
5. Return to `enabled` if canary telemetry shows a required replayable tool-derived output is not covered by shared direct-source preflight.

Rollback behavior:
- Changing the setting affects new post-tool fallback decisions only.
- Existing generated-output runs keep their persisted executor and planner metadata.
- Direct shared-preflight runs, run status, cancel, resume, and artifact publication remain available while the compatibility reader stays present.

## Testing And Validation

Functional coverage:
- `functional_tests/test_tabular_phase9_legacy_retirement.py` verifies decision modes, duplicate fallback suppression after shared durable acceptance, and observe-mode post-tool side-effect suppression.
- `functional_tests/test_tabular_shared_request_planner.py` verifies the shared planner and facade remain compatible.
- `functional_tests/test_tabular_search_shared_preflight_adapter.py` and `functional_tests/test_tabular_analyze_shared_preflight_adapter.py` verify Search and Analyze shared-preflight behavior still avoids duplicate legacy work after active acceptance.

Performance and limitations:
- Phase 9 does not delete compatibility wrappers or old-run readers.
- Phase 9 does not remove post-tool recovery while the mode remains `enabled`.
- Full scale, chaos, and final parent integration validation still require the broader Phase 9 matrix before the feature branch can merge to `Development`.
