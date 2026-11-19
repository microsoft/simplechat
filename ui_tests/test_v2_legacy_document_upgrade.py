# test_v2_legacy_document_upgrade.py
"""
Closed, real-SPA browser scenarios for the native legacy document upgrade.
Version: 0.261.448
Implemented in: 0.261.448

Documents stored before progress tracking have no percentage_complete, and every document list
says so in needs_legacy_update_check. The V2 Documents explorer shows an "Update older documents"
notice for all three scopes and runs the update itself, where it used to send group and public
users to a "Classic tools" button and offered personal users nothing at all.

Only HTTP responses are scripted. The group and public replies are the receipts the real routes
send (the builders in fixtures/group_document_management.py and public_document_management.py,
pinned to the routes by functional_tests/test_group_document_fixture_parity.py and
test_public_document_fixture_parity.py); the personal route's is the sentence it sends. Each
fixture's list says a document is old exactly when the server does, so a successful update is a
scripted receipt that also replaces the row with one that tracks progress. Components, stores,
focus, requests and layout run in the production SPA.

Rebuild the SPA (npx vite build in application\\v2_ui) before running this file; the fixtures refuse
a bundle older than its sources.
"""

import copy
import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.group_document_management import (
    DOCUMENT_OPERATION_FAILED_ERROR as GROUP_OPERATION_FAILED_ERROR,
    GroupDocumentManagementFixture, connect_options, group_management_ui,  # noqa: F401
    upgrade_failure as group_upgrade_failure, upgrade_legacy_result as group_upgrade_result,
)
from ui_tests.fixtures.public_document_management import (
    DOCUMENT_OPERATION_FAILED_ERROR as PUBLIC_OPERATION_FAILED_ERROR,
    PublicDocumentManagementFixture, public_management_ui,  # noqa: F401
    upgrade_failure as public_upgrade_failure, upgrade_legacy_result as public_upgrade_result,
)
from ui_tests.test_v2_personal_document_scope import PersonalDocumentFixture


pytestmark = pytest.mark.ui

GROUP_HEADING = "Update older group documents"
PUBLIC_HEADING = "Update older public workspace documents"
PERSONAL_HEADING = "Update older documents"
GROUP_PATH = "/api/groups/group-a/documents/upgrade_legacy"
PUBLIC_PATH = "/api/public-workspaces/pub-a/documents/upgrade_legacy"
PERSONAL_PATH = "/api/documents/upgrade_legacy"
STILL_OLD = "Some older documents still need updating"
WIDTHS = [("light", 1440, 900), ("dark", 1440, 900), ("light", 390, 844), ("dark", 390, 844)]


# --- Fixtures --------------------------------------------------------------------------------------

class LegacyGroupFixture(GroupDocumentManagementFixture):
    """The group management boundary with one document that predates progress tracking."""

    def __init__(self, page):
        super().__init__(page)
        for group_id in ("group-a", "group-b"):
            del self.record("notes-document", group_id)["percentage_complete"]


class LegacyPublicFixture(PublicDocumentManagementFixture):
    """The public management boundary with one document that predates progress tracking."""

    def __init__(self, page):
        super().__init__(page)
        for workspace_id in ("pub-a", "pub-b"):
            del self.record("notes-document", workspace_id)["percentage_complete"]


class LegacyPersonalFixture(PersonalDocumentFixture):
    """The personal document API with one document that predates progress tracking, and the
    personal upgrade route, which answers a sentence and upgrades every document it can."""

    def __init__(self, page):
        super().__init__(page)
        del self.documents["personal-beta"]["percentage_complete"]
        self.upgrade_replies = []

    def has_legacy_documents(self):
        return any("percentage_complete" not in row for row in self.documents.values())

    def reply_to_upgrade(self, payload, status=200):
        self.upgrade_replies.append((status, payload))

    def _json(self, route, payload, status=200):
        # The list route's own flag, which the base fixture's list leaves out.
        if isinstance(payload, dict) and {"documents", "total_count"} <= set(payload):
            payload = {**payload, "needs_legacy_update_check": self.has_legacy_documents()}
        super()._json(route, payload, status)

    def _dispatch(self, route, entry):
        if entry.path == PERSONAL_PATH:
            assert entry.method == "POST" and not entry.query and entry.body is None, entry
            assert self.upgrade_replies, f"Unplanned legacy document upgrade: {entry}"
            status, payload = self.upgrade_replies.pop(0)
            if status < 300:
                for row in self.documents.values():
                    row.setdefault("percentage_complete", 100)
            self._json(route, payload, status)
            return
        super()._dispatch(route, entry)

    def assert_clean(self):
        super().assert_clean()
        assert not self.upgrade_replies, f"Expected upgrades were not made: {self.upgrade_replies}"


