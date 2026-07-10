# functions_mcp_server_registry.py

PLANNED_INBOUND_MCP_TOOLS = (
    {
        "id": "show_user_profile",
        "display_name": "Show user profile",
        "description": "Return a redacted profile for the delegated user.",
        "scope": "personal",
        "resource_family": "profile",
        "operation": "retrieve",
        "identity_type": "delegated",
        "enabled_by_default": False,
    },
    {
        "id": "list_conversations",
        "display_name": "List conversations",
        "description": "List conversations visible to the delegated user.",
        "scope": "personal",
        "resource_family": "conversations",
        "operation": "list",
        "identity_type": "delegated",
        "enabled_by_default": False,
    },
    {
        "id": "get_conversation_messages",
        "display_name": "Get conversation messages",
        "description": "Retrieve messages from an authorized personal conversation.",
        "scope": "personal",
        "resource_family": "conversations",
        "operation": "retrieve",
        "identity_type": "delegated",
        "enabled_by_default": False,
    },
    {
        "id": "list_personal_documents",
        "display_name": "List personal documents",
        "description": "List documents visible in the delegated user's personal workspace.",
        "scope": "personal",
        "resource_family": "documents",
        "operation": "list",
        "identity_type": "delegated",
        "enabled_by_default": False,
    },
    {
        "id": "search_personal_documents",
        "display_name": "Search personal documents",
        "description": "Search documents visible in the delegated user's personal workspace.",
        "scope": "personal",
        "resource_family": "documents",
        "operation": "search",
        "identity_type": "delegated",
        "enabled_by_default": False,
    },
)


def get_inbound_mcp_tool_registry():
    """Return planned inbound MCP tools without enabling them."""
    return [dict(tool) for tool in PLANNED_INBOUND_MCP_TOOLS]


def get_enabled_inbound_mcp_tools(auth_context=None):
    """Return enabled inbound MCP tools for the disabled shell."""
    _ = auth_context
    return []
