# Custom Model Endpoint Provider (v0.261.107)

## Overview

Custom connections let an administrator use a provider's API or an approved gateway
without disguising it as an Azure resource. The connection owns its endpoint,
authentication, API contract, and manually configured models. Chat and images can
reference the same connection while keeping independent defaults.

Implemented in version: **0.261.107** for the React v2/shared-image forward-port.
Application versioning is tracked in `application/single_app/config.py`.
The implementation reuses the Custom foundation from #1437 without replacing newer
shared-connection behavior.

The original global, personal, and group Custom chat provider was implemented in
**0.250.172** for [#1222](https://github.com/microsoft/simplechat/issues/1222).
Verified endpoint/model capacity overrides were added in **0.261.035** and remain
separate from provider and image-operation selection.

**Dependencies:** an existing provider or gateway, the configured credentials,
network access, the existing scoped endpoint governance and Key Vault integration,
and an implemented operation. No resource is provisioned or inferred from a model's name.

## API contracts and identity

| Custom API type | Request identifier | Version field | Purpose |
| --- | --- | --- | --- |
| `openai` | `modelName` | None | Direct OpenAI or an explicitly configured OpenAI-compatible gateway |
| `azure_openai` | `deploymentName` | `connection.api_version` | Azure's deployment-addressed API contract |
| `anthropic` | `modelName` | `connection.anthropic_version` | Anthropic messages |
| `gemini` | `modelName` | None | Gemini's OpenAI-compatible surface |

The connection provider is `custom`; `api_type` is authoritative for the wire
contract. Endpoint paths and GPT-like model names do not select a different protocol.
Registry IDs and display names do not become provider model/deployment identifiers.
For deployment-addressed APIs, an underlying model name or catalog identity is
metadata, not a replacement for the actual deployment name.
Model discovery is manual for Custom connections, not an Azure Resource Manager
listing through an inference key.

Automatic URL handling follows the selected API type and preserves gateway prefixes.
Exact handling keeps the configured API base without adding version/deployment
prefixes. For Anthropic exact mode, supply the complete messages URL. Exact mode
does not disable endpoint validation, TLS, or the guarded transport.

## Configure a connection

In global **AI Connections**, choose **Custom**, select the API contract, and enter
the provider or approved gateway URL. Choose its supported authentication method.
Azure's contract needs the API version; Anthropic uses its version header instead.
Add models manually using the request identifier the contract requires.

Enable each model and publish it only for the intended supported tasks. Chat and
image generation keep independent defaults. In classic Admin Settings, **Save
Endpoint** stages edits; save the main settings form to persist them. React V2
saves each connection individually. Image tests require a saved connection rather
than an unsaved draft.

### Verified capacity and image-input overrides

Use **Advanced endpoint capacity** for verified endpoint defaults and **Advanced
model capacity** for deployment-specific limits or an exact catalog identity.
`contextWindow`, `inputTokenLimit`, and `outputTokenLimit` inherit independently
from model override, endpoint override, then the exact catalog model. Blank
fields inherit; clearing a saved override writes `null`. Unknown limits are not
unlimited and must not be guessed from a model family or a friendly deployment name.

`catalogModelId` and `modelVersion` identify the published model and deployed
snapshot, not the endpoint API version. `tokenLimitProvider` chooses the hosting
profile for capacity evidence without changing the request route.
`outputTokenAccounting` must match the provider/API's documented treatment of
reasoning and other generated tokens. **Response Length** is a per-request
generation allowance, not a hard model capacity. Independent input/output ceilings
need not fit simultaneously, but each request must fit its shared context.

The **Reads images** override concerns input only. The canonical
`capabilities.processesImages` value takes precedence over legacy `supportsVision`,
and editing the control keeps an existing canonical declaration and legacy value
consistent. Neither vision support nor token capacity establishes image generation.
See [verified model capacity](../../admin/ai-models.md#verified-model-capacity) for
field validation and the evidence to check before declaring overrides.

## Configure direct OpenAI images

Create a Custom connection using the OpenAI API contract, normally
`https://api.openai.com/v1`. Supply its credentials through the connection's secret
fields and add an actual provider model name.

Known GPT image-tool models can be published for image generation through this
connection. Dedicated GPT Image models use Images operations. Select the saved
connection/model under the global Image Generation default; no duplicate image
endpoint/key configuration is needed.

For a new model not covered by the catalog, use **Capability metadata** to declare
image generation and its compatible API. Source-image editing and uploaded-mask
support are separate declarations. Known provider restrictions still apply: an Azure
GPT chat deployment does not become an image generator through a metadata override.

The following configuration excerpt intentionally omits credentials:

```json
{
  "id": "direct-openai",
  "name": "Direct OpenAI",
  "provider": "custom",
  "api_type": "openai",
  "connection": {
    "endpoint": "https://api.openai.com/v1",
    "url_mode": "auto"
  },
  "models": [
    {
      "id": "frontier",
      "modelName": "gpt-6-astra",
      "enabled": true,
      "enabled_capabilities": ["chat", "image_generation"]
    }
  ]
}
```

An OpenAI-compatible gateway is not automatically the direct OpenAI service.
Capability evidence must match the configured backend/operation; otherwise use
explicit compatible metadata rather than relying on a GPT-like name.

## Authentication and transport

Custom connections support API keys, bearer tokens, and OAuth2 client credentials.
API-key header names and value prefixes can be overridden for approved gateways.
OAuth2 token requests use the same outbound validation and network policy as model
requests; tokens are cached with expiry-aware refresh.

Saved keys, bearer tokens, and client secrets are not returned in ordinary connection
read responses. Blank secret fields preserve stored values. Key Vault is used when
configured; request validation must not mistake a redacted value for a new credential.

mTLS uses deployment-mounted certificate/private-key paths in
`connection.client_cert_path` and `connection.client_key_path`, not inline PEM values
stored in settings. An empty key path is valid when the certificate PEM contains the
private key.

All Custom SDK operations use the shared DNS-pinned transport, not a new SDK client
with default networking. Redirects, loopback/link-local/platform metadata addresses,
and inherited environment proxies are not alternate routes around this boundary.
HTTPS certificate verification remains enabled.

By default, Custom URLs require HTTPS and a public fully qualified hostname.
Embedded credentials, query strings, and fragments are rejected. IP literals,
short host names, and private addresses require the explicit private-host policy;
loopback, link-local, metadata/platform, multicast, reserved, and unspecified
addresses remain blocked. URL/DNS policy is checked at save and runtime, and the
transport revalidates and pins addresses when connecting. Provider error bodies
and raw Custom Anthropic exceptions are not returned as connection diagnostics.

## Network policy settings

These administrator settings apply to Custom connections and OAuth2 token requests:

| Setting | Default | Effect |
| --- | --- | --- |
| `allow_private_custom_model_endpoints` | `False` | Permits approved private-network destinations while retaining hard blocks on loopback, link-local, and platform metadata addresses |
| `allow_insecure_custom_model_endpoints` | `False` | Permits plaintext HTTP only when private-host permission is also enabled; prompts and credentials then lack TLS protection |
| `custom_model_endpoint_ca_bundle_path` | Empty | Uses a deployment-mounted trust bundle instead of the default public roots; use this for approved private CAs rather than disabling verification |

These controls are available under **Custom endpoint network policy** in AI
Connections. They do not authorize cross-cloud data transfers or override model
capability/publication rules.

Custom image output URLs are fetched with a fresh guarded client. Inference
credentials, identity headers, cookies, and mTLS credentials are not forwarded to an
output host. Downloads and decoded images remain subject to application size limits.

## Scope, APIs, and implementation

Global endpoints remain administrator-controlled. Personal and group chat endpoints
retain their existing feature flags (`allow_user_custom_endpoints` and
`allow_group_custom_endpoints`), role/governance checks, active-group checks, stable
endpoint/model IDs, and Key Vault scope. Runtime requests resolve authorized saved
records rather than trusting caller-supplied connection details. The advanced auth
controls described here are in the global classic and React V2 connection editors.
`enable_multi_model_endpoints` controls connection-backed chat, not image-only use.

Chat tests use `POST /api/models/test-model`, `POST /api/user/models/test-model`,
or `POST /api/group/models/test-model` for the corresponding authorized scope.
Personal/group saves retain their `/api/user/model-endpoints` and
`/api/group/model-endpoints` routes. Custom discovery is rejected before model-list
network dispatch.

Key implementation files:

- Protocol registry and identifiers: `functions_model_endpoint_providers.py`,
  `functions_model_endpoint_types.py`.
- Validation, auth, and guarded runtime: `functions_model_endpoint_validation.py`,
  `functions_model_endpoint_auth.py`, `functions_model_endpoint_runtime.py`,
  `model_endpoint_clients.py`.
- Save/test routes: `route_backend_models.py`, `route_backend_v2.py`.
- Classic editors: `templates/_multiendpoint_modal.html`,
  `templates/admin/_panes/model-endpoints.html`,
  `static/js/admin/admin_model_endpoints.js`,
  `static/js/workspace/workspace_model_endpoints.js`.
- Shared capacity controls: `static/js/model_budget_editor.js`.

These paths are relative to `application/single_app/`. React V2's connection
components and helpers are under `application/v2_ui/src/`.

## Validation and limitations

React V2 **Test connection** validates the configured Custom contract; its
`validation_only` result is not an inference result. **Test chat** exercises chat
and reports the resolved request URL when available; it does not test image
generation. An image-specific test exercises the saved image binding and may incur
charges.

`functional_tests/test_custom_model_endpoint_foundation.py` covers API types, URL modes, auth headers, token
handling, network boundaries, settings/secret preservation, and runtime integration.
The Custom and shared-admin browser suites cover the real forms. Image-specific
contract and output-transport tests cover the image integration, including
`functional_tests/test_image_custom_output_transport.py`.
`functional_tests/test_custom_model_endpoint_provider.py` retains scoped foundation
coverage. The offline `functional_tests/test_admin_model_endpoint_editor_integration.js`
regression exercises the combined classic editor and real capacity controls without
calling a provider.

Protocol compatibility alone does not implement every provider operation. Anthropic
and Gemini Custom support does not grant image generation through OpenAI's hosted
image tool. Embeddings and other service configuration remain separate. Personal
or group chat connections do not become global image defaults.

URL validation adds DNS lookups at save and connection time; this is intentional
address validation, not model discovery. Runtime latency and capability readiness
still depend on the configured provider, credentials, and operation.

## Related

- [Model capability catalog](MODEL_CAPABILITY_CATALOG.md)
- [Shared AI Connections](AI_CONNECTIONS_FRAMEWORK.md)
- [Provider-aware images](IMAGE_GENERATION_RESPONSES_MODELS.md)
- [Configure AI connections](../../guides/configure-ai-connections.md)
