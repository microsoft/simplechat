# test_v2_workflow_unsupported_schedule_readonly.py
#!/usr/bin/env python3
"""
Functional test for the V2 editor's handling of a stored schedule it can't show exactly.
Version: 0.261.202
Implemented in: 0.261.202

The save routes refuse or canonicalize every schedule they store, but a newer server, a direct
write or a record saved before a rule existed can leave one the V2 editor has no fields for. This
test ensures that the editor never puts a schedule of its own in place of the stored one:

* a scheduled workflow opens read-only, in both scopes and for the interval and File Sync
  triggers, when its stored schedule has a kind, calendar frequency, interval unit or weekly day the
  server doesn't define, a seconds or minutes unit stored other than exactly (the scheduler runs
  any other unit text as hours), or an interval value that isn't a JSON whole number (text, a
  fraction, a boolean, null or none). ``normalizeWorkflowDefinition`` keeps the schedule exactly as
  stored and sets the read-only reason, ``flowUnsupportedReason`` returns it (which is what makes
  the dialog read-only), and ``workflowForSave`` refuses to build a payload, so nothing is written.
  Sending the stored record back instead would be refused by the real save route, or would store a
  different schedule;
* the editor opens an interval schedule editable only when saving it keeps when the real scheduler
  runs it;
* a schedule stored with only the case and whitespace a save canonicalizes (an hours unit, and the
  kind, frequency, days, time and time zone text) or with a whole-number float opens editable,
  shows the schedule the save stores, and saves it through the real route;
* a whole-number interval value out of range, an empty weekly day list and a monthly day that isn't
  a whole number stay editable, are named by validation with the save route's message, and are
  refused by the route, so nothing is written until the author corrects them;
* ``workflowScheduleSupported`` agrees with an independent reading of the server's rules for every
  schedule the calendar parity cases cover, and for a supported schedule the editor saves exactly
  what the server reads from the stored one;
* a manual workflow, which does not use its schedule and for which the server stores none, stays
  editable, and its save stores no schedule, as before;
* supported interval and calendar schedules are never made read-only;
* the existing read-only reason for an unsupported task schema still takes precedence.

The TypeScript runs unmodified in Node through ``test_support/tsResolve.mjs``. The save routes are
the real route bodies over the real personal and group stores, and the scheduler is the real
``compute_next_run_at``.
"""

import copy
import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

import test_group_workflow_round_trip_preservation as harness  # noqa: E402  (shared real-module harness)
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_workflow_calendar_schedule_client_parity import RAW_CASES  # noqa: E402  (the parity schedules)
from test_workflow_calendar_schedules import (  # noqa: E402  (the server's cases and save routes)
    DAY_OF_MONTH_TYPE_ERROR, DAYS_ERROR, DAYS_REQUIRED_ERROR, EVERY_MINUTE, FREQUENCY_ERROR, KIND_ERROR,
    MONDAYS_NY, NOW, SETTINGS_CODE, CalendarRoutes, _calendar,
)


REPO_ROOT = harness.REPO_ROOT
GROUP_ID = harness.GROUP_ID
OWNER_ID = harness.OWNER_ID
SCOPES = ("personal", "group")
UNIT_ERROR = "Schedule unit must be seconds, minutes or hours."
MINUTES_RANGE_ERROR = "Schedule value for minutes must be between 1 and 59."
HOURS_RANGE_ERROR = "Schedule value for hours must be between 1 and 24."
# The save route's messages for a kind, frequency, unit or weekly day the server doesn't define.
VOCABULARY_ERRORS = {KIND_ERROR, FREQUENCY_ERROR, UNIT_ERROR, DAYS_ERROR}
UNSUPPORTED = {"kind": "cron", "expression": "0 8 * * 1", "timezone": "America/New_York"}
SCHEMA_REASON = (
    "This workflow contains task configuration or bindings from an unsupported schema. "
    "Its original configuration has been retained and editing is disabled."
)
SAVE_REFUSAL = "This workflow contains unsupported executable fields and cannot be saved by this editor."
EDITED_DESCRIPTION = "Edited in the V2 editor."

