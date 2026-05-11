---
layout: showcase-page
title: "Features Reference"
permalink: /reference/features/
menubar: docs_menu
accent: blue
eyebrow: "Reference"
description: "Use this page as an operator-focused map of Simple Chat capabilities, service dependencies, and the docs that go deeper on each area."
hero_icons:
  - bi-grid-1x2
  - bi-chat-square-text
  - bi-gear
hero_pills:
  - Chat and retrieval
  - Workspaces and processing
  - Safety and automation
hero_links:
  - label: "Feature overview"
    url: /features/
    style: primary
  - label: "Application workflows"
    url: /application_workflows/
    style: secondary
---

The main features page is the broad product tour. This reference page is the faster operator map for people who need to connect a capability to the Azure services, admin settings, and user workflows behind it.

<section class="latest-release-card-grid">
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-chat-square-text"></i></div>
		<h2>Conversation surface</h2>
		<p>Core chat includes model selection, grounded responses, citations, exports, history, and optional multimedia or image-generation extensions.</p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-folder2-open"></i></div>
		<h2>Workspace ingestion</h2>
		<p>Personal, group, and public workspaces add uploads, extraction, chunking, indexing, metadata, and optional classification across shared document sets.</p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-shield-check"></i></div>
		<h2>Governance and safety</h2>
		<p>Admins can control content safety, archiving, feedback, access roles, API documentation visibility, and advanced feature exposure from one settings surface.</p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-robot"></i></div>
		<h2>Agents and integrations</h2>
		<p>Optional Semantic Kernel agents, actions, OpenAPI plugins, SQL workflows, and external application helpers let teams move beyond plain chat into automation.</p>
	</article>
</section>

<div class="latest-release-note-panel">
	<h2>Use the narrative page and the reference page differently</h2>
	<p>Start with <a href="{{ '/features/' | relative_url }}">Features</a> when you want the user-facing tour. Switch to this page when you are mapping a requirement to configuration, dependencies, or adjacent docs.</p>
</div>

## Feature map by operating area

| Area | What it covers | Common dependencies |
| :--- | :--- | :--- |
| Chat and model routing | Conversations, grounded answers, citations, export, streaming, optional image generation | Azure OpenAI, optional Content Safety |
| Workspaces and documents | Uploads, extraction, embeddings, search, classification, multimedia processing | Azure AI Search, embeddings, Document Intelligence, optional Speech and Video Indexer |
| Citations and previews | Standard citations, enhanced previews, storage-backed source rendering | Azure Storage for enhanced citations |
| Governance and operations | RBAC, logging, feedback, archiving, API docs visibility, scaling controls | Admin Settings, App Service, Application Insights |
| Agents and actions | Semantic Kernel agents, OpenAPI actions, SQL integrations, workspace-scoped automation | Agent/action enablement, plugin configuration, model endpoints |

## Where to go deeper

<section class="latest-release-card-grid">
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-sliders"></i></div>
		<h2>Admin settings</h2>
		<p>Use the admin reference when you need to turn a capability on and verify which toggles or service tests control it.</p>
		<p><a href="{{ '/reference/admin_configuration/' | relative_url }}">Open admin reference</a></p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-diagram-3"></i></div>
		<h2>Workflows</h2>
		<p>Use the workflow guide when you want to understand how uploads, safety review, and retrieval-backed chat behave behind the UI.</p>
		<p><a href="{{ '/application_workflows/' | relative_url }}">Review workflows</a></p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-stars"></i></div>
		<h2>Latest release changes</h2>
		<p>Use the latest-release section when you need the most recent UI and capability changes rather than the long-lived platform map.</p>
		<p><a href="{{ '/latest-release/' | relative_url }}">Browse latest release</a></p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-mortarboard"></i></div>
		<h2>Tutorials and how-to guides</h2>
		<p>Use tutorials for onboarding and the how-to guides for repeatable operational workflows once the platform is already running.</p>
		<p><a href="{{ '/tutorials/' | relative_url }}">Open tutorials</a></p>
	</article>
</section>
