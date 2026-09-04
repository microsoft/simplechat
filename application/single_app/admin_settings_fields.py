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

Beyond a field's type, three optional descriptors shape how a section reads:

``group``
    Names the cluster a field belongs to, with a variant from ``GROUP_VARIANTS``.
    The renderer opens the ``connection`` group first, because an administrator
    arriving at an unconfigured capability needs the endpoint before the tuning
    knobs. Without this, a section like Document Intelligence is a flat run of
    forty controls in which the credential that makes the rest work is simply
    the last one.

``depends_on``
    Shows a field only while a condition holds. See ``evaluate_dependency`` for
    the supported shapes; ``any_of`` exists because the Speech resource block is
    revealed by any of three independent capability toggles.

``requires``
    Declares a prerequisite owned by a different section, mirroring the
    ``data-requires`` attributes ``admin_settings_dependencies.js`` reads. File
    Sync needs Redis Cache, which lives under Scale, and saying so where the
    dependency is felt beats discovering it from a flash message after saving.

``paths``
    Where the value actually lives, when that is not a top-level settings key.
    Most settings are flat, but a few are assembled into a nested object by the
    server-rendered form's save handler -- the Web Search Foundry connection is
    built into ``web_search_agent`` -- so a field whose key matches the V1 form
    input would otherwise save to a top-level key nothing reads. See
    ``_apply_nested_paths``.

