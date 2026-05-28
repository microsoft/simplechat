# Local Chat OpenLayers Assets Fix

Fixed/Implemented in version: **0.241.116**

## Issue Description

Customers in privacy-restricted browsers could see chat stay on the plain `Streaming...` placeholder while the browser console reported tracking-prevention warnings for `https://cdn.jsdelivr.net/npm/ol@10.6.1/...`. The chat page was loading OpenLayers CSS and JavaScript from jsDelivr even though SimpleChat expects runtime assets to be served locally.

## Root Cause Analysis

- The chat template referenced OpenLayers from jsDelivr for inline Azure Maps visualizations.
- The Content Security Policy still allowed jsDelivr for script and style sources.
- The admin landing-page SimpleMDE editor disabled FontAwesome auto-download but left spell checking at the default, which can request CDN-hosted dictionary files.

## Version Implemented

- **0.241.116**
- Application version updated in `application/single_app/config.py` to `0.241.116`.

## Files Modified

- `application/single_app/templates/chats.html`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/templates/base.html`
- `application/single_app/templates/workspace.html`
- `application/single_app/templates/group_workspaces.html`
- `application/single_app/templates/my_feedback.html`
- `application/single_app/templates/my_safety_violations.html`
- `application/single_app/config.py`
- `application/single_app/static/js/openlayers/ol.js`
- `application/single_app/static/js/openlayers/ol.js.map`
- `application/single_app/static/css/openlayers/ol.css`
- `application/single_app/static/js/simplemde/simplemde.js`
- `application/single_app/static/js/simplemde/simplemde.min.js`
- `ui_tests/test_chat_inline_azure_maps_rendering.py`
- `functional_tests/test_chat_local_openlayers_assets.py`

## Code Changes Summary

- Vendored OpenLayers 10.6.1 JavaScript, source map, and CSS under SimpleChat static assets.
- Updated the chat template to load OpenLayers from `url_for('static', ...)` instead of jsDelivr.
- Removed jsDelivr from `script-src` and `style-src` in the application Content Security Policy.
- Disabled SimpleMDE spell checking for the admin landing-page editor so it does not request CDN dictionary files.
- Hardened local SimpleMDE defaults so FontAwesome auto-download stays disabled and spell checking only initializes when explicitly enabled.
- Removed obsolete CDN examples from shared template comments to avoid misleading scans.
- Added regression coverage for local OpenLayers asset references and CSP behavior.

## Testing Approach

- Added `functional_tests/test_chat_local_openlayers_assets.py` to statically validate the local asset contract.
- Updated `ui_tests/test_chat_inline_azure_maps_rendering.py` so the browser test stubs local OpenLayers static paths and fails if jsDelivr is requested.

## Impact Analysis

- Chat no longer depends on jsDelivr for OpenLayers visualizations.
- Privacy/tracking-prevention settings that block third-party CDN storage should no longer interfere with loading the OpenLayers library used by inline map cards.
- The app CSP now aligns with the local-runtime asset expectation for scripts and styles.

## Validation

- Before: chat loaded OpenLayers from jsDelivr and CSP allowed that external script/style source.
- After: chat loads OpenLayers from SimpleChat static files and CSP script/style sources are local-only.