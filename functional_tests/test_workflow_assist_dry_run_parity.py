#!/usr/bin/env python3
# test_workflow_assist_dry_run_parity.py
"""
Functional test for the AI workflow assistant's save check, over the real workflow store.
Version: 0.261.206
Implemented in: 0.261.206

This test ensures that the assistant checks a candidate exactly as saving it would. It runs the
real personal workflow store and Phase 2's draft service over the recorded doubles of
``test_workflow_draft_service.py``:

* the base reader returns the record the editor loads (``get_personal_workflow``), reads a
  missing, foreign or unreadable ID as not found, and turns a store outage into a 503, never a 404;
* the payload the assistant dry-runs is the editor's save projection of the candidate, the real
  dry run accepts it without writing, and saving that projection stores what the dry run built.
  The weekday schedule and urgent-only alert rule from the roadmap's "Done when" save as checked;
* a `#` document placed as a shared reference passes the save's reference check as the owner;
* a new draft is checked as a new workflow;
* a whole ``expected_count`` given as ``"12"`` or ``12.0`` is checked and saved as the integer 12,
  as the editor's save sends it;
* a change the real build refuses goes back to the model once, and a second refusal is a 502
  with nothing written;
* a save that lands during the model call makes the request a 409 and leaves that save alone.

The model is scripted; nothing here reaches Azure or a model.
"""

import json
import sys
from pathlib import Path

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
sys.path.insert(0, str(ROOT / "functional_tests"))

import functions_workflow_assist_runtime as runtime  # noqa: E402
from functions_workflow_assist import WorkflowAssistError  # noqa: E402
from functions_workflow_assist_editor import editor_original, workflow_for_save  # noqa: E402
from test_support import workflow_assist as wa  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_workflow_draft_save_parity import OWNER_ID, _task, _v2  # noqa: E402
from test_workflow_draft_service import TIMESTAMP_FIELDS, DraftHarness, WriteGuard, _without  # noqa: E402


RESEARCHER = {
    "id": "agent-researcher", "name": "researcher", "display_name": "Researcher", "is_global": False,
    "is_group": False, "group_id": "", "loop_eligible": False,
}
# In the editor's choices but gone from the store, so only the real save check catches it.
RETIRED = {
    "id": "agent-retired-0009", "name": "retired", "display_name": "Retired helper", "is_global": False,
    "is_group": False, "group_id": "", "loop_eligible": False,
}
# The options ``get_workflow_editor_options`` builds for the harness's settings, plus RETIRED.
OPTIONS = {
    "agents": [RESEARCHER, RETIRED],
    "models": [{
        "endpoint_id": "endpoint-global", "model_id": "model-4o", "label": "Global AOAI / gpt-4o", "provider": "aoai",
        "loop_eligible": True,
    }],
    "default_model": {"label": "Default app model", "valid": True, "loop_eligible": True},
    "max_tasks": 50,
    "schedule": {"min_interval_seconds": 300},
}
CHECKLIST = {"kind": "document", "id": "doc-checklist", "label": "Security checklist.pdf", "scope": {"kind": "personal"}}
LABELS = {CHECKLIST["id"]: CHECKLIST["label"]}
STYLE_REFERENCE = {
    "id": "reference-style-0009", "name": "Style_guide", "document_id": "doc-style-0009",
    "scope_type": "personal", "scope_id": OWNER_ID,
}

WEEKDAYS_AT_SEVEN = {"op": "set_schedule_calendar", "frequency": "weekdays", "time_of_day": "07:00"}
URGENT_PROMPT = "The results include something urgent that needs attention today."
URGENT_ONLY = [
    {"op": "set_alert_mode", "mode": "rules"},
    {"op": "add_alert_rule", "name": "Urgent findings", "severity": "high",
     "condition": {"type": "model_evaluation", "prompt": URGENT_PROMPT}},
]
SAVE_ONLY_FIELDS = TIMESTAMP_FIELDS | {"definition_revision"}


@pytest.fixture
def harness():
    return DraftHarness()


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.206")


def _seed(harness, **fields):
    """Save one workflow as its owner; returns it as the editor loads it."""
    payload = _v2(
        "Document review", description="Review new documents.",
        tasks=[
            _task("collect", "Collect", "Collect the new documents.", reference_ids=[]),
            _task("review", "Review", "Review each new document and list any problems."),
        ],
        **fields,
    )
    saved = harness.save_personal("create", payload)
    assert saved is not None, harness.steps[-1]["error"]
    return harness.load_personal(saved["id"])


