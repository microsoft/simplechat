# Chat Orchestration Action Access

Version: **0.261.321**

Implemented in version: **0.261.098**

Retrieved-data charts added in version: **0.261.132**

Operation intent and named inputs implemented in version: **0.261.321**

Application version tracking remains in `application/single_app/config.py`.

## Purpose

**Use an action** lets a chat orchestration plan gather information or perform requested work through an existing
integration without loading a configured agent, its instructions or its unrelated actions.
For example, a ticket-status question can use an existing ticket-system action and pass
its findings to the normal answer step.

This is an optional Gather capability, not a file renderer. Gather placement describes
the integration task's purpose, not a promise that it cannot modify data. Explicit
operation intent lets the planner represent work such as creating a ticket or preparing
and sending an email, subject to the integration's existing policies.

## Research, prepare, and act

A request to send an email about a current event can use Web Search for missing facts,
`compose` to prepare grounded content, an action to deliver it, and another `compose`
step to report the outcome. Complete supplied content does not require redundant research.
The planner reasons over available capabilities and the request; there is no event-name,
email-address, or keyword-routing rule.

`action_invoke` and `agent_invoke` accept `execution_intent`: `gather` or `operate`.
An omitted value remains `gather`, so old M365 plans remain read-only. An operation
does not enable a disabled function, override governance, or replace required approval.
The plan preview labels requested operations; **Ask planner** can revise them before
execution. The existing narrowing controls can disable eligible work.

Prepared text, Markdown, or structured results reach an integration through explicit
named inputs. `depends_on` alone supplies no content. Complete authorized readers
preserve input lineage; incidental sibling notes are not forwarded. Inputs over
64,000 serialized bytes or outside the verified model budget are rejected, not shortened.
Retained document results keep their original prepared snapshot and conversation/run
access rules; current external-source checks still apply.

For M365, `operate` admits only configured email, calendar, or read-state writes:
manual delivery prepares the existing reviewable card, delayed delivery schedules it,
and automatic delivery submits it through the existing authorized path. Plan approval
does not turn manual delivery into automatic sending. A draft or schedule is not reported
as sent, and Graph acceptance does not prove recipient delivery.

Private claimed receipts recover confirmed tool results without making the same call
again. A changed payload, an unfinished effect, or new calls beyond the recovered work
stop for review rather than being blindly replayed. Remote agents without local tool
interception use a conservative invocation receipt. This is not provider-independent
exactly-once delivery.

## Dependencies

- The V2 chat interface and Chat Orchestration must be enabled.
- Semantic Kernel and the separate, default-off **Enable Action Access** switch must be
  enabled.
- At least one existing personal, group or global action must be available to the current
  user under the existing scope, ownership, membership, enablement and governance rules.
- A configured model must support the selected action's function-calling workflow, and
  the action must have the connection and identity configuration required by its type.

No configured or selected agent is required. **Call agent** actions are excluded from
direct action selection; agent delegation continues through **Ask an agent**.

## Architecture and contracts

1. **Discover metadata.** The server resolves actions the user may use and projects safe
   identifying metadata and descriptions. Discovery does not initialize plugins or expose
   action manifests, credentials, endpoints or connection settings to the planner or
   browser. Known M365 function descriptions and configured delivery modes are projected
   separately as safe capability metadata, not raw configuration.
2. **Plan and validate.** The capability is `action_invoke`, labeled **Use an action**, in
   role **Gather**. A step takes `action_ref`, `task`, optional `execution_intent`, and
   optional complete named inputs. Its scope-qualified reference
   distinguishes identically named actions without itself granting access. Named
   dependencies make the findings available to later `compose` or rendering work.
3. **Review the selected resource.** Optional `plan.inputs.actions` contains only
   `{action_ref, display_name, scope_label}` entries. The existing Run view matches each
   action step by reference and renders its authoritative display name and scope as text.
   Older plans without the array still render; missing metadata is not replaced by a
   guessed name or a manifest dump.
4. **Reauthorize and execute.** Execution resolves the selected action again using the
   authenticated caller and current access. It loads that action and any required
   action-local companions, not a configured agent or unrelated tools.
