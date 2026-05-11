# BLOB_METADATA_TAG_PROPAGATION.md

**Feature**: Blob Metadata Tag Propagation
**Version**: v0.238.025
**Dependencies**: Azure Blob Storage, Azure Cosmos DB, Enhanced Citations

## Overview and Purpose

When enhanced citations is enabled, document tags are now propagated to Azure Blob Storage metadata in addition to AI Search chunks. This ensures that blob-level metadata reflects the current tags assigned to a document, enabling blob-level tag filtering and providing tag context when serving documents through enhanced citations.

## Key Features

- **Automatic Propagation**: Tags are written to blob metadata whenever they are updated on a document
- **Conditional on Enhanced Citations**: Blob metadata updates only occur when `enable_enhanced_citations` is enabled in admin settings
- **Non-Blocking**: Blob metadata update failures are logged but do not prevent the primary tag propagation to AI Search chunks
- **Cross-Workspace Support**: Works for personal, group, and public workspace documents

## Technical Specifications

### Blob Metadata Format

Tags are stored in blob metadata as a comma-separated string under the key `document_tags`:

| Metadata Key | Value Format | Example |
|-------------|-------------|---------|
| `document_tags` | Comma-separated string | `finance,quarterly-report,2024` |
| `document_id` | UUID string | `abc-123-def` (existing) |
| `user_id` | UUID string | `user-456` (existing) |
| `group_id` | UUID string | `group-789` (existing, group docs only) |

### Function: `propagate_tags_to_blob_metadata()`

**Location**: `functions_documents.py`

**Parameters**:
- `document_id` (str): Document ID
- `tags` (list): Array of normalized tag names
- `user_id` (str): User ID
- `group_id` (str, optional): Group ID for group workspace documents
- `public_workspace_id` (str, optional): Public workspace ID

**Flow**:
1. Check if `enable_enhanced_citations` is enabled via `get_settings()`
2. Read document from Cosmos DB to obtain `file_name`
3. Construct blob path based on workspace type
4. Get existing blob metadata via `get_blob_properties()`
5. Merge `document_tags` into existing metadata
6. Update via `set_blob_metadata()`

### Integration Point

Called from `propagate_tags_to_chunks()` after all AI Search chunks are updated. This maintains the existing single-call pattern: routes call `propagate_tags_to_chunks()` and both chunk and blob metadata updates happen automatically.

### Files Modified

| File | Change |
|------|--------|
| `functions_documents.py` | Added `propagate_tags_to_blob_metadata()` function; called from `propagate_tags_to_chunks()` |

## Usage Instructions

No additional configuration is needed. When enhanced citations is enabled in Admin Settings, blob metadata tags are automatically updated whenever document tags change.

## Testing and Validation

1. Enable enhanced citations in Admin Settings
2. Upload a document to any workspace
3. Add tags to the document
4. Verify blob metadata contains `document_tags` field via Azure Storage Explorer or Azure Portal
5. Update tags and verify blob metadata reflects the change
6. Remove all tags and verify `document_tags` is set to empty string
7. Disable enhanced citations and verify blob metadata is NOT updated when tags change
