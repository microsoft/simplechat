---
layout: showcase-page
title: "Working in the repo"
permalink: /contributing/
menubar: docs_menu
accent: sky
eyebrow: "Contribute"
description: "The docs, app, and deployers are all maintained together, so the contributor guide is the fastest way to align with the expected workflow."
hero_icons:
  - bi-git
  - bi-journal-code
  - bi-check2-square
hero_pills:
  - Docs, app, and deployers live together
  - Target the right branch first
  - Validate the surface you touched
hero_links:
  - label: Return to docs home
    url: /
    style: primary
  - label: Review setup paths
    url: /setup_instructions/
    style: secondary
---

Simple Chat is maintained as one repo, which means a change in the app usually pulls docs, deployers, or tests along with it. The safest contribution pattern is to start from the branch flow, keep the change scoped, and run the validation closest to the surface you changed.

<section class="latest-release-card-grid">
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-window-stack"></i></div>
        <h2>Application surface</h2>
        <p>The Flask app lives under <code>application/single_app/</code>, with route modules, Jinja templates, static assets, and service integrations all in the same deployment unit.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-book"></i></div>
        <h2>Docs site</h2>
        <p>The public documentation is the Jekyll site under <code>docs/</code>. If you touch user-visible behavior, expect to update docs or screenshots alongside the code.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-cloud-arrow-up"></i></div>
        <h2>Deployers</h2>
        <p>Azure deployment assets sit under <code>deployers/</code> and cover AZD, Bicep, Terraform, and Azure CLI driven paths. Infrastructure-facing changes should stay aligned across those entry points.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-bezier2"></i></div>
        <h2>Regression coverage</h2>
        <p>Behavior checks are split across <code>functional_tests/</code> and <code>ui_tests/</code>. Browser-facing changes should leave behind an updated UI regression, not just a visual review.</p>
    </article>
</section>

## Contribution workflow

<div class="latest-release-note-panel">
    <h2>Use the real upstream branch names</h2>
    <p>The current shared branch flow is <strong>Development → Staging → main</strong>. In this repo the upstream branch names are capitalized as <code>Development</code> and <code>Staging</code>, so keep that exact casing when you create branches, compare refs, or document automation.</p>
</div>

1. Start your work from <code>Development</code> unless a maintainer asks you to branch elsewhere.
2. Keep the change focused on one feature, fix, or docs sweep so the review stays readable.
3. Open pull requests into <code>Development</code> for normal feature and fix work.
4. Treat promotion into <code>Staging</code> and then <code>main</code> as release flow, not day-to-day feature branching.
5. If you touch workflow automation, verify branch comparisons carefully because older workflow logic may still use lowercase strings even though the upstream branches are capitalized.

## Local setup before you edit

Use the deployment and setup docs when you need a full environment, but keep these contributor shortcuts handy for day-to-day repo work.

### Docs preview

Build the Jekyll site before you send a docs or screenshot-heavy pull request:

```powershell
cd docs
bundle exec jekyll build
bundle exec jekyll serve --host 127.0.0.1 --port 4000
```

Open the site at <code>http://127.0.0.1:4000/simplechat/</code>. The repo uses a Jekyll <code>baseurl</code>, so the local path includes <code>/simplechat/</code> unless you intentionally override it.

### UI regression for docs pages

If your change affects docs rendering, layout, links, images, or JavaScript behavior, run the docs UI suite against the local Jekyll server:

```powershell
cd ..
$env:SIMPLECHAT_DOCS_BASE_URL = "http://127.0.0.1:4000/simplechat"
python -m pytest ui_tests/test_docs_showcase_pages.py
```

### App and backend validation

For application changes, run the narrowest relevant validation instead of skipping straight to a broad full-repo test pass.

<section class="latest-release-card-grid">
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-sliders"></i></div>
        <h2>Targeted functional tests</h2>
        <p>Add or update focused scripts in <code>functional_tests/</code> when you fix a bug, ship a feature, or change an integration path.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-layout-text-window"></i></div>
        <h2>UI coverage</h2>
        <p>When templates, CSS, or browser-side JavaScript change, update the Playwright coverage in <code>ui_tests/</code> so the behavior is reproducible in CI and local review.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-link-45deg"></i></div>
        <h2>Cross-file changes</h2>
        <p>If a feature spans app code, docs, and deployers, keep the terminology and defaults aligned. This repo is easier to review when one pull request closes the loop instead of leaving follow-up drift.</p>
    </article>
</section>

## Pull request checklist

Before you open a PR, confirm the basics:

- The branch target is <code>Development</code> for normal contribution work.
- The description explains the user-visible impact, not just the implementation.
- Docs, screenshots, release notes, or test coverage were updated when the change affected them.
- Validation commands were run for the surfaces you changed.
- The diff stays scoped to the task instead of bundling unrelated cleanup.

## Related references

<section class="latest-release-card-grid">
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-rocket-takeoff"></i></div>
        <h2>Deployment setup</h2>
        <p><a href="{{ '/setup_instructions/' | relative_url }}">Getting Started</a> is the fastest path if you need a full environment instead of a docs-only or code-only edit.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-journal-richtext"></i></div>
        <h2>Release traceability</h2>
        <p>Use the <a href="{{ '/explanation/release_notes/' | relative_url }}">release notes</a> and explanation docs when your change needs a durable record beyond the PR.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-question-circle"></i></div>
        <h2>Operational follow-up</h2>
        <p>If a change affects administrators or deployment operators, link the matching reference or how-to page in the PR so reviewers can verify the end-to-end story.</p>
    </article>
</section>