@pytest.fixture
def legacy_group_ui(page):
    fixture = LegacyGroupFixture(page)
    yield fixture
    fixture.assert_clean()


@pytest.fixture
def legacy_public_ui(page):
    fixture = LegacyPublicFixture(page)
    yield fixture
    fixture.assert_clean()


@pytest.fixture
def legacy_personal_ui(page):
    fixture = LegacyPersonalFixture(page)
    yield fixture
    fixture.assert_clean()


# --- Helpers ---------------------------------------------------------------------------------------

def explorer(ui):
    return ui.page.get_by_role("group", name="Documents explorer", exact=True)


def notice(ui, heading):
    return ui.page.get_by_role("region", name=heading, exact=True)


def update_now(ui):
    return explorer(ui).get_by_role("button", name="Update now", exact=True)


def maybe_later(ui):
    return explorer(ui).get_by_role("button", name="Maybe later", exact=True)


def search_box(ui):
    return ui.page.get_by_role("searchbox", name="Search documents. Press Enter to search immediately.", exact=True)


def status_line(ui, text):
    return explorer(ui).get_by_role("status").filter(has_text=text)


def upgraded(record, **changes):
    """The row once the server has upgraded it: it tracks progress, so the list stops flagging it."""
    return {**copy.deepcopy(record), "percentage_complete": 100, **changes}


def response_for(method, path):
    return lambda response: response.request.method == method and urlsplit(response.url).path == path


def perform(ui, path, action, *, status=200, method="POST"):
    with ui.page.expect_response(response_for(method, path)) as pending:
        action()
    response = pending.value
    assert response.status == status
    response.finished()
    return response


def list_reads(ui, path):
    return [entry for entry in ui.requests if entry.path == path and entry.method == "GET"]


def assert_served(ui, path, expected):
    """Every list the server sent for this scope carried `needs_legacy_update_check` as `expected`."""
    flags = [
        payload["needs_legacy_update_check"] for url, payload in ui.responses
        if urlsplit(url).path == path and isinstance(payload, dict) and "needs_legacy_update_check" in payload
    ]
    assert flags and all(flag is expected for flag in flags), flags


def open_group(ui, **options):
    ui.open("/groups/group-a/documents", **options)
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_be_visible()
    expect(explorer(ui)).to_have_attribute("aria-busy", "false")
    expect(explorer(ui)).to_be_enabled()


def open_public(ui, **options):
    ui.open("/public/pub-a/documents", **options)
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_be_visible()
    expect(explorer(ui)).to_have_attribute("aria-busy", "false")
    expect(explorer(ui)).to_be_enabled()


def open_personal(ui, **options):
    ui.open("/workspace/documents", **options)
    expect(ui.page.get_by_role("checkbox", name="Select Personal Alpha", exact=True)).to_be_visible()
    expect(explorer(ui)).to_have_attribute("aria-busy", "false")
    expect(explorer(ui)).to_be_enabled()


def assert_no_classic(ui):
    expect(ui.page.get_by_role("button", name=re.compile("classic", re.IGNORECASE))).to_have_count(0)
    expect(ui.page.get_by_text("Classic tools", exact=True)).to_have_count(0)
    # The personal fixture has no classic pages to visit: any request it does not serve fails assert_clean.
    assert not getattr(ui, "classic_visits", []), ui.classic_visits


# --- Group -----------------------------------------------------------------------------------------

