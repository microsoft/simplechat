# V2 Tabular Analysis

## Overview

Tabular analysis always worked in the React V2 interface. Asking a question about a
spreadsheet returned a real answer, because the analysis runs server-side on the same
`/api/chat` stream V2 already used.

What was missing was everything the analysis *produced*. `REACT_V2_UI.md` recorded it as
"tabular runs... are not wired", and the practical effect was worse than that sounds: a
request for an export created the file, told the user it had created it, and then offered
nothing to open it with. The file was in storage the whole time. Nothing in the interface led
to it, and the reply's own text asserted otherwise, so the failure was invisible.

This change closes that gap and five smaller ones around it. Implemented in version
**0.261.057**.

### Dependencies

None added. Every route and payload this uses already existed and is unchanged; the work is
entirely in `application/v2_ui`.

## What was missing

| Gap | Legacy source | State before |
|---|---|---|
| Generated artifact cards | `chat-messages.js` | Nothing |
| Durable run status, resume and cancel | `chat-messages.js` | Nothing |
| Progress lane in reasoning steps | `chat-thoughts.js` | Flattened to a list |
| Large-run confirmation | `chat-messages.js` | Nothing |
| Chat-upload preview and download | `chat-input-actions.js` | File name only |
| Tabular tool-result row bands | `chat-citations.js` | Full JSON dump |

The enhanced-citation tabular viewer — sheet switcher, truncation notice, download — was
already at parity and is unchanged.

## Architecture

Behaviour lives in pure modules under `src/lib`, and rendering in components that consume
them. The split is what lets the normalising, the download-target choice, the progress
arithmetic and the confirmation heuristic be tested without a DOM.

```
lib/generatedArtifacts.ts   Reading, normalising and de-duplicating artifact metadata;
                            download targets; durable run progress arithmetic
lib/activityLanes.ts        Folding reasoning steps into a progress report
lib/tabularRunEstimate.ts   The large-run confirmation heuristic
lib/agentCitationRows.ts    Row banding for tabular tool results
lib/csvPreview.ts           Parsing the CSV a chat upload returns

components/chat/GeneratedArtifactCard.tsx   The artifact card and its preview dialog
components/chat/TabularRunStatus.tsx        Live progress, resume and cancel
components/chat/LargeRunDialog.tsx          The confirmation
components/chat/ChatFilePreview.tsx         An uploaded file's contents
```

### The metadata contract

`_build_generated_analysis_metadata` in `route_backend_chats.py` writes two keys onto the
assistant message:

- `metadata.generated_analysis_artifacts` — every generated file
- `metadata.generated_tabular_outputs` — the tabular subset of the same records

A tabular export is written to **both**. `readGeneratedArtifacts` merges them and
de-duplicates on the same identifiers the server uses — `artifact_message_id`, then
`document_id`, then `export_run_id`, then file name and format — so an export appears once
rather than twice.

An artifact is only rendered if it names somewhere to fetch the file from. The one exception
is a run that ended `failed` or `canceled` while setting `suppress_assistant_table_export`:
that has nothing to download but must still be shown, because the turn suppressed its own
table in favour of a file that never arrived, and dropping the record would leave a reply
that silently lost both.

### Capabilities

The card is generic across the `capability` field rather than tabular-only, which is both
less work than a tabular-specific card and closes the same gap for other producers:

| Capability | Produced by | Layout |
|---|---|---|
| `tabular` | Tabular analysis exports | Compact when finished |
| `file_export` | Structured exports | Compact when finished |
| `analyze` | Analyze summaries | Preview collapsed |
| `comparison` | Document comparison | Preview collapsed |
| `analysis` | Deep Research ledgers and others | Preview inline |

A finished row-level export gets the compact layout: its file name and row count already say
what it is, so the summary, source note and inline preview are traded for a **View** control
that opens the preview full size when it is wanted. The two prose capabilities keep their
previews collapsed because they are long enough to push the reply off screen.

### Download targets

```
artifact_message_id + conversation_id  ->  /api/chat_artifacts/download
document_id                            ->  /api/workspace_documents/download
neither                                ->  no download control
```

The conversation copy is preferred over the workspace copy because it is the copy *this turn*
produced; the workspace copy may be a later revision. `conversation_id` falls back to the
message being rendered when the artifact does not carry its own.

