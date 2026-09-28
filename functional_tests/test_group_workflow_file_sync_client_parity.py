# test_group_workflow_file_sync_client_parity.py
#!/usr/bin/env python3
"""
Functional test for the seam between the V2 workflow editor's settings rules and the save routes.
Version: 0.261.149
Implemented in: 0.261.141

This test ensures that the V2 editor's client-side File Sync, trigger, schedule and Analyze rules
agree with the real server in both workflow scopes, message for message, and that the editor's
read-only alert summary resolves stored alerts the same way the server does.

* The client half runs the production TypeScript (`lib/workflowEditor.ts`, which applies
  `lib/workflowSettings.ts`) under Node. For each case it normalizes the draft, validates it with
  the real editor validators, and builds the exact save payload with `workflowForSave`.
* The server half posts that payload through the real save route bodies and the real
  `save_personal_workflow` and `save_group_workflow`, using the harness of
  `test_workflow_settings_reviewed_messages.py`. A stored case is first saved for real, then
  changed in the store the way an older or classic writer could leave it, and loaded through the
  real getter before the editor sees it; the editor then makes an ordinary edit and saves.
* For every case, the editor allows the save exactly when the server accepts its payload. Each
  refused case has a single reason. When the server refuses with a reviewed settings message, the
  editor's first settings message is the same text; when it refuses for another reason, the
  editor's settings rules find nothing.
* Two differences are deliberate, and asserted as such. More than 10 sources: the server silently
  keeps the first 10, so the editor refuses instead of dropping a selection. A deleted personal
  source: V2 does not list personal sources, so only the server's reviewed 400 can report it.
* Raw request values reach the settings rules unchanged in a second set of cases, so the
  client's Python semantics (``str(value or '')``, ``strip``, ``_normalize_bool`` and ``int``)
  are compared with the real functions on the values a request can carry.
* No create payload carries a ``definition_revision``, so the server's deleted-workflow refusal can
  never block a create.
* `workflowAlertSummary` is compared with the real `resolve_workflow_alert_config`.

The M6 classic alerts link, and its `workflowAlertsEditableInClassic` predicate, were removed in
0.261.144 when native alert editing replaced them; `test_workflow_alert_client_parity.py` covers
the alert editor.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

from test_group_workflow_round_trip_preservation import (  # noqa: E402  (shared real-store harness)
    GROUP_ID,
    OTHER_GROUP_ID,
    OWNER_ID,
    GroupWorkflowStore,
    monitored_workflow,
)
from test_workflow_alert_reviewed_messages import _payload  # noqa: E402
from test_workflow_settings_reviewed_messages import (  # noqa: E402  (save routes over the real stores)
    PERSONAL_SOURCE_ID,
    SOURCE_UNAVAILABLE,
    SettingsRoutes,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FINANCE = {"scope_type": "group", "scope_id": GROUP_ID, "source_id": "finance-share"}
HOME = {"scope_type": "personal", "scope_id": OWNER_ID, "source_id": PERSONAL_SOURCE_ID}
LISTED_SOURCES = [{
    "scope_type": "group", "scope_id": GROUP_ID, "source_id": "finance-share", "name": "Finance share",
    "source_type": "smb", "enabled": True, "label": "Finance share (Group)",
}]
SETTINGS_CODES = {"invalid_workflow_settings", "file_sync_source_unavailable"}
F3 = "To continue only when changes are found, File Sync must wait for the sync to complete."
F4 = "Group File Sync must be enabled before a group workflow can use File Sync sources."
F5 = "Group workflows can only use File Sync sources from this group."
F6 = "Select at least one File Sync source for this workflow."
F7 = "Select at least one group File Sync source for this workflow."
T3 = "Monitor File Sync Changes workflows require File Sync before run."
T5 = "Monitor File Sync Changes workflows must continue only when changes are found."

NODE_SCRIPT = r"""
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.argv[1];
const input = JSON.parse(readFileSync(0, 'utf8'));
await import(pathToFileURL(path.join(root, 'functional_tests', 'test_support', 'tsResolve.mjs')));
const editor = await import(pathToFileURL(path.join(root, 'application', 'v2_ui', 'src', 'lib', 'workflowEditor.ts')));
const settings = await import(pathToFileURL(path.join(root, 'application', 'v2_ui', 'src', 'lib', 'workflowSettings.ts')));
const baseOptions = {
    definition_version: 2, supported_definition_versions: [1, 2, 3], can_manage: true, max_tasks: 50,
    agents: [], models: [], default_model: { label: 'Default model', valid: true },
};
const scopes = {
    group: { scope: { type: 'group', groupId: input.group_id }, options: { ...baseOptions, scope: { type: 'group', id: input.group_id } } },
    personal: { scope: { type: 'personal' }, options: { ...baseOptions, scope: { type: 'personal', id: input.owner_id } } },
};
const output = { cases: {}, alerts: {}, raw: {} };
for (const [name, testCase] of Object.entries(input.cases)) {
    const { scope, options } = scopes[testCase.scope];
    // A stored case opens the loaded record and makes an ordinary edit; a create starts from its draft.
    const original = testCase.original ? editor.normalizeWorkflowDefinition(testCase.original, scope) : null;
    const draft = original
        ? { ...structuredClone(original), description: 'Edited in V2.' }
        : editor.normalizeWorkflowDefinition(testCase.payload, scope);
    output.cases[name] = {
        errors: editor.workflowValidationErrors(draft, options, original, testCase.listing),
        settings: editor.workflowSettingsDraftErrors(draft, options, original, testCase.listing),
        payload: editor.workflowForSave(draft, original, scope),
    };
}
for (const [name, record] of Object.entries(input.alerts)) {
    output.alerts[name] = editor.workflowAlertSummary(record);
}
// Raw payloads go straight to the rules, as the server receives them, with the group's real sources.
for (const [name, rawCase] of Object.entries(input.raw)) {
    const context = rawCase.scope === 'group'
        ? { scope: { type: 'group', groupId: input.group_id }, fileSyncEnabled: true, availableSourceKeys: new Set(input.available) }
        : { scope: { type: 'personal' }, fileSyncEnabled: null, availableSourceKeys: null };
    output.raw[name] = settings.workflowSettingsErrors(rawCase.payload, null, context);
}
console.log(JSON.stringify(output));
"""


def _file_sync(**overrides):
    config = {
        "enabled": True, "wait_mode": "complete", "continue_mode": "changed",
        "use_changed_documents": True, "sources": [dict(FINANCE)],
    }
    config.update(overrides)
    return config


def _draft(trigger_type="file_sync", schedule=None, file_sync=None, analyze_documents=(), **overrides):
    """A V2-shaped group draft whose first task analyzes the given documents."""
    record = monitored_workflow(
        trigger_type=trigger_type,
        schedule=schedule or {"unit": "minutes", "value": 30},
        file_sync=file_sync if file_sync is not None else _file_sync(),
        **overrides,
    )
    record["tasks"][0]["document_action"] = {
        "type": "analyze", "document_ids": list(analyze_documents), "analysis_mode": "per_document",
        "target_mode": "selected",
    }
    record["tasks"][1]["document_action"] = {"type": "none"}
    return record


def _personal_file_sync(**overrides):
    config = {
        "enabled": True, "wait_mode": "complete", "continue_mode": "changed",
        "use_changed_documents": True, "sources": [dict(HOME)],
    }
    config.update(overrides)
    return config


def _personal(trigger_type="manual", schedule=None, file_sync=None):
    """A valid personal definition with two instruction tasks."""
    record = _payload("personal", trigger_type=trigger_type, schedule=schedule or {"unit": "minutes", "value": 30})
    if file_sync is not None:
        record["file_sync"] = file_sync
    return record


def _case(scope, draft, expected, stored=None, file_sync_on=True):
    """`expected` is "accept", "refuse" (a refusal outside the settings rules) or the reviewed message.

    With `stored`, the draft is saved first and those fields then replace the stored ones.
    `file_sync_on=False` turns group File Sync off for the save and for the editor's source list.
    """
    return {"scope": scope, "draft": draft, "expected": expected, "stored": stored, "file_sync_on": file_sync_on}


MONITOR = _personal("file_sync", file_sync=_personal_file_sync())
CASES = {
    # Group creates.
    "monitor_valid": _case("group", _draft(), "accept"),
    "monitor_continue_always": _case("group", _draft(file_sync=_file_sync(continue_mode="always")), T5),
    "monitor_queued": _case("group", _draft(file_sync=_file_sync(wait_mode="queued")), F3),
    "monitor_without_file_sync_enabled": _case(
        "group", _draft(file_sync=_file_sync(enabled=False), analyze_documents=["policy-doc"]), T3,
    ),
    "monitor_without_sources": _case("group", _draft(file_sync=_file_sync(sources=[])), F7),
    "monitor_other_group_source": _case("group", _draft(file_sync=_file_sync(sources=[
        {"scope_type": "group", "scope_id": OTHER_GROUP_ID, "source_id": "other-share"},
    ])), F5),
    "monitor_unavailable_source": _case("group", _draft(file_sync=_file_sync(sources=[
        {"scope_type": "group", "scope_id": GROUP_ID, "source_id": "deleted-share"},
    ])), SOURCE_UNAVAILABLE),
    "monitor_59_minutes": _case("group", _draft(schedule={"unit": "minutes", "value": 59}), "accept"),
    "monitor_90_minutes": _case("group", _draft(schedule={"unit": "minutes", "value": 90}),
                                "Schedule value for minutes must be between 1 and 59."),
    "monitor_24_hours": _case("group", _draft(schedule={"unit": "hours", "value": 24}), "accept"),
    "monitor_25_hours": _case("group", _draft(schedule={"unit": "hours", "value": 25}),
                              "Schedule value for hours must be between 1 and 24."),
    "monitor_analyze_without_changed_files": _case(
        "group", _draft(file_sync=_file_sync(use_changed_documents=False)), "refuse",
    ),
    "monitor_analyze_selected_without_changed_files": _case(
        "group", _draft(file_sync=_file_sync(use_changed_documents=False), analyze_documents=["policy-doc"]), "accept",
    ),
    "interval_59_seconds": _case(
        "group", _draft("interval", {"unit": "seconds", "value": 59}, _file_sync(enabled=False, sources=[])), "refuse",
    ),
    "interval_59_seconds_with_documents": _case("group", _draft(
        "interval", {"unit": "seconds", "value": 59}, _file_sync(enabled=False, sources=[]), ["policy-doc"],
    ), "accept"),
    "interval_60_seconds": _case("group", _draft(
        "interval", {"unit": "seconds", "value": 60}, _file_sync(enabled=False, sources=[]), ["policy-doc"],
    ), "Schedule value for seconds must be between 1 and 59."),
    "manual_before_run_queued_always": _case(
        "group", _draft("manual", file_sync=_file_sync(wait_mode="queued", continue_mode="always")), "accept",
    ),
    "manual_before_run_queued_changed": _case(
        "group", _draft("manual", file_sync=_file_sync(wait_mode="queued", continue_mode="changed")), F3,
    ),
    "manual_before_run_without_sources": _case("group", _draft("manual", file_sync=_file_sync(sources=[])), F7),
    "manual_without_file_sync": _case("group", _draft(
        "manual", file_sync=_file_sync(enabled=False, sources=[]), analyze_documents=["policy-doc"],
    ), "accept"),
    "manual_without_file_sync_analyze_empty": _case(
        "group", _draft("manual", file_sync=_file_sync(enabled=False, sources=[])), "refuse",
    ),
    "group_file_sync_off": _case(
        "group", _draft("manual", file_sync=_file_sync(continue_mode="always")), F4, file_sync_on=False,
    ),
    "group_file_sync_off_unused": _case("group", _draft(
        "manual", file_sync=_file_sync(enabled=False, sources=[]), analyze_documents=["policy-doc"],
    ), "accept", file_sync_on=False),
    "create_with_a_stray_revision": _case("group", {**_draft(), "definition_revision": "f" * 64}, "accept"),
    # Group records changed after they were stored.
    "stored_monitor_unchanged": _case("group", _draft(), "accept", stored={}),
    "stored_deleted_source": _case("group", _draft(), SOURCE_UNAVAILABLE, stored={"file_sync": _file_sync(sources=[{
        "scope_type": "group", "scope_id": GROUP_ID, "source_id": "deleted-share",
        "name": "Deleted share", "source_type": "smb",
    }])}),
    "stored_group_file_sync_off": _case("group", _draft(), F4, stored={}, file_sync_on=False),
    # Personal creates.
    "personal_manual": _case("personal", _personal(), "accept"),
    "personal_interval_24_hours": _case("personal", _personal("interval", {"unit": "hours", "value": 24}), "accept"),
    "personal_interval_90_minutes": _case("personal", _personal("interval", {"unit": "minutes", "value": 90}),
                                          "Schedule value for minutes must be between 1 and 59."),
    # Personal records changed after they were stored; V2 sends their File Sync back as loaded.
    "personal_stored_monitor": _case("personal", MONITOR, "accept", stored={}),
    "personal_stored_monitor_continue_always": _case(
        "personal", MONITOR, T5, stored={"file_sync": _personal_file_sync(continue_mode="always")},
    ),
    "personal_stored_monitor_without_file_sync": _case(
        "personal", MONITOR, T3, stored={"file_sync": {"source_id": "legacy-source", "delete_policy": "preserve"}},
    ),
    "personal_stored_monitor_61_minutes": _case(
        "personal", MONITOR, "Schedule value for minutes must be between 1 and 59.",
        stored={"schedule": {"unit": "minutes", "value": 61}},
    ),
    "personal_stored_queued_changed": _case(
        "personal", _personal(file_sync=_personal_file_sync(continue_mode="always")), F3,
        stored={"file_sync": _personal_file_sync(wait_mode="queued")},
    ),
    "personal_stored_wait_mode": _case(
        "personal", _personal(), "File Sync wait mode must be complete or queued.",
        stored={"file_sync": _personal_file_sync(wait_mode="later", continue_mode="always")},
    ),
    "personal_stored_continue_mode": _case(
        "personal", _personal(), "File Sync continue mode must be always or changed.",
        stored={"file_sync": _personal_file_sync(continue_mode="sometimes")},
    ),
    "personal_stored_without_sources": _case(
        "personal", _personal(), F6, stored={"file_sync": _personal_file_sync(continue_mode="always", sources=[])},
    ),
    "personal_stored_other_group_source": _case("personal", _personal(), "accept", stored={"file_sync": _personal_file_sync(
        continue_mode="always", sources=[{"scope_type": "group", "scope_id": OTHER_GROUP_ID, "source_id": "other-share"}],
    )}),
    "personal_stored_legacy_file_sync": _case(
        "personal", _personal(), "accept", stored={"file_sync": {"source_id": "legacy-source", "delete_policy": "preserve"}},
    ),
}
# The editor cannot see these; each has its own test below.
DIVERGENT_CASES = {
    "eleven_sources": _case("group", _draft(file_sync=_file_sync(sources=[
        {"scope_type": "group", "scope_id": GROUP_ID, "source_id": f"share-{index}"} for index in range(11)
    ])), "divergent"),
    "personal_stored_deleted_source": _case("personal", _personal(), "divergent", stored={"file_sync": _personal_file_sync(
        continue_mode="always", sources=[{"scope_type": "personal", "scope_id": OWNER_ID, "source_id": "gone-share"}],
    )}),
}

RAW_SCHEDULE_VALUES = {
    "int": 5, "text": "5", "spaced_text": " 5 ", "signed_text": "+5", "zero_padded_text": "05",
    "underscored_text": "1_0", "decimal_text": "5.0", "exponent_text": "1e3", "double_underscore": "1__0",
    "leading_underscore": "_1", "decimal": 5.9, "negative": -1, "zero": 0, "large": 1000,
    "true": True, "false": False, "null": None, "list": [], "object": {}, "empty_text": "",
}
RAW_SCHEDULE_UNITS = {
    "upper": "MINUTES", "spaced": " minutes ", "tab": "Hours\t", "empty": "", "null": None,
    "singular": "minute", "number": 5, "seconds_upper": "SECONDS",
}
RAW_TRIGGERS = {
    "empty": "", "spaces": "  ", "null": None, "zero": 0, "upper_interval": "INTERVAL",
    "spaced_manual": " manual ", "weekly": "weekly", "true": True, "list": ["manual"], "dashed": "file-sync",
}
RAW_FILE_SYNC = {
    "enabled_yes": {"enabled": "yes"}, "enabled_one": {"enabled": 1}, "enabled_zero": {"enabled": 0},
    "enabled_list": {"enabled": []}, "enabled_true_text": {"enabled": "TRUE "}, "enabled_null": {"enabled": None},
    "enabled_off_text": {"enabled": "off", "sources": []}, "wait_upper": {"wait_mode": "COMPLETE"},
    "wait_spaced_queued": {"wait_mode": " queued "}, "wait_null": {"wait_mode": None},
    "wait_empty": {"wait_mode": ""}, "wait_zero": {"wait_mode": 0}, "wait_true": {"wait_mode": True},
    "continue_upper": {"continue_mode": "CHANGED"}, "continue_true": {"continue_mode": True},
    "queued_changed_mixed_case": {"wait_mode": "Queued", "continue_mode": " Changed"},
    "sources_not_a_list": {"sources": "finance-share"}, "sources_not_objects": {"sources": ["finance-share", 5, None]},
}
RAW_GROUP_SOURCES = {
    "whitespace_id": [{"scope_type": "group", "source_id": "   "}],
    "id_alias": [{"id": "finance-share"}],
    "duplicate": [FINANCE, FINANCE],
    "upper_scope_spaced_ids": [{"scope_type": "GROUP", "scope_id": f" {GROUP_ID} ", "source_id": " finance-share "}],
    "blank_scope_defaults_to_group": [{"scope_type": "", "scope_id": "", "source_id": "finance-share"}],
    "unknown_after_valid": [FINANCE, {"scope_type": "group", "source_id": "missing-share"}],
    "foreign_scope_without_id": [{"scope_type": "group", "scope_id": OTHER_GROUP_ID, "source_id": ""}],
    "personal_scope": [{"scope_type": "personal", "source_id": "finance-share"}],
}
RAW_PERSONAL_SOURCES = {
    "upper_scope": [{"scope_type": "PERSONAL", "scope_id": "someone-else", "source_id": f" {PERSONAL_SOURCE_ID} "}],
    "missing_scope_is_skipped": [{"source_id": PERSONAL_SOURCE_ID}],
    "unknown_scope_is_skipped": [{"scope_type": "team", "source_id": PERSONAL_SOURCE_ID}],
    "blank_id_is_skipped": [{"scope_type": "public", "scope_id": "handbook", "source_id": ""}],
    "duplicate": [HOME, HOME],
    "group_source": [FINANCE],
}


def _raw_payload(scope, **fields):
    """A valid definition with File Sync before run, where only the raw fields under test vary."""
    file_sync = {
        "enabled": True, "wait_mode": "complete", "continue_mode": "always", "use_changed_documents": True,
        "sources": [dict(FINANCE if scope == "group" else HOME)],
    }
    file_sync.update(fields.pop("file_sync", {}))
    payload = _payload(scope, trigger_type="manual", schedule={"unit": "minutes", "value": 30}, file_sync=file_sync)
    payload.update(fields)
    return payload


RAW_CASES = {
    **{f"{scope}-schedule-value-{name}": (scope, _raw_payload(scope, trigger_type="interval", schedule={"unit": "minutes", "value": value}))
       for scope in ("personal", "group") for name, value in RAW_SCHEDULE_VALUES.items()},
    **{f"{scope}-schedule-unit-{name}": (scope, _raw_payload(scope, trigger_type="interval", schedule={"unit": unit, "value": 5}))
       for scope in ("personal", "group") for name, unit in RAW_SCHEDULE_UNITS.items()},
    **{f"{scope}-trigger-{name}": (scope, _raw_payload(scope, trigger_type=trigger))
       for scope in ("personal", "group") for name, trigger in RAW_TRIGGERS.items()},
    **{f"{scope}-file-sync-{name}": (scope, _raw_payload(scope, file_sync=config))
       for scope in ("personal", "group") for name, config in RAW_FILE_SYNC.items()},
    **{f"group-sources-{name}": ("group", _raw_payload("group", file_sync={"sources": sources}))
       for name, sources in RAW_GROUP_SOURCES.items()},
    **{f"personal-sources-{name}": ("personal", _raw_payload("personal", file_sync={"sources": sources}))
       for name, sources in RAW_PERSONAL_SOURCES.items()},
}

ALERT_RECORDS = {
    "empty": {},
    "legacy_priority_only": {"alert_priority": "high"},
    "unknown_priority": {"alert_priority": "urgent"},
    "every_run": {"alert_mode": "every_run", "alert_priority": "low", "alert_rules": []},
    "explicit_rules": {"alert_mode": "rules", "alert_priority": "none", "alert_rules": [{"id": "a"}, {"id": "b"}]},
    "rules_without_mode": {"alert_priority": "medium", "alert_rules": [{"id": "a"}, {"id": "b"}, {"id": "c"}]},
    "spaced_mode": {"alert_mode": " OFF ", "alert_priority": "high", "alert_rules": [{"id": "a"}]},
    "unknown_mode_with_priority": {"alert_mode": "sometimes", "alert_priority": "medium"},
    "unknown_mode_with_rules": {"alert_mode": "sometimes", "alert_rules": [{"id": "a"}]},
    "rules_not_a_list": {"alert_rules": "not-a-list", "alert_priority": "none"},
    "off_with_rules_kept": {"alert_mode": "off", "alert_priority": "low", "alert_rules": [{"id": "a"}]},
}


def _listing(case):
    """The group source list the editor holds: the flag, and the sources only when File Sync is on."""
    if case["scope"] != "group":
        return None
    return {"fileSyncEnabled": case["file_sync_on"], "sources": LISTED_SOURCES if case["file_sync_on"] else []}


def _load(routes, scope, workflow_id):
    if scope == "group":
        return routes.store.module.get_group_workflow(GROUP_ID, workflow_id)
    return routes.store.modules["functions_personal_workflows"].get_personal_workflow(OWNER_ID, workflow_id)


def _server(routes, case, payload):
    """Post exactly what the editor would send, with group File Sync in the case's state."""
    if not case["file_sync_on"]:
        routes.store.file_sync_groups.discard(GROUP_ID)
    try:
        return routes.post(case["scope"], copy.deepcopy(payload))
    finally:
        routes.store.file_sync_groups.add(GROUP_ID)


