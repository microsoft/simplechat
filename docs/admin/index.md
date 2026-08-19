---
layout: page
title: "Administration"
description: "Admin settings guide organized by the 18 SimpleChat settings tabs."
section: "Administration"
audience: admin
admin_tab: index
---

## Administration settings guide

Use these pages when configuring SimpleChat from **Admin Settings**. Each page follows one tab in the application and explains what the settings control, why they matter, common tasks, and related pages.

## Start here

For a first-time deployment, configure the tabs in this order: **General**, **AI Models**, **Search and Extract**, **Workspaces**, **Citations**, **Safety**, **Security**, **Agents**, **Scale**, then the operational tabs such as **Logging**, **Control Center**, **File Sync**, **Governance**, and **Backup, Migrate & Restore**.

## Settings tabs

| Tab | What it controls | Link |
| --- | --- | --- |
| General | Controls branding, home page copy, navigation defaults, user notices, health checks, support menu entries, external links, and global app behavior. | [General settings]({{ '/admin/general/' | relative_url }}) |
| AI Models | Controls chat, embedding, image generation, and multi-endpoint model routing for the application. | [AI Models settings]({{ '/admin/ai-models/' | relative_url }}) |
| Search and Extract | Controls retrieval, web search, URL access, Deep Research, extraction services, chunking, video processing, and speech features. | [Search and Extract settings]({{ '/admin/search-extract/' | relative_url }}) |
| Workspaces | Controls personal, group, and public workspace availability, downloads, workflows, file uploads, metadata, classification, retention, and agreements. | [Workspaces settings]({{ '/admin/workspaces/' | relative_url }}) |
| File Sync | Controls file sync availability, visible connector types, per-scope sync policy, source limits, and source-management access. | [File Sync settings]({{ '/admin/file-sync/' | relative_url }}) |
| Global Identities | Provides the administration surface for shared identity mappings used by workspace connectors and sync sources. | [Global Identities settings]({{ '/admin/workspace-identities/' | relative_url }}) |
| Citations | Controls enhanced citation storage, tabular previews, and large tabular run safeguards. | [Citations settings]({{ '/admin/citation/' | relative_url }}) |
| Safety | Controls Azure Content Safety, user feedback, desktop notifications, review-role requirements, and conversation archiving. | [Safety settings]({{ '/admin/safety/' | relative_url }}) |
| Security | Controls Key Vault secret storage and SimpleChat secret expiration reminder tracking. | [Security settings]({{ '/admin/security/' | relative_url }}) |
| Agents | Controls document actions, agent availability, agent marketplace copy, orchestration, workspace agent/action permissions, core actions, and inbound MCP. | [Agents settings]({{ '/admin/agents/' | relative_url }}) |
| Scale | Controls Redis, conversation and document-access caches, Cosmos maintenance and throughput automation, and Front Door support. | [Scale settings]({{ '/admin/scale/' | relative_url }}) |
| Control Center | Controls Control Center refresh scheduling and role-gated access to Control Center views. | [Control Center settings]({{ '/admin/control-center-config/' | relative_url }}) |
| Backup, Migrate & Restore | Controls scheduled backup settings and the operational tools for migration, restore, backup inventory, job history, and Cosmos JSON editing. | [Backup, Migrate & Restore settings]({{ '/admin/data-management/' | relative_url }}) |
| Governance | Controls governance review for personal, group, and global endpoints, agents, actions, and MCP destinations. | [Governance settings]({{ '/admin/governance/' | relative_url }}) |
| Logging | Controls Application Insights logging, temporary debug logging, file-processing logs, and stored-log cleanup. | [Logging settings]({{ '/admin/logging/' | relative_url }}) |
| Send Feedback | Provides admin-side forms for reporting bugs and feature requests to the SimpleChat team. | [Send Feedback settings]({{ '/admin/send-feedback/' | relative_url }}) |
| Custom Pages | Controls whether admin-authored custom pages appear in navigation and how they are grouped. | [Custom Pages settings]({{ '/admin/custom-pages/' | relative_url }}) |
| Latest Features New | Provides a feature-rollout review surface and mirrors a small set of related controls from other tabs. | [Latest Features New settings]({{ '/admin/latest-features/' | relative_url }}) |
