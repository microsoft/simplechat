# test_mcp_outbound_logging.py
#!/usr/bin/env python3
"""
Functional test for outbound MCP structured logging.
Version: 0.250.098
Implemented in: 0.250.095

This test ensures outbound MCP discovery telemetry uses correlation IDs,
safe destination metadata, and non-secret-bearing log context.
"""

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

from functions_mcp_destinations import build_mcp_destination_log_context  # noqa: E402


def read_source(relative_path):
    """Read a repository source file."""
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def test_destination_log_context_redacts_endpoint_query_values():
    """Validate destination logging avoids raw endpoint query strings."""
    manifest = {
        "name": "test_mcp",
        "type": "mcp",
        "endpoint": "https://example.com/mcp?api_key=super-secret&tenant=contoso",
        "auth": {"type": "key", "key": "another-secret"},
        "additionalFields": {
            "transport": "streamable_http",
            "auth_method": "api_key",
            "server_profile": "generic",
            "preconfiguration_id": "github",
        },
    }

    context = build_mcp_destination_log_context(manifest)
    context_text = repr(context)

    assert context["host"] == "example.com"
    assert context["path"] == "/mcp"
    assert context["has_query"] is True
    assert len(context["endpoint_hash"]) == 16
    assert "super-secret" not in context_text
    assert "another-secret" not in context_text
    assert "api_key=super-secret" not in context_text
    assert "tenant=contoso" not in context_text


def test_discovery_route_emits_correlated_lifecycle_events():
    """Validate the discovery route has start/completion/failure telemetry."""
    source = read_source(Path("application") / "single_app" / "route_backend_plugins.py")

    assert "mcp_operation_id = str(uuid.uuid4())" in source
    assert "[MCP Discovery] Started" in source
    assert "[MCP Discovery] Completed" in source
    assert "[MCP Discovery] Failed" in source
    assert "_build_mcp_discovery_log_context" in source
    assert "'mcp_operation_id': mcp_operation_id" in source
    assert "duration_ms" in source
    assert "failure_stage" in source


def test_factory_logs_retries_without_raw_endpoint_debug_messages():
    """Validate factory telemetry includes retries and avoids raw endpoint debug text."""
    source = read_source(
        Path("application") / "single_app" / "semantic_kernel_plugins" / "mcp_plugin_factory.py"
    )

    assert "[MCPOutbound] Operation retry scheduled" in source
    assert "[MCPOutbound] Operation failed" in source
    assert "build_mcp_destination_log_context" in source
    assert "endpoint={endpoint}" not in source


def main():
    """Run tests as a standalone functional test script."""
    tests = [
        test_destination_log_context_redacts_endpoint_query_values,
        test_discovery_route_emits_correlated_lifecycle_events,
        test_factory_logs_retries_without_raw_endpoint_debug_messages,
    ]
    for test in tests:
        try:
            test()
        except Exception as ex:
            print(f"{test.__name__} failed: {ex}")
            raise
    print("MCP outbound logging tests passed.")


if __name__ == "__main__":
    main()
