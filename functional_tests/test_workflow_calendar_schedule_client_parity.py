# test_workflow_calendar_schedule_client_parity.py
#!/usr/bin/env python3
"""
Functional test for V2 workflow editor parity with the server's calendar schedule rules.
Version: 0.261.193
Implemented in: 0.261.193

This test ensures that the V2 editor's schedule rules, which name a schedule problem before the
save, agree with the server's:

* the production TypeScript ``workflowScheduleForSave`` stores or refuses every raw schedule
  exactly as ``normalize_workflow_schedule`` does, with the same reviewed message, and
  ``workflowScheduleLabel`` reads each schedule as ``workflow_schedule_label`` does;
* for new and edited drafts in both scopes, ``workflowSettingsDraftErrors`` reports a schedule
  problem exactly when the real save route refuses the payload ``workflowForSave`` builds, with
  the route's message, including the administrator's minimum for new or changed intervals. An
  accepted draft stores the schedule the editor sent.

The TypeScript runs unmodified in Node through ``test_support/tsResolve.mjs``. The save routes
are the real route bodies over the real personal and group stores, from
``test_workflow_calendar_schedules.py``.
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
from test_workflow_calendar_schedules import (  # noqa: E402  (the server cases and save routes)
    ACCEPTED, DAY_OF_MONTH_RANGE_ERROR, DAY_OF_MONTH_TYPE_ERROR, DAYS_REQUIRED_ERROR, EVERY_MINUTE, INVALID,
    LABELS, LEGACY_INTERVAL_INPUTS, MIN_SETTING, MONDAYS_NY, SETTINGS_CODE, TIME_ERROR, WEEKDAYS_TOKYO, ZONE_ERROR,
    CalendarRoutes, _calendar, _minimum_message,
)


REPO_ROOT = harness.REPO_ROOT
GROUP_ID = harness.GROUP_ID
OWNER_ID = harness.OWNER_ID
SCOPES = ("personal", "group")

# Raw schedules beyond the server test's own cases: Python's truthiness, int() and strip() rules.
EXTRA_RAW = {
    "kind_true": {"kind": True, "unit": "minutes", "value": 5},
    "kind_zero": {"kind": 0, "unit": "minutes", "value": 5},
    "kind_empty_list": {"kind": [], "unit": "minutes", "value": 5},
    "kind_list": {"kind": ["calendar"], **MONDAYS_NY},
    "frequency_list": {**MONDAYS_NY, "frequency": ["weekly"]},
    "value_underscored": {"unit": "minutes", "value": "1_0"},
    "value_signed": {"unit": "minutes", "value": "+5"},
    "value_negative_zero": {"unit": "minutes", "value": "-0"},
    "value_huge": {"unit": "hours", "value": 1e300},
    "days_object": {**MONDAYS_NY, "days_of_week": {}},
    "days_null": {**MONDAYS_NY, "days_of_week": None},
    "days_padded": {**MONDAYS_NY, "days_of_week": ["\tSunday\n", "monday"]},
    "day_of_month_text": {**MONDAYS_NY, "frequency": "monthly", "day_of_month": "31"},
    "day_of_month_huge": {**MONDAYS_NY, "frequency": "monthly", "day_of_month": 1e20},
    "day_of_month_whole_float": {**MONDAYS_NY, "frequency": "monthly", "day_of_month": 12.0},
    "time_padded": {**MONDAYS_NY, "time_of_day": "\t08:00\n"},
    "time_trailing_newline_only": {**MONDAYS_NY, "time_of_day": "08:00\n"},
    "time_full_width_digits": {**MONDAYS_NY, "time_of_day": "\uff10\uff18:\uff10\uff10"},
    "zone_no_break_spaces": {**MONDAYS_NY, "timezone": "\u00a0UTC\u00a0"},
    "zone_inner_space": {**MONDAYS_NY, "timezone": "America/New York"},
}

# name: (scope, stored workflow, minimum, edited fields, expected route message or None when saved)
# Stored workflows are saved under the default minimum before the case raises it.
DRAFTS = {
    "new_weekly_mondays_new_york": (None, None, 1, {"trigger_type": "interval", "schedule": MONDAYS_NY}, None),
    "new_weekly_several_days": (None, None, 1, {"trigger_type": "interval", "schedule": _calendar(
        "weekly", "09:00", "Europe/Berlin", days=["friday", "monday", "wednesday"])}, None),
    "new_weekdays_tokyo": (None, None, 1, {"trigger_type": "interval", "schedule": WEEKDAYS_TOKYO}, None),
    "new_daily_london": (None, None, 1, {"trigger_type": "interval",
                                         "schedule": _calendar("daily", "18:00", "Europe/London")}, None),
    "new_monthly_day_31": (None, None, 1, {"trigger_type": "interval",
                                           "schedule": _calendar("monthly", "06:00", "UTC", day_of_month=31)}, None),
    "new_zone_padded": (None, None, 1, {"trigger_type": "interval",
                                        "schedule": {**MONDAYS_NY, "timezone": "  America/New_York  "}}, None),
    "new_zone_unknown": (None, None, 1, {"trigger_type": "interval",
                                         "schedule": {**MONDAYS_NY, "timezone": "Mars/Olympus"}}, ZONE_ERROR),
    "new_zone_wrong_case": (None, None, 1, {"trigger_type": "interval",
                                            "schedule": {**MONDAYS_NY, "timezone": "america/new_york"}}, ZONE_ERROR),
    "new_zone_empty": (None, None, 1, {"trigger_type": "interval", "schedule": {**MONDAYS_NY, "timezone": ""}},
                       ZONE_ERROR),
    "new_time_empty": (None, None, 1, {"trigger_type": "interval", "schedule": {**MONDAYS_NY, "time_of_day": ""}},
                       TIME_ERROR),
    "new_time_twelve_hour": (None, None, 1, {"trigger_type": "interval",
                                             "schedule": {**MONDAYS_NY, "time_of_day": "8:00 AM"}}, TIME_ERROR),
    "new_weekly_without_days": (None, None, 1, {"trigger_type": "interval",
                                                "schedule": {**MONDAYS_NY, "days_of_week": []}}, DAYS_REQUIRED_ERROR),
    "new_monthly_without_day": (None, None, 1, {"trigger_type": "interval", "schedule": _calendar(
        "monthly", "06:00", "UTC")}, DAY_OF_MONTH_TYPE_ERROR),
    "new_monthly_day_32": (None, None, 1, {"trigger_type": "interval", "schedule": _calendar(
        "monthly", "06:00", "UTC", day_of_month=32)}, DAY_OF_MONTH_RANGE_ERROR),
    "new_monthly_day_0": (None, None, 1, {"trigger_type": "interval", "schedule": _calendar(
        "monthly", "06:00", "UTC", day_of_month=0)}, DAY_OF_MONTH_RANGE_ERROR),
    "new_interval_under_minimum": (None, None, 300, {"trigger_type": "interval",
                                                     "schedule": {"unit": "minutes", "value": 4}},
                                   _minimum_message("5 minutes")),
    "new_interval_at_minimum": (None, None, 300, {"trigger_type": "interval",
                                                  "schedule": {"unit": "minutes", "value": 5}}, None),
    "new_interval_under_largest_minimum": (None, None, 86400, {"trigger_type": "interval",
                                                               "schedule": {"unit": "hours", "value": 23}},
                                           _minimum_message("24 hours")),
    "new_interval_at_largest_minimum": (None, None, 86400, {"trigger_type": "interval",
                                                            "schedule": {"unit": "hours", "value": 24}}, None),
    "new_calendar_at_largest_minimum": (None, None, 86400, {"trigger_type": "interval", "schedule": MONDAYS_NY},
                                        None),
    "stored_interval_described_after_minimum_raised": (None, "interval", 300,
                                                       {"description": "Still every minute."}, None),
    "stored_interval_paused_after_minimum_raised": (None, "interval", 300, {"is_enabled": False}, None),
    "stored_interval_changed_under_minimum": (None, "interval", 300, {"schedule": {"unit": "minutes", "value": 2}},
                                              _minimum_message("5 minutes")),
    "stored_interval_to_calendar": (None, "interval", 86400, {"schedule": MONDAYS_NY}, None),
    "stored_calendar_to_interval_under_minimum": (None, "calendar", 300, {"schedule": EVERY_MINUTE},
                                                  _minimum_message("5 minutes")),
    "stored_calendar_new_time": (None, "calendar", 1, {"schedule": {**MONDAYS_NY, "time_of_day": "09:00"}}, None),
    "stored_calendar_bad_zone": (None, "calendar", 1, {"schedule": {**MONDAYS_NY, "timezone": "Mars/Olympus"}},
                                 ZONE_ERROR),
    "stored_calendar_to_manual": (None, "calendar", 1, {"trigger_type": "manual"}, None),
    "stored_manual_to_calendar": (None, "manual", 1, {"trigger_type": "interval", "schedule": WEEKDAYS_TOKYO}, None),
    "stored_manual_to_interval_under_minimum": (None, "manual", 300,
                                                {"trigger_type": "interval", "schedule": EVERY_MINUTE},
                                                _minimum_message("5 minutes")),
    "stored_monitor_to_calendar": ("group", "monitor", 1, {"schedule": WEEKDAYS_TOKYO}, None),
    "stored_monitor_described_after_minimum_raised": ("group", "monitor", 300,
                                                      {"description": "Still every minute."}, None),
    "stored_monitor_changed_under_minimum": ("group", "monitor", 300, {"schedule": {"unit": "minutes", "value": 3}},
                                             _minimum_message("5 minutes")),
}
DRAFT_CASES = [
    (scope, name) for name, (only, *_rest) in sorted(DRAFTS.items()) for scope in SCOPES if only in (None, scope)
]

NODE_SCRIPT = r"""
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.argv[1];
const input = JSON.parse(readFileSync(0, 'utf8'));
await import(pathToFileURL(path.join(root, 'functional_tests', 'test_support', 'tsResolve.mjs')));
const lib = path.join(root, 'application', 'v2_ui', 'src', 'lib');
const editor = await import(pathToFileURL(path.join(lib, 'workflowEditor.ts')));
const settings = await import(pathToFileURL(path.join(lib, 'workflowSettings.ts')));
const zones = new Set(input.schedule_options.timezones);
const scopes = { personal: { type: 'personal' }, group: { type: 'group', groupId: input.group_id } };
// What the editor options route returns, with the schedule block the server builds.
const options = (scope, minimum) => ({
    definition_version: 2, supported_definition_versions: [1, 2, 3], can_manage: true, max_tasks: 50,
    agents: [], models: [], default_model: { label: 'Default model', valid: true },
    scope: scope.type === 'group' ? { type: 'group', id: scope.groupId } : { type: 'personal', id: input.owner_id },
    schedule: { ...input.schedule_options, min_interval_seconds: minimum },
});
const output = { normalized: {}, labels: {}, drafts: {} };
for (const [name, raw] of Object.entries(input.raw)) {
    output.normalized[name] = settings.workflowScheduleForSave(raw, zones);
}
for (const [name, [triggerType, raw]] of Object.entries(input.labels)) {
    output.labels[name] = settings.workflowScheduleLabel(triggerType, raw, zones);
}
for (const [name, testCase] of Object.entries(input.drafts)) {
    const scope = scopes[testCase.scope];
    const original = testCase.record ? editor.normalizeWorkflowDefinition(testCase.record, scope) : null;
    let draft;
    if (original) {
        draft = { ...structuredClone(original), ...testCase.fields };
    } else {
        const blank = editor.newWorkflowDefinition(scope);
        draft = {
            ...blank,
            name: 'Calendar draft',
            tasks: blank.tasks.map((task) => ({ ...task, name: 'Summarize', instructions: 'Summarize the week.' })),
            ...testCase.fields,
        };
    }
    // The schedule fields write the editor's shape, as normalizeWorkflowSchedule reads it.
    if (testCase.fields.schedule) draft.schedule = editor.normalizeWorkflowSchedule(testCase.fields.schedule);
    const caseOptions = options(scope, testCase.minimum);
    const payload = editor.workflowForSave(draft, original, scope);
    output.drafts[name] = {
        errors: editor.workflowSettingsDraftErrors(draft, caseOptions, original, null),
        payload,
        label: editor.workflowScheduleLabel(payload.trigger_type, payload.schedule, editor.workflowScheduleTimezones(caseOptions)),
    };
}
console.log(JSON.stringify(output));
"""


def _json_safe(value):
    try:
        json.dumps(value, allow_nan=False)
    except ValueError:
        return False
    return True


def _raw_cases():
    cases = {f"accepted:{name}": raw for name, (raw, _expected) in ACCEPTED.items()}
    cases.update({f"invalid:{name}": raw for name, (raw, _message) in INVALID.items()})
    cases.update({f"interval:{index}": raw for index, raw in enumerate(LEGACY_INTERVAL_INPUTS) if _json_safe(raw)})
    cases.update({f"extra:{name}": raw for name, raw in EXTRA_RAW.items()})
    return cases


RAW_CASES = _raw_cases()


def _stored(routes, scope, kind):
    """Save the workflow a draft case edits, under the default minimum, and load it as the editor does."""
    if kind == "monitor":
        response = routes.post("group", harness.monitored_workflow(schedule=EVERY_MINUTE))
        assert response.status_code == 201, response.get_data(as_text=True)
        workflow_id = response.json["workflow"]["id"]
    else:
        fields = {
            "interval": {"trigger_type": "interval", "schedule": EVERY_MINUTE},
            "calendar": {"trigger_type": "interval", "schedule": MONDAYS_NY},
            "manual": {},
        }[kind]
        workflow_id = routes.created(scope, **fields)["id"]
    return routes.load(scope, workflow_id)


@pytest.fixture(scope="module")
def outcome():
    routes = CalendarRoutes()
    schedules = routes.schedules
    records = {
        (scope, name): _stored(routes, scope, DRAFTS[name][1]) if DRAFTS[name][1] else None
        for scope, name in DRAFT_CASES
    }
    payload = {
        "group_id": GROUP_ID, "owner_id": OWNER_ID,
        "schedule_options": schedules.build_workflow_schedule_editor_options(min_interval_seconds=1),
        "raw": RAW_CASES,
        "labels": {str(index): [trigger_type, schedule] for index, (trigger_type, schedule, _label) in enumerate(LABELS)},
        "drafts": {
            f"{scope}:{name}": {
                "scope": scope, "record": records[(scope, name)], "minimum": DRAFTS[name][2], "fields": DRAFTS[name][3],
            }
            for scope, name in DRAFT_CASES
        },
    }
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", NODE_SCRIPT, str(REPO_ROOT)],
        input=json.dumps(payload, allow_nan=False), cwd=REPO_ROOT, text=True, encoding="utf-8",
        capture_output=True, timeout=120, check=False,
    )
    assert result.returncode == 0, f"Production TypeScript check failed:\n{result.stdout}\n{result.stderr}"
    client = json.loads(result.stdout)

    # Send each draft's payload to the real save route, under the case's minimum.
    saves = {}
    for scope, name in DRAFT_CASES:
        routes.store.settings[MIN_SETTING] = DRAFTS[name][2]
        writes = routes.writes()
        response = routes.post(scope, copy.deepcopy(client["drafts"][f"{scope}:{name}"]["payload"]))
        saves[(scope, name)] = (response.status_code, response.get_json(), routes.writes() - writes)
    routes.store.settings.pop(MIN_SETTING, None)
    return schedules, client, saves


def test_the_application_version_includes_calendar_schedule_parity():
    assert_app_version_at_least("0.261.193")


@pytest.mark.parametrize("name", sorted(RAW_CASES))
def test_the_editor_stores_or_refuses_each_schedule_as_the_server_does(outcome, name):
    schedules, client, _saves = outcome
    raw = copy.deepcopy(RAW_CASES[name])
    try:
        expected = {"schedule": schedules.normalize_workflow_schedule(raw), "error": ""}
    except schedules.WorkflowPublicValidationError as exc:
        expected = {"schedule": None, "error": exc.public_message}
    assert client["normalized"][name] == expected


@pytest.mark.parametrize("index", range(len(LABELS)))
def test_the_editor_labels_each_schedule_as_the_server_does(outcome, index):
    schedules, client, _saves = outcome
    trigger_type, schedule, label = LABELS[index]
    assert schedules.workflow_schedule_label(trigger_type, copy.deepcopy(schedule)) == label
    assert client["labels"][str(index)] == label


@pytest.mark.parametrize("scope, name", DRAFT_CASES)
def test_the_editor_names_a_schedule_problem_exactly_when_the_save_route_refuses_it(outcome, scope, name):
    schedules, client, saves = outcome
    expected_message = DRAFTS[name][4]
    drafted = client["drafts"][f"{scope}:{name}"]
    status, body, writes = saves[(scope, name)]

    if expected_message:
        assert drafted["errors"][:1] == [expected_message]
        assert status == 400, body
        assert body == {"error": expected_message, "code": SETTINGS_CODE}
        assert writes == 0
        return

    assert drafted["errors"] == []
    assert status in (200, 201), body
    saved = body["workflow"]
    sent = drafted["payload"]
    if saved["trigger_type"] == "manual":
        assert saved["schedule"] == {}
        assert drafted["label"] == ""
    else:
        assert saved["schedule"] == sent["schedule"]
        assert drafted["label"] == schedules.workflow_schedule_label(saved["trigger_type"], saved["schedule"])
        assert drafted["label"]
