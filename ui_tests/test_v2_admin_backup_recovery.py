# test_v2_admin_backup_recovery.py
"""
Browser coverage for V2 Admin Settings > Backup & Recovery.
Version: 0.261.260
Implemented in: 0.261.260

The category used to render "No settings match". It now draws one card per navigation
section over the classic data-management API. These tests run the built SPA against an
in-memory copy of that API (``fixtures/v2_admin_data_management.py``) and check the
contracts that matter to an administrator: every card renders, backup settings join the
page's Save bar and save as the whole document the classic page sends, actions that run
against saved settings save first, destructive actions demand their typed confirmations,
and leaving the page with unsaved work asks first. No live settings are written.
"""

import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_data_management import BACKUP_RECOVERY_SECTIONS, EDITABLE_KEYS, REDACTED, DataManagementFixture  # noqa: E402
from v2_admin_settings import connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui

ARTIFACTS = "v2_admin_backup_recovery"
CARD_TITLES = ("Start Here", "Backup", "Schedule", "Storage", "Encryption", "Migration",
               "Backup Inventory & Restore", "Cosmos Editor", "Jobs")


@pytest.fixture
def dm(page):
    fixture = DataManagementFixture(page)
    page.emulate_media(reduced_motion="reduce")
    yield fixture
    fixture.assert_clean()


def region(page, name):
    return page.get_by_role("region", name=name, exact=True)


def save_bar(page):
    return page.get_by_role("status").filter(has_text=re.compile(r"unsaved change"))


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_backup_recovery_card_renders(dm, theme):
    dm.open_backup_recovery(theme=theme)
    page = dm.page
    for title in CARD_TITLES:
        expect(region(page, title)).to_be_visible()
    expect(page.get_by_text(re.compile("No settings match"))).to_have_count(0)
    expect(page.get_by_test_id("dm-readiness")).to_contain_text("Backup storage")
    expect(save_bar(page)).to_have_count(0)
    dm.capture(f"backup-recovery-{theme}", ARTIFACTS)


def test_backup_settings_join_the_save_bar(dm):
    dm.open_backup_recovery()
    page = dm.page
    schedule = region(page, "Schedule")
    schedule.get_by_text("Scheduled backups", exact=True).click()
    expect(save_bar(page)).to_contain_text("1 unsaved change")

    retention = schedule.get_by_role("spinbutton").first
    retention.fill("2")
    schedule.get_by_role("combobox", name=re.compile("unit", re.I)).select_option("weeks")
    expect(save_bar(page)).to_contain_text("3 unsaved changes")

    page.get_by_role("button", name="Save changes").click()
    expect(save_bar(page)).to_have_count(0)

    saves = dm.requests_to("PUT", r"/settings")
    assert len(saves) == 1, saves
    body = saves[0]["body"]
    assert set(body) == set(EDITABLE_KEYS), sorted(set(EDITABLE_KEYS) ^ set(body))
    assert body["enabled"] is True
    assert body["retention_value"] == 2 and body["retention_unit"] == "weeks" and body["retention_days"] == 14
    assert body["target_cosmos_key"] == REDACTED, "an untouched secret must round-trip as the placeholder"
    assert not dm.patches, "backup settings are not main settings"


def test_discard_drops_backup_edits(dm):
    dm.open_backup_recovery()
    page = dm.page
    region(page, "Schedule").get_by_text("Scheduled backups", exact=True).click()
    expect(save_bar(page)).to_contain_text("1 unsaved change")
    page.get_by_role("button", name="Discard").click()
    expect(save_bar(page)).to_have_count(0)
    assert not dm.requests_to("PUT", r"/settings")


def test_a_rejected_backup_save_keeps_the_edit(dm):
    dm.open_backup_recovery()
    page = dm.page
    dm.reject_next_dm_save = "Backup storage must use a dedicated Azure Storage account."
    region(page, "Schedule").get_by_text("Scheduled backups", exact=True).click()
    page.get_by_role("button", name="Save changes").click()
    expect(page.get_by_text("Backup storage must use a dedicated Azure Storage account.").first).to_be_visible()
    expect(save_bar(page)).to_contain_text("1 unsaved change")
    # The browser logs the deliberate 400; nothing else may have failed.
    dm.errors[:] = [error for error in dm.errors if "status of 400" not in error]


