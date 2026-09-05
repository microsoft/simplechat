# Model Endpoint Provider Registry

## Overview

Custom model endpoints let an administrator point SimpleChat at a model API that
is not an Azure OpenAI or Foundry resource. The first implementation supported
three API types — OpenAI, Azure OpenAI, and Anthropic — but each one was
hard-coded in five separate places:

- the supported api-type allowlist,
- the request-model resolver that decides whether a model is named by model name
  or deployment name,
- the protocol inference chain,
- the admin template's `<option>` list,
- the admin and workspace JavaScript that shows and hides version fields.

Adding a provider meant editing all five consistently. Missing one produced a
silent, hard-to-diagnose failure.

The provider registry makes an API type a single declarative record.

**Implemented in version: 0.261.014**

## Dependencies

No new dependencies. The registry uses only the standard library so it can sit
below the client, runtime, validation, and route layers without import cycles.

## Architecture

### The provider record

`application/single_app/functions_model_endpoint_providers.py` defines
`ModelEndpointProvider`. One record carries everything the rest of the
application needs:

| Field | Purpose |
|---|---|
| `api_type` | Stable identifier persisted on the endpoint record |
| `display_name` | Label shown in the admin API Type list |
| `protocol` | Wire protocol: `openai_style`, `azure_openai`, or `anthropic` |
| `model_identifier` | Whether models are named by model name or deployment name |
| `url_policy` | How the configured URL becomes a request URL |
| `auth_types` | Which authentication types the API type accepts |
| `requires_api_version` | Whether an API version must be supplied |
| `version_field` | Which connection field carries the version, if any |
| `default_version` | Default applied when the version field is empty |
| `supports_streaming` / `supports_tools` | Declared capability of the API surface |

### Registered API types

| API type | Protocol | Model named by | URL policy |
|---|---|---|---|
| `openai` | `openai_style` | Model name | Append `/v1` if missing |
| `azure_openai` | `azure_openai` | Deployment name | Azure resource endpoint |
| `anthropic` | `anthropic` | Model name | Anthropic messages URL |
| `gemini` | `openai_style` | Model name | Use exactly as given |

`openai` covers OpenAI itself and any OpenAI-compatible surface, including
gateways, vLLM, and LiteLLM.

### URL policies

Appending `/v1` is correct for OpenAI and OpenAI-compatible gateways whose base
carries no version segment. It is wrong for a surface that already has one.
Google Gemini's OpenAI-compatible base is
`https://generativelanguage.googleapis.com/v1beta/openai/`; appending `/v1`
produces `…/v1beta/openai/v1/` and a 404.

| Policy | Behaviour |
|---|---|
| `append_v1_if_missing` | Append `/v1` only when the URL does not already name the API surface |
| `as_given` | Use the configured URL exactly, normalizing only the trailing slash |
| `azure_deployment` | Pass to the Azure OpenAI SDK as the resource endpoint |
| `anthropic_messages` | Normalize to the Anthropic `/v1/messages` URL |

`append_v1_if_missing` does not append when either of these is true:

- **The last path segment is already a version**, matching `v` followed by digits
  and optional qualifiers — `v1`, `v2`, `v1beta`, `v1alpha`.
- **The URL is a full operation URL**, ending in `/chat/completions`,
  `/responses`, or `/models`. Such a URL states the base exactly, so the
  operation suffix is stripped and the remainder is used as given.

Worked examples:

| Configured | Resolved |
|---|---|
| `https://api.openai.com` | `https://api.openai.com/v1/` |
| `https://api.gen.ai.mil/v1` | `https://api.gen.ai.mil/v1/` |
| `https://gw.example.com/api/v2` | `https://gw.example.com/api/v2/` |
| `https://apim.example.com/inference/chat/completions` | `https://apim.example.com/inference/` |
| `https://generativelanguage.googleapis.com/v1beta/openai` | unchanged (`as_given`) |

### The exact-URL escape hatch

