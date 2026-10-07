# test_v2_admin_backup_recovery.py
"""
Browser coverage for V2 Admin Settings > Backup & Recovery.
Version: 0.261.274
Implemented in: 0.261.274

The category used to render "No settings match". It now draws one card per navigation
section over the classic data-management API. These tests run the built SPA against an
in-memory copy of that API (``fixtures/v2_admin_data_management.py``) and check the
contracts that matter to an administrator: every card renders, backup settings join the
page's Save bar and save as the whole document the classic page sends, actions that run
against saved settings save first, destructive actions demand their typed confirmations,
history filters and continuation tokens stay server-backed, responsive workbenches do not
overflow, keyboard list navigation works, and leaving the page with unsaved work asks first.
No live settings are written.
"""

import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_data_management import (  # noqa: E402
    BACKUP_RECOVERY_SECTIONS,
    EDITABLE_KEYS,
    REDACTED,
    DataManagementFixture,
    backup_row,
)
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
    if width == 390:
        dm.add_job("migration-wide", operation="migration", status="completed", can_retry=False, can_cancel=False)
    dm.open_backup_recovery(width=width)
    page = dm.page
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for test_id in (
        "dm-readiness", "dm-backup-runs", "dm-schedule", "dm-storage", "dm-encryption",
        "dm-migration", "dm-backup-inventory", "dm-cosmos-editor", "dm-jobs",
    ):
        assert_no_horizontal_overflow(page.get_by_test_id(test_id), test_id, width)
    if width == 390:
        inventory = section(page, "backup-inventory")
        inventory.get_by_role("list", name="Backup inventory").get_by_role("button").first.click()
        assert_no_horizontal_overflow(inventory, "selected backup detail", width)
        inventory.get_by_role("button", name="Restore…").click()
        assert_no_horizontal_overflow(page.get_by_role("dialog", name="Restore backup"), "restore dialog", width)
        page.get_by_role("dialog", name="Restore backup").get_by_role("button", name="Cancel").click()
        jobs = section(page, "jobs")
        jobs.get_by_role("list", name="Jobs").get_by_role("button").first.click()
        job_detail = jobs.get_by_test_id("dm-job-detail")
        assert_top_visible(job_detail, "job detail")
        assert_no_horizontal_overflow(job_detail, "job detail", width)
    dm.capture(f"responsive-{width}", ARTIFACTS)


def section(page, section_id):
    card = page.locator(f"#data-management-{section_id}-section")
    card.scroll_into_view_if_needed()
    return card


def writes_to(dm, *paths):
    """The ordered writes that hit any of the given API paths."""
    return [write for write in dm.writes if write[1] in paths]


def assert_no_horizontal_overflow(locator, label, width):
    locator.scroll_into_view_if_needed()
    overflow = locator.evaluate("element => element.scrollWidth - element.clientWidth")
    assert overflow <= 1, f"{label} overflows by {overflow}px at {width}px"


def assert_top_visible(locator, label):
    box = locator.bounding_box()
    assert box, f"{label} has no bounding box"
    viewport_height = locator.page.evaluate("window.innerHeight")
    assert 0 <= box["y"] <= viewport_height - 1, f"{label} top is outside the viewport: {box}"


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


def test_inventory_summary_tiles_filter_with_server_queries(dm):
    dm.open_backup_recovery()
    page = dm.page
    inventory = section(page, "backup-inventory")
    inventory.get_by_role("button", name=re.compile("^Full backups")).click()
    expect(inventory.get_by_role("list", name="Backup inventory").get_by_role("button").first).to_be_visible()
    full_query = dm.requests_to("GET", r"/backups")[-1]["query"]
    assert full_query["backup_type"] == ["full"]
    assert full_query["status"] == ["available"]

    inventory.get_by_role("button", name=re.compile("^Partial backups")).click()
    expect(inventory.get_by_role("list", name="Backup inventory").get_by_role("button").first).to_be_visible()
    partial_query = dm.requests_to("GET", r"/backups")[-1]["query"]
    assert partial_query["backup_type"] == ["partial"]

    inventory.get_by_role("button", name=re.compile("^Available backups")).click()
    expect(inventory.get_by_role("list", name="Backup inventory").get_by_role("button").first).to_be_visible()
    available_query = dm.requests_to("GET", r"/backups")[-1]["query"]
    assert "backup_type" not in available_query
    assert available_query["status"] == ["available"]


def test_inventory_invalid_created_range_blocks_fetch(dm):
    dm.open_backup_recovery()
    page = dm.page
    inventory = section(page, "backup-inventory")
    # The list loads once the card is on screen; count only after that load has landed.
    expect(inventory.get_by_role("list", name="Backup inventory").get_by_role("button").first).to_be_visible()
    before = len(dm.requests_to("GET", r"/backups"))
    inventory.get_by_label("Created from").fill("2026-09-10")
    inventory.get_by_label("Created through").fill("2026-09-01")
    expect(inventory.get_by_role("alert")).to_contain_text("end date must be on or after the start date")
    page.wait_for_timeout(400)
    assert len(dm.requests_to("GET", r"/backups")) == before


