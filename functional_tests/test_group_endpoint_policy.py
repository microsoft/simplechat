# test_group_endpoint_policy.py
"""
Functional test for the native group model endpoint policy and its context pin.
Version: 0.261.140
Implemented in: 0.261.140

The real ``functions_group_endpoint_policy`` is loaded from its file path with only
``functions_governance`` replaced. The tests pin:

- the one availability predicate, ``group_endpoints_available``: the four tenant
  flags plus the per-user ``governance_group_endpoints`` check, with the section's
  own reason text;
- the management and per-endpoint vocabularies (Owner/Admin in an ``active``
  group; no ``create`` per endpoint; ``require_owner_for_group_agent_management``
  does not narrow endpoints);
- the workspace context uses that predicate and that projection, and no copy of
  them: its Endpoints section and ``endpoint_management`` handshake follow the
  policy functions even when they are replaced by sentinels.
"""

import importlib.util
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_support.agent_delegation import APP_ROOT, module_stub
from test_v2_group_workspace_context import environment as context_environment  # noqa: F401  (pytest fixture)
from test_v2_group_workspace_context import read_as


FLAGS = (
    "enable_semantic_kernel",
    "per_user_semantic_kernel",
    "allow_group_custom_endpoints",
    "enable_multi_model_endpoints",
)
ALL_ON = {flag: True for flag in FLAGS}
OPERATIONS = ["create", "edit", "delete", "enable", "test"]
ITEM_OPERATIONS = ["edit", "delete", "enable", "test"]
DISABLED_REASON = "Group model endpoints are not enabled."
GOVERNANCE_REASON = "Your administrator has restricted access to this capability."


@pytest.fixture
def policy(monkeypatch):
    governance = SimpleNamespace(allowed=True, calls=[])

    def is_governance_access_allowed(feature_key, user_id):
        governance.calls.append((feature_key, user_id))
        return governance.allowed

    monkeypatch.setitem(sys.modules, "functions_governance", module_stub(
        "functions_governance", is_governance_access_allowed=is_governance_access_allowed,
    ))
    spec = importlib.util.spec_from_file_location(
        "tested_group_endpoint_policy", APP_ROOT / "functions_group_endpoint_policy.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.governance = governance
    return module


def group(status="active"):
    return {"id": "group-a", "status": status}


# --------------------------------------------------------------------------
# The availability predicate
# --------------------------------------------------------------------------

def test_available_when_every_flag_is_on_and_governance_allows(policy):
    assert policy.group_endpoints_available("owner", dict(ALL_ON)) == (True, None)
    assert policy.governance.calls == [("governance_group_endpoints", "owner")]


@pytest.mark.parametrize("flag", FLAGS)
def test_each_flag_off_makes_the_surface_unavailable_without_consulting_governance(policy, flag):
    settings = {**ALL_ON, flag: False}
    assert policy.group_endpoints_configured(settings) is False
    assert policy.group_endpoints_available("owner", settings) == (False, DISABLED_REASON)
    assert policy.governance.calls == []


def test_governance_denial_is_its_own_reason(policy):
    policy.governance.allowed = False
    assert policy.group_endpoints_available("owner", dict(ALL_ON)) == (False, GOVERNANCE_REASON)


def test_group_workspaces_flag_is_left_to_the_route_decorator(policy):
    # ``enable_group_workspaces`` is enforced by ``enabled_required`` and the context
    # guard, exactly as for group agents, so the predicate does not repeat it.
    settings = {**ALL_ON, "enable_group_workspaces": False}
    assert policy.group_endpoints_available("owner", settings) == (True, None)


# --------------------------------------------------------------------------
# Management and per-endpoint projections
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role,status,expected", [
    ("Owner", "active", OPERATIONS),
    ("Admin", "active", OPERATIONS),
    ("DocumentManager", "active", []),
    ("User", "active", []),
    (None, "active", []),
    ("Owner", "locked", []),
    ("Owner", "upload_disabled", []),
    ("Owner", "inactive", []),
    ("Owner", "unexpected-status", []),
])
def test_management_operations_need_a_write_role_in_an_active_group(policy, role, status, expected):
    operations = policy.group_endpoint_management_operations("user", group(status), role, dict(ALL_ON))
    assert operations == expected
    actions = policy.group_endpoint_actions({"id": "ep"}, "user", group(status), role, dict(ALL_ON))
    assert actions == [operation for operation in ITEM_OPERATIONS if operation in expected]
    assert "create" not in actions


def test_unavailable_surface_offers_nothing_even_to_an_owner(policy):
    policy.governance.allowed = False
    assert policy.group_endpoint_management_operations("owner", group(), "Owner", dict(ALL_ON)) == []
    assert policy.group_endpoint_actions({"id": "ep"}, "owner", group(), "Owner", dict(ALL_ON)) == []


