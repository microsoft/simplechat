# test_v2_public_directory.py
"""
Production-SPA coverage for the native V2 public workspace directory page.
Version: 0.261.175
Implemented in: 0.261.175

Exercises the real public directory surface -- the browse-and-curate page built on the My Workspace
design system and driven by the public directory adapter -- against closed synthetic HTTP. The
fixture serves only the native routes the page reads and writes (`GET /api/public_workspaces/
directory`, the public `GET /api/public_workspaces/<id>/logo`, and the shared `/api/user/settings`
store the visibility toggle writes) and models the server's own rules, so a page that read a
personal resource, loaded a public workspace context from the directory, activated a workspace,
called the retired bare public list, or rendered a shape it could not verify would fail the run
rather than pass.

It pins the route reservation (no public context load and no `setActive` for `/public/directory`),
the view/search/paging URL state, Open deep-linking by immutable id, the public logo entitlement --
which, unlike a group, follows storage alone and is served to any caller regardless of membership --
a malformed envelope surfacing as a hard error rather than an empty directory, the visibility map's
exact rules (default-all-visible with the honest note, an additive one-entry write, and an
unavailable-status row that stays hideable and never errors), a graceful deep link into a section a
public workspace does not offer, and both themes at both breakpoints.
"""

import re

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.workspace_authoring import ORIGIN  # noqa: F401
from ui_tests.fixtures.public_directory import (  # noqa: F401
    PublicDirectoryFixture, public_directory_ui,
    MEMBER_WORKSPACE, LOGO_WORKSPACE, INACTIVE_WORKSPACE, UNKNOWN_WORKSPACE,
    MEMBER_WORKSPACE_NAME, LOGO_WORKSPACE_NAME, INACTIVE_WORKSPACE_NAME, UNKNOWN_WORKSPACE_NAME,
    LONG_WORKSPACE_NAME,
)


pytestmark = pytest.mark.ui

LAYOUTS = [
    pytest.param("light", 1440, 900, id="desktop-light"),
    pytest.param("dark", 1440, 900, id="desktop-dark"),
    pytest.param("light", 390, 844, id="mobile-light"),
    pytest.param("dark", 390, 844, id="mobile-dark"),
]

FIRST_FILLER = "Directory workspace 01"   # a page-1 none row with no stored logo.


# --------------------------------------------------------------------------
# Helpers.
# --------------------------------------------------------------------------

def open_directory(ui, **options):
    ui.open("/public/directory", **options)
    expect(ui.page.get_by_role("heading", name="Public directory", exact=True)).to_be_visible()


def row(ui, name):
    return ui.page.get_by_role("listitem").filter(has_text=name)


def search_for(ui, term):
    ui.page.get_by_placeholder("Search public workspaces by name or description").fill(term)


def directory_gets(ui):
    return [
        entry for entry in ui.requests
        if entry.path == "/api/public_workspaces/directory" and entry.method == "GET"
    ]


def logo_requests(ui, workspace_id):
    return [entry for entry in ui.requests if entry.path == f"/api/public_workspaces/{workspace_id}/logo"]


def visibility_writes(ui):
    return [entry for entry in ui.requests if entry.path == "/api/user/settings" and entry.method == "POST"]


def visibility_switch(ui, name):
    return ui.page.get_by_role("checkbox", name=f"Show {name} in public chat", exact=True)


def assert_no_public_context_or_activation(ui):
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/v2/workspaces/public/")], (
        "The directory page must not load any public workspace context."
    )
    assert not [entry for entry in ui.requests if entry.path == "/api/public_workspaces/setActive"], (
        "The directory page must never set an active public workspace."
    )


def assert_no_legacy_list(ui):
    assert not [
        entry for entry in ui.requests
        if entry.path == "/api/public_workspaces" and entry.method == "GET"
    ], "The directory page must never call the retired bare public list."


def assert_no_personal_reads(ui):
    assert not [
        entry for entry in ui.requests
        if entry.path.startswith("/api/documents") or entry.path.startswith("/api/public-workspaces/")
    ], "The directory page must not read any personal or per-workspace document resource."


def toggled_response(response):
    return (
        response.request.method == "POST"
        and response.url.endswith("/api/user/settings")
        and "publicDirectorySettings" in (response.request.post_data or "")
    )


