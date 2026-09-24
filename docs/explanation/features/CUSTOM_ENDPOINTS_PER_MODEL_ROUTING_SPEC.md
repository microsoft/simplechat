# Custom Endpoints: Per-Model Routing and GenAI.mil

## Status and Version

- Status: proposed specification and implementation plan; no runtime implementation in this change.
- Date: 2026-09-21.
- Baseline application version: **0.261.039**, from `application/single_app/config.py`.
- Implemented in version: **Not implemented**. Assign the implementation version and increment only the third version segment when code changes land. This documentation-only change does not increment the version.
- Working branch: `feature/customendpoints`, created from refreshed `origin/Development`.
- Baseline commit: `f1be106ec2088cf9105293a7b1dac16e668e2685`.
- Source reviewed: [Paullizer's React v2 branch in the main repository](https://github.com/microsoft/simplechat/tree/3f896d7b6c45800c593599f3100b9aa7c7251159), `origin/paullizer-react-v2-ui`, commit `3f896d7b6c45800c593599f3100b9aa7c7251159`, version **0.261.126** at inspection. The user identified the deployed UI as **0.261.123**; pin the source commit rather than assuming the deployed UI is the latest branch tip.
- Associated issue: not yet assigned. Existing Custom endpoint work references #1222; this proposal must not imply that issue already covers the new scope.

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

### Initial Port Manifest

| Surface | Reviewed evidence | Planned disposition |
|---|---|---|
| Model capability catalogue | `application/single_app/static/json/model_capabilities.json` contains 75 records on Development and 113 on the correct pinned source; the catalogue schema also differs. | Review and port the relevant source catalogue/schema changes together with capability tests. Record counts alone are not a compatibility check. |
| Capability resolver | Both branches contain `functions_model_capabilities.py`; the source includes additional model reasoning/vision resolution tests. | Reconcile resolver changes with the expanded catalogue and explicit model/profile restrictions. Preserve model budget and override precedence behavior. |
| Selection identity | Endpoint/model/provider identity must survive the active endpoint UI and model-chat paths. A React picker helper is not the Custom protocol registry. | Audit source identity behavior against Development and port needed invariants/tests without adopting React, changing agent selection, or introducing silent endpoint fallback. |
| Custom registry/auth/validation/diagnostics | Present and modified on the correct source, with additional Custom foundation and diagnostics coverage. | Selectively port required changes and tests, preserving outbound safety, secret handling, and governance. |
| Pure URL contracts | Source adds `functions_model_endpoint_urls.py`, including Custom OpenAI and Azure deployment base resolvers. | Reuse and extend this module for per-model path composition and the in-scope Chat Completions and Messages contracts; avoid inventing a parallel resolver. Test its Exact behavior and suffix parsing against this spec. |
| Endpoint editors, runtime, and clients | The correct source contains modified runtime/client/editor code, URL Handling controls, and editor integration tests. | Port relevant foundation/editor changes at function/component level with provenance. Identify which requested behaviors already exist before implementing the remaining delta. |

## Goals and Scope

1. Reuse relevant model-library and Custom endpoint work from the verified source, preserving provenance and tests.
2. Give each model an optional multi-segment **API path suffix**, including models on existing endpoint providers.
3. Give each Custom model an authoritative **Model API type** for Azure OpenAI deployment-style Chat Completions, OpenAI-compatible Chat Completions, or Messages (Anthropic-compatible), preserving existing compatible profiles such as Gemini. Explicit Azure/Foundry Chat Completions presentation remains under review below. Responses is deferred.
4. Support mixed protocols and paths under one Custom endpoint, with independent identifiers and protocol-specific versions.
5. Make saved configuration, test-model, interactive model chat, and its non-agent helper/background calls use the same resolved routing contract.
6. Add **GenAI.mil** as a first-class, named endpoint provider/profile using its documented OpenAI-compatible API.
7. Preserve existing configurations and security boundaries; provide a reversible migration path.
8. Keep routing, protocol adaptation, and policy boundaries suitable for future Responses and custom calls, without developing either feature in this release.

In scope: global, personal, and group endpoint editing; model-library metadata; model selection; configuration normalization; model-chat streaming and existing supported tool behavior; capability gates; GenAI.mil model discovery; documentation and regression coverage.

Out of scope: Responses model inference; custom calls (custom request bodies, URL templates, or arbitrary HTTP dispatch); agent integration or behavior changes; a React UI migration; unrelated source-branch features; new embedding/image/audio APIs; automatic key unlock; GenAI.mil key provisioning; and changes to APIM policies or live deployments. Existing supported capabilities must not be removed. Responses and custom calls require separate future plans and explicit implementation approval.

Agent scope boundary: preserve existing agent behavior and configuration. Do not wire new routing modes into agent defaults, overrides, selectors, hosted-agent integrations, or tool loops. Shared helper/settings changes must not silently opt agent consumers into schema-v2 routing; retain their compatibility path and verify non-regression where shared code is touched. Any boundary that cannot preserve that behavior is a scope blocker, not permission to extend agent support.

## Configuration Contract

### Endpoint and Model Responsibilities

| Owner | Proposed fields and behavior |
|---|---|
| Endpoint | Stable `id`, provider/profile, enabled state, base connection URL, auth and Key Vault references, and identity-header policy. Credentials remain endpoint-scoped. No inherited URL Handling setting for schema-v2 Custom models. |
| Model | Stable `id`, display metadata, existing model/deployment identifier, enabled/capability settings, `api_path`, explicit `api_type` and `url_mode` for Custom models, `api_version`, and `anthropic_version` where applicable. |
| Library/profile | Defaults, supported protocol options, URL policy, credential header defaults, and verified capabilities. Metadata is not permission to invoke a model. |

New endpoint records use `routing_schema_version: 2`. New Custom model records persist explicit `api_type` and `url_mode` values; missing and unsupported values are rejected on new saves. Library suggestions must become visible, saved model values, not runtime inheritance from an endpoint default. Existing records without the marker use the compatibility reader until explicitly migrated. Field names here are proposed contracts, not implemented fields.

`api_path` defaults to an empty string and is the gateway API suffix. For schema v2, insert its complete segment sequence immediately after the origin (scheme, host, and optional port), before the endpoint's remaining path and the API-specific route: `origin / model API suffix / endpoint path / protocol route`. The suffix may contain multiple segments; "first level" describes its insertion point, not a one-segment limit. API type selects a calling adapter, not a literal path segment bearing a provider name.

A new gateway configuration should use the origin as its endpoint URL and put model-specific prefixes into `api_path`. If an endpoint contains an API base such as `/openai/v1`, the suffix goes before it: endpoint `https://gateway.example/openai/v1` plus suffix `team` produces an API base of `https://gateway.example/team/openai/v1`. Preserve the endpoint path's segment order; do not drop it, append the suffix after it, or deduplicate arbitrary repeated segments. Legacy records retain their old composition until explicit migration; ambiguous existing gateway prefixes require owner review.

Per-model versions take precedence over compatible legacy endpoint versions. Do not remove one model's deployment identifier or version because another model uses Messages or OpenAI. Changing a model API type requires the new identifier/version fields to validate; do not silently substitute a display name or reuse an unrelated identifier.

### Model API Types

| UI label | Persisted value | Identifier | Native operation and version behavior |
|---|---|---|---|
| Azure OpenAI (Deployments) | `azure_openai` | `deploymentName` | `chat/completions` beneath `openai/deployments/{deployment}`; requires an approved `api-version`. |
| OpenAI API (Chat Completions) | `openai` | `modelName` | `chat/completions` beneath the API base; model in JSON; no implicit dated query version. |
| Messages (Anthropic-compatible) | `anthropic` | `modelName` | `messages` beneath the API base; Anthropic-compatible Messages request, response, and event contract, independent of model vendor; applicable `anthropic-version` header. |

Review requirement (2026-09-21): explicitly distinguish deployment-style Azure OpenAI calls from Azure/Foundry OpenAI Chat Completions using `/openai/v1/chat/completions`. The latter uses the Chat Completions calling contract, not Responses and not the deployment-in-path contract. Preserve generic OpenAI-compatible connections, including GenAI.mil; decide whether the Azure/Foundry distinction is a separate API choice or a labeled URL/profile preset before changing persisted values or normalization rules.

Confirmed deferral (2026-09-21): Responses is not a selectable or executable model API type in this release. Keep **Responses (OpenAI-compatible)** as an approved future label only; do not add a registered `responses` type, saved model option, adapter, or provider-side continuation state. Treat attempted unsupported API types as validation errors, never as a reason to fall back to Chat Completions. See the future-work section for Responses and custom calls.

API type selects the library/client method and its wire-format adapter, including request bodies, response blocks, streaming events, and tool exchanges. It is not inferred from the model family, provider name, or an operation called `messages`. A different API with a `/messages` route but incompatible schemas is not supported by this adapter; it would need a separately reviewed adapter rather than arbitrary body/URL handling.

Provider/profile, model vendor, URL path version, and wire contract are separate concepts. A configured `/v2/messages` path may use the same compatible contract through a gateway, but its spelling does not prove compatibility with a future protocol revision. Do not invent v2 schemas or silently change adapters. `anthropic_version` represents the protocol's dated header where required, not the `v1`/`v2` path segment; Azure's dated `api-version` query is likewise distinct. Endpoint/profile authentication remains authoritative and may differ between compatible hosts.

#### Non-Anthropic Messages Evidence

Official documentation inspected on 2026-09-21 demonstrates that Messages compatibility is not limited to Anthropic models:

- [Ollama Anthropic compatibility](https://docs.ollama.com/api/anthropic-compatibility) documents `/v1/messages`, an Anthropic SDK example using `qwen3-coder`, and `gpt-oss:20b` among recommended local models. Ollama explicitly supports a subset of the Anthropic API; examples include unsupported `tool_choice` and prompt caching. Its direct cloud endpoint requires bearer authentication rather than `x-api-key` alone.
- [MiniMax Anthropic SDK compatibility](https://platform.minimax.io/docs/api-reference/text-anthropic-api) documents calling MiniMax models, including the M2 series, with `client.messages.create`. Its compatibility table describes supported, partial, and ignored parameters rather than identical behavior for every model and field.

These are evidence for vendor-independent adapter selection, not a claim that SimpleChat has validated these hosts/models or a commitment to add named provider integrations. Test each enabled feature against the actual gateway/model contract. A shared adapter with capability restrictions is sufficient; no model-vendor-specific protocol inference or generic request engine is required.

Keep existing persisted `anthropic` values rather than renaming records to `messages`. Preserve existing Gemini OpenAI-compatible configurations/profile metadata; an editor migration must not coerce their `/v1beta/openai` paths or capabilities to generic OpenAI defaults.

For non-Custom providers, show the path field and the effective protocol; retain provider-specific behavior for legacy records. Any migration to explicit routing must preserve the previous working wire contract. GenAI.mil offers only its verified OpenAI API type in the initial release. It does not inherit every Custom protocol simply because it uses the shared registry.

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

For schema v2, **Exact** means use the composed API base as given, without adding a version or Azure deployment prefix; append only the known operation. It does not mean arbitrary full-request URLs. Azure Exact bases must already include the `openai/deployments/{deployment}` path and agree with the selected deployment. Legacy exact Messages operation URLs are interpreted by the compatibility reader, not changed silently to this new base-URL meaning.

Automatic mode applies the selected protocol's structural rules after composing origin, model `api_path`, and endpoint path in that order:

- OpenAI-compatible Chat Completions: append `/v1` when the base has no recognized terminal version segment; preserve terminal `v1`, `v1beta`, or another supported version and registered as-given profiles such as Gemini.
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

- Use the verified main-repository `origin/paullizer-react-v2-ui` source and record its pinned version/commit; do not substitute the stale same-named fork branch. Compare the reported deployed version with the current tip when behavior differs.
- Compare the actual library asset, model helper, endpoint UI, backend, tests, and dependencies against the pinned Development baseline. Record source commit and port decision per logical change.
- Reuse code already in Development. Cherry-pick only self-contained compatible commits; otherwise port the relevant hunks with provenance. Do not use a whole-branch merge or copy obsolete runtime/security files over Development.
- Establish passing baseline tests for current Custom endpoints, routing, auth, normalization, and route policy. Confirm whether any source UI logic needs adaptation to the active editor rather than React adoption.
- Exit: reviewed port manifest, dependency ordering, and agreed schema/URL semantics. Source identity is resolved; detailed selective-port review remains an implementation gate.

### Phase 1: Contract, Migration, and Resolver

- Write table-driven tests for this spec's URL matrix, origin-first suffix insertion, required per-model Custom API type/URL Handling, identifiers, version precedence, malicious paths, legacy parity, and mixed models before changing behavior.
- Extend the registry/types, settings normalization/validation, sanitized descriptors, and authorized context resolution for in-scope contracts only. Implement the pure shared resolver and dual-reader migration; retain an internal adapter boundary without registering or dispatching Responses or custom calls.
- Retain stable IDs and secret references. Ensure capability and cache keys use the effective model routing contract.
- Exit: deterministic resolution, idempotent migration, and no regression for existing endpoint types or protected transports.

### Phase 2: Endpoint Editor and Model Library

- Selectively integrate the verified source library behavior and defaults, keeping one registry-backed API type list.
- Update global/personal/group model editors with path, explicit per-model Custom API type and URL Handling, versions, safe preview, and validation; remove the new-schema Custom endpoint-default/inherit presentation.
- Propagate the fields through save/load/export/import and model-test requests; run browser tests for independent rows, save/edit round trips, scope controls, and safe rendering.
- Exit: two models under one endpoint persist distinct routing and report accurate previews; no secrets reach non-admin browser payloads.

### Phase 3: Runtime and Model Chat

- Wire test-model, model chat, and all audited non-agent helper/background consumers to the shared resolver, including chat-service builders only where those callers use them. Preserve existing agent behavior where implementation ownership is shared.
- Reuse existing OpenAI/Azure/Messages adapters where their behavior fits the contract and verify request/response/stream handling with recorded or mocked fixtures. Do not develop Responses, custom calls, or agent integrations.
- Apply capability checks, state isolation, cancellation, safe errors, and route-aware caching consistently.
- Exit: actual captured request URLs/headers/bodies match previews for model chat and in-scope helpers across the supported contracts. Deferred and unsupported combinations fail clearly before outbound dispatch; shared changes preserve existing excluded consumers.

### Phase 4: GenAI.mil

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
| CE-03 | A single Custom endpoint hosts the in-scope Azure deployment, OpenAI-compatible Chat Completions, and Messages contracts; each model explicitly stores its API type and URL Handling without endpoint inheritance or model-name heuristics changing them. | Settings round trip; missing-field rejection; mixed Auto/Exact models; Claude-name/OpenAI and GPT-name/Messages negative heuristic tests; existing compatible-profile parity. |
| CE-04 | Azure deployment identifiers and protocol versions belong to the selected model; configured path versions are distinct from dated protocol headers/queries; no duplicate structural suffix or query injection. | Captured requests, wrong-deployment rejection, mixed-version tests, synthetic `/v2/messages` path preservation without inferred new wire-format support. |
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
- Azure API presentation under review: explicitly include deployment-style Azure OpenAI and Azure/Foundry Chat Completions. Preserve generic OpenAI-compatible support; settle separate API choice versus URL/profile preset before changing the contract table or enum.
- Confirmed future-work decision (2026-09-21): Responses and custom calls are excluded from current development and belong in separate future plans. Keep existing routing/adapter/policy boundaries extensible, but add no dormant feature implementation, selectable option, persisted mappings, or dispatch for either.
- Confirmed agent scope (2026-09-21): agent changes are excluded. Preserve existing integrations and compatibility; new model-routing work does not authorize agent defaults, overrides, selectors, or tool-loop changes.
- Proposed GenAI scope: official SimpleChat provider integration, not a claim of vendor endorsement or approval for particular data. Messages/tools/vision/Responses await a documented contract and validation.
- No implementation, API migration, cloud changes, commits, or pushes are authorized by this planning artifact alone.

## Related Documentation

- [Existing Custom provider](CUSTOM_MODEL_ENDPOINT_PROVIDER.md)
- [Existing Custom authentication](CUSTOM_MODEL_ENDPOINT_AUTH.md)
- [Custom endpoint diagnostics](../fixes/CUSTOM_MODEL_ENDPOINT_DIAGNOSTICS_FIX.md)
- [Contribution workflow](../../../CONTRIBUTING.md)