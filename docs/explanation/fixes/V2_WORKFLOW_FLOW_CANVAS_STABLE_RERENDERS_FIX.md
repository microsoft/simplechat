# V2 Workflow Flow Canvas Stable Re-renders Fix (v0.261.207)

**Fixed in version: 0.261.207**

The application version is tracked in `application/single_app/config.py`.

Fixes #1573. Found during the Chat Orchestration Workflows work (#1543).

## Issue

The V2 workflow editor's **Flow** surface and the read-only Flow view draw the
workflow with React Flow. Their execution arrows (control edges) disappeared
whenever the page re-rendered for a reason that didn't change the diagram: the
**Saving…** state, a failed save, typing in a field outside the diagram, or a
runtime poll of a running workflow that returned the same run. Usually the arrows
came back a frame or two later, once React Flow measured the blocks again.
Sometimes they didn't come back at all until something else made React Flow
measure the blocks.

The UI test
`ui_tests/test_v2_workflow_flow_authoring.py::test_save_failures_retain_flow_fields_and_never_replace_the_original_cas_revision[400|409|503]`
edits two fields and then waits, with Playwright's default 5 seconds, for a control
edge (`expect_compiled`, line 282). Each variant timed out at least once in
full-suite runs, including on the V2 base, and passed when run alone.

## Root cause

### Every render rebuilt every node

`WorkflowFlowCanvas` builds React Flow's node objects in a `useMemo`. Its
dependencies included the four handlers every node calls: `onSelect`,
`onCollapse`, and the canvas's own `onFocus` and `onNavigate`. The editor passes
new functions on every render:

- `WorkflowEditorDialog` passes `onSelect` as an inline arrow.
- `WorkflowFlowAuthoring` passes `collapse`, a plain function, as `onCollapse`.
  The canvas's `onNavigate` depends on `onCollapse`, so it changed as well.

So every render of the editor built a new object for every node, even when the
diagram hadn't changed. Real changes did the same: selecting a block or typing in a
task rebuilt every node, not only the ones that changed.

### A new node object loses its handle positions

In `@xyflow/react` 12.11.6, `adoptUserNodes` keeps React Flow's internal node only
when it receives the same node object again. For any other object without a
`measured` size, `parseHandles` drops the node's handle bounds, and `EdgeWrapper`
draws no edge whose handles have no bounds. Each rebuild therefore removed every
arrow from the page, and the arrows came back only after the node's
ResizeObserver measured it again. On a diagram that shows 12 control edges, the
new regression spec counts 24 removed and added again while a save is pending.

### A lost measurement leaves the arrows missing

React Flow observes a node again only when the node's initialized state changes
(`useNodeObserver`). Two rebuilds in a row can lose that measurement:

1. A rebuild drops the handle bounds, so React Flow observes the node again.
2. A second rebuild renders at default priority and commits. Its passive effect,
   which gives React Flow the new node objects, hasn't run yet.
3. The ResizeObserver notification from step 1 arrives, and React Flow stores the
   handle bounds. That store update renders synchronously, so React first runs the
   pending passive effect, which drops the handle bounds again.
4. The node was uninitialized before and is uninitialized now, so React Flow
   doesn't observe it again. Its arrows stay missing.

In the flaky test, the second field edit renders the editor synchronously, which
rebuilds every node. The compiler preview effect then sets `loaded` to `null`,
which renders `WorkflowFlowAuthoring` again at default priority with a new
`collapse` and rebuilds every node a second time. A ResizeObserver notification
that lands between that render's commit and its passive effects leaves the arrows
missing, and `expect_compiled` times out at line 282.

## Fix

All changes are in `WorkflowFlowCanvas.tsx` and a new helper,
`lib/workflowFlowNodeReuse.ts`. The editor dialog, `WorkflowFlowAuthoring` and
`WorkflowFlowView` are unchanged, so the fix covers both the editor and the
read-only Flow view.

### Stable handlers

The canvas keeps the latest `onSelect`, `onCollapse`, `onFocus` and `onNavigate`
in a ref, updated after every commit, and gives the nodes stable wrappers that
call them. A new handler identity no longer rebuilds a node, and a click or a key
still reaches the editor's current state.

### Unchanged nodes keep their object

`reuseUnchangedFlowNodes` compares each rebuilt node with the previous node of the
same ID. Fields are compared by identity, and plain-object fields such as `data`,
`style` and `position` are compared one level down. A node that didn't change
keeps its previous object, and when no node changed the canvas passes React Flow
its previous array, so React Flow has nothing to adopt again. A change to one
block, such as its selection, now rebuilds only the nodes whose values changed.

### Changed nodes keep their measured size

The canvas records the size React Flow reports for each node (`dimensions`
changes in `onNodesChange`), and a rebuilt node carries it as `measured`.
React Flow then keeps the node's handle bounds instead of dropping them, so a real
change, such as typing in a task, a new compiler status or a collapse, no longer
removes the node's arrows while React Flow measures it again. Sizes of nodes that
leave the diagram are forgotten. `measured` is ignored when nodes are compared, so
recording a size never rebuilds a node.

### Selection re-measures its node

A selected block has a 2px border instead of 1px. That moves its handles without
changing its size, so no ResizeObserver notification follows. Before this fix, the
rebuild dropped the handle bounds, which forced a new measurement. Now each node
asks React Flow to measure it again (`useUpdateNodeInternals`) when its selection
changes, so its arrows follow the new border.

### Stable React Flow props

`onInit`, `onError` and `fitViewOptions` were new on every render. They are now a
`useCallback` each and a module constant, so a re-render gives `<ReactFlow>` no new
props when nothing changed.

### What still rebuilds nodes

