---
layout: page
title: "Update an existing SimpleChat deployment"
description: "Plan, back up, upgrade, validate, and roll back a SimpleChat deployment without mixing runtime models."
section: "Guides"
audience: admin
---

## What this covers

This guide helps administrators update an existing SimpleChat environment by identifying the current version and runtime model, taking backups, choosing the matching upgrade path, validating the release, and preparing a rollback route.

{% include media.html type="video"
                      title="Update an existing SimpleChat deployment walkthrough"
                      poster="video-posters/guide-admin-update-simplechat.png"
                      capture="Recording planned. Walk the full journey end to end and explain the decisions an admin makes along the way." %}

## Why it matters

The correct upgrade path depends on how the current site is deployed. Native Python App Service upgrades need startup-command validation. Container-based deployments normally use `azd deploy` for code-only updates and reserve provisioning commands for infrastructure changes. A release plan that ignores that split can make rollback harder than the change itself.

## Before you start

- Identify whether the running site is native Python App Service or a container-based App Service deployed through AZD, Azure CLI with PowerShell, Bicep, or Terraform.
- Record the current SimpleChat version from `application/single_app/config.py` in the release you are running or from your deployed artifact metadata if your operations process tracks images separately.
- Confirm you can access App Service logs, Application Insights, Cosmos DB, Azure AI Search, and any storage used for Enhanced Citations or backups.
- Schedule the change window according to your tenant's availability and validation requirements.

## Step 1: Check the current deployment model and version

Start with [Upgrade Paths]({{ '/guides/upgrade-paths/' | relative_url }}). The first decision is deployment model, not command choice. Confirm whether App Service is pulling a container image or running native Python code. Then record the current app version and current image tag or deployment package so rollback has a known target.

{% include media.html src="guides/admin-update-simplechat-inventory.png"
                      alt="Upgrade inventory showing runtime model, current version, image or package identifier, and App Service details."
                      title="Inventory the current deployment"
                      capture="Capture the current deployment model and version evidence with subscription and secret values redacted." %}

## Step 2: Back up the data surfaces first

Use [Backup, Migrate & Restore settings]({{ '/admin/backup-recovery/' | relative_url }}) before changing code or infrastructure. At minimum, preserve Cosmos DB data and AI Search indexes. Include source document blobs when Enhanced Citations are enabled and those blobs are required for restore or migration. Prefer a recent successful backup plus a clear restore policy over assuming the platform backup is enough.

## Step 3: Choose the matching upgrade path

Use the upgrade guide's split:

| Current deployment | Normal upgrade path | Notes |
| --- | --- | --- |
| Native Python App Service | VS Code deploy, Azure CLI ZIP deploy, or deployment slots | Confirm the native Python Gunicorn startup command before closing the release. |
| Container-based App Service through AZD, Bicep, Terraform, or repo deployers | `azd deploy` for code-only releases | Use `azd provision` for infrastructure-only changes and `azd up` when app and infrastructure change together. |
| Azure CLI with PowerShell image rollout | `deployers/azurecli/upgrade-simplechat.ps1` | Use when your App Service already pulls from ACR and you want a PowerShell-first code-only rollout. |
| Image-tag promotion model | Move App Service back or forward between known image tags | Treat this as an advanced operations path that depends on your ACR and App Service process. |

{% include media.html src="guides/admin-update-simplechat-path.png"
                      alt="Upgrade decision table separating native Python, container, PowerShell image rollout, and image-tag promotion paths."
                      title="Pick the upgrade path"
                      capture="Capture the Upgrade Paths decision guide with the deployment-model split visible." %}

## Step 4: Run the update through the chosen path

For container releases, use the smallest command that matches the change: application-only, infrastructure-only, or both. For native Python releases, deploy the `application/single_app` folder and verify dependency installation and startup behavior. For production, prefer deployment slots or image tags when your operating model supports staged validation and fast rollback.

## Step 5: Validate after release

Open the updated site, sign in, open Admin Settings, run basic chat, and test one document retrieval flow if workspaces are enabled. Check Application Insights or App Service logs for startup errors, dependency failures, authentication problems, downstream service failures, and unexpected throttling.

{% include media.html src="guides/admin-update-simplechat-validate.png"
                      alt="Post-upgrade validation checklist showing sign-in, chat, document retrieval, and telemetry checks."
                      title="Validate the upgrade"
                      capture="Capture the post-upgrade validation checklist or monitoring view after a successful release." %}

## Step 6: Roll back when validation fails

Use the rollback method that matches the rollout. Swap back if you used deployment slots. Repoint App Service to the prior known-good image tag if you use image promotion. Redeploy the previous package for native Python when package rollback is your process. If data changed during the failed release, use [Backup, Migrate & Restore settings]({{ '/admin/backup-recovery/' | relative_url }}) only after preflight confirms the target and collision policy.

## Verify it worked

- The site reports or corresponds to the intended SimpleChat version or image tag.
- App Service startup logs do not show dependency or Gunicorn failures.
- Authentication, Admin Settings, basic chat, and representative workspace retrieval work.
- Application Insights requests and exceptions do not show a new failure pattern.
- The rollback target remains available until the release is accepted.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A native Python site fails after deployment | Startup command or deployment folder is wrong | Use the native Python startup command and deploy `application/single_app` as documented in [Manual deployment notes]({{ '/reference/deploy/manual_deploy/' | relative_url }}). |
| A container release was reprovisioned unnecessarily | `azd up` was used for a code-only change | Prefer `azd deploy` for application-only updates and use provisioning commands only when infrastructure changed. |
| Post-upgrade document retrieval fails | Search, embedding, or extraction settings changed or a dependency is unhealthy | Check [AI Models settings]({{ '/admin/ai-models/' | relative_url }}), [Search and Extract settings]({{ '/admin/knowledge/' | relative_url }}), and related telemetry. |

## Related

- [Upgrade Paths]({{ '/guides/upgrade-paths/' | relative_url }})
- [Deployment Reference]({{ '/reference/deploy/' | relative_url }})
- [Backup, Migrate & Restore settings]({{ '/admin/backup-recovery/' | relative_url }})
- [Operate SimpleChat day to day]({{ '/guides/admin-operate-simplechat/' | relative_url }})
