# Provider-qualified image generation and editing (v0.261.107)

## Issue and root cause

SimpleChat applied publisher-level OpenAI image-tool facts to Azure OpenAI and
Foundry endpoints. A GPT chat deployment could therefore appear as an image choice
without a usable image operation. Editing was inferred from a name marker, and
models with reference-image APIs but no uploaded-mask contract were indistinguishable
from generation-only models.

The image runtime also assumed Azure/OpenAI URL, parameter, and model-identity
conventions for every provider. Those conventions do not describe the native MAI or
FLUX APIs, or direct OpenAI configured through a Custom connection.

Fixed/Implemented in version: **0.261.107**.
Application version: `application/single_app/config.py`.
Related foundations: shared AI Connections in #1436 and the Custom endpoint
implementation in #1437. No separate issue was created for this work.

## Product policy versus provider documentation

Microsoft documents Azure Responses image generation backed by a separate GPT Image
deployment. This change does not claim that Azure categorically lacks that tool.
The agreed SimpleChat policy deliberately offers **dedicated image models only on
Azure/Foundry**. GPT image-tool orchestration is available through qualified direct
OpenAI Custom endpoints.

An Azure GPT model remains eligible for its supported chat/vision/reasoning tasks.
It cannot regain image eligibility through a stale declaration, a forged capability
projection, or a saved Responses profile.

## Catalog and endpoint qualification

The JSON catalog separates publisher, hosting/API profile, endpoint cloud, image
operations, lifecycle, options, and availability evidence. Common operation profiles
are referenced by canonical model records; aliases do not create duplicate identities.

The effective endpoint matters, not `AZURE_ENVIRONMENT`. A Government-hosted
application can call an approved commercial endpoint without relabeling it as a
Government service. The reviewed Government table does not establish availability
of the image models covered here, so that fact remains unknown rather than becoming
invented availability or a blanket ban.

Unknown Custom models require an explicit compatible operation. Generation, reference
editing, and masking are independent capabilities. Known provider/adapter restrictions
take precedence, and generic vision/tool support is never image-generation evidence.

## Image operations

| Integration | Contract and behavior |
| --- | --- |
| Direct OpenAI Custom | OpenAI Images or Responses, provider model names, configured Custom authentication/transport, and no Azure deployment-routing header |
| Azure GPT Image | Dedicated deployment Images operations with image-specific API versions; explicit imported versions and APIM prefixes remain intact |
| MAI Image 2.5/2.6 | `/mai/v1/images/generations` JSON and `/mai/v1/images/edits` multipart reference images; PNG output and no undocumented mask parameter |
| FLUX.2 | Explicit Foundry BFL paths and base64 source-image fields; generation and reference editing use their documented per-operation parameters |
| FLUX-1.1-pro | Native Foundry generation; no source-edit or mask capability is claimed |
| FLUX.1-Kontext-pro | Documented v1 Images-compatible generation/multipart reference editing; not a guessed native width/height/mask payload |

For native FLUX generation, the documented pro example uses `num_images: 1`, flex
omits count, and Microsoft's native 1.1 notebook uses `n: 1`. The application does
not send both spellings or assume one universal payload. It does not import direct
BFL's asynchronous polling protocol into Foundry.

The editor distinguishes changing the existing image from creating a new image from
its prompt. Masks are sent only for a supported mask operation. Unsupported/stale
masks or rendering options fail explicitly rather than producing a different paid
operation. Model-specific controls avoid GPT-only parameters on MAI/FLUX.

MAI generation uses dimensions of at least 768 pixels per side and at most
1,048,576 total pixels. Native MAI/FLUX reference edits do not expose size overrides
in this integration; dimension changes use regeneration. Existing application upload
and decompression limits remain separate from provider limits.

## Configuration and migration impact

One global image default still references a saved connection/model pair independently
of chat. There is no new per-chat image picker, duplicate OpenAI credential store,
automatic provider fallback, or activation of the irreversible chat-connection switch.

The Custom connection foundation is selectively forward-ported rather than replacing
newer shared-connection code with the historical patch. Direct OpenAI administrators
use that connection's endpoint, API contract, credentials, and model names.

Connections, credentials, original legacy settings, stored images, and revision
history are retained. An incompatible imported image default receives a replacement
notice; importing it does not grant an unsupported capability or select another model.
Clearing a shared default never revives the legacy route.

## Technical files

Application files below are under `application/single_app/`.

| File | Responsibility |
| --- | --- |
| `static/json/model_capabilities.json` and its schema | Provider-qualified operation profiles and evidence |
| `functions_model_capabilities.py`, `functions_image_capabilities.py` | Cached catalog resolution and effective image qualification |
| `functions_ai_connections.py` | Shared publication, default selection, and binding validation |
| `functions_image_api_route.py` | Wire model identity, operation version, and resource/gateway URL construction |
| `functions_image_adapters.py`, `functions_image_generation.py` | Provider requests, safe failures, and actual image-output validation |
| `functions_image_edit.py` | Mask/source validation, explicit edit/regeneration, and revision integration |
| `functions_ai_connection_migration.py` | Conservative legacy import and incompatible-default notices |
| `route_backend_v2.py` and the React image editor | Safe capability projection and model-specific controls |

## Regression coverage and limitations

`functional_tests/test_image_provider_capabilities.py` exercises provider differences,
hosting-cloud independence, Government unknown availability, explicit Custom metadata,
mask qualification, model-specific dimensions, lifecycle, and catalog/schema integrity.
`functional_tests/test_image_provider_sdk_http.py` exercises the installed, pinned
OpenAI SDK against mock HTTP for actual JSON and multipart request construction.

Existing binding, migration, runtime, proposal, revision, route-policy, and browser
suites protect the surrounding workflows. Mocked responses and documentation review
are not live-provider certification; an authorized service must return and persist
an actual image before an installation treats its connection as ready.

MAI models are preview offerings. Optional Bing web grounding is not enabled.
Foundry FLUX documentation calls for configuring content safety during inference;
do not assume deployment-time filtering or identical safety behavior across providers.
Network policy and organizational approval for cross-cloud transfers remain required.

## References

- [Direct OpenAI image tool](https://developers.openai.com/api/docs/guides/tools-image-generation)
- [Direct OpenAI source and mask editing](https://developers.openai.com/api/docs/guides/image-generation)
- [Azure Responses](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/responses)
- [Azure dedicated image APIs](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/dall-e)
- [Foundry MAI Image](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-mai-image)
- [Foundry FLUX](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-flux)
- [Azure Government models](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-gov)
