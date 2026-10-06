# test_v2_collaboration_ux.py
"""
UI test for the V2 shared conversation experience.
Version: 0.261.260
Implemented in: 0.261.255

This test ensures that, in a shared conversation, a message names the people and the agent it
was addressed to as pills above its text instead of repeating "@Name" in it; that the composer's
@ menu adds removable chips (any number of people, one agent, a second agent replacing the first)
and sends them as the mentions the server stores; that running agent requests show as slim
activity lines for everyone instead of a "Thinking" bubble; and that the conversation drawer
lists generated documents (preview and download only where permitted) and every image and clip
in the thread. Only HTTP boundaries are mocked; the real MessageList, Composer, ConversationDrawer
and stores run in Chromium with production CSS.

Build: npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_collaboration_ux.py -q
"""

import base64
import json
import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from test_v2_orchestration_plan_editor import (  # noqa: F401
    HARNESS,
    ORIGIN,
    connect_options,
    editor_assets,
    editor_browser,
)

pytestmark = pytest.mark.ui

CONVERSATION = "shared-response-chat"
ME = {"user_id": "ui-user", "display_name": "Pat Reader", "email": "pat@example.gov"}
SAM = {"user_id": "u-sam", "display_name": "Sam Lee", "email": "sam@example.gov"}
WATCH = {"id": "agent-watch", "name": "watch_officer", "display_name": "Watch Officer", "scope_type": "group"}
CELL = {"id": "agent-cell", "name": "response_cell", "display_name": "Response Cell Officer", "scope_type": "group"}
PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
CAPTURE = f"{ORIGIN}/captures/cap-1.png?exp=1791043200&sig=0a1b2c"
CLIP = f"{ORIGIN}/clips/bridge-7.mp4?exp=1791043200&sig=3d4e5f"
BRIEF_ID = "11111111-2222-3333-4444-555555555555"
WORD_ID = "66666666-7777-8888-9999-000000000000"
BRIEF_MARKDOWN = "# Watch brief\n\nThe van crossed the bridge at **22:15**.\n"


def message(message_id, role, content, sender=None, **extra):
    record = {
        "id": message_id,
        "conversation_id": CONVERSATION,
        "role": role,
        "content": content,
        "timestamp": "2026-10-02T16:12:20Z",
        "metadata": extra.pop("metadata", {}),
        **extra,
    }
    if sender:
        record["sender"] = sender
        record["metadata"] = {**record["metadata"], "sender": sender}
    return record


class CollaborationApi:
    """The HTTP boundary of a shared conversation, with the requests the browser made."""

    def __init__(self, assets):
        self.assets = assets
        self.posts = []
        self.downloads = []
        self.unexpected = []
        self.errors = []

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        base = f"/api/collaboration/conversations/{CONVERSATION}"
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(request.url)
            route.abort()
            return
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
            return
        if path.startswith("/captures/"):
            route.fulfill(status=200, body=PIXEL, content_type="image/png")
            return
        # The drawer's clip tile loads the clip's first frame; an unplayable clip shows as unavailable.
        if path.startswith("/clips/"):
            route.fulfill(status=404, body="Media not found.", content_type="text/plain")
            return
        if request.method == "POST" and path == f"{base}/typing":
            route.fulfill(json={"success": True})
            return
        if request.method == "POST" and path == f"{base}/messages":
            body = json.loads(request.post_data or "{}")
            self.posts.append(body)
            stored = message(
                "posted-1", "user", body.get("content", ""), sender=ME,
                metadata={"mentioned_participants": body.get("mentioned_participants", [])},
            )
            route.fulfill(json={"message": stored})
            return
        if request.method == "GET" and path == f"{base}/generated-documents":
            route.fulfill(json={"documents": [
                {"document_id": BRIEF_ID, "file_name": "Watch brief.md", "workspace_scope": "group",
                 "preview": "markdown", "message_id": "a-1", "created_at": "2026-10-02T16:12:20Z", "can_download": True},
                {"document_id": WORD_ID, "file_name": "Quarterly brief.docx", "workspace_scope": "personal",
                 "preview": None, "message_id": "a-1", "created_at": "2026-10-02T16:12:20Z", "can_download": False},
            ]})
            return
        if request.method == "GET" and path == f"{base}/generated-documents/{BRIEF_ID}/download":
            self.downloads.append(BRIEF_ID)
            route.fulfill(status=200, body=BRIEF_MARKDOWN, content_type="text/markdown", headers={
                "Content-Disposition": 'attachment; filename="Watch brief.md"',
            })
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unmocked request"})


@pytest.fixture
def shared_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1280, "height": 1000}, accept_downloads=True)
    page = context.new_page()
    api = CollaborationApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    try:
        yield page, api
    finally:
        context.close()
        assert not api.unexpected, f"Unexpected browser requests: {api.unexpected}"
        assert not api.errors, api.errors


