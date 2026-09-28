# test_v2_group_document_management.py
"""
Closed, real-SPA browser scenarios for M2B group document management.
Version: 0.261.174
Implemented in: 0.261.129
Coded failures show the server's sentence, delete guards name the conversation, and an archive takes
the server's name: 0.261.164
A tag vocabulary conflict shows its sentence; the empty explorer and a refused change say who can
change documents, or why no one can, and never point at classic: 0.261.167
A manager who can't upload is told why when dropping files: 0.261.168
The group's content screening controls, offered to the members the screening routes accept: 0.261.174
Every scripted receipt is the server's (the builders in fixtures/group_document_management.py,
pinned by functional_tests/test_group_document_fixture_parity.py), except the deliberately
malformed receipts each robustness scenario names.

Only HTTP responses are scripted. Components, stores, navigation, downloads,
selection and validation execute in the production SPA. No live service/model
writes are allowed. Collect/static-check this file while production wiring is
in progress; run it only against an explicitly ready, freshly built SPA.

PYTHONPATH must include ui_tests\\fixtures for the shared Azure Playwright
connection fixture. Set SIMPLECHAT_UI_SCREENSHOTS to a short session-files
directory when taking the desktop/mobile, light/dark captures.
"""

import copy
import io
import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.group_document_management import (
    CONVERSATION_DELETE_MESSAGE, DOCUMENT_ACTIONS, DOCUMENT_CHANGED_ERROR, DOCUMENT_DELETED_MESSAGE,
    DOCUMENT_OPERATION_FAILED_ERROR, GROUP_ARCHIVE_NAME, METADATA_UPDATED_MESSAGE, OPERATIONS,
    PROPAGATION_INCOMPLETE_MESSAGE, SYNCED_DELETE_OPTIONS, TAG_CREATED_MESSAGE, TAG_REVISION_CHANGED_ERROR,
    VOCABULARY_CONFLICT_CODE, VOCABULARY_CONFLICT_MESSAGE,
    attachment, batch_error, bulk_tag_result, connect_options, conversation_delete_guard,  # noqa: F401
    delete_result, group_management_ui, metadata_result, operation_path, propagation_incomplete,  # noqa: F401
    queue_result, synced_delete_guard, tag_created, tag_result, tag_vocabulary_conflict, tag_vocabulary_refusal,
    upload_refusal, upload_result,
)
from ui_tests.fixtures.group_documents import ARTIFACT_AWAITING_APPROVAL_STATUS, document, pending_artifact, restricted
from ui_tests.fixtures.workspace_authoring import ORIGIN, OWNER_ID


pytestmark = pytest.mark.ui
SCREENSHOTS = Path(os.environ.get(
    "SIMPLECHAT_UI_SCREENSHOTS", str(Path(__file__).parent / "artifacts" / "gm"),
))
GROUP_CONTEXT = "/api/v2/workspaces/group/group-a"


def explorer(ui):
    return ui.page.get_by_role("group", name="Documents explorer", exact=True)


def command(ui, label):
    return explorer(ui).get_by_role("button", name=label, exact=True).first


def details_button(ui, identifier, group_id="group-a"):
    record = ui.record(identifier, group_id)
    name = record.get("title") or record["file_name"]
    return ui.page.get_by_role("button", name=f"Details for {name}", exact=True)


def document_row(ui, identifier, group_id="group-a"):
    return ui.page.get_by_role("row").filter(has=details_button(ui, identifier, group_id))


def checkbox(ui, identifier, group_id="group-a"):
    return document_row(ui, identifier, group_id).get_by_role("checkbox")


def response_for(method, path):
    return lambda response: response.request.method == method and urlsplit(response.url).path == path


def perform(ui, reply, action):
    with ui.page.expect_response(response_for(reply.method, reply.path)) as pending:
        action()
    response = pending.value
    assert response.status == reply.status
    is_download = reply.method in ("GET", "POST") and reply.path.endswith("/download")
    # Refused downloads leave bodies unread; callers await the UI refusal or save complete bytes.
    if not is_download:
        response.finished()
    return response


def open_documents(ui, **options):
    ui.open("/groups/group-a/documents", **options)
    expect(details_button(ui, "same-document")).to_be_visible()
    expect(explorer(ui)).to_have_attribute("aria-busy", "false")
    expect(explorer(ui)).to_be_enabled()


def clear_selection(ui):
    expect(explorer(ui)).to_be_enabled()
    ui.page.get_by_role("button", name=re.compile(r"^Details for ")).first.focus()
    ui.page.keyboard.press("Escape")
    expect(explorer(ui).locator('input[type="checkbox"]:checked')).to_have_count(0)


def select_documents(ui, *identifiers):
    clear_selection(ui)
    for index, identifier in enumerate(identifiers):
        if index == 0:
            with ui.page.expect_response(response_for("GET", f"/api/group_documents/{identifier}")) as detail:
                checkbox(ui, identifier).check()
            detail.value.finished()
        else:
            checkbox(ui, identifier).check()
        expect(checkbox(ui, identifier)).to_be_checked()
    expect(explorer(ui)).to_be_enabled()


def show_details(ui, identifier="same-document"):
    with ui.page.expect_response(response_for("GET", f"/api/group_documents/{identifier}")) as detail:
        details_button(ui, identifier).click()
    detail.value.finished()
    expect(ui.page.get_by_role("button", name="Refresh document details", exact=True)).to_be_enabled()


def edit_metadata(ui):
    show_details(ui)
    ui.page.get_by_role("button", name="Edit", exact=True).click()
    dialog = ui.page.get_by_role("dialog", name="Edit metadata", exact=True)
    expect(dialog).to_be_visible()
    return dialog


def assert_no_personal_controls(ui):
    for label in ("Share", "Save view", "Approve", "Reject", "Remove from this group"):
        expect(explorer(ui).get_by_role("button", name=label, exact=True)).to_have_count(0)
    expect(ui.page.get_by_text("Personal private view", exact=True)).to_have_count(0)


def assert_read_only(ui):
    for label in ("Upload", "Upload a document", "Tag", "Edit", "Extract", "Delete", "Download"):
        expect(explorer(ui).get_by_role("button", name=label, exact=True)).to_have_count(0)
    expect(explorer(ui).get_by_role("button", name=re.compile(r"Enhanced|Standard"))).to_have_count(0)
    expect(explorer(ui).locator('input[type="file"]')).to_have_count(0)
    expect(explorer(ui).get_by_role("button", name=re.compile(r"^Remove tag "))).to_have_count(0)
    assert_no_personal_controls(ui)


def open_tags(ui):
    ui.open("/groups/group-a/tags")
    expect(ui.page.get_by_role("heading", name="Tags", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="finance", exact=True)).to_be_visible()


def tag_row(ui, name):
    return ui.page.get_by_role("listitem").filter(
        has=ui.page.get_by_label(f"Colour for {name}", exact=True),
    )


def begin_rename(ui, name, new_name):
    item = tag_row(ui, name)
    item.get_by_role("button", name=name, exact=True).click()
    item.get_by_role("textbox", name=f"Rename {name}", exact=True).fill(new_name)
    return item


def changed_record(ui, identifier, **changes):
    return {**copy.deepcopy(ui.record(identifier)), **copy.deepcopy(changes)}


def drop_on_tag(ui, name, payload):
    filters = ui.page.get_by_role("navigation", name="Document filters", exact=True)
    filters.get_by_role("button", name=re.compile(rf"^{re.escape(name)}\b")).evaluate(
        """(element, payload) => {
            const transfer = new DataTransfer();
            transfer.setData('application/x-simplechat-documents', JSON.stringify(payload));
            element.dispatchEvent(new DragEvent('drop', {
                bubbles: true, cancelable: true, dataTransfer: transfer,
            }));
        }""",
        payload,
    )


def test_missing_or_unknown_handshake_keeps_every_entry_point_read_only(group_management_ui):
    ui = group_management_ui
    for handshake in (None, {"schema_version": 99, "operations": list(OPERATIONS)}):
        if handshake is None:
            ui.groups["group-a"].pop("document_management")
        else:
            ui.groups["group-a"]["document_management"] = handshake
        open_documents(ui)
        select_documents(ui, "same-document")
        assert_read_only(ui)
        expect(document_row(ui, "same-document")).to_have_attribute("draggable", "false")
        ui.page.get_by_role("table").evaluate("""element => {
            const transfer = new DataTransfer();
            transfer.items.add(new File(['blocked'], 'blocked.txt', {type: 'text/plain'}));
            element.dispatchEvent(new DragEvent('drop', {
                bubbles: true, cancelable: true, dataTransfer: transfer,
            }));
        }""")
        expect(ui.page.get_by_text(
            "This group's document permissions couldn't be confirmed. Refresh this workspace before managing documents.",
            exact=True,
        )).to_be_visible()
        page_size = ui.page.get_by_label("Documents per page", exact=True)
        current_size = page_size.input_value()
        with ui.page.expect_response(response_for("POST", "/api/user/settings")) as preferences:
            page_size.select_option("50" if current_size == "25" else "25")
        preferences.value.finished()
        expect(explorer(ui)).to_have_attribute("aria-busy", "false")
        assert not ui.operation_requests
        assert ui.preferences["v2DocumentSavedViews"][0]["name"] == "Personal private view"
    ui.documents["group-a"] = []
    ui.open("/groups/group-a/documents")
    expect(ui.page.get_by_text("No documents yet", exact=True)).to_be_visible()
    # An unreadable hint is never read as the viewer's role: an Owner here is asked to refresh.
    expect(explorer(ui).get_by_text(
        "This group's document permissions couldn't be confirmed. Refresh this workspace to check whether you can "
        "add documents.", exact=True,
    )).to_be_visible()
    assert_read_only(ui)


EMPTY_GROUP_CASES = [
    ("Owner", "active", None),
    ("User", "active", "This group's owner, admins and document managers can add documents."),
    ("DocumentManager", "upload_disabled", "Document uploads are disabled for this group."),
    ("User", "upload_disabled", "Document uploads are disabled for this group."),
    ("Owner", "locked", "This group is locked (read-only), so documents can't be added."),
]


@pytest.mark.parametrize("role, status, description", EMPTY_GROUP_CASES)
def test_an_empty_group_says_who_can_add_documents_and_never_offers_classic(group_management_ui, role, status, description):
    ui = group_management_ui
    ui.set_policy(role=role, status=status)
    ui.documents["group-a"] = []
    ui.open("/groups/group-a/documents")
    expect(ui.page.get_by_text("No documents yet", exact=True)).to_be_visible()
    upload = explorer(ui).get_by_role("button", name="Upload a document", exact=True)
    if description is None:
        expect(explorer(ui).get_by_text("Upload a file to make it available for grounded chat.", exact=True)).to_be_visible()
        expect(upload).to_be_visible()
    else:
        expect(explorer(ui).get_by_text(description, exact=True)).to_be_visible()
        expect(upload).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Manage files in classic", exact=True)).to_have_count(0)
    expect(explorer(ui).get_by_text(re.compile("classic", re.IGNORECASE))).to_have_count(0)
    assert not ui.operation_requests


