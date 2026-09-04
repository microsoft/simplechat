# admin_settings_fields.py
"""Declarative field definitions for the Admin Settings surface.

``admin_settings_nav.py`` says which groups, tabs and sections exist. It does
not say which settings live inside a section, because the server-rendered
Admin Settings page answers that with hand-written markup in
``templates/admin/_panes/``.

The V2 React admin surface cannot read that markup. Without a machine-readable
description it can only discover settings by scanning the settings document for
``enable_*`` booleans, which is why it could render switches and nothing else:
titles, colours, selects, ranges, uploads and repeatable lists are all
invisible to that scan.

This module supplies the missing description. Each section id from ``ADMIN_NAV``
maps to an ordered list of fields, and each field carries everything a generic
renderer needs -- type, label, help text, default, bounds, options and
visibility dependencies.

Two things keep this honest rather than becoming a third source of truth:

``LEGACY_FIELD_NAMES``
    Records the server-rendered form field names each entry replaces, including
    the places where V1's form shape differs from the stored settings key. The
    parity functional test walks the V1 panes and fails when a form field is not
    claimed here, so a setting cannot exist in one interface only.

``normalize_admin_settings_updates``
    Validates and coerces incoming values against these definitions, delegating
    to the same normalizers the server-rendered form uses. Both interfaces
    therefore agree on what a valid value is.

Only the Appearance and Chat groups are described in full so far. Sections with
no entry here fall back to the V2 surface's ``enable_*`` scan, so undescribed
groups keep working exactly as they did. A handful of individual fields outside
those groups are also declared: that scan places a key by guessing from shared
word stems, and declaring a field is the only way to stop it guessing wrong.

``SUPPRESSED_CAPABILITY_KEYS`` covers the opposite case -- a boolean the scan
would draw but which is not an editable setting at all.
"""

import re
from urllib.parse import urlparse

from admin_settings_secret_utils import (
    ADMIN_SETTINGS_SECRET_REDACTED_VALUE,
    resolve_admin_settings_secret_value,
)
from functions_ai_notice import (
    AI_NOTICE_MAX_MESSAGE_LENGTH,
    normalize_ai_notice_frequency,
    normalize_ai_notice_message,
)
from functions_terms_of_use import (
    TERMS_OF_USE_DEFAULT_REDIRECT,
    TERMS_OF_USE_MAX_BUTTON_TEXT_LENGTH,
    TERMS_OF_USE_MAX_MESSAGE_LENGTH,
    TERMS_OF_USE_MAX_TITLE_LENGTH,
    normalize_terms_of_use_frequency,
    normalize_terms_of_use_redirect_url,
    normalize_terms_of_use_text,
)

HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")

# Field types the V2 renderer knows how to draw. A type outside this set is a
# schema bug, and the schema test fails on it rather than the browser silently
# rendering nothing.
FIELD_TYPES = (
    "text",
    "textarea",
    "secret",
    "select",
    "switch",
    "checkbox_set",
    "color",
    "range",
    "number",
    "image",
    "link_list",
    "component",
)

# Types that own their persistence outside the settings PATCH: image uploads go
# through the multipart branding endpoint, and components talk to their own API.
NON_PATCHABLE_TYPES = ("image", "component")

# Keys the settings PATCH must refuse outright.
#
# ``model_endpoints`` holds each endpoint's API key and client secret inside the
# list, so the admin surface is served a sanitized copy with those stripped.
# Writing that copy back would erase every credential it removed. The V2 surface
# has no editor for it, so refusing is safe and keeps a malformed or hostile
# payload from destroying the endpoint configuration.
NON_PATCHABLE_KEYS = {
    "model_endpoints": (
        "Model endpoints hold credentials that are stripped before they reach "
        "the browser, so they cannot be saved from here."
    ),
}

LANDING_PAGE_ALIGNMENTS = ("left", "center", "right")
USER_AGREEMENT_APPLY_TO_VALUES = ("personal", "group", "public", "chat")

LOGO_SCALE_MIN_PERCENT = 50
LOGO_SCALE_MAX_PERCENT = 500
LOGO_SCALE_DEFAULT_PERCENT = 100

# Advisory, not enforced. The server-rendered form warns and saves anyway, so
# rejecting the value here would lock an administrator out of editing a section
# that already holds a longer agreement.
USER_AGREEMENT_WORD_LIMIT = 200

CLASSIFICATION_BANNER_DEFAULT_COLOR = "#ffc107"
CLASSIFICATION_BANNER_DEFAULT_TEXT_COLOR = "#ffffff"

# Schemes permitted for administrator-configured navigation links. These render
# into an anchor href, so allowing arbitrary schemes would let a saved link
# carry javascript: into every page's navigation.
EXTERNAL_LINK_ALLOWED_SCHEMES = ("http", "https")


