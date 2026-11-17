#!/usr/bin/env python3
# test_v2_workflow_activity.py
"""
Functional test for the V2 Workflow Activity page (/v2/workflow-activity).
Version: 0.261.448
Implemented in: 0.261.448

This test ensures the V2 page is what the classic `/workflow-activity` page is, in React: it takes the
same query, reads the same snapshot and stream and calls the same cancel route, shows the same header,
buttons and figures, and is opened from every place the classic interface opens workflow activity (the
chat header, a run in a workflow's history, the workflow's own header) as well as from notification
links and Support shortcuts. It ports the contracts of the classic tests:

- test_workflow_activity_view_feature.py: the snapshot the page reads is the one the server builds,
  run through the page's own reader (the Node probes below read server-built snapshots);
- test_workflow_activity_response_preview_toggle.py: the response preview starts closed and opens and
  closes from a labelled button that says what it controls;
- test_workflow_activity_new_tab_navigation.py: the entry points open the page in a new tab, and
  never navigate the tab they are in;
- test_workflow_activity_dark_mode_layout_contract.py: the page is drawn only from theme tokens, so it
  follows the theme, and it lays out in two columns on a wide screen and one under 992 px;
- test_group_workflow_activity_view_gate.py: group activity has its own gate, independent of personal
  workflows (the gate itself is run in test_v2_workflow_activity_gates.py).

The Node probes execute the real TypeScript modules; the browser behaviour is in
ui_tests/test_v2_workflow_activity.py.
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

LOGIC_TEST = REPO_ROOT / "functional_tests" / "test_v2_workflow_activity_logic.mjs"
ROUTING_TEST = REPO_ROOT / "functional_tests" / "test_v2_workflow_run_link_routing.mjs"
SNAPSHOT_FILE = V2_DIR / "node_modules" / ".cache-workflow-activity-snapshots.json"

OWN_FILES = (
    "pages/WorkflowActivityPage.tsx",
    "lib/workflowActivity.ts",
    "lib/workflowActivitySnapshot.ts",
    "lib/workflowActivityStream.ts",
    "components/workflowActivity/ActivityPendingAction.tsx",
    "components/workflowActivity/ActivityStatusBadge.tsx",
    "components/workflowActivity/WorkflowActivityDetail.tsx",
    "components/workflowActivity/WorkflowActivityHero.tsx",
    "components/workflowActivity/WorkflowActivityLinks.tsx",
    "components/workflowActivity/WorkflowActivityTimeline.tsx",
    "components/workflowActivity/useWorkflowActivity.ts",
)


def read_v2(relative):
    return (V2_SRC / relative).read_text(encoding="utf-8")


def read_app(relative):
    return (APP_ROOT / relative).read_text(encoding="utf-8")


def own_sources():
    return {name: read_v2(name) for name in OWN_FILES}


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.448")
    print("  ok  application version is at or beyond the implementing release")


def test_the_page_is_routed_and_every_entry_point_is_wired():
    app = read_v2("App.tsx")
    assert "import { WorkflowActivityPage } from './pages/WorkflowActivityPage';" in app
    assert '<Route path="/workflow-activity" element={<WorkflowActivityPage />} />' in app

    # Where the classic interface opens workflow activity, V2 now does too.
    chat = read_v2("pages/ChatPage.tsx")
    assert "<WorkflowActivityHeaderLink conversationId={activeConversationId} sources={[metadata, active]} />" in chat
    assert chat.index("<WorkflowActivityHeaderLink") < chat.index('aria-label="View conversation details"')

    history = read_v2("components/workflows/WorkflowRunHistory.tsx")
    assert "<WorkflowRunActivityLink scope={scope} workflowId={workflowId} run={run} />" in history
    assert history.index("<WorkflowRunActivityLink") < history.index("<WorkflowRunAskInChat")

    workbench = read_v2("components/workflows/WorkflowWorkbenchDetail.tsx")
    assert "<WorkflowActivityLink scope={scope} workflow={workflow} />" in workbench
    print("  ok  the route and the three entry points are in place")


def test_the_page_reads_the_query_and_the_endpoints_the_classic_page_reads():
    classic = read_app("static/js/workflow/workflow-activity.js")
    page = read_v2("lib/workflowActivity.ts")

    # The five parameters of the page's address.
    for name in ("conversationId", "workflowId", "runId", "scope", "groupId"):
        assert f'"{name}"' in classic or f"'{name}'" in classic, f"classic no longer reads {name}"
        assert name in page, f"the V2 page does not read {name}"
    # The names the endpoints take, and the endpoints themselves.
    for name in ("conversation_id", "workflow_id", "run_id", "group_id"):
        assert name in classic and f"'{name}'" in page, name
    assert '"/api/group/workflows/activity"' in classic and "'/api/group/workflows/activity'" in page
    assert '"/api/user/workflows/activity"' in classic and "'/api/user/workflows/activity'" in page
    assert "/stream" in classic and "`${base}/stream`" in page

    # The classic page's own live statuses are the ones the V2 page listens for.
    classic_statuses = re.search(r"WORKFLOW_ACTIVE_STATUSES\s*=\s*new Set\(\[(?P<items>[^\]]+)\]\)", classic)
    assert classic_statuses, "classic no longer defines WORKFLOW_ACTIVE_STATUSES"
    v2_statuses = re.search(r"WORKFLOW_ACTIVITY_ACTIVE_STATUSES[^=]*=\s*new Set\(\[(?P<items>[^\]]+)\]\)", page)
    assert v2_statuses, "the V2 page no longer defines WORKFLOW_ACTIVITY_ACTIVE_STATUSES"
    words = lambda text: set(re.findall(r"""["']([a-z_]+)["']""", text))  # noqa: E731
    assert words(classic_statuses.group("items")) == words(v2_statuses.group("items"))
    print("  ok  the query, the endpoints and the live statuses are the classic page's")


def test_the_entry_points_open_the_page_in_a_new_tab_and_never_navigate_the_current_one():
    # Classic: chats.html `workflow-activity-btn` and the run history link are `target="_blank"`, and
    # workspace_workflows.js opens a window rather than navigating the workspace tab.
    workflow_js = read_app("static/js/workspace/workspace_workflows.js")
    assert 'window.location.href = activityState.url;' not in workflow_js
    assert 'target="_blank" rel="noopener"' in workflow_js

    links = read_v2("components/workflowActivity/WorkflowActivityLinks.tsx")
    for component in ("WorkflowActivityHeaderLink", "WorkflowRunActivityLink", "WorkflowActivityLink"):
        body = links[links.index(f"export function {component}"):]
        body = body[: body.index("\nexport function ")] if "\nexport function " in body[10:] else body
        assert "<Link" in body, component
        assert 'target="_blank"' in body, f"{component} does not open a new tab"
        assert 'rel="noopener noreferrer"' in body, f"{component} leaves the opener attached"
        assert "(opens in a new tab)" in body, f"{component} does not say it opens a new tab"
    # A real link, not a script: it works from the keyboard, and a blocked pop-up cannot swallow it.
    code = re.sub(r"//.*", "", links)
    for forbidden in ("window.open", "window.location", "useNavigate", "navigate("):
        assert forbidden not in code, forbidden
    print("  ok  the entry points are links that open a new tab")


def test_the_response_preview_starts_closed_and_is_a_labelled_toggle():
    hero = read_v2("components/workflowActivity/WorkflowActivityHero.tsx")
    snapshot = read_v2("lib/workflowActivitySnapshot.ts")

    assert "useState(false)" in hero, "the response preview does not start closed"
    assert "aria-expanded={shown}" in hero
    assert "aria-controls={responseId}" in hero
    assert "id={responseId}" in hero and 'role="region"' in hero
    assert "setExpanded((open) => !open)" in hero
    assert "!shown && 'hidden'" in hero, "a closed panel is hidden by class, never by a style set in script"
    assert "return `${expanded ? 'Hide' : 'Show'} ${heading.trim().toLowerCase() || 'response preview'}`;" in snapshot
    # What it shows: the run's error, else its response preview, and the answer checks tasks saved.
    assert "heading: 'Run Error'" in snapshot and "heading: 'Response Preview'" in snapshot
    assert "<TaskCompletenessDetails value={check.completeness} />" in hero
    # Starts closed again when a run has nothing to preview.
    assert "setExpanded(false)" in hero
    print("  ok  the response preview is closed by default and toggles with its own label")


def test_the_page_is_drawn_from_theme_tokens_and_lays_out_in_two_columns_then_one():
    colour = re.compile(
        r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\b(?:bg|text|border|ring|fill|stroke)-(?:white|black|slate|gray|zinc|neutral|stone"
        r"|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)(?:-\d+)?\b"
    )
    for name, source in own_sources().items():
        found = colour.findall(re.sub(r"//.*", "", source))
        assert not found, f"{name} names a colour instead of a theme token: {found}"
        assert "style={{ color" not in source and "backgroundColor" not in source, name

    page = read_v2("pages/WorkflowActivityPage.tsx")
    # Two columns from 992 px, one below, as classic's single-column breakpoint. The single column
    # is `minmax(0, 1fr)` so a long unbreakable word in a card can't widen it past a phone screen.
    assert "min-[992px]:grid-cols-[minmax(0,1.35fr)_minmax(20rem,0.85fr)]" in page
    assert "grid grid-cols-[minmax(0,1fr)] gap-4" in page
    # Words are in the body text colour: a status colour on its own tint is under 4.5:1 in light.
    badge = read_v2("components/workflowActivity/ActivityStatusBadge.tsx")
    assert "text-text-1" in badge
    tone_block = badge.split("const TONE_CLASS")[1].split("const GLYPH")[0]
    for classes in re.findall(r"badge: '([^']+)'", tone_block):
        assert "text-" not in classes, classes
    notice = re.search(r'data-testid="v2-workflow-activity-notice"\s+className="([^"]+)"', page)
    assert notice, "the page's notice moved"
    assert "text-text-1" in notice.group(1) and "text-danger" not in notice.group(1), notice.group(1)
    timeline = read_v2("components/workflowActivity/WorkflowActivityTimeline.tsx")
    assert "max-[991px]:max-h-[50vh]" in timeline, "the timeline is not capped under 992 px"
    assert "[--lane-step:0rem] md:[--lane-step:2.5rem]" in timeline, "lanes still indent on a phone"
    # The page fills the main area instead of adding a width of its own.
    assert "max-w-" not in page.split("function Loading")[0].replace("max-w-2xl", "")
    print("  ok  the page uses theme tokens and a 992 px two-column layout")


def test_nothing_a_workflow_wrote_is_ever_markup_and_nothing_is_loaded_from_elsewhere():
    sinks = ("dangerouslySetInnerHTML", "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(")  # xss-check: ignore - names the sinks the test forbids
    hidden = ("display:none", "display: none", ".style.display", "style={{ display")
    for name, source in own_sources().items():
        code = re.sub(r"//.*", "", source)
        for sink in sinks:
            assert sink not in code, f"{name} uses {sink}"
        for pattern in hidden:
            assert pattern not in code, f"{name} hides with {pattern}; use the hidden class"
        assert "alert(" not in code, name
        assert not re.search(r"https?://", code), f"{name} names an absolute address"
        assert "import(" not in code and "new Worker" not in code and "importScripts" not in code, name
    # One place makes the one connection, and it makes it to this application.
    stream = read_v2("lib/workflowActivityStream.ts")
    assert stream.count("new EventSource(") == 1
    assert "apiUrl(workflowActivityApiUrl(query, true))" in stream
    assert "withCredentials: Boolean(API_BASE)" in stream
    for name, source in own_sources().items():
        if name != "lib/workflowActivityStream.ts":
            assert "EventSource(" not in source, name
    print("  ok  workflow output is only text and no asset comes from elsewhere")


def test_the_card_beside_a_run_is_the_one_chat_and_approvals_use():
    detail = read_v2("components/workflowActivity/ActivityPendingAction.tsx")
    assert "from '../approvals/PendingActionCard'" in detail
    assert "createPendingActionsStore({ scope: 'detail'" in detail
    assert '<PendingActionCard id={action.id} variant="inline" />' in detail
    # It is told what the snapshot said as a snapshot, never as a read the server confirmed.
    assert "store.getState().remember(action)" in detail
    assert "authoritative" not in detail
    # The page reads again when the card learns something newer, and not for an action it already holds.
    hook = read_v2("components/workflowActivity/useWorkflowActivity.ts")
    assert "pendingActionMoved(held, action)" in hook
    print("  ok  the Microsoft 365 card is the shared card, told only what the snapshot said")


def test_notification_links_and_support_shortcuts_open_the_page_and_not_the_classic_one():
    links = read_v2("lib/notificationLinks.ts")
    assert "validatedWorkflowActivitySearch(url.search)" in links
    assert "route(`${WORKFLOW_ACTIVITY_PATH}${search}`)" in links
    # The old routing of a classic link to a classic page, keyed on the notice agreeing with it, is gone.
    for gone in ("linkWorkflowScope", "agreesWithNotice", "workflowActivityRunPath"):
        assert gone not in links, gone
    shortcuts = read_v2("lib/latestFeatureShortcuts.ts")
    assert "case '/workflow-activity':" in shortcuts
    assert "isWorkflowActivityRoute(path)" in shortcuts
    print("  ok  notices and shortcuts resolve to the V2 page")


def test_a_busy_button_stays_focusable_a_long_word_wraps_and_work_for_a_page_that_has_gone_is_dropped():
    hero = read_v2("components/workflowActivity/WorkflowActivityHero.tsx")
    code = re.sub(r"//.*", "", hero)
    # Refresh and Cancel run are busy as aria-disabled and never as a native `disabled`, which hands
    # the reader's focus to the page the moment it is set.
    assert not re.search(r"(?<![\w-])disabled=", code), "a button on the page uses the native disabled attribute"
    assert "aria-disabled={loading || undefined}" in hero
    assert "aria-disabled={inert || undefined}" in hero
    assert "aria-busy={loading || undefined}" in hero and "aria-busy={busy || undefined}" in hero
    # Pressing one while it is busy asks for nothing more.
    assert "if (!loading) {" in hero and "if (!inert) {" in hero
    # Cancel run leaves when the run settles; if it holds focus then, Refresh takes it before the
    # button is taken out of the page (a layout effect's cleanup runs while it is still there).
    assert "useLayoutEffect(" in hero
    assert "document.activeElement?.id === id" in hero and "document.getElementById(refreshId)?.focus()" in hero
    # The title can shrink to its card. `break-words` alone leaves a flex item as wide as its longest word.
    title = re.search(r'data-testid="v2-workflow-activity-title"\s+className="([^"]+)"', hero)
    assert title, "the title moved"
    assert {"min-w-0", "max-w-full", "[overflow-wrap:anywhere]"} <= set(title.group(1).split()), title.group(1)
    assert "break-words" not in title.group(1)
    for name in ("WorkflowActivityTimeline.tsx", "WorkflowActivityDetail.tsx"):
        lane = read_v2(f"components/workflowActivity/{name}")
        assert "min-w-0" in lane and "[overflow-wrap:anywhere]" in lane, f"{name} lets a long lane name widen a card"

    # The run history's row wraps its links under the time instead of squeezing the time to nothing.
    history = read_v2("components/workflows/WorkflowRunHistory.tsx")
    row = re.search(r'<div className="([^"]+)">\s*<RowAction', history)
    assert row and "flex-wrap" in row.group(1).split(), "the run history row does not wrap"
    assert "min-w-[9rem] flex-1" in history, "the run's time can shrink to nothing"

    # Everything that runs later than the render that made it holds the address it was made for.
    hook = read_v2("components/workflowActivity/useWorkflowActivity.ts")
    code = re.sub(r"//.*", "", hook)
    load = code[code.index("const load = useCallback"):code.index("const listening")]
    assert "keyRef.current !== key" in load.split("request.current?.abort()")[0], (
        "a read for an address the page has left would stop the read of the one it is on"
    )
    for declaration in ("const refresh = useCallback", "const pendingActionChanged = useCallback"):
        assert "keyRef.current !== key" in code[code.index(declaration):][:400], declaration
    cancel = code[code.index("const cancel = useCallback"):code.index("const selectActivity")]
    assert "cancelRequest.current === key" in cancel, "a second press is not ignored"
    answered = cancel.split("await cancelScopedWorkflowRun")[1]
    assert "keyRef.current !== key" in answered, "a cancel's answer is acted on after the reader has gone"
    assert "if (cancelRequest.current === key)" in cancel, "a cancel's end clears what belongs to another address"
    assert "setCancelling(" not in code, "the busy state is one flag for every address"
    print("  ok  busy buttons keep focus, long words wrap, and a stale answer touches nothing")


def _snapshots():
    """What the server builds, for the Node probes to read through the page's own reader."""
    from functions_workflow_activity import build_workflow_activity_snapshot

    workflow_id, conversation_id = "workflow-abc", "conversation-xyz"

    def thought(thought_id, index, step_type, content, detail, timestamp, duration, key, kind, title, status, lane, run_id):
        return {
            "id": thought_id, "step_index": index, "step_type": step_type, "content": content, "detail": detail,
            "timestamp": timestamp, "duration_ms": duration,
            "activity": {
                "activity_key": key, "workflow_id": workflow_id, "run_id": run_id, "kind": kind, "title": title,
                "status": status, "lane_key": lane[0], "lane_label": lane[1],
            },
        }

    main = ("main", "Main")
    plugin = ("SecurityPlugin", "SecurityPlugin")
    finished = build_workflow_activity_snapshot(
        run_record={
            "id": "run-123", "workflow_id": workflow_id, "workflow_name": "Security Events",
            "conversation_id": conversation_id, "assistant_message_id": "assistant-message-1", "status": "completed",
            "success": True, "started_at": "2025-01-01T00:00:00+00:00", "completed_at": "2025-01-01T00:00:04+00:00",
            "trigger_source": "manual", "response_preview": "Security events workflow completed.",
        },
        workflow={"id": workflow_id, "name": "Security Events", "runner_type": "agent", "conversation_id": conversation_id},
        conversation={"id": conversation_id, "title": "Workflow: Security Events", "chat_type": "workflow", "workflow_id": workflow_id},
        thoughts=[
            thought("t1", 0, "workflow", "Workflow run started", "trigger_source=manual", "2025-01-01T00:00:00+00:00", None,
                    "run:run-123", "workflow_run", "Workflow run", "running", main, "run-123"),
            thought("t2", 1, "agent_tool_call", "Invoking SecurityPlugin.fetch_events", "severity=high", "2025-01-01T00:00:01+00:00", None,
                    "plugin-1", "tool_invocation", "SecurityPlugin.fetch_events", "running", plugin, "run-123"),
            thought("t3", 2, "agent_tool_call", "Workflow agent executed SecurityPlugin.fetch_events (450ms)",
                    "severity=high; success=True", "2025-01-01T00:00:02+00:00", 450,
                    "plugin-1", "tool_invocation", "SecurityPlugin.fetch_events", "completed", plugin, "run-123"),
            thought("t4", 3, "workflow", "Workflow run completed", "message_id=assistant-message-1", "2025-01-01T00:00:04+00:00", None,
                    "run:run-123", "workflow_run", "Workflow run", "completed", main, "run-123"),
        ],
    )
    running = build_workflow_activity_snapshot(
        run_record={
            "id": "running-run-1", "workflow_id": workflow_id, "workflow_name": "Security Events", "status": "running",
            "success": False, "started_at": "2025-01-03T00:00:00+00:00", "conversation_id": conversation_id,
            "assistant_message_id": "assistant-message-2", "trigger_source": "manual", "agent_display_name": "Security Agent",
        },
        workflow={"id": workflow_id, "name": "Security Events"},
        conversation={"id": conversation_id, "title": "Workflow: Security Events", "chat_type": "workflow"},
        thoughts=[
            thought("r1", 0, "workflow", "Workflow run started", "trigger_source=manual", "2025-01-03T00:00:00+00:00", None,
                    "run:running-run-1", "workflow_run", "Workflow run", "running", main, "running-run-1"),
            thought("r2", 1, "agent_tool_call", "Invoking SecurityPlugin.fetch_events", "severity=high", "2025-01-03T00:00:01+00:00", None,
                    "plugin-running-1", "tool_invocation", "SecurityPlugin.fetch_events", "running", plugin, "running-run-1"),
        ],
    )
    with_action = build_workflow_activity_snapshot(
        run_record={
            "id": "run-with-pending-graph", "workflow_id": workflow_id, "workflow_name": "Security Events",
            "status": "running", "success": False, "started_at": "2025-01-04T00:00:00+00:00", "conversation_id": conversation_id,
        },
        workflow={"id": workflow_id, "name": "Security Events"},
        conversation={"id": conversation_id, "title": "Workflow: Security Events", "chat_type": "workflow"},
        thoughts=[
            thought("g1", 0, "workflow", "Workflow run started", "trigger_source=manual", "2025-01-04T00:00:00+00:00", None,
                    "run:run-with-pending-graph", "workflow_run", "Workflow run", "running", main, "run-with-pending-graph"),
        ],
        pending_actions=[{
            "id": "pending-calendar-1", "type": "msgraph_pending_action", "operation": "create_calendar_invite",
            "graph_resource_type": "calendar", "status": "scheduled", "action_mode": "delayed",
            "subject": "Review planning invite", "workflow_id": workflow_id, "run_id": "run-with-pending-graph",
            "created_at": "2025-01-04T00:00:05+00:00", "updated_at": "2025-01-04T00:00:05+00:00",
            "auto_send_at_utc": "2025-01-04T00:02:05Z", "delay_seconds": 120, "can_cancel": True, "can_send_now": True,
            "version": "v1", "viewer_is_owner": True,
        }],
    )
    legacy = build_workflow_activity_snapshot(
        run_record={
            "id": "legacy-run-1", "workflow_id": workflow_id, "workflow_name": "Security Events", "status": "failed",
            "success": False, "started_at": "2025-01-02T00:00:00+00:00", "completed_at": "2025-01-02T00:00:03+00:00",
            "error": "Workflow agent timed out.",
        },
        workflow={"id": workflow_id, "name": "Security Events"},
        conversation={"id": conversation_id, "title": "Workflow: Security Events"},
        thoughts=[],
    )
    conversation_only = build_workflow_activity_snapshot(
        conversation={"id": conversation_id, "title": "Workflow: Security Events", "chat_type": "workflow"},
    )
    return {
        "finished": finished, "running": running, "withAction": with_action,
        "legacy": legacy, "conversationOnly": conversation_only,
    }


def _run_node_test(path, environment=None):
    """Execute one of the Node probes, reporting its result."""
    assert path.exists(), f"The runtime test is missing: {path}"
    if not (V2_DIR / "node_modules" / "zustand").exists():
        print("  application/v2_ui/node_modules is not installed; skipping the runtime test.")
        print("  Install it with: npm ci --prefix application/v2_ui")
        return
    node = shutil.which("node")
    if not node:
        print(f"  Node is not installed; skipping. Run it with: node {path.relative_to(REPO_ROOT)}")
        return
    completed = subprocess.run(
        [node, str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(REPO_ROOT), env={**os.environ, **(environment or {})}, check=False,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    # Node below 22.6 cannot import TypeScript directly: a limit of the environment, not of the code.
    if completed.returncode != 0 and "Unknown file extension" in output:
        print("  This Node cannot import TypeScript directly (needs 22.6 or newer); skipping.")
        return
    if completed.returncode != 0:
        # Node's reporter draws ticks and crosses a Windows console's code page cannot print.
        print(output.encode("ascii", "replace").decode("ascii"))
        raise AssertionError(f"{path.name} failed; see the output above.")
    passed = re.search(r"(?m)^.{0,3}pass (\d+)\s*$", output)
    failed = re.search(r"(?m)^.{0,3}fail (\d+)\s*$", output)
    assert passed and failed, f"{path.name} printed no test summary:\n{output}"
    assert int(passed.group(1)) >= 1 and int(failed.group(1)) == 0, output
    print(f"  {path.name}: {passed.group(1)} tests passed.")


def test_the_page_reads_what_the_server_builds_and_the_rules_hold():
    """Run the page's pure rules against snapshots built by the server's own builder."""
    SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_FILE.write_text(json.dumps(_snapshots(), default=str), encoding="utf-8")
    try:
        _run_node_test(LOGIC_TEST, {"WORKFLOW_ACTIVITY_SNAPSHOTS": str(SNAPSHOT_FILE)})
    finally:
        SNAPSHOT_FILE.unlink(missing_ok=True)


def test_a_run_link_and_a_workflow_activity_link_resolve_as_the_notice_resolver_says():
    """The routing probes: run deep links, the bell's reading of notices, and the alert card's Open run."""
    _run_node_test(ROUTING_TEST)


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_the_page_is_routed_and_every_entry_point_is_wired,
    test_the_page_reads_the_query_and_the_endpoints_the_classic_page_reads,
    test_the_entry_points_open_the_page_in_a_new_tab_and_never_navigate_the_current_one,
    test_the_response_preview_starts_closed_and_is_a_labelled_toggle,
    test_the_page_is_drawn_from_theme_tokens_and_lays_out_in_two_columns_then_one,
    test_nothing_a_workflow_wrote_is_ever_markup_and_nothing_is_loaded_from_elsewhere,
    test_the_card_beside_a_run_is_the_one_chat_and_approvals_use,
    test_notification_links_and_support_shortcuts_open_the_page_and_not_the_classic_one,
    test_a_busy_button_stays_focusable_a_long_word_wraps_and_work_for_a_page_that_has_gone_is_dropped,
    test_the_page_reads_what_the_server_builds_and_the_rules_hold,
    test_a_run_link_and_a_workflow_activity_link_resolve_as_the_notice_resolver_says,
]


def main():
    print("Testing the V2 Workflow Activity page...\n")
    failures = []
    for test in TESTS:
        try:
            test()
        except AssertionError as error:
            failures.append(test.__name__)
            print(f"FAIL  {test.__name__}: {error}")
    print(f"\n{len(TESTS) - len(failures)}/{len(TESTS)} tests passed")
    if failures:
        print("Failed: " + ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
