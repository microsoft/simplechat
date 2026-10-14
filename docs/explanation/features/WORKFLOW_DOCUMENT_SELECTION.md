# Per-task rolling document selection — v0.261.333

## Overview

**Implemented in version: 0.261.332**, tracked by
`application/single_app/config.py`.

Unified controls, Added semantics and runtime choice implemented in version:
**0.261.333**, also tracked in `application/single_app/config.py`.

Workflow tasks can select documents at execution time using an explicit
workspace, rolling update window, and typed metadata conditions. This makes
scheduled document reviews useful without repeatedly attaching individual
files. Each task owns its selection; a summary task and a comparison task need
not read the same documents.

Dependencies are the authorized document-access catalog, current-document
reader, existing native document actions, and the repository-pinned `regex`
package. The guided editor uses only bundled local frontend assets.

## Technical contract

The task's `document_action` retains `target_mode: recent` and canonical
`recent_window_minutes`, plus `document_selection`:

```json
{
  "scopes": [{"scope_type": "personal"}],
  "time_basis": "added",
  "filters": {
    "operator": "and",
    "conditions": [
      {"field": "file_type", "operator": "has_any", "value": ["pdf", "csv"]},
      {"operator": "or", "conditions": [
        {"field": "filename", "operator": "starts_with", "value": "Tim"},
        {"field": "tags", "operator": "has_any", "value": ["X"]}
      ]}
    ]
  },
  "on_empty": "report"
}
```

Workspace and time boundaries are outside the Boolean tree. Filename
conditions support equality, prefix, substring, and regex. Tags support any/all
selected values; file types support alternative extensions. Classification,
authors, and keywords support text conditions. Matching defaults to
case-insensitive; `match_case` changes that default. Regex inline flags still
follow the regex engine's syntax.

Windows are whole canonical minutes from 1 through 525,600. The optional
`time_basis` is `added` or `added_or_updated`. Omission retains `_ts` semantics:
both new uploads and metadata/content edits qualify. Added parses the current
record's authoritative `upload_date`, including timezone offsets and historical
naive UTC values. Missing/malformed upload metadata never falls back to `_ts`.
Added describes the current upload, including a newly uploaded revision, not
the original revision family's creation. Both endpoints are inclusive; future
timestamps do not qualify. Matches sort newest-first by the chosen time basis.
Conditions require recorded metadata rather
than inferring authors or classifications from document content.

Selections allow 1–20 explicit workspaces, 32 filter nodes including groups,
and four total tree levels. Predicate strings are at most 256 characters.
Regex matching has a 20 ms per-match timeout. Capture is bounded by 10,000
candidates, 30 seconds, and the action's document limit. These are safeguards,
not new admin settings. A failure never becomes an empty or truncated success.

## Authorization, capture, and native actions

The preview and runtime share `functions_workflow_document_selection.py` and
the existing `functions_workflow_loop_inputs.py` authorized paging boundary.
Filters apply before matching-document limits. Native Merge also applies its
supported input extensions before that limit.

Every selected source retains its scope and source proof. Task-local retries
reuse their snapshot; durable execution stores it in a replay-safe task/visit
unit. Resume checks current scope access and source versions, including when
the stored selection was empty. New runs capture again.
Merge reads full source metadata and validates its frozen proof in the same
authorized read, so it cannot accidentally assemble a later revision.

Native source readers and Search hits are bound to the selected workspace.
The binding is actor-scoped and cleared after each operation; it is an
additional restriction, not authorization. A task whose selected documents
share an identifier across workspaces is refused rather than ambiguously
resolving one of them.

Analyze, Search, Compare, and Merge accept guided selectors. Search ranks
content within the matching set; it does not guarantee whole-document coverage.
Compare uses the newest match as Source and requires at least two matches.
With `on_empty: report`, no matching documents produces an informational result
without a processing-model/native-merge call. Explicit output contracts still
apply; the implementation does not manufacture documents or structured records.
Legacy recent actions keep their prior empty-selection behavior.

## Preview APIs and editor

- `POST /api/user/workflows/document-selection/preview`
- `POST /api/group/workflows/document-selection/preview?group_id=<explicit-group>`

