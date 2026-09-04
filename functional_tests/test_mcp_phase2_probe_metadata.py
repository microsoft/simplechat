# test_mcp_phase2_probe_metadata.py
#!/usr/bin/env python3
"""
Functional test for MCP Phase 2 probe metadata and safeguards.
Version: 0.250.068
Implemented in: 0.250.068

This test ensures outbound MCP metadata normalization, discovery warnings,
argument schema validation, and large-result policies work without requiring
a live MCP server.
"""

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

from functions_mcp_operations import (  # noqa: E402
    MCP_MAX_TOOL_RESULT_TEXT_LENGTH,
    MCP_TOOL_RESULT_POLICY_ERROR_ON_LIMIT,
    McpRuntimeError,
    apply_mcp_result_text_policy,
    build_mcp_tool_metadata_warnings,
    normalize_mcp_additional_fields,
    normalize_mcp_tool_metadata,
    validate_mcp_tool_arguments,
)


def test_mcp_phase2_metadata_warnings_and_argument_validation():
    """Validate Phase 2 metadata preservation and opt-in schema validation."""
    tools = normalize_mcp_tool_metadata([
        {
            "original_name": "search-repositories",
            "description": "Search repositories.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "items": {"type": "array"},
                },
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "original_name": "search repositories",
            "description": "Duplicate normalized name.",
            "input_schema": {},
        },
    ])

    assert tools[0]["function_name"] == "search_repositories"
    assert tools[1]["function_name"] == "search_repositories_2"
    assert tools[0]["output_schema"]["type"] == "object"
    assert tools[0]["annotations"]["readOnlyHint"] is True
    assert tools[0]["structured_content"] is True

    warnings = build_mcp_tool_metadata_warnings(tools, {"load_prompts": True})
    assert any("normalized" in warning for warning in warnings)
    assert any("broad" in warning for warning in warnings)
    assert any("Prompt loading" in warning for warning in warnings)

    validation_errors = validate_mcp_tool_arguments(tools[0], {})
    assert validation_errors
    assert "query" in validation_errors[0]
    assert validate_mcp_tool_arguments(tools[0], {"query": "simplechat"}) == []


def test_mcp_phase2_result_policy_and_defaults():
    """Validate default normalization and error-on-limit result handling."""
    additional_fields = normalize_mcp_additional_fields({})
    assert additional_fields["validate_tool_arguments"] is False
    assert additional_fields["tool_result_policy"] == "truncate"

    long_text = "x" * (MCP_MAX_TOOL_RESULT_TEXT_LENGTH + 1)
    truncated = apply_mcp_result_text_policy(long_text, "truncate")
    assert truncated.endswith("[truncated]")

    try:
        apply_mcp_result_text_policy(
            long_text,
            MCP_TOOL_RESULT_POLICY_ERROR_ON_LIMIT,
        )
    except McpRuntimeError as ex:
        assert ex.category == "result_limit"
    else:
        raise AssertionError("Expected oversized MCP result to raise McpRuntimeError.")


def main():
    """Run tests as a standalone functional test script."""
    tests = [
        test_mcp_phase2_metadata_warnings_and_argument_validation,
        test_mcp_phase2_result_policy_and_defaults,
    ]
    for test in tests:
        try:
            test()
        except Exception as ex:
            print(f"{test.__name__} failed: {ex}")
            raise
    print("MCP Phase 2 probe metadata tests passed.")


if __name__ == "__main__":
    main()
