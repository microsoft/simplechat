# Custom Logo File Preservation on Startup Fix

## Issue Description

When running SimpleChat locally in Docker, startup initialization removed:

- `application/single_app/static/images/custom_logo.png`
- `application/single_app/static/images/custom_logo_dark.png`

This happened during startup sync logic when database settings did not contain base64 logo data.

## Root Cause Analysis

`ensure_custom_logo_file_exists()` in `config.py` treated missing/empty `custom_logo_base64` and `custom_logo_dark_base64` as a signal to delete existing logo files from disk.

On local Docker runs, users may intentionally keep logo files mounted or present on disk even when those base64 values are not populated in settings. The startup cleanup logic removed those files every run.

## Version Implemented

Fixed/Implemented in version: **0.240.004**

Related config version update:

- `application/single_app/config.py` → `VERSION = "0.240.004"`

## Technical Details

### Files Modified

- `application/single_app/config.py`
- `functional_tests/test_custom_logo_file_preservation_on_startup.py`

### Code Change Summary

- Updated `ensure_custom_logo_file_exists()` to preserve existing logo files when base64 settings are empty.
- Retained overwrite behavior when base64 settings are present and valid.
- Added regression test to verify preserve behavior and guard against reintroducing delete logic.

## Validation

### Test Coverage

- Added functional test: `functional_tests/test_custom_logo_file_preservation_on_startup.py`

### Expected Before/After Behavior

- **Before**: Startup with empty logo base64 settings could delete existing `custom_logo.png` and `custom_logo_dark.png`.
- **After**: Startup preserves existing logo files when base64 settings are empty; only writes/overwrites when base64 data exists.
