# mcp_plugin_factory.py
"""Factory for creating Model Context Protocol Semantic Kernel plugins."""

import asyncio
import base64
import logging
import time
from typing import Any, Dict, List, Optional

from semantic_kernel.connectors.mcp import (
    MCPSsePlugin,
    MCPStdioPlugin,
    MCPStreamableHttpPlugin,
    MCPWebsocketPlugin,
)

from functions_appinsights import log_event
from functions_debug import debug_print
from functions_mcp_operations import (
    MCP_CUSTOM_HEADERS_FIELD,
    MCP_PLUGIN_TYPE,
    McpRuntimeError,
    apply_mcp_result_text_policy,
    build_mcp_tool_metadata_warnings,
    classify_mcp_exception,
    get_mcp_custom_header_validation_errors,
    is_valid_mcp_header_name,
    normalize_mcp_additional_fields,
    normalize_mcp_tool_metadata,
    validate_mcp_endpoint_for_transport,
)
from functions_mcp_destinations import (
    assert_mcp_destination_allowed,
    build_mcp_destination_log_context,
    infer_mcp_destination_scope,
)
from functions_mcp_preconfigurations import assert_mcp_preconfiguration_manifest_allowed
from semantic_kernel_plugins.mcp_plugin import McpPlugin


class McpPluginFactory:
    """Factory for MCP plugin instances from stored action manifests."""

    @classmethod
    def _build_operation_log_context(
        cls,
        config: Dict[str, Any],
        operation: str,
        attempt: Optional[int] = None,
        tool_name: str = "",
    ) -> Dict[str, Any]:
        """Build low-sensitivity structured telemetry for an outbound MCP operation."""
        manifest = dict(config or {})
        additional_fields = normalize_mcp_additional_fields(manifest.get("additionalFields", {}))
        auth = manifest.get("auth") if isinstance(manifest.get("auth"), dict) else {}
        context = {
            "mcp_operation_id": str(manifest.get("mcp_operation_id") or "").strip(),
            "operation": operation,
            "action_name": str(manifest.get("name") or "").strip(),
            "transport": additional_fields.get("transport"),
            "auth_method": additional_fields.get("auth_method"),
            "preconfiguration_id": additional_fields.get("preconfiguration_id"),
            "server_profile": additional_fields.get("server_profile"),
            "custom_header_count": len(additional_fields.get(MCP_CUSTOM_HEADERS_FIELD) or {}),
            "has_auth_secret": bool(str(auth.get("key") or "").strip()),
            "has_identity": bool(str(auth.get("identity") or "").strip()),
        }
        context.update({
            f"destination_{key}": value
            for key, value in build_mcp_destination_log_context(manifest).items()
        })
        if attempt is not None:
            context["attempt"] = attempt
        if tool_name:
            context["tool_name"] = tool_name
        return context

    @classmethod
    def _log_connector_event(
        cls,
        message: str,
        config: Dict[str, Any],
        operation: str,
        level: int = logging.INFO,
        debug_only: bool = False,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        context = cls._build_operation_log_context(config, operation)
        context.update(extra or {})
        log_event(message, extra=context, level=level, debug_only=debug_only)

    @classmethod
    def create_from_config(cls, config: Dict[str, Any]) -> McpPlugin:
        """Create an MCP plugin from an action manifest."""
        manifest = dict(config or {})
        manifest["additionalFields"] = normalize_mcp_additional_fields(manifest.get("additionalFields", {}))
        return McpPlugin(manifest)

    @classmethod
    async def discover_tools_from_config(cls, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Connect to an MCP server and return normalized tool metadata."""
        return await cls._run_with_retries(
            config,
            "tool_discovery",
            lambda: cls._discover_tools_once(config),
        )

    @classmethod
    async def probe_server_from_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """Connect to an MCP server and return tool metadata plus compatibility hints."""
        return await cls._run_with_retries(
            config,
            "capability_probe",
            lambda: cls._probe_server_once(config),
        )

    @classmethod
    async def _probe_server_once(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """Perform one MCP compatibility probe attempt."""
        manifest = dict(config or {})
        additional_fields = normalize_mcp_additional_fields(manifest.get("additionalFields", {}))
        connector = cls.create_connector(manifest)
        started_at = time.perf_counter()
        try:
            cls._log_connector_event(
                "[MCPOutbound] Capability probe connector starting",
                manifest,
                "capability_probe",
                level=logging.INFO,
                debug_only=True,
            )
            await connector.connect()
            if not connector.session:
                raise ValueError("MCP server did not create a session.")

            tools = await cls._list_tools_from_session(connector.session)
            capabilities = {
                "tools": bool(tools),
                "prompts_requested": bool(additional_fields.get("load_prompts")),
                "resources": False,
                "connector_type": connector.__class__.__name__,
                "session_type": connector.session.__class__.__name__,
            }
            warnings = build_mcp_tool_metadata_warnings(tools, additional_fields)
            result = {
                "transport": additional_fields.get("transport"),
                "auth_method": additional_fields.get("auth_method"),
                "tool_count": len(tools),
                "tools": tools,
                "capabilities": capabilities,
                "warnings": warnings,
            }
            cls._log_connector_event(
                "[MCPOutbound] Capability probe connector completed",
                manifest,
                "capability_probe",
                level=logging.INFO,
                debug_only=True,
                extra={
                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "tool_count": len(tools),
                    "warning_count": len(warnings),
                    "connector_type": connector.__class__.__name__,
                },
            )
            return result
        finally:
            cls._log_connector_event(
                "[MCPOutbound] Capability probe connector closing",
                manifest,
                "capability_probe",
                level=logging.INFO,
                debug_only=True,
            )
            await connector.close()

    @classmethod
    async def _discover_tools_once(cls, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Perform one MCP tool discovery attempt."""
        connector = cls.create_connector(config)
        started_at = time.perf_counter()
        try:
            cls._log_connector_event(
                "[MCPOutbound] Tool discovery connector starting",
                config,
                "tool_discovery",
                level=logging.INFO,
                debug_only=True,
            )
            await connector.connect()
            if not connector.session:
                raise ValueError("MCP server did not create a session.")
            normalized_tools = await cls._list_tools_from_session(connector.session)
            cls._log_connector_event(
                "[MCPOutbound] Tool discovery connector completed",
                config,
                "tool_discovery",
                level=logging.INFO,
                debug_only=True,
                extra={
                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "tool_count": len(normalized_tools),
                    "connector_type": connector.__class__.__name__,
                },
            )
            return normalized_tools
        finally:
            cls._log_connector_event(
                "[MCPOutbound] Tool discovery connector closing",
                config,
                "tool_discovery",
                level=logging.INFO,
                debug_only=True,
            )
            await connector.close()

    @classmethod
    async def _list_tools_from_session(cls, session) -> List[Dict[str, Any]]:
        tool_list = await session.list_tools()
        raw_tools = []
        for tool in tool_list.tools if tool_list else []:
            raw_tools.append({
                "original_name": getattr(tool, "name", ""),
                "function_name": getattr(tool, "name", ""),
                "description": getattr(tool, "description", "") or "",
                "input_schema": cls._coerce_schema(
                    getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None)
                ),
                "output_schema": cls._coerce_schema(
                    getattr(tool, "outputSchema", None) or getattr(tool, "output_schema", None)
                ),
                "annotations": cls._coerce_object(
                    getattr(tool, "annotations", None)
                ),
                "structured_content": bool(
                    getattr(tool, "structuredContent", False)
                    or getattr(tool, "structured_content", False)
                    or getattr(tool, "outputSchema", None)
                    or getattr(tool, "output_schema", None)
                ),
            })
        return normalize_mcp_tool_metadata(raw_tools)

    @classmethod
    async def call_tool_from_config(
        cls,
        config: Dict[str, Any],
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Connect to an MCP server, invoke one tool, and normalize the result."""
        return await cls._run_with_retries(
            config,
            "tool_call",
            lambda: cls._call_tool_once(config, tool_name, arguments),
        )

    @classmethod
    async def _call_tool_once(
        cls,
        config: Dict[str, Any],
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Perform one MCP tool call attempt."""
        connector = cls.create_connector(config)
        try:
            debug_print(f"[MCP_PLUGIN_FACTORY] Connecting to MCP server for tool call tool_name={tool_name}.")
            await connector.connect()
            raw_result = await connector.call_tool(tool_name, **(arguments or {}))
            additional_fields = normalize_mcp_additional_fields((config or {}).get("additionalFields", {}))
            result = cls._serialize_tool_result(
                tool_name,
                raw_result,
                additional_fields.get("tool_result_policy"),
            )
            debug_print(
                f"[MCP_PLUGIN_FACTORY] MCP tool call succeeded tool_name={tool_name} "
                f"success={result.get('success') if isinstance(result, dict) else '<unknown>'}."
            )
            return result
        finally:
            debug_print(f"[MCP_PLUGIN_FACTORY] Closing MCP tool connector tool_name={tool_name}.")
            await connector.close()

    @classmethod
    async def _run_with_retries(cls, config: Dict[str, Any], operation: str, operation_factory):
        """Run an MCP operation with bounded retries and classified failures."""
        additional_fields = normalize_mcp_additional_fields((config or {}).get("additionalFields", {}))
        retry_count = int(additional_fields.get("retry_count") or 0)
        retry_backoff_seconds = int(additional_fields.get("retry_backoff_seconds") or 1)

        attempt = 0
        while True:
            try:
                return await operation_factory()
            except McpRuntimeError:
                raise
            except Exception as exc:
                error_info = classify_mcp_exception(exc, operation)
                if isinstance(exc, ValueError) and error_info["category"] == "unknown":
                    error_info.update({
                        "category": "validation",
                        "message": error_info["detail"] or "MCP configuration is invalid.",
                        "retryable": False,
                    })

                if error_info["retryable"] and attempt < retry_count:
                    delay = retry_backoff_seconds * (2 ** attempt)
                    log_event(
                        "[MCP_OUTBOUND] Operation retry scheduled",
                        extra={
                            **cls._build_operation_log_context(config, operation, attempt=attempt + 1),
                            "delay_seconds": delay,
                            "category": error_info["category"],
                            "retryable": error_info["retryable"],
                        },
                        level=logging.WARNING,
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue

                log_event(
                    "[MCP_OUTBOUND] Operation failed",
                    extra={
                        **cls._build_operation_log_context(config, operation, attempt=attempt + 1),
                        "category": error_info["category"],
                        "retryable": error_info["retryable"],
                    },
                    level=logging.WARNING,
                )
                raise McpRuntimeError(
                    error_info["message"],
                    category=error_info["category"],
                    operation=operation,
                    detail=error_info["detail"],
                    retryable=error_info["retryable"],
                ) from exc

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

        inferred_scope_type, inferred_scope_id = infer_mcp_destination_scope(manifest)
        mcp_operation_id = str(manifest.get("mcp_operation_id") or "").strip()
        assert_mcp_destination_allowed(
            manifest,
            scope_type=inferred_scope_type,
            scope_id=inferred_scope_id,
            operation="mcp_runtime_connector",
            user_id=manifest.get("runtime_user_id") or manifest.get("user_id") or "",
            mcp_operation_id=mcp_operation_id,
        )
        assert_mcp_preconfiguration_manifest_allowed(
            manifest,
            scope_type=inferred_scope_type,
            scope_id=inferred_scope_id,
            operation="mcp_runtime_connector",
            user_id=manifest.get("runtime_user_id") or manifest.get("user_id") or "",
        )

        if transport == "stdio":
            command = str(additional_fields.get("command") or "").strip()
            if not command:
                raise ValueError("MCP stdio transport requires a command.")
            log_event(
                "[MCP_OUTBOUND] Creating MCP stdio connector",
                extra={
                    **cls._build_operation_log_context(manifest, "create_connector"),
                    "command_present": bool(command),
                    "args_count": len(list(additional_fields.get("args") or [])),
                },
                level=logging.INFO,
                debug_only=True,
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
        endpoint_errors = validate_mcp_endpoint_for_transport(endpoint, transport)
        if endpoint_errors:
            raise ValueError("; ".join(endpoint_errors))

        headers = cls._build_headers(manifest)
        if transport == "websocket" and headers:
            raise ValueError(
                "MCP websocket transport does not support custom or authentication headers. "
                "Use streamable_http or sse for header-based authentication."
            )

        timeout = float(additional_fields.get("connect_timeout") or 10)
        sse_read_timeout = float(additional_fields.get("sse_read_timeout") or 300)
        log_event(
            "[MCP_OUTBOUND] Creating MCP remote connector",
            extra={
                **cls._build_operation_log_context(manifest, "create_connector"),
                "connect_timeout": timeout,
                "sse_read_timeout": sse_read_timeout,
                "request_timeout": request_timeout,
                "headers_present": bool(headers),
            },
            level=logging.INFO,
            debug_only=True,
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
        headers = dict(additional_fields.get(MCP_CUSTOM_HEADERS_FIELD) or {})
        header_errors = get_mcp_custom_header_validation_errors(headers)
        if header_errors:
            raise ValueError("; ".join(header_errors))

        auth_headers = {}
        if auth_method == "bearer" and secret_value:
            auth_headers["Authorization"] = f"Bearer {secret_value}"
        if auth_method == "api_key" and secret_value:
            header_name = str(additional_fields.get("api_key_header_name") or "X-API-Key").strip() or "X-API-Key"
            if not is_valid_mcp_header_name(header_name):
                raise ValueError("MCP api_key auth requires a valid api_key_header_name")
            auth_headers[header_name] = secret_value
        if auth_method == "basic" and identity_value and secret_value:
            credential_bytes = f"{identity_value}:{secret_value}".encode("utf-8")
            encoded_credentials = base64.b64encode(credential_bytes).decode("ascii")
            auth_headers["Authorization"] = f"Basic {encoded_credentials}"

        identity_auth_type = str(additional_fields.get("identity_auth_type") or "").strip().lower()
        if identity_auth_type == "bearer_token" and secret_value:
            auth_headers["Authorization"] = f"Bearer {secret_value}"
        if identity_auth_type == "api_key" and secret_value:
            header_name = str(additional_fields.get("api_key_header_name") or "X-API-Key").strip() or "X-API-Key"
            if not is_valid_mcp_header_name(header_name):
                raise ValueError("MCP api_key identity requires a valid api_key_header_name")
            auth_headers[header_name] = secret_value
        if identity_auth_type == "username_password" and identity_value and secret_value:
            credential_bytes = f"{identity_value}:{secret_value}".encode("utf-8")
            encoded_credentials = base64.b64encode(credential_bytes).decode("ascii")
            auth_headers["Authorization"] = f"Basic {encoded_credentials}"

        headers.update(auth_headers)
        return headers

    @staticmethod
    def _coerce_schema(schema_value: Any) -> Dict[str, Any]:
        if isinstance(schema_value, dict):
            return schema_value
        if hasattr(schema_value, "model_dump"):
            return schema_value.model_dump(mode="json", exclude_none=True)
        return {}

    @staticmethod
    def _coerce_object(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json", exclude_none=True)
        return {}

    @classmethod
    def _serialize_tool_result(cls, tool_name: str, raw_result: Any, result_policy: str) -> Dict[str, Any]:
        if isinstance(raw_result, list):
            content = [cls._serialize_content_item(item, result_policy) for item in raw_result]
        else:
            content = cls._serialize_content_item(raw_result, result_policy)
        return {
            "success": True,
            "tool_name": tool_name,
            "content": content,
        }

    @classmethod
    def _serialize_content_item(cls, item: Any, result_policy: str) -> Any:
        if item is None or isinstance(item, (bool, int, float)):
            return item
        if isinstance(item, str):
            return cls._truncate_text(item, result_policy)
        if isinstance(item, list):
            return [cls._serialize_content_item(child, result_policy) for child in item]
        if isinstance(item, dict):
            return {str(key): cls._serialize_content_item(value, result_policy) for key, value in item.items()}
        if hasattr(item, "model_dump"):
            try:
                return cls._serialize_content_item(item.model_dump(mode="json", exclude_none=True), result_policy)
            except Exception:
                pass

        text_value = getattr(item, "text", None)
        if text_value is not None:
            return {
                "type": item.__class__.__name__,
                "text": cls._truncate_text(str(text_value), result_policy),
            }
        return cls._truncate_text(str(item), result_policy)

    @staticmethod
    def _truncate_text(value: str, result_policy: str) -> str:
        return apply_mcp_result_text_policy(value, result_policy)
