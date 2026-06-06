# App Settings Cache Versioning

Implemented in version: **0.242.020**

## Overview

App settings cache versioning improves consistency across multiple workers while keeping settings reads fast. It preserves the existing Redis-backed shared cache for Redis deployments and adds a Cosmos-backed shared version document for non-Redis deployments.

## Purpose

The app reads settings frequently across routes, background work, model calls, governance checks, and UI rendering. Without Redis, each Python worker has its own in-memory settings cache. A settings update in one worker does not automatically update another worker's process memory.

The versioning layer bounds that stale window without forcing every request to read the full settings document from Cosmos DB.

## Cache Layers

### Redis Enabled

When Redis cache is enabled:

- app settings are still written to Redis under `APP_SETTINGS_CACHE`;
- a Redis version key, `APP_SETTINGS_CACHE_VERSION`, tracks settings updates;
- each worker keeps a local in-process copy of settings;
- each worker rechecks the shared Redis version after the local version-read TTL expires;
- when the version changes, the worker refreshes its local settings cache from Redis.

### Redis Disabled

When Redis cache is disabled:

- app settings are cached in each worker process;
- the shared version document is stored in the existing `cosmos_settings_container`;
- the version document ID is `app_settings_cache_version`;
- each worker checks the shared Cosmos version at most once per `15` seconds;
- when the version changes, the worker reloads the app settings document from Cosmos.

The version document shape is:

```json
{
    "id": "app_settings_cache_version",
    "type": "cache_version",
    "version": 42,
    "updated_at": "2026-06-04T00:00:00.000000"
}
```

## Write Flow

When app settings are persisted:

1. The `app_settings` document is upserted to Cosmos DB.
2. The shared app settings cache version is bumped.
3. The current worker updates its local cache immediately.
4. Other workers observe the version change after their local version-read TTL expires.

## Staleness Window

The shared version read TTL is `15` seconds. In non-Redis deployments, workers can serve stale settings for up to roughly that window after another worker saves settings. This is intentional to avoid a Cosmos read on every settings lookup while still preventing indefinite worker-local staleness.

## Governance Separation

Governance policy cache versioning uses a separate version document in the governance policies container. App settings changes do not invalidate governance policy caches, and governance policy changes do not force workers to reload the full app settings document.

## Primary Files

- `application/single_app/app_settings_cache.py`
- `application/single_app/functions_settings.py`
- `functional_tests/test_app_settings_cache_versioning.py`

## Validation

Validation includes marker coverage for:

- Redis app settings version keys;
- Cosmos app settings version document IDs;
- `15` second shared-version read TTL;
- settings write paths that bump the shared version;
- governance cache version fallback separation.