def mount(page, api, component, messages, *, chat=None, drawer=None):
    page.goto(ORIGIN + HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=ORIGIN + url)
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({ data: {
                version: '0.261.255', settings: {}, branding: { app_title: 'SimpleChat' },
                features: {},
                user: { id: spec.me.user_id, display_name: spec.me.display_name },
                scope: { groups: [], public_workspaces: [] },
                catalogs: { models: [], agents: spec.agents, prompts: [] },
            } });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation, activeConversationKind: 'collaborative',
                conversations: [{ id: spec.conversation, title: 'Response cell', conversation_kind: 'collaborative' }],
                messagesLoading: false, messagesError: null, streaming: false, streamingContent: '',
                streamError: null, thoughts: [], messages: spec.messages,
                drawerMode: spec.drawer, metadata: spec.drawer ? { used_documents: [] } : null,
                ...spec.chat,
            });
            H.stores.collaboration.useCollaborationStore.setState({
                activeConversationId: spec.conversation,
                conversation: {
                    id: spec.conversation, can_post_messages: true, can_manage_members: false,
                    participants: [
                        { ...spec.me, status: 'accepted', membership_status: 'accepted' },
                        { ...spec.sam, status: 'accepted', membership_status: 'accepted' },
                    ],
                },
                replyTo: null, aiRuns: [], typingUsers: [],
            });
            H.mount('test-root', spec.component);
        }""",
        {
            "conversation": CONVERSATION, "me": ME, "sam": SAM, "agents": [WATCH, CELL],
            "messages": messages, "component": component, "chat": chat or {}, "drawer": drawer,
        },
    )


def test_a_message_shows_who_it_was_addressed_to_as_pills(shared_ui):
    page, api = shared_ui
    mount(page, api, "MessageList", [
        message("m-1", "user", "@Watch Officer @Sam Lee where is the van now?", sender=ME, message_kind="ai_request",
                metadata={
                    "mentioned_participants": [SAM],
                    "ai_invocation_target": {"target_type": "agent", "display_name": "Watch Officer",
                                             "mention_text": "@Watch Officer", "source_mode": "explicit_tag"},
                }),
        message("m-2", "user", "@Pat Reader can you confirm the plate?", sender=SAM,
                metadata={"mentioned_participants": [ME]}),
        message("m-3", "user", "No mentions, just  spacing.", sender=SAM),
    ])

    own = page.locator("#message-m-1")
    pills = own.get_by_role("list", name="Addressed to")
    expect(pills.locator("li")).to_have_count(2)
    expect(pills.locator("[data-mention-kind='agent']")).to_contain_text("Watch Officer")
    expect(pills.locator("[data-mention-kind='person']")).to_contain_text("Sam Lee")
    expect(own.get_by_text("Where is the van now?", exact=True)).to_be_visible()
    assert "@" not in own.locator("p").filter(has_text="Where is the van").inner_text()

    mentioned_me = page.locator("#message-m-2")
    expect(mentioned_me.locator("[data-mention-kind='self']")).to_contain_text("Pat Reader")
    expect(mentioned_me.get_by_text("Can you confirm the plate?", exact=True)).to_be_visible()

    plain = page.locator("#message-m-3")
    expect(plain.get_by_role("list", name="Addressed to")).to_have_count(0)
    expect(plain.get_by_text("No mentions, just  spacing.", exact=True)).to_be_visible()


def test_running_agents_show_as_activity_lines_not_a_thinking_bubble(shared_ui):
    page, api = shared_ui
    request = message("m-1", "user", "@Watch Officer status?", sender=ME, metadata={
        "ai_invocation_target": {"target_type": "agent", "display_name": "Watch Officer"},
    })
    mount(page, api, "MessageList", [request], chat={"streaming": True, "streamingContent": "",
                                                       "thoughts": [{"id": "t1", "title": "x", "content": "Invoking OpenApiPlugin.searchEntries"}]})

    activity = page.get_by_role("list", name="AI activity")
    expect(activity.locator("li")).to_have_count(1)
    expect(activity).to_contain_text("Watch Officer is working for you")
    expect(activity).not_to_contain_text("OpenApiPlugin")
    expect(page.get_by_text("Thinking", exact=True)).to_have_count(0)

    page.evaluate(
        """() => {
            const store = window.OrchHarness.stores.collaboration.useCollaborationStore.getState();
            const start = (run) => store.applyAiActivity({ kind: 'started', run, occurredAt: NaN, replayed: false });
            start({ run_id: 'mine', display_name: 'Watch Officer', target_type: 'agent',
                    requested_by: { user_id: 'ui-user', display_name: 'Pat Reader' }, request_message_id: 'm-1' });
            start({ run_id: 'theirs', display_name: 'Response Cell Officer', target_type: 'agent',
                    requested_by: { user_id: 'u-sam', display_name: 'Sam Lee' }, request_message_id: 'm-9' });
            store.applyAiActivity({ kind: 'progress', run: { run_id: 'theirs', step: 'Creating the group' },
                                    occurredAt: NaN, replayed: false });
        }"""
    )
    expect(activity.locator("li")).to_have_count(2)
    expect(activity.locator("[data-ai-run='mine']")).to_contain_text("Watch Officer is working for you")
    expect(activity.locator("[data-ai-run='theirs']")).to_contain_text("Response Cell Officer is working for Sam Lee")
    expect(activity.locator("[data-ai-run='theirs']")).to_contain_text("Creating the group")

    page.evaluate(
        """() => window.OrchHarness.stores.collaboration.useCollaborationStore.getState().applyAiActivity(
            { kind: 'finished', run: { run_id: 'theirs', status: 'completed' }, occurredAt: NaN, replayed: false })"""
    )
    expect(activity.locator("li")).to_have_count(1)

    page.evaluate(
        """() => {
            window.OrchHarness.stores.chat.useChatStore.setState({ streaming: false });
            window.OrchHarness.stores.collaboration.useCollaborationStore.getState()
                .finishAiRunsAnsweredBy({ role: 'assistant', reply_to_message_id: 'm-1' });
        }"""
    )
    expect(page.get_by_role("list", name="AI activity")).to_have_count(0)


def pick_mention(page, query, name):
    box = page.locator("textarea").first
    box.press_sequentially(f"@{query}")
    page.get_by_role("listbox", name="Mention suggestions").get_by_role("option", name=re.compile(name)).click()


def test_composer_mentions_become_chips_and_are_sent_as_mentions(shared_ui):
    page, api = shared_ui
    mount(page, api, "PromptExperience", [])
    box = page.locator("textarea").first
    chips = page.get_by_role("list", name="Sending to")

    pick_mention(page, "Sa", "Sam Lee")
    expect(chips.locator("[data-mention-kind='person']")).to_contain_text("Sam Lee")
    expect(box).to_have_value("")

    pick_mention(page, "Wat", "Watch Officer")
    pick_mention(page, "Resp", "Response Cell Officer")
    expect(chips.locator("[data-mention-kind='agent']")).to_have_count(1)
    expect(chips.locator("[data-mention-kind='agent']")).to_contain_text("Response Cell Officer")

    chips.get_by_role("button", name="Remove Response Cell Officer").click()
    expect(chips.locator("li")).to_have_count(1)

    box.fill("please check the plates")
    box.press("Enter")
    posted = page.locator("#message-posted-1")
    expect(posted).to_be_visible()
    assert len(api.posts) == 1, api.posts
    sent = api.posts[0]
    assert sent["content"] == "@Sam Lee please check the plates", sent
    assert [person["user_id"] for person in sent["mentioned_participants"]] == ["u-sam"], sent

    expect(posted.get_by_role("list", name="Addressed to")).to_contain_text("Sam Lee")
    expect(posted.get_by_text("Please check the plates", exact=True)).to_be_visible()
    expect(page.get_by_role("list", name="Sending to")).to_have_count(0)


def test_drawer_lists_generated_documents_and_media(shared_ui):
    page, api = shared_ui
    reply = message("a-1", "assistant", "\n".join([
        "The brief is ready.",
        f"![Plate capture at the bridge]({CAPTURE})",
        f"[Open video: Bridge camera clip]({CLIP})",
    ]))
    mount(page, api, "ConversationDrawer", [reply], drawer="documents")

    generated = page.get_by_role("region", name="Generated documents")
    expect(generated.locator("[data-generated-document]")).to_have_count(2)
    word = generated.locator(f"[data-generated-document='{WORD_ID}']")
    expect(word).to_contain_text("Download not permitted")
    expect(word.get_by_role("button")).to_have_count(0)

    generated.get_by_role("button", name="Preview Watch brief.md").click()
    dialog = page.get_by_role("dialog", name="Watch brief.md")
    expect(dialog.get_by_role("heading", name="Watch brief", exact=True)).to_be_visible()
    expect(dialog).to_contain_text("The van crossed the bridge at 22:15.")
    with page.expect_download() as download_info:
        dialog.get_by_role("button", name="Download").click()
    assert download_info.value.suggested_filename == "Watch brief.md"
    dialog.get_by_role("button", name="Close", exact=True).first.click()
    expect(page.get_by_role("dialog", name="Watch brief.md")).to_have_count(0)

    media = page.get_by_role("region", name="Media")
    expect(media.get_by_role("button", name="View image: Plate capture at the bridge")).to_be_visible()
    expect(media.get_by_role("button", name=re.compile("Bridge camera clip"))).to_be_visible()
    media.get_by_role("button", name="View image: Plate capture at the bridge").click()
    expect(page.get_by_role("dialog").filter(has_text="Plate capture at the bridge")).to_be_visible()
    assert api.downloads == [BRIEF_ID, BRIEF_ID], api.downloads
