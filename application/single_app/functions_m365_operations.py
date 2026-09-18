# functions_m365_operations.py
"""Authoritative source, capability, and configuration contracts for M365 actions."""

from copy import deepcopy
from functools import wraps
from inspect import signature
from typing import Any, Dict, List, Optional

from functions_msgraph_operations import (
    MSGRAPH_CAPABILITY_DEFINITIONS,
    normalize_msgraph_calendar_send_options,
    normalize_msgraph_mail_send_options,
)


M365_SHARING_DURATIONS = ("request", "today", "always")
M365_FILE_SOURCES = frozenset({"onedrive", "spo"})
M365_SOURCES = frozenset({"calendar", "email", "onedrive", "spo"})
M365_WRITE_FUNCTIONS = frozenset({
    "create_calendar_invite", "mark_message_as_read", "send_mail",
})
M365_DIRECTORY_FUNCTIONS = frozenset({"search_users", "get_user_by_email"})

_LEGACY_DEFINITIONS = {
    definition["function_name"]: definition
    for definition in MSGRAPH_CAPABILITY_DEFINITIONS
}
_FILE_FUNCTION_DEFINITIONS = [
    {
        "key": "analyze_file",
        "function_name": "analyze_file",
        "label": "Analyze retained file evidence",
        "description": "Analyze one approved batch of a prepared source-specific file without loading the whole file into the main conversation.",
        "requires_remote_access": False,
        "parameters": [
            {"name": "memory_id", "type": "str", "required": True, "description": "Prepared file run ID or exact evidence reference from this source."},
            {"name": "question", "type": "str", "required": True, "description": "The analysis question."},
            {"name": "analysis_id", "type": "str", "required": False, "description": "Analysis run returned by the preceding batch."},
        ],
    },
    {
        "key": "search_files",
        "function_name": "search_files",
        "label": "Find relevant file excerpts",
        "description": "Find accessible files and grounding excerpts, with source and coverage information.",
        "parameters": [
            {"name": "query", "type": "str", "required": True, "description": "Natural-language search, not KQL."},
            {"name": "folder", "type": "str", "required": False, "description": "Optional exact folder URL; OneDrive also accepts a path in your own drive."},
            {"name": "top", "type": "int", "required": False, "description": "Number of results, from 1 to 25."},
        ],
    },
    {
        "key": "discover_files",
        "function_name": "discover_files",
        "label": "Discover a resumable set of files",
        "description": "Persist a bounded page of file identities and discovery progress for later analysis.",
        "parameters": [
            {"name": "query", "type": "str", "required": True, "description": "Natural-language search, not KQL."},
            {"name": "folder", "type": "str", "required": False, "description": "Optional exact folder URL or OneDrive path."},
            {"name": "memory_id", "type": "str", "required": False, "description": "Authorized discovery manifest to continue, if returned previously."},
        ],
    },
    {
        "key": "prepare_file",
        "function_name": "prepare_file",
        "label": "Capture file evidence",
        "description": "Read an accessible file into durable conversation evidence, subject to analysis approval and hard limits.",
        "parameters": [
            {"name": "drive_id", "type": "str", "required": False, "description": "Canonical Graph drive ID from discovery."},
            {"name": "item_id", "type": "str", "required": False, "description": "Canonical Graph item ID from discovery."},
            {"name": "web_url", "type": "str", "required": False, "description": "Canonical file URL, used only when IDs are unavailable."},
        ],
    },
    {
        "key": "read_file",
        "function_name": "read_file",
        "label": "Read file content",
        "description": "Capture a file and return a context-bounded evidence window with references to unread chunks.",
        "parameters": [
            {"name": "drive_id", "type": "str", "required": False, "description": "Canonical Graph drive ID from discovery."},
            {"name": "item_id", "type": "str", "required": False, "description": "Canonical Graph item ID from discovery."},
            {"name": "web_url", "type": "str", "required": False, "description": "Canonical file URL, used only when IDs are unavailable."},
        ],
    },
    {
        "key": "read_file_chunk",
        "function_name": "read_file_chunk",
        "label": "Read retained file evidence",
        "description": "Reload a bounded captured evidence chunk. Published snapshots use conversation access, not fresh remote access.",
        "requires_remote_access": False,
        "parameters": [
            {"name": "memory_id", "type": "str", "required": True, "description": "Authorized file-evidence manifest ID."},
            {"name": "chunk_index", "type": "int", "required": False, "description": "Zero-based evidence chunk index."},
            {"name": "char_offset", "type": "int", "required": False, "description": "Character offset inside the chunk, when a previous model window returned next_char_offset."},
        ],
    },
]