@pytest.fixture(scope="module")
def parity():
    routes = SettingsRoutes()
    node_cases = {}
    for name, case in {**CASES, **DIVERGENT_CASES}.items():
        original = None
        if case["stored"] is not None:
            created = routes.post(case["scope"], copy.deepcopy(case["draft"]))
            assert created.status_code == 201, (name, created.get_data(as_text=True))
            workflow_id = created.json["workflow"]["id"]
            routes.container(case["scope"]).items[(routes.partition(case["scope"]), workflow_id)].update(
                copy.deepcopy(case["stored"]),
            )
            original = _load(routes, case["scope"], workflow_id)
        node_cases[name] = {"scope": case["scope"], "payload": case["draft"], "original": original, "listing": _listing(case)}
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", NODE_SCRIPT, str(REPO_ROOT)],
        input=json.dumps({
            "group_id": GROUP_ID, "owner_id": OWNER_ID, "cases": node_cases, "alerts": ALERT_RECORDS,
            "raw": {name: {"scope": scope, "payload": payload} for name, (scope, payload) in RAW_CASES.items()},
            # The group's real sources in the save harness, which the editor's source list would offer.
            "available": [f"group:{GROUP_ID}:finance-share"],
        }),
        cwd=REPO_ROOT, text=True, capture_output=True, timeout=60, check=False,
    )
    assert result.returncode == 0, f"Production TypeScript check failed:\n{result.stdout}\n{result.stderr}"
    return routes, json.loads(result.stdout), node_cases


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_editor_and_the_server_agree_on_each_save(parity, name):
    routes, client, _ = parity
    case, outcome = CASES[name], client["cases"][name]

    response = _server(routes, case, outcome["payload"])

    if case["expected"] == "accept":
        assert response.status_code in (200, 201), response.get_data(as_text=True)
        assert outcome["errors"] == [], outcome["errors"]
        assert outcome["settings"] == []
        return
    assert response.status_code == 400, response.get_data(as_text=True)
    assert outcome["errors"], "The editor allowed a save the server refuses."
    if case["expected"] == "refuse":
        # Refused outside the settings rules, which must then find nothing.
        assert response.json.get("code") not in SETTINGS_CODES, response.json
        assert outcome["settings"] == [], outcome["settings"]
    else:
        assert response.json["error"] == case["expected"]
        assert response.json["code"] in SETTINGS_CODES
        assert outcome["settings"][:1] == [case["expected"]], outcome["settings"]
        assert case["expected"] in outcome["errors"]


