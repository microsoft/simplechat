# test_v2_plan_editor_references.py
"""
Browser tests for `#` document and tag references in the plan editor's Ask AI.
Version: 0.261.201
Implemented in: 0.261.201

The plan editor's input is restricted: it offers `#` documents and tags and Add context, but no
uploads and no `/` prompts. A picked chip travels with the request, shows in the reader's turn,
and a stale one is refused in the planner's turn with Edit and resend. The main composer and
the question card keep their full tools, and the diagram, chart and image editors offer no `#`
picker at all.

Only HTTP boundaries are stubbed, with `page.route`; no live data or credentials are used. The
planner stub mirrors the server's contract for references: it names a refused reference by the
label the reader picked, stores the server's own label with the user turn, and replays a
submission id without merging its references again. The server itself has functional coverage
in functional_tests/test_orchestration_plan_revision_references.py.

Build the plan editor's styles and the V2 SPA first:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
npm --prefix .\\application\\v2_ui run build
Run: python -m pytest .\\ui_tests\\test_v2_plan_editor_references.py -q
"""

import copy
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "fixtures"))
sys.path.insert(0, str(HERE / "fixtures" / "orchestration"))

# The plan editor, assist thread and question card harnesses live in their own test modules.
import harness_build as hb  # noqa: E402
import test_v2_assist_thread as assist_tests  # noqa: E402
import test_v2_orchestration_plan_editor as editor_tests  # noqa: E402
from image_editor import ImageEditorFixture, image_editor_assets, image_profile  # noqa: E402, F401
from playwright_connection import connect_options  # noqa: E402, F401
from test_v2_elicitation_composer import InlineApi  # noqa: E402
from test_v2_orchestration_plan_editor import (  # noqa: E402, F401
    editor_assets,
    editor_browser,
    planner_log,
    state,
    thread_exchanges,
    wait_revision,
)


pytestmark = pytest.mark.ui
PERSONAL = "/api/documents"
GROUP = "/api/group_documents"
PUBLIC = "/api/public_workspace_documents"
WORKSPACE_READS = {PERSONAL, GROUP, PUBLIC, f"{PERSONAL}/tags", f"{GROUP}/tags", f"{PUBLIC}/tags"}
SALES_TEAM = {"id": "group-1", "name": "Sales team"}
HOSTILE = '<img src=x onerror="window.__refXss=1">Board notes'
CHIPS_RETURNED = (
    "The planner answered without changing the plan, so your documents and tags are back in the "
    "input. Send again to use them, or remove them."
)
Q3_REF = {"kind": "document", "id": "doc-q3", "scope": {"kind": "personal", "id": None}, "label": "Q3 pricing"}
Q4_REF = {"kind": "document", "id": "doc-q4", "scope": {"kind": "personal", "id": None}, "label": "Q4 pricing"}
GROUP_REF = {
    "kind": "document", "id": "doc-group", "scope": {"kind": "group", "id": "group-1"}, "label": "Regional pricing",
}
TAG_REF = {"kind": "tag", "id": "pricing", "scope": {"kind": "personal", "id": None}, "label": "pricing"}
# Instructions in this file avoid "add" and "remove": the shared planner stub reads those as
# requests to change the plan's web step.


def workspace_document(document_id, title, file_name, **extra):
    return {
        "id": document_id, "title": title, "file_name": file_name,
        "status": "Processing complete", "percentage_complete": 100, **extra,
    }


def unavailable(label):
    return f"\u201c{label}\u201d is no longer available to you. Remove it and pick another document."


def scope_notice(*items):
    joined = f"{', '.join(items[:-1])} and {items[-1]}" if len(items) > 1 else items[0]
    return f"Searches in this plan now look only at what you attached: {joined}."


