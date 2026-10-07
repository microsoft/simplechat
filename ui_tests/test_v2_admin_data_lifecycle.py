# test_v2_admin_data_lifecycle.py
"""
Browser coverage for the V2 Admin Settings Data Lifecycle group.
Version: 0.261.260
Implemented in: 0.261.260

Exercise the built application with the real Data Lifecycle schema, the real settings
normalizer and in-memory retention routes. Check that Retention Policy, Document
Classification and Conversation Archiving render their real controls rather than bare
switches; that switching a workspace type on reveals its defaults and reschedules the next
run on save; that Run now and Reset to defaults review saved settings only, are held while
edits are unsaved, report per-type results, and never show server exception text; that
categories are edited, validated and saved in order; and that the cards fit a phone at
large text in light and dark -- without writing to live settings.
"""

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from data_lifecycle_admin import SERVER_EXCEPTION_TEXT, DataLifecycleAdminFixture  # noqa: E402
from v2_admin_settings import connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui

ARTIFACTS = "v2_admin_data_lifecycle"


@pytest.fixture
def lifecycle(page):
    fixture = DataLifecycleAdminFixture(page)
    yield fixture
    fixture.assert_clean()


def _region(page, name):
    return page.get_by_role("region", name=name, exact=True)


def _switch(scope, label):
    return scope.get_by_role("checkbox", name=re.compile(f"^{re.escape(label)}"))


def _toggle(scope, label, checked):
    switch = _switch(scope, label)
    if switch.is_checked() != checked:
        scope.get_by_text(label, exact=True).first.click()
    expect(switch).to_be_checked(checked=checked)


def _save(page):
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)


def test_sections_render_real_controls_instead_of_bare_switches(lifecycle):
    lifecycle.open_data_lifecycle()
    page = lifecycle.page

    retention = _region(page, "Retention Policy")
    for label in ("Personal workspaces", "Group workspaces", "Public workspaces"):
        expect(_switch(retention, label)).to_have_count(1)
    expect(_switch(retention, "Personal workspaces")).to_be_checked()
    expect(_switch(retention, "Public workspaces")).not_to_be_checked()
    # Each type carries its own icon, and none of them is promoted over the others.
    for icon in ("lucide-user", "lucide-users", "lucide-globe"):
        expect(retention.locator(f'[aria-hidden="true"] svg.{icon}')).to_have_count(1)
    expect(retention.locator('[data-setting-emphasis="primary"]')).to_have_count(0)
    # The fallback printed storage keys under each switch; the described section does not.
    expect(retention.get_by_text("enable_retention_policy_group", exact=True)).to_have_count(0)

    # Defaults appear for the two types that are on, nested beneath their switch.
    expect(retention.get_by_label("Default conversation retention", exact=True)).to_have_count(2)
    expect(page.locator("#admin-field-default_retention_conversation_public")).to_have_count(0)
    expect(page.locator("#admin-field-default_retention_document_group")).to_have_value("365")
    expect(retention.locator('[data-setting-emphasis="dependent"]')).to_have_count(4)

    hour = retention.get_by_label("Daily run time", exact=True)
    expect(hour).to_have_value("2")
    expect(hour.locator("option")).to_have_count(24)
    readout = retention.get_by_test_id("retention-schedule-readout")
    expect(readout).to_contain_text("Last run")
    expect(readout).to_contain_text("yesterday")
    expect(readout).to_contain_text("UTC")
    expect(retention.get_by_role("button", name="Run now…")).to_be_enabled()
    expect(retention.get_by_role("button", name="Reset to defaults…")).to_be_enabled()

    classification = _region(page, "Document Classification")
    expect(classification.get_by_text("Configured", exact=True)).to_be_visible()
    expect(_switch(classification, "Enable document classification")).to_be_checked()
    preview = classification.get_by_test_id("classification-categories-preview")
    for label in ("None", "N/A", "Pending"):
        expect(preview.get_by_text(label, exact=True)).to_be_visible()

    archiving = _region(page, "Conversation Archiving")
    expect(_switch(archiving, "Archive deleted conversations")).to_be_checked()
    expect(archiving.get_by_text(re.compile("Retention follows this setting too"))).to_be_visible()

    # The group is fully described, so the pointer to the classic page is gone.
    expect(page.get_by_text(re.compile("need more than a switch"))).to_have_count(0)


