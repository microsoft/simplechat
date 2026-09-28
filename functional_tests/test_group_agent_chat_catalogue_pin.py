# test_group_agent_chat_catalogue_pin.py
"""
Pin the group agent ``chat`` hint to the real chat catalogue.
Version: 0.261.138
Implemented in: 0.261.138

M4C §8 B2. ``group_agent_actions`` advertises ``"chat"`` for a group agent from
``group_agent_chat_available``, a small re-implementation of the gate the chat
picker applies. It is correct today because group agents carry no per-agent chat
filter, but nothing stops it drifting from the catalogue. This test pins the
equivalence against the REAL ``build_accessible_agent_catalog`` filtered by the
REAL ``_is_chat_agent_allowed_by_governance`` (the V2 bootstrap filter): across
the tenant flags and governance, a group agent advertises ``"chat"`` exactly when
its catalogue key survives that filter. The Semantic Kernel flags are varied to
show they gate the editor, never chat. It also pins that a merged global row in
the group list advertises no operations at all.

The real catalogue module and policy module are loaded over stubbed dependency
modules (the precedent is ``test_agents_catalog_feature.py``); the governance
filter and one projection helper are compiled from source. No Flask app, Cosmos,
Key Vault, governance backend or network is involved.
"""

import ast
import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
CHATS_FILE = APP_ROOT / "route_frontend_chats.py"
AGENT_ACCESS_FILE = APP_ROOT / "functions_group_agent_access.py"

USER_ID = "user-1"
GROUP_ID = "group-a"
AGENT_ID = "agent-1"
GROUP_DOC = {"id": GROUP_ID, "name": "Group A", "status": "active"}
GROUP = {"id": GROUP_ID, "status": "active"}
AGENT = {"id": AGENT_ID, "name": "Alpha"}
EXPECTED_KEY = f"group:{GROUP_ID}:{AGENT_ID}"


class _Governance:
    """One switch drives both the catalogue filter and the chat predicate."""

    def __init__(self):
        self.group_allow = True

    def decision(self, feature):
        if feature == "governance_group_agents":
            return self.group_allow
        return True


def _load_named_function(source_file, function_name, namespace):
    source = source_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_file))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == function_name
    )
    node.decorator_list = []
    module = ast.Module(body=[node], type_ignores=[])
    exec(compile(module, str(source_file), "exec"), namespace)
    return namespace[function_name]


@pytest.fixture()
def catalog_env():
    governance = _Governance()

    stub_modules = {
        "config": {"cosmos_activity_logs_container": SimpleNamespace(query_items=lambda **kwargs: [])},
        "functions_action_catalog": {
            "resolve_current_user_groups": lambda user_id, user_groups=None: list(user_groups or []),
        },
        "functions_appinsights": {"log_event": lambda *a, **k: None},
        "functions_assigned_knowledge": {"get_agent_assigned_knowledge": lambda *a, **k: {}},
        "functions_global_actions": {"get_global_actions": lambda *a, **k: []},
        "functions_global_agents": {"get_global_agents": lambda *a, **k: []},
        "functions_group": {
            "get_group_model_endpoints": lambda *a, **k: [],
            "get_user_groups": lambda *a, **k: [],
        },
        "functions_group_actions": {"get_group_actions": lambda *a, **k: []},
        "functions_group_agents": {
            "get_group_agents": lambda group_id: [dict(AGENT)] if group_id == GROUP_ID else [],
        },
        "functions_governance": {
            "filter_actions_by_action_type_access": lambda _u, actions, _f, _s: actions or [],
            "filter_governed_global_actions_for_user": lambda _u, actions: actions or [],
            "is_governance_access_allowed": lambda feature, user_id, **k: governance.decision(feature),
        },
        "functions_keyvault": {"SecretReturnType": SimpleNamespace(NAME="name")},
        "functions_personal_actions": {
            "get_governed_personal_actions": lambda *a, **k: [],
            "get_personal_actions": lambda *a, **k: [],
        },
        "functions_personal_agents": {
            "ensure_migration_complete": lambda *a, **k: None,
            "get_personal_agents": lambda *a, **k: [],
        },
        "functions_settings": {
            "get_settings": lambda *a, **k: {},
            "get_user_settings": lambda *a, **k: {"settings": {}},
            "get_group_workflow_management_roles": lambda settings: ("Owner", "Admin"),
            "normalize_agents_page_promoted_popular_agents": lambda value: value or [],
            "normalize_agents_page_promoted_popular_order": lambda value: value or "before",
            "normalize_agents_page_promoted_popular_tag_enabled": lambda value: bool(value),
            "normalize_agents_page_promoted_popular_tag_label": lambda value: value or "Promoted",
            "normalize_agents_page_promoted_popular_window": lambda value: value or "both",
            "normalize_model_endpoints": lambda endpoints: (endpoints or [], []),
        },
    }

    saved = {name: sys.modules.get(name) for name in stub_modules}
    saved_catalog = sys.modules.pop("functions_agent_catalog", None)
    saved_policy = sys.modules.pop("functions_group_agent_policy", None)

    original_path = list(sys.path)
    if str(APP_ROOT) not in sys.path:
        sys.path.insert(0, str(APP_ROOT))

    for module_name, attributes in stub_modules.items():
        module = ModuleType(module_name)
        for attribute_name, value in attributes.items():
            setattr(module, attribute_name, value)
        sys.modules[module_name] = module

    try:
        catalog_module = importlib.import_module("functions_agent_catalog")
        policy_module = importlib.import_module("functions_group_agent_policy")
        is_chat_allowed = _load_named_function(
            CHATS_FILE,
            "_is_chat_agent_allowed_by_governance",
            {"ensure_governance_access": _make_ensure(governance)},
        )
        yield SimpleNamespace(
            governance=governance,
            build_accessible_agent_catalog=catalog_module.build_accessible_agent_catalog,
            build_agent_catalog_key=catalog_module.build_agent_catalog_key,
            group_agent_actions=policy_module.group_agent_actions,
            group_agent_chat_available=policy_module.group_agent_chat_available,
            is_chat_allowed=is_chat_allowed,
        )
    finally:
        sys.modules.pop("functions_agent_catalog", None)
        sys.modules.pop("functions_group_agent_policy", None)
        if saved_catalog is not None:
            sys.modules["functions_agent_catalog"] = saved_catalog
        if saved_policy is not None:
            sys.modules["functions_group_agent_policy"] = saved_policy
        for module_name, original in saved.items():
            if original is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original
        sys.path[:] = original_path


