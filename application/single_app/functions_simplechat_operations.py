# functions_simplechat_operations.py
"""Shared SimpleChat-native operations for routes and Semantic Kernel plugins."""

import logging
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

import requests
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from flask import current_app, has_app_context, session

from collaboration_models import normalize_collaboration_user
from config import (
    cosmos_activity_logs_container,
    cosmos_conversations_container,
    cosmos_groups_container,
    cosmos_messages_container,
)
from functions_activity_logging import (
    log_chat_activity,
    log_conversation_creation,
    log_document_upload,
    log_group_status_change,
    log_workflow_creation,
)
from functions_appinsights import log_event
from functions_authentication import (
    get_current_user_info,
    get_graph_endpoint,
    get_valid_access_token,
)
from functions_collaboration import (
    assert_user_can_participate_in_collaboration_conversation,
    create_collaboration_message_notifications,
    create_group_collaboration_conversation_record,
    create_personal_collaboration_conversation_record,
    get_collaboration_conversation,
    invite_personal_collaboration_participants,
    is_group_collaboration_conversation,
    persist_collaboration_message,
)
from functions_documents import allowed_file, create_document, process_document_upload_background, update_document
from functions_group import (
    assert_group_role,
    check_group_status_allows_operation,
    create_group,
    find_group_by_id,
    get_user_role_in_group,
    require_active_group,
)
from functions_notifications import create_notification
from functions_personal_workflows import save_personal_workflow
from functions_settings import get_settings, get_user_settings
from utils_cache import invalidate_group_search_cache, invalidate_personal_search_cache


SIMPLECHAT_PLUGIN_TYPE = "simplechat"
SIMPLECHAT_DEFAULT_ENDPOINT = "simplechat://internal"
SIMPLECHAT_CAPABILITY_TO_FUNCTION = {
    "create_group": "create_group",
    "add_group_member": "add_user_to_group",
    "make_group_inactive": "make_group_inactive",
    "create_group_conversation": "create_group_conversation",
    "invite_group_conversation_members": "invite_group_conversation_members",
    "add_conversation_message": "add_conversation_message",
    "upload_markdown_document": "upload_markdown_document",
    "create_personal_conversation": "create_personal_conversation",
    "create_personal_workflow": "create_personal_workflow",
    "create_personal_collaboration_conversation": "create_personal_collaboration_conversation",
}
SIMPLECHAT_CAPABILITY_DEFINITIONS = [
    {
        "key": "create_group",
        "function_name": SIMPLECHAT_CAPABILITY_TO_FUNCTION["create_group"],
        "label": "Create Groups",
        "description": "Create a new group workspace as the current user.",
    },
    {
        "key": "add_group_member",
        "function_name": SIMPLECHAT_CAPABILITY_TO_FUNCTION["add_group_member"],
        "label": "Add Group Members",
        "description": "Add a user directly to a group as a member, admin, or document manager.",
    },
    {
        "key": "make_group_inactive",
        "function_name": SIMPLECHAT_CAPABILITY_TO_FUNCTION["make_group_inactive"],
        "label": "Make Groups Inactive",
        "description": "Mark a group inactive using the current user's Control Center admin permissions.",
    },
    {
        "key": "create_group_conversation",
        "function_name": SIMPLECHAT_CAPABILITY_TO_FUNCTION["create_group_conversation"],
        "label": "Create Group Multi-User Conversations",
        "description": "Create an invite-managed multi-user conversation in a group the current user can access, then add current group members as participants to grant access.",
    },
    {
        "key": "invite_group_conversation_members",
        "function_name": SIMPLECHAT_CAPABILITY_TO_FUNCTION["invite_group_conversation_members"],
        "label": "Invite Group Conversation Members",
        "description": "Invite current group members into an existing invite-managed group multi-user conversation the current user manages.",
    },
    {
        "key": "add_conversation_message",
        "function_name": SIMPLECHAT_CAPABILITY_TO_FUNCTION["add_conversation_message"],
        "label": "Add Conversation Messages",
        "description": "Add a user-authored message to a personal or collaborative conversation the current user can access.",
    },
    {
        "key": "upload_markdown_document",
        "function_name": SIMPLECHAT_CAPABILITY_TO_FUNCTION["upload_markdown_document"],
        "label": "Upload Markdown Documents",
        "description": "Create and upload a Markdown document into the current user's personal workspace or an allowed group workspace.",
    },
    {
        "key": "create_personal_conversation",
        "function_name": SIMPLECHAT_CAPABILITY_TO_FUNCTION["create_personal_conversation"],
        "label": "Create Personal Conversations",
        "description": "Create a standard one-user personal conversation.",
    },
    {
        "key": "create_personal_workflow",
        "function_name": SIMPLECHAT_CAPABILITY_TO_FUNCTION["create_personal_workflow"],
        "label": "Create Personal Workflows",
        "description": "Create a personal workflow for the current user using the existing workflow engine and permissions.",
    },
    {
        "key": "create_personal_collaboration_conversation",
        "function_name": SIMPLECHAT_CAPABILITY_TO_FUNCTION["create_personal_collaboration_conversation"],
        "label": "Create Personal Collaborative Conversations",
        "description": "Create a personal collaborative conversation and invite other users.",
    },
]


def get_default_simplechat_capabilities() -> Dict[str, bool]:
    return {definition["key"]: True for definition in SIMPLECHAT_CAPABILITY_DEFINITIONS}


def normalize_simplechat_capabilities(raw_capabilities: Any = None) -> Dict[str, bool]:
    normalized = get_default_simplechat_capabilities()

    if raw_capabilities is None:
        return normalized

    if isinstance(raw_capabilities, dict):
        for capability_key in normalized:
            if capability_key in raw_capabilities:
                normalized[capability_key] = bool(raw_capabilities[capability_key])
        return normalized

    if isinstance(raw_capabilities, (list, tuple, set)):
        enabled_items = {str(item or "").strip() for item in raw_capabilities if str(item or "").strip()}
        return {
            definition["key"]: (
                definition["key"] in enabled_items or definition["function_name"] in enabled_items
            )
            for definition in SIMPLECHAT_CAPABILITY_DEFINITIONS
        }

    return normalized


def get_simplechat_enabled_function_names(raw_capabilities: Any = None) -> List[str]:
    normalized = normalize_simplechat_capabilities(raw_capabilities)
    return [
        definition["function_name"]
        for definition in SIMPLECHAT_CAPABILITY_DEFINITIONS
        if normalized.get(definition["key"], False)
    ]


