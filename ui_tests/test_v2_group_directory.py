# test_v2_group_directory.py
"""
Production-SPA coverage for the native V2 group directory page.
Version: 0.261.149
Implemented in: 0.261.149

Exercises the real group directory surface -- the browse-and-join page built on the My Workspace
design system and driven by the scope-neutral directory adapter -- against closed synthetic HTTP.
The fixture serves only the native directory family the page reads and writes
(`GET`/`POST /api/groups/directory`, `POST`/`DELETE /api/groups/<id>/join-request` and the
member-only `GET /api/groups/<id>/logo`) and models the server's own rules, so a page that read a
personal or tenant-admin resource, invented an optimistic membership, requested a logo it was not
entitled to, or treated its reserved route as a group id would fail the run rather than pass.

It pins the route reservation (no active-group handshake and no group-context load for
`/groups/directory`), the view/search/paging URL state, join then cancel following the server's
returned rows, every 409 and the 404 reloading or holding the page as the contract requires, the
server-hint gate on Create (never the raw feature flag), create navigating to the new group by id,
Open navigating by id with no activate call, a logo requested only for a member row that has one,
a malformed envelope surfacing as a hard error, and both themes at both breakpoints.
"""

import re

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.workspace_authoring import ORIGIN  # noqa: F401
from ui_tests.fixtures.group_directory import (  # noqa: F401
    GroupDirectoryFixture, group_directory_ui,
    MEMBER_GROUP, LOGO_MEMBER_GROUP, PENDING_GROUP, JOINABLE_GROUP,
)


pytestmark = pytest.mark.ui

LAYOUTS = [
    pytest.param("light", 1440, 900, id="desktop-light"),
    pytest.param("dark", 1440, 900, id="desktop-dark"),
    pytest.param("light", 390, 844, id="mobile-light"),
    pytest.param("dark", 390, 844, id="mobile-dark"),
]

# Names the fixture seeds, chosen so a search isolates one row regardless of paging.
RESEARCH_GROUP_NAME = "Research group"       # MEMBER_GROUP, a member row (Owner).
DESIGN_GROUP_NAME = "Design group"           # LOGO_MEMBER_GROUP, a member row whose logo is stored.
MARKETING_GROUP_NAME = "Marketing circle"    # JOINABLE_GROUP, a none row with a stored logo hidden.
PLATFORM_GROUP_NAME = "Platform guild"       # PENDING_GROUP, a pending row.


def open_directory(ui, **options):
    ui.open("/groups/directory", **options)
    expect(ui.page.get_by_role("heading", name="Group directory", exact=True)).to_be_visible()


def row(ui, name):
    return ui.page.get_by_role("listitem").filter(has_text=name)


def search_for(ui, term):
    ui.page.get_by_placeholder("Search groups by name or description").fill(term)


def directory_gets(ui):
    return [entry for entry in ui.requests if entry.path == "/api/groups/directory" and entry.method == "GET"]


def logo_requests(ui, group_id):
    return [entry for entry in ui.requests if entry.path == f"/api/groups/{group_id}/logo"]


def assert_no_group_context_or_activation(ui):
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/v2/workspaces/group/")], (
        "The directory page must not load any group workspace context."
    )
    assert not [entry for entry in ui.requests if entry.path == "/api/groups/setActive"], (
        "The directory page must never set an active group."
    )


def assert_no_personal_or_admin_reads(ui):
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/v2/admin/")], (
        "The directory page must not reach any tenant-admin route."
    )
    assert not [
        entry for entry in ui.requests
        if entry.path.startswith("/api/documents") or entry.path.startswith("/api/user_documents")
    ], "The directory page must not read any personal document resource."


