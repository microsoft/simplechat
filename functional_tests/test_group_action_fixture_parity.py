# test_group_action_fixture_parity.py
"""
Per-route shape parity between the M4 group action UI fixture and the real routes.
Version: 0.261.161
Implemented in: 0.261.161

The V2 group Actions workbench and its editor mock the network with the closed HTTP fixture
``ui_tests/fixtures/group_actions.py``, whose dispatch lives in the shared
``ui_tests/fixtures/group_workspace.py`` base. A fixture whose response shape drifts from the
server lets a passing browser suite hide a real regression. The M4 action fixtures predate the
per-route parity rule, so this test backfills the pin.

For every native route the action workbench (``lib/actionWorkbench.ts``) and its editor call --
list, read, create, update, delete, the ``actions/types`` catalogue and ``action-options``, plus
the stale revision conflict and each refusal the editor renders -- it asserts that the fixture
never invents a top-level, record, catalogue or reminder key the server does not return
(``fixture keys <= server keys``), that the keys the UI reads are present on both sides, that the
status code and the machine-readable ``error_code`` match (the action routes send none, so its
absence is pinned), and that every message the editor renders verbatim is the server's own.

The real routes run through ``test_support/group_action_harness.py``, the family API suite's
harness, with the deployment the fixture models (global actions merged in). The stored actions
are the fixture's own rows: they already carry every field the real preparer defaults (name,
display name, description, type, endpoint, auth, additional fields and metadata) and only fields
the plugin schema allows, so the real projection answers with exactly the keys a real stored
action has. Writes go through the harness's preparer stand-in, which applies the same defaults.
The type catalogue replaces the harness's stand-in with the real ``build_action_editor_types``
over the real type and auth resolution from ``json_schema_validation``; plugin discovery itself
imports every connector module, so the discovered names are the fixture's own.

The fixture handlers are the production browser-test code, exercised through the same
``_dispatch`` entry the Playwright route handler calls, with a tiny fake page and route that only
capture the fulfilled status and JSON. The reusable identities the editor lists are pinned by
``test_group_identity_fixture_parity.py``; the per-type connection tests are shared plugin routes
outside this family.
"""

import json
import os
import re
import sys
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest
from flask import jsonify

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN, SECRET_MASK  # noqa: E402
from ui_tests.fixtures.group_actions import (  # noqa: E402
    EDITABLE_ACTION_ID, IDENTITY_ACTION_ID, MCP_ACTION_ID, MEMBER_ACTION_ID, PROVIDED_ACTION_ID,
    WITHHELD_ACTION_ID, GroupActionsFixture,
)

from test_support.agent_delegation import APP_ROOT, execute_functions  # noqa: E402
from test_support.group_action_harness import (  # noqa: E402,F401  (environment is a pytest fixture)
    LIST_PATH, OPTIONS_PATH, as_user, environment,
)


GROUP_A = "group-a"
GROUP_B = "group-b"
TYPES_PATH = f"{LIST_PATH}/types"

# The deployment the action fixture models: provided (global) actions merged into the group list.
MODELLED_SETTINGS = {"merge_global_semantic_kernel_with_workspace": True}

# The record keys the workbench, its gates and the editor read: identity and presentation in the
# collection, the connector fields the editor edits, `group_id` and `action_actions` for the
# per-action gates, and `is_global` for the provided-row scope check.
ACTION_UI_KEYS = {
    "id", "name", "displayName", "description", "type", "endpoint", "auth", "additionalFields",
    "metadata", "is_global", "action_actions",
}
GROUP_ACTION_UI_KEYS = ACTION_UI_KEYS | {"group_id"}
ENVELOPE_UI_KEYS = {"record", "revision", "secret_paths", "read_only"}
# `groupEditorHints` validates the reminder block strictly, field by field.
REMINDER_UI_KEYS = {"storage_enabled", "reminders_enabled", "require_expiration", "lead_days", "contact_email"}
TYPE_UI_KEYS = {"type", "display", "description", "allowed_auth_types", "additional_fields_schema", "metadata_schema"}
# The one catalogue type the fixture invents on purpose: a server-discovered connector that is not
# hardcoded in the browser, with a field schema of its own.
MODELLED_CUSTOM_TYPE = "fixture_custom"
# Keys only the projection owns, so a stored record never carries them.
PROJECTION_KEYS = {"action_actions", "is_global", "is_group"}


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
    return GroupActionsFixture(_FakePage())


def actions_path(group_id=GROUP_A, action_id=None):
    base = f"/api/groups/{group_id}/actions"
    return f"{base}/{action_id}" if action_id else base


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
# Seeding the real store from the fixture's rows, and the real type catalogue.
# --------------------------------------------------------------------------