def drop_file(ui):
    ui.page.get_by_role("table").evaluate("""element => {
        const transfer = new DataTransfer();
        transfer.items.add(new File(['blocked'], 'blocked.txt', {type: 'text/plain'}));
        element.dispatchEvent(new DragEvent('drop', {
            bubbles: true, cancelable: true, dataTransfer: transfer,
        }));
    }""")


@pytest.mark.parametrize("status, refusal", [
    ("active", "Only this group's owner, admins and document managers can manage its documents."),
    ("locked", "This group is locked (read-only), so its documents can't be changed."),
])
def test_a_member_who_drops_files_is_told_who_manages_documents(group_management_ui, status, refusal):
    ui = group_management_ui
    ui.set_policy(role="User", status=status)
    open_documents(ui)
    assert_read_only(ui)
    drop_file(ui)
    expect(ui.page.get_by_text(refusal, exact=True).first).to_be_visible()
    expect(ui.page.get_by_text("Document management is available in the classic group workspace.", exact=True)).to_have_count(0)
    assert not ui.operation_requests


@pytest.mark.parametrize("role, status, refusal", [
    ("DocumentManager", "upload_disabled", "Document uploads are disabled for this group."),
    ("Owner", "locked", "This group is locked (read-only), so documents can't be added."),
])
def test_a_manager_who_cannot_upload_is_told_why_when_dropping_files(group_management_ui, role, status, refusal):
    ui = group_management_ui
    ui.set_policy(role=role, status=status)
    open_documents(ui)
    expect(explorer(ui).locator('input[type="file"]')).to_have_count(0)
    drop_file(ui)
    # The manager keeps other operations, so the refusal says why no upload can happen, in the empty
    # explorer's words, rather than the per-document answer.
    expect(ui.page.get_by_text(refusal, exact=True).first).to_be_visible()
    expect(ui.page.get_by_text(
        "This operation is not currently permitted for every selected document. Refresh access or adjust the selection.",
        exact=True,
    )).to_have_count(0)
    assert not ui.operation_requests


