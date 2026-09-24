# test_v2_group_members.py
"""
Production-SPA coverage for the native V2 group Members section.
Version: 0.261.155
Implemented in: 0.261.155

Exercises the real Members section -- a section of the group WorkspaceShell in its Manage group,
built on the M7B native membership routes -- against closed synthetic HTTP. The fixture
(`ui_tests/fixtures/group_members.py`) serves only the native membership family and the directory
people search, runs the real membership policy module for every hint, and models the server's
owner, status, pending-request, transfer and directory rules with their exact messages, so a page
that read a personal, tenant-admin or classic membership route, invented a control the hints
withhold, or kept an optimistic row would fail the run rather than pass.

It pins one navigation tree (Members in the rail and on the overview, no second button), reads and
gating for every role and status, the search, role filter and page in the URL, add with each
directory outcome, CSV import with mixed results and a retry of the failed rows, role change with
the self-demotion confirmation, remove, leave, bulk role change and bulk remove with per-item
results, transfer with its consequences, approve and reject with `already_member` and
`no_pending_request` as already handled, every refusal the page handles, a malformed envelope as a
hard error, and both themes at both breakpoints with a member at the server's text maxima.
"""

import re

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.workspace_authoring import ORIGIN, OWNER_ID  # noqa: F401
from ui_tests.fixtures.group_members import (  # noqa: F401
    GroupMembersFixture, group_members_ui,
    ALREADY_MEMBER_MESSAGE, LEE, LONG_NAME, MAYA, MEMBERSHIP_PERMISSION_MESSAGE, NIA, NORA,
    OLIVIA, OWNER_LEAVE_MESSAGE, OWNER_ROLE_MESSAGE, PRIYA,
    STATUS_UNAVAILABLE_MESSAGE, USER_NOT_FOUND_MESSAGE, USER_SEARCH_TIMEOUT_MESSAGE, VIEWER_NAME,
    WRITE_CONFLICT_MESSAGE, guid,
)


pytestmark = pytest.mark.ui

LAYOUTS = [
    pytest.param("light", 1440, 900, id="desktop-light"),
    pytest.param("dark", 1440, 900, id="desktop-dark"),
    pytest.param("light", 390, 844, id="mobile-light"),
    pytest.param("dark", 390, 844, id="mobile-dark"),
]

MEMBERS_PATH = "/api/groups/group-a/membership/members"
REQUESTS_PATH = "/api/groups/group-a/membership/requests"


# --------------------------------------------------------------------------
# Helpers.
# --------------------------------------------------------------------------

def open_members(ui, group="group-a", **options):
    ui.open(f"/groups/{group}/members", **options)
    expect(ui.page.get_by_role("heading", name="Members", exact=True)).to_be_visible()


def member_list(ui):
    return ui.page.get_by_role("list", name="Members", exact=True)


def row(ui, name):
    return member_list(ui).get_by_role("listitem").filter(has_text=name)


def request_row(ui, name):
    return ui.page.get_by_role("list", name="Requests to join", exact=True).get_by_role("listitem").filter(has_text=name)


def dialog(ui, name):
    return ui.page.get_by_role("dialog", name=name, exact=True)


def calls(ui, method, path):
    return [entry for entry in ui.requests if entry.method == method and entry.path == path]


def alert(ui, text):
    return ui.page.get_by_role("alert").filter(has_text=text)


def status_text(ui, text):
    return ui.page.get_by_text(text, exact=True)


def wait_until(ui, predicate, timeout_ms=5000):
    """Wait for a fixture-side condition, such as a request the page is about to send."""
    waited = 0
    while not predicate():
        assert waited < timeout_ms, "The expected request was never made."
        ui.page.wait_for_timeout(50)
        waited += 50


def assert_no_foreign_membership_traffic(ui):
    """Only the native membership family, the people search and the shell's own reads."""
    for entry in ui.requests:
        path = entry.path
        if not path.startswith("/api/"):
            continue
        assert not re.match(r"^/api/groups/[^/]+/(members|requests|transferOwnership)(/|$)", path), (
            f"The Members section reached a classic membership route: {entry.method} {path}"
        )
        assert not path.startswith("/api/v2/admin/"), f"The Members section reached an admin route: {path}"


def add_person(ui, search, choose, role="User"):
    page = ui.page
    page.get_by_role("button", name="Add member", exact=True).click()
    add = dialog(ui, "Add a member")
    add.get_by_label("Search the directory").fill(search)
    add.get_by_role("button", name=f"Choose {choose}", exact=True).click()
    add.get_by_label("Role for the new member").select_option(role)
    add.get_by_role("button", name="Add member", exact=True).click()
    return add


