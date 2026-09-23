---
layout: showcase-page
title: "Troubleshooting"
permalink: /troubleshooting/
menubar: docs_menu
accent: rose
eyebrow: "Diagnose The Right Layer"
description: "Start with telemetry, narrow the failing request path, and then decide whether the issue is instrumentation, configuration, or a backend dependency."
hero_icons:
  - bi-wrench-adjustable-circle
  - bi-bug
  - bi-activity
hero_pills:
  - Observe before changing config
  - Use Application Insights traces
  - Restart only when required
hero_links:
  - label: Review workflows
    url: /reference/application-workflows/
    style: primary
  - label: Check admin configuration
    url: /admin_configuration/
    style: secondary
---
Most support work on Simple Chat starts with one question: is the failure in the app layer, in telemetry wiring, or in a downstream Azure dependency? This page gives the shortest path to answer that question.

<section class="latest-release-card-grid">
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-bar-chart"></i></div>
		<h2>OpenTelemetry settings</h2>
		<p>Use the official Azure Monitor and OpenTelemetry references when instrumentation variables or exporter settings are in question.</p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-diagram-3"></i></div>
		<h2>Failing backend calls</h2>
		<p>Trace the failed request in Application Insights first, capture the `operation_Id`, and pivot from requests into exceptions.</p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-power"></i></div>
		<h2>Startup instrumentation errors</h2>
		<p>If Flask instrumentation itself is breaking startup, disable it explicitly with an environment variable and restart the app.</p>
	</article>
</section>

## OpenTelemetry Settings

- [Azure Monitor OpenTelemetry distribution](https://pypi.org/project/azure-monitor-opentelemetry/)
- [OpenTelemetry SDK environment variable reference](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/)

## Backend Call Failing

Simple Chat uses Flask instrumentation by default, and backend calls are logged to Application Insights. Start with the `requests` table to find the failing call, capture the `operation_Id`, and use that identifier to pivot into related exceptions.

### Query failed requests

```kusto
requests
| where success == false
```

### Query most recent exceptions

```kusto
exceptions
| top 10 by timestamp
```

### Query exceptions associated with a specific `operation_Id`

```kusto
exceptions
| where operation_Id == '61a97b6a6ddc11b465b5289738bddcf1'
```

## Flask Instrumentation Startup Error

If startup logs show an error while Flask instrumentation is initializing, disable it with the `DISABLE_FLASK_INSTRUMENTATION` environment variable. Set the value to `1` or `true`, then restart the app service so the process starts cleanly without the instrumentation hook.

## Admin settings saves and connection tests

The diagnostics below apply to **0.261.125** and later. A redirect after posting the classic settings form is not proof that the save succeeded: check its banner and correlate the request with dependency operations.

### Key Vault can be read but settings will not save

The older connection test only listed secret properties. An identity with **Key Vault Secrets User** could pass that test and still receive `ForbiddenByRbac` when saving a secret. Grant **Key Vault Secrets Officer on the vault** to the identity actually selected by the application, not just the deploying account. For access-policy vaults, grant Get, List, Set, and Delete. Network restrictions can also produce a 403.

The current test verifies list, write, read-back, and deletion of a uniquely owned temporary secret using the values currently in the form. A write or cleanup failure remains a failed test. Follow the reported cleanup instruction only for the generated `simplechat-connection-test-*` secret. The test does not purge soft-deleted metadata.

For this incident, successful Cosmos reads preceded the failed Key Vault writes. A prior Cosmos key rotation was a separate authentication problem. Diagnose each dependency from its own operation and time window rather than rotating Cosmos keys again to address a Key Vault permission failure.

### Search checks fail or a form becomes stale

An error importing `search_resource_manager` from `config` identifies the public-cloud configuration regression fixed in **0.261.125**. It occurs before Search authentication, so changing Search or Cosmos keys does not repair it.

The same release makes unchanged schema observations read-only and sequences initial index checks. The page updates its hidden revision only after its own conditional metadata operation. If another settings edit wins, the page keeps the draft and asks for a reload; copy the unsaved values before reviewing the latest settings. Do not substitute an arbitrary latest revision or bypass the conflict check.

Redis-required settings writes intentionally fail closed if safe shared publication is unavailable. Repair that dependency rather than bypassing it with a direct Cosmos write. The model discovery and model-test APIs remain supported by classic and V2 clients.

### Find the diagnostic stage

Human-readable `log_event` messages are in `customDimensions.sc_message`. Query the stable tags and correlate the resulting `operation_Id` with requests and dependencies:

```kusto
traces
| where timestamp > ago(1h)
| extend app_message = tostring(customDimensions.sc_message)
| where app_message has_any ("[AKV_TEST]", "[KEY_VAULT]", "[EMBEDDING]")
| project timestamp, operation_Id, app_message,
          stage = tostring(customDimensions.sc_stage),
          error_type = tostring(customDimensions.sc_error_type),
          status_code = tostring(customDimensions.sc_status_code)
| order by timestamp desc
```

Use the equivalent Application Insights table and properties columns when querying a Log Analytics workspace. Responses deliberately omit raw provider exceptions and secret values. See the [Key Vault setup guidance]({{ '/admin/security/#keyvault-section' | relative_url }}) and [Search settings]({{ '/admin/knowledge/#azure-ai-search-section' | relative_url }}).

## Mixed-Source Partial Coverage

A mixed-source answer may complete with partial coverage when one narrative retrieval, table tool call, authorization check, or comparison Target cannot complete. This is expected fail-closed behavior: a failed table is not silently treated as narrative text, and prior conversation evidence does not fill a gap in the current selection.

1. Review the response coverage summary for completed, partial, failed, and skipped source counts.
2. Confirm the relevant mixed-source mode flag is enabled and subordinate rollout flags are not being assumed.
3. Recheck personal ownership or approved sharing, group membership, public visibility, and chat-upload conversation ownership.
4. For Analyze All, confirm the document access index is ready and the authorized catalog does not exceed the configured workflow Analyze limit.
5. If aggregate development telemetry is enabled, correlate `MixedSourceTelemetry` events by `request_correlation_id` and inspect only counts, mode, status, cancellation phase, and latency. Source content or identity should never appear.

If cancellation occurs, no final assistant response or new generated artifact should be published. A background tabular export that was already queued is canceled through its existing export run status.
