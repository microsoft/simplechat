# test_v2_public_documents.py
"""
Production-SPA coverage for native V2 public workspace document browsing (M3A),
management (M3B) and generated-artifact approval (M3C).
Version: 0.261.163
Implemented in: 0.261.132
A coded failure shows the server's sentence (apiClient), and an archive takes the server's
name: 0.261.163

Exercises real components, stores and navigation with closed synthetic HTTP.
The read fixture never permits personal or group document requests, and never
permits a document write: the M3A surface is strictly read-only. The M3B management
fixture allows writes only on the immutable /api/public-workspaces/<id>/documents
family. M3C adds publication (generated-artifact) decisions on that same immutable
family, still with no cross-workspace sharing, so the Shared place stays absent.
Every read and operation carries its workspace id in the request path, so selecting
a public workspace can never leak into a personal or group read or write.
"""

import copy
import io
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.public_document_management import (
    DOCUMENT_ACTIONS, OPERATIONS, PROPAGATION_INCOMPLETE_MESSAGE, delete_result, metadata_result,  # noqa: F401
    operation_path, propagation_incomplete, public_management_ui, tag_result, tag_vocabulary_conflict,
)
from ui_tests.fixtures.public_document_collaboration import (
    COLLABORATION_OPERATIONS, collaboration_receipt, public_collaboration_ui,  # noqa: F401
    publication,
)
from ui_tests.fixtures.public_documents import (
    NUMERIC_SORT_FIELDS, SORT_FIELDS, connect_options, document,  # noqa: F401
    public_documents_ui,
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


# --- M3B public document management ------------------------------------------
# The management surface extends the same explorer and immutable read/operation
# family. It reuses the group management components, so a manager moving between
# public and group workspaces cannot tell them apart. Every operation carries its
# public workspace id in the request path, never an active selection.
MANAGEMENT_SCREENSHOTS = Path(os.environ.get(
    "SIMPLECHAT_UI_SCREENSHOTS", str(Path(__file__).parent / "artifacts" / "public-management"),
))


def command(ui, label):
    return explorer(ui).get_by_role("button", name=label, exact=True).first


def details_button(ui, identifier, workspace_id="pub-a"):
    record = ui.record(identifier, workspace_id)
    name = record.get("title") or record["file_name"]
    return ui.page.get_by_role("button", name=f"Details for {name}", exact=True)


def document_row(ui, identifier, workspace_id="pub-a"):
    return ui.page.get_by_role("row").filter(has=details_button(ui, identifier, workspace_id))


def checkbox(ui, identifier, workspace_id="pub-a"):
    return document_row(ui, identifier, workspace_id).get_by_role("checkbox")


def response_for(method, path):
    return lambda response: response.request.method == method and urlsplit(response.url).path == path


def detail_path(identifier, workspace_id="pub-a"):
    return f"/api/public-workspaces/{workspace_id}/documents/{identifier}"


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


def open_management(ui, workspace_id="pub-a", **options):
    ui.open(f"/public/{workspace_id}/documents", **options)
    expect(details_button(ui, "same-document", workspace_id)).to_be_visible()
    expect(explorer(ui)).to_have_attribute("aria-busy", "false")
    expect(explorer(ui)).to_be_enabled()


def clear_selection(ui):
    expect(explorer(ui)).to_be_enabled()
    ui.page.get_by_role("button", name=re.compile(r"^Details for ")).first.focus()
    ui.page.keyboard.press("Escape")
    expect(explorer(ui).locator('input[type="checkbox"]:checked')).to_have_count(0)


def select_documents(ui, *identifiers, workspace_id="pub-a"):
    clear_selection(ui)
    for index, identifier in enumerate(identifiers):
        if index == 0:
            with ui.page.expect_response(response_for("GET", detail_path(identifier, workspace_id))) as detail:
                checkbox(ui, identifier, workspace_id).check()
            detail.value.finished()
        else:
            checkbox(ui, identifier, workspace_id).check()
        expect(checkbox(ui, identifier, workspace_id)).to_be_checked()
    expect(explorer(ui)).to_be_enabled()


def show_details(ui, identifier="same-document", workspace_id="pub-a"):
    with ui.page.expect_response(response_for("GET", detail_path(identifier, workspace_id))) as detail:
        details_button(ui, identifier, workspace_id).click()
    detail.value.finished()
    expect(ui.page.get_by_role("button", name="Refresh document details", exact=True)).to_be_enabled()


def edit_metadata(ui, identifier="same-document", workspace_id="pub-a"):
    show_details(ui, identifier, workspace_id)
    ui.page.get_by_role("button", name="Edit", exact=True).click()
    dialog = ui.page.get_by_role("dialog", name="Edit metadata", exact=True)
    expect(dialog).to_be_visible()
    return dialog


def changed_record(ui, identifier, workspace_id="pub-a", **changes):
    return {**copy.deepcopy(ui.record(identifier, workspace_id)), **copy.deepcopy(changes)}


def assert_no_shared_place(ui):
    # Public has no cross-workspace share relationship in M3B: facets omit shared_with_me,
    # so no Shared place and no personal 'Save view' or 'Share' controls may appear.
    expect(filters(ui).get_by_role("button", name=re.compile(r"^Shared"))).to_have_count(0)
    for label in ("Share", "Save view", "Approve", "Reject"):
        expect(explorer(ui).get_by_role("button", name=label, exact=True)).to_have_count(0)


def test_missing_or_unknown_handshake_keeps_public_management_read_only(public_management_ui):
    ui = public_management_ui
    # An absent or unrecognised handshake is an interface hint, never an authorization: the
    # surface must stay read-only rather than degrade into a partially enabled state.
    for handshake in (None, {"schema_version": 99, "operations": list(OPERATIONS)}):
        if handshake is None:
            ui.workspaces["pub-a"].pop("document_management")
        else:
            ui.workspaces["pub-a"]["document_management"] = handshake
        open_management(ui)
        select_documents(ui, "same-document")
        assert_read_only(ui)
        assert_no_shared_place(ui)
        expect(document_row(ui, "same-document")).to_have_attribute("draggable", "false")
        assert not ui.operation_requests
    ui.documents["pub-a"] = []
    ui.open("/public/pub-a/documents")
    expect(ui.page.get_by_text("No documents yet", exact=True)).to_be_visible()
    assert_read_only(ui)
    assert not ui.operation_requests


def test_user_role_leaves_the_public_surface_read_only(public_management_ui):
    ui = public_management_ui
    # A non-manager role advertises no operations, so management affordances never appear.
    ui.set_policy("pub-a", role="User")
    open_management(ui)
    select_documents(ui, "same-document")
    expect(command(ui, "Chat")).to_be_enabled()
    assert_read_only(ui)
    assert_no_shared_place(ui)
    assert not ui.operation_requests


def test_per_document_actions_gate_every_command(public_management_ui):
    ui = public_management_ui
    # document_management advertises the surface; per-document document_actions authorise each
    # document. A withheld document (empty actions) must disable every command even for a manager,
    # and a mixed selection must not borrow a sibling's permission.
    open_management(ui)
    select_documents(ui, "same-document")
    for label in ("Tag", "Edit", "Delete", "Extract", "Download", "Switch to Enhanced"):
        expect(command(ui, label)).to_be_enabled()
    select_documents(ui, "withheld-document")
    for label in ("Tag", "Edit", "Delete", "Extract", "Download", "Switch to Enhanced"):
        expect(command(ui, label)).to_be_disabled()
    expect(document_row(ui, "withheld-document")).to_have_attribute("draggable", "false")
    select_documents(ui, "same-document", "withheld-document")
    for label in ("Tag", "Delete", "Extract", "Download", "Switch to Enhanced"):
        expect(command(ui, label)).to_be_disabled()
    assert not ui.operation_requests


def test_upload_repeated_file_parts_partial_acceptance(public_management_ui):
    ui = public_management_ui
    ui.documents["pub-a"] = []
    ui.open("/public/pub-a/documents")
    expect(ui.page.get_by_text("No documents yet", exact=True)).to_be_visible()
    files = [
        {"name": "accepted.txt", "mimeType": "text/plain", "buffer": b"Accepted public source.\n"},
        {"name": "refused.txt", "mimeType": "text/plain", "buffer": b"Rejected public source.\n"},
    ]
    uploaded = document(
        "pub-a", "uploaded-document", "Accepted upload", timestamp=ui.now + 1,
        file_name="accepted.txt", tags=[], document_actions=list(DOCUMENT_ACTIONS),
    )
    reply = ui.queue_operation(
        "POST", "upload", files=files, status=207,
        response={
            "document_ids": ["uploaded-document"], "processed_filenames": ["accepted.txt"],
            "errors": ["refused.txt: this file was not accepted."],
        },
        records=[uploaded],
    )
    ui.defer_next("POST", reply.path)
    with ui.page.expect_file_chooser() as chooser:
        ui.page.get_by_role("button", name="Upload a document", exact=True).click()
    with ui.page.expect_request(lambda request: request.method == "POST" and urlsplit(request.url).path == reply.path):
        chooser.value.set_files(files)
    expect(ui.page.get_by_role("progressbar", name="Uploading files", exact=True)).to_be_visible()
    expect(command(ui, "Upload")).to_be_disabled()
    assert len(ui.pending_responses) == 1
    perform(ui, reply, ui.release_responses)
    expect(ui.page.get_by_role("alert").filter(has_text="refused.txt: this file was not accepted.")).to_be_visible()
    expect(details_button(ui, "uploaded-document")).to_be_visible()
    assert ui.multipart_uploads == [(reply.path, files)]
    assert len(ui.operation_requests) == 1


def test_metadata_patch_retains_failed_draft_and_targets_the_immutable_workspace(public_management_ui):
    ui = public_management_ui
    original = copy.deepcopy(ui.record("same-document"))
    open_management(ui)
    dialog = edit_metadata(ui)
    expect(dialog.get_by_role("button", name="Save", exact=True)).to_be_disabled()
    dialog.get_by_label(re.compile(r"^Title")).fill("Updated public brief")
    dialog.get_by_label("Keywords", exact=True).fill("baseline, reviewed")
    body = {"title": "Updated public brief", "keywords": ["baseline", "reviewed"]}
    failed = ui.queue_operation(
        "PATCH", "same-document", body=body, status=500, response=propagation_incomplete("same-document"),
    )
    perform(ui, failed, dialog.get_by_role("button", name="Save", exact=True).click)
    # The server's sentence, not its `document_propagation_incomplete` code.
    expect(dialog.get_by_role("alert")).to_contain_text(PROPAGATION_INCOMPLETE_MESSAGE)
    expect(dialog.get_by_role("alert")).not_to_contain_text("document_propagation_incomplete")
    expect(dialog.get_by_label(re.compile(r"^Title"))).to_have_value("Updated public brief")
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
    # The active selection is a courtesy only. Changing it while a write is in flight must not
    # retarget the immutable operation path or trigger a setActive.
    ui.active_workspace = "pub-b"
    perform(ui, saved, ui.release_responses)
    expect(dialog).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Details for Updated public brief", exact=True)).to_be_visible()
    assert [entry.body for entry in ui.operation_requests] == [body, body]
    assert all(entry.path == operation_path("same-document") for entry in ui.operation_requests)
    assert not any(entry.path == "/api/public_workspaces/setActive" for entry in ui.writes)
    assert ui.record("same-document")["abstract"] == original["abstract"]


def test_bulk_tag_add_via_command_and_remove_via_chip(public_management_ui):
    ui = public_management_ui
    open_management(ui)
    select_documents(ui, "same-document", "notes-document")
    command(ui, "Tag").click()
    dialog = ui.page.get_by_role("dialog", name="Tag 2 documents", exact=True)
    dialog.get_by_role("checkbox", name=re.compile(r"^review\b")).check()
    tagged = changed_record(ui, "same-document", tags=["finance", "team", "review"])
    tagged_notes = changed_record(ui, "notes-document", tags=["team", "legacy/review", "review"])
    added = ui.queue_operation(
        "POST", "bulk-tag",
        body={"document_ids": ["same-document", "notes-document"], "action": "add_tags", "tags": ["review"]},
        response={
            "success": [
                {"document_id": "same-document", "tags": tagged["tags"]},
                {"document_id": "notes-document", "tags": tagged_notes["tags"]},
            ],
            "errors": [],
        },
        records=[tagged, tagged_notes],
    )
    perform(ui, added, dialog.get_by_role("button", name="Apply", exact=True).click)
    expect(dialog).to_have_count(0)
    expect(document_row(ui, "same-document").get_by_text("review", exact=True)).to_be_visible()
    expect(document_row(ui, "notes-document").get_by_text("review", exact=True)).to_be_visible()
    # Removing the tag is scoped to the current selection, so both documents lose it together.
    untagged = changed_record(ui, "same-document", tags=["finance", "team"])
    untagged_notes = changed_record(ui, "notes-document", tags=["team", "legacy/review"])
    removed = ui.queue_operation(
        "POST", "bulk-tag",
        body={"document_ids": ["same-document", "notes-document"], "action": "remove_tags", "tags": ["review"]},
        response={
            "success": [
                {"document_id": "same-document", "tags": untagged["tags"]},
                {"document_id": "notes-document", "tags": untagged_notes["tags"]},
            ],
            "errors": [],
        },
        records=[untagged, untagged_notes],
    )
    perform(ui, removed, ui.page.get_by_role("button", name="Remove tag review", exact=True).first.click)
    expect(document_row(ui, "same-document").get_by_text("review", exact=True)).to_have_count(0)
    expect(document_row(ui, "notes-document").get_by_text("review", exact=True)).to_have_count(0)
    assert len(ui.operation_requests) == 2


def test_single_revision_delete_uses_the_public_family_and_query_mode(public_management_ui):
    ui = public_management_ui
    open_management(ui)
    history = ui.versions[("pub-a", "same-document")]
    promoted = {**copy.deepcopy(history[1]), "is_current_version": True, "document_actions": list(DOCUMENT_ACTIONS)}
    select_documents(ui, "same-document")
    command(ui, "Delete").click()
    dialog = ui.page.get_by_role("dialog", name="Delete documents", exact=True)
    dialog.get_by_label(re.compile(r"^Delete every version")).set_checked(False)
    current = ui.queue_operation(
        "DELETE", "same-document", query={"delete_mode": ["current_only"]},
        response=delete_result(
            "same-document", deleted_mode="current_only",
            deleted_document_ids=["same-document"], promoted_document_id=promoted["id"],
        ),
        remove_ids=["same-document"], records=[promoted], versions={promoted["id"]: [promoted]},
    )
    perform(ui, current, dialog.get_by_role("button", name="Delete", exact=True).click)
    expect(dialog).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_have_count(0)
    expect(details_button(ui, "previous-version")).to_be_visible()
    select_documents(ui, "notes-document")
    command(ui, "Delete").click()
    dialog = ui.page.get_by_role("dialog", name="Delete documents", exact=True)
    dialog.get_by_label(re.compile(r"^Delete every version")).set_checked(True)
    every = ui.queue_operation(
        "DELETE", "notes-document", query={"delete_mode": ["all_versions"]},
        response=delete_result(
            "notes-document", deleted_mode="all_versions",
            deleted_document_ids=["notes-document"], promoted_document_id=None,
        ),
        remove_ids=["notes-document"],
    )
    perform(ui, every, dialog.get_by_role("button", name="Delete", exact=True).click)
    expect(dialog).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Details for Field notes", exact=True)).to_have_count(0)
    assert len(ui.operation_requests) == 2
    assert all(entry.method == "DELETE" for entry in ui.operation_requests)


def test_bulk_delete_removes_every_requested_document(public_management_ui):
    ui = public_management_ui
    open_management(ui)
    select_documents(ui, "same-document", "notes-document")
    command(ui, "Delete").click()
    dialog = ui.page.get_by_role("dialog", name="Delete documents", exact=True)
    expect(dialog).to_contain_text("Research brief")
    expect(dialog).to_contain_text("Field notes")
    reply = ui.queue_operation(
        "POST", "bulk-delete",
        body={
            "document_ids": ["same-document", "notes-document"], "delete_mode": "all_versions",
            "conversation_linked_delete_confirmed": False,
        },
        response=delete_result("same-document", "notes-document"),
        remove_ids=["same-document", "notes-document"],
    )
    perform(ui, reply, dialog.get_by_role("button", name="Delete", exact=True).click)
    expect(dialog).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Details for Field notes", exact=True)).to_have_count(0)
    expect(details_button(ui, "withheld-document")).to_be_visible()
    assert ui.operation_requests[-1].path == operation_path("bulk-delete")


def test_downloads_save_complete_bytes_and_refusals_never_become_files(public_management_ui, tmp_path):
    ui = public_management_ui
    ui.record("same-document")["file_name"] = "brief.txt"
    owned_bytes = b"Published public research source.\n"
    open_management(ui)
    select_documents(ui, "same-document")
    single = ui.queue_operation(
        "GET", "same-document/download", response=owned_bytes, content_type="text/plain",
        headers={"Content-Disposition": 'attachment; filename="brief.txt"'},
    )
    with ui.page.expect_download() as download:
        perform(ui, single, command(ui, "Download").click)
    assert download.value.suggested_filename == "brief.txt"
    saved = tmp_path / "one.txt"
    download.value.save_as(saved)
    assert saved.read_bytes() == owned_bytes and download.value.failure() is None
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_STORED) as archive:
        for name, content in (("brief.txt", owned_bytes), ("notes-document.pdf", b"Public field notes.\n")):
            archive.writestr(ZipInfo(name, date_time=(2026, 9, 1, 0, 0, 0)), content)
    archive_bytes = stream.getvalue()
    select_documents(ui, "same-document", "notes-document")
    # The public route names its archive public-documents.zip, and the explorer saves it so.
    batch = ui.queue_operation(
        "POST", "download", body={"document_ids": ["same-document", "notes-document"]},
        response=archive_bytes, content_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="public-documents.zip"'},
    )
    with ui.page.expect_download() as download:
        perform(ui, batch, command(ui, "Download").click)
    assert download.value.suggested_filename == "public-documents.zip"
    saved_archive = tmp_path / "set.zip"
    download.value.save_as(saved_archive)
    assert saved_archive.read_bytes() == archive_bytes
    downloads = []
    ui.page.on("download", lambda item: downloads.append(item))
    select_documents(ui, "same-document")
    refused = ui.queue_operation(
        "GET", "same-document/download", status=403,
        response={"error": "The public workspace no longer permits downloading."},
    )
    response = perform(ui, refused, command(ui, "Download").click)
    assert "content-disposition" not in response.headers
    expect(ui.page.get_by_text(
        "The download was not authorized or did not return a complete file. No file was saved.", exact=True,
    )).to_be_visible()
    assert downloads == []
    assert len(ui.operation_requests) == 3


