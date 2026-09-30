#!/usr/bin/env python3
# test_workflow_assist_scenarios.py
"""
Functional test for the AI workflow assistant's end-to-end scenarios.
Version: 0.261.208
Implemented in: 0.261.208

This test ensures that the assistant turns an instruction into the candidate the roadmap's "Done
when" describes, with a scripted model:

* "run this at 7 AM on weekdays and only alert me when something is urgent" is a weekday 07:00
  calendar schedule in the request's time zone plus a rules-mode alert, with a Run as re-approval
  warning only when the workflow has Run as and a fingerprinted field changed;
* "compare every new document against #checklist" adds a shared reference the review task uses,
  "summarize #Q3-budget every Friday" gives a reference to one task while the others use none,
  "investigate #incident-report" makes the document one task's target, and an ambiguous placement
  is a question that changes nothing.

It also ensures that the candidate is the draft plus only the applied change while the save check
sees the normalized projection, that one correction round repairs a reply the save check refuses,
that a problem the draft already had is tolerated and flagged, that a save that lands during the
model call is a 409, that the email and Microsoft 365 warnings are advisory, that the deadline
bounds every model call, and that telemetry never carries content.

The model is always scripted; nothing here reaches Azure or a model.
"""

import copy
import json
import logging
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
sys.path.insert(0, str(ROOT / "functional_tests"))

import functions_workflow_assist as core  # noqa: E402
from test_support import workflow_assist as wa  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


SENTINEL = "SENTINEL-CONTENT-7d2e"
SUMMARIZE_ID = "task-summarize-0003"
STYLE_REFERENCE = {
    "id": "reference-style-0009", "name": "Style_guide", "document_id": "doc-style-0009",
    "scope_type": "personal", "scope_id": wa.USER_ID,
}
CHECKLIST_REFERENCE_ID = f"personal:{wa.USER_ID}:{wa.CHECKLIST['id']}"
MAILER = {
    "id": wa.AGENT["id"], "name": wa.AGENT["name"], "display_name": wa.AGENT["display_name"],
    "is_global": False, "is_group": False,
}

WEEKDAYS_AT_SEVEN = {"op": "set_schedule_calendar", "frequency": "weekdays", "time_of_day": "07:00"}
URGENT_PROMPT = "The results include something urgent that needs attention today."
URGENT_ONLY = [
    {"op": "set_alert_mode", "mode": "rules"},
    {"op": "add_alert_rule", "name": "Urgent findings", "severity": "high",
     "condition": {"type": "model_evaluation", "prompt": URGENT_PROMPT}},
]
URGENT_RULE = {
    "name": "Urgent findings", "enabled": True, "severity": "high", "delivery": "default",
    "scope": {"type": "final", "task_id": ""}, "condition": {"type": "model_evaluation", "prompt": URGENT_PROMPT},
}
EMAIL_TASK = {
    "op": "add_task", "key": "new_1", "name": "Email the summary",
    "instructions": "Email me the list of problems every morning.", "after": "task_2",
}
RENAME = {"op": "set_name", "name": "Nightly review"}

RUN_AS_MESSAGE = "Saving this change requires re-approving Run as, because it changes how the workflow runs."
EMAIL_MESSAGE = (
    "This task sends email, which needs an agent with the Microsoft 365 action. Choose such an agent for the task "
    "or the workflow."
)
DRAFT_ERRORS_MESSAGE = (
    "The draft already had a problem that saving will report. The assistant did not cause it; fix it before saving."
)
METRIC_KEYS = {
    "user_id", "submission_id", "status", "outcome", "code", "stage", "error_type", "invalid_stage",
    "operation_count", "correction_count", "model_calls", "turns_received", "turns_sent", "turns_dropped",
    "reference_count", "excerpt_count", "definition_version", "is_new", "warning_codes", "fault_location",
    "duration_ms",
}


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.208")


def _answer(stored, operations, *, instruction, reply_text="Done.", references=(), email_tasks=None, **service_fields):
    """Run one request whose model replies ``changed`` with ``operations``; returns the result and its parts."""
    model = wa.ScriptedModel(wa.reply("changed", reply_text, operations, email_tasks))
    bundle = wa.services(model, stored=stored, **service_fields)
    body = wa.request_body(stored=stored, instruction=instruction, references=list(references))
    result = wa.run(body, bundle)
    assert result["outcome"] == "changed", result["reply"]
    return result, body["draft"], model, bundle


def _keys(result):
    return [change["key"] for change in result["changes"]]


def _codes(result):
    return [warning["code"] for warning in result["warnings"]]


def _checked_payloads(bundle):
    return [payload for _user_id, payload in bundle.recorder.named("dry_run")]


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


