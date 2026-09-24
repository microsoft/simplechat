# test_v2_group_prompts.py
"""
Production-SPA coverage for the native scope-aware V2 group prompts workbench.
Version: 0.261.152
Implemented in: 0.261.136

Exercises the real workbench, adapter and chat resolution against closed synthetic
HTTP. The fixture only serves the immutable `/api/groups/<id>/prompts` family, never
personal prompt writes, so a group scope that leaked into personal reads would fail.
Group prompts carry no per-user favourite and no Shared place: a manager writes with
conditional etags, an ordinary member gets a read-only workbench, and an inline
`prompt_actions` gate hides edit and delete per prompt exactly as the server dictates.
"""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.group_prompts import (
    GroupPromptsFixture, connect_options, group_prompts_ui,  # noqa: F401
)


pytestmark = pytest.mark.ui
SCREENSHOTS = Path(os.environ.get(
    "SIMPLECHAT_UI_SCREENSHOTS", str(Path(__file__).parent / "artifacts" / "group-prompts"),
))
REBASE_NOTICE = (
    "Someone else changed this while you were editing. Their changes are loaded; "
    "your edits are kept. Review, then save."
)
REBASE_DELETED_NOTICE = "This item was deleted. Copy anything you need, then close."


def search_box(ui):
    return ui.page.get_by_role("searchbox", name="Search prompts", exact=True)


def row(ui, name):
    return ui.page.get_by_role("button", name=re.compile(rf"^{re.escape(name)}"))


def details(ui):
    return ui.page.get_by_role("main")


def open_prompts(ui, group="group-a", **options):
    ui.open(f"/groups/{group}/prompts", **options)
    expect(search_box(ui)).to_be_visible()


def last_list(ui, group="group-a"):
    return [
        entry for entry in ui.requests
        if entry.path == f"/api/groups/{group}/prompts" and entry.method == "GET"
    ][-1]


@pytest.mark.parametrize("theme,width,height", [
    ("light", 1440, 900), ("dark", 1440, 900), ("light", 390, 844), ("dark", 390, 844),
])
def test_prompt_layout(group_prompts_ui, theme, width, height):
    ui = group_prompts_ui
    open_prompts(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("button", name="New prompt", exact=True)).to_be_visible()
    ui.assert_no_overflow()
    box = search_box(ui).bounding_box()
    assert box and box["width"] >= 40
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    label = f'{"mobile" if width < 768 else "desktop"}-{theme}'
    ui.page.screenshot(path=str(SCREENSHOTS / f"{label}.png"), full_page=True)


def test_list_reads_whole_group_set(group_prompts_ui):
    ui = group_prompts_ui
    open_prompts(ui)
    query = last_list(ui).query
    assert query["page"] == ["1"]
    assert query["page_size"] == ["500"]
    expect(row(ui, "Weekly status")).to_be_visible()
    expect(row(ui, "Withheld template")).to_be_visible()
    # Every returned prompt identifies the requested group; none advertise a Shared place.
    listed = [
        entry for entry in ui.responses
        if entry[0].endswith("/api/groups/group-a/prompts?page=1&page_size=500")
    ][-1][1]["prompts"]
    assert listed and all(prompt["group_id"] == "group-a" for prompt in listed)


def test_manager_can_create(group_prompts_ui):
    ui = group_prompts_ui
    open_prompts(ui)
    ui.page.get_by_role("button", name="New prompt", exact=True).click()
    dialog = ui.page.get_by_role("dialog", name="New prompt", exact=True)
    expect(dialog).to_be_visible()
    ui.page.locator("#prompt-name").fill("Fresh prompt")
    ui.page.locator("#prompt-content").fill("A brand new shared wording.")
    ui.page.get_by_role("button", name="Create prompt", exact=True).click()
    expect(row(ui, "Fresh prompt")).to_be_visible()
    created = [
        entry for entry in ui.writes
        if entry.method == "POST" and entry.path == "/api/groups/group-a/prompts"
    ][-1]
    assert created.body == {
        "name": "Fresh prompt", "content": "A brand new shared wording.", "description": "",
    }
    assert "is_favorite" not in created.body
    # A write refreshes the chat catalog so the new prompt is usable in chat without a reload.
    assert any(
        entry.path == "/api/v2/bootstrap" for entry in ui.requests
        if entry.method == "GET"
    )


