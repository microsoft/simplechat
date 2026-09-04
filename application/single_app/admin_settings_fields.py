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

Beyond a field's type, four optional descriptors shape how a section reads:

``group``
    Names the cluster a field belongs to, either as a label or with a variant
    from ``GROUP_VARIANTS``. The renderer opens the ``connection`` group first,
    because an administrator arriving at an unconfigured capability needs the
    endpoint before the tuning knobs. Without this, a section like Document
    Intelligence is a flat run of forty controls in which the credential that
    makes the rest work is simply the last one.

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

The Appearance, Agents & Actions, Chat, Knowledge, Workflow, Workspaces and
Security groups are described in full. Sections with no entry here fall back to the V2 surface's
``enable_*`` scan, so undescribed groups keep working exactly as they did. A
handful of individual fields outside those groups are also declared: that scan
places a key by guessing from shared word stems, and declaring a field is the
only way to stop it guessing wrong, and the only way a ``require_member_of_*``
setting appears in V2 at all. Workflow had the opposite problem -- none of its
settings are named ``enable_*``, so the scan had nothing to guess with and the
group rendered empty.

``SUPPRESSED_CAPABILITY_KEYS`` covers the remaining case -- a boolean the scan
would draw but which is not an editable setting at all.

Secrets are declared with the ``secret`` type. The browser is sent a placeholder
rather than the stored value, so the module reports which keys are secrets --
through ``get_secret_field_keys`` and ``get_secret_storage_paths`` -- and the
route swaps the placeholder back for what is stored, which is a persistence
concern belonging with the code holding the current settings document, and is
where the server-rendered form does it too.

