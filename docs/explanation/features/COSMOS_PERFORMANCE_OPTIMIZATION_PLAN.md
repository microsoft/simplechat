# Cosmos DB Performance Optimization and Maintenance Plan

## Header Information

**Status**: Implemented through Phase 9 hardening docs, Cosmos indexing maintenance, stale cache cleanup maintenance, and Admin Settings maintenance visibility
**Documented against version**: **0.250.039**
**Implemented in version**: **0.250.005 - 0.250.039**
**Related config.py version update**: Phase 9 hardening docs and the Admin Settings guarded index-apply action are implemented in `application/single_app/config.py` version **0.250.039**.
**Primary audience**: SimpleChat technical leadership and application developers
**Primary goal**: Reduce high-volume Azure Cosmos DB reads and repeated cross-partition queries while preserving the current application architecture and existing Azure AI Search indexing model.

## Review Summary

This plan proposes a phased Cosmos performance program rather than a single large rewrite. The lowest-risk work adds advanced cache configuration, invalidation-aware caching for low-churn data, and a reusable app maintenance job framework. The highest-impact work adds a companion `document_access_index` container that acts as a read model for document list screens. Source document containers stay authoritative; the companion container exists to align high-volume UI list queries with Cosmos partitioning.

The recommendation is to approve the full direction but implement it in phases, with feature flags and shadow validation before switching document list endpoints to the companion container.

### 2026-06-29 Technical Review Updates

The repository review confirmed the main direction and added several implementation gates that should be treated as required before user-facing read paths change:

1. **Baseline first**: Capture request charge, query metrics, index metrics, latency, result count, and source/result equivalence for the current hot paths before code changes. The Python SDK can expose `x-ms-request-charge`, query metrics, and index metrics after query iteration.
2. **Add a Phase 0 design gate**: Finalize projection row identifiers, shared-user/shared-group approval-state normalization, version-family/current-document semantics, and stale-index fallback rules before adding write-through hooks.
3. **Use continuation-token pagination where possible**: `OFFSET LIMIT` can be acceptable for shallow page-number compatibility, but deep paging should prefer SDK continuation tokens because offsets still require skipped work.
4. **Treat permission-reducing updates as security-sensitive**: Share removal, delete, retention delete, archive, and visibility changes must not leave stale `document_access_index` rows or Azure AI Search chunk visibility behind without repair tracking and safe read fallback.
5. **Keep Azure AI Search visibility synchronized**: The companion container optimizes Cosmos list screens only. It does not replace existing search-index visibility fields or source-of-truth authorization checks.
6. **Use shadow validation before reads**: Backfill plus write-through is not enough. Source-container results and `document_access_index` results must be compared by scope, sort, filter, and page before enabling reads.

### 2026-07-01 Wave 4B Implementation Update

Wave 4B adds shadow validation without switching any document list read paths. Personal, group, and public document list routes still return source-container results, then compare those authoritative current-document identities with `document_access_index` projection rows when `enable_document_access_index_shadow_validation` is enabled. The latest shadow validation result is persisted to the settings container and surfaced in Admin Settings > Scale > Cosmos Document Access Index. Read switchover remains disabled and reserved for Wave 5.

### 2026-07-01 Wave 4B.1 Shadow Metrics Update

Wave 4B.1 adds source-versus-projection query diagnostics to shadow validation. When shadow validation is enabled, document list routes capture the source query elapsed time and Cosmos request charge where the SDK provides it, then compare those values with the single-partition projection query. The admin dashboard displays source/index RU, estimated RU savings, source/index latency, and estimated latency savings. These values estimate future read-path benefits; shadow mode still runs the source query plus the projection query until Wave 5 enables controlled index reads.

### 2026-07-01 Wave 4B2 Candidate Read Metrics Update

Wave 4B2 keeps full parity validation in place but adds a separate candidate read query against `document_access_index`. The corrected candidate query is one single-partition query per scope key, returns all current rows for that scope, avoids Cosmos-side `ORDER BY`, `OFFSET`, `LIMIT`, and `TOP`, and projects only the fields needed by the document list UI plus `source_ts` for the current default sort contract. App Service remains responsible for sort/filter/page shaping until Wave 5 read switchover is deliberately implemented. Admin Settings separates **Validation Index RU** from **Candidate Read RU** and uses the candidate scope-read diagnostics for **Estimated Wave 5 Savings**. This prevents the full-scope parity query and Cosmos-side sort/page costs from overstating the expected cost of the future Wave 5 read path.

### 2026-07-01 Wave 4B3 Rolling Decision Metrics Update

Wave 4B3 keeps the latest shadow validation state in the settings container and adds a bounded rolling metric history to the same document. Admin Settings now shows 5-minute and 15-minute aggregate source-versus-candidate RU totals, estimated Wave 5 savings, validation overhead, and sample counts. These dashboard values are intended to help admins compare the current source-container document-list cost with the future access-index read path over a workflow window instead of only looking at the most recent validation call. The same aggregate structure will also help evaluate Wave 6 Redis document access caching, where a short TTL such as 15 minutes may make the access-index path beneficial for more deployments.

### 2026-07-02 Wave 5A Read-Switch Canary Update

Wave 5 is split into **5A canary** and **5B broad enablement**. Wave 5A implements `document_access_index`-backed list reads for personal, group, and public document-list routes behind `enable_document_access_index_reads`. This includes personal workspace lists, group workspace lists, internal public workspace lists, external public workspace lists, and chat document pickers that load personal, group, or visible public workspace documents. The switch stays off by default, is exposed in Admin Settings as a canary control, and only serves from the access index when the container is enabled, write-through is enabled, the relevant backfill scope is `succeeded`, and repair backlog count is zero. If the access-index query is unavailable or readiness checks fail, routes fall back to the existing source-container read path. When shadow validation remains enabled during canary testing, routes still run the source query for validation; admins should disable shadow validation when measuring the overhead-eliminated read path.

Wave 5A uses the candidate-read shape established in Wave 4B2: one single-partition query per access `scope_key`, no Cosmos-side `ORDER BY`, `OFFSET`, `LIMIT`, or `TOP`, and projection-only fields needed by the list UI. Source containers remain authoritative, and DAI rows are shaped into source-like list documents before existing sort, paging, and response enrichment run. The Wave 5A projection schema is versioned, and reads require a matching backfill state schema version so older Wave 4 projection rows cannot be served after the read path is enabled. Existing deployments now run document access repair and backfill automatically during app maintenance after upgrading; manual batches remain available for support and troubleshooting.

### 2026-07-02 Wave 5A2 Tag-List Read Optimization Update

Wave 5A2 extends the same DAI read pattern to the remaining hot tag-list endpoints: personal tags, group tags, and public workspace tags. These endpoints now attempt a DAI tag-count read first when the readiness gates pass, count projected current owner-scope `tags` rows with one single-partition query per access `scope_key`, then merge existing tag definitions and safe colors from settings/group/public workspace records. Source-backed `get_workspace_tags(...)` remains the fallback whenever backfill is not ready, repair backlog is present, or the projection query fails.

### 2026-07-03 Wave 5A2 Operations Dashboard and Auto-Maintenance Update

Wave 5A2 hardens the DAI operations posture before broad enablement. The DAI container, write-through projection, and automatic repair/backfill maintenance are now treated as always-on requirements, including for deployments with older saved settings that previously disabled them. App maintenance repairs fail-open projection records first, runs one bounded backfill batch, and uses a short active maintenance interval while repair or backfill work remains so existing deployments transparently backfill and converge after upgrade. The Admin Settings DAI card now emphasizes operational health: automatic maintenance state, next action, active loop interval, repair backlog, production DAI read attempts, DAI-served reads, source fallbacks, fallback rate, DAI read RU, DAI latency, and last fallback reason. Shadow validation metrics remain available as optional parity diagnostics, but they are no longer the primary dashboard signal for DAI read health.

### 2026-07-03 Wave 5A3 Redis Monitoring Baseline Update

Wave 5A3 adds Redis monitoring before Wave 6 introduces Redis-backed DAI document-list caching. Admin Settings > Scale now surfaces sanitized Redis runtime and capacity signals from the active Redis client: configuration state, health, app-cache and session runtime usage, monitoring source, ping latency, Redis version, connected clients, memory usage, maxmemory policy, fragmentation ratio, ops/sec, keyspace hit rate, tracked keys, expired keys, evicted keys, error replies, rejected connections, last checked time, and last error summary. The monitoring endpoint does not return Redis keys, secret names, or host names; it reports whether Redis is disabled, missing configuration, unavailable at runtime, degraded, healthy, or errored so admins can establish a baseline before document-list caching changes traffic patterns.

### 2026-07-03 Wave 5B Broad Default Read Enablement Update

Wave 5B promotes DAI-backed document and tag list reads from canary to the default read path. App settings now create and migrate `enable_document_access_index_reads` to `True`, Admin Settings displays the read path as an always-on Wave 5B default, and the settings save path preserves that required state even if an older deployment had stored the prior canary value as disabled. The existing safety gates remain unchanged: DAI rows are used only when write-through is enabled, schema-v2 backfill has succeeded for the requested source scope, repair backlog is clear, and the DAI query succeeds. Otherwise, each optimized route automatically falls back to the source document containers and records source fallback metrics for the operations dashboard. Shadow validation remains optional and should stay disabled when measuring overhead-eliminated production reads.

### 2026-07-04 Wave 6 Redis Document Access Cache Update

Wave 6 adds Redis-only read-through caching on top of DAI document, tag, and legacy-count reads. The cache never writes Cosmos cache documents and never forces source-container fallback when Redis is unavailable; Redis misses, unavailable clients, or Redis errors simply bypass cache and run the DAI query directly. The default TTL is **900 seconds** with a supported range of **60-900 seconds**. Cache keys include the operation, source scope, schema version, normalized filters/access role, and per-scope Redis version tokens. DAI projection sync, delete, repair, and backfill paths bump affected scope-version tokens for personal, group, and public access scopes so document uploads, deletes, metadata updates, share/access changes, tag changes, and projection repairs make new list reads miss old cache entries immediately. Old versioned entries naturally expire by TTL.

Admin Settings > Scale displays Redis DAI cache status and lightweight in-process cache metrics: cache enabled/TTL, 15-minute cache hit rate, hits/misses, bypasses/errors, invalidations, and last cache event. These metrics complement the Wave 5 production DAI read metrics and Wave 5A3 Redis runtime monitoring so admins can compare Redis cache hit behavior, Redis health, and DAI/source fallback rates before and after enabling broader Redis-dependent performance work.

### 2026-07-06 Wave 6 Admin Metrics UI Cleanup

DAI is now treated as an always-on production read path in the Admin Settings experience. The default Redis DAI cache TTL is **900 seconds**, relying on scope-version invalidation for immediate visibility after document, tag, share, repair, delete, and backfill changes. The Scale left navigation now links directly to **DAI Metrics**, **Cosmos Metrics**, and **Redis Metrics** so admins can jump to the relevant operational dashboard.

