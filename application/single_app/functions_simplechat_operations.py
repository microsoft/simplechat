# functions_simplechat_operations.py
"""Shared SimpleChat-native operations for routes and Semantic Kernel plugins."""

import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

import requests
from flask import session

from collaboration_models import normalize_collaboration_user
from config import (
    cosmos_activity_logs_container,
    cosmos_conversations_container,
    cosmos_groups_container,
)
from functions_activity_logging import log_conversation_creation
from functions_appinsights import log_event
from functions_authentication import (
    get_current_user_info,
    get_graph_endpoint,
    get_valid_access_token,
)
from functions_collaboration import (
    create_group_collaboration_conversation_record,
    create_personal_collaboration_conversation_record,
)
from functions_group import (
    assert_group_role,
    check_group_status_allows_operation,
    create_group,
    find_group_by_id,
    get_user_role_in_group,
)
from functions_notifications import create_notification
from functions_settings import get_settings, get_user_settings


SIMPLECHAT_PLUGIN_TYPE = "simplechat"
SIMPLECHAT_DEFAULT_ENDPOINT = "simplechat://internal"
SIMPLECHAT_CAPABILITY_TO_FUNCTION = {
    "create_group": "create_group",
    "add_group_member": "add_user_to_group",
    "create_group_conversation": "create_group_conversation",
    "create_personal_conversation": "create_personal_conversation",
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
        "key": "create_group_conversation",
        "function_name": SIMPLECHAT_CAPABILITY_TO_FUNCTION["create_group_conversation"],
        "label": "Create Group Conversations",
        "description": "Create a collaborative conversation in a group the current user can access.",
    },
    {
        "key": "create_personal_conversation",
        "function_name": SIMPLECHAT_CAPABILITY_TO_FUNCTION["create_personal_conversation"],
        "label": "Create Personal Conversations",
        "description": "Create a standard one-user personal conversation.",
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
    action_id: Optional[str] = None,
    action_name: Optional[str] = None,
) -> Dict[str, bool]:
    if not isinstance(action_capability_map, dict):
        return get_default_simplechat_capabilities()

    for candidate_key in (str(action_id or "").strip(), str(action_name or "").strip()):
        if candidate_key and candidate_key in action_capability_map:
            return normalize_simplechat_capabilities(action_capability_map.get(candidate_key))

    return get_default_simplechat_capabilities()


def create_personal_conversation_for_current_user(title: str = "New Conversation") -> Dict[str, Any]:
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
    return conversation_item


def create_group_for_current_user(name: str, description: str = "") -> Dict[str, Any]:
    settings = _require_group_workspaces_enabled()
    _require_group_creation_enabled(settings)
    normalized_name = str(name or "").strip() or "Untitled Group"
    normalized_description = str(description or "").strip()
    return create_group(normalized_name, normalized_description)


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

    conversation_doc = create_group_collaboration_conversation_record(
        title=str(title or "").strip(),
        creator_user=current_user,
        group_doc=group_doc,
    )
    return conversation_doc, current_user, group_doc


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
) -> None:
    role_display = {
        "admin": "Admin",
        "document_manager": "Document Manager",
        "user": "Member",
    }.get(member_role, "Member")

    try:
        create_notification(
            user_id=member_doc.get("userId", ""),
            notification_type="system_announcement",
            title="Added to Group",
            message=(
                f"You have been added to the group '{group_doc.get('name', 'Unknown')}' "
                f"as {role_display} by {added_by_email}."
            ),
            link_url=f"/manage_group/{group_doc.get('id', '')}",
            metadata={
                "group_id": group_doc.get("id", ""),
                "group_name": group_doc.get("name", "Unknown"),
                "added_by": added_by_email,
                "role": member_role,
            },
        )
    except Exception as exc:
        log_event(
            f"[SimpleChat] Failed to notify group member addition: {exc}",
            level=logging.WARNING,
            exceptionTraceback=True,
        )