The one exception is a secret declared with ``paths``. That value is folded into
its containing object by ``_apply_nested_paths`` before the route sees it, so it
never arrives as a settings key the route's key-based resolve can match. For
those, and only those, the normalizer drops a submitted placeholder rather than
letting it through to overwrite a stored credential.
"""

import copy
import json
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
from functions_content_safety import (
    CONTENT_SAFETY_VIOLATION_MESSAGE_MAX_LENGTH,
    normalize_content_safety_violation_message,
)
from functions_model_endpoint_identity_header import (
    DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_NAME,
    DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_VALUE_TYPE,
    normalize_model_endpoint_identity_header_name,
    normalize_model_endpoint_identity_header_value_type,
)
from functions_group_assignment_ids import (
    normalize_group_workflow_allowed_group_ids,
)
from functions_model_endpoint_identity_header import (
    DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_NAME,
    DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_VALUE_TYPE,
    normalize_model_endpoint_identity_header_name,
    normalize_model_endpoint_identity_header_value_type,
)
from functions_rate_limit import (
    RATE_LIMIT_MESSAGE_MAX_LENGTH,
    normalize_rate_limit_message,
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
    "string_list",
    "image",
    "link_list",
    "entry_list",
    "component",
    "id_list",
    "group_picker",
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

# ``input_type`` values a text field may ask the browser for. Anything else would
# reach the DOM unvalidated, so the schema test rejects it.
TEXT_INPUT_TYPES = ("text", "email", "url")


LANDING_PAGE_ALIGNMENTS = ("left", "center", "right")
USER_AGREEMENT_APPLY_TO_VALUES = ("personal", "group", "public", "chat")

# Mirrors AGENTS_PAGE_PROMOTED_POPULAR_ORDER_OPTIONS in functions_settings.py.
AGENTS_PAGE_PROMOTED_POPULAR_ORDERS = ("before", "after", "mixed")
AGENTS_PAGE_HERO_COLOR_MODES = ("single", "two_tone")

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
# Above this many automatic tool calls per workflow run, a run is capacity
# sensitive rather than merely long. The server-rendered pane says so in a
# warning block, so the same guidance is attached to the field here.
WORKFLOW_AUTO_INVOKE_CAPACITY_THRESHOLD = 100

CLASSIFICATION_BANNER_DEFAULT_COLOR = "#ffc107"
CLASSIFICATION_BANNER_DEFAULT_TEXT_COLOR = "#ffffff"

# The two ways SimpleChat authenticates to an Azure OpenAI resource on the classic
# single-endpoint routes. Shared by the embedding and image generation sections so the
# two cannot offer different values for the same question.
AZURE_OPENAI_AUTH_OPTIONS = [
    {"value": "key", "label": "Key"},
    {"value": "managed_identity", "label": "Managed Identity"},
]

# Mirrors PUBLIC_WORKSPACE_DISPLAY_NAME_MAX_LENGTH in functions_settings.py, which
# cannot be imported here: it reaches config.py and a live Cosmos client, and is one
# of the modules the functional tests stub out. test_v2_admin_workspaces_parity.py
# reads the value back out of that source and fails if the two drift apart.
PUBLIC_WORKSPACE_DISPLAY_NAME_MAX_LENGTH = 32

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

# Document action limits, mirrored from DOCUMENT_ACTION_LIMIT_BOUNDS and
# DEFAULT_DOCUMENT_ACTION_CAPABILITIES in functions_document_actions.py, which
# cannot be imported here for the same reason. Pinned by
# test_v2_admin_actions_parity.py rather than left to drift.
DOCUMENT_ACTION_CHAT_MIN_LIMIT = 2
DOCUMENT_ACTION_CHAT_MAX_LIMIT = 300
DOCUMENT_ACTION_CHAT_DEFAULT_LIMIT = 3
DOCUMENT_ACTION_WORKFLOW_MIN_LIMIT = 2
DOCUMENT_ACTION_WORKFLOW_MAX_LIMIT = 1000
DOCUMENT_ACTION_WORKFLOW_DEFAULT_LIMIT = 10

# Schemes permitted for administrator-configured navigation links. These render
# into an anchor href, so allowing arbitrary schemes would let a saved link
# carry javascript: into every page's navigation.
EXTERNAL_LINK_ALLOWED_SCHEMES = ("http", "https")

# Front Door terminates TLS and rewrites the host, so the value here becomes the
# base of every generated redirect. A scheme-less or pathful value would produce
# redirects that silently fail sign-in, which is why it is validated rather than
# stored as typed.
FRONT_DOOR_ALLOWED_SCHEMES = ("http", "https")

# Matches the server-rendered form: fewer than ten minutes of inactivity signs
# people out mid-thought, and the warning cannot arrive after the logout it warns
# about.
IDLE_TIMEOUT_MIN_MINUTES = 10
IDLE_TIMEOUT_MAX_MINUTES = 1440
IDLE_WARNING_MIN_MINUTES = 0

# Bounds enforced by ``normalize_key_vault_secret_reminder_config``. Declaring the
# same numbers here means an out-of-range value is refused at the point of entry
# with a message, instead of being quietly clamped on the next read.
KEY_VAULT_REMINDER_MIN_LEAD_DAYS = 1
KEY_VAULT_REMINDER_MAX_LEAD_DAYS = 3650
KEY_VAULT_REMINDER_MIN_SCAN_SECONDS = 900
KEY_VAULT_REMINDER_MAX_SCAN_SECONDS = 86400

# ``normalize_admin_role_list`` falls back to this when the list comes back empty,
# so an administrator who clears the field gets the same result either way.
KEY_VAULT_REMINDER_DEFAULT_ADMIN_ROLES = ["Admin"]

ACCESS_DENIED_MESSAGE_MAX_LENGTH = 2000


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
    "multi-endpoint-configuration": [
        {
            "key": "enable_multi_model_endpoints",
            "type": "switch",
            "label": "Use connections for chat",
            "help": (
                "Routes chat through the connections listed below, so several Azure "
                "OpenAI or Foundry resources can serve models at once. When off, chat "
                "uses the single classic endpoint instead and these connections are "
                "not consulted. Switching this on cannot be undone, and carries the "
                "classic endpoint over as the first connection."
            ),
            "default": False,
        },
        {
            "type": "component",
            "component": "model-connections-manager",
            "label": "Connections",
            "help": (
                "Each connection is one Azure OpenAI or Foundry resource: where it is, "
                "how SimpleChat authenticates to it, and which of its deployed models "
                "may be used."
            ),
        },
        {
            "key": "model_endpoint_identity_header_enabled",
            "type": "switch",
            "label": "Send an identity header with model requests",
            "help": (
                "Adds a header identifying the signed-in user to every model request. "
                "Gateways in front of a model endpoint use it to attribute usage or "
                "apply per-user quotas, which they otherwise cannot do because the "
                "request arrives under SimpleChat's own credentials."
            ),
            "default": False,
        },
        {
            "key": "model_endpoint_identity_header_name",
            "type": "text",
            "label": "Header name",
            "help": (
                "Rejected if it collides with a header the model call already sets, "
                "such as authorization or api-key."
            ),
            "default": DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_NAME,
            "max_length": 128,
            "fallback_when_empty": True,
            "depends_on": {"key": "model_endpoint_identity_header_enabled", "equals": True},
        },
        {
            "key": "model_endpoint_identity_header_value_type",
            "type": "select",
            "label": "Identity sent in the header",
            "help": (
                "Object id is stable when a user is renamed; UPN is readable in gateway "
                "logs. The tenant variants qualify the value for a multi-tenant gateway."
            ),
            "default": DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_VALUE_TYPE,
            "options": [
                {"value": "user_oid_tenant_id", "label": "Object id and tenant id"},
                {"value": "user_oid", "label": "Object id"},
                {"value": "user_upn_tenant_id", "label": "User principal name and tenant id"},
                {"value": "user_upn", "label": "User principal name"},
            ],
            "depends_on": {"key": "model_endpoint_identity_header_enabled", "equals": True},
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
            "default": "",
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
            "default": "",
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
            "default": "",
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
                "Narrows fetching a URL in chat, and enabling it for a workflow, to "
                "holders of the UrlAccessUser app role. Assign the role in the "
                "Enterprise App before turning this on, or nobody will be able to use "
                "URL Access."
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
                "Narrows Deep Research to holders of the DeepResearchUser app role. "
                "Worth using where the multi-step runs it performs are expensive enough "
                "to want a named audience. Assign the role in the Enterprise App before "
                "turning this on, or nobody will be able to use Deep Research."
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
            "default": "",
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
            "default": "",
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
            "default": "",
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
    # ------------------------------------------------------------------
    # Knowledge / Audio & Video
    #
    # Restructured relative to the server-rendered pane in two ways.
    #
    # The completion chime is gone from here. `enable_chat_completion_audio_cues`
    # plays a bundled local sound when a response finishes; its own help text
    # says it does not use Azure Speech Service, yet it is the first control in
    # the AI Voice Conversations card, above the Speech resource configuration.
    # It is declared under Chat > Feedback & Alerts instead, which is where the
    # rest of the notification settings live. Declaring a key removes it from the
    # V2 fallback scan, so it cannot appear in both places.
    #
    # The shared Speech resource is stated before the toggles rather than after.
    # Three independent capabilities reveal the same configuration block, and V1
    # explains that in an alert placed underneath them, so an administrator
    # enabling the second one is surprised to find it already configured.
    # ------------------------------------------------------------------
    "ai-voice-chat-section": [
        {
            "key": "speech_service_endpoint",
            "type": "text",
            "label": "Speech Endpoint",
            "help": (
                "One Speech resource serves all three voice capabilities below. Use the "
                "resource-specific custom domain endpoint when authenticating with a "
                "managed identity."
            ),
            "default": "",
            "required": True,
            "placeholder": "https://<location>.cognitiveservices.azure.com/",
            "group": {
                "id": "speech",
                "label": "Speech resource",
                "variant": "connection",
                "help": (
                    "Configure this once. Audio file uploads, voice input and voice "
                    "responses all use it."
                ),
            },
            "depends_on": {
                "any_of": [
                    {"key": "enable_audio_file_support", "equals": True},
                    {"key": "enable_speech_to_text_input", "equals": True},
                    {"key": "enable_text_to_speech", "equals": True},
                ]
            },
        },
        {
            "key": "speech_service_location",
            "type": "text",
            "label": "Location",
            "help": (
                "Needed for recognition locale defaults, and for text-to-speech when "
                "using a managed identity."
            ),
            "default": "",
            "required": True,
            "placeholder": "eastus",
            "group": {"id": "speech", "label": "Speech resource", "variant": "connection"},
            "depends_on": {
                "any_of": [
                    {"key": "enable_audio_file_support", "equals": True},
                    {"key": "enable_speech_to_text_input", "equals": True},
                    {"key": "enable_text_to_speech", "equals": True},
                ]
            },
        },
        {
            "key": "speech_service_authentication_type",
            "type": "select",
            "label": "Authentication Type",
            "default": "key",
            "options": [
                {"value": "key", "label": "Key"},
                {"value": "managed_identity", "label": "Managed Identity"},
            ],
            "group": {"id": "speech", "label": "Speech resource", "variant": "connection"},
            "depends_on": {
                "any_of": [
                    {"key": "enable_audio_file_support", "equals": True},
                    {"key": "enable_speech_to_text_input", "equals": True},
                    {"key": "enable_text_to_speech", "equals": True},
                ]
            },
        },
        {
            "key": "speech_service_key",
            "type": "secret",
            "default": "",
            "label": "API Key",
            "required": True,
            "group": {"id": "speech", "label": "Speech resource", "variant": "connection"},
            "depends_on": {
                "all_of": [
                    {"key": "speech_service_authentication_type", "equals": "key"},
                    {
                        "any_of": [
                            {"key": "enable_audio_file_support", "equals": True},
                            {"key": "enable_speech_to_text_input", "equals": True},
                            {"key": "enable_text_to_speech", "equals": True},
                        ]
                    },
                ]
            },
        },
        {
            "key": "speech_service_subscription_id",
            "type": "text",
            "label": "Subscription ID",
            "default": "",
            "placeholder": "12345678-1234-1234-1234-123456789abc",
            "group": {"id": "speech", "label": "Speech resource", "variant": "connection"},
            "depends_on": {
                "all_of": [
                    {
                        "key": "speech_service_authentication_type",
                        "equals": "managed_identity",
                    },
                    {
                        "any_of": [
                            {"key": "enable_audio_file_support", "equals": True},
                            {"key": "enable_speech_to_text_input", "equals": True},
                            {"key": "enable_text_to_speech", "equals": True},
                        ]
                    },
                ]
            },
        },
        {
            "key": "speech_service_resource_group",
            "type": "text",
            "label": "Resource Group",
            "default": "",
            "placeholder": "rg-speech-prod",
            "group": {"id": "speech", "label": "Speech resource", "variant": "connection"},
            "depends_on": {
                "all_of": [
                    {
                        "key": "speech_service_authentication_type",
                        "equals": "managed_identity",
                    },
                    {
                        "any_of": [
                            {"key": "enable_audio_file_support", "equals": True},
                            {"key": "enable_speech_to_text_input", "equals": True},
                            {"key": "enable_text_to_speech", "equals": True},
                        ]
                    },
                ]
            },
        },
        {
            "key": "speech_service_resource_name",
            "type": "text",
            "label": "Resource Name",
            "help": (
                "With a custom-domain Speech endpoint this is usually the first part of "
                "that hostname."
            ),
            "default": "",
            "placeholder": "my-speech-resource",
            "group": {"id": "speech", "label": "Speech resource", "variant": "connection"},
            "depends_on": {
                "all_of": [
                    {
                        "key": "speech_service_authentication_type",
                        "equals": "managed_identity",
                    },
                    {
                        "any_of": [
                            {"key": "enable_audio_file_support", "equals": True},
                            {"key": "enable_speech_to_text_input", "equals": True},
                            {"key": "enable_text_to_speech", "equals": True},
                        ]
                    },
                ]
            },
        },
        {
            "key": "speech_service_resource_id",
            "type": "component",
            "component": "resource-id-builder",
            "label": "Speech Resource ID",
            "help": (
                "Required for voice responses under a managed identity. Build it from "
                "the fields above or paste it in full."
            ),
            "required": True,
            "placeholder": (
                "/subscriptions/<subscription>/resourceGroups/<resource-group>"
                "/providers/Microsoft.CognitiveServices/accounts/<speech-resource>"
            ),
            "builder_template": (
                "/subscriptions/{subscription}/resourceGroups/{resource_group}"
                "/providers/Microsoft.CognitiveServices/accounts/{resource_name}"
            ),
            "builder_sources": {
                "subscription": "speech_service_subscription_id",
                "resource_group": "speech_service_resource_group",
                "resource_name": "speech_service_resource_name",
            },
            "group": {"id": "speech", "label": "Speech resource", "variant": "connection"},
            "depends_on": {
                "all_of": [
                    {
                        "key": "speech_service_authentication_type",
                        "equals": "managed_identity",
                    },
                    {
                        "any_of": [
                            {"key": "enable_audio_file_support", "equals": True},
                            {"key": "enable_speech_to_text_input", "equals": True},
                            {"key": "enable_text_to_speech", "equals": True},
                        ]
                    },
                ]
            },
        },
        {
            "key": "speech_service_locale",
            "type": "text",
            "label": "Locale",
            "help": "Default recognition locale, for example en-US.",
            "default": "en-US",
            "fallback_when_empty": True,
            "group": {"id": "speech", "label": "Speech resource", "variant": "connection"},
            "depends_on": {
                "any_of": [
                    {"key": "enable_audio_file_support", "equals": True},
                    {"key": "enable_speech_to_text_input", "equals": True},
                    {"key": "enable_text_to_speech", "equals": True},
                ]
            },
        },
        {
            "key": "enable_audio_file_support",
            "type": "switch",
            "label": "Audio file upload and transcription",
            "help": (
                "Uploaded audio is transcribed and indexed, so recordings of meetings, "
                "interviews and lectures become searchable and citable."
            ),
            "default": False,
            "group": {"id": "capabilities", "label": "Capabilities", "variant": "behavior"},
        },
        {
            "key": "enable_speech_to_text_input",
            "type": "switch",
            "label": "Voice input (speech-to-text)",
            "help": "Users can record up to 90 seconds in the chat box instead of typing.",
            "default": False,
            "group": {"id": "capabilities", "label": "Capabilities", "variant": "behavior"},
        },
        {
            "key": "enable_text_to_speech",
            "type": "switch",
            "label": "Voice responses (text-to-speech)",
            "help": "Each message gains a speaker button that reads the response aloud.",
            "default": False,
            "group": {"id": "capabilities", "label": "Capabilities", "variant": "behavior"},
        },
        {
            # V1 prints this under the toggles as loose markup. Declaring it keeps
            # the reason a format is unsupported next to the capability that
            # would otherwise silently skip the file.
            "type": "status",
            "label": "Audio runtime",
            "status_source": "audio_runtime",
            "help": (
                "Transcoding breadth depends on whether FFmpeg is present in this "
                "deployment. Without it, only formats that transcribe directly are "
                "accepted."
            ),
            "group": {"id": "capabilities", "label": "Capabilities", "variant": "behavior"},
            "depends_on": {"key": "enable_audio_file_support", "equals": True},
        },
    ],
    "video-intelligence-section": [
        {
            "key": "enable_video_file_support",
            "type": "switch",
            "label": "Video file upload and processing",
            "help": (
                "Uploaded video is processed by Azure Video Indexer, which extracts "
                "spoken content, speakers, faces and brands into searchable metadata."
            ),
            "default": False,
            "role": "capability",
        },
        {
            "key": "video_indexer_endpoint",
            "type": "text",
            "label": "API Endpoint",
            "help": (
                "https://api.videoindexer.ai for Azure Public, or "
                "https://api.videoindexer.ai.azure.us for Azure Government. Use another "
                "value only for a non-standard deployment."
            ),
            "default": "",
            "required": True,
            "placeholder": "https://api.videoindexer.ai",
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
        },
        {
            "key": "video_indexer_subscription_id",
            "type": "text",
            "label": "Subscription ID",
            "default": "",
            "required": True,
            "placeholder": "12345678-1234-1234-1234-123456789abc",
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
        },
        {
            "key": "video_indexer_resource_group",
            "type": "text",
            "label": "Resource Group",
            "help": "The resource group containing the Video Indexer account.",
            "default": "",
            "required": True,
            "placeholder": "rg-videoindexer-prod",
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
        },
        {
            "key": "video_indexer_account_name",
            "type": "text",
            "label": "Account Name",
            "default": "",
            "required": True,
            "placeholder": "my-video-indexer",
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
        },
        {
            "key": "video_indexer_account_id",
            "type": "text",
            "label": "Account ID",
            "help": "Shown on the Video Indexer account overview page in the Azure portal.",
            "default": "",
            "required": True,
            "placeholder": "12345678-abcd-1234-abcd-123456789abc",
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
        },
        {
            "key": "video_indexer_location",
            "type": "text",
            "label": "Location",
            "help": "The Azure region the account is deployed in, for example eastus.",
            "default": "",
            "required": True,
            "placeholder": "eastus",
            "group": {"id": "connection", "label": "Connection", "variant": "connection"},
        },
        {
            "key": "video_indexer_arm_api_version",
            "type": "text",
            "label": "ARM API Version",
            "default": "",
            "fallback_when_empty": True,
            "group": {"id": "advanced", "label": "Advanced", "variant": "advanced"},
        },
        {
            "key": "video_index_timeout",
            "type": "number",
            "label": "Indexing Timeout",
            "help": "How long to wait for Video Indexer to finish processing one file.",
            "default": 600,
            "min": 30,
            "max": 7200,
            "suffix": "s",
            "group": {"id": "advanced", "label": "Advanced", "variant": "advanced"},
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
        {
            "key": "enable_chat_completion_audio_cues",
            "type": "switch",
            "label": "AI response completion sounds",
            "help": (
                "Lets users opt in to a short bundled sound when a response finishes "
                "while they are looking elsewhere. Played locally by the browser; no "
                "Azure Speech resource is involved."
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
    # ------------------------------------------------------------------
    # Knowledge / File Sync
    #
    # File Sync needs Redis Cache, which lives under Scale, and the
    # server-rendered card says so with data-requires attributes that
    # admin_settings_dependencies.js reads. That is the first real use of the
    # `requires` descriptor: without it an administrator turns File Sync on and
    # nothing happens, with no visible reason until a flash message after saving.
    #
    # The three scope sections share one shape -- enable, access, assignment --
    # so learning Personal is enough to read Group and Public.
    # ------------------------------------------------------------------
    "file-sync-section": [
        {
            "key": "enable_file_sync",
            "type": "switch",
            "label": "Enable File Sync",
            "help": (
                "Lets workspaces pull documents from a configured source on a schedule "
                "instead of relying on manual upload."
            ),
            "default": False,
            "role": "capability",
            "requires": {
                "key": "enable_redis_cache",
                "label": "Redis Cache",
                "mode": "warn",
                "target_section": "redis-cache-section",
                "description": (
                    "File Sync settings can be saved now, but sync runs stay inactive "
                    "until Redis Cache is enabled and configured."
                ),
            },
        },
        {
            "key": "file_sync_max_sources_per_scope",
            "type": "number",
            "label": "Max Sources per Workspace",
            "default": 10,
            "min": 1,
            "max": 100,
            "group": {"id": "limits", "label": "Run limits", "variant": "limits"},
            "depends_on": {"key": "enable_file_sync", "equals": True},
        },
        {
            "key": "file_sync_min_schedule_interval_minutes",
            "type": "number",
            "label": "Minimum Schedule Interval",
            "help": "The shortest gap a workspace may schedule between runs.",
            "default": 15,
            "min": 5,
            "max": 1440,
            "suffix": " min",
            "group": {"id": "limits", "label": "Run limits", "variant": "limits"},
            "depends_on": {"key": "enable_file_sync", "equals": True},
        },
        {
            "key": "file_sync_max_files_per_run",
            "type": "number",
            "label": "Max Files per Run",
            "default": 1000,
            "min": 1,
            "max": 100000,
            "group": {"id": "limits", "label": "Run limits", "variant": "limits"},
            "depends_on": {"key": "enable_file_sync", "equals": True},
        },
        {
            "key": "file_sync_max_gb_per_run",
            "type": "number",
            "label": "Max Size per Run",
            "help": "Entered in gigabytes; stored in bytes.",
            "default": 5,
            "min": 1,
            "max": 1024,
            "suffix": " GB",
            # 1 GiB, matching the conversion the server-rendered form applies.
            "scale": 1073741824,
            "paths": ["file_sync_max_bytes_per_run"],
            "group": {"id": "limits", "label": "Run limits", "variant": "limits"},
            "depends_on": {"key": "enable_file_sync", "equals": True},
        },
        {
            "key": "file_sync_max_concurrent_runs",
            "type": "number",
            "label": "Max Concurrent Runs",
            "help": "How many workspaces may sync at once across the whole deployment.",
            "default": 2,
            "min": 1,
            "max": 25,
            "group": {"id": "limits", "label": "Run limits", "variant": "limits"},
            "depends_on": {"key": "enable_file_sync", "equals": True},
        },
        {
            "key": "file_sync_allow_recursive_sources",
            "type": "switch",
            "label": "Allow recursive sources",
            "help": "Lets a source include subfolders rather than only its top level.",
            "default": True,
            "group": {"id": "limits", "label": "Run limits", "variant": "limits"},
            "depends_on": {"key": "enable_file_sync", "equals": True},
        },
    ],
    "file-sync-source-types-section": [
        {
            "key": "file_sync_visible_source_types",
            "type": "checkbox_set",
            "label": "Source types offered when adding a source",
            "help": (
                "Credentials for a source are held in Key Vault when Key Vault secret "
                "storage is enabled, and in the encrypted settings path otherwise."
            ),
            "default": ["smb", "azure_files"],
            "min_selected": 1,
            "options": [
                {"value": "smb", "label": "SMB Share", "description": "Available now."},
                {
                    "value": "azure_files",
                    "label": "Azure Files",
                    "description": "Available now.",
                },
                {
                    "value": "azure_blob",
                    "label": "Azure Blob Storage",
                    "description": "Available now.",
                },
                {
                    "value": "onedrive",
                    "label": "OneDrive",
                    "description": "Coming soon.",
                    "disabled": True,
                },
                {
                    "value": "sharepoint_on_prem",
                    "label": "On-prem SharePoint",
                    "description": "Coming soon.",
                    "disabled": True,
                },
                {
                    "value": "google_workspace",
                    "label": "Google Workspace",
                    "description": "Coming soon.",
                    "disabled": True,
                },
            ],
            "depends_on": {"key": "enable_file_sync", "equals": True},
        },
    ],
    "file-sync-personal-section": [
        {
            "key": "enable_file_sync_personal",
            "type": "switch",
            "label": "Enable sync for personal workspaces",
            "default": True,
            "role": "capability",
        },
        {
            "key": "file_sync_personal_admin_only",
            "type": "switch",
            "label": "Only administrators manage sources",
            "help": "Users keep their synced documents but cannot add or edit a source.",
            "default": False,
            "group": {"id": "access", "label": "Access", "variant": "access"},
            "depends_on": {"key": "enable_file_sync_personal", "equals": True},
        },
        {
            "key": "file_sync_personal_require_app_role",
            "type": "switch",
            "label": "Require the PersonalFileSyncUser app role",
            "help": (
                "Required app role value: PersonalFileSyncUser. Assign it in the "
                "Enterprise App before turning this on, or no user will be able to "
                "manage a personal source."
            ),
            "default": False,
            "group": {"id": "access", "label": "Access", "variant": "access"},
            "depends_on": {"key": "enable_file_sync_personal", "equals": True},
        },
    ],
    "file-sync-group-section": [
        {
            "key": "enable_file_sync_group",
            "type": "switch",
            "label": "Enable sync for group workspaces",
            "default": True,
            "role": "capability",
        },
        {
            "key": "file_sync_group_admin_only",
            "type": "switch",
            "label": "Only administrators manage sources",
            "default": False,
            "group": {"id": "access", "label": "Access", "variant": "access"},
            "depends_on": {"key": "enable_file_sync_group", "equals": True},
        },
        {
            "key": "require_group_assignment_for_file_sync",
            "type": "switch",
            "label": "Restrict to assigned groups",
            "help": "Only the groups listed below may use File Sync.",
            "default": False,
            "group": {"id": "access", "label": "Access", "variant": "access"},
            "depends_on": {"key": "enable_file_sync_group", "equals": True},
        },
        {
            "key": "file_sync_allowed_group_ids",
            "type": "id_list",
            "label": "Assigned groups",
            "help": (
                "Leaving this empty while the restriction is on means no group can use "
                "File Sync."
            ),
            "default": [],
            "placeholder": "Search groups by name",
            "search_endpoint": "/api/admin/file-sync/groups/search",
            "search_param": "q",
            "results_key": "groups",
            "item_noun": "group",
            "item_noun_plural": "groups",
            # Group ids are canonical UUIDs, and the shared normalizer drops
            # anything else, matching what the server-rendered form stores.
            "id_kind": "group",
            "group": {"id": "assignment", "label": "Assignment", "variant": "access"},
            "depends_on": {
                "all_of": [
                    {"key": "enable_file_sync_group", "equals": True},
                    {"key": "require_group_assignment_for_file_sync", "equals": True},
                ]
            },
        },
    ],
    "file-sync-public-section": [
        {
            "key": "enable_file_sync_public",
            "type": "switch",
            "label": "Enable sync for public workspaces",
            "default": False,
            "role": "capability",
        },
        {
            "key": "file_sync_public_admin_only",
            "type": "switch",
            "label": "Only administrators manage sources",
            "default": False,
            "group": {"id": "access", "label": "Access", "variant": "access"},
            "depends_on": {"key": "enable_file_sync_public", "equals": True},
        },
        {
            "key": "require_public_workspace_assignment_for_file_sync",
            "type": "switch",
            "label": "Restrict to assigned public workspaces",
            "help": "Only the public workspaces listed below may use File Sync.",
            "default": False,
            "group": {"id": "access", "label": "Access", "variant": "access"},
            "depends_on": {"key": "enable_file_sync_public", "equals": True},
        },
        {
            "key": "file_sync_allowed_public_workspace_ids",
            "type": "id_list",
            "label": "Assigned public workspaces",
            "help": (
                "Leaving this empty while the restriction is on means no public "
                "workspace can use File Sync."
            ),
            "default": [],
            "placeholder": "Search public workspaces by name",
            "search_endpoint": "/api/admin/file-sync/public-workspaces/search",
            "search_param": "q",
            "results_key": "workspaces",
            "item_noun": "public workspace",
            "item_noun_plural": "public workspaces",
            # Public workspace ids are not UUID-constrained, so they are only
            # trimmed and deduplicated.
            "id_kind": "opaque",
            "group": {"id": "assignment", "label": "Assignment", "variant": "access"},
            "depends_on": {
                "all_of": [
                    {"key": "enable_file_sync_public", "equals": True},
                    {
                        "key": "require_public_workspace_assignment_for_file_sync",
                        "equals": True,
                    },
                ]
            },
        },
    ],
    "permissions-section": [
        {
            "key": "require_member_of_safety_violation_admin",
            "type": "switch",
            "label": "Require SafetyViolationAdmin App Role",
            "help": (
                "Narrows the Safety Violations report to holders of the "
                "SafetyViolationAdmin app role. Left off, anyone with the general "
                "Admin role can read it, including the flagged message text."
            ),
            "default": False,
        },
        {
            "key": "require_member_of_feedback_admin",
            "type": "switch",
            "label": "Require FeedbackAdmin App Role",
            "help": (
                "Narrows the User Feedback report to holders of the FeedbackAdmin app "
                "role. It only governs that report, so it has no effect until User "
                "Feedback is enabled under Chat."
            ),
            "default": False,
        },
    ],
    "app-role-requirements-section": [
        {
            "type": "component",
            "component": "app-role-requirements-roster",
            "label": "App Role Requirements",
            "help": (
                "Every setting that can demand an Entra app role, gathered so the "
                "whole access policy reads in one place. Each switch is the same value "
                "as the one on its own tab, so changing it here changes it there."
            ),
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
    # `chat-file-uploads-section` is declared in full in the Chat group above,
    # including this role requirement gated on the capability itself. A second
    # declaration here would override that one and silently drop
    # `enable_chat_file_uploads`, because a later key wins in a dict literal.
    "control-center-overview-section": [
        {
            "key": "require_member_of_control_center_admin",
            "type": "switch",
            "label": "Require ControlCenterAdmin App Role",
            "help": (
                "Narrows the Control Center -- user management, group oversight, "
                "public workspace control and activity logs -- to holders of the "
                "ControlCenterAdmin app role. Note that this takes it away from "
                "general Admins, so assign the role before switching it on."
            ),
            "default": False,
        },
        {
            "key": "require_member_of_control_center_dashboard_reader",
            "type": "switch",
            "label": "Allow ControlCenterDashboardReader App Role",
            "help": (
                "Grants the Control Center dashboard, and nothing else, to holders of "
                "the ControlCenterDashboardReader app role. Useful for giving someone "
                "the usage picture without any management ability."
            ),
            "default": False,
        },
    ],
    "group-workspaces-section": [
        {
            "key": "enable_group_workspaces",
            "type": "switch",
            "label": "Enable Group Workspaces",
            "help": (
                "Lets users form groups that share one document library, prompt set "
                "and agent catalogue, with membership managed per group. This is the "
                "gate for everything else in this section."
            ),
            "default": True,
        },
        {
            # V1 renders this inverted, as a "Disable Group Creation" checkbox, while
            # the stored key is enable_group_creation. Declaring it positively means
            # the switch and the value it writes finally agree, which is what makes
            # the interaction with the role requirement below readable.
            "key": "enable_group_creation",
            "type": "switch",
            "label": "Allow Users to Create Groups",
            "help": (
                "When off, nobody can create a new group regardless of app role, and "
                "existing groups keep working. Use this to freeze the group list "
                "while a migration or review is under way. Off here overrides the "
                "CreateGroups role requirement entirely."
            ),
            "default": True,
            "depends_on": {"key": "enable_group_workspaces", "equals": True},
        },
        {
            "key": "require_member_of_create_group",
            "type": "switch",
            "label": "Require CreateGroups App Role",
            "help": (
                "Narrows group creation to users holding the CreateGroups app role. "
                "Assign the role in the Enterprise App before switching this on, or "
                "nobody will be able to create a group. Left off, any signed-in user "
                "can create groups while the two settings above allow it."
            ),
            "default": False,
            "depends_on": {"key": "enable_group_workspaces", "equals": True},
        },
        {
            "key": "require_owner_for_group_agent_management",
            "type": "switch",
            "label": "Require Owner to Manage Group Agents, Actions and Workflows",
            "help": (
                "Restricts creating, editing and deleting a group's agents, actions "
                "and workflows to the group Owner. Group Admins keep read access, so "
                "they can still see what is configured without being able to change "
                "what the group's agents are allowed to do."
            ),
            "default": False,
            "depends_on": {"key": "enable_group_workspaces", "equals": True},
        },
    ],
    "public-workspaces-section": [
        {
            "key": "enable_public_workspaces",
            "type": "switch",
            "label": "Enable Public Workspaces",
            "help": (
                "Adds a workspace type any user in the organisation can read without "
                "being a member, for reference material meant to reach everyone. "
                "Membership still controls who can add or change documents."
            ),
            "default": False,
        },
        {
            "key": "public_workspace_display_name",
            "type": "text",
            "label": "End-user display name",
            "help": (
                "Renames the workspace type wherever end users meet it, so it can "
                "match what your organisation already calls this material -- "
                "\"Knowledge Base\" or \"Library\", for example. Admin settings and "
                "internal references keep saying Public Workspace. Leave empty to use "
                "the default name."
            ),
            "placeholder": "Public Workspace",
            "default": "",
            "max_length": PUBLIC_WORKSPACE_DISPLAY_NAME_MAX_LENGTH,
            "depends_on": {"key": "enable_public_workspaces", "equals": True},
        },
        {
            "key": "require_member_of_create_public_workspace",
            "type": "switch",
            "label": "Require CreatePublicWorkspaces App Role",
            "help": (
                "Narrows public workspace creation to users holding the "
                "CreatePublicWorkspaces app role. Because anything published here is "
                "readable organisation-wide, this is usually the setting to reach for "
                "before enabling the workspace type broadly."
            ),
            "default": False,
            "depends_on": {"key": "enable_public_workspaces", "equals": True},
        },
    ],
    "workspace-identities-section": [
        {
            "type": "component",
            "component": "global-identities-list",
            "label": "Global Identities",
            "help": (
                "Credentials saved once and reused by File Sync sources and Actions, "
                "referenced by name so the secret itself never travels with a "
                "configuration. Each one stores its secret in Key Vault when Key Vault "
                "is configured."
            ),
        },
    ],
    "file-download-settings-section": [
        {
            "key": "allow_personal_workspace_file_downloads",
            "type": "switch",
            "label": "Enable Personal Workspace Downloads",
            "help": (
                "Lets users retrieve the original uploaded file from their own "
                "workspace, rather than only the extracted text the model reads. Off "
                "by default because it turns the workspace into a way to move a file "
                "back out of the tenant."
            ),
            "default": False,
        },
        {
            "key": "allow_group_workspace_file_downloads",
            "type": "switch",
            "label": "Enable Group Workspace Downloads",
            "help": (
                "Permits downloads from group workspaces. A group Owner or Admin can "
                "still switch downloads off for their own group, so this sets the "
                "ceiling rather than the outcome."
            ),
            "default": False,
        },
        {
            "key": "require_group_assignment_for_file_downloads",
            "type": "switch",
            "label": "Require Group Assignment for Downloads",
            "help": (
                "Limits downloads to the groups named below instead of every group. "
                "Use this to pilot downloads with a few teams before opening them up."
            ),
            "default": False,
            "depends_on": {"key": "allow_group_workspace_file_downloads", "equals": True},
        },
        {
            "key": "file_download_allowed_group_ids",
            "type": "id_list",
            "label": "Groups allowed to download",
            "help": (
                "Only these groups can offer downloads while the requirement above is "
                "on. A group left out of this list behaves as though downloads were "
                "never enabled."
            ),
            "default": [],
            "id_kind": "group",
            "search_endpoint": "/api/groups/discover",
            "search_param": "search",
            "search_extra": {"showAll": "true"},
            "results_key": "groups",
            "item_noun": "group",
            "item_noun_plural": "groups",
            "depends_on": [
                {"key": "allow_group_workspace_file_downloads", "equals": True},
                {"key": "require_group_assignment_for_file_downloads", "equals": True},
            ],
        },
        {
            "key": "allow_public_workspace_file_downloads",
            "type": "switch",
            "label": "Enable Public Workspace Downloads",
            "help": (
                "Permits downloads from public workspaces. Because these are readable "
                "organisation-wide, this makes every original file in them retrievable "
                "by anyone who can see the workspace."
            ),
            "default": False,
        },
        {
            "key": "require_public_workspace_assignment_for_file_downloads",
            "type": "switch",
            "label": "Require Public Workspace Assignment for Downloads",
            "help": (
                "Limits downloads to the public workspaces named below instead of all "
                "of them."
            ),
            "default": False,
            "depends_on": {
                "key": "allow_public_workspace_file_downloads",
                "equals": True,
            },
        },
        {
            "key": "file_download_allowed_public_workspace_ids",
            "type": "id_list",
            "label": "Public workspaces allowed to download",
            "help": (
                "Only these public workspaces can offer downloads while the "
                "requirement above is on."
            ),
            "default": [],
            "id_kind": "opaque",
            "search_endpoint": "/api/admin/file-sync/public-workspaces/search",
            "search_param": "q",
            "results_key": "workspaces",
            "item_noun": "public workspace",
            "item_noun_plural": "public workspaces",
            "depends_on": [
                {"key": "allow_public_workspace_file_downloads", "equals": True},
                {
                    "key": "require_public_workspace_assignment_for_file_downloads",
                    "equals": True,
                },
            ],
        },
    ],
    "file-sharing-section": [
        {
            "key": "enable_file_sharing",
            "type": "switch",
            "label": "Enable File Sharing",
            "help": (
                "Lets a user hand a workspace file to another user or workspace from "
                "inside the application, instead of downloading it and sending it on."
            ),
            "default": False,
        },
    ],
    "file-size-limit-section": [
        {
            "key": "max_file_size_mb",
            "type": "number",
            "label": "Maximum File Size (MB)",
            "help": (
                "Rejects an upload larger than this before any extraction runs. It "
                "applies to workspace documents and to files attached to a chat "
                "message, so lowering it narrows both paths at once. Raise it only as "
                "far as your extraction and storage tiers can actually handle."
            ),
            "default": 150,
            "min": 1,
            "suffix": " MB",
        },
    ],
    "shared-conversation-file-approvals-section": [
        {
            "key": "require_shared_conversation_file_approval",
            "type": "switch",
            "label": "Require approval for participant-generated files",
            "help": (
                "Files a participant generates in someone else's shared conversation "
                "are saved into the owner's storage. With this on they are withheld "
                "until the owner approves them -- in a group conversation any Owner, "
                "Admin or Document Manager can. Anything left unapproved is declined "
                "and deleted after three days. Covers CSV, XLSX, DOCX, PDF, JSON and "
                "XML; generated images and charts are never held."
            ),
            "default": True,
        },
    ],
    # The Orchestration group had the same problem the Workflow group had, from the
    # other direction: exactly one of its settings is named `enable_*`, so the fallback
    # scan found that switch and nothing else. The group rendered as a single toggle
    # while the classic page carried the approval mode, every limit, the capability
    # list and the planner model -- which meant the one interface an administrator is
    # steered towards was the one that could not configure the feature.
    "chat-orchestration-section": [
        {
            "key": "enable_chat_orchestration",
            "type": "switch",
            "label": "Enable Chat Orchestration",
            "help": (
                "Lets a user describe what they want and have SimpleChat work out the "
                "rest. Instead of choosing documents, web search, a prompt, an agent and "
                "a model before asking, the user asks; SimpleChat plans the work, shows "
                "the plan, and runs it once approved. Orchestration reaches only "
                "capabilities this deployment already allows, so turning it on grants no "
                "new access. Available in the V2 interface."
            ),
            "default": False,
            "role": "capability",
        },
    ],
    "chat-orchestration-approval-section": [
        {
            "key": "chat_orchestration_default_approval_mode",
            "type": "select",
            "label": "Default Approval Mode",
            "help": (
                "How much say a user has before a plan runs. Reviewing every plan is the "
                "safest default and the slowest; running automatically is the fastest and "
                "gives the user no chance to intervene before work starts. The countdown "
                "sits between the two: the plan appears with a timer, and doing nothing "
                "runs it."
            ),
            "default": "manual",
            "options": [
                {"value": "manual", "label": "Review before running"},
                {"value": "timed", "label": "Run automatically after a countdown"},
                {"value": "auto", "label": "Run automatically"},
            ],
            "depends_on": {"key": "enable_chat_orchestration", "equals": True},
            "group": {"id": "behavior", "label": "Approval", "variant": "behavior"},
        },
        {
            "key": "chat_orchestration_timed_approval_seconds",
            "type": "number",
            "label": "Countdown Before Running",
            "help": (
                "Seconds the user has to intervene when the mode is a countdown. "
                "Supported range is 3 to 120."
            ),
            "default": 10,
            "min": 3,
            "max": 120,
            # Both conditions, not just the mode. Visibility is evaluated per field rather
            # than recursively, so gating this only on the mode would leave it on screen
            # whenever the mode field itself was hidden by orchestration being off.
            "depends_on": [
                {"key": "enable_chat_orchestration", "equals": True},
                {"key": "chat_orchestration_default_approval_mode", "equals": "timed"},
            ],
            "group": {"id": "behavior", "label": "Approval", "variant": "behavior"},
        },
        {
            "key": "chat_orchestration_allow_user_approval_override",
            "type": "switch",
            "label": "Let Users Change Their Own Approval Mode",
            "help": (
                "When off, every user stays on the default above and the control is "
                "hidden from the composer."
            ),
            "default": True,
            "depends_on": {"key": "enable_chat_orchestration", "equals": True},
            "group": {"id": "behavior", "label": "Approval", "variant": "behavior"},
        },
        {
            "key": "chat_orchestration_show_manual_controls",
            "type": "switch",
            "label": "Keep The Manual Composer Controls Available",
            "help": (
                "Keeps the document, web, model and agent pickers reachable behind a "
                "disclosure while orchestration is on. Anything chosen there constrains "
                "the plan rather than being ignored, so a power user can pin the work to "
                "a particular document and let orchestration decide the rest."
            ),
            "default": True,
            "depends_on": {"key": "enable_chat_orchestration", "equals": True},
            "group": {"id": "behavior", "label": "Approval", "variant": "behavior"},
        },
    ],
    "chat-orchestration-capabilities-section": [
        {
            "key": "chat_orchestration_enabled_capabilities",
            "type": "checkbox_set",
            "label": "Capabilities",
            "help": (
                "Which kinds of work a plan may contain. Leaving every box ticked is the "
                "normal state and means whatever the rest of this deployment already "
                "permits; clearing one keeps it out of plans even where it remains "
                "available to users working by hand. Answering is always available "
                "because a plan has to end somewhere."
            ),
            "default": [],
            "options": [
                {"value": "document_search", "label": "Search documents"},
                {"value": "document_analyze", "label": "Analyse documents"},
                {"value": "document_compare", "label": "Compare documents"},
                {"value": "tabular_analyze", "label": "Analyse spreadsheets"},
                {"value": "web_search", "label": "Search the web"},
                {"value": "url_fetch", "label": "Read linked pages"},
                {"value": "deep_research", "label": "Research in depth"},
                {"value": "agent_invoke", "label": "Ask an agent"},
            ],
            "depends_on": {"key": "enable_chat_orchestration", "equals": True},
        },
    ],
    "chat-orchestration-limits-section": [
        {
            "key": "chat_orchestration_max_steps",
            "type": "number",
            "label": "Maximum Steps In A Plan",
            "help": (
                "Caps how much work one plan may describe. Enforced regardless of what a "
                "plan asks for, so a vaguely worded request cannot become an open-ended "
                "amount of work. Supported range is 1 to 30."
            ),
            "default": 8,
            "min": 1,
            "max": 30,
            "depends_on": {"key": "enable_chat_orchestration", "equals": True},
            "group": {"id": "limits", "label": "Limits", "variant": "limits"},
        },
        {
            "key": "chat_orchestration_max_replans",
            "type": "number",
            "label": "Maximum Re-plans Per Run",
            "help": (
                "How often a step may send the plan back to be reconsidered after "
                "discovering something. Zero means a plan is followed as written."
            ),
            "default": 2,
            "min": 0,
            "max": 5,
            "depends_on": {"key": "enable_chat_orchestration", "equals": True},
            "group": {"id": "limits", "label": "Limits", "variant": "limits"},
        },
        {
            "key": "chat_orchestration_step_timeout_seconds",
            "type": "number",
            "label": "Step Timeout",
            "help": "Seconds a single step may run before it is abandoned.",
            "default": 180,
            "min": 30,
            "max": 1800,
            "depends_on": {"key": "enable_chat_orchestration", "equals": True},
            "group": {"id": "limits", "label": "Limits", "variant": "limits"},
        },
        {
            "key": "chat_orchestration_total_timeout_seconds",
            "type": "number",
            "label": "Run Timeout",
            "help": "Seconds a whole run may take before it is abandoned.",
            "default": 900,
            "min": 60,
            "max": 7200,
            "depends_on": {"key": "enable_chat_orchestration", "equals": True},
            "group": {"id": "limits", "label": "Limits", "variant": "limits"},
        },
        {
            "key": "chat_orchestration_ledger_max_runs",
            "type": "number",
            "label": "Earlier Runs Shown To The Planner",
            "help": (
                "How many of the conversation's previous runs the planner can see. This "
                "is what lets a follow-up question reuse what an earlier turn already "
                "found instead of searching for it again, and what stops the assistant "
                "asking a question the user has already answered. Zero makes every turn "
                "plan from scratch."
            ),
            "default": 10,
            "min": 0,
            "max": 50,
            "depends_on": {"key": "enable_chat_orchestration", "equals": True},
            "group": {"id": "limits", "label": "Limits", "variant": "limits"},
        },
        {
            "key": "chat_orchestration_ledger_max_bytes",
            "type": "number",
            "label": "Earlier-run Summary Size",
            "help": (
                "Caps the size of that summary in bytes. Older runs lose their detail "
                "first when the budget is reached."
            ),
            "default": 16384,
            "min": 1024,
            "max": 131072,
            "depends_on": {"key": "enable_chat_orchestration", "equals": True},
            "group": {"id": "limits", "label": "Limits", "variant": "limits"},
        },
    ],
    "chat-orchestration-planner-model-section": [
        {
            "key": "chat_orchestration_planner_deployment",
            "type": "text",
            "label": "Planner Deployment Name",
            "help": (
                "Which model writes the plan. Planning is a short, structured task rather "
                "than a conversational one, so a smaller and faster deployment usually "
                "does it well and costs less per message than the model that writes the "
                "answer. Leave blank to plan with this deployment's default chat model."
            ),
            "default": "",
            "depends_on": {"key": "enable_chat_orchestration", "equals": True},
            "group": {"id": "connection", "label": "Planner model", "variant": "connection"},
        },
        {
            "key": "chat_orchestration_planner_model_id",
            "type": "text",
            "label": "Planner Model Id",
            "help": "Identifies the model when planning through a configured model endpoint.",
            "default": "",
            "depends_on": {"key": "enable_chat_orchestration", "equals": True},
            "group": {"id": "connection", "label": "Planner model", "variant": "connection"},
        },
        {
            "key": "chat_orchestration_planner_model_endpoint_id",
            "type": "text",
            "label": "Planner Model Endpoint Id",
            "help": (
                "Identifies the endpoint when planning through a configured model "
                "endpoint rather than the default deployment."
            ),
            "default": "",
            "depends_on": {"key": "enable_chat_orchestration", "equals": True},
            "group": {"id": "connection", "label": "Planner model", "variant": "connection"},
        },
        {
            "key": "chat_orchestration_planner_model_provider",
            "type": "text",
            "label": "Planner Model Provider",
            "help": "Identifies the provider when planning through a configured model endpoint.",
            "default": "",
            "depends_on": {"key": "enable_chat_orchestration", "equals": True},
            "group": {"id": "connection", "label": "Planner model", "variant": "connection"},
        },
    ],
    # The Workflow group has exactly one section, and none of its settings are
    # named `enable_*`, so the fallback scan found nothing at all and the group
    # rendered empty in V2. Declaring the section is what makes it reachable.
    "workflow-settings-section": [
        {
            "key": "allow_user_workflows",
            "type": "switch",
            "label": "Enable Personal Workflows",
            "help": (
                "Users can create personal workflows that run a selected agent or "
                "model manually or on an interval schedule."
            ),
            "default": False,
        },
        {
            "key": "require_member_of_workflow_user",
            "type": "switch",
            "label": "Require WorkflowUser App Role",
            "help": (
                "Restricts personal workflows to holders of the WorkflowUser "
                "Enterprise App role, covering opening, creating, editing, running "
                "and inspecting them. Assign the role value WorkflowUser to users or "
                "groups in the Enterprise App before turning this on, or everyone "
                "loses access at once."
            ),
            "default": False,
            "depends_on": {"key": "allow_user_workflows", "equals": True},
        },
        {
            "key": "allow_group_workflows",
            "type": "switch",
            "label": "Enable Group Workflows",
            "help": (
                "Permitted group members can create, manage and run workflows from "
                "group workspaces. Owners and Admins may author them unless "
                "Workspaces > Workspace Types restricts group agent, action and "
                "workflow management to Owners."
            ),
            "default": False,
        },
        {
            "key": "require_group_assignment_for_group_workflows",
            "type": "switch",
            "label": "Require Group Assignment to Use Workflow",
            "help": (
                "Narrows group workflows to an explicit allow list. Every other "
                "group loses the capability, so assign the groups that need it "
                "before turning this on."
            ),
            "default": False,
            "depends_on": {"key": "allow_group_workflows", "equals": True},
        },
        {
            "key": "group_workflow_allowed_group_ids",
            "type": "group_picker",
            "label": "Assigned Groups",
            "help": (
                "The groups that may create, manage and run group workflows while "
                "assignment is required."
            ),
            "default": [],
            "search_endpoint": "/api/v2/admin/groups",
            "depends_on": [
                {"key": "allow_group_workflows", "equals": True},
                {
                    "key": "require_group_assignment_for_group_workflows",
                    "equals": True,
                },
            ],
        },
        {
            "key": "workflow_max_auto_invoke_attempts",
            "type": "number",
            "label": "Workflow Agent Action Limit",
            "help": (
                "Maximum automatic tool or action calls an agent can make during one "
                "workflow run. Default is 60; increase for large document sets."
            ),
            "default": 60,
            "min": 1,
            "max": 500,
            "step": 1,
            "notice_level": "warning",
            "notice": (
                f"Values above {WORKFLOW_AUTO_INVOKE_CAPACITY_THRESHOLD} are "
                "capacity-sensitive. Enable Cosmos DB Throughput automation in "
                "SimpleChat so the app can monitor RU pressure and scale up Cosmos "
                "when needed, and also monitor Azure OpenAI throttling, App Service "
                "CPU and memory, and downstream service latency."
            ),
        },
        {
            "key": "workflow_max_tasks",
            "type": "number",
            "label": "Workflow Task Limit",
            "help": (
                "Maximum ordered instruction tasks users can add to one workflow. "
                "Default is 50; supported range is 1-100."
            ),
            "default": 50,
            "min": 1,
            "max": 100,
            "step": 1,
        },
    ],
    # --- Agents & Actions -------------------------------------------------
    #
    # The V1 pane renders the whole Agents tab as one card with several nested
    # cards inside it. The fields below are filed under those nested card ids,
    # which ``ADMIN_NAV`` now names as sections, so the V2 surface can separate
    # the runtime gate from the workspace permissions and the Agents page copy
    # without the server-rendered page changing at all.
    "agents-config": [
        {
            "key": "enable_semantic_kernel",
            "type": "switch",
            "label": "Enable Agents",
            "help": (
                "Runs the Semantic Kernel agent runtime. Everything else in this "
                "group depends on it: the Agents catalog page, the global agent "
                "and action tables, and every workspace permission are all "
                "unavailable while it is off."
            ),
            "default": False,
        },
        {
            "key": "per_user_semantic_kernel",
            "type": "switch",
            "label": "Workspace Mode",
            "help": (
                "Decides where agents and actions come from. Off means everyone "
                "shares one global set and an administrator picks the single agent "
                "that answers. On means each user and group keeps their own "
                "collection, and the workspace permissions become available."
            ),
            "default": False,
            "depends_on": {"key": "enable_semantic_kernel", "equals": True},
        },
        {
            "key": "merge_global_semantic_kernel_with_workspace",
            "type": "switch",
            "label": "Add Global Agents and Actions to Workspaces",
            "help": (
                "Folds the global set into every workspace collection, so people "
                "see both what they built and what the organisation publishes. "
                "Without this, turning on Workspace Mode hides the global set."
            ),
            "default": False,
            "depends_on": [
                {"key": "enable_semantic_kernel", "equals": True},
                {"key": "per_user_semantic_kernel", "equals": True},
            ],
        },
        {
            # Derived by POST /api/orchestration_settings from the chosen
            # orchestration mode. The fallback scan used to render it as a live
            # switch under AI Models, where setting it did nothing.
            "key": "enable_multi_agent_orchestration",
            "type": "switch",
            "label": "Multi-Agent Orchestration",
            "help": (
                "Whether the runtime coordinates several agents rather than "
                "routing to one. Follows the orchestration mode; this deployment "
                "offers only single-agent orchestration."
            ),
            "default": False,
            "readonly": True,
            "managed_by": "Agent Orchestration",
            "depends_on": {"key": "enable_semantic_kernel", "equals": True},
        },
        {
            # Reads and writes through /api/orchestration_settings rather than the
            # settings PATCH, and draws nothing while the deployment offers a
            # single orchestration type, which is the case today.
            "type": "component",
            "component": "agent-orchestration",
            "label": "Agent Orchestration",
            "help": (
                "How a chat is routed across agents. Only appears when this "
                "deployment offers more than one orchestration type."
            ),
            "depends_on": {"key": "enable_semantic_kernel", "equals": True},
        },
    ],
    # Rendered by V1 only while Workspace Mode is on, which ``ADMIN_NAV`` now
    # states as a section condition, so V2 hides the section on the same terms.
    "agent-toggles-card": [
        {
            "key": "allow_user_agents",
            "type": "switch",
            "label": "Allow Personal Agents",
            "help": (
                "People can build and keep agents in their own workspace. Use a "
                "personal agent governance policy when only some of them should."
            ),
            "default": False,
        },
        {
            "key": "allow_group_agents",
            "type": "switch",
            "label": "Allow Group Agents",
            "help": (
                "Groups can own agents their members share. Group workspaces must "
                "also be enabled under Workspaces, or the agents stay invisible."
            ),
            "default": False,
        },
        {
            "key": "allow_user_custom_endpoints",
            "type": "switch",
            "label": "Allow Personal Custom Endpoints",
            "help": (
                "People can point their own agents at a model endpoint they "
                "configure themselves instead of the deployment's shared models. "
                "This lets model traffic leave the endpoints you administer."
            ),
            "default": False,
        },
        {
            "key": "allow_group_custom_endpoints",
            "type": "switch",
            "label": "Allow Group Custom Endpoints",
            "help": (
                "The same for group-owned agents. Group workspaces must also be "
                "enabled under Workspaces."
            ),
            "default": False,
        },
        {
            "key": "enable_agent_template_gallery",
            "type": "switch",
            "label": "Enable Agent Template Gallery",
            "help": (
                "Gives workspace users a gallery of approved agents to start from "
                "rather than a blank editor, and adds the Agent Template Approvals "
                "section below."
            ),
            "default": True,
        },
    ],
    # Customises the /agents catalog page. That page carries
    # @enabled_required('enable_semantic_kernel'), so none of this copy is
    # reachable while agents are off -- which is why every field depends on it.
    "agents-page-customization-card": [
        {
            "key": "agents_page_title",
            "type": "text",
            "label": "Hero Title",
            "help": "Headline at the top of the Agents catalog page.",
            "default": "Find your next AI partner",
            "max_length": 120,
            "fallback_when_empty": True,
            "group": "Hero",
            "depends_on": {"key": "enable_semantic_kernel", "equals": True},
        },
        {
            "key": "agents_page_subtitle",
            "type": "text",
            "label": "Hero Subtitle",
            "help": "Supporting line under the headline.",
            "default": "Explore specialized agents built to accelerate how you work.",
            "max_length": 240,
            "fallback_when_empty": True,
            "group": "Hero",
            "depends_on": {"key": "enable_semantic_kernel", "equals": True},
        },
        {
            "key": "agents_page_hero_color_mode",
            "type": "select",
            "label": "Hero Color Mode",
            "help": "A flat colour, or a gradient between the two colours below.",
            "default": "single",
            "options": [
                {"value": "single", "label": "Single color"},
                {"value": "two_tone", "label": "Two tone gradient"},
            ],
            "group": "Hero",
            "depends_on": {"key": "enable_semantic_kernel", "equals": True},
        },
        {
            "key": "agents_page_hero_primary_color",
            "type": "color",
            "label": "Primary Color",
            "help": "Hero background, and the first stop of the gradient.",
            "default": "#0f172a",
            "group": "Hero",
            "depends_on": {"key": "enable_semantic_kernel", "equals": True},
        },
        {
            "key": "agents_page_hero_secondary_color",
            "type": "color",
            "label": "Secondary Color",
            "help": "Second stop of the gradient.",
            "default": "#1e293b",
            "group": "Hero",
            "depends_on": [
                {"key": "enable_semantic_kernel", "equals": True},
                {"key": "agents_page_hero_color_mode", "equals": "two_tone"},
            ],
        },
        {
            "key": "agents_page_disclaimer_markdown",
            "type": "textarea",
            "label": "Disclaimer or Guidance Text",
            "help": (
                "Shown under the hero. Use it for who to contact about a new agent, "
                "or the governance reminder people need before picking one."
            ),
            "default": "",
            "rows": 4,
            "markdown": True,
            "max_length": 3000,
            "placeholder": "Need a new agent? Contact ai-support@example.com.",
            "group": "Guidance",
            "depends_on": {"key": "enable_semantic_kernel", "equals": True},
        },
        {
            "key": "agents_page_show_instructions_in_details",
            "type": "switch",
            "label": "Show Agent Instructions in Details",
            "help": (
                "Reveals an agent's system prompt in its details popup and in the "
                "catalog API response. Turn it off when instructions carry wording "
                "or internal references you would rather not publish."
            ),
            "default": True,
            "group": "Guidance",
            "depends_on": {"key": "enable_semantic_kernel", "equals": True},
        },
        {
            "key": "agents_page_promoted_popular_order",
            "type": "select",
            "label": "Promoted Placement",
            "help": (
                "Where promoted agents sit relative to the ones that earned their "
                "place through usage."
            ),
            "default": "before",
            "options": [
                {"value": "before", "label": "Before actual popular agents"},
                {"value": "after", "label": "After actual popular agents"},
                {"value": "mixed", "label": "Mixed in by usage"},
            ],
            "group": "Promoted agents",
            "collapsed": True,
            "depends_on": {"key": "enable_semantic_kernel", "equals": True},
        },
        {
            "key": "agents_page_promoted_popular_tag_enabled",
            "type": "switch",
            "label": "Show Promoted Tag",
            "help": "Marks promoted agents so their placement is not mistaken for usage.",
            "default": True,
            "group": "Promoted agents",
            "collapsed": True,
            "depends_on": {"key": "enable_semantic_kernel", "equals": True},
        },
        {
            "key": "agents_page_promoted_popular_tag_label",
            "type": "text",
            "label": "Promoted Tag Label",
            "help": "Wording of that tag.",
            "default": "Promoted",
            "max_length": 40,
            "fallback_when_empty": True,
            "group": "Promoted agents",
            "collapsed": True,
            "depends_on": [
                {"key": "enable_semantic_kernel", "equals": True},
                {"key": "agents_page_promoted_popular_tag_enabled", "equals": True},
            ],
        },
        {
            # Writes agents_page_promoted_popular_agents into the draft. The list
            # is normalized on save by the delegated normalizer below.
            "type": "component",
            "component": "promoted-popular-agents",
            "key": "agents_page_promoted_popular_agents",
            "label": "Promoted Agents",
            "help": (
                "Puts chosen agents in the Popular tab before they have any usage "
                "behind them, which is how a brand new agent gets discovered. "
                "People only ever see agents already visible to them."
            ),
            "group": "Promoted agents",
            "collapsed": True,
            "depends_on": {"key": "enable_semantic_kernel", "equals": True},
        },
    ],
    "agent-template-approvals-section": [
        {
            "key": "agent_templates_allow_user_submission",
            "type": "switch",
            "label": "Allow User Template Submissions",
            "help": (
                "Workspace users can offer an agent they built as a template for "
                "everyone else, which is how a gallery grows without an admin "
                "authoring every entry."
            ),
            "default": True,
        },
        {
            "key": "agent_templates_require_approval",
            "type": "switch",
            "label": "Require Admin Approval",
            "help": (
                "Holds submissions in the approvals queue instead of publishing "
                "them straight into the gallery."
            ),
            "default": True,
            "depends_on": {"key": "agent_templates_allow_user_submission", "equals": True},
        },
    ],
    # --- Actions ----------------------------------------------------------
    #
    # Analyze and Comparison are stored as one nested object rather than as six
    # top-level keys, so each field names the path it writes and the container is
    # reassembled on save. Both limits are bounded by
    # DOCUMENT_ACTION_LIMIT_BOUNDS, which the container normalizer enforces.
    "document-action-capabilities-card": [
        {
            "key": "document_action_analyze_enabled",
            "settings_path": ["document_action_capabilities", "analyze", "enabled"],
            "type": "switch",
            "label": "Enable Analyze",
            "help": (
                "Offers Analyze in the Action menu in chat and workflows. It reads "
                "the selected documents in full rather than searching them, so an "
                "answer covers every one instead of the passages a search returned."
            ),
            "default": True,
            "group": "Analyze",
        },
        {
            "key": "document_action_analyze_chat_max_documents",
            "settings_path": ["document_action_capabilities", "analyze", "chat_max_documents"],
            "type": "number",
            "label": "Analyze: Chat Document Limit",
            "help": (
                "Most documents one chat message may analyze. Each one is read in "
                "full, so this bounds how long a single message can take and how "
                "much it costs."
            ),
            "default": DOCUMENT_ACTION_CHAT_DEFAULT_LIMIT,
            "min": DOCUMENT_ACTION_CHAT_MIN_LIMIT,
            "max": DOCUMENT_ACTION_CHAT_MAX_LIMIT,
            "group": "Analyze",
            "depends_on": {"key": "document_action_analyze_enabled", "equals": True},
        },
        {
            "key": "document_action_analyze_workflow_max_documents",
            "settings_path": [
                "document_action_capabilities",
                "analyze",
                "workflow_max_documents",
            ],
            "type": "number",
            "label": "Analyze: Workflow Document Limit",
            "help": (
                "The same limit for a workflow run, which is not waiting on someone "
                "watching a chat and so can be allowed a far larger batch."
            ),
            "default": DOCUMENT_ACTION_WORKFLOW_DEFAULT_LIMIT,
            "min": DOCUMENT_ACTION_WORKFLOW_MIN_LIMIT,
            "max": DOCUMENT_ACTION_WORKFLOW_MAX_LIMIT,
            "group": "Analyze",
            "depends_on": {"key": "document_action_analyze_enabled", "equals": True},
        },
        {
            "key": "document_action_comparison_enabled",
            "settings_path": ["document_action_capabilities", "comparison", "enabled"],
            "type": "switch",
            "label": "Enable Document Comparison",
            "help": (
                "Offers Document Comparison in the Action menu. It reads one "
                "baseline document against the others selected, which is what "
                "answers questions about what changed between versions."
            ),
            "default": True,
            "group": "Comparison",
        },
        {
            "key": "document_action_comparison_chat_max_documents",
            "settings_path": [
                "document_action_capabilities",
                "comparison",
                "chat_max_documents",
            ],
            "type": "number",
            "label": "Comparison: Chat Document Limit",
            "help": "Most documents one chat message may compare, including the baseline.",
            "default": DOCUMENT_ACTION_CHAT_DEFAULT_LIMIT,
            "min": DOCUMENT_ACTION_CHAT_MIN_LIMIT,
            "max": DOCUMENT_ACTION_CHAT_MAX_LIMIT,
            "group": "Comparison",
            "depends_on": {"key": "document_action_comparison_enabled", "equals": True},
        },
        {
            "key": "document_action_comparison_workflow_max_documents",
            "settings_path": [
                "document_action_capabilities",
                "comparison",
                "workflow_max_documents",
            ],
            "type": "number",
            "label": "Comparison: Workflow Document Limit",
            "help": "The same limit for a workflow run.",
            "default": DOCUMENT_ACTION_WORKFLOW_DEFAULT_LIMIT,
            "min": DOCUMENT_ACTION_WORKFLOW_MIN_LIMIT,
            "max": DOCUMENT_ACTION_WORKFLOW_MAX_LIMIT,
            "group": "Comparison",
            "depends_on": {"key": "document_action_comparison_enabled", "equals": True},
        },
    ],
    # Rendered by V1 only while Workspace Mode is on, matching agent-toggles-card.
    "plugin-feature-toggles": [
        {
            "key": "allow_user_plugins",
            "type": "switch",
            "label": "Allow Personal Actions",
            "help": (
                "People can create actions in their own workspace. This is a wider "
                "grant than a personal agent: an action carries an endpoint and the "
                "credentials to reach it, so the traffic an agent generates is no "
                "longer limited to destinations you configured."
            ),
            "default": False,
        },
        {
            "key": "allow_group_plugins",
            "type": "switch",
            "label": "Allow Group Actions",
            "help": (
                "The same for a group's shared actions. Group workspaces must also "
                "be enabled under Workspaces."
            ),
            "default": False,
        },
    ],
    "gpt-config": [
        {
            "type": "component",
            "component": "chat-mode-notice",
            "label": "Which endpoint chat is using",
            "help": (
                "Connections and the classic single endpoint are two separate routes, and "
                "only one of them is live at a time. This says which."
            ),
        },
        {
            "key": "default_model_selection",
            "type": "component",
            "component": "chat-default-model",
            "label": "Default model",
            "help": (
                "Used when nothing else has chosen a model -- a new conversation, or work "
                "started outside the chat window. Only models that are enabled on an "
                "enabled connection can be picked, because anything else is cleared the "
                "next time the connections are saved."
            ),
        },
        {
            "key": "enable_gpt_apim",
            "type": "switch",
            "label": "Send requests through API Management",
            "help": (
                "Routes GPT requests that use the classic endpoint through API Management "
                "rather than straight to the Azure OpenAI resource, which is how a "
                "deployment applies its own governance and monitoring to them. The APIM "
                "endpoint, deployment and subscription key this needs are configured on "
                "the classic admin page, so turning it on before those are set leaves "
                "those requests with nowhere to go."
            ),
            "default": False,
        },
    ],
    "core-plugin-toggles": [
        {
            "key": "enable_time_plugin",
            "type": "switch",
            "label": "Time",
            "help": (
                "Lets an agent read the current date and time and calculate with "
                "them. Without it a model answers date questions from its training "
                "data, which is always out of date."
            ),
            "default": True,
            "group": "Built-in actions",
            "collapsed": True,
        },
        {
            "key": "enable_http_plugin",
            "type": "switch",
            "label": "HTTP",
            "help": (
                "Lets an agent fetch a URL directly. This is the one built-in action "
                "that reaches outside the deployment, so turn it off where agents "
                "should only use the connectors you configured."
            ),
            "default": True,
            "group": "Built-in actions",
            "collapsed": True,
        },
        {
            "key": "enable_wait_plugin",
            "type": "switch",
            "label": "Wait",
            "help": "Lets an agent pause, which workflows use to space out repeated calls.",
            "default": True,
            "group": "Built-in actions",
            "collapsed": True,
        },
        {
            "key": "enable_math_plugin",
            "type": "switch",
            "label": "Math",
            "help": (
                "Lets an agent calculate rather than predict an answer, which is why "
                "arithmetic in a reply can be relied on."
            ),
            "default": True,
            "group": "Built-in actions",
            "collapsed": True,
        },
        {
            "key": "enable_text_plugin",
            "type": "switch",
            "label": "Text",
            "help": "Lets an agent format, trim and reshape text deterministically.",
            "default": True,
            "group": "Built-in actions",
            "collapsed": True,
        },
        {
            "key": "enable_default_embedding_model_plugin",
            "type": "switch",
            "label": "Default Embedding Model",
            "help": (
                "Exposes the embedding model to agents for similarity work outside "
                "the normal document search path. Off by default; document search "
                "already embeds without it."
            ),
            "default": False,
            "group": "Built-in actions",
            "collapsed": True,
        },
        {
            "key": "enable_fact_memory_plugin",
            "type": "switch",
            "label": "Fact Memory",
            "help": (
                "Lets an agent store, update and remove durable facts and "
                "instructions for the current user or group."
            ),
            "default": True,
            "readonly": True,
            "managed_by": "Chat \u203a Chat Experience \u203a Fact Memory",
            "group": "Managed elsewhere",
        },
        {
            "key": "enable_tabular_processing_plugin",
            "type": "switch",
            "label": "Tabular Processing",
            "help": (
                "Lets an agent analyse a CSV or XLSX file as a whole dataset rather "
                "than as retrieved passages. The application recomputes this from "
                "Enhanced Citations on every settings read, so it cannot be set "
                "independently."
            ),
            "default": False,
            "readonly": True,
            "managed_by": "Chat \u203a Citations \u203a Enhanced",
            "group": "Managed elsewhere",
        },
    ],
    # --- Inbound MCP ------------------------------------------------------
    #
    # The whole card is gated by ENABLE_MCP_UI, an App Service application
    # setting with no entry in the settings document, so the fields depend on a
    # runtime flag rather than a settings key. When the flag is off the section
    # still renders, showing only the notice that explains how to turn it on --
    # which is why the notice depends on the same flag being false.
    "inbound-mcp-configuration": [
        {
            "type": "component",
            "component": "inbound-mcp-disabled-notice",
            "label": "Inbound MCP preview",
            "depends_on": {"flag": "mcp_ui_enabled", "equals": False},
        },
        {
            "key": "enable_inbound_mcp_server",
            "type": "switch",
            "label": "Enable Inbound MCP Server",
            "help": (
                "Accepts requests from external MCP clients such as an editor. "
                "Access stays deny-by-default afterwards: a request must also pass "
                "the delegated scope, the Entra role, the client allowlist, the "
                "source allowlist, and a governance policy. Turn this on last."
            ),
            "default": False,
            "group": "Runtime gate",
            "depends_on": {"flag": "mcp_ui_enabled", "equals": True},
        },
        {
            "key": "inbound_mcp_required_scope",
            "type": "text",
            "label": "Required Delegated Scope",
            "help": (
                "The delegated scope a user's client must present. It has to match "
                "the scope exposed on the Entra application registration, or every "
                "request is refused."
            ),
            "default": "DelegatedMcpServerAccess",
            "max_length": 128,
            "fallback_when_empty": True,
            "group": "Runtime gate",
            "depends_on": {"flag": "mcp_ui_enabled", "equals": True},
        },
        {
            "key": "inbound_mcp_required_user_role",
            "type": "text",
            "label": "Required Delegated User Role",
            "help": (
                "The Entra app role a signed-in user must hold. This decides who "
                "may connect at all; which tools they then get is decided by "
                "governance policy."
            ),
            "default": "InboundMCPUserAccess",
            "max_length": 128,
            "fallback_when_empty": True,
            "group": "Runtime gate",
            "depends_on": {"flag": "mcp_ui_enabled", "equals": True},
        },
        {
            "key": "inbound_mcp_required_app_role",
            "type": "text",
            "label": "Required App-Only Role",
            "help": (
                "Reserved for future service-to-service tools. No tool uses it "
                "today; personal tools require a delegated user token."
            ),
            "default": "InboundMCPAppAccess",
            "max_length": 128,
            "fallback_when_empty": True,
            "group": "Runtime gate",
            "depends_on": {"flag": "mcp_ui_enabled", "equals": True},
        },
        {
            "key": "enable_inbound_mcp_rate_limits",
            "type": "switch",
            "label": "Enable Tool Throttles",
            "help": (
                "Caps how often one caller may invoke each category of tool. On by "
                "default, and enforced across app instances, so a client stuck in a "
                "loop cannot exhaust the deployment. It has no effect until the "
                "server itself is enabled."
            ),
            "default": True,
            "group": "Request limits",
            "depends_on": {"flag": "mcp_ui_enabled", "equals": True},
        },
        {
            "key": "inbound_mcp_max_request_bytes",
            "type": "number",
            "label": "Max Request Bytes",
            "help": "Largest request body accepted. Anything bigger is refused unread.",
            "default": 65536,
            "min": 1024,
            "max": 1048576,
            "group": "Request limits",
            "depends_on": {"flag": "mcp_ui_enabled", "equals": True},
        },
        {
            "key": "inbound_mcp_rate_limit_window_seconds",
            "type": "number",
            "label": "Throttle Window (Seconds)",
            "help": "The period each of the three limits below is counted over.",
            "default": 60,
            "min": 10,
            "max": 3600,
            "group": "Request limits",
            "depends_on": [
                {"flag": "mcp_ui_enabled", "equals": True},
                {"key": "enable_inbound_mcp_rate_limits", "equals": True},
            ],
        },
        {
            "key": "inbound_mcp_rate_limit_read_per_window",
            "type": "number",
            "label": "Read Calls Per Window",
            "help": "Reads are cheap, so this is the most permissive of the three.",
            "default": 120,
            "min": 1,
            "max": 10000,
            "group": "Request limits",
            "depends_on": [
                {"flag": "mcp_ui_enabled", "equals": True},
                {"key": "enable_inbound_mcp_rate_limits", "equals": True},
            ],
        },
        {
            "key": "inbound_mcp_rate_limit_search_per_window",
            "type": "number",
            "label": "Search Calls Per Window",
            "help": "Searches cost an index query each, so they are limited harder than reads.",
            "default": 30,
            "min": 1,
            "max": 10000,
            "group": "Request limits",
            "depends_on": [
                {"flag": "mcp_ui_enabled", "equals": True},
                {"key": "enable_inbound_mcp_rate_limits", "equals": True},
            ],
        },
        {
            "key": "inbound_mcp_rate_limit_write_per_window",
            "type": "number",
            "label": "Write Calls Per Window",
            "help": "Writes change stored data, so this is the tightest limit.",
            "default": 10,
            "min": 1,
            "max": 10000,
            "group": "Request limits",
            "depends_on": [
                {"flag": "mcp_ui_enabled", "equals": True},
                {"key": "enable_inbound_mcp_rate_limits", "equals": True},
            ],
        },
        {
            "key": "inbound_mcp_allowed_client_app_entries",
            "type": "entry_list",
            "label": "Allowed Client App IDs",
            "help": (
                "The Entra application ids permitted to connect. This list is "
                "required: while it is empty no MCP client can reach the endpoint, "
                "whatever else is configured."
            ),
            "default": [],
            "value_label": "Client app ID",
            "placeholder": "00000000-0000-0000-0000-000000000000",
            "empty_text": "No client apps allowed, so nothing can connect.",
            "group": "Allowlists",
            "depends_on": {"flag": "mcp_ui_enabled", "equals": True},
        },
        {
            "key": "inbound_mcp_allow_external_tenants",
            "type": "switch",
            "label": "Allow Additional Tenant IDs",
            "help": (
                "Off restricts callers to this deployment's own tenant. Turn it on "
                "only to admit a named partner tenant; the deployment's own tenant "
                "is always included."
            ),
            "default": False,
            "group": "Allowlists",
            "depends_on": {"flag": "mcp_ui_enabled", "equals": True},
        },
        {
            "key": "inbound_mcp_allowed_tenant_entries",
            "type": "entry_list",
            "label": "Allowed Tenant IDs",
            "help": "Additional tenants whose users may connect.",
            "default": [],
            "value_label": "Tenant ID",
            "placeholder": "00000000-0000-0000-0000-000000000000",
            "empty_text": "Only this deployment's tenant is allowed.",
            "group": "Allowlists",
            "depends_on": [
                {"flag": "mcp_ui_enabled", "equals": True},
                {"key": "inbound_mcp_allow_external_tenants", "equals": True},
            ],
        },
        {
            "key": "inbound_mcp_allow_all_source_ids",
            "type": "switch",
            "label": "Allow All Source IDs",
            "help": (
                "The source is a client-supplied header, so it identifies rather "
                "than authenticates. Leaving this on accepts any value at this "
                "layer; a governance policy still decides who gets tools. Turn it "
                "off only where a gateway sets and enforces the header."
            ),
            "default": True,
            "group": "Allowlists",
            "depends_on": {"flag": "mcp_ui_enabled", "equals": True},
        },
        {
            "key": "inbound_mcp_source_header",
            "type": "text",
            "label": "Source Header Name",
            "help": "The request header the source value is read from.",
            "default": "X-SimpleChat-MCP-Source",
            "max_length": 128,
            "fallback_when_empty": True,
            "group": "Allowlists",
            "depends_on": {"flag": "mcp_ui_enabled", "equals": True},
        },
        {
            "key": "inbound_mcp_allowed_source_entries",
            "type": "entry_list",
            "label": "Allowed Source IDs",
            "help": "The source values accepted when not allowing all of them.",
            "default": [],
            "value_label": "Source value",
            "empty_text": "No source values allowed, so no request passes this check.",
            "group": "Allowlists",
            "depends_on": [
                {"flag": "mcp_ui_enabled", "equals": True},
                {"key": "inbound_mcp_allow_all_source_ids", "equals": False},
            ],
        },
    ],
    "access-denied-message-section": [
        {
            "key": "access_denied_message",
            "type": "textarea",
            "label": "Access Denied Message",
            "help": (
                "Shown to someone who signed in successfully but holds none of the "
                "roles the application requires. Name the team that grants access, "
                "since the person reading it cannot get any further on their own."
            ),
            "default": (
                "You are logged in but do not have the required permissions to access "
                "this application.\nPlease contact an administrator for access."
            ),
            "rows": 3,
            "max_length": ACCESS_DENIED_MESSAGE_MAX_LENGTH,
            "fallback_when_empty": True,
        },
    ],
    "keyvault-section": [
        {
            "key": "enable_key_vault_secret_storage",
            "type": "switch",
            "group": "Vault connection",
            "label": "Store agent and action secrets in Key Vault",
            "help": (
                "API keys and secrets attached to agents and actions are written to "
                "Azure Key Vault instead of the settings document, and referenced by "
                "name."
            ),
            "notice": (
                "Enabling this is effectively one-way. Secrets saved afterwards live "
                "in Key Vault and are referenced by name, so turning it back off "
                "leaves those references pointing at values the application can no "
                "longer read, breaking every agent and action that depends on them."
            ),
            "notice_level": "warning",
            "default": False,
        },
        {
            "key": "key_vault_name",
            "type": "text",
            "group": "Vault connection",
            "label": "Key Vault Name",
            "help": (
                "The vault resource name only, not a URL. The endpoint suffix comes "
                "from the AZURE_ENVIRONMENT App Service setting."
            ),
            "default": "",
            "max_length": 120,
            "placeholder": "my-simplechat-vault",
            "depends_on": {"key": "enable_key_vault_secret_storage", "equals": True},
        },
        {
            "key": "key_vault_identity",
            "type": "text",
            "group": "Vault connection",
            "label": "Managed Identity Client ID",
            "help": (
                "Client ID of the user-assigned managed identity that holds Get, Set "
                "and List on the vault. Leave blank to use the App Service "
                "system-assigned identity."
            ),
            "default": "",
            "max_length": 120,
            "depends_on": {"key": "enable_key_vault_secret_storage", "equals": True},
        },
        {
            "type": "component",
            "component": "connection-test",
            "test_type": "key_vault",
            "test_payload": {
                "vault_name": {"key": "key_vault_name"},
                "client_id": {"key": "key_vault_identity"},
            },
            "group": "Vault connection",
            "label": "Test Key Vault connection",
            "help": (
                "Lists secret properties with the identity above. Run this before "
                "saving a vault change, because a wrong identity is only visible once "
                "an agent tries to read a secret."
            ),
            "depends_on": {"key": "enable_key_vault_secret_storage", "equals": True},
        },
        {
            "key": "enable_key_vault_secret_expiration_reminders",
            "type": "switch",
            "group": "Expiration reminders",
            "label": "Track secret expiration dates",
            "help": (
                "Key Vault secret names are opaque hashes, so an expiry alert from "
                "Azure cannot be traced back to an owner. Tracking records who owns "
                "each secret, which action and field it backs, and warns before it "
                "expires."
            ),
            "notice": (
                "SimpleChat raises reminders in-app and emits the Application "
                "Insights event key_vault_expiration_reminder_triggered; it does not "
                "send email. To notify anyone, point an Azure Monitor scheduled query "
                "alert, Logic App, Function or webhook at that event, and configure "
                "the vault's own expiry alerts in Azure Monitor or Event Grid too."
            ),
            "notice_level": "info",
            "default": False,
            "depends_on": {"key": "enable_key_vault_secret_storage", "equals": True},
        },
        {
            "key": "key_vault_secret_expiration_default_lead_days",
            "type": "number",
            "group": "Expiration reminders",
            "label": "Default lead days",
            "help": "How far ahead of expiry the first reminder is raised.",
            "default": 30,
            "min": KEY_VAULT_REMINDER_MIN_LEAD_DAYS,
            "max": KEY_VAULT_REMINDER_MAX_LEAD_DAYS,
            "depends_on": [
                {"key": "enable_key_vault_secret_storage", "equals": True},
                {"key": "enable_key_vault_secret_expiration_reminders", "equals": True},
            ],
        },
        {
            "key": "key_vault_secret_expiration_default_contact_email",
            "type": "text",
            "input_type": "email",
            "group": "Expiration reminders",
            "label": "Default reminder email",
            "help": (
                "Used when a tracked secret names no owner of its own. This address "
                "is not emailed by SimpleChat; it is recorded so Azure Monitor or a "
                "Logic App can route to it."
            ),
            "default": "",
            "max_length": 254,
            "placeholder": "owner@example.com",
            "depends_on": [
                {"key": "enable_key_vault_secret_storage", "equals": True},
                {"key": "enable_key_vault_secret_expiration_reminders", "equals": True},
            ],
        },
        {
            "key": "key_vault_secret_expiration_admin_roles",
            "type": "string_list",
            "group": "Expiration reminders",
            "label": "Admin notification roles",
            "help": (
                "Roles notified in-app about global-scope reminders, meaning secrets "
                "with no individual owner. Comma separated."
            ),
            "default": KEY_VAULT_REMINDER_DEFAULT_ADMIN_ROLES,
            "fallback_when_empty": True,
            "max_item_length": 80,
            "placeholder": "Admin",
            "depends_on": [
                {"key": "enable_key_vault_secret_storage", "equals": True},
                {"key": "enable_key_vault_secret_expiration_reminders", "equals": True},
            ],
        },
        {
            "key": "key_vault_secret_expiration_scan_interval_seconds",
            "type": "number",
            "group": "Expiration reminders",
            "label": "Scan interval (seconds)",
            "help": (
                "How often the background sweep re-checks tracked secrets. The "
                "default of 21600 is four sweeps a day."
            ),
            "default": 21600,
            "min": KEY_VAULT_REMINDER_MIN_SCAN_SECONDS,
            "max": KEY_VAULT_REMINDER_MAX_SCAN_SECONDS,
            "depends_on": [
                {"key": "enable_key_vault_secret_storage", "equals": True},
                {"key": "enable_key_vault_secret_expiration_reminders", "equals": True},
            ],
        },
        {
            "key": "key_vault_secret_expiration_require_expiration",
            "type": "switch",
            "group": "Expiration reminders",
            "label": "Require an expiration date when users enable tracking",
            "help": (
                "A tracked secret with no expiry date can never raise a reminder, so "
                "this stops one being created in that state."
            ),
            "default": False,
            "depends_on": [
                {"key": "enable_key_vault_secret_storage", "equals": True},
                {"key": "enable_key_vault_secret_expiration_reminders", "equals": True},
            ],
        },
        {
            "key": "key_vault_secret_expiration_emit_contact_email_in_telemetry",
            "type": "switch",
            "group": "Expiration reminders",
            "label": "Include the contact email in external telemetry",
            "help": (
                "Adds contact_email to the key_vault_expiration_reminder_triggered "
                "Application Insights event. Turn this on only when downstream "
                "automation needs the address to route a notification, since it puts "
                "an email address into telemetry."
            ),
            "default": False,
            "depends_on": [
                {"key": "enable_key_vault_secret_storage", "equals": True},
                {"key": "enable_key_vault_secret_expiration_reminders", "equals": True},
            ],
        },
        {
            "type": "component",
            "component": "key-vault-secret-reminders",
            "group": "Tracked secrets",
            "label": "Tracked secret inventory",
            "help": (
                "Maps each opaque vault secret name back to its owner, source and "
                "field, so an emailed Key Vault alert can be acted on."
            ),
            "depends_on": [
                {"key": "enable_key_vault_secret_storage", "equals": True},
                {"key": "enable_key_vault_secret_expiration_reminders", "equals": True},
            ],
        },
    ],
    "content-safety-section": [
        {
            "key": "enable_content_safety",
            "type": "switch",
            "group": "Connection",
            "label": "Enable Content Safety",
            "help": (
                "Every user message is sent to Azure AI Content Safety before it "
                "reaches a model. A message that trips the configured thresholds is "
                "blocked and recorded as a safety violation."
            ),
            "default": False,
        },
        {
            "key": "enable_content_safety_apim",
            "type": "switch",
            "group": "Connection",
            "label": "Route through Azure API Management",
            "help": (
                "Send Content Safety calls to an APIM front end rather than the "
                "service endpoint, so they are subject to the same policy, quota and "
                "logging as the rest of your Azure AI traffic."
            ),
            "default": False,
            "depends_on": {"key": "enable_content_safety", "equals": True},
        },
        {
            "key": "content_safety_endpoint",
            "type": "text",
            "input_type": "url",
            "group": "Connection",
            "label": "Content Safety Endpoint",
            "help": "The resource endpoint from the Content Safety resource in Azure.",
            "default": "",
            "max_length": 500,
            "placeholder": "https://my-content-safety.cognitiveservices.azure.com/",
            "depends_on": [
                {"key": "enable_content_safety", "equals": True},
                {"key": "enable_content_safety_apim", "equals": False},
            ],
        },
        {
            "key": "content_safety_authentication_type",
            "type": "select",
            "group": "Connection",
            "label": "Authentication Type",
            "help": (
                "Managed identity avoids storing a key, and needs the Cognitive "
                "Services User role on the resource for the App Service identity."
            ),
            "default": "key",
            "options": [
                {"value": "key", "label": "Key"},
                {"value": "managed_identity", "label": "Managed Identity"},
            ],
            "depends_on": [
                {"key": "enable_content_safety", "equals": True},
                {"key": "enable_content_safety_apim", "equals": False},
            ],
        },
        {
            "key": "content_safety_key",
            "type": "secret",
            "group": "Connection",
            "label": "Content Safety Key",
            "help": "Either key from the Content Safety resource.",
            "default": "",
            "depends_on": [
                {"key": "enable_content_safety", "equals": True},
                {"key": "enable_content_safety_apim", "equals": False},
                {"key": "content_safety_authentication_type", "equals": "key"},
            ],
        },
        {
            "key": "azure_apim_content_safety_endpoint",
            "type": "text",
            "input_type": "url",
            "group": "Connection",
            "label": "APIM Content Safety Endpoint",
            "help": "The APIM API base URL that fronts the Content Safety resource.",
            "default": "",
            "max_length": 500,
            "depends_on": [
                {"key": "enable_content_safety", "equals": True},
                {"key": "enable_content_safety_apim", "equals": True},
            ],
        },
        {
            "key": "azure_apim_content_safety_subscription_key",
            "type": "secret",
            "group": "Connection",
            "label": "APIM Subscription Key",
            "help": "The APIM subscription key authorised for that API.",
            "default": "",
            "depends_on": [
                {"key": "enable_content_safety", "equals": True},
                {"key": "enable_content_safety_apim", "equals": True},
            ],
        },
        {
            "type": "component",
            "component": "connection-test",
            "test_type": "safety",
            "test_payload": {
                "enabled": {"value": True},
                "enable_apim": {"key": "enable_content_safety_apim"},
                "apim.endpoint": {"key": "azure_apim_content_safety_endpoint"},
                "apim.subscription_key": {
                    "key": "azure_apim_content_safety_subscription_key"
                },
                "direct.endpoint": {"key": "content_safety_endpoint"},
                "direct.key": {"key": "content_safety_key"},
                # The endpoint reads `auth_type`, not the settings key name. Sending
                # the settings name would leave the managed identity branch
                # unreachable, so the probe would test the key path on a deployment
                # that does not use it.
                "direct.auth_type": {"key": "content_safety_authentication_type"},
            },
            "group": "Connection",
            "label": "Test Content Safety connection",
            "help": (
                "Analyses a harmless sample string. Worth running before saving, "
                "because a broken connection blocks chat rather than failing quietly."
            ),
            "depends_on": {"key": "enable_content_safety", "equals": True},
        },
        {
            "key": "content_safety_violation_message",
            "type": "textarea",
            "markdown": True,
            "group": "When a message is blocked",
            "label": "Safety Violation Message",
            "help": (
                "Replaces the blocked message in the conversation. Say what to do "
                "next -- rephrase, or raise it with a named team -- because the user "
                "cannot see what triggered the block unless you include it below."
            ),
            "default": "",
            "rows": 4,
            "max_length": CONTENT_SAFETY_VIOLATION_MESSAGE_MAX_LENGTH,
            "placeholder": "Your message was blocked by Content Safety.",
            "depends_on": {"key": "enable_content_safety", "equals": True},
        },
        {
            "key": "content_safety_include_trigger_information",
            "type": "switch",
            "group": "When a message is blocked",
            "label": "Show what triggered the block",
            "help": (
                "Appends the detected categories, their severities and any blocklist "
                "matches beneath the message. Helps users self-correct, but tells "
                "them exactly which thresholds are set."
            ),
            "default": True,
            "depends_on": {"key": "enable_content_safety", "equals": True},
        },
    ],
    "idle-timeout-section": [
        {
            "key": "enable_idle_timeout",
            "type": "switch",
            "label": "Sign out inactive users",
            "help": (
                "Ends the local session after a period without interaction, so an "
                "unattended browser on a shared machine does not stay signed in. "
                "This is a client-side timer, not a token lifetime."
            ),
            "default": False,
        },
        {
            "key": "idle_timeout_minutes",
            "type": "number",
            "label": "Sign out after (minutes)",
            "help": (
                "Minimum 10 minutes. Anything shorter interrupts people mid-task "
                "while they read a long response."
            ),
            "default": 30,
            "min": IDLE_TIMEOUT_MIN_MINUTES,
            "max": IDLE_TIMEOUT_MAX_MINUTES,
            "depends_on": {"key": "enable_idle_timeout", "equals": True},
        },
        {
            "key": "idle_warning_minutes",
            "type": "number",
            "label": "Warn after (minutes)",
            "help": (
                "When the warning dialog appears. Set it equal to the sign-out time "
                "to skip the warning entirely. A value beyond the sign-out time is "
                "lowered to match, since a warning cannot follow the sign-out."
            ),
            "default": 28,
            "min": IDLE_WARNING_MIN_MINUTES,
            "max": IDLE_TIMEOUT_MAX_MINUTES,
            "depends_on": {"key": "enable_idle_timeout", "equals": True},
        },
        {
            "key": "idle_warning_message",
            "type": "text",
            "label": "Idle Warning Message",
            "help": "Heading of the dialog offering to keep the session alive.",
            "default": "You've been inactive for a while.",
            "max_length": 200,
            "fallback_when_empty": True,
            "depends_on": {"key": "enable_idle_timeout", "equals": True},
        },
    ],
    "front-door-section": [
        {
            "key": "enable_front_door",
            "type": "switch",
            "label": "Behind Azure Front Door or a load balancer",
            "help": (
                "The App Service sees its own internal hostname, not the one users "
                "typed, so sign-in redirects would send people back to a host they "
                "cannot reach. Enabling this makes the URL below the base of every "
                "generated redirect."
            ),
            "default": False,
        },
        {
            "key": "front_door_url",
            "type": "text",
            "input_type": "url",
            "label": "Front Door URL",
            "help": (
                "The public origin only -- scheme and host, no path. This must match "
                "a redirect URI registered on the Entra app registration, or sign-in "
                "fails with a redirect mismatch."
            ),
            "default": "",
            "max_length": 500,
            "placeholder": "https://your-frontdoor.azurefd.net",
            "depends_on": {"key": "enable_front_door", "equals": True},
        },
        {
            "type": "component",
            "component": "front-door-redirect-preview",
            "label": "Generated redirects",
            "help": (
                "Register both of these on the Entra app registration before saving."
            ),
            "depends_on": {"key": "enable_front_door", "equals": True},
        },
    ],
    "rate-limit-message-section": [
        {
            "key": "enable_custom_rate_limit_message",
            "type": "switch",
            "label": "Use a custom rate limit message",
            "help": (
                "Throttled calls are retried with backoff, so this is only reached "
                "once the retries run out and the request fails with HTTP 429. Leave "
                "it off to keep the built-in wording."
            ),
            "default": False,
        },
        {
            "key": "rate_limit_message",
            "type": "textarea",
            "markdown": True,
            "label": "Rate Limit Message",
            "help": (
                "Give the retry window or an internal support channel -- the built-in "
                "text cannot know either. Clearing this falls back to the built-in "
                "message rather than showing nothing."
            ),
            "default": "",
            "rows": 5,
            "max_length": RATE_LIMIT_MESSAGE_MAX_LENGTH,
            "depends_on": {"key": "enable_custom_rate_limit_message", "equals": True},
        },
    ],
    "cosmos-maintenance-section": [
        {
            "key": "enable_app_maintenance",
            "type": "switch",
            "label": "Run background maintenance",
            "help": (
                "The recurring job that checks Cosmos composite index policies, "
                "reconciles the document access index and clears stale cache "
                "documents. Turning it off stops index repair and backfill from "
                "converging, so document lists fall back to slower source queries."
            ),
            "default": True,
        },
        {
            "key": "enable_startup_app_maintenance",
            "type": "switch",
            "label": "Also run maintenance at startup",
            "help": (
                "Runs one maintenance pass as the application starts, so an upgrade "
                "picks up new index policies without waiting for the next scheduled "
                "run. Disable it only if startup time matters more than converging "
                "promptly after a deployment."
            ),
            "default": True,
            "depends_on": {"key": "enable_app_maintenance", "equals": True},
        },
    ],
    "embeddings-config": [
        {
            "key": "enable_embedding_apim",
            "type": "switch",
            "label": "Use APIM instead of direct to Azure OpenAI endpoint",
            "help": (
                "Sends embedding requests to API Management rather than straight to the "
                "Azure OpenAI resource, so a gateway can apply its own governance and "
                "monitoring. The two routes are configured separately and only the "
                "selected one is used."
            ),
            "default": False,
        },
        {
            "key": "azure_openai_embedding_endpoint",
            "type": "text",
            "label": "Azure OpenAI Embedding Endpoint",
            "help": (
                "The Azure OpenAI resource that turns document and query text into "
                "vectors. Embeddings are not shared with chat: indexing and search use "
                "this route even when chat is pointed somewhere else entirely."
            ),
            "default": "",
            "placeholder": "https://your-resource.openai.azure.com",
            "depends_on": {"key": "enable_embedding_apim", "equals": False},
        },
        {
            "key": "azure_openai_embedding_authentication_type",
            "type": "select",
            "label": "Authentication Type",
            "help": (
                "Managed identity avoids storing a credential and is what lets SimpleChat "
                "list the resource's deployments for you. A key authenticates to inference "
                "only."
            ),
            "default": "key",
            "options": AZURE_OPENAI_AUTH_OPTIONS,
            "depends_on": {"key": "enable_embedding_apim", "equals": False},
        },
        {
            "key": "azure_openai_embedding_subscription_id",
            "type": "text",
            "label": "Subscription ID",
            "help": (
                "Used to address the resource when listing its deployments. Inference does "
                "not need it, so an embedding route can work while the model list stays "
                "empty."
            ),
            "default": "",
            "depends_on": {"key": "enable_embedding_apim", "equals": False},
        },
        {
            "key": "azure_openai_embedding_resource_group",
            "type": "text",
            "label": "Resource Group",
            "help": "The other half of the address the deployment list is fetched from.",
            "default": "",
            "depends_on": {"key": "enable_embedding_apim", "equals": False},
        },
        {
            "key": "azure_openai_embedding_key",
            "type": "secret",
            "label": "Azure OpenAI Embedding Key",
            "help": (
                "Only used with key authentication. Leave it blank to keep the stored key."
            ),
            "default": "",
            # Two conditions, because this control sits inside two nested blocks on the
            # server-rendered page: the direct-connection card and the key-authentication
            # card within it. With only the authentication condition, switching the route
            # to APIM would leave a direct-connection credential on screen.
            "depends_on": [
                {"key": "enable_embedding_apim", "equals": False},
                {"key": "azure_openai_embedding_authentication_type", "equals": "key"},
            ],
        },
        {
            "key": "embedding_model",
            "type": "component",
            "component": "embedding-model-selection",
            "label": "Embedding model",
            "help": (
                "One deployment serves every embedding SimpleChat stores. Changing it does "
                "not re-embed what is already indexed, so existing chunks keep the "
                "dimensions of the model that wrote them."
            ),
            "depends_on": {"key": "enable_embedding_apim", "equals": False},
        },
        {
            "key": "azure_openai_embedding_api_version",
            "type": "text",
            "label": "Azure OpenAI Embedding API Version",
            "help": (
                "Pin this only when a deployment needs a version other than the default; "
                "an unsupported value fails every embedding call rather than degrading."
            ),
            "default": "2024-05-01-preview",
            "depends_on": {"key": "enable_embedding_apim", "equals": False},
        },
        {
            "key": "azure_apim_embedding_endpoint",
            "type": "text",
            "label": "Azure APIM Endpoint",
            "help": "The API Management address that fronts the embedding deployment.",
            "default": "",
            "depends_on": {"key": "enable_embedding_apim", "equals": True},
        },
        {
            "key": "azure_apim_embedding_api_version",
            "type": "text",
            "label": "Azure APIM API Version",
            "help": (
                "Whatever version the API Management operation expects. There is no "
                "default here, because a gateway can publish any version it likes."
            ),
            "default": "",
            "depends_on": {"key": "enable_embedding_apim", "equals": True},
        },
        {
            "key": "azure_apim_embedding_deployment",
            "type": "text",
            "label": "Azure APIM Deployment",
            "help": (
                "The deployment name to send embedding requests to. Discovery does not "
                "reach through a gateway, so this is typed rather than picked."
            ),
            "default": "",
            "depends_on": {"key": "enable_embedding_apim", "equals": True},
        },
        {
            "key": "azure_apim_embedding_subscription_key",
            "type": "secret",
            "label": "Azure APIM Subscription Key",
            "help": "Leave it blank to keep the stored key.",
            "default": "",
            "depends_on": {"key": "enable_embedding_apim", "equals": True},
        },
    ],
    "image-config": [
        {
            "key": "enable_image_generation",
            "type": "switch",
            "label": "Enable Image Generation",
            "help": (
                "Offers image generation in chat. With it off nothing below is consulted, "
                "and the rest of this section stays out of the way."
            ),
            "default": False,
        },
        {
            "key": "enable_image_gen_apim",
            "type": "switch",
            "label": "Use APIM instead of direct to Azure OpenAI endpoint",
            "help": (
                "Sends image requests to API Management rather than straight to the Azure "
                "OpenAI resource. The two routes are configured separately and only the "
                "selected one is used."
            ),
            "default": False,
            "depends_on": {"key": "enable_image_generation", "equals": True},
        },
        {
            "key": "azure_openai_image_gen_endpoint",
            "type": "text",
            "label": "Azure OpenAI Image Generation Endpoint",
            "help": (
                "Image models are deployed separately from chat models and are often in a "
                "different region, so this rarely matches the chat endpoint."
            ),
            "default": "",
            "placeholder": "https://your-resource.openai.azure.com",
            "depends_on": [
                {"key": "enable_image_generation", "equals": True},
                {"key": "enable_image_gen_apim", "equals": False},
            ],
        },
        {
            "key": "azure_openai_image_gen_authentication_type",
            "type": "select",
            "label": "Authentication Type",
            "help": (
                "Managed identity avoids storing a credential and is what lets SimpleChat "
                "list the resource's deployments for you. A key authenticates to inference "
                "only."
            ),
            "default": "key",
            "options": AZURE_OPENAI_AUTH_OPTIONS,
            "depends_on": [
                {"key": "enable_image_generation", "equals": True},
                {"key": "enable_image_gen_apim", "equals": False},
            ],
        },
        {
            "key": "azure_openai_image_gen_subscription_id",
            "type": "text",
            "label": "Subscription ID",
            "help": (
                "Used to address the resource when listing its deployments. Inference does "
                "not need it, so generation can work while the model list stays empty."
            ),
            "default": "",
            "depends_on": [
                {"key": "enable_image_generation", "equals": True},
                {"key": "enable_image_gen_apim", "equals": False},
            ],
        },
        {
            "key": "azure_openai_image_gen_resource_group",
            "type": "text",
            "label": "Resource Group",
            "help": "The other half of the address the deployment list is fetched from.",
            "default": "",
            "depends_on": [
                {"key": "enable_image_generation", "equals": True},
                {"key": "enable_image_gen_apim", "equals": False},
            ],
        },
        {
            "key": "azure_openai_image_gen_key",
            "type": "secret",
            "label": "Azure OpenAI Image Generation Key",
            "help": (
                "Only used with key authentication. Leave it blank to keep the stored key."
            ),
            "default": "",
            # Nested the same way as the embedding key: inside the direct-connection card
            # and the key-authentication card within it.
            "depends_on": [
                {"key": "enable_image_generation", "equals": True},
                {"key": "enable_image_gen_apim", "equals": False},
                {"key": "azure_openai_image_gen_authentication_type", "equals": "key"},
            ],
        },
        {
            "key": "image_gen_model",
            "type": "component",
            "component": "image-model-selection",
            "label": "Image model",
            "help": (
                "The deployment every generated image comes from. Image deployments differ "
                "in the sizes and quality settings they accept, so a change here can alter "
                "what the image tool is able to produce."
            ),
            "depends_on": [
                {"key": "enable_image_generation", "equals": True},
                {"key": "enable_image_gen_apim", "equals": False},
            ],
        },
        {
            "key": "azure_openai_image_gen_api_version",
            "type": "text",
            "label": "Azure OpenAI Image Gen API Version",
            "help": (
                "Image generation moves on its own API schedule, which is why this defaults "
                "later than the chat and embedding versions. Change it only for a "
                "deployment that needs a different one."
            ),
            "default": "2024-12-01-preview",
            "depends_on": [
                {"key": "enable_image_generation", "equals": True},
                {"key": "enable_image_gen_apim", "equals": False},
            ],
        },
        {
            "key": "azure_apim_image_gen_endpoint",
            "type": "text",
            "label": "Azure APIM Endpoint",
            "help": "The API Management address that fronts the image deployment.",
            "default": "",
            "depends_on": [
                {"key": "enable_image_generation", "equals": True},
                {"key": "enable_image_gen_apim", "equals": True},
            ],
        },
        {
            "key": "azure_apim_image_gen_api_version",
            "type": "text",
            "label": "Azure APIM API Version",
            "help": (
                "Whatever version the API Management operation expects. There is no "
                "default here, because a gateway can publish any version it likes."
            ),
            "default": "",
            "depends_on": [
                {"key": "enable_image_generation", "equals": True},
                {"key": "enable_image_gen_apim", "equals": True},
            ],
        },
        {
            "key": "azure_apim_image_gen_deployment",
            "type": "text",
            "label": "Azure APIM Deployment",
            "help": (
                "The deployment name to send image requests to. Discovery does not reach "
                "through a gateway, so this is typed rather than picked."
            ),
            "default": "",
            "depends_on": [
                {"key": "enable_image_generation", "equals": True},
                {"key": "enable_image_gen_apim", "equals": True},
            ],
        },
        {
            "key": "azure_apim_image_gen_subscription_key",
            "type": "secret",
            "label": "Azure APIM Subscription Key",
            "help": "Leave it blank to keep the stored key.",
            "default": "",
            "depends_on": [
                {"key": "enable_image_generation", "equals": True},
                {"key": "enable_image_gen_apim", "equals": True},
            ],
        },
    ],
}


# Maps each schema key to the field name(s) the server-rendered form submits.
# Most match exactly and are omitted. The entries below are the places where the
# two shapes genuinely differ, and the parity test uses them to resolve a V1
# form field to its V2 equivalent.
LEGACY_FIELD_NAMES = {
    # Same shape: the Grounding with Bing terms are accepted on the toggle, and
    # the flag rides along with the save rather than being edited on its own.
    "enable_web_search": ["enable_web_search", "web_search_consent_accepted"],
    # V1 submits four independent checkboxes and assembles the array server-side.
    "user_agreement_apply_to": [
        "user_agreement_apply_personal",
        "user_agreement_apply_group",
        "user_agreement_apply_public",
        "user_agreement_apply_chat",
    ],
    # V1 round-trips the list through a hidden JSON field maintained by script.
    "external_links": ["external_links_json"],
    # Same pattern: V1 posts the default model reference as serialized JSON, while V2
    # writes it through /api/v2/admin/default-model.
    "default_model_selection": ["default_model_selection_json"],
    # V1 posts the images as part of the settings form; V2 uploads them
    # separately, so the stored keys are what the schema names.
    "custom_logo_base64": ["logo_file"],
    "custom_logo_dark_base64": ["logo_dark_file"],
    "custom_favicon_base64": ["favicon_file"],
    # Collected as an acknowledgement on the toggle rather than a stored value.
    "enable_custom_pages": ["enable_custom_pages", "custom_pages_restart_acknowledged"],
    # V1 renders this as an inverted "Disable Group Creation" checkbox and flips it
    # server-side; V2 edits the stored key directly.
    "enable_group_creation": ["disable_group_creation"],
    # V1 round-trips the promoted agent list through a hidden JSON field that its
    # script maintains; V2 edits the stored list directly.
    "agents_page_promoted_popular_agents": ["agents_page_promoted_popular_agents_json"],
    # The inbound MCP allowlists take the same shape: a hidden JSON field in V1.
    "inbound_mcp_allowed_client_app_entries": ["inbound_mcp_allowed_client_app_entries_json"],
    "inbound_mcp_allowed_tenant_entries": ["inbound_mcp_allowed_tenant_entries_json"],
    "inbound_mcp_allowed_source_entries": ["inbound_mcp_allowed_source_entries_json"],
}

# Field names present in the V1 panes covered by a parity test that intentionally
# have no V2 equivalent, with the reason. The parity test reads this, so an
# unexplained omission fails rather than passing silently.
LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT = {
    "source_review_default_mode": (
        "Not a real choice. The V1 control is a permanently disabled select "
        "offering one option, shadowed by a hidden input hard-coded to 'manual', "
        "and get_source_review_config rewrites any other value back to 'manual' "
        "on read. Reproducing it would add a control that cannot be changed and "
        "implies a setting that does not exist. Deep Research states the "
        "behaviour in its description instead."
    ),
    "orchestration_type": (
        "Saved through POST /api/orchestration_settings, not the settings PATCH. "
        "V2 renders it from the agent-orchestration component, which reads the "
        "available types from the server rather than hard-coding them."
    ),
    "max_rounds_per_agent": (
        "Saved through POST /api/orchestration_settings alongside "
        "orchestration_type, and only meaningful for a multi-agent orchestration "
        "type. Owned by the agent-orchestration component."
    ),
}

# Settings the schema declares that the server-rendered page has no control for,
# with the reason it is reasonable for V2 to be ahead. The parity test reads this
# so a V2-only field is a recorded decision rather than an accident.
V2_ONLY_FIELDS = {
    "enable_app_maintenance": (
        "Documented in docs/admin/scale.md but never given a control on the "
        "server-rendered page. Declared here so it stops being guessed into "
        "Security > App Role Requirements by the fallback scan, which matched it "
        "on the shared word stem 'app'."
    ),
    "enable_startup_app_maintenance": (
        "Same as enable_app_maintenance: no server-rendered control, and misfiled "
        "into Security by the fallback scan until it was declared."
    ),
}


# Section-level state, drawn as a pill in the section header.
#
# A section reduced to a list of controls tells an administrator nothing until they
# read every control in it. That is bearable for a section with one switch and
# actively misleading for an integration, where "enabled" and "usable" are different
# things: Content Safety can be on with no endpoint, and Key Vault can be on with no
# vault name, and in both cases the feature is silently doing nothing.
#
# ``enabled_key``
#     The capability toggle. False renders "Off" and nothing else is evaluated.
#
# ``configured``
#     Rules deciding whether an enabled section is actually usable. Each rule
#     applies when every entry in its ``when`` map matches current state, and
#     requires every key in ``requires`` to hold a non-empty value. A rule with no
#     ``when`` always applies. Rules exist rather than a flat key list because the
#     required keys change with configuration: Content Safety needs a direct
#     endpoint or an APIM endpoint depending on how it is routed, never both.
ADMIN_SECTION_STATUS = {
    "keyvault-section": {
        "enabled_key": "enable_key_vault_secret_storage",
        "configured": [{"requires": ["key_vault_name"]}],
    },
    "content-safety-section": {
        "enabled_key": "enable_content_safety",
        "configured": [
            {
                "when": {"enable_content_safety_apim": False},
                "requires": ["content_safety_endpoint"],
            },
            {
                "when": {"enable_content_safety_apim": True},
                "requires": ["azure_apim_content_safety_endpoint"],
            },
        ],
    },
    "front-door-section": {
        "enabled_key": "enable_front_door",
        "configured": [{"requires": ["front_door_url"]}],
    },
    "idle-timeout-section": {
        "enabled_key": "enable_idle_timeout",
    },
    "rate-limit-message-section": {
        "enabled_key": "enable_custom_rate_limit_message",
        "configured": [{"requires": ["rate_limit_message"]}],
    },
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


def get_admin_settings_fields():
    """Return the section-id keyed field schema."""
    return ADMIN_SETTINGS_FIELDS


def get_admin_section_status():
    """Return the section-id keyed status descriptors."""
    return ADMIN_SECTION_STATUS


def iter_fields():
    """Yield ``(section_id, field)`` for every declared field."""
    for section_id, fields in ADMIN_SETTINGS_FIELDS.items():
        for field in fields:
            yield section_id, field


def get_field_definition(key):
    """Return the field definition for a settings key, or None.

    A key may be declared twice: once where it is edited, and once as a read-only
    mirror in a section that only needs to report its state. Fact memory is
    edited under Chat but affects which actions an agent has, so it appears in
    both. The writable declaration is the one that governs saving, so it wins
    regardless of declaration order.
    """
    mirror = None
    for _section_id, field in iter_fields():
        if field.get("key") != key:
            continue
        if field.get("readonly"):
            mirror = mirror or field
            continue
        return field
    return mirror


def get_declared_setting_keys():
    """Return every settings key the schema describes.

    The V2 surface uses this to suppress its ``enable_*`` fallback scan for keys
    that already have a proper field, so a toggle is never rendered twice.
    """
    return {field["key"] for _section_id, field in iter_fields() if field.get("key")}


def get_suppressed_capability_keys():
    """Return the keys the V2 fallback scan must not render a switch for."""
    return sorted(SUPPRESSED_CAPABILITY_KEYS)


def get_secret_field_keys():
    """Return the settings keys declared as secrets.

    The browser is handed a placeholder for each of these instead of the stored
    value, so the route applying a save has to know which submitted values may be
    that placeholder rather than a real new secret.
    """
    return {
        field["key"]
        for _section_id, field in iter_fields()
        if field.get("type") == "secret" and field.get("key")
    }


def iter_field_dependencies(field):
    """Yield each ``depends_on`` condition on a field.

    A field may declare one condition or a list of them; a list means every
    condition has to hold. Both shapes are read through here so callers never have
    to care which was written. A list is needed wherever a control is gated on a
    sibling whose own default would otherwise reveal it -- the Enhanced Citations
    storage credentials are chosen by authentication type, but must stay hidden
    entirely while Enhanced Citations itself is off.
    """
    dependency = field.get("depends_on")
    if not dependency:
        return
    if isinstance(dependency, dict):
        yield dependency
        return
    for condition in dependency:
        yield condition


def _dependency_is_satisfied(condition, settings):
    """Whether one ``depends_on`` condition holds against a settings mapping."""
    if not condition.get("key"):
        # A condition naming a runtime flag is resolved in the browser from the
        # flags the settings API sends. The server has no settings key to read,
        # and treating it as unmet here would suppress validation for every field
        # behind a preview gate.
        return True
    expected = condition.get("equals", True)
    current = settings.get(condition["key"])
    if isinstance(expected, bool):
        return _coerce_bool(current) is expected
    return str(current if current is not None else "") == str(expected)


def field_dependencies_are_satisfied(field, settings):
    """Whether every ``depends_on`` condition on a field holds."""
    return all(
        _dependency_is_satisfied(condition, settings)
        for condition in iter_field_dependencies(field)
    )


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

    # A list means every condition has to hold. It is the shorthand the Security
    # and Workspaces sections declare, and is equivalent to ``all_of``.
    if isinstance(dependency, list):
        return all(evaluate_dependency(nested, read_value) for nested in dependency)

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




def _validate_front_door_url(value):
    """Return ``(url, error)`` for the Front Door origin.

    Every sign-in redirect is built from this value, so a path, a query or a
    missing scheme produces redirects that fail authentication rather than merely
    looking untidy. The server-rendered form blanks a bad value and flashes a
    message; refusing the save says the same thing without the administrator
    having to notice the field emptied itself.
    """
    candidate = str(value or "").strip().rstrip("/")
    if not candidate:
        return "", None

    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in FRONT_DOOR_ALLOWED_SCHEMES:
        allowed = " or ".join(f"{scheme}://" for scheme in FRONT_DOOR_ALLOWED_SCHEMES)
        return None, f"URL must start with {allowed}."
    if not parsed.netloc:
        return None, "URL is missing a host."
    if parsed.path or parsed.query or parsed.fragment:
        return None, "Enter the origin only, with no path or query string."
    return candidate, None


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

    Two sets of descriptors are honoured because the two admin groups introduced
    them separately and both are in use: ``entry_pattern``/``entry_label`` and
    ``max_entries`` validate the URL Access domain lists, while
    ``max_item_length`` and ``fallback_when_empty`` bound the Key Vault reminder
    roles and restore their default when the list is emptied.
    """
    if isinstance(value, list):
        candidates = [str(item or "") for item in value]
    else:
        candidates = re.split(r"[\n,;]+", str(value if value is not None else ""))

    # `entry_max_length` and `max_item_length` name the same cap. The default is
    # generous enough for a fully qualified domain, which is the longest thing
    # any declared list holds.
    max_length = field.get("entry_max_length", field.get("max_item_length", 253))

    entries = []
    seen = set()
    for candidate in candidates:
        # Collapse internal whitespace as well as trimming, so a value pasted out
        # of a document does not become a distinct entry from the typed one.
        entry = " ".join(candidate.split())
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
        entries.append(entry[:max_length])

    maximum = field.get("max_entries")
    if maximum is not None and len(entries) > maximum:
        return None, f"Enter at most {maximum} entries."

    if not entries and field.get("fallback_when_empty"):
        # Emptying the list means "use the default" rather than "allow nobody",
        # which for the Key Vault reminder roles would silence the reminders.
        entries = list(field.get("default") or [])

    return entries, None


