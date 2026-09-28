# test_workflow_classic_advanced_guard.py
"""
Source-backed browser coverage for the Classic advanced-workflow edit guard.
Version: 0.261.193
Implemented in: 0.261.116; calendar schedule routing and labels added in 0.261.193

The actual local edit function must stop before loading runners or resetting a
draft for advanced definitions and for calendar schedules, which the Classic
form cannot show. Legacy eligibility, the advanced-flow message, interval
labels, and Run/Cancel are unchanged.
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.playwright_connection import connect_options  # noqa: F401


SOURCE = Path(__file__).resolve().parents[1] / "application" / "single_app" / "static" / "js" / "workspace" / "workspace_workflows.js"
ORIGIN = "http://workflow-guard.test"
ADVANCED_MESSAGE = (
    "This workflow uses advanced data flow. Open V2 to edit it without losing its configuration. "
    "Run and Cancel remain available here."
)
CALENDAR_MESSAGE = (
    "This workflow uses a calendar schedule. Open V2 to edit it without losing its configuration. "
    "Run and Cancel remain available here."
)
GUARD_FUNCTIONS = (
    "normalizeText",
    "isWorkflowCalendarSchedule",
    "workflowNativeEditorReason",
    "workflowNeedsNativeEditor",
    "openWorkflowModal",
)
LABEL_FUNCTIONS = (
    "normalizeText",
    "isWorkflowCalendarSchedule",
    "getWorkflowCalendarScheduleLabel",
    "getWorkflowTriggerLabel",
)
pytestmark = pytest.mark.ui


def _function(source, name):
    start = re.search(rf"(?m)^(?:async )?function {name}\(", source)
    assert start, f"Missing production function {name}."
    following = re.search(r"(?m)^(?:async )?function ", source[start.end():])
    assert following, f"Missing end boundary for production function {name}."
    return source[start.start():start.end() + following.start()]


def _functions(names):
    source = SOURCE.read_text(encoding="utf-8")
    return "\n".join(_function(source, name) for name in names)


def _serve(page, script, unexpected):
    def route(request):
        if request.request.url == f"{ORIGIN}/":
            request.fulfill(
                content_type="text/html",
                body='<html lang="en"><body><button id="edit" type="button">Edit workflow</button><script src="/guard.js"></script></body></html>',
            )
        elif request.request.url == f"{ORIGIN}/guard.js":
            request.fulfill(content_type="application/javascript", body=script)
        else:
            unexpected.append(request.request.url)
            request.abort()

    page.route("**/*", route)
    page.goto(f"{ORIGIN}/")


def _guard_script():
    return """
