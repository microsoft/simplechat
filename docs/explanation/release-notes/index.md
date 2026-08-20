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
| v0.260.020 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.019 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.018 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.017 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.016 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.015 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.014 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.013 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.012 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.011 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.010 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
| v0.260.009 | [Release notes index]({{ '/explanation/release_notes/' | relative_url }}) |
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

### **(v0.260.011)**

#### User Interface Enhancements

*   **Governance And Scale Split Into Focused Tabs**
    *   Governance held five cards covering three different jobs. It is now **Feature Governance** (which features are governed), **Policies** (the policies themselves), and **MCP Governance**.
    *   Scale mixed cache configuration with Cosmos capacity, and is now **Redis & Caching** and **Cosmos**.
    *   **Azure Front Door** moved out of Scale into Security, under a new **Network** tab. It configures authentication and redirect flows rather than throughput, so it never belonged with capacity settings.
    *   Existing links and bookmarks to `#governance` and `#scale` still work and land on the first tab of each group.
    *   No settings changed. Every option keeps its name and its saved value.
    *   (Ref: navigation map, `feature-governance`, `governance-policies`, `mcp-governance`, `redis-caching`, `cosmos`, `network`)

#### Bug Fixes

*   **Governance Status Messages No Longer Get Stuck On One Tab**
    *   The inline governance status message lived inside the Governance pane, so a message raised while working in one area could end up rendered on a tab you were not looking at.
    *   It now sits outside the tabs and is visible wherever you are in Governance.
    *   (Ref: `governance-status`, `admin_governance.js`)

#### Bug Fixes

*   **Reliable File Generation From Agent Action Results**
    *   Asking an agent for a downloadable file built from action results now produces the complete dataset in the requested format. Previously these requests could fail outright, publish a three-row sample of a large result, overwrite the assistant's written answer, or return nothing at all. Delivered across v0.260.004 through v0.260.011.
    *   **Files no longer fail to generate.** A CSV built from several actions in one turn could stop with `Generated output schema mismatch at row 2`, because each action returned a different set of columns. The export now pins a union of every column before the run starts and pads the missing cells, so mixed-shape results serialize instead of failing.
    *   **The written answer is no longer replaced by the file card.** CSV replies were suppressed alongside JSON and XML, but only JSON and XML withhold their payload from the response. CSV, DOCX, and PDF now keep the assistant's answer and append the file card beneath it.
    *   **Files contain the retrieved data, not a sample of it.** When the assistant pasted a few example rows above its answer, that excerpt outranked the real result set, producing a 3-row file from a 900-row query. Pasted rows are now used only when they are not an excerpt of the data actually retrieved.
    *   **Discovery calls no longer dilute the dataset.** A turn that lists instances, lists parameters, then retrieves history used to blend all three into one file. Rows are grouped by the action that produced them, and the action holding the substantive dataset wins.
    *   **Follow-up requests reuse data already gathered.** Asking "now make that a CSV" after the data was retrieved in an earlier turn no longer returns an empty result. The export reaches back through stored conversation citations, bounded by the **conversation history limit** in Admin Settings, and reuses the rows already collected instead of re-querying the source.
    *   **Answering a clarifying question now delivers the file.** When the assistant asks which rows and columns to include, replying "yes, all columns" now publishes the file that was originally requested. The clarification turn itself no longer publishes a placeholder file built from the question text.
    *   **The assistant no longer claims it cannot create files.** Every format now states the publication contract to the model, including on the turn that only answers a clarification, so replies stop saying "I cannot create or attach a file in this interface" and then producing one anyway.
    *   **Overlapping result pages no longer double the row count.** Agents frequently re-request a range from the same start time rather than paging forward, which produced a 1,000-row file for a window holding roughly 500 distinct records. Rows an earlier page of the same action already returned are dropped, while genuinely repeated records inside a single response are preserved.
    *   **Partial data is now labeled.** When an action reports that it truncated its own results, the file carries a **Partial** badge and a note explaining that it covers only the rows the action returned. Agents are also instructed to request the remainder starting after the last row they already hold, rather than repeating the original range.
    *   **CSV, DOCX, PDF, JSON, and XML now behave identically.** All five formats resolve rows the same way, reach back to earlier turns, decline to publish on a clarification turn, and report truncation.
    *   (Ref: `functions_generated_file_exports.py`, `functions_tabular_generated_exports.py`, `route_backend_chats.py`, `chat-messages.js`, [Generated Artifact Paging, Truncation, and Guidance Carry-Forward Fix](https://github.com/microsoft/simplechat/blob/main/docs/explanation/fixes/GENERATED_ARTIFACT_PAGING_AND_GUIDANCE_FIX.md), Refs #1071)

### **(v0.260.010)**

#### New Features

*   **Admin Settings Navigation Is Now Grouped**
    *   Admin Settings presented 18 tabs in one flat list. Related tabs are now collected under 12 groups such as Appearance, Knowledge, Security and Operations, so the list is scannable and has room to grow.
    *   In the sidebar, groups are collapsible and remember whether you left them open. In the tab layout, a row of group pills filters the tab strip to one group at a time.
    *   Opening a tab always reveals its group first, so a deep link or a cross-reference can never land you on a pane whose tab is hidden.
    *   Sidebar search now matches group names as well as tab and setting names, and expands whatever it needs to show a result.
    *   No settings moved in this release. Every tab keeps its contents; only the navigation around them changed.
    *   (Ref: `admin_settings_nav.py`, `_sidebar_nav.html`, `admin_settings.html`, `admin_sidebar_nav.js`)

#### Bug Fixes

*   **Shared Conversation File Approvals Is Reachable From The Sidebar**
    *   The Shared Conversation File Approvals card had no navigation entry, so it could only be found by scrolling the AI Models tab. It is now listed like every other setting.
    *   (Ref: `shared-conversation-file-approvals-section`, navigation map)

*   **Navigation Labels And Order Can No Longer Drift**
    *   The tab strip and the sidebar each maintained the same structure by hand and had diverged: tab order differed between them, and Agents, Custom Pages and Search and Extract each showed a different name depending on which navigation you used.
    *   Both now render from one definition, so a change is made once and appears in both.
    *   (Ref: `admin_settings_nav.py`, `test_admin_settings_nav_map.py`)

### **(v0.260.009)**

#### New Features

*   **Admin Settings Form Field Contract Is Now Enforced**
    *   Admin Settings submits one form and the backend reads every value by field name, so the set of `name` attributes is the real contract between the template and the settings backend. Renaming or dropping one silently stops that setting from saving, with no error anywhere.
    *   A new test pins every field name against a committed baseline, and fails the build if one disappears. Adding settings is unaffected; removing one now requires regenerating the baseline in the same commit, which makes it a visible, reviewed decision.
    *   The same test rejects duplicate field names, which is what prevents a mirrored control from submitting a value twice.
    *   (Ref: `test_admin_settings_field_contract.py`, `admin_settings_field_baseline.json`)