# ---------------------------------------------------------------------------------------------
# Schedules and alerts
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("run_as", ["", wa.RUN_AS_ID], ids=["without Run as", "with Run as"])
def test_weekdays_at_seven_alerting_only_when_urgent(run_as):
    stored = wa.stored_workflow(m365_run_as_user_id=run_as)
    result, draft, model, bundle = _answer(
        stored, [WEEKDAYS_AT_SEVEN, *URGENT_ONLY],
        instruction="Run this at 7 AM on weekdays and only alert me when something is urgent.",
        reply_text="It now runs at 7:00 on weekdays and alerts you only when something is urgent.",
    )

    assert result["reply"] == "It now runs at 7:00 on weekdays and alerts you only when something is urgent."
    candidate = result["candidate"]
    rule_id = candidate["alert_rules"][0]["id"]
    assert str(uuid.UUID(rule_id)) == rule_id
    assert candidate == {
        **draft,
        "trigger_type": "interval",
        "schedule": {
            "kind": "calendar", "frequency": "weekdays", "days_of_week": [], "day_of_month": None,
            "time_of_day": "07:00", "timezone": wa.TIME_ZONE,
        },
        "alert_mode": "rules",
        "alert_priority": "none",
        "alert_rules": [{"id": rule_id, **URGENT_RULE}],
        "alert_evaluation": {"on_error": "skip"},
    }
    assert result["changes"] == [
        {"key": "schedule", "kind": "field", "label": "Trigger and schedule", "owner_label": "Workflow",
         "target": {"focus_key": "schedule"}, "summary": "Workflow: Trigger and schedule"},
        {"key": "alerts", "kind": "field", "label": "Alerts", "owner_label": "Workflow",
         "target": {"focus_key": "alerts"}, "summary": "Workflow: Alerts"},
    ]
    expected_warnings = [{"code": "run_as_reapproval", "message": RUN_AS_MESSAGE}] if run_as else []
    assert result["warnings"] == expected_warnings

    # The model knew Run as was set and which time zone the editor is in, but never saw the Run as ID.
    envelope = model.envelope()
    assert envelope["time_zone"] == wa.TIME_ZONE
    assert envelope["draft"]["run_as_configured"] is bool(run_as)
    assert wa.RUN_AS_ID not in model.text()
    [payload] = _checked_payloads(bundle)
    assert (payload["trigger_type"], payload["schedule"]) == ("interval", candidate["schedule"])
    record = wa.finished_log(bundle)
    assert (record["status"], record["outcome"], record["operation_count"]) == (200, "changed", 3)
    assert record["warning_codes"] == _codes(result)


def test_an_alert_change_alone_does_not_ask_to_re_approve_run_as():
    stored = wa.stored_workflow(m365_run_as_user_id=wa.RUN_AS_ID)
    result, draft, _model, _bundle = _answer(
        stored, [{"op": "set_alert_mode", "mode": "every_run", "priority": "high"}],
        instruction="Alert me after every run.",
    )
    assert result["candidate"] == {
        **draft, "alert_mode": "every_run", "alert_priority": "high", "alert_rules": [],
        "alert_evaluation": {"on_error": "skip"},
    }
    assert _keys(result) == ["alerts"]
    assert result["warnings"] == []


@pytest.mark.parametrize("operation, schedule", [
    (
        {"frequency": "daily", "time_of_day": "06:15"},
        {"frequency": "daily", "days_of_week": [], "day_of_month": None, "time_of_day": "06:15", "timezone": wa.TIME_ZONE},
    ),
    (
        {"frequency": "weekly", "days_of_week": ["friday", "monday"], "time_of_day": "17:30", "timezone": "Europe/Paris"},
        {"frequency": "weekly", "days_of_week": ["monday", "friday"], "day_of_month": None, "time_of_day": "17:30",
         "timezone": "Europe/Paris"},
    ),
    (
        {"frequency": "monthly", "day_of_month": 1, "time_of_day": "09:00"},
        {"frequency": "monthly", "days_of_week": [], "day_of_month": 1, "time_of_day": "09:00", "timezone": wa.TIME_ZONE},
    ),
], ids=["every day", "named days in a named time zone", "the first of the month"])
def test_calendar_schedules_take_the_editors_shape(operation, schedule):
    result, _draft, _model, _bundle = _answer(
        wa.stored_workflow(), [{"op": "set_schedule_calendar", **operation}], instruction="Change when it runs.",
    )
    assert result["candidate"]["schedule"] == {"kind": "calendar", **schedule}
    assert result["candidate"]["trigger_type"] == "interval"


def test_a_new_calendar_time_keeps_the_schedules_time_zone():
    stored = wa.stored_workflow(trigger_type="interval", schedule={
        "kind": "calendar", "frequency": "daily", "time_of_day": "08:30", "timezone": "Europe/London",
    })
    result, _draft, _model, _bundle = _answer(stored, [WEEKDAYS_AT_SEVEN], instruction="Run it at 7 on weekdays.")
    assert result["candidate"]["schedule"] == {
        "kind": "calendar", "frequency": "weekdays", "days_of_week": [], "day_of_month": None,
        "time_of_day": "07:00", "timezone": "Europe/London",
    }


