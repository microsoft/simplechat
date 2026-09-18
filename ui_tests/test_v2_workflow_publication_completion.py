# test_v2_workflow_publication_completion.py
"""
UI coverage for publication completion authoring and exact run inspection.
Version: 0.261.118
Implemented in: 0.261.118

The production SPA uses a closed API fixture with serialized public publication
status. Tests never publish a document, invoke a model, or contact a live service.
"""

import copy
import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

# Shared fixture imports require the repository-local module paths above.
from ui_tests.fixtures.workflow_publication_completion import (
    GROUP_ID,
    connect_options,  # noqa: F401
    execution_id,
    publication_key,
    publication_status,
    publication_ui,  # noqa: F401
)


pytestmark = pytest.mark.ui
POLICIES = ["submitted", "approved", "indexed_ready"]


def saved_workflow(ui, scope="user"):
    workflow_id = publication_key(scope)[1]
    return ui.group_workflows[GROUP_ID][workflow_id] if scope == "group" else ui.personal_workflows[workflow_id]


def open_editor(ui, scope="user", **viewport):
    record = saved_workflow(ui, scope)
    record.pop("active_run_id", None)
    record.pop("status", None)
    ui.workflow_runs[record["id"]] = []
    if scope == "group":
        ui.open("/groups", **viewport)
        ui.page.get_by_label("Group workspace", exact=True).select_option(GROUP_ID)
        ui.page.get_by_role("button", name=f"Edit {record['name']}", exact=True).click()
    else:
        ui.open(f"/workspace/workflows?workflow_id={record['id']}", **viewport)
    expect(ui.page.get_by_role("dialog", name="Edit workflow", exact=True)).to_be_visible()
    return publication_fields(ui.page)


def publication_fields(page):
    block = page.get_by_role("region", name="Publish artifact block", exact=True)
    block.get_by_text("Runner, inputs, references and outputs", exact=True).click()
    return block


def policy_field(block):
    return block.get_by_label("Complete publication when for Publish artifact", exact=True)