# Stored schedules the editor can't show exactly.
READ_ONLY_SCHEDULES = {
    "kind_cron": UNSUPPORTED,
    "frequency_fortnightly": {**MONDAYS_NY, "frequency": "fortnightly"},
    "frequency_hourly": {**MONDAYS_NY, "frequency": "hourly"},
    "frequency_missing": {key: value for key, value in MONDAYS_NY.items() if key != "frequency"},
    "weekly_day_unknown": {**MONDAYS_NY, "days_of_week": ["monday", "funday"]},
    "weekly_days_text": {**MONDAYS_NY, "days_of_week": "monday"},
    "unit_days": {"unit": "days", "value": 2},
    "unit_missing": {"value": 2},
    # The scheduler runs any unit but exactly "seconds" or "minutes" as hours.
    "unit_minutes_padded": {"unit": " Minutes ", "value": 2},
    "unit_seconds_upper": {"unit": "SECONDS", "value": 30},
    "value_text": {"unit": "minutes", "value": "5"},
    "value_fraction": {"unit": "minutes", "value": 2.5},
    "value_boolean": {"unit": "minutes", "value": True},
    "value_null": {"unit": "minutes", "value": None},
    "value_missing": {"unit": "minutes"},
}
# name: (scope, how the workflow was stored, the trigger the editor reads)
READ_ONLY_TRIGGERS = {
    "personal:interval": ("personal", "interval", "interval"),
    "group:interval": ("group", "interval", "interval"),
    "group:monitor": ("group", "monitor", "file_sync"),
    # V2 does not author personal File Sync, but it opens those workflows, and the monitor uses the schedule.
    "personal:file_sync": ("personal", "interval", "file_sync"),
}
READ_ONLY = {
    f"{trigger}:{schedule}": (*READ_ONLY_TRIGGERS[trigger], schedule)
    for trigger in READ_ONLY_TRIGGERS
    for schedule in READ_ONLY_SCHEDULES
}
# Stored schedules whose text or number form only a save canonicalizes: (stored, shown and saved).
CANONICAL = {
    "unit_hours_upper": ({"unit": "HOURS", "value": 2}, {"unit": "hours", "value": 2}),
    "unit_hours_padded": ({"unit": " Hours ", "value": 2}, {"unit": "hours", "value": 2}),
    "kind_interval_padded": ({"kind": " INTERVAL ", "unit": "minutes", "value": 5}, {"unit": "minutes", "value": 5}),
    "value_whole_float": ({"unit": "minutes", "value": 5.0}, {"unit": "minutes", "value": 5}),
    "calendar_padded": ({
        "kind": " Calendar ", "frequency": " WEEKLY ", "days_of_week": ["MONDAY", " monday "],
        "day_of_month": None, "time_of_day": " 08:00 ", "timezone": " America/New_York ",
    }, MONDAYS_NY),
}
# Stored schedules shown for validation to name: (stored, shown, the save route's message).
VALIDATION_NAMED = {
    "value_zero": ({"unit": "minutes", "value": 0}, {"unit": "minutes", "value": 0}, MINUTES_RANGE_ERROR),
    "value_ninety": ({"unit": "minutes", "value": 90}, {"unit": "minutes", "value": 90}, MINUTES_RANGE_ERROR),
    "value_negative_hours": ({"unit": "hours", "value": -3}, {"unit": "hours", "value": -3}, HOURS_RANGE_ERROR),
    "weekly_without_days": ({**MONDAYS_NY, "days_of_week": []}, {**MONDAYS_NY, "days_of_week": []},
                            DAYS_REQUIRED_ERROR),
    "monthly_day_text": (_calendar("monthly", "06:00", "UTC", day_of_month="15"),
                         _calendar("monthly", "06:00", "UTC"), DAY_OF_MONTH_TYPE_ERROR),
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
# A stored interval schedule and how long after NOW the scheduler runs it.
SCHEDULER_DELAYS = {
    "minutes_exact": ({"unit": "minutes", "value": 2}, timedelta(minutes=2)),
    "minutes_padded": ({"unit": " Minutes ", "value": 2}, timedelta(hours=2)),
    "minutes_title": ({"unit": "Minutes", "value": 2}, timedelta(hours=2)),
    "seconds_exact": ({"unit": "seconds", "value": 30}, timedelta(seconds=30)),
    "seconds_upper": ({"unit": "SECONDS", "value": 30}, timedelta(hours=30)),
    "hours_exact": ({"unit": "hours", "value": 2}, timedelta(hours=2)),
    "hours_upper": ({"unit": "HOURS", "value": 2}, timedelta(hours=2)),
    "hours_padded": ({"unit": " Hours ", "value": 2}, timedelta(hours=2)),
}
EXTRA_SCHEDULES = {
    "unit_leading_space": {"unit": " seconds", "value": 5},
    "unit_hours_tabbed": {"unit": "\thours\n", "value": 5},
    "unit_weeks": {"unit": "weeks", "value": 1},
    "value_huge_whole": {"unit": "hours", "value": 10 ** 20},
    "value_negative_whole_float": {"unit": "hours", "value": -2.0},
    "daily_days_text": {**_calendar("daily", "08:00", "UTC"), "days_of_week": "monday"},
    "not_an_object": "every minute",
}
# Every schedule whose support is compared with an independent reading of the server's rules.
SCHEDULES = {
    **{f"parity:{name}": raw for name, raw in RAW_CASES.items()},
    **{f"kind:{name}": raw for name, raw in KINDS.items()},
    **{f"read_only:{name}": raw for name, raw in READ_ONLY_SCHEDULES.items()},
    **{f"canonical:{name}": raw for name, (raw, _shown) in CANONICAL.items()},
    **{f"validation:{name}": raw for name, (raw, _shown, _message) in VALIDATION_NAMED.items()},
    **{f"scheduler:{name}": raw for name, (raw, _delay) in SCHEDULER_DELAYS.items()},
    **{f"extra:{name}": raw for name, raw in EXTRA_SCHEDULES.items()},
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
const zones = new Set(input.schedule_options.timezones);
const scopes = { personal: { type: 'personal' }, group: { type: 'group', groupId: input.group_id } };
// What the editor options route returns, with the schedule block the server builds.
const options = (scope) => ({
    definition_version: 2, supported_definition_versions: [1, 2, 3], can_manage: true, max_tasks: 50,
    agents: [], models: [], default_model: { label: 'Default model', valid: true },
    scope: scope.type === 'group' ? { type: 'group', id: scope.groupId } : { type: 'personal', id: input.owner_id },
    schedule: { ...input.schedule_options, min_interval_seconds: 1 },
});
const output = { reason: editor.WORKFLOW_UNSUPPORTED_SCHEDULE_REASON, cases: {}, schedules: {} };
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
        label: settings.workflowScheduleLabel(original.trigger_type, original.schedule, zones),
        errors: editor.workflowSettingsDraftErrors(draft, options(scope), original, null),
        saveError,
        payload,
    };
}
for (const [name, raw] of Object.entries(input.schedules)) {
    const shown = editor.normalizeWorkflowSchedule(raw);
    const opened = editor.normalizeWorkflowDefinition({ trigger_type: 'interval', schedule: raw }, scopes.personal);
    output.schedules[name] = {
        supported: settings.workflowScheduleSupported(raw),
        shown,
        forSave: settings.workflowScheduleForSave(shown, zones),
        again: editor.normalizeWorkflowSchedule(shown),
        opened: { schedule: opened.schedule, reason: opened.editor_readonly_reason ?? '' },
    };
}
console.log(JSON.stringify(output));
"""


def _js(value):
    """A value as JavaScript's JSON writes it back: a whole-number float below 1e21 is an integer."""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e21:
        return int(value)
    if isinstance(value, dict):
        return {key: _js(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_js(item) for item in value]
    return value


def _same(left, right):
    """Equal as JSON text, so True is not 1 and "5" is not 5."""
    return json.dumps(_js(left), sort_keys=True) == json.dumps(_js(right), sort_keys=True)


def _server_reading(schedules, raw):
    """What a save stores for a schedule, or the message it refuses the schedule with."""
    try:
        return {"schedule": schedules.normalize_workflow_schedule(copy.deepcopy(raw)), "error": ""}
    except schedules.WorkflowPublicValidationError as exc:
        return {"schedule": None, "error": exc.public_message}


def _whole(value):
    """A JSON whole number: an int, or a float with no fraction. Booleans and text are not numbers."""
    return type(value) is int or (type(value) is float and value.is_integer())


def _editor_can_show(schedules, raw):
    """Whether the editor can show a stored schedule exactly, read independently from the server's rules.

    It can't when the server doesn't define the kind, frequency, unit or a weekly day. An interval
    schedule also needs a whole-number value, and a seconds or minutes unit stored exactly as the
    scheduler reads it, because the scheduler runs any other unit text as hours.
    """
    if _server_reading(schedules, raw)["error"] in VOCABULARY_ERRORS:
        return False
    raw = raw if isinstance(raw, dict) else {}
    if str(raw.get("kind") or "interval").strip().lower() != "interval":
        return True
    unit = raw.get("unit")
    canonical = str(unit or "").strip().lower()
    return _whole(raw.get("value")) and (canonical == "hours" or unit == canonical)


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
    for name, (scope, stored_as, trigger, schedule_name) in READ_ONLY.items():
        ids[name] = _stored(routes, scope, stored_as, READ_ONLY_SCHEDULES[schedule_name])
        record = routes.load(scope, ids[name])
        cases[name] = {"scope": scope, "record": {**record, "trigger_type": trigger}}
    for scope in SCOPES:
        name = f"{scope}:manual"
        ids[name] = _stored(routes, scope, "manual", UNSUPPORTED)
        cases[name] = {"scope": scope, "record": routes.load(scope, ids[name])}
        for group, group_cases in (("canonical", CANONICAL), ("validation", VALIDATION_NAMED)):
            for case_name, (raw, *_rest) in group_cases.items():
                name = f"{scope}:{group}:{case_name}"
                ids[name] = _stored(routes, scope, "interval", raw)
                cases[name] = {"scope": scope, "record": routes.load(scope, ids[name])}
    for name, (scope, schedule) in SUPPORTED.items():
        ids[name] = routes.created(scope, trigger_type="interval", schedule=schedule)["id"]
        cases[name] = {"scope": scope, "record": routes.load(scope, ids[name])}
    precedence = routes.load("personal", ids["personal:interval:kind_cron"])
    precedence.update(definition_version=3, tasks=[
        {"id": "script", "type": "script", "name": "Script", "instructions": "Run the script.", "order": 1},
    ])
    cases["personal:schema_precedence"] = {"scope": "personal", "record": precedence}

    payload = {
        "group_id": GROUP_ID, "owner_id": OWNER_ID, "description": EDITED_DESCRIPTION,
        "schedule_options": routes.schedules.build_workflow_schedule_editor_options(min_interval_seconds=1),
        "cases": cases, "schedules": SCHEDULES,
    }
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", NODE_SCRIPT, str(REPO_ROOT)],
        input=json.dumps(payload, allow_nan=False), cwd=REPO_ROOT, text=True, encoding="utf-8",
        capture_output=True, timeout=120, check=False,
    )
    assert result.returncode == 0, f"Production TypeScript check failed:\n{result.stdout}\n{result.stderr}"
    return routes, ids, json.loads(result.stdout)


