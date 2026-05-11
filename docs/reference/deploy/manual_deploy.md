---
layout: showcase-page
title: "Manual Deployment Notes"
permalink: /reference/deploy/manual_deploy/
menubar: docs_menu
accent: orange
eyebrow: "Deployment Reference"
description: "Use these notes when you are intentionally running Simple Chat as a native Python Azure App Service deployment instead of the repo's container deployers."
hero_icons:
  - bi-box-arrow-up-right
  - bi-file-earmark-zip
  - bi-gear
hero_pills:
  - Native Python only
  - Explicit startup command required
  - Upgrade validation matters
hero_links:
  - label: "Upgrade paths"
    url: /how-to/upgrade_paths/
    style: primary
  - label: "Deployment reference"
    url: /reference/deploy/
    style: secondary
nav_links:
  prev:
    title: "Terraform Deployment"
    url: /reference/deploy/terraform_deploy/
show_nav: true
---

Use this path only when native Python App Service is an intentional operating choice. It is not the default runtime model for the repo, so the main thing to get right is the distinction between native Python startup behavior and the container-based deployers used elsewhere.

<section class="latest-release-card-grid">
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-signpost-split"></i></div>
        <h2>Confirm the deployment model</h2>
        <p>Before touching the app, verify that you are actually running a native Python App Service deployment and not one of the repo's container paths.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-play-circle"></i></div>
        <h2>Set the startup command</h2>
        <p>Native Python deployments require an explicit Gunicorn startup command. Leaving it blank is a common way to turn a routine upgrade into downtime.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-cloud-upload"></i></div>
        <h2>Pick an upgrade method</h2>
        <p>Use VS Code deploy, ZIP deploy, or deployment slots based on how much repeatability and rollback capability you need.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-check2-square"></i></div>
        <h2>Validate after release</h2>
        <p>Confirm the app starts, dependencies install correctly, and the site is healthy before closing the change.</p>
    </article>
</section>

<div class="latest-release-note-panel">
    <h2>This page exists because native Python and container deployments behave differently</h2>
    <p>Container-based App Service deployments in this repo do not need the native Python startup command because the image entrypoint already launches Gunicorn. Native Python App Service does need it, and that difference drives the whole deployment checklist here.</p>
</div>

## Native Python App Service Startup Command

Set the App Service Stack Settings Startup command explicitly.

Do **not** leave the Startup command empty during an upgrade. Validate it before or during the release.

Deploy and run the `application/single_app` folder in App Service.

Use this Startup command:

```bash
python -m gunicorn -c gunicorn.conf.py app:app
```

## Native Python Upgrade Checklist

Use this checklist when updating an existing native Python App Service deployment.

1. Confirm the deployment model is **native Python Azure App Service**, not container-based App Service.
2. Confirm the `application/single_app` folder is the deployment unit and the Startup command is present and correct.
3. Choose an upgrade method:
   - **VS Code deployment** when you want the simplest manual update path.
   - **Azure CLI ZIP deploy** when you want a repeatable package-and-deploy path.
   - **Deployment slots** when you want validation and rollback for production.
4. If you use ZIP deploy, confirm `SCM_DO_BUILD_DURING_DEPLOYMENT=true` so App Service installs dependencies from `requirements.txt`.
5. Validate the site after deployment.

## Native Python Upgrade Methods

### Visual Studio Code Deployment

Deploy the updated code from VS Code by right-clicking the existing App Service and selecting **Deploy to Web App...**.

### Azure CLI ZIP Deploy

Package the updated application into a deployment ZIP, then deploy it:

```bash
az webapp deploy \
  --resource-group <Your-Resource-Group-Name> \
  --name <Your-App-Service-Name> \
  --src-path ../deployment.zip \
  --type zip
```

This is an upgrade method, not only an initial deployment method.

## Important distinction

- Native Python App Service needs the Startup command above.
- The repo-provided `azd`, Bicep, Terraform, and Azure CLI deployers do not need this because they deploy a container image whose entrypoint already launches Gunicorn.
