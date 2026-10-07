---
layout: page
title: "Scale settings"
description: "Scale covers Redis, the caches built on it, the document access index, Cosmos maintenance, and Cosmos DB throughput, with the health readouts and actions used to run them."
section: "Administration"
audience: admin
admin_tab: scale
---


# Scale settings

## What this group controls

Scale covers the services that keep SimpleChat fast and affordable as usage grows: Redis, the
conversation and document-list caches built on it, the document access index, background Cosmos
maintenance, and Cosmos DB throughput.

Most of the group is operational rather than configuration. Beside the settings, each card shows
live health and activity, and offers the actions an administrator uses to confirm that caching
and maintenance are working, or to change Cosmos capacity by hand.

## Why it matters

Scale settings trade latency, freshness, and Azure spend. Caches make the app faster, and
throughput automation prevents throttling, but both need guardrails. The readouts are how you
find out whether those guardrails are right: a low cache hit rate, a document access index that
keeps falling back to source queries, or a database pinned at its maximum RU/s all show up here
before users report them.

{% include media.html src="admin-settings/scale.png" alt="Screenshot of the Scale group in Admin Settings." title="Scale settings" %}

{% include media.html type="video" title="Scale settings walkthrough" poster="video-posters/admin-scale.png" capture="Recording planned. Walk through each tab in the Scale group and explain when to change each setting." %}

## Before you change anything

- Provision Redis before enabling it. Changing whether Redis is on, or how SimpleChat connects
  to it, takes effect only after every web worker and the scheduler restart together.
- Know your Cosmos RU baseline before turning on automatic scaling, so the thresholds and
  guardrails reflect real load.
- Operations that change Azure resources take effect immediately: applying indexes, deleting
  stale cache documents, resetting the index backfill, and scaling or converting throughput.
  The V2 admin page states what each one will do and asks for confirmation first. Read-only
  actions, such as refreshing status, validating access, or a cleanup dry run, run at once.

## Redis & Caching {#redis-caching}

The workspace search result cache is not configured here. It is part of Azure AI Search on the [Knowledge settings]({{ '/admin/knowledge/#azure-ai-search-section' | relative_url }}) page, and it is stored in Cosmos DB rather than Redis.

### Redis Cache {#redis-cache-section}

Redis holds sessions, the shared settings record, and the shared caches, so several app
instances behave as one. Without it each worker keeps its own state, which is fine for a single
instance and wrong for anything larger. The card lists the sections that rely on Redis, such as
Conversation Cache, Redis Metrics and File Sync, and each of those sections names Redis as a
prerequisite and links back here.

SimpleChat connects to either Azure Managed Redis or Azure Cache for Redis. The two services
listen on different TLS ports, so SimpleChat reads the host name suffix and picks the port for
you: `*.<region>.redis.azure.net` is Azure Managed Redis on port 10000, and
`*.redis.cache.windows.net` (or the Azure Government and 21Vianet equivalents) is Azure Cache
for Redis on port 6380. Set the service explicitly only when a custom DNS name or private
endpoint hides that suffix, because detection has nothing to read in that case and falls back
to Azure Cache for Redis.

Azure Cache for Redis Basic, Standard, and Premium retire on September 30, 2028. New
deployments provision Azure Managed Redis; an existing Azure Cache for Redis instance keeps
working, and moving to Azure Managed Redis is a host name change rather than a code change.

SimpleChat signs in to Redis in one of three ways. Managed identity stores no credential. An
access key is stored as a secret: the browser is never sent it, the field shows it as stored,
and it changes only when you replace it. With Key Vault authentication, the same field holds the
name of the Key Vault secret that contains the access key, and is labelled **Key Vault Secret
Name**. That mode needs Key Vault secret storage, so the card says so and links to the Key Vault
section until it is configured.

