# functions_msgraph_operations.py
"""Shared Microsoft Graph action capability metadata and helpers."""

from typing import Any, Dict, List, Optional


MSGRAPH_PLUGIN_TYPE = "msgraph"
MSGRAPH_DEFAULT_ENDPOINT = "https://graph.microsoft.com"
MSGRAPH_CAPABILITY_DEFINITIONS = [
    {
        "key": "get_my_profile",
        "function_name": "get_my_profile",
        "label": "Read my profile",
        "description": "Read the signed-in user's Microsoft 365 profile details.",
    },
    {
        "key": "get_my_timezone",
        "function_name": "get_my_timezone",
        "label": "Read my mailbox timezone",
        "description": "Read the signed-in user's mailbox time zone and time formatting settings.",
    },
    {
        "key": "get_my_events",
        "function_name": "get_my_events",
        "label": "Read my calendar events",
        "description": "Read upcoming calendar events for the signed-in user.",
    },
    {
        "key": "create_calendar_invite",
        "function_name": "create_calendar_invite",
        "label": "Create calendar invites",
        "description": "Create calendar invites, optionally add current group members, and turn meetings into Microsoft Teams meetings.",
    },
    {
        "key": "get_my_messages",
        "function_name": "get_my_messages",
        "label": "Read my mail",
        "description": "Read recent mail messages for the signed-in user.",
    },
    {
        "key": "mark_message_as_read",
        "function_name": "mark_message_as_read",
        "label": "Update message read state",
        "description": "Mark a message as read or unread for the signed-in user.",
    },
    {
        "key": "search_users",
        "function_name": "search_users",
        "label": "Search directory users",
        "description": "Search Microsoft 365 directory users by name or email prefix.",
    },
    {
        "key": "get_user_by_email",
        "function_name": "get_user_by_email",
        "label": "Lookup user by email",
        "description": "Get a directory user by exact email address or UPN.",
    },
    {
        "key": "list_drive_items",
        "function_name": "list_drive_items",
        "label": "List OneDrive items",
        "description": "List OneDrive items from the signed-in user's drive.",
    },
    {
        "key": "get_my_security_alerts",
        "function_name": "get_my_security_alerts",
        "label": "Read my security alerts",
        "description": "Read recent security alerts available to the signed-in user.",
    },
]


def get_default_msgraph_capabilities() -> Dict[str, bool]:
    return {definition["key"]: True for definition in MSGRAPH_CAPABILITY_DEFINITIONS}


def normalize_msgraph_capabilities(raw_capabilities: Any = None) -> Dict[str, bool]:
    normalized = get_default_msgraph_capabilities()

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
            for definition in MSGRAPH_CAPABILITY_DEFINITIONS
        }

    return normalized


def get_msgraph_enabled_function_names(raw_capabilities: Any = None) -> List[str]:
    normalized = normalize_msgraph_capabilities(raw_capabilities)
    return [
        definition["function_name"]
        for definition in MSGRAPH_CAPABILITY_DEFINITIONS
        if normalized.get(definition["key"], False)
    ]


def resolve_msgraph_action_capabilities(
    action_capability_map: Any,
    action_defaults: Any = None,
    action_id: Optional[str] = None,
    action_name: Optional[str] = None,
) -> Dict[str, bool]:
    resolved_defaults = normalize_msgraph_capabilities(action_defaults)

    if not isinstance(action_capability_map, dict):
        return resolved_defaults

    for candidate_key in (str(action_id or "").strip(), str(action_name or "").strip()):
        if candidate_key and candidate_key in action_capability_map:
            return normalize_msgraph_capabilities(action_capability_map.get(candidate_key))

    return resolved_defaults