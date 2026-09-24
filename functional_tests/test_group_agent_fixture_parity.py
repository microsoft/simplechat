# test_group_agent_fixture_parity.py
"""
Per-route shape parity between the M4C group agent UI fixture and the real routes.
Version: 0.261.157
Implemented in: 0.261.157

The V2 group Agents workbench and its editor mock the network with the closed HTTP fixture
``ui_tests/fixtures/group_agents.py``, whose dispatch lives in the shared
``ui_tests/fixtures/group_workspace.py`` base. A fixture whose response shape drifts from the
server lets a passing browser suite hide a real regression. The M4C agent fixtures predate the
per-route parity rule, so this test backfills the pin.

For every native route the agent workbench (``lib/agentWorkbench.ts``) and its editor call --
list, read, create, update, delete, ``agent-options`` and ``agent-knowledge``, plus the stale
revision conflict and each refusal the editor renders -- it asserts that the fixture never
invents a top-level, record, option, endpoint, model or catalogue key the server does not return
(``fixture keys <= server keys``), that the keys the UI reads are present on both sides, that the
status code and the machine-readable ``error_code`` match (the agent routes send none, so its
absence is pinned), and that every message the editor renders verbatim is the server's own.

The real routes run through ``test_support/group_agent_harness.py``, the family API suite's
harness, with the deployment the fixture models (every agent type allowed, global agents merged
in, the template gallery and the math builtin on). Three harness seams would otherwise answer
with invented shapes, so this test replaces them with the real code for its own requests:

- the stored agents and the create and update preparer run through the real
  ``sanitize_agent_payload``, so a record carries exactly the keys a real stored agent does. The
  preparer's knowledge, schema and delegation checks are left out; none of them adds a key;
- the option endpoints are the real ``build_combined_model_endpoints`` and the options builder's
  second sanitize pass, computed once in ``test_support/group_endpoint_harness.py``, which loads
  the real settings module;
- the knowledge catalogue is the real ``build_assigned_knowledge_catalog`` with its real tag
  normalization. Document storage, current-version selection and screening are passthrough seams
  that neither add nor remove a catalogue key.

The fixture handlers are the production browser-test code, exercised through the same
``_dispatch`` entry the Playwright route handler calls, with a tiny fake page and route that only
capture the fulfilled status and JSON. The named-group Foundry discovery route the editor also
calls is pinned by ``test_group_endpoint_fixture_parity.py``.

One product finding is pinned as a strict xfail for the coordinator's decision: the group editor
offers public knowledge, which the server neither lists for a group nor stores on a group agent.
"""

import ast
import importlib.util
import json
import logging
import re
import sys
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import Mock

import pytest
from flask import jsonify

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN, SECRET_MASK  # noqa: E402
from ui_tests.fixtures.group_agents import (  # noqa: E402
    EDITABLE_AGENT_ID, FOUNDRY_AGENT_ID, MEMBER_AGENT_ID, PROVIDED_AGENT_ID, WITHHELD_AGENT_ID,
    GroupAgentsFixture,
)
from ui_tests.fixtures.group_workspace import (  # noqa: E402
    GLOBAL_FOUNDRY_ENDPOINT_ID, GROUP_FOUNDRY_ENDPOINT_ID,
)

from test_support.agent_delegation import APP_ROOT, execute_functions  # noqa: E402
from test_support.group_agent_harness import (  # noqa: E402,F401  (environment is a pytest fixture)
    KNOWLEDGE_PATH, LIST_PATH, OPTIONS_PATH, as_user, environment,
)
from test_support.group_endpoint_harness import (  # noqa: E402
    aoai_endpoint, foundry_endpoint, group_endpoint_environment,
)


GROUP_A = "group-a"
GROUP_B = "group-b"

# The deployment the agent fixture models: every agent type on, global agents merged into the
# group list, the template gallery on with user submissions allowed, and the math builtin on.
MODELLED_SETTINGS = {
    "allow_group_ai_foundry_agents": True,
    "allow_group_new_foundry_agents": True,
    "merge_global_semantic_kernel_with_workspace": True,
    "enable_multi_model_endpoints": True,
    "enable_agent_template_gallery": True,
    "allow_user_agents": True,
    "agent_templates_allow_user_submission": True,
    "enable_web_search": True,
    "enable_url_access": True,
    "enable_math_plugin": True,
}

