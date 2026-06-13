# User Settings Cache Optimization

Implemented in version: **0.242.044**

## Overview

User settings cache optimization reduces repeated Cosmos DB reads for user-specific UI preferences while keeping security-sensitive user settings fresh. The implementation supports both single App Service deployments without Redis and scaled-out App Service deployments with Redis.

## Purpose

SimpleChat reads user settings during shared page rendering and from frontend scripts that initialize theme, navigation, profile image, and tutorial controls. Without caching, a single page load can read the same user settings document multiple times.

This feature adds request-scoped memoization for full user settings and a lightweight UI settings cache for non-security browser chrome preferences.

## Dependencies

- Flask request context for request-scoped memoization
- Existing app cache configuration in `application/single_app/app_settings_cache.py`
- Optional Redis cache when `enable_redis_cache` is enabled
- Cosmos DB user settings container as the source of truth

## Technical Specifications

### Cache Layers

1. Request-scoped cache for full user settings documents.
2. Lightweight UI settings cache for shared page chrome fields.
3. Redis-backed UI settings cache when Redis is enabled.
4. Process-local TTL UI settings cache when Redis is disabled.

### Cached UI Fields

The lightweight UI cache includes fields such as:

- `profileImage`
- `navLayout`
- `darkModeEnabled`
- `showTutorialButtons`
- `chatLayout`
- `streamingEnabled`
- `notifications_per_page`

Security-sensitive fields such as access restrictions and file upload controls are not introduced into the lightweight UI cache contract.

### No-Redis Behavior

In a single App Service deployment without Redis, the UI settings cache is process-local with a short TTL. It does not use per-user Cosmos version documents, avoiding high-cardinality invalidation reads across multiple workers.

### Redis Behavior

In scaled-out deployments with Redis, the UI settings cache uses Redis keys shared by all workers and instances. User settings writes invalidate the lightweight UI cache so later page renders reload current values from Cosmos.

## Primary Files

- `application/single_app/app_settings_cache.py`
- `application/single_app/functions_settings.py`
- `application/single_app/app.py`
- `application/single_app/templates/base.html`
- `application/single_app/static/js/dark-mode.js`
- `application/single_app/static/js/sidebar.js`
- `functional_tests/test_user_settings_cache_optimization.py`

## Usage Instructions

No administrator action is required. The cache behavior follows the existing app Redis configuration:

- Redis disabled: request cache plus process-local UI settings TTL cache.
- Redis enabled: request cache plus Redis-backed UI settings cache.

## Testing and Validation

Functional coverage is provided by `functional_tests/test_user_settings_cache_optimization.py`.

The test validates:

- Full user settings request memoization markers.
- Redis and no-Redis UI settings cache contracts.
- Cache invalidation markers on user settings write paths.
- Frontend reuse of injected user UI settings before full API fallback.

## Known Limitations

The no-Redis process-local UI cache is intentionally short-lived and per worker. It is designed for low-risk UI preferences, not immediate cross-worker propagation of security decisions.

## Related Version Updates

Implemented in version: **0.242.044**

The application version was updated in `application/single_app/config.py` to track this feature.
