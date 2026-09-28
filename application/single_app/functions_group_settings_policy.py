# functions_group_settings_policy.py
"""Who may change which group settings, decided in one place.

``group_settings_decisions`` is the one decision behind the native group settings
and insights routes, the ``settings_management`` block of their settings read, and
the same block in the group workspace context. For each operation it returns
``None`` when the caller may perform it, or the reason code the route refuses with,
so the interface can explain an unavailable control without guessing.

The rules, each matching its classic writer (a seam test holds them to those
routes' outcomes):

- ``edit_name``, ``edit_description`` and ``edit_color`` need the owner, and the
  ``CreateGroups`` app role when ``require_member_of_create_group`` is on, because
  the classic ``PATCH``/``PUT /api/groups/<group_id>`` carries
  ``create_group_role_required``. ``enable_group_creation`` plays no part, as it
  doesn't there, and the ``Admin`` app role does not stand in for the role;
- ``edit_logo`` needs the owner only, as ``POST /api/groups/<group_id>/logo`` does;
- those four are refused unless the group is ``active`` or ``upload_disabled``:
  while it's ``locked`` or ``inactive``, where the classic manage page makes the
  form read-only, and while its status isn't recognized, which fails closed as
  the workspace context and adding a member do. This rule is native only: the
  classic routes check no status;
- ``edit_downloads`` needs the owner or an admin, and the administrator's download
  capability for the group;
- ``edit_retention`` needs the owner or an admin, with group workspaces and
  ``enable_retention_policy_group`` on, the switch the classic manage page shows
  its retention section by;
- ``view_activity`` and ``view_stats`` need the owner or an admin, and
  ``view_file_count`` the owner, in every status, as the classic reads.

When several reasons apply, the caller's group role is reported first, then the
creation role, then the group status, so nobody is told to obtain a role that
would not help.

The decision reads only the values it is given.
"""

from functions_group_directory_policy import GROUP_CREATION_ROLE_REQUIRED, group_creation_role_missing
from functions_settings import is_group_workspace_file_download_admin_enabled


GROUP_SETTINGS_MANAGEMENT_SCHEMA_VERSION = 1

GROUP_SETTINGS_OPERATIONS = (
    "edit_name",
    "edit_description",
    "edit_color",
    "edit_logo",
    "edit_downloads",
    "edit_retention",
    "view_activity",
    "view_stats",
    "view_file_count",
)
GROUP_PROFILE_OPERATIONS = ("edit_name", "edit_description", "edit_color")
GROUP_SETTINGS_OWNER_ROLE = "Owner"
GROUP_SETTINGS_MANAGER_ROLES = ("Owner", "Admin")
# The statuses in which the classic manage page makes the group's profile read-only.
GROUP_SETTINGS_READ_ONLY_STATUSES = ("locked", "inactive")
# The only statuses in which the profile and logo can change. Any other value,
# including one this version doesn't recognize, keeps them read-only.
GROUP_SETTINGS_WRITABLE_STATUSES = ("active", "upload_disabled")

# Reason codes. Each is also the ``error_code`` a route refuses that operation with.
GROUP_OWNER_REQUIRED = "group_owner_required"
GROUP_MANAGER_REQUIRED = "group_manager_required"
GROUP_STATUS_UNAVAILABLE = "group_status_unavailable"
GROUP_DOWNLOADS_NOT_ENABLED = "group_downloads_not_enabled"
GROUP_RETENTION_DISABLED = "group_retention_disabled"


def group_retention_enabled(settings):
    """Whether group retention policies are on: group workspaces and the group retention switch."""
    source = settings if isinstance(settings, dict) else {}
    return bool(source.get("enable_group_workspaces", False)) and bool(source.get("enable_retention_policy_group", False))


def group_settings_read_only(group):
    """Whether the group's status keeps its profile read-only.

    A missing status is ``active``, as everywhere else; a value that isn't one of the
    writable statuses, recognized or not, is read-only.
    """
    source = group if isinstance(group, dict) else {}
    return source.get("status", "active") not in GROUP_SETTINGS_WRITABLE_STATUSES


def group_settings_decisions(role, group, settings, session_roles):
    """Return ``{operation: None or reason}`` for every operation, in a fixed order."""
    group = group if isinstance(group, dict) else {}
    settings = settings if isinstance(settings, dict) else {}
    owner = role == GROUP_SETTINGS_OWNER_ROLE
    manager = role in GROUP_SETTINGS_MANAGER_ROLES
    read_only = group_settings_read_only(group)

    if not owner:
        profile = GROUP_OWNER_REQUIRED
    elif group_creation_role_missing(settings, session_roles):
        profile = GROUP_CREATION_ROLE_REQUIRED
    elif read_only:
        profile = GROUP_STATUS_UNAVAILABLE
    else:
        profile = None

    decisions = {operation: profile for operation in GROUP_PROFILE_OPERATIONS}
    decisions["edit_logo"] = GROUP_OWNER_REQUIRED if not owner else GROUP_STATUS_UNAVAILABLE if read_only else None
    if not manager:
        decisions["edit_downloads"] = GROUP_MANAGER_REQUIRED
    elif not is_group_workspace_file_download_admin_enabled(settings, group):
        decisions["edit_downloads"] = GROUP_DOWNLOADS_NOT_ENABLED
    else:
        decisions["edit_downloads"] = None
    if not manager:
        decisions["edit_retention"] = GROUP_MANAGER_REQUIRED
    elif not group_retention_enabled(settings):
        decisions["edit_retention"] = GROUP_RETENTION_DISABLED
    else:
        decisions["edit_retention"] = None
    decisions["view_activity"] = None if manager else GROUP_MANAGER_REQUIRED
    decisions["view_stats"] = None if manager else GROUP_MANAGER_REQUIRED
    decisions["view_file_count"] = None if owner else GROUP_OWNER_REQUIRED
    return {operation: decisions[operation] for operation in GROUP_SETTINGS_OPERATIONS}


def group_settings_operations(role, group, settings, session_roles):
    """Return the operations the caller may perform, in ``GROUP_SETTINGS_OPERATIONS`` order."""
    return [
        operation for operation, reason in group_settings_decisions(role, group, settings, session_roles).items()
        if reason is None
    ]


def build_group_settings_management(role, group, settings, session_roles):
    """Return the ``settings_management`` block: the allowed operations and why the others are not."""
    decisions = group_settings_decisions(role, group, settings, session_roles)
    return {
        "schema_version": GROUP_SETTINGS_MANAGEMENT_SCHEMA_VERSION,
        "operations": [operation for operation, reason in decisions.items() if reason is None],
        "reasons": {operation: reason for operation, reason in decisions.items() if reason is not None},
    }


__all__ = [
    "GROUP_DOWNLOADS_NOT_ENABLED",
    "GROUP_MANAGER_REQUIRED",
    "GROUP_OWNER_REQUIRED",
    "GROUP_PROFILE_OPERATIONS",
    "GROUP_RETENTION_DISABLED",
    "GROUP_SETTINGS_MANAGEMENT_SCHEMA_VERSION",
    "GROUP_SETTINGS_MANAGER_ROLES",
    "GROUP_SETTINGS_OPERATIONS",
    "GROUP_SETTINGS_READ_ONLY_STATUSES",
    "GROUP_SETTINGS_WRITABLE_STATUSES",
    "GROUP_STATUS_UNAVAILABLE",
    "build_group_settings_management",
    "group_retention_enabled",
    "group_settings_decisions",
    "group_settings_operations",
    "group_settings_read_only",
]
