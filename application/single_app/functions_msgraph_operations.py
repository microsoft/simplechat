# functions_msgraph_operations.py
"""Shared Microsoft Graph action capability metadata and helpers."""

from typing import Any, Dict, List, Optional


MSGRAPH_PLUGIN_TYPE = "msgraph"
MSGRAPH_DEFAULT_ENDPOINT = "https://graph.microsoft.com"
MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL = "draft_manual"
MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED = "draft_delayed"
MSGRAPH_MAIL_SEND_MODE_AUTO_SEND = "auto_send"
MSGRAPH_DEFAULT_MAIL_SEND_MODE = MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL
MSGRAPH_MIN_MAIL_DELAY_SECONDS = 5
MSGRAPH_MAX_MAIL_DELAY_SECONDS = 600
MSGRAPH_DEFAULT_MAIL_DELAY_SECONDS = 60
MSGRAPH_MAIL_SEND_MODES = {
    MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL,
    MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED,
    MSGRAPH_MAIL_SEND_MODE_AUTO_SEND,
}
MSGRAPH_CALENDAR_SEND_MODE_DRAFT_MANUAL = MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL
MSGRAPH_CALENDAR_SEND_MODE_DRAFT_DELAYED = MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED
MSGRAPH_CALENDAR_SEND_MODE_AUTO_SEND = MSGRAPH_MAIL_SEND_MODE_AUTO_SEND
MSGRAPH_DEFAULT_CALENDAR_SEND_MODE = MSGRAPH_CALENDAR_SEND_MODE_AUTO_SEND
MSGRAPH_MIN_CALENDAR_DELAY_SECONDS = 5
MSGRAPH_MAX_CALENDAR_DELAY_SECONDS = 600
MSGRAPH_DEFAULT_CALENDAR_DELAY_SECONDS = 60
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
        "key": "send_mail",
        "function_name": "send_mail",
        "label": "Send mail",
        "description": "Create manual drafts, delayed-delivery drafts, or send messages from the signed-in user's mailbox.",
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


def normalize_msgraph_mail_send_mode(raw_mode: Any = None) -> str:
    normalized_mode = str(raw_mode or "").strip().lower().replace("-", "_").replace(" ", "_")
    mode_aliases = {
        "": MSGRAPH_DEFAULT_MAIL_SEND_MODE,
        "draft": MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL,
        "manual": MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL,
        "draft_manual": MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL,
        "draft_with_manual": MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL,
        "manual_draft": MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL,
        "delayed": MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED,
        "delay": MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED,
        "draft_delayed": MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED,
        "delayed_delivery": MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED,
        "draft_with_delayed_delivery": MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED,
        "auto": MSGRAPH_MAIL_SEND_MODE_AUTO_SEND,
        "autosend": MSGRAPH_MAIL_SEND_MODE_AUTO_SEND,
        "auto_send": MSGRAPH_MAIL_SEND_MODE_AUTO_SEND,
        "send": MSGRAPH_MAIL_SEND_MODE_AUTO_SEND,
        "send_now": MSGRAPH_MAIL_SEND_MODE_AUTO_SEND,
    }
    return mode_aliases.get(normalized_mode, MSGRAPH_DEFAULT_MAIL_SEND_MODE)


def normalize_msgraph_mail_delay_seconds(raw_delay_seconds: Any = None) -> int:
    try:
        delay_seconds = int(raw_delay_seconds)
    except (TypeError, ValueError):
        delay_seconds = MSGRAPH_DEFAULT_MAIL_DELAY_SECONDS

    return max(
        MSGRAPH_MIN_MAIL_DELAY_SECONDS,
        min(delay_seconds, MSGRAPH_MAX_MAIL_DELAY_SECONDS),
    )


def normalize_msgraph_mail_send_options(raw_options: Any = None) -> Dict[str, Any]:
    options = raw_options if isinstance(raw_options, dict) else {}
    send_mode = normalize_msgraph_mail_send_mode(
        options.get("msgraph_mail_send_mode") or options.get("mail_send_mode")
    )
    delay_seconds = normalize_msgraph_mail_delay_seconds(
        options.get("msgraph_mail_delay_seconds") or options.get("mail_delay_seconds")
    )
    return {
        "msgraph_mail_send_mode": send_mode,
        "msgraph_mail_delay_seconds": delay_seconds,
    }


def normalize_msgraph_calendar_send_mode(raw_mode: Any = None) -> str:
    normalized_mode = str(raw_mode or "").strip().lower().replace("-", "_").replace(" ", "_")
    mode_aliases = {
        "": MSGRAPH_DEFAULT_CALENDAR_SEND_MODE,
        "draft": MSGRAPH_CALENDAR_SEND_MODE_DRAFT_MANUAL,
        "manual": MSGRAPH_CALENDAR_SEND_MODE_DRAFT_MANUAL,
        "draft_manual": MSGRAPH_CALENDAR_SEND_MODE_DRAFT_MANUAL,
        "manual_review": MSGRAPH_CALENDAR_SEND_MODE_DRAFT_MANUAL,
        "delayed": MSGRAPH_CALENDAR_SEND_MODE_DRAFT_DELAYED,
        "delay": MSGRAPH_CALENDAR_SEND_MODE_DRAFT_DELAYED,
        "draft_delayed": MSGRAPH_CALENDAR_SEND_MODE_DRAFT_DELAYED,
        "delayed_delivery": MSGRAPH_CALENDAR_SEND_MODE_DRAFT_DELAYED,
        "auto": MSGRAPH_CALENDAR_SEND_MODE_AUTO_SEND,
        "autosend": MSGRAPH_CALENDAR_SEND_MODE_AUTO_SEND,
        "auto_send": MSGRAPH_CALENDAR_SEND_MODE_AUTO_SEND,
        "send": MSGRAPH_CALENDAR_SEND_MODE_AUTO_SEND,
        "send_now": MSGRAPH_CALENDAR_SEND_MODE_AUTO_SEND,
    }
    return mode_aliases.get(normalized_mode, MSGRAPH_DEFAULT_CALENDAR_SEND_MODE)


def normalize_msgraph_calendar_delay_seconds(raw_delay_seconds: Any = None) -> int:
    try:
        delay_seconds = int(raw_delay_seconds)
    except (TypeError, ValueError):
        delay_seconds = MSGRAPH_DEFAULT_CALENDAR_DELAY_SECONDS

    return max(
        MSGRAPH_MIN_CALENDAR_DELAY_SECONDS,
        min(delay_seconds, MSGRAPH_MAX_CALENDAR_DELAY_SECONDS),
    )


def normalize_msgraph_calendar_send_options(raw_options: Any = None) -> Dict[str, Any]:
    options = raw_options if isinstance(raw_options, dict) else {}
    send_mode = normalize_msgraph_calendar_send_mode(
        options.get("msgraph_calendar_send_mode") or options.get("calendar_send_mode")
    )
    delay_seconds = normalize_msgraph_calendar_delay_seconds(
        options.get("msgraph_calendar_delay_seconds") or options.get("calendar_delay_seconds")
    )
    return {
        "msgraph_calendar_send_mode": send_mode,
        "msgraph_calendar_delay_seconds": delay_seconds,
    }


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