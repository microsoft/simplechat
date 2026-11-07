# Azure Maps Tile Token Redaction Fix

Fixed/Implemented in version: **0.261.224**

Related issue: [#1609](https://github.com/microsoft/simplechat/issues/1609)

## Issue Description

Maps that an agent drew with the Azure Maps action showed their markers, paths and areas on a
blank background, in both the classic and the V2 chat, for personal conversations, workflow
conversations and group conversations alike. Every tile request returned 400, "Invalid or
expired Azure Maps tile token."

## Root Cause Analysis

- Tool results are passed through `sanitize_plugin_invocation_value`
  (`semantic_kernel_plugins/plugin_invocation_logger.py`) before they are stored as a reply's
  agent citations. This happens in chat (`_build_plugin_invocation_agent_citation`) and in the
  workflow runner.
- Its `SECRET_ASSIGNMENT_RE` replaces the value of any `token=` assignment in a string with
  `***REDACTED***`. That includes the map payload's `tile_url_template`,
  `/api/azure-maps/tile?token=<proxy token>&...`.
- The stored template therefore carried `token=***REDACTED***`. The tile proxy could not
  decrypt it, and the token refresh that runs when a conversation is opened could not reissue
  it, so no tile ever loaded.

## Version Implemented

- **0.261.224**
- Application version updated in `application/single_app/config.py` to `0.261.224`.

## Technical Details

### Files Modified

- `application/single_app/semantic_kernel_plugins/plugin_invocation_logger.py`
- `application/single_app/config.py`
- `functional_tests/test_v2_inline_maps.py`
- `docs/explanation/features/V2_INTERACTIVE_MAPS.md`
- `docs/explanation/release_notes.md`

### Code Changes Summary

- New `AZURE_MAPS_TILE_PROXY_QUERY_PREFIX` (`/api/azure-maps/tile?`), matching
  `AZURE_MAPS_TILE_PROXY_ROUTE` in `functions_azure_maps.py`.
- `_redact_secret_assignment` keeps a `token=` value only when it directly follows that prefix,
  which is exactly where `build_tile_proxy_url_template` writes it. Every other match is still
  redacted. That includes another key after the prefix, a token later in the query, the prefix
  on another path, and absolute URLs, which `_redact_url` handles as before.
- The kept token is not a credential. It is encrypted with the app's secret key, expires after
  240 minutes, only works on SimpleChat's own signed-in tile proxy, and the browser needs it to
  load map tiles. The Azure Maps subscription key itself never leaves the server.

### Testing Approach

`functional_tests/test_v2_inline_maps.py::test_tool_result_redaction_keeps_only_the_tile_proxy_token`
loads the real invocation logger and Azure Maps helpers. It checks that:

- A map result keeps its tile template, as an object and as JSON text, and the kept token still
  decodes.
- `token=abc`, `/api/other?token=`, `/api/azure-maps/tile?api_key=`, a token later in the query,
  `access_token`, an absolute tile URL and a password beside a kept token are all still
  redacted.
- The prefix matches `AZURE_MAPS_TILE_PROXY_ROUTE`.

### Impact Analysis

- New maps load their tiles in the classic and V2 chat, and the existing refresh keeps them
  loading after the token's 240 minutes.
- Maps stored before this fix keep `***REDACTED***` in place of the token. The server cannot
  recover it, so those maps still show no tiles. Running the request again produces a working
  map.

## Validation

- Before: a stored map's tile template read `token=***REDACTED***`, and every tile request
  returned 400.
- After: the stored template keeps its proxy token, tiles load, and every other secret in a tool
  result is redacted as before.
