# test_v2_public_chat_scope.py
"""
Workspace-sidebar and public-only migration browser regressions.
Version: 0.261.395
Implemented in: 0.261.395

Real Composer/stores run in the shared Azure/local Playwright harness.
Classic aggregate-public authorization remains covered by the functional suite.
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect
from test_v2_orchestration_plan_editor import editor_assets

from ui_tests.test_v2_chat_context_selection import (
    STREAM_PATHS, connect_options, context_page, mount_workflow, open_picker, pick_context,
)


pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def production_picker_styles(context_page, editor_assets):
    page, _ = context_page
    for url, path in editor_assets.items():
        if url.endswith(".css"):
            page.add_style_tag(content=path.read_text(encoding="utf-8"))
    page.evaluate("""() => {
        document.getElementById('mount-a').className = 'flex h-dvh flex-col justify-end p-4';
    }""")


def send(page, message, dispatch="chat"):
    page.get_by_role("textbox", name="Message", exact=True).fill(message)
    with page.expect_request(lambda request: request.method == "POST"
                             and request.url.endswith(STREAM_PATHS[dispatch])) as sent:
        page.get_by_role("button", name="Send message", exact=True).click()
    page.wait_for_function("() => !window.OrchHarness.stores.chat.useChatStore.getState().streaming")
    return sent.value.post_data_json


@pytest.mark.parametrize("dispatch", ["chat", "plan"])
def test_search_all_is_explicit_and_not_tied_to_active_workspace(context_page, dispatch):
    page, _ = context_page
    mount_workflow(page, orchestration=dispatch == "plan")
    open_picker(page)
    all_button = page.get_by_role("button", name="Search all documents", exact=True)
    expect(all_button).to_have_attribute("aria-pressed", "false")
    expect(page.get_by_label("Search in", exact=True)).to_have_count(0)
    all_button.click()
    page.get_by_role("button", name="Done", exact=True).click()
    body = send(page, "Find the policy", dispatch)
    assert body["document_source_selection"] == {"version": 1, "mode": "all", "sources": []}
    assert "public_workspace_selection" not in body and "active_group_ids" not in body


@pytest.mark.parametrize("dispatch", ["chat", "plan"])
def test_public_only_launch_becomes_selected_public_workspaces(context_page, dispatch):
    page, _ = context_page
    mount_workflow(page, orchestration=dispatch == "plan")
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().setPublicWorkspaceSelection('all')")
    expect(page.get_by_role("button", name="Remove Handbook", exact=True)).to_be_visible()
    body = send(page, "Find public policy", dispatch)
    assert body["document_source_selection"] == {
        "version": 1, "mode": "selected",
        "sources": [{"kind": "workspace", "scope": {"kind": "public", "id": "public-1"}}],
    }
    assert "public_workspace_selection" not in body


def test_new_chat_does_not_inherit_all_document_search(context_page):
    page, _ = context_page
    mount_workflow(page)
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.setState({activeConversationId: 'conv-01'})")
    open_picker(page)
    page.get_by_role("button", name="Search all documents", exact=True).click()
    page.get_by_role("button", name="Done", exact=True).click()
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.setState({activeConversationId: null, messages: []})")
    open_picker(page)
    expect(page.get_by_role("button", name="Search all documents", exact=True)).to_have_attribute("aria-pressed", "false")
    page.get_by_role("button", name="Done", exact=True).click()
    body = send(page, "Start without document search")
    assert "document_source_selection" not in body
    assert body["hybrid_search"] is False


def test_workspace_sidebar_and_documents_filter_together(context_page):
    page, _ = context_page
    mount_workflow(page)
    open_picker(page)
    search = page.get_by_role("searchbox", name="Search documents", exact=True)
    search.fill("policy")
    directory = page.get_by_role("navigation", name="Workspaces")
    expect(directory.get_by_role("button", name=re.compile("^Handbook"))).to_be_visible()
    expect(directory.get_by_role("button", name=re.compile("^Marketing"))).to_have_count(0)
    expect(directory.get_by_role("button", name=re.compile("^My workspace"))).to_have_count(0)
    expect(page.get_by_role("button", name=re.compile("^Travel policy"))).to_be_visible()
    search.fill("Marketing")
    expect(directory.get_by_role("button", name=re.compile("^Marketing"))).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("^Campaign outline"))).to_be_visible()
    search.fill("no-match-anywhere")
    expect(page.get_by_text("No matching workspaces or documents. Try a different name or tag.")).to_be_visible()
    search.fill("")
    expect(directory.get_by_role("button", name=re.compile("^My workspace"))).to_be_visible()


def test_search_from_a_workspace_resets_browsing_without_discarding_selection(context_page):
    page, _ = context_page
    mount_workflow(page)
    pick_context(page, "Quarterly brief")
    open_picker(page)
    page.get_by_role("navigation", name="Workspaces").get_by_role("button", name=re.compile("^Marketing")).click()
    expect(page.get_by_role("button", name=re.compile("^Campaign outline"))).to_be_visible()
    page.get_by_role("searchbox", name="Search documents", exact=True).fill("policy")
    expect(page.get_by_role("button", name=re.compile("^Travel policy"))).to_be_visible()
    expect(page.get_by_text("1 sources selected", exact=True)).to_be_visible()
    page.get_by_role("button", name="Done", exact=True).click()
    body = send(page, "Use only my selected source")
    assert body["document_source_selection"]["sources"] == [
        {"kind": "document", "id": "personal-brief", "scope": {"kind": "personal"}},
    ]


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width,height", [(1280, 900), (390, 844)])
def test_sidebar_layout_and_mobile_collapse(context_page, theme, width, height):
    page, _ = context_page
    page.set_viewport_size({"width": width, "height": height})
    mount_workflow(page)
    page.evaluate("(dark) => document.documentElement.classList.toggle('dark', dark)", theme == "dark")
    open_picker(page)
    picker = page.locator("[data-context-picker]")
    expect(page.get_by_role("button", name=re.compile("^Travel policy"))).to_be_visible()
    bounds = picker.bounding_box()
    assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
    assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= height
    if width < 768:
        toggle = page.get_by_role("navigation", name="Workspaces").get_by_role("button", name="All workspaces", exact=True)
        expect(toggle).to_have_attribute("aria-expanded", "false")
        toggle.click()
        expect(toggle).to_have_attribute("aria-expanded", "true")
    artifacts = Path(__file__).resolve().parent / "artifacts" / "document-scope"
    artifacts.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(artifacts / f"sidebar-{theme}-{width}.png"))


@pytest.mark.parametrize("restriction", ["shared", "restricted", "referenceUploadsOnly", "not-opted-in"])
def test_unrelated_editors_keep_the_existing_picker(context_page, restriction):
    page, _ = context_page
    mount_workflow(page)
    page.evaluate("""restriction => {
        const H = window.OrchHarness;
        H.unmount('mount-a');
        const props = {
            id: 'isolated-editor', label: 'Answer', conversationId: null,
            draft: {text: '', contextItems: [], attachedPrompt: null, promptValues: {}, uploads: [], imageReferences: []},
            onChange: () => {}, pickerOpen: true, allowContext: true,
            documentScopeControl: {id: 'isolated-scope', publicEnabled: true, disabled: false, onChange: () => {}},
        };
        if (restriction === 'not-opted-in') delete props.documentScopeControl;
        else props[restriction] = true;
        H.mount('mount-a', 'ComposerEditor', props);
    }""", restriction)
    expect(page.locator("[data-context-picker]")).to_be_visible()
    expect(page.get_by_role("region", name="Document sources")).to_have_count(0)


def test_disabled_picker_cannot_change_search_mode(context_page):
    page, _ = context_page
    mount_workflow(page)
    open_picker(page)
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.setState({streaming: true})")
    expect(page.get_by_role("button", name="Search all documents", exact=True)).to_be_disabled()
