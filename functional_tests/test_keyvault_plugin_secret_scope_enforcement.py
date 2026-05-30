# test_keyvault_plugin_secret_scope_enforcement.py
"""
Functional test for Key Vault plugin secret scope enforcement.
Version: 0.241.022
Implemented in: 0.241.011; 0.241.022

This test ensures plugin Key Vault references are validated against the
expected scope and source before they are preserved, resolved, or deleted.
It also verifies the runtime plugin loader and SQL test-connection flow do
not dereference cross-scope secret references.
"""

import ast
import logging
import os
import re
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYVAULT_FILE = os.path.join(ROOT_DIR, "application", "single_app", "functions_keyvault.py")
PLUGIN_ROUTE_FILE = os.path.join(ROOT_DIR, "application", "single_app", "route_backend_plugins.py")
SK_LOADER_FILE = os.path.join(ROOT_DIR, "application", "single_app", "semantic_kernel_loader.py")
CONFIG_FILE = os.path.join(ROOT_DIR, "application", "single_app", "config.py")
FIX_DOC_ROOT = os.path.join(ROOT_DIR, "docs", "explanation", "fixes")
FIX_DOC_NAME = "KEY_VAULT_PLUGIN_SECRET_SCOPE_ENFORCEMENT_FIX.md"


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8-sig") as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith("VERSION = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("VERSION assignment not found in config.py")


def parse_version(version_text):
    parts = version_text.split(".")
    if len(parts) != 3:
        raise AssertionError(f"Invalid version format: {version_text}")
    try:
        return tuple(int(part) for part in parts)
    except ValueError as exc:
        raise AssertionError(f"Version contains non-numeric segments: {version_text}") from exc


def find_fix_doc_paths(root_path, file_name):
    matching_paths = []
    for dirpath, _, filenames in os.walk(root_path):
        if file_name in filenames:
            matching_paths.append(os.path.join(dirpath, file_name))
    return sorted(matching_paths)


def load_functions(file_path, function_names, namespace=None):
    source = read_file_text(file_path)
    parsed = ast.parse(source, filename=file_path)
    selected_nodes = [
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    assert len(selected_nodes) == len(function_names), (
        f"Expected functions {sorted(function_names)} in {file_path}, "
        f"found {[node.name for node in selected_nodes]}"
    )
    module = ast.Module(body=selected_nodes, type_ignores=[])
    exec_namespace = dict(namespace or {})
    exec(compile(module, file_path, "exec"), exec_namespace)
    return exec_namespace, source


def extract_function_source(source_text, function_name):
    parsed = ast.parse(source_text)
    for node in ast.walk(parsed):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source_text, node)
    raise AssertionError(f"Function {function_name} not found")


def test_secret_reference_context_matching_rejects_cross_scope_values():
    """Verify full secret names must match the expected scope and source."""
    print("🔍 Testing Key Vault secret reference context matching...")

    namespace, _ = load_functions(
        KEYVAULT_FILE,
        {"clean_name_for_keyvault", "_normalize_allowed_sources", "parse_secret_name_dynamic", "secret_reference_matches_context"},
        {
            "re": re,
            "supported_scopes": ["global", "user", "group"],
            "supported_sources": ["action", "action-addset", "agent", "model-endpoint", "other"],
        },
    )

    matches_context = namespace["secret_reference_matches_context"]
    valid_reference = "user-123--action-addset--user--plugin-connection-string"

    assert matches_context(valid_reference, scope_value="user-123", scope="user", allowed_sources={"action-addset"})
    assert not matches_context(valid_reference, scope_value="user-456", scope="user", allowed_sources={"action-addset"})
    assert not matches_context(valid_reference, scope_value="user-123", scope="user", allowed_sources={"action"})
    assert not matches_context(valid_reference, scope_value="user-123", scope="group", allowed_sources={"action-addset"})

    print("✅ Key Vault secret reference context matching passed")


def test_store_plugin_secret_reference_rejects_cross_scope_secret_names():
    """Verify user-supplied cross-scope plugin references are rejected at save time."""
    print("🔍 Testing plugin save-time secret reference rejection...")

    namespace, _ = load_functions(
        KEYVAULT_FILE,
        {
            "clean_name_for_keyvault",
            "_normalize_allowed_sources",
            "parse_secret_name_dynamic",
            "secret_reference_matches_context",
            "_log_secret_reference_context_mismatch",
            "_get_nested_dict_value",
            "_set_nested_dict_value",
            "_get_existing_secret_reference",
            "validate_secret_name_dynamic",
            "_store_plugin_secret_reference",
        },
        {
            "log_event": lambda *args, **kwargs: None,
            "logging": logging,
            "re": re,
            "supported_scopes": ["global", "user", "group"],
            "supported_sources": ["action", "action-addset", "agent", "model-endpoint", "other"],
            "ui_trigger_word": "Stored_In_KeyVault",
            "build_full_secret_name": lambda *args, **kwargs: "unused",
            "store_secret_in_key_vault": lambda *args, **kwargs: "unused",
        },
    )

    store_reference = namespace["_store_plugin_secret_reference"]
    plugin_manifest = {
        "auth": {
            "type": "key",
            "key": "other-user--action--user--foreign-plugin",
        }
    }

    try:
        store_reference(
            plugin_manifest,
            existing_plugin=None,
            path=("auth", "key"),
            secret_name="local-plugin",
            scope_value="current-user",
            source="action",
            scope="user",
        )
    except ValueError as exc:
        assert "does not match the expected scope" in str(exc)
    else:
        raise AssertionError("Expected cross-scope plugin secret reference to be rejected")

    print("✅ Plugin save-time secret reference rejection passed")