def test_extract_and_reprocess_partial_then_retry(public_management_ui):
    ui = public_management_ui
    open_management(ui)
    for resource, label, extra in (
        ("extract_metadata", "Extract", {}),
        ("reprocess_extraction", "Switch to Enhanced", {"extraction_mode": "layout"}),
    ):
        select_documents(ui, "same-document", "notes-document")
        partial = ui.queue_operation(
            "POST", resource, body={"document_ids": ["same-document", "notes-document"], **extra},
            status=207,
            response={
                "queued": [{"document_id": "same-document", "status": "queued"}],
                "errors": [{"document_id": "notes-document", "error": "queue_unavailable", "message": "Field notes was not queued."}],
            },
        )
        perform(ui, partial, command(ui, label).click)
        expect(explorer(ui).get_by_role("alert")).to_contain_text("Field notes was not queued.")
        expect(checkbox(ui, "same-document")).not_to_be_checked()
        expect(checkbox(ui, "notes-document")).to_be_checked()
        retry = ui.queue_operation(
            "POST", resource, body={"document_ids": ["notes-document"], **extra}, status=202,
            response={"queued": [{"document_id": "notes-document", "status": "queued"}], "errors": []},
        )
        perform(ui, retry, command(ui, label).click)
        expect(explorer(ui).get_by_role("status").filter(has_text="queued: 1 of 1 confirmed")).to_be_visible()
        expect(explorer(ui).get_by_role("alert")).to_have_count(0)
    assert len(ui.operation_requests) == 4


