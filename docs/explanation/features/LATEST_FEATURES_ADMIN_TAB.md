# Latest Features Admin Tab (v0.240.067)

## Overview
This feature adds a dedicated **Latest Features** tab to Admin Settings so administrators can review the most important recent capabilities in one place and decide what to communicate to users.

Version Updated: 0.240.067

## Dependencies
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/functions_settings.py`
- `application/single_app/route_frontend_admin_settings.py`

## Implemented in version: **0.240.003**

## Technical Specifications

### Admin Settings Placement
- The tab is added directly to the existing Admin Settings tab list.
- It is positioned near the front of the page so administrators can review new functionality early.
- Content is grouped into collapsible cards to keep the page readable even as additional features are added in future releases.

### Feature Grouping
The tab groups recent functionality into broader themes instead of listing every release note entry separately:
- Release Notifications Registration
- Guided Tutorials
- Background Chat Completion
- Multi-Endpoint GPT Selection
- Tabular Data Analysis
- Citation Improvements
- Document Revisioning and Management
- Conversation Summaries and Export
- Agent and Action Operations
- AI Transparency
- Deployment and Runtime Guidance
- Redis and Key Vault
- Send Feedback
- Support Menu

### Mirrored Settings
Two high-impact configuration areas are mirrored in the Latest Features tab:
- `enable_thoughts`
- Enhanced Citations settings:
  - `enable_enhanced_citations`
  - `office_docs_authentication_type`
  - `office_docs_storage_account_url`
  - `office_docs_storage_account_blob_endpoint`
  - `tabular_preview_max_blob_size_mb`
- Redis cache settings:
  - `enable_redis_cache`
  - `redis_url`
  - `redis_auth_type`
  - `redis_key`

The mirrored controls are UI proxies only. They do not create new saved settings. JavaScript keeps them synchronized with the canonical controls in the existing tabs.

### Screenshot Gallery Strategy
Saved screenshots are rendered directly from:
- `application/single_app/static/images/features/`

Current screenshots surfaced in the admin UI:
- `guided_tutorials_chat.png`
- `guided_tutorials_workspace.png`
- `background_completion_notifications-01.png`
- `background_completion_notifications-02.png`
- `model_selection_multi_endpoint_admin.png`
- `model_selection_chat_selector.png`
- `tabular_analysis_enhanced_citations.png`
- `citation_improvements_history_replay.png`
- `citation_improvements_amplified_results.png`
- `document_revision_workspace.png`
- `document_revision_delete_compare.png`
- `enable_support_menu_for_end_users.png`
- `conversation_summary_card.png`
- `pdf_export_option.png`
- `per_message_export_menu.png`
- `agent_action_grid_view.png`
- `sql_test_connection.png`
- `thoughts_visibility.png`
- `gunicorn_startup_guidance.png`
- `redis_key_vault.png`
- `support_menu_entry.png`

Each screenshot now renders as a thumbnail in the Latest Features tab. Clicking a thumbnail opens a larger popup modal with a close button, and clicking outside the popup also dismisses it. The popup styling is tuned for both light and dark themes so the caption text, framed image surface, and modal shell remain easy to distinguish.

The GPT selection, citation improvement, document revision, and Support Menu entries now use saved PNG screenshots so the admin preview matches the user-facing feature surfaces more closely.

The release notifications registration explainer is intentionally text-only. It points admins to a live control that already exists at the top of Admin Settings, so no duplicate screenshot is needed.

### New Feature Coverage
- **Release Notifications Registration** explains the Registered or Unregistered badge beside the version number, clarifies that it is admin-only, and tells admins that clicking it opens the modal used to register this environment for release updates.
- **Multi-Endpoint GPT Selection** highlights the admin workflow for enabling multiple model endpoints, surfacing different GPT choices, and configuring the default fallback model used when a request does not provide an explicit selection.
- **Citation Improvements** explains conversation history citation replay and citation amplification so admins understand why follow-up questions stay grounded even when the assistant is working from prior evidence.
- **Document Revisioning and Management** explains that same-name uploads create versioned revision families, keep previous versions available for traceability, and carry classifications and tags forward to the newest revision.
- **Support Menu** introduces the user-facing support surface that exposes Latest Features and Send Feedback outside the admin-only experience.
- **User-Facing Latest Features in General Settings** gives admins a direct visual reminder that the General tab controls which latest-feature cards are shared with end users.

## Usage Instructions
- Open **Admin Settings**.
- Select **Latest Features**.
- Expand any card to review the feature summary and the saved screenshots.
- Click any screenshot thumbnail to open a larger preview modal.
- Use the Release Notifications Registration card to explain what the Registered or Unregistered badge means and where admins can update that status.
- Use the mirrored toggles when you want to enable Processing Thoughts or Enhanced Citations directly from the overview page.
- Use the GPT Selection card to direct admins to the AI Models tab when they need to review endpoint availability or the default fallback model.
- Use the Citation Improvements card to explain how grounded evidence is preserved across follow-up turns.
- Use the Document Revisioning card to explain why same-name uploads now create a new current version instead of replacing the old file in place.
- Use the mirrored Redis cache controls when you want to review or update cache settings from the overview page without leaving Latest Features.
- Use the deployment guidance card if you run the native Python App Service variant and need the Gunicorn startup command.
- Use the Send Feedback card to jump directly into the admin mailto workflow for bug reports and feature requests.
- Use the Support Menu card as a communication aid for end-user help and feedback workflows, including the General-tab checklist that controls user-facing latest-feature sharing.

## Testing and Validation
- Confirm the Latest Features tab renders in Admin Settings.
- Confirm each card expands and collapses correctly.
- Confirm the admin-only Release Notifications Registration card renders first and does not depend on a screenshot asset.
- Confirm saved screenshots render as thumbnails and open in the larger preview modal.
- Confirm the saved screenshots render for GPT Selection, Citation Improvements, Document Revisioning, Support Menu, and the General-tab user-facing latest-features checklist.
- Confirm the preview modal closes from both the close button and backdrop click.
- Confirm mirrored settings remain synchronized with the canonical controls in the existing tabs.
- Confirm Redis mirror controls stay synchronized with the canonical settings in the Scale tab.
- Confirm the page restores the active tab after save when Latest Features was the current tab.
- Confirm the Send Feedback card links into the dedicated Send Feedback tab.