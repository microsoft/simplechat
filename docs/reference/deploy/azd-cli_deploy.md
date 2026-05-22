---
layout: showcase-page
title: "Azure Developer CLI Deployment"
permalink: /reference/deploy/azd-cli_deploy/
menubar: docs_menu
accent: emerald
eyebrow: "Deployment Reference"
description: "Deploy Simple Chat with Azure Developer CLI when you want the repo's most current, end-to-end supported rollout path."
hero_icons:
  - bi-rocket-takeoff
  - bi-cloud-arrow-up
  - bi-box-seam
hero_pills:
  - Recommended deployment path
  - Provision and deploy together
  - Container-based runtime
hero_links:
  - label: "Getting Started"
    url: /setup_instructions/
    style: primary
  - label: "Upgrade paths"
    url: /how-to/upgrade_paths/
    style: secondary
nav_links:
  prev:
    title: "Deployment Reference"
    url: /reference/deploy/
  next:
    title: "Azure CLI with PowerShell"
    url: /reference/deploy/azurecli_powershell_deploy/
show_nav: true
---

Azure Developer CLI handles the cleanest end-to-end deployment flow in this repo. Use it when you want infrastructure provisioning, environment configuration, and application deployment to stay in one documented path.

<section class="latest-release-card-grid">
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-diagram-3"></i></div>
        <h2>Provision infrastructure</h2>
        <p>AZD drives the Bicep templates for the required Azure resources instead of making you stitch together the provisioning steps manually.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-sliders2"></i></div>
        <h2>Capture environment choices</h2>
        <p>Subscription, region, environment naming, and optional environment settings all stay tied to the AZD environment instead of scattered across ad hoc scripts.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-box-seam"></i></div>
        <h2>Deploy the app</h2>
        <p>The current path is container-based App Service, so the image runtime and startup behavior are handled by the deployment model rather than a native Python startup command.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-graph-up-arrow"></i></div>
        <h2>Inspect and iterate</h2>
        <p>Use AZD commands for logs, monitoring, environment inspection, and upgrade decisions without switching to a separate deployment toolset midstream.</p>
    </article>
</section>

<div class="latest-release-note-panel">
    <h2>Startup command rule for this path</h2>
    <p>The repo's AZD workflow deploys a container-based App Service. Do not add a native Python App Service startup command unless you intentionally move away from the container runtime later.</p>
</div>

## Overview

**Azure Developer CLI** is Microsoft's tool for streamlined application deployment to Azure. For Simple Chat, azd:
- Provisions all required Azure resources
- Configures service connections
- Deploys the application code
- Sets up monitoring and logging

This is the primary recommended deployment path for the repo.

## Prerequisites