# --------------------------------------------------------------------------
# Layout.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_directory_layout(public_directory_ui, theme, width, height):
    """The page matches the shell in both themes and both breakpoints, with no classic hand-off."""
    ui = public_directory_ui
    open_directory(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_placeholder("Search public workspaces by name or description")).to_be_visible()
    expect(ui.page.get_by_role("group", name="Directory view")).to_be_visible()
    expect(row(ui, LOGO_WORKSPACE_NAME)).to_be_visible()
    ui.assert_no_overflow()


# --------------------------------------------------------------------------
# Route reservation and scope.
# --------------------------------------------------------------------------

def test_directory_reserves_its_route(public_directory_ui):
    """`/public/directory` reads only the directory route; it is never treated as a workspace id."""
    ui = public_directory_ui
    open_directory(ui)
    expect(row(ui, LOGO_WORKSPACE_NAME)).to_be_visible()
    assert directory_gets(ui), "The page must load from the public directory route."
    assert_no_public_context_or_activation(ui)
    assert_no_legacy_list(ui)
    assert_no_personal_reads(ui)


# --------------------------------------------------------------------------
# Views, search and paging, all held in the URL.
# --------------------------------------------------------------------------

def test_views_filter_and_update_the_url(public_directory_ui):
    """Switching views filters to the server's membership and records the view in the URL."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui)
    page.get_by_role("button", name="My workspaces", exact=True).click()
    expect(row(ui, MEMBER_WORKSPACE_NAME)).to_be_visible()
    expect(row(ui, FIRST_FILLER)).to_have_count(0)
    assert "view=mine" in page.url

    page.get_by_role("button", name="All", exact=True).click()
    expect(row(ui, FIRST_FILLER)).to_be_visible()
    assert "view=all" in page.url


def test_search_filters_and_resets_paging(public_directory_ui):
    """A search narrows the list, records the term in the URL and returns to the first page."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui)
    search_for(ui, LOGO_WORKSPACE_NAME)
    expect(row(ui, LOGO_WORKSPACE_NAME)).to_be_visible()
    expect(row(ui, FIRST_FILLER)).to_have_count(0)
    assert "search=Atlas+library" in page.url or "search=Atlas%20library" in page.url
    assert "page=1" in page.url


def test_paging_walks_pages_via_the_url(public_directory_ui):
    """Paging moves through the filtered set and reflects the page in the URL and the controls."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui)
    expect(page.get_by_text("Page 1 of 2", exact=True)).to_be_visible()
    expect(row(ui, LOGO_WORKSPACE_NAME)).to_be_visible()

    page.get_by_role("button", name="Next workspaces", exact=True).click()
    expect(page.get_by_text("Page 2 of 2", exact=True)).to_be_visible()
    assert "page=2" in page.url
    expect(row(ui, UNKNOWN_WORKSPACE_NAME)).to_be_visible()
    expect(row(ui, LOGO_WORKSPACE_NAME)).to_have_count(0)
    expect(page.get_by_role("button", name="Next workspaces", exact=True)).to_be_disabled()


def test_an_out_of_range_url_page_is_clamped(public_directory_ui):
    """A hand-edited page far beyond the maximum is clamped into range, not sent as a repeatable 400."""
    ui, page = public_directory_ui, public_directory_ui.page
    ui.open("/public/directory?page=25000")
    expect(page.get_by_role("heading", name="Public directory", exact=True)).to_be_visible()
    gets = directory_gets(ui)
    assert gets, "The page must load from the public directory route."
    assert gets[-1].query.get("page") == ["10000"], (
        "An out-of-range URL page must be clamped to the server maximum before the request."
    )
    expect(page.get_by_role("alert").filter(has_text="The public directory could not be read")).to_have_count(0)


def test_a_search_over_the_limit_is_held_client_side(public_directory_ui):
    """A search past 200 code points shows the server's message, keeps the list and sends nothing."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui)
    expect(row(ui, LOGO_WORKSPACE_NAME)).to_be_visible()
    search_for(ui, "x" * 201)
    expect(page.get_by_role("alert").filter(has_text="Search terms can be at most 200 characters.")).to_be_visible()
    expect(row(ui, LOGO_WORKSPACE_NAME)).to_be_visible()
    assert not any("search" in entry.query for entry in directory_gets(ui)), (
        "A search over the code-point limit must never be sent to the server."
    )