def _normalize_id_list(value, field):
    """Return ``(ids, error)`` for a list of assigned group or workspace ids.

    What counts as a valid id depends on the record being assigned, and the two
    cases genuinely differ in the application:

    ``id_kind: "group"``
        Delegated to ``normalize_group_workflow_allowed_group_ids``, which is what
        ``functions_settings.normalize_file_download_allowed_group_ids`` calls. It
        requires a canonical group UUID and silently drops anything else, so
        normalizing here instead would let V2 store an id the server-rendered form
        would have discarded.

    ``id_kind: "opaque"``
        Public workspace ids are not UUID-constrained --
        ``normalize_file_sync_allowed_public_workspace_ids`` only trims and
        deduplicates -- so imposing a UUID check would reject valid assignments.

    The delegation is possible because ``functions_group_assignment_ids`` was split
    out of ``functions_settings`` precisely so this module can reach it: the parent
    builds a Cosmos client at import time and is stubbed by the functional tests.

    A string is also accepted. The server-rendered File Sync pane round-trips these
    lists through a hidden textarea holding a JSON array, so a value read back from
    a document that form wrote arrives serialized rather than as a list.
    """
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return [], None
        try:
            value = json.loads(stripped)
        except ValueError:
            return None, "Expected a list of ids."

    if not isinstance(value, list):
        return None, "Expected a list of ids."

    if field.get("id_kind") == "group":
        return normalize_group_workflow_allowed_group_ids(value), None

    ids = []
    seen = set()
    for item in value:
        # The assignment picker holds records, not bare ids.
        if isinstance(item, dict):
            item = item.get("id")
        candidate = str(item or "").strip()
        if not candidate or candidate in seen:
            continue
        ids.append(candidate)
        seen.add(candidate)

    maximum = field.get("max_entries")
    if maximum is not None and len(ids) > maximum:
        return None, f"Assign at most {maximum} entries."

    return ids, None
