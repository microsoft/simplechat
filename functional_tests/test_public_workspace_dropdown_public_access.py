# test_public_workspace_dropdown_public_access.py
"""
Functional test for public workspace dropdown access and search.
Version: 0.241.152
Implemented in: 0.241.151

This test ensures authenticated users can discover every public workspace in
the selector, ordinary viewers receive an implicit User role, privileged
actions remain role-gated, and the public workspace dropdown search is wired.
Updated in 0.241.152 to validate that the search field is visible for any
non-empty public workspace list.
"""

import ast
import os
import sys
from typing import Iterable


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(ROOT_DIR, "application", "single_app", "config.py")
PUBLIC_WORKSPACES_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "functions_public_workspaces.py",
)
PUBLIC_WORKSPACES_ROUTE_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "route_backend_public_workspaces.py",
)
PUBLIC_PROMPTS_ROUTE_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "route_backend_public_prompts.py",
)
PUBLIC_WORKSPACE_SCRIPT = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "static",
    "js",
    "public",
    "public_workspace.js",
)
PUBLIC_WORKSPACES_TEMPLATE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "templates",
    "public_workspaces.html",
)


def read_file_text(file_path):
    """Read a repository file as text."""
    with open(file_path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def read_config_version():
    """Read VERSION from config.py without importing application dependencies."""
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith("VERSION = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("VERSION assignment not found in config.py")


def load_functions(file_path, function_names, namespace=None):
    """Load selected functions from a source file without importing the full app."""
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
    """Return the source for a single function from a Python module."""
    parsed = ast.parse(source_text)
    for node in ast.walk(parsed):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source_text, node)
    raise AssertionError(f"Function {function_name} not found")


class FakePublicWorkspaceContainer:
    """Small Cosmos container stand-in that records public workspace queries."""

    def __init__(self, workspaces):
        self.workspaces = workspaces
        self.calls = []

    def query_items(self, query, parameters=None, enable_cross_partition_query=False):
        self.calls.append({
            "query": query,
            "parameters": parameters or [],
            "enable_cross_partition_query": enable_cross_partition_query,
        })
        search_value = next(
            (parameter["value"] for parameter in (parameters or []) if parameter["name"] == "@search"),
            "",
        )
        if search_value:
            return [
                workspace for workspace in self.workspaces
                if search_value in workspace.get("name", "").lower()
                or search_value in workspace.get("description", "").lower()
            ]
        return list(self.workspaces)


class FakeSettingsModule:
    """Settings stand-in for active public workspace validation."""

    @staticmethod
    def get_user_settings(_user_id):
        return {"settings": {"activePublicWorkspaceOid": "workspace-public"}}


def test_public_workspace_helpers_support_all_public_users():
    """Verify public helper behavior for all-public discovery and implicit User role."""
    print("[check] Testing all-public workspace helper behavior...")

    workspaces = [
        {
            "id": "workspace-owned",
            "name": "Owner Workspace",
            "description": "Managed by the caller.",
            "owner": {"userId": "owner-user"},
            "admins": [],
            "documentManagers": [],
        },
        {
            "id": "workspace-public",
            "name": "Research Library",
            "description": "Open public research workspace.",
            "owner": {"userId": "owner-user"},
            "admins": [],
            "documentManagers": [],
        },
    ]
    fake_container = FakePublicWorkspaceContainer(workspaces)
    namespace, _ = load_functions(
        PUBLIC_WORKSPACES_FILE,
        {
            "get_all_public_workspaces",
            "search_all_public_workspaces",
            "get_user_role_in_public_workspace",
            "require_active_public_workspace",
        },
        {
            "cosmos_public_workspaces_container": fake_container,
            "functions_settings": FakeSettingsModule,
            "find_public_workspace_by_id": lambda workspace_id: next(
                (workspace for workspace in workspaces if workspace["id"] == workspace_id),
                None,
            ),
            "Iterable": Iterable,
        },
    )

    all_workspaces = namespace["get_all_public_workspaces"]()
    assert [workspace["id"] for workspace in all_workspaces] == ["workspace-owned", "workspace-public"]
    assert "@uid" not in fake_container.calls[-1]["query"], "All-public query should not filter by user id."
    assert fake_container.calls[-1]["enable_cross_partition_query"] is True

    search_results = namespace["search_all_public_workspaces"]("research")
    assert [workspace["id"] for workspace in search_results] == ["workspace-public"]
    assert "@uid" not in fake_container.calls[-1]["query"], "All-public search should not filter by role."
    assert fake_container.calls[-1]["parameters"] == [{"name": "@search", "value": "research"}]

    get_role = namespace["get_user_role_in_public_workspace"]
    assert get_role(workspaces[0], "owner-user") == "Owner"
    assert get_role(workspaces[1], "ordinary-user") == "User"
    assert get_role(None, "ordinary-user") is None

    require_active = namespace["require_active_public_workspace"]
    active_id, active_workspace, role = require_active(
        "ordinary-user",
        allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
    )
    assert active_id == "workspace-public"
    assert active_workspace["name"] == "Research Library"
    assert role == "User"

    try:
        require_active("ordinary-user")
    except PermissionError:
        pass
    else:
        raise AssertionError("Default active public workspace validation should still deny ordinary User writes.")

    print("[pass] All-public workspace helper behavior passed")


def test_public_workspace_routes_and_dropdown_search_are_wired():
    """Verify source wiring for all-public API listing and dropdown filtering."""
    print("[check] Testing public workspace route and dropdown search wiring...")

    route_source = read_file_text(PUBLIC_WORKSPACES_ROUTE_FILE)
    list_source = extract_function_source(route_source, "api_list_public_workspaces")
    assert "search_all_public_workspaces(search_term)" in list_source
    assert "get_all_public_workspaces()" in list_source
    assert "search_public_workspaces(search_term, user_id)" not in list_source
    assert "get_user_public_workspaces(user_id)" not in list_source
    assert '"userRole": role' in list_source

    prompt_route_source = read_file_text(PUBLIC_PROMPTS_ROUTE_FILE)
    helper_source = extract_function_source(prompt_route_source, "_get_active_public_workspace_or_error")
    assert '("Owner", "Admin", "DocumentManager", "User")' in helper_source
    create_source = extract_function_source(prompt_route_source, "api_create_public_prompt")
    update_source = extract_function_source(prompt_route_source, "api_update_public_prompt")
    delete_source = extract_function_source(prompt_route_source, "api_delete_public_prompt")
    for source in (create_source, update_source, delete_source):
        assert 'allowed_roles=("Owner", "Admin", "DocumentManager")' in source

    public_template = read_file_text(PUBLIC_WORKSPACES_TEMPLATE)
    public_script = read_file_text(PUBLIC_WORKSPACE_SCRIPT)
    assert 'id="public-search-input"' in public_template
    assert "function filterPublicDropdownItems()" in public_script
    assert "fetch('/api/public_workspaces?page_size=1000')" in public_script
    assert "const shouldShowSearch = userPublics.length > 0;" in public_script
    assert "publicSearchInput.addEventListener('input', filterPublicDropdownItems);" in public_script
    assert "item.classList.toggle('d-none', !isVisible);" in public_script
    assert "No matching workspaces" in public_script
    assert "No public workspaces are available. Select My Workspaces to create one." in public_script
    assert "You are not a member of any public workspace" not in public_script

    print("[pass] Public workspace route and dropdown search wiring passed")


def test_config_version_for_public_workspace_dropdown_access_change():
    """Verify config.py reflects the public workspace dropdown access update."""
    print("[check] Testing config version bump...")

    assert read_config_version() == "0.241.152"

    print("[pass] Config version bump passed")


if __name__ == "__main__":
    tests = [
        test_public_workspace_helpers_support_all_public_users,
        test_public_workspace_routes_and_dropdown_search_are_wired,
        test_config_version_for_public_workspace_dropdown_access_change,
    ]

    results = []
    for test in tests:
        print(f"\n[test] Running {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception:
            results.append(False)
            raise

    success = all(results)
    print(f"\n[results] {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)