**Test Redis connection** connects with the values on screen and writes, reads and expires a
short-lived key, so a connection can be checked before it is saved. A stored key is used as
stored; the browser sends only its placeholder. A passing test also refreshes the Redis Metrics
reading, if one is on screen.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Redis Cache | Keeps sessions, settings, and shared caches in Redis so several instances share state. Recommended for production. | Off | `enable_redis_cache`; capability toggle |
| Redis Server Host Name | The Redis host. Its suffix tells SimpleChat which service and port to use. | Empty | `redis_url` |
| Redis Service | Detect from the host name, or name the service when a custom DNS name or private endpoint hides the suffix. | Detect from host name | `redis_service_type` |
| Redis Port | Overrides the port of the selected service, for a proxy or non-standard listener. Must be 1 to 65535, or blank. | Blank | `redis_port` |
| Redis Authentication Type | Access key, managed identity, or an access key read from Key Vault. | Access key | `redis_auth_type` |
| Redis Access Key / Key Vault Secret Name | The access key, or with Key Vault authentication the name of the secret holding it. Hidden for managed identity. | Empty | `redis_key`; secret |

### Admin settings consistency

Implemented in **0.261.025**. App settings no longer have a worker-local snapshot or
a 15-second version-check delay. With Redis enabled, workers read the shared settings
document on every lookup; without Redis, they read Cosmos directly. Other caches,
including conversation, user UI, and governance caches, retain their own policies.

Settings changes use Cosmos ETag checks and a shared Redis write marker. An older
writer or starting worker cannot replace the shared settings with its earlier
snapshot. The admin form also carries the revision it displayed: if another save
changed that revision, reload and review the new values before saving again.

When configured Redis is unavailable, **settings saves are rejected** rather than
silently writing only to Cosmos. Reads can fall back to Cosmos; if both services
are unavailable, the app does not serve an old worker snapshot. Cosmos fallback
reads still use the account/client's Session consistency, so this is not a promise
of global strong consistency during an outage.

A failure after the database write can leave the outcome unconfirmed. The UI asks
you to reload and verify instead of reporting success or promising a rollback.
The shared pending marker prevents readers from using the previous Redis value.
After its 30-second write lease expires, a read can repair publication using a
conditional Cosmos write. No fixed redirect delay is needed.

Deploy this change to all web workers and the scheduler together. Older versions
do not participate in the new publication protocol. Redis connection or enablement
changes require a coordinated restart of all workers; do not leave workers using
different cache backends. Do not share a Redis database between independent
SimpleChat deployments: the cache keys are application-wide.

Validation: `functional_tests/test_app_settings_store_consistency.py` covers
multi-worker reads, conditional writes, failure recovery, and expired writers.
`ui_tests/test_admin_settings_save_consistency.py` covers form revisions and includes
an optional authenticated stale-form check.

As of **0.261.026**, Redis Explorer identifies `APP_SETTINGS_STATE_V2` as the current
shared settings record. Old `APP_SETTINGS_CACHE` and `APP_SETTINGS_CACHE_VERSION`
keys are labeled legacy; their presence does not mean workers still read them.
Previews redact credentials and the Cosmos session token in ready or pending records.

In **0.261.027**, cache initialization uses the settings object supplied by the web
or scheduler startup path. The settings owner supplies database handles and logging
callbacks separately; the startup path supplies the Redis client factory. Cache
helpers no longer import `config` or rediscover configuration while initializing.
These runtime dependencies are never added to the stored settings document.
Before cache initialization, settings reads remain available through the owning
settings layer, but Redis-required writes remain blocked until its client is configured.
`functional_tests/test_app_settings_import_boundaries.py` checks cold imports,
dependency direction, and normal/optimized Python startup probes without network access.

### Redis Metrics {#redis-monitoring-section}

Redis Metrics answers whether the Redis the running application uses is healthy and has room:
configuration and health, whether the app cache and sessions are using Redis, ping latency,
memory used against `maxmemory`, fragmentation, connected and rejected clients, operations per
second, keyspace hit rate, expired and evicted keys, and how many document access index cache
markers and payloads Redis holds. Rising evictions or memory near the limit mean the cache is
too small for its load.

The metrics are read from the Redis `INFO` command when the card scrolls into view, and again
on **Refresh status**, rather than with the page. They describe the saved configuration, so the
card shows nothing to monitor until Redis is enabled and saved.