# --------------------------------------------------------------------------
# Open.
# --------------------------------------------------------------------------

def test_open_navigates_by_id(public_directory_ui):
    """Open on a member row deep-links to the workspace by immutable id, not the picker's activate."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui)
    page.get_by_role("button", name="My workspaces", exact=True).click()
    row(ui, MEMBER_WORKSPACE_NAME).get_by_role("button", name=f"Open {MEMBER_WORKSPACE_NAME}", exact=True).click()
    expect(page).to_have_url(re.compile(rf"/v2/public/{re.escape(MEMBER_WORKSPACE)}(?:[/?#]|$)"))
    # The directory itself never activated a workspace; the shell it lands on owns any courtesy write.
    assert not [entry for entry in ui.requests if entry.path == "/api/public_workspaces/setActive"], (
        "Opening from the directory must not activate a workspace from the directory page."
    )


# --------------------------------------------------------------------------
# Logo entitlement: public logos follow storage alone, served to any caller.
# --------------------------------------------------------------------------

def test_a_public_logo_loads_for_any_caller_when_stored(public_directory_ui):
    """A stored public logo loads even for a non-member row; a row with none is never fetched."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui)
    expect(row(ui, LOGO_WORKSPACE_NAME)).to_be_visible()
    # LOGO_WORKSPACE is a non-member row whose logo the public directory still serves -- the public
    # difference from a group, where a stored logo on a non-member row is withheld.
    assert logo_requests(ui, LOGO_WORKSPACE), "A stored public logo must load regardless of membership."
    assert not logo_requests(ui, "pub-fill-01"), "A row with no stored logo must never request one."


# --------------------------------------------------------------------------
# Hard error.
# --------------------------------------------------------------------------

def test_a_malformed_list_is_a_hard_error(public_directory_ui):
    """A malformed envelope surfaces as a load error, never an empty directory."""
    ui, page = public_directory_ui, public_directory_ui.page
    ui.malformed_list = True
    open_directory(ui)
    expect(page.get_by_role("alert").filter(has_text="The public directory could not be read")).to_be_visible()
    expect(row(ui, LOGO_WORKSPACE_NAME)).to_have_count(0)
    expect(row(ui, FIRST_FILLER)).to_have_count(0)
    assert_no_public_context_or_activation(ui)


# --------------------------------------------------------------------------
# Long content: an 80-char name and a 500-char description stay contained.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_a_long_content_row_never_overflows(public_directory_ui, theme, width, height):
    """A maximal name and description stay inside the row at both breakpoints and themes."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui, theme=theme, width=width, height=height)
    search_for(ui, LONG_WORKSPACE_NAME)
    long_row = row(ui, LONG_WORKSPACE_NAME)
    expect(long_row).to_be_visible()
    # The visible Open label stays short; the full name rides in the accessible name via aria-label,
    # so an 80-character name can never stretch the shrink-0 action container.
    action = long_row.get_by_role("button", name=f"Open {LONG_WORKSPACE_NAME}", exact=True)
    expect(action).to_be_visible()
    assert action.inner_text().strip() == "Open"
    ui.assert_no_overflow()


# --------------------------------------------------------------------------
# Membership badges share the header's role labels.
# --------------------------------------------------------------------------

def test_membership_badges_use_the_shared_role_labels(public_directory_ui):
    """A member row's badge reads the friendly role label, not the raw stored role string."""
    ui, page = public_directory_ui, public_directory_ui.page
    # DocumentManager -> "Document manager". Mutating the seeded member row proves the badge shares
    # the header's mapping rather than printing the raw stored role.
    ui.directory_workspaces[MEMBER_WORKSPACE]["user_role"] = "DocumentManager"
    open_directory(ui)
    page.get_by_role("button", name="My workspaces", exact=True).click()
    expect(row(ui, MEMBER_WORKSPACE_NAME).get_by_text("Document manager", exact=True)).to_be_visible()
    expect(row(ui, MEMBER_WORKSPACE_NAME).get_by_text("DocumentManager", exact=True)).to_have_count(0)


