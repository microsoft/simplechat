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
| v0.260.024 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.023 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.021 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.020 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.019 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.018 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.017 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.016 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.015 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.014 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.013 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.012 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.011 | [Release notes 0.260 series]({{ '/explanation/release-notes/v0.260/' | relative_url }}) |
| v0.260.010 | [Release notes 0.260 series]({{ '/explanation/release-notes/v0.260/' | relative_url }}) |
| v0.260.009 | [Release notes 0.260 series]({{ '/explanation/release-notes/v0.260/' | relative_url }}) |
| v0.260.008 | [Release notes 0.260 series]({{ '/explanation/release-notes/v0.260/' | relative_url }}) |
| v0.260.007 | [Release notes 0.260 series]({{ '/explanation/release-notes/v0.260/' | relative_url }}) |
| v0.260.006 | [Release notes 0.260 series]({{ '/explanation/release-notes/v0.260/' | relative_url }}) |
| v0.260.005 | [Release notes 0.260 series]({{ '/explanation/release-notes/v0.260/' | relative_url }}) |
| v0.260.004 | [Release notes 0.260 series]({{ '/explanation/release-notes/v0.260/' | relative_url }}) |
| v0.260.003 | [Release notes 0.260 series]({{ '/explanation/release-notes/v0.260/' | relative_url }}) |
| v0.260.002 | [Release notes 0.260 series]({{ '/explanation/release-notes/v0.260/' | relative_url }}) |
| v0.260.001 | [Release notes 0.260 series]({{ '/explanation/release-notes/v0.260/' | relative_url }}) |
| v0.250.231 | [Release notes 0.250 series]({{ '/explanation/release-notes/v0.250/' | relative_url }}) |
| v0.250.230 | [Release notes 0.250 series]({{ '/explanation/release-notes/v0.250/' | relative_url }}) |
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

### **(v0.260.024)**

#### Bug Fixes