Both require the existing login, user, workflow enablement, and management
policies. A group task is restricted to its own group. Responses contain an
advisory exact count, limit, cutoff, and at most 50 safe document descriptors;
they expose neither settings nor storage locators. Over-limit responses use
422 with a lower-bound count and `count_exact: false`; incomplete capture does
not claim an exact count.

In the V2 editor's visible Documents section, choose an action, then Recent
documents by criteria. Discover workspaces by source kind and name, Add them,
and review the separate Remove list. All authorized metadata remains searchable,
with at most 25 rendered results and a separate 20-selected-workspace limit.
Then choose the event, units, and metadata conditions. Help, examples, searchable
tag/type choices, a Boolean summary, and preview explain what each condition
does. Changed configuration invalidates the old preview.
An unavailable workspace can be removed without losing the other filters.
Malformed saved selectors have an explicit reset action rather than crashing
the editor.

The UI is implemented in `WorkflowDocumentSelection.tsx`, with the pure
frontend contract in `workflowDocumentSelection.ts`. Save normalization is in
`functions_document_actions.py`; runtime capture and dispatch are in
`functions_workflow_runner.py`. Classic editors retain their existing controls
with the updated one-year recent-window bound.

## Ask AI

Ask AI uses authorized workspace handles, never raw workspace IDs, to author
Analyze/Search/Compare/Merge selectors. Window and individual-filter follow-ups
have targeted operations that preserve other filters and tasks. Merge output
settings/options and broader scoped Search also have closed operations.

Clear edits may include a separate clarification question. An incomplete new
goal leaves execution details unresolved rather than inventing a time, window,
or workspace. The user reviews and saves the resulting draft; the assistant
does not save, enable, or run it.

Known instructions and selectors are authored even when only the schedule time
is missing. A separate draft-calendar contract accepts the requested recurrence
with blank time; the executable schedule normalizer still rejects it.

## Opt-in runtime choice

`type: choose` is accepted only by workflow-task normalization. It requires a
guided recent selection or selected `document_sources` carrying exact scope and
document identity. It cannot use broad Search or all-files mode. Selection uses
the smallest enabled action limit, then rechecks the chosen action's own limit
without truncation.

`functions_workflow_action_choice.py` projects eligible capabilities and opaque
document handles into action-specific closed schemas. The model returns one
action or a structured refusal; it supplies neither raw IDs/scopes nor output
destinations, task mutations, arbitrary steps or tools. Compare handles must
cover the captured set exactly. Merge is eligible only with explicit authored
kind/format and compatible extensions. Metadata is untrusted data.

The runner retains the capture and decision in task/visit units, including
refusals and malformed/incomplete model outcomes. Resume checks permissions,
source proofs, enabled capabilities and digests; missing retained state cannot
trigger a new decision. Processing uses model-only document runners with agent
tools and URL access disabled. The selected-input reader fence refuses unknown
IDs for runtime-choice actions.
An interrupted decision with unknown outcome, or a retained provider failure,
also requires a new run. The same visit does not silently issue another choice.

Results/history expose `document_action_choice`: action, bounded public summary,
input count and `selection_token_usage`. Token totals include selection cost
once, even for Merge. Refusals use existing safe task failures, not background
elicitation. An empty report-policy capture makes no selection or processing call.
Frozen plan replay is not changed.

## Validation and limitations

`functional_tests/test_workflow_document_selection.py` covers Boolean truth
tables, time/case/regex boundaries, complete authorized paging, filter-before-
limit behavior, task snapshots, resume authorization, native scope binding, and
typed conversational edits. Preview policy tests are in
`functional_tests/route_tests/test_workflow_document_selection_policy.py`.
`functional_tests/test_workflow_goal_first_authoring.py` covers partial calendars,
3/10/16/64 operations, upload-time semantics, every runtime action, strict
decision validation, selected/scoped authorization and retry/resume integrity.

`ui_tests/test_v2_workflow_document_selection.py` exercises the production bundle
at mobile and desktop widths, exact save payloads, explanatory controls,
escaped filenames, preview invalidation, and visible error/empty states.

Preview is advisory: documents can change between preview and execution.
Regexes are evaluated only on the server. Read
[the workflow guide](../../guides/create-a-workflow.md#rolling-documents-for-each-task)
for usage.
