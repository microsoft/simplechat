# test_mcp_server_presets.py
#!/usr/bin/env python3
"""
Functional test for declarative MCP server presets.
Version: 0.250.062
Implemented in: 0.250.062

This test ensures MCP server presets are loaded from validated JSON definitions,
served through server-side helpers, and remain backward compatible with the
existing Splunk preset id.
"""

import json
import os
import sys
import tempfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "application" / "single_app"
PRESET_DIR = APP_DIR / "mcp_presets" / "definitions"
sys.path.insert(0, str(APP_DIR))

from functions_mcp_operations import normalize_mcp_server_profile  # noqa: E402
from functions_mcp_presets import (  # noqa: E402
    MCP_PRESET_PATHS_ENV,
    build_mcp_server_presets_response,
    clear_mcp_server_preset_cache,
    get_mcp_server_preset,
    load_mcp_server_presets,
)


def test_builtin_mcp_server_presets():
    """Validate bundled MCP server presets and backward-compatible ids."""
    clear_mcp_server_preset_cache()
    presets = load_mcp_server_presets()
    preset_ids = {preset["id"] for preset in presets}

    assert "generic" in preset_ids
    assert "splunk" in preset_ids
    assert normalize_mcp_server_profile("splunk") == "splunk"
    assert normalize_mcp_server_profile("splunk_enterprise") == "splunk"
    assert normalize_mcp_server_profile("../unsafe") == "generic"

    splunk = get_mcp_server_preset("splunk")
    assert splunk["displayName"] == "Splunk MCP Server"
    assert splunk["defaults"]["transport"] == "streamable_http"
    assert splunk["defaults"]["auth_method"] == "bearer"
    assert "custom_headers" not in splunk["defaults"]

    response = build_mcp_server_presets_response()
    assert response["defaultPreset"] == "generic"
    assert {preset["id"] for preset in response["presets"]} == preset_ids
    assert all("source" in preset for preset in response["presets"])

    for preset_file in PRESET_DIR.glob("*.json"):
        preset = json.loads(preset_file.read_text(encoding="utf-8"))
        assert preset["id"] == preset_file.stem
        assert "auth" not in preset["defaults"]
        assert "endpoint" not in preset["defaults"]


def test_custom_mcp_server_preset_path_loading():
    """Validate org-authored presets can be loaded from configured directories."""
    previous_paths = os.environ.get(MCP_PRESET_PATHS_ENV)
    with tempfile.TemporaryDirectory() as temp_dir:
        custom_preset = {
            "id": "contoso",
            "version": "1.0.0",
            "displayName": "Contoso MCP Server",
            "description": "Contoso-specific MCP compatibility defaults.",
            "provider": "Contoso",
            "enabled": True,
            "sortOrder": 15,
            "defaults": {
                "transport": "sse",
                "auth_method": "api_key",
                "api_key_header_name": "X-Contoso-Key",
                "load_tools": True,
                "load_prompts": False,
                "request_timeout": 45,
                "connect_timeout": 15,
                "sse_read_timeout": 120,
                "retry_count": 1,
                "retry_backoff_seconds": 2,
                "allowed_tool_names": [],
            },
            "ui": {
                "helpText": "Use this preset for Contoso MCP endpoints.",
                "endpointPlaceholder": "https://mcp.contoso.example/mcp",
                "websocketEndpointPlaceholder": "wss://mcp.contoso.example/mcp",
            },
            "constraints": {
                "allowedTransports": ["sse"],
                "allowedAuthMethods": ["api_key"],
                "customHeadersAllowed": True,
                "stdioAllowed": False,
            },
            "suggestedHeaders": [],
            "warnings": [],
        }
        Path(temp_dir, "contoso.json").write_text(json.dumps(custom_preset, indent=4), encoding="utf-8")

        os.environ[MCP_PRESET_PATHS_ENV] = temp_dir
        clear_mcp_server_preset_cache()
        try:
            presets = load_mcp_server_presets()
            preset_ids = {preset["id"] for preset in presets}
            assert "contoso" in preset_ids
            assert get_mcp_server_preset("contoso")["defaults"]["auth_method"] == "api_key"
            assert normalize_mcp_server_profile("contoso") == "contoso"
        finally:
            if previous_paths is None:
                os.environ.pop(MCP_PRESET_PATHS_ENV, None)
            else:
                os.environ[MCP_PRESET_PATHS_ENV] = previous_paths
            clear_mcp_server_preset_cache()


if __name__ == "__main__":
    try:
        test_builtin_mcp_server_presets()
        test_custom_mcp_server_preset_path_loading()
        success = True
    except Exception as ex:
        print(f"MCP server presets test failed: {ex}")
        import traceback

        traceback.print_exc()
        success = False
    sys.exit(0 if success else 1)