def test_switching_a_type_on_reveals_defaults_and_reschedules_on_save(lifecycle):
    # A week out: a stale schedule the rule can never produce, so only rescheduling on
    # save can replace it.
    stale_next_run = (
        datetime.fromisoformat(lifecycle.settings["retention_policy_next_run"]) + timedelta(days=7)
    ).isoformat()
    lifecycle.settings["retention_policy_next_run"] = stale_next_run
    lifecycle.open_data_lifecycle()
    page = lifecycle.page
    retention = _region(page, "Retention Policy")

    _toggle(retention, "Public workspaces", True)
    public_conversations = page.locator("#admin-field-default_retention_conversation_public")
    expect(public_conversations).to_be_visible()
    public_conversations.select_option("30")
    # A switched-on type moves the next run, and the readout says so before saving.
    expect(retention.get_by_test_id("retention-schedule-readout")).to_contain_text("once you save")
    expect(retention.get_by_role("button", name="Run now…")).to_be_disabled()
    expect(retention.get_by_text(re.compile("Save or discard your changes first"))).to_have_count(2)

    before_save = datetime.now(timezone.utc)
    _save(page)
    after_save = datetime.now(timezone.utc)
    assert lifecycle.patches[-1] == {
        "enable_retention_policy_public": True,
        "default_retention_conversation_public": "30",
    }
    next_run = lifecycle.settings["retention_policy_next_run"]
    assert next_run != stale_next_run, "Saving a type must reschedule the next run."
    assert next_run in {
        lifecycle.fields.compute_retention_next_run(2, before_save),
        lifecycle.fields.compute_retention_next_run(2, after_save),
    }
    expect(retention.get_by_test_id("retention-schedule-readout")).not_to_contain_text("once you save")
    expect(retention.get_by_role("button", name="Run now…")).to_be_enabled()


def test_the_run_hour_saves_as_a_number(lifecycle):
    lifecycle.open_data_lifecycle()
    page = lifecycle.page
    retention = _region(page, "Retention Policy")

    retention.get_by_label("Daily run time", exact=True).select_option("5")
    expect(retention.get_by_test_id("retention-schedule-readout")).to_contain_text("once you save")
    _save(page)
    assert lifecycle.patches[-1] == {"retention_policy_execution_hour": 5}
    assert lifecycle.settings["retention_policy_execution_hour"] == 5
    assert lifecycle.settings["retention_policy_next_run"].endswith("T05:00:00+00:00")


def test_run_now_offers_only_saved_types_and_reports_results(lifecycle):
    lifecycle.open_data_lifecycle()
    page = lifecycle.page
    retention = _region(page, "Retention Policy")

    retention.get_by_role("button", name="Run now…").click()
    review = page.get_by_role("region", name="Review before running", exact=True)
    expect(review).to_be_visible()
    expect(review.get_by_role("heading", name="Review before running")).to_be_focused()
    expect(_switch(review, "Public workspaces")).to_be_disabled()
    expect(review.get_by_text(re.compile("Retention is off for this type"))).to_be_visible()
    expect(review.get_by_text(re.compile("conversations deleted after 90 days, documents deleted after 365 days"))).to_be_visible()
    expect(review.get_by_text(re.compile("copied to the archive first"))).to_be_visible()
    confirm = review.get_by_role("button", name="Run retention now")
    expect(confirm).to_be_disabled()

    _switch(review, "Personal workspaces").check()
    _switch(review, "Group workspaces").check()
    lifecycle.capture("run-review", ARTIFACTS)
    confirm.click()

    results = page.get_by_role("region", name="Retention finished", exact=True)
    expect(results).to_be_visible()
    expect(results).to_contain_text("Removed 5 conversations and 2 documents.")
    expect(results.get_by_role("row", name=re.compile("Personal workspaces"))).to_contain_text("3 users")
    expect(results.get_by_role("row", name=re.compile("Group workspaces"))).to_contain_text("1 group")
    assert lifecycle.executions == [{"scopes": ["personal", "group"]}]
    # The run's new last run reaches the schedule beside it.
    expect(retention.get_by_test_id("retention-schedule-readout")).to_contain_text("just now")
    assert lifecycle.schedule_reads >= 1

    results.get_by_role("button", name="Done").click()
    expect(retention.get_by_role("button", name="Run now…")).to_be_focused()


def test_operations_are_held_while_their_settings_are_unsaved(lifecycle):
    lifecycle.open_data_lifecycle()
    page = lifecycle.page
    retention = _region(page, "Retention Policy")
    run = retention.get_by_role("button", name="Run now…")
    reset = retention.get_by_role("button", name="Reset to defaults…")

    page.locator("#admin-field-default_retention_document_group").select_option("30")
    expect(run).to_be_disabled()
    expect(reset).to_be_disabled()
    page.get_by_role("button", name="Discard", exact=True).click()
    expect(run).to_be_enabled()
    expect(reset).to_be_enabled()

    # Archiving changes what a run does to conversations, but not what a reset applies.
    _toggle(_region(page, "Conversation Archiving"), "Archive deleted conversations", False)
    expect(run).to_be_disabled()
    expect(reset).to_be_enabled()
    page.get_by_role("button", name="Discard", exact=True).click()
    assert lifecycle.executions == [] and lifecycle.force_pushes == []
    assert lifecycle.patches == []


