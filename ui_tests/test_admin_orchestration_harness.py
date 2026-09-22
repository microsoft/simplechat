# test_admin_orchestration_harness.py
"""
UI coverage for the new-plan Gather / Reason / Render preview control.
Version: 0.261.127
Implemented in: 0.261.127

Render the real admin pane with synthetic settings. Check accessible labeling,
default/strict checked state, keyboard interaction and normal form submission.
The shared Azure Playwright connection fixture also supports a local browser.
Refs microsoft/simplechat#1509.
"""

import sys
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect

# The shared fixture supplies Azure workspace authentication when configured.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from playwright_connection import connect_options


pytestmark = pytest.mark.ui
APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
HARNESS_FLAG = "enable_chat_orchestration_harness"
LABEL = "Gather / Reason / Render harness (preview)"


def render_pane(page, settings, *, capabilities=(), selected=()):
    environment = Environment(
        loader=FileSystemLoader(APP_ROOT / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    template = environment.get_template("admin/_panes/chat-orchestration.html")
    markup = template.render(
        settings=settings,
        admin_landing_tab="chat-orchestration",
        orchestration_capabilities=capabilities,
        orchestration_selected_capabilities=selected,
    )
    page.set_content(f'<form id="orchestration-settings">{markup}</form>')


@pytest.mark.parametrize("settings,checked", [
    ({}, False),
    ({HARNESS_FLAG: False}, False),
    ({HARNESS_FLAG: True}, True),
    ({HARNESS_FLAG: "false"}, False),
    ({HARNESS_FLAG: "true"}, False),
])
def test_preview_checked_state_requires_a_saved_boolean(page, settings, checked):
    render_pane(page, settings)
    checkbox = page.get_by_role("checkbox", name=LABEL, exact=True)
    expect(checkbox).to_be_visible()
    expect(checkbox).to_be_checked(checked=checked)
    expect(checkbox).to_have_attribute("aria-describedby", "chat-orchestration-harness-help")
    help_text = page.locator("#chat-orchestration-harness-help")
    expect(help_text).to_contain_text("Off by default")
    expect(help_text).to_contain_text("Requires Chat Orchestration and server rollout readiness")
    expect(help_text).to_contain_text("retained results and explicit file-rendering tasks")
    expect(help_text).to_contain_text("authorized read/recovery access")


def test_preview_uses_keyboard_and_standard_checkbox_submission(page):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    render_pane(page, {"enable_chat_orchestration": True})
    checkbox = page.get_by_role("checkbox", name=LABEL, exact=True)
    checkbox.focus()
    checkbox.press("Space")
    expect(checkbox).to_be_checked()
    submitted = page.evaluate(
        "(key) => new FormData(document.getElementById('orchestration-settings')).get(key)",
        HARNESS_FLAG,
    )
    assert submitted == "on"
    checkbox.press("Space")
    expect(checkbox).not_to_be_checked()
    unchecked = page.evaluate(
        "(key) => new FormData(document.getElementById('orchestration-settings')).get(key)",
        HARNESS_FLAG,
    )
    assert unchecked is None
    expect(page.get_by_label("Enable Chat Orchestration", exact=True)).to_be_checked()
    assert errors == []


@pytest.mark.parametrize("width", [1280, 390])
def test_harness_capabilities_remain_independent_when_preview_is_off(page, width):
    page.set_viewport_size({"width": width, "height": 900})
    capabilities = [
        {"id": "respond", "label": "Answering", "cost": "low", "terminal": True, "summary": "Legacy answer."},
        {"id": "compose", "label": "Prepare content", "cost": "medium", "terminal": False, "summary": "Reusable prepared content."},
        {"id": "render_file", "label": "Create a file", "cost": "low", "terminal": False, "summary": "Render an explicit file."},
    ]
    render_pane(
        page, {"enable_chat_orchestration": True, HARNESS_FLAG: False},
        capabilities=capabilities, selected=("compose", "render_file"),
    )
    compose = page.get_by_role("checkbox", name="Prepare content")
    render = page.get_by_role("checkbox", name="Create a file")
    legacy = page.get_by_role("checkbox", name="Answering")
    expect(compose).to_be_checked()
    expect(render).to_be_checked()
    expect(legacy).to_be_checked()
    expect(legacy).to_be_disabled()
    render.focus()
    render.press("Space")
    expect(render).not_to_be_checked()
    expect(compose).to_be_checked()
    selected = page.evaluate(
        "() => new FormData(document.getElementById('orchestration-settings'))"
        ".getAll('chat_orchestration_enabled_capabilities')",
    )
    assert selected == ["compose"]
    expect(page.get_by_role("checkbox", name=LABEL, exact=True)).not_to_be_checked()
