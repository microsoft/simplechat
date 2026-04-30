---
layout: showcase-page
title: "Terraform Deployment"
permalink: /reference/deploy/terraform_deploy/
menubar: docs_menu
accent: slate
eyebrow: "Deployment Reference"
description: "Use the Terraform deployer when your environment standardizes on Terraform state and you want to keep Simple Chat in the repo's container-based runtime model."
hero_icons:
  - bi-boxes
  - bi-box-seam
  - bi-tag
hero_pills:
  - Terraform-managed infrastructure
  - Container image first
  - Native Python only if you switch models
hero_links:
  - label: "Deployment reference"
    url: /reference/deploy/
    style: primary
  - label: "Upgrade paths"
    url: /how-to/upgrade_paths/
    style: secondary
nav_links:
  prev:
    title: "Bicep Deployment"
    url: /reference/deploy/bicep_deploy/
  next:
    title: "Manual Deployment Notes"
    url: /reference/deploy/manual_deploy/
show_nav: true
---

Use Terraform when state-managed infrastructure is already your team standard and you are comfortable separating image publication from infrastructure application.

<section class="latest-release-card-grid">
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-diagram-2"></i></div>
				<h2>State-managed infra</h2>
				<p>Choose this path when Terraform workflows, reviews, and state handling are already part of how your platform team works.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-box-seam"></i></div>
				<h2>Container runtime by default</h2>
				<p>The current deployer targets a container-based Azure Linux Web App, so the application runtime still follows the Docker image entrypoint.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-tag"></i></div>
				<h2>Publish the image first</h2>
				<p>Terraform does not build the application image for you. Publish to ACR first, then point the deployment at the tag you intend to run.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-arrow-left-right"></i></div>
				<h2>Know when the rule changes</h2>
				<p>If you ever move Terraform away from containers and into native Python App Service, the startup-command rules change with it.</p>
		</article>
</section>

<div class="latest-release-note-panel">
		<h2>Terraform is not the image build step</h2>
		<p>The most common mistake with this path is assuming Terraform also handles the application image lifecycle. It does not. Treat image publication and infrastructure application as two separate steps in the release flow.</p>
</div>

## When to choose this path

- Your team standardizes on Terraform state and workflows
- You want Terraform-managed infrastructure rather than `azd` orchestration
- You are comfortable publishing the application image before applying infrastructure

## Runtime model

The current Terraform deployer in this repo provisions a **container-based Azure Linux Web App**.

## Current behavior

- Terraform sets the App Service to run the published container image.
- Gunicorn startup is already handled by the container entrypoint in `application/single_app/Dockerfile`.
- You do **not** need to configure App Service Stack Settings Startup command for the current Terraform deployment.

## If you switch Terraform to native Python later

If you change the Terraform deployment model away from containers and into native Python App Service, deploy the `application/single_app` folder and use this Startup command:

```bash
python -m gunicorn -c gunicorn.conf.py app:app
```

## References

- [Setup Instructions](../../setup_instructions.md)
- [Upgrade Paths](../../how-to/upgrade_paths.md)
- [Terraform deployer README](https://github.com/microsoft/simplechat/blob/main/deployers/terraform/ReadMe.md)
