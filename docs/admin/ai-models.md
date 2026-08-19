---
layout: page
title: "AI Models Settings"
description: "Controls chat, embedding, image generation, and multi-endpoint model routing for the application."
section: "Administration"
audience: admin
admin_tab: ai-models
---

## What this tab controls

Controls chat, embedding, image generation, and multi-endpoint model routing for the application.

## Why it matters

These settings decide which model endpoints receive prompts, embeddings, and image-generation requests. If GPT settings are wrong, chat and agents fail. If embeddings are wrong, workspace retrieval and document search fail. Multi-endpoint routing and user-selectable models are powerful, but they also widen the cost, quota, and governance surface because different deployments may have different capabilities and data-handling expectations.

{% include media.html src="admin-settings/ai-models.png" alt="Screenshot of the AI Models settings tab showing chat, embedding, image generation, and model routing controls available to administrators." title="AI Models settings tab" %}

{% include media.html type="video" title="AI Models settings walkthrough" poster="video-posters/admin-ai-models.png" capture="Recording planned. Walk through every setting on the AI Models tab and explain when to change each one." %}

## Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable multi-endpoint model management | Points SimpleChat to the enable multi-endpoint model management used by this feature. | Off | `enable_multi_model_endpoints`; capability toggle |
| Search Agents | Controls how SimpleChat uses search agents on this tab. | N/A (runtime control) | Runtime UI control |
| Filter | Controls how SimpleChat uses filter on this tab. | N/A (runtime control) | Runtime UI control |
| Enable header | Points SimpleChat to the enable header used by this feature. | Off | `model_endpoint_identity_header_enabled` |
| Header Name | Points SimpleChat to the header name used by this feature. | Not specified in defaults | `model_endpoint_identity_header_name` |
| Identity Value | The selected identity is HMAC-hashed before leaving SimpleChat. Missing identity values omit the header. | Not specified in defaults | `model_endpoint_identity_header_value_type` |
| Default model for fallbacks | Used for tasks such as conversation summarization, fallback, and other operations when an agent is selected. | Not specified in defaults | Runtime UI control |
| Enable Processing Thoughts | Makes processing thoughts available in the product when its required service and access policy are configured. | On | `enable_thoughts`; capability toggle |
| Use APIM instead of direct to Azure OpenAI endpoint | Makes use apim instead of direct to azure openai endpoint available in the product when its required service and access policy are configured. | Off | `enable_embedding_apim`; capability toggle |
| Azure OpenAI Embedding Endpoint | Points SimpleChat to the azure openai embedding endpoint used by this feature. | Empty | `azure_openai_embedding_endpoint` |
| Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `azure_openai_embedding_authentication_type` |
| Subscription ID | Controls how SimpleChat uses subscription id on this tab. | Empty | `azure_openai_embedding_subscription_id` |
| Resource Group | Controls how SimpleChat uses resource group on this tab. | Empty | `azure_openai_embedding_resource_group` |
| Azure OpenAI Embedding Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_openai_embedding_key` |
| Azure OpenAI Embedding API Version | Pins the service API version SimpleChat sends with requests for this feature. | 2024-05-01-preview | `azure_openai_embedding_api_version` |
| Azure APIM Endpoint | Points SimpleChat to the azure apim endpoint used by this feature. | Empty | `azure_apim_embedding_endpoint` |
| Azure APIM API Version | Pins the service API version SimpleChat sends with requests for this feature. | Empty | `azure_apim_embedding_api_version` |
| Azure APIM Deployment | Chooses the model or deployment SimpleChat uses for azure apim deployment. | Empty | `azure_apim_embedding_deployment` |
| Azure APIM Subscription Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_apim_embedding_subscription_key` |
| Enable Image Generation | Makes image generation available in the product when its required service and access policy are configured. | Off | `enable_image_generation`; capability toggle |
| Use APIM instead of direct to Azure OpenAI endpoint. | Makes use apim instead of direct to azure openai endpoint available in the product when its required service and access policy are configured. | Off | `enable_image_gen_apim`; capability toggle |
| Azure OpenAI Image Generation Endpoint | Points SimpleChat to the azure openai image generation endpoint used by this feature. | Empty | `azure_openai_image_gen_endpoint` |
| Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `azure_openai_image_gen_authentication_type` |
| Subscription ID | Controls how SimpleChat uses subscription id on this tab. | Empty | `azure_openai_image_gen_subscription_id` |
| Resource Group | Controls how SimpleChat uses resource group on this tab. | Empty | `azure_openai_image_gen_resource_group` |
| Azure OpenAI Image Generation Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_openai_image_gen_key` |
| Azure OpenAI Image Gen API Version | Pins the service API version SimpleChat sends with requests for this feature. | 2024-12-01-preview | `azure_openai_image_gen_api_version` |
| Azure APIM Endpoint | Points SimpleChat to the azure apim endpoint used by this feature. | Empty | `azure_apim_image_gen_endpoint` |
| Azure APIM API Version | Pins the service API version SimpleChat sends with requests for this feature. | Empty | `azure_apim_image_gen_api_version` |
| Azure APIM Deployment | Chooses the model or deployment SimpleChat uses for azure apim deployment. | Empty | `azure_apim_image_gen_deployment` |
| Azure APIM Subscription Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_apim_image_gen_subscription_key` |
| Use APIM instead of direct to Azure OpenAI endpoint | Makes use apim instead of direct to azure openai endpoint available in the product when its required service and access policy are configured. | Off | `enable_gpt_apim`; capability toggle |
| Azure OpenAI Endpoint | Points SimpleChat to the azure openai endpoint used by this feature. | Empty | `azure_openai_gpt_endpoint` |
| Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `azure_openai_gpt_authentication_type` |
| Subscription ID | Controls how SimpleChat uses subscription id on this tab. | Empty | `azure_openai_gpt_subscription_id` |
| Resource Group | Controls how SimpleChat uses resource group on this tab. | Empty | `azure_openai_gpt_resource_group` |
| Azure OpenAI GPT Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_openai_gpt_key` |
| Azure OpenAI API Version | Pins the service API version SimpleChat sends with requests for this feature. | 2024-05-01-preview | `azure_openai_gpt_api_version` |
| Azure APIM Endpoint | Points SimpleChat to the azure apim endpoint used by this feature. | Empty | `azure_apim_gpt_endpoint` |
| Azure APIM API Version | Pins the service API version SimpleChat sends with requests for this feature. | Empty | `azure_apim_gpt_api_version` |
| Azure APIM Deployment | Each model defined here will be available in the Chat UI as an option for the User. You can include multiple models seperated by a comma (example: gpt-4o, o-1, o-3). | Empty | `azure_apim_gpt_deployment` |
| Azure APIM Subscription Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_apim_gpt_subscription_key` |

