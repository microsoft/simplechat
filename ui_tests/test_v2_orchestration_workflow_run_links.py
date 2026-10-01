# test_v2_orchestration_workflow_run_links.py
"""
Real-component browser tests for the run links under an answer whose plan started saved workflows.
Version: 0.261.212
Implemented in: 0.261.212
Refs: microsoft/simplechat#1551

The production MessageList and WorkflowRunLinks run in Chromium with the production CSS, and the
last test runs the real built SPA from the chat page to the Workflows page. Only HTTP boundaries
are stubbed. The link responses follow the shape of
`GET /api/v2/orchestration/runs/<run>/workflow-runs` (functions_orchestration_workflow_run_links).
The server side of every decision (requester only, private conversations only, the status
mapping, a deleted workflow or a missing run) is covered by
`functional_tests/test_orchestration_workflow_run_link_routes.py`, and the response checks by
`functional_tests/test_v2_orchestration_workflow_run_links.mjs`.

Build CSS with the existing V2 build, keeping outputs in UI test artifacts:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
The last test also needs the production bundle the app serves:
npm --prefix .\\application\\v2_ui run build
Run: python -m pytest .\\ui_tests\\test_v2_orchestration_workflow_run_links.py -q
"""

import copy
import sys
from pathlib import Path
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402
from ui_tests.fixtures.workflow_editor import WORKFLOW_ID, WorkflowEditorFixture  # noqa: E402
from ui_tests.fixtures.workspace_authoring import ORIGIN as SPA_ORIGIN  # noqa: E402


pytestmark = pytest.mark.ui
IMPLEMENTED_IN = "0.261.212"
CONVERSATION = "run-link-chat"
TURN = "run-link-turn"
RUN_ID = "run-link-run-1"
LINKS_PATH = f"/api/v2/orchestration/runs/{RUN_ID}/workflow-runs"
NAME = "Weekly digest"
HOSTILE_NAME = '<img src=x onerror="window.__hostile = 1"> Weekly <b>digest</b> & {{7*7}}'
LOAD_ERROR = "Could not load the workflow runs this plan started."
FOOTNOTE = "Status when this message loaded. Open the run for its progress and results."
DELETED_TEXT = "This workflow was deleted, so its run cannot be opened."
STATE_LABELS = {
    "queued": "Queued", "running": "Running", "waiting": "Waiting", "completed": "Completed",
    "completed_partial": "Partly completed", "failed": "Failed", "cancelled": "Cancelled",
    "skipped": "Skipped",
}


def started(step_id, state="queued", *, name=NAME, workflow_id=None, run_id=None):
    """A link to a run the plan started, as the link route describes it."""
    return {
        "step_id": step_id, "name": name, "state": state, "reason": None,
        "workflow_id": workflow_id or f"wf-{step_id}", "workflow_run_id": run_id or f"wr-{step_id}",
    }


def unavailable(step_id, reason, *, name=""):
    """A run the reader cannot open here: never linked, and always with the closed reason."""
    return {
        "step_id": step_id, "name": name, "state": "unavailable", "reason": reason,
        "workflow_id": None, "workflow_run_id": None,
    }


def run_href(workflow_id, run_id):
    return f"/workspace/workflows?workflow_id={workflow_id}&run_id={run_id}"


class LinksApi:
    """The link route for one run, answered from `self.items` the way the server decides."""

    def __init__(self, assets):
        self.assets = assets
        self.items = [started("run_digest")]
        self.body = None
        self.status_error = None
        self.reads = []
        self.proposal_reads = []
        self.unexpected = []
        self.expected_errors = set()

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(request.url)
            route.abort()
            return
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
            return
        if path == LINKS_PATH and request.method == "GET":
            self.reads.append(parsed.query)
            if parsed.query != f"conversation_id={CONVERSATION}":
                self.unexpected.append(f"GET {path}?{parsed.query}")
            if self.status_error == 404:
                self.expected_errors.add((path, 404))
                route.fulfill(status=404, json={"error": "Orchestration run not found.", "code": "run_not_found"})
            elif self.status_error:
                self.expected_errors.add((path, self.status_error))
                route.fulfill(status=self.status_error, json={
                    "error": "Workflow run links are unavailable right now.", "code": "unavailable",
                })
            else:
                route.fulfill(json=copy.deepcopy(self.body) if self.body is not None else {
                    "run_id": RUN_ID, "workflow_runs": copy.deepcopy(self.items),
                })
            return
        if path == f"/api/v2/orchestration/runs/{RUN_ID}/workflow-proposals" and request.method == "GET":
            # An answer whose plan proposed a workflow mounts the proposal card, which reads its own route.
            self.proposal_reads.append(parsed.query)
            route.fulfill(json={"run_id": RUN_ID, "proposals": []})
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unmocked request"})


