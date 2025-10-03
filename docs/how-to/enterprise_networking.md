# How to Configure Enterprise Networking

This guide walks you through setting up Simple Chat with enterprise-grade network security using Azure Private Endpoints, Virtual Networks, and Private DNS. This configuration ensures all traffic stays on the Microsoft backbone and never traverses the public internet.

## Overview

Enterprise networking for Simple Chat involves:
- **Private Endpoints**: Secure connections to Azure services
- **Virtual Networks (VNets)**: Isolated network environments  
- **Subnets**: Segmented network spaces for different components
- **Private DNS Zones**: Internal name resolution

### Networking in Azure Commercial

![Architecture with Private Endpoints in Azure Commercial](../images/architecture-private-endpoints-commercial.png)

### Networking in Azure Government

![Architecture with Private Endpoints in Azure Government](../images/architecture-private-endpoints-government.png)

## Prerequisites

- Azure subscription with network administrator permissions
- Simple Chat already deployed (can be reconfigured for private networking)
- Understanding of Azure networking concepts
- Planning for IP address ranges and network topology

## Step 1: Plan Your Network Architecture

### Network Topology Planning

**Decide on VNet structure:**
```
Production VNet (10.0.0.0/16):
├── App Service Subnet (10.0.1.0/24)
├── Private Endpoint Subnet (10.0.2.0/24)  
├── Database Subnet (10.0.3.0/24)
└── Management Subnet (10.0.4.0/24)
```

**Consider connectivity requirements:**
- On-premises connectivity (ExpressRoute/VPN)
- Multi-region deployment needs
- Integration with existing networks
- Compliance and security requirements

### Service Endpoint Requirements

**Services requiring Private Endpoints:**
- Azure App Service (inbound)
- Azure OpenAI
- Azure Cosmos DB
- Azure AI Search
- Azure Storage (for Enhanced Citations)
- Azure Document Intelligence
- Azure Content Safety
- Azure Speech Services (if used)

## Step 2: Create Virtual Network Infrastructure

### Create Main VNet

1. **Go to Azure Portal** → **Create a resource** → **Virtual Network**
2. **Configure basic settings:**
   ```
   Name: simplechat-prod-vnet
   Region: Your deployment region
   Resource Group: Your Simple Chat resource group
   ```

3. **Configure IP addresses:**
   ```
   IPv4 address space: 10.0.0.0/16
   ```

4. **Create subnets:**
   ```
   Subnet 1:
   Name: app-service-subnet  
   Address range: 10.0.1.0/24
   
   Subnet 2:
   Name: private-endpoint-subnet
   Address range: 10.0.2.0/24
   
   Subnet 3:  
   Name: database-subnet
   Address range: 10.0.3.0/24
   ```

### Configure Subnet Delegation

**For App Service integration:**
1. **Select app-service-subnet**
2. **Configure delegation:**
   - Delegate subnet to: `Microsoft.Web/serverFarms`
   - This allows App Service to integrate with the subnet

### Network Security Groups (NSGs)

**Create NSGs for each subnet:**

**App Service NSG rules:**
```
Inbound Rules:
- Allow HTTPS (443) from Internet
- Allow HTTP (80) from Internet (redirect to HTTPS)  
- Deny all other inbound

Outbound Rules:
- Allow HTTPS (443) to Private Endpoint subnet
- Allow DNS (53) to Azure DNS
- Deny Internet access (force through Private Endpoints)
```

**Private Endpoint NSG rules:**  
```
Inbound Rules:
- Allow traffic from App Service subnet
- Deny all other inbound

Outbound Rules:
- Allow as needed for service communication
```

## Step 3: Configure App Service VNet Integration

### Enable VNet Integration

1. **Go to your App Service** → **Settings** → **Networking**
2. **Click "VNet integration"**
3. **Select "Add VNet integration"**
4. **Configure:**
   ```
   Virtual Network: simplechat-prod-vnet
   Subnet: app-service-subnet
   ```

### Configure Route All Traffic

**Enable route all traffic through VNet:**
1. **In VNet integration settings**
2. **Enable "Route All"** 
3. This forces all outbound traffic through the VNet

### Test VNet Integration

**Verify integration:**
1. **Go to App Service** → **Advanced Tools** → **Kudu**
2. **Open Debug console** 
3. **Test name resolution:**
   ```bash
   nslookup your-cosmosdb-account.documents.azure.com
   # Should resolve to private IP (10.x.x.x)
   ```

