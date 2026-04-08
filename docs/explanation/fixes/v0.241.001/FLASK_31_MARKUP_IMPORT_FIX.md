# Flask 3.1 Markup Import Fix

Fixed/Implemented in version: **0.240.016**

## Issue Description

After upgrading Flask from `2.2.5` to `3.1.3`, the application failed during startup while loading `config.py` with `ImportError: cannot import name 'Markup' from 'flask'`.

## Root Cause Analysis

Flask 3 no longer re-exports `Markup` from the `flask` package.

The shared `config.py` module still imported `Markup` through `from flask import ...`, which caused the import failure before the app could finish initialization.

## Technical Details

### Files Modified

- `application/single_app/config.py`
- `functional_tests/test_flask_markup_import_fix.py`

### Code Changes Summary

- Removed `Markup` from the `flask` import list in `config.py`.
- Added `from markupsafe import Markup` so the shared symbol remains available to modules that import from `config.py`.
- Added a regression test that parses `config.py` imports and verifies the Flask 3-safe import path.
- Bumped the application version to `0.240.016`.

### Testing Approach

- Added `functional_tests/test_flask_markup_import_fix.py` to verify `Markup` is imported from `markupsafe` and not from `flask`.
- Re-ran the application startup path to validate the previous import failure is removed.

## Validation

### Before

- `python app.py` failed immediately during `config.py` import.
- The traceback stopped on `ImportError: cannot import name 'Markup' from 'flask'`.

### After

- `config.py` imports `Markup` from `markupsafe`, which is compatible with Flask 3.x.
- The app can proceed past the previous startup import failure point.

### Impact Analysis

This is a narrow compatibility fix with no intended runtime behavior change.

Markdown rendering and newline-to-HTML conversion continue to use the same `Markup` type, but the import source now matches the Flask 3 package boundary.