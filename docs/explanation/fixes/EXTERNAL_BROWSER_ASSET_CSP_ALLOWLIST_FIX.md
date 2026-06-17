# External Browser Asset CSP Allowlist Fix

Fixed/Implemented in version: **0.242.053**

## Issue Description

The external browser assets audit found that the main application Content Security Policy still allowed `https://cdn.jsdelivr.net` in `script-src` and `style-src`, even though SimpleChat browser runtime JavaScript and JavaScript companion assets are expected to be served from local static files.

## Root Cause Analysis

The OpenLayers local asset fix had already moved chat map runtime assets into SimpleChat static files and added regression coverage for local-only CSP behavior. The live CSP later drifted back to permitting jsDelivr script and style sources, leaving a public CDN execution path available to reachable application pages.

## Version Implemented

- **0.242.053**
- Application version updated in `application/single_app/config.py` to `0.242.053`.

## Files Modified

- `application/single_app/config.py`
- `functional_tests/test_chat_local_openlayers_assets.py`
- `docs/explanation/fixes/EXTERNAL_BROWSER_ASSET_CSP_ALLOWLIST_FIX.md`
- `docs/explanation/fixes/index.md`

## Code Changes Summary

- Removed `https://cdn.jsdelivr.net` from `script-src` and `style-src` in the main application CSP.
- Removed stale commented CDN allowlist examples beside the active CSP definition.
- Updated the existing local OpenLayers/CSP regression test to pin the current application version.

## Testing Approach

- Reused `functional_tests/test_chat_local_openlayers_assets.py` to validate local OpenLayers references, local-only script/style CSP fragments, and SimpleMDE CDN-prevention defaults.
- Ran the repository XSS sink checker against the changed Python file.

## Impact Analysis

- Reachable application pages no longer permit runtime JavaScript or JavaScript-required stylesheets from jsDelivr through the main CSP.
- Existing local static assets for Bootstrap, Bootstrap Icons, jQuery, DataTables, marked, DOMPurify, Chart.js, SimpleMDE, and OpenLayers remain the browser runtime sources.
- `unsafe-eval` remains unchanged because the vendored Swagger UI bundle still contains dynamic evaluation patterns and needs a separate compatibility review before tightening.

## Validation

- Before: the active CSP allowed `https://cdn.jsdelivr.net` for scripts and styles.
- After: the active CSP keeps script and style sources local-only, while authenticated API, Azure service, image, media, and websocket allowances are unchanged.