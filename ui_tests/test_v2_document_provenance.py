# test_v2_document_provenance.py
"""
Production-SPA coverage for where a V2 document came from.
Version: 0.261.199
Implemented in: 0.261.194
A workflow alert's Open workflow, followed while that workflows list is already open: 0.261.199

The real SPA runs against closed synthetic document, workflow and chat APIs, with no live data.
A list row says only which kind of origin a document has (`origin_kind`). The details pane asks
the single-document read for the `origin_summary` the server resolved for this reader
(`functions_document_provenance.resolve_origin_summary`) and shows it: a link to the workflow run
or the conversation when the server sends one, and plain text when it does not. The fixtures
never send a raw `origin`.

The workflows list acts on each navigation that names a run once, including one that only
changes the address while the list is open, as a workflow alert's Open workflow does (Track N2).
"""

import copy
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

from ui_tests.fixtures.group_documents import GroupDocumentsFixture, served  # noqa: E402
from ui_tests.fixtures.v2_notification_stubs import (  # noqa: E402
    is_notification_count,
    is_workflow_alerts,
    notification_count_payload,
    workflow_alert_document,
    workflow_alerts_payload,
)
from ui_tests.fixtures.workflow_editor import (  # noqa: E402
    GROUP_ID,
    WORKFLOW_ID,
    WorkflowEditorFixture,
    workflow_record,
)
from ui_tests.fixtures.workspace_authoring import ORIGIN, OWNER_ID, connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui
CHAT_ID = "existing-workspace-chat"
LINKED_RUN_ID = "run-linked"
LINKED_RUN_STARTED_AT = "2026-09-16T12:00:00Z"
WORKFLOW_HREF = f"/workspace/workflows?workflow_id={WORKFLOW_ID}&run_id={LINKED_RUN_ID}"
CHAT_HREF = f"/chat?conversationId={CHAT_ID}"
GROUP_HREF = "/groups/group-a/workflows?workflow_id=group-workflow&run_id=group-run-1"
WORKFLOW_SUMMARY = {
    "kind": "workflow", "label": "Created by Quarterly review workflow",
    "href": WORKFLOW_HREF, "run_started_at": LINKED_RUN_STARTED_AT,
}
CHAT_SUMMARY = {"kind": "chat", "label": "Created in chat \u00b7 Existing conversation", "href": CHAT_HREF}
# What a reader who cannot open the creator's workflow, run or chat is sent: no name, title, id or link.
WORKFLOW_FALLBACK = {"kind": "workflow", "label": "Created by a workflow"}
CHAT_FALLBACK = {"kind": "chat", "label": "Created in a chat"}
MARKUP_LABEL = '<img src=x onerror="window.__originInjected = true"> Quarterly review'
UNSAFE_HREFS = (
    # xss-check: ignore - hostile server values this test proves never become links or markup.
    ("workflow", "javascript:alert(1)//?workflow_id=workflow-v2-review"),
    ("workflow", "https://evil.example/workspace/workflows?workflow_id=workflow-v2-review&run_id=run-linked"),
    ("workflow", "//evil.example/workspace/workflows?workflow_id=workflow-v2-review"),
    ("workflow", "/groups/../workflows?workflow_id=workflow-v2-review"),
    ("workflow", "/groups/%2e%2e/workflows?workflow_id=workflow-v2-review"),
    ("workflow", "/groups/team\\..\\../workflows?workflow_id=workflow-v2-review"),
    ("workflow", "/workspace/workflows?workflow_id=workflow-v2-review&run_id=run-linked&next=/admin"),
    ("chat", "/chat?conversationId=existing-workspace-chat#message-1"),
    ("chat", "/chats?conversationId=existing-workspace-chat"),
    ("chat", "/admin/settings"),
)


def personal_document(identifier, title, **overrides):
    """A personal row as the list route projects it: `origin_kind` at most, never `origin`."""
    record = {
        "id": identifier, "document_id": identifier, "user_id": OWNER_ID, "owner_id": OWNER_ID,
        "title": title, "file_name": f"{identifier}.pdf", "file_type": "pdf", "tags": [],
        "version": 1, "number_of_pages": 2, "file_size": 2048, "num_chunks": 2,
        "percentage_complete": 100, "status": "Complete", "shared_approval_status": "owner",
        "is_current_version": True, "revision_family_id": f"family-{identifier}", "_ts": 1,
    }
    record.update(copy.deepcopy(overrides))
    return record


