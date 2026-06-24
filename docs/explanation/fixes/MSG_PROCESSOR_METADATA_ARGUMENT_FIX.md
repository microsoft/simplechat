# MSG Processor Metadata Argument Fix

Fixed/Implemented in version: **0.250.031**

## Issue Description

Uploading an Outlook `.msg` file could fail during background processing with:

```text
process_msg() got an unexpected keyword argument 'auto_extract_metadata'
```

## Root Cause Analysis

The document upload dispatcher passes a shared processor argument set to file processors that participate in the final metadata extraction flow. The new Outlook MSG processor did not include the `auto_extract_metadata` keyword argument in its function signature, so dispatching `.msg` uploads raised a `TypeError` before text extraction could run.

## Technical Details

Files modified:

- `application/single_app/functions_documents.py`
- `application/single_app/config.py`
- `functional_tests/test_msg_processor_auto_metadata_argument.py`

Code changes summary:

- Added `auto_extract_metadata=True` to `process_msg`.
- Reused the MSG processor settings object for chunk configuration and metadata extraction checks.
- Added a final metadata extraction call for direct `process_msg` usage when metadata extraction is enabled.
- Added a regression test that validates the MSG processor accepts the shared dispatcher argument.
- Updated `config.py` from `0.250.030` to `0.250.031`.

## Validation

Testing approach:

- Compile the modified backend and regression test files.
- Run the focused functional regression test.
- Run repository whitespace validation.

Before the fix, `.msg` uploads failed before processing because the processor signature rejected the dispatcher argument. After the fix, the MSG processor accepts the shared metadata argument and can continue through Outlook MSG text extraction and chunk indexing.