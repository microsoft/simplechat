---

layout: page

title: "Provision Azure Resources"

description: "Manual setup reference for provision azure resources."

section: "Deploy & Operate"

permalink: /deploy/manual/provision-azure-resources/

menubar: docs_menu

---



[Back to manual setup hub]({{ '/setup_instructions_manual/' | relative_url }})



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

| **Azure Managed Redis**      | Balanced B0, high availability enabled (Optional)            | Required only if you need the performance, scalability, and distributed session support provided by a Redis cache. Replaces Azure Cache for Redis, which retires September 30, 2028. Azure Government and 21Vianet must still use Azure Cache for Redis Standard C0. |



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

    *   You will initialize indexes later ([Initializing indexes]({{ '/deploy/manual/application-specific-configuration/#initializing-indexes-in-azure-ai-search' | relative_url }})).

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

10. **Deploy Azure Managed Redis (Optional)**:

    *   Azure Cache for Redis Basic, Standard, and Premium retire on **September 30, 2028**. Deploy **Azure Managed Redis** unless you are in Azure Government or Azure operated by 21Vianet, where Azure Managed Redis is not available; in those clouds create an **Azure Cache for Redis** Standard C0 instead.

    *   Create an **Azure Managed Redis** resource.

    *   **Name**: Choose a unique name for your Redis instance (e.g., `simplechat-redis`).

    *   **Region**: Select the same region as your App Service for lowest latency.

    *   **Cache SKU**: `Balanced B0` (0.5 GB). This is the documented replacement for Azure Cache for Redis Standard C0. Choose a larger Balanced size if your peak used memory exceeds roughly 0.4 GB.

    *   **High availability**: Enabled. Disabling it removes the SLA, allows data loss during maintenance, and cannot be re-disabled after creation.

    *   **Clustering policy**: **Non-clustered**. SimpleChat uses a non-cluster-aware Redis client, and the portal default (OSS cluster) will not work with it. Non-clustered is valid up to 25 GB and can be changed later without recreating the database.

    *   **Networking**: Set to **Public** for initial setup. Azure Managed Redis does not support virtual network injection; use Azure Private Link if you need network isolation.

    *   **Authentication**:

        - For managed identity, keep **Microsoft Entra Authentication** enabled and assign the App Service managed identity the built-in `default` access policy on the database.

        - For key-based access, enable **Access Keys Authentication**, which is disabled by default on new instances.

    *   After Redis is created, note the **Host Name** (`<name>.<region>.redis.azure.net`) and the access keys if you are using key authentication.

    *   In Admin Settings, paste the host name into **Redis Server Host Name**. SimpleChat detects Azure Managed Redis from the host name suffix and connects on port 10000 automatically; Azure Cache for Redis host names resolve to port 6380.

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
