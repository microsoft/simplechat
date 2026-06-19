---
layout: showcase-page
title: "Configure Model Endpoint Identity"
permalink: /how-to/model_endpoint_identity_setup/
menubar: docs_menu
accent: teal
eyebrow: "Admin How-To"
description: "Assign managed identity or service principal access for Azure OpenAI, Foundry (classic), and New Foundry model endpoints in the multi-endpoint modal."
version: "0.250.006"
keywords:
  - model endpoints
  - multi endpoint
  - Azure OpenAI
  - Foundry classic
  - New Foundry
  - managed identity
  - service principal
  - RBAC
hero_icons:
  - bi-diagram-3
  - bi-person-badge
  - bi-shield-check
hero_pills:
  - Azure OpenAI and Foundry providers
  - Managed identity or service principal
  - Correct RBAC scope before testing
hero_links:
  - label: "Admin configuration overview"
    url: /admin_configuration/
    style: primary
  - label: "Managed identity guide"
    url: /how-to/use_managed_identity/
    style: secondary
---

Use this guide when admins need to configure the shared **Model Endpoint** modal for Azure OpenAI, Foundry (classic), or New Foundry without depending on legacy single-endpoint settings.

Documented for version **0.250.006**.

The multi-endpoint UI also includes a **Setup Guide** button beside endpoint actions and inside the Model Endpoint modal. Use that in-product guidance for quick RBAC reminders, and use this page when you need the full setup sequence.

<section class="latest-release-card-grid">
    <article class="latest-release-card latest-release-accent--blue">
        <div class="latest-release-card-shell">
            <div class="latest-release-card-top">
                <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-diagram-3"></i></span>
                <span class="latest-release-card-badge">Provider</span>
            </div>
            <h2>Pick the endpoint family</h2>
            <p class="latest-release-card-summary">Choose Azure OpenAI for resource endpoints, Foundry (classic) for classic project agents, or New Foundry for the application-based runtime.</p>
        </div>
    </article>
    <article class="latest-release-card latest-release-accent--emerald">
        <div class="latest-release-card-shell">
            <div class="latest-release-card-top">
                <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-person-badge"></i></span>
                <span class="latest-release-card-badge">Identity</span>
            </div>
            <h2>Assign the right principal</h2>
            <p class="latest-release-card-summary">Grant roles to the App Service managed identity, a user-assigned managed identity, or the enterprise application behind a service principal.</p>
        </div>
    </article>
    <article class="latest-release-card latest-release-accent--orange">
        <div class="latest-release-card-shell">
            <div class="latest-release-card-top">
                <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-shield-check"></i></span>
                <span class="latest-release-card-badge">RBAC</span>
            </div>
            <h2>Target the correct resource</h2>
            <p class="latest-release-card-summary">Azure OpenAI discovery needs ARM read access on the OpenAI resource, while Foundry discovery and agent invocation need Foundry project access.</p>
        </div>
    </article>
</section>

## Before You Start

- Sign in to Simple Chat as an admin when creating global model endpoints.
- Make sure you can assign Azure roles on the target Azure OpenAI resource, Foundry project, or backing Foundry resource.
- Decide whether the endpoint is global, personal, or group scoped. The identity and RBAC requirements are the same, but the endpoint is saved in a different scope.
- If you use a service principal, create the Entra app registration first and keep the tenant ID, client ID, and client secret ready.
- If you use a user-assigned managed identity, attach it to the App Service and copy the managed identity **Client ID** for the modal.
- Plan separate model endpoints when provider families need different project settings, authentication, or manual deployment rows. For Foundry project model inference, Simple Chat normalizes calls to `/openai/v1`, so keep **OpenAI API Version** at endpoint default `v1`.

## Choose The Provider

The modal provider decides which discovery API and token scope Simple Chat uses.

| Provider in the modal | Use it for | Endpoint value | RBAC target |
|-----------------------|------------|----------------|-------------|
| `Azure OpenAI` | Direct Azure OpenAI resource endpoints and Azure OpenAI-compatible APIM paths | `https://<openai-resource>.openai.azure.com/` for direct Azure OpenAI | The Azure OpenAI resource, or a parent resource group/subscription when your access model requires it |
| `Foundry (classic)` | Existing classic Foundry project agents and model deployments | `https://<foundry-resource>.services.ai.azure.com/api/projects/<project>` or the project base endpoint plus **Foundry Project Name** | The Foundry project when the portal exposes project-scoped access, otherwise the backing Foundry resource/account |
| `New Foundry` | Application-based Foundry runtime, New Foundry agents, and OpenAI-compatible project model deployments | The same Foundry project endpoint shape used by the New Foundry project | The Foundry project when the portal exposes project-scoped access, otherwise the backing Foundry resource/account |

