# test_workflow_settings_reviewed_messages.py
#!/usr/bin/env python3
"""
Functional test for reviewed workflow settings messages, deleted File Sync sources and deleted workflows.
Version: 0.261.149
Implemented in: 0.261.149

This test ensures that, on both ``POST /api/user/workflows`` and ``POST /api/group/workflows``:

* every File Sync, schedule and trigger failure on the save path reaches the client as its own
  reviewed, data-free message: HTTP 400 with
  ``{"error": <message>, "code": "invalid_workflow_settings"}``. Any other ``ValueError`` still
  returns the generic "Invalid workflow settings" message;
* a selected File Sync source, or the workspace that owned it, deleted after it was chosen is a
  400 with code ``file_sync_source_unavailable``, and nothing is written. A source the caller may
  not use stays 403, a deleted group stays 404, and any other ``LookupError`` keeps its mapping;
* saving a workflow that was deleted after the editor opened it, which V2 marks with the
  ``definition_revision`` it opened, is a 409 with code ``workflow_deleted``. Nothing is written
  and the workflow is not recreated. Creates and current updates are unchanged, and a transient
  read failure is never reported as a deletion;
* a save that sends no revision, as classic does, still recreates a deleted workflow. This is a
  known limitation, pinned here so it cannot change unnoticed.

The route bodies, and the real ``save_personal_workflow`` and ``save_group_workflow``, come from
the M6B harness in ``test_workflow_alert_reviewed_messages.py``. Only Cosmos, the group role
check, the File Sync source stores and settings are doubled.
"""

import copy
import json
import sys
from pathlib import Path

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError

sys.path.append(str(Path(__file__).resolve().parent))

from test_group_workflow_round_trip_preservation import (  # noqa: E402  (shared real-module harness)
    GROUP_ID,
    OTHER_GROUP_ID,
    OWNER_ID,
    SOURCE_ID,
)
from test_workflow_alert_reviewed_messages import GENERIC_400, SaveRoutes, _payload  # noqa: E402


SETTINGS_CODE = "invalid_workflow_settings"
SOURCE_UNAVAILABLE = "A selected File Sync source is no longer available. Remove it and save again."
WORKFLOW_DELETED = "This workflow was deleted after it was opened, so your changes were not saved."
MARKER = "PRIVATE-MARKER-5c1d"
PERSONAL_SOURCE_ID = "notes-share"
UNMANAGED_GROUP_ID = "group-gamma"
DELETED_GROUP_ID = "group-deleted"
SCOPES = ("personal", "group")
SCHEDULE = {"unit": "minutes", "value": 30}


def _source(scope):
    if scope == "group":
        return {"scope_type": "group", "scope_id": GROUP_ID, "source_id": SOURCE_ID}
    return {"scope_type": "personal", "scope_id": OWNER_ID, "source_id": PERSONAL_SOURCE_ID}


def _file_sync(scope, **overrides):
    config = {
        "enabled": True, "wait_mode": "complete", "continue_mode": "always",
        "use_changed_documents": True, "sources": [_source(scope)],
    }
    config.update(overrides)
    return config


def _monitor(scope, **overrides):
    return _file_sync(scope, continue_mode="changed", **overrides)