def _normalize_promoted_popular_agents(value):
    """Normalize the Agents page promotion list.

    Imported lazily, and documented here as the exception to the imports-at-top
    rule: ``functions_settings`` reaches ``config.py``, which builds a Cosmos
    client at import time, so importing it at module scope would make this
    schema module unimportable in a plain test process.
    """
    from functions_settings import normalize_agents_page_promoted_popular_agents

    return normalize_agents_page_promoted_popular_agents(value)


def _normalize_document_action_capabilities(value):
    """Normalize the assembled document action capabilities container.

    Lazily imported for the same reason as above.
    """
    from functions_document_actions import normalize_document_action_capabilities

    return normalize_document_action_capabilities({"document_action_capabilities": value})


# Containers assembled from several ``settings_path`` fields, and the function
# that already owns validating the whole object. Bounds live there, so a limit
# typed into either admin surface is clamped the same way.
_CONTAINER_NORMALIZERS = {
    "document_action_capabilities": _normalize_document_action_capabilities,
}


def _normalize_entry_list(value):
    """Normalize a ``{value, description}`` allowlist.

    Delegated to ``functions_mcp_server_config`` so both admin surfaces agree on
    what a row is worth keeping. Imported lazily for the reason given above.
    """
    from functions_mcp_server_config import normalize_inbound_mcp_value_entries

    return normalize_inbound_mcp_value_entries(value)