Support-only controls and diagnostics are hidden by default behind the app setting `enable_dai_debug`, which defaults to `false` and is not exposed in the Admin Settings UI. When that setting is edited directly in Cosmos and set to `true`, the DAI card renders manual backfill/reset controls, DAI read/cache toggles, batch-size fields, shadow validation controls, and rolling shadow-decision diagnostics for troubleshooting. Default admins see only production DAI health, maintenance, cache, fallback, RU, latency, repair, and backfill metrics.

### 2026-07-06 Phase 3 Low-Churn Cache Hardening

Phase 3 completes and hardens the existing shared low-churn cache foundation for custom pages/navigation and chat bootstrap data. Shared cache helpers now record safe hit, miss, write, delete, and version-bump counters using hashed cache-key context, and app maintenance status includes these shared cache metrics alongside cache version document status.

Custom pages cache invalidation now runs after app settings writes so feature enablement, menu configuration, and TTL changes do not depend on old cache entries expiring. Chat bootstrap cache invalidation coverage now includes group creation/deletion/status/member/role/ownership/model-endpoint changes and public workspace creation/deletion/status/member/role/ownership changes across both normal workspace routes, Control Center admin routes, and SimpleChat-native operations used by internal tools. Existing Redis-first/Cosmos-fallback shared cache behavior remains unchanged, and process memory remains a diagnostic/near-cache layer rather than the authoritative invalidation mechanism.

### 2026-07-06 Phase 4 Conversation Cache Hardening

Phase 4 completes and hardens the existing conversation list, feed, and advanced-search cache path. Conversation cache remains user-scoped and versioned, but version tokens and volatile payloads are Redis-only as of version `0.250.037`. When an app-cache Redis client is unavailable, routes bypass cache reads/writes and run the existing Cosmos source queries directly; when conversation caching is explicitly disabled, routes also bypass cache reads/writes and run the source path directly.

The default app setting `enable_conversation_cache` is `true`, with `conversation_cache_ttl_seconds` controlling cache entry lifetime. Cache keys include user id, operation, user cache version, normalized request parameters, and group-access fingerprints for collaboration-visible feed/search results. Mutation coverage includes conversation create, title update, delete, bulk delete, pin/hide changes, mark-read, metadata/summary/context updates, scope-lock changes, chat completion/title initialization, collaboration participant/message/title/member changes, and notification read/dismiss actions.

Version `0.250.034` adds DAI-style conversation cache metrics to Admin Settings > Scale. Reads, writes, disabled/TTL bypasses, and version invalidations emit lightweight in-process rolling samples over 5-minute, 15-minute, and 60-minute windows. The admin dashboard displays runtime state, 15-minute hit rate, hits/misses, bypasses/errors, writes/invalidations, operation mix, last cache event, and last invalidation without adding Cosmos reads to the conversation hot path.

Version `0.250.035` tunes the mark-read flow exposed by those metrics. Normal conversation navigation no longer forces a mark-read request when the client has no unread state, and the backend mark-read endpoint only upserts the conversation and bumps the conversation cache version when unread fields actually changed. Notification clearing remains available, but already-read conversations no longer churn the conversation feed cache simply because a user switched conversations or reloaded the page.

Version `0.250.036` preserves background chat-completion unread state after the mark-read tuning. Streaming finalization now only force-clears unread state when the completed conversation is still the active conversation, and it no longer switches the active conversation back to a completed background stream. This keeps the "chat finished while away" notification and green unread dot until the user opens that conversation.

### 2026-07-06 Settings Container RU Suppression and Stale Cleanup Planning

Version `0.250.037` removes the unexpected idle `settings` container RU pattern discovered during Phase 4 validation. Generic app settings writes no longer bump unrelated chat-bootstrap and custom-pages version documents, Cosmos throughput status refresh is read-only, no-op background autoscale checks no longer persist runtime status, volatile chat-bootstrap/conversation cache payloads do not fall back to Cosmos when Redis is unavailable, and DAI status uses short-lived in-process state caching while skipping disabled shadow-validation state reads. Post-deploy monitoring confirmed that `settings` dropped out of the top normalized RU consumers during idle monitoring.

The remaining obsolete `settings` documents should be cleaned up through app maintenance rather than by ad hoc deletion. Cleanup must be allowlisted, idempotent, dry-run capable, and limited to stale operational cache artifacts that the new code no longer uses, such as old `conversation_cache_version:*` documents and volatile `shared_cache_entry:conversation_cache:*` entries. Cleanup must not delete `app_settings`, active cache-version docs that still coordinate low-churn caches, app-maintenance state, DAI state, repair/backfill state, or any source-of-truth configuration document.

### 2026-07-06 Phase 5 Cosmos Maintenance Implementation

Version `0.250.038` implements the Phase 5 maintenance surface. Expected Cosmos indexing policies remain centralized in `functions_cosmos_indexing.py`, app maintenance can compare or apply missing composite indexes non-destructively, and Admin Settings > Scale now displays indexing status, mode, missing expected indexes, updated containers, failures, and last evaluation time.

The same maintenance surface now includes stale operational cache cleanup. Cleanup is logically separate from indexing updates, is skipped by default for background runs, and can be triggered from Admin Settings in dry-run or apply mode. Apply mode deletes only allowlisted stale cache artifacts from the settings container: retired `conversation_cache_version:*` documents, obsolete Redis-only `shared_cache_entry:conversation_cache:*` and `shared_cache_entry:chat_bootstrap:*` payloads, and expired shared cache entries. It reports candidate, deleted, skipped, failed, category, and more-candidate counts without touching app settings, active cache-version documents, DAI state, app maintenance state, source documents, or user data.

### 2026-07-06 Phase 9 Hardening and Admin Index Apply

Version `0.250.039` completes the Phase 9 runbook pass and exposes a guarded Admin Settings action for applying missing Cosmos composite indexes. Admin Settings > Scale > Cosmos Maintenance now keeps the default status view read-only, then requires an explicit confirmation modal before posting `apply_cosmos_indexing_policies=true` to the existing app-maintenance run endpoint. The modal clarifies that the update is additive and non-destructive, preserves existing indexing policy paths, can improve supported lookup and ordered-query speed, and may add write-index overhead plus asynchronous Cosmos index transformation work.

Phase 9 also documents support runbooks for rebuilding caches, rebuilding `document_access_index`, cleaning stale operational cache documents, interpreting shadow validation diffs, interpreting DAI fallback/cache metrics, and deciding whether broad source fallback should remain after DAI/cache telemetry is stable.

## Executive Summary

The current application already improved app settings and user UI settings access by introducing request-scoped caching, Redis-backed caching, Cosmos-coordinated worker-local near-caching, shared version checks, and targeted invalidation. This proposal extends that pattern to other high-utilization areas of the application:

1. Chat bootstrap data that changes infrequently but is assembled on common page loads.
2. Custom page metadata and navigation, which is very low churn and can be cached statically until invalidated.
3. Conversation list and conversation search data, which is user scoped and can be cached with version invalidation.
4. Cosmos DB indexing policy validation and application maintenance jobs, including automatic startup execution and manual admin execution.
5. A companion Document Access Index container designed specifically for document list, count, filter, and paging workloads.

The proposal intentionally keeps the existing three Azure AI Search indexes. Conversation search and document list optimization should remain inside Cosmos and Redis for now. Azure AI Search remains dedicated to the existing document search and retrieval scenarios.

The largest potential RU reduction is expected from the companion Document Access Index because the current document list endpoints query full source-of-truth document containers that are partitioned by document id. That partitioning is good for direct document lookups but expensive for list screens that ask, "show all documents visible to this user, group, or public workspace, let alone across multiple combinations of these." The companion container flips the access pattern by partitioning index rows by access scope.

## Current Performance Constraints

### Existing Containers and Access Pattern

The main document containers are currently created with `/id` as the partition key:

```python
cosmos_user_documents_container_name = "documents"
cosmos_user_documents_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_user_documents_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_group_documents_container_name = "group_documents"
cosmos_group_documents_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_group_documents_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_public_documents_container_name = "public_documents"
cosmos_public_documents_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_public_documents_container_name,
    partition_key=PartitionKey(path="/id")
)
```

This works well for direct document reads:

```python
cosmos_user_documents_container.read_item(item=document_id, partition_key=document_id)
```

It is less efficient for list screens because common list predicates are based on `user_id`, `group_id`, `public_workspace_id`, shared user arrays, shared group arrays, tags, status, classification, and current version state. Those predicates are not the partition key.

### Example Current Document List Flow

The personal document list endpoint currently:

1. Builds a dynamic filter for owner and shared-user access.
2. Runs a cross-partition query against the `documents` container.
3. Loads all matching documents into Python.
4. Collapses version families to current documents in Python.
5. Sorts in Python.
6. Applies pagination in Python.
7. Runs a second query to check legacy document counts.

That means the first page of 10 documents can still require reading many matching document records and version records before returning a small page to the client.

### Why Cosmos Indexing Alone Does Not Fully Solve This

Specialized Cosmos DB indexing policies can reduce RU and latency for filtered and sorted queries. For example, composite indexes can help this pattern:

```sql
SELECT *
FROM c
WHERE c.user_id = @user_id
ORDER BY c.last_updated DESC
```

However, if the container is partitioned by `/id`, Cosmos still needs to fan the query across logical or physical partitions because the predicate does not include the partition key. Indexing improves the work inside each partition, but it does not route the query to a single logical partition.

Cosmos indexing policy improvements are still worthwhile as a lower-risk first step, but they should be treated as an incremental optimization. The companion Document Access Index targets the root mismatch between UI list access patterns and source container partitioning.

## Goals

- Reduce repeated Cosmos reads for common page loads.
- Reduce cross-partition document list queries.
- Keep the current three Azure AI Search indexes unchanged.
- Use invalidation-first caching for low-churn data.
- Expose performance cache TTLs in an admin-only advanced configuration section.
- Provide automatic startup maintenance for existing deployments (this includes cache warm-up and version checks for the new companion container).
- Provide a manual admin maintenance button for retries and support operations.
- Keep all maintenance jobs idempotent and resumable.
- Preserve existing document source-of-truth containers and existing document APIs.
- Create and manage indexes on existing containers to optimize current queries.

## Non-Goals

- Do not add new Azure AI Search indexes for conversations or document access projections at this time.
- Do not replace the source document containers.
- Do not remove version history from source document records.
- Do not rely on in-process-only caches for any deployment. Even a single App Service instance runs multiple Gunicorn workers, and each worker has isolated memory.
- Do not run heavy migration or reindexing work synchronously during request startup.

## Proposed Architecture Overview

The proposal has five implementation areas, with Cosmos indexing policy maintenance and admin controls acting as cross-cutting support work:

1. **Cache configuration and invalidation controls**
   - Admin advanced settings for cache TTLs and cache modes.
  - Redis-backed distributed cache when Redis is enabled.
  - Cosmos-backed shared cache documents when Redis is unavailable.
  - Worker-local in-memory near-cache only as a short-lived optimization over Redis or Cosmos, never as the authoritative cache.
  - Versioned cache keys or shared version docs for safe invalidation across Gunicorn workers and App Service instances.

2. **Chat bootstrap cache**
   - Scope-specific cache for user, group, and global low-churn data.
   - Invalidation when agents, actions, prompts, groups, public workspaces, governance policies, or model endpoint configuration changes.

3. **Custom pages static cache**
   - Cache custom page catalog and navigation indefinitely.
   - Invalidate when a custom page is added, updated, deleted, or when app cache version changes.

4. **Conversation list and search cache**
  - User-scoped shared cache for conversation lists and conversation search results, using Redis first and Cosmos cache documents when Redis is unavailable.
   - Version bump on conversation CRUD or metadata updates.
   - Lazy warm on first request, optional background warm after login.

5. **Document Access Index companion container**
   - New read-model container partitioned by `scope_key`.
   - Lightweight current-document rows for owner, shared user, group, and public workspace scopes.
   - Used for list, count, filter, and paging operations.
   - Source document containers remain canonical.

## Advanced Cache Configuration in Admin UI

### Proposed Settings

Add an **Advanced Performance and Cache Configuration** section to Admin Settings. This should be visible only to admins and placed near the Redis Cache section or under a new advanced/system-performance grouping.

Proposed app settings defaults:

```python
{
    "enable_chat_bootstrap_cache": True,
    "chat_bootstrap_cache_ttl_seconds": 300,
    "enable_custom_pages_cache": True,
    "custom_pages_cache_mode": "static_until_invalidated",  # Other UI options: "ttl_based" or "disabled"
    "cache_backend_preference": "redis_then_cosmos",
    "conversation_list_cache_ttl_seconds": 300,
    "conversation_search_cache_ttl_seconds": 300,
    "notification_count_cache_ttl_seconds": 30,
    "cache_version_read_ttl_seconds": 15,
    "governance_cache_ttl_seconds": 60,
    "enable_startup_app_maintenance": True,
    "app_maintenance_check_interval_seconds": 300,
    "app_maintenance_job_lease_seconds": 3600
}
```

### Notes on TTL and Invalidation

The preferred model is invalidation-first, not TTL-first. TTLs are still useful for memory hygiene, fallback safety, and stale-entry cleanup. For data where correctness matters, a versioned cache key should be used.

Example versioned cache key pattern:

```text
conversation_cache_version:{user_id} = 42
conversation_list:{user_id}:v42
conversation_search:{user_id}:v42:{filters_hash}
```

When a conversation changes, the version is incremented. Old cache entries become unreachable even if they remain in Redis until TTL expiry.

### Advanced UI Behavior

The advanced section should include descriptive warnings:

- Lower TTLs improve freshness but reduce cache hit rates.
- Higher TTLs reduce Cosmos reads but depend on invalidation correctness.
- Static custom page caching should be safe only when backed by a shared cache/version layer because custom page changes are admin-driven and often deployment/restart-coupled.
- Redis is the preferred shared cache backend for all production deployments.
- If Redis is unavailable, use Cosmos-backed cache documents and shared version documents as the authoritative cache layer.
- Worker-local memory may be used only as a short-lived near-cache after checking shared Redis/Cosmos versions; it must never be the only invalidation mechanism.

## Chat Bootstrap Cache

### Current Behavior

The `/chats` frontend route assembles many low-churn datasets before rendering the chat page:

- User settings.
- User group list.
- Visible public workspaces.
- Personal agents.
- Group agents for each group.
- Global agents.
- Prompt catalogs.
- Model endpoint catalogs.
- Governance-filtered options.

Many of these are excellent cache candidates because they change only when an admin, owner, or workspace manager updates configuration.

### Proposed Cache Units

Cache smaller scoped fragments instead of one large page-level payload:

```text
chat_bootstrap:user:{user_id}:groups:v{version}
chat_bootstrap:user:{user_id}:visible_public_workspaces:v{version}
chat_bootstrap:user:{user_id}:personal_agents:v{version}
chat_bootstrap:user:{user_id}:personal_actions:v{version}

chat_bootstrap:group:{group_id}:agents:v{version}
chat_bootstrap:group:{group_id}:actions:v{version}
chat_bootstrap:group:{group_id}:prompts:v{version}
chat_bootstrap:group:{group_id}:model_endpoints:v{version}

chat_bootstrap:global:agents:v{version}
chat_bootstrap:global:actions:v{version}
chat_bootstrap:global:prompts:v{version}
chat_bootstrap:global:model_endpoints:v{version}
```

### Invalidation Triggers

| Scope | Trigger | Invalidation |
| --- | --- | --- |
| User | Personal agent create/update/delete | Bump `chat_bootstrap:user:{user_id}` version |
| User | Personal action create/update/delete | Bump `chat_bootstrap:user:{user_id}` version |
| User | Personal prompt create/update/delete | Bump `chat_bootstrap:user:{user_id}` version |
| User | User visible public workspace setting changes | Bump `chat_bootstrap:user:{user_id}` version |
| Group | Group membership changes | Bump group version and affected user group-list versions |
| Group | Group agent/action/prompt changes | Bump `chat_bootstrap:group:{group_id}` version |
| Group | Group model endpoints change | Bump `chat_bootstrap:group:{group_id}` version |
| Global | Global agent/action changes | Bump `chat_bootstrap:global` version |
| Global | App model endpoints change | Bump `chat_bootstrap:global` version |
| Governance | Policy changes | Bump governance version and relevant chat bootstrap versions |

### Recommended Implementation Pattern

Create a helper module such as:

```text
application/single_app/app_bootstrap_cache.py
```

Responsibilities:

- Resolve the shared cache backend through existing `app_settings_cache` patterns: Redis when enabled, otherwise Cosmos cache documents in a shared container such as `settings` or a dedicated `app_cache` container.
- Use process memory only for request or short-lived near-cache entries after validating a shared version value.
- Provide `get_or_load_chat_bootstrap_fragment(cache_key, loader)`.
- Provide version bump helpers:
  - `bump_user_bootstrap_version(user_id)`
  - `bump_group_bootstrap_version(group_id)`
  - `bump_global_bootstrap_version()`
- Provide centralized logging for cache hits, misses, invalidations, and load errors.

## Custom Pages Static Cache

### Current Behavior

Template context injection calls `get_custom_pages_nav(settings)` on rendered pages. If custom pages are enabled, this can call `list_custom_pages()`, which queries all Cosmos custom page metadata.

### Proposed Behavior

Cache both:

1. Normalized custom page catalog.
2. Computed navigation items.

Because custom pages are low churn and often require file deployment, container rebuild, or App Service restart, the recommended default is no TTL:

```text
custom_pages:catalog:v{version}
custom_pages:nav:{role_hash}:v{version}
```

Role-aware nav output should include a role hash because the catalog may be global but navigation visibility depends on user roles.

Example role hash source:

```python
roles = sorted(str(role or "").strip().lower() for role in current_user_roles)
role_hash = sha256("|".join(roles).encode("utf-8")).hexdigest()
```

### Invalidation Triggers

Invalidate custom pages cache when:

- A static custom page is created.
- A static custom page is updated.
- A static custom page is deleted.
- App cache is cleared manually by an admin.
- App service restarts.
- A maintenance job explicitly rebuilds custom page cache.

### Shared Cache Backend Requirement

In-process static cache is not safe as an authoritative cache in any deployment because Gunicorn workers do not share memory. A single App Service instance still runs multiple workers, so one worker can invalidate or refresh its local state while another worker continues serving stale data.

Custom pages should therefore use one of these authoritative shared backends:

1. Redis, when Redis cache is enabled.
2. Cosmos-backed cache documents, when Redis is unavailable.

Worker-local memory can still be used as a near-cache, but only with a short `cache_version_read_ttl_seconds` and a shared version check. The existing app settings cache already uses this general pattern by reading a Cosmos-backed version document such as `app_settings_cache_version` when Redis is not available.

Proposed shared version doc:

```text
custom_pages_cache_version = 12
```

Proposed Cosmos-backed cache docs when Redis is unavailable:

```json
{
  "id": "cache:custom_pages:catalog:v12",
  "type": "app_cache_entry",
  "cache_name": "custom_pages_catalog",
  "cache_version": 12,
  "payload": [
    {
      "slug": "request-access",
      "title": "Request Access",
      "enabled": true,
      "show_in_nav": true,
      "nav_order": 100
    }
  ],
  "created_at": "2026-06-12T15:00:00Z",
  "updated_at": "2026-06-12T15:00:00Z"
}
```

Partition key recommendation for a dedicated `app_cache` container:

```text
/cache_name
```

If the existing `settings` container is used instead, use `id` as the partition key, matching the current settings-cache version document approach.

## Conversation List and Conversation Search Cache

### Current Behavior

The conversation list endpoint queries Cosmos by user id and orders by `last_updated`. The conversations container is partitioned by `/id`, so list reads are cross-partition.

Conversation search also loads candidate conversations and runs a cross-partition message query using `CONTAINS(m.content, ...)`. The proposal does not move this to Azure AI Search. Instead, we cache results by user and query hash.

### Proposed Cache Strategy

Use per-user versioned cache keys. Redis is the runtime backend for conversation cache version tokens and volatile payloads; when Redis is unavailable, the application bypasses cache and uses source Cosmos queries:

```text
conversation_cache_version:{user_id} = 42
conversation_list:{user_id}:v42
conversation_search:{user_id}:v42:{filters_hash}
conversation_classifications:{user_id}:v42
```

When conversation state changes, increment `conversation_cache_version:{user_id}` in Redis. Old keys become stale immediately because reads use the latest version. If Redis is unavailable, no Cosmos cache-version fallback is used; cache key construction returns no key and the request falls through to the source query behavior.

Retired Cosmos-backed conversation cache entry shape cleaned up by Phase 5 maintenance:

```json
{
  "id": "cache:conversation_list:user-123:v42",
  "type": "app_cache_entry",
  "cache_name": "conversation_list:user-123",
  "user_id": "user-123",
  "cache_version": 42,
  "payload": {
    "generated_at": "2026-06-12T15:30:00Z",
    "conversations": []
  },
  "expires_at": "2026-06-12T15:35:00Z",
  "created_at": "2026-06-12T15:30:00Z"
}
```

### Lazy Warm vs Login Warm

Login warming is possible after authentication succeeds. However, login should remain fast and resilient. Recommended behavior:

1. Lazy warm the conversation list on first `/api/get_conversations` request.
2. Optionally start a background warm after login if a shared cache backend is available and the user id is available.
3. Never block login on conversation cache warmup.

