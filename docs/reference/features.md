---
layout: page
title: "Features Reference"
permalink: /reference/features/
menubar: docs_menu
description: "Use this page as an operator-focused map of Simple Chat capabilities, service dependencies, and the docs that go deeper on each area."
---

The main features page is the broad product tour. This reference page is the faster operator map for people who need to connect a capability to the Azure services, admin settings, and user workflows behind it.

## Conversation surface

Core chat includes model selection, grounded responses, citations, exports, history, and optional multimedia or image-generation extensions.

## Workspace ingestion

Personal, group, and public workspaces add uploads, extraction, chunking, indexing, metadata, and optional classification across shared document sets.

## Governance and safety

Admins can control content safety, archiving, feedback, access roles, API documentation visibility, and advanced feature exposure from one settings surface.

## Agents and integrations

Optional Semantic Kernel agents, actions, OpenAPI plugins, SQL workflows, and external application helpers let teams move beyond plain chat into automation.

## Use the narrative page and the reference page differently

Start with [Features]({{ '/features/' | relative_url }}) when you want the user-facing tour. Switch to this page when you are mapping a requirement to configuration, dependencies, or adjacent docs.

## Feature map by operating area

| Area | What it covers | Common dependencies |
| :--- | :--- | :--- |
| Chat and model routing | Conversations, grounded answers, citations, export, streaming, optional image generation | Azure OpenAI, optional Content Safety |
| Workspaces and documents | Uploads, extraction, embeddings, search, classification, multimedia processing | Azure AI Search, embeddings, Document Intelligence, optional Speech and Video Indexer |
| Citations and previews | Standard citations, enhanced previews, storage-backed source rendering | Azure Storage for enhanced citations |
| Governance and operations | RBAC, logging, feedback, archiving, API docs visibility, scaling controls | Admin Settings, App Service, Application Insights |
| Agents and actions | Semantic Kernel agents, OpenAPI actions, SQL integrations, workspace-scoped automation | Agent/action enablement, plugin configuration, model endpoints |

## Where to go deeper

### Admin settings

Use the admin reference when you need to turn a capability on and verify which toggles or service tests control it.

[Open admin reference]({{ '/reference/admin_configuration/' | relative_url }})

### Workflows

Use the workflow guide when you want to understand how uploads, safety review, and retrieval-backed chat behave behind the UI.

[Review workflows]({{ '/reference/application-workflows/' | relative_url }})

### Latest release changes

Use the latest-release section when you need the most recent UI and capability changes rather than the long-lived platform map.

[Browse latest release]({{ '/latest-release/' | relative_url }})

### Tutorials and how-to guides

Use tutorials for onboarding and the how-to guides for repeatable operational workflows once the platform is already running.

[Open tutorials]({{ '/guides/' | relative_url }})
