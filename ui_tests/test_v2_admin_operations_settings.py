# test_v2_admin_operations_settings.py
"""
Browser coverage for the V2 Admin Settings Operations group.
Version: 0.261.260
Implemented in: 0.261.260

Exercise the built application with the real Operations field schema and the real
settings normalizer behind an intercepted API. Check that every Operations section
renders real controls instead of guessed switches, that the logging timer and the
refresh schedule report what a save will do and then what the server calculated, that
the access table follows unsaved role switches, that each section guide opens from its
header and hands focus back, that the stored-log cleanup confirms exactly what it will
delete before posting, and that nothing overflows at phone or desktop widths in light or
dark -- without writing to live settings.
"""

import copy
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401
from test_support.app_stubs import import_app_module  # noqa: E402
from test_support.nav import ADMIN_NAV  # noqa: E402


pytestmark = [
    pytest.mark.ui,
    # The schedule is shown in its own zone and the reader's; a reader outside the
    # schedule's zone is what makes the second one appear.
    pytest.mark.browser_context_args(timezone_id="Europe/Paris", locale="en-US"),
]

# The fixture origin is plain HTTP, where browsers withhold the Clipboard API, so copies
# are recorded instead, as test_control_center_activity_logs_layout does.
CLIPBOARD_STUB = """
Object.defineProperty(window, '__copiedText', { value: null, writable: true, configurable: true });
Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: async (text) => { window.__copiedText = text; } },
    configurable: true,
});
"""

OPERATIONS_SECTIONS = {
    "operations": (
        "control-center-auto-refresh-section",
        "control-center-overview-section",
        "application-insights-section",
        "debug-logging-section",
        "file-processing-logs-section",
        "health-check-section",
        "swagger-section",
    ),
}
SECTION_LABELS = (
    "Automatic Data Refresh",
    "Control Center Access",
    "Application Insights",
    "Debug Logging",
    "File Process Logging",
    "Health Check",
    "API Documentation",
)
CLEANUP_PATH = "**/api/admin/settings/file-processing-logs/cleanup"
ARTIFACTS = "v2_admin_operations"
# Section, header button, dialog title.
GUIDES = (
    ("Control Center Access", "Role setup guide", "Control Center role setup"),
    ("Health Check", "Configuration guide", "Health check configuration"),
    ("API Documentation", "Why enable Swagger?", "Why enable Swagger?"),
)


def _dai_metrics_location():
    """Scale > Cosmos > DAI Metrics alone, so a cross-reference has somewhere to point.

    The fixture narrows the navigation to the sections under test, while production sends
    all of it. With no fields declared for it here, the section is not drawn.
    """
    group = copy.deepcopy(next(
        group for group in ADMIN_NAV
        if any(tab["id"] == "cosmos" for tab in group["tabs"])
    ))
    group["tabs"] = [tab for tab in group["tabs"] if tab["id"] == "cosmos"]
    group["tabs"][0]["sections"] = [
        section for section in group["tabs"][0]["sections"]
        if section["id"] == "document-access-index-section"
    ]
    return group


@pytest.fixture
def operations_ui(page):
    fields_module = import_app_module("admin_settings_fields")
    page.add_init_script(CLIPBOARD_STUB)
    fixture = AdminSettingsFixture(page, sections=OPERATIONS_SECTIONS, validate_updates=True)
    # Seeded for the Agents tests; undeclared here, it would fall back to a guessed switch.
    fixture.settings.pop("enable_semantic_kernel", None)
    fixture.payload["admin_nav"].append(_dai_metrics_location())
    now = datetime.now(timezone.utc)
    fixture.settings.update({
        "enable_debug_logging": True,
        "debug_logging_timer_enabled": True,
        "debug_timer_value": 2,
        "debug_timer_unit": "hours",
        "debug_logging_turnoff_time": (now + timedelta(minutes=59)).isoformat(),
        "enable_external_healthcheck": True,
        "control_center_auto_refresh_next_run": (now + timedelta(hours=5)).isoformat(),
        "control_center_last_refresh": (now - timedelta(hours=19)).isoformat(),
    })
    fixture.payload["section_guides"] = copy.deepcopy(fields_module.get_admin_section_guides())
    fixture.payload["runtime_flags"] = {
        "appinsights_connection_configured": False,
        "appinsights_global_logging_active": False,
        "swagger_routes_registered": True,
    }
    fixture.payload["status_readouts"] = {
        "appinsights_connection": {
            "ok": False,
            "message": (
                "APPLICATIONINSIGHTS_CONNECTION_STRING is not set on this App Service, so "
                "nothing reaches Application Insights whatever the switch above says."
            ),
        },
    }
    yield fixture
    fixture.assert_clean()


