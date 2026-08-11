# Tabular Analyze/Search Parity Phase 3 Search Adapter

Implemented in version: **0.250.159**

## Overview

Phase 3 routes Search tabular durable preflight through the shared tabular request planner introduced in Phase 2. Search keeps its existing durable generated-output runner, source replay, authorization checks, artifact metadata, and bounded foreground fallback, but the decision point can now be owned by the shared planner when the Search-specific gate is enabled.

The behavior remains default-off. With the gate disabled, or with planner mode set to `off`, Search calls the legacy direct preflight path exactly as before.

## Dependencies

- Shared planner facade in `application/single_app/functions_tabular_orchestration.py`
- Lazy adapter surface in `application/single_app/functions_tabular_analysis.py`
- Existing Search direct durable preflight in `application/single_app/route_backend_chats.py`
- Existing durable generated-output runner in `application/single_app/functions_tabular_generated_exports.py`
- Current application version from `application/single_app/config.py`: **0.250.159**

## Technical Specifications

Search now calls `maybe_queue_search_tabular_generated_output(...)` at the preflight points that previously called the route-owned direct helper. The wrapper applies these rules:

- `enable_tabular_search_shared_preflight = False`: call the legacy direct preflight.
- `enable_tabular_search_shared_preflight = True` and `tabular_request_planner_mode = off` or invalid: call the legacy direct preflight.
- `tabular_request_planner_mode = shadow`: run shared planning without side effects, emit safe comparison telemetry, then call the legacy direct preflight.
- `tabular_request_planner_mode = active`: run the shared facade with the existing direct durable queue callback and return accepted generated-output metadata without a duplicate legacy call.
- Active foreground or ineligible results return `None`, so existing bounded Search tabular evidence continues normally.
- Shared preflight exceptions emit safe failure telemetry and fall back to the legacy direct preflight.

The route still retains `maybe_queue_direct_tabular_generated_output(...)` as the durable side-effect owner and compatibility safety net. Phase 3 does not remove the late post-tool generated-output fallback.

## Rollout Controls

Phase 3 uses the existing backend-only controls:

- `enable_tabular_search_shared_preflight`: default `False`.
- `tabular_request_planner_mode`: default `off`; supported active rollout values are `shadow` and `active`.

Both controls remain in the backend settings denylist used by `sanitize_settings_for_user(...)`, so non-admin frontend routes do not receive them.

## Usage Instructions

Operators can observe Search parity decisions by enabling `enable_tabular_search_shared_preflight` and setting `tabular_request_planner_mode` to `shadow`. In shadow mode, the shared planner records its decision without creating durable work, and Search still uses the legacy direct preflight outcome.

After shadow telemetry is acceptable, operators can set `tabular_request_planner_mode` to `active` for Search. Active mode still uses the existing direct durable runner callback and does not change Analyze behavior.

Rollback is immediate for new requests: set `enable_tabular_search_shared_preflight` to `False` or set `tabular_request_planner_mode` to `off`. Runs already accepted by the durable runner continue under their recorded generated-output contract.

## Testing and Validation

Functional coverage is in `functional_tests/test_tabular_search_shared_preflight_adapter.py`.

The test validates:

- Gate-off and planner-off behavior preserve the legacy direct preflight.
- Shadow mode invokes shared planning without durable side effects and then preserves legacy behavior.
- Active mode returns shared accepted metadata without a duplicate legacy preflight.
- Active foreground results decline to the existing bounded foreground Search path.
- Shared planner failures fall back to the legacy direct safety net.
- Search preflight call sites use the Phase 3 adapter with explicit required arguments.

The existing shared planner test remains the route-neutral facade contract, and the direct generated-output queue tests continue to cover the legacy durable side-effect owner.

## Known Limitations

Phase 3 migrates Search only. Analyze still uses its existing foreground-first path until the next phase activates Analyze durable preflight behind its own gate.
