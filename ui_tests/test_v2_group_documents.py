# test_v2_group_documents.py
"""
Production-SPA coverage for native read-only V2 group document browsing.
Version: 0.261.129
Implemented in: 0.261.128

Exercises real components, stores and navigation with closed synthetic HTTP.
The API fixture never permits personal document requests or document writes.
"""

import copy
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.group_documents import (
    NUMERIC_SORT_FIELDS, SORT_FIELDS, connect_options, group_documents_ui, restricted,  # noqa: F401
)
from ui_tests.fixtures.workspace_authoring import ORIGIN


pytestmark = pytest.mark.ui
SCREENSHOTS = Path(os.environ.get(
    "SIMPLECHAT_UI_SCREENSHOTS", str(Path(__file__).parent / "artifacts" / "group-documents"),
))


def explorer(ui):
    return ui.page.get_by_role("group", name="Documents explorer", exact=True)


def filters(ui):
    return ui.page.get_by_role("navigation", name="Document filters", exact=True)


def row(ui, name):
    return ui.page.get_by_role("row").filter(
        has=ui.page.get_by_role("button", name=f"Details for {name}", exact=True)
    )


def open_documents(ui, **options):
    ui.open("/groups/group-a/documents", **options)
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_be_visible()
    expect(explorer(ui)).to_have_attribute("aria-busy", "false")


def search(ui, text):
    control = ui.page.get_by_role("searchbox", name="Search documents. Press Enter to search immediately.", exact=True)
    control.fill(text)
    control.press("Enter")
    return control


def last_list(ui):
    return [entry for entry in ui.requests if entry.path == "/api/group_documents"][-1]


def assert_read_only(ui):
    for label in (
        "Upload", "Upload a document", "Tag", "Edit", "Extract", "Share",
        "Delete", "Download", "Save view", "Enhanced",
    ):
        expect(explorer(ui).get_by_role("button", name=label, exact=True)).to_have_count(0)
    expect(explorer(ui).locator('input[type="file"]')).to_have_count(0)
    expect(ui.page.get_by_text("Personal private view", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name=re.compile(r"^Remove tag "))).to_have_count(0)


@pytest.mark.parametrize("theme,width,height", [
    ("light", 1440, 900), ("dark", 1440, 900), ("light", 390, 844), ("dark", 390, 844),
])
def test_document_layout(group_documents_ui, theme, width, height):
    ui = group_documents_ui
    open_documents(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("heading", name="Documents", exact=True)).to_be_visible()
    assert_read_only(ui)
    ui.assert_no_overflow()
    bounds = explorer(ui).bounding_box()
    assert bounds and bounds["width"] >= 200 and bounds["height"] >= 180
    search_bounds = ui.page.get_by_role("searchbox", name="Search documents. Press Enter to search immediately.").bounding_box()
    table_viewport = ui.page.get_by_role("table").locator("..").bounding_box()
    assert search_bounds and search_bounds["width"] >= 180
    assert table_viewport and table_viewport["height"] >= 160
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    label = f'{"mobile" if width < 768 else "desktop"}-{theme}'
    ui.page.screenshot(path=str(SCREENSHOTS / f"{label}.png"), full_page=True)
    ui.page.get_by_role("button", name="Details for Research brief", exact=True).click()
    expect(ui.page.get_by_text("Approved metadata for Research brief.", exact=True)).to_be_visible()
    if width < 1280:
        expect(ui.page.get_by_role("dialog", name="Document details", exact=True)).to_be_visible()
    ui.assert_no_overflow()
    ui.page.screenshot(path=str(SCREENSHOTS / f"{label}-details.png"), full_page=True)