def test_queueing_a_backup_saves_pending_settings_first(dm):
    dm.open_backup_recovery()
    page = dm.page
    region(page, "Schedule").get_by_text("Scheduled backups", exact=True).click()
    backup = region(page, "Backup")
    backup.get_by_role("button", name=re.compile("Save and queue full backup")).click()
    expect(backup.get_by_text(re.compile("queued", re.I)).first).to_be_visible()

    order = [(entry["method"], entry["path"]) for entry in dm.dm_requests if entry["method"] in ("PUT", "POST")]
    assert order.index(("PUT", "/settings")) < order.index(("POST", "/jobs")), order
    job = dm.requests_to("POST", r"/jobs")[0]["body"]
    assert job["operation"] == "backup" and job["backup_type"] == "full"
    assert set(job["options"]) == {"include_cosmos", "include_ai_search", "include_source_blobs"}
    expect(save_bar(page)).to_have_count(0)


def test_leaving_with_unsaved_changes_asks_first(dm):
    dm.open_backup_recovery()
    page = dm.page
    region(page, "Schedule").get_by_text("Scheduled backups", exact=True).click()
    page.get_by_role("link", name=re.compile("^Chat", re.I)).first.click()
    dialog = page.get_by_role("dialog", name="Leave Admin settings?")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Stay").click()
    expect(dialog).to_have_count(0)
    expect(save_bar(page)).to_contain_text("1 unsaved change")


@pytest.mark.parametrize("width", [390, 1920])
def test_backup_recovery_never_overflows(dm, width):
    dm.open_backup_recovery(width=width)
    page = dm.page
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for test_id in ("dm-readiness", "dm-backup-runs", "dm-schedule", "dm-storage", "dm-encryption", "dm-migration"):
        card = page.get_by_test_id(test_id)
        card.scroll_into_view_if_needed()
        overflow = card.evaluate("element => element.scrollWidth - element.clientWidth")
        assert overflow <= 1, f"{test_id} overflows by {overflow}px at {width}px"
    dm.capture(f"responsive-{width}", ARTIFACTS)


def section(page, section_id):
    card = page.locator(f"#data-management-{section_id}-section")
    card.scroll_into_view_if_needed()
    return card


def writes_to(dm, *paths):
    """The ordered writes that hit any of the given API paths."""
    return [write for write in dm.writes if write[1] in paths]


def unlock_cosmos(page):
    editor = section(page, "cosmos-editor")
    editor.get_by_role("button", name="Unlock editor").click()
    unlock = page.get_by_role("dialog", name="Unlock Cosmos DB editor")
    expect(unlock.get_by_role("button", name="Unlock", exact=True)).to_be_disabled()
    unlock.get_by_role("checkbox").check()
    unlock.get_by_role("button", name="Unlock", exact=True).click()
    expect(editor.get_by_role("button", name="Lock editor")).to_be_visible()
    return editor


def walk_migration_to_confirm(migration, *, mirror=False):
    migration.get_by_role("button", name="Continue to Scope").click()
    migration.get_by_role("radio", name=re.compile("^Selected")).check()
    migration.get_by_role("button", name="Search", exact=True).click()
    migration.get_by_role("checkbox", name=re.compile(r"^User 1 user1@")).check()
    migration.get_by_role("button", name="Continue to What moves").click()
    if mirror:
        migration.get_by_role("radio", name=re.compile("^Make destination match source")).check()
    migration.get_by_role("checkbox", name=re.compile("Other writers to the destination AI Search are frozen")).check()
    migration.get_by_role("button", name="Continue to Review").click()
    migration.get_by_role("button", name="Run preflight review").click()
    expect(migration.get_by_role("list", name="Review checks").get_by_text("Migration scope")).to_be_visible()
    migration.get_by_role("button", name="Continue to Confirm").click()
    migration.get_by_role("checkbox", name=re.compile("I reviewed the plan")).check()


def test_looking_through_every_card_changes_nothing(dm):
    dm.open_backup_recovery()
    page = dm.page
    for section_id in BACKUP_RECOVERY_SECTIONS["backup-recovery"]:
        card = page.locator(f"#{section_id}")
        card.scroll_into_view_if_needed()
        for summary in card.locator("details > summary").all():
            summary.click()
    page.wait_for_timeout(300)
    expect(save_bar(page)).to_have_count(0)
    assert not dm.writes, dm.writes