# The record keys the workbench and its gates read: identity and presentation in the collection,
# `group_id` and `agent_actions` for the per-agent gates, `is_global` for the provided-row scope
# check. Optional presentation fields (icon, tags, model and deployment fields) are stored
# passthrough fields the real sanitizer defaults; subset parity still holds for them.
AGENT_UI_KEYS = {
    "id", "name", "display_name", "description", "agent_type", "actions_to_load",
    "is_global", "agent_actions",
}
GROUP_AGENT_UI_KEYS = AGENT_UI_KEYS | {"group_id"}
ENVELOPE_UI_KEYS = {"record", "revision", "secret_paths", "read_only"}
OPTIONS_UI_KEYS = {"agent_types", "settings", "model_endpoints", "builtin_actions"}
AGENT_TYPE_UI_KEYS = {"value", "label", "enabled"}
# The option settings the group agent editor reads: the custom-endpoint and template-submission
# gates, the gallery switch, and the model-choice fallbacks (`agentModelChoices`).
SETTINGS_UI_KEYS = {
    "allow_group_custom_endpoints", "agent_template_submission_allowed", "enable_agent_template_gallery",
    "enable_multi_model_endpoints", "enable_gpt_apim", "azure_apim_gpt_deployment", "gpt_model",
}
ENDPOINT_UI_KEYS = {"id", "name", "provider", "enabled", "scope", "models"}
MODEL_UI_KEYS = {"id", "deploymentName", "modelName", "enabled", "capability_status"}
BUILTIN_UI_KEYS = {"id", "label"}
CATALOG_UI_KEYS = {"sources", "documents", "tags"}
SOURCE_UI_KEYS = {"scope", "id", "label"}
DOCUMENT_UI_KEYS = {"id", "title", "file_name", "scope", "source_id", "source_name", "tags"}
TAG_UI_KEYS = {"name", "count"}
# Keys only the projection owns, so a stored record never carries them.
PROJECTION_KEYS = {"agent_actions", "is_global", "is_group"}


# --------------------------------------------------------------------------
# Fixture driving: a fake page and route that only capture the fulfilled response.
# --------------------------------------------------------------------------

class _FakeContext:
    def route(self, *args, **kwargs):
        pass

    def on(self, *args, **kwargs):
        pass


class _FakePage:
    def __init__(self):
        self.context = _FakeContext()
        self.url = "about:blank"

    def on(self, *args, **kwargs):
        pass


class _FakeRequest:
    def __init__(self, url):
        self.url = url


class _FakeRoute:
    def __init__(self, url):
        self.request = _FakeRequest(url)
        self.status = 200
        self.payload = None

    def fulfill(self, status=200, json=None, **kwargs):
        self.status = status
        self.payload = json


def drive_fixture(fixture, method, path, body=None, query=None):
    """Dispatch one request through the fixture exactly as its Playwright route handler would, and
    return the fulfilled (status, payload)."""
    entry = ApiRequest(method=method, path=path, query=query or {}, body=body)
    route = _FakeRoute(f"{ORIGIN}{path}")
    fixture._dispatch(route, entry)
    return route.status, route.payload


def new_fixture():
    return GroupAgentsFixture(_FakePage())


def agents_path(group_id=GROUP_A, agent_id=None):
    base = f"/api/groups/{group_id}/agents"
    return f"{base}/{agent_id}" if agent_id else base


# --------------------------------------------------------------------------
# Parity assertions, mirroring the file source and endpoint parity tests.
# --------------------------------------------------------------------------

def assert_no_invented_keys(scenario, fixture_payload, real_payload):
    invented = set(fixture_payload) - set(real_payload)
    assert not invented, (
        f"{scenario}: the fixture returns keys the server never does: {sorted(invented)} "
        f"(server keys {sorted(real_payload)})"
    )


def assert_shared_keys(scenario, fixture_payload, real_payload, required):
    for key in required:
        assert key in real_payload, f"{scenario}: the server no longer returns {key!r}; the harness or contract drifted"
        assert key in fixture_payload, f"{scenario}: the fixture dropped {key!r}, which the UI reads"


def assert_nested_parity(scenario, fixture_obj, real_obj, ui_keys):
    assert_no_invented_keys(scenario, fixture_obj, real_obj)
    assert_shared_keys(scenario, fixture_obj, real_obj, ui_keys)


def assert_error_parity(scenario, status, payload, real, expected_status):
    """The same status, the same keys, no error_code on either side, and the server's own text."""
    real_payload = real.get_json()
    assert (status, real.status_code) == (expected_status, expected_status), (
        f"{scenario}: fixture {status}, server {real.status_code}"
    )
    assert_no_invented_keys(scenario, payload, real_payload)
    assert_shared_keys(scenario, payload, real_payload, {"error"})
    assert payload.get("error_code") is None and real_payload.get("error_code") is None, (
        f"{scenario}: error_code fixture {payload.get('error_code')!r}, server {real_payload.get('error_code')!r}"
    )
    assert payload["error"] == real_payload["error"], (
        f"{scenario}: the editor renders this text verbatim -- fixture {payload['error']!r}, "
        f"server {real_payload['error']!r}"
    )


