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

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Help settings]({{ '/admin/help/' | relative_url }})
- [Scale settings]({{ '/admin/scale/' | relative_url }})