def test_an_interval_edits_the_schedule_and_manual_keeps_it():
    stored = wa.stored_workflow(trigger_type="interval", schedule={"unit": "minutes", "value": 30})
    result, draft, _model, _bundle = _answer(
        stored, [{"op": "set_schedule_interval", "unit": "hours", "value": 2}], instruction="Run it every two hours.",
    )
    assert result["candidate"] == {**draft, "schedule": {"unit": "hours", "value": 2}}

    result, draft, _model, _bundle = _answer(stored, [{"op": "set_trigger_manual"}], instruction="Stop the schedule.")
    # The trigger select changes only the trigger, as the editor does.
    assert result["candidate"] == {**draft, "trigger_type": "manual"}
    assert _keys(result) == ["schedule"]


@pytest.mark.parametrize("bad, message", [
    (
        {**WEEKDAYS_AT_SEVEN, "timezone": "Factory"},
        "Operation 1 (set_schedule_calendar): The time zone must be an IANA time zone name, such as America/New_York.",
    ),
    ({"op": "set_schedule_interval", "unit": "minutes", "value": 1}, None),
], ids=["a time zone the schedule list excludes", "an interval under the minimum"])
def test_a_schedule_the_editor_would_refuse_goes_back_for_one_correction(bad, message):
    model = wa.ScriptedModel(
        wa.reply("changed", "Done.", [bad]),
        wa.reply("changed", "Done.", [{**WEEKDAYS_AT_SEVEN, "timezone": "America/Chicago"}]),
    )
    bundle = wa.services(model)
    result = wa.run(wa.request_body(instruction="Run it at 7 AM Chicago time on weekdays."), bundle)
    assert result["candidate"]["schedule"]["timezone"] == "America/Chicago"
    [correction] = model.envelope(1)["previous_attempt_errors"]
    if message is not None:
        assert correction == message
    else:
        assert correction.startswith("Operation 1 (set_schedule_interval): ")
        assert "300" in correction or "5 minutes" in correction
    assert wa.finished_log(bundle)["invalid_stage"] == "apply"


# ---------------------------------------------------------------------------------------------
# Placing `#` documents (roadmap section 5, "How # documents are used")
# ---------------------------------------------------------------------------------------------

def test_compare_every_new_document_against_a_checklist_adds_a_reference_review_uses():
    stored = _review_workflow()
    result, draft, model, bundle = _answer(
        stored, [{"op": "bind_reference", "document": "ref_1", "tasks": ["task_2"]}],
        instruction="Compare every new document against #checklist.",
        reply_text="Review now compares each new document against Security checklist.pdf.",
        references=[wa.CHECKLIST],
    )

    # The model saw which task reads what, by handle, and the attached document by its file name.
    view = model.envelope()["draft"]
    assert [task["references"] for task in view["tasks"]] == ["none", "all", "all"]
    assert view["shared_references"] == [{"reference": "Style_guide", "name": "Style_guide"}]
    assert view["attached_documents"] == [{"document": "ref_1", "label": "Security checklist.pdf"}]

    expected = copy.deepcopy(draft)
    expected["reference_inputs"].append({
        "id": CHECKLIST_REFERENCE_ID, "name": "Security_checklist_pdf", "document_id": wa.CHECKLIST["id"],
        "scope_type": "personal", "scope_id": wa.USER_ID,
    })
    # Summarize read every reference; it keeps reading only the one it had.
    wa.task_by_id(expected, SUMMARIZE_ID)["reference_ids"] = [STYLE_REFERENCE["id"]]
    assert result["candidate"] == expected
    # Review still reads every reference, the checklist included, and Collect still reads none.
    assert "reference_ids" not in wa.task_by_id(result["candidate"], wa.REVIEW_ID)
    assert wa.task_by_id(result["candidate"], wa.COLLECT_ID)["reference_ids"] == []
    assert sorted(_keys(result)) == sorted([
        f"task:{SUMMARIZE_ID}:reference_ids", "reference:personal%3Auser-0001-abcdef%3Adoc-checklist-0001",
    ])
    added = next(change for change in result["changes"] if change["kind"] == "added")
    assert added["summary"] == "Added reference: Security_checklist_pdf"
    assert result["context_documents"] == []
    [payload] = _checked_payloads(bundle)
    assert payload["reference_inputs"] == expected["reference_inputs"]