def by_id(rows):
    return {row["id"]: row for row in rows}


# --------------------------------------------------------------------------
# The real code the harness seams stand in for.
# --------------------------------------------------------------------------

def _load_module(monkeypatch, name):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def agent_payload(environment, monkeypatch):  # noqa: F811 - the imported harness fixture
    """The real ``functions_agent_payload``, loaded for this test only."""
    _load_module(monkeypatch, "functions_icon_utils")
    return _load_module(monkeypatch, "functions_agent_payload")


def stored_agent(agent_payload, row, *, group_id=GROUP_A, is_global=False):
    """A stored agent as the real preparer and engine would write it for this projected row."""
    agent = {key: deepcopy(value) for key, value in row.items() if key not in PROJECTION_KEYS}
    stored = agent_payload.sanitize_agent_payload(agent)
    stored["is_global"] = is_global
    stored["is_group"] = not is_global
    if not is_global:
        stored["group_id"] = group_id
    stored.update({
        "created_at": "2026-01-01T00:00:00Z", "created_by": "owner",
        "modified_at": "2026-01-01T00:00:00Z", "modified_by": "owner",
    })
    return stored


def fixture_row(fixture, group_id, agent_id):
    """The fixture's stored row, unmasked, as it would seed a real store."""
    return deepcopy(fixture.record_agent(group_id, agent_id))


def seed_server_from_fixture(env, agent_payload, fixture, group_id, agent_ids):
    for agent_id in agent_ids:
        row = fixture_row(fixture, group_id, agent_id)
        if row.get("is_global"):
            env.global_container.create_item(stored_agent(agent_payload, row, is_global=True))
        else:
            env.group_container.create_item(stored_agent(agent_payload, row, group_id=group_id))


def closer_prepare(agent_payload):
    """The real preparer's sanitize step and group flags, without its knowledge, schema and
    delegation checks, none of which adds or removes a record key."""
    def prepare(user_id, group_id, agent, settings, existing):
        try:
            cleaned = agent_payload.sanitize_agent_payload(agent)
        except agent_payload.AgentPayloadError as error:
            return None, (jsonify({"error": str(error)}), 400)
        cleaned["is_global"] = False
        cleaned["is_group"] = True
        return cleaned, None
    return prepare


class _DocumentsContainer:
    """A group documents container answering the catalogue's parameterized query."""

    def __init__(self, documents):
        self.documents = documents

    def query_items(self, query, parameters=None, enable_cross_partition_query=None):
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        return [deepcopy(item) for item in self.documents if item.get("group_id") == values.get("@group_id")]


def real_catalog_builder(env, documents):
    """The real catalogue builder, serializer and tag normalization over seeded group documents."""
    source = (APP_ROOT / "functions_assigned_knowledge.py").read_text(encoding="utf-8")
    limit = next(
        ast.literal_eval(node.value) for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "ASSIGNED_KNOWLEDGE_CATALOG_DOCUMENT_LIMIT"
                for target in node.targets)
    )
    namespace = {
        "Any": Any, "Dict": Dict, "List": List, "Optional": Optional, "logging": logging,
        "log_event": Mock(), "ASSIGNED_KNOWLEDGE_CATALOG_DOCUMENT_LIMIT": limit,
        "find_group_by_id": lambda group_id: deepcopy(env.groups.get(group_id)),
        "cosmos_group_documents_container": _DocumentsContainer(documents),
        "cosmos_user_documents_container": _DocumentsContainer([]),
        "cosmos_public_documents_container": _DocumentsContainer([]),
        "get_all_public_workspaces": lambda: [],
        # Passthrough seams: none adds or removes a catalogue key for an unscreened document.
        "document_provenance": lambda document: {},
        "public_document_payload": lambda document: document,
        "PROVENANCE_FIELD": "content_provenance",
        "select_current_documents": lambda documents: list(documents),
        "sort_documents": lambda documents, *args, **kwargs: list(documents),
    }
    execute_functions("functions_documents.py", {"normalize_tag", "sanitize_tags_for_filter"}, namespace)
    execute_functions("functions_assigned_knowledge.py", {
        "build_assigned_knowledge_catalog", "_serialize_catalog_document", "_append_tag_counts",
        "_get_personal_catalog_documents", "_get_group_catalog_documents",
        "_get_public_catalog_documents", "_public_workspace_source_map", "_query_documents",
    }, namespace)
    return namespace["build_assigned_knowledge_catalog"]