5. **Return findings.** A bounded function-calling loop can invoke several functions from
   the selected action. Findings, supported tool citations and usage flow through the
   existing orchestration result and run paths. Tool text is not relabeled as document
   evidence. Tool invocations use the existing `agent_citations` channel and appear under
   **Sources → Tool calls** on the answer; web references remain in
   `web_search_citations`.

The top-level planner chooses the action and task; the focused loop chooses functions
and binds their arguments. Avoiding agent setup does **not** mean avoiding model calls.
Conversational follow-ups retain their resolved request and bounded, authorized
conversation reference when handed to an action, including accepted clarification answers.

### Charting retrieved data

Since **0.261.132**, an action step can chart what it retrieves. When the user's current
message asks for a chart, or the planner's task for the step asks for one, a chart sub-step
runs after the action's own loop:

- It is a separate model call whose kernel holds only the built-in chart tools. It cannot
  call the action's functions, and it does not count toward the action's function-call limit.
- `chart_retrieved_rows` charts the exact rows a gather call returned, read on the server.
  Time and numeric x values are sorted ascending, and a series longer than 200 points keeps
  each segment's highest and lowest value. The chart subtitle states the sampling.
- It receives the user's saved Instruction memories, so preferences such as chart colors or
  "no charts" apply. An explicit chart request in the current message still wins. Recalled
  facts are never included.
- A chart that cannot be created leaves the step's findings intact and says so.

The step summary reports the result, for example "Used Simulation (3 function calls) and
created 1 chart." The chart travels in the step's tool citations, untruncated, and the answer
places it from the planned visual binding.

Since **0.261.293**, the plan must bind the step's `prepared` output to the compose step
that writes the answer, because only a Reason step reads what a gather step found. A plan
with only the action step is refused while planning, and the planner corrects it. The
answer step receives each chart as its `[[chart:<id>]]` token rather than a second copy of
its data, and the server places the chart at that token. A chart the step drew is still
shown when no answer step placed it, for example in a plan saved before this version. A
chart that couldn't be drawn is reported as not delivered, and a retry runs the action
again after confirmation. See the
[action chart not delivered fix](../fixes/ORCHESTRATION_ACTION_CHART_NOT_DELIVERED_FIX.md).

The existing `/api/v2/orchestration/plan` and `/api/v2/orchestration/run` endpoints and
plan approval/editing flow remain the entry points. There is no second action allowlist,
read/write classification or new approval system.

### Main files

Backend filenames below are under `application/single_app/`; UI paths are
repository-relative.

| Area | Files |
| --- | --- |
| Capability, discovery and validation | `functions_orchestration_registry.py`, `functions_action_catalog.py`, `functions_orchestration_context.py`, `functions_orchestration_planner.py`, `functions_orchestration_schema.py` |
| Execution | `functions_orchestration_actions.py`, `functions_orchestration_adapters.py`, `functions_orchestration_executor.py`, `route_backend_orchestration.py` |
| Settings | `functions_settings.py`, `admin_settings_fields.py`, `route_frontend_admin_settings.py`, `templates/admin/_panes/chat-orchestration.html` |
| Plan and answer display | `application/v2_ui/src/lib/orchestration.ts`, `application/v2_ui/src/lib/orchestrationPlan.ts`, `application/v2_ui/src/components/chat/OrchestrationRunView.tsx`, `application/v2_ui/src/stores/chatStore.ts` |

## Configuration

| Setting | Purpose | Default or existing behavior |
| --- | --- | --- |
| `enable_chat_orchestration` | Makes planning available in V2 chat. | Off |
| `enable_semantic_kernel` | Enables the existing agent/action runtime. | Existing prerequisite |
| `enable_chat_orchestration_actions` | Allows orchestration to choose existing actions directly. | Off |
| `chat_orchestration_enabled_capabilities` | Narrows the capabilities available to plans. | An empty list permits all otherwise-enabled capabilities; a narrowed list must include `action_invoke` for direct actions. |
| `max_auto_invoke_attempts` | Bounds the focused function-calling loop. | Uses the existing runtime limit, not a new setting. |
| `chat_orchestration_step_timeout_seconds`, `chat_orchestration_total_timeout_seconds` | Bound action steps and the whole run. | Existing orchestration limits apply. |

The independent opt-in is necessary because an empty capability list means all
otherwise-enabled capabilities. Adding `action_invoke` to the registry or selecting it in
Capabilities does not enable action access while the new switch is off.