def test_a_reference_for_every_task_reaches_tasks_that_chose_their_references():
    result, _draft, _model, _bundle = _answer(
        _review_workflow(), [{"op": "bind_reference", "document": "ref_1", "tasks": "all"}],
        instruction="Every task should follow #checklist.", references=[wa.CHECKLIST],
    )
    candidate = result["candidate"]
    assert wa.task_by_id(candidate, wa.COLLECT_ID)["reference_ids"] == [CHECKLIST_REFERENCE_ID]
    assert "reference_ids" not in wa.task_by_id(candidate, wa.REVIEW_ID)
    assert "reference_ids" not in wa.task_by_id(candidate, SUMMARIZE_ID)
    assert candidate["reference_inputs"][-1]["id"] == CHECKLIST_REFERENCE_ID


def test_summarize_a_budget_every_friday_gives_it_to_that_task_and_the_others_use_none():
    stored = wa.stored_workflow(tasks=[
        wa.task(wa.COLLECT_ID, "Collect", "Collect this week's spending.", 1),
        wa.task(SUMMARIZE_ID, "Summarize", "Summarize the spending for the team.", 2),
    ])
    result, draft, _model, _bundle = _answer(
        stored, [
            {"op": "bind_reference", "document": "ref_1", "tasks": ["task_2"]},
            {"op": "set_schedule_calendar", "frequency": "weekly", "days_of_week": ["friday"], "time_of_day": "09:00"},
        ],
        instruction="Summarize #Q3-budget every Friday.", references=[wa.BUDGET],
    )
    budget_id = f"personal:{wa.USER_ID}:{wa.BUDGET['id']}"
    expected = copy.deepcopy(draft)
    expected["reference_inputs"] = [{
        "id": budget_id, "name": "Q3_budget_xlsx", "document_id": wa.BUDGET["id"], "scope_type": "personal",
        "scope_id": wa.USER_ID,
    }]
    # Summarize reads every reference, which is now just the budget; Collect is pinned to none.
    wa.task_by_id(expected, wa.COLLECT_ID)["reference_ids"] = []
    expected.update(trigger_type="interval", schedule={
        "kind": "calendar", "frequency": "weekly", "days_of_week": ["friday"], "day_of_month": None,
        "time_of_day": "09:00", "timezone": wa.TIME_ZONE,
    })
    assert result["candidate"] == expected
    assert "reference_ids" not in wa.task_by_id(result["candidate"], SUMMARIZE_ID)
    assert result["context_documents"] == []


def test_investigate_a_report_makes_it_one_tasks_target_only():
    stored = wa.stored_workflow()
    result, draft, _model, _bundle = _answer(
        stored, [{"op": "set_task_document_target", "task": "task_2", "action": "analyze", "documents": ["ref_1"]}],
        instruction="Investigate #incident-report.", references=[wa.INCIDENT],
    )
    expected = copy.deepcopy(draft)
    wa.task_by_id(expected, wa.REVIEW_ID)["document_action"] = {
        "type": "analyze", "doc_scope": "personal", "active_group_ids": [], "active_public_workspace_id": [],
        "document_ids": [wa.INCIDENT["id"]], "target_mode": "selected", "analysis_mode": "combined",
    }
    assert result["candidate"] == expected
    assert result["candidate"]["reference_inputs"] == []
    assert result["changes"] == [{
        "key": f"task:{wa.REVIEW_ID}:document_action", "kind": "field", "label": "Document action",
        "owner_label": "Review", "target": {"focus_key": f"task:{wa.REVIEW_ID}:document_action"},
        "summary": "Review: Document action",
    }]
    assert result["context_documents"] == []


def test_an_ambiguous_placement_is_a_question_that_changes_nothing():
    stored = wa.stored_workflow()
    model = wa.ScriptedModel(wa.reply("question", "Should every task read the checklist, or only Review?"))
    limiter = wa.FakeLimiter()
    bundle = wa.services(model, stored=stored, limiter=limiter)
    result = wa.run(wa.request_body(stored=stored, instruction="Use #checklist.", references=[wa.CHECKLIST]), bundle)
    assert result == {
        "submission_id": "submission-0001", "outcome": "question",
        "reply": "Should every task read the checklist, or only Review?",
        "candidate": None, "changes": [], "warnings": [], "context_documents": ["Security checklist.pdf"],
    }
    assert bundle.recorder.named("dry_run") == []
    record = wa.finished_log(bundle)
    assert (record["outcome"], record["operation_count"], record["model_calls"]) == ("question", 0, 1)
    assert limiter.events == [("acquire", wa.USER_ID), ("release", "lease-1", False)]


def test_an_explanation_changes_nothing_and_reports_documents_read_as_context():
    model = wa.ScriptedModel(wa.reply("explained", "Security checklist.pdf asks for four controls, and Review checks them."))
    bundle = wa.services(model)
    result = wa.run(wa.request_body(instruction="Does this cover #checklist?", references=[wa.CHECKLIST]), bundle)
    assert (result["outcome"], result["candidate"], result["changes"], result["warnings"]) == ("explained", None, [], [])
    assert result["context_documents"] == ["Security checklist.pdf"]
    assert model.envelope()["document_excerpts"] == [{"document": "ref_1", "excerpt": wa.EXCERPT_TEXT, "truncated": False}]


