# functions_group_membership_policy.py
"""Who may do what to a group's membership, decided in one place.

The native membership routes and the hints they publish read the same two
functions, so the Members view can never offer a control the routes refuse:

- ``group_membership_operations(role, group, settings)``: the group-level
  operations the caller may perform, published as ``membership_management`` in the
  member-list envelope. ``review_requests`` covers the pending-request list and
  its approve and reject routes;
- ``group_member_actions(caller_role, target_role, is_self=...)``: what the caller
  may do to one member, published on each member row as ``member_actions``.

The rules follow the classic routes, except where the M7B decisions refine them:

- the Owner and Admins manage members: they add, review requests, change roles
  and remove. An Admin may promote to and demote from Admin, including other
  Admins and themselves, as classic allows;
- only the Owner transfers ownership, to a member other than themselves;
- the Owner's role can't be changed and the Owner can't be removed or leave; the
  routes answer ``owner_target`` and ``owner_cannot_leave``;
- any other member may leave;
- adding members needs an ``active`` or ``upload_disabled`` group, as the classic
  page hides Add and Bulk add when a group is ``locked`` or ``inactive``; an
  unrecognized status is refused too. Every other membership operation is allowed
  in every status, as classic allows.

This module is pure: it reads only the values it is given.
"""

GROUP_MEMBERSHIP_HINT_SCHEMA_VERSION = 1
GROUP_MEMBER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
GROUP_MEMBERSHIP_MANAGER_ROLES = ("Owner", "Admin")
GROUP_ASSIGNABLE_ROLES = ("Admin", "DocumentManager", "User")
GROUP_MEMBER_ADD_STATUSES = frozenset({"active", "upload_disabled"})

GROUP_MEMBERSHIP_OPERATIONS = (
    "add_member",
    "review_requests",
    "change_role",
    "remove_member",
    "transfer_ownership",
    "leave",
)
GROUP_MEMBER_ACTIONS = ("change_role", "remove", "transfer_ownership", "leave")


def group_member_add_allowed(group):
    """Whether the group's status lets members be added (a missing status is ``active``)."""
    status = (group if isinstance(group, dict) else {}).get("status") or "active"
    return status in GROUP_MEMBER_ADD_STATUSES


def group_membership_operations(role, group, settings):
    """The membership operations a caller holding ``role`` may perform on ``group``."""
    if not (settings if isinstance(settings, dict) else {}).get("enable_group_workspaces", False):
        return []
    if role not in GROUP_MEMBER_ROLES:
        return []
    operations = set()
    if role in GROUP_MEMBERSHIP_MANAGER_ROLES:
        operations.update({"review_requests", "change_role", "remove_member"})
        if group_member_add_allowed(group):
            operations.add("add_member")
    if role == "Owner":
        operations.add("transfer_ownership")
    else:
        operations.add("leave")
    return [operation for operation in GROUP_MEMBERSHIP_OPERATIONS if operation in operations]


def group_member_actions(caller_role, target_role, *, is_self):
    """What a caller holding ``caller_role`` may do to a member holding ``target_role``."""
    if caller_role not in GROUP_MEMBER_ROLES or target_role not in GROUP_MEMBER_ROLES:
        return []
    if target_role == "Owner":
        return []
    actions = set()
    if is_self:
        actions.add("leave")
        if caller_role == "Admin":
            actions.add("change_role")
    elif caller_role in GROUP_MEMBERSHIP_MANAGER_ROLES:
        actions.update({"change_role", "remove"})
        if caller_role == "Owner":
            actions.add("transfer_ownership")
    return [action for action in GROUP_MEMBER_ACTIONS if action in actions]


__all__ = [
    "GROUP_ASSIGNABLE_ROLES",
    "GROUP_MEMBERSHIP_HINT_SCHEMA_VERSION",
    "GROUP_MEMBERSHIP_MANAGER_ROLES",
    "GROUP_MEMBERSHIP_OPERATIONS",
    "GROUP_MEMBER_ACTIONS",
    "GROUP_MEMBER_ADD_STATUSES",
    "GROUP_MEMBER_ROLES",
    "group_member_actions",
    "group_member_add_allowed",
    "group_membership_operations",
]
