---
layout: page
title: "Latest Release Highlights"
description: "Current feature guides with previous release highlights kept for reference"
section: "Latest Release"
---

This page tracks the current set of guides behind the in-app **Latest Features** experience and keeps the earlier `v0.239.001` content available below as **Previous Release Features**.

## Current Release Features

These guides map to the feature set currently highlighted in the app for end users.

### Guided Tutorials

Step-by-step walkthroughs help users discover core chat, workspace, and onboarding flows faster, and each user can now hide the launchers when they no longer need them.

[Read the full guide]({{ '/latest-release/guided-tutorials/' | relative_url }})

### Background Chat

Long-running chat requests can finish in the background while users continue working elsewhere in the app.

[Read the full guide]({{ '/latest-release/background-chat/' | relative_url }})

### GPT Selection

Teams can expose better model-selection options so users can choose the best experience for a task.

[Read the full guide]({{ '/latest-release/gpt-selection/' | relative_url }})

### Tabular Analysis

Spreadsheet and table workflows continue to improve for exploration, filtering, and grounded follow-up questions.

[Read the full guide]({{ '/latest-release/tabular-analysis/' | relative_url }})

### Citation Improvements

Enhanced citations give users better source traceability, document previews, and history-aware grounding.

[Read the full guide]({{ '/latest-release/citation-improvements/' | relative_url }})

### Document Versioning

Document revision visibility has improved so users can work with the right version of shared content.

[Read the full guide]({{ '/latest-release/document-versioning/' | relative_url }})

### Summaries and Export

Conversation summaries and export workflows continue to expand for reporting and follow-up sharing.

[Read the full guide]({{ '/latest-release/summaries-and-export/' | relative_url }})

### Agent Operations

Agent creation, organization, and operational controls keep getting smoother for advanced scenarios.

[Read the full guide]({{ '/latest-release/agent-operations/' | relative_url }})

### AI Transparency

Thought and reasoning transparency options help users better understand what the assistant is doing.

[Read the full guide]({{ '/latest-release/ai-transparency/' | relative_url }})

### Fact Memory

Profile-based memory now distinguishes always-on Instructions from recall-only Facts so the assistant can carry durable preferences and relevant personal context forward more cleanly.

[Read the full guide]({{ '/latest-release/fact-memory/' | relative_url }})

### Deployment

Deployment guidance and diagnostics keep improving so admins can roll out changes with less guesswork.

[Read the full guide]({{ '/latest-release/deployment/' | relative_url }})

### Redis and Key Vault

Caching and secret-management setup guidance has expanded for more secure and predictable operations.

[Read the full guide]({{ '/latest-release/redis-and-key-vault/' | relative_url }})

### Send Feedback

End users can prepare bug reports and feature requests for their SimpleChat admins directly from the Support menu.

[Read the full guide]({{ '/latest-release/send-feedback/' | relative_url }})

### Support Menu

Admins can surface a dedicated Support menu in navigation with Latest Features and Send Feedback entries for end users.

[Read the full guide]({{ '/latest-release/support-menu/' | relative_url }})

## Previous Release Features

The earlier `v0.239.001` release guides remain available here for reference.

### Conversation Export

Export one or multiple conversations from the Chat page in JSON or Markdown format. A guided wizard walks you through format selection, packaging options, and download. Sensitive internal metadata is automatically stripped for security.

[Read the full guide]({{ '/latest-release/export-conversation/' | relative_url }})

### Retention Policy

Configure conversation and document retention periods directly from the workspace and group management pages. Choose from preset retention periods ranging from 7 days to 10 years, use the organization default, or disable automatic deletion entirely.

[Read the full guide]({{ '/latest-release/retention-policy/' | relative_url }})

### Owner-Only Group Agent Management

New admin setting to restrict group agent and action management (create, edit, delete) to only the group Owner role. When enabled, group Admins and other roles are restricted to read-only access. Backend enforcement returns 403 for unauthorized operations.

### Enforce Workspace Scope Lock

New admin setting to control whether users can unlock workspace scope in chat conversations. When enabled, workspace scope automatically locks after the first AI search and users cannot unlock it, preventing accidental cross-contamination between data sources.

[Read the full guide]({{ '/latest-release/workspace-scope-lock/' | relative_url }})

### Document Tag System

Comprehensive tag management system for organizing documents across personal, group, and public workspaces. Includes color-coded tags from a 10-color default palette, full CRUD API, bulk tag operations, and AI Search integration for tag-based filtering during hybrid search.

[Read the full guide]({{ '/latest-release/tags-grid-view-chat-filtering/' | relative_url }})

### Workspace Folder View

Toggle between traditional list view and folder-based grid view for workspace documents. Tag folders display document count and color coding, with drill-down navigation, in-folder search, and configurable page sizes. View preference is saved automatically.

[Read the full guide]({{ '/latest-release/tags-grid-view-chat-filtering/' | relative_url }})

### Multi-Workspace Scope Management

Select from personal, multiple group, and multiple public workspaces simultaneously in the chat interface. Includes hierarchical scope dropdown with checkbox multi-selection and per-conversation scope locking that freezes workspace selection after the first AI search.

[Read the full guide]({{ '/latest-release/tags-grid-view-chat-filtering/' | relative_url }})

### Chat Document and Tag Filtering

Checkbox-based multi-document and multi-tag filtering in the chat interface, replacing the legacy single-document dropdown. Each document is labeled with its source workspace, and tags load dynamically across all selected scopes.

[Read the full guide]({{ '/latest-release/tags-grid-view-chat-filtering/' | relative_url }})

## Previous Release Bug Fixes

- **Citation Parsing** -- Fixed edge cases where page range references failed to generate correct clickable links when not all pages had explicit reference IDs.
- **Public Workspace Activation** -- Fixed 403 error when non-owner users tried to activate a public workspace for chat.

---

For complete technical details, see the [Release Notes]({{ '/explanation/release_notes/' | relative_url }}).
