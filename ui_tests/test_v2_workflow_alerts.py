# test_v2_workflow_alerts.py
"""
UI tests for native V2 workflow alert editing, in personal and group workflows.
Version: 0.261.144
Implemented in: 0.261.144

These tests use the real V2 SPA bundle with the closed workflow fixture. Both save routes run
the REAL `normalize_workflow_alert_settings`, compiled from `functions_workflow_alerts.py`. A
refusal returns the route's reviewed 400 (`{"error": ..., "code": "invalid_workflow_alerts"}`), and
the fixture stores the server's normalization. Tests cover, in both scopes:

* authoring each of the seven condition types, checked on the POST body, with the fixture's real
  normalizer accepting it;
* editing, disabling, deleting and reordering rules;
* an untouched alert configuration sent back exactly as loaded;
* a task-scoped rule whose task is removed, flagged before saving, in every alert mode;
* a priority-only record, shown as the server resolves it and not rewritten unless edited;
* the read-only summary for a group member and for an unsupported definition;
* a definition version 1 workflow edited natively, with no classic alerts link;
* a server refusal shown exactly as returned;
* desktop and mobile layout.
"""

import copy
import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

from ui_tests.fixtures.workflow_editor import (  # noqa: E402
    GROUP_ID,
    UNSUPPORTED_WORKFLOW_ID,
    WORKFLOW_ID,
    connect_options,  # noqa: F401
    workflow_record,
    workflow_ui,  # noqa: F401
)


pytestmark = pytest.mark.ui
SCOPES = ("personal", "group")
NAMES = {"personal": "Quarterly review workflow", "group": "Group review workflow"}
ALERT_FIELDS = ("alert_mode", "alert_priority", "alert_rules", "alert_evaluation")
REMOVED_TASK = "Alert rule 1 watches a task that is no longer in this workflow."


def open_workflows(ui, scope):
    if scope == "group":
        ui.open("/groups")
        ui.select_group(GROUP_ID)
    else:
        ui.open("/workspace/workflows")
    expect(ui.page.get_by_role("heading", name="Workflows", exact=True)).to_be_visible()


def target(ui, scope):
    return ui.personal_workflows[WORKFLOW_ID] if scope == "personal" else ui.group_workflows[GROUP_ID]["group-workflow"]


def seed(ui, scope, identifier, **fields):
    """Add a stored workflow to the scope's list."""
    record = workflow_record(identifier, reference_inputs=[], **({"group_id": GROUP_ID} if scope == "group" else {}), **fields)
    (ui.personal_workflows if scope == "personal" else ui.group_workflows[GROUP_ID])[identifier] = record
    return record


def edit(ui, name):
    ui.page.get_by_role("button", name=f"Edit {name}", exact=True).click()
    dialog = ui.page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(dialog).to_be_visible()
    return dialog


def alerts_region(page):
    return page.get_by_role("region", name="Alerts", exact=True)


def rule_rows(page):
    return page.get_by_role("list", name="Alert rules", exact=True).get_by_role("listitem")


def field(page, label):
    return page.get_by_label(label, exact=True)


def save(ui, dialog):
    writes = len(ui.workflow_writes)
    dialog.get_by_role("button", name="Save workflow", exact=True).click()
    expect(dialog).to_have_count(0)
    assert len(ui.workflow_writes) == writes + 1
    return ui.workflow_writes[-1]


def stored(ui, scope, identifier):
    return (ui.personal_workflows if scope == "personal" else ui.group_workflows[GROUP_ID])[identifier]


def rule(name, condition, **fields):
    return {
        "id": f"rule-{name.lower().replace(' ', '-')}", "name": name, "enabled": True, "severity": "medium",
        "delivery": "default", "scope": {"type": "final", "task_id": ""}, "condition": condition, **fields,
    }