@pytest.fixture
def links_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = LinksApi(editor_assets)
    errors = []
    dialogs = []
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: errors.append(str(error)))

    def on_dialog(dialog):
        dialogs.append(dialog.message)
        dialog.dismiss()

    page.on("dialog", on_dialog)

    def console_error(message):
        if message.type != "error":
            return
        path = urlsplit(message.location.get("url", "")).path
        if any(path == expected and str(status) in message.text for expected, status in api.expected_errors):
            return
        errors.append(message.text)

    page.on("console", console_error)
    try:
        yield page, api
        hostile = page.evaluate("() => window.__hostile ?? null")
        assert hostile is None, hostile
    finally:
        context.close()
    assert not api.unexpected, f"Unexpected browser requests: {api.unexpected}"
    assert not errors, f"Unexpected browser errors: {errors}"
    assert not dialogs, f"Unexpected browser dialogs: {dialogs}"


def answer(*, conversation=CONVERSATION, masked=False, capabilities=("compose", "workflow_run")):
    metadata = {"orchestration": {
        "run_id": RUN_ID, "turn_id": TURN, "outcome": "completed", "finalization_status": "saved",
        "message_saved": True,
        "plan_summary": {
            "plan_id": "run-link-plan", "turn_id": TURN, "status": "completed",
            "intent_summary": "Run my weekly digest now", "step_count": 2,
            "capabilities_used": list(capabilities),
        },
    }}
    if masked:
        metadata["masked_ranges"] = [{"start": 0, "end": 5}]
    return [
        {"id": "user-1", "conversation_id": conversation, "role": "user",
         "content": "Run my weekly digest now.", "metadata": {"orchestration_turn_id": TURN}},
        {"id": "answer-1", "conversation_id": conversation, "role": "assistant",
         "content": "Started `Weekly digest`. Its results appear on the run page.", "metadata": metadata},
    ]


