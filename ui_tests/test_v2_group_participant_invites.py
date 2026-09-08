# test_v2_group_participant_invites.py
"""
Browser regression for React v2 group participant invitations.
Version: 0.261.106
Implemented in: 0.261.106
Related issue and backend fix: microsoft/simplechat#1472, #1473.

The real People panel, sharing resolver, chat/collaboration stores and message list
use the actual Flask invite handlers against partition-aware in-memory Cosmos
stores. Only browser transport and external services are controlled. The existing
connection fixture supports local Chromium or a configured Azure Playwright
workspace; neither an application deployment nor live application data is needed.

Run: python .\\ui_tests\\test_v2_group_participant_invites.py
"""

from copy import deepcopy
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

# Resolve the existing browser and isolated backend harnesses for standalone runs.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "ui_tests" / "fixtures" / "orchestration"))
sys.path.insert(0, str(REPO_ROOT / "ui_tests" / "fixtures"))
sys.path.insert(0, str(REPO_ROOT / "functional_tests"))
import harness_build as hb  # noqa: E402
from playwright_connection import connect_options  # noqa: E402,F401
from test_group_collaboration_source_storage_fix import (  # noqa: E402
    COLLABORATION_FILE,
    GROUP_ID,
    INVITEE,
    OWNER,
    SECOND_INVITEE,
    SOURCE_ID,
    ConversionHarness,
    history_fixture,
    load_source_members,
)


pytestmark = pytest.mark.ui
DIRECTORY_USER = {
    "user_id": "directory-user",
    "display_name": "Directory Colleague",
    "email": "colleague@example.com",
}


class ParticipantApi:
    """Dispatch invitation writes to the real routes and serve their stored results."""

    def __init__(self, storage):
        self.backend = ConversionHarness(storage, history=False)
        self.initial_source = deepcopy(self.backend.source.items[SOURCE_ID])
        self.backend.messages.items.update({
            message["id"]: message
            for message in history_fixture()
            if message["role"] in ("user", "assistant")
        })
        self.requests = []
        self.unexpected = []
        self.expected_errors = set()
        self.fail_member_search = False
        helpers = load_source_members(
            str(COLLABORATION_FILE),
            {"serialize_collaboration_message", "_get_collaboration_display_role"},
            namespace=self.backend.namespace,
        )
        self.serialize_message = helpers["serialize_collaboration_message"]

    def conversations(self):
        return [
            self.backend.namespace["serialize_collaboration_conversation"](
                conversation,
                current_user_id=OWNER["user_id"],
            )
            for conversation in self.backend.containers["collaboration_conversations"].items.values()
        ]

    def handle(self, route):
        request = route.request
        url = urlsplit(request.url)
        path = url.path
        self.requests.append((request.method, path))

        if request.method == "POST" and re.fullmatch(
            r"/api/collaboration/conversations/(?:from-group/|from-personal/)?[^/]+/members",
            path,
        ):
            response = self.backend.post(request.post_data_json, path)
            if response.status_code >= 400:
                self.expected_errors.add((path, response.status_code))
            route.fulfill(status=response.status_code, json=response.get_json())
            return

        if path == "/api/user/settings" and request.method == "POST":
            route.fulfill(json={"message": "Settings saved"})
            return

        if request.method == "GET":
            if path == f"/api/groups/{GROUP_ID}/members":
                if self.fail_member_search:
                    self.expected_errors.add((path, 403))
                    route.fulfill(status=403, json={"error": "Group membership is required."})
                else:
                    query = parse_qs(url.query).get("search", [""])[0].casefold()
                    route.fulfill(json=[
                        member for member in self.backend.group["users"]
                        if query in f"{member['displayName']} {member['email']}".casefold()
                    ])
                return
            if path == "/api/user/collaboration-suggestions":
                route.fulfill(json={"results": [DIRECTORY_USER]})
                return
            if path == "/api/conversations/feed":
                route.fulfill(json={
                    "success": True,
                    "conversations": self.conversations(),
                    "has_more": False,
                    "next_cursor": None,
                })
                return
            for conversation in self.conversations():
                base = f"/api/collaboration/conversations/{conversation['id']}"
                if path == base:
                    route.fulfill(json={"conversation": conversation})
                    return
                if path == f"{base}/messages":
                    route.fulfill(json={"messages": [
                        self.serialize_message(message)
                        for message in self.backend.containers["collaboration_messages"].items.values()
                        if message["conversation_id"] == conversation["id"]
                    ]})
                    return
                if path == f"{base}/events":
                    route.fulfill(content_type="text/event-stream", body=": connected\n\n")
                    return

        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected test endpoint."})