# ---------------------------------------------------------------------------------------------
# Apply, then validate
# ---------------------------------------------------------------------------------------------

def test_the_candidate_is_the_draft_plus_the_change_while_the_check_sees_the_saved_shape():
    stored = wa.stored_workflow()
    draft = wa.editor_draft(stored)
    # What an editor draft can hold that saving normalizes: task numbers left from a reorder,
    # untrimmed text, a derived field that is stale and a task whose runner was never filled in.
    draft["tasks"][0]["order"] = 7
    draft["tasks"][1]["order"] = 9
    draft["description"] = "  Review new documents.  "
    draft["task_prompt"] = "An old first task."
    del draft["tasks"][1]["runner"]
    model = wa.ScriptedModel(wa.reply("changed", "Renamed.", [RENAME]))
    bundle = wa.services(model, stored=stored)

    result = wa.run(wa.request_body(draft, stored=stored), bundle)

    assert result["candidate"] == {**draft, "name": "Nightly review"}
    assert _keys(result) == ["name"]
    [payload] = _checked_payloads(bundle)
    assert [task["order"] for task in payload["tasks"]] == [1, 2]
    assert payload["tasks"][1]["runner"] == {"type": "inherit"}
    assert (payload["name"], payload["description"], payload["task_prompt"]) == (
        "Nightly review", "Review new documents.", "Collect the new documents.",
    )
    assert (payload["id"], payload["definition_revision"]) == (wa.WORKFLOW_ID, wa.REVISION)


def test_a_new_draft_is_checked_as_a_new_workflow():
    model = wa.ScriptedModel(wa.reply("changed", "Renamed.", [RENAME]))
    bundle = wa.services(model)
    result = wa.run(wa.request_body(), bundle)
    assert result["candidate"]["name"] == "Nightly review"
    [payload] = _checked_payloads(bundle)
    assert "id" not in payload and "definition_revision" not in payload
    assert bundle.recorder.named("read_base") == []
    assert wa.finished_log(bundle)["is_new"] is True


def test_the_check_uses_placeholders_only_for_text_the_draft_has_not_filled_in_yet():
    draft = wa.new_draft(name="")
    draft["tasks"][1]["instructions"] = "   "
    model = wa.ScriptedModel(wa.reply("changed", "Described.", [{"op": "set_description", "description": "Weekly."}]))
    bundle = wa.services(model)
    result = wa.run(wa.request_body(draft), bundle)
    # The candidate keeps the blanks the user has yet to fill in.
    assert result["candidate"] == {**draft, "description": "Weekly."}
    [payload] = _checked_payloads(bundle)
    assert payload["name"] == "Untitled workflow"
    assert payload["tasks"][1]["instructions"] == "Complete this task."


def test_a_change_the_save_check_refuses_goes_back_for_one_correction():
    def dry_run(_user_id, payload):
        if payload["name"] == "Nightly review!":
            return {"ok": False, "workflow": None, "errors": [{
                "code": "invalid_workflow", "path": "name", "message": "Workflow names can use letters, numbers and spaces.",
            }]}
        return {"ok": True, "workflow": payload, "errors": []}

    model = wa.ScriptedModel(
        wa.reply("changed", "Renamed.", [{"op": "set_name", "name": "Nightly review!"}]),
        wa.reply("changed", "Renamed.", [RENAME]),
    )
    bundle = wa.services(model, dry_run=dry_run)
    result = wa.run(wa.request_body(), bundle)

    assert result["candidate"]["name"] == "Nightly review"
    assert model.envelope(1)["previous_attempt_errors"] == [
        "Saving the changed workflow would fail. Workflow names can use letters, numbers and spaces.",
    ]
    # The refused change, the draft as sent (which showed the problem was new), then the correction.
    assert [payload["name"] for payload in _checked_payloads(bundle)] == [
        "Nightly review!", "Document review", "Nightly review",
    ]
    record = wa.finished_log(bundle)
    assert (record["correction_count"], record["invalid_stage"], record["model_calls"]) == (1, "validation", 2)


def test_a_problem_the_draft_already_had_is_tolerated_and_flagged():
    def dry_run(_user_id, _payload):
        return {"ok": False, "workflow": None, "errors": [{
            "code": "invalid_workflow", "path": "tasks", "message": "A task input comes from a later task.",
        }]}

    model = wa.ScriptedModel(wa.reply("changed", "Renamed.", [RENAME]))
    bundle = wa.services(model, dry_run=dry_run)
    result = wa.run(wa.request_body(), bundle)
    assert result["candidate"]["name"] == "Nightly review"
    assert result["warnings"] == [{"code": "draft_has_errors", "message": DRAFT_ERRORS_MESSAGE}]
    assert len(model.calls) == 1
    assert len(bundle.recorder.named("dry_run")) == 2