ADMIN_SETTINGS_FIELDS = {
    "branding-section": [
        {
            "key": "app_title",
            "type": "text",
            "label": "Application Title",
            "help": "Shown in the browser tab, the header and the landing page.",
            "default": "Simple Chat",
            "max_length": 120,
        },
        {
            "key": "show_logo",
            "type": "switch",
            "label": "Show Logo",
            "help": "Display the application logo in the header and navigation areas.",
            "default": False,
        },
        {
            "key": "hide_app_title",
            "type": "switch",
            "label": "Hide Application Title",
            "help": "Show only the logo in the header and navigation.",
            "default": False,
        },
        {
            "key": "landing_page_logo_scale_percent",
            "type": "range",
            "label": "Main Page Logo Size",
            "help": (
                "Adjusts the logo on the home page only. Navigation logo size is "
                "unaffected."
            ),
            "default": LOGO_SCALE_DEFAULT_PERCENT,
            "min": LOGO_SCALE_MIN_PERCENT,
            "max": LOGO_SCALE_MAX_PERCENT,
            "step": 10,
            "suffix": "%",
            "depends_on": {"key": "show_logo", "equals": True},
        },
        {
            "key": "custom_logo_base64",
            "type": "image",
            "label": "Custom Logo (Light Mode)",
            "help": (
                "Stored at up to 500px tall so the home page can enlarge it without "
                "keeping an oversized asset in settings."
            ),
            "upload_target": "logo",
            "accept": ".png,.jpg,.jpeg",
            "version_key": "logo_version",
        },
        {
            "key": "custom_logo_dark_base64",
            "type": "image",
            "label": "Custom Logo (Dark Mode)",
            "help": "Falls back to the light mode logo when no dark variant is uploaded.",
            "upload_target": "logo_dark",
            "accept": ".png,.jpg,.jpeg",
            "version_key": "logo_dark_version",
        },
        {
            "key": "custom_favicon_base64",
            "type": "image",
            "label": "Custom Favicon",
            "help": "Converted to a 32x32 ICO. Upload a square image for best results.",
            "upload_target": "favicon",
            "accept": ".png,.jpg,.jpeg,.ico",
            "version_key": "favicon_version",
        },
    ],
    "home-page-text-section": [
        {
            "key": "landing_page_alignment",
            "type": "select",
            "label": "Markdown Alignment",
            "help": "How the landing page markdown is aligned on the home page.",
            "default": "left",
            "options": [
                {"value": "left", "label": "Left"},
                {"value": "center", "label": "Center"},
                {"value": "right", "label": "Right"},
            ],
        },
        {
            "key": "enable_landing_page_editor",
            "type": "switch",
            "label": "Enable Markdown Editor",
            "help": (
                "When off, the landing page text is shown as a read-only preview "
                "instead of an editable field."
            ),
            "default": False,
        },
        {
            "key": "landing_page_text",
            "type": "textarea",
            "label": "Landing Page Text",
            "help": "Markdown is supported.",
            "default": "",
            "rows": 8,
            "markdown": True,
            "max_length": 20000,
            "depends_on": {"key": "enable_landing_page_editor", "equals": True},
        },
    ],
    "appearance-section": [
        {
            "key": "enable_dark_mode_default",
            "type": "switch",
            "label": "Enable Dark Mode by Default",
            "help": "Users can still switch themes individually.",
            "default": False,
        },
        {
            "key": "enable_left_nav_default",
            "type": "switch",
            "label": "Enable Left Nav by Default",
            "help": "Users can still toggle the sidebar individually.",
            "default": True,
        },
    ],
    "classification-banner-section": [
        {
            "key": "classification_banner_enabled",
            "type": "switch",
            "label": "Enable Classification Banner",
            "help": "Shows a data sensitivity banner at the top of every page.",
            "default": False,
        },
        {
            "key": "classification_banner_text",
            "type": "text",
            "label": "Banner Text",
            "default": "",
            "max_length": 200,
            "depends_on": {"key": "classification_banner_enabled", "equals": True},
        },
        {
            "key": "classification_banner_color",
            "type": "color",
            "label": "Banner Color",
            "default": CLASSIFICATION_BANNER_DEFAULT_COLOR,
            "depends_on": {"key": "classification_banner_enabled", "equals": True},
        },
        {
            "key": "classification_banner_text_color",
            "type": "color",
            "label": "Banner Text Color",
            "default": CLASSIFICATION_BANNER_DEFAULT_TEXT_COLOR,
            "depends_on": {"key": "classification_banner_enabled", "equals": True},
        },
        {
            "type": "component",
            "component": "classification-banner-preview",
            "label": "Preview",
            "depends_on": {"key": "classification_banner_enabled", "equals": True},
        },
    ],
    "ai-notice-section": [
        {
            "key": "enable_ai_notice",
            "type": "switch",
            "label": "Show a custom AI notice below the chat input",
            "help": (
                "Displays an administrator-provided reminder directly below the chat "
                "composer."
            ),
            "default": False,
        },
        {
            "key": "ai_notice_message",
            "type": "textarea",
            "label": "Notice Text",
            "help": "Plain text only. Line breaks are preserved.",
            "default": "",
            "rows": 3,
            "max_length": AI_NOTICE_MAX_MESSAGE_LENGTH,
            "placeholder": (
                "AI-generated responses may contain errors. Review important "
                "information before relying on it."
            ),
            "depends_on": {"key": "enable_ai_notice", "equals": True},
        },
        {
            "key": "ai_notice_frequency",
            "type": "select",
            "label": "Display Behavior",
            "help": (
                "Changing the notice text or display behavior creates a new message "
                "version and shows it again."
            ),
            "default": "non_dismissible",
            "options": [
                {"value": "non_dismissible", "label": "Always visible; users cannot dismiss it"},
                {"value": "every_session", "label": "Dismissible once per session"},
                {"value": "daily", "label": "Dismissible once per day"},
                {"value": "once", "label": "Dismissible once per message version"},
            ],
            "depends_on": {"key": "enable_ai_notice", "equals": True},
        },
    ],
    "terms-of-use-section": [
        {
            "key": "enable_terms_of_use",
            "type": "switch",
            "label": "Require terms of use",
            "help": (
                "Users must accept before reaching authenticated pages or APIs. "
                "Passive sign-in flows are gated immediately after the session is "
                "created."
            ),
            "default": False,
        },
        {
            "key": "terms_of_use_title",
            "type": "text",
            "label": "Popup Title",
            "default": "Terms of Use",
            "max_length": TERMS_OF_USE_MAX_TITLE_LENGTH,
            "depends_on": {"key": "enable_terms_of_use", "equals": True},
        },
        {
            "key": "terms_of_use_frequency",
            "type": "select",
            "label": "Show Frequency",
            "help": (
                "Changing the title, message or frequency creates a new terms version "
                "that users must accept again."
            ),
            "default": "once",
            "options": [
                {"value": "every_session", "label": "At the start of every session"},
                {"value": "daily", "label": "Once per day"},
                {"value": "once", "label": "Just once per terms version"},
            ],
            "depends_on": {"key": "enable_terms_of_use", "equals": True},
        },
        {
            "key": "terms_of_use_message",
            "type": "textarea",
            "label": "Terms of Use Message",
            "help": "Plain text is shown to users with line breaks preserved.",
            "default": "",
            "rows": 7,
            "max_length": TERMS_OF_USE_MAX_MESSAGE_LENGTH,
            "placeholder": (
                "Enter the terms, notice, or rules of behavior users must accept "
                "before using the application."
            ),
            "depends_on": {"key": "enable_terms_of_use", "equals": True},
        },
        {
            "key": "terms_of_use_decline_redirect_url",
            "type": "text",
            "label": "Cancel Redirect URL",
            "help": (
                "A local path such as / or an HTTPS URL. Signed-in users are locally "
                "logged out before this redirect."
            ),
            "default": TERMS_OF_USE_DEFAULT_REDIRECT,
            "max_length": 2000,
            "depends_on": {"key": "enable_terms_of_use", "equals": True},
        },
        {
            "key": "terms_of_use_accept_button_text",
            "type": "text",
            "label": "Accept Button Text",
            "default": "Accept and continue",
            "max_length": TERMS_OF_USE_MAX_BUTTON_TEXT_LENGTH,
            "depends_on": {"key": "enable_terms_of_use", "equals": True},
        },
        {
            "key": "terms_of_use_decline_button_text",
            "type": "text",
            "label": "Cancel Button Text",
            "default": "Cancel",
            "max_length": TERMS_OF_USE_MAX_BUTTON_TEXT_LENGTH,
            "depends_on": {"key": "enable_terms_of_use", "equals": True},
        },
    ],
    "user-agreement-section": [
        {
            "key": "enable_user_agreement",
            "type": "switch",
            "label": "Enable User Agreement",
            "help": (
                "Users must accept the agreement before uploading files in the "
                "selected workspace types."
            ),
            "default": False,
        },
        {
            "key": "user_agreement_apply_to",
            "type": "checkbox_set",
            "label": "Apply to",
            "help": "Select where the user agreement should be shown.",
            "default": [],
            "min_selected": 1,
            "options": [
                {"value": "personal", "label": "Personal Workspaces"},
                {"value": "group", "label": "Group Workspaces"},
                {"value": "public", "label": "Public Workspaces"},
                {"value": "chat", "label": "Chat"},
            ],
            "depends_on": {"key": "enable_user_agreement", "equals": True},
        },
        {
            "key": "user_agreement_text",
            "type": "textarea",
            "label": "Agreement Text",
            "help": "Markdown is supported.",
            "default": "",
            "rows": 6,
            "markdown": True,
            "max_length": 10000,
            "word_limit": USER_AGREEMENT_WORD_LIMIT,
            "placeholder": (
                "Enter the agreement text that users must accept before uploading "
                "files..."
            ),
            "depends_on": {"key": "enable_user_agreement", "equals": True},
        },
        {
            "key": "enable_user_agreement_daily",
            "type": "switch",
            "label": "Allow users to accept once per day",
            "help": (
                "Users accept once per day instead of every time they upload files."
            ),
            "default": False,
            "depends_on": {"key": "enable_user_agreement", "equals": True},
        },
        {
            "type": "component",
            "component": "user-agreement-preview",
            "label": "Test Preview",
            "depends_on": {"key": "enable_user_agreement", "equals": True},
        },
    ],
    "custom-pages-section": [
        {
            "key": "enable_custom_pages",
            "type": "switch",
            "label": "Enable Custom Pages",
            "help": (
                "Serves trusted pages deployed under custom_pages at /custom. When "
                "off, /custom returns Not Found before any custom metadata, file or "
                "Python extension is loaded."
            ),
            "default": False,
            # Enabling only takes full effect after an App Service restart, so the
            # V2 surface must collect the same acknowledgement the V1 form does.
            "requires_acknowledgement": {
                "key": "custom_pages_restart_acknowledged",
                "when": "enabled",
                "title": "Custom Pages requires a restart",
                "message": (
                    "Custom Pages is not fully enabled until the App Service is "
                    "restarted. Python-backed pages register their routes at startup."
                ),
            },
        },
        {
            "key": "custom_pages_menu_name",
            "type": "text",
            "label": "Menu Name",
            "help": "Shown when custom pages are grouped into a menu.",
            "default": "Custom Pages",
            "max_length": 60,
            "fallback_when_empty": True,
            "depends_on": {"key": "enable_custom_pages", "equals": True},
        },
        {
            "key": "custom_pages_force_menu",
            "type": "switch",
            "label": "Force Menu Display",
            "help": (
                "When off, 1-2 pages appear as top-level nav items and 3 or more "
                "become a menu."
            ),
            "default": False,
            "depends_on": {"key": "enable_custom_pages", "equals": True},
        },
        {
            "type": "component",
            "component": "custom-pages-table",
            "label": "Static Page Metadata",
            "help": (
                "Metadata contracts for pages built from files in custom_pages/html, "
                "css, js, assets and json."
            ),
            "depends_on": {"key": "enable_custom_pages", "equals": True},
        },
    ],
    "external-links-section": [
        {
            "key": "enable_external_links",
            "type": "switch",
            "label": "Enable External Links in Navigation",
            "help": "Adds administrator-approved links to the navigation bar.",
            "default": False,
        },
        {
            "key": "external_links_menu_name",
            "type": "text",
            "label": "Menu Name",
            "help": "Appears in the navigation bar as the menu title.",
            "default": "External Links",
            "max_length": 60,
            "fallback_when_empty": True,
            "depends_on": {"key": "enable_external_links", "equals": True},
        },
        {
            "key": "external_links_force_menu",
            "type": "switch",
            "label": "Force Menu Display",
            "help": (
                "When off, 1-2 links appear as top-level nav items and 3 or more "
                "become a dropdown."
            ),
            "default": False,
            "depends_on": {"key": "enable_external_links", "equals": True},
        },
        {
            "key": "external_links",
            "type": "link_list",
            "label": "External Links",
            "help": "Links open in a new tab. Only http and https addresses are allowed.",
            "default": [],
            "item_fields": [
                {"key": "label", "type": "text", "label": "Label", "max_length": 80},
                {"key": "url", "type": "text", "label": "URL", "max_length": 2000},
            ],
            "depends_on": {"key": "enable_external_links", "equals": True},
        },
    ],
    # ------------------------------------------------------------------
    # Chat group. Sections and order follow admin_settings_nav.py; wording
    # follows the V1 panes (chat-experience, feedback-alerts, citation) so both
    # interfaces describe the same setting the same way.
    # ------------------------------------------------------------------
    "processing-thoughts-section": [
        {
            "key": "enable_thoughts",
            "type": "switch",
            "label": "Enable Processing Thoughts",
            "help": (
                "Shows the steps taken while answering -- document searches, web "
                "searches, agent calls -- as they happen, and stores them so a "
                "message can be reviewed afterwards."
            ),
            "default": True,
        },
    ],
    "chat-file-uploads-section": [
        {
            "key": "enable_chat_file_uploads",
            "type": "switch",
            "label": "Enable Chat File Uploads",
            "help": (
                "Lets users attach files directly to a conversation instead of "
                "adding them to a workspace first."
            ),
            "default": True,
        },
        {
            "key": "require_member_of_chat_file_upload_user",
            "type": "switch",
            "label": "Require ChatFileUploadUser App Role",
            "help": (
                "Restricts new uploads to users holding the ChatFileUploadUser "
                "Enterprise App role. Files already attached stay visible."
            ),
            "default": False,
            "depends_on": {"key": "enable_chat_file_uploads", "equals": True},
        },
    ],
    "conversation-contents-drawer-section": [
        {
            "key": "enable_conversation_contents_drawer",
            "type": "switch",
            "label": "Enable Conversation Contents Drawer",
            "help": (
                "Adds a drawer listing a conversation's prompts so users can jump "
                "back to an earlier turn. Users can turn it off for themselves in "
                "their profile."
            ),
            "default": True,
        },
    ],
    "workspace-scope-lock-section": [
        {
            "key": "enforce_workspace_scope_lock",
            "type": "switch",
            "label": "Enforce Workspace Scope Lock",
            "help": (
                "Keeps a conversation restricted to the workspaces that produced "
                "its first search results. Turn this off to let users unlock the "
                "scope and search elsewhere in the same conversation."
            ),
            "default": True,
        },
    ],
    "conversation-history-section": [
        {
            "key": "conversation_history_limit",
            "type": "number",
            "label": "Conversation History Limit",
            "help": (
                "How many previous messages are carried into each new request. "
                "Raising it preserves more context and costs more tokens per turn."
            ),
            "default": 10,
            "min": 1,
        },
        {
            "key": "enable_summarize_content_history_beyond_conversation_history_limit",
            "type": "switch",
            "label": "Summarize Messages Beyond the History Limit",
            "help": (
                "Replaces messages that fall outside the limit with a running "
                "summary instead of dropping them, so older context survives a "
                "long conversation."
            ),
            "default": False,
        },
        {
            "key": "enable_summarize_content_history_for_search",
            "type": "switch",
            "label": "Summarize Conversation History for Search",
            "help": (
                "Summarizes recent turns into the query used for hybrid document "
                "search, so a follow-up question that relies on earlier context "
                "still retrieves the right sources."
            ),
            "default": False,
        },
        {
            "key": "number_of_historical_messages_to_summarize",
            "type": "number",
            "label": "Historical Messages to Summarize",
            "help": (
                "How many recent messages are summarized into the search query. "
                "Twice this many are read to build the summary."
            ),
            "default": 10,
            "min": 1,
            "max": 100,
            "depends_on": {
                "key": "enable_summarize_content_history_for_search",
                "equals": True,
            },
        },
    ],
    "default-system-prompt-section": [
        {
            "key": "default_system_prompt",
            "type": "textarea",
            "label": "Default System Prompt",
            "help": (
                "Applied to conversations that do not set their own. Agents and "
                "conversations with a custom prompt are unaffected."
            ),
            "default": "",
            "rows": 5,
        },
    ],
    "fact-memory-section": [
        {
            "key": "enable_fact_memory_plugin",
            "type": "switch",
            "label": "Enable Fact Memory",
            "help": (
                "Lets the assistant carry durable context between conversations. "
                "Instruction memories apply to every prompt; fact memories are "
                "recalled only when relevant. This is a chat capability and does "
                "not require agents or actions. Users manage their own entries "
                "under Profile > Fact Memory. Existing entries are preserved while "
                "this is off, but stay inactive."
            ),
            "default": True,
        },
    ],
    "user-feedback-section": [
        {
            "key": "enable_user_feedback",
            "type": "switch",
            "label": "Enable User Feedback (Thumbs Up/Down)",
            "help": (
                "Adds thumbs up and down controls to AI responses and routes the "
                "ratings to the feedback review workflow."
            ),
            "default": True,
        },
    ],
    "desktop-notifications-section": [
        {
            "key": "enable_desktop_notifications",
            "type": "switch",
            "label": "Enable Desktop Conversation Notifications",
            "help": (
                "Lets users receive an operating system notification when a "
                "response finishes in a hidden or unfocused tab. Requires browser "
                "permission, stops when the tab is closed, and users can turn it "
                "off in their profile."
            ),
            "default": False,
        },
    ],
    # Standard citations has no settings -- V1's card is explanatory only -- so it
    # is deliberately absent. A section with nothing to render is skipped.
    "enhanced-citations-section": [
        {
            "key": "enable_enhanced_citations",
            "type": "switch",
            "label": "Enable Enhanced Citations",
            "help": (
                "Stores original files in an Azure Storage account so citations can "
                "link to and preview the source document rather than only quoting "
                "extracted text."
            ),
            "default": False,
        },
        {
            "type": "component",
            "label": "Storage Connection",
            "component": "enhanced-citations-storage-test",
            "help": (
                "Startup does not check storage, so an outage cannot block boot. "
                "Test here to confirm the account is reachable and the expected "
                "containers exist."
            ),
            "depends_on": {"key": "enable_enhanced_citations", "equals": True},
        },
        {
            "key": "office_docs_authentication_type",
            "type": "select",
            "label": "Storage Account Authentication Type",
            "help": "How SimpleChat authenticates to the storage account.",
            "default": "key",
            "options": [
                {"value": "key", "label": "Connection String"},
                {"value": "managed_identity", "label": "Managed Identity"},
            ],
            "depends_on": {"key": "enable_enhanced_citations", "equals": True},
        },
        {
            "key": "office_docs_storage_account_url",
            "type": "secret",
            "label": "Storage Account Connection String",
            "help": "Used when authenticating with a connection string.",
            "default": "",
            "depends_on": [
                {"key": "enable_enhanced_citations", "equals": True},
                {"key": "office_docs_authentication_type", "equals": "key"},
            ],
        },
        {
            "key": "office_docs_storage_account_blob_endpoint",
            "type": "secret",
            "label": "Storage Account Blob Service Endpoint",
            "help": "Used when authenticating with a managed identity.",
            "default": "",
            "depends_on": [
                {"key": "enable_enhanced_citations", "equals": True},
                {
                    "key": "office_docs_authentication_type",
                    "equals": "managed_identity",
                },
            ],
        },
        {
            "key": "tabular_preview_max_blob_size_mb",
            "type": "number",
            "label": "Maximum File Size for Tabular Preview (MB)",
            "help": (
                "CSV and XLSX files above this size are not previewed. Raise it for "
                "larger files when the host has memory to spare; lower it to protect "
                "smaller instances."
            ),
            "default": 200,
            "min": 1,
            "max": 1024,
            "depends_on": {"key": "enable_enhanced_citations", "equals": True},
        },
        {
            "key": "enable_tabular_durable_run_confirmation",
            "type": "switch",
            "label": "Confirm very large row-level runs before starting",
            "help": (
                "When a prompt names an explicitly large row count, the user is "
                "asked to continue or narrow the scope before the run starts."
            ),
            "default": True,
            "depends_on": {"key": "enable_enhanced_citations", "equals": True},
        },
        {
            "key": "tabular_durable_run_confirmation_threshold_rows",
            "type": "number",
            "label": "Confirmation Row Threshold",
            "help": "Row count at or above which the confirmation is shown.",
            "default": 500,
            "min": 1,
            "max": 1000000,
            "depends_on": [
                {"key": "enable_enhanced_citations", "equals": True},
                {"key": "enable_tabular_durable_run_confirmation", "equals": True},
            ],
        },
        {
            "key": "tabular_durable_run_confirmation_threshold_batches",
            "type": "number",
            "label": "Confirmation Batch Threshold",
            "help": "Batch count at or above which the confirmation is shown.",
            "default": 75,
            "min": 1,
            "max": 100000,
            "depends_on": [
                {"key": "enable_enhanced_citations", "equals": True},
                {"key": "enable_tabular_durable_run_confirmation", "equals": True},
            ],
        },
        {
            "key": "tabular_generated_output_chunk_model_mode",
            "type": "select",
            "label": "Chunk Processing Model",
            "help": (
                "Whether per-chunk work reuses the model the user selected or a "
                "deployment set aside for it."
            ),
            "default": "current",
            "options": [
                {"value": "current", "label": "Use the user's selected model"},
                {
                    "value": "configured",
                    "label": "Use a configured deployment for chunk work",
                },
            ],
            "depends_on": {"key": "enable_enhanced_citations", "equals": True},
        },
        {
            "key": "tabular_generated_output_chunk_model_deployment",
            "type": "text",
            "label": "Configured Chunk Model Deployment",
            "help": "Deployment name used when chunk work runs on its own model.",
            "default": "",
            "max_length": 120,
            "depends_on": [
                {"key": "enable_enhanced_citations", "equals": True},
                {
                    "key": "tabular_generated_output_chunk_model_mode",
                    "equals": "configured",
                },
            ],
        },
    ],
    # The sections below are not part of the Appearance group. They are described
    # here because the V2 surface's `enable_*` fallback was filing their toggles
    # under Appearance: it matches a key to a section by shared leading word
    # stems and takes the first section that scores at all, so
    # `enable_external_healthcheck` matched "external" in External Links long
    # before it could reach Health Check, whose id splits into "health" and
    # "check" and so never matches the single token "healthcheck". Declaring a
    # key is what takes it out of that scan, so these five are declared rather
    # than guessed at. Wording is taken from the V1 panes so both interfaces say
    # the same thing.
    "health-check-section": [
        {
            "key": "enable_external_healthcheck",
            "type": "switch",
            "label": "Enable /external/healthcheck",
            "help": (
                "Authenticated endpoint for external monitoring systems. Best for "
                "internal monitors or diagnostics tooling that already signs in to "
                "the application."
            ),
            "default": False,
        },
        {
            "key": "enable_no_auth_external_healthcheck",
            "type": "switch",
            "label": "Enable /external/healthcheckz",
            "help": (
                "Unauthenticated endpoint for platform probes that cannot sign in. "
                "This route is intentionally unauthenticated, so only enable it for "
                "trusted health probes or controlled network paths."
            ),
            "default": False,
        },
    ],
    "user-facing-latest-features-section": [
        {
            "key": "enable_support_latest_feature_documentation_links",
            "type": "switch",
            "label": "Show Simple Chat Documentation Guide Links",
            "help": (
                "User-facing Latest Features cards show public documentation guide "
                "buttons in addition to the direct in-app shortcuts."
            ),
            "default": False,
            # V1 hides this control entirely while the Latest Features destination
            # is off, because the cards it affects are not reachable then. The
            # Support Menu condition is repeated because visibility is evaluated
            # per field rather than recursively: `enable_support_latest_features`
            # defaults to True, so gating on it alone would leave this on screen
            # while the whole Support menu is off.
            "depends_on": [
                {"key": "enable_support_menu", "equals": True},
                {"key": "enable_support_latest_features", "equals": True},
            ],
        },
    ],
    # Declared so the dependency above resolves to a control an administrator can
    # actually find and flip, and so the Support Menu gate chain reads the same in
    # both interfaces. The remaining fields in this section are still discovered
    # by the fallback scan.
    "support-menu-section": [
        {
            "key": "enable_support_menu",
            "type": "switch",
            "label": "Enable Support Menu for End Users",
            "help": (
                "Signed-in users with the User role get a Support menu in navigation, "
                "leading to destinations such as Send Feedback and Latest Features."
            ),
            "default": False,
        },
        {
            "key": "enable_support_latest_features",
            "type": "switch",
            "label": "Enable Latest Features Destination",
            "help": "Publishes a user-facing Latest Features page from the Support menu.",
            "default": True,
            "depends_on": {"key": "enable_support_menu", "equals": True},
        },
    ],
    "personal-workspaces-section": [
        {
            "key": "enable_user_workspace",
            "type": "switch",
            "label": "Enable Personal Workspaces",
            "help": (
                "Users can create and manage their own private workspace for document "
                "storage, knowledge bases and personal AI interactions."
            ),
            "default": True,
        },
    ],
    "actions-config": [
        {
            "key": "enable_text_plugin",
            "type": "switch",
            "label": "Enable Text Action",
            "help": (
                "Agents can perform text processing operations such as formatting, "
                "validation and manipulation of strings and text content."
            ),
            "default": True,
        },
        {
            "key": "enable_default_embedding_model_plugin",
            "type": "switch",
            "label": "Enable Default Embedding Model Action",
            "help": (
                "Registers the configured embedding deployment as an action agents "
                "can call to embed text directly."
            ),
            "default": False,
        },
    ],
    # The four sections below belong to Knowledge, not Chat. They are declared for
    # the same reason as Health Check above: the fallback scan matched their keys
    # to a Chat section by shared word stems -- "audio" and "video" and "file"
    # reaching chat-file-uploads-section, "enhanced" reaching
    # enhanced-citations-section -- and put audio, video and extraction toggles on
    # the Chat page. Declaring a key is what takes it out of that scan.
    "ai-voice-chat-section": [
        {
            "key": "enable_audio_file_support",
            "type": "switch",
            "label": "Enable Audio File Support",
            "help": (
                "Allows audio files to be uploaded and transcribed so their spoken "
                "content becomes searchable and citable."
            ),
            "default": False,
        },
        {
            "key": "enable_chat_completion_audio_cues",
            "type": "switch",
            "label": "Enable Chat Completion Audio Cues",
            "help": (
                "Plays a short sound when a response finishes. Users choose their "
                "own sound and volume, or mute it, in their profile."
            ),
            "default": False,
        },
    ],
    "video-intelligence-section": [
        {
            "key": "enable_video_file_support",
            "type": "switch",
            "label": "Enable Video File Support",
            "help": (
                "Allows video files to be uploaded and indexed so their spoken and "
                "on-screen content becomes searchable and citable."
            ),
            "default": False,
        },
    ],
    "document-intelligence-section": [
        {
            "key": "enable_enhanced_extraction",
            "type": "switch",
            "label": "Enable Enhanced Extraction",
            "help": (
                "Uses richer Document Intelligence extraction for layout, tables and "
                "structure, at a higher processing cost per document."
            ),
            "default": False,
        },
    ],
}