## Step 4: Create Private Endpoints

Create Private Endpoints for each Azure service Simple Chat uses.

### Azure Cosmos DB Private Endpoint

1. **Go to Cosmos DB account** → **Settings** → **Private endpoint connections**
2. **Click "+ Private endpoint"**
3. **Configure:**
   ```
   Name: simplechat-cosmos-pe
   Region: Same as VNet
   Virtual Network: simplechat-prod-vnet
   Subnet: private-endpoint-subnet
   Target sub-resource: SQL
   ```
4. **Configure DNS:**
   ```
   Integrate with private DNS zone: Yes
   Private DNS Zone: privatelink.documents.azure.com
   ```

### Azure OpenAI Private Endpoint

1. **Go to OpenAI resource** → **Networking** → **Private endpoint connections**
2. **Create endpoint:**
   ```
   Name: simplechat-openai-pe
   Target sub-resource: account
   Private DNS Zone: privatelink.openai.azure.com
   ```

### Azure AI Search Private Endpoint  

1. **Go to Search service** → **Settings** → **Private endpoint connections**
2. **Create endpoint:**
   ```
   Name: simplechat-search-pe
   Target sub-resource: searchService  
   Private DNS Zone: privatelink.search.windows.net
   ```

### Storage Account Private Endpoint

1. **Go to Storage Account** → **Security + networking** → **Private endpoint connections**
2. **Create endpoint:**
   ```
   Name: simplechat-storage-pe
   Target sub-resource: blob
   Private DNS Zone: privatelink.blob.core.windows.net
   ```

### Document Intelligence Private Endpoint

1. **Go to Document Intelligence** → **Networking** → **Private endpoint connections**  
2. **Create endpoint:**
   ```
   Name: simplechat-doc-intel-pe
   Target sub-resource: account
   Private DNS Zone: privatelink.cognitiveservices.azure.com
   ```

## Step 5: Configure Private DNS

### Verify DNS Zone Creation

Private DNS zones should be created automatically with Private Endpoints:
- `privatelink.documents.azure.com`
- `privatelink.openai.azure.com`  
- `privatelink.search.windows.net`
- `privatelink.blob.core.windows.net`
- `privatelink.cognitiveservices.azure.com`

### Link DNS Zones to VNet

**For each Private DNS zone:**
1. **Go to Private DNS zone**
2. **Settings** → **Virtual network links**
3. **Add link:**
   ```
   Link name: simplechat-vnet-link
   Virtual network: simplechat-prod-vnet
   Enable auto registration: No (for Private Endpoint zones)
   ```

### Test DNS Resolution

**From App Service Kudu console:**
```bash
# Test each service resolves to private IP
nslookup your-cosmos-account.documents.azure.com
nslookout your-openai-account.openai.azure.com  
nslookup your-search-service.search.windows.net
```

**Expected results:**
- All should resolve to 10.0.2.x addresses (Private Endpoint subnet)
- No public IP addresses should be returned

## Step 6: Secure Service Access

### Disable Public Access

**For each Azure service:**

**Cosmos DB:**
1. **Settings** → **Firewall and virtual networks**
2. **Select "Deny all networks"** 
3. **Ensure Private Endpoint access is allowed**

**Azure OpenAI:**
1. **Networking** → **Firewalls and virtual networks**
2. **Selected networks and private endpoints**
3. **Remove any public IP allowlists**

**AI Search:**
1. **Settings** → **Networking**
2. **Private access** → **All networks disabled**
3. **Verify Private Endpoint access only**

**Storage Account:**
1. **Security + networking** → **Firewalls and virtual networks**
2. **Selected networks**
3. **Clear all public network access**

### Configure Service-Specific Settings

**Cosmos DB additional settings:**
```
Connection Policy: Gateway mode (recommended for Private Endpoints)
Firewall: Disabled for public networks  
Private Endpoint: Enabled
```

**Azure OpenAI additional settings:**
```  
Network access: Private endpoint and selected networks
Custom subdomain: Required for Private Endpoints
Managed Identity: Recommended for authentication
```

## Step 7: Update Application Configuration

### Endpoint URLs

**Verify application uses correct endpoints:**

**In Admin Settings, confirm endpoints use private connectivity:**
```
Azure OpenAI: https://your-account.openai.azure.com/
Cosmos DB: Endpoint should connect via private network
AI Search: https://your-service.search.windows.net/
```

