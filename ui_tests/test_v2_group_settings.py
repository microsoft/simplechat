# test_v2_group_settings.py
"""
Production-SPA coverage for the native V2 group Settings, Activity and Statistics sections.
Version: 0.261.448
Implemented in: 0.261.165
An unrecognized status is explained with the server's own sentence: 0.261.188
The danger zone deletes the group natively, and an inactive or unknown group's owner and admins keep
these sections with no classic handoff: 0.261.448

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
danger zone as owner-only with its file count and the native delete -- held while documents remain
(including one that arrives while the confirmation is open), confirmed, refused with the server's
words or a plain sentence for a 5xx or a dropped connection, retried, already deleted elsewhere,
sent once however often it is clicked, and held back by unsaved edits; an inactive or unknown group,
whose owner and admins keep a read-only Settings, Activity and Statistics with no "Manage group
(classic)" button; the activity feed with its limits, empty and
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
from ui_tests.fixtures.group_workspace import (
    GROUP_SETTINGS_REFUSAL_MESSAGES, GROUP_STATUS_UNAVAILABLE, GROUP_STATUS_UNRECOGNIZED_MESSAGE,
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

# The native delete's route and the sentences the section shows for it (WorkspaceSettingsSection and
# GroupSettingsSection own the wording; the apostrophes are the typographic ones the page renders).
GROUP_DELETE_PATH = "/api/groups/group-a"
GROUP_DELETE_HELD = "The group wasn\u2019t deleted because it still holds documents. Remove them first."
GROUP_DELETE_FAILED = "The group couldn\u2019t be deleted. Try again."
GROUP_DELETE_GONE = "This group no longer exists. It may already have been deleted."


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


def delete_calls(ui):
    return [entry for entry in ui.requests if entry.method == "DELETE" and entry.path == GROUP_DELETE_PATH]


def delete_group_dialog(ui):
    return ui.page.get_by_role("dialog", name="Delete this group?", exact=True)


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
def test_settings_layout(group_settings_ui, theme, width, height):
    ui = group_settings_ui
    ui.set_logo_present("group-a")
    open_settings(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("heading", name="Group settings", exact=True)).to_be_visible()
    for panel in ("group-settings-name", "group-settings-logo-upload",
                  "group-settings-downloads", "group-settings-retention", "group-settings-danger"):
        expect(by_testid(ui, panel)).to_be_visible()
    # The header carries no classic button for any status: every Manage section is native.
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
    # Wait for the failure alert first, so the write has actually settled and any errant reload() would
    # already have fired; asserting the draft before the abort is processed could never fail. (S17)
    expect(ui.page.get_by_role("alert").first).to_be_visible()
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


def test_an_unrecognized_status_is_explained_with_its_own_sentence(group_settings_ui):
    """A group whose status the server doesn't recognize is read-only for the same reason code as a
    locked one, but the server refuses its writes with a sentence of its own. The context closes Settings
    on its next read, yet a section already open adopts each write's fresh settings, and a retention save
    stays allowed: after one, the profile's reason is that sentence, never "locked or inactive" (M11)."""
    ui = group_settings_ui
    open_settings(ui)
    expect(by_testid(ui, "group-settings-name")).to_be_enabled()
    # The group's stored status changes to one this version doesn't recognize while the section is open.
    ui.configure("group-a", role="Owner", status="unknown")
    by_testid(ui, "group-settings-retention-conversation").select_option("30")
    by_testid(ui, "group-settings-save-retention").click()
    expect(ui.page.get_by_text("Retention policy saved.", exact=True)).to_be_visible()
    expect(by_testid(ui, "group-settings-name")).to_be_disabled()
    expect(ui.page.get_by_text(GROUP_STATUS_UNRECOGNIZED_MESSAGE, exact=True).first).to_be_visible()
    locked = GROUP_SETTINGS_REFUSAL_MESSAGES[GROUP_STATUS_UNAVAILABLE]
    expect(ui.page.get_by_text(locked, exact=True)).to_have_count(0)


# --------------------------------------------------------------------------
# S14: a re-gated read-only draft no longer strands the page dirty.
# --------------------------------------------------------------------------