def test_inventory_pages_with_continuation_tokens(dm):
    dm.backups = [
        backup_row(f"{index:08d}-1111-4111-8111-111111111111", "full" if index % 2 else "partial")
        for index in range(1, 31)
    ]
    dm.open_backup_recovery()
    page = dm.page
    inventory = section(page, "backup-inventory")
    expect(inventory.get_by_role("button", name="Next")).to_be_enabled()
    inventory.get_by_role("button", name="Next").click()
    expect(inventory.get_by_text("Page 2")).to_be_visible()
    assert dm.requests_to("GET", r"/backups")[-1]["query"]["continuation_token"] == ["25"]
    inventory.get_by_role("button", name="Previous").click()
    expect(inventory.get_by_text("Page 1")).to_be_visible()
    assert "continuation_token" not in dm.requests_to("GET", r"/backups")[-1]["query"]


def test_inventory_empty_second_page_steps_back_after_delete(dm):
    dm.backups = [
        backup_row(f"{index:08d}-1111-4111-8111-111111111111", "full")
        for index in range(1, 27)
    ]
    dm.open_backup_recovery()
    page = dm.page
    inventory = section(page, "backup-inventory")
    inventory.get_by_role("button", name="Next").click()
    expect(inventory.get_by_text("Page 2")).to_be_visible()
    inventory.get_by_role("list", name="Backup inventory").get_by_role("button").first.click()
    inventory.get_by_role("button", name="Delete…").click()
    page.get_by_role("dialog", name="Delete backup?").get_by_role("button", name="Delete backup").click()
    expect(inventory.get_by_text("Page 1")).to_be_visible()
    expect(inventory.get_by_role("list", name="Backup inventory").get_by_role("button")).to_have_count(25)


def test_deleting_a_backup_refreshes_and_clears_selection(dm):
    dm.open_backup_recovery()
    page = dm.page
    inventory = section(page, "backup-inventory")
    first_id = dm.backups[0]["id"]
    inventory.get_by_role("list", name="Backup inventory").get_by_role("button").first.click()
    expect(inventory).to_contain_text(first_id)
    inventory.get_by_role("button", name="Delete…").click()
    confirm = page.get_by_role("dialog", name="Delete backup?")
    confirm.get_by_role("button", name="Delete backup").click()
    expect(confirm).to_have_count(0)
    expect(inventory.get_by_text("No backup selected")).to_be_visible()
    assert dm.requests_to("DELETE", rf"/backups/{first_id}") or dm.requests_to("DELETE", r"/backups/.*")
    assert first_id not in [backup["id"] for backup in dm.backups]
    assert len(dm.requests_to("GET", r"/backups")) >= 2


def test_deleting_backup_clears_matching_selected_job_detail(dm):
    backup_id = dm.backups[0]["id"]
    dm.add_job(backup_id, status="completed", can_retry=False, can_cancel=False)
    dm.open_backup_recovery()
    page = dm.page
    jobs = section(page, "jobs")
    jobs.get_by_role("list", name="Jobs").get_by_role("button").first.click()
    expect(jobs.get_by_test_id("dm-job-detail")).to_contain_text(backup_id)

    inventory = section(page, "backup-inventory")
    inventory.get_by_role("list", name="Backup inventory").get_by_role("button").first.click()
    inventory.get_by_role("button", name="Delete…").click()
    page.get_by_role("dialog", name="Delete backup?").get_by_role("button", name="Delete backup").click()
    jobs.scroll_into_view_if_needed()
    expect(jobs.get_by_text("Select a job")).to_be_visible()


def test_restore_destination_setup_opens_migration_target_step(dm):
    dm.dm_settings.update({
        "target_cosmos_endpoint": "",
        "target_ai_search_endpoint": "",
        "target_enhanced_citations_storage_blob_endpoint": "",
    })
    dm.open_backup_recovery()
    page = dm.page
    inventory = section(page, "backup-inventory")
    inventory.get_by_role("list", name="Backup inventory").get_by_role("button").first.click()
    inventory.get_by_role("button", name="Restore…").click()
    dialog = page.get_by_role("dialog", name="Restore backup")
    expect(dialog.get_by_role("button", name="Run review")).to_be_disabled()
    dialog.get_by_role("button", name=re.compile("Set up the destination")).click()
    expect(dialog).to_have_count(0)
    migration = section(page, "migration")
    expect(migration.get_by_role("heading", name="Connect the destination")).to_be_visible()