def _resolve(user_id, references):
    """``resolve_scope_references`` for the owner's own documents."""
    return [{
        "kind": "document", "id": reference["id"], "label": LABELS[reference["id"]],
        "scope": {"kind": "personal", "id": user_id, "name": "Personal"},
    } for reference in references]


def _services(harness, model, *, container=None):
    """The assistant's services over the harness: the real base reader and the real dry run."""
    guarded = container if container is not None else WriteGuard(
        "personal_workflows", harness.containers["personal_workflows"],
    )

    def read_base(user_id, workflow_id):
        return runtime.read_workflow_base(guarded, user_id, workflow_id)

    def dry_run(user_id, payload):
        # The arguments build_workflow_assist_services passes to dry_run_personal_workflow.
        return harness.call(
            "dry_run_personal_workflow", user_id, payload, actor_user_id=user_id, settings=harness.settings,
        )

    return wa.services(model, options=OPTIONS, dry_run=dry_run, read_base=read_base, resolve=_resolve)


def _checked(bundle):
    return [payload for _user_id, payload in bundle.recorder.named("dry_run")]


def _save_as_checked(harness, stored, candidate):
    """Save the candidate the way the editor would, and check the dry run built the same document."""
    projection = workflow_for_save(wa.json_copy(candidate), editor_original(stored))
    dry = harness.call(
        "dry_run_personal_workflow", OWNER_ID, projection, actor_user_id=OWNER_ID, settings=harness.settings,
    )
    assert dry["ok"] is True, dry["errors"]
    saved = harness.save_personal("assist", projection, actor_user_id=OWNER_ID)
    assert saved is not None, harness.steps[-1]["error"]
    assert _without(saved, SAVE_ONLY_FIELDS) == _without(dry["workflow"], SAVE_ONLY_FIELDS)
    revision = harness.modules["functions_workflow_definitions"].workflow_definition_revision(dry["workflow"])
    assert saved["definition_revision"] == revision
    return projection, saved


# ---------------------------------------------------------------------------------------------
# The base
# ---------------------------------------------------------------------------------------------

def test_the_base_is_the_record_the_editor_loads(harness):
    stored = _seed(
        harness, trigger_type="interval",
        schedule={"kind": "calendar", "frequency": "daily", "time_of_day": "08:30", "timezone": "Europe/London"},
        alert_mode="rules", alert_rules=[{
            "name": "Run failed", "severity": "high", "condition": {"type": "run_status", "statuses": ["failed"]},
        }],
        reference_inputs=[STYLE_REFERENCE],
    )
    guarded = WriteGuard("personal_workflows", harness.containers["personal_workflows"])

    loaded = runtime.read_workflow_base(guarded, OWNER_ID, stored["id"])
    assert loaded == stored
    assert not [key for key in loaded if key.startswith("_")]
    assert runtime.read_workflow_base(guarded, "someone-else", stored["id"]) is None
    assert runtime.read_workflow_base(guarded, OWNER_ID, "workflow-missing") is None
    assert runtime.read_workflow_base(guarded, OWNER_ID, f"{stored['id']}/other") is None
    assert harness.writes() == {"personal_workflows": [("create_item", stored["id"])]}


@pytest.mark.parametrize("status, expected", [(400, None), (404, None), (429, 503), (500, 503), (503, 503)])
def test_a_store_outage_is_a_503_never_a_missing_workflow(status, expected):
    class Failing:
        def read_item(self, item, partition_key, **kwargs):
            raise CosmosHttpResponseError(status_code=status, message="SENTINEL store message")

    if expected is None:
        assert runtime.read_workflow_base(Failing(), OWNER_ID, "workflow-1") is None
        return
    with pytest.raises(WorkflowAssistError) as caught:
        runtime.read_workflow_base(Failing(), OWNER_ID, "workflow-1")
    assert (caught.value.status, caught.value.code) == (expected, "assistant_unavailable")
    assert "SENTINEL" not in caught.value.message


