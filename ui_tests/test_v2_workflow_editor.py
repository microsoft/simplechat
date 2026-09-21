# test_v2_workflow_editor.py
"""
UI tests for the native V2 LIST workflow editor.
Version: 0.261.127
Implemented in: 0.261.108

These tests use the real V2 SPA bundle with a closed API fixture. They cover
create/edit, stable task input bindings, shared references, schema validation,
legacy-field preservation, unsupported read-only definitions, 409 draft
retention, scoped group requests, dirty group-switch guards, and run inspection.
"""

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

from ui_tests.fixtures.workflow_editor import (
    GROUP_ID,
    OWNER_ID,
    WORKFLOW_ID,
    connect_options,  # noqa: F401
    workflow_ui,  # noqa: F401
)


pytestmark = pytest.mark.ui


def labelled(page, name):
    return page.get_by_label(re.compile(rf"^{re.escape(name)}(?:\s*\*)?\s*$"))


def open_task_details(page, index):
    summary = page.get_by_text("Runner, inputs, references and outputs", exact=True).nth(index)
    summary.click()


def workflow_post(ui):
    writes = [
        request for request in ui.workflow_writes
        if request.method == "POST" and request.path in {"/api/user/workflows", "/api/group/workflows"}
    ]
    assert writes, "Expected a workflow save request."
    return writes[-1]