def test_restore_review_requires_destinations_only_for_selected_surfaces(dm):
    dm.dm_settings.update({
        "target_cosmos_endpoint": "",
        "target_ai_search_endpoint": "https://destination.search.windows.net",
        "target_enhanced_citations_storage_blob_endpoint": "",
    })
    dm.open_backup_recovery()
    page = dm.page
    inventory = section(page, "backup-inventory")
    inventory.get_by_role("list", name="Backup inventory").get_by_role("button").first.click()
    inventory.get_by_role("button", name="Restore…").click()
    dialog = page.get_by_role("dialog", name="Restore backup")

    expect(dialog.get_by_role("button", name="Run review")).to_be_disabled()
    expect(dialog).to_contain_text("Cosmos DB and Enhanced Citation files are missing a destination")

    dialog.get_by_role("checkbox", name="Cosmos DB").uncheck()
    expect(dialog.get_by_role("button", name="Run review")).to_be_disabled()
    expect(dialog).to_contain_text("Enhanced Citation files is missing a destination")

    dialog.get_by_role("checkbox", name="Enhanced Citation files").uncheck()
    expect(dialog.get_by_role("button", name="Run review")).to_be_enabled()
    dialog.get_by_role("button", name="Run review").click()
    expect(dialog.get_by_text("Backup manifest integrity")).to_be_visible()
    plan = dm.requests_to("POST", r"/restore/review")[-1]["body"]["restore_plan"]
    assert plan["include_cosmos"] is False
    assert plan["include_ai_search"] is True
    assert plan["include_source_blobs"] is False


def test_restore_review_allows_ai_search_only_with_blank_cosmos_destination(dm):
    dm.dm_settings.update({
        "target_cosmos_endpoint": "",
        "target_ai_search_endpoint": "https://destination.search.windows.net",
        "target_enhanced_citations_storage_blob_endpoint": "",
    })
    dm.open_backup_recovery()
    page = dm.page
    inventory = section(page, "backup-inventory")
    inventory.get_by_role("list", name="Backup inventory").get_by_role("button").first.click()
    inventory.get_by_role("button", name="Restore…").click()
    dialog = page.get_by_role("dialog", name="Restore backup")
    dialog.get_by_role("checkbox", name="Cosmos DB").uncheck()
    dialog.get_by_role("checkbox", name="Enhanced Citation files").uncheck()
    expect(dialog.get_by_role("button", name="Run review")).to_be_enabled()
    dialog.get_by_role("button", name="Run review").click()
    expect(dialog.get_by_text("Backup manifest integrity")).to_be_visible()
    assert dm.requests_to("POST", r"/restore/review")[-1]["body"]["restore_plan"]["include_cosmos"] is False


def test_restore_dialog_create_only_copy_matches_collision_contract(dm):
    dm.open_backup_recovery()
    page = dm.page
    inventory = section(page, "backup-inventory")
    inventory.get_by_role("list", name="Backup inventory").get_by_role("button").first.click()
    inventory.get_by_role("button", name="Restore…").click()
    dialog = page.get_by_role("dialog", name="Restore backup")
    expect(dialog).to_contain_text(
        "Create only blocks the review when destination Cosmos DB containers or AI Search indexes already hold data."
    )
    expect(dialog).to_contain_text("existing source files are skipped as collisions")
    expect(dialog.get_by_text("skipped and reported as collisions")).to_have_count(0)


def test_restore_review_blockers_keep_queue_disabled(dm):
    dm.restore_review = {
        "ready": False,
        "blocker_count": 1,
        "warning_count": 0,
        "checks": [{
            "id": "destination",
            "label": "Destination write check",
            "status": "block",
            "message": "Destination Cosmos DB cannot be written.",
        }],
    }
    dm.open_backup_recovery()
    page = dm.page
    inventory = section(page, "backup-inventory")
    inventory.get_by_role("list", name="Backup inventory").get_by_role("button").first.click()
    inventory.get_by_role("button", name="Restore…").click()
    dialog = page.get_by_role("dialog", name="Restore backup")
    dialog.get_by_role("button", name="Run review").click()
    expect(dialog.get_by_text("Destination write check")).to_be_visible()
    expect(dialog.get_by_role("button", name="Queue restore")).to_be_disabled()


def test_restore_review_saves_pending_backup_settings_first(dm):
    dm.open_backup_recovery()
    page = dm.page
    section(page, "schedule").get_by_text("Scheduled backups", exact=True).click()
    inventory = section(page, "backup-inventory")
    inventory.get_by_role("list", name="Backup inventory").get_by_role("button").first.click()
    inventory.get_by_role("button", name="Restore…").click()
    page.get_by_role("dialog", name="Restore backup").get_by_role("button", name="Run review").click()
    expect(page.get_by_role("dialog", name="Restore backup").get_by_text("Backup manifest integrity")).to_be_visible()
    order = [write[1].rsplit("/", 1)[-1] for write in dm.writes]
    assert order[:2] == ["settings", "review"], order
    expect(save_bar(page)).to_have_count(0)


def test_restore_queue_500_warns_the_job_may_have_started(dm):
    dm.queue_error = (500, {"success": False, "error": "Executor unavailable."})
    dm.open_backup_recovery()
    page = dm.page
    inventory = section(page, "backup-inventory")
    inventory.get_by_role("list", name="Backup inventory").get_by_role("button").first.click()
    inventory.get_by_role("button", name="Restore…").click()
    dialog = page.get_by_role("dialog", name="Restore backup")
    dialog.get_by_role("button", name="Run review").click()
    expect(dialog.get_by_text("Backup manifest integrity")).to_be_visible()
    dialog.get_by_role("checkbox", name=re.compile("I reviewed the destination")).check()
    dialog.get_by_role("button", name="Queue restore").click()
    expect(dialog.get_by_text("may have been queued")).to_be_visible()
    dm.errors[:] = [error for error in dm.errors if "status of 500" not in error]


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