@pytest.fixture(scope="module")
def real_option_endpoints():
    """The group agent options' model endpoints exactly as the real pipeline projects them.

    The global and group endpoints mirror the fixture's: a global Azure OpenAI connection with one
    chat deployment, and a global and a group Foundry connection. They run through the real
    ``build_combined_model_endpoints`` and the options builder's own capability filter and second
    sanitize pass, in the endpoint harness that loads the real settings module.
    """
    with group_endpoint_environment() as endpoint_env:
        endpoint_env.reset()
        settings_module = endpoint_env.modules.settings
        ai_connections = importlib.import_module("functions_ai_connections")
        workspace_model = aoai_endpoint("workspace-model-endpoint", name="Workspace model endpoint", models=[{
            "id": "workspace-model", "deploymentName": "workspace-gpt", "modelName": "gpt-4o",
            "displayName": "Workspace GPT", "enabled": True,
        }])
        global_foundry = foundry_endpoint(GLOBAL_FOUNDRY_ENDPOINT_ID, name="Global Foundry connection", models=[])
        group_foundry = foundry_endpoint(GROUP_FOUNDRY_ENDPOINT_ID, name="Group Foundry connection", models=[])
        endpoint_env.settings["model_endpoints"] = settings_module.normalize_model_endpoints(
            [workspace_model, global_foundry],
        )[0]
        endpoint_env.seed_group_with_legacy_endpoints(GROUP_A, [group_foundry])
        namespace = {
            "ensure_governance_access": endpoint_env._ensure_governance_access,
            "get_group_model_endpoints": endpoint_env.modules.group.get_group_model_endpoints,
            "get_user_settings": settings_module.get_user_settings,
            "sanitize_model_endpoints_for_frontend": settings_module.sanitize_model_endpoints_for_frontend,
            "filter_model_endpoints_by_capability": ai_connections.filter_model_endpoints_by_capability,
        }
        execute_functions("route_backend_agents.py", {"build_combined_model_endpoints"}, namespace)
        combined = namespace["build_combined_model_endpoints"](endpoint_env.settings, "owner", group_id=GROUP_A)
        projected = settings_module.sanitize_settings_for_user({
            "model_endpoints": ai_connections.filter_model_endpoints_by_capability(combined, preserve_empty=True),
        }).get("model_endpoints", [])
        return json.loads(json.dumps(projected))


@pytest.fixture
def modelled(environment, agent_payload, real_option_endpoints, monkeypatch):  # noqa: F811
    """The family harness, configured as the fixture models it, with the real code in its seams."""
    environment.settings.update(MODELLED_SETTINGS)
    environment.routes["_prepare_group_agent_payload"] = closer_prepare(agent_payload)
    monkeypatch.setattr(
        sys.modules["route_backend_agents"], "build_combined_model_endpoints",
        lambda settings, user_id, group_id=None: deepcopy(real_option_endpoints),
    )
    environment.agent_payload = agent_payload
    return environment


def seed_group_a(env, fixture):
    seed_server_from_fixture(env, env.agent_payload, fixture, GROUP_A, [
        EDITABLE_AGENT_ID, WITHHELD_AGENT_ID, FOUNDRY_AGENT_ID, PROVIDED_AGENT_ID,
    ])


# --------------------------------------------------------------------------
# List and read.
# --------------------------------------------------------------------------

def test_list_shape_parity(modelled):
    """The list envelope and every row: group rows, a Foundry row and the merged provided row."""
    fixture = new_fixture()
    seed_group_a(modelled, fixture)
    as_user(modelled, "owner")
    real = modelled.client.get(LIST_PATH)
    status, payload = drive_fixture(fixture, "GET", LIST_PATH)

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("list", payload, real_payload)
    assert_shared_keys("list", payload, real_payload, {"agents"})
    served, stored = by_id(payload["agents"]), by_id(real_payload["agents"])
    assert set(served) == set(stored)
    for agent_id in (EDITABLE_AGENT_ID, WITHHELD_AGENT_ID, FOUNDRY_AGENT_ID):
        assert_nested_parity(f"list row {agent_id}", served[agent_id], stored[agent_id], GROUP_AGENT_UI_KEYS)
        for key in ("group_id", "is_global", "is_group"):
            assert served[agent_id][key] == stored[agent_id][key], (agent_id, key)
    assert_nested_parity("list provided row", served[PROVIDED_AGENT_ID], stored[PROVIDED_AGENT_ID], AGENT_UI_KEYS)
    for key in ("is_global", "is_group", "agent_actions"):
        assert served[PROVIDED_AGENT_ID][key] == stored[PROVIDED_AGENT_ID][key], key
    # The server gives every group agent the same per-agent operations for an active writer.
    for agent_id in (EDITABLE_AGENT_ID, FOUNDRY_AGENT_ID):
        assert served[agent_id]["agent_actions"] == stored[agent_id]["agent_actions"] == ["edit", "delete", "chat"]
    # The withheld row is a deliberate client-robustness state the server never produces: the
    # policy grants every group agent the writer's operations, so the browser suite uses it only
    # to prove the per-agent gate hides what a row does not carry.
    assert served[WITHHELD_AGENT_ID]["agent_actions"] == []
    assert stored[WITHHELD_AGENT_ID]["agent_actions"] == ["edit", "delete", "chat"]
    assert served[EDITABLE_AGENT_ID]["other_settings"]["connection"]["api_key"] == SECRET_MASK
    assert stored[EDITABLE_AGENT_ID]["other_settings"]["connection"]["api_key"] == SECRET_MASK


