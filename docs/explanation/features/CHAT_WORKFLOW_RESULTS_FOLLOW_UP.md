# Workflow results in chat

Implemented in version: **0.261.214**.

Application version tracking: `application\single_app\config.py`.

Related issue: #1546 (part 6a), part of #1543. Builds on
[V2 workflow alert notices](V2_WORKFLOW_ALERT_NOTICES.md) (#1567) and the V2
run history link (#1562). The
[Chat orchestration workflows roadmap](CHAT_ORCHESTRATION_WORKFLOWS_ROADMAP.md)
describes all the phases; this is the first part of Phase 6.

## Overview and dependencies

A workflow such as a weekly digest does its work on a schedule and stores what
it found. Until this version, the only place to read that result was the run
history in Workflows. To ask a question about it, the user had to copy the
output into chat or run the workflow again.

With **Use Workflow Results In Chat** on, a user can ask chat about the stored
result of one of their own finished personal workflow runs. **Ask in chat** on a
run in the V2 run history, or **Ask about this** on a workflow alert, opens a
new chat with that run selected. Each answer:

- uses only that run's stored result. The workflow isn't re-run, and nothing
  else is searched, browsed or called.
- treats the run's output as untrusted data, never as instructions.
- ends with a fixed line, written by the server, that names the run, for
  example "_This answer uses the stored result of the Weekly digest run of Mon
  Jun 2, 2025, 9:02 AM CDT. The workflow was not re-run._"
- reads the result again on every turn, and answers only if it's still the
  result the user selected.
- stops showing in V2 once that result is no longer available to its owner.

What this version adds:

- **A result reader**, `functions_workflow_result_reader.py`. It authorizes one
  finished personal run as its owner, binds the result to a digest, and returns
  a public descriptor and, for Follow up only, bounded excerpts.
- **A descriptor route**,
  `GET /api/user/workflows/<workflow_id>/runs/<run_id>/result-context`, that the
  V2 entry points read before selecting a run.
- **Follow up**, `functions_workflow_result_followup.py`: the chat path that
  answers a question from the selected run's stored result.
- **Masking on read.** An answer built from a workflow result is withheld once
  the result is unavailable, or once the chat is no longer the owner's private
  chat, on every read that already withholds saved analyses. A few older reads
  that only the chat's owner can reach don't mask yet; see
  [Known limitations](#known-limitations).
- **Withheld collaboration copies.** Converting a chat to a collaboration stores
  its Follow up answers withheld, and doesn't carry the chat summary over.
- **V2 entry points**: the composer chip, **Ask in chat**, **Ask about this**,
  and `followUpWorkflowResult` for Phase 6b's delivered message, run card and
  recurring-workflow card.
- **The admin setting** `enable_chat_workflow_results`, off by default.

Not in this version:

- **The `workflow_results` orchestration capability**, which lets an
  orchestrated plan read a run ("What did my digest find last Monday?"). It
  builds on Phase 5's workflow planning context (0.261.212) and on this reader,
  and it shipped in 0.261.217; see
  [Chat orchestration workflow results](CHAT_ORCHESTRATION_WORKFLOW_RESULTS.md).
- Phase 6b's post-back delivery, run card, recurring-workflow card and chat-list
  indicator, and Phase 6c's in-plan wait.

Dependencies:

- Personal workflows (`allow_user_workflows`). When
  `require_member_of_workflow_user` is on, the user also needs the
  `WorkflowUser` app role.
- Durable task results. A run's tasks must have stored their results through the
  workflow result contract (`workflow-result-v1`, with a `result_ref`). Older
  runs keep previews only, and can't be asked about.
- The V2 interface, for the entry points and the chip. Chat orchestration
  (`enable_chat_orchestration`) isn't needed.

## Technical specifications

### Architecture

1. An entry point calls `openWorkflowResultInChat(workflowId, runId, ...)`,
   which opens a new chat and reads the run's descriptor from the descriptor
   route.
2. The reader authorizes the whole run as its owner and computes the digest.
   The route returns only the public descriptor.
3. The composer shows the chip. The first question creates the chat and sends
   `workflow_result_context: {workflow_id, run_id, result_sha256}` with every
   other source off.
4. Follow up checks the gate and the chat's privacy, reads the result again with
   the selected digest and excerpts, and asks the selected model or local agent,
   with tools off, to answer from a fenced block of run output.
5. The answer is saved with the disclosure line, the public descriptor and the
   accumulated result contexts.
6. Every later read through the shared sanitizer re-checks privacy and each
   result the answer relied on, and withholds the answer if either fails.

### Gates

| Surface | Needs |
| --- | --- |
| Descriptor route | Signed in, `allow_user_workflows`, the `WorkflowUser` rule, and `enable_chat_workflow_results`. `workflow_results_required` refuses with 403 `workflow_results_disabled`. |
| Follow up | The same gate, checked on every turn, plus the requester's own private personal conversation. |
| V2 entry points and chip | The bootstrap flag `features.enable_chat_workflow_results`. |
| Masking | Nothing. It always runs, so turning the setting off never reveals a withheld answer. |

`is_chat_workflow_results_enabled_for_user(settings, user_roles)` is true only
when the setting is a real `True` and `is_user_workflows_enabled_for_user`
passes. The V2 bootstrap reports that combined decision in its per-user
overrides, so the raw setting never shows a button to someone the server would
refuse. The flag only hides UI; every server path checks again.

### The reader

`read_workflow_result(user_id, workflow_id, run_id, *, expected_sha256=None,
include_excerpts=False, excerpt_budget_bytes=DEFAULT_EXCERPT_BUDGET_BYTES, ...)`
is Flask-free. Its containers, result loader, page reader and source resolver
can be injected.

1. **Point reads in the requester's partition.** The reader reads the workflow
   and the run with `read_item`, not with the getters that turn a storage error
   into "not found". A missing workflow or run, a run of a different workflow, a
   group workflow, a workflow being deleted, or a record owned by someone else
   gives 404 `workflow_result_not_found`. Because the read happens in the
   requester's own partition, someone else's run answers exactly like a missing
   one. A storage error gives 503 `workflow_result_storage_unavailable`.
2. **Structured runs are closed.** A version-3 definition, a runtime
   `schema_version` of 2, a `workflow_outputs` field, or any
   `workflow-result-v2` task result gives 409 `workflow_result_unsupported`.
   Their outputs need an exact node, execution and attempt selector.
3. **Status.** `completed` and `completed_partial` are readable. `failed`,
   `invalid`, `incomplete`, `cancelled` and `skipped` give 409
   `workflow_result_not_finished`. Any other status, for a run that is still
   queued or running, gives 409 `workflow_result_in_progress`.
4. **Task rows.** One single-partition query on the run-items container reads
   the task items, projecting only `workflow_id`, `run_id`, `task_id`,
   `task_order`, `status`, `item_type`, `label` and `workflow_result`. A query
   failure gives 503, never an empty result, and more than 200 rows gives 409
   `workflow_result_invalid`. The eligible tasks are those that `succeeded` with
   a `workflow-result-v1` `result_ref` and its SHA-256, ordered by
   `(task_order, task_id)`. No eligible task gives 409
   `workflow_result_preview_only`.
5. **The digest**, described below. A caller's `expected_sha256` that doesn't
   match gives 409 `workflow_result_changed`.
6. **Authorization.** `authorize_workflow_run_read(workflow, run_id,
   reader_user_id=user_id, result_items=<the same rows>, load_result=<a
   memoizing loader>)` checks the whole run the way run history does, including
   every stored task result and its analysis sources. Each eligible task's
   manifest must then name the same workflow, run, task and authoritative
   output, and pass the runner's own completion rule
   (`_require_completed_result`), which accepts a partial result only in a
   `completed_partial` run.
7. **Excerpts**, only when Follow up asks for them.

#### What the result is

The result is every eligible task's **authoritative output**, in run order.
Named, non-authoritative outputs aren't included yet.

#### The digest

`result_sha256` is the SHA-256 of this document, as canonical JSON (sorted keys,
compact separators, ASCII), over every eligible task:

```json
{"version": "workflow-result-v1", "workflow_id": "...", "run_id": "...", "status": "completed",
 "outputs": [["<task_id>", "<authoritative output name>", "<result_ref sha256>"]]}
```

A task's `result_ref` SHA-256 covers its stored manifest, which covers every
output the task wrote, so rewriting any included result changes the digest. The
digest doesn't depend on the excerpt budget, and it's computed from the same
rows that authorization checks.

No readable run can change in place today: `resume-failed` resumes only
`failed`, `invalid` and `incomplete` runs, and the non-durable path starts a new
run. The digest guards against any future in-place rewrite. The tests simulate
one by changing a stored `result_ref` SHA-256.

#### Excerpts and the budget

A run's result can reach 500 MB, so Follow up reads a bounded excerpt:

- **48 KB in total, and at most 8 outputs.** The final task's output comes
  first. When other outputs follow, it gets up to half the budget, and the rest
  share what remains in run order. An output that would get less than 512 bytes
  is left out.
- **Text** is cut at a UTF-8 character boundary. **Record outputs** are read a
  page at a time, up to 8 pages, one record per line. An output of up to 256 KB
  is loaded whole, so the store verifies its SHA-256. A larger one is read as a
  single bounded page, and the start of its value is taken from that page, with
  a text value cut mid-escape decoded leniently.
- **Notes inside the fence.** Each cut output is followed by a note, such as
  "[Excerpt truncated: the first 24 KB of 310 KB.]" or "[Excerpt truncated: the
  first 40 of 1200 records.]", and outputs left out are counted.
- **Model fit.** When the result and the chat history don't fit the selected
  model, Follow up reads the excerpt again at 24, 12 and then 6 KB before it
  refuses with `workflow_result_too_large`. An answer from saved analyses isn't
  read again smaller; it's refused at once. The context budget is checked before
  any model request is sent.
- **Only a task label, an output kind and text reach the model.** No store
  reference, producer id, workflow id or run id does.

**Saved analyses in a result.** An Analyze task's output is a saved analysis,
and it's read through the Analyze machinery rather than as text:
`load_workflow_task_input(..., bounded=True)` returns a `SavedAnalysisInput`,
and `_invoke_saved_analysis_chat_reply(..., saved_inputs=...)` explains it and
checks the explanation against the saved records. The same analysis is read only
once. When a run holds both saved analyses and plain outputs, the answer uses
the saved analyses only, because those record checks would reject statements
taken from plain text, and the disclosure says so. A report that combines
several saved analyses can't stand in for them, so it's left out and disclosed.
A run made only of such reports gives 409 `workflow_result_unsupported`.

#### The public descriptor

```json
{"version": "workflow-result-v1", "workflow_id": "...", "run_id": "...",
 "workflow_name": "Weekly digest", "status": "completed",
 "completed_at": "2025-06-02T14:02:00+00:00", "result_sha256": "<64 hex characters>",
 "available": true}
```

`workflow_name` is the workflow's current name, cleaned to one printable line of
at most 80 characters. It's user-authored text, and V2 only ever renders it as
text. The descriptor carries no store reference, excerpt or task detail.

### The descriptor route

`GET /api/user/workflows/<workflow_id>/runs/<run_id>/result-context`, in
`route_backend_workflows.py`.

- **Decorators:** `swagger_route`, `login_required`, `user_required`,
  `enabled_required('allow_user_workflows')`, `workflow_user_required` and
  `workflow_results_required`.
- **Body:** runs the reader without excerpts, so the whole run is authorized,
  and returns `{"workflow_result": <descriptor>}`. A closed reason returns
  `{"error": <fixed wording>, "code": <code>}` with its status.
- **Caching:** `Cache-Control: no-store, private`, because access is re-checked
  on every read.

Every V2 entry point reads the descriptor fresh rather than trusting one it was
handed, so the chip always names the result as it is now.

### Follow up

**The request.** A chat request carries `workflow_result_context:
{workflow_id, run_id, result_sha256}`, the only selector a browser sends, and,
from V2, the browser's IANA `time_zone`.

**Dispatch.** `run_workflow_result_follow_up(services, data, ...)` in
`functions_workflow_result_followup.py` holds the flow.
`route_backend_chats.py` adds a thin nested wrapper,
`execute_workflow_result_chat_request`, that passes in the route's own
persistence, screening, history and model helpers. It's dispatched ahead of
saved analysis wherever a request can carry an `analysis_result_context`: the
document-action executor, `POST /api/chat` and the streaming chat route. The
streaming chat, document-action stream and Analyze stream routes run
`workflow_result_request_precheck` first, so a disabled, conflicting, malformed
or retried request is refused before any conversation is created or stream
opened. Those routes also don't reserve an Analyze message id for a
workflow-result request.

**One turn:**

1. **Gate and context**, in this order. A request carrying both a saved analysis
   and a workflow result gives 400 `workflow_result_context_conflict`. A failed
   gate gives 403 `workflow_results_disabled`, before the context is validated.
   A malformed context gives 400 `workflow_result_invalid_context`, and a
   request that also carries a retry or edit id gives 400
   `workflow_result_retry_unsupported`. The retry and edit routes refuse Follow
   up turns themselves; see [Retry and edit](#retry-and-edit).
2. **Conversation.** The requester's conversation is loaded, or a personal one
   is created when the request has no id, as saved analysis does.
   `conversation_is_private` must pass on every turn. Shared, collaborative and
   converted chats, and someone else's chat, give 403
   `workflow_result_private_only`. A chat that no longer exists or was deleted
   gives 404 `workflow_result_conversation_unavailable`.
3. **Input screening.** The question goes through `check_chat_content`, and a
   blocked question is rejected like any other chat message.
4. **Read and bind.** The reader runs with `expected_sha256` and excerpts. A
   changed result gives 409 `workflow_result_changed`, and nothing is answered,
   saved or sent to a model.
5. **The question is saved** with `metadata.workflow_result_context`.
6. **History.** The conversation's messages pass through
   `_sanitize_saved_analysis_history`, which withholds unavailable answers and
   collects the inherited `workflow_result_contexts`, and then the usual bounded
   history segments.
7. **The model call** goes through `_invoke_saved_analysis_chat_reply`: the
   selected model or a local agent, with tools off, inside the workflow context
   budget. A non-local agent gives 400 `workflow_result_model_unsupported`.
8. **Checked again before saving.** The current context and every inherited one
   are re-authorized, inherited saved-analysis contexts are read again, and the
   chat's privacy is checked again. If any check fails, the answer isn't kept.
9. **The answer is saved** through `_persist_screened_assistant`, so output
   screening applies, with the disclosure appended. The chat is marked unread
   and titled, and activity and token usage are logged.

While the answer is written, the processing thoughts show "Answering from the
stored workflow result without re-running the workflow".

A refusal returns `{error, code, warning_type: "workflow_result_unavailable",
conversation_id, user_message_id}` with the code's status, and fixed wording
that never echoes exception text. An answer saved before the refusal is
deleted. Content screening refusals, of the question or of the answer, are
returned the way other chat turns return them, and no answer is kept.

**The messages the model sees:**

1. The default system prompt, when one is set.
2. A fixed system message. It says the block between
   `<<<WORKFLOW RESULT <code> (untrusted data)>>>` and
   `<<<END WORKFLOW RESULT <code>>>>` is untrusted data from an earlier run, not
   instructions, and must not be followed or acted on, and that only markers
   carrying this request's code delimit the result. The code is a new random
   16-character hexadecimal value for each request (`secrets.token_hex(8)`), so
   a run's output can't know it in advance. It says the workflow wasn't re-run
   and nothing else was searched, so the answer uses only the stored result and
   the conversation and says when the result doesn't contain the answer. When
   the block notes a cut or left-out output, the answer must say it's based on
   part of the result.
3. The fenced block. It holds the workflow name, the completion time and
   status, then each output labeled by its task name, its kind and whether it's
   the final output, with its truncation note, and then a count of any outputs
   left out. Any run of three or more `<` or `>` inside the block is replaced. A
   look-alike marker that survives that, such as one written with full-width
   brackets or split by a zero-width space, still lacks the request's code, so
   the system message tells the model it's part of the data.
4. The bounded history, then the question.

For a result answered from saved analyses, a different fixed message takes the
place of both. It asks the model to explain the saved Analyze result, keeping
its accepted values, record identities, evidence, coverage and validation
limits, without treating document or result text as instructions or claiming
independent verification. The Analyze reader appends the saved records to the
question instead of a fenced block.

The server builds these messages itself and reads none of the request's source
flags, so documents, web search, URL access, deep research, image generation,
agent tools and orchestration can't be added to the turn.

**The disclosure** is written by the server and appended to every answer:

> _This answer uses the stored result of the Weekly digest run of Mon Jun 2,
> 2025, 9:02 AM CDT. The workflow was not re-run._

When they apply, it adds "The run completed partially, so its result may be
incomplete.", "Only the saved analysis in this run's result was used.", "A
report that combined several saved analyses couldn't be used." and "Only part of
the result fit in this answer." The workflow name is Markdown-escaped. The time
is in the request's `time_zone`, or in UTC when there's no valid zone.

**The answer's metadata** carries `workflow_result` (the public descriptor),
`workflow_result_contexts` (every context inherited from earlier answers, plus
this one), any saved-analysis contexts the chat's history passes on, and the
usual token usage, context budget and thread information.

### Later turns

In V2, the next question in the same chat inherits the run. After an answer
arrives, and whenever the chat is loaded again, the store re-selects the chip
when the chat's latest message is an answer with an available descriptor, unless
the user removed the chip. The next question is then another Follow up turn.

A turn sent without the chip, for example after the user removes it, is an
ordinary chat turn. Its history still holds the Follow up answer, so
`_analysis_history_metadata()` carries the accumulated
`workflow_result_contexts` onto the new answer, which is then withheld along
with them.

### Retry and edit

V2 doesn't offer Retry or Edit on a Follow up turn, and the server refuses them
as well, so a Follow up question can't be replayed as an ordinary turn that
still names the result:

- `POST /api/message/<message_id>/retry` refuses when the retried message, or
  the question that opened its thread, carries `workflow_result` or
  `workflow_result_context`. Retrying the answer or the question is refused the
  same way.
- `POST /api/message/<message_id>/edit` refuses when the edited message carries
  either key.

Both give 400 `workflow_result_retry_unsupported` with the reader's fixed
wording. The refusal comes right after the ownership checks, before content
screening, so a refused request writes nothing: no blocked-attempt record, no
new attempt, and no change to the active thread.

A later ordinary answer that only inherited the lineage
(`workflow_result_contexts`) isn't a Follow up turn, and retrying it is
allowed. It replays its ordinary question through the usual history sanitize,
so the new answer carries the contexts of every Follow up answer it can still
see, and is masked on the same terms.

### Masking on read

`sanitize_saved_analysis_messages(messages, user_id, ...)` in
`functions_saved_analysis.py` now also recognizes a message that carries
`workflow_result`, `workflow_result_context` or `workflow_result_contexts`. Such
a message is shown only when both of these hold:

- its conversation is the reader's own private personal chat
  (`conversation_is_private`, on a point read of the conversation).
- every workflow result it relied on still authorizes for the reader exactly as
  selected (`authorize_workflow_result_context`: the reader, without excerpts,
  bound to the stored digest).

A message whose stored contexts are malformed is withheld without any read.
Otherwise:

- **An answer** keeps only its id, conversation, role, timestamp, model and
  agent names, thread and user information and masking ranges, and, for a
  collaboration copy, its sender, message kind, reply position and source
  message id. Its content becomes "This answer is unavailable because access to
  the workflow result it used could not be confirmed.", its citations and
  thoughts are emptied, and its metadata holds only
  `workflow_result: {version, available: false}`, with no ids, name or
  contexts.
- **A question** keeps its text. Only the three workflow keys are removed from
  its metadata.

Both forms come from `withhold_workflow_result_message` in
`functions_workflow_result_masking.py`. That module has no application imports,
so collaboration storage can use it without importing the reader, and a
withheld answer looks the same wherever it's withheld.

Every exception masks, a storage failure included, and nothing is raised out of
the read. Each distinct result is authorized once, and each distinct chat is
read once, per call. Messages that don't use a workflow result cost nothing, and
the existing saved-analysis logic runs unchanged on the messages that pass.

Because the check is in the shared sanitizer, it covers every read site that
already withholds saved analyses: chat history for the model, the V2
conversation messages route (`/api/get_messages`) and search, whole-conversation
export, collaboration, and the orchestration history readers.
`is_saved_analysis_unavailable` also recognizes
`workflow_result.available: false`, and `authorize_saved_analysis_message_read`
refuses message-derived views, such as thoughts, of an answer whose result is
unavailable. Single-message exports (Word, the email draft, and the PowerPoint
and generated-file paths) load their message through
`_load_export_message_for_user`, which now calls
`authorize_saved_analysis_message_read` and so checks both lineages; before,
it only re-read saved analyses. Conversation search skips its cache when a
match uses a workflow result, as it does for saved analyses, so a cached
snippet can't outlive access. A few older reads that only the chat's owner can
reach don't run the sanitizer yet; see [Known limitations](#known-limitations).

Masking re-checks access to the result, not the feature entitlement. Turning the
setting off, or losing the `WorkflowUser` role, stops new questions but doesn't
hide earlier answers, as with saved analyses that workflows produce.

### Privacy

Workflow results are personal, and they never reach a shared chat. Follow up
refuses any conversation that isn't the requester's own private personal chat,
on every turn, and masking applies the same rule on read. Converting a chat to a
collaboration copies its messages, and the collaboration AI bridge feeds the
source chat's history to shared replies, so **once a chat is shared or converted
to a collaboration, its Follow up answers are hidden for everyone, you
included.** The original chat's stored messages are unchanged. The
collaboration's copies are stored with these answers withheld, and the chat's
saved summary is cleared on both chats. Relaxing the rule later would show the
original chat's answers again, but not the collaboration's copies or the
cleared summary.

### Collaboration copies

Participants read a collaboration's copies directly, and several of those reads
never pass through the sanitizer: the collaboration metadata route (pending
invitees included), collaboration summaries, reply previews and MCP
collaboration reads. So conversion withholds the answers when it writes the
copies, in `functions_collaboration.py`:

- `_copy_legacy_personal_messages_to_collaboration` replaces every message that
  uses a workflow result with its withheld form before it builds the
  collaboration message, so `last_message_preview` is built from the withheld
  form as well. It doesn't ask the lineage check, because the source chat is
  marked converted only at the end of the conversion, so the check would still
  allow the message. An answer that only inherited the context is withheld too,
  and a question keeps its text without the three keys. The copies are built
  from the messages `prepare_m365_history_publication` returns, so that path is
  withheld the same way.
- When any copied message uses a workflow result,
  `_carry_summary_into_collaboration` stores the collaboration's `summary` as
  `None`, with the key present, and clears the source chat's summary. The
  conversion's final write, which marks the source converted, saves the cleared
  summary. The helper runs after `prepare_m365_history_publication`, so
  clearing the summary doesn't change what the publication covers.
  `ensure_collaboration_source_conversation` and
  `sync_collaboration_conversation_metadata_from_source`, which runs after each
  AI-bridge reply, then have no summary to bring back.
- `build_collaboration_message_metadata_payload`, which merges in the source
  message's metadata, and `mirror_source_message_to_collaboration`, which copies
  a later source message into the collaboration, withhold a source message that
  uses a workflow result first.

The group route, `ensure_group_collaboration_for_legacy_conversation`, can also
convert a personal chat that only group context classifies, such as a
`group-single-user` chat. That chat is still its owner's private personal chat,
so Follow up runs in it. For such a chat the route falls back to the personal
store and `_copy_legacy_personal_messages_to_collaboration`, and both
conversions decide the summary through `_carry_summary_into_collaboration`, so
the two can't drift. A chat stored in the group container can't hold Follow up
messages, so its messages and summary are copied as before.

Orchestration history (`normalize_history_message` in
`functions_orchestration_context.py`) skips Follow up answers and every later
answer that inherited their context, and `validate_conversation_snapshot`
rejects a snapshot that names one. The user's own questions stay in it.

### V2

| File | What it does |
| --- | --- |
| `lib/workflowResults.ts` | Descriptor parsing and validation, `latestWorkflowResult`, and `applyWorkflowResultContext`. That last one applies only when the selection belongs to the chat the request is for; it adds the context and `time_zone`, turns every other source off, and removes the saved-analysis, document-action, orchestration and image fields. Also the refusal wording and which refusals remove the chip, the descriptor read, the chip's sentence, and `canAskAboutWorkflowRun`. |
| `lib/workflowResultFollowUp.ts` | `openWorkflowResultInChat(workflowId, runId, navigation)`, which every entry point uses, and `followUpWorkflowResult(descriptor, navigation)`, the seam for Phase 6b's delivered message, run card and recurring-workflow card. Only the run's identity is used, and the descriptor is read again. |
| `lib/conversationUrl.ts` | The one-shot `result_workflow_id` and `result_run_id` parameters. They're read only with `new=1`, and `syncedConversationParams` strips them. |
| `stores/chatStore.ts` | `workflowResultContext` beside `analysisResultContext`; selecting one clears the other. `launchWorkflowResult` starts a new chat and selects the run for the chat the first question creates. Choosing a source, uploading or switching chats clears it, and loading a chat re-selects it from the latest answer unless the user removed it. A refusal that means the run can't be asked about as selected removes the chip and shows the reason. Retry and Edit on a Follow up turn are refused with a message. |
| `components/chat/WorkflowResultChip.tsx`, `components/chat/Composer.tsx` | The chip and its remove button, the placeholder "Ask about the workflow results…", Send disabled while the run is still opening, and orchestration off while the chip is selected. Choosing **Orchestrate** removes the chip. |
| `components/workflows/WorkflowRunAskInChat.tsx`, in `WorkflowRunHistory.tsx` | **Ask in chat** on a run row. |
| `lib/workflowAlertNotices.ts`, `components/notifications/WorkflowAlertCard.tsx` | **Ask about this** on a workflow alert. |
| `pages/ChatPage.tsx` | Reads the one-shot link once, and starts the launch in a StrictMode-safe effect. |

**Ask in chat** appears on a run row only in a personal workflow's history, only
while the bootstrap flag is on, and only for a `completed` or
`completed_partial` run that isn't a structured (version 3) run. The row checks
the run's own definition version, because the run history doesn't know the
workflow's. An older run of a workflow since converted to a structured one
therefore still shows the button, and the reader refuses it with
`workflow_result_unsupported` because the workflow's current definition is
version 3.

**Ask about this** appears on a personal workflow's alert that names a run which
had finished (`completed` or `completed_partial`) when the alert was raised, and
only while the bootstrap flag is on. Group alerts, alerts without a run, and
failed or cancelled runs get no button. An alert doesn't record the workflow's
definition version, so a structured workflow's alert still offers it, and the
descriptor read then refuses the run with `workflow_result_unsupported`.
Choosing it closes the alert and leaves it unread. Since 0.261.228 it sits under the
alert's **Show more**, with the alert's other secondary actions.

### Errors

"Chip" says what V2 does with the selected run when the refusal arrives.

| Code | Status | When | Chip |
| --- | --- | --- | --- |
| `workflow_results_disabled` | 403 | The setting is off, or the personal workflow gate refuses the user. | Removed |
| `workflow_result_invalid_context` | 400 | The context isn't two valid ids and a 64-character lowercase hex digest. | Removed |
| `workflow_result_context_conflict` | 400 | The request carries a saved analysis and a workflow result. | Kept |
| `workflow_result_private_only` | 403 | The chat is shared, collaborative, converted, or someone else's. | Removed |
| `workflow_result_not_found` | 404 | The workflow or run is missing, deleted or someone else's. | Removed |
| `workflow_result_access_denied` | 403 | Run authorization failed, for example a source the owner can no longer read. | Removed |
| `workflow_result_changed` | 409 | The result's digest differs from the selected one. | Removed |
| `workflow_result_in_progress` | 409 | The run hasn't finished. | Removed |
| `workflow_result_not_finished` | 409 | The run failed, was cancelled, or ended without completing. | Removed |
| `workflow_result_preview_only` | 409 | No task stored a durable result (older runs). | Removed |
| `workflow_result_unsupported` | 409 | A structured (version 3) run, or a result made only of combined reports. | Removed |
| `workflow_result_invalid` | 409 | The stored result is inconsistent, or the run has more than 200 task rows. | Removed |
| `workflow_result_conversation_unavailable` | 404 | The chat no longer exists or was deleted. | Removed |
| `workflow_result_retry_unsupported` | 400 | A Follow up request also carries a retry or edit id, or the retry or edit route is asked to replay a Follow up turn. | Kept |
| `workflow_result_too_large` | 400 | The result and history don't fit the model even at a 6 KB excerpt. | Kept |
| `workflow_result_model_unsupported` | 400 | The selected agent can't answer with its tools off. | Kept |
| `workflow_result_answer_rejected` | 400 | A saved-analysis answer didn't pass the checks against its saved records. | Kept |
| `workflow_result_storage_unavailable` | 503 | Cosmos DB, the result store, or another check that can be retried failed. | Kept |
| `workflow_result_answer_failed` | 503 | The model call failed, or the chat changed while the answer was written. | Kept |

Sign-in failures are 401 from the usual decorators, and V2 asks the user to sign
in again.

### Logging

Logs use constant messages, such as `[WorkflowResults] Workflow result
unavailable`, `[WorkflowResults] Follow up answer refused` and
`[WorkflowResults] A chat answer's workflow result was withheld on read.`, and
carry only codes, stages, checks and exception type names. They never carry
workflow names, run output, questions, answers or ids. Storage failures log at
warning level, and closed reasons at information level.

### Files

| File | Purpose |
| --- | --- |
| `functions_workflow_result_reader.py` | The reader, the digest, the descriptor, the closed reasons and their wording, and the disclosure. |
| `functions_workflow_result_followup.py` | Follow up: the precheck, one turn, the fenced messages and their per-request code, and the refusal payload. |
| `functions_workflow_result_masking.py` | Recognizing a message that uses a workflow result, and its withheld form. No application imports. |
| `route_backend_chats.py` | The nested wrapper, the dispatch and prechecks, and inherited contexts in the history helpers. |
| `route_backend_workflows.py` | The descriptor route. |
| `functions_saved_analysis.py` | Masking on read, `is_saved_analysis_unavailable` and `authorize_saved_analysis_message_read`. |
| `functions_collaboration.py` | Collaboration copies, the metadata payload and mirrored messages stored withheld, and the dropped summaries. |
| `route_backend_conversations.py` | Conversation search skips its cache for matches that use a workflow result, and the retry and edit routes refuse Follow up turns. |
| `route_backend_conversation_export.py` | Single-message exports check both result lineages. |
| `functions_orchestration_context.py` | Orchestration history skips workflow-result answers. |
| `functions_orchestration_memory.py` | `conversation_is_private`, moved here unchanged from `functions_orchestration_workflow_context.py`, which now imports it from here. Saved analysis and Follow up import it from here too, so they no longer import the planning context, whose imports reach back to saved analysis and closed the import cycle CodeQL reported. |
| `functions_settings.py`, `admin_settings_fields.py`, `route_frontend_admin_settings.py`, `templates/admin/_panes/workflow.html` | The setting, its guard, the gate and decorator, and its classic and V2 admin switches. |
| `route_backend_v2.py` | The bootstrap's per-user flag. |
| `application/v2_ui/src/...` | See [V2](#v2). |

## Usage

### Enable or configure

1. Turn on **Enable Personal Workflows**. If **Require WorkflowUser App Role**
   is on, assign the `WorkflowUser` role to the people who should use this.
2. In **Admin Settings > Workflow > Workflow**, turn on **Use Workflow Results In
   Chat**. It's off by default, and while it's off nothing changes.

See [Workflow settings](../../admin/workflow.md).

### What a user does

1. In **Workflows**, the user opens a personal workflow's run history and
   chooses **Ask in chat** on a finished run, or chooses **Ask about this** on a
   workflow alert.
2. A new chat opens with the chip "Answering from the Weekly digest run of Mon,
   Jun 2, 9:02 AM — not re-running the workflow".
3. The user asks a question. The answer ends with the disclosure line.
4. Later questions in that chat keep using the run until the user removes the
   chip.

The user guide is
[Ask about workflow results](../../guides/ask-about-workflow-results.md), and
the controls are listed in
[Chat controls](../../reference/chat-controls.md#workflow-results-in-chat-v2-interface).

## Testing and validation

### Test coverage

| Test | What it covers |
| --- | --- |
| `functional_tests/test_workflow_result_reader.py` | Owner-only reads and the non-disclosing 404, every status family, preview-only and structured runs, the real run authorizer, storage failures as 503 rather than "not found", the digest (deterministic, independent of the budget, changed by a rewritten result), the items projection, excerpts, budgets, truncation notes and lenient decoding, saved analyses and combined reports, and a drift check against the runtime store's terminal states. |
| `functional_tests/test_workflow_result_followup.py` | One turn with the real reader and fake route helpers: private chats only on every turn, the digest binding, no sources whatever the request says, the fixed system message and fence, the per-request fence code (a forged, full-width or zero-width-split end marker stays inside the data, and the code differs per request), the disclosure, input and output screening, agents, the descriptor and inherited contexts on the answer, the re-check before saving, budget steps, mixed runs and the refusal payload. |
| `functional_tests/test_workflow_result_chat_routes.py` | Dispatch at every chat entry point and the stream prechecks, then an offline boot of the real application answering through the real JSON, SSE and history routes. |
| `functional_tests/test_workflow_result_review_paths.py` | An offline boot of the real application, through `functional_tests/test_support/workflow_result_offline_app.py`. Converting a chat to a collaboration stores its Follow up answers and inherited answers withheld and keeps each question's text without the keys; the preview, a pending invitee's metadata and history, the summary input, MCP collaboration reads, mirrored messages and the M365 publication see only the withheld form; and both summaries stay empty after the source and sync calls, even when the hidden source's summary is regenerated. The group route's conversion of a group-classified private chat does the same, and a group-classified chat without workflow results keeps its summary on both chats. The Word, PowerPoint and email exports of a single message refuse a converted chat and a lost result and still export a normal message. Retry and edit refuse Follow up turns before any content check or write and still replay ordinary turns. A search whose matches use a workflow result is never written to the cache. |
| `functional_tests/test_workflow_result_masking.py` | Withholding on read for a deleted run, a changed result, lost source access, a storage failure, another reader and a chat that isn't private; the masked shape; the question's text kept; the read sites; and the per-call cost. |
| `functional_tests/test_workflow_result_orchestration_lineage.py` | Orchestration history skipping workflow-result answers and later answers that inherited them, while keeping the questions. |
| `functional_tests/test_workflow_result_privacy_import_cycle.py` | Saved analysis and Follow up import the privacy check lazily from the memory module and never from the workflow planning context, the planning context reuses that one definition, and the memory module imports none of the modules that ask it. Each module loads cold in either order, with and without `-O`, with no network access. |
| `functional_tests/test_chat_workflow_results_admin.py`, `functional_tests/test_v2_admin_workflow_parity.py` | The default, the guard, the classic and V2 admin switches, the gate and decorator, and the bootstrap flag. |
| `functional_tests/route_tests/test_workflow_result_context_policy.py` and the route inventory and unauthenticated contract tests | The descriptor route's decorators, gates, owner-only answers, error map and caching. |
| `functional_tests/test_workflow_results_clients.mjs` | The V2 helpers: descriptor parsing, request shaping, refusal wording, the chat link, entry point gating and the retry and edit guard. |
| `ui_tests/test_chat_workflow_results.py` | The real V2 chat page, composer, store, run history and alert card against a fake server: Ask in chat, the chip, an inherited second question, refusals on the descriptor read and on the stream (including a changed result), a question sent while the run is opening, Ask about this, the setting off, reopening inherited and withheld chats, Orchestrate, and a workflow name that stays text. |

### Performance

- **One check of a result** (the descriptor route, each Follow up read, the
  re-check before saving, and masking) costs 2 point reads (the workflow and the
  run), 1 single-partition query on the run items, one manifest load per
  eligible task plus the consumed-ancestor loads of run authorization, shared
  through one memoizing loader, and source authorization for any Analyze
  lineage. There's no history paging, because structured runs are closed.
- **A Follow up turn** reads the result once with excerpts, and again for each
  budget step it needs, then re-checks the current and every inherited context
  before saving.
- **Every chat send** runs the history sanitize, so a conversation that holds a
  Follow up answer pays one conversation read plus one run authorization per
  distinct context on each turn, and that authorization includes the manifest
  loads and the consumed-ancestor loads. Opening such a conversation pays the
  same once per read. Conversations without Follow up answers pay nothing.
- **A single-message export** of an answer that uses a workflow result pays
  one run authorization per distinct context, and reuses the chat it already
  read for the privacy check. Other messages export as before. **Converting a
  chat** only checks each message's metadata keys, with no extra reads.
- **Excerpts** are at most 48 KB of text per turn. A large output is read as
  one bounded page, and a record output as at most 8 pages.

### Known limitations

- **Personal workflows only.** Group workflows come in a later phase.
- **Structured (version 3) runs aren't supported.** Ask in chat is hidden for
  them, and the server refuses them with `workflow_result_unsupported`. It also
  refuses an older run of a workflow that has since been converted, which still
  shows Ask in chat, and a structured workflow's run reached from Ask about
  this.
- **Authoritative outputs only.** Named outputs aren't read.
- **Part of a large result.** An answer sees at most 48 KB of excerpts from up to
  8 outputs, and says so when it saw only part of the result. A run with more
  than 200 task rows can't be read.
- **Mixed runs** are answered from their saved analyses only.
- **Retry and Edit** on a Follow up question or answer are refused, by V2 and
  by the server, with 400 `workflow_result_retry_unsupported`. Ask the question
  again instead. A later answer that only inherited a workflow-result context
  retries as an ordinary turn, and its history is withheld on the same terms.
- **Output formats**, such as "make this a CSV", aren't supported in Follow up.
- **Orchestration history omits Follow up answers, later answers that inherited
  their workflow-result context, and orchestration answers that read a saved
  workflow result.** Since 0.261.217, a plan can read a run's result directly
  with the `workflow_results` capability; see
  [Chat orchestration workflow results](CHAT_ORCHESTRATION_WORKFLOW_RESULTS.md).
- **Shared and converted chats.** Once a chat is shared or converted to a
  collaboration, its Follow up answers are hidden for everyone, you included.
  The original chat's stored messages are unchanged. The collaboration's copies
  are stored with these answers withheld, and the chat's saved summary is
  cleared on both chats.
- **No retention setting.** A run's result stays available until the run is
  deleted.
- **Classic chat** has no entry points or chip, and its message list is one of
  the owner-only raw reads below.
- **Owner-only raw reads.** A few older reads return a personal chat's stored
  messages without the sanitizer, so they still show the chat's owner an answer
  whose result is no longer available: classic chat's
  `/conversation/<id>/messages`, the personal branch of
  `/api/message/<id>/metadata`, personal chat summaries (a new one is generated
  from the stored messages, and one already saved on the chat stays) and MCP
  reads of personal chats. Only the chat's owner can reach them, and
  saved-analysis answers have the same gap. Saved-analysis answers are also
  still copied into a collaboration as stored. Both are tracked as follow-ups
  shared with saved analysis.

### Follow-ups

- The `workflow_results` orchestration capability shipped in 0.261.217, built on
  this reader and Phase 5's workflow planning context. Its own limits are in
  [Chat orchestration workflow results](CHAT_ORCHESTRATION_WORKFLOW_RESULTS.md#known-limitations).
- Structured (version 3) runs, with their node, execution and attempt selectors.
  Until then, hiding Ask in chat on older runs of a converted workflow and Ask
  about this on a structured workflow's alerts needs the workflow's definition
  version in the run history and the alert.
- Named, non-authoritative outputs.
- Output formats in Follow up.
- Retry and edit that keep the workflow result context. The server refuses them
  today.
- Withholding unavailable answers on the owner-only raw reads (classic chat's
  message list, the personal message metadata route, personal summaries and MCP
  personal reads), and withholding saved-analysis answers in collaboration
  copies, together with saved analysis.
- A retention setting (roadmap §9).
- Group workflows (Phase 8).
- Re-checking workflow result contexts when a generated file is published.
- Phase 6b's delivery, run card, recurring-workflow card and chat-list
  indicator, and `v2WorkflowRunPath`.
- Phase 6b-1 now has its server-side delivery contract in
  [Workflow result delivery to chat](CHAT_WORKFLOW_RESULT_DELIVERY.md); the V2
  run card and chat-list indicator still follow in later work.