def stored_action(row, *, group_id=GROUP_A, is_global=False):
    """A stored action for this projected row: the projection's own keys removed, and the scope and
    audit fields the engine writes added."""
    stored = {key: deepcopy(value) for key, value in row.items() if key not in PROJECTION_KEYS | {"group_id"}}
    if not is_global:
        stored["group_id"] = group_id
    stored.update({
        "created_at": "2026-01-01T00:00:00Z", "created_by": "owner",
        "modified_at": "2026-01-01T00:00:00Z", "modified_by": "owner",
    })
    return stored


def seed_server_from_fixture(env, fixture, group_id, action_ids):
    for action_id in action_ids:
        row = deepcopy(fixture.record(group_id, action_id))
        if row.get("is_global"):
            env.global_container.create_item(stored_action(row, is_global=True))
        else:
            env.group_container.create_item(stored_action(row, group_id=group_id))


def seed_group_a(env, fixture):
    seed_server_from_fixture(env, fixture, GROUP_A, [
        EDITABLE_ACTION_ID, WITHHELD_ACTION_ID, IDENTITY_ACTION_ID, MCP_ACTION_ID, PROVIDED_ACTION_ID,
    ])


def real_type_resolution():
    """The real per-type definition name, auth types and schema directory `build_action_editor_types`
    reads from ``json_schema_validation``."""
    namespace = {
        "re": re, "os": os, "json": json, "lru_cache": lru_cache,
        "SCHEMA_DIR": str(APP_ROOT / "static" / "json" / "schemas"),
    }
    execute_functions("json_schema_validation.py", {
        "is_legacy_msgraph_type", "normalize_plugin_definition_type",
        "get_allowed_auth_types_for_plugin_type", "load_schema",
    }, namespace)
    return namespace


@pytest.fixture
def modelled(environment, monkeypatch):  # noqa: F811 - the imported harness fixture
    """The family harness, configured as the fixture models it, with the real type catalogue."""
    environment.settings.update(MODELLED_SETTINGS)
    resolution = real_type_resolution()
    validation = sys.modules["json_schema_validation"]
    for name in ("SCHEMA_DIR", "normalize_plugin_definition_type", "get_allowed_auth_types_for_plugin_type"):
        monkeypatch.setattr(validation, name, resolution[name], raising=False)
    discovered = [
        {"type": entry["type"], "display": entry["display"], "description": entry["description"]}
        for entry in new_fixture().types
    ]
    environment.routes["get_plugin_types"] = lambda allowed_type_filter=None: jsonify(discovered)
    environment.routes["build_action_editor_types"] = sys.modules["functions_workspace_authoring"].build_action_editor_types
    return environment


# --------------------------------------------------------------------------
# List and read.
# --------------------------------------------------------------------------

def test_list_shape_parity(modelled):
    """The list envelope and every row: key, identity-bound and MCP actions, and the provided row."""
    fixture = new_fixture()
    seed_group_a(modelled, fixture)
    as_user(modelled, "owner")
    real = modelled.client.get(LIST_PATH)
    status, payload = drive_fixture(fixture, "GET", LIST_PATH)

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("list", payload, real_payload)
    assert_shared_keys("list", payload, real_payload, {"actions"})
    served, stored = by_id(payload["actions"]), by_id(real_payload["actions"])
    assert set(served) == set(stored)
    for action_id in (EDITABLE_ACTION_ID, WITHHELD_ACTION_ID, IDENTITY_ACTION_ID, MCP_ACTION_ID):
        assert_nested_parity(f"list row {action_id}", served[action_id], stored[action_id], GROUP_ACTION_UI_KEYS)
        for key in ("group_id", "is_global", "is_group"):
            assert served[action_id][key] == stored[action_id][key], (action_id, key)
    assert_nested_parity("list provided row", served[PROVIDED_ACTION_ID], stored[PROVIDED_ACTION_ID], ACTION_UI_KEYS)
    for key in ("is_global", "is_group", "action_actions"):
        assert served[PROVIDED_ACTION_ID][key] == stored[PROVIDED_ACTION_ID][key], key
    # The server gives every group action the same per-action operations for an active writer.
    for action_id in (EDITABLE_ACTION_ID, IDENTITY_ACTION_ID, MCP_ACTION_ID):
        assert served[action_id]["action_actions"] == stored[action_id]["action_actions"] == ["edit", "delete", "test"]
    # The withheld row is a deliberate client-robustness state the server never produces: the
    # policy grants every group action the writer's operations, so the browser suite uses it only
    # to prove the per-action gate hides what a row does not carry.
    assert served[WITHHELD_ACTION_ID]["action_actions"] == []
    assert stored[WITHHELD_ACTION_ID]["action_actions"] == ["edit", "delete", "test"]
    assert served[EDITABLE_ACTION_ID]["auth"]["key"] == stored[EDITABLE_ACTION_ID]["auth"]["key"] == SECRET_MASK


