# Home Page Logo Upload Quality Fix

Fixed/Implemented in version: **0.241.059**

## Overview

The home page logo size control introduced in v0.241.058 exposed a quality problem in the upload pipeline. Uploaded custom logos were still being reduced to `100px` tall before storage, so increasing the main-page logo size could enlarge an already downsampled raster and make the result appear soft or blurry.

## Root Cause

- The admin logo upload path resized both light and dark custom logos to `100px` tall before converting them to PNG and storing them in settings.
- The homepage logo size control can render the logo significantly larger than `100px`, which meant the browser was forced to upscale a small stored asset.
- The upload pipeline also logged the full base64 logo payload, which becomes increasingly noisy and expensive as stored logo quality improves.

## Files Modified

- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin_settings.html`
- `functional_tests/test_logo_upload_storage_resolution.py`
- `ui_tests/test_admin_home_page_logo_scale_slider.py`
- `application/single_app/config.py`

## Code Changes

1. Added a dedicated `prepare_logo_image_for_storage(...)` helper for custom logo uploads.
2. Replaced the legacy `100px` storage resize with a bounded `500px` maximum stored height.
3. Continued converting uploaded logos to PNG for consistent downstream serving, but now save them with `optimize=True`.
4. Updated both light and dark logo upload paths to use the shared helper.
5. Replaced full base64 upload log entries with summary metadata including original size, stored size, and PNG byte length.
6. Updated the admin branding help text to explain that uploaded logos are stored at up to `500px` tall to support sharper main-page rendering.

## Validation

- Added `functional_tests/test_logo_upload_storage_resolution.py` to guard against reintroducing the legacy `100px` upload resize.
- Updated the admin home page logo scale UI test header version to track the current app version.
- Verified editor diagnostics were clean for the touched Python, HTML, and test files.

## User Impact

- Uploaded custom logos now retain enough resolution for the main page logo size control to render sharply.
- The app still bounds stored logo size so the settings document does not grow without limit.
- Branding admins receive clearer guidance in the upload UI about how custom logo storage behaves.