def test_reset_to_defaults_reviews_the_saved_defaults_and_reports_counts(lifecycle):
    lifecycle.open_data_lifecycle()
    page = lifecycle.page
    retention = _region(page, "Retention Policy")

    retention.get_by_role("button", name="Reset to defaults…").click()
    review = page.get_by_role("region", name="Review before resetting", exact=True)
    expect(review.get_by_text(re.compile("Will follow: conversations deleted after 90 days"))).to_be_visible()
    expect(review.get_by_text(re.compile("cannot be undone"))).to_be_visible()
    review.get_by_role("button", name="Cancel").click()
    expect(review).to_have_count(0)
    expect(retention.get_by_role("button", name="Reset to defaults…")).to_be_focused()
    assert lifecycle.force_pushes == []

    retention.get_by_role("button", name="Reset to defaults…").click()
    review = page.get_by_role("region", name="Review before resetting", exact=True)
    _switch(review, "Group workspaces").check()
    review.get_by_role("button", name="Reset to defaults").click()
    done = page.get_by_role("region", name="Defaults applied", exact=True)
    expect(done).to_contain_text("Reset 2 retention policies to follow the organization defaults.")
    expect(done).to_contain_text("2 groups")
    assert lifecycle.force_pushes == [{"scopes": ["group"]}]


@pytest.mark.parametrize("status,expected", [
    (500, "Check the application logs"),
    (504, "It may still be running"),
])
def test_a_failed_run_explains_itself_without_server_exception_text(lifecycle, status, expected):
    lifecycle.execute_status = status
    lifecycle.open_data_lifecycle()
    page = lifecycle.page

    _region(page, "Retention Policy").get_by_role("button", name="Run now…").click()
    review = page.get_by_role("region", name="Review before running", exact=True)
    _switch(review, "Personal workspaces").check()
    review.get_by_role("button", name="Run retention now").click()

    failed = page.get_by_role("region", name="Retention did not report back", exact=True)
    expect(failed.get_by_role("alert")).to_contain_text(expected)
    expect(page.get_by_text(re.compile("cosmos-secret-detail"))).to_have_count(0)
    assert "cosmos-secret-detail" in SERVER_EXCEPTION_TEXT


def test_categories_are_edited_validated_and_saved_in_order(lifecycle):
    lifecycle.open_data_lifecycle()
    page = lifecycle.page
    editor = page.get_by_test_id("classification-categories-editor")

    editor.get_by_role("button", name="Add category").click()
    expect(editor.get_by_text("Give this category a label.")).to_be_visible()
    editor.get_by_label("Category 4 label").fill("pending")
    expect(editor.get_by_text(re.compile("Same label as category 3"))).to_be_visible()

    # The server refuses the duplicate and says which categories collide.
    _save_attempt = page.get_by_role("button", name="Save changes", exact=True)
    _save_attempt.click()
    expect(editor.get_by_role("alert")).to_contain_text("Categories 3 and 4")

    editor.get_by_label("Category 4 label").fill("Restricted")
    editor.get_by_label("Category 4 colour hex value").fill("#AA0000")
    editor.get_by_role("button", name="Move category 4 up").click()
    expect(editor.get_by_label("Category 3 label")).to_have_value("Restricted")
    expect(page.get_by_test_id("classification-categories-preview").get_by_text("Restricted")).to_be_visible()

    _save(page)
    assert lifecycle.patches[-1] == {
        "document_classification_categories": [
            {"label": "None", "color": "#808080"},
            {"label": "N/A", "color": "#808080"},
            {"label": "Restricted", "color": "#AA0000"},
            {"label": "Pending", "color": "#0000FF"},
        ]
    }
    # Saved as normalized by the server.
    assert lifecycle.settings["document_classification_categories"][2] == {
        "label": "Restricted", "color": "#aa0000",
    }
    expect(editor.get_by_label("Category 3 colour hex value")).to_have_value("#aa0000")

    # Switching classification off hides the editor, and on with no categories reads as
    # needing configuration.
    for _ in range(4):
        editor.get_by_role("button", name="Remove category 1").click()
    expect(editor.get_by_text(re.compile("No categories yet"))).to_be_visible()
    expect(_region(page, "Document Classification").get_by_text("Needs configuration", exact=True)).to_be_visible()


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width,font_size", [(1440, "m"), (390, "xl")])
def test_data_lifecycle_cards_fit_and_read_in_both_themes(lifecycle, theme, width, font_size):
    lifecycle.open_data_lifecycle(theme=theme, width=width, font_size=font_size)
    page = lifecycle.page
    _region(page, "Retention Policy").get_by_role("button", name="Run now…").click()
    expect(page.get_by_role("region", name="Review before running", exact=True)).to_be_visible()

    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for region in page.locator(".admin-settings-distinct").all():
        overflow = region.evaluate("element => element.scrollWidth - element.clientWidth")
        assert overflow <= 1, f"A Data Lifecycle card overflows by {overflow}px at {width}px/{font_size}"
    lifecycle.capture(f"data-lifecycle-{theme}-{width}-{font_size}", ARTIFACTS)