@pytest.mark.parametrize("name", sorted(RAW_CASES))
def test_raw_request_values_get_the_same_answer(parity, name):
    """The client's rules read raw JSON values exactly as the real save functions do."""
    routes, client, _ = parity
    scope, payload = RAW_CASES[name]

    response = routes.post(scope, copy.deepcopy(payload))

    if response.status_code == 201:
        assert client["raw"][name] == [], client["raw"][name]
    else:
        assert response.status_code == 400, response.get_data(as_text=True)
        assert response.json["code"] in SETTINGS_CODES, response.json
        assert client["raw"][name][:1] == [response.json["error"]], client["raw"][name]


def test_the_raw_values_reach_both_outcomes(parity):
    """Anti-vacuity: known Python behaviours on raw values, in the client's own answers."""
    _, client, _ = parity
    raw = client["raw"]
    accepted = {name for name, errors in raw.items() if not errors}
    assert 30 < len(accepted) < len(raw) - 30, (len(accepted), len(raw))
    # int("1_0") is 10, int(True) is 1 and int(5.9) is 5, while int("5.0") and int("1e3") raise.
    assert {"group-schedule-value-underscored_text", "group-schedule-value-true", "group-schedule-value-decimal",
            "group-schedule-unit-tab", "group-trigger-upper_interval", "group-sources-upper_scope_spaced_ids",
            "personal-sources-upper_scope", "personal-sources-group_source"} <= accepted
    assert raw["group-schedule-value-decimal_text"] == ["Schedule value must be a whole number."]
    assert raw["personal-schedule-value-exponent_text"] == ["Schedule value must be a whole number."]
    assert raw["group-trigger-dashed"] == ["Trigger type must be manual, interval or file_sync."]
    assert raw["group-trigger-zero"] == ["Trigger type is required."]
    assert raw["group-sources-unknown_after_valid"] == [SOURCE_UNAVAILABLE]
    assert raw["group-sources-whitespace_id"] == [F7]
    assert raw["group-sources-personal_scope"] == [F5]
    assert raw["personal-sources-missing_scope_is_skipped"] == [F6]


