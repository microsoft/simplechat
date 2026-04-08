---
layout: page
title: "Bicep Deployment"
description: "How the repo's Bicep templates fit into the supported deployment paths"
section: "Reference"
---

# Bicep Deployment

The repo's Bicep templates are the infrastructure foundation behind the primary `azd up` deployment flow.

For most teams, the best-supported Bicep experience is to use the [Azure Developer CLI deployment guide](./azd-cli_deploy.md) and let `azd` orchestrate packaging, provisioning, and deployment.

## When to Choose This Path

- You want to inspect or customize the Bicep templates in `deployers/bicep/`
- You want to understand the infrastructure used by the `azd` deployment flow
- You are troubleshooting infrastructure behavior or preparing Bicep module changes

## Recommended Workflow

1. Start with the [Azure Developer CLI deployment guide](./azd-cli_deploy.md).
2. Review or modify the Bicep files under `deployers/bicep/`.
3. Use `azd provision --preview` or `azd up` to apply those changes through the supported workflow.

## Runtime Model

- The repo's Bicep-based deployment path is container-based Azure App Service.
- Gunicorn is started by the container entrypoint in `application/single_app/Dockerfile`.
- Do not add a native Python App Service startup command unless you intentionally switch away from containers.

## References

- [Setup Instructions](../../setup_instructions.md)
- [Special Deployment Scenarios](../../setup_instructions_special.md)
- [Enterprise Networking](../../how-to/enterprise_networking.md)
- [Bicep deployer README](https://github.com/microsoft/simplechat/blob/main/deployers/bicep/README.md)