# --------------------------------------------------------------------------
# Layout and navigation.
# --------------------------------------------------------------------------

def assert_controls_fit(ui):
    """Every visible control lies inside the viewport, so nothing is clipped by a scroll container."""
    clipped = ui.page.evaluate("""() => {
        const width = window.innerWidth;
        return [...document.querySelectorAll('main button, main select, main input, main a')]
            .filter((element) => {
                const box = element.getBoundingClientRect();
                return box.width > 0 && box.height > 0 && (box.right > width + 1 || box.left < -1);
            })
            .map((element) => element.getAttribute('aria-label') || element.textContent.trim());
    }""")
    assert not clipped, f"Controls extend past the viewport: {clipped}"


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_members_layout(group_members_ui, theme, width, height):
    """Both themes at both breakpoints, with a member at the server's 256-character maxima."""
    ui = group_members_ui
    open_members(ui, theme=theme, width=width, height=height)
    expect(row(ui, "Olivia Admin")).to_be_visible()
    long_member = row(ui, LONG_NAME[:40])
    expect(long_member).to_be_visible()
    expect(request_row(ui, "Priya Pending")).to_be_visible()
    expect(ui.page.get_by_role("button", name="Add member", exact=True)).to_be_visible()
    ui.assert_no_overflow()
    assert_controls_fit(ui)
    long_member.scroll_into_view_if_needed()
    assert_controls_fit(ui)
    assert_no_foreign_membership_traffic(ui)


