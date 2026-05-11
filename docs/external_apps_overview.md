---
layout: showcase-page
title: "External Applications Overview"
permalink: /external_apps_overview/
menubar: docs_menu
accent: emerald
eyebrow: "Supporting Utilities"
description: "Simple Chat ships with helper applications for teams that need to load content in bulk or seed administrative configuration outside the main UI."
hero_icons:
  - bi-box-arrow-up-right
  - bi-upload
  - bi-database-gear
hero_pills:
  - Bulk content onboarding
  - Configuration seeding
  - Useful for environment setup and migration
hero_links:
  - label: Manual setup guide
    url: /setup_instructions_manual/
    style: primary
  - label: Admin configuration
    url: /admin_configuration/
    style: secondary
---

These utilities sit beside the main application. They are intended for administrators and support teams that need faster environment preparation or large-scale document loading.

<section class="latest-release-card-grid">
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-upload"></i></div>
		<h2>Bulk Uploader Utility</h2>
		<p>Use the bulk uploader when you need to load a larger document set into a group workspace without relying on repeated manual uploads through the web UI.</p>
		<p><a href="{{ site.github.repository_url }}/tree/main/application/external_apps/bulkloader">Open bulk uploader source</a></p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-database-gear"></i></div>
		<h2>Database Seeder Utility</h2>
		<p>Use the database seeder to initialize or overwrite admin settings in Cosmos DB so an environment starts from a known configuration state.</p>
		<p><a href="{{ site.github.repository_url }}/tree/main/application/external_apps/databaseseeder">Open database seeder source</a></p>
	</article>
</section>

<div class="latest-release-note-panel">
	<h2>When these tools are the right choice</h2>
	<p>Use them when the UI is not the fastest path: for migration work, large initial content loads, repeatable environment setup, or admin configuration seeding across multiple environments.</p>
</div>
