# Control Center Orchestration Role Propagation Fix

**Version: 0.261.329**

Fixed in version: **0.261.329**, recorded in
`application/single_app/config.py`.

## Issue

A signed-in Control Center viewer could ask orchestration to compare dashboard
activity and chart daily trends. Planning selected the Control Center action, but
execution reported that the action was unavailable. The dependent summary and
chart were not delivered.

Application Insights and App Service console logs identified an
`external_source_preflight` refusal for `action_invoke`, with
`authority_reason=result_external_source_unavailable` and
`reason=selection_not_in_catalog`. The executor reported
`failure_code=integration_unavailable`. This happened before a Control Center
tool call, not while querying dashboard data.

## Root cause

Orchestration executes on a worker without the original Flask request context.
Its external-source identity reader captures the signed-in session's roles before
the worker starts and rechecks the actor's current conversation and user access.
Planning already supplied those roles to action discovery.

`OrchestrationExternalSourceProvider` did not forward that identity's roles to
either the action catalog reader or the exact action manifest resolver. Those
boundaries correctly refuse Control Center access without an authenticated role.
Their fallback to the current request session found no session on the worker, so
the catalog hid an action the planner had just selected.

Correcting discovery alone was insufficient: exact manifest resolution then
refused the same caller with `integration_access_denied`.

## Changes

The provider now supplies `user_roles=list(identity.roles)` when discovering
actions and resolving the selected action's exact manifest. Both operations use
the existing authenticated identity reader, not roles from a saved plan, run,
action record, or browser input.

These shared boundaries apply before invocation, during session-trusted
acquisition checks, when admitting results, and when reopening retained results.
The agent catalog callback and hand-selected-agent narrowing are unchanged.
Injected action catalog readers and resolvers accept the existing `user_roles`
keyword used by their production counterparts.

Permission rules have not changed:

- Only a caller whose current roles and Control Center settings grant dashboard
  access can use the global Control Center action.
- Current action enablement, governance, exact scope, and conversation access are
  still checked.
- Saved or ambient roles cannot override the authenticated external-source
  identity.
- Runs without a signed-in session remain refused. Plugin functions still check
  the signed-in session through the existing execution bridge before reading data.

No route, dashboard query, frontend control, deployment setting, or storage schema
changed.

## Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_orchestration_external_sources.py` | Forward authenticated roles to both action authorization boundaries. |
| `application/single_app/config.py` | Application patch version `0.261.329`. |
| `functional_tests/test_control_center_orchestration_roles.py` | Worker-context, exact-resolution, retained-result, and permission-revocation regressions. |
| Existing external-source, pre-effect, bootstrap, and seeded-agent tests | Accept and verify the action callback role parameter without changing the agent protocol. |
| `docs/explanation/features/CONTROL_CENTER_ACTION.md` | Explain worker preflight versus the plugin's signed-in execution bridge. |
| `docs/explanation/features/ORCHESTRATION_EXTERNAL_SOURCE_ACCESS.md` | Document the authenticated action callback contract. |

## Validation

The new regressions exercise the real external-source provider, action catalog,
and exact manifest resolver over existing isolated storage fixtures. Networking
is blocked. The role rule is the shipped Control Center capability function,
loaded through the existing bootstrap-free test helper.

The three allowed-role worker cases and the independent exact-resolution case
failed against the provider before this fix. The worker cases reproduced
`selection_not_in_catalog`; the exact-resolution case reproduced
`integration_access_denied`.

| Scenario | Before | After |
| --- | --- | --- |
| Admin or permitted dedicated Control Center viewer on a worker | Selected action refused before a tool call. | Preflight, acquisition checks, admission, persistence, and fresh-provider reads succeed. |
| Discovery succeeds but exact resolution has no Flask session | Manifest resolution refused the authorized caller. | Exact resolution receives the authenticated roles. |
| Dashboard access, action enablement, or governance revoked | Access must be refused. | Preflight and retained reads still refuse access. |
| Stale catalog or saved/ambient Admin roles | Must not grant access. | Exact resolution and current identity checks refuse access. |

Related suites cover existing action governance, session identity capture,
session-trusted result access, bootstrap and preflight wiring, selected-agent
behavior, and the read-only Control Center plugin. The combined run passed
**533 tests and 276 subtests** with the application's pinned Flask, Werkzeug,
and Semantic Kernel versions in an isolated test environment. Documentation
coverage passed all seven checks; documentation site quality passed all six.

Live deployment and chat retry are separate from this code fix and were not
performed.

## Related documentation

- [Control Center action](../features/CONTROL_CENTER_ACTION.md)
- [Retained orchestration external source access](../features/ORCHESTRATION_EXTERNAL_SOURCE_ACCESS.md)