def test_member_list_shape_parity(modelled):
    """A member's list: the row carries only `chat`."""
    fixture = new_fixture()
    seed_server_from_fixture(modelled, modelled.agent_payload, fixture, GROUP_B, [MEMBER_AGENT_ID])
    as_user(modelled, "member")
    real = modelled.client.get(agents_path(GROUP_B))
    status, payload = drive_fixture(fixture, "GET", agents_path(GROUP_B))

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("member list", payload, real_payload)
    served, stored = by_id(payload["agents"]), by_id(real_payload["agents"])
    assert set(served) == set(stored) == {MEMBER_AGENT_ID}
    assert_nested_parity("member list row", served[MEMBER_AGENT_ID], stored[MEMBER_AGENT_ID], GROUP_AGENT_UI_KEYS)
    assert served[MEMBER_AGENT_ID]["agent_actions"] == stored[MEMBER_AGENT_ID]["agent_actions"] == ["chat"]


def assert_envelope_parity(scenario, payload, real_payload, ui_keys=GROUP_AGENT_UI_KEYS):
    assert_no_invented_keys(scenario, payload, real_payload)
    assert_shared_keys(scenario, payload, real_payload, ENVELOPE_UI_KEYS)
    assert_nested_parity(f"{scenario} record", payload["record"], real_payload["record"], ui_keys)
    assert isinstance(payload["revision"], str) and payload["revision"]
    assert isinstance(real_payload["revision"], str) and real_payload["revision"]
    assert sorted(payload["secret_paths"]) == sorted(real_payload["secret_paths"]), scenario
    assert payload["read_only"] == real_payload["read_only"], scenario
    assert payload["record"]["agent_actions"] == real_payload["record"]["agent_actions"], scenario


def test_read_shape_parity(modelled):
    """A writer's read: the editor resource with its masked stored credential."""
    fixture = new_fixture()
    seed_group_a(modelled, fixture)
    as_user(modelled, "owner")
    real = modelled.client.get(agents_path(agent_id=EDITABLE_AGENT_ID))
    status, payload = drive_fixture(fixture, "GET", agents_path(agent_id=EDITABLE_AGENT_ID))

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_envelope_parity("read", payload, real_payload)
    assert payload["read_only"] is False
    assert payload["secret_paths"] == ["/other_settings/connection/api_key"]


def test_member_read_shape_parity(modelled):
    """A member's read is read-only, with only `chat`."""
    fixture = new_fixture()
    seed_server_from_fixture(modelled, modelled.agent_payload, fixture, GROUP_B, [MEMBER_AGENT_ID])
    as_user(modelled, "member")
    real = modelled.client.get(agents_path(GROUP_B, MEMBER_AGENT_ID))
    status, payload = drive_fixture(fixture, "GET", agents_path(GROUP_B, MEMBER_AGENT_ID))

    assert (status, real.status_code) == (200, 200)
    assert_envelope_parity("member read", payload, real.get_json())
    assert payload["read_only"] is True


def test_provided_read_shape_parity(modelled):
    """A merged provided agent opens read-only through the group route, with no operations."""
    fixture = new_fixture()
    seed_group_a(modelled, fixture)
    as_user(modelled, "owner")
    real = modelled.client.get(agents_path(agent_id=PROVIDED_AGENT_ID))
    status, payload = drive_fixture(fixture, "GET", agents_path(agent_id=PROVIDED_AGENT_ID))

    assert (status, real.status_code) == (200, 200)
    assert_envelope_parity("provided read", payload, real.get_json(), AGENT_UI_KEYS)
    assert payload["read_only"] is True and payload["record"]["agent_actions"] == []


# --------------------------------------------------------------------------
# Writes and the stale revision conflict.
# --------------------------------------------------------------------------