def test_refused_set_active_leaves_a_public_operation_working(public_management_ui):
    ui = public_management_ui
    # M3B pin: active state is non-load-bearing on purpose. A refused or failed setActive must
    # leave not just reads but an *operation* fully functional, because every operation targets
    # the immutable workspace path rather than the courtesy active selection.
    ui.set_active_failures.add("pub-b")
    open_management(ui, "pub-a")
    ui.page.get_by_role("combobox", name="Public workspace", exact=True).select_option("pub-b")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public/pub-b/documents")
    expect(details_button(ui, "same-document", "pub-b")).to_be_visible()
    attempted = [entry for entry in ui.writes if entry.path == "/api/public_workspaces/setActive"]
    assert attempted and attempted[-1].body == {"workspaceId": "pub-b"}
    assert ui.active_workspace == "pub-a"
    dialog = edit_metadata(ui, "same-document", "pub-b")
    body = {"title": "Edited despite refused active"}
    dialog.get_by_label(re.compile(r"^Title")).fill(body["title"])
    reply = ui.queue_operation(
        "PATCH", "same-document", body=body, workspace_id="pub-b",
        response=metadata_result("same-document", body, public_workspace_id="pub-b"),
        records=[changed_record(ui, "same-document", "pub-b", **body)],
    )
    perform(ui, reply, dialog.get_by_role("button", name="Save", exact=True).click)
    expect(dialog).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Details for Edited despite refused active", exact=True)).to_be_visible()
    assert ui.operation_requests[-1].path == operation_path("same-document", "pub-b")
    assert ui.active_workspace == "pub-a"


