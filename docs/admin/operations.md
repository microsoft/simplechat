---
layout: page
title: "Operations settings"
description: "Operations collects Control Center access, refresh behavior, Application Insights, debug logging, file-processing logs, health checks, and Swagger documentation."
section: "Administration"
audience: admin
admin_tab: operations
redirect_from:
  - /admin/control-center-config/
  - /admin/logging/
---


# Operations settings

## What this group controls

Operations collects Control Center access, refresh behavior, Application Insights, debug logging, file-processing logs, health checks, and Swagger documentation.

## Why it matters

Operational settings determine what admins can observe during incidents. Enable enough telemetry to diagnose problems without leaving verbose logging or unauthenticated endpoints exposed longer than needed.

{% include media.html src="admin-settings/control-center.png" alt="Screenshot of the Operations group in Admin Settings." title="Operations settings" %}

{% include media.html src="admin-settings/logging.png" alt="Screenshot of the Operations group in Admin Settings." title="Operations settings" %}

{% include media.html type="video" title="Operations settings walkthrough" poster="video-posters/admin-operations.png" capture="Recording planned. Walk through each tab in the Operations group and explain when to change each setting." %}

## Before you change anything

- Create operational roles before restricting Control Center views.
- Confirm Application Insights configuration before relying on telemetry.
- Agree with security teams before exposing health-check or Swagger endpoints.

## Control Center {#control-center-config}

### Automatic Data Refresh {#control-center-auto-refresh-section}

