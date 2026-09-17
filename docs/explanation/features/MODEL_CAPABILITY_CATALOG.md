# Provider-qualified model capability catalog (v0.261.108)

## Overview

The catalog describes model behavior so SimpleChat can offer an operation before a
user pays for an incompatible request. Image input, text output, native image output,
and image-tool orchestration are different facts. A publisher's API documentation
does not automatically establish the same operation on another hosting provider.

Implemented in version: **0.261.107** for provider-qualified image profiles.
Application versioning is tracked in `application/single_app/config.py`.
Embedding policies and provider-qualified image profiles are combined in **0.261.108**.

**Dependencies:** the repository-managed JSON catalog and schema, the pure model/image
capability helpers, and implemented image adapters. The existing vision and reasoning
resolvers remain in place; image profiles do not replace their contracts.

The catalog is not a new administrator editing page. Existing connection, default
picker, and image-editor surfaces display the relevant server-resolved information.

## Catalog structure

| Location or field | Purpose |
| --- | --- |
| `application/single_app/static/json/model_capabilities.json` | Canonical model records, generic capabilities, source references, and image operation profiles |
| `static/json/schemas/model_capabilities.schema.json` | Catalog version and image profile validation |
| Model `provider` | The publisher, such as OpenAI, Microsoft, or Black Forest Labs; not the saved connection's provider |
| Model `imageProfiles` | Maps an image delivery profile (`openai`, `azure_openai`, or `foundry`) to a named operation profile |
| Model `imageLifecycle` | Provider-specific current, preview, deprecated, or retired status |
| `imageOperationProfiles` | Reusable API/edit/mask/options/availability facts |
| `generatesEmbeddings` and model `embeddingPolicy` | Embedding output, verified dimensions, input/batch limits, and operation requirements; independent of image and chat capabilities |
| `sources` and `sourceIds` | Official documentation supporting the facts |

For example, a GPT chat model's direct OpenAI image-tool profile is distinct from a
dedicated GPT Image model's direct OpenAI and Azure Images profiles. Reusing a
canonical model record avoids duplicate identifiers with conflicting aliases.

Image operation profiles record the implemented API (`images`, `responses`, `mai`,
or `flux`), source-image editing, uploaded masks, supported rendering choices,
formats, relevant limits, and cloud availability. Kontext additionally uses the
documented `openai_images` transport variant of the Foundry FLUX integration.

Generation-only and reference-editing models do not acquire uploaded-mask support
from an inpainting description. A known image-only model does not become a text-chat
or text-producing vision-analysis choice.
Known embedding-only models likewise remain excluded from chat, image generation,
and text-producing vision analysis, including when a Custom declaration requests
an incompatible operation.

## Resolution and policy

`functions_model_capabilities.py` loads the JSON once. Public model and operation
lookups return isolated copies, including nested profiles, so a consumer cannot
change another consumer's cached capability facts.

`functions_image_capabilities.py` resolves image operations using the model and saved
endpoint context. It identifies delivery and cloud from the configured provider/API
and endpoint, not from the application's hosting environment or management authority.
Known Azure endpoints cannot masquerade as direct OpenAI by selecting a generic API
label.

Image qualification applies the following boundaries:

1. The connection must have an implemented image adapter.
2. Known provider/API restrictions and lifecycle facts remain authoritative.
3. A matching catalog profile supplies the known model's operation automatically.
4. Unknown Custom models require a compatible explicit image operation and generation
   declaration. Editing and masking require separate support.
5. The connection/model must be enabled and publish the image capability before it
   becomes a task choice.
6. The feature switch and a valid global image default are required for execution.

SimpleChat deliberately supports dedicated image models only on Azure/Foundry.
Microsoft documents an Azure Responses image tool backed by a separate image
deployment, but that conditional orchestration route is not integrated here.
Publisher-level `imageGenerationTool` flags and administrator declarations cannot
enable it. Direct OpenAI tool generation belongs in a Custom OpenAI connection.

Exact identifiers, declared aliases, and valid dated snapshots are recognized.
Arbitrary new GPT versions or suffix variants do not inherit image support from a
name prefix. An administrator may describe a new compatible Custom model without
waiting for a catalog release, but the description is not a live service test.

## Cloud availability and residency

An endpoint's cloud is independent of the host running SimpleChat. A Government-hosted
installation can use an approved commercial Azure or direct OpenAI connection.
That service remains commercial; the catalog does not authorize data transfers.

The reviewed Government table does not establish availability of the image models
covered by this integration. Their Government availability remains **unknown**.
Missing documentation is not an explicit unavailability statement or a reason to
disable every Government-hosted installation.

Availability evidence, provider lifecycle, implemented capability, publication,
credentials, quota, and live readiness are separate facts. A successful connection
listing or text answer proves neither image generation nor mask support.

## Updating the catalog

Add or revise a canonical model record with source references that actually describe
its provider/API behavior. Prefer a shared operation profile when its contract is
identical; add a distinct profile when URL, payload, editing, mask, format, or option
requirements differ.

Do not assign a broad GPT-family image flag, copy direct OpenAI retirement dates to
Azure, or infer Government availability from a commercial Global Standard offering.
Do not create a provider adapter by adding data alone: an unimplemented protocol
must not become a selectable image feature.

Keep documented provider limits distinct from SimpleChat's upload/decompression
bounds and the options the current single-image workflow actually exposes.
For example, MAI generation uses at least 768 pixels per dimension and at most
1,048,576 pixels in total; that is not the GPT landscape/portrait preset contract.

## Testing and validation

`functional_tests/test_image_provider_capabilities.py` validates schema/profile
references, provider differences, cloud independence, explicit metadata, lifecycle,
masking, and rendering bounds. `test_ai_connections_capabilities.py` covers nested-copy
isolation, publication, references, and extension contracts.

`test_image_provider_sdk_http.py` exercises provider-specific request construction
with the pinned SDK and mock HTTP. `test_image_edit_provider_operations.py` covers
actual runtime/editor projections, operation forwarding, source edits, regeneration,
and invalid outputs.

Catalog tests do not make provider calls or certify subscription capacity. Use an
explicitly authorized image-operation test against an existing configured service
to establish live readiness.

## Related

- [Shared AI Connections](AI_CONNECTIONS_FRAMEWORK.md)
- [Provider-aware image generation](IMAGE_GENERATION_RESPONSES_MODELS.md)
- [Provider capability fix](../fixes/IMAGE_PROVIDER_CAPABILITIES_FIX.md)
- [Configure AI connections](../../guides/configure-ai-connections.md)