def test_queries_use_whole_sets(group_documents_ui):
    ui = group_documents_ui
    open_documents(ui)
    total = len(ui.visible("group-a"))
    expect(explorer(ui).get_by_text(f"1\u201325 of {total}", exact=True)).to_be_visible()
    ui.page.get_by_role("navigation", name="Pagination").get_by_role("button", name="Next", exact=True).click()
    expect(explorer(ui).get_by_text(f"26\u201350 of {total}", exact=True)).to_be_visible()
    assert last_list(ui).query["page"] == ["2"]
    ui.page.get_by_label("Documents per page", exact=True).select_option("50")
    expect(explorer(ui).get_by_text(f"1\u201350 of {total}", exact=True)).to_be_visible()
    assert last_list(ui).query["page_size"] == ["50"]
    counts = ui.facets("group-a")
    finance = filters(ui).get_by_role("button", name=re.compile(r"^Finance"))
    expect(finance).to_contain_text(str(counts["by_tag"]["Finance"]))
    finance.click()
    filters(ui).get_by_role("button", name=re.compile(r"^Team")).click(modifiers=["Control"])
    filters(ui).get_by_role("button", name=re.compile(r"^Internal")).click()
    search(ui, "Team research 57")
    expect(ui.page.get_by_role("button", name="Details for Team research 57", exact=True)).to_be_visible()
    expect(explorer(ui).get_by_text("1\u20131 of 1", exact=True)).to_be_visible()
    query = last_list(ui).query
    assert query["search"] == ["Team research 57"]
    assert query["tags"] == ["Finance,Team"]
    assert query["classification"] == ["Internal"]
    assert query["page"] == ["1"]
    expect(finance).to_contain_text(str(counts["by_tag"]["Finance"]))
    expect(filters(ui).get_by_role("button", name=re.compile(r"^All documents"))).to_contain_text(str(total))
    assert all(
        entry.query == {"group_id": ["group-a"]}
        for entry in ui.requests if entry.path in ("/api/group_documents/tags", "/api/group_documents/facets")
    )
    assert_read_only(ui)


def test_all_sort_controls(group_documents_ui):
    ui = group_documents_ui
    open_documents(ui)
    for field in SORT_FIELDS:
        ui.page.get_by_label("Sort documents", exact=True).select_option(field)
        for direction in ("asc", "desc"):
            control = ui.page.get_by_role("button", name=f"Sort {'ascending' if direction == 'asc' else 'descending'}", exact=True)
            if control.count():
                control.click()
            expect(explorer(ui)).to_have_attribute("aria-busy", "false")
            ordered = sorted(
                ui.visible("group-a"),
                key=lambda item: float(item.get(field) or 0) if field in NUMERIC_SORT_FIELDS
                    else str(item.get(field) or "").casefold(),
                reverse=direction == "desc",
            )
            first = ordered[0]
            name = first.get("title") or first["file_name"]
            expect(ui.page.get_by_role("row").nth(1).get_by_role("button", name=f"Details for {name}", exact=True)).to_be_visible()
            assert last_list(ui).query["sort_by"] == [field]
            assert last_list(ui).query["sort_order"] == [direction]


def test_all_places(group_documents_ui):
    ui = group_documents_ui
    open_documents(ui)
    for place, label, count_key in (
        ("recent", "Recent", "recent"), ("shared", "Shared with this group", "shared_with_me"),
        ("processing", "Processing", "processing"), ("errors", "Needs attention", "errors"),
        ("untagged", "Untagged", "untagged"), ("all", "All documents", "total"),
    ):
        filters(ui).get_by_role("button", name=re.compile(rf"^{label}")).click()
        expect(explorer(ui)).to_have_attribute("aria-busy", "false")
        count = ui.facets("group-a")[count_key]
        expect(explorer(ui).get_by_text(f"1\u2013{min(25, count)} of {count}", exact=True)).to_be_visible()
        assert last_list(ui).query.get("place") == (None if place == "all" else [place])
        assert last_list(ui).query["group_id"] == ["group-a"]


