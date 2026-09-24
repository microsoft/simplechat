---
layout: showcase-page
title: "Configure Model Endpoint Identity"
permalink: /guides/model-endpoint-identity-setup/
menubar: docs_menu
accent: teal
eyebrow: "Admin How-To"
description: "Assign managed identity or service principal access for Azure OpenAI, Foundry (classic), and New Foundry model endpoints in the multi-endpoint modal."
version: "0.261.035"
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
    url: /guides/use-managed-identity/
    style: secondary
section: "Guides"
redirect_from:
  - /how-to/model_endpoint_identity_setup/
---

Use this guide when admins need to configure the shared **Model Endpoint** modal for Azure OpenAI, Foundry (classic), or New Foundry without depending on legacy single-endpoint settings.

Documented for version **0.261.035**. Model capacity overrides implemented in
version: **0.261.035**, tracked by `application/single_app/config.py`.

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
- Decide whether the endpoint is global, personal, or group scoped. The RBAC requirements are the same, but personal and group endpoints that use the application's managed identity have extra rules. See [Personal and group endpoints](#personal-and-group-endpoints-that-use-the-application-identity).
- If you use a service principal, create the Entra app registration first and keep the tenant ID, client ID, and client secret ready.
- If you use a user-assigned managed identity on a global endpoint, attach it to the App Service and copy the managed identity **Client ID** for the modal. Personal and group endpoints always use the deployment's default identity.
- Plan separate model endpoints when provider families need different project settings, authentication, or manual deployment rows. For Foundry project model inference, Simple Chat normalizes calls to `/openai/v1`, so keep **OpenAI API Version** at endpoint default `v1`.

## Choose The Provider

The modal provider decides which discovery API and token scope Simple Chat uses.

| Provider in the modal | Use it for | Endpoint value | RBAC target |
|-----------------------|------------|----------------|-------------|
| `Azure OpenAI` | Direct Azure OpenAI resource endpoints and Azure OpenAI-compatible APIM paths | `https://<openai-resource>.openai.azure.com/` for direct Azure OpenAI | The Azure OpenAI resource, or a parent resource group/subscription when your access model requires it |
| `Foundry (classic)` | Existing classic Foundry project agents and model deployments | `https://<foundry-resource>.services.ai.azure.com/api/projects/<project>` or the project base endpoint plus **Foundry Project Name** | The Foundry project when the portal exposes project-scoped access, otherwise the backing Foundry resource/account |
| `New Foundry` | Application-based Foundry runtime, New Foundry agents, and OpenAI-compatible project model deployments | The same Foundry project endpoint shape used by the New Foundry project | The Foundry project when the portal exposes project-scoped access, otherwise the backing Foundry resource/account |

For APIM, choose the provider that matches the backend service and select API key authentication when APIM expects a subscription key or other shared key. API key authentication can run inference, but it cannot use **Fetch Models** for Azure OpenAI ARM discovery or Foundry project discovery.

## Personal And Group Endpoints That Use The Application Identity

Personal and group endpoints are set up by people who aren't administrators. When
one of them authenticates with **Managed Identity**, the token Simple Chat sends
is the application's own. Simple Chat therefore decides where that token can go,
what it is for, and which identity issues it. These rules were implemented in
version **0.261.140**. They apply to Azure OpenAI, Foundry (classic), and New
Foundry endpoints in personal and group workspaces.

The rules don't apply to:

- global endpoints configured in Admin Settings;
- endpoints that use an API key or a service principal;
- custom connections.

