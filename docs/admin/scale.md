---
layout: page
title: "Scale Settings"
description: "Controls Redis, conversation and document-access caches, Cosmos maintenance and throughput automation, and Front Door support."
section: "Administration"
audience: admin
admin_tab: scale
---

## What this tab controls

Controls Redis, conversation and document-access caches, Cosmos maintenance and throughput automation, and Front Door support.

## Why it matters

Scale settings trade freshness, cost, and resilience. Redis and caches reduce repeated reads but require cache invalidation to work correctly. Cosmos throughput automation can prevent throttling but changes RU spend. Front Door settings affect redirect URLs and sign-in behavior for every user behind the routed domain.

{% include media.html src="admin/scale-overview.png" alt="Screenshot of the Scale settings tab showing scale tab." title="Scale tab" capture="Capture the Scale tab for Scale tab. Show relevant controls and redact secrets." %}

{% include media.html type="video" title="Scale settings walkthrough" poster="video-posters/admin-scale.png" capture="Recording planned. Walk through every setting on the Scale tab and explain when to change each one." %}

## Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Redis Cache | Uses Redis for shared cache/session scenarios so multiple app instances can share cached state. | Off | `enable_redis_cache`; capability toggle |
| Redis Server Host Name | Controls how SimpleChat uses redis server host name on this tab. | Empty | `redis_url` |
| Redis Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | Empty | `redis_auth_type` |
| Key Vault Secret Name Redis Access Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `redis_key` |
| Key Filter | Blank filter browses all keys. Filters are case sensitive. Redis SCAN order is server-defined, so use Next Page to keep browsing. | N/A (runtime control) | Runtime UI control |
| Page Size | Controls how SimpleChat uses page size on this tab. | Not specified in defaults | Runtime UI control |
| Enable conversation cache | Makes conversation cache available in the product when its required service and access policy are configured. | On | `enable_conversation_cache`; capability toggle |
| Search result caching | Caches workspace search-result payloads with document-set fingerprints so repeated personal, group, public, or all-scope searches can reuse results until document changes or the TTL invalidate them. | On | `enable_search_result_caching`; no visible field in `admin_settings.html` |
| Cache TTL Seconds | Default 120 seconds. User-scoped version invalidation refreshes changed conversations; set to 0 to skip writing new entries. | 120 | `conversation_cache_ttl_seconds` |
| Write-through projection | Makes write-through projection available in the product when its required service and access policy are configured. | On | `enable_document_access_index_write_through`; capability toggle |
| Automatic repair/backfill | Makes automatic repair/backfill available in the product when its required service and access policy are configured. | On | `enable_startup_document_access_index_backfill`; capability toggle |
| Enable shadow validation | Makes shadow validation available in the product when its required service and access policy are configured. | Off | `enable_document_access_index_shadow_validation`; capability toggle |
| Backfill Batch Size | Documents processed per manual or scheduled batch. | 200 | `document_access_index_backfill_batch_size` |
| Repair Batch Size | Fail-open repair records reconciled before each backfill batch. | 100 | `document_access_index_repair_batch_size` |
| Document access index reads Wave 5B default | Makes document access index reads wave 5b default available in the product when its required service and access policy are configured. | On | `enable_document_access_index_reads`; capability toggle |
| Redis document list cache Wave 6 | Makes redis document list cache wave 6 available in the product when its required service and access policy are configured. | On | `enable_document_access_index_cache`; capability toggle |
| Cache TTL Seconds | Default 900 seconds. Scope-version invalidation makes document changes visible immediately; TTL clears unreachable old entries. | 900 | `document_access_index_cache_ttl_seconds` |
| Cosmos Throughput Container Policies Json | Controls how SimpleChat uses cosmos throughput container policies json on this tab. | Not specified in defaults | `cosmos_throughput_container_policies_json` |
| App maintenance background scheduler | Allows the background maintenance loop to run app maintenance jobs such as Cosmos index policy checks and stale cache cleanup according to the maintenance interval and lease settings. | On | `enable_app_maintenance`; no visible field in `admin_settings.html` |
| Enable Cosmos throughput automation | Controls how SimpleChat uses enable cosmos throughput automation on this tab. | Off | `cosmos_throughput_autoscale_enabled` |
| Subscription ID | Controls how SimpleChat uses subscription id on this tab. | Not specified in defaults | `cosmos_throughput_subscription_id` |
| Resource Group | Controls how SimpleChat uses resource group on this tab. | Not specified in defaults | `cosmos_throughput_resource_group` |
| Cosmos Account | Controls the user-facing copy or name shown for cosmos account. | Not specified in defaults | `cosmos_throughput_account_name` |
| Database | Controls the user-facing copy or name shown for database. | Not specified in defaults | `cosmos_throughput_database_name` |
| Metrics Window | Caps or schedules metrics window so the feature stays within expected capacity. | 5 | `cosmos_throughput_metrics_window_minutes` |
| Auto scale up | Controls how SimpleChat uses auto scale up on this tab. | On | `cosmos_throughput_auto_scale_up_enabled` |
| Scale Up At | Caps or schedules scale up at so the feature stays within expected capacity. | 90 | `cosmos_throughput_scale_up_threshold_percent` |
| Scale Up Step | Controls how SimpleChat uses scale up step on this tab. | 1000 | `cosmos_throughput_scale_up_step_ru` |
| Scale Up Interval | Caps or schedules scale up interval so the feature stays within expected capacity. | 5 | `cosmos_throughput_scale_up_cooldown_minutes` |
| Maximum RU/s | SimpleChat-managed scaling stops at 10,000 RU/s. Use the Azure portal above this limit. | Not specified in defaults | `cosmos_throughput_max_ru` |
| Ignore maximum guardrail | Caps or schedules ignore maximum guardrail so the feature stays within expected capacity. | Off | `cosmos_throughput_ignore_max_limit` |
| Auto scale down | Controls how SimpleChat uses auto scale down on this tab. | On | `cosmos_throughput_auto_scale_down_enabled` |
| Scale Down At | Caps or schedules scale down at so the feature stays within expected capacity. | 70 | `cosmos_throughput_scale_down_threshold_percent` |
| Scale Down Step | Controls how SimpleChat uses scale down step on this tab. | 1000 | `cosmos_throughput_scale_down_step_ru` |
| Scale Down Interval | Caps or schedules scale down interval so the feature stays within expected capacity. | 20 | `cosmos_throughput_scale_down_cooldown_minutes` |
| Minimum RU/s | Controls how SimpleChat uses minimum ru/s on this tab. | Not specified in defaults | `cosmos_throughput_min_ru` |
| Ignore minimum guardrail | Caps or schedules ignore minimum guardrail so the feature stays within expected capacity. | Off | `cosmos_throughput_ignore_min_limit` |
| Convert manual throughput to Cosmos autoscale | Controls how SimpleChat uses convert manual throughput to cosmos autoscale on this tab. | Off | `cosmos_throughput_convert_manual_to_autoscale_enabled` |
| Enforce global policy for all containers | Controls how SimpleChat uses enforce global policy for all containers on this tab. | Off | `cosmos_throughput_enforce_container_defaults` |
| Filter Containers | Controls how SimpleChat uses filter containers on this tab. | N/A (runtime control) | Runtime UI control |
| Filter Container Policies | Controls how SimpleChat uses filter container policies on this tab. | N/A (runtime control) | Runtime UI control |
| Enable Front Door Support | Generates user-facing and OAuth redirect URLs using the configured Front Door or load-balancer base URL. | Off | `enable_front_door`; capability toggle |
| Front Door URL | The base URL of your Front Door or load balancer. The system will automatically generate: Home redirect: https://your-frontdoor.azurefd.net OAuth2 redirect: https://your-frontdoor.azurefd.net/getAToken | Empty | `front_door_url` |

