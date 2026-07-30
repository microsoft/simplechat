# Redis Explorer

## Header Information

**Overview**: Redis Explorer is an admin-only troubleshooting tool in Admin Settings > Scale > Redis Monitoring. It lets administrators browse Redis keys with cursor pagination, inspect sanitized read-only value previews, and resolve Document Access Index (DAI) Redis version-marker hashes to safe SimpleChat scope metadata.

**Implemented in version**: **0.250.040**

**Latest UI refinement version**: **0.250.043**

**Related config.py version update**: `application/single_app/config.py` version **0.250.043**

**Dependencies**:

- Redis app-cache or session Redis client available at runtime.
- Admin Settings access.
- Existing Redis monitoring configuration.
- Document Access Index projection containers for DAI marker resolution.

## Technical Specifications

### Architecture

Redis Explorer extends the existing Redis monitoring surface:

- Backend helper: `functions_redis_monitoring.py`
- Admin routes: `route_backend_settings.py`
- UI modal and controls: `templates/admin_settings.html`
- Browser behavior: `static/js/admin/admin_settings.js`

The feature is read-only. It never writes, deletes, expires, or mutates Redis keys.
The modal body can scroll when the dialog contents exceed the viewport. The key list and value preview also use bounded independent scrolling so admins can browse key pages without losing the selected preview context.

DAI version-marker keys use the `DAI_LIST_CACHE_VERSION:{hash}` pattern. The hash is one-way, so Redis Explorer resolves it by re-hashing known SimpleChat scope keys from DAI projection rows, group workspaces, public workspaces, and user settings. When a match is found, the preview shows the entity type, ID, optional workspace name/status, scope key, and DAI row count. It does not expose raw settings, Redis secrets, or user-settings payloads.

### API Endpoints

- `GET /api/admin/settings/redis-explorer/keys`
  - Admin-only.
  - Uses Redis `SCAN` with a cursor, page size, and optional substring filter.
  - Returns key metadata including key name, type, TTL, memory usage when available, whether preview is restricted, and safe SimpleChat resolution metadata when available.

- `POST /api/admin/settings/redis-explorer/value`
  - Admin-only.
  - Accepts a Redis key in the JSON request body.
  - Returns sanitized metadata, safe SimpleChat resolution metadata when available, and a bounded preview.

### Security and Privacy

- Only admins can access the endpoints.
- Value previews are sanitized and bounded.
- Keys with names containing session, token, cookie, credential, password, secret, authorization, or CSRF indicators return a restricted preview message instead of content.
- JSON fields with sensitive names are redacted.
- DAI hash resolution returns only safe entity metadata and summary counts; it does not expose raw app settings, Redis secrets, or user-settings documents.
- Errors returned to the browser do not expose Redis host names, connection strings, or secret values.

## Usage Instructions

1. Open Admin Settings.
2. Go to Scale.
3. In Redis Monitoring, choose Redis Explorer.
4. Leave Key Filter blank and choose Browse All to page through Redis keys, or enter a case-sensitive key substring and choose Apply Filter.
5. Choose a page size.
6. Use Previous Page and Next Page to move through Redis `SCAN` cursor pages.
7. Select a key to view sanitized metadata, SimpleChat resolution details when available, and preview content.

Redis key names and filters are case sensitive. Keys can use uppercase names, prefixes, or internal identifiers. For example, global app settings cache entries are stored as `APP_SETTINGS_CACHE` and `APP_SETTINGS_CACHE_VERSION`, not `app_settings`.

For DAI cache keys, Redis Monitoring also shows:

- DAI payload key count.
- DAI version-marker key count.
- No-expiry DAI version-marker count.
- The current derived DAI version-marker TTL policy.

DAI version markers now receive a bounded TTL that is longer than the payload TTL. With the current 900-second DAI payload TTL, marker TTLs are refreshed to 3,600 seconds on reads, invalidations, and app-maintenance hygiene. Existing no-expiry markers are repaired through the maintenance pass instead of being deleted.

## Testing and Validation

Coverage includes:

- Redis Explorer key pagination and metadata using a fake Redis client.
- Sanitized JSON value previews.
- Restricted previews for session-like keys.
- DAI version-marker hygiene and safe hash resolution metadata.
- Admin UI static contract checks for modal controls and endpoint wiring.
- Route policy tests for new admin endpoints.

Known limitations:

- Redis `SCAN` cursors are forward-oriented; Previous uses the browser's local cursor history for the current modal session.
- Binary Redis keys or values are decoded with replacement characters for safe browser display.
- Previews are intentionally bounded and may be truncated.