def test_lock_regate_frees_picker_and_downloads_and_offers_discard(group_settings_ui):
    ui = group_settings_ui
    open_settings(ui)
    original = by_testid(ui, "group-settings-name").input_value()
    by_testid(ui, "group-settings-name").fill("Edited just before the lock")
    # While the profile draft is editable and dirty, the picker search and the downloads switch are
    # frozen -- the group can't be switched, and the immediate-save switch can't fire, mid-edit.
    expect(ui.page.get_by_placeholder("Search all your groups")).to_be_disabled()
    expect(by_testid(ui, "group-settings-downloads-toggle")).to_be_disabled()
    # The group locks server-side; the refused save re-gates the profile read-only and keeps the draft.
    ui.configure("group-a", role="Owner", status="locked")
    by_testid(ui, "group-settings-save-profile").click()
    expect(by_testid(ui, "group-settings-name")).to_be_disabled()
    expect(by_testid(ui, "group-settings-save-profile")).to_have_count(0)
    # S14: the now read-only draft is dropped from the leave guard, so the picker frees again and the
    # downloads switch follows only its own gate -- an owner in a locked group may still use it. A
    # Discard control stays available and clears the stranded draft when clicked.
    expect(ui.page.get_by_placeholder("Search all your groups")).to_be_enabled()
    expect(by_testid(ui, "group-settings-downloads-toggle")).to_be_enabled()
    discard = by_testid(ui, "group-settings-discard-profile")
    expect(discard).to_be_visible()
    discard.click()
    expect(by_testid(ui, "group-settings-name")).to_have_value(original)
    expect(by_testid(ui, "group-settings-discard-profile")).to_have_count(0)


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


def test_downloads_toggle_refreshes_context(group_settings_ui):
    ui = group_settings_ui
    open_settings(ui)
    before = len(context_calls(ui))
    # S16: a downloads save refreshes the workspace context, so the Documents section drops Download
    # without waiting for a refocus. The save fires a fresh context GET; wait for it to land.
    with ui.page.expect_response(
        lambda response: response.url.endswith("/api/v2/workspaces/group/group-a")
        and response.request.method == "GET"
    ):
        by_testid(ui, "group-settings-downloads-toggle").click()
    expect(ui.page.get_by_text("File download policy saved.", exact=True)).to_be_visible()
    assert len(settings_calls(ui, "PATCH", "downloads")) == 1
    assert len(context_calls(ui)) > before


def test_status_change_keeps_a_settings_write(group_settings_ui):
    ui = group_settings_ui
    open_settings(ui)
    # Turn downloads off: a real write that lands in the fixture's settings store.
    by_testid(ui, "group-settings-downloads-toggle").click()
    expect(ui.page.get_by_text("File download policy saved.", exact=True)).to_be_visible()
    # The group is then rebuilt for a new status. S20: the fixture replays the settings store over the
    # rebuilt context, so the downloads-off write is still there in the very next context read. The
    # server, which reads the same settings on every context build, never reverts it either.
    ui.configure("group-a", role="Owner", status="active")
    with ui.page.expect_response(
        lambda response: response.url.endswith("/api/v2/workspaces/group/group-a")
        and response.request.method == "GET"
    ) as info:
        ui.page.evaluate("window.dispatchEvent(new Event('focus'))")
    context = info.value.json()
    assert context["document_permissions"]["can_download"] is False
    assert "download" not in context["document_management"].get("operations", [])


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


def test_danger_zone_is_owner_only_with_the_file_count(group_settings_ui):
    ui = group_settings_ui
    ui.set_file_count("group-a", 7)
    open_settings(ui)
    expect(by_testid(ui, "group-settings-file-count")).to_contain_text("holds 7 documents")
    assert len(insight_calls(ui, "file-count")) == 1
    # Before anything is clicked the zone says what a delete does and what it leaves behind.
    expect(by_testid(ui, "group-settings-danger")).to_contain_text("removes only the group and every member")
    expect(by_testid(ui, "group-settings-danger")).to_contain_text(
        "conversations, prompts, agents, actions and other saved items are left behind")
    assert not delete_calls(ui) and not ui.classic_visits


