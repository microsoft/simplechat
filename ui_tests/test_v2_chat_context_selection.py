# test_v2_chat_context_selection.py
"""
Browser regressions for V2 context selection and explicitly chosen inline mentions.
Version: 0.261.094
Implemented in: 0.261.094

The real Composer, DocumentExplorer, stores, router, and request builders run in the
existing local Playwright harness. Only API responses are mocked. No Azure resource,
credentials, or running Flask instance is needed.

Selections must stay pills-only through draft edits, while explicit # completions own
their inline tokens. The suite also covers workspace and delayed StrictMode handoffs,
removal boundaries, and actual chat/planner request metadata and draft clearing.
Missing browser/toolchain dependencies fail rather than silently skip these checks.

Run: python .\\ui_tests\\test_v2_chat_context_selection.py
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Page, Route, expect

# The shared harness must also resolve when this file is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "orchestration"))
import harness_build as hb  # noqa: E402


pytestmark = pytest.mark.ui

CONVERSATION_ID = "context-selection-chat"
SCOPES = {
    "personal": {"kind": "personal", "id": None, "name": "My workspace"},
    "group": {"kind": "group", "id": "group-1", "name": "Marketing"},
    "public": {"kind": "public", "id": "public-1", "name": "Handbook"},
}
DOCUMENTS = {
    "personal": [
        {
            "id": "personal-brief",
            "title": "Quarterly brief",
            "file_name": "quarterly-brief.pdf",
            "status": "completed",
            "tags": [],
        },
        {
            "id": "personal-budget",
            "title": "Budget notes",
            "file_name": "budget-notes.pdf",
            "status": "completed",
            "tags": [],
        },
    ],
    "group": [
        {
            "id": "group-campaign",
            "title": "Campaign outline",
            "file_name": "campaign-outline.pdf",
            "status": "completed",
            "group_id": "group-1",
            "tags": [],
        },
    ],
    "public": [
        {
            "id": "public-policy",
            "title": "Travel policy",
            "file_name": "travel-policy.pdf",
            "status": "completed",
            "public_workspace_id": "public-1",
            "tags": [],
        },
    ],
}
TAGS = {"personal": "urgent", "group": "launch", "public": "public-ready"}
COLLECTIONS = {
    "/api/documents": "personal",
    "/api/group_documents": "group",
    "/api/public_workspace_documents": "public",
}
STREAM_PATHS = {
    "chat": "/api/chat/stream",
    "plan": "/api/v2/orchestration/plan",
}


class ContextApi:
    """Mock only the endpoints the real workflow uses, with an explicit handoff gate."""

    def __init__(self):
        self.requests = []
        self.unexpected = []
        self.deferred_document_ids = set()
        self.pending_documents = []

    def handle(self, route: Route):
        request = route.request
        url = urlsplit(request.url)
        path = url.path
        self.requests.append((request.method, path))

        if request.method == "POST" and path in STREAM_PATHS.values():
            if path == STREAM_PATHS["chat"]:
                frames = [{"response": "Mock answer."}, {"done": True}]
            else:
                body = request.post_data_json
                frames = [
                    {
                        "type": "orchestration_plan",
                        "plan": {
                            "plan_id": "context-plan",
                            "run_id": "context-run",
                            "turn_id": body["turn_id"],
                            "intent": {"summary": "Compare sources", "complexity": "simple"},
                            "steps": [
                                {
                                    "step_id": "answer",
                                    "capability_id": "respond",
                                    "title": "Answer",
                                    "arguments": {},
                                    "estimated_cost": "low",
                                },
                            ],
                            "approval": {
                                "mode": "manual",
                                "timeout_seconds": 0,
                                "state": "pending",
                            },
                            "status": "awaiting_approval",
                        },
                    },
                ]
            route.fulfill(
                content_type="text/event-stream",
                body="".join(f"data: {json.dumps(frame)}\n\n" for frame in frames),
            )
            return

        if request.method == "GET":
            if path == "/api/documents/facets":
                route.fulfill(
                    json={
                        "total": len(DOCUMENTS["personal"]),
                        "untagged": 2,
                        "processing": 0,
                        "errors": 0,
                        "recent": 2,
                        "shared_with_me": 0,
                        "by_tag": {},
                        "by_classification": {},
                    },
                )
                return

            for collection, scope in COLLECTIONS.items():
                if path == f"{collection}/tags":
                    route.fulfill(json={"tags": [{"name": TAGS[scope]}]})
                    return
                if path == collection:
                    query = parse_qs(url.query).get("search", [""])[0].casefold()
                    documents = [
                        document
                        for document in DOCUMENTS[scope]
                        if query in f"{document['title']} {document['file_name']}".casefold()
                    ]
                    route.fulfill(
                        json={
                            "documents": documents,
                            "total_count": len(documents),
                            "file_downloads_enabled": False,
                        },
                    )
                    return
                for document in DOCUMENTS[scope]:
                    if path == f"{collection}/{document['id']}":
                        if document["id"] in self.deferred_document_ids:
                            self.pending_documents.append((route, document))
                        else:
                            route.fulfill(json=document)
                        return

        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected test endpoint."})

    def release_documents(self):
        """Release held network responses only after the test has edited the pending draft."""
        self.deferred_document_ids.clear()
        pending, self.pending_documents = self.pending_documents, []
        for route, document in pending:
            route.fulfill(json=document)


@pytest.fixture
def context_page():
    errors = []
    with hb.harness_page(collect_errors=errors) as page:
        api = ContextApi()
        page.route("**/api/**", api.handle)
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )
        try:
            yield page, api
        finally:
            page.evaluate("() => window.OrchHarness.reset()")
            assert not errors, f"Unexpected workflow browser errors: {errors}"
            assert not api.unexpected, f"Unmocked workflow requests: {api.unexpected}"


def mount_workflow(page: Page, entry="/chat", *, strict_mode=False, orchestration=False):
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({
                data: {
                    features: {
                        enable_user_workspace: true,
                        enable_group_workspaces: true,
                        enable_public_workspaces: true,
                        enable_chat_orchestration: spec.orchestration,
                    },
                    orchestration: {
                        enabled: spec.orchestration,
                        show_manual_controls: true,
                        default_approval_mode: 'manual',
                        allow_user_approval_override: true,
                        timed_approval_seconds: 8,
                    },
                    catalogs: { prompts: [], models: [], agents: [] },
                    settings: {},
                    user: { id: 'context-tester', display_name: 'Context Tester' },
                    scope: {
                        groups: [{ id: 'group-1', name: 'Marketing' }],
                        public_workspaces: [{ id: 'public-1', name: 'Handbook' }],
                        active_group_id: null,
                        active_public_workspace_id: null,
                    },
                },
            });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversationId,
                activeConversationKind: 'personal',
                messages: [],
                conversations: [],
                streaming: false,
                streamError: null,
            });
            H.stores.orchestration.useOrchestrationStore.getState()
                .setVisibleConversation(spec.conversationId);
            H.mount('mount-a', 'ContextWorkflow', {}, {
                initialEntries: [spec.entry],
                strictMode: spec.strictMode,
            });
        }""",
        {
            "entry": entry,
            "strictMode": strict_mode,
            "orchestration": orchestration,
            "conversationId": CONVERSATION_ID,
        },
    )
    expect(page.get_by_label("Current route", exact=True)).to_be_visible()