# name: (scopes, payload fields, reviewed message). Every invalid value carries MARKER, so a
# message that echoed caller text would fail the data-free check.
CASES = {
    "schedule_unit": (SCOPES, {"trigger_type": "interval", "schedule": {"unit": f"weeks-{MARKER}", "value": 5}},
                      "Schedule unit must be seconds, minutes or hours."),
    "schedule_unit_missing": (SCOPES, {"trigger_type": "interval", "schedule": {"value": 5}},
                              "Schedule unit must be seconds, minutes or hours."),
    "schedule_value_text": (SCOPES, {"trigger_type": "interval", "schedule": {"unit": "minutes", "value": f"soon-{MARKER}"}},
                            "Schedule value must be a whole number."),
    "schedule_value_decimal_text": (SCOPES, {"trigger_type": "interval", "schedule": {"unit": "hours", "value": "1.5"}},
                                    "Schedule value must be a whole number."),
    "schedule_value_missing": (SCOPES, {"trigger_type": "interval", "schedule": {"unit": "minutes"}},
                               "Schedule value must be a whole number."),
    "schedule_value_list": (SCOPES, {"trigger_type": "interval", "schedule": {"unit": "minutes", "value": [MARKER]}},
                            "Schedule value must be a whole number."),
    "schedule_minutes_high": (SCOPES, {"trigger_type": "interval", "schedule": {"unit": "minutes", "value": 90}},
                              "Schedule value for minutes must be between 1 and 59."),
    "schedule_seconds_zero": (SCOPES, {"trigger_type": "interval", "schedule": {"unit": "seconds", "value": 0}},
                              "Schedule value for seconds must be between 1 and 59."),
    "schedule_hours_high": (SCOPES, {"trigger_type": "interval", "schedule": {"unit": "HOURS", "value": "25"}},
                            "Schedule value for hours must be between 1 and 24."),
    "monitor_schedule": (SCOPES, {"trigger_type": "file_sync", "schedule": {"unit": "minutes", "value": 60},
                                  "file_sync": {"continue_mode": "changed"}},
                         "Schedule value for minutes must be between 1 and 59."),
    "trigger_missing": (SCOPES, {"trigger_type": "  "}, "Trigger type is required."),
    "trigger_unknown": (SCOPES, {"trigger_type": f"weekly-{MARKER}"},
                        "Trigger type must be manual, interval or file_sync."),
    "wait_mode": (SCOPES, {"file_sync": {"wait_mode": f"later-{MARKER}"}},
                  "File Sync wait mode must be complete or queued."),
    "continue_mode": (SCOPES, {"file_sync": {"continue_mode": f"sometimes-{MARKER}"}},
                      "File Sync continue mode must be always or changed."),
    "queued_changed": (SCOPES, {"file_sync": {"wait_mode": "queued", "continue_mode": "changed"}},
                       "To continue only when changes are found, File Sync must wait for the sync to complete."),
    "monitor_without_file_sync": (SCOPES, {"trigger_type": "file_sync", "file_sync": {"enabled": False, "sources": []}},
                                  "Monitor File Sync Changes workflows require File Sync before run."),
    "monitor_queued": (SCOPES, {"trigger_type": "file_sync", "file_sync": {"wait_mode": "queued", "continue_mode": "always"}},
                       "Monitor File Sync Changes workflows must wait for sync completion."),
    "monitor_always": (SCOPES, {"trigger_type": "file_sync", "file_sync": {"continue_mode": "always"}},
                       "Monitor File Sync Changes workflows must continue only when changes are found."),
    "personal_without_sources": (("personal",), {"file_sync": {"sources": []}},
                                 "Select at least one File Sync source for this workflow."),
    "group_without_sources": (("group",), {"file_sync": {"sources": []}},
                              "Select at least one group File Sync source for this workflow."),
    "group_other_group_source": (("group",), {"file_sync": {"sources": [
        {"scope_type": "group", "scope_id": OTHER_GROUP_ID, "source_id": f"other-{MARKER}"},
    ]}}, "Group workflows can only use File Sync sources from this group."),
    "group_personal_source": (("group",), {"file_sync": {"sources": [
        {"scope_type": "personal", "scope_id": OWNER_ID, "source_id": PERSONAL_SOURCE_ID},
    ]}}, "Group workflows can only use File Sync sources from this group."),
}
SCOPED_CASES = [(scope, name) for name, (scopes, _, _) in sorted(CASES.items()) for scope in scopes]


def _settings_payload(scope, fields):
    """A valid definition with File Sync before run; the failing fields are merged into it."""
    fields = copy.deepcopy(fields)
    file_sync = _file_sync(scope)
    file_sync.update(fields.pop("file_sync", {}))
    payload = _payload(scope, file_sync=file_sync, schedule=copy.deepcopy(SCHEDULE))
    payload.update(fields)
    return payload


