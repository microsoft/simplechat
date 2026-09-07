---
layout: page
title: "Log Analytics"
description: "Reference for the Log Analytics SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: log-analytics -->

{% include media.html src="reference/actions-log-analytics-configuration.png" alt="The Log Analytics configuration pane showing workspace ID, cloud and API endpoint fields, Managed Identity authentication with a note about the Log Analytics Reader role, and a Test Connection button." title="Log Analytics action configuration" capture="Capture the Log Analytics action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Discovers Azure Log Analytics table schemas and runs read-only KQL queries against one workspace.

## Why and when to use it

Use it for operational telemetry and App Insights-style investigation. Use SQL/Snowflake/Databricks for business data.

## Before you start

- Workspace ID plus identity, user, service principal, or key access.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

Set Workspace ID, Cloud, optional endpoints, Authentication Method, and test the connection.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