@pytest.mark.parametrize("scope", SCOPES)
def test_authoring_every_condition_type_posts_the_server_shape(workflow_ui, scope):
    """Each of the seven condition types is authored natively and accepted by the real normalizer."""
    ui, page = workflow_ui, workflow_ui.page
    open_workflows(ui, scope)
    dialog = edit(ui, NAMES[scope])
    region = alerts_region(page)
    expect(field(region, "When to alert")).to_have_value("off")
    expect(region.get_by_role("button", name="Add alert rule", exact=True)).to_have_count(0)

    field(region, "When to alert").select_option("rules")
    message = "Add at least one alert rule, or choose a different alert mode."
    expect(page.get_by_role("status").filter(has_text=message)).to_be_visible()
    expect(region.get_by_text("No alert rules yet.", exact=False)).to_be_visible()
    for _ in range(8):
        region.get_by_role("button", name="Add alert rule", exact=True).click()
    expect(rule_rows(page)).to_have_count(8)
    expect(page.get_by_role("status").filter(has_text=message)).to_have_count(0)
    expect(region.get_by_role("heading", name="Rule 1: Run status is failed", exact=True)).to_be_visible()

    # 1. Run status, more than one status, with a name.
    region.get_by_role("checkbox", name="Alert rule 1 run statuses: Completed", exact=True).check()
    field(region, "Alert rule 1 name").fill("Run failed or finished")
    expect(region.get_by_role("heading", name="Rule 1: Run failed or finished", exact=True)).to_be_visible()
    # 2. Task status on one specific task.
    field(region, "Alert rule 2 condition").select_option("task_status")
    region.get_by_role("checkbox", name="Alert rule 2 task statuses: Succeeded", exact=True).check()
    field(region, "Alert rule 2 looks at").select_option("task")
    expect(field(region, "Alert rule 2 task")).to_have_value("task-a")
    field(region, "Alert rule 2 task").select_option(label="Summarize evidence")
    # 3. Text values, one per line, across every task, case-sensitive.
    field(region, "Alert rule 3 condition").select_option("text_match")
    field(region, "Alert rule 3 match values").fill("penalty\nbreach")
    field(region, "Alert rule 3 looks at").select_option("any_task")
    region.get_by_role("checkbox", name="Alert rule 3 matches case exactly", exact=True).check()
    # 4. A regex.
    field(region, "Alert rule 4 condition").select_option("text_match")
    field(region, "Alert rule 4 match type").select_option("regex")
    expect(field(region, "Alert rule 4 matches case exactly")).to_have_count(0)
    field(region, "Alert rule 4 regex pattern").fill(r"expires in \d+ days")
    # 5. File Sync: a run-level condition, so there is no scope to choose.
    field(region, "Alert rule 5 condition").select_option("file_sync")
    expect(field(region, "Alert rule 5 looks at")).to_have_count(0)
    field(region, "Alert rule 5 File Sync result").select_option("sync_failed")
    # 6. No output, quiet severity delivered as a pop-up anyway.
    field(region, "Alert rule 6 condition").select_option("no_output")
    field(region, "Alert rule 6 severity").select_option("info")
    expect(rule_rows(page).nth(5).get_by_text("Goes to the notification bell", exact=True)).to_be_visible()
    field(region, "Alert rule 6 delivery").select_option("popup")
    expect(rule_rows(page).nth(5).get_by_text("Opens the pop-up alert", exact=True)).to_be_visible()
    # 7. A model-judged condition, which brings the evaluation error choice.
    evaluation = field(region, "If a model evaluated condition cannot be judged")
    expect(evaluation).to_have_count(0)
    field(region, "Alert rule 7 condition").select_option("model_evaluation")
    field(region, "Alert rule 7 model condition").fill("Any certificate expires within 14 days.")
    expect(evaluation).to_have_value("skip")
    evaluation.select_option("alert")
    # 8. An agent signal.
    field(region, "Alert rule 8 condition").select_option("agent_signal")
    field(region, "Alert rule 8 signal name").fill("expiring")
    field(region, "Alert rule 8 minimum signal severity").select_option("high")

    body = save(ui, dialog).body
    assert not ui.alert_refusals
    assert body["alert_mode"] == "rules"
    assert body["alert_priority"] == "none"
    assert body["alert_evaluation"] == {"on_error": "alert"}
    sent = body["alert_rules"]
    assert [item["condition"] for item in sent] == [
        {"type": "run_status", "statuses": ["failed", "completed"]},
        {"type": "task_status", "statuses": ["failed", "succeeded"]},
        {"type": "text_match", "mode": "contains_any", "values": ["penalty", "breach"], "case_sensitive": True},
        {"type": "text_match", "mode": "regex", "values": [], "case_sensitive": False, "pattern": r"expires in \d+ days"},
        {"type": "file_sync", "outcome": "sync_failed"},
        {"type": "no_output"},
        {"type": "model_evaluation", "prompt": "Any certificate expires within 14 days."},
        {"type": "agent_signal", "signal_name": "expiring", "min_severity": "high"},
    ]
    assert [item["scope"] for item in sent][:3] == [
        {"type": "final", "task_id": ""}, {"type": "task", "task_id": "task-b"}, {"type": "any_task", "task_id": ""},
    ]
    assert (sent[5]["severity"], sent[5]["delivery"]) == ("info", "popup")
    assert all(item["severity"] == "high" for index, item in enumerate(sent) if index != 5)
    assert len({item["id"] for item in sent}) == 8

    # The fixture stored the real normalizer's output: unnamed rules are named from their condition.
    saved = stored(ui, scope, WORKFLOW_ID if scope == "personal" else "group-workflow")["alert_rules"]
    assert [item["order"] for item in saved] == list(range(1, 9))
    assert [item["name"] for item in saved][:3] == [
        "Run failed or finished", "Task status is failed, succeeded", "Output text contains any of penalty, breach",
    ]