Only the Appearance group is described in full so far. Sections with no entry
here fall back to the V2 surface's ``enable_*`` scan, so undescribed groups keep
working exactly as they did. A handful of individual fields outside Appearance
are also declared: that scan places a key by guessing from shared word stems,
and declaring a field is the only way to stop it guessing wrong.
"""

import copy
import json
import re
from urllib.parse import urlparse

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
    "select",
    "switch",
    "checkbox_set",
    "color",
    "range",
    "number",
    "image",
    "link_list",
    "component",
    "secret",
    "string_list",
    "id_list",
    "status",
)

# Types that own their persistence outside the settings PATCH: image uploads go
# through the multipart branding endpoint, components talk to their own API, and
# a status readout is computed by the server rather than stored at all.
NON_PATCHABLE_TYPES = ("image", "component", "status")

# Group variants. A section orders its fields into groups, and the variant is
# what the renderer uses to decide which group opens first: an admin arriving at
# an unconfigured capability needs the connection, not the tuning knobs.
GROUP_VARIANTS = ("connection", "behavior", "limits", "access", "advanced")

# Roles a field can play in its section's header rather than its body.
#
# "capability" marks the switch that turns the whole section on. The renderer
# lifts it into the section header next to the status, so the one control that
# decides whether anything else matters is never buried among forty others.
FIELD_ROLES = ("capability",)

# Modes for a cross-section prerequisite, matching the server-rendered
# `data-requires-mode` contract in admin_settings_dependencies.js.
#   block  disables the dependent controls until the prerequisite is on
#   warn   leaves them usable, for prerequisites the backend accepts as intent
REQUIRES_MODES = ("block", "warn")

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

# Placeholder a stored secret is replaced with before it is sent to a browser.
#
# This mirrors ``functions_settings.ADMIN_SETTINGS_SECRET_REDACTED_VALUE`` rather
# than importing it. This module is a pure declaration that several functional
# tests import directly, and ``functions_settings`` reaches ``config``, which
# builds a Cosmos client at import time. The schema test pins the two values
# together, so the duplication cannot drift.
SECRET_REDACTED_VALUE = "***REDACTED***"

# Longest value accepted for a secret. Generous enough for a certificate-bearing
# connection string, short enough that a paste accident is refused rather than
# stored.
SECRET_MAX_LENGTH = 4096

# Returned by the secret normalizer when the submitted value is the redaction
# placeholder, meaning the administrator never touched the field. The update is
# then dropped rather than written, so a save that touches one toggle cannot
# overwrite every key on the page with "***REDACTED***".
SECRET_UNCHANGED = object()

# Mirrors ``functions_settings.WEB_SEARCH_USER_NOTICE_DEFAULT_TEXT``, for the same
# reason ``SECRET_REDACTED_VALUE`` is mirrored: this module stays importable
# without ``config``. The schema test compares declared defaults against the
# application, so the two cannot drift.
WEB_SEARCH_USER_NOTICE_DEFAULT_TEXT = (
    "Your current message will be sent to Microsoft Bing for web search. Conversation "
    "history is not sent for web search, but any sensitive content you paste into this "
    "message may be sent."
)


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
            # is off, because the cards it affects are not reachable then.
            "depends_on": {"key": "enable_support_latest_features", "equals": True},
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
    # The first Knowledge section described, and the reference for the rest.
    "azure-ai-search-section": [
        {
            "key": "enable_ai_search_apim",
            "type": "switch",
            "label": "Route through API Management",
            "help": (
                "Send Azure AI Search requests through API Management for centralized "
                "monitoring and control instead of reaching the service directly."
            ),
            "default": False,
            "group": {
                "id": "connection",
                "label": "Connection",
                "variant": "connection",
                "help": (
                    "Where the application sends search requests, and how it "
                    "authenticates to them."
                ),
            },
        },
        {
            "key": "azure_ai_search_endpoint",
            "type": "text",
            "label": "Search Endpoint",
            "help": "For example https://your-service.search.windows.net.",
            "default": "",
            "required": True,
            "placeholder": "https://your-service.search.windows.net",
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
            "depends_on": {"key": "enable_ai_search_apim", "equals": False},
        },
        {
            "key": "azure_ai_search_authentication_type",
            "type": "select",
            "label": "Authentication Type",
            "help": (
                "Managed identity avoids storing a key, and requires the app identity to "
                "hold a Search Index Data Contributor role on the service."
            ),
            "default": "key",
            "options": [
                {"value": "key", "label": "Key"},
                {"value": "managed_identity", "label": "Managed Identity"},
            ],
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
            "depends_on": {"key": "enable_ai_search_apim", "equals": False},
        },
        {
            "key": "azure_ai_search_key",
            "type": "secret",
            "label": "Search Key",
            "help": "An admin key for the search service.",
            "required": True,
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
            "depends_on": {
                "all_of": [
                    {"key": "enable_ai_search_apim", "equals": False},
                    {"key": "azure_ai_search_authentication_type", "equals": "key"},
                ]
            },
        },
        {
            "key": "azure_apim_ai_search_endpoint",
            "type": "text",
            "label": "API Management Endpoint",
            "help": "The API Management URL that fronts Azure AI Search.",
            "default": "",
            "required": True,
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
            "depends_on": {"key": "enable_ai_search_apim", "equals": True},
        },
        {
            "key": "azure_apim_ai_search_subscription_key",
            "type": "secret",
            "label": "API Management Subscription Key",
            "required": True,
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
            "depends_on": {"key": "enable_ai_search_apim", "equals": True},
        },
        {
            "type": "component",
            "component": "connection-test",
            "label": "Test search connection",
            "help": (
                "Runs against the values above, so a connection can be checked before it "
                "is saved."
            ),
            "test_type": "azure_ai_search",
            "test_payload": {
                "enable_apim": {"key": "enable_ai_search_apim"},
                "direct.endpoint": {
                    "key": "azure_ai_search_endpoint",
                    "when": {"key": "enable_ai_search_apim", "equals": False},
                },
                "direct.auth_type": {
                    "key": "azure_ai_search_authentication_type",
                    "when": {"key": "enable_ai_search_apim", "equals": False},
                },
                "direct.key": {
                    "key": "azure_ai_search_key",
                    "when": {"key": "enable_ai_search_apim", "equals": False},
                },
                "apim.endpoint": {
                    "key": "azure_apim_ai_search_endpoint",
                    "when": {"key": "enable_ai_search_apim", "equals": True},
                },
                "apim.subscription_key": {
                    "key": "azure_apim_ai_search_subscription_key",
                    "when": {"key": "enable_ai_search_apim", "equals": True},
                },
            },
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
        },
    ],
    # ------------------------------------------------------------------
    # Knowledge / Web & Research
    #
    # Web Search reaches outside the tenant, so consent comes before
    # configuration: the Grounding with Bing terms move customer data outside the
    # Azure compliance boundary, and the server-rendered pane gates the toggle on
    # accepting them. The same acknowledgement mechanism Custom Pages uses
    # carries that here.
    #
    # The Foundry connection is stored inside `web_search_agent` rather than as
    # top-level keys, so every field in the connection group declares `paths`.
    # ------------------------------------------------------------------
    "web-search-section": [
        {
            "key": "enable_web_search",
            "type": "switch",
            "label": "Enable Web Search via Foundry Agent",
            "help": (
                "Routes web search queries through an Azure AI Foundry agent. Only the "
                "user's current message is sent; conversation history is not."
            ),
            "default": False,
            "role": "capability",
            "requires_acknowledgement": {
                "key": "web_search_consent_accepted",
                "when": "enabled",
                "title": "Web Search Consent Required",
                "message": (
                    "When you use Grounding with Bing Search, your customer data is "
                    "transferred outside of the Azure compliance boundary to the "
                    "Grounding with Bing Search service. Grounding with Bing Search is "
                    "not subject to the same data processing terms (including location "
                    "of processing) and does not have the same compliance standards and "
                    "certifications as the Azure AI Agent Service. It is your "
                    "responsibility to assess whether use of Grounding with Bing Search "
                    "in your agent meets your needs and requirements."
                ),
            },
        },
        {
            "key": "web_search_foundry_endpoint",
            "type": "text",
            "label": "Foundry Project Endpoint",
            "help": (
                "The project endpoint, not the inference endpoint: "
                "https://<foundry-resource>.services.ai.azure.com/api/projects/<project-name>."
            ),
            "default": "",
            "required": True,
            "placeholder": "https://<resource>.services.ai.azure.com/api/projects/<project-name>",
            # Written to both locations because the save handler does, and the
            # runtime still reads the legacy one.
            "paths": [
                "web_search_agent.other_settings.azure_ai_foundry.endpoint",
                "web_search_agent.azure_openai_gpt_endpoint",
            ],
            "group": {
                "id": "connection",
                "label": "Foundry connection",
                "variant": "connection",
            },
            "depends_on": {"key": "enable_web_search", "equals": True},
        },
        {
            "key": "web_search_foundry_api_version",
            "type": "text",
            "label": "Foundry API Version",
            "default": "",
            "required": True,
            "placeholder": "2025-05-01",
            "paths": [
                "web_search_agent.other_settings.azure_ai_foundry.api_version",
                "web_search_agent.azure_openai_gpt_api_version",
            ],
            "group": {"id": "connection", "label": "Foundry connection", "variant": "connection"},
            "depends_on": {"key": "enable_web_search", "equals": True},
        },
        {
            "key": "web_search_foundry_agent_id",
            "type": "text",
            "label": "Foundry Agent ID",
            "help": "Typically starts with asst_.",
            "default": "",
            "required": True,
            "placeholder": "asst_...",
            "paths": ["web_search_agent.other_settings.azure_ai_foundry.agent_id"],
            "group": {"id": "connection", "label": "Foundry connection", "variant": "connection"},
            "depends_on": {"key": "enable_web_search", "equals": True},
        },
        {
            "key": "web_search_foundry_auth_type",
            "type": "select",
            "label": "Authentication Type",
            "help": (
                "The identity must hold Cognitive Services User and AI Developer roles "
                "on the Foundry project."
            ),
            "default": "managed_identity",
            "options": [
                {"value": "managed_identity", "label": "Managed Identity"},
                {"value": "service_principal", "label": "Service Principal"},
            ],
            "paths": ["web_search_agent.other_settings.azure_ai_foundry.authentication_type"],
            "group": {"id": "connection", "label": "Foundry connection", "variant": "connection"},
            "depends_on": {"key": "enable_web_search", "equals": True},
        },
        {
            "key": "web_search_foundry_managed_identity_type",
            "type": "select",
            "label": "Managed Identity Type",
            "default": "system_assigned",
            "options": [
                {"value": "system_assigned", "label": "System-assigned (SAMI)"},
                {"value": "user_assigned", "label": "User-assigned (UAMI)"},
            ],
            "paths": ["web_search_agent.other_settings.azure_ai_foundry.managed_identity_type"],
            "group": {"id": "connection", "label": "Foundry connection", "variant": "connection"},
            "depends_on": {
                "all_of": [
                    {"key": "enable_web_search", "equals": True},
                    {"key": "web_search_foundry_auth_type", "equals": "managed_identity"},
                ]
            },
        },
        {
            "key": "web_search_foundry_managed_identity_client_id",
            "type": "text",
            "label": "Managed Identity Client ID",
            "help": "Only needed for a user-assigned managed identity.",
            "default": "",
            "required": True,
            "placeholder": "Client ID for user-assigned managed identity",
            "paths": [
                "web_search_agent.other_settings.azure_ai_foundry.managed_identity_client_id"
            ],
            "group": {"id": "connection", "label": "Foundry connection", "variant": "connection"},
            "depends_on": {
                "all_of": [
                    {"key": "enable_web_search", "equals": True},
                    {"key": "web_search_foundry_auth_type", "equals": "managed_identity"},
                    {
                        "key": "web_search_foundry_managed_identity_type",
                        "equals": "user_assigned",
                    },
                ]
            },
        },
        {
            "key": "web_search_foundry_tenant_id",
            "type": "text",
            "label": "Tenant ID",
            "default": "",
            "required": True,
            "placeholder": "Entra tenant ID",
            "paths": ["web_search_agent.other_settings.azure_ai_foundry.tenant_id"],
            "group": {"id": "connection", "label": "Foundry connection", "variant": "connection"},
            "depends_on": {
                "all_of": [
                    {"key": "enable_web_search", "equals": True},
                    {"key": "web_search_foundry_auth_type", "equals": "service_principal"},
                ]
            },
        },
        {
            "key": "web_search_foundry_client_id",
            "type": "text",
            "label": "Client ID",
            "default": "",
            "required": True,
            "placeholder": "App registration client ID",
            "paths": ["web_search_agent.other_settings.azure_ai_foundry.client_id"],
            "group": {"id": "connection", "label": "Foundry connection", "variant": "connection"},
            "depends_on": {
                "all_of": [
                    {"key": "enable_web_search", "equals": True},
                    {"key": "web_search_foundry_auth_type", "equals": "service_principal"},
                ]
            },
        },
        {
            "key": "web_search_foundry_client_secret",
            "type": "secret",
            "label": "Client Secret",
            "help": "A secret value or a Key Vault reference.",
            "required": True,
            "placeholder": "Secret or Key Vault reference",
            "paths": ["web_search_agent.other_settings.azure_ai_foundry.client_secret"],
            "group": {"id": "connection", "label": "Foundry connection", "variant": "connection"},
            "depends_on": {
                "all_of": [
                    {"key": "enable_web_search", "equals": True},
                    {"key": "web_search_foundry_auth_type", "equals": "service_principal"},
                ]
            },
        },
        {
            "key": "web_search_foundry_cloud",
            "type": "select",
            "label": "Cloud",
            "default": "",
            "options": [
                {"value": "", "label": "Azure Public"},
                {"value": "usgov", "label": "Azure Government"},
                {"value": "custom", "label": "Custom"},
            ],
            "paths": ["web_search_agent.other_settings.azure_ai_foundry.cloud"],
            "group": {"id": "connection", "label": "Foundry connection", "variant": "connection"},
            "depends_on": {
                "all_of": [
                    {"key": "enable_web_search", "equals": True},
                    {"key": "web_search_foundry_auth_type", "equals": "service_principal"},
                ]
            },
        },
        {
            "key": "web_search_foundry_authority",
            "type": "text",
            "label": "Authority Endpoint",
            "help": "Only needed for a custom cloud.",
            "default": "",
            "required": True,
            "placeholder": "https://login.microsoftonline.com/",
            "paths": ["web_search_agent.other_settings.azure_ai_foundry.authority"],
            "group": {"id": "connection", "label": "Foundry connection", "variant": "connection"},
            "depends_on": {
                "all_of": [
                    {"key": "enable_web_search", "equals": True},
                    {"key": "web_search_foundry_auth_type", "equals": "service_principal"},
                    {"key": "web_search_foundry_cloud", "equals": "custom"},
                ]
            },
        },
        {
            "type": "component",
            "component": "connection-test",
            "label": "Test web search",
            "help": "Runs a search through the configured agent using the values above.",
            "test_type": "web_search",
            "test_payload": {
                "enabled": {"key": "enable_web_search"},
                "consent_accepted": {"value": True},
                "query": {"value": "What is Azure AI Foundry?"},
                "foundry.endpoint": {"key": "web_search_foundry_endpoint"},
                "foundry.api_version": {"key": "web_search_foundry_api_version"},
                "foundry.agent_id": {"key": "web_search_foundry_agent_id"},
                "foundry.authentication_type": {"key": "web_search_foundry_auth_type"},
                "foundry.managed_identity_type": {
                    "key": "web_search_foundry_managed_identity_type",
                    "when": {
                        "key": "web_search_foundry_auth_type",
                        "equals": "managed_identity",
                    },
                },
                "foundry.managed_identity_client_id": {
                    "key": "web_search_foundry_managed_identity_client_id",
                    "when": {
                        "key": "web_search_foundry_auth_type",
                        "equals": "managed_identity",
                    },
                },
                "foundry.tenant_id": {
                    "key": "web_search_foundry_tenant_id",
                    "when": {
                        "key": "web_search_foundry_auth_type",
                        "equals": "service_principal",
                    },
                },
                "foundry.client_id": {
                    "key": "web_search_foundry_client_id",
                    "when": {
                        "key": "web_search_foundry_auth_type",
                        "equals": "service_principal",
                    },
                },
                "foundry.client_secret": {
                    "key": "web_search_foundry_client_secret",
                    "when": {
                        "key": "web_search_foundry_auth_type",
                        "equals": "service_principal",
                    },
                },
                "foundry.cloud": {
                    "key": "web_search_foundry_cloud",
                    "when": {
                        "key": "web_search_foundry_auth_type",
                        "equals": "service_principal",
                    },
                },
                "foundry.authority": {
                    "key": "web_search_foundry_authority",
                    "when": {
                        "key": "web_search_foundry_auth_type",
                        "equals": "service_principal",
                    },
                },
            },
            "group": {"id": "connection", "label": "Foundry connection", "variant": "connection"},
            "depends_on": {"key": "enable_web_search", "equals": True},
        },
        {
            "key": "enable_web_search_user_notice",
            "type": "switch",
            "label": "Show data notice to users when web search is used",
            "help": (
                "Tells users their message leaves the tenant, which is the only warning "
                "they get before it does."
            ),
            "default": False,
            "group": {
                "id": "notice",
                "label": "User notice",
                "variant": "behavior",
            },
            "depends_on": {"key": "enable_web_search", "equals": True},
        },
        {
            "key": "web_search_user_notice_text",
            "type": "textarea",
            "label": "Notice Text",
            "help": "Shown once per session, the first time a user runs a web search.",
            "default": WEB_SEARCH_USER_NOTICE_DEFAULT_TEXT,
            "rows": 3,
            "max_length": 1000,
            "fallback_when_empty": True,
            "group": {"id": "notice", "label": "User notice", "variant": "behavior"},
            "depends_on": {
                "all_of": [
                    {"key": "enable_web_search", "equals": True},
                    {"key": "enable_web_search_user_notice", "equals": True},
                ]
            },
        },
    ],
    # URL Access is genuinely shared policy: chat, workflows and Deep Research all
    # fetch through it, and the allow and block lists below are the same lists
    # Deep Research reads. The role requirement comes first because it decides who
    # can reach the capability at all.
    "url-access-section": [
        {
            "key": "enable_url_access",
            "type": "switch",
            "label": "Enable URL Access for chat and workflows",
            "help": (
                "Lets pasted links be fetched and read. Non-HTTP(S) URLs, credentialed "
                "URLs, literal IPs, localhost, metadata hosts, unsafe redirects and "
                "oversized pages are refused before any fetch is made."
            ),
            "default": False,
            "role": "capability",
        },
        {
            "key": "require_member_of_url_access_user",
            "type": "switch",
            "label": "Require UrlAccessUser App Role",
            "help": (
                "Required app role value: UrlAccessUser. Assign it in the Enterprise App "
                "before turning this on, or nobody will be able to use URL Access."
            ),
            "default": False,
            "group": {"id": "access", "label": "Access", "variant": "access"},
        },
        {
            "key": "url_access_max_chat_urls_per_turn",
            "type": "number",
            "label": "Chat URL Limit",
            "help": "Direct URLs read per chat message. Hard limit 100.",
            "default": 10,
            "min": 1,
            "max": 100,
            "group": {"id": "limits", "label": "Limits", "variant": "limits"},
            "depends_on": {"key": "enable_url_access", "equals": True},
        },
        {
            "key": "url_access_max_workflow_urls_per_run",
            "type": "number",
            "label": "Workflow URL Limit",
            "help": "Direct URLs read per workflow prompt. Hard limit 500.",
            "default": 50,
            "min": 1,
            "max": 500,
            "group": {"id": "limits", "label": "Limits", "variant": "limits"},
            "depends_on": {"key": "enable_url_access", "equals": True},
        },
        {
            "key": "url_access_allowed_domains",
            "type": "string_list",
            "label": "Allowed Domains",
            "help": (
                "Leave empty to allow any public domain that passes the safety checks. "
                "Deep Research reads this same list."
            ),
            "default": [],
            "placeholder": "example.com or *.contoso.com",
            "entry_pattern": r"^[A-Za-z0-9*][A-Za-z0-9*.\-]*$",
            "entry_label": "domain",
            # Stored twice, because Deep Research reads the source_review copy and
            # the save handler writes both.
            "paths": ["url_access_allowed_domains", "source_review_allowed_domains"],
            "group": {"id": "policy", "label": "Domain policy", "variant": "access"},
        },
        {
            "key": "url_access_blocked_domains",
            "type": "string_list",
            "label": "Blocked Domains",
            "help": "Applies to URL Access and to Deep Research source-page review.",
            "default": [],
            "placeholder": "example.org or *.contoso.net",
            "entry_pattern": r"^[A-Za-z0-9*][A-Za-z0-9*.\-]*$",
            "entry_label": "domain",
            "paths": ["url_access_blocked_domains", "source_review_blocked_domains"],
            "group": {"id": "policy", "label": "Domain policy", "variant": "access"},
        },
        {
            "type": "component",
            "component": "connection-test",
            "label": "Test URL policy",
            "help": "Checks a URL against the allow and block lists above before saving.",
            "test_type": "url_access_policy",
            "test_payload": {
                "enabled": {"key": "enable_url_access"},
                "url": {"value": "https://example.com/"},
                "source_review_allow_internal_hosts": {
                    "key": "source_review_allow_internal_hosts"
                },
                "url_access_allowed_domains": {"key": "url_access_allowed_domains"},
                "url_access_blocked_domains": {"key": "url_access_blocked_domains"},
            },
            "group": {"id": "policy", "label": "Domain policy", "variant": "access"},
        },
    ],
    # Deep Research plans bounded searches and inspects pages. Its budgets are
    # what keep it bounded, so they sit together and above the behaviour switches
    # rather than being interleaved with them as they are in the V1 pane.
    #
    # Direct pasted URLs are governed by URL Access, not here, and the allow and
    # block lists are shared with it.
    "source-review-section": [
        {
            "key": "enable_source_review",
            "type": "switch",
            "label": "Enable Deep Research for chat",
            "help": (
                "Plans bounded web searches, inspects source pages, and keeps a research "
                "ledger. Runs only when a user selects it for a message."
            ),
            "default": False,
            "role": "capability",
        },
        {
            "key": "require_member_of_deep_research_user",
            "type": "switch",
            "label": "Require DeepResearchUser App Role",
            "help": (
                "Required app role value: DeepResearchUser. Assign it in the Enterprise "
                "App before turning this on, or nobody will be able to use Deep Research."
            ),
            "default": False,
            "group": {"id": "access", "label": "Access", "variant": "access"},
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            "key": "source_review_allow_internal_hosts",
            "type": "switch",
            "label": "Allow internal network hostnames",
            "help": (
                "Permits DNS hostnames that resolve to private addresses. Literal IP "
                "targets, localhost, metadata hosts, link-local and reserved addresses "
                "stay blocked regardless."
            ),
            "default": False,
            "group": {"id": "access", "label": "Access", "variant": "access"},
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            "key": "source_review_max_pages_per_turn",
            "type": "number",
            "label": "Max Pages per Turn",
            "help": "Hard limit 10.",
            "default": 10,
            "min": 1,
            "max": 10,
            "group": {"id": "budgets", "label": "Budgets", "variant": "limits"},
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            "key": "source_review_max_seed_pages_per_turn",
            "type": "number",
            "label": "Max Seed Pages per Turn",
            "help": (
                "Caps initial search-result and direct URL pages so budget is left for "
                "the pages they link to."
            ),
            "default": 10,
            "min": 1,
            "max": 10,
            "group": {"id": "budgets", "label": "Budgets", "variant": "limits"},
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            "key": "deep_research_max_user_urls_per_turn",
            "type": "number",
            "label": "Max User URLs per Turn",
            "help": "Direct URLs past this cap are recorded as omitted in the ledger.",
            "default": 100,
            "min": 1,
            "max": 100,
            "group": {"id": "budgets", "label": "Budgets", "variant": "limits"},
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            "key": "deep_research_max_search_queries_per_turn",
            "type": "number",
            "label": "Max Search Queries per Turn",
            "help": "Includes the original current-message query.",
            "default": 8,
            "min": 1,
            "max": 8,
            "group": {"id": "budgets", "label": "Budgets", "variant": "limits"},
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            "key": "source_review_timeout_seconds",
            "type": "number",
            "label": "Timeout per Turn",
            "help": "Hard limit 30 seconds.",
            "default": 30,
            "min": 3,
            "max": 30,
            "suffix": "s",
            "group": {"id": "budgets", "label": "Budgets", "variant": "limits"},
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            "key": "source_review_max_redirects",
            "type": "number",
            "label": "Max Redirects",
            "help": "Every redirect target is revalidated against the URL policy.",
            "default": 5,
            "min": 0,
            "max": 5,
            "group": {"id": "budgets", "label": "Budgets", "variant": "limits"},
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            "key": "source_review_max_bytes_per_page_mb",
            "type": "number",
            "label": "Max MB per Page",
            "help": "Hard limit 5 MB.",
            "default": 5,
            "min": 1,
            "max": 5,
            "suffix": " MB",
            "group": {"id": "budgets", "label": "Budgets", "variant": "limits"},
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            "key": "source_review_max_depth",
            "type": "number",
            "label": "Source Traversal Depth",
            "help": "Depth 2 follows selected links from seed and child pages.",
            "default": 2,
            "min": 0,
            "max": 2,
            "group": {"id": "budgets", "label": "Budgets", "variant": "limits"},
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            "key": "enable_deep_source_review",
            "type": "switch",
            "label": "Inspect linked source pages",
            "help": (
                "Follows only scored, policy-approved links, within the page and depth "
                "budgets above."
            ),
            "default": True,
            "group": {"id": "behavior", "label": "Research behaviour", "variant": "behavior"},
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            "key": "deep_research_enable_query_planning",
            "type": "switch",
            "label": "Plan multiple web search queries",
            "help": (
                "The selected chat model proposes bounded query variants, drawn from the "
                "current message only, before any page is reviewed."
            ),
            "default": True,
            "group": {"id": "behavior", "label": "Research behaviour", "variant": "behavior"},
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            "key": "deep_research_enable_ledger_artifact",
            "type": "switch",
            "label": "Save research ledger artifacts",
            "help": (
                "Writes a Markdown artifact recording search queries, reviewed sources, "
                "skipped URLs and coverage, so a result can be audited afterwards."
            ),
            "default": True,
            "group": {"id": "behavior", "label": "Research behaviour", "variant": "behavior"},
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            "key": "source_review_enable_llm_planning",
            "type": "switch",
            "label": "Use model-assisted source link planning",
            "help": (
                "Lets the selected chat model rank candidate links a page exposes before "
                "the server fetches any of them."
            ),
            "default": True,
            "group": {"id": "behavior", "label": "Research behaviour", "variant": "behavior"},
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            "key": "source_review_respect_robots_txt",
            "type": "switch",
            "label": "Respect robots.txt",
            "default": True,
            "group": {"id": "behavior", "label": "Research behaviour", "variant": "behavior"},
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            "key": "source_review_audit_logging",
            "type": "switch",
            "label": "Log Deep Research activity",
            "default": True,
            "group": {"id": "behavior", "label": "Research behaviour", "variant": "behavior"},
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            "key": "source_review_allow_js_rendering",
            "type": "switch",
            "label": "Allow JavaScript rendering fallback",
            "help": "Requires a verified Playwright browser runtime on the app host.",
            "default": True,
            "group": {
                "id": "rendering",
                "label": "JavaScript rendering",
                "variant": "advanced",
            },
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            # V1 disables the switch above and explains why in loose markup beneath
            # it. Declaring the readout keeps the reason next to the control and
            # makes it searchable, rather than leaving an option that looks broken.
            "type": "status",
            "label": "Browser runtime",
            "status_source": "source_review_js_runtime",
            "help": (
                "Without the Playwright Chromium runtime, pages that build their content "
                "in the browser are read as empty."
            ),
            "group": {
                "id": "rendering",
                "label": "JavaScript rendering",
                "variant": "advanced",
            },
            "depends_on": {"key": "enable_source_review", "equals": True},
        },
        {
            "key": "source_review_js_load_more_clicks",
            "type": "number",
            "label": "Rendered Load More Clicks",
            "help": (
                "How many visible Load More controls Deep Research may click while "
                "rendering a page."
            ),
            "default": 12,
            "min": 0,
            "max": 12,
            "group": {
                "id": "rendering",
                "label": "JavaScript rendering",
                "variant": "advanced",
            },
            "depends_on": {
                "all_of": [
                    {"key": "enable_source_review", "equals": True},
                    {"key": "source_review_allow_js_rendering", "equals": True},
                ]
            },
        },
    ],
    # ------------------------------------------------------------------
    # Knowledge / Document Extraction
    #
    # Reordered relative to the server-rendered pane, which is the point of
    # describing it. There, "Enable Enhanced extraction" is the first control and
    # the Document Intelligence endpoint and key are the last, several hundred
    # lines below, after the extraction mode, formula extraction, Content
    # Understanding and Office image options. An administrator turns a feature on
    # and then scrolls past everything that depends on the connection before
    # reaching the connection itself.
    #
    # Here the connection comes first and the behaviour that needs it follows,
    # declaring `requires` so a toggle flipped without a configured endpoint says
    # so rather than silently doing nothing.
    # ------------------------------------------------------------------
    "document-intelligence-section": [
        {
            "key": "enable_document_intelligence_apim",
            "type": "switch",
            "label": "Route through API Management",
            "help": (
                "Send Document Intelligence requests through API Management for "
                "centralized monitoring and control instead of reaching the service "
                "directly."
            ),
            "default": False,
            "group": {
                "id": "connection",
                "label": "Connection",
                "variant": "connection",
                "help": (
                    "Document Intelligence reads PDFs and images. Nothing else in this "
                    "tab works until it is reachable."
                ),
            },
        },
        {
            "key": "azure_document_intelligence_endpoint",
            "type": "text",
            "label": "Document Intelligence Endpoint",
            "default": "",
            "required": True,
            "placeholder": "https://your-resource.cognitiveservices.azure.com/",
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
            "depends_on": {"key": "enable_document_intelligence_apim", "equals": False},
        },
        {
            "key": "azure_document_intelligence_authentication_type",
            "type": "select",
            "label": "Authentication Type",
            "help": (
                "Managed identity requires the app identity to hold Cognitive Services "
                "User on the resource."
            ),
            "default": "key",
            "options": [
                {"value": "key", "label": "Key"},
                {"value": "managed_identity", "label": "Managed Identity"},
            ],
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
            "depends_on": {"key": "enable_document_intelligence_apim", "equals": False},
        },
        {
            "key": "azure_document_intelligence_key",
            "type": "secret",
            "label": "Document Intelligence Key",
            "required": True,
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
            "depends_on": {
                "all_of": [
                    {"key": "enable_document_intelligence_apim", "equals": False},
                    {"key": "azure_document_intelligence_authentication_type", "equals": "key"},
                ]
            },
        },
        {
            "key": "azure_apim_document_intelligence_endpoint",
            "type": "text",
            "label": "API Management Endpoint",
            "default": "",
            "required": True,
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
            "depends_on": {"key": "enable_document_intelligence_apim", "equals": True},
        },
        {
            "key": "azure_apim_document_intelligence_subscription_key",
            "type": "secret",
            "label": "API Management Subscription Key",
            "required": True,
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
            "depends_on": {"key": "enable_document_intelligence_apim", "equals": True},
        },
        {
            "type": "component",
            "component": "connection-test",
            "label": "Test Document Intelligence connection",
            "help": "Analyses a small sample document using the values above.",
            "test_type": "azure_doc_intelligence",
            "test_payload": {
                "enable_apim": {"key": "enable_document_intelligence_apim"},
                "document_intelligence_pdf_image_extraction_mode": {
                    "key": "document_intelligence_pdf_image_extraction_mode"
                },
                "document_intelligence_auto_sample_pages": {
                    "key": "document_intelligence_auto_sample_pages"
                },
                "direct.endpoint": {
                    "key": "azure_document_intelligence_endpoint",
                    "when": {"key": "enable_document_intelligence_apim", "equals": False},
                },
                "direct.auth_type": {
                    "key": "azure_document_intelligence_authentication_type",
                    "when": {"key": "enable_document_intelligence_apim", "equals": False},
                },
                "direct.key": {
                    "key": "azure_document_intelligence_key",
                    "when": {"key": "enable_document_intelligence_apim", "equals": False},
                },
                "apim.endpoint": {
                    "key": "azure_apim_document_intelligence_endpoint",
                    "when": {"key": "enable_document_intelligence_apim", "equals": True},
                },
                "apim.subscription_key": {
                    "key": "azure_apim_document_intelligence_subscription_key",
                    "when": {"key": "enable_document_intelligence_apim", "equals": True},
                },
            },
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
        },
        {
            "key": "document_intelligence_pdf_image_extraction_mode",
            "type": "select",
            "label": "PDF and Image Extraction Mode",
            "help": (
                "Standard is Document Intelligence Read: fastest and cheapest for plain "
                "text. Enhanced captures tables, page structure, forms and checkbox "
                "states, at roughly six times the cost per thousand pages. Auto samples "
                "the first pages and picks."
            ),
            "default": "read",
            "options": [
                {"value": "read", "label": "Standard — faster text extraction"},
                {
                    "value": "layout",
                    "label": "Enhanced — richer structure, tables and checkbox states",
                },
                {
                    "value": "auto",
                    "label": "Auto — sample first pages, then choose",
                },
            ],
            "group": {"id": "extraction", "label": "Extraction", "variant": "behavior"},
        },
        {
            "key": "document_intelligence_auto_sample_pages",
            "type": "number",
            "label": "Auto Sample Pages",
            "help": (
                "How many opening PDF pages Auto inspects. If it finds tables, selection "
                "marks or figures the whole document uses Enhanced; otherwise it "
                "finishes with Standard. Images always use Enhanced in Auto mode."
            ),
            "default": 3,
            "min": 1,
            "max": 20,
            "group": {"id": "extraction", "label": "Extraction", "variant": "behavior"},
            "depends_on": {
                "key": "document_intelligence_pdf_image_extraction_mode",
                "equals": "auto",
            },
        },
        {
            "key": "enable_enhanced_extraction",
            "type": "switch",
            "label": "Enable Enhanced extraction",
            "help": (
                "Uses Azure AI Content Understanding, which returns tables, page "
                "structure, checkbox states and descriptions of figures and charts. "
                "Falls back to Document Intelligence Layout where Content Understanding "
                "is unavailable or unconfigured."
            ),
            "default": False,
            "group": {"id": "extraction", "label": "Extraction", "variant": "behavior"},
        },
        {
            "key": "enable_document_intelligence_formula_extraction",
            "type": "switch",
            "label": "Extract mathematical formulas",
            "help": (
                "Captures equations as LaTeX rather than approximate OCR text. This is a "
                "billed Document Intelligence add-on that adds per-page cost to every "
                "Enhanced extraction, and it has no effect while extraction is Standard."
            ),
            "default": False,
            "group": {"id": "extraction", "label": "Extraction", "variant": "behavior"},
        },
    ],
    # Its own section now. The card has always been in the extraction pane but
    # was missing from ADMIN_NAV, so neither interface could navigate to it.
    "content-understanding-section": [
        {
            "key": "azure_content_understanding_endpoint",
            "type": "text",
            "label": "Foundry Endpoint",
            "help": (
                "The Microsoft Foundry resource endpoint, with no trailing path. Leave "
                "blank and Enhanced extraction falls back to Document Intelligence "
                "Layout."
            ),
            "default": "",
            "placeholder": "https://your-resource.services.ai.azure.com",
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
        },
        {
            "key": "azure_content_understanding_authentication_type",
            "type": "select",
            "label": "Authentication Type",
            "help": (
                "Managed identity requires the Cognitive Services User role on the "
                "Foundry resource."
            ),
            "default": "key",
            "options": [
                {"value": "key", "label": "Key"},
                {"value": "managed_identity", "label": "Managed Identity"},
            ],
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
        },
        {
            "key": "azure_content_understanding_key",
            "type": "secret",
            "label": "Content Understanding Key",
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
            "depends_on": {
                "key": "azure_content_understanding_authentication_type",
                "equals": "key",
            },
        },
        {
            "key": "azure_content_understanding_api_version",
            "type": "text",
            "label": "API Version",
            "default": "",
            "fallback_when_empty": True,
            "group": {"id": "analyzers", "label": "Analyzers", "variant": "advanced"},
        },
        {
            "key": "azure_content_understanding_analyzer_id",
            "type": "text",
            "label": "Document Analyzer",
            "default": "",
            "fallback_when_empty": True,
            "group": {"id": "analyzers", "label": "Analyzers", "variant": "advanced"},
        },
        {
            "key": "azure_content_understanding_image_analyzer_id",
            "type": "text",
            "label": "Image Analyzer",
            "default": "",
            "fallback_when_empty": True,
            "group": {"id": "analyzers", "label": "Analyzers", "variant": "advanced"},
        },
        {
            "type": "component",
            "component": "connection-test",
            "label": "Test Content Understanding connection",
            "test_type": "content_understanding",
            "test_payload": {
                "endpoint": {"key": "azure_content_understanding_endpoint"},
                "authentication_type": {
                    "key": "azure_content_understanding_authentication_type"
                },
                "key": {"key": "azure_content_understanding_key"},
                "api_version": {"key": "azure_content_understanding_api_version"},
                "analyzer_id": {"key": "azure_content_understanding_analyzer_id"},
                "image_analyzer_id": {
                    "key": "azure_content_understanding_image_analyzer_id"
                },
            },
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
        },
    ],
    # Also promoted out of the extraction card into a section of its own. It is
    # independent of Enhanced extraction despite sitting inside it in the V1
    # markup, which is what made it read as part of that feature.
    "office-embedded-image-section": [
        {
            "key": "enable_office_embedded_image_analysis",
            "type": "switch",
            "label": "Analyze images embedded in DOCX and PPTX files",
            "help": (
                "Neither extraction engine describes figures inside Word and PowerPoint "
                "files. With this on, embedded images are pulled out, analysed with "
                "whichever engine backs the selected extraction mode, and indexed as "
                "their own citable chunks. Works with Standard extraction too."
            ),
            "default": True,
            "role": "capability",
        },
        {
            "key": "office_embedded_image_min_pixels",
            "type": "number",
            "label": "Minimum Image Size (pixels)",
            "help": "Images narrower or shorter than this are skipped as icons or spacers.",
            "default": 150,
            "min": 1,
            "max": 2000,
            "group": {"id": "limits", "label": "Limits", "variant": "limits"},
            "depends_on": {"key": "enable_office_embedded_image_analysis", "equals": True},
        },
        {
            "key": "office_embedded_image_max_per_document",
            "type": "number",
            "label": "Maximum Images Per Document",
            "help": "Caps per-document cost. Duplicate images are analysed once.",
            "default": 25,
            "min": 0,
            "max": 200,
            "group": {"id": "limits", "label": "Limits", "variant": "limits"},
            "depends_on": {"key": "enable_office_embedded_image_analysis", "equals": True},
        },
    ],
    # Chunk sizes live in a single `chunk_size` object as {key: {value, unit}},
    # so each field declares its path into it. The assembled object is clamped to
    # the embedding model's budget on save by PATH_CONTAINER_NORMALIZERS, which
    # is what the server-rendered form does too: a chunk larger than that budget
    # can never embed, whatever an administrator saves.
    #
    # The cap is stated up front rather than as a warning that only appears once
    # it has already been exceeded.
    "chunk-size-section": [
        {
            "key": "enable_chunk_size_override",
            "type": "switch",
            "label": "Enable custom chunk sizes by file type",
            "help": (
                "Applies to new uploads only; documents already indexed keep the chunks "
                "they were built with. Sizes are capped at what fits in one embedding "
                "request for the deployed model, and anything larger is reduced on save."
            ),
            "default": False,
            "role": "capability",
        },
        {
            "key": "chunk_size_txt",
            "type": "number",
            "label": "TXT (words)",
            "default": 400,
            "min": 1,
            "paths": ["chunk_size.txt.value"],
            "group": {"id": "sizes", "label": "Sizes by file type", "variant": "behavior"},
            "depends_on": {"key": "enable_chunk_size_override", "equals": True},
        },
        {
            "key": "chunk_size_log",
            "type": "number",
            "label": "LOG (words)",
            "default": 1000,
            "min": 1,
            "paths": ["chunk_size.log.value"],
            "group": {"id": "sizes", "label": "Sizes by file type", "variant": "behavior"},
            "depends_on": {"key": "enable_chunk_size_override", "equals": True},
        },
        {
            "key": "chunk_size_doc",
            "type": "number",
            "label": "DOC (words)",
            "default": 400,
            "min": 1,
            "paths": ["chunk_size.doc.value"],
            "group": {"id": "sizes", "label": "Sizes by file type", "variant": "behavior"},
            "depends_on": {"key": "enable_chunk_size_override", "equals": True},
        },
        {
            "key": "chunk_size_docm",
            "type": "number",
            "label": "DOCM (words)",
            "default": 400,
            "min": 1,
            "paths": ["chunk_size.docm.value"],
            "group": {"id": "sizes", "label": "Sizes by file type", "variant": "behavior"},
            "depends_on": {"key": "enable_chunk_size_override", "equals": True},
        },
        {
            "key": "chunk_size_docx",
            "type": "number",
            "label": "DOCX (words)",
            "default": 400,
            "min": 1,
            "paths": ["chunk_size.docx.value"],
            "group": {"id": "sizes", "label": "Sizes by file type", "variant": "behavior"},
            "depends_on": {"key": "enable_chunk_size_override", "equals": True},
        },
        {
            "key": "chunk_size_html",
            "type": "number",
            "label": "HTML (words)",
            "default": 1200,
            "min": 1,
            "paths": ["chunk_size.html.value"],
            "group": {"id": "sizes", "label": "Sizes by file type", "variant": "behavior"},
            "depends_on": {"key": "enable_chunk_size_override", "equals": True},
        },
        {
            "key": "chunk_size_md",
            "type": "number",
            "label": "Markdown (words)",
            "default": 1200,
            "min": 1,
            "paths": ["chunk_size.md.value"],
            "group": {"id": "sizes", "label": "Sizes by file type", "variant": "behavior"},
            "depends_on": {"key": "enable_chunk_size_override", "equals": True},
        },
        {
            "key": "chunk_size_xml",
            "type": "number",
            "label": "XML (characters)",
            "default": 4000,
            "min": 1,
            "paths": ["chunk_size.xml.value"],
            "group": {"id": "sizes", "label": "Sizes by file type", "variant": "behavior"},
            "depends_on": {"key": "enable_chunk_size_override", "equals": True},
        },
        {
            "key": "chunk_size_yaml",
            "type": "number",
            "label": "YAML (characters)",
            "default": 4000,
            "min": 1,
            "paths": ["chunk_size.yaml.value"],
            "group": {"id": "sizes", "label": "Sizes by file type", "variant": "behavior"},
            "depends_on": {"key": "enable_chunk_size_override", "equals": True},
        },
        {
            "key": "chunk_size_yml",
            "type": "number",
            "label": "YML (characters)",
            "default": 4000,
            "min": 1,
            "paths": ["chunk_size.yml.value"],
            "group": {"id": "sizes", "label": "Sizes by file type", "variant": "behavior"},
            "depends_on": {"key": "enable_chunk_size_override", "equals": True},
        },
        {
            "key": "chunk_size_json",
            "type": "number",
            "label": "JSON (characters)",
            "default": 4000,
            "min": 1,
            "paths": ["chunk_size.json.value"],
            "group": {"id": "sizes", "label": "Sizes by file type", "variant": "behavior"},
            "depends_on": {"key": "enable_chunk_size_override", "equals": True},
        },
        {
            "key": "chunk_size_csv",
            "type": "number",
            "label": "CSV (characters)",
            "default": 800,
            "min": 1,
            "paths": ["chunk_size.csv.value"],
            "group": {"id": "sizes", "label": "Sizes by file type", "variant": "behavior"},
            "depends_on": {"key": "enable_chunk_size_override", "equals": True},
        },
        {
            "key": "chunk_size_excel",
            "type": "number",
            "label": "Excel (characters)",
            "default": 800,
            "min": 1,
            "paths": ["chunk_size.excel.value"],
            "group": {"id": "sizes", "label": "Sizes by file type", "variant": "behavior"},
            "depends_on": {"key": "enable_chunk_size_override", "equals": True},
        },
        {
            "key": "chunk_size_transcript",
            "type": "number",
            "label": "Transcripts (words)",
            "default": 400,
            "min": 1,
            "paths": ["chunk_size.transcript.value"],
            "group": {"id": "sizes", "label": "Sizes by file type", "variant": "behavior"},
            "depends_on": {"key": "enable_chunk_size_override", "equals": True},
        },
        {
            "key": "chunk_size_pdf",
            "type": "number",
            "label": "PDF (pages)",
            "default": 1,
            "min": 1,
            "paths": ["chunk_size.pdf.value"],
            "group": {"id": "sizes", "label": "Sizes by file type", "variant": "behavior"},
            "depends_on": {"key": "enable_chunk_size_override", "equals": True},
        },
        {
            "key": "chunk_size_pptx",
            "type": "number",
            "label": "PPT/PPTX (slides)",
            "default": 1,
            "min": 1,
            "paths": ["chunk_size.pptx.value"],
            "group": {"id": "sizes", "label": "Sizes by file type", "variant": "behavior"},
            "depends_on": {"key": "enable_chunk_size_override", "equals": True},
        },
    ],
    # The model picker itself arrives with the vision capability work, which
    # replaces the name-matching heuristic both selectors use today.
    "metadata-extraction-section": [
        {
            "key": "enable_extract_meta_data",
            "type": "switch",
            "label": "Enable metadata extraction",
            "help": (
                "Runs a model over each uploaded document to infer a title, authors, "
                "subject and keywords, which are then searchable alongside the content."
            ),
            "default": False,
            "role": "capability",
        },
        {
            "key": "metadata_extraction_model",
            "type": "component",
            "component": "model-picker",
            "label": "Extraction Model",
            "help": (
                "Uses Global Endpoints when multi-endpoint model management is on; "
                "otherwise the legacy GPT or APIM deployment settings."
            ),
            "placeholder": "No metadata extraction model selected",
            "required": True,
            "group": {"id": "model", "label": "Model", "variant": "connection"},
            "depends_on": {"key": "enable_extract_meta_data", "equals": True},
        },
    ],
    # Vision analysis sends page images to a model, so the picker offers only
    # models that read them. Which models those are used to be decided by
    # matching the model's name against a pattern; it is now resolved from the
    # shipped capability catalog, with an explicit per-model flag able to
    # override it and the name pattern kept only as a last resort.
    "multimodal-vision-section": [
        {
            "key": "enable_multimodal_vision",
            "type": "switch",
            "label": "Enable Multi-Modal Vision Analysis",
            "help": (
                "Sends page images to a vision-capable model so figures, charts and "
                "scanned pages are described and indexed rather than skipped."
            ),
            "default": False,
            "role": "capability",
        },
        {
            "key": "multimodal_vision_model",
            "type": "component",
            "component": "model-picker",
            "label": "Vision Model",
            "help": (
                "Only models that report image support are listed. If a model you expect "
                "is missing, set its image support explicitly under AI Models."
            ),
            "placeholder": "Select a vision-capable model",
            "requires_vision": True,
            "required": True,
            "group": {"id": "model", "label": "Model", "variant": "connection"},
            "depends_on": {"key": "enable_multimodal_vision", "equals": True},
        },
        {
            "type": "component",
            "component": "connection-test",
            "label": "Test vision analysis",
            "help": "Sends a sample image to the selected model.",
            "test_type": "multimodal_vision",
            "test_payload": {
                "vision_model": {"key": "multimodal_vision_model"},
            },
            "group": {"id": "model", "label": "Model", "variant": "connection"},
            "depends_on": {"key": "enable_multimodal_vision", "equals": True},
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
    ],
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
    # Same shape: the Grounding with Bing terms are accepted on the toggle, and
    # the flag rides along with the save rather than being edited on its own.
    "enable_web_search": ["enable_web_search", "web_search_consent_accepted"],
}

# Field names present in the V1 panes that intentionally have no V2 equivalent,
# with the reason. The parity test reads this, so an unexplained omission fails
# rather than passing silently.
LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT = {
    "source_review_default_mode": (
        "Not a real choice. The V1 control is a permanently disabled select "
        "offering one option, shadowed by a hidden input hard-coded to 'manual', "
        "and get_source_review_config rewrites any other value back to 'manual' "
        "on read. Reproducing it would add a control that cannot be changed and "
        "implies a setting that does not exist. Deep Research states the "
        "behaviour in its description instead."
    ),
}


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


def get_legacy_field_names():
    """Return the V1 form field names claimed by the schema."""
    claimed = set()
    for _section_id, field in iter_fields():
        key = field.get("key")
        if not key:
            continue
        claimed.update(LEGACY_FIELD_NAMES.get(key, [key]))
    return claimed


def get_secret_setting_keys():
    """Return every settings key the schema declares as a credential.

    The V2 settings endpoint uses this to replace stored secrets with
    ``SECRET_REDACTED_VALUE`` before the document reaches a browser, which is the
    same protection the server-rendered form gets from
    ``redact_admin_settings_secrets_for_form``.
    """
    return {
        field["key"]
        for _section_id, field in iter_fields()
        if field.get("type") == "secret" and field.get("key")
    }


def get_secret_storage_paths():
    """Return where each declared credential is actually stored.

    A field's key names the control, which for historical reasons is the V1 form
    input name. That is usually also the settings key, but not always: the Web
    Search client secret is stored inside ``web_search_agent``. Redaction has to
    follow the storage location, not the control name, or the secret is
    protected in name only.
    """
    paths = set()
    for _section_id, field in iter_fields():
        if field.get("type") != "secret":
            continue
        declared = field.get("paths")
        if declared:
            paths.update(declared)
        elif field.get("key"):
            paths.add(field["key"])
    return paths


def get_nested_path_fields():
    """Return ``{key: [storage paths]}`` for fields stored outside a top-level key."""
    return {
        field["key"]: list(field["paths"])
        for _section_id, field in iter_fields()
        if field.get("paths") and field.get("key")
    }


def evaluate_dependency(dependency, read_value):
    """Whether a ``depends_on`` condition holds, given a value reader.

    ``read_value`` takes a settings key and returns its current value, so the
    same rules apply whether the caller is reading a stored document or a draft
    that has not been saved yet.

    Four shapes are supported, and they compose:

    ``{"key": k, "equals": v}``      k currently equals v
    ``{"key": k, "not_equals": v}``  k currently differs from v
    ``{"any_of": [...]}``            at least one nested condition holds
    ``{"all_of": [...]}``            every nested condition holds

    ``equals`` against a boolean compares truthiness rather than identity,
    because a settings document written by the server-rendered form stores
    checkbox state as the string ``"on"``.
    """
    if not dependency:
        return True

    if "any_of" in dependency:
        return any(
            evaluate_dependency(nested, read_value) for nested in dependency["any_of"]
        )

    if "all_of" in dependency:
        return all(
            evaluate_dependency(nested, read_value) for nested in dependency["all_of"]
        )

    current = read_value(dependency["key"])

    if "not_equals" in dependency:
        return not _dependency_values_match(current, dependency["not_equals"])

    return _dependency_values_match(current, dependency.get("equals", True))


def _dependency_values_match(current, expected):
    """Compare a stored value against a declared one, tolerating form shapes."""
    if isinstance(expected, bool):
        return _coerce_bool(current) is expected
    return str(current if current is not None else "").strip() == str(expected)


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


def is_redacted_secret(value):
    """Whether a submitted value is the placeholder shown in place of a secret."""
    return str(value if value is not None else "").strip() == SECRET_REDACTED_VALUE


def _normalize_secret(value, field):
    """Return ``(secret, error)`` for a credential field.

    A browser is never sent a stored secret; it is sent ``SECRET_REDACTED_VALUE``
    instead. Submitting that placeholder back therefore means "unchanged", and
    the only safe response is to drop the key from the update entirely. Writing
    the placeholder through would destroy the credential, and writing the
    resolved value through would echo the real secret in the PATCH response.
    """
    if is_redacted_secret(value):
        return SECRET_UNCHANGED, None

    secret = str(value if value is not None else "").strip()
    if len(secret) > SECRET_MAX_LENGTH:
        return None, f"Value is longer than {SECRET_MAX_LENGTH} characters."
    return secret, None


def _normalize_string_list(value, field):
    """Return ``(entries, error)`` for a list of short strings.

    Stored as a list, matching the settings document. The server-rendered form
    round-trips these through a newline-joined textarea, so a string arriving
    here is split the same way that form's handler splits it.
    """
    if isinstance(value, list):
        candidates = [str(item or "") for item in value]
    else:
        candidates = re.split(r"[\n,;]+", str(value if value is not None else ""))

    entries = []
    seen = set()
    for candidate in candidates:
        entry = candidate.strip()
        if not entry:
            continue
        # Case-insensitive, matching parse_source_review_list, so an allow list
        # cannot hold both Example.com and example.com and behave unpredictably.
        folded = entry.lower()
        if folded in seen:
            continue

        pattern = field.get("entry_pattern")
        if pattern and not re.match(pattern, entry):
            return None, f"{entry!r} is not a valid {field.get('entry_label', 'entry')}."

        seen.add(folded)
        entries.append(entry[: field.get("entry_max_length", 253)])

    maximum = field.get("max_entries")
    if maximum is not None and len(entries) > maximum:
        return None, f"Enter at most {maximum} entries."

    return entries, None


def _normalize_id_list(value, field):
    """Return ``(ids, error)`` for a list of opaque identifiers.

    Kept as a JSON array, matching the hidden textareas the server-rendered File
    Sync pane writes, so an assignment saved in one interface is readable in the
    other.
    """
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return [], None
        # The V1 pane stores this as a JSON array inside a textarea, so a string
        # arriving here is most likely that same serialized form.
        try:
            value = json.loads(stripped)
        except ValueError:
            return None, "Expected a list of identifiers."

    if not isinstance(value, list):
        return None, "Expected a list of identifiers."

    ids = []
    for item in value:
        if isinstance(item, dict):
            item = item.get("id")
        identifier = str(item or "").strip()
        if not identifier or identifier in ids:
            continue
        ids.append(identifier[:200])

    maximum = field.get("max_entries")
    if maximum is not None and len(ids) > maximum:
        return None, f"Assign at most {maximum} entries."

    return ids, None


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


def _normalize_field_value(key, value, field):
    """Return ``(normalized, error, warning)`` for one declared field."""
    field_type = field.get("type")

    if field_type in NON_PATCHABLE_TYPES:
        return None, f"{key} cannot be changed through this endpoint.", None

    if key in _DELEGATED_NORMALIZERS:
        return _DELEGATED_NORMALIZERS[key](value, field), None, None

    if field_type == "switch":
        return _coerce_bool(value), None, None

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

    if field_type == "secret":
        secret, error = _normalize_secret(value, field)
        return secret, error, None

    if field_type == "string_list":
        entries, error = _normalize_string_list(value, field)
        return entries, error, None

    if field_type == "id_list":
        ids, error = _normalize_id_list(value, field)
        return ids, error, None

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


def read_nested_setting(document, path):
    """Read a dotted path out of a settings document, or None."""
    cursor = document if isinstance(document, dict) else {}
    for part in str(path or "").split("."):
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(part)
    return cursor


def write_nested_setting(document, path, value):
    """Write a dotted path into a document, creating intermediate objects."""
    parts = str(path or "").split(".")
    cursor = document
    for part in parts[:-1]:
        if not isinstance(cursor.get(part), dict):
            cursor[part] = {}
        cursor = cursor[part]
    cursor[parts[-1]] = value


def _normalize_chunk_size_container(container, current_settings):
    """Clamp assembled chunk sizes to the caps the embedding model allows.

    A chunk has to fit in one embedding request, so a size above the model's
    budget can never embed no matter what is saved. The server-rendered form
    computes those caps from the deployed embedding model and clamps on save;
    doing the same here is what stops the two interfaces accepting different
    values for the same setting.

    Imported lazily because the cap depends on the live settings document, and
    this module is otherwise a pure declaration that several tests import
    without ``config`` available.
    """
    try:
        from functions_settings import get_chunk_size_defaults, get_chunk_size_cap
    except Exception:
        # Without the caps the safe thing is to leave the values alone rather
        # than write unclamped ones; the embed path bounds them again anyway.
        return container, {}

    defaults = get_chunk_size_defaults()
    warnings = {}

    for key, meta in list(container.items()):
        if not isinstance(meta, dict) or "value" not in meta:
            continue

        unit = meta.get("unit") or defaults.get(key, {}).get("unit")
        if unit:
            meta["unit"] = unit

        try:
            value = int(meta["value"])
        except (TypeError, ValueError):
            value = defaults.get(key, {}).get("value", 1)

        cap = get_chunk_size_cap(current_settings, unit)
        clamped = max(1, min(value, cap) if cap else max(1, value))
        if clamped != value:
            warnings[f"chunk_size_{key}"] = (
                f"Reduced to {clamped}, the largest {unit or 'value'} that fits in one "
                "embedding request for the deployed model."
            )
        meta["value"] = clamped

    return container, warnings


# Assembled containers that need a final pass once every declared leaf has been
# written into them. Keyed by the top-level settings key the container lives at.
PATH_CONTAINER_NORMALIZERS = {
    "chunk_size": _normalize_chunk_size_container,
}


def _apply_nested_paths(normalized, current_settings, warnings=None):
    """Move path-declared values to where they are actually stored.

    Most settings are top-level keys, so the normalized dict can be handed
    straight to ``update_settings``. Two cases are not:

    A value assembled into a nested object. The server-rendered form builds the
    Web Search Foundry connection into a single ``web_search_agent`` object, so a
    field named after the form input would write a top-level key nothing reads.

    A value mirrored into more than one key. URL Access domain lists are stored
    twice, once under ``url_access_*`` and once under ``source_review_*``, and
    writing only one leaves Deep Research reading the stale copy.

    A nested container is rebuilt from the stored one and handed back whole,
    because ``update_settings`` merges at the top level only. Writing just the
    changed leaf would replace the object and drop its siblings, so editing the
    Foundry endpoint would silently discard the agent id and the credentials.
    """
    nested_fields = get_nested_path_fields()
    if not nested_fields:
        return normalized

    pending = {key: normalized.pop(key) for key in list(normalized) if key in nested_fields}
    if not pending:
        return normalized

    # One deep copy per containing object, seeded from what is stored so untouched
    # siblings survive the write.
    containers = {}
    for key, value in pending.items():
        for path in nested_fields[key]:
            root, _, remainder = path.partition(".")
            if not remainder:
                # A plain mirror to another top-level key.
                normalized[root] = value
                continue

            if root not in containers:
                stored = current_settings.get(root)
                containers[root] = copy.deepcopy(stored) if isinstance(stored, dict) else {}
            write_nested_setting(containers[root], remainder, value)

    for root, container in containers.items():
        container_normalizer = PATH_CONTAINER_NORMALIZERS.get(root)
        if container_normalizer:
            containers[root], container_warnings = container_normalizer(
                container, current_settings
            )
            if warnings is not None:
                warnings.update(container_warnings)

    normalized.update(containers)
    return normalized


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

        field_value, error, warning = _normalize_field_value(key, value, field)
        if error:
            errors[key] = error
            continue
        if field_value is SECRET_UNCHANGED:
            # The administrator never touched this credential. Dropping it keeps
            # the stored value intact and keeps the real secret out of the
            # response, which echoes back whatever lands in ``normalized``.
            continue
        if warning:
            warnings[key] = warning
        normalized[key] = field_value

    _check_acknowledgements(updates, current, errors)

    # "At least one" style constraints can only be judged once the whole payload
    # is known, because the capability toggle and its selection may arrive apart.
    _check_minimum_selections(normalized, current, errors)

    # Applied last so the checks above still see flat keys, which is the shape
    # they and the schema are written against.
    _apply_nested_paths(normalized, current, warnings)

    return normalized, errors, warnings


def _check_minimum_selections(normalized, current_settings, errors):
    """Enforce ``min_selected`` once the merged state of a save is known."""
    def read_value(key):
        return normalized[key] if key in normalized else current_settings.get(key)

    for _section_id, field in iter_fields():
        key = field.get("key")
        minimum = field.get("min_selected")
        if not key or not minimum:
            continue

        # A constraint on a hidden field would reject a save for a control the
        # administrator cannot even see.
        if not evaluate_dependency(field.get("depends_on"), read_value):
            continue

        selection = (
            normalized[key] if key in normalized else current_settings.get(key) or []
        )
        if len(selection) < minimum:
            errors[key] = f"Select at least {minimum} option."