def test_restore_needs_a_current_review_an_acknowledgement_and_the_phrase(dm):
    dm.open_backup_recovery()
    page = dm.page
    inventory = section(page, "backup-inventory")
    inventory.get_by_role("list", name="Backup inventory").get_by_role("button").first.click()
    inventory.get_by_role("button", name="Restore…").click()

    dialog = page.get_by_role("dialog", name="Restore backup")
    queue = dialog.get_by_role("button", name="Queue restore")
    expect(queue).to_be_disabled()
    dialog.get_by_role("radio", name=re.compile("^Overwrite existing")).check()
    dialog.get_by_role("button", name="Run review").click()
    expect(dialog.get_by_text("Backup manifest integrity")).to_be_visible()

    review = dm.requests_to("POST", r"/restore/review")[-1]["body"]
    assert review["restore_plan"]["restore_policy"] == "overwrite_existing"
    assert set(review["settings"]) == set(EDITABLE_KEYS)

    dialog.get_by_role("checkbox", name=re.compile("I reviewed the destination")).check()
    expect(queue).to_be_disabled()
    phrase = dialog.get_by_role("textbox")
    phrase.fill("restore with overwrite")
    expect(queue).to_be_disabled()
    phrase.fill("RESTORE WITH OVERWRITE")
    # The phrase is not part of what was reviewed, so typing it keeps the review current.
    expect(dialog.get_by_text("Inputs changed after the review")).to_have_count(0)
    expect(queue).to_be_enabled()
    queue.click()
    expect(dialog).to_have_count(0)

    job = dm.requests_to("POST", r"/jobs")[-1]["body"]
    assert job["operation"] == "restore"
    assert job["options"]["review_authorization_token"] == "restore-token"
    assert job["options"]["review_fingerprint"] == "restore-fingerprint"
    plan = job["options"]["restore_plan"]
    assert plan["source_backup_id"] == dm.backups[0]["id"]
    assert plan["overwrite_confirmed"] is True and plan["overwrite_confirmation_phrase"] == "RESTORE WITH OVERWRITE"
    expect(section(page, "jobs").get_by_test_id("dm-job-detail")).to_contain_text("Restore")


def test_changing_the_restore_policy_makes_the_review_stale(dm):
    dm.open_backup_recovery()
    page = dm.page
    inventory = section(page, "backup-inventory")
    inventory.get_by_role("list", name="Backup inventory").get_by_role("button").first.click()
    inventory.get_by_role("button", name="Restore…").click()
    dialog = page.get_by_role("dialog", name="Restore backup")
    dialog.get_by_role("button", name="Run review").click()
    dialog.get_by_role("checkbox", name=re.compile("I reviewed the destination")).check()
    expect(dialog.get_by_role("button", name="Queue restore")).to_be_enabled()

    dialog.get_by_role("checkbox", name="AI Search").uncheck()
    expect(dialog.get_by_text("Inputs changed after the review. Run it again.")).to_be_visible()
    expect(dialog.get_by_role("button", name="Queue restore")).to_be_disabled()
    dialog.get_by_role("button", name="Cancel").click()

    # Each opening starts again from a clean draft.
    inventory.get_by_role("button", name="Restore…").click()
    dialog = page.get_by_role("dialog", name="Restore backup")
    expect(dialog.get_by_text("No restore review has run yet.")).to_be_visible()
    expect(dialog.get_by_role("checkbox", name="AI Search")).to_be_checked()


def test_retention_cleanup_saves_pending_settings_first(dm):
    dm.open_backup_recovery()
    page = dm.page
    section(page, "schedule").locator("#data-management-retention-value").fill("21")
    expect(save_bar(page)).to_contain_text("unsaved change")
    section(page, "backup-inventory").get_by_role("button", name="Run retention cleanup").click()

    confirm = page.get_by_role("dialog", name="Run retention cleanup?")
    expect(confirm).to_contain_text("(21 days)")
    assert writes_to(dm, "/api/admin/data-management/settings") == [("PUT", "/api/admin/data-management/settings")]
    confirm.get_by_role("button", name="Run cleanup").click()
    expect(page.get_by_text("Retention cleanup result")).to_be_visible()
    order = [write[1].rsplit("/", 1)[-1] for write in dm.writes]
    assert order == ["settings", "cleanup"], order
    expect(save_bar(page)).to_have_count(0)