@pytest.mark.parametrize("code", ["workflow_definition_conflict", "workflow_deleted"])
def test_a_save_that_lands_during_the_model_call_is_a_conflict(code):
    stored = wa.stored_workflow()

    def dry_run(_user_id, _payload):
        return {"ok": False, "workflow": None, "errors": [
            {"code": code, "path": "", "message": "This workflow changed since it was opened. Reload it before saving."},
        ]}

    model = wa.ScriptedModel(wa.reply("changed", "Renamed.", [RENAME]))
    limiter = wa.FakeLimiter()
    bundle = wa.services(model, stored=stored, dry_run=dry_run, limiter=limiter)
    error = wa.refusal(wa.request_body(stored=stored), bundle)
    assert (error.status, error.code) == (409, code)
    # A conflict is not the model's to correct.
    assert len(model.calls) == 1
    assert limiter.events[-1] == ("release", "lease-1", False)


def test_a_change_to_what_the_draft_already_says_is_an_explanation():
    model = wa.ScriptedModel(wa.reply("changed", "Renamed.", [{"op": "set_name", "name": "Document review"}]))
    bundle = wa.services(model)
    result = wa.run(wa.request_body(instruction="Call it Document review."), bundle)
    assert (result["outcome"], result["reply"], result["candidate"], result["changes"]) == (
        "explained", "The workflow already works this way, so nothing was changed.", None, [],
    )
    assert bundle.recorder.named("dry_run") == []
    record = wa.finished_log(bundle)
    assert (record["outcome"], record["operation_count"]) == ("explained", 1)


# ---------------------------------------------------------------------------------------------
# Email and Microsoft 365 warnings
# ---------------------------------------------------------------------------------------------

def _email_task(result, name="Email the summary"):
    return next(task for task in result["candidate"]["tasks"] if task["name"] == name)


def test_an_email_task_on_the_model_runner_needs_an_agent_with_the_m365_action():
    result, _draft, _model, _bundle = _answer(wa.stored_workflow(), [EMAIL_TASK], instruction="Email me the problems.")
    task = _email_task(result)
    assert [item["id"] for item in result["candidate"]["tasks"]] == [wa.COLLECT_ID, wa.REVIEW_ID, task["id"]]
    assert result["warnings"] == [{
        "code": "email_requires_m365_agent", "message": EMAIL_MESSAGE, "target": {"focus_key": f"task:{task['id']}"},
    }]
    added = next(change for change in result["changes"] if change["kind"] == "added")
    assert added["target"] == {"focus_key": f"task:{task['id']}"}


def test_the_model_can_name_an_email_task_its_instructions_do_not_spell_out():
    result, _draft, _model, _bundle = _answer(
        wa.stored_workflow(),
        [{"op": "set_task_instructions", "task": "task_2", "instructions": "Send the problems to my manager."}],
        instruction="Have Review send the problems to my manager.", email_tasks=["task_2"],
    )
    assert result["warnings"] == [{
        "code": "email_requires_m365_agent", "message": EMAIL_MESSAGE, "target": {"focus_key": f"task:{wa.REVIEW_ID}"},
    }]


def test_an_email_task_in_a_flow_points_at_its_block():
    stored = wa.flow_stored()
    result, _draft, _model, _bundle = _answer(
        stored, [{"op": "set_task_instructions", "task": "task_1", "instructions": "Email me the report."}],
        instruction="Email me the report.",
    )
    target = {"focus_key": "task:report-task", "node_id": "report-node"}
    assert result["warnings"] == [{"code": "email_requires_m365_agent", "message": EMAIL_MESSAGE, "target": target}]
    assert result["changes"][0]["target"] == {"focus_key": "task:report-task:instructions", "node_id": "report-node"}


@pytest.mark.parametrize("capable, expected", [
    (True, []),
    (False, ["email_requires_m365_agent", "email_requires_m365_agent"]),
    (None, []),
], ids=["an agent that can send email", "an agent that cannot", "an agent the check cannot read"])
def test_an_email_task_on_an_agent_asks_once_whether_that_agent_can_send_email(capable, expected):
    lookups = []

    def agent_email_capable(user_id, agent):
        lookups.append((user_id, agent))
        return capable

    second = {**EMAIL_TASK, "key": "new_2", "name": "Email the owner", "instructions": "Send an email to the owner.",
              "after": "new_1"}
    stored = wa.stored_workflow(runner_type="agent", selected_agent=MAILER)
    result, _draft, _model, _bundle = _answer(
        stored, [EMAIL_TASK, second], instruction="Email me and the owner.",
        agent_email_capable=agent_email_capable, m365_connected=lambda _user_id: True,
    )
    assert _codes(result) == expected
    assert lookups == [(wa.USER_ID, MAILER)]
    if expected:
        targets = [warning["target"]["focus_key"] for warning in result["warnings"]]
        assert targets == [f"task:{_email_task(result)['id']}", f"task:{_email_task(result, 'Email the owner')['id']}"]


