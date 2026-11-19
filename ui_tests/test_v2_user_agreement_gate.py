# test_v2_user_agreement_gate.py
"""
Browser regressions for the V2 user agreement gate: the agreement an administrator requires before a
user uploads files, shown before the chat composer or the documents explorer sends anything.
Version: 0.261.448
Implemented in: 0.261.448
Send held while a file waits on the agreement (the race a reviewer found): 0.261.448

The real chat composer editor, the whole chat composer with its Send control, and the real documents
explorer (personal, group and public scope, built from the real adapters) run in Chromium, bundled by
fixtures/user_agreement_gate. Only HTTP answers are replaced, including the two user agreement routes,
which the fixture answers the way route_backend_user_agreement.py does: the same parameters, the same
validation, the same once-per-day rule keyed by workspace type and workspace id. The existing Azure
Playwright connection fixture also supports a local browser; no live application data is read or modified.

A file has no chip until its gate settles, so the composer holds Enter and Send meanwhile; the tests that
cover it delay the check route and answer it when the test says.

Run: python -m pytest ui_tests/test_v2_user_agreement_gate.py -q -p no:cacheprovider
(needs a built SPA for its stylesheet: cd application/v2_ui; npx vite build)
"""

import json
import re
import sys
import time
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Imported through the package: a bare `harness_build` would collide with the orchestration fixture
# module of the same name when both suites run in one session.
from ui_tests.fixtures.agent_delegation.harness_build import ensure_bundle  # noqa: E402
from ui_tests.fixtures.playwright_connection import connect_options  # noqa: E402,F401
from ui_tests.fixtures.v2_pending_action_stubs import pending_actions_payload  # noqa: E402


pytestmark = pytest.mark.ui

FIXTURE = ROOT / "ui_tests" / "fixtures" / "user_agreement_gate"
BUNDLE = FIXTURE / "harness.bundle.js"
STATIC = ROOT / "application" / "single_app" / "static"
# A secure context, as every deployment is.
ORIGIN = "https://simplechat.test"
POLICY_HOST = "policy.example.test"
DIALOG = "User Agreement Required"
UNAVAILABLE = "User agreement could not be checked"
AGREEMENT_TEXT = (
    "## Upload agreement\n\n"
    "By uploading you confirm you may share this content.\n\n"
    f"[Read the policy](https://{POLICY_HOST}/rules)\n\n"
    '<script>window.__agreementXss = 1</script>\n\n'
    '<img src=x onerror="window.__agreementXss = 2">\n'
)
CHECK_PATH = "/api/user_agreement/check"
ACCEPT_PATH = "/api/user_agreement/accept"
UPLOAD_PATHS = {
    "chat": "/upload",
    "personal": "/api/documents/upload",
    "group": "/api/groups/group-a/documents/upload",
    "public": "/api/public-workspaces/public-a/documents/upload",
}
SEND_PATH = "/api/chat/stream"
CREATE_CONVERSATION_PATH = "/api/create_conversation"
PLAN_PATH = "/api/v2/orchestration/plan"
QUESTION_CONVERSATION = "conv-questions"
# The limit USER_AGREEMENT_REQUEST_TIMEOUT_MS puts on a check or an acceptance, and how the failure says it.
TIME_LIMIT_MS = 20_000
TIMED_OUT = "no answer within 20 seconds"
# What the chat composer asks for on its own while it is open, answered as for a user with nothing saved.
CHAT_SIDE_ANSWERS = {
    "/api/msgraph/pending-actions": pending_actions_payload(),
    "/api/action-credentials/pending": {"success": True, "requests": []},
    "/api/action-recovery/context": {"csrf_token": "synthetic-csrf"},
    "/api/v2/orchestration/runs": {"runs": []},
    "/api/v2/orchestration/questions": {"questions": []},
    "/api/v2/user-input/pending": {"requests": [], "csrf_token": "synthetic-csrf"},
    "/api/get_messages": {"messages": []},
    "/api/conversations/feed": {"conversations": [], "has_more": False, "next_cursor": None},
}
ANSWER_STREAM = "".join(f"data: {json.dumps(frame)}\n\n" for frame in ({"response": "Mock answer."}, {"done": True}))
# What the check route says when no agreement applies to the scope.
NO_AGREEMENT = {"needsAgreement": False, "agreementText": "", "enableDailyAcceptance": False}
# What the composer says while a file waits on the agreement, as userAgreement.ts words it.
PENDING = "Checking the user agreement before attaching your file…"
LEFT_CONVERSATION = "was not attached because you left the conversation"
LIST_PAGE = {"documents": [], "page": 1, "page_size": 25, "total_count": 0, "file_downloads_enabled": False}
FACETS = {
    "total": 0, "untagged": 0, "processing": 0, "errors": 0, "recent": 0, "shared_with_me": 0,
    "by_tag": {}, "by_classification": {},
}


class AgreementServer:
    """The two routes as route_backend_user_agreement.py answers them, with the state they read."""

    VALID_TYPES = ("personal", "group", "public", "chat")

    def __init__(self):
        self.enabled = True
        self.apply_to = list(self.VALID_TYPES)
        self.text = AGREEMENT_TEXT
        self.daily = False
        # Acceptances recorded today, as the activity log keys them: workspace type and workspace id.
        self.accepted_today = set()
        self.check_failures = []
        self.accept_failures = []
        self.unreadable_checks = 0
        self.checks = []
        self.accepts = []

    def check(self, query):
        self.checks.append(dict(query))
        return self.answer(query)

    def answer(self, query):
        """What the route says to this query, without recording that it was asked."""
        workspace_id = query.get("workspace_id")
        workspace_type = query.get("workspace_type")
        action = query.get("action_context", "file_upload")
        if not workspace_id or not workspace_type:
            return 400, {"error": "workspace_id and workspace_type are required"}
        if workspace_type not in self.VALID_TYPES:
            return 400, {"error": "Invalid workspace_type."}
        if not self.enabled:
            return 200, {"needsAgreement": False, "agreementText": "", "enableDailyAcceptance": False}
        applies = workspace_type in self.apply_to or (action == "chat" and "chat" in self.apply_to)
        if not applies:
            return 200, {"needsAgreement": False, "agreementText": "", "enableDailyAcceptance": False}
        if self.daily and (workspace_type, workspace_id) in self.accepted_today:
            return 200, {
                "needsAgreement": False, "agreementText": "", "enableDailyAcceptance": True,
                "alreadyAcceptedToday": True,
            }
        return 200, {"needsAgreement": True, "agreementText": self.text, "enableDailyAcceptance": self.daily}

    def accept(self, body):
        self.accepts.append(dict(body))
        if not body.get("workspace_id") or not body.get("workspace_type"):
            return 400, {"error": "workspace_id and workspace_type are required"}
        if body["workspace_type"] not in self.VALID_TYPES:
            return 400, {"error": "Invalid workspace_type."}
        self.accepted_today.add((body["workspace_type"], body["workspace_id"]))
        return 200, {"success": True, "message": "User agreement acceptance recorded"}