def test_a_queued_job_is_followed_until_it_finishes(dm):
    dm.open_backup_recovery()
    page = dm.page
    backup = section(page, "backup")
    backup.get_by_role("button", name=re.compile("Queue full backup")).click()
    backup.get_by_role("button", name="View in Job history").click()
    detail = section(page, "jobs").get_by_test_id("dm-job-detail")
    expect(detail).to_contain_text("Full backup")
    # The live line names the finished state once polling has seen it.
    expect(detail.get_by_text(re.compile(r"^Job is completed", re.I))).to_be_visible(timeout=15_000)
    assert dm.progress_polls.get("backup-1", 0) >= 2
    expect(detail.get_by_role("button", name="Cancel")).to_have_count(0)


def test_cancelling_a_running_job_sends_the_reason(dm):
    dm.add_job("backup-7", status="running", can_retry=False, can_cancel=True)
    dm.progress_polls["backup-7"] = -1000
    dm.open_backup_recovery()
    page = dm.page
    jobs = section(page, "jobs")
    jobs.get_by_role("list", name="Jobs").get_by_role("button").first.click()
    jobs.get_by_test_id("dm-job-detail").get_by_role("button", name="Cancel").click()
    confirm = page.get_by_role("dialog", name="Request job cancellation")
    confirm.get_by_role("textbox").fill("Maintenance window")
    confirm.get_by_role("button", name="Request cancellation").click()
    expect(confirm).to_have_count(0)
    cancel = dm.requests_to("POST", r"/jobs/backup-7/cancel")
    assert len(cancel) == 1 and cancel[0]["body"].get("reason") == "Maintenance window", cancel


def test_retrying_a_job_never_saves_settings(dm):
    dm.add_job("backup-9")
    dm.open_backup_recovery()
    page = dm.page
    section(page, "schedule").get_by_text("Scheduled backups", exact=True).click()
    expect(save_bar(page)).to_contain_text("1 unsaved change")

    jobs = section(page, "jobs")
    jobs.get_by_role("list", name="Jobs").get_by_role("button").first.click()
    jobs.get_by_test_id("dm-job-detail").get_by_role("button", name="Retry failures").click()
    expect(page.get_by_text(re.compile("retry queued"))).to_be_visible()
    assert dm.writes == [("POST", "/api/admin/data-management/jobs/backup-9/retry")], dm.writes
    # The pending edit is still pending, not saved behind the administrator's back.
    expect(save_bar(page)).to_contain_text("1 unsaved change")


def test_cosmos_editor_unlocks_queries_and_saves_with_the_phrase(dm):
    dm.open_backup_recovery()
    page = dm.page
    editor = unlock_cosmos(page)

    editor.get_by_label("Container").select_option("user_settings")
    editor.get_by_role("button", name="Run query").click()
    editor.get_by_test_id("dm-cosmos-editor-results").get_by_role("button").first.click()
    json_box = editor.get_by_role("textbox", name="Cosmos DB document JSON")
    expect(json_box).to_have_value(re.compile('"name": "Settings"'))
    json_box.fill(json_box.input_value().replace('"Settings"', '"Repaired"'))
    editor.get_by_role("button", name="Save…").click()

    confirm = page.get_by_role("dialog", name="Confirm Cosmos DB document save")
    save = confirm.get_by_role("button", name="Save document")
    expect(save).to_be_disabled()
    confirm.get_by_role("textbox").fill("I understand this can damage system data")
    save.click()
    expect(confirm).to_have_count(0)
    assert dm.cosmos_documents["doc-1"]["name"] == "Repaired"
    saved = dm.requests_to("PUT", r"/cosmos-editor/document")[-1]["body"]
    assert saved["etag"] == "etag-1" and saved["confirmation_accepted"] is True


def test_a_cosmos_conflict_asks_for_a_reload(dm):
    dm.open_backup_recovery()
    page = dm.page
    editor = unlock_cosmos(page)
    editor.get_by_label("Container").select_option("user_settings")
    editor.get_by_role("button", name="Run query").click()
    editor.get_by_test_id("dm-cosmos-editor-results").get_by_role("button").first.click()
    json_box = editor.get_by_role("textbox", name="Cosmos DB document JSON")
    expect(json_box).to_have_value(re.compile('"name": "Settings"'))
    # Someone else saves the document after it was opened.
    dm.cosmos_documents["doc-1"]["_etag"] = "etag-elsewhere"
    json_box.fill(json_box.input_value().replace('"Settings"', '"Repaired"'))
    editor.get_by_role("button", name="Save…").click()
    confirm = page.get_by_role("dialog", name="Confirm Cosmos DB document save")
    confirm.get_by_role("textbox").fill("I understand this can damage system data")
    confirm.get_by_role("button", name="Save document").click()
    expect(confirm.get_by_text(re.compile("changed after it was opened"))).to_be_visible()
    expect(confirm.get_by_role("button", name="Reload")).to_be_visible()
    assert dm.cosmos_documents["doc-1"]["name"] == "Settings"
    dm.errors[:] = [error for error in dm.errors if "status of 409" not in error]


