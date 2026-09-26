# test_v2_public_directory.py
"""
Production-SPA coverage for the native V2 public workspace directory page.
Version: 0.261.184
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
public workspace does not offer, the whole-directory visibility tools (bulk show/hide, saved lists,
and the classic-chat hand-off, each acting across the server's pages), and both themes at both
breakpoints.
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
    REQUESTABLE_WORKSPACE, PENDING_WORKSPACE,
    REQUESTABLE_WORKSPACE_NAME, PENDING_WORKSPACE_NAME,
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
    expect(page.get_by_role("heading", name="Public Workspaces", exact=True)).to_be_visible()
    # A public workspace never offers agents: the section leaves the public registry (R5), so a deep
    # link to it lands on the shell's graceful "Section not found" empty state rather than a crash.
    expect(page.get_by_text("Section not found", exact=False)).to_be_visible()
    # The workspace context loads, but no document read fires for a section that never mounts them.
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/public-workspaces/")], (
        "A section that a public workspace does not offer must not trigger a document read."
    )


def create_posts(ui):
    return [
        entry for entry in ui.requests
        if entry.path == "/api/public_workspaces" and entry.method == "POST"
    ]


# --------------------------------------------------------------------------
# Create: the M10A affordance over the classic POST /api/public_workspaces, gated on the hint.
# --------------------------------------------------------------------------

def test_create_is_gated_on_the_server_hint(public_directory_ui):
    """Create is offered only when the directory hint allows it, never on the feature flag alone."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui)
    expect(page.get_by_role("button", name="Create public workspace", exact=True)).to_be_visible()


def test_create_is_hidden_when_the_hint_refuses(public_directory_ui):
    """With the feature on but the hint refusing (the classic create gate would 403), Create is gone."""
    ui, page = public_directory_ui, public_directory_ui.page
    ui.set_hints(can_create=False)
    open_directory(ui)
    expect(row(ui, LOGO_WORKSPACE_NAME)).to_be_visible()
    expect(page.get_by_role("button", name="Create public workspace", exact=True)).to_have_count(0)


def test_create_requires_a_name_before_calling_the_server(public_directory_ui):
    """The one client rule is a form nicety: a blank name never reaches the classic route."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui)
    page.get_by_role("button", name="Create public workspace", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Create public workspace", exact=True).click()
    expect(dialog.get_by_role("alert").filter(has_text="Enter a public workspace name.")).to_be_visible()
    assert not create_posts(ui), "A name the client rejects must never reach the classic create route."


def test_create_navigates_to_the_new_workspace_by_id(public_directory_ui):
    """A successful create deep-links to the new public workspace by its immutable id."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui)
    page.get_by_role("button", name="Create public workspace", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Public Workspace name", exact=True).fill("Open science library")
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/api/public_workspaces")
    ) as created:
        dialog.get_by_role("button", name="Create public workspace", exact=True).click()
    assert created.value.status == 201
    # The reuse is the classic create route, not a native directory POST, and it carries no active
    # handshake: the created workspace's own shell owns activation once we land on it by id.
    expect(page).to_have_url(re.compile(r"/v2/public/pub-created-1(?:[/?#]|$)"))


