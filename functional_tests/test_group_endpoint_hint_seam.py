# test_group_endpoint_hint_seam.py
"""
Functional test for the backend/frontend seam on group model endpoint hints.
Version: 0.261.140
Implemented in: 0.261.140

Twice in this programme a read-only-era constant shipped as a live defect because
the backend suite pinned the constant while the frontend fixture mocked a populated
value. The endpoint hints must not repeat that: ``endpoint_actions`` on each
endpoint and ``endpoint_management.operations`` in the workspace context are
computed per request from the policy module, never from a literal.

Two layers are pinned. Structurally, every assignment of the hint fields calls the
policy function. Behaviourally, replacing the policy function with a sentinel
changes what the real list and read routes return.
"""

import ast
from pathlib import Path

import pytest

from test_support.group_endpoint_harness import GROUP_A, aoai_endpoint, group_endpoint_environment


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"


def _function(filename, name):
    tree = ast.parse((APP_DIR / filename).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{filename} no longer defines {name}")


def _subscript_assignments(function, field):
    values = []
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == field
                ):
                    values.append(node.value)
    return values


def _calls(value, function_name):
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == function_name
        for node in ast.walk(value)
    )


def test_projector_computes_endpoint_actions_from_policy():
    values = _subscript_assignments(
        _function("functions_group_endpoint_access.py", "_project_group_endpoint"), "endpoint_actions",
    )
    assert values, "_project_group_endpoint never assigns endpoint_actions"
    for value in values:
        assert not isinstance(value, ast.List), "endpoint_actions must not be a literal list"
        assert _calls(value, "group_endpoint_actions")


def test_every_endpoint_response_goes_through_the_projector():
    for name in ("list_group_model_endpoints", "_single_endpoint"):
        source = ast.dump(_function("functions_group_endpoint_access.py", name))
        assert "_project_group_endpoint" in source, f"{name} bypasses the projector"


def test_context_handshake_is_computed_from_policy():
    function = _function("functions_workspace_context.py", "build_group_workspace_context")
    handshake = None
    for node in ast.walk(function):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "endpoint_management":
                    handshake = value
    assert isinstance(handshake, ast.Dict), "the context lost its endpoint_management handshake"
    operations = dict(zip((key.value for key in handshake.keys), handshake.values))["operations"]
    assert not isinstance(operations, ast.List)
    assert _calls(operations, "group_endpoint_management_operations")


def test_write_context_enforces_the_same_projection():
    source = ast.dump(_function("functions_group_endpoint_access.py", "require_group_endpoint_write_context"))
    assert "group_endpoint_management_operations" in source


@pytest.fixture(scope="module")
def module_env():
    with group_endpoint_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


def test_list_and_read_carry_whatever_the_policy_function_returns(env, monkeypatch):
    env.seed_group_with_legacy_endpoints(GROUP_A, [aoai_endpoint("ep-a")])
    received = []

    def sentinel(endpoint, user_id, group, role, settings, *, available=None):
        received.append((endpoint.get("id"), user_id, group.get("id"), role))
        return ["sentinel-action"]

    monkeypatch.setattr(env.modules.access, "group_endpoint_actions", sentinel)
    env.as_user("member")
    listing = env.client.get(f"/api/groups/{GROUP_A}/model-endpoints").get_json()
    assert [item["endpoint_actions"] for item in listing["endpoints"]] == [["sentinel-action"]]
    single = env.client.get(f"/api/groups/{GROUP_A}/model-endpoints/ep-a").get_json()
    assert single["endpoint"]["endpoint_actions"] == ["sentinel-action"]
    assert received == [("ep-a", "member", GROUP_A, "User")] * 2


def test_member_and_manager_hints_differ_as_the_policy_says(env):
    env.seed_group_with_legacy_endpoints(GROUP_A, [aoai_endpoint("ep-a")])
    env.as_user("owner")
    owner = env.client.get(f"/api/groups/{GROUP_A}/model-endpoints").get_json()["endpoints"][0]
    env.as_user("member")
    member = env.client.get(f"/api/groups/{GROUP_A}/model-endpoints").get_json()["endpoints"][0]
    assert owner["endpoint_actions"] == ["edit", "delete", "enable", "test"]
    assert member["endpoint_actions"] == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
