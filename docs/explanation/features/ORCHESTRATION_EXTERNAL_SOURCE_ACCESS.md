# Retained orchestration external source access

**Implemented in version: 0.261.127**, tracked by
`application/single_app/config.py`.
Refs [#1509](https://github.com/microsoft/simplechat/issues/1509).

## Purpose and scope

An external Gather result is the content an authorized adapter actually returned,
not a newly invented document or a promise that a remote page is unchanged. This
provider binds the exact retained `structured-v1` value to its producing step,
current conversation audience, and server-owned source configuration. That lets a
later task reuse the same content without running web search, fetching a URL,
invoking an integration, or recalling memory again.

The provider does not enable the harness by itself. The integrated application
root binds it for web and scheduler execution; new-plan admission still requires
the default-off orchestration and harness-preview settings. Execution budgets,
output rendering, and current capability checks remain with their owning services.

## Provider API and dependencies

`application/single_app/functions_orchestration_external_sources.py` exports:

- `CurrentExternalSourceIdentity(user_id, roles, user_enable_agents=False, email=None)`.
- `ExternalSourceConfiguration(identity, revision)`, containing bounded opaque
  configuration tokens, not credentials or fetch URLs.
- `OrchestrationExternalSourceProvider(...)`, scoped to one actor/conversation.

The provider requires these owner-supplied callbacks:

| Callback | Required result and boundary |
| --- | --- |
| `read_identity(*, user_id, conversation_id)` | A new `CurrentExternalSourceIdentity` from a **current** account/app-role check on every call. Missing identity or loss of the User/Admin role denies access. |
| `read_settings()` | Current normalized application settings, supplied by their owner. The provider never calls `get_settings()` or imports configuration to rediscover them. |
| `read_conversation(id)` and `read_run(id)` | Current server records used by the existing result-access producer checks. The producer must belong to this actor/conversation and a recorded v2 plan. |
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
metadata. It is not sufficient to establish supported v2 acquisition.

The root binds this real operation as `external_source_preflight`. External
adapters invoke it before engine/import/logger/budget effects and require an
exact synchronous `None` return. It is not a presence-only readiness flag.
The separate capture callback still performs the stronger combined
authorization/support operation below; entry authorization is not capture proof.

For the v2 root capture callback, use
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
Known recorded audience changes are refused. Directory service failures and
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

### Deterministic research acquisition profile

Captured v2 research initially supports deterministic query and link selection.
This avoids paying for search or page acquisition when later LLM planner request
controls cannot be attested. Constructor `response_length`/`reasoning_effort`
defaults do not prove the source-review planner's temperature/token variants,
fallbacks, or negotiated reasoning controls.

`is_research_acquisition_profile_supported(settings)` in
`functions_orchestration_external_configuration.py` is the shared pure support
predicate. It uses the existing `get_source_review_config` normalization and
clamping; it grants no authority and creates no invocation evidence. The exact
captured Source Review boundary is:

- Query planning is unsupported when `enable_web_search` is true, the normalized
  `deep_research_max_search_queries_per_turn` exceeds one, and
  `deep_research_enable_query_planning` is true. With one query, or no web
  discovery, an enabled query-planning flag cannot initiate a planner request.
- Link planning is unsupported when both `enable_deep_source_review` and
  `source_review_enable_llm_planning` are true. A zero depth, one-page budget, or
  an input that happens to contain no links does not relax this profile boundary.

For example, multiple deterministic search queries require the existing query
planning flag to be false; deterministic deep link selection requires the
existing LLM link-planning flag to be false. No new settings or runtime flags are
introduced. Omitted values retain the source-review normalizer's existing
defaults, including enabled query/link planning and an eight-query limit.
Existing boolean-string normalization is reused, so `"false"` is not treated as
truthy. `enable_web_search` remains an exact boolean in the private configuration
contract.

`preflight_gather_acquisition` validates **both** fresh current settings and the
actual invocation settings at every capture boundary, before current model or
Foundry metadata work. Unsupported profiles raise `ResultUnavailableError` with
code `external_configuration_research_profile_unsupported`. Settings, tools and
overrides are never rewritten to fit the supported subset.

A supported profile still needs genuine `planner` / `resolved` construction
evidence and, with web discovery, the actual Foundry definition/run events under
the same `deep_research` producer. Deterministic planning does not remove those
proofs or the existing model, token, time, step and transport guards. It prevents
LLM query/link planning, not the explicitly attested Foundry search itself.

This is a new-acquisition restriction, not a settings migration or a new
retained-read policy. Authorization-only preflight, `attestor.current`, saved
configuration comparison, and capture-free recovery remain unchanged.
Uncaptured v1 and workflow Source Review retain their existing defaults and
planner behavior. The regression matrix in
`functional_tests/test_orchestration_research_pre_effect.py` covers normalized
profiles, current/actual mismatch, changing current policy between events, zero
effects, deterministic acquisition/restart and v1 LLM query planning.

### Current role refresh is an integration requirement

The existing orchestration route's `_request_identity()` captures session claims
for a request/worker. It is **not** a background role refresher. Reconstructing
`CurrentExternalSourceIdentity` from saved `RunContext.user_roles`, old login claims,
or persisted tokens would violate this provider's callback contract.

The web and scheduler owners must supply a role/account reader that refreshes the
authorization state at each access, including after restart. If that cannot be
done, the callback must fail and the affected retained source remains unavailable.
There is no permissive default or fallback to cached role claims.

## Read-only Microsoft Graph identity reader

`application/single_app/functions_orchestration_external_identity.py` provides
`GraphExternalIdentityReader`. It implements the provider's `read_identity`
callback without trusting saved login roles or treating conversation ownership
as an application role. Construction validates its inputs but performs no I/O.

```python
reader = GraphExternalIdentityReader(
    user_id=user_id,
    conversation_id=conversation_id,
    app_client_id=simplechat_app_client_id,
    graph_base_url=graph_api_base,
    graph_scope=graph_application_scope,
    get_access_token=get_initialized_credential_token,
    http_get=initialized_http_session.get,
    authorize_conversation=authorize_current_conversation,
    read_user_settings=read_current_user_settings,
    execution_check=check_current_execution,
)

identity = reader(user_id=user_id, conversation_id=conversation_id)
```

Inject `reader` directly as `OrchestrationExternalSourceProvider(read_identity=...)`.
The actor and configured application client ID must be canonical lowercase GUID
strings. The conversation remains an exact, bounded application identifier.
Calling a reader with a different actor or conversation fails before token or
directory access.

### Owner-supplied boundaries

| Argument | Contract |
| --- | --- |
| `app_client_id` | The SimpleChat application's client ID whose service principal and role definitions establish authority. This is not a role display name or an arbitrary application selected by a caller. |
| `graph_base_url` | Trusted HTTPS Graph API base including the configured version/path prefix, such as a national-cloud `/v1.0` base or an explicitly trusted Graph gateway. No endpoint is discovered from source content. |
| `graph_scope` | The configured HTTPS application resource scope ending in `/.default`. There is no global-cloud default or change to interactive OAuth scopes. |
| `get_access_token(scope)` | Returns the raw bearer **string**, for example the `access_token` from an owner-controlled MSAL application callback or `initialized_credential.get_token(scope).token`. Do not return a token-result dictionary or add a `Bearer ` prefix. The owner may cache tokens, never account or role results. |
| `http_get(url, *, headers, timeout, allow_redirects, stream)` | An initialized, non-caching `requests.Session.get`-compatible transport returning a `requests.Response`. The reader supplies bounded timeouts, `allow_redirects=False`, and `stream=True`; the transport must honor these and retain normal TLS verification. |
| `authorize_conversation(*, user_id, conversation_id)` | Revalidates the trusted requesting actor's current access and returns the owned server record with matching `id` and `user_id`. This must not merely echo caller-supplied IDs. It runs before directory requests and again before authority is returned. |
| `read_user_settings(user_id)` | A fresh, scoped, read-only document with matching `id` and a dictionary `settings` field. Missing records, failures, malformed data, and wrong actors deny access. |
| `execution_check()` | Optional owning cancellation/lease/budget check. `None` or `True` means continue; `False` raises `ExternalIdentityCancelledError`. Owner control-flow exceptions propagate. |

The application root can reuse the existing authentication configuration:
`functions_authentication._build_msal_app(cache=None,
authority_override=get_graph_authority())` supplies a configured confidential
client. Its creation and `acquire_token_for_client(scopes=[scope])` must remain
inside the injected token callback, reached only for an external identity read.
The lower reader never imports or constructs this authentication owner.
The root may retain the MSAL application/token cache without caching directory
authority.

Pass the existing `get_graph_base_url()` result as the API base; it already
includes `/v1.0`, so do not append the version again. The token callback receives
the separately configured trusted Graph origin's `/.default` scope. Existing
`get_graph_authority()` and `get_graph_base_url()` preserve Public/Gov/custom
cloud selection. Do not reuse the interactive `SCOPE` list or create a new global
OAuth scope. Document/source-free operations must not invoke this token callback.
The root must translate MSAL error dictionaries into the safe denied/service
exception categories below, preserving transient `server_error` or
`temporarily_unavailable` failures without exposing `error_description`.

Do not use the existing `get_user_settings()` as this reader's settings callback:
it can return a request-cached document and create or repair records. Do not call
`check_user_access_status()` either: its broad error handler can default to
allow, and expired restrictions can trigger a write. The owner must instead
provide an authorized current point read using its initialized resources.

The credential and settings/conversation callbacks must also bound their own
I/O. The reader cannot forcibly interrupt an arbitrary synchronous callback.
Its elapsed budget is checked around owner operations and while consuming
response bodies, so an over-budget operation cannot return authority afterward.

### Directory authority and Control Center restrictions

Every invocation reads the current user account, the service principal selected
by the exact configured `appId`, and the user's assignments for that resource.
The account and service principal must both be enabled. Exactly one service
principal must match. Only enabled role definitions that allow `User` members
can contribute role values; application-only, disabled, foreign-resource and
default-access assignments do not imply `User` or `Admin`.

The [user app-role assignment API](https://learn.microsoft.com/en-us/graph/api/user-list-approleassignments?view=graph-rest-1.0)
includes grants through groups of which the user is a **direct** member.
The reader uses the documented `ConsistencyLevel: eventual` header and
`$count=true`, exhausts every page, and verifies the returned count before
returning roles. It does not infer nested-group grants. Canonical object IDs,
assignment principals, role shapes, duplicate definitions/assignments, missing
pages and ambiguous service principals are checked rather than coerced.

A fresh `User` or `Admin` role is mandatory. Non-admins are denied by current
Control Center `settings.access.status="deny"` unless a valid, timezone-aware
`datetime_to_allow` has elapsed. Expiration permits access without changing the
stored restriction. Unknown statuses and malformed restrictions fail closed.
Only a freshly resolved `Admin` bypasses this access restriction, matching
`user_required`; it does not bypass account disablement or the need for a
current settings record. The `enable_agents` preference remains effective even
for admins. Its existing enabled default applies only to a valid current
document where that optional preference is absent, never to a failed read.

### Bounded reads and safe failures

Defaults are 20 total Graph requests/pages, 4,096 total directory records
(including role definitions), 1 MiB per response, a 10-second request timeout,
and a 30-second elapsed authorization budget. The corresponding constructor
options are `max_pages`, `max_records`, `max_response_bytes`, `request_timeout`,
and `max_elapsed`; each also has a finite upper bound.

Every continuation URL must remain HTTPS, on the exact configured origin and
API path prefix, and on the same collection path. Credentials, fragments,
traversal, cycles, malformed links and cross-user/cross-collection continuations
are rejected before requesting another token. Redirects are not followed.
Response bodies are bounded, streamed, closed and decoded without accepting
duplicate JSON keys or non-finite JSON numbers. No error response body is used
as a public message.

| Failure | Parent-facing exception |
| --- | --- |
| Missing current authority, disabled/deleted account or service principal, access restriction, HTTP 401/403/404/410 | Existing `ResultUnavailableError` (`PermissionError`) with a safe code. |
| Throttling, HTTP 5xx, network failures, timeouts or HTTP 202 incomplete work | `ExternalIdentityServiceError` with `retryable=True` and a safe `code`. These are service failures, not an empty role set or proof of revoked access. |
| Invalid/incomplete response shape, pagination, limits or callback contract | `ExternalIdentityServiceError` with `retryable=False`. No authority is returned. |
| Explicit owning cancellation | `ExternalIdentityCancelledError` (`InterruptedError`), distinct from access denial. |

Expected Azure/requests I/O exceptions are translated without preserving raw
provider text or credential-bearing exception chains. Parent code should map
these categories explicitly rather than silently hiding results on a transient
directory failure.

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

Using this reader requires an operator's explicit application-permission grant
of **Directory.Read.All** to an already-configured application identity, as
documented by Microsoft for the assignment API. Existing interactive read scopes
are insufficient. This implementation performs only GET requests: it does not
grant permissions, construct credentials, change login/scopes/settings, write
user records, assign roles, or enable the harness. The parent owns initialized
factory wiring and operator-facing administration documentation; the harness
remains default-off.

Fresh HTTP reads do not eliminate Microsoft's directory replication delay:
the complete group-grant API uses eventual consistency. There is no local role
cache or fallback to old claims during that delay. Current source-specific
execution-configuration capture is a separate requirement; this reader does not
make post-execution current configuration equivalent to the configuration an
adapter actually used.

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
of the owned v2 run. Only model selector fields, selected group IDs and reasoning
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
not change standalone/v1 execution or make the harness runtime-ready.

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
`external_source_preflight`. These are the **four** required v2 runtime
callbacks. Entry preflight performs current authorization, while independent
fresh pre-effect authorization and current/actual support checks
execute inside `capture`, including its initial `source=None` preparation;
retention-time admission is not a substitute. No callback is a no-op readiness
binding. Missing callbacks still withhold discovery/execution.
V1 behavior is unchanged. These server callbacks remain private and
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

Existing capability permissions are reused independently of the new-plan rollout
switch. Turning off `enable_chat_orchestration_harness` does not itself revoke
saved results; ordinary capability/access revocation still does.

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
reader through prepared HTTP requests and streamed `requests.Response` objects,
with only the HTTP adapter and owner I/O doubled. It covers direct/group grants,
the exact target application, current account/role/access revocation, read-only
restriction expiration, paging/counts/bounds/origin checks, malformed data,
transient versus denied failures and national/custom cloud configuration.
Fresh normal and optimized Python processes prohibit network access and
credential/client construction during real application-module imports. No test
contacts a tenant or grants a permission.

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
and configuration callbacks are required production dependencies, not evidence
that the full harness is ready for admission.
