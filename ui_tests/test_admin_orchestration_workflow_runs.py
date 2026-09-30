# test_admin_orchestration_workflow_runs.py
"""
UI coverage for the switch that lets chat orchestration start saved workflows, in both admin surfaces.
Version: 0.261.211
Implemented in: 0.261.211

The V2 page shows Run Workflows From Chat off by default, only while Chat Orchestration and
personal workflows are both on, and saves it as a partial update through the production field
normalizer, without touching Propose Workflows From Chat. A stored value hidden by a prerequisite
survives other saves. The Classic pane renders the switch with its help and submits it as a normal
form checkbox. Both surfaces offer Run workflows in the capability allowlist, which does not turn the
switch on. API interception uses synthetic settings; no live admin settings are changed.
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

from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: F401
from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV


pytestmark = pytest.mark.ui
APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
KEY = "enable_chat_orchestration_workflow_runs"
LABEL = "Run Workflows From Chat"
PROPOSALS_KEY = "enable_chat_orchestration_workflows"
PROPOSALS_LABEL = "Propose Workflows From Chat"
HELP_ID = "chat-orchestration-workflow-runs-help"


@pytest.fixture
def orchestration_admin(page):
    fixture = AdminSettingsFixture(page, validate_updates=True)
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
    fixture.settings["allow_user_workflows"] = True
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


def test_v2_switch_defaults_off_and_saves_as_a_partial_update(orchestration_admin):
    fixture = orchestration_admin
    _open_orchestration(fixture)
    page = fixture.page
    expect(_switch(page, LABEL)).not_to_be_checked()
    expect(_switch(page, PROPOSALS_LABEL)).not_to_be_checked()
    expect(page.get_by_text("always waits for the user to run it", exact=False)).to_be_visible()

    _set_switch(page, LABEL, True)
    _save(page)
    assert fixture.patches == [{KEY: True}]
    assert fixture.settings[KEY] is True
    assert fixture.settings[PROPOSALS_KEY] is False
    assert fixture.settings["chat_orchestration_enabled_capabilities"] == []

    page.reload(wait_until="networkidle")
    expect(_switch(page, LABEL)).to_be_checked()
    expect(_switch(page, PROPOSALS_LABEL)).not_to_be_checked()
    _set_switch(page, LABEL, False)
    _save(page)
    assert fixture.patches[-1] == {KEY: False}
    assert fixture.settings[KEY] is False


def test_v2_switch_is_keyboard_operable(orchestration_admin):
    fixture = orchestration_admin
    _open_orchestration(fixture)
    page = fixture.page
    checkbox = _switch(page, LABEL)
    checkbox.focus()
    expect(checkbox).to_be_focused()
    page.keyboard.press("Space")
    expect(checkbox).to_be_checked()
    _save(page)
    assert fixture.patches == [{KEY: True}]


def test_v2_switch_is_hidden_without_personal_workflows_and_keeps_its_stored_value(orchestration_admin):
    fixture = orchestration_admin
    fixture.settings["allow_user_workflows"] = False
    fixture.settings[KEY] = True
    _open_orchestration(fixture)
    page = fixture.page
    expect(_switch(page, LABEL)).to_have_count(0)

    page.get_by_role("checkbox", name="Propose workflows", exact=True).check()
    _save(page)
    assert fixture.patches == [{"chat_orchestration_enabled_capabilities": ["workflow_propose"]}]
    assert fixture.settings[KEY] is True


def test_v2_switch_reappears_with_its_stored_value_when_orchestration_is_turned_on(orchestration_admin):
    fixture = orchestration_admin
    fixture.settings["enable_chat_orchestration"] = False
    fixture.settings[KEY] = True
    _open_orchestration(fixture)
    page = fixture.page
    expect(_switch(page, LABEL)).to_have_count(0)

    page.get_by_role("button", name="All settings", exact=True).click()
    _set_switch(page, "Enable Chat Orchestration", True)
    expect(_switch(page, LABEL)).to_be_checked()
    _save(page)
    assert fixture.patches == [{"enable_chat_orchestration": True}]
    assert fixture.settings[KEY] is True


def test_v2_capability_allowlist_offers_run_workflows_on_its_own(orchestration_admin):
    fixture = orchestration_admin
    _open_orchestration(fixture)
    page = fixture.page
    capability = page.get_by_role("checkbox", name="Run workflows", exact=True)
    expect(capability).not_to_be_checked()
    expect(page.get_by_text(f"Run workflows also requires {LABEL}", exact=False)).to_be_visible()

    capability.check()
    _save(page)
    # Admitting the capability does not turn on the switch it also needs.
    assert fixture.patches == [{"chat_orchestration_enabled_capabilities": ["workflow_run"]}]
    assert fixture.settings[KEY] is False


def _render_classic_pane(page, settings):
    registry = import_app_module("functions_orchestration_registry")
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


def _submitted(page, key=KEY):
    return page.evaluate(
        "(key) => new FormData(document.getElementById('orchestration-settings')).get(key)",
        key,
    )


@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize("enabled", [False, True])
def test_classic_pane_switch_submits_a_normal_form_value(page, width, enabled):
    page.set_viewport_size({"width": width, "height": 900})
    _render_classic_pane(page, {"enable_chat_orchestration": True, "allow_user_workflows": True, KEY: enabled})
    checkbox = page.get_by_label(LABEL, exact=True)
    expect(checkbox).to_be_checked(checked=enabled)
    expect(checkbox).to_have_attribute("aria-describedby", HELP_ID)
    expect(page.locator(f"#{HELP_ID}")).to_be_visible()
    expect(page.locator(f"#{HELP_ID}")).to_contain_text("Requires Chat Orchestration and Enable Personal Workflows.")

    page.locator(f'label[for="{KEY}"]').click()
    expect(checkbox).to_be_checked(checked=not enabled)
    submitted_after_label_click = _submitted(page)
    assert submitted_after_label_click == (None if enabled else "on")

    checkbox.check()
    submitted_checked = _submitted(page)
    submitted_proposals = _submitted(page, PROPOSALS_KEY)
    checkbox.uncheck()
    submitted_unchecked = _submitted(page)
    assert submitted_checked == "on"
    assert submitted_proposals is None
    assert submitted_unchecked is None

    # The capability box is a separate allowlist entry with the settings it also needs.
    capability = page.locator("#chat_orchestration_capability_workflow_run")
    expect(capability).to_be_checked()
    expect(page.get_by_text(f"Run workflows also requires {LABEL}", exact=False)).to_be_visible()
    submitted_capabilities = page.evaluate(
        "() => new FormData(document.getElementById('orchestration-settings'))"
        ".getAll('chat_orchestration_enabled_capabilities')"
    )
    assert "workflow_run" in submitted_capabilities