class ReferenceApi(editor_tests.EditorApi):
    """The plan editor's planner, workspace lists and tag vocabularies, with `#` references."""

    def __init__(self, assets):
        super().__init__(assets)
        self.documents = {
            PERSONAL: [
                workspace_document("doc-q3", "Q3 pricing", "q3-pricing.pdf"),
                workspace_document("doc-q4", "Q4 pricing", "q4-pricing.pdf"),
            ],
            GROUP: [workspace_document("doc-group", "Regional pricing", "regional.pdf", group_id="group-1")],
            PUBLIC: [],
        }
        self.tags = {f"{PERSONAL}/tags": [{"name": "pricing"}], f"{GROUP}/tags": [], f"{PUBLIC}/tags": []}
        # Documents the reader could once pick and no longer can read: deleted, or access removed.
        self.unavailable = set()
        self.document_reads = []
        self.replays = []
        self.narrowed = set()

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        if (request.method == "GET" and f"{parsed.scheme}://{parsed.netloc}" == editor_tests.ORIGIN
                and parsed.path in WORKSPACE_READS):
            self.document_reads.append(f"{parsed.path}?{parsed.query}")
            if parsed.path in self.tags:
                route.fulfill(json={"tags": copy.deepcopy(self.tags[parsed.path])})
                return
            search = parse_qs(parsed.query).get("search", [""])[0].lower()
            documents = [
                document for document in self.documents[parsed.path]
                if search in f"{document['title']} {document['file_name']}".lower()
            ]
            route.fulfill(json={"documents": copy.deepcopy(documents), "total_count": len(documents)})
            return
        super().handle(route)

    def server_label(self, reference):
        if reference["kind"] == "tag":
            return reference["id"]
        for documents in self.documents.values():
            for document in documents:
                if document["id"] == reference["id"]:
                    return document["title"]
        raise AssertionError(f"Unknown document {reference['id']}")

    def narrow(self, editor, references):
        """Picked documents replace the plan's search; the first narrowing says so once."""
        documents = [reference for reference in references if reference["kind"] == "document"]
        tags = [reference for reference in references if reference["kind"] == "tag"]
        plan = editor["plan"]
        if documents:
            names = {reference["id"]: self.server_label(reference) for reference in documents}
            read = next(step for step in plan["steps"] if step["step_id"] == "read")
            read["arguments"]["document_ids"] = list(names)
            plan["inputs"]["documents"] = [
                {"document_id": document_id, "display_name": name, "selected_by_user": True}
                for document_id, name in names.items()
            ]
            self.records[plan["run_id"]] = copy.deepcopy(plan)
        if plan["conversation_id"] in self.narrowed:
            return None
        self.narrowed.add(plan["conversation_id"])
        return {
            "kind": "search_limited",
            "documents": [self.server_label(reference) for reference in documents],
            "tags": [reference["id"] for reference in tags],
            "more": 0,
        }

    def revise(self, route, editor, body, behavior):
        if body["action"] != "ask" or behavior not in ("success", "explain", "lost"):
            super().revise(route, editor, body, behavior)
            return
        submission = body["submission_id"]
        if submission in self.submissions:
            saved_body, event = self.submissions[submission]
            assert saved_body == body, "An idempotency token must not identify changed input."
            # A replay returns what was stored; its references are not checked or merged again.
            self.replays.append(submission)
            self.stream(route, event)
            return
        attempted = self.attempts.get(submission)
        if attempted is not None and attempted != body:
            self.error(route, 409, "That submission ID was already used for a different edit.",
                       "submission_conflict")
            return
        if body["expected_version"] != editor["version"]:
            self.error(route, 409, "The plan changed. Review its current saved revision.",
                       "plan_changed", editor["plan"]["run_id"])
            return
        self.attempts[submission] = copy.deepcopy(body)
        references = body.get("references", [])
        refused = next((reference for reference in references if reference["id"] in self.unavailable), None)
        if refused:
            # Refused before anything is saved, named by the label the reader picked.
            editor["busy"] = False
            self.error(route, 400, unavailable(refused["label"]), "reference_unavailable")
            return
        if "edits" in body:
            editor["edits"] = copy.deepcopy(body["edits"])
        instruction = body["instruction"]
        turn = {"role": "user", "content": instruction, "timestamp": "2026-09-07T15:00:00Z",
                "submission_id": submission}
        if references:
            turn["references"] = [{
                "kind": reference["kind"], "id": reference["id"], "label": self.server_label(reference),
                "scope": copy.deepcopy(reference["scope"]),
            } for reference in references]
        editor["chat"].append(turn)
        reply = {"role": "assistant", "timestamp": "2026-09-07T15:00:02Z", "submission_id": submission}
        if behavior == "explain":
            reply.update(content=f"Kept the saved plan. Your request was: {instruction}",
                         timestamp="2026-09-07T15:00:01Z")
            editor["busy"] = False
            self.touch(editor)
        else:
            self.publish(editor, instruction)
            notice = self.narrow(editor, references) if references else None
            reply["content"] = editor["history"][0]["note"]
            if notice:
                reply["scope_notice"] = notice
        editor["chat"].append(reply)
        event = self.result(editor)
        self.submissions[submission] = (copy.deepcopy(body), event)
        if behavior == "lost":
            self.expected_errors.add((urlsplit(route.request.url).path, "net::ERR_FAILED"))
            route.abort("failed")
        else:
            self.stream(route, event)