# ---------------------------------------------------------------------------------------------
# The save check is the save
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("run_as", ["", OWNER_ID], ids=["without Run as", "with Run as"])
def test_the_weekday_schedule_and_urgent_alert_pass_the_real_check_and_save_as_checked(harness, run_as):
    stored = _seed(harness, m365_run_as_user_id=run_as)
    assert stored["m365_run_as_user_id"] == run_as
    writes = harness.writes()
    model = wa.ScriptedModel(wa.reply("changed", "It now runs at 7:00 on weekdays.", [WEEKDAYS_AT_SEVEN, *URGENT_ONLY]))
    bundle = _services(harness, model)
    body = wa.request_body(
        stored=stored, instruction="Run this at 7 AM on weekdays and only alert me when something is urgent.",
    )

    with harness.guarded():
        result = wa.run(body, bundle, user_id=OWNER_ID)

    assert harness.writes() == writes
    assert result["outcome"] == "changed"
    assert [warning["code"] for warning in result["warnings"]] == (["run_as_reapproval"] if run_as else [])
    candidate = result["candidate"]
    # The assistant checked the editor's save projection of the candidate, once.
    [checked] = _checked(bundle)
    projection, saved = _save_as_checked(harness, stored, candidate)
    assert checked == projection
    assert saved["trigger_type"] == "interval"
    assert {key: saved["schedule"][key] for key in ("kind", "frequency", "time_of_day", "timezone")} == {
        "kind": "calendar", "frequency": "weekdays", "time_of_day": "07:00", "timezone": wa.TIME_ZONE,
    }
    assert saved["alert_mode"] == "rules"
    assert [(rule["name"], rule["severity"], rule["condition"]) for rule in saved["alert_rules"]] == [
        ("Urgent findings", "high", {"type": "model_evaluation", "prompt": URGENT_PROMPT}),
    ]
    assert saved["alert_rules"][0]["id"] == candidate["alert_rules"][0]["id"]


def test_a_document_placed_as_a_shared_reference_passes_the_saves_reference_check(harness):
    stored = _seed(harness)
    writes = harness.writes()
    model = wa.ScriptedModel(wa.reply(
        "changed", "Review now compares each new document against Security checklist.pdf.",
        [{"op": "bind_reference", "document": "ref_1", "tasks": ["task_2"]}],
    ))
    bundle = _services(harness, model)
    body = wa.request_body(
        stored=stored, instruction="Compare every new document against #checklist.", references=[CHECKLIST],
    )

    with harness.guarded():
        result = wa.run(body, bundle, user_id=OWNER_ID)

    assert harness.writes() == writes
    reference = {
        "id": f"personal:{OWNER_ID}:{CHECKLIST['id']}", "name": "Security_checklist_pdf",
        "document_id": CHECKLIST["id"], "scope_type": "personal", "scope_id": OWNER_ID,
    }
    assert result["candidate"]["reference_inputs"] == [reference]
    checks_before = len(harness.called("authorize_workflow_reference"))
    _projection, saved = _save_as_checked(harness, stored, result["candidate"])
    assert saved["reference_inputs"] == [reference]
    assert wa.task_by_id(saved, "collect")["reference_ids"] == []
    assert "reference_ids" not in wa.task_by_id(saved, "review")
    # The dry run and the save both checked the new document as its owner.
    checks = harness.called("authorize_workflow_reference")
    assert [(call[2]["document_id"], call[3]) for call in checks[checks_before:]] == [
        (CHECKLIST["id"], OWNER_ID), (CHECKLIST["id"], OWNER_ID),
    ]


def test_a_new_draft_is_checked_as_a_new_workflow(harness):
    model = wa.ScriptedModel(wa.reply("changed", "Renamed it.", [{"op": "set_name", "name": "Nightly review"}]))
    bundle = _services(harness, model)

    with harness.guarded():
        result = wa.run(wa.request_body(wa.new_draft()), bundle, user_id=OWNER_ID)

    assert harness.writes() == {}
    [checked] = _checked(bundle)
    assert checked == workflow_for_save(wa.json_copy(result["candidate"]), None)
    assert "id" not in checked and "definition_revision" not in checked
    dry = harness.call("dry_run_personal_workflow", OWNER_ID, checked, settings=harness.settings)
    assert dry["ok"] is True, dry["errors"]
    assert dry["workflow"]["name"] == "Nightly review"


