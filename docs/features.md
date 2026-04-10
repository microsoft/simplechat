---
layout: showcase-page
title: "Features"
description: "A structured view of the Simple Chat experience, from core workspace flows to optional feature packs and the Azure services behind them."
section: "Overview"
accent: orange
eyebrow: "Capability Map"
hero_icons:
  - bi-stars
  - bi-grid-3x3-gap
  - bi-shield-check
hero_pills:
  - Core workspace experience
  - Optional admin-enabled packs
  - Azure-native services
hero_links:
  - label: "See latest release highlights"
    url: /latest-release/
    style: primary
  - label: "Review admin configuration"
    url: /admin_configuration/
    style: outline
---

Simple Chat starts with a grounded chat experience, then expands through optional modules for governance, media processing, feedback loops, advanced citations, and operational scale.

<section class="latest-release-section">
  <div class="latest-release-section-header">
    <div>
      <div class="latest-release-section-kicker">Core experience</div>
      <h2>What ships with the day-one product surface</h2>
      <p>These are the capabilities most teams use immediately after deployment.</p>
    </div>
    <span class="latest-release-section-badge">Always relevant</span>
  </div>

  <div class="latest-release-card-grid">
    <article class="latest-release-card latest-release-accent--blue">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-chat-dots"></i></span>
          <span class="latest-release-card-badge">Conversation</span>
        </div>
        <h3 class="latest-release-card-title">Chat with AI</h3>
        <p class="latest-release-card-summary">Interact with Azure OpenAI deployments through a workspace-aware chat surface built for grounded answers, prompt reuse, and iterative conversations.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--teal">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-search"></i></span>
          <span class="latest-release-card-badge">Retrieval</span>
        </div>
        <h3 class="latest-release-card-title">RAG with hybrid search</h3>
        <p class="latest-release-card-summary">Combine vector and keyword retrieval over uploaded files so chat responses can pull directly from the indexed document set.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--emerald">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-folder2-open"></i></span>
          <span class="latest-release-card-badge">Workspaces</span>
        </div>
        <h3 class="latest-release-card-title">Personal and group document management</h3>
        <p class="latest-release-card-summary">Upload, version, organize, and reuse files in personal workspaces or share them through group workspaces with role-aware access control.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--slate">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-clock-history"></i></span>
          <span class="latest-release-card-badge">Session scope</span>
        </div>
        <h3 class="latest-release-card-title">Ephemeral chat uploads</h3>
        <p class="latest-release-card-summary">Attach single-conversation documents when you need temporary grounding without committing those files to persistent search indexes.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--orange">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-person-lock"></i></span>
          <span class="latest-release-card-badge">Access</span>
        </div>
        <h3 class="latest-release-card-title">Authentication and RBAC</h3>
        <p class="latest-release-card-summary">Secure the app with Entra ID, managed identities, and app roles such as Admin, User, CreateGroup, SafetyAdmin, and FeedbackAdmin.</p>
      </div>
    </article>
  </div>
</section>

<section class="latest-release-section">
  <div class="latest-release-section-header">
    <div>
      <div class="latest-release-section-kicker">Optional capability packs</div>
      <h2>Modules you can enable as the rollout matures</h2>
      <p>These features are designed to layer onto the base experience through admin settings and supporting Azure services.</p>
    </div>
    <span class="latest-release-section-badge">Admin controlled</span>
  </div>

  <div class="latest-release-card-grid">
    <article class="latest-release-card latest-release-accent--rose">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-shield-check"></i></span>
          <span class="latest-release-card-badge">Governance</span>
        </div>
        <h3 class="latest-release-card-title">Content safety and policy controls</h3>
        <p class="latest-release-card-summary">Review user prompts before they reach AI models, search, or image generation and give designated reviewers a place to inspect flagged activity.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--orange">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-images"></i></span>
          <span class="latest-release-card-badge">Generation</span>
        </div>
        <h3 class="latest-release-card-title">Image generation and live web results</h3>
        <p class="latest-release-card-summary">Add DALL-E powered image creation and Bing-powered web search when your users need current results or generated visuals inside the same app.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--teal">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-camera-video"></i></span>
          <span class="latest-release-card-badge">Media</span>
        </div>
        <h3 class="latest-release-card-title">Video and audio extraction</h3>
        <p class="latest-release-card-summary">Transcribe media, capture timestamps, and turn recordings into searchable assets with citations that can point back to the right moment.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--blue">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-tags"></i></span>
          <span class="latest-release-card-badge">Document context</span>
        </div>
        <h3 class="latest-release-card-title">Classification, metadata, and enhanced citations</h3>
        <p class="latest-release-card-summary">Add labels, AI-generated summaries, author/date inference, and source-linked previews so users can understand where an answer came from.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--emerald">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-hand-thumbs-up"></i></span>
          <span class="latest-release-card-badge">Feedback + retention</span>
        </div>
        <h3 class="latest-release-card-title">User feedback and conversation archiving</h3>
        <p class="latest-release-card-summary">Collect structured sentiment on responses and, when needed, retain conversations in a dedicated archive for audit and compliance workflows.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--slate">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-hdd-network"></i></span>
          <span class="latest-release-card-badge">Scale + extensibility</span>
        </div>
        <h3 class="latest-release-card-title">Redis cache, SQL agents, and processing logs</h3>
        <p class="latest-release-card-summary">Scale session handling, inspect ingestion activity, and connect agent workflows to SQL data sources through configurable plugins.</p>
      </div>
    </article>
  </div>