@pytest.fixture
def reference_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = ReferenceApi(editor_assets)
    errors = []
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: errors.append(str(error)))

    def console_error(message):
        if message.type != "error":
            return
        path = urlsplit(message.location.get("url", "")).path
        if any(path == expected_path and str(status) in message.text for expected_path, status in api.expected_errors):
            return
        errors.append(message.text)

    page.on("console", console_error)
    try:
        yield page, api
    finally:
        api.release()
        context.close()
        assert not api.unexpected, f"Unexpected browser requests: {api.unexpected}"
        assert not errors, f"Unexpected browser errors: {errors}"


def mount_editor(page, api):
    """Open the plan editor's Ask AI, with uploads, prompts and a group workspace all on."""
    editor_tests.mount(page, api)
    page.evaluate(
        """(group) => {
            const store = window.OrchHarness.stores.bootstrap.useBootstrapStore;
            const data = store.getState().data;
            store.setState({ data: {
                ...data,
                features: { ...data.features, enable_user_workspace: true,
                    enable_group_workspaces: true, enable_chat_file_uploads: true },
                scope: { groups: [group], public_workspaces: [] },
                catalogs: { ...data.catalogs, prompts: [{ id: 'summary-prompt', name: 'Summary',
                    content: 'Summarize {{composer}}.', scope_type: 'personal' }] },
            } });
        }""",
        SALES_TEAM,
    )
    dialog = editor_tests.open_editor(page)
    dialog.get_by_role("tab", name="Ask planner", exact=True).click()
    return dialog


def composer(dialog):
    return dialog.get_by_role("textbox", name="Ask planner", exact=True)


def suggestions(page):
    return page.get_by_role("listbox", name="Context suggestions")


def send(dialog):
    dialog.get_by_role("button", name="Send planner request").click()


def wait_for_calls(page, api, count, timeout=10):
    """Let the page's requests reach the route handler, which runs while Playwright waits."""
    deadline = time.monotonic() + timeout
    while len(api.calls("/revisions")) < count:
        assert time.monotonic() < deadline, f"Expected {count} revision requests."
        page.wait_for_timeout(50)