def test_a_group_manager_sees_the_notice_and_updates_in_place(legacy_group_ui):
    ui = legacy_group_ui
    open_group(ui)
    banner = notice(ui, GROUP_HEADING)
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("Some documents in this group were uploaded with an older version.")
    expect(update_now(ui)).to_be_enabled()
    expect(maybe_later(ui)).to_be_enabled()
    assert_no_classic(ui)
    assert_served(ui, "/api/group_documents", True)

    reads = len(list_reads(ui, "/api/group_documents"))
    reply = ui.queue_operation(
        "POST", "upgrade_legacy", response=group_upgrade_result(1),
        records=[upgraded(ui.record("notes-document"), title="Field notes (updated)")],
    )
    perform(ui, GROUP_PATH, update_now(ui).click)

    status = status_line(ui, reply.response["message"])
    expect(status).to_be_visible()
    expect(status).to_be_focused()
    expect(banner).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Details for Field notes (updated)", exact=True)).to_be_visible()
    expect(explorer(ui)).to_be_enabled()
    assert len(list_reads(ui, "/api/group_documents")) > reads, "A successful update must read the list again."
    assert [(entry.method, entry.path, entry.query, entry.body) for entry in ui.operation_requests] == [
        ("POST", GROUP_PATH, {}, None),
    ]
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/group_documents/upgrade_legacy")]
    assert_no_classic(ui)


def test_the_group_notice_never_shows_when_nothing_is_old(group_management_ui):
    ui = group_management_ui
    open_group(ui)
    expect(notice(ui, GROUP_HEADING)).to_have_count(0)
    expect(explorer(ui).get_by_role("button", name="Update now", exact=True)).to_have_count(0)
    assert_served(ui, "/api/group_documents", False)
    assert not ui.operation_requests
    assert_no_classic(ui)


@pytest.mark.parametrize("role, status, offered", [
    ("Owner", "active", True),
    ("Admin", "active", True),
    ("DocumentManager", "active", True),
    ("User", "active", False),
    ("Owner", "locked", False),
    ("DocumentManager", "upload_disabled", False),
])
def test_only_managers_of_an_active_group_are_offered_the_update(legacy_group_ui, role, status, offered):
    ui = legacy_group_ui
    ui.set_policy("group-a", role=role, status=status)
    open_group(ui)
    assert_served(ui, "/api/group_documents", True)  # the server still says documents are old
    if offered:
        expect(notice(ui, GROUP_HEADING)).to_be_visible()
    else:
        expect(notice(ui, GROUP_HEADING)).to_have_count(0)
        expect(explorer(ui).get_by_role("button", name="Update now", exact=True)).to_have_count(0)
    assert not ui.operation_requests
    assert_no_classic(ui)


def test_the_group_update_is_held_still_while_it_runs(legacy_group_ui):
    ui = legacy_group_ui
    open_group(ui)
    reply = ui.queue_operation(
        "POST", "upgrade_legacy", response=group_upgrade_result(1), records=[upgraded(ui.record("notes-document"))],
    )
    ui.defer_next("POST", reply.path)
    update_now(ui).click()

    banner = notice(ui, GROUP_HEADING)
    busy = explorer(ui).get_by_role("button", name="Updating...", exact=True)
    expect(busy).to_be_disabled()
    expect(banner.get_by_role("status")).to_contain_text("Updating older documents. This can take a few moments.")
    expect(search_box(ui)).to_be_disabled()
    expect(ui.page.get_by_role("checkbox", name="Select Research brief", exact=True)).to_be_disabled()
    expect(maybe_later(ui)).to_be_disabled()

    ui.release_responses()
    expect(banner).to_have_count(0)
    expect(explorer(ui)).to_be_enabled()
    expect(search_box(ui)).to_be_enabled()
    expect(status_line(ui, reply.response["message"])).to_be_visible()