def test_migration_reviews_then_queues_with_its_authorization(dm):
    dm.open_backup_recovery()
    page = dm.page
    migration = section(page, "migration")
    walk_migration_to_confirm(migration, mirror=True)

    start = migration.get_by_role("button", name="Start migration")
    expect(start).to_be_disabled()
    migration.get_by_role("textbox").fill("MAKE DESTINATION MATCH SOURCE")
    expect(start).to_be_enabled()
    start.click()
    expect(migration.get_by_text("migration-1", exact=True)).to_be_visible()

    review = dm.requests_to("POST", r"/migration/review")[-1]["body"]
    job = dm.requests_to("POST", r"/jobs")[-1]["body"]
    assert job["operation"] == "migration"
    assert job["options"]["review_fingerprint"] == "migration-fingerprint"
    assert job["options"]["review_authorization_token"] == "migration-token"
    plan = job["options"]["migration_plan"]
    assert plan["migration_mode"] == "mirror_with_deletions"
    assert plan["mirror_confirmation"] == "MAKE DESTINATION MATCH SOURCE"
    # The phrase authorizes the run; everything the review covered is sent unchanged.
    assert review["migration_plan"]["mirror_confirmation"] == ""
    assert {key: value for key, value in plan.items() if key != "mirror_confirmation"} == {
        key: value for key, value in review["migration_plan"].items() if key != "mirror_confirmation"
    }


def test_a_stale_migration_review_sends_the_administrator_back(dm):
    dm.queue_error = (409, {"success": False, "error": "Migration inputs changed after preflight review. Run review again before execution.", "workflow_step": "review"})
    dm.open_backup_recovery()
    page = dm.page
    migration = section(page, "migration")
    walk_migration_to_confirm(migration)
    migration.get_by_role("button", name="Start migration").click()
    expect(migration.get_by_role("heading", name="Review migration evidence")).to_be_visible()
    expect(migration.get_by_text(re.compile("Run review again before execution"))).to_be_visible()
    dm.errors[:] = [error for error in dm.errors if "status of 409" not in error]


def test_a_typed_destination_key_does_not_make_the_review_stale(dm):
    dm.open_backup_recovery()
    page = dm.page
    migration = section(page, "migration")
    migration.get_by_label("Account key", exact=True).fill("new-destination-key")
    expect(save_bar(page)).to_contain_text("1 unsaved change")
    walk_migration_to_confirm(migration)

    start = migration.get_by_role("button", name="Save and start migration")
    start.click()
    expect(migration.get_by_text("migration-1", exact=True)).to_be_visible()
    order = [write[1].rsplit("/", 1)[-1] for write in dm.writes]
    assert order == ["review", "settings", "jobs"], order
    saved = dm.requests_to("PUT", r"/settings")[-1]["body"]
    assert saved["target_cosmos_key"] == "new-destination-key"
    expect(save_bar(page)).to_have_count(0)


def test_a_failed_container_list_waits_for_the_administrator(dm):
    dm.cosmos_container_failures = 1
    dm.open_backup_recovery()
    page = dm.page
    editor = unlock_cosmos(page)
    expect(editor.get_by_text("The container list is not loaded.")).to_be_visible()
    page.wait_for_timeout(1_500)
    assert len(dm.requests_to("GET", r"/cosmos-editor/containers")) == 1
    editor.get_by_role("button", name="Load containers").click()
    expect(editor.get_by_label("Container").locator("option[value='user_settings']")).to_have_count(1)
    expect(editor.get_by_text("The container list is not loaded.")).to_have_count(0)
    dm.errors[:] = [error for error in dm.errors if "status of 503" not in error]


def test_editing_a_query_drops_its_next_page(dm):
    dm.open_backup_recovery()
    page = dm.page
    editor = unlock_cosmos(page)
    editor.get_by_label("Container").select_option("user_settings")
    query = editor.get_by_label("SELECT query")
    query.fill("SELECT * FROM c")
    editor.get_by_role("button", name="Run query").click()
    expect(editor.get_by_role("button", name="Next page")).to_be_visible()
    query.fill("SELECT c.id FROM c")
    expect(editor.get_by_role("button", name="Next page")).to_have_count(0)


