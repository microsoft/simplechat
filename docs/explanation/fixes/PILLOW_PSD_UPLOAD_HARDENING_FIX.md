# Pillow PSD Upload Hardening Fix

Fixed/Implemented in version: **0.239.134**

## Issue Description

The application pinned Pillow to `11.1.0`, which falls in the vulnerable range for an out-of-bounds write when parsing specially crafted PSD images.

Although the admin settings page only intends to accept PNG and JPEG uploads for logos and favicons, those uploads were still passed directly to `Image.open(...)` without an explicit decoder allowlist.

## Root Cause Analysis

- `application/single_app/requirements.txt` pinned Pillow to a vulnerable version.
- `application/single_app/route_frontend_admin_settings.py` relied on filename extensions before calling Pillow, but did not constrain Pillow to the actual image formats the route supports.

## Technical Details

### Files Modified

- `application/single_app/requirements.txt`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/config.py`
- `functional_tests/test_pillow_psd_upload_hardening.py`

### Code Changes Summary

- Updated the Pillow dependency pin to `12.1.1`.
- Added `open_allowed_uploaded_image(...)` so admin logo and favicon uploads only open through Pillow with `PNG` and `JPEG` decoders enabled.
- Reused that helper for standard logo, dark-mode logo, and favicon uploads.
- Bumped the application version to `0.239.134`.

### Testing Approach

- Added `functional_tests/test_pillow_psd_upload_hardening.py` to verify the patched dependency pin, the route-level Pillow format allowlist, and the version bump.

## Validation

### Before

- The app installed a Pillow version in the vulnerable range.
- A disguised PSD upload could still be handed to Pillow from the admin image upload route.

### After

- The app pins Pillow to the patched version.
- The admin image upload route now restricts Pillow parsing to the PNG and JPEG formats already allowed by the UI.