Note that `/api/workspace_documents/download` is registered in `route_enhanced_citations.py`,
alongside the other blob-backed downloads, rather than in the documents blueprint.

### Durable runs

A large export returns as soon as it is queued and produces its file minutes later. The card
polls `GET /api/tabular/generated-output/runs/<run_id>` — first after two seconds, because a
small run often finishes almost immediately, then every ten.

Polling stops as soon as the run reaches a state it cannot leave on its own. A `failed` run
that the server marked `retryable_failure` keeps polling, because the worker may pick it up
again without anyone intervening; a terminal failure does not.

**Continue** and **Cancel** are shown only when the server's own `can_resume` and `can_cancel`
say so. Inferring them from the status would offer a control the endpoint then rejects with a
409.

A run reporting `completed` is not necessarily finished: its artifact set may still be
validating, or may have been rolled back. `isRunArtifactSetComplete` checks the set's
`lifecycle_state` and `validation_state` before the progress card is replaced with downloads.
A completed run that reports no member list promotes the artifact the card was built from,
rather than leaving a full progress bar with nothing to download.

Members are read from `generated_artifacts`, falling back to the singular
`generated_artifact` and then to the legacy collections. **`artifact_set` is a summary** —
`member_count`, `lifecycle_state`, `primary_artifact_id` — and carries no member list, so
reading members from it finds none and quietly reduces a combined run, which produces both an
analysis summary and a structured export, to a single card. The primary analysis is sorted
first, because it is what the reply is about and the export is its appendix.

### Approval

A file generated in a shared conversation would become available to every participant, so the
conversation's owner decides first. While it is staged the server withholds the content from
everyone, including the person who asked for it, and `/api/chat_artifacts/download` answers
403.

The card therefore replaces its download and preview controls with a banner explaining the
state, and offers Approve and Deny to a viewer the server marks `viewer_can_approve`. Leaving
the download button visible would render a control that cannot work and says nothing about
why.

### Progress lanes

A *lane* is a named kind of staged work. Lanes are declared in one table in
`activityLanes.ts` rather than branched on at the call site, so adding workflow activity later
is a table entry rather than a second copy of the progress card.

A lane opens on any of:

- a thought `step_type` the lane claims — `tabular_analysis`
- `activity.kind` — `tabular_tool_invocation`, `tabular_post_processing`
- `activity.lane_key` — `tabular`
- `activity.plugin_name` — `TabularProcessingPlugin`

Tabular is the first consumer; the agent lane is declared alongside it because the same
payloads already describe both. A tabular turn opens with the agent hand-off sentence, so a
more specific lane supersedes the general agent one — otherwise a workbook run would be
labelled "Agent progress".

Every activity is emitted at least twice, running then completed, keyed by `activity_key`.
They are folded into a map so a tool call is counted once rather than once per frame.

**A lane that declares post-processing needs to see it before reporting completion.** Because
each invocation settles before the next begins, there is a moment between tool calls when no
activity is running. Treating that as done makes the lane announce "Tabular analysis complete"
at 100% mid-run and then fall back when the next call arrives. The agent lane, which declares
no post-processing, uses the plain rule.

**The bar ratchets.** Recomputing the percentage from scratch would let it run backwards:
finishing two of two activities reads as 80%, and a third activity starting computes as 50%.
The fold carries the highest value reached, which keeps it a pure function of the step list
rather than component state.

### The large-run confirmation

Fires only when a prompt asks for row-level output **and** asks for a file **and** names a
count over the threshold. All three are required because a confirmation that appears on
ordinary questions gets clicked through without being read, which is worse than not asking.

The estimate is taken **before** the message is dispatched and before the composer is
cleared, so declining leaves the typed prompt exactly where it was to be edited.

## Configuration

| Setting | Default | Effect |
|---|---|---|
| `enable_tabular_durable_run_confirmation` | `true` | Whether the confirmation is offered at all |
| `tabular_durable_run_confirmation_threshold_rows` | `500` | Row count above which a run is confirmed |
| `tabular_durable_run_confirmation_threshold_batches` | `75` | Batch count above which a run is confirmed |
| `tabular_generated_output_max_batch_rows` | `50` | Used to estimate batches from rows |

