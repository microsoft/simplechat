---
layout: showcase-page
title: "API Reference"
permalink: /reference/api_reference/
menubar: docs_menu
accent: slate
eyebrow: "Reference"
description: "Use the live Swagger endpoints and repository OpenAPI artifacts to inspect Simple Chat APIs, integration helpers, and route coverage."
hero_icons:
  - bi-braces
  - bi-filetype-json
  - bi-diagram-2
hero_pills:
  - Authenticated live docs
  - JSON and YAML output
  - Route and cache inspection
hero_links:
  - label: "Admin settings reference"
    url: /reference/admin_configuration/
    style: primary
  - label: "Feature reference"
    url: /reference/features/
    style: secondary
---

Use this page when you need to answer a concrete API question: what route exists, which auth model it uses, whether a deployed environment is exposing docs, or which OpenAPI helper endpoints support custom action setup.

<section class="latest-release-card-grid">
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-window"></i></div>
				<h2>Interactive docs</h2>
				<p>Open <code>/swagger</code> in a signed-in environment when you want the interactive route browser backed by the running app.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-filetype-json"></i></div>
				<h2>Machine-readable specs</h2>
				<p>Download <code>/swagger.json</code> or <code>/swagger.yaml</code> when you need tooling input, contract review, or export-friendly route metadata.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-list-task"></i></div>
				<h2>Route inventory</h2>
				<p>Use <code>/api/swagger/routes</code> and <code>/api/swagger/cache</code> to inspect route coverage, cache state, and documentation internals.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-plug"></i></div>
				<h2>OpenAPI helpers</h2>
				<p>The <code>/api/openapi/*</code> endpoints support OpenAPI upload, validation, and auth-scheme analysis for custom action configuration.</p>
		</article>
</section>

<div class="latest-release-note-panel">
		<h2>Pick the right source of truth</h2>
		<p>Use the live Swagger endpoints when you need the currently deployed route set, auth requirements, or generated schemas. Use the repository artifact at <code>artifacts/open_api/openapi.yaml</code> when you are reviewing frontend dependencies or discussing API shape in a pull request without relying on a running environment.</p>
</div>

## Documentation endpoints

| Endpoint | Use it for | Notes |
| :--- | :--- | :--- |
| <code>/swagger</code> | Interactive documentation UI | Requires authentication and depends on API documentation being enabled in Admin Settings. |
| <code>/swagger.json</code> | JSON OpenAPI output | Cached and rate limited. Good for tooling and diffing. |
| <code>/swagger.yaml</code> | YAML OpenAPI output | Same data as JSON, but easier to read or export into YAML-based workflows. |
| <code>/api/swagger/routes</code> | Route documentation status | Useful when you want to confirm which endpoints are documented. |
| <code>/api/swagger/cache</code> | Cache statistics and management | Supports inspection and cache clearing workflows. |

## OpenAPI action helper endpoints

Use these when configuring custom OpenAPI-backed actions:

- <code>/api/openapi/upload</code> validates an uploaded OpenAPI file and returns extracted spec metadata.
- <code>/api/openapi/list-uploaded</code> lists previously stored validated specs when available.
- <code>/api/openapi/analyze-auth</code> inspects the uploaded spec and suggests authentication handling.

## Recommended working pattern

1. Enable API documentation in Admin Settings if the environment hides Swagger routes by default.
2. Sign in and confirm the live docs at <code>/swagger</code> match the running environment.
3. Download <code>/swagger.json</code> or <code>/swagger.yaml</code> when you need contract-oriented tooling.
4. Use <code>artifacts/open_api/openapi.yaml</code> when you want a repo-side artifact for code review or frontend analysis.