class Harness:
    """The composer, the composer's editor on its own, and the explorer, driven the way a person drives them."""

    def __init__(self, page, stylesheets):
        self.page = page
        self.stylesheets = stylesheets
        self.agreement = AgreementServer()
        self.requests = []
        self.uploads = []
        self.opened = []
        self.upload_failures = []
        self.hold_accept = False
        self.held_accepts = []
        # Checks held until the test answers them, as a slow network would hold them.
        self.hold_checks = False
        self.held_checks = []
        self.abandoned_checks = 0
        # The messages the chat composer sent, as the server received them.
        self.sends = []
        # The answers an elicitation card submitted, as the server received them.
        self.answers = []
        self.errors = []
        self.unexpected = []
        self.expected_http_failures = set()
        self.list_params = []
        self.max_file_size_mb = 25
        page.context.route("**/*", self.handle)
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.on("console", self.record_console)
        page.on("requestfailed", self.record_failed_request)

    # Routing ----------------------------------------------------------------------------------

    def record_console(self, message):
        if message.type != "error":
            return
        path = urlsplit(message.location.get("url", "")).path
        status = re.search(r"^Failed to load resource: the server responded with a status of (\d+)", message.text)
        if status and (path, int(status.group(1))) in self.expected_http_failures:
            return
        # A held check the page itself gave up on, which is what an owner going away does.
        if path == CHECK_PATH and self.abandoned_checks and "net::ERR_ABORTED" in message.text:
            return
        self.errors.append(message.text)

    def record_failed_request(self, request):
        if urlsplit(request.url).path == CHECK_PATH and "ERR_ABORTED" in (request.failure or ""):
            self.abandoned_checks += 1

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        method = request.method
        if parsed.netloc == POLICY_HOST:
            self.opened.append(request.url)
            route.fulfill(content_type="text/html", body="<!doctype html><title>Policy</title><p>Policy</p>")
            return
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(f"{method} {request.url}")
            route.abort()
            return
        path = parsed.path
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        self.requests.append((method, path))
        for answer in (
            self.page_route, self.agreement_route, self.upload_route, self.read_route, self.chat_route,
        ):
            if answer(route, request, method, path, query):
                return
        self.unexpected.append(f"{method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def page_route(self, route, request, method, path, query):
        if method != "GET":
            return False
        if path == "/harness.html":
            route.fulfill(path=str(FIXTURE / "harness.html"), content_type="text/html")
        elif path == "/harness.bundle.js":
            route.fulfill(path=str(BUNDLE), content_type="application/javascript")
        elif path == "/favicon.ico":
            route.fulfill(status=204, body="")
        else:
            return False
        return True

    def agreement_route(self, route, request, method, path, query):
        if method == "GET" and path == CHECK_PATH:
            if self.hold_checks:
                self.agreement.checks.append(dict(query))
                self.held_checks.append((route, query))
                return True
            if self.agreement.check_failures:
                status = self.agreement.check_failures.pop(0)
                self.expected_http_failures.add((path, status))
                self.agreement.checks.append(dict(query))
                route.fulfill(status=status, json={"error": "Fixture check failure."})
                return True
            if self.agreement.unreadable_checks:
                self.agreement.unreadable_checks -= 1
                self.agreement.checks.append(dict(query))
                route.fulfill(status=200, json={"unexpected": "shape"})
                return True
            status, payload = self.agreement.check(query)
            route.fulfill(status=status, json=payload)
            return True
        if method == "POST" and path == ACCEPT_PATH:
            if self.agreement.accept_failures:
                status = self.agreement.accept_failures.pop(0)
                self.expected_http_failures.add((path, status))
                self.agreement.accepts.append(request.post_data_json)
                route.fulfill(status=status, json={"success": False, "error": "Fixture accept failure."})
                return True
            if self.hold_accept:
                self.held_accepts.append(route)
                self.agreement.accepts.append(request.post_data_json)
                return True
            status, payload = self.agreement.accept(request.post_data_json)
            route.fulfill(status=status, json=payload)
            return True
        return False

    def release_accepts(self):
        held, self.held_accepts = self.held_accepts, []
        for route in held:
            body = json.loads(route.request.post_data)
            self.agreement.accepted_today.add((body["workspace_type"], body["workspace_id"]))
            route.fulfill(json={"success": True, "message": "User agreement acceptance recorded"})

    def release_check(self, payload=None, status=200):
        """Answer the oldest held check as the route would, or with `payload`."""
        assert self.held_checks, "no check is being held"
        route, query = self.held_checks.pop(0)
        if payload is None:
            status, payload = self.agreement.answer(query)
        route.fulfill(status=status, json=payload)

    def upload_route(self, route, request, method, path, query):
        kind = next((name for name, upload_path in UPLOAD_PATHS.items() if upload_path == path), None)
        if method != "POST" or kind is None:
            return False
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode() + request.post_data_buffer
        )
        files = [
            part.get_filename() for part in message.iter_parts()
            if part.get_param("name", header="content-disposition") == "file"
        ]
        conversation = next((
            part.get_content().strip() for part in message.iter_parts()
            if part.get_param("name", header="content-disposition") == "conversation_id"
        ), "conv-1")
        self.uploads.append({"kind": kind, "path": path, "files": files})
        if self.upload_failures:
            status = self.upload_failures.pop(0)
            self.expected_http_failures.add((path, status))
            route.fulfill(status=status, json={"error": "Upload failed. Please retry."})
        elif kind == "chat":
            number = len(self.uploads)
            route.fulfill(json={
                "success": True, "conversation_id": conversation, "file_message_id": f"upload-message-{number}",
            })
        else:
            route.fulfill(json={
                "document_ids": [f"document-{index}" for index, _ in enumerate(files)],
                "processed_filenames": files, "errors": [],
            })
        return True

    def read_route(self, route, request, method, path, query):
        if method != "GET":
            return False
        if path in ("/api/documents", "/api/group_documents", "/api/public-workspaces/public-a/documents"):
            self.list_params.append((path, query))
            route.fulfill(json=LIST_PAGE)
        elif path == "/api/documents/facets":
            route.fulfill(json=FACETS)
        elif path in (
            "/api/documents/tags", "/api/group_documents/tags", "/api/public-workspaces/public-a/documents/tags",
        ):
            route.fulfill(json={"tags": []})
        else:
            return False
        return True

    def chat_route(self, route, request, method, path, query):
        """What the chat composer needs: its own reads, and the two requests a send makes."""
        if method == "GET":
            if path in CHAT_SIDE_ANSWERS:
                route.fulfill(json=CHAT_SIDE_ANSWERS[path])
            elif path.startswith("/api/chat/stream/status/"):
                route.fulfill(json={"active": False, "pending": False, "reattachable": False})
            else:
                return False
            return True
        if method != "POST":
            return False
        if path == "/api/chat/action-health":
            route.fulfill(json={"state": "ready"})
        elif path == CREATE_CONVERSATION_PATH:
            route.fulfill(json={"conversation_id": "conv-new", "title": "New chat"})
        elif path == SEND_PATH:
            self.sends.append(request.post_data_json)
            route.fulfill(content_type="text/event-stream", body=ANSWER_STREAM)
        elif path == PLAN_PATH:
            body = request.post_data_json
            self.answers.append(body)
            route.fulfill(content_type="text/event-stream", body=f"data: {json.dumps(plan_frame(body))}\n\n")
        else:
            return False
        return True

    # Opening ----------------------------------------------------------------------------------

    def open(self, mount, *, enabled=True, width=1280, height=860, flag=None, clock=False):
        """Seed the bootstrap store as the server sends it, then mount the composer or an explorer.

        `enabled` is the administrator's switch as bootstrap carries it; `flag` overrides what is sent for it.
        `clock` installs a fake clock before the page loads: time still flows, and a test can jump it forward
        to reach the limit on a check or an acceptance without waiting for it.
        """
        settings = {"max_file_size_mb": self.max_file_size_mb}
        if flag is not None:
            settings["enable_user_agreement"] = flag
        elif enabled:
            settings["enable_user_agreement"] = True
        self.page.set_viewport_size({"width": width, "height": height})
        if clock:
            self.page.clock.install()
        self.page.goto(f"{ORIGIN}/harness.html")
        for stylesheet in self.stylesheets:
            self.page.add_style_tag(path=str(stylesheet))
        self.page.evaluate(SEED, {"settings": settings})
        self.page.evaluate(mount)

    def open_composer(self, **options):
        self.open("() => window.AgreementHarness.mountComposer('conv-1')", **options)
        expect(self.page.get_by_role("textbox", name="Message", exact=True)).to_be_visible()

    def open_chat(self, conversation="conv-1", **options):
        """The whole chat composer, with its Send control, in `conversation` (None for a new chat)."""
        self.open(f"() => window.AgreementHarness.mountChat({json.dumps(conversation)})", **options)
        expect(self.composer).to_be_visible()

    def open_questions(self, question=None, **options):
        """The real elicitation card over `question`, which asks for notes and then a format by default."""
        self.open(
            f"() => window.AgreementHarness.mountQuestions({json.dumps(question or questions())})", **options,
        )
        expect(self.card).to_be_visible()

    def open_explorer(self, kind, **options):
        self.open(f"() => window.AgreementHarness.mountExplorer('{kind}')", **options)
        explorer = self.page.get_by_role("group", name="Documents explorer", exact=True)
        expect(explorer).to_be_visible()
        expect(explorer).to_have_attribute("aria-busy", "false")

    # Reading ----------------------------------------------------------------------------------

    def wait_for(self, predicate, message, timeout=6.0):
        """Poll from the test thread, so held routes keep being answered meanwhile."""
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError(message)
            self.page.wait_for_timeout(40)

    def sequence(self):
        """The agreement, upload and send requests so far, in the order they were made."""
        interesting = {CHECK_PATH, ACCEPT_PATH, SEND_PATH, CREATE_CONVERSATION_PATH, *UPLOAD_PATHS.values()}
        return [f"{method} {path}" for method, path in self.requests if path in interesting]

    def settle(self):
        """Let anything that is going to happen after a click happen."""
        self.page.wait_for_timeout(250)

    @property
    def dialog(self):
        return self.page.get_by_role("dialog", name=DIALOG, exact=True)

    @property
    def unavailable(self):
        return self.page.get_by_role("dialog", name=UNAVAILABLE, exact=True)

    @property
    def composer(self):
        return self.page.get_by_role("textbox", name="Message", exact=True)

    @property
    def send(self):
        return self.page.get_by_role("button", name="Send message", exact=True)

    @property
    def send_button(self):
        """Send by its label alone, which still finds it while a modal dialog hides the page from the tree."""
        return self.page.locator('button[aria-label="Send message"]')

    @property
    def held_notice(self):
        return self.page.get_by_role("status").filter(has_text=PENDING)

    @property
    def attach(self):
        return self.page.get_by_role("button", name="Attach a file", exact=True)

    @property
    def attached(self):
        return self.page.get_by_role("list", name="Attached files", exact=True).get_by_role("listitem")

    @property
    def explorer_input(self):
        return self.page.locator('input[type="file"][aria-label="Upload workspace documents"]')

    @property
    def chat_input(self):
        return self.page.locator('[data-composer-editor="agreement-composer"] input[type="file"]')

    @property
    def chat_composer_input(self):
        """The whole chat composer's file input, which the Attach button opens."""
        return self.page.locator('[data-composer-editor="composer-input"] input[type="file"]')

    @property
    def card(self):
        return self.page.get_by_role("region", name="Follow-up questions", exact=True)

    @property
    def card_input(self):
        """The file input of the question being answered."""
        return self.card.locator('input[type="file"]')

    @property
    def forward(self):
        """The card's forward control, which says Next, Review answers or Use these answers by where it is.

        Found by its type rather than its role, so that it is still found while a modal dialog hides the page
        from the accessibility tree.
        """
        return self.card.locator('button[type="submit"]')

    @property
    def hint(self):
        """The line under the card's buttons that says why the forward control is unavailable.

        Its container may also offer links to answers elsewhere that are still missing, so the sentence is read
        from its own paragraph.
        """
        return self.card.locator('div[aria-live="polite"] > p')

    def paste_file(self, name="policy.txt", selector="#composer-input"):
        self.page.evaluate(PASTE_FILE, {"name": name, "body": "Quarterly policy text.", "selector": selector})

    def drop_files(self, *names, selector="#composer-input"):
        files = [{"name": name, "body": "Quarterly policy text."} for name in names]
        self.page.evaluate(DROP_FILES, {"selector": selector, "files": files})

    def accept(self, dialog=None):
        (dialog or self.dialog).get_by_role("button", name="Accept", exact=True).click()

    def cancel(self, dialog=None):
        (dialog or self.dialog).get_by_role("button", name="Cancel", exact=True).click()