def test_job_filters_map_to_history_query_params(dm):
    dm.add_job("migration-done", operation="migration", status="completed", scheduled=True,
               created_at="2026-09-03T09:00:00+00:00", can_retry=False)
    dm.add_job("backup-failed", operation="backup", status="failed", scheduled=False,
               created_at="2026-09-01T09:00:00+00:00")
    dm.open_backup_recovery()
    page = dm.page
    jobs = section(page, "jobs")
    jobs.get_by_label("Operation").select_option("migration")
    jobs.get_by_label("Status").select_option("completed")
    jobs.get_by_label("Run type").select_option("scheduled")
    jobs.get_by_label("Rows per page").select_option("10")
    jobs.get_by_label("Created from").fill("2026-09-02")
    jobs.get_by_label("Created through").fill("2026-09-04")
    expect(jobs.get_by_role("list", name="Jobs").get_by_text("Migration", exact=True)).to_be_visible()
    query = dm.requests_to("GET", r"/jobs")[-1]["query"]
    assert query["operation"] == ["migration"]
    assert query["status"] == ["completed"]
    assert query["scheduled"] == ["scheduled"]
    assert query["page_size"] == ["10"]
    assert query["created_from"] == ["2026-09-02"]
    assert query["created_to"] == ["2026-09-04"]


def test_job_invalid_created_range_blocks_fetch(dm):
    dm.add_job("backup-older")
    dm.open_backup_recovery()
    page = dm.page
    jobs = section(page, "jobs")
    # The list loads once the card is on screen; count only after that load has landed.
    expect(jobs.get_by_role("list", name="Jobs").get_by_role("button").first).to_be_visible()
    before = len(dm.requests_to("GET", r"/jobs"))
    jobs.get_by_label("Created from").fill("2026-09-10")
    jobs.get_by_label("Created through").fill("2026-09-01")
    expect(jobs.get_by_role("alert")).to_contain_text("end date must be on or after the start date")
    page.wait_for_timeout(400)
    assert len(dm.requests_to("GET", r"/jobs")) == before


def test_jobs_page_with_continuation_tokens(dm):
    for index in range(1, 31):
        dm.add_job(f"backup-page-{index:02d}", status="completed", can_retry=False,
                   created_at=f"2026-09-{index:02d}T09:00:00+00:00")
    dm.open_backup_recovery()
    page = dm.page
    jobs = section(page, "jobs")
    expect(jobs.get_by_role("button", name="Next")).to_be_enabled()
    jobs.get_by_role("button", name="Next").click()
    expect(jobs.get_by_text("Page 2")).to_be_visible()
    assert dm.requests_to("GET", r"/jobs")[-1]["query"]["continuation_token"] == ["25"]
    jobs.get_by_role("button", name="Previous").click()
    expect(jobs.get_by_text("Page 1")).to_be_visible()
    assert "continuation_token" not in dm.requests_to("GET", r"/jobs")[-1]["query"]


def test_jobs_empty_second_page_steps_back_on_refresh(dm):
    for index in range(1, 27):
        dm.add_job(f"backup-page-{index:02d}", status="completed", can_retry=False,
                   created_at=f"2026-09-{index:02d}T09:00:00+00:00")
    dm.open_backup_recovery()
    page = dm.page
    jobs = section(page, "jobs")
    jobs.get_by_role("button", name="Next").click()
    expect(jobs.get_by_text("Page 2")).to_be_visible()
    dm.jobs.pop("backup-page-01")
    jobs.get_by_role("button", name="Refresh").click()
    expect(jobs.get_by_text("Page 1")).to_be_visible()
    expect(jobs.get_by_role("list", name="Jobs").get_by_role("button")).to_have_count(25)


def test_finished_job_detail_does_not_fetch_loop(dm):
    dm.add_job("idle-job", status="completed", can_retry=False, can_cancel=False)
    dm.open_backup_recovery()
    page = dm.page
    jobs = section(page, "jobs")
    jobs.get_by_role("list", name="Jobs").get_by_role("button").first.click()
    expect(jobs.get_by_test_id("dm-job-detail")).to_contain_text("idle-job")
    page.wait_for_timeout(3_200)
    detail_requests = dm.requests_to("GET", r"/jobs/idle-job")
    assert len(detail_requests) <= 2, detail_requests


