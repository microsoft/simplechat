# test_v2_scope_lock.py
"""
Browser regressions for locking and unlocking a conversation's workspace scope in the V2 chat.
Version: 0.261.448
Implemented in: 0.261.448

V2 drew a conversation's scope lock in the chat header and gave no way to change it. The lock is
now a button that opens a dialog, reachable from the header, the conversation details and the
Documents picker, with classic's wording and rules: locking is always allowed, unlocking is refused
while the administrator enforces the lock, a personal conversation is changed by its owner and a
shared one by anyone who can post in it.

Exercises the real chat page, composer, picker, details, stores and toaster, bundled by
fixtures/scope_lock. Only HTTP answers are replaced; no live application data is read or modified.
"""

import json
import mimetypes
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Imported through the package: a bare `harness_build` would collide with the orchestration
# fixture module of the same name when both suites run in one session.
from ui_tests.fixtures.agent_delegation.harness_build import ensure_bundle  # noqa: E402
from ui_tests.fixtures.playwright_connection import connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui

FIXTURE = ROOT / "ui_tests" / "fixtures" / "scope_lock"
BUNDLE = FIXTURE / "harness.bundle.js"
STATIC = ROOT / "application" / "single_app" / "static"
ORIGIN = "https://simplechat.test"
CONVERSATION = "conv-lock"
SHARED = "collab-lock"
GROUP = "group-1"
MARKETING = {"scope": "group", "id": GROUP}
LOCKED_LABEL = "Workspace scope is locked. Review or unlock it."
UNLOCKED_LABEL = "Workspace scope is unlocked. Review or lock it."
LOCKED_VIEW_LABEL = "Workspace scope is locked. View details."
UNENFORCED_403 = "Scope unlock is disabled by administrator"


def metadata(conversation_id=CONVERSATION, **extra):
    """The conversation as GET /api/conversations/<id>/metadata returns it."""
    record = {
        "conversation_id": conversation_id,
        "title": "Quarterly plan",
        "user_id": "user-1",
        "last_updated": "2025-06-02T15:00:00Z",
        "classification": [],
        "context": [{"type": "primary", "scope": "group", "id": GROUP, "name": "Marketing"}],
        "tags": [],
        "strict": False,
        "is_pinned": False,
        "is_hidden": False,
        "scope_locked": True,
        "locked_contexts": [dict(MARKETING)],
        "chat_type": "group-single-user",
        "summary": None,
        "linked_workspace_documents": [],
    }
    record.update(extra)
    return record


def shared_conversation(**extra):
    """A shared conversation as GET /api/collaboration/conversations/<id> serializes it."""
    record = {
        "id": SHARED,
        "title": "Team plan",
        "conversation_kind": "collaborative",
        "chat_type": "group_multi_user",
        "created_at": "2025-06-02T15:00:00Z",
        "updated_at": "2025-06-02T15:00:00Z",
        "last_updated": "2025-06-02T15:00:00Z",
        "membership_status": "accepted",
        "current_user_role": "member",
        "can_post_messages": True,
        "can_manage_members": False,
        "can_manage_roles": False,
        "can_accept_invite": False,
        "can_delete_conversation": False,
        "can_leave_conversation": True,
        "participants": [],
        "participant_count": 1,
        "pending_invite_count": 0,
        "context": [{"type": "primary", "scope": "group", "id": GROUP, "name": "Marketing"}],
        "scope_locked": True,
        "locked_contexts": [dict(MARKETING)],
        "group_id": GROUP,
        "group_name": "Marketing",
        "user_id": "creator-1",
        "tags": [],
        "classification": [],
        "is_pinned": False,
        "is_hidden": False,
    }
    record.update(extra)
    return record


