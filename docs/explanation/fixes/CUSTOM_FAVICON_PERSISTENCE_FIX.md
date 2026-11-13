# Custom Favicon Persistence Fix

Fixed in version: **0.261.440**

Related issue: [#1932](https://github.com/microsoft/simplechat/issues/1932). Related historical branding report: [#292](https://github.com/microsoft/simplechat/issues/292).

Development port of the main-branch fix in [#1935](https://github.com/microsoft/simplechat/pull/1935), source commit `48eab1c86`. No main promotion history is included.

## Issue and root cause

A customer on v0.261.027 reported that a custom favicon reverted to the SimpleChat icon after some time. Re-uploading restored it temporarily. The customer's instance lifecycle and configuration were not available to confirm the precise trigger.

Uploads already persisted `custom_favicon_base64` and incremented `favicon_version`. The template already included that version in its static favicon URL. However, startup regenerated only custom logos, not the favicon, and an upload regenerated the favicon only on the instance handling the save. A fresh instance could therefore serve the bundled icon despite having the correct custom favicon in its settings.

Redis cannot fix that gap by itself: it shares the settings document, not the instance-local image file. Without Redis, the settings resolver reads Cosmos directly; that also does not regenerate the file.

## Implementation

`application\single_app\app.py` now restores the favicon alongside the logos in `initialize_application`. Before serving the existing static `images/favicon.ico` asset, the initialization hook resolves request settings through the existing shared settings path and regenerates the local icon if necessary. Unrelated static requests do not perform this reconciliation.

`application\single_app\config.py` retains `ensure_custom_favicon_file_exists` as the shared materialization helper. It validates the base64 and ICO image, skips identical content, and writes changed bytes to a temporary sibling file before an atomic replacement. Invalid data and filesystem failures are logged under `[BRANDING]`; a failed replacement does not truncate the previous icon, and temporary files are cleaned up.

The change preserves the existing upload format handling, static URL, favicon version counter, settings sanitization, and logo behavior. It introduces no Redis requirement or new settings key.

The application version in `application\single_app\config.py` advances from **0.261.439** to **0.261.440**.

Development's shared `functions_branding_urls.py` URL builder, V2 bootstrap branding payload, V2 shell, and upload APIs remain unchanged. Their existing `/static/images/favicon.ico` URLs use the same static-request reconciliation as the classic interface.

## Validation

`functional_tests\test_custom_favicon_persistence.py` imports real application modules in fresh processes with external network access blocked. Normal and optimized Python exercise startup restoration, independent instance roots, subsequent uploads with Redis/Cosmos/read-fallback settings, missing-file recovery, unchanged-file preservation, invalid data, failed replacement cleanup, and concurrent complete-file reads.

`ui_tests\test_custom_favicon_persistence.py` runs isolated local browser fixtures using the real base-template head, V2 shell branding renderer, and favicon hook. Both surfaces verify the red custom icon at version 2, update settings and remove the instance file, then verify the regenerated blue icon at version 3. Functional probes also exercise the real V2 bootstrap branding builder. These tests do not modify a deployed application's branding.

The targeted favicon, settings consistency, import-boundary, and V2 branding suite passed **45 tests**. The classic and V2 browser regressions passed **2 tests**. Logo preservation, route policy, documentation quality, and documentation surface coverage checks also passed. Exact commands and results are recorded in the Development pull request.

The existing `test_app_settings_cache_versioning.py` source-marker check fails on Development because it expects an outdated one-line settings write call. Its test and all three inspected settings modules are unchanged from the Development base; the runtime settings consistency and favicon Redis/Cosmos/fallback regressions pass. This unrelated baseline test is not modified by the port.

## Impact and limitations

Fresh instances no longer require an admin re-upload to display stored branding. Already-running instances reconcile their file when the browser requests the favicon, including after a versioned upload.

Browsers may retain an already-cached favicon until another icon request or page reload. This change does not push live favicon updates into open tabs. If settings are unavailable, existing settings error handling still applies. A filesystem failure is logged and retried on a later favicon request; on Windows, a concurrent open file can prevent replacement without damaging its existing bytes.

The fix does not change clearing/resetting branding or unrelated logo synchronization.