def test_migration_job_detail_exposes_manifest_download_links(dm):
    dm.add_job("migration-artifacts", operation="migration", status="completed", can_retry=False, can_cancel=False)
    dm.open_backup_recovery()
    page = dm.page
    jobs = section(page, "jobs")
    jobs.get_by_role("list", name="Jobs").get_by_role("button").first.click()
    detail = jobs.get_by_test_id("dm-job-detail")
    expect(detail).to_contain_text("migration-artifacts")
    manifest = detail.get_by_role("link", name="Download manifest")
    failures = detail.get_by_role("link", name="Download failures")
    expect(manifest).to_have_attribute("href", re.compile(r"/api/admin/data-management/jobs/migration-artifacts/migration-manifest$"))
    expect(failures).to_have_attribute("href", re.compile(r"/api/admin/data-management/jobs/migration-artifacts/migration-manifest\?statuses=failed%2Cmissing%2Ccollision$"))


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


def test_cosmos_document_detail_scrolls_into_view_on_mobile(dm):
    dm.open_backup_recovery(width=390)
    page = dm.page
    editor = unlock_cosmos(page)
    expect(editor.get_by_text("Cosmos DB editor unlocked for this page session.")).to_be_visible()
    editor.get_by_label("Container").select_option("user_settings")
    editor.get_by_role("button", name="Run query").click()
    editor.get_by_test_id("dm-cosmos-editor-results").get_by_role("button").first.click()
    detail = editor.get_by_role("textbox", name="Cosmos DB document JSON")
    expect(detail).to_have_value(re.compile('"name": "Settings"'))
    assert_top_visible(detail, "Cosmos document detail")


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


def test_migration_destination_tests_post_inline_settings_without_saving(dm):
    dm.open_backup_recovery()
    page = dm.page
    migration = section(page, "migration")
    migration.locator("[data-dm-key='target_cosmos_endpoint']").get_by_label("Endpoint").fill("https://inline.documents.azure.com:443/")
    migration.get_by_role("button", name="Test Cosmos DB").click()
    expect(migration.get_by_text("planned containers verified")).to_be_visible()
    cosmos_body = dm.requests_to("POST", r"/target/cosmos/test")[-1]["body"]
    assert cosmos_body["settings"]["target_cosmos_endpoint"] == "https://inline.documents.azure.com:443/"

    migration.locator("[data-dm-key='target_ai_search_endpoint']").get_by_label("Endpoint").fill("https://inline.search.windows.net")
    migration.get_by_role("button", name="Test AI Search").click()
    expect(migration.get_by_text("expected indexes exist")).to_be_visible()
    search_body = dm.requests_to("POST", r"/target/search/test")[-1]["body"]
    assert search_body["settings"]["target_ai_search_endpoint"] == "https://inline.search.windows.net"

    migration.locator("[data-dm-key='target_enhanced_citations_storage_blob_endpoint']").get_by_label("Blob endpoint").fill("https://inline.blob.core.windows.net")
    migration.get_by_role("button", name="Test storage").click()
    expect(migration.get_by_text("containers ready")).to_be_visible()
    storage_body = dm.requests_to("POST", r"/target/enhanced-citation-storage/test")[-1]["body"]
    assert storage_body["settings"]["target_enhanced_citations_storage_blob_endpoint"] == "https://inline.blob.core.windows.net"
    assert not dm.requests_to("PUT", r"/settings")
    expect(save_bar(page)).to_contain_text("3 unsaved changes")


def test_enabling_destination_ru_boost_reveals_management_fields(dm):
    dm.open_backup_recovery()
    page = dm.page
    migration = section(page, "migration")
    migration.get_by_role("button", name="Continue to Scope").click()
    migration.get_by_role("radio", name=re.compile("^All")).first.check()
    migration.get_by_role("button", name="Continue to What moves").click()
    expect(migration.get_by_label("Subscription ID")).to_have_count(0)
    migration.get_by_text("Destination RU Boost for this migration", exact=True).click()
    expect(migration.get_by_label("Subscription ID")).to_be_visible()
    expect(migration.get_by_label("Resource group")).to_be_visible()


def test_invalid_previous_migration_guid_blocks_options_continue(dm):
    dm.open_backup_recovery()
    page = dm.page
    migration = section(page, "migration")
    migration.get_by_role("button", name="Continue to Scope").click()
    migration.get_by_role("radio", name=re.compile("^All")).first.check()
    migration.get_by_role("button", name="Continue to What moves").click()
    migration.get_by_role("radio", name=re.compile("^Catch up changed items")).check()
    migration.get_by_label("Previous migration job ID").fill("not-a-guid")
    expect(migration.get_by_text("must be a GUID")).to_be_visible()
    expect(migration.get_by_role("button", name="Continue to Review")).to_be_disabled()


def test_migration_all_scope_counts_once_and_uses_count_in_header(dm):
    dm.open_backup_recovery()
    page = dm.page
    migration = section(page, "migration")
    migration.get_by_role("button", name="Continue to Scope").click()
    migration.get_by_role("radio", name=re.compile("^All")).check()
    expect(migration.get_by_role("tab").filter(has_text="Users").filter(has_text="30")).to_be_visible()
    expect(migration.get_by_text("30 users included.")).to_be_visible()
    expect(migration.get_by_text("30 principal scopes selected")).to_be_visible()

    count_requests = dm.requests_to("GET", r"/migration/catalog/users")
    assert len(count_requests) == 1, count_requests
    assert count_requests[0]["query"] == {
        "search": [""],
        "continuation_token": [""],
        "page_size": ["1"],
    }


