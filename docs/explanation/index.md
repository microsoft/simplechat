---
layout: showcase-page
title: "Explanation"
permalink: /explanation/
menubar: docs_menu
accent: violet
eyebrow: "Understand The Platform"
description: "Use the explanation section when you want the reasoning behind the product: architecture, operating principles, rollout guidance, and runtime patterns."
hero_icons: ["bi-diagram-3", "bi-lightbulb", "bi-journal-richtext"]
hero_pills: ["Architecture and principles", "Feature rollout guidance", "Local and production runtime patterns"]
hero_links: [{ label: "Architecture", url: "/explanation/architecture/", style: "primary" }, { label: "Feature guidance", url: "/explanation/feature_guidance/", style: "secondary" }]
---

This section is for decisions, not just steps. Use it when you need to understand why Simple Chat is put together the way it is and how that affects deployment, operations, and feature rollout.

<section class="latest-release-card-grid">
  <article class="latest-release-card">
    <div class="latest-release-card-icon"><i class="bi bi-diagram-3"></i></div>
    <h2>Architecture</h2>
    <p>Understand how App Service, Azure OpenAI, AI Search, Cosmos DB, Storage, and optional services combine into one application surface.</p>
    <p><a href="{{ '/explanation/architecture/' | relative_url }}">Open architecture</a></p>
  </article>
  <article class="latest-release-card">
    <div class="latest-release-card-icon"><i class="bi bi-compass"></i></div>
    <h2>Design Principles</h2>
    <p>See the operating philosophy behind the product, including security, enterprise readiness, modularity, observability, and user-centered design.</p>
    <p><a href="{{ '/explanation/design_principles/' | relative_url }}">Open design principles</a></p>
  </article>
  <article class="latest-release-card">
    <div class="latest-release-card-icon"><i class="bi bi-grid-1x2"></i></div>
    <h2>Feature Guidance</h2>
    <p>Use the feature guidance page to decide which capabilities belong in a first rollout and which ones should be layered in after the platform stabilizes.</p>
    <p><a href="{{ '/explanation/feature_guidance/' | relative_url }}">Open feature guidance</a></p>
  </article>
  <article class="latest-release-card">
    <div class="latest-release-card-icon"><i class="bi bi-play-circle"></i></div>
    <h2>Runtime Patterns</h2>
    <p>Compare the recommended local developer loop with the Azure production runtime model so startup decisions stay consistent with the deployment model.</p>
    <p><a href="{{ '/explanation/running_simplechat_locally/' | relative_url }}">Local runtime</a> · <a href="{{ '/explanation/running_simplechat_azure_production/' | relative_url }}">Azure production</a></p>
  </article>
</section>

<div class="latest-release-note-panel">
  <h2>Use these pages differently from how-to guides</h2>
  <p>How-to guides are task-oriented. The explanation section is where you go when you want to understand the tradeoffs behind deployment models, feature boundaries, or operational choices before you commit to one path.</p>
</div>

## Continue into deeper references

<section class="latest-release-card-grid">
  <article class="latest-release-card">
    <div class="latest-release-card-icon"><i class="bi bi-collection"></i></div>
    <h2>Scenarios</h2>
    <p>Example workspace and agent scenarios show how the product can be applied in concrete business contexts.</p>
    <p><a href="{{ '/explanation/scenarios/agents/' | relative_url }}">Agent examples</a> · <a href="{{ '/explanation/scenarios/workspaces/' | relative_url }}">Workspace examples</a></p>
  </article>
  <article class="latest-release-card">
    <div class="latest-release-card-icon"><i class="bi bi-clock-history"></i></div>
    <h2>Version history</h2>
    <p>Track long-lived feature and fix documentation by version when you need historical context for rollout planning or regression analysis.</p>
    <p><a href="{{ '/explanation/features/' | relative_url }}">Features by version</a> · <a href="{{ '/explanation/fixes/' | relative_url }}">Fixes by version</a></p>
  </article>
</section>