@pytest.mark.parametrize("theme,width,height,label", [
    ("light", 1440, 900, "dl"), ("dark", 1440, 900, "dd"),
    ("light", 390, 844, "ml"), ("dark", 390, 844, "md"),
])
def test_management_layout_and_dialogs_in_both_themes(public_management_ui, theme, width, height, label):
    ui = public_management_ui
    open_management(ui, theme=theme, width=width, height=height)
    expect(command(ui, "Upload")).to_be_enabled()
    assert_no_shared_place(ui)
    ui.assert_no_overflow()
    bounds = explorer(ui).bounding_box()
    search_control = ui.page.get_by_role("searchbox", name="Search documents. Press Enter to search immediately.", exact=True)
    search_bounds = search_control.bounding_box()
    table_viewport = ui.page.get_by_role("table").locator("..").bounding_box()
    assert bounds and bounds["width"] >= 200 and bounds["height"] >= 180
    assert search_bounds and search_bounds["width"] >= 180
    assert table_viewport and table_viewport["height"] >= 160
    MANAGEMENT_SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    ui.page.screenshot(path=str(MANAGEMENT_SCREENSHOTS / f"{label}-docs.png"), full_page=True)
    dialog = edit_metadata(ui)
    dialog.get_by_label(re.compile(r"^Title")).fill("A retained public draft")
    expect(dialog.get_by_role("button", name="Save", exact=True)).to_be_enabled()
    card = dialog.locator(".glass-modal")
    dialog_bounds = card.bounding_box()
    assert dialog_bounds and dialog_bounds["x"] >= 0 and dialog_bounds["width"] <= width
    assert dialog_bounds["y"] >= 0 and dialog_bounds["y"] + dialog_bounds["height"] <= height + 1
    fits = card.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
    assert fits is True
    expect(ui.page.locator("html")).to_have_css("color-scheme", theme)
    ui.assert_no_overflow()
    ui.page.screenshot(path=str(MANAGEMENT_SCREENSHOTS / f"{label}-edit.png"), full_page=True)
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    expect(dialog).to_have_count(0)
    assert not ui.operation_requests


