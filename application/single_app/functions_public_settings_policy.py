# functions_public_settings_policy.py
"""Who may change which public workspace settings, decided in one place.

``public_settings_decisions`` is the one decision behind the native public workspace
settings and insights routes, the ``settings_management`` block of their settings
read, and the same block in the public workspace context. For each operation it
returns ``None`` when the caller may perform it, or the reason code the route refuses
with, so the interface can explain an unavailable control without guessing.

The rules, each matching its classic route (a seam test holds them to those routes'
outcomes):

- ``edit_name``, ``edit_description``, ``edit_color`` and ``edit_logo`` need the
  owner, as ``PATCH``/``PUT /api/public_workspaces/<ws_id>`` and ``POST
  /api/public_workspaces/<ws_id>/logo`` do. Neither classic route carries a
  creation-role rule, so none applies here;
- those four are refused unless the workspace is ``active`` or ``upload_disabled``:
  while it's ``locked`` or ``inactive``, and while its status isn't recognized, which
  fails closed as the public workspace context does. This rule is native only: the
  classic routes check no status;
- ``edit_downloads`` needs the owner or an admin, and the administrator's download
  capability for the workspace, as ``PATCH .../download-settings`` does;
- ``edit_retention`` needs the owner or an admin, as ``POST
  /api/retention-policy/public/<ws_id>`` does, with public workspaces and
  ``enable_retention_policy_public`` on: the switch the classic manage page shows its
  retention section by. The classic route checks neither switch, so that part is
  native only too;
- ``view_activity`` needs the owner or an admin, and ``view_stats`` the owner, an
  admin or a document manager, as the classic ``/activity`` and ``/stats`` reads do,
  in every status.

Every signed-in caller reads a public workspace as at least a ``User``, so a role is
always known. When several reasons apply, the caller's role is reported before the
workspace status, so nobody is told to wait for a status change that would not help.

The decision reads only the values it is given.
"""

from functions_settings import is_public_workspace_file_download_admin_enabled


PUBLIC_SETTINGS_MANAGEMENT_SCHEMA_VERSION = 1

PUBLIC_SETTINGS_OPERATIONS = (
    "edit_name",
    "edit_description",
    "edit_color",
    "edit_logo",
    "edit_downloads",
    "edit_retention",
    "view_activity",
    "view_stats",
)
PUBLIC_PROFILE_OPERATIONS = ("edit_name", "edit_description", "edit_color")
PUBLIC_SETTINGS_OWNER_ROLE = "Owner"
PUBLIC_SETTINGS_MANAGER_ROLES = ("Owner", "Admin")
# The stored roles: every other signed-in caller is a ``User``.
PUBLIC_SETTINGS_MEMBER_ROLES = ("Owner", "Admin", "DocumentManager")
# The only statuses in which the profile and logo can change. Any other value,
# including one this version doesn't recognize, keeps them read-only.
PUBLIC_SETTINGS_WRITABLE_STATUSES = ("active", "upload_disabled")

# Reason codes. Each is also the ``error_code`` a route refuses that operation with.
PUBLIC_OWNER_REQUIRED = "public_workspace_owner_required"
PUBLIC_MANAGER_REQUIRED = "public_workspace_manager_required"
PUBLIC_MEMBER_REQUIRED = "public_workspace_member_required"
PUBLIC_STATUS_UNAVAILABLE = "public_workspace_status_unavailable"
PUBLIC_DOWNLOADS_NOT_ENABLED = "public_workspace_downloads_not_enabled"
PUBLIC_RETENTION_DISABLED = "public_workspace_retention_disabled"


def public_retention_enabled(settings):
    """Whether public retention policies are on: public workspaces and the public retention switch."""
    source = settings if isinstance(settings, dict) else {}
    return bool(source.get("enable_public_workspaces", False)) and bool(source.get("enable_retention_policy_public", False))


def public_settings_read_only(workspace):
    """Whether the workspace's status keeps its profile and logo read-only.

    A missing status is ``active``, as everywhere else; a value that isn't one of the
    writable statuses, recognized or not, is read-only.
    """
    source = workspace if isinstance(workspace, dict) else {}
    return source.get("status", "active") not in PUBLIC_SETTINGS_WRITABLE_STATUSES


def public_settings_decisions(role, workspace, settings):
    """Return ``{operation: None or reason}`` for every operation, in a fixed order."""
    workspace = workspace if isinstance(workspace, dict) else {}
    settings = settings if isinstance(settings, dict) else {}
    owner = role == PUBLIC_SETTINGS_OWNER_ROLE
    manager = role in PUBLIC_SETTINGS_MANAGER_ROLES
    member = role in PUBLIC_SETTINGS_MEMBER_ROLES

    if not owner:
        profile = PUBLIC_OWNER_REQUIRED
    elif public_settings_read_only(workspace):
        profile = PUBLIC_STATUS_UNAVAILABLE
    else:
        profile = None

    decisions = {operation: profile for operation in PUBLIC_PROFILE_OPERATIONS}
    decisions["edit_logo"] = profile
    if not manager:
        decisions["edit_downloads"] = PUBLIC_MANAGER_REQUIRED
    elif not is_public_workspace_file_download_admin_enabled(settings, workspace):
        decisions["edit_downloads"] = PUBLIC_DOWNLOADS_NOT_ENABLED
    else:
        decisions["edit_downloads"] = None
    if not manager:
        decisions["edit_retention"] = PUBLIC_MANAGER_REQUIRED
    elif not public_retention_enabled(settings):
        decisions["edit_retention"] = PUBLIC_RETENTION_DISABLED
    else:
        decisions["edit_retention"] = None
    decisions["view_activity"] = None if manager else PUBLIC_MANAGER_REQUIRED
    decisions["view_stats"] = None if member else PUBLIC_MEMBER_REQUIRED
    return {operation: decisions[operation] for operation in PUBLIC_SETTINGS_OPERATIONS}


def public_settings_operations(role, workspace, settings):
    """Return the operations the caller may perform, in ``PUBLIC_SETTINGS_OPERATIONS`` order."""
    return [
        operation for operation, reason in public_settings_decisions(role, workspace, settings).items()
        if reason is None
    ]


def build_public_settings_management(role, workspace, settings):
    """Return the ``settings_management`` block: the allowed operations and why the others are not."""
    decisions = public_settings_decisions(role, workspace, settings)
    return {
        "schema_version": PUBLIC_SETTINGS_MANAGEMENT_SCHEMA_VERSION,
        "operations": [operation for operation, reason in decisions.items() if reason is None],
        "reasons": {operation: reason for operation, reason in decisions.items() if reason is not None},
    }


__all__ = [
    "PUBLIC_DOWNLOADS_NOT_ENABLED",
    "PUBLIC_MANAGER_REQUIRED",
    "PUBLIC_MEMBER_REQUIRED",
    "PUBLIC_OWNER_REQUIRED",
    "PUBLIC_PROFILE_OPERATIONS",
    "PUBLIC_RETENTION_DISABLED",
    "PUBLIC_SETTINGS_MANAGEMENT_SCHEMA_VERSION",
    "PUBLIC_SETTINGS_MANAGER_ROLES",
    "PUBLIC_SETTINGS_MEMBER_ROLES",
    "PUBLIC_SETTINGS_OPERATIONS",
    "PUBLIC_SETTINGS_OWNER_ROLE",
    "PUBLIC_SETTINGS_WRITABLE_STATUSES",
    "PUBLIC_STATUS_UNAVAILABLE",
    "build_public_settings_management",
    "public_retention_enabled",
    "public_settings_decisions",
    "public_settings_operations",
    "public_settings_read_only",
]