def expect_pills(page: Page, *labels):
    expect(page.locator("button[aria-label^='Remove ']")).to_have_count(len(labels))
    for label in labels:
        expect(page.get_by_role("button", name=f"Remove {label}", exact=True)).to_have_count(1)


def open_picker(page: Page):
    toolbar = page.get_by_title(re.compile(r"^Documents(?: · \d+)?$"))
    if not toolbar.is_visible():
        page.get_by_title("Manual controls", exact=True).click()
    toolbar.click()
    expect(page.get_by_role("searchbox", name="Search documents", exact=True)).to_be_visible()


def picker_candidate(page: Page, label):
    return page.get_by_role("button", name=re.compile(f"^{re.escape(label)}")).and_(
        page.locator("button[aria-pressed]")
    )


def pick_context(page: Page, *labels):
    open_picker(page)
    for label in labels:
        candidate = picker_candidate(page, label)
        expect(candidate).to_have_attribute("aria-pressed", "false")
        candidate.click()
        expect(candidate).to_have_attribute("aria-pressed", "true")
    page.get_by_role("button", name="Done", exact=True).click()


def choose_mention(page: Page, label, *, query=None, keyboard=False):
    draft = page.get_by_role("textbox", name="Message", exact=True)
    draft.fill(f"{draft.input_value()}#{query or label}")
    menu = page.get_by_role("listbox", name="Context suggestions")
    option = menu.get_by_role("option", name=re.compile(f"^{re.escape(label)}"))
    expect(option).to_be_visible()
    if keyboard:
        expect(option).to_have_attribute("aria-selected", "true")
        draft.press("Enter")
    else:
        option.click()
    expect(menu).to_have_count(0)
    # Completion restores the caret on the next frame, before further user typing.
    page.evaluate("() => new Promise(resolve => window.requestAnimationFrame(resolve))")
    expect(draft).to_be_focused()
    assert draft.evaluate(
        "element => element.selectionStart === element.value.length"
        " && element.selectionEnd === element.value.length"
    )