# --- M3C public generated-artifact approval ----------------------------------
# Publication decisions extend the same explorer and immutable operation family.
# They reuse the group review dialog, so a reviewer moving between public and group
# workspaces cannot tell them apart. Public workspaces have no cross-workspace
# sharing in this milestone, so the review dialog exposes only publication
# decisions and the Shared place never appears. Every decision carries its public
# workspace id in the request path, never an active selection.
REVIEW_SCREENSHOTS = Path(os.environ.get(
    "SIMPLECHAT_UI_SCREENSHOTS", str(Path(__file__).parent / "artifacts" / "public-review"),
))
REVIEW_TITLE = "Document review"


def review_dialog(ui):
    return ui.page.get_by_role("dialog", name=REVIEW_TITLE, exact=True)


def review_control(ui, identifier, workspace_id="pub-a"):
    record = ui.record(identifier, workspace_id)
    name = record.get("title") or record["file_name"]
    return document_row(ui, identifier, workspace_id).get_by_role("button", name=f"Review {name}", exact=True)


def publication_path(identifier, workspace_id="pub-a"):
    return f"/api/public-workspaces/{workspace_id}/documents/{identifier}/publication"


def open_review(ui, identifier="pending-publication", workspace_id="pub-a"):
    with ui.page.expect_response(response_for("GET", publication_path(identifier, workspace_id))) as read:
        review_control(ui, identifier, workspace_id).click()
    read.value.finished()
    dialog = review_dialog(ui)
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("button", name="Refresh review details", exact=True)).to_be_enabled()
    return dialog


