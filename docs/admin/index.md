---
layout: page
title: "Administration"
description: "Admin settings guide organized by the grouped SimpleChat Admin Settings information architecture."
section: "Administration"
audience: admin
admin_tab: index
---

## Administration settings guide

Use these pages when configuring SimpleChat from **Admin Settings**. The application now uses **group → tab → section** navigation, so each page below covers one group and each tab has a stable heading anchor.

## Start here

For a first-time deployment, configure **Appearance**, **AI Models**, **Knowledge**, **Workspaces**, **Chat**, **Security**, and **Agents & Actions** first. Then review **Scale**, **Operations**, **Governance**, **Data Lifecycle**, **Backup & Recovery**, **Workflow**, and **Help** as the deployment moves into operations.

## Settings groups

| Group | What it controls | Tabs | Link |
| --- | --- | --- | --- |
| Appearance | Appearance controls the public-facing identity of SimpleChat: branding, landing copy, banners, user notices, terms, custom pages, and external navigation links. | `branding`, `notices`, `custom-pages` | [Appearance settings]({{ '/admin/appearance/' | relative_url }}) |
| Chat | Chat controls the conversation surface: file uploads, processing indicators, drawers, history, feedback, notifications, citations, and the default prompt. | `chat-experience`, `feedback-alerts`, `citation` | [Chat settings]({{ '/admin/chat/' | relative_url }}) |
| AI Models | AI Models configures chat, embedding, image generation, APIM, multi-endpoint routing, and model endpoint identity behavior. | `model-endpoints`, `embeddings`, `image-generation` | [AI Models settings]({{ '/admin/ai-models/' | relative_url }}) |
| Agents & Actions | Agents & Actions controls the Semantic Kernel runtime, agent marketplace presentation, document actions, built-in actions, workspace permissions, orchestration, and inbound MCP. | `agents`, `actions`, `inbound-mcp` | [Agents & Actions settings]({{ '/admin/agents-actions/' | relative_url }}) |
| Workspaces | Workspaces controls personal, group, and public workspace availability, file downloads, sharing policy, file-size limits, and global identities. | `workspace-types`, `files-sharing`, `workspace-identities` | [Workspaces settings]({{ '/admin/workspaces/' | relative_url }}) |
| Workflow | Workflow centralizes task sequence, assignment, and approval behavior used across SimpleChat surfaces. | `workflow` | [Workflow settings]({{ '/admin/workflow/' | relative_url }}) |
| Knowledge | Knowledge controls web research, URL access, Azure AI Search, extraction, chunking, multimodal processing, audio/video processing, and file sync. | `web-research`, `search-index`, `extraction`, `audio-video`, `file-sync` | [Knowledge settings]({{ '/admin/knowledge/' | relative_url }}) |
| Security | Security covers access roles, Key Vault integration, Content Safety, idle session behavior, and Front Door-aware network URLs. | `access-roles`, `secrets`, `content-safety`, `session`, `network` | [Security settings]({{ '/admin/security/' | relative_url }}) |
| Governance | Governance controls review policy for personal, group, and global endpoints, agents, actions, and MCP destinations. | `feature-governance`, `governance-policies`, `mcp-governance` | [Governance settings]({{ '/admin/governance/' | relative_url }}) |
| Data Lifecycle | Data Lifecycle groups retention, classification, and conversation archiving decisions. | `retention`, `classification`, `archiving` | [Data Lifecycle settings]({{ '/admin/data-lifecycle/' | relative_url }}) |
| Backup & Recovery | Backup & Recovery contains backup readiness, scheduled backups, migration, restore, backup inventory, job history, and Cosmos JSON repair tools. | `backup`, `migrate`, `restore`, `cosmos-editor`, `jobs` | [Backup & Recovery settings]({{ '/admin/backup-recovery/' | relative_url }}) |
| Scale | Scale covers Redis, conversation and search caches, document access indexing, Cosmos maintenance, and Cosmos throughput automation. | `redis-caching`, `cosmos` | [Scale settings]({{ '/admin/scale/' | relative_url }}) |
| Operations | Operations collects Control Center access, refresh behavior, Application Insights, debug logging, file-processing logs, health checks, and Swagger documentation. | `control-center-config`, `logging` | [Operations settings]({{ '/admin/operations/' | relative_url }}) |
| Help | Help controls end-user support navigation, Send Feedback destinations, and Latest Features cards. | `support-menu`, `send-feedback`, `latest-features` | [Help settings]({{ '/admin/help/' | relative_url }}) |