def delete_range(page: Page, start, end):
    draft = page.get_by_role("textbox", name="Message", exact=True)
    draft.evaluate(
        "(element, range) => { element.focus(); element.setSelectionRange(...range); }",
        [start, end],
    )
    draft.press("Backspace")


def send_draft(page: Page, api: ContextApi, dispatch="chat"):
    draft = page.get_by_role("textbox", name="Message", exact=True)
    message = draft.input_value()
    endpoint = STREAM_PATHS[dispatch]
    with page.expect_request(
        lambda request: request.method == "POST" and urlsplit(request.url).path == endpoint
    ) as sent:
        page.get_by_role("button", name="Send message", exact=True).click()

    payload = sent.value.post_data_json
    assert payload["message"] == message
    assert payload["conversation_id"] == CONVERSATION_ID
    expect(draft).to_have_value("")
    expect_pills(page)
    page.wait_for_function(
        "() => !window.OrchHarness.stores.chat.useChatStore.getState().streaming"
    )
    state = page.evaluate(
        """() => {
            const state = window.OrchHarness.stores.chat.useChatStore.getState();
            return {
                error: state.streamError,
                users: state.messages.filter(message => message.role === 'user'),
                plans: Object.keys(
                    window.OrchHarness.stores.orchestration.useOrchestrationStore.getState().plans
                ).length,
            };
        }"""
    )
    assert state["error"] is None
    assert [user["content"] for user in state["users"]] == [message]
    assert [path for method, path in api.requests if method == "POST"] == [endpoint]
    if dispatch == "plan":
        assert state["plans"] == 1
    return payload


def expect_context_metadata(payload, *, documents=(), tags=(), group=False, public=False):
    assert sorted(payload["selected_document_ids"]) == sorted(documents)
    assert payload.get("tags", []) == list(tags)
    assert payload.get("document_filter_mode") == ("union" if documents and tags else None)
    assert payload["doc_scope"] == ("all" if group or public else "personal")
    assert payload["active_group_ids"] == (["group-1"] if group else [])
    assert payload["active_group_id"] == ("group-1" if group else None)
    assert payload["active_public_workspace_ids"] == (["public-1"] if public else [])
    assert payload["active_public_workspace_id"] == ("public-1" if public else None)


@pytest.mark.parametrize("initial_draft", ["", "Keep this paragraph.\nAnd this one."])
def test_picker_selection_never_edits_the_draft_and_survives_typing(context_page, initial_draft):
    page, _ = context_page
    mount_workflow(page)
    draft = page.get_by_role("textbox", name="Message", exact=True)
    draft.fill(initial_draft)
    pick_context(page, "Quarterly brief")
    expect(draft).to_have_value(initial_draft)
    expect_pills(page, "Quarterly brief")

    draft.press("Control+End")
    draft.press_sequentially(" More detail.")
    expect(draft).to_have_value(f"{initial_draft} More detail.")
    expect_pills(page, "Quarterly brief")
    draft.fill("A replacement question.")
    expect_pills(page, "Quarterly brief")
    draft.fill("")
    expect_pills(page, "Quarterly brief")
    expect(page.get_by_role("button", name="Send message", exact=True)).to_be_disabled()