| Rule | What it means |
| --- | --- |
| The endpoint must be an Azure AI service host in this deployment's cloud | Public cloud: `*.openai.azure.com`, `*.services.ai.azure.com`, `*.cognitiveservices.azure.com`, `*.api.cognitive.microsoft.com`. Azure Government: the same names ending in `.azure.us` or `.microsoft.us`. A custom cloud has no allowed hosts. APIM gateways (`*.azure-api.net`) and other proxies aren't allowed. |
| The token audience and authority are the deployment's own | Leave **Foundry Scope**, **Custom Authority**, and a **Custom** management cloud unset. Simple Chat uses the deployment's own values. |
| The deployment chooses the identity | A managed identity client ID can't be entered. The deployment's default identity is the one that needs the role assignments in [Assign Roles](#assign-roles). |

Saving an endpoint that breaks a rule is refused with a message that names the
rule. An endpoint saved before these rules stops working until it's changed:
tests, **Fetch Models**, and chat show the same message instead of calling the
endpoint. To reach a host outside the list, or to use a specific identity, use an
API key or a service principal, or ask an administrator to add a global endpoint.

## Choose API Versions

The endpoint API version fields below are intentionally separate. They also
differ from the exact **Model Version** in **Advanced model capacity**.

| Field | What it controls | Recommended starting point |
|-------|------------------|----------------------------|
| **Project API Version** | Foundry project discovery calls such as deployment listing, agent listing, and workflow listing. | Keep `v1` unless your Foundry project documentation says otherwise. |
| **OpenAI API Version** | Inference calls for OpenAI-compatible Foundry project model deployments. Simple Chat normalizes Foundry project endpoints to `/openai/v1`. | Keep `Endpoint default (v1)` for New Foundry project model endpoints. The `/v1` path does not allow an `api-version` query, including dated preview values. |

If one deployed model family works and another fails with API-version or unsupported-operation errors, create a separate endpoint for the failing family so you can isolate its project endpoint, authentication, deployment rows, and test results. For the normalized `/openai/v1` inference path, keep **OpenAI API Version** at endpoint default `v1`.

Claude deployments are detected from the deployment name or Anthropic endpoint path and use the Anthropic messages protocol at runtime. The endpoint still stores an OpenAI API Version for the other model rows on that endpoint, so keep Claude with compatible rows or use a separate endpoint when the configuration becomes confusing.

Live validation against Foundry-hosted model families showed that basic chat-completions calls work for DeepSeek, Grok, and Llama, but reasoning-effort support and memory context tolerance are model-specific. Simple Chat only sends reasoning effort to known OpenAI reasoning families such as GPT-5 and o-series models. For Foundry-hosted non-OpenAI chat-completions models, Simple Chat folds saved memory values into the latest user message as plain background notes instead of injecting memory system messages. This preserves memory context while avoiding provider-side content-filter blocks observed with system-style memory prompts.

The same endpoint runtime helpers are used for chat streaming, workflow execution, metadata extraction, endpoint test calls, and Semantic Kernel-backed tabular or agent services. This keeps provider selection, authentication, OpenAI-compatible `/openai/v1` normalization, and Anthropic routing consistent across Simple Chat features.

## Declare Verified Model Capacity

Use this workflow for a custom/on-premises deployment with documented limits, or
when a deployment alias does not identify the actual published model. The same
controls appear in Admin Settings and authorized personal/group workspace
endpoint editors; group endpoint changes still require the existing Owner or
Admin permission.

1. Obtain the deployed model's actual ID, exact version, hosting provider/cloud,
   and supported limits from its operator or first-party deployment
   documentation. A similarly named model, example generation length, or a
   commercial-cloud listing alone does not verify a different deployment.
2. Open the endpoint. Use **Advanced endpoint capacity** only for defaults that
   apply to its models. Otherwise, put the verified values in the relevant
   model's **Advanced model capacity** section.
3. If the deployment has an arbitrary name, enter its actual published ID in
   **Catalog Model ID**, and its exact version in **Model Version** where the
   serving limits depend on a snapshot. For example, map `team-chat` to
   `gpt-5.6-terra` only if that is the model actually deployed. Leave the request
   deployment/model name unchanged. Display names are not proof of capacity.
4. Enter **Context Window** for a shared input-plus-generation total, **Input
   Token Limit** only for an independently documented input ceiling, and
   **Output Token Limit** for a hard provider output maximum. All counts must be
   positive whole tokens, at most `9007199254740991`. Do not use zero, commas,
   fractions, or scientific notation. Leave undocumented values blank.
5. Choose **Token Limit Provider** when a specific hosting profile is required.
   **Auto / inherit** follows the selected endpoint/provider rather than
   changing the request destination. Set **Output Token Accounting** to **Total
   generation** only when the API's allowance includes reasoning and other
   generated tokens. **Visible output only** and **Unknown** describe
   incomplete accounting honestly; they do not manufacture a bounded reasoning
   allowance.
6. Configure **Response Length** separately as the per-request generation
   allowance. It is not a capacity declaration. Save the endpoint, and also
   save the main settings form for global endpoints. Personal/group editors
   save through their existing scope-specific routes.

Every field inherits independently from the model override, then the endpoint
override, then the exact catalog entry. Clearing an override restores
inheritance, stored as `null`. Unknown capacity is not unlimited capacity.
Independent input and output maxima may add up to more than the context window:
they are alternative ceilings, not a promise that both can be used at once.

Reopen the saved endpoint to confirm the exact identity, version, and overrides.
Fetch Models, Add Model, and other model-row refreshes retain configured version,
capacity, and capability metadata. A small successful Test Connection verifies
connectivity, not a model's maximum context or output allowance.

Editor API responses and page bootstrap data retain capacity, catalog identity,
output accounting, and explicit `null` inheritance at both endpoint and model
levels. Stored API keys, client secrets, and bearer/access/refresh credentials
are not returned with that metadata.

If server validation rejects a submitted budget, the workspace editor remains
open with a field-specific error; Admin Settings returns to the settings form
with an error message. Correct that field or clear it to inherit. Invalid values
are not silently discarded or saved as provider capacity.

Regression coverage is in
`functional_tests/test_model_endpoint_normalization_backend.py`,
`functional_tests/test_model_endpoint_capacity_save_validation.py`,
`functional_tests/test_model_capacity_editor_values.js`, and
`ui_tests/test_model_endpoint_capacity_editor.py`. The browser suite exercises
admin, personal, and group saves, clearing/inheritance, invalid inputs,
metadata/version preservation, inert text rendering, and mobile layout using
the real local editor assets.

## Understand Discovery Versus Inference

### Embedding inference

Implemented in version **0.261.106**, shared embedding connections use a separate
operation contract from chat. A Foundry project endpoint cannot route embeddings;
configure the embedding inference base for that connection explicitly, usually
the resource URL ending in `/openai/v1/`. Grant inference permissions on that
resource as well as project/management read permissions for discovery.

OpenAI-compatible custom embedding connections use API keys/tokens and manual
model entry. They do not acquire Azure tokens or use project discovery. The
embedding-specific test probes actual vectors; a successful chat or discovery
request does not prove embedding access. See [Configure AI connections]({{ '/guides/configure-ai-connections/' | relative_url }}).

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
6. For managed identity, set **Authentication Type** to **Managed Identity**. Choose **System Assigned** or **User Assigned**. For user-assigned identity on a global endpoint, enter the identity client ID. Personal and group endpoints use the deployment's default identity.
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
8. For Azure Government, set **Management Cloud** to **Azure Government**. For a custom cloud on a global endpoint, set **Management Cloud** to **Custom**, then enter the custom authority and Foundry scope. Personal and group endpoints that use managed identity can't set these.
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
8. Set **Management Cloud** for public, Azure Government, or custom cloud. Custom cloud requires both **Custom Authority** and **Foundry Scope**, and is available only for global endpoints or for personal and group endpoints that use a service principal.
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
| User-assigned managed identity is ignored | The client ID is missing or the identity is not attached to the App Service. Personal and group endpoints always use the deployment's default identity. | For a global endpoint, attach the identity to the App Service and enter the managed identity client ID, not the object ID. For a personal or group endpoint, grant the deployment's default identity access, or use a service principal. |
| "The application identity can be used only with an Azure AI endpoint in this cloud." | A personal or group endpoint uses managed identity with a host outside the allowed list, such as an APIM gateway. | Use an API key or a service principal, or ask an admin for a global endpoint. See [Personal and group endpoints](#personal-and-group-endpoints-that-use-the-application-identity). |
| "The application identity uses this deployment's own token audience and authority." | A personal or group endpoint that uses managed identity sets a Foundry scope, custom authority, or custom cloud. | Remove those settings, or use a service principal. |
| "The application identity is selected by this deployment." | A personal or group endpoint that uses managed identity sets a managed identity client ID. | Remove the client ID, or use a service principal. |
| API key endpoint cannot fetch models | API key mode is inference-only for discovery paths. | Add model rows manually, or switch to managed identity/service principal and assign RBAC. |

## Related Documentation

- [Use Managed Identity]({{ '/guides/use-managed-identity/' | relative_url }})
- [Admin configuration overview]({{ '/admin_configuration/' | relative_url }})