# test_v2_public_chat_scope.py
"""
Native aggregate public chat, using the real React composer, stores and router.
Version: 0.261.315
Implemented in: 0.261.310
Scope controls moved into Documents in: 0.261.315

HTTP boundaries reuse the context workflow harness; no Azure or model calls are made.
"""

import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.test_v2_chat_context_selection import (  # noqa: F401
    HANDOFF_CONVERSATION_ID, STREAM_PATHS,
    connect_options, context_page, mount_workflow, open_picker, pick_context,
)
from ui_tests.fixtures.public_documents import chat_list


pytestmark = pytest.mark.ui


def send(page, message, dispatch="chat"):
    page.get_by_role("textbox", name="Message", exact=True).fill(message)
    with page.expect_request(lambda request: request.method == "POST"
                             and request.url.endswith(STREAM_PATHS[dispatch])) as sent:
        page.get_by_role("button", name="Send message", exact=True).click()
    page.wait_for_function("() => !window.OrchHarness.stores.chat.useChatStore.getState().streaming")
    return sent.value.post_data_json


def select_scope(page, mode):
    open_picker(page)
    page.get_by_label("Search in", exact=True).select_option(mode)
    page.get_by_role("button", name="Done", exact=True).click()
    expect(page.get_by_label("Search in", exact=True)).to_have_count(0)


def expect_scope(page, mode):
    open_picker(page)
    expect(page.get_by_label("Search in", exact=True)).to_have_value(mode)
    page.get_by_role("button", name="Done", exact=True).click()


@pytest.mark.parametrize("mode", ["all", "visible"])
@pytest.mark.parametrize("dispatch", ["chat", "plan"])
def test_both_dispatches_are_public_only_despite_stored_active_context(context_page, mode, dispatch):
    page, api = context_page
    mount_workflow(page, orchestration=dispatch == "plan")
    page.evaluate("""() => {
        const store = window.OrchHarness.stores.bootstrap.useBootstrapStore;
        const data = store.getState().data;
        store.setState({data: {...data, scope: {...data.scope,
            active_group_id: 'group-1', active_public_workspace_id: 'stale-public'}}});
    }""")
    select_scope(page, mode)
    body = send(page, "Find public policy", dispatch)
    scope = body if dispatch == "chat" else body["seeds"] if "seeds" in body else body
    assert scope["public_workspace_selection"] == mode
    assert scope["doc_scope"] == "public" and scope["active_group_ids"] == []
    assert scope["active_public_workspace_ids"] == []
    if dispatch == "chat":
        assert body["chat_type"] == "user" and body["hybrid_search"]
    expect_scope(page, mode)


@pytest.mark.parametrize("mode", ["all", "visible"])
def test_picker_and_hash_candidates_are_public_only(context_page, mode):
    page, api = context_page
    queries = []
    hidden = {"id": "hidden-policy", "title": "Hidden policy", "file_name": "hidden.pdf",
              "status": "completed", "public_workspace_id": "hidden-public"}
    visible = {"id": "public-policy", "title": "Travel policy", "file_name": "travel-policy.pdf",
               "status": "completed", "public_workspace_id": "public-1"}
    def public_sources(route):
        query = parse_qs(urlsplit(route.request.url).query)
        queries.append(query)
        if urlsplit(route.request.url).path.endswith("/tags"):
            route.fulfill(json={"tags": [{"name": "public-ready"}]})
        else:
            documents = [visible, hidden] if query.get("public_workspace_selection") == ["all"] else [visible]
            route.fulfill(json=chat_list(documents))
    page.route("**/api/public_workspace_documents?**", public_sources)
    page.route("**/api/public_workspace_documents/tags?**", public_sources)
    mount_workflow(page)
    select_scope(page, mode)
    open_picker(page)
    expect(page.get_by_role("button", name=re.compile("^Travel policy"))).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("^Quarterly brief"))).to_have_count(0)
    expect(page.get_by_role("button", name=re.compile("^Campaign outline"))).to_have_count(0)
    expect(page.get_by_role("button", name="Search all my documents", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name=re.compile("^Hidden policy"))).to_have_count(1 if mode == "all" else 0)
    expect(page.get_by_role("button", name=re.compile("^Handbook"))).to_have_count(0)
    assert queries and all(query.get("public_workspace_selection") == [mode] for query in queries)
    assert not any(path in ("/api/documents", "/api/documents/tags", "/api/group_documents",
                           "/api/group_documents/tags") for method, path in api.requests)
    page.get_by_role("button", name="Done", exact=True).click()
    page.get_by_role("textbox", name="Message", exact=True).fill("#Travel")
    expect(page.get_by_role("listbox", name="Context suggestions")).to_be_visible()
    expect(page.get_by_role("option", name=re.compile("^Travel policy"))).to_be_visible()