# --------------------------------------------------------------------------
# Deleting the group natively: the count gate, the confirmation, every refusal, one send.
# --------------------------------------------------------------------------

def test_delete_is_held_while_the_group_holds_documents(group_settings_ui):
    ui = group_settings_ui
    ui.set_file_count("group-a", 7)
    open_settings(ui)
    by_testid(ui, "group-settings-delete").click()
    expect(by_testid(ui, "group-settings-danger-error")).to_have_text(GROUP_DELETE_HELD)
    expect(delete_group_dialog(ui)).to_have_count(0)
    # The count is read again at the click, as classic does, and nothing is ever sent to delete.
    assert len(insight_calls(ui, "file-count")) == 2
    assert not delete_calls(ui) and not ui.deleted_groups and not ui.classic_visits


def test_a_document_that_arrives_while_the_confirmation_is_open_holds_the_delete(group_settings_ui):
    ui = group_settings_ui
    ui.set_file_count("group-a", 0)
    open_settings(ui)
    by_testid(ui, "group-settings-delete").click()
    confirm = delete_group_dialog(ui)
    expect(confirm).to_be_visible()
    # The server checks nothing about documents, so the page reads the count once more before sending.
    ui.set_file_count("group-a", 2)
    confirm.get_by_role("button", name="Delete group", exact=True).click()
    expect(confirm).to_have_count(0)
    expect(by_testid(ui, "group-settings-danger-error")).to_have_text(GROUP_DELETE_HELD)
    expect(by_testid(ui, "group-settings-file-count")).to_contain_text("holds 2 documents")
    assert not delete_calls(ui) and not ui.deleted_groups