def normalized(text):
    """Collapse whitespace as Playwright's text matching does, including a locale's narrow spaces."""
    return " ".join(text.split())


class ProvenanceDocumentsFixture(WorkflowEditorFixture):
    """Personal documents, the personal workflow run history and the chat page, on closed APIs."""

    def __init__(self, page):
        super().__init__(page)
        self.workspace_documents = {
            "workflow-report": personal_document(
                "workflow-report", "Quarterly findings", origin_kind="workflow", tags=["workflow"],
            ),
            "chat-notes": personal_document(
                "chat-notes", "Budget notes", origin_kind="chat",
                # A chat upload keeps its older fields; the origin replaces the line they showed.
                created_from_chat_upload=True, conversation_id=CHAT_ID,
                conversation_title_at_upload="Existing conversation",
            ),
            "manual-upload": personal_document("manual-upload", "Manual upload"),
        }
        self.origin_summaries = {
            "workflow-report": copy.deepcopy(WORKFLOW_SUMMARY),
            "chat-notes": copy.deepcopy(CHAT_SUMMARY),
        }
        self.workflow_runs[WORKFLOW_ID] = [
            {"id": "run-latest", "workflow_id": WORKFLOW_ID, "status": "completed",
             "started_at": "2026-09-17T09:00:00Z"},
            {"id": LINKED_RUN_ID, "workflow_id": WORKFLOW_ID, "status": "completed",
             "started_at": LINKED_RUN_STARTED_AT},
        ]
        self.extra_gets["/api/documents/facets"] = {
            "total": 3, "untagged": 2, "processing": 0, "errors": 0, "recent": 0,
            "shared_with_me": 0, "by_tag": {"workflow": 1}, "by_classification": {},
        }
        self.extra_gets["/api/documents/tags"] = {"tags": [{"name": "workflow", "count": 1, "color": "#0078d4"}]}

    def add_document(self, identifier, title, origin_kind, summary):
        self.workspace_documents[identifier] = personal_document(identifier, title, origin_kind=origin_kind)
        self.origin_summaries[identifier] = copy.deepcopy(summary)

    def summary_reads(self):
        return [
            entry for entry in self.requests
            if entry.path.startswith("/api/documents/") and "origin_summary" in entry.query
        ]

    def _dispatch(self, route, entry):
        path, method = entry.path, entry.method
        if path == "/api/documents" and method == "GET":
            # A list read never resolves an origin, so it costs no reads per row.
            assert not [key for key in entry.query if key.startswith("origin")], entry
            rows = list(self.workspace_documents.values())
            self._json(route, {
                "documents": copy.deepcopy(rows), "page": 1, "page_size": 25,
                "total_count": len(rows), "file_downloads_enabled": False,
            })
        elif (
            method == "GET" and (match := re.fullmatch(r"/api/documents/([^/]+)", path))
            and match[1] in self.workspace_documents
        ):
            assert set(entry.query) <= {"origin_summary"}, entry
            payload = copy.deepcopy(self.workspace_documents[match[1]])
            summary = self.origin_summaries.get(match[1])
            if entry.query.get("origin_summary") == ["1"] and summary is not None:
                payload["origin_summary"] = copy.deepcopy(summary)
            self._json(route, payload)
        elif (
            method == "GET" and (match := re.fullmatch(r"/api/documents/([^/]+)/versions", path))
            and match[1] in self.workspace_documents
        ):
            assert not entry.query, entry
            record = self.workspace_documents[match[1]]
            self._json(route, {
                "document_id": match[1], "revision_family_id": record["revision_family_id"],
                "versions": [copy.deepcopy(record)],
            })
        else:
            super()._dispatch(route, entry)


# What each workspace's Open workflow names: the workflow, its title, the run the alert is about,
# another workflow on the same list, and the list's own address.
ALERT_CASES = {
    "personal": (WORKFLOW_ID, "Quarterly review workflow", LINKED_RUN_ID, "Agent review workflow",
                 "/workspace/workflows"),
    "group": ("group-workflow", "Group review workflow", "run-1", "Group digest workflow",
              f"/groups/{GROUP_ID}/workflows"),
}


