#!/usr/bin/env python3
# test_workflow_assist_candidate_parity.py
"""
Functional test for the agreement between the AI workflow assistant and the V2 workflow editor.
Version: 0.261.205
Implemented in: 0.261.205

The assistant returns an applied candidate that the V2 editor applies with ``applyAssist``
(Phase 3a), and it checks that candidate on the server with a Python port of the editor's logic
(functions_workflow_assist_editor.py). This test ensures the two layers agree. It runs real
assistant requests, with a scripted model, for every kind of change the assistant makes, and
replays each result through the real TypeScript under node:

* the editor opens the saved workflow as the same draft the server's port computes;
* ``workflowAssistViolation`` accepts every candidate, and ``applyAssist`` applies it unchanged;
* ``diffWorkflowChanges`` lists the change keys, kinds, labels and Jump to targets the server reports;
* the editor asks to re-approve Run as exactly when the server warns that saving requires it;
* ``workflowForSave`` builds the same save payload as the server's port, which is what the dry run
  validated;
* the editor refuses the candidates the server refuses, with the same message.

The TypeScript side is test_workflow_assist_candidate_parity_logic.ts, bundled with esbuild and run
under node as test_v2_workflow_change_tracking.py does. That check is skipped when
application/v2_ui/node_modules is missing; run npm ci there first.
"""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "application" / "single_app"))
sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

import functions_workflow_assist as core  # noqa: E402
import functions_workflow_assist_editor as editor  # noqa: E402
from test_support import workflow_assist as wa  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

V2_DIR = REPO_ROOT / "application" / "v2_ui"
LOGIC_CHECK = Path(__file__).with_name("test_workflow_assist_candidate_parity_logic.ts")
FIXTURE_ENV = "WORKFLOW_ASSIST_PARITY_FIXTURE"
FLOW_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "workflow_flow_authoring.json"

# The flow fixture's editor capabilities, with the default user's agents and models.
PARITY_OPTIONS = {**json.loads(FLOW_FIXTURE.read_text(encoding="utf-8"))["options"], **copy.deepcopy(wa.OPTIONS)}

SUMMARIZE_ID = "task-summarize-0003"
STYLE_REFERENCE = {
    "id": "reference-style-0009", "name": "Style_guide", "document_id": "doc-style-0009",
    "scope_type": "personal", "scope_id": wa.USER_ID,
}
MAILER = {
    "id": wa.AGENT["id"], "name": wa.AGENT["name"], "display_name": wa.AGENT["display_name"],
    "is_global": False, "is_group": False,
}
BREACH_RULE = {
    "id": "rule-breach-0001", "name": "Mentions a breach", "enabled": True, "severity": "high", "delivery": "default",
    "scope": {"type": "task", "task_id": wa.REVIEW_ID},
    "condition": {"type": "text_match", "mode": "contains_any", "values": ["breach"], "case_sensitive": False},
    "order": 1,
}
FAILED_RULE = {
    "id": "rule-failed-0002", "name": "Run failed", "enabled": True, "severity": "high", "delivery": "popup",
    "scope": {"type": "final", "task_id": ""}, "condition": {"type": "run_status", "statuses": ["failed"]}, "order": 2,
}
FILE_SYNC = {
    "enabled": True, "sources": [{"scope_type": "personal", "scope_id": wa.USER_ID, "source_id": "source-0001"}],
    "wait_mode": "complete", "continue_mode": "always", "use_changed_documents": True,
}

WEEKDAYS_AT_SEVEN = {"op": "set_schedule_calendar", "frequency": "weekdays", "time_of_day": "07:00"}
URGENT_ONLY = [
    {"op": "set_alert_mode", "mode": "rules"},
    {"op": "add_alert_rule", "name": "Urgent findings", "severity": "high",
     "condition": {"type": "model_evaluation", "prompt": "The results include something urgent."}},
]


def _review_workflow(**fields):
    """Collect reads no reference, Review and Summarize read every reference, and one reference exists."""
    return wa.stored_workflow(
        tasks=[
            wa.task(wa.COLLECT_ID, "Collect", "Collect the new documents.", 1, reference_ids=[]),
            wa.task(wa.REVIEW_ID, "Review", "Review each new document and list any problems.", 2),
            wa.task(SUMMARIZE_ID, "Summarize", "Summarize the problems for the team.", 3),
        ],
        reference_inputs=[STYLE_REFERENCE],
        **fields,
    )


