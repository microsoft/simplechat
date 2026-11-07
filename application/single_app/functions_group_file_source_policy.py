# functions_group_file_source_policy.py
"""Group workspace file source management capability projections.

These are interface hints only. Every file source route reauthorizes membership,
role and group status independently: a projection here never grants access.

Like group identities, group file sources are a manager-only surface for both
reads and writes, matching the classic interface and today's
``/api/file-sync/sources`` group routes. There is one availability predicate,
:func:`group_file_sources_available`, shared with the workspace context's
``sections.sync`` so the section, the projection and the routes all read the
same gate.
"""


# Reads and writes both require a content-manager role; ordinary members cannot
# list group file sources today, and M5B keeps that.
GROUP_FILE_SOURCE_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
# Statuses a manager may browse. ``inactive`` and any unrecognized status are
# denied outright, never treated as active.
GROUP_FILE_SOURCE_READ_STATUSES = frozenset({"active", "locked", "upload_disabled"})
# Workspace-level management capabilities, ordered for a stable projection.
# ``sync`` queues a run and ``test`` probes credentials, so both are management
# capabilities that require an active workspace, not read-only browsing.
GROUP_FILE_SOURCE_OPERATIONS = ("create", "edit", "delete", "sync", "test")
# The per-source subset. ``create`` is a workspace capability, not a property of
# an existing source, so it is never a per-item action.
GROUP_FILE_SOURCE_ITEM_OPERATIONS = ("edit", "delete", "sync", "test")

# The reason the shared shell shows when the surface is unavailable. Unlike
# identities, file sources require File Sync specifically; Semantic Kernel does
# not enable them.
GROUP_FILE_SOURCES_UNAVAILABLE_REASON = "File sources require File Sync."


def group_file_sources_available(settings, group_id, *, user_info=None, file_sync_enabled=None):
    """The single availability predicate for the whole native group file source surface.

    Returns ``(available, reason)``. Group file sources are offered only when
    File Sync is enabled for this group. This is the one place that flag is
    resolved, so the context's Sync section, the management projection and every
    immutable route agree.

    ``file_sync_enabled`` may carry the caller's precomputed
    ``is_file_sync_enabled_for_group`` result (the context resolves it once for
    its Sync section) so this predicate does not repeat the lookup. The routes
    pass nothing and resolve it here with ``user_info`` so the
    ``file_sync_group_admin_only`` toggle is evaluated against the caller.
    """
    if file_sync_enabled is None:
        from functions_file_sync import is_file_sync_enabled_for_group

        file_sync_enabled = is_file_sync_enabled_for_group(settings, group_id, user_info=user_info)
    if file_sync_enabled:
        return True, None
    return False, GROUP_FILE_SOURCES_UNAVAILABLE_REASON


def group_file_source_management_operations(role, group, settings, *, available):
    """The workspace-level file source operations a caller may perform.

    The surface must be available (File Sync enabled for the group), the caller
    must hold a manager role, and the group must be ``active``. Any non-``active``
    status is read-only. Empty when the surface is unavailable, so the projection
    and the routes cannot offer management a disabled tenant forbids.

    ``available`` is always supplied by the access layer, which resolves the
    predicate once per request; the surface's availability depends on tenant
    flags and the caller's File Sync eligibility, not on a value this projection
    can recompute on its own.
    """
    if not available:
        return []
    if role not in GROUP_FILE_SOURCE_MANAGER_ROLES:
        return []
    if group.get("status", "active") != "active":
        return []
    return list(GROUP_FILE_SOURCE_OPERATIONS)


def group_file_source_actions(role, group, settings, *, available):
    """The operations advertised for a single file source.

    ``edit``, ``delete``, ``sync`` and ``test`` come from the management
    projection intersected with the per-item vocabulary, computed fresh so a
    stored ``source_actions`` can never be served.
    """
    management = set(
        group_file_source_management_operations(role, group, settings, available=available)
    )
    return [operation for operation in GROUP_FILE_SOURCE_ITEM_OPERATIONS if operation in management]
