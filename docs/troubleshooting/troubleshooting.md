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
    url: /application_workflows/
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