def test_generating_a_key_waits_for_unsaved_key_vault_settings(page):
    sections = {"security": ("keyvault-section",), **BACKUP_RECOVERY_SECTIONS}
    dm = DataManagementFixture(page, sections=sections)
    page.emulate_media(reduced_motion="reduce")
    dm.open_backup_recovery()
    vault = page.locator("#keyvault-section")
    vault.scroll_into_view_if_needed()
    vault.get_by_text("Vault connection", exact=True).click()
    vault.get_by_text("Store agent and action secrets in Key Vault", exact=True).first.click()
    expect(save_bar(page)).to_contain_text("1 unsaved change")

    section(page, "encryption").get_by_role("button", name="Replace key").click()
    page.get_by_role("dialog", name="Save all changes first?").get_by_role("button", name="Save all and continue").click()
    replace = page.get_by_role("dialog", name="Replace backup encryption key?")
    replace.get_by_role("button", name="Replace key").click()
    expect(replace).to_have_count(0)
    assert dm.writes == [
        ("PATCH", "/api/v2/admin/settings"),
        ("POST", "/api/admin/data-management/encryption-key"),
    ], dm.writes
    expect(save_bar(page)).to_have_count(0)
    dm.assert_clean()


def test_switching_categories_keeps_edits_and_invents_none(page):
    sections = {
        "chat": ("enhanced-citations-section",),
        "security": ("keyvault-section",),
        **BACKUP_RECOVERY_SECTIONS,
    }
    dm = DataManagementFixture(page, sections=sections)
    page.emulate_media(reduced_motion="reduce")
    dm.open_backup_recovery()
    rail = page.get_by_role("complementary", name="Settings categories")

    for label in ("Backup & Recovery", "Chat", "Security", "All settings", "Backup & Recovery"):
        rail.get_by_role("button", name=re.compile(f"^{re.escape(label)}$")).click()
        expect(rail.get_by_role("button", name=re.compile(f"^{re.escape(label)}$"))).to_have_attribute("aria-pressed", "true")
        expect(save_bar(page)).to_have_count(0)

    # A pending backup edit lives in the store, not the card, so hiding the card keeps it.
    section(page, "schedule").get_by_text("Scheduled backups", exact=True).click()
    expect(save_bar(page)).to_contain_text("1 unsaved change")
    rail.get_by_role("button", name=re.compile("^Chat$")).click()
    expect(page.locator("#data-management-schedule-section")).to_have_count(0)
    expect(save_bar(page)).to_contain_text("1 unsaved change")
    rail.get_by_role("button", name=re.compile(f"^{re.escape('Backup & Recovery')}$")).click()
    expect(section(page, "schedule").get_by_role("checkbox", name=re.compile("^Scheduled backups"))).to_be_checked()
    assert not dm.writes, dm.writes
    dm.assert_clean()


def test_backup_storage_waits_for_unsaved_enhanced_citation_settings(page):
    sections = {"chat": ("enhanced-citations-section",), **BACKUP_RECOVERY_SECTIONS}
    dm = DataManagementFixture(page, sections=sections)
    page.emulate_media(reduced_motion="reduce")
    dm.open_backup_recovery()
    citations = page.locator("#enhanced-citations-section")
    citations.scroll_into_view_if_needed()
    citations.get_by_text("Enable Enhanced Citations", exact=True).first.click()
    section(page, "schedule").get_by_text("Scheduled backups", exact=True).click()
    expect(save_bar(page)).to_contain_text("2 unsaved changes")

    section(page, "backup").get_by_role("button", name=re.compile("Save and queue full backup")).click()
    confirm = page.get_by_role("dialog", name="Save all changes first?")
    expect(confirm).to_contain_text("Enhanced Citations storage settings have unsaved changes")
    assert not dm.writes, "nothing is saved until the administrator agrees"
    confirm.get_by_role("button", name="Save all and continue").click()
    expect(section(page, "backup").get_by_text("Full backup queued")).to_be_visible()
    assert dm.writes[:3] == [
        ("PATCH", "/api/v2/admin/settings"),
        ("PUT", "/api/admin/data-management/settings"),
        ("POST", "/api/admin/data-management/jobs"),
    ], dm.writes
    expect(save_bar(page)).to_have_count(0)
    dm.assert_clean()
