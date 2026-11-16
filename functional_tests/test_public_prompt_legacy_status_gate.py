# test_public_prompt_legacy_status_gate.py
"""
Pin the M9C behaviour change on the legacy /api/public_prompts write routes.

Version: 0.261.177
Implemented in: 0.261.177

Before M9C the active-scoped public prompt writes (POST create, PATCH update and
DELETE) ran with no workspace-status check, so a ``locked``, ``upload_disabled``,
``inactive`` or unrecognized workspace could still be written through the active
route. M9C (contract decision 19 default) gates those writes on the same explicit
status allowlist the new scoped routes use -- an unknown status is denied, never
treated as ``active`` -- while leaving the reads (GET list, GET one) untouched.

Two layers are pinned so a regression in either fails:

1. ``_ensure_active_status_for_write`` refuses every non-``active`` and unknown
   status, refuses a non-manager role, refuses when the feature flag is off, and
   allows an ``active`` workspace for a manager. The refusal decision is computed
   by the real ``public_prompt_management_operations`` policy, so weakening the
   policy allowlist fails this too.
2. The three write routes call the gate and the two read routes do not, proving
   the behaviour change is wired to exactly the writes.
"""

import ast
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import pytest

from test_support.agent_delegation import APP_ROOT
from test_support.app_source import definitions, run_definitions


LEGACY_ROUTE_FILE = "route_backend_public_prompts.py"
POLICY_FILE = "functions_public_prompt_policy.py"
REGISTRAR = "register_route_backend_public_prompts"
WRITE_ROUTES = ("api_create_public_prompt", "api_update_public_prompt", "api_delete_public_prompt")
READ_ROUTES = ("api_list_public_prompts", "api_get_public_prompt")
GATE = "_ensure_active_status_for_write"


def _real_policy():
    """The real management-operations projection with its module constants."""
    namespace = {}
    run_definitions(POLICY_FILE, {
        "PUBLIC_PROMPT_MANAGER_ROLES",
        "PUBLIC_PROMPT_OPERATIONS",
        "public_prompt_management_operations",
    }, namespace)
    return namespace["public_prompt_management_operations"]


def _load_gate(settings):
    """Extract the legacy write gate wired to the real policy and a settings stub."""
    namespace = {
        "public_prompt_management_operations": _real_policy(),
        "get_settings": lambda: settings,
        "jsonify": lambda payload: payload,
    }
    run_definitions(LEGACY_ROUTE_FILE, {GATE}, namespace)
    return namespace[GATE]


def _workspace(status):
    return {"id": "public-a", "name": "Public A", "status": status}


ENABLED = {"enable_public_workspaces": True}


@pytest.mark.parametrize("operation", ("create", "edit", "delete"))
def test_active_workspace_allows_a_manager_write(operation):
    gate = _load_gate(ENABLED)
    assert gate(_workspace("active"), "Owner", operation) is None


@pytest.mark.parametrize("status", ("locked", "upload_disabled", "inactive", "haunted", ""))
@pytest.mark.parametrize("operation", ("create", "edit", "delete"))
def test_non_active_status_refuses_every_write(status, operation):
    gate = _load_gate(ENABLED)
    result = gate(_workspace(status), "Owner", operation)
    assert result is not None
    payload, code = result
    assert code == 403
    assert "not accepting prompt changes" in payload["error"]


@pytest.mark.parametrize("role", ("User", "Stranger", ""))
@pytest.mark.parametrize("operation", ("create", "edit", "delete"))
def test_a_non_manager_role_is_refused_even_when_active(role, operation):
    gate = _load_gate(ENABLED)
    result = gate(_workspace("active"), role, operation)
    assert result is not None
    assert result[1] == 403


@pytest.mark.parametrize("operation", ("create", "edit", "delete"))
def test_the_gate_refuses_when_the_feature_is_disabled(operation):
    gate = _load_gate({"enable_public_workspaces": False})
    result = gate(_workspace("active"), "Owner", operation)
    assert result is not None
    assert result[1] == 403


def _route_nodes():
    module = definitions(
        LEGACY_ROUTE_FILE,
        set(),
        register=REGISTRAR,
        nested=WRITE_ROUTES + READ_ROUTES,
    )
    return {node.name: node for node in module.body}


def _calls_gate(node):
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) and inner.func.id == GATE:
            return True
    return False


@pytest.mark.parametrize("route", WRITE_ROUTES)
def test_each_write_route_calls_the_status_gate(route):
    assert _calls_gate(_route_nodes()[route])


@pytest.mark.parametrize("route", READ_ROUTES)
def test_no_read_route_calls_the_status_gate(route):
    assert not _calls_gate(_route_nodes()[route])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