For APIM, choose the provider that matches the backend service and select API key authentication when APIM expects a subscription key or other shared key. API key authentication can run inference, but it cannot use **Fetch Models** for Azure OpenAI ARM discovery or Foundry project discovery.

## Choose API Versions

The modal has two version fields, and they are intentionally separate.

| Field | What it controls | Recommended starting point |
|-------|------------------|----------------------------|
| **Project API Version** | Foundry project discovery calls such as deployment listing, agent listing, and workflow listing. | Keep `v1` unless your Foundry project documentation says otherwise. |
| **OpenAI API Version** | Inference calls for OpenAI-compatible Foundry project model deployments. Simple Chat normalizes Foundry project endpoints to `/openai/v1`. | Keep `Endpoint default (v1)` for New Foundry project model endpoints. The `/v1` path does not allow an `api-version` query, including dated preview values. |

If one deployed model family works and another fails with API-version or unsupported-operation errors, create a separate endpoint for the failing family so you can isolate its project endpoint, authentication, deployment rows, and test results. For the normalized `/openai/v1` inference path, keep **OpenAI API Version** at endpoint default `v1`.

Claude deployments are detected from the deployment name or Anthropic endpoint path and use the Anthropic messages protocol at runtime. The endpoint still stores an OpenAI API Version for the other model rows on that endpoint, so keep Claude with compatible rows or use a separate endpoint when the configuration becomes confusing.

Live validation against Foundry-hosted model families showed that basic chat-completions calls work for DeepSeek, Grok, and Llama, but reasoning-effort support and memory context tolerance are model-specific. Simple Chat only sends reasoning effort to known OpenAI reasoning families such as GPT-5 and o-series models. For Foundry-hosted non-OpenAI chat-completions models, Simple Chat folds saved memory values into the latest user message as plain background notes instead of injecting memory system messages. This preserves memory context while avoiding provider-side content-filter blocks observed with system-style memory prompts.

The same endpoint runtime helpers are used for chat streaming, workflow execution, metadata extraction, endpoint test calls, and Semantic Kernel-backed tabular or agent services. This keeps provider selection, authentication, OpenAI-compatible `/openai/v1` normalization, and Anthropic routing consistent across Simple Chat features.

## Understand Discovery Versus Inference

The modal has two separate behaviors that often require different permissions.

| Modal action | Azure OpenAI provider | Foundry providers |
|--------------|-----------------------|-------------------|
| **Fetch Models** | Uses Azure Resource Manager through the Cognitive Services management API to list deployments. It needs management-plane read access plus data-plane access for later inference. | Uses the Foundry project deployments API. It needs Entra ID access to the Foundry project. API keys are not supported for this discovery path. |
| **Test Model** | Calls the selected deployment for chat inference. Managed identity and service principal use Azure OpenAI Entra auth; API key uses the configured key. | Calls the selected project deployment. Managed identity and service principal use the Foundry token scope. API key is inference-only where the target endpoint accepts it. |
| Agent or workflow import | Not used for local Azure OpenAI models. | Classic Foundry, New Foundry, and Foundry Workflow discovery require Entra ID/RBAC. API keys are not used for chat-selectable Foundry agents or workflows. |

## Assign Roles

Grant roles to the exact principal that Simple Chat will use from the modal.

| Scenario | Principal to assign | Scope | Minimum roles |
|----------|---------------------|-------|---------------|
| Azure OpenAI with managed identity or service principal, including **Fetch Models** | App Service system-assigned identity, user-assigned identity, or service principal enterprise application | Azure OpenAI resource. Use resource group or subscription scope only when your organization manages access there. | `Reader` for deployment discovery, plus `Cognitive Services OpenAI User` for inference |
| Azure OpenAI inference with manually entered model rows | Same identity or service principal | Azure OpenAI resource | `Cognitive Services OpenAI User` |
| Foundry (classic) project model discovery or classic agent import | Same identity or service principal | Foundry project when available, otherwise the backing Foundry resource/account | `Foundry User` in commercial clouds, or `Azure AI User` where that older name is still shown |
| New Foundry project model discovery, application discovery, or Responses runtime | Same identity or service principal | Foundry project when available, otherwise the backing Foundry resource/account | `Foundry User` in commercial clouds, or `Azure AI User` where that older name is still shown |
| Foundry project administration outside Simple Chat, such as creating projects, apps, deployments, or assigning dependent roles | Admin operator or automation service principal | Foundry project, resource, account, or subscription according to your governance model | `Foundry Project Manager`, `Foundry Owner`, or `Foundry Account Owner` as appropriate. Azure Government and custom clouds may still show `Azure AI Project Manager`, `Azure AI Owner`, or `Azure AI Account Owner`. |

