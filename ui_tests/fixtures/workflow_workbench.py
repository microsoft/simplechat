# workflow_workbench.py
"""
Shared navigation for the V2 Workflows workbench and its routed editor.
Version: 0.261.266
Implemented in: 0.261.266

The Workflows section is a workbench, drawn the way Admin's Model Catalog is. A list of workflows
(`list "Workflows"`, one button per workflow, named by the workflow) sits beside the selected
workflow's detail: an `article` named by the workflow, with its Run, Cancel, Edit (or View) and
Delete actions and the tabs Overview, Runs and, for a structured (definition 3) workflow, Flow.
The first visible workflow is selected when the section opens. `?workflow_id=<id>` selects a
workflow and shows its Overview; adding `&run_id=<id>` shows its Runs tab with that run expanded.

Editing is a page of its own, not a dialog: `/workspace/workflows/<id>` (or `/new`), and
`/groups/<group>/workflows/<id>` in a group. It is a region named "Edit workflow" or
"Create workflow". Saving returns to the list with the saved workflow selected. Leaving with
unsaved changes asks the workspace leave prompt ("Discard unsaved changes?", with Keep editing and
Discard changes), not the dialog editor's "Discard unsaved workflow changes?". The chat proposal
card still opens the same editor as a dialog.
"""

from urllib.parse import quote

from playwright.sync_api import Page, expect

PERSONAL_WORKFLOWS_PATH = "/workspace/workflows"
EDIT_WORKFLOW = "Edit workflow"
CREATE_WORKFLOW = "Create workflow"
LEAVE_PROMPT = "Discard unsaved changes?"


def workflows_path(group_id=None):
    """The Workflows section of the personal workspace, or of a group."""
    return f"/groups/{quote(group_id, safe='')}/workflows" if group_id else PERSONAL_WORKFLOWS_PATH


def workflow_editor_path(workflow_id=None, group_id=None):
    """The editor page for a workflow, or the page that creates one when no workflow is named."""
    return f"{workflows_path(group_id)}/{quote(workflow_id or 'new', safe='')}"


def workflow_editor(page: Page, name=EDIT_WORKFLOW):
    """The routed editor page: a region named "Edit workflow" or "Create workflow"."""
    return page.get_by_role("region", name=name, exact=True)


def workflow_list(page: Page):
    return page.get_by_role("list", name="Workflows", exact=True)


def workflow_row(page: Page, name):
    """A workflow's row in the list: a button named by the workflow."""
    return workflow_list(page).get_by_role("button", name=name, exact=True)


def workflow_detail(page: Page, name):
    """The detail of the selected workflow: an article named by the workflow."""
    return page.get_by_role("article", name=name, exact=True)


def select_workflow(page: Page, name):
    """Select a workflow in the list and return its detail."""
    row = workflow_row(page, name)
    row.click()
    expect(row).to_have_attribute("aria-pressed", "true")
    detail = workflow_detail(page, name)
    expect(detail).to_be_visible()
    return detail


def open_workflow_tab(page: Page, name, tab):
    """Select a workflow, open one of its detail tabs and return the tab's panel."""
    detail = select_workflow(page, name)
    detail.get_by_role("tab", name=tab, exact=True).click()
    panel = detail.get_by_role("tabpanel", name=tab, exact=True)
    expect(panel).to_be_visible()
    return panel


def open_workflow_runs(page: Page, name):
    """The workflow's Runs tab: its run history, which reads and polls only while shown."""
    return open_workflow_tab(page, name, "Runs")


def open_workflow_flow(page: Page, name):
    """The structured workflow's Flow tab: the saved definition, read-only."""
    return open_workflow_tab(page, name, "Flow")


def leave_workflow_runs(page: Page, name):
    """Return to Overview, which unmounts the run history and stops its polling."""
    detail = workflow_detail(page, name)
    detail.get_by_role("tab", name="Overview", exact=True).click()
    expect(detail.get_by_role("tabpanel", name="Overview", exact=True)).to_be_visible()


def edit_workflow(page: Page, name, *, action="Edit"):
    """Select a workflow, choose Edit (or View) and return the editor page."""
    detail = select_workflow(page, name)
    detail.get_by_role("button", name=f"{action} {name}", exact=True).click()
    editor = workflow_editor(page)
    expect(editor).to_be_visible()
    return editor


def create_workflow(page: Page):
    """Choose Create workflow and return the editor page."""
    page.get_by_role("button", name=CREATE_WORKFLOW, exact=True).click()
    editor = workflow_editor(page, CREATE_WORKFLOW)
    expect(editor).to_be_visible()
    return editor


def leave_prompt(page: Page):
    """The workspace prompt that asks before unsaved editor changes are left behind."""
    return page.get_by_role("dialog", name=LEAVE_PROMPT, exact=True)


def discard_and_leave(page: Page):
    """Answer the leave prompt with Discard changes."""
    prompt = leave_prompt(page)
    expect(prompt).to_be_visible()
    prompt.get_by_role("button", name="Discard changes", exact=True).click()
    expect(prompt).to_have_count(0)