def refresh_review(ui, identifier="pending-publication", workspace_id="pub-a"):
    with ui.page.expect_response(response_for("GET", publication_path(identifier, workspace_id))) as read:
        review_dialog(ui).get_by_role("button", name="Refresh review details", exact=True).click()
    read.value.finished()
    return read.value


def confirm(ui, label):
    review_dialog(ui).get_by_role("button", name=label, exact=True).click()
    dialog = ui.page.get_by_role("dialog", name=f"Confirm {label.lower()}", exact=True)
    expect(dialog).to_be_visible()
    return dialog


def changed_state(ui, identifier="pending-publication", workspace_id="pub-a", **changes):
    return {**copy.deepcopy(ui.review_state(identifier, workspace_id)), **copy.deepcopy(changes)}


def test_publication_approval_queues_processing_and_targets_the_immutable_workspace(public_collaboration_ui):
    ui = public_collaboration_ui
    # Approval records a decision and queues processing; it never claims completed work and
    # never releases the still-restricted generated artifact for ordinary management.
    open_management(ui, "pub-a")
    state = ui.review_state("pending-publication")
    dialog = open_review(ui, "pending-publication")
    expect(dialog).to_contain_text("Publishing colleague")
    held = changed_record(
        ui, "pending-publication", generated_artifact_promotion_status="approved",
        document_actions=[], document_collaboration_actions=["inspect"],
    )
    reply = ui.queue_decision(
        "pending-publication", "approve_artifact", expected_etag=state["etag"], status=202,
        response=collaboration_receipt("pending-publication", "approve_artifact", "approved", status="queued"),
        records=[held], publication_after=changed_state(
            ui, "pending-publication", etag='"publication:queued"',
            publication=publication(status="approved"),
        ),
    )
    perform(ui, reply, dialog.get_by_role("button", name="Approve publication", exact=True).click)
    expect(dialog.get_by_role("status").filter(has_text="Processing is queued, not complete")).to_be_visible()
    dialog.get_by_role("button", name="Done", exact=True).click()
    assert ui.operation_requests[-1].path == operation_path("pending-publication/artifact/approve", "pub-a")
    assert ui.record("pending-publication")["generated_artifact_promotion_status"] == "approved"
    assert not ui.record("pending-publication")["document_actions"]
    assert ui.active_workspace == "pub-a"


def test_reject_publication_requires_confirmation_and_records_the_decision(public_collaboration_ui):
    ui = public_collaboration_ui
    open_management(ui, "pub-a")
    dialog = open_review(ui, "pending-publication")
    confirmation = confirm(ui, "Reject publication")
    expect(confirmation).to_contain_text("Revision 3")
    assert not ui.operation_requests
    reply = ui.queue_decision(
        "pending-publication", "reject_artifact",
        expected_etag=ui.review_state("pending-publication")["etag"],
        response=collaboration_receipt("pending-publication", "reject_artifact", "rejected"),
        records=[changed_record(
            ui, "pending-publication", generated_artifact_promotion_status="rejected",
            document_collaboration_actions=["inspect"],
        )],
        publication_after=changed_state(
            ui, "pending-publication", etag='"publication:rejected"',
            publication=publication(status="rejected"),
        ),
    )
    perform(ui, reply, confirmation.get_by_role("button", name="Reject publication", exact=True).click)
    expect(confirmation).to_have_count(0)
    expect(dialog.get_by_role("status").filter(has_text="Decision confirmed.")).to_be_visible()
    expect(dialog).to_contain_text("Result: rejected")
    assert set(ui.operation_requests[0].body) == {"expected_etag"}
    assert ui.active_workspace == "pub-a"


def test_only_the_requester_can_cancel_a_pending_publication(public_collaboration_ui):
    ui = public_collaboration_ui
    open_management(ui, "pub-a")
    # A non-requester sees approve and reject, never cancel.
    non_requester = open_review(ui, "pending-publication")
    expect(non_requester.get_by_role("button", name="Cancel publication request", exact=True)).to_have_count(0)
    non_requester.get_by_role("button", name="Done", exact=True).click()
    expect(non_requester).to_have_count(0)
    # The requester may withdraw their own request, behind a confirmation.
    dialog = open_review(ui, "requested-publication")
    expect(dialog).to_contain_text("(you)")
    expect(dialog.get_by_role("button", name="Approve publication", exact=True)).to_have_count(0)
    confirmation = confirm(ui, "Cancel publication request")
    reply = ui.queue_decision(
        "requested-publication", "cancel_artifact",
        expected_etag=ui.review_state("requested-publication")["etag"],
        response=collaboration_receipt("requested-publication", "cancel_artifact", "cancelled"),
        records=[changed_record(
            ui, "requested-publication", generated_artifact_promotion_status="cancelled",
            document_collaboration_actions=["inspect"],
        )],
        publication_after=changed_state(
            ui, "requested-publication", etag='"publication:cancelled"',
            publication=publication(requester=True, status="cancelled"),
        ),
    )
    perform(ui, reply, confirmation.get_by_role("button", name="Cancel publication request", exact=True).click)
    expect(confirmation).to_have_count(0)
    expect(dialog.get_by_role("status").filter(has_text="Decision confirmed.")).to_be_visible()
    expect(dialog).to_contain_text("Result: cancelled")


