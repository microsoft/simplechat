#!/usr/bin/env python3
# test_workflow_assist_candidate_parity.py
"""
Functional test for the agreement between the AI workflow assistant and the V2 workflow editor.
Version: 0.261.208
Implemented in: 0.261.208

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

JSON can't tell 12 from 12.0 inside node, but the save route can: it refuses a count that is not an
int. So the editor also prints what it opens and saves for every result, and for a corpus of numbers,
whitespace and JSON literals: ``Number()`` of each value, the draft it opens, the payload it saves,
and what ``JSON.parse`` reads or refuses. This test reads each line with Python's JSON parser and
compares it with the port's answer type-strictly, by ``json.dumps`` text. The port is also held,
without node, to JavaScript's answers for the numbers in ``KNOWN_NUMBERS``; the node run confirms
those answers against the real ``Number()``.

The TypeScript side is test_workflow_assist_candidate_parity_logic.ts, bundled with esbuild and run
under node as test_v2_workflow_change_tracking.py does. That check is skipped when
application/v2_ui/node_modules is missing; run npm ci there first.
"""

import copy
import json
import math
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


# ---------------------------------------------------------------------------
# The number, whitespace and JSON literal corpus
# ---------------------------------------------------------------------------

# Characters that JavaScript's trim(), Python's strip(), both or neither remove: U+FEFF is JavaScript
# whitespace only, U+001C and U+0085 are Python whitespace only, U+2028, U+000B and U+00A0 are both,
# and U+200B is neither.
MARKS = ("\ufeff", "\x1c", "\x85", "\u2028", "\x0b", "\xa0", "\u200b")
LARGEST_DOUBLE = int(sys.float_info.max)
# Half the gap between the largest double and 2**1024: an integer this far past the largest double
# rounds up to Infinity, and one less rounds down to the largest double.
HALF_TOP_GAP = 2 ** 970

# Number(value) in JavaScript, as describeNumber in the logic check prints it, for values the port
# must read the same way. The port is held to these without node; the node run confirms each one
# against the real Number().
KNOWN_NUMBERS = [
    ("\uff11\uff12", "NaN"),
    ("\uff13", "NaN"),
    ("\ufeff12", 12),
    ("\x1c12", "NaN"),
    ("\x8512", "NaN"),
    (1.2345678901234568e20, 123456789012345680000),
    (9007199254740993, 9007199254740992),
    (1e21, 1e21),
    (-0.0, "-0"),
    ([[1.5]], 1.5),
    ([True], "NaN"),
    ("0b12", "NaN"),
    ("-0x10", "NaN"),
    ("0o8", "NaN"),
    ([5], 5),
    ("0x" + "f" * 300, "Infinity"),
    (hex(LARGEST_DOUBLE + HALF_TOP_GAP), "Infinity"),
    (hex(LARGEST_DOUBLE + HALF_TOP_GAP - 1), sys.float_info.max),
    ("  -0  ", "-0"),
    ("", 0),
    ("Infinity", "Infinity"),
    ("infinity", "NaN"),
    ("1_000", "NaN"),
    ("\u0661\u0662", "NaN"),
    ("\u2028 12", 12),
    ("\u200b12", "NaN"),
    ("\u180e12", "NaN"),
    ([None], 0),
    ([1, 2], "NaN"),
]

CORPUS_NUMBERS = [value for value, _answer in KNOWN_NUMBERS] + [
    "0x20000000000001", "0x10", "0x", "0X1F", "0b101", "0o17",
    "12", "1e21", " ", "+Infinity", "-Infinity", "12px", ".5", "5.", "+5", "1e-7", ".", "1e", "00012", "12.0",
    "-12.5", "1e999", "-1e999",
    "\x0b12", "\xa012", "12\ufeff", "12\x85", "\t12\n", "\u3000 12", "\ufeff12\ufeff", "\x1c12\x1c", "\x8512\x85",
    None, True, False, [], {}, 0.1, 12, 12.0, -12.5, [[None]], [{}], [1e21], [-0.0], ["-0"], ["\x1c12"], [" 12 "],
]