def test_manager_can_edit_with_conditional_write(group_prompts_ui):
    ui = group_prompts_ui
    open_prompts(ui)
    row(ui, "Weekly status").click()
    details(ui).get_by_role("button", name="Edit", exact=True).click()
    dialog = ui.page.get_by_role("dialog", name="Edit prompt", exact=True)
    expect(dialog).to_be_visible()
    ui.page.locator("#prompt-name").fill("Weekly status revised")
    ui.page.get_by_role("button", name="Save changes", exact=True).click()
    expect(row(ui, "Weekly status revised")).to_be_visible()
    patched = [
        entry for entry in ui.writes
        if entry.method == "PATCH" and entry.path == "/api/groups/group-a/prompts/weekly-status"
    ][-1]
    assert patched.body.get("expected_etag") == '"etag-weekly-status-0"'
    assert "is_favorite" not in patched.body


def test_manager_can_delete_with_expected_etag(group_prompts_ui):
    ui = group_prompts_ui
    open_prompts(ui)
    row(ui, "Weekly status").click()
    details(ui).get_by_role("button", name="Delete", exact=True).click()
    details(ui).get_by_role("button", name="Delete", exact=True).click()
    expect(row(ui, "Weekly status")).to_have_count(0)
    deleted = [
        entry for entry in ui.writes
        if entry.method == "DELETE" and entry.path == "/api/groups/group-a/prompts/weekly-status"
    ][-1]
    assert isinstance(deleted.body, dict)
    assert deleted.body.get("expected_etag") == '"etag-weekly-status-0"'


def test_manager_can_duplicate(group_prompts_ui):
    ui = group_prompts_ui
    open_prompts(ui)
    row(ui, "Weekly status").click()
    details(ui).get_by_role("button", name="Duplicate", exact=True).click()
    expect(row(ui, "Weekly status (copy)")).to_be_visible()
    created = [
        entry for entry in ui.writes
        if entry.method == "POST" and entry.path == "/api/groups/group-a/prompts"
    ][-1]
    assert created.body["name"] == "Weekly status (copy)"
    assert "is_favorite" not in created.body


def test_inline_actions_gate_edit_and_delete(group_prompts_ui):
    ui = group_prompts_ui
    open_prompts(ui)
    # Positive control: a prompt whose inline actions include edit and delete shows both.
    row(ui, "Weekly status").click()
    expect(details(ui).get_by_role("button", name="Edit", exact=True)).to_be_visible()
    expect(details(ui).get_by_role("button", name="Delete", exact=True)).to_be_visible()
    # The withheld prompt advertises an empty inline array while the workspace still offers the
    # operations, so its edit and delete affordances must be hidden even though create is allowed.
    row(ui, "Withheld template").click()
    expect(details(ui).get_by_role("button", name="Edit", exact=True)).to_have_count(0)
    expect(details(ui).get_by_role("button", name="Delete", exact=True)).to_have_count(0)
    expect(details(ui).get_by_role("link", name="Use in chat", exact=True)).to_be_visible()


def test_member_workbench_is_read_only(group_prompts_ui):
    ui = group_prompts_ui
    open_prompts(ui, group="group-b")
    expect(ui.page.get_by_role("button", name="New prompt", exact=True)).to_have_count(0)
    row(ui, "Team charter").click()
    for label in ("Edit", "Duplicate", "Delete"):
        expect(details(ui).get_by_role("button", name=label, exact=True)).to_have_count(0)
    expect(details(ui).get_by_role("link", name="Use in chat", exact=True)).to_be_visible()
    expect(details(ui).get_by_role("button", name="Copy", exact=True)).to_be_visible()