def _apply_inbound_mcp_derivations(normalized, current_settings):
    """Write the flat lists the inbound MCP runtime reads.

    The runtime does not read the ``*_entries`` lists an administrator edits. It
    reads ``*_ids`` lists, and single-role settings are mirrored into
    ``*_roles`` arrays. The server-rendered form derives all of those on every
    save; without the same derivation here, an allowlist edited in V2 would be
    stored and then ignored.

    The rules are not a straight mapping, which is why this reproduces the whole
    block rather than a per-key transform: the tenant list only takes effect when
    additional tenants are allowed and always gains the deployment's own tenant,
    and the source list collapses to ``*`` when all sources are allowed.
    """
    if not any(key.startswith("inbound_mcp_") for key in normalized):
        return

    from functions_mcp_server_config import (
        INBOUND_MCP_SETTINGS_DEFAULTS,
        ensure_inbound_mcp_default_tenant_entry,
        inbound_mcp_entry_values,
        normalize_inbound_mcp_single_value,
        normalize_inbound_mcp_value_entries,
    )

    def merged(key):
        """The value this save will leave behind, edited or not."""
        if key in normalized:
            return normalized[key]
        if key in current_settings:
            return current_settings[key]
        return INBOUND_MCP_SETTINGS_DEFAULTS.get(key)

    for role_key, roles_key in (
        ("inbound_mcp_required_user_role", "inbound_mcp_required_user_roles"),
        ("inbound_mcp_required_app_role", "inbound_mcp_required_app_roles"),
    ):
        if role_key not in normalized:
            continue
        role = normalize_inbound_mcp_single_value(
            normalized[role_key],
            default_value=INBOUND_MCP_SETTINGS_DEFAULTS[role_key],
            max_length=128,
        )
        normalized[role_key] = role
        normalized[roles_key] = [role] if role else []

    if "inbound_mcp_allowed_client_app_entries" in normalized:
        entries = normalize_inbound_mcp_value_entries(
            normalized["inbound_mcp_allowed_client_app_entries"], lowercase=True
        )
        normalized["inbound_mcp_allowed_client_app_entries"] = entries
        normalized["inbound_mcp_allowed_client_app_ids"] = inbound_mcp_entry_values(
            entries, lowercase=True
        )

    if (
        "inbound_mcp_allowed_tenant_entries" in normalized
        or "inbound_mcp_allow_external_tenants" in normalized
    ):
        entries = normalize_inbound_mcp_value_entries(
            merged("inbound_mcp_allowed_tenant_entries"), lowercase=True
        )
        if _coerce_bool(merged("inbound_mcp_allow_external_tenants")):
            entries = ensure_inbound_mcp_default_tenant_entry(entries)
            tenant_ids = inbound_mcp_entry_values(entries, lowercase=True)
        else:
            # Restricting to the deployment's own tenant is expressed by the id
            # list, not by clearing the entries, so a partner tenant an admin
            # added is still there when they turn the switch back on.
            from config import TENANT_ID

            own_tenant = str(TENANT_ID or "").strip().lower()
            tenant_ids = [own_tenant] if own_tenant else []
        normalized["inbound_mcp_allowed_tenant_entries"] = entries
        normalized["inbound_mcp_allowed_tenant_ids"] = tenant_ids

    if (
        "inbound_mcp_allowed_source_entries" in normalized
        or "inbound_mcp_allow_all_source_ids" in normalized
    ):
        allow_all = _coerce_bool(merged("inbound_mcp_allow_all_source_ids"))
        entries = normalize_inbound_mcp_value_entries(
            merged("inbound_mcp_allowed_source_entries"),
            default=(
                INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_allowed_source_entries"]
                if allow_all
                else None
            ),
        )
        if not allow_all:
            # The wildcard row belongs to the allow-all mode. Leaving it in a
            # controlled list would silently keep accepting every source.
            entries = [entry for entry in entries if entry.get("value") != "*"]
        normalized["inbound_mcp_allowed_source_entries"] = entries
        normalized["inbound_mcp_allowed_source_ids"] = (
            ["*"] if allow_all else inbound_mcp_entry_values(entries)
        )




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
    "content_safety_violation_message": lambda value, field: (
        normalize_content_safety_violation_message(value)
    ),
    "rate_limit_message": lambda value, field: normalize_rate_limit_message(value),
    # Declared as a component field, so it never reaches the type-driven
    # normalization below and would otherwise be written through unvalidated.
    "agents_page_promoted_popular_agents": lambda value, field: (
        _normalize_promoted_popular_agents(value)
    ),
}


