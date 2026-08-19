---
layout: page
title: "Logging Settings"
description: "Controls Application Insights logging, temporary debug logging, file-processing logs, and stored-log cleanup."
section: "Administration"
audience: admin
admin_tab: logging
---

## What this tab controls

Controls Application Insights logging, temporary debug logging, file-processing logs, and stored-log cleanup.

## Why it matters

Logging is the difference between guessing and diagnosing, but it can also increase storage and expose sensitive operational details. Application Insights is appropriate for ongoing telemetry; debug logging and file-processing logs should be temporary or intentionally retained with cleanup.

{% include media.html src="admin/logging-overview.png" alt="Screenshot of the Logging settings tab showing logging tab." title="Logging tab" capture="Capture the Logging tab for Logging tab. Show relevant controls and redact secrets." %}

{% include media.html type="video" title="Logging settings walkthrough" poster="video-posters/admin-logging.png" capture="Recording planned. Walk through every setting on the Logging tab and explain when to change each one." %}

## Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Application Insights Global Logging | Sends global application, agent, and orchestration logging events to Application Insights. | Off | `enable_appinsights_global_logging`; capability toggle |
| Enable Debug Logging | Captures verbose diagnostic logs for troubleshooting until disabled or the timer turns it off. | Off | `enable_debug_logging`; capability toggle |
| Enable Time-based Auto Turnoff | Controls how SimpleChat uses enable time-based auto turnoff on this tab. | Off | `debug_logging_timer_enabled` |
| Duration | Controls how SimpleChat uses duration on this tab. | 1 | `debug_timer_value` |
| Time Unit | Controls how SimpleChat uses time unit on this tab. | hours | `debug_timer_unit` |
| Enable File Processing Logs | Records upload, extraction, indexing, and file-processing events for administrative troubleshooting. | On | `enable_file_processing_logs`; capability toggle |
| Enable Time-based Auto Turnoff | Controls how SimpleChat uses enable time-based auto turnoff on this tab. | Off | `file_processing_logs_timer_enabled` |
| Duration | Controls how SimpleChat uses duration on this tab. | 1 | `file_timer_value` |
| Time Unit | Controls how SimpleChat uses time unit on this tab. | hours | `file_timer_unit` |
| Delete logs older than | Controls how SimpleChat uses delete logs older than on this tab. | Not specified in defaults | Runtime UI control |
| Age unit | Controls how SimpleChat uses age unit on this tab. | Not specified in defaults | Runtime UI control |

### Debug logging

Debug logging is for short investigations. Use the timer fields so sensitive diagnostic detail does not keep flowing after the incident window closes.

### File-processing logs

File-processing logs help diagnose upload, extraction, indexing, and sync runs. They are useful during rollout, but cleanup controls should be part of the same operating procedure.

## Before you change anything

- Confirm Application Insights is configured for the app before enabling global logging.
- Use debug logging only for a short diagnostic window because it can collect sensitive details.
- Choose a file-processing log retention period before enabling long-running processing logs.

## Common tasks

1. **Enable Application Insights logging.**
    1. Enable **Enable Application Insights Global Logging**.
    2. Save settings.
    3. Restart the app if required by the deployment.
    4. Confirm events appear in Application Insights.
    Outcome to verify: Operational events flow into Azure monitoring.

{% include media.html src="admin/logging-enable-application-insights-logging.png" alt="Screenshot of the Logging settings tab showing enable application insights logging." title="Logging: Enable Application Insights logging" capture="Capture the Logging tab while performing Enable Application Insights logging. Show the relevant controls and redact secrets." %}

2. **Run temporary debug logging.**
    1. Enable **Enable Debug Logging**.
    2. Enable **Time-based Auto Turnoff**.
    3. Set **Duration** and **Time Unit**.
    4. Save, reproduce the issue, then verify logging turns off.
    Outcome to verify: Debug logging captures only the diagnostic window.

{% include media.html src="admin/logging-run-temporary-debug-logging.png" alt="Screenshot of the Logging settings tab showing run temporary debug logging." title="Logging: Run temporary debug logging" capture="Capture the Logging tab while performing Run temporary debug logging. Show the relevant controls and redact secrets." %}

3. **Clean up file-processing logs.**
    1. Enable **File Processing Logs** only when processing history is needed.
    2. Use **Delete logs older than** and **Age unit** for cleanup.
    3. Confirm the permanent-delete prompt.
    4. Review remaining log entries.
    Outcome to verify: Stored processing logs are reduced to the intended window.

{% include media.html src="admin/logging-clean-up-file-processing-logs.png" alt="Screenshot of the Logging settings tab showing clean up file-processing logs." title="Logging: Clean up file-processing logs" capture="Capture the Logging tab while performing Clean up file-processing logs. Show the relevant controls and redact secrets." %}

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Debug logging stays on too long | Time-based auto turnoff is disabled or duration is too long. | Enable auto turnoff and set a short duration. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Scale]({{ '/admin/scale/' | relative_url }})
- [Safety]({{ '/admin/safety/' | relative_url }})