def test_a_role_refusal_shows_a_safe_message_keeps_the_draft_and_re_reads_the_hint(public_directory_ui):
    """A stale Create that the classic gate now 403s shows a safe message, keeps the draft, reloads."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui)
    before = len(directory_gets(ui))
    ui.create_refusal = "role"
    page.get_by_role("button", name="Create public workspace", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Public Workspace name", exact=True).fill("Denied library")
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/api/public_workspaces")
    ) as answered:
        dialog.get_by_role("button", name="Create public workspace", exact=True).click()
    assert answered.value.status == 403
    # The classic 403 body is never echoed (it can carry an internal message); a safe, status-derived
    # sentence is shown instead, and the reviewed permission wording names the surface.
    expect(dialog.get_by_role("alert").filter(has_text="You do not have permission to create a public workspace.")).to_be_visible()
    # The typed name survives the refusal, so a policy answer never eats the draft.
    expect(dialog.get_by_label("Public Workspace name", exact=True)).to_have_value("Denied library")
    # A refusal can only mean the hint went stale, so the directory is re-read.
    expect(page.get_by_role("button", name="Create public workspace", exact=True).first).to_be_visible()
    assert len(directory_gets(ui)) > before, "A create refusal must re-read the directory hint."


# --------------------------------------------------------------------------
# The self-service document-manager request, driven by the server's returned rows.
# --------------------------------------------------------------------------

def request_button(ui, name):
    return row(ui, name).get_by_role("button", name=f"Ask to manage documents in {name}", exact=True)


def cancel_button(ui, name):
    return row(ui, name).get_by_role("button", name=f"Cancel request for {name}", exact=True)


def test_request_then_cancel_follow_the_server_rows(public_directory_ui):
    """A request turns the row to Requested, a cancel turns it back, each from the server's `{workspace}`."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui)
    search_for(ui, REQUESTABLE_WORKSPACE_NAME)
    target = row(ui, REQUESTABLE_WORKSPACE_NAME)
    expect(request_button(ui, REQUESTABLE_WORKSPACE_NAME)).to_be_visible()

    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith(f"/api/public-workspaces/{REQUESTABLE_WORKSPACE}/membership/requests")
    ) as requested:
        request_button(ui, REQUESTABLE_WORKSPACE_NAME).click()
    assert requested.value.status == 201
    expect(target.get_by_text("Requested", exact=True)).to_be_visible()
    expect(cancel_button(ui, REQUESTABLE_WORKSPACE_NAME)).to_be_visible()
    expect(page.get_by_role("status").filter(has_text="was sent")).to_be_visible()

    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and response.url.endswith(f"/api/public-workspaces/{REQUESTABLE_WORKSPACE}/membership/requests")
    ) as cancelled:
        cancel_button(ui, REQUESTABLE_WORKSPACE_NAME).click()
    assert cancelled.value.status == 200
    expect(request_button(ui, REQUESTABLE_WORKSPACE_NAME)).to_be_visible()
    expect(target.get_by_text("Requested", exact=True)).to_have_count(0)
    # The request family never activates a workspace or loads a public context from the directory.
    assert_no_public_context_or_activation(ui)


def test_a_pending_row_starts_on_cancel_and_hides_the_request(public_directory_ui):
    """A row the server already reports pending shows the Requested pill and only a Cancel action."""
    ui = public_directory_ui
    open_directory(ui)
    search_for(ui, PENDING_WORKSPACE_NAME)
    pending = row(ui, PENDING_WORKSPACE_NAME)
    expect(pending.get_by_text("Requested", exact=True)).to_be_visible()
    expect(cancel_button(ui, PENDING_WORKSPACE_NAME)).to_be_visible()
    expect(pending.get_by_role("button", name=f"Ask to manage documents in {PENDING_WORKSPACE_NAME}", exact=True)).to_have_count(0)


def test_a_member_row_offers_no_request_control(public_directory_ui):
    """A member sees neither Ask nor Cancel: the affordance is gated on server membership, not a role check."""
    ui = public_directory_ui
    open_directory(ui)
    search_for(ui, MEMBER_WORKSPACE_NAME)
    member = row(ui, MEMBER_WORKSPACE_NAME)
    expect(member.get_by_role("button", name=f"Ask to manage documents in {MEMBER_WORKSPACE_NAME}", exact=True)).to_have_count(0)
    expect(member.get_by_role("button", name=f"Cancel request for {MEMBER_WORKSPACE_NAME}", exact=True)).to_have_count(0)


