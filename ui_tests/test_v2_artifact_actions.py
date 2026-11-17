# test_v2_artifact_actions.py
"""
Browser regressions for "Add to workspace" and "Create PowerPoint" on V2 generated-artifact cards.
Version: 0.261.445
Implemented in: 0.261.445

Classic's generated-artifact card offers both actions; the V2 card offered only Download and View.
The V2 actions call the same two routes: ``POST /api/chat_artifacts/promote`` (an explicit
destination taken from the conversation, an approval flow for group and public workspaces) and
``POST /api/message/export-powerpoint`` (a deck built from a stored Markdown file beside the reply
that carries it).

Exercises the real card, actions, promotion dialog, stores, toaster and export machinery, bundled
by fixtures/artifact_actions. Only HTTP answers are replaced; no live application data is read or
modified.
"""

import json
import mimetypes
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

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

FIXTURE = ROOT / "ui_tests" / "fixtures" / "artifact_actions"
BUNDLE = FIXTURE / "harness.bundle.js"
STATIC = ROOT / "application" / "single_app" / "static"
ORIGIN = "https://simplechat.test"
CONVERSATION = "conv-1"
REPLY = "reply-1"
GROUP = "group-1"
PUBLIC_WORKSPACE = "public-1"
MARKDOWN_NAME = "analysis-summary.md"
CSV_NAME = "rows.csv"

REFUSED = "Artifact publication is not permitted."
UNCONFIRMED = (
    "Publication could not be fully confirmed. Check the existing destination; no second copy was created."
)
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def artifact(**extra):
    """A generated file as the card receives it, after readGeneratedArtifacts normalised it."""
    record = {
        "capability": "analyze",
        "artifact_message_id": "art-md",
        "conversation_id": CONVERSATION,
        "document_id": "",
        "export_run_id": "",
        "run_id": "",
        "background_export": False,
        "suppress_assistant_table_export": False,
        "storage_scope": "chat",
        "file_name": MARKDOWN_NAME,
        "output_format": "md",
        "preview_text": "# Findings\n\nEvery state has exactly one capital city.",
    }
    record.update(extra)
    return record


def spreadsheet(**extra):
    return artifact(
        capability="tabular", artifact_message_id="art-csv", file_name=CSV_NAME, output_format="csv",
        row_count=3, preview_text="", preview_rows=[{"State": "Alabama", "Capital": "Montgomery"}], **extra,
    )


def card(record, *, message_id=REPLY, embedded=False):
    return {"artifact": record, "conversationId": CONVERSATION, "messageId": message_id, "embedded": embedded}


def conversation(chat_type="personal_single_user", **extra):
    """The conversation's own metadata, which decides where a file can be added."""
    record = {"conversation_id": CONVERSATION, "title": "Quarterly plan", "chat_type": chat_type, "context": []}
    record.update(extra)
    return record


GROUP_CONVERSATION = conversation(
    "group-single-user",
    context=[{"type": "primary", "scope": "group", "id": GROUP, "name": "Marketing"}],
)
PUBLIC_CONVERSATION = conversation(
    "public",
    context=[{"type": "primary", "scope": "public", "id": PUBLIC_WORKSPACE, "name": "Public library"}],
)


def promotion_answer(status="queued", approval_required=False, **extra):
    """What POST /api/chat_artifacts/promote answers (route_enhanced_citations)."""
    body = {
        "message": "Generated artifact added to your personal workspace.",
        "workspace_scope": "personal",
        "approval_required": approval_required,
        "document": {"id": "doc-1", "file_name": f"{MARKDOWN_NAME} (artifact 000001)", "status": "Queued for processing"},
        "publication": {"id": "receipt-1", "state": status, "document_id": "doc-1", "unresolved_stages": []},
    }
    body.update(extra)
    return body


