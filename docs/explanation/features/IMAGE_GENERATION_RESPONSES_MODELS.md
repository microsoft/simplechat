# Image Generation Through Responses-Capable Chat Models (v0.261.105)

## Overview

SimpleChat can generate images through either a dedicated Images operation or the hosted
`image_generation` tool of a supported GPT deployment. Both use the administrator's
single image-model selection in [Shared AI Connections](AI_CONNECTIONS_FRAMEWORK.md).
Images can share a connection with chat or use a separate image-only resource.

Implemented in version: **0.261.105** for shared bindings and the corrected Azure v1
Responses contract. The initial Responses integration was introduced in **0.261.088**.
Application versioning is recorded in `application/single_app/config.py`.

Associated issue: [#1436 — Unify AI connections and fix GPT image generation](https://github.com/microsoft/simplechat/issues/1436).

**Dependencies:** the existing OpenAI SDK Responses surface, a supported deployed image
operation, and the required provider authentication and permissions. The hosted tool's
availability, region, entitlement, and backing image configuration are deployment-specific.
An existing GPT deployment alone is not a guarantee of image generation.

## Architecture

### One binding, two operation contracts

| Route | Endpoint | Models |
| --- | --- | --- |
| `images` | Images generation; Images edits only where supported | Currently available, compatible dedicated image deployments such as the `gpt-image-*` series |
| `responses` | Azure `/openai/v1/responses` with the hosted `image_generation` tool | GPT deployments whose image-tool support is established for the configured provider |

The global `image_generation_model_selection` reference supplies an endpoint ID,
model ID, and provider. Resolution uses the saved connection and model, not a copied
image endpoint/key or the user's current text-chat model.

Technical support comes from model capability metadata and the implemented provider
adapter. `supportsImageGeneration` can explicitly describe support, and
`image_generation_api` can retain a compatible `images` or `responses` route. A
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

### Azure v1 Responses, not a dated preview workaround

The hosted image tool uses Azure's v1 Responses contract. The earlier
`2025-04-01-preview` workaround did not provide the required image-tool schema and
must not be used as evidence of compatibility.

The selected GPT deployment is the request's top-level `model`. The request supplies
an `image_generation` tool and forces that tool choice, rather than accepting prose
about an image as the requested output. Size, quality, and background are supplied
only when requested, leaving unspecified provider defaults alone.

The v1 Responses request does not send a dated `api-version` query parameter.

### Image API versions

Images and Responses have separate version contracts:

| Configuration | Version used |
| --- | --- |
| Shared Images model with no image-specific version, including a missing operation profile | `2025-04-01-preview` for Images generations and edits |
| Shared Images model with an explicit `connection.operation_settings.image_generation.api_version` | The stored version, including an older imported version |
| Unmigrated legacy Images route without a configured image API version | `2024-12-01-preview` |
| Supported Responses image-tool route | `v1`, without a dated query parameter |

New shared Images defaults do not inherit the connection's chat `api_version` or
`openai_api_version`, or legacy root image settings. Image operation settings likewise
do not replace the chat API version. The new Images default is not a reason to
rewrite imported profile versions, nor does it make the dated Responses preview
support the hosted image tool.

### API Management and image-backend prerequisites

Shared connections retain gateway paths, authentication, and published-operation
constraints. An imported legacy APIM image route retains its Images behavior rather
than guessing a new Responses route from a deployment name. A Responses-capable shared
configuration still requires the gateway to publish the matching operation; SimpleChat
must not bypass it or redirect to another resource.

Azure documentation is not uniform about default backing-image routing. Some examples
use a type-only tool, while others require an image-deployment binding. Any required
binding must be verified from existing provider configuration or deployment metadata.
The optional tool `model` must not be assumed to be an Azure deployment name.

For an explicitly stored binding, the image operation profile's `image_deployment`
is sent in `x-ms-oai-image-generation-deployment`. With that metadata absent, the
adapter leaves backend routing to the provider. It does not choose another
deployment from the shared registry.

There is no second backend picker, no arbitrary search for another image model, and
no resource provisioning. A missing image capability or binding is a configuration
limitation to report, not something a GPT name can overcome.

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

Responses-backed image generation offers whole-image regeneration in SimpleChat.
Masked editing continues through the existing direct Images edit path when the
selected model and API support it. This release does not add reference-image input
or multi-turn Responses editing, and image-input/vision support must not be confused
with either editing or generation.

## Testing and validation

| Coverage | Regression suite |
| --- | --- |
| Route classification, tool options, and response handling | `functional_tests/test_image_generation_responses_route.py` |
| Client-only factory contract, image-only requests, scoped secrets, invalid defaults, safe errors, proposal/storage metadata, and editing/regeneration | `functional_tests/test_ai_connection_image_runtime.py` |
| SDK URLs, independent Images version defaults, preserved imported versions, APIM authentication/identity/backend headers, payloads, multipart edits, response parsing, and provider-error mapping | `functional_tests/test_image_generation_sdk_http.py` |
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

- Image generation is not supported by every GPT model or every resource exposing
  Responses. Required backend deployments/defaults and service permissions still apply.
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
- An image test is an inference request and can incur charges. Responses orchestration
  and image generation can have different cost and latency characteristics.
- Embedding, speech, transcription, and computer-use configuration are unchanged.

## References

- [GPT image-generation fix](../fixes/GPT_CHAT_MODEL_IMAGE_GENERATION_FIX.md)
- [Azure OpenAI Responses API](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/responses)
- [Azure Responses REST reference](https://github.com/MicrosoftDocs/azure-docs-rest-apis/blob/live/docs-ref-conceptual/microsoft-foundry/azureopenai/responses.md)
- [Azure direct-endpoint image-tool header guidance](https://github.com/MicrosoftDocs/azure-ai-docs/blob/main/articles/foundry/how-to/develop/langchain-models.md#L364-L384)
- [Azure v1 schema](https://github.com/Azure/azure-rest-api-specs/blob/main/specification/ai/data-plane/OpenAI.v1/azure-v1-v1-generated.json)