@pytest.mark.parametrize("workspace_id,workspace_name,code,action,message,expected", [
    (REQUESTABLE_WORKSPACE, REQUESTABLE_WORKSPACE_NAME, "already_member",
     "Ask to manage documents in", "You already manage this public workspace's documents.", "Open"),
    (REQUESTABLE_WORKSPACE, REQUESTABLE_WORKSPACE_NAME, "request_pending",
     "Ask to manage documents in", "You've already asked to manage this public workspace's documents.", "Cancel request for"),
    (PENDING_WORKSPACE, PENDING_WORKSPACE_NAME, "no_pending_request",
     "Cancel request for", "You don't have a pending request for this public workspace.", "Ask to manage documents in"),
])
def test_request_conflict_codes_reload_the_row(public_directory_ui, workspace_id, workspace_name, code, action, message, expected):
    """A stale-state 409 shows the server message and reloads, so the row settles on the truth."""
    ui, page = public_directory_ui, public_directory_ui.page
    ui.force_request_conflict(workspace_id, code)
    open_directory(ui)
    search_for(ui, workspace_name)
    row(ui, workspace_name).get_by_role("button", name=f"{action} {workspace_name}", exact=True).click()
    expect(page.get_by_role("status").filter(has_text=message)).to_be_visible()
    expect(row(ui, workspace_name).get_by_role("button", name=f"{expected} {workspace_name}", exact=False)).to_be_visible()


def test_a_write_conflict_keeps_the_row_for_a_plain_retry(public_directory_ui):
    """A public_workspace_write_conflict shows its message but keeps the row unchanged, no reload."""
    ui, page = public_directory_ui, public_directory_ui.page
    ui.force_request_conflict(REQUESTABLE_WORKSPACE, "public_workspace_write_conflict")
    open_directory(ui)
    search_for(ui, REQUESTABLE_WORKSPACE_NAME)
    request_button(ui, REQUESTABLE_WORKSPACE_NAME).click()
    expect(page.get_by_role("status").filter(has_text="The public workspace changed while your request was being saved")).to_be_visible()
    # No reconciliation, no reload: the request is still on offer for a plain retry.
    expect(request_button(ui, REQUESTABLE_WORKSPACE_NAME)).to_be_visible()


def test_a_workspace_not_found_reports_and_drops_the_row(public_directory_ui):
    """A 404 says the workspace is gone and reloads, so the vanished row leaves the list."""
    ui, page = public_directory_ui, public_directory_ui.page
    ui.force_request_conflict(REQUESTABLE_WORKSPACE, "workspace_not_found")
    open_directory(ui)
    search_for(ui, REQUESTABLE_WORKSPACE_NAME)
    request_button(ui, REQUESTABLE_WORKSPACE_NAME).click()
    expect(page.get_by_role("status").filter(has_text="The public workspace was not found.")).to_be_visible()
    expect(row(ui, REQUESTABLE_WORKSPACE_NAME)).to_have_count(0)


# --------------------------------------------------------------------------
# Visibility tools: bulk show/hide, saved lists, and the classic-chat hand-off.
#
# The bulk and saved-list controls act on the whole directory, which is server-paged, so the page
# walks the directory route at the server's largest page to cover every workspace rather than the
# page on screen. The single chat entry point hands off to the classic public chat -- V2 chat has
# no all-visible public scope (recorded exception, decision 31) -- and writes nothing itself.
# --------------------------------------------------------------------------

def all_directory_ids(ui):
    return set(ui.directory_workspaces)


def visibility_map(ui):
    return ui.preferences.get("publicDirectorySettings")


def saved_lists(ui):
    return ui.preferences.get("publicDirectorySavedLists")


def enumeration_gets(ui):
    """Directory reads at the server's largest page: the whole-directory walk, not the page load."""
    return [entry for entry in directory_gets(ui) if entry.query.get("page_size") == ["100"]]


def wrote_key(key):
    def _match(response):
        return (
            response.request.method == "POST"
            and response.url.endswith("/api/user/settings")
            and key in (response.request.post_data or "")
        )
    return _match


def stub_chat_navigation(ui):
    """Fulfil the classic aggregate-chat document navigation so the hand-off can be observed."""
    ui.page.context.route(
        "**/chats*",
        lambda route: route.fulfill(status=200, content_type="text/html",
                                    body="<!doctype html><title>chat</title>"),
    )


