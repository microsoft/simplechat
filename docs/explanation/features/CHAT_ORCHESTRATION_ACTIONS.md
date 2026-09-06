# Chat Orchestration Action Access

Version: **0.261.098**

Implemented in version: **0.261.098**

Application version tracking remains in `application/single_app/config.py`.

## Purpose

**Use an action** lets a chat orchestration plan gather information through an existing
integration without loading a configured agent, its instructions or its unrelated actions.
For example, a ticket-status question can use an existing ticket-system action and pass
its findings to the normal answer step.

This is an optional knowledge capability, not a new output or do-something phase. It
retains the selected action's existing behavior: knowledge-phase placement is planning
intent, not a promise that the action cannot modify data.

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
   browser.
2. **Plan and validate.** The capability is `action_invoke`, labeled **Use an action**, in
   phase `knowledge`. A step takes `action_ref` and `task`. Its scope-qualified reference
   distinguishes identically named actions without itself granting access. Normal
   `depends_on` relationships order work before the terminal `respond` step.
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
  harness for action identity/scope matching, safe rendering, status changes, normal plan
  edits and older-plan compatibility. It also runs the real controller against done
  frames with tool citations, checking that the standard message Sources panel keeps
  tools separate from web references and renders tool results as inert text.
- Backend action catalog, planning and runtime tests cover authorization, isolated
  execution and failure behavior. The existing orchestration tests remain relevant for
  phase ordering, executor behavior and citation persistence.
- TypeScript changes are checked with the existing V2 `npm run typecheck` command.

Browser fixtures use local assets and synthetic data. They do not prove live
connectivity to every action provider; connection and identity failures still need to be
checked against the configured integration.

## Limits and safety boundaries

- One action step can call multiple functions from its selected action, within the
  existing invocation limits, deadlines and cancellation behavior.
- Existing action function restrictions and confirmation behavior are preserved. This
  feature does not add a read-only filter or certify an action as incapable of mutation.
- Personal, group and global access remain governed by the existing rules. Administrator
  enablement does not grant a user additional access.
- Call agent actions stay outside direct action selection. There is no automatic agent
  fallback when an action fails.
- The focused loop can make model calls and incur both model and integration costs. No
  fixed cost or speed improvement is guaranteed.
- No output-phase orchestration, action-management page or operation-permission editor
  is introduced.
