# Azure Developer CLI Deployment

Azure Developer CLI (azd) provides the fastest and most automated way to deploy Simple Chat. This method handles resource provisioning, configuration, and application deployment with minimal manual steps.

## Overview

**Azure Developer CLI** is Microsoft's tool for streamlined application deployment to Azure. For Simple Chat, azd:
- Provisions all required Azure resources
- Configures service connections
- Deploys the application code
- Sets up monitoring and logging

## Prerequisites

### Required Software
- **Azure Developer CLI** ([install guide](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/install-azd))
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
```bash
# Enable specific features
azd env set ENABLE_CONTENT_SAFETY "true"
azd env set ENABLE_IMAGE_GENERATION "true"
azd env set ENABLE_REDIS_CACHE "true"

# Set service tiers
azd env set APP_SERVICE_SKU "P1v3"
azd env set COSMOS_DB_THROUGHPUT "1000"
azd env set SEARCH_SKU "standard"
```

**Azure Government:**
```bash
azd env set AZURE_ENVIRONMENT "usgovernment"
azd env set AZURE_LOCATION "USGov Virginia"
```

### Resource Sizing

**Development/Testing:**
```bash
azd env set ENVIRONMENT_TYPE "dev"
# Uses: B1 App Service, 400 RU/s Cosmos, Basic Search
```

**Production:**  
```bash
azd env set ENVIRONMENT_TYPE "prod"
# Uses: P1v3 App Service, 1000 RU/s Cosmos, Standard Search
```

**Custom Sizing:**
```bash
azd env set APP_SERVICE_SKU "P2v3"
azd env set COSMOS_DB_THROUGHPUT "4000" 
azd env set SEARCH_SKU "standard2"
azd env set OPENAI_SKU "S0"
```

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

## Management Commands

### Application Lifecycle

**Deploy application updates:**
```bash
azd deploy
```

**Provision infrastructure changes:**
```bash
azd provision
```

**Full redeployment:**
```bash  
azd down --purge
azd up
```

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
```bash
# Development environments
azd env set APP_SERVICE_SKU "B1"
azd env set COSMOS_DB_THROUGHPUT "400"
azd env set SEARCH_SKU "basic"

# Production with cost optimization
azd env set ENABLE_REDIS_CACHE "false"  # Start without Redis
azd env set COSMOS_DB_AUTOSCALE "true"  # Use autoscale for variable load
```

This Azure Developer CLI approach provides the fastest path from zero to a fully functional Simple Chat deployment with minimal manual configuration required.
