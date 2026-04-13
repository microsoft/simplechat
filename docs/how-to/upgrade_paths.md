---
layout: showcase-page
title: "Upgrade Paths"
permalink: /how-to/upgrade_paths/
menubar: docs_menu
accent: emerald
eyebrow: "How-To Guide"
description: "Choose the right upgrade method based on whether your deployment is native Python App Service or one of the repo's container-based deployment paths."
hero_icons:
  - bi-arrow-repeat
  - bi-box-seam
  - bi-cloud-arrow-up
hero_pills:
  - Deployment model first
  - Container and native paths differ
  - Validate before closing the release
hero_links:
  - label: "Deployment reference"
    url: /reference/deploy/
    style: primary
  - label: "Manual deployment notes"
    url: /reference/deploy/manual_deploy/
    style: secondary
---

The first upgrade decision is not which command to run. It is whether your existing site is running as native Python App Service or as one of the repo's container-based deployment models. That single distinction drives startup handling, rollout mechanics, and rollback choices.

<section class="latest-release-card-grid">
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-filetype-py"></i></div>
        <h2>Native Python upgrades</h2>
        <p>Use VS Code deploy, ZIP deploy, or deployment slots when the app code is deployed directly to App Service instead of through a container image.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-box-seam"></i></div>
        <h2>Container upgrades</h2>
        <p>Use <code>azd deploy</code> for routine code updates when infrastructure is unchanged and reserve <code>azd up</code> for combined app-plus-infrastructure releases.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-tag"></i></div>
        <h2>Image-only rollouts</h2>
        <p>Teams already managing App Service against ACR can use image-tag promotion or restart-based rollout strategies without reprovisioning infrastructure.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-check2-square"></i></div>
        <h2>Validation is part of the upgrade</h2>
        <p>Checking startup behavior, dependency installation, and app health after release is not optional. It is part of the upgrade path itself.</p>
    </article>
</section>

<div class="latest-release-note-panel">
    <h2>Figure out the runtime model before you change anything</h2>
    <p>If you skip the deployment-model check, you can apply the wrong startup-command guidance, wrong release command, or wrong rollback assumption. That is the most common way an upgrade guide becomes misleading.</p>
</div>

## Choose the Right Upgrade Path

| If you deployed SimpleChat as... | Use this path | Default upgrade command or method |
| :--- | :--- | :--- |
| **Native Python Azure App Service** | [Native Python App Service Upgrades](#native-python-app-service-upgrades) | VS Code deployment or Azure CLI ZIP deploy |
| **Container-based Azure App Service** using the repo `azd`, Bicep, Terraform, or Azure CLI deployers | [Container-Based App Service Upgrades](#container-based-app-service-upgrades) | `azd deploy` for code-only updates |

## Native Python App Service Upgrades

This path applies when you deployed the application code directly to Azure App Service instead of using the repo's container image.

### Required Startup Command Check

For native Python App Service upgrades, do **not** leave the App Service Stack Settings Startup command blank.

Deploy and run the `application/single_app` folder in App Service.

Use this Startup command:

```bash
python -m gunicorn -c gunicorn.conf.py app:app
```

Validate this before or during the upgrade. A missing or incorrect Startup command is one of the fastest ways to turn a straightforward code update into an outage.

### Recommended Native Upgrade Methods

#### Option 1: Visual Studio Code Deployment

Use this when you want the simplest manual update path.

1. Sign in to Azure from VS Code.
2. Open the Azure extension.
3. Find the existing App Service.
4. Right-click the App Service.
5. Select **Deploy to Web App...**.
6. Deploy the `application/single_app` folder.

This is the same deployment mechanism used for an initial native Python deployment. It is also a valid upgrade method.

#### Option 2: Azure CLI ZIP Deploy

Use this when you want a repeatable manual package-and-deploy flow.

1. Create a deployment ZIP from the required application contents.
2. Build that ZIP from inside `application/single_app` so the deployed package contains the app files directly.
3. Confirm `SCM_DO_BUILD_DURING_DEPLOYMENT=true` in App Service configuration.
4. Deploy the ZIP with Azure CLI:

```bash
az webapp deploy \
  --resource-group <Your-Resource-Group-Name> \
  --name <Your-App-Service-Name> \
  --src-path ../deployment.zip \
  --type zip
```

This is an upgrade path, not only an initial deployment path. Package the new version, deploy the ZIP, and validate the Startup command before closing the change.

#### Option 3: Deployment Slots for Production

Use deployment slots when you want staged validation and rollback capability for native Python deployments.

Recommended flow:

1. Deploy the updated code to a staging slot.
2. Validate the staging slot URL.
3. Swap staging into production.
4. Roll back with another swap if needed.

### Native Python References

- [Manual setup instructions](../setup_instructions_manual.md)
- [Manual deployment notes](../reference/deploy/manual_deploy.md)

## Container-Based App Service Upgrades

This path applies to the repo-provided `azd`, Bicep, Terraform, and Azure CLI deployers. These deployers run SimpleChat as a **container** on Azure App Service.

### Important Runtime Rule

For container-based deployments, do **not** add a native Python App Service Startup command. Gunicorn is started by the container entrypoint in `application/single_app/Dockerfile`.

### Upgrade Decision Guide

| Situation | Recommended action | Why |
| :--- | :--- | :--- |
| **Application code change only** | `azd deploy` | Updates the app without treating the release like a full infrastructure event |
| **Infrastructure change only** | `azd provision` | Applies Azure resource/configuration changes without redeploying the app container |
| **Application code and infrastructure changed together** | `azd up` | Runs the combined app + infrastructure workflow |
| **You are considering `azd down --purge` for a normal release** | Avoid this for routine upgrades | This is destructive and not a standard upgrade path |

### Recommended Default for Container Releases

For a normal code release, start with:

```bash
azd deploy
```

Do **not** assume `azd up` is required for every upgrade. Use `azd up` only when the release also needs infrastructure updates.

When you are unsure whether infrastructure changes are included, review them first:

```bash
azd provision --preview
```

### Advanced Option: ACR/Image-Only Rollout

If your App Service is already configured to pull its image from Azure Container Registry and your goal is to avoid any infrastructure reprovisioning, you can use an image-only rollout.

The repo already contains an image publish workflow:

- [.github/workflows/docker_image_publish.yml](../../.github/workflows/docker_image_publish.yml)

That workflow publishes:

1. A timestamped image tag for rollback-friendly releases.
2. A `latest` tag for the current build.

Use this path when your operations model is:

1. Build and push the updated image to ACR.
2. Refresh App Service to use the new image tag, or restart it if your container configuration intentionally tracks `latest`.
3. Roll back by moving App Service back to the prior known-good tag.

This is an **advanced operational option**, not the default repo deployment workflow. It exists specifically for teams that want to update the container image without treating every release like a provisioning event.

### Container Upgrade References

- [AZD deployment guide](../reference/deploy/azd-cli_deploy.md)
- [Azure CLI with PowerShell deployment guide](../reference/deploy/azurecli_powershell_deploy.md)
- [Bicep deployment guide](../reference/deploy/bicep_deploy.md)
- [Terraform deployment guide](../reference/deploy/terraform_deploy.md)

## Summary

- Native Python App Service upgrades: validate the Startup command, then use VS Code deploy, ZIP deploy, or deployment slots.
- Container-based upgrades: prefer `azd deploy` for code-only changes and reserve `azd up` for releases that also change infrastructure.
- If you already operate App Service against ACR and want lower-touch rollouts, use an image-only update process instead of full reprovisioning.