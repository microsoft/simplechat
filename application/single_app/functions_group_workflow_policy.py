# functions_group_workflow_policy.py
"""Group workspace workflow capability projection.

An interface hint only. Every ``/api/group/workflows`` route reauthorizes the caller's
membership and role independently: a projection here never grants access.

Running a group workflow and cancelling its active run are member operations. The run,
cancel, run-cancel and resume-failed routes resolve the group with
:data:`GROUP_WORKFLOW_MEMBER_ROLES`, every group role. Creating, editing and deleting are
management operations, for the roles ``get_group_workflow_management_roles(settings)``
names.

Those routes check no group status. The V2 workflows section has only ever offered its
controls in an ``active`` group, so this projection narrows the routes on status rather
than widening V2: every other status offers nothing.
"""


# The roles the group workflow run, cancel, run-cancel and resume-failed routes accept.
GROUP_WORKFLOW_MEMBER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
# What those member routes do, in a stable order.
GROUP_WORKFLOW_MEMBER_OPERATIONS = ("run", "cancel")
# What the management routes (save and delete) do: creating, editing and deleting a workflow.
GROUP_WORKFLOW_MANAGER_OPERATIONS = ("create", "edit", "delete")


def group_workflow_management_operations(role, group, *, available, manager):
    """The workflow operations a caller may perform on a group's workflows in V2.

    ``available`` is whether the group's workflows can be opened at all (workflows
    enabled and assigned to this group, and the group viewable); ``manager`` is whether
    ``role`` is one of the settings' workflow management roles. Both are resolved once
    by the caller, as the workspace context resolves its sections. Empty unless the
    group is ``active``.
    """
    if not available or group.get("status", "active") != "active":
        return []
    operations = []
    if role in GROUP_WORKFLOW_MEMBER_ROLES:
        operations.extend(GROUP_WORKFLOW_MEMBER_OPERATIONS)
    if manager:
        operations.extend(GROUP_WORKFLOW_MANAGER_OPERATIONS)
    return operations