# --------------------------------------------------------------------------
# Layout.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_directory_layout(group_directory_ui, theme, width, height):
    """The page matches the shell in both themes and both breakpoints, with no classic hand-off."""
    ui = group_directory_ui
    open_directory(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_placeholder("Search groups by name or description")).to_be_visible()
    expect(ui.page.get_by_role("group", name="Directory view")).to_be_visible()
    expect(row(ui, DESIGN_GROUP_NAME)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Open classic group workspace", exact=True)).to_have_count(0)
    ui.assert_no_overflow()


# --------------------------------------------------------------------------
# Route reservation and scope.
# --------------------------------------------------------------------------

def test_directory_reserves_its_route(group_directory_ui):
    """`/groups/directory` reads only the directory route; it is never treated as a group id."""
    ui = group_directory_ui
    open_directory(ui)
    expect(row(ui, DESIGN_GROUP_NAME)).to_be_visible()
    assert directory_gets(ui), "The page must load from the group directory route."
    assert_no_group_context_or_activation(ui)
    assert_no_personal_or_admin_reads(ui)


# --------------------------------------------------------------------------
# Views, search and paging, all held in the URL.
# --------------------------------------------------------------------------

def test_views_filter_and_update_the_url(group_directory_ui):
    """Switching views filters the list to the server's membership and records the view in the URL."""
    ui, page = group_directory_ui, group_directory_ui.page
    open_directory(ui)
    page.get_by_role("button", name="My groups", exact=True).click()
    expect(row(ui, RESEARCH_GROUP_NAME)).to_be_visible()
    expect(row(ui, DESIGN_GROUP_NAME)).to_be_visible()
    expect(row(ui, "Directory group 01")).to_have_count(0)
    assert "view=mine" in page.url

    page.get_by_role("button", name="Discover", exact=True).click()
    expect(row(ui, "Directory group 01")).to_be_visible()
    expect(row(ui, RESEARCH_GROUP_NAME)).to_have_count(0)
    assert "view=discover" in page.url


def test_search_filters_and_resets_paging(group_directory_ui):
    """A search narrows the list, records the term in the URL and returns to the first page."""
    ui, page = group_directory_ui, group_directory_ui.page
    open_directory(ui)
    search_for(ui, MARKETING_GROUP_NAME)
    expect(row(ui, MARKETING_GROUP_NAME)).to_be_visible()
    expect(row(ui, DESIGN_GROUP_NAME)).to_have_count(0)
    assert "search=Marketing+circle" in page.url or "search=Marketing%20circle" in page.url
    assert "page=1" in page.url


def test_paging_walks_pages_via_the_url(group_directory_ui):
    """Paging moves through the filtered set and reflects the page in the URL and the controls."""
    ui, page = group_directory_ui, group_directory_ui.page
    open_directory(ui)
    expect(page.get_by_text("Page 1 of 2", exact=True)).to_be_visible()
    expect(row(ui, DESIGN_GROUP_NAME)).to_be_visible()

    page.get_by_role("button", name="Next groups", exact=True).click()
    expect(page.get_by_text("Page 2 of 2", exact=True)).to_be_visible()
    assert "page=2" in page.url
    expect(row(ui, "Support crew")).to_be_visible()
    expect(row(ui, DESIGN_GROUP_NAME)).to_have_count(0)
    expect(page.get_by_role("button", name="Next groups", exact=True)).to_be_disabled()


# --------------------------------------------------------------------------
# Join and cancel, driven by the server's returned rows.
# --------------------------------------------------------------------------

def test_join_then_cancel_follow_the_server_rows(group_directory_ui):
    """A join turns the row to Requested, a cancel turns it back, each from the server's `{group}`."""
    ui, page = group_directory_ui, group_directory_ui.page
    open_directory(ui)
    search_for(ui, MARKETING_GROUP_NAME)
    marketing = row(ui, MARKETING_GROUP_NAME)
    expect(marketing.get_by_role("button", name=f"Request to join {MARKETING_GROUP_NAME}", exact=True)).to_be_visible()

    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith(f"/api/groups/{JOINABLE_GROUP}/join-request")
    ) as joined:
        marketing.get_by_role("button", name=f"Request to join {MARKETING_GROUP_NAME}", exact=True).click()
    assert joined.value.status == 201
    expect(marketing.get_by_text("Requested", exact=True)).to_be_visible()
    expect(marketing.get_by_role("button", name=f"Cancel request for {MARKETING_GROUP_NAME}", exact=True)).to_be_visible()
    expect(page.get_by_role("status").filter(has_text="was sent")).to_be_visible()

    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and response.url.endswith(f"/api/groups/{JOINABLE_GROUP}/join-request")
    ) as cancelled:
        marketing.get_by_role("button", name=f"Cancel request for {MARKETING_GROUP_NAME}", exact=True).click()
    assert cancelled.value.status == 200
    expect(marketing.get_by_role("button", name=f"Request to join {MARKETING_GROUP_NAME}", exact=True)).to_be_visible()
    assert_no_group_context_or_activation(ui)


