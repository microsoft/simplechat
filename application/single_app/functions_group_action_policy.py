# functions_group_action_policy.py
"""Group action management capability projections.

These are interface hints only. Every action route reauthorizes membership,
role and group status independently: a projection here never grants access.

Group actions reuse the personal editor contract, so the vocabulary adds
``test`` to the workspace management set: testing a saved action loads its
stored credentials and is therefore an editor-only capability (see M4 §2). The
same status matrix the group document and prompt slices use is reused so the
surfaces read the same way to an operator, with one difference recorded in
``group_action_management_operations``: an owner-only governance setting can
narrow writes to the Owner alone.
"""


GROUP_ACTION_ADMIN_ROLES = ("Owner", "Admin")
GROUP_ACTION_READER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
# Statuses a reader may browse. ``inactive`` and any unrecognized status are
# denied outright, never treated as active.
GROUP_ACTION_READ_STATUSES = frozenset({"active", "locked", "upload_disabled"})
# Workspace-level management capabilities, ordered for a stable projection.
GROUP_ACTION_OPERATIONS = ("create", "edit", "delete", "test")
# The per-action subset. ``create`` is a workspace capability, not a property of
# an existing action, so it is never a per-item action.
GROUP_ACTION_ITEM_OPERATIONS = ("edit", "delete", "test")


def group_action_write_roles(settings):
    """The roles permitted to manage group actions.

    Mirrors the classic ``canManagePlugins()``: Owner and Admin by default, and
    Owner alone when ``require_owner_for_group_agent_management`` is enabled.
    """
    if settings.get("require_owner_for_group_agent_management", False):
        return ("Owner",)
    return GROUP_ACTION_ADMIN_ROLES


def group_action_management_operations(group, role, settings):
    """The workspace-level action operations a caller may perform.

    Mirrors V1's ``canManagePlugins()`` and ``groupAllowsModifications()``: a
    write role and an ``active`` group are required for all action management.
    Any non-``active`` status is read-only, matching the prompt slice, because
    testing a saved action is itself an editor capability.
    """
    if not settings.get("enable_group_workspaces", False):
        return []
    if role not in group_action_write_roles(settings):
        return []
    if group.get("status", "active") != "active":
        return []
    return list(GROUP_ACTION_OPERATIONS)


def group_action_actions(action, group, role, settings):
    """The operations advertised for a single action.

    Actions carry no per-item eligibility beyond the workspace policy, so this
    is the management projection intersected with the per-item vocabulary. It
    still takes ``action`` so the read projector computes actions per record and
    so a future per-action rule has one place to live.
    """
    operations = set(group_action_management_operations(group, role, settings))
    return [operation for operation in GROUP_ACTION_ITEM_OPERATIONS if operation in operations]
