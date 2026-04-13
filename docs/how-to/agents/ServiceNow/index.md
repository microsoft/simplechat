---
layout: showcase-page
title: "ServiceNow Agent Guides"
permalink: /how-to/agents/ServiceNow/
menubar: docs_menu
accent: slate
eyebrow: "How-To Guide"
description: "Use these guides to connect Simple Chat agents and actions to ServiceNow for incident handling, knowledge workflows, OAuth authentication, and asset management."
hero_icons: ["bi-plug", "bi-life-preserver", "bi-database-gear"]
hero_pills: ["Incident and KB integrations", "OAuth 2.0 authentication", "Single-agent and multi-agent patterns"]
hero_links: [{ label: "Create agents", url: "/how-to/create_agents/", style: "primary" }, { label: "How-to index", url: "/how-to/", style: "secondary" }]
---

These guides are best read as a family. Start with the single-agent integration if you want the fastest path, move into OAuth when you need production authentication, then use the advanced guides only when your permissions or workflows demand more separation.

<section class="latest-release-card-grid">
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-life-preserver"></i></div>
        <h2>Single-agent ServiceNow integration</h2>
        <p>Use the standard support-agent guide for incident management and read-only KB search through one agent and two actions.</p>
        <p><a href="{{ '/how-to/agents/ServiceNow/servicenow_integration/' | relative_url }}">Open integration guide</a></p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-key"></i></div>
        <h2>OAuth 2.0 setup</h2>
        <p>Use the OAuth guide when you need bearer-token authentication instead of Basic Auth for ServiceNow actions in production-style environments.</p>
        <p><a href="{{ '/how-to/agents/ServiceNow/servicenow_oauth_setup/' | relative_url }}">Open OAuth guide</a></p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-people"></i></div>
        <h2>Two-agent KB management</h2>
        <p>Use the advanced split-agent design when incident handling and KB publishing need separate roles, tokens, and approval boundaries.</p>
        <p><a href="{{ '/how-to/agents/ServiceNow/two_agent_setup/' | relative_url }}">Open two-agent guide</a></p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-pc-display-horizontal"></i></div>
        <h2>Asset management agent</h2>
        <p>Use the asset-management guide when you want a dedicated agent with separate query, create, update, and delete actions over the `alm_asset` table.</p>
        <p><a href="{{ '/how-to/agents/ServiceNow/servicenow_asset_management_setup/' | relative_url }}">Open asset guide</a></p>
    </article>
</section>

<div class="latest-release-note-panel">
    <h2>Pick the narrowest integration that fits</h2>
    <p>Most teams should start with the single-agent support pattern. Add OAuth when security posture requires it, add the two-agent KB model when permissions diverge, and add asset management only when hardware lifecycle workflows belong inside the agent surface.</p>
</div>

## Shared supporting assets

<section class="latest-release-card-grid">
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-filetype-yaml"></i></div>
        <h2>OpenAPI specs</h2>
        <p>The ServiceNow folder includes incident, knowledge-base, and asset-management specs for the actions described in these guides.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-journal-text"></i></div>
        <h2>Agent instructions</h2>
        <p>Instruction files for the support, KB management, and asset-management agents live beside the specs so action and prompt behavior stay aligned.</p>
    </article>
</section>