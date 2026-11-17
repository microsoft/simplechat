# test_v2_public_settings.py
"""
Production-SPA coverage for the native V2 public workspace Settings, Activity and Statistics sections.
Version: 0.261.445
Implemented in: 0.261.185
An unrecognized status is explained with the server's own sentence: 0.261.188
The danger zone deletes the workspace natively instead of handing off to classic: 0.261.445
An owner or admin keeps these sections in an inactive or unrecognized-status workspace, and a document
manager keeps Statistics: 0.261.445

Exercises the real Settings, Activity and Statistics sections -- the M10C sections of the public
WorkspaceShell's Manage group, the shared M7C components driven by the public scope -- against closed
synthetic HTTP. The fixture (`ui_tests/fixtures/public_settings.py`) serves the native
`/api/public-workspaces/<w>/settings[...]` and `/insights/*` routes with the server's decision, order of
checks and reviewed texts (held to the real routes by test_public_settings_fixture_parity.py), serves the
owner's `DELETE /api/public_workspaces/<w>` as the real route answers it (held to the route by
test_v2_workspace_delete_fixture_parity.py), and traps every other classic public settings route and every
personal-scope read, so a page that called a classic or personal route, invented a control the hints
withhold, or kept an optimistic draft fails the run.

It pins the Manage group's rail entries; the three sections' reads and gating for the owner, an admin,
a document manager and a reader, and in a locked or inactive workspace; the profile edit with its live
preview, success notice and the header following the save; a stale revision that rebases, the shared
write conflict that allows a plain retry, a refocus that preserves the open drafts, and a 400, 500 or
network failure that keeps every field; a mid-session lock that re-gates the profile read-only and
offers Discard; the logo upload and removal, a conflict that keeps the file for an explicit retry, and
the image check that refuses a non-image; the downloads and retention cards' presence, absence and
edits, including the context refresh after a downloads save; the danger zone -- owner-only, quoting the
workspace's own current-document count, saying deletion removes only the workspace record, and deleting
natively: held while documents remain (including one that arrives while the confirmation is open),
confirmed, refused with the server's words or a plain sentence for a 5xx or a dropped connection,
retried, already deleted elsewhere, sent once however often it is clicked, held back by unsaved edits,
worded with the administrator's workspace label, and never touching classic or setActive; the activity
feed with the public actor labels ("Not a member"), limits,
empty and unavailable states; the statistics windows, the custom-range limit, the classic CSV export
(the label title, no BOM, the classic file name) and the unavailable state; an administrator's custom
workspace label reaching every section; and both themes at both breakpoints.
"""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.public_settings import (
    PUBLIC_ACTIVITY_UNAVAILABLE_MESSAGE, PUBLIC_SETTINGS_CHANGED_MESSAGE, PUBLIC_SETTINGS_REFUSAL_MESSAGES,
    PUBLIC_STATS_UNAVAILABLE_MESSAGE, PUBLIC_STATUS_UNRECOGNIZED_MESSAGE, PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE,
)
from ui_tests.fixtures.public_settings import public_settings_ui as public_settings_ui
from ui_tests.fixtures.public_workspace import PUBLIC_INACTIVE_REASON, PUBLIC_STATUS_UNKNOWN_REASON
from ui_tests.fixtures.workspace_authoring import ORIGIN


pytestmark = pytest.mark.ui
# The browser fixture, imported under its own name so pytest finds it.
_PYTEST_FIXTURES = (public_settings_ui,)

WORKSPACE = "pub-a"
LAYOUTS = [
    pytest.param("light", 1440, 900, id="desktop-light"),
    pytest.param("dark", 1440, 900, id="desktop-dark"),
    pytest.param("light", 390, 844, id="mobile-light"),
    pytest.param("dark", 390, 844, id="mobile-dark"),
]

SCREENSHOTS = Path(os.environ.get(
    "SIMPLECHAT_UI_SCREENSHOTS", str(Path(__file__).parent / "artifacts" / "public-settings"),
))

# A real, minimal 1x1 PNG: the fixture, like the server, reads the bytes and refuses anything else.
LOGO_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x05\x02\x00\x84\xd0"
    b"\x8f\xdd\x00\x00\x00\x00IEND\xaeB`\x82"
)
LOGO_PNG = {"name": "logo.png", "mimeType": "image/png", "buffer": LOGO_PNG_BYTES}
LOGO_NOT_AN_IMAGE = {"name": "logo.png", "mimeType": "image/png", "buffer": b"this is not an image"}

OWNER_REASON = PUBLIC_SETTINGS_REFUSAL_MESSAGES["public_workspace_owner_required"]
MANAGER_REASON = PUBLIC_SETTINGS_REFUSAL_MESSAGES["public_workspace_manager_required"]
MEMBER_REASON = PUBLIC_SETTINGS_REFUSAL_MESSAGES["public_workspace_member_required"]
LOCKED_REASON = PUBLIC_SETTINGS_REFUSAL_MESSAGES["public_workspace_status_unavailable"]

# The raw status a test stores, the status the page shows (a value this version doesn't recognize is
# "unknown"), the page's status pill, the reason the profile is read-only for the owner, and the reason
# a section closed to the viewer gives.
BARRING_STATUSES = [
    pytest.param("inactive", "Status: Inactive", LOCKED_REASON, PUBLIC_INACTIVE_REASON, id="inactive"),
    pytest.param("frozen", "Status: Status unavailable", PUBLIC_STATUS_UNRECOGNIZED_MESSAGE,
                 PUBLIC_STATUS_UNKNOWN_REASON, id="unrecognized"),
]

# The native delete's route and the sentences the section shows for it (WorkspaceSettingsSection and
# PublicSettingsSection own the wording; the apostrophes are the typographic ones the page renders).
PUBLIC_DELETE_PATH = f"/api/public_workspaces/{WORKSPACE}"
PUBLIC_DELETE_HELD = "The public workspace wasn\u2019t deleted because it still holds documents. Remove them first."
PUBLIC_DELETE_FAILED = "The public workspace couldn\u2019t be deleted. Try again."
PUBLIC_DELETE_GONE = "This public workspace no longer exists. It may already have been deleted."


# --------------------------------------------------------------------------
# Helpers.
# --------------------------------------------------------------------------

def by_testid(ui, name):
    return ui.page.get_by_test_id(name)


def open_settings(ui, workspace=WORKSPACE, **options):
    ui.open(f"/public/{workspace}/settings", **options)
    expect(by_testid(ui, "public-settings-section")).to_be_visible()


def open_activity(ui, workspace=WORKSPACE, **options):
    ui.open(f"/public/{workspace}/activity", **options)
    expect(by_testid(ui, "public-activity-section")).to_be_visible()


def open_statistics(ui, workspace=WORKSPACE, **options):
    ui.open(f"/public/{workspace}/statistics", **options)
    expect(by_testid(ui, "public-statistics-section")).to_be_visible()


