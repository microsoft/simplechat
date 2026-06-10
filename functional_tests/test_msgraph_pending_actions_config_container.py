# test_msgraph_pending_actions_config_container.py
#!/usr/bin/env python3
"""
Functional test for Microsoft Graph pending actions config container.
Version: 0.241.177
Implemented in: 0.241.177

This test ensures config.py exposes the Cosmos container required by
functions_msgraph_pending_actions.py and uses the expected user-scoped partition key.
"""

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "application" / "single_app" / "config.py"


def _find_assignment(module_ast, target_name):
    for node in module_ast.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == target_name:
                return node
    return None


def test_msgraph_pending_actions_config_container():
    """Verify the pending actions container name, export, and partition key."""
    print("Testing Microsoft Graph pending actions config container...")

    try:
        config_source = CONFIG_PATH.read_text(encoding="utf-8")
        module_ast = ast.parse(config_source)

        name_assignment = _find_assignment(module_ast, "cosmos_msgraph_pending_actions_container_name")
        if not name_assignment or not isinstance(name_assignment.value, ast.Constant):
            print("Missing cosmos_msgraph_pending_actions_container_name assignment.")
            return False
        if name_assignment.value.value != "msgraph_pending_actions":
            print(f"Unexpected container name: {name_assignment.value.value}")
            return False

        container_assignment = _find_assignment(module_ast, "cosmos_msgraph_pending_actions_container")
        if not container_assignment or not isinstance(container_assignment.value, ast.Call):
            print("Missing cosmos_msgraph_pending_actions_container assignment.")
            return False

        partition_key_calls = [
            keyword.value
            for keyword in container_assignment.value.keywords
            if keyword.arg == "partition_key" and isinstance(keyword.value, ast.Call)
        ]
        partition_paths = [
            keyword.value.value
            for call in partition_key_calls
            for keyword in call.keywords
            if keyword.arg == "path" and isinstance(keyword.value, ast.Constant)
        ]
        if "/user_id" not in partition_paths:
            print(f"Expected /user_id partition key, got: {partition_paths}")
            return False

        print("Microsoft Graph pending actions config container is defined correctly")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_msgraph_pending_actions_config_container()
    sys.exit(0 if success else 1)