@pytest.mark.parametrize("expected_count", ["12", 12.0], ids=["numeric string", "whole float"])
def test_a_whole_expected_count_is_checked_and_saved_as_an_integer(harness, expected_count):
    # The editor's save sends Number('12') and 12.0 as the JSON integer 12, and the build refuses
    # any count that is not an int, so the check has to see the same integer.
    stored = _seed(harness)
    writes = harness.writes()
    draft = wa.editor_draft(stored)
    wa.task_by_id(draft, "review")["output_contract"] = {"kind": "records", "expected_count": expected_count}
    model = wa.ScriptedModel(wa.reply("changed", "Renamed it.", [{"op": "set_name", "name": "Nightly review"}]))
    bundle = _services(harness, model)

    with harness.guarded():
        result = wa.run(wa.request_body(draft, stored=stored), bundle, user_id=OWNER_ID)

    assert harness.writes() == writes
    assert result["outcome"] == "changed"
    assert "draft_has_errors" not in [warning["code"] for warning in result["warnings"]]
    [checked] = _checked(bundle)
    checked_count = wa.task_by_id(checked, "review")["output_contract"]["expected_count"]
    assert type(checked_count) is int and checked_count == 12
    projection, saved = _save_as_checked(harness, stored, result["candidate"])
    # Type-strict: 12 == 12.0 in Python, but not in the JSON the build reads.
    assert json.dumps(checked, sort_keys=True) == json.dumps(projection, sort_keys=True)
    saved_count = wa.task_by_id(saved, "review")["output_contract"]["expected_count"]
    assert type(saved_count) is int and saved_count == 12
    assert saved["name"] == "Nightly review"


def test_a_change_the_real_build_refuses_goes_back_once_and_a_second_refusal_is_a_502(harness):
    stored = _seed(harness)
    writes = harness.writes()
    retired = {"op": "set_task_runner", "task": "task_2", "runner": "agent", "agent": "agent_2"}
    researcher = {"op": "set_task_runner", "task": "task_2", "runner": "agent", "agent": "agent_1"}
    body = wa.request_body(stored=stored, instruction="Have an agent do the review.")

    model = wa.ScriptedModel(wa.reply("changed", "Done.", [retired]), wa.reply("changed", "Done.", [researcher]))
    with harness.guarded():
        result = wa.run(body, _services(harness, model), user_id=OWNER_ID)
    assert harness.writes() == writes
    # The dry run returns what the save route would: its public message, never the build's own text.
    assert model.envelope(1)["previous_attempt_errors"] == [
        "Saving the changed workflow would fail. Invalid workflow settings. Review the task, runner, trigger, and "
        "document inputs.",
    ]
    assert "Select a valid" not in model.text()
    assert wa.task_by_id(result["candidate"], "review")["runner"] == {"type": "agent", "selected_agent": RESEARCHER}
    _save_as_checked(harness, stored, result["candidate"])
    writes = harness.writes()

    stored = harness.load_personal(stored["id"])
    body = wa.request_body(stored=stored, instruction="Have the retired helper do the collecting.")
    retired = {**retired, "task": "task_1"}
    model = wa.ScriptedModel(wa.reply("changed", "Done.", [retired]), wa.reply("changed", "Done.", [retired]))
    bundle = _services(harness, model)
    with harness.guarded():
        error = wa.refusal(body, bundle, user_id=OWNER_ID)
    assert (error.status, error.code) == (502, "assistant_output_invalid")
    assert len(model.calls) == 2
    assert harness.writes() == writes
    assert harness.load_personal(stored["id"]) == stored


def test_a_save_that_lands_during_the_model_call_is_a_409_and_that_save_stands(harness):
    stored = _seed(harness)
    writes = harness.writes()["personal_workflows"]

    def save_elsewhere(_call):
        saved = harness.save_personal("elsewhere", {**stored, "description": "Changed in another tab."},
                                      actor_user_id=OWNER_ID)
        assert saved is not None, harness.steps[-1]["error"]

    model = wa.ScriptedModel(wa.reply("changed", "Renamed it.", [{"op": "set_name", "name": "Nightly review"}]),
                             on_call=save_elsewhere)
    error = wa.refusal(wa.request_body(stored=stored), _services(harness, model), user_id=OWNER_ID)

    assert (error.status, error.code) == (409, "workflow_definition_conflict")
    assert harness.writes()["personal_workflows"] == [*writes, ("replace_item", stored["id"])]
    current = harness.load_personal(stored["id"])
    assert (current["name"], current["description"]) == ("Document review", "Changed in another tab.")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
