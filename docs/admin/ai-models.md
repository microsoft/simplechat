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

## Model Endpoints {#model-endpoints}

### Model Endpoints {#multi-endpoint-configuration}

The Model Endpoints section belongs to the Model Endpoints tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Chat Model {#gpt-config}

The Chat Model section belongs to the Model Endpoints tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable multi-endpoint model management | Provides the endpoint or route SimpleChat uses for this service. | Off | `enable_multi_model_endpoints`; capability toggle |
| Search Agents | Defines behavior for the related admin workflow; verify the affected feature after saving. | N/A (runtime control) | Runtime UI control |
| Filter | Defines behavior for the related admin workflow; verify the affected feature after saving. | N/A (runtime control) | Runtime UI control |
| Enable header | Provides the endpoint or route SimpleChat uses for this service. | Off | `model_endpoint_identity_header_enabled` |
| Header Name | Provides the endpoint or route SimpleChat uses for this service. | Not specified in defaults | `model_endpoint_identity_header_name` |
| Identity Value | The selected identity is HMAC-hashed before leaving SimpleChat. Missing identity values omit the header. | Not specified in defaults | `model_endpoint_identity_header_value_type` |
| Default model for fallbacks | Used for tasks such as conversation summarization, fallback, and other operations when an agent is selected. | Not specified in defaults | Runtime UI control |
| Use APIM instead of direct to Azure OpenAI endpoint | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_gpt_apim`; capability toggle |
| Azure OpenAI Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Empty | `azure_openai_gpt_endpoint` |
| Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `azure_openai_gpt_authentication_type` |
| Subscription ID | Defines behavior for the related admin workflow; verify the affected feature after saving. | Empty | `azure_openai_gpt_subscription_id` |
| Resource Group | Defines behavior for the related admin workflow; verify the affected feature after saving. | Empty | `azure_openai_gpt_resource_group` |
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

1. **Route chat through approved endpoints.** Enable multi-endpoint management when needed and run a chat through the intended deployment. Outcome to verify: Requests reach the approved route.
2. **Configure embeddings.** Set endpoint, authentication, API version, and deployment, then index a small document. Outcome to verify: Indexing succeeds with the configured embedding route.
3. **Enable image generation.** Enable the capability, set endpoint values, and generate a low-risk test image. Outcome to verify: The image tool returns output from the configured deployment.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Embeddings fail during indexing | Endpoint, deployment, API version, or authentication does not match the Azure resource. | Validate the embedding route with a small document before bulk indexing. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Agents & Actions settings]({{ '/admin/agents-actions/' | relative_url }})
- [Chat settings]({{ '/admin/chat/' | relative_url }})