Azure Managed Redis runs the Redis Enterprise engine, which reports a different set of `INFO`
fields than open-source Redis, so some counters show "Not available" there. That is expected
and does not indicate a connection problem &mdash; check the Health badge and ping latency instead.

#### Redis Explorer

The Redis Explorer, collapsed at the bottom of the card, is a read-only browser for
troubleshooting what is actually in the cache. It pages through keys with Redis `SCAN`, using
**Next** and **Previous**, filters by a case-sensitive substring, and lists 10, 25, 50 or 100
keys at a time. `SCAN` order is defined by the server, so a filter can return a short page while
more matches remain; keep paging.

Selecting a key shows its type, TTL, memory use, and a preview. SimpleChat recognises its own
keys, such as the shared settings record and document access index scope markers, and says what
each one belongs to. Previews are sanitized and size-limited by the server, and restricted
outright for session, token, cookie, credential, password, and secret-like keys. Nothing in the
explorer writes to Redis.

### Conversation Cache {#conversation-cache-section}

The conversation cache stores each user's conversation list, feed, and advanced-search results
in Redis, keyed by user and version, so a repeat load skips the Cosmos query. A user's change
bumps their version, so they see it at once; the TTL only bounds how long an untouched entry
lives. Without Redis the cache is bypassed and every request reads Cosmos, which is why the card
names Redis as a prerequisite.

The card reports the last 15 minutes of activity as counted in the app worker that served the
page: hit rate, hits and misses, bypasses and errors, writes and invalidations, the mix of
operations, and the most recent cache event and invalidation. Application Insights remains the
fleet-wide record.

