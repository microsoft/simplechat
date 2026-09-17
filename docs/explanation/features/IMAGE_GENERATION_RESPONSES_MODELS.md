# Provider-aware Image Generation and Editing (v0.261.107)

## Overview

SimpleChat generates images through dedicated GPT Image, MAI Image, and Foundry FLUX
operations, or the hosted `image_generation` tool of a verified direct OpenAI GPT model.
All use the administrator's
single image-model selection in [Shared AI Connections](AI_CONNECTIONS_FRAMEWORK.md).
Images can share a connection with chat or use a separate image-only resource.

Implemented in version: **0.261.107** for provider-qualified operations and editing.
Shared bindings were introduced in **0.261.105**, and the original Responses
integration in **0.261.088**.
Application versioning is recorded in `application/single_app/config.py`.

Related foundation: [#1436 — Shared AI connections](https://github.com/microsoft/simplechat/issues/1436).

**Dependencies:** the existing pinned OpenAI SDK, the Custom endpoint foundation for
direct OpenAI, an implemented image API, and the configured provider credentials and
permissions. Model capability and cloud availability do not prove live service access.

## Architecture

### One binding, provider-specific operation contracts

| Route | Endpoint | Models |
| --- | --- | --- |
| `images` | Direct OpenAI or Azure Images generation and supported edits | Compatible dedicated GPT Image models |
| `responses` | Direct OpenAI `/v1/responses` with `image_generation` | Verified GPT image-tool models through Custom connections |
| `mai` | Foundry `/mai/v1/images/generations` and multipart `/images/edits` | Documented MAI Image 2.5/2.6 variants |
| `flux` | Per-model native Foundry BFL API, or the documented Images-compatible Kontext API | FLUX.2-pro, FLUX.2-flex, FLUX-1.1-pro, and FLUX.1-Kontext-pro |

The global `image_generation_model_selection` reference supplies an endpoint ID,
model ID, and provider. Resolution uses the saved connection and model, not a copied
image endpoint/key or the user's current text-chat model.

Technical support comes from provider-qualified catalog metadata and the implemented
adapter. Unknown Custom models can declare a compatible `image_generation_api` and
`supportsImageGeneration`; source editing and masking are separate declarations.
Known provider/adapter restrictions take precedence. A
publication list, `enabled_capabilities`, independently controls whether users may
use that supported operation.

Known image models do not become chat choices. Conversely, an unknown model name,
vision/image-input support, or generic tool support does not establish hosted image
generation. The picker only offers image-eligible published models on enabled connections.

Support evidence must match the model and provider, not just a GPT or Codex family
name. In particular, an OpenAI `-chat-latest` model identifier is not interchangeable
with a similarly named Azure `-chat` identifier.

Image-tool catalog matching accepts exact IDs, declared aliases, and valid dated
snapshots, not arbitrary `gpt-4o-*` suffix variants inheriting support from a prefix.
The legacy vision heuristic is separate and does not grant image-generation support.

### Direct OpenAI Responses, not an Azure chat-model image choice

The hosted tool is reached through an OpenAI API **Custom** connection, normally
`https://api.openai.com/v1`. It uses the provider model name, not an Azure deployment
path or configuration UUID.

The selected GPT model is the request's top-level `model`. The request supplies
an `image_generation` tool and forces that tool choice, rather than accepting prose
about an image as the requested output. Size, quality, and background are supplied
only when requested, leaving unspecified provider defaults alone.

Direct OpenAI requests do not send an Azure `api-version` query or
`x-ms-oai-image-generation-deployment` header.

Microsoft does document an Azure Responses image tool backed by a separate GPT Image
deployment. SimpleChat deliberately offers dedicated image models only on Azure/Foundry,
instead of integrating that conditional Azure orchestration path. This is an
application policy, not a claim that the Azure tool does not exist.

### Image API versions

Images and Responses have separate version contracts:

| Configuration | Version used |
| --- | --- |
| Shared Images model with no image-specific version, including a missing operation profile | `2025-04-01-preview` for Images generations and edits |
| Shared Images model with an explicit `connection.operation_settings.image_generation.api_version` | The stored version, including an older imported version |
| Unmigrated legacy Images route without a configured image API version | `2024-12-01-preview` |
| Direct OpenAI Images or Responses | OpenAI `/v1`, without an Azure version query |
| MAI Image | `/mai/v1`, without an Azure OpenAI version query |
| Foundry FLUX | `api-version=preview`; native per-model paths or the documented v1 Images-compatible Kontext paths |

New shared Images defaults do not inherit the connection's chat `api_version` or
`openai_api_version`, or legacy root image settings. Image operation settings likewise
do not replace the chat API version. The new Images default is not a reason to
rewrite imported profile versions, nor does it make the dated Responses preview
support the hosted image tool.

### Custom endpoints and API Management

Shared connections retain gateway paths, authentication, and published-operation
constraints. An imported legacy APIM image route retains its Images behavior rather
than guessing a new Responses route from a deployment name. A Responses-capable shared
configuration still requires the gateway to publish the matching operation; SimpleChat
must not bypass it or redirect to another resource.

Direct OpenAI reuses the Custom connection's URL, authentication, and guarded
transport. A generic OpenAI-compatible gateway does not inherit direct OpenAI
image-tool capability merely by sharing its wire protocol. Unknown models/backends
require compatible explicit metadata.

There is no second backend picker, automatic model substitution, Azure image-backend
header, or resource provisioning. A missing image capability is reported, not worked
around by trying another provider or bypassing its gateway.

### Response shape

An Images response supplies an image URL or base64 image data. The Responses route
supplies an `image_generation_call` item in `output`, with base64 in `result` and an
optional `output_format`.

Both are normalized into the existing image-source contract for storage, proposals,
revision history, and display. A text-only response, refusal, failed/incomplete image
call, or empty image payload is not successful generation. Provider success alone is
also insufficient: the image message and its deployment metadata must be persisted.

## File structure

| File | Role |
| --- | --- |
| `application/single_app/functions_ai_connections.py` | Shared capability validation, safe catalogs, references, and server-only bindings |
| `application/single_app/functions_ai_connection_migration.py` | Automatic legacy image import and failure retention |
| `application/single_app/functions_image_api_route.py` | Image operation selection, tool specification, and Responses output handling |
| `application/single_app/functions_image_capabilities.py` | Provider/cloud-qualified generation, editing, masks, options, and availability |
| `application/single_app/functions_image_adapters.py` | Distinct OpenAI, MAI, and FLUX request payloads |
| `application/single_app/functions_image_generation.py` | Registered `build_image_connection_client`, shared requests, and generated-image message construction |
| `application/single_app/functions_image_edit.py` | Shared regeneration and existing masked-edit restrictions |
| `application/single_app/route_backend_chats.py` | Chat image request handling |
| `application/single_app/route_backend_settings.py` | Image-specific operation test |
| `application/single_app/route_backend_v2.py` | Capability-default API and invalidation notices |

The registered `build_image_connection_client(binding, settings)` factory returns
the configured SDK client only. The compatibility helper
`resolve_image_generation_client()` returns the client and deployment name together;
that tuple-returning helper is not the registered factory.

### Callers

The shared generation entry point serves:

- Chat **Image** mode.
- `generate_chat_image_message()` for image proposals and approvals.
- The whole-image regeneration branch of `request_image_edit()`.
- Image-specific admin tests.

Chat Image-mode requests skip mandatory text-GPT client/model initialization and use
their independent image binding. An image-only configuration is not forced through a
text inference client before generation.

A management/discovery check or an ordinary chat test is not interchangeable with an
image test. A useful image test must exercise the selected image binding and operation.

## Configuration

1. Configure the resource and its models in **AI Connections**.
2. Publish a supported image model and select it under **Image Generation**, using
   the single model picker grouped by connection.
3. Enable image generation and verify an actual image request.

There is no required API-mode choice. Shared image generation does not require the
irreversible **Use AI Connections for chat** switch, and its default is independent of
`default_model_selection`.

Existing direct/APIM settings are imported automatically with the active route,
deployment, authentication, and operation version retained. Original values remain as
backup. An incomplete import retains legacy operation with a warning; after success or
an explicit shared-default save, clearing the default never restores legacy settings.

For the administrator workflow, see [Configure AI connections](../../guides/configure-ai-connections.md).

## Editing and regeneration

The editor distinguishes a source-image edit from prompt-only regeneration.
Compatible direct OpenAI Responses/Images and Azure GPT Image operations can accept
an uploaded mask. MAI and eligible FLUX operations can edit a reference image without
claiming a mask interface. FLUX-1.1-pro offers generation/regeneration only.

Direct Responses editing sends the current source image and, when selected, its PNG
mask through `input_image_mask`. A mask guides the model rather than enforcing
pixel-exact preservation. It is never silently discarded to produce a replacement.

Rendering controls come from the selected operation profile. Native MAI and FLUX.2
reference edits do not expose dimension overrides here; regeneration supplies the
documented generation dimensions. Unknown availability is explained separately from
the model's editing capabilities.

## Testing and validation

| Coverage | Regression suite |
| --- | --- |
| Route classification, tool options, and response handling | `functional_tests/test_image_generation_responses_route.py` |
| Client-only factory contract, image-only requests, scoped secrets, invalid defaults, safe errors, proposal/storage metadata, and editing/regeneration | `functional_tests/test_ai_connection_image_runtime.py` |
| SDK URLs, independent Images versions, APIM authentication/identity headers, multipart edits, response parsing, and provider-error mapping | `functional_tests/test_image_generation_sdk_http.py` |
| Provider/cloud qualification, catalog schema, options, and exact provider wire payloads | `functional_tests/test_image_provider_capabilities.py`, `functional_tests/test_image_provider_sdk_http.py` |
| Shared default HTTP contracts and legacy import | `functional_tests/test_ai_connection_defaults_api.py`, `functional_tests/test_ai_connection_image_migration.py` |

The SDK HTTP tests use the application-pinned OpenAI **1.109.1** client with
`httpx.MockTransport`. Request construction and response/error handling execute in
the installed SDK, while HTTP responses, credential/secret collaborators, and
storage dependencies are isolated. They verify transport contracts without
contacting Azure or provisioning resources.

This describes regression coverage, not completed live-provider certification.
Verify the selected deployment on an authorized existing resource and confirm that
an image is displayed and persisted. A mocked result, successful discovery, or a text
answer is not live image-generation evidence.

## Known limitations

- Image generation is not inferred for every GPT model or OpenAI-compatible resource.
  Azure/Foundry GPT orchestration is excluded by the standalone-only application policy.
- [Azure retired DALL-E 3 on March 4, 2026](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/dall-e);
  existing Azure deployments are non-functional. Legacy identifiers can remain in
  stored settings and compatibility handling, but that does not restore service
  availability. Select an approved, currently available image deployment instead.
- Retirement dates are provider-specific. A deprecation notice for OpenAI's hosted
  API does not establish the availability or retirement date of an Azure deployment.
- An API Management gateway must support the selected operation and its authentication
  contract. The application does not discover a bypass route.
- Content safety, rate limits, and transient failures remain possible even for a
  correctly configured model; they do not change its capabilities or default.
- MAI models are preview offerings, and optional Bing web grounding is not enabled.
  Foundry FLUX documentation requires operators to configure content safety during
  inference rather than assume deployment-time filtering.
- App hosting does not establish endpoint residency. Government image availability
  absent from the reviewed provider table remains unknown, not globally prohibited.
- An image test is an inference request and can incur charges. Responses orchestration
  and image generation can have different cost and latency characteristics.
- Embedding, speech, transcription, and computer-use configuration are unchanged.

## References

- [Provider capability fix](../fixes/IMAGE_PROVIDER_CAPABILITIES_FIX.md)
- [Direct OpenAI image generation](https://developers.openai.com/api/docs/guides/image-generation)
- [Foundry MAI Image](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-mai-image)
- [Foundry FLUX](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-flux)
- [Azure OpenAI Responses API](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/responses)
- [Azure Responses REST reference](https://github.com/MicrosoftDocs/azure-docs-rest-apis/blob/live/docs-ref-conceptual/microsoft-foundry/azureopenai/responses.md)
- [Azure v1 schema](https://github.com/Azure/azure-rest-api-specs/blob/main/specification/ai/data-plane/OpenAI.v1/azure-v1-v1-generated.json)
