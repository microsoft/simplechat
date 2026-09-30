# test_v2_workflow_flow_canvas_stability.py
"""
Offline real-bundle browser regressions for a stable workflow Flow canvas (#1573).
Version: 0.261.205
Implemented in: 0.261.205

A re-render that doesn't change the diagram must not rebuild the React Flow nodes. New node
objects reset React Flow's measured handle bounds, so every edge is removed from the page
until the nodes are measured again, and a later rebuild can leave the edges missing. These
tests watch the canvas with a MutationObserver while the editor saves, fails a save and takes
typing outside the diagram, and while a read-only run Flow receives runtime polls. No node or
control edge may be removed or added. The canvas handlers must still reach the latest editor
state afterwards: pointer and keyboard selection, collapse, keyboard navigation and a focus
request.

A focus or selection change rebuilds only the nodes it changes, and those keep their measured
handles, so no control edge leaves the page. Rapid focus and selection changes, which rebuild
the same nodes again before React Flow measures them, must leave every control edge drawn once
the canvas settles.

Reuses the closed Flow harnesses, the local production assets and the real compiler. No live
app, model, workflow admission, publication or Azure browser is contacted. Run with
PLAYWRIGHT_SERVICE_URL='' and PYTHONPATH including ui_tests/fixtures.
"""

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

# The shared fixtures import pure application helpers after setting their paths.
from ui_tests import test_v2_workflow_flow_authoring as authoring
from ui_tests.fixtures.workflow_flow import FLOW_NAME, FLOW_RUN_ID, FLOW_WORKFLOW_ID, workflow_flow_ui  # noqa: F401
from ui_tests.test_v2_workflow_flow_authoring import authoring_ui, connect_options  # noqa: F401


pytestmark = pytest.mark.ui

EDGE = ".workflow-flow-control-edge"

# Counts every control edge and React Flow node removed from or added to the canvas, including
# those inside a removed or added element, and the fewest control edges the canvas showed.
INSTALL_PROBE = """
(root) => {
    window.__flowCanvasChurn?.observer.disconnect();
    const selectors = { edges: '.workflow-flow-control-edge', nodes: '.react-flow__node' };
    const count = (element, selector) => element.nodeType === Node.ELEMENT_NODE
        ? Number(element.matches(selector)) + element.querySelectorAll(selector).length : 0;
    const state = {
        removedEdges: 0, addedEdges: 0, removedNodes: 0, addedNodes: 0,
        fewestEdges: root.querySelectorAll(selectors.edges).length,
    };
    const record = (mutations) => {
        for (const mutation of mutations) {
            for (const element of mutation.removedNodes) {
                state.removedEdges += count(element, selectors.edges);
                state.removedNodes += count(element, selectors.nodes);
            }
            for (const element of mutation.addedNodes) {
                state.addedEdges += count(element, selectors.edges);
                state.addedNodes += count(element, selectors.nodes);
            }
        }
        state.fewestEdges = Math.min(state.fewestEdges, root.querySelectorAll(selectors.edges).length);
    };
    const observer = new MutationObserver(record);
    observer.observe(root, { childList: true, subtree: true });
    window.__flowCanvasChurn = { observer, record, state };
    return state.fewestEdges;
}
"""

READ_PROBE = """
() => {
    const probe = window.__flowCanvasChurn;
    probe.record(probe.observer.takeRecords());
    return { ...probe.state };
}
"""

NEXT_FRAMES = "() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))"

# Returns every drawn control edge whose ends are not on a node handle, measured the way React
# Flow measures handles. An edge drawn from stale handle bounds misses its handle.
DETACHED_EDGES = """
(root) => {
    const viewport = root.querySelector('.react-flow__viewport');
    const zoom = new DOMMatrixReadOnly(getComputedStyle(viewport).transform).m22;
    const anchors = { source: [], target: [] };
    for (const node of root.querySelectorAll('.react-flow__node')) {
        const [x, y] = node.style.transform.match(/-?[\\d.]+/g).map(Number);
        const bounds = node.getBoundingClientRect();
        for (const handle of node.querySelectorAll('.react-flow__handle')) {
            const rect = handle.getBoundingClientRect();
            const left = x + (rect.left - bounds.left) / zoom;
            const top = y + (rect.top - bounds.top) / zoom;
            const width = handle.offsetWidth;
            const height = handle.offsetHeight;
            const side = handle.dataset.handlepos;
            const point = side === 'top' ? [left + width / 2, top]
                : side === 'bottom' ? [left + width / 2, top + height]
                    : side === 'left' ? [left, top + height / 2] : [left + width, top + height / 2];
            anchors[handle.classList.contains('source') ? 'source' : 'target'].push(point);
        }
    }
    const near = (points, [x, y]) => points.some(([px, py]) => Math.abs(px - x) <= 0.5 && Math.abs(py - y) <= 0.5);
    return [...root.querySelectorAll('.workflow-flow-control-edge')].flatMap((edge) => {
        const path = edge.querySelector('.react-flow__edge-path').getAttribute('d');
        const numbers = path.match(/-?\\d*\\.?\\d+(?:e[-+]?\\d+)?/gi).map(Number);
        const start = numbers.slice(0, 2);
        const end = numbers.slice(-2);
        return near(anchors.source, start) && near(anchors.target, end) ? [] : [{ edge: edge.dataset.id, start, end }];
    });
}
"""