Workspace search results have a separate cache, with its own switch under Knowledge > Search
Index > Azure AI Search. See [Knowledge settings]({{ '/admin/knowledge/' | relative_url }}#azure-ai-search-section).

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable conversation cache | Caches conversation lists, feeds, and advanced-search results per user. Off bypasses cache reads and writes. | On | `enable_conversation_cache`; capability toggle; needs Redis |
| Cache TTL | How long a cached payload lives. `0` stops writing new entries. | 120 seconds | `conversation_cache_ttl_seconds`; shown while the cache is on |

## Cosmos {#cosmos}

### DAI Metrics {#document-access-index-section}

The document access index (DAI) is a projection of who can see which document. It replaces
expensive cross-partition queries, so document and tag lists in personal, group, and public
workspaces load quickly. The index container, write-through projection of document changes, the
index read path, and the startup backfill are always on: the application forces them on whenever
settings are read or saved, so the card shows them as **Always on** rather than as switches.

The index converges through the background maintenance job, which repairs records whose
projection failed and then runs bounded backfill batches while work remains. The card names
**Run background maintenance** as its prerequisite and links to Cosmos Maintenance. It reports:

- **Projection and maintenance:** the always-on components, the Redis document list cache, and
  what maintenance will do next.
- **Backfill progress:** state, repair backlog, current and completed scopes, documents
  processed and failed, rows written and deleted, and the last error.
- **Reads, last 15 minutes:** read attempts, how many the index served, source fallbacks and
  their rate, RU charge, latency, and the most recent fallback reason. A high fallback rate
  after an upgrade means the backfill has not caught up.
- **Redis list cache, last 15 minutes:** hit rate, hits and misses, bypasses and errors, and
  invalidations.

While a backfill batch is running, the card refreshes itself every few seconds.

#### Diagnostics

Diagnostics appear only while **Document Access Index diagnostics** (`enable_dai_debug`) is on,
under Operations > Logging & Health > Debug Logging. The classic page has no control for that
flag and shows the same diagnostics only while it is set. It is meant for support sessions, not
everyday operation. While it is on, the card adds shadow-validation and rolling RU metrics, the
settings below, and two actions: **Run one backfill batch**, and **Reset checkpoint**, which
restarts the backfill from the beginning and asks for confirmation first.

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable shadow validation | Compares source list results with index rows and logs mismatches, without changing what users see. | Off | `enable_document_access_index_shadow_validation` |
| Backfill Batch Size | Documents processed per manual or scheduled batch, 1 to 1,000. | 200 | `document_access_index_backfill_batch_size` |
| Repair Batch Size | Failed projection records reconciled before each backfill batch, 1 to 500. | 100 | `document_access_index_repair_batch_size` |
| Redis document list cache | Read-through Redis caching for index document, tag, and count reads. Bypassed when Redis is unavailable. | On | `enable_document_access_index_cache`; needs Redis |
| Cache TTL | 60 to 900 seconds. Scope versions make changes visible at once; the TTL clears entries nothing can reach any more. | 900 seconds | `document_access_index_cache_ttl_seconds`; shown while the list cache is on |

### Cosmos Maintenance {#cosmos-maintenance-section}

A recurring background job keeps Cosmos in the shape the application expects: it compares composite index policies against what the current code needs, reconciles the document access index by repairing fail-open projection records and running a bounded backfill batch, and clears stale operational cache documents. Newly upgraded deployments rely on it to converge, since the document access index read path falls back to slower source queries until backfill catches up.

The card shows what maintenance last found. **Indexing policies** reports the mode, how many
containers were checked, how many are missing expected composite indexes, and how many were
updated or failed. **Stale cache cleanup** reports candidates, deletions, and failures, with a
breakdown by category.

Three actions run the Cosmos tasks on demand:

- **Apply missing indexes** adds the expected composite indexes that are missing and keeps
  existing policy paths. It asks first, and Cosmos may keep transforming indexes after it
  returns, so refresh later to follow it.
- **Dry run cleanup** lists stale cache documents without deleting anything.
- **Delete stale cache docs** deletes one bounded batch of obsolete cache documents. It asks
  first.

Both switches below default to on and should stay on. Turning off the scheduler stops repair and backfill from converging at all. Turning off the startup pass only delays convergence to the next scheduled run, which is a reasonable trade when application start time matters more than picking up new index policies immediately after a deployment.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Run background maintenance | Runs the recurring job that checks Cosmos composite index policies, reconciles the document access index, and clears stale cache documents. | On | `enable_app_maintenance`; capability toggle |
| Also run maintenance at startup | Runs one maintenance pass as the application starts, so a deployment picks up new index policies without waiting for the next scheduled run. | On | `enable_startup_app_maintenance`; capability toggle |

### Cosmos DB Throughput {#cosmos-throughput-section}

Throughput automation reads recent RU utilization from Azure Monitor on every metrics window and
scales the SimpleChat database, or each container with dedicated throughput, up or down within
the guardrails you set. It prevents throttling under load without paying for peak capacity all
day. SimpleChat changes capacity only at 10,000 RU/s or lower. Above that it monitors, and
capacity changes belong in the Azure portal, where they can take four to six hours.

#### Status and manual changes

The top of the card shows the current mode, RU/s, utilization, and when they were last checked.
Until you select **Refresh**, it shows the last status saved by automation, marked as a saved
snapshot. The card also offers:

- **Validate access**, which checks the values on screen, including unsaved ones, against Azure:
  resource identity, throughput reads, container discovery, and metrics. It saves nothing, and
  what it reads stays with its result: the status above remains the saved target's, which is
  what manual changes act on.
- **Container policies**, which opens Cosmos Metrics.
- **Convert to autoscale**, **Scale up**, and **Scale down** for the database. Each opens a
  confirmation that names the target, its current RU/s, and the RU/s it will most likely land
  on, worked out the way the server works it out. Conversion is one way; converting back to
  manual is done in the Azure portal.

Manual changes use the saved policy, not unsaved edits. The card says when there are unsaved
throughput changes, so you can save first.

#### Which resource is managed

The **Saved target** readout names the Cosmos account and database that automation and manual
changes act on, and whether each value comes from the saved settings or from the App Service
settings. Leave the resource fields blank to use `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`,
the account in `AZURE_COSMOS_ENDPOINT`, and `AZURE_COSMOS_DATABASE_NAME`.

#### Rules a save must pass

Both admin interfaces enforce the same rules while automation is on. Scale Up At must be higher
than Scale Down At, and each scale interval must be at least the metrics window. The V2 page
shows a broken rule beside the value as you type, and the server refuses the save with the same
message. With automation off, nothing blocks a save; an inverted threshold pair is corrected, and
the correction is shown beside the field.

RU/s values are saved in the 1,000 RU/s increments Cosmos autoscale uses, rounding up, and never
above 10,000 RU/s. A value saved differently from how it was typed is reported beside its field.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Cosmos throughput automation | Runs the background check that scales throughput within the guardrails. | Off | `cosmos_throughput_autoscale_enabled`; capability toggle |
| Subscription ID | The subscription holding the Cosmos account. | Blank, uses `AZURE_SUBSCRIPTION_ID` | `cosmos_throughput_subscription_id` |
| Resource Group | The resource group holding the Cosmos account. | Blank, uses `AZURE_RESOURCE_GROUP` | `cosmos_throughput_resource_group` |
| Cosmos Account | The Cosmos account name. | Blank, uses the account in `AZURE_COSMOS_ENDPOINT` | `cosmos_throughput_account_name` |
| Database | The database whose throughput is managed. | `SimpleChat` | `cosmos_throughput_database_name` |
| Metrics Window | How much recent utilization each check reads, and how often automation runs. 1 to 60 minutes. | 5 minutes | `cosmos_throughput_metrics_window_minutes` |
| Auto scale up | Raises throughput when utilization crosses Scale Up At. | On | `cosmos_throughput_auto_scale_up_enabled` |
| Scale Up At | Utilization that triggers a scale up. Must be higher than Scale Down At. | 90% | `cosmos_throughput_scale_up_threshold_percent` |
| Scale Up Step | RU/s added per scale up, automatic or manual. | 1,000 RU/s | `cosmos_throughput_scale_up_step_ru` |
| Scale Up Interval | The shortest gap between scale ups. At least the metrics window. | 5 minutes | `cosmos_throughput_scale_up_cooldown_minutes` |
| Maximum RU/s | Scaling up stops here. At most 10,000 RU/s. | 10,000 RU/s | `cosmos_throughput_max_ru` |
| Ignore maximum guardrail | Scales past Maximum RU/s. The 10,000 RU/s ceiling still applies. | Off | `cosmos_throughput_ignore_max_limit` |
| Auto scale down | Lowers throughput when utilization stays under Scale Down At. | On | `cosmos_throughput_auto_scale_down_enabled` |
| Scale Down At | Utilization that allows a scale down. Must be lower than Scale Up At. | 70% | `cosmos_throughput_scale_down_threshold_percent` |
| Scale Down Step | RU/s removed per scale down, automatic or manual. | 1,000 RU/s | `cosmos_throughput_scale_down_step_ru` |
| Scale Down Interval | The shortest gap between scale downs. At least the metrics window. | 20 minutes | `cosmos_throughput_scale_down_cooldown_minutes` |
| Minimum RU/s | Scaling down stops here. | 1,000 RU/s | `cosmos_throughput_min_ru` |
| Ignore minimum guardrail | Scales below Minimum RU/s, down to the Cosmos service minimum. | Off | `cosmos_throughput_ignore_min_limit` |
| Convert manual throughput to Cosmos autoscale | Converts manual database or dedicated container throughput to native autoscale before applying the guardrails. | Off | `cosmos_throughput_convert_manual_to_autoscale_enabled` |
| Enforce global policy for all containers | Every dedicated-throughput container, including ones discovered later, uses the policy above instead of its own. | Off | `cosmos_throughput_enforce_container_defaults` |

### Cosmos Metrics {#cosmos-throughput-metrics-table-section}

Cosmos Metrics answers which container is hot. It lists every container with its RU utilization,
mode, RU/s, and request units over the metrics window, and can be filtered by name and sorted by
utilization, RU/s, request units, or policy. When Azure Monitor sends no utilization percentage
for a container, the utilization is estimated from request units against current RU/s and marked
**est.**

Selecting a container shows its details, its manual capacity actions, which confirm first like
the database ones, and its automation policy. The policy is edited in place and saved with the
page's **Save changes**, like any other setting. It starts from the values that govern the
container now, so a value it does not set shows the global value it inherits.

- **Use global values** replaces one container's policy with the global policy, and **Apply
  global policy to all** does it for every listed container. Both take effect when you save.
- A container sharing database throughput has no policy of its own; database automation covers
  it. A container above 10,000 RU/s is monitored only.
- While **Enforce global policy for all containers** is on, every container follows the global
  policy and per-container policies cannot be edited.

The policies are stored in `cosmos_throughput_container_policies`, which the server-rendered
page edits as `cosmos_throughput_container_policies_json`. The same rules apply to each container
as to the global policy. Each policy also records when automation last scaled or converted the
container, which its intervals depend on. Those times are always kept from the stored settings,
so saving a page that was loaded before a scale cannot reset a container's interval.

## Common tasks

1. **Enable Redis.** Turn on Redis Cache, enter the host name, choose how SimpleChat signs in, and
   select **Test Redis connection**. Save, then restart every web worker and the scheduler
   together. Outcome to verify: Redis Metrics shows the connection as healthy and the app cache
   as active.
2. **Keep the Redis key in Key Vault.** Configure Key Vault secret storage, choose Key Vault
   authentication, and enter the secret's name in Key Vault Secret Name. Outcome to verify: the
   connection test passes and the Redis card no longer shows a Key Vault prerequisite.
3. **Confirm an upgrade has settled.** Check that background maintenance is on, then open DAI
   Metrics. Outcome to verify: the backfill state is completed and the fallback rate is near
   zero.
4. **Guard Cosmos throughput.** Leave the resource blank to use the App Service settings, or
   fill it in, then select **Validate access**. Set thresholds, steps, intervals, and guardrails,
   turn on automation, and save. Outcome to verify: after the next metrics window, the status
   shows a fresh check time.
5. **Change capacity now.** Select **Scale up** or **Scale down** on Cosmos DB Throughput, or on a
   container in Cosmos Metrics, and review the target in the confirmation. Outcome to verify: the
   card reports the change and the refreshed RU/s.
6. **Give one container its own limits.** In Cosmos Metrics, select the container, change its
   policy, and save the page. Outcome to verify: the container's Policy reads the new range.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Redis Metrics shows nothing to monitor | Redis Cache is off, or on but not yet saved. | Enable Redis Cache, save, and restart the workers and scheduler. |
| Some Redis counters read "Not available" | Azure Managed Redis omits several `INFO` fields. | Expected. Use Health and ping latency to judge the connection. |
| The Redis test fails with Key Vault authentication | The secret name is wrong, or Key Vault secret storage is not configured. | Follow the Key Vault link on the Redis card, then check the secret name. |
| Document lists are slow after an upgrade | The document access index has not converged, so reads fall back to source queries. | Keep background maintenance on and follow the backfill in DAI Metrics. |
| A save is refused with "Scale Up At must be higher than Scale Down At." | The thresholds overlap, globally or in a container policy. | Raise Scale Up At or lower Scale Down At. The field that broke the rule is marked. |
| A save is refused because an interval is shorter than the metrics window | The metrics window was raised past a scale interval. | Lengthen the interval or shorten the window. |
| Scale up is unavailable with a message about 10,000 RU/s | The target is at or above SimpleChat's ceiling. | Change capacity in the Azure portal. |
| A container has no policy to edit | It shares database throughput, is monitored only above 10,000 RU/s, or the global policy is enforced. | Use the database policy, the Azure portal, or turn off enforcement. |
| Cosmos scaling changes too often | Thresholds or intervals are too aggressive. | Widen the gap between Scale Up At and Scale Down At, or lengthen the intervals. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Security settings]({{ '/admin/security/' | relative_url }})
- [Operations settings]({{ '/admin/operations/' | relative_url }})
- [Backup & Recovery settings]({{ '/admin/backup-recovery/' | relative_url }})
