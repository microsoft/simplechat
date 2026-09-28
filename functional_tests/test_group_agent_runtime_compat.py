# test_group_agent_runtime_compat.py
"""
Runtime compatibility of the stored group-agent shape (M4C §8 B6).
Version: 0.261.138
Implemented in: 0.261.138

One record is built by the REAL ``apply_group_agent_write`` (through the immutable
group-agent create route, over the same in-memory Cosmos seam the API contract
suite uses), and the resulting *stored document* is fed to every runtime consumer
that branches on the ``is_global``/``is_group``/``group_id`` shape B4 restores:

* ``functions_group_agents._clean_agent`` (the read normalizer);
* ``functions_agent_catalog.build_accessible_agent_catalog`` (chat selection);
* ``route_backend_chats._resolve_canonical_chat_agent`` (chat resolution);
* ``functions_agent_delegation.agent_reference`` / ``_canonical_agent`` (Call agent);
* ``functions_agent_scope`` (selection scope);
* ``functions_group_workflows._find_matching_agent`` (line 227 eligibility).

Each consumer is loaded from source in isolation (a spec import for the pure
modules, an AST-compiled function for the ones inside heavy route modules), so no
Flask app, Cosmos, Key Vault, governance backend or network is required. The one
record they all receive is the genuine output of the editor write path.
"""

import ast
import importlib.util
import sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least

# The API-contract suite owns the real create harness; reuse its fixture and
# helpers so the record under test is built by the same route/authoring engine.
from test_group_agent_apis import (  # noqa: E402  (fixture reuse)
    LIST_PATH,
    as_user,
    create_body,
    environment,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
GROUP_AGENTS_FILE = APP_ROOT / "functions_group_agents.py"
CHATS_ROUTE_FILE = APP_ROOT / "route_backend_chats.py"
CHATS_FRONTEND_FILE = APP_ROOT / "route_frontend_chats.py"
WORKFLOWS_FILE = APP_ROOT / "functions_group_workflows.py"

GROUP_ID = "group-a"
USER_ID = "user-1"
GROUP_DOC = {"id": GROUP_ID, "name": "Group A", "status": "active"}


def _create_stored_group_agent(environment, name="runtime-agent", **fields):
    """Create one group agent through the real route and return its stored document."""
    as_user(environment, "owner")
    body = create_body(name=name, **fields)
    response = environment.client.post(LIST_PATH, json=body)
    assert response.status_code == 201, response.get_data(as_text=True)
    agent_id = body["updates"]["id"]
    stored = environment.group_container.records[(GROUP_ID, agent_id)]
    # The write path must have stamped the legacy group shape (B4); everything
    # downstream depends on it.
    assert stored["is_group"] is True and stored["is_global"] is False
    assert stored["group_id"] == GROUP_ID
    return deepcopy(stored)


def _load_module_from_file(name, source_file):
    """Load a real module from its file without registering it in ``sys.modules``."""
    spec = importlib.util.spec_from_file_location(name, source_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_named_function(source_file, function_name, namespace):
    """Compile one top-level function from ``source_file`` with its free names supplied."""
    source = Path(source_file).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_file))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == function_name
    )
    node.decorator_list = []
    module = ast.Module(body=[node], type_ignores=[])
    exec(compile(module, str(source_file), "exec"), namespace)
    return namespace[function_name]


def _chat_settings():
    return {
        "enable_group_workspaces": True,
        "allow_group_agents": True,
        "enable_semantic_kernel": True,
        "per_user_semantic_kernel": True,
        "allow_user_agents": False,
        "model_endpoints": [],
    }


# --------------------------------------------------------------------------
# Versioning
# --------------------------------------------------------------------------

def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.138")


# --------------------------------------------------------------------------
# Read normalizer
# --------------------------------------------------------------------------

def test_clean_agent_preserves_the_stored_group_shape(environment):
    stored = _create_stored_group_agent(environment)
    clean_agent = _load_named_function(
        GROUP_AGENTS_FILE, "_clean_agent",
        {
            "Dict": dict, "Any": object,
            "keyvault_agent_get_helper": lambda record, agent_id, scope="group": record,
        },
    )

    cleaned = clean_agent(stored)

    assert cleaned["is_group"] is True
    assert cleaned["is_global"] is False
    assert cleaned["group_id"] == GROUP_ID
    # The read normalizer must not strip the identity a group agent is stored with.
    assert cleaned["id"] == stored["id"]
    assert cleaned["max_completion_tokens"] == -1


# --------------------------------------------------------------------------
# Selection scope
# --------------------------------------------------------------------------

def test_agent_scope_resolves_the_stored_group_agent(environment):
    stored = _create_stored_group_agent(environment)
    scope = _load_module_from_file("functions_agent_scope", APP_ROOT / "functions_agent_scope.py")

    selection = {"id": stored["id"], "is_group": True, "group_id": GROUP_ID}
    assert scope.find_agent_by_scope([stored], selection) is stored

    # A different group must not match the stored group agent.
    other = {"id": stored["id"], "is_group": True, "group_id": "group-b"}
    assert scope.find_agent_by_scope([stored], other) is None

    assert scope.is_selected_agent_scope_enabled({"allow_group_agents": True}, stored) is True
    assert scope.is_selected_agent_scope_enabled({"allow_group_agents": False}, stored) is False


