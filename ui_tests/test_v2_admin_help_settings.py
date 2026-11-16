# test_v2_admin_help_settings.py
"""
Browser coverage for the V2 Admin Settings Help group.
Version: 0.261.276
Implemented in: 0.261.276

Exercise the built application with the real Help field schema, the real Latest
Features catalogues and intercepted APIs. Check the four Help cards and the
registration badge do what the classic page does, in the V2 design language:

- Support nests its settings under the menu switch, reads "Needs configuration"
  while Send Feedback has no recipient, flags that field, and refuses a malformed
  address in place.
- The Send Feedback cards validate, post to the classic endpoint and offer the
  mailto draft, without ever touching the settings draft.
- User-Facing Latest Features says when nothing is published and jumps to Support,
  previews what users see, and saves a complete visibility map.
- Admin Latest Features is drawn from the catalogue with a New badge on the card
  and the category, and its shortcuts jump within V2 or open the classic tab.
- The Registered/Unregistered badge registers the deployment.

Nothing is written to live settings, and unexpected requests fail the test.
"""

import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui

HELP_SECTIONS = {
    "help": (
        "support-menu-section",
        "send-feedback-overview-card",
        "send-feedback-bug-card",
        "send-feedback-feature-card",
        "user-facing-latest-features-section",
        "latest-features",
    ),
}
ARTIFACTS = "v2_admin_help"

# Chromium has no mail handler in the test browser, so opening a draft logs this.
MAILTO_LAUNCH_ERROR = re.compile(r"Failed to launch 'mailto:")


@pytest.fixture
def help_ui(page):
    fixture = AdminSettingsFixture(page, sections=HELP_SECTIONS, validate_updates=True)
    yield fixture
    fixture.errors[:] = [error for error in fixture.errors if not MAILTO_LAUNCH_ERROR.search(error)]
    fixture.assert_clean()


def _region(page, name):
    return page.get_by_role("region", name=name, exact=True)


def _no_horizontal_overflow(page):
    overflow = page.get_by_test_id("admin-settings-scroll").evaluate(
        "element => element.scrollWidth - element.clientWidth"
    )
    assert overflow <= 1, f"The settings pane scrolls sideways by {overflow}px"


def test_support_card_needs_a_recipient_and_refuses_a_bad_one(help_ui):
    help_ui.open(ready_region="Support")
    page = help_ui.page
    support = _region(page, "Support")

    expect(support.get_by_text("Off", exact=True)).to_be_visible()
    expect(support.get_by_label("Menu Name")).to_have_count(0)

    support.get_by_text("Enable Support Menu for End Users", exact=True).click()
    expect(support.get_by_label("Menu Name")).to_have_value("Support")
    expect(support.get_by_text("Enable Send Feedback Destination", exact=True)).to_be_visible()
    recipient = support.get_by_label("Support Recipient Email")
    expect(recipient).to_have_attribute("type", "email")
    expect(support.get_by_text("Required", exact=True)).to_be_visible()
    expect(support.get_by_text("Needs configuration", exact=True)).to_be_visible()

    # The misfiled switch that used to sit on the Send Feedback overview is gone.
    expect(_region(page, "Overview").get_by_text("Support send feedback")).to_have_count(0)

    recipient.fill("help desk@contoso")
    page.get_by_role("button", name="Save changes").click()
    expect(support.get_by_role("alert")).to_contain_text("Enter one email address")
    expect(recipient).to_have_value("help desk@contoso")
    assert help_ui.settings["enable_support_menu"] is False, "A rejected save must not land half-applied."
    # The refused save is answered with a 400, which the browser logs; it is the point here.
    help_ui.errors = [error for error in help_ui.errors if "400 (Bad Request)" not in error]

    recipient.fill("help@contoso.com")
    expect(support.get_by_text("Required", exact=True)).to_have_count(0)
    expect(support.get_by_text("Configured", exact=True)).to_be_visible()
    page.get_by_role("button", name="Save changes").click()
    expect(page.get_by_role("button", name="Save changes")).to_have_count(0)
    assert help_ui.patches[-1]["support_feedback_recipient_email"] == "help@contoso.com"
    assert help_ui.settings["enable_support_menu"] is True


