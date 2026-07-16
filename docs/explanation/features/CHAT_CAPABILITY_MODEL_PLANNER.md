# Chat Capability Model Planner

Implemented in version: **0.250.069**

Hardened in version: **0.250.071**

Associated issue: **[#1021](https://github.com/microsoft/simplechat/issues/1021)**

## Overview

The chat capability model planner is a bounded, non-executing planning layer for
SimpleChat orchestration. It evaluates the current user request against the
server-authorized capability inventory and returns a strict `direct`, `propose`,
or `clarify` result.

Phase 10A ships only `off` and `shadow` modes. Shadow results are measured but
cannot change a recommendation, toolbar state, capability choice, runtime plan,
finalizer, response, or external query.

## Dependencies

- Existing authenticated streaming chat route and conversation authorization.
- Phase 8A built-in capability inventory and deterministic recommendation.
- Phase 8B governed-agent safe descriptors and opaque references.
- Existing chat model resolution and global admin model-endpoint governance.
- Phase 9 privacy-safe orchestration evaluation events and quality-gate runner.

## Architecture

The streaming path performs these operations in order:

1. Authorize the user, conversation, active scopes, selected controls, and input readiness.
2. Resolve the chat model through existing endpoint governance.
3. Build the safe capability inventory and deterministic control recommendation.
4. When eligible, invoke and validate the non-executing shadow planner.
5. Compare safe planner classes with the deterministic control.
6. Build and persist the unchanged deterministic orchestration plan.
7. Continue through the existing proposal, runtime, evidence, and finalization paths.

The planner is a normal synchronous chat-completion call. It does not initialize
Semantic Kernel, expose plugins, provide tools, enable automatic function
selection, or create an execution route.

## Request Contract

The version 1 request contains:

- The current user request, bounded to 16,000 characters.
- Selected capability IDs marked as required mandates.
- At most 64 safe available built-in and governed-agent descriptors.
- Server-owned candidate and per-plan limits.
- Literal policy flags stating that the planner cannot execute or grant access.

Built-in descriptors contain only server-known planning classes such as state,
category, discoverability, read-only status, external-data status, risk,
latency, cost, evidence types, input readiness, and choice requirements.
Governed agents additionally use an opaque reference, bounded display label,
safe scope/sensitivity classes, capability tags, and evidence types.

Unavailable, unauthorized, policy-blocked, hidden, inaccessible, or non-input-
ready entries do not enter the request. Canonical agent, group, document,
conversation, user, endpoint, action, and connector IDs remain server-only.
Instructions, prompts, tool schemas, assigned knowledge, evidence, citations,
artifacts, secrets, and inaccessible counts are forbidden.

## Result Validation

The version 1 result schema permits only:

- `version`
- `decision`
- `requirements`
- `candidate_plans`
- `recommended_plan_id`
- `clarification_code`

Requirements and candidates have fixed nested fields and use allowlisted reason,
evidence, and confidence classes. Validation rejects malformed JSON, missing or
unknown fields, unsupported versions, unknown IDs, unavailable entries,
selected-only proposals, over-budget collections, invalid decision shapes, and
recommendations that do not identify a validated candidate.

The structured-output schema is rebuilt from each safe planner request. It
enumerates only `requirement_1` through `requirement_8`, candidate aliases within
the current policy budget, exact eligible unselected capability IDs, and exact
safe evidence types. Selected mandates remain visible as required context but
are excluded from candidate additions. When no eligible addition exists,
`propose` is removed from the decision enum and candidate plans are bounded to
zero. The same request-specific schema is sent in both the prompt and provider
`response_format`.

Selected mandates are restored from the request rather than trusted from model
output. Candidate members and equivalent candidate sets are deduplicated.
Duplicate candidates cannot create a second execution option, and no validation
repair can turn an unknown ID into a known capability.

## Provider And Timeout Behavior

The default model source is `same_as_chat`. `configured` mode accepts only a
server-saved global endpoint ID and model ID and resolves them through current
global endpoint and item governance. A personal or group endpoint with the same
ID cannot shadow the configured planner. Missing, disabled, inaccessible, or
unsupported configured models do not fall back to browser input or another
model.

Azure OpenAI and compatible OpenAI providers prefer strict JSON schema and use a
bounded list of fallbacks only when the active optional request parameter is
explicitly unsupported. Anthropic-compatible providers receive the exact result
schema in a JSON-only prompt. SDK retries are disabled, and arbitrary model,
network, quota, or service failures are not retried.

Every call passes its remaining deadline to the provider request itself. The
default is 5,000 milliseconds, persisted values are clamped from 250 to 10,000
milliseconds, all compatibility variants share that one wall-clock budget, and
the Anthropic HTTP adapter splits the same bound across connect and read time in
`requests.post`. Timeout, empty or malformed provider output, invalid JSON,
refusal, content filtering, client failure, and cancellation all produce compact
failure states while deterministic chat continues unchanged.

## Configuration

Backend settings and defaults are:

```json
{
  "chat_capability_planner_mode": "off",
  "chat_capability_planner_timeout_ms": 5000,
  "chat_capability_planner_max_completion_tokens": 600,
  "chat_capability_planner_max_candidate_plans": 3,
  "chat_capability_planner_max_capabilities_per_plan": 4,
  "chat_capability_planner_model_source": "same_as_chat",
  "chat_capability_planner_model_endpoint_id": "",
  "chat_capability_planner_model_id": ""
}
```

Phase 10A does not expose an Admin UI control. Planner settings are removed from
ordinary sanitized frontend settings. Administrators may set them through the
existing backend configuration store in controlled environments.

## Privacy And Observability

Persisted `capability_planner_shadow` metadata contains only bounded status,
decision, candidate count, safe capability classes, allowlisted reason codes,
latency, fallback state, and failure code. It is stored only on the source user
turn and never on a proposal as executable state.

Evaluation emits fixed events:

- `orchestration_planner_completed`
- `orchestration_planner_rejected`
- `orchestration_planner_timed_out`
- `orchestration_planner_shadow_compared`

Events hash run correlation, bucket provider/model classes, and omit raw model
or user content. Opaque agent references become `governed_agent`; unknown
classes are dropped.

## Testing And Validation

`functional_tests/test_chat_capability_model_planner.py` covers request/result
contracts, provider variants, disabled SDK retries, shared transport deadlines,
strict failures, cancellation, metadata privacy, configuration, all 139
deterministic evaluation rows, and the required archive, additive, direct,
selected-mandate, clarify, and governed-agent scenarios.

`functional_tests/test_chat_capability_planner_route.py` verifies route ordering,
off/resume/cancellation gates, server-owned model selection, deterministic
control isolation, and user-turn-only shadow metadata.

`functional_tests/test_phase10a_controlled_shadow_runner.py` validates the
realistic controlled manifest, unavailable and input-not-ready filtering,
additive scoring, explicit acceptance thresholds, and privacy-safe result
artifacts. The manifest covers direct, public archive, named public source,
workspace, selected-plus-additive, selected-mandate, governed-agent,
clarification, prompt-injection, unavailable, unauthorized, and policy-blocked
behavior.

Run the combined deterministic gate with:

```powershell
.\.venv\Scripts\python.exe scripts\run_phase9_orchestration_quality_gates.py
```

No live or billable planner call is required by the test suite.

After deterministic gates pass, run the opt-in controlled live matrix with a
known test deployment:

```powershell
.\.venv\Scripts\python.exe scripts\run_phase10a_controlled_shadow.py `
  --auth azure_cli `
  --repetitions 3
```

The command never executes a capability. It writes bounded decisions,
capability classes, reason codes, failure codes, and latency aggregates to
`artifacts/phase10a_controlled_shadow_report.json`. Prompts, raw responses,
deployment names, endpoint hosts, credentials, canonical IDs, and evidence are
not persisted. Version 0.250.071 was accepted against the controlled
`gpt-5.6-terra` deployment with 57 of 57 end-to-end samples, 100% semantic
accuracy and strict JSON-schema use in every category, zero timeouts,
operational failures, invalid outputs, false proposals, capability leakage, or
prohibited execution-surface imports, and p50/p95 latency of 1.67/2.65 seconds.

## Known Limitations

- Shadow output is observational and cannot create a choice or clarification UI.
- Only the current user request is available; prior-turn goal resolution is deferred to Phase 10C.
- Phase 10A does not activate additive plans or expand bundles into executable options.
- Consequential, write, sensitive, or over-budget approval remains outside this phase.
- Generalized document, presentation, data, export, and workflow finalizers remain Phase 11 work.