Keep runtime identities narrow. A managed identity or service principal used by Simple Chat usually needs user-level access to invoke and discover resources, not owner-level access to administer the Foundry account.

## Assign Access In Azure Portal

Use these steps for each target resource and role.

1. Open the target Azure OpenAI resource, Foundry project, or backing Foundry resource in Azure portal or Foundry portal.
2. Open **Access control (IAM)** for Azure resources, or the project access page for project-scoped Foundry roles.
3. Select **Add role assignment**.
4. Choose the required role from the table above.
5. For a system-assigned managed identity, choose **Managed identity**, select **App Service**, then select the Simple Chat App Service.
6. For a user-assigned managed identity, choose **Managed identity**, select **User-assigned managed identity**, then select the identity attached to the App Service.
7. For a service principal, choose **User, group, or service principal**, then search for the enterprise application by display name or client ID.
8. Review and assign. Repeat for every role and resource scope required by the provider.

## Assign Access With Azure CLI

Use the object ID of the managed identity or enterprise application when possible.

```bash
# Azure OpenAI direct resource: discovery plus inference
az role assignment create \
  --assignee-object-id <principal-object-id> \
  --assignee-principal-type ServicePrincipal \
  --role "Reader" \
  --scope <azure-openai-resource-id>

az role assignment create \
  --assignee-object-id <principal-object-id> \
  --assignee-principal-type ServicePrincipal \
  --role "Cognitive Services OpenAI User" \
  --scope <azure-openai-resource-id>

# Foundry project or backing Foundry resource: discovery and invocation
az role assignment create \
  --assignee-object-id <principal-object-id> \
  --assignee-principal-type ServicePrincipal \
  --role "Foundry User" \
  --scope <foundry-project-or-resource-scope>
```

If the target cloud still lists the earlier role names, replace `Foundry User` with `Azure AI User`. For custom clouds, use the role name and role assignment scope exposed by that cloud.

## Configure Azure OpenAI

1. Open **Admin Settings** and go to **AI Models** for global endpoints, or open the personal/group workspace endpoint management area for scoped endpoints.
2. Add or edit a **Model Endpoint**.
3. Set **Provider** to **Azure OpenAI**.
4. Enter an endpoint name and the Azure OpenAI resource endpoint, such as `https://<openai-resource>.openai.azure.com/`.
5. Select the **OpenAI API Version** used by the deployment.
6. For managed identity, set **Authentication Type** to **Managed Identity**. Choose **System Assigned** or **User Assigned**. For user-assigned identity, enter the identity client ID.
7. For service principal, set **Authentication Type** to **Service Principal** and enter tenant ID, client ID, and client secret.
8. Enter **Subscription ID** and **Resource Group** when using managed identity or service principal. These are required for **Fetch Models** because Azure OpenAI discovery uses ARM deployment listing.
9. Select **Fetch Models**. Confirm the expected deployments appear, then use **Test Model** on at least one model row.
10. Save the endpoint, then save settings when you are in Admin Settings.

For API key mode, enter the endpoint, OpenAI API version, and API key. Add model rows manually if **Fetch Models** is unavailable, because API key authentication is inference-only for this modal.

## Configure Foundry Classic

Use **Foundry (classic)** when the target is an existing classic Foundry project or classic Foundry agent flow.

1. Grant the identity or service principal `Foundry User` or `Azure AI User` on the target Foundry project or backing Foundry resource.
2. Add or edit a **Model Endpoint**.
3. Set **Provider** to **Foundry (classic)**.
4. Enter the Foundry project endpoint. If the endpoint already contains `/api/projects/<project>`, the modal can infer the project name. Otherwise, fill **Foundry Project Name**.
5. Keep **Project API Version** at `v1` unless your Foundry project specifically requires another supported value.
6. Keep **OpenAI API Version** at **Endpoint default (v1)** for Foundry project model inference. Simple Chat normalizes these calls to `/openai/v1`, and that path rejects `api-version` query values.
7. Select **Managed Identity** or **Service Principal** and fill the identity fields.
8. For Azure Government, set **Management Cloud** to **Azure Government**. For a custom cloud, set **Management Cloud** to **Custom**, then enter the custom authority and Foundry scope.
9. Select **Fetch Models** to verify project deployment discovery.
10. When importing classic Foundry agents, use the saved endpoint from the agent modal and fetch the classic agents from that project.

