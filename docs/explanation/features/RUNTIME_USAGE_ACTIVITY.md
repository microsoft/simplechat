# Runtime usage activity

Implemented in version: **0.261.447**

## Purpose and dependencies

Control Center activity readers can investigate adoption and reliability without reading conversations. **Agent, action & workflow usage** appears inside Activity Logs in both Classic and V2. It uses the existing activity log container and Control Center authorization; Application Insights configuration is not required for the usage report.

The application version is maintained in `application/single_app/config.py`. Existing record retention determines the available history.

## Recorded metadata

Each terminal invocation attempt records its server execution identity, canonical entity identity and configuration scope, configured label/type, outcome, and measured elapsed duration when available. Actual retries count as separate attempts; repeated delivery of the same completion event does not. Selecting an agent, loading an action, editing configuration, or opening a workflow is not an invocation.

Action records include the configured destination host, canonical operation name, and authentication category. A host excludes the URL's username, password, port, path, query, and fragment. An unknown authentication method is **unknown**, not **none**; internal actions may use **not_applicable**. Configuration scope identifies where the reusable entity is defined; execution workspace identifies where the work ran. They are not interchangeable.

The usage payload excludes prompts, agent instructions, conversation content/titles, workflow inputs, action arguments/results, response previews, complete URLs, credentials, raw configuration, and provider exception messages. Opaque execution IDs permit correlation without retrieving the underlying messages. Existing conversation and workflow-detail features have their own permissions and content policies; this feature does not replace them.

## Investigate use

1. Open **Control Center → Activity Logs**, then expand **Agent, action & workflow usage**.
2. Select an inclusive UTC date window. The default is 30 days; a window cannot exceed 366 days. V2 reuses the surrounding date/person/workspace filters; Classic provides those controls within the usage section.
3. Filter by entity kind or ID, configuration scope, configured host, authentication category, operation, or outcome. These are exact metadata filters. General log search and token/model filters do not apply to usage totals.
4. Review attempts, distinct executing users, and outcomes by kind. The ranking separates canonical scoped entities and their operation/host/authentication combinations, including historical connector configurations.
5. Choose **View events** to filter the activity log to that ranking row. Choose **Export usage CSV** for the same rankings and metadata, not raw activity JSON.

**Reload usage** recalculates the report. Complete results may otherwise be reused for 90 seconds. Loading or query failures are shown explicitly; narrow the range when a complete calculation exceeds the query budget.

## Metric interpretation

| Metric | Meaning |
| --- | --- |
| Attempts | Recorded invocations that reached an outcome, including failed/cancelled attempts and actual retries; not currently running jobs. |
| Distinct users | Unique executing user IDs in each category or ranking row. Summing rows can count the same person more than once. |
| Outcomes | Recorded success, failure, cancellation, timeout, partial completion, or unknown. Unknown does not imply success. |
| Average duration | Mean of available finite, nonnegative duration measurements. Missing durations are excluded, not treated as zero. |
| Timed / legacy | Coverage of measured duration and pre-instrumentation records in a ranking row. |

Nested agent/tool durations overlap. Neither adding durations across categories nor adding action and agent invocation totals measures exclusive compute time, token consumption, or cost. Existing token reports remain the source for token metrics; this feature does not allocate monetary cost.

The activity trend strip still uses its documented newest-5,000-record sample. Usage totals use a separate streaming metadata projection, not that sample or the visible page. Queries exceeding 250,000 records or 20,000 distinct ranking combinations fail explicitly instead of returning partial totals. Multiple reads are not a transactional snapshot against concurrent deletion or late-arriving events.

## Architecture and APIs

`runtime_usage.py` defines bootstrap-free metadata and outcome contracts. The initialized activity logger owns durable writes and deterministic event IDs. Connector bindings and execution context supply identity; request arguments and model-provided IDs do not authorize a lookup.

`functions_control_center_usage.py` aggregates narrow projections and exports allowlisted metadata. Both interfaces call the same service:

| API | Access and response |
| --- | --- |
| `GET /api/admin/control-center/activity-logs/usage` | Classic alias; requires Activity Logs access. |
| `GET /api/v2/control-center/activity-logs/usage` | V2 alias; the same authorization and report contract. |
| Either API with `format=csv` | Metadata-only ranking CSV with formula-prefixed cells escaped. |

Both routes accept `start_date`, `end_date`, executing `user_id`, execution workspace filters, and `usage_kind`, `usage_entity_id`, `usage_scope_type`, `usage_scope_id`, `usage_host`, `usage_auth`, `usage_operation`, and `usage_outcome`. `refresh=true` bypasses the short-lived cache. Invalid filters return 400, an incomplete calculation returns 422, and a query failure returns a safe 500 response. Dashboard-reader access alone does not grant access.

## Coverage and limitations

Historical agent/workflow records remain readable with missing metadata labeled unknown. Historical action executions cannot be reconstructed reliably and are not backfilled from conversations. Pre-instrumentation agent records do not represent complete failure/retry coverage.

Telemetry does not retry an external action or fail an otherwise completed operation when the activity store is unavailable. Such write failures produce sanitized operational diagnostics. Process termination and unavailable storage can leave gaps; counts describe recorded activity, not an exactly-once billing ledger.

The focused regressions live in `functional_tests/test_control_center_usage.py`, the activity route tests, runtime usage tests, and `ui_tests/test_control_center_runtime_usage.py`. They cover large-range aggregation, privacy projections, canonical scope grouping, access checks, export, and both browser interfaces.