SEED = """(spec) => {
    const H = window.AgreementHarness;
    H.stores.bootstrap.useBootstrapStore.setState({
        loading: false,
        data: {
            version: '0.261.448',
            user: { id: 'viewer-1', display_name: 'Viewer', is_admin: false, roles: ['User'] },
            branding: { app_title: 'SimpleChat' },
            features: {
                enable_chat_file_uploads: true, enable_user_workspace: true,
                enable_group_workspaces: true, enable_public_workspaces: true,
            },
            scope: { groups: [], public_workspaces: [] },
            catalogs: { models: [], agents: [], prompts: [] },
            settings: spec.settings,
        },
    });
}"""


def text_file(name="policy.txt", body=b"Quarterly policy text."):
    return {"name": name, "mimeType": "text/plain", "buffer": body}


def questions(pages=(("notes",), ("format",)), revision=0):
    """What an elicitation card asks: optional notes, which take a typed answer and files, and a required format."""
    properties = {
        "notes": {"type": "string", "title": "Notes"},
        "format": {"type": "string", "enum": ["Summary", "Detailed"], "title": "Format"},
    }
    names = [name for page in pages for name in page]
    return {
        "elicitation_id": "agreement-questions",
        "contract_version": 2,
        "run_id": "",
        "revision": revision,
        "turn_id": "turn-questions",
        "message": "Tell me what to look for in the report.",
        "requested_schema": {
            "type": "object",
            "properties": {name: properties[name] for name in names},
            "required": ["format"] if "format" in names else [],
        },
        "ui_hints": {"order": names, "pages": [list(page) for page in pages]},
    }


def plan_frame(body):
    """The planning stream's answer to a submitted elicitation response."""
    return {"type": "orchestration_plan", "plan": {
        "plan_id": "accepted-plan", "run_id": "accepted-run",
        "conversation_id": QUESTION_CONVERSATION, "turn_id": body["turn_id"],
        "revision": body["elicitation_revision"] + 1,
        "planner_contract_version": 2,
        "intent": {"summary": "Use the supplied answer", "complexity": "simple"},
        "steps": [{
            "step_id": "answer", "capability_id": "compose", "role": "reason", "title": "Answer",
            "arguments": {"instruction": "Use the supplied answer."}, "inputs": {},
            "outputs": [{"name": "answer", "kind": "markdown-v1"}], "depends_on": [],
        }],
        "final_response": {
            "version": "orchestration-input-binding-v1", "step_id": "answer",
            "output_name": "answer", "existing_result": None,
        },
        "approval": {"mode": "manual", "state": "pending", "timeout_seconds": 0},
        "status": "awaiting_approval",
    }}


DROP_FILES = """(spec) => {
    const target = document.querySelector(spec.selector);
    const transfer = new DataTransfer();
    for (const file of spec.files) {
        transfer.items.add(new File([file.body], file.name, { type: 'text/plain' }));
    }
    target.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: transfer }));
}"""

PASTE_FILE = """(spec) => {
    const target = document.querySelector(spec.selector ?? '#agreement-composer');
    const transfer = new DataTransfer();
    transfer.items.add(new File([spec.body], spec.name, { type: 'text/plain' }));
    target.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: transfer }));
}"""

# Presses Enter in the composer on every frame until told to stop, so that no moment between the check
# answering and the file reaching the draft can pass unpressed.
HAMMER_ENTER = """(spec) => {
    const target = document.querySelector(spec.selector);
    const hammer = { stop: false, presses: 0 };
    window.__enterHammer = hammer;
    const press = () => {
        if (hammer.stop) {
            return;
        }
        target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
        hammer.presses += 1;
        requestAnimationFrame(press);
    };
    press();
}"""

# Records, from now on, whether the held-Send wording ever reaches the page: as text anywhere or as a title.
WATCH_HELD_SEND = """(spec) => {
    const seen = { text: false, title: false };
    window.__heldSend = seen;
    const look = () => {
        seen.text = seen.text || document.body.innerText.includes(spec.message);
        seen.title = seen.title || Boolean(document.querySelector(`[title="${spec.message}"]`));
    };
    new MutationObserver(look).observe(document.body, {
        subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['title'],
    });
    look();
}"""


@pytest.fixture(scope="module")
def harness_assets():
    index = STATIC / "v2" / "index.html"
    assert index.is_file(), "Build the V2 SPA first: cd application/v2_ui; npx vite build"
    hrefs = re.findall(r'<link\b[^>]*href="([^"]+\.css)"', index.read_text(encoding="utf-8"))
    stylesheets = [STATIC / href.removeprefix("/static/") for href in hrefs]
    assert stylesheets and all(sheet.is_file() for sheet in stylesheets), stylesheets
    assert any("max-h-\\[45vh\\]" in sheet.read_text(encoding="utf-8") for sheet in stylesheets), (
        "The built stylesheet predates the user agreement dialog; rebuild it: cd application/v2_ui; npx vite build"
    )
    ensure_bundle(entry=FIXTURE / "harness_entry.tsx", bundle=BUNDLE)
    yield stylesheets
    BUNDLE.unlink(missing_ok=True)
    BUNDLE.with_suffix(".css").unlink(missing_ok=True)


@pytest.fixture
def harness(page, harness_assets):
    api = Harness(page, harness_assets)
    yield api
    assert not api.errors, api.errors
    assert not api.unexpected, api.unexpected


# Chat -----------------------------------------------------------------------------------------


def test_a_chat_upload_waits_for_the_agreement_and_records_the_acceptance_before_the_file_is_sent(harness):
    harness.open_composer()
    with harness.page.expect_file_chooser() as chooser:
        harness.attach.click()
    chooser.value.set_files(text_file())

    expect(harness.dialog).to_be_visible()
    expect(harness.dialog.get_by_role("heading", name="Upload agreement", exact=True)).to_be_visible()
    expect(harness.dialog.get_by_text("Accepting records your acceptance and continues the upload of 1 file.")).to_be_visible()
    assert harness.agreement.checks == [{
        "workspace_type": "chat", "workspace_id": "default", "action_context": "file_upload",
    }]
    # Nothing has been attached, recorded or sent while the person is still reading.
    expect(harness.attached).to_have_count(0)
    assert harness.sequence() == [f"GET {CHECK_PATH}"]

    harness.accept()
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    expect(harness.dialog).to_have_count(0)
    assert harness.agreement.accepts == [{
        "workspace_type": "chat", "workspace_id": "default", "action_context": "file_upload",
    }]
    assert harness.sequence() == [f"GET {CHECK_PATH}", f"POST {ACCEPT_PATH}", "POST /upload"]
    assert harness.uploads == [{"kind": "chat", "path": "/upload", "files": ["policy.txt"]}]


def test_cancelling_uploads_nothing_and_leaves_the_composer_as_it_was(harness):
    harness.open_composer()
    harness.composer.fill("Summarise the attached policy.")
    with harness.page.expect_file_chooser() as chooser:
        harness.attach.click()
    chooser.value.set_files(text_file())
    expect(harness.dialog).to_be_visible()

    harness.cancel()
    expect(harness.dialog).to_have_count(0)
    harness.settle()
    expect(harness.composer).to_have_value("Summarise the attached policy.")
    expect(harness.attached).to_have_count(0)
    # Focus is handed back to the control that started the upload.
    expect(harness.attach).to_be_focused()
    assert harness.sequence() == [f"GET {CHECK_PATH}"]
    assert harness.agreement.accepts == [] and harness.uploads == []