# JSON texts as a request or a model reply may carry them. The browser's JSON.parse reads Infinity
# for 1e999 and for an integer past the largest double; the server refuses each of those.
CORPUS_LITERALS = [
    "1e999", "-1e999", "1.5E400", "NaN", "Infinity", "-Infinity", "-NaN", "[Infinity]", '{"a": 1e999}',
    "1e308", "-0.0", "-0", "9007199254740993", "12.0", "1E21", "1.0e+2", "0.1", "1e-7", '"12"',
    str(LARGEST_DOUBLE), str(LARGEST_DOUBLE + HALF_TOP_GAP - 1), str(LARGEST_DOUBLE + HALF_TOP_GAP),
    "1" + "0" * 400, "1" + "0" * 4400,
    "1.7976931348623158e308", "1.7976931348623159e308", "4.9e-324", "1e-400", "-1e-400",
    "[1e999]", '{"a": NaN}', '{"a": [1, -0.0, 2.5e-3]}', "123456789012345680000", "1.2345678901234568e20",
]


def _is_json_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _wrap(mark, text):
    return f"{mark}{text}{mark}"


def _monthly(day_of_month):
    return {
        "kind": "calendar", "frequency": "monthly", "days_of_week": [], "day_of_month": copy.deepcopy(day_of_month),
        "time_of_day": "08:00", "timezone": "UTC",
    }


def _marked_calendar(mark):
    return {
        "kind": _wrap(mark, "calendar"), "frequency": _wrap(mark, "weekly"), "days_of_week": [_wrap(mark, "monday")],
        "time_of_day": _wrap(mark, "08:00"), "timezone": _wrap(mark, "UTC"),
    }


def _stored_with_number(value):
    """A saved workflow that holds ``value`` in every number field the editor reads when it opens one."""
    stored = wa.stored_workflow(
        trigger_type="interval",
        schedule={"unit": "minutes", "value": copy.deepcopy(value)},
        error_handling={"strategy": "halt", "retry_count": copy.deepcopy(value)},
    )
    # Version 3 would open the workflow as a structured one, which these records are not.
    if not (_is_json_number(value) and value == 3):
        stored["definition_version"] = copy.deepcopy(value)
    wa.task_by_id(stored, wa.REVIEW_ID)["output_contract"] = {"kind": "records", "expected_count": copy.deepcopy(value)}
    return stored


def _stored_with_mark(mark):
    """A saved workflow with ``mark`` around every piece of text the editor trims or strips when it opens one."""
    stored = wa.stored_workflow(
        trigger_type="interval",
        schedule={"unit": _wrap(mark, "hours"), "value": 2},
        reference_inputs=[{**STYLE_REFERENCE, "name": _wrap(mark, "Style_guide")}],
    )
    review = wa.task_by_id(stored, wa.REVIEW_ID)
    review["output_contract"] = {"kind": "records", "identity_field": _wrap(mark, "id")}
    review["inputs"] = [{"name": _wrap(mark, "collected"), "task_id": wa.COLLECT_ID, "output": "text"}]
    return stored


def _draft_with_number(stored, value):
    """The editor's draft of ``stored`` with ``value`` in every number field a save reads."""
    draft = wa.editor_draft(stored)
    draft["trigger_type"] = "interval"
    draft["schedule"] = {"unit": "minutes", "value": copy.deepcopy(value)}
    draft["error_handling"] = {"strategy": "halt", "retry_count": copy.deepcopy(value)}
    wa.task_by_id(draft, wa.REVIEW_ID)["output_contract"] = {"kind": "records", "expected_count": copy.deepcopy(value)}
    return draft