@pytest.mark.parametrize("scope", SCOPES)
def test_editing_disabling_deleting_and_reordering_rules(workflow_ui, scope):
    """Row controls change only the draft, and the POST carries the result without dropping fields."""
    ui, page = workflow_ui, workflow_ui.page
    target(ui, scope).update(
        alert_mode="rules", alert_priority="none", alert_evaluation={"on_error": "skip"},
        alert_rules=[
            rule("Run failed", {"type": "run_status", "statuses": ["failed"]}, severity="high", order=1),
            rule("Risk", {"type": "text_match", "mode": "contains_any", "values": ["penalty"], "case_sensitive": False},
                 order=2, x_note={"kept": True}),
            rule("Silent run", {"type": "no_output"}, order=3),
        ],
    )
    open_workflows(ui, scope)
    dialog = edit(ui, NAMES[scope])
    region = alerts_region(page)
    expect(rule_rows(page)).to_have_count(3)
    expect(region.get_by_role("button", name="Move alert rule 1 up", exact=True)).to_be_disabled()
    expect(region.get_by_role("button", name="Move alert rule 3 down", exact=True)).to_be_disabled()

    region.get_by_role("button", name="Move alert rule 3 up", exact=True).click()
    expect(region.get_by_role("heading", name="Rule 2: Silent run", exact=True)).to_be_visible()
    region.get_by_role("button", name="Remove alert rule 1", exact=True).click()
    expect(rule_rows(page)).to_have_count(2)
    expect(region.get_by_role("heading", name="Rule 1: Silent run", exact=True)).to_be_visible()
    expect(region.get_by_role("heading", name="Rule 2: Risk", exact=True)).to_be_visible()
    field(region, "Alert rule 2 severity").select_option("critical")
    region.get_by_role("checkbox", name=re.compile(r"^Rule 1 enabled")).uncheck(force=True)
    expect(rule_rows(page).nth(0).get_by_text("Opens the pop-up alert · Disabled", exact=True)).to_be_visible()

    body = save(ui, dialog).body
    assert [item["id"] for item in body["alert_rules"]] == ["rule-silent-run", "rule-risk"]
    assert body["alert_rules"][0]["enabled"] is False
    assert body["alert_rules"][1]["severity"] == "critical"
    # The client never drops a rule field; the server's allow-list then discards it (M6B C2).
    assert body["alert_rules"][1]["x_note"] == {"kept": True}
    saved = stored(ui, scope, WORKFLOW_ID if scope == "personal" else "group-workflow")["alert_rules"]
    assert [(item["id"], item["order"], item["enabled"]) for item in saved] == [
        ("rule-silent-run", 1, False), ("rule-risk", 2, True),
    ]
    assert "x_note" not in saved[1]


@pytest.mark.parametrize("scope", SCOPES)
def test_an_untouched_alert_configuration_is_sent_exactly_as_loaded(workflow_ui, scope):
    ui, page = workflow_ui, workflow_ui.page
    target(ui, scope).update(
        alert_mode="rules", alert_priority="low", alert_evaluation={"on_error": "alert"},
        alert_rules=[
            rule("Summary risk", {"type": "text_match", "mode": "contains_any", "values": ["penalty"], "case_sensitive": False},
                 scope={"type": "task", "task_id": "task-b"}, order=1, x_note="kept"),
            rule("Judged risk", {"type": "model_evaluation", "prompt": "Any risk?"}, order=2),
        ],
    )
    loaded = copy.deepcopy(target(ui, scope))
    open_workflows(ui, scope)
    dialog = edit(ui, NAMES[scope])
    expect(rule_rows(page)).to_have_count(2)
    field(page, "Description").first.fill("Only the description changed.")

    body = save(ui, dialog).body
    assert body["description"] == "Only the description changed."
    for name in ALERT_FIELDS:
        assert body[name] == loaded[name], name
    assert not ui.alert_refusals


