# Read-only workflow Flow inspection

Implemented in version: **0.261.121**

Application version tracking: `application/single_app/config.py`.

## Purpose and boundaries

M5A adds a read-only diagram to personal and group V2 structured workflows.
Use it to understand branch order, loop boundaries, declared data dependencies,
and the exact configuration behind a historical run. Author executable changes
in List; the diagram cannot add, connect, delete, reorder, or save steps.

The existing version-3 definition and Python compiler remain authoritative.
There is no second stored executable graph, scheduler, result store, exporter,
or publication ledger. Version-1/version-2 List and history remain unchanged.
Viewing a workflow does not convert it to version 3.

M5B direct visual authoring and the separately requested personal/group Control
Center Workflow Monitoring capability are not part of this release.

## Dependencies and architecture

Flow uses the existing V2 React/Vite application and the MIT-licensed
`@xyflow/react` **12.11.6**, pinned with its dependency lockfile. SimpleChat owns
the deterministic structured layout. Dagre, ELK, remote scripts, workers, and
React Flow Pro examples are not used.

The production build emits local assets under `/static/v2/`. Required notices
are retained in `application/v2_ui/public/licenses/workflow-flow-notices.txt`
and copied to `/static/v2/licenses/workflow-flow-notices.txt`. No CSP relaxation
or browser-side library download is required.

`functions_workflow_inspection.py` projects the normalized compiler's regions,
nodes, joins, successors, and lexical loop ancestry. The task catalogue's array
order is not treated as execution order. Each loop has one template body,
regardless of how many frozen items or lifetime rounds exist.

The renderer's pan, zoom, collapse, and box coordinates are temporary component
state. They never enter workflow JSON, definition revisions, approval inputs,
execution identities, or persistent browser storage.

## Three separate definition sources

| Source label | Definition shown | Run evidence |
| --- | --- | --- |
| Saved definition | Currently authorized saved structured definition | None |
| Unsaved draft | Compiler-checked preview of current List edits | None |
| Run's frozen definition | The selected run's validated admitted snapshot | Only matching execution, mixed path, and attempt |

The viewer always identifies its source and revision or preview digest. Draft
digests carry a `DRAFT:` prefix and never replace the editor's saved
`definition_revision` concurrency baseline. Preview is opt-in and debounced;
it performs no save, model call, document selection, input freezing, or run.

Invalid or unsupported drafts retain the List edits and clear the outdated
diagram. A structurally valid preview is not proof of save/admission eligibility.
Missing, corrupt, or unsupported frozen snapshots fail explicitly; run Flow
never substitutes the current saved definition.

## Read-only APIs and authorization

Personal and group workflows expose the same operations:

| Method and path | Purpose |
| --- | --- |
| `GET /api/{user\|group}/workflows/<workflow_id>/flow` | Saved topology or a bounded node-detail section |
| `GET /api/{user\|group}/workflows/<workflow_id>/runs/<run_id>/flow` | Frozen-run topology or node details |
| `POST /api/{user\|group}/workflows/flow-preview` | Pure compiler preview of an authored draft |
| Existing run `/executions` GET with `node_id`, `iteration_path`, `limit=1` | Exact execution lookup, not a journal scan |

Every group request carries an explicit authorized `group_id`. Saved/run
inspection uses existing reader access; preview uses authoring access. Swagger,
Blueprint login policy, feature gates, and object-level workflow/run/scope
checks remain in effect. Run evidence reuses current source, contributor,
attempt, and frozen/admitted path authorization.

The topology DTO contains canonical IDs, labels, kinds, nesting/order,
connection labels, input/output counts, finite loop maxima, and run limits.
It does not contain raw snapshots, private runner context, settings, leases,
result-store locators, saved state values, or full schemas/instruction bodies.

To inspect a node, supply its `node_id`, matching `revision`, and a `section`:
`configuration`, `inputs`, `condition`, `outputs`, `state`, or `selection`.
Preview uses the same selectors alongside `definition` in its POST body.
Responses contain `items`, `total_count`, and a source-bound `next_cursor`.

The UI requests at most 50 detail/history entries at a time; server detail
pages permit 1-100 entries and impose a 240 KiB serialized response budget.
An individually oversized detail fails rather than returning a shortened
schema, instruction, or state contract. Pages replace one another; cursors
are not automatically drained.

Exact execution lookup validates the complete mixed path and derives identity
server-side from the frozen definition revision. For-each item keys/indexes and
Repeat lifetime iterations retain their existing distinct shapes. A valid
selector with no stored execution says **No execution recorded**, not Completed
or empty success.

## Use saved and draft Flow

1. In personal or group Workflows, choose **View Flow for ...** on a saved
   version-3 workflow. This does not require opening Edit and remains available
   while a run is active, subject to current reader access.
2. Select a node and choose its inspection section. Instructions, contracts,
   conditions, references, and source selections load only when requested.
   **Source selection** describes authored selection; it does not rerun a query
   or enumerate its current matches.
3. Read solid arrows as control flow. Dashed arrows describe declared typed
   connections for the selected detail page, including join exports, Repeat
   state receipts, and Collect's frozen-item source. They are not additional
   execution paths or loaded result values. Parallel connections have compact
   count labels; their complete meanings remain in the relationship lists.
