# Azure AI Search Document Cleanup Scope Fix

Fixed in version: **0.250.060**

## Issue

Personal, group, and public workspace documents use one Azure AI Search index per workspace type. Chunk cleanup previously queried the selected index by `document_id` alone. Although normal uploads generate unique document IDs, an ID reused by an import, synchronization process, migration, or integration could allow one workspace's cleanup operation to match chunks owned by another workspace in the same index.

## Root Cause

The cleanup helpers selected the correct personal, group, or public Search client but did not include the corresponding `user_id`, `group_id`, or `public_workspace_id` in their OData filters. The same document-only predicate was also used when changing revision visibility.

Archived revisions store their workspace field as `__archived__::<scope-id>`, so cleanup must recognize both the active and archived forms without matching another workspace.

## Technical Details

### Files Modified

- `application/single_app/functions_documents.py`
- `application/single_app/functions_retention_policy.py`
- `application/single_app/route_backend_control_center.py`
- `functional_tests/test_ai_search_document_cleanup_scope.py`
- `application/single_app/config.py`

### Code Changes

- Added one OData filter builder for document chunk mutations.
- Required every filter to combine `document_id` with the owning workspace field.
- Escaped apostrophes in document and workspace identifiers before constructing OData literals.
- Matched only the active scope ID and its `__archived__::` form so revision cleanup and promotion continue to work.
- Required personal cleanup callers to provide `user_id`; missing personal scope now fails before querying Azure AI Search.
- Converted version values to integers before adding them to version-specific cleanup filters.
- Propagated personal owner IDs through retention, reprocessing, revision deletion, and control-center bulk deletion paths.

## Impact Analysis

Normal cleanup behavior is unchanged for correctly scoped documents. Deleting a document owned by a group still removes its chunks, including archived revisions, while removing a receiving group's share continues to leave the owning document intact. Cleanup can no longer select chunks associated with another user, group, or public workspace solely because they have the same document ID.

The application version in `application/single_app/config.py` was incremented from `0.250.059` to `0.250.060` for this fix.

## Validation

`functional_tests/test_ai_search_document_cleanup_scope.py` validates:

- Personal, group, and public cleanup predicates.
- Active and archived workspace scope matching.
- OData literal escaping.
- Fail-closed personal cleanup when `user_id` is absent.
- Integer-only version cleanup filters.
- Delete actions emitted by the production cleanup helpers.
- Scope propagation at every production `delete_document_chunks` call site.

Focused result: **6 tests passed**.