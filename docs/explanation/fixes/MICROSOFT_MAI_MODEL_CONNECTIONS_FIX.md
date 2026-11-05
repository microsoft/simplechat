# Microsoft MAI Model Connection Compatibility Fix

Fixed/Implemented in version: **0.261.407**.
The application version update is in `application/single_app/config.py`.

## Issue and root cause

MAI-Thinking-1 uses Microsoft's `/mai/v1/chat/completions` inference operation.
It is compatible with the OpenAI Chat Completions SDK, but a descriptive catalog
entry alone cannot make SimpleChat's existing client paths use that contract.
Requiring a separate vendor-specific connection also made operators learn URL
suffixes instead of selecting the model deployed on their Foundry resource.

Saving a full operation removes `/chat/completions` from the connection base.
The previous Foundry normalizer then appended `/openai/v1/` to a saved
`/mai/v1/` base. A gateway exposing the MAI path could also be classified as a
dated Azure deployment API. Native MAI authentication and output parameters
additionally differed from existing defaults: Cognitive Services is the
documented token audience, resource keys use `api-key`, and the native generation
ceiling is `max_completion_tokens`, not `max_tokens`.

The asynchronous Custom stream wrapper also lacked the SDK stream type expected
by Semantic Kernel. Auxiliary timeout binding could bypass the synchronous
compatibility wrapper and lose the selected model's request policy.

## Technical changes

| Area | Change |
| --- | --- |
| Protocol and URL resolution | A trusted native Foundry resource/project endpoint resolves each model's contract. OpenAI/Grok preserve their v1 surface and documented project prefix; MAI uses the resource's `/mai/v1/`; Anthropic retains messages. Saved discovery endpoints are not changed. |
| Native authentication | Public Microsoft MAI resource URLs default to the Cognitive Services audience. Explicit audiences remain authoritative. Resource-key authentication uses `api-key` without duplicating it into a bearer header. |
| Request policy | Sync chat, auxiliary clients, and SK/async callers use `max_completion_tokens` and omit undocumented sampling/effort controls and `stream_options` for the reviewed MAI model/contract. Deployment and gateway request names remain unchanged. |
| Streaming | The sanitized Custom async stream retains the SDK stream interface while keeping error sanitization and cleanup. Function tool calls remain usable when MAI reports `finish_reason: stop`. |
| Catalog | The sourced preview profile describes text reasoning, function calling, streaming, 256,000-token shared context, 64,000-token total generation, and its native Foundry API. Independent input capacity and configurable effort levels remain unknown. |
| Connection editor | Built-in model selection fills canonical model identity without renaming deployments/aliases or copying over explicit overrides. Automatic name matching remains available. Native models can be saved manually without discovery coordinates. |
| API preference and metadata | MAI/Anthropic keep their supported native API when a shared connection prefers Responses. Chat, agents, workflow metadata, tabular budgets and capture validation derive the same per-model operation. |

Primary implementation files are `functions_model_endpoint_urls.py`, `functions_model_endpoint_validation.py`,
`functions_model_capabilities.py`, `functions_model_budget_runtime.py`,
`functions_settings.py`, `model_endpoint_clients.py`,
`functions_model_endpoint_runtime.py`, `model_tool_chat_completion.py`,
`semantic_kernel_loader.py`, and `static/json/model_capabilities.json`, under
`application/single_app/`. The V2 connection logic lives in
`application/v2_ui/src/lib/` and `components/admin/ModelConnectionsManager.tsx`.

## Configuration and impact

No new top-level provider or custom API type is needed. Use **Azure AI Foundry**
or **Azure OpenAI** for the native resource, or **Custom → OpenAI API** for an
approved gateway. See the [configuration guide](../../guides/configure-ai-connections.md#microsoft-mai-text-models).

For native Foundry, configure the resource or project endpoint once, then add
OpenAI, Grok and MAI deployments. Select a recognized underlying model by name or
choose its built-in profile. An opaque alias retains its request name while
**Catalog model ID** identifies the actual deployed model. Native MAI automatically
uses Chat Completions even when the shared connection prefers Responses.
Keep managed identity when resource keys are disabled. Discovery can omit a valid
deployment; it is not an inference readiness test.

For a gateway, retain its actual base, authentication, and model identifier.
Choosing the built-in MAI model fills **Catalog model ID** `mai-thinking-1` to
identify an opaque alias's reviewed underlying model independently of its request
name. Custom or imported descriptive profile associations do not become numeric
evidence or silently choose another protocol.
Explicit deployment capacity overrides still take precedence over catalog limits.

The change does not enable resource keys, provision a deployment, weaken outbound
address/TLS policy, add managed identity to Custom authentication, or change global
chat, planner, image, or embedding defaults. GPT, Grok, Anthropic, and other model
families do not inherit MAI request rules.

## Validation

`functional_tests/test_microsoft_mai_model_connections.py` exercises real SDK
requests and real Semantic Kernel services with external I/O blocked. It covers:

- Mixed native Foundry connections for OpenAI, Grok and MAI, managed identity and
  existing resource keys, including both shared OpenAI API preferences.
- Custom/APIM exact paths, subscription headers, bearer authentication, and opaque
  request aliases with explicit canonical model metadata.
- Non-streaming and streaming chat, function invocation and continuation, native
  local-agent factories, normal and optimized Python, auxiliary timeout binding,
  and per-model workflow/capture metadata and tabular budgets.
- Scoped audience defaults, preserved explicit audiences, lookalike hosts and path
  versions, immutable caller settings, and isolation from other model families.

The MAI regression suite, catalog schema/evidence checks, V2 form-logic checks,
TypeScript type-check, and production frontend build pass. Broader older Custom,
image, and embedding fixture suites still have failures involving stale AST extraction, incomplete
module stubs, and outdated auth doubles; the same failures were independently
reproduced with unchanged `HEAD` sources and are not repaired by this change.

`ui_tests/test_microsoft_mai_ai_connections.py` adds fixture-only browser scenarios
for desktop/mobile mixed-resource saves, model-preset preconfiguration and preserved
Custom gateway aliases. Browser
execution and live deployment readiness are separate checks; the local SDK tests
do not perform paid inference.

Before the fix, a saved native base could target a nonexistent OpenAI-suffixed
route or send unsupported output parameters. After the fix, the mock HTTP boundary
observes each model's documented native operation from one unchanged project
connection, including MAI's route, audience and total-generation ceiling through
streaming tool continuations.

## Limits and source evidence

MAI-Thinking-1 remains a preview text model. The reviewed contract does not
establish Responses, images, embeddings, JSON-schema output, or selectable reasoning
efforts. SimpleChat does not opt in to or carry the optional encrypted reasoning
envelope across turns. Quota, region, RBAC, network access, and gateway
operation readiness still require deployment-specific verification.

Sources reviewed on **2026-11-05**:

- [Microsoft MAI-Thinking-1 inference, authentication, streaming, and tools](https://learn.microsoft.com/azure/foundry/foundry-models/how-to/use-foundry-models-mai-thinking).
- [Azure model table with exact MAI context/output limits](https://learn.microsoft.com/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure#microsoft-models-sold-by-azure).
- [Foundry project OpenAI client setup](https://learn.microsoft.com/azure/foundry/foundry-models/how-to/use-chat-reasoning).
- [Grok native v1 inference operations](https://learn.microsoft.com/azure/foundry/foundry-models/how-to/use-foundry-models-grok).
