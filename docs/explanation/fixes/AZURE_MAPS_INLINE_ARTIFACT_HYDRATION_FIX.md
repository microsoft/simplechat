# Azure Maps Inline Artifact Hydration Fix

Fixed in version: **0.241.050**

## Issue Description

Inline Azure Maps cards could fail during OpenLayers initialization even when the full map artifact existed. The browser console showed errors like `Cannot assign to read only property '0' of string '<list with 2 items>'`, and the card fell back to the generic initialization failure message instead of rendering the map.

## Root Cause Analysis

- The inline renderer in `chat-inline-maps.js` accepted compact citation payloads before artifact hydration when `function_result` already contained a shallow `render_type` and `map_payload` preview.
- Compact assistant citation payloads replace deep list and object values with placeholders such as `<list with 2 items>` and `<dict with 6 keys>`, which are not valid coordinate arrays for OpenLayers.
- The renderer did not normalize or reject those placeholder coordinate shapes before calling `ol.proj.fromLonLat(...)`.

## Version Implemented

- **0.241.050**

## Files Modified

- `application/single_app/static/js/chat/chat-inline-maps.js`
- `ui_tests/test_chat_inline_azure_maps_rendering.py`
- `functional_tests/test_azure_maps_inline_artifact_hydration_fix.py`

## Code Changes Summary

- Updated the inline Azure Maps renderer to prefer hydrated artifact payloads whenever `raw_payload_externalized` is present.
- Added coordinate, marker, area, and view normalization so compact placeholder shapes are rejected instead of being passed into OpenLayers.
- Strengthened the UI test to reproduce the compact-payload preview case while still requiring artifact hydration to succeed.
- Added a functional regression test to lock the renderer contract in environments where browser UI tests are skipped.

## Testing Approach

- Added `functional_tests/test_azure_maps_inline_artifact_hydration_fix.py`.
- Updated `ui_tests/test_chat_inline_azure_maps_rendering.py` so the compact citation preview includes invalid placeholder coordinate data and still expects artifact hydration.

## Impact Analysis

- Inline Azure Maps cards now render from the full hydrated payload instead of failing on compact preview placeholders.
- Compact externalized citations remain safe for storage while the UI still gets the full geometry needed for OpenLayers.

## Validation

- Before: compact citation previews could pass the render-type guard and crash during `fromLonLat(...)`.
- After: the renderer hydrates the full artifact first, normalizes geometry, and only initializes OpenLayers with valid coordinate arrays.