Some gateways mount the OpenAI surface at a path SimpleChat cannot infer, such as
`https://gw.example.com/llm/openai`, where the API may live at that path or at
`…/openai/v1`. Rather than guess, the endpoint editor offers **Use this URL
exactly as entered**, stored as `connection.url_mode = "exact"`, which forces the
`as_given` policy for any API type.

Because the resolved URL is otherwise invisible, **Test Connection reports the
URL that was actually called**, so a rewrite is always verifiable.

### Transport tiers

Providers are tiered by whether SimpleChat can control the outbound connection:

- **Tier A** — reached over an OpenAI-compatible or Anthropic HTTP surface, so
  the request runs on the validated-DNS pinned transport that refuses redirects
  and re-validates addresses at connect time.
- **Tier B** — would require a vendor SDK with its own transport, such as gRPC
  or botocore, which the pinned transport cannot wrap.

Only Tier A providers are registered. Google Gemini is reachable at Tier A
through its OpenAI-compatible surface, so it gains support without giving up the
outbound-connection controls.

## Usage

### Adding an API type

Add one `ModelEndpointProvider` entry to `MODEL_ENDPOINT_PROVIDERS`. The admin
API Type list, the model identifier field, the version fields, validation, and
protocol inference all follow from it.

```python
ModelEndpointProvider(
    api_type="my_provider",
    display_name="My Provider",
    protocol=MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    model_identifier=MODEL_IDENTIFIER_MODEL_NAME,
    url_policy=URL_POLICY_AS_GIVEN,
    description="What this surface is and when to choose it.",
)
```

An API type whose wire protocol is not one of the three existing protocols also
needs a client adapter; the registry alone does not add protocol support.

### Configuring a Gemini endpoint

1. Admin Settings → Model Endpoints → add an endpoint, provider **Custom**.
2. Set **API Type** to **Google Gemini (OpenAI-compatible)**.
3. Set the endpoint URL to
   `https://generativelanguage.googleapis.com/v1beta/openai/`.
4. Supply the Gemini API key.
5. Add models manually by **Model Name**, for example `gemini-3.8-flash`. Those
   models resolve their capabilities from the model capability catalog.

## Frontend integration

The registry is rendered server-side, so the browser never hard-codes an API
type list. It reaches the frontend two ways:

- `_multiendpoint_modal.html` renders the `<option>` list and serializes the full
  registry into a `data-api-types` attribute, which the admin and workspace
  scripts parse once and cache.
- `base.html` exposes `window.simplechatModelEndpointApiTypes` and the
  `window.simplechatCustomApiTypeUsesModelName()` helper, for scripts such as
  `agents_common.js` that render model lists without the endpoint editor present.

Both are inline JSON rendered through Jinja's `tojson` with autoescaping, so no
third-party or CDN asset is involved.

## Testing and validation

`functional_tests/test_model_endpoint_provider_registry.py` covers:

- the three original API types behaving exactly as before the registry;
- every registered API type being reachable end to end through normalization,
  protocol inference, request-model resolution, and the UI descriptor;
- unregistered API types still being rejected, including by protocol inference;
- Gemini's base URL not gaining a second `/v1`, while plain OpenAI keeps the
  appending behaviour;
- the append rule leaving existing version segments and full operation URLs
  alone, across seven real endpoint shapes;
- the exact-URL escape hatch disabling rewriting for any API type;
- every UI descriptor carrying the fields the admin JavaScript reads.

`functional_tests/test_custom_model_endpoint_provider.py` additionally asserts
that the admin and workspace scripts contain no hard-coded `api_type`
comparisons.

## Known limitations

- Authentication is still API key only. Bearer, OAuth2, and mTLS are declared in
  the registry's `auth_types` field but not yet implemented.
- `supports_streaming` and `supports_tools` are declared on the provider record
  but are not yet consumed; streaming behaviour is unchanged in this version.
- Tier B providers such as Vertex AI and Bedrock are not registered, because
  their SDK transports cannot be wrapped by the pinned transport.