def test_a_partial_update_names_the_document_and_keeps_the_notice(legacy_group_ui):
    ui = legacy_group_ui
    del ui.record("same-document")["percentage_complete"]
    failed_file = ui.record("notes-document")["file_name"]
    open_group(ui)
    banner = notice(ui, GROUP_HEADING)
    partial = ui.queue_operation(
        "POST", "upgrade_legacy", status=207,
        response=group_upgrade_result(1, errors=[group_upgrade_failure("notes-document", failed_file)]),
        records=[upgraded(ui.record("same-document"))],
    )
    # The keyboard runs the update, as a click does.
    update_now(ui).focus()
    perform(ui, GROUP_PATH, lambda: ui.page.keyboard.press("Enter"), status=207)

    alert = explorer(ui).get_by_role("alert")
    expect(alert).to_contain_text(partial.response["message"])
    expect(alert).to_contain_text(f"{failed_file}: Unable to update this document.")
    expect(banner).to_be_visible()
    expect(banner.get_by_role("status")).to_contain_text(STILL_OLD)
    expect(update_now(ui)).to_be_focused()
    expect(explorer(ui)).to_be_enabled()

    retry = ui.queue_operation(
        "POST", "upgrade_legacy", response=group_upgrade_result(1), records=[upgraded(ui.record("notes-document"))],
    )
    perform(ui, GROUP_PATH, update_now(ui).click)
    expect(banner).to_have_count(0)
    expect(explorer(ui).get_by_role("alert")).to_have_count(0)
    expect(status_line(ui, retry.response["message"])).to_be_visible()
    assert len(ui.operation_requests) == 2


def test_a_limited_update_says_more_remain_and_keeps_the_notice(legacy_group_ui):
    ui = legacy_group_ui
    del ui.record("same-document")["percentage_complete"]
    open_group(ui)
    limited = ui.queue_operation(
        "POST", "upgrade_legacy", response=group_upgrade_result(1, remaining=True),
        records=[upgraded(ui.record("same-document"))],
    )
    perform(ui, GROUP_PATH, update_now(ui).click)

    expect(status_line(ui, "More older documents remain; update again to continue.")).to_be_visible()
    assert "More older documents remain" in limited.response["message"]
    expect(explorer(ui).get_by_role("alert")).to_have_count(0)
    banner = notice(ui, GROUP_HEADING)
    expect(banner.get_by_role("status")).to_contain_text(STILL_OLD)
    expect(update_now(ui)).to_be_focused()


def test_a_failed_update_shows_the_servers_sentence_and_reads_the_list_again(legacy_group_ui):
    ui = legacy_group_ui
    open_group(ui)
    reads = len(list_reads(ui, "/api/group_documents"))
    ui.queue_operation("POST", "upgrade_legacy", status=500, response={"error": GROUP_OPERATION_FAILED_ERROR})
    perform(ui, GROUP_PATH, update_now(ui).click, status=500)

    alert = explorer(ui).get_by_role("alert")
    expect(alert).to_contain_text("The update did not finish. Some documents may already have been updated.")
    expect(alert).to_contain_text(GROUP_OPERATION_FAILED_ERROR)
    expect(notice(ui, GROUP_HEADING)).to_be_visible()
    expect(update_now(ui)).to_be_focused()
    expect(explorer(ui)).to_be_enabled()
    assert len(list_reads(ui, "/api/group_documents")) > reads, "A failure may have updated some documents."
    assert_no_classic(ui)


def test_maybe_later_hides_the_group_notice_for_this_visit_only(legacy_group_ui):
    ui = legacy_group_ui
    open_group(ui)
    banner = notice(ui, GROUP_HEADING)
    maybe_later(ui).click()
    expect(banner).to_have_count(0)
    expect(search_box(ui)).to_be_focused()

    # Reading the list again, as a search does, never brings it back.
    search_box(ui).fill("Field")
    search_box(ui).press("Enter")
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Details for Field notes", exact=True)).to_be_visible()
    expect(banner).to_have_count(0)
    search_box(ui).press("Escape")
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_be_visible()
    expect(banner).to_have_count(0)
    assert not ui.operation_requests, "Maybe later changes nothing on the server."

    # A new visit offers it again, because nothing was remembered.
    open_group(ui)
    expect(banner).to_be_visible()


@pytest.mark.parametrize("theme, width, height", WIDTHS)
def test_the_group_notice_fits_every_theme_and_width(legacy_group_ui, theme, width, height):
    ui = legacy_group_ui
    open_group(ui, theme=theme, width=width, height=height)
    banner = notice(ui, GROUP_HEADING)
    expect(banner).to_be_visible()
    for button in (update_now(ui), maybe_later(ui)):
        expect(button).to_be_visible()
        box = button.bounding_box()
        assert box and 0 <= box["x"] and box["x"] + box["width"] <= width, (button, box)
    box = banner.bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= width, box
    ui.assert_no_overflow()