def test_user_role_is_read_only_in_documents_and_native_tags(group_management_ui):
    ui = group_management_ui
    ui.set_policy(role="User")
    open_documents(ui)
    select_documents(ui, "same-document")
    expect(command(ui, "Chat")).to_be_enabled()
    assert_read_only(ui)
    ui.page.locator('a[href="/v2/groups/group-a/tags"]').first.click()
    expect(ui.page.get_by_role("heading", name="Tags", exact=True)).to_be_visible()
    expect(ui.page.get_by_label("New tag", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Create", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name=re.compile(r"^Delete tag "))).to_have_count(0)
    expect(ui.page.get_by_label(re.compile(r"^Colour for "))).to_have_count(0)
    assert not ui.operation_requests


def test_locked_workspace_only_offers_eligible_downloads(group_management_ui):
    ui = group_management_ui
    ui.set_policy(status="locked")
    open_documents(ui)
    select_documents(ui, "same-document")
    expect(command(ui, "Download")).to_be_enabled()
    # A locked group is read-only, not closed to chat: the server keeps chat on in it.
    expect(command(ui, "Chat")).to_be_enabled()
    for label in ("Upload", "Tag", "Edit", "Delete", "Extract", "Switch to Enhanced"):
        expect(explorer(ui).get_by_role("button", name=label, exact=True)).to_have_count(0)
    expect(checkbox(ui, "held-report")).to_be_disabled()
    # With chat on, a document whose source cannot be downloaded is still selectable (so opening its
    # details keeps the selection). Selected on its own, it offers no download in the command bar or
    # in its details.
    select_documents(ui, "source-denied")
    expect(command(ui, "Download")).to_be_disabled()
    expect(ui.page.get_by_role("complementary").get_by_role("button", name="Download", exact=True)).to_be_disabled()
    assert_no_personal_controls(ui)
    assert not ui.operation_requests


def test_upload_disabled_document_manager_retains_cleanup_and_reprocess(group_management_ui):
    ui = group_management_ui
    ui.set_policy(role="DocumentManager", status="upload_disabled")
    open_documents(ui)
    select_documents(ui, "same-document")
    for label in ("Upload", "Tag", "Edit", "Extract"):
        expect(explorer(ui).get_by_role("button", name=label, exact=True)).to_have_count(0)
    for label in ("Download", "Delete", "Switch to Enhanced"):
        expect(command(ui, label)).to_be_enabled()
    reply = ui.queue_operation(
        "POST", "reprocess_extraction",
        body={"document_ids": ["same-document"], "extraction_mode": "layout"},
        response=queue_result("same-document", extraction_mode="layout"), status=202,
    )
    perform(ui, reply, command(ui, "Switch to Enhanced").click)
    expect(explorer(ui).get_by_role("status").filter(has_text="1 of 1 confirmed")).to_be_visible()
    select_documents(ui, "held-report")
    expect(command(ui, "Delete")).to_be_enabled()
    expect(command(ui, "Download")).to_be_disabled()
    expect(command(ui, "Chat")).to_be_disabled()
    assert_no_personal_controls(ui)


def test_missing_fresh_and_mixed_document_actions_are_not_workspace_authorization(group_management_ui):
    ui = group_management_ui
    ui.record("notes-document").pop("document_actions")
    ui.detail_overrides[("group-a", "same-document")] = changed_record(ui, "same-document", document_actions=[])
    open_documents(ui)
    for identifier in ("notes-document", "same-document"):
        select_documents(ui, identifier)
        for label in ("Tag", "Edit", "Delete", "Extract", "Download", "Switch to Enhanced"):
            expect(command(ui, label)).to_be_disabled()
        expect(document_row(ui, identifier)).to_have_attribute("draggable", "false")
    ui.detail_overrides.clear()
    open_documents(ui)
    select_documents(ui, "shared-report")
    expect(command(ui, "Download")).to_be_enabled()
    for label in ("Tag", "Edit", "Delete", "Extract", "Switch to Enhanced"):
        expect(command(ui, label)).to_be_disabled()
    select_documents(ui, "same-document", "shared-report")
    for label in ("Tag", "Delete", "Extract", "Switch to Enhanced"):
        expect(command(ui, label)).to_be_disabled()
    expect(command(ui, "Download")).to_be_enabled()
    select_documents(ui, "shared-report", "source-denied")
    expect(command(ui, "Download")).to_be_disabled()
    search = ui.page.get_by_role("searchbox", name="Search documents. Press Enter to search immediately.", exact=True)
    with ui.page.expect_response(response_for("GET", "/api/group_documents")) as filtered:
        search.fill("Research brief")
        search.press("Enter")
    filtered.value.finished()
    expect(details_button(ui, "same-document")).to_be_visible()
    assert_no_personal_controls(ui)
    assert not ui.operation_requests


def test_owned_pending_promotion_blocks_chat_actions_and_query_handoff(group_management_ui):
    ui = group_management_ui
    identifier = "pending-promotion"
    title = "Generated report awaiting approval"
    pending = pending_artifact(
        document("group-a", identifier, title, timestamp=ui.now - 7, tags=[]),
        requested_by_user_id="publication-requester", requested_by_display_name="Publishing colleague",
        requested_at="2026-09-22T10:00:00Z",
    )
    pending["document_collaboration_actions"] = ["inspect", "approve_artifact", "reject_artifact"]
    assert "content_screening" not in pending
    ui.documents["group-a"].append(pending)
    open_documents(ui)
    expect(document_row(ui, identifier).get_by_text("Pending approval", exact=True)).to_be_visible()
    expect(checkbox(ui, identifier)).to_be_disabled()
    expect(document_row(ui, identifier)).to_have_attribute("draggable", "false")
    show_details(ui, identifier)
    pane = explorer(ui).get_by_role("complementary")
    for label in ("Chat", "Tag", "Edit", "Extract", "Download", "Delete"):
        expect(pane.get_by_role("button", name=label, exact=True)).to_be_disabled()
    for control in pane.get_by_role("button", name=re.compile(r"^(Switch to|Extract as) ")).all():
        expect(control).to_be_disabled()
    assert_no_personal_controls(ui)
    details_button(ui, identifier).focus()
    ui.page.keyboard.press("Control+a")
    expect(checkbox(ui, "same-document")).to_be_checked()
    expect(checkbox(ui, identifier)).not_to_be_checked()
    clear_selection(ui)

    with (
        ui.page.expect_response(response_for("GET", GROUP_CONTEXT)) as workspace_response,
        ui.page.expect_response(response_for("GET", f"/api/group_documents/{identifier}")) as document_response,
    ):
        ui.open(f"/chat?search_documents=true&doc_scope=group&group_id=group-a&document_ids={identifier}")
    workspace_response.value.finished()
    document_response.value.finished()
    workspace = workspace_response.value.json()
    received = document_response.value.json()
    query = parse_qs(urlsplit(document_response.value.url).query)
    assert workspace_response.value.status == 200 and document_response.value.status == 200
    assert workspace["scope"] == {"kind": "group", "id": "group-a"}
    assert workspace["document_permissions"]["can_view"] and workspace["document_permissions"]["can_chat"]
    assert query == {"group_id": ["group-a"]}
    assert received["group_id"] == "group-a" and received["shared_approval_status"] == "owner"
    assert "content_screening" not in received
    assert received["generated_artifact_promotion_status"] == "pending_approval"
    assert received["status"] == ARTIFACT_AWAITING_APPROVAL_STATUS and received["document_actions"] == []
    refusal = "Could not load the selected context. Choose it again from Documents."
    expect(ui.page.get_by_text(refusal, exact=True)).to_be_visible()
    expect(ui.page.locator("#composer-input")).to_be_visible()
    for name in (title, pending["file_name"], identifier):
        expect(ui.page.get_by_role("button", name=f"Remove {name}", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name=re.compile(r"^(Approve|Reject)(?:\s|$)"))).to_have_count(0)

    with ui.page.expect_response(response_for("GET", "/api/group_documents/same-document")) as available:
        ui.open("/chat?search_documents=true&doc_scope=group&group_id=group-a&document_ids=same-document")
    available.value.finished()
    expect(ui.page.get_by_role("button", name="Remove Research brief", exact=True)).to_be_visible()
    expect(ui.page.get_by_text(refusal, exact=True)).to_have_count(0)
    assert not ui.operation_requests
    assert not any(entry.path in ("/api/create_conversation", "/api/chat/stream") for entry in ui.writes)


def test_owned_held_cleanup_selection_never_enables_chat_or_inflight_deletion(group_management_ui):
    ui = group_management_ui
    cleanup_states = ("scan_error", "incomplete", "rejected", "deleting")
    inflight_states = ("pending_scan", "extracting", "scanning", "remediating", "publishing")
    for state in (*cleanup_states, *inflight_states):
        record = restricted(document(
            "group-a", f"held-{state}", "Never expose held metadata", timestamp=ui.now - 20,
            content_screening={"state": state, "available": False, "finding_count": 0},
        ))
        record["document_actions"] = ["delete"] if state in cleanup_states else []
        ui.documents["group-a"].append(record)
    open_documents(ui)
    for state in cleanup_states:
        expect(checkbox(ui, f"held-{state}")).to_be_enabled()
    for identifier in ("pending-report", "held-share", *(f"held-{state}" for state in inflight_states)):
        expect(checkbox(ui, identifier)).to_be_disabled()
    select_documents(ui, "held-report")
    expect(command(ui, "Delete")).to_be_enabled()
    for label in ("Chat", "Tag", "Extract", "Download"):
        expect(command(ui, label)).to_be_disabled()
    # Editing is a details-pane action, and a held source's details offer only its cleanup.
    expect(ui.page.get_by_role("complementary").get_by_role("button", name="Edit", exact=True)).to_have_count(0)
    expect(ui.page.get_by_text("Restricted held title", exact=True)).to_have_count(0)
    command(ui, "Delete").click()
    dialog = ui.page.get_by_role("dialog", name="Delete documents", exact=True)
    dialog.get_by_label(re.compile(r"^Delete every version")).uncheck()
    reply = ui.queue_operation(
        "DELETE", "held-report", query={"delete_mode": ["current_only"]},
        response=delete_result(
            "held-report", deleted_mode="current_only",
            deleted_document_ids=["held-report"], promoted_document_id=None,
        ),
        remove_ids=["held-report"],
    )
    perform(ui, reply, dialog.get_by_role("button", name="Delete", exact=True).click)
    expect(dialog).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Details for held-report.pdf", exact=True)).to_have_count(0)
    assert not any(entry.path in ("/api/create_conversation", "/api/chat/stream") for entry in ui.requests)


def test_held_details_offer_only_the_advertised_cleanup(group_management_ui):
    """A held source's details never offer chat, download, tagging, editing, analysis or sharing.

    The owned held-report advertises deletion, so its details keep Delete; the incoming held-share
    advertises nothing, so its details offer no action at all.
    """
    ui = group_management_ui
    open_documents(ui)
    details = ui.page.get_by_role("complementary")
    notice = "Held sources cannot be selected for chat, analyzed, shared, or downloaded here."
    for identifier, deletable in (("held-report", True), ("held-share", False)):
        show_details(ui, identifier)
        expect(details.get_by_text(notice, exact=False)).to_be_visible()
        for label in ("Chat", "Download", "Tag", "Edit", "Extract", "Share"):
            expect(details.get_by_role("button", name=label, exact=True)).to_have_count(0)
        delete = details.get_by_role("button", name="Delete", exact=True)
        if deletable:
            expect(delete).to_be_enabled()
        else:
            expect(delete).to_have_count(0)
    expect(ui.page.get_by_text("Restricted held title", exact=True)).to_have_count(0)
    assert not ui.operation_requests


def test_upload_repeated_file_parts_partial_acceptance_and_real_polling(group_management_ui):
    ui = group_management_ui
    ui.documents["group-a"] = []
    ui.page.clock.install()
    ui.open("/groups/group-a/documents")
    expect(ui.page.get_by_text("No documents yet", exact=True)).to_be_visible()
    files = [
        {"name": "accepted.txt", "mimeType": "text/plain", "buffer": b"Accepted research source.\n"},
        {"name": "refused.txt", "mimeType": "text/plain", "buffer": b"Rejected research source.\n"},
    ]
    uploaded = document(
        "group-a", "uploaded-document", "Accepted upload", timestamp=ui.now + 1,
        file_name="accepted.txt", tags=[], status="Processing", percentage_complete=25,
        document_actions=[],
    )
    refusal = upload_refusal("refused.txt")
    reply = ui.queue_operation(
        "POST", "upload", files=files, status=207,
        response=upload_result(["uploaded-document"], ["accepted.txt"], [refusal]),
        records=[uploaded],
    )
    ui.defer_next("POST", reply.path)
    with ui.page.expect_file_chooser() as chooser:
        ui.page.get_by_role("button", name="Upload a document", exact=True).click()
    with ui.page.expect_request(lambda request: request.method == "POST" and urlsplit(request.url).path == reply.path):
        chooser.value.set_files(files)
    expect(ui.page.get_by_role("progressbar", name="Uploading files", exact=True)).to_be_visible()
    expect(command(ui, "Upload")).to_be_disabled()
    expect(ui.page.get_by_role("combobox", name="Group workspace", exact=True)).to_be_disabled()
    assert len(ui.pending_responses) == 1
    perform(ui, reply, ui.release_responses)
    expect(ui.page.get_by_role("alert").filter(has_text=refusal)).to_be_visible()
    expect(ui.page.get_by_text(
        "Accepted 1 of 2 files. Processing is queued, not complete.", exact=True,
    ).first).to_be_visible()
    expect(details_button(ui, "uploaded-document")).to_be_visible()
    assert ui.multipart_uploads == [(reply.path, files)]
    with ui.page.expect_response(response_for("GET", "/api/group_documents/uploaded-document")) as initial_detail:
        details_button(ui, "uploaded-document").click()
    initial_detail.value.finished()
    expect(ui.page.get_by_role("button", name="Refresh document details", exact=True)).to_be_enabled()
    ui.detail_overrides[("group-a", "uploaded-document")] = {
        **uploaded, "title": "Processed upload", "status": "Processing complete",
        "percentage_complete": 100, "document_actions": list(DOCUMENT_ACTIONS),
    }
    with ui.page.expect_response(response_for("GET", "/api/group_documents/uploaded-document")) as polled:
        ui.page.clock.fast_forward(5000)
    polled.value.finished()
    expect(ui.page.get_by_role("button", name="Details for Processed upload", exact=True)).to_be_visible()
    expect(command(ui, "Edit")).to_be_enabled()
    assert len(ui.operation_requests) == 1


def test_metadata_changed_field_patch_retains_failed_draft_and_immutable_group(group_management_ui):
    ui = group_management_ui
    other_group = copy.deepcopy(ui.documents["group-b"])
    original = copy.deepcopy(ui.record("same-document"))
    open_documents(ui)
    dialog = edit_metadata(ui)
    expect(dialog.get_by_role("button", name="Save", exact=True)).to_be_disabled()
    dialog.get_by_label(re.compile(r"^Title")).fill("Updated research brief")
    dialog.get_by_label("Keywords", exact=True).fill("baseline, reviewed")
    body = {"title": "Updated research brief", "keywords": ["baseline", "reviewed"]}
    failed = ui.queue_operation(
        "PATCH", "same-document", body=body, status=500, response=propagation_incomplete("same-document"),
    )
    perform(ui, failed, dialog.get_by_role("button", name="Save", exact=True).click)
    expect(dialog.get_by_role("alert")).to_contain_text(re.compile(r"propagation|repair", re.IGNORECASE))
    expect(dialog.get_by_label(re.compile(r"^Title"))).to_have_value("Updated research brief")
    expect(dialog.get_by_label("Keywords", exact=True)).to_have_value("baseline, reviewed")
    expect(ui.page.get_by_text("Metadata saved.", exact=True)).to_have_count(0)
    assert ui.record("same-document") == original
    saved = ui.queue_operation(
        "PATCH", "same-document", body=body, response=metadata_result("same-document", body),
        records=[{**original, **body}],
    )
    ui.defer_next("PATCH", saved.path)
    with ui.page.expect_request(lambda request: request.method == "PATCH" and urlsplit(request.url).path == saved.path):
        dialog.get_by_role("button", name="Save", exact=True).click()
    expect(dialog.get_by_role("button", name="Cancel", exact=True)).to_be_disabled()
    ui.active_group = "group-b"
    perform(ui, saved, ui.release_responses)
    expect(dialog).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Details for Updated research brief", exact=True)).to_be_visible()
    assert ui.active_group == "group-b" and ui.documents["group-b"] == other_group
    assert [entry.body for entry in ui.operation_requests] == [body, body]
    assert not any(entry.path == "/api/groups/setActive" for entry in ui.writes)
    assert ui.record("same-document")["authors"] == original["authors"]
    assert ui.record("same-document")["abstract"] == original["abstract"]


def test_metadata_propagation_failure_shows_the_servers_sentence(group_management_ui):
    """A coded failure carries its machine code in `error` and its sentence in `message`; the
    dialog shows the sentence, never the code."""
    ui = group_management_ui
    open_documents(ui)
    dialog = edit_metadata(ui)
    dialog.get_by_label(re.compile(r"^Title")).fill("Updated research brief")
    failed = ui.queue_operation(
        "PATCH", "same-document", body={"title": "Updated research brief"}, status=500,
        response=propagation_incomplete("same-document"),
    )
    perform(ui, failed, dialog.get_by_role("button", name="Save", exact=True).click)
    expect(dialog.get_by_role("alert")).to_contain_text(PROPAGATION_INCOMPLETE_MESSAGE)
    expect(dialog.get_by_role("alert")).not_to_contain_text("document_propagation_incomplete")


def test_queued_metadata_acknowledgement_keeps_saved_content_held_for_screening(group_management_ui):
    ui = group_management_ui
    open_documents(ui)
    dialog = edit_metadata(ui)
    body = {"abstract": "New unscreened abstract that must not be released yet."}
    dialog.get_by_label(re.compile(r"^Abstract")).fill(body["abstract"])
    held = restricted(changed_record(
        ui, "same-document", **body,
        content_screening={"state": "pending_review", "available": False, "finding_count": 1},
    ))
    held["document_actions"] = ["delete"]
    reply = ui.queue_operation(
        "PATCH", "same-document", body=body, status=202,
        response=metadata_result("same-document", body, queued=True), records=[held],
    )
    perform(ui, reply, dialog.get_by_role("button", name="Save", exact=True).click)
    expect(dialog).to_have_count(0)
    expect(ui.page.get_by_text(
        "Metadata saved. Screening is queued; the document remains unavailable until released.", exact=True,
    )).to_be_visible()
    expect(ui.page.get_by_text("Metadata saved.", exact=True)).to_have_count(0)
    expect(details_button(ui, "same-document")).to_be_visible()
    expect(ui.page.get_by_text(body["abstract"], exact=True)).to_have_count(0)
    select_documents(ui, "same-document")
    for label in ("Chat", "Tag", "Extract", "Download"):
        expect(command(ui, label)).to_be_disabled()
    expect(ui.page.get_by_role("complementary").get_by_role("button", name="Edit", exact=True)).to_have_count(0)
    expect(command(ui, "Delete")).to_be_enabled()
    assert len(ui.operation_requests) == 1


def test_malformed_metadata_success_never_discards_the_draft(group_management_ui):
    ui = group_management_ui
    original = copy.deepcopy(ui.record("same-document"))
    body = {"title": "Unconfirmed metadata draft", "keywords": ["baseline", "unconfirmed"]}
    receipt = metadata_result("same-document", body)
    cases = (
        ("message-only", {"response": {"message": METADATA_UPDATED_MESSAGE}}),
        ("raw-record", {"response": {**original, **body}}),
        ("wrong-document", {"response": {**receipt, "document_id": "notes-document"}}),
        ("wrong-group", {"response": {**receipt, "group_id": "group-b"}}),
        ("missing-field", {"response": {**receipt, "updated_fields": ["title"]}}),
        ("extra-field", {"response": {**receipt, "updated_fields": ["title", "keywords", "abstract"]}}),
        ("duplicate-field", {"response": {**receipt, "updated_fields": ["title", "title"]}}),
        ("queued-as-200", {"response": {**receipt, "status": "queued"}}),
        ("updated-as-202", {"response": receipt, "status": 202}),
        ("empty-error-207", {"response": {**receipt, "errors": []}, "status": 207}),
        ("html", {"response": b"<html><body>Sign in to continue.</body></html>", "content_type": "text/html"}),
    )
    open_documents(ui)
    for name, outcome in cases:
        clear_selection(ui)
        dialog = edit_metadata(ui)
        dialog.get_by_label(re.compile(r"^Title")).fill(body["title"])
        dialog.get_by_label("Keywords", exact=True).fill("baseline, unconfirmed")
        reply = ui.queue_operation("PATCH", "same-document", body=body, **outcome)
        perform(ui, reply, dialog.get_by_role("button", name="Save", exact=True).click)
        expect(dialog, f"The {name} receipt must not discard the metadata draft.").to_be_visible()
        expect(dialog.get_by_role("alert")).to_contain_text("did not confirm the metadata change")
        expect(dialog.get_by_label(re.compile(r"^Title"))).to_have_value(body["title"])
        expect(dialog.get_by_label("Keywords", exact=True)).to_have_value("baseline, unconfirmed")
        expect(ui.page.get_by_text("Metadata saved.", exact=True)).to_have_count(0)
        assert ui.record("same-document") == original, name
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        expect(dialog).to_have_count(0)
    assert len(ui.operation_requests) == len(cases)


def test_bulk_tag_partial_failure_keeps_failed_draft_and_rejects_wrong_scope_drop(group_management_ui):
    ui = group_management_ui
    open_documents(ui)
    drop_on_tag(
        ui, "review",
        {"scopeKey": json.dumps([OWNER_ID, "group", "group-b"], separators=(",", ":")),
         "documentIds": ["same-document"]},
    )
    expect(ui.page.get_by_text(
        "Drag documents from this workspace only. No tags were changed.", exact=True,
    )).to_be_visible()
    assert not ui.operation_requests
    select_documents(ui, "same-document", "notes-document")
    command(ui, "Tag").click()
    dialog = ui.page.get_by_role("dialog", name="Tag 2 documents", exact=True)
    dialog.get_by_role("checkbox", name=re.compile(r"^review\b")).check()
    tagged = changed_record(ui, "same-document", tags=["finance", "team", "review"])
    partial = ui.queue_operation(
        "POST", "bulk-tag",
        body={"document_ids": ["same-document", "notes-document"], "action": "add_tags", "tags": ["review"]},
        status=207,
        response=bulk_tag_result(
            [{"document_id": "same-document", "tags": tagged["tags"]}],
            [batch_error("notes-document", DOCUMENT_CHANGED_ERROR)],
        ),
        records=[tagged],
    )
    perform(ui, partial, dialog.get_by_role("button", name="Apply", exact=True).click)
    retry_dialog = ui.page.get_by_role("dialog", name="Tag Field notes", exact=True)
    expect(retry_dialog).to_be_visible()
    expect(retry_dialog.get_by_role("alert")).to_contain_text(DOCUMENT_CHANGED_ERROR)
    expect(retry_dialog.get_by_role("checkbox", name=re.compile(r"^review\b"))).to_be_checked()
    expect(checkbox(ui, "same-document")).not_to_be_checked()
    expect(checkbox(ui, "notes-document")).to_be_checked()
    expect(document_row(ui, "same-document").get_by_text("review", exact=True)).to_be_visible()
    notes = changed_record(ui, "notes-document", tags=["team", "legacy/review", "review"])
    retry = ui.queue_operation(
        "POST", "bulk-tag",
        body={"document_ids": ["notes-document"], "action": "add_tags", "tags": ["review"]},
        response=bulk_tag_result([{"document_id": "notes-document", "tags": notes["tags"]}]),
        records=[notes],
    )
    perform(ui, retry, retry_dialog.get_by_role("button", name="Apply", exact=True).click)
    expect(retry_dialog).to_have_count(0)
    expect(document_row(ui, "notes-document").get_by_text("review", exact=True)).to_be_visible()
    untagged = changed_record(ui, "notes-document", tags=["team", "legacy/review"])
    remove = ui.queue_operation(
        "POST", "bulk-tag",
        body={"document_ids": ["notes-document"], "action": "remove_tags", "tags": ["review"]},
        response=bulk_tag_result([{"document_id": "notes-document", "tags": untagged["tags"]}]),
        records=[untagged],
    )
    perform(ui, remove, ui.page.get_by_role("button", name="Remove tag review", exact=True).click)
    expect(document_row(ui, "notes-document").get_by_text("review", exact=True)).to_have_count(0)
    expect(explorer(ui)).to_be_enabled()
    dragged = document_row(ui, "notes-document").evaluate("""element => {
        const transfer = new DataTransfer();
        element.dispatchEvent(new DragEvent('dragstart', {
            bubbles: true, cancelable: true, dataTransfer: transfer,
        }));
        return transfer.getData('application/x-simplechat-documents');
    }""")
    payload = json.loads(dragged)
    assert payload == {
        "scopeKey": json.dumps([OWNER_ID, "group", "group-a"], separators=(",", ":")),
        "documentIds": ["notes-document"],
    }
    tagged_notes = changed_record(ui, "notes-document", tags=["team", "legacy/review", "finance"])
    drop = ui.queue_operation(
        "POST", "bulk-tag",
        body={"document_ids": ["notes-document"], "action": "add_tags", "tags": ["finance"]},
        response=bulk_tag_result([{"document_id": "notes-document", "tags": tagged_notes["tags"]}]),
        records=[tagged_notes],
    )
    perform(ui, drop, lambda: drop_on_tag(ui, "finance", payload))
    expect(document_row(ui, "notes-document").get_by_text("finance", exact=True)).to_be_visible()
    assert len(ui.operation_requests) == 4


def test_malformed_bulk_tag_success_keeps_every_failed_item_selected(group_management_ui):
    ui = group_management_ui
    original = copy.deepcopy(ui.documents["group-a"])
    open_documents(ui)
    select_documents(ui, "same-document", "notes-document")
    command(ui, "Tag").click()
    dialog = ui.page.get_by_role("dialog", name="Tag 2 documents", exact=True)
    dialog.get_by_role("checkbox", name=re.compile(r"^review\b")).check()
    body = {
        "document_ids": ["same-document", "notes-document"],
        "action": "add_tags", "tags": ["review"],
    }
    updated = [
        changed_record(ui, identifier, tags=[*ui.record(identifier)["tags"], "review"])
        for identifier in body["document_ids"]
    ]
    receipt = bulk_tag_result([{"document_id": record["id"], "tags": record["tags"]} for record in updated])
    for name, outcome, error_text in (
        ("html", {
            "response": b"<html><body>No operation receipt.</body></html>", "content_type": "text/html",
        }, "complete operation receipt"),
        ("empty-error-207", {"response": receipt, "status": 207}, "complete operation receipt"),
        ("tag-only-error-in-document-batch", {
            "response": {**receipt, "errors": [tag_vocabulary_conflict()]}, "status": 207,
        }, "invalid operation result"),
    ):
        reply = ui.queue_operation("POST", "bulk-tag", body=body, **outcome)
        perform(ui, reply, dialog.get_by_role("button", name="Apply", exact=True).click)
        expect(dialog, f"The {name} receipt must keep the tag draft open.").to_be_visible()
        expect(dialog.get_by_role("alert")).to_contain_text(error_text)
        expect(dialog.get_by_role("checkbox", name=re.compile(r"^review\b"))).to_be_checked()
        for identifier in body["document_ids"]:
            expect(checkbox(ui, identifier)).to_be_checked()
        expect(ui.page.get_by_text("Updating document tags: 2 of 2 confirmed.", exact=True)).to_have_count(0)
        assert ui.documents["group-a"] == original, name
    retry = ui.queue_operation("POST", "bulk-tag", body=body, response=receipt, records=updated)
    perform(ui, retry, dialog.get_by_role("button", name="Apply", exact=True).click)
    expect(dialog).to_have_count(0)
    for identifier in body["document_ids"]:
        expect(document_row(ui, identifier).get_by_text("review", exact=True)).to_be_visible()
    assert len(ui.operation_requests) == 4


def test_revision_delete_distinguishes_requested_ids_from_removed_siblings(group_management_ui):
    ui = group_management_ui
    old_notes = changed_record(
        ui, "notes-document", id="previous-notes", document_id="previous-notes",
        title="Earlier field notes", version=2, is_current_version=False,
    )
    ui.versions[("group-a", "notes-document")] = [copy.deepcopy(ui.record("notes-document")), old_notes]
    open_documents(ui)
    for identifier, all_versions in (("same-document", False), ("notes-document", True)):
        select_documents(ui, identifier)
        command(ui, "Delete").click()
        dialog = ui.page.get_by_role("dialog", name="Delete documents", exact=True)
        expect(dialog).to_contain_text("Research group")
        version_choice = dialog.get_by_label(re.compile(r"^Delete every version"))
        version_choice.set_checked(all_versions)
        mode = "all_versions" if all_versions else "current_only"
        history = ui.versions[("group-a", identifier)]
        promoted = {**copy.deepcopy(history[1]), "is_current_version": True, "document_actions": list(DOCUMENT_ACTIONS)}
        removed = [identifier, history[1]["id"]] if all_versions else [identifier]
        reply = ui.queue_operation(
            "DELETE", identifier, query={"delete_mode": [mode]},
            response=delete_result(
                identifier, deleted_mode=mode, deleted_document_ids=removed,
                promoted_document_id=None if all_versions else promoted["id"],
            ),
            remove_ids=removed, records=[] if all_versions else [promoted],
            versions={} if all_versions else {promoted["id"]: [promoted]},
        )
        previous_name = ui.record(identifier)["title"]
        perform(ui, reply, dialog.get_by_role("button", name="Delete", exact=True).click)
        expect(dialog).to_have_count(0)
        expect(ui.page.get_by_role("button", name=f"Details for {previous_name}", exact=True)).to_have_count(0)
        if all_versions:
            expect(ui.page.get_by_role("button", name="Details for Earlier field notes", exact=True)).to_have_count(0)
        else:
            expect(details_button(ui, "previous-version")).to_be_visible()
        expect(explorer(ui).get_by_role("alert")).to_have_count(0)
    assert len(ui.operation_requests) == 2


def test_single_delete_rejects_message_only_and_incomplete_success_receipts(group_management_ui):
    ui = group_management_ui
    original = copy.deepcopy(ui.record("same-document"))
    receipt = delete_result(
        "same-document", deleted_mode="all_versions",
        deleted_document_ids=["same-document", "previous-version"], promoted_document_id=None,
    )
    cases = (
        ("message-only", {"response": {"message": DOCUMENT_DELETED_MESSAGE}}),
        ("missing-revision-details", {"response": {**delete_result("same-document"), "message": DOCUMENT_DELETED_MESSAGE}}),
        ("wrong-requested-id", {"response": {**receipt, "deleted": [{"document_id": "previous-version"}]}}),
        ("wrong-deleted-count", {"response": {**receipt, "deleted_count": 2}}),
        ("wrong-error-count", {"response": {**receipt, "error_count": 1}}),
        ("empty-error-207", {"response": receipt, "status": 207}),
        ("html", {"response": b"<html><body>Delete not confirmed.</body></html>", "content_type": "text/html"}),
    )
    open_documents(ui)
    for name, outcome in cases:
        select_documents(ui, "same-document")
        command(ui, "Delete").click()
        dialog = ui.page.get_by_role("dialog", name="Delete documents", exact=True)
        reply = ui.queue_operation(
            "DELETE", "same-document", query={"delete_mode": ["all_versions"]}, **outcome,
        )
        perform(ui, reply, dialog.get_by_role("button", name="Delete", exact=True).click)
        failure = ui.page.get_by_role("dialog", name="Some documents need confirmation", exact=True)
        expect(failure, f"The {name} receipt must not confirm a deletion.").to_be_visible()
        expect(failure).to_contain_text("Research brief")
        expect(checkbox(ui, "same-document")).to_be_checked()
        expect(ui.page.get_by_text("Deleting documents: 1 of 1 confirmed.", exact=True)).to_have_count(0)
        assert ui.record("same-document") == original, name
        failure.get_by_role("button", name="Cancel", exact=True).click()
        expect(failure).to_have_count(0)
    assert len(ui.operation_requests) == len(cases)


def test_single_sync_guard_preserves_advertised_actions_without_force_aliases(group_management_ui):
    ui = group_management_ui
    open_documents(ui)
    for identifier, action in (("same-document", "ignore_remote"), ("notes-document", "delete_only")):
        select_documents(ui, identifier)
        command(ui, "Delete").click()
        dialog = ui.page.get_by_role("dialog", name="Delete documents", exact=True)
        guarded = ui.queue_operation(
            "DELETE", identifier, query={"delete_mode": ["all_versions"]}, status=409,
            response=synced_delete_guard(identifier, {
                "source_id": "source-1", "source_name": "Research library",
                "remote_path": "/library/teams/research.pdf", "relative_path": "teams/research.pdf",
            }),
        )
        perform(ui, guarded, dialog.get_by_role("button", name="Delete", exact=True).click)
        confirmation = ui.page.get_by_role("dialog", name="Some documents need confirmation", exact=True)
        expect(confirmation).to_contain_text("Research library")
        expect(confirmation).to_contain_text("teams/research.pdf")
        retry_button = confirmation.get_by_role("button", name="Retry delete", exact=True)
        expect(retry_button).to_be_disabled()
        actions = confirmation.get_by_label("Synced-file action", exact=True)
        expect(actions.get_by_role("option")).to_have_text([
            "Choose the advertised source action", *(option["label"] for option in SYNCED_DELETE_OPTIONS),
        ])
        actions.select_option(action)
        revisions = ui.versions.get(("group-a", identifier), [ui.record(identifier)])
        deleted_ids = [record["id"] for record in revisions]
        retry = ui.queue_operation(
            "DELETE", identifier,
            query={"delete_mode": ["all_versions"], "file_sync_delete_action": [action]},
            response=delete_result(
                identifier, deleted_mode="all_versions",
                deleted_document_ids=deleted_ids, promoted_document_id=None,
            ),
            remove_ids=deleted_ids, versions={identifier: []},
        )
        perform(ui, retry, retry_button.click)
        expect(confirmation).to_have_count(0)
    assert len(ui.operation_requests) == 4


def test_partial_bulk_delete_retains_conversation_guard_and_retries_only_failed_id(group_management_ui):
    ui = group_management_ui
    open_documents(ui)
    select_documents(ui, "same-document", "notes-document")
    command(ui, "Delete").click()
    dialog = ui.page.get_by_role("dialog", name="Delete documents", exact=True)
    expect(dialog).to_contain_text("Research brief")
    expect(dialog).to_contain_text("Field notes")
    guard = conversation_delete_guard(
        "notes-document", "existing-workspace-chat", title="Planning review", file_name="notes-document.pdf",
    )
    partial = ui.queue_operation(
        "POST", "bulk-delete",
        body={
            "document_ids": ["same-document", "notes-document"], "delete_mode": "all_versions",
            "conversation_linked_delete_confirmed": False,
        },
        response=delete_result("same-document", errors=[guard]), status=207,
        remove_ids=["same-document"],
    )
    perform(ui, partial, dialog.get_by_role("button", name="Delete", exact=True).click)
    confirmation = ui.page.get_by_role("dialog", name="Some documents need confirmation", exact=True)
    expect(confirmation).to_contain_text("Field notes")
    expect(confirmation).to_contain_text(CONVERSATION_DELETE_MESSAGE)
    expect(confirmation).not_to_contain_text("Research brief")
    expect(checkbox(ui, "notes-document")).to_be_checked()
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_have_count(0)
    retry_button = confirmation.get_by_role("button", name="Retry delete", exact=True)
    expect(retry_button).to_be_disabled()
    confirmation.get_by_role("checkbox", name=re.compile(r"^Delete the conversation-linked files")).check()
    retry = ui.queue_operation(
        "DELETE", "notes-document",
        query={"delete_mode": ["all_versions"], "conversation_linked_delete_confirmed": ["true"]},
        response=delete_result(
            "notes-document", deleted_mode="all_versions",
            deleted_document_ids=["notes-document"], promoted_document_id=None,
        ),
        remove_ids=["notes-document"],
    )
    perform(ui, retry, retry_button.click)
    expect(confirmation).to_have_count(0)
    expect(explorer(ui).locator('input[type="checkbox"]:checked')).to_have_count(0)
    assert ui.operation_requests[-1].path == operation_path("notes-document")
    assert not any("force" in entry.query or "keep_source" in str(entry.body) for entry in ui.operation_requests)


def test_conversation_guard_names_the_linked_conversation(group_management_ui):
    """The confirmation names the conversation a file was uploaded in, and opens it natively on
    the V2 chat page, never at the classic url the server sends; the link opens in a new tab,
    keeping the confirmation."""
    ui = group_management_ui
    open_documents(ui)
    select_documents(ui, "notes-document")
    command(ui, "Delete").click()
    dialog = ui.page.get_by_role("dialog", name="Delete documents", exact=True)
    guarded = ui.queue_operation(
        "DELETE", "notes-document", query={"delete_mode": ["all_versions"]}, status=409,
        response=conversation_delete_guard(
            "notes-document", "existing-workspace-chat", title="Planning review", file_name="notes-document.pdf",
        ),
    )
    perform(ui, guarded, dialog.get_by_role("button", name="Delete", exact=True).click)
    confirmation = ui.page.get_by_role("dialog", name="Some documents need confirmation", exact=True)
    expect(confirmation).to_contain_text(CONVERSATION_DELETE_MESSAGE)
    expect(confirmation).to_contain_text("Conversation: Planning review")
    link = confirmation.get_by_role("link", name=re.compile(r"^Planning review"))
    expect(link).to_have_attribute("href", "/v2/chat?conversationId=existing-workspace-chat")
    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_have_attribute("rel", "noopener noreferrer")


def test_conversation_guard_links_only_the_native_chat_and_renders_text(group_management_ui):
    """Robustness: deliberately malformed guards. Without a conversation id, an absolute,
    protocol-relative, backslash or scripted url never becomes a link, and a url that names no
    conversation shows the title only; with an id, the link is the native chat page, never the
    url. A title is always text, never markup."""
    ui = group_management_ui
    title = '<img src=x onerror="window.__guardInjected = true"> Planning review'
    cases = (
        (None, "https://evil.example/chats?conversation_id=stolen", None),
        (None, "//evil.example/chats?conversation_id=stolen", None),
        (None, "/\\evil.example/chats?conversation_id=stolen", None),
        # xss-check: ignore -- deliberately malformed server urls this test proves are never rendered as links.
        (None, "javascript:alert(1)//?conversation_id=stolen", None),
        (None, "/chats", None),
        (None, "/chats?conversation_id=from-the-url", "/v2/chat?conversationId=from-the-url"),
        ("existing-workspace-chat", "javascript:alert(1)", "/v2/chat?conversationId=existing-workspace-chat"),
    )
    open_documents(ui)
    for conversation_id, url, href in cases:
        select_documents(ui, "notes-document")
        command(ui, "Delete").click()
        dialog = ui.page.get_by_role("dialog", name="Delete documents", exact=True)
        guard = conversation_delete_guard(
            "notes-document", conversation_id or "unused", title=title, file_name="notes-document.pdf",
        )
        if conversation_id is None:
            del guard["conversation"]["id"]
        guard["conversation"]["url"] = url
        guarded = ui.queue_operation(
            "DELETE", "notes-document", query={"delete_mode": ["all_versions"]}, status=409, response=guard,
        )
        perform(ui, guarded, dialog.get_by_role("button", name="Delete", exact=True).click)
        confirmation = ui.page.get_by_role("dialog", name="Some documents need confirmation", exact=True)
        expect(confirmation, f"The {url!r} guard must still name its conversation.").to_contain_text(f"Conversation: {title}")
        links = confirmation.get_by_role("link")
        if href is None:
            expect(links, f"The {url!r} guard must not become a link.").to_have_count(0)
        else:
            expect(links).to_have_count(1)
            expect(links).to_have_attribute("href", href)
        expect(confirmation.locator("img")).to_have_count(0)
        confirmation.get_by_role("button", name="Cancel", exact=True).click()
        expect(confirmation).to_have_count(0)
    assert ui.page.evaluate("() => window.__guardInjected === undefined")
    assert len(ui.operation_requests) == len(cases)


def test_approved_source_single_and_batch_downloads_save_complete_bytes(group_management_ui, tmp_path):
    ui = group_management_ui
    ui.record("same-document")["file_name"] = "research.txt"
    ui.record("shared-report")["file_name"] = "published.txt"
    owned_bytes = b"Recipient-owned research source.\n"
    source_bytes = b"Publishing-group approved source.\nNot a same-name recipient blob.\n"
    open_documents(ui)
    select_documents(ui, "shared-report")
    single = ui.queue_operation(
        "GET", "shared-report/download", response=source_bytes, content_type="text/plain",
        headers=attachment("published.txt"),
    )
    with ui.page.expect_download() as download:
        perform(ui, single, command(ui, "Download").click)
    assert download.value.suggested_filename == "published.txt"
    saved_source = tmp_path / "one.txt"
    download.value.save_as(saved_source)
    actual_source = saved_source.read_bytes()
    failure = download.value.failure()
    assert failure is None and actual_source == source_bytes and actual_source != owned_bytes
    select_documents(ui, "same-document", "shared-report")
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_STORED) as archive:
        for name, content in (("research.txt", owned_bytes), ("published.txt", source_bytes)):
            archive.writestr(ZipInfo(name, date_time=(2026, 9, 1, 0, 0, 0)), content)
    archive_bytes = stream.getvalue()
    batch = ui.queue_operation(
        "POST", "download", body={"document_ids": ["same-document", "shared-report"]},
        response=archive_bytes, content_type="application/zip", headers=attachment(GROUP_ARCHIVE_NAME),
    )
    with ui.page.expect_download() as download:
        perform(ui, batch, command(ui, "Download").click)
    saved_archive = tmp_path / "set.zip"
    download.value.save_as(saved_archive)
    actual_archive = saved_archive.read_bytes()
    assert actual_archive == archive_bytes
    with ZipFile(io.BytesIO(actual_archive)) as archive:
        names = archive.namelist()
        owned_file = archive.read("research.txt")
        shared_file = archive.read("published.txt")
    assert names == ["research.txt", "published.txt"]
    assert owned_file == owned_bytes and shared_file == source_bytes
    assert ui.record("shared-report")["group_id"] == "origin"
    assert "origin" not in ui.groups


def test_batch_download_is_saved_under_the_servers_archive_name(group_management_ui):
    """A multi-document download is saved under the archive name the server's attachment gives."""
    ui = group_management_ui
    open_documents(ui)
    select_documents(ui, "same-document", "shared-report")
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_STORED) as archive:
        archive.writestr(ZipInfo("research.txt", date_time=(2026, 9, 1, 0, 0, 0)), b"Research source.\n")
    batch = ui.queue_operation(
        "POST", "download", body={"document_ids": ["same-document", "shared-report"]},
        response=stream.getvalue(), content_type="application/zip", headers=attachment(GROUP_ARCHIVE_NAME),
    )
    with ui.page.expect_download() as download:
        perform(ui, batch, command(ui, "Download").click)
    assert download.value.suggested_filename == GROUP_ARCHIVE_NAME


