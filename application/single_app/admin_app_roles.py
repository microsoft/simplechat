# admin_app_roles.py
"""Registry of every setting that can require an Entra app role.

Requiring an app role is the most consequential change an administrator can make
in Admin Settings: get it wrong and a surface becomes unreachable, including, in
the Control Center's case, for the administrator making the change. The settings
themselves live on the tab that owns the feature, which is the right place to
decide them, but it means the full access policy is spread across seven tabs and
cannot be read as a whole.

The server-rendered page answers that with a roster built by scanning the DOM for
``input[name^="require_member_of_"]``. That works only because every control is
present in one document, which is not true of the V2 surface, and it silently
misses ``file_sync_personal_require_app_role`` because the name does not match the
selector.

This module is the description that scan was standing in for. Each entry names the
Entra app role value to assign, what enforcing it grants, and what happens when it
is left off -- the two facts an administrator needs and that neither interface
previously stated in one place.

``test_v2_admin_app_role_registry.py`` walks the settings defaults for role-shaped
keys and fails when one is not registered here, so this cannot fall behind the way
the DOM scan quietly did.
"""


# ``key``          The settings key holding the requirement.
# ``role``         The Entra Enterprise App role value to assign.
# ``section_id``   The card that owns the real control, for the "go to setting" link.
# ``grants``       What enforcing the requirement restricts, and to whom.
# ``when_off``     Who can reach the surface while the requirement is not enforced.
# ``depends_on``   A capability that must be on for the requirement to have any
#                  effect, or None. Enforcing a role for a disabled feature is not
#                  harmful, but it is confusing, so the surface says so.
APP_ROLE_REQUIREMENTS = [
    {
        "key": "require_member_of_safety_violation_admin",
        "role": "SafetyViolationAdmin",
        "label": "Safety Violations report",
        "section_id": "permissions-section",
        "grants": "Opening the Safety Violations admin report.",
        "when_off": "Any account with the general Admin role can open it.",
        "depends_on": None,
    },
    {
        "key": "require_member_of_feedback_admin",
        "role": "FeedbackAdmin",
        "label": "User Feedback report",
        "section_id": "permissions-section",
        "grants": "Opening the User Feedback admin report.",
        "when_off": "Any account with the general Admin role can open it.",
        "depends_on": "enable_user_feedback",
    },
    {
        "key": "require_member_of_control_center_admin",
        "role": "ControlCenterAdmin",
        "label": "Control Center",
        "section_id": "control-center-overview-section",
        "grants": (
            "The Control Center and every management feature in it. Accounts "
            "holding only the general Admin role lose access."
        ),
        "when_off": "Any account with the general Admin role has full access.",
        "depends_on": None,
    },
    {
        "key": "require_member_of_control_center_dashboard_reader",
        "role": "ControlCenterDashboardReader",
        "label": "Control Center dashboard, read only",
        "section_id": "control-center-overview-section",
        "grants": (
            "The Control Center dashboard without the management features. Only "
            "takes effect while the ControlCenterAdmin requirement is enforced."
        ),
        "when_off": "There is no dashboard-only tier; access is all or nothing.",
        "depends_on": "require_member_of_control_center_admin",
    },
    {
        "key": "require_member_of_create_group",
        "role": "CreateGroups",
        "label": "Creating group workspaces",
        "section_id": "group-workspaces-section",
        "grants": "Creating new group workspaces.",
        "when_off": "Any signed-in user can create a group workspace.",
        "depends_on": "enable_group_workspaces",
    },
    {
        "key": "require_member_of_create_public_workspace",
        "role": "CreatePublicWorkspaces",
        "label": "Creating public workspaces",
        "section_id": "public-workspaces-section",
        "grants": "Creating new public workspaces.",
        "when_off": "Any signed-in user can create a public workspace.",
        "depends_on": "enable_public_workspaces",
    },
    {
        "key": "require_member_of_chat_file_upload_user",
        "role": "ChatFileUploadUser",
        "label": "Uploading files into chat",
        "section_id": "chat-file-uploads-section",
        "grants": (
            "Attaching new files to a conversation. Attachments already in a "
            "conversation stay visible either way."
        ),
        "when_off": "Any signed-in user can attach files to a conversation.",
        "depends_on": "enable_user_workspace",
    },
    {
        "key": "require_member_of_workflow_user",
        "role": "WorkflowUser",
        "label": "Personal workflows",
        "section_id": "workflow-settings-section",
        "grants": "Opening, creating, editing, running and inspecting personal workflows.",
        "when_off": "Any signed-in user can use personal workflows.",
        "depends_on": "allow_user_workflows",
    },
    {
        "key": "require_member_of_url_access_user",
        "role": "UrlAccessUser",
        "label": "URL Access",
        "section_id": "url-access-section",
        "grants": "Using URL Access in chat, and enabling it for a workflow.",
        "when_off": "Any signed-in user can use URL Access.",
        "depends_on": "enable_url_access",
    },
    {
        "key": "require_member_of_deep_research_user",
        "role": "DeepResearchUser",
        "label": "Deep Research",
        "section_id": "source-review-section",
        "grants": "Using Deep Research.",
        "when_off": "Any signed-in user can use Deep Research.",
        "depends_on": "enable_source_review",
    },
    {
        "key": "file_sync_personal_require_app_role",
        "role": "PersonalFileSyncUser",
        "label": "Personal workspace file sync",
        "section_id": "file-sync-personal-section",
        "grants": "Syncing files into a personal workspace.",
        "when_off": "Any signed-in user can set up personal workspace sync.",
        "depends_on": "enable_file_sync",
    },
]

# Key prefixes and suffixes that mark a settings key as an app role requirement.
# The registry test uses these to find candidates in the settings defaults, so a
# new requirement following either convention is caught even though nothing else
# in the application links the two names.
APP_ROLE_SETTING_PREFIXES = ("require_member_of_",)
APP_ROLE_SETTING_SUFFIXES = ("_require_app_role",)


def get_app_role_requirements():
    """Return the registered app role requirements."""
    return APP_ROLE_REQUIREMENTS


def get_app_role_setting_keys():
    """Return the settings keys the registry describes."""
    return {requirement["key"] for requirement in APP_ROLE_REQUIREMENTS}


def is_app_role_setting_key(key):
    """Whether a settings key names an app role requirement by convention."""
    name = str(key or "")
    return name.startswith(APP_ROLE_SETTING_PREFIXES) or name.endswith(
        APP_ROLE_SETTING_SUFFIXES
    )
