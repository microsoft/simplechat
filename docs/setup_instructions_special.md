# Simple Chat - Special Setup Instructions 

- [Azure Government Configuration](#azure-government-configuration)
- [How to use Managed Identity](#how-to-use-managed-identity)
- [Enterprise Networking](#enterprise-networking)

- [Return to Main](../README.md)


## Azure Government Configuration

> <a href="#simple-chat---special-setup-instructions" style="text-decoration: none;">Return to top</a>

To run the application in Azure Government cloud:

1. **Deploy Resources**: Provision all necessary Azure resources (App Service, OpenAI, Cosmos DB, etc.) within your Azure Government subscription and appropriate Gov regions.

2. **Update Environment Variable**:

   - In the App Service **Application settings** (or your .env file before uploading), set the AZURE_ENVIRONMENT variable:

     ```
     AZURE_ENVIRONMENT="usgovernment"
     ```

   - This ensures the application uses the correct Azure Government endpoints for authentication (MSAL) and potentially for fetching management plane details when using Managed Identity with direct endpoints.

3. **Endpoint URLs**: Ensure all endpoint URLs configured (in App Settings or via the Admin UI) point to the correct .usgovernment.azure.com (or specific service) domains. Azure OpenAI endpoints in Gov are different from Commercial.

4. **App Registration**: Ensure the App Registration is done within your Azure Government Azure AD tenant. The Redirect URI for the App Service will use the .azurewebsites.us domain.

## How to use Managed Identity

> <a href="#simple-chat---setup-instructions" style="text-decoration: none;">Return to top</a>

Using Managed Identity allows the App Service to authenticate to other Azure resources securely without needing to store secrets (like API keys or connection strings) in Application Settings.

> [!TIP]
>
> **Recap: Managed Identity vs. App Registration**
>
> - **App Service Managed Identity (System-Assigned or User-Assigned)**: An identity automatically managed by Azure, tied to the App Service instance itself. Used for Azure resource-to-resource authentication (e.g., App Service accessing Cosmos DB data plane). **It cannot be used for user login.**
> - **App Registration (Service Principal)**: An identity created manually in Azure AD representing your application. Used for user authentication flows (via App Service Authentication integration) and potentially for application permissions to APIs like Microsoft Graph. It can *also* be used for resource-to-resource authentication (using client secrets/certificates), but Managed Identity is often preferred for Azure resources.
> - **Enterprise Application**: An instance of an App Registration within your tenant, used to manage user assignments, roles, and SSO configuration.

**Steps to Enable Managed Identity Authentication for Supported Services:**

1. **Enable Managed Identity on App Service**:

   - Go to your **App Service** in the Azure Portal.
   - Navigate to **Settings** > **Identity**.
   - Under the **System assigned** tab, switch **Status** to **On**.
   - Click **Save**. Azure creates an identity for your App Service in Azure AD. Note the **Object (principal) ID**.

   ![enable managed identity](./images/enable_managed_identity.png)

2. **Assign Roles to the Managed Identity**:

   - For each Azure service you want the App Service to access using its Managed Identity, you must grant that identity the appropriate role on the target service.
   - Go to the target Azure resource (e.g., Azure OpenAI, Cosmos DB, AI Search, Storage Account, Document Intelligence, Content Safety).
   - Navigate to **Access control (IAM)**.
   - Click **+ Add** > **Add role assignment**.
   - Select the appropriate role from the table below.
   - **Assign access to**: Select **Managed identity**.
   - **Members**: Click **+ Select members**.
   - Choose the **Subscription**, select **App Service** for the Managed identity type, and then find and select the **name of your App Service instance**. Click **Select**.
   - Click **Review + assign**.

   ![add role assignment - job function](./images/add_role_assignment-job_function.png)

   ![add role assignment - managed identity](./images/add_role_assignment-select_member-managed_identity.png)

   **Required Roles for Managed Identity Access:**

   | Target Service        | Required Role                       | Notes                                                        |
   | --------------------- | ----------------------------------- | ------------------------------------------------------------ |
   | Azure OpenAI          | Cognitive Services OpenAI User      | Allows data plane access (generating completions, embeddings, images). |
   | Azure AI Search       | Search Index Data Contributor       | Allows reading/writing data to search indexes.               |
   | Azure Cosmos DB       | Cosmos DB Built-in Data Contributor | Allows reading/writing data. Least privilege possible via custom roles. Key auth might be simpler. |
   | Document Intelligence | Cognitive Services User             | Allows using the DI service for analysis.                    |
   | Content Safety        | Cognitive Services Contributor      | Allows using the CS service for analysis. (Role name might vary slightly, check portal) |
   | Azure Storage Account | Storage Blob Data Contributor       | Required for Enhanced Citations if using Managed Identity. Allows reading/writing blobs. |
   | Azure Speech Service  | Cognitive Services User             | Allows using the Speech service for transcription.           |
   | Video Indexer         | (Handled via VI resource settings)  | VI typically uses its own Managed Identity to access associated Storage/Media Services. Check VI docs. |

3. **Configure Application to Use Managed Identity**:

   - Update the **Application settings** in the App Service (or .env before upload) **OR** use the toggles in the **Admin Settings UI** where available.
   - **Cosmos DB**: Set AZURE_COSMOS_AUTHENTICATION_TYPE="managed_identity" in Application Settings. Remove AZURE_COSMOS_KEY and AZURE_COSMOS_CONNECTION_STRING.
   - **Other Services (OpenAI, Search, DI, CS, Storage)**: Check the **Admin Settings UI** first. Most sections (GPT, Embeddings, Image Gen, Citations, Safety, Search & Extract) have toggles or dropdowns to select "Managed Identity" as the authentication method. Using the UI toggle is preferred as it handles the backend configuration. If UI options aren't present or for overrides, you might need specific environment variables like AZURE_OPENAI_USE_MANAGED_IDENTITY="True", but rely on the UI where possible.

## Enterprise Networking
> <a href="#simple-chat---special-setup-instructions" style="text-decoration: none;">Return to top</a>

![Architecture with Private Endpoints](./images/architecture-private-endpoints.png)

### Private Endpoints, Virtual Networks, Subnets, and Private DNS Zones

For enterprise deployments—whether in Azure Commercial, Azure Government, or custom/sovereign environments—network isolation and private connectivity are critical for security, compliance, and data protection. The Simple Chat reference architecture leverages Azure Private Endpoints, Virtual Networks (VNets), dedicated subnets, and Private DNS Zones to ensure all traffic between the application and Azure services remains on the Microsoft backbone, never traversing the public internet.

#### **Why Use Private Endpoints and Private DNS?**

- **Security & Compliance:** Private Endpoints restrict access to Azure PaaS services (Cosmos DB, AI Search, OpenAI, Storage, Redis, etc.) to only resources within your VNet, preventing data exfiltration and unauthorized access.
- **Data Privacy:** All data-in-transit between the App Service and backend services stays within the Azure backbone, never exposed to the public internet.
- **Zero Trust & Defense-in-Depth:** Network-level controls complement identity and RBAC, supporting regulatory requirements (e.g., FedRAMP, HIPAA, GDPR).
- **Custom DNS Resolution:** Private DNS Zones ensure that service FQDNs (e.g., *.documents.azure.com) resolve to private IPs within your VNet, so all traffic is routed privately.

#### **Network Topology Overview**

The architecture consists of a single VNet with multiple subnets and a set of Private DNS Zones, as shown in the diagram above.

**Subnets:**
- **App Inbound:** Hosts the Private Endpoint for inbound traffic to the App Service (front end). This allows secure, private access from internal users or jump hosts.
- **App Outbound:** Used for VNet Integration, enabling the App Service to make outbound calls to private endpoints of backend services (Cosmos DB, Redis, Storage, etc.).
- **Data:** Hosts Private Endpoints for data services (Cosmos DB, Redis, Storage).
- **AI Services:** Hosts Private Endpoints for AI-related services (OpenAI, AI Search, Document Intelligence, Content Safety, Speech, Video Indexer).

**Key Points:**
- The App Service has **two network connections**:
  - **Private Endpoint (Inbound):** Exposes the app privately for internal access (e.g., from a corporate network or jump box).
  - **VNet Integration (Outbound):** Allows the app to reach private endpoints of backend services via the VNet.
- All backend services are deployed with Private Endpoints in their respective subnets.
- Each service type requires a corresponding Private DNS Zone for name resolution.

#### **Required Private DNS Zones**

For each Azure service with a Private Endpoint, you must create and link the following Private DNS Zones to your VNet:

| Service                | Private DNS Zone Name                        |
|------------------------|----------------------------------------------|
| App Service            | privatelink.azurewebsites.net                |
| Cosmos DB              | privatelink.documents.azure.com              |
| Redis Cache            | privatelink.redis.cache.windows.net          |
| Storage Account        | privatelink.blob.core.windows.net            |
| Azure AI Search        | privatelink.search.windows.net               |
| Azure OpenAI           | privatelink.openai.azure.com                 |
| Document Intelligence  | privatelink.cognitiveservices.azure.com      |
| Content Safety         | privatelink.cognitiveservices.azure.com      |
| Speech Service         | privatelink.cognitiveservices.azure.com      |
| Video Indexer          | privatelink.cognitiveservices.azure.com      |

> **Note:** Some services (like Document Intelligence, Content Safety, Speech, Video Indexer) share the same DNS zone: `privatelink.cognitiveservices.azure.com`.

**You must link each DNS zone to the VNet and ensure the correct records are created for each private endpoint.**

#### **How Private Endpoints and DNS Work Together**

- When a Private Endpoint is created for a service, Azure automatically creates a private IP in the subnet and a DNS record in the linked Private DNS Zone.
- The App Service (via VNet Integration) resolves the service FQDN to the private IP, ensuring all traffic is routed privately.
- This setup prevents accidental data leakage to the public internet, even if a developer or admin uses a public FQDN in configuration.

#### **Summary of Steps for Enterprise Network Isolation**

1. **Create a VNet** with at least four subnets: App Inbound, App Outbound, Data, and AI Services.
2. **Deploy Private Endpoints** for each backend service (Cosmos DB, Redis, Storage, AI Search, OpenAI, etc.) into the appropriate subnet.
3. **Create and link Private DNS Zones** for each service type to the VNet.
4. **Configure App Service:**
   - Enable a **Private Endpoint** for inbound access (frontend).
   - Enable **VNet Integration** for outbound access to backend services.
5. **Restrict public network access** on all backend services (set "Deny public network access" to "Yes").
6. **Test connectivity** from the App Service to each backend service to ensure all traffic is private.

> This architecture is recommended for all production, government, and regulated environments. The pattern is identical for Azure Commercial, Azure Government, and custom/sovereign clouds—only the region and service endpoints differ.

For more details, see the [Azure documentation on Private Endpoints](https://learn.microsoft.com/azure/private-link/private-endpoint-overview) and [App Service VNet Integration](https://learn.microsoft.com/azure/app-service/overview-vnet-integration).
