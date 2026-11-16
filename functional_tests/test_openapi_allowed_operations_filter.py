# test_openapi_allowed_operations_filter.py
#!/usr/bin/env python3
"""
Functional test for OpenAPI allowed operation filtering.
Version: 0.261.276
Implemented in: 0.261.276

This test ensures OpenAPI actions expose only the configured operation IDs while
preserving backward-compatible all-operation behavior when no allow-list exists.
"""

import os
import sys
import types


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

# Keep this focused unit-style functional test offline: the OpenAPI plugin logger normally
# imports the web authentication/bootstrap stack, which initializes Azure clients.
auth_module = types.ModuleType("functions_authentication")
auth_module.get_current_user_id = lambda: "openapi-test-user"
sys.modules["functions_authentication"] = auth_module

appinsights_module = types.ModuleType("functions_appinsights")
appinsights_module.log_event = lambda *args, **kwargs: None
appinsights_module.get_appinsights_logger = lambda: None
appinsights_module.debug_print = lambda *args, **kwargs: None
appinsights_module.is_debug_enabled = lambda: False
sys.modules["functions_appinsights"] = appinsights_module

from semantic_kernel_plugins.openapi_plugin_factory import OpenApiPluginFactory


INLINE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Allowed Operations Test API", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List pets",
                "responses": {"200": {"description": "OK"}},
            },
            "post": {
                "operationId": "createPet",
                "summary": "Create a pet",
                "responses": {"201": {"description": "Created"}},
            },
        },
        "/status": {
            "get": {
                "summary": "Get service status",
                "responses": {"200": {"description": "OK"}},
            },
        },
    },
}


def create_plugin(allowed_operations=None):
    """Create a plugin with the inline spec and optional allow-list."""
    additional_fields = {"openapi_spec_content": INLINE_SPEC}
    if allowed_operations is not None:
        additional_fields["allowed_operations"] = allowed_operations
    return OpenApiPluginFactory.create_from_config({
        "name": "allowed_operations_test",
        "base_url": "https://api.example.test",
        "additionalFields": additional_fields,
    })


def create_plugin_with_root_allow_list(allowed_operations):
    """Create a plugin where allowed_operations is stored at the manifest root."""
    return OpenApiPluginFactory.create_from_config({
        "name": "allowed_operations_test",
        "base_url": "https://api.example.test",
        "openapi_spec_content": INLINE_SPEC,
        "allowed_operations": allowed_operations,
    })


def test_allowed_operations_filter_registered_functions():
    """Only configured operation IDs and generated operation keys are registered."""
    plugin = create_plugin(["listPets", "get__status"])

    functions = set(plugin.get_functions())
    assert "listPets" in functions
    assert "get__status" in functions
    assert "createPet" not in functions
    assert "call_operation" in functions
    assert hasattr(plugin, "listPets")
    assert hasattr(plugin, "get__status")
    assert not hasattr(plugin, "createPet")
    assert plugin.get_operation_details("listPets") is not None
    assert plugin.get_operation_details("createPet") is None


def test_factory_passes_root_allowed_operations_manifest_field():
    """Root-level manifest allow-lists are passed through for legacy callers."""
    plugin = create_plugin_with_root_allow_list(["createPet"])
    functions = set(plugin.get_functions())
    assert "createPet" in functions
    assert "listPets" not in functions
    assert "get__status" not in functions


def test_disallowed_operation_rejected_before_http_call():
    """A disabled operation is rejected at call time without issuing a request."""
    plugin = create_plugin(["listPets"])

    try:
        plugin.call_operation(operation_id="createPet")
    except PermissionError as ex:
        assert "not enabled" in str(ex)
    else:
        raise AssertionError("Disabled OpenAPI operation was not rejected.")


def test_empty_or_missing_allow_list_keeps_backward_compatible_all_operations():
    """Missing or empty allowed_operations continues to expose every operation."""
    for allowed_operations in (None, []):
        plugin = create_plugin(allowed_operations)
        functions = set(plugin.get_functions())
        assert {"listPets", "createPet", "get__status"}.issubset(functions)


def test_malformed_allow_list_fails_closed():
    """A present non-list allow-list must not silently expose every operation."""
    try:
        create_plugin("listPets")
    except ValueError:
        pass
    else:
        raise AssertionError("Malformed allowed_operations exposed the plugin.")


if __name__ == "__main__":
    test_allowed_operations_filter_registered_functions()
    test_factory_passes_root_allowed_operations_manifest_field()
    test_disallowed_operation_rejected_before_http_call()
    test_empty_or_missing_allow_list_keeps_backward_compatible_all_operations()
    test_malformed_allow_list_fails_closed()
    print("OpenAPI allowed operation filtering tests passed.")
