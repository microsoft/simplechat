# DOCUMENT_TAG_SYSTEM.md

**Feature**: Document Tag System
**Version**: v0.238.024
**Dependencies**: Azure Cosmos DB, Azure AI Search, Flask Backend

## Overview and Purpose

The Document Tag System provides user-defined labels for organizing documents across all workspace types (personal, group, and public). Tags enable flexible, non-hierarchical document categorization that integrates directly with Azure AI Search, allowing tag-filtered retrieval during chat. Tags support custom colors, bulk operations, and are consistently available across all three workspace scopes.

## Key Features

- **Tag Creation with Custom Colors**: 10-color default palette with hash-based assignment, plus custom hex color override
- **Bulk Tagging**: Apply, remove, or set tags on multiple documents in a single operation
- **Tag Renaming and Deletion**: Rename or delete tags with automatic propagation to all affected documents and their AI Search chunks
- **AI Search Integration**: Tags propagate to document chunks, enabling OData tag filtering during hybrid search
- **Cross-Workspace Support**: Consistent tag API across personal, group, and public workspaces
- **Tag Validation**: Max 50 characters, alphanumeric plus hyphens/underscores, normalized to lowercase, deduplicated

## Technical Specifications

### Architecture Overview

Tag definitions and document tag assignments are stored separately:

1. **Tag Definitions** (name + color + created_at):
   - **Personal**: Stored in user settings container under `settings.tag_definitions.personal`
   - **Group**: Stored on the group Cosmos document under `tag_definitions`
   - **Public**: Stored on the public workspace Cosmos document under `tag_definitions`

2. **Document Tags**: Each document record contains a `tags` array of normalized tag name strings (e.g., `["finance", "q4-report"]`)

3. **Chunk Tags**: When tags are updated on a document, they are propagated to all associated chunks via the `document_tags` field, enabling AI Search filtering

### Core Functions

Located in `application/single_app/functions_documents.py` (lines 6250-6558):

| Function | Purpose |
|----------|---------|
| `normalize_tag(tag)` | Trims whitespace and converts to lowercase |
| `validate_tags(tags)` | Validates array of tags against rules (length, charset, uniqueness). Returns `(is_valid, error_message, normalized_tags)` |
| `get_workspace_tags(user_id, group_id, public_workspace_id)` | Returns all tags with document counts and colors, sorted by count desc then name asc. Includes defined-but-unused tags with count 0 |
| `get_default_tag_color(tag_name)` | Generates consistent color from 10-color palette using character sum hash |
| `get_or_create_tag_definition(user_id, tag_name, workspace_type, color, group_id, public_workspace_id)` | Creates tag definition if it does not exist; stores in appropriate location |
| `propagate_tags_to_chunks(document_id, tags, user_id, group_id, public_workspace_id)` | Updates all chunks for a document with new tags via `update_chunk_metadata()` |

### Color Palette

The default 10-color palette for automatic tag color assignment:

| Color | Hex Code |
|-------|----------|
| Blue | `#3b82f6` |
| Green | `#10b981` |
| Amber | `#f59e0b` |
| Red | `#ef4444` |
| Purple | `#8b5cf6` |
| Pink | `#ec4899` |
| Cyan | `#06b6d4` |
| Lime | `#84cc16` |
| Orange | `#f97316` |
| Indigo | `#6366f1` |

Colors are assigned deterministically using `sum(ord(c) for c in tag_name) % 10`.

### API Endpoints

The same 5 endpoint patterns are replicated across all three workspace types:

#### Personal Workspace (route_backend_documents.py)

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/api/documents/tags` | List all tags with document counts and colors |
| POST | `/api/documents/tags` | Create a new tag definition with optional color |
| POST | `/api/documents/bulk-tag` | Bulk tag operation on multiple documents |
| PATCH | `/api/documents/tags/<tag_name>` | Rename tag or change color |
| DELETE | `/api/documents/tags/<tag_name>` | Delete tag from all documents and definitions |

#### Group Workspace (route_backend_group_documents.py)

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/api/group_documents/<group_id>/tags` | List group tags with counts |
| POST | `/api/group_documents/<group_id>/tags` | Create group tag definition |
| POST | `/api/group_documents/<group_id>/bulk-tag` | Bulk tag group documents |
| PATCH | `/api/group_documents/<group_id>/tags/<tag_name>` | Rename or recolor group tag |
| DELETE | `/api/group_documents/<group_id>/tags/<tag_name>` | Delete group tag |