def test_create_workflow_with_reorder_bindings_references_and_schema_validation(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows")
    expect(page.get_by_role("heading", name="Workflows", exact=True)).to_be_visible()
    ui.assert_no_overflow()

    page.get_by_role("button", name="Create workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_be_visible()
    expect(labelled(page, "Workflow name")).to_be_visible()
    expect(page.get_by_text("The default model is not valid here", exact=False)).to_be_visible()
    labelled(page, "Workflow name").fill("V2 evidence workflow")
    labelled(page, "Description").first.fill("Created in the V2 LIST editor.")
    labelled(page, "Runner type").select_option("agent")
    labelled(page, "Agent").select_option(label="Workspace reviewer")
    labelled(page, "Trigger").select_option("interval")
    labelled(page, "Interval value").fill("45")
    labelled(page, "Interval unit").select_option("minutes")
    page.get_by_role("button", name="Add task", exact=True).click()
    page.get_by_role("button", name="Add task", exact=True).click()

    labelled(page, "Task name").nth(0).fill("Collect records")
    labelled(page, "Instructions").nth(0).fill("Collect the approved records.")
    labelled(page, "Task name").nth(1).fill("Intermediate note")
    labelled(page, "Instructions").nth(1).fill("Write a short interim note.")
    labelled(page, "Task name").nth(2).fill("Final synthesis")
    labelled(page, "Instructions").nth(2).fill("Synthesize the first task without relying on the adjacent note.")

    page.get_by_role("button", name=re.compile(r"Move Final synthesis up")).click()
    page.get_by_role("button", name=re.compile(r"Move Final synthesis down")).click()
    page.get_by_role("list", name="Available documents").get_by_text("Private brief").click()
    page.get_by_role("listitem").filter(has_text="Private brief").get_by_role("button", name="Add").click()
    page.get_by_label("Reference alias for personal-brief", exact=True).fill("9 invalid alias")
    expect(page.get_by_label("Reference alias for personal-brief", exact=True)).to_have_value("invalid_alias")
    labelled(page, "Source").select_option(label="Public: Published handbook")
    expect(page.get_by_role("list", name="Available documents").get_by_text("Published policy")).to_be_visible()
    page.get_by_role("listitem").filter(has_text="Published policy").get_by_role("button", name="Add").click()

    open_task_details(page, 2)
    labelled(page, "Task runner").nth(2).select_option("agent")
    labelled(page, "Task agent").select_option(label="Provided reviewer · Provided")
    labelled(page, "Document action").nth(2).select_option("analyze")
    page.get_by_role("list", name="Available evidence for Final synthesis").get_by_text("Private brief").click()
    page.get_by_role("list", name="Available evidence for Final synthesis").locator("li").filter(has_text="Private brief").get_by_role("button", name="Add").click()
    page.get_by_label("Output contract for Final synthesis", exact=True).select_option("json")
    expect(page.get_by_text("Stable alias: start with a letter", exact=False)).to_have_count(0)
    page.get_by_label("Previous-task inputs for Final synthesis", exact=True).select_option("custom")
    page.get_by_label("Bind Collect records to Final synthesis", exact=True).check()
    expect(page.get_by_text("Stable alias: start with a letter", exact=False)).to_be_visible()
    labelled(page, "Input alias").fill("records from the first task")
    page.get_by_text("Optional JSON schema", exact=True).click()
    labelled(page, "Optional JSON schema").fill("{")
    expect(page.get_by_role("alert").filter(has_text="JSON schema must be valid JSON.").first).to_be_visible()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="JSON schema must be valid JSON.").first).to_be_visible()
    assert not ui.workflow_writes

    labelled(page, "Optional JSON schema").fill('{"type":"object","pattern":"nope"}')
    expect(page.get_by_role("alert").filter(has_text="unsupported keyword pattern").first).to_be_visible()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    assert not ui.workflow_writes

    labelled(page, "Optional JSON schema").fill('{"type":"object","properties":{"answer":{"type":"string"}}}')
    expect(page.get_by_role("alert").filter(has_text="JSON schema must be valid JSON.")).to_have_count(0)
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_have_count(0)

    write = workflow_post(ui)
    body = write.body
    assert write.path == "/api/user/workflows"
    assert body["definition_version"] == 2
    assert body["runner_type"] == "agent"
    assert body["selected_agent"] == {
        "id": "00000000-0000-4000-8000-000000000001",
        "name": "workspace-reviewer",
        "display_name": "Workspace reviewer",
        "is_global": False,
        "is_group": False,
    }
    assert body["trigger_type"] == "interval"
    assert body["schedule"] == {"unit": "minutes", "value": 45}
    assert body["reference_inputs"][0]["document_id"] == "personal-brief"
    assert body["reference_inputs"][0]["name"] == "invalid_alias"
    assert body["reference_inputs"][0]["scope_id"] == OWNER_ID
    assert body["reference_inputs"][1]["document_id"] == "public-policy"
    assert body["reference_inputs"][1]["scope_id"] == "public-handbook"
    assert body["tasks"][2]["inputs"][0]["task_id"] == body["tasks"][0]["id"]
    assert body["tasks"][2]["inputs"][0]["name"] == "records_from_the_first_task"
    assert body["tasks"][2]["runner"]["selected_agent"] == {
        "id": "00000000-0000-4000-8000-000000000003",
        "name": "provided-reviewer",
        "display_name": "Provided reviewer",
        "is_global": True,
        "is_group": False,
    }
    assert body["tasks"][2]["document_action"] == {
        "type": "analyze",
        "doc_scope": "personal",
        "active_group_ids": [],
        "active_public_workspace_id": [],
        "document_ids": ["personal-brief"],
        "target_mode": "selected",
        "analysis_mode": "combined",
    }
    assert body["tasks"][2]["output_contract"]["allow_partial"] is False
    assert body["tasks"][2]["output_contract"]["schema"]["properties"]["answer"]["type"] == "string"