def test_hash_picks_a_document_by_keyboard_and_the_revised_plan_reads_it(reference_ui):
    page, api = reference_ui
    dialog = mount_editor(page, api)
    textbox = composer(dialog)
    options = suggestions(page).get_by_role("option")

    # Restricted: documents and tags, but no uploads or prompts even though both are enabled.
    expect(dialog.get_by_role("button", name="Add context", exact=True)).to_be_visible()
    expect(dialog.get_by_role("button", name="Attach a file")).to_have_count(0)
    expect(dialog.locator('input[type="file"]')).to_have_count(0)
    textbox.fill("/Summ")
    page.wait_for_timeout(300)
    expect(page.get_by_role("listbox", name="Prompt suggestions")).to_have_count(0)

    # A bare # offers documents from every workspace and tags, but never a whole workspace.
    textbox.fill("#")
    expect(options).to_have_count(4)
    expect(suggestions(page).get_by_role("option", name=re.compile("Everything in this workspace"))).to_have_count(0)

    textbox.fill("Focus the comparison on ")
    # Typed, not filled: fill() sends no key events, so React's onSelect would first fire on the
    # next key press and re-sync the menu (see the ComposerEditor follow-up in the A2 PR).
    textbox.press_sequentially("#q")
    expect(options).to_have_count(2)
    expect(options.nth(0)).to_contain_text("Q3 pricing")
    expect(options.nth(0)).to_have_attribute("aria-selected", "true")
    textbox.press("ArrowDown")
    expect(options.nth(1)).to_have_attribute("aria-selected", "true")
    textbox.press("ArrowDown")
    expect(options.nth(0)).to_have_attribute("aria-selected", "true")
    textbox.press("ArrowUp")
    expect(options.nth(1)).to_have_attribute("aria-selected", "true")
    expect(options.nth(0)).to_have_attribute("aria-selected", "false")
    textbox.press("Enter")
    expect(textbox).to_have_value("Focus the comparison on #[Q4 pricing] ")
    expect(suggestions(page)).to_have_count(0)
    expect(dialog.get_by_role("button", name="Remove Q4 pricing", exact=True)).to_be_visible()
    preview = dialog.get_by_test_id("plan-editor-preview")
    expect(preview.get_by_text("Report A", exact=True)).to_be_visible()

    api.next_revision = "delay"
    textbox.press("Enter")
    # The chip moves into the reader's turn at once, before the planner answers.
    exchange = thread_exchanges(dialog)
    expect(exchange).to_have_attribute("data-status", "pending")
    expect(exchange.get_by_test_id("assist-reference-chip")).to_have_text("Document: Q4 pricing")
    expect(textbox).to_have_value("")
    expect(dialog.get_by_role("button", name="Remove Q4 pricing", exact=True)).to_have_count(0)
    wait_for_calls(page, api, 1)
    sent = api.calls("/revisions")[0]["body"]
    assert sent["action"] == "ask"
    assert sent["instruction"] == "Focus the comparison on #[Q4 pricing]"
    assert sent["references"] == [Q4_REF]

    api.release()
    wait_revision(page, 1)
    log = planner_log(dialog)
    expect(thread_exchanges(dialog)).to_have_count(0)
    chip = log.get_by_test_id("assist-reference-chip")
    expect(chip).to_have_count(1)
    expect(chip).to_have_attribute("data-kind", "document")
    expect(chip).to_have_text("Document: Q4 pricing")
    expect(log.get_by_test_id("assist-scope-notice")).to_have_text(scope_notice("Q4 pricing"))
    expect(preview.get_by_text("Q4 pricing", exact=True).first).to_be_visible()
    expect(preview.get_by_text("Report A", exact=True)).to_have_count(0)
    assert state(page)["plan"]["steps"][0]["arguments"]["document_ids"] == ["doc-q4"]


