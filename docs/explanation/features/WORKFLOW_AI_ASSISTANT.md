# Workflow AI Assistant (v0.261.211)

## Overview

The AI workflow assistant lets a person change a personal workflow by describing the change in
plain language: "run this at 7 AM on weekdays and only alert me when something is urgent", or
"compare every new document against #checklist". The assistant proposes the edit, and the V2
workflow editor shows it as highlighted, attributed, revertible changes that the person reviews
before saving. The assistant never saves anything.

The server half is `POST /api/user/workflows/assist`, added in 0.261.208. It takes one
instruction and the editor's current draft, asks the model for a small set of allowlisted
operations, applies them to a copy of the draft, checks the result the way a save would, and
returns a candidate draft. It writes nothing.

The editor half is the **Ask AI** tab, added in 0.261.211. It sends the instruction, checks the
answer against the draft it was sent with, and applies the candidate through the editor's
`applyAssist` seam, so every change is highlighted, attributed to the turn and undoable. The same
release adds **Draft with AI**, which writes instructions for an empty task.

Implemented in version: **0.261.208** (the endpoint) and **0.261.211** (the **Ask AI** tab and
**Draft with AI**), tracked in `application/single_app/config.py`.
Phases 3b and 3c of the [chat orchestration workflows roadmap](CHAT_ORCHESTRATION_WORKFLOWS_ROADMAP.md)
(#1548, part of #1543).

The assistant ships in three layers:

| Layer | What it adds | Status |
| --- | --- | --- |
| 3a | Change tracking in the V2 editor, including `WorkflowAuthoringSession.applyAssist(candidate, {turnId, label})` | Shipped in 0.261.203 ([Workflow editor change tracking](WORKFLOW_EDITOR_CHANGE_TRACKING.md)) |
| 3b | The endpoint: instruction in, validated candidate out | Shipped in 0.261.208 |
| 3c | The **Ask AI** tab on the shared assist thread, which calls the endpoint, and **Draft with AI** | Shipped in 0.261.211 |

Dependencies:

- Phase 2's draft service: `dry_run_personal_workflow` in `functions_workflow_drafts.py`, which
  builds the save payload exactly as saving would and writes nothing.
- Track A2's `#` reference authorizer: `resolve_scope_references` in
  `functions_orchestration_context.py`.
- The workflow editor options (`get_workflow_editor_options`) and workflow reference loading
  (`load_workflow_reference`).
- The draft-instructions model deployment that `/api/workflows/draft-instructions` already uses.
  No new model setting is added.
- For the tab: Track A1's shared assist thread (`AssistThread`, `useAssistThread` and
  `assistThreadStore`, see [V2 shared assist thread](V2_SHARED_ASSIST_THREAD.md)), Track A2's
  `#` references in `lib/planReferences.ts`, and 3a's `applyAssist`, `revertTurn` and **Changes**
  tab.

## What it does and doesn't do

