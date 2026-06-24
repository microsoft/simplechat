# mcp_plugin_factory.py
"""Factory for creating Model Context Protocol Semantic Kernel plugins."""

import base64
from typing import Any, Dict, List, Optional

from semantic_kernel.connectors.mcp import (
    MCPSsePlugin,
    MCPStdioPlugin,
    MCPStreamableHttpPlugin,
    MCPWebsocketPlugin,
)

from functions_mcp_operations import (
    MCP_MAX_TOOL_RESULT_TEXT_LENGTH,
    MCP_PLUGIN_TYPE,
    normalize_mcp_additional_fields,
    normalize_mcp_tool_metadata,
)
from functions_debug import debug_print
from semantic_kernel_plugins.mcp_plugin import McpPlugin


class McpPluginFactory:
    """Factory for MCP plugin instances from stored action manifests."""

    @classmethod
    def create_from_config(cls, config: Dict[str, Any]) -> McpPlugin:
        """Create an MCP plugin from an action manifest."""
        manifest = dict(config or {})
        manifest["additionalFields"] = normalize_mcp_additional_fields(manifest.get("additionalFields", {}))
        return McpPlugin(manifest)

    @classmethod
    async def discover_tools_from_config(cls, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Connect to an MCP server and return normalized tool metadata."""
        connector = cls.create_connector(config)
        try:
            debug_print("[McpPluginFactory] Connecting to MCP server for tool discovery.")
            await connector.connect()
            if not connector.session:
                raise ValueError("MCP server did not create a session.")
            tool_list = await connector.session.list_tools()
            raw_tools = []
            for tool in tool_list.tools if tool_list else []:
                raw_tools.append({
                    "original_name": getattr(tool, "name", ""),
                    "function_name": getattr(tool, "name", ""),
                    "description": getattr(tool, "description", "") or "",
                    "input_schema": cls._coerce_schema(getattr(tool, "inputSchema", None)),
                })
            normalized_tools = normalize_mcp_tool_metadata(raw_tools)
            debug_print(f"[McpPluginFactory] MCP tool discovery succeeded tool_count={len(normalized_tools)}.")
            return normalized_tools
        finally:
            debug_print("[McpPluginFactory] Closing MCP discovery connector.")
            await connector.close()

    @classmethod
    async def call_tool_from_config(cls, config: Dict[str, Any], tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Connect to an MCP server, invoke one tool, and normalize the result."""
        connector = cls.create_connector(config)
        try:
            debug_print(f"[McpPluginFactory] Connecting to MCP server for tool call tool_name={tool_name}.")
            await connector.connect()
            raw_result = await connector.call_tool(tool_name, **(arguments or {}))
            result = cls._serialize_tool_result(tool_name, raw_result)
            debug_print(
                f"[McpPluginFactory] MCP tool call succeeded tool_name={tool_name} "
                f"success={result.get('success') if isinstance(result, dict) else '<unknown>'}."
            )
            return result
        finally:
            debug_print(f"[McpPluginFactory] Closing MCP tool connector tool_name={tool_name}.")
            await connector.close()

    @classmethod
    def create_connector(cls, config: Dict[str, Any]):
        """Create the native Semantic Kernel MCP connector for a manifest."""
        manifest = dict(config or {})
        additional_fields = normalize_mcp_additional_fields(manifest.get("additionalFields", {}))
        manifest["additionalFields"] = additional_fields
        transport = additional_fields.get("transport")
        name = str(manifest.get("name") or MCP_PLUGIN_TYPE).strip() or MCP_PLUGIN_TYPE
        description = str(manifest.get("description") or "Model Context Protocol action").strip()
        request_timeout = additional_fields.get("request_timeout")
        load_tools = bool(additional_fields.get("load_tools", True))
        load_prompts = bool(additional_fields.get("load_prompts", False))

        if transport == "stdio":
            command = str(additional_fields.get("command") or "").strip()
            if not command:
                raise ValueError("MCP stdio transport requires a command.")
            debug_print(
                f"[McpPluginFactory] Creating MCP stdio connector name={name} "
                f"command_present={bool(command)} args_count={len(list(additional_fields.get('args') or []))}"
            )
            return MCPStdioPlugin(
                name=name,
                command=command,
                args=list(additional_fields.get("args") or []),
                env=dict(additional_fields.get("env") or {}),
                load_tools=load_tools,
                load_prompts=load_prompts,
                request_timeout=request_timeout,
                description=description,
            )

        endpoint = str(manifest.get("endpoint") or "").strip()
        if not endpoint:
            raise ValueError("MCP remote transports require an endpoint.")

        headers = cls._build_headers(manifest)
        timeout = float(additional_fields.get("connect_timeout") or 10)
        sse_read_timeout = float(additional_fields.get("sse_read_timeout") or 300)
        debug_print(
            f"[McpPluginFactory] Creating MCP connector name={name} transport={transport} "
            f"endpoint={endpoint} timeout={timeout} sse_read_timeout={sse_read_timeout} "
            f"request_timeout={request_timeout} headers_present={bool(headers)}"
        )

        if transport == "sse":
            return MCPSsePlugin(
                name=name,
                url=endpoint,
                headers=headers,
                timeout=timeout,
                sse_read_timeout=sse_read_timeout,
                load_tools=load_tools,
                load_prompts=load_prompts,
                request_timeout=request_timeout,
                description=description,
            )
        if transport == "websocket":
            return MCPWebsocketPlugin(
                name=name,
                url=endpoint,
                load_tools=load_tools,
                load_prompts=load_prompts,
                request_timeout=request_timeout,
                description=description,
            )

        return MCPStreamableHttpPlugin(
            name=name,
            url=endpoint,
            headers=headers,
            timeout=timeout,
            sse_read_timeout=sse_read_timeout,
            terminate_on_close=True,
            load_tools=load_tools,
            load_prompts=load_prompts,
            request_timeout=request_timeout,
            description=description,
        )

    @classmethod
    def _build_headers(cls, manifest: Dict[str, Any]) -> Dict[str, str]:
        additional_fields = normalize_mcp_additional_fields(manifest.get("additionalFields", {}))
        auth = manifest.get("auth", {}) if isinstance(manifest.get("auth"), dict) else {}
        auth_method = additional_fields.get("auth_method") or "none"
        secret_value = str(auth.get("key") or "").strip()
        identity_value = str(auth.get("identity") or "").strip()

        if auth_method == "bearer" and secret_value:
            return {"Authorization": f"Bearer {secret_value}"}
        if auth_method == "api_key" and secret_value:
            header_name = str(additional_fields.get("api_key_header_name") or "X-API-Key").strip() or "X-API-Key"
            return {header_name: secret_value}
        if auth_method == "basic" and identity_value and secret_value:
            credential_bytes = f"{identity_value}:{secret_value}".encode("utf-8")
            encoded_credentials = base64.b64encode(credential_bytes).decode("ascii")
            return {"Authorization": f"Basic {encoded_credentials}"}

        identity_auth_type = str(additional_fields.get("identity_auth_type") or "").strip().lower()
        if identity_auth_type == "bearer_token" and secret_value:
            return {"Authorization": f"Bearer {secret_value}"}
        if identity_auth_type == "api_key" and secret_value:
            header_name = str(additional_fields.get("api_key_header_name") or "X-API-Key").strip() or "X-API-Key"
            return {header_name: secret_value}
        if identity_auth_type == "username_password" and identity_value and secret_value:
            credential_bytes = f"{identity_value}:{secret_value}".encode("utf-8")
            encoded_credentials = base64.b64encode(credential_bytes).decode("ascii")
            return {"Authorization": f"Basic {encoded_credentials}"}

        return {}

    @staticmethod
    def _coerce_schema(schema_value: Any) -> Dict[str, Any]:
        if isinstance(schema_value, dict):
            return schema_value
        if hasattr(schema_value, "model_dump"):
            return schema_value.model_dump(mode="json", exclude_none=True)
        return {}

    @classmethod
    def _serialize_tool_result(cls, tool_name: str, raw_result: Any) -> Dict[str, Any]:
        if isinstance(raw_result, list):
            content = [cls._serialize_content_item(item) for item in raw_result]
        else:
            content = cls._serialize_content_item(raw_result)
        return {
            "success": True,
            "tool_name": tool_name,
            "content": content,
        }

    @classmethod
    def _serialize_content_item(cls, item: Any) -> Any:
        if item is None or isinstance(item, (bool, int, float)):
            return item
        if isinstance(item, str):
            return cls._truncate_text(item)
        if isinstance(item, list):
            return [cls._serialize_content_item(child) for child in item]
        if isinstance(item, dict):
            return {str(key): cls._serialize_content_item(value) for key, value in item.items()}
        if hasattr(item, "model_dump"):
            try:
                return cls._serialize_content_item(item.model_dump(mode="json", exclude_none=True))
            except Exception:
                pass

        text_value = getattr(item, "text", None)
        if text_value is not None:
            return {
                "type": item.__class__.__name__,
                "text": cls._truncate_text(str(text_value)),
            }
        return cls._truncate_text(str(item))

    @staticmethod
    def _truncate_text(value: str) -> str:
        if len(value) <= MCP_MAX_TOOL_RESULT_TEXT_LENGTH:
            return value
        return f"{value[:MCP_MAX_TOOL_RESULT_TEXT_LENGTH]}... [truncated]"