# Keys the V2 fallback scan must not draw a switch for.
#
# That scan renders every `enable_*` boolean it finds in the settings document.
# Some of those booleans are not settings an administrator can change, so a
# switch would appear to save and then silently revert, or save a value nothing
# ever reads. Declaring them is not the answer either -- a declared field claims
# there is something to edit. They are named here with the reason instead, and
# the settings GET sends this list so the scan can skip them.
SUPPRESSED_CAPABILITY_KEYS = {
    "enable_tabular_processing_plugin": (
        "Derived, not stored: is_tabular_processing_enabled() returns "
        "enable_enhanced_citations, and get_settings() overwrites the stored value "
        "on every read. A switch here would revert on the next page load."
    ),
    "enable_enhanced_citations_mount": (
        "No control in either interface. The saved value is forced off unless "
        "Enhanced Citations is enabled, and the mount path itself is not "
        "administrator-editable."
    ),
    "enable_mixed_source_chat_search": (
        "Staged rollout flag for mixed-source chat and search, with no control in "
        "the server-rendered admin form."
    ),
    "enable_mixed_source_conversation_continuity": (
        "Staged rollout flag gated behind enable_mixed_source_chat_search, with no "
        "control in the server-rendered admin form."
    ),
}


# Maps each schema key to the field name(s) the server-rendered form submits.
# Most match exactly and are omitted. The entries below are the places where the
# two shapes genuinely differ, and the parity test uses them to resolve a V1
# form field to its V2 equivalent.
LEGACY_FIELD_NAMES = {
    # V1 submits four independent checkboxes and assembles the array server-side.
    "user_agreement_apply_to": [
        "user_agreement_apply_personal",
        "user_agreement_apply_group",
        "user_agreement_apply_public",
        "user_agreement_apply_chat",
    ],
    # V1 round-trips the list through a hidden JSON field maintained by script.
    "external_links": ["external_links_json"],
    # V1 posts the images as part of the settings form; V2 uploads them
    # separately, so the stored keys are what the schema names.
    "custom_logo_base64": ["logo_file"],
    "custom_logo_dark_base64": ["logo_dark_file"],
    "custom_favicon_base64": ["favicon_file"],
    # Collected as an acknowledgement on the toggle rather than a stored value.
    "enable_custom_pages": ["enable_custom_pages", "custom_pages_restart_acknowledged"],
}

