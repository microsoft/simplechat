# test_group_agent_secret_scope.py
"""
Functional test pinning the §2.1 agent Key Vault scope seam.
Version: 0.261.138
Implemented in: 0.261.138

Before M4C the shared editor engine hardcoded every agent credential to the
``user`` Key Vault scope: ``_secret_scope`` returned ``(record_id, "agent",
"user")`` regardless of where the agent lived. Group agents are stored under the
``group`` scope by the legacy group route's ``keyvault_agent_save_helper``, so a
V2 group agent would either fail to rehydrate a V1-written secret (wrong scope on
read) or mint an orphan ``{agent_id}--agent--user--{name}`` secret that the legacy
``scope="group"`` delete would never clean up.

This test pins the fix directly at the seam: for ``kind="agents"`` the resolved
scope is ``group`` exactly when a ``group_id`` is present, and ``user`` otherwise,
while the source stays ``agent`` and the scope value stays the agent id. Personal
agents (no ``group_id``) are unchanged, and actions keep their own scoping.
"""

import importlib.util
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from test_support.agent_delegation import APP_ROOT
from test_support.versioning import assert_app_version_at_least


@pytest.fixture
def secret_scope(monkeypatch):
    """Load the real authoring engine standalone and hand back ``_secret_scope``.

    Only the one top-level service import (``functions_ai_connections``) is stubbed;
    ``_secret_scope`` itself reaches no service, so the seam is exercised for real.
    """
    monkeypatch.syspath_prepend(str(APP_ROOT))
    connections = ModuleType("functions_ai_connections")
    connections.filter_model_endpoints_by_capability = MagicMock(return_value=[])
    monkeypatch.setitem(sys.modules, "functions_ai_connections", connections)
    monkeypatch.delitem(sys.modules, "functions_workspace_authoring", raising=False)
    spec = importlib.util.spec_from_file_location(
        "functions_workspace_authoring", APP_ROOT / "functions_workspace_authoring.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "functions_workspace_authoring", module)
    spec.loader.exec_module(module)
    return module._secret_scope


AGENT_RECORD = {"id": "agent-123", "name": "Shared assistant"}
KEY_PATH = ("azure_openai_gpt_key",)


def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.138")


def test_group_agent_secret_resolves_to_group_scope(secret_scope):
    assert secret_scope("agents", "user-1", AGENT_RECORD, KEY_PATH, group_id="group-a") == (
        "agent-123", "agent", "group",
    )


def test_personal_agent_secret_stays_user_scope(secret_scope):
    assert secret_scope("agents", "user-1", AGENT_RECORD, KEY_PATH) == (
        "agent-123", "agent", "user",
    )
    assert secret_scope("agents", "user-1", AGENT_RECORD, KEY_PATH, group_id=None) == (
        "agent-123", "agent", "user",
    )


def test_agent_scope_value_is_the_agent_id_not_the_group_or_user(secret_scope):
    # Whichever namespace it lives in, an agent secret is keyed by the agent id and
    # the ``agent`` source, so the legacy save/delete helpers address the same name.
    group_value, group_source, _ = secret_scope(
        "agents", "user-1", AGENT_RECORD, KEY_PATH, group_id="group-a",
    )
    user_value, user_source, _ = secret_scope("agents", "user-1", AGENT_RECORD, KEY_PATH)
    assert group_value == user_value == "agent-123"
    assert group_source == user_source == "agent"


def test_actions_keep_their_own_scoping(secret_scope):
    # The agent branch must not have widened to actions: a group action key is
    # scoped by the group id under the action source, not the record id.
    action_record = {"id": "action-9", "name": "connector"}
    assert secret_scope("actions", "user-1", action_record, ("auth", "key"), group_id="group-a") == (
        "group-a", "action", "group",
    )
    assert secret_scope("actions", "user-1", action_record, ("auth", "key")) == (
        "user-1", "action", "user",
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
