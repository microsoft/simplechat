# Workflow draft service

Implemented in version: **0.261.197**.

Application version tracking: `application\single_app\config.py`.

Related issue: #1545, part of #1543. Builds on
[Workflow calendar schedules](WORKFLOW_CALENDAR_SCHEDULES.md) (#1544).

## Overview and dependencies

Chat orchestration is going to propose workflows from a conversation, such as
"every Monday at 08:00 in New York, read my email and list this week's to-dos".
Before it can, the server needs three things:

- a way to check a proposed workflow exactly as a save would, without saving
  anything;
- a narrow format a model can fill in without naming endpoints, models or raw
  document ids;
- a way to create the accepted workflow once, and remember where it came from.

This version adds that service. It has no route or screen of its own. Its first
callers are the V2 workflow assistant (#1548) and orchestration's workflow
proposals (#1547).

What it adds:

- **A dry-run build.** The personal and group save functions are split into a
  build step, which normalizes and authorizes a workflow and writes nothing, and
  a persist step. Saves behave exactly as before.
- **A closed blueprint schema.** A proposed workflow is a small JSON document:
  a name, a trigger, one to five tasks, alert preferences and a Run as choice.
- **A deterministic builder.** It turns a blueprint into a version 2 task-based
  workflow. The same blueprint, handles and proposal always give the same
  workflow.
- **Server-only provenance.** A workflow created from chat records its
  conversation, run and proposal in `origin`, and whether its owner has since
  edited it.
- **Two administrator limits.** A per-user cap on workflows created from chat,
  and a minimum schedule interval for them.
- **Local run time for calendar workflows.** Every run of a workflow with a
  calendar schedule tells the model the run's local date and time, so "this
  week" means the right week. This applies to every calendar workflow, not only
  those created from chat.
- **Stable error codes.** Every refusal names a machine code, a short message
  and the JSON path to fix, so one model repair round can act on it.

Dependencies:

- `jsonschema` (`jsonschema==4.25.1` in `application/single_app/requirements.txt`)
  for the Draft 2020-12 validator. No new package is added.
- Calendar schedules from version 0.261.193 (`functions_workflow_schedules.py`).
- The existing agent, reference and File Sync authorization used by saves.

There's no new route, database container or user-facing control. The two new
settings are on the **Chat Orchestration** admin tab.

## Technical specifications

### Build, then persist

`save_personal_workflow` and `save_group_workflow` keep their signatures. Each
now calls a build function and then writes the result:

| Function | Returns |
| --- | --- |
| `build_personal_workflow_document(user_id, workflow_data, actor_user_id=None, *, settings=None, workflow_id=None, origin=None, user_settings_reader=None, resolve_document=None, sanitize_source=None)` | `(workflow, existing_workflow)` |
| `build_group_workflow_document(group_id, workflow_data, actor_user_id, user_info=None, *, settings=None, workflow_id=None, origin=None, resolve_document=None, sanitize_source=None)` | `(workflow, existing_workflow)` |

The build performs every normalization and authorization a save performed. It
writes nothing: no workflow record, no conversation, no notification, and no
blob, Key Vault or Microsoft 365 call. It reads an existing workflow
conversation to check that it belongs to the user, but never creates one; the
runner creates it on the first run. It needs no Flask request or application
context, so chat orchestration can run it on an executor thread.

Called without the keyword arguments, as a save calls it, the build makes the
same reads in the same order as before. A write-free caller passes:

- `settings`, because loading settings can write defaults;
- `user_settings_reader`, because `get_user_settings` repairs a missing or
  incomplete settings document. The draft service reads
  `read_user_settings_snapshot` instead, which fills the same defaults on a copy
  only;
- `resolve_document`, a memoized resolver for shared references. For public
  workspaces it takes the user's visible workspaces from the settings snapshot
  (`visible_public_workspace_ids_from_user_settings`), because the usual lookup
  can repair the settings document;
- `sanitize_source`, which keeps a File Sync source's name and type only. The
  full sanitizer resolves the source's workspace identity, which can read Key
  Vault; the stored fields are the same.

`workflow_id` and `origin` belong to a server create path, never to a save
payload. See [Provenance](#provenance).

### Draft service

`functions_workflow_drafts.py` holds the service. Every entry point takes the
application `settings` explicitly and needs no request context.

| Function | Purpose |
| --- | --- |
| `workflow_blueprint_schema()` | A copy of the closed schema, for a planner prompt |
| `validate_workflow_blueprint(blueprint)` | The schema check alone; reads nothing |
| `build_workflow_blueprint_payload(blueprint, handles, *, workflow_id, user_id, settings, enabled=False)` | The version 2 payload a blueprint maps to |
| `dry_run_workflow_blueprint(user_id, blueprint, handles, *, origin, settings, user_info=None, ...)` | Every draft check, then the build; returns the workflow document the create would store |
| `create_personal_workflow_from_blueprint(user_id, blueprint, handles, *, origin, settings, user_info=None, enabled=False, ...)` | The same checks, then creates the workflow at most once per proposal |
| `create_personal_workflow_from_payload(user_id, workflow_data, *, origin, settings, user_info=None, ...)` | Creates an accepted proposal the user edited in the workflow editor, under the same id and origin |
| `dry_run_personal_workflow(...)`, `dry_run_group_workflow(...)` | Build an editor payload exactly as a save would, for an assistant previewing a change |
| `check_orchestration_workflow_quota(user_id, settings)` | `quota_exceeded`, or `None` under the cap |
| `orchestration_workflow_id(user_id, proposal_id)` | The workflow id a proposal maps to |
| `read_only_document_resolver(...)` | The write-free document resolver, for callers that build their own drafts |

Dry runs return `{'ok', 'workflow', 'errors'}` and creates return
`{'ok', 'workflow', 'created', 'errors'}`. Creates return the editor
projection, with `definition_revision`, so an editor can open the result.

Workflows created from chat are personal only, as roadmap decision 3 requires.
`create_group_workflow_if_absent` exists for the group follow-on (#1550), but no
blueprint path uses it yet.

### Blueprint schema

The schema is JSON Schema Draft 2020-12, `$id`
`urn:simplechat:workflow-blueprint:1`. Every object sets
`additionalProperties: false`, and every string and array is bounded.

| Field | Rule |
| --- | --- |
| `name` | Required. 1 to 120 characters, not only spaces. |
| `description` | Optional. Up to 1,000 characters. |
| `trigger.type` | Required. `manual`, `calendar`, `interval` or `file_sync`. |
| `tasks` | Required. 1 to 5 tasks, and no more than the administrator's **Workflow Task Limit**. |
| `tasks[].title` | Required. 1 to 120 characters. |
| `tasks[].instructions` | Required. 1 to 4,000 characters. |
| `tasks[].runner` | Optional. `{"type": "agent", "agent_ref": <handle>}` or `{"type": "model"}`. Omitted means the default model. |
| `tasks[].inputs` | Optional. Up to 10 distinct document handles. |
| `alerts.mode` | Optional. `every_run` (the default) or `failures_only`. |
| `alerts.severity` | Optional. `info` (the default) or `low`. |
| `run_as` | Optional. `self` or `none`. |
| `durable` | Optional. Only `true`; every workflow created from chat is durable. |

Trigger fields depend on the type, and fields a type doesn't use are refused
rather than dropped:

| Type | Fields |
| --- | --- |
| `manual` | None. |
| `calendar` | `frequency` (`daily`, `weekdays`, `weekly`, `monthly`), `time_of_day` (`HH:MM`, 24-hour), `timezone` (an exact IANA name the server offers, up to 64 characters). `days_of_week` is required for `weekly` and refused otherwise; `day_of_month` (1 to 31) is required for `monthly` and refused otherwise. |
| `interval` | `unit` (`minutes` or `hours`) and `value` (1 to 59 minutes, or 1 to 24 hours). Seconds aren't offered. |
| `file_sync` | `source_ids` (1 to 10 distinct source handles) and `schedule`, which is `{"kind": "calendar", ...}` or `{"kind": "interval", ...}` with the fields above. |

The whole blueprint must be JSON values only, at most 131,072 bytes as UTF-8 and
nested no more than 16 levels deep.

Nothing in the schema can name a destination, endpoint, URL, deployment, model,
secret or document id. A task can't read another task's output or an earlier
plan step's output: its inputs are fixed when the workflow is created.

### Handles

A blueprint refers to documents, agents and File Sync sources by request-local
handles, such as `q3_report`: a lowercase letter followed by up to 63 lowercase
letters, digits, `_` or `-`. The caller maps each handle to a record it chose
for this user:

```json
{
  "documents": {"checklist": {"document_id": "<id>", "scope_type": "personal"}},
  "agents": {"mail_agent": {"id": "<id>", "name": "mail-agent", "is_global": false}},
  "sources": {"contracts": {"scope_type": "group", "scope_id": "<group id>", "source_id": "<id>"}}
}
```

- `scope_type` is `personal`, `group` or `public`. A personal entry always
  belongs to the requesting user; naming another user's id is refused.
- Each kind holds up to 100 handles.
- Mapping a handle doesn't authorize it. The dry run checks every mapped record
  for the requesting user.
- A handle the blueprint uses that the map doesn't contain is
  `reference_unknown`.
- The map is built by server code, not by a model, so a malformed map raises
  `ValueError` rather than returning draft errors.

### From blueprint to workflow

| Blueprint | Stored workflow |
| --- | --- |
| `manual` trigger | `trigger_type: manual` |
| `calendar` trigger | `trigger_type: interval` with the calendar schedule, which is how calendar schedules are stored |
| `interval` trigger | `trigger_type: interval` with `{unit, value}` |
| `file_sync` trigger | `trigger_type: file_sync`, the schedule, and `file_sync` with `wait_mode: complete`, `continue_mode: changed`, `use_changed_documents: true` and the mapped sources |
| Tasks | Version 2 `instructions` tasks, with `name` from the title |
| `runner.type: agent` | `selected_agent` from the agent handle |
| `runner.type: model`, or no runner | `runner: {type: inherit}`, the default model |
| Task `inputs` | `reference_inputs` named by handle, and each task's `reference_ids` |
| `alerts` | Bell-only alert rules; see below |
| `run_as: self` | `m365_run_as_user_id` set to the user, with no approval yet |

Every created workflow also has `definition_version: 2`,
`durable_execution: true`, `runner_type: model`, no model endpoint or model id,
`chat_capabilities_enabled: false` and `error_handling: {strategy: halt,
retry_count: 0}`. It's paused unless the caller passes `enabled=True`.

In a File Sync workflow, the first task analyzes the documents each sync
changed, when the document analysis action is enabled. Later tasks don't.

**Alerts.** A workflow created from chat is a digest: its results should reach
the notification bell without interrupting anyone. The stored `every_run` mode
always opens a pop-up, so the builder writes `alert_mode: rules` instead:

- with `every_run`, a **Run completed** rule at the chosen severity (`info` by
  default) for completed runs;
- always, a **Run had errors** rule at `low` for failed runs and runs completed
  with task errors.

Both rules deliver `notify_only`, so they never pop up. `alert_evaluation` is
`{on_error: skip}`. With `failures_only`, `severity` is accepted and ignored.

**Determinism.** The workflow id is a UUID 5 of the user and the proposal. Task,
reference and alert rule ids are UUID 5 values of the workflow id and their
position or handle. The builder reads no clock and no random source, so the same
blueprint, handles and proposal always produce the same definition. Only the
stored document's timestamps differ between builds.

### Draft checks

`dry_run_workflow_blueprint` runs these checks in order and stops at the first
step that fails:

1. The personal workflow gate: **Enable Personal Workflows**, and the
   WorkflowUser app role when **Require WorkflowUser App Role** is on. Chat
   orchestration doesn't pass through the save routes' decorators, so the
   service applies the gate itself.
2. The per-user cap, unless the caller passes `check_quota=False`. It comes
   before the schema, so a user at the cap isn't asked to repair a blueprint
   that can't be created.
3. The schema.
4. The task limit: the smaller of 5 and **Workflow Task Limit**.
5. Unknown handles.
6. The schedule, agents, documents and File Sync sources, collected together so
   one repair round can fix them all:
   - the schedule must be valid and meet the minimum for workflows created from
     chat;
   - each agent must be one the user could pick for a workflow task in the
     editor: agents and user agents are enabled, and the agent is one of the
     user's enabled personal agents or a global agent merged into their
     workspace;
   - each document must be one the user can read now;
   - each source must exist, be one the user can use, and have File Sync enabled
     for its workspace.
7. The build, with the origin, which returns the normalized document.

### Error codes

Every error is `{code, message, path}`. `path` is an RFC 6901 JSON pointer into
the blueprint, such as `/tasks/0/runner/agent_ref`; `''` is the whole
blueprint. At most 10 errors are returned, sorted by path.

| Code | Meaning | Path |
| --- | --- | --- |
| `blueprint_invalid` | A value has the wrong type, length, range or format, or the blueprint is too large, too deep or not JSON | The value |
| `unsupported_field` | A field the schema doesn't define, or one the chosen trigger, frequency or runner doesn't use | The field to remove |
| `too_many_tasks` | More than 5 tasks, or more than **Workflow Task Limit** | `/tasks` |
| `trigger_invalid` | A trigger or schedule field is wrong; an unknown time zone points at `timezone` | The trigger field |
| `cadence_below_minimum` | An interval shorter than the minimum for workflows created from chat; the message names the minimum | `/trigger` or `/trigger/schedule` |
| `quota_exceeded` | The user already has the most workflows created from chat allowed | `''` |
| `agent_unavailable` | `agent_ref` names an agent the user can't use | Each use |
| `reference_unknown` | A handle the request didn't map, or text that isn't a handle | Each use |
| `reference_unauthorized` | A document the user can't read, including one held for content review | Each use |
| `file_sync_source_unavailable` | A source that doesn't exist or isn't available, or whose workspace doesn't allow File Sync | Each use |
| `workflows_unavailable` | Personal workflows aren't available to the user | `''` |
| `workflow_conflict` | A different workflow already uses the proposal's id, or it's being deleted | `''` or `/id` |

Messages are built only from fixed text and schema limits, such as "Must be 120
characters or fewer." They never repeat the caller's input; an unexpected field
whose name isn't plain letters, digits, `_` or `-` is reported at its parent
object instead of by name. Log entries record error codes only, never the
blueprint.

Two failures raise instead, because no repair can fix them: `ValueError` for a
malformed handle map, origin or missing settings (a caller bug), and
`WorkflowLoopLimitError` for a misconfigured administrator limit (a server
fault).

The payload dry runs, `dry_run_personal_workflow` and `dry_run_group_workflow`,
return the codes and messages the save routes return, such as
`invalid_workflow`, `not_allowed` and `workflow_definition_conflict` for a stale
`definition_revision`.

### Provenance

A workflow created from chat stores:

```json
"origin": {
  "source": "orchestration",
  "conversation_id": "<conversation id>",
  "orchestration_run_id": "<run id>",
  "proposal_id": "<proposal id>",
  "created_at": "2026-09-28T12:00:00+00:00",
  "edited": false
}
```

- `source` is a closed list; `orchestration` is its only value. The three ids
  are required, up to 128 characters each, and `created_at` is an ISO 8601
  timestamp.
- **Server only.** Only the server create paths record it. The build never reads
  `origin` from a payload, so the personal and group save routes ignore any
  `origin` a caller sends, when creating or updating. An ordinary workflow can't
  gain one.
- **Preserved.** Saves, runs, enabling and pausing keep the stored origin.
- **Edited.** `edited` becomes `true` the first time the owner saves a material
  change: the name, description, alerts, error handling, or anything that
  changes how the workflow runs, such as its tasks, schedule, trigger, runner,
  model, references or Run as user. It stays `true` even if the change is
  reverted. Enabling, pausing and run progress aren't edits.
- **Outside the fingerprint.** `origin` isn't part of the definition revision or
  the Microsoft 365 Run as fingerprint. Recording it, or setting `edited`, never
  invalidates an open editor's revision or a Run as approval. A material change
  that is part of the fingerprint, such as a task change, still needs renewed
  approval as before.

### Creating a workflow at most once

`orchestration_workflow_id(user_id, proposal_id)` derives the workflow id from
the user and the proposal, so accepting the same proposal twice finds the first
workflow instead of creating another. Accepting it again returns the stored
workflow with `created: false`, even when the user has since reached the cap.

`create_personal_workflow_if_absent` and `create_group_workflow_if_absent` take
that id and the origin. The store creates the record only if no record has that
id. A record already there from a different proposal, an ordinary workflow, or a
workflow being deleted is `workflow_conflict`; the create never adopts or
revives another record. A save payload can't choose the id.

### Limits for workflows created from chat

| Setting | Default | Range | Applies |
| --- | --- | --- | --- |
| `chat_orchestration_max_workflows_per_user` | 20 | 1 to 100 | When a workflow is created from chat |
| `chat_orchestration_min_workflow_interval_seconds` | 3,600 (hourly) | 60 to 86,400 | When a workflow is created from chat |

- The cap counts the user's workflows whose `origin.source` is `orchestration`
  and that aren't being deleted. Workflows the user builds in the editor never
  count. A count that fails refuses the create rather than treating the count as
  zero. Two accepts at the same moment can both pass, so the cap can be exceeded
  by the number of concurrent accepts.
- The effective minimum interval is the larger of this setting and the general
  **Workflow Minimum Schedule Interval**. Calendar schedules run no more than
  once a day, so they always pass.
- Both limits apply when a workflow is created from chat. The owner's later edits
  follow only the general minimum, like any other workflow.
- Workflows without an orchestration origin are unaffected.
- The V2 admin page refuses a value outside the range. The classic admin page
  keeps its existing behavior of clamping to the range.

### Calendar run time in the prompt

`workflow_run_time_context(schedule, run_started_at)` in
`functions_workflow_schedules.py` returns a line such as:

```text
Current date and time: Monday, 28 September 2026, 09:00 (America/New_York)
```

It returns `''` for any schedule that isn't a valid calendar schedule, and for a
start time it can't read. It never raises. Day and month names are fixed English
text, not the server's locale.

The runner adds the line under a `[Workflow run time]` heading when the
workflow's stored trigger is scheduled (`interval` or `file_sync`) and its
stored schedule is a calendar schedule:

- **Scope follows the stored schedule, not how the run started.** Scheduled
  runs, catch-up runs and **Run now** all get the line.
- **Actual start time.** The line uses the run's start time in the schedule's
  time zone, so it's right on both sides of a daylight saving change. A resumed
  durable run keeps its original start time.
- **Every task.** Each task of a task-based workflow gets the line. It comes
  after the File Sync context on the first task, and before the previous task's
  output.
- **Unchanged prompts elsewhere.** Manual workflows, including one that still
  stores an unused calendar schedule, and interval workflows get byte-identical
  prompts. Calendar schedules are new in 0.261.193, so no existing prompt
  changes.
- **Prompt only.** The line is added to that run's copy of the workflow. It's
  never stored in the definition and never enters the fingerprint. Document
  search in legacy single-prompt workflows still uses the prompt without it.

### Files

| File | Change |
| --- | --- |
| `application/single_app/functions_workflow_drafts.py` | New: the schema, handles, builder, checks, dry runs and creates |
| `application/single_app/functions_personal_workflows.py` | `build_personal_workflow_document`, `create_personal_workflow_if_absent`, `count_personal_orchestration_workflows`; the save builds, then persists |
| `application/single_app/functions_group_workflows.py` | `build_group_workflow_document`, `create_group_workflow_if_absent`; the save builds, then persists |
| `application/single_app/functions_workflow_definition_store.py` | `create_workflow_definition_record_if_absent` |
| `application/single_app/functions_workflow_definitions.py` | Origin rules, `WorkflowCadenceError`, `existing_server_created_workflow` |
| `application/single_app/functions_workflow_schedules.py` | `enforce_orchestration_workflow_cadence`, `workflow_run_time_context` |
| `application/single_app/functions_workflow_limits.py` | The two limits' ranges, validation and getters |
| `application/single_app/functions_workflow_runner.py` | Adds the run-time line to calendar runs |
| `application/single_app/functions_settings.py` | Defaults, update validation and `read_user_settings_snapshot` |
| `application/single_app/functions_public_workspaces.py` | `visible_public_workspace_ids_from_user_settings` |
| `application/single_app/functions_search_service.py` | `resolve_document_context` accepts precomputed public workspace visibility |
| `application/single_app/admin_settings_fields.py` | The V2 admin fields |
| `application/single_app/route_frontend_admin_settings.py` | The classic admin save |
| `application/single_app/templates/admin/_panes/chat-orchestration.html` | The classic admin fields |

## Usage

### Enable or configure

Nothing needs turning on; chat orchestration features call the service. To
change the limits, turn on **Enable Chat Orchestration** in **Admin Settings >
Orchestration > Chat Orchestration**, then set **Workflows Created From Chat Per
User** and **Minimum Schedule Interval For Workflows Created From Chat
(seconds)** under **Limits**. See [Orchestration settings](../../admin/orchestration.md).

### Check and create a proposed workflow

A caller, such as orchestration's workflow proposal, checks the blueprint, shows
the result, and creates the workflow when the user accepts:

```python
from functions_workflow_drafts import create_personal_workflow_from_blueprint, dry_run_workflow_blueprint

blueprint = {
    "name": "Weekly to-do digest",
    "trigger": {
        "type": "calendar", "frequency": "weekly", "days_of_week": ["monday"],
        "time_of_day": "08:00", "timezone": "America/New_York",
    },
    "tasks": [{
        "title": "List this week's to-dos",
        "instructions": "Read my email from the past week and list the to-dos I need to finish this week.",
        "runner": {"type": "agent", "agent_ref": "mail_agent"},
    }],
    "alerts": {"mode": "every_run", "severity": "info"},
    "run_as": "self",
}
handles = {"agents": {"mail_agent": {"id": agent_id, "name": agent_name, "is_global": False}}}
origin = {
    "source": "orchestration",
    "conversation_id": conversation_id,
    "orchestration_run_id": run_id,
    "proposal_id": proposal_id,
    "created_at": proposed_at,
}

preview = dry_run_workflow_blueprint(
    user_id, blueprint, handles, origin=origin, settings=settings, user_info=user_info,
)
if not preview["ok"]:
    repair_prompt_errors = preview["errors"]  # [{'code', 'message', 'path'}, ...]

# After the user accepts:
result = create_personal_workflow_from_blueprint(
    user_id, blueprint, handles, origin=origin, settings=settings, user_info=user_info,
)
```

The workflow is created paused, with a bell-only alert for each completed run
and each run with errors. It runs every Monday at 08:00 in New York, and each
run's prompt says, for example, "Current date and time: Monday, 5 October 2026,
08:00 (America/New_York)".

If the user edits the proposal in the workflow editor before accepting, the
caller passes the editor's payload to `create_personal_workflow_from_payload`
with the same origin. Either path creates the same workflow once. A payload
that turns on URL Access is refused with `unsupported_field` at
`/url_access_enabled`. The runner treats a stored URL Access authorization as
proof of the user's **UrlAccessUser** role, and only the save route may grant
it, so the payload create also drops any authorization fields the caller sent.

### What an owner sees

A workflow created from chat is an ordinary personal workflow. The owner can
open, edit, run, pause or delete it. Its first material edit sets
`origin.edited`, so later features can tell a workflow the owner has reviewed
from one they haven't.

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_workflow_draft_save_parity.py` | 23 personal and group save scenarios (manual, interval, calendar and File Sync triggers; alerts; references; agents; custom models; Microsoft 365 Run as with fingerprints and approvals; versions 1 to 3; refusals), compared field by field with results captured from the code before the refactor |
| `functional_tests/test_workflow_draft_service.py` | Both example blueprints dry-run with zero writes and no conversation, including on an executor thread and with no Flask context; one refusal for each error code; forbidden fields, bounds, six tasks, oversize text and unknown handles; messages that never repeat input; builder determinism; bell-only digest alerts; File Sync defaults; the default model; creates that happen once per proposal, even at the cap; conflicts; payload dry runs and creates, which never authorize URL Access; workflows without an origin unaffected |
| `functional_tests/test_workflow_origin_provenance.py` | The real personal and group save route bodies ignore a forged origin on create and update; ordinary workflows can't gain one; each material change sets `edited` and non-material saves don't; the origin is outside the fingerprint and revision, so a description edit keeps a Run as approval; idempotent creates and their conflicts |
| `functional_tests/test_workflow_orchestration_limits_settings.py` | Defaults, validation, fail-closed getters, the combined minimum, the V2 fields and their gating, classic clamping, `update_settings` validation, and the admin docs |
| `functional_tests/test_workflow_run_time_context.py` | Calendar runs in America/New_York on both sides of a daylight saving change; Run now and resumed runs; every task of task-based and structured workflows; manual and interval prompts byte-identical to those captured before this change |

Performance: the schema validator is compiled once per process. A dry run
caches each user's settings snapshot and each document lookup it makes, for the
length of that dry run, and makes one count query for the cap.

Known limitations:

- The cap is checked before the write without a lock, so simultaneous accepts
  can exceed it by the number of accepts in flight.
- After a workflow created from chat has been deleted, accepting the same
  proposal again creates it again. While the deletion is still in progress, the
  accept is refused with `workflow_conflict`. Whether an accepted proposal
  should stay spent is left to #1547, which owns proposal state.
- The service checks that an agent is available, not that it has the actions a
  task needs, such as sending email.
- `run_as: self` records the Run as user without an approval. As for any
  workflow, the user must approve Microsoft 365 access before the workflow can
  act as them.
