---
layout: page
title: "AI Models settings"
description: "Configure shared chat and image connections, independent task defaults, embeddings, APIM, and model request identity."
section: "Administration"
audience: admin
admin_tab: ai-models
version: "0.261.105"
---


# AI Models settings

## What this group controls

AI Models configures chat, embedding, image generation, APIM, multi-endpoint routing, and model endpoint identity behavior. Chat and images can now use the same AI Connections registry with independent defaults; embedding and other service configuration remain separate.

## Why it matters

Model endpoints are production dependencies for every generated answer, embedding, and image. Keep deployment names, API versions, and authentication choices aligned with the Azure resources operators support.

{% include media.html src="admin-settings/ai-models.png" alt="Screenshot of the AI Models group in Admin Settings." title="AI Models settings" %}

{% include media.html type="video" title="AI Models settings walkthrough" poster="video-posters/admin-ai-models.png" capture="Recording planned. Walk through each tab in the AI Models group and explain when to change each setting." %}

## Before you change anything

- Provision Azure OpenAI, APIM, and image resources before pointing SimpleChat to them.
- Choose key or managed identity authentication and grant required permissions.
- Identify the models used by background tasks before retiring a connection.

## AI Connections {#model-endpoints}

### Shared connection manager {#multi-endpoint-configuration}

A connection records a resource's address, provider, authentication, and deployed models. Configure those details once, then select compatible models for chat or image generation without copying endpoint and key settings into each task. Different resources remain separate connections, including an image-only resource in another region.

**Use AI Connections for chat** controls chat only. With it off, chat uses the classic endpoint under Chat, but image generation can still use AI Connections. Do not enable this irreversible chat switch merely to configure images.

Each connection is stored on its own. Adding, editing, or deleting one takes effect when you save that connection, rather than when the surrounding settings page is saved. Task defaults retain connection/model IDs, so equally named deployments on different resources are not confused.

For a task-oriented walkthrough, see [Configure AI connections]({{ '/guides/configure-ai-connections/' | relative_url }}).

### Authentication and model discovery

The authentication method determines whether SimpleChat can enumerate a resource's deployments for you:

- **Managed identity** and **service principal**, with the required read permissions, can list existing deployments through Azure Resource Manager or the Foundry project API. For an Azure OpenAI resource this needs the subscription id and resource group, because that is how the deployment list is addressed.
- **API key** authenticates to inference only. Discovery is unavailable, so deployment names have to be entered by hand.

Discovered models arrive switched off. Finding a deployment is not the same as publishing it, so each one has to be enabled and made available for the intended task before it can be selected. Discovery includes supported image models as well as chat models; it does not perform paid image generation or prove that an image operation works.

Secrets are never returned to the browser. When a key or client secret is already stored, its field shows that it exists and stays empty; leaving it empty keeps the stored value, and typing a new one replaces it. Deleting a connection removes the secrets it owned.

### Identity header

Model requests reach a gateway under SimpleChat's own credentials, so a gateway cannot tell one user's traffic from another's. The identity header adds a header naming the signed-in user, which lets a gateway attribute usage or apply per-user quotas. The value is HMAC-hashed before it leaves SimpleChat, and a request with no identity omits the header rather than sending a blank one.

Individual connections can override the global choice, which is useful when only some of them sit behind a gateway that expects the header.

### Image input versus image generation

