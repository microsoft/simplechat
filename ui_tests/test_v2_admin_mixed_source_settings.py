# test_v2_admin_mixed_source_settings.py
"""
Browser coverage for where V2 Admin Settings shows the mixed-source settings.
Version: 0.261.260
Implemented in: 0.261.260

Exercise the built application with the real field schema and intercepted APIs.
Before 0.261.260 the page filed five mixed-source switches under Knowledge > Web &
Research > Deep Research, labelled only with their key names, because nothing declared
them and the fallback scan matched the word "source". Check that Deep Research and the
rest of the page now show none of them, that the two real choices appear with their
descriptions under Enhanced Citations and Application Insights, that the spreadsheet
switch is shown only while Enhanced Citations is on, that the behaviors derived from
Enhanced Citations are never drawn, and that both switches save through the production
field normalizer. The classic panes are rendered from their templates and must submit
both switches as normal form checkboxes, including the spreadsheet switch while Enhanced
Citations is off and its container is hidden. No live settings are written.
"""

import re
import sys
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
MIXED_SOURCE_SECTIONS = {
    "chat": ("enhanced-citations-section",),
    "knowledge": ("source-review-section",),
    "operations": ("application-insights-section",),
}
# A settings document after the 0.261.260 load: the derived behaviors follow Enhanced
# Citations and Analyze All has been reset. All of them are enable_* booleans the
# fallback scan would draw if they were not suppressed.
STORED_MIXED_SOURCE_SETTINGS = {
    "enable_enhanced_citations": True,
    "enable_mixed_source_chat_search": True,
    "enable_mixed_source_conversation_continuity": True,
    "enable_cross_format_compare": True,
    "enable_cross_format_compare_one_to_many": True,
    "enable_mixed_source_analyze_all": False,
}
CITATIONS_LABEL = "Enable Enhanced Citations"
RELEVANCE_KEY = "enable_mixed_source_relevance_candidates"
RELEVANCE_LABEL = "Look for relevant spreadsheets when no files are selected"
TELEMETRY_KEY = "enable_mixed_source_development_telemetry"
TELEMETRY_LABEL = "Record mixed document and spreadsheet metrics"
GLOBAL_LOGGING_LABEL = "Enable Application Insights Global Logging"
ARTIFACTS = "v2_admin_mixed_source"


@pytest.fixture
def mixed_source_ui(page):
    fixture = AdminSettingsFixture(page, sections=MIXED_SOURCE_SECTIONS, validate_updates=True)
    fixture.settings.update(STORED_MIXED_SOURCE_SETTINGS)
    yield fixture
    fixture.assert_clean()


def _switch(scope, label):
    return scope.get_by_role("checkbox", name=re.compile(f"^{re.escape(label)}"))


def _set_switch(page, label, checked):
    checkbox = _switch(page, label)
    if checkbox.is_checked() != checked:
        page.get_by_text(label, exact=True).click()
    expect(checkbox).to_be_checked(checked=checked)


def _save(page):
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)


def test_mixed_source_switches_are_described_where_they_belong(mixed_source_ui):
    mixed_source_ui.open(ready_region="Enhanced")
    page = mixed_source_ui.page

    deep_research = page.get_by_role("region", name="Deep Research", exact=True)
    expect(deep_research).to_be_visible()
    expect(deep_research.get_by_text(re.compile("mixed source", re.IGNORECASE))).to_have_count(0)
    # A guessed row prints its raw key; a declared field prints its description instead.
    expect(page.get_by_text(re.compile(r"enable_(mixed_source|cross_format)"))).to_have_count(0)
    expect(page.get_by_text(re.compile(r"^(Mixed source|Cross format compare)", re.IGNORECASE))).to_have_count(0)
    # The fixture always seeds the Agents switches, whose sections are not served here,
    # so "Other capabilities" may exist; it must not hold a mixed-source row.
    other = page.get_by_role("region", name="Other capabilities", exact=True)
    expect(other.get_by_text(re.compile("mixed source|cross format", re.IGNORECASE))).to_have_count(0)

    enhanced = page.get_by_role("region", name="Enhanced", exact=True)
    expect(enhanced.get_by_text("It also turns on spreadsheet analysis", exact=False)).to_be_visible()
    relevance = _switch(enhanced, RELEVANCE_LABEL)
    expect(relevance).to_be_visible()
    expect(relevance).to_be_checked()
    expect(enhanced.get_by_text("second search aimed at spreadsheet columns", exact=False)).to_be_visible()

    insights = page.get_by_role("region", name="Application Insights", exact=True)
    expect(_switch(insights, GLOBAL_LOGGING_LABEL)).to_be_visible()
    telemetry = _switch(insights, TELEMETRY_LABEL)
    expect(telemetry).to_be_visible()
    expect(telemetry).not_to_be_checked()
    expect(insights.get_by_text("Never records prompts", exact=False)).to_be_visible()
    mixed_source_ui.capture("placement", ARTIFACTS)


