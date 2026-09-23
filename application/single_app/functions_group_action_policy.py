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

# The two reasons the shared shell shows when the surface is unavailable. The
# governance text matches the context's own wording so the section, the
# projection and the routes all read the same way to an operator.
GROUP_ACTIONS_DISABLED_REASON = "Group actions are not enabled."
GROUP_ACTIONS_GOVERNANCE_REASON = "Your administrator has restricted access to this capability."


def group_actions_configured(settings):
    """Whether the tenant flags that expose native group actions are all on.

    This mirrors the context's ``sections.actions`` configuration gate exactly:
    the group Semantic Kernel (``enable_semantic_kernel`` and
    ``per_user_semantic_kernel``), group agents (``allow_group_agents``) and the
    group plugins flag (``allow_group_plugins``, off by default) must all be set,
    inside an enabled group workspace. Governance is a separate, per-user gate.
    """
    return bool(
        settings.get("enable_group_workspaces", False)
        and settings.get("enable_semantic_kernel", False)
        and settings.get("per_user_semantic_kernel", False)
        and settings.get("allow_group_agents", False)
        and settings.get("allow_group_plugins", False)
    )


def group_actions_available(user_id, settings):
    """The single availability predicate for the whole native group action surface.

    Returns ``(available, reason)``. It is the one place the tenant flags and the
    per-user action governance check are combined, so the context's Actions
    section, the management projection and every immutable route agree: a tenant
    with group actions off (or a user governance-denied) offers nothing and every
    route refuses. ``reason`` is ``None`` when available, otherwise the section's
    own reason text.
    """
    if not group_actions_configured(settings):
        return False, GROUP_ACTIONS_DISABLED_REASON
    from functions_governance import is_action_scope_access_allowed

    if not is_action_scope_access_allowed("governance_group_actions", user_id, "group"):
        return False, GROUP_ACTIONS_GOVERNANCE_REASON
    return True, None


def group_action_write_roles(settings):
    """The roles permitted to manage group actions.

    Mirrors the classic ``canManagePlugins()``: Owner and Admin by default, and
    Owner alone when ``require_owner_for_group_agent_management`` is enabled.
    """
    if settings.get("require_owner_for_group_agent_management", False):
        return ("Owner",)
    return GROUP_ACTION_ADMIN_ROLES


def group_action_management_operations(user_id, group, role, settings, *, available=None):
    """The workspace-level action operations a caller may perform.

    Mirrors V1's ``canManagePlugins()`` and ``groupAllowsModifications()``: the
    surface must be available (tenant flags plus per-user governance), the caller
    must hold a write role, and the group must be ``active``. Any non-``active``
    status is read-only, matching the prompt slice, because testing a saved action
    is itself an editor capability. Empty when the surface is unavailable, so the
    projection and the routes cannot offer management a disabled tenant forbids.

    ``available`` may carry the caller's precomputed :func:`group_actions_available`
    result so a caller that already gated the surface (the context computes it for
    ``sections.actions``) does not repeat the per-user governance check. The routes
    pass nothing and gate here.
    """
    if available is None:
        available, _reason = group_actions_available(user_id, settings)
    if not available:
        return []
    if role not in group_action_write_roles(settings):
        return []
    if group.get("status", "active") != "active":
        return []
    return list(GROUP_ACTION_OPERATIONS)


def group_action_actions(action, user_id, group, role, settings):
    """The operations advertised for a single action.

    Actions carry no per-item eligibility beyond the workspace policy, so this
    is the management projection intersected with the per-item vocabulary. It
    still takes ``action`` so the read projector computes actions per record and
    so a future per-action rule has one place to live.
    """
    operations = set(group_action_management_operations(user_id, group, role, settings))
    return [operation for operation in GROUP_ACTION_ITEM_OPERATIONS if operation in operations]