Each model within a connection also records whether it can accept image input. This is what
[Multi-Modal Vision Analysis](knowledge.md#multimodal-vision-section) requires alongside text output, and
getting it wrong is only discovered when a document fails to process.

The checkbox arrives pre-filled. The application ships capability data for known models and
uses it to answer the question before you are asked, and the field says where its answer
came from:

- **Set here** — recorded on this model. This wins over everything else.
- **From the built-in model capability data** — matched against the shipped catalog, by
  model id or a declared alias, including deployments named after a known model with a
  suffix such as a date or region.
- **Inferred from the model name** — neither of the above matched, so the name was used as
  a guess. This is the case worth reviewing: a self-hosted or internally named model may
  well read images without its name saying so.

Correcting the checkbox records your answer on the model, and it is then used in preference
to the catalog from that point on.

Accepting image input is not the same as generating images. Chat output and image
generation have separate capability information, and a model can be technically
capable of both while being published for only one task. Known image-only models
are not offered as text-chat models.

Image-tool support uses exact catalog IDs, declared aliases, or valid dated
snapshots. An arbitrary `gpt-4o-*` variant does not gain image generation merely
by sharing a prefix. The vision/name fallback described above remains separate.

Technical support does not prove current service readiness. An enabled model can
still fail because of provider permissions, quota, gateway operations, or missing
image-tool access. Do not declare image support simply because the model can accept
pictures or call generic tools.

### Connection settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Use AI Connections for chat | Migrates chat from the classic endpoint to shared connections. Switching this on cannot be undone; it carries over the classic chat configuration when needed without replacing image connections. | Off | `enable_multi_model_endpoints`; chat-only capability toggle, not required for images |
| AI Connections | Shared resource/authentication/model records, each saved individually. Chat and image defaults reference these records. | Empty before configuration/import | `model_endpoints`; edited through its own API |
| Model availability | Limits a model to the supported tasks administrators intend to publish. Changing availability does not change the model's technical capabilities. | No task-specific restriction when absent | Model `enabled_capabilities`; `chat` and `image_generation` are the implemented operations |
| Send an identity header with model requests | Adds a header identifying the signed-in user to every model request. | Off | `model_endpoint_identity_header_enabled` |
| Header name | Rejected if it collides with a header the model call already sets, such as `authorization`. | x-simplechat-identity-key | `model_endpoint_identity_header_name` |
| Identity sent in the header | Object id is stable across a rename; UPN is readable in gateway logs. Tenant variants qualify the value for a multi-tenant gateway. | Object id and tenant id | `model_endpoint_identity_header_value_type` |

### Chat {#gpt-config}

SimpleChat has two ways to reach a chat model and only one of them is in force at a time. When **Use AI Connections for chat** is on, chat draws from the connections above. When it is off, chat runs on a single classic endpoint — one Azure OpenAI resource, or API Management in front of one — whose address, credentials, API version and deployment are configured on the server-rendered admin page rather than here.

That distinction is worth stating because the two are easy to confuse: connections can be configured and serving images while chat still uses the classic route. This section names the chat route that is actually live, and links to the classic page when that route is the classic one.

Turning connections on is not reversible from the admin interface. The setting is stored as "already on or newly on", so an attempt to switch back is refused rather than silently discarded. When the registry has no chat-eligible configuration, the switch carries the classic chat endpoint into it without replacing imported image connections. Treat it as a chat migration.

### Default model

The default model is the one chat uses when nothing else has chosen — a conversation started before the user has picked anything, or work that begins outside the chat window. It is stored as a reference to a connection and one of that connection's models, not as a copy of the model, so it outlives what it names: deleting a connection, disabling one, or switching off a single model all leave it pointing at nothing.

Rather than let that reference decay into a silent fallback to some other model, SimpleChat clears it whenever the thing it names stops being available, and says so. Only chat-compatible models published on an enabled connection can be chosen. An image-only model cannot become the chat default merely because it is enabled.

The default applies to connections only. With chat on the classic single endpoint there is nothing for it to select from, and a choice made in that state is refused rather than stored.

### Chat settings

The classic single endpoint is configured on the server-rendered admin page. Its values are listed here because they are what chat uses while **Use AI Connections for chat** is off, and because API Management applies to GPT requests that use the classic endpoint whichever mode chat is in.

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Default model | The model chat uses when nothing else has chosen one. Cleared automatically if the connection or model it names is deleted or disabled. | Not specified in defaults | `default_model_selection`; connections mode only |
| Send requests through API Management | Routes GPT requests that use the classic endpoint through API Management rather than straight to the Azure OpenAI resource, so a deployment can apply its own governance and monitoring to them. Set on the classic page only — a connection carries its own API Management configuration, so this tab does not offer it. | Off | `enable_gpt_apim`; needs the three APIM values below |
| Azure OpenAI Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Empty | `azure_openai_gpt_endpoint` |
| Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `azure_openai_gpt_authentication_type` |
| Subscription ID | Addresses the resource when listing its deployments. | Empty | `azure_openai_gpt_subscription_id` |
| Resource Group | Addresses the resource when listing its deployments. | Empty | `azure_openai_gpt_resource_group` |
| Azure OpenAI GPT Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_openai_gpt_key` |
| Azure OpenAI API Version | Pins the service API version SimpleChat sends with requests for this feature. | 2024-05-01-preview | `azure_openai_gpt_api_version` |
| Azure APIM Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Empty | `azure_apim_gpt_endpoint` |
| Azure APIM API Version | Pins the service API version SimpleChat sends with requests for this feature. | Empty | `azure_apim_gpt_api_version` |
| Azure APIM Deployment | Each model defined here will be available in the Chat UI as an option for the User. You can include multiple models seperated by a comma (example: gpt-4o, o-1, o-3). | Empty | `azure_apim_gpt_deployment` |
| Azure APIM Subscription Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_apim_gpt_subscription_key` |

## Embeddings {#embeddings}

### Embeddings {#embeddings-config}

Embeddings turn text into vectors so a document can be found by meaning rather than by exact words. Every workspace document is embedded when it is indexed, and every question is embedded when it is asked, which makes this route a dependency of search itself rather than of chat: with it misconfigured, indexing fails and citations stop being found, while chat continues to answer from whatever it is given.

Unlike chat, embeddings have no connections list. There is one Azure OpenAI resource, or API Management in front of one, and it is configured here.

#### Direct or through API Management

The two routes are alternatives, and only the selected one is used. Switching to APIM does not carry the direct settings over — the gateway has its own address, version, deployment name and subscription key — so the fields for the route you are not using stay out of the way rather than sitting there looking configured.

#### Authentication and deployment discovery

Managed identity avoids storing a credential at all, and it is also what allows SimpleChat to list the resource's deployments for you. That listing goes through Azure Resource Manager, which is why it needs the subscription id and resource group as well as the endpoint: inference is addressed by URL, but a deployment list is addressed by resource. A key authenticates to inference only.

**Fetch deployments** reads the *saved* endpoint, subscription id and resource group, not what is currently on screen, so save changes to those before fetching. The list it returns is a cache of that answer: it can name a deployment that has since been removed, and a deployment the resource no longer reports is dropped from the selection rather than left to fail on the next embedding call.

The stored key is never shown. Its field stays empty whatever is stored, and leaving it empty keeps the stored key rather than clearing it, so saving an API version cannot wipe a working credential. Typing a value replaces it, and **Remove stored value** clears it.

#### Changing the embedding model

An embedding is only comparable with other embeddings from the same model. Changing the deployment does not re-embed what is already indexed, so existing chunks keep the dimensions and the semantics of the model that wrote them, and search quality across the two sets degrades quietly rather than failing. Treat a model change as a re-index.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Use APIM instead of direct to Azure OpenAI endpoint | Sends embedding requests through API Management rather than straight to the Azure OpenAI resource. Only the selected route is used. | Off | `enable_embedding_apim`; capability toggle |
| Azure OpenAI Embedding Endpoint | The Azure OpenAI resource that produces vectors. Independent of the chat endpoint. | Empty | `azure_openai_embedding_endpoint` |
| Authentication Type | Managed identity stores no credential and enables deployment discovery; a key authenticates to inference only. | key | `azure_openai_embedding_authentication_type` |
| Subscription ID | Addresses the resource when listing its deployments. Inference does not need it. | Empty | `azure_openai_embedding_subscription_id` |
| Resource Group | The other half of the address the deployment list is fetched from. | Empty | `azure_openai_embedding_resource_group` |
| Azure OpenAI Embedding Key | Used only with key authentication. Leaving it blank keeps the stored key. | Empty | `azure_openai_embedding_key` |
| Embedding model | The single deployment every stored embedding comes from. Changing it does not re-embed existing documents. | None selected | `embedding_model`; written through its own API |
| Azure OpenAI Embedding API Version | Pin only when a deployment needs a version other than the default; an unsupported value fails every embedding call. | 2024-05-01-preview | `azure_openai_embedding_api_version` |
| Azure APIM Endpoint | The API Management address that fronts the embedding deployment. | Empty | `azure_apim_embedding_endpoint` |
| Azure APIM API Version | Whatever version the API Management operation publishes; there is no default, because a gateway can publish any. | Empty | `azure_apim_embedding_api_version` |
| Azure APIM Deployment | The deployment name to send embedding requests to. Discovery does not reach through a gateway, so this is typed. | Empty | `azure_apim_embedding_deployment` |
| Azure APIM Subscription Key | Leaving it blank keeps the stored key. | Empty | `azure_apim_embedding_subscription_key` |

## Image Generation {#image-generation}

### Image Generation {#image-config}

Image generation gives chat a tool that produces pictures from a prompt. It is off by
default and has its own global default model, selected from AI Connections. That model
can share a resource with chat or use a separate image-only connection.

The image feature does not depend on **Use AI Connections for chat**. Its default can be
configured while images are disabled, and saving a default does not turn either feature
on. Embedding, speech, and other service settings are unchanged.

### Choose the image default

Choose one image-compatible model from the picker grouped by connection. Its saved
reference identifies the connection and model, not just a deployment name. Two resources
can each have a deployment called `production`; their connection labels distinguish
the choices and their IDs keep requests on the intended resource.

The connection and model must be enabled, technically support the image operation
through their provider, and publish image generation. Changing the chat default does
not change this selection. Users keep the existing chat **Image** control; no second
per-chat image-model picker is introduced.

Deleting or disabling the selected connection/model, or withdrawing its image
availability, invalidates the default with a notice. Choose a compatible replacement;
SimpleChat does not silently substitute another model.

### Which API produces the image

A compatible dedicated image deployment uses the Images API. A GPT deployment with
established hosted-image-tool support uses Azure v1 Responses with the
`image_generation` tool. Capability and connection metadata select the route internally:
there is no mandatory API-mode setting or second backing-image chooser.

Not every GPT or Responses deployment supports image generation. A GPT-only resource is
not guaranteed to work: any required image backend/default, entitlement, and provider
permissions must already be available and verified. Generic tools or image-input support
are not enough, and SimpleChat does not guess or provision a missing deployment.

Responses image generation offers whole-image regeneration in SimpleChat, not masked
editing. Existing direct-image masked editing remains subject to the selected model
and Images API support.

New shared Images connections without an image-specific API version use
`2025-04-01-preview` for generations and edits. Explicit image operation versions,
including older imported versions, are preserved. Unmigrated legacy Images settings
retain their `2024-12-01-preview` fallback when no image version is configured.

These versions do not come from the chat connection's API version or legacy root
settings after shared selection. The hosted image tool instead uses v1 Responses
without a dated `api-version` query. No image operation changes the chat API version.

### Direct connections and API Management

Store the intended route and credentials in the selected connection. An APIM-backed
connection must retain its gateway path, authentication convention, and supported
operation; a failing gateway request must not be redirected to the backend resource.

Imported legacy APIM image configurations retain their Images route. A shared model
configured for Responses still needs the gateway to publish the matching operation.
Discovery/read permissions and image-inference permissions are separate, so test the
image operation rather than relying on a successful deployment listing or chat test.

### Existing installations and import warnings

Startup imports configured direct and APIM image settings into AI Connections, or
reuses a compatible connection. It preserves the active deployment, credentials, and
operation settings. Newly imported model records initially publish images only,
without changing chat mode or enabling image generation.

The original legacy values remain as backup. After successful import or an explicit
shared-default save, the image reference is authoritative: clearing it does not revive
the old route. The normal configuration workflow no longer needs a duplicate image
endpoint/key form.

A failed import shows a warning and retains legacy image operation. Review the safe
notice and `[AI_CONNECTIONS]` server logs, correct the identified settings or
permissions, and restart to retry. Do not remove working legacy credentials during
recovery.

### Image settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Image Generation | Makes the Image task available in chat. Disabling it stops image requests without changing either task's default. | Off | `enable_image_generation`; independent capability toggle |
| Default image model | The global image model selected from shared connections, independently of the chat default. | None until imported or selected | `image_generation_model_selection`; connection/model/provider reference |

### Legacy image values retained for import

These are the pre-migration image fields, not a second active configuration system.
They remain operational only while import is incomplete and no shared selection has
been saved. After import, edit the shared connection and image default instead.

For API integrations, both `GET` and `PUT /api/v2/admin/model-selection/image`
return `409` with `code: image_catalog_migrated` after import or an explicit shared
selection. This is an intentional handoff, not a successful legacy save. Read or
write the current image reference through
`/api/v2/admin/capability-models/image_generation` instead. The legacy embedding
model-selection API is unchanged.

| Legacy value | What the import preserves | Original default | Settings key |
| --- | --- | --- | --- |
| Use APIM for images | Which legacy route was active when selecting the imported default | Off | `enable_image_gen_apim` |
| Azure OpenAI Image Generation Endpoint | Direct resource address | Empty | `azure_openai_image_gen_endpoint` |
| Authentication Type | Direct image authentication method | key | `azure_openai_image_gen_authentication_type` |
| Subscription ID | Direct-resource discovery context | Empty | `azure_openai_image_gen_subscription_id` |
| Resource Group | Direct-resource discovery context | Empty | `azure_openai_image_gen_resource_group` |
| Azure OpenAI Image Generation Key | Direct-route credential, through scoped secret helpers | Empty | `azure_openai_image_gen_key` |
| Image model | Active direct deployment and saved model metadata | None selected | `image_gen_model` |
| Azure OpenAI Image Gen API Version | Direct Images operation version; not the Azure v1 Responses contract | 2024-12-01-preview | `azure_openai_image_gen_api_version` |
| Azure APIM Endpoint | Gateway address and path | Empty | `azure_apim_image_gen_endpoint` |
| Azure APIM API Version | Gateway image operation version | Empty | `azure_apim_image_gen_api_version` |
| Azure APIM Deployment | Active gateway deployment name | Empty | `azure_apim_image_gen_deployment` |
| Azure APIM Subscription Key | Gateway credential and existing authentication convention | Empty | `azure_apim_image_gen_subscription_key` |


## Common tasks

1. **Publish models from a new resource.** Add a connection, configure its provider/authentication, discover or enter deployments, then enable and publish the intended operations. Save the connection. Outcome to verify: compatible models appear in the corresponding task picker, not every picker.
2. **Rotate a stored connection key.** Edit the connection, type the replacement into the empty secret field, and save. Outcome to verify: each task using that connection works with the replacement; no copied image key needs updating.
3. **Choose the model chat starts from.** With connections in force, pick a default under Chat. Outcome to verify: a new conversation opens on that model without anyone selecting it.
4. **Retire a connection.** Disable it, review affected chat/image defaults, and select replacements before deleting it. Outcome to verify: its models stop being offered and unavailable defaults are reported instead of silently substituted.
5. **Configure embeddings.** Set the endpoint, authentication and — with managed identity — the subscription id and resource group, then save. Fetch the deployments, choose one, and index a small document. Outcome to verify: indexing completes and the document's citations are found by a question that does not repeat its wording.
6. **Enable image generation.** Select an image-compatible model from AI Connections, then enable the image feature. Outcome to verify: a real Image request returns and stores a picture from that binding without changing chat mode.
7. **Rotate an embedding key.** Update the embedding route's own stored key and save. Outcome to verify: indexing still works. Image keys are rotated in their shared connection instead.
8. **Move images behind API Management.** Configure an APIM-backed connection with the published path, authentication, and image operation, then select its image model. Outcome to verify: generation succeeds through the gateway and no request bypasses it.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A connection's models never appear in chat | Chat may still use the classic endpoint, or the models may not be chat-compatible and published. | Check the chat route and model availability. Do not enable the irreversible chat switch just to use images. |
| **Use AI Connections for chat** will not turn off | Enabling connections is one-way, because chats, agents and workflows may already reference a model published from one. | Disable the individual connections instead, or point chat at the model you want by making it the default. |
| **Discover models** is unavailable | The connection authenticates with an API key, which reaches inference but not Azure Resource Manager. | Switch to managed identity or a service principal, or add the deployment names by hand. |
| Discovery returns nothing for an Azure OpenAI connection | The subscription id or resource group does not match the resource. | Correct them, then run **Test connection** before discovering again. |
| Models are listed but nobody can choose them | Discovery does not publish models; they may be disabled or unavailable for the requested task. | Enable the connection/model and publish a technically supported operation. |
| A default model reverted to none | The connection/model was deleted, disabled, or made incompatible/unpublished. | Review the notice and select a compatible published model. No alternate image or legacy default is substituted. |
| The chat default model list is empty | Chat may be on the classic route, or no connection has an enabled chat-compatible published model. | Check chat mode and publication. Changing chat mode is a migration, not an image prerequisite. |
| A chat default choice is refused | Chat is on the classic single endpoint. | Keep the classic configuration or deliberately migrate with **Use AI Connections for chat**. |
| The image default list is empty | No enabled connection has a supported, published image model. | Check image capabilities, provider support, and publication in AI Connections; do not change chat mode. |
| Embeddings fail during indexing | Endpoint, deployment, API version, or authentication does not match the Azure resource. | Validate the embedding route with a small document before bulk indexing. |
| **Fetch deployments** returns nothing | Either the endpoint, subscription id and resource group do not name the resource the deployment lives in, or those changes have not been saved yet — fetching reads the saved values. | Save the connection details first, then fetch again. |
| **Fetch deployments** is refused | The route authenticates with a key, which reaches inference but not Azure Resource Manager. | Switch to managed identity, and grant it read access to the resource. |
| An embedding deployment disappeared from the list | The deployment was removed or renamed in Azure, so discovery no longer reports it. The selection is cleared rather than kept, because a request naming it would fail. | Choose a replacement from the refreshed list. |
| Search quality dropped after changing the embedding model | Embeddings are only comparable with others from the same model, and existing chunks were not rewritten. | Re-index the affected workspaces so every chunk comes from one model. |
| A key was cleared without anyone changing it | Nothing in the V2 admin surface clears a secret by saving an empty field, so check the classic admin page, where a blank key field does store a blank. | Re-enter the key. Use the V2 surface's **Remove stored value** when removal is what you want. |
| Image generation is configured but never offered | **Enable Image Generation** is off. | Enable it and verify the shared image default. |
| A GPT responds with text or rejects the image tool | That deployment/resource or gateway may lack the required image operation or backend binding. | Verify image-specific support and permissions on the selected resource; a successful chat test is not sufficient. |
| Image import reports a warning | Connection, settings-write, or Key Vault preparation did not complete. | Retain working legacy values, correct the reported problem, and restart to retry. |
| Images stop after clearing an imported default | The shared selection is authoritative and no longer falls back to legacy values. | Choose a new shared image default or disable image generation. |

## Related

- [Configure AI connections]({{ '/guides/configure-ai-connections/' | relative_url }})
- [Generate images]({{ '/guides/generate-images/' | relative_url }})
- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Agents & Actions settings]({{ '/admin/agents-actions/' | relative_url }})
- [Chat settings]({{ '/admin/chat/' | relative_url }})
