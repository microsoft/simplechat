# OpenAPI URL Import Removal Fix

Fixed/Implemented in version: **0.239.143**

## Issue Description

SimpleChat had moved the OpenAPI plugin UI to an upload-only workflow, but the backend still exposed authenticated URL import endpoints and legacy URL-based plugin creation paths.

That mismatch left dead functionality in place and preserved an unnecessary server-side URL fetch surface that was no longer part of the supported product flow.

## Root Cause Analysis

The frontend plugin modal had already standardized on uploaded OpenAPI file content, but the backend still retained:

- `/api/openapi/validate-url`
- `/api/openapi/download-from-url`
- URL-fetch validation helpers in `openapi_security.py`
- a deprecated `openapi_source_type == 'url'` branch in the OpenAPI plugin factory

Because those code paths still existed, authenticated callers could continue to exercise an unsupported backend URL import path even though the web UI no longer offered it.

## Technical Details

### Files Modified

- `application/single_app/route_openapi.py`
- `application/single_app/openapi_security.py`
- `application/single_app/semantic_kernel_plugins/openapi_plugin_factory.py`
- `application/single_app/config.py`
- `docs/explanation/features/v0.229.001/OPENAPI_ACTION.md`
- `functional_tests/test_openapi_upload_only_flow.py`

### Code Changes Summary

- Removed the backend URL import endpoints for validating and downloading OpenAPI specifications from remote URLs.
- Removed URL-fetch validation helpers from the OpenAPI security validator so it now focuses on uploaded file content only.
- Removed deprecated URL-based plugin factory handling to align runtime behavior with the upload/content-based configuration flow.
- Updated the OpenAPI feature documentation to reflect the supported upload-only workflow.
- Added regression coverage to ensure URL import routes and URL source handling do not return unintentionally.
- Bumped the application version to `0.239.143`.

### Testing Approach

- Added `functional_tests/test_openapi_upload_only_flow.py` to verify the backend no longer exposes URL import routes or URL-based factory handling.
- The regression test also checks that the frontend still requires uploaded OpenAPI content and that the config version matches the implementation.

## Validation

### Before

- The modal required an uploaded OpenAPI file.
- The backend still registered authenticated URL import endpoints.
- The plugin factory still contained a deprecated URL source path.

### After

- OpenAPI configuration is consistently upload-only across the frontend and backend.
- The unsupported server-side URL import surface has been removed.
- The factory and documentation now match the supported content-based plugin configuration flow.

### Impact Analysis

This change is intentionally narrow:

- the supported upload workflow remains unchanged
- frontend configuration still stores validated OpenAPI spec content directly
- only dead URL import behavior was removed