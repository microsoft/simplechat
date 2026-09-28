# functions_group_identity_policy.py
"""Group workspace identity management capability projections.

These are interface hints only. Every identity route reauthorizes membership,
role and group status independently: a projection here never grants access.

Unlike group agents (which any member may select in chat), identities are a
manager-only surface for both reads and writes, matching the classic interface
and today's ``/api/workspace-identities/group`` routes. There is one availability
predicate, :func:`group_identities_available`, shared with the workspace
context's ``sections.identities`` so the section, the projection and the routes
all read the same gate.
"""


# Reads and writes both require a content-manager role; ordinary members cannot
# list group identities today, and M5A keeps that.
GROUP_IDENTITY_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
# Statuses a manager may browse. ``inactive`` and any unrecognized status are
# denied outright, never treated as active.
GROUP_IDENTITY_READ_STATUSES = frozenset({"active", "locked", "upload_disabled"})
# Workspace-level management capabilities, ordered for a stable projection.
GROUP_IDENTITY_OPERATIONS = ("create", "edit", "delete")
# The per-identity subset. ``create`` is a workspace capability, not a property of
# an existing identity, so it is never a per-item action.
GROUP_IDENTITY_ITEM_OPERATIONS = ("edit", "delete")

# The reason the shared shell shows when the surface is unavailable. It matches
# the context's own wording so the section, the projection and the routes all
# read the same way to an operator.
GROUP_IDENTITIES_UNAVAILABLE_REASON = "Identities require File Sync or Semantic Kernel."


def group_identities_available(settings, group_id, *, user_info=None, file_sync_enabled=None):
    """The single availability predicate for the whole native group identity surface.

    Returns ``(available, reason)``. Group identities are offered when the tenant
    has Semantic Kernel on, or when File Sync is enabled for this group. This is
    the one place those two flags are combined, so the context's Identities
    section, the management projection and every immutable route agree.

    ``file_sync_enabled`` may carry the caller's precomputed
    ``is_file_sync_enabled_for_group`` result (the context resolves it once for
    its File Sync section) so this predicate does not repeat the lookup. The
    routes pass nothing and resolve it here with ``user_info`` so the
    ``file_sync_group_admin_only`` toggle is evaluated against the caller.
    """
    if bool(settings.get("enable_semantic_kernel", False)):
        return True, None
    if file_sync_enabled is None:
        from functions_file_sync import is_file_sync_enabled_for_group

        file_sync_enabled = is_file_sync_enabled_for_group(settings, group_id, user_info=user_info)
    if file_sync_enabled:
        return True, None
    return False, GROUP_IDENTITIES_UNAVAILABLE_REASON


def group_identity_management_operations(role, group, settings, *, available):
    """The workspace-level identity operations a caller may perform.

    The surface must be available (Semantic Kernel or File Sync), the caller must
    hold a manager role, and the group must be ``active``. Any non-``active``
    status is read-only. Empty when the surface is unavailable, so the projection
    and the routes cannot offer management a disabled tenant forbids.

    ``available`` is always supplied by the access layer, which resolves the
    predicate once per request; the identity surface's availability depends on
    tenant flags and the caller's File Sync eligibility, not on a value this
    projection can recompute on its own.
    """
    if not available:
        return []
    if role not in GROUP_IDENTITY_MANAGER_ROLES:
        return []
    if group.get("status", "active") != "active":
        return []
    return list(GROUP_IDENTITY_OPERATIONS)


def group_identity_actions(role, group, settings, *, available):
    """The operations advertised for a single identity.

    ``edit`` and ``delete`` come from the management projection intersected with
    the per-item vocabulary, computed fresh so a stored ``identity_actions`` can
    never be served.
    """
    management = set(
        group_identity_management_operations(role, group, settings, available=available)
    )
    return [operation for operation in GROUP_IDENTITY_ITEM_OPERATIONS if operation in management]
