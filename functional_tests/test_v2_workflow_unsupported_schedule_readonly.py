# test_v2_workflow_unsupported_schedule_readonly.py
#!/usr/bin/env python3
"""
Functional test for the V2 editor's handling of a stored schedule of a kind it does not support.
Version: 0.261.197
Implemented in: 0.261.197

Only a newer server or a direct write can store a schedule whose kind is neither interval nor
calendar: the save routes refuse one. This test ensures that the V2 editor never replaces such a
schedule:

* for the interval and File Sync triggers in both scopes, ``normalizeWorkflowDefinition`` keeps the
  stored schedule exactly as stored and sets the read-only reason, ``flowUnsupportedReason``
  returns it (which is what makes the dialog read-only), and ``workflowForSave`` refuses to build a
  payload, so nothing is written. Sending the stored record as it is would be refused by the real
  save route, so read-only is the only safe reading;
* a manual workflow, which does not use its schedule and for which the server stores none, stays
  editable, and its save through the real route stores no schedule, as before;
* supported interval and calendar schedules are never made read-only;
* ``workflowScheduleKindSupported`` reads a kind exactly as ``normalize_workflow_schedule`` does;
* the existing read-only reason for an unsupported task schema still takes precedence.

The TypeScript runs unmodified in Node through ``test_support/tsResolve.mjs``. The save routes are
the real route bodies over the real personal and group stores.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

import test_group_workflow_round_trip_preservation as harness  # noqa: E402  (shared real-module harness)
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_workflow_calendar_schedules import (  # noqa: E402  (the server's cases and save routes)
    EVERY_MINUTE, KIND_ERROR, MONDAYS_NY, SETTINGS_CODE, CalendarRoutes,
)


REPO_ROOT = harness.REPO_ROOT
GROUP_ID = harness.GROUP_ID
SCOPES = ("personal", "group")
UNSUPPORTED = {"kind": "cron", "expression": "0 8 * * 1", "timezone": "America/New_York"}
SCHEMA_REASON = (
    "This workflow contains task configuration or bindings from an unsupported schema. "
    "Its original configuration has been retained and editing is disabled."
)
SAVE_REFUSAL = "This workflow contains unsupported executable fields and cannot be saved by this editor."
EDITED_DESCRIPTION = "Edited in the V2 editor."

# Read-only cases: (scope, how the workflow was stored, the trigger the editor reads).
READ_ONLY = {
    "personal:interval": ("personal", "interval", "interval"),
    "group:interval": ("group", "interval", "interval"),
    "group:monitor": ("group", "monitor", "file_sync"),
    # V2 does not author personal File Sync, but it opens those workflows, and the monitor uses the schedule.
    "personal:file_sync": ("personal", "interval", "file_sync"),
}
SUPPORTED = {
    f"{scope}:{name}": (scope, schedule)
    for scope in SCOPES
    for name, schedule in (("every_minute", EVERY_MINUTE), ("mondays_new_york", MONDAYS_NY))
}
# Each kind as a stored schedule carries it; the server decides which are supported.
KINDS = {
    "missing": {"unit": "minutes", "value": 5},
    **{
        name: {"kind": kind, "unit": "minutes", "value": 5}
        for name, kind in {
            "null": None, "empty": "", "interval": "interval", "interval_padded": " INTERVAL ",
            "interval_tabbed": "\tinterval\n", "calendar": "calendar", "calendar_padded": " Calendar ",
            "calendar_upper": "CALENDAR", "cron": "cron", "rrule_padded": " RRULE ", "calendar_v2": "calendar-v2",
            "true": True, "false": False, "zero": 0, "zero_float": 0.0, "one": 1, "empty_list": [],
            "calendar_list": ["calendar"], "empty_object": {},
        }.items()
    },
}

NODE_SCRIPT = r"""
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.argv[1];
const input = JSON.parse(readFileSync(0, 'utf8'));
await import(pathToFileURL(path.join(root, 'functional_tests', 'test_support', 'tsResolve.mjs')));
const lib = path.join(root, 'application', 'v2_ui', 'src', 'lib');
const editor = await import(pathToFileURL(path.join(lib, 'workflowEditor.ts')));
const flow = await import(pathToFileURL(path.join(lib, 'workflowFlow.ts')));
const settings = await import(pathToFileURL(path.join(lib, 'workflowSettings.ts')));
const scopes = { personal: { type: 'personal' }, group: { type: 'group', groupId: input.group_id } };
const output = { reason: editor.WORKFLOW_UNSUPPORTED_SCHEDULE_REASON, cases: {}, kinds: {} };
for (const [name, testCase] of Object.entries(input.cases)) {
    const scope = scopes[testCase.scope];
    // The editor opens the stored record, and the author changes the description.
    const original = editor.normalizeWorkflowDefinition(testCase.record, scope);
    const draft = { ...structuredClone(original), description: input.description };
    let payload = null;
    let saveError = '';
    try {
        payload = editor.workflowForSave(draft, original, scope);
    } catch (error) {
        saveError = String(error.message);
    }
    output.cases[name] = {
        trigger: original.trigger_type,
        schedule: original.schedule,
        reason: original.editor_readonly_reason ?? '',
        flowReason: flow.flowUnsupportedReason(original),
        label: settings.workflowScheduleLabel(original.trigger_type, original.schedule, null),
        saveError,
        payload,
    };
}
for (const [name, raw] of Object.entries(input.kinds)) {
    output.kinds[name] = settings.workflowScheduleKindSupported(raw);
}
console.log(JSON.stringify(output));
"""


def _plant(routes, scope, workflow_id, schedule):
    """Replace a stored workflow's schedule, as a newer server or a direct write would."""
    routes.container(scope).items[(routes.partition(scope), workflow_id)]["schedule"] = copy.deepcopy(schedule)


