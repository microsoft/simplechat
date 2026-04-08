---
layout: page
title: "Azure CLI with PowerShell Deployment"
description: "Use the script-driven Azure CLI + PowerShell deployer"
section: "Reference"
---

# Azure CLI with PowerShell Deployment

This deployer provisions Simple Chat with Azure CLI and PowerShell orchestration.

Use it when you want a script-driven deployment flow without `azd`, or when you want more direct control over sequencing and recovery steps than the default `azd` workflow provides.

## When to Choose This Path

- You want a script-driven deployment flow without `azd`
- You want more direct control over sequencing and recovery steps
- You still want the repo's container-based App Service deployment model

## Runtime Model

- This deployer creates a container-based Azure App Service deployment.
- Gunicorn is started by the container entrypoint in `application/single_app/Dockerfile`.
- Do not add a native Python App Service startup command for this path.

## Main Files

- `deployers/azurecli/deploy-simplechat.ps1`
- `deployers/azurecli/destroy-simplechat.ps1`

## Quick Start

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