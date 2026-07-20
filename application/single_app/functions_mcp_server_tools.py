# functions_mcp_server_tools.py

from functions_documents import get_workspace_tags


INBOUND_MCP_TOOL_RESULT_LIMIT_DEFAULT = 100
INBOUND_MCP_TOOL_RESULT_LIMIT_MAX = 100


def _coerce_limit(value, default_value=INBOUND_MCP_TOOL_RESULT_LIMIT_DEFAULT):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default_value
    return min(max(limit, 1), INBOUND_MCP_TOOL_RESULT_LIMIT_MAX)


def _require_delegated_user_id(auth_context):
    delegated_user_id = str(getattr(auth_context, "delegated_user_id", "") or "").strip()
    if not delegated_user_id:
        raise PermissionError("Inbound MCP tool requires a delegated user identity.")
    return delegated_user_id


def list_personal_tags(auth_context, arguments=None):
    """List personal workspace tags for the delegated user."""
    delegated_user_id = _require_delegated_user_id(auth_context)
    arguments = arguments if isinstance(arguments, dict) else {}
    limit = _coerce_limit(arguments.get("limit"))
    tags = []
    for tag in (get_workspace_tags(delegated_user_id) or [])[:limit]:
        if not isinstance(tag, dict):
            continue
        tag_name = str(tag.get("name") or "").strip()
        if not tag_name:
            continue
        tags.append({
            "name": tag_name,
            "count": int(tag.get("count") or 0),
            "color": str(tag.get("color") or "").strip(),
        })
    return {
        "scope": "personal",
        "tags": tags,
        "count": len(tags),
        "limit": limit,
    }


def execute_inbound_mcp_tool(tool_id, auth_context, arguments=None):
    """Dispatch an implemented inbound MCP tool."""
    normalized_tool_id = str(tool_id or "").strip()
    if normalized_tool_id == "list_personal_tags":
        return list_personal_tags(auth_context, arguments)
    raise LookupError(f"Inbound MCP tool '{normalized_tool_id}' is not implemented.")