def test_support_saves_without_a_recipient_and_says_why(help_ui):
    help_ui.open(ready_region="Support")
    page = help_ui.page
    support = _region(page, "Support")

    support.get_by_text("Enable Support Menu for End Users", exact=True).click()
    page.get_by_role("button", name="Save changes").click()
    expect(support.get_by_text("Users won't see Send Feedback until a recipient email is set.")).to_be_visible()
    expect(support.get_by_text("Needs configuration", exact=True)).to_be_visible()
    assert help_ui.settings["enable_support_send_feedback"] is True, (
        "Unlike the classic form, turning the menu on must not switch Send Feedback off."
    )

    # The destination says where the announcements it publishes are chosen.
    expect(support.get_by_text("Shown in Help", exact=False)).to_be_visible()
    support.get_by_role("button", name="Go to User-Facing Latest Features").click()
    expect(page.get_by_role("heading", name="User-Facing Latest Features", level=2)).to_be_focused()


def test_send_feedback_validates_and_prepares_a_draft(help_ui):
    help_ui.open(ready_region="Report a Bug")
    page = help_ui.page
    bug = _region(page, "Report a Bug")

    expect(bug.get_by_label("Name")).to_have_value("Test Admin")
    expect(bug.get_by_label("Email")).to_have_value("test.admin@contoso.test")

    bug.get_by_role("button", name="Open Bug Report Email").click()
    expect(bug.get_by_text("Enter your organization.")).to_be_visible()
    expect(bug.get_by_text("Describe the feedback.")).to_be_visible()
    expect(bug.get_by_label("Organization")).to_be_focused()
    assert not help_ui.feedback_posts, "An incomplete report must not be posted."

    bug.get_by_label("Organization").fill("Contoso")
    bug.get_by_label("Bug Details").fill("Citations do not open after an upload.")
    # Typing a report is not a settings edit.
    expect(page.get_by_role("button", name="Save changes")).to_have_count(0)

    bug.get_by_role("button", name="Open Bug Report Email").click()
    draft = bug.get_by_role("link", name="open the draft")
    expect(draft).to_be_visible()
    expect(bug).to_contain_text("Draft prepared for simplechat@microsoft.com")
    href = draft.get_attribute("href") or ""
    assert href.startswith("mailto:simplechat@microsoft.com?subject="), href
    assert "Citations%20do%20not%20open" in href and "App%20Version%3A%200.261.093" in href, href

    assert help_ui.feedback_posts == [{
        "feedbackType": "bug_report",
        "reporterName": "Test Admin",
        "reporterEmail": "test.admin@contoso.test",
        "organization": "Contoso",
        "details": "Citations do not open after an upload.",
    }]

    # The overview explains the difference from the users' own Send Feedback.
    _region(page, "Overview").get_by_role("button", name="Open Support settings").click()
    expect(page.get_by_role("heading", name="Support", level=2)).to_be_focused()


def test_user_facing_choices_preview_and_save_a_full_map(help_ui):
    help_ui.open(ready_region="User-Facing Latest Features")
    page = help_ui.page
    card = _region(page, "User-Facing Latest Features")

    publication = card.get_by_test_id("latest-features-publication")
    expect(publication).to_contain_text("Not published yet")
    expect(publication).to_contain_text("The Support menu is off")
    expect(card.get_by_text("77 of 79 shared", exact=True)).to_be_visible()

    first = help_ui._latest_features_payload()["user"][0]["features"][0]
    checkbox = card.get_by_role("checkbox", name=first["title"])
    expect(checkbox).to_be_checked()
    checkbox.uncheck()
    expect(card.get_by_text("Hidden from users").first).to_be_visible()
    expect(card.get_by_text("76 of 79 shared", exact=True)).to_be_visible()

    card.get_by_role("button", name=f"Preview for {first['title']}").click()
    expect(card.get_by_text("Steps users are given").first).to_be_visible()
    if first["images"]:
        card.get_by_role("button", name=re.compile(r"\(enlarge\)$")).first.click()
        dialog = page.get_by_role("dialog")
        expect(dialog.locator("img")).to_be_visible()
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)

    page.get_by_role("button", name="Save changes").click()
    expect(page.get_by_role("button", name="Save changes")).to_have_count(0)
    saved = help_ui.patches[-1]["support_latest_features_visibility"]
    assert len(saved) == 79, f"The saved map should name every announcement, got {len(saved)}"
    assert saved[first["id"]] is False
    assert saved["deployment"] is False and saved["redis_key_vault"] is False

    publication.get_by_role("button", name="Open Support settings").click()
    expect(page.get_by_role("heading", name="Support", level=2)).to_be_focused()