# The node buttons a pointer can reach at their centers, in canvas order.
CLICKABLE_NODES = """
(root) => [...root.querySelectorAll('button[data-workflow-node-id]')].flatMap((button) => {
    const bounds = button.getBoundingClientRect();
    const x = bounds.left + bounds.width / 2;
    const y = bounds.top + bounds.height / 2;
    return button.contains(document.elementFromPoint(x, y)) ? [{ id: button.dataset.workflowNodeId, x, y }] : [];
})
"""


def settle(page, delay=400):
    """Leave time for React effects, a debounced preview and a ResizeObserver pass to happen."""
    page.evaluate(NEXT_FRAMES)
    page.wait_for_timeout(delay)
    page.evaluate(NEXT_FRAMES)


def install_probe(page, view):
    settle(page)
    edges = view.locator(".react-flow").evaluate(INSTALL_PROBE)
    assert edges > 0, "The canvas must show control edges before it is watched."
    return edges


def assert_no_churn(page, edges, moment):
    settle(page)
    churn = page.evaluate(READ_PROBE)
    assert churn == {
        "removedEdges": 0, "addedEdges": 0, "removedNodes": 0, "addedNodes": 0, "fewestEdges": edges,
    }, f"The Flow canvas rebuilt its nodes {moment}: {churn}"


def assert_edges_meet_handles(view, moment):
    settle(view.page)
    detached = view.locator(".react-flow").evaluate(DETACHED_EDGES)
    assert detached == [], f"Control edges miss their node handles {moment}: {detached}"


def is_save(request):
    return request.method == "POST" and urlsplit(request.url).path == "/api/user/workflows"


def compiled_status(view):
    return view.get_by_role("status").filter(has_text=re.compile(r"^Compiler-validated draft\."))


def node_order(view):
    return view.locator(".react-flow__node").evaluate_all("nodes => nodes.map((node) => node.dataset.id)")


def open_compiled_flow(ui):
    editor = authoring.open_editor(ui)
    view = authoring.switch_surface(editor, "Flow")
    authoring.expect_compiled(view)
    return view


@pytest.mark.parametrize("status", [400, 409, 503])
def test_non_diagram_rerenders_keep_every_flow_node_and_edge_mounted(authoring_ui, status):
    ui, page = authoring_ui, authoring_ui.page
    editor = authoring.open_editor(ui)
    view = authoring.switch_surface(editor, "Flow")
    fields = authoring.select_node(view, "evaluate")
    fields.get_by_label("Task name", exact=True).fill("Kept while the editor re-renders")
    fields.get_by_label("Instructions", exact=True).fill("Keep this unsaved instruction while the editor re-renders.")
    authoring.open_details(fields)
    authoring.expect_compiled(view)
    edges = install_probe(page, view)
    previews = len(ui.preview_requests)

    # Saving and a failed save re-render the editor without changing the diagram.
    if status == 409:
        ui.mutate_revision(FLOW_WORKFLOW_ID)
    else:
        ui.reject_next("POST", "/api/user/workflows", status=status, error="Fictional authoring save was rejected.")
    ui.hold_save_response = True
    with page.expect_request(is_save):
        editor.get_by_role("button", name="Save workflow", exact=True).click()
    try:
        expect(editor.get_by_role("button", name="Saving…", exact=True)).to_be_disabled()
        assert_no_churn(page, edges, "while saving")
    finally:
        ui.release_save_responses()
    expect(editor.get_by_role("alert").first).to_be_visible()
    expect(editor.get_by_role("button", name="Save workflow", exact=True)).to_be_enabled()
    assert_no_churn(page, edges, f"after the failed {status} save")

    # The decision field builder changes a field draft, not the previewed definition.
    builder = fields.get_by_label("Decision field name", exact=True)
    builder.click()
    page.keyboard.type("extra")
    expect(builder).to_have_value("extra")
    expect(builder).to_be_focused()
    assert_no_churn(page, edges, "while typing outside the diagram")
    assert len(ui.preview_requests) == previews, "Typing in the field builder must not revalidate the draft."
    expect(compiled_status(view)).to_be_visible()
    expect(fields.get_by_label("Task name", exact=True)).to_have_value("Kept while the editor re-renders")

    # The canvas handlers still reach the latest editor state after those re-renders.
    finish = authoring.node_button(view, "finish")
    finish.focus()
    page.keyboard.press("Enter")
    expect(finish).to_have_attribute("aria-pressed", "true")
    expect(authoring.configuration(view).get_by_text("Canonical ID: finish", exact=True)).to_be_visible()
    choose = authoring.node_button(view, "choose")
    toggle = view.locator(".react-flow__node[data-id='choose'] button.workflow-flow-collapse")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    toggle.focus()
    page.keyboard.press("Enter")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(choose).to_have_attribute("aria-pressed", "true")
    expect(authoring.configuration(view).get_by_text("Canonical ID: choose", exact=True)).to_be_visible()
    choose.focus()
    page.keyboard.press("ArrowRight")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(choose).to_be_focused()
    order = node_order(view)
    following = order[order.index("choose") + 1]
    assert following != "bypass-note", "An expanded If block must list its own regions next."
    page.keyboard.press("ArrowDown")
    expect(authoring.node_button(view, following)).to_be_focused()
    authoring.configuration(view).get_by_role("button", name="Return to selected block", exact=True).click()
    expect(choose).to_be_focused()
    expect(view.locator(EDGE)).to_have_count(edges)
    assert_edges_meet_handles(view, "after the canvas handlers ran")
    assert not ui.workflow_writes