def test_show_all_makes_every_workspace_visible_and_reports_the_count(public_directory_ui):
    """Show all in chat writes true for every workspace across all pages, and reports the true count."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui)
    ids = all_directory_ids(ui)
    with page.expect_response(wrote_key("publicDirectorySettings")):
        page.get_by_role("button", name="Show all in chat", exact=True).click()
    written = visibility_map(ui)
    assert set(written) == ids and all(written.values()), (
        "Show all must make every workspace in the directory visible, not just the page on screen."
    )
    assert enumeration_gets(ui), "The bulk action must walk the directory at the server's largest page."
    expect(page.get_by_text(f"Made {len(ids)} workspaces visible in chat.", exact=False)).to_be_visible()


def test_hide_all_hides_every_workspace_and_reports_the_count(public_directory_ui):
    """Hide all from chat writes false for every workspace, and reports the count it wrote."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui)
    ids = all_directory_ids(ui)
    with page.expect_response(wrote_key("publicDirectorySettings")):
        page.get_by_role("button", name="Hide all from chat", exact=True).click()
    written = visibility_map(ui)
    assert set(written) == ids and not any(written.values()), "Hide all must hide every workspace."
    expect(page.get_by_text(f"Hid {len(ids)} workspaces from chat.", exact=False)).to_be_visible()


def test_a_bulk_action_preserves_entries_it_did_not_name(public_directory_ui):
    """A bulk write merges onto the stored map, so an entry for a since-removed workspace survives."""
    ui, page = public_directory_ui, public_directory_ui.page
    ui.seed_visibility({"ghost-ws": True})
    open_directory(ui)
    ids = all_directory_ids(ui)
    with page.expect_response(wrote_key("publicDirectorySettings")):
        page.get_by_role("button", name="Show all in chat", exact=True).click()
    written = visibility_map(ui)
    assert "ghost-ws" not in ids, "The stale id is genuinely absent from the directory."
    assert written.get("ghost-ws") is True, "A bulk action must preserve entries it did not name (R2)."
    assert all(written[identifier] is True for identifier in ids), "Every real workspace is visible."


def test_save_current_snapshots_the_whole_directory_by_default(public_directory_ui):
    """With no custom map every workspace is visible, so a saved list captures the whole directory."""
    ui, page = public_directory_ui, public_directory_ui.page
    open_directory(ui)
    ids = all_directory_ids(ui)
    page.get_by_placeholder("Name this visible set").fill("Everything")
    with page.expect_response(wrote_key("publicDirectorySavedLists")):
        page.get_by_role("button", name="Save current", exact=True).click()
    assert set(saved_lists(ui)["Everything"]) == ids, (
        "The default snapshot is the whole directory, applying the empty-map fallback."
    )
    assert enumeration_gets(ui), "Saving the default set walks the directory to enumerate it."
    expect(page.get_by_text(f'Saved "Everything" with {len(ids)} workspaces.', exact=False)).to_be_visible()


def test_save_current_snapshots_only_the_visible_ids_and_drops_stale(public_directory_ui):
    """A custom map's snapshot keeps only the visible ids that still exist, dropping a stale entry."""
    ui, page = public_directory_ui, public_directory_ui.page
    ui.seed_visibility({LOGO_WORKSPACE: True, "ghost-ws": True})
    open_directory(ui)
    page.get_by_placeholder("Name this visible set").fill("Just the atlas")
    with page.expect_response(wrote_key("publicDirectorySavedLists")):
        page.get_by_role("button", name="Save current", exact=True).click()
    assert saved_lists(ui)["Just the atlas"] == [LOGO_WORKSPACE], (
        "The snapshot keeps the one visible id and drops the stale one, like the classic snapshot."
    )
    expect(page.get_by_text('Saved "Just the atlas" with 1 workspace.', exact=False)).to_be_visible()