def _region(page, name):
    return page.get_by_role("region", name=name, exact=True)


def test_every_operations_section_renders_real_controls(operations_ui):
    operations_ui.open(width=1440, ready_region="Automatic Data Refresh")
    page = operations_ui.page

    for label in SECTION_LABELS:
        expect(_region(page, label)).to_be_visible()

    # Nothing is left to the fallback scan, so no switch named after its raw key and no
    # pointer to the classic page for "settings that need more than a switch".
    expect(page.get_by_text("Dai debug", exact=True)).to_have_count(0)
    expect(page.get_by_text(re.compile("still on the"))).to_have_count(0)

    debug = _region(page, "Debug Logging")
    debug.get_by_role("button", name=re.compile("^Feature diagnostics")).click()
    expect(debug.get_by_text("Document Access Index diagnostics", exact=True)).to_be_visible()
    expect(debug.get_by_role("link", name=re.compile("^Open DAI Metrics on the classic admin page"))).to_have_attribute(
        "href", "/admin/settings#cosmos"
    )
    operations_ui.capture("all-sections-1440", ARTIFACTS)


def test_the_debug_timer_nests_and_reports_its_turnoff(operations_ui):
    operations_ui.open(width=1440, ready_region="Debug Logging")
    page = operations_ui.page
    debug = _region(page, "Debug Logging")

    # The timer switch, duration and unit sit beneath the switch they depend on.
    expect(debug.locator('[data-setting-emphasis="dependent"]')).to_have_count(3)
    expect(debug.get_by_text(re.compile(r"^Turns off .*\(in 1 hour\)\.$"))).to_be_visible()

    duration = debug.get_by_label("Duration", exact=True)
    duration.fill("3")
    expect(debug.get_by_text(re.compile(r"^Saving now would turn it off .*\(in 3 hours\)\."))).to_be_visible()

    page.get_by_role("button", name="Save changes").click()
    expect(page.get_by_role("button", name="Save changes")).to_have_count(0)
    assert operations_ui.patches[-1] == {"debug_timer_value": 3}
    stored = operations_ui.settings["debug_logging_turnoff_time"]
    assert stored.endswith("+00:00"), f"The turnoff time was not stored in UTC: {stored}"
    expect(debug.get_by_text(re.compile(r"^Turns off .*\(in 3 hours\)\.$"))).to_be_visible()


def test_the_refresh_schedule_reads_in_both_timezones_and_adopts_mine(operations_ui):
    operations_ui.open(width=1440, ready_region="Automatic Data Refresh")
    page = operations_ui.page
    schedule = _region(page, "Automatic Data Refresh")

    expect(schedule.get_by_label("Refresh Time", exact=True)).to_have_attribute("type", "time")
    expect(schedule.get_by_text(re.compile(r"in America/New_York, which is .* your time"))).to_be_visible()
    expect(schedule.get_by_text(re.compile(r"^Last refreshed "))).to_be_visible()
    expect(schedule.get_by_role("link", name=re.compile("^Open Control Center"))).to_have_attribute(
        "target", "_blank"
    )

    schedule.get_by_role("button", name="Use my timezone (Europe/Paris)").click()
    expect(schedule.get_by_label("Timezone", exact=True)).to_have_value("Europe/Paris")
    expect(schedule.get_by_text(re.compile(r"^Saving schedules the next refresh for"))).to_be_visible()

    page.get_by_role("button", name="Save changes").click()
    expect(page.get_by_role("button", name="Save changes")).to_have_count(0)
    assert operations_ui.patches[-1] == {"control_center_auto_refresh_timezone": "Europe/Paris"}
    next_run = datetime.fromisoformat(operations_ui.settings["control_center_auto_refresh_next_run"])
    assert next_run.utcoffset() == timedelta(0)
    expect(schedule.get_by_text("Runs daily at 2:00 AM, Europe/Paris time.", exact=True)).to_be_visible()