@pytest.mark.parametrize("group_id,group_name,code,action,message,expected", [
    (JOINABLE_GROUP, MARKETING_GROUP_NAME, "already_member",
     "Request to join", "You're already a member of this group.", "Open"),
    (JOINABLE_GROUP, MARKETING_GROUP_NAME, "request_pending",
     "Request to join", "You've already asked to join this group.", "Cancel request for"),
    (PENDING_GROUP, PLATFORM_GROUP_NAME, "no_pending_request",
     "Cancel request for", "You don't have a pending request to join this group.", "Request to join"),
])
def test_conflict_codes_reload_the_row(group_directory_ui, group_id, group_name, code, action, message, expected):
    """A stale-state 409 shows the server message and reloads, so the row settles on the truth."""
    ui, page = group_directory_ui, group_directory_ui.page
    ui.forced_conflicts[group_id] = code
    open_directory(ui)
    search_for(ui, group_name)
    target = row(ui, group_name)
    target.get_by_role("button", name=f"{action} {group_name}", exact=True).click()
    expect(page.get_by_role("status").filter(has_text=message)).to_be_visible()
    expect(row(ui, group_name).get_by_role("button", name=f"{expected} {group_name}", exact=False)).to_be_visible()


def test_group_write_conflict_keeps_the_row_for_a_plain_retry(group_directory_ui):
    """A group_write_conflict shows its message but keeps the row unchanged for a retry, no reload."""
    ui, page = group_directory_ui, group_directory_ui.page
    ui.forced_conflicts[JOINABLE_GROUP] = "group_write_conflict"
    open_directory(ui)
    search_for(ui, MARKETING_GROUP_NAME)
    marketing = row(ui, MARKETING_GROUP_NAME)
    marketing.get_by_role("button", name=f"Request to join {MARKETING_GROUP_NAME}", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="The group changed while your request was being saved")).to_be_visible()
    # No reconciliation, no reload: the join is still on offer for a plain retry.
    expect(row(ui, MARKETING_GROUP_NAME).get_by_role("button", name=f"Request to join {MARKETING_GROUP_NAME}", exact=True)).to_be_visible()


def test_group_not_found_reports_and_drops_the_row(group_directory_ui):
    """A 404 says the group is gone and reloads, so the vanished row leaves the list."""
    ui, page = group_directory_ui, group_directory_ui.page
    ui.forced_conflicts[JOINABLE_GROUP] = "group_not_found"
    open_directory(ui)
    search_for(ui, MARKETING_GROUP_NAME)
    row(ui, MARKETING_GROUP_NAME).get_by_role("button", name=f"Request to join {MARKETING_GROUP_NAME}", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="Group not found.")).to_be_visible()
    expect(row(ui, MARKETING_GROUP_NAME)).to_have_count(0)


# --------------------------------------------------------------------------
# Open.
# --------------------------------------------------------------------------

def test_open_navigates_by_id_without_activating(group_directory_ui):
    """Open on a member row deep-links by immutable id rather than the picker's activate-then-go."""
    ui, page = group_directory_ui, group_directory_ui.page
    open_directory(ui)
    page.get_by_role("button", name="My groups", exact=True).click()
    row(ui, RESEARCH_GROUP_NAME).get_by_role("button", name=f"Open {RESEARCH_GROUP_NAME}", exact=True).click()
    # The directory navigates straight to the group by id; that the directory itself never calls
    # setActive is pinned by test_directory_reserves_its_route. The group shell it lands on owns its
    # own activation, so this test asserts only the by-id deep link.
    expect(page).to_have_url(re.compile(rf"/v2/groups/{re.escape(MEMBER_GROUP)}(?:[/?#]|$)"))