def test_escape_the_close_button_and_the_backdrop_all_mean_do_not_upload(harness):
    harness.open_composer()
    for dismiss in ("escape", "close", "backdrop"):
        harness.chat_input.set_input_files(text_file())
        expect(harness.dialog).to_be_visible()
        if dismiss == "escape":
            harness.page.keyboard.press("Escape")
        elif dismiss == "close":
            harness.dialog.get_by_role("button", name="Close", exact=True).click()
        else:
            harness.page.mouse.click(5, 5)
        expect(harness.dialog).to_have_count(0)
    harness.settle()
    assert harness.agreement.accepts == [] and harness.uploads == []
    expect(harness.attached).to_have_count(0)


def test_keyboard_focus_stays_in_the_dialog_and_the_agreement_text_can_be_scrolled(harness):
    harness.agreement.text = "\n\n".join(f"Clause {number}: you agree to the terms of clause {number}." for number in range(60))
    harness.open_composer()
    harness.chat_input.set_input_files(text_file())
    expect(harness.dialog).to_be_visible()
    text = harness.dialog.get_by_role("region", name="User agreement text", exact=True)
    assert text.evaluate("element => element.scrollHeight > element.clientHeight"), "A long agreement must scroll."

    visited = []
    for _ in range(8):
        harness.page.keyboard.press("Tab")
        visited.append(harness.page.evaluate("""() => {
            const active = document.activeElement;
            const dialog = active && active.closest('[role="dialog"]');
            return dialog ? (active.getAttribute('aria-label') || active.textContent.trim() || active.tagName) : 'OUTSIDE';
        }"""))
    assert "OUTSIDE" not in visited, visited
    assert {"Close", "User agreement text", "Cancel", "Accept"} <= set(visited), visited
    harness.page.keyboard.press("Shift+Tab")
    assert harness.page.evaluate("() => Boolean(document.activeElement.closest('[role=\"dialog\"]'))")

    # Reading with the keyboard: the focused text scrolls, and Escape still cancels.
    text.focus()
    harness.page.keyboard.press("PageDown")
    # Keyboard scrolling is animated, so the position is read once it has moved rather than at once.
    harness.wait_for(lambda: text.evaluate("element => element.scrollTop") > 0, "PageDown did not scroll the agreement.")
    harness.page.keyboard.press("Escape")
    expect(harness.dialog).to_have_count(0)
    assert harness.uploads == []


def test_accepting_with_the_keyboard_uploads_the_file(harness):
    harness.open_composer()
    harness.chat_input.set_input_files(text_file())
    expect(harness.dialog).to_be_visible()
    harness.dialog.get_by_role("button", name="Accept", exact=True).focus()
    harness.page.keyboard.press("Enter")
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    assert harness.sequence() == [f"GET {CHECK_PATH}", f"POST {ACCEPT_PATH}", "POST /upload"]


def test_agreement_text_is_rendered_as_markdown_without_running_embedded_markup(harness):
    harness.open_composer()
    harness.chat_input.set_input_files(text_file())
    text = harness.dialog.get_by_role("region", name="User agreement text", exact=True)
    expect(text.get_by_role("heading", name="Upload agreement", exact=True)).to_be_visible()
    expect(text.get_by_role("link", name="Read the policy", exact=True)).to_be_visible()
    harness.settle()
    assert harness.page.evaluate("() => window.__agreementXss === undefined"), "Agreement markup must not execute."
    assert text.locator("script, img").count() == 0


def test_a_link_in_the_agreement_opens_a_new_tab_and_keeps_the_upload_waiting(harness):
    harness.open_composer()
    harness.chat_input.set_input_files(text_file())
    expect(harness.dialog).to_be_visible()
    page_url = harness.page.url
    with harness.page.context.expect_page() as opened:
        harness.dialog.get_by_role("link", name="Read the policy", exact=True).click()
    opened.value.wait_for_load_state()
    assert opened.value.url == f"https://{POLICY_HOST}/rules"
    opened.value.close()
    # The tab the person is working in did not navigate, so the upload is still waiting for them.
    assert harness.page.url == page_url
    expect(harness.dialog).to_be_visible()
    harness.accept()
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()


def test_feature_off_sends_no_check_and_uploads_immediately(harness):
    harness.open_composer(enabled=False)
    harness.chat_input.set_input_files(text_file())
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    assert harness.sequence() == ["POST /upload"]
    assert harness.agreement.checks == []
    expect(harness.dialog).to_have_count(0)


def test_an_explicit_off_in_bootstrap_is_off_but_any_other_value_asks_the_server(harness):
    harness.open_composer(flag=False)
    harness.chat_input.set_input_files(text_file())
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    assert harness.agreement.checks == []

    harness.agreement.enabled = False
    harness.open_composer(flag="yes")
    harness.chat_input.set_input_files(text_file("second.txt"))
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    assert len(harness.agreement.checks) == 1, "An unrecognised switch value must be settled by the server."
    expect(harness.dialog).to_have_count(0)


def test_a_server_that_says_the_agreement_does_not_apply_to_chat_lets_the_upload_through(harness):
    harness.agreement.apply_to = ["personal", "group", "public"]
    harness.open_composer()
    harness.chat_input.set_input_files(text_file())
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    assert harness.sequence() == [f"GET {CHECK_PATH}", "POST /upload"]
    assert harness.agreement.accepts == []


def test_daily_acceptance_is_remembered_and_is_not_asked_again(harness):
    harness.agreement.daily = True
    harness.open_composer()
    harness.chat_input.set_input_files(text_file("first.txt"))
    expect(harness.dialog.get_by_text("Your acceptance will be remembered for today.")).to_be_visible()
    harness.accept()
    expect(harness.attached.get_by_text("Ready", exact=True)).to_have_count(1)

    harness.chat_input.set_input_files(text_file("second.txt"))
    expect(harness.attached.get_by_text("Ready", exact=True)).to_have_count(2)
    expect(harness.dialog).to_have_count(0)
    assert harness.sequence() == [
        f"GET {CHECK_PATH}", f"POST {ACCEPT_PATH}", "POST /upload", f"GET {CHECK_PATH}", "POST /upload",
    ]
    assert len(harness.agreement.accepts) == 1


def test_without_daily_acceptance_every_upload_asks_again(harness):
    harness.open_composer()
    for number in (1, 2):
        harness.chat_input.set_input_files(text_file(f"file-{number}.txt"))
        expect(harness.dialog).to_be_visible()
        assert "remembered" not in harness.dialog.inner_text()
        harness.accept()
        expect(harness.attached.get_by_text("Ready", exact=True)).to_have_count(number)
    assert len(harness.agreement.accepts) == 2


def test_a_failed_check_holds_the_upload_and_try_again_recovers(harness):
    harness.agreement.check_failures = [503]
    harness.open_composer()
    harness.chat_input.set_input_files(text_file())
    expect(harness.unavailable).to_be_visible()
    expect(harness.unavailable.get_by_role("alert")).to_contain_text(
        "We could not confirm whether a user agreement applies, so nothing was uploaded. (status 503)"
    )
    expect(harness.unavailable).to_contain_text("Your upload is on hold until this check succeeds.")
    expect(harness.unavailable.get_by_role("button", name="Try again", exact=True)).to_be_focused()
    assert harness.uploads == []

    harness.unavailable.get_by_role("button", name="Try again", exact=True).click()
    expect(harness.dialog).to_be_visible()
    # The failure's button is gone; focus moves to the agreement's dialog rather than falling to the page.
    assert harness.page.evaluate("() => Boolean(document.activeElement.closest('[role=\"dialog\"]'))")
    harness.accept()
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    assert harness.sequence() == [f"GET {CHECK_PATH}", f"GET {CHECK_PATH}", f"POST {ACCEPT_PATH}", "POST /upload"]


def test_a_failed_check_can_be_cancelled_and_nothing_is_uploaded(harness):
    harness.agreement.check_failures = [500]
    harness.open_composer()
    harness.composer.fill("Keep this draft.")
    harness.chat_input.set_input_files(text_file())
    expect(harness.unavailable).to_be_visible()
    harness.cancel(harness.unavailable)
    expect(harness.unavailable).to_have_count(0)
    harness.settle()
    expect(harness.composer).to_have_value("Keep this draft.")
    assert harness.uploads == [] and harness.agreement.accepts == []


def test_an_unreadable_check_answer_is_a_failed_check_never_no_agreement(harness):
    harness.agreement.unreadable_checks = 1
    harness.open_composer()
    harness.chat_input.set_input_files(text_file())
    expect(harness.unavailable).to_be_visible()
    harness.settle()
    assert harness.uploads == []
    harness.cancel(harness.unavailable)


def test_a_failed_acceptance_holds_the_upload_and_can_be_accepted_again(harness):
    harness.agreement.accept_failures = [500]
    harness.open_composer()
    harness.chat_input.set_input_files(text_file())
    harness.accept()
    alert = harness.dialog.get_by_role("alert")
    expect(alert).to_contain_text("Your acceptance could not be recorded, so nothing was uploaded. (status 500)")
    assert harness.uploads == []
    # The agreement is still there to read, and focus is back on the action to retry.
    expect(harness.dialog.get_by_role("heading", name="Upload agreement", exact=True)).to_be_visible()
    expect(harness.dialog.get_by_role("button", name="Accept", exact=True)).to_be_focused()

    harness.accept()
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    assert len(harness.agreement.accepts) == 2
    assert harness.sequence() == [
        f"GET {CHECK_PATH}", f"POST {ACCEPT_PATH}", f"POST {ACCEPT_PATH}", "POST /upload",
    ]