def test_archives_take_a_bare_server_name_and_singles_keep_their_own(group_management_ui):
    """Robustness: deliberately unusual attachment headers. An archive is saved under the server's
    name, `filename*` preferred and any path dropped, or documents.zip when the name is empty or
    only a path. A single download keeps the document's own name, whatever lossy name (the
    server's secure_filename) its header carries."""
    ui = group_management_ui
    ui.record("shared-report")["file_name"] = "Published report (final).pdf"
    ui.record("same-document")["file_name"] = "报告.pdf"
    open_documents(ui)
    both = ("same-document", "shared-report")
    cases = (
        (both, "attachment; filename*=UTF-8''r%C3%A9sum%C3%A9%20set.zip; filename=\"resume_set.zip\"", "résumé set.zip"),
        (both, 'attachment; filename="../../reports/evil.zip"', "evil.zip"),
        (both, 'attachment; filename="reports/"', "documents.zip"),
        (both, 'attachment; filename=""', "documents.zip"),
        (("shared-report",), 'attachment; filename="Published_report_final.pdf"', "Published report (final).pdf"),
        (("same-document",), 'attachment; filename="pdf"', "报告.pdf"),
        (("shared-report",), "attachment", "Published report (final).pdf"),
    )
    for identifiers, disposition, expected in cases:
        select_documents(ui, *identifiers)
        reply = ui.queue_operation(
            "GET" if len(identifiers) == 1 else "POST",
            f"{identifiers[0]}/download" if len(identifiers) == 1 else "download",
            body=None if len(identifiers) == 1 else {"document_ids": list(identifiers)},
            response=b"file bytes", content_type="application/octet-stream",
            headers={"Content-Disposition": disposition},
        )
        with ui.page.expect_download() as download:
            perform(ui, reply, command(ui, "Download").click)
        assert download.value.suggested_filename == expected, disposition
    assert len(ui.operation_requests) == len(cases)


