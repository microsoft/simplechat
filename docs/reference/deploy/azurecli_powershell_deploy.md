---
layout: showcase-page
title: "Azure CLI with PowerShell Deployment"
permalink: /reference/deploy/azurecli_powershell_deploy/
menubar: docs_menu
accent: blue
eyebrow: "Deployment Reference"
description: "Use the script-driven Azure CLI and PowerShell deployer when you want more sequencing control than the default AZD flow."
hero_icons:
  - bi-terminal
  - bi-cloud-check
  - bi-arrow-repeat
hero_pills:
  - Script-driven rollout
  - Container App Service model
  - Direct sequencing control
hero_links:
  - label: "Deployment reference"
    url: /reference/deploy/
    style: primary
  - label: "Upgrade paths"
    url: /guides/upgrade-paths/
    style: secondary
nav_links:
  prev:
    title: "Azure Developer CLI"
    url: /reference/deploy/azd-cli_deploy/
  next:
    title: "Bicep Deployment"
    url: /reference/deploy/bicep_deploy/
show_nav: true
---

This deployer keeps you in the repo's container-based deployment model while giving you more direct script control over sequencing, retries, and environment-specific adjustments.

<section class="latest-release-card-grid">
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-terminal"></i></div>
				<h2>Script-first operations</h2>
				<p>Use this when you want the deployment flow to live in PowerShell instead of AZD orchestration commands.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-list-check"></i></div>
				<h2>Explicit sequencing</h2>
				<p>The script-driven model makes it easier to reason about recovery steps and operational checkpoints in environments that prefer scripted control.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-box-seam"></i></div>
				<h2>Same runtime model</h2>
				<p>This path still deploys the containerized App Service runtime, so Gunicorn startup stays with the container entrypoint.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-tools"></i></div>
				<h2>Key scripts</h2>
				<p>The main flow lives in <code>deployers/azurecli/deploy-simplechat.ps1</code>, with paired PowerShell scripts for code-only upgrades and cleanup.</p>
		</article>
</section>

<div class="latest-release-note-panel">
		<h2>Keep the runtime rule consistent</h2>
		<p>This deployer targets container-based Azure App Service. Do not add the native Python startup command for this path unless you intentionally change deployment models.</p>
</div>

## When to choose this path

- You want a script-driven deployment flow without `azd`
- You want more direct control over sequencing and recovery steps
- You still want the repo's container-based App Service deployment model

## Main files

- `deployers/azurecli/deploy-simplechat.ps1`
- `deployers/azurecli/publish-simplechat.ps1`
- `deployers/azurecli/upgrade-simplechat.ps1`
- `deployers/azurecli/destroy-simplechat.ps1`

## Quick start

1. Review the variables near the top of `deploy-simplechat.ps1`.
2. Sign in to the target Azure cloud and subscription.
3. Run the deployer from PowerShell or `pwsh`.

```powershell
cd deployers/azurecli
./deploy-simplechat.ps1
```

## Interactive container publishing

For routine updates to an existing Linux single-container app, use
`publish-simplechat.ps1` (deployer **1.0.35**, introduced alongside application
**0.261.042**). It prompts for subscription, ACR, and web app, uploads local source
for an ACR-hosted build, then pins the app to the resulting image digest.
It preserves existing registry authentication and does not require local Docker.

```powershell
pwsh -NoProfile -File ./deployers/azurecli/publish-simplechat.ps1
```

VS Code's **Tasks: Run Task** offers **SimpleChat: Publish container (interactive)**
and a read-only preview task. Deployer **1.0.35** includes prefilled
**SimpleChat: Publish beta container (confirm)** and
**SimpleChat: Publish dev container (confirm)** tasks. Every task prompts for an
image reference with `simplechat:latest` as the default. All selections also accept parameters;
`-NonInteractive -Yes` supports automation and `-WhatIf` previews without mutations.
Uncommitted source requires separate approval or `-AllowDirty`.

Use `-ImageName simplechat:latest` for the same image choice from PowerShell, or
choose a distinct tag. Direct script calls without an image tag retain generated
timestamp/revision tags. New builds use `az acr build --no-logs` and wait for the
CLI's status polling to finish, avoiding Windows Unicode build-log crashes.
Beta and dev tasks use `-UseWebhook`: they require an enabled push hook matching
the requested tag and leave the already-configured app image unchanged. The ACR
push webhook triggers the app to pull that tag. This mode does not pin the app to
a digest or verify webhook delivery. Ordinary publishing instead updates App
Service to the successful run's output digest, even when another build overwrites
`latest`.

Authenticate with Azure CLI in the desired cloud first. The app must already pull
from the selected registry. Sidecar/Compose apps and registry authentication
changes are not supported. Configuration verification is not proof of startup:
verify the running app version and workflows after publishing.
See the [publisher reference](https://github.com/microsoft/simplechat/blob/main/deployers/azurecli/README.md#interactive-container-publishing)
for parameters, permissions, build-only operation, and rollback.

## Legacy code-only upgrades

For container-only releases where infrastructure does not change, use `upgrade-simplechat.ps1`.

This legacy script enables registry admin credentials. Prefer the publisher above
when preserving an existing managed-identity pull configuration.

This script builds the image in ACR, updates the current App Service container image, verifies the updated image reference, and restarts the site. It gives the Azure CLI deployer a PowerShell-first equivalent to the normal `azd deploy` container rollout path without invoking the AZD post-configuration Python flow.

Example:

```powershell
cd deployers/azurecli
./upgrade-simplechat.ps1 `
	-AcrName registrysimplechatprod `
	-ImageName simplechat:2026-04-29_01 `
	-BaseName contoso `
	-Environment prod
```

## References

- [Setup Instructions]({{ '/start/deployment-options/' | relative_url }})
- [Upgrade Paths]({{ '/guides/upgrade-paths/' | relative_url }})
- [Azure CLI deployer README](https://github.com/microsoft/simplechat/blob/main/deployers/azurecli/README.md)