def test_add_context_picks_group_documents_and_tags_and_escape_keeps_the_editor_open(reference_ui):
    page, api = reference_ui
    dialog = mount_editor(page, api)
    textbox = composer(dialog)
    add_context = dialog.get_by_role("button", name="Add context", exact=True)
    add_context.click()
    picker = dialog.locator("[data-context-picker]")
    search = picker.get_by_role("searchbox", name="Search documents")
    expect(search).to_be_focused()
    expect(search).to_have_attribute("placeholder", "Search documents and tags\u2026")
    expect(picker.get_by_text("Search all my documents")).to_have_count(0)
    group_row = picker.get_by_role("button", name=re.compile(r"^Regional pricing"))
    tag_row = picker.get_by_role("button", name=re.compile(r"^pricing\s*Tag"))
    expect(group_row).to_be_visible()
    expect(picker.get_by_role("button", name=re.compile("Everything in this workspace"))).to_have_count(0)
    group_row.click()
    expect(group_row).to_have_attribute("aria-pressed", "true")
    tag_row.click()
    expect(tag_row).to_have_attribute("aria-pressed", "true")
    assert any(read.startswith(f"{GROUP}?") and "group_ids=group-1" in read for read in api.document_reads)

    # Escape closes the picker first and puts the reader back in the input.
    search.focus()
    page.keyboard.press("Escape")
    expect(picker).to_have_count(0)
    expect(dialog).to_be_visible()
    expect(textbox).to_be_focused()
    expect(dialog.get_by_role("button", name="Remove Regional pricing", exact=True)).to_be_visible()
    expect(dialog.get_by_role("button", name="Remove pricing", exact=True)).to_be_visible()

    # So does the # menu (typed for the same reason as above).
    textbox.fill("Use ")
    textbox.press_sequentially("#reg")
    expect(suggestions(page).get_by_role("option")).to_have_count(1)
    textbox.press("Escape")
    expect(suggestions(page)).to_have_count(0)
    expect(dialog).to_be_visible()
    expect(textbox).to_be_focused()

    textbox.fill("Use the regional figures")
    send(dialog)
    wait_revision(page, 1)
    assert api.calls("/revisions")[-1]["body"]["references"] == [GROUP_REF, TAG_REF]
    log = planner_log(dialog)
    expect(log.get_by_test_id("assist-reference-chip")).to_have_text(["Document: Regional pricing", "Tag: pricing"])
    expect(log.get_by_test_id("assist-scope-notice")).to_have_text(scope_notice("Regional pricing", "tag pricing"))


def test_a_chip_removed_before_sending_is_not_sent(reference_ui):
    page, api = reference_ui
    dialog = mount_editor(page, api)
    textbox = composer(dialog)
    options = suggestions(page).get_by_role("option")
    textbox.fill("Compare #q")
    expect(options).to_have_count(2)
    textbox.press("Enter")
    expect(textbox).to_have_value("Compare #[Q3 pricing] ")
    textbox.fill("Compare #[Q3 pricing] and #q4")
    expect(options).to_have_count(1)
    textbox.press("Tab")
    expect(textbox).to_have_value("Compare #[Q3 pricing] and #[Q4 pricing] ")

    dialog.get_by_role("button", name="Remove Q3 pricing", exact=True).click()
    expect(textbox).to_have_value("Compare and #[Q4 pricing] ")
    send(dialog)
    wait_revision(page, 1)
    assert api.calls("/revisions")[-1]["body"]["references"] == [Q4_REF]

    # Deleting a chip's token from the text drops the chip too.
    textbox.fill("Summarize #q")
    expect(options).to_have_count(2)
    textbox.press("Enter")
    expect(dialog.get_by_role("button", name="Remove Q3 pricing", exact=True)).to_be_visible()
    textbox.fill("Summarize the pricing")
    expect(dialog.get_by_role("button", name="Remove Q3 pricing", exact=True)).to_have_count(0)
    send(dialog)
    wait_revision(page, 2)
    assert "references" not in api.calls("/revisions")[-1]["body"]
    expect(planner_log(dialog).get_by_test_id("assist-reference-chip")).to_have_text(["Document: Q4 pricing"])