def test_restricted_selection_and_writes(group_documents_ui):
    ui = group_documents_ui
    open_documents(ui)
    for name in ("pending-report.pdf", "held-report.pdf", "held-share.pdf"):
        expect(row(ui, name).get_by_role("checkbox")).to_be_disabled()
        expect(row(ui, name)).to_have_attribute("draggable", "false")
    row(ui, "Research brief").get_by_role("checkbox").check()
    expect(ui.page.get_by_text("Approved metadata for Research brief.", exact=True)).to_be_visible()
    row(ui, "pending-report.pdf").click()
    expect(ui.page.get_by_text("This shared document is awaiting approval and cannot be selected for chat.", exact=True)).to_be_visible()
    expect(row(ui, "Research brief").get_by_role("checkbox")).not_to_be_checked()
    ui.page.get_by_role("button", name="Details for Research brief", exact=True).focus()
    ui.page.keyboard.press("Control+a")
    expect(row(ui, "Research brief").get_by_role("checkbox")).to_be_checked()
    expect(row(ui, "Published report").get_by_role("checkbox")).to_be_checked()
    for name in ("pending-report.pdf", "held-report.pdf", "held-share.pdf"):
        expect(row(ui, name).get_by_role("checkbox")).not_to_be_checked()
    ui.page.keyboard.press("Escape")
    row(ui, "Research brief").click()
    row(ui, "Import needs attention").click(modifiers=["Shift"])
    expect(row(ui, "Published report").get_by_role("checkbox")).to_be_checked()
    expect(row(ui, "pending-report.pdf").get_by_role("checkbox")).not_to_be_checked()
    assert_read_only(ui)
    filters(ui).get_by_role("button", name=re.compile(r"^Finance")).evaluate("""element => {
        const dataTransfer = new DataTransfer();
        dataTransfer.setData('application/x-simplechat-documents', JSON.stringify(['same-document']));
        element.dispatchEvent(new DragEvent('drop', { bubbles: true, dataTransfer }));
    }""")
    ui.page.get_by_role("table").evaluate("""element => {
        const dataTransfer = new DataTransfer();
        dataTransfer.items.add(new File(['fixture'], 'blocked-upload.txt', {type: 'text/plain'}));
        element.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer }));
    }""")
    expect(ui.page.get_by_text("Document management is available in the classic group workspace.", exact=True)).to_be_visible()
    assert not [entry for entry in ui.writes if entry.path.startswith("/api/group_documents")]


