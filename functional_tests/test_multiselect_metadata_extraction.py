#!/usr/bin/env python3
# test_multiselect_metadata_extraction.py
"""
Functional test for multi-select metadata extraction.
Version: 0.250.106
Implemented in: 0.250.106

This test ensures personal, group, and public workspace multi-select actions
can queue metadata extraction and that the shared extraction path updates
document titles.
"""

import ast
import re
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SINGLE_APP_DIR = ROOT_DIR / "application" / "single_app"
CONFIG_FILE = SINGLE_APP_DIR / "config.py"
FUNCTIONS_DOCUMENTS_FILE = SINGLE_APP_DIR / "functions_documents.py"
PERSONAL_ROUTE_FILE = SINGLE_APP_DIR / "route_backend_documents.py"
GROUP_ROUTE_FILE = SINGLE_APP_DIR / "route_backend_group_documents.py"
PUBLIC_ROUTE_FILE = SINGLE_APP_DIR / "route_backend_public_documents.py"
WORKSPACE_TEMPLATE_FILE = SINGLE_APP_DIR / "templates" / "workspace.html"
GROUP_TEMPLATE_FILE = SINGLE_APP_DIR / "templates" / "group_workspaces.html"
PUBLIC_TEMPLATE_FILE = SINGLE_APP_DIR / "templates" / "public_workspaces.html"
WORKSPACE_JS_FILE = SINGLE_APP_DIR / "static" / "js" / "workspace" / "workspace-documents.js"
PUBLIC_JS_FILE = SINGLE_APP_DIR / "static" / "js" / "public" / "public_workspace.js"
EXPECTED_VERSION = "0.250.106"


ROUTE_CASES = [
    {
        "name": "personal",
        "file": PERSONAL_ROUTE_FILE,
        "function": "api_extract_user_metadata_batch",
        "path": "/api/documents/extract_metadata",
        "enabled_setting": "enable_user_workspace",
        "scope_checks": [
            "get_document_metadata(document_id=document_id, user_id=user_id)",
            "document_item.get('user_id') != user_id",
            "invalidate_personal_search_cache(user_id)",
        ],
    },
    {
        "name": "group",
        "file": GROUP_ROUTE_FILE,
        "function": "api_extract_group_metadata_batch",
        "path": "/api/group_documents/extract_metadata",
        "enabled_setting": "enable_group_workspaces",
        "scope_checks": [
            "_require_active_group_document_context",
            "check_group_status_allows_operation(group_doc, 'upload')",
            "group_id=active_group_id",
            "invalidate_group_search_cache(active_group_id)",
        ],
    },
    {
        "name": "public",
        "file": PUBLIC_ROUTE_FILE,
        "function": "api_extract_metadata_public_documents_batch",
        "path": "/api/public_documents/extract_metadata",
        "enabled_setting": "enable_public_workspaces",
        "scope_checks": [
            "_require_active_public_workspace_response",
            "check_public_workspace_status_allows_operation(ws_doc, 'upload')",
            "public_workspace_id=active_ws",
            "invalidate_public_workspace_search_cache(active_ws)",
        ],
    },
]


def read_file(path):
    """Read a UTF-8 text file from the repository."""
    return path.read_text(encoding="utf-8")


def parse_file(path):
    """Parse a Python file into an AST and return source text too."""
    source = read_file(path)
    return ast.parse(source, filename=str(path)), source