# Field names present in the V1 Appearance panes that intentionally have no V2
# equivalent, with the reason. The parity test reads this, so an unexplained
# omission fails rather than passing silently.
LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT = {}


def get_admin_settings_fields():
    """Return the section-id keyed field schema."""
    return ADMIN_SETTINGS_FIELDS


def iter_fields():
    """Yield ``(section_id, field)`` for every declared field."""
    for section_id, fields in ADMIN_SETTINGS_FIELDS.items():
        for field in fields:
            yield section_id, field


def get_field_definition(key):
    """Return the field definition for a settings key, or None."""
    for _section_id, field in iter_fields():
        if field.get("key") == key:
            return field
    return None


def get_declared_setting_keys():
    """Return every settings key the schema describes.

    The V2 surface uses this to suppress its ``enable_*`` fallback scan for keys
    that already have a proper field, so a toggle is never rendered twice.
    """
    return {field["key"] for _section_id, field in iter_fields() if field.get("key")}


def get_suppressed_capability_keys():
    """Return the keys the V2 fallback scan must not render a switch for."""
    return sorted(SUPPRESSED_CAPABILITY_KEYS)


def iter_field_dependencies(field):
    """Return a field's visibility conditions as a tuple.

    ``depends_on`` is normally one condition. It may also be a list, and then every
    condition must hold. That is needed wherever a control is gated on a sibling
    whose own default would otherwise reveal it: the Enhanced Citations storage
    credentials are chosen by authentication type, but must stay hidden entirely
    while Enhanced Citations itself is off.
    """
    depends_on = field.get("depends_on")
    if not depends_on:
        return ()
    if isinstance(depends_on, dict):
        return (depends_on,)
    return tuple(depends_on)