def _draft_with_mark(draft, mark):
    """``draft`` with ``mark`` around every piece of text a save trims or strips."""
    draft["name"] = _wrap(mark, "Nightly review")
    draft["description"] = _wrap(mark, "Review new documents.")
    draft["tasks"][0]["instructions"] = _wrap(mark, "Collect the new documents.")
    wa.task_by_id(draft, wa.REVIEW_ID)["output_contract"] = {"kind": "records", "identity_field": _wrap(mark, "id")}
    draft["reference_inputs"] = [{**STYLE_REFERENCE, "name": _wrap(mark, "Style_guide")}]
    draft["trigger_type"] = "interval"
    draft["schedule"] = {"unit": _wrap(mark, "hours"), "value": 2}
    return draft


def _corpus_opens():
    opens = []
    for value in CORPUS_NUMBERS:
        opens.append(_stored_with_number(value))
        opens.append(wa.stored_workflow(trigger_type="interval", schedule=_monthly(value)))
    for mark in MARKS:
        opens.append(_stored_with_mark(mark))
        opens.append(wa.stored_workflow(trigger_type="interval", schedule=_marked_calendar(mark)))
        opens.append(wa.stored_workflow(trigger_type="interval", schedule={"unit": f"minutes{mark}", "value": 15}))
    return opens


def _corpus_saves():
    stored = wa.stored_workflow()
    saves = []
    for value in CORPUS_NUMBERS:
        saves.append({"stored": stored, "draft": _draft_with_number(stored, value)})
        monthly = wa.editor_draft(stored)
        monthly["trigger_type"] = "interval"
        monthly["schedule"] = _monthly(value)
        saves.append({"stored": stored, "draft": monthly})
    for mark in MARKS:
        saves.append({"stored": stored, "draft": _draft_with_mark(wa.editor_draft(stored), mark)})
        saves.append({"stored": None, "draft": _draft_with_mark(wa.new_draft(), mark)})
        calendar = wa.editor_draft(stored)
        calendar["trigger_type"] = "interval"
        calendar["schedule"] = _marked_calendar(mark)
        saves.append({"stored": stored, "draft": calendar})
    return saves


CORPUS = {
    "numbers": CORPUS_NUMBERS, "opens": _corpus_opens(), "saves": _corpus_saves(), "literals": CORPUS_LITERALS,
}


# ---------------------------------------------------------------------------
# The port's answers, in the shapes the logic check prints
# ---------------------------------------------------------------------------

def _canonical(value):
    """JSON text that tells 12 from 12.0, 0 from -0.0 and 1 from True, unlike ``==``."""
    return json.dumps(value, sort_keys=True)


def _described(number):
    """``describeNumber`` in the logic check: NaN, the infinities and negative zero by name."""
    if isinstance(number, float):
        if math.isnan(number):
            return "NaN"
        if math.isinf(number):
            return "Infinity" if number > 0 else "-Infinity"
        if number == 0 and math.copysign(1.0, number) < 0:
            return "-0"
    return editor.json_number(number)


def _port_open(stored):
    try:
        return editor.strip_undefined(editor.editor_original(stored))
    except editor.WorkflowEditorProjectionError as exc:
        return {"editor_refused": exc.message}


def _port_save(stored, draft):
    try:
        return editor.workflow_for_save(wa.json_copy(draft), editor.editor_original(stored))
    except editor.WorkflowEditorProjectionError as exc:
        return {"editor_refused_to_save": exc.message}


def _port_read(text):
    """What the server reads from a JSON text, after the rounding every number gets in the browser.

    The server keeps an integer past 2**53 exactly where JSON.parse rounds it to a double; no field
    the assistant writes takes such a number, and ``strip_undefined`` applies that rounding here.
    """
    try:
        value = core._strict_json(text)
    except (ValueError, RecursionError):
        return {"refused": True}
    return {"value": editor.strip_undefined(value)}


