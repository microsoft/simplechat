# Orchestration Microsoft 365 File Action Evidence Fix

**Version: 0.261.300**

Fixed in version: **0.261.300**, recorded in
`application/single_app/config.py`.

This affects the React V2 branch (`paullizer-react-v2-ui`) and deployments built
from it.

## Issue

In chat, the user's `m365` agent answered "what is the EVA Swab Tool" from a NASA
PDF in their SharePoint document library. With **Orchestrate** on, the planner
chose a **Use an action** step with the user's **M365 SharePoint** action. The step
made one function call and reported **Completed**, but the answer said the search
"did not return any documents or excerpts because the connected document-evidence
service could not run."

## Root cause

### Telemetry

App Insights for the deployment recorded one Microsoft 365 failure for the
orchestrated step and none for the agent's successful search. App events are
`traces` with the message `[SIMPLE_CHAT_LOG_EVENT]` and the event text in
`customDimensions.sc_message`:

| Time (UTC) | Event | `sc_failure_code` | `sc_resource` | `sc_operation` |
| --- | --- | --- | --- | --- |
| 2026-10-07 21:40:39 | `[MS_GRAPH_PLUGIN] Microsoft 365 operation could not complete.` | `model_context_unavailable` | `spo` | `search_files` |

The step's model never sent the search to Microsoft Graph. The function refused the
call before any Microsoft 365 request.

### Why a plan step had no model budget

SharePoint and OneDrive file functions bound the excerpts and file content they
return by the model's remaining context. `search_files`, `read_file`,
`read_file_chunk` and `analyze_file` read that room from a task-local budget that
`configure_m365_model_context()` sets.

- In chat, `LoggingChatCompletionAgent.invoke` runs inside
  `m365_agent_continuation`. Its continuation journal binds the agent's
  `ModelTokenBudget` before each tool call, and offers the agent to deeper file
  analysis.
- An orchestration **Use an action** step calls its model directly, with a bare
  Semantic Kernel kernel and no agent. The
  [Microsoft 365 action context fix](ORCHESTRATION_M365_ACTION_CONTEXT_FIX.md) in
  0.261.238 gave these steps a Microsoft 365 execution context, but nothing bound a
  model budget.

So every file function refused the call with `model_context_unavailable`: "Select an
agent with verified model token limits before adding file evidence." Calendar and
Email functions don't use the budget, which is why those plan steps worked.

### Why the step still completed

`result_refusal()` stopped a step only for sign-in, approval and authorization
refusals. `model_context_unavailable` is none of those, so the refusal reached the
model as an ordinary result. The model reported it as findings, and the final
answer said the documents couldn't be searched.

### Deeper file analysis could never finish in a plan

`analyze_m365_memory()` took its model from the chat agent's continuation journal.
In a plan step, `analyze_file` stopped for the user's extended-analysis approval.
After the user approved it and retried the step, the approval was found, but no
agent existed. The step then failed with `m365_unavailable`, telling the user to
check their access, and every retry failed the same way.

## Changes

### Each file step binds its own model

`invoke_action()` in `functions_orchestration_actions.py` treats an
`m365_sharepoint` or `m365_onedrive` action as a file step:

- `_build_file_action_model()` builds the step's model from the same single
  endpoint and model resolution as `_build_action_model()`, which keeps its
  signature. `_action_model_budget()` derives the step's `ModelTokenBudget` the way
  `build_agent_model_budget()` does for an agent:
  - It uses secret-free projections of the resolved model and endpoint records, or
    of the classic `gpt_model` deployment.
  - It uses the protocol the service speaks.
  - It sets no request output limit. The step doesn't cap its model's output, so
    the model's documented output limit is reserved.
- `file_step_filter()` in `functions_orchestration_m365.py` is an auto
  function-invocation filter. Around each of the step's function calls, it binds:
  - The model budget, measured against the step's current chat history and tool
    schemas.
  - The step's own model, offered to retained-file analysis for this request only.

  Both end with the call.

### Deeper file analysis uses the step's model

`get_m365_analysis_model()` in `functions_m365_agent_continuation.py` replaces
`get_m365_analysis_agent()`. It returns the chat agent's model through the
continuation journal, as before. Without a journal, it returns the model that
`m365_step_model_binder()` bound for the same request, data user and conversation.
Any other request is refused with `m365_analysis_unavailable`.
`analyze_m365_memory()` reads the deployment name, budget, service and settings
through this lookup. Batches still remove tools, cap output at 1,536 tokens and
check the model's room.

### Model limits are checked before the step reads anything

The step's model must have verified token limits, from the model catalog or Model
Endpoints. `file_step_filter()` checks the budget before the step's model or
Microsoft Graph is called. A model without usable limits stops the step with the
new `m365_model_limits_required` failure, and the stop keeps the budget code, such
as `model_generation_unbounded`.

### Application failures stop the step

`result_refusal()` and `failure_code()` now stop a step on two more kinds of
function result. These describe the application, not the user's data:

| Failure code | Function result codes |
| --- | --- |
| `m365_model_limits_required` | `model_context_unavailable`, `model_generation_unbounded`, `model_input_estimate_unavailable`, `model_context_invalid`, `model_tool_configuration_invalid` |
| `m365_evidence_unavailable` | `memory_unavailable`, `memory_access_denied`, `memory_context_mismatch`, `memory_busy`, `memory_recovery_required`, `request_memory_binding_required`, `request_memory_mismatch`, `request_memory_busy`, `invalid_request_memory`, `invalid_model_budget`, `m365_continuation_unavailable` |

Bounded-coverage outcomes stay findings that the model reports. These include
`model_context_full`, `memory_hard_limit`, `request_operation_limit`,
`search_limit`, nothing found and throttling.

Both failures are in `M365_STEP_FAILURE_CODES`, so a step's failure keeps its file
source in `m365_sources`. Their messages name the next step:

- `m365_model_limits_required`: ask an admin to set the model's token limits in Model
  Endpoints, then ask again. A retry runs the plan's approved model, and an Auto plan
  whose model limits changed asks for a new plan.
- `m365_evidence_unavailable`: retry, then ask an admin to check the app's chat
  storage.

The V2 run details show both messages. No UI change was needed.

## Files modified

| File | Change |
| --- | --- |
| `functions_orchestration_actions.py` | `_resolve_action_model()`, `_action_model_configuration()`, `_build_file_action_model()` and `_action_model_budget()`. `invoke_action()` builds a file step's model with its budget and registers `file_step_filter()`. |
| `functions_orchestration_m365.py` | `m365_file_source()`, `file_step_model_limits()`, `file_step_filter()`, and the model-limit and evidence refusal codes. |
| `functions_m365_agent_continuation.py` | `M365AnalysisModel`, `get_m365_analysis_model()` and `m365_step_model_binder()`. |
| `functions_m365_analysis_runtime.py` | Reads its model through `get_m365_analysis_model()`. |
| `functions_orchestration_schema.py` | `m365_model_limits_required` and `m365_evidence_unavailable`. |
| `config.py` | Version `0.261.300`. |

## Validation

### Tests

`functional_tests/test_orchestration_m365_file_actions.py` runs:

- The real action runner, step scope, Microsoft 365 runtime, approval service and
  SharePoint plugin.
- The production file-runtime wiring, through `configure_m365_file_runtime()`,
  through a real Flask bridge.

Microsoft Graph, blob storage, Cosmos and the model are doubled, and network access
is blocked. The tests check that:

- A SharePoint step's `search_files` finds the document through Microsoft Graph
  search, and returns its excerpt with a measured context budget. The step
  completes with the excerpt in its findings.
- A step model without verified token limits stops the step with
  `m365_model_limits_required`, before the model or Microsoft Graph is called.
- Unavailable conversation evidence fails the step with
  `m365_evidence_unavailable`, instead of findings.
- `analyze_file` stops for the user's approval. After the approval, a retry reuses
  the captured file, and the analysis batch runs on the step's own model. The batch
  carries the file's evidence, has no tools and caps output at 1,536 tokens.
- The binding serves only its own request, data user and conversation, and ends
  with the call.
- Model-limit and evidence codes stop the step, and capacity outcomes stay findings.
- The step budget comes from the resolved endpoint record, the classic deployment
  settings, or the Anthropic protocol. An unlisted model has no usable budget.

Four deliberate breaks each make at least one test fail:

- Not registering the step filter, which is the shipped bug.
- Not binding the analysis model.
- Keeping evidence refusals as findings.
- Skipping the up-front limits check.

`functional_tests/test_m365_runtime_adapters.py` now supplies the analysis model
through `get_m365_analysis_model()`. The existing orchestration, Microsoft 365
provider, file analysis and continuation tests pass unchanged.

### Before and after

| Before | After |
| --- | --- |
| Every SharePoint or OneDrive file function in a plan refused the call with `model_context_unavailable`. | The step's own model bounds file content, as the agent's model does in chat. |
| The refusal became findings, the step completed, and the answer said the documents couldn't be searched. | Model-limit and evidence failures stop the step with a message that names the fix. |
| After the user approved deeper analysis, every retry failed with `m365_unavailable`. | A retry after the approval analyzes the file on the step's own model. |

## Limitations

- Each `analyze_file` call processes one captured chunk. **Max auto-invoke
  attempts** limits a step's function calls, so a long file can finish with partial
  coverage. The analysis checkpoint lets a retry continue where it stopped.
- A model without published token limits can't add file evidence in a plan, the
  same as in chat. Set the limits in Model Endpoints, or choose a catalog model.

## Related

- [Orchestration Microsoft 365 action context fix](ORCHESTRATION_M365_ACTION_CONTEXT_FIX.md)
- [Microsoft 365 actions in plans](../../admin/orchestration.md#microsoft-365-actions-in-plans)
- [Logging tags](../../reference/logging-tags.md)