# --------------------------------------------------------------------------
# Visibility: the per-user "visible for chat" map.
# --------------------------------------------------------------------------

def test_every_workspace_is_visible_by_default_with_an_honest_note(public_directory_ui):
    """With no custom map every row is visible and the page explains the default before any change."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui)
    expect(page.get_by_text("Every public workspace appears in chat by default", exact=False)).to_be_visible()
    expect(visibility_switch(ui, LOGO_WORKSPACE_NAME)).to_be_checked()
    expect(visibility_switch(ui, FIRST_FILLER)).to_be_checked()


def test_hiding_one_writes_only_that_entry(public_directory_ui):
    """A toggle from the default writes exactly the one workspace's entry, nothing else."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui)
    with page.expect_response(toggled_response):
        visibility_switch(ui, LOGO_WORKSPACE_NAME).uncheck(force=True)
    expect(visibility_switch(ui, LOGO_WORKSPACE_NAME)).not_to_be_checked()
    assert ui.preferences.get("publicDirectorySettings") == {LOGO_WORKSPACE: False}, (
        "Hiding one workspace must write only that entry, per the additive R2 ruling."
    )


def test_a_toggle_is_additive_over_a_stored_map(public_directory_ui):
    """A toggle composes on the stored map: it adds its entry and leaves the others untouched."""
    ui, page = public_directory_ui, public_directory_ui.page
    ui.seed_visibility({LOGO_WORKSPACE: True})
    open_directory(ui)
    # With a custom map the note is gone and a row absent from the map reads as hidden.
    expect(page.get_by_text("Every public workspace appears in chat by default", exact=False)).to_have_count(0)
    expect(visibility_switch(ui, LOGO_WORKSPACE_NAME)).to_be_checked()
    expect(visibility_switch(ui, FIRST_FILLER)).not_to_be_checked()

    with page.expect_response(toggled_response):
        visibility_switch(ui, FIRST_FILLER).check(force=True)
    assert ui.preferences.get("publicDirectorySettings") == {LOGO_WORKSPACE: True, "pub-fill-01": True}, (
        "A toggle must add its own entry and preserve every other stored entry unchanged."
    )


def test_an_unavailable_workspace_is_dimmed_but_still_hideable(public_directory_ui):
    """A status a reader cannot chat is labelled unavailable, but its visibility toggle still works."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui)
    search_for(ui, INACTIVE_WORKSPACE_NAME)
    target = row(ui, INACTIVE_WORKSPACE_NAME)
    expect(target).to_be_visible()
    expect(target.get_by_text("Not available for chat right now", exact=False)).to_be_visible()
    with page.expect_response(toggled_response):
        visibility_switch(ui, INACTIVE_WORKSPACE_NAME).uncheck(force=True)
    expect(visibility_switch(ui, INACTIVE_WORKSPACE_NAME)).not_to_be_checked()
    assert ui.preferences.get("publicDirectorySettings") == {INACTIVE_WORKSPACE: False}, (
        "Hiding an unavailable workspace is a valid choice and must write its entry, never error."
    )
    expect(page.get_by_role("alert")).to_have_count(0)


# --------------------------------------------------------------------------
# A deep link into a section a public workspace does not offer lands gracefully.
# --------------------------------------------------------------------------

def test_a_deep_link_into_an_unavailable_section_lands_gracefully(public_directory_ui):
    """`/public/<id>/agents` shows the workspace's graceful empty state, never a crash or a leak."""
    ui, page = public_directory_ui, public_directory_ui.page
    ui.open(f"/public/{MEMBER_WORKSPACE}/agents")
    expect(page.get_by_role("heading", name="Public workspaces", exact=True)).to_be_visible()
    # A public workspace never offers agents: the section leaves the public registry (R5), so a deep
    # link to it lands on the shell's graceful "Section not found" empty state rather than a crash.
    expect(page.get_by_text("Section not found", exact=False)).to_be_visible()
    # The workspace context loads, but no document read fires for a section that never mounts them.
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/public-workspaces/")], (
        "A section that a public workspace does not offer must not trigger a document read."
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
