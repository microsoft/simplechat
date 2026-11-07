# functions_public_identity_policy.py
"""Public-workspace identity management capability projections.

Version: 0.261.182
Implemented in: 0.261.182

These are interface hints only. Every identity route reauthorizes role and
workspace status independently: a projection here never grants access.

Public identities are a manager-only surface for both reads and writes, exactly
like group identities and the existing ``/api/workspace-identities/public``
routes. There is one availability predicate, :func:`public_identities_available`,
shared with the workspace context's ``sections.identities`` so the section, the
projection and the routes all read the same gate.

The one deliberate difference from the group predicate is the consumer set: a
public workspace has no Semantic Kernel actions, so File Sync is the only thing
that consumes a public identity. The predicate therefore rests solely on File
Sync availability for the workspace, not on ``enable_semantic_kernel``. As with
the public prompt and document policies, the readable-status gate is an
**explicit** allowlist so an unrecognized status is denied rather than treated
as active.
"""


# Reads and writes both require a content-manager role; an ordinary ``User``
# cannot list public identities, matching the classic interface and the existing
# ``/api/workspace-identities/public`` routes.
PUBLIC_IDENTITY_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
# Statuses a manager may browse. ``inactive`` and any unrecognized status are
# denied outright, never treated as active. This matches the public document and
# prompt read sets so the surfaces read the same.
PUBLIC_IDENTITY_READ_STATUSES = frozenset({"active", "locked", "upload_disabled"})
# Workspace-level management capabilities, ordered for a stable projection.
PUBLIC_IDENTITY_OPERATIONS = ("create", "edit", "delete")
# The per-identity subset. ``create`` is a workspace capability, not a property
# of an existing identity, so it is never a per-item action.
PUBLIC_IDENTITY_ITEM_OPERATIONS = ("edit", "delete")

# The reason the shared shell shows when the surface is unavailable. Public
# identities are consumed only by File Sync, so the wording names File Sync
# rather than the group predicate's "File Sync or Semantic Kernel".
PUBLIC_IDENTITIES_UNAVAILABLE_REASON = "Identities require File Sync."


def public_identities_available(settings, workspace_id, *, user_info=None, file_sync_enabled=None):
    """The single availability predicate for the whole native public identity surface.

    Returns ``(available, reason)``. Public identities are offered only when File
    Sync is enabled for this workspace, because File Sync is the sole consumer of
    a public identity. This is the one place that flag is read, so the context's
    Identities section, the management projection and every immutable route agree.

    ``file_sync_enabled`` may carry the caller's precomputed
    ``is_file_sync_enabled_for_public_workspace`` result (the context resolves it
    once for its File Sync section) so this predicate does not repeat the lookup.
    The routes pass nothing and resolve it here with ``user_info`` so the
    ``file_sync_public_admin_only`` toggle is evaluated against the caller.
    """
    if file_sync_enabled is None:
        from functions_file_sync import is_file_sync_enabled_for_public_workspace

        file_sync_enabled = is_file_sync_enabled_for_public_workspace(
            settings, workspace_id, user_info=user_info
        )
    if file_sync_enabled:
        return True, None
    return False, PUBLIC_IDENTITIES_UNAVAILABLE_REASON


def public_identity_management_operations(role, workspace, settings, *, available):
    """The workspace-level identity operations a caller may perform.

    The surface must be available (File Sync for this workspace), the caller must
    hold a manager role, and the workspace must be ``active``. Any non-``active``
    status is read-only, and the allowlist is exact so an unrecognized status is
    read-only too. Empty when the surface is unavailable, so the projection and
    the routes cannot offer management a disabled tenant forbids.

    ``available`` is always supplied by the access layer, which resolves the
    predicate once per request; the identity surface's availability depends on
    tenant flags and the caller's File Sync eligibility, not on a value this
    projection can recompute on its own.
    """
    if not available:
        return []
    if role not in PUBLIC_IDENTITY_MANAGER_ROLES:
        return []
    if workspace.get("status", "active") != "active":
        return []
    return list(PUBLIC_IDENTITY_OPERATIONS)


def public_identity_actions(role, workspace, settings, *, available):
    """The operations advertised for a single identity.

    ``edit`` and ``delete`` come from the management projection intersected with
    the per-item vocabulary, computed fresh so a stored ``identity_actions`` can
    never be served.
    """
    management = set(
        public_identity_management_operations(role, workspace, settings, available=available)
    )
    return [operation for operation in PUBLIC_IDENTITY_ITEM_OPERATIONS if operation in management]