### Redis cache

Redis enables distributed caching across app instances. Conversation and document-list caches improve latency, but stale or unreachable Redis can affect freshness until invalidation or TTL clears entries.

### Cosmos throughput automation

Throughput automation monitors RU consumption and changes Cosmos capacity inside configured guardrails. Scale-up protects users from throttling; scale-down controls cost. Use conservative thresholds until production patterns are known.

### Front Door

Front Door support tells SimpleChat to generate user-facing and OAuth redirect URLs through the routed domain. Misconfiguration can break sign-in redirects, so validate login through the Front Door URL after saving.

### Search result caching

Search result caching is not exposed as a visible field in `admin_settings.html`, but `utils_cache.py` reads `enable_search_result_caching` and `search_cache_ttl_seconds`. When enabled, cache keys include document-set fingerprints so changes to personal, group, or public documents invalidate affected results. The tradeoff is faster repeated searches versus relying on cache invalidation and TTL for freshness.

### App maintenance background scheduler

`enable_app_maintenance` is not shown as a visible admin field. The background task loop reads it before running application maintenance, including bounded maintenance jobs such as Cosmos indexing policy work and stale cache cleanup. Disabling it would stop those automatic background maintenance passes, so operators would need to run maintenance manually or accept drift until the setting is restored.

## Before you change anything

