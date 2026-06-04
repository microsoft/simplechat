---
layout: showcase-page
title: "Simple Chat Documentation"
description: "Azure-native documentation for deploying, operating, and extending Simple Chat with the same polished visual language as the latest-release experience."
section: "Overview"
accent: blue
eyebrow: "Docs Overview"
home_search: true
hero_icons:
  - bi-house-fill
  - bi-stars
  - bi-rocket-takeoff
hero_pills:
  - Azure OpenAI
  - Retrieval-Augmented Generation
  - Enterprise controls
hero_links:
  - label: "Start the guide"
    url: /tutorials/
    style: primary
  - label: "Open API reference"
    url: /reference/api_reference/
    style: outline
---

Simple Chat gives teams an Azure-native way to deploy, ground, govern, and extend AI experiences without stitching together a separate chat app, search layer, and admin plane.

<section class="latest-release-section">
  <div class="latest-release-section-header">
    <div>
      <div class="latest-release-section-kicker">Start here</div>
      <h2>The shortest paths through the docs</h2>
      <p>Use these entry points when you want guidance, API details, examples, and release history without hunting through the entire docs tree.</p>
    </div>
    <span class="latest-release-section-badge">Top routes</span>
  </div>

  <div class="latest-release-card-grid">
    <article class="latest-release-card latest-release-accent--emerald">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-rocket-takeoff"></i></span>
          <span class="latest-release-card-badge">Deployment</span>
        </div>
        <h3 class="latest-release-card-title"><a href="{{ '/setup_instructions/' | relative_url }}">Getting Started</a></h3>
        <p class="latest-release-card-summary">Pick the right deployment path, line up prerequisites, and follow the repo's recommended order of operations.</p>
        <div class="latest-release-card-actions">
          <a class="btn btn-primary btn-sm" href="{{ '/setup_instructions/' | relative_url }}">Open guide</a>
        </div>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--blue">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-mortarboard"></i></span>
          <span class="latest-release-card-badge">Guide</span>
        </div>
        <h3 class="latest-release-card-title"><a href="{{ '/tutorials/' | relative_url }}">Tutorials</a></h3>
        <p class="latest-release-card-summary">Follow guided product paths for first deployment, document upload, agents, and classification.</p>
        <div class="latest-release-card-actions">
          <a class="btn btn-primary btn-sm" href="{{ '/tutorials/' | relative_url }}">Start learning</a>
        </div>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--orange">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-grid-3x3-gap"></i></span>
          <span class="latest-release-card-badge">Capabilities</span>
        </div>
        <h3 class="latest-release-card-title"><a href="{{ '/features/' | relative_url }}">Features</a></h3>
        <p class="latest-release-card-summary">See the core workspace experience, optional feature packs, platform services, and supported file types in one place.</p>
        <div class="latest-release-card-actions">
          <a class="btn btn-primary btn-sm" href="{{ '/features/' | relative_url }}">Browse features</a>
        </div>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--slate">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-braces"></i></span>
          <span class="latest-release-card-badge">Reference</span>
        </div>
        <h3 class="latest-release-card-title"><a href="{{ '/reference/api_reference/' | relative_url }}">API Reference</a></h3>
        <p class="latest-release-card-summary">Find live Swagger endpoints, OpenAPI helper routes, and the right source of truth for route review.</p>
        <div class="latest-release-card-actions">
          <a class="btn btn-primary btn-sm" href="{{ '/reference/api_reference/' | relative_url }}">Inspect APIs</a>
        </div>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--teal">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-palette"></i></span>
          <span class="latest-release-card-badge">Admin UI</span>
        </div>
        <h3 class="latest-release-card-title"><a href="{{ '/how-to/admin_ui_settings/' | relative_url }}">Branding and Support Settings</a></h3>
        <p class="latest-release-card-summary">Change logo, title, home page text, health checks, Swagger, classification banner, Support, external links, and system settings.</p>
        <div class="latest-release-card-actions">
          <a class="btn btn-primary btn-sm" href="{{ '/how-to/admin_ui_settings/' | relative_url }}">Open how-to</a>
        </div>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--teal">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-collection-play"></i></span>
          <span class="latest-release-card-badge">Examples</span>
        </div>
        <h3 class="latest-release-card-title"><a href="{{ '/explanation/scenarios/' | relative_url }}">Scenario Library</a></h3>
        <p class="latest-release-card-summary">Browse workspace and agent scenarios that show how Simple Chat can be shaped for practical team workflows.</p>
        <div class="latest-release-card-actions">
          <a class="btn btn-primary btn-sm" href="{{ '/explanation/scenarios/' | relative_url }}">View examples</a>
        </div>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--violet">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-clock-history"></i></span>
          <span class="latest-release-card-badge">Changelog</span>
        </div>
        <h3 class="latest-release-card-title"><a href="{{ '/explanation/release_notes/' | relative_url }}">Release Notes</a></h3>
        <p class="latest-release-card-summary">Track feature additions, UI improvements, and fixes by version when you need implementation history.</p>
        <div class="latest-release-card-actions">
          <a class="btn btn-primary btn-sm" href="{{ '/explanation/release_notes/' | relative_url }}">Read changelog</a>
        </div>
      </div>
    </article>
  </div>
