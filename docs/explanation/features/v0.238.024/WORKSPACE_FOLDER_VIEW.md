# WORKSPACE_FOLDER_VIEW.md

**Feature**: Workspace Folder View (Grid View)
**Version**: v0.238.024
**Dependencies**: Document Tag System, Bootstrap 5

## Overview and Purpose

The Workspace Folder View introduces a grid-based alternative to the traditional document list view. Documents are organized into visual "folders" based on their tags and classifications, providing an intuitive file-manager-style interface. Users can toggle between list and grid views, drill into folders to see their contents, and manage tags directly from the grid interface. This feature is available across personal, group, and public workspaces.

## Key Features

- **View Toggle**: Switch between list view and grid view via radio buttons
- **Tag Folders**: Color-coded cards displaying tag name, document count, and folder icon
- **Special Folders**: "Untagged" folder for documents with no tags, "Unclassified" for documents without classification (when classification is enabled)
- **Classification Folders**: Classification categories displayed as folder cards when document classification is enabled
- **Folder Drill-Down**: Click a folder to see its contents with breadcrumb navigation
- **In-Folder Search**: Search within folder contents by filename or title
- **Configurable Page Sizes**: 10, 20, or 50 items per page
- **Sort Controls**: Sort grid overview by name or file count; sort folder contents by filename or title
- **View Persistence**: Selected view saved to localStorage
- **Tag Management Modal**: Step-through workflow for creating, editing, renaming, recoloring, and deleting tags
- **Bulk Tag Management**: Select multiple documents and apply tag operations

## Technical Specifications

### Architecture Overview

The folder view is built as two JavaScript modules that work alongside the existing workspace documents module:

1. **workspace-tags.js** (1257 lines): Grid rendering, folder drill-down, breadcrumb navigation, pagination, tag filtering, and view switching
2. **workspace-tag-management.js** (732 lines): Tag management modal with step-through workflow, color picker, create/edit/delete operations

### State Variables (workspace-tags.js)

| Variable | Default | Purpose |
|----------|---------|---------|
| `workspaceTags` | `[]` | All available workspace tags with colors |
| `currentView` | `'list'` | Active view mode: `'list'` or `'grid'` |
| `selectedTagFilter` | `[]` | Currently selected tag filters |
| `currentFolder` | `null` | Currently viewed folder (`null` = overview) |
| `currentFolderType` | `null` | Folder type: `null`, `'tag'`, or `'classification'` |
| `folderCurrentPage` | `1` | Current page in folder drill-down |
| `folderPageSize` | `10` | Items per page (10, 20, or 50) |
| `gridSortBy` | `'count'` | Grid overview sort field: `'count'` or `'name'` |
| `gridSortOrder` | `'desc'` | Grid overview sort direction |
| `folderSortBy` | `'_ts'` | Folder contents sort field |
| `folderSortOrder` | `'desc'` | Folder contents sort direction |
| `folderSearchTerm` | `''` | Search term within folder drill-down |

### Initialization Flow

1. `initializeTags()` is called on page load
2. Loads workspace tags via `loadWorkspaceTags()` (fetches from `/api/documents/tags`)
3. Sets up view switcher event listeners on radio buttons
4. Sets up tag filter dropdown
5. Sets up bulk tag management button
6. Wires grid sort buttons and page-size select
7. Restores view preference from localStorage

### View Switching

```
switchView(view):
  1. Update currentView state
  2. Toggle visibility: #documents-list-view vs #documents-grid-view
  3. Show/hide #grid-controls-bar
  4. Reset folder drill-down (currentFolder = null)
  5. If grid: renderGridView()
  6. Save preference to localStorage ('personalWorkspaceViewPreference')
```

### Grid Rendering

The `renderGridView()` function builds the folder card layout:

- Fetches document counts per tag and classification
- Sorts folders by `gridSortBy`/`gridSortOrder`
- Renders each tag as a card with:
  - Colored folder icon (using tag's hex color)
  - Tag name (truncated, max-width: 120px)
  - Document count
  - Context menu (rename, change color, delete)
- Adds special "Untagged" folder (count of documents with empty tags array)
- Adds classification folders when classification is enabled
- Adds "Unclassified" folder for documents without classification

### Folder Drill-Down

When a folder card is clicked:

1. Sets `currentFolder` to the tag/classification name
2. Sets `currentFolderType` to `'tag'` or `'classification'`
3. Calls `renderFolderContents(tagName)`
4. Shows breadcrumb navigation: "All / [Folder Name] (N files)"
5. Displays a searchable, sortable, paginated table of documents
6. Each row includes: status indicator, filename, title, and action buttons (Chat, Edit, Delete, Share)

### Tag Management Modal

The tag management modal (workspace-tag-management.js) provides a step-through workflow:

| Step | Purpose |
|------|---------|
| Step 1: Manage | Create new tags, rename, recolor, or delete existing tags |
| Step 2: Select | Pick tags to apply to document(s) from the tag list |
| Step 3: Apply | Execute bulk-tag API call and refresh the view |

**Context modes**:
- `'document'`: Managing tags for a single document
- `'bulk'`: Managing tags for multiple selected documents

### CSS Styling

Tag folder cards are styled in workspace template files:

- `.tag-folder-card`: Interactive card with hover shadow effect, cursor pointer
- `.tag-folder-icon`: Large icon area (font-size: 2.5rem)
- `.tag-folder-name`: Truncated text with ellipsis (max-width: 120px)
- `.tag-folder-count`: Gray text showing document count
- `.tag-folder-actions`: Hidden action menu revealed on card hover

### Group and Public Workspace Support

- **Group workspaces**: Tag management UI is implemented inline in `templates/group_workspaces.html` with equivalent grid view and tag management functionality
- **Public workspaces**: Tag management is in `static/js/public/public_workspace.js` with matching grid/folder view features

## File Structure

| File | Purpose |
|------|---------|
| `static/js/workspace/workspace-tags.js` (1257 lines) | Grid view rendering, folder drill-down, pagination, tag filtering |
| `static/js/workspace/workspace-tag-management.js` (732 lines) | Tag management modal, create/edit/delete workflow, color picker |
| `static/js/workspace/workspace-utils.js` | Shared utilities (`escapeHtml`) |
| `templates/workspace.html` (lines 475-597) | View toggle radio buttons, grid container, grid controls bar, CSS styles |
| `templates/group_workspaces.html` | Inline JS for group workspace tag/grid view |
| `static/js/public/public_workspace.js` | Public workspace tag/grid view |
| `templates/public_workspaces.html` | Public workspace template with grid view markup |

## Usage Instructions

### Switching Views

1. In the personal workspace, locate the view toggle above the document list
2. Click "List View" for the traditional table layout or "Grid View" for the folder layout
3. The selected view is remembered across sessions via localStorage

### Navigating Folders

1. In grid view, click any folder card to drill down into its contents
2. Use the breadcrumb bar to navigate back to the overview ("All")
3. Use the search bar within a folder to filter by filename or title
4. Adjust page size (10, 20, 50) and use pagination controls as needed

### Managing Tags from Grid View

1. Hover over a folder card to reveal the context menu (three-dot icon)
2. Choose "Rename" to change the tag name, "Change Color" to pick a new color, or "Delete" to remove the tag
3. Alternatively, click "Manage Tags" button to open the full tag management modal

### Bulk Tagging

1. In list view, select multiple documents via checkboxes
2. Click the "Tag" bulk action button
3. In the tag management modal, create or select tags, then choose an action (add, remove, or set)
4. Confirm to apply the operation to all selected documents

## Testing and Validation

- **View toggle**: Verify switching between list and grid preserves document state
- **LocalStorage persistence**: Verify view preference survives page reload
- **Grid sort**: Verify sorting by name and count with ascending/descending toggle
- **Folder drill-down**: Click a folder, verify correct documents displayed, verify breadcrumb navigation works
- **In-folder search**: Type a search term, verify results filter correctly
- **Pagination**: Navigate between pages, verify page size changes reset to page 1
- **Special folders**: Verify "Untagged" shows correct count, "Unclassified" only appears when classification is enabled
- **Tag management modal**: Create, rename, recolor, delete tags; verify grid view updates
- **Group/Public workspaces**: Verify equivalent functionality in group and public workspace views
