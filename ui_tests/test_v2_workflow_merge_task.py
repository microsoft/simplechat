# test_v2_workflow_merge_task.py
"""
UI test for the V2 workflow editor Merge files document action.
Version: 0.261.223
Implemented in: 0.261.220; PDF merge authoring added in 0.261.221; Word in 0.261.222; PowerPoint in 0.261.223

This test ensures the workflow editor can author a merge task, keep the user's selected file
order after reordering, and save the backend document_action shape, and that it doesn't offer
Merge files while the server's editor options say an administrator turned Merge off.
"""

import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "functional_tests"))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402
from ui_tests.fixtures.workflow_editor import workflow_ui  # noqa: F401, E402


pytestmark = pytest.mark.ui


def labelled(page, name):
    return page.get_by_label(re.compile(rf"^{re.escape(name)}(?:\s*\*)?\s*$"))


def open_task_details(page, index):
    page.get_by_text("Runner, inputs, references and outputs", exact=True).nth(index).click()


def workflow_post(ui):
    writes = [
        request for request in ui.workflow_writes
        if request.method == "POST" and request.path in {"/api/user/workflows", "/api/group/workflows"}
    ]
    assert writes, "Expected a workflow save request."
    return writes[-1]


def test_v2_workflow_merge_task_selected_files_reorder(workflow_ui):
    assert_app_version_at_least("0.261.220")
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows")

    page.get_by_role("button", name="Create workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_be_visible()
    labelled(page, "Workflow name").fill("Merge files workflow")
    labelled(page, "Description").first.fill("Combines selected files in order.")
    labelled(page, "Runner type").select_option("agent")
    labelled(page, "Agent").select_option(label="Workspace reviewer")
    labelled(page, "Task name").fill("Merge monthly files")
    labelled(page, "Instructions").fill("Merge the selected files without changing their order.")

    open_task_details(page, 0)
    labelled(page, "Document action").select_option("merge")
    expect(labelled(page, "Merge type")).to_have_value("tabular")
    expect(page.get_by_text("Inputs: .csv, .xlsx, .xlsm, .xls", exact=True)).to_be_visible()

    available = page.get_by_role("list", name="Available merge files for Merge monthly files")
    available.locator("li").filter(has_text="Private brief").get_by_role("button", name="Add").click()
    available.locator("li").filter(has_text="Second brief").get_by_role("button", name="Add").click()
    page.get_by_role("button", name="Move Second_brief up in merge order").click()
    labelled(page, "Merge output format").select_option("xlsx")
    labelled(page, "Merge output file name").fill("monthly_combined")

    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_have_count(0)

    action = workflow_post(ui).body["tasks"][0]["document_action"]
    assert action == {
        "type": "merge",
        "merge_kind": "tabular",
        "target_mode": "selected",
        "doc_scope": "personal",
        "active_group_ids": [],
        "active_public_workspace_id": [],
        "document_ids": ["personal-second", "personal-brief"],
        "output_format": "xlsx",
        "output_file_name": "monthly_combined",
    }


def test_v2_workflow_merge_task_is_not_offered_while_merge_is_off(workflow_ui):
    # The server's editor options say an administrator turned Merge off; a save would be refused.
    ui, page = workflow_ui, workflow_ui.page
    ui.editor_option_overrides = {"document_actions": {"merge": {"enabled": False, "workflow_max_documents": 100}}}
    ui.open("/workspace/workflows")

    page.get_by_role("button", name="Create workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_be_visible()
    labelled(page, "Task name").fill("Merge monthly files")
    open_task_details(page, 0)
    action = labelled(page, "Document action")
    expect(action.locator("option", has_text="Compare source and target documents")).to_have_count(1)
    expect(action.locator("option", has_text="Merge files")).to_have_count(0)
    assert not [request for request in ui.workflow_writes if request.method == "POST"]


def test_v2_workflow_merge_task_assembles_pdfs_without_bookmarks(workflow_ui):
    assert_app_version_at_least("0.261.221")
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows")

    page.get_by_role("button", name="Create workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_be_visible()
    labelled(page, "Workflow name").fill("Board pack")
    labelled(page, "Description").first.fill("Joins the briefs into one PDF.")
    labelled(page, "Runner type").select_option("agent")
    labelled(page, "Agent").select_option(label="Workspace reviewer")
    labelled(page, "Task name").fill("Join the briefs")
    labelled(page, "Instructions").fill("Join the briefs into one PDF.")

    open_task_details(page, 0)
    labelled(page, "Document action").select_option("merge")
    labelled(page, "Merge type").select_option("pdf")
    expect(page.get_by_text("Inputs: .pdf", exact=True)).to_be_visible()
    expect(page.get_by_text("Output format: PDF", exact=False)).to_be_visible()
    available = page.get_by_role("list", name="Available merge files for Join the briefs")
    available.locator("li").filter(has_text="Private brief").get_by_role("button", name="Add").click()
    available.locator("li").filter(has_text="Second brief").get_by_role("button", name="Add").click()
    page.get_by_text("More merge options", exact=True).click()
    page.get_by_role("checkbox", name=re.compile("^Add bookmarks")).uncheck(force=True)

    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_have_count(0)
    action = workflow_post(ui).body["tasks"][0]["document_action"]
    assert (action["type"], action["merge_kind"], action["output_format"]) == ("merge", "pdf", "pdf")
    assert action["document_ids"] == ["personal-brief", "personal-second"]
    assert action["merge_options"] == {"bookmarks": False}


def test_v2_workflow_merge_task_appends_word_documents_with_their_options(workflow_ui):
    assert_app_version_at_least("0.261.222")
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows")

    page.get_by_role("button", name="Create workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_be_visible()
    labelled(page, "Workflow name").fill("Minutes book")
    labelled(page, "Description").first.fill("Appends the meeting minutes into one Word document.")
    labelled(page, "Runner type").select_option("agent")
    labelled(page, "Agent").select_option(label="Workspace reviewer")
    labelled(page, "Task name").fill("Append the minutes")
    labelled(page, "Instructions").fill("Append the minutes, in order, into one Word document.")

    open_task_details(page, 0)
    labelled(page, "Document action").select_option("merge")
    merge_type = labelled(page, "Merge type")
    expect(merge_type.locator("option", has_text="Combine Word documents")).to_have_count(1)
    expect(merge_type.locator("option", has_text="not enabled")).to_have_count(0)
    merge_type.select_option("docx")
    expect(page.get_by_text("Inputs: .docx", exact=True)).to_be_visible()
    expect(page.get_by_text("Output format: DOCX", exact=False)).to_be_visible()
    available = page.get_by_role("list", name="Available merge files for Append the minutes")
    available.locator("li").filter(has_text="Second brief").get_by_role("button", name="Add").click()
    available.locator("li").filter(has_text="Private brief").get_by_role("button", name="Add").click()
    page.get_by_text("More merge options", exact=True).click()
    labelled(page, "Word formatting").select_option("use_first")
    page.get_by_role("checkbox", name=re.compile("^Page break between documents")).uncheck(force=True)
    page.get_by_role("checkbox", name=re.compile("^Add source headings")).check(force=True)

    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_have_count(0)
    action = workflow_post(ui).body["tasks"][0]["document_action"]
    assert (action["type"], action["merge_kind"], action["output_format"]) == ("merge", "docx", "docx")
    assert action["document_ids"] == ["personal-second", "personal-brief"]
    assert action["merge_options"] == {"formatting": "use_first", "page_breaks": False, "source_headings": True}


def test_v2_workflow_merge_task_appends_powerpoint_decks_with_their_options(workflow_ui):
    assert_app_version_at_least("0.261.223")
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows")

    page.get_by_role("button", name="Create workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_be_visible()
    labelled(page, "Workflow name").fill("Quarterly reviews")
    labelled(page, "Description").first.fill("Appends the review decks into one deck.")
    labelled(page, "Runner type").select_option("agent")
    labelled(page, "Agent").select_option(label="Workspace reviewer")
    labelled(page, "Task name").fill("Append the decks")
    labelled(page, "Instructions").fill("Append the review decks, in order, into one deck.")

    open_task_details(page, 0)
    labelled(page, "Document action").select_option("merge")
    labelled(page, "Merge type").select_option("pptx")
    expect(page.get_by_text("Inputs: .pptx", exact=True)).to_be_visible()
    expect(page.get_by_text("Output format: PPTX", exact=False)).to_be_visible()
    available = page.get_by_role("list", name="Available merge files for Append the decks")
    available.locator("li").filter(has_text="Private brief").get_by_role("button", name="Add").click()
    available.locator("li").filter(has_text="Second brief").get_by_role("button", name="Add").click()
    page.get_by_text("More merge options", exact=True).click()
    labelled(page, "PowerPoint formatting").select_option("use_first")
    page.get_by_role("checkbox", name=re.compile("^Create one section per deck")).uncheck(force=True)

    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_have_count(0)
    action = workflow_post(ui).body["tasks"][0]["document_action"]
    assert (action["type"], action["merge_kind"], action["output_format"]) == ("merge", "pptx", "pptx")
    assert action["document_ids"] == ["personal-brief", "personal-second"]
    assert action["merge_options"] == {"formatting": "use_first", "sections": False}