def test_member_list_shape_parity(modelled):
    """A member's list: the row offers no operations."""
    fixture = new_fixture()
    seed_server_from_fixture(modelled, fixture, GROUP_B, [MEMBER_ACTION_ID])
    as_user(modelled, "member")
    real = modelled.client.get(actions_path(GROUP_B))
    status, payload = drive_fixture(fixture, "GET", actions_path(GROUP_B))

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("member list", payload, real_payload)
    served, stored = by_id(payload["actions"]), by_id(real_payload["actions"])
    assert set(served) == set(stored) == {MEMBER_ACTION_ID}
    assert_nested_parity("member list row", served[MEMBER_ACTION_ID], stored[MEMBER_ACTION_ID], GROUP_ACTION_UI_KEYS)
    assert served[MEMBER_ACTION_ID]["action_actions"] == stored[MEMBER_ACTION_ID]["action_actions"] == []


def assert_envelope_parity(scenario, payload, real_payload, ui_keys=GROUP_ACTION_UI_KEYS):
    assert_no_invented_keys(scenario, payload, real_payload)
    assert_shared_keys(scenario, payload, real_payload, ENVELOPE_UI_KEYS)
    assert_nested_parity(f"{scenario} record", payload["record"], real_payload["record"], ui_keys)
    assert isinstance(payload["revision"], str) and payload["revision"]
    assert isinstance(real_payload["revision"], str) and real_payload["revision"]
    assert sorted(payload["secret_paths"]) == sorted(real_payload["secret_paths"]), scenario
    assert payload["read_only"] == real_payload["read_only"], scenario
    assert payload["record"]["action_actions"] == real_payload["record"]["action_actions"], scenario


def test_read_shape_parity(modelled):
    """A writer's read: the editor resource with its masked stored key."""
    fixture = new_fixture()
    seed_group_a(modelled, fixture)
    as_user(modelled, "owner")
    real = modelled.client.get(actions_path(action_id=EDITABLE_ACTION_ID))
    status, payload = drive_fixture(fixture, "GET", actions_path(action_id=EDITABLE_ACTION_ID))

    assert (status, real.status_code) == (200, 200)
    assert_envelope_parity("read", payload, real.get_json())
    assert payload["read_only"] is False and payload["secret_paths"] == ["/auth/key"]


def test_identity_bound_read_shape_parity(modelled):
    """An identity-bound action stores no inline secret, so nothing is masked or registered."""
    fixture = new_fixture()
    seed_group_a(modelled, fixture)
    as_user(modelled, "owner")
    real = modelled.client.get(actions_path(action_id=IDENTITY_ACTION_ID))
    status, payload = drive_fixture(fixture, "GET", actions_path(action_id=IDENTITY_ACTION_ID))

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_envelope_parity("identity-bound read", payload, real_payload)
    assert payload["secret_paths"] == [] and payload["record"]["identity_id"] == real_payload["record"]["identity_id"]


def test_member_read_shape_parity(modelled):
    """A member's read is read-only, with no operations."""
    fixture = new_fixture()
    seed_server_from_fixture(modelled, fixture, GROUP_B, [MEMBER_ACTION_ID])
    as_user(modelled, "member")
    real = modelled.client.get(actions_path(GROUP_B, MEMBER_ACTION_ID))
    status, payload = drive_fixture(fixture, "GET", actions_path(GROUP_B, MEMBER_ACTION_ID))

    assert (status, real.status_code) == (200, 200)
    assert_envelope_parity("member read", payload, real.get_json())
    assert payload["read_only"] is True


def test_provided_read_shape_parity(modelled):
    """A merged provided action opens read-only through the group route, with no operations."""
    fixture = new_fixture()
    seed_group_a(modelled, fixture)
    as_user(modelled, "owner")
    real = modelled.client.get(actions_path(action_id=PROVIDED_ACTION_ID))
    status, payload = drive_fixture(fixture, "GET", actions_path(action_id=PROVIDED_ACTION_ID))

    assert (status, real.status_code) == (200, 200)
    assert_envelope_parity("provided read", payload, real.get_json(), ACTION_UI_KEYS)
    assert payload["read_only"] is True and payload["record"]["action_actions"] == []