class ArtifactApi:
    """The two routes the actions call, answered the way route_* answers, with the requests seen."""

    def __init__(self, page):
        self.page = page
        self.promotions = []
        self.promote_answers = []
        self.exports = []
        self.export_answer = None
        # When a list, requests are parked in it and left unanswered until the test answers them.
        self.held_promotions = None
        self.held_exports = None
        self.requests = []
        self.errors = []
        self.unexpected = []
        self.expected_http_failures = set()

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
        if method == "GET" and path == "/harness.html":
            route.fulfill(path=str(FIXTURE / "harness.html"), content_type="text/html")
        elif method == "GET" and path == "/harness.bundle.js":
            route.fulfill(path=str(BUNDLE), content_type="application/javascript")
        elif method == "GET" and path == "/favicon.ico":
            route.fulfill(status=204, body="")
        elif method == "GET" and path.startswith("/static/"):
            asset = (STATIC / path.removeprefix("/static/")).resolve()
            if asset.is_relative_to(STATIC.resolve()) and asset.is_file():
                route.fulfill(path=str(asset), content_type=mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
            else:
                self.unexpected.append(f"{method} {path}")
                route.fulfill(status=404, body="")
        elif method == "POST" and path == "/api/chat_artifacts/promote":
            self.promotions.append(request.post_data_json)
            self.answer_promotion(route)
        elif method == "POST" and path == "/api/message/export-powerpoint":
            self.exports.append(request.post_data_json)
            self.answer_export(route)
        else:
            self.unexpected.append(f"{method} {path}")
            route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def answer_promotion(self, route):
        if self.held_promotions is not None:
            self.held_promotions.append(route)
            return
        status, body = self.promote_answers.pop(0) if self.promote_answers else (200, promotion_answer())
        if status >= 400:
            self.expected_http_failures.add(("/api/chat_artifacts/promote", status))
        route.fulfill(status=status, json=body)

    def answer_export(self, route):
        if self.held_exports is not None:
            self.held_exports.append(route)
            return
        if self.export_answer:
            status, body = self.export_answer
            self.expected_http_failures.add(("/api/message/export-powerpoint", status))
            route.fulfill(status=status, json=body)
            return
        route.fulfill(status=200, body=b"PK\x03\x04pptx", headers={
            "Content-Type": PPTX,
            "Content-Disposition": 'attachment; filename="message_export_20260102_030405.pptx"',
        })


SEED = r"""
(seed) => {
    const H = window.ArtifactHarness;
    H.stores.bootstrap.useBootstrapStore.setState({
        data: {
            version: '0.261.445',
            user: {id: 'user-1', display_name: 'Riley Chen', roles: []},
            features: seed.features,
            branding: {app_title: 'Contoso Chat'},
            settings: {},
            scope: {
                groups: seed.groups,
                public_workspaces: seed.publicWorkspaces,
                active_group_id: null,
                active_group_name: null,
                active_public_workspace_id: null,
            },
            catalogs: {models: [], agents: [], prompts: []},
        },
        loading: false,
        error: null,
    });
    H.stores.chat.useChatStore.setState({
        activeConversationId: seed.conversation,
        activeConversationKind: seed.kind,
        conversations: [],
        messages: [],
        metadata: seed.metadata,
    });
    H.stores.actions.useGeneratedArtifactActionStore.setState({promotions: {}});
    H.mount(seed.cards);
}
"""

ALL_WORKSPACES = {"enable_user_workspace": True, "enable_group_workspaces": True, "enable_public_workspaces": True}


class Harness(ArtifactApi):
    """The card in a browser page, driven the way a reader drives it."""

    def __init__(self, page, stylesheets):
        super().__init__(page)
        self.stylesheets = stylesheets
        self.seed = None

    def open(self, cards, *, metadata=None, kind="personal", features=None):
        self.page.route("**/*", self.handle)
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("console", self.record_console)
        self.page.goto(f"{ORIGIN}/harness.html")
        for stylesheet in self.stylesheets:
            self.page.add_style_tag(path=str(stylesheet))
        self.seed = {
            "conversation": CONVERSATION,
            "kind": kind,
            "metadata": conversation() if metadata is None else metadata,
            "features": ALL_WORKSPACES if features is None else features,
            "groups": [{"id": GROUP, "name": "Marketing"}],
            "publicWorkspaces": [{"id": PUBLIC_WORKSPACE, "name": "Public library"}],
            "cards": cards,
        }
        self.page.evaluate(SEED, self.seed)

    def reseed(self, **changes):
        """Replace the seeded stores and draw the cards again, as a remount does."""
        self.seed.update(changes)
        self.page.evaluate(SEED, self.seed)

    def record_console(self, message):
        if message.type != "error":
            return
        path = urlsplit(message.location.get("url", "")).path
        status = re.search(r"^Failed to load resource: the server responded with a status of (\d+)", message.text)
        if status and (path, int(status.group(1))) in self.expected_http_failures:
            return
        self.errors.append(message.text)

    def card_of(self, file_name):
        return self.page.locator("section").filter(has_text=file_name)

    def add_button(self, file_name=MARKDOWN_NAME):
        return self.card_of(file_name).get_by_role("button", name=re.compile(r"^(Add to workspace|Check again):"))

    def powerpoint_button(self, file_name=MARKDOWN_NAME):
        return self.card_of(file_name).get_by_role("button", name=re.compile("^Create PowerPoint"))

    @property
    def dialog(self):
        return self.page.get_by_role("dialog")

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
def harness(page, harness_assets):
    api = Harness(page, harness_assets)
    yield api
    # The requests nobody answered come first: they are the usual cause of a console 404.
    assert not api.unexpected, api.unexpected
    assert not api.errors, api.errors


# Which files get which button -----------------------------------------------------------------


def test_a_markdown_file_offers_both_actions_and_a_spreadsheet_only_the_workspace(harness):
    harness.open([card(artifact()), card(spreadsheet())])

    markdown = harness.card_of(MARKDOWN_NAME)
    expect(markdown.get_by_role("button", name=re.compile("^Download MD"))).to_be_visible()
    expect(harness.powerpoint_button()).to_have_accessible_name(f"Create PowerPoint from {MARKDOWN_NAME}")
    expect(harness.add_button()).to_have_accessible_name(f"Add to workspace: {MARKDOWN_NAME}")

    sheet = harness.card_of(CSV_NAME)
    expect(sheet.get_by_role("button", name=re.compile("^Download CSV"))).to_be_visible()
    expect(harness.add_button(CSV_NAME)).to_be_visible()
    expect(harness.powerpoint_button(CSV_NAME)).to_have_count(0)


def test_a_withheld_file_and_an_orchestration_file_card_offer_neither(harness):
    harness.open([
        card(artifact(approval={"state": "pending_approval", "viewer_can_approve": False})),
        card(spreadsheet(), embedded=True),
    ])

    expect(harness.page.get_by_text("waiting for approval", exact=False).first).to_be_visible()
    expect(harness.add_button()).to_have_count(0)
    expect(harness.powerpoint_button()).to_have_count(0)
    # The embedded card still downloads; the two classic buttons are not part of it.
    expect(harness.page.get_by_role("button", name=re.compile("^Download CSV"))).to_be_visible()
    expect(harness.page.get_by_role("button", name=re.compile("Add to workspace"))).to_have_count(0)


def test_a_released_file_is_actionable_again(harness):
    harness.open([card(artifact(approval={"state": "approved", "resolved_by_name": "Riley Chen"}))])

    expect(harness.add_button()).to_be_visible()
    expect(harness.powerpoint_button()).to_be_visible()


def test_a_conversation_that_has_not_loaded_offers_no_destination(harness):
    harness.open([card(artifact())])
    expect(harness.add_button()).to_be_visible()

    # The destination is read from the conversation's own metadata. Until that has loaded, a
    # default of "personal" could put a group's file in the reader's private workspace.
    harness.reseed(metadata=None)
    expect(harness.add_button()).to_have_count(0)
    expect(harness.powerpoint_button()).to_be_visible()

    harness.reseed(metadata=conversation())
    expect(harness.add_button()).to_be_visible()


def test_a_workspace_the_deployment_has_switched_off_is_not_offered(harness):
    harness.open([card(artifact())], features={**ALL_WORKSPACES, "enable_user_workspace": False})

    expect(harness.powerpoint_button()).to_be_visible()
    expect(harness.add_button()).to_have_count(0)


# Add to workspace -----------------------------------------------------------------------------


def test_adding_a_file_to_the_personal_workspace_confirms_first_and_names_the_destination(harness):
    harness.open([card(artifact())])
    harness.add_button().click()

    dialog = harness.dialog
    expect(dialog).to_have_accessible_name("Add to Personal workspace?")
    expect(dialog).to_contain_text(f"{MARKDOWN_NAME} will be saved to Personal workspace.")
    expect(dialog).to_contain_text("Private to you.")
    assert not harness.promotions, "Opening the dialog sends nothing"
    dialog.get_by_role("button", name="Cancel").click()
    expect(harness.dialog).to_have_count(0)
    assert not harness.promotions, "Cancelling sends nothing"

    harness.add_button().click()
    harness.dialog.get_by_role("button", name="Add to Personal").click()
    expect(harness.toast("Added to your personal workspace.")).to_be_visible()
    # An explicit destination and nothing else: no request_id, so a retry is not a second copy.
    assert harness.promotions == [{"conversation_id": CONVERSATION, "message_id": "art-md", "workspace_scope": "personal"}]
    expect(harness.dialog).to_have_count(0)
    status = harness.card_of(MARKDOWN_NAME).get_by_role("status").filter(has_text="Added to workspace")
    expect(status).to_be_visible()
    expect(harness.add_button()).to_have_count(0)


def test_what_the_card_did_survives_the_thread_drawing_it_again(harness):
    harness.open([card(artifact())])
    harness.add_button().click()
    harness.dialog.get_by_role("button", name="Add to Personal").click()
    expect(harness.card_of(MARKDOWN_NAME).get_by_role("status").filter(has_text="Added to workspace")).to_be_visible()

    # Only the card is drawn again, as it is when the thread reloads; the store that remembers its
    # state is left alone.
    harness.page.evaluate("(cards) => { window.ArtifactHarness.unmount(); window.ArtifactHarness.mount(cards); }",
                          harness.seed["cards"])
    expect(harness.card_of(MARKDOWN_NAME).get_by_role("status").filter(has_text="Added to workspace")).to_be_visible()
    expect(harness.add_button()).to_have_count(0)
    assert len(harness.promotions) == 1


def test_a_group_conversation_submits_its_file_to_the_group_for_approval(harness):
    harness.promote_answers = [(202, promotion_answer(
        "pending_approval", True, workspace_scope="group", group_id=GROUP,
        message="Generated artifact submitted to the destination workspace for approval.",
    ))]
    harness.open([card(artifact())], metadata=GROUP_CONVERSATION)
    harness.add_button().click()

    dialog = harness.dialog
    expect(dialog).to_have_accessible_name("Add to Marketing?")
    expect(dialog).to_contain_text("Group workspace approval request.")
    expect(dialog).to_contain_text("once one of its approvers accepts the request")
    dialog.get_by_role("button", name="Submit to Group").click()

    expect(harness.toast("Submitted to Marketing for approval.")).to_be_visible()
    assert harness.promotions == [{
        "conversation_id": CONVERSATION, "message_id": "art-md", "workspace_scope": "group", "group_id": GROUP,
    }]
    expect(harness.card_of(MARKDOWN_NAME).get_by_role("status").filter(has_text="Pending approval")).to_be_visible()


def test_a_public_conversation_submits_its_file_to_the_public_workspace(harness):
    harness.promote_answers = [(202, promotion_answer("pending_approval", True, workspace_scope="public"))]
    harness.open([card(artifact())], metadata=PUBLIC_CONVERSATION)
    harness.add_button().click()

    expect(harness.dialog).to_have_accessible_name("Add to Public library?")
    harness.dialog.get_by_role("button", name="Submit to Public").click()
    expect(harness.toast("Submitted to Public library for approval.")).to_be_visible()
    assert harness.promotions == [{
        "conversation_id": CONVERSATION, "message_id": "art-md", "workspace_scope": "public",
        "public_workspace_id": PUBLIC_WORKSPACE,
    }]


def test_a_conversation_that_does_not_name_its_workspace_lets_the_reader_choose(harness):
    harness.promote_answers = [(202, promotion_answer("pending_approval", True, workspace_scope="group"))]
    harness.open([card(artifact())], metadata=conversation("group-single-user"))
    harness.add_button().click()

    dialog = harness.dialog
    expect(dialog).to_have_accessible_name("Choose workspace")
    options = dialog.get_by_role("radio")
    expect(options).to_have_count(3)
    expect(options.first).to_be_checked()
    expect(dialog.get_by_role("button", name="Add to selected workspace")).to_be_enabled()

    dialog.get_by_role("radio", name=re.compile("Marketing")).check()
    dialog.get_by_role("button", name="Add to selected workspace").click()
    expect(harness.toast("Submitted to Marketing for approval.")).to_be_visible()
    assert harness.promotions[0]["workspace_scope"] == "group" and harness.promotions[0]["group_id"] == GROUP


def test_a_refusal_stays_in_the_dialog_and_can_be_tried_again(harness):
    harness.promote_answers = [(403, {"error": REFUSED})]
    harness.open([card(artifact())])
    harness.add_button().click()
    harness.dialog.get_by_role("button", name="Add to Personal").click()

    expect(harness.alert(REFUSED)).to_be_visible()
    expect(harness.dialog).to_be_visible()
    expect(harness.dialog.get_by_role("button", name="Add to Personal")).to_be_enabled()
    expect(harness.card_of(MARKDOWN_NAME).get_by_role("status").filter(has_text="Added to workspace")).to_have_count(0)

    harness.dialog.get_by_role("button", name="Add to Personal").click()
    expect(harness.toast("Added to your personal workspace.")).to_be_visible()
    assert len(harness.promotions) == 2 and harness.promotions[0] == harness.promotions[1], (
        "The retry is the same request, which the server answers with the publication that exists"
    )


def test_an_unconfirmed_publication_stays_on_the_card_as_a_warning_not_a_success(harness):
    harness.promote_answers = [
        (409, promotion_answer("uncertain", False, message=UNCONFIRMED, publication={
            "id": "receipt-1", "state": "uncertain", "document_id": "doc-1", "unresolved_stages": ["prepare"],
        })),
        (200, promotion_answer()),
    ]
    harness.open([card(artifact())])
    harness.add_button().click()
    harness.dialog.get_by_role("button", name="Add to Personal").click()

    expect(harness.dialog).to_have_count(0)
    section = harness.card_of(MARKDOWN_NAME)
    expect(section.get_by_role("status").filter(has_text=UNCONFIRMED)).to_be_visible()
    expect(section.get_by_role("status").filter(has_text="Added to workspace")).to_have_count(0)
    check = harness.add_button()
    expect(check).to_have_accessible_name(f"Check again: {MARKDOWN_NAME}")

    check.click()
    harness.dialog.get_by_role("button", name="Add to Personal").click()
    expect(harness.card_of(MARKDOWN_NAME).get_by_role("status").filter(has_text="Added to workspace")).to_be_visible()
    expect(section.get_by_role("status").filter(has_text=UNCONFIRMED)).to_have_count(0)


def test_the_dialog_cannot_be_dismissed_or_pressed_twice_while_the_request_runs(harness):
    held = harness.held_promotions = []
    harness.open([card(artifact())])
    harness.add_button().click()
    harness.dialog.get_by_role("button", name="Add to Personal").click()

    harness.page.wait_for_timeout(300)
    assert len(held) == 1
    expect(harness.dialog.get_by_role("button", name="Add to Personal")).to_be_disabled()
    expect(harness.dialog.get_by_role("button", name="Cancel")).to_be_disabled()
    harness.page.keyboard.press("Escape")
    expect(harness.dialog).to_be_visible()

    held[0].fulfill(status=200, json=promotion_answer())
    expect(harness.toast("Added to your personal workspace.")).to_be_visible()
    expect(harness.dialog).to_have_count(0)


def test_a_shared_conversation_can_still_add_a_file_to_a_workspace(harness):
    harness.open([card(artifact())], metadata=conversation("personal_multi_user"), kind="collaborative")

    harness.add_button().click()
    harness.dialog.get_by_role("button", name="Add to Personal").click()
    expect(harness.toast("Added to your personal workspace.")).to_be_visible()
    assert harness.promotions[0]["conversation_id"] == CONVERSATION, "The file's own conversation is what the route reads"


# Create PowerPoint ----------------------------------------------------------------------------


def test_creating_a_powerpoint_downloads_a_deck_built_from_the_stored_file(harness):
    harness.open([card(artifact())])

    with harness.page.expect_download() as download:
        harness.powerpoint_button().click()
    assert re.fullmatch(r"message_export_\d{8}_\d{6}\.pptx", download.value.suggested_filename), download.value.suggested_filename
    expect(harness.toast("Markdown artifact exported as PowerPoint.")).to_be_visible()

    # The file's id and the reply carrying it, and nothing of the reply's own text.
    assert harness.exports == [{"message_id": REPLY, "conversation_id": CONVERSATION, "artifact_message_id": "art-md"}]
    expect(harness.powerpoint_button()).to_be_enabled()


def test_a_powerpoint_in_progress_says_so_and_cannot_be_started_twice(harness):
    held = harness.held_exports = []
    harness.open([card(artifact())])
    harness.powerpoint_button().click()

    expect(harness.toast("Building your PowerPoint")).to_be_visible()
    button = harness.powerpoint_button()
    expect(button).to_be_disabled()
    expect(button).to_have_attribute("aria-busy", "true")
    expect(button).to_contain_text("Creating")
    harness.page.wait_for_timeout(200)
    assert len(held) == 1

    with harness.page.expect_download():
        held[0].fulfill(status=200, body=b"PK\x03\x04pptx", headers={"Content-Type": PPTX})
    expect(harness.toast("Markdown artifact exported as PowerPoint.")).to_be_visible()
    expect(harness.powerpoint_button()).to_be_enabled()


def test_a_failed_powerpoint_says_why_and_can_be_tried_again(harness):
    harness.export_answer = (404, {"error": "Generated Markdown artifact not found"})
    harness.open([card(artifact())])
    harness.powerpoint_button().click()

    expect(harness.alert("PowerPoint export failed: Generated Markdown artifact not found")).to_be_visible()
    expect(harness.powerpoint_button()).to_be_enabled()
    expect(harness.toast("exported as PowerPoint")).to_have_count(0)

    harness.export_answer = None
    with harness.page.expect_download():
        harness.powerpoint_button().click()
    expect(harness.toast("Markdown artifact exported as PowerPoint.")).to_be_visible()
    assert len(harness.exports) == 2


def test_no_powerpoint_is_offered_in_a_shared_conversation_or_without_the_reply(harness):
    harness.open([card(artifact())], metadata=conversation("personal_multi_user"), kind="collaborative")
    expect(harness.add_button()).to_be_visible()
    expect(harness.powerpoint_button()).to_have_count(0)

    harness.reseed(metadata=conversation(), kind="personal", cards=[card(artifact(), message_id="")])
    expect(harness.powerpoint_button()).to_have_count(0)
    expect(harness.add_button()).to_be_visible()


# Keyboard and a phone -------------------------------------------------------------------------


def test_adding_a_file_is_operable_from_the_keyboard_and_returns_focus(harness):
    harness.open([card(artifact())])

    harness.add_button().focus()
    harness.page.keyboard.press("Enter")
    dialog = harness.dialog
    expect(dialog).to_have_accessible_name("Add to Personal workspace?")
    inside = "() => Boolean(document.activeElement && document.activeElement.closest('[role=dialog]'))"
    assert harness.page.evaluate(inside)
    for _ in range(4):
        harness.page.keyboard.press("Tab")
        assert harness.page.evaluate(inside), "Tab left the dialog"

    harness.page.keyboard.press("Escape")
    expect(harness.dialog).to_have_count(0)
    expect(harness.add_button()).to_be_focused()
    assert not harness.promotions


def test_the_actions_fit_a_phone_and_work_there(page, harness):
    page.set_viewport_size({"width": 390, "height": 844})
    harness.open([card(artifact())])

    for button in (harness.powerpoint_button(), harness.add_button()):
        expect(button).to_be_visible()
        box = button.bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= 390, box
        assert box["height"] >= 32, "A comfortable touch target"
    assert harness.no_horizontal_scroll()

    harness.add_button().click()
    dialog = harness.dialog
    expect(dialog).to_be_visible()
    for name in ("Cancel", "Add to Personal"):
        edge = dialog.get_by_role("button", name=name).bounding_box()
        assert edge and edge["x"] >= 0 and edge["x"] + edge["width"] <= 390, (name, edge)
    assert harness.no_horizontal_scroll()
    dialog.get_by_role("button", name="Add to Personal").click()
    expect(harness.toast("Added to your personal workspace.")).to_be_visible()
    expect(harness.card_of(MARKDOWN_NAME).get_by_role("status").filter(has_text="Added to workspace")).to_be_visible()
    assert harness.no_horizontal_scroll()

    with page.expect_download():
        harness.powerpoint_button().click()
    expect(harness.toast("Markdown artifact exported as PowerPoint.")).to_be_visible()
