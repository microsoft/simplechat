---
layout: showcase-page
title: "Bicep Deployment"
permalink: /reference/deploy/bicep_deploy/
menubar: docs_menu
accent: orange
eyebrow: "Deployment Reference"
description: "Use this page when you need to inspect or modify the Bicep templates that sit underneath the repo's primary deployment workflow."
hero_icons:
  - bi-diagram-3
  - bi-braces-asterisk
  - bi-cloud-check
hero_pills:
  - Repo IaC layer
  - Best used with AZD orchestration
  - Container runtime underneath
hero_links:
  - label: "AZD deployment"
    url: /reference/deploy/azd-cli_deploy/
    style: primary
  - label: "Enterprise networking"
    url: /how-to/enterprise_networking/
    style: secondary
nav_links:
  prev:
    title: "Azure CLI with PowerShell"
    url: /reference/deploy/azurecli_powershell_deploy/
  next:
    title: "Terraform Deployment"
    url: /reference/deploy/terraform_deploy/
show_nav: true
---

The Bicep templates are the infrastructure backbone behind the repo's recommended deployment flow. Most teams should still apply them through AZD, but this page is where you orient yourself when you need to inspect or customize the infrastructure directly.

<section class="latest-release-card-grid">
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-boxes"></i></div>
				<h2>Understand the IaC baseline</h2>
				<p>Use this path when you need to know what the repo is actually provisioning rather than treating AZD as a black box.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-wrench-adjustable"></i></div>
				<h2>Customize safely</h2>
				<p>Review or modify the files in <code>deployers/bicep/</code> when your organization needs network, SKU, or resource-layout changes.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-search"></i></div>
				<h2>Preview before applying</h2>
				<p>Keep <code>azd provision --preview</code> in the flow so you can inspect infrastructure impact before applying it to a shared environment.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-box-seam"></i></div>
				<h2>Remember the runtime model</h2>
				<p>The supported Bicep path still lands on container-based App Service, so startup behavior follows the container entrypoint rather than native Python app settings.</p>
		</article>
</section>

<div class="latest-release-note-panel">
		<h2>Use Bicep as the infrastructure layer, not a separate platform story</h2>
		<p>In this repo, Bicep is best understood as the IaC layer beneath AZD rather than a competing deployment experience. Start from the AZD guide unless your goal is specifically to inspect or change the infrastructure modules themselves.</p>
</div>

## When to choose this path

- You want to inspect or customize the Bicep templates in `deployers/bicep/`
- You want to understand the infrastructure used by the `azd` deployment flow
- You are troubleshooting infrastructure behavior or preparing Bicep module changes

## Recommended workflow

1. Start with the [Azure Developer CLI deployment guide](./azd-cli_deploy.md).
2. Review or modify the Bicep files under `deployers/bicep/`.
3. Use `azd provision --preview` or `azd up` to apply those changes through the supported workflow.

## References

- [Setup Instructions](../../setup_instructions.md)
- [Special Deployment Scenarios](../../setup_instructions_special.md)
- [Enterprise Networking](../../how-to/enterprise_networking.md)
- [Bicep deployer README](https://github.com/microsoft/simplechat/blob/main/deployers/bicep/README.md)