class AlertLinkedWorkflowsFixture(ProvenanceDocumentsFixture):
    """
    The workflows lists with workflow alerts popping up over them. The count, the alerts read and
    the read receipt are answered as route_backend_notifications answers them, so the real bell,
    notice and card run unchanged.
    """

    def __init__(self, page):
        super().__init__(page)
        self.alerts = []
        self.read_calls = []
        self.last_count_read = 0.0
        self.group_workflows[GROUP_ID]["group-digest"] = workflow_record(
            "group-digest", name="Group digest workflow", group_id=GROUP_ID, reference_inputs=[],
        )

    def unread_alerts(self):
        return [alert for alert in self.alerts if not alert["is_read"] and not alert["is_dismissed"]]

    def count_reads(self):
        return sum(1 for entry in self.requests if is_notification_count(entry.method, entry.path))

    def _dispatch(self, route, entry):
        path, method = entry.path, entry.method
        if is_notification_count(method, path):
            self.last_count_read = time.monotonic()
            self._json(route, notification_count_payload(min(len(self.unread_alerts()), 10)))
        elif is_workflow_alerts(method, path):
            # The V2 runtime's own read: its store's cap, and only the day a pop-up may come from.
            # Every alert here pops up and is a minute old, so the unread ones are the answer.
            if entry.query != {"limit": ["10"], "since_hours": ["24"]}:
                self.unexpected_requests.append(f"GET {path} {entry.query}")
            self._json(route, workflow_alerts_payload(copy.deepcopy(self.unread_alerts())))
        elif method == "POST" and (match := re.fullmatch(r"/api/notifications/([^/]+)/read", path)):
            record = next((alert for alert in self.alerts if alert["id"] == match[1]), None)
            if record is None:
                self.unexpected_requests.append(f"POST {path} (unknown notice)")
                self._json(route, {"error": "Notification not found"}, 404)
                return
            record["is_read"] = True
            record["read_by"] = [OWNER_ID]
            self.read_calls.append(match[1])
            self._json(route, {"success": True, "message": "Notification marked as read"})
        else:
            super()._dispatch(route, entry)


class GroupProvenanceFixture(GroupDocumentsFixture):
    """The group explorer as an ordinary member, with origin summaries on detail reads."""

    def __init__(self, page):
        super().__init__(page)
        self.origin_summaries = {}
        kinds = {"same-document": "workflow", "team-01": "workflow", "team-02": "chat"}
        for row in self.documents["group-a"]:
            if row["id"] in kinds:
                row["origin_kind"] = kinds[row["id"]]

    def summary_reads(self):
        return [
            entry for entry in self.requests
            if entry.path.startswith("/api/group_documents/") and "origin_summary" in entry.query
        ]

    def _dispatch(self, route, entry):
        match = re.fullmatch(r"/api/group_documents/([^/]+)", entry.path)
        if entry.method == "GET" and match and "origin_summary" in entry.query:
            assert entry.query == {"group_id": ["group-a"], "origin_summary": ["1"]}, entry
            record = next(row for row in self.visible("group-a") if row["id"] == match[1])
            payload = served(record)
            summary = self.origin_summaries.get(match[1])
            if summary is not None:
                payload["origin_summary"] = copy.deepcopy(summary)
            self._json(route, payload)
        else:
            super()._dispatch(route, entry)


@pytest.fixture
def provenance_ui(page):
    fixture = ProvenanceDocumentsFixture(page)
    yield fixture
    fixture.assert_clean()


@pytest.fixture
def group_provenance_ui(page):
    fixture = GroupProvenanceFixture(page)
    yield fixture
    fixture.assert_clean()


@pytest.fixture
def alert_workflows_ui(page):
    fixture = AlertLinkedWorkflowsFixture(page)
    yield fixture
    fixture.assert_clean()


