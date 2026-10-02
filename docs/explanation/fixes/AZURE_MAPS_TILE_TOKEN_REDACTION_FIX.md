# Azure Maps Tile Token Redaction Fix

Fixed/Implemented in version: **0.261.050**

## Issue Description

Maps that an agent drew with the Azure Maps action showed their markers, paths and areas on a
blank background, in chat and in workflow results. Every tile request returned 400, "Invalid or
expired Azure Maps tile token."

## Root Cause Analysis

- Before a tool result is stored as a reply's agent citation, it passes through
  `sanitize_plugin_invocation_value` in `semantic_kernel_plugins/plugin_invocation_logger.py`.
  Chat (`_build_plugin_invocation_agent_citation`) and the workflow runner both do this.
- Its `SECRET_ASSIGNMENT_RE` replaces the value of any `token=` assignment with
  `***REDACTED***`. That includes the map payload's `tile_url_template`,
  `/api/azure-maps/tile?token=<proxy token>&...`.
- The stored template therefore carried `token=***REDACTED***`. The tile proxy could not decrypt
  it, and the token refresh that runs when a conversation is opened could not reissue it.

## Version Implemented

- **0.261.050**
- Application version updated in `application/single_app/config.py` to `0.261.050`.

## Files Modified

- `application/single_app/semantic_kernel_plugins/plugin_invocation_logger.py`
- `application/single_app/config.py`
- `functional_tests/test_azure_maps_tile_token_redaction_fix.py`
- `docs/explanation/release_notes.md`

## Code Changes Summary

- New `AZURE_MAPS_TILE_PROXY_QUERY_PREFIX` (`/api/azure-maps/tile?`), matching
  `AZURE_MAPS_TILE_PROXY_ROUTE` in `functions_azure_maps.py`.
- `_redact_secret_assignment` keeps a `token=` value only when it directly follows that prefix,
  which is where `build_tile_proxy_url_template` writes it. Every other match is still redacted:
  another key after the prefix, a token later in the query, the prefix on another path, and
  absolute URLs, which `_redact_url` handles as before.
- The kept token is not a credential. It is encrypted with the app's secret key, expires after
  240 minutes, only works on SimpleChat's signed-in tile proxy, and the browser needs it to load
  tiles. The Azure Maps subscription key never leaves the server.

## Testing Approach

`functional_tests/test_azure_maps_tile_token_redaction_fix.py` loads the real invocation logger
and Azure Maps helpers. It checks that:

- A map result keeps its tile template, as an object and as JSON text, and the kept token still
  decodes.
- Other `token=` values, other keys after the prefix, a token later in the query, `access_token`,
  absolute tile URLs and a password next to a kept token are still redacted.
- The prefix matches `AZURE_MAPS_TILE_PROXY_ROUTE`.

## Impact Analysis

- New maps load their tiles, and the existing refresh keeps them loading after 240 minutes.
- Maps stored before this fix keep `***REDACTED***` in place of the token. That cannot be
  recovered, so those maps still show no tiles. Running the request again produces a working map.

## Validation

- Before: a stored map's tile template read `token=***REDACTED***`, and every tile request
  returned 400.
- After: the stored template keeps its proxy token and tiles load. Every other secret in a tool
  result is redacted as before.