def test_runtime_plugin_loader_blanks_secret_fields_on_scope_mismatch():
    """Verify the runtime loader refuses to resolve foreign plugin secret references."""
    print("🔍 Testing runtime plugin secret resolution hardening...")

    namespace, _ = load_functions(
        SK_LOADER_FILE,
        {"_get_plugin_secret_context", "_is_sql_sensitive_plugin_field", "resolve_key_vault_secrets_in_plugins"},
        {
            "SQL_PLUGIN_SENSITIVE_AUTH_FIELDS": {"client_secret"},
            "SQL_PLUGIN_SENSITIVE_ADDITIONAL_FIELDS": {"connection_string", "password"},
            "validate_secret_name_dynamic": lambda value: isinstance(value, str) and value.startswith("ref-"),
            "resolve_secret_reference_for_context": lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("scope mismatch")),
            "log_event": lambda *args, **kwargs: None,
            "logging": logging,
            "debug_print": lambda *args, **kwargs: None,
        },
    )

    resolve_manifest = namespace["resolve_key_vault_secrets_in_plugins"]
    plugin_manifest = {
        "id": "plugin-1",
        "name": "sql-plugin",
        "user_id": "current-user",
        "type": "sql_query",
        "auth": {"type": "key", "key": "ref-auth"},
        "additionalFields": {"connection_string": "ref-connection"},
    }

    resolved_manifest = resolve_manifest(plugin_manifest, {"key_vault_name": "kv-demo"})
    assert resolved_manifest["auth"]["key"] == ""
    assert resolved_manifest["additionalFields"]["connection_string"] == ""

    print("✅ Runtime plugin secret resolution hardening passed")


def test_sql_secret_resolution_helper_binds_expected_scope_and_source():
    """Verify SQL test-connection resolution delegates to the scope-aware Key Vault helper."""
    print("🔍 Testing SQL test-connection secret resolution helper...")

    captured = {}

    def fake_resolver(value, scope_value=None, scope=None, allowed_sources=None, context_label=None):
        captured.update({
            "value": value,
            "scope_value": scope_value,
            "scope": scope,
            "allowed_sources": allowed_sources,
            "context_label": context_label,
        })
        return "resolved-secret"

    namespace, _ = load_functions(
        PLUGIN_ROUTE_FILE,
        {"_resolve_secret_value_for_sql_test"},
        {
            "validate_secret_name_dynamic": lambda value: True,
            "resolve_secret_reference_for_context": fake_resolver,
        },
    )

    resolve_sql_secret = namespace["_resolve_secret_value_for_sql_test"]
    resolved_value = resolve_sql_secret(
        "user-123--action-addset--user--plugin-connection-string",
        "connection_string",
        scope_value="user-123",
        scope="user",
    )

    assert resolved_value == "resolved-secret"
    assert captured["scope_value"] == "user-123"
    assert captured["scope"] == "user"
    assert captured["allowed_sources"] == {"action-addset"}
    assert captured["context_label"] == "SQL field 'connection_string'"

    print("✅ SQL test-connection secret resolution helper passed")


def test_delete_and_loader_paths_include_scope_checks():
    """Verify the delete and runtime loader paths include explicit scope validation hooks."""
    print("🔍 Testing delete and loader source enforcement markers...")

    keyvault_source = read_file_text(KEYVAULT_FILE)
    loader_source = read_file_text(SK_LOADER_FILE)

    delete_source = extract_function_source(keyvault_source, "keyvault_plugin_delete_helper")
    assert delete_source.count("secret_reference_matches_context(") >= 2
    assert delete_source.count("continue") >= 2

    loader_source_segment = extract_function_source(loader_source, "resolve_key_vault_secrets_in_plugins")
    assert "resolve_secret_reference_for_context(" in loader_source_segment
    assert "resolved_auth[auth_field] = \"\"" in loader_source_segment
    assert "resolved_additional_fields[field_name] = \"\"" in loader_source_segment

    print("✅ Delete and loader source enforcement markers passed")


def test_fix_documentation_and_version_exist():
    """Verify the config version bump and fix documentation landed for this change."""
    print("🔍 Testing Key Vault scope enforcement documentation and version...")

    current_version = read_config_version()
    minimum_version = "0.241.022"
    assert parse_version(current_version) >= parse_version(minimum_version), (
        f"Expected config version >= {minimum_version}, found {current_version}"
    )
    matching_fix_docs = find_fix_doc_paths(FIX_DOC_ROOT, FIX_DOC_NAME)
    assert matching_fix_docs, (
        f"Expected fix documentation named {FIX_DOC_NAME} under {FIX_DOC_ROOT}"
    )

    print("✅ Key Vault scope enforcement documentation and version passed")


if __name__ == "__main__":
    tests = [
        test_secret_reference_context_matching_rejects_cross_scope_values,
        test_store_plugin_secret_reference_rejects_cross_scope_secret_names,
        test_runtime_plugin_loader_blanks_secret_fields_on_scope_mismatch,
        test_sql_secret_resolution_helper_binds_expected_scope_and_source,
        test_delete_and_loader_paths_include_scope_checks,
        test_fix_documentation_and_version_exist,
    ]

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        test()

    print(f"\n📊 Results: {len(tests)}/{len(tests)} tests passed")
    sys.exit(0)