# test_workflow_origin_provenance.py
#!/usr/bin/env python3
"""
Functional test for server-owned workflow provenance (``origin``).
Version: 0.261.207
Implemented in: 0.261.202
Edited-at-accept provenance: 0.261.207

This test ensures that the ``origin`` a chat orchestration create records on a workflow is
server-only. The two save routes, ``POST /api/user/workflows`` and ``POST /api/group/workflows``,
create and update workflows. Neither can set, change, reset or remove an origin, whether a
version 2 or version 3 definition carries it. An ordinary save preserves the stored origin, and
``edited`` becomes true, for good, only when the owner saves a material change, or from the
start when the owner changed a proposal in the editor before accepting it. The origin is
outside the definition revision and the Microsoft 365 execution fingerprint, so recording or
changing it never invalidates an editor's revision or a Run as approval (gotcha 15). A server
create happens at most once per proposal and never adopts or revives another workflow.

The route bodies are compiled from ``route_backend_workflows.py`` and call the real
``save_personal_workflow`` and ``save_group_workflow``. They run over the save parity harness,
which loads the real workflow modules, including the structured-flow modules a version 3 save
imports, over doubled I/O.
"""

import ast
import copy
import logging
import sys
import uuid
from pathlib import Path

import pytest
from flask import Flask, jsonify, request

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_workflow_draft_save_parity import (  # noqa: E402  (shared real-module save harness)
    CALENDAR_WEEKLY,
    GROUP_ID,
    OWNER_ID,
    SaveParityHarness,
    _task,
    _v2,
)


ROUTES_FILE = Path(__file__).resolve().parents[1] / "application" / "single_app" / "route_backend_workflows.py"
SCOPES = ("personal", "group")
WORKFLOW_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "simplechat-test:origin-provenance"))
ORIGIN = {
    "source": "orchestration",
    "conversation_id": "conv-chat",
    "orchestration_run_id": "orchestration-run-1",
    "proposal_id": "proposal-monday-digest",
    "created_at": "2026-09-28T12:00:00+00:00",
}
UNEDITED = {**ORIGIN, "edited": False}
EDITED = {**ORIGIN, "edited": True}
FORGED_ORIGINS = {
    "lookalike": {
        "source": "orchestration", "conversation_id": "conv-forged", "orchestration_run_id": "run-forged",
        "proposal_id": "proposal-forged", "created_at": "2020-01-01T00:00:00+00:00", "edited": False,
    },
    "unknown_source": {"source": "import", "proposal_id": "proposal-forged", "role": "admin"},
    "oversize": "orchestration" * 2000,
    "null": None,
}