A real change to a block's values still builds a new object for that block: its
record, label, status, selection, collapse, focus or position. Typing in a task
changes the draft, so every record is new and every node is rebuilt. Each rebuilt
node carries its measured size, so its arrows stay drawn.

### Files modified

| File | Change |
| --- | --- |
| `application/v2_ui/src/components/workflows/WorkflowFlowCanvas.tsx` | Stable handler wrappers, node reuse, recorded sizes carried as `measured`, the selection re-measure, and stable `onInit`, `onError` and `fitViewOptions` |
| `application/v2_ui/src/lib/workflowFlowNodeReuse.ts` | New: `sameFlowNode` and `reuseUnchangedFlowNodes` |
| `functional_tests/test_v2_workflow_flow_node_reuse_logic.mjs` | New: unit tests for the helper |
| `ui_tests/test_v2_workflow_flow_canvas_stability.py` | New: browser regression tests |
| `application/single_app/config.py` | Version 0.261.207 |

## Testing

### Regression spec

`ui_tests/test_v2_workflow_flow_canvas_stability.py` runs the production bundle
against the closed Flow harnesses and the real compiler. It installs a
MutationObserver on the canvas and counts every control edge and React Flow node
removed from or added to the page, and the fewest control edges shown:

- `test_non_diagram_rerenders_keep_every_flow_node_and_edge_mounted[400|409|503]`
  holds a save open, lets it fail with 400, 409 or 503, and types in the decision
  field builder with `page.keyboard`. Nothing may be removed or added, and typing
  must not revalidate the draft. Afterwards, keyboard selection, collapse, arrow
  key navigation and **Return to selected block** must still reach the latest
  editor state, and every control edge must still start and end on its node's
  handles.
- `test_focus_and_selection_changes_keep_control_edges_mounted_and_on_their_handles`
  moves focus and selection with the keyboard. No control edge may leave the page,
  and every control edge must end on its handles after the wider selected border.
- `test_rapid_focus_and_selection_changes_leave_every_control_edge_drawn` fits
  the view, then clicks and presses keys faster than React Flow measures. Once the
  canvas settles, every control edge must be drawn, on its handles, with no
  further churn.
- `test_runtime_polls_keep_read_only_flow_nodes_and_edges_mounted` opens the
  read-only Flow of a running workflow and waits for two runtime polls that return
  the same run. Nothing may be removed or added.

### Reproducing the flake

The flake needs a ResizeObserver notification to land inside a short window, so
it rarely shows on a fast machine. A session-only pytest plugin, not committed,
repeated each test 20 times and made the window measurable with two options:

- CPU throttling slows the page 4 times through the Chrome DevTools Protocol
  (`Emulation.setCPUThrottlingRate`).
- A race amplifier, an init script, holds each ResizeObserver notification until a
  microtask after the next React commit, or one more frame at most. A browser may
  deliver a notification at that point, so it makes a rare but legal order common.

Every failure of the save-failure test on the base, with or without the amplifier,
was the control edge wait at line 282, exactly as in the full-suite runs.

The amplifier also holds React Flow's pane-size notifications. Under it, the first
fit showed the diagram at full size, with only the root block's button reachable,
on both the base and the fix. The rapid test therefore fits the view itself before
it clicks.

### Unit tests

`functional_tests/test_v2_workflow_flow_node_reuse_logic.mjs` checks, with
`node --test`, that equal rebuilds are reused, that a changed value, key or deeper
identity isn't, that ignored fields don't count, that the previous array is kept
only when every node is kept in order, and that neither input is changed.

## Validation

"Before" is the V2 bundle at `c33ad4d16`, and "after" is the bundle built from
this change. Both ran in Chromium against the offline Playwright harness.

- The regression spec failed 5 of its 6 tests on the base, each on its churn
  assertion. 24 control edges were removed and redrawn while a save was pending
  and failing, 72 during focus and selection changes, and 24 across two runtime
  polls, and each time there was a moment with no control edge drawn. The rapid
  test passed on the base. With the fix, all 6 pass.
- With the fix, `ui_tests/test_v2_workflow_flow_authoring.py` passed all 30 tests
  in each of two runs. The Flow inspection (53), authoring history (28), change
  tracking (24), editor (9), calendar schedule (14), control flow (10) and M365
  runtime (8) specs pass.
- `node --test functional_tests/test_v2_workflow_flow_node_reuse_logic.mjs`
  passes 10 of 10, and `functional_tests/test_v2_workflow_change_tracking.py`
  passes 4 of 4. `npm run typecheck` and `npm run build` pass.

The stress rows repeated each test 20 times with the session-only plugin described
under **Reproducing the flake**.

| | Before | After |
| --- | --- | --- |
| Save, failed save (400, 409 or 503), typing outside the diagram | Every control edge removed and redrawn | Nothing removed |
| Runtime poll that returns the same run | Every control edge removed and redrawn | Nothing removed |
| Focus and selection changes | Every control edge removed and redrawn | Only the changed nodes are rebuilt; no control edge removed |
| Save-failure test, 4× CPU throttle and race amplifier, 60 runs | 60 failed, all at the control edge wait (line 282) | None failed |
| Save-failure test, 4× CPU throttle, 60 runs | 3 failed, all at the control edge wait (line 282) | None failed |
| Rapid selection test, 4× CPU throttle and race amplifier, 20 runs | 2 failed, both at the control edge wait (line 282) while opening the Flow | None failed |

## Known limitations

A node React Flow has never measured has no size to carry. If it is rebuilt at
default priority before its first measurement, and the measurement lands between
that render's commit and its passive effects, its arrows can still go missing, as
before. A new node is normally measured within a frame of being added, and none of
the stress runs showed this.