def _with_run_as(**fields):
    return wa.stored_workflow(m365_run_as_user_id=wa.RUN_AS_ID, **fields)


def _file_sync_draft():
    draft = wa.editor_draft(wa.stored_workflow(file_sync=FILE_SYNC))
    draft["file_sync"] = {**FILE_SYNC, "continue_mode": "changed"}
    return draft


def _scenario(name, operations, *, stored, draft=None, references=()):
    return {"name": name, "operations": operations, "stored": stored, "draft": draft, "references": list(references)}


SCENARIOS = [
    _scenario("weekdays at seven with urgent alerts and Run as", [WEEKDAYS_AT_SEVEN, *URGENT_ONLY], stored=_with_run_as()),
    _scenario("weekly calendar in another time zone", [{
        "op": "set_schedule_calendar", "frequency": "weekly", "days_of_week": ["friday", "monday"],
        "time_of_day": "09:30", "timezone": "Europe/London",
    }], stored=wa.stored_workflow(trigger_type="interval", schedule={"unit": "hours", "value": 1})),
    _scenario("monthly calendar", [
        {"op": "set_schedule_calendar", "frequency": "monthly", "day_of_month": 15, "time_of_day": "18:00"},
    ], stored=wa.stored_workflow()),
    _scenario("interval after a calendar schedule", [{"op": "set_schedule_interval", "unit": "hours", "value": 2}],
              stored=wa.stored_workflow(trigger_type="interval", schedule={
                  "kind": "calendar", "frequency": "daily", "days_of_week": [], "day_of_month": None,
                  "time_of_day": "08:00", "timezone": "UTC",
              })),
    _scenario("manual trigger and a new description with Run as", [
        {"op": "set_trigger_manual"},
        {"op": "set_description", "description": "Review new documents every morning.\nFlag anything urgent."},
    ], stored=_with_run_as(trigger_type="interval", schedule={"unit": "minutes", "value": 30})),
    _scenario("shared reference for the review task", [
        {"op": "bind_reference", "document": "ref_1", "tasks": ["task_2"]},
    ], stored=_review_workflow(), references=[wa.CHECKLIST]),
    _scenario("shared reference for every task with Run as", [
        {"op": "bind_reference", "document": "ref_1", "tasks": "all"},
    ], stored=_with_run_as(), references=[wa.CHECKLIST]),
    _scenario("one task's document target", [
        {"op": "set_task_document_target", "task": "task_2", "action": "analyze", "documents": ["ref_1"]},
    ], stored=wa.stored_workflow(), references=[wa.INCIDENT]),
    _scenario("comparison target", [
        {"op": "set_task_document_target", "task": "task_2", "action": "comparison", "left": "ref_1", "right": ["ref_2"]},
    ], stored=wa.stored_workflow(), references=[wa.CHECKLIST, wa.INCIDENT]),
    _scenario("relevance search target", [
        {"op": "set_task_document_target", "task": "task_1", "action": "search", "search_mode": "relevance"},
    ], stored=wa.stored_workflow()),
    _scenario("reference selection", [
        {"op": "set_task_references", "task": "task_3", "mode": "selected", "references": ["Style_guide"]},
        {"op": "set_task_references", "task": "task_2", "mode": "none"},
    ], stored=_review_workflow()),
    _scenario("reference removal", [
        {"op": "set_task_references", "task": "task_1", "mode": "all"},
        {"op": "unbind_reference", "reference": "Style_guide"},
    ], stored=_review_workflow()),
    _scenario("added, moved and rewritten tasks with Run as", [
        {"op": "add_task", "key": "new_1", "name": "Summarize", "instructions": "Summarize the problems.", "after": "task_1"},
        {"op": "set_task_name", "task": "task_2", "name": "Check"},
        {"op": "set_task_instructions", "task": "task_2", "instructions": "Check each document.\nList every problem."},
        {"op": "move_task", "task": "task_2", "after": "start"},
        {"op": "set_task_inputs", "task": "new_1", "mode": "tasks", "from": ["task_1"]},
    ], stored=_with_run_as()),
    _scenario("removed task", [{"op": "remove_task", "task": "task_3"}], stored=_review_workflow()),
    _scenario("workflow and task runners", [
        {"op": "set_workflow_runner", "runner": "agent", "agent": "agent_1"},
        {"op": "set_task_runner", "task": "task_1", "runner": "model", "model": "model_1"},
        {"op": "set_task_runner", "task": "task_2", "runner": "agent", "agent": "agent_2"},
    ], stored=wa.stored_workflow()),
    _scenario("default model runner", [{"op": "set_workflow_runner", "runner": "model", "model": "default_model"}],
              stored=wa.stored_workflow(runner_type="agent", selected_agent=MAILER)),
    _scenario("legacy alert priority with Run as", [{"op": "set_alert_mode", "mode": "every_run", "priority": "high"}],
              stored=_with_run_as(alert_priority="medium")),
    _scenario("alert rules edited", [
        {"op": "remove_alert_rule", "rule": "alert_2"},
        {"op": "add_alert_rule", "name": "Mentions a leak", "severity": "critical", "delivery": "popup",
         "scope": {"type": "task", "task": "task_2"},
         "condition": {"type": "text_match", "mode": "contains_all", "values": ["leak", "customer"],
                       "case_sensitive": True}},
    ], stored=wa.stored_workflow(alert_mode="rules", alert_priority="none", alert_rules=[BREACH_RULE, FAILED_RULE],
                                 alert_evaluation={"on_error": "skip"})),
    _scenario("alerts turned off", [{"op": "set_alert_mode", "mode": "off"}],
              stored=wa.stored_workflow(alert_mode="rules", alert_rules=[BREACH_RULE])),
    _scenario("flow task renamed and rewritten", [
        {"op": "set_task_name", "task": "task_7", "name": "Closing note"},
        {"op": "set_task_instructions", "task": "task_1", "instructions": "Write the final report."},
    ], stored=wa.flow_stored()),
    _scenario("flow task target and runner", [
        {"op": "set_task_document_target", "task": "task_1", "action": "analyze", "documents": ["ref_1"]},
        {"op": "set_task_runner", "task": "task_5", "runner": "model", "model": "model_1"},
    ], stored=wa.flow_stored(), references=[wa.INCIDENT]),
    _scenario("new draft", [
        {"op": "set_name", "name": "Morning digest"},
        {"op": "set_schedule_interval", "unit": "hours", "value": 2},
        {"op": "set_description", "description": "A digest of new documents."},
    ], stored=None),
    _scenario("new draft with a shared reference", [
        {"op": "bind_reference", "document": "ref_1", "tasks": "all"},
    ], stored=None, references=[wa.CHECKLIST]),
    _scenario("personal draft with edited File Sync and Run as", [{"op": "set_name", "name": "Nightly review"}],
              stored=_with_run_as(file_sync=FILE_SYNC), draft=_file_sync_draft()),
]