def test_edit_preserves_legacy_fields_and_run_inspection_surfaces_validation(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows")

    ui.fail_next_workflow_run()
    page.get_by_role("button", name=re.compile(r"Run Quarterly review workflow")).click()
    expect(page.get_by_role("alert").filter(has_text="Workflow run completed with failed tasks.")).to_be_visible()
    expect(page.get_by_text("completed_partial", exact=True)).to_be_visible()

    page.get_by_role("button", name="Show run task results", exact=True).click()
    expect(page.get_by_text("completed_partial", exact=True)).to_be_visible()
    expect(page.get_by_text("accepted_partial", exact=False)).to_be_visible()
    expect(page.get_by_text("partial_coverage", exact=False)).to_be_visible()
    expect(page.get_by_text("Context budget:", exact=False).first).to_be_visible()
    expect(page.get_by_text("Consumed inputs:", exact=False)).to_be_visible()
    expect(page.get_by_text("Skipped document attachment", exact=False)).to_have_count(0)
    page.get_by_role("button", name="Load result excerpt", exact=True).first.click()
    expect(page.get_by_text("First transport excerpt page", exact=False)).to_be_visible()
    expect(page.get_by_text("Output authoritative · offset 0", exact=False)).to_be_visible()
    page.get_by_role("button", name="Next result page", exact=True).click()
    expect(page.get_by_text("Second transport excerpt page", exact=False)).to_be_visible()
    expect(page.get_by_text("offset 2000", exact=False)).to_be_visible()

    page.get_by_role("button", name=re.compile(r"Edit Quarterly review workflow")).click()
    expect(page.get_by_text("Preserved settings", exact=True)).to_be_visible()
    expect(page.get_by_text("file sync settings", exact=False)).to_be_visible()
    labelled(page, "Description").first.fill("Edited without losing legacy settings.")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)

    body = workflow_post(ui).body
    assert body["id"] == WORKFLOW_ID
    assert body["definition_revision"] == "revision:workflow-v2-review:1"
    assert body["file_sync"] == {"source_id": "legacy-source", "delete_policy": "preserve"}
    assert body["alert_settings"] == {"owner_on_failure": True}
    assert body["publication_options"] == {"publish_to_public_workspace": False}
    assert body["metadata"] == {"legacy": {"kept": True}}
    assert "output_contract" not in body["tasks"][1]


def test_unsupported_version_is_read_only_and_409_retains_draft(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows")

    page.get_by_role("button", name=re.compile(r"Edit Future workflow")).click()
    expect(page.get_by_role("alert").filter(has_text="definition version 4")).to_be_visible()
    expect(page.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    page.get_by_role("dialog", name="Edit workflow", exact=True).get_by_role(
        "button", name="Close", exact=True
    ).last.click()
    assert not ui.workflow_writes

    expect(page.get_by_role("button", name=re.compile(r"Active running workflow is running"))).to_be_disabled()

    page.get_by_role("button", name=re.compile(r"Edit Quarterly review workflow")).click()
    labelled(page, "Workflow name").fill("Retained stale draft")
    ui.mutate_revision(WORKFLOW_ID)
    with page.expect_response(
        lambda response: response.status == 409 and urlsplit(response.url).path == "/api/user/workflows"
    ):
        page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="draft has been retained")).to_be_visible()
    expect(labelled(page, "Workflow name")).to_have_value("Retained stale draft")