class OriginRoutes:
    """Both save route bodies over the real personal and group workflow stores."""

    def __init__(self):
        self.harness = SaveParityHarness()
        self.definitions = self.harness.modules["functions_workflow_definitions"]
        namespace = {
            "request": request,
            "jsonify": jsonify,
            "logging": logging,
            "log_event": lambda *args, **kwargs: None,
            "get_current_user_id": lambda: OWNER_ID,
            # The real classes the loaded modules raise, so the routes' except clauses see them.
            "WorkflowDefinitionConflict": self.definitions.WorkflowDefinitionConflict,
            "WorkflowDefinitionError": self.definitions.WorkflowDefinitionError,
            "WorkflowPublicValidationError": self.definitions.WorkflowPublicValidationError,
            "_prepare_workflow_url_access_payload": lambda payload, user_id: payload,
            "_resolve_active_group_for_workflow_management": lambda user_id: (GROUP_ID, {}),
            "_get_current_user_info_with_roles": lambda: {"roles": ["User"]},
            "save_personal_workflow": self.harness.personal.save_personal_workflow,
            "save_group_workflow": self.harness.group.save_group_workflow,
            "log_workflow_creation": lambda **kwargs: None,
            "log_workflow_update": lambda **kwargs: None,
            "authorize_workflow_run_read": lambda *args, **kwargs: None,
            "AnalysisResultUnavailable": LookupError,
        }
        names = {"save_user_workflow", "save_group_workflow_route", "_workflow_definition_response"}
        nodes = []
        for node in ast.walk(ast.parse(ROUTES_FILE.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef) and node.name in names and node.name not in {n.name for n in nodes}:
                node.decorator_list = []
                nodes.append(node)
        assert {node.name for node in nodes} == names
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROUTES_FILE), "exec"), namespace)
        app = Flask("workflow-origin-provenance")
        app.add_url_rule("/api/user/workflows", endpoint="save_user_workflow",
                         view_func=namespace["save_user_workflow"], methods=["POST"])
        app.add_url_rule("/api/group/workflows", endpoint="save_group_workflow_route",
                         view_func=namespace["save_group_workflow_route"], methods=["POST"])
        self.client = app.test_client()

    def post(self, scope, payload):
        path = "/api/group/workflows" if scope == "group" else "/api/user/workflows"
        with self.harness.active():
            return self.client.post(path, json=payload)

    def server_create(self, scope, payload, *, workflow_id=WORKFLOW_ID, origin=ORIGIN):
        """The create path chat orchestration uses: a server-chosen id and a server origin."""
        with self.harness.active():
            if scope == "group":
                return self.harness.group.create_group_workflow_if_absent(
                    GROUP_ID, copy.deepcopy(payload), OWNER_ID, {"roles": ["User"]},
                    workflow_id=workflow_id, origin=copy.deepcopy(origin),
                )
            return self.harness.personal.create_personal_workflow_if_absent(
                OWNER_ID, copy.deepcopy(payload), workflow_id=workflow_id, origin=copy.deepcopy(origin),
                actor_user_id=OWNER_ID,
            )

    def load(self, scope, workflow_id=WORKFLOW_ID):
        """The record the editor opens: the stored workflow with its definition revision."""
        if scope == "group":
            return self.harness.load_group(workflow_id)
        return self.harness.load_personal(workflow_id)

    def container(self, scope):
        return self.harness.containers["group_workflows" if scope == "group" else "personal_workflows"]

    def stored(self, scope, workflow_id=WORKFLOW_ID):
        partition = GROUP_ID if scope == "group" else OWNER_ID
        return self.container(scope).items.get((partition, workflow_id))

    def writes(self):
        return sum(len(self.container(scope).writes) for scope in SCOPES)


@pytest.fixture
def routes():
    return OriginRoutes()


def _definition(version=2, **fields):
    """A paused Monday digest, the shape a chat orchestration create stores."""
    if version == 3:
        payload = _v2(
            "Monday digest", definition_version=3,
            tasks=[_task("gather", "Gather", "Gather this week's to-dos.", inputs=[], output_contract={"kind": "text"})],
            flow={"id": "root", "nodes": [{"id": "gather_node", "kind": "task", "task_id": "gather"}], "outputs": []},
        )
    else:
        payload = _v2(
            "Monday digest", trigger_type="interval", schedule=copy.deepcopy(CALENDAR_WEEKLY), is_enabled=False,
            tasks=[_task("read", "Read", "Read my email."), _task("list", "List", "List this week's to-dos.")],
        )
    payload.update(copy.deepcopy(fields))
    return payload


def _with_origin(payload, forged):
    """A payload carrying a forged origin, or with the key removed when ``forged`` is ``...``."""
    payload = copy.deepcopy(payload)
    if forged is ...:
        payload.pop("origin", None)
    else:
        payload["origin"] = copy.deepcopy(forged)
    return payload


def test_version_header_is_current():
    assert_app_version_at_least("0.261.202")


# Save and update routes -------------------------------------------------------------------------

@pytest.mark.parametrize("forged", sorted(FORGED_ORIGINS))
@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("scope", SCOPES)
def test_a_save_route_create_never_records_an_origin(routes, scope, version, forged):
    """A create through a save route stores no origin, whatever the payload claims."""
    response = routes.post(scope, _with_origin(_definition(version), FORGED_ORIGINS[forged]))

    assert response.status_code == 201, response.get_data(as_text=True)
    workflow = response.json["workflow"]
    assert "origin" not in workflow
    assert "origin" not in routes.stored(scope, workflow["id"])


