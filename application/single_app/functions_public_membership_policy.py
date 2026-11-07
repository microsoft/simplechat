# functions_public_membership_policy.py
"""Who may do what to a public workspace's membership, decided in one place.

The native public membership routes and the hints they publish read the same two
functions, so the Members view can never offer a control the routes refuse:

- ``public_membership_operations(role, workspace, settings)``: the workspace-level
  operations the caller may perform, published as ``membership_management`` in the
  member-list envelope. ``review_requests`` covers the pending document-manager
  request list and its approve and reject routes;
- ``public_member_actions(caller_role, target_role, is_self=...)``: what the caller
  may do to one member, published on each member row as ``member_actions``.

The rules follow the classic public routes, except where the M10A decisions refine
them, and they deliberately differ from the group policy in two ways:

- a public workspace has no ``users[]`` roster: the members are exactly the Owner,
  the Admins and the DocumentManagers. ``User`` is every other signed-in reader,
  who is never stored, listed, added or removed as a member;
- there is **no ``leave`` and no "step down"** (decision 17). Classic refuses
  self-removal, and V2 keeps that: a manager can't remove themselves, and the
  routes carry no ``leave`` operation or action. This is the one deliberate
  difference from the group policy;
- the assignable roles are Admin and DocumentManager only. Removal stands in for
  demoting a member to ``User``, because a ``User`` is never stored.

Otherwise the Owner and Admins manage members (add, review requests, change roles
and remove); only the Owner transfers ownership, to a member other than themselves;
the Owner's role can't be changed and the Owner can't be removed; and adding a
member or changing a role needs an ``active`` or ``upload_disabled`` workspace, as
the classic page hides those controls when a workspace is ``locked`` or
``inactive``. An unrecognized status is refused too. Removing a member, reviewing
requests and transferring ownership are allowed in every status, as classic allows.

This module is pure: it reads only the values it is given.
"""

PUBLIC_MEMBERSHIP_HINT_SCHEMA_VERSION = 1
PUBLIC_MEMBER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
PUBLIC_MEMBERSHIP_MANAGER_ROLES = ("Owner", "Admin")
PUBLIC_ASSIGNABLE_ROLES = ("Admin", "DocumentManager")
PUBLIC_MEMBER_ADD_STATUSES = frozenset({"active", "upload_disabled"})

PUBLIC_MEMBERSHIP_OPERATIONS = (
    "add_member",
    "review_requests",
    "change_role",
    "remove_member",
    "transfer_ownership",
)
PUBLIC_MEMBER_ACTIONS = ("change_role", "remove", "transfer_ownership")


def public_member_add_allowed(workspace):
    """Whether the workspace's status lets members be added (a missing status is ``active``)."""
    status = (workspace if isinstance(workspace, dict) else {}).get("status") or "active"
    return status in PUBLIC_MEMBER_ADD_STATUSES


def public_membership_operations(role, workspace, settings):
    """The membership operations a caller holding ``role`` may perform on ``workspace``."""
    if not (settings if isinstance(settings, dict) else {}).get("enable_public_workspaces", False):
        return []
    if role not in PUBLIC_MEMBER_ROLES:
        return []
    operations = set()
    if role in PUBLIC_MEMBERSHIP_MANAGER_ROLES:
        operations.update({"review_requests", "remove_member"})
        if public_member_add_allowed(workspace):
            operations.update({"add_member", "change_role"})
    if role == "Owner":
        operations.add("transfer_ownership")
    return [operation for operation in PUBLIC_MEMBERSHIP_OPERATIONS if operation in operations]


def public_member_actions(caller_role, target_role, *, is_self):
    """What a caller holding ``caller_role`` may do to a member holding ``target_role``.

    There is no ``leave`` and no self-action: a public manager can't remove or demote
    themselves (decision 17), so ``is_self`` yields no actions.
    """
    if caller_role not in PUBLIC_MEMBER_ROLES or target_role not in PUBLIC_MEMBER_ROLES:
        return []
    if target_role == "Owner":
        return []
    if is_self:
        return []
    actions = set()
    if caller_role in PUBLIC_MEMBERSHIP_MANAGER_ROLES:
        actions.update({"change_role", "remove"})
        if caller_role == "Owner":
            actions.add("transfer_ownership")
    return [action for action in PUBLIC_MEMBER_ACTIONS if action in actions]


__all__ = [
    "PUBLIC_ASSIGNABLE_ROLES",
    "PUBLIC_MEMBERSHIP_HINT_SCHEMA_VERSION",
    "PUBLIC_MEMBERSHIP_MANAGER_ROLES",
    "PUBLIC_MEMBERSHIP_OPERATIONS",
    "PUBLIC_MEMBER_ACTIONS",
    "PUBLIC_MEMBER_ADD_STATUSES",
    "PUBLIC_MEMBER_ROLES",
    "public_member_actions",
    "public_member_add_allowed",
    "public_membership_operations",
]