def _normalize_field_value(key, value, field):
    """Return ``(normalized, error, warning)`` for one declared field."""
    field_type = field.get("type")

    if field_type in NON_PATCHABLE_TYPES:
        return None, f"{key} cannot be changed through this endpoint.", None

    if field.get("readonly"):
        # A mirror reports a value that something else owns. Accepting a write
        # here would let the Actions surface set a Chat capability, or set a key
        # the application recomputes on every read.
        owner = field.get("managed_by")
        return None, (
            f"{key} is managed by {owner}." if owner
            else f"{key} cannot be changed through this endpoint."
        ), None

    if field_type == "switch":
        return _coerce_bool(value), None, None

    if field_type == "secret":
        # Whitespace only, and no length cap: the value is an opaque credential,
        # and the placeholder standing in for a stored secret is resolved by the
        # route that holds the settings document, not here.
        #
        # One exception. That route resolves by settings key, and a field declaring
        # `paths` is folded into its containing object by _apply_nested_paths before
        # the route ever sees it -- the Foundry client secret arrives as part of
        # `web_search_agent`, never as a key of its own. The route cannot reach it,
        # so an untouched placeholder has to be dropped here or it would be written
        # over the stored credential.
        secret = str(value if value is not None else "").strip()
        if field.get("paths") and secret == SECRET_REDACTED_VALUE:
            return SECRET_UNCHANGED, None, None
        return secret, None, None

    if field_type == "string_list":
        items, error = _normalize_string_list(value, field)
        return items, error, None

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
        if error:
            return None, error, None
        # A field may be edited in one unit and stored in another -- File Sync's
        # per-run limit is entered in GB and stored in bytes. Bounds are declared
        # in the editing unit, so scaling happens after clamping.
        scale = field.get("scale")
        if scale:
            number = int(number * scale)
        return number, None, None

    if field_type == "checkbox_set":
        selection, error = _normalize_checkbox_set(value, field)
        return selection, error, None

    if field_type == "string_list":
        entries, error = _normalize_string_list(value, field)
        return entries, error, None

    if field_type == "entry_list":
        return _normalize_entry_list(value), None, None

    if field_type == "id_list":
        ids, error = _normalize_id_list(value, field)
        return ids, error, None

    if field_type == "group_picker":
        # Delegated so an assignment saved from V2 is byte-for-byte what the
        # server-rendered form would have stored, including how it drops ids that
        # are not canonical group UUIDs.
        return normalize_group_workflow_allowed_group_ids(value), None, None

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
    """Move values to where they are actually stored, when that is not their own key.

    Most settings are top-level keys, so the normalized dict can be handed
    straight to ``update_settings``. Three cases are not, and two different
    descriptors express them because the two admin surfaces grew them
    separately:

    ``paths`` names one or more dotted destinations. A value assembled into a
    nested object -- the server-rendered form builds the Web Search Foundry
    connection into a single ``web_search_agent`` object -- or mirrored into
    more than one key, as URL Access domain lists are stored twice, once under
    ``url_access_*`` and once under ``source_review_*``. Writing only one leaves
    Deep Research reading the stale copy.

    ``settings_path`` names a single destination as a list of segments.
    ``document_action_capabilities`` holds six values across two action types,
    and nothing reads a flattened form of them, so writing the flat keys through
    would save a setting the application never looks at.

    Either way the container is rebuilt from the stored object and handed back
    whole, because ``update_settings`` merges at the top level only. Writing just
    the changed leaf would replace the object and drop its siblings, so editing
    the Foundry endpoint would silently discard the agent id and the credentials.
    """
    containers = {}

    # `settings_path`: a list of segments naming one destination.
    for key in list(normalized):
        field = get_field_definition(key)
        path = (field or {}).get("settings_path")
        if not path:
            continue

        value = normalized.pop(key)
        root = path[0]
        if root not in containers:
            stored = current_settings.get(root)
            containers[root] = copy.deepcopy(stored) if isinstance(stored, dict) else {}

        node = containers[root]
        for segment in path[1:-1]:
            child = node.get(segment)
            if not isinstance(child, dict):
                child = {}
                node[segment] = child
            node = child
        node[path[-1]] = value

    # `paths`: one or more dotted destinations, possibly mirroring to several.
    nested_fields = get_nested_path_fields()
    pending = {
        key: normalized.pop(key) for key in list(normalized) if key in nested_fields
    }
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
        # Two registries, because the two descriptors were introduced with
        # different normalizer signatures: one reports warnings back to the
        # caller, the other validates the whole object and returns it.
        path_normalizer = PATH_CONTAINER_NORMALIZERS.get(root)
        if path_normalizer:
            container, container_warnings = path_normalizer(container, current_settings)
            if warnings is not None:
                warnings.update(container_warnings)

        container_normalizer = _CONTAINER_NORMALIZERS.get(root)
        if container_normalizer:
            container = container_normalizer(container)

        normalized[root] = container

    return normalized