def test_while_the_acceptance_is_being_recorded_the_dialog_cannot_be_dismissed(harness):
    harness.hold_accept = True
    harness.open_composer()
    harness.chat_input.set_input_files(text_file())
    harness.accept()
    harness.wait_for(lambda: len(harness.held_accepts) == 1, "The acceptance was not requested.")
    accept = harness.dialog.get_by_role("button", name="Accept", exact=True)
    cancel = harness.dialog.get_by_role("button", name="Cancel", exact=True)
    expect(accept).to_be_disabled()
    expect(cancel).to_be_disabled()
    expect(harness.dialog.get_by_role("status")).to_have_text("Recording your acceptance…")
    harness.page.keyboard.press("Escape")
    harness.page.mouse.click(5, 5)
    harness.settle()
    expect(harness.dialog).to_be_visible()
    assert harness.uploads == []

    harness.release_accepts()
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    assert len(harness.agreement.accepts) == 1


def test_pasting_and_dropping_a_file_into_the_composer_ask_first(harness):
    harness.open_composer()
    harness.page.evaluate(PASTE_FILE, {"name": "pasted.txt", "body": "pasted text file"})
    expect(harness.dialog).to_be_visible()
    assert harness.uploads == []
    harness.cancel()
    expect(harness.dialog).to_have_count(0)

    harness.page.evaluate(DROP_FILES, {"selector": "#agreement-composer", "files": [{"name": "dropped.txt", "body": "dropped"}]})
    expect(harness.dialog).to_be_visible()
    assert harness.uploads == []
    harness.accept()
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    assert harness.uploads == [{"kind": "chat", "path": "/upload", "files": ["dropped.txt"]}]
    assert len(harness.agreement.checks) == 2


def test_a_batch_is_asked_about_once_and_a_second_drop_waits_its_turn(harness):
    harness.open_composer()
    harness.chat_input.set_input_files([text_file("one.txt"), text_file("two.txt")])
    expect(harness.dialog).to_be_visible()
    expect(harness.dialog.get_by_text("continues the upload of 2 files.")).to_be_visible()
    # A second drop while the first is being asked about queues behind it instead of stacking a dialog.
    harness.page.evaluate(DROP_FILES, {"selector": "#agreement-composer", "files": [{"name": "three.txt", "body": "three"}]})
    harness.settle()
    assert harness.page.get_by_role("dialog").count() == 1
    harness.accept()
    expect(harness.attached.get_by_text("Ready", exact=True)).to_have_count(2)
    expect(harness.dialog).to_be_visible()
    expect(harness.dialog.get_by_text("continues the upload of 1 file.")).to_be_visible()
    harness.accept()
    expect(harness.attached.get_by_text("Ready", exact=True)).to_have_count(3)
    assert [upload["files"] for upload in harness.uploads] == [["one.txt"], ["two.txt"], ["three.txt"]]
    assert len(harness.agreement.accepts) == 2


def test_a_file_the_composer_refuses_never_triggers_the_agreement(harness):
    harness.open_composer()
    harness.chat_input.set_input_files({"name": "program.exe", "mimeType": "application/octet-stream", "buffer": b"MZ"})
    expect(harness.attached.get_by_role("alert")).to_contain_text("This file type is not supported for chat uploads.")
    harness.settle()
    assert harness.sequence() == []
    expect(harness.dialog).to_have_count(0)


def test_retrying_a_failed_upload_asks_again_and_a_double_click_starts_one_upload(harness):
    harness.upload_failures = [503]
    harness.open_composer()
    harness.chat_input.set_input_files(text_file())
    harness.accept()
    retry = harness.page.get_by_role("button", name="Retry policy.txt", exact=True)
    expect(retry).to_be_visible()
    assert len(harness.uploads) == 1

    retry.evaluate("button => { button.click(); button.click(); }")
    expect(harness.dialog).to_be_visible()
    harness.settle()
    assert harness.page.get_by_role("dialog").count() == 1
    assert len(harness.agreement.checks) == 2, "The second click must not start a second check."
    harness.accept()
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    assert len(harness.uploads) == 2


def test_cancelling_the_agreement_for_a_retry_keeps_the_failed_file_to_retry_later(harness):
    harness.upload_failures = [503]
    harness.open_composer()
    harness.chat_input.set_input_files(text_file())
    harness.accept()
    retry = harness.page.get_by_role("button", name="Retry policy.txt", exact=True)
    retry.click()
    expect(harness.dialog).to_be_visible()
    harness.cancel()
    expect(harness.dialog).to_have_count(0)
    expect(retry).to_be_visible()
    assert len(harness.uploads) == 1
    retry.click()
    harness.accept()
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()


def test_leaving_the_composer_while_the_agreement_is_open_uploads_nothing(harness):
    harness.open_composer()
    harness.chat_input.set_input_files(text_file())
    expect(harness.dialog).to_be_visible()
    harness.page.evaluate("() => window.AgreementHarness.unmount()")
    expect(harness.dialog).to_have_count(0)
    harness.settle()
    assert harness.uploads == [] and harness.agreement.accepts == []


def test_a_file_chosen_in_one_conversation_is_not_sent_to_another_one(harness):
    harness.open_composer()
    harness.chat_input.set_input_files(text_file())
    expect(harness.dialog).to_be_visible()
    harness.page.evaluate("() => window.AgreementHarness.moveComposer('conv-2')")
    # The person accepts, but the composer is now in another conversation, so the file is not attached to it.
    harness.accept()
    expect(harness.dialog).to_have_count(0)
    # The person is told, rather than left to find the file missing.
    expect(harness.page.get_by_role("alert").filter(has_text=LEFT_CONVERSATION)).to_be_visible()
    harness.settle()
    assert harness.uploads == []
    expect(harness.attached).to_have_count(0)
    assert len(harness.agreement.accepts) == 1


def test_the_dialog_fits_a_phone_and_its_actions_stay_reachable(harness):
    harness.agreement.text = "\n\n".join(f"Clause {number}: you agree to the terms of clause {number}." for number in range(40))
    harness.open_composer(width=390, height=780)
    harness.chat_input.set_input_files(text_file())
    expect(harness.dialog).to_be_visible()
    box = harness.dialog.locator("xpath=./*").first.bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= 390, box
    assert box["y"] >= 0 and box["y"] + box["height"] <= 780, box
    assert harness.page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
    for name in ("Cancel", "Accept"):
        button = harness.dialog.get_by_role("button", name=name, exact=True)
        expect(button).to_be_visible()
        button_box = button.bounding_box()
        assert button_box["x"] >= 0 and button_box["x"] + button_box["width"] <= 390, (name, button_box)
        assert button_box["y"] + button_box["height"] <= 780, (name, button_box)
    harness.accept()
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()


# Holding Send while the agreement is settled ----------------------------------------------------
#
# A file waits on the agreement before it has a chip, so for that wait nothing in the draft says an upload
# is coming. The chat composer holds Enter and Send from the gate's `pending` flag meanwhile. Without it a
# message went without its file, and the file that arrived afterwards had nowhere to go.


def start_held_upload(
    harness, *, conversation="conv-1", width=1280, message="Summarise the attached policy.", entry="paste",
):
    """A person types, adds a file, and is waiting on a check the network has not answered."""
    harness.hold_checks = True
    harness.open_chat(conversation, width=width)
    harness.composer.fill(message)
    if entry == "paste":
        harness.paste_file()
    elif entry == "drop":
        harness.drop_files("policy.txt")
    else:
        harness.chat_composer_input.set_input_files(text_file())
    harness.wait_for(lambda: len(harness.held_checks) == 1, "the check was never made")
    return message


@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize("conversation", [None, "conv-1"], ids=["new-chat", "open-conversation"])
def test_enter_while_the_check_runs_sends_nothing_and_the_file_still_goes_with_the_message(
    harness, conversation, width,
):
    message = start_held_upload(harness, conversation=conversation, width=width)

    # The file has no chip yet. Send says why it is held, as text and to assistive technology, and Enter
    # does nothing: the message is still in the box, and no conversation has been made.
    expect(harness.held_notice).to_be_visible()
    expect(harness.send).to_be_disabled()
    expect(harness.send).to_have_accessible_description(PENDING)
    harness.composer.press("Enter")
    harness.settle()
    assert harness.sends == []
    assert harness.sequence() == [f"GET {CHECK_PATH}"]
    expect(harness.composer).to_have_value(message)
    expect(harness.attached).to_have_count(0)
    if width == 390:
        assert harness.page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
        for locator in (harness.held_notice, harness.send_button):
            box = locator.bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= 390, box

    # The check says no agreement applies: the chip appears, the file uploads, and only then can Send go.
    harness.release_check(NO_AGREEMENT)
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    expect(harness.held_notice).to_have_count(0)
    expect(harness.send).to_be_enabled()
    expect(harness.send_button).not_to_have_attribute("title", PENDING)
    harness.send.click()
    harness.wait_for(lambda: len(harness.sends) == 1, "the message was never sent")
    assert harness.sends[0]["message"] == message
    sequence = harness.sequence()
    assert sequence[:2] == [f"GET {CHECK_PATH}", "POST /upload"], sequence
    assert sequence.index(f"POST {SEND_PATH}") > sequence.index("POST /upload"), sequence
    assert harness.uploads == [{"kind": "chat", "path": "/upload", "files": ["policy.txt"]}]