def resolve_simplechat_action_capabilities(
    action_capability_map: Any,
    action_defaults: Any = None,
    action_id: Optional[str] = None,
    action_name: Optional[str] = None,
) -> Dict[str, bool]:
    resolved_defaults = normalize_simplechat_capabilities(action_defaults)

    if not isinstance(action_capability_map, dict):
        return resolved_defaults

    for candidate_key in (str(action_id or "").strip(), str(action_name or "").strip()):
        if candidate_key and candidate_key in action_capability_map:
            return normalize_simplechat_capabilities(action_capability_map.get(candidate_key))

    return resolved_defaults


def create_personal_conversation_for_current_user(
    title: str = "New Conversation",
    notify_creation: bool = False,
) -> Dict[str, Any]:
    current_user = _require_current_user_info()
    normalized_title = str(title or "").strip() or "New Conversation"
    conversation_id = str(uuid.uuid4())
    conversation_item = {
        "id": conversation_id,
        "user_id": current_user["userId"],
        "last_updated": datetime.utcnow().isoformat(),
        "title": normalized_title,
        "context": [],
        "tags": [],
        "strict": False,
        "is_pinned": False,
        "is_hidden": False,
        "chat_type": "new",
        "has_unread_assistant_response": False,
        "last_unread_assistant_message_id": None,
        "last_unread_assistant_at": None,
    }
    cosmos_conversations_container.upsert_item(conversation_item)

    log_conversation_creation(
        user_id=current_user["userId"],
        conversation_id=conversation_id,
        title=normalized_title,
        workspace_type="personal",
    )

    conversation_item["added_to_activity_log"] = True
    cosmos_conversations_container.upsert_item(conversation_item)

    if notify_creation:
        _notify_personal_conversation_created(
            conversation_item=conversation_item,
            current_user=current_user,
        )

    return conversation_item


def create_personal_workflow_for_current_user(
    name: str,
    task_prompt: str,
    description: str = "",
    runner_type: str = "model",
    trigger_type: str = "manual",
    selected_agent_name: str = "",
    selected_agent_id: str = "",
    selected_agent_is_global: bool = False,
    model_endpoint_id: str = "",
    model_id: str = "",
    alert_priority: str = "none",
    is_enabled: bool = True,
    schedule_value: int = 1,
    schedule_unit: str = "hours",
    conversation_id: str = "",
) -> Dict[str, Any]:
    _require_user_workflows_enabled()
    current_user_info = _require_current_user_info()

    normalized_runner_type = str(runner_type or "model").strip().lower() or "model"
    normalized_trigger_type = str(trigger_type or "manual").strip().lower() or "manual"
    workflow_payload = {
        "name": str(name or "").strip(),
        "description": str(description or "").strip(),
        "task_prompt": str(task_prompt or "").strip(),
        "runner_type": normalized_runner_type,
        "trigger_type": normalized_trigger_type,
        "alert_priority": str(alert_priority or "none").strip().lower() or "none",
        "is_enabled": bool(is_enabled) if normalized_trigger_type == "interval" else True,
        "conversation_id": str(conversation_id or "").strip(),
    }

    if normalized_runner_type == "agent":
        workflow_payload["selected_agent"] = {
            "id": str(selected_agent_id or "").strip(),
            "name": str(selected_agent_name or "").strip(),
            "is_global": bool(selected_agent_is_global),
        }
    else:
        workflow_payload["model_endpoint_id"] = str(model_endpoint_id or "").strip()
        workflow_payload["model_id"] = str(model_id or "").strip()

    if normalized_trigger_type == "interval":
        workflow_payload["schedule"] = {
            "value": int(schedule_value),
            "unit": str(schedule_unit or "hours").strip().lower() or "hours",
        }

    workflow = save_personal_workflow(
        current_user_info["userId"],
        workflow_payload,
        actor_user_id=current_user_info["userId"],
    )
    log_workflow_creation(
        user_id=current_user_info["userId"],
        workflow_id=str(workflow.get("id") or "").strip(),
        workflow_name=str(workflow.get("name") or "").strip(),
        runner_type=workflow.get("runner_type"),
        trigger_type=workflow.get("trigger_type"),
    )
    return {
        "workflow": workflow,
        "message": f"Created workflow '{workflow.get('name', 'Workflow')}'.",
    }


def add_conversation_message_for_current_user(
    conversation_id: str,
    content: str,
    reply_to_message_id: str = "",
) -> Dict[str, Any]:
    current_user_info = _require_current_user_info()
    normalized_conversation_id = str(conversation_id or "").strip()
    normalized_content = str(content or "").strip()
    normalized_reply_to_message_id = str(reply_to_message_id or "").strip() or None

    if not normalized_conversation_id:
        raise ValueError("conversation_id is required")
    if not normalized_content:
        raise ValueError("content is required")

    try:
        conversation_item = cosmos_conversations_container.read_item(
            item=normalized_conversation_id,
            partition_key=normalized_conversation_id,
        )
    except CosmosResourceNotFoundError:
        conversation_item = None

    if conversation_item is not None:
        if str(conversation_item.get("user_id") or "").strip() != current_user_info["userId"]:
            raise PermissionError("Conversation not found or not accessible for the current user")

        message_doc, updated_conversation = _persist_personal_conversation_message(
            conversation_item=conversation_item,
            current_user_info=current_user_info,
            content=normalized_content,
            reply_to_message_id=normalized_reply_to_message_id,
        )
        return {
            "conversation": updated_conversation,
            "message": message_doc,
            "conversation_kind": "personal",
        }

    current_user = normalize_collaboration_user(current_user_info)
    if not current_user:
        raise PermissionError("User not authenticated")

    try:
        collaboration_conversation = get_collaboration_conversation(normalized_conversation_id)
    except CosmosResourceNotFoundError as exc:
        raise LookupError("Conversation was not found") from exc

    assert_user_can_participate_in_collaboration_conversation(
        current_user["user_id"],
        collaboration_conversation,
    )
    message_doc, updated_conversation = persist_collaboration_message(
        collaboration_conversation,
        current_user,
        normalized_content,
        reply_to_message_id=normalized_reply_to_message_id,
    )
    create_collaboration_message_notifications(updated_conversation, message_doc)
    return {
        "conversation": updated_conversation,
        "message": message_doc,
        "conversation_kind": "collaboration",
    }