def _first_difference(editor_value, server_value, path="$"):
    """The first path where the editor's JSON value and the server's differ, type included, or None."""
    if _canonical(editor_value) == _canonical(server_value):
        return None
    if isinstance(editor_value, list) and isinstance(server_value, list) and len(editor_value) == len(server_value):
        for index, (left, right) in enumerate(zip(editor_value, server_value)):
            found = _first_difference(left, right, f"{path}[{index}]")
            if found:
                return found
    if isinstance(editor_value, dict) and isinstance(server_value, dict):
        for key in sorted(set(editor_value) | set(server_value)):
            if key not in editor_value or key not in server_value:
                return f"{path}.{key} is only in the {'server' if key in server_value else 'editor'}'s answer"
            found = _first_difference(editor_value[key], server_value[key], f"{path}.{key}")
            if found:
                return found
    return f"{path}: editor {ascii(_canonical(editor_value))[:300]}, server {ascii(_canonical(server_value))[:300]}"


def _differences(inputs, editor_answers, server_answers):
    assert len(editor_answers) == len(server_answers) == len(inputs)
    report = []
    for item, editor_answer, server_answer in zip(inputs, editor_answers, server_answers):
        found = _first_difference(editor_answer, server_answer)
        if found:
            report.append(f"{ascii(item)[:160]}\n    {found}")
    return report


def _emitted(run, label):
    """One line the logic check printed, read with Python's JSON parser."""
    # Split on newlines only: splitlines() also splits on U+001C, U+0085 and U+2028.
    lines = [line for line in run.stdout.split("\n") if line.startswith(f"{label} ")]
    assert len(lines) == 1, f"the editor printed {len(lines)} {label} lines\n{(run.stdout + run.stderr)[-3000:]}"
    return json.loads(lines[0][len(label) + 1:])


@pytest.fixture(scope="module")
def parity_cases():
    return [_run_case(scenario) for scenario in SCENARIOS]


@pytest.fixture(scope="module")
def editor_run(parity_cases):
    """The logic check's run under node over every assistant result and the corpus."""
    assert LOGIC_CHECK.exists(), "the TypeScript logic check is missing"
    if not (V2_DIR / "node_modules").exists():
        pytest.skip("run npm ci in application/v2_ui to replay the candidates through the editor")

    fixture_path = V2_DIR / "node_modules" / ".cache-workflow-assist-parity-fixture.json"
    bundle_path = V2_DIR / "node_modules" / ".cache-workflow-assist-parity-check.mjs"
    fixture = {"options": PARITY_OPTIONS, "cases": parity_cases, "corpus": CORPUS}
    fixture_path.write_text(json.dumps(fixture, allow_nan=False), encoding="utf-8")
    try:
        subprocess.run(
            [
                "npx", "esbuild", str(LOGIC_CHECK), "--bundle", "--platform=node", "--format=esm",
                "--packages=external", f"--outfile={bundle_path}", "--log-level=error",
            ],
            cwd=str(V2_DIR), check=True, shell=(sys.platform == "win32"), timeout=300,
        )
        return subprocess.run(
            ["node", str(bundle_path)],
            cwd=str(V2_DIR), capture_output=True, text=True, encoding="utf-8", shell=(sys.platform == "win32"),
            timeout=300, env={**os.environ, FIXTURE_ENV: str(fixture_path)},
        )
    finally:
        for path in (fixture_path, bundle_path):
            if path.exists():
                path.unlink()


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.208")


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


def test_the_port_reads_numbers_as_javascript_does():
    wrong = [
        f"Number({ascii(value)[:60]}) is {expected!r} in JavaScript, {_described(editor._js_number(value))!r} in the port"
        for value, expected in KNOWN_NUMBERS
        if _canonical(_described(editor._js_number(value))) != _canonical(expected)
    ]
    assert not wrong, "\n".join(wrong)


def test_a_whole_number_the_editor_saves_reaches_the_server_as_an_integer():
    stored = wa.stored_workflow()
    for value in ("12", 12.0, "\ufeff12", [12], ["12"]):
        payload = _port_save(stored, _draft_with_number(stored, value))
        contract = wa.task_by_id(payload, wa.REVIEW_ID)["output_contract"]
        assert type(contract["expected_count"]) is int and contract["expected_count"] == 12, ascii(value)
        assert type(payload["error_handling"]["retry_count"]) is int, ascii(value)


