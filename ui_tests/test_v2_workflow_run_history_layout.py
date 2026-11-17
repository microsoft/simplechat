# test_v2_workflow_run_history_layout.py
"""
UI tests for a run in a workflow's run history, in the V2 Workflows workbench, on a phone.
Version: 0.261.445
Implemented in: 0.261.445

A finished personal run's row holds the run's status and times, the Open activity link to the
Workflow Activity page, and, while the administrator's chat-results setting is on, Ask in chat. On a
390 px screen those two links are 214 px between them and the row's content box is 338 px, so a row
that does not wrap pushes the links out past its own edge and squeezes the time down to nothing.
These tests drive the real V2 SPA bundle against the closed workflow API fixture and measure the row
as drawn, at 390 px and at 360 px, where the workbench's own grid clips what spills.
"""

import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

from ui_tests.fixtures.workflow_editor import (  # noqa: E402
    WORKFLOW_ID,
    connect_options,  # noqa: F401
    workflow_ui,  # noqa: F401
)
from ui_tests.fixtures.workflow_workbench import open_workflow_runs  # noqa: E402


pytestmark = pytest.mark.ui

QUARTERLY = "Quarterly review workflow"
RUNS = [
    # Finished with both times: the longest row there is.
    {
        "id": "run-2026-09-16-finished", "workflow_id": WORKFLOW_ID, "status": "completed",
        "trigger_source": "manual", "definition_version": 2,
        "started_at": "2026-09-16T12:00:00Z", "completed_at": "2026-09-16T12:03:00Z",
    },
    {
        "id": "run-2026-09-15-partial", "workflow_id": WORKFLOW_ID, "status": "completed_partial",
        "trigger_source": "manual", "definition_version": 2,
        "started_at": "2026-09-15T09:30:00Z", "completed_at": "2026-09-15T09:41:00Z",
    },
    # Not finished: nothing to ask about, and no end time.
    {
        "id": "run-2026-09-17-running", "workflow_id": WORKFLOW_ID, "status": "running",
        "trigger_source": "manual", "definition_version": 2, "started_at": "2026-09-17T08:00:00Z",
    },
]

# A row's parts in order: the expander, the status, the time, then the links. Each is measured
# against the row and against every ancestor that would clip it, such as the workbench's grid.
MEASURE_ROW = r"""
(item) => {
    const row = item.firstElementChild;
    const rowStyle = getComputedStyle(row);
    const rowRect = row.getBoundingClientRect();
    const clips = [];
    for (let parent = row.parentElement; parent; parent = parent.parentElement) {
        if (getComputedStyle(parent).overflowX !== 'visible') {
            clips.push(parent.getBoundingClientRect());
        }
    }
    const parts = [...row.children].map((child) => {
        const rect = child.getBoundingClientRect();
        return {
            text: (child.textContent || child.getAttribute('aria-label') || '').trim().slice(0, 48),
            left: Math.round(rect.left),
            right: Math.round(rect.right),
            width: Math.round(rect.width),
            textClipped: child.scrollWidth > child.clientWidth + 1,
            clippedByAncestor: clips.some((clip) => rect.right > clip.right + 1 || rect.left < clip.left - 1),
        };
    });
    return {
        overflow: row.scrollWidth - row.clientWidth,
        rowLeft: Math.round(rowRect.left),
        rowRight: Math.round(rowRect.right),
        screen: window.innerWidth,
        parts,
    };
}
"""


def with_chat_results(ui):
    """The administrator's setting that adds Ask in chat to a finished personal run."""
    served = ui._bootstrap

    def bootstrap():
        payload = served()
        payload["features"]["enable_chat_workflow_results"] = True
        return payload

    ui._bootstrap = bootstrap


@pytest.mark.parametrize("width", [390, 360])
@pytest.mark.parametrize("results", [True, False], ids=["with-ask-in-chat", "without-ask-in-chat"])
def test_a_run_row_fits_a_phone_and_keeps_its_time_readable_beside_its_links(workflow_ui, width, results):
    ui, page = workflow_ui, workflow_ui.page
    if results:
        with_chat_results(ui)
    ui.workflow_runs[WORKFLOW_ID] = RUNS
    ui.open("/workspace/workflows", width=width, height=844)
    panel = open_workflow_runs(page, QUARTERLY)

    rows = panel.locator("li", has=page.get_by_role("button", name="Show run task results", exact=True))
    expect(rows).to_have_count(len(RUNS))
    # Open activity on every run, and Ask in chat on the finished ones when it is offered.
    expect(rows.get_by_test_id("v2-workflow-run-activity-link")).to_have_count(len(RUNS))
    expect(rows.locator("[data-workflow-run-ask-in-chat]")).to_have_count(2 if results else 0)

    for index in range(len(RUNS)):
        row = rows.nth(index)
        expect(row.get_by_test_id("v2-workflow-run-activity-link")).to_be_visible()
        measured = row.evaluate(MEASURE_ROW)
        label = f"{width}px, row {index}: {measured}"
        # The row holds its own content: nothing is wider than its box, or than the screen.
        assert measured["overflow"] <= 0, label
        for part in measured["parts"]:
            assert part["left"] >= measured["rowLeft"] - 1, label
            assert part["right"] <= measured["rowRight"] + 1, label
            assert part["right"] <= measured["screen"], label
            assert not part["clippedByAncestor"], label
        # The time, which is what tells one run from another, keeps room to be read and is not cut.
        time = measured["parts"][2]
        assert time["width"] >= 120, label
        assert not time["textClipped"], label
        assert "2026" in time["text"], label
    ui.assert_no_overflow()