def _capability_definitions(function_names):
    return [
        {
            **deepcopy(_LEGACY_DEFINITIONS[name]),
            "default": name not in M365_WRITE_FUNCTIONS | M365_DIRECTORY_FUNCTIONS,
            "requires_remote_access": True,
        }
        for name in function_names
    ]


M365_ACTION_DEFINITIONS = {
    "m365_calendar": {
        "type": "m365_calendar",
        "source": "calendar",
        "display_name": "Microsoft 365 Calendar",
        "class_name": "M365CalendarPlugin",
        "description": "Delegated calendar reads, mailbox timezone, and explicitly enabled invite delivery.",
        "capabilities": _capability_definitions((
            "get_my_timezone", "get_my_events", "create_calendar_invite",
            "search_users", "get_user_by_email",
        )),
    },
    "m365_email": {
        "type": "m365_email",
        "source": "email",
        "display_name": "Microsoft 365 Email",
        "class_name": "M365EmailPlugin",
        "description": "Delegated mail reads and explicitly enabled read-state or mail-delivery operations.",
        "capabilities": _capability_definitions((
            "get_my_messages", "mark_message_as_read", "send_mail",
            "search_users", "get_user_by_email",
        )),
    },
    "m365_onedrive": {
        "type": "m365_onedrive",
        "source": "onedrive",
        "display_name": "Microsoft 365 OneDrive",
        "class_name": "M365OneDrivePlugin",
        "description": "Live delegated OneDrive for Business file discovery, grounding, and retained conversation evidence.",
        "capabilities": [
            {"requires_remote_access": True, **deepcopy(item), "default": True}
            for item in _FILE_FUNCTION_DEFINITIONS
        ],
    },
    "m365_sharepoint": {
        "type": "m365_sharepoint",
        "source": "spo",
        "display_name": "Microsoft 365 SharePoint Online",
        "class_name": "M365SharePointPlugin",
        "description": "Live delegated SPO document-library discovery, grounding, and retained conversation evidence.",
        "capabilities": [
            {"requires_remote_access": True, **deepcopy(item), "default": True}
            for item in _FILE_FUNCTION_DEFINITIONS
        ],
    },
}
M365_ACTION_TYPES = tuple(M365_ACTION_DEFINITIONS)
M365_PLUGIN_TYPES = M365_ACTION_TYPES
M365_LEGACY_OPERATION_SOURCES = {
    "get_my_timezone": "calendar",
    "get_my_events": "calendar",
    "create_calendar_invite": "calendar",
    "resolve_calendar_timezone": "calendar",
    "resolve_calendar_identity": "calendar",
    "create_calendar_invite_delayed_delivery": "calendar",
    "get_my_messages": "email",
    "mark_message_as_read": "email",
    "send_mail": "email",
    "send_mail_delayed_delivery": "email",
    "list_drive_items": "onedrive",
}
M365_INTERNAL_OPERATION_FUNCTIONS = {
    "resolve_calendar_timezone": "create_calendar_invite",
    "resolve_calendar_identity": "create_calendar_invite",
    "create_calendar_invite_delayed_delivery": "create_calendar_invite",
    "send_mail_delayed_delivery": "send_mail",
}
M365_SELECTED_RESOURCE_SOURCES = {
    "mailboxsettings": ("calendar", "get_my_timezone"),
    "calendar": ("calendar", "get_my_events"),
    "calendars": ("calendar", "get_my_events"),
    "calendarview": ("calendar", "get_my_events"),
    "events": ("calendar", "get_my_events"),
    "messages": ("email", "get_my_messages"),
    "mailfolders": ("email", "get_my_messages"),
    "drive": ("onedrive", "list_drive_items"),
    "drives": ("onedrive", "list_drive_items"),
}