class SettingsRoutes(SaveRoutes):
    """The M6B save routes, with a personal File Sync source store modelled on the real lookup."""

    def __init__(self):
        super().__init__()
        self.store.sources[(UNMANAGED_GROUP_ID, "gamma-share")] = {
            "id": "gamma-share", "scope_type": "group", "group_id": UNMANAGED_GROUP_ID,
            "name": "Gamma share", "source_type": "smb",
        }
        self.personal_sources = {
            (OWNER_ID, PERSONAL_SOURCE_ID): {
                "id": PERSONAL_SOURCE_ID, "scope_type": "personal", "user_id": OWNER_ID,
                "name": "Notes share", "source_type": "smb",
            },
        }
        existing_groups = {GROUP_ID, OTHER_GROUP_ID, UNMANAGED_GROUP_ID}
        group_lookup = self.store.module.get_authorized_sync_source

        def get_authorized_sync_source(scope_type, source_id, user_id, scope_id=None, **kwargs):
            # Like functions_file_sync.get_authorized_sync_source: a deleted source, or a deleted
            # group (assert_group_role's "Group not found"), is a LookupError; a group the caller
            # cannot manage is a PermissionError.
            if scope_type == "personal":
                source = self.personal_sources.get((user_id, source_id))
                if source is None:
                    raise LookupError("File sync source not found")
                return copy.deepcopy(source)
            if scope_id not in existing_groups:
                raise LookupError("Group not found")
            return group_lookup(scope_type, source_id, user_id, scope_id=scope_id, **kwargs)

        self.store.modules["functions_personal_workflows"].get_authorized_sync_source = get_authorized_sync_source

    def container(self, scope):
        return self.store.container if scope == "group" else self.personal_container

    def partition(self, scope):
        return GROUP_ID if scope == "group" else OWNER_ID


@pytest.fixture(scope="module")
def routes():
    return SettingsRoutes()


def _created(routes, scope, **fields):
    response = routes.post(scope, _payload(scope, **fields))
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.json["workflow"]


def _edited(record, **fields):
    """What the V2 editor sends back: the loaded record, with its id and opened revision, plus edits."""
    payload = {
        key: copy.deepcopy(value) for key, value in record.items()
        if key not in {"user_id", "created_at", "created_by", "modified_at", "modified_by", "updated_at"}
    }
    payload.update(copy.deepcopy(fields))
    return payload


# ---------------------------------------------------------------------------------------------
# (b) reviewed File Sync, schedule and trigger messages
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("scope, case", SCOPED_CASES)
def test_each_settings_failure_returns_its_reviewed_message(routes, scope, case):
    """Each File Sync, schedule and trigger failure is a 400 with its reviewed, data-free message."""
    _, fields, message = CASES[case]
    writes_before = routes.writes()

    response = routes.post(scope, _settings_payload(scope, fields))

    assert response.status_code == 400, response.get_data(as_text=True)
    assert response.json == {"error": message, "code": SETTINGS_CODE}
    assert MARKER not in response.get_data(as_text=True)
    assert routes.writes() == writes_before


@pytest.mark.parametrize("scope", SCOPES)
def test_group_file_sync_disabled_is_a_reviewed_400(routes, scope):
    """Group File Sync switched off refuses a group workflow's File Sync; personal is not gated by it."""
    routes.store.file_sync_groups.discard(GROUP_ID)
    try:
        response = routes.post(scope, _settings_payload(scope, {}))
    finally:
        routes.store.file_sync_groups.add(GROUP_ID)

    if scope == "group":
        assert response.status_code == 400
        assert response.json == {
            "error": "Group File Sync must be enabled before a group workflow can use File Sync sources.",
            "code": SETTINGS_CODE,
        }
    else:
        assert response.status_code == 201, response.get_data(as_text=True)


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("literal", ["Infinity", "-Infinity", "NaN"])
def test_a_non_finite_schedule_value_is_a_reviewed_400_not_a_500(routes, scope, literal):
    """The request parser accepts JSON's non-finite literals; they used to escape int() as a 500."""
    payload = _settings_payload(scope, {"trigger_type": "interval"})
    body = json.dumps(payload).replace('"value": 30', f'"value": {literal}')
    assert literal in body

    response = routes.client.post(
        "/api/group/workflows" if scope == "group" else "/api/user/workflows",
        data=body, content_type="application/json",
    )

    assert response.status_code == 400, response.get_data(as_text=True)
    assert response.json == {"error": "Schedule value must be a whole number.", "code": SETTINGS_CODE}


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("fields", [
    {"trigger_type": "interval", "schedule": {"unit": "seconds", "value": 59}},
    {"trigger_type": "interval", "schedule": {"unit": "minutes", "value": 1}},
    {"trigger_type": "interval", "schedule": {"unit": " Hours ", "value": "24"}},
    {"trigger_type": "interval", "schedule": {"unit": "minutes", "value": 30.9}},
    {"trigger_type": "MANUAL"},
    {"trigger_type": "file_sync", "file_sync": {"continue_mode": "changed"}},
    {"file_sync": {"wait_mode": "queued", "continue_mode": "always"}},
    {"file_sync": {"enabled": False, "sources": []}},
], ids=["59_seconds", "1_minute", "24_hours_text", "decimal_truncates", "manual_upper", "monitor",
        "queued_always", "no_file_sync"])