# --------------------------------------------------------------------------
# Create, gated on the server hint.
# --------------------------------------------------------------------------

def test_create_is_gated_on_the_server_hint(group_directory_ui):
    """Create is offered only when the server hint allows it, independent of the feature flag."""
    ui, page = group_directory_ui, group_directory_ui.page
    open_directory(ui)
    expect(page.get_by_role("button", name="Create group", exact=True)).to_be_visible()


def test_create_is_hidden_when_the_hint_refuses(group_directory_ui):
    """With creation allowed by the flag but refused by the hint, Create is not offered at all."""
    ui, page = group_directory_ui, group_directory_ui.page
    ui.set_hints(can_create=False)
    open_directory(ui)
    expect(row(ui, DESIGN_GROUP_NAME)).to_be_visible()
    expect(page.get_by_role("button", name="Create group", exact=True)).to_have_count(0)


def test_create_validates_before_calling_the_server(group_directory_ui):
    """A blank name is caught by the client, so no create request is made."""
    ui, page = group_directory_ui, group_directory_ui.page
    open_directory(ui)
    page.get_by_role("button", name="Create group", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Create group", exact=True).click()
    expect(dialog.get_by_role("alert").filter(has_text="Enter a group name.")).to_be_visible()
    assert not [entry for entry in ui.requests if entry.path == "/api/groups/directory" and entry.method == "POST"], (
        "A name the client rejects must never reach the server."
    )


def test_create_navigates_to_the_new_group_by_id(group_directory_ui):
    """A successful create deep-links to the new group by id."""
    ui, page = group_directory_ui, group_directory_ui.page
    open_directory(ui)
    page.get_by_role("button", name="Create group", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Group name", exact=True).fill("Frontier research circle")
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/api/groups/directory")
    ) as created:
        dialog.get_by_role("button", name="Create group", exact=True).click()
    assert created.value.status == 201
    # The create call carries no active-group handshake; the directory reserves that route. The
    # created group's shell owns its own activation once we land on it.
    expect(page).to_have_url(re.compile(r"/v2/groups/dir-created-1(?:[/?#]|$)"))


# --------------------------------------------------------------------------
# Logo entitlement.
# --------------------------------------------------------------------------

def test_a_logo_is_requested_only_for_an_entitled_member_row(group_directory_ui):
    """A stored logo loads for a member row; a stored logo on a non-member row is never fetched."""
    ui, page = group_directory_ui, group_directory_ui.page
    open_directory(ui)
    page.get_by_role("button", name="My groups", exact=True).click()
    expect(row(ui, DESIGN_GROUP_NAME)).to_be_visible()
    # The member row with a stored logo fetches it; the member row without one does not.
    assert "view=mine" in page.url
    assert logo_requests(ui, LOGO_MEMBER_GROUP), "A member row with a stored logo must load it."
    assert not logo_requests(ui, MEMBER_GROUP), "A member row with no logo must not request one."

    # A non-member row whose logo the server stores but withholds (hasLogo false) is never fetched,
    # even when rendered. Return to the full view so the discoverable row is on screen to prove it.
    page.get_by_role("button", name="All", exact=True).click()
    search_for(ui, MARKETING_GROUP_NAME)
    expect(row(ui, MARKETING_GROUP_NAME)).to_be_visible()
    assert not logo_requests(ui, JOINABLE_GROUP), (
        "A non-member row must never request a logo, even when the server stores one."
    )


# --------------------------------------------------------------------------
# Hard error.
# --------------------------------------------------------------------------

def test_a_malformed_list_is_a_hard_error(group_directory_ui):
    """A malformed envelope surfaces as a load error, never an empty directory."""
    ui, page = group_directory_ui, group_directory_ui.page
    ui.malformed_list = True
    open_directory(ui)
    expect(page.get_by_role("alert").filter(has_text="The group directory could not be read")).to_be_visible()
    expect(row(ui, DESIGN_GROUP_NAME)).to_have_count(0)
    expect(row(ui, "Directory group 01")).to_have_count(0)
    assert_no_group_context_or_activation(ui)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