### Invalidation Triggers

Invalidate by bumping the user conversation cache version after:

- Conversation create.
- Conversation title update.
- Conversation delete.
- Bulk conversation delete.
- Pin or unpin.
- Hide or unhide.
- Bulk pin or bulk hide.
- Mark read or unread state changes.
- Scope lock changes.
- Metadata updates from chat flows.
- Summary generation or summary update.
- Classification/tag/context updates.

The helper `update_conversation_with_metadata()` should also bump the version because chat workflows can update metadata outside the explicit CRUD routes.

### Example Cached Conversation List Payload

```json
{
  "user_id": "user-123",
  "cache_version": 42,
  "generated_at": "2026-06-12T15:30:00Z",
  "conversations": [
    {
      "id": "conversation-001",
      "title": "Policy review",
      "last_updated": "2026-06-12T15:12:00Z",
      "chat_type": "personal_single_user",
      "classification": ["Internal"],
      "is_pinned": true,
      "is_hidden": false,
      "has_unread_assistant_response": false,
      "last_unread_assistant_message_id": null,
      "last_unread_assistant_at": null,
      "tags": []
    }
  ]
}
```

### Conversation Search Cache Key

Normalize the search body before hashing:

```python
search_signature = {
    "search_term": normalized_search_term,
    "date_from": date_from,
    "date_to": date_to,
    "chat_types": sorted(chat_types or []),
    "classifications": sorted(classifications or []),
    "has_files": bool(has_files),
    "has_images": bool(has_images),
    "page": int(page),
    "per_page": int(per_page),
}
filters_hash = sha256(json.dumps(search_signature, sort_keys=True).encode("utf-8")).hexdigest()
```

## Cosmos DB Indexing Policy Improvements

### Why Keep This Step

Even with the companion Document Access Index, indexing policies remain valuable for:

- Existing deployments before the Document Access Index backfill completes.
- Admin-only screens that still query source containers.
- Metadata and audit queries.
- Retention policy queries.
- Migration and maintenance jobs.

### Candidate Indexing Improvements

Cosmos DB indexes should be treated as the first, lowest-risk performance improvement. They do not remove the need for the Document Access Index because they cannot change the partition key or eliminate cross-partition fanout, but they can still reduce RU consumption and latency for the current queries that remain on existing containers.

The expected tradeoff is additional index storage and slightly more write work when indexed paths change. For this application, the storage cost is expected to be minor relative to the RU savings on repeated list, filter, metadata, maintenance, and admin queries. Indexes should be applied through the maintenance job so existing deployments can be updated automatically and admins can re-run validation manually.

### Recommended Indexing Policy by Container

The table below lists the highest-value existing containers to optimize. Exact policy JSON should be generated from a central definition in code and validated against Cosmos DB SDK behavior before rollout.

| Container | Current High-Value Query Patterns | Recommended Included Paths | Recommended Composite Indexes / Sort Support | Notes |
| --- | --- | --- | --- | --- |
| `documents` | Personal workspace list, direct user shares, tags, classification, metadata filters, legacy checks | `/id/?`, `/user_id/?`, `/shared_user_ids/[]/?`, `/file_name/?`, `/title/?`, `/last_updated/?`, `/_ts/?`, `/version/?`, `/document_classification/?`, `/tags/[]/?`, `/authors/[]/?`, `/keywords/[]/?`, `/percentage_complete/?` | `user_id + last_updated DESC`, `user_id + _ts DESC`, `user_id + file_name ASC`, `user_id + title ASC`, `user_id + document_classification ASC + last_updated DESC` | Helps current personal document list while Document Access Index is rolled out. |
| `group_documents` | Group workspace list, shared group access, tags, classification, metadata filters | `/id/?`, `/group_id/?`, `/shared_group_ids/[]/?`, `/file_name/?`, `/title/?`, `/last_updated/?`, `/_ts/?`, `/version/?`, `/document_classification/?`, `/tags/[]/?`, `/authors/[]/?`, `/keywords/[]/?`, `/percentage_complete/?` | `group_id + last_updated DESC`, `group_id + _ts DESC`, `group_id + file_name ASC`, `group_id + title ASC`, `group_id + document_classification ASC + last_updated DESC` | Should reduce RU for group document list and admin/group maintenance queries. |
| `public_documents` | Public workspace list, public document count, tags, classification, metadata filters | `/id/?`, `/public_workspace_id/?`, `/file_name/?`, `/title/?`, `/last_updated/?`, `/_ts/?`, `/version/?`, `/document_classification/?`, `/tags/[]/?`, `/authors/[]/?`, `/keywords/[]/?`, `/percentage_complete/?` | `public_workspace_id + last_updated DESC`, `public_workspace_id + _ts DESC`, `public_workspace_id + file_name ASC`, `public_workspace_id + title ASC`, `public_workspace_id + document_classification ASC + last_updated DESC` | Also helps `count_public_workspace_documents()`-style queries. |
| `conversations` | Conversation list by user, pinned/hidden filters, classifications, date filters, search candidate filtering | `/id/?`, `/user_id/?`, `/last_updated/?`, `/title/?`, `/chat_type/?`, `/classification/[]/?`, `/tags/[]/?`, `/is_pinned/?`, `/is_hidden/?`, `/has_unread_assistant_response/?` | `user_id + last_updated DESC`, `user_id + is_pinned DESC + last_updated DESC`, `user_id + is_hidden ASC + last_updated DESC`, `user_id + chat_type ASC + last_updated DESC` | Complements conversation shared caching and helps cache warm/miss paths. |
| `messages` | Message retrieval by conversation, conversation search by content, thread repair/delete workflows | `/id/?`, `/conversation_id/?`, `/timestamp/?`, `/role/?`, `/parent_message_id/?`, `/metadata/thread_info/thread_id/?`, `/metadata/thread_info/previous_thread_id/?`, `/metadata/thread_info/active_thread/?` | `conversation_id + timestamp ASC`, `conversation_id + role ASC + timestamp ASC`, `conversation_id + metadata.thread_info.thread_id ASC` | Content search with `CONTAINS` is still expensive; indexes mainly help scoped message retrieval and thread operations. |
| `groups` | User group membership lookups, group search, active group validation | `/id/?`, `/name/?`, `/owner/id/?`, `/users/[]/userId/?`, `/admins/[]/?`, `/documentManagers/[]/?`, `/status/?`, `/modifiedDate/?` | `status + modifiedDate DESC`; single-field `name` sorting is covered by the included path | Array membership queries may still be expensive but benefit from indexed array paths. |
| `public_workspaces` | User public workspace membership, visible workspace hydration, workspace search/counts | `/id/?`, `/name/?`, `/description/?`, `/owner/userId/?`, `/admins/[]/?`, `/documentManagers/[]/userId/?`, `/status/?`, `/modifiedDate/?` | `status + modifiedDate DESC`; single-field `name` sorting is covered by the included path | Helps notification lookup fanout, chat bootstrap, and public workspace pages. |
| `notifications` | User notification list/count, group/public workspace notification lookup, assignment notification filtering | `/id/?`, `/user_id/?`, `/group_id/?`, `/public_workspace_id/?`, `/scope/?`, `/notification_type/?`, `/created_at/?`, `/read_by/[]/?`, `/dismissed_by/[]/?`, `/metadata/conversation_id/?`, `/assignment/roles/[]/?`, `/assignment/all_users/?` | `user_id + created_at DESC`, `group_id + created_at DESC`, `public_workspace_id + created_at DESC`, `scope + created_at DESC`, `notification_type + created_at DESC` | Pairs with notification-count caching to reduce polling cost. |
| `activity_logs` | Admin/control-center audit queries, date ranges, activity type reports, token usage reports | `/id/?`, `/user_id/?`, `/activity_type/?`, `/timestamp/?`, `/created_at/?`, `/workspace_type/?`, `/token_type/?`, `/workspace_context/group_id/?`, `/workspace_context/public_workspace_id/?` | `user_id + timestamp DESC`, `activity_type + timestamp DESC`, `workspace_type + timestamp DESC`, `token_type + timestamp DESC` | Activity logs are write-heavy; avoid indexing large nested payloads that are never filtered. |
| `prompts`, `group_prompts`, `public_prompts` | Prompt catalog/list by owner/group/public workspace and type | `/id/?`, `/user_id/?`, `/group_id/?`, `/public_id/?`, `/type/?`, `/name/?`, `/updated_at/?` | `user_id + type ASC + updated_at DESC`, `group_id + type ASC + updated_at DESC`, `public_id + type ASC + updated_at DESC` | Supports chat bootstrap prompt catalogs and prompt management pages. |
| `personal_agents`, `group_agents`, `global_agents` | Agent catalogs by scope, lookups by name/id | `/id/?`, `/user_id/?`, `/group_id/?`, `/name/?`, `/display_name/?`, `/agent_type/?`, `/modified_at/?`, `/last_updated/?` | `user_id + modified_at DESC`, `group_id + modified_at DESC`, `agent_type + modified_at DESC` | Supports chat bootstrap and admin/management lists. |
| `personal_actions`, `group_actions`, `global_actions` | Action/plugin catalogs by scope, lookups by name/id | `/id/?`, `/user_id/?`, `/group_id/?`, `/name/?`, `/displayName/?`, `/type/?`, `/modified_at/?`, `/last_updated/?` | `user_id + modified_at DESC`, `group_id + modified_at DESC`, `type + modified_at DESC` | Supports chat bootstrap and plugin management lists. |
| `custom_pages` | Custom page nav/catalog reads and admin management | `/id/?`, `/slug/?`, `/enabled/?`, `/show_in_nav/?`, `/nav_order/?`, `/nav_label/?`, `/access_level/?`, `/roles/[]/?`, `/modified_at/?` | `enabled + show_in_nav ASC + nav_order ASC`, `access_level + nav_order ASC` | Custom page caching will reduce reads, but indexes help admin/cache rebuild paths. |
| `governance_policies` | Feature governance reads and admin listing | `/id/?`, `/feature_key/?`, `/allow_all/?`, `/allowed_users/[]/?`, `/allowed_groups/[]/?`, `/updated_at/?` | No composite index required initially; single-field `feature_key` and `updated_at` sorting/filtering is covered by included paths | Governance already has process/request caching; indexes help misses and admin management. |
| `governance_item_policies` | Item policy lookups by entity type and item id | `/id/?`, `/entity_type/?`, `/item_id/?`, `/policy_id/?`, `/allow_all/?`, `/allowed_users/[]/?`, `/allowed_groups/[]/?`, `/updated_at/?` | `entity_type + item_id ASC`, `entity_type + item_id ASC + policy_id ASC` | Important for global endpoint/agent/action governance checks. |
| `search_cache` | Cache lookup, scoped invalidation, cache cleanup | `/id/?`, `/user_id/?`, `/doc_scope/?`, `/created_at/?`, `/expiry_time/?` | `user_id + created_at DESC`, `doc_scope + created_at DESC`; single-field `expiry_time` cleanup sorting is covered by the included path | If invalidation metadata is improved, add explicit scope id paths too. |
| `document_access_index` | Fast document list/count/filter by access scope | `/id/?`, `/scope_key/?`, `/scope_type/?`, `/scope_id/?`, `/access_type/?`, `/document_id/?`, `/source_container/?`, `/owner_user_id/?`, `/workspace_type/?`, `/group_id/?`, `/public_workspace_id/?`, `/current_version/?`, `/file_name/?`, `/title/?`, `/last_updated/?`, `/document_classification/?`, `/tags/[]/?`, `/status/?`, `/percentage_complete/?`, `/projection_version/?` | `scope_key + last_updated DESC`, `scope_key + file_name ASC`, `scope_key + title ASC`, `scope_key + document_classification ASC + last_updated DESC`, `scope_key + status ASC + last_updated DESC` | This is the main read model for document list performance. |

