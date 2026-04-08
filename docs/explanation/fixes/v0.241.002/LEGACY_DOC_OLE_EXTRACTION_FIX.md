# Legacy DOC OLE Extraction Fix

Fixed/Implemented in version: **0.241.002**

## Issue Description

Uploading Word 97-2003 `.doc` files failed during text extraction because the code treated `.doc` and `.docm` as the same format and sent both through `docx2txt`.

Binary `.doc` files are OLE compound documents, not OOXML zip archives, so `docx2txt` raised `There is no item named 'word/document.xml' in the archive`.

## Root Cause Analysis

- `application/single_app/functions_documents.py` used the same extraction path for `.doc` and `.docm`.
- `application/single_app/route_frontend_chats.py` mirrored the same assumption for inline chat uploads.
- The shared content helpers had metadata extraction for `.docx`, but no legacy `.doc` parser for OLE `WordDocument` and table streams.

## Technical Details

### Files Modified

- `application/single_app/functions_content.py`
- `application/single_app/functions_documents.py`
- `application/single_app/route_frontend_chats.py`
- `application/single_app/requirements.txt`
- `application/single_app/config.py`
- `functional_tests/test_legacy_doc_ole_extraction.py`

### Code Changes Summary

- Added an `olefile`-based legacy `.doc` extraction path that reads `WordDocument` and table streams and reconstructs text from Word piece tables.
- Kept `.docm` on the existing OOXML `docx2txt` path.
- Added shared Word text and metadata dispatch helpers so document processing and chat uploads use the same format-aware behavior.
- Pinned `olefile==0.47` in the main application requirements.
- Bumped the application version to `0.241.002`.

### Testing Approach

- Added `functional_tests/test_legacy_doc_ole_extraction.py` to validate compressed and UTF-16 piece-table decoding plus `.doc` versus `.docm` dispatch behavior without requiring the full Azure/Cosmos runtime.

## Validation

### Before

- Real Word 97-2003 `.doc` uploads failed with a missing `word/document.xml` archive entry.
- The same incorrect `.doc` assumption existed in both document ingestion and chat upload extraction.

### After

- Legacy `.doc` files are parsed through an OLE-aware extraction path.
- `.docm` files continue to use the OOXML extraction path they already required.
- The regression test suite now covers the binary Word piece-table parser and extension dispatch split.