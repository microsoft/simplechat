# Document Upload Traceback Shadow Fix

Fixed/Implemented in version: **0.239.165**

## Issue Description

Uploading PDF and DOCX documents could fail during processing with this message:

`Processing failed: cannot access local variable 'traceback' where it is not associated with a value`

The failure happened while the document ingestion flow was handling an earlier exception, so the user saw the traceback-scoping error instead of the original upload problem.

## Root Cause Analysis

- `process_di_document(...)` used `traceback.format_exc()` in one exception path.
- The same function also had a later branch with `import traceback` inside the function body.
- In Python, that function-local import makes `traceback` a local variable for the entire function scope.
- When an earlier exception path tried to call `traceback.format_exc()` before the local import executed, Python raised an unbound local error.

## Technical Details

### Files Modified

- `application/single_app/functions_documents.py`
- `application/single_app/config.py`
- `functional_tests/test_document_upload_traceback_shadow_fix.py`

### Code Changes Summary

- Added a module-level `import traceback` in `functions_documents.py`.
- Removed function-local `import traceback` statements so exception handlers all use the same module-scoped import.
- Bumped the application version to `0.239.165`.
- Added a regression test that inspects the AST for `process_di_document(...)` and verifies the fix remains in place.

### Testing Approach

- Added `functional_tests/test_document_upload_traceback_shadow_fix.py` to verify:
- `functions_documents.py` imports `traceback` at module scope.
- `process_di_document(...)` does not locally import `traceback`.
- `process_di_document(...)` still uses `traceback.format_exc()` for diagnostics.

## Validation

### Before

- PDF and DOCX uploads could fail with an unbound local error while handling a processing exception.
- The error masked the original processing failure and made upload debugging harder.

### After

- The upload pipeline uses a consistent module-scoped `traceback` import.
- PDF and DOCX processing no longer trips the unbound local error caused by traceback shadowing.
- Any real underlying processing error now surfaces through the intended exception handling path.