</section>

<section class="latest-release-section">
  <div class="latest-release-section-header">
    <div>
      <div class="latest-release-section-kicker">Why teams use it</div>
      <h2>One application, multiple working modes</h2>
      <p>Simple Chat is opinionated about the hard parts: identity, grounding, document processing, and admin controls are already wired together.</p>
    </div>
    <span class="latest-release-section-badge">Azure-native</span>
  </div>

  <div class="latest-release-card-grid">
    <article class="latest-release-card latest-release-accent--blue">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-chat-dots"></i></span>
          <span class="latest-release-card-badge">Chat + grounding</span>
        </div>
        <h3 class="latest-release-card-title">Context-aware AI conversations</h3>
        <p class="latest-release-card-summary">Use Azure OpenAI with hybrid retrieval over personal, group, and public workspace content so responses stay tied to your own data.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--emerald">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-folder2-open"></i></span>
          <span class="latest-release-card-badge">Documents</span>
        </div>
        <h3 class="latest-release-card-title">Document pipelines that stay searchable</h3>
        <p class="latest-release-card-summary">Ingest PDFs, Office files, images, audio, and video through Azure AI services, then retrieve them with citations and optional metadata enrichment.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--orange">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-shield-check"></i></span>
          <span class="latest-release-card-badge">Governance</span>
        </div>
        <h3 class="latest-release-card-title">Controls for enterprise rollouts</h3>
        <p class="latest-release-card-summary">Layer on Entra ID roles, content safety, feedback review, conversation archiving, and operational logging without rebuilding the app.</p>
      </div>
    </article>
  </div>
</section>

<section class="latest-release-section">
  <div class="latest-release-section-header">
    <div>
      <div class="latest-release-section-kicker">Architecture</div>
      <h2>What sits behind the experience</h2>
      <p>The platform runs on Azure App Service and composes search, storage, document processing, and conversation state into a single application surface.</p>
    </div>
    <span class="latest-release-section-badge">Reference view</span>
  </div>

  <div class="latest-release-note-panel latest-release-accent--slate">
    <h3>Platform at a glance</h3>
    <p>Core application state lives in Azure Cosmos DB, document retrieval runs through Azure AI Search, ingestion is handled by Azure AI Document Intelligence and related media services, and authentication uses Entra ID. That combination makes it practical to run Simple Chat as a governed internal tool instead of a demo-only sample.</p>
  </div>

  <div class="mt-3">
    <img src="{{ '/images/architecture.png' | relative_url }}" alt="Architecture diagram showing Simple Chat running on Azure App Service with Azure OpenAI, AI Search, Cosmos DB, and storage services." />
  </div>
</section>

<section class="latest-release-section">
  <div class="latest-release-section-header">
    <div>
      <div class="latest-release-section-kicker">Contribute</div>
      <h2>Working in the repo</h2>
      <p>The docs, app, and deployers are all maintained together, so the contributor guide is the fastest way to align with the expected workflow.</p>
    </div>
    <span class="latest-release-section-badge">Collaboration</span>
  </div>

  <div class="latest-release-note-panel latest-release-accent--teal">
    <h3>Want to make changes?</h3>
    <p>Use the <a href="{{ '/contributing/' | relative_url }}">Contributing guide</a> for the fork-based workflow, target branch expectations, and local development references before you start editing code or docs.</p>
  </div>
</section>
