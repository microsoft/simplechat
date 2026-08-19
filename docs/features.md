---
layout: page
title: "Features"
description: "A data-driven catalog of SimpleChat capabilities, grouped by operating area and tied to the settings that enable them."
section: "Features"
permalink: /features/
---

SimpleChat capabilities are catalogued from the application surface inventory so every shipped feature toggle is represented once and only once. Use this page to find the capability, understand what it does, and jump to the admin setting that controls it.

This catalog covers **38 capabilities** backed by **111 capability toggles**.

## Chat and retrieval

| Capability | What it does | Who uses it | Default | Enable it in |
| --- | --- | --- | --- | --- |
| [Chat file uploads](/features/chat-file-uploads/) | Lets users attach files directly to a chat so the conversation can use uploaded content as context. | End users | Enabled | [Workspaces](/admin/workspaces/) |
| [Collaborative conversations](/features/collaborative-conversations/) | Allows shared conversation participation so multiple users can work in the same chat context. | End users | Enabled | [Workspaces](/admin/workspaces/) |
| [Conversation productivity controls](/features/conversation-productivity/) | Controls chat navigation, appearance, drawers, notifications, and audio cues around conversation work. | End users | Mixed | [General](/admin/general/) |
| [Deep research and source review](/features/deep-research/) | Adds bounded source-page review and deeper web evidence inspection before web-grounded answers are used. | End users | Mixed | [Search and Extract](/admin/search-extract/) |
| [Enhanced citations](/features/enhanced-citations/) | Adds richer source previews and storage-backed citation rendering for documents used in answers. | End users | Disabled | [Citations](/admin/citation/) |
| [Grounded document search](/features/grounded-document-search/) | Controls Azure AI Search-backed retrieval, cached search results, and mixed-source evidence reuse in chat. | End users | Mixed | [Search and Extract](/admin/search-extract/) |
| [Source history summaries](/features/source-history-summaries/) | Summarizes older conversation context so search and long-running chats can keep useful history. | End users | Disabled | [Search and Extract](/admin/search-extract/) |
| [URL access](/features/url-access/) | Lets chat and workflows fetch approved pasted URLs under admin-controlled limits and domain policy. | End users | Disabled | [Search and Extract](/admin/search-extract/) |
| [Web search](/features/web-search/) | Adds Bing-backed web search through a configured Azure AI Foundry agent for current external information. | End users | Disabled | [Search and Extract](/admin/search-extract/) |

## Documents and workspaces

| Capability | What it does | Who uses it | Default | Enable it in |
| --- | --- | --- | --- | --- |
| [Document access index](/features/document-access-index/) | Maintains a dedicated document-access index for faster authorization-aware document reads and validation. | Operators | Mixed | [Scale](/admin/scale/) |
| [File sync](/features/file-sync/) | Lets enabled workspaces ingest content from configured storage sources instead of relying only on manual uploads. | End users | Mixed | [File Sync](/admin/file-sync/) |
| [Group workspaces](/features/group-workspaces/) | Enables shared group spaces, group creation, and approval-aware file sharing between groups. | End users | Mixed | [Workspaces](/admin/workspaces/) |
| [Personal workspaces](/features/personal-workspace/) | Gives each user a personal document workspace for uploads, tags, prompts, agents, actions, and workflows where enabled. | End users | Enabled | [Workspaces](/admin/workspaces/) |
| [Public workspaces](/features/public-workspaces/) | Publishes approved workspace content to a broader public workspace experience. | End users | Disabled | [Workspaces](/admin/workspaces/) |
| [Retention policies](/features/retention-policies/) | Applies automatic retention rules separately for personal, group, and public workspace content. | Admins | Disabled | [Backup, Migrate & Restore](/admin/data-management/) |

## Media and ingestion

