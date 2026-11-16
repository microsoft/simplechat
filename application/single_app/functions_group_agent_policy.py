# functions_group_agent_policy.py
"""Group agent management capability projections.

These are interface hints only. Every agent route reauthorizes membership, role
and group status independently: a projection here never grants access.

Group agents reuse the personal editor contract, but unlike group actions the
management vocabulary carries no ``test``. The per-agent vocabulary instead adds
``chat`` — "this agent is in the caller's chat catalogue" — which is independent
of the edit rights: a plain ``User`` who cannot edit an agent may still select it
in chat. ``chat`` is therefore computed from the same predicate the chat
catalogue applies (``build_accessible_agent_catalog`` plus
``_is_chat_agent_allowed_by_governance``), not from the write policy.

Write roles come from ``get_group_workflow_management_roles`` — the same function
the shell's ``sections.agents.can_manage`` uses — so the projection and the routes
agree: Owner/Admin, or Owner alone under ``require_owner_for_group_agent_management``.
"""


GROUP_AGENT_READER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
# Statuses a reader may browse. ``inactive`` and any unrecognized status are
# denied outright, never treated as active.
GROUP_AGENT_READ_STATUSES = frozenset({"active", "locked", "upload_disabled"})
# Workspace-level management capabilities, ordered for a stable projection.
GROUP_AGENT_OPERATIONS = ("create", "edit", "delete")
# The per-agent subset. ``create`` is a workspace capability, not a property of an
# existing agent, so it is never a per-item action. ``chat`` is a per-item read
# capability computed separately from the management policy.
GROUP_AGENT_ITEM_OPERATIONS = ("edit", "delete", "chat")

# The two reasons the shared shell shows when the surface is unavailable. The
# governance text matches the context's own wording so the section, the
# projection and the routes all read the same way to an operator.
GROUP_AGENTS_DISABLED_REASON = "Group agents are not enabled."
GROUP_AGENTS_GOVERNANCE_REASON = "Your administrator has restricted access to this capability."


def group_agents_configured(settings):
    """Whether the tenant flags that expose native group agents are all on.

    This mirrors the context's ``sections.agents`` configuration gate exactly:
    the group Semantic Kernel (``enable_semantic_kernel`` and
    ``per_user_semantic_kernel``) and group agents (``allow_group_agents``) must
    all be set. ``enable_group_workspaces`` is enforced by the route decorator and
    the context guard, so — like the context's ``agents_allowed`` — it is not part
    of this predicate. Governance is a separate, per-user gate.
    """
    return bool(
        settings.get("enable_semantic_kernel", False)
        and settings.get("per_user_semantic_kernel", False)
        and settings.get("allow_group_agents", False)
    )


def group_agents_available(user_id, settings):
    """The single availability predicate for the whole native group agent surface.

    Returns ``(available, reason)``. It is the one place the tenant flags and the
    per-user agent governance check are combined, so the context's Agents section,
    the management projection and every immutable route agree: a tenant with group
    agents off (or a user governance-denied) offers nothing and every route
    refuses. ``reason`` is ``None`` when available, otherwise the section's own
    reason text. This equals the context's ``agents_allowed`` exactly.
    """
    if not group_agents_configured(settings):
        return False, GROUP_AGENTS_DISABLED_REASON
    from functions_governance import is_governance_access_allowed

    if not is_governance_access_allowed("governance_group_agents", user_id):
        return False, GROUP_AGENTS_GOVERNANCE_REASON
    return True, None


def group_agent_chat_available(user_id, settings):
    """Whether the caller may select a group agent in chat.

    Uses the exact gate the chat catalogue applies: an agent is built into the
    catalogue only when ``enable_group_workspaces`` and ``allow_group_agents`` are
    on, then filtered by ``governance_group_agents``. This is independent of the
    editor availability predicate (which also needs Semantic Kernel), so the
    ``chat`` hint tracks the picker and not the editor.
    """
    if not (
        settings.get("enable_group_workspaces", False)
        and settings.get("allow_group_agents", False)
    ):
        return False
    from functions_governance import is_governance_access_allowed

    return bool(is_governance_access_allowed("governance_group_agents", user_id))


def group_agent_write_roles(settings):
    """The roles permitted to manage group agents.

    Mirrors the shell's ``sections.agents.can_manage``: Owner and Admin by
    default, Owner alone when ``require_owner_for_group_agent_management`` is set.
    """
    from functions_settings import get_group_workflow_management_roles

    return get_group_workflow_management_roles(settings)


def group_agent_management_operations(user_id, group, role, settings, *, available=None):
    """The workspace-level agent operations a caller may perform.

    The surface must be available (tenant flags plus per-user governance), the
    caller must hold a write role, and the group must be ``active``. Any
    non-``active`` status is read-only. Empty when the surface is unavailable, so
    the projection and the routes cannot offer management a disabled tenant
    forbids.

    ``available`` may carry the caller's precomputed :func:`group_agents_available`
    result so a caller that already gated the surface (the context computes it for
    ``sections.agents``) does not repeat the per-user governance check. The routes
    pass nothing and gate here.
    """
    if available is None:
        available, _reason = group_agents_available(user_id, settings)
    if not available:
        return []
    if role not in group_agent_write_roles(settings):
        return []
    if group.get("status", "active") != "active":
        return []
    return list(GROUP_AGENT_OPERATIONS)


def group_agent_actions(agent, user_id, group, role, settings, *, available=None, chat_available=None):
    """The operations advertised for a single agent.

    ``edit`` and ``delete`` come from the management projection intersected with
    the per-item vocabulary. ``chat`` is added independently when the agent is in
    the caller's chat catalogue, so a ``User`` with no edit rights still sees
    ``["chat"]``. ``available`` and ``chat_available`` may carry precomputed
    results so a list projection resolves each surface once rather than per row.
    """
    management = set(
        group_agent_management_operations(user_id, group, role, settings, available=available)
    )
    if chat_available is None:
        chat_available = group_agent_chat_available(user_id, settings)
    eligible = {operation for operation in ("edit", "delete") if operation in management}
    if chat_available:
        eligible.add("chat")
    return [operation for operation in GROUP_AGENT_ITEM_OPERATIONS if operation in eligible]
