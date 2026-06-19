# Azure OpenAI Model Discovery Identity Fix

Fixed in version: **0.250.001**

## Issue Description

Legacy Azure OpenAI model discovery for GPT, embeddings, and image generation could be confusing because `Fetch Models` uses Azure Resource Manager deployment listing while runtime generation uses the Azure OpenAI data plane. Admins could successfully test embedding generation or process uploaded files with managed identity, yet still see model fetch failures when the management-plane identity did not have the correct Azure OpenAI role.

## Root Cause

The fetch and use paths require different authorization surfaces:

- `Fetch Models` is a management-plane operation that lists Azure OpenAI deployments.
- Embedding generation, file-upload embeddings, GPT inference, and image generation are data-plane operations.
- API keys can authorize data-plane inference but cannot authorize management-plane deployment listing.

For legacy GPT, embeddings, and image generation settings, SimpleChat uses the configured app registration/service principal for management-plane fetch and the selected runtime authentication method for data-plane use.

## Technical Details

Files modified:

- `application/single_app/route_backend_models.py`
- `application/single_app/templates/admin_settings.html`
- `deployers/bicep/modules/setPermissions.bicep`
- `deployers/bicep/modules/setPermissions-openAIExternal.bicep`
- `deployers/bicep/main.json`
- `deployers/azurecli/deploy-simplechat.ps1`
- `deployers/terraform/main.tf`
- `deployers/version.txt`
- `functional_tests/test_azure_openai_identity_split.py`
- `functional_tests/test_azure_openai_deployer_role_split.py`

Code changes summary:

- Centralized legacy Azure OpenAI account-name normalization for GPT, embedding, and image fetch routes.
- Routed legacy Azure OpenAI deployment discovery through the configured service principal management-plane credential.
- Added an Admin Settings setup guide explaining the management-plane fetch versus data-plane use split.
- Added deployer role assignments so the app registration/service principal receives `Cognitive Services User` on the Azure OpenAI resource for model discovery.
- Preserved the App Service managed identity `Cognitive Services OpenAI User` role for data-plane generation.

## Role Mapping

| Purpose | Entra object | Azure role | Scope |
| --- | --- | --- | --- |
| Fetch model deployments | SimpleChat app registration/service principal, such as `simplechat-*-ar` | `Cognitive Services User` | Azure OpenAI resource |
| Generate embeddings or images with managed identity | App Service managed identity, such as `simplechat-*-app` | `Cognitive Services OpenAI User` | Azure OpenAI resource |
| Generate embeddings or images with key authentication | Saved Azure OpenAI key | Resource key from Keys and Endpoint | Azure OpenAI data plane |

## Validation

Validation approach:

- Functional tests verify the backend fetch/use identity split.
- Functional tests verify Bicep, ARM JSON, Azure CLI, and Terraform deployer role coverage.
- Python compile checks validate edited backend and test files.

Before this fix, an admin could see a successful embedding connection test but fail to fetch embedding deployments if the management-plane principal lacked deployment discovery access. After this fix, deployers grant the explicit management-plane role and the admin guide names which identity and role apply to fetch versus use.

Config version updated in `application/single_app/config.py` to **0.250.001**.