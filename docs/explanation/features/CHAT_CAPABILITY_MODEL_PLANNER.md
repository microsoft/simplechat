# Chat Capability Model Planner

Implemented in version: **0.250.069**

Hardened in version: **0.250.071**

Governed activation implemented in version: **0.250.072**

Admin configuration guidance enhanced in version: **0.250.073**

Choice-card experience enhanced in version: **0.250.074**

Associated issue: **[#1021](https://github.com/microsoft/simplechat/issues/1021)**

## Overview

The chat capability model planner is a bounded planning layer for SimpleChat
orchestration. It evaluates the current user request against the
server-authorized capability inventory and returns a strict `direct`, `propose`,
or `clarify` result. The model never receives execution authority.

Phase 10A introduced `off` and observational `shadow` modes. Phase 10B adds a
conservative `assist` mode: a validated high-confidence `propose` result may
become one durable server-authored choice card. The existing deterministic
recommendation wins material conflicts, and planner failure always falls back
to deterministic or direct behavior. `clarify` remains observational until
Phase 10C.

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
4. When eligible, invoke and strictly validate the planner.
5. In `shadow`, compare safe planner classes with the unchanged deterministic control.
6. In `assist`, materialize high-confidence candidates from the current server inventory and arbitrate them against the deterministic recommendation.
7. Persist at most one recommendation through the existing capability proposal contract, or continue directly when no material valid proposal remains.
8. Recursively expand selected, automatic, and approved bundles, then reauthorize every effective member at decision, resume, and immediately before child-run execution.
9. Continue through the existing runtime, evidence-ledger, and central-finalization paths.

The planner is a normal synchronous chat-completion call. It does not initialize
Semantic Kernel, expose plugins, provide tools, enable automatic function
selection, or create an execution route.

## Governed Additive Activation

`assist` activation accepts only a valid `propose` result whose recommended
candidate has `high` confidence. Built-in candidates must remain read-only,
authorized, available, discoverable, input-ready, and approval-eligible.
Governed-agent candidates must resolve to a current Phase 8B opaque read-only
descriptor. Mixed agent/built-in options, write capabilities, unknown IDs,
cyclic bundles, missing members, and over-budget plans fail closed.

The server, not the model, owns option IDs, labels, risk, sensitivity, latency,
cost, external-data state, and approval requirements. Built-in option IDs use a
stable opaque `plan:` digest bound to sorted approved IDs, recursively expanded
effective IDs, inventory version, and safe policy state. The same binding is
recomputed from a fresh inventory before execution.

The additive fields have distinct meanings:

- `capability_ids` contains only unselected additions approved by the option.
- `effective_capability_ids` contains those additions plus current server-owned bundle dependencies.
- Submitted selections and their inherited dependencies remain in the immutable selection snapshot with origin `selection`.
- Policy-approved automatic discovery stores bounded server-authored root IDs and its exact effective closure in provenance v2; independently auto-approved dependencies retain origin `discovery_auto`, selected dependencies retain `selection`, and neither is requested for approval again.
- Only newly approved additions use origin `discovery_approved`.

Deep Research expands to Deep Research plus Web Search. An explicit Deep
Research plus Web Search candidate collapses to that same plan. Workspace
Search plus Web Search may appear as one option when both are true additions;
if Workspace Search was submitted or automatically discovered, the option is
instead labeled `Add Web Search`. A card contains one recommendation, at most
two alternatives, and one Continue option, including after sensitive-input
variants are added.

Compatibility execution remains conservative. Image cannot be combined with
another built-in or selected/approved agent mandate, and Analyze or Compare
cannot be combined with retrieval until those compatibility executors can
satisfy the complete union. Such options are suppressed before display and
rejected again during durable decision, resume, and pre-execution validation.
Automatic roots and their effective closure are persisted separately. A fresh
closure must exactly match the persisted `discovery_auto` members, so a bundle
member added, removed, or replaced after proposal creation invalidates the
proposal with `capability_bundle_changed` instead of changing execution.
Rootless legacy state remains compatible only when one unchanged unbundled
automatic capability can be reconstructed; ambiguous multi-member state fails
closed.

Resume execution context is never accepted from browser JSON or embedded back
into reconstructed request data. HTTP chat and document-action boundaries strip
underscore-prefixed server fields recursively, including nested agent fields,
while authorized resume claims pass their context through a separate internal
parameter. Browser decisions remain limited to conversation, proposal, and
persisted option IDs.

Native streaming owns one terminalization guard for each claimed resume lease.
Normal, partial, and terminal safety output persist exact resume correlation
and complete the claim; setup failure, cancellation, and any other no-output
exit release it for retry. Safety messages from native and compatibility paths
carry the same bounded correlation as assistant and image output and
participate in process-loss reconciliation. Exact-owner guards cover both
post-claim reauthorization and route setup before background-worker handoff, so
a failed setup cannot strand the lease or release a newer execution.
Cancellation partials and document-action results produced before runtime
reconciliation failure are persisted as incomplete correlated assistant output
and complete the exact execution. Cancellation or reconciliation paths reopen
the lease only when they produced no durable output.
Once correlated output is durable, it remains authoritative even if the
proposal completion write transiently fails. Wrappers do not downgrade that
execution to retryable failure, and restart reconciliation may complete the
same exact running or failed execution without accepting a newer claim.

Deterministic recommendations use the same recursive baseline semantics as
planner options. Selected bundle dependencies are treated as already effective
and cannot be offered again. Deterministic built-in options are rebound to the
fresh recursive closure and safe policy fields at decision and resume, so a
bundle member added, removed, or replaced invalidates the stored option.
Streaming, non-streaming, and document-action provenance all record the same
expanded selected closure while preserving only explicit roots in the immutable
selection snapshot.

Material arbitration is deliberately conservative. A planner plan may augment
the deterministic recommendation only when it contains the deterministic
plan's effective capability set. If it omits or conflicts with that material
source, the deterministic recommendation remains authoritative. Low confidence,
invalid output, timeout, refusal, filtering, provider failure, materialization
failure, or persistence failure grants no new capability.

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
  "chat_capability_planner_mode": "assist",
  "chat_capability_planner_timeout_ms": 10000,
  "chat_capability_planner_max_completion_tokens": 600,
  "chat_capability_planner_max_candidate_plans": 3,
  "chat_capability_planner_max_capabilities_per_plan": 4,
  "chat_capability_planner_model_source": "same_as_chat",
  "chat_capability_planner_model_endpoint_id": "",
  "chat_capability_planner_model_id": ""
}
```

Admin Settings exposes `Off`, `Shadow`, and `Assist` modes plus model source,
global endpoint/model IDs, timeout, completion budget, candidate count, and
per-plan capability limits. Server normalization accepts only
`off | shadow | assist`, clamps every numeric value to the documented bounds,
and forces incomplete configured-model selections back to `off`. The shipped
default is `assist`; administrators may select `off` as a kill switch or return
to `shadow` without altering already persisted proposals awaiting a decision.

The Admin panel defines each mode and setting through visible descriptions and
keyboard-accessible information tooltips:

- `Assist` is the recommended operating mode. Eligible new turns call the
  planner, and validated high-confidence additions appear as approval choices.
- `Shadow` calls and evaluates the planner but does not change the answer path,
  display proposals, or execute suggested capabilities.
- `Off` skips the planner model call entirely.
- `Same as selected chat model` plans with the model selected for each turn.
  `Configured global model` instead requires the internal global endpoint ID
  and model ID from the Admin model-endpoint catalog; these values are not URLs,
  deployment labels, candidate plans, or capability IDs.
- Planner timeout uses a 1-20 second slider with 10 seconds recommended.
- Completion budget uses a 64-1200 token slider with 600 recommended. It limits
  only the compact planner JSON, not the final response or tool output.
- Candidate plans is a 1-6 option set with 3 recommended.
- Capabilities per plan uses a 1-8 slider with 4 recommended. Selected mandates
  and server-expanded dependencies remain governed separately.

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

In `assist`, the source user turn stores a separate bounded
`capability_planner_activation` summary with materialized/suppressed status,
planner-versus-deterministic source, and an allowlisted suppression reason. It
does not store planner rationale, prompt, response, option labels, opaque agent
references, object IDs, or authorization claims.

Phase 10B additionally emits fixed activation and recommendation-revalidation
events. Capability combinations use a small allowlist such as
`web_search+workspace_search` or `deep_research+web_search`; other combinations
collapse to fixed buckets. Decision, resume, and execution revalidation events
contain only hashed correlation, fixed phase/status/reason classes, safe
capability count/combination, and recommendation source. Existing recommendation
events provide approval/decline, latency, downstream run status, and citation
yield without raw IDs or content.

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

`functional_tests/test_phase10b_governed_additive_plan_activation.py` validates
assist normalization and eligibility, high-confidence activation, deterministic
conflict precedence, Workspace plus Web and selected/automatic additive cases,
Deep Research expansion, deterministic and planner selected/automatic bundle
subtraction, root-to-closure drift, deterministic option rebinding, dependency
policy drift, equivalent-plan collapse, governed agents, Image/agent exclusion,
unknown/revoked/write/cyclic/input/policy failures, opaque plan binding,
sensitive current-turn options, actionable-option limits, origin separation,
admin controls, and privacy-safe activation/revalidation events.

The existing choice contract, persistence, authenticated route, orchestration,
and Phase 9 observability suites validate exact source-turn ownership, ETag
decisions, duplicate resume protection, process-loss reconciliation, bundle
revocation, current-turn-only external queries, child-run provenance, and
downstream outcome metrics. Desktop/mobile Azure Playwright coverage validates
equal-width plan cards, the corner recommendation ribbon, concise descriptions,
multi-capability Includes checklists, selected context, inert text rendering,
keyboard use, 44-pixel controls, immediate decision/resume, no overflow, and a
single server-authored option ID per browser decision. Live browser cases
remain explicitly environment-gated.

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

- `shadow` remains observational; only `assist` can materialize a proposal.
- `clarify` is still observational and cannot create a conversational checkpoint until Phase 10C.
- Only the current user request is available. Prior-turn goal resolution and prior-user-text external queries are deferred to Phase 10C.
- Planner activation is limited to read-only built-ins and Phase 8B governed agents. Consequential, write, action-attached, sensitive-by-policy, and over-budget tools remain prohibited.
- Generalized document, presentation, data, export, and workflow finalizers remain Phase 11 work.