def get_m365_action_definition(action_type: str) -> Dict[str, Any]:
    """Return a copy so consumers cannot mutate the authoritative capability bounds."""
    if action_type not in M365_ACTION_DEFINITIONS:
        raise ValueError("Unsupported Microsoft 365 action type.")
    return deepcopy(M365_ACTION_DEFINITIONS[action_type])


def is_m365_action_type(action_type: Any) -> bool:
    return isinstance(action_type, str) and action_type in M365_ACTION_DEFINITIONS


def get_m365_default_capabilities(action_type: str) -> Dict[str, bool]:
    return {
        definition["key"]: definition["default"]
        for definition in get_m365_action_definition(action_type)["capabilities"]
    }


def _capability_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise ValueError("Microsoft 365 capabilities must be boolean values.")


def normalize_m365_capabilities(action_type: str, raw_capabilities: Any = None) -> Dict[str, bool]:
    normalized = get_m365_default_capabilities(action_type)
    if raw_capabilities is None:
        return normalized
    if isinstance(raw_capabilities, dict):
        for name in normalized:
            if name in raw_capabilities:
                normalized[name] = _capability_boolean(raw_capabilities[name])
        return normalized
    if isinstance(raw_capabilities, (list, tuple, set, frozenset)):
        return {name: name in raw_capabilities for name in normalized}
    raise ValueError("Microsoft 365 capabilities must be an object or a list of function names.")


def _restrict_m365_capabilities(capabilities: Dict[str, bool], restrictions: Any) -> Dict[str, bool]:
    if restrictions is None:
        return capabilities
    if isinstance(restrictions, dict):
        return {
            name: enabled and _capability_boolean(restrictions.get(name, enabled))
            for name, enabled in capabilities.items()
        }
    if isinstance(restrictions, (list, tuple, set, frozenset)):
        return {name: enabled and name in restrictions for name, enabled in capabilities.items()}
    raise ValueError("Microsoft 365 capability restrictions must be an object or a list.")


def _config_m365_capabilities(action_type: str, config: Dict[str, Any]) -> Dict[str, bool]:
    additional = config.get("additionalFields", {})
    if not isinstance(additional, dict):
        raise ValueError("Microsoft 365 additionalFields must be an object.")
    if "m365_capabilities" in additional:
        saved = normalize_m365_capabilities(action_type, additional["m365_capabilities"])
        return _restrict_m365_capabilities(saved, config.get("m365_capabilities"))
    return normalize_m365_capabilities(action_type, config.get("m365_capabilities"))


def get_m365_enabled_function_names(
    action_type: str,
    raw_capabilities: Any = None,
    enabled_functions: Optional[List[str]] = None,
    agent_capabilities: Any = None,
) -> List[str]:
    """Intersect type, saved capabilities, explicit functions, and agent restrictions."""
    if isinstance(raw_capabilities, dict) and any(
        key in raw_capabilities for key in ("m365_capabilities", "additionalFields", "enabled_functions")
    ):
        config = raw_capabilities
        normalized = _config_m365_capabilities(action_type, config)
        if enabled_functions is None and "enabled_functions" in config:
            enabled_functions = config["enabled_functions"]
    else:
        normalized = normalize_m365_capabilities(action_type, raw_capabilities)
    if enabled_functions is not None:
        if not isinstance(enabled_functions, (list, tuple, set, frozenset)):
            raise ValueError("enabled_functions must be a list of function names.")
        normalized = {name: enabled and name in enabled_functions for name, enabled in normalized.items()}
    normalized = _restrict_m365_capabilities(normalized, agent_capabilities)
    return [name for name, enabled in normalized.items() if enabled]