def test_migration_all_scope_count_failure_waits_for_retry(dm):
    dm.catalog_count_failures = 1
    dm.open_backup_recovery()
    page = dm.page
    migration = section(page, "migration")
    migration.get_by_role("button", name="Continue to Scope").click()
    migration.get_by_role("radio", name=re.compile("^All")).check()
    expect(migration.get_by_role("tab").filter(has_text="Users").filter(has_text="Unavailable")).to_be_visible()
    expect(migration.get_by_text("The users count could not be loaded. The server review still counts them.")).to_be_visible()
    expect(migration.get_by_text("Some counts are unavailable")).to_be_visible()
    page.wait_for_timeout(2_100)
    count_requests = dm.requests_to("GET", r"/migration/catalog/users")
    assert len(count_requests) == 1, count_requests

    migration.get_by_role("button", name="Retry count").click()
    expect(migration.get_by_text("30 users included.")).to_be_visible()
    assert len(dm.requests_to("GET", r"/migration/catalog/users")) == 2
    dm.errors[:] = [error for error in dm.errors if "status of 503" not in error]


def test_migration_zero_all_count_blocks_scope_step(dm):
    dm.open_backup_recovery()
    page = dm.page
    migration = section(page, "migration")
    migration.get_by_role("button", name="Continue to Scope").click()
    migration.get_by_role("tab", name=re.compile("^Public workspaces")).click()
    migration.get_by_role("radio", name=re.compile("^All")).check()
    expect(migration.get_by_text("0 public workspaces included.")).to_be_visible()
    expect(migration.get_by_text("Choose at least one user, group, or public workspace before review.")).to_be_visible()
    expect(migration.get_by_role("button", name="Continue to What moves")).to_be_disabled()


def test_migration_catalog_empty_state_changes_after_search(dm):
    dm.open_backup_recovery()
    page = dm.page
    migration = section(page, "migration")
    migration.get_by_role("button", name="Continue to Scope").click()
    migration.get_by_role("radio", name=re.compile("^Selected")).check()
    expect(migration.get_by_text("Search the server catalog.")).to_be_visible()
    migration.get_by_label(re.compile("Search users")).fill("does-not-exist")
    migration.get_by_role("button", name="Search", exact=True).click()
    expect(migration.get_by_text("No matches found.")).to_be_visible()


def test_migration_confirm_uses_server_normalized_review_summary(dm):
    dm.open_backup_recovery()
    page = dm.page
    migration = section(page, "migration")
    migration.get_by_role("button", name="Continue to Scope").click()
    migration.get_by_role("radio", name=re.compile("^Selected")).check()
    migration.get_by_text("Include their documents", exact=True).click()
    migration.get_by_role("button", name="Search", exact=True).click()
    migration.get_by_role("checkbox", name=re.compile(r"^User 1 user1@")).check()
    migration.get_by_role("tab", name=re.compile("^Groups")).click()
    migration.get_by_role("radio", name=re.compile("^All")).check()
    migration.get_by_text("Include their documents", exact=True).click()
    expect(migration.get_by_text("1 groups included.")).to_be_visible()
    migration.get_by_role("button", name="Continue to What moves").click()
    migration.get_by_role("radio", name=re.compile("^Make destination match source")).check()
    migration.get_by_role("checkbox", name=re.compile("Other writers to the destination AI Search are frozen")).check()
    migration.get_by_role("button", name="Continue to Review").click()
    migration.get_by_role("button", name="Run preflight review").click()
    expect(migration.get_by_text("Users: Selected (1, 1 documents, documents included)")).to_be_visible()
    expect(migration.get_by_text("Groups: All (1, 4 documents, documents included)")).to_be_visible()
    migration.get_by_role("button", name="Continue to Confirm").click()

    plan = migration.get_by_text("Server-normalized plan").locator("xpath=ancestor::div[contains(@class, 'rounded-xl')][1]")
    expect(plan).to_contain_text("Ready")
    expect(plan).to_contain_text("Principal scopes")
    expect(plan).to_contain_text("2")
    expect(plan).to_contain_text("Included documents")
    expect(plan).to_contain_text("5")
    expect(plan).to_contain_text("Synchronization mode")
    expect(plan).to_contain_text("Make destination match source")
    expect(plan).to_contain_text("Creates / updates")
    expect(plan).to_contain_text("3 / 2")
    expect(plan).to_contain_text("Deletes")
    expect(plan).to_contain_text("1")
    expect(plan).to_contain_text("Conflicts")
    expect(plan).to_contain_text("4")