def test_a_stale_reference_is_refused_in_the_planner_turn_and_edit_and_resend_restores_it(reference_ui):
    page, api = reference_ui
    api.unavailable = {"doc-q3"}
    dialog = mount_editor(page, api)
    textbox = composer(dialog)
    options = suggestions(page).get_by_role("option")
    textbox.fill("Focus on #q")
    expect(options).to_have_count(2)
    textbox.press("Enter")
    expect(textbox).to_have_value("Focus on #[Q3 pricing] ")
    send(dialog)

    exchange = thread_exchanges(dialog)
    expect(exchange).to_have_attribute("data-status", "failed")
    expect(exchange.get_by_role("alert")).to_have_text(unavailable("Q3 pricing"))
    expect(exchange.get_by_test_id("assist-reference-chip")).to_have_text("Document: Q3 pricing")
    expect(dialog.get_by_role("alert")).to_have_count(1)
    expect(textbox).to_have_value("")
    expect(thread_exchanges(dialog)).to_have_count(1)
    first = api.calls("/revisions")[0]["body"]
    assert first["references"] == [Q3_REF]
    assert api.editors["editor-chat"]["chat"] == []
    assert state(page)["plan"]["revision"] == 0

    # Retry sends the very same request, which is refused the same way.
    exchange.get_by_role("button", name="Retry", exact=True).click()
    wait_for_calls(page, api, 2)
    expect(exchange).to_have_attribute("data-status", "failed")
    assert api.calls("/revisions")[1]["body"] == first

    exchange.get_by_role("button", name="Edit and resend", exact=True).click()
    expect(thread_exchanges(dialog)).to_have_count(0)
    expect(textbox).to_have_value(re.compile(r"^Focus on #\[Q3 pricing\]\s*$"))
    dialog.get_by_role("button", name="Remove Q3 pricing", exact=True).click()
    textbox.fill("Focus on #q4")
    expect(options).to_have_count(1)
    textbox.press("Enter")
    send(dialog)
    wait_revision(page, 1)
    last = api.calls("/revisions")[-1]["body"]
    assert last["references"] == [Q4_REF]
    assert last["submission_id"] != first["submission_id"]
    expect(dialog.get_by_role("alert")).to_have_count(0)


def test_chips_come_back_when_the_planner_answers_without_changing_the_plan(reference_ui):
    page, api = reference_ui
    dialog = mount_editor(page, api)
    textbox = composer(dialog)
    options = suggestions(page).get_by_role("option")
    api.next_revision = "explain"
    textbox.fill("Check #q4")
    expect(options).to_have_count(1)
    textbox.press("Enter")
    send(dialog)

    log = planner_log(dialog)
    expect(log.get_by_text("Kept the saved plan. Your request was: Check #[Q4 pricing]", exact=True)).to_be_visible()
    expect(dialog.get_by_text(CHIPS_RETURNED, exact=True)).to_be_visible()
    expect(dialog.get_by_role("button", name="Remove Q4 pricing", exact=True)).to_be_visible()
    expect(textbox).to_have_value("")
    assert state(page)["plan"]["revision"] == 0
    explained = api.calls("/revisions")[-1]["body"]

    textbox.fill("Now focus on the totals")
    send(dialog)
    wait_revision(page, 1)
    resent = api.calls("/revisions")[-1]["body"]
    assert resent["references"] == explained["references"] == [Q4_REF]
    assert resent["submission_id"] != explained["submission_id"]
    expect(dialog.get_by_text(CHIPS_RETURNED, exact=True)).to_have_count(0)
    expect(log.get_by_test_id("assist-scope-notice")).to_have_text(scope_notice("Q4 pricing"))


def test_untrusted_document_titles_render_as_text(reference_ui):
    page, api = reference_ui
    api.documents[PERSONAL].append(workspace_document("doc-board", HOSTILE, "board.pdf"))
    dialog = mount_editor(page, api)
    textbox = composer(dialog)
    options = suggestions(page).get_by_role("option")
    textbox.fill("Summarize #board")
    expect(options).to_have_count(1)
    textbox.press("Enter")
    send(dialog)
    wait_revision(page, 1)

    assert api.calls("/revisions")[-1]["body"]["references"][0]["label"] == HOSTILE
    log = planner_log(dialog)
    expect(log.get_by_test_id("assist-reference-chip")).to_have_text(f"Document: {HOSTILE}")
    expect(log.get_by_test_id("assist-scope-notice")).to_have_text(scope_notice(HOSTILE))
    expect(dialog.get_by_test_id("plan-editor-preview").get_by_text(HOSTILE, exact=True).first).to_be_visible()
    expect(page.locator('img[src="x"]')).to_have_count(0)
    assert page.evaluate("() => window.__refXss") is None


