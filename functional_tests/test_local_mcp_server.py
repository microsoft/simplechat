# test_local_mcp_server.py
#!/usr/bin/env python3
"""
Functional test for the SimpleChat local MCP development server.
Version: 0.250.100
Implemented in: 0.250.059

This test ensures that the reusable local MCP server supports SimpleChat MCP
discovery, custom header validation, and auth-header precedence.
"""

import asyncio
import json
import socket
import subprocess
import sys
import time
import types
from pathlib import Path

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
LOCAL_MCP_SERVER = REPO_ROOT / "application" / "development" / "local_mcp" / "server.py"
sys.path.insert(0, str(APP_DIR))


def _noop(*_args, **_kwargs):
    return None


class _NoopLogger:
    def __getattr__(self, _name):
        return _noop


_NOOP_LOGGER = _NoopLogger()


def _get_noop_logger():
    return _NOOP_LOGGER


sys.modules.setdefault(
    "functions_appinsights",
    types.SimpleNamespace(
        log_event=_noop,
        get_appinsights_logger=_get_noop_logger,
    ),
)
sys.modules.setdefault(
    "functions_authentication",
    types.SimpleNamespace(get_current_user_id=lambda: "functional-test-user"),
)
sys.modules.setdefault(
    "functions_debug",
    types.SimpleNamespace(debug_print=lambda *args, **kwargs: None),
)

from functions_mcp_operations import MCP_PLUGIN_TYPE  # noqa: E402
from semantic_kernel_plugins.mcp_plugin_factory import McpPluginFactory  # noqa: E402