def create_request():
    return {
        "updates": {
            "id": str(uuid.uuid4()), "name": "release-reviewer", "display_name": "Release reviewer",
            "description": "Reviews release notes.", "instructions": "Be precise.", "agent_type": "local",
            "actions_to_load": [], "other_settings": {}, "max_completion_tokens": -1,
            "model_endpoint_id": "workspace-model-endpoint", "model_id": "workspace-model",
            "model_provider": "aoai", "azure_openai_gpt_deployment": "workspace-gpt",
        },
        "clear_secret_paths": [],
        "removed_paths": [],
    }


def test_create_shape_parity(modelled):
    """A create answers 201 with the editor resource for the new agent."""
    as_user(modelled, "owner")
    body = create_request()
    real = modelled.client.post(LIST_PATH, json=body)
    status, payload = drive_fixture(new_fixture(), "POST", LIST_PATH, body=deepcopy(body))

    assert (status, real.status_code) == (201, 201), real.get_json()
    real_payload = real.get_json()
    assert_envelope_parity("create", payload, real_payload)
    assert payload["read_only"] is False
    assert payload["record"]["id"] == real_payload["record"]["id"] == body["updates"]["id"]


def update_request(revision, **updates):
    return {
        "updates": updates or {"display_name": "Weekly reviewer (renamed)"},
        "expected_revision": revision,
        "clear_secret_paths": [],
        "removed_paths": [],
    }


def real_revision(env, agent_id, group_id=GROUP_A):
    return env.client.get(agents_path(group_id, agent_id)).get_json()["revision"]


def test_update_shape_parity(modelled):
    """A conditional update answers 200 with the updated resource and keeps the stored key masked."""
    fixture = new_fixture()
    seed_group_a(modelled, fixture)
    as_user(modelled, "owner")
    real = modelled.client.patch(
        agents_path(agent_id=EDITABLE_AGENT_ID), json=update_request(real_revision(modelled, EDITABLE_AGENT_ID)),
    )
    status, payload = drive_fixture(
        fixture, "PATCH", agents_path(agent_id=EDITABLE_AGENT_ID),
        body=update_request(fixture._agent_revision(GROUP_A, EDITABLE_AGENT_ID)),
    )

    assert (status, real.status_code) == (200, 200), real.get_json()
    real_payload = real.get_json()
    assert_envelope_parity("update", payload, real_payload)
    assert payload["record"]["display_name"] == real_payload["record"]["display_name"] == "Weekly reviewer (renamed)"


def test_stale_revision_shape_parity(modelled):
    """A stale revision is a 409 with nothing written, and the same body from both."""
    fixture = new_fixture()
    seed_group_a(modelled, fixture)
    as_user(modelled, "owner")
    real = modelled.client.patch(agents_path(agent_id=EDITABLE_AGENT_ID), json=update_request('"stale-etag"'))
    fixture.touch_agent(GROUP_A, EDITABLE_AGENT_ID)
    status, payload = drive_fixture(
        fixture, "PATCH", agents_path(agent_id=EDITABLE_AGENT_ID), body=update_request("stale-revision"),
    )
    assert_error_parity("stale revision", status, payload, real, 409)


def test_delete_shape_parity(modelled):
    """A delete answers `{success: true}` from both."""
    fixture = new_fixture()
    seed_group_a(modelled, fixture)
    as_user(modelled, "owner")
    real = modelled.client.delete(agents_path(agent_id=EDITABLE_AGENT_ID))
    status, payload = drive_fixture(fixture, "DELETE", agents_path(agent_id=EDITABLE_AGENT_ID))

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert set(payload) == set(real_payload) == {"success"}
    assert payload["success"] is True and real_payload["success"] is True


# --------------------------------------------------------------------------
# The refusals the editor renders verbatim.
# --------------------------------------------------------------------------

def test_unknown_agent_shape_parity(modelled):
    as_user(modelled, "owner")
    real = modelled.client.get(agents_path(agent_id="missing-agent"))
    status, payload = drive_fixture(new_fixture(), "GET", agents_path(agent_id="missing-agent"))
    assert_error_parity("unknown agent", status, payload, real, 404)


@pytest.mark.parametrize("path", [LIST_PATH, OPTIONS_PATH, KNOWLEDGE_PATH], ids=["list", "options", "knowledge"])
def test_non_member_shape_parity(modelled, path):
    as_user(modelled, "outsider")
    real = modelled.client.get(path)
    fixture = new_fixture()
    fixture.denied_groups.add(GROUP_A)
    status, payload = drive_fixture(fixture, "GET", path)
    assert_error_parity("non-member", status, payload, real, 403)


