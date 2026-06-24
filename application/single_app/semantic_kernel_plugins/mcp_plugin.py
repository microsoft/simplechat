# mcp_plugin.py
"""Semantic Kernel plugin descriptor for Model Context Protocol actions."""

from typing import Any, Dict, List, Optional

from semantic_kernel.functions import kernel_function
from semantic_kernel.functions.kernel_plugin import KernelPlugin

from functions_debug import debug_print
from functions_mcp_operations import (
    MCP_PLUGIN_TYPE,
    normalize_mcp_additional_fields,
    normalize_mcp_tool_metadata,
)
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger


class McpPlugin(BasePlugin):
    """Model Context Protocol action descriptor."""

    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        super().__init__(manifest)
        self.manifest = manifest or {}
        self._metadata = self.manifest.get("metadata", {}) if isinstance(self.manifest.get("metadata"), dict) else {}
        self._additional_fields = normalize_mcp_additional_fields(self.manifest.get("additionalFields", {}))
        self._allowed_tool_names = set(self._additional_fields.get("allowed_tool_names") or [])
        self._tools = self._filter_tools(
            normalize_mcp_tool_metadata(self._additional_fields.get("mcp_tools", []))
        )

    def _filter_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self._allowed_tool_names:
            return tools
        return [
            tool
            for tool in tools
            if tool.get("original_name") in self._allowed_tool_names
            or tool.get("function_name") in self._allowed_tool_names
        ]

    @property
    def display_name(self) -> str:
        return "Model Context Protocol"

    @property
    def metadata(self) -> Dict[str, Any]:
        methods = [
            {
                "name": "list_configured_tools",
                "description": "List MCP tools configured on this action manifest.",
                "parameters": [],
                "returns": {"type": "dict", "description": "Configured MCP tool metadata."},
            }
        ]

        for tool in self._tools:
            methods.append({
                "name": tool.get("function_name") or tool.get("original_name"),
                "description": tool.get("description") or "MCP tool discovered from the configured server.",
                "parameters": [],
                "returns": {"type": "object", "description": "MCP tool result."},
            })

        return {
            "name": self.manifest.get("name", "mcp"),
            "type": MCP_PLUGIN_TYPE,
            "description": self.manifest.get("description") or "Model Context Protocol action configuration.",
            "transport": self._additional_fields.get("transport"),
            "methods": methods,
        }

    def get_functions(self) -> List[str]:
        return ["list_configured_tools", "call_tool"] + [
            tool.get("function_name")
            for tool in self._tools
            if tool.get("function_name")
        ]

    def get_kernel_plugin(self, plugin_name: str = "mcp") -> KernelPlugin:
        """Create a KernelPlugin with dynamic MCP tool functions."""
        functions = {
            "list_configured_tools": self.list_configured_tools,
            "call_tool": self.call_tool,
        }

        for tool in self._tools:
            function_name = tool.get("function_name")
            original_name = tool.get("original_name")
            if not function_name or not original_name:
                continue
            functions[function_name] = self._create_tool_function(tool)

        return KernelPlugin.from_object(
            plugin_name,
            functions,
            description=self.metadata.get("description"),
        )

    def _create_tool_function(self, tool: Dict[str, Any]):
        original_name = tool.get("original_name")
        function_name = tool.get("function_name")
        description = tool.get("description") or f"Call MCP tool {original_name}."
        input_schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {}

        if input_schema:
            description = f"{description}\n\nInput schema: {input_schema}"

        async def tool_function(**kwargs):
            return await self.invoke_tool(original_name, kwargs)

        tool_function.__name__ = function_name
        tool_function.__qualname__ = f"McpPlugin.{function_name}"
        wrapped_function = plugin_function_logger("McpPlugin")(tool_function)
        return kernel_function(name=function_name, description=description)(wrapped_function)

    @plugin_function_logger("McpPlugin")
    @kernel_function(description="List the MCP tools configured on this action manifest.")
    def list_configured_tools(self) -> dict:
        """Return configured MCP tool metadata for this action."""
        return {
            "success": True,
            "transport": self._additional_fields.get("transport"),
            "allowed_tool_names": sorted(self._allowed_tool_names),
            "tool_count": len(self._tools),
            "tools": self._tools,
        }

    @plugin_function_logger("McpPlugin")
    @kernel_function(description="Call an MCP tool by its original MCP tool name with a JSON object of arguments.")
    async def call_tool(self, tool_name: str, arguments: Optional[dict] = None) -> dict:
        """Call a configured MCP tool by original name."""
        normalized_tool_name = str(tool_name or "").strip()
        if not normalized_tool_name:
            return {
                "success": False,
                "error": "tool_name is required",
                "error_type": "validation",
            }

        configured_tool_names = {tool.get("original_name") for tool in self._tools}
        if self._allowed_tool_names and normalized_tool_name not in self._allowed_tool_names and normalized_tool_name not in configured_tool_names:
            return {
                "success": False,
                "error": f"Tool '{normalized_tool_name}' is not allowed for this MCP action.",
                "error_type": "not_allowed",
                "allowed_tools": sorted(self._allowed_tool_names),
            }
        if configured_tool_names and normalized_tool_name not in configured_tool_names:
            return {
                "success": False,
                "error": f"Tool '{normalized_tool_name}' is not configured for this MCP action.",
                "error_type": "not_configured",
                "configured_tools": sorted(configured_tool_names),
            }

        return await self.invoke_tool(normalized_tool_name, arguments or {})

    async def invoke_tool(self, tool_name: str, arguments: Optional[dict] = None) -> dict:
        """Invoke an MCP tool through the factory's native MCP connector."""
        try:
            debug_print(
                f"[McpPlugin] Invoking MCP tool tool_name={tool_name} "
                f"transport={self._additional_fields.get('transport')} "
                f"endpoint_present={bool(str(self.manifest.get('endpoint') or '').strip())} "
                f"argument_keys={sorted((arguments or {}).keys())}"
            )
            from semantic_kernel_plugins.mcp_plugin_factory import McpPluginFactory

            result = await McpPluginFactory.call_tool_from_config(
                self.manifest,
                tool_name,
                arguments or {},
            )
            debug_print(
                f"[McpPlugin] MCP tool completed tool_name={tool_name} "
                f"success={result.get('success') if isinstance(result, dict) else '<unknown>'}"
            )
            return result
        except ValueError as exc:
            debug_print(f"[McpPlugin] MCP tool validation failed tool_name={tool_name} message={exc}")
            return {
                "success": False,
                "error": str(exc),
                "error_type": "validation",
            }
        except Exception as exc:
            debug_print(
                f"[McpPlugin] MCP tool call failed tool_name={tool_name} "
                f"exception_type={type(exc).__name__} message={exc}"
            )
            return {
                "success": False,
                "error": f"Failed to call MCP tool '{tool_name}'.",
                "error_type": "mcp_call_failed",
                "details": str(exc),
            }