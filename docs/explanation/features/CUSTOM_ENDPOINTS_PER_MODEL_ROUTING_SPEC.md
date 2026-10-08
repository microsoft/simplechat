# Custom Endpoints: Per-Model Routing and GenAI.mil

## Status and Version

- Status: Phases 0-3 implementation is committed through `262ccbce`. The approved editor refinements, shared CA bundle manager, and Phase 4 GenAI.mil profile are implemented in the working tree in **0.261.052**. Local regression validation is recorded below; live provider acceptance, release promotion, and deployment remain separate.
- Date: 2026-09-21.
- Decisions last reviewed: 2026-10-05. Shared CA certificates use a dedicated private container in the existing Blob account and metadata in the existing Cosmos DB, independent of Enhanced Citations. Agents remain excluded from new per-model routing. Live GenAI.mil access remains unavailable to the current tester.
- Baseline application version: **0.261.039**, from `application/single_app/config.py`.
- Phase 0 closeout version: **0.261.040**, for test-fixture repairs and required version metadata only; that version did not implement new routing.
- Implemented in version: **0.261.041** for Phase 1, **0.261.042** for Phase 2, **0.261.044-0.261.046** for Phase 3 runtime hardening/activation, and **0.261.052** for editor usability, shared CA storage/trust selection, and the named GenAI.mil profile. `application/single_app/config.py` is **0.261.052**.
- Working branch: `feature/customendpoints`, created from refreshed `origin/Development`.
- Baseline commit: `f1be106ec2088cf9105293a7b1dac16e668e2685`.
- Source reviewed: [Paullizer's React v2 branch in the main repository](https://github.com/microsoft/simplechat/tree/3f896d7b6c45800c593599f3100b9aa7c7251159), `origin/paullizer-react-v2-ui`, commit `3f896d7b6c45800c593599f3100b9aa7c7251159`, version **0.261.126** at inspection. The user identified the deployed UI as **0.261.123**; pin the source commit rather than assuming the deployed UI is the latest branch tip.
- Tracking: [issue #1518](https://github.com/microsoft/simplechat/issues/1518) and [PR #1514](https://github.com/microsoft/simplechat/pull/1514). The prior local/uncommitted Phase 3 statements below describe historical checkpoints; Phase 3 is now committed. New **0.261.052** changes are not committed or deployed by this implementation task. Live GitHub status was not reverified because SSO authorization was unavailable. Existing issue #1222 is not the tracker for this scope.

## Problem and Evidence

An endpoint currently owns the Custom API type, while its models primarily supply model/deployment identifiers. That cannot describe a gateway hosting models with different route prefixes and protocols under one hostname and credential.

The APIM API suffix is a path prefix, not a hostname or model identifier. It may contain multiple segments, such as `aoai-global-team/v1`. Model names must not decide which wire protocol a configured Custom model uses.

Verified local Development-baseline behavior before this proposal:

- `normalize_anthropic_messages_url` falls back to origin-only normalization for non-Custom endpoints. A gateway URL ending in `/aoai-global-team` becomes `/anthropic/v1/messages`, losing the gateway prefix.
- Azure deployment-style calls preserve that prefix and add `/openai/deployments/{deployment}/chat/completions` plus `api-version`.
- OpenAI-compatible calls preserve this prefix and use a different operation path. The current non-Custom inference heuristic can choose the wrong protocol when APIM hides the backend hostname.
- `functions_model_endpoint_types.py` and `functions_settings.py` resolve identifiers and prune version/identifier fields using the endpoint-level API type. Moving only the UI dropdown would lose data or dispatch incorrectly.
- `functions_model_endpoint_runtime.py` has both synchronous chat and Semantic Kernel service construction. Audit which builders serve in-scope model chat/helper calls; shared ownership does not bring agent integration into scope.

These findings came from source inspection and network-blocked/mocked local requests, not live APIM or GenAI.mil validation.

### Source Integration Finding

The initial investigation used the same-named branch on the wrong remote: `paullizer/simplechat` at `631edca15cdc00aad76b5126cecda9922d604586`, version **0.261.023**. Its missing Custom modules and smaller catalogue do not describe the intended source. That assessment is superseded by the main-repository branch above.

The correct source contains the Custom provider, type, authentication, validation, and diagnostics modules; a dedicated `functions_model_endpoint_urls.py`; expanded model-library metadata; Custom endpoint foundation tests; and URL Handling controls. There is no missing-source blocker. The source's current UI has evolved beyond the reported deployed version, so compare pinned revisions during the implementation audit.

Treat Development as the target/security baseline and the main-repository React branch as the source of reusable Custom work. Port the relevant foundation, library, runtime, editor, and regression changes selectively; do not merge the entire React branch or discard either branch's protections. Source-only paths are provenance references, not files this proposal has added locally.

### Reviewed Selective Port Manifest

Reviewed on 2026-09-22. In this table, **D** is Development commit `f1be106ec2088cf9105293a7b1dac16e668e2685` and **S** is source commit `3f896d7b6c45800c593599f3100b9aa7c7251159`. Application paths are relative to `application/single_app/`; test paths are relative to `functional_tests/`. These are logical hunk selections, not approval to replace whole files or cherry-pick unrelated commits. Phase 1 adapted registry metadata, pure URL ownership, auth-merge preservation, and auth projection filtering; model-local contracts, migration planning, scoped context resolution, and conservative capabilities are new work. Legacy client URL helpers now have compatibility imports from the pure owner. Actual consumer dispatch, transport changes, catalogue assets, and editors remain deferred.

| Logical change | Pinned evidence | Port decision and dependencies |
|---|---|---|
| Registry and identifiers | D/S: `functions_model_endpoint_providers.py`, `functions_model_endpoint_types.py`. Same four registered types; S adds `protocol`/`urlPolicy` UI metadata and changes Azure API-key defaults. S also adds an embedding-only validation alias. | **Reuse D, adapt S metadata**, then add `azure_openai_v1` and per-model resolution. Keep public helper contracts and endpoint header overrides. Do not silently change legacy Azure auth defaults; omit the embedding alias and unrelated dataclass refactor. Depends on contract tests. |
| Pure URL policy | S: new `functions_model_endpoint_urls.py`; D/S: `model_endpoint_clients.py`. S extracts OpenAI base handling and adds an encoded Azure deployment resolver. | **Port and extend** the pure owner with origin-first suffix composition and strict schema-v2 rules. Preserve compatibility imports/readers. S Azure Exact accepts any base, Auto uses substring replacement, and Messages Exact treats the URL as a complete operation; none is the new contract unchanged. Do not enable Responses/images/embeddings from operation-suffix metadata. Depends on registry and URL tests. |
| Credentials and outbound safety | D/S: `functions_model_endpoint_auth.py`, `functions_model_endpoint_validation.py`, `functions_model_endpoint_diagnostics.py`, transport classes in `model_endpoint_clients.py`. S adds header/framing checks, request-time Host validation, explicit redirect rejection, stricter URL checks, and OAuth/diagnostic changes. | **Adapt relevant hardening hunks and tests**, retaining D's DNS pinning, TLS/private-host gates, CA/mTLS, error interfaces, and auth ownership. Validate legacy parity rather than copying rewritten modules. Transport-option changes must be threaded through each in-scope adapter. |
| Normalization, secrets, and migration | D/S: `functions_settings.py`. S normalizes endpoint `connection.url_mode`, preserves empty header/prefix overrides during auth merge, and adds Custom auth projection filtering. Its identifier/version pruning is still endpoint-scoped and it also imports unrelated AI connection/operation machinery. | **Reuse D and adapt narrow preservation/sanitization hunks**. Implement model-local fields and dual readers as new work; neither branch supplies this migration. Preserve stable IDs, Key Vault references, budgets, and identity headers. Do not copy operation settings, automatic unrelated migrations, or broader settings rewrites. Depends on registry, validation, and migration fixtures. |
| Runtime and connection tests | D/S: `functions_model_endpoint_runtime.py`, `model_endpoint_clients.py`, `route_backend_models.py`, `route_backend_chats.py`. S routes guarded Custom SDK construction through new helpers but also depends on `functions_ai_connections` and unrelated image/reasoning/workflow changes. | **Adapt client/transport and routing hunks**, using D's existing scope/credential boundaries. Do not wholesale port the new connection framework, chat route, or Semantic Kernel changes. Preserve legacy call behavior; opt only audited in-scope callers into the new contract. Depends on resolver, normalization, and security fixtures. |
| Model library | D/S: `static/json/model_capabilities.json`, its schema, and `functions_model_capabilities.py`. Parsed counts are 75/113. S adds `imageOperationProfiles`, reasoning/image fields, and changes `load_model_capability_catalog()` from a document to an identifier-indexed view. | **Select chat-relevant catalogue/schema/resolution hunks together**. Preserve D's loader return contract, audited token-evidence matching, budget precedence, and explicit capability restrictions. Do not assume all 113 records or S's loader can be copied unchanged; defer new image/embedding execution and unrelated reasoning UI/retry behavior. Depends on catalogue/schema and budget tests. |
| Active endpoint editors | D/S: `static/js/admin/admin_model_endpoints.js`; `templates/_multiendpoint_modal.html` and `static/js/workspace/workspace_model_endpoints.js` have no pinned diff. S's admin URL Handling remains endpoint-scoped and also handles new operation settings. | **Adapt selected admin behavior to D's Jinja/JavaScript UI**, then implement per-model rows in both global and shared personal/group editors. No source patch already provides per-model routing. Keep existing local assets; omit React and image/embedding UI. Depends on normalized descriptors and save/load contracts. |
| Selection identity | D/S: `static/js/chat/chat-model-selector.js`. The two added S fields carry model name and reasoning capabilities, not per-model URL/API routing. | **Reuse D's stable selection identity** and add only approved routing metadata where needed. Do not substitute display names or adopt React pickers/agent selection. Verify test-model and helper parity. Depends on normalized records and runtime context. |
| Regression reuse | S: `test_custom_model_endpoint_foundation.py`, `test_admin_model_endpoint_editor_integration.js`, `test_custom_model_connections_ui_logic.js`, catalogue and summary/payload-order tests. The foundation suite imports screening/workflow/V2-admin helpers; the editor harness uses Node built-ins and a mocked DOM. | **Port coherent test cases, not whole suites**. Extend D's nearest tests. Adapt registry/URL/auth/transport/secret cases and the editor harness without its unrelated operations. The two narrow baseline fixture repairs have been applied/adapted; see Phase 0 results. Browser coverage is still required later. |
| Dependencies | D/S: `requirements.txt` keeps OpenAI/Semantic Kernel/Foundry SDK pins. S adds `regex==2026.5.9` for `content_screening` and `tiktoken==0.12.0` for `functions_workflow_context.py`. Root `package.json` and `requirements-dev.txt` have no pinned diff. | **Retain D's dependencies** for the selected routing work. Neither new package is installed in the tested environment; neither is a routing prerequisite. Do not import excluded source modules just to run a copied test suite. Reassess only if a selected hunk demonstrates a real dependency. |

## Goals and Scope

1. Reuse relevant model-library and Custom endpoint work from the verified source, preserving provenance and tests.
2. Give each model an optional multi-segment **API path suffix**, including models on existing endpoint providers.
3. Give each Custom model an authoritative **Model API type** with separate choices for Azure OpenAI (Deployments), Chat Completions (Azure/Foundry), OpenAI API (Chat Completions), and Messages (Anthropic-compatible), preserving existing compatible profiles such as Gemini. The Azure/Foundry choice shares the OpenAI-compatible Chat Completions adapter; it is not a new wire protocol. Responses is deferred.
4. Support mixed protocols and paths under one Custom endpoint, with independent identifiers and protocol-specific versions.
5. Make saved configuration, test-model, interactive model chat, and its non-agent helper/background calls use the same resolved routing contract.
6. Add **GenAI.mil** as a first-class, named endpoint provider/profile using its documented OpenAI-compatible API.
7. Preserve existing configurations and security boundaries; provide a reversible migration path.
8. Keep routing, protocol adaptation, and policy boundaries suitable for future Responses and custom calls, without developing either feature in this release.

In scope: global, personal, and group endpoint editing; model-library metadata; model selection; configuration normalization; model-chat streaming and existing supported tool behavior; capability gates; GenAI.mil model discovery; documentation and regression coverage.

Out of scope: Responses model inference; custom calls (custom request bodies, URL templates, or arbitrary HTTP dispatch); agent integration or behavior changes; a React UI migration; unrelated source-branch features; new embedding/image/audio APIs; automatic key unlock; GenAI.mil key provisioning; changes to APIM policies; and deployments beyond the explicitly selected beta validation target below. Existing supported capabilities must not be removed. Responses and custom calls require separate future plans and explicit implementation approval.

Agent scope boundary: preserve existing agent behavior and configuration. Do not wire new routing modes into agent defaults, overrides, selectors, hosted-agent integrations, or tool loops. Shared helper/settings changes must not silently opt agent consumers into schema-v2 routing; retain their compatibility path and verify non-regression where shared code is touched. Any boundary that cannot preserve that behavior is a scope blocker, not permission to extend agent support.

## Configuration Contract

### Endpoint and Model Responsibilities

| Owner | Proposed fields and behavior |
|---|---|
| Endpoint | Stable `id`, provider/profile, enabled state, base connection URL, auth and Key Vault references, and identity-header policy. Credentials remain endpoint-scoped. No inherited URL Handling setting for schema-v2 Custom models. |
| Model | Stable `id`, display metadata, existing model/deployment identifier, enabled/capability settings, `api_path`, explicit `api_type` and `url_mode` for Custom models, `api_version`, and `anthropic_version` where applicable. |
| Library/profile | Defaults, supported protocol options, URL policy, credential header defaults, and verified capabilities. Metadata is not permission to invoke a model. |

New endpoint records use `routing_schema_version: 2`. New Custom model records persist explicit `api_type` and `url_mode` values; missing and unsupported values are rejected on new saves. Library suggestions become visible, saved model values, not runtime inheritance from an endpoint default. Existing records without the marker use the compatibility reader until explicitly migrated. Schema-v2 test, chat, and audited helper dispatch is implemented locally in Phase 3.

`api_path` defaults to an empty string and is the gateway API suffix. For schema v2, insert its complete segment sequence immediately after the origin (scheme, host, and optional port), before the endpoint's remaining path and the API-specific route: `origin / model API suffix / endpoint path / protocol route`. The suffix may contain multiple segments; "first level" describes its insertion point, not a one-segment limit. API type selects a calling adapter, not a literal path segment bearing a provider name.

A new gateway configuration should use the origin as its endpoint URL and put model-specific prefixes into `api_path`. If an endpoint contains an API base such as `/openai/v1`, the suffix goes before it: endpoint `https://gateway.example/openai/v1` plus suffix `team` produces an API base of `https://gateway.example/team/openai/v1`. Preserve the endpoint path's segment order; do not drop it, append the suffix after it, or deduplicate arbitrary repeated segments. Legacy records retain their old composition until explicit migration; ambiguous existing gateway prefixes require owner review.

Per-model versions take precedence over compatible legacy endpoint versions. Do not remove one model's deployment identifier or version because another model uses Messages or OpenAI. Changing a model API type requires the new identifier/version fields to validate; do not silently substitute a display name or reuse an unrelated identifier.

### Model API Types

| UI label | Persisted value | Identifier | Native operation and version behavior |
|---|---|---|---|
| Azure OpenAI (Deployments) | `azure_openai` | `deploymentName` | `chat/completions` beneath `openai/deployments/{deployment}`; requires an approved `api-version`. |
| Chat Completions (Azure/Foundry) | `azure_openai_v1` (configuration, preview, and local dispatch implemented in 0.261.044) | `modelName` | `/openai/v1/chat/completions` in Auto mode; Azure deployment/model identifier in the JSON `model` field, not the URL; no implicit dated query version. Shares the OpenAI-compatible adapter. |
| OpenAI API (Chat Completions) | `openai` | `modelName` | `chat/completions` beneath the API base; model in JSON; no implicit dated query version. |
| Messages (Anthropic-compatible) | `anthropic` | `modelName` | `messages` beneath the API base; Anthropic-compatible Messages request, response, and event contract, independent of model vendor; applicable `anthropic-version` header. |

Confirmed Azure API presentation (2026-09-22): **Chat Completions (Azure/Foundry)** is a separate labeled dropdown choice, distinct from **Azure OpenAI (Deployments)**, and shares the existing OpenAI-compatible adapter. Preserve generic OpenAI-compatible connections, including GenAI.mil. Implement the distinction through registry metadata and URL policy, not a duplicate request/response adapter or model-name/hostname inference.

The selected key `azure_openai_v1` names that URL policy and UI choice, not a new wire protocol; its runtime protocol remains `openai_style`. Phase 0 found no occurrence or conflicting alias in either pinned application/test tree and confirmed the existing adapter's wire mapping with a mocked SDK request. The new registry entry, dedicated Azure/Foundry URL policy, and per-model persistence remain implementation work. New saves and editor round trips must retain the explicit choice; do not relabel or migrate existing `openai`, `azure_openai`, `anthropic`, `gemini`, or provider records merely from their URL. Endpoint credentials/header policy remain authoritative for both Chat Completions choices.

Confirmed deferral (2026-09-21): Responses is not a selectable or executable model API type in this release. Keep **Responses (OpenAI-compatible)** as an approved future label only; do not add a registered `responses` type, saved model option, adapter, or provider-side continuation state. Treat attempted unsupported API types as validation errors, never as a reason to fall back to Chat Completions. See the future-work section for Responses and custom calls.

API type selects the library/client method and its wire-format adapter, including request bodies, response blocks, streaming events, and tool exchanges. It is not inferred from the model family, provider name, or an operation called `messages`. A different API with a `/messages` route but incompatible schemas is not supported by this adapter; it would need a separately reviewed adapter rather than arbitrary body/URL handling.

Provider/profile, model vendor, URL path version, and wire contract are separate concepts. A configured `/v2/messages` path may use the same compatible contract through a gateway, but its spelling does not prove compatibility with a future protocol revision. Do not invent v2 schemas or silently change adapters. `anthropic_version` represents the protocol's dated header where required, not the `v1`/`v2` path segment; Azure's dated `api-version` query is likewise distinct. Endpoint/profile authentication remains authoritative and may differ between compatible hosts.

#### Non-Anthropic Messages Evidence

Official documentation inspected on 2026-09-21 demonstrates that Messages compatibility is not limited to Anthropic models:

- [Ollama Anthropic compatibility](https://docs.ollama.com/api/anthropic-compatibility) documents `/v1/messages`, an Anthropic SDK example using `qwen3-coder`, and `gpt-oss:20b` among recommended local models. Ollama explicitly supports a subset of the Anthropic API; examples include unsupported `tool_choice` and prompt caching. Its direct cloud endpoint requires bearer authentication rather than `x-api-key` alone.
- [MiniMax Anthropic SDK compatibility](https://platform.minimax.io/docs/api-reference/text-anthropic-api) documents calling MiniMax models, including the M2 series, with `client.messages.create`. Its compatibility table describes supported, partial, and ignored parameters rather than identical behavior for every model and field.

These are evidence for vendor-independent adapter selection, not a claim that SimpleChat has validated these hosts/models or a commitment to add named provider integrations. Test each enabled feature against the actual gateway/model contract. A shared adapter with capability restrictions is sufficient; no model-vendor-specific protocol inference or generic request engine is required.

Keep existing persisted `anthropic` values rather than renaming records to `messages`. Preserve existing Gemini OpenAI-compatible configurations/profile metadata; an editor migration must not coerce their `/v1beta/openai` paths or capabilities to generic OpenAI defaults.

For non-Custom providers, show the path field and the effective protocol; retain provider-specific behavior for legacy records. Any migration to explicit routing must preserve the previous working wire contract. GenAI.mil offers only its documented OpenAI-compatible Chat Completions contract in the initial release, not the Azure/Foundry URL policy. It does not inherit every Custom protocol simply because it uses the shared registry.

### Example Mixed Gateway

Illustrative proposed storage, omitting existing auth and other model fields:

```json
{
  "id": "gateway-example",
  "provider": "custom",
  "routing_schema_version": 2,
  "connection": {
    "endpoint": "https://gateway.example"
  },
  "models": [
    {
      "id": "model-deployment",
      "api_type": "azure_openai",
      "url_mode": "auto",
      "api_path": "aoai-global-team",
      "deploymentName": "team-deployment",
      "api_version": "approved-api-version"
    },
    {
      "id": "model-chat",
      "api_type": "openai",
      "url_mode": "auto",
      "api_path": "aoai-global-team/v1",
      "modelName": "gateway-model-id"
    },
    {
      "id": "model-foundry-chat",
      "api_type": "azure_openai_v1",
      "url_mode": "auto",
      "api_path": "team",
      "modelName": "team-foundry-deployment"
    },
    {
      "id": "model-messages",
      "api_type": "anthropic",
      "url_mode": "auto",
      "api_path": "team/anthropic/v1",
      "modelName": "gateway-messages-id",
      "anthropic_version": "2023-06-01"
    }
  ]
}
```

### URL Handling Decision

Confirmed during spec review: **URL Handling is explicit on each Custom model**, alongside **Model API type** and **API path suffix**. There is no endpoint default or model override/inherit control for schema-v2 Custom records. Legacy endpoint values are compatibility-reader and migration inputs only; migration copies their effective values into each model before enabling the new contract. Non-Custom provider behavior remains unchanged except for the planned suffix support.

For schema v2, **Exact** means use the composed API base as given, without adding a version or Azure deployment prefix; append only the known operation. It does not mean arbitrary full-request URLs. Azure OpenAI (Deployments) Exact bases must already include the `openai/deployments/{deployment}` path and agree with the selected deployment. Chat Completions (Azure/Foundry) Exact appends only `/chat/completions`, allowing an explicitly configured gateway mount without requiring `/openai/v1`. Legacy exact Messages operation URLs are interpreted by the compatibility reader, not changed silently to this new base-URL meaning.

Automatic mode applies the selected protocol's structural rules after composing origin, model `api_path`, and endpoint path in that order:

- Generic OpenAI-compatible Chat Completions: append `/v1` when the base has no recognized terminal version segment; preserve terminal `v1`, `v1beta`, or another supported version and registered as-given profiles such as Gemini.
- Chat Completions (Azure/Foundry): preserve an existing terminal `/openai/v1`, extend a terminal `/openai` with `/v1`, or append `/openai/v1` to the composed base, then `/chat/completions`. Preserve preceding gateway segments, including literal `v1` prefixes; reject recognized deployment-style bases rather than mixing API families. No deployment-path insertion or implicit dated `api-version` query is allowed.
- Messages: append the default `/v1` only when there is no recognized terminal version segment, then `/messages`. Preserve an explicitly configured terminal version such as `v1` or `v2` rather than constructing `/v2/v1/messages`. This is URL construction, not a guarantee of compatibility with a future wire format. Foundry-style Messages uses an explicit `anthropic/v1` base suffix; do not guess that segment from `claude` in the model name.
- Azure OpenAI: append `/openai/deployments/{encoded-deployment}/chat/completions`. Reuse only recognized terminal Azure base/deployment structures; do not duplicate `openai` or a matching deployment. Reject an incompatible terminal `/openai/v1` base for deployment mode instead of constructing both API families.
- Do not strip an arbitrary gateway prefix to switch protocols. Native Foundry project-path conversion remains a separate, recognized legacy conversion, not an origin-only fallback for gateway paths.

The resolver must parse URLs and compose path segments; a leading slash must never cause `urljoin`-style replacement of the configured base path. Recognize structural suffixes by complete path segments, not substring matches such as `/models` inside a gateway prefix. Never deduplicate unrelated segments by guessing.

### Required URL Examples

All examples use endpoint `https://gateway.example` unless stated otherwise. `D` is a validated deployment identifier. The `v2` case tests path preservation only; it does not assert that a Messages v2 protocol exists or is supported.

| API type | Model path | Mode | Expected request path |
|---|---|---|---|
| OpenAI | `aoai-global-team` | Auto | `/aoai-global-team/v1/chat/completions` |
| OpenAI | `aoai-global-team/v1` | Auto | `/aoai-global-team/v1/chat/completions` |
| OpenAI | `aoai-global-team/openai/v1` | Auto | `/aoai-global-team/openai/v1/chat/completions` |
| OpenAI | `aoai-global-team` | Exact | `/aoai-global-team/chat/completions` |
| Chat Completions (Azure/Foundry) | `team` | Auto | `/team/openai/v1/chat/completions` |
| Chat Completions (Azure/Foundry) | `team/openai/v1` | Auto | `/team/openai/v1/chat/completions` |
| Chat Completions (Azure/Foundry) | `team/v1` | Auto | `/team/v1/openai/v1/chat/completions` |
| Chat Completions (Azure/Foundry) | `team` | Exact | `/team/chat/completions` |
| Chat Completions (Azure/Foundry), endpoint already ends in `/openai/v1` | `team` | Auto | `/team/openai/v1/chat/completions` |
| Messages | `aoai-global-team` | Auto | `/aoai-global-team/v1/messages` |
| Messages | `aoai-global-team/v2` | Auto | `/aoai-global-team/v2/messages` |
| Messages | `aoai-global-team/anthropic/v1` | Auto | `/aoai-global-team/anthropic/v1/messages` |
| Azure OpenAI | `aoai-global-team` | Auto | `/aoai-global-team/openai/deployments/D/chat/completions?api-version=...` |
| Azure OpenAI | `aoai-global-team/v1` | Auto | `/aoai-global-team/v1/openai/deployments/D/chat/completions?api-version=...` |
| Azure OpenAI | `team/openai/deployments/D` | Exact | `/team/openai/deployments/D/chat/completions?api-version=...` |
| OpenAI, endpoint already ends in `/openai/v1` | `team` | Auto | `/team/openai/v1/chat/completions` |
| OpenAI, endpoint already ends in `/shared` | `team` | Auto | `/team/shared/v1/chat/completions` |

The Azure `team/v1` example preserves a literal gateway prefix; it does not opt into OpenAI v1 semantics. Backend/API routing must agree with the resulting path. Resolved-request preview and real dispatch must use the same resolver.

### Path Validation

- Allow multiple ordinary path segments, hyphens, underscores, and a blank suffix. Normalize surrounding whitespace and one ordinary leading/trailing slash consistently.
- Reject scheme/hostname overrides, scheme-relative `//host`, backslashes, queries, fragments, embedded credentials, control characters, interior empty segments, and dot/dot-dot traversal segments.
- Reject encoded separators, encoded traversal, double-encoded bypasses, malformed percent escapes, and any input whose decoding changes origin or segment boundaries. Use a documented segment allowlist rather than arbitrary percent-decoding loops.
- Deployment identifiers are separate from the path, validated and encoded as one segment. They cannot inject an operation, query, or another host.
- Validate the final composed URL at save and execution. Preserve HTTPS/TLS policy, DNS pinning, blocked-address checks, redirect refusal, private-host controls, approved CA/mTLS configuration, and existing cloud/authority configuration.

## Shared Runtime and Model Library

Extend the source's pure URL-contract module into one shared routing resolver below routes and clients, rather than creating a competing implementation. Input is the authorized saved endpoint plus selected saved model; output includes the effective profile, API type, request identifier, API base, operation URL, version fields, credential policy, and verified capability policy. The resolver does not retrieve secrets or mutate settings.

Evolve the existing provider registry instead of introducing competing protocol lists. Separate provider/profile identity (including GenAI.mil) from model wire protocol. Library metadata can prefill a new model, but an explicit saved model choice wins. A Claude-named model explicitly configured for OpenAI stays OpenAI; a GPT-named model explicitly configured for Messages stays Messages if the gateway supports it.

Library records must carry provenance/version and conservative capability metadata. Availability, model permission, and enabled state are resolved at runtime. Unknown models remain manually configurable under governance; library inclusion is not proof of tool, vision, JSON-schema, reasoning, image-generation, or Responses support.

For explicit Custom/GenAI routing, effective capabilities are bounded by the adapter and verified gateway/profile contract, then by the selected model's supported features. A catalogue match or model override cannot grant a feature excluded by the gateway contract. Preserve legacy capability behavior outside this new routing mode unless an independently tested migration changes it.

Authentication precedence: explicit authorized endpoint header/prefix settings, then the selected provider/profile policy, then protocol defaults. Do not change an APIM subscription-key header because the selected model changes protocols. Models requiring different credentials should use separate endpoint records in this release. Preserve identity-header protections and Key Vault scope.

## Model Chat and Background Work

- Select by stable endpoint/model IDs, not display names. Global, personal, and group permissions remain authoritative on the server.
- Update test-model, model chat, summaries, metadata/title generation, tabular calls, and their non-agent queued/background context consumers to use the resolver. Audit any Semantic Kernel chat-service construction used by these callers without extending agent support; do not claim coverage solely from a model-test success.
- Preserve routing metadata in authorized runtime context without persisting secrets. Re-resolve saved IDs and permissions at execution/resume; handle removed/disabled models with a safe error rather than falling back to another endpoint.
- Include effective API type, path, versions, profile, and configuration revision in client/cache keys so two models cannot share the wrong client. Do not include raw credentials in logs or public keys.
- Preserve chat's current stream envelope, cancellation, citations, token accounting, attachments, and error display across protocol adapters.
- Dispatch only implemented, registered adapters. Do not add Responses invocations, custom payload dispatch, request templates, continuation handling, or new agent/tool orchestration as part of this work.
- Test Messages-compatible streaming and existing supported tool behavior as well as OpenAI and Azure calls, including non-Anthropic model identifiers and a restricted compatible-host fixture. Feature-gate tools/vision/structured output by verified protocol plus model capabilities, and reject unsupported requested features before dispatch. Do not assume all compatible hosts support optional fields, forced tool choice, caching, or the same authentication header.
- For models with no verified tools, allow ordinary model chat and reject tool-dependent requests rather than advertising unsupported function calling. Agent behavior remains outside this change.

## UI and User Workflows

Use the active Development UI and existing shared endpoint editor. Do not import the React runtime to deliver these controls. Apply equivalent contracts to a future React consumer only when that consumer is separately in scope.

Each model editor exposes API path suffix and, for Custom, explicit Model API type and URL Handling dropdowns together. Show Model Name or Deployment Name and protocol-specific version fields accordingly. Do not offer endpoint inheritance for Custom routing. Preserve display name, icon, response length, enabled state, and capability settings.

The editor offers a secret-free resolved method/path preview and model test. It must make duplicate or incompatible route structures visible before saving. Switching model type must not silently discard fields or move every other model onto that type. Existing legacy configuration remains operable without forcing an edit.

Example workflows:

1. Add a Custom endpoint for an APIM hostname and its shared credential/header policy. Add an Azure deployment model at `aoai-global-team`, an OpenAI model at `aoai-global-team/v1`, and a Messages model at `team/anthropic/v1`. Verify each independent request preview/test, then save.
2. Choose GenAI.mil, enter the scoped key through the existing secret flow, load available models, and select an authorized model. Manual model entry remains available if discovery is unavailable.
3. Select a saved model in chat. The model test, chat call, and related in-scope helper calls must agree on its route and identifier and enforce the selected model's verified capabilities.

No Responses option, placeholder Custom body/URL editor, selectable unimplemented API type, or fake test-success state is added.

## GenAI.mil Provider Profile

Confirmed initial scope (2026-09-22): implement the named GenAI.mil profile with model discovery and streamed/non-streamed OpenAI-compatible Chat Completions, scoped bearer-key authentication, documented-only request fields, and the error handling below. Do not include tools/function calling, vision, structured output, Messages, or Responses without a separately approved and verified contract. This confirms the planned product scope, not live service validation, vendor endorsement, or authorization to send data.

### Evidence and Defaults

Source: user-supplied API documentation and Swagger text received for this planning session. Their referenced pages are [user API documentation](https://genai.mil/stark/user-ui/docs) and [Swagger UI](https://genai.mil/stark/api/swagger-ui/#/LLM). These pages were not live-verified. Do not commit the full supplied documents, credentials, customer data, or local download paths.

The supplied quick start and curl example establish:

| Item | Initial support |
|---|---|
| Display name / profile key | `GenAI.mil` / proposed `genai_mil` |
| Default API base | `https://api.genai.mil/v1` |
| Inference | `POST /v1/chat/completions` |
| Discovery | `GET /v1/models` |
| Authentication | Scoped API key sent as `Authorization: Bearer <key>` |
| Model identifier | Exact model ID returned by discovery or entered manually; documentation examples are not a guaranteed inventory. |
| Streaming | Chat Completions SSE, explicitly documented. |
| Initial request fields | `model`, `messages`, optional `temperature`, `max_tokens`, `stream`. |

Register GenAI.mil in the endpoint picker and shared profile registry, not as a special URL check scattered across model-chat consumers. Preserve the existing governance toggles for personal/group Custom endpoints when allowing this external profile; a new provider name must not bypass them. Apply the same endpoint secret-storage, sanitization, scope, and outbound safety policies.

Keep the API host configurable under existing governance for future approved environments. Changing to a different host requires explicit approval of sending the configured credential there; do not silently forward a stored GenAI.mil key to a new origin. Product support does not establish authorization to send any particular classification or category of data.

### Capability Limits and Errors

- Do not infer tool/function calling, vision, structured output, Responses, or image generation from OpenAI compatibility or a Gemini/Claude model name. Disable those capabilities unless separately documented and validated.
- The documents mention Anthropic compatibility but do not supply a Messages operation/schema. Initial GenAI.mil support is OpenAI Chat Completions only. Adding Messages requires a verified contract, not a guessed `/v1/messages` request.
- Omit undocumented request extensions such as `stream_options.include_usage` by default. `usage: null` is documented; display unavailable usage honestly and do not record it as zero actual consumption.
- Keys lock every eight hours according to the supplied documentation. Handle a locked-key 401 with a safe action-required message and the configured portal link. Do not repeatedly retry, automatically unlock, or fetch an arbitrary `unlock_url` supplied by an error body. Any future displayed unlock URL needs an explicit approved-origin and scheme policy.
- 403: scoped model permission denied. 404: model unavailable/not enabled. 429: respect bounded `Retry-After`/backoff and cancellation. 502: upstream failure. Never blindly replay a partially consumed stream or an operation with completed side effects.
- Sanitize provider errors and key material. Retain safe status/correlation information for diagnostics. Discovery uses a protected backend request, never a browser request containing the key.

## Compatibility, Migration, and Rollback

1. Add dual readers first. Legacy endpoint `api_type`, `connection.url_mode`, version fields, and identifier aliases retain their old behavior until migration.
2. Dry-run migration derives explicit model-level API type and URL Handling values from the endpoint and reports ambiguous full-operation URLs, existing gateway prefixes, incompatible model identifiers, and unknown API types. Preserve stable endpoint/model IDs and all secrets/references.
3. Do not split or rewrite arbitrary URL paths by heuristic. Migrate unambiguous settings deterministically; retain a legacy record or require explicit owner review for ambiguous routes. Read-time normalization must not destructively write back a guess.
4. Changing to schema v2 copies the effective legacy settings into every model first. Mixed API types can then be added deliberately. Legacy Gemini and exact Messages configurations require explicit parity tests. Preserve the agent compatibility boundary: where a shared record cannot be migrated without changing an excluded consumer's behavior, retain its legacy mode and require separate scope review rather than silently migrating it.
5. Existing non-Custom endpoints with no model suffix retain their working contract. Fix the APIM prefix-loss case with targeted regression coverage while preserving native Foundry project conversion.
6. Keep a versioned backup/export before persisted migration. Rollback restores the old configuration and code together; old binaries cannot safely interpret mixed-protocol records. Never collapse mixed models into one endpoint type on downgrade. Disable or restore affected records explicitly if full rollback is unavailable.

## Future Responses and Custom Calls

Both features are deferred to separate future plans. Their architectural accommodation below is in scope; their runtime implementation, UI, persisted configuration, and live validation are not.

### Extension Boundary for Current Work

- Reuse the existing registry, pure URL resolver, and adapter dispatch. Keep URL composition separate from protocol-specific request construction and response/stream normalization so a future reviewed adapter can be added without rewriting endpoint identity, credential ownership, or model path composition.
- Keep scope authorization, outbound URL validation, credential/header policy, capabilities, and safe diagnostics shared and mandatory for every adapter. Future extensibility must not create a permissive fallback or bypass path.
- Define only the interfaces needed by the current Chat Completions and Messages adapters. Do not implement a generic request engine, speculative adapter framework, disabled Responses adapter, placeholder editor, new feature flag, or template storage to anticipate future work.
- Unknown or deferred API types and custom-call configuration are rejected on new saves and before model dispatch. Catalogue metadata and SDK support do not enable an adapter. Existing legacy operation-URL normalization is not Responses support and must retain compatibility without becoming a new API selector.

### Future Responses Plan

The 2026-09-21 read-only audit found no Responses SDK calls in the current model-chat path. The pinned and installed OpenAI **1.109.1** SDK exposes Responses on synchronous/asynchronous OpenAI and Azure OpenAI clients; mocked create/parse checks passed without live inference. Semantic Kernel **1.39.4** includes Responses agent classes, but their presence does not provide a model-chat adapter or bring agents into scope. Existing hosted-agent REST Responses integrations are unchanged.

A future plan must define native input/history/instruction translation, output items, text/usage normalization, SSE events, cancellation/errors, and any supported tool exchanges. A renamed Chat Completions URL is not a Responses adapter. It must also specify supported hosts/models, version/auth policy, capability gates, request preview parity, tests, and rollout. The approved future display label is **Responses (OpenAI-compatible)**; any `responses` identifier is a future proposal, not a registered or accepted value in this release.

That plan must explicitly decide conversation-state and retention behavior. Prefer locally reconstructed history and no provider-side response storage by default; any retained response identifiers must be isolated by conversation, user/scope, endpoint, and model. No Responses state fields or continuation behavior are developed now. Agent integration, if later requested, needs its own explicit scope decision.

### Future Custom Calls Plan

A future separately reviewed design may add versioned declarative URL/body mappings, typed substitutions from approved model/conversation fields, and response/stream extraction. It must define validation, secret-reference handling, origin restrictions, payload limits, capability mapping, supported tool semantics, redaction, previews, schema migration, and audit permissions before implementation. Its scope must not implicitly include agents.

No Python/JavaScript evaluation, shell expressions, arbitrary template execution, unrestricted headers, browser-side key handling, or SSRF-policy bypass is permitted. Unknown/future types fail closed today. This release stores no executable templates or custom-call mappings and adds no route that dispatches arbitrary user-supplied bodies or URLs. The planned API path suffix and Auto/Exact controls are bounded URL composition for known operations, not custom calls.

## Implementation Plan

### Implementation Ownership

| Area | Existing owner to extend |
|---|---|
| Profile/API descriptors and identifiers | `functions_model_endpoint_providers.py`, `functions_model_endpoint_types.py` |
| Settings, migration, and safe descriptors | `functions_settings.py` and existing global/personal/group endpoint save paths |
| URL policy, outbound safety, and auth | Selectively port and extend `functions_model_endpoint_urls.py`; preserve `functions_model_endpoint_validation.py`, `functions_model_endpoint_auth.py` |
| In-scope model client and chat-service construction | `functions_model_endpoint_runtime.py`, `model_endpoint_clients.py`; preserve excluded agent callers' compatibility |
| Connection tests and chat dispatch | `route_backend_models.py`, `route_backend_chats.py`, plus the helper/background call sites identified by the implementation audit |
| Library and capabilities | `functions_model_capabilities.py`, `static/json/model_capabilities.json` |
| Endpoint UI | `templates/_multiendpoint_modal.html`, `static/js/admin/admin_model_endpoints.js`, `static/js/workspace/workspace_model_endpoints.js` |
| Model selection | `static/js/chat/chat-model-selector.js` and existing model-chat backend resolvers; no agent editor/default/override changes |

Application paths in this table are relative to `application/single_app/`. It is an ownership map, not authorization for unrelated rewrites in those files.

### Phase 0: Source Selection and Baseline

- Product decisions confirmed on 2026-09-22: use a separate Azure/Foundry Chat Completions dropdown choice sharing the OpenAI-compatible adapter, and the bounded GenAI.mil scope above. These decisions do not complete the engineering gates below.
- Confirm the `azure_openai_v1` registry key against the pinned source and Development contracts; document its shared `openai_style` adapter mapping, URL policy, identifier handling, and preservation of existing saved choices before schema changes. Completed as an audit finding below, not as runtime support.
- Use the verified main-repository `origin/paullizer-react-v2-ui` source and record its pinned version/commit; do not substitute the stale same-named fork branch. Compare the reported deployed version with the current tip when behavior differs.
- Compare the actual library asset, model helper, endpoint UI, backend, tests, and dependencies against the pinned Development baseline. Record source commit and port decision per logical change.
- Reuse code already in Development. Cherry-pick only self-contained compatible commits; otherwise port the relevant hunks with provenance. Do not use a whole-branch merge or copy obsolete runtime/security files over Development.
- Establish passing baseline tests for current Custom endpoints, routing, auth, normalization, and route policy. Confirm whether any source UI logic needs adaptation to the active editor rather than React adoption.
- Exit: reviewed port manifest, dependency ordering, confirmed selector-key mapping, agreed schema/URL semantics, and passing baseline results. Passed on 2026-09-22 after the two fixture repairs and a full rerun of the 21-script baseline below.

#### Phase 0 Evidence (2026-09-22)

**Phase 0 complete; exit gate passed.** The initial read-only audit found two pre-existing test-fixture failures. The authorized closeout repaired those tests and bumped `config.py` to **0.261.040**, with no application behavior, dependency, endpoint configuration, or database changes. See the [baseline test fix](../fixes/MODEL_ENDPOINT_BASELINE_TEST_FIX.md). The following evidence is historical Phase 0 evidence; current Phase 1 results appear below. Live-service validation has not been performed.

Provenance and execution:

- Tested HEAD: `e55022b178ac938e70c7cbf57ac02d93c5692d77` (the specification commit). At the initial audit, Git comparison confirmed `application/`, `functional_tests/`, `package.json`, and `requirements-dev.txt` matched D. The closeout rerun used that HEAD with local changes to the two test fixtures and the application version marker. Source comparisons used S throughout; no source checkout, merge, or cherry-pick occurred.
- Interpreter: VS Code/Pylance-selected `.venv/Scripts/python.exe`, Python **3.13.15**. Installed versions match the pins: OpenAI **1.109.1**, Semantic Kernel **1.39.4**, Azure AI Projects **1.0.0**, Azure AI Agents **1.2.0b6**. No package installation or SDK upgrade was needed.
- Each baseline script ran in a fresh process using `python -I -X utf8 -c <guarded-runpy-bootstrap> <test-path>` and its own `__main__` runner/exit code. Several legacy tests catch assertions and return booleans, so a generic pytest invocation would not establish their success. The token-budget script invokes its own pytest suite.
- The bootstrap disabled dotenv loading and blocked `.env`/`.env.*` reads, subprocess launches, external DNS, and non-loopback connections. Loopback remained available for Python's async event-loop machinery. No application server or live provider was contacted.
- The initial on-prem run hit the external-DNS guard (4/7 cases passed). The corrected runner supplied public `93.184.216.34` for its public-host fixture, private `10.20.30.40` for its three on-prem hostname fixtures, and `socket.gaierror` for unknown hosts. It then passed 7/7 without changing application/tests or weakening the connection guard. This initial failure was a harness issue, not an application regression.

Confirmed selector and compatibility mapping:

- Neither `azure_openai_v1` nor proposed profile key `genai_mil` occurs in D/S application or test trees. Both registries still expose only the four existing API types. Keep `genai_mil` a bounded provider/profile using generic OpenAI Chat Completions, not a new wire protocol or the Azure URL policy.
- `azure_openai_v1` will use `openai_style`, the existing model-name identifier contract (`modelName`), and the dedicated Azure/Foundry Auto/Exact rules above. A real SDK call through the existing OpenAI-style wrapper and `httpx.MockTransport` captured `/team/openai/v1/chat/completions`, the configured deployment identifier in JSON `model`, no query version, and a parsed completion. That probe verifies adapter reuse only: it used existing `openai`/Exact options and does not prove an unimplemented registry entry or schema-v2 resolver.
- Legacy records keep their saved selectors, effective versions/auth headers, and endpoint-level URL interpretation. Migration explicitly copies each effective API type/URL mode into the model; no URL/model-name inference converts an existing record to the new Azure choice. Both branches still need model-local normalization to prevent endpoint-wide identifier/version pruning.

Shared-consumer boundary:

- Language-server references confirm the synchronous builder serves model tests/settings, chat, export summaries, document processing, and workflow code. The Semantic Kernel builder serves chat helpers, tabular exports, fact-memory autosave, workflows, and `semantic_kernel_loader.py`.
- The agent loader calls that shared builder with a legacy endpoint-level context. Source runtime changes also introduce a broader connection framework and optional authorization behavior. Do not copy those changes wholesale or make schema-v2 interpretation the default for every shared caller.
- Phase 1 must preserve a legacy-default call path and explicitly opt audited model-chat/helper paths into resolved schema-v2 contracts. Migration of a record referenced by an excluded consumer must stay in legacy mode unless equivalent legacy behavior can be demonstrated. Do not silently project a mixed model record onto one endpoint-wide API type. Agent/workflow integration expansion remains out of scope; non-regression fixtures, not new support, are required at this boundary.

Initial baseline outcomes, after the on-prem harness correction: **19/21 scripts passed**. After the fixture repairs, the entire baseline was rerun with the same guards: **21/21 scripts passed**. The table shows the final closeout results.

| Baseline scripts (under `functional_tests/`) | Result |
|---|---|
| `test_model_endpoint_provider_registry.py`, `test_model_endpoint_protocol_inference.py`, `test_model_endpoint_normalization_backend.py` | 3/3 scripts passed. |
| `test_custom_model_endpoint_provider.py`, `test_custom_model_endpoint_auth.py`, `test_custom_model_endpoint_diagnostics.py`, `test_custom_model_endpoint_on_prem.py`, `test_custom_model_endpoint_synthetic_streaming.py` | 5/5 scripts passed; on-prem 7/7 cases with offline DNS. |
| `test_tabular_claude_model_endpoint_support.py` | Passed, 6/6 cases. |
| `route_tests/test_route_blueprint_policy_inventory.py`, `route_tests/test_route_unauthenticated_policy_contract.py`, `route_tests/test_route_policy_test_coverage.py` | 3/3 scripts passed (6, 4, and 2 cases). |
| `test_model_capability_catalog_resolution.py`, `test_model_catalog_token_evidence.py`, `test_model_token_budget_resolution.py` | 3/3 scripts passed (7, 36, and 51 cases). Token-budget pytest emitted an already-imported `anyio` assertion-rewrite warning. |
| `test_model_endpoint_scope_gate_enforcement.py`, `test_model_endpoint_identity_header.py`, `test_model_endpoints_key_vault_secret_storage.py`, `test_model_endpoint_management_cloud_environment.py` | 4/4 scripts passed. |
| `test_conversation_summary_model_endpoint_protocol.py` | Passed, 4/4 cases after the real identity-header helper was added to the fixture namespace. |
| `test_model_endpoint_payload_auth_type_order.py` | Passed with a function-scoped assertion matching the current payload builder. |

The two resolved pre-existing blockers and discriminating probes:

1. **Summary fixture:** `load_summary_helpers()` extracted route functions into an isolated namespace but omitted `build_model_endpoint_identity_headers`. The production route already imported the real helper; its absence in the fixture raised `NameError` in three cases. The test now imports and supplies that real helper, rather than a no-op stub. All four cases pass, as does the separate five-case identity-header suite. S's unrelated imports were not ported; no runtime workaround was required.
2. **Editor assertion:** the payload-order test searched the entire script for obsolete `provider === "aifoundry" && authType` text and found an unrelated earlier auth declaration. The actual builder declares its conditional Custom auth value before `isFoundryProvider(provider)` and AOAI checks. The repair adapts S's function-scoped assertion without changing JavaScript. In-memory negative probes confirmed that a missing local declaration and a declaration moved after validation both fail, despite earlier declarations elsewhere. This source-level check does not replace later browser tests.

The initial in-memory diagnostic probes were not counted as passing baseline scripts. The final results come from rerunning the repaired repository files. No full repository suite, source-branch suite, browser suite, live auth test, APIM inference, or GenAI.mil call was performed. Static route/scope checks are not proof of live authorization behavior. These limits remain explicit for later phases.

Dependency order and next action:

1. **Phase 0 closed:** the authorized fixture repairs, version metadata, focused checks, and all 21 baseline scripts passed in **0.261.040**. Runtime behavior is unchanged. The gate was satisfied by actual test-file repairs and a full baseline rerun, not waived by diagnostic probes.
2. **Phase 1 closed locally:** failing-first schema-v2, mixed-model, migration, malicious-path, and scoped-context cases now pass. Registry/types, the pure URL owner, normalization/validation, dual readers, and migration planning are implemented in **0.261.041**. Transport/auth integration changes still require scoped tests in Phase 3.
3. **Phase 2:** adapt the chat-relevant catalogue/schema/resolver together, preserving D's APIs; wire sanitized registry/model descriptors into both active editors and their round trips. No dependency on a React migration or excluded source packages.
4. **Phases 3-4:** integrate only in-scope runtime/helper callers, then the bounded GenAI profile/discovery/payload rules using the shared resolver and mandatory security policy. Keep optional live validation separately approved.
5. **Phase 5:** run the remaining browser, regression, documentation, versioning, and rollout gates before release. The Phase 0 findings do not authorize these implementations automatically.

### Phase 1: Contract, Migration, and Resolver

- Write table-driven tests for this spec's URL matrix, origin-first suffix insertion, required per-model Custom API type/URL Handling, identifiers, version precedence, malicious paths, legacy parity, and mixed models before changing behavior.
- Extend the registry/types, settings normalization/validation, sanitized descriptors, and authorized context resolution for in-scope contracts only. Implement the pure shared resolver and dual-reader migration; retain an internal adapter boundary without registering or dispatching Responses or custom calls.
- Retain stable IDs and secret references. Ensure capability and cache keys use the effective model routing contract.
- Exit: deterministic resolution, idempotent migration, and no regression for existing endpoint types or protected transports.

#### Phase 1 Implementation (0.261.041)

Implemented in version: **0.261.041**, recorded in `application/single_app/config.py`.
No new package, route, feature flag, catalogue asset, browser asset, or deployer change is required.

The pure `functions_model_endpoint_urls.py` owner resolves schema-v2 records into
API base, operation URL, protocol, canonical request identifier, effective versions,
credential-header policy without credential values, and bounded capabilities.
Origin-first model path composition preserves existing gateway paths. Deployment
identifiers are encoded as one segment, and deployment-family mismatches,
nonterminal/repeated deployment structures, unsafe paths, full operation bases,
unknown API types, and deferred request-template/state fields fail closed.
The existing legacy URL readers and inference helper are exported from this owner
and re-exported by `model_endpoint_clients.py`; their behavior remains unchanged.

Custom models require explicit API type and Auto/Exact values. Non-Custom models
derive missing effective fields from the existing provider contract and materialize
them during normalization. Recognized native Foundry project Messages endpoints
retain their conversion; arbitrary gateway paths do not use that conversion.
`azure_openai_v1` uses the existing `openai_style` protocol and model-name contract,
without an implicit dated query. The fifth registry descriptor is available only
when requesting schema-v2 UI options; existing editors still receive four options.

`functions_settings.py` preserves mixed model identifiers, versions, stable IDs,
secret references, budgets, and endpoint identity policy. Schema-v2 auth projection
allows only type/header/prefix metadata plus existing secret-presence flags.
Explicit blank credential prefixes survive merge. Legacy consumers of shared type
and capability helpers reject schema-v2 records unless explicitly opted in, rather
than silently selecting an endpoint-wide protocol for mixed models.
Optional schema-v2 tools, image input, and structured output require explicit
endpoint/model permission bounded by the adapter; catalogue/name inference does
not enable them. Existing legacy capability resolution is unchanged.

#### Authorized Context and Cache Contract

`build_model_endpoint_routing_context` stores only schema marker, stable endpoint
and model IDs, and scope type/ID. URLs, credentials, display names, and request-model
strings in persisted contexts are not authority.

`resolve_authorized_model_endpoint_route` requires server-owned, actor-bound
`authorize_scope` and `load_endpoint` callbacks. It checks current scope gates,
authorizes before loading, reloads saved state, requires enabled matching endpoint
and model IDs, and revalidates final API bases against current outbound policy
with DNS resolution required. It does not resolve credentials or send a request.
The loader supplies an authoritative configuration revision covering routing,
credentials/identity, transport, and policy changes. The cache key binds that
revision, scope, IDs, and effective routing contract without raw secrets.

These callbacks are integration contracts, not a new permission system or proof of
live group RBAC. Phase 3 must bind them to existing authorized stores and use the
result only through protected adapters. Existing chat/helper/agent dispatch has
not been opted into schema v2.

#### Migration and Rollback Operations

`plan_model_endpoint_routing_migration` performs a dry run and never writes settings.
Its default is blocked until a server-side audit explicitly confirms no excluded
consumer references. Only unambiguous Custom shapes are eligible automatically;
gateway paths, non-Custom records, conflicting model-version metadata, query or
fragment URLs, and other ambiguous records require owner review and remain legacy.
Endpoint/model IDs and credentials/references are retained; repeated planning of
an already normalized candidate is idempotent. Exact Messages and Gemini candidates
are checked against the real legacy URL readers.

The returned versioned backup contains the original record, including secrets.
Keep both candidate and backup server-side, use an approved secure export/storage
path before any separately authorized persistence, and never return them directly
to a browser or log them. No export endpoint or persisted migration is enabled in
Phase 1. `restore_model_endpoint_routing_backup` returns the original only when
the endpoint identity and migrated fingerprint still match, refusing concurrent
edits. Restore configuration together with old code; old binaries must not consume
mixed records. An implicit schema downgrade is rejected.

#### Phase 1 Verification (2026-09-22)

- Tests were added before their implementations. Observed failures covered the
  missing registry entry/resolver/context API, mixed-model pruning, capability
  policy, non-Custom defaults, lossy migration inputs, and duplicate deployment routes.
- All **21/21 baseline scripts** passed with the same dotenv, network, subprocess,
  and offline-DNS guards described in Phase 0. Updated focused suites passed:
  registry **9/9**, protocol **5/5 groups** including the 23-row URL matrix,
  normalization/migration **11/11**, and Custom provider/context **8/8**.
- Four fresh-process import probes passed: forward/reverse imports under normal
  and optimized Python. Real pure modules did not import settings/config/client
  runtime. The optimized probe uses explicit checks, not stripped assertions;
  it does not claim optimized assertion coverage for the entire suite.
- Pylance found existing call sites compatible with both type helpers and both
  capability helpers. Focused editor and syntax diagnostics were clean.
- Protected auth, on-prem/DNS/TLS, CA/mTLS, identity-header, Key Vault, route-policy,
  token-budget, synthetic streaming, summary, tabular, and existing agent-adapter
  behavior remained covered by the baseline. No transport implementation changed.

Limits: no full repository suite, deployed/live provider call, APIM deployment,
saved migration, or GenAI.mil validation was performed. This completes the Phase 1
foundation, not all CE-01 through CE-13 end-to-end gates. Phase 3 local dispatch is
now implemented; deployment and live verification remain pending.

### Phase 2: Endpoint Editor and Model Library

- Selectively integrate the verified source library behavior and defaults, keeping one registry-backed API type list.
- Update global/personal/group model editors with path, explicit per-model Custom API type and URL Handling, versions, safe preview, and validation; remove the new-schema Custom endpoint-default/inherit presentation.
- Propagate the fields through save/load/export/import and model-test requests; run browser tests for independent rows, save/edit round trips, scope controls, and safe rendering.
- Exit: two models under one endpoint persist distinct routing and report accurate previews; no secrets reach non-admin browser payloads.

#### Phase 2 Implementation (0.261.042)

Implemented in version: **0.261.042**, recorded in `application/single_app/config.py`.
Refs [#1518](https://github.com/microsoft/simplechat/issues/1518).

The shared local `static/js/model_routing_editor.js` module supplies independent
model controls to the existing global, personal, and group editors. New Custom
rows save explicit API Type, URL Handling, API Path, canonical request identifier,
and applicable protocol version. Non-Custom rows expose API Path and retain their
provider contract. Schema-v2 Custom editors hide the endpoint-wide API selectors;
legacy records retain their previous editor and are not automatically migrated.
Existing capacity, icon, identity-header, enabled-state, and credential-reference
behavior is retained. Explicit auth header/prefix overrides, including a blank
prefix, survive edits. Existing JSON serialization, normalization, and authorized
secret merge preserve mixed model records without adding an export/import API.

**Preview Route** uses `preview_only: true` on the existing global/user/group
model-test routes. Existing login, role, group ownership, scope, and governance
checks remain authoritative; existing IDs require an authorized lookup. The
structural draft contains no auth object. The response contains only method,
resolved URL/base, protocol, request identifier, and effective versions. Preview
does not resolve secrets, perform DNS/network checks, construct a provider client,
or call inference. Server-side save validation remains responsible for outbound
policy. Invalid routes and duplicate request-identifier/URL pairs block the save.
Edits, row additions/removals, and modal closure invalidate pending validation.
Errors are safely rendered inside the modal rather than replacing its contents.

Schema-v2 live **Test Connection** now resolves the saved endpoint/model route,
rechecks governance and personal/group scope, compares submitted route fields with
saved values, and rejects stale edits before dispatch. An authorized one-off test
can run before activation; it may incur provider usage charges. Preview remains
network-free. Newly created endpoints still start disabled and require explicit
activation for chat. Existing legacy endpoint tests and dispatch retain their
compatibility behavior. Persist feature/scope enablement before testing. Global
**Save Endpoint** changes the settings form; the main settings save persists it.

#### Selective Library Integration

Source S remains `3f896d7b6c45800c593599f3100b9aa7c7251159`. Its defensive-copy
behavior is adopted for catalogue records, while Development's full-document
loader API and audited **75-record** catalogue/token evidence remain intact.
The source's **113-record** catalogue is not copied wholesale: image/embedding
entries are outside scope, and additional chat records lack the complete token
evidence and metadata required by Development's schema. No source-only dependency,
Responses image profile, reasoning-policy expansion, or indexed-loader API change
is introduced.

`editorRoutingProfiles` adds registry-validated editor suggestions without changing
numeric capacity or capability evidence. The browser receives only chat-relevant
IDs, display names, publisher/lifecycle, routing suggestions, and provenance.
Selecting a library entry sets `catalogModelId`; a new Custom row may visibly adopt
the suggested API type/mode and fill blank identifiers. Existing explicit API
choices, identifiers, paths, capabilities, and capacity overrides are not replaced.
Library selection is not evidence that a particular gateway supports that protocol.

#### Phase 2 Verification and Deployment Check

- `ui_tests/test_model_endpoint_capacity_editor.py`: the final **50/50** cases
  passed, including the nine-case stale-save matrix with row-mutation protection.
  Coverage includes all three scopes, mixed protocols, save/reopen,
  legacy records, library precedence, non-Custom paths, secret-free previews,
  hostile text, desktop/mobile layout, keyboard access, and rejected saves.
- All **21/21 baseline scripts** passed with the Phase 0 isolation guards, including
  routing, normalization/JSON round trips, auth, identity headers, Key Vault,
  catalogue/token evidence, scope gates, and route policy. The preview test forbids
  secret resolution and provider dispatch and checks denied/disabled scopes.
- Documentation coverage/site-quality checks passed **13/13**, with the generated
  application-surface inventory still current. Registry labels distinguish API
  protocols without changing persisted selector values or legacy routing.
- No live provider, deployed RBAC, APIM inference, Azure browser service, persisted
  migration, or full repository suite was run. Local Playwright used mocked APIs
  and real local assets; its preview fixture calls the actual pure resolver.

In a deployed nonproduction instance, persist multi-endpoint and applicable
workspace enablement. Create a disabled endpoint with two configured models,
compare previews, save/reopen, then run **Test Connection** against each saved
route. Since **0.261.046**, explicit Enable/Disable controls are available in all
three editors; new endpoints still start disabled. Persist global changes with
the main settings save, and use only new nonproduction records for live testing.
Keep production legacy records unchanged. **The current local tests use mocked
providers; they do not verify a live APIM deployment.** Agents and GenAI.mil remain
outside this implementation.

### Phase 3: Runtime and Model Chat

The runtime/model-test/helper integration is implemented locally in **0.261.046**.
Deployment validation and signed-in beta acceptance remain pending. Local
regressions do not replace an actual APIM request comparison with the preview.

- [x] Wire saved schema-v2 model tests and explicitly selected non-agent model chat to the shared route resolver; reject explicit agent selections and preserve legacy fallback for agent default selection.
- [x] Wire summary generation, metadata extraction, multimodal vision tests, and chat-owned queued helpers through saved endpoint/model IDs and scoped reauthorization. Endpoint URLs and secrets are not serialized in schema-v2 background routing context.
- [x] Reuse OpenAI-compatible, Azure deployment, and Messages adapters with captured mock requests for resolver-matched operation URLs. Deferred Responses/custom calls remain unregistered and rejected.
- [x] Wire Direct Model workflows and both deferred tabular handoffs to saved scoped contexts; enforce feature/item governance before endpoint-store reads and recheck group membership.
- [ ] Complete end-to-end workflow/helper acceptance beyond isolated function and adapter tests; verify saved-context owner binding, scoped credential sources, and policy changes between queued work and execution.
- [x] Allow deliberate activation/deactivation in admin/personal/group editors while new records remain disabled by default; preserve legacy records and agent-default fallback.
- [x] Enforce resolved identity and capabilities at sync/async dispatch, bind queued export contexts to their verified run owner, use saved routing for tabular budgets, and cover Messages cleanup before/during streaming and cancellation.
- [ ] Complete streaming/request-body/capability and state/cancellation coverage for all in-scope consumers, plus deployed nonproduction validation.
- Exit: actual captured request URLs/headers/bodies match previews for model chat and in-scope helpers across the supported contracts. Deferred and unsupported combinations fail clearly before outbound dispatch; shared changes preserve existing excluded consumers.

#### Phase 3 Continuation (2026-09-25)

Fixed/Implemented in version: **0.261.045**, recorded in `config.py`.
Source, tests, and docs remain local and uncommitted on `feature/customendpoints`.
No deployment, commit, push, or issue update was performed in this continuation.
The separate publisher work, unrelated identity-binding specification, and local
browser artifacts remain outside the runtime work.

The four workflow failures at the previous checkpoint are resolved. The workflow
mock now accepts `include_context`; the legacy protocol fixture uses the existing
isolated runtime loader with restored modules; the historical version assertion
uses `assert_app_version_at_least`.

Regression-backed corrections include pre-read feature/item governance for every
workflow endpoint scope, current group membership checks, stable allowlisted
contexts for both deferred tabular handoffs, and avoiding an unused synchronous
client during context-only resolution. The real chat wrapper now accepts and
forwards TLS policy; model tests and summaries read the canonical plaintext-policy
key; vision testing supplies the authenticated actor; actual agent default
requests preserve legacy fallback without opting agents into schema v2.

Validation: **149 tests passed** across 20 explicit endpoint, workflow, tabular,
settings, auth, and streaming test files under deployment-environment-file and
external-socket guards. Only Python's internal Windows asyncio socketpair was
allowed through the socket guard. The directly changed seven suites also passed
**46/46** after the final version and agent-fallback changes. Earlier checkpoint
results were 53 browser cases, 12 route-policy checks, and 13 documentation checks;
these are not evidence of a full live workflow.

A guarded repository-wide collection attempt failed on app-bootstrap/import
conflicts, including test-injected modules missing `build_safe_csv_headers` and
`TABLE_EXPORT_REQUEST_MARKERS`. There is no full-suite pass. Do not load `.env`
or run live services merely to make collection succeed.

Next: finish the open capability, streaming/body/header, cancellation, context
ownership, and activation acceptance gates above, then run a controlled
nonproduction APIM comparison with Preview Route. No provider calls were made by
the tests. See [workflow handoff repairs](../fixes/SCHEMA_V2_WORKFLOW_HANDOFF_FIX.md).

#### Phase 3 Runtime Hardening (0.261.046)

Fixed/Implemented in version: **0.261.046**, recorded in `config.py`.
Failing-first regressions demonstrated and now guard these gaps:

- Saved global endpoints selected through personal/group test routes retain their verified credential scope.
- Sync and async schema-v2 clients reject unsupported tools, images, structured output, streaming, and request-model substitutions before inference. Each client holds an isolated copy of the resolved policy. Messages settings are checked before translation can drop unsupported options.
- Queued export model/chunk contexts cannot impersonate a different run owner or personal scope. Actor-less contexts bind to the conversation owner only after the existing ownership check. Legacy contexts retain their compatibility path.
- Tabular budgets use the authorized request model/protocol and saved limits rather than stale context overrides or model-name inference. Metadata extraction forwards the canonical plaintext and CA settings.
- Messages streams own their response/client even before the first chunk. Early close, parser failure, in-flight-read cancellation, and streams arriving after cancellation release resources. A canceled synchronous read is not force-killed; cleanup occurs when it finishes within the existing transport timeout.
- Explicit activation/deactivation is covered in all three browser scopes. New endpoints remain disabled, and legacy records are not migrated. Agent requests retain their existing default fallback.

Final validation: the expanded 22-file guarded selection passed **235** tests
(47 warnings), with deployment environment reads and external sockets blocked.
Run this selection from the repository root; a wrong-directory attempt was
blocked by the dotenv guard and was rerun without weakening the guard. The
editor suite passed **53/53** in local Chromium with mocked APIs, both changed
JavaScript syntax checks passed, documentation checks passed **13/13**, and
route-policy checks passed **12/12**. Editor diagnostics were clear. Existing
repository-wide collection conflicts remain a disclosed limitation; this is not
a full-suite or cold-bootstrap pass.

Beta preflight is blocked: the current Azure CLI context is AzureCloud with the
recorded beta subscription, but direct reads of both `simplechat2026betaacr` and
`simplechat-2026beta-app` return **AuthorizationFailed**. Resource Graph also
returns no matches across accessible subscriptions; do not interpret that as
proof of deletion. The read-only publisher preview stopped before any ACR build.
No image was pushed, no webhook was triggered, and no application settings,
credentials, role assignments, or Azure context were changed. Restore beta access
or use the intended signed-in account, then re-run preflight and record the
previous digest before publishing. Signed-in APIM/AOAI tests remain outstanding.
No commit, push, release-note edit, or issue comment was made in this continuation.

#### Beta Live Test Decisions (2026-09-25)

- Target: beta, `simplechat-2026beta-app` in `simplechat-2026beta-rg`, using `simplechat2026betaacr`. Do not deploy to dev or production as part of this validation.
- The user will exercise Foundry Claude and GPT through APIM, plus AOAI. Record each tested route's actual API type and URL mode; a model name alone does not identify its wire protocol. Do not assume all API-type combinations are covered by these deployments.
- Finish the remaining local Phase 3 runtime/security and activation gates before publishing for live testing. Use the existing remote ACR build/webhook workflow; record the new and previous image digests and retain configuration backups for rollback.
- Use new test records and synthetic prompts. Preserve existing legacy records and keep credentials in approved application/Key Vault settings. Compare Preview Route with the actual request URL and safe header/body metadata without logging credentials or sensitive content.
- Agents remain excluded. This work must not introduce agent routing through APIM or change existing agent configurations; preserving compatibility is not an expansion of agent support.
- UI refinements and the CA bundle manager below are deferred until after Phase 3; they do not block this beta runtime test. Existing TLS and outbound-network protections remain mandatory.
- GenAI.mil cannot be tested live by the current tester. Keep its named integration in Phase 4 and report live verification as unavailable, not passed. Beta results for Foundry/APIM or AOAI do not establish GenAI.mil compatibility.

#### Post-Phase 3 Follow-Up: Endpoint Usability and CA Bundles

Recorded from the lead's review and the user's deferral on 2026-09-25. These are
historical pending work items. They are implemented in **0.261.052**, not changes
to Phase 3's live acceptance requirements. See
[shared CA bundles](./CUSTOM_ENDPOINT_CA_BUNDLES.md) and
[the GenAI.mil profile](./GENAI_MIL_MODEL_PROFILE.md).
Complete Phase 3 runtime validation first; implement the editor refinements and
CA registry as separately testable increments afterward. Track with issue #1518.

- [ ] Move advanced Custom endpoint network/trust controls after the endpoint configuration. Retain admin-controlled private-host and plaintext-HTTP opt-ins, their dependency, secure defaults, and existing blocked-address protections.
- [ ] Replace the user-entered global CA path with an admin-managed expandable CA bundle table: add/upload PEM certificates, give bundles friendly names, edit/replace, list multiple bundles, and delete unused bundles. Show certificate fingerprints, expiry information, and references. Endpoint editors select a stable bundle ID or public certificate authorities rather than a filesystem path.
- [ ] Design durable shared CA storage, authorization, certificate-only validation, upload limits, audit history, revision-based client refresh, and deletion/reference protection across endpoint scopes. Reject private keys and preserve hostname verification. Migrate existing path configurations without silent trust changes: today's supplied bundle replaces public roots, rather than extending them. Validate replacement, restart, scale-out, and sync/async consumers before rollout; do not use ephemeral container files as the source of truth.
- [ ] Clarify API Path as an optional additional gateway prefix, inserted after the origin and before the endpoint's existing path. Add accessible explanatory controls and make the resolved request preview prominent. Clarify Automatic as the default protocol-based composition, and Exact as the configured API base plus the known operation. Neither mode requires an additional API Path, and Exact is not an arbitrary full-request URL. Preserve persisted values and the agreed routing contract.
- [ ] Clarify required request model/deployment identifiers versus optional catalog model selection. Preserve Manual entry, do not overwrite entered identifiers or explicit API types, and do not infer a mismatch from an arbitrary deployment alias. Use verified metadata for suggestions; avoid filling Azure deployment aliases from publisher IDs. Remove duplicate editable catalog identity controls while preserving saved values.
- [ ] Make model capacity primary, rename endpoint capacity to Default model limits, and collapse endpoint defaults. Display effective values and their source. Preserve per-field precedence of model override, endpoint default, then verified catalog value; do not turn endpoint defaults into hard overrides. Keep Response Length distinct from capacity and throughput quotas.
- [ ] Extend existing global/personal/group browser and regression coverage, update admin/user documentation and the generated surface inventory where applicable, and verify the CA transport changes independently before deployment. No automatic migration or agent integration is implied by these follow-ups.

### Phase 4: GenAI.mil

GenAI.mil implementation is complete locally in **0.261.052**, with live
verification still unavailable. It is separate from Phase 3, not removed from the overall plan and not
excluded because of a protocol mismatch. The supplied documentation maps its
inference to the existing `openai` Chat Completions contract, using
`https://api.genai.mil/v1` and bearer-key authentication. Reuse that adapter rather
than adding a new wire protocol. Generic Custom configuration alone is not proof
of complete GenAI.mil support: the named profile must constrain request fields,
capabilities, discovery, and error handling to the documented service contract.
The current tester has no live access; implement and validate locally with mocks,
then retain an explicit live-verification gap until an authorized tester is
available. Do not register a selectable unfinished profile or claim live support
from the beta APIM/AOAI tests.

- Add the named provider profile, bearer-key defaults, documented request filtering, and scoped backend model discovery.
- Add safe locked-key handling, nullable usage, and bounded rate-limit behavior. No automatic unlock or speculative Messages/Responses support.
- Validate with mocks first; perform an opt-in live smoke test only with approved access, approved test content, a user-configured key, and acceptance of token costs. Do not claim live certification from mocks.
- Exit: discovery, streamed/non-streamed model chat, error cases, governance, and rejection of unsupported tool requests verified. Record live access blockers separately from local results.

### Phase 5: Release and Rollout

- Complete the acceptance suite below, scoped route/security tests, and existing regression suites for impacted consumers; run required browser checks, Python diagnostics, JavaScript syntax checks, and whitespace checks.
- Update the feature/auth docs, AI models admin reference, model-chat guidance, and capability inventory when affected. Regenerate `docs/_data/app_surface.yml` if the documented surface changes, then run docs coverage/site-quality tests.
- At code delivery, increment `config.py`'s patch segment and align functional-test headers/implementation docs. Ask before updating release notes and the associated issue. No deployer version change unless deployer files actually change.
- Pilot explicit models before bulk migration; review diagnostics without logging secrets, retain rollback exports, and promote only after gates pass. Publishing a branch, PR, or deployment is a separate action.

## Acceptance and Test Matrix

| ID | Acceptance criterion | Verification |
|---|---|---|
| CE-01 | Exact Development/source revisions and selected source changes are recorded; no unrelated React migration or security downgrade. | Git diff and port-manifest review. |
| CE-02 | Every model supports blank/single/multi-segment suffixes inserted immediately after the origin and before the remaining endpoint/API path; existing path segments survive in order. | URL matrix plus leading/trailing slash, nonempty endpoint path, and multi-segment insertion tests. |
| CE-03 | A single Custom endpoint preserves separate Azure deployment, Azure/Foundry Chat Completions, generic OpenAI-compatible Chat Completions, and Messages choices; each model explicitly stores its choice and URL Handling without endpoint inheritance or model-name heuristics changing them. | Settings and editor round trips; missing-field rejection; mixed Auto/Exact models; Claude-name/OpenAI and GPT-name/Messages negative heuristic tests; existing compatible-profile parity; shared OpenAI-compatible adapter mapping for both Chat Completions choices. |
| CE-04 | Identifiers and protocol versions belong to the selected model; Azure/Foundry sends its identifier in JSON without a deployment path or implicit dated query; configured path versions are distinct from dated headers/queries; no duplicate structural suffix or query injection. | Captured requests for both Azure choices, wrong-deployment/incompatible-base rejection, mixed-version tests, synthetic `/v2/messages` path preservation without inferred new wire-format support. |
| CE-05 | Messages APIM prefixes survive while native Foundry project conversion and legacy exact/Gemini routes retain parity. | Regression tests covering both old and new schema modes. |
| CE-06 | Test-model, model chat, and non-agent helper/background calls agree on request resolution and recheck scope; shared changes do not opt agents into new routing. | Consumer integration tests, removed/disabled model, group-revocation and stale-context cases; existing agent non-regression tests where shared code changes. |
| CE-07 | Routing/policy and adapter dispatch remain separable for future additions, but Responses and custom calls have no registered type, selectable UI, persisted feature configuration, or outbound dispatch in this release. | Architecture review of existing boundaries; registry/editor absence checks; save and dispatch rejection tests with zero outbound requests and no silent Chat Completions fallback. |
| CE-08 | Global/personal/group editors preserve independent model choices and show accurate, safe previews. | Browser tests including hostile labels/path text, secret absence, and save/edit round trips. |
| CE-09 | GenAI.mil uses `/v1/chat/completions`, bearer-key auth, `/v1/models`, nullable usage, and documented-only payload options. | Mock transport assertions plus optional approved live smoke. |
| CE-10 | Locked keys require user action, model denial is distinct, and rate limits do not cause unbounded retries or replay. | 401/403/404/429/502 fixtures, hostile unlock URL, mid-stream failure, and cancellation. |
| CE-11 | New paths/adapters cannot bypass SSRF, TLS, auth, Key Vault, identity-header, or scope policy. | Encoded-path/host-override tests, pinned DNS, redirect refusal, header precedence, secret-redaction, and unauthorized-access tests. |
| CE-12 | Legacy configuration migration is idempotent and reversible; mixed records cannot be silently downgraded. | Migration/backup/restore fixtures with unchanged stable IDs and secrets. |
| CE-13 | Unsupported capabilities and future arbitrary body/URL options are rejected rather than dispatched; Messages-compatible hosts do not inherit every Anthropic feature. | Restricted compatible-host and no-tool model fixtures, undocumented GenAI capability tests, unknown API-type rejection. |

Extend the nearest existing tests before creating new files: `test_model_endpoint_protocol_inference.py`, `test_model_endpoint_normalization_backend.py`, `test_model_endpoint_provider_registry.py`, `test_custom_model_endpoint_provider.py`, `test_custom_model_endpoint_auth.py`, `test_custom_model_endpoint_diagnostics.py`, `test_custom_model_endpoint_on_prem.py`, `test_custom_model_endpoint_synthetic_streaming.py`, `test_conversation_summary_model_endpoint_protocol.py`, `test_tabular_claude_model_endpoint_support.py`, and existing endpoint UI tests. Run existing agent tests only as non-regression coverage where shared behavior is affected, not to add agent support. Add deferred-type rejection cases to existing validation tests, not a Responses/custom-call implementation suite. New GenAI fixtures are justified only where no coherent existing home exists.

For route changes, run the policy inventory, unauthenticated contract, and policy-coverage tests in `functional_tests/route_tests/`. Keep setup and stateful operations outside assertions, restore all mocks/environment changes, and block network calls in local regression tests. A test that only examines source strings is not sufficient proof of outbound behavior.

## Decisions and Open Questions

- Source identity is resolved: use `microsoft/simplechat`'s `paullizer-react-v2-ui` branch. The stale fork comparison is superseded. Confirm the exact deployed commit only if reproducing version-specific UI behavior requires it.
- Confirmed UI decision (2026-09-21): Custom models explicitly store API type and URL Handling alongside their API path suffix. No endpoint default or model inheritance for the new schema; legacy values are retained only for compatibility and explicit migration.
- Confirmed suffix placement (2026-09-21): insert the model's entire API suffix immediately after the origin and before the endpoint's remaining path/API route. API type chooses the library/calling contract, not the model vendor or a mandatory vendor-named URL segment.
- Confirmed API-type meaning (2026-09-21): API type selects the library/calling and wire-format contract, independently of the model vendor. Messages-compatible endpoints can serve non-Anthropic models; versioned paths alone do not establish schema compatibility.
- Confirmed display naming (2026-09-21): **Messages (Anthropic-compatible)** for the in-scope adapter and **Responses (OpenAI-compatible)** for future planning only. These name compatibility contracts, not vendor restrictions. Keep legacy `anthropic`; do not register the proposed future `responses` identifier. Provider/profile stays separate.
- Confirmed Azure API presentation (2026-09-22): separate **Chat Completions (Azure/Foundry)** choice sharing the existing OpenAI-compatible adapter. The schema-v2 descriptor, editor, URL policy, and local dispatch are implemented. Preserve existing choices rather than inferring migration from URLs.
- Phase 0-2 closeout: test-fixture repairs and route foundation are in **0.261.040/0.261.041**; editor/library/preview work is **0.261.042** and pushed to draft PR #1514. Phase 3 runtime work is local in **0.261.044**; no live Azure validation or deployment has occurred.
- Confirmed future-work decision (2026-09-21): Responses and custom calls are excluded from current development and belong in separate future plans. Keep existing routing/adapter/policy boundaries extensible, but add no dormant feature implementation, selectable option, persisted mappings, or dispatch for either.
- Confirmed agent scope (2026-09-21): agent changes are excluded. Preserve existing integrations and compatibility; new model-routing work does not authorize agent defaults, overrides, selectors, or tool-loop changes.
- Confirmed GenAI.mil scope (2026-09-22): named SimpleChat provider integration with model discovery and Chat Completions only, including streaming and documented authentication/error handling. Messages, tools, vision, structured output, and Responses remain excluded. No claim of vendor endorsement, live certification, or approval for particular data.
- No implementation, API migration, cloud changes, commits, or pushes are authorized by this planning artifact alone.

## Related Documentation

- [Existing Custom provider](CUSTOM_MODEL_ENDPOINT_PROVIDER.md)
- [Existing Custom authentication](CUSTOM_MODEL_ENDPOINT_AUTH.md)
- [Custom endpoint diagnostics](../fixes/CUSTOM_MODEL_ENDPOINT_DIAGNOSTICS_FIX.md)
- [Contribution workflow](../../../CONTRIBUTING.md)