@pytest.mark.parametrize("path", [LIST_PATH, OPTIONS_PATH, KNOWLEDGE_PATH], ids=["list", "options", "knowledge"])
def test_query_parameter_shape_parity(modelled, path):
    as_user(modelled, "owner")
    real = modelled.client.get(path, query_string={"page": "1"})
    status, payload = drive_fixture(new_fixture(), "GET", path, query={"page": ["1"]})
    assert_error_parity("query parameter", status, payload, real, 400)


SECRET_REFUSALS = {
    # A mask where nothing is stored: the Foundry agent carries no connection key.
    "mask without a stored secret": (FOUNDRY_AGENT_ID, {
        "updates": {"other_settings": {"connection": {"api_key": SECRET_MASK}}},
        "clear_secret_paths": [], "removed_paths": [],
    }),
    "clear of a field that is not a secret": (EDITABLE_AGENT_ID, {
        "updates": {}, "clear_secret_paths": ["/description"], "removed_paths": [],
    }),
    "clear and remove of the same field": (EDITABLE_AGENT_ID, {
        "updates": {}, "clear_secret_paths": ["/other_settings/connection/api_key"],
        "removed_paths": ["/other_settings/connection/api_key"],
    }),
    "emptied stored secret": (EDITABLE_AGENT_ID, {
        "updates": {"other_settings": {"connection": {"api_key": ""}}},
        "clear_secret_paths": [], "removed_paths": [],
    }),
    "removed configuration holding a stored secret": (EDITABLE_AGENT_ID, {
        "updates": {}, "clear_secret_paths": [], "removed_paths": ["/other_settings/connection"],
    }),
}


@pytest.mark.parametrize("case", list(SECRET_REFUSALS))
def test_secret_refusal_shape_parity(modelled, case):
    """Each stored-credential refusal is a 400 carrying the server's own sentence."""
    agent_id, request_body = SECRET_REFUSALS[case]
    fixture = new_fixture()
    seed_group_a(modelled, fixture)
    as_user(modelled, "owner")
    real = modelled.client.patch(
        agents_path(agent_id=agent_id), json={**deepcopy(request_body), "expected_revision": real_revision(modelled, agent_id)},
    )
    status, payload = drive_fixture(fixture, "PATCH", agents_path(agent_id=agent_id), body={
        **deepcopy(request_body), "expected_revision": fixture._agent_revision(GROUP_A, agent_id),
    })
    assert_error_parity(case, status, payload, real, 400)


# --------------------------------------------------------------------------
# Editor options and assigned knowledge.
# --------------------------------------------------------------------------

def assert_options_parity(scenario, payload, real_payload):
    assert_no_invented_keys(scenario, payload, real_payload)
    assert_shared_keys(scenario, payload, real_payload, OPTIONS_UI_KEYS)
    served_types, real_types = payload["agent_types"], real_payload["agent_types"]
    assert [item["value"] for item in served_types] == [item["value"] for item in real_types]
    for served, stored in zip(served_types, real_types):
        assert_nested_parity(f"{scenario} agent type {stored['value']}", served, stored, AGENT_TYPE_UI_KEYS)
        assert served == stored, f"{scenario}: agent type {stored['value']}"
    assert_nested_parity(f"{scenario} settings", payload["settings"], real_payload["settings"], SETTINGS_UI_KEYS)
    for key in SETTINGS_UI_KEYS:
        assert payload["settings"][key] == real_payload["settings"][key], f"{scenario}: settings.{key}"
    assert payload["builtin_actions"] == real_payload["builtin_actions"], scenario
    for served in payload["builtin_actions"]:
        assert set(served) == BUILTIN_UI_KEYS
    served_endpoints, real_endpoints = by_id(payload["model_endpoints"]), by_id(real_payload["model_endpoints"])
    assert set(served_endpoints) == set(real_endpoints), scenario
    for endpoint_id, served in served_endpoints.items():
        stored = real_endpoints[endpoint_id]
        assert_nested_parity(f"{scenario} endpoint {endpoint_id}", served, stored, ENDPOINT_UI_KEYS)
        for key in ("scope", "provider", "enabled", "name"):
            assert served[key] == stored[key], f"{scenario}: endpoint {endpoint_id}.{key}"
        assert [model["id"] for model in served["models"]] == [model["id"] for model in stored["models"]]
        for served_model, stored_model in zip(served["models"], stored["models"]):
            assert_nested_parity(f"{scenario} model {served_model['id']}", served_model, stored_model, MODEL_UI_KEYS)
            # The picker skips a deployment whose chat capability is unavailable.
            served_chat, stored_chat = served_model["capability_status"]["chat"], stored_model["capability_status"]["chat"]
            assert_nested_parity(f"{scenario} model chat capability", served_chat, stored_chat, {"available"})
            assert served_chat == {key: stored_chat[key] for key in served_chat}, scenario


