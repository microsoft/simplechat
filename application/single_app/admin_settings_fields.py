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

Only the Appearance, Workflow and Workspaces groups are described in full so far.
Sections with no entry here fall back to the V2 surface's ``enable_*`` scan, so
undescribed groups keep working exactly as they did. A handful of individual
fields outside those groups are also declared: that scan places a key by guessing
from shared word stems, and declaring a field is the only way to stop it guessing
wrong, and the only way a ``require_member_of_*`` setting appears in V2 at all.
Workflow had the opposite problem -- none of its settings are named ``enable_*``,
so the scan had nothing to guess with and the group rendered empty.
"""

import re
from urllib.parse import urlparse

from functions_ai_notice import (
    AI_NOTICE_MAX_MESSAGE_LENGTH,
    normalize_ai_notice_frequency,
    normalize_ai_notice_message,
)
from functions_group_assignment_ids import (
    normalize_group_workflow_allowed_group_ids,
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
    "id_list",
    "group_picker",
    "component",
)

# Types that own their persistence outside the settings PATCH: image uploads go
# through the multipart branding endpoint, and components talk to their own API.
NON_PATCHABLE_TYPES = ("image", "component")

LANDING_PAGE_ALIGNMENTS = ("left", "center", "right")
USER_AGREEMENT_APPLY_TO_VALUES = ("personal", "group", "public", "chat")

LOGO_SCALE_MIN_PERCENT = 50
LOGO_SCALE_MAX_PERCENT = 500
LOGO_SCALE_DEFAULT_PERCENT = 100

# Advisory, not enforced. The server-rendered form warns and saves anyway, so
# rejecting the value here would lock an administrator out of editing a section
# that already holds a longer agreement.
USER_AGREEMENT_WORD_LIMIT = 200

# Above this many automatic tool calls per workflow run, a run is capacity
# sensitive rather than merely long. The server-rendered pane says so in a
# warning block, so the same guidance is attached to the field here.
WORKFLOW_AUTO_INVOKE_CAPACITY_THRESHOLD = 100

CLASSIFICATION_BANNER_DEFAULT_COLOR = "#ffc107"
CLASSIFICATION_BANNER_DEFAULT_TEXT_COLOR = "#ffffff"

# Mirrors PUBLIC_WORKSPACE_DISPLAY_NAME_MAX_LENGTH in functions_settings.py, which
# cannot be imported here: it reaches config.py and a live Cosmos client, and is one
# of the modules the functional tests stub out. test_v2_admin_workspaces_parity.py
# reads the value back out of that source and fails if the two drift apart.
PUBLIC_WORKSPACE_DISPLAY_NAME_MAX_LENGTH = 32

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
                "Gives every user a private space for their own documents, prompts, "
                "agents and actions, which only they can reach. The new interface "
                "presents it to end users as \"My Workspace\"; admin settings and "
                "internal references call it the personal workspace. Turning this off "
                "hides the destination and the personal scope in chat, and leaves "
                "already-stored documents in place but unreachable."
            ),
            "default": True,
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
    "url-access-section": [
        {
            "key": "require_member_of_url_access_user",
            "type": "switch",
            "label": "Require UrlAccessUser App Role",
            "help": (
                "Narrows fetching a URL in chat, and enabling it for a workflow, to "
                "holders of the UrlAccessUser app role."
            ),
            "default": False,
        },
    ],
    "source-review-section": [
        {
            "key": "require_member_of_deep_research_user",
            "type": "switch",
            "label": "Require DeepResearchUser App Role",
            "help": (
                "Narrows Deep Research to holders of the DeepResearchUser app role. "
                "Worth using where the multi-step runs it performs are expensive "
                "enough to want a named audience."
            ),
            "default": False,
        },
    ],
    "workflow-settings-section": [
        {
            "key": "require_member_of_workflow_user",
            "type": "switch",
            "label": "Require WorkflowUser App Role",
            "help": (
                "Narrows opening, creating, editing, running and inspecting personal "
                "workflows to holders of the WorkflowUser app role. Scheduled "
                "workflows run unattended, so this is the control over who can leave "
                "one running."
            ),
            "default": False,
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
    """
    if not isinstance(value, list):
        return None, "Expected a list of ids."

    if field.get("id_kind") == "group":
        return normalize_group_workflow_allowed_group_ids(value), None

    ids = []
    seen = set()
    for item in value:
        candidate = str(item or "").strip()
        if not candidate or candidate in seen:
            continue
        ids.append(candidate)
        seen.add(candidate)
    return ids, None


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

    if field_type == "link_list":
        links, error = _normalize_link_list(value)
        return links, error, None

    if field_type == "id_list":
        ids, error = _normalize_id_list(value, field)
        return ids, error, None

    if field_type == "group_picker":
        # Delegated so an assignment saved from V2 is byte-for-byte what the
        # server-rendered form would have stored, including how it drops ids that
        # are not canonical group UUIDs.
        return normalize_group_workflow_allowed_group_ids(value), None, None

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

    return normalized, errors, warnings


def _check_minimum_selections(normalized, current_settings, errors):
    """Enforce ``min_selected`` once the merged state of a save is known."""
    for _section_id, field in iter_fields():
        key = field.get("key")
        minimum = field.get("min_selected")
        if not key or not minimum:
            continue

        depends_on = field.get("depends_on")
        if depends_on:
            gate_key = depends_on["key"]
            gate_value = (
                normalized[gate_key] if gate_key in normalized
                else current_settings.get(gate_key, False)
            )
            if _coerce_bool(gate_value) != depends_on.get("equals", True):
                continue

        selection = (
            normalized[key] if key in normalized else current_settings.get(key) or []
        )
        if len(selection) < minimum:
            errors[key] = f"Select at least {minimum} option."