def test_details_versions_and_screening(group_documents_ui):
    ui = group_documents_ui
    open_documents(ui)
    ui.detail_overrides[("group-a", "same-document")] = {
        **copy.deepcopy(ui.documents["group-a"][0]), "abstract": "Fresh group metadata.",
    }
    ui.page.get_by_role("button", name="Details for Research brief", exact=True).click()
    expect(ui.page.get_by_text("Fresh group metadata.", exact=True)).to_be_visible()
    ui.page.get_by_role("button", name="Refresh document details", exact=True).click()
    expect(ui.page.get_by_text("Refreshing document details...", exact=True)).to_have_count(0)
    ui.page.get_by_role("button", name="Version history", exact=True).click()
    expect(ui.page.get_by_text("Version 3 (current)", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Earlier research brief", exact=True)).to_be_visible()
    ui.page.get_by_role("button", name="Details for Published report", exact=True).click()
    expect(ui.page.get_by_text("Version 3 (current)", exact=True)).to_have_count(0)
    ui.page.get_by_role("button", name="Version history", exact=True).click()
    expect(ui.page.get_by_text("Version 1", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("pending-version.pdf", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Restricted earlier share", exact=True)).to_have_count(0)
    ui.page.get_by_role("button", name="Details for held-report.pdf", exact=True).click()
    expect(ui.page.get_by_text("Held until an authorized reviewer makes an explicit decision.", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Restricted held title", exact=True)).to_have_count(0)
    assert_read_only(ui)
    reads = [entry for entry in ui.requests if entry.path.startswith("/api/group_documents/")]
    assert all(entry.query == {"group_id": ["group-a"]} for entry in reads)
    assert any(entry.path.endswith("/same-document/versions") for entry in reads)
    assert not [entry for entry in ui.requests if "screening/policy" in entry.path]


def test_late_query_is_discarded(group_documents_ui):
    ui = group_documents_ui
    open_documents(ui)
    ui.defer_next("GET", "/api/group_documents")
    search(ui, "no earlier match")
    expect(explorer(ui)).to_have_attribute("aria-busy", "true")
    search(ui, "Team research 57")
    expect(ui.page.get_by_role("button", name="Details for Team research 57", exact=True)).to_be_visible()
    assert len(ui.pending_responses) == 1
    ui.release_responses()
    expect(ui.page.get_by_role("button", name="Details for Team research 57", exact=True)).to_be_visible()
    expect(explorer(ui).get_by_text("No documents match these filters", exact=True)).to_have_count(0)


@pytest.mark.parametrize("path,action", [
    ("/api/group_documents", "list"),
    ("/api/group_documents/tags", "sidebar"),
    ("/api/group_documents/facets", "sidebar"),
    ("/api/group_documents/same-document", "detail"),
    ("/api/group_documents/same-document/versions", "versions"),
])
def test_late_scope_reads(group_documents_ui, path, action):
    ui = group_documents_ui
    open_documents(ui)
    if action == "versions":
        ui.page.get_by_role("button", name="Details for Research brief", exact=True).click()
        expect(ui.page.get_by_text("Approved metadata for Research brief.", exact=True)).to_be_visible()
    ui.defer_next("GET", path)
    with ui.page.expect_request(lambda request: urlsplit(request.url).path == path):
        if action == "list":
            search(ui, "Research brief")
        elif action == "sidebar":
            ui.page.evaluate("window.dispatchEvent(new Event('focus'))")
        elif action == "detail":
            ui.page.get_by_role("button", name="Details for Research brief", exact=True).click()
        else:
            ui.page.get_by_role("button", name="Version history", exact=True).click()
    ui.page.get_by_role("combobox", name="Group workspace", exact=True).select_option("group-b")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-b/documents")
    expect(ui.page.get_by_role("button", name="Details for Read-only brief", exact=True)).to_be_visible()
    assert ui.pending_responses
    ui.release_responses()
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Details for Read-only brief", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Earlier research brief", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("searchbox", name="Search documents. Press Enter to search immediately.")).to_have_value("")
    expect(explorer(ui).locator('input[type="checkbox"]:checked')).to_have_count(0)
    expect(filters(ui).get_by_role("button", name=re.compile(r"^All documents"))).to_contain_text(str(len(ui.visible("group-b"))))
    assert last_list(ui).query["group_id"] == ["group-b"]


def test_late_progress_is_discarded(group_documents_ui):
    ui = group_documents_ui
    ui.page.clock.install()
    open_documents(ui)
    ui.defer_next("GET", "/api/group_documents/processing-report")
    with ui.page.expect_request(lambda request: urlsplit(request.url).path == "/api/group_documents/processing-report"):
        ui.page.clock.fast_forward(5000)
    ui.page.get_by_role("combobox", name="Group workspace", exact=True).select_option("group-b")
    expect(ui.page.get_by_role("button", name="Details for Read-only brief", exact=True)).to_be_visible()
    ui.detail_overrides[("group-a", "processing-report")] = {
        **ui.documents["group-a"][5], "title": "Late group A progress",
    }
    ui.release_responses()
    expect(ui.page.get_by_role("button", name="Details for Late group A progress", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Details for Indexing source", exact=True)).to_be_visible()


def test_poll_replaces_restricted_metadata(group_documents_ui):
    ui = group_documents_ui
    ui.page.clock.install()
    open_documents(ui)
    with ui.page.expect_response(
        lambda response: urlsplit(response.url).path == "/api/group_documents/processing-report"
    ) as initial_detail:
        row(ui, "Indexing source").get_by_role("checkbox").check()
    initial_detail.value.finished()
    expect(ui.page.get_by_role("button", name="Refresh document details", exact=True)).to_be_enabled()
    expect(ui.page.get_by_text("Approved metadata for Indexing source.", exact=True)).to_be_visible()
    held = restricted({
        **ui.documents["group-a"][5], "percentage_complete": 100,
        "content_screening": {"state": "pending_review", "available": False, "finding_count": 1},
    })
    ui.detail_overrides[("group-a", "processing-report")] = held
    with ui.page.expect_response(
        lambda response: urlsplit(response.url).path == "/api/group_documents/processing-report"
    ) as polled:
        ui.page.clock.fast_forward(5000)
    polled.value.finished()
    expect(row(ui, "processing-report.pdf").get_by_role("checkbox")).to_be_disabled()
    expect(ui.page.get_by_text("Approved metadata for Indexing source.", exact=True)).to_have_count(0)
    expect(explorer(ui).locator('input[type="checkbox"]:checked')).to_have_count(0)
    assert any(
        entry.path == "/api/group_documents/processing-report" and entry.query == {"group_id": ["group-a"]}
        for entry in ui.requests
    )


def test_access_revalidation(group_documents_ui):
    ui = group_documents_ui
    open_documents(ui)
    row(ui, "Research brief").get_by_role("checkbox").check()
    ui.reject_next("GET", "/api/v2/workspaces/group/group-a")
    ui.page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(ui.page.get_by_role("alert")).to_contain_text("Your changes are kept")
    expect(explorer(ui).get_by_role("button", name="Chat", exact=True).first).to_be_disabled()
    expect(row(ui, "Research brief").get_by_role("checkbox")).to_be_disabled()
    ui.page.get_by_role("button", name="Retry workspace details", exact=True).click()
    expect(row(ui, "Research brief").get_by_role("checkbox")).to_be_enabled()
    ui.denied_groups.add("group-a")
    ui.page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(ui.page.get_by_role("alert")).to_contain_text("permission")
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_have_count(0)


def test_lifecycle_and_chat_ceiling(group_documents_ui):
    ui = group_documents_ui
    ui.groups["group-a"]["status"] = "locked"
    ui.groups["group-a"]["document_permissions"]["can_chat"] = False
    open_documents(ui)
    expect(row(ui, "Research brief").get_by_role("checkbox")).to_be_disabled()
    row(ui, "Research brief").click()
    expect(ui.page.get_by_text("Chat is not currently available for this group.", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Approved metadata for Research brief.", exact=True)).to_be_visible()
    assert_read_only(ui)
    ui.groups["group-a"]["sections"]["documents"].update({"enabled": False, "can_manage": False, "reason": "This group is inactive."})
    ui.groups["group-a"]["document_permissions"]["can_view"] = False
    reads = len([entry for entry in ui.requests if entry.path.startswith("/api/group_documents")])
    ui.page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(ui.page.get_by_text("This group is inactive.", exact=True)).to_be_visible()
    assert len([entry for entry in ui.requests if entry.path.startswith("/api/group_documents")]) == reads


def test_query_capabilities(group_documents_ui):
    ui = group_documents_ui
    ui.groups["group-a"]["document_queries"] = {"sort_fields": ["file_name"], "facets": False, "places": False}
    ui.open("/groups/group-a/documents")
    expect(explorer(ui)).to_have_attribute("aria-busy", "false")
    expect(ui.page.get_by_label("Sort documents")).to_have_value("file_name")
    expect(ui.page.get_by_label("Sort documents").get_by_role("option")).to_have_count(1)
    expect(filters(ui).get_by_role("button", name=re.compile(r"^Recent|^Shared with this group|^Processing"))).to_have_count(0)
    expect(ui.page.get_by_role("columnheader", name="Modified", exact=True).get_by_role("button")).to_have_count(0)
    assert not [entry for entry in ui.requests if entry.path == "/api/group_documents/facets"]
    assert last_list(ui).query["sort_by"] == ["file_name"]


def test_errors_are_not_empty(group_documents_ui):
    ui = group_documents_ui
    open_documents(ui)
    ui.reject_next("GET", "/api/group_documents")
    search(ui, "Team")
    expect(ui.page.get_by_role("alert")).to_contain_text("Documents could not be loaded")
    expect(ui.page.get_by_text("No documents yet", exact=True)).to_have_count(0)
    expect(ui.page.get_by_text("No documents", exact=True)).to_have_count(0)
    ui.page.get_by_role("button", name="Retry documents", exact=True).click()
    expect(explorer(ui)).to_have_attribute("aria-busy", "false")
    expect(ui.page.get_by_role("alert")).to_have_count(0)
    search(ui, "")
    ui.reject_next("GET", "/api/group_documents/same-document/versions")
    ui.page.get_by_role("button", name="Details for Research brief", exact=True).click()
    ui.page.get_by_role("button", name="Version history", exact=True).click()
    expect(ui.page.get_by_role("button", name="Retry version history", exact=True)).to_be_visible()
    ui.page.get_by_role("button", name="Retry version history", exact=True).click()
    expect(ui.page.get_by_text("Earlier research brief", exact=True)).to_be_visible()


def test_facets_failure_is_visible(group_documents_ui):
    ui = group_documents_ui
    ui.reject_next("GET", "/api/group_documents/facets")
    open_documents(ui)
    expect(ui.page.get_by_role("button", name="Retry document updates", exact=True)).to_be_visible()
    ui.page.get_by_role("button", name="Retry document updates", exact=True).click()
    expect(ui.page.get_by_role("alert")).to_have_count(0)
    expect(filters(ui).get_by_role("button", name=re.compile(r"^All documents"))).to_contain_text("65")

def test_detail_failure_hides_cached_metadata(group_documents_ui):
    ui = group_documents_ui
    open_documents(ui)
    ui.reject_next("GET", "/api/group_documents/same-document", status=403)
    ui.page.get_by_role("button", name="Details for Research brief", exact=True).click()
    expect(ui.page.get_by_role("button", name="Retry document details", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Approved metadata for Research brief.", exact=True)).to_have_count(0)
    expect(explorer(ui).get_by_role("button", name="Chat", exact=True).first).to_be_disabled()
    ui.page.get_by_role("button", name="Retry document details", exact=True).click()
    expect(ui.page.get_by_text("Approved metadata for Research brief.", exact=True)).to_be_visible()


def test_empty_group_stays_read_only(group_documents_ui):
    ui = group_documents_ui
    ui.documents["group-a"] = []
    ui.open("/groups/group-a/documents")
    expect(ui.page.get_by_text("No documents yet", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Manage files in classic", exact=True)).to_be_visible()
    expect(explorer(ui).get_by_role("button", name="Chat", exact=True)).to_be_disabled()
    assert_read_only(ui)


def test_chat_rechecks_screening(group_documents_ui):
    ui = group_documents_ui
    open_documents(ui)
    row(ui, "Research brief").get_by_role("checkbox").check()
    expect(ui.page.get_by_text("Approved metadata for Research brief.", exact=True)).to_be_visible()
    ui.detail_overrides[("group-a", "same-document")] = restricted({
        **ui.documents["group-a"][0],
        "content_screening": {"state": "pending_review", "available": False, "finding_count": 1},
    })
    explorer(ui).get_by_role("button", name="Chat", exact=True).first.click()
    expect(ui.page.get_by_text(
        "Held sources cannot be selected for chat. An authorized reviewer must resolve the hold in Content review.", exact=True,
    )).to_be_visible()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a/documents")
    expect(row(ui, "same-document.pdf").get_by_role("checkbox")).to_be_disabled()


def test_chat_handoff_keeps_source_identity(group_documents_ui):
    ui = group_documents_ui
    open_documents(ui)
    filters(ui).get_by_role("button", name=re.compile(r"^Finance")).click()
    row(ui, "Published report").get_by_role("checkbox").check()
    expect(ui.page.get_by_text("Approved metadata for Published report.", exact=True)).to_be_visible()
    ui.active_group = "group-b"
    explorer(ui).get_by_role("button", name="Chat", exact=True).first.click()
    expect(ui.page.get_by_role("button", name="Remove Published report", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Remove Finance", exact=True)).to_be_visible()
    ui.allow_chat_writes = True
    ui.page.locator("#composer-input").fill("Review the selected group report.")
    with ui.page.expect_request(lambda request: request.method == "POST" and urlsplit(request.url).path == "/api/chat/stream") as sent:
        ui.page.get_by_role("button", name="Send message", exact=True).click()
    body = sent.value.post_data_json
    assert body["selected_document_ids"] == ["shared-report"]
    assert body["tags"] == ["Finance"]
    assert "group-a" in body["active_group_ids"]
    assert body["chat_type"] == "user" and body["doc_scope"] == "all"
    expect(ui.page.get_by_text("Workspace review response.", exact=True)).to_be_visible()
    assert ui.active_group == "group-b"
    assert not [entry for entry in ui.writes if entry.path == "/api/groups/setActive"]


def test_legacy_link_and_lock_error(group_documents_ui):
    ui = group_documents_ui
    ui.allow_chat_writes = True
    ui.lock_chat = True
    ui.conversations[0]["scope_locked"] = True
    ui.open("/chat?conversationId=existing-workspace-chat&doc_scope=group&group_id=group-a&document_ids=shared-report")
    expect(ui.page.get_by_text("An earlier conversation.", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Remove Published report", exact=True)).to_be_visible()
    ui.page.locator("#composer-input").fill("Respect the existing conversation scope.")
    ui.page.get_by_role("button", name="Send message", exact=True).click()
    expect(ui.page.get_by_text("Context scope is locked for this conversation.", exact=True)).to_be_visible()
    requests = [entry for entry in ui.writes if entry.path == "/api/chat/stream"]
    assert requests[-1].body["conversation_id"] == "existing-workspace-chat"
    assert not [entry for entry in ui.writes if entry.path == "/api/create_conversation"]
    assert not [entry for entry in ui.writes if "scope" in entry.path or "metadata" in entry.path]
    assert any(
        entry.path == "/api/group_documents/shared-report" and entry.query == {"group_id": ["group-a"]}
        for entry in ui.requests
    )


def test_classic_handoff_and_tags(group_documents_ui):
    ui = group_documents_ui
    open_documents(ui)
    ui.active_group = "group-b"
    ui.page.get_by_role("button", name="Open classic group workspace", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/group_workspaces")
    assert ui.classic_visits == [("/group_workspaces", "group-a")]
    ui.open("/groups/group-a/tags")
    expect(ui.page.get_by_role("heading", name="Tags", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Tag management is not available with this workspace's current permissions.", exact=False)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Create", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Open classic group workspace", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("searchbox", name="Search documents. Press Enter to search immediately.", exact=True)).to_have_count(0)


def test_group_document_text_is_inert(group_documents_ui):
    ui = group_documents_ui
    payload = '<img src=x onerror="window.documentTextExecuted=true">'
    ui.documents["group-a"][0].update({"title": payload, "abstract": payload})
    ui.open("/groups/group-a/documents")
    ui.page.get_by_role("button", name=f"Details for {payload}", exact=True).click()
    expect(ui.page.get_by_role("complementary").get_by_text(payload, exact=True)).to_have_count(2)
    executed = ui.page.evaluate("window.documentTextExecuted === true")
    assert executed is False