def find_free_port():
    """Find an available local TCP port for the server subprocess."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_socket:
        probe_socket.bind(("127.0.0.1", 0))
        return probe_socket.getsockname()[1]


def wait_for_server(port, process):
    """Wait until the local MCP server health endpoint is available."""
    health_url = f"http://127.0.0.1:{port}/healthz"
    deadline = time.time() + 20
    last_error = None

    while time.time() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=5)
            raise RuntimeError(
                f"Local MCP server exited early with code {process.returncode}.\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )

        try:
            response = requests.get(health_url, timeout=1)
            if response.status_code == 200 and response.json().get("status") == "ok":
                return
        except requests.RequestException as ex:
            last_error = ex

        time.sleep(0.25)

    raise TimeoutError(f"Local MCP server did not become healthy: {last_error}")


def start_local_mcp_server(port, extra_args=None):
    """Start the local MCP server subprocess."""
    command = [
        sys.executable,
        str(LOCAL_MCP_SERVER),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    command.extend(extra_args or [])

    process = subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    wait_for_server(port, process)
    return process


def stop_local_mcp_server(process):
    """Stop the local MCP server subprocess."""
    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def extract_mcp_content(result):
    """Normalize SimpleChat MCP result content into a Python object."""
    content = result.get("content")
    if isinstance(content, list) and content:
        first_item = content[0]
        if isinstance(first_item, dict) and "text" in first_item:
            return json.loads(first_item["text"])
        if isinstance(first_item, str):
            return json.loads(first_item)
        return first_item

    if isinstance(content, dict) and "text" in content:
        return json.loads(content["text"])
    if isinstance(content, str):
        return json.loads(content)
    return content


def build_manifest(port):
    """Build a SimpleChat MCP action manifest for the local server."""
    return {
        "name": "local_mcp_test",
        "displayName": "Local MCP Test",
        "type": MCP_PLUGIN_TYPE,
        "description": "Local MCP validation server.",
        "endpoint": f"http://127.0.0.1:{port}/mcp",
        "auth": {
            "type": "key",
            "key": "real-auth-token",
        },
        "metadata": {},
        "additionalFields": {
            "server_profile": "generic",
            "transport": "streamable_http",
            "auth_method": "bearer",
            "custom_headers": {
                "Authorization": "Bearer custom-header-token",
                "X-SimpleChat-Test": "phase1",
                "X-Splunk-Host": "local-search-head",
            },
            "request_timeout": 10,
            "connect_timeout": 5,
            "sse_read_timeout": 30,
            "retry_count": 0,
            "retry_backoff_seconds": 1,
        },
    }


def test_local_mcp_server_workflow():
    """Validate discovery, custom headers, and auth precedence."""
    print("Testing SimpleChat local MCP server workflow...")
    port = find_free_port()
    process = start_local_mcp_server(port)

    try:
        manifest = build_manifest(port)
        tools = asyncio.run(McpPluginFactory.discover_tools_from_config(manifest))
        tool_names = {tool.get("original_name") for tool in tools}
        assert "ping" in tool_names
        assert "require_headers" in tool_names
        assert "require_auth" in tool_names
        assert "mock_search" in tool_names

        header_result = asyncio.run(
            McpPluginFactory.call_tool_from_config(
                manifest,
                "require_headers",
                {
                    "required_headers": ["Authorization", "X-SimpleChat-Test", "X-Splunk-Host"],
                    "expected_headers": {
                        "X-SimpleChat-Test": "phase1",
                        "X-Splunk-Host": "local-search-head",
                    },
                },
            )
        )
        header_content = extract_mcp_content(header_result)
        assert header_content["success"] is True
        assert header_content["missing_headers"] == []
        assert header_content["mismatched_headers"] == {}

        auth_result = asyncio.run(
            McpPluginFactory.call_tool_from_config(
                manifest,
                "require_auth",
                {
                    "auth_type": "bearer",
                    "expected_token": "real-auth-token",
                },
            )
        )
        auth_content = extract_mcp_content(auth_result)
        assert auth_content["success"] is True
        assert auth_content["scheme"] == "Bearer"
        assert auth_content["matched"] is True

        inspect_result = asyncio.run(
            McpPluginFactory.call_tool_from_config(
                manifest,
                "inspect_headers",
                {
                    "header_names": ["Authorization", "X-SimpleChat-Test"],
                    "include_sensitive": False,
                },
            )
        )
        inspect_content = extract_mcp_content(inspect_result)
        assert inspect_content["success"] is True
        assert inspect_content["headers"]["Authorization"]["value"] == "***REDACTED***"
        assert inspect_content["headers"]["X-SimpleChat-Test"]["value"] == "phase1"

        print("SimpleChat local MCP server workflow test passed.")
    finally:
        stop_local_mcp_server(process)


def test_local_mcp_ingress_header_gate():
    """Validate the optional local ingress header gate for discovery testing."""
    print("Testing SimpleChat local MCP ingress header gate...")
    port = find_free_port()
    process = start_local_mcp_server(
        port,
        ["--require-header-value", "X-Required-Gate=open-sesame"],
    )

    try:
        manifest = build_manifest(port)
        manifest["auth"] = {"type": "NoAuth"}
        manifest["additionalFields"]["auth_method"] = "none"
        manifest["additionalFields"]["custom_headers"] = {
            "X-Required-Gate": "open-sesame",
        }

        tools = asyncio.run(McpPluginFactory.discover_tools_from_config(manifest))
        tool_names = {tool.get("original_name") for tool in tools}
        assert "server_info" in tool_names

        blocked_response = requests.post(
            f"http://127.0.0.1:{port}/mcp",
            json={},
            timeout=5,
        )
        assert blocked_response.status_code == 401
        assert "header gate rejected" in blocked_response.text.lower()

        print("SimpleChat local MCP ingress header gate test passed.")
    finally:
        stop_local_mcp_server(process)


if __name__ == "__main__":
    try:
        test_local_mcp_server_workflow()
        test_local_mcp_ingress_header_gate()
        success = True
    except Exception as ex:
        print(f"SimpleChat local MCP server workflow test failed: {ex}")
        import traceback

        traceback.print_exc()
        success = False
    sys.exit(0 if success else 1)
