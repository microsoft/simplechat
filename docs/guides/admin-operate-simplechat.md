---
layout: page
title: "Operate SimpleChat day to day"
description: "Monitor, scale, review safety and feedback, manage data, and troubleshoot a running SimpleChat deployment."
section: "Guides"
audience: admin
---

## What this covers

This guide gives administrators a day-to-day operating loop for SimpleChat after deployment and first configuration: watch telemetry, scale proven bottlenecks, review feedback and safety events, manage retention and backups, and know where to look when something breaks.

{% include media.html type="video"
                      title="Operate SimpleChat day to day walkthrough"
                      poster="video-posters/guide-admin-operate-simplechat.png"
                      capture="Recording planned. Walk the full journey end to end and explain the decisions an admin makes along the way." %}

## Why it matters

SimpleChat depends on several Azure services that fail or saturate differently. App Service pressure, Cosmos RU exhaustion, Azure AI Search latency, model quota, extraction failures, and governance blocks need different responses. A steady operating rhythm keeps admins from guessing during incidents.

## Before you start

- Confirm [Logging settings]({{ '/admin/operations/' | relative_url }}) are configured for Application Insights and that temporary debug logging has an auto-turnoff window when used.
- Confirm [Backup, Migrate & Restore settings]({{ '/admin/backup-recovery/' | relative_url }}) have a valid storage target and a retention policy.
- Know which optional capabilities are enabled so you can check their backing Azure resources during incidents.
- Keep access to Azure Portal views for App Service, Cosmos DB, Azure AI Search, Azure OpenAI or Foundry, Document Intelligence, Storage, Redis, and Application Insights.

## Step 1: Monitor the application before changing settings

Use Application Insights and App Service logs to establish whether the issue is in the web tier, instrumentation, configuration, or a downstream dependency. The troubleshooting reference starts with failed requests and exceptions because those records identify the failing operation before you change Admin Settings.

{% include media.html src="guides/admin-operate-simplechat-monitor.png"
                      alt="Application Insights view showing failed requests and exceptions for a SimpleChat operation."
                      title="Monitor requests and exceptions"
                      capture="Capture Application Insights requests and exceptions with operation identifiers visible and user content redacted." %}

## Step 2: Scale the bottleneck you can prove

Use [Application Scaling]({{ '/application_scaling/' | relative_url }}) and [Scale settings]({{ '/admin/scale/' | relative_url }}) together. Scale App Service up for memory or CPU pressure and out for concurrent traffic. Watch Cosmos RU consumption and HTTP 429 responses before increasing throughput. Use Azure AI Search replicas, partitions, or higher tiers when query latency, indexing throughput, or service limits justify it. Treat AI service quota and rate limits as separate from web-tier capacity.

## Step 3: Review safety violations, feedback, and governed items

Use [Safety settings]({{ '/admin/security/' | relative_url }}) to control Content Safety, feedback collection, review role requirements, and conversation archiving. Use [Governance settings]({{ '/admin/governance/' | relative_url }}) to review personal, group, and global endpoints, agents, actions, and MCP destinations. Keep review roles assigned before enforcing review-only access.

{% include media.html src="guides/admin-operate-simplechat-review.png"
                      alt="Admin review surfaces for safety, feedback, and governed items."
                      title="Review operational queues"
                      capture="Capture safety, feedback, or governance review queues with any user content blurred or replaced by sample data." %}

## Step 4: Manage retention, archiving, and backups

Use [Workspaces settings]({{ '/admin/workspaces/' | relative_url }}) for default document and conversation retention by workspace type. Use [Safety settings]({{ '/admin/security/' | relative_url }}) when deletion should archive conversations instead of removing them immediately. Use [Backup, Migrate & Restore settings]({{ '/admin/backup-recovery/' | relative_url }}) for scheduled backups, restore preflight, job history, migration, and emergency Cosmos JSON edits.

## Step 5: Keep ingestion and source data under control

Use [Search and Extract settings]({{ '/admin/knowledge/' | relative_url }}) to tune extraction, chunking, URL Access, Web Search, Deep Research, Speech, and Video Indexer. Use [File Sync settings]({{ '/admin/knowledge/' | relative_url }}) to limit source counts, schedule frequency, files per run, GB per run, concurrency, recursive sources, and allowed workspace scopes before sync jobs grow unexpectedly.

## Step 6: Diagnose failures by layer

Start with [Troubleshooting]({{ '/troubleshooting/' | relative_url }}). Query failed requests, pivot to exceptions with the same `operation_Id`, and only then decide whether the problem is authentication, model routing, retrieval, extraction, storage, cache, or a feature toggle. Use temporary debug logging for short windows and turn it off after reproducing the issue.

{% include media.html src="guides/admin-operate-simplechat-diagnose.png"
                      alt="Troubleshooting flow showing requests, exceptions, Admin Settings, and Azure dependency checks."
                      title="Diagnose by layer"
                      capture="Capture the troubleshooting flow or a monitoring workbook that separates app, data, search, and AI service checks." %}

## Verify it worked

- Routine telemetry shows successful requests, expected latency, and no unexplained exception spike.
- Backup jobs complete on schedule and old backups follow the configured retention policy.
- Safety, feedback, governance, and file-processing queues are reviewed at the cadence your tenant requires.
- Scaling changes are tied to observed pressure such as CPU, memory, RU saturation, search latency, or AI service quota.
- Temporary debug logging is off outside active investigations.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| You cannot tell which backend call failed | The investigation started from settings instead of telemetry | Query Application Insights failed requests, capture `operation_Id`, then pivot to exceptions. |
| Horizontal scale causes inconsistent behavior | Shared cache or session assumptions were not ready | Review Redis-backed cache guidance in [Scale settings]({{ '/admin/scale/' | relative_url }}) before serious scale-out. |
| File processing history grows without cleanup | File-processing logs are enabled without a retention routine | Use [Logging settings]({{ '/admin/operations/' | relative_url }}) cleanup controls and set an operating cadence. |

## Related

- [Troubleshooting]({{ '/troubleshooting/' | relative_url }})
- [Application Scaling]({{ '/application_scaling/' | relative_url }})
- [Logging settings]({{ '/admin/operations/' | relative_url }})
- [Backup, Migrate & Restore settings]({{ '/admin/backup-recovery/' | relative_url }})
- [Update SimpleChat]({{ '/guides/admin-update-simplechat/' | relative_url }})
