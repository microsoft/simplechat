# Image Generation API Version Default Fix (v0.261.047)

Fixed in version: **0.261.047** (Development) and **0.261.210** (React V2)

## React V2

React V2 manages image generation through AI Connections, so the same change reaches three more
places in **0.261.210**:

- `normalize_image_connection_api_version_settings()` in `functions_settings.py` runs on every
  settings load. It upgrades a connection's image operation profile
  (`connection.operation_settings.image_generation.api_version`) that is exactly
  `2024-12-01-preview`, which the legacy image import copied from the old default. APIM
  profiles, other versions and blank versions are left alone. A blank version already falls back
  to `2025-04-01-preview` at request time.
- `LEGACY_DEFAULT_IMAGES_API_VERSION` in `functions_image_api_route.py`, the fallback for
  unmigrated legacy direct Images settings with no version, now equals
  `DEFAULT_IMAGES_API_VERSION` (`2025-04-01-preview`). An unmigrated legacy APIM route with no
  version keeps its `2024-12-01-preview` fallback, now named
  `LEGACY_APIM_DEFAULT_IMAGES_API_VERSION`, because the gateway decides which versions it
  accepts.
- The V2 admin field for `azure_openai_image_gen_api_version` in `admin_settings_fields.py`
  shows the new default, and `docs/admin/ai-models.md` and
  `docs/explanation/features/IMAGE_GENERATION_RESPONSES_MODELS.md` describe the upgrade.

`functional_tests/test_image_generation_api_version_default.py` covers the connection profile
migration, including a real settings load that persists it, and
`functional_tests/test_image_generation_sdk_http.py` expects the new fallback on the wire.

## Issue Description

The Azure OpenAI image generation API version, `azure_openai_image_gen_api_version`, defaulted to
`2024-12-01-preview`. That version predates gpt-image model support, so a deployment that left the
default in place could not use gpt-image-1, gpt-image-1.5, or gpt-image-2 without an admin
changing it by hand.

## Root Cause Analysis

The shipped default, `2024-12-01-preview`, predates gpt-image model support; Microsoft documents
`2025-04-01-preview` for the gpt-image models. Raising the code-level default alone would not have
been enough: `get_settings()` merges defaults with `deep_merge_dicts()`, which only fills keys that
are missing from the persisted settings document. Every deployment that had already loaded
settings stored `2024-12-01-preview`, and would have kept it indefinitely.

## Technical Details

### Files Modified

| File | Change |
| --- | --- |
| `application/single_app/functions_settings.py` | New default constant and load-time migration |
| `docs/admin/ai-models.md` | Image Gen API Version default |
| `artifacts/cosmos_examples/cosmos-settings-example.json` | Image generation API version example |
| `application/external_apps/databaseseeder/artifacts/admin_settings.json` | Image generation API version seed value |
| `application/single_app/config.py` | Version `0.261.047` |
| `functional_tests/test_image_generation_api_version_default.py` | New regression coverage |
| `docs/explanation/release_notes.md` | Bug Fixes entry |

### Code Changes Summary

- `AZURE_OPENAI_IMAGE_GEN_API_VERSION_DEFAULT = '2025-04-01-preview'` is the new default in
  `get_settings()`. It is the newest dated Azure OpenAI API version and the one Microsoft documents
  for gpt-image-1, gpt-image-1.5, and gpt-image-2.
- `AZURE_OPENAI_IMAGE_GEN_API_VERSION_PREVIOUS_DEFAULT = '2024-12-01-preview'` records the old
  default for the migration.
- `normalize_image_generation_api_version_settings(settings)` runs from
  `normalize_loaded_settings()` on every settings load. It upgrades a stored value that is exactly
  the previous default, or blank, to the new default and returns `True` so the change is
  persisted. Any other value is a deliberate admin choice and is left untouched.
- `azure_apim_image_gen_api_version` is intentionally not migrated. An APIM gateway defines the API
  version it accepts, which is why that setting has no default.

A saved `2024-12-01-preview` cannot be told apart from the untouched old default, so that exact
value is always upgraded. Any other saved version is kept, so an admin can still pin a specific
version by entering it.

## Testing

`functional_tests/test_image_generation_api_version_default.py` covers:

- the new default and the named constants,
- the previous default and padded previous default being upgraded,
- blank, whitespace, missing, and `None` values being upgraded,
- custom values such as `2025-03-01-preview`, and the new default itself, being left untouched,
- the APIM API version never changing,
- non-dict settings and non-string values being handled safely,
- the migration being wired into `normalize_loaded_settings()`,
- the admin docs and example artifacts showing the new default,
- a real `get_settings()` load, in fresh normal and optimized processes with external I/O blocked,
  that migrates and persists the value to the settings document.

Run it with:

```powershell
python .\functional_tests\test_image_generation_api_version_default.py
```

The existing settings suites `test_app_settings_store_consistency.py`,
`test_settings_deep_merge_persistence_fix.py`, `test_tabular_parity_stale_settings_migration.py`,
and `test_app_settings_cache_versioning.py` were re-run and pass.

## Validation

| Stored `azure_openai_image_gen_api_version` | Before | After |
| --- | --- | --- |
| `2024-12-01-preview` | Kept | `2025-04-01-preview` |
| Blank | Kept blank | `2025-04-01-preview` |
| `2025-03-01-preview` or any other value | Kept | Kept |
| New deployment | `2024-12-01-preview` | `2025-04-01-preview` |
| `azure_apim_image_gen_api_version` | Kept | Kept |