@pytest.mark.parametrize("run_as, checked, expected", [
    ("", True, ["email_requires_m365_agent", "m365_not_connected"]),
    (wa.USER_ID, True, ["run_as_reapproval", "email_requires_m365_agent", "m365_not_connected"]),
    (wa.RUN_AS_ID, False, ["run_as_reapproval", "email_requires_m365_agent"]),
], ids=["runs as the caller implicitly", "runs as the caller explicitly", "runs as someone else"])
def test_a_missing_m365_connection_is_the_callers_own_only(run_as, checked, expected):
    lookups = []

    def m365_connected(user_id):
        lookups.append(user_id)
        return False

    result, _draft, _model, _bundle = _answer(
        wa.stored_workflow(m365_run_as_user_id=run_as), [EMAIL_TASK], instruction="Email me the problems.",
        m365_connected=m365_connected,
    )
    assert _codes(result) == expected
    assert lookups == ([wa.USER_ID] if checked else [])


@pytest.mark.parametrize("connected", [True, None], ids=["connected", "unknown"])
def test_a_connection_that_is_there_or_unknown_adds_no_warning(connected):
    result, _draft, _model, _bundle = _answer(
        wa.stored_workflow(), [EMAIL_TASK], instruction="Email me the problems.",
        m365_connected=lambda _user_id: connected,
    )
    assert _codes(result) == ["email_requires_m365_agent"]


def test_an_advisory_check_that_fails_adds_no_warning_and_never_fails_the_request():
    def broken(*_args):
        raise RuntimeError(SENTINEL)

    stored = wa.stored_workflow(runner_type="agent", selected_agent=MAILER)
    result, _draft, _model, bundle = _answer(
        stored, [EMAIL_TASK], instruction="Email me the problems.", agent_email_capable=broken, m365_connected=broken,
    )
    assert result["warnings"] == []
    assert SENTINEL not in json.dumps(bundle.logs)


def test_with_little_time_left_the_stored_record_checks_are_skipped_but_run_as_is_not():
    clock = wa.FakeClock()
    lookups = []

    def m365_connected(user_id):
        lookups.append(user_id)
        return False

    def dry_run(_user_id, payload):
        clock.advance(3)
        return {"ok": True, "workflow": payload, "errors": []}

    stored = wa.stored_workflow(m365_run_as_user_id=wa.USER_ID)
    model = wa.ScriptedModel(wa.reply("changed", "Done.", [EMAIL_TASK]), on_call=lambda _call: clock.advance(144))
    bundle = wa.services(model, stored=stored, clock=clock, dry_run=dry_run, m365_connected=m365_connected)
    result = wa.run(wa.request_body(stored=stored), bundle)
    assert _codes(result) == ["run_as_reapproval", "email_requires_m365_agent"]
    assert lookups == []


# ---------------------------------------------------------------------------------------------
# The deadline and the model's finish reasons
# ---------------------------------------------------------------------------------------------

def test_each_model_call_gets_the_time_left_before_the_deadline():
    clock = wa.FakeClock()
    model = wa.ScriptedModel(
        "not JSON", wa.reply("changed", "Renamed.", [RENAME]),
        on_call=lambda call: clock.advance(100) if call == 1 else None,
    )
    bundle = wa.services(model, clock=clock)
    result = wa.run(wa.request_body(), bundle)
    assert result["candidate"]["name"] == "Nightly review"
    # 150 seconds for the whole request, less 5 kept for the check and the response.
    assert model.timeouts == [145.0, 45.0]
    assert wa.finished_log(bundle)["duration_ms"] == 100000


def test_no_model_call_starts_without_time_to_finish_it():
    clock = wa.FakeClock()
    model = wa.ScriptedModel("not JSON", on_call=lambda _call: clock.advance(140))
    limiter = wa.FakeLimiter()
    bundle = wa.services(model, clock=clock, limiter=limiter)
    error = wa.refusal(wa.request_body(), bundle)
    assert (error.status, error.code) == (503, "assistant_timeout")
    assert len(model.calls) == 1
    record = wa.finished_log(bundle)
    assert (record["model_calls"], record["correction_count"], record["invalid_stage"]) == (1, 1, "parse")
    assert limiter.events[-1] == ("release", "lease-1", False)


def test_a_filtered_reply_is_refused_without_a_correction_round():
    model = wa.ScriptedModel(("", "content_filter"))
    bundle = wa.services(model)
    error = wa.refusal(wa.request_body(), bundle)
    assert (error.status, error.code) == (502, "assistant_refused")
    assert len(model.calls) == 1
    assert bundle.recorder.named("dry_run") == []


