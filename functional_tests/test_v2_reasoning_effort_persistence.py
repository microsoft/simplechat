# test_v2_reasoning_effort_persistence.py
"""
Functional regressions for canonical reasoning projection and preference contracts.
Version: 0.261.104
Implemented in: 0.261.104

Executes actual catalog/initial-selection functions without Flask/Azure startup, then the
Node behavioral tests. Real late-load, migration and remount behavior is in the UI suite.
"""

import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))

from functions_model_capabilities import REASONING_IDENTIFIER_FIELDS, resolve_model_reasoning_policy  # noqa: E402


def _catalog_functions():
    source = ast.parse((APP / "route_frontend_chats.py").read_text(encoding="utf-8"))
    names = {
        "_normalize_chat_model_value", "_build_chat_model_catalog",
        "_build_initial_chat_model_selection", "_chat_model_reasoning_metadata",
    }
    namespace = {
        "resolve_model_reasoning_policy": resolve_model_reasoning_policy,
        "REASONING_IDENTIFIER_FIELDS": REASONING_IDENTIFIER_FIELDS,
        "sanitize_model_endpoints_for_frontend": copy.deepcopy,
        "normalize_model_endpoints": lambda endpoints: (endpoints, False),
        "_filter_chat_model_endpoints_by_governance": lambda user, endpoints, feature: endpoints,
    }
    module = ast.Module(body=[node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
    exec(compile(module, "route_frontend_chats.py", "exec"), namespace)
    return namespace


def test_authorized_model_policy_is_identical_on_initial_and_refreshed_catalogs():
    namespace = _catalog_functions()
    model = {
        "id": "opaque-uuid", "modelName": "gpt-5.6-luna",
        "deploymentName": "chat-prod", "displayName": "Friendly display",
        "api_key": "never-project-this",
    }
    settings = {"enable_multi_model_endpoints": True, "model_endpoints": [
        {"id": endpoint_id, "models": [model], "endpoint": "https://internal.invalid", "key": "secret"}
        for endpoint_id in ("first", "second")
    ]}
    catalog = namespace["_build_chat_model_catalog"](
        user_id="caller", settings=settings, user_settings_dict={}, user_groups_raw=[],
    )
    assert len(catalog) == 2
    assert catalog[0]["selection_key"] != catalog[1]["selection_key"]
    for item in catalog:
        initial = namespace["_build_initial_chat_model_selection"](
            chat_model_options=catalog, preferred_model_id=item["selection_key"],
        )
        assert initial["model_name"] == item["model_name"] == "gpt-5.6-luna"
        assert initial["reasoning_capabilities"] == item["reasoning_capabilities"] == resolve_model_reasoning_policy("gpt-5.6-luna")
    serialized = json.dumps(catalog)
    assert "never-project-this" not in serialized and "internal.invalid" not in serialized
    assert "secret" not in serialized


def test_legacy_and_apim_models_have_safe_policies_without_new_identity_keys():
    namespace = _catalog_functions()
    for settings in (
        {"gpt_model": {"selected": [{"deploymentName": "custom", "modelName": "gpt-5.6-luna"}]}},
        {"enable_gpt_apim": True, "azure_apim_gpt_deployment": "gpt-5.6-luna"},
    ):
        catalog = namespace["_build_chat_model_catalog"](
            user_id="caller", settings=settings, user_settings_dict={}, user_groups_raw=[],
        )
        assert catalog[0]["reasoning_capabilities"] == resolve_model_reasoning_policy("gpt-5.6-luna")
        assert "model_id" not in catalog[0] and "endpoint_id" not in catalog[0]
    legacy = namespace["_build_chat_model_catalog"](
        user_id="caller",
        settings={"enable_gpt_apim": True, "azure_apim_gpt_deployment": "z-first,a-second"},
        user_settings_dict={}, user_groups_raw=[],
    )
    initial = namespace["_build_initial_chat_model_selection"](chat_model_options=legacy)
    assert initial["deployment_name"] == "z-first"
    apim = namespace["_build_chat_model_catalog"](
        user_id="caller",
        settings={
            "enable_gpt_apim": True, "azure_apim_gpt_deployment": "custom",
            "gpt_model": {"selected": [{"deploymentName": "custom", "modelName": "gpt-5.6-luna"}]},
        },
        user_settings_dict={}, user_groups_raw=[],
    )
    assert apim[0]["model_name"] == apim[0]["selection_key"] == "custom"
    assert apim[0]["reasoning_capabilities"]["status"] == "unknown"


def test_shared_preference_keys_remain_writable_and_request_path_is_centralized():
    users = (APP / "route_backend_users.py").read_text(encoding="utf-8")
    writable = (ROOT / "application" / "v2_ui" / "src" / "lib" / "userSettings.ts").read_text(encoding="utf-8")
    for key in ("reasoningEffortSettings", "preferredModelId", "preferredModelDeployment"):
        assert key in users and key in writable
    composer = (ROOT / "application" / "v2_ui" / "src" / "components" / "chat" / "Composer.tsx").read_text(encoding="utf-8")
    assert "reasoningEffortSettings: { ...saved, ...levels }" in composer
    assert "if (!settingsLoaded || Object.keys(pendingLevels.current).length === 0)" in composer


def test_catalog_identity_matches_authorized_record_policy_priority():
    namespace = _catalog_functions()
    fixtures = [
        ({"modelName": "  ", "behavior_name": "gpt-5.6-luna", "deploymentName": "custom"}, "gpt-5.6-luna"),
        ({"modelName": "  ", "deploymentName": "gpt-5.6-luna"}, "gpt-5.6-luna"),
        ({"modelName": "unknown-private", "behavior_name": "gpt-5.6-luna", "deploymentName": "gpt-5.6-luna"}, "unknown-private"),
        ({"modelName": 17, "behavior_name": "gpt-5.6-luna", "deploymentName": "custom"}, "gpt-5.6-luna"),
        ({"deploymentName": "custom", "displayName": "gpt-5.6-luna", "id": "gpt-5.6-luna"}, "custom"),
    ]
    for model, expected_name in fixtures:
        for settings in (
            {"gpt_model": {"selected": [model]}},
            {"enable_multi_model_endpoints": True, "model_endpoints": [{"id": "endpoint", "models": [model]}]},
        ):
            catalog = namespace["_build_chat_model_catalog"](
                user_id="caller", settings=settings, user_settings_dict={}, user_groups_raw=[],
            )
            initial = namespace["_build_initial_chat_model_selection"](chat_model_options=catalog)
            assert initial["model_name"] == catalog[0]["model_name"] == expected_name
            assert initial["reasoning_capabilities"] == catalog[0]["reasoning_capabilities"] == resolve_model_reasoning_policy(model)
            assert catalog[0]["deployment_name"] == model["deploymentName"]


def test_frontend_reasoning_behavior():
    subprocess.run(["node", str(ROOT / "functional_tests" / "test_v2_reasoning_effort_logic.mjs")], cwd=ROOT, check=True)


if __name__ == "__main__":
    tests = [
        test_authorized_model_policy_is_identical_on_initial_and_refreshed_catalogs,
        test_legacy_and_apim_models_have_safe_policies_without_new_identity_keys,
        test_shared_preference_keys_remain_writable_and_request_path_is_centralized,
        test_catalog_identity_matches_authorized_record_policy_priority,
        test_frontend_reasoning_behavior,
    ]
    for test in tests:
        test()
    print(f"{len(tests)}/{len(tests)} reasoning projection checks passed")