def test_every_reviewed_family_is_exercised():
    """Anti-vacuity: the cases reach each File Sync, trigger and schedule family in both scopes."""
    messages = {case["expected"] for case in CASES.values()}
    assert {F3, F4, F5, F6, F7, T3, T5, SOURCE_UNAVAILABLE} <= messages
    assert {"accept", "refuse"} <= messages
    assert {case["scope"] for case in CASES.values() if case["expected"] not in {"accept", "refuse"}} == {"personal", "group"}


def test_more_than_ten_sources_is_a_deliberate_difference(parity):
    """The server keeps only the first 10 sources without saying so; the editor refuses instead."""
    _, client, _ = parity
    assert "Choose at most 10 File Sync sources." in client["cases"]["eleven_sources"]["errors"]
    store = GroupWorkflowStore()
    for index in range(11):
        store.sources[(GROUP_ID, f"share-{index}")] = {
            "id": f"share-{index}", "scope_type": "group", "group_id": GROUP_ID,
            "name": f"Share {index}", "source_type": "smb",
        }
    saved = store.save(DIVERGENT_CASES["eleven_sources"]["draft"])
    assert [source["source_id"] for source in saved["file_sync"]["sources"]] == [f"share-{index}" for index in range(10)]


def test_a_deleted_personal_source_is_left_to_the_servers_reviewed_400(parity):
    """V2 lists no personal sources, so the editor allows the save and the server reports the source."""
    routes, client, _ = parity
    case, outcome = DIVERGENT_CASES["personal_stored_deleted_source"], client["cases"]["personal_stored_deleted_source"]
    assert outcome["errors"] == [] and outcome["settings"] == []

    response = _server(routes, case, outcome["payload"])

    assert response.status_code == 400
    assert response.json == {"error": SOURCE_UNAVAILABLE, "code": "file_sync_source_unavailable"}


