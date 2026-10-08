# V2 Group Switch Latency Fix

Fixed in version: **0.261.305**

Related backend follow-up: [#1725](https://github.com/microsoft/simplechat/issues/1725).
The application version is recorded in `application/single_app/config.py`.

## Issue and root cause

Switching group workspaces waited for the complete V2 bootstrap response between
persisting the selection and reading the selected workspace's fresh context.
Production telemetry showed bootstrap taking approximately 5.1 seconds at the
median, compared with roughly 0.1 seconds for saving the selection and 0.15 seconds
for a workspace context read. A switch could therefore wait several seconds for
catalogs and other startup data that the selection itself did not change.

Some observed switches also coincided with an earlier bootstrap read. Their next
bootstrap request reached the server just after the earlier request finished.
Browser same-URL request coalescing is a possible explanation, not a confirmed
root cause: the telemetry lacks browser queueing information and user/session
identifiers. These timelines cannot prove all neighboring requests belonged to
the same browser.

## Technical changes

### Lightweight, server-authoritative confirmation

`GET /api/v2/scope` returns the authenticated viewer id and three active-scope
fields: `active_group_id`, `active_group_name`, and
`active_public_workspace_id`. It requires a signed-in, unrestricted User or
Admin session and is registered on the existing protected V2 Blueprint.

The endpoint reads the caller's saved preferences, current groups, and any
selected public workspace. It shares `_resolve_active_scope` with bootstrap,
filters unavailable selections, and returns `Cache-Control: no-store`.
Storage failures return an explicit 503 rather than an empty successful
selection. It sends no application settings or catalog content to the browser.

The group-switch sequence is now:

1. Confirm that leaving the current page is allowed.
2. Read the target workspace context to validate access.
3. Persist the active group through the existing `PATCH /api/groups/setActive`.
4. Confirm the persisted selection through `GET /api/v2/scope`.
5. Read the target context again before exposing editable workspace resources.

The preflight and final context reads remain because they validate current access.
A missing write acknowledgement still requires read-only reconciliation and
never causes the client to replay a possibly committed PATCH.

### Client state and response ordering

`bootstrapStore.refreshScope` validates the viewer and response shape and changes
only the three active-scope fields, preserving cached catalogs and workspace
lists. The group store uses this action for activation and reconciliation.
Responses from another sign-in or an older scope request cannot install state.
If another refresh has already installed a competing selection while the scope
read was pending, the scope read reports a conflict instead of hiding that change.

A full bootstrap that overlaps a scope refresh still updates branding, features,
and catalogs, but cannot restore an older active selection when it arrives late.
Bootstrap and scope fetches explicitly use `cache: 'no-store'`; other API requests
retain their existing cache behavior.

### Bootstrap phase timing

Each authenticated bootstrap execution emits one `[V2_BOOTSTRAP] Phase timings`
event, including failed executions. `time.perf_counter` measures settings reads
and sanitization, user settings, individual feature predicates, groups, public
workspaces, catalogs, scope resolution, workspace eligibility, safety warnings,
shell projections, and JSON serialization.

Timings are flat numeric properties because `log_event` reduces nested objects
to counts. Logging adds the `sc_` prefix, producing properties such as
`sc_total_ms` and `sc_phase_model_catalog_ms`. No user identity, settings contents,
catalog entries, or credentials are included in this timing event.

Example Application Insights query:

```kusto
traces
| where timestamp > ago(1d)
| where tostring(customDimensions.sc_message) == "[V2_BOOTSTRAP] Phase timings"
| extend total_ms = todouble(customDimensions.sc_total_ms),
         models_ms = todouble(customDimensions.sc_phase_model_catalog_ms),
         review_ms = todouble(customDimensions.sc_phase_source_review_ms)
| summarize p50_total_ms = percentile(total_ms, 50),
            p90_total_ms = percentile(total_ms, 90),
            p50_models_ms = percentile(models_ms, 50),
            p50_review_ms = percentile(review_ms, 50)
```

## Files and impact

Backend changes are in `route_backend_v2.py` and `config.py`. Frontend changes
are in `apiClient.ts`, `endpoints.ts`, `types.ts`, `bootstrapStore.ts`, and
`groupWorkspaceStore.ts`. The shared legacy active-group PATCH is unchanged.
The production V2 bundle is generated using `npm run build` in
`application/v2_ui`; generated assets remain outside source control.

First-load bootstrap still builds the complete startup payload. This fix removes
that work from group switching; it does not claim to fix initial-load latency.
The instrumentation informs the broader backend optimization tracked in #1725.

## Validation

Functional coverage includes `test_v2_scope_and_bootstrap_timings.py`,
`test_v2_bootstrap_refresh_logic.mjs`, and
`test_v2_group_workspace_context_logic.mjs`. Cases cover response shape, authorized
scope filtering, explicit storage failure, anonymous access, flat numeric timings,
overlapping bootstrap/scope reads, sign-in changes, cancellation, competing
selections, revoked access, and read-only recovery.

`ui_tests/test_v2_group_workspace_shell.py` exercises the real built SPA with
isolated HTTP fixtures. Desktop and mobile switch checks assert that a scope
confirmation replaces the extra bootstrap read, and recovery checks ensure an
ambiguous switch does not replay the PATCH. The existing route policy tests cover
the new endpoint's authenticated Blueprint and user-session requirements.

The removed bootstrap wait suggests a substantial switch improvement, but the
approximately one-second estimate is not a measured production result. After
deployment, compare repeated stopwatch and DevTools measurements, scope endpoint
latency, and bootstrap phase timings. Live Azure latency and first-load LCP are
not validated by isolated functional or browser tests.