def test_valid_settings_still_save(routes, scope, fields):
    """The reviewed branch refuses only invalid settings; each accepted form still saves."""
    response = routes.post(scope, _settings_payload(scope, fields))

    assert response.status_code == 201, response.get_data(as_text=True)


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("fields, legacy_message", [
    ({"name": "   "}, "Workflow name is required."),
    ({"runner_type": f"robot-{MARKER}"}, "Runner type must be agent or model."),
])
def test_other_value_errors_stay_generic(routes, scope, fields, legacy_message):
    """A ValueError outside the reviewed families keeps the generic message and carries no code."""
    response = routes.post(scope, _settings_payload(scope, fields))

    assert response.status_code == 400
    assert response.json == {"error": GENERIC_400}
    assert legacy_message not in response.get_data(as_text=True)


# ---------------------------------------------------------------------------------------------
# (a) a File Sync source deleted between opening and saving
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("scope", SCOPES)
def test_a_deleted_source_is_a_reviewed_400_and_nothing_is_written(routes, scope):
    """A selected source that no longer exists is the reviewed 400 with its own code, never a 404."""
    missing = {**_source(scope), "source_id": f"deleted-{MARKER}"}
    writes_before = routes.writes()

    response = routes.post(scope, _settings_payload(scope, {"file_sync": {"sources": [missing]}}))

    assert response.status_code == 400, response.get_data(as_text=True)
    assert response.json == {"error": SOURCE_UNAVAILABLE, "code": "file_sync_source_unavailable"}
    assert MARKER not in response.get_data(as_text=True)
    assert routes.writes() == writes_before


@pytest.mark.parametrize("scope", SCOPES)
def test_a_source_deleted_after_the_editor_opened_the_workflow_keeps_the_stored_record(routes, scope):
    """The editor's real path: the loaded File Sync is sent back after its source was deleted."""
    record = _created(routes, scope, file_sync=_file_sync(scope), schedule=copy.deepcopy(SCHEDULE))
    stored_key = (routes.partition(scope), record["id"])
    stored = copy.deepcopy(routes.container(scope).items[stored_key])
    sources = routes.store.sources if scope == "group" else routes.personal_sources
    source_key = (GROUP_ID, SOURCE_ID) if scope == "group" else (OWNER_ID, PERSONAL_SOURCE_ID)
    deleted = sources.pop(source_key)
    try:
        writes_before = routes.writes()
        response = routes.post(scope, _edited(record, description="Edited after the source was deleted."))
    finally:
        sources[source_key] = deleted

    assert response.status_code == 400, response.get_data(as_text=True)
    assert response.json == {"error": SOURCE_UNAVAILABLE, "code": "file_sync_source_unavailable"}
    assert routes.writes() == writes_before
    assert routes.container(scope).items[stored_key] == stored


def test_a_deleted_owning_workspace_is_the_same_400(routes):
    """A source whose group was deleted fails like a deleted source: assert_group_role's LookupError."""
    orphaned = {"scope_type": "group", "scope_id": DELETED_GROUP_ID, "source_id": "orphaned-share"}

    response = routes.post("personal", _settings_payload("personal", {"file_sync": {"sources": [orphaned]}}))

    assert response.status_code == 400, response.get_data(as_text=True)
    assert response.json == {"error": SOURCE_UNAVAILABLE, "code": "file_sync_source_unavailable"}


