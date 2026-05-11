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
    url: /how-to/upgrade_paths/
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
				<p>The main flow lives in <code>deployers/azurecli/deploy-simplechat.ps1</code>, with destroy/reset support in the paired cleanup script.</p>
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
- `deployers/azurecli/destroy-simplechat.ps1`

## Quick start

1. Review the variables near the top of `deploy-simplechat.ps1`.
2. Sign in to the target Azure cloud and subscription.
3. Run the deployer from PowerShell or `pwsh`.

```powershell
cd deployers/azurecli
./deploy-simplechat.ps1
```

## References

- [Setup Instructions](../../setup_instructions.md)
- [Upgrade Paths](../../how-to/upgrade_paths.md)
- [Azure CLI deployer README](https://github.com/microsoft/simplechat/blob/main/deployers/azurecli/README.md)