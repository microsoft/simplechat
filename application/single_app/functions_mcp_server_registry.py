# functions_mcp_server_registry.py

from functions_mcp_server_governance import evaluate_inbound_mcp_governance


PLANNED_INBOUND_MCP_TOOLS = (
    {
        "id": "list_conversations",
        "display_name": "List conversations",
        "description": "List conversations visible to the delegated user.",
        "scope": "personal",
        "resource_family": "conversations",
        "operation": "list",
        "identity_type": "delegated",
        "rate_limit_category": "read",
        "audit_event": "InboundMcpListConversations",
        "enabled_by_default": False,
        "implemented": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "offset": {"type": "integer", "minimum": 0},
                "include_hidden": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    {
        "id": "get_conversation_messages",
        "display_name": "Get conversation messages",
        "description": "Retrieve messages from an authorized personal conversation.",
        "scope": "personal",
        "resource_family": "conversations",
        "operation": "retrieve",
        "identity_type": "delegated",
        "rate_limit_category": "read",
        "audit_event": "InboundMcpGetConversationMessages",
        "enabled_by_default": False,
        "implemented": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "offset": {"type": "integer", "minimum": 0},
            },
            "required": ["conversation_id"],
            "additionalProperties": False,
        },
    },
    {
        "id": "list_personal_documents",
        "display_name": "List personal documents",
        "description": "List documents visible in the delegated user's personal workspace.",
        "scope": "personal",
        "resource_family": "documents",
        "operation": "list",
        "identity_type": "delegated",
        "rate_limit_category": "read",
        "audit_event": "InboundMcpListPersonalDocuments",
        "enabled_by_default": False,
        "implemented": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "offset": {"type": "integer", "minimum": 0},
                "tag": {"type": "string", "minLength": 1, "maxLength": 50},
            },
            "additionalProperties": False,
        },
    },
    {
        "id": "list_personal_prompts",
        "display_name": "List personal prompts",
        "description": "List prompts visible in the delegated user's personal workspace.",
        "scope": "personal",
        "resource_family": "prompts",
        "operation": "list",
        "identity_type": "delegated",
        "rate_limit_category": "read",
        "audit_event": "InboundMcpListPersonalPrompts",
        "enabled_by_default": False,
        "implemented": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "offset": {"type": "integer", "minimum": 0},
            },
            "additionalProperties": False,
        },
    },
    {
        "id": "list_personal_tags",
        "display_name": "List personal tags",
        "description": "List personal workspace tags available to the delegated user.",
        "scope": "personal",
        "resource_family": "tags",
        "operation": "list",
        "identity_type": "delegated",
        "rate_limit_category": "read",
        "audit_event": "InboundMcpListPersonalTags",
        "enabled_by_default": False,
        "implemented": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
    },
    {
        "id": "search_personal_documents",
        "display_name": "Search personal documents",
        "description": "Search documents visible in the delegated user's personal workspace.",
        "scope": "personal",
        "resource_family": "documents",
        "operation": "search",
        "identity_type": "delegated",
        "rate_limit_category": "search",
        "audit_event": "InboundMcpSearchPersonalDocuments",
        "enabled_by_default": False,
        "implemented": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 1000},
                "top_n": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "id": "execute_workflow",
        "display_name": "Execute workflow",
        "description": "Trigger an explicitly governed personal workflow for the delegated user.",
        "scope": "personal",
        "resource_family": "workflows",
        "operation": "execute",
        "identity_type": "delegated",
        "rate_limit_category": "write",
        "audit_event": "InboundMcpExecuteWorkflow",
        "enabled_by_default": False,
        "implemented": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "minLength": 1},
            },
            "required": ["workflow_id"],
            "additionalProperties": False,
        },
    },
)


def get_inbound_mcp_tool_registry():
    """Return planned inbound MCP tools without enabling them."""
    return [dict(tool) for tool in PLANNED_INBOUND_MCP_TOOLS]


def get_inbound_mcp_tool(tool_id):
    """Return one planned inbound MCP tool by id."""
    normalized_tool_id = str(tool_id or "").strip()
    for tool in PLANNED_INBOUND_MCP_TOOLS:
        if tool.get("id") == normalized_tool_id:
            return dict(tool)
    return None


def build_mcp_tool_descriptor(tool):
    """Return safe MCP tool metadata for the protocol tools/list response."""
    return {
        "name": tool.get("id", ""),
        "title": tool.get("display_name", ""),
        "description": tool.get("description", ""),
        "inputSchema": tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {
            "type": "object",
            "additionalProperties": False,
        },
    }


def get_enabled_inbound_mcp_tools(auth_context=None):
    """Return implemented inbound MCP tools allowed by explicit governance."""
    enabled_tools = []
    for tool in PLANNED_INBOUND_MCP_TOOLS:
        if not bool(tool.get("implemented", False)):
            continue
        decision = evaluate_inbound_mcp_governance(
            auth_context=auth_context,
            tool_id=tool.get("id", ""),
            resource_family=tool.get("resource_family", ""),
            operation=tool.get("operation", ""),
            scope=tool.get("scope", ""),
            target_scope_id=getattr(auth_context, "delegated_user_id", ""),
            identity_type=tool.get("identity_type", "delegated"),
        )
        if decision.allowed:
            enabled_tools.append(dict(tool))
    return enabled_tools