# --------------------------------------------------------------------------
# Delegation (Call agent)
# --------------------------------------------------------------------------

def test_delegation_reference_and_canonicalization(environment):
    stored = _create_stored_group_agent(environment)
    delegation = _load_module_from_file(
        "functions_agent_delegation", APP_ROOT / "functions_agent_delegation.py"
    )

    reference = delegation.agent_reference(stored, USER_ID)
    assert reference == {"id": stored["id"], "scope_type": "group", "scope_id": GROUP_ID}

    canonical = delegation._canonical_agent(stored, "group", GROUP_ID)
    assert canonical["is_group"] is True
    assert canonical["is_global"] is False
    assert canonical["group_id"] == GROUP_ID
    assert canonical["scope_type"] == "group" and canonical["scope_id"] == GROUP_ID
    assert canonical["user_id"] is None

    # Canonicalizing against a foreign group is refused, never silently rescoped.
    with pytest.raises(PermissionError):
        delegation._canonical_agent(stored, "group", "group-b")


# --------------------------------------------------------------------------
# Group workflow eligibility (line 227)
# --------------------------------------------------------------------------

def test_group_workflow_eligibility_matches_the_stored_shape(environment):
    stored = _create_stored_group_agent(environment)
    find_matching_agent = _load_named_function(WORKFLOWS_FILE, "_find_matching_agent", {})

    requested = {"id": stored["id"], "is_group": True, "group_id": GROUP_ID}
    assert find_matching_agent([stored], requested, GROUP_ID) is stored

    # Its group scope is required; the same id is ineligible for another group.
    assert find_matching_agent([stored], requested, "group-b") is None
    global_request = {"id": stored["id"], "is_global": True}
    assert find_matching_agent([stored], global_request, GROUP_ID) is None


# --------------------------------------------------------------------------
# Chat resolution
# --------------------------------------------------------------------------

def test_chat_resolution_accepts_the_stored_group_agent(environment):
    stored = _create_stored_group_agent(environment)
    scope_matches = _load_named_function(CHATS_ROUTE_FILE, "_chat_agent_scope_matches", {})
    resolve = _load_named_function(
        CHATS_ROUTE_FILE, "_resolve_canonical_chat_agent",
        {
            "_build_user_accessible_chat_agents": lambda user_id, settings, requested_agent=None: [stored],
            "_chat_agent_scope_matches": scope_matches,
        },
    )

    requested = {"id": stored["id"], "is_group": True, "group_id": GROUP_ID}
    assert resolve(USER_ID, _chat_settings(), requested) is stored

    # A mismatched workspace must not resolve to the stored group agent.
    foreign = {"id": stored["id"], "is_group": True, "group_id": "group-b"}
    assert resolve(USER_ID, _chat_settings(), foreign) is None


# --------------------------------------------------------------------------
# Chat catalogue
# --------------------------------------------------------------------------

@contextmanager
def _real_catalog(stored):
    """Load the real catalogue over dependency stubs, serving ``stored`` as the group agent."""
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
            "get_group_agents": lambda group_id: [deepcopy(stored)] if group_id == GROUP_ID else [],
        },
        "functions_governance": {
            "filter_actions_by_action_type_access": lambda _u, actions, _f, _s: actions or [],
            "filter_governed_global_actions_for_user": lambda _u, actions: actions or [],
            "is_governance_access_allowed": lambda feature, user_id, **k: True,
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
        is_chat_allowed = _load_named_function(
            CHATS_FRONTEND_FILE, "_is_chat_agent_allowed_by_governance",
            {"ensure_governance_access": lambda *a, **k: None},
        )
        yield SimpleNamespace(
            build_accessible_agent_catalog=catalog_module.build_accessible_agent_catalog,
            build_agent_catalog_key=catalog_module.build_agent_catalog_key,
            is_chat_allowed=is_chat_allowed,
        )
    finally:
        sys.modules.pop("functions_agent_catalog", None)
        if saved_catalog is not None:
            sys.modules["functions_agent_catalog"] = saved_catalog
        for module_name, original in saved.items():
            if original is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original
        sys.path[:] = original_path


def test_catalog_serves_the_stored_group_agent_for_chat(environment):
    stored = _create_stored_group_agent(environment)
    expected_key = f"group:{GROUP_ID}:{stored['id']}"

    with _real_catalog(stored) as catalog:
        assert catalog.build_agent_catalog_key(stored) == expected_key

        entries = catalog.build_accessible_agent_catalog(
            USER_ID, settings=_chat_settings(), user_groups=[dict(GROUP_DOC)]
        )
        match = next((e for e in entries if e.get("catalog_key") == expected_key), None)
        assert match is not None
        assert match.get("scope_type") == "group"

        # The stored record survives the real chat governance filter unchanged.
        allowed = [
            entry for entry in entries
            if catalog.is_chat_allowed(
                USER_ID, entry, str(entry.get("scope_type") or "").strip().lower() or "personal"
            )
        ]
        assert any(entry.get("catalog_key") == expected_key for entry in allowed)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
