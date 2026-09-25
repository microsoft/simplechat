# functions_workspace_context.py

"""Safe, explicitly scoped context for the shared V2 workspace shell.

This projection describes navigation and operation eligibility, not authorization
to a particular document or resource. Resource routes must still check access.
"""

import re
from urllib.parse import quote

from functions_file_sync import is_file_sync_enabled_for_group
from functions_governance import is_governance_access_allowed
from functions_group import (
    assert_group_role,
    check_group_status_allows_operation,
    find_group_by_id,
    get_user_role_in_group,
)
from functions_group_document_policy import (
    group_document_collaboration_operations,
    group_document_management_operations,
)
from functions_group_prompt_policy import group_prompt_management_operations
from functions_group_action_policy import (
    group_action_management_operations,
    group_actions_available,
)
from functions_group_agent_policy import (
    group_agent_management_operations,
    group_agents_available,
)
from functions_group_identity_policy import (
    group_identities_available,
    group_identity_management_operations,
)
from functions_group_endpoint_policy import (
    GROUP_ENDPOINTS_DISABLED_REASON,
    GROUP_ENDPOINT_WRITE_ROLES,
    group_endpoint_management_operations,
    group_endpoints_available,
)
from functions_group_file_source_policy import (
    group_file_source_management_operations,
    group_file_sources_available,
)
from functions_group_membership_policy import GROUP_MEMBERSHIP_MANAGER_ROLES
from functions_group_settings_policy import (
    GROUP_MANAGER_REQUIRED,
    GROUP_SETTINGS_MANAGER_ROLES,
    build_group_settings_management,
    group_settings_decisions,
)
try:
    from functions_group_settings import REFUSAL_MESSAGES
except ImportError:
    # Isolated context tests load this module with a stubbed functions_group; keep the
    # navigation seam tied to the one server text it needs without importing the full
    # settings writer boundary in that harness.
    REFUSAL_MESSAGES = {GROUP_MANAGER_REQUIRED: "Only the group owner or an admin can do this."}
from functions_settings import (
    get_group_workflow_management_roles,
    is_group_workflows_enabled_for_group,
    is_group_workspace_file_download_enabled,
    is_public_workspace_file_download_enabled,
)
from functions_workspace_branding import get_workspace_logo_metadata, normalize_workspace_hero_color
from functions_workspace_sections import WORKSPACE_SECTION_GROUPS
from functions_public_document_policy import (
    public_document_collaboration_operations,
    public_document_management_operations,
)
from functions_public_workspaces import (
    check_public_workspace_status_allows_operation,
    find_public_workspace_by_id,
    get_user_role_in_public_workspace,
)


GROUP_READER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
GROUP_CONTENT_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
GROUP_STATUSES = ("active", "locked", "upload_disabled", "inactive")
PUBLIC_READER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
PUBLIC_CONTENT_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
PUBLIC_STATUSES = ("active", "locked", "upload_disabled", "inactive")
INVALID_SCOPE_ID = re.compile(r"[/\\?#\x00-\x1f\x7f]")
# The group-only navigation group that holds workspace management sections (M7B Members;
# M7C adds settings, activity and statistics to it).
GROUP_MANAGE_SECTION_GROUP = "manage"


class WorkspaceContextError(Exception):
    """An expected, user-safe context lookup failure."""

    def __init__(self, public_message, status_code):
        super().__init__(public_message)
        self.public_message = public_message
        self.status_code = status_code