def get_m365_remote_function_names(
    action_type: str,
    raw_capabilities: Any = None,
    enabled_functions: Optional[List[str]] = None,
    agent_capabilities: Any = None,
) -> List[str]:
    """Return enabled functions that need fresh delegated source access, not snapshot-only reads."""
    enabled = set(get_m365_enabled_function_names(
        action_type, raw_capabilities, enabled_functions, agent_capabilities,
    ))
    return [
        definition["function_name"]
        for definition in get_m365_action_definition(action_type)["capabilities"]
        if definition["function_name"] in enabled and definition["requires_remote_access"]
    ]


def get_m365_function_definitions(action_type: str) -> List[Dict[str, Any]]:
    return [
        {
            **definition,
            "name": definition["function_name"],
            "returns": {"type": "dict", "description": "Source-attributed result with explicit coverage or an error."},
        }
        for definition in get_m365_action_definition(action_type)["capabilities"]
    ]


def get_m365_default_config(action_type: str) -> Dict[str, Any]:
    definition = get_m365_action_definition(action_type)
    additional = {
        "m365_capabilities": get_m365_default_capabilities(action_type),
        "maximum_sharing_acknowledgement": "always",
    }
    if definition["source"] == "calendar":
        additional.update(normalize_msgraph_calendar_send_options({
            "msgraph_calendar_send_mode": "draft_manual",
        }))
    elif definition["source"] == "email":
        additional.update(normalize_msgraph_mail_send_options())
    return {
        "type": action_type,
        "auth": {"type": "user"},
        "additionalFields": additional,
    }


def normalize_m365_action_config(action_type: str, config: Any = None) -> Dict[str, Any]:
    """Normalize a saved action; endpoints, tokens, and source restrictions are not action options."""
    if config is not None and not isinstance(config, dict):
        raise ValueError("Microsoft 365 action configuration must be an object.")
    definition = get_m365_action_definition(action_type)
    normalized = deepcopy(config or {})
    additional = normalized.get("additionalFields", {})
    if not isinstance(additional, dict):
        raise ValueError("Microsoft 365 additionalFields must be an object.")
    unsupported_scope_fields = {
        "allowed_sites", "allowed_folders", "site_ids", "folder_ids",
        "site_allowlist", "folder_allowlist", "site_id", "folder_id",
    }
    if unsupported_scope_fields.intersection(normalized) or unsupported_scope_fields.intersection(additional):
        raise ValueError("Microsoft 365 folder and site scopes belong to individual requests, not action configuration.")
    capabilities = _config_m365_capabilities(action_type, normalized)
    durations = [
        fields["maximum_sharing_acknowledgement"]
        for fields in (additional, normalized)
        if "maximum_sharing_acknowledgement" in fields
    ] or ["always"]
    if any(duration not in M365_SHARING_DURATIONS for duration in durations):
        raise ValueError("Invalid maximum sharing acknowledgement duration.")
    duration = min(durations, key=M365_SHARING_DURATIONS.index)
    normalized["type"] = action_type
    normalized["auth"] = {"type": "user"}
    normalized.pop("endpoint", None)
    normalized.pop("scopes", None)
    normalized["m365_capabilities"] = capabilities
    normalized["maximum_sharing_acknowledgement"] = duration
    normalized["enabled_functions"] = get_m365_enabled_function_names(
        action_type, capabilities, normalized.get("enabled_functions")
    )
    allowed_additional = {
        "m365_capabilities": capabilities,
        "maximum_sharing_acknowledgement": duration,
    }
    delivery_options = {**additional, **normalized}
    delivery_prefix = {"calendar": "calendar", "email": "mail"}.get(definition["source"])
    if delivery_prefix:
        mode_key = f"msgraph_{delivery_prefix}_send_mode"
        delay_key = f"msgraph_{delivery_prefix}_delay_seconds"
        mode = delivery_options.get(mode_key) or delivery_options.get(f"{delivery_prefix}_send_mode") or "draft_manual"
        delay = delivery_options.get(delay_key)
        if delay is None:
            delay = delivery_options.get(f"{delivery_prefix}_delay_seconds", 60)
        if mode not in ("draft_manual", "draft_delayed", "auto_send"):
            raise ValueError("Microsoft 365 delivery mode must be draft_manual, draft_delayed, or auto_send.")
        if type(delay) is not int or not 5 <= delay <= 600:
            raise ValueError("Microsoft 365 delivery delay must be an integer from 5 to 600 seconds.")
        delivery_options[mode_key] = mode
        delivery_options[delay_key] = delay
        normalized.pop(mode_key, None)
        normalized.pop(delay_key, None)
    if definition["source"] == "calendar":
        allowed_additional.update(normalize_msgraph_calendar_send_options(delivery_options))
    elif definition["source"] == "email":
        allowed_additional.update(normalize_msgraph_mail_send_options(delivery_options))
    normalized["additionalFields"] = allowed_additional
    return normalized