def test_final_html_json_and_error_download_bodies_never_become_files(group_management_ui):
    ui = group_management_ui
    downloads = []
    ui.page.on("download", lambda download: downloads.append(download))
    cases = (
        (["shared-report"], {"status": 403, "response": {"error": "The source owner no longer permits downloading."}}),
        (["same-document", "shared-report"], {"status": 403, "response": {"error": "The entire archive was refused."}}),
        (["shared-report"], {
            "status": 200, "response": b"<html><body>Sign in again.</body></html>", "content_type": "text/html",
        }),
        (["same-document", "shared-report"], {
            "status": 207, "response": {"errors": [{"document_id": "shared-report", "error": "source_unavailable"}]},
        }),
    )
    open_documents(ui)
    for identifiers, case in cases:
        select_documents(ui, *identifiers)
        reply = ui.queue_operation(
            "GET" if len(identifiers) == 1 else "POST",
            "shared-report/download" if len(identifiers) == 1 else "download",
            body=None if len(identifiers) == 1 else {"document_ids": identifiers},
            **case,
        )
        response = perform(ui, reply, command(ui, "Download").click)
        assert "content-disposition" not in response.headers
        if reply.content_type:
            assert response.headers["content-type"].startswith(reply.content_type)
        expect(ui.page.get_by_text(
            "The download was not authorized or did not return a complete file. No file was saved.", exact=True,
        )).to_be_visible()
        expect(command(ui, "Download")).to_be_enabled()
        expect(ui.page.get_by_text("Download ready.", exact=True)).to_have_count(0)
        assert downloads == []
        ui.page.get_by_role("button", name="Dismiss notification", exact=True).click()
        expect(ui.page.get_by_text(
            "The download was not authorized or did not return a complete file. No file was saved.", exact=True,
        )).to_have_count(0)
    assert len(ui.operation_requests) == len(cases)