def build_group_workspace_context(user_id, group_id, settings, *, user_info=None):
    """Resolve one authorized group without reading or changing active preferences."""
    if (
        not isinstance(group_id, str)
        or not group_id
        or group_id in (".", "..")
        or group_id != group_id.strip()
        or INVALID_SCOPE_ID.search(group_id)
    ):
        raise WorkspaceContextError("Invalid group identifier.", 400)
    if not user_id or not settings.get("enable_group_workspaces", False):
        raise WorkspaceContextError("Group workspaces are unavailable.", 403)

    try:
        assert_group_role(user_id, group_id, allowed_roles=GROUP_READER_ROLES)
    except PermissionError as exc:
        raise WorkspaceContextError("You do not have access to the selected group.", 403) from exc
    except LookupError as exc:
        raise WorkspaceContextError("The selected group was not found.", 404) from exc
    group = find_group_by_id(group_id)
    if not group:
        raise WorkspaceContextError("The selected group was not found.", 404)
    # Recheck the returned snapshot as membership may have changed since the guard's read.
    role = get_user_role_in_group(group, user_id)
    if role not in GROUP_READER_ROLES:
        raise WorkspaceContextError("You do not have access to the selected group.", 403)

    stored_status = group.get("status", "active")
    status = stored_status if stored_status in GROUP_STATUSES else "unknown"
    view_allowed, status_reason = check_group_status_allows_operation(group, "view")
    if status == "unknown":
        view_allowed = False
        status_reason = "This group's status is not recognized. Contact an administrator."
    active = status == "active"
    manager = role in GROUP_CONTENT_MANAGER_ROLES
    automation_manager = role in get_group_workflow_management_roles(settings)
    semantic_kernel = bool(settings.get("enable_semantic_kernel", False))
    file_sync_enabled = is_file_sync_enabled_for_group(settings, group_id, user_info=user_info)
    sync_enabled = manager and file_sync_enabled
    # The single availability predicate the immutable identity routes also call, so
    # the Identities section and the routes agree on one gate (Semantic Kernel or
    # File Sync). ``manager`` still gates the section, so this stays manager-only.
    identities_available, _identities_reason = group_identities_available(
        settings, group_id, user_info=user_info, file_sync_enabled=file_sync_enabled,
    )
    # The single availability predicate the immutable file source routes also call,
    # so the Sync section and the routes agree on one gate (File Sync for this
    # group). ``manager`` still gates the section, so this stays manager-only.
    file_sources_available, _file_sources_reason = group_file_sources_available(
        settings, group_id, user_info=user_info, file_sync_enabled=file_sync_enabled,
    )

    delegation_configured = semantic_kernel and bool(settings.get("allow_group_agents", False))
    delegation_allowed = delegation_configured and is_governance_access_allowed("governance_group_agents", user_id)
    # The single availability predicate the immutable agent routes also call, so
    # the Agents section and the routes agree on one gate (mirrors actions/B3).
    agents_available, agents_reason = group_agents_available(user_id, settings)
    actions_available, actions_reason = group_actions_available(user_id, settings)
    # The same one-predicate rule for the immutable-target endpoint routes (M5C).
    endpoints_available, endpoints_reason = group_endpoints_available(user_id, settings)
    workflows_enabled = is_group_workflows_enabled_for_group(settings, group_id)

    def section(enabled, can_manage=False, reason="This section is not enabled for this group."):
        available = bool(view_allowed and enabled)
        return {
            "enabled": available,
            "can_manage": bool(available and active and can_manage),
            "reason": None if available else (status_reason if not view_allowed else reason),
        }

    governance_reason = "Your administrator has restricted access to this capability."
    manager_reason = "Your role does not permit managing this group's connections."
    sections = {
        "documents": section(True, manager),
        "tags": section(True, manager),
        "prompts": section(True, manager),
        "agents": section(
            agents_available, automation_manager,
            agents_reason or "Group agents are not enabled.",
        ),
        "actions": section(
            actions_available, automation_manager,
            actions_reason or "Group actions are not enabled.",
        ),
        "endpoints": section(
            endpoints_available, role in GROUP_ENDPOINT_WRITE_ROLES,
            endpoints_reason or GROUP_ENDPOINTS_DISABLED_REASON,
        ),
        "workflows": section(
            workflows_enabled, automation_manager,
            "Workflows are not enabled or assigned to this group.",
        ),
        "identities": section(
            manager and identities_available, manager,
            manager_reason if not manager else "Identities require File Sync or Semantic Kernel.",
        ),
        "sync": section(
            sync_enabled, manager,
            manager_reason if not manager else "File Sync is not available for this group.",
        ),
    }
    for section_id, entry in sections.items():
        entry["group"] = WORKSPACE_SECTION_GROUPS[section_id]
    # Members (M7B) is a group-only section in the "manage" group, so the personal section
    # registry and its groups are untouched. Every member may open it in any status that
    # lets them view the group, like every other section; which membership controls it
    # offers comes from the member list's own hints, never from this navigation entry.
    sections["members"] = {
        **section(True, role in GROUP_MEMBERSHIP_MANAGER_ROLES),
        "group": GROUP_MANAGE_SECTION_GROUP,
    }
    # Settings, Activity and Statistics (M7C) join Members in the "manage" group. Their
    # availability is the native group settings decision, so the navigation, the settings
    # read and the routes agree on one gate: Settings and both insight views open to a
    # manager (Owner or Admin), in any status that lets the caller view the group, and the
    # controls each offers still come from settings_management, never from this entry.
    manage_manager = role in GROUP_SETTINGS_MANAGER_ROLES
    manage_decisions = group_settings_decisions(role, group, settings, (user_info or {}).get("roles"))
    manage_reason = REFUSAL_MESSAGES[GROUP_MANAGER_REQUIRED]
    sections["settings"] = {
        **section(manage_manager, manage_manager, manage_reason),
        "group": GROUP_MANAGE_SECTION_GROUP,
    }
    sections["activity"] = {
        **section(manage_decisions["view_activity"] is None, reason=manage_reason),
        "group": GROUP_MANAGE_SECTION_GROUP,
    }
    sections["statistics"] = {
        **section(manage_decisions["view_stats"] is None, reason=manage_reason),
        "group": GROUP_MANAGE_SECTION_GROUP,
    }

    logo = get_workspace_logo_metadata(group)
    owner = group.get("owner") or {}
    return {
        "schema_version": 1,
        "enabled": True,
        "viewer_id": user_id,
        "scope": {"kind": "group", "id": group_id},
        "workspace": {
            "name": str(group.get("name") or "Untitled group"),
            "description": str(group.get("description") or ""),
            "owner": {
                "display_name": str(owner.get("displayName") or ""),
                "email": str(owner.get("email") or ""),
            },
            "hero_color": normalize_workspace_hero_color(group.get("heroColor")),
            "logo_url": (
                f"/api/groups/{quote(group_id, safe='')}/logo?v={logo['logoVersion']}"
                if logo["hasLogo"] else None
            ),
        },
        "role": role,
        "status": status,
        "can_manage_workspace": role in ("Owner", "Admin"),
        "sections": sections,
        "native_delegation": {
            **section(
                delegation_allowed,
                automation_manager and bool(settings.get("allow_group_plugins", False)),
                governance_reason if delegation_configured else "Group agents are not enabled.",
            ),
            "group": "automation",
        },
        "document_permissions": {
            "can_view": bool(view_allowed),
            "can_chat": bool(view_allowed and check_group_status_allows_operation(group, "chat")[0]),
            "can_upload": bool(manager and active),
            "can_edit": bool(manager and active),
            "can_delete": bool(manager and view_allowed and check_group_status_allows_operation(group, "delete")[0]),
            "can_download": bool(
                manager and view_allowed and is_group_workspace_file_download_enabled(settings, group)
            ),
        },
        "document_queries": {
            "sort_fields": [
                "_ts", "file_name", "title", "upload_date", "file_size",
                "number_of_pages", "version", "document_classification",
            ],
            "facets": True,
            "places": True,
        },
        "document_management": {
            "schema_version": 1,
            "operations": group_document_management_operations(
                group, role, settings,
                download_enabled=is_group_workspace_file_download_enabled(settings, group),
            ),
        },
        "document_collaboration": {
            "schema_version": 1,
            "operations": group_document_collaboration_operations(group, role, settings),
        },
        "prompt_management": {
            "schema_version": 1,
            "operations": group_prompt_management_operations(group, role, settings),
        },
        "action_management": {
            "schema_version": 1,
            "operations": group_action_management_operations(
                user_id, group, role, settings, available=actions_available,
            ),
        },
        "agent_management": {
            "schema_version": 1,
            "operations": group_agent_management_operations(
                user_id, group, role, settings, available=agents_available,
            ),
        },
        "identity_management": {
            "schema_version": 1,
            "operations": group_identity_management_operations(
                role, group, settings, available=identities_available,
            ),
        },
        "endpoint_management": {
            "schema_version": 1,
            "operations": group_endpoint_management_operations(
                user_id, group, role, settings, available=endpoints_available,
            ),
        },
        "file_source_management": {
            "schema_version": 1,
            "operations": group_file_source_management_operations(
                role, group, settings, available=file_sources_available,
            ),
        },
        # The decision the native group settings routes enforce and their settings read
        # publishes; the header offers Settings from it without an extra read.
        "settings_management": build_group_settings_management(
            role, group, settings, (user_info or {}).get("roles"),
        ),
    }


