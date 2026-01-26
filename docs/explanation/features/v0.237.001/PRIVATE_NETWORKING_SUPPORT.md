# Private Networking Support

## Overview

Comprehensive private networking support for SimpleChat deployments via Azure Developer CLI (AZD) and Bicep infrastructure-as-code. This feature enables secure, isolated deployments with private endpoints, virtual networks, and private DNS zones.

**Version Implemented:** v0.237.001

## Key Features

- **Private Endpoint Support**: All Azure PaaS services can be configured with private endpoints
- **Virtual Network Integration**: Full VNet integration for App Service and dependent resources
- **Private DNS Zones**: Automated DNS zone configuration for private endpoint resolution
- **AZD Integration**: Seamless deployment via `azd up` with private networking enabled
- **Bicep Automation**: Infrastructure-as-code templates for reproducible deployments
- **Post-Deployment Security**: Automatic disabling of public network access when private networking is enabled

## Architecture

### Network Topology

```
┌─────────────────────────────────────────────────────────────────┐
│                        Virtual Network                           │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │   App Service   │  │  Private DNS    │  │   Private       │  │
│  │   Subnet        │  │  Zones          │  │   Endpoints     │  │
│  │                 │  │                 │  │   Subnet        │  │
│  │  ┌───────────┐  │  │  - Cosmos DB    │  │                 │  │
│  │  │SimpleChat │  │  │  - OpenAI       │  │  ┌───────────┐  │  │
│  │  │  App      │──────│  - AI Search   │──────│ Cosmos DB │  │  │
│  │  └───────────┘  │  │  - Storage      │  │  └───────────┘  │  │
│  │                 │  │  - Key Vault    │  │                 │  │
│  └─────────────────┘  └─────────────────┘  │  ┌───────────┐  │  │
│                                             │  │ Azure     │  │  │
│                                             │  │ OpenAI    │  │  │
│                                             │  └───────────┘  │  │
│                                             │                 │  │
│                                             │  ┌───────────┐  │  │
│                                             │  │ AI Search │  │  │
│                                             │  └───────────┘  │  │
│                                             └─────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Supported Private Endpoints

| Service | Private DNS Zone |
|---------|-----------------|
| Azure Cosmos DB | `privatelink.documents.azure.com` |
| Azure OpenAI | `privatelink.openai.azure.com` |
| Azure AI Search | `privatelink.search.windows.net` |
| Azure Blob Storage | `privatelink.blob.core.windows.net` |
| Azure Key Vault | `privatelink.vaultcore.azure.net` |
| Azure Document Intelligence | `privatelink.cognitiveservices.azure.com` |

## Deployment

### Prerequisites

1. **Azure Subscription** with appropriate permissions
2. **Azure Developer CLI (AZD)** installed
3. **Azure CLI** installed and authenticated
4. **Permissions**: Contributor or higher on the subscription/resource group

### AZD Deployment

```bash
# Clone the repository
git clone https://github.com/microsoft/simplechat.git
cd simplechat/deployers

# Initialize AZD (first time)
azd init

# Enable private networking
azd env set ENABLE_PRIVATE_NETWORKING true

# Deploy with private networking
azd up
```

### Bicep Deployment

```bash
# Deploy with private networking parameter
az deployment sub create \
  --location eastus \
  --template-file main.bicep \
  --parameters enablePrivateNetworking=true
```

## Configuration Options

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ENABLE_PRIVATE_NETWORKING` | Enable private endpoints for all services | `false` |
| `VNET_ADDRESS_SPACE` | Virtual network address space | `10.0.0.0/16` |
| `APP_SUBNET_PREFIX` | App Service subnet prefix | `10.0.1.0/24` |
| `PRIVATE_ENDPOINT_SUBNET_PREFIX` | Private endpoints subnet prefix | `10.0.2.0/24` |

## Deployment Hooks

### Post-Provision Hook
- Creates private DNS zones
- Configures private endpoints
- Sets up VNet integration

### Pre-Deploy Hook
- Validates network configuration
- Ensures DNS resolution is working

### Post-Up Hook
- **NEW**: Automatically disables public network access for resources when private networking is enabled
- Validates connectivity through private endpoints
- Outputs connection validation results

## Azure Government Considerations

### Regional Availability
- Private endpoints available in all USGov regions
- Some services may have regional restrictions

### Model Configuration
- Azure OpenAI models may differ in government regions
- Configure model overrides as needed

### Service Limitations
- Some preview features may not be available
- Check Azure Government documentation for current status

## Error Handling

The deployment scripts include:
- **Stepwise logging**: Detailed output for each deployment phase
- **Explicit error handling**: Failures caught early with clear messages
- **Troubleshooting guidance**: Helpful error messages for common issues

## Post-Deployment Validation

After deployment, validate:

1. **DNS Resolution**: Private DNS zones resolve correctly
2. **Network Connectivity**: App Service can reach all services via private endpoints
3. **AI Model Connections**: Test chat functionality
4. **Search Integration**: Verify AI Search connectivity
5. **Document Processing**: Test Document Intelligence

## Security Benefits

1. **No Public Exposure**: Services not accessible from public internet
2. **Network Isolation**: All traffic stays within Azure backbone
3. **Reduced Attack Surface**: Minimized exposure to external threats
4. **Compliance**: Meets enterprise security requirements
5. **Data Protection**: Data never traverses public networks

## Known Issues and Workarounds

1. **DNS Propagation Delay**: Allow 5-10 minutes for DNS changes to propagate
2. **VNet Peering**: Additional configuration needed if peering with existing VNets
3. **On-Premises Connectivity**: Requires ExpressRoute or VPN Gateway for hybrid scenarios

## Files Modified

### Deployment Files
- `deployers/azure.yaml` - Enhanced hooks with logging and error handling
- `deployers/bicep/*.bicep` - Private networking Bicep templates

### Documentation
- `deployers/bicep/README.md` - Enhanced prerequisites and USGov guidance
- `OneClickDeploy.md` - Corrected deployment button links

## Related Documentation

- [Azure Private Endpoints Documentation](https://docs.microsoft.com/azure/private-link/private-endpoint-overview)
- [App Service VNet Integration](https://docs.microsoft.com/azure/app-service/web-sites-integrate-with-vnet)
- [Private DNS Zones](https://docs.microsoft.com/azure/dns/private-dns-overview)
