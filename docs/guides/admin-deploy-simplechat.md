---
layout: page
title: "Deploy SimpleChat as an administrator"
description: "Choose a SimpleChat deployment path, prepare the required Azure resources, run the rollout, and verify first boot."
section: "Guides"
audience: admin
---

## What this covers

This guide helps administrators choose a deployment path, line up the required Azure and identity prerequisites, run the deployment through the correct reference guide, and prove the new SimpleChat site is ready for first configuration.

{% include media.html type="video"
                      title="Deploy SimpleChat as an administrator walkthrough"
                      poster="video-posters/guide-admin-deploy-simplechat.png"
                      capture="Recording planned. Walk the full journey end to end and explain the decisions an admin makes along the way." %}

## Why it matters

Deployment choices decide the runtime model you will operate later. The repo-supported deployers run SimpleChat as a container-based App Service, while the manual notes are for intentional native Python App Service deployments. Picking the wrong path can lead to the wrong startup command, upgrade command, or rollback expectation.

## Before you start

- Confirm you have Azure subscription rights to create the app, data, search, storage, monitoring, and AI resources required by the path you choose.
- Confirm who can create or coordinate the Entra application registration and app roles used for sign-in and role-gated features.
- Install the toolchain for your chosen path. The recommended Azure Developer CLI path requires Azure Developer CLI, Azure CLI, Git, and Python 3.12 because the repo deployment hooks run Python.
- Decide whether the deployment must use Azure Government, managed identity, enterprise private networking, or a native Python App Service model before you run the first deployer.

## Step 1: Choose the deployment path

Use the deployment references as the mechanical source of truth instead of copying command details into this journey.

| Choose this path | Use it when | Read next |
| --- | --- | --- |
| Azure Developer CLI | You want the repo's recommended end-to-end flow for provisioning, configuration, and application deployment. | [Azure Developer CLI deployment]({{ '/reference/deploy/azd-cli_deploy/' | relative_url }}) |
| Azure CLI with PowerShell | You want a script-driven container App Service rollout with more direct sequencing and recovery control than AZD. | [Azure CLI with PowerShell deployment]({{ '/reference/deploy/azurecli_powershell_deploy/' | relative_url }}) |
| Bicep | You need to inspect or customize the infrastructure modules directly. | [Bicep deployment]({{ '/reference/deploy/bicep_deploy/' | relative_url }}) |
| Terraform | Your environment already manages infrastructure through Terraform and can own the image-publishing flow. | [Terraform deployment]({{ '/reference/deploy/terraform_deploy/' | relative_url }}) |
| Manual native Python | You intentionally operate native Python App Service instead of the repo container deployers. | [Manual deployment notes]({{ '/reference/deploy/manual_deploy/' | relative_url }}) |

{% include media.html src="guides/admin-deploy-simplechat-path.png"
                      alt="Deployment decision table showing when to choose AZD, Azure CLI with PowerShell, Bicep, Terraform, or manual native Python."
                      title="Choose the deployment path"
                      capture="Capture the deployment reference decision map with the recommended order visible." %}

## Step 2: Prepare the required Azure resources

A first deployment needs the core runtime resources before optional capabilities matter: App Service, Azure OpenAI for chat, Azure OpenAI embeddings for retrieval, Azure AI Search, Cosmos DB for app data, Document Intelligence for ingestion, and monitoring. Optional resources such as Content Safety, Video Indexer, Speech, Storage for Enhanced Citations, Redis, and APIM should be provisioned only when the matching feature is in scope.

For resource sizing and service-specific notes, use [Manual Setup]({{ '/setup_instructions_manual/' | relative_url }}). For Azure Government, managed identity, and private endpoint patterns, use [Special Setup Scenarios]({{ '/setup_instructions_special/' | relative_url }}).

## Step 3: Run the deployment reference

Follow the selected reference guide from start to finish. For the current AZD path, initialize the environment, answer subscription, region, and environment prompts, and let the deployment provision resources and deploy the app together. For script-driven or IaC paths, keep the deployment model aligned with the reference and avoid mixing native Python startup guidance into container deployments.

{% include media.html src="guides/admin-deploy-simplechat-run.png"
                      alt="Terminal or deployment output showing the selected SimpleChat deployer completing successfully."
                      title="Run the deployer"
                      capture="Capture the final successful deployment output with resource names and secrets redacted." %}

## Step 4: Keep startup behavior aligned with the runtime

Container-based deployments through AZD, Azure CLI with PowerShell, Bicep, and Terraform use the container entrypoint to start Gunicorn. Do not add the native Python startup command to those App Services. Native Python deployments must deploy the `application/single_app` folder and use the startup command documented in [Manual deployment notes]({{ '/reference/deploy/manual_deploy/' | relative_url }}).

## Step 5: Complete first-boot checks

Open the app URL from the deployment output, sign in, and confirm the application reaches the authenticated experience. Then open Admin Settings and verify the first configuration tabs are available before inviting end users.

## Verify it worked

- The App Service is reachable at the expected URL.
- Sign-in completes through the intended Entra tenant and returns to SimpleChat.
- Admin Settings opens for an administrator.
- A basic chat model is ready or you know that the next step is [first configuration]({{ '/guides/admin-first-configuration/' | relative_url }}).
- Monitoring or deployment logs show the site started cleanly.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The site starts but native Python commands are being discussed for a container deployment | The runtime model was mixed during setup | Recheck the deployment reference and remove native Python startup assumptions from container App Service paths. |
| Authentication redirects fail after a routed-domain setup | Front Door or redirect URL configuration is incomplete | Review [Scale settings]({{ '/admin/scale/' | relative_url }}) and validate sign-in through the routed URL after saving. |
| The app loads but document search fails | Embedding, AI Search, or Document Intelligence configuration is incomplete | Finish [AI Models settings]({{ '/admin/ai-models/' | relative_url }}) and [Search and Extract settings]({{ '/admin/search-extract/' | relative_url }}). |

## Related

- [Getting Started]({{ '/setup_instructions/' | relative_url }})
- [Deployment Reference]({{ '/reference/deploy/' | relative_url }})
- [Manual Setup]({{ '/setup_instructions_manual/' | relative_url }})
- [Special Setup Scenarios]({{ '/setup_instructions_special/' | relative_url }})
- [First configuration guide]({{ '/guides/admin-first-configuration/' | relative_url }})