def test_existing_agent_and_legacy_prompt_workflows_preserve_backend_shapes(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows")

    page.get_by_role("button", name=re.compile(r"Edit Agent review workflow")).click()
    expect(labelled(page, "Agent")).to_have_value(
        '["00000000-0000-4000-8000-000000000001",false,false,""]'
    )
    open_task_details(page, 0)
    expect(labelled(page, "Task agent")).to_have_value(
        '["00000000-0000-4000-8000-000000000003",true,false,""]'
    )
    labelled(page, "Description").first.fill("Agent references are preserved.")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    body = workflow_post(ui).body
    assert body["id"] == "agent-workflow"
    assert body["selected_agent"]["id"] == "00000000-0000-4000-8000-000000000001"
    assert body["tasks"][0]["runner"]["selected_agent"]["id"] == "00000000-0000-4000-8000-000000000003"
    assert "output_contract" not in body["tasks"][0]

    page.get_by_role("button", name=re.compile(r"Edit Legacy prompt workflow")).click()
    expect(labelled(page, "Instructions").first).to_have_value("Use the legacy single prompt.")
    open_task_details(page, 0)
    expect(labelled(page, "Document action").first).to_have_value("analyze")
    labelled(page, "Description").first.fill("Legacy single prompt metadata edit.")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    legacy_body = workflow_post(ui).body
    assert legacy_body["id"] == "legacy-prompt-workflow"
    assert legacy_body["tasks"][0]["instructions"] == "Use the legacy single prompt."
    assert legacy_body["tasks"][0]["document_action"] == {"type": "analyze", "document_ids": ["personal-brief"]}
    assert "output_contract" not in legacy_body["tasks"][0]

    page.get_by_role("button", name=re.compile(r"Edit Legacy prompt workflow")).click()
    open_task_details(page, 0)
    labelled(page, "Document action").first.select_option("none")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    disabled_body = workflow_post(ui).body
    assert disabled_body["id"] == "legacy-prompt-workflow"
    assert disabled_body["tasks"][0]["document_action"] == {"type": "none"}


def test_document_action_comparison_posts_real_payload(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows")
    page.get_by_role("button", name="Create workflow", exact=True).click()
    labelled(page, "Workflow name").fill("Comparison workflow")
    labelled(page, "Model").select_option(label="Workspace GPT · aoai")
    labelled(page, "Instructions").first.fill("Compare the selected source and target.")
    open_task_details(page, 0)
    labelled(page, "Document action").select_option("comparison")
    page.get_by_role("list", name="Available evidence for Task 1").locator("li").filter(has_text="Private brief").get_by_role("button", name="Add").click()
    expect(page.get_by_role("list", name="Selected evidence for Task 1").get_by_text("Private_brief")).to_be_visible()
    page.get_by_role("list", name="Available evidence for Task 1").locator("li").filter(has_text="Second brief").get_by_role("button", name="Add").click()
    expect(page.get_by_role("list", name="Selected evidence for Task 1").get_by_text("Second_brief")).to_be_visible()
    labelled(page, "Comparison source").select_option("personal-brief")
    expect(page.get_by_role("checkbox", name="Second_brief", exact=True)).to_be_checked()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    body = workflow_post(ui).body
    action = body["tasks"][0]["document_action"]
    assert action["type"] == "comparison"
    assert action["doc_scope"] == "personal"
    assert action["document_ids"] == ["personal-brief", "personal-second"]
    assert action["active_public_workspace_id"] == []
    assert action["left_document_id"] == "personal-brief"
    assert action["right_document_ids"] == ["personal-second"]


def test_initial_workflow_id_opens_once_and_close_stays_closed(workflow_ui):
    _ui, page = workflow_ui, workflow_ui.page
    workflow_ui.open(f"/workspace/workflows?workflow_id={WORKFLOW_ID}")
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_be_visible()
    page.get_by_role("dialog", name="Edit workflow", exact=True).get_by_role(
        "button", name="Cancel", exact=True
    ).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    page.get_by_role("button", name=re.compile(r"Show run history")).first.click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)


def test_pristine_create_cancels_without_invented_dirty_state(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows")
    page.get_by_role("button", name="Create workflow", exact=True).click()
    page.get_by_role("dialog", name="Create workflow", exact=True).get_by_role("button", name="Cancel", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert not ui.workflow_writes


def test_group_workflows_carry_group_id_and_dirty_guard_blocks_switching(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/groups")
    ui.select_group(GROUP_ID)
    expect(page.get_by_role("heading", name="Workflows", exact=True)).to_be_visible()
    page.get_by_role("button", name="Create workflow", exact=True).click()
    labelled(page, "Workflow name").fill("Group workflow from V2")
    labelled(page, "Model").select_option(label="Workspace GPT · aoai")
    expect(page.get_by_label("Group workspace", exact=True)).to_be_disabled()
    expect(page.get_by_role("status").filter(has_text="group changes")).to_be_visible()

    expect(page.get_by_role("list", name="Available documents").get_by_text("Group brief")).to_be_visible()
    page.get_by_role("listitem").filter(has_text="Group brief").get_by_role("button", name="Add").click()
    labelled(page, "Instructions").first.fill("Review only the selected group evidence.")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_have_count(0)

    group_requests = [
        request for request in ui.requests
        if request.path.startswith("/api/group/workflows")
    ]
    assert group_requests
    assert all(request.query.get("group_id") == [GROUP_ID] for request in group_requests)
    body = workflow_post(ui).body
    assert body["group_id"] == GROUP_ID
    assert body["reference_inputs"][0]["document_id"] == "group-brief"
    assert body["reference_inputs"][0]["name"] == "Group_brief"