def wait_until(ui, predicate, message, timeout=10.0):
    """Poll from the test thread, so routes keep being answered meanwhile."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(message())
        ui.page.wait_for_timeout(100)


def raise_workflow_alert(ui, scope, identifier, title):
    """Write an alert about the case's run, and let the bell see it on its next read."""
    workflow_id, name, run_id, _, _ = ALERT_CASES[scope]
    created_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="milliseconds")
    ui.alerts.append(workflow_alert_document(
        identifier, created_at=created_at, user_id=OWNER_ID, workflow_id=workflow_id, workflow_name=name,
        scope=scope, group_id=GROUP_ID if scope == "group" else None, priority="high", run_id=run_id,
        title=title, link_targets=[],
    ))
    # The bell reads the count when the window regains focus, unless it read in the last two
    # seconds. Waiting those out first means one focus is normally enough.
    reads = ui.count_reads()
    ui.page.wait_for_timeout(max(0, int(2300 - (time.monotonic() - ui.last_count_read) * 1000)))
    deadline = time.monotonic() + 10
    while ui.count_reads() == reads:
        if time.monotonic() > deadline:
            raise AssertionError("The bell never read the count again.")
        ui.page.evaluate("() => window.dispatchEvent(new FocusEvent('focus'))")
        ui.page.wait_for_timeout(500)
    notice = ui.page.locator("[data-workflow-alert-notice]")
    expect(notice).to_contain_text(title)
    return notice


def open_workflow_from(ui, notice):
    notice.locator("[data-workflow-alert-open]").click()
    card = ui.page.locator("[data-workflow-alert-card]")
    expect(card).to_be_visible()
    card.locator("[data-workflow-alert-open-workflow]").click()
    expect(card).to_have_count(0)


def details_button(ui, title):
    return ui.page.get_by_role("button", name=f"Details for {title}", exact=True)


def origin_section(ui):
    return ui.page.locator("section").filter(has=ui.page.get_by_role("heading", name="Origin", exact=True))


def details_pane(ui):
    return ui.page.locator("aside").filter(has=ui.page.get_by_role("heading", name="Tags", exact=True))


def open_documents(ui):
    ui.open("/workspace/documents")
    expect(details_button(ui, "Quarterly findings")).to_be_visible()


def show_details(ui, title):
    details_button(ui, title).click()
    expect(details_pane(ui)).to_contain_text(title)
    return origin_section(ui)