def mount(page, api, *, kind="personal", theme="light", messages=None):
    page.goto(ORIGIN + HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=ORIGIN + url)
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            document.documentElement.classList.toggle('dark', spec.theme === 'dark');
            H.stores.bootstrap.useBootstrapStore.setState({ data: {
                version: '0.261.212', settings: {}, branding: { app_title: 'SimpleChat' },
                features: { enable_chat_orchestration: true },
                user: { id: 'run-link-tester', display_name: 'Run Link Tester' },
                scope: { groups: [], public_workspaces: [] },
                orchestration: { enabled: true, capabilities: [] },
                catalogs: { models: [], agents: [], prompts: [] },
            } });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation, activeConversationKind: spec.kind,
                messagesLoading: false, messagesError: null, streaming: false, streamingContent: '',
                streamError: null, thoughts: [], messages: spec.messages,
                conversations: [{ id: spec.conversation, title: 'Weekly digest' }],
            });
            H.mount('mount-a', 'MessageList', {}, { strictMode: true });
        }""",
        {"conversation": CONVERSATION, "kind": kind, "theme": theme,
         "messages": messages if messages is not None else answer()},
    )
    expect(page.get_by_text("Run my weekly digest now.", exact=True)).to_be_visible()


def links(page):
    region = page.get_by_role("region", name="Started workflows")
    expect(region).to_be_visible()
    return region


def run_item(region, name):
    item = region.get_by_role("listitem").filter(has=region.page.get_by_text(name, exact=True))
    expect(item).to_have_count(1)
    return item


def wait_for(page, predicate, message):
    for _ in range(200):
        if predicate():
            return
        page.wait_for_timeout(25)
    raise AssertionError(message)


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least(IMPLEMENTED_IN)


@pytest.mark.parametrize("theme,width", [("light", 1440), ("dark", 390)])
def test_each_run_is_named_with_its_status_and_a_link_to_it(links_ui, theme, width):
    page, api = links_ui
    page.set_viewport_size({"width": width, "height": 900})
    api.items = [
        started("run_digest", "queued", name=HOSTILE_NAME),
        started("run_report", "completed", name="Monthly report"),
        unavailable("run_old", "workflow_deleted", name="Old digest"),
    ]
    mount(page, api, theme=theme)
    region = links(page)
    expect(region.get_by_role("listitem")).to_have_count(3)

    # The workflow's own name is shown exactly as written and never becomes markup.
    digest = run_item(region, HOSTILE_NAME)
    expect(digest).to_contain_text("Started workflow")
    expect(digest.get_by_text("Queued", exact=True)).to_be_visible()
    open_digest = digest.get_by_role("link", name=f"Open run of {HOSTILE_NAME}", exact=True)
    expect(open_digest).to_have_text("Open run")
    expect(open_digest).to_have_attribute("href", run_href("wf-run_digest", "wr-run_digest"))
    for tag in ("img", "b", "script"):
        expect(region.locator(tag)).to_have_count(0)

    report = run_item(region, "Monthly report")
    expect(report.get_by_text("Completed", exact=True)).to_be_visible()
    expect(report.get_by_role("link", name="Open run of Monthly report", exact=True)).to_have_attribute(
        "href", run_href("wf-run_report", "wr-run_report"),
    )

    # A run that cannot be opened says why in fixed words, and is never linked.
    old = run_item(region, "Old digest")
    expect(old.get_by_text("Unavailable", exact=True)).to_be_visible()
    expect(old).to_contain_text(DELETED_TEXT)
    expect(old.get_by_role("link")).to_have_count(0)

    expect(region).to_contain_text(FOOTNOTE)
    expect(region.get_by_role("link")).to_have_count(2)
    assert region.evaluate("(element) => element.scrollWidth <= element.clientWidth + 1")
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")


@pytest.mark.parametrize("state", list(STATE_LABELS))
def test_every_started_state_reads_as_its_status_and_stays_linked(links_ui, state):
    page, api = links_ui
    api.items = [started("run_digest", state)]
    mount(page, api)
    item = run_item(links(page), NAME)
    expect(item.get_by_text(STATE_LABELS[state], exact=True)).to_be_visible()
    expect(item.get_by_role("link", name=f"Open run of {NAME}", exact=True)).to_have_attribute(
        "href", run_href("wf-run_digest", "wr-run_digest"),
    )


@pytest.mark.parametrize("reason,name,shown,text", [
    ("workflow_run_missing", NAME, NAME, "This run is no longer in the workflow's run history."),
    ("workflow_shared_conversation", "", "Saved workflow",
     "Links to workflow runs appear only in your own conversations."),
    ("workflow_role_required", "", "Saved workflow", "You no longer have access to personal workflows."),
    ("a_reason_added_later", "", "Saved workflow", "This workflow run is not available."),
])
def test_a_run_that_cannot_be_opened_says_why_in_fixed_words(links_ui, reason, name, shown, text):
    page, api = links_ui
    api.items = [unavailable("run_digest", reason, name=name)]
    mount(page, api)
    region = links(page)
    item = run_item(region, shown)
    expect(item.get_by_text("Unavailable", exact=True)).to_be_visible()
    expect(item).to_contain_text(text)
    expect(region.get_by_role("link")).to_have_count(0)


def test_open_run_is_reached_by_keyboard_with_a_visible_focus_ring(links_ui):
    page, api = links_ui
    api.items = [started("run_digest", "running"), started("run_report", "queued", name="Monthly report")]
    mount(page, api)
    region = links(page)
    first = region.get_by_role("link", name=f"Open run of {NAME}", exact=True)
    second = region.get_by_role("link", name="Open run of Monthly report", exact=True)
    expect(first).to_be_visible()
    # Reach the first link from the control before it, the way a keyboard user does.
    first.focus()
    page.keyboard.press("Shift+Tab")
    expect(first).not_to_be_focused()
    page.keyboard.press("Tab")
    expect(first).to_be_focused()
    ring = first.evaluate(
        "(element) => { const style = getComputedStyle(element);"
        " return { style: style.outlineStyle, width: style.outlineWidth }; }"
    )
    assert ring["style"] != "none" and ring["width"] != "0px", ring
    page.keyboard.press("Tab")
    expect(second).to_be_focused()


def test_nothing_polls_and_a_reload_reads_the_status_again(links_ui):
    page, api = links_ui
    page.clock.install()
    mount(page, api)
    expect(run_item(links(page), NAME).get_by_text("Queued", exact=True)).to_be_visible()
    # Strict mode mounts effects twice in development, so the first read may be cancelled and
    # repeated once; after that, nothing reads again however long the answer stays open.
    page.wait_for_timeout(300)
    settled = len(api.reads)
    assert 1 <= settled <= 2, api.reads
    page.clock.run_for(10 * 60 * 1000)
    page.wait_for_timeout(300)
    assert len(api.reads) == settled, "The links polled the runs."

    api.items = [started("run_digest", "completed")]
    mount(page, api)
    expect(run_item(links(page), NAME).get_by_text("Completed", exact=True)).to_be_visible()
    assert len(api.reads) > settled


def test_a_failed_read_offers_try_again(links_ui):
    page, api = links_ui
    api.status_error = 503
    mount(page, api)
    region = links(page)
    alert = region.get_by_role("alert")
    expect(alert).to_contain_text(LOAD_ERROR)
    expect(region.get_by_role("link")).to_have_count(0)
    api.status_error = None
    before = len(api.reads)
    retry = alert.get_by_role("button", name="Try again", exact=True)
    retry.focus()
    page.keyboard.press("Enter")
    expect(run_item(links(page), NAME).get_by_text("Queued", exact=True)).to_be_visible()
    expect(region.get_by_role("alert")).to_have_count(0)
    assert len(api.reads) == before + 1


@pytest.mark.parametrize("body", [
    {"run_id": "another-run", "workflow_runs": [started("run_digest")]},
    {"run_id": RUN_ID, "workflow_runs": [{**started("run_digest"), "reason": "workflow_deleted"}]},
    {"run_id": RUN_ID, "workflow_runs": [{**unavailable("run_digest", "workflow_deleted"), "workflow_id": "wf-x"}]},
], ids=["another-run", "started-with-a-reason", "unavailable-with-ids"])
def test_a_response_of_the_wrong_shape_links_nothing(links_ui, body):
    page, api = links_ui
    api.body = body
    mount(page, api)
    region = links(page)
    expect(region.get_by_role("alert")).to_contain_text(LOAD_ERROR)
    expect(region.get_by_role("link")).to_have_count(0)
    expect(region.get_by_role("listitem")).to_have_count(0)


@pytest.mark.parametrize("status_error,items", [(404, None), (None, [])], ids=["not-found", "nothing-started"])
def test_a_run_with_nothing_to_show_renders_nothing(links_ui, status_error, items):
    page, api = links_ui
    api.status_error = status_error
    if items is not None:
        api.items = items
    mount(page, api)
    wait_for(page, lambda: api.reads, "The links never asked for the runs.")
    page.wait_for_timeout(300)
    expect(page.get_by_role("region", name="Started workflows")).to_have_count(0)
    expect(page.get_by_role("alert")).to_have_count(0)


@pytest.mark.parametrize("kind,messages", [
    ("collaborative", answer()),
    ("personal", answer(capabilities=("compose",))),
    ("personal", answer(capabilities=("compose", "workflow_propose"))),
    ("personal", answer(masked=True)),
    ("personal", answer(conversation="another-chat")),
], ids=["shared-conversation", "no-run-step", "proposal-only", "masked-answer", "another-conversation"])
def test_no_links_and_no_request_outside_a_personal_run_answer(links_ui, kind, messages):
    page, api = links_ui
    mount(page, api, kind=kind, messages=messages)
    page.wait_for_timeout(400)
    expect(page.get_by_role("region", name="Started workflows")).to_have_count(0)
    assert not api.reads, api.reads
    if kind == "personal" and "workflow_propose" in messages[1]["metadata"]["orchestration"]["plan_summary"][
        "capabilities_used"
    ]:
        # The control: the same answer still mounts the proposal card, which reads its own route.
        wait_for(page, lambda: api.proposal_reads, "The proposal card never read its proposals.")


# The real SPA: from the answer in chat to the run in the Workflows page.
SPA_CHAT_ID = "existing-workspace-chat"
SPA_RUN_ID = "run-link-spa-run"
SPA_LINKS_PATH = f"/api/v2/orchestration/runs/{SPA_RUN_ID}/workflow-runs"
SPA_WORKFLOW_RUN_ID = "5e3c2d7b-4f0a-5c51-9a8e-2f6b7c1d9e04"
SPA_WORKFLOW_NAME = "Quarterly review workflow"
SPA_HREF = run_href(WORKFLOW_ID, SPA_WORKFLOW_RUN_ID)


class ChatRunLinksFixture(WorkflowEditorFixture):
    """The chat page with an answer whose plan started a saved workflow, and that workflow's runs."""

    def __init__(self, page):
        super().__init__(page)
        metadata = {"orchestration": {
            "run_id": SPA_RUN_ID, "turn_id": TURN, "outcome": "completed", "finalization_status": "saved",
            "message_saved": True,
            "plan_summary": {
                "plan_id": "run-link-spa-plan", "turn_id": TURN, "status": "completed",
                "intent_summary": "Run my quarterly review now", "step_count": 2,
                "capabilities_used": ["compose", "workflow_run"],
            },
        }}
        self.messages[SPA_CHAT_ID] = [
            {"id": "spa-user", "role": "user", "content": "Run my quarterly review now.",
             "conversation_id": SPA_CHAT_ID, "timestamp": "2026-09-16T11:59:00Z",
             "metadata": {"orchestration_turn_id": TURN}},
            {"id": "spa-answer", "role": "assistant", "content": "Started your quarterly review.",
             "conversation_id": SPA_CHAT_ID, "timestamp": "2026-09-16T12:00:00Z", "metadata": metadata},
        ]
        self.workflow_runs[WORKFLOW_ID] = [
            {"id": "run-latest", "workflow_id": WORKFLOW_ID, "status": "completed",
             "started_at": "2026-09-17T09:00:00Z"},
            {"id": SPA_WORKFLOW_RUN_ID, "workflow_id": WORKFLOW_ID, "status": "completed",
             "started_at": "2026-09-16T12:00:00Z"},
        ]
        self.link_reads = []

    def _dispatch(self, route, entry):
        if entry.method == "GET" and entry.path == SPA_LINKS_PATH:
            self.link_reads.append(entry.query)
            if entry.query != {"conversation_id": [SPA_CHAT_ID]}:
                self.unexpected_requests.append(f"GET {entry.path} {entry.query}")
            self._json(route, {"run_id": SPA_RUN_ID, "workflow_runs": [
                started("run_review", "completed", name=SPA_WORKFLOW_NAME, workflow_id=WORKFLOW_ID,
                        run_id=SPA_WORKFLOW_RUN_ID),
            ]})
        else:
            super()._dispatch(route, entry)


