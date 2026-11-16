# test_v2_workspace_draft_navigation.py
"""Real-router regressions for completed-save history and suspended editor drafts.

Version: 0.261.096
Implemented in: 0.261.096
"""

import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.workspace_authoring import (
    AGENT_ID,
    ORIGIN,
    connect_options,  # noqa: F401
    workspace_ui,  # noqa: F401
)
from ui_tests.test_v2_workspace_authoring import editor_section, save_resource


pytestmark = pytest.mark.ui


def unload_is_protected(page):
    return page.evaluate("""() => {
        const event = new Event('beforeunload', {cancelable: true});
        window.dispatchEvent(event);
        return event.defaultPrevented;
    }""")


@pytest.mark.parametrize("saving", [False, True])
def test_old_save_history_entry_cannot_bypass_a_later_editor_guard(workspace_ui, saving):
    ui, page = workspace_ui, workspace_ui.page
    ui.open(f"/workspace/agents/{AGENT_ID}")
    page.get_by_role("textbox", name="Description", exact=True).fill("Saved first edit")
    assert save_resource(ui, "agent", identifier=AGENT_ID).ok

    page.locator(f'a[href="/v2/workspace/agents/{AGENT_ID}"]').first.click()
    description = page.get_by_role("textbox", name="Description", exact=True)
    expect(description).to_have_value("Saved first edit")
    description.fill("Unsaved subsequent edit")
    if saving:
        ui.defer_next("PATCH", f"/api/user/agents/{AGENT_ID}")
        with page.expect_request(
            lambda request: request.method == "PATCH" and urlsplit(request.url).path == f"/api/user/agents/{AGENT_ID}"
        ):
            page.get_by_role("button", name="Save agent", exact=True).click()

    page.evaluate("history.back()")
    dialog = page.get_by_role(
        "dialog",
        name="Your changes are still being saved" if saving else "Discard unsaved changes?",
        exact=True,
    )
    expect(dialog).to_be_visible()
    expect(page).to_have_url(f"{ORIGIN}/v2/workspace/agents/{AGENT_ID}")
    expect(description).to_have_value("Unsaved subsequent edit")
    if saving:
        expect(dialog.get_by_role("button", name="Discard changes", exact=True)).to_be_disabled()
    dialog.get_by_role("button", name="Keep editing", exact=True).click()
    if saving:
        ui.release_responses()
        expect(page).to_have_url(f"{ORIGIN}/v2/workspace/agents")


def test_suspended_agent_draft_keeps_unload_protection_in_a_clean_action_editor(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.open(f"/workspace/agents/{AGENT_ID}")
    description = page.get_by_role("textbox", name="Description", exact=True)
    description.fill("Keep this unfinished agent")
    assert unload_is_protected(page)
    editor_section(page, "Actions")
    page.get_by_role("button", name="New action", exact=True).click()
    expect(page.get_by_role("combobox", name=re.compile("^Action type"))).to_be_visible()
    expect(page.get_by_role("status").filter(has_text="No unsaved changes")).to_be_visible()
    assert unload_is_protected(page)

    page.evaluate("history.back()")
    expect(description).to_have_value("Keep this unfinished agent")
    assert unload_is_protected(page)
    page.get_by_role("button", name="Cancel", exact=True).click()
    page.get_by_role("dialog", name="Discard unsaved changes?", exact=True).get_by_role(
        "button", name="Discard changes", exact=True
    ).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/workspace/agents")
    assert not unload_is_protected(page)
