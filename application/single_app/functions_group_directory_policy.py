# functions_group_directory_policy.py
"""Who may create a group and who may ask to join one, decided in one place.

Classic group creation is gated in three places that agree only by coincidence: the
``create_group_role_required`` decorator (the ``CreateGroups`` app role when
``require_member_of_create_group`` is on), ``enabled_required("enable_group_creation")``
and the ``_require_group_creation_enabled`` helper behind
``create_group_for_current_user``. The native group directory reads one decision
instead: ``group_creation_refusal`` gates the native create route and
``build_group_directory_hints`` reports the same answer to the client, so the Create
control can never be offered to someone the route refuses, or hidden from someone it
accepts. A seam test holds both to the legacy outcomes.

The rules, matching the legacy checks:

- creation needs ``enable_group_workspaces`` and ``enable_group_creation``; a missing
  setting counts as off;
- when ``require_member_of_create_group`` is on, the session's app roles must include
  ``CreateGroups``. The ``Admin`` app role does not stand in for it;
- roles that are missing, ``None`` or not a list of names count as no roles.

Creation that is switched off is reported before a missing role, as the helper does,
so a user is not told to obtain a role that would not help. Asking to join needs only
``enable_group_workspaces``: every authenticated user may ask to join any group, in
every group status, as the classic Find Group flow allows.

``group_creation_role_missing`` is the role half on its own. It is exactly the rule
``create_group_role_required`` applies, and the classic group rename, recolor and
delete routes carry that decorator, so the native group settings reuse it without
the switches, which those routes never read.

This module is pure: it reads only the values it is given.
"""

GROUP_DIRECTORY_HINTS_SCHEMA_VERSION = 1
GROUP_CREATION_APP_ROLE = "CreateGroups"

GROUP_CREATION_DISABLED = "group_creation_disabled"
GROUP_CREATION_ROLE_REQUIRED = "create_groups_role_required"


def _role_names(roles):
    if isinstance(roles, (list, tuple, set, frozenset)):
        return {role for role in roles if isinstance(role, str)}
    return set()


def group_creation_role_missing(settings, roles):
    """Return ``True`` when creation is narrowed to ``CreateGroups`` and ``roles`` lacks it.

    ``enable_group_workspaces`` and ``enable_group_creation`` are not read: the legacy
    decorator this matches does not read them either.
    """
    source = settings if isinstance(settings, dict) else {}
    return bool(source.get("require_member_of_create_group", False)) and GROUP_CREATION_APP_ROLE not in _role_names(roles)


def group_creation_refusal(settings, roles):
    """Return why the caller may not create a group, or ``None`` when they may.

    The reason is ``GROUP_CREATION_DISABLED`` when group workspaces or group creation
    are switched off, and ``GROUP_CREATION_ROLE_REQUIRED`` when creation is narrowed to
    the ``CreateGroups`` app role and ``roles`` does not include it.
    """
    source = settings if isinstance(settings, dict) else {}
    if not source.get("enable_group_workspaces", False) or not source.get("enable_group_creation", False):
        return GROUP_CREATION_DISABLED
    if group_creation_role_missing(source, roles):
        return GROUP_CREATION_ROLE_REQUIRED
    return None


def build_group_directory_hints(settings, roles):
    """Return the ``group_directory`` hint the directory response carries."""
    source = settings if isinstance(settings, dict) else {}
    return {
        "schema_version": GROUP_DIRECTORY_HINTS_SCHEMA_VERSION,
        "can_create": group_creation_refusal(source, roles) is None,
        "can_request_to_join": bool(source.get("enable_group_workspaces", False)),
    }


__all__ = [
    "GROUP_CREATION_APP_ROLE",
    "GROUP_CREATION_DISABLED",
    "GROUP_CREATION_ROLE_REQUIRED",
    "GROUP_DIRECTORY_HINTS_SCHEMA_VERSION",
    "build_group_directory_hints",
    "group_creation_refusal",
    "group_creation_role_missing",
]