def test_a_reply_cut_off_at_the_token_limit_is_corrected_once():
    model = wa.ScriptedModel(('{"outcome": "changed", "reply": "Ren', "length"), wa.reply("changed", "Renamed.", [RENAME]))
    bundle = wa.services(model)
    result = wa.run(wa.request_body(), bundle)
    assert result["candidate"]["name"] == "Nightly review"
    assert model.envelope(1)["previous_attempt_errors"] == [
        "The reply was cut off before it ended. Reply with fewer operations or a shorter reply.",
    ]
    assert wa.finished_log(bundle)["invalid_stage"] == "length"


# ---------------------------------------------------------------------------------------------
# Telemetry carries no content
# ---------------------------------------------------------------------------------------------

def _request_full_of_content():
    stored = wa.stored_workflow(description=f"Review new documents. {SENTINEL}")
    draft = wa.editor_draft(stored)
    draft["tasks"][1]["instructions"] = f"Review each new document. {SENTINEL}"
    body = wa.request_body(
        draft, stored=stored, instruction=f"Rename it to Nightly review. {SENTINEL}",
        conversation=[{"role": "user", "text": f"Earlier {SENTINEL}"}, {"role": "assistant", "text": f"Sure {SENTINEL}"}],
        references=[wa.CHECKLIST],
    )
    return stored, body


def _provider_down():
    error = core.WorkflowAssistError("assistant_unavailable")
    error.__cause__ = ConnectionError(SENTINEL)
    return error


CONTENT_RUNS = {
    "changed": ([wa.reply("changed", f"Renamed. {SENTINEL}", [{"op": "set_name", "name": f"Nightly {SENTINEL}"}])], 200),
    "question": ([wa.reply("question", f"Which name? {SENTINEL}")], 200),
    "invalid twice": ([wa.reply("changed", SENTINEL, [{"op": SENTINEL}])] * 2, 502),
    "provider down": ([_provider_down()], 503),
    "unexpected fault": ([RuntimeError(SENTINEL)], 500),
}


@pytest.mark.parametrize("label", list(CONTENT_RUNS))
def test_telemetry_is_content_free_whatever_the_outcome(label):
    replies, status = CONTENT_RUNS[label]
    stored, body = _request_full_of_content()
    model = wa.ScriptedModel(*replies)
    bundle = wa.services(model, stored=stored, excerpts={wa.CHECKLIST["id"]: f"Checklist text {SENTINEL}"})
    if status == 200:
        wa.run(body, bundle)
    else:
        assert wa.refusal(body, bundle).status == status

    logged = json.dumps(bundle.logs)
    for content in (SENTINEL, wa.CHECKLIST["id"], wa.CHECKLIST["label"], wa.WORKFLOW_ID, wa.REVISION, wa.COLLECT_ID):
        assert content not in logged, content
    record = wa.finished_log(bundle)
    assert set(record) == METRIC_KEYS
    assert (record["status"], record["submission_id"], record["user_id"]) == (status, "submission-0001", wa.USER_ID)
    assert (record["turns_received"], record["turns_sent"], record["reference_count"]) == (2, 2, 1)
    level = next(level for message, _extra, level in bundle.logs if message == "[WorkflowAssist] Assist request finished")
    assert level == {200: logging.INFO, 502: logging.WARNING, 503: logging.WARNING, 500: logging.ERROR}[status]


def test_a_successful_request_logs_exactly_its_counts():
    stored, body = _request_full_of_content()
    model = wa.ScriptedModel(wa.reply("changed", "Renamed.", [RENAME]))
    bundle = wa.services(model, stored=stored)
    wa.run(body, bundle)
    assert wa.finished_log(bundle) == {
        "user_id": wa.USER_ID, "submission_id": "submission-0001", "status": 200, "outcome": "changed", "code": None,
        "stage": "response", "error_type": None, "invalid_stage": None, "operation_count": 1, "correction_count": 0,
        "model_calls": 1, "turns_received": 2, "turns_sent": 2, "turns_dropped": 0, "reference_count": 1,
        "excerpt_count": 1, "definition_version": 2, "is_new": False, "warning_codes": [], "fault_location": None,
        "duration_ms": 0,
    }


def test_a_failure_logs_its_category_not_its_message():
    stored, body = _request_full_of_content()
    bundle = wa.services(wa.ScriptedModel(_provider_down()), stored=stored)
    wa.refusal(body, bundle)
    record = wa.finished_log(bundle)
    assert (record["code"], record["error_type"], record["stage"]) == ("assistant_unavailable", "ConnectionError", "model")

    bundle = wa.services(wa.ScriptedModel(RuntimeError(SENTINEL)), stored=stored)
    wa.refusal(body, bundle)
    record = wa.finished_log(bundle)
    assert (record["code"], record["error_type"]) == ("assistant_failed", "RuntimeError")
    assert record["fault_location"].startswith("workflow_assist.py:")


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-q", "-p", "no:cacheprovider"]))
