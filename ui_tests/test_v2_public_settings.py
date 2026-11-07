# test_v2_public_settings.py
"""
Production-SPA coverage for the native V2 public workspace Settings, Activity and Statistics sections.
Version: 0.261.188
Implemented in: 0.261.185
An unrecognized status is explained with the server's own sentence: 0.261.188

Exercises the real Settings, Activity and Statistics sections -- the M10C sections of the public
WorkspaceShell's Manage group, the shared M7C components driven by the public scope -- against closed
synthetic HTTP. The fixture (`ui_tests/fixtures/public_settings.py`) serves the native
`/api/public-workspaces/<w>/settings[...]` and `/insights/*` routes with the server's decision, order of
checks and reviewed texts (held to the real routes by test_public_settings_fixture_parity.py), and traps
every classic public settings route and every personal-scope read, so a page that called a classic or
personal route, invented a control the hints withhold, or kept an optimistic draft fails the run.

It pins the Manage group's rail entries; the three sections' reads and gating for the owner, an admin,
a document manager and a reader, and in a locked or inactive workspace; the profile edit with its live
preview, success notice and the header following the save; a stale revision that rebases, the shared
write conflict that allows a plain retry, a refocus that preserves the open drafts, and a 400, 500 or
network failure that keeps every field; a mid-session lock that re-gates the profile read-only and
offers Discard; the logo upload and removal, a conflict that keeps the file for an explicit retry, and
the image check that refuses a non-image; the downloads and retention cards' presence, absence and
edits, including the context refresh after a downloads save; the danger zone -- owner-only, quoting the
workspace's own current-document count, saying deletion removes only the workspace record, confirming
the active public workspace before the classic handoff, stopping when that fails, and asking first
when a change is unsaved; the activity feed with the public actor labels ("Not a member"), limits,
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


def open_delete_confirmation(ui):
    by_testid(ui, "public-settings-delete").click()
    expect(ui.page.get_by_role("dialog")).to_contain_text("Delete this public workspace in classic?")


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


def test_an_inactive_workspace_closes_the_manage_sections(public_settings_ui):
    ui, page = public_settings_ui, public_settings_ui.page
    ui.configure(WORKSPACE, role="Owner", status="inactive")
    ui.open(f"/public/{WORKSPACE}/settings")
    expect(page.get_by_text("Settings is not available", exact=True)).to_be_visible()
    expect(page.get_by_text(
        "This public workspace is inactive. Access is restricted to administrators.", exact=True)).to_be_visible()
    assert ui.settings_requests() == []


# --------------------------------------------------------------------------
# The danger zone: the workspace's own count, an honest description, and a confirmed handoff.
# --------------------------------------------------------------------------

def test_the_danger_zone_quotes_the_current_document_count_and_what_deletion_leaves(public_settings_ui):
    ui = public_settings_ui
    ui.set_file_count(WORKSPACE, 7)
    open_settings(ui)
    danger = by_testid(ui, "public-settings-danger")
    expect(by_testid(ui, "public-settings-file-count")).to_have_text("This public workspace holds 7 current documents.")
    assert len(ui.insight_requests("file-count")) == 1
    expect(danger).to_contain_text("Deleting removes only the public workspace record.")
    expect(danger).to_contain_text("Its documents, prompts, identities and file sources are left behind")
    expect(danger).to_contain_text("counts documents itself, earlier versions included")
    expect(by_testid(ui, "public-settings-delete")).to_have_text("Delete public workspace (classic)")


def test_the_danger_zone_count_reads_naturally_at_zero(public_settings_ui):
    ui = public_settings_ui
    ui.set_file_count(WORKSPACE, 0)
    open_settings(ui)
    expect(by_testid(ui, "public-settings-file-count")).to_have_text("This public workspace holds no current documents.")


def test_the_classic_handoff_confirms_the_active_workspace_first(public_settings_ui):
    ui, page = public_settings_ui, public_settings_ui.page
    ui.active_workspace = "pub-b"
    open_settings(ui)
    open_delete_confirmation(ui)
    expect(page.get_by_role("dialog")).to_contain_text("It removes only the public workspace record")
    page.get_by_role("button", name="Open classic", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/public_workspaces/{WORKSPACE}")
    assert [entry.body for entry in ui.set_active_requests()] == [{"workspaceId": WORKSPACE}]
    assert (f"/public_workspaces/{WORKSPACE}", WORKSPACE) in ui.classic_visits


def test_the_classic_handoff_stops_when_the_workspace_cannot_be_confirmed(public_settings_ui):
    ui, page = public_settings_ui, public_settings_ui.page
    ui.set_active_failures.add(WORKSPACE)
    open_settings(ui)
    open_delete_confirmation(ui)
    page.get_by_role("button", name="Open classic", exact=True).click()
    expect(page.get_by_role("alert").filter(
        has_text="The active public workspace could not be saved.")).to_be_visible()
    expect(page).to_have_url(f"{ORIGIN}/v2/public/{WORKSPACE}/settings")
    assert ui.classic_visits == []


def test_the_classic_handoff_asks_before_discarding_an_unsaved_change(public_settings_ui):
    ui, page = public_settings_ui, public_settings_ui.page
    open_settings(ui)
    by_testid(ui, "public-settings-name").fill("Unsaved name")
    open_delete_confirmation(ui)
    page.get_by_role("button", name="Open classic", exact=True).click()
    prompt = page.get_by_role("dialog").filter(has_text="Discard unsaved changes?")
    expect(prompt).to_be_visible()
    prompt.get_by_role("button", name="Keep editing", exact=True).click()
    expect(by_testid(ui, "public-settings-name")).to_have_value("Unsaved name")
    assert ui.set_active_requests() == [] and ui.classic_visits == []
    open_delete_confirmation(ui)
    page.get_by_role("button", name="Open classic", exact=True).click()
    prompt.get_by_role("button", name="Discard changes", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/public_workspaces/{WORKSPACE}")
    assert len(ui.set_active_requests()) == 1


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