## Configure New Foundry

Use **New Foundry** for the application-based Foundry runtime and New Foundry agent/application flows.

1. Grant the identity or service principal `Foundry User` or `Azure AI User` on the target Foundry project or backing Foundry resource.
2. Add or edit a **Model Endpoint**.
3. Set **Provider** to **New Foundry**.
4. Enter the New Foundry project endpoint. If the URL does not include `/api/projects/<project>`, fill **Foundry Project Name**.
5. Keep **Project API Version** at `v1` unless your Foundry project requires a different supported value.
6. Keep **OpenAI API Version** at **Endpoint default (v1)** for New Foundry project model inference. Simple Chat normalizes these calls to `/openai/v1`, and that path rejects `api-version` query values. Claude deployments are detected from the model name and use the Anthropic messages protocol.
7. Select **Managed Identity** or **Service Principal** and fill the identity fields.
8. Set **Management Cloud** for public, Azure Government, or custom cloud. Custom cloud requires both **Custom Authority** and **Foundry Scope**.
9. Select **Fetch Models** and test a deployment.
10. When creating New Foundry agents, use the saved endpoint in the agent modal so application discovery and runtime calls use the same identity and project settings.

API keys are not a replacement for Foundry RBAC when users need New Foundry agent discovery, Foundry Workflow discovery, or chat-selectable Foundry agent invocation. For API-key-only model inference, **Fetch Models** is unavailable; add each deployment row manually and test it before saving.

## Validate The Setup

- **Fetch Models** returns the expected model deployments for the selected provider.
- **Test Model** succeeds for at least one enabled model row.
- Classic Foundry agent fetch, New Foundry application fetch, or Foundry Workflow fetch succeeds when you configure those agent types.
- A normal user can select the model or agent in chat only when the endpoint scope and governance settings allow it.
- Application logs do not show `403`, `401`, missing client secret, missing project name, or missing subscription/resource group errors.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Azure OpenAI **Fetch Models** fails | The identity can call inference but cannot read ARM deployment metadata. | Add `Reader` on the Azure OpenAI resource or correct parent scope, and confirm subscription ID, resource group, and endpoint resource name match. |
| Azure OpenAI **Test Model** fails with authorization errors | Missing data-plane role. | Add `Cognitive Services OpenAI User` on the Azure OpenAI resource. |
| Foundry **Fetch Models** fails | Wrong provider, wrong project endpoint, missing project name, wrong cloud authority/scope, or missing Foundry RBAC. | Confirm provider is Foundry (classic) or New Foundry, verify the project endpoint, then assign `Foundry User` or `Azure AI User` to the modal identity. |
| Grok, Meta/Llama, DeepSeek, or another non-OpenAI provider fails with `api-version query parameter is not allowed when using /v1 path` | A dated preview or other query-style **OpenAI API Version** is being applied to the normalized `/openai/v1` inference path. | Keep **OpenAI API Version** at `Endpoint default (v1)`, save the endpoint, then run **Test Model** again. |
| DeepSeek, Grok, Llama, or another non-OpenAI family returns empty content or content-filter errors only from Simple Chat | The request may include model-family-specific parameters such as `reasoning_effort`. | Use the current Simple Chat version, which sends reasoning effort only to known OpenAI reasoning families, then test the model again. |
| DeepSeek, Grok, Llama, or another non-OpenAI family works in direct probes but fails only in the app | App-added memory system messages may trigger provider-side content filters. | Use the current Simple Chat version, which folds saved memory values into the latest user message as plain background notes for non-OpenAI Foundry models. |
| Service principal cannot authenticate | Tenant ID, client ID, or secret is incorrect, expired, or saved against the wrong endpoint. | Rotate the secret, update the endpoint, and confirm the enterprise application has the role assignment. |
| User-assigned managed identity is ignored | The client ID is missing or the identity is not attached to the App Service. | Attach the identity to the App Service and enter the managed identity client ID, not the object ID. |
| API key endpoint cannot fetch models | API key mode is inference-only for discovery paths. | Add model rows manually, or switch to managed identity/service principal and assign RBAC. |

## Related Documentation

- [Use Managed Identity]({{ '/how-to/use_managed_identity/' | relative_url }})
- [Admin configuration overview]({{ '/admin_configuration/' | relative_url }})
- [Workspace Multi Endpoints]({{ '/explanation/features/v0.241.001/WORKSPACE_MULTI_ENDPOINTS/' | relative_url }})
- [Dual Foundry Agent Support]({{ '/explanation/features/v0.241.001/DUAL_FOUNDRY_AGENT_SUPPORT/' | relative_url }})