def test_the_corpus_covers_what_it_is_for():
    answers = [_port_read(text) for text in CORPUS_LITERALS]
    assert sum("refused" in answer for answer in answers) >= 10
    assert sum("value" in answer for answer in answers) >= 10
    saves = [_port_save(item["stored"], item["draft"]) for item in CORPUS["saves"]]
    assert all("editor_refused_to_save" not in payload for payload in saves)
    assert any("editor_readonly_reason" in payload for payload in saves)
    assert any("editor_readonly_reason" not in payload for payload in saves)
    opens = [_port_open(stored) for stored in CORPUS["opens"]]
    assert any("editor_readonly_reason" in draft for draft in opens)
    assert any("editor_readonly_reason" not in draft for draft in opens)


def test_the_editor_agrees_with_every_candidate(parity_cases, editor_run):
    output = editor_run.stdout + editor_run.stderr
    failures = [line for line in output.split("\n") if line.startswith("FAIL")]
    assert editor_run.returncode == 0 and not failures, "\n".join(failures or [output[-4000:]])
    expected = sum(
        (1 if case["stored"] is not None else 0) + 6 + 2 * len(case["refused"]) for case in parity_cases
    )
    passed = sum(1 for line in editor_run.stdout.split("\n") if line.startswith("  ok  "))
    assert passed == expected, f"expected {expected} editor checks, saw {passed}"


def test_the_editor_opens_and_saves_every_result_exactly_as_the_server_does(parity_cases, editor_run):
    results = _emitted(editor_run, "RESULTS")
    assert [item["name"] for item in results] == [case["name"] for case in parity_cases]
    wrong = []
    for case, item in zip(parity_cases, results):
        for field, server_value in (("original", case["original"]), ("payload", case["projection"])):
            found = _first_difference(item[field], server_value)
            if found:
                wrong.append(f"{case['name']}, {field}: {found}")
    assert not wrong, "\n".join(wrong)


def test_the_editor_confirms_the_known_javascript_answers(editor_run):
    answers = _emitted(editor_run, "NUMBERS")[:len(KNOWN_NUMBERS)]
    wrong = [
        f"Number({ascii(value)[:60]}) is {answer!r} in node, not {expected!r}"
        for (value, expected), answer in zip(KNOWN_NUMBERS, answers)
        if _canonical(answer) != _canonical(expected)
    ]
    assert len(answers) == len(KNOWN_NUMBERS) and not wrong, "\n".join(wrong)


def test_the_port_reads_every_corpus_number_as_the_editor_does(editor_run):
    editor_answers = _emitted(editor_run, "NUMBERS")
    server_answers = [_described(editor._js_number(value)) for value in CORPUS_NUMBERS]
    wrong = _differences(CORPUS_NUMBERS, editor_answers, server_answers)
    assert not wrong, "\n".join(wrong)


def test_the_port_opens_every_corpus_workflow_as_the_editor_does(editor_run):
    editor_answers = _emitted(editor_run, "OPENS")
    server_answers = [_port_open(stored) for stored in CORPUS["opens"]]
    wrong = _differences(CORPUS["opens"], editor_answers, server_answers)
    assert not wrong, "\n".join(wrong)


def test_the_port_saves_every_corpus_draft_as_the_editor_does(editor_run):
    editor_answers = _emitted(editor_run, "SAVES")
    server_answers = [_port_save(item["stored"], item["draft"]) for item in CORPUS["saves"]]
    wrong = _differences([item["draft"] for item in CORPUS["saves"]], editor_answers, server_answers)
    assert not wrong, "\n".join(wrong)


def test_the_server_refuses_exactly_the_json_the_browser_cannot_read_as_finite(editor_run):
    editor_answers = [
        {"refused": True} if "refused" in answer else answer for answer in _emitted(editor_run, "LITERALS")
    ]
    server_answers = [_port_read(text) for text in CORPUS_LITERALS]
    wrong = _differences(CORPUS_LITERALS, editor_answers, server_answers)
    assert not wrong, "\n".join(wrong)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