@pytest.mark.parametrize("entry", ["choose", "drop"])
def test_choosing_or_dropping_a_file_holds_send_while_the_check_runs_like_pasting_does(harness, entry):
    message = start_held_upload(harness, entry=entry)
    expect(harness.held_notice).to_be_visible()
    expect(harness.send).to_be_disabled()
    harness.composer.press("Enter")
    harness.settle()
    assert harness.sends == []
    expect(harness.composer).to_have_value(message)

    harness.release_check(NO_AGREEMENT)
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    expect(harness.send).to_be_enabled()
    harness.send.click()
    harness.wait_for(lambda: len(harness.sends) == 1, "the message was never sent")
    assert harness.uploads == [{"kind": "chat", "path": "/upload", "files": ["policy.txt"]}]
    assert harness.sequence().index(f"POST {SEND_PATH}") > harness.sequence().index("POST /upload")


@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize("outcome", ["agreement", "unavailable"])
def test_an_open_dialog_keeps_send_held_and_cancel_releases_it_with_nothing_uploaded(harness, outcome, width):
    if outcome == "unavailable":
        harness.agreement.check_failures = [503]
    message = "Summarise the attached policy."
    harness.open_chat("conv-1", width=width)
    harness.composer.fill(message)
    harness.paste_file()
    dialog = harness.dialog if outcome == "agreement" else harness.unavailable
    expect(dialog).to_be_visible()

    # Behind the dialog the message is still held. Enter cannot reach the box through the modal, so it is
    # sent to the box directly, as an assistive technology can.
    expect(harness.send_button).to_be_disabled()
    expect(harness.send_button).to_have_attribute("title", PENDING)
    harness.page.evaluate(
        "() => document.querySelector('#composer-input').dispatchEvent("
        "new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }))"
    )
    harness.settle()
    assert harness.sends == []

    # Cancel leaves the composer as it was: the message stays, the hold is gone, and nothing was uploaded.
    harness.cancel(dialog)
    expect(dialog).to_have_count(0)
    expect(harness.composer).to_have_value(message)
    expect(harness.held_notice).to_have_count(0)
    expect(harness.send).to_be_enabled()
    expect(harness.attached).to_have_count(0)
    assert harness.uploads == [] and harness.agreement.accepts == []
    harness.send.click()
    harness.wait_for(lambda: len(harness.sends) == 1, "the message was never sent")
    assert harness.sequence() == [f"GET {CHECK_PATH}", f"POST {SEND_PATH}"]


def test_accepting_releases_send_only_once_the_file_has_been_attached_and_uploaded(harness):
    message = "Summarise the attached policy."
    harness.open_chat("conv-1")
    harness.composer.fill(message)
    harness.paste_file()
    expect(harness.dialog).to_be_visible()
    expect(harness.send_button).to_be_disabled()
    harness.accept()
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    expect(harness.held_notice).to_have_count(0)
    expect(harness.send).to_be_enabled()
    harness.send.click()
    harness.wait_for(lambda: len(harness.sends) == 1, "the message was never sent")
    assert harness.sequence()[:4] == [f"GET {CHECK_PATH}", f"POST {ACCEPT_PATH}", "POST /upload", f"POST {SEND_PATH}"]


def test_two_files_dropped_in_quick_succession_keep_send_held_until_both_have_arrived(harness):
    harness.hold_checks = True
    harness.open_chat("conv-1")
    harness.composer.fill("Compare the two files.")
    harness.drop_files("a.txt")
    harness.drop_files("b.txt")
    harness.wait_for(lambda: len(harness.held_checks) == 1, "the first check was never made")
    harness.settle()
    assert len(harness.held_checks) == 1, "the second drop must wait behind the first"
    expect(harness.send).to_be_disabled()

    # The first file is attached and uploaded, but the second is still on its way: Send stays held.
    harness.release_check(NO_AGREEMENT)
    expect(harness.attached).to_have_count(1)
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    harness.wait_for(lambda: len(harness.held_checks) == 1, "the second check was never made")
    expect(harness.held_notice).to_be_visible()
    expect(harness.send).to_be_disabled()

    harness.release_check(NO_AGREEMENT)
    expect(harness.attached).to_have_count(2)
    expect(harness.attached.get_by_text("Ready", exact=True)).to_have_count(2)
    expect(harness.held_notice).to_have_count(0)
    expect(harness.send).to_be_enabled()
    assert [upload["files"] for upload in harness.uploads] == [["a.txt"], ["b.txt"]]
    assert harness.sends == []


def test_enter_pressed_on_every_frame_never_sends_before_the_file_is_attached(harness):
    """No moment between the check answering and the file reaching the draft may let a message go."""
    message = start_held_upload(harness, conversation=None)
    harness.page.evaluate(HAMMER_ENTER, {"selector": "#composer-input"})
    harness.settle()
    assert harness.sends == []
    harness.release_check(NO_AGREEMENT)
    harness.wait_for(lambda: len(harness.sends) == 1, "the message was never sent")
    harness.page.evaluate("() => { window.__enterHammer.stop = true; }")
    harness.settle()
    assert harness.page.evaluate("() => window.__enterHammer.presses") > 5
    assert len(harness.sends) == 1 and harness.sends[0]["message"] == message
    sequence = harness.sequence()
    assert sequence[:2] == [f"GET {CHECK_PATH}", "POST /upload"], sequence
    assert sequence.index(f"POST {SEND_PATH}") > sequence.index("POST /upload"), sequence


def test_leaving_the_conversation_while_the_check_runs_says_the_file_was_not_attached(harness):
    start_held_upload(harness)
    harness.page.evaluate("() => window.AgreementHarness.newChat()")
    # The check is still out, so the new chat's Send waits for it too: it is the same composer.
    harness.composer.fill("A fresh question.")
    expect(harness.send).to_be_disabled()
    expect(harness.held_notice).to_be_visible()

    harness.release_check(NO_AGREEMENT)
    expect(harness.page.get_by_role("alert").filter(has_text=LEFT_CONVERSATION)).to_be_visible()
    harness.settle()
    assert harness.uploads == []
    expect(harness.attached).to_have_count(0)
    expect(harness.composer).to_have_value("A fresh question.")
    # Nothing stays held: the new chat takes the message and sends it.
    expect(harness.held_notice).to_have_count(0)
    expect(harness.send).to_be_enabled()
    harness.send.click()
    harness.wait_for(lambda: len(harness.sends) == 1, "the message was never sent")
    assert harness.sends[0]["message"] == "A fresh question."
    assert "POST /upload" not in harness.sequence()


def test_enter_in_the_editor_is_ignored_while_a_file_waits_for_an_owner_that_does_not_read_the_flag(harness):
    """The shared editor also sits in cards that hold nothing themselves, so it must not submit early either."""
    harness.hold_checks = True
    harness.open_composer()
    submitted = harness.page.get_by_label("Submitted", exact=True)
    harness.composer.press("Enter")
    expect(submitted).to_have_text("1")

    harness.paste_file(selector="#agreement-composer")
    harness.wait_for(lambda: len(harness.held_checks) == 1, "the check was never made")
    harness.composer.press("Enter")
    harness.settle()
    expect(submitted).to_have_text("1")

    harness.release_check(NO_AGREEMENT)
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    harness.composer.press("Enter")
    expect(submitted).to_have_text("2")


def test_an_editor_that_goes_away_while_the_check_runs_does_not_leave_its_owner_held(harness):
    harness.hold_checks = True
    harness.open_composer()
    owner_sees = harness.page.get_by_label("Agreement pending", exact=True)
    expect(owner_sees).to_have_text("false")
    harness.paste_file(selector="#agreement-composer")
    harness.wait_for(lambda: len(harness.held_checks) == 1, "the check was never made")
    expect(owner_sees).to_have_text("true")

    harness.page.evaluate("() => window.AgreementHarness.removeEditor()")
    expect(harness.page.get_by_text("The editor is gone.", exact=True)).to_be_visible()
    expect(owner_sees).to_have_text("false")
    harness.settle()
    assert harness.uploads == [] and harness.agreement.accepts == []


