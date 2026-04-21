# Azure Maps Tile Proxy Token Refresh Fix

Fixed in version: **0.241.063**

## Issue Description

Older chat messages that contained inline Azure Maps visualizations could stop loading map tiles after the stored proxy token expired. The browser then showed repeated `400` responses from `/api/azure-maps/tile`, while the backend logged `Rejected an expired Azure Maps tile proxy token.`

## Root Cause Analysis

- The Azure Maps visualization plugin stores a secure proxy tile URL template inside the citation payload.
- That URL template contains an encrypted proxy token with a limited lifetime.
- When an older message was reopened after the token expired, the app could still return the original stored tile URL template instead of reissuing a fresh proxy token.
- Some older assistant messages also persisted a legacy `{{map:...}}` content block that embedded the original tile URL template directly in message text.
- The Azure Maps subscription key itself was still valid; only the stored proxy token had aged out.

## Version Implemented

- **0.241.063**

## Files Modified

- `application/single_app/functions_azure_maps.py`
- `application/single_app/functions_message_artifacts.py`
- `application/single_app/route_frontend_conversations.py`
- `functional_tests/test_azure_maps_tile_token_refresh_fix.py`

## Code Changes Summary

- Added helper functions to refresh Azure Maps tile proxy tokens and rebuild tile URL templates from stored encrypted payloads.
- Updated artifact hydration so Azure Maps citations get a freshly issued tile URL template before they are returned to the client.
- Updated the agent citation artifact endpoint to refresh Azure Maps citation payloads before serializing the response.
- Updated conversation message loading so assistant citations are hydrated from artifacts before the chat UI renders them.
- Updated conversation message loading to refresh all Azure Maps citations in the returned message payload, even when the client falls back to the compact citation.
- Updated conversation message loading to refresh embedded legacy `{{map:...}}` content blocks before serializing assistant messages.
- Updated the inline Azure Maps renderer to prefer artifact-backed payloads whenever an artifact id is available for the citation.
- Updated AI message rendering to strip legacy `{{map:...}}` blocks from visible markdown so the raw payload no longer appears in chat text.
- Disabled browser caching on conversation-message and agent-citation artifact responses so stale expired tile URLs are not reused from cache.
- Updated the chat message and artifact fetches to request `no-store` responses and append a cache-busting timestamp.
- Added a regression test that verifies expired stored tile URLs are reissued automatically during hydration.

## Testing Approach

- Added `functional_tests/test_azure_maps_tile_token_refresh_fix.py`.
- Validated direct tile URL template refresh, artifact-hydration refresh, inline message-content refresh, the conversation-load contract, and the no-store fetch contract using an intentionally expired stored proxy token.

## Impact Analysis

- Existing chat messages with inline Azure Maps visualizations now recover automatically without requiring a new Azure Maps subscription key.
- The browser receives a fresh proxy tile URL template when the visualization is loaded, so the map tiles render again instead of returning `400` errors.
- The conversation history endpoint now refreshes agent citation payloads before the UI renders them, which closes the path that could still reuse compact stale map payloads after a server restart.
- Older assistant messages that still contain legacy `{{map:...}}` blocks now have their embedded tile URLs refreshed server-side, and the raw block is hidden from rendered chat text.
- Browser caching is now bypassed for the conversation JSON and agent-citation artifact JSON, which prevents the page from reusing an old expired `tile_url_template` after a normal reload.

## Validation

- Before: reopening older Azure Maps messages reused an expired tile token and tile requests failed with `400`.
- After: stored Azure Maps citation payloads are refreshed server-side before the client renders the map, so tile requests use a valid proxy token.