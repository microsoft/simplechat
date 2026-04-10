# Legacy DOC Processing Parity Fix

Fixed/Implemented in version: **0.241.004**

## Issue Description

Legacy Word 97-2003 `.doc` files could be uploaded and chunked after the OLE extraction fix, but they still did not follow the same higher-level processing workflow as other Word documents.

That left two visible gaps:

- metadata extraction did not populate the document record consistently
- enhanced citations did not report the same processing state as the shared document pipeline

## Root Cause Analysis

- `application/single_app/functions_documents.py` still routed `.doc` files through `process_doc(...)`, which is a direct text-extraction path.
- The richer `process_di_document(...)` path is where the app performs initial metadata updates, sets the `enhanced_citations` state, and runs final metadata extraction.
- Legacy OLE metadata values can be stored as byte strings, so title/author values also needed normalization before being written back to the document record.

## Technical Details

### Files Modified

- `application/single_app/functions_content.py`
- `application/single_app/functions_documents.py`
- `application/single_app/config.py`
- `functional_tests/test_legacy_doc_ole_extraction.py`

### Code Changes Summary

- Routed `.doc` files through the shared document-processing pipeline instead of the direct `process_doc(...)` branch.
- Added a legacy `.doc` branch inside the shared pipeline that uses `extract_word_text(..., '.doc')` instead of Azure Document Intelligence.
- Normalized OLE metadata byte values before applying title/author updates.
- Updated document creation logging to fall back to the stored `authors` list when a singular `author` field is not present.
- Bumped the application version to `0.241.004`.

### Testing Approach

- Extended `functional_tests/test_legacy_doc_ole_extraction.py` to cover metadata normalization and verify that `.doc` now routes through the shared document-processing workflow while `.docm` stays on the direct OOXML path.

## Validation

### Before

- `.doc` files extracted text, but skipped the shared processing workflow used by richer document types.
- Metadata fields could remain blank because the direct `.doc` path did not run the same metadata lifecycle.
- Enhanced citations did not surface the same state transitions as the shared Word document path.

### After

- `.doc` files use the shared document-processing workflow while still relying on OLE extraction for their content.
- Initial metadata values from OLE are normalized before they are saved.
- Final metadata extraction can run through the same workflow used by other document types.
- Document creation logging now records author information from the saved `authors` list when available.