# test_admin_orchestration_actions.py
"""
UI coverage for the orchestration action opt-in in both admin surfaces.
Version: 0.261.098
Implemented in: 0.261.098

Reuse the schema-backed admin fixture and Azure Playwright connection options.
API interception uses synthetic settings; no live admin settings are changed.
"""

import copy
import re
import sys
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect

# Shared fixtures provide isolated application imports and Azure connect_options.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options
from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV


pytestmark = pytest.mark.ui
APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
ACTION_FLAG = "enable_chat_orchestration_actions"
CAPABILITIES_KEY = "chat_orchestration_enabled_capabilities"


@pytest.fixture
def orchestration_admin(page):
    fixture = AdminSettingsFixture(page)
    group = copy.deepcopy(next(item for item in ADMIN_NAV if item["id"] == "orchestration"))
    fields = import_app_module("admin_settings_fields").get_admin_settings_fields()
    fixture.payload["admin_nav"].append(group)
    for tab in group["tabs"]:
        for section in tab["sections"]:
            definitions = copy.deepcopy(fields[section["id"]])
            fixture.schema[section["id"]] = definitions
            for field in definitions:
                if field.get("key") and "default" in field:
                    fixture.settings[field["key"]] = copy.deepcopy(field["default"])
    fixture.settings["enable_chat_orchestration"] = True
    yield fixture
    fixture.assert_clean()


def _switch(page, label):
    return page.get_by_role("checkbox", name=re.compile(f"^{re.escape(label)}"))


def _set_switch(page, label, checked):
    checkbox = _switch(page, label)
    if checkbox.is_checked() != checked:
        page.get_by_text(label, exact=True).click()
    expect(checkbox).to_be_checked(checked=checked)


def _open_orchestration(fixture):
    fixture.open()
    fixture.page.get_by_role("button", name="Orchestration", exact=True).click()


def _save(page):
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)


def test_v2_opt_in_defaults_off_and_round_trips_as_a_partial_update(orchestration_admin):
    fixture = orchestration_admin
    _open_orchestration(fixture)
    page = fixture.page
    expect(_switch(page, "Enable Action Access")).not_to_be_checked()
    expect(page.get_by_role("checkbox", name="Use an action", exact=True)).to_be_visible()
    _set_switch(page, "Enable Action Access", True)
    _save(page)
    assert fixture.patches == [{ACTION_FLAG: True}]
    assert fixture.settings[CAPABILITIES_KEY] == []
    page.reload(wait_until="networkidle")
    expect(_switch(page, "Enable Action Access")).to_be_checked()
    _set_switch(page, "Enable Action Access", False)
    _save(page)
    assert fixture.patches[-1] == {ACTION_FLAG: False}


def test_v2_capability_selection_never_changes_the_independent_opt_in(orchestration_admin):
    fixture = orchestration_admin
    _open_orchestration(fixture)
    page = fixture.page
    page.get_by_role("checkbox", name="Use an action", exact=True).check()
    _save(page)
    assert fixture.patches == [{CAPABILITIES_KEY: ["action_invoke"]}]
    assert fixture.settings[ACTION_FLAG] is False
    _set_switch(page, "Enable Action Access", True)
    _save(page)
    page.get_by_role("checkbox", name="Use an action", exact=True).uncheck()
    _save(page)
    assert fixture.patches[-1] == {CAPABILITIES_KEY: []}
    assert fixture.settings[ACTION_FLAG] is True


@pytest.mark.parametrize("gate,label", [
    ("enable_chat_orchestration", "Enable Chat Orchestration"),
    ("enable_semantic_kernel", "Enable Agents"),
])
def test_v2_hidden_opt_in_is_preserved_when_a_prerequisite_is_changed(orchestration_admin, gate, label):
    fixture = orchestration_admin
    fixture.settings[ACTION_FLAG] = True
    fixture.settings[gate] = False
    _open_orchestration(fixture)
    page = fixture.page
    expect(_switch(page, "Enable Action Access")).to_have_count(0)
    page.get_by_role("button", name="All settings", exact=True).click()
    _set_switch(page, label, True)
    expect(_switch(page, "Enable Action Access")).to_be_checked()
    _save(page)
    assert fixture.patches == [{gate: True}]
    assert fixture.settings[ACTION_FLAG] is True


@pytest.mark.parametrize("enabled", [False, True])
def test_template_opt_in_and_action_capability_submit_normal_form_values(page, enabled):
    fields = import_app_module("admin_settings_fields").get_admin_settings_fields()
    registry = import_app_module("functions_orchestration_registry")
    settings = {
        field["key"]: copy.deepcopy(field["default"])
        for section_id, definitions in fields.items()
        if section_id.startswith("chat-orchestration-")
        for field in definitions
        if field.get("key") and "default" in field
    }
    settings.update({
        "enable_chat_orchestration": True,
        "enable_semantic_kernel": True,
        ACTION_FLAG: enabled,
    })
    environment = Environment(
        loader=FileSystemLoader(APP_ROOT / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    template = environment.get_template("admin/_panes/chat-orchestration.html")
    markup = template.render(
        settings=settings,
        admin_landing_tab="chat-orchestration",
        orchestration_capabilities=registry.build_capability_client_projection(registry.CAPABILITY_REGISTRY),
        orchestration_selected_capabilities=registry.all_capability_ids(),
    )
    page.set_content(f'<form id="orchestration-settings">{markup}</form>')
    checkbox = page.get_by_label("Enable Action Access", exact=True)
    expect(checkbox).to_be_checked(checked=enabled)
    expect(checkbox).to_have_attribute("aria-describedby", "chat-orchestration-actions-help")
    expect(page.locator("#chat-orchestration-actions-help")).to_contain_text(
        "Requires Chat Orchestration and Semantic Kernel"
    )
    expect(page.locator("#chat_orchestration_capability_action_invoke")).to_be_checked()
    expect(page.locator('label[for="chat_orchestration_capability_action_invoke"]')).to_contain_text(
        "Use an action"
    )
    expect(page.locator("#chat_orchestration_capability_respond")).to_be_disabled()
    checkbox.check()
    assert page.evaluate(
        "(key) => new FormData(document.getElementById('orchestration-settings')).get(key)",
        ACTION_FLAG,
    ) == "on"
    checkbox.uncheck()
    assert page.evaluate(
        "(key) => new FormData(document.getElementById('orchestration-settings')).get(key)",
        ACTION_FLAG,
    ) is None
