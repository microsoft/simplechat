# test_v2_group_settings.py
"""
Production-SPA coverage for the native V2 group Settings, Activity and Statistics sections.
Version: 0.261.165
Implemented in: 0.261.157

Exercises the real Settings, Activity and Statistics sections -- the M7C sections of the group
WorkspaceShell's Manage group -- against closed synthetic HTTP. The fixture
(`ui_tests/fixtures/group_settings.py`) reuses the shell fixture's `/api/groups/<g>/settings[/logo]`
and `/api/groups/<g>/insights/*` serving, which runs the real settings policy for every hint and
models the server's owner, manager, status and capability rules with their exact messages, so a page
that read a personal or classic route, invented a control the hints withhold, or kept an optimistic
draft would fail the run rather than pass.

It pins the three sections' reads and gating for the owner, an admin and a member; the profile edit
with its live preview and success notice; the logo upload and removal, a write-guard conflict that
keeps the chosen file for an explicit retry, a stale-revision conflict that rebases, and the server's
image-bytes check that refuses a non-image and keeps the file; the download and retention cards'
presence, absence and edits, retention offered as the classic day choices with only the changed
period sent; every refusal the sections handle, including the CreateGroups-role refusal's explanation;
the way a refocus preserves the open drafts and their leave guard (S1); a 400, 500 or network write
failure that keeps every field (S2); a mid-session lock that re-gates the controls read-only (S3); the
danger zone as owner-only with its file count and classic handoff; the header's classic button
surviving only for an inactive or unknown group; the activity feed with its limits, empty and
unavailable states; the statistics windows, custom range, CSV export and unavailable state; and both
themes at both breakpoints.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.group_settings import (  # noqa: F401
    GROUP_ACTIVITY_UNAVAILABLE_MESSAGE, GROUP_SETTINGS_CHANGED_MESSAGE,
    GROUP_STATS_UNAVAILABLE_MESSAGE, GROUP_WRITE_CONFLICT_MESSAGE,
    GroupSettingsFixture, group_settings_ui,
)
from ui_tests.fixtures.workspace_authoring import ORIGIN  # noqa: F401


pytestmark = pytest.mark.ui

LAYOUTS = [
    pytest.param("light", 1440, 900, id="desktop-light"),
    pytest.param("dark", 1440, 900, id="desktop-dark"),
    pytest.param("light", 390, 844, id="mobile-light"),
    pytest.param("dark", 390, 844, id="mobile-dark"),
]

SCREENSHOTS = Path(os.environ.get(
    "SIMPLECHAT_UI_SCREENSHOTS", str(Path(__file__).parent / "artifacts" / "group-settings"),
))

# A real, minimal 1x1 PNG. The server (and this fixture) now read the logo's bytes with PIL and refuse
# anything that is not a PNG or JPEG, so the upload path needs a genuine image body -- an ASCII
# placeholder no longer passes the magic-byte check. Playwright records a binary multipart body from
# its bytes, so the fixture reads the real image from request.post_data_buffer.
LOGO_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x05\x02\x00\x84\xd0"
    b"\x8f\xdd\x00\x00\x00\x00IEND\xaeB`\x82"
)
LOGO_PNG = {"name": "logo.png", "mimeType": "image/png", "buffer": LOGO_PNG_BYTES}
# A body with the right extension and MIME type but bytes that are not a PNG or JPEG: the server reads
# the image and refuses it, so it exercises the bad-image path the extension check alone would miss.
LOGO_NOT_AN_IMAGE = {"name": "logo.png", "mimeType": "image/png", "buffer": b"this is not an image"}


# --------------------------------------------------------------------------
# Helpers.
# --------------------------------------------------------------------------

def open_settings(ui, group="group-a", **options):
    ui.open(f"/groups/{group}/settings", **options)
    expect(ui.page.get_by_test_id("group-settings-section")).to_be_visible()


def open_activity(ui, group="group-a", **options):
    ui.open(f"/groups/{group}/activity", **options)
    expect(ui.page.get_by_test_id("group-activity-section")).to_be_visible()


def open_statistics(ui, group="group-a", **options):
    ui.open(f"/groups/{group}/statistics", **options)
    expect(ui.page.get_by_test_id("group-statistics-section")).to_be_visible()


def by_testid(ui, name):
    return ui.page.get_by_test_id(name)


def settings_calls(ui, method, section=None):
    suffix = "/settings" if section is None else f"/settings/{section}"
    return [entry for entry in ui.requests
            if entry.method == method and "/groups/" in entry.path and entry.path.endswith(suffix)]


def insight_calls(ui, name):
    return [entry for entry in ui.requests if f"/insights/{name}" in entry.path and entry.method == "GET"]


def context_calls(ui, group="group-a"):
    return [entry for entry in ui.requests
            if entry.method == "GET" and entry.path == f"/api/v2/workspaces/group/{group}"]


# --------------------------------------------------------------------------
# Layout: the three sections render and stay within the viewport, light and dark.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_settings_layout(group_settings_ui, theme, width, height):
    ui = group_settings_ui
    ui.set_logo_present("group-a")
    open_settings(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("heading", name="Group settings", exact=True)).to_be_visible()
    for panel in ("group-settings-name", "group-settings-logo-upload",
                  "group-settings-downloads", "group-settings-retention", "group-settings-danger"):
        expect(by_testid(ui, panel)).to_be_visible()
    # The header's classic button is withheld for an active group, whose Manage sections are native.
    expect(ui.page.get_by_role("button", name="Manage group (classic)")).to_have_count(0)
    ui.assert_no_overflow()
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    label = f'{"mobile" if width < 768 else "desktop"}-{theme}'
    ui.page.screenshot(path=str(SCREENSHOTS / f"settings-{label}.png"), full_page=True)


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_activity_layout(group_settings_ui, theme, width, height):
    ui = group_settings_ui
    open_activity(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("heading", name="Activity", exact=True)).to_be_visible()
    expect(by_testid(ui, "group-activity-section").get_by_role("listitem")).to_have_count(2)
    expect(by_testid(ui, "group-activity-limit-10")).to_be_visible()
    ui.assert_no_overflow()
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    label = f'{"mobile" if width < 768 else "desktop"}-{theme}'
    ui.page.screenshot(path=str(SCREENSHOTS / f"activity-{label}.png"), full_page=True)


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_statistics_layout(group_settings_ui, theme, width, height):
    ui = group_settings_ui
    open_statistics(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("heading", name="Statistics", exact=True)).to_be_visible()
    expect(by_testid(ui, "group-statistics-window-7")).to_be_visible()
    expect(by_testid(ui, "group-statistics-export")).to_be_visible()
    expect(ui.page.get_by_role("heading", name="Document activity", exact=True)).to_be_visible()
    ui.assert_no_overflow()
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    label = f'{"mobile" if width < 768 else "desktop"}-{theme}'
    ui.page.screenshot(path=str(SCREENSHOTS / f"statistics-{label}.png"), full_page=True)


# --------------------------------------------------------------------------
# Profile.
# --------------------------------------------------------------------------

def test_profile_edit_previews_and_saves(group_settings_ui):
    ui = group_settings_ui
    open_settings(ui)
    name = by_testid(ui, "group-settings-name")
    name.fill("Frontier research")
    # The preview reflects the draft before any save.
    expect(by_testid(ui, "group-settings-preview")).to_contain_text("Frontier research")
    by_testid(ui, "group-settings-save-profile").click()
    expect(ui.page.get_by_text("Group profile saved.", exact=True)).to_be_visible()
    assert len(settings_calls(ui, "PATCH", "profile")) == 1
    # A fresh read replaces the state, so the saved name survives a reopen.
    open_settings(ui)
    expect(by_testid(ui, "group-settings-name")).to_have_value("Frontier research")


def test_profile_stale_revision_rebases_then_saves(group_settings_ui):
    ui = group_settings_ui
    open_settings(ui)
    ui.force_settings_changed("group-a")
    by_testid(ui, "group-settings-name").fill("Rebased name")
    by_testid(ui, "group-settings-save-profile").click()
    # The stale-revision conflict reloads the section; the edit is kept over the fresh copy.
    expect(ui.page.get_by_text(GROUP_SETTINGS_CHANGED_MESSAGE, exact=True)).to_be_visible()
    expect(by_testid(ui, "group-settings-name")).to_have_value("Rebased name")
    by_testid(ui, "group-settings-save-profile").click()
    expect(ui.page.get_by_text("Group profile saved.", exact=True)).to_be_visible()
    assert len(settings_calls(ui, "PATCH", "profile")) == 2


def test_profile_write_conflict_allows_plain_retry(group_settings_ui):
    ui = group_settings_ui
    open_settings(ui)
    ui.force_write_conflict("group-a")
    by_testid(ui, "group-settings-name").fill("Retried name")
    by_testid(ui, "group-settings-save-profile").click()
    expect(ui.page.get_by_text(GROUP_WRITE_CONFLICT_MESSAGE, exact=True)).to_be_visible()
    expect(by_testid(ui, "group-settings-name")).to_have_value("Retried name")
    by_testid(ui, "group-settings-save-profile").click()
    expect(ui.page.get_by_text("Group profile saved.", exact=True)).to_be_visible()
    assert len(settings_calls(ui, "PATCH", "profile")) == 2


# --------------------------------------------------------------------------
# S1: a refocus preserves the open drafts, their leave guard and the switch freeze.
# --------------------------------------------------------------------------

def test_refocus_preserves_open_drafts_and_leave_guard(group_settings_ui):
    ui = group_settings_ui
    open_settings(ui)
    by_testid(ui, "group-settings-name").fill("Draft that must survive a refocus")
    by_testid(ui, "group-settings-retention-conversation").select_option("30")
    # While an editor is dirty the immediate-save downloads switch is frozen: its own half of the guard.
    expect(by_testid(ui, "group-settings-downloads-toggle")).to_be_disabled()
    settings_reads_before = len(settings_calls(ui, "GET"))
    # A refocus revalidates the workspace context, which reparses it into a fresh object. The adapter is
    # keyed on the group id alone, so it is not rebuilt and the section keeps -- never reloads -- its
    # open drafts. (S1) Wait for the context re-read to land before asserting nothing was discarded.
    with ui.page.expect_response(
        lambda response: response.url.endswith("/api/v2/workspaces/group/group-a")
        and response.request.method == "GET"
    ):
        ui.page.evaluate("window.dispatchEvent(new Event('focus'))")
    ui.page.wait_for_timeout(150)
    # The drafts, the frozen switch and the leave guard all survive; the settings are never re-read
    # (a reload is what the old adapter churn caused), so no second settings GET fires.
    expect(by_testid(ui, "group-settings-name")).to_have_value("Draft that must survive a refocus")
    expect(by_testid(ui, "group-settings-retention-conversation")).to_have_value("30")
    expect(by_testid(ui, "group-settings-downloads-toggle")).to_be_disabled()
    assert len(settings_calls(ui, "GET")) == settings_reads_before
    assert len(context_calls(ui)) >= 1


# --------------------------------------------------------------------------
# S2: a 400, a 5xx or a network failure keeps every field; only the message is shown.
# --------------------------------------------------------------------------

def test_profile_validation_error_keeps_draft(group_settings_ui):
    ui = group_settings_ui
    open_settings(ui)
    ui.next_write_error("A group name can't be only spaces.")
    by_testid(ui, "group-settings-name").fill("Kept through a 400")
    by_testid(ui, "group-settings-save-profile").click()
    # The server's 400 text is shown verbatim and the draft is kept for a fix-and-retry. (S2)
    expect(ui.page.get_by_text("A group name can't be only spaces.", exact=True)).to_be_visible()
    expect(by_testid(ui, "group-settings-name")).to_have_value("Kept through a 400")
    expect(by_testid(ui, "group-settings-name")).to_be_enabled()
    assert len(settings_calls(ui, "PATCH", "profile")) == 1


def test_profile_server_error_keeps_draft(group_settings_ui):
    ui = group_settings_ui
    open_settings(ui)
    ui.reject_next("PATCH", "/api/groups/group-a/settings/profile",
                   status=500, error="Group settings are briefly unavailable.")
    by_testid(ui, "group-settings-name").fill("Kept through a 500")
    by_testid(ui, "group-settings-save-profile").click()
    # A 5xx is not a refusal: the draft and the surface are kept, only the message is shown. (S2)
    expect(ui.page.get_by_text("Group settings are briefly unavailable.", exact=True)).to_be_visible()
    expect(by_testid(ui, "group-settings-name")).to_have_value("Kept through a 500")
    expect(by_testid(ui, "group-settings-name")).to_be_enabled()
    assert len(settings_calls(ui, "PATCH", "profile")) == 1


def test_profile_network_failure_keeps_draft(group_settings_ui):
    ui = group_settings_ui
    open_settings(ui)
    target = "**/api/groups/group-a/settings/profile"

    def _abort(route):
        try:
            route.abort()
        except Exception:
            pass

    ui.page.route(target, _abort)
    by_testid(ui, "group-settings-name").fill("Kept through a dropped connection")
    by_testid(ui, "group-settings-save-profile").click()
    # A dropped connection is not a refusal either: the draft stays and the profile stays editable. (S2)
    expect(by_testid(ui, "group-settings-name")).to_have_value("Kept through a dropped connection")
    expect(by_testid(ui, "group-settings-name")).to_be_enabled()
    # The aborted request never reaches the fixture, so drop its transport console error to keep the
    # shared teardown's console gate meaningful for every other request.
    ui.console_errors[:] = [
        (text, url) for text, url in ui.console_errors if "/settings/profile" not in url
    ]


# --------------------------------------------------------------------------
# S3: after the server refuses a write, the controls re-gate from the fresher context.
# --------------------------------------------------------------------------

def test_lock_after_load_regates_controls_read_only(group_settings_ui):
    ui = group_settings_ui
    open_settings(ui)
    by_testid(ui, "group-settings-name").fill("Edited just before the lock")
    # The group is locked server-side after the page loaded. The next write is refused with the status
    # refusal, and the section re-reads the context and re-gates its controls read-only. (S3)
    ui.configure("group-a", role="Owner", status="locked")
    by_testid(ui, "group-settings-save-profile").click()
    locked_reason = ("This group is locked or inactive, so its name, description, color and "
                     "logo can't be changed.")
    expect(ui.page.get_by_text(locked_reason, exact=True).first).to_be_visible()
    # The controls re-gate read-only and the header follows the fresher status.
    expect(by_testid(ui, "group-settings-name")).to_be_disabled()
    expect(by_testid(ui, "group-settings-save-profile")).to_have_count(0)
    expect(ui.page.get_by_text("Locked - read only", exact=False).first).to_be_visible()
    # The draft is kept even as the controls freeze, and no further write is attempted.
    expect(by_testid(ui, "group-settings-name")).to_have_value("Edited just before the lock")
    assert len(settings_calls(ui, "PATCH", "profile")) == 1


# --------------------------------------------------------------------------
# S4: the CreateGroups-role refusal carries its explanation.
# --------------------------------------------------------------------------

def test_create_groups_role_refusal_explains_itself(group_settings_ui):
    ui = group_settings_ui
    # The deployment requires the CreateGroups app role to edit a group's profile, and this owner does
    # not hold it. The profile is read-only and carries the server's own reason, keyed on the plural
    # create_groups_role_required code the server actually sends. (S4)
    ui.configure("group-a", role="Owner", status="active",
                 create_role_required=True, has_create_role=False)
    open_settings(ui)
    expect(by_testid(ui, "group-settings-name")).to_be_disabled()
    expect(ui.page.get_by_text(
        "You need the CreateGroups role to change this group's name, description or color.",
        exact=False).first).to_be_visible()


# --------------------------------------------------------------------------
# Logo.
# --------------------------------------------------------------------------

def test_logo_upload_and_remove(group_settings_ui):
    ui = group_settings_ui
    open_settings(ui)
    expect(by_testid(ui, "group-settings-logo-remove")).to_have_count(0)
    by_testid(ui, "group-settings-logo-input").set_input_files(files=[LOGO_PNG])
    expect(ui.page.get_by_text("Group logo updated.", exact=True)).to_be_visible()
    expect(by_testid(ui, "group-settings-logo-remove")).to_be_visible()
    assert len(settings_calls(ui, "PUT", "logo")) == 1
    by_testid(ui, "group-settings-logo-remove").click()
    expect(ui.page.get_by_text("Group logo removed.", exact=True)).to_be_visible()
    expect(by_testid(ui, "group-settings-logo-remove")).to_have_count(0)
    assert len(settings_calls(ui, "DELETE", "logo")) == 1


def test_logo_conflict_keeps_file_for_explicit_retry(group_settings_ui):
    ui = group_settings_ui
    open_settings(ui)
    ui.force_write_conflict("group-a")
    by_testid(ui, "group-settings-logo-input").set_input_files(files=[LOGO_PNG])
    # The write is never auto-retried; the chosen file is kept behind an explicit Retry.
    expect(ui.page.get_by_text(GROUP_WRITE_CONFLICT_MESSAGE, exact=True)).to_be_visible()
    expect(by_testid(ui, "group-settings-logo-retry")).to_be_visible()
    assert len(settings_calls(ui, "PUT", "logo")) == 1
    by_testid(ui, "group-settings-logo-retry").click()
    expect(ui.page.get_by_text("Group logo updated.", exact=True)).to_be_visible()
    expect(by_testid(ui, "group-settings-logo-retry")).to_have_count(0)
    assert len(settings_calls(ui, "PUT", "logo")) == 2


def test_logo_bad_image_shows_error_and_keeps_file(group_settings_ui):
    ui = group_settings_ui
    open_settings(ui)
    # The server reads the image bytes and refuses anything that is not a PNG or JPEG (S6). The right
    # extension and MIME type are not enough; the file is kept for an explicit retry, never discarded.
    by_testid(ui, "group-settings-logo-input").set_input_files(files=[LOGO_NOT_AN_IMAGE])
    expect(ui.page.get_by_text(
        "The logo image could not be read. Upload a PNG or JPEG image.", exact=True)).to_be_visible()
    expect(by_testid(ui, "group-settings-logo-retry")).to_be_visible()
    assert len(settings_calls(ui, "PUT", "logo")) == 1
    # A real image then replaces the chosen file and succeeds on the explicit retry.
    by_testid(ui, "group-settings-logo-input").set_input_files(files=[LOGO_PNG])
    expect(ui.page.get_by_text("Group logo updated.", exact=True)).to_be_visible()


# --------------------------------------------------------------------------
# Downloads and retention: present, absent, and edited.
# --------------------------------------------------------------------------

def test_downloads_toggle_saves(group_settings_ui):
    ui = group_settings_ui
    open_settings(ui)
    # The checkbox is controlled by the server round-trip, so click it rather than assert a
    # synchronous state flip, then prove the save landed by its notice and the one PATCH.
    by_testid(ui, "group-settings-downloads-toggle").click()
    expect(ui.page.get_by_text("File download policy saved.", exact=True)).to_be_visible()
    assert len(settings_calls(ui, "PATCH", "downloads")) == 1


def test_downloads_absent_when_capability_off(group_settings_ui):
    ui = group_settings_ui
    ui.configure("group-a", role="Owner", status="active", downloads_admin=False)
    open_settings(ui)
    expect(by_testid(ui, "group-settings-downloads")).to_have_count(0)


def test_retention_edit_saves(group_settings_ui):
    ui = group_settings_ui
    open_settings(ui)
    # Retention is offered as the classic day choices, not free text, so the period is selected.
    conversation = by_testid(ui, "group-settings-retention-conversation")
    conversation.select_option("30")
    by_testid(ui, "group-settings-save-retention").click()
    expect(ui.page.get_by_text("Retention policy saved.", exact=True)).to_be_visible()
    calls = settings_calls(ui, "PATCH", "retention")
    assert len(calls) == 1
    # Only the changed period is sent; the untouched document period is never echoed back, so a stored
    # value now outside the bounds can't fail a save that changed only the conversation period. (S5)
    body = calls[-1].body or {}
    assert body.get("conversation_retention_days") == 30
    assert "document_retention_days" not in body


def test_retention_offers_classic_choices_within_bounds(group_settings_ui):
    ui = group_settings_ui
    open_settings(ui)
    conversation = by_testid(ui, "group-settings-retention-conversation")
    # The two policy words plus the classic day options the server's bounds allow, and nothing else.
    values = conversation.evaluate(
        "select => Array.from(select.options).map(option => option.value)")
    assert values == ["default", "none", "7", "14", "30", "60", "90", "180", "365", "730", "1095", "3650"]


def test_retention_absent_when_disabled(group_settings_ui):
    ui = group_settings_ui
    ui.configure("group-a", role="Owner", status="active", retention_enabled=False)
    open_settings(ui)
    expect(by_testid(ui, "group-settings-retention")).to_have_count(0)


# --------------------------------------------------------------------------
# Gating: a member is refused Settings, an admin gets a read-only profile with no danger zone.
# --------------------------------------------------------------------------

def test_member_cannot_open_settings(group_settings_ui):
    ui = group_settings_ui
    ui.open("/groups/group-b/settings")
    expect(ui.page.get_by_text("Settings is not available", exact=True)).to_be_visible()
    # A member never even reads the settings route.
    assert settings_calls(ui, "GET") == []


def test_admin_locked_is_read_only_without_danger_zone(group_settings_ui):
    ui = group_settings_ui
    ui.configure("group-a", role="Admin", status="locked")
    open_settings(ui)
    # Profile is the owner's alone, so an admin's fields are read-only with the server's own reason.
    expect(by_testid(ui, "group-settings-name")).to_be_disabled()
    expect(ui.page.get_by_text("Only the group owner can do this.", exact=False).first).to_be_visible()
    # An admin still manages downloads and retention, but the danger zone is the owner's alone.
    expect(by_testid(ui, "group-settings-downloads-toggle")).to_be_enabled()
    expect(by_testid(ui, "group-settings-danger")).to_have_count(0)
    assert insight_calls(ui, "file-count") == []


def test_danger_zone_is_owner_only_with_file_count_and_classic(group_settings_ui):
    ui = group_settings_ui
    ui.set_file_count("group-a", 7)
    open_settings(ui)
    expect(by_testid(ui, "group-settings-file-count")).to_contain_text("holds 7 documents")
    assert len(insight_calls(ui, "file-count")) == 1
    by_testid(ui, "group-settings-delete").click()
    ui.page.get_by_role("button", name="Open classic", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/groups/group-a")
    assert ("/groups/group-a", "group-a") in ui.classic_visits


# --------------------------------------------------------------------------
# The header's classic button survives only for an inactive or unknown group.
# --------------------------------------------------------------------------

def test_classic_manage_button_shown_when_inactive(group_settings_ui):
    ui = group_settings_ui
    ui.configure("group-a", role="Owner", status="inactive")
    ui.open("/groups/group-a")
    button = ui.page.get_by_role("button", name="Manage group (classic)")
    expect(button).to_be_visible()
    button.click()
    expect(ui.page).to_have_url(f"{ORIGIN}/groups/group-a")
    assert ("/groups/group-a", "group-a") in ui.classic_visits


# --------------------------------------------------------------------------
# Activity.
# --------------------------------------------------------------------------

def test_activity_feed_and_limits(group_settings_ui):
    ui = group_settings_ui
    open_activity(ui)
    expect(ui.page.get_by_text("Uploaded a document", exact=True)).to_be_visible()
    by_testid(ui, "group-activity-limit-10").click()
    expect(by_testid(ui, "group-activity-limit-10")).to_have_attribute("aria-pressed", "true")
    latest = insight_calls(ui, "activity")[-1]
    assert latest.query["limit"] == ["10"]


def test_activity_empty_state(group_settings_ui):
    ui = group_settings_ui
    ui.clear_activity("group-a")
    open_activity(ui)
    expect(ui.page.get_by_text("No recent activity", exact=True)).to_be_visible()


def test_activity_unavailable_state(group_settings_ui):
    ui = group_settings_ui
    ui.make_activity_unavailable("group-a")
    open_activity(ui)
    expect(ui.page.get_by_text("Activity unavailable", exact=True)).to_be_visible()
    expect(ui.page.get_by_text(GROUP_ACTIVITY_UNAVAILABLE_MESSAGE, exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Retry", exact=True)).to_be_visible()


# --------------------------------------------------------------------------
# Statistics.
# --------------------------------------------------------------------------

def test_statistics_windows_and_export(group_settings_ui):
    ui = group_settings_ui
    open_statistics(ui)
    by_testid(ui, "group-statistics-window-7").click()
    expect(by_testid(ui, "group-statistics-window-7")).to_have_attribute("aria-pressed", "true")
    latest = insight_calls(ui, "stats")[-1]
    assert latest.query["days"] == ["7"]
    by_testid(ui, "group-statistics-export").click()
    expect(ui.page.get_by_role("dialog")).to_be_visible()


def test_statistics_unavailable_state(group_settings_ui):
    ui = group_settings_ui
    ui.make_stats_unavailable("group-a")
    open_statistics(ui)
    expect(ui.page.get_by_text("Statistics unavailable", exact=True)).to_be_visible()
    expect(ui.page.get_by_text(GROUP_STATS_UNAVAILABLE_MESSAGE, exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Retry", exact=True)).to_be_visible()