def build_public_workspace_context(user_id, workspace_id, settings, *, user_info=None):
    """Resolve one explicit public workspace without reading or changing active preferences.

    This is the read-only M3A slice. The workspace is always taken from the caller's
    explicit target, never from a stored active-workspace preference, and this context
    is an interface hint only: every document route reauthorizes independently.
    """
    if (
        not isinstance(workspace_id, str)
        or not workspace_id
        or workspace_id in (".", "..")
        or workspace_id != workspace_id.strip()
        or INVALID_SCOPE_ID.search(workspace_id)
    ):
        raise WorkspaceContextError("Invalid public workspace identifier.", 400)
    if not user_id or not settings.get("enable_public_workspaces", False):
        raise WorkspaceContextError("Public workspaces are unavailable.", 403)

    workspace = find_public_workspace_by_id(workspace_id)
    if not workspace:
        raise WorkspaceContextError("The selected public workspace was not found.", 404)
    role = get_user_role_in_public_workspace(workspace, user_id)
    if role not in PUBLIC_READER_ROLES:
        raise WorkspaceContextError("You do not have access to the selected public workspace.", 403)

    stored_status = workspace.get("status", "active")
    status = stored_status if stored_status in PUBLIC_STATUSES else "unknown"
    view_allowed, status_reason = check_public_workspace_status_allows_operation(workspace, "view")
    if status == "unknown":
        view_allowed = False
        status_reason = "This workspace's status is not recognized. Contact an administrator."
    active = status == "active"
    manager = role in PUBLIC_CONTENT_MANAGER_ROLES

    def section(enabled, can_manage=False, reason="This section is not available for public workspaces yet."):
        available = bool(view_allowed and enabled)
        return {
            "enabled": available,
            "can_manage": bool(available and active and can_manage),
            "reason": None if available else (status_reason if not view_allowed else reason),
        }

    # Public workspaces offer read-only document browsing, and a manager of an active
    # workspace manages the documents section. Tags, prompts, identities and sync are
    # listed but not yet available (M9C/M10B). Sections public workspaces will never
    # have -- agents, actions, endpoints and workflows -- are left out of the registry
    # entirely rather than shown as "not available yet".
    sections = {
        "documents": section(True, manager),
        "tags": section(False),
        "prompts": section(False),
        "identities": section(False),
        "sync": section(False),
    }
    for section_id, entry in sections.items():
        entry["group"] = WORKSPACE_SECTION_GROUPS[section_id]

    logo = get_workspace_logo_metadata(workspace)
    owner = workspace.get("owner") or {}
    return {
        "schema_version": 1,
        "enabled": True,
        "viewer_id": user_id,
        "scope": {"kind": "public", "id": workspace_id},
        "workspace": {
            "name": str(workspace.get("name") or "Untitled workspace"),
            "description": str(workspace.get("description") or ""),
            "owner": {
                "display_name": str(owner.get("displayName") or ""),
                "email": str(owner.get("email") or ""),
            },
            "hero_color": normalize_workspace_hero_color(workspace.get("heroColor")),
            "logo_url": (
                f"/api/public_workspaces/{quote(workspace_id, safe='')}/logo?v={logo['logoVersion']}"
                if logo["hasLogo"] else None
            ),
        },
        "role": role,
        "status": status,
        "can_manage_workspace": role in ("Owner", "Admin"),
        "sections": sections,
        "document_permissions": {
            "can_view": bool(view_allowed),
            "can_chat": bool(view_allowed and check_public_workspace_status_allows_operation(workspace, "chat")[0]),
            "can_upload": bool(manager and active),
            "can_edit": bool(manager and active),
            "can_delete": bool(
                manager and view_allowed
                and check_public_workspace_status_allows_operation(workspace, "delete")[0]
            ),
            "can_download": bool(
                manager and view_allowed and is_public_workspace_file_download_enabled(settings, workspace)
            ),
        },
        "document_management": {
            "schema_version": 1,
            "operations": public_document_management_operations(
                workspace, role, settings,
                download_enabled=is_public_workspace_file_download_enabled(settings, workspace),
            ),
        },
        "document_collaboration": {
            "schema_version": 1,
            "operations": public_document_collaboration_operations(workspace, role, settings),
        },
        "document_queries": {
            "sort_fields": [
                "_ts", "file_name", "title", "upload_date", "file_size",
                "number_of_pages", "version", "document_classification",
            ],
            "facets": True,
            "places": True,
        },
    }