@pytest.mark.parametrize("scope", SCOPES)
def test_a_rule_watching_a_removed_task_is_flagged_before_saving(workflow_ui, scope):
    """M6B C5: removing a watched task used to fail every save with the generic 400."""
    ui, page = workflow_ui, workflow_ui.page
    target(ui, scope).update(
        alert_mode="rules", alert_priority="none", alert_evaluation={"on_error": "skip"},
        alert_rules=[rule("Summary failed", {"type": "task_status", "statuses": ["failed"]},
                          scope={"type": "task", "task_id": "task-b"}, order=1)],
    )
    open_workflows(ui, scope)
    dialog = edit(ui, NAMES[scope])
    region = alerts_region(page)
    expect(field(region, "Alert rule 1 task")).to_have_value("task-b")
    dialog.get_by_role("button", name="Remove Summarize evidence", exact=True).click()

    row = rule_rows(page).nth(0)
    expect(row.get_by_role("alert")).to_have_text(REMOVED_TASK)
    expect(field(region, "Alert rule 1 task")).to_have_value("task-b")
    expect(field(region, "Alert rule 1 task").locator("option:checked")).to_have_text("Removed task (review)")
    expect(page.get_by_role("status").filter(has_text=REMOVED_TASK)).to_be_visible()
    requests = len(ui.requests)
    dialog.get_by_role("button", name="Save workflow", exact=True).click()
    expect(dialog.get_by_role("alert").filter(has_text=REMOVED_TASK).first).to_be_visible()
    assert not [entry for entry in ui.requests[requests:] if entry.method == "POST"]

    field(region, "Alert rule 1 task").select_option(label="Collect evidence")
    expect(row.get_by_role("alert")).to_have_count(0)
    body = save(ui, dialog).body
    assert body["alert_rules"][0]["scope"] == {"type": "task", "task_id": "task-a"}
    assert [task["id"] for task in body["tasks"]] == ["task-a"]


def test_rules_are_kept_and_still_checked_when_alerts_are_off(workflow_ui):
    """M6B C6: the server validates saved rules in every mode, so the editor does too."""
    ui, page = workflow_ui, workflow_ui.page
    target(ui, "personal").update(
        alert_mode="off", alert_priority="none", alert_evaluation={"on_error": "skip"},
        alert_rules=[rule("Summary failed", {"type": "task_status", "statuses": ["failed"]},
                          scope={"type": "task", "task_id": "task-b"}, order=1)],
    )
    open_workflows(ui, "personal")
    dialog = edit(ui, NAMES["personal"])
    region = alerts_region(page)
    expect(field(region, "When to alert")).to_have_value("off")
    expect(region.get_by_text("These saved rules send alerts only when", exact=False)).to_be_visible()
    expect(region.get_by_role("button", name="Add alert rule", exact=True)).to_have_count(0)
    expect(rule_rows(page)).to_have_count(1)
    dialog.get_by_role("button", name="Remove Summarize evidence", exact=True).click()
    expect(rule_rows(page).nth(0).get_by_role("alert")).to_have_text(REMOVED_TASK)
    region.get_by_role("button", name="Remove alert rule 1", exact=True).click()
    body = save(ui, dialog).body
    assert (body["alert_mode"], body["alert_rules"]) == ("off", [])


