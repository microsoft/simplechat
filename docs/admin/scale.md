---
layout: page
title: "Scale settings"
description: "Scale covers Redis, conversation and search caches, document access indexing, Cosmos maintenance, and Cosmos throughput automation."
section: "Administration"
audience: admin
admin_tab: scale
---


# Scale settings

## What this group controls

Scale covers Redis, conversation and search caches, document access indexing, Cosmos maintenance, and Cosmos throughput automation.

## Why it matters

Scale settings trade latency, freshness, and Azure spend. Caches can make the app faster, while throughput automation can prevent throttling, but both need guardrails.

{% include media.html src="admin-settings/scale.png" alt="Screenshot of the Scale group in Admin Settings." title="Scale settings" %}

{% include media.html type="video" title="Scale settings walkthrough" poster="video-posters/admin-scale.png" capture="Recording planned. Walk through each tab in the Scale group and explain when to change each setting." %}

## Before you change anything

- Provision Redis before enabling shared cache behavior.
- Understand Cosmos RU baselines before enabling automatic scale changes.
- Review document access index rollout state before changing cache or repair settings.

## Redis & Caching {#redis-caching}

### Redis Cache {#redis-cache-section}

The Redis Cache section belongs to the Redis & Caching tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Redis Metrics {#redis-monitoring-section}

The Redis Metrics section belongs to the Redis & Caching tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Conversation Cache {#conversation-cache-section}

The Conversation Cache section belongs to the Redis & Caching tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Redis Cache | Uses Redis for shared cache/session scenarios so multiple app instances can share cached state. | Off | `enable_redis_cache`; capability toggle |
| Redis Server Host Name | Defines behavior for the related admin workflow; verify the affected feature after saving. | Empty | `redis_url` |
| Redis Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | Empty | `redis_auth_type` |
| Key Vault Secret Name Redis Access Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `redis_key` |
| Enable conversation cache | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_conversation_cache`; capability toggle |
| Cache TTL Seconds | Default 120 seconds. User-scoped version invalidation refreshes changed conversations; set to 0 to skip writing new entries. | 120 | `conversation_cache_ttl_seconds` |
| Redis document list cache Wave 6 | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_document_access_index_cache`; capability toggle |
| Cache TTL Seconds | Default 900 seconds. Scope-version invalidation makes document changes visible immediately; TTL clears unreachable old entries. | 900 | `document_access_index_cache_ttl_seconds` |

## Cosmos {#cosmos}

### DAI Metrics {#document-access-index-section}

The DAI Metrics section belongs to the Cosmos tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Cosmos Maintenance {#cosmos-maintenance-section}

A recurring background job keeps Cosmos in the shape the application expects: it compares composite index policies against what the current code needs, reconciles the document access index by repairing fail-open projection records and running a bounded backfill batch, and clears stale operational cache documents. Newly upgraded deployments rely on it to converge, since the document access index read path falls back to slower source queries until backfill catches up.

The section also runs a maintenance pass on demand and reports what the last run did, which is the quickest way to confirm an upgrade has settled.

Both switches below default to on and should stay on. Turning off the scheduler stops repair and backfill from converging at all. Turning off the startup pass only delays convergence to the next scheduled run, which is a reasonable trade when application start time matters more than picking up new index policies immediately after a deployment.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Run background maintenance | Runs the recurring job that checks Cosmos composite index policies, reconciles the document access index, and clears stale cache documents. | On | `enable_app_maintenance`; capability toggle |
| Also run maintenance at startup | Runs one maintenance pass as the application starts, so a deployment picks up new index policies without waiting for the next scheduled run. | On | `enable_startup_app_maintenance`; capability toggle |

### Cosmos DB Throughput {#cosmos-throughput-section}

The Cosmos DB Throughput section belongs to the Cosmos tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Cosmos Metrics {#cosmos-throughput-metrics-table-section}

The Cosmos Metrics section belongs to the Cosmos tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Key Filter | Blank filter browses all keys. Filters are case sensitive. Redis SCAN order is server-defined, so use Next Page to keep browsing. | N/A (runtime control) | Runtime UI control |
| Page Size | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | Runtime UI control |
| Search result caching | Caches workspace search-result payloads with document-set fingerprints so repeated personal, group, public, or all-scope searches can reuse results until document changes or the TTL invalidate them. | On | `enable_search_result_caching`; no visible field in `admin_settings.html` |
| Write-through projection | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_document_access_index_write_through`; capability toggle |
| Automatic repair/backfill | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_startup_document_access_index_backfill`; capability toggle |
| Enable shadow validation | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_document_access_index_shadow_validation`; capability toggle |
| Backfill Batch Size | Documents processed per manual or scheduled batch. | 200 | `document_access_index_backfill_batch_size` |
| Repair Batch Size | Fail-open repair records reconciled before each backfill batch. | 100 | `document_access_index_repair_batch_size` |
| Document access index reads Wave 5B default | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_document_access_index_reads`; capability toggle |
| Cosmos Throughput Container Policies Json | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `cosmos_throughput_container_policies_json` |
| Enable Cosmos throughput automation | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `cosmos_throughput_autoscale_enabled` |
| Subscription ID | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `cosmos_throughput_subscription_id` |
| Resource Group | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `cosmos_throughput_resource_group` |
| Cosmos Account | Provides displayed text that users see in the affected interface. | Not specified in defaults | `cosmos_throughput_account_name` |
| Database | Provides displayed text that users see in the affected interface. | Not specified in defaults | `cosmos_throughput_database_name` |
| Metrics Window | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 5 | `cosmos_throughput_metrics_window_minutes` |
| Auto scale up | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `cosmos_throughput_auto_scale_up_enabled` |
| Scale Up At | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 90 | `cosmos_throughput_scale_up_threshold_percent` |
| Scale Up Step | Defines behavior for the related admin workflow; verify the affected feature after saving. | 1000 | `cosmos_throughput_scale_up_step_ru` |
| Scale Up Interval | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 5 | `cosmos_throughput_scale_up_cooldown_minutes` |
| Maximum RU/s | SimpleChat-managed scaling stops at 10,000 RU/s. Use the Azure portal above this limit. | Not specified in defaults | `cosmos_throughput_max_ru` |
| Ignore maximum guardrail | Defines a capacity or timing boundary that keeps the feature inside supported limits. | Off | `cosmos_throughput_ignore_max_limit` |
| Auto scale down | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `cosmos_throughput_auto_scale_down_enabled` |
| Scale Down At | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 70 | `cosmos_throughput_scale_down_threshold_percent` |
| Scale Down Step | Defines behavior for the related admin workflow; verify the affected feature after saving. | 1000 | `cosmos_throughput_scale_down_step_ru` |
| Scale Down Interval | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 20 | `cosmos_throughput_scale_down_cooldown_minutes` |
| Minimum RU/s | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `cosmos_throughput_min_ru` |
| Ignore minimum guardrail | Defines a capacity or timing boundary that keeps the feature inside supported limits. | Off | `cosmos_throughput_ignore_min_limit` |
| Convert manual throughput to Cosmos autoscale | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `cosmos_throughput_convert_manual_to_autoscale_enabled` |
| Enforce global policy for all containers | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `cosmos_throughput_enforce_container_defaults` |
| Filter Containers | Defines behavior for the related admin workflow; verify the affected feature after saving. | N/A (runtime control) | Runtime UI control |
| Filter Container Policies | Defines behavior for the related admin workflow; verify the affected feature after saving. | N/A (runtime control) | Runtime UI control |

## Common tasks

1. **Enable Redis caching.** Set Redis host and authentication, then test a cache-dependent page. Outcome to verify: Distributed cache state is available.
2. **Tune cache freshness.** Set TTLs and change a test document. Outcome to verify: Users see expected freshness behavior.
3. **Guard Cosmos throughput.** Set thresholds, steps, cooldowns, and RU guardrails, then refresh metrics. Outcome to verify: Capacity changes stay within guardrails.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Cosmos scaling changes too often | Thresholds or cooldowns are too aggressive. | Adjust thresholds after reviewing metrics. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Operations settings]({{ '/admin/operations/' | relative_url }})
- [Backup & Recovery settings]({{ '/admin/backup-recovery/' | relative_url }})