@pytest.mark.parametrize("dispatch", ["chat", "plan"])
def test_mixed_picker_context_reaches_real_dispatch_and_clears_the_turn(context_page, dispatch):
    page, api = context_page
    mount_workflow(page, orchestration=dispatch == "plan")
    draft = page.get_by_role("textbox", name="Message", exact=True)
    draft.fill("Compare these sources.")
    pick_context(
        page, "Quarterly brief", "Campaign outline", "Travel policy", "urgent", "Marketing"
    )
    expect(draft).to_have_value("Compare these sources.")
    expect_pills(page, "Quarterly brief", "Campaign outline", "Travel policy", "urgent", "Marketing")
    draft.press("Control+End")
    draft.press_sequentially(" Include the differences.")
    payload = send_draft(page, api, dispatch)
    assert "#[" not in payload["message"]
    expect_context_metadata(
        payload,
        documents=["personal-brief", "group-campaign", "public-policy"],
        tags=["urgent"],
        group=True,
        public=True,
    )
    if dispatch == "chat":
        assert payload["hybrid_search"] is True
    else:
        assert payload["approval_mode"] == "manual"
        assert payload["context_documents"] == [
            {
                "id": "personal-brief",
                "label": "Quarterly brief",
                "file_name": "quarterly-brief.pdf",
                "scope_kind": "personal",
            },
            {
                "id": "group-campaign",
                "label": "Campaign outline",
                "file_name": "campaign-outline.pdf",
                "scope_kind": "group",
                "workspace_id": "group-1",
            },
            {
                "id": "public-policy",
                "label": "Travel policy",
                "file_name": "travel-policy.pdf",
                "scope_kind": "public",
                "workspace_id": "public-1",
            },
        ]


@pytest.mark.parametrize("scope", ["personal", "group", "public"])
@pytest.mark.parametrize("kind", ["tag", "workspace"])
def test_tag_or_workspace_alone_enables_search_with_its_scope(context_page, scope, kind):
    page, api = context_page
    mount_workflow(page)
    label = TAGS[scope] if kind == "tag" else SCOPES[scope]["name"]
    pick_context(page, label)
    draft = page.get_by_role("textbox", name="Message", exact=True)
    expect(draft).to_have_value("")
    expect_pills(page, label)
    draft.fill("Find the relevant guidance.")
    expect_pills(page, label)
    payload = send_draft(page, api)
    assert payload["hybrid_search"] is True
    expect_context_metadata(
        payload,
        tags=[label] if kind == "tag" else [],
        group=scope == "group",
        public=scope == "public",
    )


def test_workspace_chat_action_hands_real_selection_to_pills_only(context_page):
    page, api = context_page
    mount_workflow(page, "/workspace", strict_mode=True)
    page.get_by_role("checkbox", name="Select Quarterly brief", exact=True).check()
    page.get_by_role("checkbox", name="Select Budget notes", exact=True).check()
    page.get_by_role("button", name="Chat", exact=True).first.click()

    expect(page.get_by_label("Current route", exact=True)).to_have_text("/chat")
    draft = page.get_by_role("textbox", name="Message", exact=True)
    expect(draft).to_have_value("")
    expect_pills(page, "Quarterly brief", "Budget notes")
    assert ("GET", "/api/documents/personal-brief") not in api.requests
    assert ("GET", "/api/documents/personal-budget") not in api.requests
    draft.fill("Compare my selected documents.")
    payload = send_draft(page, api)
    expect_context_metadata(payload, documents=["personal-brief", "personal-budget"])
    draft.fill("Start the next turn without those pills.")
    expect_pills(page)


def test_router_state_handoff_deduplicates_and_retains_scoped_metadata(context_page):
    page, api = context_page
    group_document = {"document": DOCUMENTS["group"][0], "scope": SCOPES["group"]}
    mount_workflow(
        page,
        {
            "pathname": "/chat",
            "search": (
                "?search_documents=true&doc_scope=all&document_ids=group-campaign,public-policy"
                "&tags=urgent&group_id=group-1&workspace_id=public-1&keep=untouched"
            ),
            "state": {
                "contextDocuments": [
                    group_document,
                    group_document,
                    {"document": DOCUMENTS["public"][0], "scope": SCOPES["public"]},
                ],
                "contextTags": [{"name": "urgent", "scope": SCOPES["personal"]}],
            },
        },
        strict_mode=True,
    )
    expect(page.get_by_label("Current route", exact=True)).to_have_text("/chat?keep=untouched")
    draft = page.get_by_role("textbox", name="Message", exact=True)
    expect(draft).to_have_value("")
    expect_pills(page, "Campaign outline", "Travel policy", "urgent")
    assert not api.requests, "Router records should avoid document resolution requests."
    draft.fill("Use the handed-over sources.")
    payload = send_draft(page, api)
    expect_context_metadata(
        payload,
        documents=["group-campaign", "public-policy"],
        tags=["urgent"],
        group=True,
        public=True,
    )


