---
layout: page
title: "v0.239.001 Release"
description: "Overview of new features and improvements in v0.239.001"
section: "Latest Release"
---

This release introduces conversation export capabilities, retention policy management, enhanced workspace controls, and a comprehensive document tagging system.

## New Features

### Conversation Export

Export one or multiple conversations from the Chat page in JSON or Markdown format. A guided wizard walks you through format selection, packaging options, and download. Sensitive internal metadata is automatically stripped for security.

[Read the full guide]({{ '/latest-release/export-conversation/' | relative_url }})

### Retention Policy UI

Configure conversation and document retention periods directly from the workspace and group management pages. Choose from preset retention periods ranging from 7 days to 10 years, use the organization default, or disable automatic deletion entirely.

### Owner-Only Group Agent Management

New admin setting to restrict group agent and action management (create, edit, delete) to only the group Owner role. When enabled, group Admins and other roles are restricted to read-only access. Backend enforcement returns 403 for unauthorized operations.

### Enforce Workspace Scope Lock

New admin setting to control whether users can unlock workspace scope in chat conversations. When enabled, workspace scope automatically locks after the first AI search and users cannot unlock it, preventing accidental cross-contamination between data sources.

### Document Tag System

Comprehensive tag management system for organizing documents across personal, group, and public workspaces. Includes color-coded tags from a 10-color default palette, full CRUD API, bulk tag operations, and AI Search integration for tag-based filtering during hybrid search.

### Workspace Folder View

Toggle between traditional list view and folder-based grid view for workspace documents. Tag folders display document count and color coding, with drill-down navigation, in-folder search, and configurable page sizes. View preference is saved automatically.

### Multi-Workspace Scope Management

Select from personal, multiple group, and multiple public workspaces simultaneously in the chat interface. Includes hierarchical scope dropdown with checkbox multi-selection and per-conversation scope locking that freezes workspace selection after the first AI search.

### Chat Document and Tag Filtering

Checkbox-based multi-document and multi-tag filtering in the chat interface, replacing the legacy single-document dropdown. Each document is labeled with its source workspace, and tags load dynamically across all selected scopes.

## Bug Fixes

- **Citation Parsing** -- Fixed edge cases where page range references failed to generate correct clickable links when not all pages had explicit reference IDs.
- **Public Workspace Activation** -- Fixed 403 error when non-owner users tried to activate a public workspace for chat.

---

For complete technical details, see the [Release Notes]({{ '/explanation/release_notes/' | relative_url }}).
