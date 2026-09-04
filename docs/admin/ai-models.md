---
layout: page
title: "AI Models settings"
description: "AI Models configures chat, embedding, image generation, APIM, multi-endpoint routing, and model endpoint identity behavior."
section: "Administration"
audience: admin
admin_tab: ai-models
---


# AI Models settings

## What this group controls

AI Models configures chat, embedding, image generation, APIM, multi-endpoint routing, and model endpoint identity behavior.

## Why it matters

Model endpoints are production dependencies for every generated answer, embedding, and image. Keep deployment names, API versions, and authentication choices aligned with the Azure resources operators support.

{% include media.html src="admin-settings/ai-models.png" alt="Screenshot of the AI Models group in Admin Settings." title="AI Models settings" %}

{% include media.html type="video" title="AI Models settings walkthrough" poster="video-posters/admin-ai-models.png" capture="Recording planned. Walk through each tab in the AI Models group and explain when to change each setting." %}

## Before you change anything

- Provision Azure OpenAI, APIM, and image resources before pointing SimpleChat to them.
- Choose key or managed identity authentication and grant required permissions.
- Name fallback deployments deliberately so background tasks use approved models.

## Connections {#model-endpoints}

### Connections {#multi-endpoint-configuration}

A connection is one Azure OpenAI or Azure AI Foundry resource: where it is, how SimpleChat authenticates to it, and which of its deployed models may be used. Several connections can serve models at once, so a deployment in one subscription and a Foundry project in another can both appear in the chat model picker.

Connections are consulted only when **Use connections for chat** is on. With it off, chat runs on the single classic endpoint configured under Chat instead, and anything listed here is ignored.

Each connection is stored on its own. Adding, editing or deleting one takes effect when you save that connection, rather than when the surrounding settings page is saved.

#### Authentication and model discovery

The authentication method determines whether SimpleChat can enumerate a resource's deployments for you:

- **Managed identity** and **service principal** can reach Azure Resource Manager, so **Discover models** lists the deployments the resource already has. For an Azure OpenAI resource this needs the subscription id and resource group, because that is how the deployment list is addressed.
- **API key** authenticates to inference only. Discovery is unavailable, so deployment names have to be entered by hand.

Discovered models arrive switched off. Finding a deployment is not the same as publishing it, so each one has to be turned on before people can pick it.

Secrets are never returned to the browser. When a key or client secret is already stored, its field shows that it exists and stays empty; leaving it empty keeps the stored value, and typing a new one replaces it. Deleting a connection removes the secrets it owned.

#### Identity header

Model requests reach a gateway under SimpleChat's own credentials, so a gateway cannot tell one user's traffic from another's. The identity header adds a header naming the signed-in user, which lets a gateway attribute usage or apply per-user quotas. The value is HMAC-hashed before it leaves SimpleChat, and a request with no identity omits the header rather than sending a blank one.

Individual connections can override the global choice, which is useful when only some of them sit behind a gateway that expects the header.

#### Image support

