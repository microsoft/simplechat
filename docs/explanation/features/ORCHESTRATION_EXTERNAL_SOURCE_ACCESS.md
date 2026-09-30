# Retained orchestration external source access

**Implemented in version: 0.261.127**, tracked by
`application/single_app/config.py`.
Refs [#1509](https://github.com/microsoft/simplechat/issues/1509).

**Updated in version: 0.261.209.** External-source identity now uses the app
roles of the signed-in session, as classic chat does, instead of reading
Microsoft Graph on every call. Deep research can use its query and link planners
again. See the [session identity fix](../fixes/ORCHESTRATION_SESSION_IDENTITY_FIX.md).

## Purpose and scope

An external Gather result is the content an authorized adapter actually returned,
not a newly invented document or a promise that a remote page is unchanged. This
provider binds the exact retained `structured-v1` value to its producing step,
current conversation audience, and server-owned source configuration. That lets a
later task reuse the same content without running web search, fetching a URL,
invoking an integration, or recalling memory again.

The provider does not enable orchestration by itself. The integrated application
root binds it for web and scheduler execution when Chat Orchestration is enabled.
Execution budgets, output rendering, and current capability checks remain with
their owning services.

## Provider API and dependencies

`application/single_app/functions_orchestration_external_sources.py` exports:

- `CurrentExternalSourceIdentity(user_id, roles, user_enable_agents=False, email=None)`.
- `ExternalSourceConfiguration(identity, revision)`, containing bounded opaque
  configuration tokens, not credentials or fetch URLs.
- `OrchestrationExternalSourceProvider(...)`, scoped to one actor/conversation.

The provider requires these owner-supplied callbacks:

| Callback | Required result and boundary |
| --- | --- |
| `read_identity(*, user_id, conversation_id)` | A new `CurrentExternalSourceIdentity` on every call. The application root supplies `SessionExternalIdentityReader`, which uses the signed-in session's app roles and point-reads conversation ownership and Control Center access on each call. No signed-in session, or no User/Admin role, denies access. |
| `read_settings()` | Current normalized application settings, supplied by their owner. The provider never calls `get_settings()` or imports configuration to rediscover them. |
| `read_conversation(id)` and `read_run(id)` | Current server records used by the existing result-access producer checks. The producer must belong to this actor/conversation and a recorded current-version plan. |
| `read_configuration(source_type, *, producer, settings, source)` | An `ExternalSourceConfiguration` reconstructed from current configuration. `source` is the currently authorized agent/action record, or `None` for web/URL/deep research. Reads after restart must not require a live invocation-capture map. |
| `configuration_admitter(source_type, *, producer, settings, source, selector)` | Required for new non-memory Gather admission. Validates the actual captured invocation configuration against current configuration and returns the captured `ExternalSourceConfiguration`, not a later replacement. Without this callback new admission fails closed; authorized retained reads remain available. |
| `acquisition_validator(source_type, *, producer, settings, source, selector, current_settings, current_source)` | Required by `preflight_gather_acquisition`; returns `None` only after independently supported current metadata agrees with actual acquisition evidence. Bind `attestor.validate_acquisition`. The current settings and exact origin-bearing source come from fresh provider authorization, never the acquisition envelope. Optional for existing auth-only callers and capture-free retained reads. |

Catalog callbacks default to `resolve_agent_catalog` and `resolve_action_catalog`
from `functions_orchestration_context.py`. They must return current authorized
catalogs, not the list saved on a run context. Catalogs are bounded to 4,096 entries.
Membership in a catalog alone is insufficient: the provider also calls
`resolve_delegation_agent` or `resolve_action_manifest` for the exact stored
integration. These existing APIs recheck scope membership, governance, enablement,
and identity without invoking a model or plugin.
An injected action resolver must retain the real `ScopedActionManifest` origin;
matching fields in a plain dictionary are not proof of a scoped authorized read.

The admission callback must use the actual server execution binding. A source
name from plan text is not configuration identity. An agent/action identity must
continue to identify that same configuration rather than a same-name replacement.
For web/deep research, include the configured search provider and applicable review
policy in the server configuration identity/revision. For direct URL review, use
the server review implementation/policy identity, not the page URL. Hash non-opaque
ETags before returning them. Only hashes reach the committed source descriptor;
raw settings, provider endpoints, credentials, and resolver objects do not.

Use a source-specific revision, not a fingerprint of the entire settings document.
An unrelated admin save or new-plan rollout rollback must not look like a changed
source. On admission, the owner must be able to tie this configuration to the
adapter that returned the content; do not substitute a newly configured provider
after execution if the original binding cannot be established.

### Pre-invocation authorization and support

`provider.preflight_gather_invocation(*, producer, selector=None)` remains the
backward-compatible **authorization-only** operation. It returns `None`, creates
no content digest, alias or configuration proof, and does not call configuration
metadata. It is not sufficient to establish supported acquisition.

The root binds this real operation as `external_source_preflight`. External
adapters invoke it before engine/import/logger/budget effects and require an
exact synchronous `None` return. It is not a presence-only readiness flag.
The separate capture callback still performs the stronger combined
authorization/support operation below; entry authorization is not capture proof.

For the root capture callback, use
`provider.preflight_gather_acquisition(source_type, *, producer, settings,
source=None, selector=None)` before capture and effects. This public operation
reuses the same fresh authorization and exact source resolution, then calls the
configured acquisition validator. It returns only `None`, never a permission
snapshot or a reusable authorization token. Missing validators and non-`None`
success-shaped callback returns fail explicitly.

Every call refreshes `read_identity`, application settings, producer/run state,
conversation ownership/audience and current capability policy. Agent/action
calls require the original exact server `catalog_key`/`action_ref`, a fresh
catalog, matching authoritative saved-step selection, and the real exact scoped
resolver. Catalog membership or a same-name replacement is not sufficient.
Known recorded audience changes are refused. Identity service failures and
cancellation propagate distinctly rather than becoming denied or empty results.

The parent composes the acquisition operation into the existing hook, with
`acquisition_validator=attestor.validate_acquisition` on the provider:

```python
def capture_external_source_configuration(
    source_type, *, producer, settings, source=None, selector=None,
):
    provider.preflight_gather_acquisition(
        source_type, producer=producer, settings=settings,
        source=source, selector=selector,
    )
    if source is None and (source_type, producer.capability_id) in (
        ("agent", "agent_invoke"), ("action", "action_invoke"),
    ):
        return
    attestor.capture(
        source_type, producer=producer, settings=settings,
        source=source, selector=selector,
    )
```

For agent/action calls, an early `source=None` event is authorization/support-only
preparation. Emit it before manifest hydration, downstream credential/model
construction or other acquisition effects, using the original server selector.
The root validates current support but does **not** call `attestor.capture` for
that event or create an acquisition binding. The invocation wrapper must count actual
configuration proof separately: an early preparation must never satisfy its
acquired-configuration requirement. Subsequent real engine events run preflight
and actual-versus-current comparison again before capturing the actual configuration.

The public validator is
`attestor.validate_acquisition(source_type, *, producer, settings,
current_settings, source=None, selector=None, current_source=None)`. Production
root code calls it through the provider so it cannot substitute an acquisition
envelope for fresh current authority or duplicate scoped source resolution.
The attestor reuses its existing configuration/component projectors and the
current metadata reader's supported-mode checks; it adds no parallel projector.
Preparation settings, each actual partial component, and any earlier captured
components must match independently reconstructed current metadata.

A supported current Bing definition therefore cannot admit a different actual
Azure AI Search definition, model, endpoint, API version, instructions, controls,
or prepared action manifest. Unsupported current local/resource-dependent,
custom or implicit configurations stop at preparation; differing actual
configuration stops at its pre-invocation capture boundary. No model/tool call,
source-content fetch, or synthetic run is needed for these comparisons.
Definition-stage validation is provisional: the actual observed run still
completes Foundry attestation afterward.

This exception is specific to the two matching integration type/capability
pairs. Do not skip all `source=None` events: URL policy capture is meaningful,
and web/research preparation establishes the attestor's pending components.
The attestor itself still rejects missing agent/action configuration. Preparation
does not replace later actual configuration capture, admission or current reads.

For URL invocations, preflight runs the normal caller-specific URL capability
gate, not the retained-read exception. It uses the same server-owned provenance
as execution: `user_message`, human `edit_user_urls`, accepted
`answered_questions`, and selected, untruncated **user** messages in
`conversation_context` identified by `request_resolution.message_ids`.
It never derives a grant from model-authored plan URLs, assistant text, citations
or a saved result. Missing or malformed provenance fails closed.

This is necessary access preflight, **not** authorization to fetch a particular
URL. The owner must still revalidate conversation history, enforce the existing
exact user-URL grant, transport/SSRF/domain policy, cancellation/lease and
model/token/time/step budgets before effects. It must not cache a successful
preflight or replace later admission/current-read authorization with it.
Agent/action acquisition remains unavailable until its actual internal
configuration proof is also supplied. Fact Memory retains its separate explicit
scope/audience path; this method does not enable or implicitly read it.

### Research planner requests

Before 0.261.209, captured research accepted only deterministic query and link
selection. With the default Knowledge settings, where query planning and LLM
link planning are both on, every orchestrated deep-research acquisition was
refused with `external_configuration_research_profile_unsupported` before it
started. The step then reported "A required retained result is unavailable or
changed."

That restriction is removed. Orchestrated deep research runs the same query
planner and link planner as manual Deep Research, within the existing Knowledge
limits. The research engine calls `capture_research_planner_configuration`
before query planning starts and again before and after every search and page
fetch, so each planner request follows a fresh capture. Through the application
root's `capture` wrapper, every call runs a fresh `preflight_gather_acquisition`
and records `planner` / `resolved` evidence for the model client actually
constructed for the run. A planner request therefore still happens only after
current authorization and the actual planner deployment are attested. The
planner's request controls, a response-token cap and temperature fallbacks,
are fixed in code by `SOURCE_REVIEW_HARD_LIMITS` rather than read from settings.

The research policy projected by `_fetch_policy` includes
`enable_deep_source_review`, `source_review_enable_llm_planning`,
`deep_research_enable_query_planning`, `deep_research_max_search_queries_per_turn`,
and the depth and URL limits. `validate_acquisition` compares that policy from
fresh current settings with the invocation's actual settings at every capture
boundary. If an administrator changes a planner setting while a step runs, the
next boundary raises `external_configuration_changed` before any further
search, page fetch or planner request. Settings, tools and overrides are never
rewritten to fit a profile.

With web discovery, a research result still needs the actual Foundry definition
and run events under the same `deep_research` producer. The existing model,
token, time, step and transport guards are unchanged. Workflow Source Review
remains outside this orchestration capture path.

`functional_tests/test_orchestration_research_pre_effect.py` covers the removed
gate, planner profiles, current/actual mismatch, a change after preparation, and
zero effects on refusal. `functional_tests/test_orchestration_research_capture.py`
asserts that each planner request happens only after its attestation and with
the attested deployment, and that the result is retained and recovered.

### Signed-in session roles

Classic chat authorizes web search and deep research with the app roles in the
user's signed-in session. Since 0.261.209, orchestration does the same. When the
application root builds services for a request, `build_external_identity_reader`
captures the session's `roles` and `preferred_username` while the Flask request
context exists, because execution then continues on a worker thread. The roles
are not saved on the run, and saved `RunContext.user_roles` are never restored.

A role change in Entra ID therefore takes effect when the user's session picks
up new claims, for example at the next sign-in, as it does for classic chat.
There is no per-call directory lookup, and no Microsoft Graph application
permission is needed.

A scheduler continuation, such as recovery after a restart, has no signed-in
session. Its reader has no roles, so every external-source read fails closed
with the refusal code `external_identity_session_unavailable`. The step reports
the `external_session_required` failure, which asks the user to send the request
again. Document-backed and source-free results don't use this reader and are
unaffected.

## Signed-in session identity reader

`application/single_app/functions_orchestration_external_identity.py` provides
`SessionExternalIdentityReader`, the provider's `read_identity` callback.
Construction validates its inputs but performs no I/O, and the module makes no
directory calls.

```python
reader = SessionExternalIdentityReader(
    user_id=user_id,
    conversation_id=conversation_id,
    roles=session_roles,
    email=session_email,
    authorize_conversation=authorize_current_conversation,
    read_user_settings=read_current_user_settings,
    execution_check=check_current_execution,
)

identity = reader(user_id=user_id, conversation_id=conversation_id)
```

Inject `reader` directly as `OrchestrationExternalSourceProvider(read_identity=...)`.
Calling a reader with a different actor or conversation fails with
`external_identity_actor_mismatch` before any callback runs.

### Owner-supplied boundaries

| Argument | Contract |
| --- | --- |
| `roles` | The session's app-role values, captured while a request context exists, or `None` when no signed-in session matches the actor. The bootstrap uses `capture_execution_identity`, which returns roles only when the session's `oid` equals the actor. Values are deduplicated, and entries that aren't bounded identifiers are dropped. |
| `email` | The session's `preferred_username`, or `None`. A value that isn't a bounded identifier, or that contains whitespace, becomes `None`. |
| `authorize_conversation(*, user_id, conversation_id)` | Revalidates the actor's current access and returns the owned server record with matching `id` and `user_id`, not deleted. It must not merely echo caller-supplied IDs. |
| `read_user_settings(user_id)` | A fresh, scoped, read-only document with matching `id` and a dictionary `settings` field. Missing records, failures, malformed data, and wrong actors deny access. |
| `execution_check()` | Optional owning cancellation, lease or budget check. `None` or `True` means continue; `False` raises `ExternalIdentityCancelledError`. Owner control-flow exceptions propagate. |

The application root reads user settings with a Cosmos point read of
`cosmos_user_settings_container`, with 10-second connection and read timeouts
and no retries. Don't use `get_user_settings()` as this callback: it can return a
request-cached document and create or repair records. Don't call
`check_user_access_status()` either: its broad error handler can default to
allow, and expired restrictions can trigger a write.

### Access checks on every call

Each call applies these checks in order and returns a new identity only if all
of them pass:

1. The actor and conversation match the reader, otherwise
   `external_identity_actor_mismatch`.
2. A signed-in session was captured, otherwise
   `external_identity_session_unavailable`.
3. The session holds no more than 64 roles, otherwise the non-retryable service
   error `external_identity_limit_exceeded`.
4. The session holds `User` or `Admin`, otherwise
   `external_identity_role_required`.
5. The conversation is still owned and not deleted, otherwise
   `external_identity_conversation_unavailable`.
6. The user settings document is valid, otherwise
   `external_identity_settings_unavailable`.
7. Control Center access allows the user, otherwise
   `external_identity_access_restricted`.

Non-admins are denied by `settings.access.status="deny"` unless a valid,
timezone-aware `datetime_to_allow` has elapsed. Expiration permits access without
changing the stored restriction. Unknown statuses and malformed restrictions fail
closed. Only `Admin` bypasses this restriction, matching `user_required`; it
doesn't bypass the need for a current settings record. The `enable_agents`
preference remains effective even for admins. Its enabled default applies only
to a valid current document where that optional preference is absent, never to
a failed read.

### Safe failures

| Failure | Parent-facing exception |
| --- | --- |
| No session, no User/Admin role, lost conversation, missing settings, access restriction, or an owner callback's `PermissionError` or HTTP 401/403/404/410 | `ResultUnavailableError` (`PermissionError`) with a safe code. |
| Throttling, HTTP 5xx, network failures, timeouts or HTTP 202 incomplete work in an owner callback | `ExternalIdentityServiceError` with `retryable=True` and a safe `code`. These are service failures, not proof of revoked access. |
| An invalid callback result or more than 64 session roles | `ExternalIdentityServiceError` with `retryable=False`. No authority is returned. |
| Explicit owning cancellation | `ExternalIdentityCancelledError` (`InterruptedError`), distinct from access denial. |

Expected Azure and requests I/O exceptions are translated without preserving raw
provider text or credential-bearing exception chains.

### How a refusal reaches the user

Acquisition capture normalizes an access refusal to
`OrchestrationInvocationDeniedError` with the code `result_unavailable`, keeping
only the refusal's stable code in `authority_reason`. `access_failure` in
`functions_orchestration_schema.py` reads that code, or the refusal's own `code`,
and follows at most three `__cause__` links. Only
`external_identity_session_unavailable` becomes the `external_session_required`
failure; every other refusal stays `result_unavailable`. Exception text is never
read, and the reason code is never shown to the user. Step, saved-wait,
finalization and composition failure events log it as `sc_authority_reason`.

### Invocation failure classification

`ExternalIdentityServiceError` and `ExternalConfigurationServiceError` inherit
the pure `OrchestrationInvocationServiceError` marker from
`functions_orchestration_invocation_capture.py`. Their existing constructors,
validated codes, retryable flags and safe messages are unchanged.
`ExternalIdentityCancelledError` and `ExternalConfigurationCancelledError`
inherit `OrchestrationInvocationCancelledError` and remain `InterruptedError`
subclasses with no-argument constructors.

Metadata helpers also preserve plain `InterruptedError`. At the invocation
boundary, capture normalizes that interruption to
`OrchestrationInvocationCancelledError` without retaining its original type or
private message. Explicit owner cancellation markers still retain their concrete
safe type and code. This does not classify arbitrary code-bearing lease or budget
errors as lifecycle controls; their owner must explicitly adopt the control marker.

These markers let acquisition code distinguish operational failure and
cancellation without importing application owners. Initial and sticky failures
must reconstruct the concrete safe exception from its class and validated code
(or its no-argument cancellation constructor), not retain or rethrow the original
provider exception, traceback, private attributes or exception chain. A tool
loop swallowing the first failure must not allow the invocation to continue as
valid, denied, empty or successful. Runtime recovery must preserve the service
code and retryability; cancellation remains normal cancellation rather than
source denial.

Known access refusals remain distinct: acquisition capture normalizes them to
`OrchestrationInvocationDeniedError`, a `PermissionError` with the safe
`result_unavailable` code and `retryable=False`. Existing document holds retain
the `DocumentHeldError` category through `OrchestrationInvocationHeldError`.
Adapters propagate these categories rather than flattening them into generic
capture-invalid or ordinary failed StepResults. Preflight revocation still
prevents provider/model work and client construction; unavailable SDK run proof
still prevents admission and leaves the owned resources closed.

`functional_tests/test_orchestration_external_error_markers.py` covers all
existing public service codes, both cancellation types, constructor validation,
initial/sticky reconstruction, private exception collection and real
normal/optimized import orders. The marker dependency adds no settings,
directory, SDK or application-bootstrap work.
The invocation-capture tests also cover engine failure and SDK-handler rechecks
without retained exception chains. Research-capture tests exercise plain and
owner-marked cancellation through preparation, planner, definition, run and page
boundaries with actual current metadata and no planner requests.

### Deployment boundary and limitations

The session reader needs no Microsoft Graph permission, admin consent, or
deployer change. Before 0.261.209, a Graph reader made several directory
requests on every external-source call and required the **application**
permission `Directory.Read.All`. Without it, every orchestrated web search, URL
read and deep-research step failed as "A required retained result is
unavailable or changed." Deployments that granted `Directory.Read.All` only for
orchestration can revoke it.

Trusting session roles has the same limits as classic chat. A role removed in
Entra ID still applies until the user's session is refreshed, and a background
continuation can't use external sources because it has no session. Current
source-specific execution-configuration capture is a separate requirement; this
reader doesn't make post-execution current configuration equivalent to the
configuration an adapter actually used.

## Invocation configuration and current metadata

`application/single_app/functions_orchestration_external_configuration.py`
separates two different questions: **what configuration actually produced this
content?** and **is that configuration still current?** A current settings read
after an invocation cannot answer the first question.

```python
attestor = OrchestrationExternalConfigurationAttestor(
    user_id=user_id,
    conversation_id=conversation_id,
    read_current_source=read_current_source_metadata,
    private_digest=keyed_configuration_digest,
    execution_check=check_current_execution,
    max_captures=64,
)
```

Parent wiring uses these exact callbacks:

| Boundary | Callback |
| --- | --- |
| Adapter entry, before engine effects | `external_source_preflight=provider.preflight_gather_invocation` |
| Actual engine acquisition | The `capture` wrapper below: fresh `provider.preflight_gather_acquisition(...)`, then `attestor.capture(...)` except integration preparation |
| Provider pre-effect support | `acquisition_validator=attestor.validate_acquisition` |
| Provider new-Gather admission | `configuration_admitter=attestor.for_admission` |
| Provider retained/current reads | `read_configuration=attestor.current` |
| Original integration selector at retention | `attestor.selector_for(producer)` |

`capture(source_type, *, producer, settings, source=None, selector=None)` returns
no public configuration. `for_admission` takes the same arguments and returns
the captured `ExternalSourceConfiguration` after current comparison.
`current(source_type, *, producer, settings, source=None)` independently
reconstructs current configuration. The provider also compares the admitted
configuration with its current reader before issuing aliases.

`project_external_configuration(source_type, *, settings, source=None,
selector=None, private_digest=None)` is the pure projection entry point. It
hashes source-specific execution configuration, never the full application
settings document. URL policy reuses the real source-review normalization,
including safety clamping, domain aliases and chat-only limits. Workflow-only
limits, unrelated settings, rollout switches and audit fields do not become
configuration revisions.

### Private engine evidence

Non-URL `source` payloads are server-only dictionaries with
`version="orchestration-external-acquisition-v1"`, a `kind`, and a `phase`.
They are never accepted from model output, optional citations or display labels,
and must not be serialized into a public `StepResult`.
Use these exact kind/field names; alternate `action-invocation-v1`,
`agent-invocation-v1` and `foundry-definition-v1` envelopes are not admitted.

| Kind | Required private evidence |
| --- | --- |
| `action` | Exact `reference={id, scope_type, scope_id}`, the real origin-bearing `manifest`, actual `prepared_manifest` supplied to the loader, and actual construction `model` metadata. The outer selector is the original `action_ref`. |
| `agent` | Exact `reference`, actual `resolved_config`, actual `prepared_plugins` and construction `model` metadata for a local agent. The outer selector is the original `catalog_key`. Classic Foundry agents additionally require actual Foundry proof, not a catalog candidate. |
| `planner` | Actual research-client construction `model` metadata. The answer-model selection or a post-invocation settings lookup is not a substitute. |
| `foundry` | Actual resolved `endpoint`, `api_version`, supplied `foundry_settings`, observed `definition`, and actual invocation `overrides`; completed proof supplies either an actual `run` snapshot or the narrowly supported pinned `request` described below. |
| `deep_research` | A complete research projection containing `model` metadata and `web` Foundry evidence when web discovery is enabled. Separate planner and Foundry capture events can build the same configuration without retaining raw evidence. |

Construction `model` metadata contains `provider`, `protocol`, `endpoint`,
`api_version`, `deployment`, `endpoint_id`, `model_id`, and a `parameters`
dictionary of allowlisted controls observed by the owning runtime. Legacy optional IDs can be
empty or null only when genuinely absent. Messages, task text and generated
output are not model configuration.

The direct-action emitter now binds and captures
`parameters={"parallel_tool_calls": False, "tool_choice": "auto"}` before plugin
loading. Current action metadata reconstructs those same explicit runtime
controls. The real SDK-request comparison in
`test_orchestration_action_runtime.py::test_capture_parameters_match_actual_sdk_requests`
verifies the descriptor against both the tool-call request and its continuation
after `FunctionChoiceBehavior.Auto` is attached. This is actual pinned-control
evidence, not a current-only guess or permission to borrow the optional local
loader's different budget/control projection.

The implemented planner proof API is
`planner_client_construction_source(planner_client, planner_model)` in
`functions_orchestration_models.py`. At the research capture boundary, pass the
actual `context.planner_client` and `context.planner_deployment`, not
`context.model_context`, which can describe a different answer model. The getter
returns a fresh private `planner` / `resolved` envelope from the actual
construction record and rejects replaced, mutated, closed or unverifiable
bindings without directory, metadata or provider I/O.

For planner evidence, `parameters` covers only the bound `response_length` and
`reasoning_effort` construction defaults when present. It does not attest
arbitrary later per-call overrides or a remote model definition. The current
metadata reader independently reconstructs the same supported configuration; it
does not call this getter, retain a planner client, or read its capture map.
An envelope that the getter can describe is not automatically a supported
current-read mode: APIM, custom transports and implicit configuration remain
unavailable in the bounded reader.

The default `binding="observed-run-v1"` Foundry projection requires observed `id`, `model`,
`instructions`, `tools`, `tool_resources`, `response_format`, `temperature`
and `top_p`. A run snapshot additionally identifies the actual `id`, `thread_id`
and `agent_id`, and must match the observed definition plus explicit overrides.
Applicable token/tool/truncation overrides must match the actual run as well.
Use `foundry_definition_snapshot(Agent)` and `foundry_run_snapshot(ThreadRun)`
to normalize the real installed SDK models. These helpers do not invent missing
response fields and normalize the wire `assistant_id` to Python `agent_id`.

The phases have distinct authority:

- `resolved` attests an actual resolved/prepared local configuration or bound
  planner construction.
- `definition` is preparation for a Foundry invocation, not proof that this
  definition was executed.
- `run` completes Foundry proof only after comparison with the actual run
  snapshot. Obtain that snapshot before deleting the thread.
- `pinned` completes only the explicit `pinned-request-v1` binding after checking
  the actual fully bound SDK request, not merely the fetched definition.
- `current` is reserved for fresh metadata reads and cannot serve as invocation
  capture evidence.

A web/research adapter's initial `source=None` settings pin is also preparation.
It cannot admit a result by itself. Repeated definitions invalidate completed
Foundry proof until the next matching run or fully pinned request is attested. A changed configuration
or selector during one producer poisons that producer's capture; reverting a
setting later does not overwrite or repair a mixed invocation.

### Classic SDK pinned-request boundary

The classic Semantic Kernel invocation path does not expose `ThreadRun` to the
application. That limitation does not justify inventing a run snapshot or treating
GET-agent as proof of execution. An engine can instead use this one bounded
binding when it demonstrably forwards the complete configuration to the SDK:

```python
source = {
    "version": EXTERNAL_ACQUISITION_VERSION,
    "kind": "foundry",
    "binding": FOUNDRY_PINNED_REQUEST,  # "pinned-request-v1"
    "phase": "pinned",
    "endpoint": actual_endpoint,
    "api_version": actual_api_version,
    "foundry_settings": actual_foundry_settings,
    "definition": foundry_definition_snapshot(
        sdk_definition, binding=FOUNDRY_PINNED_REQUEST,
    ),
    "overrides": actual_configuration_overrides,
    "request": actual_pinned_run_arguments,
}
```

`request` contains `agent_id`, `model`, `instructions`, `tools`, `response_format`,
`temperature`, and `top_p`, plus every applicable explicit token/tool/truncation
option. These must be the actual server-bound arguments, not an expected request
reconstructed from settings after invocation. They must match the definition plus
the explicit overrides. Unrepresented request options are refused. Thread IDs,
messages, generated outputs, transport options and credentials are not this
configuration payload.

Instructions, tools and response format must be nonempty; temperature and top-p
must be explicitly non-null (zero is valid). Nullable or omitted definition fields
can be supplied by actual explicit overrides, but the helper never manufactures
defaults for them. Use the pinned definition normalizer on both acquisition and
current reads; it preserves observed fields without inventing a run or unused
tool-resource field.

Only explicit `bing_grounding` tools qualify, with nonempty
`bing_grounding.search_configurations` containing actual `connection_id` values
and supported `market`, `set_lang`, `count`, or `freshness` parameters. Nonempty
assistant `tool_resources`, file search, code interpreter, function/OpenAPI tools,
custom-search variants and unknown tool configuration remain unavailable.
An engine must refuse unsupported modes before their provider work. It must not
assert that empty/omitted SDK arguments were pinned when the SDK would inherit
live remote state. This proof describes application invocation configuration,
not an unobservable revision of the hosted service or remote documents.

The same binding is included in fresh `phase="current"` metadata, but current
payloads contain neither `request` nor `run`. Retained reads reconstruct the
configuration from current authorized metadata and explicit configuration
overrides without a capture map. Only successful actual Gather execution may
publish retained content after the pre-invocation proof; proof alone is not an
empty-result success. No additional model, tool or provider execution is needed
for attestation.

### Current-read and privacy dependencies

The root supplies
`read_current_source(source_type, *, producer, settings, source, selector)`.
It must return a fresh `phase="current"` payload using the same private shapes,
not a previous run or capture. Its work is limited to authorized metadata:
current scoped agent/action configuration and preparation, configured model
metadata, and current Foundry GET-agent definitions. It must not execute a
model/tool, re-fetch source content, or require a live capture map.

Current classic-Foundry agent payloads include their current `foundry` definition
inside the agent envelope. Current research payloads use
`kind="deep_research"` with current construction configuration and, when enabled,
the current web definition. Current payloads do not contain old run or request snapshots.
Source account, capability, audience and scoped authorization remain mandatory
in the external-source provider.

Non-URL configuration revisions require `private_digest(canonical_bytes)`,
returning a lowercase 64-character SHA-256 HMAC hex digest from an existing
stable backend key supplied by the root. This protects credential-bearing
prepared configuration from guessable public fingerprints while still detecting
relevant credential/configuration changes. The helper never discovers, stores,
or persists that key. The key must remain stable across workers/restarts; key
rotation changes these revisions and requires an owner-managed policy.

Capture maps contain only full producer bindings, opaque configuration tokens,
original selectors and completion state. Raw settings, endpoints, definitions,
credentials and SDK objects are not retained in those maps or result references.
Current reconstruction uses the same projection and digest callback without
reading the capture map. Missing capture prevents a new write, not an otherwise
authorized read of committed content.

### Application metadata reader

The initialized application root can supply the actual current reader from
`application/single_app/functions_orchestration_external_metadata.py`:

```python
read_current_source = build_external_metadata_reader(
    user_id,
    conversation_id,
    read_conversation=read_conversation,
    execution_check=execution_check,
)
```

The returned callback has the exact attestor signature
`read_current_source(source_type, *, producer, settings, source, selector)`.
Construction does not read settings, query Graph, contact a source, or construct
an SDK client. The callback verifies the exact actor, conversation and capability
on the producer, then rechecks live conversation ownership before metadata I/O
and again before returning anything.

This is an application composition helper: the root must have initialized the
real settings/cache and storage dependencies first. It is not a replacement
bootstrap and never repairs missing initialization by importing a route or
creating application storage. Runtime stores, loader preparation and SDK resource
factories are imported only at their authorized operation boundary.

| Source | Independently reconstructed current metadata |
| --- | --- |
| URL | No additional source metadata or SDK work. The attestor continues to project the existing URL policy directly. |
| Web search | One classic Foundry GET-agent using the explicit current endpoint, API version, agent ID and backend authentication configuration. Only explicit Bing grounding or an empty tool list is supported; mutable tool resources and hidden integrations are refused. |
| Direct action | The exact origin-bearing scoped action is resolved again, compared with the provider's current record, and passed through the real action-manifest preparation helper without loading or invoking the plugin. Its explicit Azure model selection is independently resolved and authorized. |
| Classic Foundry agent | The exact scoped agent is resolved again and passed through the actual `resolve_agent_config` function. The full current JSON configuration, current GET-agent definition and the agent's explicit completion-token override form the projection. |
| Deep research | Current model metadata is resolved independently of the captured planner client. Current web metadata is included only when web discovery is enabled. There is no planner request, page fetch or search invocation. |

Readiness requires both acquisition proof and independent current verification.
An additional tool type accepted by the acquisition engine does not expand this
reader's supported modes. In particular, Azure AI Search remains unavailable
until current referenced-resource configuration and authorization can be
verified; an observed tool definition alone is insufficient. Root discovery and
the acquisition boundary must keep such modes unavailable before provider work,
not discover the mismatch only after a result has been produced.
The bounded application reader reconstructs `observed-run-v1`; a separately
available pure pinned-request projection does not enable a pinned fallback.

Action and research model selection uses a strict, conversation-partitioned read
of the owned run. Only model selector fields, selected group IDs and reasoning
effort are used from its seeds. Stored roles, endpoint configurations, client
objects and earlier acquisition evidence are not authority. Named model endpoints
are resolved through the existing `authorize=True` boundary, including current
governance and group membership checks. A saved selector therefore does not grant
continued model access after revocation.

Supported model transports are explicitly configured direct Azure OpenAI
connections: named enabled endpoint/model bindings, explicit legacy deployment
selections, and explicit planner overrides. Model clients are never created for
current reconstruction. APIM, custom/implicit transports, environment-derived
endpoint/API defaults and unnamed action routing in multi-endpoint mode remain
unavailable. The configured planner override is resolved as the planner, not
substituted with the answer-model metadata.

Classic Foundry metadata reads use the real synchronous `AgentsClient.get_agent`
operation, not a get-or-create helper. Connection and read timeouts are 5 and 10
seconds, retries and redirects are disabled, and the reader checks its 30-second
elapsed deadline plus the owner's execution check between operations. Owned SDK
clients and credentials close on success, failure and cancellation. The
existing storage resolvers retain their owning application's transport policy.
Foundry authentication must be explicitly managed identity or service principal;
delegated-user and implicit authentication are not reconstructed in a background
reader. Indirect service-principal secret references and workspace-identity or
indirect-secret action hydration remain unsupported while the legacy hydration
helpers can swallow backend failures.

Every result is `phase="current"` in the existing acquisition envelope. No old
run/request snapshot, live capture map or earlier role snapshot is consulted.
Configuration revisions still come from the attestor and the parent's stable
private HMAC; this reader neither owns that key nor issues retained-source aliases.
Current GET-agent metadata is never treated as proof that an acquisition happened.

Local-agent metadata remains unavailable until the loader-owned full
configuration, actual plugin set and model construction proof can be matched
without inferring hidden core tools or dynamic children. Assigned knowledge,
dynamic child agents/actions, resource-dependent Foundry tools and new
Foundry/workflow protocols likewise remain explicit refusals. These limits do
not change standalone execution or bypass Chat Orchestration readiness.

`functional_tests/test_orchestration_external_metadata.py` exercises the real SDK
GET/deserialization path, actual scoped resolvers and action preparation, actual
model-construction projections, fresh-instance comparisons, ownership and model
revocation, changed definitions, bounded HTTP failures, malformed responses,
cleanup and cancellation. Cold-import probes use real modules with network
access blocked, in normal and optimized Python, for both web and scheduler entry
points. Run the focused suite with:

```powershell
python -B -m pytest -q .\functional_tests\test_orchestration_external_metadata.py
python -B -O -m pytest -q .\functional_tests\test_orchestration_external_metadata.py
```

### Explicit unsupported proof cases

Missing SDK definition/run fields, unavailable actual planner construction
metadata, unobserved prepared plugin configuration, and unsupported invocation
overrides remain unavailable rather than acquiring a manufactured revision.
New Foundry application/workflow protocols are not covered by either classic
binding and remain unsupported by this projection. A model name in an HTTP
response is not a trustworthy application definition or version.

Arbitrary dynamically selected child integrations cannot be recovered from an
opaque root configuration digest after restart. Non-empty dynamic `dependencies`
payloads and a changed root selector are therefore refused. Do not retain a
root-only proof after acquiring data from an unattested child. Supporting such
children requires a separately reviewed, durable, authorized dependency identity
contract; this helper does not add a storage container or reinterpret existing
external references.

`ExternalConfigurationServiceError` exposes a validated `code` and `retryable`
flag. Metadata timeouts, network failures, 429 and 5xx are service failures, not
source denial. Malformed metadata, callback contracts and limits are
non-retryable verification failures. Known access denial, configuration
replacement, incomplete invocation proof and unsupported acquisition cases use
`ResultUnavailableError`. These categories must remain distinct in parent
delivery/recovery handling.

An obsolete or malformed pre-invocation private envelope raises
`ExternalConfigurationServiceError("external_configuration_metadata_invalid")`
with `retryable=False` before a provider run. Capture/adapters preserve that
typed verification failure; they must not flatten it into a denied, empty or
ordinary failed StepResult merely because the envelope is invalid.

The optional execution check returns `None` or exact `True`, or raises the
owner's lease/budget/cancellation exception. Exact `False` raises
`ExternalConfigurationCancelledError` (`InterruptedError`), not a source-denial
error. Lease exceptions and cancellation raised by the metadata owner propagate;
the helper does not convert them into a successful or empty configuration.

## Gather admission and retained reads

### Verified root injection boundary

The engine/helper integration uses **one**
`orchestration-external-acquisition-v1` envelope. There is no compatibility
translator for the earlier private `*-invocation-v1` or
`foundry-definition-v1` shapes. Actual URL and classic Foundry acquisition, and
multi-call action execution, are exercised against the real attestor/provider
rather than a callback that merely accepts a dictionary.

The constructor and callback signatures for root injection are:

```python
read_current_source = build_external_metadata_reader(
    user_id,
    conversation_id,
    read_conversation=read_conversation,
    execution_check=execution_check,
)
attestor = OrchestrationExternalConfigurationAttestor(
    user_id=user_id,
    conversation_id=conversation_id,
    read_current_source=read_current_source,
    private_digest=private_external_configuration_digest,
    execution_check=execution_check,
)
provider = OrchestrationExternalSourceProvider(
    user_id=user_id,
    conversation_id=conversation_id,
    read_identity=read_identity,
    read_settings=read_settings,
    read_conversation=read_conversation,
    read_run=read_run,
    read_configuration=attestor.current,
    configuration_admitter=attestor.for_admission,
    acquisition_validator=attestor.validate_acquisition,
)

def capture(source_type, *, producer, settings, source=None, selector=None):
    provider.preflight_gather_acquisition(
        source_type, producer=producer, settings=settings,
        source=source, selector=selector,
    )
    if source is None and (source_type, producer.capability_id) in (
        ("agent", "agent_invoke"), ("action", "action_invoke"),
    ):
        return
    attestor.capture(
        source_type, producer=producer, settings=settings,
        source=source, selector=selector,
    )

def admit(*, producer, prepared):
    return provider.admit_gather_result(
        producer=producer, prepared=prepared,
        selector=attestor.selector_for(producer),
    )
```

Bind `capture` to `capture_external_source_configuration`, `admit` to
`external_source_admission`, and `provider.authorize` to the result facade's
`external_source_authorizer`. Bind `provider.preflight_gather_invocation` to
`external_source_preflight`. These are the **four** required runtime
callbacks. Entry preflight performs current authorization, while independent
fresh pre-effect authorization and current/actual support checks
execute inside `capture`, including its initial `source=None` preparation;
retention-time admission is not a substitute. No callback is a no-op readiness
binding. Missing callbacks still withhold discovery/execution.
These server callbacks remain private and
actor/conversation-bound. Construction does not itself grant authority or
enable a capability. Do not bind bare `attestor.capture`, or replace the new
operation with auth-only preflight: both would omit supported current metadata
comparison before effects. The metadata factory's cancellation keyword remains
`execution_check`, not `cancel_requested` or `cancellation_check`; the callback
takes no arguments, and exact `False` raises the typed configuration cancellation.

For the actual classic SDK observer path, a valid capture sequence is built from
the objects already used/returned by that invocation:

```python
definition_event = {
    "version": EXTERNAL_ACQUISITION_VERSION,
    "kind": "foundry",
    "binding": FOUNDRY_OBSERVED_RUN,
    "phase": "definition",
    "endpoint": actual_endpoint,
    "api_version": actual_api_version,
    "foundry_settings": actual_foundry_settings,
    "definition": foundry_definition_snapshot(actual_sdk_definition),
    "overrides": actual_run_controls,
}
capture("web", producer=producer, settings=invocation_settings, source=definition_event)

# Observe the existing owned-client operation's response; do not create another run.
run_event = {
    **definition_event,
    "phase": "run",
    "run": foundry_run_snapshot(actual_returned_thread_run),
}
capture("web", producer=producer, settings=invocation_settings, source=run_event)
```

The definition event is provisional. Only a matching real run completes this
binding. SDK fields missing from the raw response stay missing and make the proof
unavailable; an SDK property declaration is not evidence that a particular
response included it. The observer does not add provider/model calls.

On restart, the facade restores committed external references from lineage.
Create a fresh provider/attestor with an empty admission catalog and inject
`provider.authorize`; do not recreate invocation captures. Its current metadata
callback is
`read_current_source(source_type, *, producer, settings, source, selector)`.
For integrations, the provider first reconstructs selection from a **fresh
authorized catalog** and exact scoped resolver, not from an old run catalog.
Current metadata is independently projected using the same configuration schema
and stable digest key. It must not depend on a saved run response, live capture
map, source-content refetch or model/tool execution.

The focused integration command is:

```powershell
python -B -m pytest -q --disable-warnings `
  .\functional_tests\test_orchestration_external_capture_integration.py `
  .\functional_tests\test_orchestration_external_configuration_capture.py::test_actual_sdk_builds_run_options_from_captured_definition `
  .\functional_tests\test_orchestration_external_configuration_capture.py::test_real_sk_observes_sdk_runs_and_cleans_owned_thread
```

It combines the actual acquisition hooks with preflight, opaque capture,
admission, central retention, live copied-catalog installation, receipt recovery
and capture-free current authorization. Page/provider/model responses and storage
I/O are doubled; no tenant is contacted or permission granted. This bounded
proof does not enable unresolved local attached-plugin/knowledge graphs,
LLM research request-override profiles, unsupported SDK modes, or broken
service-error/cancellation propagation.

`functional_tests/test_orchestration_external_pre_effect.py` covers the additional
pre-effect boundary using the real current metadata reader, exact scoped
resolvers, actual Azure constructors, and real capture/admission hooks, with
external SDK/store I/O doubled. It verifies:

- Unsupported or changed current configuration and a supported current definition
  paired with different actual tools/model/endpoint/controls cause zero paid
  calls. Actual action construction/preparation drift blocks plugin loading,
  model requests and tool execution, and closes the constructed client.
- The engine's stricter non-Bing/resource rejection can precede the definition
  callback. Tests separately verify its zero-effect failed result and the
  provider guard's independent rejection of those actual definition components;
  they do not mistake the earlier refusal for a successful guard call.
- Actual planner construction defaults are compared before a request; changed
  earlier agent components cannot be replaced by a matching later Foundry event.
  A forged acquisition envelope cannot bypass fresh source authorization.
- A definition alone creates no completed proof; supported definition, actual
  observed run, admission and capture-free restart still work.
- Identity/configuration outages, malformed metadata and cancellation retain
  their typed meaning, distinct from genuine denial. Authorization-only defaults
  remain unchanged; missing/invalid validators fail rather than reporting success.

Run the same boundary in normal and optimized Python:

```powershell
Set-Location .\functional_tests
python -B -m pytest --rootdir=. --confcutdir=. -q --disable-warnings `
  .\test_orchestration_external_pre_effect.py `
  .\test_orchestration_external_capture_integration.py
python -B -O -m pytest --rootdir=. --confcutdir=. -q --disable-warnings `
  .\test_orchestration_external_pre_effect.py `
  .\test_orchestration_external_capture_integration.py
```

Current metadata GETs are bounded support checks, not source-content acquisition
or execution proof. They do not widen supported modes, grant roles/permissions,
or relax the owner's URL, cancellation, lease, token, time or step guards.

### Admission and registration

Call:

```python
catalog = provider.admit_gather_result(
    producer=producer,
    prepared=prepared,
    selector=selected_catalog_key_or_action_ref,
)
```

`prepared` must be the exact `orchestration-gathered-content-v1` dictionary that
M4 persists as its `prepared` / `structured-v1` output. For agent/action work,
`selector` is the original **server-selected** `catalog_key` / `action_ref`, not a
display name or browser-supplied reference. The selection is matched against the
fresh catalog, exact resolver, and approved producing step. Web, URL, and deep
research do not take a selector.

Install the returned `{alias: frozen ExternalSourceRef}` mapping in
`OrchestrationResultAccess.external_source_catalog`, pass its alias names to
`persist_task_result(external_sources=...)`, and inject `provider.authorize` as
`external_source_authorizer`. The result facade copies the constructor catalog;
adding a later admission to a different dictionary does not update that copy.
The integration owner must install newly admitted bindings before persistence.
Use external-only lineage with `origin="grounded"` and `sources=[]`, not fabricated
document IDs or external entries in the document-only evidence/source-set kinds.

The descriptor's SHA-256 covers the canonical bytes of the complete retained
value. Its opaque reference binds that digest to the producer and exact source.
Its `configuration:` revision is a server configuration fingerprint, **not a
remote-document revision**. A configuration identity replacement denies reuse;
a changed revision is reported to the result facade's existing snapshot policy.

After restart, no admission catalog is needed for reads. The result facade
restores the committed binding and calls:

```python
current = provider.authorize(
    reference,
    producer=producer,
    user_id=user_id,
    conversation_id=conversation_id,
)
```

The return is a current, exact-identity `ExternalSourceRef`, never a success
boolean or dictionary. Role, capability selection, integration governance,
membership, and conversation audience are checked again. The retained content
digest stays tied to the immutable saved content; the provider does not fetch a
page to invent a current remote digest. In particular, a saved public URL or
citation does not authorize a new fetch.

The same boundary applies to optional committed-result receipts. A caller that
passes its server-computed `input_fingerprint` to `persist_task_result()` can use
`recover_task_result(producer=..., input_fingerprint=...)` after a crash between
result commitment and checkpoint publication. Recovery rechecks the committed
external bindings with `provider.authorize`, without a live admission catalog or
another Gather invocation. A receipt does not bypass current roles, scoped
membership, or source configuration revisions, and does not change the public
`TaskResult` wire contract.

Existing capability permissions are reused independently of plan creation.
Removing the retired orchestration-contract setting does not revoke saved
results; ordinary capability/access revocation still does.

## Explicit saved-memory use

`admit_memory_result(producer=..., prepared=...)` is a separate explicit operation.
It requires the producing run's server-recorded `memory_scope` and
`memory_audience`, the current Fact Memory capability, and the real
`validate_memory_context` checks. User scope must belong to the actor. Group scope
requires current group membership and enabled group workspaces.

Shared/hidden collaboration audiences are refused for saved-memory use, including
when a formerly private conversation changes audience. No memory search, embedding,
backfill, autosave, global recall, or inference of a scope from a browser selection
occurs. Only the explicitly supplied retained value is attested.

## Validation and limitations

`functional_tests/test_orchestration_external_sources.py` exercises the real
contracts, retained-result store/readers, capability context, exact integration
resolvers, and memory audience validation with external identity/storage seams
doubled. Coverage includes live reads, catalog-free restarts, fresh normal and
optimized Python processes, role/capability/governance/membership revocation,
configuration replacement, audience changes, disabled integrations, forged
producer bindings, and secret-free descriptors. Network access and implicit
memory recall are prohibited in the tests. Late admission exercises the live
access catalog rather than its copied constructor input. Optional receipt tests
cover all external source types, crash-after-commit recovery, and current-role
revocation in fresh normal and optimized Python processes.

`functional_tests/test_orchestration_external_identity.py` exercises the real
session reader with only the owner callbacks doubled and networking blocked. It
covers session role validation and bounds, the missing-session refusal, the
User/Admin requirement, actor and conversation binding, per-call conversation and
Control Center rereads, read-only restriction expiration, the Admin bypass,
settings that never default to allow, safe I/O error categories and cancellation.
Fresh normal and optimized Python processes import the real module without
settings, authentication, route or credential modules. No test contacts a tenant.
`functional_tests/test_orchestration_external_bootstrap.py` checks that the root
captures session roles only inside a request context and makes no Graph calls.

`functional_tests/test_orchestration_external_configuration.py` covers actual URL
policy normalization, source-specific projections, keyed opaque revisions,
definition/run comparisons using real SDK model objects, sticky re-resolution
failures, planner and scoped integration proof, metadata error categories, real
retained-result persistence, and current reconstruction after restart with no
capture map. Fresh normal/optimized imports prohibit network and client/credential
construction. `test_orchestration_external_root_runtime.py` additionally exercises
the actual root, authorized URL acquisition, retained result, JSON Render,
restart/history/download, and fresh revocation without reacquisition. The
pre-effect/capture suites exercise actual engine ordering and original-claim
checks on entry, capture and admission.

This provider attests returned excerpts/findings, not whole-page completeness or
ongoing remote freshness. It adds no service or storage container. Current identity
and configuration callbacks are required production dependencies, not optional
readiness flags.