def test_personal_validation_applies_only_the_personal_rules(parity):
    """Personal saves have no group File Sync gate, no same-group rule and their own wording."""
    _, client, _ = parity
    group_only = {F4, F5, F7}
    for name, case in CASES.items():
        if case["scope"] == "personal":
            assert not group_only & set(client["cases"][name]["errors"]), (name, client["cases"][name]["errors"])
    assert client["cases"]["personal_stored_without_sources"]["settings"] == [F6]


def test_no_create_payload_carries_a_revision_and_every_edit_carries_the_opened_one(parity):
    """The server refuses a save naming a deleted workflow only when it carries a revision; creates never do."""
    _, client, node_cases = parity
    for name, case in node_cases.items():
        payload = client["cases"][name]["payload"]
        if case["original"] is None:
            assert "definition_revision" not in payload and "id" not in payload, (name, payload.get("definition_revision"))
        else:
            assert payload["id"] == case["original"]["id"]
            assert payload["definition_revision"] == case["original"]["definition_revision"]


def test_the_alert_summary_resolves_stored_alerts_like_the_server(parity):
    _, client, _ = parity
    resolve = GroupWorkflowStore().modules["functions_workflow_alerts"].resolve_workflow_alert_config
    for name, record in ALERT_RECORDS.items():
        server = resolve(copy.deepcopy(record))
        summary = client["alerts"][name]
        assert summary == {
            "mode": server["alert_mode"], "priority": server["alert_priority"], "ruleCount": len(server["alert_rules"]),
        }, name
