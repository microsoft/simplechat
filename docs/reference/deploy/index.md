---
layout: showcase-page
title: "Deployment Reference"
permalink: /reference/deploy/
menubar: docs_menu
accent: emerald
eyebrow: "Reference"
description: "Choose the right Simple Chat deployment path and understand when each deployment model is the right operational fit."
hero_icons:
  - bi-rocket-takeoff
  - bi-cloud-arrow-up
  - bi-diagram-3
hero_pills:
  - AZD first
  - Container deployers by default
  - Native Python notes included
hero_links:
  - label: "Getting Started"
    url: /setup_instructions/
    style: primary
  - label: "Upgrade paths"
    url: /how-to/upgrade_paths/
    style: secondary
---

This section is the deployment decision map. Use it after you already understand the basics and need the path-specific guidance for the rollout model your team actually uses.

<section class="latest-release-card-grid">
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-rocket-takeoff"></i></div>
				<h2>Azure Developer CLI</h2>
				<p>The most current and best-supported path. Use it when you want provisioning, configuration, and deployment handled in one repo-aligned workflow.</p>
				<p><a href="{{ '/reference/deploy/azd-cli_deploy/' | relative_url }}">Open AZD reference</a></p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-terminal"></i></div>
				<h2>Azure CLI with PowerShell</h2>
				<p>Use this when you want a script-driven deployment flow with more control over sequencing and recovery than the default AZD experience.</p>
				<p><a href="{{ '/reference/deploy/azurecli_powershell_deploy/' | relative_url }}">Open script-driven path</a></p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-diagram-3"></i></div>
				<h2>Bicep and Terraform</h2>
				<p>Use these when infrastructure-as-code ownership is the main concern and your team needs more direct control over templates or state.</p>
				<p><a href="{{ '/reference/deploy/bicep_deploy/' | relative_url }}">Inspect IaC paths</a></p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-box-seam"></i></div>
				<h2>Manual native Python notes</h2>
				<p>Use the manual notes only when you are intentionally operating a native Python App Service deployment rather than the repo's container deployers.</p>
				<p><a href="{{ '/reference/deploy/manual_deploy/' | relative_url }}">Read native Python notes</a></p>
		</article>
</section>

<div class="latest-release-note-panel">
		<h2>Pick the runtime model first</h2>
		<p>The most important split is not AZD versus Terraform. It is container-based App Service versus native Python App Service. The repo's main deployment paths are container-based, and that changes startup-command handling, upgrade flow, and rollback expectations.</p>
</div>

## Recommended order

1. [Azure Developer CLI (`azd up`)](./azd-cli_deploy.md)
2. [Azure CLI with PowerShell](./azurecli_powershell_deploy.md)
3. [Bicep](./bicep_deploy.md)
4. [Terraform](./terraform_deploy.md)
5. [Manual deployment notes](./manual_deploy.md)

## Related guides

- [Setup Instructions](../../setup_instructions.md)
- [Upgrade Paths](../../how-to/upgrade_paths.md)
- [Special Deployment Scenarios](../../setup_instructions_special.md)