def expect_context_read(ui, workspace=WORKSPACE):
    return ui.page.expect_response(
        lambda response: response.url.endswith(f"/api/v2/workspaces/public/{workspace}")
        and response.request.method == "GET"
    )


def delete_calls(ui):
    return [entry for entry in ui.requests if entry.method == "DELETE" and entry.path == PUBLIC_DELETE_PATH]


def delete_dialog(ui):
    return ui.page.get_by_role("dialog", name="Delete this public workspace?", exact=True)


def wait_for_delete(ui, timeout_ms=5000):
    """Wait for the page's DELETE to reach the fixture, so a held response can be arranged around it."""
    waited = 0
    while not delete_calls(ui):
        assert waited < timeout_ms, "The delete was never sent."
        ui.page.wait_for_timeout(50)
        waited += 50


# --------------------------------------------------------------------------
# Layout: the three sections render and stay within the viewport, light and dark.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_settings_layout(public_settings_ui, theme, width, height):
    ui = public_settings_ui
    ui.set_logo_present(WORKSPACE)
    open_settings(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("heading", name="Public Workspace settings", exact=True)).to_be_visible()
    for panel in ("public-settings-name", "public-settings-logo-upload", "public-settings-downloads",
                  "public-settings-retention", "public-settings-danger"):
        expect(by_testid(ui, panel)).to_be_visible()
    ui.assert_no_overflow()
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    label = f'{"mobile" if width < 768 else "desktop"}-{theme}'
    ui.page.screenshot(path=str(SCREENSHOTS / f"settings-{label}.png"), full_page=True)


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_activity_layout(public_settings_ui, theme, width, height):
    ui = public_settings_ui
    open_activity(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("heading", name="Activity", exact=True)).to_be_visible()
    expect(by_testid(ui, "public-activity-section").get_by_role("listitem")).to_have_count(3)
    expect(by_testid(ui, "public-activity-limit-10")).to_be_visible()
    ui.assert_no_overflow()
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    label = f'{"mobile" if width < 768 else "desktop"}-{theme}'
    ui.page.screenshot(path=str(SCREENSHOTS / f"activity-{label}.png"), full_page=True)


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_statistics_layout(public_settings_ui, theme, width, height):
    ui = public_settings_ui
    open_statistics(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("heading", name="Statistics", exact=True)).to_be_visible()
    expect(by_testid(ui, "public-statistics-window-7")).to_be_visible()
    expect(by_testid(ui, "public-statistics-export")).to_be_visible()
    expect(ui.page.get_by_role("heading", name="Document activity", exact=True)).to_be_visible()
    ui.assert_no_overflow()
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    label = f'{"mobile" if width < 768 else "desktop"}-{theme}'
    ui.page.screenshot(path=str(SCREENSHOTS / f"statistics-{label}.png"), full_page=True)


# --------------------------------------------------------------------------
# Navigation: the three sections join Members in the rail's Manage group.
# --------------------------------------------------------------------------

