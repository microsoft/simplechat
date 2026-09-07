---
layout: page
title: "Search"
description: "Search the Simple Chat documentation."
section: "Search"
permalink: /search/
hide_toc: true
noindex: true
---

<div class="docs-search-page" data-docs-search-page="true">
    <form class="docs-search-page-form" role="search" autocomplete="off" data-docs-search-form="true">
        <label class="visually-hidden" for="docs-search-page-input">Search documentation</label>
        <div class="docs-search-page-field">
            <i class="bi bi-search" aria-hidden="true"></i>
            <input id="docs-search-page-input"
                   class="docs-search-page-input"
                   type="search"
                   name="q"
                   placeholder="Search the documentation"
                   data-docs-search-page-input="true" />
        </div>
    </form>

    <div class="docs-search-page-filters d-none" data-docs-search-filters="true" role="group" aria-label="Filter results by section"></div>

    <p class="docs-search-page-status" data-docs-search-status="true" role="status" aria-live="polite"></p>

    <div class="docs-search-page-results" data-docs-search-page-results="true"></div>

    <noscript>
        <p>Search requires JavaScript. Use the section navigation to browse the documentation instead.</p>
    </noscript>
</div>