### Multi-endpoint model management

Enable multi-endpoint mode when different deployments, providers, or model families should be managed together. After enabling it, choose a fallback model so background tasks and agents that do not specify a model still have a safe default.

### Embeddings configuration

Embeddings are required for document retrieval and workspace search. Configure and test embeddings before telling users to upload searchable documents; otherwise files may upload but retrieval-backed answers will not work correctly.

### Image generation

Image generation sends user prompts to the configured image model deployment. Keep it off unless the deployment has quota, content policy approval, and a model selected for image generation.

## Before you change anything

- Create the Azure OpenAI, Foundry, or APIM endpoints and know each deployment name before adding it.
- For managed identity authentication, grant the app identity access to the OpenAI or Foundry resource before saving.
- Configure embeddings before enabling document retrieval experiences that depend on vector search.
- For multi-endpoint mode, decide which model is the default fallback before users start creating agents.

## Common tasks

1. **Add or review chat model routing.**
    1. Enable **Enable multi-endpoint model management** if using the endpoint manager.
    2. Add or verify chat endpoints and deployments in **Model Endpoints** or legacy **Chat Model** fields.
    3. Choose **Default model for fallbacks**.
    4. Save and open Chat to verify the model selector.
    Outcome to verify: Users can select the intended chat deployments.

{% include media.html src="admin/ai-models-add-or-review-chat-model-routing.png" alt="Screenshot of the AI Models settings tab showing add or review chat model routing." title="AI Models: Add or review chat model routing" capture="Capture the AI Models tab while performing Add or review chat model routing. Show the relevant controls and redact secrets." %}

2. **Configure embeddings for workspaces.**
    1. Set **Use APIM instead of direct to Azure OpenAI endpoint** if embeddings route through APIM.
    2. Enter the embedding endpoint, authentication type, API version, and deployment details.
    3. Provide key or managed identity subscription/resource group values as required.
    4. Save and run the connection test.
    Outcome to verify: Workspace search has a working embedding deployment.

{% include media.html src="admin/ai-models-configure-embeddings-for-workspaces.png" alt="Screenshot of the AI Models settings tab showing configure embeddings for workspaces." title="AI Models: Configure embeddings for workspaces" capture="Capture the AI Models tab while performing Configure embeddings for workspaces. Show the relevant controls and redact secrets." %}

3. **Enable image generation.**
    1. Enable **Enable Image Generation**.
    2. Configure direct Azure OpenAI or APIM image-generation endpoint fields.
    3. Select authentication type and provide the key or managed identity details.
    4. Save and verify the image generation control appears only for intended users.
    Outcome to verify: Image prompts route to the configured image model.

{% include media.html src="admin/ai-models-enable-image-generation.png" alt="Screenshot of the AI Models settings tab showing enable image generation." title="AI Models: Enable image generation" capture="Capture the AI Models tab while performing Enable image generation. Show the relevant controls and redact secrets." %}

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Users do not see models in chat | No active GPT deployment or endpoint is configured. | Configure a chat endpoint and deployment, then save settings and refresh chat. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Agents]({{ '/admin/agents/' | relative_url }})
- [Workspaces]({{ '/admin/workspaces/' | relative_url }})