#### Public Workspace (route_backend_public_documents.py)

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/api/public_workspace_documents/<ws_id>/tags` | List public workspace tags |
| POST | `/api/public_workspace_documents/<ws_id>/tags` | Create public workspace tag |
| POST | `/api/public_workspace_documents/<ws_id>/bulk-tag` | Bulk tag public documents |
| PATCH | `/api/public_workspace_documents/<ws_id>/tags/<tag_name>` | Rename or recolor public tag |
| DELETE | `/api/public_workspace_documents/<ws_id>/tags/<tag_name>` | Delete public workspace tag |

### Bulk Tag Operations

The bulk-tag endpoint supports three actions:

| Action | Behavior |
|--------|----------|
| `add_tags` | Adds specified tags to each document's existing tags (union) |
| `remove_tags` | Removes specified tags from each document |
| `set_tags` | Replaces all tags on each document with the specified set |

**Request Body**:
```json
{
    "document_ids": ["doc-1", "doc-2"],
    "action": "add_tags",
    "tags": ["finance", "q4-report"]
}
```

**Response**: Returns success/error counts per document.

### AI Search Integration

Located in `application/single_app/functions_search.py`:

- `build_tags_filter(tags)` constructs an OData filter clause: `document_tags/any(t: t eq 'tag1') and document_tags/any(t: t eq 'tag2')`
- Uses AND logic: all specified tags must be present on a chunk for it to match
- The `document_tags` field is defined in the AI Search index schemas (`static/json/ai_search-index-user.json`, `ai_search-index-group.json`, `ai_search-index-public.json`)

### Tag Validation Rules

| Rule | Detail |
|------|--------|
| Max length | 50 characters |
| Allowed characters | `[a-z0-9_-]` (lowercase alphanumeric, hyphens, underscores) |
| Normalization | Trimmed and lowercased before storage |
| Duplicates | Silently deduplicated within a single tags array |
| Empty tags | Silently skipped |

## File Structure

| File | Purpose |
|------|---------|
| `application/single_app/functions_documents.py` (lines 6250-6558) | Core tag CRUD and chunk propagation functions |
| `application/single_app/functions_search.py` | `build_tags_filter()` for OData query construction |
| `application/single_app/route_backend_documents.py` (lines 753-1280) | Personal workspace tag API routes |
| `application/single_app/route_backend_group_documents.py` (lines 966-1400) | Group workspace tag API routes |
| `application/single_app/route_backend_public_documents.py` (lines 459-890) | Public workspace tag API routes |
| `application/single_app/static/json/ai_search-index-user.json` | AI Search index schema with `document_tags` field |
| `application/single_app/static/json/ai_search-index-group.json` | Group AI Search index schema |
| `application/single_app/static/json/ai_search-index-public.json` | Public AI Search index schema |

## Usage Instructions

### Creating Tags

1. Navigate to the workspace (personal, group, or public)
2. Open the tag management modal (via grid view or bulk tag button)
3. Enter a tag name and optionally select a color
4. Click Create - the tag definition is stored immediately

### Applying Tags to Documents

- **Single document**: Open the tag management modal for a specific document, select tags, and apply
- **Bulk tagging**: Select multiple documents via checkboxes, click the bulk tag button, choose an action (add/remove/set), select tags, and apply

### Tag Filtering in Chat

When tags are selected in the chat tag filter dropdown, only documents matching ALL selected tags are included in AI Search results. See `CHAT_DOCUMENT_AND_TAG_FILTERING.md` for details.

## Testing and Validation

- **Tag normalization**: Verify uppercase input is normalized to lowercase, whitespace is trimmed
- **Validation edge cases**: Tags with special characters are rejected, tags exceeding 50 chars are rejected
- **Cross-workspace isolation**: Personal tags do not appear in group workspaces and vice versa
- **Chunk propagation**: After tagging a document, verify all chunks have updated `document_tags` field
- **AI Search filtering**: Verify that searching with tag filters returns only documents with matching tags
- **Bulk operations**: Apply tags to multiple documents, verify all are updated, check error handling for documents that fail
- **Tag rename**: Rename a tag and verify all documents and chunks reflect the new name
- **Tag deletion**: Delete a tag and verify it is removed from all documents, chunks, and tag definitions