@pytest.mark.parametrize("forged", [*sorted(FORGED_ORIGINS), "removed"])
@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("scope", SCOPES)
def test_a_save_route_update_keeps_the_server_origin(routes, scope, version, forged):
    """An update cannot replace, reset or remove the origin a server create recorded."""
    created, was_created = routes.server_create(scope, _definition(version))
    assert was_created is True
    assert created["origin"] == UNEDITED
    value = ... if forged == "removed" else FORGED_ORIGINS[forged]

    response = routes.post(scope, _with_origin(routes.load(scope), value))

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["workflow"]["origin"] == UNEDITED
    assert routes.stored(scope)["origin"] == UNEDITED


@pytest.mark.parametrize("scope", SCOPES)
def test_an_ordinary_workflow_cannot_gain_an_origin_on_update(routes, scope):
    """A workflow saved through a route stays without an origin when a later save claims one."""
    workflow = routes.post(scope, _definition()).json["workflow"]
    loaded = routes.load(scope, workflow["id"])

    for forged in FORGED_ORIGINS.values():
        response = routes.post(scope, _with_origin(routes.load(scope, workflow["id"]), forged))
        assert response.status_code == 200, response.get_data(as_text=True)
        assert "origin" not in response.json["workflow"]
    assert "origin" not in routes.stored(scope, workflow["id"])
    assert routes.load(scope, workflow["id"])["definition_revision"] == loaded["definition_revision"]


# The edited flag ---------------------------------------------------------------------------------

MATERIAL_CHANGES = {
    "name": lambda workflow: {"name": "My Monday digest"},
    "description": lambda workflow: {"description": "Only the urgent ones."},
    "instructions": lambda workflow: {
        "tasks": [{**workflow["tasks"][0], "instructions": "Read my flagged email."}, *workflow["tasks"][1:]],
    },
    "schedule": lambda workflow: {"schedule": {**CALENDAR_WEEKLY, "time_of_day": "09:00"}},
    "alerts": lambda workflow: {"alert_mode": "every_run", "alert_priority": "low"},
}


@pytest.mark.parametrize("scope", SCOPES)
def test_saving_or_pausing_a_created_workflow_is_not_an_edit(routes, scope):
    """Re-saving what the editor loaded, enabling and pausing keep the origin unedited."""
    routes.server_create(scope, _definition())

    for change in ({}, {"is_enabled": True}, {"is_enabled": False}, {}):
        response = routes.post(scope, {**routes.load(scope), **change})
        assert response.status_code == 200, response.get_data(as_text=True)
        assert response.json["workflow"]["origin"] == UNEDITED
    assert routes.stored(scope)["origin"] == UNEDITED


@pytest.mark.parametrize("change", sorted(MATERIAL_CHANGES))
@pytest.mark.parametrize("scope", SCOPES)
def test_a_material_change_marks_the_workflow_edited_for_good(routes, scope, change):
    """The owner's first material change sets ``edited``; reverting it or a forged origin cannot unset it."""
    created, _ = routes.server_create(scope, _definition())
    loaded = routes.load(scope)

    edited = routes.post(scope, {**loaded, **MATERIAL_CHANGES[change](loaded)})

    assert edited.status_code == 200, edited.get_data(as_text=True)
    assert edited.json["workflow"]["origin"] == EDITED
    restored = {**routes.load(scope), **{field: created[field] for field in MATERIAL_CHANGES[change](loaded)}}
    reverted = routes.post(scope, _with_origin(restored, UNEDITED))
    assert reverted.status_code == 200, reverted.get_data(as_text=True)
    assert reverted.json["workflow"]["origin"] == EDITED
    assert routes.stored(scope)["origin"] == EDITED