def test_metadata_and_reprocess_partial_queues_refresh_success_and_retry_failures(group_management_ui):
    ui = group_management_ui
    open_documents(ui)
    for resource, label, extra in (
        ("extract_metadata", "Extract", {}),
        ("reprocess_extraction", "Switch to Enhanced", {"extraction_mode": "layout"}),
    ):
        select_documents(ui, "same-document", "notes-document")
        initial_reads = len([entry for entry in ui.requests if entry.path == "/api/group_documents"])
        partial = ui.queue_operation(
            "POST", resource, body={"document_ids": ["same-document", "notes-document"], **extra},
            status=207,
            response=queue_result(
                "same-document", errors=[batch_error("notes-document")],
                extraction_mode=extra.get("extraction_mode"),
            ),
        )
        perform(ui, partial, command(ui, label).click)
        expect(explorer(ui).get_by_role("alert")).to_contain_text(DOCUMENT_OPERATION_FAILED_ERROR)
        expect(explorer(ui).get_by_role("alert")).to_contain_text("1 of 2 confirmed")
        expect(checkbox(ui, "same-document")).not_to_be_checked()
        expect(checkbox(ui, "notes-document")).to_be_checked()
        expect(explorer(ui)).to_be_enabled()
        refreshed_reads = len([entry for entry in ui.requests if entry.path == "/api/group_documents"])
        assert refreshed_reads > initial_reads
        retry = ui.queue_operation(
            "POST", resource, body={"document_ids": ["notes-document"], **extra}, status=202,
            response=queue_result("notes-document", extraction_mode=extra.get("extraction_mode")),
        )
        perform(ui, retry, command(ui, label).click)
        expect(explorer(ui).get_by_role("status").filter(has_text="queued: 1 of 1 confirmed")).to_be_visible()
        expect(explorer(ui).get_by_role("alert")).to_have_count(0)
        assert ui.record("same-document")["keywords"] == ["baseline"]
    assert len(ui.operation_requests) == 4


def test_native_tags_admin_create_normalizes_name_and_recolour_requires_save(group_management_ui):
    ui = group_management_ui
    ui.set_policy(role="Admin")
    original_documents = copy.deepcopy(ui.documents)
    open_tags(ui)
    ui.page.get_by_label("New tag", exact=True).fill("  Urgent  ")
    ui.page.get_by_role("button", name="Use colour #8b5cf6", exact=True).click()
    vocabulary = {**ui.vocabulary["group-a"], "urgent": "#8b5cf6"}
    created = ui.queue_operation(
        "POST", "tags", body={"tag_name": "urgent", "color": "#8b5cf6"},
        response=tag_created("urgent", "#8b5cf6"),
        status=201, vocabulary=vocabulary,
    )
    perform(ui, created, ui.page.get_by_role("button", name="Create", exact=True).click)
    expect(tag_row(ui, "urgent")).to_contain_text("0 documents")
    expect(ui.page.get_by_label("New tag", exact=True)).to_have_value("")
    colour = ui.page.get_by_label("Colour for urgent", exact=True)
    colour.evaluate("""(input, value) => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value);
        input.dispatchEvent(new Event('input', {bubbles: true}));
        input.dispatchEvent(new Event('change', {bubbles: true}));
    }""", "#ef4444")
    expect(tag_row(ui, "urgent").get_by_role("button", name="Save colour", exact=True)).to_be_enabled()
    assert len(ui.operation_requests) == 1
    recoloured = ui.queue_operation(
        "PATCH", "tags/urgent", body={"color": "#ef4444"},
        response=tag_result("update", tag={"name": "urgent", "color": "#ef4444"}),
        vocabulary={**vocabulary, "urgent": "#ef4444"},
    )
    perform(ui, recoloured, tag_row(ui, "urgent").get_by_role("button", name="Save colour", exact=True).click)
    expect(colour).to_have_value("#ef4444")
    expect(ui.page.get_by_role("combobox", name="Group workspace", exact=True)).to_be_enabled()
    assert ui.documents == original_documents
    assert len(ui.operation_requests) == 2


def test_tag_creation_requires_201_and_the_actual_name_and_colour(group_management_ui):
    ui = group_management_ui
    original = copy.deepcopy(ui.vocabulary["group-a"])
    body = {"tag_name": "urgent", "color": "#3b82f6"}
    receipt = tag_created("urgent", "#3b82f6")
    cases = (
        ("wrong-status", {"response": receipt, "status": 200}),
        ("message-only", {"response": {"message": TAG_CREATED_MESSAGE}, "status": 201}),
        ("missing-name", {"response": {"message": TAG_CREATED_MESSAGE, "tag": {"color": "#3b82f6"}}, "status": 201}),
        ("missing-colour", {"response": {"message": TAG_CREATED_MESSAGE, "tag": {"name": "urgent"}}, "status": 201}),
        ("wrong-name", {"response": {**receipt, "tag": {"name": "other-tag", "color": "#3b82f6"}}, "status": 201}),
    )
    open_tags(ui)
    ui.page.get_by_label("New tag", exact=True).fill("urgent")
    for name, outcome in cases:
        reply = ui.queue_operation("POST", "tags", body=body, **outcome)
        perform(ui, reply, ui.page.get_by_role("button", name="Create", exact=True).click)
        expect(ui.page.get_by_role("alert")).to_be_visible()
        expect(
            ui.page.get_by_label("New tag", exact=True),
            f"The {name} receipt must not clear the new-tag draft.",
        ).to_have_value("urgent")
        expect(ui.page.get_by_label("Colour for urgent", exact=True)).to_have_count(0)
        expect(ui.page.get_by_role("button", name="Create", exact=True)).to_be_enabled()
        assert ui.vocabulary["group-a"] == original, name
    assert len(ui.operation_requests) == len(cases)