def test_migration_validate_cosmos_access_uses_data_copy(dm):
    dm.open_backup_recovery()
    page = dm.page
    migration = section(page, "migration")
    migration.get_by_role("button", name="Continue to Scope").click()
    migration.get_by_role("radio", name=re.compile("^Selected")).check()
    migration.get_by_role("button", name="Search", exact=True).click()
    migration.get_by_role("checkbox", name=re.compile(r"^User 1 user1@")).check()
    migration.get_by_role("button", name="Continue to What moves").click()
    migration.get_by_role("checkbox", name=re.compile("Other writers to the destination AI Search are frozen")).check()
    migration.get_by_role("button", name="Continue to Review").click()
    migration.get_by_role("button", name="Validate Cosmos access").click()
    expect(migration.get_by_text(
        "Cosmos data-copy access is ready. 7 planned Cosmos containers can be read and written. RU Boost permissions are tested separately."
    )).to_be_visible()


def test_migration_catalog_paging_keeps_selections_across_pages_and_tabs(dm):
    dm.catalog["groups"] = [
        {"id": f"group-{index}", "label": f"Group {index}", "description": f"group-{index}", "document_count": index}
        for index in range(1, 28)
    ]
    dm.catalog["users"] = [
        {"id": f"user-{index}", "label": f"User {index}", "description": f"user{index}@contoso.com", "document_count": index}
        for index in range(1, 61)
    ]
    dm.open_backup_recovery()
    page = dm.page
    migration = section(page, "migration")
    migration.get_by_role("button", name="Continue to Scope").click()
    migration.get_by_role("radio", name=re.compile("^Selected")).check()
    migration.get_by_role("button", name="Search", exact=True).click()
    migration.get_by_role("checkbox", name=re.compile(r"^User 1 user1@")).check()
    migration.get_by_role("button", name="Next").click()
    expect(migration.get_by_text("User 26")).to_be_visible()
    assert dm.requests_to("GET", r"/migration/catalog/users")[-1]["query"]["continuation_token"] == ["25"]
    migration.get_by_role("checkbox", name=re.compile(r"^User 26 user26@")).check()
    migration.get_by_role("button", name="Previous").click()
    expect(migration.get_by_role("checkbox", name=re.compile(r"^User 1 user1@"))).to_be_checked()
    migration.get_by_role("tab", name=re.compile("^Groups")).click()
    migration.get_by_role("radio", name=re.compile("^Selected")).check()
    migration.get_by_role("button", name="Search", exact=True).click()
    migration.get_by_role("checkbox", name=re.compile("^Group 1 group-1")).check()
    migration.get_by_role("tab", name=re.compile("^Users")).click()
    expect(migration.get_by_text("Selected (2)")).to_be_visible()
    expect(migration.get_by_role("checkbox", name=re.compile(r"^User 1 user1@"))).to_be_checked()


def test_migration_review_blocker_locks_confirm_and_go_to_step_opens_fix(dm):
    dm.migration_review = {
        "ready": False,
        "blocker_count": 1,
        "warning_count": 0,
        "checks": [{
            "id": "target",
            "label": "Destination configuration",
            "status": "block",
            "summary": "Destination Cosmos DB is not writable.",
            "workflow_step": "target",
        }],
    }
    dm.open_backup_recovery()
    page = dm.page
    migration = section(page, "migration")
    migration.get_by_role("button", name="Continue to Scope").click()
    migration.get_by_role("radio", name=re.compile("^Selected")).check()
    migration.get_by_role("button", name="Search", exact=True).click()
    migration.get_by_role("checkbox", name=re.compile(r"^User 1 user1@")).check()
    migration.get_by_role("button", name="Continue to What moves").click()
    migration.get_by_role("checkbox", name=re.compile("Other writers to the destination AI Search are frozen")).check()
    migration.get_by_role("button", name="Continue to Review").click()
    migration.get_by_role("button", name="Run preflight review").click()
    expect(migration.get_by_text("Destination configuration")).to_be_visible()
    expect(migration.get_by_role("button", name="Continue to Confirm")).to_be_disabled()
    migration.get_by_role("button", name="Go to Destination").click()
    expect(migration.get_by_role("heading", name="Connect the destination")).to_be_visible()


def test_running_migration_job_reattaches_progress_when_card_opens(dm):
    dm.add_job("migration-live", operation="migration", status="running", can_retry=False, can_cancel=True,
               progress={"current_step": "copy", "percent_complete": 25, "completed_steps": 1, "total_steps": 4})
    dm.progress_polls["migration-live"] = -1000
    dm.open_backup_recovery()
    page = dm.page
    migration = section(page, "migration")
    expect(migration.get_by_role("heading", name="Monitor migration progress")).to_be_visible()
    expect(migration.get_by_text("migration-live")).to_be_visible()


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


def test_storage_test_posts_unsaved_values_without_saving_settings(dm):
    dm.open_backup_recovery()
    page = dm.page
    storage = section(page, "storage")
    storage.get_by_label("Blob endpoint").fill("https://unsaved.blob.core.windows.net")
    storage.get_by_label("Container").fill("unsaved-container")
    expect(save_bar(page)).to_contain_text("2 unsaved changes")
    storage.get_by_role("button", name="Test storage").click()
    expect(storage.get_by_text("Connected. Container unsaved-container was found.")).to_be_visible()
    body = dm.requests_to("POST", r"/storage/test")[-1]["body"]
    assert body["settings"]["backup_storage_blob_endpoint"] == "https://unsaved.blob.core.windows.net"
    assert body["settings"]["backup_storage_container_name"] == "unsaved-container"
    assert not dm.requests_to("PUT", r"/settings")
    expect(save_bar(page)).to_contain_text("2 unsaved changes")


