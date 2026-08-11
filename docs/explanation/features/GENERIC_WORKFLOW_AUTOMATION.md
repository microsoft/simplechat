# Generic Workflow Automation

Implemented in version: **0.250.063**
Enhanced in version: **0.250.065**
Task-level runner selection implemented in version: **0.250.065**
Configurable task limits implemented in version: **0.250.129**

Related issues: #1082, #1084

## Overview

Workflows are repeatable AI automations. Their required configuration is a
workflow instruction and a default runner: either a Direct Model or an Agent.
Each ordered task can inherit that default or select an authorized model or
agent override.
Workspace documents, document actions, File Sync, URL access, alerts, and
scheduling are optional capabilities that can be added when they are relevant
to the task.

Fixed/Implemented in version: **0.250.063**
Configurable task limits implemented in version: **0.250.129**

Related version update:
- `application/single_app/config.py` reports version `0.250.129`.

Dependencies:
- `application/single_app/functions_personal_workflows.py`
- `application/single_app/functions_group_workflows.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/functions_model_endpoint_runtime.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/templates/workspace.html`
- `application/single_app/templates/group_workspaces.html`
- `application/single_app/static/js/workspace/workspace_workflows.js`

## Technical Specifications

### Workflow contract

- Required: `task_prompt` and `runner_type` (`model` or `agent`).
- Optional document context: `document_action` can be `none`, `search`,
  `analyze`, or `comparison`.
- Optional trigger: manual execution, interval schedule, or File Sync change
  monitoring.
- Optional pre-run step: File Sync can run before manual or interval workflows
  without requiring document analysis.
- Each run records its messages and result in the workflow conversation and
  retains the normal workflow run history.
- A workflow can contain up to the admin-configured ordered instruction task
   limit, which defaults to 50 and is hard-capped at 100. A task runner can
   inherit the workflow default, use an authorized Direct Model override, or use
   an authorized Agent override. Every task receives a bounded copy of the
   previous task's response as context.
- Global task error handling supports 0-5 retries and either stops the workflow
   after the final failed attempt or records the failure and continues.
- Tasks without a `runner` field behave as `inherit`, and workflows without a
   `tasks` array retain the legacy single-dispatch path.

New workflow definitions set `chat_capabilities_enabled` to `true`. Existing
saved Direct Model workflows remain on their prior raw-completion behavior when
the field is absent, preserving established results until they are explicitly
migrated or recreated.

### Direct Model execution

When `chat_capabilities_enabled` is enabled, a Direct Model workflow:

1. Resolves the workflow's saved model endpoint and model selection.
2. Creates a Semantic Kernel chat service for that selected model, including a
   configured default-model selection when one is in use.
3. Loads the same headless core plugins used by model-only chat: document
   search, time, math, text, tabular processing, and conversation charts when
   enabled by settings.
4. Invokes the chat service with `FunctionChoiceBehavior.Auto` and the kernel
   instance so supported model tool calls can execute.
5. Saves the response, plugin citations, alerts, and workflow conversation
   metadata through the standard workflow run path.

The workflow runner establishes a scoped user, conversation, workflow, and
group authorization context before loading tools. Group workflows retain their
active group scope while core tools execute.

### Task runner authorization and dispatch

Task runner configuration is validated when a workflow is saved and again
immediately before each task attempt executes:

- Personal workflows resolve agents from the owning user's personal agents and
   currently permitted merged global agents. Group workflows resolve agents from
   the selected group and currently permitted merged global agents.
- Group execution revalidates the current actor's group membership and role at
   the task boundary.
- Model overrides resolve only enabled endpoint and model IDs from current
   global, personal, or group endpoint options. Stored summaries contain no
   endpoint credentials or secrets.
- Agent names, labels, group IDs, and scope flags supplied by the browser are not
   trusted. The saved task receives a normalized identity from the server-side
   authorized option.
- Deleted, disabled, stale, cross-user, and cross-group runners fail the task.
   The workflow's retry count and stop-or-continue strategy handle that failure.

Execution creates a temporary workflow binding for model and agent overrides,
then passes it through the existing document/model/agent dispatch path. The
stored workflow default remains unchanged. Task run items record requested and
resolved runner modes, non-secret model or agent identifiers, execution model
deployment/provider, attempts, status, errors, timestamps, output preview, and
per-task token counts when available.

### Document actions and File Sync

The `No document action` option is the default for new personal and group
workflows. Document picker and analysis controls are initialized only after a
document action is selected. Search, Analyze, and Compare continue to use the
existing document-specialized execution paths and validation.

For ordered workflows, the configured document action applies to the first
task. Later tasks consume the prior task response without repeating document
retrieval or analysis. File Sync remains a single optional pre-run input stage.

File Sync remains independent of document selection. A workflow can run after
syncing sources and then execute its model or agent instruction without a
document action. A File Sync trigger still requires the existing completion and
changed-files safeguards.

### Headless capability boundary

Workflows support server-side core capabilities that can run safely without an
interactive browser session. Streaming, browser-only upload interactions, and
workflows that require a user approval gesture are not executed headlessly.
Model endpoint protocols that do not support function calling still return a
normal model response; capability use depends on the selected endpoint and
enabled plugins.

## Usage Instructions

1. Open the Personal Workspace or a Group Workspace and select Workflows.
2. In `General`, provide a name and choose the Default Runner: Direct Model or
   Agent.
3. In `Trigger`, choose Manual, Interval, or File Sync behavior and configure
   optional URL or File Sync inputs.
4. In `Tasks`, add, edit, remove, or reorder instruction tasks. For each task,
   choose Workflow default, Direct Model, or Agent. Model and agent options are
   limited to the current workspace's authorized choices. Leave `Workspace
   documents` set to `No document action` for prompt-only or agent-only
   automation, or choose Search, Analyze, or Compare for task one.
5. In `Reliability`, choose the task retry count and whether execution stops or
   continues after a failed task.
6. In `Review`, confirm the workflow and choose its completion alert priority.
7. Save the workflow and review task outcomes, citations, and supported
   artifacts in its workflow conversation and run history.

## Testing And Validation

Functional coverage:
- `functional_tests/test_generic_workflow_automation.py` verifies the
  document-optional modal contract and Direct Model/Agent runner paths.
- `functional_tests/test_workflow_model_core_capabilities.py` verifies saved
  model binding, kernel-based core capability invocation, default-model binding,
  and legacy Direct Model compatibility.
- `functional_tests/test_workflow_task_sequence.py` verifies task runner
  normalization, personal/group authorization, disabled and deleted runner
  revalidation, alternating model-agent-model execution, audit/token metadata,
  retries, continue-on-error behavior, bounded chaining, and legacy dispatch.
- `functional_tests/test_workflow_stepped_builder.py` verifies the shared
  five-step modal, conditional runner controls, inherited runner payloads, safe
  task summaries, and existing route reuse.

UI coverage:
- `ui_tests/test_workflow_document_action_modal.py` verifies conditional task
   model/agent controls, task row and Review summaries, safe rendering of
   untrusted labels, reorder persistence, desktop/mobile layout, and preserved
   document action workflows.

Validation should include the focused functional tests, JavaScript syntax
validation, and the UI test against an authenticated `SIMPLECHAT_UI_BASE_URL`
environment.