@pytest.mark.parametrize("scope", SCOPES)
def test_a_priority_only_record_is_resolved_but_not_rewritten(workflow_ui, scope):
    """The editor shows the server's legacy rules; only an alert edit writes all four fields."""
    ui, page = workflow_ui, workflow_ui.page
    target(ui, scope)["alert_priority"] = "high"
    open_workflows(ui, scope)
    dialog = edit(ui, NAMES[scope])
    region = alerts_region(page)
    expect(field(region, "When to alert")).to_have_value("rules")
    expect(region.get_by_role("heading", name="Rule 1: Run failed", exact=True)).to_be_visible()
    expect(region.get_by_role("heading", name="Rule 2: Run completed", exact=True)).to_be_visible()
    field(page, "Description").first.fill("Untouched alerts.")

    body = save(ui, dialog).body
    assert body["alert_priority"] == "high"
    assert not {"alert_mode", "alert_rules", "alert_evaluation"} & set(body)
    # The server, not the client, turns the priority into the legacy rules on any save (M6B C3).
    identifier = WORKFLOW_ID if scope == "personal" else "group-workflow"
    materialized = stored(ui, scope, identifier)
    assert materialized["alert_mode"] == "rules"
    assert [item["id"] for item in materialized["alert_rules"]] == ["legacy-run-failed", "legacy-run-completed"]

    dialog = edit(ui, NAMES[scope])
    field(region, "When to alert").select_option("every_run")
    expect(field(region, "Pop-up alert priority")).to_have_value("high")
    body = save(ui, dialog).body
    assert (body["alert_mode"], body["alert_priority"]) == ("every_run", "high")
    assert body["alert_rules"] == materialized["alert_rules"]
    assert body["alert_evaluation"] == {"on_error": "skip"}
    assert stored(ui, scope, identifier)["alert_mode"] == "every_run"