def test_members_is_a_section_of_the_one_workspace_navigation(group_members_ui):
    """Members sits in the rail's Manage group and on the overview; the header adds no second tree."""
    ui, page = group_members_ui, group_members_ui.page
    ui.open("/groups/group-a")
    nav = page.get_by_role("navigation", name="Workspace sections", exact=True)
    expect(nav.get_by_text("Manage", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Manage", exact=True)).to_be_visible()
    expect(page.get_by_role("link").filter(has_text="Who belongs to this group, their roles, and who is asking to join.")).to_be_visible()
    # M7C landed native Settings/Activity/Statistics, so an active group no longer hands off to
    # classic from the header; the button now survives only for inactive or unknown statuses (§8.9).
    expect(page.get_by_role("button", name=re.compile("Manage group \\(classic\\)"))).to_have_count(0)
    expect(page.get_by_role("button", name=re.compile("members", re.IGNORECASE))).to_have_count(0)
    assert not ui.membership_requests(), "The overview must not read the member list."
    nav.get_by_role("link", name="Members", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/groups/group-a/members")
    expect(page.get_by_role("heading", name="Members", exact=True)).to_be_visible()
    expect(row(ui, "Olivia Admin")).to_be_visible()


def test_a_stray_segment_on_members_opens_the_section(group_members_ui):
    """Members has no item route, so /members/<id> opens the section itself, as every other section
    without one does, rather than waiting on a view that never renders."""
    ui, page = group_members_ui, group_members_ui.page
    ui.open("/groups/group-a/members/not-a-member-route")
    expect(page).to_have_url(f"{ORIGIN}/v2/groups/group-a/members")
    expect(page.get_by_role("heading", name="Members", exact=True)).to_be_visible()
    expect(row(ui, "Olivia Admin")).to_be_visible()
    expect(page.get_by_text("Opening the requested view...", exact=True)).to_have_count(0)


# --------------------------------------------------------------------------
# Reads and gating.
# --------------------------------------------------------------------------

def test_the_owner_gets_every_control_the_hints_offer(group_members_ui):
    ui, page = group_members_ui, group_members_ui.page
    open_members(ui)
    [listing] = calls(ui, "GET", MEMBERS_PATH)
    assert listing.query == {"page": ["1"], "page_size": ["20"]}
    assert calls(ui, "GET", REQUESTS_PATH), "The owner reviews requests, so the list is read."
    expect(page.get_by_role("button", name="Import CSV", exact=True)).to_be_visible()
    olivia = row(ui, "Olivia Admin")
    expect(olivia.get_by_label("Role for Olivia Admin")).to_have_value("Admin")
    expect(olivia.get_by_role("button", name="Make Olivia Admin the owner", exact=True)).to_be_visible()
    expect(olivia.get_by_role("button", name="Remove Olivia Admin", exact=True)).to_be_visible()
    me = row(ui, VIEWER_NAME)
    expect(me.get_by_text("You", exact=True)).to_be_visible()
    expect(me.get_by_text("Owner", exact=True)).to_be_visible()
    expect(me.get_by_role("combobox")).to_have_count(0)
    expect(me.get_by_role("button")).to_have_count(0)
    expect(me.get_by_role("checkbox")).to_have_count(0)
    expect(page.get_by_text("Showing 20 of 24 members", exact=True)).to_be_visible()


def test_an_admin_manages_members_but_not_ownership(group_members_ui):
    ui, page = group_members_ui, group_members_ui.page
    ui.set_viewer_role("group-a", "Admin")
    open_members(ui)
    owner = row(ui, "Omar Owner")
    expect(owner.get_by_text("Owner", exact=True)).to_be_visible()
    expect(owner.get_by_role("button")).to_have_count(0)
    expect(owner.get_by_role("combobox")).to_have_count(0)
    maya = row(ui, "Maya Member")
    expect(maya.get_by_label("Role for Maya Member")).to_be_visible()
    expect(maya.get_by_role("button", name="Remove Maya Member", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("the owner$"))).to_have_count(0)
    me = row(ui, VIEWER_NAME)
    expect(me.get_by_label(f"Role for {VIEWER_NAME}")).to_have_value("Admin")
    expect(me.get_by_role("button", name="Leave this group", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Add member", exact=True)).to_be_visible()
    expect(request_row(ui, "Sam Seeker")).to_be_visible()


@pytest.mark.parametrize("role", ["DocumentManager", "User"])
def test_other_members_see_the_list_and_can_only_leave(group_members_ui, role):
    ui, page = group_members_ui, group_members_ui.page
    ui.set_viewer_role("group-a", role)
    open_members(ui)
    expect(row(ui, "Olivia Admin")).to_be_visible()
    expect(member_list(ui).get_by_role("combobox")).to_have_count(0)
    expect(member_list(ui).get_by_role("checkbox")).to_have_count(0)
    expect(page.get_by_role("button", name="Add member", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Import CSV", exact=True)).to_have_count(0)
    expect(page.get_by_role("heading", name="Requests to join", exact=True)).to_have_count(0)
    expect(row(ui, VIEWER_NAME).get_by_role("button", name="Leave this group", exact=True)).to_be_visible()
    expect(member_list(ui).get_by_role("button")).to_have_count(1)
    assert not calls(ui, "GET", REQUESTS_PATH), "Only the owner and admins read the pending requests."


def test_a_locked_group_hides_adding_but_keeps_the_rest(group_members_ui):
    ui, page = group_members_ui, group_members_ui.page
    ui.set_viewer_role("group-a", "Owner", status="locked")
    open_members(ui)
    expect(row(ui, "Maya Member").get_by_label("Role for Maya Member")).to_be_visible()
    expect(row(ui, "Maya Member").get_by_role("button", name="Remove Maya Member", exact=True)).to_be_visible()
    expect(request_row(ui, "Priya Pending")).to_be_visible()
    expect(page.get_by_role("button", name="Add member", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Import CSV", exact=True)).to_have_count(0)


def test_an_inactive_group_offers_no_members_section(group_members_ui):
    ui, page = group_members_ui, group_members_ui.page
    ui.set_viewer_role("group-a", "Owner", status="inactive")
    ui.open("/groups/group-a/members")
    expect(page.get_by_text("Members is not available", exact=True)).to_be_visible()
    expect(page.get_by_text("This group is inactive.", exact=True)).to_be_visible()
    assert not ui.membership_requests(), "An unavailable section must not read the membership routes."


def test_search_role_filter_and_page_live_in_the_url(group_members_ui):
    ui, page = group_members_ui, group_members_ui.page
    open_members(ui)
    page.get_by_role("button", name="Next page", exact=True).click()
    expect(page).to_have_url(re.compile(r"/v2/groups/group-a/members\?page=2$"))
    expect(row(ui, "Teammate 18")).to_be_visible()
    assert calls(ui, "GET", MEMBERS_PATH)[-1].query == {"page": ["2"], "page_size": ["20"]}
    page.get_by_label("Filter by role").select_option("Admin")
    expect(page).to_have_url(re.compile(r"\?role=Admin$"))
    expect(row(ui, "Olivia Admin")).to_be_visible()
    expect(member_list(ui).get_by_role("listitem")).to_have_count(1)
    page.get_by_placeholder("Search members by name or email").fill("oli")
    expect(page).to_have_url(re.compile(r"\?role=Admin&search=oli$"))
    assert calls(ui, "GET", MEMBERS_PATH)[-1].query == {
        "search": ["oli"], "role": ["Admin"], "page": ["1"], "page_size": ["20"],
    }
    page.go_back()
    expect(page).to_have_url(re.compile(r"\?page=2$"))
    expect(row(ui, "Teammate 18")).to_be_visible()


# --------------------------------------------------------------------------
# Add.
# --------------------------------------------------------------------------

def test_add_uses_the_directory_and_shows_the_server_row(group_members_ui):
    """The search reads /api/userSearch; the added row is the one the server resolved by id."""
    ui = group_members_ui
    ui.directory_by_id[NORA["userId"]] = {"id": NORA["userId"], "displayName": "Nora Newcomer (Research)",
                                          "email": NORA["email"]}
    open_members(ui)
    add_person(ui, "Nora", "Nora Newcomer", role="Admin")
    expect(status_text(ui, "Nora Newcomer (Research) was added as Admin.")).to_be_visible()
    expect(dialog(ui, "Add a member")).to_have_count(0)
    [search] = calls(ui, "GET", "/api/userSearch")
    assert search.query == {"query": ["Nora"]}
    [added] = calls(ui, "POST", MEMBERS_PATH)
    assert added.body == {"userId": NORA["userId"], "displayName": "Nora Newcomer", "email": NORA["email"], "role": "Admin"}
    expect(row(ui, "Nora Newcomer (Research)").get_by_label("Role for Nora Newcomer (Research)")).to_have_value("Admin")


def test_add_refusals_about_the_person_keep_the_dialog_open(group_members_ui):
    ui = group_members_ui
    open_members(ui)
    add = add_person(ui, "Nia", "Nia Unlisted")
    expect(add.get_by_role("alert").filter(has_text=USER_NOT_FOUND_MESSAGE)).to_be_visible()
    add.get_by_label("Search the directory").fill("Maya")
    add.get_by_role("button", name="Choose Maya Member", exact=True).click()
    add.get_by_role("button", name="Add member", exact=True).click()
    expect(add.get_by_role("alert").filter(has_text=ALREADY_MEMBER_MESSAGE)).to_be_visible()
    add.get_by_role("button", name="Cancel", exact=True).click()
    expect(add).to_have_count(0)
    assert len(calls(ui, "POST", MEMBERS_PATH)) == 2


def test_add_with_the_directory_unavailable_uses_the_submitted_details(group_members_ui):
    ui = group_members_ui
    ui.directory_available = False
    open_members(ui)
    add_person(ui, "Nora", "Nora Newcomer")
    expect(status_text(ui, "Nora Newcomer was added as Member.")).to_be_visible()
    expect(row(ui, "Nora Newcomer").get_by_label("Role for Nora Newcomer")).to_have_value("User")


def test_a_group_locked_after_loading_closes_the_add_dialog(group_members_ui):
    ui, page = group_members_ui, group_members_ui.page
    open_members(ui)
    ui.set_status("group-a", "locked")
    add_person(ui, "Nora", "Nora Newcomer")
    expect(dialog(ui, "Add a member")).to_have_count(0)
    expect(alert(ui, STATUS_UNAVAILABLE_MESSAGE)).to_be_visible()
    expect(page.get_by_role("button", name="Add member", exact=True)).to_have_count(0)


def test_a_failed_directory_search_is_reported_in_the_dialog(group_members_ui):
    ui, page = group_members_ui, group_members_ui.page
    ui.user_search_failure = (504, USER_SEARCH_TIMEOUT_MESSAGE)
    open_members(ui)
    page.get_by_role("button", name="Add member", exact=True).click()
    add = dialog(ui, "Add a member")
    add.get_by_label("Search the directory").fill("Nora")
    expect(add.get_by_role("alert").filter(has_text=f"The directory search isn't available: {USER_SEARCH_TIMEOUT_MESSAGE}")).to_be_visible()
    expect(add.get_by_role("button", name="Add member", exact=True)).to_be_disabled()


# --------------------------------------------------------------------------
# CSV import.
# --------------------------------------------------------------------------

def csv_file(text):
    return {"name": "members.csv", "mimeType": "text/csv", "buffer": text.encode("utf-8")}


def test_csv_import_reports_each_row_and_retries_only_the_failed_ones(group_members_ui):
    ui, page = group_members_ui, group_members_ui.page
    extra = {"id": guid(20), "displayName": "Quinn Csv", "email": "quinn.csv@example.test"}
    ui.directory[extra["id"]] = extra
    ui.force_conflict("POST", "members")
    open_members(ui)
    page.get_by_role("button", name="Import CSV", exact=True).click()
    importer = dialog(ui, "Import members from CSV")
    importer.get_by_label("CSV file").set_input_files(csv_file("\n".join([
        "userId,displayName,email,role",
        f"{extra['id']},Quinn Csv,quinn.csv@example.test,document_manager",
        f"{NORA['userId']},Nora Newcomer,nora.newcomer@example.test,admin",
        f"{MAYA['userId']},Maya Member,maya.member@example.test,user",
        f"{NIA['userId']},Nia Unlisted,nia.unlisted@example.test,user",
    ])))
    expect(importer.get_by_text("4 members are ready to add.", exact=True)).to_be_visible()
    importer.get_by_role("button", name="Add 4 members", exact=True).click()
    expect(importer.get_by_text("1 added, 1 already a member, 2 failed.", exact=True)).to_be_visible()
    results = importer.get_by_role("list", name="Import results", exact=True)
    expect(results.get_by_role("listitem").filter(has_text="Quinn Csv")).to_contain_text(WRITE_CONFLICT_MESSAGE)
    expect(results.get_by_role("listitem").filter(has_text="Nora Newcomer")).to_contain_text("Added")
    expect(results.get_by_role("listitem").filter(has_text="Maya Member")).to_contain_text("Already a member")
    expect(results.get_by_role("listitem").filter(has_text="Nia Unlisted")).to_contain_text(USER_NOT_FOUND_MESSAGE)
    posts = calls(ui, "POST", MEMBERS_PATH)
    assert [entry.body["role"] for entry in posts] == ["DocumentManager", "Admin", "User", "User"]
    importer.get_by_role("button", name="Retry 2 failed rows", exact=True).click()
    expect(importer.get_by_text("2 added, 1 already a member, 1 failed.", exact=True)).to_be_visible()
    retried = calls(ui, "POST", MEMBERS_PATH)[len(posts):]
    assert [entry.body["userId"] for entry in retried] == [extra["id"], NIA["userId"]]
    importer.get_by_role("button", name="Done", exact=True).click()
    expect(row(ui, "Quinn Csv").get_by_label("Role for Quinn Csv")).to_have_value("DocumentManager")
    expect(row(ui, "Nora Newcomer").get_by_label("Role for Nora Newcomer")).to_have_value("Admin")


def test_csv_import_refuses_a_file_the_classic_page_refuses(group_members_ui):
    ui, page = group_members_ui, group_members_ui.page
    open_members(ui)
    page.get_by_role("button", name="Import CSV", exact=True).click()
    importer = dialog(ui, "Import members from CSV")
    importer.get_by_label("CSV file").set_input_files(csv_file("name,email\nNora,nora@example.test\n"))
    expect(importer.get_by_role("alert")).to_contain_text("Invalid header. Expected: userId,displayName,email,role")
    importer.get_by_label("CSV file").set_input_files(csv_file("\n".join([
        "userId,displayName,email,role", "not-a-guid,Nora,nora@example.test,user",
        f"{NORA['userId']},Nora,nora@example.test,owner",
    ])))
    refusal = importer.get_by_role("alert")
    expect(refusal).to_contain_text("Row 2: Invalid GUID format for userId")
    expect(refusal).to_contain_text("Row 3: Invalid role 'owner'. Must be: user, admin, or document_manager")
    expect(importer.get_by_role("button", name="Add members", exact=True)).to_be_disabled()
    assert not calls(ui, "POST", MEMBERS_PATH)


# --------------------------------------------------------------------------
# Role change, remove and leave.
# --------------------------------------------------------------------------

def test_role_change_writes_the_role_and_reloads(group_members_ui):
    ui = group_members_ui
    open_members(ui)
    row(ui, "Maya Member").get_by_label("Role for Maya Member").select_option("DocumentManager")
    expect(status_text(ui, "Maya Member's role is now Document manager.")).to_be_visible()
    [change] = calls(ui, "PATCH", f"{MEMBERS_PATH}/{MAYA['userId']}")
    assert change.body == {"role": "DocumentManager"}
    expect(row(ui, "Maya Member").get_by_label("Role for Maya Member")).to_have_value("DocumentManager")


def test_an_admin_demoting_themselves_confirms_first_and_loses_management(group_members_ui):
    ui, page = group_members_ui, group_members_ui.page
    ui.set_viewer_role("group-a", "Admin")
    open_members(ui)
    mine = row(ui, VIEWER_NAME).get_by_label(f"Role for {VIEWER_NAME}")
    mine.select_option("User")
    confirm = dialog(ui, "Change your own role?")
    expect(confirm).to_contain_text("You'll no longer be able to manage this group's members.")
    confirm.get_by_role("button", name="Cancel", exact=True).click()
    expect(confirm).to_have_count(0)
    expect(mine).to_have_value("Admin")
    assert not calls(ui, "PATCH", f"{MEMBERS_PATH}/{OWNER_ID}")
    mine.select_option("User")
    dialog(ui, "Change your own role?").get_by_role("button", name="Change my role", exact=True).click()
    expect(status_text(ui, "Your role is now Member.")).to_be_visible()
    expect(page.get_by_text("Role: Member", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Add member", exact=True)).to_have_count(0)
    expect(member_list(ui).get_by_role("combobox")).to_have_count(0)
    patch = calls(ui, "PATCH", f"{MEMBERS_PATH}/{OWNER_ID}")
    assert [entry.body for entry in patch] == [{"role": "User"}]
    after = ui.requests[ui.requests.index(patch[0]):]
    assert any(entry.path == "/api/v2/workspaces/group/group-a" for entry in after), (
        "The workspace context is re-read after a self-demotion."
    )
    assert not [entry for entry in after if entry.path == REQUESTS_PATH], (
        "Once the caller lost management, the request list must not be read again."
    )


def test_remove_confirms_then_removes(group_members_ui):
    ui = group_members_ui
    open_members(ui)
    row(ui, "Lee Reader").get_by_role("button", name="Remove Lee Reader", exact=True).click()
    confirm = dialog(ui, "Remove Lee Reader?")
    expect(confirm).to_contain_text("Lee Reader will lose access to Research group")
    confirm.get_by_role("button", name="Remove member", exact=True).click()
    expect(status_text(ui, "Lee Reader was removed from the group.")).to_be_visible()
    expect(row(ui, "Lee Reader")).to_have_count(0)
    [removal] = calls(ui, "DELETE", f"{MEMBERS_PATH}/{LEE['userId']}")
    assert removal.body is None and removal.query == {}


def test_leave_confirms_then_returns_to_groups(group_members_ui):
    ui, page = group_members_ui, group_members_ui.page
    ui.set_viewer_role("group-a", "User")
    open_members(ui)
    row(ui, VIEWER_NAME).get_by_role("button", name="Leave this group", exact=True).click()
    confirm = dialog(ui, "Leave Research group?")
    confirm.get_by_role("button", name="Leave group", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/groups")
    expect(page.get_by_text("Choose a group workspace", exact=True)).to_be_visible()
    [leave] = calls(ui, "DELETE", f"{MEMBERS_PATH}/{OWNER_ID}")
    assert leave.body is None
    bootstrap_reads = [index for index, entry in enumerate(ui.requests) if entry.path == "/api/v2/bootstrap"]
    assert bootstrap_reads[-1] > ui.requests.index(leave), "The bootstrap is re-read after leaving."
    expect(page.get_by_role("dialog")).to_have_count(0)


# --------------------------------------------------------------------------
# Bulk changes.
# --------------------------------------------------------------------------

def test_bulk_role_change_and_remove_report_each_member_and_keep_failures_selected(group_members_ui):
    ui, page = group_members_ui, group_members_ui.page
    ui.force_conflict("PATCH", f"members/{LEE['userId']}")
    open_members(ui)
    for name in ("Maya Member", "Lee Reader", "Teammate 01"):
        row(ui, name).get_by_role("checkbox", name=f"Select {name}", exact=True).check()
    selected = page.get_by_role("region", name="Selected members", exact=True)
    expect(selected).to_contain_text("3 selected")
    selected.get_by_label("New role for the selected members").select_option("DocumentManager")
    selected.get_by_role("button", name="Change role", exact=True).click()
    report = page.get_by_role("status", name="Bulk results", exact=True)
    expect(report).to_contain_text("Changed 2 members to Document manager. 1 failed.")
    expect(report).to_contain_text(f"Lee Reader: {WRITE_CONFLICT_MESSAGE}")
    expect(row(ui, "Lee Reader").get_by_role("checkbox", name="Select Lee Reader", exact=True)).to_be_checked()
    expect(row(ui, "Maya Member").get_by_role("checkbox", name="Select Maya Member", exact=True)).not_to_be_checked()
    expect(row(ui, "Maya Member").get_by_label("Role for Maya Member")).to_have_value("DocumentManager")
    expect(selected).to_contain_text("1 selected")
    selected.get_by_role("button", name="Remove selected", exact=True).click()
    confirm = dialog(ui, "Remove 1 member?")
    expect(confirm).to_contain_text("Lee Reader")
    confirm.get_by_role("button", name="Remove 1 member", exact=True).click()
    expect(report).to_contain_text("Removed 1 member.")
    expect(row(ui, "Lee Reader")).to_have_count(0)
    expect(page.get_by_role("region", name="Selected members", exact=True)).to_have_count(0)


# --------------------------------------------------------------------------
# Transfer.
# --------------------------------------------------------------------------

def test_transfer_explains_the_consequences_and_hands_over(group_members_ui):
    ui, page = group_members_ui, group_members_ui.page
    open_members(ui)
    row(ui, "Olivia Admin").get_by_role("button", name="Make Olivia Admin the owner", exact=True).click()
    confirm = dialog(ui, "Make Olivia Admin the owner?")
    expect(confirm).to_contain_text("Olivia Admin becomes the owner of Research group.")
    expect(confirm).to_contain_text("You become a Member. You lose the owner's abilities")
    expect(confirm).to_contain_text("Only the new owner can transfer ownership back.")
    confirm.get_by_role("button", name="Transfer ownership", exact=True).click()
    expect(status_text(ui, "Olivia Admin is now the owner. You're now a Member.")).to_be_visible()
    [transfer] = calls(ui, "PUT", "/api/groups/group-a/membership/owner")
    assert transfer.body == {"userId": OLIVIA["userId"]}
    expect(row(ui, "Olivia Admin").get_by_text("Owner", exact=True)).to_be_visible()
    expect(row(ui, VIEWER_NAME).get_by_role("button", name="Leave this group", exact=True)).to_be_visible()
    expect(page.get_by_text("Role: Member", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Add member", exact=True)).to_have_count(0)
    after = ui.requests[ui.requests.index(transfer):]
    assert any(entry.path == "/api/v2/workspaces/group/group-a" for entry in after), "The context is re-read after a transfer."
    assert not [entry for entry in after if entry.path == REQUESTS_PATH], (
        "Once the transfer ended the caller's management, the request list must not be read again."
    )


# --------------------------------------------------------------------------
# Requests to join.
# --------------------------------------------------------------------------

def test_approve_and_reject_follow_the_server(group_members_ui):
    ui = group_members_ui
    ui.add_pending("group-a", MAYA)
    open_members(ui)
    request_row(ui, "Priya Pending").get_by_role("button", name="Approve Priya Pending", exact=True).click()
    expect(status_text(ui, "Priya Pending was added to the group.")).to_be_visible()
    expect(row(ui, "Priya Pending")).to_be_visible()
    expect(request_row(ui, "Priya Pending")).to_have_count(0)
    request_row(ui, "Maya Member").get_by_role("button", name="Approve Maya Member", exact=True).click()
    expect(status_text(ui, "Maya Member was already a member. Their request to join was cleared.")).to_be_visible()
    request_row(ui, "Sam Seeker").get_by_role("button", name="Reject Sam Seeker", exact=True).click()
    expect(status_text(ui, "Sam Seeker's request to join was rejected.")).to_be_visible()
    expect(ui.page.get_by_text("No one is waiting to join.", exact=True)).to_be_visible()
    assert [entry.body for entry in ui.membership_requests("POST")] == [None, None, None]


def test_a_request_already_handled_is_not_a_failure(group_members_ui):
    """`no_pending_request` -- someone else decided it, or an earlier approve's answer was lost."""
    ui = group_members_ui
    open_members(ui)
    ui.approve_elsewhere("group-a", PRIYA["userId"])
    request_row(ui, "Priya Pending").get_by_role("button", name="Approve Priya Pending", exact=True).click()
    expect(status_text(ui, "Priya Pending's request was already handled.")).to_be_visible()
    expect(ui.page.get_by_role("alert")).to_have_count(0)
    expect(request_row(ui, "Priya Pending")).to_have_count(0)
    expect(row(ui, "Priya Pending")).to_be_visible()


# --------------------------------------------------------------------------
# Refusals.
# --------------------------------------------------------------------------

def test_a_role_change_on_someone_now_the_owner_is_refused(group_members_ui):
    ui = group_members_ui
    ui.set_viewer_role("group-a", "Admin")
    open_members(ui)
    ui.make_owner("group-a", MAYA["userId"])
    row(ui, "Maya Member").get_by_label("Role for Maya Member").select_option("Admin")
    expect(alert(ui, OWNER_ROLE_MESSAGE)).to_be_visible()
    expect(row(ui, "Maya Member").get_by_text("Owner", exact=True)).to_be_visible()
    expect(row(ui, "Maya Member").get_by_role("combobox")).to_have_count(0)


def test_leaving_after_becoming_the_owner_is_refused(group_members_ui):
    ui = group_members_ui
    ui.set_viewer_role("group-a", "Admin")
    open_members(ui)
    ui.make_owner("group-a", OWNER_ID)
    row(ui, VIEWER_NAME).get_by_role("button", name="Leave this group", exact=True).click()
    dialog(ui, "Leave Research group?").get_by_role("button", name="Leave group", exact=True).click()
    expect(alert(ui, OWNER_LEAVE_MESSAGE)).to_be_visible()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-a/members")
    expect(row(ui, VIEWER_NAME).get_by_role("button", name="Leave this group", exact=True)).to_have_count(0)


def test_losing_management_mid_session_refuses_and_refreshes_the_hints(group_members_ui):
    ui, page = group_members_ui, group_members_ui.page
    ui.set_viewer_role("group-a", "Admin")
    open_members(ui)
    ui.set_member_role("group-a", OWNER_ID, "User")
    row(ui, "Maya Member").get_by_role("button", name="Remove Maya Member", exact=True).click()
    dialog(ui, "Remove Maya Member?").get_by_role("button", name="Remove member", exact=True).click()
    expect(alert(ui, MEMBERSHIP_PERMISSION_MESSAGE)).to_be_visible()
    expect(page.get_by_role("button", name="Add member", exact=True)).to_have_count(0)
    expect(member_list(ui).get_by_role("button", name="Remove Maya Member", exact=True)).to_have_count(0)
    expect(page.get_by_text("Role: Member", exact=True)).to_be_visible()


def test_being_removed_mid_session_ends_the_workspace(group_members_ui):
    ui, page = group_members_ui, group_members_ui.page
    ui.set_viewer_role("group-a", "Admin")
    open_members(ui)
    ui.remove_person("group-a", OWNER_ID)
    row(ui, "Lee Reader").get_by_label("Role for Lee Reader").select_option("Admin")
    expect(page.get_by_text("You no longer have permission to access that group.", exact=True)).to_be_visible()


def test_a_write_conflict_keeps_the_state_for_a_plain_retry(group_members_ui):
    ui = group_members_ui
    ui.force_conflict("PATCH", f"members/{MAYA['userId']}")
    open_members(ui)
    lists_before = len(calls(ui, "GET", MEMBERS_PATH))
    select = row(ui, "Maya Member").get_by_label("Role for Maya Member")
    select.select_option("Admin")
    expect(alert(ui, WRITE_CONFLICT_MESSAGE)).to_be_visible()
    expect(select).to_have_value("User")
    # A conflict changed nothing, so nothing is reloaded: the same action is simply retried.
    ui.page.wait_for_timeout(500)
    assert len(calls(ui, "GET", MEMBERS_PATH)) == lists_before
    select.select_option("Admin")
    expect(status_text(ui, "Maya Member's role is now Admin.")).to_be_visible()
    assert len(calls(ui, "PATCH", f"{MEMBERS_PATH}/{MAYA['userId']}")) == 2
    wait_until(ui, lambda: len(calls(ui, "GET", MEMBERS_PATH)) == lists_before + 1)
    expect(row(ui, "Maya Member").get_by_label("Role for Maya Member")).to_have_value("Admin")


def test_a_deleted_group_is_gone(group_members_ui):
    ui, page = group_members_ui, group_members_ui.page
    open_members(ui)
    ui.delete_group("group-a")
    row(ui, "Maya Member").get_by_label("Role for Maya Member").select_option("Admin")
    expect(page.get_by_text("That group no longer exists.", exact=True)).to_be_visible()


def test_a_malformed_member_list_is_a_load_error(group_members_ui):
    ui, page = group_members_ui, group_members_ui.page
    ui.malformed_list = True
    open_members(ui)
    expect(alert(ui, "The member list could not be read. Please retry.")).to_be_visible()
    expect(member_list(ui)).to_have_count(0)
    expect(page.get_by_role("button", name="Add member", exact=True)).to_have_count(0)
    ui.malformed_list = False
    page.get_by_role("button", name="Retry members", exact=True).click()
    expect(row(ui, "Olivia Admin")).to_be_visible()


def test_a_malformed_request_list_is_a_load_error(group_members_ui):
    ui = group_members_ui
    ui.malformed_requests = True
    open_members(ui)
    expect(alert(ui, "The requests to join could not be read. Please retry.")).to_be_visible()
    expect(row(ui, "Olivia Admin")).to_be_visible()