def _stored(routes, scope, stored_as, schedule):
    """Save a workflow through the real route, then give it the schedule under test."""
    if stored_as == "monitor":
        response = routes.post("group", harness.monitored_workflow(schedule=EVERY_MINUTE))
        assert response.status_code == 201, response.get_data(as_text=True)
        workflow_id = response.json["workflow"]["id"]
    elif stored_as == "interval":
        workflow_id = routes.created(scope, trigger_type="interval", schedule=EVERY_MINUTE)["id"]
    else:
        workflow_id = routes.created(scope)["id"]
    _plant(routes, scope, workflow_id, schedule)
    return workflow_id


@pytest.fixture(scope="module")
def outcome():
    routes = CalendarRoutes()
    ids, cases = {}, {}
    for name, (scope, stored_as, trigger) in READ_ONLY.items():
        ids[name] = _stored(routes, scope, stored_as, UNSUPPORTED)
        record = routes.load(scope, ids[name])
        cases[name] = {"scope": scope, "record": {**record, "trigger_type": trigger}}
    for scope in SCOPES:
        name = f"{scope}:manual"
        ids[name] = _stored(routes, scope, "manual", UNSUPPORTED)
        cases[name] = {"scope": scope, "record": routes.load(scope, ids[name])}
    for name, (scope, schedule) in SUPPORTED.items():
        ids[name] = routes.created(scope, trigger_type="interval", schedule=schedule)["id"]
        cases[name] = {"scope": scope, "record": routes.load(scope, ids[name])}
    precedence = routes.load("personal", ids["personal:interval"])
    precedence.update(definition_version=3, tasks=[
        {"id": "script", "type": "script", "name": "Script", "instructions": "Run the script.", "order": 1},
    ])
    cases["personal:schema_precedence"] = {"scope": "personal", "record": precedence}

    payload = {
        "group_id": GROUP_ID, "description": EDITED_DESCRIPTION, "cases": cases, "kinds": KINDS,
    }
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", NODE_SCRIPT, str(REPO_ROOT)],
        input=json.dumps(payload, allow_nan=False), cwd=REPO_ROOT, text=True, encoding="utf-8",
        capture_output=True, timeout=120, check=False,
    )
    assert result.returncode == 0, f"Production TypeScript check failed:\n{result.stdout}\n{result.stderr}"
    return routes, ids, cases, json.loads(result.stdout)


def test_the_application_version_includes_the_unsupported_schedule_guard():
    assert_app_version_at_least("0.261.197")