def get_legacy_field_names():
    """Return the V1 form field names claimed by the schema."""
    claimed = set()
    for _section_id, field in iter_fields():
        key = field.get("key")
        if not key:
            continue
        claimed.update(LEGACY_FIELD_NAMES.get(key, [key]))
    return claimed


def _coerce_bool(value):
    """Coerce a JSON or form-shaped truthy value into a bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "on", "yes", "1")
    return bool(value)


def _normalize_text(value, field):
    """Strip and truncate a single-line value, applying an empty-value fallback."""
    text = str(value if value is not None else "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text and field.get("fallback_when_empty"):
        text = str(field.get("default") or "")
    max_length = field.get("max_length")
    if max_length:
        text = text[:max_length]
    return text


def _validate_external_link_url(url):
    """Return an error message when a navigation link URL is not safe to render."""
    candidate = str(url or "").strip()
    if not candidate:
        return "URL is required."
    if candidate.startswith("/") and not candidate.startswith("//"):
        return None

    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in EXTERNAL_LINK_ALLOWED_SCHEMES:
        return (
            "URL must be a local path or use "
            f"{' or '.join(EXTERNAL_LINK_ALLOWED_SCHEMES)}."
        )
    if not parsed.netloc:
        return "URL is missing a host."
    return None


def is_safe_external_link_url(url):
    """Return True when a navigation link URL is safe to render as an ``href``.

    The write path already refuses anything else, but only the V2 settings PATCH goes
    through it: the server-rendered admin form stores whatever string it is given, and a
    settings document predates both. Any surface that turns a stored link into an anchor
    should therefore check here rather than trust the document.
    """
    return _validate_external_link_url(url) is None


def _normalize_link_list(value):
    """Return ``(links, error)`` for an administrator-managed navigation list."""
    if not isinstance(value, list):
        return None, "Expected a list of links."

    links = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            return None, f"Link {index} is not an object."

        label = str(item.get("label") or "").strip()
        url = str(item.get("url") or "").strip()
        if not label:
            return None, f"Link {index} is missing a label."

        url_error = _validate_external_link_url(url)
        if url_error:
            return None, f"Link {index}: {url_error}"

        links.append({"label": label[:80], "url": url[:2000]})

    return links, None


def _normalize_checkbox_set(value, field):
    """Return ``(selection, error)`` for a multi-select checkbox group."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return None, "Expected a list of values."

    allowed = [option["value"] for option in field.get("options", [])]
    # Preserve the declared option order so the stored array is stable no matter
    # which order the browser sent the boxes in.
    selection = [option for option in allowed if option in value]

    unknown = sorted({str(item) for item in value} - set(allowed))
    if unknown:
        return None, f"Unsupported value(s): {', '.join(unknown)}."

    return selection, None