@pytest.mark.parametrize("scope", SCOPES)
def test_runtime_progress_is_not_an_edit(routes, scope):
    """A run's progress updates keep the origin as the create recorded it."""
    routes.server_create(scope, _definition())
    updates = {"run_count": 1, "last_run_status": "completed", "last_run_at": "2026-10-05T12:01:00+00:00"}

    with routes.harness.active():
        if scope == "group":
            updated = routes.harness.group.update_group_workflow_runtime_fields(GROUP_ID, WORKFLOW_ID, updates)
        else:
            updated = routes.harness.personal.update_personal_workflow_runtime_fields(OWNER_ID, WORKFLOW_ID, updates)
    resaved = routes.post(scope, routes.load(scope))

    assert updated["origin"] == UNEDITED
    assert resaved.status_code == 200, resaved.get_data(as_text=True)
    assert resaved.json["workflow"]["origin"] == UNEDITED


# Fingerprint and approval (gotcha 15) ----------------------------------------------------------

def test_the_origin_is_outside_the_fingerprint_and_the_definition_revision(routes):
    """Adding, flipping or changing the origin leaves both hashes where they were."""
    created, _ = routes.server_create("personal", _definition(m365_run_as_user_id=OWNER_ID))
    binding = routes.harness.modules["functions_m365_workflow_binding"]
    without = {key: value for key, value in created.items() if key != "origin"}
    variants = [
        without,
        created,
        {**created, "origin": EDITED},
        {**created, "origin": {**EDITED, "proposal_id": "another-proposal", "conversation_id": "another-conv"}},
    ]

    assert "origin" not in binding.M365_WORKFLOW_FIELDS
    assert "origin" not in routes.definitions.WORKFLOW_DEFINITION_FIELDS
    assert {binding.workflow_execution_fingerprint(variant) for variant in variants} == {created["m365_revision"]}
    assert {routes.definitions.workflow_definition_revision(variant) for variant in variants} == {
        created["definition_revision"],
    }


@pytest.mark.parametrize("scope", SCOPES)
def test_marking_a_workflow_edited_keeps_its_run_as_approval(routes, scope):
    """The edit that flips ``edited`` keeps an approval its execution settings still match."""
    created, _ = routes.server_create(scope, _definition(m365_run_as_user_id=OWNER_ID))
    partition = GROUP_ID if scope == "group" else OWNER_ID
    container = "group_workflows" if scope == "group" else "personal_workflows"
    routes.harness.seed_approval(container, partition, WORKFLOW_ID, "approval-1")

    described = routes.post(scope, {**routes.load(scope), "description": "Only the urgent ones."})

    assert described.status_code == 200, described.get_data(as_text=True)
    workflow = described.json["workflow"]
    assert workflow["origin"] == EDITED
    assert workflow["m365_revision"] == created["m365_revision"]
    assert workflow["m365_binding_approval_id"] == "approval-1"
    # A change the approval covers still clears it, exactly as before provenance existed.
    loaded = routes.load(scope)
    retasked = routes.post(scope, {
        **loaded, "tasks": [{**loaded["tasks"][0], "instructions": "Read my flagged email."}, *loaded["tasks"][1:]],
    })
    assert retasked.status_code == 200, retasked.get_data(as_text=True)
    assert retasked.json["workflow"]["m365_binding_approval_id"] is None
    assert retasked.json["workflow"]["origin"] == EDITED


# Server creates ------------------------------------------------------------------------------------

@pytest.mark.parametrize("scope", SCOPES)
def test_a_server_create_happens_once_per_proposal(routes, scope):
    """Accepting a proposal twice returns the first workflow; another proposal's id is a conflict."""
    first, created = routes.server_create(scope, _definition())
    again, created_again = routes.server_create(scope, _definition(name="A second accept"))

    assert created is True and created_again is False
    assert again == first
    assert routes.container(scope).writes == [("create_item", WORKFLOW_ID)]
    with pytest.raises(routes.definitions.WorkflowDefinitionConflict, match="A different workflow already uses this id."):
        routes.server_create(scope, _definition(), origin={**ORIGIN, "proposal_id": "another-proposal"})
    assert routes.writes() == 1


@pytest.mark.parametrize("scope", SCOPES)
def test_a_server_create_records_a_proposal_edited_before_accepting(routes, scope):
    """A proposal changed in the editor before it was accepted is recorded as edited from the start."""
    workflow, created = routes.server_create(scope, _definition(), origin=EDITED)

    assert created is True
    assert workflow["origin"] == EDITED
    assert routes.stored(scope)["origin"] == EDITED
    resaved = routes.post(scope, routes.load(scope))
    assert resaved.status_code == 200, resaved.get_data(as_text=True)
    assert routes.stored(scope)["origin"] == EDITED