### Existing action scope settings

Direct action discovery honors the existing scope enablement and global-merging settings:

- Personal actions require `allow_user_plugins` and an enabled personal workspace
  (`enable_user_workspace`).
- Group actions require `allow_group_plugins`, enabled group workspaces
  (`enable_group_workspaces`) and current membership in the target group.
- Global actions are eligible in global mode (`per_user_semantic_kernel` off). In
  Workspace Mode, `merge_global_semantic_kernel_with_workspace` must be on to include
  them.

The matching action-type and item-level governance still applies. Enabling global merging
does not override it, and the orchestration opt-in does not enable a disabled action
scope. See [Agents and actions settings](../../admin/agents-actions.md) for these existing
controls.

Both admin surfaces expose the opt-in. V2 uses the declarative field schema and partial
settings updates; saving an unrelated field does not clear a previously saved opt-in.
The template-backed admin form includes the same switch and capability.

## Usage

1. Create or select an existing action using the normal action-management workflow.
   Confirm that its description explains which questions it can help answer.
2. In Admin Settings, confirm Semantic Kernel is enabled, then enable Chat Orchestration
   and **Enable Action Access**. If Capabilities is narrowed, include **Use an action**.
3. In V2 chat, use orchestration and ask a question that needs that integration. There is
   no new composer action picker.
4. Review the action name, scope and task in the existing plan drawer. The task runs as a
   knowledge step before answering, under the deployment's existing approval mode.
5. Follow the step's progress and findings. If access was revoked or the action cannot
   run, the failure is visible rather than silently delegated to another action or agent.

Choose **Ask an agent** instead when the task needs an agent's instructions, knowledge
or broader procedure. A user-selected agent remains meaningful; the planner must not
replace it with direct actions or duplicate the same delegated work.

For action setup and type-specific behavior, use the existing
[Create an action guide](../../guides/create-an-action.md),
[Actions reference](../../reference/actions/index.md) and
[Agents and actions settings](../../admin/agents-actions.md).
See [Orchestration settings](../../admin/orchestration.md) for rollout and limits.

## Testing and validation

- `functional_tests/test_orchestration_actions_admin.py` covers the default-off schema,
  prerequisite visibility, capability selection, template-form round trips and V2 partial
  updates.
- `ui_tests/test_admin_orchestration_actions.py` exercises the real schema-backed admin
  page and template switch in Playwright without writing live settings.
- `ui_tests/test_v2_orchestration_actions.py` uses the existing orchestration browser
  coverage for action identity/scope matching, safe rendering, status changes, normal plan
  edits and older-plan compatibility. It also runs the real controller against done
  frames with tool citations, checking that the standard message Sources panel keeps
  tools separate from web references and renders tool results as inert text.
- Backend action catalog, planning and runtime tests cover authorization, isolated
  execution and failure behavior. The existing orchestration tests remain relevant for
  dependency ordering, executor behavior and citation persistence.
- `functional_tests/test_orchestration_action_runtime.py` also covers the chart sub-step:
  exact rows become at most 200 chronological points, the sub-step cannot call the action,
  saved instructions reach it while facts do not, and capturing runs never add it.
  `functional_tests/test_orchestration_visual_outputs.py` covers placement in the answer.
- TypeScript changes are checked with the existing V2 `npm run typecheck` command.

Browser fixtures use local assets and synthetic data. They do not prove live
connectivity to every action provider; connection and identity failures still need to be
checked against the configured integration.

## Limits and safety boundaries

- One action step can call multiple functions from its selected action, within the
  existing invocation limits, deadlines and cancellation behavior.
- Existing action function restrictions and confirmation behavior are preserved. This
  feature does not certify arbitrary actions as incapable of mutation. M365 gather-intent
  steps retain their write filter; explicit operation steps follow configured write policies.
- Personal, group and global access remain governed by the existing rules. Administrator
  enablement does not grant a user additional access.
- Call agent actions stay outside direct action selection. There is no automatic agent
  fallback when an action fails.
- The focused loop can make model calls and incur both model and integration costs. No
  fixed cost or speed improvement is guaranteed.
- No action-management page or operation-permission editor
  is introduced.
