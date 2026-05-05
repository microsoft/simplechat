# Document Upload Settings Binding Fix

Fixed/Implemented in version: **0.241.101**

## Issue Description

Valid document uploads could fail in two stages after full application startup:

- The upload request could return a 400 even though the file type and request payload were valid.
- After the request path was repaired, background processing could still fail with `name 'get_settings' is not defined` while generating embeddings.

This affected personal, group, and public workspace uploads because all three flows share the same upload helpers.

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.101"`.

## Root Cause Analysis

- `application/single_app/functions_logging.py` and `application/single_app/functions_content.py` depended on `get_settings()` through star-import snapshots from `functions_settings.py`.
- During the full Flask app import path, those snapshots could lose the live `get_settings` binding.
- The request-time upload logging helper then raised `NameError`, which surfaced as the immediate 400 upload failure.
- The embedding helper hit the same missing name later in background processing, so uploads could appear accepted but never finish processing.

## Technical Details

Files modified:

- `application/single_app/functions_logging.py`
- `application/single_app/functions_content.py`
- `application/single_app/functions_documents.py`
- `application/single_app/config.py`
- `functional_tests/test_upload_settings_import_order_fix.py`

Code changes summary:

- Resolved settings access in the upload logging path through the live `functions_settings` module object.
- Added the same runtime-safe settings resolution to the embedding helper used during background chunk processing.
- Kept `functions_documents.py` on the same runtime-safe settings access pattern for the shared upload pipeline.
- Added a focused regression test that imports the full app and exercises both helpers without calling external Azure services.

Testing approach:

- Reproduced the original request-path failure with `functional_tests/test_upload_diagnosis.py`.
- Re-ran the same diagnostic after the request-path fix to isolate the remaining background embedding failure.
- Added a focused import-order regression test for the upload logging and embedding helper bindings.

## Validation

Before:

- `/api/documents/upload` could return 400 for valid uploads.
- Background document processing could fail with `name 'get_settings' is not defined` during embedding generation.
- The same bug class affected personal, group, and public uploads because they all share the same helper path.

After:

- Upload requests return 200 for valid files.
- Background processing completes chunk save and embedding generation.
- The diagnostic upload completed with the document processed successfully and embedding token usage recorded.

Related functional tests:

- `functional_tests/test_upload_settings_import_order_fix.py`
- `functional_tests/test_upload_diagnosis.py`