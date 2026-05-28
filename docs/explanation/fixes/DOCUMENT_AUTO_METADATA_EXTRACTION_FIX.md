# Document Auto Metadata Extraction Fix

Fixed in version: **0.241.110**

## Issue Description

Automatic document metadata extraction was inconsistent across upload file types when `enable_extract_meta_data` was enabled. Plain text and several text-like formats could finish chunking without the final AI metadata extraction pass, while other processors ran their own local metadata extraction and then had the final status overwritten by the shared upload dispatcher.

Public workspace audio and video processing also did not preserve public workspace scope consistently when saving searchable chunks, which could prevent public media content from participating correctly in final metadata extraction and later metadata-to-chunk synchronization.

## Root Cause Analysis

Metadata extraction was implemented inside individual file processors instead of as one shared post-processing step. File types whose processors did not include that local extraction block skipped automatic extraction entirely. Processors that did include it could set `Final metadata extracted`, but the dispatcher later replaced the status with generic `Processing complete`.

Public media chunk saving reused personal/group assumptions and did not consistently pass `public_workspace_id` into search chunk creation or metadata propagation.

## Technical Details

Files modified:

- `application/single_app/functions_documents.py`
- `application/single_app/config.py`
- `functional_tests/test_document_auto_metadata_extraction_consistency.py`

Code changes summary:

- Added one dispatcher-owned final metadata extraction step after successful chunking for all supported upload file types.
- Disabled processor-local auto extraction when processors are invoked by the dispatcher to avoid duplicate extraction calls.
- Preserved final status outcomes such as final metadata extracted, no new metadata, extraction warning, and no indexed content.
- Passed public workspace scope through video chunk creation, audio transcript chunk creation, blob metadata, and metadata-to-chunk sync.
- Updated `config.py` from `0.241.109` to `0.241.110` for traceability.

## Testing Approach

Added `functional_tests/test_document_auto_metadata_extraction_consistency.py` to validate the dispatcher-owned metadata flow, final status mapping, public workspace media scope handling, and the version update.

## Impact Analysis

All upload-supported file types now share the same automatic metadata extraction experience when the feature flag is enabled. Existing manual metadata extraction endpoints remain unchanged. Public workspace media files now retain public scope during chunk indexing and metadata synchronization.

## Validation

Before this fix, `.txt`, `.xml`, `.yaml`, `.yml`, `.log`, and `.docm` uploads could finish processing without automatic metadata extraction. After this fix, the dispatcher attempts final metadata extraction for any file type that saved at least one chunk and only skips it when the feature is disabled or no chunks were indexed.

Related functional test: `functional_tests/test_document_auto_metadata_extraction_consistency.py`

Related config.py version update: `application/single_app/config.py` -> `0.241.110`