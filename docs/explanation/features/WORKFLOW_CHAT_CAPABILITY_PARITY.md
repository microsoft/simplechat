# Workflow chat capability parity (v0.261.343)

Implemented in version: **0.261.343**.

Application version tracking: `application/single_app/config.py`.

## Purpose and dependencies

Workflows execute repeatable tasks as their authorized user without requiring
an open browser. Ordinary workflows can now use the existing orchestration
planner and execution harness rather than treating the legacy core-plugin
switch as full chat capability support. Audit history stays separate from the
optional results conversation people read and continue.

Dependencies are the existing personal/group workflow policies, chat
orchestration, capability registry, retained results and output continuation
services. Shared delivery also needs the existing collaboration feature and
authorized recipients. No new research provider, app role, approval policy,
recipient-discovery engine or output format is introduced.

## Configuration and compatibility

`functions_workflow_configuration.py` validates two versioned authored objects:

| Object | Fields and meaning |
| --- | --- |
| `chat_execution` | `version: 1`, `mode: orchestration/selected/off`, `required_capabilities`, `visual_requirements`. Task omission means inherit; a task override replaces the workflow configuration. |
| `results_delivery` | `version: 1`, `mode: history/conversation/task`, `conversation_type: personal/shared/group/group_shared`, canonical `recipient_ids`, `all_group_members`. A group destination stays in the workflow's group. |

New ordinary workflows default to automatic orchestration when enabled,
otherwise the existing core-capability default. Their results default to a
private conversation in their scope. Existing saved definitions retain their
legacy behavior until changed. Specialized frozen-plan and chat-origin
producers keep their existing contracts.

Selected capabilities are positive requirements, not a new permission
allowlist. Required unavailable or failed execution cannot succeed by returning
a raw-model substitute. Charts and diagrams use the existing planned visual
deliverables; image proposals use the existing composition visual option.
Recursive workflow-control capabilities are not exposed by this integration.

## Runtime and identity

`functions_workflow_chat_execution.py` binds a task-local owner identity and
builds the existing composer seeds from saved source, agent and model choices.
Current workflow, group and source access still apply. Existing server-authored
owner-bound URL/deep-research grants provide only those optional roles; arbitrary
stored roles are not restored.

Each workflow run/task or structured task execution has a deterministic child
orchestration identity. A new run plans again. A resume adopts the same bound
child and its checkpoints instead of issuing a new search or external action.
The workflow lease owns continuation through the existing orchestration
scheduler/output services; general chat scans do not independently drive these
children.

Search tasks use the real search adapter rather than first running legacy
search and then searching again. Explicit Analyze, Compare and Merge operations
retain their canonical workflow output and a document-operation checkpoint.
Additional requested chat work consumes that completed outcome without
repeating the document operation. Saved-analysis-only and runtime-choice
restrictions remain intact.

Waiting output releases the workflow worker. Polling does not count as another
task attempt. Required incomplete output remains a visible failure, not a
successful model-only result. Workflow cancellation uses the existing child
cancellation and publication fence.

## Results, history and follow-up

Every new run has its own audit conversation. Generated titles use the workflow
name and run date/time, while the conversation list displays an additive
**Workflow** tag. Existing titles are not bulk-renamed.

Conversation delivery publishes actual output, citations and supported
artifacts through the existing conversation/collaboration services, with durable
receipts and stable message/invitation identities. Retrying delivery reuses the
same destination. Shared delivery does not grant audit access. Notifications
prefer the saved results destination instead of guessing from response text.

Task/agent-controlled delivery and chat-origin post-back retain their existing
meaning. Automatic delivery is not added to a legacy definition that never
requested it. Delivered conversations are normal conversations that users can
continue; they do not automatically acquire the restrictive selected-run chip
used by the separate saved-result follow-up feature.

## Ask AI and editor

The shared V2 editor exposes workflow defaults, replacing task overrides and a
Results section. Ask AI uses the same closed configuration operations,
validation, change history and undo path. The group assist endpoint is
`POST /api/groups/<group_id>/workflows/assist`; the personal endpoint remains
`POST /api/user/workflows/assist`.

Authorized people are represented by request-local handles during authoring.
Ask AI cannot invent recipient IDs, grant access, silently select an ambiguous
person or invite anyone while drafting. All-current-group-members delivery is
an explicit selection, not a new dynamic audience-discovery service.

## Validation and limitations

Regression coverage includes:

- `test_workflow_configuration.py` and save-parity tests for defaults, inheritance,
  revisions, snapshots, legacy preservation and scope validation.
- `test_workflow_chat_execution.py` for the actual offline planner/harness,
  attested web acquisition and retained sources, child reuse, failed-upload file
  continuation without another model call, cancellation, source selections,
  canonical document hand-off and concurrent identity isolation.
- `test_workflow_assist_chat_results.py` and workflow-assist policy tests for
  personal/group authoring, required-tool selections, recipients and permissions.
- `test_workflow_results_delivery.py` for per-run history, publication,
  idempotency, destination authorization and result alerts.
- `test_v2_workflow_chat_controls.mjs` and
  `ui_tests/test_v2_workflow_chat_controls.py` for editor controls and badges.

External providers are doubled in offline tests; these are not evidence of a
live deployment. Provider metadata timeouts, uncertain result commits and
checkpoint-recovery failures remain distinct runtime failures. This integration
does not claim to repair that separate failure chain.