def test_the_owner_deletes_an_empty_group_and_returns_to_the_list(group_settings_ui):
    ui = group_settings_ui
    ui.set_file_count("group-a", 0)
    open_settings(ui)
    expect(by_testid(ui, "group-settings-file-count")).to_have_text("This group holds no documents.")
    by_testid(ui, "group-settings-delete").click()
    confirm = delete_group_dialog(ui)
    expect(confirm).to_be_visible()
    expect(confirm).to_contain_text("Every member loses access to it right away")
    expect(confirm).to_contain_text(
        "conversations, prompts, agents, actions and other saved items are left behind")
    assert not delete_calls(ui), "Nothing is sent until the confirmation."
    confirm.get_by_role("button", name="Delete group", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups")
    expect(ui.page.get_by_text("Choose a group workspace", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Research group was deleted.", exact=True)).to_be_visible()
    [removal] = delete_calls(ui)
    assert removal.body is None and removal.query == {}
    assert ui.deleted_groups == ["group-a"]
    bootstrap_reads = [index for index, entry in enumerate(ui.requests) if entry.path == "/api/v2/bootstrap"]
    assert bootstrap_reads[-1] > ui.requests.index(removal), "The groups are read again after the delete."
    expect(ui.page.get_by_role("dialog")).to_have_count(0)
    assert not ui.classic_visits, "A native delete never visits the classic pages."


def test_cancelling_the_confirmation_sends_nothing(group_settings_ui):
    ui = group_settings_ui
    ui.set_file_count("group-a", 0)
    open_settings(ui)
    by_testid(ui, "group-settings-delete").click()
    confirm = delete_group_dialog(ui)
    confirm.get_by_role("button", name="Cancel", exact=True).click()
    expect(confirm).to_have_count(0)
    expect(by_testid(ui, "group-settings-delete")).to_be_enabled()
    assert not delete_calls(ui) and not ui.deleted_groups


@pytest.mark.parametrize("status,payload,shown", [
    pytest.param(
        403, {"error": "Forbidden", "message": "Insufficient permissions (CreateGroups role required)"},
        "Insufficient permissions (CreateGroups role required)", id="403-create-groups-role",
    ),
    pytest.param(
        403, {"error": "Only the owner can delete the group"},
        "Only the owner can delete the group", id="403-owner-only",
    ),
    pytest.param(
        409, {"error": "The group changed while it was being deleted."},
        "The group changed while it was being deleted.", id="409-conflict",
    ),
    pytest.param(
        500, {"error": "Internal cosmos failure for partition 7"},
        GROUP_DELETE_FAILED, id="500-never-raw",
    ),
])
def test_a_refused_delete_says_why_keeps_the_group_and_can_be_retried(group_settings_ui, status, payload, shown):
    ui = group_settings_ui
    ui.set_file_count("group-a", 0)
    open_settings(ui)
    by_testid(ui, "group-settings-delete").click()
    confirm = delete_group_dialog(ui)
    error, *rest = payload.items()
    ui.reject_next("DELETE", GROUP_DELETE_PATH, status=status, error=error[1], **dict(rest))
    confirm.get_by_role("button", name="Delete group", exact=True).click()
    # The server's words (or a plain sentence for a 5xx) appear in the dialog, which stays open.
    expect(by_testid(ui, "group-settings-delete-error")).to_have_text(shown)
    expect(confirm).to_be_visible()
    expect(confirm.get_by_role("button", name="Delete group", exact=True)).to_be_enabled()
    assert "Internal cosmos failure" not in ui.page.locator("body").inner_text()
    assert not ui.deleted_groups and ui.page.url == f"{ORIGIN}/v2/groups/group-a/settings"
    # Nothing was lost, so the same dialog can send the delete again, and it goes through.
    confirm.get_by_role("button", name="Delete group", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups")
    assert ui.deleted_groups == ["group-a"]
    assert len(delete_calls(ui)) == 2


def test_a_dropped_connection_never_shows_a_raw_error_and_can_be_retried(group_settings_ui):
    ui = group_settings_ui
    ui.set_file_count("group-a", 0)
    open_settings(ui)
    by_testid(ui, "group-settings-delete").click()
    confirm = delete_group_dialog(ui)

    def _abort(route):
        if route.request.method == "DELETE":
            route.abort()
        else:
            route.fallback()

    ui.page.route("**/api/groups/group-a", _abort)
    confirm.get_by_role("button", name="Delete group", exact=True).click()
    expect(by_testid(ui, "group-settings-delete-error")).to_have_text(GROUP_DELETE_FAILED)
    expect(confirm).to_be_visible()
    assert not ui.deleted_groups
    # The aborted request never reaches the fixture, so drop its transport console error, as the
    # profile network test does, to keep the shared teardown's console gate meaningful.
    ui.console_errors[:] = [(text, url) for text, url in ui.console_errors if not url.endswith("/api/groups/group-a")]
    ui.page.unroute("**/api/groups/group-a", _abort)
    confirm.get_by_role("button", name="Delete group", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups")
    assert ui.deleted_groups == ["group-a"]


def test_a_group_already_deleted_elsewhere_is_left_as_after_a_delete(group_settings_ui):
    ui = group_settings_ui
    ui.set_file_count("group-a", 0)
    open_settings(ui)
    by_testid(ui, "group-settings-delete").click()
    confirm = delete_group_dialog(ui)
    ui.defer_next("DELETE", GROUP_DELETE_PATH)
    confirm.get_by_role("button", name="Delete group", exact=True).click()
    wait_for_delete(ui)
    # Another session deletes the group first, so the held DELETE meets the route's own 404.
    ui.groups.pop("group-a")
    ui.active_group = None
    ui.release_responses()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups")
    expect(ui.page.get_by_text(GROUP_DELETE_GONE, exact=True)).to_be_visible()
    assert not ui.deleted_groups, "This session deleted nothing."
    expect(ui.page.get_by_role("dialog")).to_have_count(0)


def test_a_second_click_while_the_delete_is_in_flight_sends_nothing(group_settings_ui):
    ui = group_settings_ui
    ui.set_file_count("group-a", 0)
    open_settings(ui)
    by_testid(ui, "group-settings-delete").click()
    confirm = delete_group_dialog(ui)
    submit = confirm.get_by_role("button", name="Delete group", exact=True)
    ui.defer_next("DELETE", GROUP_DELETE_PATH)
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
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups")
    assert ui.deleted_groups == ["group-a"] and len(delete_calls(ui)) == 1


def test_delete_waits_for_unsaved_profile_edits(group_settings_ui):
    ui = group_settings_ui
    ui.set_file_count("group-a", 0)
    open_settings(ui)
    by_testid(ui, "group-settings-name").fill("A half-finished rename")
    expect(by_testid(ui, "group-settings-delete")).to_be_disabled()
    expect(by_testid(ui, "group-settings-delete-unsaved")).to_have_text(
        "Save or discard your profile and retention changes before deleting the group.")
    by_testid(ui, "group-settings-discard-profile").click()
    expect(by_testid(ui, "group-settings-delete")).to_be_enabled()
    expect(by_testid(ui, "group-settings-delete-unsaved")).to_have_count(0)
    assert not delete_calls(ui)


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_the_delete_confirmation_fits_every_layout(group_settings_ui, theme, width, height):
    ui = group_settings_ui
    ui.set_file_count("group-a", 0)
    open_settings(ui, theme=theme, width=width, height=height)
    by_testid(ui, "group-settings-delete").click()
    confirm = delete_group_dialog(ui)
    expect(confirm).to_be_visible()
    box = confirm.bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= width, "The dialog is clipped horizontally."
    expect(confirm.get_by_role("button", name="Delete group", exact=True)).to_be_visible()
    ui.assert_no_overflow()
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    label = f'{"mobile" if width < 768 else "desktop"}-{theme}'
    ui.page.screenshot(path=str(SCREENSHOTS / f"delete-confirmation-{label}.png"))


# --------------------------------------------------------------------------
# An inactive, locked or unknown group: the owner keeps a native, read-only Settings.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["inactive", "unknown"])
def test_an_inactive_or_unknown_groups_owner_keeps_a_read_only_settings_and_no_classic_button(group_settings_ui, status):
    ui = group_settings_ui
    ui.configure("group-a", role="Owner", status=status)
    ui.open("/groups/group-a")
    # The header no longer carries "Manage group (classic)" for any status.
    expect(ui.page.get_by_role("button", name="Manage group (classic)")).to_have_count(0)
    open_settings(ui)
    expect(by_testid(ui, "group-settings-name")).to_be_disabled()
    expect(by_testid(ui, "group-settings-save-profile")).to_have_count(0)
    sentence = (GROUP_STATUS_UNRECOGNIZED_MESSAGE if status == "unknown"
                else GROUP_SETTINGS_REFUSAL_MESSAGES[GROUP_STATUS_UNAVAILABLE])
    expect(ui.page.get_by_text(sentence, exact=True).first).to_be_visible()
    # Downloads and retention follow the owner's own gates, and the danger zone stays the owner's.
    expect(by_testid(ui, "group-settings-downloads-toggle")).to_be_enabled()
    expect(by_testid(ui, "group-settings-danger")).to_be_visible()
    assert not ui.classic_visits


@pytest.mark.parametrize("status", ["inactive", "unknown"])
def test_an_inactive_or_unknown_groups_owner_keeps_activity_and_statistics(group_settings_ui, status):
    ui = group_settings_ui
    ui.configure("group-a", role="Owner", status=status)
    open_activity(ui)
    expect(ui.page.get_by_text("Uploaded a document", exact=True)).to_be_visible()
    open_statistics(ui)
    by_testid(ui, "group-statistics-window-7").click()
    expect(by_testid(ui, "group-statistics-window-7")).to_have_attribute("aria-pressed", "true")
    assert insight_calls(ui, "stats")[-1].query["days"] == ["7"]
    assert not ui.classic_visits


@pytest.mark.parametrize("status", ["inactive", "unknown"])
def test_an_inactive_groups_admin_keeps_settings_without_the_danger_zone(group_settings_ui, status):
    ui = group_settings_ui
    ui.configure("group-a", role="Admin", status=status)
    open_settings(ui)
    expect(by_testid(ui, "group-settings-name")).to_be_disabled()
    expect(by_testid(ui, "group-settings-danger")).to_have_count(0)
    assert insight_calls(ui, "file-count") == []


def test_a_plain_member_of_an_inactive_group_still_gets_the_reason_not_settings(group_settings_ui):
    ui = group_settings_ui
    ui.configure("group-a", role="User", status="inactive")
    ui.open("/groups/group-a/settings")
    expect(ui.page.get_by_text("Settings is not available", exact=True)).to_be_visible()
    assert settings_calls(ui, "GET") == []


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