def test_the_manage_group_lists_settings_activity_and_statistics(public_settings_ui):
    ui, page = public_settings_ui, public_settings_ui.page
    ui.open(f"/public/{WORKSPACE}")
    nav = page.get_by_role("navigation", name="Workspace sections", exact=True)
    expect(nav.get_by_text("Manage", exact=True)).to_be_visible()
    for label in ("Members", "Settings", "Activity", "Statistics"):
        expect(nav.get_by_role("link", name=label, exact=True)).to_be_visible()
    # The overview reads no settings or insights route.
    assert ui.settings_requests() == [] and ui.insight_requests("stats") == []
    nav.get_by_role("link", name="Settings", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/public/{WORKSPACE}/settings")
    expect(by_testid(ui, "public-settings-section")).to_be_visible()


def test_a_stray_segment_on_a_manage_section_opens_the_section(public_settings_ui):
    ui, page = public_settings_ui, public_settings_ui.page
    ui.open(f"/public/{WORKSPACE}/statistics/not-a-route")
    expect(page).to_have_url(f"{ORIGIN}/v2/public/{WORKSPACE}/statistics")
    expect(by_testid(ui, "public-statistics-section")).to_be_visible()


# --------------------------------------------------------------------------
# Profile.
# --------------------------------------------------------------------------

def test_profile_edit_previews_saves_and_the_header_follows(public_settings_ui):
    ui = public_settings_ui
    open_settings(ui)
    by_testid(ui, "public-settings-name").fill("Frontier library")
    expect(by_testid(ui, "public-settings-preview")).to_contain_text("Frontier library")
    with expect_context_read(ui) as info:
        by_testid(ui, "public-settings-save-profile").click()
    expect(ui.page.get_by_text("Public Workspace profile saved.", exact=True)).to_be_visible()
    assert len(ui.settings_requests("PATCH", "profile")) == 1
    # The save re-reads the context, which now carries the saved name, so the page header follows.
    assert info.value.json()["workspace"]["name"] == "Frontier library"
    ui.page.wait_for_function(
        """() => Array.from(document.querySelectorAll('p')).some((element) =>
            element.textContent === 'Frontier library'
            && !element.closest('[data-testid="public-settings-section"]'))"""
    )
    open_settings(ui)
    expect(by_testid(ui, "public-settings-name")).to_have_value("Frontier library")


def test_profile_stale_revision_rebases_then_saves(public_settings_ui):
    ui = public_settings_ui
    open_settings(ui)
    ui.force_settings_changed(WORKSPACE)
    reads_before = len(ui.settings_requests("GET"))
    by_testid(ui, "public-settings-name").fill("Rebased name")
    by_testid(ui, "public-settings-save-profile").click()
    expect(ui.page.get_by_text(PUBLIC_SETTINGS_CHANGED_MESSAGE, exact=True)).to_be_visible()
    expect(by_testid(ui, "public-settings-name")).to_have_value("Rebased name")
    # public_workspace_settings_changed reloads the section before the draft is rebased over it.
    assert len(ui.settings_requests("GET")) == reads_before + 1
    by_testid(ui, "public-settings-save-profile").click()
    expect(ui.page.get_by_text("Public Workspace profile saved.", exact=True)).to_be_visible()
    assert len(ui.settings_requests("PATCH", "profile")) == 2


def test_profile_write_conflict_allows_plain_retry(public_settings_ui):
    ui = public_settings_ui
    open_settings(ui)
    ui.force_write_conflict(WORKSPACE)
    reads_before = len(ui.settings_requests("GET"))
    by_testid(ui, "public-settings-name").fill("Retried name")
    by_testid(ui, "public-settings-save-profile").click()
    expect(ui.page.get_by_text(PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE, exact=True)).to_be_visible()
    expect(by_testid(ui, "public-settings-name")).to_have_value("Retried name")
    # public_workspace_write_conflict is a plain retry: nothing changed, so nothing is re-read.
    assert len(ui.settings_requests("GET")) == reads_before
    by_testid(ui, "public-settings-save-profile").click()
    expect(ui.page.get_by_text("Public Workspace profile saved.", exact=True)).to_be_visible()
    assert len(ui.settings_requests("PATCH", "profile")) == 2


def test_a_name_too_long_is_refused_in_the_servers_words(public_settings_ui):
    ui = public_settings_ui
    open_settings(ui)
    by_testid(ui, "public-settings-name").fill("n" * 81)
    by_testid(ui, "public-settings-save-profile").click()
    expect(ui.page.get_by_text("Workspace names can be at most 80 characters.", exact=True)).to_be_visible()
    assert ui.settings_requests("PATCH", "profile") == []


def test_refocus_preserves_open_drafts_and_leave_guard(public_settings_ui):
    ui = public_settings_ui
    open_settings(ui)
    by_testid(ui, "public-settings-name").fill("Draft that must survive a refocus")
    by_testid(ui, "public-settings-retention-conversation").select_option("30")
    expect(by_testid(ui, "public-settings-downloads-toggle")).to_be_disabled()
    reads_before = len(ui.settings_requests("GET"))
    # A refocus reparses the context into a fresh object; the client is keyed on the workspace id, so it
    # is not rebuilt and the section keeps -- never reloads -- its open drafts.
    with expect_context_read(ui):
        ui.page.evaluate("window.dispatchEvent(new Event('focus'))")
    ui.page.wait_for_timeout(150)
    expect(by_testid(ui, "public-settings-name")).to_have_value("Draft that must survive a refocus")
    expect(by_testid(ui, "public-settings-retention-conversation")).to_have_value("30")
    expect(by_testid(ui, "public-settings-downloads-toggle")).to_be_disabled()
    assert len(ui.settings_requests("GET")) == reads_before


def test_profile_validation_error_keeps_draft(public_settings_ui):
    ui = public_settings_ui
    open_settings(ui)
    ui.next_write_error("A workspace name can't be only spaces.")
    by_testid(ui, "public-settings-name").fill("Kept through a 400")
    by_testid(ui, "public-settings-save-profile").click()
    expect(ui.page.get_by_text("A workspace name can't be only spaces.", exact=True)).to_be_visible()
    expect(by_testid(ui, "public-settings-name")).to_have_value("Kept through a 400")
    expect(by_testid(ui, "public-settings-name")).to_be_enabled()
    assert len(ui.settings_requests("PATCH", "profile")) == 1


def test_profile_server_error_keeps_draft(public_settings_ui):
    ui = public_settings_ui
    open_settings(ui)
    ui.reject_next("PATCH", f"/api/public-workspaces/{WORKSPACE}/settings/profile",
                   status=500, error="The workspace settings request could not be completed. Try again.")
    by_testid(ui, "public-settings-name").fill("Kept through a 500")
    by_testid(ui, "public-settings-save-profile").click()
    expect(ui.page.get_by_text(
        "The workspace settings request could not be completed. Try again.", exact=True)).to_be_visible()
    expect(by_testid(ui, "public-settings-name")).to_have_value("Kept through a 500")
    expect(by_testid(ui, "public-settings-name")).to_be_enabled()


def test_profile_network_failure_keeps_draft(public_settings_ui):
    ui = public_settings_ui
    open_settings(ui)

    def _abort(route):
        try:
            route.abort()
        except Exception:
            pass

    ui.page.route(f"**/api/public-workspaces/{WORKSPACE}/settings/profile", _abort)
    by_testid(ui, "public-settings-name").fill("Kept through a dropped connection")
    by_testid(ui, "public-settings-save-profile").click()
    expect(ui.page.get_by_role("alert").first).to_be_visible()
    expect(by_testid(ui, "public-settings-name")).to_have_value("Kept through a dropped connection")
    expect(by_testid(ui, "public-settings-name")).to_be_enabled()
    # The aborted request never reaches the fixture; drop its transport console error only.
    ui.console_errors[:] = [(text, url) for text, url in ui.console_errors if "/settings/profile" not in url]


def test_a_lock_after_load_regates_the_profile_and_offers_discard(public_settings_ui):
    ui = public_settings_ui
    open_settings(ui)
    original = by_testid(ui, "public-settings-name").input_value()
    by_testid(ui, "public-settings-name").fill("Edited just before the lock")
    expect(by_testid(ui, "public-settings-downloads-toggle")).to_be_disabled()
    # The workspace is locked server-side after the page loaded: the save is refused with the status
    # reason, the page re-reads its context, and the profile re-gates read-only with the draft kept.
    ui.configure(WORKSPACE, role="Owner", status="locked")
    by_testid(ui, "public-settings-save-profile").click()
    expect(ui.page.get_by_text(LOCKED_REASON, exact=True).first).to_be_visible()
    expect(by_testid(ui, "public-settings-name")).to_be_disabled()
    expect(by_testid(ui, "public-settings-save-profile")).to_have_count(0)
    expect(ui.page.get_by_text("Status: Locked - read only", exact=True)).to_be_visible()
    expect(by_testid(ui, "public-settings-name")).to_have_value("Edited just before the lock")
    # The read-only draft no longer holds the downloads switch, which the owner may still use while
    # the workspace is locked, and Discard clears it.
    expect(by_testid(ui, "public-settings-downloads-toggle")).to_be_enabled()
    by_testid(ui, "public-settings-discard-profile").click()
    expect(by_testid(ui, "public-settings-name")).to_have_value(original)
    assert len(ui.settings_requests("PATCH", "profile")) == 1


# --------------------------------------------------------------------------
# Logo.
# --------------------------------------------------------------------------

def test_logo_upload_and_remove(public_settings_ui):
    ui = public_settings_ui
    open_settings(ui)
    expect(by_testid(ui, "public-settings-logo-remove")).to_have_count(0)
    by_testid(ui, "public-settings-logo-input").set_input_files(files=[LOGO_PNG])
    expect(ui.page.get_by_text("Public Workspace logo updated.", exact=True)).to_be_visible()
    expect(by_testid(ui, "public-settings-logo-remove")).to_be_visible()
    assert len(ui.settings_requests("PUT", "logo")) == 1
    by_testid(ui, "public-settings-logo-remove").click()
    expect(ui.page.get_by_text("Public Workspace logo removed.", exact=True)).to_be_visible()
    expect(by_testid(ui, "public-settings-logo-remove")).to_have_count(0)
    assert len(ui.settings_requests("DELETE", "logo")) == 1


def test_logo_conflict_keeps_file_for_explicit_retry(public_settings_ui):
    ui = public_settings_ui
    open_settings(ui)
    ui.force_write_conflict(WORKSPACE)
    reads_before = len(ui.settings_requests("GET"))
    by_testid(ui, "public-settings-logo-input").set_input_files(files=[LOGO_PNG])
    expect(ui.page.get_by_text(PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE, exact=True)).to_be_visible()
    expect(by_testid(ui, "public-settings-logo-retry")).to_be_visible()
    assert len(ui.settings_requests("GET")) == reads_before
    by_testid(ui, "public-settings-logo-retry").click()
    expect(ui.page.get_by_text("Public Workspace logo updated.", exact=True)).to_be_visible()
    expect(by_testid(ui, "public-settings-logo-retry")).to_have_count(0)
    assert len(ui.settings_requests("PUT", "logo")) == 2


def test_logo_bad_image_shows_error_and_keeps_file(public_settings_ui):
    ui = public_settings_ui
    open_settings(ui)
    by_testid(ui, "public-settings-logo-input").set_input_files(files=[LOGO_NOT_AN_IMAGE])
    expect(ui.page.get_by_text(
        "The logo image could not be read. Upload a PNG or JPEG image.", exact=True)).to_be_visible()
    expect(by_testid(ui, "public-settings-logo-retry")).to_be_visible()
    by_testid(ui, "public-settings-logo-input").set_input_files(files=[LOGO_PNG])
    expect(ui.page.get_by_text("Public Workspace logo updated.", exact=True)).to_be_visible()


# --------------------------------------------------------------------------
# Downloads and retention.
# --------------------------------------------------------------------------

def test_a_downloads_save_refreshes_the_context(public_settings_ui):
    ui = public_settings_ui
    open_settings(ui)
    expect(ui.page.get_by_text("Turn off file downloads for this public workspace", exact=True)).to_be_visible()
    with expect_context_read(ui) as info:
        by_testid(ui, "public-settings-downloads-toggle").click()
    expect(ui.page.get_by_text("File download policy saved.", exact=True)).to_be_visible()
    assert len(ui.settings_requests("PATCH", "downloads")) == 1
    context = info.value.json()
    assert context["document_permissions"]["can_download"] is False
    assert "download" not in context["document_management"]["operations"]


def test_downloads_absent_when_the_administrator_disallows_them(public_settings_ui):
    ui = public_settings_ui
    ui.configure(WORKSPACE, role="Owner", status="active", downloads_admin=False)
    open_settings(ui)
    expect(by_testid(ui, "public-settings-downloads")).to_have_count(0)


def test_retention_edit_sends_only_the_changed_period(public_settings_ui):
    ui = public_settings_ui
    open_settings(ui)
    by_testid(ui, "public-settings-retention-conversation").select_option("30")
    by_testid(ui, "public-settings-save-retention").click()
    expect(ui.page.get_by_text("Retention policy saved.", exact=True)).to_be_visible()
    calls = ui.settings_requests("PATCH", "retention")
    assert len(calls) == 1
    body = calls[-1].body or {}
    assert body.get("conversation_retention_days") == 30
    assert "document_retention_days" not in body


def test_retention_offers_the_classic_choices_within_bounds(public_settings_ui):
    ui = public_settings_ui
    open_settings(ui)
    values = by_testid(ui, "public-settings-retention-document").evaluate(
        "select => Array.from(select.options).map(option => option.value)")
    assert values == ["default", "none", "7", "14", "30", "60", "90", "180", "365", "730", "1095", "3650"]
    # The organization defaults this deployment sets are named in the card.
    expect(by_testid(ui, "public-settings-retention")).to_contain_text("no automatic deletion / 30 days (1 month)")


def test_retention_absent_when_public_retention_is_off(public_settings_ui):
    ui = public_settings_ui
    ui.configure(WORKSPACE, role="Owner", status="active", retention_enabled=False)
    open_settings(ui)
    expect(by_testid(ui, "public-settings-retention")).to_have_count(0)


# --------------------------------------------------------------------------
# Gating by role and status.
# --------------------------------------------------------------------------

def test_an_admin_gets_a_read_only_profile_and_no_danger_zone(public_settings_ui):
    ui = public_settings_ui
    ui.configure(WORKSPACE, role="Admin", status="active")
    open_settings(ui)
    expect(by_testid(ui, "public-settings-name")).to_be_disabled()
    expect(ui.page.get_by_text(OWNER_REASON, exact=True).first).to_be_visible()
    expect(ui.page.get_by_text("PNG or JPEG, set by the workspace owner.", exact=True)).to_be_visible()
    expect(by_testid(ui, "public-settings-downloads-toggle")).to_be_enabled()
    expect(by_testid(ui, "public-settings-danger")).to_have_count(0)
    assert ui.insight_requests("file-count") == []


def test_a_document_manager_reads_statistics_but_not_settings_or_activity(public_settings_ui):
    ui, page = public_settings_ui, public_settings_ui.page
    ui.configure(WORKSPACE, role="DocumentManager", status="active")
    ui.open(f"/public/{WORKSPACE}/settings")
    expect(page.get_by_text("Settings is not available", exact=True)).to_be_visible()
    expect(page.get_by_text(MANAGER_REASON, exact=True)).to_be_visible()
    ui.open(f"/public/{WORKSPACE}/activity")
    expect(page.get_by_text("Activity is not available", exact=True)).to_be_visible()
    open_statistics(ui)
    assert len(ui.insight_requests("stats")) == 1
    # Neither closed section ever reads its route.
    assert ui.settings_requests("GET") == [] and ui.insight_requests("activity") == []


def test_a_reader_finds_every_manage_section_closed_with_its_reason(public_settings_ui):
    ui, page = public_settings_ui, public_settings_ui.page
    ui.configure(WORKSPACE, role="User", status="active")
    ui.open(f"/public/{WORKSPACE}/statistics")
    expect(page.get_by_text("Statistics is not available", exact=True)).to_be_visible()
    expect(page.get_by_text(MEMBER_REASON, exact=True)).to_be_visible()
    ui.open(f"/public/{WORKSPACE}/settings")
    expect(page.get_by_text("Settings is not available", exact=True)).to_be_visible()
    assert ui.settings_requests() == []
    assert ui.insight_requests("stats") == [] and ui.insight_requests("activity") == []


def test_a_locked_workspace_keeps_its_policies_editable_by_the_owner(public_settings_ui):
    ui = public_settings_ui
    ui.configure(WORKSPACE, role="Owner", status="locked")
    open_settings(ui)
    expect(by_testid(ui, "public-settings-name")).to_be_disabled()
    expect(ui.page.get_by_text(LOCKED_REASON, exact=True).first).to_be_visible()
    expect(by_testid(ui, "public-settings-downloads-toggle")).to_be_enabled()
    expect(by_testid(ui, "public-settings-save-retention")).to_be_visible()
    expect(by_testid(ui, "public-settings-danger")).to_be_visible()


def test_an_unrecognized_status_is_explained_with_its_own_sentence(public_settings_ui):
    """A workspace whose status the server doesn't recognize is read-only for the same reason code as a
    locked one, but the server refuses its writes with a sentence of its own. The context closes Settings
    on its next read, yet a section already open adopts each write's fresh settings, and a retention save
    stays allowed: after one, the profile's reason is that sentence, never "locked or inactive" (M11)."""
    ui = public_settings_ui
    open_settings(ui)
    expect(by_testid(ui, "public-settings-name")).to_be_enabled()
    # The workspace's stored status changes to one this version doesn't recognize while the section is open.
    ui.configure(WORKSPACE, role="Owner", status="unknown")
    by_testid(ui, "public-settings-retention-conversation").select_option("30")
    by_testid(ui, "public-settings-save-retention").click()
    expect(ui.page.get_by_text("Retention policy saved.", exact=True)).to_be_visible()
    expect(by_testid(ui, "public-settings-name")).to_be_disabled()
    expect(ui.page.get_by_text(PUBLIC_STATUS_UNRECOGNIZED_MESSAGE, exact=True).first).to_be_visible()
    expect(ui.page.get_by_text(LOCKED_REASON, exact=True)).to_have_count(0)


@pytest.mark.parametrize("role", ["Owner", "Admin"])
@pytest.mark.parametrize("raw,pill,profile_reason,closed_reason", BARRING_STATUSES)
def test_the_owner_and_admins_keep_the_manage_sections_where_the_status_bars_viewing(
    public_settings_ui, role, raw, pill, profile_reason, closed_reason,
):
    """The classic manage page keeps Settings, Activity and Statistics for an owner and an admin of an
    inactive workspace, and the routes behind them check no status, so V2 keeps them too. The content
    sections stay closed, the profile and logo are read-only with the reason, and everything the routes
    still allow works: downloads, retention, the activity feed, the statistics and, for the owner, the
    danger zone."""
    ui, page = public_settings_ui, public_settings_ui.page
    ui.configure(WORKSPACE, role=role, status=raw)
    ui.open(f"/public/{WORKSPACE}")
    nav = page.get_by_role("navigation", name="Workspace sections", exact=True)
    for label in ("Members", "Settings", "Activity", "Statistics"):
        expect(nav.get_by_role("link", name=label, exact=True)).to_have_count(1)
    for label in ("Documents", "Tags", "Prompts"):
        expect(nav.get_by_role("link", name=label, exact=True)).to_have_count(0)
    expect(page.get_by_text(pill, exact=True)).to_be_visible()
    nav.get_by_role("link", name="Settings", exact=True).click()
    expect(by_testid(ui, "public-settings-section")).to_be_visible()
    expect(page.get_by_text("Settings is not available", exact=True)).to_have_count(0)
    # The profile and logo are read-only. The owner is told the status; an admin the role, which comes first.
    expect(by_testid(ui, "public-settings-name")).to_be_disabled()
    expect(by_testid(ui, "public-settings-description")).to_be_disabled()
    expect(by_testid(ui, "public-settings-save-profile")).to_have_count(0)
    expect(by_testid(ui, "public-settings-logo-upload")).to_have_count(0)
    expect(page.get_by_text(profile_reason if role == "Owner" else OWNER_REASON, exact=True).first).to_be_visible()
    # Downloads and retention follow their own rules, not the status.
    expect(by_testid(ui, "public-settings-downloads-toggle")).to_be_enabled()
    expect(by_testid(ui, "public-settings-save-retention")).to_be_visible()
    expect(by_testid(ui, "public-settings-danger")).to_have_count(1 if role == "Owner" else 0)
    open_activity(ui)
    expect(by_testid(ui, "public-activity-section").get_by_role("listitem")).to_have_count(3)
    open_statistics(ui)
    expect(by_testid(ui, "public-statistics-window-7")).to_be_visible()
    assert len(ui.insight_requests("stats")) == 1 and len(ui.insight_requests("activity")) == 1
    assert not ui.settings_requests("PATCH", "profile") and not ui.settings_requests("PUT", "logo")
    assert not ui.classic_visits


@pytest.mark.parametrize("raw,pill,profile_reason,closed_reason", BARRING_STATUSES)
def test_the_owner_still_changes_downloads_and_retention_where_the_status_bars_viewing(
    public_settings_ui, raw, pill, profile_reason, closed_reason,
):
    ui = public_settings_ui
    ui.configure(WORKSPACE, role="Owner", status=raw)
    open_settings(ui)
    by_testid(ui, "public-settings-downloads-toggle").click()
    expect(ui.page.get_by_text("File download policy saved.", exact=True)).to_be_visible()
    by_testid(ui, "public-settings-retention-conversation").select_option("30")
    by_testid(ui, "public-settings-save-retention").click()
    expect(ui.page.get_by_text("Retention policy saved.", exact=True)).to_be_visible()
    assert len(ui.settings_requests("PATCH", "downloads")) == 1
    assert len(ui.settings_requests("PATCH", "retention")) == 1
    assert not ui.settings_requests("PATCH", "profile") and not ui.settings_requests("PUT", "logo")


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_settings_where_the_status_bars_viewing_fits_every_layout(public_settings_ui, theme, width, height):
    ui = public_settings_ui
    ui.configure(WORKSPACE, role="Owner", status="inactive")
    open_settings(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_text("Status: Inactive", exact=True)).to_be_visible()
    expect(by_testid(ui, "public-settings-name")).to_be_disabled()
    expect(ui.page.get_by_text(LOCKED_REASON, exact=True).first).to_be_visible()
    for panel in ("public-settings-downloads", "public-settings-retention", "public-settings-danger"):
        expect(by_testid(ui, panel)).to_be_visible()
    ui.assert_no_overflow()
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    label = f'{"mobile" if width < 768 else "desktop"}-{theme}'
    ui.page.screenshot(path=str(SCREENSHOTS / f"settings-inactive-{label}.png"), full_page=True)


def test_a_status_that_bars_viewing_after_load_keeps_the_section_and_regates_the_profile(public_settings_ui):
    """Before 0.261.445 an owner whose workspace went inactive while Settings was open lost the whole
    section on the next context read, and the draft with it. Now the section stays, the save is refused
    with the status, the profile re-gates read-only with the draft kept, and Discard clears it."""
    ui = public_settings_ui
    open_settings(ui)
    original = by_testid(ui, "public-settings-name").input_value()
    by_testid(ui, "public-settings-name").fill("Edited just before the workspace went inactive")
    ui.configure(WORKSPACE, role="Owner", status="inactive")
    by_testid(ui, "public-settings-save-profile").click()
    expect(ui.page.get_by_text(LOCKED_REASON, exact=True).first).to_be_visible()
    expect(ui.page.get_by_text("Status: Inactive", exact=True)).to_be_visible()
    expect(by_testid(ui, "public-settings-section")).to_be_visible()
    expect(by_testid(ui, "public-settings-name")).to_be_disabled()
    expect(by_testid(ui, "public-settings-name")).to_have_value("Edited just before the workspace went inactive")
    expect(by_testid(ui, "public-settings-save-profile")).to_have_count(0)
    by_testid(ui, "public-settings-discard-profile").click()
    expect(by_testid(ui, "public-settings-name")).to_have_value(original)
    assert len(ui.settings_requests("PATCH", "profile")) == 1


@pytest.mark.parametrize("raw,pill,profile_reason,closed_reason", BARRING_STATUSES)
def test_a_document_manager_keeps_only_statistics_where_the_status_bars_viewing(
    public_settings_ui, raw, pill, profile_reason, closed_reason,
):
    """Statistics is open to every stored role in every status, as classic's Stats tab and the route are;
    Settings and Activity stay closed to a document manager, with the status as the reason."""
    ui, page = public_settings_ui, public_settings_ui.page
    ui.configure(WORKSPACE, role="DocumentManager", status=raw)
    ui.open(f"/public/{WORKSPACE}")
    nav = page.get_by_role("navigation", name="Workspace sections", exact=True)
    expect(nav.get_by_role("link", name="Statistics", exact=True)).to_have_count(1)
    for label in ("Members", "Settings", "Activity", "Documents"):
        expect(nav.get_by_role("link", name=label, exact=True)).to_have_count(0)
    ui.open(f"/public/{WORKSPACE}/settings")
    expect(page.get_by_text("Settings is not available", exact=True)).to_be_visible()
    expect(page.get_by_text(closed_reason, exact=True)).to_be_visible()
    ui.open(f"/public/{WORKSPACE}/activity")
    expect(page.get_by_text("Activity is not available", exact=True)).to_be_visible()
    expect(page.get_by_text(closed_reason, exact=True)).to_be_visible()
    open_statistics(ui)
    assert len(ui.insight_requests("stats")) == 1
    assert ui.settings_requests("GET") == [] and ui.insight_requests("activity") == []


@pytest.mark.parametrize("raw,pill,profile_reason,closed_reason", BARRING_STATUSES)
def test_a_reader_finds_every_manage_section_closed_where_the_status_bars_viewing(
    public_settings_ui, raw, pill, profile_reason, closed_reason,
):
    ui, page = public_settings_ui, public_settings_ui.page
    ui.configure(WORKSPACE, role="User", status=raw)
    ui.open(f"/public/{WORKSPACE}")
    nav = page.get_by_role("navigation", name="Workspace sections", exact=True)
    for label in ("Members", "Settings", "Activity", "Statistics", "Documents", "Tags", "Prompts"):
        expect(nav.get_by_role("link", name=label, exact=True)).to_have_count(0)
    for section, title in (("settings", "Settings"), ("activity", "Activity"), ("statistics", "Statistics")):
        ui.open(f"/public/{WORKSPACE}/{section}")
        expect(page.get_by_text(f"{title} is not available", exact=True)).to_be_visible()
        expect(page.get_by_text(closed_reason, exact=True)).to_be_visible()
    assert ui.settings_requests() == []
    assert ui.insight_requests("stats") == [] and ui.insight_requests("activity") == []


# --------------------------------------------------------------------------
# The danger zone: the workspace's own count, an honest description, and a native, confirmed delete.
# --------------------------------------------------------------------------

def test_the_danger_zone_quotes_the_current_document_count_and_what_deletion_leaves(public_settings_ui):
    ui = public_settings_ui
    ui.set_file_count(WORKSPACE, 7)
    open_settings(ui)
    danger = by_testid(ui, "public-settings-danger")
    expect(by_testid(ui, "public-settings-file-count")).to_have_text(
        "This public workspace holds 7 current documents. Remove them before deleting the public workspace.")
    assert len(ui.insight_requests("file-count")) == 1
    expect(danger).to_contain_text("It removes only the public workspace record")
    expect(danger).to_contain_text("Its documents have to be removed first")
    expect(danger).to_contain_text("its prompts, identities and file sources are left behind")
    expect(by_testid(ui, "public-settings-delete")).to_have_text("Delete public workspace")
    assert not ui.classic_visits and not delete_calls(ui)


def test_the_danger_zone_count_reads_naturally_at_zero(public_settings_ui):
    ui = public_settings_ui
    ui.set_file_count(WORKSPACE, 0)
    open_settings(ui)
    expect(by_testid(ui, "public-settings-file-count")).to_have_text("This public workspace holds no current documents.")


def test_delete_is_held_while_the_workspace_holds_documents(public_settings_ui):
    ui = public_settings_ui
    ui.set_file_count(WORKSPACE, 7)
    open_settings(ui)
    by_testid(ui, "public-settings-delete").click()
    expect(by_testid(ui, "public-settings-danger-error")).to_have_text(PUBLIC_DELETE_HELD)
    expect(delete_dialog(ui)).to_have_count(0)
    # The count is read again at the click, as classic does, and nothing is ever sent to delete.
    assert len(ui.insight_requests("file-count")) == 2
    assert not delete_calls(ui) and not ui.deleted_workspaces and not ui.classic_visits


def test_a_document_that_arrives_while_the_confirmation_is_open_holds_the_delete(public_settings_ui):
    ui = public_settings_ui
    ui.set_file_count(WORKSPACE, 0)
    open_settings(ui)
    by_testid(ui, "public-settings-delete").click()
    confirm = delete_dialog(ui)
    expect(confirm).to_be_visible()
    # The server checks nothing about documents, so the page reads the count once more before sending.
    ui.set_file_count(WORKSPACE, 2)
    confirm.get_by_role("button", name="Delete public workspace", exact=True).click()
    expect(confirm).to_have_count(0)
    expect(by_testid(ui, "public-settings-danger-error")).to_have_text(PUBLIC_DELETE_HELD)
    expect(by_testid(ui, "public-settings-file-count")).to_contain_text("holds 2 current documents")
    assert not delete_calls(ui) and not ui.deleted_workspaces


def test_the_owner_deletes_an_empty_workspace_and_returns_to_the_list(public_settings_ui):
    ui = public_settings_ui
    ui.set_file_count(WORKSPACE, 0)
    open_settings(ui)
    by_testid(ui, "public-settings-delete").click()
    confirm = delete_dialog(ui)
    expect(confirm).to_be_visible()
    expect(confirm).to_contain_text("Everyone loses access to it right away")
    expect(confirm).to_contain_text("Its prompts, identities and file sources are left behind")
    assert not delete_calls(ui), "Nothing is sent until the confirmation."
    confirm.get_by_role("button", name="Delete public workspace", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public")
    expect(ui.page.get_by_text("Choose a public workspace", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Research library was deleted.", exact=True)).to_be_visible()
    [removal] = delete_calls(ui)
    assert removal.body is None and removal.query == {}
    assert ui.deleted_workspaces == [WORKSPACE]
    bootstrap_reads = [index for index, entry in enumerate(ui.requests) if entry.path == "/api/v2/bootstrap"]
    assert bootstrap_reads[-1] > ui.requests.index(removal), "The workspaces are read again after the delete."
    expect(ui.page.get_by_role("dialog")).to_have_count(0)
    # The delete never visits the classic page and never asks the server to make the workspace active.
    assert not ui.classic_visits and ui.set_active_requests() == []


def test_cancelling_the_confirmation_sends_nothing(public_settings_ui):
    ui = public_settings_ui
    ui.set_file_count(WORKSPACE, 0)
    open_settings(ui)
    by_testid(ui, "public-settings-delete").click()
    confirm = delete_dialog(ui)
    confirm.get_by_role("button", name="Cancel", exact=True).click()
    expect(confirm).to_have_count(0)
    expect(by_testid(ui, "public-settings-delete")).to_be_enabled()
    assert not delete_calls(ui) and not ui.deleted_workspaces


@pytest.mark.parametrize("status,payload,shown", [
    pytest.param(
        403, {"error": "Only owner can delete"}, "Only owner can delete", id="403-owner-only",
    ),
    pytest.param(
        409, {"error": "The workspace changed while it was being deleted."},
        "The workspace changed while it was being deleted.", id="409-conflict",
    ),
    pytest.param(
        500, {"error": "Internal cosmos failure for partition 7"}, PUBLIC_DELETE_FAILED, id="500-never-raw",
    ),
])
def test_a_refused_delete_says_why_keeps_the_workspace_and_can_be_retried(public_settings_ui, status, payload, shown):
    ui = public_settings_ui
    ui.set_file_count(WORKSPACE, 0)
    open_settings(ui)
    by_testid(ui, "public-settings-delete").click()
    confirm = delete_dialog(ui)
    ui.reject_next("DELETE", PUBLIC_DELETE_PATH, status=status, error=payload["error"])
    confirm.get_by_role("button", name="Delete public workspace", exact=True).click()
    # The server's words (or a plain sentence for a 5xx) appear in the dialog, which stays open.
    expect(by_testid(ui, "public-settings-delete-error")).to_have_text(shown)
    expect(confirm).to_be_visible()
    expect(confirm.get_by_role("button", name="Delete public workspace", exact=True)).to_be_enabled()
    assert "Internal cosmos failure" not in ui.page.locator("body").inner_text()
    assert not ui.deleted_workspaces and ui.page.url == f"{ORIGIN}/v2/public/{WORKSPACE}/settings"
    # Nothing was lost, so the same dialog can send the delete again, and it goes through.
    confirm.get_by_role("button", name="Delete public workspace", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public")
    assert ui.deleted_workspaces == [WORKSPACE] and len(delete_calls(ui)) == 2


def test_a_dropped_connection_never_shows_a_raw_error_and_can_be_retried(public_settings_ui):
    ui = public_settings_ui
    ui.set_file_count(WORKSPACE, 0)
    open_settings(ui)
    by_testid(ui, "public-settings-delete").click()
    confirm = delete_dialog(ui)

    def _abort(route):
        if route.request.method == "DELETE":
            route.abort()
        else:
            route.fallback()

    ui.page.route(f"**{PUBLIC_DELETE_PATH}", _abort)
    confirm.get_by_role("button", name="Delete public workspace", exact=True).click()
    expect(by_testid(ui, "public-settings-delete-error")).to_have_text(PUBLIC_DELETE_FAILED)
    expect(confirm).to_be_visible()
    assert not ui.deleted_workspaces
    # The aborted request never reaches the fixture, so drop its transport console error, as the
    # profile network test does, to keep the shared teardown's console gate meaningful.
    ui.console_errors[:] = [(text, url) for text, url in ui.console_errors if not url.endswith(PUBLIC_DELETE_PATH)]
    ui.page.unroute(f"**{PUBLIC_DELETE_PATH}", _abort)
    confirm.get_by_role("button", name="Delete public workspace", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public")
    assert ui.deleted_workspaces == [WORKSPACE]


def test_a_workspace_already_deleted_elsewhere_is_left_as_after_a_delete(public_settings_ui):
    ui = public_settings_ui
    ui.set_file_count(WORKSPACE, 0)
    open_settings(ui)
    by_testid(ui, "public-settings-delete").click()
    confirm = delete_dialog(ui)
    ui.defer_next("DELETE", PUBLIC_DELETE_PATH)
    confirm.get_by_role("button", name="Delete public workspace", exact=True).click()
    wait_for_delete(ui)
    # Another session deletes the workspace first, so the held DELETE meets the route's own 404.
    ui.workspaces.pop(WORKSPACE)
    ui.active_workspace = None
    ui.release_responses()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public")
    expect(ui.page.get_by_text(PUBLIC_DELETE_GONE, exact=True)).to_be_visible()
    assert not ui.deleted_workspaces, "This session deleted nothing."
    expect(ui.page.get_by_role("dialog")).to_have_count(0)


def test_a_second_click_while_the_delete_is_in_flight_sends_nothing(public_settings_ui):
    ui = public_settings_ui
    ui.set_file_count(WORKSPACE, 0)
    open_settings(ui)
    by_testid(ui, "public-settings-delete").click()
    confirm = delete_dialog(ui)
    submit = confirm.get_by_role("button", name="Delete public workspace", exact=True)
    ui.defer_next("DELETE", PUBLIC_DELETE_PATH)
    submit.click()
    wait_for_delete(ui)
    expect(submit).to_be_disabled()
    expect(confirm.get_by_role("button", name="Cancel", exact=True)).to_be_disabled()
    submit.click(force=True)
    ui.page.keyboard.press("Enter")
    ui.page.keyboard.press("Escape")
    ui.page.wait_for_timeout(200)
    expect(confirm).to_be_visible()
    assert len(delete_calls(ui)) == 1, "A delete in flight is never sent twice."
    ui.release_responses()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public")
    assert ui.deleted_workspaces == [WORKSPACE] and len(delete_calls(ui)) == 1


def test_delete_waits_for_unsaved_profile_edits(public_settings_ui):
    ui = public_settings_ui
    ui.set_file_count(WORKSPACE, 0)
    open_settings(ui)
    by_testid(ui, "public-settings-name").fill("A half-finished rename")
    expect(by_testid(ui, "public-settings-delete")).to_be_disabled()
    expect(by_testid(ui, "public-settings-delete-unsaved")).to_have_text(
        "Save or discard your profile and retention changes before deleting the public workspace.")
    by_testid(ui, "public-settings-discard-profile").click()
    expect(by_testid(ui, "public-settings-delete")).to_be_enabled()
    expect(by_testid(ui, "public-settings-delete-unsaved")).to_have_count(0)
    assert not delete_calls(ui)


def test_a_custom_workspace_label_words_the_delete_flow(public_settings_ui):
    ui = public_settings_ui
    ui.set_labels(singular="Knowledge Hub", plural="Knowledge Hubs", lower_singular="knowledge hub",
                  lower_plural="knowledge hubs", short="Hub")
    ui.set_file_count(WORKSPACE, 0)
    open_settings(ui)
    expect(by_testid(ui, "public-settings-delete")).to_have_text("Delete knowledge hub")
    by_testid(ui, "public-settings-delete").click()
    confirm = ui.page.get_by_role("dialog", name="Delete this knowledge hub?", exact=True)
    expect(confirm).to_contain_text("The knowledge hub holds no current documents.")
    confirm.get_by_role("button", name="Delete knowledge hub", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public")
    expect(ui.page.get_by_text("Choose a knowledge hub", exact=True)).to_be_visible()


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_the_delete_confirmation_fits_every_layout(public_settings_ui, theme, width, height):
    ui = public_settings_ui
    ui.set_file_count(WORKSPACE, 0)
    open_settings(ui, theme=theme, width=width, height=height)
    by_testid(ui, "public-settings-delete").click()
    confirm = delete_dialog(ui)
    expect(confirm).to_be_visible()
    box = confirm.bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= width, "The dialog is clipped horizontally."
    expect(confirm.get_by_role("button", name="Delete public workspace", exact=True)).to_be_visible()
    ui.assert_no_overflow()
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    label = f'{"mobile" if width < 768 else "desktop"}-{theme}'
    ui.page.screenshot(path=str(SCREENSHOTS / f"delete-confirmation-{label}.png"))


# --------------------------------------------------------------------------
# Activity.
# --------------------------------------------------------------------------

def test_the_activity_feed_names_members_readers_and_the_system(public_settings_ui):
    ui = public_settings_ui
    open_activity(ui)
    feed = by_testid(ui, "public-activity-section")
    expect(feed.get_by_text("Uploaded a document", exact=True)).to_be_visible()
    expect(feed.get_by_text("Research library owner", exact=False)).to_be_visible()
    expect(feed.get_by_text("Not a member", exact=False)).to_be_visible()
    expect(feed.get_by_text("System", exact=False).first).to_be_visible()
    by_testid(ui, "public-activity-limit-10").click()
    expect(by_testid(ui, "public-activity-limit-10")).to_have_attribute("aria-pressed", "true")
    assert ui.insight_requests("activity")[-1].query["limit"] == ["10"]


def test_activity_empty_state(public_settings_ui):
    ui = public_settings_ui
    ui.clear_activity(WORKSPACE)
    open_activity(ui)
    expect(ui.page.get_by_text("No recent activity", exact=True)).to_be_visible()
    expect(ui.page.get_by_text(
        "Uploads, conversations, status changes and File Sync runs in this public workspace will appear here.",
        exact=True)).to_be_visible()


def test_activity_unavailable_state(public_settings_ui):
    ui = public_settings_ui
    ui.make_activity_unavailable(WORKSPACE)
    open_activity(ui)
    expect(ui.page.get_by_text("Activity unavailable", exact=True)).to_be_visible()
    expect(ui.page.get_by_text(PUBLIC_ACTIVITY_UNAVAILABLE_MESSAGE, exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Retry", exact=True)).to_be_visible()


# --------------------------------------------------------------------------
# Statistics.
# --------------------------------------------------------------------------

def test_statistics_windows_and_the_classic_csv_export(public_settings_ui):
    ui, page = public_settings_ui, public_settings_ui.page
    open_statistics(ui)
    by_testid(ui, "public-statistics-window-7").click()
    expect(by_testid(ui, "public-statistics-window-7")).to_have_attribute("aria-pressed", "true")
    assert ui.insight_requests("stats")[-1].query["days"] == ["7"]
    by_testid(ui, "public-statistics-export").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Export public workspace statistics")
    with page.expect_download() as info:
        dialog.get_by_role("button", name="Download CSV", exact=True).click()
    download = info.value
    assert re.fullmatch(r"public_workspace_stats_export_\d{4}-\d{2}-\d{2}\.csv", download.suggested_filename)
    raw = Path(download.path()).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "The classic public export writes no BOM."
    rows = raw.decode("utf-8").split("\n")
    assert rows[0] == "Public Workspace Stats Export"
    for expected in ("SUMMARY METRICS", "Total Documents,3", "Storage Used (bytes),4096", "Total Tokens,256",
                     "Total Members,3", "STORAGE USAGE", "AI Search,1024,1 KB", "Blob Storage,4096,4 KB"):
        assert expected in rows, expected
    assert not any("Storage Limit" in row for row in rows)


def test_a_custom_range_over_the_limit_is_refused_before_any_request(public_settings_ui):
    ui = public_settings_ui
    open_statistics(ui)
    reads_before = len(ui.insight_requests("stats"))
    by_testid(ui, "public-statistics-window-custom").click()
    by_testid(ui, "public-statistics-start").fill("2024-01-01")
    by_testid(ui, "public-statistics-end").fill("2025-01-01")
    by_testid(ui, "public-statistics-apply").click()
    expect(ui.page.get_by_text("Choose a date range of 366 days or fewer.", exact=True)).to_be_visible()
    assert len(ui.insight_requests("stats")) == reads_before


def test_statistics_unavailable_state(public_settings_ui):
    ui = public_settings_ui
    ui.make_stats_unavailable(WORKSPACE)
    open_statistics(ui)
    expect(ui.page.get_by_text("Statistics unavailable", exact=True)).to_be_visible()
    expect(ui.page.get_by_text(PUBLIC_STATS_UNAVAILABLE_MESSAGE, exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Retry", exact=True)).to_be_visible()


# --------------------------------------------------------------------------
# An administrator's custom workspace label reaches every section.
# --------------------------------------------------------------------------

def test_a_custom_workspace_label_reaches_every_section(public_settings_ui):
    ui, page = public_settings_ui, public_settings_ui.page
    ui.set_labels(singular="Knowledge Hub", plural="Knowledge Hubs", lower_singular="knowledge hub",
                  lower_plural="knowledge hubs", short="Hub")
    open_settings(ui)
    expect(page.get_by_role("heading", name="Knowledge Hub settings", exact=True)).to_be_visible()
    expect(page.get_by_text("Turn off file downloads for this knowledge hub", exact=True)).to_be_visible()
    expect(by_testid(ui, "public-settings-danger")).to_contain_text("Delete this knowledge hub")
    open_statistics(ui)
    by_testid(ui, "public-statistics-export").click()
    with page.expect_download() as info:
        page.get_by_role("dialog").get_by_role("button", name="Download CSV", exact=True).click()
    first_row = Path(info.value.path()).read_text(encoding="utf-8").split("\n")[0]
    assert first_row == "Knowledge Hub Stats Export"
    # The classic file name stays the classic one whatever the label.
    assert re.fullmatch(r"public_workspace_stats_export_\d{4}-\d{2}-\d{2}\.csv", info.value.suggested_filename)


# --------------------------------------------------------------------------
# Every request stays on the native public routes.
# --------------------------------------------------------------------------

def test_every_settings_and_insights_request_names_the_workspace(public_settings_ui):
    ui = public_settings_ui
    open_settings(ui)
    open_activity(ui)
    open_statistics(ui)
    touched = [
        entry.path for entry in ui.requests
        if re.search(r"/(settings|insights)(/|$)", entry.path) and entry.path != "/api/user/settings"
    ]
    assert touched, "The sections read nothing."
    assert all(path.startswith(f"/api/public-workspaces/{WORKSPACE}/") for path in touched), touched