def test_use_this_list_replaces_the_map_with_only_the_list(public_directory_ui):
    """Using a saved list is a full replace: only its workspaces are visible and the rest are hidden."""
    ui, page = public_directory_ui, public_directory_ui.page
    ui.preferences["publicDirectorySavedLists"] = {"Pair": [LOGO_WORKSPACE, REQUESTABLE_WORKSPACE]}
    ui.seed_visibility({INACTIVE_WORKSPACE: True})
    open_directory(ui)
    page.get_by_label("Saved list", exact=True).select_option("Pair")
    with page.expect_response(wrote_key("publicDirectorySettings")):
        page.get_by_role("button", name="Use this list", exact=True).click()
    assert visibility_map(ui) == {LOGO_WORKSPACE: True, REQUESTABLE_WORKSPACE: True}, (
        "Using a list replaces the whole map with exactly the list's workspaces."
    )
    assert not enumeration_gets(ui), "A non-empty list needs no directory walk; the custom map hides the rest."
    expect(page.get_by_text("2 workspaces now visible in chat; the rest are hidden.", exact=False)).to_be_visible()


def test_use_an_empty_saved_list_hides_every_workspace(public_directory_ui):
    """An empty list cannot be a custom map, so applying it walks the directory to hide every id."""
    ui, page = public_directory_ui, public_directory_ui.page
    ui.preferences["publicDirectorySavedLists"] = {"Nothing visible": []}
    open_directory(ui)
    ids = all_directory_ids(ui)
    page.get_by_label("Saved list", exact=True).select_option("Nothing visible")
    with page.expect_response(wrote_key("publicDirectorySettings")):
        page.get_by_role("button", name="Use this list", exact=True).click()
    written = visibility_map(ui)
    assert set(written) == ids and not any(written.values()), "An empty list hides every workspace."
    assert enumeration_gets(ui), "The empty-list case walks the directory to build an all-hidden map."
    expect(page.get_by_text("All workspaces are now hidden from chat.", exact=False)).to_be_visible()


def test_delete_removes_only_the_named_list(public_directory_ui):
    """Deleting a saved list removes just that key and leaves every other list untouched."""
    ui, page = public_directory_ui, public_directory_ui.page
    ui.preferences["publicDirectorySavedLists"] = {
        "Alpha": [LOGO_WORKSPACE], "Beta": [REQUESTABLE_WORKSPACE],
    }
    open_directory(ui)
    page.get_by_label("Saved list", exact=True).select_option("Alpha")
    with page.expect_response(wrote_key("publicDirectorySavedLists")):
        page.get_by_role("button", name="Delete saved list Alpha", exact=True).click()
    assert saved_lists(ui) == {"Beta": [REQUESTABLE_WORKSPACE]}, "Delete removes only the named list."
    expect(page.get_by_text('Deleted the saved list "Alpha".', exact=False)).to_be_visible()


def test_chat_with_visible_opens_chat_and_writes_nothing(public_directory_ui):
    """Chat with visible (classic) hands off to the classic public chat without changing any preference."""
    ui, page = public_directory_ui, public_directory_ui.page
    stub_chat_navigation(ui)
    open_directory(ui)
    # The help text is exact about the destination: it is classic chat searching the visible
    # workspaces, not the classic workspace page, and the button itself writes nothing (decision 31).
    expect(page.get_by_text(
        "Opens classic chat, searching the public workspaces that are visible now. It changes nothing.",
        exact=False,
    )).to_be_visible()
    with page.expect_navigation(url=re.compile(r"/chats\?openSearch=1&scope=public"),
                                wait_until="domcontentloaded"):
        page.get_by_role("button", name="Chat with visible (classic)", exact=True).click()
    assert not visibility_writes(ui), "Chat with visible must not write any visibility preference."


def test_the_visibility_tools_are_hidden_on_an_empty_directory(public_directory_ui):
    """With nothing to curate -- an empty directory, no custom list, no saved lists -- the panel is gone."""
    ui, page = public_directory_ui, public_directory_ui.page
    ui.directory_workspaces = {}
    open_directory(ui)
    expect(page.get_by_role("group", name="Chat visibility for public workspaces", exact=True)).to_have_count(0)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
