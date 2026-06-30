# Cosmos DB Performance Optimization and Maintenance Plan

## Header Information

**Status**: Reviewed proposal for phased implementation
**Documented against version**: **0.250.004**
**Implemented in version**: **TBD**
**Related config.py version update**: No version change is included with this proposal. Implementation should increment `VERSION` in `application/single_app/config.py` when code changes are made.
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

Use per-user versioned cache keys. Redis is preferred, but the same key model can be stored in Cosmos cache documents when Redis is unavailable:

```text
conversation_cache_version:{user_id} = 42
conversation_list:{user_id}:v42
conversation_search:{user_id}:v42:{filters_hash}
conversation_classifications:{user_id}:v42
```

When conversation state changes, increment `conversation_cache_version:{user_id}` in the shared backend. Old keys become stale immediately because reads use the latest version. Worker memory can keep a short-lived near-cache of the latest version and payload, but it must re-check the shared version before trusting local data beyond the local version-read TTL.

Example Cosmos-backed conversation cache entry:

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
    }
  },
  "summary": {
    "containers_created": 1,
    "containers_validated": 6,
    "indexing_policies_submitted": 2,
    "access_index_rows_upserted": 0,
    "access_index_rows_deleted": 0,
    "cache_versions_initialized": 4
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

#### Step 6: Backfill Document Access Index Container

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
    "enable_document_access_index_container": False,
    "enable_document_access_index_reads": False,
    "enable_document_access_index_write_through": True,
    "enable_startup_document_access_index_backfill": False
}
```

Suggested phased rollout:

1. Deploy container, maintenance jobs, cache settings, and write-through projection disabled for reads.
2. Run backfill manually or through startup maintenance.
3. Enable write-through projection.
4. Compare source list results and Document Access Index list results in shadow mode.
5. Enable Document Access Index reads for admin/test users.
6. Enable Document Access Index reads globally.

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

Exit criteria:

- Cache misses still use source queries safely.
- Cache invalidation is versioned and cross-worker safe.
- Conversation list/search RU reductions are measurable against Phase 0 baseline.

### Phase 5: Cosmos Indexing Policy Maintenance

1. Define expected indexing policies in one central module.
2. Compare current container policies to expected policies.
3. Apply non-destructive updates through maintenance jobs.
4. Record index transformation submission and current status where available.
5. Validate high-use source-container query metrics before and after policy updates.

Exit criteria:

- Indexing policy changes can be re-run safely.
- Admins can see whether policy validation or update failed.
- Source-query RU improves or remains stable while companion-container work proceeds.

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
4. Keep `enable_document_access_index_reads` disabled until shadow validation is clean.

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

1. Add or update functional tests for caches, maintenance jobs, indexing policy validation, projection write-through, backfill, reconciliation, shadow validation, and read switchover.
2. Add fix/feature documentation with the implementation version.
3. Update release notes if approved.
4. Add support runbook content for:
   - Rebuilding caches.
   - Rebuilding `document_access_index`.
   - Interpreting shadow validation diffs.
   - Temporarily disabling access-index reads.
5. Review whether source fallback can remain as a safety path or be limited to admin repair scenarios.

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