def test_a_tag_vocabulary_conflict_shows_the_servers_sentence_and_keeps_the_draft(group_management_ui):
    ui = group_management_ui
    original = copy.deepcopy(ui.vocabulary["group-a"])
    open_tags(ui)
    ui.page.get_by_label("New tag", exact=True).fill("urgent")
    # The real 409 when the group changed under the vocabulary write: its sentence in `error`, its
    # machine code in `error_code`.
    reply = ui.queue_operation(
        "POST", "tags", body={"tag_name": "urgent", "color": "#3b82f6"}, response=tag_vocabulary_refusal(), status=409,
    )
    perform(ui, reply, ui.page.get_by_role("button", name="Create", exact=True).click)
    expect(ui.page.get_by_role("alert").filter(has_text=VOCABULARY_CONFLICT_MESSAGE)).to_be_visible()
    expect(ui.page.get_by_text(VOCABULARY_CONFLICT_CODE)).to_have_count(0)
    expect(ui.page.get_by_label("New tag", exact=True)).to_have_value("urgent")
    expect(ui.page.get_by_label("Colour for urgent", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Create", exact=True)).to_be_enabled()
    assert ui.vocabulary["group-a"] == original
    assert len(ui.operation_requests) == 1


def test_native_tag_encoded_rename_merge_and_delete_consume_owned_current_outcomes(group_management_ui):
    ui = group_management_ui
    ui.set_policy(role="DocumentManager")
    history = copy.deepcopy(ui.versions[("group-a", "same-document")][1])
    incoming = copy.deepcopy(ui.record("shared-report"))
    other_group = copy.deepcopy(ui.documents["group-b"])
    open_tags(ui)
    item = begin_rename(ui, "legacy/review", "Archive")
    renamed_notes = changed_record(ui, "notes-document", tags=["team", "archive"])
    vocabulary = {name: colour for name, colour in ui.vocabulary["group-a"].items() if name != "legacy/review"}
    vocabulary["archive"] = "#8b5cf6"
    rename = ui.queue_operation(
        "PATCH", f"tags/{quote('legacy/review', safe='')}", body={"new_name": "archive"},
        response=tag_result(
            "rename", tag={"name": "archive", "color": "#8b5cf6"},
            success=[{"document_id": "notes-document", "tags": renamed_notes["tags"]}],
        ),
        records=[renamed_notes], vocabulary=vocabulary,
    )
    perform(ui, rename, item.get_by_role("button", name="Save", exact=True).click)
    expect(tag_row(ui, "archive")).to_contain_text("1 document")
    expect(ui.page.get_by_label("Colour for legacy/review", exact=True)).to_have_count(0)
    item = begin_rename(ui, "archive", "team")
    expect(item.get_by_role("button", name="Merge", exact=True)).to_be_enabled()
    merged_notes = changed_record(ui, "notes-document", tags=["team"])
    vocabulary.pop("archive")
    merge = ui.queue_operation(
        "PATCH", "tags/archive", body={"new_name": "team"},
        response=tag_result(
            "rename", tag={"name": "team", "color": vocabulary["team"]},
            success=[{"document_id": "notes-document", "tags": ["team"]}],
        ),
        records=[merged_notes], vocabulary=vocabulary,
    )
    perform(ui, merge, item.get_by_role("button", name="Merge", exact=True).click)
    expect(ui.page.get_by_label("Colour for archive", exact=True)).to_have_count(0)
    expect(tag_row(ui, "team")).to_contain_text("2 documents")
    ui.page.get_by_role("button", name="Delete tag team", exact=True).click()
    dialog = ui.page.get_by_role("dialog", name="Delete tag", exact=True)
    expect(dialog).to_contain_text("team")
    vocabulary.pop("team")
    updated = [
        changed_record(ui, "same-document", tags=["finance"]),
        changed_record(ui, "notes-document", tags=[]),
    ]
    deleted = ui.queue_operation(
        "DELETE", "tags/team",
        response=tag_result("delete", success=[
            {"document_id": record["id"], "tags": record["tags"]} for record in updated
        ]),
        records=updated, vocabulary=vocabulary,
    )
    perform(ui, deleted, dialog.get_by_role("button", name="Delete tag", exact=True).click)
    expect(dialog).to_have_count(0)
    expect(ui.page.get_by_label("Colour for team", exact=True)).to_have_count(0)
    assert ui.versions[("group-a", "same-document")][1] == history
    assert ui.record("shared-report") == incoming and ui.documents["group-b"] == other_group
    ui.page.locator('a[href="/v2/groups/group-a/documents"]').first.click()
    expect(details_button(ui, "notes-document")).to_be_visible()
    expect(document_row(ui, "notes-document").get_by_text("team", exact=True)).to_have_count(0)
    expect(document_row(ui, "shared-report").get_by_text("finance", exact=True)).to_be_visible()


@pytest.mark.parametrize("operation", ["rename", "delete"])
def test_partial_tag_vocabulary_retains_old_definition_and_failed_current_documents(group_management_ui, operation):
    ui = group_management_ui
    ui.record("notes-document")["tags"].append("finance")
    original_history = copy.deepcopy(ui.versions[("group-a", "same-document")][1])
    open_tags(ui)
    target_tags = ["budget", "team"] if operation == "rename" else ["team"]
    vocabulary = copy.deepcopy(ui.vocabulary["group-a"])
    if operation == "rename":
        vocabulary["budget"] = vocabulary["finance"]
        item = begin_rename(ui, "finance", "budget")
        submit = item.get_by_role("button", name="Save", exact=True)
    else:
        ui.page.get_by_role("button", name="Delete tag finance", exact=True).click()
        submit = ui.page.get_by_role("dialog", name="Delete tag", exact=True).get_by_role(
            "button", name="Delete tag", exact=True,
        )
    partial = ui.queue_operation(
        "PATCH" if operation == "rename" else "DELETE", "tags/finance",
        body={"new_name": "budget"} if operation == "rename" else None, status=207,
        response=tag_result(
            operation, tag={"name": "budget", "color": vocabulary["finance"]} if operation == "rename" else None,
            success=[{"document_id": "same-document", "tags": target_tags}],
            errors=[batch_error("notes-document", TAG_REVISION_CHANGED_ERROR)],
        ),
        records=[changed_record(ui, "same-document", tags=target_tags)], vocabulary=vocabulary,
    )
    perform(ui, partial, submit.click)
    expect(ui.page.get_by_role("alert").filter(has_text=TAG_REVISION_CHANGED_ERROR)).to_be_visible()
    expect(tag_row(ui, "finance")).to_contain_text("2 documents")
    if operation == "rename":
        expect(tag_row(ui, "budget")).to_contain_text("1 document")
    expect(ui.page.get_by_text(re.compile(r'^Renamed to |^Deleted "finance"'))).to_have_count(0)
    assert "finance" in ui.vocabulary["group-a"]
    assert "finance" in ui.record("notes-document")["tags"]
    assert ui.versions[("group-a", "same-document")][1] == original_history
    assert len(ui.operation_requests) == 1


@pytest.mark.parametrize("operation", ["rename", "delete"])
def test_tag_vocabulary_cas_conflict_keeps_propagation_and_requires_retry(group_management_ui, operation):
    ui = group_management_ui
    ui.page.clock.install()
    original_history = copy.deepcopy(ui.versions[("group-a", "same-document")][1])
    incoming = copy.deepcopy(ui.record("shared-report"))
    other_group = copy.deepcopy(ui.documents["group-b"])
    open_tags(ui)
    method = "PATCH" if operation == "rename" else "DELETE"
    body = {"new_name": "budget"} if operation == "rename" else None
    target_tags = ["budget", "team"] if operation == "rename" else ["team"]
    vocabulary = {**ui.vocabulary["group-a"], "review": "#ef4444"}
    target = {"name": "budget", "color": vocabulary["finance"]} if operation == "rename" else None
    conflict = tag_vocabulary_conflict()
    if operation == "rename":
        vocabulary["budget"] = vocabulary["finance"]
        item = begin_rename(ui, "finance", "budget")
        submit = item.get_by_role("button", name="Save", exact=True)
    else:
        ui.page.get_by_role("button", name="Delete tag finance", exact=True).click()
        dialog = ui.page.get_by_role("dialog", name="Delete tag", exact=True)
        submit = dialog.get_by_role("button", name="Delete tag", exact=True)
    partial = ui.queue_operation(
        method, "tags/finance", body=body, status=207,
        response=tag_result(
            operation, tag=target, success=[{"document_id": "same-document", "tags": target_tags}],
            errors=[conflict],
        ),
        records=[changed_record(ui, "same-document", tags=target_tags)], vocabulary=vocabulary,
    )
    with ui.page.expect_response(response_for("GET", "/api/group_documents/tags")) as refreshed:
        perform(ui, partial, submit.click)
    refreshed.value.finished()
    feedback = ui.page.get_by_role("alert").filter(has_text=conflict["message"])
    expect(feedback).to_be_visible()
    expect(feedback).to_contain_text("Tag vocabulary")
    expect(feedback).to_contain_text(re.compile(r"\b1 document updates? (?:was|were) confirmed\b"))
    expect(ui.page.get_by_label("Colour for review", exact=True)).to_have_value("#ef4444")
    expect(tag_row(ui, "finance")).to_contain_text("1 document")
    expect(ui.page.get_by_role("combobox", name="Group workspace", exact=True)).to_be_disabled()
    if operation == "rename":
        expect(tag_row(ui, "finance").get_by_role("textbox", name="Rename finance", exact=True)).to_have_value("budget")
        expect(tag_row(ui, "budget")).to_contain_text("1 document")
        retry_button = tag_row(ui, "finance").get_by_role("button", name="Merge", exact=True)
    else:
        expect(dialog).to_be_visible()
        retry_button = dialog.get_by_role("button", name="Delete tag", exact=True)
    expect(retry_button).to_be_enabled()
    ui.page.clock.fast_forward(10000)
    expect(feedback).to_be_visible()
    assert len(ui.operation_requests) == 1
    assert not ui.planned_operations
    assert ui.record("same-document")["tags"] == target_tags
    assert ui.versions[("group-a", "same-document")][1] == original_history
    assert ui.record("shared-report") == incoming and ui.documents["group-b"] == other_group

    propagated_documents = copy.deepcopy(ui.documents)
    vocabulary.pop("finance")
    retry = ui.queue_operation(
        method, "tags/finance", body=body, response=tag_result(operation, tag=target), vocabulary=vocabulary,
    )
    with ui.page.expect_response(response_for("GET", "/api/group_documents/tags")) as refreshed:
        perform(ui, retry, retry_button.click)
    refreshed.value.finished()
    expect(ui.page.get_by_label("Colour for finance", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("alert").filter(has_text=conflict["message"])).to_have_count(0)
    expect(ui.page.get_by_role("combobox", name="Group workspace", exact=True)).to_be_enabled()
    if operation == "rename":
        expect(tag_row(ui, "budget")).to_contain_text("1 document")
    else:
        expect(dialog).to_have_count(0)
    assert ui.documents == propagated_documents
    assert len(ui.operation_requests) == 2
    assert all(entry.method == method and entry.path == operation_path("tags/finance") for entry in ui.operation_requests)


def test_dirty_and_busy_navigation_never_discards_an_inflight_write(group_management_ui):
    ui = group_management_ui
    open_tags(ui)
    ui.page.locator('a[href="/v2/groups/group-a/documents"]').first.click()
    expect(details_button(ui, "same-document")).to_be_visible()
    dialog = edit_metadata(ui)
    dialog.get_by_label(re.compile(r"^Title")).fill("Navigation-protected draft")
    expect(ui.page.get_by_role("combobox", name="Group workspace", exact=True)).to_be_disabled()
    protected = ui.page.evaluate("""() => {
        const event = new Event('beforeunload', {cancelable: true});
        window.dispatchEvent(event);
        return event.defaultPrevented;
    }""")
    assert protected is True
    ui.page.evaluate("history.back()")
    leave = ui.page.get_by_role("dialog", name="Discard unsaved changes?", exact=True)
    expect(leave).to_be_visible()
    leave.get_by_role("button", name="Keep editing", exact=True).click()
    expect(dialog.get_by_label(re.compile(r"^Title"))).to_have_value("Navigation-protected draft")
    reply = ui.queue_operation(
        "PATCH", "same-document", body={"title": "Navigation-protected draft"},
        response=metadata_result("same-document", {"title": "Navigation-protected draft"}),
        records=[changed_record(ui, "same-document", title="Navigation-protected draft")],
    )
    ui.defer_next("PATCH", reply.path)
    with ui.page.expect_request(lambda request: request.method == "PATCH" and urlsplit(request.url).path == reply.path):
        dialog.get_by_role("button", name="Save", exact=True).click()
    expect(dialog.get_by_role("button", name="Cancel", exact=True)).to_be_disabled()
    ui.page.keyboard.press("Escape")
    expect(dialog).to_be_visible()
    ui.page.evaluate("history.back()")
    leave = ui.page.get_by_role("dialog", name="Your changes are still being saved", exact=True)
    expect(leave.get_by_role("button", name="Discard changes", exact=True)).to_be_disabled()
    leave.get_by_role("button", name="Keep editing", exact=True).click()
    assert len(ui.pending_responses) == 1 and not ui.completed_operations
    assert ui.record("same-document")["title"] == "Research brief"
    perform(ui, reply, ui.release_responses)
    expect(dialog).to_have_count(0)
    expect(details_button(ui, "same-document")).to_be_visible()
    expect(ui.page.get_by_role("combobox", name="Group workspace", exact=True)).to_be_enabled()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a/documents")
    assert len(ui.completed_operations) == 1 and not ui.failed_operations


def test_transient_refocus_failure_pauses_save_without_discarding_metadata(group_management_ui):
    ui = group_management_ui
    open_documents(ui)
    dialog = edit_metadata(ui)
    dialog.get_by_label(re.compile(r"^Title")).fill("Draft across refocus")
    ui.reject_next("GET", GROUP_CONTEXT)
    with ui.page.expect_response(response_for("GET", GROUP_CONTEXT)) as failed:
        ui.page.evaluate("window.dispatchEvent(new Event('focus'))")
    failed.value.finished()
    expect(ui.page.get_by_role("alert").filter(has_text="Your changes are kept")).to_be_visible()
    expect(dialog.get_by_role("button", name="Save", exact=True)).to_be_disabled()
    expect(dialog.get_by_label(re.compile(r"^Title"))).to_have_value("Draft across refocus")
    expect(dialog).to_contain_text("Your draft is kept.")
    assert not ui.operation_requests
    with ui.page.expect_response(response_for("GET", GROUP_CONTEXT)) as recovered:
        ui.page.evaluate("window.dispatchEvent(new Event('focus'))")
    recovered.value.finished()
    expect(dialog.get_by_role("button", name="Save", exact=True)).to_be_enabled()
    expect(dialog.get_by_label(re.compile(r"^Title"))).to_have_value("Draft across refocus")
    reply = ui.queue_operation(
        "PATCH", "same-document", body={"title": "Draft across refocus"},
        response=metadata_result("same-document", {"title": "Draft across refocus"}),
        records=[changed_record(ui, "same-document", title="Draft across refocus")],
    )
    perform(ui, reply, dialog.get_by_role("button", name="Save", exact=True).click)
    expect(dialog).to_have_count(0)
    expect(details_button(ui, "same-document")).to_be_visible()


@pytest.mark.parametrize("theme,width,height,label", [
    ("light", 1440, 900, "dl"), ("dark", 1440, 900, "dd"),
    ("light", 390, 844, "ml"), ("dark", 390, 844, "md"),
])
def test_management_layout_dialogs_and_tags_in_both_themes(group_management_ui, theme, width, height, label):
    ui = group_management_ui
    open_documents(ui, theme=theme, width=width, height=height)
    expect(command(ui, "Upload")).to_be_enabled()
    assert_no_personal_controls(ui)
    ui.assert_no_overflow()
    bounds = explorer(ui).bounding_box()
    search = ui.page.get_by_role("searchbox", name="Search documents. Press Enter to search immediately.", exact=True)
    search_bounds = search.bounding_box()
    table_viewport = ui.page.get_by_role("table").locator("..").bounding_box()
    assert bounds and bounds["width"] >= 200 and bounds["height"] >= 180
    assert search_bounds and search_bounds["width"] >= 180
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    ui.page.screenshot(path=str(SCREENSHOTS / f"{label}-docs.png"), full_page=True)
    assert table_viewport and table_viewport["height"] >= 160, (
        f"Documents need the existing 160px minimum table viewport; received {table_viewport}"
    )
    dialog = edit_metadata(ui)
    dialog.get_by_label(re.compile(r"^Title")).fill("A retained group draft")
    expect(dialog.get_by_role("button", name="Save", exact=True)).to_be_enabled()
    card = dialog.locator(".glass-modal")
    dialog_bounds = card.bounding_box()
    assert dialog_bounds and dialog_bounds["x"] >= 0 and dialog_bounds["width"] <= width
    assert dialog_bounds["y"] >= 0 and dialog_bounds["y"] + dialog_bounds["height"] <= height + 1
    fits = card.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
    assert fits is True
    ui.assert_no_overflow()
    ui.page.screenshot(path=str(SCREENSHOTS / f"{label}-edit.png"), full_page=True)
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    expect(dialog).to_have_count(0)
    ui.page.locator('a[href="/v2/groups/group-a/tags"]').first.click()
    expect(ui.page.get_by_role("heading", name="Tags", exact=True)).to_be_visible()
    expect(ui.page.get_by_label("New tag", exact=True)).to_be_visible()
    expect(tag_row(ui, "finance")).to_be_visible()
    expect(ui.page.locator("html")).to_have_css("color-scheme", theme)
    ui.assert_no_overflow()
    ui.page.screenshot(path=str(SCREENSHOTS / f"{label}-tags.png"), full_page=True)
    assert not ui.operation_requests


# --- Content screening in the group Documents section (G3) -----------------------------------------
# The section mounts personal documents' screening controls for the group, offered to the members the
# context's `screening_management` hint names. The routes they call are modelled in
# fixtures/group_screening.py, by the real screening rules.

SCREENING_REFUSED = "You are not authorized for this screening action. Your workspace access may have changed."
NO_SCAN_OFFERED = "No scan action is authorized for this scope, or new scanning is disabled."


def screening_requests(ui):
    return [entry for entry in ui.requests if entry.path.startswith("/api/content-screening/")]


def open_screening(ui):
    open_documents(ui)
    ui.page.get_by_role("button", name="Screening scans", exact=True).click()
    dialog = ui.page.get_by_role("dialog", name="Content screening controls", exact=True)
    expect(dialog).to_be_visible()
    return dialog


def test_a_manager_scans_the_group_from_its_documents(group_management_ui):
    """The group's own screening controls: the policy additions, the scan and its cancellation all
    name the group, never the viewer's personal workspace. The server accepts the start, and a
    cancel only requests cancellation, so the job stays listed with its holds enforced."""
    ui = group_management_ui
    dialog = open_screening(ui)
    expect(dialog.get_by_text("New scanning: enabled.", exact=False)).to_be_visible()
    expect(dialog.get_by_role("region", name="Workspace screening policy", exact=True)).to_be_visible()
    expect(dialog.get_by_role("link", name="Open Content review", exact=True)).to_have_attribute(
        "href", "/v2/content-review",
    )
    dialog.get_by_role("button", name="Start scan", exact=True).click()
    expect(dialog.get_by_role("button", name="Cancel scan", exact=True)).to_be_enabled()
    assert ui.screening_scan_starts == [{"scope_type": "group", "scope_id": "group-a"}]
    dialog.get_by_role("button", name="Cancel scan", exact=True).click()
    expect(dialog.get_by_text("Cancellation requested; existing holds remain enforced.", exact=False)).to_be_visible()
    expect(dialog.get_by_role("button", name="Cancel scan", exact=True)).to_be_disabled()
    assert ui.screening_actions == [("job-group-1", "cancel")]
    requests = screening_requests(ui)
    assert "/api/content-screening/policies/group/group-a" in {entry.path for entry in requests}
    assert all(entry.query.get("scope_id", ["group-a"]) == ["group-a"] for entry in requests)
    assert not [entry for entry in requests if "/personal/" in entry.path or "personal" in entry.query.get("scope_type", [])]


def test_no_scan_is_offered_while_new_scanning_is_off(group_management_ui):
    """With new scanning off the controls still open and say so, but offer no scan; the policy
    additions stay with the members the server accepts, exactly as personal's do."""
    ui = group_management_ui
    ui.screening_enabled = False
    dialog = open_screening(ui)
    expect(dialog.get_by_text("New scanning: disabled.", exact=False)).to_be_visible()
    expect(dialog.get_by_text(NO_SCAN_OFFERED, exact=True)).to_be_visible()
    expect(dialog.get_by_role("button", name="Start scan", exact=True)).to_have_count(0)
    expect(dialog.get_by_role("region", name="Workspace screening policy", exact=True)).to_be_visible()
    assert not ui.screening_scan_starts


@pytest.mark.parametrize("role,offered", [
    ("Owner", True), ("Admin", True), ("DocumentManager", True), ("User", False),
])
def test_screening_is_offered_to_exactly_the_members_the_server_accepts(group_management_ui, role, offered):
    """The screening routes accept a group's Owner, Admin or DocumentManager, and the hint says so: an
    ordinary member is offered nothing. Nothing is read until the controls are opened."""
    ui = group_management_ui
    ui.set_policy("group-a", role=role)
    open_documents(ui)
    button = ui.page.get_by_role("button", name="Screening scans", exact=True)
    if offered:
        expect(button).to_be_enabled()
    else:
        expect(button).to_have_count(0)
    assert not screening_requests(ui)


@pytest.mark.parametrize("status", ["locked", "upload_disabled"])
def test_screening_follows_the_role_in_every_viewable_status(group_management_ui, status):
    """The screening routes check no group status, so neither does the hint: the Owner of a locked or
    upload-disabled group is still offered the controls, and the server still answers them."""
    ui = group_management_ui
    ui.set_policy("group-a", role="Owner", status=status)
    dialog = open_screening(ui)
    expect(dialog.get_by_role("region", name="Workspace screening policy", exact=True)).to_be_visible()
    expect(dialog.get_by_role("button", name="Start scan", exact=True)).to_be_enabled()


def test_a_stale_screening_hint_meets_the_servers_refusal(group_management_ui):
    """The controls stay the server's to authorize: when the viewer's role changes after the page read
    its context, opening them shows the refusal and offers neither a scan nor policy additions."""
    ui = group_management_ui
    open_documents(ui)
    ui.set_policy("group-a", role="User")
    ui.page.get_by_role("button", name="Screening scans", exact=True).click()
    dialog = ui.page.get_by_role("dialog", name="Content screening controls", exact=True)
    expect(dialog.get_by_text(SCREENING_REFUSED, exact=True)).to_be_visible()
    expect(dialog.get_by_role("button", name="Start scan", exact=True)).to_have_count(0)
    expect(dialog.get_by_role("region", name="Workspace screening policy", exact=True)).to_have_count(0)
    assert not ui.screening_scan_starts