def _normalize_number(value, field):
    """Return ``(number, error)`` clamped to the field's declared bounds."""
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None, "Expected a number."

    minimum = field.get("min")
    maximum = field.get("max")
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number, None


# Keys whose normalization already exists elsewhere. Reusing those functions is
# what stops the two admin surfaces from disagreeing about, for example, which
# frequency aliases are accepted or how a terms message is trimmed.
_DELEGATED_NORMALIZERS = {
    "ai_notice_message": lambda value, field: normalize_ai_notice_message(value),
    "ai_notice_frequency": lambda value, field: normalize_ai_notice_frequency(value),
    "terms_of_use_frequency": lambda value, field: normalize_terms_of_use_frequency(value),
    "terms_of_use_title": lambda value, field: normalize_terms_of_use_text(
        value, fallback="Terms of Use", max_length=TERMS_OF_USE_MAX_TITLE_LENGTH
    ),
    "terms_of_use_message": lambda value, field: normalize_terms_of_use_text(
        value, max_length=TERMS_OF_USE_MAX_MESSAGE_LENGTH
    ),
    "terms_of_use_accept_button_text": lambda value, field: normalize_terms_of_use_text(
        value, fallback="Accept and continue", max_length=TERMS_OF_USE_MAX_BUTTON_TEXT_LENGTH
    ),
    "terms_of_use_decline_button_text": lambda value, field: normalize_terms_of_use_text(
        value, fallback="Cancel", max_length=TERMS_OF_USE_MAX_BUTTON_TEXT_LENGTH
    ),
}