### Source Document Container Policy Example

Document source containers should have indexing support for common filters and sorts:

```json
{
  "indexingMode": "consistent",
  "automatic": true,
  "includedPaths": [
    { "path": "/id/?" },
    { "path": "/user_id/?" },
    { "path": "/group_id/?" },
    { "path": "/public_workspace_id/?" },
    { "path": "/file_name/?" },
    { "path": "/title/?" },
    { "path": "/last_updated/?" },
    { "path": "/version/?" },
    { "path": "/document_classification/?" },
    { "path": "/tags/[]/?" },
    { "path": "/shared_user_ids/[]/?" },
    { "path": "/shared_group_ids/[]/?" }
  ],
  "compositeIndexes": [
    [
      { "path": "/user_id", "order": "ascending" },
      { "path": "/last_updated", "order": "descending" }
    ],
    [
      { "path": "/group_id", "order": "ascending" },
      { "path": "/last_updated", "order": "descending" }
    ],
    [
      { "path": "/public_workspace_id", "order": "ascending" },
      { "path": "/last_updated", "order": "descending" }
    ],
    [
      { "path": "/user_id", "order": "ascending" },
      { "path": "/file_name", "order": "ascending" }
    ]
  ],
  "excludedPaths": [
    { "path": "/_etag/?" },
    { "path": "/content/?" },
    { "path": "/file_content/?" },
    { "path": "/raw_content/?" }
  ]
}
```

The exact policy should be validated against current query needs and Cosmos DB indexing limitations. Large text fields should be excluded when they are not used for Cosmos filtering or sorting.

### Expected Benefit

Indexing policies can reduce RU for existing queries, but they do not remove cross-partition fanout when the partition key is `/id` and the predicate is `user_id`, `group_id`, or `public_workspace_id`.

## Companion Document Access Index Container

### Purpose

The companion container is a read model optimized for list, count, filter, and pagination scenarios. It does not replace the source document containers.

Source document containers remain responsible for:

- Full metadata.
- Version history.
- Direct document reads.
- Enhanced citation references.
- Search index chunk metadata.
- Canonical ownership and sharing state.

The companion Document Access Index is responsible for:

- Fast document list pages.
- Fast counts by scope.
- Fast filtering by scope, tag, classification, status, owner, and current version.
- Fast pagination by `last_updated`, `file_name`, or `title`.

### Proposed Container

```python
cosmos_document_access_index_container_name = "document_access_index"
cosmos_document_access_index_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_document_access_index_container_name,
    partition_key=PartitionKey(path="/scope_key")
)
```

### Scope Key Model

Each index row belongs to exactly one access scope:

```text
user:{user_id}
group:{group_id}
public:{public_workspace_id}
```

Examples:

```text
user:730c9cfe-1234-4b7e-9b81-000000000001
group:2db0d836-1234-41ec-b60a-000000000002
public:8e0b4f7d-1234-480f-9870-000000000003
```

### Important Sharing Behavior

Direct user sharing can fan out. If one document is shared with 40 individual users, it can have 40 lightweight user-scope index rows plus the owner row.

Group and public sharing should not fan out to every member. Instead:

- A group-shared document gets one `group:{group_id}` index row.
- A public workspace document gets one `public:{workspace_id}` index row.
- A user with multiple groups can query the user scope plus the relevant group scopes.

This keeps group and public workspace access scalable while still making direct user sharing efficient for the recipient's personal list.

### Proposed Document Access Index Row Format

```json
{
  "id": "user:730c9cfe-1234-4b7e-9b81-000000000001:doc:9a82f1e4-1234-49e6-9241-000000000010",
  "scope_key": "user:730c9cfe-1234-4b7e-9b81-000000000001",
  "scope_type": "user",
  "scope_id": "730c9cfe-1234-4b7e-9b81-000000000001",
  "access_type": "owner",
  "document_id": "9a82f1e4-1234-49e6-9241-000000000010",
  "source_container": "documents",
  "owner_user_id": "730c9cfe-1234-4b7e-9b81-000000000001",
  "owner_display_name": "Avery Howard",
  "workspace_type": "personal",
  "group_id": null,
  "public_workspace_id": null,
  "current_version": 4,
  "is_current": true,
  "file_name": "budget-analysis.xlsx",
  "title": "Budget Analysis",
  "abstract": "Quarterly budget model and notes.",
  "authors": ["Finance Team"],
  "keywords": ["budget", "forecast", "finance"],
  "tags": ["finance", "fy26"],
  "document_classification": "Internal",
  "status": "Complete",
  "percentage_complete": 100,
  "file_type": ".xlsx",
  "file_size": 7340032,
  "num_file_chunks": 18,
  "has_enhanced_citations": true,
  "created_at": "2026-06-01T14:00:00Z",
  "last_updated": "2026-06-12T15:00:00Z",
  "source_document_updated_at": "2026-06-12T15:00:00Z",
  "index_updated_at": "2026-06-12T15:00:02Z",
  "projection_version": 1
}
```

### Shared User Index Row Example

```json
{
  "id": "user:99115fd2-1234-45a8-9184-000000000020:doc:9a82f1e4-1234-49e6-9241-000000000010",
  "scope_key": "user:99115fd2-1234-45a8-9184-000000000020",
  "scope_type": "user",
  "scope_id": "99115fd2-1234-45a8-9184-000000000020",
  "access_type": "shared_user",
  "share_status": "approved",
  "document_id": "9a82f1e4-1234-49e6-9241-000000000010",
  "source_container": "documents",
  "owner_user_id": "730c9cfe-1234-4b7e-9b81-000000000001",
  "workspace_type": "personal",
  "current_version": 4,
  "file_name": "budget-analysis.xlsx",
  "title": "Budget Analysis",
  "tags": ["finance", "fy26"],
  "document_classification": "Internal",
  "status": "Complete",
  "last_updated": "2026-06-12T15:00:00Z",
  "projection_version": 1
}
```

### Group Index Row Example

```json
{
  "id": "group:2db0d836-1234-41ec-b60a-000000000002:doc:9a82f1e4-1234-49e6-9241-000000000010",
  "scope_key": "group:2db0d836-1234-41ec-b60a-000000000002",
  "scope_type": "group",
  "scope_id": "2db0d836-1234-41ec-b60a-000000000002",
  "access_type": "group_workspace",
  "document_id": "9a82f1e4-1234-49e6-9241-000000000010",
  "source_container": "group_documents",
  "owner_user_id": "730c9cfe-1234-4b7e-9b81-000000000001",
  "workspace_type": "group",
  "group_id": "2db0d836-1234-41ec-b60a-000000000002",
  "current_version": 4,
  "file_name": "budget-analysis.xlsx",
  "title": "Budget Analysis",
  "tags": ["finance", "fy26"],
  "document_classification": "Internal",
  "status": "Complete",
  "last_updated": "2026-06-12T15:00:00Z",
  "projection_version": 1
}
```

### Query Examples

List a user's personal and directly shared documents:

```sql
SELECT *
FROM c
WHERE c.scope_key = @scope_key
ORDER BY c.last_updated DESC
OFFSET @offset LIMIT @limit
```

Parameters:

```json
[
  { "name": "@scope_key", "value": "user:730c9cfe-1234-4b7e-9b81-000000000001" },
  { "name": "@offset", "value": 0 },
  { "name": "@limit", "value": 20 }
]
```

Pagination implementation note:

- Prefer SDK continuation tokens for high-volume or deep paging. Continuation tokens avoid repeatedly scanning and discarding skipped results.
- If the current UI must preserve page-number semantics, use `OFFSET LIMIT` only for shallow pages and capture RU/latency separately for deeper pages.
- Keep `TOP` values as literal integers if `TOP` is used in Cosmos SQL; do not parameterize `TOP`.

Count current documents for a group:

```sql
SELECT VALUE COUNT(1)
FROM c
WHERE c.scope_key = @scope_key
```

Filter by tag and classification within one scope:

```sql
SELECT *
FROM c
WHERE c.scope_key = @scope_key
  AND ARRAY_CONTAINS(c.tags, @tag)
  AND c.document_classification = @classification
ORDER BY c.last_updated DESC
OFFSET @offset LIMIT @limit
```

### Multi-Scope Listing

For an "all accessible documents" view, the application can query multiple targeted scopes:

```text
user:{user_id}
group:{group_id_1}
group:{group_id_2}
public:{workspace_id_1}
```

Each query is single-partition. The application then merges the small page candidate sets. If this becomes complex, a second user-specific rollup can be considered later, but the first version should avoid fanout to every group member.

### CRUD Maintenance Matrix

| Source Operation | Document Access Index Action |
| --- | --- |
| Create personal document | Upsert owner index row `user:{owner_user_id}:doc:{document_id}` |
| Create group document | Upsert group index row `group:{group_id}:doc:{document_id}` |
| Create public workspace document | Upsert public index row `public:{workspace_id}:doc:{document_id}` |
| Processing status update | Update all index rows for the document with status and percentage |
| Metadata update | Update all index rows for title, tags, classification, authors, keywords, abstract, last_updated |
| Create new version | Update existing index rows to point to new `current_version` |
| Delete old non-current version | No index change unless deleting current version changes current version resolution |
| Delete document family | Delete all index rows for that `document_id` |
| Share with user | Upsert `user:{shared_user_id}:doc:{document_id}` index row |
| Approve shared user | Update `share_status` or upsert approved row |
| Unshare user | Delete `user:{shared_user_id}:doc:{document_id}` index row |
| Share with group | Upsert `group:{target_group_id}:doc:{document_id}` index row |
| Approve group share | Update `share_status` or upsert approved row |
| Unshare group | Delete `group:{target_group_id}:doc:{document_id}` index row |
| Move or promote to public | Upsert public index row and remove old rows if access changed |
| Retention policy delete | Delete related index rows as part of delete workflow |

### Finding All Index Rows for a Document