def test_non_public_draft_references_block_send_until_context_is_changed(context_page):
    page, api = context_page
    mount_workflow(page)
    pick_context(page, "Quarterly brief")
    select_scope(page, "all")
    page.get_by_role("textbox", name="Message", exact=True).fill("Question")
    page.get_by_role("button", name="Send message", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Clear personal or group references")
    assert not any(method == "POST" for method, path in api.requests)
    page.get_by_label("Search in", exact=True).select_option("")
    page.get_by_role("button", name="Done", exact=True).click()
    body = send(page, "Question")
    assert "public_workspace_selection" not in body
    assert body["selected_document_ids"] == ["personal-brief"]


def test_selected_workspace_is_not_silently_broadened_by_aggregate_mode(context_page):
    page, api = context_page
    mount_workflow(page)
    pick_context(page, "Handbook")
    select_scope(page, "all")
    page.get_by_role("textbox", name="Message", exact=True).fill("Question")
    page.get_by_role("button", name="Send message", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Clear whole-workspace references")
    assert not any(method == "POST" for method, path in api.requests)


def test_store_dispatch_inherits_the_persistent_public_scope(context_page):
    page, api = context_page
    mount_workflow(page)
    select_scope(page, "all")
    with page.expect_request(lambda request: request.method == "POST" and request.url.endswith(STREAM_PATHS["chat"])) as sent:
        page.evaluate("""() => window.OrchHarness.stores.chat.useChatStore.getState().sendMessage(
            'Public follow-up', {documentSearch: false, webSearch: false, imageGeneration: false,
                deepResearch: false, urlAccess: false, contextItems: []})""")
    body = sent.value.post_data_json
    assert body["public_workspace_selection"] == "all"
    assert body["doc_scope"] == "public" and body["hybrid_search"]


def test_scope_change_refreshes_candidates_and_picker_failures_are_explicit(context_page):
    page, api = context_page
    mount_workflow(page)
    select_scope(page, "all")
    open_picker(page)
    expect(page.get_by_role("button", name=re.compile("^Travel policy"))).to_be_visible()
    def refuse(route):
        api.expected_resource_errors.add(("/api/public_workspace_documents", 409))
        route.fulfill(status=409, json={"error": "No public workspaces are available for this scope."})
    page.route("**/api/public_workspace_documents?**", refuse)
    page.get_by_label("Search in", exact=True).select_option("visible")
    expect(page.get_by_role("alert")).to_contain_text("Could not load public search sources")
    expect(page.get_by_role("button", name=re.compile("^Travel policy"))).to_have_count(0)


@pytest.mark.parametrize("strict_mode", [False, True])
def test_scope_only_launch_is_fresh_consumed_once_and_survives_first_id(context_page, strict_mode):
    page, api = context_page
    mount_workflow(page, "/chat?public_workspace_selection=visible", strict_mode=strict_mode, native_chat=True)
    expect(page.get_by_label("Current route")).to_have_text("/chat")
    expect_scope(page, "visible")
    first = send(page, "First public question")
    assert first["conversation_id"] == HANDOFF_CONVERSATION_ID
    followup = send(page, "Follow-up question")
    assert followup["public_workspace_selection"] == "visible"
    assert followup["conversation_id"] == HANDOFF_CONVERSATION_ID
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().startNewConversation()")
    expect_scope(page, "")


def test_switching_and_reload_restore_only_the_latest_user_turn(context_page):
    page, api = context_page
    mount_workflow(page)
    conversations = {
        "aggregate-saved": [
            {"id": "u1", "role": "user", "content": "Public question", "metadata": {
                "workspace_search": {"public_workspace_selection": "all"},
            }},
            {"id": "a1", "role": "assistant", "content": "Answer"},
        ],
        "ordinary-saved": [
            {"id": "u1", "role": "user", "content": "Old public question", "metadata": {
                "workspace_search": {"public_workspace_selection": "visible"},
            }},
            {"id": "u2", "role": "user", "content": "Ordinary question", "metadata": {}},
        ],
    }
    page.route("**/api/get_messages?**", lambda route: route.fulfill(json={
        "messages": conversations["aggregate-saved" if "aggregate-saved" in route.request.url else "ordinary-saved"],
    }))
    page.route("**/api/conversations/*/metadata", lambda route: route.fulfill(json={"context": []}))
    page.route("**/api/conversations/*/kind", lambda route: route.fulfill(json={"kind": "personal"}))
    page.route("**/api/chat/stream/status?**", lambda route: route.fulfill(json={"active": False}))
    page.route("**/api/v2/orchestration/runs?**", lambda route: route.fulfill(json={"runs": []}))
    for identifier, mode in [("aggregate-saved", "all"), ("ordinary-saved", ""), ("aggregate-saved", "all")]:
        page.evaluate("(id) => window.OrchHarness.stores.chat.useChatStore.getState().selectConversation(id)", identifier)
        expect_scope(page, mode)


@pytest.mark.parametrize("orchestration", [False, True])
def test_scope_is_only_in_documents_and_opening_it_preserves_current_context(context_page, orchestration):
    page, api = context_page
    mount_workflow(page, orchestration=orchestration)
    expect(page.get_by_label("Document search scope")).to_have_count(0)
    expect(page.get_by_label("Search in", exact=True)).to_have_count(0)
    open_picker(page)
    expect(page.get_by_label("Search in", exact=True)).to_have_value("")
    expect(page.get_by_role("searchbox", name="Search documents", exact=True)).to_be_focused()
    page.get_by_role("searchbox", name="Search documents", exact=True).press("Escape")
    expect(page.get_by_label("Search in", exact=True)).to_have_count(0)
    expect(page.get_by_role("textbox", name="Message", exact=True)).to_be_focused()
    dispatch = "plan" if orchestration else "chat"
    body = send(page, "Ordinary question", dispatch)
    scope = body.get("seeds", body) if orchestration else body
    assert "public_workspace_selection" not in scope
    assert scope["doc_scope"] == "personal"
    assert scope["active_group_ids"] == [] and scope["active_public_workspace_ids"] == []
    if not orchestration:
        assert not body["hybrid_search"]


def test_disabled_public_workspaces_allow_escape_without_dropping_references(context_page):
    page, api = context_page
    mount_workflow(page)
    pick_context(page, "Travel policy")
    select_scope(page, "visible")
    page.evaluate("""() => {
        const store = window.OrchHarness.stores.bootstrap.useBootstrapStore;
        const data = store.getState().data;
        store.setState({data: {...data, features: {...data.features, enable_public_workspaces: false}}});
    }""")
    page.get_by_role("textbox", name="Message", exact=True).fill("Question")
    page.get_by_role("button", name="Send message", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Public workspaces are currently disabled")
    expect(page.get_by_label("Search in", exact=True).locator('option[value="all"]')).to_be_disabled()
    expect(page.get_by_role("button", name="Remove Travel policy", exact=True)).to_be_visible()
    page.get_by_label("Search in", exact=True).select_option("")
    page.get_by_role("button", name="Done", exact=True).click()
    body = send(page, "Question")
    assert "public_workspace_selection" not in body
    assert body["selected_document_ids"] == ["public-policy"]


def test_admin_hidden_manual_controls_do_not_expose_scope_and_offer_manual_recovery(context_page):
    page, api = context_page
    mount_workflow(page, orchestration=True)
    page.evaluate("() => window.OrchHarness.mount('mount-b', 'Toaster', {})")
    page.evaluate("""() => {
        const H = window.OrchHarness;
        H.stores.chat.useChatStore.getState().setPublicWorkspaceSelection('all');
        const store = H.stores.bootstrap.useBootstrapStore;
        const data = store.getState().data;
        store.setState({data: {...data, features: {...data.features, enable_public_workspaces: false},
            orchestration: {...data.orchestration, show_manual_controls: false}}});
    }""")
    expect(page.get_by_title("Manual controls", exact=True)).to_have_count(0)
    expect(page.get_by_title(re.compile(r"^Documents"))).to_have_count(0)
    page.get_by_role("textbox", name="Message", exact=True).fill("Question")
    page.get_by_role("button", name="Send message", exact=True).click()
    expect(page.get_by_text(re.compile("Switch to Manual mode, then open Documents"))).to_be_visible()
    expect(page.get_by_label("Search in", exact=True)).to_have_count(0)
    assert not any(method == "POST" for method, path in api.requests)
    page.get_by_title("Orchestrate", exact=True).click()
    open_picker(page)
    page.get_by_label("Search in", exact=True).select_option("")
    page.get_by_role("button", name="Done", exact=True).click()
    body = send(page, "Question")
    assert "public_workspace_selection" not in body


@pytest.mark.parametrize("theme,width,height", [
    ("light", 1440, 900), ("dark", 1440, 900),
    ("light", 390, 844), ("dark", 390, 844),
])
def test_scope_picker_layout_and_active_summary(context_page, theme, width, height):
    page, api = context_page
    page.set_viewport_size({"width": width, "height": height})
    assets = Path(__file__).resolve().parents[1] / "application" / "single_app" / "static" / "v2" / "assets"
    stylesheets = list(assets.glob("*.css"))
    assert len(stylesheets) == 1, "Build V2 before checking its production styling."
    page.add_style_tag(content=stylesheets[0].read_text(encoding="utf-8"))
    page.add_style_tag(content="#mount-a { display: flex; flex-direction: column; justify-content: end; height: 100dvh; }")
    mount_workflow(page, orchestration=True)
    page.evaluate("""(theme) => {
        document.documentElement.classList.toggle('dark', theme === 'dark');
        const store = window.OrchHarness.stores.bootstrap.useBootstrapStore;
        const data = store.getState().data;
        store.setState({data: {...data, settings: {...data.settings, public_workspace_labels: {
            singular: 'Public knowledge collection', plural: 'Public knowledge collections with long configured names',
        }}}});
    }""", theme)
    expect(page.get_by_label("Search in", exact=True)).to_have_count(0)
    expect(page.get_by_title(re.compile("^Documents"))).to_have_count(0)
    select_scope(page, "visible")
    documents = page.get_by_title(re.compile(r"^Documents · Visible"))
    expect(documents).to_have_attribute("aria-pressed", "true")
    page.get_by_title("Manual controls", exact=True).click()
    expect(documents).to_have_count(0)
    expect(page.get_by_label("Search in", exact=True)).to_have_count(0)
    open_picker(page)
    expect(page.get_by_label("Search in", exact=True)).to_have_value("visible")
    fits = page.locator("[data-context-picker]").evaluate("""(node) => {
        const rect = node.getBoundingClientRect();
        return rect.left >= 0 && rect.right <= window.innerWidth
            && rect.top >= 0 && rect.bottom <= window.innerHeight
            && document.documentElement.scrollWidth <= window.innerWidth;
    }""")
    assert fits
    expect(page.get_by_role("button", name=re.compile("^Travel policy"))).to_be_visible()
    artifacts = Path(__file__).resolve().parent / "artifacts" / "document-scope"
    artifacts.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(artifacts / f"picker-{theme}-{width}.png"))


@pytest.mark.parametrize("restriction", ["shared", "restricted", "referenceUploadsOnly", "not-opted-in"])
def test_unrelated_editors_cannot_edit_the_global_chat_scope(context_page, restriction):
    page, api = context_page
    mount_workflow(page)
    page.evaluate("""(restriction) => {
        const H = window.OrchHarness;
        H.unmount('mount-a');
        const props = {
            id: 'isolated-editor', label: 'Answer', conversationId: null,
            draft: {text: '', contextItems: [], attachedPrompt: null, promptValues: {}, uploads: [], imageReferences: []},
            onChange: () => {}, pickerOpen: true, allowContext: true,
            documentScopeControl: {
                id: 'isolated-scope', publicEnabled: true, disabled: false,
                onChange: (selection) => H.stores.chat.useChatStore.getState().setPublicWorkspaceSelection(selection),
            },
        };
        if (restriction === 'not-opted-in') delete props.documentScopeControl;
        else props[restriction] = true;
        H.mount('mount-a', 'ComposerEditor', props);
    }""", restriction)
    expect(page.locator("[data-context-picker]")).to_be_visible()
    expect(page.get_by_label("Search in", exact=True)).to_have_count(0)
    selection = page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().publicWorkspaceSelection")
    assert selection is None


def test_scope_cannot_change_while_streaming(context_page):
    page, api = context_page
    mount_workflow(page)
    select_scope(page, "visible")
    open_picker(page)
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.setState({streaming: true})")
    expect(page.get_by_label("Search in", exact=True)).to_be_disabled()
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.setState({streaming: false})")
    expect(page.get_by_label("Search in", exact=True)).to_be_enabled()
    expect(page.get_by_label("Search in", exact=True)).to_have_value("visible")


def test_an_open_picker_closes_when_admin_hides_manual_controls(context_page):
    page, api = context_page
    mount_workflow(page, orchestration=True)
    select_scope(page, "all")
    open_picker(page)
    page.evaluate("""() => {
        const store = window.OrchHarness.stores.bootstrap.useBootstrapStore;
        const data = store.getState().data;
        store.setState({data: {...data, orchestration: {...data.orchestration, show_manual_controls: false}}});
    }""")
    expect(page.locator("[data-context-picker]")).to_have_count(0)
    selection = page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().publicWorkspaceSelection")
    assert selection == "all"


@pytest.mark.parametrize("conflict", ["image", "saved-result"])
def test_incompatible_modes_explain_recovery_without_a_standalone_scope_control(context_page, conflict):
    page, api = context_page
    mount_workflow(page)
    select_scope(page, "all")
    page.evaluate("() => window.OrchHarness.mount('mount-b', 'Toaster', {})")
    if conflict == "image":
        page.evaluate("""() => {
            const store = window.OrchHarness.stores.bootstrap.useBootstrapStore;
            const data = store.getState().data;
            store.setState({data: {...data, features: {...data.features, enable_image_generation: true}}});
        }""")
        page.get_by_title("Image", exact=True).click()
        recovery = "Turn off Image"
    else:
        page.evaluate("""() => {
            const store = window.OrchHarness.stores.chat.useChatStore;
            store.setState({analysisResultContext: {
                conversation_id: store.getState().activeConversationId, message_id: 'saved-result',
                result_sha256: 'a'.repeat(64),
            }});
        }""")
        recovery = "Remove the saved result"
    page.get_by_role("textbox", name="Message", exact=True).fill("Question")
    page.get_by_role("button", name="Send message", exact=True).click()
    expect(page.get_by_text(re.compile(recovery))).to_be_visible()
    expect(page.get_by_label("Search in", exact=True)).to_have_count(0)
    assert not any(method == "POST" for method, path in api.requests)
    if conflict == "image":
        page.get_by_title("Image", exact=True).click()
    else:
        page.get_by_role("button", name="Remove saved analysis context", exact=True).click()
    select_scope(page, "")
    body = send(page, "Question")
    assert "public_workspace_selection" not in body
