# test_public_workspace_hidden_document_chat_visibility.py
#!/usr/bin/env python3
"""
Functional test for hidden public workspace document chat visibility.
Version: 0.250.200
Implemented in: 0.250.200

This test ensures a public workspace document chat handoff makes the workspace
visible without hiding other workspaces and rejects unauthorized mutations.
"""

import ast
import sys
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = REPO_ROOT / "application" / "single_app" / "route_frontend_chats.py"


def load_visibility_helper(workspaces, roles):
    """Load the route helper with focused workspace and persistence doubles."""
    source = ROUTE_FILE.read_text(encoding="utf-8")
    parsed = ast.parse(source, filename=str(ROUTE_FILE))
    helper_nodes = [
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_ensure_public_chat_workspace_visible"
    ]
    if len(helper_nodes) != 1:
        raise AssertionError("Expected one public chat workspace visibility helper.")

    persisted = []
    namespace = {
        "find_public_workspace_by_id": lambda workspace_id: workspaces.get(workspace_id),
        "get_user_role_in_public_workspace": (
            lambda workspace, user_id: roles.get((workspace.get("id"), user_id))
        ),
        "add_visible_public_workspace": (
            lambda user_id, workspace_id: persisted.append((user_id, workspace_id))
        ),
    }
    module = ast.Module(body=helper_nodes, type_ignores=[])
    exec(compile(module, str(ROUTE_FILE), "exec"), namespace)
    return namespace["_ensure_public_chat_workspace_visible"], persisted


def test_hidden_public_workspace_handoff_adds_visibility():
    """A valid document handoff should add visibility and preserve existing choices."""
    helper, persisted = load_visibility_helper(
        {"workspace-hidden": {"id": "workspace-hidden"}},
        {("workspace-hidden", "user-1"): "User"},
    )
    user_settings = {
        "publicDirectorySettings": {
            "workspace-visible": True,
            "workspace-hidden": False,
        }
    }

    changed = helper(
        "user-1",
        {
            "search_documents": "true",
            "doc_scope": "public",
            "workspace_id": "workspace-hidden",
        },
        user_settings,
    )

    assert changed is True
    assert persisted == [("user-1", "workspace-hidden")]
    assert user_settings["publicDirectorySettings"] == {
        "workspace-visible": True,
        "workspace-hidden": True,
    }


def test_visible_workspace_handoff_does_not_write_again():
    """An already-visible workspace should not trigger a redundant settings write."""
    helper, persisted = load_visibility_helper({}, {})
    user_settings = {"publicDirectorySettings": {"workspace-visible": True}}

    changed = helper(
        "user-1",
        {
            "search_documents": "TRUE",
            "doc_scope": "PUBLIC",
            "workspace_id": "workspace-visible",
        },
        user_settings,
    )

    assert changed is False
    assert persisted == []


def test_invalid_or_unauthorized_handoffs_do_not_change_visibility():
    """Only an authorized public document-search handoff may update visibility."""
    helper, persisted = load_visibility_helper(
        {"workspace-hidden": {"id": "workspace-hidden"}},
        {("workspace-hidden", "user-1"): None},
    )

    ignored_requests = [
        {"search_documents": "false", "doc_scope": "public", "workspace_id": "workspace-hidden"},
        {"search_documents": "true", "doc_scope": "group", "workspace_id": "workspace-hidden"},
        {"search_documents": "true", "doc_scope": "public", "workspace_id": ""},
    ]
    for request_args in ignored_requests:
        user_settings = {"publicDirectorySettings": {"workspace-existing": True}}
        assert helper("user-1", request_args, user_settings) is False
        assert user_settings == {"publicDirectorySettings": {"workspace-existing": True}}

    user_settings = {"publicDirectorySettings": {"workspace-hidden": False}}
    assert helper(
        "user-1",
        {
            "search_documents": "true",
            "doc_scope": "public",
            "workspace_id": "workspace-hidden",
        },
        user_settings,
    ) is False
    assert persisted == []
    assert user_settings["publicDirectorySettings"]["workspace-hidden"] is False


def test_chat_route_applies_visibility_before_building_public_scope():
    """The chat route must persist handoff visibility before loading selector data."""
    source = ROUTE_FILE.read_text(encoding="utf-8")
    chats_source = source[source.index("    def chats():"):]

    visibility_call = chats_source.index(
        "_ensure_public_chat_workspace_visible(user_id, request.args, user_settings_dict)"
    )
    visible_workspace_load = chats_source.index(
        "get_user_visible_public_workspace_ids_from_settings(user_id)"
    )
    assert visibility_call < visible_workspace_load


def test_version_contract():
    """The application version should include this fix."""
    assert_app_version_at_least("0.250.200")


def main():
    tests = [
        test_hidden_public_workspace_handoff_adds_visibility,
        test_visible_workspace_handoff_does_not_write_again,
        test_invalid_or_unauthorized_handoffs_do_not_change_visibility,
        test_chat_route_applies_visibility_before_building_public_scope,
        test_version_contract,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print(f"PASS: {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {test.__name__}: {exc}")
            results.append(False)

    print(f"Results: {sum(results)}/{len(results)} tests passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