| Capability | What it does | Who uses it | Default | Enable it in |
| --- | --- | --- | --- | --- |
| [Audio and video ingestion](/features/media-file-ingestion/) | Allows audio and video files to be processed into searchable transcript-style content. | End users | Disabled | [Search and Extract](/admin/search-extract/) |
| [Chunk size overrides](/features/chunk-size-overrides/) | Lets admins override default extraction chunk sizes by file type for indexing and retrieval. | Admins | Disabled | [Search and Extract](/admin/search-extract/) |
| [Cross-format document compare](/features/document-compare/) | Compares documents across supported formats, including staged one-to-many comparison behavior. | End users | Disabled | [Search and Extract](/admin/search-extract/) |
| [Document extraction](/features/document-extraction/) | Controls Document Intelligence, enhanced extraction, formulas, and embedded Office image analysis during ingestion. | End users | Mixed | [Search and Extract](/admin/search-extract/) |
| [Document metadata and classification](/features/document-metadata-and-classification/) | Adds AI-assisted metadata extraction and category labels to workspace documents. | End users | Disabled | [Search and Extract](/admin/search-extract/) |
| [Image generation](/features/image-generation/) | Adds AI image creation from chat using the configured image generation model route. | End users | Disabled | [AI Models](/admin/ai-models/) |
| [Multimodal vision](/features/multimodal-vision/) | Enables model-based visual analysis for images and visual document content. | End users | Disabled | [Search and Extract](/admin/search-extract/) |
| [Tabular analysis](/features/tabular-analysis/) | Runs structured CSV and spreadsheet analysis with durable planning, batching, checkpoints, and response controls. | End users | Mixed | [Agents](/admin/agents/) |

## Agents and actions

| Capability | What it does | Who uses it | Default | Enable it in |
| --- | --- | --- | --- | --- |
| [Agents](/features/agents/) | Enables Semantic Kernel agents, agent discovery, templates, and multi-agent orchestration options. | End users | Mixed | [Agents](/admin/agents/) |
| [Core actions](/features/core-actions/) | Controls built-in action plugins for HTTP access, math, text transformation, time, waits, fact memory, and embedding utilities. | End users | Mixed | [Agents](/admin/agents/) |
| [MCP destination governance](/features/mcp-governance/) | Adds governance controls for Model Context Protocol destinations used by agent actions. | Admins | Disabled | [Governance](/admin/governance/) |

## Governance and safety

| Capability | What it does | Who uses it | Default | Enable it in |
| --- | --- | --- | --- | --- |
| [Content safety](/features/content-safety/) | Screens prompts and content through Azure AI Content Safety with optional API Management routing. | Admins | Disabled | [Safety](/admin/safety/) |
| [Feedback and conversation archiving](/features/feedback-and-archiving/) | Collects user feedback, exposes support feedback, and can archive conversations for review or compliance workflows. | End users | Mixed | [Send Feedback](/admin/send-feedback/) |
| [Notices and terms of use](/features/notices-and-terms/) | Shows AI notices and terms-of-use acknowledgement prompts to users. | End users | Disabled | [General](/admin/general/) |
| [Support menu and latest features](/features/support-menu/) | Adds the support menu, latest-feature pages, and optional documentation links for in-app help. | End users | Mixed | [Latest Features New](/admin/latest-features/) |

## Integrations

| Capability | What it does | Who uses it | Default | Enable it in |
| --- | --- | --- | --- | --- |
| [Custom pages and external links](/features/custom-navigation/) | Lets admins add trusted in-app custom pages and curated external navigation links. | End users | Disabled | [Custom Pages](/admin/custom-pages/) |
| [Key Vault secret storage](/features/key-vault-secrets/) | Stores configured secrets in Azure Key Vault and can remind operators about secret expiration. | Operators | Disabled | [Security](/admin/security/) |

## Platform and operations

| Capability | What it does | Who uses it | Default | Enable it in |
| --- | --- | --- | --- | --- |
| [App maintenance and health checks](/features/app-maintenance-and-health/) | Runs startup and recurring maintenance jobs and exposes optional external health-check behavior. | Operators | Mixed | [Control Center](/admin/control-center-config/) |
| [Front Door and session controls](/features/front-door-and-session-security/) | Supports Azure Front Door routing and optional idle-timeout behavior for browser sessions. | Operators | Disabled | [Security](/admin/security/) |
| [Logging and diagnostics](/features/logging-and-diagnostics/) | Controls diagnostic logging, Application Insights global logging, and user-visible file processing logs. | Operators | Mixed | [Logging](/admin/logging/) |
| [Model routing and endpoints](/features/model-routing/) | Configures how chat and embeddings reach approved Azure OpenAI or model endpoint routes. | Admins | Mixed | [AI Models](/admin/ai-models/) |
| [Scale and cache](/features/scale-and-cache/) | Enables Redis-backed scale-out support and cached conversation reads for faster hot paths. | Operators | Mixed | [Scale](/admin/scale/) |
| [Thoughts display](/features/thoughts-display/) | Shows configured processing-thought information in supported chat flows. | End users | Enabled | [General](/admin/general/) |
