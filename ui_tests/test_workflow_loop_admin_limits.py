# test_workflow_loop_admin_limits.py
"""
Source-backed browser tests for Classic/V2 For-each and Repeat policy limits.
Version: 0.261.120
Implemented in: 0.261.117

The actual Classic pane, V2 SPA, field registry and admin patch normalizer run
against intercepted APIs. No live settings, Azure resource, or model is used.
Repeat-until coverage was added in 0.261.120.
"""

import sys
from pathlib import Path
from typing import NamedTuple

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


class LimitPolicy(NamedTuple):
    key: str
    label: str
    default: int
    maximum: int
    help_id: str
    help_text: tuple[str, ...]


@pytest.fixture(params=[
    pytest.param(LimitPolicy(
        "workflow_max_loop_items", "Workflow Loop Item Limit", 500, 5000,
        "workflow-max-loop-items-help", ("actual items", "Active runs", "never truncated"),
    ), id="for-each"),
    pytest.param(LimitPolicy(
        "workflow_max_repeat_iterations", "Workflow Repeat Iteration Limit", 25, 1000,
        "workflow-max-repeat-iterations-help",
        ("automatic Repeat until batch", "per-block maximum", "never shortened", "manual continuation", "admitted limit"),
    ), id="repeat-until"),
])
def workflow_limit(request):
    return request.param


@pytest.fixture
def loop_admin_ui(page):
    fixture = WorkflowAdminLimitsFixture(page)
    yield fixture
    fixture.assert_clean()


@pytest.mark.parametrize("configured", ["absent", "maximum"])
def test_classic_workflow_limit_default_bounds_and_keyboard(loop_admin_ui, workflow_limit, configured):
    ui, page = loop_admin_ui, loop_admin_ui.page
    policy = workflow_limit
    if configured == "absent":
        ui.settings.pop(policy.key, None)
    else:
        ui.settings[policy.key] = policy.maximum
    ui.open_workflow(classic=True, width=390)
    field = page.get_by_label(policy.label, exact=True)
    expect(field).to_have_value(str(policy.default if configured == "absent" else policy.maximum))
    expect(field).to_have_attribute("type", "number")
    expect(field).to_have_attribute("name", policy.key)
    expect(field).to_have_attribute("min", "1")
    expect(field).to_have_attribute("max", str(policy.maximum))
    expect(field).to_have_attribute("step", "1")
    expect(field).to_have_attribute("required", "")
    expect(field).to_have_attribute("aria-describedby", policy.help_id)
    for text in policy.help_text:
        expect(page.locator(f"#{policy.help_id}")).to_contain_text(text)
    for invalid in ("0", str(policy.maximum + 1), "1.5", ""):
        field.fill(invalid)
        assert not field.evaluate("element => element.checkValidity()")
    field.fill("1")
    field.focus()
    field.press("ArrowUp")
    expect(field).to_have_value("2")
    assert field.evaluate("element => element.checkValidity()")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert ui.patches == []


def test_v2_workflow_limit_registry_mobile_keyboard_and_narrow_patch(loop_admin_ui, workflow_limit):
    ui, page = loop_admin_ui, loop_admin_ui.page
    policy = workflow_limit
    ui.open_workflow(width=390)
    field = page.get_by_label(policy.label, exact=True)
    expect(field).to_have_value(str(policy.default))
    expect(field).to_have_attribute("min", "1")
    expect(field).to_have_attribute("max", str(policy.maximum))
    expect(field).to_have_attribute("step", "1")
    field.focus()
    field.press("ArrowDown")
    expect(field).to_have_value(str(policy.default - 1))
    save = page.get_by_role("button", name="Save changes", exact=True)
    save.focus()
    save.press("Enter")
    expect(save).to_have_count(0)
    assert ui.patches == [{policy.key: policy.default - 1}]
    assert ui.settings[policy.key] == policy.default - 1
    page.reload(wait_until="networkidle")
    expect(field).to_have_value(str(policy.default - 1))
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_v2_invalid_workflow_limit_retains_draft_and_existing_policy(loop_admin_ui, workflow_limit):
    ui, page = loop_admin_ui, loop_admin_ui.page
    policy = workflow_limit
    ui.open_workflow()
    field = page.get_by_label(policy.label, exact=True)
    field.fill(str(policy.maximum + 1))
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text=f"{policy.maximum:,}")).to_be_visible()
    expect(field).to_have_value(str(policy.maximum + 1))
    assert ui.settings[policy.key] == policy.default
    page.get_by_role("button", name="Discard", exact=True).click()
    expect(field).to_have_value(str(policy.default))
    field.fill(str(policy.maximum))
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)
    assert ui.settings[policy.key] == policy.maximum


def test_v2_unrelated_patch_preserves_an_absent_workflow_limit(loop_admin_ui, workflow_limit):
    ui, page = loop_admin_ui, loop_admin_ui.page
    policy = workflow_limit
    ui.settings.pop(policy.key, None)
    ui.open_workflow()
    expect(page.get_by_label(policy.label, exact=True)).to_have_value(str(policy.default))
    page.get_by_label("Workflow Task Limit", exact=True).fill("51")
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)
    assert ui.patches == [{"workflow_max_tasks": 51}]
    assert policy.key not in ui.settings