def _validate_identity_header_name(value):
    """Return ``(normalized, error)`` for the model endpoint identity header name.

    ``normalize_model_endpoint_identity_header_name`` answers "" for a name that
    collides with a header the model call already sets, such as ``authorization`` or
    ``api-key``. Storing that silently would turn the header off without saying so, so
    an explicit save reports the refusal instead.
    """
    candidate = str(value or "").strip()
    if not candidate:
        return DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_NAME, None

    normalized = normalize_model_endpoint_identity_header_name(candidate)
    if not normalized:
        return None, (
            "That header name is reserved or malformed. Use a token such as "
            f"{DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_NAME}."
        )
    return normalized, None


def _validate_multi_model_endpoint_enablement(value, current_settings):
    """Return ``(normalized, error)`` for the connections capability toggle.

    ``update_settings`` runs this key through ``coerce_multi_model_endpoint_enablement``,
    which is ``existing or requested`` -- so once connections are on they cannot be turned
    off. The classic form reflects that by rendering the checkbox only while the flag is
    off. The V2 surface has no such affordance, so without this an administrator could
    switch it off, be told the save succeeded, and be shown the toggle in its new position,
    while chat carried on routing through connections.
    """
    requested = _coerce_bool(value)
    already_on = _coerce_bool(current_settings.get("enable_multi_model_endpoints", False))

    if already_on and not requested:
        return None, (
            "Connections cannot be switched off once enabled, because existing chats, "
            "agents and workflows may already reference a model published from one."
        )
    return requested, None


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

        # Delegated keys are normalized by the function that already owns them,
        # whatever their field type. This runs before the field lookup so a
        # component-backed key such as the Agents page promotion list is still
        # validated rather than written straight through.
        if key in _DELEGATED_NORMALIZERS:
            normalized[key] = _DELEGATED_NORMALIZERS[key](value, field)
            continue

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

        if key == "model_endpoint_identity_header_name":
            header_value, header_error = _validate_identity_header_name(value)
            if header_error:
                errors[key] = header_error
            else:
                normalized[key] = header_value
            continue

        if key == "enable_multi_model_endpoints":
            enablement, enablement_error = _validate_multi_model_endpoint_enablement(
                value, current
            )
            if enablement_error:
                errors[key] = enablement_error
            else:
                normalized[key] = enablement
            continue

        if key == "front_door_url":
            front_door_value, front_door_error = _validate_front_door_url(value)
            if front_door_error:
                errors[key] = front_door_error
            else:
                normalized[key] = front_door_value
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

    # Same reasoning for settings that constrain each other: the pair may be edited
    # together or one at a time, so the merged state is the only thing worth
    # judging.
    _apply_cross_field_rules(normalized, current, warnings)

    # Folded last so the checks above still see the flat keys they were written
    # against, and so a rejected save never assembles a container.
    if not errors:
        _apply_nested_paths(normalized, current)
        _apply_inbound_mcp_derivations(normalized, current)

    return normalized, errors, warnings


def _apply_cross_field_rules(normalized, current_settings, warnings):
    """Reconcile settings whose valid range depends on another setting.

    Only the idle warning needs this today. It has to arrive before the sign-out it
    warns about, and the two are separate fields that can be saved independently,
    so the check cannot live on either field's own definition. The server-rendered
    form silently lowers the warning to match; doing the same and saying so is
    kinder than rejecting a save over a value the administrator did not touch.
    """
    if "idle_warning_minutes" not in normalized and "idle_timeout_minutes" not in normalized:
        return

    def merged(key, fallback):
        if key in normalized:
            return normalized[key]
        stored = current_settings.get(key)
        return fallback if stored is None else stored

    try:
        timeout = int(merged("idle_timeout_minutes", 30))
        warning = int(merged("idle_warning_minutes", 28))
    except (TypeError, ValueError):
        return

    if warning <= timeout:
        return

    normalized["idle_warning_minutes"] = timeout
    warnings["idle_warning_minutes"] = (
        f"Lowered to {timeout} minutes, because a warning cannot arrive after the "
        "sign-out it warns about."
    )


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
