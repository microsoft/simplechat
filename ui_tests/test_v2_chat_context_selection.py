# test_v2_chat_context_selection.py
"""
Browser regressions for V2 context selection and explicitly chosen inline mentions.
Version: 0.261.099
Implemented in: 0.261.094
Shared editor and prompt dispatch regression coverage added in: 0.261.096

The real Composer, DocumentExplorer, stores, router, and request builders run in the
existing Playwright harness. The shared connection fixture supports a configured Azure
Playwright workspace or a local browser. API responses and local harness assets are
intercepted; no running Flask instance or application credentials are needed.

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
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import harness_build as hb  # noqa: E402
from playwright_connection import connect_options  # noqa: E402,F401


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
        self.expected_resource_errors = set()

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
def context_page(page):
    errors = []
    hb.ensure_bundle()
    api = ContextApi()

    def handle(route):
        path = urlsplit(route.request.url).path
        if path == "/harness.html":
            route.fulfill(content_type="text/html", body=(hb.HERE / "harness.html").read_text(encoding="utf-8"))
        elif path == "/harness.bundle.js":
            route.fulfill(content_type="application/javascript", body=hb.BUNDLE.read_text(encoding="utf-8"))
        elif path == "/favicon.ico":
            route.fulfill(status=204)
        else:
            api.handle(route)

    page.route("**/*", handle)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text)
        if message.type == "error" and not (
            message.text.startswith("Failed to load resource:")
            and any(
                urlsplit(message.location.get("url", "")).path == path
                and f"status of {status}" in message.text
                for path, status in api.expected_resource_errors
            )
        ) else None,
    )
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto("http://simplechat.test/harness.html")
    page.wait_for_function('() => typeof window.OrchHarness === "object"')
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


@pytest.mark.parametrize("dispatch", ["chat", "plan"])
def test_shared_editor_prompt_variables_and_context_reach_both_main_send_paths(context_page, dispatch):
    page, api = context_page
    mount_workflow(page, orchestration=dispatch == "plan")
    page.evaluate(
        """() => window.OrchHarness.stores.bootstrap.useBootstrapStore.getState().upsertPromptInCatalog({
            id: 'context-prompt', name: 'Context report', content: 'For {{topic}}: {{composer}}',
            scope_type: 'personal'
        })"""
    )
    pick_context(page, "Quarterly brief")
    draft = page.get_by_role("textbox", name="Message", exact=True)
    draft.fill("/Context")
    menu = page.get_by_role("listbox", name="Prompt suggestions", exact=True)
    expect(menu.get_by_role("option", name=re.compile(r"^Context report"))).to_be_visible()
    draft.press("Tab")
    expect(menu).to_have_count(0)
    expect(draft).to_have_value("")
    expect_pills(page, "Quarterly brief", "Context report")

    page.get_by_role("button", name="Edit Context report for this message", exact=True).click()
    page.get_by_role("textbox", name="topic", exact=True).fill("resilience")
    page.get_by_role("textbox", name="Prompt text", exact=True).fill(
        "Compare {{topic}} using {{composer}}."
    )
    draft.fill("the latest report")
    expect_pills(page, "Quarterly brief", "Context report")
    with page.expect_request(
        lambda request: request.method == "POST" and urlsplit(request.url).path == STREAM_PATHS[dispatch]
    ) as sent:
        page.get_by_role("button", name="Send message", exact=True).click()
    payload = sent.value.post_data_json
    assert payload["message"] == "Compare resilience using the latest report."
    assert payload["prompt_info"]["variables"] == {"topic": "resilience", "composer": "the latest report"}
    assert payload["prompt_info"]["original_content"] == "For {{topic}}: {{composer}}"
    assert payload["prompt_info"]["edited"] is True
    assert payload["prompt_info"]["user_text"] == ""
    expect_context_metadata(payload, documents=["personal-brief"])
    expect(draft).to_have_value("")
    expect_pills(page)
    assert [path for method, path in api.requests if method == "POST"] == [STREAM_PATHS[dispatch]]


def test_shared_editor_prompt_only_send_and_picker_keyboard_remain_safe(context_page):
    page, api = context_page
    mount_workflow(page)
    page.evaluate(
        """() => window.OrchHarness.stores.bootstrap.useBootstrapStore.getState().upsertPromptInCatalog({
            id: 'brief-prompt', name: 'Brief report', content: 'Summarize the available sources.',
            scope_type: 'personal'
        })"""
    )
    draft = page.get_by_role("textbox", name="Message", exact=True)
    draft.fill("/Brief")
    expect(page.get_by_role("listbox", name="Prompt suggestions")).to_be_visible()
    draft.press("Enter")
    expect(draft).to_have_value("")
    expect(page.get_by_role("button", name="Send message", exact=True)).to_be_enabled()
    open_picker(page)
    page.get_by_role("searchbox", name="Search documents", exact=True).press("Enter")
    assert not [path for method, path in api.requests if method == "POST"]
    page.get_by_role("button", name="Done", exact=True).click()
    with page.expect_request(
        lambda request: request.method == "POST" and urlsplit(request.url).path == STREAM_PATHS["chat"]
    ) as sent:
        page.get_by_role("button", name="Send message", exact=True).click()
    assert sent.value.post_data_json["message"] == "Summarize the available sources."
    assert sent.value.post_data_json["prompt_info"]["user_text"] == ""
    expect(page.get_by_role("button", name="Remove Brief report", exact=True)).to_have_count(0)


def test_shared_editor_upload_requires_destination_and_waits_for_real_group_document(context_page):
    page, api = context_page
    mount_workflow(page)
    page.evaluate(
        """() => {
            const store = window.OrchHarness.stores.bootstrap.useBootstrapStore;
            store.setState(state => ({data: {...state.data,
                features: {...state.data.features, enable_chat_file_uploads: true},
                scope: {...state.data.scope, groups: [
                    {id: 'group-1', name: 'Marketing'}, {id: 'group-2', name: 'Legal'}
                ]}
            }}));
        }"""
    )
    pick_context(page, "Marketing", "Legal")
    page.get_by_role("textbox", name="Message", exact=True).fill("Read the uploaded group document.")
    uploads = []
    ready = False
    api.expected_resource_errors.add(("/upload", 400))

    def upload(route):
        uploads.append(route.request.post_data_buffer.decode("utf-8", errors="replace"))
        if len(uploads) == 1:
            route.fulfill(status=400, json={
                "error": "Choose a destination.",
                "requires_group_upload_target": True,
                "group_upload_targets": [
                    {"id": "group-1", "name": "Marketing", "can_upload": True},
                    {"id": "group-2", "name": "Legal", "can_upload": True},
                ],
            })
        else:
            route.fulfill(json={
                "conversation_id": CONVERSATION_ID,
                "file_message_id": "real-file-message",
                "workspace_document_id": "real-group-document",
                "workspace_scope": "group",
                "workspace_document": {
                    "document_id": "real-group-document", "scope": "group", "group_id": "group-2",
                    "file_name": "evidence.pdf", "status": "Queued for processing", "percentage_complete": 0,
                },
                "group_upload_target": {"id": "group-2", "name": "Legal", "can_upload": True},
            })

    def document_status(route):
        route.fulfill(json={
            "id": "real-group-document", "group_id": "group-2", "file_name": "evidence.pdf",
            "status": "Processing complete" if ready else "Processing",
            "percentage_complete": 100 if ready else 35,
        })

    page.route("**/upload", upload)
    page.route("**/api/get_messages?*", lambda route: route.fulfill(json={"messages": []}))
    page.route("**/api/group_documents/real-group-document", document_status)
    page.locator('[data-composer-editor="composer-input"] input[type="file"]').set_input_files({
        "name": "evidence.pdf", "mimeType": "application/pdf", "buffer": b"upload fixture",
    })
    destination = page.get_by_label("Upload destination", exact=True)
    expect(destination).to_be_visible()
    expect(page.get_by_role("button", name="Retry evidence.pdf", exact=True)).to_be_disabled()
    destination.select_option("group-2")
    page.get_by_role("button", name="Retry evidence.pdf", exact=True).click()
    expect(page.get_by_text("Processing 35%", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Send message", exact=True)).to_be_disabled()
    assert len(uploads) == 2
    assert 'name="upload_scope_group_ids"\r\n\r\ngroup-1' in uploads[1]
    assert 'name="upload_scope_group_ids"\r\n\r\ngroup-2' in uploads[1]
    assert 'name="group_upload_target_id"\r\n\r\ngroup-2' in uploads[1]
    ready = True
    expect(page.get_by_text("Ready", exact=True)).to_be_visible(timeout=15000)
    with page.expect_request(
        lambda request: request.method == "POST" and urlsplit(request.url).path == STREAM_PATHS["chat"]
    ) as sent:
        page.get_by_role("button", name="Send message", exact=True).click()
    assert sent.value.post_data_json["selected_document_ids"] == ["real-group-document"]
    assert sorted(sent.value.post_data_json["active_group_ids"]) == ["group-1", "group-2"]
    assert "real-file-message" not in sent.value.post_data_json["selected_document_ids"]
    expect(page.get_by_role("list", name="Attached files", exact=True)).to_have_count(0)


def test_shared_editor_new_chat_upload_batches_share_the_returned_conversation(context_page):
    page, _ = context_page
    mount_workflow(page)
    page.evaluate(
        """() => {
            const H = window.OrchHarness;
            H.stores.chat.useChatStore.setState({activeConversationId: null});
            const store = H.stores.bootstrap.useBootstrapStore;
            store.setState(state => ({data: {...state.data,
                features: {...state.data.features, enable_chat_file_uploads: true}
            }}));
        }"""
    )
    uploads = []
    pending = []
    created = "new-upload-conversation"

    def upload(route):
        uploads.append(route.request.post_data_buffer.decode("utf-8", errors="replace"))
        if len(uploads) == 1:
            pending.append(route)
        else:
            route.fulfill(json={"conversation_id": created, "file_message_id": "created_file_2"})

    page.route("**/upload", upload)
    file_input = page.locator('[data-composer-editor="composer-input"] input[type="file"]')
    with page.expect_request(lambda request: urlsplit(request.url).path == "/upload"):
        file_input.set_input_files({"name": "first.txt", "mimeType": "text/plain", "buffer": b"first"})
    file_input.set_input_files({"name": "second.txt", "mimeType": "text/plain", "buffer": b"second"})
    expect(page.get_by_text("second.txt", exact=True)).to_be_visible()
    assert len(uploads) == 1
    pending[0].fulfill(json={"conversation_id": created, "file_message_id": "created_file_1"})
    expect(page.get_by_text("Ready", exact=True)).to_have_count(2)
    assert len(uploads) == 2
    assert 'name="conversation_id"' not in uploads[0]
    assert f'name="conversation_id"\r\n\r\n{created}' in uploads[1]
    page.get_by_role("textbox", name="Message", exact=True).fill("Read both files.")
    with page.expect_request(
        lambda request: request.method == "POST" and urlsplit(request.url).path == STREAM_PATHS["chat"]
    ) as sent:
        page.get_by_role("button", name="Send message", exact=True).click()
    assert sent.value.post_data_json["conversation_id"] == created
    assert sent.value.post_data_json["selected_document_ids"] == []


def mount_inline_lifecycle(page):
    mount_workflow(page)
    page.evaluate(
        """(conv) => {
            const H = window.OrchHarness;
            H.unmount('mount-a');
            const bootstrap = H.stores.bootstrap.useBootstrapStore;
            bootstrap.setState(state => ({data: {...state.data,
                features: {...state.data.features, enable_chat_file_uploads: true},
                catalogs: {...state.data.catalogs, prompts: [{
                    id: 'lifecycle-prompt', name: 'Lifecycle prompt',
                    content: 'Compare {{topic}}: {{composer}}. {{note|keep default}}',
                    scope_type: 'personal'
                }]}
            }}));
            H.stores.orchestration.useOrchestrationStore.getState().setElicitation(conv, 'lifecycle-turn', {
                contract_version: 2, elicitation_id: 'lifecycle-question', revision: 0,
                turn_id: 'lifecycle-turn', run_id: '', message: 'Choose a source and describe its use.',
                requested_schema: {type: 'object', properties: {
                    files: {type: 'array', items: {type: 'string'}, title: 'Source files'},
                    details: {type: 'string', title: 'Details'}
                }, required: ['files', 'details']},
                ui_hints: {pages: [['files'], ['details']], order: ['files', 'details'],
                    fields: {files: {input: 'files', candidates: []}}}
            });
            H.mount('mount-a', 'ElicitationCard', {conversationId: conv, turnId: 'lifecycle-turn'},
                {strictMode: true});
        }""",
        CONVERSATION_ID,
    )
    card = page.get_by_role("region", name="Follow-up questions")
    expect(card).to_be_visible()
    return card


def read_inline_lifecycle_draft(page):
    return page.evaluate(
        """(conv) => {
            const O = window.OrchHarness.stores.orchestration;
            return O.selectElicitationDraft(O.useOrchestrationStore.getState(), conv, 'lifecycle-turn');
        }""",
        CONVERSATION_ID,
    )


def defer_editor_response(page, endpoint, payload):
    """Keep one response late even after abort, proving stale completions cannot change drafts."""
    page.evaluate(
        """({endpoint, payload}) => {
            const previous = window.fetch.bind(window);
            window.deferredEditorRequest = {started: false, release: null, signal: null};
            window.fetch = (input, init) => {
                const path = new URL(String(input), window.location.href).pathname;
                const held = window.deferredEditorRequest;
                if (path === endpoint && !held.started) {
                    held.started = true;
                    held.signal = init.signal;
                    return new Promise(resolve => {
                        held.release = () => resolve(new Response(JSON.stringify(payload),
                            {status: 200, headers: {'Content-Type': 'application/json'}}));
                    });
                }
                return previous(input, init);
            };
        }""",
        {"endpoint": endpoint, "payload": payload},
    )


def test_shared_editor_paging_marks_interrupted_transfer_actionable_and_retries(context_page):
    page, _ = context_page
    card = mount_inline_lifecycle(page)
    defer_editor_response(page, "/upload", {
        "conversation_id": CONVERSATION_ID, "file_message_id": "late-file-message",
    })
    page.route("**/upload", lambda route: route.fulfill(json={
        "conversation_id": CONVERSATION_ID, "file_message_id": "retried-file-message",
    }))
    card.locator('input[type="file"]').set_input_files({
        "name": "first.txt", "mimeType": "text/plain", "buffer": b"first answer file",
    })
    page.wait_for_function("() => typeof window.deferredEditorRequest.release === 'function'")
    before = read_inline_lifecycle_draft(page)["editors"]["files"]["uploads"][0]
    assert before["state"] == "uploading"
    card.get_by_role("button", name="Next", exact=True).click()
    card.get_by_role("textbox", name="Details", exact=True).fill("Keep the second answer.")
    state = read_inline_lifecycle_draft(page)
    interrupted = state["editors"]["files"]["uploads"][0]
    assert interrupted["state"] == "failed"
    assert interrupted["interrupted"] == "uploading"
    assert "Retry" in interrupted["error"]
    assert page.evaluate("() => window.deferredEditorRequest.signal.aborted") is True
    page.evaluate("() => window.deferredEditorRequest.release()")
    expect(card.get_by_role("button", name="Finish", exact=True)).to_be_disabled()
    assert read_inline_lifecycle_draft(page)["editors"]["files"]["uploads"][0]["state"] == "failed"
    card.get_by_role("button", name="Back", exact=True).click()
    expect(card.get_by_role("alert").filter(has_text="transfer was interrupted")).to_be_visible()
    with page.expect_file_chooser() as chooser:
        card.get_by_role("button", name="Retry first.txt", exact=True).click()
    chooser.value.set_files({"name": "first.txt", "mimeType": "text/plain", "buffer": b"first answer file"})
    expect(card.get_by_text("Ready", exact=True)).to_be_visible()
    retried = read_inline_lifecycle_draft(page)["editors"]["files"]["uploads"][0]
    assert retried["id"] == before["id"]
    assert retried["reference"]["id"] == "retried-file-message"
    assert retried["reference"]["scope"]["id"] == CONVERSATION_ID
    card.get_by_role("button", name="Next", exact=True).click()
    expect(card.get_by_role("textbox", name="Details", exact=True)).to_have_value("Keep the second answer.")
    expect(card.get_by_role("button", name="Finish", exact=True)).to_be_enabled()


def test_shared_editor_retained_processing_and_prompt_values_survive_remount(context_page):
    page, _ = context_page
    card = mount_inline_lifecycle(page)
    draft = card.get_by_role("textbox", name="Additional details for Source files (optional)", exact=True)
    draft.fill("/Lifecycle")
    expect(card.get_by_role("listbox", name="Prompt suggestions")).to_be_visible()
    draft.press("Tab")
    card.get_by_role("button", name="Edit Lifecycle prompt for this message", exact=True).click()
    card.get_by_role("textbox", name="topic", exact=True).fill("contracts")
    card.get_by_role("textbox", name="note", exact=True).fill("")
    edited = "Review {{topic}}: {{composer}}. {{note|keep default}}"
    card.get_by_role("textbox", name="Prompt text", exact=True).fill(edited)
    draft.fill("the first answer")
    uploading_document = {
        "document_id": "lifecycle-document", "scope": "personal", "file_name": "source.pdf",
        "status": "Processing", "percentage_complete": 25,
    }
    uploads = []

    def upload(route):
        uploads.append(route.request.post_data_buffer)
        route.fulfill(json={
            "conversation_id": CONVERSATION_ID, "file_message_id": "source-file-message",
            "workspace_scope": "personal", "workspace_document_id": "lifecycle-document",
            "workspace_document": uploading_document,
        })

    page.route("**/upload", upload)
    page.route("**/api/documents/lifecycle-document", lambda route: route.fulfill(json={
        **uploading_document, "status": "Processing complete", "percentage_complete": 100,
    }))
    defer_editor_response(page, "/api/documents/lifecycle-document", {
        **uploading_document, "status": "Processing complete", "percentage_complete": 100,
    })
    card.locator('input[type="file"]').set_input_files({
        "name": "source.pdf", "mimeType": "application/pdf", "buffer": b"source fixture",
    })
    expect(card.get_by_text("Processing 25%", exact=True)).to_be_visible()
    page.wait_for_function("() => typeof window.deferredEditorRequest.release === 'function'")
    before = read_inline_lifecycle_draft(page)["editors"]["files"]
    card.get_by_role("button", name="Next", exact=True).click()
    card.get_by_role("textbox", name="Details", exact=True).fill("The independent second answer.")
    retained = read_inline_lifecycle_draft(page)["editors"]["files"]
    assert retained["uploads"][0]["state"] == "processing"
    assert retained["uploads"][0]["reference"] == before["uploads"][0]["reference"]
    assert retained["promptValues"] == {"topic": "contracts", "note": ""}
    assert page.evaluate("() => window.deferredEditorRequest.signal.aborted") is False
    page.evaluate("() => window.OrchHarness.unmount('mount-a')")
    page.evaluate("() => window.deferredEditorRequest.release()")
    page.wait_for_function(
        """(conv) => {
            const O = window.OrchHarness.stores.orchestration;
            return O.selectElicitationDraft(O.useOrchestrationStore.getState(), conv, 'lifecycle-turn')
                .editors.files.uploads[0].state === 'ready';
        }""",
        arg=CONVERSATION_ID,
    )
    page.evaluate(
        """(conv) => {
            const H = window.OrchHarness;
            H.mount('mount-a', 'ElicitationCard', {conversationId: conv, turnId: 'lifecycle-turn'},
                {strictMode: true});
        }""",
        CONVERSATION_ID,
    )
    expect(card.get_by_role("textbox", name="Details", exact=True)).to_have_value("The independent second answer.")
    expect(card.get_by_role("button", name="Finish", exact=True)).to_be_enabled()
    card.get_by_role("button", name="Back", exact=True).click()
    expect(card.get_by_text("Ready", exact=True)).to_be_visible()
    card.get_by_role("button", name="Edit Lifecycle prompt for this message", exact=True).click()
    expect(card.get_by_role("textbox", name="topic", exact=True)).to_have_value("contracts")
    expect(card.get_by_role("textbox", name="note", exact=True)).to_have_value("")
    expect(card.get_by_role("textbox", name="Prompt text", exact=True)).to_have_value(edited)
    expect(draft).to_have_value("the first answer")
    resumed = read_inline_lifecycle_draft(page)
    assert resumed["editors"]["files"]["uploads"][0]["id"] == before["uploads"][0]["id"]
    assert resumed["editors"]["files"]["uploads"][0]["state"] == "ready"
    assert resumed["editors"]["details"]["attachedPrompt"] is None
    assert len(uploads) == 1, "Remounting must check the existing file, not upload it a second time."
    card.get_by_role("button", name="Next", exact=True).click()
    expect(card.get_by_role("button", name="Finish", exact=True)).to_be_enabled()


@pytest.mark.parametrize("retirement", ["discard", "supersede", "remove"])
@pytest.mark.parametrize("processing", [False, True], ids=["transfer", "processing"])
def test_shared_editor_late_upload_cannot_revive_a_retired_question(context_page, retirement, processing):
    page, _ = context_page
    card = mount_inline_lifecycle(page)
    if processing:
        page.route("**/upload", lambda route: route.fulfill(json={
            "conversation_id": CONVERSATION_ID, "workspace_document_id": "retired-document",
            "workspace_scope": "personal", "workspace_document": {
                "document_id": "retired-document", "scope": "personal", "status": "Processing",
                "file_name": "retired.txt", "percentage_complete": 25,
            },
        }))
        defer_editor_response(page, "/api/documents/retired-document", {
            "status": "Processing complete", "percentage_complete": 100,
        })
    else:
        defer_editor_response(page, "/upload", {
            "conversation_id": CONVERSATION_ID, "file_message_id": "late-retired-file",
        })
    card.locator('input[type="file"]').set_input_files({
        "name": "retired.txt", "mimeType": "text/plain", "buffer": b"retired upload",
    })
    page.wait_for_function("() => typeof window.deferredEditorRequest.release === 'function'")
    if processing:
        card.get_by_role("button", name="Next", exact=True).click()
        assert page.evaluate("() => window.deferredEditorRequest.signal.aborted") is False
    page.evaluate(
        """({conv, retirement}) => {
            const O = window.OrchHarness.stores.orchestration;
            const store = O.useOrchestrationStore.getState();
            if (retirement === 'supersede') {
                const previous = O.selectElicitation(store, conv, 'lifecycle-turn');
                store.setElicitation(conv, 'lifecycle-turn', {...previous, elicitation_id: 'replacement-question'});
            } else if (retirement === 'remove') {
                store.updateElicitationDraft(conv, 'lifecycle-turn', 'lifecycle-question', 0, draft => ({
                    ...draft, editors: {...draft.editors, files: {...draft.editors.files, uploads: []}}
                }));
            } else {
                store.clearElicitation(conv, 'lifecycle-turn');
            }
        }""",
        {"conv": CONVERSATION_ID, "retirement": retirement},
    )
    page.wait_for_function("() => window.deferredEditorRequest.signal.aborted")
    page.evaluate(
        """async () => {
            window.deferredEditorRequest.release();
            await new Promise(resolve => window.requestAnimationFrame(resolve));
        }"""
    )
    current = read_inline_lifecycle_draft(page)
    if retirement != "discard":
        assert current["elicitationId"] == (
            "replacement-question" if retirement == "supersede" else "lifecycle-question"
        )
        assert current["editors"]["files"]["uploads"] == []
        assert current["editors"]["files"]["text"] == ""
    else:
        assert current is None
        expect(card).to_have_count(0)
    expect(page.get_by_text("retired.txt", exact=True)).to_have_count(0)


def test_shared_editor_preserves_workspace_agent_launch_selection(context_page):
    page, _ = context_page
    mount_workflow(page, orchestration=True)
    page.evaluate(
        """() => {
            const H = window.OrchHarness;
            H.unmount('mount-a');
            H.stores.bootstrap.useBootstrapStore.setState(state => ({data: {...state.data,
                catalogs: {...state.data.catalogs, agents: [{
                    id: 'launch-agent', catalog_key: 'personal::launch-agent',
                    name: 'launch-agent', display_name: 'Launched agent', scope_type: 'personal'
                }]}
            }}));
            H.mount('mount-a', 'Composer', {initialAgentSelection: 'personal::launch-agent'});
        }"""
    )
    expect(page.get_by_title("Orchestrate", exact=True)).to_have_attribute("aria-pressed", "false")
    expect(page.get_by_role("button", name="Launched agent", exact=True)).to_be_visible()
    page.get_by_role("textbox", name="Message", exact=True).fill("Use the launched agent.")
    with page.expect_request(
        lambda request: request.method == "POST" and urlsplit(request.url).path == STREAM_PATHS["chat"]
    ) as sent:
        page.get_by_role("button", name="Send message", exact=True).click()
    assert sent.value.post_data_json["agent_info"]["id"] == "launch-agent"
    assert sent.value.post_data_json["agent_info"]["name"] == "launch-agent"
    assert "model_deployment" not in sent.value.post_data_json


def test_shared_editor_grounded_prompt_values_and_undo_survive_inline_paging(context_page):
    page, _ = context_page
    card = mount_inline_lifecycle(page)
    answer = card.get_by_role("textbox", name="Additional details for Source files (optional)", exact=True)
    answer.fill("/Lifecycle")
    expect(card.get_by_role("listbox", name="Prompt suggestions")).to_be_visible()
    answer.press("Tab")
    answer.fill("Use this answer, not the main composer.")
    card.get_by_role("textbox", name="note", exact=True).fill("")
    card.get_by_role("button", name="Choose knowledge", exact=True).click()
    picker_candidate(page, "Quarterly brief").click()
    page.get_by_role("button", name="Done", exact=True).click()
    fills = []

    def fill(route):
        fills.append(route.request.post_data_json)
        route.fulfill(json={"values": [{
            "key": "topic", "value": "Grounded contracts", "sources": [{
                "document_id": "personal-brief", "chunk_id": "page-1", "title": "Quarterly brief",
                "excerpt": "Authorized evidence for the answer.",
            }],
        }], "unresolved": []})

    page.route("**/api/v2/prompts/fill-variables", fill)
    card.get_by_role("button", name="Fill missing fields", exact=True).click()
    expect(card.get_by_role("textbox", name="topic", exact=True)).to_have_value("Grounded contracts")
    expect(card.get_by_text("AI-filled", exact=True)).to_be_visible()
    assert fills[0]["conversation_id"] == CONVERSATION_ID
    assert fills[0]["composer_text"] == "Use this answer, not the main composer."
    assert fills[0]["selected_document_ids"] == ["personal-brief"]
    card.get_by_role("button", name="Next", exact=True).click()
    card.get_by_role("textbox", name="Details", exact=True).fill("A separate answer.")
    page.evaluate(
        """(conv) => {
            const H = window.OrchHarness;
            H.unmount('mount-a');
            H.mount('mount-a', 'ElicitationCard', {conversationId: conv, turnId: 'lifecycle-turn'},
                {strictMode: true});
        }""",
        CONVERSATION_ID,
    )
    card.get_by_role("button", name="Back", exact=True).click()
    expect(card.get_by_role("textbox", name="topic", exact=True)).to_have_value("Grounded contracts")
    expect(card.get_by_role("textbox", name="note", exact=True)).to_have_value("")
    expect(card.get_by_text("AI-filled", exact=True)).to_be_visible()
    card.get_by_role("button", name="Sources (1)", exact=True).click()
    expect(card.get_by_role("list", name="Sources for topic", exact=True)).to_contain_text(
        "Authorized evidence for the answer."
    )
    card.get_by_role("button", name="Undo AI fill for topic", exact=True).click()
    expect(card.get_by_role("textbox", name="topic", exact=True)).to_have_value("")
    expect(card.get_by_text("AI-filled", exact=True)).to_have_count(0)
    assert len(fills) == 1
    assert read_inline_lifecycle_draft(page)["editors"]["details"]["text"] == "A separate answer."


if __name__ == "__main__":
    raise SystemExit(pytest.main([str(Path(__file__).resolve()), "-q", *sys.argv[1:]]))
