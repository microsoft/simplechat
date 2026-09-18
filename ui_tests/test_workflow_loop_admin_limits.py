# test_workflow_loop_admin_limits.py
"""
Source-backed browser tests for Classic/V2 workflow loop admission limits.
Version: 0.261.117
Implemented in: 0.261.117

The actual Classic pane, V2 SPA, field registry and admin patch normalizer run
against intercepted APIs. No live settings, Azure resource, or model is used.
"""

import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

# Isolated application imports are configured by the shared fixture.
from ui_tests.fixtures.workflow_admin_limits import (
    WorkflowAdminLimitsFixture,
    connect_options,  # noqa: F401
)


pytestmark = pytest.mark.ui


@pytest.fixture
def loop_admin_ui(page):
    fixture = WorkflowAdminLimitsFixture(page)
    yield fixture
    fixture.assert_clean()


@pytest.mark.parametrize("configured", [None, 5000])
def test_classic_loop_limit_default_bounds_and_keyboard(loop_admin_ui, configured):
    ui, page = loop_admin_ui, loop_admin_ui.page
    if configured is None:
        ui.settings.pop("workflow_max_loop_items", None)
    else:
        ui.settings["workflow_max_loop_items"] = configured
    ui.open_workflow(classic=True, width=390)
    field = page.get_by_label("Workflow Loop Item Limit", exact=True)
    expect(field).to_have_value(str(configured if configured is not None else 500))
    expect(field).to_have_attribute("type", "number")
    expect(field).to_have_attribute("name", "workflow_max_loop_items")
    expect(field).to_have_attribute("min", "1")
    expect(field).to_have_attribute("max", "5000")
    expect(field).to_have_attribute("step", "1")
    expect(field).to_have_attribute("required", "")
    expect(page.locator("#workflow-max-loop-items-help")).to_contain_text("actual items")
    expect(page.locator("#workflow-max-loop-items-help")).to_contain_text("Active runs")
    expect(page.locator("#workflow-max-loop-items-help")).to_contain_text("never truncated")
    for invalid in ("0", "5001", "1.5", ""):
        field.fill(invalid)
        assert not field.evaluate("element => element.checkValidity()")
    field.fill("1")
    field.focus()
    field.press("ArrowUp")
    expect(field).to_have_value("2")
    assert field.evaluate("element => element.checkValidity()")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert ui.patches == []


def test_v2_loop_limit_registry_mobile_keyboard_and_narrow_patch(loop_admin_ui):
    ui, page = loop_admin_ui, loop_admin_ui.page
    ui.open_workflow(width=390)
    field = page.get_by_label("Workflow Loop Item Limit", exact=True)
    expect(field).to_have_value("500")
    expect(field).to_have_attribute("min", "1")
    expect(field).to_have_attribute("max", "5000")
    expect(field).to_have_attribute("step", "1")
    field.focus()
    field.press("ArrowDown")
    expect(field).to_have_value("499")
    save = page.get_by_role("button", name="Save changes", exact=True)
    save.focus()
    save.press("Enter")
    expect(save).to_have_count(0)
    assert ui.patches == [{"workflow_max_loop_items": 499}]
    assert ui.settings["workflow_max_loop_items"] == 499
    page.reload(wait_until="networkidle")
    expect(field).to_have_value("499")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_v2_invalid_loop_limit_retains_draft_and_existing_policy(loop_admin_ui):
    ui, page = loop_admin_ui, loop_admin_ui.page
    ui.open_workflow()
    field = page.get_by_label("Workflow Loop Item Limit", exact=True)
    field.fill("5001")
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="5,000")).to_be_visible()
    expect(field).to_have_value("5001")
    assert ui.settings["workflow_max_loop_items"] == 500
    page.get_by_role("button", name="Discard", exact=True).click()
    expect(field).to_have_value("500")
    field.fill("5000")
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)
    assert ui.settings["workflow_max_loop_items"] == 5000


def test_v2_unrelated_patch_preserves_an_absent_loop_limit(loop_admin_ui):
    ui, page = loop_admin_ui, loop_admin_ui.page
    ui.settings.pop("workflow_max_loop_items", None)
    ui.open_workflow()
    expect(page.get_by_label("Workflow Loop Item Limit", exact=True)).to_have_value("500")
    page.get_by_label("Workflow Task Limit", exact=True).fill("51")
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)
    assert ui.patches == [{"workflow_max_tasks": 51}]
    assert "workflow_max_loop_items" not in ui.settings
