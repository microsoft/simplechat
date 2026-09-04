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

The Appearance and Security groups are described in full. Sections with no entry
here fall back to the V2 surface's ``enable_*`` scan, so undescribed groups keep
working exactly as they did. A handful of individual fields outside those groups
are also declared: that scan places a key by guessing from shared word stems, and
declaring a field is the only way to stop it guessing wrong.

Secrets are declared with the ``secret`` type but are *not* resolved here. The
browser is sent a placeholder rather than the stored value, and swapping the
placeholder back for what is stored is a persistence concern that belongs with the
route holding the current settings document -- which is where the server-rendered
form does it too. This module only reports which keys are secrets, through
``get_secret_field_keys``.
"""

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
    "note",
    "image",
    "link_list",
    "component",
)

# Types that own their persistence outside the settings PATCH: image uploads go
# through the multipart branding endpoint, components talk to their own API, and a
# note is standing prose with no value behind it.
NON_PATCHABLE_TYPES = ("image", "component", "note")

# ``input_type`` values a text field may ask the browser for. Anything else would
# reach the DOM unvalidated, so the schema test rejects it.
TEXT_INPUT_TYPES = ("text", "email", "url")

# Tones a note may carry. ``warning`` is for consequences that cannot be undone;
# everything explanatory is ``info``.
NOTE_TONES = ("info", "warning")

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
    # ------------------------------------------------------------------
    # Security > Access & Roles
    # ------------------------------------------------------------------
    "permissions-section": [
        {
            "key": "require_member_of_safety_violation_admin",
            "type": "switch",
            "label": "Require the SafetyViolationAdmin app role",
            "help": (
                "Restricts the Safety Violations report to accounts holding the "
                "SafetyViolationAdmin Enterprise App role. Leave this off and any "
                "account with the general Admin role can open the report. Assign the "
                "role before enabling this, or the report becomes unreachable."
            ),
            "default": False,
        },
        {
            "key": "require_member_of_feedback_admin",
            "type": "switch",
            "label": "Require the FeedbackAdmin app role",
            "help": (
                "Restricts the User Feedback report to accounts holding the "
                "FeedbackAdmin Enterprise App role. Leave this off and any account "
                "with the general Admin role can open the report."
            ),
            "default": False,
        },
        {
            "type": "note",
            "tone": "info",
            "label": "User Feedback is currently off",
            "body": (
                "The FeedbackAdmin role only gates the User Feedback report, so "
                "requiring it changes nothing until User Feedback is enabled under "
                "Chat > Feedback & Alerts."
            ),
            # Shown only while the capability it depends on is off, which is the one
            # state where the switch above has no observable effect.
            "depends_on": {"key": "enable_user_feedback", "equals": False},
        },
    ],
    "app-role-requirements-section": [
        {
            "type": "component",
            "component": "app-role-requirements",
            "label": "App role requirements",
            "help": (
                "Every setting that can require an Entra app role, with the role value "
                "to assign and what changes when it is enforced. Each switch is the "
                "same setting shown on its own tab."
            ),
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
    # ------------------------------------------------------------------
    # Security > Secrets
    # ------------------------------------------------------------------
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
            "default": False,
        },
        {
            "type": "note",
            "tone": "warning",
            "group": "Vault connection",
            "label": "Enabling this is effectively one-way",
            "body": (
                "Secrets saved after this point live in Key Vault and are referenced "
                "by name. Turning it back off leaves those references pointing at "
                "values the application can no longer read, which breaks every agent "
                "and action that depends on them."
            ),
            "depends_on": {"key": "enable_key_vault_secret_storage", "equals": True},
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
            "type": "note",
            "tone": "info",
            "group": "Expiration reminders",
            "label": "SimpleChat does not send the emails",
            "body": (
                "Reminders are raised in-app and emitted as the Application Insights "
                "event key_vault_expiration_reminder_triggered. To email anyone, "
                "point an Azure Monitor scheduled query alert, Logic App, Function or "
                "webhook at that event, and configure the vault's own expiry alerts "
                "in Azure Monitor or Event Grid as well."
            ),
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
    # ------------------------------------------------------------------
    # Security > Content Safety
    # ------------------------------------------------------------------
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
    # ------------------------------------------------------------------
    # Security > Session
    # ------------------------------------------------------------------
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
    # ------------------------------------------------------------------
    # Security > Network
    # ------------------------------------------------------------------
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
    # ------------------------------------------------------------------
    # Security > Rate Limiting
    # ------------------------------------------------------------------
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
    # ------------------------------------------------------------------
    # Scale > Cosmos
    #
    # Declared so they stop being guessed into Security > App Role Requirements,
    # where the fallback scan filed them on the shared word stem "app". Neither has
    # a control on the server-rendered page; this is the first place an
    # administrator can see or change them.
    # ------------------------------------------------------------------
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
}

# Field names present in the V1 panes covered by a parity test that intentionally
# have no V2 equivalent, with the reason. The parity test reads this, so an
# unexplained omission fails rather than passing silently.
LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT = {}

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
        return str(value if value is not None else "").strip(), None, None

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
        if warning:
            warnings[key] = warning
        normalized[key] = field_value

    _check_acknowledgements(updates, current, errors)

    # "At least one" style constraints can only be judged once the whole payload
    # is known, because the capability toggle and its selection may arrive apart.
    _check_minimum_selections(normalized, current, errors)

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
    merged = {**current_settings, **normalized}

    for _section_id, field in iter_fields():
        key = field.get("key")
        minimum = field.get("min_selected")
        if not key or not minimum:
            continue

        # A hidden field is not one the administrator declined to fill in, so a
        # gated selection is only judged while its gate is open.
        if not field_dependencies_are_satisfied(field, merged):
            continue

        selection = (
            normalized[key] if key in normalized else current_settings.get(key) or []
        )
        if len(selection) < minimum:
            errors[key] = f"Select at least {minimum} option."

