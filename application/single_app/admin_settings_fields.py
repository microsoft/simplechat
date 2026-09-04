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

The Appearance, Workflow, Workspaces, Security and Knowledge groups are
described in full. Sections with no entry here fall back to the V2 surface's
``enable_*`` scan, so undescribed groups keep working exactly as they did. A
handful of individual fields outside those groups are also declared: that scan
places a key by guessing from shared word stems, and declaring a field is the
only way to stop it guessing wrong, and the only way a ``require_member_of_*``
setting appears in V2 at all. Workflow had the opposite problem -- none of its
settings are named ``enable_*``, so the scan had nothing to guess with and the
group rendered empty.

Secrets are declared with the ``secret`` type. The browser is sent a placeholder
rather than the stored value, so the module reports which keys are secrets --
through ``get_secret_field_keys`` and ``get_secret_storage_paths`` -- and the
normalizer drops a submitted placeholder rather than writing it, which is what
stops an unrelated save from overwriting every stored credential.
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
from functions_content_safety import (
    CONTENT_SAFETY_VIOLATION_MESSAGE_MAX_LENGTH,
    normalize_content_safety_violation_message,
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
    "component",
    "secret",
    "string_list",
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

# ``input_type`` values a text field may ask the browser for. Anything else would
# reach the DOM unvalidated, so the schema test rejects it.
TEXT_INPUT_TYPES = ("text", "email", "url")


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
# Above this many automatic tool calls per workflow run, a run is capacity
# sensitive rather than merely long. The server-rendered pane says so in a
# warning block, so the same guidance is attached to the field here.
WORKFLOW_AUTO_INVOKE_CAPACITY_THRESHOLD = 100

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
    # Relocated from Knowledge > Audio & Video, where it was the first control in
    # the AI Voice Conversations card, above the Azure Speech Service
    # configuration. It plays a bundled local sound and, as its own help text
    # says, needs no Speech resource at all. Notifications are what it belongs
    # with. V1 keeps it where it is; declaring the key here removes it from the
    # V2 fallback scan, so it cannot render in both places.
    "desktop-notifications-section": [
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
            "key": "require_member_of_chat_file_upload_user",
            "type": "switch",
            "label": "Require ChatFileUploadUser App Role",
            "help": (
                "Narrows attaching files to a chat message to holders of the "
                "ChatFileUploadUser app role. Attachments already in a conversation "
                "stay readable; this governs new uploads only."
            ),
            "default": False,
        },
    ],
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
            "depends_on": {
                "key": "require_group_assignment_for_file_downloads",
                "equals": True,
            },
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
            "depends_on": {
                "key": "require_public_workspace_assignment_for_file_downloads",
                "equals": True,
            },
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
            "depends_on": {
                "key": "require_group_assignment_for_group_workflows",
                "equals": True,
            },
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
    # V1 renders this as an inverted "Disable Group Creation" checkbox and flips it
    # server-side; V2 edits the stored key directly.
    "enable_group_creation": ["disable_group_creation"],
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
    to care which was written.
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


def _normalize_string_list(value, field):
    """Return ``(items, error)`` for a comma-separated list of short tokens.

    Accepts the list the V2 control sends and the comma string the server-rendered
    form stores, because both shapes already exist in saved settings documents.
    """
    if isinstance(value, str):
        raw_items = value.replace(";", ",").split(",")
    elif isinstance(value, list):
        raw_items = value
    elif value is None:
        raw_items = []
    else:
        return None, "Expected a list of values."

    max_item_length = field.get("max_item_length", 80)
    items = []
    for raw_item in raw_items:
        item = " ".join(str(raw_item or "").split())[:max_item_length]
        if item and item not in items:
            items.append(item)

    if not items and field.get("fallback_when_empty"):
        items = list(field.get("default") or [])
    return items, None


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