def test_the_application_version_includes_the_unsupported_schedule_guard():
    assert_app_version_at_least("0.261.202")


@pytest.mark.parametrize("name", sorted(READ_ONLY))
def test_a_scheduled_workflow_with_an_unsupported_schedule_opens_read_only_and_keeps_it(outcome, name):
    routes, ids, client = outcome
    scope, _stored_as, trigger, schedule_name = READ_ONLY[name]
    schedule = READ_ONLY_SCHEDULES[schedule_name]
    opened = client["cases"][name]
    server_label = routes.schedules.workflow_schedule_label(trigger, copy.deepcopy(schedule))
    stored = routes.load(scope, ids[name])["schedule"]

    assert opened["trigger"] == trigger
    assert _same(opened["schedule"], schedule)
    assert opened["reason"] == client["reason"]
    assert client["reason"].startswith("This workflow uses a schedule this editor does not support.")
    assert opened["flowReason"] == client["reason"]
    assert opened["saveError"] == SAVE_REFUSAL
    assert opened["payload"] is None
    # The workflow list still labels the stored schedule as the server does.
    assert opened["label"] == server_label
    assert _same(stored, schedule)


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("schedule_name", sorted(READ_ONLY_SCHEDULES))
def test_saving_the_stored_schedule_back_would_be_refused_or_change_it(outcome, scope, schedule_name):
    """Why the editor must not save: the route refuses the stored schedule, or stores a different one."""
    routes, _ids, _client = outcome
    raw = READ_ONLY_SCHEDULES[schedule_name]
    workflow_id = _stored(routes, scope, "interval", raw)
    reading = _server_reading(routes.schedules, raw)
    writes = routes.writes()

    response = routes.resave(scope, workflow_id, description=EDITED_DESCRIPTION)
    body = response.get_json()
    written = routes.writes() - writes
    stored = routes.load(scope, workflow_id)["schedule"]

    if reading["error"]:
        assert response.status_code == 400, body
        assert body == {"error": reading["error"], "code": SETTINGS_CODE}
        assert written == 0
        assert _same(stored, raw)
    else:
        assert response.status_code == 200, body
        assert stored == reading["schedule"]
        assert not _same(stored, raw)