def upload_markdown_document_for_current_user(
    file_name: str,
    markdown_content: str,
    workspace_scope: str = "personal",
    group_id: str = "",
    default_group_id: str = "",
) -> Dict[str, Any]:
    current_user_info = _require_current_user_info()
    current_user_id = current_user_info["userId"]
    normalized_workspace_scope = _normalize_document_workspace_scope(workspace_scope)
    normalized_file_name = _normalize_markdown_file_name(file_name)
    raw_markdown_content = str(markdown_content or "")

    if not raw_markdown_content.strip():
        raise ValueError("markdown_content is required")
    if not allowed_file(normalized_file_name, allowed_extensions={"md"}):
        raise ValueError("Only Markdown files are supported")

    document_id = str(uuid.uuid4())
    encoded_markdown_content = raw_markdown_content.encode("utf-8")
    temp_file_path = _write_temp_markdown_file(raw_markdown_content)
    resolved_group_id = None

    try:
        if normalized_workspace_scope == "group":
            resolved_group_id = _resolve_group_upload_target_for_current_user(
                current_user_id,
                group_id=group_id,
                default_group_id=default_group_id,
            )
            create_document(
                file_name=normalized_file_name,
                group_id=resolved_group_id,
                user_id=current_user_id,
                document_id=document_id,
                num_file_chunks=0,
                status="Queued for processing",
            )
            update_document(
                document_id=document_id,
                user_id=current_user_id,
                group_id=resolved_group_id,
                percentage_complete=0,
            )
        else:
            create_document(
                file_name=normalized_file_name,
                user_id=current_user_id,
                document_id=document_id,
                num_file_chunks=0,
                status="Queued for processing",
            )
            update_document(
                document_id=document_id,
                user_id=current_user_id,
                percentage_complete=0,
            )

        _queue_document_upload_background_task(
            document_id=document_id,
            user_id=current_user_id,
            temp_file_path=temp_file_path,
            original_filename=normalized_file_name,
            group_id=resolved_group_id,
        )

        if normalized_workspace_scope == "group":
            invalidate_group_search_cache(resolved_group_id)
            log_document_upload(
                user_id=current_user_id,
                container_type="group",
                document_id=document_id,
                file_size=len(encoded_markdown_content),
                file_type=".md",
            )
        else:
            invalidate_personal_search_cache(current_user_id)
            log_document_upload(
                user_id=current_user_id,
                container_type="personal",
                document_id=document_id,
                file_size=len(encoded_markdown_content),
                file_type=".md",
            )

        return {
            "document": {
                "id": document_id,
                "file_name": normalized_file_name,
                "status": "Queued for processing",
                "workspace_scope": normalized_workspace_scope,
                "group_id": resolved_group_id,
            },
            "message": f"Queued Markdown document '{normalized_file_name}' for processing.",
        }
    except Exception:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise


def create_group_for_current_user(name: str, description: str = "") -> Dict[str, Any]:
    settings = _require_group_workspaces_enabled()
    _require_group_creation_enabled(settings)
    normalized_name = str(name or "").strip() or "Untitled Group"
    normalized_description = str(description or "").strip()
    current_user = _require_current_user_info()
    group_doc = create_group(normalized_name, normalized_description)
    _notify_group_created(group_doc=group_doc, actor_user=current_user)
    return group_doc


def make_group_inactive_for_current_user(
    group_id: str = "",
    reason: str = "",
    default_group_id: str = "",
) -> Dict[str, Any]:
    current_user_info = _require_current_user_info()
    admin_session_user = _require_control_center_admin_access()

    resolved_group_id = str(group_id or default_group_id or "").strip()
    if not resolved_group_id:
        resolved_group_id = require_active_group(current_user_info["userId"])

    group_doc = find_group_by_id(resolved_group_id)
    if not group_doc:
        raise LookupError("Group not found")

    old_status = str(group_doc.get("status") or "active").strip() or "active"
    if old_status == "inactive":
        return {
            "group": group_doc,
            "old_status": old_status,
            "new_status": old_status,
            "message": f"Group '{group_doc.get('name', 'Unknown')}' is already inactive.",
        }

    changed_at = datetime.utcnow().isoformat()
    changed_by_user_id = str(admin_session_user.get("oid") or current_user_info.get("userId") or "").strip() or "unknown"
    changed_by_email = str(
        admin_session_user.get("preferred_username")
        or current_user_info.get("email")
        or current_user_info.get("userPrincipalName")
        or ""
    ).strip() or "unknown"
    normalized_reason = str(reason or "").strip()

    group_doc["status"] = "inactive"
    group_doc["modifiedDate"] = changed_at
    group_doc.setdefault("statusHistory", []).append(
        {
            "old_status": old_status,
            "new_status": "inactive",
            "changed_by_user_id": changed_by_user_id,
            "changed_by_email": changed_by_email,
            "changed_at": changed_at,
            "reason": normalized_reason,
        }
    )
    updated_group_doc = cosmos_groups_container.upsert_item(group_doc)

    log_group_status_change(
        group_id=resolved_group_id,
        group_name=str(group_doc.get("name") or "Unknown").strip() or "Unknown",
        old_status=old_status,
        new_status="inactive",
        changed_by_user_id=changed_by_user_id,
        changed_by_email=changed_by_email,
        reason=normalized_reason or None,
    )
    log_event(
        "[SimpleChat] Group marked inactive",
        {
            "group_id": resolved_group_id,
            "group_name": group_doc.get("name"),
            "old_status": old_status,
            "new_status": "inactive",
            "changed_by_user_id": changed_by_user_id,
            "changed_by_email": changed_by_email,
            "reason": normalized_reason,
        },
    )

    return {
        "group": updated_group_doc,
        "old_status": old_status,
        "new_status": "inactive",
        "message": f"Marked group '{group_doc.get('name', 'Unknown')}' as inactive.",
    }