def test_manager_options_shape_parity(modelled):
    """A writer's options: every type, the endpoints the editor can bind, and the builtins."""
    as_user(modelled, "owner")
    real = modelled.client.get(OPTIONS_PATH)
    status, payload = drive_fixture(new_fixture(), "GET", OPTIONS_PATH)
    assert (status, real.status_code) == (200, 200)
    assert_options_parity("manager options", payload, real.get_json())


def test_member_options_shape_parity(modelled):
    """A member's options: no types to author, no models and no builtins."""
    as_user(modelled, "member")
    real = modelled.client.get(f"/api/groups/{GROUP_B}/agent-options")
    status, payload = drive_fixture(new_fixture(), "GET", f"/api/groups/{GROUP_B}/agent-options")
    assert (status, real.status_code) == (200, 200)
    assert_options_parity("member options", payload, real.get_json())


def test_knowledge_shape_parity(modelled, monkeypatch):
    """The catalogue for a group names the group, and only the group, as its source."""
    documents = [{
        "id": f"{GROUP_A}-brief", "title": "Group review brief", "file_name": "group-brief.pdf",
        "group_id": GROUP_A, "tags": ["finance"],
    }]
    monkeypatch.setattr(
        sys.modules["functions_assigned_knowledge"], "build_assigned_knowledge_catalog",
        real_catalog_builder(modelled, documents),
    )
    as_user(modelled, "owner")
    real = modelled.client.get(KNOWLEDGE_PATH)
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "GET", KNOWLEDGE_PATH)

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("knowledge", payload, real_payload)
    assert_shared_keys("knowledge", payload, real_payload, CATALOG_UI_KEYS)
    for key, ui_keys in (("sources", SOURCE_UI_KEYS), ("documents", DOCUMENT_UI_KEYS), ("tags", TAG_UI_KEYS)):
        assert payload[key] and real_payload[key], key
        for served in payload[key]:
            assert_nested_parity(f"knowledge {key}", served, real_payload[key][0], ui_keys)
    # A group catalogue offers the group alone, labelled with its name: never a public source.
    assert [(source["scope"], source["id"]) for source in payload["sources"]] == [("group", GROUP_A)]
    assert [(source["scope"], source["id"]) for source in real_payload["sources"]] == [("group", GROUP_A)]
    assert real_payload["sources"][0]["label"] == modelled.groups[GROUP_A]["name"]
    assert payload["sources"][0]["label"] == fixture.groups[GROUP_A]["workspace"]["name"]
    assert {document["scope"] for document in payload["documents"]} == {"group"}
    assert all(tag["name"] == tag["name"].lower() for tag in payload["tags"]), "The server normalizes tags."
    assert all(tag == tag.lower() for document in payload["documents"] for tag in document["tags"])


# --------------------------------------------------------------------------
# Product finding, reported for the coordinator's decision (R3).
# --------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason=(
    "Product finding: the group agent workbench offers 'public' as an assignable knowledge scope "
    "(agentWorkbench.ts, knowledgeScopes: ['group', 'public']), but the server never lists a public "
    "source in a group catalogue, and _enforce_scope_policy stores no public workspace for a group "
    "agent. The old fixture hid this by inventing a public source. Awaiting the coordinator's call."
))
def test_group_agent_knowledge_scopes_are_the_ones_the_server_stores():
    """The group editor should offer exactly the knowledge scopes a group agent can keep."""
    source = (ROOT / "application" / "v2_ui" / "src" / "lib" / "agentWorkbench.ts").read_text(encoding="utf-8")
    group_adapter = source[source.index("export function createGroupAgentWorkbench"):]
    listed = re.search(r"knowledgeScopes:\s*\[([^\]]*)\]", group_adapter).group(1)
    offered = {scope.strip().strip("'\"") for scope in listed.split(",") if scope.strip()}
    namespace = {"Any": Any, "Dict": Dict, "Optional": Optional, "AssignedKnowledgeError": ValueError}
    execute_functions("functions_assigned_knowledge.py", {"_enforce_scope_policy"}, namespace)
    kept = namespace["_enforce_scope_policy"](
        {"personal": True, "group_ids": ["another-group"], "public_workspace_ids": ["public-handbook"]},
        agent_scope="group", group_id=GROUP_A,
    )
    storable = {"group"} | ({"public"} if kept["public_workspace_ids"] else set()) | ({"personal"} if kept["personal"] else set())
    assert offered == storable, f"the editor offers {sorted(offered)}; a group agent keeps {sorted(storable)}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