@pytest.mark.parametrize("strict_mode", [False, True], ids=["ordinary", "strict-mode"])
def test_delayed_url_handoff_preserves_in_progress_draft_and_is_applied_once(
    context_page, strict_mode
):
    page, api = context_page
    api.deferred_document_ids.add("personal-brief")
    entry = (
        "/chat?search_documents=true&doc_scope=personal"
        "&document_ids=personal-brief,personal-brief&document_id=personal-budget"
        "&tags=urgent,urgent&keep=untouched"
    )
    with page.expect_request(re.compile(r"/api/documents/personal-brief$")):
        mount_workflow(page, entry, strict_mode=strict_mode)
    draft = page.get_by_role("textbox", name="Message", exact=True)
    draft.fill("Draft started before the documents arrived.")
    expect_pills(page)
    expect(page.get_by_label("Current route", exact=True)).to_have_text(entry)
    pick_context(page, "Marketing")
    draft.press("Control+End")
    draft.press_sequentially(" Keep this edit.")
    expected = "Draft started before the documents arrived. Keep this edit."
    assert api.pending_documents, "The test must edit while resolution is still pending."
    api.release_documents()

    expect(page.get_by_label("Current route", exact=True)).to_have_text("/chat?keep=untouched")
    expect(draft).to_have_value(expected)
    expect_pills(page, "Marketing", "Quarterly brief", "Budget notes", "urgent")
    page.get_by_role("button", name="Remove Quarterly brief", exact=True).click()
    draft.fill("The removed handoff document must not return.")
    expect_pills(page, "Marketing", "Budget notes", "urgent")
    payload = send_draft(page, api)
    expect_context_metadata(
        payload, documents=["personal-budget"], tags=["urgent"], group=True
    )
    expect(page.get_by_label("Current route", exact=True)).to_have_text("/chat?keep=untouched")


@pytest.mark.parametrize(
    ("label", "query", "keyboard"),
    [("Quarterly brief", "Quarter", True), ("urgent", "urgent", False), ("Marketing", "Marketing", False)],
    ids=["document-keyboard", "tag-mouse", "workspace-mouse"],
)
def test_explicit_hash_completion_adds_inline_text_and_one_pill(context_page, label, query, keyboard):
    page, _ = context_page
    mount_workflow(page)
    draft = page.get_by_role("textbox", name="Message", exact=True)
    draft.fill("Use ")
    choose_mention(page, label, query=query, keyboard=keyboard)
    expect(draft).to_have_value(f"Use #[{label}] ")
    expect_pills(page, label)
    draft.press_sequentially("for this answer.")
    expect(draft).to_have_value(f"Use #[{label}] for this answer.")
    expect_pills(page, label)


def test_deleting_mention_preserves_selection_without_adopting_later_literal(context_page):
    page, api = context_page
    mount_workflow(page)
    draft = page.get_by_role("textbox", name="Message", exact=True)
    draft.fill("Discuss ")
    pick_context(page, "Quarterly brief")
    choose_mention(page, "Quarterly brief", keyboard=True)
    expect(draft).to_have_value("Discuss #[Quarterly brief] ")
    expect_pills(page, "Quarterly brief")
    delete_range(page, len("Discuss "), len(draft.input_value()))
    expect(draft).to_have_value("Discuss ")
    expect_pills(page, "Quarterly brief")

    literal = "Quoted literal #[Quarterly brief] is not a new reference."
    draft.fill(literal)
    expect_pills(page, "Quarterly brief")
    page.get_by_role("button", name="Remove Quarterly brief", exact=True).click()
    expect(draft).to_have_value(literal)
    expect_pills(page)
    payload = send_draft(page, api)
    expect_context_metadata(payload)
    assert payload["hybrid_search"] is False


