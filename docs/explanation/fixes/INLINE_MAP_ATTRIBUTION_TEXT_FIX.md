# Inline Map Attribution Text Fix

Fixed/Implemented in version: **0.261.049**

## Issue Description

The chat's inline map card passed a tool result's `map_payload.tile_attribution` straight to
OpenLayers, which renders attribution strings as HTML. The card also drew any tool result shaped
like a map, whatever its `tile_url_template` named. A result from a tool other than the Azure
Maps action could therefore place markup in the map's attribution, or make the browser load map
tiles from another host.

## Root Cause Analysis

- `initializeOpenLayersMap` set `attributions: payload.tile_attribution`, and OpenLayers'
  Attribution control writes each attribution string into the page as HTML.
- `isAzureMapsVisualization` only checked that `tile_url_template` was present, not that it
  pointed at SimpleChat's tile proxy.
- The Azure Maps action itself always returns a fixed attribution and a proxied tile template,
  so maps from that action were never affected.

## Version Implemented

- **0.261.049**
- Application version updated in `application/single_app/config.py` to `0.261.049`.

## Files Modified

- `application/single_app/static/js/chat/chat-inline-maps.js`
- `application/single_app/config.py`
- `functional_tests/test_chat_inline_map_attribution_text.py`
- `docs/explanation/release_notes.md`

## Code Changes Summary

- The attribution is passed through the existing `escapeHtml` helper before OpenLayers receives
  it, so it is shown as text.
- New `isTileProxyTemplate` accepts only templates that start with `/api/azure-maps/tile?`,
  contain `{z}`, `{x}` and `{y}`, and have no whitespace, quotes, angle brackets or backslashes.
  `isAzureMapsVisualization` requires it, so a result naming any other tile source is not drawn.

## Testing Approach

- `functional_tests/test_chat_inline_map_attribution_text.py` checks that the attribution is
  escaped and that the map check requires the proxy template. It then runs the real
  `isTileProxyTemplate` function in Node against proxy, foreign, protocol-relative, incomplete and
  quoted templates.
- `ui_tests/test_chat_inline_azure_maps_rendering.py` already uses a proxied template, so the
  existing rendering coverage still applies.

## Impact Analysis

- Maps from the Azure Maps action render exactly as before; the escaped attribution reads the
  same.
- A tool result that only resembles a map, with a tile template outside the proxy, is no longer
  drawn as a map. Its citation is still available through the normal citation controls.

## Validation

- Before: attribution text from a tool result reached the page as HTML, and tiles could load from
  any template.
- After: the attribution is text, and tiles only load through `/api/azure-maps/tile`.