def test_focus_and_selection_changes_keep_control_edges_mounted_and_on_their_handles(authoring_ui):
    ui, page = authoring_ui, authoring_ui.page
    view = open_compiled_flow(ui)
    order = node_order(view)
    assert len(order) > 4
    edges = install_probe(page, view)

    # Focus moves the canvas tab stop, and Enter selects a node, which widens its border.
    authoring.node_button(view, order[0]).focus()
    for key in ("ArrowDown", "Enter", "ArrowDown", "ArrowDown", "Enter", "ArrowUp"):
        page.keyboard.press(key)
        settle(page, 100)
    expect(authoring.node_button(view, order[3])).to_have_attribute("aria-pressed", "true")
    expect(authoring.node_button(view, order[1])).to_have_attribute("aria-pressed", "false")
    expect(authoring.node_button(view, order[2])).to_be_focused()
    assert_no_churn(page, edges, "on focus and selection changes")
    assert_edges_meet_handles(view, "after the selection changed")
    assert not ui.workflow_writes


def test_rapid_focus_and_selection_changes_leave_every_control_edge_drawn(authoring_ui):
    ui, page = authoring_ui, authoring_ui.page
    view = open_compiled_flow(ui)
    order = node_order(view)
    # Fit the view again so the clicks below don't depend on when the initial fit ran.
    view.get_by_role("button", name="Fit Flow", exact=True).click()
    edges = install_probe(page, view)

    # Each click and key rebuilds nodes again before React Flow has measured the last rebuild.
    # The clicks come first: keyboard focus reveals a node at full size, which hides the rest.
    reachable = view.locator(".react-flow").evaluate(CLICKABLE_NODES)
    clicks = (reachable[::2] + reachable[1::2])[:5]
    assert len(clicks) >= 2, f"The fitted canvas must show at least two clickable nodes: {reachable}"
    for click in clicks:
        page.mouse.click(click["x"], click["y"])
    authoring.node_button(view, order[0]).focus()
    for key in ["ArrowDown"] * 6 + ["ArrowUp"] * 6 + ["ArrowDown", "Enter", "ArrowUp", "Enter"] * 2:
        page.keyboard.press(key)
    expect(authoring.node_button(view, order[0])).to_have_attribute("aria-pressed", "true")
    expect(authoring.node_button(view, order[0])).to_be_focused()

    settle(page)
    expect(view.locator(EDGE)).to_have_count(edges)
    assert install_probe(page, view) == edges
    page.wait_for_timeout(1000)
    assert_no_churn(page, edges, "after rapid focus and selection changes settled")
    assert_edges_meet_handles(view, "after rapid focus and selection changes settled")
    assert not ui.workflow_writes


def test_runtime_polls_keep_read_only_flow_nodes_and_edges_mounted(workflow_flow_ui):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    key = ("user", FLOW_WORKFLOW_ID, FLOW_RUN_ID)
    # An active durable run makes the runtime panel poll, with an equal runtime every time.
    ui.workflow_runs[FLOW_WORKFLOW_ID][0]["status"] = "running"
    ui.workflow_runtimes[key]["state"] = "running"
    ui.open("/workspace/workflows")
    row = page.get_by_role("listitem").filter(has=page.get_by_role(
        "button", name=f"View Flow for {FLOW_NAME}", exact=True,
    )).first
    row.get_by_role("button", name="Show run history", exact=True).click()
    row.get_by_role("button", name="Show run task results", exact=True).click()
    row.get_by_role("button", name="Show Flow for this run", exact=True).click()
    view = page.get_by_role("region", name="Workflow Flow", exact=True)
    expect(view.get_by_text("Run's frozen definition", exact=True)).to_be_visible()
    expect(view.get_by_text("Loading bounded execution overlay...", exact=True)).to_have_count(0)
    expect(view.locator(EDGE).first).to_be_attached()
    edges = install_probe(page, view)
    polls = ui.runtime_get_count[key]

    def is_runtime_poll(response):
        return response.request.method == "GET" and urlsplit(response.url).path.endswith(f"/runs/{FLOW_RUN_ID}/runtime")

    for _ in range(2):
        with page.expect_response(is_runtime_poll, timeout=10_000):
            pass
    assert ui.runtime_get_count[key] >= polls + 2
    assert_no_churn(page, edges, "on runtime polls that did not change the run")
    expect(view.get_by_role("alert")).to_have_count(0)
    ui.assert_read_only()