def test_a_lost_reply_is_retried_under_the_same_id_and_its_references_merge_once(reference_ui):
    page, api = reference_ui
    dialog = mount_editor(page, api)
    textbox = composer(dialog)
    options = suggestions(page).get_by_role("option")
    api.next_revision = "lost"
    textbox.fill("Focus on #q4")
    expect(options).to_have_count(1)
    textbox.press("Enter")
    send(dialog)
    exchange = thread_exchanges(dialog)
    expect(exchange).to_have_attribute("data-status", "failed")
    assert state(page)["plan"]["revision"] == 0

    exchange.get_by_role("button", name="Retry", exact=True).click()
    wait_revision(page, 1)
    first, retry = (call["body"] for call in api.calls("/revisions"))
    assert retry == first and first["references"] == [Q4_REF]
    assert api.replays == [first["submission_id"]]
    log = planner_log(dialog)
    expect(thread_exchanges(dialog)).to_have_count(0)
    expect(log.get_by_test_id("assist-reference-chip")).to_have_count(1)
    expect(log.get_by_test_id("assist-scope-notice")).to_have_count(1)
    assert [turn["role"] for turn in api.editors["editor-chat"]["chat"]] == ["user", "assistant"]
    assert state(page)["plan"]["steps"][0]["arguments"]["document_ids"] == ["doc-q4"]


def test_the_main_composer_and_question_card_keep_their_full_tools(editor_browser):
    hb.ensure_bundle()
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    api = InlineApi(context.new_page())
    whole_workspace = re.compile(r"^My workspace\s*Everything in this workspace")
    try:
        api.open(main_composer=True)
        main = api.page.locator("#mount-a")
        message = main.get_by_role("textbox", name="Message", exact=True)
        expect(main.get_by_role("button", name="Attach a file")).to_have_count(1)
        message.fill("/Summ")
        expect(main.get_by_role("listbox", name="Prompt suggestions")).to_be_visible()
        message.fill("#my")
        expect(main.get_by_role("option", name=whole_workspace)).to_be_visible()
        message.fill("")

        card = api.card.get_by_role("textbox", name="Additional details for Source files (optional)", exact=True)
        expect(api.card.get_by_role("button", name="Attach a file", exact=True)).to_be_visible()
        card.fill("#my")
        expect(api.card.get_by_role("option", name=whole_workspace)).to_be_visible()
        card.fill("/Summ")
        expect(api.card.get_by_role("listbox", name="Prompt suggestions")).to_be_visible()
    finally:
        context.close()
    assert not api.errors, api.errors
    assert not api.unexpected, api.unexpected


@pytest.mark.parametrize("name", ["diagram", "chart"])
def test_the_diagram_and_chart_editors_offer_no_hash_references(editor_browser, name):
    hb.ensure_bundle()
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = assist_tests.AssistApi(page)
    reads = []
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    page.on("console", api.record_console)
    page.on("request", lambda request: reads.append(request.url)
            if urlsplit(request.url).path in WORKSPACE_READS else None)
    try:
        assist_tests.mount(api)
        editor = assist_tests.Editor(page, name).open()
        reads.clear()
        expect(editor.dialog.get_by_role("button", name="Add context")).to_have_count(0)
        editor.input.fill("#report")
        page.wait_for_timeout(400)
        expect(page.get_by_role("listbox", name="Context suggestions")).to_have_count(0)
        assert reads == []
    finally:
        api.drop_held()
        context.close()
    assert not api.errors, f"Unexpected browser errors: {api.errors}"
    assert not api.unexpected, f"Unexpected browser requests: {api.unexpected}"


def test_the_image_editor_offers_no_hash_references(editor_browser, image_editor_assets):
    context = editor_browser.new_context()
    page = context.new_page()
    try:
        # The image fixture records any workspace read as an unexpected request.
        image = ImageEditorFixture(page, image_editor_assets)
        image.open(capability=image_profile())
        expect(page.get_by_role("button", name="Add context")).to_have_count(0)
        page.get_by_label("Describe the change", exact=True).fill("#report")
        page.wait_for_timeout(400)
        expect(page.get_by_role("listbox", name="Context suggestions")).to_have_count(0)
        image.assert_clean()
    finally:
        context.close()
