# test_group_workflow_file_sync_client_parity.py
#!/usr/bin/env python3
"""
Functional test for the seam between the V2 group workflow editor and the group workflow server.
Version: 0.261.141
Implemented in: 0.261.141

This test ensures that the V2 editor's client-side File Sync, trigger, schedule and Analyze rules
agree with the real server, and that the editor's read-only alert summary resolves stored alerts
the same way the server does.

* The client half runs the production TypeScript (`lib/workflowEditor.ts`) under Node. It
  normalizes each draft, validates it with the real editor validators, and builds the exact save
  payload with `workflowForSave`.
* The server half sends that payload through the real `save_group_workflow`, using the harness
  from `test_group_workflow_round_trip_preservation.py`. The File Sync, document action, alert and
  definition normalizers there are real; only I/O is doubled.
* For every case, the editor allows the save exactly when the server would accept its payload.
  The one deliberate difference, more than 10 sources, is asserted as such: the server silently
  keeps the first 10, so the editor refuses instead of dropping a selection.
* `workflowAlertSummary` is compared with the real `resolve_workflow_alert_config`.
* `workflowAlertsEditableInClassic` is compared with the classic editor's own
  `workflowNeedsNativeEditor`, extracted from `workspace_workflows.js`.
"""

import copy
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

from test_group_workflow_round_trip_preservation import (  # noqa: E402  (shared real-store harness)
    GROUP_ID,
    OTHER_GROUP_ID,
    GroupWorkflowStore,
    monitored_workflow,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CLASSIC_WORKFLOWS_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "workspace_workflows.js"
FINANCE = {"scope_type": "group", "scope_id": GROUP_ID, "source_id": "finance-share"}
LISTED_SOURCES = [{
    "scope_type": "group", "scope_id": GROUP_ID, "source_id": "finance-share", "name": "Finance share",
    "source_type": "smb", "enabled": True, "label": "Finance share (Group)",
}]

NODE_SCRIPT = r"""
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.argv[1];
const input = JSON.parse(readFileSync(0, 'utf8'));
await import(pathToFileURL(path.join(root, 'functional_tests', 'test_support', 'tsResolve.mjs')));
const editor = await import(pathToFileURL(path.join(root, 'application', 'v2_ui', 'src', 'lib', 'workflowEditor.ts')));
const classicNeedsNative = new Function(`${input.classic_function}; return workflowNeedsNativeEditor;`)();
const group = { type: 'group', groupId: input.group_id };
const options = {
    definition_version: 2, supported_definition_versions: [1, 2, 3], can_manage: true, max_tasks: 50,
    agents: [], models: [], default_model: { label: 'Default model', valid: true },
    scope: { type: 'group', id: input.group_id },
};
const personalOptions = { ...options, scope: { type: 'personal', id: 'owner-1' } };
const output = { cases: {}, personal: {}, alerts: {}, classic: {} };
for (const [name, testCase] of Object.entries(input.cases)) {
    const draft = editor.normalizeWorkflowDefinition(testCase.payload, group);
    const errors = [
        ...editor.workflowValidationErrors(draft, options),
        ...editor.workflowFileSyncAvailabilityErrors(draft, input.sources),
    ];
    output.cases[name] = { errors, payload: errors.length ? null : editor.workflowForSave(draft, null, group) };
    output.personal[name] = editor.workflowValidationErrors(
        editor.normalizeWorkflowDefinition(testCase.payload), personalOptions,
    ).filter((error) => /File Sync|Schedule value|Monitor/.test(error));
}
for (const [name, record] of Object.entries(input.alerts)) {
    output.alerts[name] = editor.workflowAlertSummary(record);
}
for (const [name, record] of Object.entries(input.classic)) {
    output.classic[name] = {
        v2: editor.workflowAlertsEditableInClassic(editor.normalizeWorkflowDefinition(record, group)),
        classic: !classicNeedsNative(record),
    };
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


# name: (payload, expected: "both_accept" | "both_refuse")
CASES = {
    "monitor_valid": (_draft(), "both_accept"),
    "monitor_continue_always": (_draft(file_sync=_file_sync(continue_mode="always")), "both_refuse"),
    "monitor_queued": (_draft(file_sync=_file_sync(wait_mode="queued")), "both_refuse"),
    "monitor_without_file_sync_enabled": (_draft(file_sync=_file_sync(enabled=False)), "both_refuse"),
    "monitor_without_sources": (_draft(file_sync=_file_sync(sources=[])), "both_refuse"),
    "monitor_other_group_source": (_draft(file_sync=_file_sync(sources=[
        {"scope_type": "group", "scope_id": OTHER_GROUP_ID, "source_id": "other-share"},
    ])), "both_refuse"),
    "monitor_unavailable_source": (_draft(file_sync=_file_sync(sources=[
        {"scope_type": "group", "scope_id": GROUP_ID, "source_id": "deleted-share"},
    ])), "both_refuse"),
    "monitor_59_minutes": (_draft(schedule={"unit": "minutes", "value": 59}), "both_accept"),
    "monitor_90_minutes": (_draft(schedule={"unit": "minutes", "value": 90}), "both_refuse"),
    "monitor_24_hours": (_draft(schedule={"unit": "hours", "value": 24}), "both_accept"),
    "monitor_25_hours": (_draft(schedule={"unit": "hours", "value": 25}), "both_refuse"),
    "monitor_analyze_without_changed_files": (
        _draft(file_sync=_file_sync(use_changed_documents=False)), "both_refuse",
    ),
    "monitor_analyze_selected_without_changed_files": (
        _draft(file_sync=_file_sync(use_changed_documents=False), analyze_documents=["policy-doc"]), "both_accept",
    ),
    "interval_59_seconds": (_draft("interval", {"unit": "seconds", "value": 59}, _file_sync(enabled=False, sources=[])), "both_refuse"),
    "interval_59_seconds_with_documents": (
        _draft("interval", {"unit": "seconds", "value": 59}, _file_sync(enabled=False, sources=[]), ["policy-doc"]),
        "both_accept",
    ),
    "interval_60_seconds": (
        _draft("interval", {"unit": "seconds", "value": 60}, _file_sync(enabled=False, sources=[]), ["policy-doc"]),
        "both_refuse",
    ),
    "manual_before_run_queued_always": (
        _draft("manual", file_sync=_file_sync(wait_mode="queued", continue_mode="always")), "both_accept",
    ),
    "manual_before_run_queued_changed": (
        _draft("manual", file_sync=_file_sync(wait_mode="queued", continue_mode="changed")), "both_refuse",
    ),
    "manual_before_run_without_sources": (_draft("manual", file_sync=_file_sync(sources=[])), "both_refuse"),
    "manual_without_file_sync": (
        _draft("manual", file_sync=_file_sync(enabled=False, sources=[]), analyze_documents=["policy-doc"]), "both_accept",
    ),
    "manual_without_file_sync_analyze_empty": (
        _draft("manual", file_sync=_file_sync(enabled=False, sources=[])), "both_refuse",
    ),
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

CLASSIC_RECORDS = {
    "version_one": {"definition_version": 1, "name": "Classic"},
    "version_two": {"definition_version": 2, "name": "V2"},
    "version_three": {"definition_version": 3, "name": "Structured", "flow": {"id": "root", "nodes": []}},
    "version_one_with_flow": {"definition_version": 1, "name": "Odd", "flow": {"id": "root", "nodes": []}},
    # Records saved before definition_version existed: V2 normalizes them to version 2 on load.
    "unversioned": {"name": "Predates versions"},
}


def _classic_function():
    source = CLASSIC_WORKFLOWS_JS.read_text(encoding="utf-8")
    match = re.search(r"function workflowNeedsNativeEditor\(workflow\) \{.*?\n\}", source, re.DOTALL)
    assert match, "Classic workflowNeedsNativeEditor was not found."
    return match.group(0)


@pytest.fixture(scope="module")
def client():
    payload = {
        "group_id": GROUP_ID,
        "sources": LISTED_SOURCES,
        "cases": {name: {"payload": draft} for name, (draft, _) in CASES.items()},
        "alerts": ALERT_RECORDS,
        "classic": CLASSIC_RECORDS,
        "classic_function": _classic_function(),
    }
    payload["cases"]["eleven_sources"] = {"payload": _draft(file_sync=_file_sync(sources=[
        {"scope_type": "group", "scope_id": GROUP_ID, "source_id": f"share-{index}"} for index in range(11)
    ]))}
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", NODE_SCRIPT, str(REPO_ROOT)],
        input=json.dumps(payload), cwd=REPO_ROOT, text=True, capture_output=True, timeout=60, check=False,
    )
    assert result.returncode == 0, f"Production TypeScript check failed:\n{result.stdout}\n{result.stderr}"
    return json.loads(result.stdout)


def _server_accepts(payload, store=None):
    """Send exactly what the editor would post through the real save_group_workflow."""
    store = store or GroupWorkflowStore()
    try:
        store.save(payload)
    except (ValueError, LookupError, PermissionError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_editor_allows_a_save_exactly_when_the_server_accepts_it(client, name):
    draft, expected = CASES[name]
    outcome = client["cases"][name]
    if expected == "both_accept":
        assert outcome["errors"] == [], outcome["errors"]
        accepted, reason = _server_accepts(outcome["payload"])
        assert accepted, reason
    else:
        assert outcome["errors"], "The editor allowed a save the server refuses."
        # The editor's refusal is correct only if the server refuses the same draft too.
        accepted, _ = _server_accepts(copy.deepcopy(draft))
        assert not accepted, "The editor refused a draft the server accepts."


def test_more_than_ten_sources_is_the_one_deliberate_difference(client):
    """The server keeps only the first 10 sources without saying so; the editor refuses instead."""
    outcome = client["cases"]["eleven_sources"]
    assert "Choose at most 10 File Sync sources." in outcome["errors"]
    store = GroupWorkflowStore()
    for index in range(11):
        store.sources[(GROUP_ID, f"share-{index}")] = {
            "id": f"share-{index}", "scope_type": "group", "group_id": GROUP_ID,
            "name": f"Share {index}", "source_type": "smb",
        }
    payload = _draft(file_sync=_file_sync(sources=[
        {"scope_type": "group", "scope_id": GROUP_ID, "source_id": f"share-{index}"} for index in range(11)
    ]))
    saved = store.save(payload)
    assert [source["source_id"] for source in saved["file_sync"]["sources"]] == [f"share-{index}" for index in range(10)]


def test_personal_validation_never_applies_the_group_rules(client):
    """The group trigger, schedule and File Sync rules stay out of personal validation."""
    assert all(errors == [] for errors in client["personal"].values()), client["personal"]


def test_the_alert_summary_resolves_stored_alerts_like_the_server(client):
    resolve = GroupWorkflowStore().modules["functions_workflow_alerts"].resolve_workflow_alert_config
    for name, record in ALERT_RECORDS.items():
        server = resolve(copy.deepcopy(record))
        summary = client["alerts"][name]
        assert summary == {
            "mode": server["alert_mode"], "priority": server["alert_priority"], "ruleCount": len(server["alert_rules"]),
        }, name


def test_the_classic_link_follows_the_classic_editors_own_predicate(client):
    """Every versioned record agrees with classic; unversioned records get no link, which is conservative."""
    for name, outcome in client["classic"].items():
        if name != "unversioned":
            assert outcome["v2"] == outcome["classic"], name
    assert client["classic"]["version_one"] == {"v2": True, "classic": True}
    assert client["classic"]["version_two"] == {"v2": False, "classic": False}
    # Classic can still open a record that predates definition_version, but V2 normalizes it to
    # version 2 on load and cannot tell the two apart, so it conservatively withholds the link.
    assert client["classic"]["unversioned"] == {"v2": False, "classic": True}
