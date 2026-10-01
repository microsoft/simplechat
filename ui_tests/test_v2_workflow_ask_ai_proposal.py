# test_v2_workflow_ask_ai_proposal.py
"""
Real-component browser test for Ask AI on a workflow proposal's draft (Phase 3c).
Version: 0.261.211
Implemented in: 0.261.211
Refs: microsoft/simplechat#1548

Phase 4's proposal card opens the workflow editor on the proposal's draft through Edit. Ask AI
works there too: the draft has no saved workflow behind it, so a turn sends `base: null` and a
draft without an `id`, and a Save with an AI change in it opens Review before saving first, then
accepts the proposal through the card and never through the workflow save route.

Reuses the proposal card harness (the production MessageList, WorkflowProposalCards and
WorkflowEditorDialog in Chromium with the production CSS). `POST /api/user/workflows/assist` is
answered in the page by 3b's real pipeline with a scripted model (`fixtures/workflow_ask_ai.py`),
so no live model or Azure service is contacted.

Build CSS with the existing V2 build, keeping outputs in UI test artifacts:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run with PLAYWRIGHT_SERVICE_URL='' and PYTHONPATH including application/single_app,
functional_tests and ui_tests/fixtures.
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

# The shared fixtures import pure application helpers after setting their paths.
from test_v2_orchestration_workflow_proposal_card import (  # noqa: E402,F401
    CONVERSATION,
    HOSTILE_INSTRUCTIONS,
    NAME,
    card,
    card_ui,
    connect_options,
    editor_assets,
    editor_browser,
    editor_options,
    mount,
    open_editor,
)
from ui_tests.fixtures.workflow_ask_ai import ASSIST_ROUTE, AssistStub  # noqa: E402
from ui_tests.test_v2_workflow_change_tracking import (  # noqa: E402
    RUN_AS_NOTE,
    author,
    changed,
    changes_toggle,
    open_panel,
    side_panel,
)


pytestmark = pytest.mark.ui
DESCRIBED = "Reviews the week's email and flags anything urgent."


@pytest.fixture
def ask_card_ui(card_ui):
    page, api = card_ui

    def record_error(url, status):
        api.expected_errors.add((urlsplit(url).path, status))

    # A proposal draft has no saved workflow to read, and these tests send no # references.
    stub = AssistStub(
        user_id="proposal-tester", record_error=record_error, options=editor_options, read_base=None, resolve=None,
    )
    # Registered after the harness's catch-all route, so it answers the assist route first.
    page.route(ASSIST_ROUTE, stub.handle)
    try:
        yield page, api, stub
        stub.assert_clean()
    finally:
        stub.release()


def enable_ask_ai(page):
    """The bootstrap's per-user flag, as the server sends it when Ask AI is available to this user."""
    page.evaluate("""() => {
        const store = window.OrchHarness.stores.bootstrap.useBootstrapStore;
        const data = store.getState().data;
        store.setState({ data: { ...data, features: { ...data.features, enable_workflow_ai_assistant: true } } });
    }""")


def description_field(dialog):
    return dialog.locator("section[aria-label='Workflow basics']").get_by_label("Description", exact=True)


def test_a_proposal_draft_sends_no_base_and_saves_through_review(ask_card_ui):
    page, api, stub = ask_card_ui
    stub.queue(stub.changed({"op": "set_description", "description": DESCRIBED}, text="Updated the description."))
    mount(page, api)
    enable_ask_ai(page)
    dialog, _ = open_editor(page, card(page))

    toggle = dialog.get_by_role("button", name="Ask AI", exact=True)
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    panel = side_panel(dialog)
    expect(panel.get_by_role("tab", name="Ask AI", exact=True)).to_have_attribute("aria-selected", "true")
    box = panel.get_by_role("textbox", name="Message Ask AI", exact=True)
    expect(box).to_be_focused()
    box.fill("Say that it flags anything urgent.")
    box.press("Enter")
    body = stub.wait_for_requests(page, 1)

    # A proposal draft is a new draft: no base, and no id in the draft.
    assert body["base"] is None
    assert "id" not in body["draft"]
    assert body["draft"]["name"] == NAME
    assert body["draft"]["tasks"][0]["instructions"] == HOSTILE_INSTRUCTIONS
    assert (body["conversation"], body["focus"], body["references"]) == ([], None, [])

    found = panel.locator(f"[data-workflow-assist-card='{body['submission_id']}']")
    expect(found).to_have_attribute("data-state", "applied")
    expect(found.locator("[data-workflow-assist-reply]")).to_have_text("Updated the description.")
    expect(description_field(dialog)).to_have_value(DESCRIBED)
    expect(author(changed(dialog, "description"))).to_have_text("AI assist")
    expect(changes_toggle(dialog)).to_have_accessible_name("Changes (1 unsaved)")

    # The first Save reviews the AI change; only Confirm and save accepts the proposal.
    dialog.get_by_role("button", name="Save workflow", exact=True).click()
    expect(panel.get_by_role("tab", name="Changes", exact=True)).to_have_attribute("aria-selected", "true")
    review = panel.get_by_role("region", name="Review before saving", exact=True)
    expect(review.get_by_role("heading", name="Review before saving", exact=True)).to_be_focused()
    expect(review.locator("li").filter(has_text=RUN_AS_NOTE)).to_have_count(0)
    assert not api.writes(), "Save accepted the proposal before Confirm and save."
    review.get_by_role("button", name="Confirm and save", exact=True).click()
    expect(dialog).to_have_count(0)

    bodies = [call["body"] for call in api.writes()]
    assert len(bodies) == 1, bodies
    assert set(bodies[0]) == {"conversation_id", "workflow"}, sorted(bodies[0])
    assert bodies[0]["conversation_id"] == CONVERSATION
    workflow = bodies[0]["workflow"]
    assert workflow["description"] == DESCRIBED
    assert "id" not in workflow
    assert not [call for call in api.requests if call["path"].startswith("/api/user/workflows")
                and call["method"] == "POST"], "The editor saved a workflow directly."
    expect(card(page).get_by_role("status")).to_have_text("Created, paused")


def test_ask_ai_is_hidden_in_a_proposal_draft_when_the_assistant_is_off(ask_card_ui):
    page, api, stub = ask_card_ui
    mount(page, api)
    dialog, _ = open_editor(page, card(page))

    # An empty task would offer Draft with AI if Ask AI were available.
    instructions = dialog.get_by_label("Instructions", exact=True).first
    instructions.fill("")
    expect(instructions).to_have_value("")
    panel = open_panel(dialog)
    expect(panel.get_by_role("tab")).to_have_count(1)
    expect(panel.locator("[data-workflow-ask-ai]")).to_have_count(0)
    expect(dialog.get_by_role("button", name="Ask AI", exact=True)).to_have_count(0)
    expect(dialog.locator("[data-workflow-ask-ai-task]")).to_have_count(0)
    expect(dialog.locator("[data-workflow-draft-ai]")).to_have_count(0)
    expect(dialog.get_by_role("button", name=re.compile(r"^(Ask AI|Draft with AI)"))).to_have_count(0)
    assert not stub.bodies