@pytest.mark.parametrize("flag", [None, False], ids=["absent", "explicitly-off"])
def test_with_the_feature_off_send_is_never_held_and_the_upload_starts_at_once(harness, flag):
    harness.open_chat("conv-1", enabled=False, flag=flag)
    harness.page.evaluate(WATCH_HELD_SEND, {"message": PENDING})
    message = "Summarise the attached policy."
    harness.composer.fill(message)
    harness.paste_file()
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    # The held-Send wording never reached the page, not even for a frame, and nothing was asked of the server.
    assert harness.page.evaluate("() => window.__heldSend") == {"text": False, "title": False}
    assert harness.agreement.checks == [] and harness.sequence() == ["POST /upload"]
    expect(harness.send).to_be_enabled()
    harness.send.click()
    harness.wait_for(lambda: len(harness.sends) == 1, "the message was never sent")
    assert harness.sequence() == ["POST /upload", f"POST {SEND_PATH}"]


# Holding the elicitation card's controls --------------------------------------------------------
#
# A question field embeds the same editor, so a file chosen in one waits on the agreement before it has a chip
# too. Next, Review answers and Enter would otherwise move on, or send the answers, without it.


def start_held_answer(harness, **options):
    """A person types an optional note, adds a file to it, and waits on a check the network has not answered."""
    harness.hold_checks = True
    harness.open_questions(**options)
    harness.card.get_by_role("textbox", name="Notes", exact=True).fill("See the attached policy.")
    expect(harness.forward).to_be_enabled()
    harness.card_input.set_input_files(text_file())
    harness.wait_for(lambda: len(harness.held_checks) == 1, "the check was never made")


def card_page(harness, number, of=2):
    return harness.card.get_by_label(f"Question page {number} of {of}", exact=True)


def attached_ready(harness):
    return harness.card.get_by_role("list", name="Attached files", exact=True).get_by_text("Ready", exact=True)


def test_next_is_held_while_a_file_in_a_question_waits_on_the_agreement(harness):
    start_held_answer(harness)

    # Next is unavailable and the line under the buttons says why. Enter in the answer, and a submit of the form
    # itself, move nowhere. Declining and abandoning the request are not held.
    expect(harness.forward).to_be_disabled()
    expect(harness.forward).to_contain_text("Next")
    expect(harness.hint).to_have_text(PENDING)
    harness.card.get_by_role("textbox", name="Notes", exact=True).press("Enter")
    harness.page.evaluate("() => document.querySelector('section[aria-label=\"Follow-up questions\"] form').requestSubmit()")
    harness.settle()
    expect(card_page(harness, 1)).to_be_visible()
    assert harness.answers == []
    expect(harness.card.get_by_role("button", name="Decline to answer", exact=True)).to_be_enabled()
    expect(harness.card.get_by_role("button", name="Cancel and abandon this request", exact=True)).to_be_enabled()

    # The check says no agreement applies: the chip appears and uploads, and Next goes on.
    harness.release_check(NO_AGREEMENT)
    expect(attached_ready(harness)).to_be_visible()
    expect(harness.forward).to_be_enabled()
    expect(harness.hint).to_have_count(0)
    harness.forward.click()
    expect(card_page(harness, 2)).to_be_visible()
    assert harness.uploads == [{"kind": "chat", "path": "/upload", "files": ["policy.txt"]}]


def test_review_answers_and_use_these_answers_work_once_the_check_has_answered(harness):
    one_page = questions(pages=(("notes",),))
    start_held_answer(harness, question=one_page)
    expect(harness.forward).to_be_disabled()
    expect(harness.forward).to_contain_text("Review answers")
    expect(harness.hint).to_have_text(PENDING)

    harness.release_check(NO_AGREEMENT)
    expect(attached_ready(harness)).to_be_visible()
    expect(harness.forward).to_be_enabled()
    harness.forward.click()
    expect(harness.card.get_by_role("heading", name="Review your answers", exact=True)).to_be_visible()
    expect(harness.forward).to_contain_text("Use these answers")
    assert harness.answers == [], "reviewing is not submitting"
    harness.forward.click()
    harness.wait_for(lambda: len(harness.answers) == 1, "the answers were never sent")
    response = harness.answers[0]["elicitation_response"]
    assert response["action"] == "accept" and response["content"]["notes"].startswith("See the attached policy.")
    assert harness.uploads == [{"kind": "chat", "path": "/upload", "files": ["policy.txt"]}]


def test_an_open_dialog_keeps_the_card_held_and_cancel_releases_it(harness):
    harness.open_questions()
    harness.card.get_by_role("textbox", name="Notes", exact=True).fill("See the attached policy.")
    harness.card_input.set_input_files(text_file())
    expect(harness.dialog).to_be_visible()
    expect(harness.forward).to_be_disabled()
    expect(harness.hint).to_have_text(PENDING)

    harness.cancel()
    expect(harness.dialog).to_have_count(0)
    expect(harness.forward).to_be_enabled()
    expect(harness.hint).to_have_count(0)
    expect(harness.attached).to_have_count(0)
    assert harness.uploads == [] and harness.agreement.accepts == []
    harness.forward.click()
    expect(card_page(harness, 2)).to_be_visible()


def test_accepting_in_a_question_attaches_the_file_and_releases_the_card(harness):
    harness.open_questions()
    harness.card.get_by_role("textbox", name="Notes", exact=True).fill("See the attached policy.")
    harness.card_input.set_input_files(text_file())
    expect(harness.dialog).to_be_visible()
    expect(harness.forward).to_be_disabled()
    harness.accept()
    expect(attached_ready(harness)).to_be_visible()
    expect(harness.forward).to_be_enabled()
    expect(harness.hint).to_have_count(0)
    assert harness.sequence() == [f"GET {CHECK_PATH}", f"POST {ACCEPT_PATH}", "POST /upload"]


def test_going_back_while_a_file_waits_releases_the_hold(harness):
    harness.hold_checks = True
    harness.open_questions(questions(pages=(("format",), ("notes",))))
    harness.card.get_by_role("radio", name="Summary", exact=True).check()
    harness.forward.click()
    expect(card_page(harness, 2)).to_be_visible()
    harness.card.get_by_role("textbox", name="Notes", exact=True).fill("See the attached policy.")
    harness.card_input.set_input_files(text_file())
    harness.wait_for(lambda: len(harness.held_checks) == 1, "the check was never made")
    expect(harness.forward).to_be_disabled()

    # Back is not held. The field goes away with its hold, and the file that was waiting is not sent.
    back = harness.card.get_by_role("button", name="Back", exact=True)
    expect(back).to_be_enabled()
    back.click()
    expect(card_page(harness, 1)).to_be_visible()
    expect(harness.forward).to_be_enabled()
    expect(harness.hint).to_have_count(0)
    harness.settle()
    assert harness.uploads == []


def test_a_new_revision_of_the_question_starts_with_nothing_held(harness):
    start_held_answer(harness)
    expect(harness.forward).to_be_disabled()
    harness.page.evaluate("(question) => window.AgreementHarness.reviseQuestions(question)", questions(revision=1))
    expect(card_page(harness, 1)).to_be_visible()
    expect(harness.forward).to_be_enabled()
    expect(harness.hint).to_have_count(0)
    harness.settle()
    assert harness.uploads == []


def test_declining_is_not_held_while_a_file_waits(harness):
    start_held_answer(harness)
    expect(harness.forward).to_be_disabled()
    harness.card.get_by_role("button", name="Decline to answer", exact=True).click()
    harness.wait_for(lambda: len(harness.answers) == 1, "the decline was never sent")
    assert harness.answers[0]["elicitation_response"] == {"action": "decline", "content": {}}
    assert harness.uploads == []


def test_with_the_feature_off_the_card_is_never_held(harness):
    harness.open_questions(enabled=False)
    harness.page.evaluate(WATCH_HELD_SEND, {"message": PENDING})
    harness.card.get_by_role("textbox", name="Notes", exact=True).fill("See the attached policy.")
    harness.card_input.set_input_files(text_file())
    expect(attached_ready(harness)).to_be_visible()
    assert harness.page.evaluate("() => window.__heldSend") == {"text": False, "title": False}
    assert harness.agreement.checks == [] and harness.sequence() == ["POST /upload"]
    expect(harness.forward).to_be_enabled()
    expect(harness.hint).to_have_count(0)


# A check or an acceptance that never answers ---------------------------------------------------
#
# request() has no time limit of its own, so one that never answered held Send for good, or kept the dialog open
# with Cancel ignored while it was out. Both now run out of time, and take the path of any other failure. The
# page's clock is faked, so the limit is reached by jumping it and no test waits twenty seconds.


def test_a_check_that_never_answers_fails_after_the_time_limit_and_cancel_releases_send(harness):
    harness.hold_checks = True
    harness.open_chat("conv-1", clock=True)
    message = "Summarise the attached policy."
    harness.composer.fill(message)
    harness.paste_file()
    harness.wait_for(lambda: len(harness.held_checks) == 1, "the check was never made")
    expect(harness.send).to_be_disabled()
    expect(harness.held_notice).to_be_visible()

    # Well inside the limit nothing has changed. Past it, the check has failed: the dialog says so and offers
    # Try again and Cancel, and Send is still held behind it.
    harness.page.clock.fast_forward(10_000)
    harness.settle()
    expect(harness.unavailable).to_have_count(0)
    harness.page.clock.fast_forward(15_000)
    expect(harness.unavailable).to_be_visible()
    expect(harness.unavailable).to_contain_text("We could not confirm whether a user agreement applies")
    expect(harness.unavailable).to_contain_text(TIMED_OUT)
    expect(harness.unavailable.get_by_role("button", name="Try again", exact=True)).to_be_enabled()
    expect(harness.send_button).to_be_disabled()

    # Cancel releases Send. The message is as it was, and nothing was uploaded.
    harness.cancel(harness.unavailable)
    expect(harness.unavailable).to_have_count(0)
    expect(harness.held_notice).to_have_count(0)
    expect(harness.send).to_be_enabled()
    expect(harness.composer).to_have_value(message)
    assert harness.uploads == [] and harness.agreement.accepts == []
    harness.send.click()
    harness.wait_for(lambda: len(harness.sends) == 1, "the message was never sent")


