# functions_public_directory_policy.py
"""Who may create a public workspace, decided in one place.

Classic public workspace creation is gated on the ``POST /api/public_workspaces``
route by two decorators that agree only by coincidence: ``create_public_workspace_role_required``
(the ``CreatePublicWorkspaces`` app role when ``require_member_of_create_public_workspace``
is on) and ``enabled_required("enable_public_workspaces")``. The native public
directory reads one decision instead: ``public_creation_refusal`` reports why a caller
may not create, and ``build_public_directory_hints`` publishes it as ``can_create``, so
the Create control can never be offered to someone the classic route refuses, or hidden
from someone it accepts. A seam test holds the decision to the classic decorators.

The rules, matching the classic decorators:

- creation needs ``enable_public_workspaces``; a missing setting counts as off. Unlike
  a group there is no separate creation switch: the public route has no
  ``enable_public_workspace_creation``, so the feature flag alone gates it;
- when ``require_member_of_create_public_workspace`` is on, the session's app roles
  must include ``CreatePublicWorkspaces``. The ``Admin`` app role does not stand in
  for it;
- roles that are missing, ``None`` or not a list of names count as no roles.

Creation that is switched off is reported before a missing role, so a user is not told
to obtain a role that would not help. This module is pure: it reads only the values it
is given.
"""

PUBLIC_DIRECTORY_HINTS_SCHEMA_VERSION = 1
PUBLIC_CREATION_APP_ROLE = "CreatePublicWorkspaces"

PUBLIC_CREATION_DISABLED = "public_workspace_creation_disabled"
PUBLIC_CREATION_ROLE_REQUIRED = "create_public_workspaces_role_required"


def _role_names(roles):
    if isinstance(roles, (list, tuple, set, frozenset)):
        return {role for role in roles if isinstance(role, str)}
    return set()


def public_creation_role_missing(settings, roles):
    """Return ``True`` when creation is narrowed to ``CreatePublicWorkspaces`` and ``roles`` lacks it.

    ``enable_public_workspaces`` is not read: the classic decorator this matches does
    not read it either.
    """
    source = settings if isinstance(settings, dict) else {}
    return (
        bool(source.get("require_member_of_create_public_workspace", False))
        and PUBLIC_CREATION_APP_ROLE not in _role_names(roles)
    )


def public_creation_refusal(settings, roles):
    """Return why the caller may not create a public workspace, or ``None`` when they may.

    The reason is ``PUBLIC_CREATION_DISABLED`` when public workspaces are switched off,
    and ``PUBLIC_CREATION_ROLE_REQUIRED`` when creation is narrowed to the
    ``CreatePublicWorkspaces`` app role and ``roles`` does not include it.
    """
    source = settings if isinstance(settings, dict) else {}
    if not source.get("enable_public_workspaces", False):
        return PUBLIC_CREATION_DISABLED
    if public_creation_role_missing(source, roles):
        return PUBLIC_CREATION_ROLE_REQUIRED
    return None


def build_public_directory_hints(settings, roles):
    """Return the ``public_directory`` hint the directory response carries."""
    source = settings if isinstance(settings, dict) else {}
    return {
        "schema_version": PUBLIC_DIRECTORY_HINTS_SCHEMA_VERSION,
        "can_create": public_creation_refusal(source, roles) is None,
    }


__all__ = [
    "PUBLIC_CREATION_APP_ROLE",
    "PUBLIC_CREATION_DISABLED",
    "PUBLIC_CREATION_ROLE_REQUIRED",
    "PUBLIC_DIRECTORY_HINTS_SCHEMA_VERSION",
    "build_public_directory_hints",
    "public_creation_refusal",
    "public_creation_role_missing",
]
