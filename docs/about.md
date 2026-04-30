---
layout: showcase-page
title: "About Simple Chat"
permalink: /about/
menubar: docs_menu
accent: teal
eyebrow: "Platform Overview"
description: "Simple Chat combines Azure-hosted chat, grounded retrieval, workspace management, and optional agent orchestration into one application surface."
hero_icons:
  - bi-chat-square-text
  - bi-database
  - bi-diagram-3
hero_pills:
  - Azure-native by design
  - Workspace-first document grounding
  - Optional agents and automation
hero_links:
  - label: Start with setup
    url: /setup_instructions/
    style: primary
  - label: Explore features
    url: /features/
    style: secondary
---

Simple Chat is an enterprise-ready Flask application for teams that want conversational AI grounded in their own data, with admin controls that stay practical instead of sprawling.

<section class="latest-release-card-grid">
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-chat-square-text"></i></div>
		<h2>Grounded Chat</h2>
		<p>Users can chat directly with models or switch into retrieval-backed conversations that cite files from personal, group, or public workspaces.</p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-folder2-open"></i></div>
		<h2>Document Workflows</h2>
		<p>Uploads are processed through document extraction, chunking, embeddings, and search so teams can move from raw files to usable retrieval quickly.</p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-sliders"></i></div>
		<h2>Admin Control Surface</h2>
		<p>Admins configure branding, models, workspaces, search, safety, logging, and scale features from one settings experience.</p>
	</article>
</section>

<div class="latest-release-note-panel">
	<h2>What the docs are optimized for</h2>
	<p>The documentation is organized to help with three common paths: deploy the platform, configure the services behind it, and teach end users how to get value from workspaces, search, and agents.</p>
</div>

## Follow the right path

<section class="latest-release-card-grid">
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-rocket-takeoff"></i></div>
		<h2>Deploy</h2>
		<p>Use the guided deployment path if you want the fastest route into a working environment.</p>
		<p><a href="{{ '/setup_instructions/' | relative_url }}">Open Getting Started</a></p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-grid-1x2"></i></div>
		<h2>Understand capabilities</h2>
		<p>Review how chat, workspaces, safety, citations, multimedia, and agents fit together before expanding the deployment.</p>
		<p><a href="{{ '/features/' | relative_url }}">Browse the feature map</a></p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-gear"></i></div>
		<h2>Operate and tune</h2>
		<p>Use the admin, workflow, scaling, and troubleshooting guides when the platform moves from proof of concept into production support.</p>
		<p><a href="{{ '/application_scaling/' | relative_url }}">Review scaling guidance</a></p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-mortarboard"></i></div>
		<h2>Teach the team</h2>
		<p>The tutorial track is written for people who need to go from first login to useful document-grounded chat without reading every reference page first.</p>
		<p><a href="{{ '/tutorials/' | relative_url }}">Open tutorials</a></p>
	</article>
</section>

## Built as an open repo

The project lives in the open and includes application code, deployment assets, functional tests, UI tests, and deep change documentation under the docs tree.

<section class="latest-release-card-grid">
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-github"></i></div>
		<h2>Source and contribution flow</h2>
		<p>Contributors can inspect the application, deployment scripts, docs site, and supporting tools in one repository.</p>
		<p><a href="{{ '/contributing/' | relative_url }}">Read contribution guidance</a></p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-journal-text"></i></div>
		<h2>Release-by-release traceability</h2>
		<p>Feature explanations, fixes, and release notes are captured inside the docs site so changes remain searchable after deployment work is done.</p>
		<p><a href="{{ '/explanation/release_notes/' | relative_url }}">Review release notes</a></p>
	</article>
</section>
