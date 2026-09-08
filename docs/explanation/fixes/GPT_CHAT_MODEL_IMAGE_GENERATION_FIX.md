# GPT Chat Model Image Generation Fix (v0.261.105)

## Issue

An image-capable GPT deployment could be selected for image generation but fail when
SimpleChat invoked it. Separately, a successful provider image response could still
fail while the application constructed the image message. These failures made a
configured image workflow look like a bad prompt or an unavailable image model.

Fixed in version: **0.261.105**. The application version is tracked in
`application/single_app/config.py`.

Associated issue: [#1436 — Unify AI connections and fix GPT image generation](https://github.com/microsoft/simplechat/issues/1436).

## Root causes

### An incompatible Responses contract

The earlier Responses image integration substituted `2025-04-01-preview` for the
older image API version. That dated preview's Responses schema does not include the
hosted `image_generation` tool. Being newer than an Images API version was not proof
that the required Responses operation existed.

The earlier discovery/classification rules also treated broad GPT/chat model names
as evidence of image generation. Image input, ordinary text output, and generic tool
calling do not establish hosted image-tool support for a particular Azure deployment.

### A deployment name lost before persistence

`generate_chat_image_message()` used `image_gen_model` when populating
`model_deployment_name`, but that variable was not defined in the helper after image
requests moved into `request_generated_image_source()`. Obtaining an image was
therefore insufficient to complete the message/persistence workflow.

### Errors attributed to the prompt

Image request failures were not sufficiently separated into configuration,
unsupported-operation, service, content-safety, and rate-limit cases. Retrying a
different prompt cannot repair a missing image-tool contract or an invalid default.

## Changes

### Resolve one shared image default

The image workflow resolves `image_generation_model_selection` against
`model_endpoints`. That reference supplies the exact enabled connection and
image-compatible published model. The deployment used for generation is also
available to message metadata and persistence.

Existing direct/APIM image settings are automatically imported, preserving the active
route and model. A failed import retains legacy operation with a warning. A successful
import or explicit shared selection makes the new reference authoritative; clearing
it cannot silently revive old settings.

See [Shared AI Connections](../features/AI_CONNECTIONS_FRAMEWORK.md) for the binding,
publication, migration, and administrator API contracts.

### Use the matching image operation

| Selected operation | Request contract |
| --- | --- |
| Dedicated image generation | The existing Images operation and its model/version-specific options |
| Supported GPT hosted image tool | Azure v1 Responses, selected deployment as top-level `model`, an `image_generation` tool, and forced image-tool choice |

The dated preview workaround is not the Responses image contract. Image operation
settings do not change the chat connection's API version. API Management paths,
authentication conventions, and published operations must be preserved rather than
bypassed to obtain a result.

The UI remains one model selection. There is no required API-mode selector or second
image-backend chooser. Where Azure requires an image deployment/default behind its
tool, that binding must come from verified existing metadata or provider
configuration; SimpleChat must not invent or provision it.

### Preserve the image workflow and report non-success

Chat Image mode, proposal approval, regeneration, and image-specific tests use the
shared generation path. The fix retains generated-image storage, chunk handling,
proposal linkage, and revision history instead of treating the provider result as
the completed application workflow.

Text-only replies, refusals, failed/incomplete image calls, and empty image data are
not successful generation. User-facing failures distinguish unavailable
configuration/service capability from content rejection or rate limiting; operational
diagnostics must not expose credentials or raw SDK exceptions to the browser.

`image_generation_error_response()` supplies a safe `error` and `error_code`, with
`rate_limited: true` for throttling. Its error mapping separates disabled capability
(`403`), unavailable configuration/service (`503`), content/request rejection (`400`),
rate limits (`429`), and incomplete or other technical failures (`502`).

Existing direct-image masked editing remains subject to its model/API restrictions.
Responses images use whole-image regeneration. Reference-image and multi-turn
Responses editing are not introduced by this fix.

## Relevant files

| File | Responsibility |
| --- | --- |
| `functions_ai_connections.py` | Capability eligibility and server-only image binding |
| `functions_ai_connection_migration.py` | Idempotent, conditional import of legacy image settings |
| `functions_image_api_route.py` | Image operation selection, Responses tool specification, and output handling |
| `functions_image_generation.py` | Shared image request entry point and generated-message deployment metadata |
| `functions_image_edit.py` | Preserve masked-edit restrictions and use the shared path for regeneration |
| `route_backend_chats.py` | Chat image request integration and safe failures |
| `route_backend_settings.py` | Image-specific test path |
| `route_backend_v2.py` | Shared default API and unavailable-default notices |
| `application/single_app/config.py` | Application version `0.261.105` |

Unless qualified, application files above are under `application/single_app/`.

## Validation and impact

| Before | After |
| --- | --- |
| A GPT/chat name was treated as sufficient evidence of image output | Shared selection requires declared/catalog-supported image capability and a compatible provider operation |
| A dated Responses preview was assumed to support the image tool | The hosted image operation uses Azure v1 Responses |
| A provider image could be followed by an undefined-variable failure | The selected image deployment is retained for generated-message metadata |
| Endpoint and key configuration were duplicated for images | Chat and images can reference a shared connection while keeping independent defaults |
| Repeated prompts obscured configuration problems | No-image and unsupported/configuration outcomes are failures, not successful text replies or automatic model substitutions |

`functional_tests/test_ai_connection_image_migration.py` covers legacy route/model
preservation, stable IDs, failures, and concurrent settings changes.
`functional_tests/test_ai_connection_defaults_api.py` covers shared reference
validation, independent defaults, safe catalogs, and explicit clearing.
`functional_tests/test_image_generation_responses_route.py` covers the image request
and response contracts; image/client, editor, proposal, and persistence regressions
must also protect the end-to-end application workflow.

These are regression-coverage boundaries, not a claim that every provider deployment
has been tested live. A deployment must produce an actual persisted image to establish
live success. Discovery, a mocked image response, or a successful GPT text response
does not establish Azure image readiness.

## Azure prerequisites and references

Azure documentation differs on whether the Responses image tool can use a service
default or requires an explicit image-deployment binding. A GPT-only resource is not
guaranteed to generate images. Region, entitlement, deployment access, gateway
operations, and any required image backend must be verified on an authorized existing
resource. No Azure provisioning is part of this fix.

- [Azure OpenAI Responses API](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/responses)
- [Azure OpenAI API version lifecycle](https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle)
- [Dated 2025-04-01-preview schema](https://github.com/Azure/azure-rest-api-specs/blob/main/specification/cognitiveservices/data-plane/AzureOpenAI/inference/preview/2025-04-01-preview/inference.json)
- [Azure v1 schema](https://github.com/Azure/azure-rest-api-specs/blob/main/specification/ai/data-plane/OpenAI.v1/azure-v1-v1-generated.json)
- [Responses image-generation feature](../features/IMAGE_GENERATION_RESPONSES_MODELS.md)
- [Configure AI connections](../../guides/configure-ai-connections.md)
