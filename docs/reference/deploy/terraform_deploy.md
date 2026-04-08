---
layout: page
title: "Terraform Deployment"
description: "Use the Terraform deployer for state-managed infrastructure"
section: "Reference"
---

# Terraform Deployment

Use this path when Terraform is the standard infrastructure workflow in your environment and you want the repo's container-based App Service deployment model.

## When to Choose This Path

- Your team standardizes on Terraform state and workflows
- You want Terraform-managed infrastructure rather than `azd` orchestration
- You are comfortable publishing the application image before applying infrastructure

## Runtime Model

The current Terraform deployer in this repo provisions a **container-based Azure Linux Web App**.

## Current Behavior

- Terraform sets the App Service to run the published container image.
- Gunicorn startup is already handled by the container entrypoint in `application/single_app/Dockerfile`.
- You do **not** need to configure App Service Stack Settings Startup command for the current Terraform deployment.

## Important Note

Terraform does not build the application image for you. Publish the image to Azure Container Registry first, then point Terraform at the image tag you want App Service to run.

## If You Switch Terraform to Native Python Later

If you change the Terraform deployment model away from containers and into native Python App Service, deploy the `application/single_app` folder and use this Startup command:

```bash
python -m gunicorn -c gunicorn.conf.py app:app
```

## References

- [Setup Instructions](../../setup_instructions.md)
- [Upgrade Paths](../../how-to/upgrade_paths.md)
- [Terraform deployer README](https://github.com/microsoft/simplechat/blob/main/deployers/terraform/ReadMe.md)
