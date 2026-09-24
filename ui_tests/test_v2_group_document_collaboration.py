# test_v2_group_document_collaboration.py
"""
Production-SPA M2C sharing and publication browser scenarios.
Version: 0.261.160
Implemented in: 0.261.130
Every scripted refusal and partial outcome is the server's (fixtures/group_document_collaboration.py,
pinned by functional_tests/test_group_document_fixture_parity.py), except the deliberately malformed
receipts a robustness scenario names.

Selectors use the real row, details and compact review actions and sharing/review dialog.
Deep-link cases expect review, never a decision, to open for the exact requested
document. Terminal cleanup uses normal-read 404s; one separately bound recipient
repair case is cleanup-only and grants no document access. Notification-consumer
glue loads the actual local notification script before entering the production SPA.

PYTHONPATH must include ui_tests\\fixtures. All HTTP is closed fixture traffic;
no components/stores, redirects, downloads, model calls or live APIs are mocked
into the application. Set SIMPLECHAT_UI_SCREENSHOTS to a short artifact path.
"""

import copy
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.group_document_collaboration import (
    COLLABORATION_OPERATIONS, COLLABORATION_PATH, FAILED_HANDOFF_ERRORS, PUBLICATION_HANDOFF_ERROR, STATE_CONFLICT,
    collaboration_path, collaboration_receipt, connect_options, effect_error,  # noqa: F401
    group_collaboration_ui, publication, recipient,  # noqa: F401
)
from ui_tests.fixtures.workspace_authoring import ORIGIN


pytestmark = pytest.mark.ui
SCREENSHOTS = Path(os.environ.get(
    "SIMPLECHAT_UI_SCREENSHOTS", str(Path(__file__).parent / "artifacts" / "gc"),
))
REVIEW_TITLE = "Document sharing and review"
GROUP_CONTEXT = "/api/v2/workspaces/group/group-a"


def explorer(ui):
    return ui.page.get_by_role("group", name="Documents explorer", exact=True)


def review_dialog(ui):
    return ui.page.get_by_role("dialog", name=REVIEW_TITLE, exact=True)


def row(ui, identifier, group_id="group-a"):
    record = ui.record(identifier, group_id)
    name = record.get("title") or record["file_name"]
    return ui.page.get_by_role("row").filter(
        has=ui.page.get_by_role("button", name=f"Details for {name}", exact=True),
    )


def review_control(ui, identifier, group_id="group-a"):
    record = ui.record(identifier, group_id)
    name = record.get("title") or record["file_name"]
    return row(ui, identifier, group_id).get_by_role("button", name=f"Review {name}", exact=True)


def response_for(method, path, status=None):
    return lambda response: (
        response.request.method == method and urlsplit(response.url).path == path
        and (status is None or response.status == status)
    )


def perform(ui, reply, action):
    with ui.page.expect_response(response_for(reply.method, reply.path)) as pending:
        action()
    response = pending.value
    assert response.status == reply.status
    response.finished()
    return response


def open_documents(ui, **options):
    ui.open("/groups/group-a/documents", **options)
    expect(row(ui, "same-document")).to_be_visible()
    expect(explorer(ui)).to_have_attribute("aria-busy", "false")


def open_review(ui, identifier="same-document", group_id="group-a"):
    with ui.page.expect_response(response_for("GET", collaboration_path(identifier, group_id=group_id))) as read:
        review_control(ui, identifier, group_id).click()
    read.value.finished()
    dialog = review_dialog(ui)
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("button", name="Refresh review details", exact=True)).to_be_enabled()
    return dialog


def refresh_review(ui, identifier="same-document", *, confirmation=None):
    button = (
        confirmation.get_by_role("button", name="Refresh and review", exact=True)
        if confirmation is not None else
        review_dialog(ui).get_by_role("button", name="Refresh review details", exact=True)
    )
    with ui.page.expect_response(response_for("GET", collaboration_path(identifier))) as read:
        button.click()
    read.value.finished()
    return read.value


def choose_target(ui, name="Destination 05"):
    radio = review_dialog(ui).get_by_role("radio", name=f"Select {name}", exact=True)
    expect(radio).to_be_enabled()
    radio.check()
    expect(radio).to_be_checked()
    return radio


def confirm(ui, label, *, source=None):
    container = source if source is not None else review_dialog(ui)
    container.get_by_role("button", name=label, exact=True).click()
    dialog = ui.page.get_by_role("dialog", name=f"Confirm {label.lower()}", exact=True)
    expect(dialog).to_be_visible()
    return dialog


def unavailable(control):
    for button in control.all():
        expect(button).to_be_disabled()


def changed_state(ui, identifier="same-document", **changes):
    return {**copy.deepcopy(ui.review_state(identifier)), **copy.deepcopy(changes)}


def changed_record(ui, identifier, **changes):
    return {**copy.deepcopy(ui.record(identifier)), **copy.deepcopy(changes)}


def assert_terminal_cleanup(ui, identifier):
    dialog = review_dialog(ui)
    expect(dialog.get_by_role("status").filter(has_text="Decision confirmed.")).to_be_visible()
    expect(dialog.get_by_role("status").filter(has_text="no longer available")).to_be_visible()
    expect(dialog.get_by_role("alert")).to_have_count(0)
    responses = [
        payload for url, payload in ui.responses
        if urlsplit(url).path in (
            f"/api/group_documents/{identifier}", collaboration_path(identifier),
        )
    ]
    assert any(isinstance(payload, dict) and "error" in payload for payload in responses)
    assert not any(record["id"] == identifier for record in ui.documents["group-a"])


def notification(identifier="off-page", *, link=None, group_id="group-a"):
    return {
        "id": "review-notice", "is_read": False, "title": "Review the group document",
        "message": "Open the exact document revision for review.", "created_at": "2026-09-22T10:00:00Z",
        "link_url": link or f"/v2/groups/{group_id}/documents?document_id={identifier}",
        "link_context": {"workspace_type": "group", "group_id": group_id, "document_id": identifier},
    }