window.preparationCalls = 0;
const workflowModal = {show() { window.preparationCalls++; }};
const workflowWorkspaceConfig = {scope: 'personal'};
function getWorkflowActiveGroupId() { return 'group-1'; }
async function loadAgentOptions() { window.preparationCalls++; throw new Error('Unexpected runner loading'); }
async function loadFileSyncSourceOptions() { window.preparationCalls++; throw new Error('Unexpected source loading'); }
function resetWorkflowForm() { window.preparationCalls++; }
function showToast(message, tone) {
    const notice = document.createElement('div');
    notice.classList.add('alert', `alert-${tone}`);
    notice.setAttribute('role', 'alert');
    notice.textContent = message;
    document.body.appendChild(notice);
}
""" + _functions(GUARD_FUNCTIONS) + """
document.getElementById('edit').addEventListener('click', () => openWorkflowModal(window.testWorkflow));
window.configureScope = scope => { workflowWorkspaceConfig.scope = scope; };
"""


@pytest.mark.parametrize("scope", ["personal", "group"])
@pytest.mark.parametrize("version", [2, 3, 4, "3"])
def test_classic_advanced_edit_stops_before_preparation(page, scope, version):
    unexpected = []
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _serve(page, _guard_script(), unexpected)
    page.evaluate("(scope) => window.configureScope(scope)", scope)
    page.evaluate("(version) => { window.testWorkflow = {id: 'workflow', definition_version: version}; }", version)
    page.get_by_role("button", name="Edit workflow", exact=True).click()
    expect(page.get_by_role("alert")).to_have_text(ADVANCED_MESSAGE)
    assert page.evaluate("window.preparationCalls") == 0
    assert page.evaluate("workflowNeedsNativeEditor(null)") is False
    assert page.evaluate("workflowNeedsNativeEditor({id: 'legacy'})") is False
    assert page.evaluate("workflowNeedsNativeEditor({definition_version: 1})") is False
    assert page.evaluate("workflowNeedsNativeEditor({definition_version: 1, flow: {}})") is True
    assert not unexpected
    assert not errors


@pytest.mark.parametrize("scope", ["personal", "group"])
@pytest.mark.parametrize("trigger", ["interval", "file_sync"])
@pytest.mark.parametrize("version", [1, 2])
def test_classic_calendar_edit_routes_to_v2(page, scope, trigger, version):
    unexpected = []
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _serve(page, _guard_script(), unexpected)
    page.evaluate("(scope) => window.configureScope(scope)", scope)
    page.evaluate(
        """([trigger, version]) => {
            window.testWorkflow = {
                id: 'workflow',
                definition_version: version,
                trigger_type: trigger,
                schedule: {
                    kind: 'calendar', frequency: 'weekly', days_of_week: ['monday'], day_of_month: null,
                    time_of_day: '08:00', timezone: 'America/New_York',
                },
            };
        }""",
        [trigger, version],
    )
    page.get_by_role("button", name="Edit workflow", exact=True).click()
    expect(page.get_by_role("alert")).to_have_text(CALENDAR_MESSAGE)
    assert page.evaluate("window.preparationCalls") == 0
    assert page.evaluate("workflowNeedsNativeEditor({trigger_type: 'interval', schedule: {unit: 'minutes', value: 5}})") is False
    assert page.evaluate("workflowNeedsNativeEditor({trigger_type: 'file_sync', schedule: {unit: 'hours', value: 1}})") is False
    assert page.evaluate("workflowNeedsNativeEditor({trigger_type: 'manual', schedule: {}})") is False
    assert page.evaluate("workflowNeedsNativeEditor({trigger_type: 'interval', schedule: {kind: 'Calendar'}})") is True
    assert page.evaluate("workflowNativeEditorReason({definition_version: 3, flow: {}, schedule: {kind: 'calendar'}})") == "a calendar schedule"
    assert page.evaluate("workflowNativeEditorReason({definition_version: 2, schedule: {unit: 'minutes', value: 5}})") == "advanced data flow"
    assert not unexpected
    assert not errors


def test_classic_schedule_labels(page):
    unexpected = []
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _serve(page, _functions(LABEL_FUNCTIONS), unexpected)

    def label(workflow):
        return page.evaluate("(workflow) => getWorkflowTriggerLabel(workflow)", workflow)

    def calendar(**changes):
        return {
            "kind": "calendar", "frequency": "daily", "days_of_week": [], "day_of_month": None,
            "time_of_day": "08:00", "timezone": "America/New_York", **changes,
        }

    # Interval labels are unchanged.
    assert label({"trigger_type": "interval", "schedule": {"unit": "minutes", "value": 30}}) == "Every 30 minutes"
    assert label({"trigger_type": "interval", "schedule": {"unit": "minutes", "value": 1}}) == "Every 1 minutes"
    assert label({"trigger_type": "file_sync", "schedule": {"unit": "hours", "value": 2}}) == "Monitor File Sync every 2 hours"
    assert label({"trigger_type": "manual", "schedule": {}}) == "Manual"
    assert label(None) == "Manual"

    weekly = calendar(frequency="weekly", days_of_week=["monday"])
    assert label({"trigger_type": "interval", "schedule": weekly}) == "Mondays 08:00 America/New_York"
    several = calendar(frequency="weekly", days_of_week=["friday", "monday", "wednesday"])
    assert label({"trigger_type": "interval", "schedule": several}) == "Mondays, Wednesdays and Fridays 08:00 America/New_York"
    pair = calendar(frequency="weekly", days_of_week=["saturday", "sunday"])
    assert label({"trigger_type": "interval", "schedule": pair}) == "Saturdays and Sundays 08:00 America/New_York"
    assert label({"trigger_type": "interval", "schedule": calendar(time_of_day="09:30", timezone="Europe/London")}) == "Daily 09:30 Europe/London"
    weekdays = calendar(frequency="weekdays", time_of_day="07:00", timezone="Asia/Tokyo")
    assert label({"trigger_type": "interval", "schedule": weekdays}) == "Weekdays 07:00 Asia/Tokyo"
    assert label({"trigger_type": "file_sync", "schedule": weekdays}) == "Monitor File Sync: Weekdays 07:00 Asia/Tokyo"
    month_end = calendar(frequency="monthly", day_of_month=31, time_of_day="06:00", timezone="UTC")
    assert label({"trigger_type": "interval", "schedule": month_end}) == "Monthly on day 31 (or last day), 06:00 UTC"
    mid_month = calendar(frequency="monthly", day_of_month=15, time_of_day="06:00", timezone="UTC")
    assert label({"trigger_type": "interval", "schedule": mid_month}) == "Monthly on day 15, 06:00 UTC"
    assert label({"trigger_type": "manual", "schedule": weekly}) == "Manual"
    assert not unexpected
    assert not errors