def test_a_refused_timezone_is_reported_on_the_field(operations_ui):
    operations_ui.open(width=1440, ready_region="Automatic Data Refresh")
    page = operations_ui.page
    schedule = _region(page, "Automatic Data Refresh")

    schedule.get_by_label("Timezone", exact=True).fill("Mars/Olympus")
    expect(schedule.get_by_text(re.compile("Not a timezone this browser recognises"))).to_be_visible()
    page.get_by_role("button", name="Save changes").click()
    expect(schedule.get_by_role("alert")).to_contain_text("Choose an IANA timezone")
    # The refusal is the point; Chromium logs every 400 as a console error.
    operations_ui.errors = [error for error in operations_ui.errors if "400 (Bad Request)" not in error]


def test_the_access_table_follows_unsaved_role_switches(operations_ui):
    operations_ui.open(width=1440, ready_region="Control Center Access")
    page = operations_ui.page
    access = _region(page, "Control Center Access")
    table = access.get_by_role("table")

    expect(table).to_contain_text(re.compile(r"\bAdmin can use the management features"))
    page.get_by_text("Require ControlCenterAdmin App Role", exact=True).click()
    expect(table).to_contain_text(re.compile(r"\bAdmin cannot use the management features"))
    expect(table).to_contain_text("ControlCenterAdmin can use the management features")
    expect(access.get_by_text(re.compile("Showing your unsaved changes"))).to_be_visible()

    access.get_by_role("button", name="Copy the ControlCenterAdmin role value").click()
    assert page.wait_for_function("window.__copiedText").json_value() == "ControlCenterAdmin"


@pytest.mark.parametrize("region_name,button,title", GUIDES)
def test_each_guide_opens_from_its_header_and_returns_focus(operations_ui, region_name, button, title):
    operations_ui.open(width=1440, ready_region=region_name)
    page = operations_ui.page
    trigger = _region(page, region_name).get_by_role("button", name=button)
    trigger.click()

    dialog = page.get_by_role("dialog", name=title)
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("heading", level=3).first).to_be_visible()
    expect(dialog.get_by_role("link", name=re.compile("^Read this in the documentation"))).to_have_attribute(
        "href", re.compile(r"^https://microsoft\.github\.io/simplechat/admin/operations/#")
    )

    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(trigger).to_be_focused()


def test_the_health_check_guide_shows_this_deployments_addresses(operations_ui):
    operations_ui.open(width=1440, ready_region="Health Check")
    page = operations_ui.page
    _region(page, "Health Check").get_by_role("button", name="Configuration guide").click()
    dialog = page.get_by_role("dialog", name="Health check configuration")

    expect(dialog).to_contain_text("http://simplechat.test/external/healthcheck")
    expect(dialog).to_contain_text("Enable External Healthcheck is disabled.")
    dialog.get_by_role("button", name="Copy the health check path").click()
    assert page.wait_for_function("window.__copiedText").json_value() == "/external/healthcheck"
    operations_ui.capture("health-check-guide", ARTIFACTS)


def test_endpoints_offer_open_only_while_they_answer(operations_ui):
    operations_ui.open(width=1440, ready_region="Health Check")
    page = operations_ui.page
    health = _region(page, "Health Check")

    expect(health.get_by_text("http://simplechat.test/external/healthcheck", exact=True)).to_be_visible()
    expect(health.get_by_role("link", name=re.compile("^Open"))).to_have_count(1)

    page.get_by_text("Enable /external/healthcheckz", exact=True).click()
    expect(health.get_by_text("On after you save", exact=True)).to_be_visible()
    expect(health.get_by_role("link", name=re.compile("^Open"))).to_have_count(1)


def test_startup_bound_settings_say_when_a_restart_is_needed(operations_ui):
    operations_ui.open(width=1440, ready_region="API Documentation")
    page = operations_ui.page

    insights = _region(page, "Application Insights")
    expect(insights.get_by_text(re.compile("APPLICATIONINSIGHTS_CONNECTION_STRING is not set"))).to_be_visible()
    # With nowhere to send telemetry, there is no running state worth comparing.
    expect(insights.get_by_text("Running state", exact=True)).to_have_count(0)

    swagger = _region(page, "API Documentation")
    expect(swagger.get_by_text("Running as saved: on.", exact=True)).to_be_visible()
    page.get_by_text("Enable Swagger/OpenAPI Documentation (/swagger)", exact=True).click()
    expect(swagger.get_by_text(re.compile(r"^Turns off after you save and then restart"))).to_be_visible()