@pytest.mark.parametrize("name", sorted(READ_ONLY))
def test_a_scheduled_workflow_with_an_unsupported_schedule_opens_read_only_and_keeps_it(outcome, name):
    routes, ids, _cases, client = outcome
    scope, _stored_as, trigger = READ_ONLY[name]
    opened = client["cases"][name]

    assert opened["trigger"] == trigger
    assert opened["schedule"] == UNSUPPORTED
    assert opened["reason"] == client["reason"]
    assert client["reason"].startswith("This workflow uses a schedule this editor does not support.")
    assert opened["flowReason"] == client["reason"]
    assert opened["saveError"] == SAVE_REFUSAL
    assert opened["payload"] is None
    assert opened["label"] == ""
    assert routes.schedules.workflow_schedule_label(trigger, copy.deepcopy(UNSUPPORTED)) == ""
    assert routes.load(scope, ids[name])["schedule"] == UNSUPPORTED


@pytest.mark.parametrize("scope", SCOPES)
def test_the_save_route_refuses_the_stored_record_as_it_is(outcome, scope):
    """Why the editor must not save: the server refuses the schedule it would have to send back."""
    routes, ids, _cases, _client = outcome
    name = f"{scope}:interval"
    record = routes.load(scope, ids[name])
    writes = routes.writes()
    response = routes.post(scope, {**record, "description": EDITED_DESCRIPTION})

    assert response.status_code == 400, response.get_data(as_text=True)
    assert response.get_json() == {"error": KIND_ERROR, "code": SETTINGS_CODE}
    assert routes.writes() == writes
    assert routes.load(scope, ids[name])["schedule"] == UNSUPPORTED


@pytest.mark.parametrize("scope", SCOPES)
def test_a_manual_workflow_with_a_leftover_schedule_stays_editable_and_saves_none(outcome, scope):
    routes, ids, _cases, client = outcome
    name = f"{scope}:manual"
    opened = client["cases"][name]

    assert opened["trigger"] == "manual"
    assert opened["reason"] == ""
    assert opened["flowReason"] == ""
    assert opened["saveError"] == ""
    sent = opened["payload"]
    assert sent["trigger_type"] == "manual"
    assert sent["description"] == EDITED_DESCRIPTION
    assert "editor_readonly_reason" not in sent

    response = routes.post(scope, copy.deepcopy(sent))
    assert response.status_code == 200, response.get_data(as_text=True)
    stored = routes.load(scope, ids[name])
    assert stored["schedule"] == {}
    assert stored["description"] == EDITED_DESCRIPTION


@pytest.mark.parametrize("name", sorted(SUPPORTED))
def test_a_supported_schedule_is_never_read_only(outcome, name):
    routes, ids, _cases, client = outcome
    scope, _schedule = SUPPORTED[name]
    stored = routes.load(scope, ids[name])["schedule"]
    opened = client["cases"][name]

    assert opened["reason"] == ""
    assert opened["flowReason"] == ""
    assert opened["saveError"] == ""
    assert opened["schedule"] == stored
    assert opened["payload"]["schedule"] == stored
    assert opened["label"] == routes.schedules.workflow_schedule_label("interval", copy.deepcopy(stored))
    assert opened["label"]


@pytest.mark.parametrize("name", sorted(KINDS))
def test_the_editor_reads_each_kind_as_the_server_does(outcome, name):
    routes, _ids, _cases, client = outcome
    schedules = routes.schedules
    try:
        schedules.normalize_workflow_schedule(copy.deepcopy(KINDS[name]))
        supported = True
    except schedules.WorkflowPublicValidationError as exc:
        supported = exc.public_message != KIND_ERROR
    assert client["kinds"][name] is supported


def test_the_schema_reason_still_takes_precedence_and_the_schedule_is_kept(outcome):
    _routes, _ids, _cases, client = outcome
    opened = client["cases"]["personal:schema_precedence"]

    assert opened["reason"] == SCHEMA_REASON
    assert opened["flowReason"] == SCHEMA_REASON
    assert opened["schedule"] == UNSUPPORTED
    assert opened["saveError"] == SAVE_REFUSAL
