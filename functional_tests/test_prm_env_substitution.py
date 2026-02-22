#!/usr/bin/env python3
"""
Quick validation test for PRM metadata environment variable substitution.
Version: 0.237.012
Implemented in: 0.237.012

This test ensures that _resolve_env_placeholders correctly substitutes
${VAR} and ${VAR:-default} placeholders in prm_metadata.json.
"""

import re
import os
import json
import sys

# Path to the actual prm_metadata.json
_PRM_METADATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "application", "external_apps", "mcp", "prm_metadata.json"
)


def _resolve_env_placeholders(raw_text):
    """Exact copy of the static method from _PrmAndAuthShim."""
    _PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")

    def _replacer(match):
        var_name = match.group(1)
        default_value = match.group(2)
        env_value = os.environ.get(var_name, "").strip()
        if env_value:
            return env_value
        if default_value is not None:
            return default_value
        raise ValueError(
            f"PRM metadata placeholder ${{{var_name}}} is unresolved: "
            f"set the {var_name} environment variable or provide a "
            f"default with ${{{var_name}:-default}}"
        )

    return _PLACEHOLDER_RE.sub(_replacer, raw_text)


def test_substitution_with_env_vars():
    """Test 1: placeholders are replaced when env vars are set."""
    print("Test 1: Substitution with env vars set...")
    os.environ["MCP_PRM_TENANT_ID"] = "test-tenant-1234"
    os.environ["MCP_PRM_RESOURCE_APP_ID"] = "test-app-5678"
    try:
        with open(_PRM_METADATA_PATH, "r") as f:
            raw = f.read()

        resolved = _resolve_env_placeholders(raw)
        data = json.loads(resolved)

        assert "test-tenant-1234" in data["authorization_servers"][0], \
            f"Tenant not substituted: {data['authorization_servers'][0]}"
        assert "test-app-5678" in data["scopes_supported"][0], \
            f"App ID not substituted: {data['scopes_supported'][0]}"

        expected_auth = "https://login.microsoftonline.com/test-tenant-1234/v2.0"
        assert data["authorization_servers"][0] == expected_auth, \
            f"Expected {expected_auth}, got {data['authorization_servers'][0]}"

        expected_scope = "api://test-app-5678/.default"
        assert data["scopes_supported"][0] == expected_scope, \
            f"Expected {expected_scope}, got {data['scopes_supported'][0]}"

        print("  PASSED")
        return True
    finally:
        os.environ.pop("MCP_PRM_TENANT_ID", None)
        os.environ.pop("MCP_PRM_RESOURCE_APP_ID", None)


def test_fallback_syntax():
    """Test 2: ${VAR:-fallback} uses fallback when var is unset."""
    print("Test 2: Fallback syntax...")
    test_json = '{"val": "${NONEXISTENT_VAR_XYZ:-my-fallback}"}'
    result = _resolve_env_placeholders(test_json)
    parsed = json.loads(result)
    assert parsed["val"] == "my-fallback", f"Expected 'my-fallback', got '{parsed['val']}'"
    print("  PASSED")
    return True


def test_missing_required_var_raises():
    """Test 3: ${VAR} with no default raises ValueError when var is unset."""
    print("Test 3: Missing required var raises error...")
    os.environ.pop("MCP_PRM_TENANT_ID", None)
    test_json = '{"val": "${MCP_PRM_TENANT_ID}"}'
    try:
        _resolve_env_placeholders(test_json)
        print("  FAILED: should have raised ValueError")
        return False
    except ValueError as e:
        assert "MCP_PRM_TENANT_ID" in str(e), f"Error message should mention var name: {e}"
        print(f"  PASSED (got expected error)")
        return True


def test_literal_strings_unchanged():
    """Test 4: strings with no placeholders pass through unmodified."""
    print("Test 4: Literal strings unchanged...")
    literal = '{"url": "https://login.microsoftonline.com/v2.0", "num": 42}'
    assert _resolve_env_placeholders(literal) == literal
    print("  PASSED")
    return True


def test_empty_default():
    """Test 5: ${VAR:-} uses empty string as default."""
    print("Test 5: Empty default...")
    os.environ.pop("SOME_EMPTY_VAR", None)
    test_json = '{"val": "${SOME_EMPTY_VAR:-}"}'
    result = _resolve_env_placeholders(test_json)
    parsed = json.loads(result)
    assert parsed["val"] == "", f"Expected empty string, got '{parsed['val']}'"
    print("  PASSED")
    return True


def test_multiple_placeholders():
    """Test 6: multiple placeholders in one string all get replaced."""
    print("Test 6: Multiple placeholders...")
    os.environ["VAR_A"] = "alpha"
    os.environ["VAR_B"] = "beta"
    try:
        test_json = '{"val": "${VAR_A}-${VAR_B}"}'
        result = _resolve_env_placeholders(test_json)
        parsed = json.loads(result)
        assert parsed["val"] == "alpha-beta", f"Expected 'alpha-beta', got '{parsed['val']}'"
        print("  PASSED")
        return True
    finally:
        os.environ.pop("VAR_A", None)
        os.environ.pop("VAR_B", None)


def test_result_is_valid_json():
    """Test 7: full prm_metadata.json produces valid JSON after substitution."""
    print("Test 7: Full file produces valid JSON...")
    os.environ["MCP_PRM_TENANT_ID"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    os.environ["MCP_PRM_RESOURCE_APP_ID"] = "11111111-2222-3333-4444-555555555555"
    try:
        with open(_PRM_METADATA_PATH, "r") as f:
            raw = f.read()
        resolved = _resolve_env_placeholders(raw)
        data = json.loads(resolved)
        assert isinstance(data, dict), "Result should be a dict"
        assert "resource" in data
        assert "authorization_servers" in data
        assert "scopes_supported" in data
        assert "bearer_methods_supported" in data
        print("  PASSED")
        return True
    finally:
        os.environ.pop("MCP_PRM_TENANT_ID", None)
        os.environ.pop("MCP_PRM_RESOURCE_APP_ID", None)


if __name__ == "__main__":
    tests = [
        test_substitution_with_env_vars,
        test_fallback_syntax,
        test_missing_required_var_raises,
        test_literal_strings_unchanged,
        test_empty_default,
        test_multiple_placeholders,
        test_result_is_valid_json,
    ]
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"  FAILED: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    passed = sum(r for r in results if r)
    total = len(results)
    print(f"\nResults: {passed}/{total} tests passed")
    sys.exit(0 if all(results) else 1)
