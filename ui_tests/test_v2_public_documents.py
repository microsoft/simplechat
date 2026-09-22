# test_v2_public_documents.py
"""
Production-SPA coverage for native read-only V2 public workspace document browsing.
Version: 0.261.132
Implemented in: 0.261.132

Exercises real components, stores and navigation with closed synthetic HTTP.
The API fixture never permits personal or group document requests, and never
permits a document write: the public surface is strictly read-only. Every read
carries its workspace id in the request path, so selecting a public workspace can
never leak into a personal or group read.
"""

import copy
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.public_documents import (
    NUMERIC_SORT_FIELDS, SORT_FIELDS, connect_options, public_documents_ui,  # noqa: F401
)
from ui_tests.fixtures.workspace_authoring import ORIGIN


pytestmark = pytest.mark.ui
SCREENSHOTS = Path(os.environ.get(
    "SIMPLECHAT_UI_SCREENSHOTS", str(Path(__file__).parent / "artifacts" / "public-documents"),
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
    ui.open("/public/pub-a/documents", **options)
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_be_visible()
    expect(explorer(ui)).to_have_attribute("aria-busy", "false")


def search(ui, text):
    control = ui.page.get_by_role("searchbox", name="Search documents. Press Enter to search immediately.", exact=True)
    control.fill(text)
    control.press("Enter")
    return control


def list_requests(ui):
    return [
        entry for entry in ui.requests
        if entry.path.startswith("/api/public-workspaces/") and entry.path.endswith("/documents")
    ]


def last_list(ui):
    return list_requests(ui)[-1]


def assert_read_only(ui):
    for label in (
        "Upload", "Upload a document", "Tag", "Edit", "Extract", "Share",
        "Delete", "Download", "Save view", "Enhanced",
    ):
        expect(explorer(ui).get_by_role("button", name=label, exact=True)).to_have_count(0)
    expect(explorer(ui).locator('input[type="file"]')).to_have_count(0)
    expect(ui.page.get_by_role("button", name=re.compile(r"^Remove tag "))).to_have_count(0)


@pytest.mark.parametrize("theme,width,height", [
    ("light", 1440, 900), ("dark", 1440, 900), ("light", 390, 844), ("dark", 390, 844),
])
def test_document_layout(public_documents_ui, theme, width, height):
    ui = public_documents_ui
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
    expect(ui.page.get_by_text("Published metadata for Research brief.", exact=True)).to_be_visible()
    if width < 1280:
        expect(ui.page.get_by_role("dialog", name="Document details", exact=True)).to_be_visible()
    ui.assert_no_overflow()
    ui.page.screenshot(path=str(SCREENSHOTS / f"{label}-details.png"), full_page=True)


def test_queries_use_whole_sets(public_documents_ui):
    ui = public_documents_ui
    open_documents(ui)
    total = len(ui.visible("pub-a"))
    expect(explorer(ui).get_by_text(f"1\u201325 of {total}", exact=True)).to_be_visible()
    ui.page.get_by_role("navigation", name="Pagination").get_by_role("button", name="Next", exact=True).click()
    expect(explorer(ui).get_by_text(f"26\u201350 of {total}", exact=True)).to_be_visible()
    assert last_list(ui).query["page"] == ["2"]
    ui.page.get_by_label("Documents per page", exact=True).select_option("50")
    expect(explorer(ui).get_by_text(f"1\u201350 of {total}", exact=True)).to_be_visible()
    assert last_list(ui).query["page_size"] == ["50"]
    counts = ui.facets("pub-a")
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
        entry.query == {}
        for entry in ui.requests
        if entry.path.startswith("/api/public-workspaces/") and entry.path.endswith(("/documents/tags", "/documents/facets"))
    )
    assert_read_only(ui)


def test_all_sort_controls(public_documents_ui):
    ui = public_documents_ui
    open_documents(ui)
    for field in SORT_FIELDS:
        ui.page.get_by_label("Sort documents", exact=True).select_option(field)
        for direction in ("asc", "desc"):
            control = ui.page.get_by_role("button", name=f"Sort {'ascending' if direction == 'asc' else 'descending'}", exact=True)
            if control.count():
                control.click()
            expect(explorer(ui)).to_have_attribute("aria-busy", "false")
            ordered = sorted(
                ui.visible("pub-a"),
                key=lambda item: float(item.get(field) or 0) if field in NUMERIC_SORT_FIELDS
                    else str(item.get(field) or "").casefold(),
                reverse=direction == "desc",
            )
            first = ordered[0]
            name = first.get("title") or first["file_name"]
            expect(ui.page.get_by_role("row").nth(1).get_by_role("button", name=f"Details for {name}", exact=True)).to_be_visible()
            assert last_list(ui).query["sort_by"] == [field]
            assert last_list(ui).query["sort_order"] == [direction]


def test_all_places(public_documents_ui):
    ui = public_documents_ui
    open_documents(ui)
    # The public surface has no 'shared' place: facets omit shared_with_me, so it never appears.
    expect(filters(ui).get_by_role("button", name=re.compile(r"^Shared"))).to_have_count(0)
    for place, label, count_key in (
        ("recent", "Recent", "recent"),
        ("processing", "Processing", "processing"), ("errors", "Needs attention", "errors"),
        ("untagged", "Untagged", "untagged"), ("all", "All documents", "total"),
    ):
        filters(ui).get_by_role("button", name=re.compile(rf"^{label}")).click()
        expect(explorer(ui)).to_have_attribute("aria-busy", "false")
        count = ui.facets("pub-a")[count_key]
        expect(explorer(ui).get_by_text(f"1\u2013{min(25, count)} of {count}", exact=True)).to_be_visible()
        assert last_list(ui).query.get("place") == (None if place == "all" else [place])
        assert last_list(ui).path == "/api/public-workspaces/pub-a/documents"


def test_details_and_versions(public_documents_ui):
    ui = public_documents_ui
    open_documents(ui)
    ui.detail_overrides[("pub-a", "same-document")] = {
        **copy.deepcopy(ui.documents["pub-a"][0]), "abstract": "Fresh public metadata.",
    }
    ui.page.get_by_role("button", name="Details for Research brief", exact=True).click()
    expect(ui.page.get_by_text("Fresh public metadata.", exact=True)).to_be_visible()
    ui.page.get_by_role("button", name="Refresh document details", exact=True).click()
    expect(ui.page.get_by_text("Refreshing document details...", exact=True)).to_have_count(0)
    ui.page.get_by_role("button", name="Version history", exact=True).click()
    expect(ui.page.get_by_text("Version 3 (current)", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Earlier research brief", exact=True)).to_be_visible()
    assert_read_only(ui)
    reads = [entry for entry in ui.requests if entry.path.startswith("/api/public-workspaces/pub-a/documents/")]
    assert all(entry.query == {} for entry in reads)
    assert any(entry.path.endswith("/same-document/versions") for entry in reads)


def test_late_query_is_discarded(public_documents_ui):
    ui = public_documents_ui
    open_documents(ui)
    ui.defer_next("GET", "/api/public-workspaces/pub-a/documents")
    search(ui, "no earlier match")
    expect(explorer(ui)).to_have_attribute("aria-busy", "true")
    search(ui, "Team research 57")
    expect(ui.page.get_by_role("button", name="Details for Team research 57", exact=True)).to_be_visible()
    assert len(ui.pending_responses) == 1
    ui.release_responses()
    expect(ui.page.get_by_role("button", name="Details for Team research 57", exact=True)).to_be_visible()
    expect(explorer(ui).get_by_text("No documents match these filters", exact=True)).to_have_count(0)


@pytest.mark.parametrize("suffix,action", [
    ("", "list"),
    ("/tags", "sidebar"),
    ("/facets", "sidebar"),
    ("/same-document", "detail"),
    ("/same-document/versions", "versions"),
])
def test_late_scope_reads(public_documents_ui, suffix, action):
    ui = public_documents_ui
    open_documents(ui)
    path = f"/api/public-workspaces/pub-a/documents{suffix}"
    if action == "versions":
        ui.page.get_by_role("button", name="Details for Research brief", exact=True).click()
        expect(ui.page.get_by_text("Published metadata for Research brief.", exact=True)).to_be_visible()
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
    ui.page.get_by_role("combobox", name="Public workspace", exact=True).select_option("pub-b")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public/pub-b/documents")
    expect(ui.page.get_by_role("button", name="Details for Read-only brief", exact=True)).to_be_visible()
    assert ui.pending_responses
    ui.release_responses()
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Details for Read-only brief", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Earlier research brief", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("searchbox", name="Search documents. Press Enter to search immediately.")).to_have_value("")
    expect(filters(ui).get_by_role("button", name=re.compile(r"^All documents"))).to_contain_text(str(len(ui.visible("pub-b"))))
    assert last_list(ui).path == "/api/public-workspaces/pub-b/documents"


def test_errors_are_not_empty(public_documents_ui):
    ui = public_documents_ui
    open_documents(ui)
    ui.reject_next("GET", "/api/public-workspaces/pub-a/documents")
    search(ui, "Team")
    expect(ui.page.get_by_role("alert")).to_contain_text("Documents could not be loaded")
    expect(ui.page.get_by_text("No documents yet", exact=True)).to_have_count(0)
    expect(ui.page.get_by_text("No documents", exact=True)).to_have_count(0)
    ui.page.get_by_role("button", name="Retry documents", exact=True).click()
    expect(explorer(ui)).to_have_attribute("aria-busy", "false")
    expect(ui.page.get_by_role("alert")).to_have_count(0)
    search(ui, "")
    ui.reject_next("GET", "/api/public-workspaces/pub-a/documents/same-document/versions")
    ui.page.get_by_role("button", name="Details for Research brief", exact=True).click()
    ui.page.get_by_role("button", name="Version history", exact=True).click()
    expect(ui.page.get_by_role("button", name="Retry version history", exact=True)).to_be_visible()
    ui.page.get_by_role("button", name="Retry version history", exact=True).click()
    expect(ui.page.get_by_text("Earlier research brief", exact=True)).to_be_visible()


def test_facets_failure_is_visible(public_documents_ui):
    ui = public_documents_ui
    ui.reject_next("GET", "/api/public-workspaces/pub-a/documents/facets")
    open_documents(ui)
    expect(ui.page.get_by_role("button", name="Retry document updates", exact=True)).to_be_visible()
    ui.page.get_by_role("button", name="Retry document updates", exact=True).click()
    expect(ui.page.get_by_role("alert")).to_have_count(0)
    expect(filters(ui).get_by_role("button", name=re.compile(r"^All documents"))).to_contain_text(str(len(ui.visible("pub-a"))))


def test_detail_failure_hides_cached_metadata(public_documents_ui):
    ui = public_documents_ui
    open_documents(ui)
    ui.reject_next("GET", "/api/public-workspaces/pub-a/documents/same-document", status=403)
    ui.page.get_by_role("button", name="Details for Research brief", exact=True).click()
    expect(ui.page.get_by_role("button", name="Retry document details", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Published metadata for Research brief.", exact=True)).to_have_count(0)
    ui.page.get_by_role("button", name="Retry document details", exact=True).click()
    expect(ui.page.get_by_text("Published metadata for Research brief.", exact=True)).to_be_visible()


def test_empty_workspace_stays_read_only(public_documents_ui):
    ui = public_documents_ui
    ui.documents["pub-a"] = []
    ui.open("/public/pub-a/documents")
    expect(ui.page.get_by_text("No documents yet", exact=True)).to_be_visible()
    expect(explorer(ui).get_by_role("button", name="Chat", exact=True)).to_be_disabled()
    assert_read_only(ui)


def test_chat_ceiling_is_read_only(public_documents_ui):
    ui = public_documents_ui
    ui.workspaces["pub-a"]["document_permissions"]["can_chat"] = False
    open_documents(ui)
    expect(row(ui, "Research brief").get_by_role("checkbox")).to_be_disabled()
    row(ui, "Research brief").click()
    expect(ui.page.get_by_text("Chat is not currently available for this public workspace.", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Published metadata for Research brief.", exact=True)).to_be_visible()
    assert_read_only(ui)


def test_unknown_workspace_is_surfaced(public_documents_ui):
    ui = public_documents_ui
    ui.open("/public/pub-missing/documents")
    expect(ui.page.get_by_role("alert")).to_contain_text("no longer exists")
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_have_count(0)
    assert not list_requests(ui)


def test_unauthorized_workspace_is_surfaced(public_documents_ui):
    ui = public_documents_ui
    ui.denied_workspaces.add("pub-a")
    ui.open("/public/pub-a/documents")
    expect(ui.page.get_by_role("alert")).to_contain_text("do not have access")
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_have_count(0)
    assert not list_requests(ui)


def test_disabled_feature_hides_surface(public_documents_ui):
    ui = public_documents_ui
    ui.public_enabled = False
    ui.open("/public")
    expect(ui.page.get_by_text("Public workspaces are not enabled", exact=True)).to_be_visible()
    assert not list_requests(ui)
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/v2/workspaces/public/")]


def test_selection_sets_active_and_navigates(public_documents_ui):
    ui = public_documents_ui
    open_documents(ui)
    ui.page.get_by_role("combobox", name="Public workspace", exact=True).select_option("pub-b")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public/pub-b/documents")
    expect(ui.page.get_by_role("button", name="Details for Read-only brief", exact=True)).to_be_visible()
    active = [entry for entry in ui.writes if entry.path == "/api/public_workspaces/setActive"]
    assert active and active[-1].body == {"workspaceId": "pub-b"}
    assert ui.active_workspace == "pub-b"


def test_refused_set_active_leaves_surface_functional(public_documents_ui):
    ui = public_documents_ui
    # A refused setActive must not gate navigation, reads or rendering: reads target the id
    # in the path, so the surface stays fully functional even when the courtesy write fails.
    ui.set_active_failures.add("pub-b")
    open_documents(ui)
    ui.page.get_by_role("combobox", name="Public workspace", exact=True).select_option("pub-b")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public/pub-b/documents")
    expect(ui.page.get_by_role("button", name="Details for Read-only brief", exact=True)).to_be_visible()
    expect(explorer(ui)).to_have_attribute("aria-busy", "false")
    assert_read_only(ui)
    expect(ui.page.get_by_role("alert")).to_have_count(0)
    attempted = [entry for entry in ui.writes if entry.path == "/api/public_workspaces/setActive"]
    assert attempted and attempted[-1].body == {"workspaceId": "pub-b"}
    assert ui.active_workspace == "pub-a"
    assert last_list(ui).path == "/api/public-workspaces/pub-b/documents"


def test_classic_handoff(public_documents_ui):
    ui = public_documents_ui
    open_documents(ui)
    ui.page.get_by_role("button", name="Open classic public workspace", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/public_workspaces")
    assert ("/public_workspaces", "pub-a") in ui.classic_visits


def test_public_document_text_is_inert(public_documents_ui):
    ui = public_documents_ui
    payload = '<img src=x onerror="window.documentTextExecuted=true">'
    ui.documents["pub-a"][0].update({"title": payload, "abstract": payload})
    ui.open("/public/pub-a/documents")
    ui.page.get_by_role("button", name=f"Details for {payload}", exact=True).click()
    expect(ui.page.get_by_role("complementary").get_by_text(payload, exact=True)).to_have_count(2)
    executed = ui.page.evaluate("window.documentTextExecuted === true")
    assert executed is False
