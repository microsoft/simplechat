# test_agent_model_governance_filtering.py
#!/usr/bin/env python3
"""
Functional test for agent model governance filtering.
Version: 0.261.048
Implemented in: 0.261.048

This test ensures the personal and group agent model dropdown payloads apply
governance policies before returning model endpoints to the browser.
"""

import ast
import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_ROUTE = REPO_ROOT / "application" / "single_app" / "route_backend_agents.py"


def _load_build_combined_model_endpoints():
    source = AGENTS_ROUTE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function_node = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "build_combined_model_endpoints"
        ),
        None,
    )
    if function_node is None:
        raise AssertionError("build_combined_model_endpoints was not found.")

    module = ast.Module(body=[function_node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, str(AGENTS_ROUTE), "exec"), namespace)
    return namespace["build_combined_model_endpoints"]


def test_agent_settings_model_endpoints_respect_governance():
    print("Testing agent settings model endpoint governance filtering...")
    assert_app_version_at_least("0.261.048")

    calls = []
    build_combined_model_endpoints = _load_build_combined_model_endpoints()

    def filter_governed_model_endpoints(user_id, endpoints, feature_key):
        calls.append((user_id, feature_key, [endpoint.get("id") for endpoint in endpoints]))
        return [endpoint for endpoint in endpoints if "denied" not in endpoint.get("id", "")]

    def sanitize_model_endpoints_for_frontend(endpoints):
        return endpoints

    def ensure_governance_access(feature_key, user_id):
        calls.append((user_id, feature_key, "feature-check"))

    def get_user_settings(user_id):
        return {
            "settings": {
                "personal_model_endpoints": [
                    {"id": "personal-allowed", "models": [{"id": "personal-model"}]},
                    {"id": "personal-denied", "models": [{"id": "restricted-personal-model"}]},
                ]
            }
        }

    def get_group_model_endpoints(group_id):
        return [
            {"id": "group-allowed", "models": [{"id": "group-model"}]},
            {"id": "group-denied", "models": [{"id": "restricted-group-model"}]},
        ]

    build_combined_model_endpoints.__globals__.update({
        "filter_governed_model_endpoints": filter_governed_model_endpoints,
        "sanitize_model_endpoints_for_frontend": sanitize_model_endpoints_for_frontend,
        "ensure_governance_access": ensure_governance_access,
        "get_user_settings": get_user_settings,
        "get_group_model_endpoints": get_group_model_endpoints,
    })

    settings = {
        "model_endpoints": [
            {"id": "global-allowed", "models": [{"id": "allowed-model"}]},
            {"id": "global-denied", "models": [{"id": "restricted-model"}]},
        ],
        "allow_user_custom_endpoints": True,
        "allow_group_custom_endpoints": True,
    }

    personal_ids = [
        endpoint["id"]
        for endpoint in build_combined_model_endpoints(settings, user_id="user-b")
    ]
    assert personal_ids == ["global-allowed", "personal-allowed"], personal_ids

    group_ids = [
        endpoint["id"]
        for endpoint in build_combined_model_endpoints(
            settings,
            user_id="user-b",
            group_id="group-1",
        )
    ]
    assert group_ids == ["global-allowed", "group-allowed"], group_ids

    admin_ids = [endpoint["id"] for endpoint in build_combined_model_endpoints(settings)]
    assert admin_ids == ["global-allowed", "global-denied"], admin_ids

    asserted_filters = {(call[0], call[1]) for call in calls if len(call) == 3}
    assert ("user-b", "governance_global_endpoints") in asserted_filters
    assert ("user-b", "governance_user_endpoints") in asserted_filters
    assert ("user-b", "governance_group_endpoints") in asserted_filters
    print("PASS: agent settings model endpoint governance filtering verified")


if __name__ == "__main__":
    try:
        test_agent_settings_model_endpoints_respect_governance()
        sys.exit(0)
    except Exception as exc:
        print(f"FAIL: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)