- Provision Redis and choose key, managed identity, or Key Vault authentication before enabling Redis cache.
- Confirm Cosmos account, database, subscription, and resource group before enabling throughput automation.
- Understand current RU limits before enabling automatic scale up or down.
- Configure Front Door hostnames and authentication redirect URLs before enabling Front Door support.

## Common tasks

1. **Enable Redis-backed caching.**
    1. Enable **Enable Redis Cache**.
    2. Enter **Redis Server Host Name**.
    3. Choose **Redis Authentication Type** and provide the key or Key Vault secret name.
    4. Save and test cache-dependent pages.
    Outcome to verify: Distributed cache works across app instances.

{% include media.html src="admin/scale-enable-redis-backed-caching.png" alt="Screenshot of the Scale settings tab showing enable redis-backed caching." title="Scale: Enable Redis-backed caching" capture="Capture the Scale tab while performing Enable Redis-backed caching. Show the relevant controls and redact secrets." %}

2. **Tune conversation and document caches.**
    1. Enable **conversation cache** if repeated conversation reads should be cached.
    2. Set **Cache TTL Seconds** for conversations.
    3. Review document access index read/cache switches and TTL.
    4. Save and check document list freshness.
    Outcome to verify: Cache TTLs balance latency with freshness.

{% include media.html src="admin/scale-tune-conversation-and-document-caches.png" alt="Screenshot of the Scale settings tab showing tune conversation and document caches." title="Scale: Tune conversation and document caches" capture="Capture the Scale tab while performing Tune conversation and document caches. Show the relevant controls and redact secrets." %}

3. **Configure Cosmos throughput automation.**
    1. Enable **Enable Cosmos throughput automation**.
    2. Enter subscription, resource group, account, and database.
    3. Set scale-up and scale-down thresholds, steps, cooldowns, and min/max RU guardrails.
    4. Save and refresh throughput status.
    Outcome to verify: Cosmos capacity changes only within configured guardrails.

{% include media.html src="admin/scale-configure-cosmos-throughput-automation.png" alt="Screenshot of the Scale settings tab showing configure cosmos throughput automation." title="Scale: Configure Cosmos throughput automation" capture="Capture the Scale tab while performing Configure Cosmos throughput automation. Show the relevant controls and redact secrets." %}

4. **Enable Front Door support.**
    1. Enable **Enable Front Door Support**.
    2. Set **Front Door URL** to the routed base URL.
    3. Save settings.
    4. Sign in through the Front Door URL and verify redirects.
    Outcome to verify: Home and OAuth redirect URLs use the routed domain.

{% include media.html src="admin/scale-enable-front-door-support.png" alt="Screenshot of the Scale settings tab showing enable front door support." title="Scale: Enable Front Door support" capture="Capture the Scale tab while performing Enable Front Door support. Show the relevant controls and redact secrets." %}

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Front Door redirects use the wrong host | Front Door support is off or the URL is blank. | Enable Front Door support and set the base Front Door URL. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Logging]({{ '/admin/logging/' | relative_url }})
- [Backup, Migrate & Restore]({{ '/admin/data-management/' | relative_url }})