def dotted_name(node):
    """Return a dotted name for AST name, call, and attribute nodes."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return dotted_name(node.func)
    return ""


def route_path(route_decorator):
    """Return the literal route path from a Flask route decorator."""
    if route_decorator.args and isinstance(route_decorator.args[0], ast.Constant):
        return str(route_decorator.args[0].value)
    return ""


def get_function(module_ast, function_name):
    """Return a named function from a parsed module."""
    matches = [
        node for node in ast.walk(module_ast)
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    ]
    assert matches, f"Missing function: {function_name}"
    return matches[0]


def get_route_decorator(function_node):
    """Return the Flask route decorator from a route function."""
    route_decorators = [
        decorator for decorator in function_node.decorator_list
        if isinstance(decorator, ast.Call) and dotted_name(decorator.func).endswith(".route")
    ]
    assert route_decorators, f"Missing route decorator on {function_node.name}"
    return route_decorators[0]


def decorator_names(function_node):
    """Return decorator names from a function."""
    return tuple(
        dotted_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
        for decorator in function_node.decorator_list
    )


def test_batch_metadata_routes_are_registered_and_secured():
    """Verify all workspace batch routes are present and decorated."""
    print("Testing batch metadata route registration...")

    for route_case in ROUTE_CASES:
        module_ast, _source = parse_file(route_case["file"])
        function_node = get_function(module_ast, route_case["function"])
        route_decorator = get_route_decorator(function_node)
        names = decorator_names(function_node)

        assert route_path(route_decorator) == route_case["path"], (
            f"{route_case['name']} route path mismatch"
        )
        assert "swagger_route" in names, f"{route_case['name']} route missing swagger_route"
        assert "login_required" in names, f"{route_case['name']} route missing login_required"
        assert "user_required" in names, f"{route_case['name']} route missing user_required"
        assert "enabled_required" in names, f"{route_case['name']} route missing enabled_required"
        assert route_case["enabled_setting"] in ast.unparse(function_node), (
            f"{route_case['name']} route missing expected feature flag"
        )

    print("Batch metadata route registration passed")
    return True


def test_batch_metadata_routes_queue_authorized_background_jobs():
    """Verify routes parse selected IDs, validate scope, and queue extraction."""
    print("Testing batch metadata route queueing...")

    for route_case in ROUTE_CASES:
        module_ast, _source = parse_file(route_case["file"])
        function_source = ast.unparse(get_function(module_ast, route_case["function"]))

        assert "document_ids" in function_source, f"{route_case['name']} route must accept document_ids"
        assert "queued = []" in function_source, f"{route_case['name']} route must report queued docs"
        assert "errors = []" in function_source, f"{route_case['name']} route must report skipped docs"
        assert "process_metadata_extraction_background" in function_source, (
            f"{route_case['name']} route must use shared metadata extraction background job"
        )
        assert "submit_stored" in function_source, (
            f"{route_case['name']} route must track queued background jobs"
        )
        for expected_snippet in route_case["scope_checks"]:
            assert expected_snippet in function_source, (
                f"{route_case['name']} route missing scope check: {expected_snippet}"
            )

    print("Batch metadata route queueing passed")
    return True


def test_bulk_metadata_ui_wiring_exists_for_all_workspaces():
    """Verify multi-select bars expose metadata extraction and call batch routes."""
    print("Testing bulk metadata UI wiring...")

    workspace_template = read_file(WORKSPACE_TEMPLATE_FILE)
    group_template = read_file(GROUP_TEMPLATE_FILE)
    public_template = read_file(PUBLIC_TEMPLATE_FILE)
    workspace_js = read_file(WORKSPACE_JS_FILE)
    public_js = read_file(PUBLIC_JS_FILE)

    assert 'id="extract-selected-metadata-btn"' in workspace_template
    assert "window.extractSelectedMetadata" in workspace_js
    assert "/api/documents/extract_metadata" in workspace_js

    assert 'id="group-extract-selected-metadata-btn"' in group_template
    assert "extractGroupSelectedMetadata" in group_template
    assert "/api/group_documents/extract_metadata" in group_template

    assert 'id="public-extract-selected-metadata-btn"' in public_template
    assert "extractPublicSelectedMetadata" in public_js
    assert "/api/public_documents/extract_metadata" in public_js

    print("Bulk metadata UI wiring passed")
    return True


def test_metadata_extraction_updates_title():
    """Verify metadata extraction persists title updates to documents and chunks."""
    print("Testing metadata title update path...")

    module_ast, source = parse_file(FUNCTIONS_DOCUMENTS_FILE)
    background_function = ast.unparse(get_function(module_ast, "process_metadata_extraction_background"))
    final_metadata_function = ast.unparse(get_function(module_ast, "_run_final_metadata_extraction"))
    update_document_function = ast.unparse(get_function(module_ast, "update_document"))

    assert '"title": metadata.get(\'title\')' in source, (
        "Manual metadata extraction must pass title into update_document"
    )
    assert "document_metadata.items()" in final_metadata_function, (
        "Final metadata extraction should not exclude title from update fields"
    )
    assert "update_callback(**update_fields)" in final_metadata_function, (
        "Final metadata extraction must persist extracted fields"
    )
    assert "'title', 'authors', 'file_name', 'document_classification', 'tags'" in source, (
        "Document updates must mark title changes for chunk sync"
    )
    assert "chunk_updates['title'] = existing_document.get('title')" in update_document_function, (
        "Title updates must propagate to search chunks"
    )

    print("Metadata title update path passed")
    return True


def test_config_version_bumped_for_multiselect_metadata_extraction():
    """Verify config.py version was bumped for this change."""
    print("Testing config version bump...")

    config_source = read_file(CONFIG_FILE)
    version_match = re.search(r'VERSION = "([0-9.]+)"', config_source)
    assert version_match, "Could not find VERSION in config.py"
    assert version_match.group(1) == EXPECTED_VERSION, (
        f"Expected config.py version {EXPECTED_VERSION}"
    )

    print("Config version bump passed")
    return True


if __name__ == "__main__":
    tests = [
        test_batch_metadata_routes_are_registered_and_secured,
        test_batch_metadata_routes_queue_authorized_background_jobs,
        test_bulk_metadata_ui_wiring_exists_for_all_workspaces,
        test_metadata_extraction_updates_title,
        test_config_version_bumped_for_multiselect_metadata_extraction,
    ]

    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            results.append(test())
        except Exception as test_error:
            print(f"Test failed: {test_error}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