def _normalize_field_value(key, value, field, current_settings=None):
    """Return ``(normalized, error, warning)`` for one declared field."""
    field_type = field.get("type")

    if field_type in NON_PATCHABLE_TYPES:
        return None, f"{key} cannot be changed through this endpoint.", None

    if key in _DELEGATED_NORMALIZERS:
        return _DELEGATED_NORMALIZERS[key](value, field), None, None

    if field_type == "switch":
        return _coerce_bool(value), None, None

    if field_type == "secret":
        # A value still equal to the mask means the administrator did not touch
        # the field, so the stored secret is kept. Storing the mask would
        # overwrite a working credential with the literal "***REDACTED***".
        resolved = resolve_admin_settings_secret_value(
            key, value, current_settings or {}
        )
        max_length = field.get("max_length")
        return (resolved[:max_length] if max_length else resolved), None, None

    if field_type == "select":
        allowed = [option["value"] for option in field.get("options", [])]
        candidate = str(value or "").strip()
        if candidate not in allowed:
            return None, f"Expected one of: {', '.join(allowed)}.", None
        return candidate, None, None

    if field_type == "color":
        candidate = str(value or "").strip()
        if not HEX_COLOR_PATTERN.match(candidate):
            return None, "Expected a hex colour such as #ffc107.", None
        return candidate.lower(), None, None

    if field_type in ("range", "number"):
        number, error = _normalize_number(value, field)
        return number, error, None

    if field_type == "checkbox_set":
        selection, error = _normalize_checkbox_set(value, field)
        return selection, error, None

    if field_type == "link_list":
        links, error = _normalize_link_list(value)
        return links, error, None

    if field_type == "textarea":
        text = str(value if value is not None else "")
        text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        max_length = field.get("max_length")
        if max_length:
            text = text[:max_length]

        warning = None
        word_limit = field.get("word_limit")
        if word_limit and len(text.split()) > word_limit:
            # Advisory only, matching the server-rendered form, which warns and
            # saves rather than blocking the whole submission.
            warning = (
                f"{len(text.split())} words exceeds the recommended "
                f"{word_limit} word limit."
            )
        return text, None, warning

    if field_type == "text":
        return _normalize_text(value, field), None, None

    return value, None, None


