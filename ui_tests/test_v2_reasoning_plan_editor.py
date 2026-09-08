# test_v2_reasoning_plan_editor.py
"""
Real-editor regression for original selections and reasoning correction metadata.
Version: 0.261.104
Implemented in: 0.261.104

Uses the existing editor harness and production CSS with mocked HTTP boundaries.
The separate module keeps its Playwright lifetime independent of Composer fixtures.
"""

import pytest
from playwright.sync_api import expect

import test_v2_orchestration_plan_editor as editor_tests
from test_v2_orchestration_plan_editor import (  # noqa: F401
    connect_options, editor_assets, editor_browser, editor_ui,
)

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("requirements", [None, [], ["deep_research"], ["agent_invoke"]])
def test_editor_preserves_original_requirements_and_reasoning_through_web_revision(editor_ui, requirements):
    page, api = editor_ui
    plan = api.add()
    plan["inputs"]["web"] = True
    if requirements is not None:
        plan["inputs"]["required_capabilities"] = requirements
    expected_requirements = requirements if requirements is not None else []
    plan["reasoning_adjustments"] = [{
        "requested_effort": "minimal", "effective_effort": "low", "mode": "explicit",
        "adjustment_reason": "reasoning_effort_unsupported",
        "model_name": "gpt-5.6-luna", "stage": "planner",
    }]
    editor_tests.mount(page, api)
    dialog = editor_tests.open_editor(page)
    editor_tests.ask(page, "Add a Web search for current information.")
    editor_tests.wait_revision(page, 1)
    current = editor_tests.state(page)
    assert current["plan"]["inputs"]["required_capabilities"] == expected_requirements
    assert current["editor"]["state"]["plan"]["inputs"]["required_capabilities"] == expected_requirements
    assert current["plan"]["inputs"]["web"] is True
    assert any(step["capability_id"] == "web_search" for step in current["plan"]["steps"])
    assert current["plan"]["reasoning_adjustments"] == plan["reasoning_adjustments"]
    expect(dialog.get_by_role("status").filter(has_text="Minimal could not be used")).to_be_visible()
    assert current["plan"]["revision"] == 1
