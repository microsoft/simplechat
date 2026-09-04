# Azure OpenAI Identity Setup Guide

Implemented in version: **0.250.001**

## Overview

The Azure OpenAI identity setup guide helps admins configure GPT, embeddings, and image generation by explaining which identity is used for model discovery and which identity or secret is used for runtime generation.

Dependencies:

- Azure OpenAI resource
- SimpleChat app registration/service principal
- App Service managed identity when using managed identity runtime calls
- Azure RBAC assignment permission on the Azure OpenAI resource

## Technical Specifications

Architecture overview:

- Legacy GPT, embedding, and image generation `Fetch Models` buttons call SimpleChat backend routes that list Azure OpenAI deployments through Azure Resource Manager.
- Runtime GPT, embedding, file-upload embedding, and image generation calls use the Azure OpenAI data plane.
- The setup guide is rendered in Admin Settings near embeddings and image generation and also aligns with the global model endpoint setup guidance.

API endpoints:

- `GET /api/models/gpt`
- `GET /api/models/embedding`
- `GET /api/models/image`
- `POST /api/admin/settings/test_connection`

Configuration options:

- Azure OpenAI endpoint
- Subscription ID and resource group for model discovery
- Key or managed identity authentication for runtime data-plane use
- APIM endpoint, deployment, API version, and subscription key when APIM is enabled

File structure:

- `application/single_app/templates/admin_settings.html`
- `application/single_app/route_backend_models.py`
- `functional_tests/test_azure_openai_identity_split.py`

## Usage Instructions

Admins should assign roles on the Azure OpenAI resource before fetching or testing models:

1. Assign the SimpleChat app registration/service principal `Cognitive Services User` for `Fetch Models` deployment discovery.
2. Assign the App Service managed identity `Cognitive Services OpenAI User` when runtime generation uses managed identity.
3. Copy the Azure OpenAI endpoint, subscription ID, and resource group from the Azure portal.
4. Copy an Azure OpenAI key from `Keys and Endpoint` only when runtime generation uses key authentication.
5. Use `Fetch Models` to discover deployments, then use the relevant test connection button to validate data-plane generation.

## Testing and Validation

Test coverage:

- `functional_tests/test_azure_openai_identity_split.py`
- `functional_tests/test_azure_openai_deployer_role_split.py`

Performance considerations:

- Model discovery is an admin operation and only lists deployment metadata.
- Runtime embedding and image calls are unchanged by the setup guide.

Known limitations:

- API keys do not authorize management-plane model discovery.
- Foundry provider role setup is handled separately by the global model endpoint setup guide.

Config version updated in `application/single_app/config.py` to **0.250.001**.