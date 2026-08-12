# Tabular Analyze/Search Parity Phase 4 Analyze Preflight

Implemented in version: **0.250.160**

## Overview

Phase 4 gives pure single-source tabular Analyze the same shared durable preflight decision point already introduced for Search. When the Analyze-specific gate and shared planner active mode are enabled, exhaustive tabular requests can be accepted by the existing durable generated-output runner before foreground tabular tools retrieve bounded rows.

The behavior remains default-off. With the gate disabled, planner mode set to `off`, planner mode set to `shadow`, or a bounded foreground aggregate classification, Analyze continues to use the existing foreground tabular document-action helper and synthesis prompt.

## Dependencies

- Shared planner facade in `application/single_app/functions_tabular_orchestration.py`
- Lazy adapter surface in `application/single_app/functions_tabular_analysis.py`
- Authorized source manifest contexts from `application/single_app/functions_mixed_source_orchestration.py`
- Existing workflow coordinator in `application/single_app/functions_workflow_runner.py`
- Existing durable generated-output runner in `application/single_app/functions_tabular_generated_exports.py`
- Current application version from `application/single_app/config.py`: **0.250.166**

## Technical Specifications

Pure tabular Analyze now invokes `_maybe_execute_pure_tabular_analyze_preflight(...)` immediately after authorized manifest resolution and partitioning. The helper only handles one authorized tabular source and declines mixed, unsupported, unresolved, narrative, or multi-tabular selections so later phases can define those contracts explicitly.

The wrapper applies these rules:

- `enable_tabular_analyze_durable_preflight = False`: preserve the existing foreground Analyze path.
- `tabular_request_planner_mode = off` or invalid: preserve the existing foreground Analyze path.
- `tabular_request_planner_mode = shadow`: run shared planning without durable side effects, emit safe comparison telemetry, then preserve the existing foreground path.
- `tabular_request_planner_mode = active` and durable metadata is returned: short-circuit foreground tabular tools and immediate synthesis, return generated-output metadata, and mark the source as pending or failed evidence depending on the queue result.
- Active foreground or ineligible planner results decline to the existing bounded foreground Analyze path.
- Shared preflight exceptions emit safe failure telemetry and preserve the existing foreground path unless cancellation was requested.

Accepted durable work uses the existing direct generated-output queue callback. Phase 4 does not add a new runner, source resolver, authorization model, artifact UI, mixed-source continuation, or per-document fan-out.

## Rollout Controls

Phase 4 uses backend-only controls:

- `enable_tabular_analyze_durable_preflight`: default `False`.
- `tabular_request_planner_mode`: default `off`; supported active rollout values are `shadow` and `active`.

Both controls remain in the backend settings denylist used by `sanitize_settings_for_user(...)`, so non-admin frontend routes do not receive them.

## Usage Instructions

Operators can observe Analyze parity decisions by enabling `enable_tabular_analyze_durable_preflight` and setting `tabular_request_planner_mode` to `shadow`. In shadow mode, the shared planner records its decision without creating durable work, and Analyze still uses the legacy foreground document-action path.

After shadow telemetry is acceptable, operators can set `tabular_request_planner_mode` to `active` for pure single-source tabular Analyze. Active accepted requests show the existing generated-output card and avoid manufacturing a competing immediate answer from bounded tool output.

Rollback is immediate for new requests: set `enable_tabular_analyze_durable_preflight` to `False` or set `tabular_request_planner_mode` to `off`. Runs already accepted by the durable runner continue under their recorded generated-output contract.

## Testing and Validation

Functional coverage is in `functional_tests/test_tabular_analyze_shared_preflight_adapter.py`.

The test validates:

- Active durable Analyze preflight returns generated-output metadata before foreground tools or immediate synthesis run.
- Authorized manifest contexts, including storage locators, are passed to the shared planner.
- Gate-off behavior preserves the foreground Analyze path.
- Shadow mode compares shared planning and preserves the foreground path.
- Active foreground classifications decline to bounded foreground Analyze.
- Failed durable metadata returns honest non-completion instead of pending or completed evidence.
- Mixed narrative plus tabular selections do not enter the single-source preflight path.

The existing shared planner, Search shared preflight, tabular document-action, and mixed-source Analyze tests remain the adjacent regression coverage for the Phase 1 through Phase 3 contracts.

## Known Limitations

Phase 4 handles pure single-source tabular Analyze only. Mixed narrative plus tabular deferred composition, recursive per-document Analyze, several tabular sources in one request, and broader Compare behavior remain intentionally outside this phase.
