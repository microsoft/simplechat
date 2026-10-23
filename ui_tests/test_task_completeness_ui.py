# test_task_completeness_ui.py
"""Classic/V2 admin and real-component completeness outcome coverage.

Version: 0.261.380
Implemented in: 0.261.380
Uses existing Python Azure Playwright-compatible fixtures and synthetic API data.
"""

import sys
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from v2_admin_settings import connect_options  # noqa: F401
from test_v2_orchestration_recovery import (
    recovery_ui, mount_recovery, editor_assets, editor_browser,  # noqa: F401
)
from test_admin_orchestration_actions import orchestration_admin, _open_orchestration  # noqa: F401


pytestmark = pytest.mark.ui
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("scope,pane", [
    ("workflow", "workflow"), ("chat_orchestration", "chat-orchestration"),
])
@pytest.mark.parametrize("width", [390, 1280])
def test_classic_completeness_defaults_and_zero_submit(page, scope, pane, width):
    environment = Environment(
        loader=FileSystemLoader(ROOT / "application" / "single_app" / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    markup = environment.get_template(f"admin/_panes/{pane}.html").render(
        settings={}, admin_landing_tab=pane, orchestration_capabilities=[],
        orchestration_selected_capabilities=[],
    )
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(f'<form id="settings">{markup}</form>')
    toggle = page.locator(f"#enable_{scope}_completeness_check")
    limit = page.locator(f"#{scope}_completeness_max_corrections")
    expect(toggle).to_be_checked()
    expect(limit).to_have_value("2")
    limit.fill("0")
    toggle.uncheck()
    values = page.evaluate("() => Object.fromEntries(new FormData(document.querySelector('form')))")
    assert values[f"{scope}_completeness_max_corrections"] == "0"
    assert f"enable_{scope}_completeness_check" not in values


def test_v2_admin_correction_limit_and_opt_out_roundtrip(orchestration_admin):
    fixture = orchestration_admin
    page = fixture.page
    _open_orchestration(fixture)
    page.get_by_role("button", name="All settings", exact=True).click()
    toggle = page.get_by_role("checkbox", name="Check Answer Completeness", exact=False)
    expect(toggle).to_be_checked()
    page.get_by_label("Maximum Answer Corrections", exact=True).fill("0")
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)
    assert fixture.settings["chat_orchestration_completeness_max_corrections"] == 0
    page.get_by_text("Check Answer Completeness", exact=True).click()
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)
    assert fixture.settings["enable_chat_orchestration_completeness_check"] is False
    fixture.assert_clean()


@pytest.mark.parametrize("status,label", [
    ("complete", "Corrected and complete"),
    ("incomplete", "Incomplete"),
    ("verification_unavailable", "Verification unavailable"),
])
@pytest.mark.parametrize("width", [390, 1440])
def test_saved_report_is_visible_accessible_and_inert(recovery_ui, status, label, width):
    page, api = recovery_ui
    page.set_viewport_size({"width": width, "height": 900})
    api.finish(api.plan["run_id"])
    api.steps[api.plan["run_id"]][1]["task_completeness"] = {
        "version": 1, "status": status, "corrections": 2, "max_corrections": 2,
        "checks": 3, "requirements": [{
            "id": "fact", "requirement": "<img src=x onerror=window.unsafeExecuted=true>",
            "status": "missing", "reason": "Requested date omitted.",
        }],
    }
    mount_recovery(page, api, saved=True)
    page.get_by_role("button", name="Review saved attempt").first.click()
    report = page.get_by_test_id("task-completeness")
    expect(report).to_contain_text(label)
    summary = report.locator("summary")
    summary.focus()
    page.keyboard.press("Enter")
    expect(report.get_by_text("Requested date omitted.", exact=True)).to_be_visible()
    expect(report.locator("img")).to_have_count(0)
    assert page.evaluate("() => window.unsafeExecuted === undefined")
    request_count = len(api.calls("/run"))
    page.evaluate("(id) => window.OrchHarness.resume.resumeOrchestrationForConversation(id)", api.plan["conversation_id"])
    assert len(api.calls("/run")) == request_count


def test_classic_outcome_uses_text_nodes_not_html(page):
    source = ROOT / "application" / "single_app" / "static" / "js" / "workflow" / "completeness.js"
    page.set_content('<main id="report"></main>')
    # Execute the checked-in module body without import/export setup or a live server.
    page.add_script_tag(content=source.read_text(encoding="utf-8").replace("export function", "function", 1))
    page.evaluate("""() => appendWorkflowCompleteness(document.getElementById('report'), [{
        task_name: '<script>bad()</script>',
        workflow_result: {task_completeness: {
            version: 1, status: 'complete', corrections: 2,
            requirements: [{requirement: '<img src=x onerror=bad()>', status: 'satisfied', reason: 'Complete.'}]
        }}
    }])""")
    report = page.get_by_test_id("task-completeness")
    report.locator("summary").click()
    expect(report).to_contain_text("Corrected and complete")
    expect(report.locator("img,script")).to_have_count(0)