def _make_ensure(governance):
    def ensure_governance_access(feature, user_id, **kwargs):
        if not governance.decision(feature):
            raise PermissionError(feature)
    return ensure_governance_access


def _make_settings(enable_gw, allow_ga, sk_on):
    return {
        "enable_group_workspaces": enable_gw,
        "allow_group_agents": allow_ga,
        "enable_semantic_kernel": sk_on,
        "per_user_semantic_kernel": sk_on,
        "allow_user_agents": False,
        "model_endpoints": [],
    }


def _catalogue_has_group_agent(env, settings):
    catalog = env.build_accessible_agent_catalog(
        USER_ID, settings=settings, user_groups=[dict(GROUP_DOC)]
    )
    filtered = [
        agent for agent in catalog
        if env.is_chat_allowed(
            USER_ID, agent, str(agent.get("scope_type") or "").strip().lower() or "personal"
        )
    ]
    return any(agent.get("catalog_key") == EXPECTED_KEY for agent in filtered)


def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.138")


@pytest.mark.parametrize("enable_gw", [True, False])
@pytest.mark.parametrize("allow_ga", [True, False])
@pytest.mark.parametrize("gov_allow", [True, False])
@pytest.mark.parametrize("sk_on", [True, False])
def test_chat_hint_matches_the_real_catalogue(catalog_env, enable_gw, allow_ga, gov_allow, sk_on):
    env = catalog_env
    env.governance.group_allow = gov_allow
    settings = _make_settings(enable_gw, allow_ga, sk_on)

    actions = env.group_agent_actions(dict(AGENT), USER_ID, GROUP, "User", settings)
    has_chat = "chat" in actions

    in_catalogue = _catalogue_has_group_agent(env, settings)

    # The pin: the advertised chat hint agrees with catalogue membership, and both
    # equal the ground-truth gate (tenant flags plus group-agent governance).
    assert has_chat == in_catalogue
    assert has_chat == (enable_gw and allow_ga and gov_allow)


@pytest.mark.parametrize("enable_gw", [True, False])
@pytest.mark.parametrize("allow_ga", [True, False])
@pytest.mark.parametrize("gov_allow", [True, False])
def test_semantic_kernel_flags_do_not_move_the_chat_hint(catalog_env, enable_gw, allow_ga, gov_allow):
    env = catalog_env
    env.governance.group_allow = gov_allow

    with_sk = env.group_agent_actions(
        dict(AGENT), USER_ID, GROUP, "User", _make_settings(enable_gw, allow_ga, True)
    )
    without_sk = env.group_agent_actions(
        dict(AGENT), USER_ID, GROUP, "User", _make_settings(enable_gw, allow_ga, False)
    )
    assert ("chat" in with_sk) == ("chat" in without_sk)


def test_merged_global_rows_advertise_no_operations():
    """A provided (global) row in the group list never advertises operations."""
    group_agent_actions = Mock(return_value=["edit", "delete", "chat"])
    namespace = {
        "project_editor_record": lambda record, kind, **kwargs: dict(record),
        "group_agent_actions": group_agent_actions,
    }
    project_group_agent = _load_named_function(AGENT_ACCESS_FILE, "_project_group_agent", namespace)

    settings = _make_settings(True, True, True)

    global_row = project_group_agent(
        dict(AGENT), USER_ID, GROUP, "Owner", settings,
        is_global=True, available=True, chat_available=True,
    )
    assert global_row["agent_actions"] == []
    # A global row is never even offered to the per-item policy.
    group_agent_actions.assert_not_called()

    group_row = project_group_agent(
        dict(AGENT), USER_ID, GROUP, "Owner", settings,
        is_global=False, available=True, chat_available=True,
    )
    assert group_row["agent_actions"] == ["edit", "delete", "chat"]
    group_agent_actions.assert_called_once()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