def test_native_notification_enters_exact_off_page_review_without_legacy_activation(group_collaboration_ui):
    ui = group_collaboration_ui
    ui.add_off_page_document()
    ui.active_group = "group-b"
    ui.notifications = [notification()]
    ui.page.goto(f"{ORIGIN}/notifications", wait_until="networkidle")
    expect(ui.page.get_by_text("Review the group document", exact=True)).to_be_visible()
    assert not [entry for entry in ui.writes if entry.path == "/api/groups/setActive"]
    ui.page.get_by_text("Review the group document", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a/documents?document_id=off-page")
    dialog = review_dialog(ui)
    expect(dialog).to_be_visible()
    expect(dialog.get_by_text("off-page", exact=True)).to_be_visible()
    expect(dialog.get_by_text("7", exact=True)).to_be_visible()
    assert ui.notification_reads == ["review-notice"]
    activation = [index for index, entry in enumerate(ui.requests) if entry.path == "/api/groups/setActive"]
    bootstrap = [index for index, entry in enumerate(ui.requests) if entry.path == "/api/v2/bootstrap"]
    assert len(activation) == 1 and bootstrap and activation[0] > bootstrap[0], (
        "Only the scoped V2 controller may align navigation after SPA bootstrap, not the legacy notification handler."
    )
    assert any(
        entry.path == "/api/group_documents/off-page" and entry.query == {"group_id": ["group-a"]}
        for entry in ui.requests
    )
    assert not ui.operation_requests


@pytest.mark.parametrize("link", [
    "/v2/groups/other/documents?document_id=off-page",
    "/v2/groups/group-a/documents?document_id=other",
    "/v2/groups//documents?document_id=off-page",
    "/v2/groups/group-a//documents?document_id=off-page",
])
def test_mismatched_notification_has_no_navigation_or_activation_side_effect(group_collaboration_ui, link):
    ui = group_collaboration_ui
    ui.notifications = [notification(link=link)]
    ui.page.goto(f"{ORIGIN}/notifications", wait_until="networkidle")
    ui.page.get_by_text("Review the group document", exact=True).click()
    expect(ui.page.get_by_role("alert")).to_contain_text("does not match")
    expect(ui.page).to_have_url(f"{ORIGIN}/notifications")
    assert not ui.notification_reads
    assert not ui.writes
    assert not ui.operation_requests


def test_missing_or_unknown_support_never_reuses_personal_sharing(group_collaboration_ui):
    ui = group_collaboration_ui
    for capability in (None, {"schema_version": 99, "operations": list(COLLABORATION_OPERATIONS)}):
        if capability is None:
            ui.groups["group-a"].pop("document_collaboration")
        else:
            ui.groups["group-a"]["document_collaboration"] = capability
        open_documents(ui)
        expect(explorer(ui).get_by_role("button", name=re.compile(r"^Review\b"))).to_have_count(0)
        row(ui, "same-document").get_by_role("button", name="Details for Research brief", exact=True).click()
        expect(explorer(ui).get_by_role("button", name="Share", exact=True)).to_have_count(0)
        expect(ui.page.get_by_role("button", name=re.compile(r"Classic", re.IGNORECASE)).first).to_be_visible()
        assert not [entry for entry in ui.requests if COLLABORATION_PATH.fullmatch(entry.path)]
    assert not ui.operation_requests


def test_workspace_record_and_fresh_review_actions_intersect(group_collaboration_ui):
    ui = group_collaboration_ui
    ui.configure_group(status="locked", operations=["inspect"])
    open_documents(ui)
    dialog = open_review(ui)
    unavailable(dialog.get_by_role("button", name="Share with group", exact=True))
    unavailable(dialog.get_by_role("button", name="Stop sharing", exact=True))
    dialog.get_by_role("button", name="Done", exact=True).click()
    ui.configure_group()
    ui.record("same-document").pop("document_collaboration_actions")
    open_documents(ui)
    expect(review_control(ui, "same-document")).to_have_count(0)
    ui.record("same-document")["document_collaboration_actions"] = ["inspect"]
    open_documents(ui)
    dialog = open_review(ui)
    unavailable(dialog.get_by_role("button", name="Share with group", exact=True))
    dialog.get_by_role("button", name="Done", exact=True).click()
    ui.record("same-document")["document_collaboration_actions"] = ["inspect", "share", "unshare"]
    ui.review_state()["actions"] = ["inspect"]
    open_documents(ui)
    dialog = open_review(ui)
    expect(dialog.get_by_text("No collaboration decision is currently available.", exact=False)).to_be_visible()
    unavailable(dialog.get_by_role("button", name="Share with group", exact=True))
    dialog.get_by_role("button", name="Done", exact=True).click()
    ui.review_state()["group_id"] = "group-b"
    open_documents(ui)
    with ui.page.expect_response(response_for("GET", collaboration_path("same-document"))):
        review_control(ui, "same-document").click()
    expect(review_dialog(ui).get_by_role("alert")).to_contain_text("do not identify this group and document")
    unavailable(review_dialog(ui).get_by_role("button", name="Share with group", exact=True))
    assert not ui.operation_requests


def test_pending_recipient_review_does_not_select_or_unlock_source(group_collaboration_ui):
    ui = group_collaboration_ui
    open_documents(ui)
    pending = row(ui, "pending-report")
    expect(pending.get_by_role("checkbox")).to_be_disabled()
    expect(pending).to_have_attribute("draggable", "false")
    dialog = open_review(ui, "pending-report")
    expect(dialog).to_contain_text("Research group (group-a)")
    expect(dialog).to_contain_text("Publishing group (origin)")
    expect(dialog).to_contain_text("pending-report")
    expect(dialog.get_by_text("3", exact=True)).to_be_visible()
    expect(dialog.get_by_role("button", name="Approve access", exact=True)).to_be_enabled()
    expect(dialog.get_by_role("button", name="Deny request", exact=True)).to_be_enabled()
    expect(dialog.get_by_role("searchbox", name="Search recipient groups", exact=True)).to_have_count(0)
    expect(explorer(ui).locator('input[type="checkbox"]:checked')).to_have_count(0)
    expect(ui.page.get_by_text("Restricted pending title", exact=True)).to_have_count(0)
    dialog.get_by_role("button", name="Done", exact=True).click()
    pending.get_by_role("button", name="Details for pending-report.pdf", exact=True).click()
    pane = explorer(ui).get_by_role("complementary")
    for label in ("Chat", "Edit", "Tag", "Download", "Delete", "Extract"):
        unavailable(pane.get_by_role("button", name=label, exact=True))
    details_review = pane.get_by_role("button", name="Sharing and review", exact=True)
    expect(details_review).to_be_enabled()
    with ui.page.expect_response(response_for("GET", collaboration_path("pending-report"))) as reopened:
        details_review.click()
    reopened.value.finished()
    expect(review_dialog(ui)).to_be_visible()
    expect(pending.get_by_role("checkbox")).to_be_disabled()
    expect(explorer(ui).locator('input[type="checkbox"]:checked')).to_have_count(0)
    assert not ui.operation_requests


def test_user_requester_cannot_manage_others_but_can_confirm_own_cancellation(group_collaboration_ui):
    ui = group_collaboration_ui
    ui.configure_group(role="User", operations=["inspect", "cancel_artifact"])
    state = ui.review_state("requested-publication")
    state["publication"]["is_requester"] = False
    open_documents(ui)
    dialog = open_review(ui, "requested-publication")
    for label in ("Approve publication", "Reject publication", "Cancel publication request"):
        unavailable(dialog.get_by_role("button", name=label, exact=True))
    state["publication"]["is_requester"] = True
    refresh_review(ui, "requested-publication")
    confirmation = confirm(ui, "Cancel publication request")
    expect(confirmation).to_contain_text("Research group")
    expect(confirmation).to_contain_text("requested-publication.pdf")
    assert not ui.operation_requests
    reply = ui.queue_decision(
        "requested-publication", "cancel_artifact", expected_etag=state["etag"],
        response=collaboration_receipt("requested-publication", "cancel_artifact", "cancelled"),
        gone=True,
    )
    perform(ui, reply, confirmation.get_by_role("button", name="Cancel publication request", exact=True).click)
    expect(confirmation).to_have_count(0)
    assert_terminal_cleanup(ui, "requested-publication")
    assert not ui.groups["group-a"]["document_management"]["operations"]


def test_owner_target_search_pages_over_the_complete_eligible_set(group_collaboration_ui):
    ui = group_collaboration_ui
    open_documents(ui)
    dialog = open_review(ui)
    expect(dialog.get_by_role("radio")).to_have_count(25)
    expect(dialog.get_by_text(re.compile(r"35 eligible groups.*Page 1"))).to_be_visible()
    expect(dialog.get_by_role("radio", name="Select Research group", exact=True)).to_have_count(0)
    with ui.page.expect_response(response_for("GET", collaboration_path("same-document", "sharing/targets"))) as page_two:
        dialog.get_by_role("button", name="Next groups", exact=True).click()
    page_two.value.finished()
    expect(dialog.get_by_role("radio")).to_have_count(10)
    expect(dialog.get_by_text(re.compile(r"35 eligible groups.*Page 2"))).to_be_visible()
    dialog.get_by_role("searchbox", name="Search recipient groups", exact=True).fill("Destination 35")
    with ui.page.expect_response(response_for("GET", collaboration_path("same-document", "sharing/targets"))) as searched:
        dialog.get_by_role("button", name="Search groups", exact=True).click()
    searched.value.finished()
    expect(dialog.get_by_role("radio", name="Select Destination 35", exact=True)).to_be_visible()
    expect(dialog.get_by_role("radio")).to_have_count(1)
    expect(dialog.get_by_text(re.compile(r"1 eligible groups.*Page 1"))).to_be_visible()
    query = parse_qs(urlsplit(searched.value.url).query)
    assert query == {"search": ["Destination 35"], "page": ["1"], "page_size": ["25"]}
    assert not ui.operation_requests


def test_share_uses_fresh_etag_and_captured_scope_during_active_group_drift(group_collaboration_ui):
    ui = group_collaboration_ui
    other_group = copy.deepcopy(ui.documents["group-b"])
    open_documents(ui)
    dialog = open_review(ui)
    choose_target(ui)
    before = copy.deepcopy(ui.review_state())
    next_state = changed_state(
        ui, etag='"review:after-share"',
        recipients=[*before["recipients"], recipient("target-05", "Destination 05")],
    )
    reply = ui.queue_decision(
        "same-document", "share", expected_etag=before["etag"], target_group_id="target-05",
        response=collaboration_receipt("same-document", "share", "not_approved", target_group_id="target-05"),
        sharing_after=next_state,
    )
    ui.defer_next(reply.method, reply.path)
    with ui.page.expect_request(lambda request: request.method == reply.method and urlsplit(request.url).path == reply.path):
        dialog.get_by_role("button", name="Share with group", exact=True).click()
    expect(dialog.get_by_role("button", name="Done", exact=True)).to_be_disabled()
    expect(ui.page.get_by_role("combobox", name="Group workspace", exact=True)).to_be_disabled()
    ui.active_group = "group-b"
    perform(ui, reply, ui.release_responses)
    expect(dialog.get_by_role("status").filter(has_text="Decision confirmed.")).to_be_visible()
    expect(dialog.get_by_role("listitem").filter(has_text="target-05")).to_contain_text("Pending approval")
    assert ui.active_group == "group-b" and ui.documents["group-b"] == other_group
    assert ui.operation_requests[0].body == {"expected_etag": before["etag"], "target_group_id": "target-05"}
    assert not any(entry.path == "/api/groups/setActive" for entry in ui.writes)


def test_unshare_confirms_only_the_named_recipient_and_revision(group_collaboration_ui):
    ui = group_collaboration_ui
    history = copy.deepcopy(ui.versions)
    documents = copy.deepcopy(ui.documents)
    open_documents(ui)
    dialog = open_review(ui)
    source = dialog.get_by_role("listitem").filter(has_text="target-01")
    confirmation = confirm(ui, "Stop sharing", source=source)
    expect(confirmation).to_contain_text("Destination 01 (target-01)")
    expect(confirmation).to_contain_text("Revision 3")
    expect(confirmation).to_contain_text("other recipients are not deleted")
    expect(ui.page.get_by_role("combobox", name="Group workspace", exact=True)).to_be_disabled()
    assert not ui.operation_requests
    state = ui.review_state()
    reply = ui.queue_decision(
        "same-document", "unshare", expected_etag=state["etag"], target_group_id="target-01",
        response=collaboration_receipt("same-document", "unshare", "removed", target_group_id="target-01"),
        sharing_after=changed_state(
            ui, etag='"review:after-unshare"',
            recipients=[entry for entry in state["recipients"] if entry["id"] != "target-01"],
        ),
    )
    perform(ui, reply, confirmation.get_by_role("button", name="Stop sharing", exact=True).click)
    expect(confirmation).to_have_count(0)
    expect(dialog.get_by_role("listitem").filter(has_text="target-01")).to_have_count(0)
    expect(dialog.get_by_role("listitem").filter(has_text="target-02")).to_be_visible()
    assert ui.documents == documents and ui.versions == history
    assert ui.operation_requests[0].body == {"expected_etag": state["etag"]}
    assert ui.operation_requests[0].path == collaboration_path("same-document", "share/target-01")


def test_owner_partial_unshare_repairs_missing_target_without_touching_a_new_grant(group_collaboration_ui):
    ui = group_collaboration_ui
    ui.page.clock.install()
    documents = copy.deepcopy(ui.documents)
    history = copy.deepcopy(ui.versions)
    initial = copy.deepcopy(ui.review_state())
    open_documents(ui)
    dialog = open_review(ui)
    recipients = dialog.get_by_role("heading", name="Recipient groups", exact=True).locator("..")
    confirmation = confirm(
        ui, "Stop sharing", source=recipients.get_by_role("listitem").filter(has_text="target-01"),
    )
    removed = changed_state(
        ui, etag='"review:owner-cleanup-1"',
        recipients=[entry for entry in initial["recipients"] if entry["id"] != "target-01"],
    )
    notice = effect_error("notifications")
    message = notice["message"]
    receipt = collaboration_receipt(
        "same-document", "unshare", "removed", status="partial", target_group_id="target-01",
        errors=[notice],
    )
    partial = ui.queue_decision(
        "same-document", "unshare", expected_etag=initial["etag"], target_group_id="target-01",
        response=receipt, status=207, sharing_after=removed,
    )
    perform(ui, partial, confirmation.get_by_role("button", name="Stop sharing", exact=True).click)
    expect(confirmation).to_have_count(0)
    expect(dialog.get_by_role("alert").filter(has_text=message)).to_be_visible()
    expect(dialog.get_by_text("Owned by this group", exact=True)).to_be_visible()
    expect(recipients.get_by_role("listitem").filter(has_text="target-01")).to_have_count(0)
    expect(recipients.get_by_role("listitem").filter(has_text="target-02")).to_be_visible()
    panel = dialog.get_by_role("heading", name="Unfinished access cleanup", exact=True).locator("..")
    expect(panel).to_contain_text("Destination 01 (target-01)")
    retry_button = panel.get_by_role("button", name="Retry access cleanup", exact=True)
    expect(retry_button).to_be_disabled()
    ui.page.clock.fast_forward(10000)
    assert len(ui.operation_requests) == 1

    refresh_review(ui)
    expect(retry_button).to_be_enabled()
    retry_button.click()
    repair_confirmation = ui.page.get_by_role("dialog", name="Confirm access cleanup", exact=True)
    expect(repair_confirmation).to_be_visible()
    expect(repair_confirmation).to_contain_text("Destination 01 (target-01)")
    expect(repair_confirmation).to_contain_text("Revision 3")
    still_pending = {**copy.deepcopy(removed), "etag": '"review:owner-cleanup-2"'}
    retry = ui.queue_decision(
        "same-document", "unshare", expected_etag=removed["etag"], target_group_id="target-01",
        response=receipt, status=207, sharing_after=still_pending,
    )
    perform(ui, retry, repair_confirmation.get_by_role("button", name="Retry access cleanup", exact=True).click)
    expect(repair_confirmation).to_have_count(0)
    expect(dialog.get_by_role("alert").filter(has_text=message)).to_be_visible()
    expect(recipients.get_by_role("listitem").filter(has_text="target-01")).to_have_count(0)

    ui.reviews[("group-a", "same-document")] = {
        **copy.deepcopy(still_pending), "etag": '"review:new-recipient-grant"',
        "recipients": [recipient("target-01", "Destination 01", "approved"), *still_pending["recipients"]],
    }
    refresh_review(ui)
    expect(recipients.get_by_role("listitem").filter(has_text="target-01")).to_contain_text("Approved")
    expect(dialog.get_by_role("heading", name="Unfinished access cleanup", exact=True)).to_have_count(0)
    expect(dialog.get_by_role("button", name="Retry access cleanup", exact=True)).to_have_count(0)
    ui.page.clock.fast_forward(10000)
    assert len(ui.operation_requests) == 2
    assert all(
        entry.method == "DELETE" and entry.path == collaboration_path("same-document", "share/target-01")
        for entry in ui.operation_requests
    )
    assert [entry.body for entry in ui.operation_requests] == [
        {"expected_etag": initial["etag"]}, {"expected_etag": removed["etag"]},
    ]
    assert ui.documents == documents and ui.versions == history


def test_recipient_approval_does_not_grant_owner_metadata_authority(group_collaboration_ui):
    ui = group_collaboration_ui
    open_documents(ui)
    dialog = open_review(ui, "pending-report")
    state = ui.review_state("pending-report")
    approved = changed_record(
        ui, "pending-report", shared_approval_status="approved", document_actions=["download"],
        document_collaboration_actions=["inspect", "remove_share"],
    )
    next_state = changed_state(
        ui, "pending-report", relationship="approved", etag='"review:approved"',
        actions=["inspect", "remove_share"],
        recipients=[recipient("group-a", "Research group", "approved")],
    )
    reply = ui.queue_decision(
        "pending-report", "approve_share", expected_etag=state["etag"],
        response=collaboration_receipt("pending-report", "approve_share", "approved"),
        records=[approved], sharing_after=next_state,
    )
    perform(ui, reply, dialog.get_by_role("button", name="Approve access", exact=True).click)
    expect(dialog.get_by_text("Approved incoming share", exact=True)).to_be_visible()
    expect(dialog.get_by_role("button", name="Approve access", exact=True)).to_have_count(0)
    expect(dialog.get_by_role("button", name="Remove from group", exact=True)).to_be_enabled()
    dialog.get_by_role("button", name="Done", exact=True).click()
    row(ui, "pending-report").get_by_role("button", name="Details for pending-report.pdf", exact=True).click()
    unavailable(explorer(ui).get_by_role("complementary").get_by_role("button", name="Edit", exact=True))
    assert ui.record("pending-report")["owner_group_id"] == "origin"
    assert len(ui.operation_requests) == 1


@pytest.mark.parametrize("identifier,label,result", [
    ("pending-report", "Deny request", "denied"),
    ("shared-report", "Remove from group", "removed"),
])
def test_recipient_cleanup_confirms_access_removal_not_source_deletion(group_collaboration_ui, identifier, label, result):
    ui = group_collaboration_ui
    other_group = copy.deepcopy(ui.documents["group-b"])
    open_documents(ui)
    dialog = open_review(ui, identifier)
    expect(dialog).to_contain_text("Publishing group (origin)")
    confirmation = confirm(ui, label)
    expect(confirmation).to_contain_text("Research group")
    expect(confirmation).to_contain_text(re.compile(r"source owner", re.IGNORECASE))
    assert not ui.operation_requests
    reply = ui.queue_decision(
        identifier, "remove_share", expected_etag=ui.review_state(identifier)["etag"],
        response=collaboration_receipt(identifier, "remove_share", result), gone=True,
    )
    perform(ui, reply, confirmation.get_by_role("button", name=label, exact=True).click)
    expect(confirmation).to_have_count(0)
    assert_terminal_cleanup(ui, identifier)
    assert ui.documents["group-b"] == other_group
    assert ui.operation_requests[0].path == collaboration_path(identifier, "received-share")


def test_removed_recipient_repair_is_cleanup_only_after_document_404(group_collaboration_ui):
    ui = group_collaboration_ui
    identifier = "shared-report"
    original = copy.deepcopy(ui.record(identifier))
    other_group = copy.deepcopy(ui.documents["group-b"])
    state = ui.install_cleanup_repair(identifier)
    with (
        ui.page.expect_response(response_for("GET", f"/api/group_documents/{identifier}", 404)) as ordinary_read,
        ui.page.expect_response(response_for("GET", collaboration_path(identifier), 200)) as repair_read,
    ):
        ui.open(f"/groups/group-a/documents?document_id={identifier}")
    ordinary_read.value.finished()
    repair_read.value.finished()
    received = repair_read.value.json()
    assert received["group_id"] == "group-a" and received["document_id"] == identifier
    assert received["owner_group"] == {"id": "origin", "name": "Publishing group"}
    assert received["document_version"] == original["version"]
    assert received["relationship"] == "removed" and received["actions"] == ["inspect"]
    assert received["recipients"] == [] and received["publication"] is None
    assert not {"title", "abstract", "content", "document_actions", "file_name"} & set(received)
    dialog = review_dialog(ui)
    expect(dialog).to_contain_text("Research group (group-a)")
    expect(dialog).to_contain_text("Publishing group (origin)")
    expect(dialog).to_contain_text("Access removed; cleanup review only")
    expect(dialog.get_by_text(str(original["version"]), exact=True)).to_be_visible()
    expect(dialog.get_by_text(original["abstract"], exact=True)).to_have_count(0)
    expect(dialog.get_by_text(original["title"], exact=True)).to_have_count(0)
    expect(dialog.get_by_role("button", name="Retry access cleanup", exact=True)).to_have_count(0)
    expect(dialog.get_by_role("searchbox", name="Search recipient groups", exact=True)).to_have_count(0)
    for label in (
        "Share with group", "Stop sharing", "Approve access", "Approve publication",
        "Resume approved publication", "Reject publication", "Cancel publication request",
        "Chat", "Edit", "Tag", "Download", "Delete", "Extract",
    ):
        expect(dialog.get_by_role("button", name=label, exact=True)).to_have_count(0)
    expect(explorer(ui).locator('input[type="checkbox"]:checked')).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Details for Published report", exact=True)).to_have_count(0)
    assert not ui.operation_requests

    state["actions"] = ["inspect", "remove_share"]
    state["etag"] = '"cleanup:group-a:shared-report:outstanding"'
    refresh_review(ui, identifier)
    expect(dialog.get_by_role("button", name="Retry access cleanup", exact=True)).to_be_enabled()
    expect(dialog.get_by_role("button", name="Approve access", exact=True)).to_have_count(0)
    confirmation = confirm(ui, "Retry access cleanup")
    expect(confirmation).to_contain_text("cannot restore access")
    expect(confirmation).to_contain_text("Revision 3")
    assert not ui.operation_requests
    reply = ui.queue_decision(
        identifier, "remove_share", expected_etag=state["etag"],
        response=collaboration_receipt(identifier, "remove_share", "removed"), gone=True,
    )
    with ui.page.expect_response(response_for("GET", collaboration_path(identifier), 404)) as missing_evidence:
        perform(ui, reply, confirmation.get_by_role("button", name="Retry access cleanup", exact=True).click)
    missing_evidence.value.finished()
    expect(confirmation).to_have_count(0)
    assert_terminal_cleanup(ui, identifier)
    expect(dialog.get_by_role("button", name="Retry access cleanup", exact=True)).to_have_count(0)
    assert ui.documents["group-b"] == other_group
    assert (ui.operation_requests[0].method, ui.operation_requests[0].path, ui.operation_requests[0].body) == (
        "DELETE", collaboration_path(identifier, "received-share"), {"expected_etag": state["etag"]},
    )
    assert len(ui.operation_requests) == 1


def test_publication_approval_requires_publication_actions_and_does_not_release_screening(group_collaboration_ui):
    ui = group_collaboration_ui
    state = ui.review_state("pending-publication")
    state["publication"]["actions"] = []
    open_documents(ui)
    dialog = open_review(ui, "pending-publication")
    unavailable(dialog.get_by_role("button", name="Approve publication", exact=True))
    unavailable(dialog.get_by_role("button", name="Reject publication", exact=True))
    state["publication"]["actions"] = ["approve_artifact", "reject_artifact"]
    refresh_review(ui, "pending-publication")
    expect(dialog).to_contain_text("Publishing colleague")
    held = changed_record(
        ui, "pending-publication", generated_artifact_promotion_status="approved",
        content_screening={"state": "pending_scan", "available": False, "finding_count": 0},
        document_actions=[], document_collaboration_actions=["inspect"],
    )
    reply = ui.queue_decision(
        "pending-publication", "approve_artifact", expected_etag=state["etag"], status=202,
        response=collaboration_receipt("pending-publication", "approve_artifact", "approved", status="queued"),
        records=[held], sharing_after=changed_state(
            ui, "pending-publication", etag='"review:publication-queued"', actions=["inspect"],
            publication=publication(status="approved"),
        ),
    )
    perform(ui, reply, dialog.get_by_role("button", name="Approve publication", exact=True).click)
    expect(dialog.get_by_role("status").filter(has_text="Processing is queued, not complete")).to_be_visible()
    dialog.get_by_role("button", name="Done", exact=True).click()
    expect(row(ui, "pending-publication").get_by_role("checkbox")).to_be_disabled()
    assert ui.record("pending-publication")["content_screening"]["available"] is False
    assert not ui.record("pending-publication")["document_actions"]


def test_approval_failed_is_recorded_approval_with_deliberate_resume(group_collaboration_ui):
    ui = group_collaboration_ui
    ui.page.clock.install()
    open_documents(ui)
    dialog = open_review(ui, "pending-publication")
    initial = copy.deepcopy(ui.review_state("pending-publication"))
    failed_record = changed_record(
        ui, "pending-publication", generated_artifact_promotion_status="approval_failed",
        status="Publication handoff failed", document_collaboration_actions=["inspect", "approve_artifact"],
    )
    failed_state = changed_state(
        ui, "pending-publication", etag='"review:handoff-failed"', actions=["inspect", "approve_artifact"],
        publication=publication(status="approval_failed", actions=["approve_artifact"]),
    )
    partial = ui.queue_decision(
        "pending-publication", "approve_artifact", expected_etag=initial["etag"], status=207,
        response=collaboration_receipt(
            "pending-publication", "approve_artifact", "approval_failed", status="partial",
            errors=list(FAILED_HANDOFF_ERRORS),
        ),
        records=[failed_record], sharing_after=failed_state,
    )
    perform(ui, partial, dialog.get_by_role("button", name="Approve publication", exact=True).click)
    expect(dialog.get_by_role("alert").filter(has_text=PUBLICATION_HANDOFF_ERROR["message"])).to_be_visible()
    expect(dialog.get_by_text("Approval was recorded, but its processing handoff needs reconciliation.", exact=True)).to_be_visible()
    expect(dialog.get_by_role("button", name="Approve publication", exact=True)).to_have_count(0)
    expect(dialog.get_by_role("button", name="Resume approved publication", exact=True)).to_be_disabled()
    ui.page.clock.fast_forward(10000)
    assert len(ui.operation_requests) == 1
    refresh_review(ui, "pending-publication")
    retry = ui.queue_decision(
        "pending-publication", "approve_artifact", expected_etag=failed_state["etag"], status=202,
        response=collaboration_receipt("pending-publication", "approve_artifact", "approved", status="queued"),
        sharing_after={**failed_state, "etag": '"review:resumed"', "actions": ["inspect"], "publication": publication(status="approved")},
    )
    perform(ui, retry, dialog.get_by_role("button", name="Resume approved publication", exact=True).click)
    expect(dialog.get_by_role("status").filter(has_text="Processing is queued, not complete")).to_be_visible()
    assert [entry.body["expected_etag"] for entry in ui.operation_requests] == [initial["etag"], failed_state["etag"]]


def test_reject_publication_requires_confirmation_and_keeps_confirmed_cleanup(group_collaboration_ui):
    ui = group_collaboration_ui
    history = copy.deepcopy(ui.versions)
    open_documents(ui)
    open_review(ui, "pending-publication")
    confirmation = confirm(ui, "Reject publication")
    expect(confirmation).to_contain_text("not a screening approval")
    expect(confirmation).to_contain_text("Revision 3")
    assert not ui.operation_requests
    reply = ui.queue_decision(
        "pending-publication", "reject_artifact",
        expected_etag=ui.review_state("pending-publication")["etag"],
        response=collaboration_receipt("pending-publication", "reject_artifact", "rejected"), gone=True,
    )
    perform(ui, reply, confirmation.get_by_role("button", name="Reject publication", exact=True).click)
    expect(confirmation).to_have_count(0)
    assert_terminal_cleanup(ui, "pending-publication")
    assert ui.versions == history
    assert set(ui.operation_requests[0].body) == {"expected_etag"}


def test_stale_etag_keeps_target_and_requires_explicit_refresh_before_retry(group_collaboration_ui):
    ui = group_collaboration_ui
    ui.page.clock.install()
    open_documents(ui)
    dialog = open_review(ui)
    dialog.get_by_role("searchbox", name="Search recipient groups", exact=True).fill("Destination 05")
    target = choose_target(ui)
    initial = copy.deepcopy(ui.review_state())
    newer = changed_state(ui, etag='"review:concurrent-change"')
    rejected = ui.queue_decision(
        "same-document", "share", expected_etag=initial["etag"], target_group_id="target-05",
        response=STATE_CONFLICT,
        status=409, sharing_after=newer,
    )
    perform(ui, rejected, dialog.get_by_role("button", name="Share with group", exact=True).click)
    expect(dialog.get_by_role("alert")).to_contain_text("Your input is kept")
    expect(dialog.get_by_role("searchbox", name="Search recipient groups", exact=True)).to_have_value("Destination 05")
    expect(target).to_be_checked()
    expect(dialog.get_by_role("button", name="Share with group", exact=True)).to_be_disabled()
    ui.page.clock.fast_forward(10000)
    assert len(ui.operation_requests) == 1
    refresh_review(ui)
    expect(target).to_be_checked()
    retry = ui.queue_decision(
        "same-document", "share", expected_etag=newer["etag"], target_group_id="target-05",
        response=collaboration_receipt("same-document", "share", "not_approved", target_group_id="target-05"),
        sharing_after={**newer, "recipients": [*newer["recipients"], recipient("target-05", "Destination 05")]},
    )
    perform(ui, retry, dialog.get_by_role("button", name="Share with group", exact=True).click)
    expect(dialog.get_by_role("status").filter(has_text="Decision confirmed.")).to_be_visible()
    assert [entry.body["expected_etag"] for entry in ui.operation_requests] == [initial["etag"], newer["etag"]]


def test_partial_share_preserves_notice_and_does_not_replay_notifications(group_collaboration_ui):
    ui = group_collaboration_ui
    ui.page.clock.install()
    open_documents(ui)
    dialog = open_review(ui)
    choose_target(ui)
    initial = copy.deepcopy(ui.review_state())
    updated = changed_state(
        ui, etag='"review:partial-share"',
        recipients=[*initial["recipients"], recipient("target-05", "Destination 05")],
    )
    reply = ui.queue_decision(
        "same-document", "share", expected_etag=initial["etag"], target_group_id="target-05", status=207,
        response=collaboration_receipt(
            "same-document", "share", "not_approved", target_group_id="target-05", status="partial",
            errors=[effect_error("notifications")],
        ),
        sharing_after=updated,
    )
    perform(ui, reply, dialog.get_by_role("button", name="Share with group", exact=True).click)
    expect(dialog.get_by_role("alert").filter(has_text=effect_error("notifications")["message"])).to_be_visible()
    expect(dialog.get_by_role("button", name="Share with group", exact=True)).to_be_disabled()
    expect(dialog.get_by_role("radio", name="Select Destination 05", exact=True)).to_be_checked()
    ui.page.clock.fast_forward(10000)
    assert len(ui.operation_requests) == 1
    refresh_review(ui)
    expect(dialog.get_by_role("listitem").filter(has_text="target-05")).to_contain_text("Pending approval")
    expect(dialog.get_by_role("alert").filter(has_text="follow-up is required")).to_be_visible()
    assert len(ui.operation_requests) == 1


def test_malformed_success_receipts_never_clear_the_decision_draft(group_collaboration_ui):
    ui = group_collaboration_ui
    open_documents(ui)
    dialog = open_review(ui)
    choose_target(ui)
    valid = collaboration_receipt("same-document", "share", "not_approved", target_group_id="target-05")
    cases = (
        ("message-only", {"response": {"message": "Shared."}}),
        ("wrong-group", {"response": {**valid, "group_id": "group-b"}}),
        ("wrong-document", {"response": {**valid, "document_id": "notes-document"}}),
        ("wrong-target", {"response": {**valid, "target_group_id": "target-06"}}),
        ("wrong-action", {"response": {**valid, "action": "approve_share"}}),
        ("queued-share", {"response": {**valid, "status": "queued"}, "status": 202}),
        ("empty-partial", {"response": {**valid, "status": "partial"}, "status": 207}),
        ("html", {"response": b"<html><body>No decision receipt.</body></html>", "content_type": "text/html"}),
    )
    for name, outcome in cases:
        reply = ui.queue_decision(
            "same-document", "share", expected_etag=ui.review_state()["etag"],
            target_group_id="target-05", **outcome,
        )
        perform(ui, reply, dialog.get_by_role("button", name="Share with group", exact=True).click)
        expect(dialog.get_by_role("alert"), f"{name} must not be a successful sharing decision.").to_be_visible()
        expect(dialog.get_by_role("radio", name="Select Destination 05", exact=True)).to_be_checked()
        expect(dialog.get_by_role("button", name="Share with group", exact=True)).to_be_disabled()
        expect(dialog.get_by_text("Decision confirmed.", exact=True)).to_have_count(0)
        refresh_review(ui)
    assert len(ui.operation_requests) == len(cases)


def test_dirty_and_busy_review_preserves_input_and_never_aborts_a_write(group_collaboration_ui):
    ui = group_collaboration_ui
    ui.open("/groups/group-a/tags")
    ui.page.locator('a[href="/v2/groups/group-a/documents"]').first.click()
    expect(row(ui, "same-document")).to_be_visible()
    dialog = open_review(ui)
    search = dialog.get_by_role("searchbox", name="Search recipient groups", exact=True)
    search.fill("Keep this recipient search")
    expect(ui.page.get_by_role("combobox", name="Group workspace", exact=True)).to_be_disabled()
    choose_target(ui)
    ui.page.evaluate("history.back()")
    leave = ui.page.get_by_role("dialog", name="Discard unsaved changes?", exact=True)
    expect(leave).to_be_visible()
    leave.get_by_role("button", name="Keep editing", exact=True).click()
    expect(search).to_have_value("Keep this recipient search")
    reply = ui.queue_decision(
        "same-document", "share", expected_etag=ui.review_state()["etag"], target_group_id="target-05",
        response=collaboration_receipt("same-document", "share", "not_approved", target_group_id="target-05"),
        sharing_after=changed_state(ui, recipients=[*ui.review_state()["recipients"], recipient("target-05", "Destination 05")]),
    )
    ui.defer_next(reply.method, reply.path)
    with ui.page.expect_request(lambda request: request.method == reply.method and urlsplit(request.url).path == reply.path):
        dialog.get_by_role("button", name="Share with group", exact=True).click()
    expect(dialog.get_by_role("button", name="Done", exact=True)).to_be_disabled()
    ui.page.keyboard.press("Escape")
    expect(dialog).to_be_visible()
    ui.page.evaluate("history.back()")
    leave = ui.page.get_by_role("dialog", name="Your changes are still being saved", exact=True)
    expect(leave.get_by_role("button", name="Discard changes", exact=True)).to_be_disabled()
    leave.get_by_role("button", name="Keep editing", exact=True).click()
    assert len(ui.pending_responses) == 1 and not ui.completed_operations
    perform(ui, reply, ui.release_responses)
    expect(dialog.get_by_text("Decision confirmed.", exact=True)).to_be_visible()
    assert len(ui.completed_operations) == 1 and not ui.failed_operations


def test_refocus_pauses_decisions_without_losing_recipient_input(group_collaboration_ui):
    ui = group_collaboration_ui
    open_documents(ui)
    dialog = open_review(ui)
    search = dialog.get_by_role("searchbox", name="Search recipient groups", exact=True)
    search.fill("Draft recipient search")
    choose_target(ui)
    ui.reject_next("GET", GROUP_CONTEXT)
    with ui.page.expect_response(response_for("GET", GROUP_CONTEXT)) as paused:
        ui.page.evaluate("window.dispatchEvent(new Event('focus'))")
    paused.value.finished()
    expect(dialog.get_by_role("status").filter(has_text="decisions are paused")).to_be_visible()
    expect(search).to_have_value("Draft recipient search")
    expect(dialog.get_by_role("radio", name="Select Destination 05", exact=True)).to_be_checked()
    expect(dialog.get_by_role("button", name="Share with group", exact=True)).to_be_disabled()
    with ui.page.expect_response(response_for("GET", GROUP_CONTEXT)) as recovered:
        ui.page.evaluate("window.dispatchEvent(new Event('focus'))")
    recovered.value.finished()
    expect(dialog.get_by_role("button", name="Refresh review details", exact=True)).to_be_enabled()
    refresh_review(ui)
    expect(search).to_have_value("Draft recipient search")
    expect(dialog.get_by_role("radio", name="Select Destination 05", exact=True)).to_be_checked()
    expect(dialog.get_by_role("button", name="Share with group", exact=True)).to_be_enabled()
    assert not ui.operation_requests


def test_late_review_cannot_populate_another_group_with_the_same_document_id(group_collaboration_ui):
    ui = group_collaboration_ui
    open_documents(ui)
    old_path = collaboration_path("same-document")
    ui.defer_next("GET", old_path)
    with ui.page.expect_request(lambda request: request.method == "GET" and urlsplit(request.url).path == old_path):
        review_control(ui, "same-document").click()
    review_dialog(ui).get_by_role("button", name="Done", exact=True).click()
    ui.page.get_by_role("combobox", name="Group workspace", exact=True).select_option("group-b")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-b/documents")
    expect(row(ui, "same-document", "group-b")).to_be_visible()
    ui.review_state("same-document", "group-b")["recipients"] = [recipient("only-b", "Only group B recipient")]
    dialog = open_review(ui, "same-document", "group-b")
    expect(dialog).to_contain_text("Operations group (group-b)")
    assert len(ui.pending_responses) == 1
    ui.release_responses()
    expect(dialog).to_contain_text("Only group B recipient")
    expect(dialog.get_by_role("listitem").filter(has_text="target-01")).to_have_count(0)
    expect(dialog).not_to_contain_text("Research group (group-a)")
    assert not ui.operation_requests


def test_off_page_deep_link_reads_exact_document_and_never_executes_a_decision(group_collaboration_ui):
    ui = group_collaboration_ui
    ui.add_off_page_document()
    with ui.page.expect_response(response_for("GET", "/api/group_documents/off-page")) as detail:
        ui.open("/groups/group-a/documents?document_id=off-page")
    detail.value.finished()
    dialog = review_dialog(ui)
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("off-page.pdf")
    expect(dialog).to_contain_text("off-page")
    expect(dialog.get_by_text("7", exact=True)).to_be_visible()
    expect(dialog).not_to_contain_text("same-document.pdf")
    lists = [
        payload for url, payload in ui.responses
        if urlsplit(url).path == "/api/group_documents" and payload.get("page") == 1
    ]
    assert lists and all(record["id"] != "off-page" for record in lists[0]["documents"])
    assert any(
        entry.path == "/api/group_documents/off-page" and entry.query == {"group_id": ["group-a"]}
        for entry in ui.requests
    )
    assert not ui.operation_requests


def test_linked_document_is_visible_when_details_preference_is_closed_and_review_is_unsupported(group_collaboration_ui):
    ui = group_collaboration_ui
    ui.add_off_page_document()
    ui.groups["group-a"].pop("document_collaboration")
    ui.preferences["v2DocumentsPrefs"]["detailsPaneOpen"] = False
    ui.open("/groups/group-a/documents?document_id=off-page")
    expect(review_dialog(ui)).to_have_count(0)
    details = ui.page.get_by_role("complementary")
    expect(details.get_by_text("Exact off-page revision", exact=True)).to_be_visible()
    expect(details.get_by_text("off-page.pdf", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Toggle details pane", exact=True)).to_have_attribute("aria-pressed", "true")
    details.get_by_role("button", name="Hide details pane", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a/documents")
    assert not ui.operation_requests


def test_denied_or_gone_link_never_falls_back_and_group_switch_clears_target(group_collaboration_ui):
    ui = group_collaboration_ui
    ui.add_off_page_document()
    for status in (403, 404):
        ui.document_failures[("group-a", "off-page")] = status
        ui.reviews.pop(("group-a", "off-page"), None)
        ui.open("/groups/group-a/documents?document_id=off-page")
        expect(ui.page.get_by_role("alert").filter(
            has_text=re.compile(r"unavailable|no longer|not available", re.IGNORECASE),
        ).first).to_be_visible()
        assert not [
            entry for entry in ui.requests
            if entry.path == collaboration_path("same-document")
        ]
        assert not ui.operation_requests
    dialog = review_dialog(ui)
    if dialog.count():
        dialog.get_by_role("button", name="Done", exact=True).click()
    ui.page.get_by_role("combobox", name="Group workspace", exact=True).select_option("group-b")
    expect(row(ui, "same-document", "group-b")).to_be_visible()
    query = parse_qs(urlsplit(ui.page.url).query)
    assert "document_id" not in query
    assert not any(
        entry.path == "/api/group_documents/off-page" and entry.query == {"group_id": ["group-b"]}
        for entry in ui.requests
    )


@pytest.mark.parametrize("theme,width,height,label", [
    ("light", 1440, 900, "dl"), ("dark", 1440, 900, "dd"),
    ("light", 390, 844, "ml"), ("dark", 390, 844, "md"),
])
def test_review_layout_preserves_document_viewport_and_compact_dialog(group_collaboration_ui, theme, width, height, label):
    ui = group_collaboration_ui
    open_documents(ui, theme=theme, width=width, height=height)
    ui.assert_no_overflow()
    table = ui.page.get_by_role("table").locator("..").bounding_box()
    search = ui.page.get_by_role("searchbox", name="Search documents. Press Enter to search immediately.", exact=True).bounding_box()
    assert table and table["height"] >= 160, table
    assert search and search["width"] >= 180, search
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    ui.page.screenshot(path=str(SCREENSHOTS / f"{label}-list.png"), full_page=True)
    if width < 1280:
        row(ui, "same-document").get_by_role("checkbox").check()
        actions = explorer(ui).get_by_role("combobox", name="Document actions", exact=True)
        expect(actions.get_by_role("option", name="Review", exact=True)).to_have_attribute("value", "review")
        expect(actions.get_by_role("option", name="Review", exact=True)).to_be_enabled()
        with ui.page.expect_response(response_for("GET", collaboration_path("same-document"))) as reviewed:
            actions.select_option("review")
        reviewed.value.finished()
        dialog = review_dialog(ui)
        expect(dialog).to_be_visible()
    else:
        dialog = open_review(ui)
    expect(dialog).to_contain_text("Research group (group-a)")
    expect(dialog).to_contain_text("same-document")
    expect(dialog.get_by_role("radio", name="Select Destination 05", exact=True)).to_be_visible()
    choose_target(ui)
    expect(dialog.get_by_role("button", name="Share with group", exact=True)).to_be_enabled()
    bounds = dialog.locator(".glass-modal").bounding_box()
    assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width + 1, bounds
    assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= height + 1, bounds
    fits = dialog.locator(".glass-modal").evaluate("element => element.scrollWidth <= element.clientWidth + 1")
    assert fits is True
    ui.assert_no_overflow()
    ui.page.screenshot(path=str(SCREENSHOTS / f"{label}-review.png"), full_page=True)
    assert not ui.operation_requests
