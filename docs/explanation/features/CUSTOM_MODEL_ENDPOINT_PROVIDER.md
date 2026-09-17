# Custom model connections (v0.261.108)

## Overview

Custom connections let an administrator use a provider's API or an approved gateway
without disguising it as an Azure resource. The connection owns its endpoint,
authentication, API contract, and manually configured models. Chat, images, and
compatible embeddings can reference the same connection with independent defaults.

Implemented in version: **0.261.107** for the React v2/shared-image forward-port.
Application versioning is tracked in `application/single_app/config.py`.
The implementation reuses the Custom foundation from #1437 without replacing newer
shared-connection behavior.
Embedding integration with this foundation was implemented in **0.261.108**.

**Dependencies:** an existing provider or gateway, the configured credentials,
network access, and an implemented operation. No resource is provisioned or inferred
from a model's name.

## API contracts and identity

| Custom API type | Model identifier | Purpose |
| --- | --- | --- |
| `openai` | `modelName` | Direct OpenAI or an explicitly configured OpenAI-compatible gateway |
| `azure_openai` | `deploymentName` | Azure's deployment-addressed API contract |
| `anthropic` | `modelName` | Anthropic messages |
| `gemini` | `modelName` | Gemini's OpenAI-compatible surface |

The connection provider is `custom`; `api_type` identifies the wire contract.
Registry IDs and display names do not become provider model/deployment identifiers.
Model discovery is manual for Custom connections, not an Azure Resource Manager
listing through an inference key.

Automatic URL handling follows the selected API type and preserves gateway prefixes.
Exact handling keeps the configured API base without adding version/deployment
prefixes. For Anthropic exact mode, supply the complete messages URL. Exact mode
does not disable endpoint validation, TLS, or the guarded transport.

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

## Validation and limitations

**Test connection** validates the configured Custom contract; its `validation_only`
result is not an inference result. **Test chat** exercises chat. An image-specific
test exercises the selected image binding and may incur charges.

`functional_tests/test_custom_model_endpoint_foundation.py` covers API types, URL modes, auth headers, token
handling, network boundaries, settings/secret preservation, and runtime integration.
The Custom and shared-admin browser suites cover the real forms. Image-specific
contract and output-transport tests cover the image integration, including
`functional_tests/test_image_custom_output_transport.py`.

Protocol compatibility alone does not implement every provider operation. Anthropic
and Gemini Custom support does not grant image generation through OpenAI's hosted
image tool. Embeddings support Custom OpenAI and Azure OpenAI API contracts with
API key/bearer authentication, using the shared network policy and pinned transport.
Other Custom API types and OAuth2 remain unavailable for embeddings in this phase.
Retained `openai_compatible` embedding-only records keep their identifiers and
exact base paths, but cannot bypass Custom network validation. Personal or group
chat connections do not become global image or embedding defaults.

## Related

- [Model capability catalog](MODEL_CAPABILITY_CATALOG.md)
- [Shared AI Connections](AI_CONNECTIONS_FRAMEWORK.md)
- [Provider-aware images](IMAGE_GENERATION_RESPONSES_MODELS.md)
- [Configure AI connections](../../guides/configure-ai-connections.md)