</section>

<section class="latest-release-section">
  <div class="latest-release-section-header">
    <div>
      <div class="latest-release-section-kicker">Platform services</div>
      <h2>Azure building blocks behind the product</h2>
      <p>Simple Chat is opinionated about which Azure services handle which part of the workload.</p>
    </div>
    <span class="latest-release-section-badge">Service map</span>
  </div>

  <div class="latest-release-note-panel latest-release-accent--orange">
    <h3>Primary service roles</h3>
    <ul>
      <li><strong>Azure Cosmos DB</strong> stores conversations, metadata, settings, user and group records, and optional archive or feedback data.</li>
      <li><strong>Azure AI Search</strong> powers hybrid retrieval across indexed personal and group content.</li>
      <li><strong>Azure AI Document Intelligence</strong> extracts text and layout from uploaded files during ingestion.</li>
      <li><strong>Azure OpenAI</strong> handles chat completions, embeddings, optional image generation, and AI-driven metadata extraction.</li>
      <li><strong>Azure Storage</strong> supports enhanced citation content and related document assets.</li>
      <li><strong>Azure Cache for Redis</strong> is optional and becomes important when you need horizontal scale with shared sessions.</li>
    </ul>
  </div>
</section>

<section class="latest-release-section">
  <div class="latest-release-section-header">
    <div>
      <div class="latest-release-section-kicker">Supported inputs</div>
      <h2>File types the platform is built to understand</h2>
      <p>Exact behavior depends on which optional extraction features you enable, but these are the main content categories the app is designed around.</p>
    </div>
    <span class="latest-release-section-badge">Coverage</span>
  </div>

  <div class="latest-release-card-grid">
    <article class="latest-release-card latest-release-accent--blue">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-filetype-txt"></i></span>
          <span class="latest-release-card-badge">Text</span>
        </div>
        <h3 class="latest-release-card-title">Structured and plain text</h3>
        <p class="latest-release-card-summary">`txt`, `md`, `html`, `json`, `xml`, `yaml`, `yml`, and `log` files fit the basic ingestion pipeline well.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--emerald">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-file-earmark-richtext"></i></span>
          <span class="latest-release-card-badge">Documents</span>
        </div>
        <h3 class="latest-release-card-title">Office and tabular documents</h3>
        <p class="latest-release-card-summary">`pdf`, `doc`, `docm`, `docx`, `pptx`, `xlsx`, `xlsm`, `xls`, and `csv` cover the common enterprise file set.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--orange">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-image"></i></span>
          <span class="latest-release-card-badge">Images</span>
        </div>
        <h3 class="latest-release-card-title">Image ingestion with OCR support</h3>
        <p class="latest-release-card-summary">`jpg`, `jpeg`, `png`, `bmp`, `tiff`, `tif`, and `heif` can be processed through document analysis and OCR-aware workflows.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--teal">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-film"></i></span>
          <span class="latest-release-card-badge">Media</span>
        </div>
        <h3 class="latest-release-card-title">Audio and video formats</h3>
        <p class="latest-release-card-summary">`mp4`, `mov`, `avi`, `wmv`, `mkv`, `webm`, `mp3`, `wav`, `ogg`, `aac`, `flac`, and `m4a` become searchable when the related media services are enabled.</p>
      </div>
    </article>
  </div>
</section>

<section class="latest-release-section">
  <div class="latest-release-section-header">
    <div>
      <div class="latest-release-section-kicker">Visual reference</div>
      <h2>Architecture and admin surface</h2>
      <p>The deployment architecture and admin settings page are usually the fastest way to explain how the feature set is organized.</p>
    </div>
    <span class="latest-release-section-badge">Screens</span>
  </div>

  <div class="latest-release-card-grid">
    <article class="latest-release-card latest-release-accent--slate">
      <div class="latest-release-card-shell">
        <a class="latest-release-card-image" href="{{ '/images/architecture.png' | relative_url }}">
          <img src="{{ '/images/architecture.png' | relative_url }}" alt="Architecture diagram for Simple Chat on Azure." />
        </a>
        <h3 class="latest-release-card-title">Architecture overview</h3>
        <p class="latest-release-card-summary">Use this diagram when you need to explain how App Service, Azure OpenAI, AI Search, Cosmos DB, and storage fit together.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--blue">
      <div class="latest-release-card-shell">
        <a class="latest-release-card-image" href="{{ '/images/admin_settings_page.png' | relative_url }}">
          <img src="{{ '/images/admin_settings_page.png' | relative_url }}" alt="Admin settings page for Simple Chat." />
        </a>
        <h3 class="latest-release-card-title">Admin configuration surface</h3>
        <p class="latest-release-card-summary">Most optional features are exposed through the admin settings experience, which keeps rollout decisions in one operational surface.</p>
      </div>
    </article>
  </div>
</section>