def get_m365_schema_for_type(action_type: str) -> Dict[str, Any]:
    definition = get_m365_action_definition(action_type)
    defaults = get_m365_default_config(action_type)["additionalFields"]
    capability_properties = {
        item["key"]: {
            "type": "boolean",
            "title": item["label"],
            "description": item["description"],
            "default": item["default"],
        }
        for item in definition["capabilities"]
    }
    additional_properties = {
        "m365_capabilities": {
            "type": "object",
            "properties": capability_properties,
            "additionalProperties": False,
            "default": defaults["m365_capabilities"],
        },
        "maximum_sharing_acknowledgement": {
            "type": "string",
            "enum": list(M365_SHARING_DURATIONS),
            "default": "always",
            "description": "Longest acknowledgement this action accepts; never pre-approves sharing.",
        },
    }
    delivery_prefix = {"calendar": "calendar", "email": "mail"}.get(definition["source"])
    if delivery_prefix:
        mode_key = f"msgraph_{delivery_prefix}_send_mode"
        delay_key = f"msgraph_{delivery_prefix}_delay_seconds"
        additional_properties[mode_key] = {
            "type": "string",
            "enum": ["draft_manual", "draft_delayed", "auto_send"],
            "default": defaults[mode_key],
        }
        additional_properties[delay_key] = {
            "type": "integer", "minimum": 5, "maximum": 600, "default": defaults[delay_key],
        }
    return {
        "type": "object",
        "title": definition["display_name"],
        "properties": {
            "type": {"type": "string", "const": action_type},
            "auth": {
                "type": "object",
                "properties": {"type": {"const": "user"}},
                "required": ["type"],
                "additionalProperties": False,
            },
            "additionalFields": {
                "type": "object",
                "properties": additional_properties,
                "additionalProperties": False,
            },
            "enabled_functions": {
                "type": "array",
                "items": {"type": "string", "enum": list(capability_properties)},
                "uniqueItems": True,
            },
        },
    }


def get_m365_operation_source(operation_name: str, action_type: str = "msgraph") -> Optional[str]:
    if is_m365_action_type(action_type):
        definition = M365_ACTION_DEFINITIONS[action_type]
        operation = M365_INTERNAL_OPERATION_FUNCTIONS.get(operation_name, operation_name)
        if operation in {item["function_name"] for item in definition["capabilities"]}:
            return definition["source"]
        return None
    return M365_LEGACY_OPERATION_SOURCES.get(operation_name)


def guarded_m365_operation(function):
    """Keep direct invocation subject to the same bounds as Semantic Kernel registration."""
    function_signature = signature(function)

    @wraps(function)
    def guarded(self, *args, **kwargs):
        arguments = function_signature.bind(self, *args, **kwargs).arguments
        denial = self._authorize_operation(function.__name__, arguments.get("select_fields", ""))
        if denial:
            return denial
        with self._operation_context(function.__name__):
            result = function(self, *args, **kwargs)
        source = get_m365_operation_source(function.__name__, self._action_type)
        if source and isinstance(result, dict):
            result.setdefault("source", source)
            result.setdefault("provider", "graph")
        return result
    return guarded
