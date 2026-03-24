# Per-Message Word Export Route Fix

Fixed/Implemented in version: **0.239.128**

## Issue Description

The chat message dropdown still offered "Export to Word", but requests to `POST /api/message/export-word` returned `405 METHOD NOT ALLOWED`.

## Root Cause Analysis

The backend export module no longer registered the explicit `/api/message/export-word` route even though the frontend, release notes, feature documentation, and functional tests still referenced it.

Because the explicit route was missing, Flask matched the request path against the generic `/api/message/<message_id>` route instead. That route only supports `DELETE`, so a `POST` to `/api/message/export-word` failed with `405`.

## Technical Details

### Files Modified

- `application/single_app/route_backend_conversation_export.py`
- `application/single_app/config.py`
- `functional_tests/test_per_message_export.py`

### Code Changes Summary

- Restored the explicit `POST /api/message/export-word` route in the conversation export module.
- Added DOCX rendering helpers for single-message export, including basic markdown formatting and citation output.
- Added regression coverage to verify that the backend source continues to define the explicit route.
- Bumped the application version to `0.239.128`.

### Testing Approach

- Extended `functional_tests/test_per_message_export.py` with an AST-based regression check for the missing backend route.
- Preserved the existing content normalization and Word document generation checks for the per-message export feature.

## Validation

### Before

- `POST /api/message/export-word` returned `405 METHOD NOT ALLOWED`.
- The frontend Word export action could not download a `.docx` file.

### After

- `POST /api/message/export-word` is explicitly registered again.
- The frontend request can resolve to the intended Word export handler instead of the generic message delete route.

### User Experience Improvement

Users can export a single chat message to Word from the message dropdown without hitting a method error.