def _validate_redirect_url(value):
    """Return ``(normalized, error)`` for the Terms of Use cancel redirect.

    ``normalize_terms_of_use_redirect_url`` silently substitutes ``/`` for an
    unsafe target. That is the right behaviour when reading stored settings, but
    on an explicit save an administrator should be told their URL was refused
    rather than discovering later that it reverted.
    """
    candidate = str(value or "").strip()
    normalized = normalize_terms_of_use_redirect_url(candidate)
    if candidate and normalized != candidate:
        return None, (
            "Use a local path such as / or an HTTPS URL without credentials."
        )
    return normalized, None


def _check_acknowledgements(updates, current_settings, errors):
    """Enforce the acknowledgements a field requires before it may be enabled."""
    for _section_id, field in iter_fields():
        acknowledgement = field.get("requires_acknowledgement")
        key = field.get("key")
        if not acknowledgement or not key or key not in updates:
            continue

        turning_on = _coerce_bool(updates[key])
        already_on = _coerce_bool(current_settings.get(key, False))
        if not turning_on or already_on:
            continue

        if not _coerce_bool(updates.get(acknowledgement["key"])):
            errors[key] = acknowledgement["message"]


def normalize_admin_settings_updates(updates, current_settings=None):
    """Validate and coerce a partial admin settings update.

    Returns ``(normalized, errors, warnings)``. ``normalized`` is safe to hand to
    ``update_settings``; it is only meaningful when ``errors`` is empty.

    Keys with no declared field pass through unchanged. That is deliberate: the
    V2 surface still renders undescribed groups from its ``enable_*`` scan, and
    those toggles must keep saving while the remaining groups are described.
    """
    current = current_settings or {}
    normalized = {}
    errors = {}
    warnings = {}

    # Acknowledgement flags gate a change rather than being stored themselves.
    acknowledgement_keys = {
        field["requires_acknowledgement"]["key"]
        for _section_id, field in iter_fields()
        if field.get("requires_acknowledgement")
    }

    for key, value in updates.items():
        if key in acknowledgement_keys:
            continue

        if key in NON_PATCHABLE_KEYS:
            errors[key] = NON_PATCHABLE_KEYS[key]
            continue

        field = get_field_definition(key)
        if field is None:
            normalized[key] = value
            continue

        if key == "terms_of_use_decline_redirect_url":
            redirect_value, redirect_error = _validate_redirect_url(value)
            if redirect_error:
                errors[key] = redirect_error
            else:
                normalized[key] = redirect_value
            continue

        field_value, error, warning = _normalize_field_value(key, value, field, current)
        if error:
            errors[key] = error
            continue
        if warning:
            warnings[key] = warning
        normalized[key] = field_value

    _check_acknowledgements(updates, current, errors)

    # "At least one" style constraints can only be judged once the whole payload
    # is known, because the capability toggle and its selection may arrive apart.
    _check_minimum_selections(normalized, current, errors)

    return normalized, errors, warnings


def _dependency_is_satisfied(depends_on, value):
    """Whether a ``depends_on`` condition holds for a field's current value.

    ``equals`` is usually a boolean, gating a field on a capability switch. It
    may also be a string, which gates a field on a select -- the Enhanced
    Citations storage credentials each apply to one authentication type only.
    """
    expected = depends_on.get("equals", True)
    if isinstance(expected, str):
        return str(value or "").strip() == expected
    return _coerce_bool(value) == expected


def _check_minimum_selections(normalized, current_settings, errors):
    """Enforce ``min_selected`` once the merged state of a save is known."""
    for _section_id, field in iter_fields():
        key = field.get("key")
        minimum = field.get("min_selected")
        if not key or not minimum:
            continue

        depends_on = field.get("depends_on")
        if depends_on:
            gated_off = False
            for condition in iter_field_dependencies(field):
                gate_key = condition["key"]
                gate_value = (
                    normalized[gate_key] if gate_key in normalized
                    else current_settings.get(gate_key, False)
                )
                if not _dependency_is_satisfied(condition, gate_value):
                    gated_off = True
                    break
            if gated_off:
                continue

        selection = (
            normalized[key] if key in normalized else current_settings.get(key) or []
        )
        if len(selection) < minimum:
            errors[key] = f"Select at least {minimum} option."
