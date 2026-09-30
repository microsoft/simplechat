# Workflow AI Assistant (v0.261.208)

## Overview

The AI workflow assistant lets a person change a personal workflow by describing the change in
plain language: "run this at 7 AM on weekdays and only alert me when something is urgent", or
"compare every new document against #checklist". The assistant proposes the edit, and the V2
workflow editor shows it as highlighted, attributed, revertible changes that the person reviews
before saving. The assistant never saves anything.

This release adds the server half: `POST /api/user/workflows/assist`. It takes one instruction and
the editor's current draft, asks the model for a small set of allowlisted operations, applies them
to a copy of the draft, checks the result the way a save would, and returns a candidate draft for
the editor's `applyAssist` seam. The **Ask AI** tab that calls it comes in the next release.

Implemented in version: **0.261.208**, tracked in `application/single_app/config.py`.
Phase 3b of the [chat orchestration workflows roadmap](CHAT_ORCHESTRATION_WORKFLOWS_ROADMAP.md)
(#1548, part of #1543).

The assistant ships in three layers:

| Layer | What it adds | Status |
| --- | --- | --- |
| 3a | Change tracking in the V2 editor, including `WorkflowAuthoringSession.applyAssist(candidate, {turnId, label})` | Shipped in 0.261.203 ([Workflow editor change tracking](WORKFLOW_EDITOR_CHANGE_TRACKING.md)) |
| 3b | This endpoint: instruction in, validated candidate out | This release |
| 3c | The **Ask AI** tab on the shared assist thread, which calls this endpoint | Next |

Dependencies:

- Phase 2's draft service: `dry_run_personal_workflow` in `functions_workflow_drafts.py`, which
  builds the save payload exactly as saving would and writes nothing.
- Track A2's `#` reference authorizer: `resolve_scope_references` in
  `functions_orchestration_context.py`.
- The workflow editor options (`get_workflow_editor_options`) and workflow reference loading
  (`load_workflow_reference`).
- The draft-instructions model deployment that `/api/workflows/draft-instructions` already uses.
  No new model setting is added.

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
`features.enable_workflow_ai_assistant`, so 3c can hide the **Ask AI** tab when the assistant isn't
available.

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
- File Sync. There are no File Sync operations until Phase 4's personal File Sync authoring
  lands, and a workflow triggered by File Sync keeps its trigger.
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
directly. It mirrors `workflowForSave` in Python for the personal scope, where `file_sync` isn't
sent. Two test files keep the port honest:

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

## Usage

### Enable or disable the assistant

The assistant is on by default wherever personal workflows are on. An administrator can turn it
off under **Admin Settings > Workflow > Enable AI Workflow Assistant**. See the
[workflow admin settings](../../admin/workflow.md).

### How 3c calls it

1. The **Ask AI** tab posts the instruction, the draft as it stands, the base the editor opened,
   the tab's recent completed turns, any `#` documents and the focused task.
2. On `changed`, it passes `candidate` to `applyAssist(candidate, {turnId, label})` and shows
   `reply`, `changes` (with **Jump to**) and `warnings` on the turn's card.
3. On `explained` or `question`, it shows `reply` and changes nothing.
4. On 409, it keeps the draft and offers to reload the workflow. On 429, it waits for
   `Retry-After`. On any other error, it shows `error` as text, including the rate-limit message.

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
| `test_workflow_assist_candidate_parity.py` | 24 Python candidates replayed through the real V2 editor code under Node, and the type-strict corpus of numbers, whitespace and JSON literals. A table of known JavaScript answers also runs without Node. |
| `route_tests/test_workflow_assist_policy.py` | The decorator order, the gates and their status codes, `is_workflow_assistant_enabled_for_user` and the V2 bootstrap flag built from it, and strict response serialization |

The Node tests build the editor code with the V2 app's esbuild, and skip when
`application/v2_ui/node_modules` isn't installed.

Run each file on its own with the pinned venv, for example:

```powershell
$env:PYTHONPATH = "application/single_app;functional_tests"
python -u -m pytest functional_tests/test_workflow_assist_scenarios.py -q
```

## Known limitations and follow-ups

- **Tags.** Workflow references hold documents, so a `#` tag is refused with `tags_unsupported`.
  3c's picker should offer documents only.
- **File Sync.** There are no File Sync operations until Phase 4's personal File Sync authoring
  lands. The Python `workflowForSave` port will need the personal File Sync fields then.
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
  which may be Markdown. 3c should render it as plain text.
- **The conversation isn't stored.** It's ephemeral in v1, as the roadmap decided.