### Connection Testing

**Test each service connection:**
1. **Go to Admin Settings**
2. **Test each service connection**
3. **Verify successful private connectivity**
4. **Check application logs for any public endpoint attempts**

### Monitor Network Traffic

**Enable network monitoring:**
1. **Configure Network Watcher** for the VNet
2. **Enable Flow logs** on NSGs
3. **Set up monitoring** for unusual traffic patterns

## Step 8: Configure Additional Security

### Application Gateway (Optional)

For additional security and routing:

1. **Deploy Application Gateway** in dedicated subnet
2. **Configure Web Application Firewall (WAF)**
3. **Route traffic:** Internet → App Gateway → App Service
4. **Enable SSL termination**

### ExpressRoute/VPN Integration

**For on-premises connectivity:**

1. **Configure ExpressRoute** or **Site-to-Site VPN**
2. **Update route tables** for proper routing
3. **Configure BGP** for dynamic routing (ExpressRoute)
4. **Test connectivity** from on-premises

### Azure Bastion (Management)

**For secure VM management:**
1. **Deploy Azure Bastion** in dedicated subnet
2. **Configure management VM** in management subnet  
3. **Use Bastion** for secure administrative access

## Step 9: Monitoring and Troubleshooting

### Network Monitoring Setup

**Configure monitoring:**
1. **Network Watcher** → **Connection Monitor**
2. **Monitor connectivity** between App Service and services
3. **Set up alerts** for connectivity failures
4. **Configure topology monitoring**

### Application Insights Network Dependency

**Monitor application dependencies:**
1. **Enable Application Insights** network dependency tracking
2. **Monitor Private Endpoint connectivity**  
3. **Set up alerts** for dependency failures
4. **Track performance** across private connections

### Common Troubleshooting

**DNS Resolution Issues:**
```
Problem: Services resolving to public IPs
Solution: 
- Check Private DNS zone configuration
- Verify VNet links are active
- Restart App Service to refresh DNS cache
```

**Connectivity Issues:**
```
Problem: Connection timeouts or failures  
Solution:
- Check NSG rules allow required traffic
- Verify Private Endpoints are approved 
- Test network connectivity with tcpping
- Review firewall settings on services
```

**Performance Issues:**
```
Problem: Slower response times with Private Endpoints
Solution:
- Verify optimal routing configuration
- Check for network latency between subnets  
- Monitor bandwidth utilization
- Consider Express Route for better performance
```

## Security Best Practices

### Network Segmentation
- ✅ Use separate subnets for different tiers
- ✅ Apply principle of least privilege with NSGs
- ✅ Regularly review and update security rules
- ✅ Monitor for unauthorized network access

### DNS Security
- ✅ Use Private DNS zones for all private services
- ✅ Prevent DNS leakage to public resolvers  
- ✅ Monitor DNS queries for suspicious activity
- ✅ Implement DNS filtering where appropriate

### Monitoring and Alerting
- ✅ Enable comprehensive network monitoring
- ✅ Set up alerts for connectivity issues
- ✅ Regular security assessments of network configuration
- ✅ Document network architecture and changes

## Compliance Considerations

### Data Residency
- All traffic stays within Azure backbone
- No data traverses public internet
- Regional data boundaries maintained
- Audit trail of network access

### Regulatory Requirements  
- Meets most compliance frameworks (FedRAMP, SOC 2, etc.)
- Supports data sovereignty requirements
- Enables network-level audit logging
- Facilitates compliance reporting

## Deployment Checklist

**Pre-deployment:**
- [ ] Plan IP address ranges and avoid conflicts
- [ ] Design network topology and subnet structure  
- [ ] Review compliance and security requirements
- [ ] Prepare rollback plan for network changes

**Deployment:**
- [ ] Create VNet and subnets with appropriate sizing
- [ ] Configure NSGs with security rules
- [ ] Enable App Service VNet integration
- [ ] Create Private Endpoints for all services
- [ ] Configure Private DNS zones and VNet links
- [ ] Disable public access on all services
- [ ] Test connectivity and DNS resolution

**Post-deployment:**
- [ ] Verify all services accessible via private network
- [ ] Test application functionality end-to-end
- [ ] Configure monitoring and alerting
- [ ] Document network configuration
- [ ] Train operations team on troubleshooting

This enterprise networking setup provides the foundation for a secure, compliant Simple Chat deployment that meets the strictest enterprise security requirements.