@pytest.fixture
def participant_page(page, request):
    hb.ensure_bundle()
    api = ParticipantApi(getattr(request, "param", "regular"))
    errors = []

    def handle(route):
        path = urlsplit(route.request.url).path
        if path == "/harness.html":
            route.fulfill(
                content_type="text/html",
                body=(hb.HERE / "harness.html").read_text(encoding="utf-8"),
            )
        elif path == "/harness.bundle.js":
            route.fulfill(
                content_type="application/javascript",
                body=hb.BUNDLE.read_text(encoding="utf-8"),
            )
        elif path == "/favicon.ico":
            route.fulfill(status=204)
        else:
            api.handle(route)

    def record_console(message):
        if message.type != "error":
            return
        path = urlsplit(message.location.get("url", "")).path
        if message.text.startswith("Failed to load resource:") and any(
            path == expected_path and f"status of {status}" in message.text
            for expected_path, status in api.expected_errors
        ):
            return
        errors.append(message.text)

    page.route("**/*", handle)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", record_console)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto("http://simplechat.test/harness.html")
    page.wait_for_function('() => typeof window.OrchHarness === "object"')
    try:
        yield page, api
    finally:
        page.evaluate("""async () => {
            const H = window.OrchHarness;
            await H.stores.userSettings.useUserSettingsStore.getState().flush();
            await H.stores.chat.useChatStore.getState().selectConversation(null);
            H.reset();
        }""")
        assert not api.unexpected, f"Unexpected requests: {api.unexpected}"
        assert not errors, f"Browser errors: {errors}"


def open_panel(page, conversation, *, mount=False):
    page.evaluate(
        """({ conversation, mount, owner }) => {
            const H = window.OrchHarness;
            if (mount) {
                H.reset();
                H.stores.collaboration.useCollaborationStore.getState().reset();
                H.stores.bootstrap.useBootstrapStore.setState({
                    data: {
                        features: { enable_collaborative_conversations: true },
                        catalogs: { models: [], agents: [], prompts: [] },
                        settings: {},
                        user: { id: owner.user_id, display_name: owner.display_name },
                        scope: { active_group_id: 'unrelated-active-group' },
                    },
                });
                H.stores.chat.useChatStore.setState({
                    activeConversationId: conversation.id,
                    activeConversationKind: 'personal',
                    conversations: [conversation],
                    metadata: { ...conversation, conversation_id: conversation.id },
                    messages: [],
                    messagesLoading: false,
                });
                H.mount('test-root', 'ParticipantsPanel', {});
                H.mount('mount-a', 'MessageList', {});
                H.mount('mount-b', 'Toaster', {});
            }
            H.stores.collaboration.useCollaborationStore.getState().openPanel(
                H.sharing.panelTargetForConversation(conversation.id, conversation),
            );
        }""",
        {"conversation": conversation, "mount": mount, "owner": OWNER},
    )


def expect_shared_history(page, conversation_id):
    page.wait_for_function(
        """(id) => {
            const state = window.OrchHarness.stores.chat.useChatStore.getState();
            return state.activeConversationId === id
                && state.activeConversationKind === 'collaborative'
                && state.messages.length === 2
                && state.messages.every(message => message.conversation_id === id);
        }""",
        arg=conversation_id,
    )
    expect(page.get_by_text("Review the group runbook.", exact=True)).to_be_visible()
    expect(page.get_by_text("Runbook response.", exact=True)).to_be_visible()