# --------------------------------------------------------------------------
# Writes and the stale revision conflict.
# --------------------------------------------------------------------------

def create_request():
    """The write the editor sends for a new action: the server allocates the id."""
    return {
        "updates": {
            "name": "release-notes-api", "displayName": "Release notes API",
            "description": "Reads the release notes.", "type": "openapi",
            "endpoint": "https://releases.example.test/v1", "auth": {"type": "key", "key": "fixture-only-new-key"},
            "additionalFields": {}, "metadata": {},
        },
        "clear_secret_paths": [],
        "removed_paths": [],
    }


def test_create_shape_parity(modelled):
    """A create answers 201 with the editor resource, its new key masked and registered."""
    as_user(modelled, "owner")
    real = modelled.client.post(LIST_PATH, json=create_request())
    status, payload = drive_fixture(new_fixture(), "POST", LIST_PATH, body=create_request())

    assert (status, real.status_code) == (201, 201), real.get_json()
    real_payload = real.get_json()
    assert_envelope_parity("create", payload, real_payload)
    assert payload["read_only"] is False
    assert payload["record"]["auth"]["key"] == real_payload["record"]["auth"]["key"] == SECRET_MASK
    assert isinstance(payload["record"]["id"], str) and isinstance(real_payload["record"]["id"], str)


def update_request(revision, **updates):
    return {
        "updates": updates or {"displayName": "Weekly report API (renamed)"},
        "expected_revision": revision,
        "clear_secret_paths": [],
        "removed_paths": [],
    }


def real_revision(env, action_id, group_id=GROUP_A):
    return env.client.get(actions_path(group_id, action_id)).get_json()["revision"]


def test_update_shape_parity(modelled):
    """A conditional update answers 200 with the updated resource and keeps the stored key masked."""
    fixture = new_fixture()
    seed_group_a(modelled, fixture)
    as_user(modelled, "owner")
    real = modelled.client.patch(
        actions_path(action_id=EDITABLE_ACTION_ID), json=update_request(real_revision(modelled, EDITABLE_ACTION_ID)),
    )
    status, payload = drive_fixture(
        fixture, "PATCH", actions_path(action_id=EDITABLE_ACTION_ID),
        body=update_request(fixture._action_revision(GROUP_A, EDITABLE_ACTION_ID)),
    )

    assert (status, real.status_code) == (200, 200), real.get_json()
    real_payload = real.get_json()
    assert_envelope_parity("update", payload, real_payload)
    assert payload["record"]["displayName"] == real_payload["record"]["displayName"] == "Weekly report API (renamed)"


def test_stale_revision_shape_parity(modelled):
    """A stale revision is a 409 with nothing written, and the same body from both."""
    fixture = new_fixture()
    seed_group_a(modelled, fixture)
    as_user(modelled, "owner")
    real = modelled.client.patch(actions_path(action_id=EDITABLE_ACTION_ID), json=update_request('"stale-etag"'))
    fixture.touch_action(GROUP_A, EDITABLE_ACTION_ID)
    status, payload = drive_fixture(
        fixture, "PATCH", actions_path(action_id=EDITABLE_ACTION_ID), body=update_request("stale-revision"),
    )
    assert_error_parity("stale revision", status, payload, real, 409)


def test_delete_shape_parity(modelled):
    """A delete answers `{success: true}` from both."""
    fixture = new_fixture()
    seed_group_a(modelled, fixture)
    as_user(modelled, "owner")
    real = modelled.client.delete(actions_path(action_id=EDITABLE_ACTION_ID))
    status, payload = drive_fixture(fixture, "DELETE", actions_path(action_id=EDITABLE_ACTION_ID))

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert set(payload) == set(real_payload) == {"success"}
    assert payload["success"] is True and real_payload["success"] is True


# --------------------------------------------------------------------------
# The refusals the editor renders verbatim.
# --------------------------------------------------------------------------

def test_unknown_action_shape_parity(modelled):
    as_user(modelled, "owner")
    real = modelled.client.get(actions_path(action_id="missing-action"))
    status, payload = drive_fixture(new_fixture(), "GET", actions_path(action_id="missing-action"))
    assert_error_parity("unknown action", status, payload, real, 404)


@pytest.mark.parametrize("path", [LIST_PATH, TYPES_PATH, OPTIONS_PATH], ids=["list", "types", "options"])
def test_non_member_shape_parity(modelled, path):
    as_user(modelled, "outsider")
    real = modelled.client.get(path)
    fixture = new_fixture()
    fixture.denied_groups.add(GROUP_A)
    status, payload = drive_fixture(fixture, "GET", path)
    assert_error_parity("non-member", status, payload, real, 403)