def test_status_locked_workbench_is_read_only(group_prompts_ui):
    ui = group_prompts_ui
    ui.set_prompt_policy("group-a", role="Owner", status="upload_disabled")
    open_prompts(ui)
    expect(ui.page.get_by_role("button", name="New prompt", exact=True)).to_have_count(0)
    row(ui, "Weekly status").click()
    expect(details(ui).get_by_role("button", name="Edit", exact=True)).to_have_count(0)
    expect(details(ui).get_by_role("button", name="Delete", exact=True)).to_have_count(0)


def test_favorites_are_hidden_in_group_scope(group_prompts_ui):
    ui = group_prompts_ui
    open_prompts(ui)
    expect(ui.page.get_by_role("button", name=re.compile(r"favou?rite", re.IGNORECASE))).to_have_count(0)
    row(ui, "Weekly status").click()
    expect(details(ui).get_by_role("button", name=re.compile(r"favou?rite", re.IGNORECASE))).to_have_count(0)


def test_conditional_conflict_keeps_draft_open(group_prompts_ui):
    ui = group_prompts_ui
    open_prompts(ui)
    row(ui, "Weekly status").click()
    # Another member edits the shared prompt after this one opened it: the stored etag moves on.
    ui.touch_prompt("group-a", "weekly-status")
    details(ui).get_by_role("button", name="Edit", exact=True).click()
    dialog = ui.page.get_by_role("dialog", name="Edit prompt", exact=True)
    ui.page.locator("#prompt-name").fill("Weekly status stale")
    ui.page.get_by_role("button", name="Save changes", exact=True).click()
    # The draft stays open with its edit intact and a refresh is offered rather than lost.
    expect(dialog).to_be_visible()
    expect(ui.page.locator("#prompt-name")).to_have_value("Weekly status stale")
    refresh = ui.page.get_by_role("button", name="Refresh", exact=True)
    expect(refresh).to_be_visible()
    refresh.click()
    ui.page.get_by_role("button", name="Save changes", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(row(ui, "Weekly status stale")).to_be_visible()
    conflicts = [
        entry for entry in ui.responses
        if entry[0].endswith("/api/groups/group-a/prompts/weekly-status")
        and isinstance(entry[1], dict) and entry[1].get("error") == "prompt_changed"
    ]
    assert conflicts, "The stale-etag edit should have produced a 409 prompt_changed."


def test_conflict_refresh_rebases_concurrent_description_and_local_name(group_prompts_ui):
    """Refreshing a stale prompt edit adopts untouched fields and keeps the local name."""
    ui = group_prompts_ui
    open_prompts(ui)
    row(ui, "Weekly status").click()
    details(ui).get_by_role("button", name="Edit", exact=True).click()
    dialog = ui.page.get_by_role("dialog", name="Edit prompt", exact=True)
    record = ui.record("group-a", "weekly-status")
    record["description"] = "Concurrent description from another manager."
    ui.touch_prompt("group-a", "weekly-status")
    ui.page.locator("#prompt-name").fill("Weekly status local draft")
    with ui.page.expect_response(
        lambda response: response.request.method == "PATCH"
        and response.url.endswith("/api/groups/group-a/prompts/weekly-status")
    ) as conflict:
        ui.page.get_by_role("button", name="Save changes", exact=True).click()
    assert conflict.value.status == 409
    with ui.page.expect_response(
        lambda response: response.request.method == "GET"
        and "/api/groups/group-a/prompts" in response.url
    ):
        ui.page.get_by_role("button", name="Refresh", exact=True).click()
    expect(ui.page.locator("#prompt-description")).to_have_value("Concurrent description from another manager.")
    expect(ui.page.locator("#prompt-name")).to_have_value("Weekly status local draft")
    expect(ui.page.get_by_text(REBASE_NOTICE, exact=True)).to_be_visible()
    with ui.page.expect_response(
        lambda response: response.request.method == "PATCH"
        and response.url.endswith("/api/groups/group-a/prompts/weekly-status")
    ) as saved:
        ui.page.get_by_role("button", name="Save changes", exact=True).click()
    assert saved.value.ok
    expect(dialog).to_have_count(0)
    saved_record = ui.record("group-a", "weekly-status")
    assert saved_record["description"] == "Concurrent description from another manager."
    assert saved_record["name"] == "Weekly status local draft"


def test_conflict_refresh_reports_name_conflict_and_keeps_local_name(group_prompts_ui):
    """Refreshing reports a same-field prompt conflict and keeps the user's name."""
    ui = group_prompts_ui
    open_prompts(ui)
    row(ui, "Weekly status").click()
    details(ui).get_by_role("button", name="Edit", exact=True).click()
    record = ui.record("group-a", "weekly-status")
    record["name"] = "Weekly status concurrent rename"
    ui.touch_prompt("group-a", "weekly-status")
    ui.page.locator("#prompt-name").fill("Weekly status local rename")
    with ui.page.expect_response(
        lambda response: response.request.method == "PATCH"
        and response.url.endswith("/api/groups/group-a/prompts/weekly-status")
    ) as conflict:
        ui.page.get_by_role("button", name="Save changes", exact=True).click()
    assert conflict.value.status == 409
    with ui.page.expect_response(
        lambda response: response.request.method == "GET"
        and "/api/groups/group-a/prompts" in response.url
    ):
        ui.page.get_by_role("button", name="Refresh", exact=True).click()
    expect(ui.page.get_by_text(f"{REBASE_NOTICE} You and someone else both changed: Name. Your values are shown.", exact=True)).to_be_visible()
    expect(ui.page.locator("#prompt-name")).to_have_value("Weekly status local rename")
    with ui.page.expect_response(
        lambda response: response.request.method == "PATCH"
        and response.url.endswith("/api/groups/group-a/prompts/weekly-status")
    ) as saved:
        ui.page.get_by_role("button", name="Save changes", exact=True).click()
    assert saved.value.ok
    assert ui.record("group-a", "weekly-status")["name"] == "Weekly status local rename"


def test_conflict_refresh_reports_deleted_prompt_without_resaving(group_prompts_ui):
    """Refreshing after a stale save shows that the prompt was deleted and does not save again."""
    ui = group_prompts_ui
    open_prompts(ui)
    row(ui, "Weekly status").click()
    details(ui).get_by_role("button", name="Edit", exact=True).click()
    ui.drop_prompt_for_conflict("group-a", "weekly-status")
    ui.page.locator("#prompt-name").fill("Weekly status deleted local")
    with ui.page.expect_response(
        lambda response: response.request.method == "PATCH"
        and response.url.endswith("/api/groups/group-a/prompts/weekly-status")
    ) as conflict:
        ui.page.get_by_role("button", name="Save changes", exact=True).click()
    assert conflict.value.status == 409
    with ui.page.expect_response(
        lambda response: response.request.method == "GET"
        and "/api/groups/group-a/prompts" in response.url
    ):
        ui.page.get_by_role("button", name="Refresh", exact=True).click()
    expect(ui.page.get_by_text(REBASE_DELETED_NOTICE, exact=True)).to_be_visible()
    assert [entry for entry in ui.writes if entry.method == "PATCH" and entry.path == "/api/groups/group-a/prompts/weekly-status"]
    assert not any(row["id"] == "weekly-status" for row in ui.prompts["group-a"])


def test_scoped_prompt_link_attaches_in_chat(group_prompts_ui):
    ui = group_prompts_ui
    ui.open("/chat?prompt=weekly-status&prompt_scope=group&prompt_scope_id=group-a")
    expect(ui.page.get_by_role("button", name="Remove Weekly status", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Research group", exact=True)).to_be_visible()


def test_legacy_prompt_link_still_resolves_by_id(group_prompts_ui):
    ui = group_prompts_ui
    ui.open("/chat?prompt=weekly-status")
    expect(ui.page.get_by_role("button", name="Remove Weekly status", exact=True)).to_be_visible()


def test_stale_scoped_link_names_the_group(group_prompts_ui):
    ui = group_prompts_ui
    ui.open("/chat?prompt=does-not-exist&prompt_scope=group&prompt_scope_id=group-a")
    expect(
        ui.page.get_by_text("That prompt is no longer available in Research group.", exact=True)
    ).to_be_visible()
    expect(ui.page.get_by_role("button", name=re.compile(r"^Remove "))).to_have_count(0)