The Automatic Data Refresh section belongs to the Control Center tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Control Center Access {#control-center-overview-section}

The Control Center Access section belongs to the Control Center tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Daily Control Center Refresh | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `control_center_auto_refresh_enabled` |
| Refresh Time () | Defines behavior for the related admin workflow; verify the affected feature after saving. | 02:00 | `control_center_auto_refresh_time` |
| Require ControlCenterAdmin App Role | Requires the `ControlCenterAdmin` app role before users can use this capability or view. | Off | `require_member_of_control_center_admin` |
| Allow ControlCenterDashboardReader App Role | Requires the `Allow ControlCenterDashboardReader` app role before users can use this capability or view. | Off | `require_member_of_control_center_dashboard_reader` |

## Logging & Health {#logging}

### Application Insights {#application-insights-section}

The Application Insights section belongs to the Logging & Health tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Debug Logging {#debug-logging-section}

The Debug Logging section belongs to the Logging & Health tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### File Process Logging {#file-processing-logs-section}

The File Process Logging section belongs to the Logging & Health tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Health Check {#health-check-section}

The Health Check section belongs to the Logging & Health tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### API Documentation {#swagger-section}

The API Documentation section belongs to the Logging & Health tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable /external/healthcheck | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_external_healthcheck`; capability toggle |
| Enable /external/healthcheckz | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_no_auth_external_healthcheck`; capability toggle |
| Enable Swagger/OpenAPI Documentation (/swagger) | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_swagger`; capability toggle |
| Enable Application Insights Global Logging | Sends global application, agent, and orchestration logging events to Application Insights. | Off | `enable_appinsights_global_logging`; capability toggle |
| Enable Debug Logging | Captures verbose diagnostic logs for troubleshooting until disabled or the timer turns it off. | Off | `enable_debug_logging`; capability toggle |
| Enable Time-based Auto Turnoff | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `debug_logging_timer_enabled` |
| Duration | Defines behavior for the related admin workflow; verify the affected feature after saving. | 1 | `debug_timer_value` |
| Time Unit | Defines behavior for the related admin workflow; verify the affected feature after saving. | hours | `debug_timer_unit` |
| Enable File Processing Logs | Records upload, extraction, indexing, and file-processing events for administrative troubleshooting. | On | `enable_file_processing_logs`; capability toggle |
| Enable Time-based Auto Turnoff | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `file_processing_logs_timer_enabled` |
| Duration | Defines behavior for the related admin workflow; verify the affected feature after saving. | 1 | `file_timer_value` |
| Time Unit | Defines behavior for the related admin workflow; verify the affected feature after saving. | hours | `file_timer_unit` |
| Delete logs older than | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | Runtime UI control |
| Age unit | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | Runtime UI control |

## Common tasks

1. **Configure Control Center.** Set refresh behavior and access requirements, then open Control Center. Outcome to verify: Only intended admins can view refreshed operational data.
2. **Enable useful logging.** Enable telemetry needed for a small operation and inspect the result. Outcome to verify: The operation leaves the expected trace.
3. **Expose health endpoints deliberately.** Enable the needed route and test monitoring. Outcome to verify: Monitoring probes the expected endpoint only.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| No telemetry appears | Application Insights or file-processing logs are disabled or misconfigured. | Enable the relevant logging path and rerun a reproducible operation. |

### Diagnose slow tabular model requests

An `AutoFunctionInvocationLoop` dependency measures the enclosing Semantic Kernel
operation, not each HTTP request to the model. To distinguish model HTTP waits
and SDK retries from fast spreadsheet tools, temporarily enable the diagnostic
client for the foreground `tabular-analysis` Azure OpenAI service. This does not
change ordinary chat clients, durable export clients, Custom endpoints, or
Anthropic clients.

For App Service code deployments, deploy the updated application, then add the
following environment settings and restart the app:

| Environment setting | Diagnostic default | Accepted values |
| --- | --- | --- |
| `SIMPLECHAT_TABULAR_HTTP_DIAGNOSTICS` | Off | `true`, `1`, `yes`, or `on` enables diagnostics |
| `SIMPLECHAT_TABULAR_HTTP_TIMEOUT_SECONDS` | `60` | Finite seconds from `1` through `600` per HTTP I/O timeout |
| `SIMPLECHAT_TABULAR_HTTP_MAX_RETRIES` | `0` | Integer from `0` through `2`; retries are in addition to the first attempt |
| `SIMPLECHAT_TABULAR_HTTP_BUDGET_SECONDS` | `180` | Finite seconds from `1` through `1800`, shared across HTTP attempts and tool rounds in one diagnostic client |

Timeout, retry, and budget overrides apply only when diagnostics is enabled.
Invalid numeric values use the diagnostic defaults. Set the retry count to `1`
to observe a controlled retry; leave it at `0` for the first fast-failure test.
The shared budget starts at the first HTTP attempt, includes elapsed time between
attempts, and limits an active HTTP send to the remaining budget. It does not
cancel spreadsheet loading, tool execution, SDK retry backoff, or final chat
synthesis outside this client. This is not a deadline for the entire chat turn.

Keep the existing Application Insights connection string configured. The new
events use `log_event` and do not require SimpleChat debug logging or
`OPENAI_LOG=debug`. Reproduce the request and run:

```kql
traces
| where timestamp > ago(1h)
| where tostring(customDimensions.sc_message) startswith "[TABULAR_MODEL_HTTP]"
| project timestamp,
  event = tostring(customDimensions.sc_operation),
  run_id = tostring(customDimensions.sc_diagnostic_run_id),
  attempt_id = tostring(customDimensions.sc_http_attempt_id),
  attempt = toint(customDimensions.sc_attempt_sequence),
  sdk_retry = toint(customDimensions.sc_retry_count),
  duration_ms = todouble(customDimensions.sc_duration_ms),
  status_code = toint(customDimensions.sc_status_code),
  error_type = tostring(customDimensions.sc_error_type),
  underlying_error = tostring(customDimensions.sc_reason),
  budget_exhausted = tobool(customDimensions.sc_budget_exhausted),
  provider_request_id = tostring(customDimensions.sc_provider_request_id),
  endpoint_fingerprint = tostring(customDimensions.sc_endpoint_fingerprint),
  operation_Id
| order by timestamp asc
```

Each SDK HTTP attempt has an `attempt_started` event followed by
`attempt_completed` or `attempt_failed`. Completion does not necessarily mean a
successful HTTP status: inspect `status_code`. All attempts for one diagnostic
client share `run_id`, including SDK retries and subsequent tool-result calls.
An endpoint fingerprint hashes the host, port, and request path to distinguish
deployment destinations without publishing their names or URLs. Provider request
IDs are recorded only when an allowlisted response header is available; failures
before response headers arrive have none. Events never contain request bodies,
response bodies, tool payloads, authorization headers, or exception messages.

After testing, remove these settings or set
`SIMPLECHAT_TABULAR_HTTP_DIAGNOSTICS=false` and restart. This restores the existing
SDK defaults. The focused regression command is
`python -m pytest functional_tests/test_tabular_model_http_diagnostics.py -q`.

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Help settings]({{ '/admin/help/' | relative_url }})
- [Scale settings]({{ '/admin/scale/' | relative_url }})