@pytest.mark.parametrize("name", sorted(SCHEDULER_DELAYS))
def test_an_interval_opens_editable_only_when_saving_it_keeps_when_it_runs(outcome, name):
    """The scheduler reads the stored unit exactly and runs any but "seconds" or "minutes" as hours."""
    routes, _ids, client = outcome
    raw, delay = SCHEDULER_DELAYS[name]
    workflow = {"trigger_type": "interval", "is_enabled": True, "schedule": copy.deepcopy(raw)}
    scheduled = routes.personal.compute_next_run_at(workflow, from_time=NOW)
    saved = routes.schedules.normalize_workflow_schedule(copy.deepcopy(raw))
    rescheduled = routes.personal.compute_next_run_at({**workflow, "schedule": saved}, from_time=NOW)
    supported = client["schedules"][f"scheduler:{name}"]["supported"]

    assert scheduled == (NOW + delay).isoformat()
    assert supported is (rescheduled == scheduled)


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("case_name", sorted(CANONICAL))
def test_a_schedule_only_a_save_canonicalizes_opens_editable_and_saves(outcome, scope, case_name):
    routes, ids, client = outcome
    raw, shown = CANONICAL[case_name]
    name = f"{scope}:canonical:{case_name}"
    opened = client["cases"][name]
    server_label = routes.schedules.workflow_schedule_label("interval", copy.deepcopy(raw))
    expected = routes.schedules.normalize_workflow_schedule(copy.deepcopy(raw))

    response = routes.post(scope, copy.deepcopy(opened["payload"]))
    stored = routes.load(scope, ids[name])

    assert opened["reason"] == ""
    assert opened["flowReason"] == ""
    assert opened["saveError"] == ""
    assert opened["errors"] == []
    assert _same(opened["schedule"], shown)
    assert _same(opened["payload"]["schedule"], shown)
    assert opened["label"] == server_label
    assert opened["label"]
    assert response.status_code == 200, response.get_data(as_text=True)
    assert _same(stored["schedule"], shown)
    assert _same(stored["schedule"], expected)
    assert stored["description"] == EDITED_DESCRIPTION


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("case_name", sorted(VALIDATION_NAMED))
def test_a_value_the_save_refuses_is_kept_for_validation_to_name(outcome, scope, case_name):
    routes, ids, client = outcome
    raw, shown, message = VALIDATION_NAMED[case_name]
    name = f"{scope}:validation:{case_name}"
    opened = client["cases"][name]
    writes = routes.writes()

    response = routes.post(scope, copy.deepcopy(opened["payload"]))
    written = routes.writes() - writes
    stored = routes.load(scope, ids[name])["schedule"]

    assert opened["reason"] == ""
    assert opened["flowReason"] == ""
    assert _same(opened["schedule"], shown)
    assert opened["errors"] == [message]
    assert _same(opened["payload"]["schedule"], shown)
    assert response.status_code == 400, response.get_data(as_text=True)
    assert response.get_json() == {"error": message, "code": SETTINGS_CODE}
    assert written == 0
    assert _same(stored, raw)