@pytest.mark.parametrize("scope", SCOPES)
def test_a_server_create_never_adopts_or_revives_another_workflow(routes, scope):
    """An ordinary workflow, or one being deleted, under the id is a conflict, never a success."""
    ordinary = routes.post(scope, _definition()).json["workflow"]
    conflict = routes.definitions.WorkflowDefinitionConflict

    with pytest.raises(conflict, match="A different workflow already uses this id."):
        routes.server_create(scope, _definition(), workflow_id=ordinary["id"])
    routes.server_create(scope, _definition())
    routes.stored(scope)["deleting"] = True
    with pytest.raises(conflict, match="This workflow is being deleted. Your draft was not saved."):
        routes.server_create(scope, _definition())
    assert "origin" not in routes.stored(scope, ordinary["id"])
    assert routes.writes() == 2


@pytest.mark.parametrize("scope", SCOPES)
def test_a_concurrent_server_create_returns_the_first_workflow(routes, scope, monkeypatch):
    """When the lookup misses a create that lands first, the conditional create still finds it."""
    first, _ = routes.server_create(scope, _definition())
    module = routes.harness.group if scope == "group" else routes.harness.personal
    monkeypatch.setattr(module, "get_group_workflow" if scope == "group" else "get_personal_workflow",
                        lambda *args, **kwargs: None)
    conflict = routes.definitions.WorkflowDefinitionConflict

    again, created = routes.server_create(scope, _definition(name="A racing accept"))

    assert created is False
    assert again["id"] == first["id"] and again["name"] == "Monday digest" and again["origin"] == UNEDITED
    with pytest.raises(conflict, match="A different workflow already uses this id."):
        routes.server_create(scope, _definition(), origin={**ORIGIN, "proposal_id": "another-proposal"})
    routes.stored(scope)["deleting"] = True
    with pytest.raises(conflict, match="This workflow is being deleted. Your draft was not saved."):
        routes.server_create(scope, _definition())
    assert routes.writes() == 1


@pytest.mark.parametrize("scope", SCOPES)
def test_a_server_create_takes_only_the_id_it_chose(routes, scope):
    """The payload cannot name the id, and the server id must be a UUID."""
    with pytest.raises(ValueError, match="A workflow created by the server cannot name its own id."):
        routes.server_create(scope, {**_definition(), "id": "chosen-by-the-payload"})
    with pytest.raises(ValueError, match="A server-created workflow id must be a UUID."):
        routes.server_create(scope, _definition(), workflow_id="not-a-uuid")
    assert routes.writes() == 0


# Normalization -----------------------------------------------------------------------------------

def test_an_origin_is_closed_and_bounded(routes):
    """Only the known fields, a known source, bounded ids and an ISO 8601 time are accepted."""
    normalize = routes.definitions.normalize_workflow_origin
    error = routes.definitions.WorkflowDefinitionError

    assert normalize(ORIGIN) == UNEDITED
    assert list(normalize(ORIGIN)) == list(routes.definitions.WORKFLOW_ORIGIN_FIELDS)
    assert normalize({**ORIGIN, "edited": True}) == EDITED
    for value in (
        None, "orchestration", [ORIGIN],
        {**ORIGIN, "source": "import"},
        {**ORIGIN, "role": "admin"},
        {**ORIGIN, "proposal_id": "p" * 129},
        {**ORIGIN, "conversation_id": ""},
        {key: value for key, value in ORIGIN.items() if key != "orchestration_run_id"},
        {**ORIGIN, "created_at": "last Monday"},
        {**ORIGIN, "created_at": "2" * 65},
        {**ORIGIN, "edited": "yes"},
    ):
        with pytest.raises(error):
            normalize(value)
    with pytest.raises(error, match="Only a new workflow can record where it came from."):
        routes.definitions.apply_workflow_origin({}, {"id": WORKFLOW_ID}, ORIGIN)