4. Expand For each or Repeat to see its single body template. Use the control
   relationship and declared-data lists to follow exact producer/boundary IDs.
5. While editing in List, choose **Show Flow preview**. On wider screens List
   and preview appear together; on narrow screens **Hide Flow preview** returns
   to List. Preview starts off and does not make an unchanged draft dirty.

Saving and running remain separate explicit operations outside Flow. Pan,
zoom, fit, collapse, temporary box movement, and **Reset layout** do not save
or affect execution.

## Inspect a selected run

Expand a run and choose **Show Flow for this run**. Flow replaces the execution
list while visible, but the existing runtime panel and its authorized actions
remain separate. It shares that panel's runtime snapshot rather than adding
another polling loop.

The viewer loads one bounded execution-metadata page, plus an explicitly
selected exact execution. **Not loaded** means evidence has not been requested;
it is not a guess about pending or completed work. Output validation remains
separate from execution status, including accepted partial and incomplete data.
An If path is marked as recorded only from a saved decision for the exact
selected instance, never inferred from nearby completed tasks.

Then/Else and loop-body regions are structural groupings, not invented
execution records. Their configuration remains inspectable; use the enclosing
control or contained nodes for run evidence. The root retains its real root
execution identity.

Inspect a loop boundary and use its existing frozen-item or Repeat-round pages.
**Use item N in Flow** or **Use round N in Flow** selects the server-returned
mixed path. Nested templates need an exact enclosing instance before runtime
inspection. Attempts, result excerpts, complete records, contributors, and
before/after Repeat state use the same read-only inspector as List history.

The run-wide retained Repeat observation names its actual execution; it is not
an aggregate for every instance of that template. The actual runtime gate and
its choices take precedence over retained counters. A cancel-only gate never
becomes a continuation action in Flow.

Changing source, revision, run, or instance discards incompatible observations.
Cancelled/stale requests cannot repopulate a newer selection. Access-loss
responses remove cached graphs, observations, state, and result inspection.

## Accessibility and mobile behavior

**Structure list** and **Flow diagram** share the same projection and inspector.
The structure list is the initial narrow-screen view. Diagram keyboard
navigation follows logical order: Up/Down, Home/End, Left to the parent, Right
to enter/expand, and Enter to select. **Inspect selected node** transfers focus
to the labeled inspector; **Return to selected node** returns it.

Collapsing a selected descendant recovers focus at the visible owning
boundary. Zoom and pan have buttons, and temporary box movement has a keyboard
alternative to dragging. Touch views do not capture background drag or pinch
zoom, leaving page scrolling and browser zoom available.

Labels, relationship lists, and line styles supplement visual geometry.
Theme tokens support light/dark mode, and programmatic view movement avoids
animation, including with reduced motion.

## Preserved M4 contracts

For each remains serial, with the 500-actual-input administrator default and
1-5,000 supported range. Repeat retains an explicit authored automatic batch,
its separate administrator default of 25 and range of 1-1,000, post-body typed
Until, exhaustion pause, and explicit same-sized continuation.

Only batch usage resets after continuation. Lifetime round identity, the
original admission budget, and elapsed deadline do not reset; lifetime round
1,001 is not confused with the per-batch ceiling. Existing 5,000-admission and
86,400-second bounds include waits. A cumulative run-token/spend cap remains
deferred.

Typed state, source authorization, locally metered loops/reports, native
Analyze identities, exact Collect order/lineage, and shared `exact_records_v1`
JSON export are unchanged. Publication still distinguishes submission,
approval, and indexed readiness. Refreshing inspection displays saved
observations; it cannot publish, reconcile readiness, or rerun Analyze.

## Coverage and limitations

Offline coverage is in:

- `functional_tests/test_workflow_flow_inspection.py`: real compiler projection,
  allowlists, bounded details, frozen snapshots, exact lookup, and lifetime paths.
- `functional_tests/route_tests/test_workflow_flow_inspection_policy.py`:
  personal/group reader and author gates, scope isolation, and safe failures.
- `functional_tests/test_workflow_flow_layout.py`: deterministic bounded layout,
  source guards, hierarchy, and collapsed-template behavior.
- `functional_tests/test_workflow_execution_inspection_client.js`: exact lookup
  client and shared inspection contracts.
- `functional_tests/test_workflow_flow_semantics.js`: real execution boundaries,
  mixed-frame equality, and unambiguous nested condition summaries.
- `functional_tests/test_workflow_flow_assets.py`: pinned local dependencies,
  copied license notices, and static import boundaries.
- `ui_tests/test_v2_workflow_flow_inspection.py`: the actual local V2 bundle
  against closed fictional APIs, including interaction and request isolation.

The structural bound remains 256 canonical IDs, region depth four, and three
mixed loop frames. Dense definitions may require zoom or the structure list;
they never expand into thousands of runtime boxes. Geometry is not retained
after closing the viewing session.

These fixtures do not establish live Azure performance or production
acceptance. No deployment, real publication, production workflow invocation,
permission change, or merge is part of this slice.