Each model within a connection also records whether it can accept image input. This is what
[Multi-Modal Vision Analysis](knowledge.md#multimodal-vision-section) filters on, and
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

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Use connections for chat | Routes chat through the connections listed here instead of the single classic endpoint. Switching this on cannot be undone, and carries the classic endpoint over as the first connection. | Off | `enable_multi_model_endpoints`; capability toggle |
| Connections | The list of model connections, each saved on its own. | Empty | `model_endpoints`; edited through its own API |
| Send an identity header with model requests | Adds a header identifying the signed-in user to every model request. | Off | `model_endpoint_identity_header_enabled` |
| Header name | Rejected if it collides with a header the model call already sets, such as `authorization`. | x-simplechat-identity-key | `model_endpoint_identity_header_name` |
| Identity sent in the header | Object id is stable across a rename; UPN is readable in gateway logs. Tenant variants qualify the value for a multi-tenant gateway. | Object id and tenant id | `model_endpoint_identity_header_value_type` |

### Chat {#gpt-config}

SimpleChat has two ways to reach a chat model and only one of them is in force at a time. When **Use connections for chat** is on, chat draws from the connections above. When it is off, chat runs on a single classic endpoint — one Azure OpenAI resource, or API Management in front of one — whose address, credentials, API version and deployment are configured on the server-rendered admin page rather than here.

That distinction is worth stating because the two are easy to confuse: connections can be fully configured and still be unused, with nothing failing to signal it. This section names the route that is actually live, and links to the classic page when that route is the classic one.

Turning connections on is not reversible from the admin interface. The setting is stored as "already on or newly on", so an attempt to switch back is refused rather than silently discarded. The switch also carries the classic endpoint over as the first connection, so the change does not begin with an empty model list. Treat it as a migration.

#### Default model

The default model is the one chat uses when nothing else has chosen — a conversation started before the user has picked anything, or work that begins outside the chat window. It is stored as a reference to a connection and one of that connection's models, not as a copy of the model, so it outlives what it names: deleting a connection, disabling one, or switching off a single model all leave it pointing at nothing.

Rather than let that reference decay into a silent fallback to some other model, SimpleChat clears it whenever the thing it names stops being available, and says so. Only models that are enabled on an enabled connection can be chosen, for the same reason — anything else would be cleared again on the next save.

The default applies to connections only. With chat on the classic single endpoint there is nothing for it to select from, and a choice made in that state is refused rather than stored.

#### Settings

The classic single endpoint is configured on the server-rendered admin page. Its values are listed here because they are what chat uses while **Use connections for chat** is off, and because API Management applies to GPT requests that use the classic endpoint whichever mode chat is in.

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

Image generation gives chat a tool that produces pictures from a prompt. It is off by default and configured entirely separately from chat and embeddings, because image models are deployed on their own and are frequently in a different region from the chat deployment.

With **Enable Image Generation** off, nothing else in this section is consulted, and the rest of it stays out of the way rather than inviting configuration that would have no effect.

#### Direct or through API Management

As with embeddings, the direct and gateway routes are alternatives and only the selected one is used. The gateway has its own address, version, deployment name and subscription key.

#### Which API produces the image

Azure OpenAI produces images two different ways, and which one applies is decided by the model behind the deployment you select rather than by a setting.

A `gpt-image-*` or DALL-E deployment serves the images endpoint and is asked for a picture directly. That is the route SimpleChat has always used, and it remains the route for every deployment that can take it.

A chat deployment — `gpt-5.6-*`, `gpt-4o` and their relations — serves no image endpoint at all. It can still produce an image, through the Responses API's hosted `image_generation` tool, and SimpleChat sends it that way instead. This matters where an image model is not available to a subscription or region: a chat deployment is then the difference between image generation working and not being offered. It is not the better route where both exist, because it cannot change part of an existing image and puts the orchestrating model in front of every picture.

Two things follow from selecting a chat deployment:

- The image editor offers whole-image regeneration only. Changing part of an image needs `/images/edits`, which the Responses tool has no equivalent for, and the editor says so before you paint a region rather than after.
- **Azure OpenAI Image Gen API Version** does not apply to it. That setting governs the image endpoints, and its default predates the Responses API entirely, so this route uses a version new enough for it regardless of what is set. A value newer than that is honoured.

A deployment reached through API Management always uses the images endpoint. The gateway records a deployment name and no model name, so there is nothing to decide from, and the operation the gateway publishes determines the shape of the call in any case.

A deployment saved before SimpleChat began recording model names also stays on the images endpoint, because an unknown model is not the same as a chat model. Re-running **Fetch deployments** and re-selecting it records the name and lets it be classified.

#### Authentication and deployment discovery

Managed identity stores no credential and is what allows SimpleChat to list the resource's deployments, using the subscription id and resource group. A key authenticates to inference only.

**Fetch deployments** reads the saved endpoint, subscription id and resource group, so save changes to those first. It lists both the image models and the chat models the resource exposes, since either can produce an image, and excludes embedding deployments, which can produce neither. A deployment the resource no longer reports is dropped from the selection rather than left to fail on the next request.

The stored key is never shown, and leaving its field empty keeps what is stored. **Remove stored value** clears it.

#### Changing the image model

Image deployments differ in the sizes, quality settings and response formats they accept, so a change here can alter what the image tool is able to produce, not only how the results look. Moving between an image model and a chat model changes the API the request takes as well, and with it whether the editor can change part of an image. Generate one test image after changing it.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Image Generation | Offers image generation in chat. With it off, nothing else here is consulted. | Off | `enable_image_generation`; capability toggle |
| Use APIM instead of direct to Azure OpenAI endpoint | Sends image requests through API Management rather than straight to the Azure OpenAI resource. Only the selected route is used. | Off | `enable_image_gen_apim`; capability toggle |
| Azure OpenAI Image Generation Endpoint | The resource holding the image deployment. Rarely the same as the chat endpoint. | Empty | `azure_openai_image_gen_endpoint` |
| Authentication Type | Managed identity stores no credential and enables deployment discovery; a key authenticates to inference only. | key | `azure_openai_image_gen_authentication_type` |
| Subscription ID | Addresses the resource when listing its deployments. Inference does not need it. | Empty | `azure_openai_image_gen_subscription_id` |
| Resource Group | The other half of the address the deployment list is fetched from. | Empty | `azure_openai_image_gen_resource_group` |
| Azure OpenAI Image Generation Key | Used only with key authentication. Leaving it blank keeps the stored key. | Empty | `azure_openai_image_gen_key` |
| Image model | The single deployment every generated image comes from. An image model is asked through the images endpoint; a chat model through the Responses image tool. | None selected | `image_gen_model`; written through its own API |
| Azure OpenAI Image Gen API Version | Image generation moves on its own API schedule, which is why this defaults later than the chat and embedding versions. Governs the image endpoints only. | 2024-12-01-preview | `azure_openai_image_gen_api_version` |
| Azure APIM Endpoint | The API Management address that fronts the image deployment. | Empty | `azure_apim_image_gen_endpoint` |
| Azure APIM API Version | Whatever version the API Management operation publishes; there is no default, because a gateway can publish any. | Empty | `azure_apim_image_gen_api_version` |
| Azure APIM Deployment | The deployment name to send image requests to. Discovery does not reach through a gateway, so this is typed. | Empty | `azure_apim_image_gen_deployment` |
| Azure APIM Subscription Key | Leaving it blank keeps the stored key. | Empty | `azure_apim_image_gen_subscription_key` |


## Common tasks

1. **Publish models from a new resource.** Add a connection, choose its provider and authentication, run **Test connection**, then **Discover models** and turn on the ones people may use. Save the connection. Outcome to verify: the enabled models appear in the chat model picker.
2. **Rotate a stored key.** Edit the connection, type the new key over the empty field, and save. Outcome to verify: **Test connection** succeeds with the replacement.
3. **Choose the model chat starts from.** With connections in force, pick a default under Chat. Outcome to verify: a new conversation opens on that model without anyone selecting it.
4. **Retire a connection.** Disable it first and confirm chat still works, then delete it. Outcome to verify: its models stop being offered, and a default model that named it is cleared.
5. **Configure embeddings.** Set the endpoint, authentication and — with managed identity — the subscription id and resource group, then save. Fetch the deployments, choose one, and index a small document. Outcome to verify: indexing completes and the document's citations are found by a question that does not repeat its wording.
6. **Enable image generation.** Turn the capability on, set the endpoint and authentication, save, fetch the deployments and choose one. Outcome to verify: the image tool returns a picture from the deployment you chose.
7. **Rotate an embedding or image key.** Type the new key over the empty field and save. Outcome to verify: **Test connection** on the classic admin page succeeds, and indexing or generation still works.
8. **Move a route behind API Management.** Turn on **Use APIM**, then fill in the gateway address, version, deployment name and subscription key. Outcome to verify: requests appear in the gateway's logs, and the direct settings are left untouched in case you switch back.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A connection's models never appear in chat | **Use connections for chat** is off, so chat is running on the classic single endpoint. | Turn it on, or configure the classic endpoint instead. Chat says which route is live. |
| **Use connections for chat** will not turn off | Enabling connections is one-way, because chats, agents and workflows may already reference a model published from one. | Disable the individual connections instead, or point chat at the model you want by making it the default. |
| **Discover models** is unavailable | The connection authenticates with an API key, which reaches inference but not Azure Resource Manager. | Switch to managed identity or a service principal, or add the deployment names by hand. |
| Discovery returns nothing for an Azure OpenAI connection | The subscription id or resource group does not match the resource. | Correct them, then run **Test connection** before discovering again. |
| Models are listed but nobody can choose them | Discovered models arrive switched off. | Turn on each model that should be available, then save the connection. |
| The default model reverted to none | The connection or model it named was deleted or disabled, so the reference no longer resolved. | Choose a default that points at an enabled model on an enabled connection. |
| The default model list is empty | Either chat is on the classic single endpoint, or no connection currently has an enabled model on an enabled connection. | Turn on **Use connections for chat**, then enable at least one model. |
| A default model choice is refused | Chat is on the classic single endpoint, so the choice would be cleared on the next save rather than taking effect. | Turn on **Use connections for chat** first. |
| Embeddings fail during indexing | Endpoint, deployment, API version, or authentication does not match the Azure resource. | Validate the embedding route with a small document before bulk indexing. |
| **Fetch deployments** returns nothing | Either the endpoint, subscription id and resource group do not name the resource the deployment lives in, or those changes have not been saved yet — fetching reads the saved values. | Save the connection details first, then fetch again. |
| **Fetch deployments** is refused | The route authenticates with a key, which reaches inference but not Azure Resource Manager. | Switch to managed identity, and grant it read access to the resource. |
| An embedding or image deployment disappeared from the list | The deployment was removed or renamed in Azure, so discovery no longer reports it. The selection is cleared rather than kept, because a request naming it would fail. | Choose a replacement from the refreshed list. |
| Search quality dropped after changing the embedding model | Embeddings are only comparable with others from the same model, and existing chunks were not rewritten. | Re-index the affected workspaces so every chunk comes from one model. |
| A key was cleared without anyone changing it | Nothing in the V2 admin surface clears a secret by saving an empty field, so check the classic admin page, where a blank key field does store a blank. | Re-enter the key. Use the V2 surface's **Remove stored value** when removal is what you want. |
| Image generation is configured but never offered | **Enable Image Generation** is off, so the rest of the section is not consulted. | Turn it on, then confirm a deployment is selected. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Agents & Actions settings]({{ '/admin/agents-actions/' | relative_url }})
- [Chat settings]({{ '/admin/chat/' | relative_url }})