def test_admin_latest_features_card_and_shortcuts(help_ui):
    help_ui.open(ready_region="Admin Latest Features")
    page = help_ui.page

    expect(page.get_by_role("button", name=re.compile(r"^Help\s*New$"))).to_be_visible()
    card = _region(page, "Admin Latest Features")
    expect(card.get_by_text("New", exact=True)).to_be_visible()
    expect(card.get_by_text("Enterprise Data Management: Backup, Restore & Migration", exact=True)).to_be_visible()
    expect(card.get_by_text("Custom Pages Administration", exact=True)).to_have_count(0)

    card.get_by_role("button", name="Details for Enterprise Data Management: Backup, Restore & Migration").click()
    expect(card.get_by_text("Rollout notes").first).to_be_visible()
    backup = card.get_by_role("link", name=re.compile(r"^Open Backup"))
    expect(backup).to_have_attribute("href", "/admin/settings#backup")

    title = "Feedback & Safety Violation Archive / Delete Lifecycle"
    card.get_by_role("button", name=f"Details for {title}").click()
    card.get_by_role("button", name="Open Send Feedback").click()
    expect(page.get_by_role("heading", name="Overview", level=2)).to_be_focused()

    # A search finds an announcement by its content and opens its release.
    page.get_by_role("searchbox", name="Search settings").fill("Custom Pages Administration")
    expect(card.get_by_text("Custom Pages Administration", exact=True)).to_be_visible()
    expect(
        card.get_by_text("Enterprise Data Management: Backup, Restore & Migration", exact=True)
    ).to_have_count(0)
    assert help_ui.latest_features_requests == 1, "The catalogues are fetched once per page load."


def test_registration_badge_registers_the_deployment(help_ui):
    help_ui.open(ready_region="Support")
    page = help_ui.page

    page.get_by_role("button", name="Unregistered for release notifications").click()
    dialog = page.get_by_role("dialog", name="Release notifications")
    expect(dialog.get_by_label("Your Name")).to_have_value("Test Admin")
    expect(dialog.get_by_label("Email")).to_have_value("test.admin@contoso.test")

    page.get_by_role("button", name="Submit registration").click()
    expect(dialog.get_by_text("Enter your organization.")).to_be_visible()
    assert not help_ui.registration_posts

    dialog.get_by_label("Organization").fill("Contoso")
    page.get_by_role("button", name="Submit registration").click()
    expect(dialog.get_by_text("This deployment is registered", exact=False)).to_be_visible()
    expect(dialog).to_contain_text("Contoso")
    expect(dialog.get_by_role("link", name=re.compile(r"open the draft to simplechat@microsoft.com"))).to_be_visible()
    assert help_ui.registration_posts == [
        {"name": "Test Admin", "email": "test.admin@contoso.test", "organization": "Contoso"}
    ]

    page.keyboard.press("Escape")
    expect(page.get_by_role("button", name="Registered for release notifications")).to_be_visible()


@pytest.mark.parametrize("theme,width", [("light", 1920), ("dark", 1440), ("light", 390), ("dark", 390)])
def test_help_group_fits_every_width_and_theme(help_ui, theme, width):
    help_ui.open(theme=theme, width=width, ready_region="Support")
    page = help_ui.page

    _region(page, "Support").get_by_text("Enable Support Menu for End Users", exact=True).click()
    card = _region(page, "Admin Latest Features")
    card.get_by_role("button", name="Details for Enterprise Data Management: Backup, Restore & Migration").click()
    user_card = _region(page, "User-Facing Latest Features")
    first = help_ui._latest_features_payload()["user"][0]["features"][0]
    user_card.get_by_role("button", name=f"Preview for {first['title']}").click()

    _no_horizontal_overflow(page)
    help_ui.capture(f"help-{theme}-{width}", ARTIFACTS)