# --- Public ----------------------------------------------------------------------------------------

def test_a_public_workspace_manager_sees_the_notice_and_updates_in_place(legacy_public_ui):
    ui = legacy_public_ui
    open_public(ui)
    banner = notice(ui, PUBLIC_HEADING)
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("Some documents in this public workspace were uploaded with an older version.")
    assert_no_classic(ui)
    assert_served(ui, "/api/public-workspaces/pub-a/documents", True)

    reads = len(list_reads(ui, "/api/public-workspaces/pub-a/documents"))
    reply = ui.queue_operation(
        "POST", "upgrade_legacy", response=public_upgrade_result(1),
        records=[upgraded(ui.record("notes-document"), title="Field notes (updated)")],
    )
    perform(ui, PUBLIC_PATH, update_now(ui).click)

    status = status_line(ui, reply.response["message"])
    expect(status).to_be_visible()
    expect(status).to_be_focused()
    expect(banner).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Details for Field notes (updated)", exact=True)).to_be_visible()
    expect(explorer(ui)).to_be_enabled()
    assert len(list_reads(ui, "/api/public-workspaces/pub-a/documents")) > reads
    assert [(entry.method, entry.path, entry.query, entry.body) for entry in ui.operation_requests] == [
        ("POST", PUBLIC_PATH, {}, None),
    ]
    assert_no_classic(ui)


@pytest.mark.parametrize("role, status, offered", [
    ("Owner", "active", True),
    ("DocumentManager", "active", True),
    ("User", "active", False),
    ("Owner", "locked", False),
    ("DocumentManager", "upload_disabled", False),
])
def test_only_managers_of_an_active_public_workspace_are_offered_the_update(legacy_public_ui, role, status, offered):
    ui = legacy_public_ui
    ui.set_policy("pub-a", role=role, status=status)
    open_public(ui)
    assert_served(ui, "/api/public-workspaces/pub-a/documents", True)
    expect(notice(ui, PUBLIC_HEADING)).to_have_count(1 if offered else 0)
    assert not ui.operation_requests
    assert_no_classic(ui)


def test_a_partial_public_update_names_the_document_and_a_failure_reads_the_list_again(legacy_public_ui):
    ui = legacy_public_ui
    failed_file = ui.record("notes-document")["file_name"]
    open_public(ui)
    banner = notice(ui, PUBLIC_HEADING)
    partial = ui.queue_operation(
        "POST", "upgrade_legacy", status=207,
        response=public_upgrade_result(0, errors=[public_upgrade_failure("notes-document", failed_file)]),
    )
    perform(ui, PUBLIC_PATH, update_now(ui).click, status=207)
    alert = explorer(ui).get_by_role("alert")
    expect(alert).to_contain_text(partial.response["message"])
    expect(alert).to_contain_text(f"{failed_file}: Unable to update this document.")
    expect(banner).to_be_visible()
    expect(update_now(ui)).to_be_focused()

    reads = len(list_reads(ui, "/api/public-workspaces/pub-a/documents"))
    ui.queue_operation("POST", "upgrade_legacy", status=500, response={"error": PUBLIC_OPERATION_FAILED_ERROR})
    perform(ui, PUBLIC_PATH, update_now(ui).click, status=500)
    alert = explorer(ui).get_by_role("alert")
    expect(alert).to_contain_text("The update did not finish. Some documents may already have been updated.")
    expect(alert).to_contain_text(PUBLIC_OPERATION_FAILED_ERROR)
    expect(banner).to_be_visible()
    assert len(list_reads(ui, "/api/public-workspaces/pub-a/documents")) > reads


@pytest.mark.parametrize("theme, width, height", [("light", 1440, 900), ("dark", 390, 844)])
def test_the_public_notice_fits_the_desktop_and_a_phone(legacy_public_ui, theme, width, height):
    ui = legacy_public_ui
    open_public(ui, theme=theme, width=width, height=height)
    expect(notice(ui, PUBLIC_HEADING)).to_be_visible()
    for button in (update_now(ui), maybe_later(ui)):
        expect(button).to_be_visible()
        box = button.bounding_box()
        assert box and 0 <= box["x"] and box["x"] + box["width"] <= width, (button, box)
    ui.assert_no_overflow()


