# functions_public_prompt_policy.py
"""Public-workspace prompt management capability projections.

Version: 0.261.178
Implemented in: 0.261.178

These are interface hints only. Every prompt route reauthorizes membership,
role and workspace status independently: a projection here never grants access.

The vocabulary mirrors the group prompt policy exactly, because a public
workspace's prompts behave the same way once the caller's role and the
workspace's status are known -- no screening, revisions, source blobs or
per-creator ownership. The one deliberate difference from the shared public
status helper (``check_public_workspace_status_allows_operation``) is that these
projections use an **explicit** status allowlist: an unrecognized status is
denied, never silently treated as ``active``.
"""


PUBLIC_PROMPT_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
PUBLIC_PROMPT_READER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
# Statuses a reader may browse. ``inactive`` and any unrecognized status are
# denied outright, never treated as active. This matches the public document
# read set (``PUBLIC_DOCUMENT_READ_STATUSES``) so the two surfaces read the same.
PUBLIC_PROMPT_READ_STATUSES = frozenset({"active", "locked", "upload_disabled"})
# Workspace-level management capabilities, ordered for a stable projection.
PUBLIC_PROMPT_OPERATIONS = ("create", "edit", "delete")
# The per-prompt subset. ``create`` is a workspace capability, not a property of
# an existing prompt, so it is never a per-item action.
PUBLIC_PROMPT_ITEM_OPERATIONS = ("edit", "delete")


def public_prompt_management_operations(workspace, role, settings):
    """The workspace-level prompt operations a caller may perform.

    Management needs a manager role and an ``active`` workspace. As with group
    prompts, no non-``active`` status permits a write: ``locked`` and
    ``upload_disabled`` are read-only for prompts, and ``inactive`` and unknown
    statuses are read-only too, since the allowlist below is exact.
    """
    if role not in PUBLIC_PROMPT_MANAGER_ROLES or not settings.get("enable_public_workspaces", False):
        return []
    if workspace.get("status", "active") != "active":
        return []
    return list(PUBLIC_PROMPT_OPERATIONS)


def public_prompt_actions(prompt, workspace, role, settings):
    """The operations advertised for a single prompt.

    Prompts carry no per-item eligibility beyond the workspace policy, so this
    is the management projection intersected with the per-item vocabulary. It
    still takes ``prompt`` so the read projector computes actions per record and
    so a future per-prompt rule has one place to live.
    """
    operations = set(public_prompt_management_operations(workspace, role, settings))
    return [operation for operation in PUBLIC_PROMPT_ITEM_OPERATIONS if operation in operations]