def test_generating_and_replacing_key_without_pending_changes_only_posts_key(dm):
    dm.dm_settings.update({"encryption_key_reference": "", "encryption_key_storage": ""})
    dm.open_backup_recovery()
    page = dm.page
    encryption = section(page, "encryption")
    encryption.get_by_role("button", name="Generate key").click()
    expect(encryption.get_by_text("Generated (hidden)")).to_be_visible()
    assert dm.writes == [("POST", "/api/admin/data-management/encryption-key")]

    dm.writes.clear()
    encryption.get_by_role("button", name="Replace key").click()
    confirm = page.get_by_role("dialog", name="Replace backup encryption key?")
    expect(confirm).to_be_visible()
    confirm.get_by_role("button", name="Replace key").click()
    expect(confirm).to_have_count(0)
    assert dm.writes == [("POST", "/api/admin/data-management/encryption-key")]


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


def test_start_here_open_storage_and_settings_search_keywords(dm):
    dm.open_backup_recovery(width=1600)
    page = dm.page
    readiness = section(page, "readiness")
    storage_item = readiness.get_by_role("listitem").filter(has_text="Backup storage")
    storage_item.get_by_role("button", name="Open Backup storage").click()
    expect(section(page, "storage")).to_be_in_viewport()

    search = page.get_by_role("searchbox", name="Search settings")
    search.fill("retention")
    expect(region(page, "Schedule")).to_be_visible()
    expect(region(page, "Cosmos Editor")).to_have_count(0)
    search.fill("cosmos editor")
    expect(region(page, "Cosmos Editor")).to_be_visible()
    expect(region(page, "Schedule")).to_have_count(0)


def test_minor_backup_recovery_copy_updates_are_present(dm):
    dm.open_backup_recovery()
    page = dm.page
    expect(section(page, "schedule")).to_contain_text("The newest successful full backup is kept by default")
    expect(section(page, "storage")).to_contain_text(
        "dedicated-storage check compares against the saved Enhanced Citations settings"
    )
    section(page, "backup-inventory").get_by_role("button", name="Run retention cleanup").click()
    expect(page.get_by_role("dialog", name="Run retention cleanup?")).to_contain_text(
        "The newest successful full backup is kept by default"
    )
    page.get_by_role("dialog", name="Run retention cleanup?").get_by_role("button", name="Cancel").click()
    migration = section(page, "migration")
    migration.get_by_role("button", name="Continue to Scope").click()
    migration.get_by_role("radio", name=re.compile("^All")).check()
    expect(migration.get_by_text("30 users included.")).to_be_visible()
    migration.get_by_role("button", name="Continue to What moves").click()
    migration.get_by_role("button", name="About RU Boost").click()
    expect(page.get_by_role("dialog", name="RU Boost permissions")).to_contain_text(
        "Use Test RU Boost before a cutover window"
    )
    page.get_by_role("dialog", name="RU Boost permissions").get_by_text("Close", exact=True).click()


def test_on_this_page_index_shows_backup_recovery_statuses(dm):
    dm.open_backup_recovery(width=1920)
    page = dm.page
    index = page.get_by_role("navigation", name="On this page")
    storage = index.get_by_role("link", name=re.compile("^Storage"))
    schedule = index.get_by_role("link", name=re.compile("^Schedule"))
    expect(storage).to_contain_text("Storage")
    expect(storage.locator(".sr-only")).to_have_text("Configured")
    expect(schedule.locator(".sr-only")).to_have_text("Off")


def test_inventory_and_job_rows_support_arrow_key_focus(dm):
    for index in range(1, 4):
        dm.backups.append(backup_row(f"33333333-3333-4333-8333-33333333333{index}", "full"))
        dm.add_job(f"keyboard-job-{index}", status="completed", can_retry=False)
    dm.open_backup_recovery()
    page = dm.page

    inventory = section(page, "backup-inventory")
    backup_rows = inventory.get_by_role("list", name="Backup inventory").get_by_role("button")
    backup_rows.nth(0).focus()
    page.keyboard.press("ArrowDown")
    expect(backup_rows.nth(1)).to_be_focused()
    page.keyboard.press("ArrowUp")
    expect(backup_rows.nth(0)).to_be_focused()

    jobs = section(page, "jobs")
    job_rows = jobs.get_by_role("list", name="Jobs").get_by_role("button")
    job_rows.nth(0).focus()
    page.keyboard.press("ArrowDown")
    expect(job_rows.nth(1)).to_be_focused()
    page.keyboard.press("ArrowUp")
    expect(job_rows.nth(0)).to_be_focused()
