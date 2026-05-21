# Visio Extensions Import Fix

Fixed/Implemented in version: **0.241.079**

## Issue Description

Application startup failed while importing enhanced citation routes because `route_enhanced_citations.py` imported `VISIO_EXTENSIONS` from `config.py`, but the shared constant was not defined.

## Root Cause Analysis

Visio ingestion and enhanced citation preview support were added around a shared extension concept, and downstream code referenced `VISIO_EXTENSIONS`. The config module still only declared base document, tabular, image, video, and audio extension sets, so Python raised an `ImportError` before Flask route registration could complete.

## Version Implemented

0.241.079

## Technical Details

### Files Modified

- `application/single_app/config.py`
- `functional_tests/test_visio_extensions_config.py`
- `docs/explanation/features/VISIO_INGESTION.md`
- `docs/explanation/fixes/VISIO_EXTENSIONS_IMPORT_FIX.md`

### Code Changes Summary

- Added `VISIO_EXTENSIONS = {'vsdx'}` to the shared configuration module.
- Included Visio extensions in `get_allowed_extensions()` so `.vsdx` uploads use the same shared allow-list as ingestion and enhanced citations.
- Bumped `application/single_app/config.py` to `VERSION = "0.241.079"`.
- Added a functional regression test that parses the relevant Python files and verifies the config export, upload allow-list inclusion, and enhanced citation import.

### Testing Approach

- Ran the new Visio extension config functional test.
- Ran Python compilation for the modified config and test files.
- Validated the enhanced citation import path used by app startup.

### Impact Analysis

The app can import and register enhanced citation routes again, and `.vsdx` uploads are consistently recognized by the shared allowed-extension configuration.

## Validation

### Test Results

- `python functional_tests/test_visio_extensions_config.py` passes.
- `python -m py_compile application/single_app/config.py functional_tests/test_visio_extensions_config.py` passes.
- `python -c "from route_enhanced_citations import register_enhanced_citations_routes; from config import VISIO_EXTENSIONS; print(VISIO_EXTENSIONS)"` succeeds.

### Before/After Comparison

Before, importing `route_enhanced_citations.py` failed with `ImportError: cannot import name 'VISIO_EXTENSIONS' from 'config'`. After, the constant is exported from config and reused by allowed-upload logic.

### User Experience Improvements

Administrators and users can start the app with enhanced citations enabled and continue using native Visio `.vsdx` ingestion and citation preview flows.