# --- Personal --------------------------------------------------------------------------------------

def test_a_personal_user_sees_the_notice_and_updates_in_place(legacy_personal_ui):
    ui = legacy_personal_ui
    open_personal(ui)
    banner = notice(ui, PERSONAL_HEADING)
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("Some of your documents were uploaded with an older version.")
    assert_no_classic(ui)
    assert_served(ui, "/api/documents", True)

    message = "Upgraded 1 document(s) to the new format."
    ui.reply_to_upgrade({"message": message})
    reads = len(list_reads(ui, "/api/documents"))
    perform(ui, PERSONAL_PATH, update_now(ui).click)

    status = status_line(ui, message)
    expect(status).to_be_visible()
    expect(status).to_be_focused()
    expect(banner).to_have_count(0)
    expect(explorer(ui)).to_be_enabled()
    assert len(list_reads(ui, "/api/documents")) > reads
    assert [(entry.method, entry.path, entry.query, entry.body) for entry in ui.writes if entry.path == PERSONAL_PATH] == [
        ("POST", PERSONAL_PATH, {}, None),
    ]
    assert not [entry for entry in ui.requests if "group" in entry.path or "public" in entry.path]
    assert_no_classic(ui)


def test_a_failed_personal_update_shows_the_servers_sentence_and_can_be_retried(legacy_personal_ui):
    ui = legacy_personal_ui
    open_personal(ui)
    banner = notice(ui, PERSONAL_HEADING)
    sentence = "Your documents could not be updated right now."
    ui.reply_to_upgrade({"error": sentence}, status=500)
    reads = len(list_reads(ui, "/api/documents"))
    perform(ui, PERSONAL_PATH, update_now(ui).click, status=500)

    alert = explorer(ui).get_by_role("alert")
    expect(alert).to_contain_text("The update did not finish. Some documents may already have been updated.")
    expect(alert).to_contain_text(sentence)
    expect(banner).to_be_visible()
    expect(update_now(ui)).to_be_focused()
    assert len(list_reads(ui, "/api/documents")) > reads

    ui.reply_to_upgrade({"message": "Upgraded 1 document(s) to the new format."})
    perform(ui, PERSONAL_PATH, update_now(ui).click)
    expect(banner).to_have_count(0)
    expect(explorer(ui).get_by_role("alert")).to_have_count(0)


def test_the_personal_notice_never_shows_when_nothing_is_old(legacy_personal_ui):
    ui = legacy_personal_ui
    ui.documents["personal-beta"]["percentage_complete"] = 100
    open_personal(ui)
    expect(notice(ui, PERSONAL_HEADING)).to_have_count(0)
    assert_served(ui, "/api/documents", False)
    assert not [entry for entry in ui.writes if entry.path == PERSONAL_PATH]


def test_maybe_later_hides_the_personal_notice_for_this_visit_only(legacy_personal_ui):
    ui = legacy_personal_ui
    open_personal(ui)
    banner = notice(ui, PERSONAL_HEADING)
    maybe_later(ui).click()
    expect(banner).to_have_count(0)
    expect(search_box(ui)).to_be_focused()
    search_box(ui).fill("Beta")
    search_box(ui).press("Enter")
    expect(ui.page.get_by_role("checkbox", name="Select Personal Alpha", exact=True)).to_have_count(0)
    expect(banner).to_have_count(0)
    assert not [entry for entry in ui.writes if entry.path == PERSONAL_PATH]
    open_personal(ui)
    expect(banner).to_be_visible()


@pytest.mark.parametrize("theme, width, height", [("light", 390, 844), ("dark", 1440, 900)])
def test_the_personal_notice_fits_a_phone_and_the_desktop(legacy_personal_ui, theme, width, height):
    ui = legacy_personal_ui
    open_personal(ui, theme=theme, width=width, height=height)
    expect(notice(ui, PERSONAL_HEADING)).to_be_visible()
    for button in (update_now(ui), maybe_later(ui)):
        expect(button).to_be_visible()
        box = button.bounding_box()
        assert box and 0 <= box["x"] and box["x"] + box["width"] <= width, (button, box)
    ui.assert_no_overflow()
