# Orchestration Model Selection Fix

**Version: 0.261.102** (tracked in `application/single_app/config.py`)

**Fixed in version: 0.261.102**

## Issue

V2 Orchestrate could use GPT-4o even when the user selected GPT-5.6 Terra in
**Manual controls** and the admin default also pointed to Terra. The selected model
identity reached the backend and was saved with the run, but planning and answer
generation still used the legacy chat configuration.

This was separate from the second-question resolver validation failure. Both fixes
are delivered in **0.261.102**, after integrating the newer V2 inline-answer and
approval-persistence changes.

## Root cause

The orchestration answer closure constructed its client without the saved selection.
The planner's legacy resolver likewise preferred the classic `gpt_model.selected`
list when no dedicated deployment override was present, ignoring the modern
`default_model_selection` reference. Selecting a different deployment string alone
would not fix this: a model connection can have a different endpoint, credential,
provider protocol and caller-identity header policy.

The answer stream also omitted model attribution, so the existing V2 message
renderer could not show the model that actually produced an orchestrated answer.

## Resolution

`functions_orchestration_models.py` provides an authorized binding used by the
orchestration HTTP routes. Answer selection follows this order:

1. The model selected in Manual controls.
2. The admin default model connection, when no manual selection was supplied.
3. The configured classic single-endpoint/APIM model, only when neither applies.

Endpoint-backed choices use `resolve_model_endpoint_from_context(..., authorize=True)`
and the existing protocol-aware client factory. Provider, endpoint, model ID and
deployment must agree. Disabled, deleted, inconsistent or inaccessible selections
fail explicitly; they do not become a request to GPT-4o.

The resolved answer identity, including an admin default, is pinned in the saved
plan's seeds. Execution reauthorizes that selection rather than applying a newly
changed default or accepting replacement model fields on the run request.

### Planning and research

Without a dedicated planner override, conversational resolution, plan generation,
research query/review completions and answer synthesis use the same selection.
Trivial plans still avoid a planning completion.

A dedicated planner remains independent of the answer. Deployment-only overrides
retain the classic/APIM connection. The existing planner endpoint/model/provider
fields can instead identify a separate authorized model connection. An unavailable
answer or planner selection fails rather than falling back to another connection.
Standalone legacy planner callers retain their existing interface.

Caller identity is captured before streaming. Planning retains authenticated request
context while restoring the canonical turn and authorizing its model, so a clarification
or replan cannot replace the original model with answer-local controls. Execution clients
are captured before the worker starts. Research receives the captured planner binding,
and direct actions receive the actual answer model identity. Configured agents retain
their own model behavior.

### Completion compatibility and lifecycle

GPT-5-family calls use `max_completion_tokens` rather than `max_tokens` and omit
unsupported temperature. Supported manual reasoning effort is retained for the
selected model; a separate planner keeps its independent defaults. Behavior uses
the underlying model name when available, so a custom deployment alias is supported.

A positive configured model-connection `responseLength` is honored for answer calls. Otherwise,
reasoning completion budgets have an 8192-token floor to leave room for reasoning
and visible output. Planning uses that bounded allowance rather than treating its
smaller visible JSON budget as the entire reasoning budget.

The Anthropic adapter normalizes successful `end_turn` and `stop_sequence`
reasons to the chat-completions `stop` value. Truncation, tool use and refusal
retain their distinct meanings. This lets a valid Claude follow-up pass the
same strict completion checks without accepting a truncated or refused JSON response.

Client bindings close idempotently after completion and failures. A stream closed
before starting allocates no planning client and releases any prepared execution clients;
disconnecting from an active run does not
close a client still in use by its worker.

Empty, refused, filtered and provider-failed answer completions fail the run
explicitly. The stream no longer presents these as completed empty answers.
Provider response text is not included in the new answer-error messages.

### Attribution

The saved assistant message and terminal SSE carry the actual
`model_deployment_name`, provider and available endpoint/model IDs. Only model
identity is exposed, not endpoint addresses or credentials. The existing V2 message
renderer displays the returned deployment name without new browser runtime code.

## Files and impact

| Component | Change |
| --- | --- |
| `functions_orchestration_models.py` | Shared authorized selection, client binding, parameter compatibility and safe identity metadata. |
| `functions_orchestration_context.py` | Retains manual reasoning effort with the model seeds. |
| `functions_orchestration_planner.py` | Accepts the captured binding for resolution, planning and clarification replanning without changing standalone callers. |
| `route_backend_orchestration.py` | Pins answer selection, reauthorizes execution, binds synthesis, closes clients and surfaces failed answers. |
| `functions_orchestration_executor.py`, `functions_orchestration_adapters.py` | Carry the selected planner into research instead of resolving an unrelated legacy client. |
| `functions_orchestration_events.py` | Includes actual answer-model metadata in the terminal stream. |
| `model_endpoint_clients.py` | Normalizes Anthropic completion reasons for chat-completions and Semantic Kernel consumers. |
| `application/single_app/config.py` | Advances the patch version from `0.261.101` to `0.261.102`. |

No new setting, dependency, conversation migration or deployment-configuration
change is required. Previously saved explicit selections are honored when their
pending plans run. Older plans without a model selection resolve the current
configured default. New plans pin the resolved default before approval.

## Validation

The focused orchestration, endpoint authorization, protocol and standalone
planner suites passed **314 tests and 245 subtests** after integrating the current
V2 inline-answer and approval-persistence changes. Coverage includes manual and
default selection, separate planner connections, all approval modes, first and
second questions, unused null clarifications, stale defaults, access revocation,
protocol parameters, native Anthropic completion flags, action/research identity,
canonical models across clarification/replanning, submission-lease cleanup,
approval preferences, token usage and client cleanup.

The local Playwright harness passed **5 tests and 3 subtests** using the shipped
controller, stores and components. It exercises model/clarification transport and
the visible answer-model label in Auto, countdown and manual approval.

A two-turn synthetic replay used the real configured Terra SDK endpoint with the
Flask route and in-memory conversation/run containers. The follow-up resolved the
prior answer successfully; all three model completions used Terra and finished
normally with the configured `2024-05-01-preview` API. No production conversation
or settings records were written, and no deployment was performed.

Primary regressions:

- `functional_tests/test_orchestration_model_selection.py`
- `functional_tests/test_orchestration_conversation_context_routes.py`
- `functional_tests/test_orchestration_conversation_context.py`
- `functional_tests/test_model_endpoint_protocol_inference.py`
- `ui_tests/test_v2_orchestration_conversation_context.py`

These results establish routing and compatibility, not factual accuracy or an
availability guarantee for every configured provider.

### Existing adjacent-test failures

Additional tabular/export-summary checks exposed four failures that also reproduce
against the unchanged **6a34c8a6** baseline. The tabular test requires an exact historical
`0.241.186` application version. Three export-summary tests omit
`build_model_endpoint_identity_headers` from their extracted helper namespace.
These unrelated tests and the export route are unchanged by this fix.

## Related

- [Conversation context fix](ORCHESTRATION_CONVERSATION_CONTEXT_FIX.md)
- [Chat orchestration](../features/CHAT_ORCHESTRATION.md)
- [Orchestration settings](../../admin/orchestration.md)
- [AI Models settings](../../admin/ai-models.md)