def test_workflow_origin_links_to_its_run_in_the_workflow_history(provenance_ui):
    """The pane names the workflow and when the run started, and its link opens the personal
    workflow history with exactly that run expanded, not the workflow editor."""
    ui = provenance_ui
    ui.defer_next("GET", "/api/documents/workflow-report")
    open_documents(ui)
    origin = show_details(ui, "Quarterly findings")
    expect(origin.get_by_role("status")).to_have_text("Checking where this document came from...")
    ui.release_responses()
    run_time = ui.page.evaluate("value => new Date(value).toLocaleString()", LINKED_RUN_STARTED_AT)
    link = origin.get_by_role("link")
    expect(link).to_have_text(normalized(f"Created by Quarterly review workflow \u00b7 run {run_time}"))
    expect(link).to_have_attribute("href", f"/v2{WORKFLOW_HREF}")
    expect(origin.get_by_role("status")).to_have_count(0)
    reads = ui.summary_reads()
    assert [(entry.path, entry.query) for entry in reads] == [
        ("/api/documents/workflow-report", {"origin_summary": ["1"]}),
    ]

    link.click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2{WORKFLOW_HREF}")
    history = ui.page.get_by_role("list", name="Workflow run history", exact=True)
    linked = history.locator('li[aria-current="true"]')
    expect(linked).to_have_count(1)
    expect(linked.get_by_role("button", name="Hide run task results", exact=True)).to_be_visible()
    expect(linked).to_contain_text("Collect evidence")
    expect(history.get_by_role("button", name="Hide run task results", exact=True)).to_have_count(1)
    expect(history.get_by_role("button", name="Show run task results", exact=True)).to_have_count(1)
    expect(ui.page.get_by_text("The linked run is not among the most recent runs shown here.")).to_have_count(0)
    expect(ui.page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    assert [entry.path for entry in ui.requests if entry.path.endswith("/items")] == [
        f"/api/user/workflows/{WORKFLOW_ID}/runs/{LINKED_RUN_ID}/items",
    ]
    assert not [entry for entry in ui.writes if entry.path != "/api/user/settings"]


def test_a_run_link_outside_the_recent_runs_says_so_and_a_workflow_link_still_edits(provenance_ui):
    """A run older than the history shows is reported rather than silently replaced by another
    run. A link that names only the workflow keeps opening the editor, as it always has."""
    ui = provenance_ui
    ui.open(f"/workspace/workflows?workflow_id={WORKFLOW_ID}&run_id=run-archived")
    expect(ui.page.get_by_role("status").filter(
        has_text="The linked run is not among the most recent runs shown here.",
    )).to_be_visible()
    history = ui.page.get_by_role("list", name="Workflow run history", exact=True)
    expect(history.get_by_role("button", name="Show run task results", exact=True)).to_have_count(2)
    expect(history.locator("li[aria-current]")).to_have_count(0)
    expect(history.get_by_role("button", name="Hide run task results", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)

    ui.open(f"/workspace/workflows?workflow_id={WORKFLOW_ID}")
    expect(ui.page.get_by_role("dialog", name="Edit workflow", exact=True)).to_be_visible()
    assert not [entry for entry in ui.requests if entry.path.endswith("/items")]


@pytest.mark.parametrize("scope", ("personal", "group"))
def test_open_workflow_from_an_alert_while_the_list_is_open(alert_workflows_ui, scope):
    """A workflow alert's Open workflow, followed while that workspace's workflows list is open,
    changes only the address; the list stays mounted. It still opens the run's history with the
    run expanded, and does so again each time it is followed, even to the same address. Nothing
    else that changes the list afterwards, such as running another workflow, opens it again."""
    ui = alert_workflows_ui
    workflow_id, _, run_id, other, list_path = ALERT_CASES[scope]
    if scope == "group":
        ui.open("/groups")
        ui.select_group(GROUP_ID)
        items_path = f"/api/group/workflows/{workflow_id}/runs/{run_id}/items"
        list_api = "/api/group/workflows"
    else:
        ui.open("/workspace/workflows")
        items_path = f"/api/user/workflows/{workflow_id}/runs/{run_id}/items"
        list_api = "/api/user/workflows"
    run_other = ui.page.get_by_role("button", name=f"Run {other}", exact=True)
    expect(run_other).to_be_visible()
    history = ui.page.get_by_role("list", name="Workflow run history", exact=True)
    linked = history.locator('li[aria-current="true"]')
    expect(history).to_have_count(0)
    target = f"{ORIGIN}/v2{list_path}?workflow_id={workflow_id}&run_id={run_id}"

    def item_reads():
        return [entry.path for entry in ui.requests if entry.path.endswith("/items")]

    open_workflow_from(ui, raise_workflow_alert(ui, scope, "alert-1", "Review found blocking items"))
    expect(ui.page).to_have_url(target)
    expect(linked).to_have_count(1)
    expect(linked.get_by_role("button", name="Hide run task results", exact=True)).to_be_visible()
    expect(linked).to_contain_text("Collect evidence")
    expect(ui.page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    wait_until(ui, lambda: ui.read_calls == ["alert-1"], lambda: f"Opening marked {ui.read_calls} as read.")
    assert item_reads() == [items_path]

    # The reader closes the run; the same Open workflow, on a second alert, opens it again.
    linked.get_by_role("button", name="Hide run task results", exact=True).click()
    expect(linked.get_by_role("button", name="Show run task results", exact=True)).to_be_visible()
    open_workflow_from(ui, raise_workflow_alert(ui, scope, "alert-2", "Review still has blocking items"))
    expect(ui.page).to_have_url(target)
    expect(linked.get_by_role("button", name="Hide run task results", exact=True)).to_be_visible()
    wait_until(ui, lambda: ui.read_calls == ["alert-1", "alert-2"], lambda: f"Opening marked {ui.read_calls} as read.")
    assert item_reads() == [items_path, items_path]

    # Running another workflow refreshes the list and expands that workflow's history instead.
    # The address still names the run, but it was already acted on, so it stays closed.
    list_reads = sum(1 for entry in ui.requests if (entry.method, entry.path) == ("GET", list_api))
    run_other.click()
    expect(ui.page.get_by_role("button", name=f"Cancel {other}", exact=True)).to_be_visible()
    wait_until(
        ui,
        lambda: sum(1 for entry in ui.requests if (entry.method, entry.path) == ("GET", list_api)) > list_reads,
        lambda: "Running the workflow did not refresh the list.",
    )
    ui.page.wait_for_timeout(500)
    expect(ui.page.get_by_role("button", name="Hide run history", exact=True)).to_have_count(1)
    expect(history.locator("li[aria-current]")).to_have_count(0)
    expect(ui.page).to_have_url(target)
    assert item_reads().count(items_path) == 2
    assert [entry.path for entry in ui.non_navigation_writes if entry.path != "/api/user/settings"] == [
        "/api/notifications/alert-1/read", "/api/notifications/alert-2/read",
        f"{list_api}/{'group-digest' if scope == 'group' else 'agent-workflow'}/run",
    ]


def test_chat_origin_opens_its_conversation(provenance_ui):
    """A chat origin names the conversation and opens it on the V2 chat page. It replaces the
    older "Uploaded through chat" line, which described the same upload."""
    ui = provenance_ui
    open_documents(ui)
    origin = show_details(ui, "Budget notes")
    link = origin.get_by_role("link")
    expect(link).to_have_text("Created in chat \u00b7 Existing conversation")
    expect(link).to_have_attribute("href", f"/v2{CHAT_HREF}")
    expect(details_pane(ui).get_by_text("Uploaded through chat")).to_have_count(0)

    link.click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2{CHAT_HREF}")
    expect(ui.page.get_by_text("An earlier conversation.", exact=True)).to_be_visible()
    assert any(
        entry.path == "/api/get_messages" and entry.query.get("conversation_id") == [CHAT_ID]
        for entry in ui.requests
    )
    assert not [entry for entry in ui.writes if entry.path != "/api/user/settings"]


def test_an_origin_the_reader_cannot_open_is_plain_text(provenance_ui):
    """A reader who cannot open the creator's workflow, run or chat is sent only the kind, so
    the pane names nothing and links nowhere. A read with no summary (a deleted origin) or with
    one of the other kind falls back the same way. A document with no origin has no section, and
    an older chat upload keeps the line it always had."""
    ui = provenance_ui
    ui.origin_summaries["workflow-report"] = copy.deepcopy(WORKFLOW_FALLBACK)
    ui.origin_summaries["chat-notes"] = copy.deepcopy(CHAT_FALLBACK)
    ui.add_document("deleted-origin", "Orphaned report", "workflow", None)
    ui.add_document("mismatched-origin", "Mismatched notes", "chat", {**WORKFLOW_SUMMARY})
    # A chat upload from before origins were recorded keeps the line it always had.
    ui.workspace_documents["legacy-chat-upload"] = personal_document(
        "legacy-chat-upload", "Legacy notes", created_from_chat_upload=True, conversation_id=CHAT_ID,
        conversation_title_at_upload="Existing conversation",
    )
    open_documents(ui)
    # Consecutive documents alternate their text, so each check waits for the pane to switch.
    cases = (
        ("Quarterly findings", "Created by a workflow"),
        ("Budget notes", "Created in a chat"),
        ("Orphaned report", "Created by a workflow"),
        ("Mismatched notes", "Created in a chat"),
    )
    for title, text in cases:
        origin = show_details(ui, title)
        expect(origin.locator("p")).to_have_text(text)
        expect(origin.get_by_role("link")).to_have_count(0)
        expect(origin.get_by_role("status")).to_have_count(0)
        expect(origin.get_by_role("alert")).to_have_count(0)
        # "Budget notes" is a chat upload; its origin, even unresolved, replaces the older line.
        expect(details_pane(ui).get_by_text("Uploaded through chat")).to_have_count(0)

    show_details(ui, "Manual upload")
    expect(ui.page.get_by_role("heading", name="Origin", exact=True)).to_have_count(0)
    show_details(ui, "Legacy notes")
    expect(details_pane(ui).get_by_text('Uploaded through chat in "Existing conversation".')).to_be_visible()
    expect(ui.page.get_by_role("heading", name="Origin", exact=True)).to_have_count(0)
    read_documents = [entry.path.rsplit("/", 1)[-1] for entry in ui.summary_reads()]
    assert read_documents == [
        "workflow-report", "chat-notes", "deleted-origin", "mismatched-origin",
    ]


def test_unsafe_origin_links_and_markup_render_as_text(provenance_ui):
    """Robustness: deliberately malformed summaries. A link that leaves the app, climbs out of
    its route, or opens anything but a workflow run or a conversation is never rendered as a
    link, and a label is always text, never markup."""
    ui = provenance_ui
    for index, (kind, href) in enumerate(UNSAFE_HREFS):
        summary = {"kind": kind, "label": f"{MARKUP_LABEL} {index}", "href": href}
        if kind == "workflow":
            summary["run_started_at"] = "not a time"
        ui.add_document(f"unsafe-{index}", f"Unsafe origin {index}", kind, summary)
    open_documents(ui)
    for index, (_, href) in enumerate(UNSAFE_HREFS):
        origin = show_details(ui, f"Unsafe origin {index}")
        expect(origin.locator("p"), f"The {href!r} summary must be text.").to_have_text(f"{MARKUP_LABEL} {index}")
        expect(origin.get_by_role("link"), f"The {href!r} summary must not become a link.").to_have_count(0)
        expect(origin.locator("img")).to_have_count(0)
    not_injected = ui.page.evaluate("() => window.__originInjected === undefined")
    reads = ui.summary_reads()
    assert not_injected
    assert len(reads) == len(UNSAFE_HREFS)


def test_a_failed_origin_read_can_be_retried(provenance_ui):
    """A failed summary read keeps the plain kind visible, says it failed, and retries."""
    ui = provenance_ui
    open_documents(ui)
    ui.reject_next("GET", "/api/documents/workflow-report", error="Origin lookup failed.")
    origin = show_details(ui, "Quarterly findings")
    alert = origin.get_by_role("alert")
    expect(alert).to_contain_text("Could not load where this document came from.")
    expect(origin.get_by_text("Created by a workflow", exact=True)).to_be_visible()
    expect(origin.get_by_role("link")).to_have_count(0)

    alert.get_by_role("button", name="Retry origin", exact=True).click()
    expect(origin.get_by_role("link")).to_have_attribute("href", f"/v2{WORKFLOW_HREF}")
    expect(origin.get_by_role("alert")).to_have_count(0)
    reads = ui.summary_reads()
    assert len(reads) == 2


def test_group_member_sees_what_the_server_resolved_for_them(group_provenance_ui):
    """In a group, each summary is read through the group's detail route. A member sees a link
    to a group workflow run they can open, which stays in that group, and plain text for another
    member's private workflow or chat."""
    ui = group_provenance_ui
    ui.origin_summaries["same-document"] = copy.deepcopy(WORKFLOW_FALLBACK)
    ui.origin_summaries["team-01"] = {
        "kind": "workflow", "label": "Created by Group review workflow",
        "href": GROUP_HREF, "run_started_at": LINKED_RUN_STARTED_AT,
    }
    ui.origin_summaries["team-02"] = copy.deepcopy(CHAT_FALLBACK)
    ui.open("/groups/group-a/documents")
    expect(details_button(ui, "Research brief")).to_be_visible()

    origin = show_details(ui, "Research brief")
    expect(origin.locator("p")).to_have_text("Created by a workflow")
    expect(origin.get_by_role("link")).to_have_count(0)

    origin = show_details(ui, "Team research 01")
    run_time = ui.page.evaluate("value => new Date(value).toLocaleString()", LINKED_RUN_STARTED_AT)
    link = origin.get_by_role("link")
    expect(link).to_have_text(normalized(f"Created by Group review workflow \u00b7 run {run_time}"))
    expect(link).to_have_attribute("href", f"/v2{GROUP_HREF}")

    origin = show_details(ui, "Team research 02")
    expect(origin.locator("p")).to_have_text("Created in a chat")
    expect(origin.get_by_role("link")).to_have_count(0)

    show_details(ui, "Published report")
    expect(ui.page.get_by_role("heading", name="Origin", exact=True)).to_have_count(0)
    read_paths = [entry.path for entry in ui.summary_reads()]
    assert read_paths == [
        "/api/group_documents/same-document", "/api/group_documents/team-01", "/api/group_documents/team-02",
    ]