@pytest.fixture
def spa_ui(page):
    fixture = ChatRunLinksFixture(page)
    yield fixture
    fixture.assert_clean()


def test_open_run_lands_on_the_run_expanded_in_its_workflow_history(spa_ui):
    ui = spa_ui
    ui.open(f"/chat?conversationId={SPA_CHAT_ID}")
    region = ui.page.get_by_role("region", name="Started workflows")
    expect(region).to_be_visible()
    link = region.get_by_role("link", name=f"Open run of {SPA_WORKFLOW_NAME}", exact=True)
    expect(link).to_have_attribute("href", f"/v2{SPA_HREF}")
    assert ui.link_reads == [{"conversation_id": [SPA_CHAT_ID]}]

    link.focus()
    ui.page.keyboard.press("Enter")
    expect(ui.page).to_have_url(f"{SPA_ORIGIN}/v2{SPA_HREF}")
    history = ui.page.get_by_role("list", name="Workflow run history", exact=True)
    linked = history.locator('li[aria-current="true"]')
    expect(linked).to_have_count(1)
    expect(linked.get_by_role("button", name="Hide run task results", exact=True)).to_be_visible()
    expect(linked).to_contain_text("Collect evidence")
    expect(history.get_by_role("button", name="Hide run task results", exact=True)).to_have_count(1)
    expect(ui.page.get_by_text("The linked run is not among the most recent runs shown here.")).to_have_count(0)
    expect(ui.page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    assert [entry.path for entry in ui.requests if entry.path.endswith("/items")] == [
        f"/api/user/workflows/{WORKFLOW_ID}/runs/{SPA_WORKFLOW_RUN_ID}/items",
    ]
    # Following the link reads and writes nothing else: it never starts, stops or changes a run.
    assert not [entry for entry in ui.writes if entry.path != "/api/user/settings"]
    assert len(ui.link_reads) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
