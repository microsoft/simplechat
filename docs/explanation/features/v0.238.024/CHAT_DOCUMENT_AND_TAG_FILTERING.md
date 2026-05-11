# CHAT_DOCUMENT_AND_TAG_FILTERING.md

**Feature**: Chat Document and Tag Filtering
**Version**: v0.238.024
**Dependencies**: Document Tag System, Multi-Workspace Scope Management, Azure AI Search

## Overview and Purpose

Chat Document and Tag Filtering replaces the legacy single-document dropdown in the chat interface with a checkbox-based multi-document selection system and adds multi-tag filtering. Users can select specific documents and tags to constrain which content is included in AI Search results during chat. Both features feed into the backend search pipeline to produce more targeted and relevant responses.

## Key Features

### Multi-Document Selection
- **Checkbox Dropdown**: Custom dropdown with checkboxes for each document, replacing the standard select element
- **"All Documents" Option**: Clears all individual selections to search across all documents in scope
- **Document Search**: Real-time text search within the dropdown to find specific documents
- **Selected Count Display**: Button text shows "All Documents" or "N Documents" based on selections
- **Scope Indicators**: Each document labeled with its source: `[Personal]`, `[Group: Name]`, or `[Public: Name]`
- **Hidden Select Sync**: Maintains a hidden `<select>` element for backward compatibility with existing code

### Tag Filtering
- **Multi-Tag Selection**: Checkboxes for selecting multiple tags simultaneously
- **Classification Support**: Separate classification section with color-coded entries when document classification is enabled
- **"Clear All" Option**: Quick reset for tag and classification filters
- **Dynamic Tag Loading**: Tags load based on currently selected scope workspaces (via `loadTagsForScope()`)
- **Merged Tag Counts**: Tag counts aggregated from all selected scopes (personal + group + public)
- **DOM-Based Filtering**: Non-matching document items are removed from the DOM (not hidden via CSS), following project conventions against `display:none`

## Technical Specifications

### Architecture Overview

The document and tag filtering logic resides in `chat-documents.js`. Document selections and tag filters are sent alongside chat messages to the backend, which constructs OData filter clauses for Azure AI Search.

**Key DOM elements**:
- `#document-select`: Hidden `<select>` element for backward compatibility
- `#document-dropdown-button` / `#document-dropdown-items`: Custom checkbox dropdown
- `#document-search-input`: Search input within document dropdown
- `#tags-dropdown-button` / `#tags-dropdown-items`: Tag filter checkbox dropdown
- `#chat-tags-filter`: Container for the tags filter dropdown

**State**:
- `tagFilteredOutItems`: Array of `{element, nextSibling}` objects storing DOM elements removed by tag filtering (enables restoration when filters change)
- `personalDocs`, `groupDocs`, `publicDocs`: In-memory arrays of loaded documents per scope

### Document Selection Flow

1. User selects scope workspaces (see `MULTI_WORKSPACE_SCOPE_MANAGEMENT.md`)
2. `loadAllDocs()` fetches documents from all selected scopes via parallel API calls
3. Documents are rendered as checkbox items in the custom dropdown with scope labels
4. User checks/unchecks documents; "All Documents" remains checked when no individual items are selected
5. On chat send, `getSelectedDocumentIds()` returns the IDs of checked documents (or empty array for "all")

### Tag Filtering Flow

1. When scope selection changes, `loadTagsForScope()` fetches tags from each selected workspace
2. Tags are merged: duplicate tag names have their counts summed across workspaces
3. Tags are rendered as checkbox items sorted by count (descending)
4. When classification is enabled, classification categories are listed in a separate section with color dots
5. When a tag is checked/unchecked:
   - Checked tags: Documents not matching any checked tag are removed from the DOM (`tagFilteredOutItems`)
   - Unchecked tag: Previously removed items are restored to the DOM at their original positions
6. The removal is DOM-level (elements removed from parent), not CSS-based, per project conventions

### Backend Integration

When a chat message is sent, the following parameters are included in the request body:

| Parameter | Type | Purpose |
|-----------|------|---------|
| `selected_document_ids` | `string[]` | IDs of selected documents (empty = all) |
| `tags` | `string[]` | Selected tag names for filtering |
| `selected_classifications` | `string[]` | Selected classification categories |

**Backend processing** (route_backend_chats.py):

1. Receives `tags` and `selected_document_ids` from the request
2. Calls `build_tags_filter(tags)` to generate an OData clause: `document_tags/any(t: t eq 'tag1') and document_tags/any(t: t eq 'tag2')`
3. Combines tag filter with document ID filter: `(document_id eq 'id1' or document_id eq 'id2')`
4. Passes combined filter to `hybrid_search()` for Azure AI Search execution

### Search Integration (functions_search.py)

The `build_tags_filter()` function constructs OData filter expressions:

- **AND logic**: All selected tags must be present on a chunk for it to match
- **Format**: `document_tags/any(t: t eq 'tag-name')`
- **Combined with document filter**: Both filters are ANDed together in the final OData `$filter` clause
- **Empty tags array**: No tag filter is applied (returns all documents in scope)

### Dynamic Tag Loading

`loadTagsForScope()` operation:

1. Determines which scopes are selected (personal, group IDs, public workspace IDs)
2. Fetches tags from each scope's API endpoint in parallel:
   - `GET /api/documents/tags` (personal)
   - `GET /api/group_documents/{id}/tags` (per group)
   - `GET /api/public_workspace_documents/{id}/tags` (per public workspace)
3. Merges results: same tag names across scopes have counts summed
4. Renders merged tag list in the dropdown
5. Preserves previously selected tags if they still exist in the merged list

## File Structure

| File | Purpose |
|------|---------|
| `static/js/chat/chat-documents.js` (lines 500-1000) | Document dropdown and tag filter rendering, DOM-based filtering |
| `static/js/chat/chat-messages.js` | Reads selected documents and tags when building chat request |
| `application/single_app/functions_search.py` (lines 76-150) | `build_tags_filter()` for OData construction |
| `application/single_app/route_backend_chats.py` (lines 63-143) | Receives tag/document params, builds search filters |
| `templates/chats.html` | HTML markup for document dropdown, tag filter, and search container |

## Usage Instructions

### Selecting Documents

1. Click the Documents dropdown in the search container above the chat input
2. Use the search box to find specific documents by name
3. Check documents you want to include in AI Search results
4. The button label updates to show the count ("3 Documents")
5. Check "All Documents" to reset and include everything in scope

### Filtering by Tags

1. Click the Tags dropdown in the search container
2. Check one or more tags to filter the document list
3. Documents without any of the checked tags are removed from the document dropdown
4. Classification categories (if enabled) appear in a separate section with color dots
5. Click "Clear All" to reset all tag and classification filters

### Combined Usage

1. First select your workspace scope (Personal, Groups, Public)
2. Then optionally filter by tags to narrow the document list
3. Then optionally select specific documents from the filtered list
4. Send your message — AI Search will constrain results to match all three dimensions (scope + tags + documents)

## Testing and Validation

- **Multi-document select**: Check multiple documents, verify IDs are sent in chat request
- **"All Documents" toggle**: Verify checking "All Documents" clears individual selections and vice versa
- **Document search**: Type in search box, verify dropdown filters to matching documents
- **Tag filtering**: Select tags, verify non-matching documents are removed from dropdown (not just hidden)
- **Tag filter restoration**: Uncheck a tag, verify previously removed documents reappear at correct DOM positions
- **Dynamic tag loading**: Change scope selection, verify tags reload with updated counts
- **Cross-scope tag merging**: Select personal and group scopes with overlapping tag names, verify counts are summed
- **Classification filtering**: Select a classification, verify only matching documents remain
- **Backend integration**: Verify tags and document IDs are included in the chat API request body
- **OData filter**: Verify `build_tags_filter()` produces correct AND-based OData expressions
- **Empty selections**: Verify sending with no tags or documents selected searches all documents in scope
