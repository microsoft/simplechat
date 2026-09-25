# functions_public_file_source_policy.py
"""Public workspace file source management capability projections.

Version: 0.261.179
Implemented in: 0.261.179

These are interface hints only. Every file source route reauthorizes membership,
role and public workspace status independently: a projection here never grants
access.

Like public identities, public file sources are a manager-only surface for both
reads and writes. There is one availability predicate,
:func:`public_file_sources_available`, shared with the workspace context's
``sections.sync`` so the section, the projection and the routes all read the same
gate. It rests solely on File Sync being enabled for the workspace -- a public
workspace has no Semantic Kernel actions, so nothing else can turn the surface on.
"""


# Reads and writes both require a content-manager role; an ordinary reader cannot
# list public file sources.
PUBLIC_FILE_SOURCE_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
# Statuses a manager may browse. ``inactive`` and any unrecognized status are
# denied outright, never treated as active.
PUBLIC_FILE_SOURCE_READ_STATUSES = frozenset({"active", "locked", "upload_disabled"})
# Workspace-level management capabilities, ordered for a stable projection.
# ``sync`` queues a run and ``test`` probes credentials, so both are management
# capabilities that require an active workspace, not read-only browsing.
PUBLIC_FILE_SOURCE_OPERATIONS = ("create", "edit", "delete", "sync", "test")
# The per-source subset. ``create`` is a workspace capability, not a property of
# an existing source, so it is never a per-item action.
PUBLIC_FILE_SOURCE_ITEM_OPERATIONS = ("edit", "delete", "sync", "test")

# The reason the shared shell shows when the surface is unavailable.
PUBLIC_FILE_SOURCES_UNAVAILABLE_REASON = "File sources require File Sync."


def public_file_sources_available(settings, workspace_id, *, user_info=None, file_sync_enabled=None):
    """The single availability predicate for the whole native public file source surface.

    Returns ``(available, reason)``. Public file sources are offered only when
    File Sync is enabled for this workspace. This is the one place that flag is
    resolved, so the context's Sync section, the management projection and every
    immutable route agree.

    ``file_sync_enabled`` may carry the caller's precomputed
    ``is_file_sync_enabled_for_public_workspace`` result (the context resolves it
    once for its Sync section) so this predicate does not repeat the lookup. The
    routes pass nothing and resolve it here with ``user_info``.
    """
    if file_sync_enabled is None:
        from functions_file_sync import is_file_sync_enabled_for_public_workspace

        file_sync_enabled = is_file_sync_enabled_for_public_workspace(
            settings, workspace_id, user_info=user_info
        )
    if file_sync_enabled:
        return True, None
    return False, PUBLIC_FILE_SOURCES_UNAVAILABLE_REASON


def public_file_source_management_operations(role, workspace, settings, *, available):
    """The workspace-level file source operations a caller may perform.

    The surface must be available (File Sync enabled for the workspace), the
    caller must hold a manager role, and the workspace must be ``active``. Any
    non-``active`` status is read-only. Empty when the surface is unavailable, so
    the projection and the routes cannot offer management a disabled tenant forbids.
    """
    if not available:
        return []
    if role not in PUBLIC_FILE_SOURCE_MANAGER_ROLES:
        return []
    if workspace.get("status", "active") != "active":
        return []
    return list(PUBLIC_FILE_SOURCE_OPERATIONS)


def public_file_source_actions(role, workspace, settings, *, available):
    """The operations advertised for a single file source.

    ``edit``, ``delete``, ``sync`` and ``test`` come from the management
    projection intersected with the per-item vocabulary, computed fresh so a
    stored ``source_actions`` can never be served.
    """
    management = set(
        public_file_source_management_operations(role, workspace, settings, available=available)
    )
    return [operation for operation in PUBLIC_FILE_SOURCE_ITEM_OPERATIONS if operation in management]