The endpoint returns a proposal. It never writes a workflow, a run or a document, and it never
starts a run. The only thing it writes is the caller's rate-limit document in the settings
container (see [Rate limits](#rate-limits)). If the saved workflow changed after the editor opened,
the endpoint refuses with 409, and the editor keeps its draft.

The candidate it returns is the draft with the operations applied and nothing else. It is not
normalized, so the editor highlights only what the assistant actually changed.

Version 1 is limited to personal workflows. Group workflows are refused. The conversation isn't
stored: the editor sends its recent turns with each request, and nothing is kept on the server.

## Technical specifications

### Architecture

| File | Responsibility |
| --- | --- |
| `route_backend_workflows.py` | The route: reads the body with a size bound, builds the services and maps errors to responses. |
| `functions_workflow_assist.py` | The core: request validation, model messages, the evaluate-and-correct loop, warnings and telemetry. |
| `functions_workflow_assist_operations.py` | Handles, the model's view of the draft, the operation schemas and the structural apply. |
| `functions_workflow_assist_editor.py` | A Python port of the V2 editor logic the candidate must satisfy: the authored and forbidden field lists, `workflowAssistViolation`, `workflowForSave` for the personal scope, and the change keys and labels from `diffWorkflowChanges`. |
| `functions_workflow_assist_limits.py` | The per-user limiter in Cosmos. |
| `functions_workflow_assist_runtime.py` | The Azure-backed services: the stored workflow, the reference authorizer, editor options, excerpts, the dry run, the Microsoft 365 checks, the model call and the limiter. |

The core has no Azure imports. Every outside service is injected through
`WorkflowAssistServices`, which is how the functional tests run the whole pipeline with a scripted
model and fake stores.

### The route and its gates

```python
@bp.route('/api/user/workflows/assist', methods=['POST'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
@enabled_required('allow_user_workflows')
@workflow_user_required
@workflow_assistant_required
def assist_user_workflow(): ...
```

`workflow_assistant_required` allows the request only when `is_workflow_assistant_enabled_for_user`
is true. That helper is built on `is_user_workflows_enabled_for_user`, so the assistant follows the
same personal-workflow and `WorkflowUser` role rules as the rest of the editor, and adds one
setting on top:

| Setting | Default | Meaning |
| --- | --- | --- |
| `enable_workflow_ai_assistant` | On | Users who can edit personal workflows can use the AI assistant in the V2 workflow editor. It has no effect while **Enable Personal Workflows** is off. |

The V2 bootstrap route (`/api/v2/bootstrap`) reports the per-user result as
`features.enable_workflow_ai_assistant`, and the editor hides the **Ask AI** tab and **Draft with
AI** when it's false. See [When the tab is offered](#when-the-tab-is-offered).

### Request

The body is a JSON object of at most 6 MiB, nested at most 200 levels deep. That's enough for a
100-task draft. Unknown fields are refused. Nothing is truncated: input over a bound gets a 400.

The body is read the way the browser's `JSON.parse` reads it, with every number finite. Python's
parser also accepts `NaN`, `Infinity` and `-Infinity`, and reads `1e999` or a 400-digit integer as
a number JavaScript can only hold as `Infinity`. All of them are refused with `invalid_request`, as
is text with a lone surrogate.

| Field | Required | Rules |
| --- | --- | --- |
| `submission_id` | Yes | The client's ID for this turn, used for idempotent logging and for 3c's turn reconciliation. Same format as the other assist routes. |
| `base` | Yes | `null` for a new draft, or `{workflow_id, definition_revision}` for a saved workflow. |
| `instruction` | Yes | 1 to 2,000 characters, not blank, with no control characters other than tab and line breaks. |
| `draft` | Yes | The editor's `WorkflowDefinition` (`lib/workflowEditor.ts`), the same shape 3c passes to `applyAssist`. Definition version 1, 2 or 3; 1 to 100 tasks, each with its own ID; at most 100 shared references. |
| `conversation` | No | Up to 20 completed turns, oldest first. Each is `{role: "user" \| "assistant", text}`, with text of 1 to 4,000 characters. Failed and cancelled turns aren't sent. |
| `focus` | No | The ID of a task or flow block in the draft, or `null`. |
| `time_zone` | No | The browser's IANA time zone, used for calendar schedules. It must be one of `workflow_schedule_timezones()`, which excludes names such as `Factory` and `localtime` that the schedule normalizer refuses. |
| `references` | No | Up to 20 `#` references in Track A2's shape: `{kind, id, label, scope: {kind, id, name}}`. Documents only; a tag is refused with `tags_unsupported`. |

The roadmap's contract names the base's token `modified_at`. The endpoint uses
`definition_revision` instead, because that is the token the save route uses to detect a
conflict. A new draft must have no `id`. A saved draft's `id` must equal `base.workflow_id`, and
its `definition_revision`, when present, must equal the base's.

The draft must be personal: a draft carrying `group_id` is refused with
`group_workflow_unsupported`. A draft the editor opened read-only (`editor_readonly_reason`) is
refused with `workflow_read_only`.

### Response

A 200 response always has this shape:

```json
{
  "submission_id": "…",
  "outcome": "changed",
  "reply": "It now runs at 07:00 on weekdays and alerts you only for urgent findings.",
  "candidate": { "…": "the applied WorkflowDefinition" },
  "changes": [
    {
      "key": "schedule",
      "kind": "field",
      "label": "Trigger and schedule",
      "owner_label": "Workflow",
      "target": { "focus_key": "schedule" },
      "summary": "Workflow: Trigger and schedule"
    }
  ],
  "warnings": [
    { "code": "run_as_reapproval", "message": "Saving this change requires re-approving Run as, because it changes how the workflow runs." }
  ],
  "context_documents": []
}
```

| Field | Meaning |
| --- | --- |
| `outcome` | `changed`, `explained` (an answer, or why the change can't be made) or `question` (the request is ambiguous). |
| `reply` | Text for the user, at most 1,500 characters, with control characters other than line breaks and tabs removed. The model is told not to use Markdown or HTML, and the client must render it as plain text. |
| `candidate` | For `changed` only: the submitted draft with the operations applied. `null` otherwise. |
| `changes` | For `changed` only: each change in the editor's reading order. `key` is the editor's change key, and `target.focus_key` (plus `target.node_id` for a flow block) is what **Jump to** focuses. |
| `warnings` | Advisory warnings for a changed candidate. None of them blocks the change. |
| `context_documents` | Labels of attached `#` documents the model read as context without placing them in the workflow. |

A `changed` reply whose operations leave the draft as it was becomes `explained`, with the reply
"The workflow already works this way, so nothing was changed."

Every response carries `Cache-Control: no-store, private`, because the body holds the caller's
draft.

Responses are written as strict JSON (`allow_nan=False`), because `response.json()` in the browser
can't read `NaN`. Strict parsing of the body and the model's reply means a candidate can't carry a
non-finite number. If a result still can't be written, the endpoint returns 500 `assistant_failed`
without echoing the value.

### Warnings

| Code | When |
| --- | --- |
| `run_as_reapproval` | The workflow has Run as (`m365_run_as_user_id`) and the change alters a key in `workflow_execution_fingerprint`, so saving asks to re-approve Run as. A change that leaves every fingerprinted key alone, such as an alert change, doesn't warn, matching the editor's `workflowRunAsConsequence`. |
| `email_requires_m365_agent` | A task this turn added or changed sends email, and the agent that runs it doesn't have the Microsoft 365 action (or no agent runs it). Targets the task. |
| `m365_not_connected` | A task sends email, the workflow has no Run as or runs as the caller, and the caller's stored Microsoft 365 connection says they aren't connected. It reads the stored record only and never calls Microsoft Graph. |
| `draft_has_errors` | The draft already failed a save check before this change, and the change caused no new failure. |

The Microsoft 365 checks are skipped when fewer than 5 seconds of the request's deadline are left.

### Status codes

Errors carry a closed `code` and a server-authored `error` message. No error echoes model output or
document text.

| Status | Codes | Meaning |
| --- | --- | --- |
| 200 | | `changed`, `explained` or `question` |
| 400 | `invalid_request`, `instruction_invalid`, `conversation_invalid`, `draft_invalid`, `focus_invalid`, `time_zone_invalid`, `tags_unsupported`, `reference_limit`, `reference_unavailable`, `group_workflow_unsupported`, `workflow_read_only`, `assistant_input_too_large` | Bad input. `assistant_input_too_large` means the draft alone doesn't fit the model prompt, even with every earlier turn dropped. |
| 400 | (no code) | **Enable Personal Workflows** is off. This is the shared `enabled_required` response every personal workflow route returns. |
| 403 | `workflow_assistant_disabled`, or the `WorkflowUser` role response | The assistant setting is off, or the role is required and the caller lacks it. |
| 404 | `workflow_not_found` | `base.workflow_id` is missing or isn't the caller's own personal workflow. |
| 409 | `workflow_definition_conflict`, `workflow_deleted` | The saved workflow changed, or was deleted, after the editor opened it. The client keeps its draft. |
| 413 | `request_too_large` | The body is over 6 MiB. |
| 429 | `assistant_busy`, `assistant_rate_limited` | A request is already in flight, or the window is used up. Both set `Retry-After` and carry `rate_limited: true` and `retry_after_seconds`. `assistant_rate_limited` uses the app's shared rate-limit message (`build_rate_limit_error_payload`), which an administrator may have written in Markdown. |
| 502 | `assistant_output_invalid`, `assistant_refused` | The model's reply still failed after the correction round, or the model refused. Nothing changed. |
| 503 | `assistant_unavailable`, `assistant_timeout`, `assistant_limit_unavailable`, `reference_check_failed` | The model, a store, the rate-limit store or the reference authorizer isn't available, or the deadline ran out. Provider throttling is 503 with the provider's `Retry-After`, clamped to 1–60 seconds (10 when the provider sends none). |
| 500 | `assistant_failed` | An unexpected failure. |

### Handles: what the model can name

The model never sees or writes a raw ID. Each request gives everything the model may name a
request-local handle, and the server maps handles back and refuses anything else.

| Handle | Names |
| --- | --- |
| `task_1`, `task_2`, … | The draft's tasks, in order |
| `new_1`, `new_2`, … | Tasks the same reply adds (the `key` of an `add_task`) |
| `node_1`, `node_2`, … | A flow's blocks, in the order the editor lists them |
| `agent_N`, `model_N`, `default_model` | The agents and models the editor offers the caller, from `get_workflow_editor_options` |
| `alert_1`, `alert_2`, … | The draft's alert rules |
| A reference's alias, or `shared_N` | The draft's shared references. The alias is shown only when it's a safe, unique name; otherwise `shared_N`. |
| `doc_N` | Documents a task already targets that no shared reference names |
| `ref_1`, `ref_2`, … | The `#` documents attached to this request |

`focus` reaches the model as a handle too. Agent, model and document labels that contain a known
ID are replaced with a generic label such as "Agent 2".

When the model places a new `#` document, the server creates the reference. Its alias comes from
the file name, is unique within the draft, and is valid under the save route's name rule. Its `id`
follows the editor picker's `scope:scope_id:document_id` form, or is a new UUID when that form is
too long or already in use.

### Operations

The model replies with one JSON object:

```json
{"outcome": "changed", "reply": "…", "operations": [ … ], "email_tasks": [ … ]}
```

The envelope and every operation are checked against closed JSON schemas (Draft 2020-12, no extra
properties) before anything is applied. At most 64 operations are accepted per reply.

| Area | Operations |
| --- | --- |
| Name and description | `set_name`, `set_description` |
| Trigger and schedule | `set_trigger_manual`, `set_schedule_interval` (seconds, minutes or hours), `set_schedule_calendar` (daily, weekdays, weekly or monthly, at a local `HH:MM`) |
| Alerts | `set_alert_mode` (`off`, `every_run` with a priority, or `rules`), `add_alert_rule`, `remove_alert_rule` |
| Runner | `set_workflow_runner`, `set_task_runner` (inherit, an agent handle or a model handle) |
| Tasks | `add_task`, `remove_task`, `move_task`, `set_task_name`, `set_task_instructions`, `set_task_inputs` |
| Documents | `bind_reference`, `set_task_references`, `unbind_reference`, `set_task_document_target`, `clear_task_document_target` |

Schedules go through the same normalizer and minimum-interval rule a save uses. A calendar
schedule keeps its current time zone unless the user names one; a new calendar schedule uses the
request's `time_zone`, and without one the model is told to ask.

`email_tasks` lists the tasks whose instructions send email. The server adds any changed task whose
instructions mention email, so the email warning doesn't depend on the model remembering.

### Document placement

A `#` document is placed by what the instruction asks for, following the roadmap's §5 table:

| The instruction | Placement |
| --- | --- |
| "Use #X to design the steps" | Not placed. The model reads the excerpt as context, and the document is listed in `context_documents`. |
| "Compare every new document against #X", "follow #X" | `bind_reference`: a shared reference used by all tasks, or by the tasks listed. |
| "Summarize #X every Friday" | `bind_reference` for that one task. Tasks that read every reference are given explicit lists, so they keep reading only the references they already had. |
| "Investigate #X", "compare #A with #B" | `set_task_document_target`: that task's document action, with the documents selected. |
| "Review each of #A, #B and #C" | Needs a For each block, which isn't available yet, so the model explains. |
| Unclear | `question`, and nothing changes. |

A `#` document here is a bound input by construction. It never narrows a search the way a
reference narrows a plan in the plan editor (roadmap gotcha 60).

### Never changed

Whatever the model emits, these are refused:

- Every field in 3a's `ASSIST_FORBIDDEN_FIELDS`: `is_enabled`, `m365_run_as_user_id`,
  `definition_version`, `id`, `user_id`, `group_id` and `url_access_enabled`.
- A task's `approval` (`ASSIST_FORBIDDEN_TASK_FIELDS`).
- Anything outside `WORKFLOW_AUTHORED_FIELDS`, which covers sharing and ownership.
- An ID that changes meaning: a task, reference or flow block ID reused for something else.
- File Sync. There are no File Sync operations yet, and a workflow triggered by File Sync keeps
  its trigger.
- For each and If blocks. The model explains instead.

The Python lists in `functions_workflow_assist_editor.py` are the server's own source of truth.
`test_workflow_assist_field_parity.py` reads `WorkflowAuthoringHistory.tsx` and fails when the two
drift.

### Flow (definition version 3) drafts

For a flow draft, the assistant can change the workflow's name, description, schedule, alerts and
runner, and for each task: its name, instructions, runner, shared references and document target.
It can't add, remove or reorder tasks or set their inputs, because those change the flow graph. The
`flow` object itself must come back unchanged. That's stricter than the editor, which allows flow
edits that keep every ID's meaning. A task that analyzes the current For each document, a
publication task's runner and documents, and an advanced document action are shown to the model as
not editable.

### Validation: apply, then check, with one correction round

Each model reply goes through these steps:

1. Parse the reply as one JSON object, as strictly as the request body: finite numbers only, valid
   Unicode, and at most 200 levels deep. One Markdown code fence is tolerated.
2. Check the envelope and every operation against the schemas.
3. Apply the operations to a deep copy of the submitted draft. It's a plain structural apply with
   no normalization and no default fill.
4. Check the candidate with the ported `workflowAssistViolation`.
5. Project the candidate with the ported `workflowForSave`, the payload the editor would post.
6. Run Phase 2's `dry_run_personal_workflow` on that payload. It checks authorized agents,
   documents and sources, limits and calendar rules, and writes nothing. Blank required text is
   filled with placeholders in this copy only, so an unfinished draft doesn't hide the change's
   own errors.

A failure in steps 1 to 6 sends server-authored error messages back to the model for **one**
correction round. A dry-run message that mentions a known ID is replaced with its error code. If
the second reply also fails, the request returns 502 `assistant_output_invalid` and changes
nothing. A `workflow_definition_conflict` or `workflow_deleted` from the dry run returns 409
immediately.

When the draft already failed the dry run before the change, the endpoint compares error lists: a
change that adds no new failure is returned with the `draft_has_errors` warning instead of being
sent back.

The editor draft isn't the save payload, so the endpoint doesn't hand the draft to the dry run
directly. It mirrors `workflowForSave` in Python for the personal scope. Since Phase 4 (#1547)
that includes `workflowFileSyncForSave`: File Sync settings the author edited are sent as the
editor sends them, and untouched ones aren't sent. Two test files keep the port honest:

- `test_workflow_assist_dry_run_parity.py` checks that the projection is what the dry run accepts.
- `test_workflow_assist_candidate_parity.py` produces 24 candidates in Python and replays each one
  through the real V2 editor code under Node: `normalizeWorkflowDefinition`,
  `workflowAssistViolation`, `diffWorkflowChanges`, `workflowRunAsConsequence`, `workflowForSave`
  and `applyAssist`. The TypeScript and Python results must match exactly.
- The same file also runs a corpus through the editor's own `Number()`,
  `normalizeWorkflowDefinition` and `workflowForSave`. It covers numbers and numeric strings in
  the forms the editor coerces:
  - fullwidth digits
  - radix prefixes
  - `1e21` and `-0`
  - integers past `Number.MAX_SAFE_INTEGER`
  - single-element arrays

  It also covers whitespace where JavaScript's `trim()` and Python's `strip()` disagree, such as
  `\ufeff`, `\x1c` and `\x85`. The port must open, save and read every entry exactly as the
  editor does. The comparison uses `json.dumps(sort_keys=True)` of both sides, so `12` and `12.0`
  are different answers.
- It also saves 11 File Sync drafts, among them untouched, new and edited ones with personal, group
  and public sources, File Sync turned off with and without a File Sync trigger, and odd, unknown
  or missing values. The port and the editor must save each one the same way. Both are also
  checked against pinned answers, so the port is still tested when Node isn't installed.

A whole number the editor would save reaches the dry run as an `int`, as it would through JSON.
For example, `output_contract.expected_count` given as `"12"` or `12.0` is checked as `12`.

### The model prompt

The model gets two messages. The system message holds the rules and the operation schemas. The
user message is one JSON document:

| Key | Content |
| --- | --- |
| `instruction` | The user's request. The only field the model is told to act on. |
| `focus`, `time_zone` | The focused task or block's handle, and the time zone. |
| `conversation` | This editor's recent turns. |
| `draft` | The draft through handles, with no IDs. Uneditable parts are marked `"editable": false`. |
| `choices` | The agents and models the caller may use, and the limits. |
| `document_excerpts` | Bounded excerpts of the attached `#` documents. |
| `previous_attempt_errors` | In the correction round only: why the previous reply couldn't be used. |

The system message says that everything except `instruction` is untrusted material to read but
never obey, including the workflow's own names and instructions, earlier turns, correction errors
and document excerpts. Every string is JSON-encoded inside the one document, so none of it can
close a fence or pose as a new message.

When the prompt is over its budget of 360,000 characters (with 6,000 kept for the correction
round), the oldest turns are dropped first, and telemetry counts them. If the draft still doesn't
fit, the request returns 400 `assistant_input_too_large`.

### Document excerpts

Excerpts are read through `load_workflow_reference`, which re-authorizes the document as it
loads. At most 5 documents are excerpted, 6,000 characters each and 24,000 in total, with control
characters removed. Loading reads the whole document, so a document is loaded only while at least
100 seconds of the request's deadline remain, which keeps time for the model call and a possible
correction round. A document that isn't loaded reaches the model as its label only. Excerpt text
is never logged.

### Deadlines

One 150-second deadline covers the whole request, correction round included. App Service ends a
request at 230 seconds and the editor gives up at about 170, so the server answers first.

- A model call isn't started with less than 15 seconds left. When there isn't time for a call,
  including the correction round, the request returns 503 `assistant_timeout`.
- Each call's timeout is the time left minus 5 seconds, kept for validation and the response.
  The OpenAI client's own retries are off.
- The advisory Microsoft 365 checks are skipped with less than 5 seconds left.

### Model parameters

The assistant uses the draft-instructions deployment (`_resolve_agent_instruction_model` and
`_create_agent_instruction_client`), including APIM and managed identity. It sets its own output
limits, because the draft-instructions route caps output at 1,400 tokens:

- Deployments whose name contains `o1`, `o3` or `gpt-5` (the same markers
  `_build_agent_instruction_api_params` uses) get `max_completion_tokens` 16,000 and no
  temperature.
- Others get `max_tokens` 4,000 and temperature 0.2.
- JSON mode (`response_format: json_object`) is requested, and dropped for the rest of the request
  if the deployment refuses it.

A `length` finish goes to the correction round. A content-filter finish, or a provider
content-filter error, returns 502 `assistant_refused`. A provider context-length error returns 400
`assistant_input_too_large`.

### Rate limits

Each user may have **one request in flight** and **20 requests per 10 minutes**. The limits must
hold across Gunicorn workers and App Service instances, so the counter lives in Cosmos. It follows
`check_inbound_mcp_tool_rate_limit`: one document per user in the settings container, read and
then created or replaced under an etag compare-and-swap.

- Acquiring sets a 180-second lease, longer than the request deadline. A second request while the
  lease is set gets 429 `assistant_busy` with `Retry-After: 1`.
- Over the window, the request gets 429 `assistant_rate_limited` with `Retry-After` set to the
  seconds until the window ends.
- A request that ends before any model call, such as a stale base, is refunded when it releases.
  A request whose model call failed still counts.
- **The limiter fails closed.** When the store can't be read or written, the request gets 503
  `assistant_limit_unavailable`, and the model is never called without the limit.
- A release that fails is logged once, as a content-free warning with the error type, and the lease
  expires on its own.

The document ID is `workflow_assist_rate_limit:<SHA-256 of the user ID>`. It holds a count, a lease
ID and timestamps, never request content. **This document is the endpoint's only write.**

### Security model

- **Personal only** (roadmap decision 3, gotcha 29). Group drafts and drafts carrying `group_id`
  are refused. The base must be the caller's own personal workflow.
- **The caller's own access.** `#` documents go through `resolve_scope_references` with the caller's
  identity, and excerpts through `load_workflow_reference`, which re-authorizes each one. Agents and
  models come only from the caller's editor options. The dry run authorizes everything again.
- **No raw IDs** (gotcha 28). The model sees handles, and the server rejects a raw document ID, an
  unknown handle or a handle of the wrong kind.
- **Untrusted material** (gotchas 5 and 27). The draft, turns and excerpts are fenced as untrusted
  data, and only `instruction` is a request.
- **Plain text only.** The reply and every string the model writes into the draft are
  length-bounded and free of control characters, and names are single lines. They are data: the
  client renders them as text, never as HTML or Markdown.
- **No raw settings.** The route reads settings on the server and returns none of them. The one
  settings-derived value in a response is the app's shared rate-limit message on a 429.
- **Content-free errors and logs.** Error messages are server-authored. Nothing logs or returns an
  instruction, draft, reply or document text.

### Telemetry

Each request logs one `[WorkflowAssist] Assist request finished` event through `log_event`, with
only these fields: `user_id`, `submission_id`, `status`, `outcome`, `code`, `stage`, `error_type`,
`invalid_stage`, `operation_count`, `correction_count`, `model_calls`, `turns_received`,
`turns_sent`, `turns_dropped`, `reference_count`, `excerpt_count`, `definition_version`, `is_new`,
`warning_codes`, `fault_location` (file and line, on a 500 only) and `duration_ms`. A body that
can't be read logs `[WorkflowAssist] Assist request refused` with its code, status and stage.

### The Ask AI tab

**Ask AI** is the second tab in the editor's side panel, after **Changes**. It runs on Track A1's
shared assist thread, so it has the same turn list, **Cancel**, **Retry**, **Edit and resend** and
`#` composer as the chat's image and plan editors. A turn that changes the draft goes through 3a's
`applyAssist`, so its changes get the same highlights, **Previously:** values, per-field
**Revert** and **Changes** list as your own edits, and saving asks you to review them first.

| File | Role |
| --- | --- |
| `components/workflows/WorkflowAskAiTab.tsx` | The tab, its turn cards, the footer toggle and the lock banner |
| `components/workflows/useWorkflowAssist.ts` | The tab's state: sending a turn, applying the answer, **Undo this change**, **Jump to** and **Draft with AI** |
| `lib/workflowAssist.ts` | Pure logic: the request, replay, the response guard, error messages, the rebase and the change check |
| `lib/codePoints.ts` | Counting and cutting text by code points, as the server counts |
| `stores/workflowAssistStore.ts` | Turn cards and the rate-limit wait, in memory only |
| `components/workflows/WorkflowEditorDialog.tsx` | Wiring: the gate, the tab, the toggle, the lock, Escape and focus |
| `components/workflows/WorkflowTaskFields.tsx` | Each task's **Ask AI** and **Draft with AI** buttons |
| `components/workflows/WorkflowChangeTracking.tsx` | A side panel whose selected tab the dialog controls, and a class for each tab's panel |
| `pages/workspace/WorkflowsSection.tsx` | Reopening a saved workflow after a conflict |

Paths are under `application/v2_ui/src/`. The shared thread gained a few options for this tab, all
off by default. See [V2 shared assist thread](V2_SHARED_ASSIST_THREAD.md#options-for-the-workflow-editor).

### When the tab is offered

The editor offers Ask AI only when all three of these hold:

1. The bootstrap reports `features.enable_workflow_ai_assistant` as true for this user. That
   follows the admin setting, personal workflows and the `WorkflowUser` role.
2. The workflow is personal. Group workflows never offer it (roadmap decision 3).
3. The editor can change the workflow. It can't when you don't have edit rights, when the workflow
   has an active run, when access was lost while the editor was open, or when the workflow uses
   something this editor can't change, such as an unsupported flow feature or a stored schedule it
   can't show exactly.

When it's offered, the footer shows an **Ask AI** toggle before **Changes**, each task has an
**Ask AI** button, and a task with empty instructions has **Draft with AI**. When it isn't, the
editor is as it was: the side panel has only **Changes**, and a read-only editor has no side panel.

It also works on a workflow proposal opened from chat with **Edit** (Phase 4). That draft is a new
personal workflow, so the tab sends it without a base, and there is no saved workflow to reload.

### The thread

A saved workflow has one thread, keyed `workflow:personal:<workflow id>`. A new workflow or a
proposal draft gets a new key, `workflow:new:<id>`, each time the editor opens, so it starts empty.
Every thread uses the conversation ID `workflow-editor` and the thread's local mode, which keeps
the last 20 finished exchanges.

While the editor is open it holds its thread, so A1's pruning never drops it, and using it never
sweeps away the chat's idle image and plan threads. Closing the editor releases the thread but
leaves it in memory, so reopening a saved workflow in the same page shows the conversation. After
that, A1's usual pruning applies: using an image or plan editor in chat drops idle threads of other
conversations, and the store keeps at most 50 threads.

The conversation is ephemeral in version 1 (roadmap §9). Nothing is stored on the server or in the
browser's storage, so reloading the page starts over. The turn cards, which record what each turn
changed and what its Undo did, live in `workflowAssistStore`, up to 200 across every editor in the
page, oldest dropped first.

### Sending a turn

**Send**, a quick action, **Retry** and **Edit and resend** each post one request:

| Field | What the tab sends |
| --- | --- |
| `submission_id` | A new ID for the turn |
| `instruction` | The text, trimmed, without the control characters the server refuses (`[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]`). Tab, line feed and carriage return are kept. |
| `draft` | The editor's draft as it stands |
| `base` | `{workflow_id, definition_revision}` for a saved workflow. A new or proposal draft sends `null`, and must have no `id`. |
| `conversation` | At most 20 `{role, text}` items: the last 10 completed exchanges, whole |
| `references` | The `#` documents in the message, deduplicated and ordered by A2's `canonicalPlanReferences` |
| `focus` | The task you asked about, as its task ID, or on a structured (v3) workflow as its flow block's ID. Sent only while that task still exists. |
| `time_zone` | The browser's IANA time zone, when the schedule editor offers it, so "7 AM" means your 7 AM |

The instruction is limited to 2,000 characters counted as code points, the way the server counts,
so an emoji counts as one. The counter and the over-limit message use the same count.

Only completed turns are replayed. Failed and cancelled turns never are, because the draft doesn't
reflect them. A user item is the instruction as it was sent. An assistant item is the reply,
followed by what became of its changes, read from the editor's history when the request is built:

| The turn's changes | What the assistant item adds |
| --- | --- |
| Applied | "Changes applied: …" |
| Partly undone | "Changes applied: … The user later undid some of them." |
| Undone | "These changes were applied and later undone: …" |
| Waiting for the impact confirmation | "These changes are waiting for the user's confirmation and are not applied yet: …" |
| Not applied | "No changes were applied." |
| From an earlier editing session | "These changes were made in an earlier editing session and may not have been saved: …" |

The list names at most 12 changes, each cut to 120 characters, then "and N more". Each item is
capped at 4,000 code points without splitting a surrogate pair, and an item that is blank after
trimming is left out. This lets the model build on what the draft actually holds, rather than on
what it proposed.

References are checked before anything is sent, and nothing is dropped silently. More than 20
documents is refused with "Attach at most 20 documents." The picker offers documents only, but a
tag or a whole workspace can still arrive through **Edit and resend**, and is refused with a
message, because a workflow reference is a document.

While a turn runs, the editor is locked, because the answer is a whole draft built from the one
that was sent. A banner reads "Ask AI is working. The editor is locked until it answers.", with the
seconds elapsed and **Cancel request**. The fields, the flow canvas, Undo and Redo (including
Ctrl+Z and Ctrl+Y) and **Save workflow** are disabled. Closing the editor cancels the turn. The
browser gives up after 170 seconds; the server's own deadline is 150.

### Applying the answer

The tab first checks that nothing moved while it was working: the same editor, the same opened
version, and a draft equal to the one it sent. If anything differs, nothing is applied, and the
turn fails with "Nothing was applied because the draft changed while Ask AI was working. Send it
again to use the current draft." **Retry** sends it against the current draft.

On `changed`, three steps follow:

1. **Rebase.** The candidate arrives as JSON, which has no `undefined` and no non-finite numbers.
   The editor's draft can hold both; a proposal or saved draft, for example, has `id: undefined`
   once the editor normalizes it. So the candidate is rebased on the live draft. Wherever it
   equals the live value as JSON, the live value is kept, object identity included. Arrays are
   matched by `id` when both sides have unique IDs, and by position otherwise. Keys the model
   removed stay removed. Without this step, `applyAssist` would refuse every answer for a new
   draft as a change to `id`, and unchanged objects would look edited.
2. **Check.** The card lists only what the editor's own `diffWorkflowChanges` finds between the
   draft that was sent and the rebased candidate. The server's summaries are used for keys the
   diff also found, and its flow block only when that block exists in the result. A change the
   server lists that the diff doesn't find isn't shown. When the diff finds nothing, the turn is
   treated as an explanation.
3. **Apply.** `applyAssist(candidate, {turnId, label: "Ask AI: <instruction>"})` applies it as one
   history step with origin `ai`. When the change removes blocks or affects other references, 3a's
   impact confirmation asks first, and Send stays busy until you answer it. A candidate that
   `applyAssist` refuses, such as one that changes a forbidden field, applies nothing, and the card
   says why.

On `explained` or `question`, the reply is shown and nothing changes. A `question` reply is
labeled **Question**.

### The turn card

Each answered turn shows the reply as text. A turn that changed the draft adds a card, whose state
is read from the editor's history rather than remembered, so the editor's Undo and Redo are
reflected:

| State | What the card says |
| --- | --- |
| Applied | "Changed N things in the draft. Review before saving." |
| Partly undone | "Some of these changes were undone." |
| Undone | "These changes were undone." |
| Waiting for the impact confirmation | "Confirm to apply these changes." |
| Not applied | "Nothing was applied: <reason>", or "You chose not to apply these changes." |
| From an earlier editing session | "Made in an earlier editing session." |

A per-field **Revert** is a step of its own, so it leaves the card applied.

- **Changes in this turn** lists each change. While they're applied or partly undone, **Jump to**
  moves focus to the change, and on the Flow surface it selects the changed block.
- **Read as context** names the documents the assistant read.
- **Warnings** lists the server's warnings, with **Jump to** when a warning names a field.
- **Undo this change** calls 3a's `revertTurn`. It reverts each key the turn changed that still
  holds what the turn left; a key changed afterwards is skipped. The result is shown and focused,
  for example "Undone: 1 reverted, 1 skipped because it changed later.", "Nothing left to undo for
  this turn." or "This turn can no longer be undone.", which is what a turn from an earlier
  editing session gets. Undo is disabled while a turn runs.

Saving closes the editor, so reopening a saved workflow starts a new editing session, and its
earlier cards are marked as such. Their changes may have been saved, or discarded with Cancel.

### When a turn fails

A failed turn changes nothing. The tab shows the server's `error` as plain text. When `error` is a
single code word and the body has a `message`, it shows the message. When there's neither, it
shows a message for the status:

| Status | Message |
| --- | --- |
| 400 | The assistant couldn't use this request. Nothing was changed. |
| 401 | Your session expired. Sign in again to use Ask AI. |
| 403 | Ask AI isn't available to you right now. |
| 404 | This workflow couldn't be found. It may have been deleted. |
| 409 | The saved workflow changed after the editor opened. Your draft was kept. Reload the workflow to use the assistant. |
| 413 | This request is too large for the assistant. Ask for a smaller change, or start a new thread. |
| 429 | The assistant is busy. Wait a moment, then try again. |
| 500 | The assistant failed. Nothing was changed. Try again. |
| 502 | The assistant's answer couldn't be used. Nothing was changed. Try again. |
| 503 | The assistant is unavailable right now. Nothing was changed. Try again later. |

- **A conflict.** A 409 `workflow_definition_conflict` means the saved workflow changed after the
  editor opened. The draft is kept, and the tab offers **Reload workflow**. It asks first,
  "Reloading discards your unsaved changes to this workflow.", and **Discard and reload** reopens
  the editor on the saved version. When the workflow was deleted, the message adds "Your draft is
  still in the editor."
- **While a reload loads.** The draft it's about to discard is locked: the fields, **Save
  workflow**, undo and redo (including Ctrl+Z and Ctrl+Y), the **Changes** tab, Send, the quick
  actions and each card's **Undo this change**. **Cancel** and Escape still close the editor, so a
  slow reload can't trap the user. A reload that finishes after its editor was closed, saved, or
  replaced by another workflow's editor is ignored, so it can't reopen a closed editor or replace
  one with unsaved changes. If the reload fails, the tab says "Couldn't reload the workflow. Try
  again." and the draft unlocks as it was.
- **A wait.** On 429 and 503, `Retry-After` is honored, as seconds or an HTTP date, or the body's
  `retry_after_seconds`, clamped to an hour. Send, the quick actions and Retry wait, and the tab
  shows "You can send again in N s." A 429 without either waits one second. The wait belongs to the
  user, so every editor in the page shares it.
- **The rate-limit message** is the admin's Markdown, and is shown as plain text.
- **No answer in time.** After 170 seconds: "The assistant took too long to answer. Nothing was
  changed. Try again, or ask for a smaller change."
- **No connection.** "Couldn't reach the assistant. Nothing was changed. Check your connection and
  try again."
- **An unreadable answer**, such as a sign-in page after the session expired: "The assistant's
  answer couldn't be read. Nothing was changed."
- **Cancel** shows "Cancelled. Nothing was changed."

The tab calls the route with `fetch` rather than the app's API client, because the client's errors
don't carry `Retry-After`, and a throttled 503 has nothing else. It keeps the client's base URL,
credentials mode and JSON headers.

### Draft with AI

**Draft with AI** appears on a task whose instructions are empty. It asks
`/api/workflows/draft-instructions`, the route behind the classic editor's draft button, for
instructions based on the workflow's name and description and the task's name. The answer is added
as one undoable AI change labeled "Draft with AI: <task>", and focus moves to the instructions.

- It needs something to go on: a workflow name or description, or a task name other than the
  default "Task N". Otherwise it asks you to name the workflow or the task first.
- It doesn't lock the editor. When the task gained instructions or was removed while it worked,
  nothing is added, and the message says so.
- Instructions longer than the editor's 12,000-character limit aren't added; the message says so.
- It's offered only where Ask AI is. The route checks personal workflow access but not
  `enable_workflow_ai_assistant`, so hiding it with Ask AI keeps the setting's meaning simple.

### Accessibility and plain text

- **Plain text.** Every string from the model or the server, including replies, errors, warnings,
  change summaries, document names and the rate-limit message, renders as React text, never as
  HTML or Markdown. Line breaks are kept.
- **Tabs.** The side panel is an ARIA tab list with automatic activation. The **Ask AI** toggle
  opens the tab and focuses its input.
- **Escape.** In an open `#` menu or document picker, Escape closes just that. Otherwise it closes
  the panel and returns focus to the toggle that matches the tab.
- **Announcements.** The thread is a polite live log, and a failed turn is an alert. The lock
  banner isn't announced separately, because the log already announces the pending turn. Undo's
  result takes focus, so it is read out.
- **Focus.** When the lock ends and focus went with it, focus moves to the Ask AI input. Draft with
  AI puts focus back on its button when it adds nothing.
- **Names.** Buttons name what they act on, such as "Ask AI about this task: Collect evidence",
  "Jump to Workflow: Description" and "Undo this change: <instruction>". States are text, not
  only color.
- **Narrow screens.** The panel takes the editor's place, as **Changes** does, and the footer wraps
  to two rows. Below the small breakpoint the toggle shows an icon with its name kept.

## Usage

### Enable or disable the assistant

The assistant is on by default wherever personal workflows are on. An administrator can turn it
off under **Admin Settings > Workflow > Enable AI Workflow Assistant**. See the
[workflow admin settings](../../admin/workflow.md).

### Use the Ask AI tab

1. Open a personal workflow in the V2 editor, or choose **Edit** on a workflow proposal in chat.
2. Choose **Ask AI** in the footer. To ask about one task, choose **Ask AI** on that task instead.
   The tab shows **About:** with the task's name, and each turn is about that task until you clear
   it.
3. Type a change or a question, or choose a quick action. Type `#` to pick one of your documents;
   the assistant can read it as context or add it to the workflow.
4. Wait for the answer. The editor is locked meanwhile, and **Cancel request** stops it.
5. Review the card and the highlighted fields. **Jump to** takes you to each change.
6. Keep what you want. **Revert** on a field puts back one change, **Undo this change** on the card
   takes back the turn, and the editor's Undo works as usual.
7. Save. Because the draft has AI changes, the first **Save workflow** opens **Review before
   saving**, and **Confirm and save** saves.

The quick actions send a fixed instruction, with no `#` documents, and leave what you've typed in
the input alone:

| Quick action | What it sends |
| --- | --- |
| Explain this workflow | "Explain what this workflow does, step by step. Don't change anything." |
| Tighten task instructions | "Tighten each task's instructions so they are clear and specific, without changing what they ask for." |
| Add a schedule | "Add a schedule that fits this workflow. Ask me if the timing isn't clear." |
| Alert me only when urgent | "Change the alerts so I am alerted only when something is urgent." |
| Check what's needed to run | "Check what this workflow still needs before it can run, such as missing fields or connections. Don't change anything." |

## Testing and validation

All tests use a scripted model. None calls a live model.

| Test | Covers |
| --- | --- |
| `test_workflow_assist_request.py` | Request validation (sizes, shapes, the 2,000-character bound, turn counts, time zones, references and drafts), strict JSON (`NaN`, `Infinity`, `1e999` and overflowing integers are refused; every finite number is read as JavaScript reads it), and authorization (group drafts, another user's draft or base, a stale or deleted base) |
| `test_workflow_assist_operations_security.py` | Every forbidden field and escalation attempt, handle mapping, no raw IDs in the model messages, fenced and bounded excerpts, and model replies with a non-finite number, a lone surrogate or nesting past the limit (corrected once, then 502) |
| `test_workflow_assist_scenarios.py` | The roadmap's "Done when" cases, placement, the un-normalized candidate, the correction round and 502, warnings, deadlines and content-free telemetry |
| `test_workflow_assist_dry_run_parity.py` | The Python `workflowForSave` projection against Phase 2's dry run, including a whole `expected_count` given as `"12"` or `12.0`, which is checked and saved as an `int` |
| `test_workflow_assist_limits_runtime.py` | The limiter (in flight, window, `Retry-After`, refunds, fail closed), the model parameters and provider errors, the runtime adapters, and a whole request against stores that fail on any write other than the caller's rate-limit document |
| `test_workflow_assist_field_parity.py` | The Python field lists, violation messages and editor vocabularies against the V2 TypeScript, read as text |
| `test_workflow_assist_candidate_parity.py` | 24 Python candidates replayed through the real V2 editor code under Node, and the type-strict corpus of numbers, whitespace, JSON literals and File Sync saves. Tables of known JavaScript answers also run without Node. |
| `route_tests/test_workflow_assist_policy.py` | The decorator order, the gates and their status codes, `is_workflow_assistant_enabled_for_user` and the V2 bootstrap flag built from it, and strict response serialization |

The Node tests build the editor code with the V2 app's esbuild, and skip when
`application/v2_ui/node_modules` isn't installed.

Run each file on its own with the pinned venv, for example:

```powershell
$env:PYTHONPATH = "application/single_app;functional_tests"
python -u -m pytest functional_tests/test_workflow_assist_scenarios.py -q
```

### Ask AI tab tests

The tab's tests connect the browser code to 3b's real code rather than to hand-written answers,
so a change on either side that breaks the contract fails a test.

| Test | Covers |
| --- | --- |
| `test_v2_workflow_ask_ai.py` | The tab renders model text as text and never as HTML, imports only local modules, is gated on the bootstrap flag, a personal workflow and a writable editor, and leaves the shared thread's new options off by default. Its instruction limit matches `ASSIST_INSTRUCTION_MAX_LENGTH` and is counted in code points. It runs `test_v2_workflow_ask_ai_logic.ts`. |
| `test_v2_workflow_ask_ai_logic.ts` | Code-point counting and cutting, the request each kind of draft builds, replay (whole exchanges, the control characters, the cap after the suffix, earlier sessions and pending confirmations), each turn's state read from a real authoring session, the response guard and every failure message, the browser request with `Retry-After` and the deadline, the rebase and the change check, and the stores: the card cap, the rate-limit wait, the thread options and held-thread pruning, including a held thread that another conversation's sweep or the 50-thread cap would otherwise drop |
| `test_v2_workflow_ask_ai_parity.py` | Requests the tab builds from editor-normalized drafts (new, proposal, saved version 2 with its revision, saved version 3, focus, time zone, references, a 20-item conversation with emoji, tabs and new lines, and a 2,000-code-point instruction) are each posted as their exact text through 3b's real Flask route with a scripted model. Every candidate-parity scenario is answered the same way. `test_v2_workflow_ask_ai_parity_logic.ts` then replays each real 200 body through the tab: the guard reads it, the rebased candidate passes `workflowAssistViolation`, and the changes it finds are exactly the server's `changes[].key`. |
| `test_v2_assist_thread.py` | A1's and A2's checks, updated for the shared thread's new options |
| `ui_tests/test_v2_workflow_ask_ai.py` | 31 browser cases: the "Done when" instruction from Send to Confirm and save, Run as warnings, each `#` placement and a document read as context, the lock with Cancel and Retry, Ctrl+Z, Ctrl+Y and Ctrl+Shift+Z waiting while a turn or a reload holds the draft, the stale-draft guard, the request a new, saved, focused or flow-focused draft sends, the code-point limit, Undo skipping a field changed later, **Jump to** a task field and a flow block, every failure and the 409 reload, a reload that's closed, superseded by another workflow's editor, or overtaken by a save while it loads, or that fails, hostile model text, where the tab is hidden (setting off, group, reader, unsupported, schedule), the keyboard and Escape, a narrow screen, Draft with AI, the quick actions, and a card from an earlier editing session |
| `ui_tests/test_v2_workflow_ask_ai_proposal.py` | A proposal opened with **Edit** sends no base and saves through review, the tab is hidden when the assistant is off, and the editor's thread leaves the chat's idle image thread alone |

The browser tests answer `POST /api/user/workflows/assist` inside the page with 3b's real
`run_workflow_assist` and a scripted model, from `ui_tests/fixtures/workflow_ask_ai.py`. Build the
V2 bundle first, then run each file on its own:

```powershell
npm --prefix application/v2_ui run build
$env:PYTHONPATH = "application/single_app;functional_tests;ui_tests/fixtures"
$env:PLAYWRIGHT_SERVICE_URL = ""
python -u -m pytest ui_tests/test_v2_workflow_ask_ai.py -q
```

## Known limitations and follow-ups

- **Personal workflows only.** Group workflows never offer Ask AI (roadmap decision 3).
- **Tags and workspaces.** Workflow references hold documents, so the server refuses a `#` tag with
  `tags_unsupported`. The tab's picker offers documents only. A tag or a whole workspace that still
  reaches the input, for example through **Edit and resend**, fails the turn with a message before
  anything is sent.
- **Quick actions send no documents.** They send fixed text only. To use a document, type the
  request and add it with `#`.
- **A field Revert leaves the card applied.** Reverting one field is your own step, so the turn's
  card still reads as applied, even when you've reverted every field it changed. **Undo this
  change** then reverts what's left and leaves the reverted field alone. With nothing left, it says
  "Nothing left to undo for this turn."
- **Earlier editing sessions.** Change tracking starts fresh when the editor reopens, so a turn
  from an earlier session can't be undone. Its card says **Made in an earlier editing session.**
  and **Undo this change** reports "This turn can no longer be undone." Replay tells the assistant
  those changes may not have been saved.
- **Draft with AI isn't gated by the assistant setting on the server.**
  `POST /api/workflows/draft-instructions` checks workflow access, not
  `enable_workflow_ai_assistant`. The V2 editor hides **Draft with AI** whenever Ask AI is hidden,
  but the classic personal and group workspace pages still offer **Draft Workflow Instructions**.
- **Hidden by an active run or lost access.** These hide the tab through the same read-only check
  as a reader's editor, which the browser tests cover, but neither has a browser case of its own.
- **File Sync operations.** Phase 4 (#1547) made personal File Sync editable, and the Python
  `workflowForSave` port now saves an edited File Sync configuration as the editor does. The
  assistant still has no File Sync operations and won't change a File Sync trigger. Adding them is
  a follow-up.
- **Structural flow edits.** For each and If blocks, and adding or moving tasks in a flow, aren't
  supported. The model explains instead.
- **Build errors.** Some dry-run failures have no structured message, and reach the model only as
  a generic "fails a save check" line. Structured errors from Phase 2 would let the correction
  round repair them.
- **Very large drafts.** A draft over the prompt budget is refused rather than summarized.
- **Unsupported publication or flow settings.** The editor's `workflowForSave` also refuses a
  draft that `flowUnsupportedReason` flags, such as a publication task with an unsupported field or
  completion policy. The Python port refuses only `editor_readonly_reason`. The save's own checks
  catch most of these, but not every publication format. A `pdf`, `docx` or `xml` publication, for
  example, passes them, while the editor accepts only `md`, `csv` and `json`. No operation sets
  these fields, so the model
  can't introduce one. But for a draft that already has one, a change can come back without
  `draft_has_errors`, and the editor still won't save it. Porting `flowUnsupportedReason` is a
  follow-up.
- **A global cap.** The limits are per user. A global in-flight cap, like Score's cap of 8, is a
  possible follow-up; provider throttling already returns 503.
- **The rate-limit message.** `assistant_rate_limited` carries the app's shared rate-limit message,
  which may be Markdown. The tab shows it as plain text, so any Markdown appears as written.
- **The conversation isn't stored.** It's ephemeral in v1, as the roadmap decided. The server
  keeps nothing, and reloading the page starts the thread and its cards over.