@pytest.mark.parametrize("name", sorted(SCHEDULES))
def test_the_editor_supports_a_schedule_exactly_when_it_can_show_it(outcome, name):
    routes, _ids, client = outcome
    raw = SCHEDULES[name]
    read = client["schedules"][name]
    expected = _editor_can_show(routes.schedules, raw)
    reading = _server_reading(routes.schedules, raw)

    assert read["supported"] is expected
    if expected:
        # Saving what the editor shows stores what the server reads from the stored schedule, and
        # reopening it changes nothing.
        assert _same(read["forSave"], reading)
        assert _same(read["again"], read["shown"])
        assert _same(read["opened"]["schedule"], read["shown"])
        assert read["opened"]["reason"] == ""
    else:
        assert _same(read["opened"]["schedule"], raw)
        assert read["opened"]["reason"] == client["reason"]


@pytest.mark.parametrize("scope", SCOPES)
def test_a_manual_workflow_with_a_leftover_schedule_stays_editable_and_saves_none(outcome, scope):
    routes, ids, client = outcome
    name = f"{scope}:manual"
    opened = client["cases"][name]
    sent = opened["payload"]

    response = routes.post(scope, copy.deepcopy(sent))
    stored = routes.load(scope, ids[name])

    assert opened["trigger"] == "manual"
    assert opened["reason"] == ""
    assert opened["flowReason"] == ""
    assert opened["saveError"] == ""
    assert sent["trigger_type"] == "manual"
    assert sent["description"] == EDITED_DESCRIPTION
    assert "editor_readonly_reason" not in sent
    assert response.status_code == 200, response.get_data(as_text=True)
    assert stored["schedule"] == {}
    assert stored["description"] == EDITED_DESCRIPTION


@pytest.mark.parametrize("name", sorted(SUPPORTED))
def test_a_supported_schedule_is_never_read_only(outcome, name):
    routes, ids, client = outcome
    scope, _schedule = SUPPORTED[name]
    stored = routes.load(scope, ids[name])["schedule"]
    server_label = routes.schedules.workflow_schedule_label("interval", copy.deepcopy(stored))
    opened = client["cases"][name]

    assert opened["reason"] == ""
    assert opened["flowReason"] == ""
    assert opened["saveError"] == ""
    assert _same(opened["schedule"], stored)
    assert _same(opened["payload"]["schedule"], stored)
    assert opened["label"] == server_label
    assert opened["label"]


def test_the_schema_reason_still_takes_precedence_and_the_schedule_is_kept(outcome):
    _routes, _ids, client = outcome
    opened = client["cases"]["personal:schema_precedence"]

    assert opened["reason"] == SCHEMA_REASON
    assert opened["flowReason"] == SCHEMA_REASON
    assert _same(opened["schedule"], UNSUPPORTED)
    assert opened["saveError"] == SAVE_REFUSAL
