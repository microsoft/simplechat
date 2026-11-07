# functions_group_endpoint_policy.py
"""Group model endpoint availability and management capability projections.

These are interface hints only. Every endpoint route reauthorizes membership, role
and group status independently: a projection here never grants access.

The workspace context's Endpoints section, the ``endpoint_management`` handshake,
each endpoint's ``endpoint_actions`` and every immutable-target route share the
one availability predicate below, so a tenant with group endpoints off (or a
governance-denied user) is offered nothing and every route refuses.

Unlike group agents and actions, the write roles are fixed at Owner and Admin:
``require_owner_for_group_agent_management`` narrows agent and action management
but has never applied to a group's model connections, and the context's
``sections.endpoints.can_manage`` has always meant Owner or Admin. ``test`` covers
model discovery, the model test and Foundry agent discovery, all of which load the
endpoint's stored credentials, so it needs the write roles too. ``enable`` is the
enabled/disabled toggle, an edit of one field that the in-use check never blocks.
"""


GROUP_ENDPOINT_READER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
GROUP_ENDPOINT_WRITE_ROLES = ("Owner", "Admin")
# Statuses a reader may browse. ``inactive`` and any unrecognized status are
# denied outright, never treated as active.
GROUP_ENDPOINT_READ_STATUSES = frozenset({"active", "locked", "upload_disabled"})
# Workspace-level management capabilities, ordered for a stable projection.
GROUP_ENDPOINT_OPERATIONS = ("create", "edit", "delete", "enable", "test")
# The per-endpoint subset. ``create`` is a workspace capability, not a property of
# an existing endpoint, so it is never a per-item action.
GROUP_ENDPOINT_ITEM_OPERATIONS = ("edit", "delete", "enable", "test")

# The two reasons the shared shell shows when the surface is unavailable. Both
# match the context's own wording so the section and the routes read the same way.
GROUP_ENDPOINTS_DISABLED_REASON = "Group model endpoints are not enabled."
GROUP_ENDPOINTS_GOVERNANCE_REASON = "Your administrator has restricted access to this capability."


def group_endpoints_configured(settings):
    """Whether the tenant flags that expose native group model endpoints are all on.

    The group Semantic Kernel (``enable_semantic_kernel`` and
    ``per_user_semantic_kernel``), custom group endpoints
    (``allow_group_custom_endpoints``) and multiple model endpoints
    (``enable_multi_model_endpoints``) must all be set. ``enable_group_workspaces``
    is enforced by the route decorator and the context guard, so it is not part of
    this predicate. Governance is a separate, per-user gate.
    """
    return bool(
        settings.get("enable_semantic_kernel", False)
        and settings.get("per_user_semantic_kernel", False)
        and settings.get("allow_group_custom_endpoints", False)
        and settings.get("enable_multi_model_endpoints", False)
    )


def group_endpoints_available(user_id, settings):
    """The single availability predicate for the whole native group endpoint surface.

    Returns ``(available, reason)``. ``available`` is exactly the context's former
    ``endpoints_allowed``: the tenant flags plus the per-user
    ``governance_group_endpoints`` check. ``reason`` is ``None`` when available,
    otherwise the section's own reason text.
    """
    if not group_endpoints_configured(settings):
        return False, GROUP_ENDPOINTS_DISABLED_REASON
    from functions_governance import is_governance_access_allowed

    if not is_governance_access_allowed("governance_group_endpoints", user_id):
        return False, GROUP_ENDPOINTS_GOVERNANCE_REASON
    return True, None


def group_endpoint_management_operations(user_id, group, role, settings, *, available=None):
    """The workspace-level endpoint operations a caller may perform.

    The surface must be available (tenant flags plus per-user governance), the
    caller must be an Owner or Admin, and the group must be ``active``. Any
    non-``active`` status is read-only. Empty when the surface is unavailable, so
    the projection and the routes cannot offer management a disabled tenant forbids.

    ``available`` may carry the caller's precomputed
    :func:`group_endpoints_available` result so a caller that already gated the
    surface (the context computes it for ``sections.endpoints``) does not repeat the
    per-user governance check. The routes pass nothing and gate here.
    """
    if available is None:
        available, _reason = group_endpoints_available(user_id, settings)
    if not available:
        return []
    if role not in GROUP_ENDPOINT_WRITE_ROLES:
        return []
    if (group or {}).get("status", "active") != "active":
        return []
    return list(GROUP_ENDPOINT_OPERATIONS)


def group_endpoint_actions(endpoint, user_id, group, role, settings, *, available=None):
    """The operations advertised for a single endpoint.

    Endpoints carry no per-item eligibility beyond the workspace policy, so this is
    the management projection intersected with the per-item vocabulary. It still
    takes ``endpoint`` so the projector computes actions per record and so a future
    per-endpoint rule has one place to live. ``available`` may carry a precomputed
    availability result so a list projection resolves the surface once.
    """
    operations = set(
        group_endpoint_management_operations(user_id, group, role, settings, available=available)
    )
    return [operation for operation in GROUP_ENDPOINT_ITEM_OPERATIONS if operation in operations]