def save_editor(ui):
    ui.page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(ui.page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    return ui.workflow_writes[-1]


def open_run(ui, scope="user", **viewport):
    record = saved_workflow(ui, scope)
    if scope == "group":
        ui.open("/groups", **viewport)
        ui.page.get_by_label("Group workspace", exact=True).select_option(GROUP_ID)
    else:
        ui.open("/workspace/workflows", **viewport)
    row = ui.page.get_by_role("listitem").filter(has_text=record["name"]).first
    row.get_by_role("button", name="Show run history", exact=True).click()
    row.get_by_role("button", name="Show run task results", exact=True).click()
    expect(ui.page.get_by_text("Workflow execution history", exact=True)).to_be_visible()
    _, workflow_id, run_id = publication_key(scope)
    return execution_id(workflow_id, run_id, "publish")


def expect_fact(region, name, value):
    term = region.locator("dt").filter(has_text=re.compile(f"^{re.escape(name)}$"))
    expect(term.locator("..").locator("dd")).to_have_text(value)


def runtime_writes(ui):
    return [request for request in ui.writes if "/runtime/" in request.path]


@pytest.mark.parametrize("scope", ["user", "group"])
@pytest.mark.parametrize("policy", POLICIES)
def test_authoring_reopens_policy_and_clears_only_incompatible_destination_ids(publication_ui, scope, policy):
    ui, page = publication_ui, publication_ui.page
    block = open_editor(ui, scope)
    policy_field(block).select_option(policy)
    for destination, identifier in (("group", GROUP_ID), ("public", "public-handbook"), ("personal", None)):
        block.get_by_label("Publication scope for Publish artifact", exact=True).select_option(destination)
        if identifier:
            block.get_by_label("Publication workspace ID for Publish artifact", exact=True).fill(identifier)
        expect(policy_field(block)).to_have_value(policy)
    if scope == "group":
        block.get_by_label("Publication scope for Publish artifact", exact=True).select_option("group")
        block.get_by_label("Publication workspace ID for Publish artifact", exact=True).fill(GROUP_ID)
    write = save_editor(ui)
    assert write.body["tasks"][1]["publication"] == {
        "artifact_format": "md", "workspace_scope": "group" if scope == "group" else "personal",
        "completion_policy": policy, **({"group_id": GROUP_ID} if scope == "group" else {}),
    }
    assert write.body["definition_version"] == 3 and write.body["durable_execution"] is True
    assert write.query.get("group_id") == ([GROUP_ID] if scope == "group" else None)
    page.get_by_role("button", name=f"Edit {saved_workflow(ui, scope)['name']}", exact=True).click()
    expect(policy_field(publication_fields(page))).to_have_value(policy)
    assert not runtime_writes(ui)


@pytest.mark.parametrize("scope", ["user", "group"])
@pytest.mark.parametrize("advertised", [True, False])
def test_legacy_omission_survives_an_unrelated_edit(publication_ui, scope, advertised):
    ui = publication_ui
    record = saved_workflow(ui, scope)
    record["tasks"][1]["publication"].pop("completion_policy")
    original = copy.deepcopy(record["tasks"][1]["publication"])
    ui.publication_policies = POLICIES if advertised else None
    block = open_editor(ui, scope)
    expect(policy_field(block)).to_have_value("")
    expect(policy_field(block).locator("option:checked")).to_have_text("Existing behavior (no completion policy)")
    if not advertised:
        expect(policy_field(block)).to_be_disabled()
    block.get_by_label("Instructions", exact=True).fill("Publish the saved artifact with the existing behavior.")
    assert save_editor(ui).body["tasks"][1]["publication"] == original


@pytest.mark.parametrize("scope", ["user", "group"])
@pytest.mark.parametrize("capabilities", [POLICIES, None, ["approved"]])
def test_new_publication_defaults_to_submitted_only_when_advertised(publication_ui, scope, capabilities):
    ui = publication_ui
    saved_workflow(ui, scope)["tasks"][1].pop("publication")
    ui.publication_policies = capabilities
    block = open_editor(ui, scope)
    block.get_by_text("Publish an existing analysis artifact", exact=True).click()
    expected = "submitted" if capabilities and "submitted" in capabilities else ""
    expect(policy_field(block)).to_have_value(expected)
    publication = save_editor(ui).body["tasks"][1]["publication"]
    if expected:
        assert publication["completion_policy"] == "submitted"
    else:
        assert "completion_policy" not in publication


def test_explicitly_returning_to_existing_behavior_removes_the_policy(publication_ui):
    ui, page = publication_ui, publication_ui.page
    block = open_editor(ui)
    policy_field(block).select_option("")
    assert "completion_policy" not in save_editor(ui).body["tasks"][1]["publication"]
    page.get_by_role("button", name="Edit Publication workflow", exact=True).click()
    expect(policy_field(publication_fields(page))).to_have_value("")


@pytest.mark.parametrize("policy,capabilities,version,durable", [
    ("indexed_ready", None, 3, True),
    ("indexed_ready", ["submitted"], 3, True),
    ("future_policy", POLICIES, 3, True),
    (None, POLICIES, 3, True),
    ("", POLICIES, 3, True),
    ({"level": "approved"}, POLICIES, 3, True),
    (["submitted"], POLICIES, 3, True),
    ("submitted", POLICIES, 2, True),
    ("submitted", POLICIES, 3, False),
])
def test_unsupported_completion_semantics_preserve_payload_read_only(publication_ui, policy, capabilities, version, durable):
    ui, page = publication_ui, publication_ui.page
    record = saved_workflow(ui)
    record["tasks"][1]["publication"]["completion_policy"] = copy.deepcopy(policy)
    record["definition_version"] = version
    record["durable_execution"] = durable
    original_publication = copy.deepcopy(record["tasks"][1]["publication"])
    ui.publication_policies = capabilities
    record.pop("active_run_id", None)
    ui.workflow_runs[record["id"]] = []
    ui.open(f"/workspace/workflows?workflow_id={record['id']}")
    expect(page.get_by_role("alert").filter(has_text="completion polic")).to_be_visible()
    expect(page.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    expect(page.get_by_label("Workflow name", exact=True)).to_be_disabled()
    assert record["tasks"][1]["publication"] == original_publication
    assert not ui.workflow_writes


@pytest.mark.parametrize("destination,changes,heading", [
    ("personal", {
        "completion_policy": "submitted", "policy_satisfied": True, "state": "submitted",
        "reason_code": "publication_submitted", "unresolved_stages": [],
    }, "Publication submitted"),
    ("personal", {
        "completion_policy": "approved", "policy_satisfied": True, "state": "approved",
        "reason_code": "publication_approved", "unresolved_stages": [],
    }, "Publication approval requirement met"),
    ("group", {
        "completion_policy": "submitted", "policy_satisfied": True, "state": "submitted",
        "reason_code": "publication_submitted", "unresolved_stages": [],
    }, "Publication submitted"),
    ("group", {}, "Waiting for destination approval"),
    ("group", {
        "state": "waiting_processing", "approval": "approved", "processing": "running",
        "reason_code": "publication_waiting_processing", "unresolved_stages": ["processing"],
    }, "Waiting for document processing"),
    ("public", {
        "state": "waiting_screening", "approval": "approved", "processing": "complete", "screening": "held",
        "reason_code": "publication_waiting_screening", "unresolved_stages": ["screening"],
    }, "Waiting for content screening"),
    ("group", {
        "state": "waiting_index", "approval": "approved", "processing": "complete", "screening": "available",
        "reason_code": "publication_waiting_index", "unresolved_stages": ["index"],
    }, "Waiting for search visibility"),
    ("public", {
        "policy_satisfied": True, "state": "indexed_ready", "approval": "approved",
        "processing": "complete", "screening": "available", "index": "ready",
        "reason_code": "publication_indexed_ready", "unresolved_stages": [],
    }, "Publication indexed and ready"),
])
def test_actual_publication_facts_do_not_imply_later_stage_completion(publication_ui, destination, changes, heading):
    ui, page = publication_ui, publication_ui.page
    status = publication_status(destination, **changes)
    ui.set_publication_status(status)
    eid = open_run(ui)
    summary = page.get_by_role("region", name=f"Publication for execution {eid}", exact=True)
    displayed_heading = f"Saved completion observation: {heading}" if status["policy_satisfied"] else heading
    expect(summary.get_by_text(displayed_heading, exact=True)).to_be_visible()
    if status["policy_satisfied"]:
        expect(summary).to_contain_text("Later destination changes do not update this snapshot.")
        expect(summary).to_contain_text("does not confirm current destination approval, availability, or index readiness.")
    else:
        expect(summary.get_by_text("Saved completion observation:", exact=False)).to_have_count(0)
    labels = {"submitted": "Submitted", "approved": "Approved", "indexed_ready": "Indexed and ready"}
    expect_fact(summary, "Requested completion", labels[status["completion_policy"]])
    expect_fact(summary, "Completion requirement", "Met" if status["policy_satisfied"] else "Not met")
    for label, field in (
        ("Submission", "submission"), ("Destination approval", "approval"),
        ("Processing", "processing"), ("Screening", "screening"), ("Index", "index"),
    ):
        expect_fact(summary, label, status[field].replace("_", " ").capitalize())
    expect(summary).to_contain_text(status["id"])
    expect(summary).to_contain_text(status["document_id"])
    expect(summary.get_by_role("link")).to_have_count(0)
    if not status["policy_satisfied"]:
        gate = page.get_by_role("region", name="Publication status", exact=True)
        expect(gate.get_by_text(heading, exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Cancel run", exact=True)).to_be_visible()
    for name in ("Approve task", "Reject task", "Retry task"):
        expect(page.get_by_role("button", name=name, exact=True)).to_have_count(0)
    assert not runtime_writes(ui)


def test_exact_attempt_status_and_output_do_not_reuse_an_older_attempt(publication_ui):
    ui, page = publication_ui, publication_ui.page
    status = publication_status(
        "group", state="indexed_ready", approval="approved", processing="complete",
        screening="available", index="ready", policy_satisfied=True,
        reason_code="publication_indexed_ready", unresolved_stages=[],
    )
    ui.set_publication_status(status, scope="group", attempt=2)
    scope, workflow_id, run_id = publication_key("group")
    eid = execution_id(workflow_id, run_id, "publish")
    attempts = ui.attempt_pages[(scope, workflow_id, run_id, eid)][""]["items"]
    attempts.insert(0, {
        "execution_id": eid, "node_id": "publish", "task_id": "publish", "iteration_path": [],
        "attempt": 1, "state": "paused",
        "workflow_result": {"publication": publication_status(
            "group", state="uncertain", submission="uncertain", reason_code="publication_uncertain",
            retryable=True, unresolved_stages=["submission"],
        )},
    })
    open_run(ui, "group")
    page.get_by_role("button", name=f"Show execution attempts for {eid}", exact=True).click()
    earlier = page.get_by_role("region", name=f"Publication for execution {eid} attempt 1", exact=True)
    current = page.get_by_role("region", name=f"Publication for execution {eid} attempt 2", exact=True)
    expect_fact(earlier, "Submission", "Uncertain")
    expect_fact(earlier, "Completion requirement", "Not met")
    expect_fact(current, "Index", "Ready")
    expect_fact(current, "Completion requirement", "Met")
    expect(earlier.get_by_text("Saved completion observation:", exact=False)).to_have_count(0)
    expect(current.get_by_text("Saved completion observation: Publication indexed and ready", exact=True)).to_be_visible()
    expect(current).to_contain_text("Refresh rereads the saved observation")
    page.get_by_role("button", name="Load authoritative output excerpt", exact=True).click()
    expect(page.locator("pre").filter(has_text='"attempt":2')).to_be_visible()
    request = next(request for request in ui.requests if request.path.endswith("/result"))
    assert request.path == f"/api/group/workflows/{workflow_id}/runs/{run_id}/executions/{eid}/attempts/2/result"
    assert request.query["group_id"] == [GROUP_ID]
    assert not any("/tasks/" in request.path for request in ui.requests)


def test_stale_resume_requires_review_and_never_republishes(publication_ui):
    ui, page = publication_ui, publication_ui.page
    status = publication_status(
        "group", state="uncertain", submission="uncertain", retryable=True,
        reason_code="publication_uncertain", unresolved_stages=["submission"],
    )
    ui.set_publication_status(status, scope="group")
    key = publication_key("group")
    original_gate = copy.deepcopy(ui.workflow_runtimes[key]["gate"])
    open_run(ui, "group", width=390, height=844, theme="dark")
    ui.assert_no_overflow()
    ui.stale_publication_decision = True
    resume = page.get_by_role("button", name="Resume / check again", exact=True)
    resume.focus()
    resume.press("Enter")
    expect(page.get_by_role("alert").filter(has_text="Runtime changed before your decision")).to_be_visible()
    assert len(runtime_writes(ui)) == 1
    assert runtime_writes(ui)[0].body["gate_id"] == original_gate["id"]
    expect(page.get_by_role("region", name="Publication status", exact=True)).to_contain_text(status["id"])
    resume.click()
    expect(resume).to_have_count(0)
    first, second = runtime_writes(ui)
    assert second.body["expected_version"] == first.body["expected_version"] + 1
    assert second.body["gate_id"] != first.body["gate_id"]
    assert second.body["request_id"] != first.body["request_id"]
    assert all(request.query.get("group_id") == [GROUP_ID] for request in (first, second))
    assert all(request.path.endswith("/runtime/decision") for request in runtime_writes(ui))
    assert not any(request.path.endswith(("/run", "/publish", "/promote")) for request in ui.writes)


@pytest.mark.parametrize("state,retryable", [
    ("uncertain", True), ("approval_failed", True), ("processing_failed", False),
    ("rejected", False), ("cancelled", False), ("content_changed", False), ("unavailable", True),
])
def test_unmet_publication_uses_only_backend_allowed_pause_actions(publication_ui, state, retryable):
    ui, page = publication_ui, publication_ui.page
    status = publication_status(
        "group", state=state, retryable=retryable, reason_code=f"publication_{state}",
        submission="uncertain" if state == "uncertain" else "confirmed",
        approval={"rejected": "rejected", "cancelled": "cancelled", "approval_failed": "failed",
                  "processing_failed": "approved", "content_changed": "approved"}.get(state, "pending"),
        processing={"processing_failed": "failed", "content_changed": "complete"}.get(state, "not_started"),
        screening="changed" if state == "content_changed" else "not_required",
        index="unavailable" if state in {"unavailable", "content_changed"} else "pending",
        unresolved_stages=[{
            "uncertain": "submission", "approval_failed": "approval", "rejected": "approval",
            "cancelled": "approval", "processing_failed": "processing", "content_changed": "screening",
            "unavailable": "index",
        }[state]],
    )
    ui.set_publication_status(status)
    open_run(ui)
    expect(page.get_by_role("region", name="Publication status", exact=True)).to_contain_text(f"Reason code: publication_{state}")
    expect(page.get_by_role("button", name="Resume / check again", exact=True)).to_have_count(1 if retryable else 0)
    expect(page.get_by_role("button", name="Cancel run", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Retry task", exact=True)).to_have_count(0)
    if state == "content_changed":
        page.get_by_role("button", name="Cancel run", exact=True).click()
        expect(page.get_by_role("region", name="Publication status", exact=True)).to_have_count(0)
        assert runtime_writes(ui)[0].body["choice"] == "cancel"


@pytest.mark.parametrize("endpoint", ["runtime", "executions", "attempts"])
@pytest.mark.parametrize("status_code", [403, 404])
def test_access_failure_removes_all_cached_publication_details(publication_ui, endpoint, status_code):
    ui, page = publication_ui, publication_ui.page
    eid = open_run(ui)
    page.get_by_role("button", name=f"Show execution attempts for {eid}", exact=True).click()
    expect(page.get_by_role("region", name=f"Publication for execution {eid} attempt 1", exact=True)).to_be_visible()
    _, workflow_id, run_id = publication_key()
    suffix = f"executions/{eid}/attempts" if endpoint == "attempts" else endpoint
    path = f"/api/user/workflows/{workflow_id}/runs/{run_id}/{suffix}"
    ui.failures.append(("GET", path, status_code, {"error": "Publication access is no longer available."}))
    if endpoint != "runtime":
        history = page.get_by_role("list", name="Workflow run history", exact=True)
        history.get_by_role("button", name="Refresh", exact=True).nth(1 if endpoint == "attempts" else 0).click()
    expect(page.get_by_role("alert").filter(has_text="Cached run details were removed")).to_be_visible(timeout=10000)
    expect(page.get_by_role("region", name=re.compile("^Publication (status|for execution)"))).to_have_count(0)
    expect(page.get_by_text("published-personal-document", exact=False)).to_have_count(0)


@pytest.mark.parametrize("status_code", [403, 404])
def test_resume_access_failure_clears_the_gate_and_history(publication_ui, status_code):
    ui, page = publication_ui, publication_ui.page
    ui.set_publication_status(publication_status(state="uncertain", retryable=True, reason_code="publication_uncertain"))
    open_run(ui)
    ui.fail_next_runtime_decision(status_code)
    page.get_by_role("button", name="Resume / check again", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="Cached run details were removed")).to_be_visible()
    expect(page.get_by_role("region", name=re.compile("^Publication (status|for execution)"))).to_have_count(0)


@pytest.mark.parametrize("location,field,value", [
    ("runtime", "state", "future_state"),
    ("runtime", "policy_satisfied", "true"),
    ("executions", "document_version", 0),
    ("executions", "private_reference", {"blob": "private-publication-marker"}),
    ("attempts", "completion_policy", None),
    ("attempts", "reason_code", "provider error: private-publication-marker"),
])
def test_malformed_publication_status_is_never_rendered_as_a_fact(publication_ui, location, field, value):
    ui, page = publication_ui, publication_ui.page
    key = publication_key()
    eid = execution_id(key[1], key[2], "publish")
    if location == "runtime":
        status = ui.workflow_runtimes[key]["gate"]["publication"]
    elif location == "executions":
        status = ui.execution_pages[key][""]["items"][0]["workflow_result"]["publication"]
    else:
        status = ui.attempt_pages[(*key, eid)][""]["items"][0]["workflow_result"]["publication"]
    status[field] = value
    open_run(ui)
    if location == "attempts":
        page.get_by_role("button", name=f"Show execution attempts for {eid}", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="unsupported")).to_be_visible()
    label = "Publication status" if location == "runtime" else f"Publication for execution {eid}"
    if location == "attempts":
        label += " attempt 1"
    expect(page.get_by_role("region", name=label, exact=True)).to_have_count(0)
    expect(page.get_by_text("private-publication-marker", exact=False)).to_have_count(0)
    assert not runtime_writes(ui)


def test_attempt_response_cannot_show_another_executions_receipt(publication_ui):
    ui, page = publication_ui, publication_ui.page
    key = publication_key()
    eid = execution_id(key[1], key[2], "publish")
    ui.attempt_pages[(*key, eid)][""]["items"][0]["execution_id"] = execution_id(key[1], key[2], "analyze")
    open_run(ui)
    page.get_by_role("button", name=f"Show execution attempts for {eid}", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="unsupported response")).to_be_visible()
    expect(page.get_by_role("region", name=f"Publication for execution {eid} attempt 1", exact=True)).to_have_count(0)


def test_mobile_keyboard_policy_selection_preserves_task_and_flow_identity(publication_ui):
    ui, page = publication_ui, publication_ui.page
    original = copy.deepcopy(saved_workflow(ui))
    block = open_editor(ui, width=390, height=844, theme="dark")
    policy = policy_field(block)
    policy.focus()
    policy.press("ArrowUp")
    expect(policy).to_have_value("approved")
    expect(block.get_by_text("Personal workspace approval is not required.", exact=False)).to_be_visible()
    ui.assert_no_overflow()
    save = page.get_by_role("button", name="Save workflow", exact=True)
    save.focus()
    save.press("Enter")
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    payload = ui.workflow_writes[-1].body
    assert payload["tasks"][1]["publication"]["completion_policy"] == "approved"
    assert payload["flow"] == original["flow"]
    assert [task["id"] for task in payload["tasks"]] == [task["id"] for task in original["tasks"]]
    ui.assert_no_overflow()