def test_a_source_the_caller_may_not_use_stays_403_on_the_personal_route(routes):
    unmanaged = {"scope_type": "group", "scope_id": UNMANAGED_GROUP_ID, "source_id": "gamma-share"}

    response = routes.post("personal", _settings_payload("personal", {"file_sync": {"sources": [unmanaged]}}))

    assert response.status_code == 403
    assert response.json == {"error": "Workflow settings or sources are not allowed for this account."}


def test_a_source_the_caller_may_not_use_stays_403_on_the_group_route(routes, monkeypatch):
    def refuse(*args, **kwargs):
        raise PermissionError("File sync source does not belong to this workspace")

    monkeypatch.setattr(routes.store.module, "get_authorized_sync_source", refuse)

    response = routes.post("group", _settings_payload("group", {}))

    assert response.status_code == 403
    assert response.json == {"error": "The selected group or workflow sources are not allowed."}


def test_a_deleted_group_stays_404(routes, monkeypatch):
    """The group resolver's LookupError, for a group deleted before the save, keeps its 404."""
    def group_gone(user_id):
        raise LookupError("Group not found")

    route = routes.client.application.view_functions["save_group_workflow_route"]
    monkeypatch.setitem(route.__globals__, "_resolve_active_group_for_workflow_management", group_gone)

    response = routes.post("group", _settings_payload("group", {}))

    assert response.status_code == 404
    assert response.json == {"error": "The workflow or one of its sources is not available."}


@pytest.mark.parametrize("scope, status, body", [
    ("group", 404, {"error": "The workflow or one of its sources is not available."}),
    ("personal", 500, {"error": "Unable to save workflow right now."}),
])
def test_other_lookup_errors_keep_their_mapping(routes, monkeypatch, scope, status, body):
    """Only the source lookup is translated; a LookupError from anywhere else maps as before."""
    module = routes.store.module if scope == "group" else routes.store.modules["functions_personal_workflows"]

    def unrelated_lookup(*args, **kwargs):
        raise LookupError("Some other record was not found")

    monkeypatch.setattr(module, "_normalize_workflow_error_handling", unrelated_lookup)

    response = routes.post(scope, _settings_payload(scope, {}))

    assert response.status_code == status
    assert response.json == body


def test_the_error_classes_keep_their_contract(routes):
    """Existing ValueError handlers still see the reviewed errors, and each family has its own code."""
    classes = routes.classes
    assert issubclass(classes.WorkflowSourceUnavailableError, classes.WorkflowPublicValidationError)
    assert not issubclass(classes.WorkflowSourceUnavailableError, LookupError)
    assert issubclass(classes.WorkflowAlertValidationError, classes.WorkflowPublicValidationError)
    assert issubclass(classes.WorkflowPublicValidationError, ValueError)
    assert issubclass(classes.WorkflowDeletedConflict, classes.WorkflowDefinitionConflict)
    assert classes.WorkflowPublicValidationError.code == SETTINGS_CODE
    assert classes.WorkflowAlertValidationError.code == "invalid_workflow_alerts"
    assert classes.WorkflowSourceUnavailableError.code == "file_sync_source_unavailable"
    assert classes.WorkflowSourceUnavailableError().public_message == SOURCE_UNAVAILABLE
    assert classes.WorkflowDefinitionConflict.code == "workflow_definition_conflict"
    assert classes.WorkflowDefinitionError.code == "invalid_workflow_definition"
    assert classes.WorkflowDeletedConflict.code == "workflow_deleted"
    assert classes.WorkflowDeletedConflict().public_message == WORKFLOW_DELETED


# ---------------------------------------------------------------------------------------------
# (d) saving a workflow deleted after the editor opened it
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("scope", SCOPES)
def test_saving_a_deleted_workflow_is_a_409_and_does_not_recreate_it(routes, scope):
    record = _created(routes, scope)
    assert record["definition_revision"]
    routes.container(scope).items.pop((routes.partition(scope), record["id"]))
    writes_before = routes.writes()

    response = routes.post(scope, _edited(record, description="Edited after the workflow was deleted."))

    assert response.status_code == 409, response.get_data(as_text=True)
    assert response.json == {"error": WORKFLOW_DELETED, "code": "workflow_deleted"}
    assert routes.writes() == writes_before
    assert (routes.partition(scope), record["id"]) not in routes.container(scope).items