class ScopeLockApi:
    """The routes the chat page calls, answered the way route_backend_* answers, with their state."""

    def __init__(self, page, record=None, *, shared=False):
        self.page = page
        self.shared = shared
        self.record = record if record is not None else (shared_conversation() if shared else metadata())
        self.conversation_id = self.record.get("id") or self.record.get("conversation_id")
        # What the server does with the next lock change, and what it tells the browser.
        self.enforced = False
        self.fail_next = None
        self.hold_patch = False
        self.held = []
        self.patches = []
        self.metadata_reads = 0
        self.source_queries = []
        self.requests = []
        self.errors = []
        self.unexpected = []
        self.expected_http_failures = set()

    # Routing ----------------------------------------------------------------------------------

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        method = request.method
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(f"{method} {request.url}")
            route.abort()
            return
        path = parsed.path
        self.requests.append((method, path))
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        for answer in (self.page_route, self.lock_route, self.conversation_route, self.other_route):
            if answer(route, method, path, query):
                return
        self.unexpected.append(f"{method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def page_route(self, route, method, path, query):
        if method != "GET":
            return False
        if path == "/harness.html":
            route.fulfill(path=str(FIXTURE / "harness.html"), content_type="text/html")
        elif path == "/harness.bundle.js":
            route.fulfill(path=str(BUNDLE), content_type="application/javascript")
        elif path == "/favicon.ico":
            route.fulfill(status=204, body="")
        elif path.startswith("/static/"):
            asset = (STATIC / path.removeprefix("/static/")).resolve()
            if not (asset.is_relative_to(STATIC.resolve()) and asset.is_file()):
                return False
            route.fulfill(path=str(asset), content_type=mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
        else:
            return False
        return True

    def lock_route(self, route, method, path, query):
        match = re.fullmatch(r"/api/conversations/([^/]+)/scope_lock", path)
        if not match or method != "PATCH":
            return False
        conversation_id = unquote(match.group(1))
        body = route.request.post_data_json
        self.patches.append({"path": path, "id": conversation_id, "body": body})
        if self.hold_patch:
            self.held.append((route, conversation_id, body))
        else:
            self.answer_patch(route, conversation_id, body)
        return True

    def answer_patch(self, route, conversation_id, body):
        path = f"/api/conversations/{conversation_id}/scope_lock"
        if self.fail_next:
            status, error = self.fail_next
            self.fail_next = None
            self.expected_http_failures.add((path, status))
            route.fulfill(status=status, json={"error": error})
            return
        wanted = body.get("scope_locked") if isinstance(body, dict) else None
        if wanted not in (True, False):
            self.expected_http_failures.add((path, 400))
            route.fulfill(status=400, json={"error": "scope_locked must be true or false"})
            return
        if wanted is False and self.enforced:
            self.expected_http_failures.add((path, 403))
            route.fulfill(status=403, json={"error": UNENFORCED_403})
            return
        self.record["scope_locked"] = wanted
        route.fulfill(json={
            "success": True,
            "scope_locked": wanted,
            "locked_contexts": list(self.record.get("locked_contexts", [])),
        })

    def release(self):
        assert self.held, "No scope lock request was held."
        route, conversation_id, body = self.held.pop(0)
        self.answer_patch(route, conversation_id, body)

    def conversation_route(self, route, method, path, query):
        if method == "GET" and path == "/api/conversations/feed":
            route.fulfill(json={
                "success": True, "conversations": [{
                    "id": self.conversation_id, "title": self.record["title"], "last_updated": "2025-06-02T15:00:00Z",
                    "has_unread_assistant_response": False, "is_pinned": False, "is_hidden": False,
                    **({"conversation_kind": "collaborative"} if self.shared else {}),
                }], "has_more": False, "next_cursor": None,
                "page_size": int(query.get("page_size", 50)), "hidden_count": 0, "priority_count": 0,
                "recent_count": 1, "source_offsets": {},
            })
        elif method == "GET" and (match := re.fullmatch(r"/api/conversations/([^/]+)/kind", path)):
            route.fulfill(json={"conversation_id": unquote(match.group(1)), "kind": "collaborative" if self.shared else "personal"})
        elif method == "GET" and re.fullmatch(r"/api/conversations/([^/]+)/metadata", path):
            self.metadata_reads += 1
            route.fulfill(json=dict(self.record))
        elif method == "GET" and re.fullmatch(r"/api/collaboration/conversations/([^/]+)", path):
            self.metadata_reads += 1
            route.fulfill(json={"conversation": dict(self.record)})
        elif method == "GET" and path in ("/api/get_messages", f"/api/collaboration/conversations/{SHARED}/messages"):
            route.fulfill(json={"messages": []})
        elif method == "GET" and path == "/api/v2/document-sources":
            self.source_queries.append(query)
            route.fulfill(json=self.sources_page())
        else:
            return False
        return True

    def sources_page(self):
        """The workspace directory, narrowed to the lock the way source_catalog narrows it."""
        marketing = {"kind": "group", "id": GROUP, "name": "Marketing", "key": f"group:{GROUP}", "document_count": 3, "match_reason": None}
        personal = {"kind": "personal", "id": None, "name": "My workspace", "key": "personal", "document_count": 5, "match_reason": None}
        workspaces = [marketing] if self.record.get("scope_locked") else [personal, marketing]
        return {
            "browsed_workspace": None, "workspaces": workspaces, "eligible_workspace_count": len(workspaces),
            "matching_workspace_count": len(workspaces), "workspace_next": None, "documents": [], "tags": [],
            "source_total": 0, "source_next": None, "complete": True,
        }

    def other_route(self, route, method, path, query):
        if method == "GET" and re.fullmatch(r"/api/chat/stream/status/[^/]+", path):
            route.fulfill(json={"active": False, "pending": False, "reattachable": False})
        elif method == "GET" and path == "/api/v2/orchestration/runs":
            route.fulfill(json={"runs": []})
        elif method == "GET" and path == "/api/msgraph/pending-actions":
            route.fulfill(json={"success": True, "pending_actions": [], "continuation_token": ""})
        elif method == "GET" and path == "/api/collaboration/file-approvals":
            route.fulfill(json={"approvals": []})
        elif method == "GET" and path == "/api/v2/orchestration/questions":
            route.fulfill(json={"questions": []})
        elif method == "GET" and path == "/api/action-credentials/pending":
            route.fulfill(json={"requests": [], "csrf_token": "csrf"})
        elif method == "GET" and path == "/api/v2/user-input/pending":
            route.fulfill(json={"requests": [], "csrf_token": "csrf"})
        elif method == "POST" and path == "/api/user/settings":
            route.fulfill(json={"message": "User settings updated successfully"})
        elif method == "POST" and re.fullmatch(r"/api/(collaboration/)?conversations/[^/]+/mark-read", path):
            route.fulfill(json={"success": True})
        else:
            return False
        return True


SEED = r"""
(seed) => {
    const H = window.ScopeLockHarness;
    H.stores.bootstrap.useBootstrapStore.setState({
        data: {
            version: '0.261.448',
            user: {id: 'user-1', display_name: 'Riley Chen', roles: []},
            features: seed.features,
            branding: {app_title: 'Contoso Chat'},
            settings: seed.settings,
            scope: {
                groups: [{id: 'group-1', name: 'Marketing'}],
                public_workspaces: [],
                active_group_id: null,
                active_group_name: null,
                active_public_workspace_id: null,
            },
            catalogs: {models: [], agents: [], prompts: []},
        },
        loading: false,
        error: null,
    });
    H.stores.userSettings.useUserSettingsStore.setState({settings: {}, loading: false, error: null});
    H.stores.ui.useUiStore.setState({railCollapsed: false, mobileNavOpen: false});
    H.stores.chat.useChatStore.setState({
        activeConversationId: seed.id,
        activeConversationKind: seed.kind,
        conversations: [{id: seed.id, title: seed.metadata.title, has_unread_assistant_response: false,
            ...(seed.kind === 'collaborative' ? {conversation_kind: 'collaborative'} : {})}],
        messages: [],
        streaming: false,
        messagesLoading: false,
        metadata: seed.metadata,
        metadataLoading: false,
        metadataError: null,
    });
    if (seed.kind === 'collaborative') {
        H.stores.collaboration.useCollaborationStore.setState({conversation: seed.metadata, activeConversationId: seed.id});
    }
    H.mount('/chat');
}
"""


class Harness(ScopeLockApi):
    """The chat page in a browser, driven the way a reader drives it."""

    def __init__(self, page, stylesheets, record=None, *, shared=False):
        super().__init__(page, record, shared=shared)
        self.stylesheets = stylesheets

    def open(self, *, enforce=None):
        """Mount the page. `enforce` is what bootstrap says; the server's own state is `self.enforced`."""
        self.page.route("**/*", self.handle)
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("console", self.record_console)
        self.page.goto(f"{ORIGIN}/harness.html")
        for stylesheet in self.stylesheets:
            self.page.add_style_tag(path=str(stylesheet))
        enforce = self.enforced if enforce is None else enforce
        # A shared conversation is mapped onto the metadata shape when it loads, keyed as
        # `conversation_id`; seeding it unmapped would not be what the page ever holds.
        seeded = dict(self.record)
        if self.shared:
            seeded["conversation_id"] = seeded["id"]
        self.page.evaluate(SEED, {
            "id": self.conversation_id,
            "kind": "collaborative" if self.shared else "personal",
            "metadata": seeded,
            "features": {
                "enable_user_workspace": True,
                "enable_group_workspaces": True,
                "enable_public_workspaces": False,
                "enable_collaborative_conversations": True,
            },
            "settings": {"enforce_workspace_scope_lock": enforce},
        })
        expect(self.page.get_by_role("heading", name=self.record["title"])).to_be_visible()

    def record_console(self, message):
        if message.type != "error":
            return
        path = urlsplit(message.location.get("url", "")).path
        status = re.search(r"^Failed to load resource: the server responded with a status of (\d+)", message.text)
        if status and (path, int(status.group(1))) in self.expected_http_failures:
            return
        self.errors.append(message.text)

    # Waiting ----------------------------------------------------------------------------------

    def wait_for(self, predicate, message, timeout=5.0):
        """Poll from the test thread, so held routes keep being answered meanwhile."""
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError(message)
            self.page.wait_for_timeout(50)

    # Reading the page -------------------------------------------------------------------------

    @property
    def header_lock(self):
        return self.page.locator("[data-scope-lock-state]")

    @property
    def dialog(self):
        return self.page.get_by_role("dialog")

    def lock_fields(self):
        return self.page.evaluate("""() => {
            const metadata = window.ScopeLockHarness.stores.chat.useChatStore.getState().metadata;
            return {scope_locked: metadata.scope_locked, locked_contexts: metadata.locked_contexts};
        }""")

    def toast(self, text):
        return self.page.get_by_role("status").filter(has_text=text)

    def alert(self, text):
        return self.page.get_by_role("alert").filter(has_text=text)

    def no_horizontal_scroll(self):
        return self.page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")


@pytest.fixture(scope="module")
def harness_assets():
    index = STATIC / "v2" / "index.html"
    assert index.is_file(), "Build the V2 SPA first: cd application/v2_ui; npx vite build"
    hrefs = re.findall(r'<link\b[^>]*href="([^"]+\.css)"', index.read_text(encoding="utf-8"))
    stylesheets = [STATIC / href.removeprefix("/static/") for href in hrefs]
    assert stylesheets and all(sheet.is_file() for sheet in stylesheets), stylesheets
    ensure_bundle(entry=FIXTURE / "harness_entry.tsx", bundle=BUNDLE)
    yield stylesheets
    BUNDLE.unlink(missing_ok=True)


@pytest.fixture
def make_harness(page, harness_assets):
    created = []

    def make(record=None, *, shared=False):
        api = Harness(page, harness_assets, record, shared=shared)
        created.append(api)
        return api

    yield make
    for api in created:
        # The requests nobody answered come first: they are the usual cause of a console 404.
        assert not api.unexpected, api.unexpected
        assert not api.errors, api.errors


# The lock button and its dialog ---------------------------------------------------------------


def test_a_locked_conversation_offers_to_unlock_in_a_dialog_that_says_what_it_does(make_harness):
    harness = make_harness()
    harness.open(enforce=False)

    expect(harness.header_lock).to_have_attribute("aria-label", LOCKED_LABEL)
    expect(harness.header_lock).to_have_attribute("aria-haspopup", "dialog")
    harness.header_lock.click()

    dialog = harness.dialog
    expect(dialog).to_have_accessible_name("Unlock workspace scope")
    expect(dialog).to_contain_text("prevent accidental cross-contamination")
    expect(dialog).to_contain_text("Currently locked to:")
    expect(dialog.get_by_role("list", name="Workspaces").get_by_role("listitem")).to_have_text(["Marketing"])
    expect(dialog).to_contain_text("Unlocking lets you choose any workspace for this conversation")
    expect(dialog.get_by_role("button", name="Cancel")).to_be_enabled()
    expect(dialog.get_by_role("button", name="Unlock scope")).to_be_enabled()
    assert not harness.patches, "Opening the dialog changes nothing"

    dialog.get_by_role("button", name="Cancel").click()
    expect(harness.dialog).to_have_count(0)
    assert not harness.patches, "Cancelling changes nothing"
    expect(harness.header_lock).to_have_attribute("aria-label", LOCKED_LABEL)


def test_unlocking_answers_the_press_at_once_and_is_confirmed_by_the_server(make_harness):
    harness = make_harness()
    harness.open(enforce=False)
    harness.hold_patch = True
    harness.header_lock.click()
    harness.dialog.get_by_role("button", name="Unlock scope").click()

    # The request is out and unanswered; the header already shows the unlocked state.
    harness.wait_for(lambda: harness.patches, "The unlock request was not sent.")
    assert harness.patches == [{"path": f"/api/conversations/{CONVERSATION}/scope_lock", "id": CONVERSATION, "body": {"scope_locked": False}}]
    expect(harness.header_lock).to_have_attribute("aria-label", UNLOCKED_LABEL)
    assert harness.lock_fields()["scope_locked"] is False
    # The dialog keeps the wording it opened with, and cannot be pressed twice.
    expect(harness.dialog).to_have_accessible_name("Unlock workspace scope")
    expect(harness.dialog.get_by_role("button", name="Unlock scope")).to_be_disabled()
    expect(harness.dialog.get_by_role("button", name="Cancel")).to_be_disabled()
    reads = harness.metadata_reads

    harness.hold_patch = False
    harness.release()
    expect(harness.toast("Workspace scope unlocked.")).to_be_visible()
    expect(harness.dialog).to_have_count(0)
    harness.wait_for(lambda: harness.metadata_reads > reads, "The conversation was not read again after the change.")
    expect(harness.header_lock).to_have_attribute("aria-label", UNLOCKED_LABEL)
    fields = harness.lock_fields()
    assert fields["scope_locked"] is False
    assert fields["locked_contexts"] == [MARKETING], "Unlocking keeps the workspaces, so locking again returns to them"
    assert len(harness.patches) == 1


def test_a_refusal_puts_the_lock_back_and_explains_inside_the_dialog(make_harness):
    harness = make_harness()
    harness.open(enforce=False)
    # Bootstrap is stale: it says the lock is free, the server says it is enforced.
    harness.enforced = True
    harness.header_lock.click()
    harness.dialog.get_by_role("button", name="Unlock scope").click()

    expect(harness.alert(UNENFORCED_403)).to_be_visible()
    expect(harness.dialog).to_have_accessible_name("Unlock workspace scope")
    expect(harness.header_lock).to_have_attribute("aria-label", LOCKED_LABEL)
    assert harness.lock_fields()["scope_locked"] is True, "Rolled back"
    assert harness.lock_fields()["locked_contexts"] == [MARKETING]
    expect(harness.toast("Workspace scope unlocked.")).to_have_count(0)
    expect(harness.dialog.get_by_role("button", name="Unlock scope")).to_be_enabled()

    # Try again once the server allows it: the same dialog completes the change.
    harness.enforced = False
    harness.dialog.get_by_role("button", name="Unlock scope").click()
    expect(harness.toast("Workspace scope unlocked.")).to_be_visible()
    expect(harness.dialog).to_have_count(0)
    expect(harness.header_lock).to_have_attribute("aria-label", UNLOCKED_LABEL)
    assert [patch["body"] for patch in harness.patches] == [{"scope_locked": False}, {"scope_locked": False}]


def test_a_server_error_is_reported_and_the_state_is_not_left_changed(make_harness):
    harness = make_harness()
    harness.open(enforce=False)
    harness.fail_next = (500, "Failed to update scope lock")
    harness.header_lock.click()
    harness.dialog.get_by_role("button", name="Unlock scope").click()

    expect(harness.alert("Failed to update scope lock")).to_be_visible()
    expect(harness.header_lock).to_have_attribute("aria-label", LOCKED_LABEL)
    assert harness.lock_fields()["scope_locked"] is True
    harness.dialog.get_by_role("button", name="Cancel").click()
    expect(harness.dialog).to_have_count(0)


def test_an_enforced_lock_can_be_read_but_not_unlocked(make_harness):
    harness = make_harness()
    harness.enforced = True
    harness.open(enforce=True)

    expect(harness.header_lock).to_have_attribute("aria-label", LOCKED_VIEW_LABEL)
    harness.header_lock.click()
    dialog = harness.dialog
    expect(dialog).to_have_accessible_name("Workspace scope is locked")
    expect(dialog).to_contain_text("Workspace scope lock is enforced by your administrator. The scope cannot be unlocked.")
    expect(dialog.get_by_role("list", name="Workspaces").get_by_role("listitem")).to_have_text(["Marketing"])
    expect(dialog.get_by_role("button", name=re.compile("Unlock"))).to_have_count(0)
    dialog.get_by_role("button", name="Done").click()
    expect(harness.dialog).to_have_count(0)
    assert not harness.patches, "An enforced lock sends no request at all"


def test_locking_is_still_offered_while_the_lock_is_enforced(make_harness):
    harness = make_harness(metadata(scope_locked=False))
    harness.enforced = True
    harness.open(enforce=True)

    expect(harness.header_lock).to_have_attribute("aria-label", UNLOCKED_LABEL)
    harness.header_lock.click()
    expect(harness.dialog).to_have_accessible_name("Lock workspace scope")
    expect(harness.dialog).to_contain_text("Will lock to:")
    expect(harness.dialog).to_contain_text("Locking limits the Documents picker to the workspaces listed above")
    harness.dialog.get_by_role("button", name="Lock scope").click()

    expect(harness.toast("Workspace scope locked.")).to_be_visible()
    assert harness.patches[-1]["body"] == {"scope_locked": True}
    expect(harness.header_lock).to_have_attribute("aria-label", LOCKED_VIEW_LABEL)
    assert harness.lock_fields()["scope_locked"] is True


def test_a_conversation_with_no_lock_state_draws_no_control(make_harness):
    harness = make_harness(metadata(scope_locked=None, locked_contexts=[]))
    harness.open(enforce=False)

    expect(harness.page.get_by_role("button", name="View conversation details")).to_be_visible()
    expect(harness.header_lock).to_have_count(0)
    harness.page.get_by_role("button", name="View conversation details").click()
    expect(harness.page.get_by_role("dialog", name="Conversation details")).to_be_visible()
    expect(harness.page.get_by_text("Workspace scope", exact=True)).to_have_count(0)


def test_an_unlocked_conversation_with_nothing_recorded_cannot_be_locked_to_nothing(make_harness):
    harness = make_harness(metadata(scope_locked=False, locked_contexts=[], context=[]))
    harness.open(enforce=False)

    harness.header_lock.click()
    expect(harness.dialog).to_have_accessible_name("Workspace scope is unlocked")
    expect(harness.dialog).to_contain_text("nothing to lock it to")
    expect(harness.dialog.get_by_role("button", name=re.compile("Lock scope"))).to_have_count(0)
    assert not harness.patches


# Shared conversations ------------------------------------------------------------------------


def test_a_shared_conversation_is_changed_through_the_same_route_by_a_participant(make_harness):
    harness = make_harness(shared=True)
    harness.open(enforce=False)

    harness.header_lock.click()
    harness.dialog.get_by_role("button", name="Unlock scope").click()
    expect(harness.toast("Workspace scope unlocked.")).to_be_visible()
    assert harness.patches == [{"path": f"/api/conversations/{SHARED}/scope_lock", "id": SHARED, "body": {"scope_locked": False}}]
    # A shared conversation is read back from its own endpoint.
    harness.wait_for(lambda: ("GET", f"/api/collaboration/conversations/{SHARED}") in harness.requests,
                     "The shared conversation was not read again.")
    expect(harness.header_lock).to_have_attribute("aria-label", UNLOCKED_LABEL)


def test_someone_who_cannot_post_in_a_shared_conversation_can_only_read_its_lock(make_harness):
    harness = make_harness(shared_conversation(can_post_messages=False, membership_status="pending", can_accept_invite=True), shared=True)
    harness.open(enforce=False)

    expect(harness.header_lock).to_have_attribute("aria-label", LOCKED_VIEW_LABEL)
    harness.header_lock.click()
    expect(harness.dialog).to_contain_text("Only people who can post in this conversation can change its workspace scope.")
    expect(harness.dialog.get_by_role("button", name=re.compile("Unlock"))).to_have_count(0)
    assert not harness.patches


def test_a_personal_conversation_owned_by_someone_else_is_read_only(make_harness):
    harness = make_harness(metadata(user_id="someone-else"))
    harness.open(enforce=False)

    expect(harness.header_lock).to_have_attribute("aria-label", LOCKED_VIEW_LABEL)
    harness.header_lock.click()
    expect(harness.dialog).to_contain_text("Only the owner of this conversation can change its workspace scope.")
    assert not harness.patches


# Other surfaces -------------------------------------------------------------------------------


def test_the_conversation_details_show_the_lock_and_share_the_dialog(make_harness):
    harness = make_harness()
    harness.open(enforce=False)

    harness.page.get_by_role("button", name="View conversation details").click()
    details = harness.page.get_by_role("dialog", name="Conversation details")
    expect(details).to_be_visible()
    row = details.locator("dt", has_text="Workspace scope").locator("xpath=following-sibling::dd")
    expect(row).to_contain_text("Locked")
    expect(row).to_contain_text("Marketing")
    row.get_by_role("button", name="Unlock workspace scope").click()
    expect(harness.page.get_by_role("dialog", name="Unlock workspace scope")).to_be_visible()

    # Escape closes the dialog on top and leaves the details the reader was reading.
    harness.page.keyboard.press("Escape")
    expect(harness.page.get_by_role("dialog", name="Unlock workspace scope")).to_have_count(0)
    expect(details).to_be_visible()
    harness.page.keyboard.press("Escape")
    expect(details).to_have_count(0)
    assert not harness.patches


def test_the_documents_picker_says_why_its_list_is_narrowed_and_hands_over_to_the_dialog(make_harness):
    harness = make_harness()
    harness.open(enforce=False)

    harness.page.get_by_role("button", name=re.compile(r"^Documents")).click()
    picker = harness.page.get_by_role("region", name="Document sources")
    expect(picker).to_be_visible()
    note = picker.get_by_role("note")
    expect(note).to_contain_text("This conversation is locked to Marketing. Only those workspaces are listed here.")
    harness.wait_for(lambda: harness.source_queries, "The picker did not read its sources.")
    assert harness.source_queries[0].get("conversation_id") == CONVERSATION, (
        "The picker names the conversation, which is how the server narrows its list to the lock"
    )
    # The narrowed list is what the lock does, so the reader sees only Marketing.
    expect(picker.get_by_role("navigation", name="Workspaces").get_by_role("button", name=re.compile("My workspace"))).to_have_count(0)

    note.get_by_role("button", name="Manage").click()
    expect(picker).to_have_count(0)
    expect(harness.page.get_by_role("dialog", name="Unlock workspace scope")).to_be_visible()


def test_an_unlocked_conversation_draws_no_note_in_the_picker(make_harness):
    harness = make_harness(metadata(scope_locked=False))
    harness.open(enforce=False)

    harness.page.get_by_role("button", name=re.compile(r"^Documents")).click()
    picker = harness.page.get_by_role("region", name="Document sources")
    expect(picker).to_be_visible()
    expect(picker.get_by_role("note")).to_have_count(0)
    harness.wait_for(lambda: harness.source_queries, "The picker did not read its sources.")
    expect(picker.get_by_role("navigation", name="Workspaces").get_by_role("button", name=re.compile("My workspace"))).to_be_visible()


# Keyboard and a phone -------------------------------------------------------------------------


def test_the_lock_is_reachable_and_operable_from_the_keyboard_and_returns_focus(make_harness):
    harness = make_harness()
    harness.open(enforce=False)

    harness.header_lock.focus()
    harness.page.keyboard.press("Enter")
    dialog = harness.dialog
    expect(dialog).to_have_accessible_name("Unlock workspace scope")
    # Focus is inside the dialog, and Tab stays there.
    focused_in_dialog = "() => Boolean(document.activeElement && document.activeElement.closest('[role=dialog]'))"
    assert harness.page.evaluate(focused_in_dialog)
    for _ in range(4):
        harness.page.keyboard.press("Tab")
        assert harness.page.evaluate(focused_in_dialog), "Tab left the dialog"

    harness.page.keyboard.press("Escape")
    expect(harness.dialog).to_have_count(0)
    expect(harness.header_lock).to_be_focused()
    assert not harness.patches


def test_the_lock_works_on_a_phone_without_horizontal_scroll(page, make_harness):
    page.set_viewport_size({"width": 390, "height": 844})
    harness = make_harness()
    harness.open(enforce=False)

    expect(harness.header_lock).to_be_visible()
    box = harness.header_lock.bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= 390, box
    assert box["width"] >= 24 and box["height"] >= 24, "A touch target of at least 24 CSS pixels"
    assert harness.no_horizontal_scroll()

    harness.header_lock.click()
    dialog = harness.dialog
    expect(dialog).to_be_visible()
    for name in ("Cancel", "Unlock scope"):
        button = dialog.get_by_role("button", name=name)
        expect(button).to_be_visible()
        edge = button.bounding_box()
        assert edge and edge["x"] >= 0 and edge["x"] + edge["width"] <= 390, (name, edge)
    assert harness.no_horizontal_scroll()

    dialog.get_by_role("button", name="Unlock scope").click()
    expect(harness.toast("Workspace scope unlocked.")).to_be_visible()
    expect(harness.header_lock).to_have_attribute("aria-label", UNLOCKED_LABEL)
    assert harness.no_horizontal_scroll()