@pytest.mark.parametrize("path", [LIST_PATH, TYPES_PATH, OPTIONS_PATH], ids=["list", "types", "options"])
def test_query_parameter_shape_parity(modelled, path):
    as_user(modelled, "owner")
    real = modelled.client.get(path, query_string={"view": "editor"})
    status, payload = drive_fixture(new_fixture(), "GET", path, query={"view": ["editor"]})
    assert_error_parity("query parameter", status, payload, real, 400)


SECRET_REFUSALS = {
    # A mask where nothing is stored: the identity-bound action carries no inline key.
    "mask without a stored secret": (IDENTITY_ACTION_ID, {
        "updates": {"auth": {"key": SECRET_MASK}}, "clear_secret_paths": [], "removed_paths": [],
    }),
    "clear of a field that is not a secret": (EDITABLE_ACTION_ID, {
        "updates": {}, "clear_secret_paths": ["/description"], "removed_paths": [],
    }),
    "clear and remove of the same field": (EDITABLE_ACTION_ID, {
        "updates": {}, "clear_secret_paths": ["/auth/key"], "removed_paths": ["/auth/key"],
    }),
    "emptied stored secret": (EDITABLE_ACTION_ID, {
        "updates": {"auth": {"key": ""}}, "clear_secret_paths": [], "removed_paths": [],
    }),
    "removed configuration holding a stored secret": (EDITABLE_ACTION_ID, {
        "updates": {}, "clear_secret_paths": [], "removed_paths": ["/auth"],
    }),
}


@pytest.mark.parametrize("case", list(SECRET_REFUSALS))
def test_secret_refusal_shape_parity(modelled, case):
    """Each stored-credential refusal is a 400 carrying the server's own sentence."""
    action_id, request_body = SECRET_REFUSALS[case]
    fixture = new_fixture()
    seed_group_a(modelled, fixture)
    as_user(modelled, "owner")
    real = modelled.client.patch(
        actions_path(action_id=action_id),
        json={**deepcopy(request_body), "expected_revision": real_revision(modelled, action_id)},
    )
    status, payload = drive_fixture(fixture, "PATCH", actions_path(action_id=action_id), body={
        **deepcopy(request_body), "expected_revision": fixture._action_revision(GROUP_A, action_id),
    })
    assert_error_parity(case, status, payload, real, 400)


# --------------------------------------------------------------------------
# The type catalogue and the editor options.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("user_id", ["owner", "member"])
def test_types_shape_parity(modelled, user_id):
    """Every member role reads the enriched catalogue; every type carries the server's auth types and
    schemas."""
    as_user(modelled, user_id)
    real = modelled.client.get(TYPES_PATH)
    status, payload = drive_fixture(new_fixture(), "GET", TYPES_PATH)

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("types", payload, real_payload)
    assert_shared_keys("types", payload, real_payload, {"types"})
    served, stored = {item["type"]: item for item in payload["types"]}, {item["type"]: item for item in real_payload["types"]}
    assert set(served) == set(stored)
    for action_type, item in served.items():
        assert_nested_parity(f"type {action_type}", item, stored[action_type], TYPE_UI_KEYS)
        # The editor offers exactly these credentials and renders exactly these field schemas.
        assert item["allowed_auth_types"] == stored[action_type]["allowed_auth_types"], f"type {action_type}"
        if action_type == MODELLED_CUSTOM_TYPE:
            # The fixture models a server-discovered connector whose schema files ship with the
            # deployment, not this repository, so only its keys and auth types are the server's here.
            continue
        for key in ("additional_fields_schema", "metadata_schema"):
            assert item[key] == stored[action_type][key], f"type {action_type}: {key}"


@pytest.mark.parametrize("user_id", ["owner", "member"])
def test_options_shape_parity(modelled, user_id):
    """Every member role reads the tenant reminder defaults, and nothing else."""
    as_user(modelled, user_id)
    real = modelled.client.get(OPTIONS_PATH)
    status, payload = drive_fixture(new_fixture(), "GET", OPTIONS_PATH)

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("options", payload, real_payload)
    assert_shared_keys("options", payload, real_payload, {"secret_reminders"})
    assert_nested_parity("options reminders", payload["secret_reminders"], real_payload["secret_reminders"], REMINDER_UI_KEYS)
    for key in REMINDER_UI_KEYS:
        assert type(payload["secret_reminders"][key]) is type(real_payload["secret_reminders"][key]), key


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
