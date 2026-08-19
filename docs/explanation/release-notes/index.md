---
title: "Release notes"
description: "SimpleChat release notes index with latest updates and links to archived release pages."
section: "Reference"
layout: page
permalink: /explanation/release_notes/
---

<!-- Generated from docs/explanation/release_notes.md by scripts/build_release_notes_pages.py. Regenerate with: python scripts/build_release_notes_pages.py -->

# Release notes

<!-- BEGIN release_notes.md BLOCK -->

For feature-focused and fix-focused drill-downs by version, see [Features by Version](https://github.com/microsoft/simplechat/tree/main/docs/explanation/features) and [Fixes by Version](https://github.com/microsoft/simplechat/tree/main/docs/explanation/fixes).

This page includes the latest release notes inline. Older release sections are split into smaller pages by minor series.

## Version index

| Version | Page |
| --- | --- |
| v0.260.002 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.001 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.250.231 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.250.230 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.250.229 | [Release notes 0.250 series]({{ '/explanation/release-notes/v0.250/' | relative_url }}) |
| v0.250.001 | [Release notes 0.250 series]({{ '/explanation/release-notes/v0.250/' | relative_url }}) |
| v0.241.007 | [Release notes 0.241 series]({{ '/explanation/release-notes/v0.241/' | relative_url }}) |
| v0.241.006 | [Release notes 0.241 series]({{ '/explanation/release-notes/v0.241/' | relative_url }}) |
| v0.241.002 | [Release notes 0.241 series]({{ '/explanation/release-notes/v0.241/' | relative_url }}) |
| v0.241.001 | [Release notes 0.241 series]({{ '/explanation/release-notes/v0.241/' | relative_url }}) |
| v0.239.002 | [Release notes 0.239 series]({{ '/explanation/release-notes/v0.239/' | relative_url }}) |
| v0.237.049 | [Release notes 0.237 series]({{ '/explanation/release-notes/v0.237/' | relative_url }}) |
| v0.237.011 | [Release notes 0.237 series]({{ '/explanation/release-notes/v0.237/' | relative_url }}) |
| v0.237.009 | [Release notes 0.237 series]({{ '/explanation/release-notes/v0.237/' | relative_url }}) |
| v0.237.007 | [Release notes 0.237 series]({{ '/explanation/release-notes/v0.237/' | relative_url }}) |
| v0.237.006 | [Release notes 0.237 series]({{ '/explanation/release-notes/v0.237/' | relative_url }}) |
| v0.237.005 | [Release notes 0.237 series]({{ '/explanation/release-notes/v0.237/' | relative_url }}) |
| v0.237.004 | [Release notes 0.237 series]({{ '/explanation/release-notes/v0.237/' | relative_url }}) |
| v0.237.003 | [Release notes 0.237 series]({{ '/explanation/release-notes/v0.237/' | relative_url }}) |
| v0.237.001 | [Release notes 0.237 series]({{ '/explanation/release-notes/v0.237/' | relative_url }}) |
| v0.235.025 | [Release notes 0.235 series]({{ '/explanation/release-notes/v0.235/' | relative_url }}) |
| v0.235.012 | [Release notes 0.235 series]({{ '/explanation/release-notes/v0.235/' | relative_url }}) |
| v0.235.003 | [Release notes 0.235 series]({{ '/explanation/release-notes/v0.235/' | relative_url }}) |

## Latest release notes

### **(v0.260.002)**

#### New Features

*   **Documentation Site Now Reflects the v0.260.001 Release**
    *   The documentation site's Latest Release section was a full release behind, still presenting v0.250.001 as current. It now mirrors the same three-tier model the application uses: v0.260.001 as the current release, v0.250.001 as the previous release, and v0.239.001-v0.241.007 in the archive.
    *   Added 20 feature guides for the v0.260.001 release covering enhanced extraction, embedded Office images, workflow task sequences, the MCP platform, the Yamcs and RocksDB actions, agent instruction references, action test connections, Azure Blob file sync, terms of use, audio file support, completion notifications, the chat AI notice, conversation context grounding, used documents on fork, the conversation contents drawer, font size and zoom, message audio export, public workspace display names, and chat scroll accessibility.
    *   (Ref: `docs/_data/latest_release_features.yml`, `docs/latest-release/release-260-*`, `application/single_app/support_menu_config.py`)

*   **Placeholder Screenshots Are Now Tracked**
    *   The v0.260.001 release ships branded "Screenshot pending" placeholder graphics so feature cards render while final captures are pending. Those placeholders are now listed on the documentation media status page with the exact file paths to overwrite, so they are visible work rather than a silent gap.
    *   (Ref: `docs/_data/media_pending.yml`, `/contributing/media-status/`)

#### User Interface Enhancements

*   **Admin Settings Pages Show Real Screenshots**
    *   Fourteen admin settings tab pages were rendering "screenshot needed" placeholders even though real screenshots already existed in the repository. Those pages now display the actual screenshots for the General, AI Models, Search and Extract, Workspaces, File Sync, Workspace Identities, Citation, Safety, Security, Agents, Scale, Control Center, Logging, and Send Feedback tabs.
    *   The four tabs with no captured screenshot still show a placeholder naming the exact file to create, so genuine gaps stay visible.
    *   (Ref: `docs/admin/`, `docs/images/admin-settings/`)

#### Bug Fixes

*   **Release Notes Index No Longer Exceeds Its Page Budget**
    *   The release notes page generator inlined a fixed number of recent releases on its index. The consolidated v0.260.001 rollup is large enough on its own that this pushed the index past the maximum page size and failed generation. The index now fills its inline section by size rather than by count, so a single large rollup cannot break it.
    *   (Ref: `scripts/build_release_notes_pages.py`)

*   **Archived Release Notes Links**
    *   The archived release notes page linked to the internal feature and fix note trees, which are intentionally not published on the documentation site. Those links now point at the repository instead.
    *   (Ref: `docs/explanation/archive_release_notes.md`)

### **(v0.260.001)**

v0.260.001 consolidates all work released after v0.250.001 into one major release note, spanning 117 incremental patch builds. This rollup highlights the major feature, UI, reliability, security, and operations themes while preserving the full per-build history in the Detailed Change Log at the end of this section.

#### Breaking Changes

*   **Workflow Alert Configuration Model**
    *   The legacy single `alert_priority` workflow field is superseded by `alert_mode`, `alert_rules`, and `alert_evaluation` for rules-based workflow notifications.
    *   Existing workflows are auto-migrated on read into equivalent failed-run and completed-run notification rules.
    *   **Migration**: Review upgraded workflow alert rules and prune any always-notify completed-run rule that is no longer desired.
*   **New Yamcs Client Dependency**
    *   The Yamcs Mission Control action adds `yamcs-client==2.1.0`, the repository's first LGPL-3.0 dynamically linked pip dependency.
    *   SimpleChat can still start without it, but Yamcs actions return an actionable dependency error until installed.
    *   **Migration**: Run `pip install -r requirements.txt` or rebuild deployment images so the Yamcs client dependency is present where Yamcs actions are used.
*   **Internal Route Name Hardening**
    *   Blueprint security hardening changed internal route names and required broad route policy/test updates.
    *   Shared-conversation streaming regressions from the rename sequence were fixed in the consolidated patch history.
    *   **Migration**: Update any custom integrations that call SimpleChat by internal endpoint name rather than public route URL.
*   **Conversation Cache Fallback Behavior**
    *   Volatile chat bootstrap and conversation cache payloads no longer fall back to the Cosmos `settings` container when Redis is unavailable.
    *   Deployments without Redis keep full functionality, but bypass these cache benefits.
    *   **Migration**: Configure Redis for deployments that depend on chat bootstrap or conversation cache acceleration.

#### Upgrade Notes

*   **Enhanced Extraction Settings Migration**
    *   Deployments already configured for Enhanced or Auto extraction are automatically migrated on first settings read to preserve their existing extraction mode.
    *   No manual change is required unless admins want to revise extraction defaults after upgrade.
*   **Embedded Image Chunk Placement**
    *   Word and PowerPoint figures are now merged into chunks with surrounding text instead of appended as extra chunks.
    *   Existing documents keep their current chunk layout until re-extracted.
    *   Use Change Extraction or re-upload documents to benefit from the new placement behavior.
*   **Workflow Alert Review**
    *   Rules-based workflow notifications can express run status, text/regex matches, File Sync results, AI-judged outcomes, and agent signals.
    *   Review workflow owner expectations after upgrade because migrated rules intentionally preserve prior notification behavior.
*   **Redis-Backed Cache Operations**
    *   DAI document/tag caches and conversation list/feed caches now include Redis-backed invalidation and metrics behavior.
    *   Monitor Redis availability to keep cache acceleration active; safety-sensitive cache invalidation fails closed when state is unknown.
*   **Detailed Patch Traceability**
    *   The original v0.250.003 through v0.250.229 entries are preserved verbatim below with demoted headings for audit and support lookup.

#### New Features

*   **Enhanced Document Extraction and Analysis**
    *   Azure AI Content Understanding supports AI-generated figure descriptions for PDFs/images, with Auto mode figure detection.
    *   Embedded Office images, including EMF/WMF diagrams and legacy DOC/PPT media, are rasterized, analyzed, and indexed as citable chunks.
    *   Optional Document Intelligence formula extraction adds LaTeX equation capture for PDFs when enabled.
    *   (Ref: Azure AI Content Understanding, Document Intelligence, embedded image extraction, formula extraction)
*   **Workflow Multi-Task Automation and Alerts**
    *   Workflows now support ordered instruction tasks with prior-task context chaining, per-task document actions, retry/failure handling, and configurable task limits.
    *   Conditional alert rules cover run status, text/regex matches, File Sync summaries, AI-judged results, and agent-raised signals across five severity levels.
    *   Active workflow runs can be cancelled from workspace rows, run history, or activity surfaces.
    *   (Ref: workflow task sequencing, workflow alert rules, `raise_workflow_alert`, run cancellation)
*   **Expanded Agent and Action Integrations**
    *   Yamcs and RocksDB action types add mission-control and HTTP/JSON data-service integrations.
    *   Inbound MCP exposes governed SimpleChat capabilities for conversations, documents, prompts, tags, and workflows.
    *   Action connection testing now covers OpenAPI, Maps, Blob, Databricks, Log Analytics, MCP, Snowflake, Tableau, RocksDB, Yamcs, SQL, and Cosmos DB.
    *   (Ref: Yamcs action, RocksDB action, MCP inbound server, action test connection)
*   **Governance, Security, and Model Administration**
    *   Governance policies support explicit block lists for feature and delegated item policies alongside allow rules.
    *   Key Vault secret expiration reminders track per-action secrets with background sweeps, notifications, and telemetry.
    *   Model requests can include HMAC-hashed user identity headers, and admins can configure per-model output token ceilings.
    *   (Ref: governance policies, Key Vault secret inventory, model endpoint identity header, output token limits)
*   **Chat Productivity, Grounding, and Notifications**
    *   Users can opt into response completion sounds, desktop notifications, configurable AI notices, and per-message MP3 export.
    *   Conversation grounding now exposes model/workspace/document/agent context, used-document panes, assistant-response forks, and a contents drawer.
    *   User font size preferences, generated JSON/XML export artifacts, and smarter scroll behavior improve long-session usability.
    *   (Ref: chat notifications, grounding citations, used documents pane, conversation fork, contents drawer, export artifacts)
*   **Workspace, Sync, and Data Management Operations**
    *   Azure Blob Storage File Sync adds SAS, managed identity, service principal auth, virtual-folder browsing, and ETag change detection.
    *   Admin operations add automatic Control Center statistics refresh, backup cleanup/retention, restore workflows, Cosmos JSON editing, Redis Explorer, feedback/safety lifecycle controls, and file-processing log cleanup.
    *   Multi-select metadata extraction, configurable Public Workspace naming, and index auto-login improve workspace administration.
    *   (Ref: File Sync, Control Center, Backup Inventory, Data Management, Redis Explorer, metadata extraction)
*   **Caching, Runtime, and Durable Processing Capabilities**
    *   DAI Redis read-through caches document lists, tag lists, and legacy counts with scope-version invalidation.
    *   Conversation list/feed caching adds Redis hit/miss metrics for Admin Settings visibility.
    *   Durable tabular analyze/search preflight parity, FFmpeg audio runtime support, and the model capability catalog broaden platform readiness.
    *   (Ref: DAI Redis cache, conversation cache metrics, tabular durable preflight, FFmpeg, model capability catalog)

*   **Latest Features Release Tiers for v0.260.001**
    *   Shifted the end-user Latest Features page and Admin Settings tab into current, previous, and archive release tiers for the v0.260.001 rollout.
    *   Preserved per-tenant visibility choices across the shift. The new v0.260.001 user-facing cards ship hidden until their placeholder screenshots are replaced, so admins publish each card once its real capture is in place.
    *   (Ref: Latest Features release groups, support catalog, admin catalog, visibility normalization)
*   **Deeper End-User Feature Cards**
    *   Added 20 v0.260.001 end-user cards with seven concrete How To Try It steps and a three-image gallery each.
    *   Expanded the Latest Features card helper with the `images=[...]` gallery form for multi-image cards.
    *   (Ref: `_latest_feature_card`, `_SUPPORT_RELEASE_260_FEATURE_CATALOG`, Latest Features image galleries)
*   **Admin Latest Features Archive Tier**
    *   Brought the Admin Settings Latest Features tab to the same three-tier current, previous, and archive model used by the end-user page.
    *   Keeps v0.250.001 admin cards and older v0.241.x admin highlights available without crowding the current release tier.
    *   (Ref: `_ADMIN_LATEST_FEATURE_RELEASE_GROUPS`, `_ADMIN_RELEASE_260_FEATURE_CATALOG`, Admin Settings Latest Features tab)
*   **Latest Features PR Workflow Hooks**
    *   Added a Latest Features authoring prompt, PR template checklist, and CI warning path so feature PRs consider release notes, cards, and screenshots together.
    *   Helps future releases keep in-app Latest Features content aligned with shipped user and admin changes.
    *   (Ref: `.github/prompts/update-latest-features.prompt.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `release-notes-check.yml`)

#### User Interface Enhancements

*   **Agent and Workflow Builder Refresh**
    *   Agent configuration now follows Actions → Knowledge → Instructions, with selected actions visible in the Instructions step.
    *   Workflows use a stepped General/Trigger/Tasks/Reliability/Review builder with per-task runner controls and alert-rule editing.
    *   (Ref: agent modal, workflow builder, workflow runner controls, alert rules editor)
*   **Administration and Configuration UX Improvements**
    *   Workspace sections now use a consistent Documents → Prompts → Identities → Sync → Endpoints → Actions → Agents → Workflows order.
    *   Governance policy copy/inverse/show-users actions, dedicated Log Analytics configuration, refreshed backup/migrate/restore flows, and reviewed data migration steps reduce admin friction.
    *   External links can be reordered, custom pages can be opened directly, and non-blocking Bootstrap toasts replace browser alerts across admin, workspace, and profile pages.
    *   (Ref: workspace section order, governance UI, Log Analytics settings, data migration UI, toast notifications)
*   **Chat, Navigation, and Accessibility Enhancements**
    *   Chat, navigation, and sidebar layouts remain usable at 200% zoom and with large text.
    *   The Conversation Contents drawer adds safe labels, keyboard focus handling, active-location tracking, and responsive desktop/mobile navigation.
    *   Long source lists collapse behind a disclosure, document picker rows show file-name context, and Refresh Documents preserves selection with clearer status.
    *   (Ref: 508 usability, conversation contents drawer, source disclosure, document picker, refresh documents)
*   **Data Explorer and Extraction Status UX**
    *   Redis Explorer uses a fixed-height modal with independent key-list and preview scrolling.
    *   Cosmos query results open in a scrollable modal so the main editor stays focused on query setup.
    *   Extraction badges identify the engine that ran and show Content Understanding vs. Document Intelligence fallback reasons.
    *   (Ref: Redis Explorer, Cosmos editor results modal, extraction badges)

*   **Placeholder Screenshots for Pending Captures**
    *   Added 76 branded "Screenshot pending" placeholders so every v0.260.001 Latest Features card renders a valid local image while final captures are pending.
    *   Placeholders can be replaced in place with real screenshots without changing the catalog configuration.
    *   (Ref: `application/single_app/static/images/features/`, Latest Features image galleries)

### **(v0.250.231)**

#### Bug Fixes

*   **Missing Release Highlight Screenshots Now Display**
    *   The Latest Release pages referenced 24 screenshots that were never present in the documentation site, so every one of them rendered as a broken image.
    *   The images already existed in the application at `application/single_app/static/images/features/`, where the in-app Latest Features gallery reads them. They are now also published with the documentation site, so the release highlight pages show the same screenshots users see in the product.
    *   (Ref: `docs/images/latest-release/`, `docs/_data/latest_release_features.yml`, Latest Release highlight pages)

*   **Broken Documentation Links Repaired**
    *   Fixed the remaining broken internal links on the documentation site. Links that pointed at renamed pages now resolve, and links that target files kept in the repository rather than published on the site, such as the Custom Pages developer guide, the Teams app manifest, and a CI workflow, now open on GitHub instead of returning a missing page.
    *   Removed two references to a ServiceNow multi-action setup guide that was never written.
    *   The documentation site now has zero broken internal links across 31,649 checked links.
    *   (Ref: `ui_tests/check_docs_links.js`, ServiceNow guides, Custom Pages guide, upgrade paths guide)

### **(v0.250.230)**

#### New Features

*   **Documentation Site Redesign**
    *   The documentation site was rebuilt for search, navigation, page simplicity, mobile support, and content coverage.
    *   Search now indexes page content instead of titles only. Previously 84% of the 986 indexed pages were internal engineering notes, 88% of entries had no description, and no page body text was indexed at all, so a search for "agent" returned mostly internal fix notes. The index is now 165 entries with a description on every one and no engineering notes.
    *   Added a dedicated search results page with section filters and highlighted excerpts, a `Ctrl+K` shortcut, keyboard navigation, and a full-screen mobile search sheet. Search was previously hidden entirely on phones.
    *   Navigation was rebuilt so the top bar and sidebar expose the same six sections: Start, Guides, Features, Administration, Deploy and operate, and Reference. Coverage went from 27 links to 74, all verified to resolve.
    *   (Ref: `docs/search-index.json`, `docs/assets/js/search.js`, `docs/_config.yml` navigation, `docs/search.md`)

*   **Screenshot and Video Placeholders for Documentation**
    *   Documentation pages can now declare a screenshot or video slot. When the asset does not exist yet the page renders a visible card naming the exact file path to create; adding the file at that path replaces the placeholder automatically on the next build with no configuration or code change.
    *   Videos render as a local poster card that links out to YouTube or Microsoft Stream, so no video files are committed to the repository and no third-party embed scripts are loaded.
    *   Added a media status page listing every slot and whether it is filled, as a capture worklist for contributors.
    *   (Ref: `docs/_includes/media.html`, `docs/_data/media.yml`, `docs/contributing/media-status.md`)

*   **Complete Documentation Coverage of the Application**
    *   Added one page per admin settings tab covering what the tab controls, why it matters, every setting with its default and governing settings key, prerequisites, and the common tasks admins perform there.
    *   Added task guides for creating actions, agents, agents with actions, multi-task workflows, triggering workflows, file sync connectors, tags, tags in chat, tags on conversations, and exporting conversations, plus further guides derived from the application surface. Each guide explains what the task does and why before the steps.
    *   Added a chat interface reference covering all 47 chat controls and an action reference covering all 27 actions.
    *   Added a feature catalog in which every one of the 111 capability toggles is claimed by exactly one capability entry.
    *   (Ref: `docs/admin/`, `docs/guides/`, `docs/reference/chat-controls.md`, `docs/reference/actions/`, `docs/_data/features.yml`)

*   **Documentation Coverage Enforcement**
    *   Added a generated inventory of the application surface and functional tests that fail when a new capability toggle, admin settings tab, action plugin, or chat control ships without documentation, so coverage stays complete as changes land.
    *   (Ref: `scripts/build_docs_inventory.py`, `functional_tests/test_docs_app_surface_coverage.py`, `functional_tests/test_docs_site_quality.py`)

#### User Interface Enhancements

*   **Documentation Site Works on Phones and Tablets**
    *   Standardized the responsive breakpoints, which previously mixed `768px` and `767.98px` and left gaps, and exported the desktop breakpoint to JavaScript so it is no longer duplicated by hand.
    *   Wide tables and long code blocks are now contained in horizontal scroll regions instead of widening the page, images are lazy-loaded with intrinsic sizing, touch targets meet a 44px minimum, and the mobile navigation drawer and search sheet trap and restore focus.
    *   Verified with browser tests at 360x640, 390x844, 768x1024, 1280x800, and 1920x1080.
    *   (Ref: `docs/assets/css/main.scss`, `docs/assets/js/sidebar.js`, `ui_tests/test_docs_site_responsive.js`)

*   **Simpler Documentation Pages**
    *   Landing pages were rewritten from hand-written HTML card markup into plain markdown. The home page previously had 82 blocks of card markup and zero markdown headings, and the features page 119 blocks and zero headings, which meant neither page had a working "On this page" table of contents or heading anchors.
    *   The FAQ was rebuilt so every question is its own heading with a linkable anchor.
    *   The decorative page hero, with its gradient banner, pill row, and icon orb, was replaced with a plain documentation header across the 38 pages that used it.
    *   Split the 452 KB release notes page into per-version-series pages while keeping the existing release notes URL working.
    *   (Ref: `docs/index.md`, `docs/features.md`, `docs/start/faqs.md`, `scripts/build_release_notes_pages.py`)

*   **Documentation URLs Now Match Their Section**
    *   Guides previously lived under three different URL spaces that all meant the same thing. Tutorials and how-to guides are consolidated under `/guides/`, orientation pages moved under `/start/`, deployment scenarios under `/deploy/`, and reference pages under `/reference/`.
    *   **Existing links and bookmarks continue to work.** Every moved page redirects from its old URL, and the URLs the application itself links to were deliberately left unchanged.
    *   (Ref: documentation navigation, `jekyll-redirect-from`, `ui_tests/check_docs_links.js`)

#### Bug Fixes

*   **Documentation Site No Longer Overflows Horizontally on Desktop**
    *   The main content region combined a full-width rule with a sidebar offset, so every desktop viewport scrolled sideways by exactly the sidebar width. This was a long-standing defect on the published site.
    *   (Ref: `.docs-main-content`, `docs/assets/css/main.scss`)

*   **Documentation Section Labels and Page Titles**
    *   Path-scoped Jekyll defaults used collection names as their type and therefore never applied, so nearly every page fell back to a generic "Docs" section and search facets were meaningless. Three scenario index pages also had a comment above their front matter, so it was never parsed and they were titled with their own file path and rendered through an empty layout.
    *   (Ref: `docs/_config.yml` defaults, `docs/explanation/scenarios/`)

*   **Documentation Site Loads No Third-Party Assets**
    *   Removed jQuery, DataTables, marked, DOMPurify, and split.js, none of which the site used, and vendored Bootstrap, Bootstrap Icons, Prism, Lunr, and the site fonts locally with their licenses. The site now makes zero external requests.
    *   (Ref: `docs/assets/vendor/`, `docs/_layouts/default.html`, local browser asset policy)