def create_group_collaboration_conversation_for_current_user(
    title: str = "",
    group_id: str = "",
    default_group_id: str = "",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    _require_collaboration_feature_enabled()
    current_user_info = _require_current_user_info()
    current_user = normalize_collaboration_user(current_user_info)
    if not current_user:
        raise PermissionError("User not authenticated")

    group_doc = _resolve_group_doc_for_current_user(
        current_user_info["userId"],
        group_id=group_id,
        default_group_id=default_group_id,
        allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
        missing_group_message="group_id is required for group collaborative conversations",
    )
    allowed, reason = check_group_status_allows_operation(group_doc, "chat")
    if not allowed:
        raise PermissionError(reason)

    conversation_doc, _ = create_group_collaboration_conversation_record(
        title=str(title or "").strip(),
        creator_user=current_user,
        group_doc=group_doc,
    )
    _notify_group_conversation_created(
        conversation_doc=conversation_doc,
        group_doc=group_doc,
        creator_user=current_user,
    )
    return conversation_doc, current_user, group_doc


def invite_group_conversation_members_for_current_user(
    conversation_id: str,
    participants: Optional[Iterable[Dict[str, Any]]] = None,
    participant_identifiers: Any = None,
) -> Dict[str, Any]:
    _require_collaboration_feature_enabled()
    current_user_info = _require_current_user_info()
    current_user = normalize_collaboration_user(current_user_info)
    if not current_user:
        raise PermissionError("User not authenticated")

    normalized_conversation_id = str(conversation_id or "").strip()
    if not normalized_conversation_id:
        raise ValueError("conversation_id is required")

    conversation_doc = get_collaboration_conversation(normalized_conversation_id)
    if not is_group_collaboration_conversation(conversation_doc):
        raise ValueError("conversation_id must reference a group multi-user conversation")

    participants_to_add = _build_invited_participants(
        creator_user=current_user,
        participants=participants,
        participant_identifiers=participant_identifiers,
    )
    if not participants_to_add:
        raise ValueError("At least one participant identifier is required")

    updated_conversation_doc, invited_state_docs = invite_personal_collaboration_participants(
        normalized_conversation_id,
        current_user["user_id"],
        participants_to_add,
    )

    conversation_title = str((updated_conversation_doc or {}).get("title") or "Group Conversation").strip() or "Group Conversation"
    scope = (updated_conversation_doc or {}).get("scope") if isinstance((updated_conversation_doc or {}).get("scope"), dict) else {}
    group_id = str(scope.get("group_id") or "").strip()
    group_name = str(scope.get("group_name") or "Group Workspace").strip() or "Group Workspace"
    invited_participants = [
        {
            "user_id": state_doc.get("user_id"),
            "display_name": state_doc.get("user_display_name"),
            "email": state_doc.get("user_email"),
            "membership_status": state_doc.get("membership_status"),
        }
        for state_doc in invited_state_docs
    ]

    if invited_participants:
        message = (
            f"Invited {len(invited_participants)} current group member(s) to "
            f"'{conversation_title}' in '{group_name}'."
        )
    else:
        message = (
            f"No new group members were invited to '{conversation_title}' in '{group_name}'."
        )

    return {
        "conversation": updated_conversation_doc,
        "group": {
            "id": group_id,
            "name": group_name,
        },
        "invited_participants": invited_participants,
        "message": message,
    }


def create_personal_collaboration_conversation_for_current_user(
    title: str = "",
    participants: Optional[Iterable[Dict[str, Any]]] = None,
    participant_identifiers: Any = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    _require_collaboration_feature_enabled()
    current_user_info = _require_current_user_info()
    creator_user = normalize_collaboration_user(current_user_info)
    if not creator_user:
        raise PermissionError("User not authenticated")

    invited_participants = _build_invited_participants(
        creator_user=creator_user,
        participants=participants,
        participant_identifiers=participant_identifiers,
    )
    conversation_doc, user_states = create_personal_collaboration_conversation_record(
        title=str(title or "").strip(),
        creator_user=creator_user,
        invited_participants=invited_participants,
    )
    _notify_personal_collaboration_conversation_created(
        conversation_doc=conversation_doc,
        creator_user=creator_user,
        invited_participants=invited_participants,
    )
    return conversation_doc, user_states, creator_user


def add_group_member_for_current_user(
    group_id: str = "",
    user_id: str = "",
    user_identifier: str = "",
    email: str = "",
    display_name: str = "",
    role: str = "user",
    default_group_id: str = "",
) -> Dict[str, Any]:
    current_user = _require_current_user_info()
    group_doc = _resolve_group_doc_for_current_user(
        current_user["userId"],
        group_id=group_id,
        default_group_id=default_group_id,
        allowed_roles=("Owner", "Admin"),
        missing_group_message="group_id is required when adding a user to a group",
    )
    actor_role = get_user_role_in_group(group_doc, current_user["userId"])
    if actor_role not in ["Owner", "Admin"]:
        raise PermissionError("Only the owner or admin can add members")

    member_role = str(role or "user").strip().lower()
    valid_roles = ["admin", "document_manager", "user"]
    if member_role not in valid_roles:
        raise ValueError(f"Invalid role. Must be: {', '.join(valid_roles)}")

    resolved_user = resolve_directory_user(
        user_id=user_id,
        user_identifier=user_identifier,
        email=email,
        display_name=display_name,
    )
    target_user_id = resolved_user["id"]
    if get_user_role_in_group(group_doc, target_user_id):
        raise ValueError("User is already a member")

    new_member_doc = {
        "userId": target_user_id,
        "email": resolved_user.get("email", ""),
        "displayName": resolved_user.get("displayName") or resolved_user.get("email") or target_user_id,
    }
    group_doc.setdefault("users", []).append(new_member_doc)

    if member_role == "admin":
        if target_user_id not in group_doc.get("admins", []):
            group_doc.setdefault("admins", []).append(target_user_id)
    elif member_role == "document_manager":
        if target_user_id not in group_doc.get("documentManagers", []):
            group_doc.setdefault("documentManagers", []).append(target_user_id)

    group_doc["modifiedDate"] = datetime.utcnow().isoformat()
    updated_group_doc = cosmos_groups_container.upsert_item(group_doc)

    _log_group_member_addition(
        actor_user=current_user,
        actor_role=actor_role,
        group_doc=group_doc,
        member_doc=new_member_doc,
        member_role=member_role,
    )
    _notify_group_member_addition(
        group_doc=group_doc,
        member_doc=new_member_doc,
        member_role=member_role,
        added_by_email=current_user.get("email", "unknown"),
        actor_user=current_user,
    )

    return {
        "success": True,
        "message": "Member added",
        "group_id": group_doc.get("id"),
        "group_name": group_doc.get("name", "Unknown"),
        "member": new_member_doc,
        "member_role": member_role,
        "group": updated_group_doc,
    }


def resolve_directory_user(
    user_id: str = "",
    user_identifier: str = "",
    email: str = "",
    display_name: str = "",
) -> Dict[str, str]:
    normalized_user_id = str(user_id or "").strip()
    normalized_identifier = str(user_identifier or "").strip()
    normalized_email = str(email or "").strip()
    normalized_display_name = str(display_name or "").strip()

    if normalized_user_id and (normalized_email or normalized_display_name):
        return {
            "id": normalized_user_id,
            "displayName": normalized_display_name or normalized_email or normalized_user_id,
            "email": normalized_email,
        }

    if normalized_user_id:
        try:
            direct_match = _get_directory_user_by_id(normalized_user_id)
        except PermissionError:
            direct_match = None
        if direct_match:
            return direct_match
        if not (normalized_identifier or normalized_email or normalized_display_name):
            return {
                "id": normalized_user_id,
                "displayName": normalized_user_id,
                "email": "",
            }

    if normalized_email or "@" in normalized_identifier:
        lookup_value = normalized_email or normalized_identifier
        exact_matches = _find_directory_users_by_email(lookup_value)
        if len(exact_matches) == 1:
            return exact_matches[0]
        if len(exact_matches) > 1:
            raise ValueError(f"Multiple directory users matched '{lookup_value}'")

    lookup_query = normalized_identifier or normalized_display_name or normalized_email or normalized_user_id
    if not lookup_query:
        raise ValueError("Missing userId or user identifier")

    search_results = search_directory_users(lookup_query, limit=10)
    if not search_results:
        raise LookupError(f"User '{lookup_query}' was not found in the directory")

    exact_matches = []
    lowered_lookup = lookup_query.lower()
    for candidate in search_results:
        candidate_email = str(candidate.get("email") or "").strip().lower()
        candidate_name = str(candidate.get("displayName") or "").strip().lower()
        candidate_id = str(candidate.get("id") or "").strip().lower()
        if lowered_lookup in {candidate_email, candidate_name, candidate_id}:
            exact_matches.append(candidate)

    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise ValueError(f"Multiple directory users matched '{lookup_query}'")
    if len(search_results) == 1:
        return search_results[0]

    raise ValueError(
        f"Multiple directory users matched '{lookup_query}'. Provide a more specific email or user ID."
    )


def search_directory_users(query: str, limit: int = 10) -> List[Dict[str, str]]:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return []

    escaped_query = _escape_odata_value(normalized_query)
    payload = _graph_get_json(
        "/users",
        params={
            "$filter": (
                f"startswith(displayName, '{escaped_query}') "
                f"or startswith(mail, '{escaped_query}') "
                f"or startswith(userPrincipalName, '{escaped_query}')"
            ),
            "$top": max(1, min(int(limit or 10), 25)),
            "$select": "id,displayName,mail,userPrincipalName",
        },
    )
    return _normalize_directory_users(payload.get("value", []))


def _build_invited_participants(
    creator_user: Dict[str, str],
    participants: Optional[Iterable[Dict[str, Any]]] = None,
    participant_identifiers: Any = None,
) -> List[Dict[str, str]]:
    invited_participants: List[Dict[str, str]] = []
    seen_user_ids = {creator_user.get("user_id")}

    for raw_participant in participants or []:
        normalized_participant = normalize_collaboration_user(raw_participant)
        if not normalized_participant:
            continue
        participant_user_id = normalized_participant.get("user_id")
        if participant_user_id in seen_user_ids:
            continue
        seen_user_ids.add(participant_user_id)
        invited_participants.append(normalized_participant)

    for raw_identifier in _split_participant_identifiers(participant_identifiers):
        resolved_user = resolve_directory_user(user_identifier=raw_identifier)
        normalized_participant = normalize_collaboration_user(resolved_user)
        if not normalized_participant:
            continue
        participant_user_id = normalized_participant.get("user_id")
        if participant_user_id in seen_user_ids:
            continue
        seen_user_ids.add(participant_user_id)
        invited_participants.append(normalized_participant)

    return invited_participants


def _split_participant_identifiers(raw_identifiers: Any) -> List[str]:
    if raw_identifiers is None:
        return []
    if isinstance(raw_identifiers, str):
        values = re.split(r"[,;\n]+", raw_identifiers)
    elif isinstance(raw_identifiers, (list, tuple, set)):
        values = []
        for item in raw_identifiers:
            if isinstance(item, str):
                values.extend(re.split(r"[,;\n]+", item))
    else:
        values = [str(raw_identifiers)]

    return [str(value or "").strip() for value in values if str(value or "").strip()]


def _persist_personal_conversation_message(
    conversation_item: Dict[str, Any],
    current_user_info: Dict[str, str],
    content: str,
    reply_to_message_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    conversation_id = str(conversation_item.get("id") or "").strip()
    if not conversation_id:
        raise ValueError("Conversation is missing an id")

    timestamp = datetime.now(timezone.utc).isoformat()
    current_thread_id = str(uuid.uuid4())
    previous_thread_id = _get_latest_personal_thread_id(conversation_id)
    normalized_chat_type = str(conversation_item.get("chat_type") or "personal_single_user").strip() or "personal_single_user"

    message_doc = {
        "id": f"{conversation_id}_user_{uuid.uuid4().hex}",
        "conversation_id": conversation_id,
        "role": "user",
        "content": str(content or "").strip(),
        "reply_to_message_id": reply_to_message_id,
        "timestamp": timestamp,
        "model_deployment_name": None,
        "metadata": {
            "user_info": {
                "user_id": current_user_info.get("userId"),
                "username": current_user_info.get("userPrincipalName"),
                "display_name": current_user_info.get("displayName"),
                "email": current_user_info.get("email"),
                "timestamp": timestamp,
            },
            "button_states": {
                "image_generation": False,
                "document_search": False,
                "web_search": False,
            },
            "workspace_search": {
                "search_enabled": False,
            },
            "chat_context": {
                "conversation_id": conversation_id,
                "chat_type": normalized_chat_type,
            },
            "thread_info": {
                "thread_id": current_thread_id,
                "previous_thread_id": previous_thread_id,
                "active_thread": True,
                "thread_attempt": 1,
            },
        },
    }

    cosmos_messages_container.upsert_item(message_doc)

    conversation_item["chat_type"] = normalized_chat_type
    if str(conversation_item.get("title") or "").strip() in {"", "New Conversation"}:
        conversation_item["title"] = _derive_personal_conversation_title(message_doc["content"])
    conversation_item["last_updated"] = timestamp
    cosmos_conversations_container.upsert_item(conversation_item)

    log_chat_activity(
        user_id=current_user_info["userId"],
        conversation_id=conversation_id,
        message_type="user_message",
        message_length=len(message_doc["content"]),
        has_document_search=False,
        has_image_generation=False,
        chat_context=normalized_chat_type,
    )

    return message_doc, conversation_item


def _get_latest_personal_thread_id(conversation_id: str) -> Optional[str]:
    query = (
        "SELECT TOP 1 c.metadata.thread_info.thread_id AS thread_id "
        "FROM c WHERE c.conversation_id = @conversation_id ORDER BY c.timestamp DESC"
    )
    items = list(cosmos_messages_container.query_items(
        query=query,
        parameters=[{"name": "@conversation_id", "value": conversation_id}],
        partition_key=conversation_id,
    ))
    if not items:
        return None
    return str(items[0].get("thread_id") or "").strip() or None


def _normalize_document_workspace_scope(workspace_scope: str = "personal") -> str:
    normalized_workspace_scope = str(workspace_scope or "personal").strip().lower()
    if normalized_workspace_scope not in {"personal", "group"}:
        raise ValueError("workspace_scope must be 'personal' or 'group'")
    return normalized_workspace_scope


def _normalize_markdown_file_name(file_name: str) -> str:
    normalized_file_name = str(file_name or "").replace("\\", "/").split("/")[-1].strip()
    if not normalized_file_name:
        normalized_file_name = "generated_markdown_document"

    base_name, extension = os.path.splitext(normalized_file_name)
    if extension.lower() == ".md" and base_name.strip():
        return normalized_file_name

    normalized_base_name = base_name.strip() or normalized_file_name.strip() or "generated_markdown_document"
    return f"{normalized_base_name}.md"


def _write_temp_markdown_file(markdown_content: str) -> str:
    sc_temp_files_dir = "/sc-temp-files" if os.path.exists("/sc-temp-files") else None
    with tempfile.NamedTemporaryFile(delete=False, suffix=".md", dir=sc_temp_files_dir) as temp_file:
        temp_file.write(str(markdown_content or "").encode("utf-8"))
        return temp_file.name


def _queue_document_upload_background_task(
    document_id: str,
    user_id: str,
    temp_file_path: str,
    original_filename: str,
    group_id: Optional[str] = None,
) -> None:
    task_kwargs = {
        "document_id": document_id,
        "user_id": user_id,
        "temp_file_path": temp_file_path,
        "original_filename": original_filename,
    }
    if group_id:
        task_kwargs["group_id"] = group_id

    if not has_app_context():
        raise RuntimeError("SimpleChat document uploads require an active app context")

    executor = current_app.extensions.get("executor")
    if executor and hasattr(executor, "submit_stored"):
        executor.submit_stored(
            document_id,
            process_document_upload_background,
            **task_kwargs,
        )
        return

    if executor and hasattr(executor, "submit"):
        executor.submit(process_document_upload_background, **task_kwargs)
        return

    process_document_upload_background(**task_kwargs)


def _resolve_group_upload_target_for_current_user(
    current_user_id: str,
    group_id: str = "",
    default_group_id: str = "",
) -> str:
    normalized_group_id = str(group_id or default_group_id or "").strip()
    if not normalized_group_id:
        normalized_group_id = require_active_group(current_user_id)

    group_doc = find_group_by_id(normalized_group_id)
    if not group_doc:
        raise LookupError("Group not found")

    allowed, reason = check_group_status_allows_operation(group_doc, "upload")
    if not allowed:
        raise PermissionError(reason)

    assert_group_role(
        current_user_id,
        normalized_group_id,
        allowed_roles=("Owner", "Admin", "DocumentManager"),
    )
    return normalized_group_id


def _derive_personal_conversation_title(content: str) -> str:
    normalized_content = str(content or "").strip()
    if not normalized_content:
        return "New Conversation"
    return f"{normalized_content[:30]}..." if len(normalized_content) > 30 else normalized_content


def _resolve_group_doc_for_current_user(
    current_user_id: str,
    group_id: str = "",
    default_group_id: str = "",
    allowed_roles: Tuple[str, ...] = ("Owner", "Admin", "DocumentManager", "User"),
    missing_group_message: str = "group_id is required",
) -> Dict[str, Any]:
    _require_group_workspaces_enabled()
    resolved_group_id = str(group_id or default_group_id or "").strip()
    if not resolved_group_id:
        user_settings = get_user_settings(current_user_id) or {}
        resolved_group_id = str(((user_settings.get("settings") or {}).get("activeGroupOid") or "")).strip()

    if not resolved_group_id:
        raise ValueError(missing_group_message)

    group_doc = find_group_by_id(resolved_group_id)
    if not group_doc:
        raise LookupError("Group not found")

    assert_group_role(current_user_id, resolved_group_id, allowed_roles=allowed_roles)
    return group_doc


def _require_current_user_info() -> Dict[str, str]:
    current_user = get_current_user_info()
    if not current_user or not current_user.get("userId"):
        raise PermissionError("User not authenticated")
    return current_user


def _require_group_workspaces_enabled() -> Dict[str, Any]:
    settings = get_settings() or {}
    if not settings.get("enable_group_workspaces", False):
        raise PermissionError("Group workspaces are disabled by configuration")
    return settings


def _require_group_creation_enabled(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    settings = settings or get_settings() or {}
    if not settings.get("enable_group_creation", False):
        raise PermissionError("Group creation is disabled by configuration")

    if settings.get("require_member_of_create_group", False):
        user_roles = (session.get("user") or {}).get("roles") or []
        if "CreateGroups" not in user_roles:
            raise PermissionError("Insufficient permissions (CreateGroups role required)")
    return settings


def _require_user_workflows_enabled() -> Dict[str, Any]:
    settings = get_settings() or {}
    if not settings.get("allow_user_workflows", True):
        raise PermissionError("Personal workflows are disabled by configuration")
    return settings


def _require_control_center_admin_access(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    settings = settings or get_settings() or {}
    session_user = (session.get("user") or {})
    user_roles = session_user.get("roles") or []
    require_member_of_control_center_admin = settings.get("require_member_of_control_center_admin", False)

    has_control_center_admin_role = "ControlCenterAdmin" in user_roles
    has_regular_admin_role = "Admin" in user_roles

    if require_member_of_control_center_admin:
        if not has_control_center_admin_role:
            raise PermissionError("Insufficient permissions (ControlCenterAdmin role required)")
        return session_user

    if not has_regular_admin_role:
        raise PermissionError("Insufficient permissions (Admin role required)")
    return session_user


def _require_collaboration_feature_enabled() -> Dict[str, Any]:
    settings = get_settings() or {}
    if not settings.get("enable_collaborative_conversations", False):
        raise PermissionError("Collaborative conversations are disabled by configuration")
    return settings


def _graph_get_json(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    token = get_valid_access_token()
    if not token:
        raise PermissionError("Could not acquire access token")

    response = requests.get(
        get_graph_endpoint(path),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        params=params,
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def _get_directory_user_by_id(user_id: str) -> Optional[Dict[str, str]]:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return None

    token = get_valid_access_token()
    if not token:
        raise PermissionError("Could not acquire access token")

    response = requests.get(
        get_graph_endpoint(f"/users/{quote(normalized_user_id)}"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        params={"$select": "id,displayName,mail,userPrincipalName"},
        timeout=20,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return _normalize_directory_user(response.json())


def _find_directory_users_by_email(email: str) -> List[Dict[str, str]]:
    normalized_email = str(email or "").strip()
    if not normalized_email:
        return []

    escaped_email = _escape_odata_value(normalized_email)
    payload = _graph_get_json(
        "/users",
        params={
            "$filter": f"mail eq '{escaped_email}' or userPrincipalName eq '{escaped_email}'",
            "$top": 5,
            "$select": "id,displayName,mail,userPrincipalName",
        },
    )
    return _normalize_directory_users(payload.get("value", []))


def _normalize_directory_users(raw_users: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    normalized_users = []
    for raw_user in raw_users or []:
        normalized_user = _normalize_directory_user(raw_user)
        if normalized_user:
            normalized_users.append(normalized_user)
    return normalized_users


def _normalize_directory_user(raw_user: Dict[str, Any]) -> Optional[Dict[str, str]]:
    if not isinstance(raw_user, dict):
        return None

    user_id = str(raw_user.get("id") or "").strip()
    if not user_id:
        return None

    email = str(raw_user.get("mail") or raw_user.get("userPrincipalName") or "").strip()
    display_name = str(raw_user.get("displayName") or email or user_id).strip()
    return {
        "id": user_id,
        "displayName": display_name,
        "email": email,
    }


def _escape_odata_value(value: str) -> str:
    return str(value or "").replace("'", "''").strip()


def _log_group_member_addition(
    actor_user: Dict[str, str],
    actor_role: str,
    group_doc: Dict[str, Any],
    member_doc: Dict[str, str],
    member_role: str,
) -> None:
    try:
        activity_record = {
            "id": str(uuid.uuid4()),
            "activity_type": "add_member_directly",
            "timestamp": datetime.utcnow().isoformat(),
            "added_by_user_id": actor_user.get("userId"),
            "added_by_email": actor_user.get("email", "unknown"),
            "added_by_role": actor_role,
            "group_id": group_doc.get("id"),
            "group_name": group_doc.get("name", "Unknown"),
            "member_user_id": member_doc.get("userId", ""),
            "member_email": member_doc.get("email", ""),
            "member_name": member_doc.get("displayName", ""),
            "member_role": member_role,
            "description": (
                f"{actor_role} {actor_user.get('email', 'unknown')} added member "
                f"{member_doc.get('displayName', '')} ({member_doc.get('email', '')}) to group "
                f"{group_doc.get('name', group_doc.get('id', 'Unknown'))} as {member_role}"
            ),
        }
        cosmos_activity_logs_container.create_item(body=activity_record)
    except Exception as exc:
        log_event(
            f"[SimpleChat] Failed to log group member addition: {exc}",
            level=logging.WARNING,
            exceptionTraceback=True,
        )


def _notify_group_member_addition(
    group_doc: Dict[str, Any],
    member_doc: Dict[str, str],
    member_role: str,
    added_by_email: str,
    actor_user: Optional[Dict[str, str]] = None,
) -> None:
    role_display = {
        "admin": "Admin",
        "document_manager": "Document Manager",
        "user": "Member",
    }.get(member_role, "Member")

    try:
        create_notification(
            user_id=member_doc.get("userId", ""),
            notification_type="group_member_added",
            title="Added to Group",
            message=(
                f"You have been added to the group '{group_doc.get('name', 'Unknown')}' "
                f"as {role_display} by {added_by_email}."
            ),
            link_url=f"/manage_group/{group_doc.get('id', '')}",
            link_context={
                "workspace_type": "group",
                "group_id": group_doc.get("id", ""),
            },
            metadata={
                "group_id": group_doc.get("id", ""),
                "group_name": group_doc.get("name", "Unknown"),
                "added_by": added_by_email,
                "role": member_role,
                "audience": "member",
            },
        )
    except Exception as exc:
        log_event(
            f"[SimpleChat] Failed to notify group member addition: {exc}",
            level=logging.WARNING,
            exceptionTraceback=True,
        )

    actor_user_id = str((actor_user or {}).get("userId") or "").strip()
    if not actor_user_id or actor_user_id == str(member_doc.get("userId") or "").strip():
        return

    try:
        create_notification(
            user_id=actor_user_id,
            notification_type="group_member_added",
            title="Group member added",
            message=(
                f"Added {member_doc.get('displayName', 'a new member')} to '{group_doc.get('name', 'Unknown')}' "
                f"as {role_display}."
            ),
            link_url=f"/manage_group/{group_doc.get('id', '')}",
            link_context={
                "workspace_type": "group",
                "group_id": group_doc.get("id", ""),
            },
            metadata={
                "group_id": group_doc.get("id", ""),
                "group_name": group_doc.get("name", "Unknown"),
                "member_user_id": member_doc.get("userId", ""),
                "member_email": member_doc.get("email", ""),
                "member_display_name": member_doc.get("displayName", ""),
                "role": member_role,
                "audience": "actor",
            },
        )
    except Exception as exc:
        log_event(
            f"[SimpleChat] Failed to notify actor about group member addition: {exc}",
            level=logging.WARNING,
            exceptionTraceback=True,
        )


def _create_personal_notification(
    user_id: str,
    notification_type: str,
    title: str,
    message: str,
    link_url: str = "",
    link_context: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return None

    try:
        return create_notification(
            user_id=normalized_user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            link_url=link_url,
            link_context=link_context or {},
            metadata=metadata or {},
        )
    except Exception as exc:
        log_event(
            f"[SimpleChat] Failed to create notification '{notification_type}': {exc}",
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return None


def _build_group_link_context(group_doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "workspace_type": "group",
        "group_id": str((group_doc or {}).get("id") or "").strip(),
    }


def _build_conversation_link_context(conversation_doc: Dict[str, Any]) -> Dict[str, Any]:
    conversation_doc = conversation_doc if isinstance(conversation_doc, dict) else {}
    scope = conversation_doc.get("scope") if isinstance(conversation_doc.get("scope"), dict) else {}
    group_id = str(scope.get("group_id") or conversation_doc.get("group_id") or "").strip()
    chat_type = str(conversation_doc.get("chat_type") or "").strip().lower()

    link_context = {
        "conversation_id": str(conversation_doc.get("id") or "").strip(),
        "workspace_type": "group" if group_id or chat_type.startswith("group") else "personal",
    }
    if group_id:
        link_context["group_id"] = group_id
    if conversation_doc.get("conversation_kind"):
        link_context["conversation_kind"] = conversation_doc.get("conversation_kind")
    return link_context


def _build_conversation_link_url(conversation_doc: Dict[str, Any]) -> str:
    conversation_id = str((conversation_doc or {}).get("id") or "").strip()
    if not conversation_id:
        return ""
    return f"/chats?conversationId={conversation_id}"


def _get_group_notification_recipient_ids(group_doc: Dict[str, Any]) -> List[str]:
    recipient_ids = set()
    owner_user_id = str(((group_doc or {}).get("owner") or {}).get("id") or "").strip()
    if owner_user_id:
        recipient_ids.add(owner_user_id)

    for member in list((group_doc or {}).get("users", []) or []):
        member_user_id = str(member.get("userId") or "").strip()
        if member_user_id:
            recipient_ids.add(member_user_id)

    return sorted(recipient_ids)


def _notify_group_created(group_doc: Dict[str, Any], actor_user: Dict[str, str]) -> None:
    group_id = str((group_doc or {}).get("id") or "").strip()
    group_name = str((group_doc or {}).get("name") or "Untitled Group").strip() or "Untitled Group"
    actor_user_id = str((actor_user or {}).get("userId") or "").strip()
    if not group_id or not actor_user_id:
        return

    _create_personal_notification(
        user_id=actor_user_id,
        notification_type="group_created",
        title=f"Group created: {group_name}",
        message=f"You created the group '{group_name}'.",
        link_url=f"/manage_group/{group_id}",
        link_context=_build_group_link_context(group_doc),
        metadata={
            "group_id": group_id,
            "group_name": group_name,
        },
    )


def _notify_personal_conversation_created(
    conversation_item: Dict[str, Any],
    current_user: Dict[str, str],
) -> None:
    conversation_title = str((conversation_item or {}).get("title") or "New Conversation").strip() or "New Conversation"
    _create_personal_notification(
        user_id=str((current_user or {}).get("userId") or "").strip(),
        notification_type="conversation_created",
        title=f"Conversation created: {conversation_title}",
        message=f"Created a new personal conversation named '{conversation_title}'.",
        link_url=_build_conversation_link_url(conversation_item),
        link_context=_build_conversation_link_context(conversation_item),
        metadata={
            "conversation_id": str((conversation_item or {}).get("id") or "").strip(),
            "conversation_title": conversation_title,
            "chat_type": str((conversation_item or {}).get("chat_type") or "").strip(),
            "audience": "actor",
        },
    )


def _notify_group_conversation_created(
    conversation_doc: Dict[str, Any],
    group_doc: Dict[str, Any],
    creator_user: Dict[str, str],
) -> None:
    conversation_title = str((conversation_doc or {}).get("title") or "New group conversation").strip() or "New group conversation"
    group_name = str((group_doc or {}).get("name") or "Group Workspace").strip() or "Group Workspace"
    creator_display_name = str((creator_user or {}).get("display_name") or (creator_user or {}).get("displayName") or "A teammate").strip() or "A teammate"
    link_url = _build_conversation_link_url(conversation_doc)
    link_context = _build_conversation_link_context(conversation_doc)
    metadata = {
        "group_id": str((group_doc or {}).get("id") or "").strip(),
        "group_name": group_name,
        "conversation_id": str((conversation_doc or {}).get("id") or "").strip(),
        "conversation_title": conversation_title,
        "chat_type": str((conversation_doc or {}).get("chat_type") or "").strip(),
    }

    for recipient_user_id in _get_group_notification_recipient_ids(group_doc):
        audience = "actor" if recipient_user_id == str((creator_user or {}).get("user_id") or "").strip() else "member"
        if audience == "actor":
            title = f"Group conversation created: {conversation_title}"
            message = f"You created '{conversation_title}' in '{group_name}'."
        else:
            title = f"New group conversation in {group_name}"
            message = f"{creator_display_name} created '{conversation_title}' in '{group_name}'."

        _create_personal_notification(
            user_id=recipient_user_id,
            notification_type="conversation_created",
            title=title,
            message=message,
            link_url=link_url,
            link_context=link_context,
            metadata={
                **metadata,
                "audience": audience,
            },
        )


def _notify_personal_collaboration_conversation_created(
    conversation_doc: Dict[str, Any],
    creator_user: Dict[str, str],
    invited_participants: Optional[Iterable[Dict[str, Any]]] = None,
) -> None:
    conversation_title = str((conversation_doc or {}).get("title") or "Collaborative conversation").strip() or "Collaborative conversation"
    creator_user_id = str((creator_user or {}).get("user_id") or "").strip()
    creator_display_name = str((creator_user or {}).get("display_name") or "You").strip() or "You"
    link_url = _build_conversation_link_url(conversation_doc)
    link_context = _build_conversation_link_context(conversation_doc)
    base_metadata = {
        "conversation_id": str((conversation_doc or {}).get("id") or "").strip(),
        "conversation_title": conversation_title,
        "chat_type": str((conversation_doc or {}).get("chat_type") or "").strip(),
        "participant_count": len(list(invited_participants or [])) + 1,
    }

    _create_personal_notification(
        user_id=creator_user_id,
        notification_type="conversation_created",
        title=f"Collaborative conversation created: {conversation_title}",
        message=(
            f"Created '{conversation_title}'"
            f" with {len(list(invited_participants or []))} invited participant(s)."
        ),
        link_url=link_url,
        link_context=link_context,
        metadata={
            **base_metadata,
            "audience": "actor",
        },
    )

    for participant in invited_participants or []:
        participant_user_id = str((participant or {}).get("user_id") or "").strip()
        if not participant_user_id or participant_user_id == creator_user_id:
            continue

        _create_personal_notification(
            user_id=participant_user_id,
            notification_type="conversation_created",
            title=f"Added to collaborative conversation: {conversation_title}",
            message=f"{creator_display_name} added you to '{conversation_title}'.",
            link_url=link_url,
            link_context=link_context,
            metadata={
                **base_metadata,
                "created_by_user_id": creator_user_id,
                "created_by_display_name": creator_display_name,
                "audience": "participant",
            },
        )