def test_approval_failed_is_recorded_approval_with_deliberate_resume(public_collaboration_ui):
    ui = public_collaboration_ui
    ui.page.clock.install()
    open_management(ui, "pub-a")
    dialog = open_review(ui, "pending-publication")
    initial = copy.deepcopy(ui.review_state("pending-publication"))
    failed_state = changed_state(
        ui, "pending-publication", etag='"publication:handoff-failed"',
        publication=publication(status="approval_failed", actions=["approve_artifact"]),
    )
    partial = ui.queue_decision(
        "pending-publication", "approve_artifact", expected_etag=initial["etag"], status=207,
        response=collaboration_receipt(
            "pending-publication", "approve_artifact", "approval_failed", status="partial",
            errors=[{"stage": "queue", "code": "handoff_failed",
                     "message": "Approval recorded; the processing handoff needs reconciliation."}],
        ),
        records=[changed_record(
            ui, "pending-publication", generated_artifact_promotion_status="approval_failed",
            document_collaboration_actions=["inspect", "approve_artifact"],
        )],
        publication_after=failed_state,
    )
    perform(ui, partial, dialog.get_by_role("button", name="Approve publication", exact=True).click)
    expect(dialog.get_by_role("alert").filter(has_text="processing handoff needs reconciliation")).to_be_visible()
    expect(dialog.get_by_text("Approval was recorded, but its processing handoff needs reconciliation.", exact=True)).to_be_visible()
    expect(dialog.get_by_role("button", name="Approve publication", exact=True)).to_have_count(0)
    expect(dialog.get_by_role("button", name="Resume approved publication", exact=True)).to_be_disabled()
    ui.page.clock.fast_forward(10000)
    assert len(ui.operation_requests) == 1
    refresh_review(ui, "pending-publication")
    retry = ui.queue_decision(
        "pending-publication", "approve_artifact", expected_etag=failed_state["etag"], status=202,
        response=collaboration_receipt("pending-publication", "approve_artifact", "approved", status="queued"),
        publication_after=changed_state(
            ui, "pending-publication", etag='"publication:resumed"',
            publication=publication(status="approved"),
        ),
    )
    perform(ui, retry, dialog.get_by_role("button", name="Resume approved publication", exact=True).click)
    expect(dialog.get_by_role("status").filter(has_text="Processing is queued, not complete")).to_be_visible()
    assert [entry.body["expected_etag"] for entry in ui.operation_requests] == [initial["etag"], failed_state["etag"]]


def test_stale_etag_keeps_the_dialog_and_requires_explicit_refresh_before_retry(public_collaboration_ui):
    ui = public_collaboration_ui
    ui.page.clock.install()
    open_management(ui, "pub-a")
    dialog = open_review(ui, "pending-publication")
    initial = copy.deepcopy(ui.review_state("pending-publication"))
    newer = changed_state(ui, "pending-publication", etag='"publication:concurrent-change"')
    rejected = ui.queue_decision(
        "pending-publication", "approve_artifact", expected_etag=initial["etag"], status=409,
        response={"error": "review_changed", "message": "Refresh the changed publication state."},
        publication_after=newer,
    )
    perform(ui, rejected, dialog.get_by_role("button", name="Approve publication", exact=True).click)
    expect(dialog.get_by_role("alert")).to_contain_text("Your input is kept")
    expect(dialog.get_by_role("button", name="Approve publication", exact=True)).to_be_disabled()
    ui.page.clock.fast_forward(10000)
    assert len(ui.operation_requests) == 1
    refresh_review(ui, "pending-publication")
    retry = ui.queue_decision(
        "pending-publication", "approve_artifact", expected_etag=newer["etag"], status=202,
        response=collaboration_receipt("pending-publication", "approve_artifact", "approved", status="queued"),
        publication_after=changed_state(
            ui, "pending-publication", etag='"publication:retried"',
            publication=publication(status="approved"),
        ),
    )
    perform(ui, retry, dialog.get_by_role("button", name="Approve publication", exact=True).click)
    expect(dialog.get_by_role("status").filter(has_text="Processing is queued, not complete")).to_be_visible()
    assert [entry.body["expected_etag"] for entry in ui.operation_requests] == [initial["etag"], newer["etag"]]


def test_missing_or_unknown_collaboration_handshake_hides_review(public_collaboration_ui):
    ui = public_collaboration_ui
    # An absent or unrecognised handshake is an interface hint, never an authorization: the
    # review affordance disappears rather than degrading into a partially enabled state.
    for handshake in (None, {"schema_version": 99, "operations": list(COLLABORATION_OPERATIONS)}):
        if handshake is None:
            ui.workspaces["pub-a"].pop("document_collaboration")
        else:
            ui.workspaces["pub-a"]["document_collaboration"] = handshake
        open_management(ui, "pub-a")
        expect(review_control(ui, "pending-publication")).to_have_count(0)
        expect(review_control(ui, "requested-publication")).to_have_count(0)
        assert_no_shared_place(ui)
        assert not ui.operation_requests


