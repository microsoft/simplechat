# Semantic Search Quota Warning Fix

Fixed in version: **0.241.086**

## Issue Description

When Azure AI Search returned the monthly free Semantic Ranker quota error, workspace search could fail without a visible warning. In streaming chat, the failure path could continue with no search results and later report `augmentation_message_count: 0`, making selected-document search look like an upload or processing problem.

## Root Cause Analysis

The Azure AI Search semantic quota error was not classified separately from other search exceptions. One chat path returned a generic embedding error, while the streaming path logged the search error and continued without augmentation. The frontend workspace and admin pages had no shared service-health signal to show that Semantic Ranker quota was exhausted.

## Version Implemented

Implemented in version: **0.241.086**

## Technical Details

Files modified:

- `application/single_app/functions_service_health.py`
- `application/single_app/functions_search.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_settings.py`
- `application/single_app/templates/_semantic_search_health_warning.html`
- Workspace templates and admin templates that include the warning partial
- `application/single_app/config.py`

Code changes summary:

- Added a semantic-search service-health helper that detects free Semantic Ranker usage exhaustion.
- Persisted a sanitized `service_health.semantic_search` warning in app settings when the quota error is detected.
- Clear the warning after a later semantic search succeeds.
- Return a typed chat warning instead of a generic embedding error for non-streaming chat.
- Stop streaming chat after emitting a visible warning instead of silently continuing with no augmentation.
- Render a warning banner on personal, group, public, and managed public workspace pages, plus Admin Settings and Control Center.

## Testing Approach

- Added `functional_tests/test_semantic_search_quota_warning.py` for backend detection, chat response wiring, template inclusion, and version consistency.
- Added `ui_tests/test_semantic_search_health_warning.py` to render the warning partial with Playwright and verify settings-backed text remains escaped.

## Impact Analysis

Users now see a clear workspace search warning after the app detects exhausted free Semantic Ranker usage. Admins see the same warning with the recommended action to upgrade Semantic Ranker to Standard or wait for the monthly free quota reset. This makes the issue visible at the workspace/admin level instead of appearing as missing document augmentation.

## Validation

Before:

- Semantic quota errors could be logged but hidden from users.
- Streaming chat could proceed with zero document augmentation.
- Workspace and admin pages did not show a service-health warning.

After:

- Semantic quota exhaustion is recorded as service health.
- Chat returns or streams a user-visible warning.
- Workspace and admin pages render the warning until a successful semantic search clears it.