def test_the_log_cleanup_confirms_what_it_deletes_before_posting(operations_ui):
    posted = []

    def cleanup(route):
        posted.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(json={"success": True, "deleted_count": 3, "delete_all": False, "cutoff": None})

    operations_ui.page.route(CLEANUP_PATH, cleanup)
    operations_ui.open(width=1440, ready_region="File Process Logging")
    page = operations_ui.page
    logs = _region(page, "File Process Logging")

    age = logs.get_by_label("Delete logs older than", exact=True)
    age.fill("0")
    logs.get_by_role("button", name="Delete older logs").click()
    expect(logs.get_by_role("alert")).to_contain_text("whole number greater than zero")
    expect(age).to_be_focused()
    assert not posted

    age.fill("14")
    logs.get_by_label("Unit", exact=True).select_option("weeks")
    logs.get_by_role("button", name="Delete older logs").click()
    dialog = page.get_by_role("dialog", name="Delete file processing logs")
    expect(dialog).to_contain_text("Delete every file processing log older than 14 weeks?")
    dialog.get_by_role("button", name="Delete logs").click()

    expect(page.get_by_text("Deleted 3 file processing logs.", exact=True)).to_be_visible()
    assert posted == [{"delete_all": False, "age": 14, "unit": "weeks", "confirmed": True}]
    # Not a setting: nothing is left waiting for Save.
    expect(page.get_by_role("button", name="Save changes")).to_have_count(0)


def test_a_failed_cleanup_says_how_far_it_got(operations_ui):
    operations_ui.page.route(
        CLEANUP_PATH,
        lambda route: route.fulfill(
            status=500,
            json={"success": False, "error": "File processing log cleanup did not complete.", "deleted_count": 2},
        ),
    )
    operations_ui.open(width=1440, ready_region="File Process Logging")
    page = operations_ui.page
    _region(page, "File Process Logging").get_by_role("button", name="Delete all logs").click()
    dialog = page.get_by_role("dialog", name="Delete file processing logs")
    dialog.get_by_role("button", name="Delete logs").click()
    expect(dialog.get_by_role("alert")).to_contain_text("2 logs were deleted before it stopped.")
    # The failure is the point; Chromium logs every 500 as a console error.
    operations_ui.errors = [error for error in operations_ui.errors if "500 (Internal Server Error)" not in error]


@pytest.mark.parametrize("font_size", ["m", "xl"])
def test_guides_fit_a_phone(operations_ui, font_size):
    operations_ui.open(width=390, font_size=font_size, ready_region="Automatic Data Refresh")
    page = operations_ui.page
    for region_name, button, title in GUIDES:
        _region(page, region_name).get_by_role("button", name=button).click()
        dialog = page.get_by_role("dialog", name=title)
        expect(dialog).to_be_visible()
        # Tables and code scroll inside their own frames; the guide itself never scrolls sideways.
        overflow = dialog.locator(".glass-modal > .overflow-y-auto").evaluate(
            "element => element.scrollWidth - element.clientWidth"
        )
        assert overflow <= 1, f"The {title} guide scrolls sideways by {overflow}px at {font_size}"
        operations_ui.capture(f"guide-{button.lower().replace(' ', '-').strip('?')}-390-{font_size}", ARTIFACTS)
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width,font_size", [(390, "m"), (1920, "m"), (390, "xl")])
def test_operations_cards_never_overflow(operations_ui, theme, width, font_size):
    operations_ui.open(theme=theme, width=width, font_size=font_size, ready_region="Automatic Data Refresh")
    page = operations_ui.page
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for region in page.locator(".admin-settings-distinct").all():
        overflow = region.evaluate("element => element.scrollWidth - element.clientWidth")
        assert overflow <= 1, f"A card overflows by {overflow}px at {width}px/{font_size}/{theme}"
    operations_ui.capture(f"responsive-{theme}-{width}-{font_size}", ARTIFACTS)