def test_per_document_collaboration_actions_gate_the_review_affordance(public_collaboration_ui):
    ui = public_collaboration_ui
    # withheld-document carries an empty inline document_collaboration_actions while the
    # workspace context still advertises the operations. The gate is per document, so no
    # review affordance appears for it even though the handshake is present.
    assert ui.record("withheld-document")["document_collaboration_actions"] == []
    open_management(ui, "pub-a")
    expect(review_control(ui, "pending-publication")).to_be_visible()
    expect(review_control(ui, "withheld-document")).to_have_count(0)
    assert not ui.operation_requests


def test_refused_set_active_leaves_a_publication_decision_working(public_collaboration_ui):
    ui = public_collaboration_ui
    # M3C pin: active state stays non-load-bearing on purpose. A refused or failed setActive
    # must leave a publication *decision* fully functional, because every decision targets the
    # immutable workspace path rather than the courtesy active selection.
    ui.set_active_failures.add("pub-b")
    open_management(ui, "pub-a")
    ui.page.get_by_role("combobox", name="Public workspace", exact=True).select_option("pub-b")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public/pub-b/documents")
    expect(details_button(ui, "same-document", "pub-b")).to_be_visible()
    attempted = [entry for entry in ui.writes if entry.path == "/api/public_workspaces/setActive"]
    assert attempted and attempted[-1].body == {"workspaceId": "pub-b"}
    assert ui.active_workspace == "pub-a"
    state = ui.review_state("pending-publication", "pub-b")
    dialog = open_review(ui, "pending-publication", "pub-b")
    reply = ui.queue_decision(
        "pending-publication", "approve_artifact", expected_etag=state["etag"], status=202,
        workspace_id="pub-b",
        response=collaboration_receipt(
            "pending-publication", "approve_artifact", "approved",
            public_workspace_id="pub-b", status="queued",
        ),
        records=[changed_record(
            ui, "pending-publication", "pub-b", generated_artifact_promotion_status="approved",
            document_actions=[], document_collaboration_actions=["inspect"],
        )],
        publication_after=changed_state(
            ui, "pending-publication", "pub-b", etag='"publication:pub-b:queued"',
            publication=publication(status="approved"),
        ),
    )
    perform(ui, reply, dialog.get_by_role("button", name="Approve publication", exact=True).click)
    expect(dialog.get_by_role("status").filter(has_text="Processing is queued, not complete")).to_be_visible()
    assert ui.operation_requests[-1].path == operation_path("pending-publication/artifact/approve", "pub-b")
    assert ui.active_workspace == "pub-a"


def test_shared_place_stays_absent_while_publication_review_is_live(public_collaboration_ui):
    ui = public_collaboration_ui
    # The M3C invariant, pinned positively: enabling publication review must not resurrect a
    # cross-workspace share relationship. Review is fully available, yet facets omit
    # shared_with_me, so no Shared place, no Share and no personal Save view control appears,
    # and the explorer never requests a shared place.
    open_management(ui, "pub-a")
    expect(review_control(ui, "pending-publication")).to_be_visible()
    assert_no_shared_place(ui)
    expect(filters(ui).get_by_role("button", name=re.compile(r"^Shared"))).to_have_count(0)
    shared_reads = [
        entry for entry in list_requests(ui)
        if "shared" in entry.query.get("place", [""])[0]
    ]
    assert not shared_reads, f"A shared place was requested for a public workspace: {shared_reads}"
    facets_response = next(
        payload for url, payload in ui.responses
        if urlsplit(url).path == "/api/public-workspaces/pub-a/documents/facets"
    )
    assert "shared_with_me" not in facets_response
    assert not ui.operation_requests


@pytest.mark.parametrize("theme,width,height,label", [
    ("light", 1440, 900, "dl"), ("dark", 1440, 900, "dd"),
    ("light", 390, 844, "ml"), ("dark", 390, 844, "md"),
])
def test_review_dialog_layout_in_both_themes(public_collaboration_ui, theme, width, height, label):
    ui = public_collaboration_ui
    open_management(ui, "pub-a", theme=theme, width=width, height=height)
    assert_no_shared_place(ui)
    dialog = open_review(ui, "pending-publication")
    expect(dialog.get_by_role("button", name="Approve publication", exact=True)).to_be_enabled()
    expect(dialog.get_by_role("button", name="Reject publication", exact=True)).to_be_enabled()
    ui.assert_no_overflow()
    card = dialog.locator(".glass-modal")
    dialog_bounds = card.bounding_box()
    assert dialog_bounds and dialog_bounds["x"] >= 0 and dialog_bounds["width"] <= width
    assert dialog_bounds["y"] >= 0 and dialog_bounds["y"] + dialog_bounds["height"] <= height + 1
    fits = card.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
    assert fits is True
    expect(ui.page.locator("html")).to_have_css("color-scheme", theme)
    REVIEW_SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    ui.page.screenshot(path=str(REVIEW_SCREENSHOTS / f"{label}-review.png"), full_page=True)
    dialog.get_by_role("button", name="Done", exact=True).click()
    expect(dialog).to_have_count(0)
    assert not ui.operation_requests