def test_readers_keep_the_summary(workflow_ui):
    """A group member, and a definition V2 cannot save, see the read-only summary and no editor."""
    ui, page = workflow_ui, workflow_ui.page
    ui.group_can_manage = False
    target(ui, "group")["alert_priority"] = "medium"
    open_workflows(ui, "group")
    page.get_by_role("button", name="View Group review workflow", exact=True).click()
    region = alerts_region(page)
    expect(region.get_by_text("Only when a condition is met", exact=True)).to_be_visible()
    expect(region.get_by_text("Medium priority", exact=True)).to_be_visible()
    expect(region.get_by_text("2 rules", exact=True)).to_be_visible()
    expect(region.get_by_role("combobox")).to_have_count(0)
    expect(region.get_by_role("button")).to_have_count(0)

    ui.group_can_manage = True
    ui.personal_workflows[UNSUPPORTED_WORKFLOW_ID]["alert_mode"] = "every_run"
    ui.personal_workflows[UNSUPPORTED_WORKFLOW_ID]["alert_priority"] = "low"
    open_workflows(ui, "personal")
    page.get_by_role("button", name="Edit Future workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="definition version 4")).to_be_visible()
    expect(region.get_by_text("On every run", exact=True)).to_be_visible()
    expect(region.get_by_text("Low priority", exact=True)).to_be_visible()
    expect(region.get_by_role("combobox")).to_have_count(0)
    assert not ui.workflow_writes


@pytest.mark.parametrize("scope", SCOPES)
def test_version_one_workflows_edit_alerts_natively_without_a_classic_link(workflow_ui, scope):
    """M6B D3: native editing replaces M6's classic alerts link; a V2 save converts the workflow."""
    ui, page = workflow_ui, workflow_ui.page
    seed(ui, scope, "legacy-alerts", name="Legacy alerts", definition_version=1, alert_priority="medium")
    open_workflows(ui, scope)
    dialog = edit(ui, "Legacy alerts")
    region = alerts_region(page)
    expect(dialog.get_by_role("button", name=re.compile("classic", re.IGNORECASE))).to_have_count(0)
    expect(dialog.get_by_text("classic", exact=False)).to_have_count(0)
    expect(field(region, "When to alert")).to_have_value("rules")
    field(region, "Alert rule 2 severity").select_option("critical")

    body = save(ui, dialog).body
    assert body["definition_version"] == 2
    assert body["alert_mode"] == "rules"
    assert [(item["id"], item["severity"]) for item in body["alert_rules"]] == [
        ("legacy-run-failed", "high"), ("legacy-run-completed", "critical"),
    ]
    assert stored(ui, scope, "legacy-alerts")["alert_rules"][1]["severity"] == "critical"


def test_refusals_the_client_cannot_check_show_the_server_message_as_returned(workflow_ui):
    """Python-only regex syntax is left to the server's reviewed 400, which the editor shows as sent."""
    ui, page = workflow_ui, workflow_ui.page
    open_workflows(ui, "personal")
    dialog = edit(ui, NAMES["personal"])
    region = alerts_region(page)
    field(region, "When to alert").select_option("rules")
    region.get_by_role("button", name="Add alert rule", exact=True).click()
    field(region, "Alert rule 1 condition").select_option("text_match")
    field(region, "Alert rule 1 match type").select_option("regex")

    # A nested quantifier is caught before any request.
    nested = "Alert rule 1 regex pattern uses nested quantifiers, which are not allowed."
    field(region, "Alert rule 1 regex pattern").fill("(a+)+")
    expect(rule_rows(page).nth(0).get_by_role("alert")).to_have_text(nested)
    requests = len(ui.requests)
    dialog.get_by_role("button", name="Save workflow", exact=True).click()
    expect(dialog.get_by_role("alert").filter(has_text=nested).first).to_be_visible()
    assert not [entry for entry in ui.requests[requests:] if entry.method == "POST"]

    # A pattern only Python refuses reaches the server, and its reviewed message is shown unchanged.
    invalid = "Alert rule 1 regex pattern is not a valid regular expression."
    field(region, "Alert rule 1 regex pattern").fill("(unclosed")
    expect(rule_rows(page).nth(0).get_by_role("alert")).to_have_count(0)
    dialog.get_by_role("button", name="Save workflow", exact=True).click()
    expect(dialog.get_by_role("alert").filter(has_text=invalid)).to_be_visible()
    assert ui.alert_refusals == [invalid]
    assert not ui.workflow_writes
    expect(field(region, "Alert rule 1 regex pattern")).to_have_value("(unclosed")

    field(region, "Alert rule 1 regex pattern").fill("(closed)")
    body = save(ui, dialog).body
    assert body["alert_rules"][0]["condition"]["pattern"] == "(closed)"


def test_the_rule_limit_disables_adding(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    target(ui, "personal").update(
        alert_mode="rules", alert_priority="none", alert_evaluation={"on_error": "skip"},
        alert_rules=[rule(f"Rule {index}", {"type": "no_output"}, order=index) for index in range(1, 21)],
    )
    open_workflows(ui, "personal")
    edit(ui, NAMES["personal"])
    region = alerts_region(page)
    expect(rule_rows(page)).to_have_count(20)
    expect(region.get_by_role("button", name="Add alert rule", exact=True)).to_be_disabled()
    expect(region.get_by_role("status").filter(has_text="A workflow can have up to 20 alert rules.")).to_be_visible()


@pytest.mark.parametrize("theme,width,height", [("light", 1440, 900), ("dark", 390, 844)], ids=["desktop-light", "mobile-dark"])
def test_the_alert_editor_fits_desktop_and_mobile(workflow_ui, theme, width, height):
    ui, page = workflow_ui, workflow_ui.page
    target(ui, "group").update(
        alert_mode="rules", alert_priority="none", alert_evaluation={"on_error": "skip"},
        alert_rules=[
            rule("A long rule name that must wrap rather than widen the dialog on a narrow screen",
                 {"type": "text_match", "mode": "contains_any", "values": ["penalty"], "case_sensitive": False},
                 scope={"type": "task", "task_id": "task-b"}, order=1),
            rule("Judged risk", {"type": "model_evaluation", "prompt": "Any risk?"}, order=2),
        ],
    )
    ui.open("/groups", theme=theme, width=width, height=height)
    ui.select_group(GROUP_ID)
    edit(ui, NAMES["group"])
    region = alerts_region(page)
    region.scroll_into_view_if_needed()
    expect(rule_rows(page)).to_have_count(2)
    expect(field(region, "If a model evaluated condition cannot be judged")).to_be_visible()
    # Text controls scroll their own value by design; every other element must fit the dialog.
    clipped = page.evaluate("""() => [...document.querySelectorAll('[role="dialog"] *')]
        .filter((element) => !['INPUT', 'TEXTAREA'].includes(element.tagName))
        .filter((element) => element.scrollWidth > element.clientWidth + 1 && getComputedStyle(element).overflowX !== 'visible')
        .map((element) => element.tagName)""")
    assert clipped == [], clipped
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    # The long name wraps in the rule heading instead of widening the row.
    heading = region.get_by_role("heading", name=re.compile(r"^Rule 1: A long rule name"))
    assert heading.evaluate("(element) => element.scrollWidth <= element.clientWidth")
