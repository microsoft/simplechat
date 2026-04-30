# TABULAR AUTHOR METADATA NORMALIZATION FIX

Fixed/Implemented in version: **0.240.028**

## Header Information

- Issue description: Tabular uploads could fail during Azure AI Search indexing when the chunk `author` field contained `null` or blank list members.
- Root cause analysis: Document metadata carried `authors` values forward without sanitization, and chunk indexing paths trusted those values when building the search payload.
- Version implemented: 0.240.028

## Technical Details

- Files modified: `application/single_app/functions_documents.py`, `application/single_app/config.py`, `functional_tests/test_tabular_author_metadata_normalization_fix.py`
- Code changes summary: Hardened `ensure_list()` to remove null and blank items, normalized carried-forward `authors` metadata, normalized chunk author values before single-chunk upload and chunk metadata sync, and defaulted new document `authors` values to an empty list.
- Testing approach: Added a focused functional regression test that validates the helper behavior and checks the tabular indexing integration points in source.
- Impact analysis: Prevents enhanced-citation tabular uploads from failing on invalid `author` metadata while preserving existing author lists that contain valid string values.

## Validation

- Test results: Targeted functional test validates author normalization behavior and version bump expectations.
- Before/after comparison: Before the fix, `author` could reach Azure AI Search as `null` or contain null members; after the fix, it is always emitted as a list of non-empty strings.
- User experience improvements: XLSX/CSV uploads that previously failed during schema-summary indexing now complete without the invalid-author payload error.