Cleanup needs to delete all Document Access Index rows for a document. There are two implementation options.

Option A, deterministic row ids from source document metadata:

- Owner row can be computed from owner id.
- Shared user rows can be computed from `shared_user_ids`.
- Shared group rows can be computed from `shared_group_ids`.
- Group/public rows can be computed from `group_id` or `public_workspace_id`.

Option B, store projection entries on the source document:

```json
{
  "document_access_index_entries": [
    {
      "scope_key": "user:730c9cfe-1234-4b7e-9b81-000000000001",
      "index_id": "user:730c9cfe-1234-4b7e-9b81-000000000001:doc:9a82f1e4-1234-49e6-9241-000000000010"
    },
    {
      "scope_key": "group:2db0d836-1234-41ec-b60a-000000000002",
      "index_id": "group:2db0d836-1234-41ec-b60a-000000000002:doc:9a82f1e4-1234-49e6-9241-000000000010"
    }
  ]
}
```

Recommendation: start with deterministic row ids and add `document_access_index_entries` only if cleanup becomes too scattered.

Recommended deterministic row id shape:

```text
{scope_key}:source:{source_container}:doc:{document_id}
```

The implementation should generate row ids from normalized projection inputs, not from display names or mutable metadata. `scope_key`, `source_container`, and `document_id` are enough for one current list row per source document per access scope. If future requirements need multiple rows per scope and document, add a stable suffix such as `:access:{access_type}`.

### Shared Access Normalization

The current source document arrays can contain simple ids and comma-suffixed approval-state values. The projection must normalize those source values before writing index rows:

```json
{
  "scope_key": "user:99115fd2-1234-45a8-9184-000000000020",
  "scope_type": "user",
  "scope_id": "99115fd2-1234-45a8-9184-000000000020",
  "access_type": "shared_user",
  "share_status": "approved"
}
```

Projection helpers should centralize parsing so list queries, cleanup, backfill, and write-through paths all interpret sharing state the same way. This also avoids carrying source-array delimiter behavior into new query code.

### Version Family Semantics

The `document_access_index` should represent listable current documents, not every historical revision:

- Only the current source document in a revision family should have active index rows.
- New version creation should update existing rows to the new current document/version metadata and ensure the old version no longer appears in list results.
- Deleting a non-current revision should not change index rows unless it changes current-version resolution.
- If deleting the current revision promotes another revision, the promotion step must update index rows in the same maintenance/write-through flow.
- Direct document open and download must continue to validate access against source-of-truth documents, not only against the index row.

### Consistency Model

The source containers remain authoritative. The Document Access Index is eventually consistent within the application write flow.

For user-facing behavior:

- Normal writes should update source and Document Access Index rows together.
- If a permission-grant projection fails, the operation may proceed only if a repair marker is recorded and the affected scope falls back to the source query until repaired.
- If a permission-reducing projection fails, such as unshare, delete, archive, or retention delete, the affected scope must be marked unsafe for index reads until repair completes.
- The admin maintenance job can rebuild the Document Access Index from source documents.
- Direct document open should still validate access against source-of-truth data if there is any doubt.
- Azure AI Search chunk visibility and sharing fields must continue to be updated by existing document workflows. The access index is a Cosmos list read model, not a replacement for search authorization metadata.

### Expected RU Reduction

The main RU reduction comes from replacing cross-partition source-container queries with single-partition Document Access Index queries.

Current list path:

```text
Query documents container across partitions by user_id/shared arrays
Load all matching records
Collapse current versions in Python
Sort in Python
Slice requested page
```

Proposed list path:

```text
Query document_access_index partition scope_key=user:{user_id}
Cosmos filters and sorts over lightweight current rows
Return requested page directly
```

Cross-partition queries generally cost more RUs because Cosmos must fan out work across partitions and merge results. Single-partition queries route directly to one logical partition and operate over a much smaller scoped working set.

## App Maintenance and Reindexing Jobs

### Purpose

Existing deployments need a safe way to adopt new containers, indexing policies, cache version docs, and future projection containers after code is deployed. The same mechanism should support manual admin repair or rebuild operations.

### Existing Pattern to Reuse

The app already starts background task threads during initialization and uses Cosmos-backed distributed locks to prevent duplicate background processing across workers.

This proposal should reuse that pattern for maintenance jobs.

### Automatic Startup Maintenance

Startup should not perform heavy work synchronously. Instead:

1. Application initialization starts background task loops.
2. A maintenance loop checks whether the current app version requires maintenance.
3. If maintenance is needed, one worker acquires a distributed lock.
4. The worker creates or updates a maintenance job record.
5. The worker runs idempotent steps in the background.

Proposed loop:

```python
def run_app_maintenance_loop():
    while True:
        try:
            check_app_maintenance_once()
        except Exception as exc:
            log_event(f"Error in app maintenance check: {exc}", level=logging.ERROR)
        time.sleep(settings.get("app_maintenance_check_interval_seconds", 300))
```

### Manual Admin Maintenance Button

Admin UI should expose a manual maintenance panel with buttons such as:

- Validate Cosmos containers.
- Apply Cosmos indexing policies.
- Rebuild app caches.
- Rebuild custom page cache.
- Rebuild conversation cache.
- Rebuild document summaries.
- Run all maintenance.

The buttons should start jobs and return immediately. The UI should poll job status.

### Proposed Job Record Format

```json
{
  "id": "maintenance_job:8fb3227f-1234-4865-b5f1-000000000100",
  "type": "app_maintenance",
  "status": "running",
  "requested_by": "startup",
  "requested_by_user_id": "system",
  "target_version": "0.242.045",
  "started_at": "2026-06-12T15:00:00Z",
  "updated_at": "2026-06-12T15:02:00Z",
  "completed_at": null,
  "lease_owner": "appservice-instance-1:1234:5678",
  "steps": {
    "ensure_cosmos_containers": {
      "status": "complete",
      "started_at": "2026-06-12T15:00:00Z",
      "completed_at": "2026-06-12T15:00:05Z",
      "processed": 3,
      "errors": []
    },
    "apply_cosmos_indexing_policies": {
      "status": "running",
      "started_at": "2026-06-12T15:00:05Z",
      "completed_at": null,
      "processed": 1,
      "errors": []
    },
    "rebuild_document_access_index": {
      "status": "pending",
      "checkpoint": {
        "source_container": "documents",
        "last_document_id": null
      },
      "processed": 0,
      "errors": []
    },
    "cleanup_stale_cache_docs": {
      "status": "pending",
      "dry_run": true,
      "candidate_count": 0,
      "deleted_count": 0,
      "skipped_count": 0,
      "checkpoint": {
        "continuation_token": null
      },
      "errors": []
    }
  },
  "summary": {
    "containers_created": 1,
    "containers_validated": 6,
    "indexing_policies_submitted": 2,
    "access_index_rows_upserted": 0,
    "access_index_rows_deleted": 0,
    "cache_versions_initialized": 4,
    "stale_cache_docs_deleted": 0,
    "stale_cache_docs_skipped": 0
  }
}
```

### Proposed Maintenance State Doc

```json
{
  "id": "app_maintenance_state",
  "type": "app_maintenance_state",
  "last_completed_version": "0.242.044",
  "last_completed_at": "2026-06-12T14:00:00Z",
  "last_job_id": "maintenance_job:8fb3227f-1234-4865-b5f1-000000000100",
  "pending_required_version": null,
  "startup_auto_maintenance_enabled": true
}
```

### Maintenance Job Steps

#### Step 1: Ensure Cosmos Containers

- Create missing companion containers.
- Validate existing container names.
- Validate expected partition keys.
- Validate TTL where applicable.

Note: Partition keys cannot be changed on existing containers. If an existing container has the wrong partition key, the job should report an actionable error and not attempt destructive changes.

#### Step 2: Apply Cosmos Indexing Policies

- Compare current indexing policy with expected policy.
- Submit policy updates where safe.
- Record which containers were updated.
- Record that Cosmos index transformation may continue asynchronously.

#### Step 3: Initialize Cache Version Docs

Create or validate shared version docs such as:

```text
app_settings_cache_version
governance_cache_version
custom_pages_cache_version
chat_bootstrap_global_cache_version
document_access_index_projection_version
```

#### Step 4: Rebuild Static Caches

- Custom page catalog.
- Custom page navigation by role hash if desired.
- Global chat bootstrap catalogs.

#### Step 5: Rebuild Conversation Cache

This should be optional because conversation cache can lazy warm. Manual rebuild may be useful after cache flushes or support events.

#### Step 6: Clean Stale Operational Cache Documents

This step removes obsolete cache artifacts from the `settings` container after the code version that stopped using them is confirmed live.

- Run in dry-run mode by default and report candidate counts by document prefix/type.
- Delete only allowlisted stale artifacts:
  - `conversation_cache_version:*`
  - `shared_cache_entry:conversation_cache:*`
  - expired volatile shared cache entries whose namespace is no longer Cosmos-backed.
- Preserve source-of-truth and active coordination docs:
  - `app_settings`
  - `app_settings_cache_version`
  - `governance_cache_version`
  - `custom_pages_cache_version`
  - `chat_bootstrap_global_cache_version`
  - `document_access_index_projection_version`
  - `app_maintenance_state`
  - DAI backfill, repair backlog, and shadow-validation state docs
  - background-task lock docs
- Process deletes in bounded batches and record deleted counts, skipped counts, last continuation token, and failures.
- Surface cleanup status and failures in Admin Settings maintenance status.

#### Step 7: Backfill Document Access Index Container

For each source document container:

1. Read documents in batches.
2. Group document versions into current document families.
3. Generate access index rows for owner/workspace/share scopes.
4. Upsert access index rows.
5. Track checkpoint.
6. Continue until complete.

The backfill must be resumable. It should be safe to run multiple times.

### Manual API Endpoints

Proposed admin endpoints:

```text
POST /api/admin/maintenance/jobs
GET  /api/admin/maintenance/jobs
GET  /api/admin/maintenance/jobs/<job_id>
POST /api/admin/maintenance/jobs/<job_id>/cancel
POST /api/admin/maintenance/run-app-maintenance
POST /api/admin/maintenance/rebuild-document-access-index
POST /api/admin/maintenance/rebuild-custom-pages-cache
POST /api/admin/maintenance/clear-app-caches
POST /api/admin/maintenance/cleanup-stale-cache-docs
```

All endpoints must use:

```python
@swagger_route(security=get_auth_security())
@login_required
@admin_required
```

### Job Safety Requirements

- Use distributed locks for startup and manual jobs.
- Prevent concurrent jobs of the same type unless explicitly allowed.
- Make each step idempotent.
- Record errors without stopping unrelated steps when safe.
- Do not block application startup or login flows.
- Do not delete source-of-truth data.
- Do not perform destructive schema changes automatically.

## Existing Deployment Upgrade Plan

### First Deploy Behavior