@pytest.mark.parametrize("participant_page", ["regular", "group"], indirect=True)
def test_group_invites_preserve_history_and_use_the_shared_id_after_conversion(participant_page):
    page, api = participant_page
    open_panel(page, api.initial_source, mount=True)
    expect(page.get_by_placeholder("Search group members")).to_be_visible()
    page.get_by_role("button", name=re.compile(INVITEE["display_name"])).click()
    expect(page.get_by_role("status").filter(has_text="Group Member was invited.")).to_be_visible()
    conversation = api.conversations()[0]
    expect_shared_history(page, conversation["id"])
    assert api.backend.source.items[SOURCE_ID]["is_hidden"]

    open_panel(page, conversation)
    expect(page.get_by_role("heading", name="People in this conversation")).to_be_visible()
    page.get_by_role("button", name=re.compile(SECOND_INVITEE["display_name"])).click()
    expect(page.get_by_role("status").filter(has_text="Second Member was invited.")).to_be_visible()

    invitation_paths = [
        path for method, path in api.requests
        if method == "POST" and path.endswith("/members")
    ]
    assert invitation_paths == [
        f"/api/collaboration/conversations/from-group/{SOURCE_ID}/members",
        f"/api/collaboration/conversations/{conversation['id']}/members",
    ]
    assert len(api.conversations()) == 1
    assert api.conversations()[0]["pending_invite_count"] == 2
    assert ("GET", "/api/user/collaboration-suggestions") not in api.requests
    expect(page.get_by_role("alert")).to_have_count(0)


def test_invite_failure_keeps_the_original_target_and_allows_retry(participant_page):
    page, api = participant_page
    del api.backend.source.items[SOURCE_ID]
    open_panel(page, api.initial_source, mount=True)
    page.get_by_role("button", name=re.compile(INVITEE["display_name"])).click()
    expect(page.get_by_role("alert")).to_have_text("Conversation not found")
    expect(page.get_by_role("dialog", name="Conversation participants")).to_be_visible()
    expect(page.get_by_role("status")).to_have_count(0)
    assert not api.conversations()
    assert page.evaluate(
        "() => window.OrchHarness.stores.collaboration.useCollaborationStore.getState().panelTarget.conversationId"
    ) == SOURCE_ID

    api.backend.source.items[SOURCE_ID] = deepcopy(api.initial_source)
    page.get_by_role("button", name=re.compile(INVITEE["display_name"])).click()
    expect(page.get_by_role("status").filter(has_text="Group Member was invited.")).to_be_visible()
    expect_shared_history(page, api.conversations()[0]["id"])


def test_missing_group_identity_does_not_fall_back_to_directory_search(participant_page):
    page, api = participant_page
    conversation = {**api.initial_source, "context": []}
    open_panel(page, conversation, mount=True)
    expect(page.get_by_role("alert")).to_contain_text("group could not be identified")
    expect(page.get_by_role("textbox", name="Search for people to add")).to_have_count(0)
    assert not api.requests


def test_group_search_denial_is_visible_without_directory_fallback(participant_page):
    page, api = participant_page
    api.fail_member_search = True
    open_panel(page, api.initial_source, mount=True)
    expect(page.get_by_text("Group membership is required.", exact=True)).to_be_visible()
    assert ("GET", "/api/user/collaboration-suggestions") not in api.requests
    assert not api.conversations()


def test_personal_invites_keep_the_personal_conversion_path(participant_page):
    page, api = participant_page
    source = api.backend.source.items[SOURCE_ID]
    source.update({
        "chat_type": "personal_single_user",
        "context": [{"type": "primary", "scope": "personal", "id": OWNER["user_id"]}],
    })
    open_panel(page, source, mount=True)
    expect(page.get_by_placeholder("Search people")).to_be_visible()
    page.get_by_role("button", name=re.compile(DIRECTORY_USER["display_name"])).click()
    expect(page.get_by_role("status").filter(has_text="Directory Colleague was invited.")).to_be_visible()
    conversation = api.conversations()[0]
    expect_shared_history(page, conversation["id"])
    assert conversation["chat_type"] == "personal_multi_user"
    assert ("POST", f"/api/collaboration/conversations/from-personal/{SOURCE_ID}/members") in api.requests
    assert not any(path.startswith("/api/groups/") for _, path in api.requests)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