### Required Software
- **Azure Developer CLI** ([install guide](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/install-azd))
- **Python 3.12** ([download](https://www.python.org/downloads/)) with `python` available on Windows and `python3` available on Linux/macOS. The `deployers/azure.yaml` `preprovision` and `postprovision` hooks call Python for prerequisite validation, dependency installation, and post-provision configuration.
- **Git** for repository cloning
- **Azure CLI** (usually installed with azd)

### Azure Requirements
- **Azure subscription** with contributor access
- **Resource quota** for required services in target region
- **Permissions** to create service principals (if not using existing)

### Supported Environments
- ✅ **Azure Commercial** 
- ✅ **Azure Government** (with environment configuration)
- ✅ **Local development** environments
- ✅ **CI/CD pipelines**

## Quick Start

## Runtime Startup Behavior

- The current `azd` deployment path in this repo is a **container-based App Service** deployment.
- Gunicorn is started by the container entrypoint in `application/single_app/Dockerfile`.
- You do **not** need to populate App Service Stack Settings Startup command when deploying through this `azd` path.
- If you later switch to native Python App Service instead, deploy the `application/single_app` folder and use this startup command:

```bash
python -m gunicorn -c gunicorn.conf.py app:app
```

### 1. Clone Repository
```bash
git clone https://github.com/microsoft/simplechat.git
cd simplechat
```

### 2. Initialize and Deploy
```bash
# Initialize the project
azd init

# Deploy to Azure
azd up
```

### 3. Follow Prompts
The `azd up` command will prompt for:
- **Subscription selection**
- **Target region**
- **Environment name** (used for resource naming)
- **Additional configuration options**

## Detailed Deployment Steps

### Step 1: Environment Setup

**Initialize project:**
```bash
azd init
```

**Select template** (if prompted):
- Choose "Simple Chat" from available templates
- Or use the current directory if already cloned

### Step 2: Configuration

**Set environment variables** (optional):
```bash
# For Azure Government
azd env set AZURE_ENVIRONMENT usgovernment

# For custom regions
azd env set AZURE_LOCATION "East US 2"

# For specific naming prefix
azd env set RESOURCE_PREFIX "myorg"
```

**Review configuration:**
```bash
azd env get-values
```

### Step 3: Deploy Resources

**Full deployment:**
```bash
azd up
```

This command:
1. **Provisions infrastructure** using Bicep templates
2. **Configures services** with proper connections
3. **Deploys application code** to App Service
4. **Sets up monitoring** and logging
5. **Outputs connection information**

### Step 4: Verify Deployment

**Check deployment status:**
```bash
azd show
```

**Get application URL:**
```bash
azd env get-values | grep APP_URL
```

**Test application:**
- Open the provided URL in browser
- Verify login functionality
- Test basic chat functionality

## Configuration Options

### Environment Variables

Set these before running `azd up` to customize deployment:

**Core Settings:**
```bash
# Deployment region
azd env set AZURE_LOCATION "East US"

# Resource naming prefix  
azd env set RESOURCE_PREFIX "simplechat"

# Environment type (affects SKUs)
azd env set ENVIRONMENT_TYPE "dev|staging|prod"
```

**Service Configuration:**

The AZD path uses the Bicep defaults: App Service P1v3, Azure AI Search Standard S1 with standard Semantic Ranker, and Cosmos DB provisioned shared autoscale throughput for the `SimpleChat` database. Free Search and serverless Cosmos DB are available only as explicit Bicep parameter customizations for short-lived MVP or evaluation phases.

**Azure Government:**
```bash
azd env set AZURE_ENVIRONMENT "usgovernment"
azd env set AZURE_LOCATION "USGov Virginia"
```

### Resource Sizing

**Development/Testing:**
Use the default Bicep sizing unless you are intentionally running a short-lived MVP. The default uses provisioned Cosmos DB and Azure AI Search Standard S1 so workspace search can use standard Semantic Ranker capacity.

**Production:**  
The default AZD/Bicep path is the production-leaning baseline: P1v3 App Service, Cosmos DB provisioned shared autoscale throughput, and Azure AI Search Standard S1.

**Custom Sizing:**
Customize Bicep parameters such as `cosmosDatabaseAutoscaleMaxThroughput`, `searchSkuName`, and `searchSemanticSearchSku` only when your cost, quota, or scale model requires it.

## Post-Deployment Configuration

### Access Admin Settings

1. **Navigate to deployed application**
2. **Sign in** with Azure AD account
3. **Assign admin role** if needed:
   ```bash
   # Get app registration details
   azd env get-values | grep APP_REGISTRATION
   
   # Assign admin role in Azure AD
   ```

### Configure Application Features

**Required configurations:**
- Test all service connections in Admin Settings
- Configure default system prompt
- Set up document classification (optional)
- Enable additional features as needed

**Recommended configurations:**
- Set up Content Safety thresholds
- Configure file size limits
- Set conversation history limits
- Enable enhanced citations

### Set Up Monitoring

**Application Insights:**
- Automatically configured by azd
- Access through Azure Portal
- Set up custom alerts and dashboards

**Azure Monitor:**
- Configure alerts for resource health
- Set up cost monitoring and budgets
- Create dashboards for operational metrics

## Advanced Configuration

### Custom Bicep Parameters

**Modify infrastructure** by editing `infra/main.parameters.json`:
```json
{
    "parameters": {
        "environmentName": "prod-simple-chat",
        "location": "East US",
        "appServiceSku": "P1v3",
        "cosmosDbThroughput": 1000,
        "searchSku": "standard",
        "enableContentSafety": true,
        "enableRedisCache": true
    }
}
```

### Multi-Environment Deployment

**Development environment:**
```bash
azd env select dev
azd up
```

**Production environment:**
```bash  
azd env select prod
azd env set ENVIRONMENT_TYPE "prod"
azd up
```

### CI/CD Integration

**GitHub Actions workflow:**
{% raw %}
```yaml
- name: Azure Dev CLI Deploy
  uses: Azure/azure-dev-cli@v1
  with:
    azure-credentials: ${{ secrets.AZURE_CREDENTIALS }}
  run: |
    azd auth login --client-id "${{ secrets.AZURE_CLIENT_ID }}" \
                   --client-secret "${{ secrets.AZURE_CLIENT_SECRET }}" \
                   --tenant-id "${{ secrets.AZURE_TENANT_ID }}"
    azd deploy
```
{% endraw %}

## Management Commands

### Upgrade Decision Guide

Use the command that matches the type of change you are making.

| If you changed... | Use | Why |
| :--- | :--- | :--- |
| **Application code only** | `azd deploy` | Recommended default for routine container upgrades |
| **Infrastructure only** | `azd provision` | Updates Azure resources without treating the release like a full app deployment |
| **Application code and infrastructure together** | `azd up` | Runs the combined deployment flow |

Do **not** assume `azd up` is required for every release. For normal code-only container updates, start with `azd deploy`.

### Application Lifecycle

**Deploy application updates:**
```bash
azd deploy
```

Recommended for routine container-based application upgrades when infrastructure is unchanged.

**Provision infrastructure changes:**
```bash
azd provision
```

Use `azd provision --preview` first when you want to review infrastructure impact before applying it.

**Full redeployment:**
```bash  
azd down --purge
azd up
```

Do not use this as a standard upgrade flow. This is a destructive reprovisioning path.

### Environment Management

**List environments:**
```bash
azd env list
```

**Switch environments:**
```bash
azd env select <environment-name>
```

**View configuration:**
```bash
azd env get-values
```

### Monitoring and Logs

**Show deployment info:**
```bash
azd show
```

**Monitor application:**
```bash
azd monitor
```

**View logs:**
```bash
# Application logs
azd logs

# Infrastructure logs  
azd logs --infrastructure
```

## Troubleshooting

### Common Issues

**Authentication failures:**
```bash
# Re-authenticate
azd auth login

# Check subscription access
az account show
```

**Resource quota issues:**
```bash
# Check quotas in target region
az vm list-usage --location "East US" --output table

# Try different region
azd env set AZURE_LOCATION "West US 2"
```

**Deployment failures:**
```bash
# Check deployment logs
azd show --output json

# View detailed logs
azd logs --infrastructure
```

### Service-Specific Issues

**Azure OpenAI not available:**
- Verify Azure OpenAI is available in target region
- Check subscription whitelist status
- Request access through Azure portal

**App Service deployment issues:**
- Check App Service logs in Azure portal
- Verify application settings configuration
- Check for startup errors in Application Insights

**Cosmos DB connection issues:**
- Verify firewall settings allow App Service
- Check connection string configuration
- Test connectivity from App Service console

### Recovery Procedures

**Rollback deployment:**
```bash
# Get previous deployment
azd show --output json

# Redeploy specific version
git checkout <previous-version-tag>
azd deploy
```

**Clean slate redeployment:**
```bash
# Remove all resources
azd down --purge

# Redeploy from scratch
azd up
```

## Best Practices

### Pre-Deployment
- ✅ Verify Azure subscription quotas in target region
- ✅ Plan resource naming conventions
- ✅ Review cost estimates for selected SKUs
- ✅ Prepare Azure AD configuration requirements

### During Deployment
- ✅ Monitor deployment progress for errors
- ✅ Note down important URLs and connection strings
- ✅ Verify each service comes online successfully
- ✅ Document any custom configurations applied

### Post-Deployment
- ✅ Test all application functionality end-to-end
- ✅ Configure monitoring and alerting
- ✅ Set up backup procedures for critical data
- ✅ Document operational procedures for team

### Security
- ✅ Review and configure Azure AD app registration
- ✅ Set up proper RBAC roles for users
- ✅ Enable managed identities where possible
- ✅ Configure network security if required

## Cost Optimization

### Right-Sizing Resources

**Monitor and adjust:**
- Review cost reports after 30 days of usage
- Adjust service tiers based on actual utilization  
- Use autoscaling for variable workloads
- Consider reserved instances for predictable usage

**Cost-effective configurations:**
For short-lived MVP or evaluation environments, you can override Bicep parameters to use Free Azure AI Search/Semantic Ranker or Cosmos DB serverless. Those are cost-focused exceptions; the repo defaults remain Standard S1 Search and provisioned Cosmos DB because they avoid common document-search and semantic-quota failures.

This Azure Developer CLI approach provides the fastest path from zero to a fully functional Simple Chat deployment with minimal manual configuration required.