On first deployment of the implementation version:

1. Code starts normally.
2. Existing `create_container_if_not_exists()` declarations create any new containers if missing.
3. Background startup maintenance detects that app maintenance has not completed for this version.
4. One worker acquires the distributed lock.
5. Maintenance validates containers and initializes version docs.
6. If the Document Access Index is enabled, maintenance starts backfill.
7. Admin UI shows job progress.
8. App remains usable during maintenance.

### Feature Flags During Rollout

Recommended rollout settings:

```python
{
    "enable_document_access_index_container": True,
    "enable_document_access_index_reads": True,
    "enable_document_access_index_write_through": True,
    "enable_startup_document_access_index_backfill": True
}
```

Suggested phased rollout:

1. Deploy container, maintenance jobs, cache settings, write-through projection, automatic repair/backfill, and default DAI reads together.
2. Allow app maintenance to backfill and repair automatically; use manual batches only for support-driven retries.
3. Let DAI read attempts fall back to source containers until schema-v2 backfill is complete and repairs are clear.
4. Enable shadow validation only when parity diagnostics are needed; disable it again when measuring production read savings.
5. Monitor DAI-served reads, source fallbacks, fallback rate, RU, latency, and repair/backfill state during and after rollout.

## Functional Test Plan

Functional tests should be added under `functional_tests/` when implementation begins. Each test file must include the current version header from `config.py` at implementation time.

Recommended tests:

1. **Custom Pages Cache Test**
   - Verify first navigation load populates cache.
   - Verify second load does not query Cosmos when cache is valid.
   - Verify save/delete invalidates cache.

2. **Chat Bootstrap Cache Test**
   - Verify user/group/global cache keys are used.
   - Verify agent/action/prompt changes invalidate the right scope.
   - Verify unrelated scopes are not invalidated.

3. **Conversation Cache Test**
   - Verify `/api/get_conversations` lazy warms cache.
   - Verify create/title update/delete/pin/hide/mark-read bumps user version.
   - Verify old cache entries are not used after version bump.

4. **Maintenance Job Test**
   - Verify job creation.
   - Verify distributed lock prevents duplicate runs.
   - Verify status doc updates.
   - Verify failed step records error and job remains inspectable.
   - Verify stale cache cleanup dry-run reports candidates without deleting.
   - Verify stale cache cleanup apply mode deletes only allowlisted obsolete cache docs.
   - Verify stale cache cleanup preserves app settings, active version docs, DAI state docs, and background-task locks.

5. **Document Access Index Projection Test**
   - Verify create document writes owner index row.
   - Verify new version updates existing index row rather than creating duplicate current rows.
   - Verify share with user creates user index row.
   - Verify comma-suffixed or approval-state share values are normalized into `scope_id` and `share_status`.
   - Verify share with group creates group index row, not one row per member.
   - Verify unshare deletes corresponding index row.
   - Verify permission-reducing changes mark affected scopes unsafe for index reads if projection cleanup fails.
   - Verify document delete removes all index rows.
   - Verify source document search visibility updates continue to propagate to Azure AI Search chunks.

6. **Document Access Index Query Equivalence Test**
   - Build source-container result set and Document Access Index result set for a fixture user.
   - Verify visible document ids match.
   - Verify sorting, filtering, and pagination are equivalent.
   - Verify multi-scope merges deduplicate documents visible through more than one scope.
   - Verify stale or missing projection rows trigger source-query fallback while feature flags are not fully enabled.

7. **Version Family Projection Test**
   - Verify only the current revision appears in `document_access_index`.
   - Verify new version creation updates index metadata to the new current version.
   - Verify deleting a non-current revision leaves index rows unchanged.
   - Verify deleting or archiving a current revision updates or removes index rows safely.

## Performance Validation Plan

Before and after implementation, collect:

- RU charge for `/api/documents` list queries.
- RU charge for group document list queries.
- RU charge for public workspace document list queries.
- RU charge for `/api/get_conversations`.
- RU charge for conversation search.
- Cache hit/miss counters for chat bootstrap, custom pages, and conversation list.
- Maintenance job duration and throughput.
- Document Access Index backfill throughput.
- Query latency p50, p95, and p99 where available.
- Cosmos query metrics and index metrics for representative Python SDK queries by setting `populate_query_metrics=True` and `populate_index_metrics=True` during diagnostic runs.
- Continuation-token versus `OFFSET LIMIT` RU and latency for document list paging, especially beyond the first few pages.
- Source-query versus access-index equivalence counts and diff summaries during shadow mode.

Add structured App Insights events for:

```text
cache_hit
cache_miss
cache_invalidate
maintenance_job_started
maintenance_job_completed
maintenance_job_failed
document_access_index_projection_upserted
document_access_index_projection_deleted
document_access_index_projection_repair_needed
```

## Risk Analysis

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Stale cache after update | Users may see old agent/page/conversation data | Versioned cache keys and explicit invalidation |
| Worker-local in-memory cache divergence | One Gunicorn worker sees stale custom pages or bootstrap data while another worker has refreshed state | Never use worker-local memory as authoritative cache; use Redis or Cosmos-backed cache documents plus shared version docs |
| Maintenance job runs on multiple workers | Duplicate work or RU spikes | Cosmos distributed lock per job type |
| Heavy backfill consumes RUs | Temporary RU pressure | Batch, throttle, checkpoint, run manually when needed |
| Document Access Index projection drift | Document lists differ from source of truth | Rebuild job, shadow comparison mode, direct source authorization on open |
| Incorrect delete cleanup | Orphan index rows | Deterministic index ids, maintenance repair job, optional source `document_access_index_entries` |
| Cosmos indexing transformation takes time | Benefits not immediate | Record policy update and expose status messaging |
| Admin misconfigures TTLs | Staleness or reduced cache effectiveness | Advanced-only UI, validation, safe defaults |

## Recommended Implementation Phases

### Phase 0: Baseline Metrics and Design Lock

This phase should happen before code behavior changes.

1. Capture current RU charge, query metrics, index metrics, latency, result count, and payload size for:
   - Personal document lists.
   - Group document lists.
   - Public workspace document lists.
   - Conversation list and conversation search.
   - Custom page navigation injection.
   - Chat bootstrap loaders.
2. Finalize `document_access_index` projection rules:
   - Deterministic row id format.
   - Shared user/group parsing and approval-state normalization.
   - Current-version and revision-family semantics.
   - Permission-reducing failure behavior.
   - Source-query fallback criteria.
3. Build representative fixtures for owner, shared user, shared group, public workspace, multi-version, archived, deleted, and overlapping multi-scope visibility.

Exit criteria:

- Baseline metrics are recorded.
- Projection rules are documented.
- Functional test fixture expectations are agreed.

### Phase 1: Maintenance Framework and Admin Controls

1. Reuse `background_tasks.py` distributed lock patterns for app maintenance jobs.
2. Store low-volume job state in the existing settings container, using `type` fields and stable ids.
3. Add a dedicated maintenance job/log container only if job history or logs become high-volume.
4. Add startup maintenance loop with:
   - Idempotent step execution.
   - Checkpoints.
   - Lease protection.
   - Safe no-op behavior when disabled.
5. Add admin-only manual maintenance endpoints and UI controls:
   - Job status.
   - Run selected job.
   - Cancel or mark job cancelled where safe.
   - Clear/rebuild caches.
   - Validate containers and indexing policies.
6. Add route-policy and admin functional tests for new endpoints.

Exit criteria:

- Jobs can be started manually and by startup loop without duplicate execution across workers.
- Job state is visible to admins.
- Failed steps are inspectable and resumable.

### Phase 2: Shared Cache Foundation

1. Extract or extend existing app settings/governance/search cache patterns into shared helpers for:
   - Redis-first cache access.
   - Cosmos-backed cache documents when Redis is unavailable.
   - Versioned cache keys.
   - Short-lived worker-local near-cache after shared version checks.
   - Cache hit/miss/invalidation telemetry.
2. Add advanced admin settings for cache enablement, TTLs, version-read TTL, and backend preference.
3. Add manual cache clear and version bump helpers.

Exit criteria:

- New cache consumers can use one common versioned cache contract.
- Worker-local memory is never the authoritative invalidation layer.

### Phase 3: Low-Churn Cache Wins

Implemented in version: **0.250.032**

Implement the safest cache wins before higher-risk read-model changes.

1. Custom pages cache:
   - Cache catalog and role-aware navigation.
   - Invalidate on custom page create/update/delete and manual cache clear.
   - Rebuild via maintenance job.
2. Chat bootstrap cache:
   - Cache scoped fragments for user, group, and global bootstrap data.
   - Add invalidation hooks for agents, actions, prompts, groups, public workspaces, governance policy changes, and model endpoint changes.
3. Add functional tests and App Insights events for cache hits, misses, and invalidations.

Exit criteria:

- Repeated page loads avoid repeated Cosmos reads for unchanged low-churn data.
- All write paths that change cached data bump the correct shared version.

### Phase 4: Conversation List and Search Cache

Implemented in version: **0.250.033**; metrics dashboard updated in **0.250.034**; mark-read invalidation tuned in **0.250.035**; background unread-state preservation updated in **0.250.036**

1. Add user-scoped conversation cache version docs or Redis version keys.
2. Add lazy warm for `/api/get_conversations`.
3. Cache normalized conversation search result signatures with query/filter hashes.
4. Invalidate on:
   - Create.
   - Rename/title update.
   - Delete or bulk delete.
   - Pin/unpin.
   - Hide/unhide.
   - Mark read/unread.
   - Scope lock changes.
   - Metadata, summary, classification, tag, or context updates.
5. Add manual rebuild/clear controls.
6. Add operational dashboard metrics for runtime status, hit rate, hits/misses, bypasses/errors, writes/invalidations, operation mix, and last invalidation.
7. Keep mark-read invalidation idempotent so normal navigation does not invalidate the feed cache when no unread state changed.

Exit criteria:

- Cache misses still use source queries safely.
- Cache invalidation is versioned and cross-worker safe.
- Conversation list/search RU reductions are measurable against Phase 0 baseline.

### Phase 5: Cosmos Indexing Policy Maintenance

Implemented in version: **0.250.038**; guarded admin apply action added in **0.250.039**

1. Define expected indexing policies in one central module.
2. Compare current container policies to expected policies.
3. Apply non-destructive updates through maintenance jobs.
4. Record index transformation submission and current status where available.
5. Validate high-use source-container query metrics before and after policy updates.
6. Surface indexing-policy comparison, transformation progress, skipped containers, and failures in Admin Settings maintenance status.
7. Include the stale operational cache-document cleanup task in the same maintenance framework, but keep it logically separate from indexing-policy updates so a cleanup failure cannot block policy validation.

Exit criteria:

- Indexing policy changes can be re-run safely.
- Admins can see whether policy validation or update failed.
- Admins can explicitly apply missing composite indexes from the UI after acknowledging write-index overhead and asynchronous transformation behavior.
- Source-query RU improves or remains stable while companion-container work proceeds.
- Stale cache cleanup can run in dry-run and apply modes, reports exact candidate/deleted/skipped counts, and never deletes source-of-truth or active coordination documents.

### Phase 6: Document Access Index Container and Write-Through

1. Add `document_access_index` container partitioned by `/scope_key`.
2. Add feature flags:
   - `enable_document_access_index_container`.
   - `enable_document_access_index_write_through`.
   - `enable_document_access_index_reads`.
   - `enable_document_access_index_shadow_validation`.
   - `enable_startup_document_access_index_backfill`.
3. Add projection builder helpers that normalize source documents into deterministic rows.
4. Add write-through hooks in source document workflows:
   - Create.
   - Metadata update.
   - Processing status update.
   - Share/unshare.
   - Share approval/denial.
   - New version/current-version changes.
   - Archive/unarchive.
   - Delete and retention delete.
5. Keep Azure AI Search visibility updates in the same source workflows.

Exit criteria:

- New writes produce expected projection rows while reads remain on source paths.
- Projection failure creates repair/fallback state instead of silent drift.

### Phase 7: Backfill, Reconciliation, and Shadow Validation

1. Add resumable, throttled backfill job with checkpoints per source container.
2. Add reconciliation job that detects:
   - Missing rows.
   - Orphan rows.
   - Incorrect current-version rows.
   - Incorrect sharing status rows.
   - Unsafe scopes requiring source fallback.
3. Add shadow validation for document list endpoints:
   - Query source path and access-index path.
   - Compare ids, sort order, filter behavior, pagination, counts, and deduplication.
   - Log diff summaries and RU deltas.
4. Keep source fallback active until shadow validation is clean and DAI maintenance is healthy.

Exit criteria:

- Backfill has completed or reached an accepted scope.
- Shadow validation shows equivalent results for representative users, groups, public workspaces, and edge-case fixtures.
- Repair jobs can fix detected drift.

### Phase 8: Controlled Read Switchover

1. Add read wrapper that chooses source query or access-index query based on feature flags, scope safety, and shadow validation state.
2. Enable access-index reads in this order:
   - Admin/test users.
   - Small internal cohort.
   - Personal document list.
   - Group document list.
   - Public workspace document list.
   - Global rollout.
3. Keep direct document open/download authorization against source-of-truth data.
4. Monitor RU, latency, error rate, stale fallback count, repair count, and user-reported discrepancies.

Exit criteria:

- Document list RU and latency improve against baseline.
- No unresolved projection drift or authorization regressions are observed.
- Source fallback remains available until confidence is high enough to remove or narrow it.

### Phase 9: Hardening, Documentation, and Release Readiness

Implemented in version: **0.250.039**

1. Add or update functional tests for caches, maintenance jobs, indexing policy validation, projection write-through, backfill, reconciliation, shadow validation, and read switchover.
2. Add fix/feature documentation with the implementation version.
3. Update release notes if approved.
4. Add support runbook content for:
   - Rebuilding caches.
   - Rebuilding `document_access_index`.
   - Cleaning stale operational cache documents from `settings`.
   - Interpreting shadow validation diffs.
   - Interpreting DAI source fallback metrics while repair/backfill catches up.
   - Interpreting DAI Redis cache metrics and Redis-unavailable bypass behavior.
5. Review whether source fallback can remain as a broad safety path or should be limited to admin repair scenarios after DAI, Redis cache, and maintenance telemetry are stable.
6. Complete final docs and release readiness checks, including maintenance runbooks, support-safe cleanup guidance, and validation queries for idle RU baselines.

#### Phase 9 Support Runbook

Use Admin Settings > Scale as the first operational surface. The dashboard is intentionally split into DAI Metrics, Cosmos Maintenance, Cosmos Metrics, Redis Metrics, and Conversation Cache so support can isolate the subsystem before changing settings.

##### Rebuilding low-churn and conversation caches

1. Confirm Redis health in Redis Metrics. If Redis is unavailable, Redis-only cache paths bypass cache and use the safe source or DAI query path rather than writing volatile cache payloads to Cosmos.
2. For custom pages/navigation and chat bootstrap cache issues, make the source-of-truth change again or save the relevant app/custom-page/workspace setting to bump the low-churn cache version.
3. For conversation list/feed/search cache issues, use the normal user-visible mutation path that changes the affected conversation, such as title update, pin/hide, delete, mark-read when unread state actually changed, or metadata update. These paths bump Redis-only conversation version tokens.
4. Do not recreate retired `conversation_cache_version:*` or volatile shared-cache payload documents in `settings`. If old documents remain, use the stale cleanup dry run and apply action instead.

##### Rebuilding `document_access_index`

1. Check Cosmos Document Access Index status in Admin Settings > Scale.
2. Confirm DAI container, write-through, automatic maintenance, repair backlog, backfill state, and last error.
3. If DAI debug mode is enabled through the hidden `enable_dai_debug` setting, run one manual backfill batch or reset the checkpoint only when support needs to reprocess all source scopes.
4. Leave production source fallback enabled while repair or backfill is incomplete. Routes only serve DAI rows when readiness gates pass and the projection query succeeds.
5. After repair backlog clears and backfill state is succeeded for the relevant scopes, compare 15-minute DAI served reads, fallback count, fallback rate, DAI RU, and DAI latency.

##### Applying expected Cosmos composite indexes

1. Open Cosmos Maintenance and refresh status.
2. Review Missing Expected Indexes, Indexing Failures, and Last Indexing Evaluation.
3. Choose **Apply Missing Indexes** only when the team accepts the tradeoff: additional composite indexes improve supported lookup/ordered-query patterns but add write-index maintenance overhead and may start asynchronous index transformation.
4. Confirm the modal. This posts an apply-mode app-maintenance run. It only appends missing expected composite indexes and preserves current included paths, excluded paths, default indexes, TTL, conflict-resolution, analytical-storage TTL, and full-text policy settings.
5. Refresh status later to monitor updated container count, failures, and `indexTransformationProgress` where Cosmos returns it.

##### Cleaning stale operational cache documents

1. Run **Dry Run Cleanup** first.
2. Review candidate count, categories, failed count, and whether more candidates remain.
3. Use **Delete Stale Cache Docs** only after dry-run counts look reasonable.
4. Apply mode deletes one bounded batch of allowlisted operational artifacts only: retired conversation cache versions, obsolete Redis-only conversation/chat-bootstrap shared-cache payloads, and expired shared-cache entries.
5. Repeat dry-run/apply if `More Candidates` remains `Yes`.

##### Interpreting shadow validation diffs

Shadow validation is a diagnostic, not the normal production read path. If enabled for troubleshooting:

- `missing_count` means source documents expected by the current source path were not found in DAI projection rows.
- `extra_count` means DAI returned rows that the source path did not return.
- Source/index RU and latency compare the cost of the current source query and the validation/candidate DAI query.
- Rolling 5-minute and 15-minute samples are useful for workflow-level comparison but should not be mixed with Redis cache hit-rate conclusions.
- Disable shadow validation before measuring production DAI/cache RU because shadow mode intentionally adds validation work.

##### Interpreting DAI fallback and Redis cache metrics

- `DAI Read Attempts` counts optimized read attempts.
- `DAI Served Reads` means the access index satisfied the read.
- `Source Fallbacks` and `Fallback Rate` show how often routes used the source containers because readiness, repair, backfill, cache safety, or query execution did not allow DAI service.
- `Last Fallback Reason` is the fastest way to decide whether to wait for backfill/repair, investigate projection errors, or inspect Redis/cache safety.
- Redis DAI cache misses and bypasses are not failures by themselves. A Redis miss should run the DAI query; Redis unavailable bypass should not write volatile cache documents to Cosmos.
- A healthy deployment should trend toward low source fallback once backfill and repair converge. A high fallback rate with clear repair backlog is expected during rollout; a high fallback rate after convergence needs investigation.

##### Source fallback readiness decision

Keep broad source fallback while any of the following are true:

- DAI repair backlog is non-zero or unknown.
- Backfill is incomplete for active source scopes.
- Shadow validation is reporting unresolved missing or extra rows.
- Production fallback reasons show projection, readiness, Redis invalidation, or query errors.
- Support has not yet validated idle RU, 15-minute DAI served reads, cache hit rate, and direct source authorization behavior after the latest deployment.

Consider narrowing fallback only after DAI readiness remains stable across representative personal, group, public, and chat document-picker workflows; Redis cache bypass behavior is understood; and support has a tested rebuild path for projection drift.

## Open Decisions

1. Should maintenance jobs use a new `maintenance_jobs` container or store job docs in the existing `settings` container?
  - Recommended: start with low-volume job state in the existing `settings` container to reuse current lock/version patterns.
  - Add a dedicated `maintenance_jobs` or `maintenance_job_logs` container only if detailed job history becomes high-volume or needs independent retention.

2. Should Document Access Index projection be enabled for writes before reads?
   - Recommended: yes. This allows backfill and shadow validation before user-facing read switch.

3. Should direct user sharing fan out immediately or be lazily materialized on first recipient list read?
   - Recommended: fan out immediately for direct user shares because direct shares are usually smaller than group membership.

4. Should group/public multi-scope document lists merge in application code or use a user-specific rollup?
   - Recommended: start with targeted per-scope queries and application merge. Add user rollup only if needed.

5. Should custom pages cache use Redis by default when Redis is enabled?
  - Recommended: yes. When Redis is unavailable, use Cosmos-backed cache documents. Worker-local memory may only act as a short-lived near-cache after checking a shared version value.

6. Should document list paging use continuation tokens or page-number offsets?
  - Recommended: use continuation tokens for high-volume list APIs and keep page-number offsets only where the current UI requires shallow random access.

7. Should permission-reducing projection failures fail the source write?
  - Recommended: avoid silent success. Either complete the source, search visibility, and projection updates together, or mark the affected scope unsafe for access-index reads and enqueue repair before returning success.

8. Should the Document Access Index replace source authorization checks?
  - Recommended: no. It is a list read model only. Direct open/download and sensitive operations must validate against source documents.

## Approval Request

Approval is requested to proceed with a phased implementation of:

1. Advanced cache configuration in Admin Settings.
2. Automatic and manual app maintenance/reindexing jobs.
3. Static invalidation-based custom page caching.
4. Scope-aware chat bootstrap caching.
5. Versioned conversation list and conversation search caching.
6. Cosmos indexing policy validation and update workflow.
7. Companion `document_access_index` container for fast document list, count, filter, and pagination workloads.

The companion container is the largest change, but it directly addresses the biggest Cosmos RU issue identified in document listing: list queries are currently shaped by user/group/workspace access patterns while the source containers are partitioned by document id. The companion container aligns partitioning with the UI read pattern while preserving the existing source-of-truth document containers.