def test_try_again_after_a_timed_out_check_asks_again(harness):
    harness.hold_checks = True
    harness.open_chat("conv-1", clock=True)
    harness.composer.fill("Summarise the attached policy.")
    harness.paste_file()
    harness.wait_for(lambda: len(harness.held_checks) == 1, "the check was never made")
    harness.page.clock.fast_forward(TIME_LIMIT_MS + 5_000)
    expect(harness.unavailable).to_be_visible()

    # Each try has a limit of its own. The request the page gave up on is not answered.
    for attempt in (2, 3):
        harness.held_checks.clear()
        harness.unavailable.get_by_role("button", name="Try again", exact=True).click()
        harness.wait_for(lambda: len(harness.held_checks) == 1, f"the check was not asked again (try {attempt})")
        if attempt == 2:
            harness.page.clock.fast_forward(TIME_LIMIT_MS + 5_000)
            expect(harness.unavailable).to_contain_text(TIMED_OUT)
    harness.release_check(NO_AGREEMENT)
    expect(harness.attached.get_by_text("Ready", exact=True)).to_be_visible()
    expect(harness.send).to_be_enabled()
    assert harness.uploads == [{"kind": "chat", "path": "/upload", "files": ["policy.txt"]}]


def test_an_acceptance_that_never_answers_fails_after_the_time_limit_and_is_not_reported_as_accepted(harness):
    harness.hold_accept = True
    harness.open_chat("conv-1", clock=True)
    message = "Summarise the attached policy."
    harness.composer.fill(message)
    harness.paste_file()
    expect(harness.dialog).to_be_visible()
    harness.accept()
    harness.wait_for(lambda: len(harness.held_accepts) == 1, "the acceptance was never sent")
    # While it is out the dialog cannot be dismissed, as before.
    expect(harness.dialog.get_by_role("button", name="Cancel", exact=True)).to_be_disabled()

    harness.page.clock.fast_forward(TIME_LIMIT_MS + 5_000)
    alert = harness.dialog.get_by_role("alert")
    expect(alert).to_contain_text("Your acceptance could not be recorded")
    expect(alert).to_contain_text(TIMED_OUT)
    # Nothing was reported as accepted: no chip, no upload, and the dialog is still asking.
    expect(harness.attached).to_have_count(0)
    assert harness.uploads == []
    expect(harness.dialog.get_by_role("button", name="Cancel", exact=True)).to_be_enabled()
    expect(harness.dialog.get_by_role("button", name="Accept", exact=True)).to_be_enabled()
    expect(harness.send_button).to_be_disabled()

    # Cancel works again, and releases Send.
    harness.cancel()
    expect(harness.dialog).to_have_count(0)
    expect(harness.send).to_be_enabled()
    expect(harness.composer).to_have_value(message)
    assert harness.uploads == []


# Workspace documents --------------------------------------------------------------------------


@pytest.mark.parametrize("kind, workspace_id", [
    ("personal", "default"), ("group", "group-a"), ("public", "public-a"),
])
def test_a_workspace_upload_asks_about_the_workspace_it_is_going_to(harness, kind, workspace_id):
    harness.open_explorer(kind)
    expect(harness.page.get_by_role("button", name="Upload", exact=True).first).to_be_enabled()
    harness.explorer_input.set_input_files(text_file("report.txt"))

    expect(harness.dialog).to_be_visible()
    assert harness.agreement.checks == [{
        "workspace_type": kind, "workspace_id": workspace_id, "action_context": "file_upload",
    }]
    assert harness.uploads == []

    harness.accept()
    harness.wait_for(lambda: len(harness.uploads) == 1, "The accepted upload was not sent.")
    expect(harness.dialog).to_have_count(0)
    assert harness.agreement.accepts == [{
        "workspace_type": kind, "workspace_id": workspace_id, "action_context": "file_upload",
    }]
    assert harness.uploads == [{"kind": kind, "path": UPLOAD_PATHS[kind], "files": ["report.txt"]}]
    assert harness.sequence() == [f"GET {CHECK_PATH}", f"POST {ACCEPT_PATH}", f"POST {UPLOAD_PATHS[kind]}"]


@pytest.mark.parametrize("kind", ["personal", "group", "public"])
def test_cancelling_a_workspace_upload_sends_nothing(harness, kind):
    harness.open_explorer(kind)
    harness.explorer_input.set_input_files(text_file("report.txt"))
    expect(harness.dialog).to_be_visible()
    harness.cancel()
    expect(harness.dialog).to_have_count(0)
    harness.settle()
    assert harness.uploads == [] and harness.agreement.accepts == []
    expect(harness.page.get_by_text("Accepted 1 of 1 files.", exact=False)).to_have_count(0)
    # The Upload command is still there to try again.
    expect(harness.page.get_by_role("button", name="Upload", exact=True).first).to_be_enabled()


def test_the_upload_button_and_dropping_on_the_explorer_are_both_gated(harness):
    harness.open_explorer("personal")
    with harness.page.expect_file_chooser() as chooser:
        harness.page.get_by_role("button", name="Upload", exact=True).first.click()
    chooser.value.set_files(text_file("picked.txt"))
    expect(harness.dialog).to_be_visible()
    # Focus returns to the control that opened the file picker.
    harness.cancel()
    expect(harness.page.get_by_role("button", name="Upload", exact=True).first).to_be_focused()

    harness.page.evaluate(
        DROP_FILES,
        {"selector": '[role="region"][aria-label="Workspace documents"]', "files": [{"name": "dropped.txt", "body": "dropped"}]},
    )
    expect(harness.dialog).to_be_visible()
    assert harness.uploads == []
    harness.accept()
    harness.wait_for(lambda: len(harness.uploads) == 1, "The accepted drop was not sent.")
    assert harness.uploads[0]["files"] == ["dropped.txt"]


def test_a_workspace_upload_is_held_when_the_check_fails_and_goes_ahead_after_a_retry(harness):
    harness.agreement.check_failures = [502]
    harness.open_explorer("group")
    harness.explorer_input.set_input_files(text_file("report.txt"))
    expect(harness.unavailable).to_be_visible()
    harness.settle()
    assert harness.uploads == []
    harness.unavailable.get_by_role("button", name="Try again", exact=True).click()
    expect(harness.dialog).to_be_visible()
    harness.accept()
    harness.wait_for(lambda: len(harness.uploads) == 1, "The upload did not go ahead after the retry.")
    assert harness.uploads[0]["kind"] == "group"


def test_a_file_the_explorer_refuses_never_triggers_the_agreement(harness):
    harness.max_file_size_mb = 1
    harness.open_explorer("personal")
    harness.explorer_input.set_input_files(
        {"name": "huge.txt", "mimeType": "text/plain", "buffer": b"x" * (2 * 1024 * 1024)},
    )
    expect(harness.page.get_by_text("huge.txt exceeds the 1 MB limit.", exact=True)).to_be_visible()
    harness.settle()
    assert harness.sequence() == []
    expect(harness.dialog).to_have_count(0)


def test_with_the_feature_off_a_workspace_upload_asks_nothing(harness):
    harness.open_explorer("public", enabled=False)
    harness.explorer_input.set_input_files(text_file("report.txt"))
    harness.wait_for(lambda: len(harness.uploads) == 1, "The upload was not sent.")
    assert harness.sequence() == [f"POST {UPLOAD_PATHS['public']}"]
    assert harness.agreement.checks == []


def test_leaving_the_explorer_while_the_agreement_is_open_uploads_nothing(harness):
    harness.open_explorer("personal")
    harness.explorer_input.set_input_files(text_file("report.txt"))
    expect(harness.dialog).to_be_visible()
    harness.page.evaluate("() => window.AgreementHarness.unmount()")
    expect(harness.dialog).to_have_count(0)
    harness.settle()
    assert harness.uploads == [] and harness.agreement.accepts == []


def test_the_workspace_dialog_fits_a_phone(harness):
    harness.open_explorer("personal", width=390, height=780)
    harness.explorer_input.set_input_files(text_file("report.txt"))
    expect(harness.dialog).to_be_visible()
    box = harness.dialog.locator("xpath=./*").first.bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= 390 and box["y"] + box["height"] <= 780, box
    assert harness.page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
    harness.accept()
    harness.wait_for(lambda: len(harness.uploads) == 1, "The accepted upload was not sent.")