def _refused_candidates(draft, candidate):
    """Bad candidates the server refuses, with the server's message; ``exact`` when the editor's must match."""
    first_task = candidate["tasks"][0]["id"]
    bad = [
        ("enablement", {**candidate, "is_enabled": not candidate.get("is_enabled", True)}, True),
        ("Run as", {**candidate, "m365_run_as_user_id": "runas-9999-other"}, True),
        ("sharing", {**candidate, "url_access_enabled": True}, True),
        ("an unauthored field", {**candidate, "shared_with": ["user-0002-ghijkl"]}, True),
        ("a task approval", {**candidate, "tasks": [
            {**task, "approval": {"required": True}} if task["id"] == first_task else task for task in candidate["tasks"]
        ]}, True),
    ]
    if isinstance(candidate.get("flow"), dict):
        flow = copy.deepcopy(candidate["flow"])
        flow["id"] = "replacement-root"
        # The server refuses any flow change; the editor refuses one that changes an ID's meaning.
        bad.append(("the flow's identity", {**candidate, "flow": flow}, False))
    refused = []
    for label, bad_candidate, exact in bad:
        message = editor.workflow_assist_violation(draft, bad_candidate)
        assert message, f"the server accepted a candidate that changes {label}"
        refused.append({"label": label, "candidate": bad_candidate, "message": message, "exact": exact})
    return refused


