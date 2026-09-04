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

Only the Appearance and Agents & Actions groups are described in full so far.
Sections with no entry here fall back to the V2 surface's ``enable_*`` scan, so
undescribed groups keep working exactly as they did. A handful of individual
fields outside those groups are also declared: that scan places a key by guessing
from shared word stems, and declaring a field is the only way to stop it guessing
wrong.
"""

import copy
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
    "entry_list",
    "component",
)

# Types that own their persistence outside the settings PATCH: image uploads go
# through the multipart branding endpoint, and components talk to their own API.
NON_PATCHABLE_TYPES = ("image", "component")

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

# Document action limits, mirrored from DOCUMENT_ACTION_LIMIT_BOUNDS and
# DEFAULT_DOCUMENT_ACTION_CAPABILITIES in functions_document_actions.py. That
# module cannot be imported here -- it reaches config.py, which builds a Cosmos
# client at import time -- so the values are restated and pinned by
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
    # Declared so the Actions surface keeps the editable Fact Memory control where
    # it belongs. Without it the mirror above would claim the key and remove the
    # real toggle from Chat.
    "fact-memory-section": [
        {
            "key": "enable_fact_memory_plugin",
            "type": "switch",
            "label": "Enable Fact Memory",
            "help": (
                "Saved memories are recalled during chat, and can be created or "
                "removed when a user asks. Instruction memories apply to every "
                "prompt; fact memories are recalled only when relevant. This is a "
                "chat capability and does not require agents."
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
    # V1 round-trips the promoted agent list through a hidden JSON field that its
    # script maintains; V2 edits the stored list directly.
    "agents_page_promoted_popular_agents": ["agents_page_promoted_popular_agents_json"],
    # The inbound MCP allowlists take the same shape: a hidden JSON field in V1.
    "inbound_mcp_allowed_client_app_entries": ["inbound_mcp_allowed_client_app_entries_json"],
    "inbound_mcp_allowed_tenant_entries": ["inbound_mcp_allowed_tenant_entries_json"],
    "inbound_mcp_allowed_source_entries": ["inbound_mcp_allowed_source_entries_json"],
}

# Field names present in the V1 panes that intentionally have no V2 equivalent,
# with the reason. The parity tests read this, so an unexplained omission fails
# rather than passing silently.
LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT = {
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


def get_admin_settings_fields():
    """Return the section-id keyed field schema."""
    return ADMIN_SETTINGS_FIELDS


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


def get_legacy_field_names():
    """Return the V1 form field names claimed by the schema."""
    claimed = set()
    for _section_id, field in iter_fields():
        key = field.get("key")
        if not key:
            continue
        claimed.update(LEGACY_FIELD_NAMES.get(key, [key]))
    return claimed


def iter_dependencies(field):
    """Yield each ``depends_on`` condition a field declares.

    ``depends_on`` started as a single condition and most fields still use one.
    A chain such as Agents -> Workspace Mode -> merge behaviour needs every link
    checked, otherwise a field reappears whenever an intermediate toggle is off
    but its own gate happens to be on, so a list is accepted too.
    """
    dependency = field.get("depends_on")
    if not dependency:
        return
    if isinstance(dependency, dict):
        yield dependency
        return
    for entry in dependency:
        if isinstance(entry, dict):
            yield entry


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


def _apply_nested_paths(normalized, current_settings):
    """Fold ``settings_path`` values into the container key they belong to.

    A few settings are stored as one nested object rather than as top-level
    keys. ``document_action_capabilities`` holds six values across two action
    types, and nothing reads a flattened form of them, so writing the flat keys
    through would save a setting the application never looks at.

    The container is rebuilt from the stored object so that saving one limit does
    not discard the other five, then handed to the function that owns it.
    """
    containers = {}

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

    for root, value in containers.items():
        container_normalizer = _CONTAINER_NORMALIZERS.get(root)
        normalized[root] = container_normalizer(value) if container_normalizer else value


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

    if field_type == "entry_list":
        return _normalize_entry_list(value), None, None

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

    # Folded last so the checks above still see the flat keys they were written
    # against, and so a rejected save never assembles a container.
    if not errors:
        _apply_nested_paths(normalized, current)
        _apply_inbound_mcp_derivations(normalized, current)

    return normalized, errors, warnings


def _check_minimum_selections(normalized, current_settings, errors):
    """Enforce ``min_selected`` once the merged state of a save is known."""
    for _section_id, field in iter_fields():
        key = field.get("key")
        minimum = field.get("min_selected")
        if not key or not minimum:
            continue

        gated_off = False
        for depends_on in iter_dependencies(field):
            gate_key = depends_on.get("key")
            if not gate_key:
                # A runtime-flag condition is resolved in the browser; the server
                # cannot judge it here and does not need to.
                continue
            gate_value = (
                normalized[gate_key] if gate_key in normalized
                else current_settings.get(gate_key, False)
            )
            expected = depends_on.get("equals", True)
            actual = (
                _coerce_bool(gate_value)
                if isinstance(expected, bool)
                else str(gate_value or "")
            )
            if actual != expected:
                gated_off = True
                break
        if gated_off:
            continue

        selection = (
            normalized[key] if key in normalized else current_settings.get(key) or []
        )
        if len(selection) < minimum:
            errors[key] = f"Select at least {minimum} option."