*   **Inline Images And Videos Now Show Only Cited Media**
    *   Assistant messages rendered an inline image or video gallery for every media file that retrieval returned, so a search that surfaced five workspace images produced five inline tiles even when the answer referenced only one of them, or none at all. Media that had nothing to do with the answer was presented inside the message bubble as though it supported the answer.
    *   Inline galleries now render only the media the response actually cited. The five-item gallery cap therefore goes to genuinely cited media instead of retrieval noise, and unreferenced workspace files no longer trigger enhanced-citation fetches.
    *   Galleries produced by an action or tool the assistant actually ran are unaffected, since those are executed results rather than unused search candidates. Conversations created before cited-source tracking existed also keep their previous behavior.
    *   The **Sources** disclosure is unchanged and still lists every retrieved document and web result, so nothing becomes harder to find.
    *   (Ref: `chat-citation-tracking.js`, `chat-inline-images.js`, `chat-inline-videos.js`, `chat-messages.js`, `cited_hybrid_citations`, [#1329](https://github.com/microsoft/simplechat/issues/1329))

### **(v0.260.023)**

#### Bug Fixes

*   **Running Simple Chat Directly No Longer Fails To Start When An Agent Has Actions**
    *   Starting Simple Chat with `python app.py` (including via `uv run`) aborted with `RuntimeError: Working outside of request context` whenever any agent had an action assigned. The app started normally until the first action was saved, which made the failure look intermittent.
    *   Semantic Kernel initialization runs before any request exists on that path, but agent plugin loading read the signed-in user from the Flask session. It now resolves the user only when a request is actually in progress and otherwise loads with no user identity, matching how global plugin loading already behaved.
    *   Container and App Service deployments were never affected, because they start through gunicorn and initialize during the first request. Their behavior is unchanged.
    *   Three further identity lookups used for group scope and personal model endpoints had the same latent problem and were corrected at the same time.
    *   (Ref: `semantic_kernel_loader.py`, `functions_authentication.py`, `get_current_user_id_or_none`, issue #1327)

### **(v0.260.021)**

#### Bug Fixes

*   **Documentation Screenshot Viewer Validates Its Image Source**
    *   The documentation site's click-to-enlarge screenshot viewer assigned an image URL taken from a data attribute in the page. Because that value flows from page content into a URL, CodeQL flagged it as a potential DOM-based cross-site scripting sink.
    *   The viewer now resolves the value and requires a same-origin `http` or `https` URL ending in an image extension before using it, so scheme-based payloads such as `javascript:` and `data:` URLs, and any off-site source, are rejected. All documentation media is local, so no legitimate image is affected.
    *   (Ref: `docs/assets/js/media.js`, `safeMediaUrl`, `ui_tests/test_docs_media_lightbox_source_validation.js`, CodeQL `js/xss-through-dom`)

### **(v0.260.020)**

#### New Features

*   **Admin Documentation Rebuilt For The Grouped Settings Layout**
    *   Admin Settings was reorganized from 18 flat tabs into 14 groups containing 44 tabs and 93 settings sections. The documentation was still written against the old flat layout, so it described tabs that no longer exist and omitted the new ones.
    *   The admin documentation is now one page per group, with every tab reachable by its own anchor so links to a specific tab keep working. Every retired tab URL redirects to the group that now owns its settings, so existing links and bookmarks continue to resolve.
    *   (Ref: `docs/admin/`, `application/single_app/admin_settings_nav.py`, `docs/_data/app_surface.yml`)

*   **Collaborating In A Conversation Is Now Documented**
    *   Added a guide covering shared conversations end to end: sharing a conversation, mentioning a participant with `@` and Tab completion, how shared files are approved before they become available, and what participants can and cannot do.
    *   The Blob Storage action reference now explains its managed identity and account key options.
    *   (Ref: `docs/guides/collaborate-in-a-conversation/`, `docs/reference/actions/blob-storage/`, `enable_collaborative_conversations`)

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

*   **Release Notes Pages No Longer Break On Quoted Template Syntax**
    *   Release notes legitimately quote template syntax when describing template work, such as a Jinja `block` tag. The page generator emitted that verbatim, so the site build failed with an unknown tag error. Quoted template syntax is now escaped in generated pages and renders as literal text.
    *   (Ref: `scripts/build_release_notes_pages.py`)

*   **Release Notes Links To Internal Engineering Notes**
    *   Some release note entries linked to the internal feature and fix note trees, which are intentionally not published on the documentation site. Those links now point at the repository.
    *   (Ref: `docs/explanation/release_notes.md`)

*   **Release Notes Index No Longer Exceeds Its Page Budget**
    *   The release notes page generator inlined a fixed number of recent releases on its index. The consolidated v0.260.001 rollup is large enough on its own that this pushed the index past the maximum page size and failed generation. The index now fills its inline section by size rather than by count, so a single large rollup cannot break it.
    *   (Ref: `scripts/build_release_notes_pages.py`)

*   **Archived Release Notes Links**
    *   The archived release notes page linked to the internal feature and fix note trees, which are intentionally not published on the documentation site. Those links now point at the repository instead.
    *   (Ref: `docs/explanation/archive_release_notes.md`)

### **(v0.260.019)**

#### Bug Fixes

*   **Admin Settings Loads Again**
    *   Admin Settings returned a 500 error on every request after the settings restructure. The Document Action Capabilities card moved to the Actions tab but the two values it reads stayed behind in the Agents tab, and each tab is rendered separately, so those values were never there when the card asked for them.
    *   Both values are now defined in the tab that uses them, and a new test renders the two tabs together to keep them there.
    *   (Ref: `admin/_panes/actions.html`, `admin/_panes/agents.html`, document action capabilities)

*   **Server Errors Are Visible In The App Service Log Again**
    *   Once Application Insights was configured it took ownership of logging, which had the side effect of stopping Flask writing unhandled errors to the container log. A failing page left nothing behind but its access-log line, so diagnosing it meant querying Application Insights.
    *   Unhandled errors are now written to both, so the reason for a failure is visible in the App Service log stream.
    *   (Ref: `functions_appinsights.py`, `ensure_console_error_logging`, App Service console logs)

*   **Document Access Index Diagnostics Appear When Enabled**
    *   The Cosmos DB tab checked the wrong thing for the debug setting, so the backfill controls, shadow validation metrics and reset option stayed hidden even after an admin turned the setting on.
    *   (Ref: `admin/_panes/cosmos.html`, `enable_dai_debug`)

### **(v0.260.018)**

#### Bug Fixes

*   **Setup Walkthrough Lands On The Right Settings Again**
    *   The guided setup walkthrough sent each step to a named tab. After the Admin Settings restructure, eleven of its twelve steps named tabs that no longer existed, so those steps would have moved nowhere and left the admin looking at whatever was already on screen.
    *   Each step now names the setting it is about and the tab is worked out from the page, so the walkthrough follows settings wherever they live.
    *   (Ref: setup walkthrough, `admin_settings.js`, `admin_card_links.js`)

*   **Cosmos Throughput Validation Reveals The Invalid Field**
    *   When Cosmos throughput values failed validation, the page tried to switch to a tab that no longer exists, so the field needing attention could be left on a hidden tab with no indication of where to look.
    *   Validation now jumps to wherever the invalid field actually is.
    *   (Ref: Cosmos throughput validation, `admin_settings.js`)

#### User Interface Enhancements

*   **Admin Settings Restructure Merged With Current Development**
    *   Version bump covering the merge of the Admin Settings information architecture work with the generated file output fixes developed in parallel. Both reached v0.260.011 independently, so their release notes are combined under that version.
    *   (Ref: Admin Settings navigation, generated file exports)

### **(v0.260.017)**

#### New Features

*   **All App Role Requirements In One Place**
    *   Ten settings across seven tabs can each require an Entra app role, which made the overall access policy impossible to read without hunting through the whole of Admin Settings.
    *   **Security → Access & Roles** now lists every one of them with a switch and a link to the setting in its own tab. Changing a switch here changes the setting itself.
    *   The list is built from the page, so a new role requirement added anywhere appears here automatically.
    *   (Ref: `app-role-requirements-section`, `admin_access_roles_roster.js`)

#### User Interface Enhancements

*   **System Settings Card Split To Where Each Setting Belongs**
    *   One card mixed maximum file size, conversation history, idle timeout, the default system prompt and the access denied message — five unrelated concerns under one heading.
    *   Maximum File Size is now in **Workspaces → Files & Sharing**, Conversation History and Default System Prompt in **Chat → Chat Experience**, and Access Denied Message in **Security → Access & Roles**.
    *   What remains in **Security → Session** is the idle timeout, and the card is now named for it.
    *   Every setting keeps its saved value; nothing needs re-entering.
    *   (Ref: `idle-timeout-section`, `file-size-limit-section`, `conversation-history-section`, `default-system-prompt-section`, `access-denied-message-section`)

### **(v0.260.016)**

#### User Interface Enhancements

*   **Backup, Migrate & Restore Split Into Five Tabs**
    *   One tab carried the entire backup, migration, restore, Cosmos editing and job history surface — over 1,600 lines in a single scroll.
    *   Backup & Recovery now has **Backup** (readiness, backup, schedule, storage, encryption), **Migrate**, **Restore**, **Cosmos Editor** and **Jobs**.
    *   The save button, status line and operational-hours warning are shared by all five tabs, so they sit above the tabs and stay available wherever you are in the group.
    *   This completes the Admin Settings restructure: **14 groups and 44 tabs**, from an original 17 flat tabs.
    *   (Ref: `backup`, `migrate`, `restore`, `cosmos-editor`, `jobs`)

#### Bug Fixes

*   **Backup Dialogs Remain Available From Every Tab**
    *   The eleven Backup & Recovery dialogs are opened from more than one place and several are opened from code rather than a button. Left inside a tab, a dialog cannot appear while a different tab is showing.
    *   They now sit outside the tabs, so restore, migration cancel, job detail, the Cosmos editor dialogs and the five setup guides all open wherever they are triggered from.
    *   (Ref: Backup & Recovery dialogs, `admin_data_management.js`)

*   **Shared Controls Work In Both Navigation Layouts**
    *   Shared group controls resolve their group from whichever navigation is on screen, so the Backup & Recovery save button is present in the sidebar layout as well as the tab layout.
    *   (Ref: `data-admin-group-shared`, `admin_sidebar_nav.js`)

### **(v0.260.015)**

#### User Interface Enhancements

*   **AI Models Split By Model Purpose**
    *   AI Models presented every model setting on one tab. It is now **Model Endpoints** (endpoint and fallback configuration, plus the Chat Model dialog opened from it), **Embeddings** and **Image Generation**.
    *   (Ref: `model-endpoints`, `embeddings`, `image-generation`)

*   **Agents And Actions Are Now Separate Tabs**
    *   A single "Agents and Actions" tab carried agent configuration, template approvals, document action capabilities, action configuration and the whole inbound MCP surface.
    *   It is now **Agents**, **Actions** and **Inbound MCP**.
    *   Inbound MCP is a large area with its own dialogs and diagnostics, and the whole tab is hidden when the inbound MCP interface is turned off rather than showing an empty tab.
    *   (Ref: `agents`, `actions`, `inbound-mcp`)

#### Bug Fixes

*   **Model Setup Guide Available From Every Model Tab**
    *   The Azure OpenAI Model Setup Guide dialog is opened from the endpoints, embeddings and image generation cards. Once those moved to separate tabs it could only have opened from one of them.
    *   The dialog now sits outside the tabs, so it opens from all three.
    *   (Ref: `legacyModelDiscoveryIdentityGuideModal`)

*   **Dangling Section Comments Removed**
    *   Seven tabs ended with a comment labelling a card that had since moved to another tab.
    *   (Ref: admin settings tab panes)

### **(v0.260.014)**

#### User Interface Enhancements

*   **Knowledge Settings Split By What They Actually Do**
    *   Search & Extract held eight cards spanning four unrelated jobs, from Bing consent to voice transcription.
    *   Knowledge now has **Web & Research** (web search, URL access, deep research), **Search Index** (Azure AI Search), **Document Extraction** (document intelligence, chunk sizes, plus metadata extraction and multi-modal vision brought over from Workspaces) and **Audio & Video** (video intelligence, voice conversations), alongside the existing File Sync.
    *   Voice and video sit under Knowledge rather than Chat because they are extraction pipelines that turn recordings into searchable content.
    *   (Ref: `web-research`, `search-index`, `extraction`, `audio-video`)

*   **Workspaces Focused On Workspaces**
    *   Workspaces mixed workspace types with file rules, workflow and extraction settings.
    *   It is now **Workspace Types** (personal, group, public), **Files & Sharing** (downloads, sharing, and shared conversation file approvals brought over from AI Models) and the existing Global Identities.
    *   (Ref: `workspace-types`, `files-sharing`)

*   **Workflow Is Its Own Area**
    *   Workflow drives approvals and assignment across every workspace type and was too large to sit as one card inside Workspaces. It now has its own group.
    *   (Ref: `workflow`, `workflow-settings-section`)

#### Bug Fixes

*   **Group Workflow Assignment Dialog Could Not Open**
    *   The Group Workflow Assignment dialog ended up in a different tab from the button that opens it. Because an inactive tab is hidden, the dialog would not have appeared at all.
    *   The dialog now sits with its button, and a new check verifies this for every dialog in Admin Settings so it cannot happen again.
    *   (Ref: `groupWorkflowAssignmentModal`, `test_admin_settings_modal_placement.py`)

*   **Misplaced Section Comments In AI Models**
    *   Two section comments had drifted onto the wrong cards while settings were being regrouped, labelling the embeddings card as processing thoughts.
    *   (Ref: `ai-models` pane)

### **(v0.260.013)**

#### User Interface Enhancements

*   **General Tab Broken Up Into Focused Tabs**
    *   General had grown into a catch-all of eleven unrelated cards: branding sat next to health checks, API documentation, terms of use and system settings.
    *   Appearance now has **Branding** (branding, home page text, appearance), **Notices & Agreements** (classification banner, chat AI notice, terms of use and the user agreement pulled across from Workspaces) and **Pages & Links** (static pages plus external links).
    *   Health Check and API Documentation moved to Operations, which is now **Logging & Health** — they report on how the app is running rather than how it looks.
    *   Support moved to Help as its own **Support Menu** tab, next to Send Feedback.
    *   (Ref: `branding`, `notices`, `custom-pages`, `logging`, `support-menu`)

*   **Security Split Into Five Purposeful Tabs**
    *   Security held a single Key Vault card while an unrelated Safety tab mixed content filtering with role permissions, which are different jobs.
    *   Security is now **Access & Roles** (who gets in and with what role), **Secrets** (Key Vault), **Content Safety** (what may be said once you are in), **Session** (idle timeout and related system settings) and **Network** (Azure Front Door).
    *   (Ref: `access-roles`, `secrets`, `content-safety`, `session`, `network`)

#### Bug Fixes

*   **"Open Key Vault Settings" Link No Longer Depends On A Hardcoded Tab**
    *   The link from Data Management to Key Vault switched tabs by a hardcoded id, so it silently stopped working whenever that tab was renamed.
    *   It now uses the standard card link, which finds the owning tab from the page itself and stays correct however the settings are grouped.
    *   (Ref: `data-management-key-vault-link`, `admin_card_links.js`, `admin_data_management.js`)

*   **Admin Settings Always Opens On A Real Tab**
    *   The tab shown on arrival was pinned to a specific id in both the markup and the sidebar script. Regrouping settings could leave Admin Settings opening with no tab selected at all.
    *   The landing tab is now taken from the navigation map, so it follows the settings and can never be Latest Features.
    *   (Ref: `admin_landing_tab`, `get_landing_tab_id`, `admin_sidebar_nav.js`)

*   **Stale Tab Names In Latest Features**
    *   Several Latest Features entries pointed readers at tabs by their old names after the settings moved.
    *   (Ref: `latest-features` pane)

### **(v0.260.012)**

#### User Interface Enhancements

*   **New Data Lifecycle Group For Retention, Classification And Archiving**
    *   Retention policy, document classification and conversation archiving all decide how long content lives and how it is labelled, but they were split across Workspaces and Safety. They now sit together in a **Data Lifecycle** group with a tab each: **Retention**, **Classification** and **Archiving**.
    *   Conversation archiving in particular was buried under Safety, which described what it protects against rather than what it does.
    *   (Ref: navigation map, `retention-policy-section`, `document-classification-section`, `conversation-archiving-section`)

*   **Chat Group Gathers The Settings That Shape A Conversation**
    *   Settings that change what a conversation looks and behaves like were spread across AI Models, Workspaces and Safety. The **Chat** group now holds them in two tabs.
    *   **Chat Experience** collects model thought display, chat file uploads (with the conversation contents drawer) and workspace scope lock.
    *   **Feedback & Alerts** collects user feedback and desktop notifications, which are both about how the app talks back to the user rather than about safety enforcement.
    *   (Ref: `chat-experience`, `feedback-alerts`, `processing-thoughts-section`, `chat-file-uploads-section`, `workspace-scope-lock-section`, `user-feedback-section`, `desktop-notifications-section`)

*   **Settings Keep Their Values Through The Move**
    *   Cards were relocated between tabs without renaming a single field, so every saved value is preserved and the form submits exactly the payload it did before.
    *   Sidebar search still finds a setting by group, tab or card name, so you can reach anything without knowing where it now lives.
    *   (Ref: admin settings field contract, `admin_settings_nav.py`)