@pytest.mark.parametrize("scope", SCOPES)
def test_the_deleted_refusal_comes_before_any_other_save_rule(routes, scope):
    """The refusal runs first, so an invalid draft of a deleted workflow still gets the 409."""
    record = _created(routes, scope)
    routes.container(scope).items.pop((routes.partition(scope), record["id"]))

    response = routes.post(scope, _edited(
        record, name="", trigger_type="interval", schedule={"unit": "minutes", "value": 90},
    ))

    assert response.status_code == 409
    assert response.json["code"] == "workflow_deleted"


@pytest.mark.parametrize("scope", SCOPES)
def test_creates_and_current_updates_are_unchanged(routes, scope):
    record = _created(routes, scope)
    assert "definition_revision" not in _payload(scope)

    response = routes.post(scope, _edited(record, description="A current update."))

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["workflow"]["description"] == "A current update."


@pytest.mark.parametrize("scope", SCOPES)
def test_a_delete_during_the_save_is_the_same_409(routes, scope, monkeypatch):
    """Deleted after the save's own lookup but before its write: the store's check gives the same answer."""
    record = _created(routes, scope)
    container = routes.container(scope)
    read_item = container.read_item
    reads = []

    def read_then_delete(item, partition_key, **kwargs):
        found = read_item(item, partition_key, **kwargs)
        reads.append(item)
        if len(reads) == 1:
            container.items.pop((partition_key, item))
        return found

    monkeypatch.setattr(container, "read_item", read_then_delete)
    writes_before = routes.writes()

    response = routes.post(scope, _edited(record, description="Edited during a delete."))

    assert response.status_code == 409, response.get_data(as_text=True)
    assert response.json == {"error": WORKFLOW_DELETED, "code": "workflow_deleted"}
    assert routes.writes() == writes_before


@pytest.mark.parametrize("scope", SCOPES)
def test_a_transient_read_failure_is_never_reported_as_a_deletion(routes, scope, monkeypatch):
    """The save's lookup returns None on any read error, so the refusal confirms a real 404 first."""
    record = _created(routes, scope)
    container = routes.container(scope)

    def unavailable(item, partition_key, **kwargs):
        raise CosmosHttpResponseError(status_code=503, message="Service unavailable")

    monkeypatch.setattr(container, "read_item", unavailable)
    writes_before = routes.writes()

    response = routes.post(scope, _edited(record, description="Edited during an outage."))

    assert response.status_code == 500
    assert response.json == {"error": "Unable to save workflow right now."}
    assert routes.writes() == writes_before


@pytest.mark.parametrize("scope", SCOPES)
def test_a_lookup_that_fails_once_keeps_the_existing_conflict(routes, scope, monkeypatch):
    """If only the first read fails, the record is there: the save keeps today's "already exists" 409."""
    record = _created(routes, scope)
    container = routes.container(scope)
    read_item = container.read_item
    reads = []

    def fail_once(item, partition_key, **kwargs):
        reads.append(item)
        if len(reads) == 1:
            raise CosmosHttpResponseError(status_code=503, message="Service unavailable")
        return read_item(item, partition_key, **kwargs)

    monkeypatch.setattr(container, "read_item", fail_once)

    response = routes.post(scope, _edited(record, description="Edited during a blip."))

    assert response.status_code == 409
    assert response.json == {
        "error": "This workflow already exists. Reload it before saving.", "code": "workflow_definition_conflict",
    }


@pytest.mark.parametrize("scope", SCOPES)
def test_known_limitation_a_save_without_a_revision_still_recreates_the_workflow(routes, scope):
    """Classic and older clients send no revision, so a deleted workflow they save is created again."""
    record = _created(routes, scope)
    routes.container(scope).items.pop((routes.partition(scope), record["id"]))
    payload = _edited(record, description="Saved by a client that sends no revision.")
    payload.pop("definition_revision")

    response = routes.post(scope, payload)

    assert response.status_code == 200, response.get_data(as_text=True)
    assert (routes.partition(scope), record["id"]) in routes.container(scope).items
    assert routes.container(scope).writes[-1] == ("create_item", record["id"])