@pytest.mark.parametrize("delete_complete_token", [True, False], ids=["delete-token", "break-token"])
def test_repeated_mentions_share_one_pill_until_the_last_complete_token_is_gone(
    context_page, delete_complete_token
):
    page, _ = context_page
    mount_workflow(page)
    draft = page.get_by_role("textbox", name="Message", exact=True)
    draft.fill("Use ")
    choose_mention(page, "Quarterly brief", keyboard=True)
    draft.press_sequentially("and ")
    choose_mention(page, "Quarterly brief")
    expect(draft).to_have_value("Use #[Quarterly brief] and #[Quarterly brief] ")
    expect_pills(page, "Quarterly brief")

    closing = draft.input_value().index("]")
    delete_range(page, closing, closing + 1)
    expect_pills(page, "Quarterly brief")
    broken = draft.input_value()
    start = broken.rindex("#[") if delete_complete_token else broken.rindex("]")
    end = broken.rindex("]") + 1
    delete_range(page, start, end)
    expect(draft).to_have_value(broken[:start] + broken[end:])
    expect_pills(page)
    draft.fill("An unbound #[Quarterly brief] stays literal.")
    expect_pills(page)


@pytest.mark.parametrize("removal", ["pill", "deselect", "picker-clear", "chip-clear"])
def test_removal_strips_owned_mentions_only_and_preserves_unrelated_prose(context_page, removal):
    page, _ = context_page
    mount_workflow(page)
    draft = page.get_by_role("textbox", name="Message", exact=True)
    prefix = "Keep\n  spacing and #[Budget notes] literal.\nUse "
    draft.fill(prefix)
    expect_pills(page)
    choose_mention(page, "Quarterly brief")
    draft.press_sequentially("for the answer.")
    pick_context(page, "Budget notes", "Campaign outline")
    expect_pills(page, "Quarterly brief", "Budget notes", "Campaign outline")
    expect(draft).to_have_value(f"{prefix}#[Quarterly brief] for the answer.")

    if removal == "pill":
        page.get_by_role("button", name="Remove Quarterly brief", exact=True).click()
    elif removal == "chip-clear":
        page.get_by_role("button", name="Clear all", exact=True).click()
    else:
        open_picker(page)
        if removal == "deselect":
            candidate = picker_candidate(page, "Quarterly brief")
            expect(candidate).to_have_attribute("aria-pressed", "true")
            candidate.click()
            expect(candidate).to_have_attribute("aria-pressed", "false")
        else:
            page.get_by_role("button", name="Clear", exact=True).click()
        page.get_by_role("button", name="Done", exact=True).click()

    expect(draft).to_have_value(f"{prefix}for the answer.")
    if removal in {"pill", "deselect"}:
        expect_pills(page, "Budget notes", "Campaign outline")
        page.get_by_role("button", name="Remove Budget notes", exact=True).click()
        expect(draft).to_have_value(f"{prefix}for the answer.")
        expect_pills(page, "Campaign outline")
    else:
        expect_pills(page)


def test_collapsed_workspace_removal_keeps_other_context_and_unbound_text(context_page):
    page, api = context_page
    mount_workflow(page)
    draft = page.get_by_role("textbox", name="Message", exact=True)
    draft.fill("Preserve #[Budget notes] as typed. Compare ")
    choose_mention(page, "Quarterly brief")
    draft.press_sequentially("with ")
    choose_mention(page, "Travel policy")
    draft.press_sequentially("for the report.")
    expect(draft).to_have_value(
        "Preserve #[Budget notes] as typed. Compare #[Quarterly brief] "
        "with #[Travel policy] for the report."
    )
    pick_context(page, "Budget notes", "urgent", "Campaign outline", "Marketing")
    expect(page.get_by_title("Documents · 6", exact=True)).to_be_visible()
    group = page.get_by_role("button", name=re.compile(r"^My workspace"))
    expect(group).to_have_attribute("aria-expanded", "false")
    group.click()
    expect(group).to_have_attribute("aria-expanded", "true")
    expect_pills(page, "Quarterly brief", "Budget notes", "urgent")
    page.get_by_role("button", name="Remove all", exact=True).click()

    expected = "Preserve #[Budget notes] as typed. Compare with #[Travel policy] for the report."
    expect(draft).to_have_value(expected)
    expect_pills(page, "Campaign outline", "Marketing", "Travel policy")
    payload = send_draft(page, api)
    expect_context_metadata(
        payload, documents=["group-campaign", "public-policy"], group=True, public=True
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([str(Path(__file__).resolve()), "-q", *sys.argv[1:]]))
