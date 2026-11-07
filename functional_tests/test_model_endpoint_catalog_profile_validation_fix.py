#!/usr/bin/env python3
# test_model_endpoint_catalog_profile_validation_fix.py
"""
Functional test for the model endpoint catalog profile validation fix.
Version: 0.261.140
Implemented in: 0.261.140

``normalize_model_endpoints`` rejects a malformed ``catalogProfileId`` by raising
``ModelTokenBudgetError``, but ``functions_settings.py`` never imported that class.
Every save carrying a malformed profile ID therefore failed with ``NameError`` and a
500 instead of the reviewed 400 the callers already map. This test ensures the class
is bound where it is raised, and that the native group, personal and legacy group
save paths answer with the stable token-budget 400 and write nothing.
"""

import ast
import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.group_endpoint_harness import (  # noqa: E402
    GROUP_A,
    aoai_endpoint,
    group_endpoint_environment,
)


SETTINGS_MODULE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "application", "single_app", "functions_settings.py"
)
EXPECTED_BODY = {"error": "Choose a valid catalog profile.", "error_code": "invalid_model_profile"}
MALFORMED_MODELS = [
    {"id": "m", "deploymentName": "gpt-4o", "modelName": "gpt-4o", "catalogProfileId": "bad profile!"},
]


def test_functions_settings_binds_the_error_it_raises():
    """The module that raises ModelTokenBudgetError must import it at module level."""
    with open(SETTINGS_MODULE, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    imported = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "functions_model_capabilities"
        for alias in node.names
    }
    raised = {
        node.exc.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
    }
    assert "ModelTokenBudgetError" in raised
    assert "ModelTokenBudgetError" in imported


@pytest.fixture(scope="module")
def module_env():
    with group_endpoint_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    module_env.seed_group_with_legacy_endpoints(GROUP_A, [aoai_endpoint("ep-a")])
    module_env.seed_personal_endpoints("owner", [aoai_endpoint("pe-own", api_key="own-personal-key")])
    module_env.active_group = GROUP_A
    module_env.vault.writes.clear()
    yield module_env
    module_env.reset()


def test_native_group_create_refuses_a_malformed_profile_with_a_stable_400(env):
    payload = aoai_endpoint("", api_key="sk-new")
    payload.pop("id")
    payload["name"] = "New connection"
    payload["models"] = MALFORMED_MODELS
    response = env.call("POST", f"/api/groups/{GROUP_A}/model-endpoints", payload)
    assert response.status_code == 400
    assert response.get_json() == EXPECTED_BODY
    assert env.write_calls() == []
    assert env.vault.writes == []


def test_personal_create_refuses_a_malformed_profile_with_a_stable_400(env):
    payload = aoai_endpoint("pe-new", api_key="sk-new")
    payload["models"] = MALFORMED_MODELS
    response = env.call("POST", "/api/user/model-endpoints", payload)
    assert response.status_code == 400
    assert response.get_json() == EXPECTED_BODY
    assert env.personal_endpoint("owner", "pe-new") is None
    assert env.vault.writes == []


def test_legacy_group_save_refuses_a_malformed_profile_with_a_stable_400(env):
    endpoint = aoai_endpoint("ep-a")
    endpoint["models"] = MALFORMED_MODELS
    response = env.call("POST", "/api/group/model-endpoints", {"endpoints": [endpoint]})
    assert response.status_code == 400
    assert response.get_json() == EXPECTED_BODY
    assert env.write_calls() == []
    assert env.vault.writes == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