def test_spreadsheet_switch_is_shown_only_with_enhanced_citations(mixed_source_ui):
    mixed_source_ui.open(ready_region="Enhanced")
    page = mixed_source_ui.page
    enhanced = page.get_by_role("region", name="Enhanced", exact=True)

    _set_switch(page, CITATIONS_LABEL, False)
    expect(_switch(enhanced, RELEVANCE_LABEL)).to_have_count(0)

    _set_switch(page, CITATIONS_LABEL, True)
    expect(_switch(enhanced, RELEVANCE_LABEL)).to_be_visible()
    expect(_switch(enhanced, RELEVANCE_LABEL)).to_be_checked()


def test_spreadsheet_switch_saves_through_the_field_normalizer(mixed_source_ui):
    mixed_source_ui.open(ready_region="Enhanced")
    page = mixed_source_ui.page

    _set_switch(page, RELEVANCE_LABEL, False)
    _save(page)
    assert mixed_source_ui.patches == [{RELEVANCE_KEY: False}]
    assert mixed_source_ui.settings[RELEVANCE_KEY] is False

    page.reload(wait_until="networkidle")
    expect(_switch(page, RELEVANCE_LABEL)).not_to_be_checked()


def test_telemetry_switch_saves_through_the_field_normalizer(mixed_source_ui):
    mixed_source_ui.open(ready_region="Enhanced")
    page = mixed_source_ui.page

    _set_switch(page, TELEMETRY_LABEL, True)
    _save(page)
    assert mixed_source_ui.patches == [{TELEMETRY_KEY: True}]
    assert mixed_source_ui.settings[TELEMETRY_KEY] is True


def _render_classic_pane(page, pane_id, settings):
    environment = Environment(
        loader=FileSystemLoader(APP_ROOT / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    markup = environment.get_template(f"admin/_panes/{pane_id}.html").render(
        settings=settings,
        admin_landing_tab=pane_id,
    )
    page.set_content(f'<form id="admin-settings-form">{markup}</form>')


def _submitted(page, key):
    return page.evaluate(
        "(key) => new FormData(document.getElementById('admin-settings-form')).get(key)",
        key,
    )


@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize("enabled", [False, True])
def test_classic_citation_pane_submits_the_spreadsheet_switch(page, width, enabled):
    page.set_viewport_size({"width": width, "height": 900})
    _render_classic_pane(page, "citation", {"enable_enhanced_citations": True, RELEVANCE_KEY: enabled})
    # admin_settings.js reveals the Enhanced Citations settings while the feature is on.
    page.evaluate("() => { document.getElementById('enhanced_citation_settings').style.display = 'block'; }")

    expect(page.get_by_role("heading", name="Spreadsheets in Chat")).to_be_visible()
    checkbox = page.get_by_label(RELEVANCE_LABEL, exact=True)
    expect(checkbox).to_be_checked(checked=enabled)
    expect(checkbox).to_have_attribute("aria-describedby", f"{RELEVANCE_KEY}_help")
    expect(page.locator(f"#{RELEVANCE_KEY}_help")).to_contain_text("second search aimed at spreadsheet columns")

    checkbox.check()
    submitted_checked = _submitted(page, RELEVANCE_KEY)
    checkbox.uncheck()
    submitted_unchecked = _submitted(page, RELEVANCE_KEY)
    assert submitted_checked == "on"
    assert submitted_unchecked is None


def test_classic_save_keeps_the_spreadsheet_switch_while_citations_are_off(page):
    """The switch sits in a hidden container then, and must still submit its stored value."""
    _render_classic_pane(page, "citation", {"enable_enhanced_citations": False, RELEVANCE_KEY: True})
    expect(page.get_by_label(RELEVANCE_LABEL, exact=True)).to_be_hidden()
    assert _submitted(page, RELEVANCE_KEY) == "on"


def test_classic_logging_pane_submits_the_metrics_switch(page):
    _render_classic_pane(page, "logging", {TELEMETRY_KEY: False})
    checkbox = page.get_by_label(TELEMETRY_LABEL, exact=True)
    expect(checkbox).not_to_be_checked()
    expect(checkbox).to_have_attribute("aria-describedby", f"{TELEMETRY_KEY}_help")
    expect(page.locator(f"#{TELEMETRY_KEY}_help")).to_contain_text("Never records prompts")

    checkbox.check()
    assert _submitted(page, TELEMETRY_KEY) == "on"
