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

Connections are consulted only when **Use connections for chat** is on. With it off, chat runs on the single classic endpoint configured under Chat Model instead, and anything listed here is ignored.

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

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Use connections for chat | Routes chat through the connections listed here instead of the single classic endpoint. | Off | `enable_multi_model_endpoints`; capability toggle |
| Connections | The list of model connections, each saved on its own. | Empty | `model_endpoints`; edited through its own API |
| Send an identity header with model requests | Adds a header identifying the signed-in user to every model request. | Off | `model_endpoint_identity_header_enabled` |
| Header name | Rejected if it collides with a header the model call already sets, such as `authorization`. | x-simplechat-identity-key | `model_endpoint_identity_header_name` |
| Identity sent in the header | Object id is stable across a rename; UPN is readable in gateway logs. Tenant variants qualify the value for a multi-tenant gateway. | Object id and tenant id | `model_endpoint_identity_header_value_type` |
| Default model for fallbacks | The model used when no other choice applies. Cleared automatically if the connection or model it names is deleted or disabled. | Not specified in defaults | `default_model_selection` |

### Chat {#gpt-config}

The classic single-endpoint chat configuration. It is what chat uses when **Use connections for chat** is off, and it remains available as a fallback route.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Use APIM instead of direct to Azure OpenAI endpoint | Sends chat requests through API Management rather than straight to the Azure OpenAI resource. | Off | `enable_gpt_apim`; capability toggle |
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

The Embeddings section belongs to the Embeddings tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Use APIM instead of direct to Azure OpenAI endpoint | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_embedding_apim`; capability toggle |
| Azure OpenAI Embedding Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Empty | `azure_openai_embedding_endpoint` |
| Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `azure_openai_embedding_authentication_type` |
| Subscription ID | Defines behavior for the related admin workflow; verify the affected feature after saving. | Empty | `azure_openai_embedding_subscription_id` |
| Resource Group | Defines behavior for the related admin workflow; verify the affected feature after saving. | Empty | `azure_openai_embedding_resource_group` |
| Azure OpenAI Embedding Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_openai_embedding_key` |
| Azure OpenAI Embedding API Version | Pins the service API version SimpleChat sends with requests for this feature. | 2024-05-01-preview | `azure_openai_embedding_api_version` |
| Azure APIM Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Empty | `azure_apim_embedding_endpoint` |
| Azure APIM API Version | Pins the service API version SimpleChat sends with requests for this feature. | Empty | `azure_apim_embedding_api_version` |
| Azure APIM Deployment | Selects the deployment SimpleChat sends requests to for this capability. | Empty | `azure_apim_embedding_deployment` |
| Azure APIM Subscription Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_apim_embedding_subscription_key` |

## Image Generation {#image-generation}

### Image Generation {#image-config}

The Image Generation section belongs to the Image Generation tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Image Generation | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_image_generation`; capability toggle |
| Use APIM instead of direct to Azure OpenAI endpoint. | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_image_gen_apim`; capability toggle |
| Azure OpenAI Image Generation Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Empty | `azure_openai_image_gen_endpoint` |
| Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `azure_openai_image_gen_authentication_type` |
| Subscription ID | Defines behavior for the related admin workflow; verify the affected feature after saving. | Empty | `azure_openai_image_gen_subscription_id` |
| Resource Group | Defines behavior for the related admin workflow; verify the affected feature after saving. | Empty | `azure_openai_image_gen_resource_group` |
| Azure OpenAI Image Generation Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_openai_image_gen_key` |
| Azure OpenAI Image Gen API Version | Pins the service API version SimpleChat sends with requests for this feature. | 2024-12-01-preview | `azure_openai_image_gen_api_version` |
| Azure APIM Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Empty | `azure_apim_image_gen_endpoint` |
| Azure APIM API Version | Pins the service API version SimpleChat sends with requests for this feature. | Empty | `azure_apim_image_gen_api_version` |
| Azure APIM Deployment | Selects the deployment SimpleChat sends requests to for this capability. | Empty | `azure_apim_image_gen_deployment` |
| Azure APIM Subscription Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_apim_image_gen_subscription_key` |

## Common tasks

1. **Publish models from a new resource.** Add a connection, choose its provider and authentication, run **Test connection**, then **Discover models** and turn on the ones people may use. Save the connection. Outcome to verify: the enabled models appear in the chat model picker.
2. **Rotate a stored key.** Edit the connection, type the new key over the empty field, and save. Outcome to verify: **Test connection** succeeds with the replacement.
3. **Retire a connection.** Disable it first and confirm chat still works, then delete it. Outcome to verify: its models stop being offered, and a default model that named it is cleared.
4. **Configure embeddings.** Set endpoint, authentication, API version, and deployment, then index a small document. Outcome to verify: Indexing succeeds with the configured embedding route.
5. **Enable image generation.** Enable the capability, set endpoint values, and generate a low-risk test image. Outcome to verify: The image tool returns output from the configured deployment.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A connection's models never appear in chat | **Use connections for chat** is off, so chat is running on the classic single endpoint. | Turn it on, or configure the classic endpoint under Chat instead. |
| **Discover models** is unavailable | The connection authenticates with an API key, which reaches inference but not Azure Resource Manager. | Switch to managed identity or a service principal, or add the deployment names by hand. |
| Discovery returns nothing for an Azure OpenAI connection | The subscription id or resource group does not match the resource. | Correct them, then run **Test connection** before discovering again. |
| Models are listed but nobody can choose them | Discovered models arrive switched off. | Turn on each model that should be available, then save the connection. |
| The default model reverted to none | The connection or model it named was deleted or disabled, so the reference no longer resolved. | Choose a default that points at an enabled model on an enabled connection. |
| Embeddings fail during indexing | Endpoint, deployment, API version, or authentication does not match the Azure resource. | Validate the embedding route with a small document before bulk indexing. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Agents & Actions settings]({{ '/admin/agents-actions/' | relative_url }})
- [Chat settings]({{ '/admin/chat/' | relative_url }})
