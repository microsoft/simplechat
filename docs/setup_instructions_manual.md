# Simple Chat - Manual Setup Instructions

- [Provision Azure Resources](#provision-azure-resources)
- [Application-Specific Configuration Steps](#application-specific-configuration-steps)
  - [Setting Up Authentication (Azure AD / Entra ID)](#setting-up-authentication-azure-ad--entra-id)
  - [Grant App Registration Access to Azure OpenAI (for Model Fetching)](#grant-app-registration-access-to-azure-openai-for-model-fetching)
  - [Clone the Repository](#clone-the-repository)
  - [Configure Environment Variables (`.env` File)](#configure-environment-variables-env-file)
  - [Alternate Method: Update App Settings via JSON (Advanced)](#alternate-method-update-app-settings-via-json-advanced)
  - [Initializing Indexes in Azure AI Search](#initializing-indexes-in-azure-ai-search)
- [Installing and Deploying the Application Code](#installing-and-deploying-the-application-code)
  - [Deploying via VS Code (Recommended for Simplicity)](#deploying-via-vs-code-recommended-for-simplicity)
  - [Deploying via Azure CLI (Zip Deploy)](#deploying-via-azure-cli-zip-deploy)
- [Running the Application](#running-the-application)
- [Upgrading the Application](#upgrading-the-application)
  - [Using Deployment Slots (Recommended for Production/Staging)](#using-deployment-slots-recommended-for-productionstaging)
  - [Using Direct Deployment to Production (Simpler, for Dev/Test or Low Impact Changes)](#using-direct-deployment-to-production-simpler-for-devtest-or-low-impact-changes)
  - [Automate via CI/CD](#automate-via-cicd)
- [Return to Main](../README.md)


> <a href="#simple-chat---manual-setup-instructions" style="text-decoration: none;">Return to top</a>

## Provision Azure Resources

Deploy the necessary Azure services. For a quick estimate of monthly costs based on recommended baseline SKUs for a Demo/Proof-of-Concept (POC)/Minimum Viable Product (MVP) solution, refer to the [Azure Pricing Calculator Link](https://azure.com/e/86504dd2857343ae80bda654ae4cc2f4). The services and SKUs below are reflected in that estimate.

> [!IMPORTANT]
> The following recommended SKUs are intended for **Development, Demo, POC, or MVP purposes only**. You **must** scale these services appropriately based on expected user load, data volume, and performance requirements when moving to a Production environment. Factors like concurrent users, document ingestion rate, and query complexity will influence the required tiers and instance counts.

| Service Type                 | Recommended Minimum SKU (for Dev/Demo/POC/MVP)               | Description / Notes                                          |
| :--------------------------- | :----------------------------------------------------------- | :----------------------------------------------------------- |
| **App Service (Frontend)**   | Premium V3 P0v3 (1 Core, 4 GB RAM, 250 GB Storage), Linux    | Hosts the Python Flask web application. Consider scaling up (P1v3+) or out (multiple instances) for production. |
| **Azure OpenAI (GPT)**       | Standard S0, `gpt-4o` deployment                             | Powers core chat functionality and optional Metadata Extraction. Choose model based on cost/performance needs. Pay-as-you-go pricing. |
| **Azure OpenAI (Embedding)** | Standard S0, `text-embedding-3-small` deployment             | Required for RAG (Your Workspace, My Groups). Generates vector embeddings. Pay-as-you-go. |
| **Azure OpenAI (Image Gen)** | Standard S0, `dall-e-3` deployment (Optional)                | Required only if Image Generation feature is enabled. Pay-as-you-go per image. |
| **Azure AI Search**          | Standard S1 (consider S2/S3 for larger scale/HA)             | Stores and indexes document chunks for RAG. Includes Semantic Ranker capacity. Scale units/replicas/partitions for performance/HA. |
| **Content Safety**           | Standard S0 (Optional)                                       | Required only if Content Safety feature is enabled. Pay-as-you-go per 1k text records / 1k images. |
| **Document Intelligence**    | Standard S0                                                  | Used for text/layout extraction from various file types during ingestion. Pay-as-you-go per page processed. |
| **Cosmos DB (NoSQL)**        | Autoscale provisioned throughput (Start ~1000 RU/s), Single-Region Write | Stores metadata, conversations, settings. Autoscale helps manage costs, but monitor RU consumption and adjust max RU for production loads. |
| **Video Indexer**            | Standard Tier (Optional)                                     | Required only if Video Extraction feature is enabled. Pay-as-you-go per input content minute (All Insights). |
| **Speech Service**           | Standard S0 (Optional)                                       | Required only if Audio Extraction feature is enabled. Pay-as-you-go per audio hour (Standard fast transcription). |
| **Storage Account**          | General Purpose V2, LRS, Hot Tier (Optional)                 | Required if Enhanced Citations feature is enabled. Stores processed files. Hierarchical Namespace (ADLS Gen2) recommended. - OR - Required if you want to use Azure Storage for temporaty file storage which is recommend for scalability and better performance |
| **Azure Cache for Redis**    | Standard Tier, C0 cache size (Optional)                      | Required only if you need the performance, scalability, and distributed session support provided by Redis Cache. |

> **Note**: Pricing is subject to change and varies significantly based on usage, region, specific configurations (e.g., network security, backup policies), and selected tiers. Always use the official Azure Pricing Calculator and monitor your Azure costs closely.

**Deployment Steps:**

1.  **Create or Select a Resource Group**:
    *   Group all related resources within a single Azure Resource Group (e.g., `rg-simple-chat-prod`, `rg-simple-chat-dev`).
    *   Deploy resources in the same Azure region where possible to minimize latency, unless specific service availability or compliance dictates otherwise (e.g., Azure OpenAI model availability).
2.  **Deploy App Service**:
    *   Create an Azure App Service instance.
    *   **Publish**: Code
    *   **Runtime stack**: Python 3.12
    *   **Operating System**: Linux
    *   **Region**: Choose your desired region.
    *   **App Service Plan**: Create a new Linux plan using the **Premium V3 (P0v3)** tier (or higher for production). Zone redundancy typically **Disabled** for baseline, enable for HA if needed.
    *   Review Networking (Public access defaults), Deployment, Monitoring settings. Modify based on organizational security/operational requirements.
    *   Note the default **App Name** and **URL** (e.g., `https://my-simplechat-app.azurewebsites.net`). This URL will be needed for AAD App Registration redirects.
3.  **Deploy Azure OpenAI Service(s)**:
    *   You can deploy a single Azure OpenAI resource hosting all models or separate resources (e.g., one for GPT, one for Embeddings) based on regional availability or management preference.
    *   Create an **Azure OpenAI** resource. Select **Standard S0** pricing tier.
    *   **Deploy Models**: Within the Azure OpenAI Studio for your resource(s), deploy the required models with custom deployment names:
        *   **GPT Model**: e.g., `gpt-4o` (Required for chat, optional for metadata). Note the **Deployment Name**.
        *   **Embedding Model**: e.g., `text-embedding-3-small` (Required for Workspaces/RAG). Note the **Deployment Name**.
        *   **Image Generation Model**: e.g., `dall-e-3` (Required for optional Image Generation). Note the **Deployment Name**.
    *   Review Networking settings (default public access, modify as needed).
    *   If using **Managed Identity** authentication later, you will need to grant the App Service's Managed Identity the `Cognitive Services OpenAI User` role on this resource(s).
4.  **Deploy Azure AI Search**:
    *   Create an **Azure AI Search** service.
    *   Select the **Standard S1** tier (or higher based on scale/HA needs). Consider replicas/partitions for production.
    *   Review Networking settings.
    *   You will initialize indexes later ([Initializing Indexes](#initializing-indexes-in-azure-ai-search)).
    *   If using **Managed Identity**, grant the App Service's Managed Identity the `Search Index Data Contributor` role on this resource.
5.  **Deploy Azure Cosmos DB**:
    *   Create an **Azure Cosmos DB** account.
    *   Select the **Azure Cosmos DB for NoSQL** API.
    *   **Capacity mode**: Provisioned throughput. Choose **Autoscale**.
    *   Set **Max throughput** at the database level initially (e.g., start with 1000 RU/s, monitor and adjust).
        - Note: Autoscale automatically adjusts the provisioned Request Units (RU/s) between 10% and 100% of this maximum value based on usage (e.g., 1000 max RU/s scales between 100 - 1000 RU/s).
        - **Container-Level Scaling (Recommended Post-Setup)**: While you set an initial database-level throughput, it's highly recommended to configure Autoscale throughput **per container** after the application creates them (or manually create them with these settings). For optimal performance and cost-efficiency, consider setting the *maximum* Autoscale throughput for key containers as follows:
          - messages container: **4000 RU/s** (will scale between 400 - 4000 RU/s)
          - documents container: **4000 RU/s** (will scale between 400 - 4000 RU/s)
          - group_documents container: **4000 RU/s** (will scale between 400 - 4000 RU/s)
          - Other containers (like settings, feedback, archived_conversations) often have lower usage and can typically start with a lower maximum (e.g., 1000 RU/s, scaling 100-1000 RU/s), but monitor their consumption.
    *   **Apply Free Tier Discount**: **DO NOT APPLY** (Free tier throughput is insufficient).
    *   **Limit total account throughput**: **Uncheck** (DISABLE).
    *   Review Networking, Backup Policy, Encryption settings.
    *   If using **Managed Identity**, grant the App Service's Managed Identity the `Cosmos DB Built-in Data Contributor` role (or create custom roles for least privilege). *Note: Managed Identity support for Cosmos DB data plane might require specific configurations.* Key-based auth is simpler initially.
6.  **Deploy Azure AI Document Intelligence**:
    *   Create an **Azure AI Document Intelligence** (formerly Form Recognizer) resource.
    *   Select the **Standard S0** pricing tier.
    *   Review Networking settings.
    *   If using **Managed Identity**, grant the App Service's Managed Identity the `Cognitive Services User` role on this resource.
7.  **Deploy Azure AI Content Safety (Optional)**:
    *   If using the Content Safety feature, create an **Azure AI Content Safety** resource.
    *   Select the **Standard S0** pricing tier.
    *   Review Networking settings.
    *   If using **Managed Identity**, grant the App Service's Managed Identity the `Cognitive Services Contributor` role on this resource.
8.  **Deploy Azure Video Indexer (Optional)**:
    *   If using the Video Extraction feature, create an **Azure Video Indexer** resource in the Azure Portal.
    *   You'll need to associate it with an Azure Media Services account (can be created during VI setup) and a Storage Account (used for temporary processing, can be new or existing).
    *   **Enable System-assigned Managed Identity** on your App Service if not already enabled (Identity > System assigned > Status: On).
    *   **Grant the App Service's Managed Identity the `Contributor` role** on the Video Indexer resource:
        - Navigate to your Video Indexer resource > Access control (IAM)
        - Add role assignment > Select `Contributor` role
        - Assign access to "Managed Identity"
        - Select your App Service's managed identity
    *   Note the **Account ID**, **Account Name**, **Resource Group**, **Subscription ID**, and **Location** (e.g., eastus). These will be configured in Admin Settings.
    *   See [Azure Video Indexer documentation](https://learn.microsoft.com/azure/azure-video-indexer/connect-to-azure) for detailed setup instructions.
9.  **Deploy Azure Speech Service (Optional)**:
    *   If using the Audio Extraction feature, create an **Azure AI Speech** resource.
    *   Select the **Standard S0** pricing tier.
    *   Review Networking and Identity settings.
    *   Note the **Endpoint**, **Region/Location**, and one of the **Keys**. These will be configured in Admin Settings.
11. **Deploy Storage Account (Optional)**:
    *   If using the Enhanced Citations feature, create an **Azure Storage Account**.
    *   **Performance**: Standard.
    *   **Redundancy**: LRS (or higher based on requirements).
    *   **Account Kind**: StorageV2 (general purpose v2).
    *   **Enable hierarchical namespace** (Azure Data Lake Storage Gen2) is recommended for better organization if storing large volumes.
    *   Review Networking, Data protection, Encryption settings.
    *   Note the **Connection String** (under Access Keys or SAS token). This will be configured in Admin Settings. If using Managed Identity, grant the App Service's Managed Identity the `Storage Blob Data Contributor` role.
    *   After deployment, note the **Connection String** (under Access Keys or SAS token). This will be configured in Admin Settings. If using Managed Identity, grant the App Service's Managed Identity the `Storage Blob Data Contributor` role.
    *   Navigate to **Data Storage** > **Containers** > **+ Container**. Add two new containers - `user-documents` and `group-documents
10. **Deploy Azure Cache for Redis (Optional)**:
    *   Create an **Azure Cache for Redis** service.
    *   **Name**: Choose a unique name for your Redis instance (e.g., `simplechat-redis`).
    *   **Region**: Select the same region as your App Service for lowest latency.
    *   **Cache SKU**: Standard.
    *   **Cache Size**: C0 (or higher based on requirements).
    *   **Networking**: Set to **Public** for initial setup (can be made private later for enhanced security).
    *   **Advanced**:
        - Enable **Access Keys Authentication** (required for key-based access).
        - All other advanced settings can remain at their defaults unless you have specific requirements.
    *   After Redis is created, note the **Host Name** and **Access Keys** (if using key authentication).
    *   If using managed identities, enable Entra Authentication and select the App Service managed identity.
    *   The Redis service can take 15-30 minutes to fully deploy.
13. **Use Azure Storage for temporary data data (Optional)**:
    *   Create an **Azure Storage Account** if you previously created Enhanced Citations you can use it.  Otherwise look at step 11 for recommendations on settings.
    *   **Enable Storage Account Key Access**
        - Goto the storage account
        - Click on Configuration (in the Settings section)
        - Click on Enable Key Access and click Save
    *   **Create a FileShare**:
        - Cick on File Shares in the Data Storage section
        - Click Add File Share
        - Give it a name (write it down for use later)
        - Click Next: Backup
        - Turn off enable backup, unless you are using this share for other files
        - Click Review and Create, then Create
    *   **Create the Share in your App Service**: 
         - Return to your App Service
         - Click on Configuration (the in Settings Section) 
         - Click on Path Mappings
         - Click on Add New Azure Storage Mount
           - Give it a name
           - Use Basic for Configuration Options
           - Select your storage account
           - Select Azure Files for Storage Type
           - Select SMB for Protocal
           - Select the FileShare your created for the Storage Container
           - Set the mount path **/sc-temp-files**  - Important to use this name
           - Click OK and then click Save

## Application-Specific Configuration Steps

> <a href="#simple-chat---manual-setup-instructions" style="text-decoration: none;">Return to top</a>

With the Azure resources provisioned, proceed with configuring the application itself. Perform these steps in order.

### Setting Up Authentication (Azure AD / Entra ID)

The application uses Azure Active Directory (Entra ID) for user authentication and role management.

1.  **Register an Application in Azure AD**:
    *   Navigate to **Azure Active Directory** > **App registrations** > **+ New registration**.
    *   Give it a name (e.g., `SimpleChatApp-Prod`).
    *   Select **Accounts in this organizational directory only** (or adjust if multi-tenant access is needed).
    *   Set the **Redirect URI**:
        *   Select **Web** platform.
        *   Enter the URI: `https://<your-app-service-name>.azurewebsites.net/.auth/login/aad/callback` (Replace `<your-app-service-name>` with your actual App Service name).
    *   Click **Register**.
    *   Note the **Application (client) ID** and **Directory (tenant) ID**. These are needed for the `.env` file (`CLIENT_ID`, `TENANT_ID`).
    *   Next, click the  **Authentication** link in the Manage section 
    *   In the Web **Redirect URIs** section of the page click **Add URI**
    *   Enter the URI: `https://<your-app-service-name>.azurewebsites.net/getAToken` (Replace `<your-app-service-name>` with your actual App Service name).
    *   Next in the **Front-channel logout URL** section of the page
    *   Enter the URI: `https://<your-app-service-name>.azurewebsites.net/logout` (Replace `<your-app-service-name>` with your actual App Service name).
    *   Now look at the **Implicit grant and hybrid flows** section
    *   Make sure the checked for ***ID tokens (used for implicit and hybrid flows)** is checked
    *   Click the **Save** button
    ![App Registration Settings](./images/app_reg_settings.png)  *(Note: Image shows general area, details might differ slightly)*
    *    Click on the **Certificates and secrets link** in the manage section
    *    Click on **Client Secrets**
    *    Verify that there is a Secret Named **MICROSOFT_PROVIDER_AUTHENTICATION_SECRET**
    *    If there is not, click on **New Client Secret** to create a new secret using **MICROSOFT_PROVIDER_AUTHENTICATION_SECRET** as the name.
    *    Make sure you copy the **Value** before you leave this page.
    ![App Registration Settings](./images/app_reg_secrets.png)  *(Note: Image shows general area, details might differ slightly)*

2.  **Configure App Service Authentication**:
    *   Go to your **App Service** in the Azure portal.
    *   Navigate to **Settings** > **Authentication**.
    *   Click **Add identity provider**.
    *   **Identity provider**: Microsoft
    *   **App registration type**: Pick an existing app registration in this directory.
    *   Select the **App registration** you just created.
    *   **Restrict access**: Require authentication.
    *   **Unauthenticated requests**: HTTP 302 Found redirect: recommended for web apps.
    *   Click **Add**. This configures the built-in App Service Authentication (Easy Auth).
    *   ⚠️ **Important**  ⚠️: After adding the provider, go back into the **Authentication** settings for the App Service, click **Edit** on the Microsoft provider. 
        *   Ensure the **Issuer URL** is correct (usually `https://login.microsoftonline.com/<your-tenant-id>/v2.0` or `https://sts.windows.net/<your-tenant-id>/v2.0`). 
        *   Note the **Client Secret Setting Name** value shown here. This secret (`MICROSOFT_PROVIDER_AUTHENTICATION_SECRET`) is often automatically added to App Service Application Settings.  If the name is not there (or a different name is there) click on **Click to edit secret value**
        *   Click on **Add**, for the name use `MICROSOFT_PROVIDER_AUTHENTICATION_SECRET` for the value enter the Key that you copied in the previous step
        *   Click **Apply**, the click **Apply** again
        *   Return to the **Edit identity provider** page and now select `MICROSOFT_PROVIDER_AUTHENTICATION_SECRET` for the Client Secret setting name.  (It may take a minute for that name to appear)

    ![App Registration - Authentication Configuration in App Service](./images/app_reg_edit_identity.png)  *(Note: Image shows general area, details might differ slightly)*

3.  **Configure API Permissions**:
    *   Go back to your **App Registration** in Azure AD.
    *   Navigate to **API permissions**.
    *   Click **+ Add a permission**.
    *   Select **Microsoft Graph**.
    *   Select **Delegated permissions**.
    *   Add the following permissions:
        *   `email`
        *   `offline_access`
        *   `openid`
        *   `profile`
        *   `User.Read` (Allows sign-in and reading the user's profile)
        *   `User.ReadBasic.All` (Allows reading basic profiles of all users - often needed for people pickers if not using `People.Read.All`)
        *   **(Conditional)** `People.Read.All`: **Required if** you enable the **My Groups** feature, as it's used to search for users within your tenant to add to groups. Add this permission if needed.
        *   **(Conditional)** `Group.Read.All`: **Required if** you enable the **My Groups** feature or need to read group memberships and group details for group workspaces. This permission allows the app to list groups and read group properties and memberships in your organization. Add this permission if group-based collaboration or group document access is needed.
    *   After adding permissions, click **Grant admin consent for [Your Tenant Name]**. This is crucial, especially for `*.All` permissions.

    ![App Registration - API Permissions](./images/app_reg-api_permissions.png) 

4.  **Configure App Roles**:
    *   In your **App Registration**, navigate to **App roles**.
    *   Click **+ Create app role**.
    *   Create roles based on the following table. Repeat for each role:

    | Display Name               | Allowed member types | Value                  | Description                                      | Do you want to enable this app role? |
    | :------------------------- | :------------------- | :--------------------- | :----------------------------------------------- | :----------------------------------- |
    | **Admins**                 | Users/Groups         | `Admin`                | Allows access to Admin Settings page.            | Yes                                  |
    | **Users**                  | Users/Groups         | `User`                 | Standard user access to chat features.           | Yes                                  |
    | **Create Group**           | Users/Groups         | `CreateGroups`         | Allows user to create new groups (if enabled).   | Yes                                  |
    | **Safety Violation Admin** | Users/Groups         | `SafetyViolationAdmin` | Allows access to view content safety violations. | Yes                                  |
    | **Feedback Admin**         | Users/Groups         | `FeedbackAdmin`        | Allows access to view user feedback admin page.  | Yes                                  |

    ![App Registration - App Roles](./images/app_reg-app_roles.png) 

5.  **Assign Users/Groups to Roles via Enterprise Application**:
    *   App Roles are *assigned* through the **Enterprise Application** associated with your App Registration.
    *   Navigate to **Azure Active Directory** > **Enterprise applications**.
    *   Find the application with the same name as your App Registration (or search by Application ID).
    *   Select your Enterprise Application.
    *   Go to **Users and groups**.
    *   Click **+ Add user/group**.
    *   Select the users or security groups you want to grant access.
    *   Under **Select a role**, choose the appropriate App Role (`Admins`, `Users`, etc.) you defined.
    *   Click **Assign**. Only assigned users/groups will be able to log in (if "Assignment required?" is enabled on the Enterprise App, which is recommended).

### Grant App Registration Access to Azure OpenAI (for Model Fetching)

The application needs permission to list the available models deployed in your Azure OpenAI resource(s). This uses the *App Registration's Service Principal*.

1.  Go to each **Azure OpenAI** service resource in the Azure portal.
2.  Select **Access control (IAM)**.
3.  Click **+ Add** > **Add role assignment**.
4.  Search for and select the role **Cognitive Services OpenAI User**. Click Next.
5.  **Assign access to**: Select **User, group, or service principal**.
6.  **Members**: Click **+ Select members**.
7.  Search for the **name of your App Registration** (e.g., `SimpleChatApp-Prod`). Select it.
8.  Click **Select**, then **Next**.
9.  Click **Review + assign**.
10. Repeat for *all* Azure OpenAI resources used by the application (GPT, Embedding, Image Gen if separate).

![Add role assignment - Job function role selected](./images/add_role_assignment-job_function.png) 
![Add role assignment - Selecting the Service Principal (App Registration)](./images/add_role_assignment-select_member-service_principal.png)

### Clone the Repository

Get the application code onto your local machine.

1.  Open a terminal or command prompt.
2.  Use Git to clone the repository:
    ```bash
    git clone <repository-url>
    cd <repository-folder>
    ```
    (Replace `<repository-url>` and `<repository-folder>` accordingly).
    *Alternatively*, use GitHub Desktop or download the ZIP and extract it.

![Clone the repo options in GitHub UI](./images/clone_the_repo.png) 

### Configure Environment Variables (`.env` File)

Core configuration values are managed via environment variables, typically set in the Azure App Service Application Settings. A `.env` file is used locally and can be uploaded to populate these settings.

1.  **Create `.env` from Example**:
    *   Find the `example.env` file in the cloned repository.
    *   Rename or copy it to `.env`.
2.  **Edit `.env`**:
    *   Open the `.env` file in a text editor (like VS Code).
    *   Fill in the placeholder values with your actual service details:

    ```dotenv
    # Azure Cosmos DB
    # Use connection string OR endpoint/key OR managed identity
    # e.g., https://mycosmosdb.documents.azure.com:443/
    AZURE_COSMOS_ENDPOINT="<your-cosmosdb-account-uri>"
    AZURE_COSMOS_KEY="<your-cosmosdb-primary-key>"
    # Options: "key", "connection_string", "managed_identity"
    AZURE_COSMOS_AUTHENTICATION_TYPE="key"
    
    # Azure AD Authentication (Required)
    CLIENT_ID="<your-app-registration-client-id>"
    TENANT_ID="<your-azure-ad-tenant-id>"
    # SECRET_KEY should be a long, random, secret string (e.g., 32+ chars) used for Flask session signing. Generate one securely.
    SECRET_KEY="Generate-A-Strong-Random-Secret-Key-Here!"
    # AZURE_ENVIRONMENT: Set based on your cloud environment
    # Options: "public", "usgovernment", "custom"
    AZURE_ENVIRONMENT="public"
    ```
    
3.  **Upload Settings to Azure App Service (Recommended using VS Code)**:
    
    *   Ensure the `.env` file is saved and **closed**.
    *   In VS Code, with the Azure App Service extension installed and signed in:
        *   **Option 1 (Command Palette)**: Press `Ctrl+Shift+P` (or `Cmd+Shift+P`), type `Azure App Service: Upload Local Settings`, select your subscription and App Service instance, then choose the `.env` file.
        *   **Option 2 (File Explorer)**: Right-click the `.env` file in the VS Code explorer, select `Azure App Service: Upload Local Settings`, and follow the prompts.
    *   This action reads your `.env` file and sets the corresponding **Application Settings** in the Azure App Service configuration blade.
    
    ![Upload local settings - Option 1 (Command Palette)](./images/upload_local_settings_1.png) 
    ![Upload local settings - Option 2 (Right-click)](./images/upload_local_settings_2.png)
    
4.  **(Optional) Download Settings from Azure App Service**:
    *   To verify or synchronize settings from Azure back to a local `.env` file:
    *   Press `Ctrl+Shift+P`, type `Azure App Service: Download Remote Settings`, select your App Service, and choose where to save the file (e.g., overwrite your local `.env`). This is useful to capture settings automatically added by Azure (like `APPLICATIONINSIGHTS_CONNECTION_STRING` or `WEBSITE_AUTH_AAD_ALLOWED_TENANTS`).

    ![Download remote settings command](./images/download_remote_settings.png)

5.  **First-Time Configuration Wizard**:
    *   When you first access the admin settings page, a configuration wizard will guide you through the required and optional settings.
    *   The wizard will help you configure:
        *   **Application basics**: Title and logo customization
        *   **GPT API settings**: Configure Azure OpenAI endpoints and models
        *   **Workspace settings**: Enable personal and group workspaces
        *   **Additional services**: Configure embedding, AI Search, Document Intelligence, and other required services
        *   **Optional features**: Content safety, user feedback, conversation archiving, and other optional features
    *   Required settings are clearly marked, ensuring that you configure all necessary components for your deployment scenario.

### Alternate Method: Update App Settings via JSON (Advanced)

You can directly edit Application Settings in the Azure portal using the "Advanced edit" feature, pasting a JSON array. This is useful for bulk updates but requires care not to overwrite essential settings added by Azure.

1.  Navigate to your **App Service** > **Settings** > **Configuration** > **Application settings**.
2.  **Backup Existing Values**: Before pasting, **copy** the current values for critical settings like `MICROSOFT_PROVIDER_AUTHENTICATION_SECRET`, `APPLICATIONINSIGHTS_CONNECTION_STRING`, and `WEBSITE_AUTH_AAD_ALLOWED_TENANTS`.
3.  **Prepare JSON**: Create a JSON array similar to the example below, inserting your specific values and the backed-up Azure-managed values.
4.  Click **Advanced edit**.
5.  **Carefully replace** the existing JSON content with your prepared JSON.
6.  Click **OK**, then **Save**.

**Example JSON Structure:**

```json
[
    // --- Azure Managed / Essential Settings ---
    { "name": "APPLICATIONINSIGHTS_CONNECTION_STRING", "value": "<your-appinsights-connection-string>", "slotSetting": false },
    { "name": "APPINSIGHTS_INSTRUMENTATIONKEY", "value": "<your-appinsights-instrumentation-key>", "slotSetting": false }, // Often same key as connection string contains
    { "name": "MICROSOFT_PROVIDER_AUTHENTICATION_SECRET", "value": "<app-service-auth-secret>", "slotSetting": true }, // CRITICAL - Get from portal if unsure
    { "name": "WEBSITE_AUTH_AAD_ALLOWED_TENANTS", "value": "<your-tenant-id>", "slotSetting": false }, // Usually set by Auth config
    { "name": "WEBSITE_AUTH_ENABLED", "value": "True", "slotSetting": true }, // Should be set by Auth config
    { "name": "WEBSITE_AUTH_DEFAULT_PROVIDER", "value": "AzureActiveDirectory", "slotSetting": true }, // Should be set by Auth config

    // --- Your Application Settings (from .env) ---
    { "name": "AZURE_COSMOS_ENDPOINT", "value": "<your-cosmosdb-endpoint>", "slotSetting": false },
    { "name": "AZURE_COSMOS_KEY", "value": "<your-cosmosdb-key>", "slotSetting": false },
    { "name": "AZURE_COSMOS_DATABASE", "value": "SimpleChat", "slotSetting": false },
    { "name": "AZURE_COSMOS_AUTHENTICATION_TYPE", "value": "key", "slotSetting": false }, // or "managed_identity"
    { "name": "CLIENT_ID", "value": "<your-app-registration-client-id>", "slotSetting": false },
    { "name": "TENANT_ID", "value": "<your-azure-ad-tenant-id>", "slotSetting": false },
    { "name": "SECRET_KEY", "value": "<your-flask-secret-key>", "slotSetting": false },
    { "name": "AZURE_ENVIRONMENT", "value": "public", "slotSetting": false }, // or "usgovernment", or "custom"

    // --- Build & Runtime Settings ---
    { "name": "SCM_DO_BUILD_DURING_DEPLOYMENT", "value": "true", "slotSetting": false }, // Ensures requirements.txt is processed
    { "name": "WEBSITE_HTTPLOGGING_RETENTION_DAYS", "value": "7", "slotSetting": false },

    // --- Optional App Insights Advanced Settings (Defaults usually fine) ---
    { "name": "ApplicationInsightsAgent_EXTENSION_VERSION", "value": "~3", "slotSetting": false },
    { "name": "APPLICATIONINSIGHTSAGENT_EXTENSION_ENABLED", "value": "true", "slotSetting": false },
    { "name": "XDT_MicrosoftApplicationInsights_Mode", "value": "default", "slotSetting": false },
    { "name": "APPINSIGHTS_PROFILERFEATURE_VERSION", "value": "1.0.0", "slotSetting": false },
    { "name": "APPINSIGHTS_SNAPSHOTFEATURE_VERSION", "value": "1.0.0", "slotSetting": false },
    { "name": "SnapshotDebugger_EXTENSION_VERSION", "value": "disabled", "slotSetting": false },
    { "name": "InstrumentationEngine_EXTENSION_VERSION", "value": "disabled", "slotSetting": false },
    { "name": "XDT_MicrosoftApplicationInsights_BaseExtensions", "value": "disabled", "slotSetting": false },
    { "name": "XDT_MicrosoftApplicationInsights_PreemptSdk", "value": "disabled", "slotSetting": false }
]
```

> [!WARNING]
>
> Editing Application Settings via JSON is powerful but risky. Incorrectly modifying or omitting settings managed by Azure (especially Authentication or App Insights integration) can break functionality. Proceed with caution and always back up existing values. Using the .env upload method is generally safer.

![alt text](./images/advanced_edit_env.png)

### Initializing Indexes in Azure AI Search

The application requires two Azure AI Search indexes: one for personal user documents and one for shared group documents. The schemas are defined in JSON files within the repository.

1. **Locate Index Schema Files**:

   - In your cloned repository, find the artifacts/ai_search_index/ directory.
   - It contains ai_search-index-user.json and ai_search-index-group.json.

   ```
   📁 SimpleChat
        └── 📁 artifacts
            └── 📁 ai_search_index
                ├── ai_search-index-group.json
                └── ai_search-index-user.json
   ```

2. **Access Azure AI Search in Azure Portal**:

   - Navigate to your **Azure AI Search** service resource.
   - Under **Search management**, select **Indexes**.

3. **Create Indexes from JSON**:

   - Click **+ Add index**.
   - Change the creation method from Enter index name to **Import from JSON**.
   - **User Index**:
     - Open ai_search-index-user.json locally, copy its entire content.
     - Paste the JSON into the **Index definition (JSON)** editor in the portal.
     - The Index Name should automatically populate as simplechat-user-index.
     - Click **Save**.
   - **Group Index**:
     - Click **+ Add index** again and choose **Import from JSON**.
     - Open ai_search-index-group.json locally, copy its content.
     - Paste the JSON into the editor.
     - The Index Name should populate as simplechat-group-index.
     - Click **Save**.

4. **Verify Indexes**:

   - You should now see simplechat-user-index and simplechat-group-index listed under **Indexes**.

> [!NOTE]
>
> **Automatic Schema Update Feature**: If you happen to miss this step or deploy an updated version of the application with new required index fields, the application includes a mechanism to help. When an Admin user navigates to the **Admin > App Settings** page, the application backend checks the schemas of the existing simplechat-user-index and simplechat-group-index against the expected schema. If missing fields are detected, notification buttons will appear at the top of the Admin Settings page: "**Add missing user fields**" and "**Add missing group fields**". Clicking these buttons will automatically add the missing fields to your Azure AI Search indexes without data loss. While this feature provides resilience, it's still recommended to create the indexes correctly using the JSON definitions initially.

![alt text](./images/ai_search-missing_index_fields.png)

## Installing and Deploying the Application Code

Deploy the application code from your local repository to the Azure App Service.

### Deploying via VS Code (Recommended for Simplicity)

1. **Ensure Azure Extensions are Installed**: You need the **Azure Tools Extension Pack** and the **Azure App Service** extension in VS Code.
2. **Sign In to Azure**: Use the Azure extension to sign in to your Azure account.
3. **Deploy**:
   - In the VS Code Activity Bar, click the Azure icon.
   - Expand **App Service**, find your subscription and the App Service instance you created.
   - **Right-click** on the App Service name.
   - Select **Deploy to Web App...**.
   - Browse and select the folder containing the application code (the root folder you cloned, e.g., SimpleChat).
   - VS Code will prompt to confirm the deployment, potentially warning about overwriting existing content. Click **Deploy**.
   - Make sure your requirements.txt file is up-to-date before deploying. The deployment process (SCM_DO_BUILD_DURING_DEPLOYMENT=true) will use this file to install dependencies on the App Service.
   - Monitor the deployment progress in the VS Code Output window.

### Deploying via Azure CLI (Zip Deploy)

This method involves creating a zip file of the application code and uploading it using the Azure CLI. Refer to the official documentation for detailed steps: [Quickstart: Deploy a Python web app to Azure App Service](https://www.google.com/url?sa=E&q=https://learn.microsoft.com/en-us/azure/app-service/quickstart-python?tabs=flask%2Cwindows%2Cazure-cli%2Czip-deploy%2Cdeploy-instructions-azportal%2Cterminal-bash%2Cdeploy-instructions-zip-azcli).

**Key Steps:**

1. **Create the ZIP file**:

   - Navigate into the application's root directory (e.g., SimpleChat) in your terminal.
   - Create a zip file containing **only** the necessary application files and folders. **Crucially, zip the contents, not the parent folder itself.**
   - **Include**:
     - static/ folder
     - templates/ folder
     - requirements.txt file
     - All Python files (*.py) at the root level (e.g., app.py, utils.py, etc.).
     - Any other necessary support files or directories at the root level.
   - **Exclude**:
     - .git/ folder and .gitignore
     - .vscode/ folder
     - __pycache__/ directories
     - .env, example.env (environment variables are set in App Settings)
     - .deployment, Dockerfile, .dockerignore (unless specifically using Docker deployment)
     - README.md, LICENSE, .DS_Store, etc.
     - Any local virtual environment folders (e.g., .venv, env).

   ![alt text](./images/files_to_zip.png)

   ![alt text](./images/zip_the_files.png)

   **Ensure SCM_DO_BUILD_DURING_DEPLOYMENT is Set**: Verify this application setting is true in your App Service configuration to ensure dependencies are installed from requirements.txt during deployment.

2. **Deploy using Azure CLI**:

   ```
   az login # Sign in if you haven't already
   az account set --subscription "<Your-Subscription-ID>"
   
   az webapp deploy --resource-group <Your-Resource-Group-Name> --name <Your-App-Service-Name> --src-path ../deployment.zip --type zip
   ```

## Running the Application

1. Navigate to your **App Service** in the Azure Portal.
2. On the **Overview** blade, find the **Default domain** URL (e.g., https://my-simplechat-app.azurewebsites.net).
3. Click the URL to open the application in your browser.
4. You should be redirected to the Microsoft login page to authenticate via Azure AD. Log in with a user account that has been assigned a role in the Enterprise Application.

![alt text](./images/visit_app.png)

## Upgrading the Application

> <a href="#simple-chat---manual-setup-instructions" style="text-decoration: none;">Return to top</a>

Keeping your Simple Chat application up-to-date involves deploying the newer version of the code. Using **Deployment Slots** is the recommended approach for production environments to ensure zero downtime and provide easy rollback capabilities.

![alt text](./images/admin_settings-upgrade_available_notification.png)

### Using Deployment Slots (Recommended for Production/Staging)

1. **Create a Deployment Slot**:

   - In your App Service, go to **Deployment** > **Deployment slots**.
   - Click **+ Add Slot**. Give it a name (e.g., staging).
   - Choose to **clone settings** from the production slot initially.
   - This creates a fully functional, independent instance of your app connected to the same App Service Plan.

2. **Deploy New Version to Staging Slot**:

   - Deploy the updated application code (using VS Code deployment or az webapp deploy) specifically targeting the **staging slot**.

   - **VS Code**: When deploying, VS Code will prompt you to select the target slot (production or staging). Choose staging.

   - **Azure CLI**: Add the --slot staging parameter to your az webapp deploy command:

     ```
     az webapp deploy --resource-group <RG_Name> --name <App_Name> --src-path <Zip_Path> --type zip --slot staging
     ```

3. **Test the Staging Slot**:

   - The staging slot has its own unique URL (e.g., https://my-simplechat-app-staging.azurewebsites.net). Access this URL directly.
   - Thoroughly test all application functionality, including new features and critical paths, in the staging environment. This slot typically uses the same backend resources (Cosmos DB, AI Search, etc.) as production unless configured otherwise (e.g., using slot-specific Application Settings).

4. **Swap Staging to Production**:

   - Once confident the new version in staging is stable, go back to **Deployment slots** in the Azure portal.

   - Click the **Swap** button.

   - Configure the swap:

     - **Source**: staging
     - **Target**: production

   - Azure performs a "warm-up" of the staging slot instance before redirecting production traffic to it. The previous production code is simultaneously moved to the staging slot. This swap happens near-instantly from a user perspective.

   - **Azure CLI Swap Command**:

     ```
     az webapp deployment slot swap --resource-group <RG_Name> --name <App_Name> --slot staging --target-slot production
     ```

5. **Monitor and Rollback (If Necessary)**:

   - Monitor the application closely after the swap using Application Insights and user feedback.
   - If critical issues arise, you can perform another **Swap** operation, this time swapping production (which now contains the problematic code) back with staging (which now contains the previous stable code). This provides an immediate rollback.

### Using Direct Deployment to Production (Simpler, for Dev/Test or Low Impact Changes)

You can deploy directly to the production slot using the same VS Code or Azure CLI methods described in the initial deployment section, simply omitting the --slot parameter or choosing the production slot in VS Code.

> [!WARNING]
>
> Deploying directly to production overwrites the live code. This will cause a brief application restart and offers no immediate rollback capability (you would need to redeploy the previous version). This method is generally **not recommended** for production environments or significant updates due to the downtime and risk involved.

### Automate via CI/CD

For mature development practices, set up a Continuous Integration/Continuous Deployment (CI/CD) pipeline using tools like GitHub Actions or Azure DevOps Pipelines. A typical pipeline would:

1. Trigger on code commits/merges to specific branches (e.g., main, release/*).
2. Build the application artifact (e.g., create the zip file).
3. Deploy the artifact to the staging slot.
4. (Optional) Run automated tests against the staging slot.
5. Require manual approval (or automatically trigger based on test results) to perform the swap operation to production.