These reach the browser through `/api/v2/bootstrap`, which returns
`sanitize_settings_for_user(settings)`. They are deliberately **not** in
`TABULAR_GENERATION_BACKEND_SETTING_KEYS`; adding them there would strip them from the
payload, and the dialog would silently fall back to its defaults on every installation.

The confirmation is opt-out. Only an explicit `false` disables it, because a missing key means
the setting has never been written, not that it is off.

## API surface

No routes were added or changed. Those consumed:

| Route | Used for |
|---|---|
| `GET /api/chat_artifacts/download` | Conversation-scoped artifact download |
| `GET /api/workspace_documents/download` | Workspace-scoped artifact download |
| `GET /api/tabular/generated-output/runs/<run_id>` | Durable run progress |
| `POST /api/tabular/generated-output/runs/<run_id>/resume` | Requeue a stalled run |
| `POST /api/tabular/generated-output/runs/<run_id>/cancel` | Stop a run |
| `POST /api/get_file_content` | An uploaded file's extracted content |
| `GET /api/enhanced_citations/tabular` | The original of an uploaded spreadsheet |

## Usage

Nothing to enable. The cards appear whenever a turn produces a file, which requires the
tabular processing plugin and its Enhanced Citations dependency to be configured as usual.

**A generated export.** Ask for one; the reply is followed by a card with the row count,
where it was saved, a preview and a download.

**A long export.** The card shows a progress bar and what the run is currently doing, and
offers Continue or Cancel where the server allows them. It replaces itself with the finished
files.

**A run being analysed.** The reasoning panel shows a progress card above the steps while the
run is live, without needing to be expanded.

**An uploaded spreadsheet.** Click its name in the thread to see it as a table, with
**Download original** when the original file is still in storage. The name is inert in a
shared conversation and on a tenant with the user workspace disabled, because
`/api/get_file_content` reads the personal conversations container and is gated on
`enable_user_workspace` — it would fail rather than explain.

**A tool result with many rows.** Open the message inspector's Sources section; the result
states how many rows matched and shows the first few, with controls for 25 or all.

## Testing and validation

| Test | Covers |
|---|---|
| `functional_tests/test_v2_tabular_parity.py` | The client reads the metadata keys the server writes; every requested route is registered; the run-control routes carry their decorators; the confirmation thresholds survive sanitization; the thought frame fields are carried; every component is mounted; the confirmation precedes the send; run members are read from the key the server sends; a withheld file offers no download; the upload preview is gated on what the endpoint supports; no remote assets |
| `functional_tests/test_v2_tabular_parity_logic.ts` | 70 behavioural checks: normalising and de-duplication, download target selection, the compact-layout rule, preview table construction, run progress and polling, artifact set completion and member ordering, approval states, lane detection and counting, the completion rule, the progress ratchet, the confirmation heuristic, row banding, CSV parsing |

Both are run by executing the Python file, which bundles the TypeScript with esbuild and runs
it under node, skipping that half when `application/v2_ui/node_modules` is absent.

### Known limitations

- **"Add to Workspace" and "Create PowerPoint" are not carried over.** The classic card offers
  both. Promotion (`/api/chat_artifacts/promote`) and the Markdown-to-PowerPoint path depend
  on the classic export module, and are better rebuilt with V2's own export machinery than
  ported.
- **The Markdown "View" opens the stored preview, not the full file.** The preview is what the
  metadata carries; the complete artifact is a download away.
- **An uploaded file cannot be previewed in a shared conversation.** `/api/get_file_content`
  is personal-only, and there is no collaboration-aware equivalent; the file name is left
  inert there rather than offering a control that always fails.
- **Non-boolean tabular admin settings are still not editable in V2.** That is the general
  "admin settings edits boolean capabilities only" limitation rather than anything specific to
  tabular, and is unchanged by this work.
- **Progress lanes cover tabular and agent work only.** Workflow activity emits compatible
  payloads but is not yet wired end to end, so it has no lane entry.

## See also

- [React V2 User Interface](REACT_V2_UI.md)
- [Tabular Background Generated Exports](TABULAR_BACKGROUND_GENERATED_EXPORTS.md)
- [Tabular Generated Output Exports](v0.241.120/TABULAR_GENERATED_OUTPUT_EXPORTS.md)