def test_precomputed_availability_skips_the_governance_check(policy):
    operations = policy.group_endpoint_management_operations(
        "owner", group(), "Owner", dict(ALL_ON), available=True,
    )
    assert operations == OPERATIONS
    assert policy.governance.calls == []
    assert policy.group_endpoint_management_operations(
        "owner", group(), "Owner", dict(ALL_ON), available=False,
    ) == []


def test_owner_only_agent_management_does_not_narrow_endpoint_roles(policy):
    settings = {**ALL_ON, "require_owner_for_group_agent_management": True}
    assert policy.group_endpoint_management_operations("admin", group(), "Admin", settings) == OPERATIONS


# --------------------------------------------------------------------------
# Context pin: the context uses the predicate and projection, not a copy
# --------------------------------------------------------------------------

def _endpoint_policy(context_environment):
    return sys.modules["functions_group_endpoint_policy"]


@pytest.mark.parametrize("flag", FLAGS)
def test_context_section_follows_the_predicate_when_a_flag_is_off(context_environment, flag):
    context_environment.settings[flag] = False
    body = read_as(context_environment).get_json()
    available, reason = _endpoint_policy(context_environment).group_endpoints_available(
        "owner", context_environment.settings,
    )
    assert available is False
    assert body["sections"]["endpoints"]["enabled"] is available
    assert body["sections"]["endpoints"]["reason"] == reason == DISABLED_REASON
    assert body["endpoint_management"] == {"schema_version": 1, "operations": []}


def test_context_section_follows_the_predicate_when_governance_denies(context_environment):
    context_environment.governance.side_effect = lambda feature, user_id: feature != "governance_group_endpoints"
    body = read_as(context_environment).get_json()
    assert body["sections"]["endpoints"] == {
        "enabled": False, "can_manage": False, "reason": GOVERNANCE_REASON,
        "group": body["sections"]["endpoints"]["group"],
    }
    assert body["endpoint_management"]["operations"] == []
    # Only the endpoint section is affected; group agents keep their own predicate.
    assert body["sections"]["agents"]["enabled"] is True


@pytest.mark.parametrize("actor,status", [
    ("owner", "active"), ("admin", "active"), ("manager", "active"), ("reader", "active"),
    ("owner", "locked"), ("admin", "upload_disabled"), ("owner", "inactive"), ("owner", "unknown"),
])
def test_context_handshake_equals_the_policy_projection(context_environment, actor, status):
    context_environment.records["group-a"]["status"] = status
    body = read_as(context_environment, actor).get_json()
    policy = _endpoint_policy(context_environment)
    group_doc = deepcopy(context_environment.records["group-a"])
    expected = policy.group_endpoint_management_operations(
        actor, group_doc, body["role"], context_environment.settings,
    )
    assert body["endpoint_management"] == {"schema_version": 1, "operations": expected}
    assert body["sections"]["endpoints"]["can_manage"] is bool(expected)


def test_context_uses_the_predicate_function_itself(context_environment, monkeypatch):
    """Replace the predicate with sentinels: the context must follow them, flags notwithstanding."""
    helper = context_environment.helper
    calls = []

    def denied(user_id, settings):
        calls.append((user_id, settings))
        return False, "Sentinel reason from the predicate."

    monkeypatch.setattr(helper, "group_endpoints_available", denied)
    body = read_as(context_environment).get_json()
    assert calls == [("owner", context_environment.settings)]
    assert body["sections"]["endpoints"]["enabled"] is False
    assert body["sections"]["endpoints"]["reason"] == "Sentinel reason from the predicate."
    assert body["endpoint_management"]["operations"] == []

    context_environment.settings["allow_group_custom_endpoints"] = False
    monkeypatch.setattr(helper, "group_endpoints_available", lambda user_id, settings: (True, None))
    opened = read_as(context_environment).get_json()
    assert opened["sections"]["endpoints"]["enabled"] is True
    assert opened["endpoint_management"]["operations"] == OPERATIONS


def test_context_handshake_uses_the_projection_function_itself(context_environment, monkeypatch):
    helper = context_environment.helper
    received = []

    def sentinel(user_id, group_doc, role, settings, *, available=None):
        received.append((user_id, group_doc.get("id"), role, available))
        return ["sentinel-operation"]

    monkeypatch.setattr(helper, "group_endpoint_management_operations", sentinel)
    body = read_as(context_environment).get_json()
    assert body["endpoint_management"] == {"schema_version": 1, "operations": ["sentinel-operation"]}
    # The context threads its one availability result through instead of re-checking.
    assert received == [("owner", "group-a", "Owner", True)]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