def _run_case(scenario):
    stored = scenario["stored"]
    draft = scenario["draft"]
    if draft is None:
        draft = wa.editor_draft(stored) if stored is not None else wa.new_draft()
    body = wa.request_body(draft, stored=stored, instruction="Change the workflow.", references=scenario["references"])
    model = wa.ScriptedModel(wa.reply("changed", "Done.", scenario["operations"]))
    bundle = wa.services(model, stored=stored, options=PARITY_OPTIONS)
    result = wa.run(body, bundle)
    assert result["outcome"] == "changed", (scenario["name"], result["reply"])
    candidate = result["candidate"]
    original = editor.editor_original(stored)
    projection = editor.workflow_for_save(wa.json_copy(candidate), original)
    checked = [payload for _user_id, payload in bundle.recorder.named("dry_run")]
    return {
        "name": scenario["name"],
        "stored": stored,
        "original": editor.strip_undefined(original) if original is not None else None,
        "draft": body["draft"],
        "candidate": candidate,
        "changes": result["changes"],
        "warnings": [warning["code"] for warning in result["warnings"]],
        "projection": projection,
        "checked": checked[-1] if checked else None,
        "run_as_warning": any(warning["code"] == "run_as_reapproval" for warning in result["warnings"]),
        "refused": _refused_candidates(body["draft"], candidate),
    }


@pytest.fixture(scope="module")
def parity_cases():
    return [_run_case(scenario) for scenario in SCENARIOS]


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.205")


def test_every_scenario_is_a_checked_change(parity_cases):
    names = [case["name"] for case in parity_cases]
    assert len(set(names)) == len(names) == len(SCENARIOS)
    for case in parity_cases:
        assert case["changes"], case["name"]
        assert editor.workflow_assist_violation(case["draft"], case["candidate"]) == "", case["name"]
        assert "draft_has_errors" not in case["warnings"], case["name"]
        # The dry run validated exactly the projection the editor will be checked against.
        assert case["checked"] == core.validation_copy(case["projection"]), case["name"]


def test_the_scenarios_cover_the_run_as_warning_both_ways(parity_cases):
    warned = {case["name"] for case in parity_cases if case["run_as_warning"]}
    with_run_as = {case["name"] for case in parity_cases if (case["stored"] or {}).get("m365_run_as_user_id")}
    assert warned and warned <= with_run_as
    assert with_run_as - warned, "no scenario shows a Run as workflow change that needs no re-approval"


def test_the_editor_agrees_with_every_candidate(parity_cases, tmp_path):
    assert LOGIC_CHECK.exists(), "the TypeScript logic check is missing"
    if not (V2_DIR / "node_modules").exists():
        pytest.skip("run npm ci in application/v2_ui to replay the candidates through the editor")

    fixture_path = V2_DIR / "node_modules" / ".cache-workflow-assist-parity-fixture.json"
    bundle_path = V2_DIR / "node_modules" / ".cache-workflow-assist-parity-check.mjs"
    fixture_path.write_text(json.dumps({"options": PARITY_OPTIONS, "cases": parity_cases}), encoding="utf-8")
    try:
        subprocess.run(
            [
                "npx", "esbuild", str(LOGIC_CHECK), "--bundle", "--platform=node", "--format=esm",
                "--packages=external", f"--outfile={bundle_path}", "--log-level=error",
            ],
            cwd=str(V2_DIR), check=True, shell=(sys.platform == "win32"), timeout=300,
        )
        result = subprocess.run(
            ["node", str(bundle_path)],
            cwd=str(V2_DIR), capture_output=True, text=True, encoding="utf-8", shell=(sys.platform == "win32"),
            timeout=300, env={**os.environ, FIXTURE_ENV: str(fixture_path)},
        )
    finally:
        for path in (fixture_path, bundle_path):
            if path.exists():
                path.unlink()

    output = result.stdout + result.stderr
    failures = [line for line in output.splitlines() if line.startswith("FAIL")]
    assert result.returncode == 0 and not failures, "\n".join(failures or [output[-4000:]])
    expected = sum(
        (1 if case["stored"] is not None else 0) + 6 + 2 * len(case["refused"]) for case in parity_cases
    )
    passed = result.stdout.count("  ok  ")
    assert passed == expected, f"expected {expected} editor checks, saw {passed}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
