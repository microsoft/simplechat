# functions_group_prompt_policy.py
"""Group prompt management capability projections.

These are interface hints only. Every prompt route reauthorizes membership,
role and group status independently: a projection here never grants access.

The vocabulary is deliberately small. Group prompts have no screening, no
revisions, no source blobs and no per-creator ownership, so a prompt's eligible
operations follow directly from the caller's role and the group's status. The
same status matrix the M2B document slice uses is reused verbatim so the two
surfaces read the same way to an operator.
"""


GROUP_PROMPT_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
GROUP_PROMPT_READER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
# Statuses a reader may browse. ``inactive`` and any unrecognized status are
# denied outright, never treated as active.
GROUP_PROMPT_READ_STATUSES = frozenset({"active", "locked", "upload_disabled"})
# Workspace-level management capabilities, ordered for a stable projection.
GROUP_PROMPT_OPERATIONS = ("create", "edit", "delete")
# The per-prompt subset. ``create`` is a workspace capability, not a property of
# an existing prompt, so it is never a per-item action.
GROUP_PROMPT_ITEM_OPERATIONS = ("edit", "delete")


def group_prompt_management_operations(group, role, settings):
    """The workspace-level prompt operations a caller may perform.

    Mirrors V1's ``canManageGroupPrompts()``, which requires a manager role and
    an ``active`` group for all prompt management. Unlike the document rules,
    ``upload_disabled`` does not permit deletes here: V1 never distinguished the
    prompt statuses, so any non-``active`` status is read-only.
    """
    if role not in GROUP_PROMPT_MANAGER_ROLES or not settings.get("enable_group_workspaces", False):
        return []
    if group.get("status", "active") != "active":
        return []
    return list(GROUP_PROMPT_OPERATIONS)


def group_prompt_actions(prompt, group, role, settings):
    """The operations advertised for a single prompt.

    Prompts carry no per-item eligibility beyond the workspace policy, so this
    is the management projection intersected with the per-item vocabulary. It
    still takes ``prompt`` so the read projector computes actions per record and
    so a future per-prompt rule has one place to live.
    """
    operations = set(group_prompt_management_operations(group, role, settings))
    return [operation for operation in GROUP_PROMPT_ITEM_OPERATIONS if operation in operations]
