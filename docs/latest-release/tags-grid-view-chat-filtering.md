---
layout: latest-release-feature
title: "Tags, Grid View, and Chat Filtering"
description: "How to create tags, organize documents in grid view, and filter by tags in chat"
section: "Latest Release"
---

Organize workspace documents with color-coded tags, browse them visually in a folder-based grid view, and filter by tags when chatting. These features work together across personal, group, and public workspaces.

## Managing Tags

Click the **Manage Tags** button on any workspace's Your Documents tab to open the tag management modal. From here you can create new tags with a custom name and color, edit existing tags, or delete them.

Tag names support lowercase letters, numbers, hyphens, and underscores. Colors can be selected from a default palette or customized via the color picker.

<img src="{{ '/images/feature-tags-manage_workspace_tags.png' | relative_url }}" alt="Manage Workspace Tags modal with tag list and color picker" style="width: 70%;" />

## Assigning Tags to Documents

### Selecting Documents

In the list view, click the ellipsis menu on any document and choose **Select** to enter selection mode. Check the documents you want to tag, then click **Tag Assignment** in the selection toolbar.

<img src="{{ '/images/feature-multi_document_select-assign_tags.png' | relative_url }}" alt="Document list with multi-select mode and Tag Assignment toolbar button" style="width: 70%;" />

### Tag Assignment Modal

The Tag Assignment modal shows the number of selected documents and lets you choose an action: **Add Tags** (append to existing), **Replace Tags**, or **Remove Tags**. Available workspace tags are displayed as clickable badges.

<img src="{{ '/images/feature-multi_document_select-view_tag_assignment.png' | relative_url }}" alt="Tag Assignment for Selected Documents modal" style="width: 70%;" />

### Selecting Tags

Click **Assign Tag** to open the tag picker. Each tag shows the number of documents currently using it. Check the tags you want to apply, then click **Done** to confirm your selection.

<img src="{{ '/images/feature-multi_document_select-manage_tag_assignment.png' | relative_url }}" alt="Select Tags overlay with checkbox list and document counts" style="width: 70%;" />

### Tagging via Document Metadata

You can also assign tags to individual documents through the **Edit Metadata** modal. Click the ellipsis menu on any document and choose **Edit Metadata**. The modal includes a **Tags** section where assigned tags appear as removable badges. Click **Manage Tags** to open the tag picker and select tags for the document.

<img src="{{ '/images/feature-document_metadata.png' | relative_url }}" alt="Edit Document Metadata modal showing tags, keywords, and other fields" style="width: 70%;" />

The tag picker shows all workspace tags with document counts. Check the tags you want to assign, then click **Done** to return to the metadata editor.

<img src="{{ '/images/feature-document_metadata-manage_tags.png' | relative_url }}" alt="Select Tags overlay within Edit Document Metadata modal" style="width: 70%;" />

## Grid View

Toggle between **List** and **Grid** view using the buttons above the document table. Grid view displays documents organized into color-coded tag folders, each showing the number of files inside. Special folders include **Unclassified** and **Untagged** for documents without classifications or tags.

<img src="{{ '/images/feature-grid_view-workspace.png' | relative_url }}" alt="Grid view showing color-coded tag folders with file counts" style="width: 70%;" />

## Tag Folder Actions

Click the ellipsis menu on any tag folder to access folder-level actions: **Chat** with all documents in the folder, **Rename Tag**, **Change Color**, or **Delete Tag**.

<img src="{{ '/images/feature-grid_view-chat_with_tagged_documents.png' | relative_url }}" alt="Tag folder context menu with Chat, Rename, Change Color, and Delete options" style="width: 70%;" />

## Browsing Tag Folders

Click a tag folder to drill down into its contents. A breadcrumb trail shows your location (e.g., **All / tag-a**), and you can search within the folder or adjust the page size. Click **All** in the breadcrumb to return to the folder overview.

<img src="{{ '/images/feature-grid_view-folder_view_when_selecting_tag.png' | relative_url }}" alt="Drill-down view inside tag-a folder showing 4 documents" style="width: 70%;" />

Classification folders work the same way. Clicking a classification folder like **Public** shows only documents with that classification.

<img src="{{ '/images/feature-grid_view-folder_view_when_selecting_document_classification_tag.png' | relative_url }}" alt="Drill-down view inside Public classification folder showing 1 document" style="width: 70%;" />

## Chat Tag and Document Filtering

### Filtering by Tag

In the chat interface, use the **Tags** dropdown to filter documents by tag before starting a conversation. The dropdown shows all tags across your selected workspace scopes with document counts. A **Classifications** section at the bottom lets you filter by document classification as well.

<img src="{{ '/images/feature-tags-showing_tag_selection_in_chat.png' | relative_url }}" alt="Chat interface with Tags dropdown showing tag checkboxes and counts" style="width: 70%;" />

### Filtered Document List

After selecting a tag, the **Documents** dropdown updates to show only documents matching the selected tags. Each document is labeled with its source workspace (e.g., [Personal]) for clarity when multiple workspaces are in scope.

<img src="{{ '/images/feature-tags-selected_tags_in_chat_filter_document_list.png' | relative_url }}" alt="Documents dropdown showing filtered documents labeled with source workspace" style="width: 70%;" />

## Notes

- Tags are workspace-scoped and available across personal, group, and public workspaces
- Grid view preference is saved automatically per workspace
- Tag filtering in chat works across all selected workspace scopes simultaneously
- Documents in the chat dropdown are labeled with their source workspace for disambiguation
