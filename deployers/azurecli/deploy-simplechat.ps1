<#
.SYNOPSIS
    Deploys the Simple Chat web application with Azure CLI and PowerShell.
.DESCRIPTION
    This PowerShell script uses Azure CLI commands to provision a set of resources.
    It is designed to be highly configurable. Please review and update the
    Configuration Variables section before running.

    Private networking scope:
        - This script can now create a deployment VNet for Simple Chat private networking,
          or reuse an existing VNet and existing subnets.
        - This script can create private endpoints for the core Simple Chat dependencies.
        - This script can create private DNS zones automatically, or reuse customer-managed
          private DNS zones by resource ID.
        - Each supported private DNS zone can optionally skip VNet link creation when a
          central networking team manages that link separately.
.NOTES
    Author: Microsoft Federal
    Date: 2025-05-14
    Version: 1.1
    Prerequisites:
        - Azure CLI installed and authenticated. Run `az login` and `az account set --subscription <YourSubscriptionId>`
        - Permissions to create resources in the specified subscription and Entra ID tenant.
        - If private networking is enabled, permissions to create or update VNets, subnets,
          private endpoints, private DNS zones, and private DNS VNet links.

    GitHub Url: https://github.com/microsoft/simplechat/

    Disclaimer:
        - This script is provided as-is and is not officially supported by Microsoft.
        - It is intended for educational purposes and may require modifications to fit specific use cases.
        - Ensure you have the necessary permissions and configurations in your Azure environment before deploying.

    Prerequisites:
        ***************************************************
        LOGIN NOTES
        ***************************************************
        - Azure CLI installed and authenticated. Run `az login` (see below)
        - Permissions to create resources in the specified subscription and Entra ID tenant.
        - For Azure Government, ensure you are logged into the correct environment:
            az cloud set --name AzureUSGovernment
            az login --scope https://management.core.usgovcloudapi.net//.default
            az login --scope https://graph.microsoft.us//.default

            - For Service Principal:
            az cache purge
            az account clear
            az cloud set --name AzureUSGovernment
            az login --scope https://management.core.usgovcloudapi.net//.default --service-principal --username <USERNAME> --password <PASSWORD> --tenant <TENANT ID>
            az login --scope https://graph.microsoft.us//.default --service-principal --username <USERNAME> --password <PASSWORD> --tenant <TENANT ID>
            az account set -s '<SUBSCRIPTION ID>'
        - For Azure Commercial, ensure you are logged into the correct environment:
            az cloud set --name AzureCloud
            az login --scope https://management.azure.com//.default
            az login --scope https://graph.microsoft.com//.default
#>
<#
============================================
Pre-deployment Notes
============================================
- Decide whether this script should create or reuse Azure OpenAI and whether it should create the default GPT and embedding model deployments.
- Have an Azure Container Registry (ACR) created, admin user enabled, and the name is set in the script.
- Decide whether this script should build the application image in ACR by using `az acr build`.
- LOGIN to Azure Cli before running this script. See "LOGIN NOTES" above.
- Review the private networking variables before running if you need private endpoints or VNet integration.
- If you reuse existing networking, supply both the App Service integration subnet ID and the private endpoint subnet ID.

============================================
Private networking prerequisites and planning questions
============================================

If you enable private networking, answer these questions before you run the script:

- Will this deployment create a new VNet, or reuse an existing enterprise VNet?
- If you are reusing a VNet, do you already have two separate subnets:
    - one subnet for App Service regional VNet integration
    - one subnet for private endpoints
- Is the App Service integration subnet delegated to `Microsoft.Web/serverFarms`?
- Will this script create private DNS zones, or will you reuse existing private DNS zones?
- If you reuse private DNS zones, are they already linked to the target VNet, or should this script create the VNet links?
- Are the required Azure resource providers registered in the target subscription, especially `Microsoft.Network`?

If you intend to place Simple Chat behind private networking, make sure the following prerequisites are already understood and planned:

- An existing VNet with dedicated subnets for:
    - App Service regional VNet integration
    - Private endpoints
- The App Service integration subnet must be delegated to `Microsoft.Web/serverFarms`.
- Private DNS zones must exist, or a central networking team must manage them, for the services you expose with private endpoints.
- Each required private DNS zone must be linked to the target VNet unless DNS is managed elsewhere.
- If DNS zones are not linked correctly, services may deploy but private name resolution will fail.

Common private DNS zones for Simple Chat private endpoint scenarios include:
- `privatelink.azurewebsites.net`
- `privatelink.documents.azure.com`
- `privatelink.blob.core.windows.net`
- `privatelink.search.windows.net`
- `privatelink.openai.azure.com`
- `privatelink.cognitiveservices.azure.com`
- `privatelink.vaultcore.azure.net`
- `privatelink.azurecr.io`

For Azure Government, use the corresponding sovereign-cloud private DNS zones such as:
- `privatelink.azurewebsites.us`
- `privatelink.documents.azure.us`
- `privatelink.blob.core.usgovcloudapi.net`
- `privatelink.search.azure.us`
- `privatelink.openai.azure.us`
- `privatelink.cognitiveservices.azure.us`
- `privatelink.vaultcore.azure.us`
- `privatelink.azurecr.us`

For detailed private networking guidance, see:
- `deployers/bicep/README.md`
- `docs/how-to/enterprise_networking.md`

============================================
Manual changes post-deployment.
============================================

STEP 1) Azure App Service > Authentication > Add identity provider
    - Setup identity per instructions in the README.md file. (Azure CLI cannot do this in gov yet)
        - Identity provider: Microsoft
        - Pick an existing app registration: Existing one created by this script.
        - Client secret expiration: You choose.
        - Issuer URL: https://login.microsoftonline.com/<tenant id>/v2.0 (replace tenant id)
        - leave everything else default.

STEP 2) Entra App Registration: 
    - Navigate to Api Permissions blade.
        - Click "Grant admin consent for <tenant name>" to grant the permissions.

        # This is done after you complete Step 1 above. Verify.
        Add the following Microsoft Graph permissions under "Other permissions granted for <tenant name>":
        - Group.Read.All, Delegated
        - offline_access, Delegated
        - openid, Delegated
        - People.Read.All, Delegated
        - User.ReadBasic.All, Delegate

STEP 3) App Service
    - restart the app service.
    - Navigate to Web UI url in a browser 
    - In the web ui, click on "Admin" > "app settings" to configure your app settings.

STEP 4) Configure Azure Search indexes
    #Deploy index as json files to Azure Search
    file: ai_search-index-group.json
    file: ai_search-index-user.json
    file: ai_search-index-public.json

STEP 5) Entra Security Groups
    - If you opted to have Security Groups created by this deployer, 
    you will need to assign them to the appropriate Enterprise Application
    and then add members to the Security Groups.

STEP 6) Cosmos DB
    - Ensure disableLocalAuth set to false (unless using RBAC, if using key based auth, disableLocalAuth must be false)
    - Ensure the firewall is set to all networks (unless using private endpoints)


STEP 7) Azure OpenAI 
    - Review the Azure OpenAI model deployments created by this script and adjust deployment type, capacity, or model versions if your environment requires different values.
    - If you reuse an existing Azure OpenAI resource, the script can create any missing default GPT and embedding deployments for you.
    - Configure a custom domain on your Azure OpenAI resources. Otherwise, you will not be able to retrieve your OpenAI models and add your OpenAI endpoint.

STEP 8) Test Web UI fully.
#>

$PSModuleAutoloadingPreference = "All"
Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

#---------------------------------------------------------------------------------------------
# Configuration Variables - MODIFY THESE VALUES AS NEEDED
#---------------------------------------------------------------------------------------------
$globalWhichAzurePlatform = "AzureCloud" # Set to "AzureUSGovernment" for Azure Government, "AzureCloud" for Azure Commercial, or "Custom" for a registered customer cloud
$param_AzureCliCustomCloudName = "" # Required when globalWhichAzurePlatform is Custom. Must match an az cloud show/list name.
$paramTenantId = "" # Tenant ID
$paramLocation = "EastUS2" # Primary Azure region for deployments (e.g., eastus, eastus2, usgovvirginia, usgovarizona, usgovtexas)
$paramResourceOwnerId = "" # used for tagging resources
$paramEnvironment = "dev"  # Environment identifier (e.g., dev, test, prod, uat)
$paramBaseName = "simplechatexp"  # A short base name for your organization or project (e.g., contoso1, projectx2)
$ACR_NAME = "registrysimplechatexperimental" # Replace with your ACR name (must be globally unique, lowercase alphanumeric)
$IMAGE_NAME = "simplechatexp:latest" # Repository[:tag] to build and deploy from ACR.
$param_BuildContainerImageWithAcr = $true # When true, run az acr build against the repo instead of requiring a prebuilt image.
$param_DockerfilePath = "application/single_app/Dockerfile"
$param_DockerBuildContextPath = "..\.." # Relative to this script. The default points to the repository root.
$param_PublishLatestImageTag = $true # Adds a latest tag when IMAGE_NAME uses a non-latest tag.

$param_UseExisting_OpenAi_Instance = $true
$param_Existing_AzureOpenAi_ResourceName = "aoai-global-team" # Azure OpenAI resource name
$param_Existing_AzureOpenAi_ResourceGroupName = "RG-AVD-East-Prod" # Azure OpenAI resource group name
$param_Existing_AzureOpenAi_SubscriptionId = "9698dd71-9367-49c2-bede-fd0deecfad62" # In case the resource is in another subscription
$param_DeployAzureOpenAiModels = $true # Creates the default GPT and embedding deployments when they do not already exist.
$param_AzureOpenAiDeploymentType = "" # Valid values: Standard, DatazoneStandard, GlobalStandard. Leave blank to be prompted in Azure Commercial. Azure Government always uses Standard.
$param_AzureOpenAiGptDeploymentName = "gpt-4o"
$param_AzureOpenAiGptModelName = "gpt-4o"
$param_AzureOpenAiGptModelVersion = "" # Leave blank to use the default for the selected cloud.
$param_AzureOpenAiGptDeploymentCapacity = 100
$param_AzureOpenAiEmbeddingDeploymentName = ""
$param_AzureOpenAiEmbeddingModelName = ""
$param_AzureOpenAiEmbeddingModelVersion = "" # Leave blank to use the default for the selected cloud and region.
$param_AzureOpenAiEmbeddingDeploymentCapacity = 80
$param_DeployVideoIndexerService = $false
$param_CustomGraphUrl = ""
$param_CustomIdentityUrl = ""
$param_CustomResourceManagerUrl = ""
$param_CustomCognitiveServicesScope = ""
$param_CustomSearchResourceUrl = ""
$param_CustomVideoIndexerEndpoint = ""
$param_CustomVideoIndexerArmApiVersion = ""

$paramCreateEntraSecurityGroups = $true # Set to true to create Entra ID security groups
$param_Existing_ResourceGroupName = "RG-SimpleChat-Experiemental" # Leave empty if not using an existing resource group name, one will be dynamically generated

# Private networking
$param_EnablePrivateNetworking = $false
$param_ExistingVirtualNetworkId = "" # Optional existing VNet resource ID to reuse.
$param_ExistingAppServiceSubnetId = "" # Required when reusing an existing VNet for App Service regional integration.
$param_ExistingPrivateEndpointSubnetId = "" # Required when reusing an existing VNet for private endpoints.
$param_PrivateNetworkAddressPrefixes = @("10.0.0.0/21")
$param_AppServiceIntegrationSubnetAddressPrefixes = @("10.0.0.0/24")
$param_PrivateEndpointSubnetAddressPrefixes = @("10.0.2.0/24")
$param_AllowedIpAddresses = @() # Optional admin IPs to keep for services that still support IP allow lists.
$param_ShowPrivateNetworkingChecklist = $true
$param_ConfirmPrivateNetworkingPlan = $false

# Optional per-zone private DNS overrides.
# Supported keys:
# keyVault, cosmosDb, containerRegistry, aiSearch, blobStorage, cognitiveServices, openAi, webSites
# Example:
# $param_PrivateDnsZoneConfigs = @{
#     openAi = @{
#         zoneResourceId = "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Network/privateDnsZones/privatelink.openai.azure.com"
#         createVNetLink = $false
#     }
#     webSites = @{
#         zoneResourceId = "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Network/privateDnsZones/privatelink.azurewebsites.net"
#     }
# }
$param_PrivateDnsZoneConfigs = @{}



#---------------------------------------------------------------------------------------------
# Script Variables - DO NOT MODIFY THESE VALUES
#---------------------------------------------------------------------------------------------

# Azure Government specific settings (DO NOT MODIFY)
if ($globalWhichAzurePlatform -eq "AzureCloud") {
    $paramCosmosDbUrlTemplate = "https://{0}.documents.azure.com:443/"
    $ACR_BASE_URL = "$ACR_NAME.azurecr.io"
    $paramRegistryServer = "https://$ACR_NAME.azurecr.io"
    $APPREG_REDIRECT_URI = "https://{0}.azurewebsites.net/.auth/login/aad/callback"
    $APPREG_REDIRECT_URI1 = "https://{0}.azurewebsites.net/getAToken"
    $APPREG_LOGOUT_URL = "https://{0}.azurewebsites.net/logout"
    $paramGraphUrl = "https://graph.microsoft.com"
    $paramArmUrl = "https://management.azure.com/"
    $param_AzureOpenAi_Url = "https://{0}.openai.azure.com/"
    $param_AiSearch_Url = "https://{0}.search.windows.net"
    $param_AppService_Environment = "public"
    $param_VideoIndexerEndpoint = "https://api.videoindexer.ai"
    $param_VideoIndexerArmApiVersion = "2025-04-01"
    $script:PrivateDnsZoneNames = @{
        aiSearch          = "privatelink.search.windows.net"
        blobStorage       = "privatelink.blob.core.windows.net"
        cognitiveServices = "privatelink.cognitiveservices.azure.com"
        containerRegistry = "privatelink.azurecr.io"
        cosmosDb          = "privatelink.documents.azure.com"
        keyVault          = "privatelink.vaultcore.azure.net"
        openAi            = "privatelink.openai.azure.com"
        webSites          = "privatelink.azurewebsites.net"
    }
} elseif ($globalWhichAzurePlatform -eq "AzureUSGovernment") {
    $paramCosmosDbUrlTemplate = "https://{0}.documents.azure.us:443/"
    $ACR_BASE_URL = "$ACR_NAME.azurecr.us"
    $paramRegistryServer = "https://$ACR_NAME.azurecr.us"
    $APPREG_REDIRECT_URI = "https://{0}.azurewebsites.us/.auth/login/aad/callback"
    $APPREG_REDIRECT_URI1 = "https://{0}.azurewebsites.us/getAToken"
    $APPREG_LOGOUT_URL = "https://{0}.azurewebsites.us/logout"
    $paramGraphUrl = "https://graph.microsoft.us"
    $paramArmUrl = "https://management.usgovcloudapi.net/"
    $param_AzureOpenAi_Url = "https://{0}.openai.azure.us/"
    $param_AiSearch_Url = "https://{0}.search.azure.us"
    $param_AppService_Environment = "usgovernment"
    $param_VideoIndexerEndpoint = "https://api.videoindexer.ai.azure.us"
    $param_VideoIndexerArmApiVersion = "2024-01-01"
    $script:PrivateDnsZoneNames = @{
        aiSearch          = "privatelink.search.azure.us"
        blobStorage       = "privatelink.blob.core.usgovcloudapi.net"
        cognitiveServices = "privatelink.cognitiveservices.azure.us"
        containerRegistry = "privatelink.azurecr.us"
        cosmosDb          = "privatelink.documents.azure.us"
        keyVault          = "privatelink.vaultcore.azure.us"
        openAi            = "privatelink.openai.azure.us"
        webSites          = "privatelink.azurewebsites.us"
    }
} elseif ($globalWhichAzurePlatform -eq "Custom") {
    $paramCosmosDbUrlTemplate = "https://{0}.documents.azure.com:443/"
    $ACR_BASE_URL = "$ACR_NAME.azurecr.io"
    $paramRegistryServer = "https://$ACR_NAME.azurecr.io"
    $APPREG_REDIRECT_URI = "https://{0}.azurewebsites.net/.auth/login/aad/callback"
    $APPREG_REDIRECT_URI1 = "https://{0}.azurewebsites.net/getAToken"
    $APPREG_LOGOUT_URL = "https://{0}.azurewebsites.net/logout"
    $paramGraphUrl = $param_CustomGraphUrl
    $paramArmUrl = $param_CustomResourceManagerUrl
    $param_AzureOpenAi_Url = "https://{0}.openai.azure.com/"
    $param_AiSearch_Url = "https://{0}.search.windows.net"
    $param_AppService_Environment = "custom"
    $param_VideoIndexerEndpoint = if ([string]::IsNullOrWhiteSpace($param_CustomVideoIndexerEndpoint)) { "https://api.videoindexer.ai" } else { $param_CustomVideoIndexerEndpoint }
    $param_VideoIndexerArmApiVersion = if ([string]::IsNullOrWhiteSpace($param_CustomVideoIndexerArmApiVersion)) { "2025-04-01" } else { $param_CustomVideoIndexerArmApiVersion }
    $script:PrivateDnsZoneNames = @{
        aiSearch          = "privatelink.search.windows.net"
        blobStorage       = "privatelink.blob.core.windows.net"
        cognitiveServices = "privatelink.cognitiveservices.azure.com"
        containerRegistry = "privatelink.azurecr.io"
        cosmosDb          = "privatelink.documents.azure.com"
        keyVault          = "privatelink.vaultcore.azure.net"
        openAi            = "privatelink.openai.azure.com"
        webSites          = "privatelink.azurewebsites.net"
    }
} else {
    Write-Error "Invalid Azure platform specified. Please set to 'AzureUSGovernment', 'AzureCloud', or 'Custom'"
    exit 1
}

$paramDateTime_ScriptStart = Get-Date
$paramDateTimeStamp = ($paramDateTime_ScriptStart).ToString("yyyy-MM-dd HH:mm:ss")

$script:SupportedPrivateDnsZoneKeys = @("keyVault", "cosmosDb", "containerRegistry", "aiSearch", "blobStorage", "cognitiveServices", "openAi", "webSites")
$script:PrivateDnsZoneLinkSuffixes = @{
    aiSearch          = "searchService"
    blobStorage       = "storage"
    cognitiveServices = "docIntelService"
    containerRegistry = "acr"
    cosmosDb          = "cosmosDb"
    keyVault          = "kv"
    openAi            = "openAiService"
    webSites          = "webApp"
}
$script:UseExistingPrivateNetwork = $false
$script:ResolvedVirtualNetworkId = ""
$script:ResolvedAppServiceSubnetId = ""
$script:ResolvedPrivateEndpointSubnetId = ""
$script:CurrentSubscriptionId = ""
$script:SupportedOpenAiDeploymentTypes = @("Standard", "DatazoneStandard", "GlobalStandard")
$script:ResolvedOpenAiDeploymentType = ""

if ([string]::IsNullOrWhiteSpace($param_AzureOpenAiGptModelVersion)) {
    if ($globalWhichAzurePlatform -eq "AzureUSGovernment") {
        $param_AzureOpenAiGptModelVersion = "2024-05-13"
    } else {
        $param_AzureOpenAiGptModelVersion = "2024-11-20"
    }
}

if ([string]::IsNullOrWhiteSpace($param_AzureOpenAiEmbeddingModelName)) {
    if ($globalWhichAzurePlatform -eq "AzureUSGovernment" -and $paramLocation -eq "usgovvirginia") {
        $param_AzureOpenAiEmbeddingModelName = "text-embedding-ada-002"
    } else {
        $param_AzureOpenAiEmbeddingModelName = "text-embedding-3-small"
    }
}

if ([string]::IsNullOrWhiteSpace($param_AzureOpenAiEmbeddingDeploymentName)) {
    $param_AzureOpenAiEmbeddingDeploymentName = $param_AzureOpenAiEmbeddingModelName
}

if ([string]::IsNullOrWhiteSpace($param_AzureOpenAiEmbeddingModelVersion)) {
    if ($param_AzureOpenAiEmbeddingModelName -eq "text-embedding-ada-002") {
        $param_AzureOpenAiEmbeddingModelVersion = "2"
    } else {
        $param_AzureOpenAiEmbeddingModelVersion = "1"
    }
}

$tags = @{
    Environment     = $paramEnvironment
    Owner           = $paramResourceOwnerId
    CreatedDateTime = $paramDateTimeStamp
    Project         = "SimpleChat"
}
# Convert the hashtable to a JSON string
$tagsJson = ($tags | ConvertTo-Json -Compress)

# --- Naming Convention Components ---
# You can customize these suffixes or define full names if preferred.
# Format: $paramBaseName-$paramEnvironment-$resourceTypeSuffix
$paramResourceGroupNameSuffix = "rg"
$paramEntraGroupNameSuffix = "sg"
$paramEntraAppRegistrationSuffix = "ar"
$paramAppServicePlanSuffix = "asp"
$paramAppServiceSuffix = "app" # Note: App Service names need to be globally unique for *.azurewebsites.us
$paramAppInsightsSuffix = "ai"
$paramCosmosDbSuffix = "cosmos" # Note: Cosmos DB account names need to be globally unique
$paramOpenAISuffix = "oai"
$paramDocIntelSuffix = "docintel"
$paramKeyVaultSuffix = "kv" # Note: Key Vault names need to be globally unique
$paramLogAnalyticsSuffix = "la"
$paramManagedIdentitySuffix = "id"
$paramSearchServiceSuffix = "search" # Note: Search service names need to be globally unique
$paramVideoIndexerSuffix = "video"
$paramStorageAccountSuffix = "sa" # Note: Storage account names need to be globally unique, lowercase alphanumeric, 3-24 chars
#$paramContainerRegistrySuffix = "acr" # Note: ACR names need to be globally unique, lowercase alphanumeric

# --- Resource Specific Settings ---

# App Service Plan
$paramAppServicePlanSku = "P1V3" # Basic tier, 1 core, 1.75GB RAM. For US Gov, check available SKUs. (e.g., B1, P1V3, S1, I1V2)

# App Service (Web App)
#$paramAppServiceRuntime = "DOTNETCORE|8.0" # Example runtime. Others: "NODE|18-lts", "PYTHON|3.11", "JAVA|17-java17"

# Storage Account
$paramStorageSku = "Standard_LRS" # Locally-redundant storage. For US Gov, check options. (e.g., Standard_GRS, Standard_RAGRS)
$paramStorageKind = "StorageV2"
$paramStorageAccessTier = "Hot"

# Cosmos DB
$paramCosmosDbKind = "GlobalDocumentDB" # For SQL API. Other: MongoDB, Cassandra, Gremlin, Table

# Azure OpenAI & Document Intelligence (Cognitive Services)
$paramCognitiveServicesSku = "S0" # Standard tier. Check availability for OpenAI and Doc Intel in Azure Gov.

# Container Registry
#$paramAcrSku = "Basic" # Other options: Standard, Premium

# Search Service
$paramSearchSku = "basic" # Other options: standard, standard2, standard3. 'free' is not available in all regions or for all subscription types.
$paramSearchReplicaCount = 1
$paramSearchPartitionCount = 1

# Key Vault
$paramKeyVaultSku = "standard" # Or "premium"

# Log Analytics Workspace
$paramLogAnalyticsSku = "PerGB2018" # Pay-as-you-go SKU

# Entra Security Group
#$paramEntraGroupMailNickname = "$($paramBaseName)-$($paramEnvironment)-entra-group" # Must be unique in the tenant


#---------------------------------------------------------------------------------------------
# Functions Declarations
#---------------------------------------------------------------------------------------------
Function Get-ResourceName {
    param(
        [string]$ResourceTypeSuffix
    )
    return "$($paramBaseName)-$($paramEnvironment)-$($ResourceTypeSuffix)".ToLower()
}

Function Get-GloballyUniqueResourceName {
    param(
        [string]$ResourceTypeSuffix,
        [string]$ExtraRandomChars = "" # Add a few random chars if needed, though base/env should be distinct
    )
    # For some resources, names need to be globally unique and often have stricter character limits/rules.
    # Storage accounts and ACR: lowercase alphanumeric
    # Key Vault, Cosmos DB, App Service, Search: globally unique, typically allow hyphens
    $name = "$($paramBaseName)$($paramEnvironment)$($ResourceTypeSuffix)$($ExtraRandomChars)".ToLower() -replace "[^a-z0-9]", ""
    return $name
}

function Ensure-AzureCliAuthenticated {
    if (-not (Get-Command "az" -ErrorAction SilentlyContinue)) {
        Write-Error "Azure CLI is not installed. Please install it before running this script."
        exit 1
    }

    $expectedCloudName = switch ($globalWhichAzurePlatform) {
        'AzureCloud' { 'AzureCloud' }
        'AzureUSGovernment' { 'AzureUSGovernment' }
        'Custom' { $param_AzureCliCustomCloudName }
        default { $null }
    }

    if (-not $expectedCloudName) {
        Write-Error "Automatic Azure CLI login requires AzureCloud, AzureUSGovernment, or a registered custom cloud name via param_AzureCliCustomCloudName. Current platform: $globalWhichAzurePlatform"
        exit 1
    }

    $currentCloudName = az cloud show --query name --output tsv 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($currentCloudName)) {
        Write-Warning "Unable to determine the current Azure CLI cloud. Setting it to '$expectedCloudName'."
        az cloud set --name $expectedCloudName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to set Azure CLI cloud to '$expectedCloudName'."
            exit 1
        }
    } elseif ($currentCloudName -ne $expectedCloudName) {
        Write-Host "Switching Azure CLI cloud from '$currentCloudName' to '$expectedCloudName'..." -ForegroundColor Yellow
        az cloud set --name $expectedCloudName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to set Azure CLI cloud to '$expectedCloudName'."
            exit 1
        }
    }

    az account show --output none 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Azure CLI authentication found." -ForegroundColor Yellow
        return
    }

    Write-Host "Azure CLI is not authenticated. Running 'az login'..." -ForegroundColor Yellow
    az login | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Azure CLI login failed. Run 'az login' manually and try again."
        exit 1
    }

    az account show --output none 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Azure CLI authentication could not be verified after login."
        exit 1
    }
}

function Resolve-ContainerImageInfo {
    param(
        [string]$ImageName
    )

    if ([string]::IsNullOrWhiteSpace($ImageName)) {
        Write-Error "IMAGE_NAME must not be empty."
        exit 1
    }

    $lastSlashIndex = $ImageName.LastIndexOf('/')
    $lastColonIndex = $ImageName.LastIndexOf(':')

    if ($lastColonIndex -gt $lastSlashIndex) {
        $repository = $ImageName.Substring(0, $lastColonIndex)
        $tag = $ImageName.Substring($lastColonIndex + 1)
    } else {
        $repository = $ImageName
        $tag = "latest"
    }

    if ([string]::IsNullOrWhiteSpace($repository) -or [string]::IsNullOrWhiteSpace($tag)) {
        Write-Error "IMAGE_NAME must be in the form repository or repository:tag. Current value: $ImageName"
        exit 1
    }

    return [PSCustomObject]@{
        Repository = $repository
        Tag        = $tag
        FullName   = "$repository`:$tag"
    }
}

function Get-DefaultOpenAiDeploymentType {
    if ($globalWhichAzurePlatform -eq 'AzureUSGovernment') {
        return 'Standard'
    }

    return 'GlobalStandard'
}

function Select-OpenAiDeploymentType {
    param(
        [string]$CurrentValue,
        [string]$PromptMessage = "Select the Azure OpenAI deployment type to use"
    )

    if ($globalWhichAzurePlatform -eq 'AzureUSGovernment') {
        Write-Host "Azure Government uses the Azure OpenAI deployment type 'Standard'." -ForegroundColor Yellow
        return 'Standard'
    }

    $defaultType = if ([string]::IsNullOrWhiteSpace($CurrentValue)) { Get-DefaultOpenAiDeploymentType } else { $CurrentValue }

    while ($true) {
        Write-Host "`n$PromptMessage" -ForegroundColor Cyan
        for ($index = 0; $index -lt $script:SupportedOpenAiDeploymentTypes.Count; $index++) {
            $deploymentType = $script:SupportedOpenAiDeploymentTypes[$index]
            $defaultMarker = if ($deploymentType -eq $defaultType) { ' (default)' } else { '' }
            Write-Host "[$($index + 1)] $deploymentType$defaultMarker"
        }

        $selection = Read-Host "Enter 1-$($script:SupportedOpenAiDeploymentTypes.Count) or press Enter for '$defaultType'"
        if ([string]::IsNullOrWhiteSpace($selection)) {
            return $defaultType
        }

        if ($selection -match '^\d+$') {
            $selectionIndex = [int]$selection - 1
            if ($selectionIndex -ge 0 -and $selectionIndex -lt $script:SupportedOpenAiDeploymentTypes.Count) {
                return $script:SupportedOpenAiDeploymentTypes[$selectionIndex]
            }
        }

        foreach ($deploymentType in $script:SupportedOpenAiDeploymentTypes) {
            if ($selection.Equals($deploymentType, [System.StringComparison]::OrdinalIgnoreCase)) {
                return $deploymentType
            }
        }

        Write-Warning "Invalid Azure OpenAI deployment type selection: '$selection'."
    }
}

function Resolve-OpenAiDeploymentType {
    param(
        [switch]$ForcePrompt
    )

    if ($globalWhichAzurePlatform -eq 'AzureUSGovernment') {
        $script:ResolvedOpenAiDeploymentType = 'Standard'
        return $script:ResolvedOpenAiDeploymentType
    }

    if (-not $ForcePrompt -and -not [string]::IsNullOrWhiteSpace($script:ResolvedOpenAiDeploymentType)) {
        return $script:ResolvedOpenAiDeploymentType
    }

    if (-not $ForcePrompt -and -not [string]::IsNullOrWhiteSpace($param_AzureOpenAiDeploymentType)) {
        foreach ($deploymentType in $script:SupportedOpenAiDeploymentTypes) {
            if ($param_AzureOpenAiDeploymentType.Equals($deploymentType, [System.StringComparison]::OrdinalIgnoreCase)) {
                $script:ResolvedOpenAiDeploymentType = $deploymentType
                return $script:ResolvedOpenAiDeploymentType
            }
        }

        Write-Error "Invalid param_AzureOpenAiDeploymentType value '$param_AzureOpenAiDeploymentType'. Valid values: $($script:SupportedOpenAiDeploymentTypes -join ', ')."
        exit 1
    }

    $script:ResolvedOpenAiDeploymentType = Select-OpenAiDeploymentType -CurrentValue $script:ResolvedOpenAiDeploymentType
    return $script:ResolvedOpenAiDeploymentType
}

function Get-OpenAiModelDeploymentDefinitions {
    $deploymentType = Resolve-OpenAiDeploymentType

    return @(
        [PSCustomObject]@{
            Kind           = 'GPT'
            DeploymentName = $param_AzureOpenAiGptDeploymentName
            ModelName      = $param_AzureOpenAiGptModelName
            ModelVersion   = $param_AzureOpenAiGptModelVersion
            ModelFormat    = 'OpenAI'
            SkuName        = $deploymentType
            SkuCapacity    = $param_AzureOpenAiGptDeploymentCapacity
        },
        [PSCustomObject]@{
            Kind           = 'Embeddings'
            DeploymentName = $param_AzureOpenAiEmbeddingDeploymentName
            ModelName      = $param_AzureOpenAiEmbeddingModelName
            ModelVersion   = $param_AzureOpenAiEmbeddingModelVersion
            ModelFormat    = 'OpenAI'
            SkuName        = $deploymentType
            SkuCapacity    = $param_AzureOpenAiEmbeddingDeploymentCapacity
        }
    )
}

function Ensure-OpenAiModelDeployment {
    param(
        [string]$AccountName,
        [string]$ResourceGroupName,
        [string]$SubscriptionId,
        [pscustomobject]$ModelDeployment
    )

    $existingDeployment = az cognitiveservices account deployment show \
        --name $AccountName \
        --resource-group $ResourceGroupName \
        --deployment-name $ModelDeployment.DeploymentName \
        --subscription $SubscriptionId \
        --query "name" \
        --output tsv 2>$null

    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($existingDeployment)) {
        Write-Host "Azure OpenAI $($ModelDeployment.Kind) deployment '$($ModelDeployment.DeploymentName)' already exists." -ForegroundColor Yellow
        return $true
    }

    $currentSkuName = $ModelDeployment.SkuName

    while ($true) {
        Write-Host "`n=====> Creating Azure OpenAI $($ModelDeployment.Kind) deployment '$($ModelDeployment.DeploymentName)' using deployment type '$currentSkuName'..."
        az cognitiveservices account deployment create \
            --name $AccountName \
            --resource-group $ResourceGroupName \
            --deployment-name $ModelDeployment.DeploymentName \
            --model-name $ModelDeployment.ModelName \
            --model-version $ModelDeployment.ModelVersion \
            --model-format $ModelDeployment.ModelFormat \
            --sku-name $currentSkuName \
            --sku-capacity $ModelDeployment.SkuCapacity \
            --subscription $SubscriptionId | Out-Null

        if ($LASTEXITCODE -eq 0) {
            Write-Host "Azure OpenAI $($ModelDeployment.Kind) deployment '$($ModelDeployment.DeploymentName)' created successfully." -ForegroundColor Green
            return $true
        }

        Write-Warning "Failed to create Azure OpenAI $($ModelDeployment.Kind) deployment '$($ModelDeployment.DeploymentName)' with deployment type '$currentSkuName'."

        if ($globalWhichAzurePlatform -eq 'AzureUSGovernment') {
            return $false
        }

        $retryChoice = Read-Host "Try a different Azure OpenAI deployment type for '$($ModelDeployment.DeploymentName)'? Enter Y to retry or press Enter to skip"
        if ($retryChoice -notmatch '^(y|yes)$') {
            return $false
        }

        $currentSkuName = Select-OpenAiDeploymentType -CurrentValue $currentSkuName -PromptMessage "Select a different Azure OpenAI deployment type for '$($ModelDeployment.DeploymentName)'"
        $script:ResolvedOpenAiDeploymentType = $currentSkuName
    }
}

function Invoke-AcrContainerBuild {
    param(
        [string]$RegistryName,
        [string]$ImageName,
        [string]$DockerfilePath,
        [string]$BuildContextPath,
        [bool]$PublishLatestTag
    )

    $containerImageInfo = Resolve-ContainerImageInfo -ImageName $ImageName
    $resolvedContextPath = Resolve-Path -Path (Join-Path $PSScriptRoot $BuildContextPath) -ErrorAction Stop
    $dockerfileFullPath = Join-Path $resolvedContextPath $DockerfilePath

    if (-not (Test-Path -Path $dockerfileFullPath)) {
        Write-Error "Dockerfile not found at '$dockerfileFullPath'."
        exit 1
    }

    $acrBuildArguments = @(
        'acr', 'build',
        '--registry', $RegistryName,
        '--file', $DockerfilePath,
        '--image', $containerImageInfo.FullName
    )

    if ($PublishLatestTag -and $containerImageInfo.Tag -ne 'latest') {
        $acrBuildArguments += @('--image', "$($containerImageInfo.Repository):latest")
    }

    $acrBuildArguments += $resolvedContextPath.Path

    Write-Host "`n=====> Building container image in Azure Container Registry via ACR Tasks..."
    Write-Host "Registry: $RegistryName"
    Write-Host "Image: $($containerImageInfo.FullName)"
    if ($PublishLatestTag -and $containerImageInfo.Tag -ne 'latest') {
        Write-Host "Additional tag: $($containerImageInfo.Repository):latest"
    }
    Write-Host "Dockerfile: $DockerfilePath"
    Write-Host "Build context: $($resolvedContextPath.Path)"

    & az @acrBuildArguments
    if ($LASTEXITCODE -ne 0) {
        Write-Error "ACR image build failed for '$($containerImageInfo.FullName)'."
        exit 1
    }
}

function CosmosDb_CreateContainer($databaseName, $containerName)
{
    $partitionKeyPath = "/partitionKey"
    $throughput = 4000

    Write-Host "`n=====> Creating Azure Cosmos DB database container: $containerName ..."
    $container = az cosmosdb sql container show `
        --account-name $script:cosmosDbName `
        --resource-group $script:resourceGroupName `
        --database-name $databaseName `
        --name $containerName `
        --query "name" `
        --output tsv 2>$null

    if (-not $container) {
        Write-Host "Container '$containerName' does not exist. Creating..."
        az cosmosdb sql container create `
            --account-name $script:cosmosDbName `
            --resource-group $script:resourceGroupName `
            --database-name $databaseName `
            --name $containerName `
            --partition-key-path $partitionKeyPath `
            --throughput $throughput
    } else {
        Write-Host "Container '$containerName' already exists."
    }
}

function Get-SubnetContext {
    param(
        [string]$SubnetId
    )

    if ([string]::IsNullOrWhiteSpace($SubnetId)) {
        return $null
    }

    $match = [regex]::Match(
        $SubnetId,
        '^/subscriptions/(?<subscriptionId>[^/]+)/resourceGroups/(?<resourceGroupName>[^/]+)/providers/Microsoft\.Network/virtualNetworks/(?<virtualNetworkName>[^/]+)/subnets/(?<subnetName>[^/]+)$',
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    )

    if (-not $match.Success) {
        Write-Error "Invalid subnet resource ID format: $SubnetId"
        exit 1
    }

    return [PSCustomObject]@{
        SubscriptionId     = $match.Groups['subscriptionId'].Value
        ResourceGroupName  = $match.Groups['resourceGroupName'].Value
        VirtualNetworkName = $match.Groups['virtualNetworkName'].Value
        SubnetName         = $match.Groups['subnetName'].Value
        VirtualNetworkId   = "/subscriptions/$($match.Groups['subscriptionId'].Value)/resourceGroups/$($match.Groups['resourceGroupName'].Value)/providers/Microsoft.Network/virtualNetworks/$($match.Groups['virtualNetworkName'].Value)"
    }
}

function Get-VirtualNetworkContext {
    param(
        [string]$VirtualNetworkId
    )

    if ([string]::IsNullOrWhiteSpace($VirtualNetworkId)) {
        return $null
    }

    $match = [regex]::Match(
        $VirtualNetworkId,
        '^/subscriptions/(?<subscriptionId>[^/]+)/resourceGroups/(?<resourceGroupName>[^/]+)/providers/Microsoft\.Network/virtualNetworks/(?<virtualNetworkName>[^/]+)$',
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    )

    if (-not $match.Success) {
        Write-Error "Invalid virtual network resource ID format: $VirtualNetworkId"
        exit 1
    }

    return [PSCustomObject]@{
        SubscriptionId     = $match.Groups['subscriptionId'].Value
        ResourceGroupName  = $match.Groups['resourceGroupName'].Value
        VirtualNetworkName = $match.Groups['virtualNetworkName'].Value
        VirtualNetworkId   = $VirtualNetworkId
    }
}

function Get-PrivateDnsZoneContext {
    param(
        [string]$ZoneResourceId
    )

    if ([string]::IsNullOrWhiteSpace($ZoneResourceId)) {
        return $null
    }

    $match = [regex]::Match(
        $ZoneResourceId,
        '^/subscriptions/(?<subscriptionId>[^/]+)/resourceGroups/(?<resourceGroupName>[^/]+)/providers/Microsoft\.Network/privateDnsZones/(?<zoneName>[^/]+)$',
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    )

    if (-not $match.Success) {
        Write-Error "Invalid private DNS zone resource ID format: $ZoneResourceId"
        exit 1
    }

    return [PSCustomObject]@{
        SubscriptionId    = $match.Groups['subscriptionId'].Value
        ResourceGroupName = $match.Groups['resourceGroupName'].Value
        ZoneName          = $match.Groups['zoneName'].Value
        ZoneResourceId    = $ZoneResourceId
    }
}

function Get-PrivateDnsZoneConfig {
    param(
        [string]$ZoneKey
    )

    $zoneResourceId = ""
    $createVNetLink = $true

    if ($param_PrivateDnsZoneConfigs -and $param_PrivateDnsZoneConfigs.ContainsKey($ZoneKey)) {
        $zoneConfig = $param_PrivateDnsZoneConfigs[$ZoneKey]
        if ($zoneConfig) {
            if ($zoneConfig.ContainsKey('zoneResourceId') -and -not [string]::IsNullOrWhiteSpace($zoneConfig.zoneResourceId)) {
                $zoneResourceId = $zoneConfig.zoneResourceId
            }

            if ($zoneConfig.ContainsKey('createVNetLink')) {
                $createVNetLink = [bool]$zoneConfig.createVNetLink
            }
        }
    }

    return [PSCustomObject]@{
        ZoneKey        = $ZoneKey
        ZoneName       = $script:PrivateDnsZoneNames[$ZoneKey]
        ZoneResourceId = $zoneResourceId
        CreateVNetLink = $createVNetLink
    }
}

function Ensure-ProviderRegistered {
    param(
        [string]$ProviderNamespace
    )

    $providerState = az provider show --namespace $ProviderNamespace --query "registrationState" --output tsv
    if ($providerState -ne "Registered") {
        Write-Host "Registering provider namespace: $ProviderNamespace"
        az provider register --namespace $ProviderNamespace | Out-Null

        while ($providerState -ne "Registered") {
            Start-Sleep -Seconds 5
            $providerState = az provider show --namespace $ProviderNamespace --query "registrationState" --output tsv
        }
    }
}

function Show-PrivateNetworkingChecklist {
    if (-not $param_EnablePrivateNetworking) {
        return
    }

    Write-Host "`n============================================" -ForegroundColor Cyan
    Write-Host "Private Networking Deployment Checklist" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan

    if ($script:UseExistingPrivateNetwork) {
        Write-Host "Mode: Reuse existing virtual network" -ForegroundColor Yellow
        Write-Host "- Virtual network: $($script:ResolvedVirtualNetworkId)"
        Write-Host "- App Service subnet: $($script:ResolvedAppServiceSubnetId)"
        Write-Host "- Private endpoint subnet: $($script:ResolvedPrivateEndpointSubnetId)"
    } else {
        Write-Host "Mode: Create new virtual network" -ForegroundColor Yellow
        Write-Host "- VNet address space: $($param_PrivateNetworkAddressPrefixes -join ', ')"
        Write-Host "- App Service subnet prefixes: $($param_AppServiceIntegrationSubnetAddressPrefixes -join ', ')"
        Write-Host "- Private endpoint subnet prefixes: $($param_PrivateEndpointSubnetAddressPrefixes -join ', ')"
    }

    if ($param_AllowedIpAddresses.Count -gt 0) {
        Write-Host "- Allowed admin IP addresses: $($param_AllowedIpAddresses -join ', ')"
    } else {
        Write-Host "- Allowed admin IP addresses: none configured"
    }

    Write-Host "`nPrivate DNS zone plan:" -ForegroundColor Yellow
    foreach ($zoneKey in $script:SupportedPrivateDnsZoneKeys) {
        $zoneConfig = Get-PrivateDnsZoneConfig -ZoneKey $zoneKey
        if ([string]::IsNullOrWhiteSpace($zoneConfig.ZoneResourceId)) {
            $zoneAction = "create in deployment resource group"
        } else {
            $zoneAction = "reuse existing zone"
        }

        if ($zoneConfig.CreateVNetLink) {
            $linkAction = "ensure VNet link"
        } else {
            $linkAction = "do not create VNet link"
        }

        Write-Host "- $zoneKey => $($zoneConfig.ZoneName) | $zoneAction | $linkAction"
        if (-not [string]::IsNullOrWhiteSpace($zoneConfig.ZoneResourceId)) {
            Write-Host "  zoneResourceId: $($zoneConfig.ZoneResourceId)"
        }
    }

    Write-Host "`nQuestions to confirm:" -ForegroundColor Yellow
    Write-Host "- Is the App Service integration subnet delegated to Microsoft.Web/serverFarms?"
    Write-Host "- If you reuse private DNS zones and createVNetLink is false, are the required VNet links already in place?"
    Write-Host "- Will administrators reach the application and private endpoints through the intended enterprise network path?"
}

function Test-PrivateNetworkingConfiguration {
    if (-not $param_EnablePrivateNetworking) {
        return
    }

    foreach ($zoneKey in $param_PrivateDnsZoneConfigs.Keys) {
        if ($script:SupportedPrivateDnsZoneKeys -notcontains $zoneKey) {
            Write-Error "Unsupported private DNS zone config key '$zoneKey'. Supported keys: $($script:SupportedPrivateDnsZoneKeys -join ', ')"
            exit 1
        }
    }

    $script:UseExistingPrivateNetwork =
        (-not [string]::IsNullOrWhiteSpace($param_ExistingVirtualNetworkId)) -or
        (-not [string]::IsNullOrWhiteSpace($param_ExistingAppServiceSubnetId)) -or
        (-not [string]::IsNullOrWhiteSpace($param_ExistingPrivateEndpointSubnetId))

    if ($script:UseExistingPrivateNetwork) {
        if ([string]::IsNullOrWhiteSpace($param_ExistingAppServiceSubnetId) -or [string]::IsNullOrWhiteSpace($param_ExistingPrivateEndpointSubnetId)) {
            Write-Error "When reusing an existing virtual network, both param_ExistingAppServiceSubnetId and param_ExistingPrivateEndpointSubnetId must be provided."
            exit 1
        }

        $appServiceSubnetContext = Get-SubnetContext -SubnetId $param_ExistingAppServiceSubnetId
        $privateEndpointSubnetContext = Get-SubnetContext -SubnetId $param_ExistingPrivateEndpointSubnetId

        if ($appServiceSubnetContext.VirtualNetworkId -ne $privateEndpointSubnetContext.VirtualNetworkId) {
            Write-Error "The existing App Service subnet and private endpoint subnet must belong to the same virtual network."
            exit 1
        }

        if (-not [string]::IsNullOrWhiteSpace($param_ExistingVirtualNetworkId) -and ($param_ExistingVirtualNetworkId -ne $appServiceSubnetContext.VirtualNetworkId)) {
            Write-Error "param_ExistingVirtualNetworkId does not match the virtual network inferred from param_ExistingAppServiceSubnetId."
            exit 1
        }

        $delegationCount = az network vnet subnet show --ids $param_ExistingAppServiceSubnetId --query "delegations[?serviceName=='Microsoft.Web/serverFarms'] | length(@)" --output tsv
        if ($LASTEXITCODE -ne 0 -or [int]$delegationCount -lt 1) {
            Write-Error "The existing App Service integration subnet must be delegated to Microsoft.Web/serverFarms before running this deployment."
            exit 1
        }

        $script:ResolvedVirtualNetworkId = $appServiceSubnetContext.VirtualNetworkId
        $script:ResolvedAppServiceSubnetId = $param_ExistingAppServiceSubnetId
        $script:ResolvedPrivateEndpointSubnetId = $param_ExistingPrivateEndpointSubnetId
    }

    if ($param_ShowPrivateNetworkingChecklist) {
        Show-PrivateNetworkingChecklist
    }

    if ($param_ConfirmPrivateNetworkingPlan) {
        $confirmation = Read-Host "Continue with the private networking plan above? Enter Y to continue"
        if ($confirmation -notin @('Y', 'y', 'Yes', 'YES', 'yes')) {
            Write-Host "Deployment cancelled by user." -ForegroundColor Yellow
            exit 0
        }
    }
}

function Ensure-PrivateNetworkingInfrastructure {
    if (-not $param_EnablePrivateNetworking) {
        return
    }

    Ensure-ProviderRegistered -ProviderNamespace "Microsoft.Network"

    if ($script:UseExistingPrivateNetwork) {
        Write-Host "`n=====> Reusing existing virtual network and subnets for private networking..."
        return
    }

    $virtualNetworkName = Get-ResourceName -ResourceTypeSuffix "vnet"
    $virtualNetwork = az network vnet show --resource-group $resourceGroupName --name $virtualNetworkName --output json 2>$null | ConvertFrom-Json
    if (-not $virtualNetwork) {
        Write-Host "`n=====> Creating virtual network: $virtualNetworkName"
        az network vnet create --resource-group $resourceGroupName --name $virtualNetworkName --location $paramLocation --address-prefixes @($param_PrivateNetworkAddressPrefixes) | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create virtual network '$virtualNetworkName'."; exit 1 }
    } else {
        Write-Host "Virtual network '$virtualNetworkName' already exists."
    }

    $appServiceSubnetName = "AppServiceIntegration"
    $privateEndpointSubnetName = "PrivateEndpoints"

    $appServiceSubnet = az network vnet subnet show --resource-group $resourceGroupName --vnet-name $virtualNetworkName --name $appServiceSubnetName --output json 2>$null | ConvertFrom-Json
    if (-not $appServiceSubnet) {
        Write-Host "Creating App Service integration subnet: $appServiceSubnetName"
        az network vnet subnet create --resource-group $resourceGroupName --vnet-name $virtualNetworkName --name $appServiceSubnetName --address-prefixes @($param_AppServiceIntegrationSubnetAddressPrefixes) --delegations Microsoft.Web/serverFarms | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create App Service integration subnet '$appServiceSubnetName'."; exit 1 }
    }

    az network vnet subnet update --resource-group $resourceGroupName --vnet-name $virtualNetworkName --name $appServiceSubnetName --disable-private-endpoint-network-policies false --disable-private-link-service-network-policies false | Out-Null

    $privateEndpointSubnet = az network vnet subnet show --resource-group $resourceGroupName --vnet-name $virtualNetworkName --name $privateEndpointSubnetName --output json 2>$null | ConvertFrom-Json
    if (-not $privateEndpointSubnet) {
        Write-Host "Creating private endpoint subnet: $privateEndpointSubnetName"
        az network vnet subnet create --resource-group $resourceGroupName --vnet-name $virtualNetworkName --name $privateEndpointSubnetName --address-prefixes @($param_PrivateEndpointSubnetAddressPrefixes) | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create private endpoint subnet '$privateEndpointSubnetName'."; exit 1 }
    }

    az network vnet subnet update --resource-group $resourceGroupName --vnet-name $virtualNetworkName --name $privateEndpointSubnetName --disable-private-endpoint-network-policies false --disable-private-link-service-network-policies false | Out-Null

    $script:ResolvedVirtualNetworkId = az network vnet show --resource-group $resourceGroupName --name $virtualNetworkName --query id --output tsv
    $script:ResolvedAppServiceSubnetId = az network vnet subnet show --resource-group $resourceGroupName --vnet-name $virtualNetworkName --name $appServiceSubnetName --query id --output tsv
    $script:ResolvedPrivateEndpointSubnetId = az network vnet subnet show --resource-group $resourceGroupName --vnet-name $virtualNetworkName --name $privateEndpointSubnetName --query id --output tsv
}

function Ensure-PrivateDnsZone {
    param(
        [string]$ZoneKey
    )

    $zoneConfig = Get-PrivateDnsZoneConfig -ZoneKey $ZoneKey
    $zoneResourceId = $zoneConfig.ZoneResourceId

    if ([string]::IsNullOrWhiteSpace($zoneResourceId)) {
        $existingZoneId = az network private-dns zone show --resource-group $resourceGroupName --name $zoneConfig.ZoneName --query id --output tsv 2>$null
        if (-not $existingZoneId) {
            Write-Host "Creating private DNS zone '$($zoneConfig.ZoneName)' in resource group '$resourceGroupName'."
            az network private-dns zone create --resource-group $resourceGroupName --name $zoneConfig.ZoneName | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create private DNS zone '$($zoneConfig.ZoneName)'."; exit 1 }
        }

        $zoneResourceId = az network private-dns zone show --resource-group $resourceGroupName --name $zoneConfig.ZoneName --query id --output tsv
    } else {
        $zoneContext = Get-PrivateDnsZoneContext -ZoneResourceId $zoneResourceId
        $existingZoneId = az network private-dns zone show --subscription $zoneContext.SubscriptionId --resource-group $zoneContext.ResourceGroupName --name $zoneContext.ZoneName --query id --output tsv 2>$null
        if (-not $existingZoneId) {
            Write-Error "The configured private DNS zone '$zoneResourceId' was not found."
            exit 1
        }
    }

    if ($zoneConfig.CreateVNetLink) {
        $zoneContext = Get-PrivateDnsZoneContext -ZoneResourceId $zoneResourceId
        $linkName = "{0}-{1}-{2}-pe-dnszonelink" -f $paramBaseName.ToLower(), $paramEnvironment.ToLower(), $script:PrivateDnsZoneLinkSuffixes[$ZoneKey]
        $existingLink = az network private-dns link vnet show --subscription $zoneContext.SubscriptionId --resource-group $zoneContext.ResourceGroupName --zone-name $zoneContext.ZoneName --name $linkName --query id --output tsv 2>$null
        if (-not $existingLink) {
            Write-Host "Creating private DNS VNet link '$linkName' for zone '$($zoneContext.ZoneName)'."
            az network private-dns link vnet create --subscription $zoneContext.SubscriptionId --resource-group $zoneContext.ResourceGroupName --zone-name $zoneContext.ZoneName --name $linkName --virtual-network $script:ResolvedVirtualNetworkId --registration-enabled false | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create private DNS VNet link '$linkName' for zone '$($zoneContext.ZoneName)'."; exit 1 }
        }
    }

    return $zoneResourceId
}

function Ensure-PrivateEndpoint {
    param(
        [string]$NameSuffix,
        [string]$ServiceResourceId,
        [string]$GroupId,
        [string]$ZoneKey
    )

    if ([string]::IsNullOrWhiteSpace($ServiceResourceId)) {
        return
    }

    $zoneResourceId = Ensure-PrivateDnsZone -ZoneKey $ZoneKey
    $zoneConfig = Get-PrivateDnsZoneConfig -ZoneKey $ZoneKey
    $privateEndpointName = ("{0}-{1}-{2}-pe" -f $paramBaseName, $paramEnvironment, $NameSuffix).ToLower()
    $privateServiceConnectionName = ("{0}-{1}-{2}-psc" -f $paramBaseName, $paramEnvironment, $NameSuffix).ToLower()
    $dnsZoneGroupName = ("{0}-{1}-{2}-dns" -f $paramBaseName, $paramEnvironment, $NameSuffix).ToLower()

    $existingPrivateEndpointId = az network private-endpoint show --resource-group $resourceGroupName --name $privateEndpointName --query id --output tsv 2>$null
    if (-not $existingPrivateEndpointId) {
        Write-Host "Creating private endpoint '$privateEndpointName' for resource '$ServiceResourceId'."
        az network private-endpoint create --resource-group $resourceGroupName --name $privateEndpointName --location $paramLocation --subnet $script:ResolvedPrivateEndpointSubnetId --private-connection-resource-id $ServiceResourceId --group-ids $GroupId --connection-name $privateServiceConnectionName | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create private endpoint '$privateEndpointName'."; exit 1 }
    }

    $existingDnsZoneGroup = az network private-endpoint dns-zone-group show --resource-group $resourceGroupName --endpoint-name $privateEndpointName --name $dnsZoneGroupName --query id --output tsv 2>$null
    if (-not $existingDnsZoneGroup) {
        Write-Host "Associating private endpoint '$privateEndpointName' with private DNS zone '$($zoneConfig.ZoneName)'."
        az network private-endpoint dns-zone-group create --resource-group $resourceGroupName --endpoint-name $privateEndpointName --name $dnsZoneGroupName --private-dns-zone $zoneResourceId --zone-name $zoneConfig.ZoneName | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create the DNS zone group for private endpoint '$privateEndpointName'."; exit 1 }
    }
}

function Update-ResourcePropertiesById {
    param(
        [string]$ResourceId,
        [string[]]$PropertyAssignments,
        [string]$DisplayName
    )

    if ([string]::IsNullOrWhiteSpace($ResourceId)) {
        return
    }

    $arguments = @('resource', 'update', '--ids', $ResourceId, '--set') + $PropertyAssignments
    & az @arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Failed to update resource properties for $DisplayName. Review this resource after deployment: $ResourceId"
    }
}

function Configure-PrivateNetworkingForDeployment {
    param(
        [string]$OpenAiResourceId
    )

    if (-not $param_EnablePrivateNetworking) {
        return
    }

    Ensure-PrivateNetworkingInfrastructure

    Write-Host "`n=====> Configuring App Service VNet integration and web app network settings..."
    Update-ResourcePropertiesById -ResourceId $(az webapp show --name $appServiceName --resource-group $resourceGroupName --query id --output tsv) -PropertyAssignments @(
        "properties.publicNetworkAccess=Disabled",
        "properties.virtualNetworkSubnetId=$($script:ResolvedAppServiceSubnetId)",
        "properties.vnetImagePullEnabled=true"
    ) -DisplayName "App Service"

    $webAppSiteConfig = @{ vnetRouteAllEnabled = $true; healthCheckPath = "/external/healthcheck" } | ConvertTo-Json -Compress
    az webapp config set --resource-group $resourceGroupName --name $appServiceName --generic-configurations $webAppSiteConfig | Out-Null
    az webapp config appsettings set --resource-group $resourceGroupName --name $appServiceName --settings WEBSITE_PULL_IMAGE_OVER_VNET=true | Out-Null

    $keyVaultResourceId = az keyvault show --name $keyVaultName --resource-group $resourceGroupName --query id --output tsv
    $cosmosResourceId = az cosmosdb show --name $cosmosDbName --resource-group $resourceGroupName --query id --output tsv
    $acrResourceId = az acr show --name $ACR_NAME --query id --output tsv
    $searchResourceId = az search service show --name $searchServiceName --resource-group $resourceGroupName --query id --output tsv
    $docIntelResourceId = az cognitiveservices account show --name $docIntelName --resource-group $resourceGroupName --query id --output tsv
    $storageResourceId = az storage account show --name $storageAccountName --resource-group $resourceGroupName --query id --output tsv
    $webAppResourceId = az webapp show --name $appServiceName --resource-group $resourceGroupName --query id --output tsv

    Ensure-PrivateEndpoint -NameSuffix "kv" -ServiceResourceId $keyVaultResourceId -GroupId "vault" -ZoneKey "keyVault"
    Ensure-PrivateEndpoint -NameSuffix "cosmosdb" -ServiceResourceId $cosmosResourceId -GroupId "sql" -ZoneKey "cosmosDb"
    Ensure-PrivateEndpoint -NameSuffix "acr" -ServiceResourceId $acrResourceId -GroupId "registry" -ZoneKey "containerRegistry"
    Ensure-PrivateEndpoint -NameSuffix "search" -ServiceResourceId $searchResourceId -GroupId "searchService" -ZoneKey "aiSearch"
    Ensure-PrivateEndpoint -NameSuffix "storage" -ServiceResourceId $storageResourceId -GroupId "blob" -ZoneKey "blobStorage"
    Ensure-PrivateEndpoint -NameSuffix "docintel" -ServiceResourceId $docIntelResourceId -GroupId "account" -ZoneKey "cognitiveServices"
    Ensure-PrivateEndpoint -NameSuffix "webapp" -ServiceResourceId $webAppResourceId -GroupId "sites" -ZoneKey "webSites"

    if (-not [string]::IsNullOrWhiteSpace($OpenAiResourceId)) {
        Ensure-PrivateEndpoint -NameSuffix "openai" -ServiceResourceId $OpenAiResourceId -GroupId "account" -ZoneKey "openAi"
    } else {
        Write-Warning "Skipping Azure OpenAI private endpoint automation because no Azure OpenAI resource ID was available."
    }

    Write-Host "`n=====> Locking down public network access for private networking resources..."
    Update-ResourcePropertiesById -ResourceId $keyVaultResourceId -PropertyAssignments @("properties.publicNetworkAccess=Disabled") -DisplayName "Key Vault"
    Update-ResourcePropertiesById -ResourceId $cosmosResourceId -PropertyAssignments @("properties.publicNetworkAccess=Disabled", "properties.isVirtualNetworkFilterEnabled=true") -DisplayName "Cosmos DB"
    Update-ResourcePropertiesById -ResourceId $acrResourceId -PropertyAssignments @("properties.publicNetworkAccess=Disabled") -DisplayName "Azure Container Registry"
    Update-ResourcePropertiesById -ResourceId $searchResourceId -PropertyAssignments @("properties.publicNetworkAccess=Disabled") -DisplayName "Azure AI Search"
    Update-ResourcePropertiesById -ResourceId $docIntelResourceId -PropertyAssignments @("properties.publicNetworkAccess=Disabled") -DisplayName "Document Intelligence"
    Update-ResourcePropertiesById -ResourceId $storageResourceId -PropertyAssignments @("properties.publicNetworkAccess=Disabled") -DisplayName "Storage Account"

    if (-not [string]::IsNullOrWhiteSpace($OpenAiResourceId)) {
        Update-ResourcePropertiesById -ResourceId $OpenAiResourceId -PropertyAssignments @("properties.publicNetworkAccess=Disabled") -DisplayName "Azure OpenAI"
    }
}

#---------------------------------------------------------------------------------------------
# Construct Resource Names
#---------------------------------------------------------------------------------------------
if([string]::IsNullOrEmpty($param_Existing_ResourceGroupName)){
    $rgTemp = Get-ResourceName -ResourceTypeSuffix $paramResourceGroupNameSuffix
    $resourceGroupName = "sc-" + $rgTemp
} else {
    $resourceGroupName = $param_Existing_ResourceGroupName
}
$appRegistrationName = Get-ResourceName -ResourceTypeSuffix $paramEntraAppRegistrationSuffix
$appServicePlanName = Get-ResourceName -ResourceTypeSuffix $paramAppServicePlanSuffix
$appServiceName = Get-ResourceName -ResourceTypeSuffix $paramAppServiceSuffix # Will be part of FQDN, needs to be unique
$appInsightsName = Get-ResourceName -ResourceTypeSuffix $paramAppInsightsSuffix
$cosmosDbName = Get-ResourceName -ResourceTypeSuffix $paramCosmosDbSuffix
$paramCosmosDbUrl = $paramCosmosDbUrlTemplate -f $cosmosDbName # Cosmos DB URL for connection strings
$openAIName = Get-ResourceName -ResourceTypeSuffix $paramOpenAISuffix
$docIntelName = Get-ResourceName -ResourceTypeSuffix $paramDocIntelSuffix
$keyVaultName = Get-ResourceName -ResourceTypeSuffix $paramKeyVaultSuffix
$logAnalyticsName = Get-ResourceName -ResourceTypeSuffix $paramLogAnalyticsSuffix
$managedIdentityName = Get-ResourceName -ResourceTypeSuffix $paramManagedIdentitySuffix
$searchServiceName = Get-ResourceName -ResourceTypeSuffix $paramSearchServiceSuffix
$videoIndexerName = Get-ResourceName -ResourceTypeSuffix $paramVideoIndexerSuffix
$storageAccountName = Get-GloballyUniqueResourceName -ResourceTypeSuffix $paramStorageAccountSuffix # Storage names are strict (lowercase, no hyphens, 3-24 chars)
if ($storageAccountName.Length -gt 24) { $storageAccountName = $storageAccountName.Substring(0, 24) }
if ($storageAccountName.Length -lt 3) { Write-Error "Generated storage account name '$storageAccountName' is too short. Adjust base name or suffix." ; exit 1 }
#$containerRegistryName = Get-GloballyUniqueResourceName -ResourceTypeSuffix $paramContainerRegistrySuffix # ACR names are strict
$entraGroupName_Admins = "$($paramBaseName)-$($paramEnvironment)-$($paramEntraGroupNameSuffix)-Admins"
$entraGroupName_Users = "$($paramBaseName)-$($paramEnvironment)-$($paramEntraGroupNameSuffix)-Users"
$entraGroupName_CreateGroup = "$($paramBaseName)-$($paramEnvironment)-$($paramEntraGroupNameSuffix)-CreateGroup"
$entraGroupName_SafetyViolationAdmin = "$($paramBaseName)-$($paramEnvironment)-$($paramEntraGroupNameSuffix)-SafetyViolationAdmin"
$entraGroupName_FeedbackAdmin = "$($paramBaseName)-$($paramEnvironment)-$($paramEntraGroupNameSuffix)-FeedbackAdmin"
$entraGroupName_CreatePublicWorkspace = "$($paramBaseName)-$($paramEnvironment)-$($paramEntraGroupNameSuffix)-CreatePublicWorkspace"
$global_EntraSecurityGroupNames = @($entraGroupName_Admins, $entraGroupName_Users, $entraGroupName_CreateGroup, $entraGroupName_SafetyViolationAdmin, $entraGroupName_FeedbackAdmin, $entraGroupName_CreatePublicWorkspace)


#---------------------------------------------------------------------------------------------
# Script Execution Starts Here
#---------------------------------------------------------------------------------------------
Write-Host "`n`n"
Write-Host "---------------------------------------------------------------------------------------------" -ForegroundColor Green
Write-Host "SimpleChat Deployer - Script Starting: [$script:paramDateTimeStamp]" -ForegroundColor Green
Write-Host "Starting Azure Resource Deployment for environment: $($paramEnvironment) in location: $($paramLocation)" -ForegroundColor Green
Write-Host "Resource Group Name: $($resourceGroupName)" -ForegroundColor Green
Write-Host "---------------------------------------------------------------------------------------------" -ForegroundColor Green

cd $PSScriptRoot #Do Not Modify

Ensure-AzureCliAuthenticated

# Check the ACR configuration
Write-Host "`n=====> Checking ACR: $($ACR_NAME) for admin user enabled..."
if ((az acr show --name $ACR_NAME --query "adminUserEnabled" --output tsv) -eq 'false') {
    Write-Host "Enabling admin user for ACR: $($ACR_NAME)..."
    az acr update --name $ACR_NAME --admin-enabled true
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to enable admin user for ACR '$($ACR_NAME)'. Ensure you have permissions." ; exit 1 } # Basic error check
} else {
    Write-Host "ACR: $($ACR_NAME) admin user is already enabled."
}

if ($param_BuildContainerImageWithAcr) {
    Invoke-AcrContainerBuild -RegistryName $ACR_NAME -ImageName $IMAGE_NAME -DockerfilePath $param_DockerfilePath -BuildContextPath $param_DockerBuildContextPath -PublishLatestTag $param_PublishLatestImageTag
} else {
    Write-Host "Skipping ACR image build because param_BuildContainerImageWithAcr is set to false." -ForegroundColor Yellow
}

# Check CosmosDB provider state
$cosmosDbProviderState = az provider show --namespace Microsoft.DocumentDB --query "registrationState" --output tsv
if ($cosmosDbProviderState -ne "Registered") {
    Write-Host "Registering CosmosDB provider..."
    az provider register --namespace Microsoft.DocumentDB

    while($cosmosDbProviderState -ne "Registered") {
        Start-Sleep -Seconds 5
        $cosmosDbProviderState = az provider show --namespace Microsoft.DocumentDB --query "registrationState" --output tsv
    }
}

$global_userType = az account show --query "user.type" -o tsv
if ($global_userType -eq "servicePrincipal") {
    Write-Output "Logged in as a service principal."
    $currentUserAppId = $(az account show --query "user.name" -o tsv) # returns app reg client id/app id NOT objectid
    Write-Host "Service Principal App ID: $currentUserAppId" -ForegroundColor Yellow
    $currentUserObjectId = az ad sp show --id $currentUserAppId --query id --output tsv
} elseif ($global_userType -eq "user") {
    Write-Output "Logged in as a user."
    $currentUserObjectId = $(az ad signed-in-user show --query "id" -o tsv)
} else {
    Write-Output "Unknown login type: $global_userType"
    Write-Error "Please log in to Azure CLI."
}
Write-Host "Logged in as: $currentUserObjectId" -ForegroundColor Yellow

$script:CurrentSubscriptionId = az account show --query "id" -o tsv
if ([string]::IsNullOrWhiteSpace($script:CurrentSubscriptionId)) {
    Write-Error "Failed to determine the active Azure subscription ID from the current Azure CLI context."
    exit 1
}

$resolvedExistingOpenAiSubscriptionId = if ([string]::IsNullOrWhiteSpace($param_Existing_AzureOpenAi_SubscriptionId)) { $script:CurrentSubscriptionId } else { $param_Existing_AzureOpenAi_SubscriptionId }

Test-PrivateNetworkingConfiguration

Write-Host "`nGetting Access Token Refreshed for: $paramArmUrl" -ForegroundColor Yellow
az account get-access-token --resource $paramArmUrl --output none
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to get ARM  Access Token." ; exit 1 } # Basic error check
Write-Host "`nGetting Access Token Refreshed for: $paramGraphUrl" -ForegroundColor Yellow
$userGraphToken = az account get-access-token --resource $paramGraphUrl -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to get MSGraph Access Token."; exit 1 } # Basic error check

# Find ACR registry
$paramRegistryServerUsername = $(az acr credential show --name $ACR_NAME --query username -o tsv)
$paramRegistryServerPassword = $(az acr credential show --name $ACR_NAME --query passwords[0].value -o tsv)
if (-not $paramRegistryServerUsername -or -not $paramRegistryServerPassword) {
    Write-Error "Failed to retrieve ACR credentials. Ensure the ACR exists and you have access."
}

# --- Create Entra ID Security Group ---
if ($paramCreateEntraSecurityGroups -eq $false) {
    Write-Host "`n=====> Skipping Entra ID Security Group creation as per configuration."
} else {
    # Note: This requires appropriate Entra ID permissions (e.g., Groups Administrator, User Administrator, or Global Administrator)
    Write-Host "`n=====> Creating Entra ID Security Groups..."
    foreach ($securityGroupName in $global_EntraSecurityGroupNames) {
        Write-Host "`nChecking if exists Security Group: $($securityGroupName)..."
        $entraGroup = az ad group show --group $securityGroupName --query "id" -o tsv 2>$null
        if (-not $entraGroup) {
            az ad group create --display-name $securityGroupName --mail-nickname $securityGroupName --description "Security group for $($paramBaseName) $($paramEnvironment) environment"
            #az ad group create --display-name $securityGroupName --description "Security group for $($paramBaseName) $($paramEnvironment) environment"
            if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to create Entra ID Security Group '$($securityGroupName)'. Check permissions or if mailNickname is unique." }
            else { Write-Host "Entra ID Security Group '$($securityGroupName)' created successfully." }
        } else {
            Write-Host "Entra ID Security Group '$($securityGroupName)' already exists."
        }
    }
}


# --- Create Resource Group ---
Write-Host "`n=====> Creating Resource Group: $($resourceGroupName)..."
# Check if the resource group exists
$resourceGroup = az group show --name $resourceGroupName --query "name" --output tsv 2>$null
if (-not $resourceGroup) {
    Write-Host "Resource group does not exist. Creating..."
    az group create --name $resourceGroupName --location $paramLocation --tags $tagsJson
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create Resource Group." ; exit 1 } # Basic error check

} else {
    Write-Host "Resource group '$resourceGroupName' already exists."
}

# --- Create Log Analytics Workspace ---
Write-Host "`n=====> Creating Log Analytics Workspace: $($logAnalyticsName)..."
# Check if the Log Analytics workspace exists
$workspace = az monitor log-analytics workspace show --workspace-name $logAnalyticsName --resource-group $resourceGroupName --query "name" --output tsv 2>$null
if (-not $workspace) {
    Write-Host "Log Analytics workspace does not exist. Creating..."
    az monitor log-analytics workspace create --resource-group $resourceGroupName --workspace-name $logAnalyticsName --location $paramLocation --sku $paramLogAnalyticsSku
    if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to create Log Analytics Workspace '$($logAnalyticsName)'." }
    else {
        $logAnalyticsWorkspaceId = $(az monitor log-analytics workspace show --resource-group $resourceGroupName --workspace-name $logAnalyticsName --query "id" -o tsv)
        Write-Host "Log Analytics Workspace '$($logAnalyticsName)' created successfully with ID: $logAnalyticsWorkspaceId"
    }
} else {
    Write-Host "Log Analytics workspace '$logAnalyticsName' already exists."
}

$logAnalyticsWorkspaceId = $(az monitor log-analytics workspace show --resource-group $resourceGroupName --workspace-name $logAnalyticsName --query "id" -o tsv)
if (-not $logAnalyticsWorkspaceId) {
    Write-Error "Failed to retrieve Log Analytics Workspace ID. Ensure the workspace was created successfully."
}


# --- Create Key Vault ---
Write-Host "`n=====> Getting Key Vault: $($keyVaultName)..."
# Check if the Key Vault exists
$vault = az keyvault show --name $keyVaultName --resource-group $resourceGroupName --query "name" --output tsv 2>$null
if (-not $vault) {
    Write-Host "Key Vault not found. Checking to see if its deleted..."
    # Attempt to recover the deleted Key Vault
    $kv = az keyvault recover --name $keyVaultName --resource-group $resourceGroupName --location $paramLocation
    if($kv){
        Write-Host "Key Vault recovered, waiting 30 seconds to make sure it is ready..."
        Start-Sleep -Seconds 60
        Write-Host "Key Vault 60 second wait over..."
    }
    else{
        Write-Host "Key Vault was not in a deleted state"
    }
} else {
    Write-Host "Key Vault '$keyVaultName' already exists."
}

Write-Host "`n=====> Getting Key Vault: $($keyVaultName)..."
$vault = az keyvault show --name $keyVaultName --resource-group $resourceGroupName 2>$null | ConvertFrom-Json
if (-not $vault) {
    Write-Host "`n=====> Creating Key Vault: $($keyVaultName)..."
    # Get current user's object ID to grant permissions
    $currentUserObjectId = $(az ad signed-in-user show --query "id" -o tsv)
    if (-not $currentUserObjectId) {
        Write-Warning "Could not retrieve current user's object ID. Key Vault permissions will need to be set manually."
        $vault = az keyvault create --name $keyVaultName --resource-group $resourceGroupName --location $paramLocation --sku $paramKeyVaultSku --enable-rbac-authorization false | ConvertFrom-Json # Using access policies if RBAC fails for user
    } else {
        $vault = az keyvault create --name $keyVaultName --resource-group $resourceGroupName --location $paramLocation --sku $paramKeyVaultSku --enable-rbac-authorization true | ConvertFrom-Json # Recommended: Use RBAC
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Key Vault '$($keyVaultName)' created successfully with RBAC. Assigning 'Key Vault Secrets Officer' role to current user..."
            # Wait a bit for KV to be fully provisioned before assigning role
            Start-Sleep -Seconds 30
            az role assignment create --role "Key Vault Secrets Officer" --assignee-object-id $currentUserObjectId --scope $(az keyvault show --name $keyVaultName --resource-group $resourceGroupName --query id -o tsv) --assignee-principal-type User
            if ($LASTEXITCODE -ne 0) { Write-Error "Failed to assign 'Key Vault Secrets Officer' role to current user for Key Vault '$($keyVaultName)'. You may need to do this manually."}
        } else {
            Write-Warning "Failed to create Key Vault '$($keyVaultName)' with RBAC. Trying with access policies..."
            $vault = az keyvault create --name $keyVaultName --resource-group $resourceGroupName --location $paramLocation --sku $paramKeyVaultSku --enable-rbac-authorization false | ConvertFrom-Json
            if ($LASTEXITCODE -eq 0 -and $currentUserObjectId) {
                Write-Host "Key Vault '$($keyVaultName)' created with access policies. Setting secret permissions for current user..."
                az keyvault set-policy --name $keyVaultName --resource-group $resourceGroupName --object-id $currentUserObjectId --secret-permissions get list set delete
            } elseif ($LASTEXITCODE -ne 0) {
                Write-Error "Failed to create Key Vault '$($keyVaultName)' with access policies."
            }
        }
    }
    if ($LASTEXITCODE -eq 0) { Write-Host "Key Vault '$($keyVaultName)' configuration completed."}
}
else 
{
    Write-Host "Key Vault '$keyVaultName' already exists."
}

# --- Create Application Insights ---
Write-Host "`n=====> Creating Application Insights: $($appInsightsName)..."
# Check if the Application Insights resource exists
$appInsights = az monitor app-insights component show --app $appInsightsName --resource-group $resourceGroupName --query "name" --output tsv 2>$null
if (-not $appInsights) {
    Write-Host "App Insights resource does not exist. Creating..."
    if ($logAnalyticsWorkspaceId) {
        az monitor app-insights component create --app $appInsightsName --location $paramLocation --resource-group $resourceGroupName --kind "web" --workspace $logAnalyticsWorkspaceId --tags $tagsJson
        if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to create Application Insights '$($appInsightsName)' (workspace-based)." }
        else {
            $appInsightsInstrumentationKey = $(az monitor app-insights component show --app $appInsightsName --resource-group $resourceGroupName --query "instrumentationKey" -o tsv)
            $appInsightsConnectionString = $(az monitor app-insights component show --app $appInsightsName --resource-group $resourceGroupName --query "connectionString" -o tsv)
            Write-Host "Application Insights '$($appInsightsName)' created. Key: $appInsightsInstrumentationKey, Connection String: $appInsightsConnectionString"
        }
    } else {
        Write-Error "Skipping Application Insights creation as Log Analytics Workspace creation failed or ID not found."
    }
} else {
    Write-Host "App Insights '$appInsightsName' already exists."
}


# --- Create Storage Account ---
Write-Host "`n=====> Creating Storage Account: $($storageAccountName)..."
# Check if the storage account exists
$storageAccount = az storage account show --name $storageAccountName --resource-group $resourceGroupName --query "name" --output tsv 2>$null
if (-not $storageAccount) {
    Write-Host "Storage account does not exist. Creating..."
    Write-Host "`n=====> Creating Storage Account: $($storageAccountName)..."
    New-AzStorageAccount -Name $storageAccountName -ResourceGroupName $resourceGroupName -Location $paramLocation -SkuName $paramStorageSku -Kind $paramStorageKind -AccessTier $paramStorageAccessTier -AllowBlobPublicAccess $false -Tags $tags
    # az command was failing with subscription not found
    #az storage account create --name $storageAccountName --resource-group $resourceGroupName --location $paramLocation --sku $paramStorageSku --kind $paramStorageKind --access-tier $paramStorageAccessTier --allow-blob-public-access false --tags $tagsJson
    if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to create Storage Account '$($storageAccountName)'." }
    else { Write-Host "Storage Account '$($storageAccountName)' created successfully." }
} else {
    Write-Host "Storage account '$storageAccountName' already exists."
}


# --- Create User-Assigned Managed Identity ---
Write-Host "`n=====> Creating User-Assigned Managed Identity: $($managedIdentityName)..."
# Check if the managed identity exists
$identity = az identity show --name $managedIdentityName --resource-group $resourceGroupName --query "name" --output tsv 2>$null
if (-not $identity) {
    az identity create --name $managedIdentityName --resource-group $resourceGroupName --location $paramLocation
    if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to create User-Assigned Managed Identity '$($managedIdentityName)'." }
    else {
        $managedIdentityPrincipalId = $(az identity show --name $managedIdentityName --resource-group $resourceGroupName --query "principalId" -o tsv)
        $managedIdentityId = $(az identity show --name $managedIdentityName --resource-group $resourceGroupName --query "id" -o tsv)
        Write-Host "User-Assigned Managed Identity '$($managedIdentityName)' created with Principal ID: $managedIdentityPrincipalId and Resource ID: $managedIdentityId"
        # Example: Grant Managed Identity access to Key Vault (secrets get/list)
        if ($keyVaultName -and $managedIdentityPrincipalId) {
            Write-Host "=====> Granting Managed Identity '$($managedIdentityName)' access to Key Vault '$($keyVaultName)' (get/list secrets)..."
            # Check if KV is RBAC or policy based
            $kvRbacEnabled = $(az keyvault show --name $keyVaultName --resource-group $resourceGroupName --query "properties.enableRbacAuthorization" -o tsv)
            if ($kvRbacEnabled -eq "true") {
                az role assignment create --role "Key Vault Secrets User" --assignee-object-id $managedIdentityPrincipalId --scope $(az keyvault show --name $keyVaultName --resource-group $resourceGroupName --query id -o tsv) --assignee-principal-type ServicePrincipal
                if ($LASTEXITCODE -ne 0) { Write-Error "Failed to assign 'Key Vault Secrets User' role to Managed Identity '$($managedIdentityName)' for Key Vault '$($keyVaultName)'."}
            } else {
                az keyvault set-policy --name $keyVaultName --resource-group $resourceGroupName --object-id $managedIdentityPrincipalId --secret-permissions get list
                if ($LASTEXITCODE -ne 0) { Write-Error "Failed to set Key Vault policy for Managed Identity '$($managedIdentityName)' on Key Vault '$($keyVaultName)'."}
            }
        }
    }
} else {
    Write-Host "Managed Identity '$managedIdentityName' already exists."
}


# --- Create App Service Plan ---
Write-Host "`n=====> Creating App Service Plan: $($appServicePlanName)..."
# Check if the App Service Plan exists
$plan = az appservice plan show --name $appServicePlanName --resource-group $resourceGroupName --query "name" --output tsv 2>$null
if (-not $plan) {
    Write-Host "App Service Plan does not exist. Creating..."
    az appservice plan create --name $appServicePlanName --resource-group $resourceGroupName --location $paramLocation --sku $paramAppServicePlanSku --is-linux # Specify --is-linux for Linux plans or remove for Windows
    if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to create App Service Plan '$($appServicePlanName)'." }
    else { Write-Host "App Service Plan '$($appServicePlanName)' created successfully." }
} else {
    Write-Host "App Service Plan '$appServicePlanName' already exists."
}


# --- Create App Service (Web App) ---
# Check if the Web App exists
$webApp = az webapp show --name $appServiceName --resource-group $resourceGroupName --query "name" --output tsv 2>$null
if (-not $webApp) {
    # Ensure App Service Plan creation was successful
    if ($(az appservice plan show --name $appServicePlanName --resource-group $resourceGroupName --query "id" -o tsv)) {
        Write-Host "`n=====> Creating App Service (Web App): $($appServiceName)..."
        az webapp create --resource-group $resourceGroupName --plan $appServicePlanName --name $appServiceName --deployment-container-image-name $ACR_BASE_URL/$IMAGE_NAME
        #az webapp create --resource-group $resourceGroupName --plan $appServicePlanName --name $appServiceName --image $ACR_BASE_URL/$IMAGE_NAME

        if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to create App Service '$($appServiceName)'." }
        else {
            Write-Host "App Service '$($appServiceName)' created successfully. URL: http://$($appServiceName).azurewebsites.us"
            # Example: Assign the managed identity to the App Service
            if ($managedIdentityId) {
                Write-Host "Assigning Managed Identity '$($managedIdentityName)' to App Service '$($appServiceName)'..."
                az webapp identity assign --name $appServiceName --resource-group $resourceGroupName --identities $managedIdentityId
                if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to assign Managed Identity to App Service '$($appServiceName)'."}
            }
        }

        Write-Host "`n=====> Setting App Service Container Image ..."
        # This deployer uses a container-based App Service.
        # Gunicorn startup is handled by the Dockerfile ENTRYPOINT inside the image,
        # so App Service native Python startup settings are not configured here.
        # az webapp config container set `
        # --name $appServiceName `
        # --resource-group $resourceGroupName `
        # --container-image-name $ACR_BASE_URL/$IMAGE_NAME `
        # --container-registry-url $paramRegistryServer `
        # --docker-registry-server-user $(az acr credential show --name $ACR_NAME --query username -o tsv) `
        # --docker-registry-server-password $(az acr credential show --name $ACR_NAME --query passwords[0].value -o tsv)
        az webapp config container set `
        --name $appServiceName `
        --resource-group $resourceGroupName `
        --container-image-name $ACR_BASE_URL/$IMAGE_NAME `
        --container-registry-url $paramRegistryServer `
        --container-registry-user $(az acr credential show --name $ACR_NAME --query username -o tsv) `
        --container-registry-password $(az acr credential show --name $ACR_NAME --query passwords[0].value -o tsv)

        # TODO
        # CLASSIC WAY
        # az webapp auth-classic update --resource-group sc-emma4-sbx-rg --name emma4-sbx-app --enabled true

        # NEW WAY
        # az webapp auth update --resource-group $resourceGroupName --name $appServiceName --enabled true --unauthenticated-client-action RedirectToLoginPage

        # az webapp auth microsoft update `
        # --resource-group $RESOURCE_GROUP `
        # --name $APP_NAME `
        # --client-id "<your-client-id>" `
        # --client-secret "<your-client-secret>" `
        # --issuer "https://login.microsoftonline.us/6bc5b33e-bc05-493c-b076-8f8ce1331515/v2.0"

        # Enable System Managed Identity
        az webapp identity assign --name $appServiceName --resource-group $resourceGroupName

    } else {
        Write-Error "Cannot create App Service because App Service Plan '$($appServicePlanName)' was not found or failed to create."
    }
} else {
    Write-Host "Web App '$appServiceName' already exists."
}


# --- Entra App Registration ---
Write-Host "`n=====> Creating Entra App Registration: $($appServiceName)..."
$tempAppServiceRedirectUrl = $APPREG_REDIRECT_URI -f $appServiceName
$tempAppServiceRedirectUrl1 = $APPREG_REDIRECT_URI1 -f $appServiceName
$tempAppServiceLogoutUrl = $APPREG_LOGOUT_URL -f $appServiceName

# Check if the app already exists
$appRegistration = az ad app list --display-name $appRegistrationName --output json | ConvertFrom-Json
if (-not $appRegistration -or $appRegistration.Count -eq 0) {
    Write-Host "App [$appRegistrationName] does not exist. Creating..."
    Write-Host "Redirect Url: $tempAppServiceRedirectUrl" 
    Write-Host "Redirect Url1: $tempAppServiceRedirectUrl1"
    $appRegistration = az ad app create --display-name $appRegistrationName --web-redirect-uris "$tempAppServiceRedirectUrl" "$tempAppServiceRedirectUrl1" --output json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create App Registration '$($appRegistrationName)'." }
    else { Write-Host "App Registration '$($appRegistrationName)' created successfully." }

    $appRegistrationServicePrincipal = az ad sp create --id $appRegistration.appId
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create App Registration Service Principal for '$($appRegistrationName)'." }
    else { Write-Host "App Registration '$($appRegistrationName)' Service Principal created successfully." }

    az ad app update --id $($appRegistration.appId) --app-roles '@appRegistrationRoles.json'

    Write-Host "App [$appRegistrationName] logout url set: [$tempAppServiceLogoutUrl]..."
    #az ad app update --id $($appRegistration.id) --web-logout-uri "$tempAppServiceLogoutUrl"
    $appReg = az ad app show --id $($appRegistration.appId) | ConvertFrom-Json
    $body = @{ web = @{ logoutUrl = "$tempAppServiceLogoutUrl" } } | ConvertTo-Json -Compress
    az rest --method PATCH --uri ($paramGraphUrl + '/v1.0/applications/{0}' -f $appReg.id) --headers 'Content-Type=application/json' --body ($body -replace '"', '\"') 

    Write-Host "App [$appRegistrationName] setting implicit grants..."
    az ad app update --id $($appRegistration.id) --enable-id-token-issuance true --enable-access-token-issuance true
    #'{"implicitGrantSettings":{"enableAccessTokenIssuance":true,"enableIdTokenIssuance":true}}'

    Write-Host "App Registration: Setting Api Permissions..."
    #user.read
    az ad app permission add --id $($appRegistration.id) --api 00000003-0000-0000-c000-000000000000 --api-permissions e1fe6dd8-ba31-4d61-89e7-88639da4683d=Scope
    #profile
    az ad app permission add --id $($appRegistration.id) --api 00000003-0000-0000-c000-000000000000 --api-permissions 14dad69e-099b-42c9-810b-d002981feec1=Scope
    #email
    az ad app permission add --id $($appRegistration.id) --api 00000003-0000-0000-c000-000000000000 --api-permissions 64a6cdd6-aab1-4aaf-94b8-3cc8405e90d0=Scope 

    #az ad app permission admin-consent --id $($appRegistration.id)
    #az ad app permission grant --id e432e60d-42c9-490f-a97b-94dab5010406 --api 00000003-0000-0000-c000-000000000000
    # This command is not yet supported on sovereign clouds


    $currentUserObjectId = $(az ad signed-in-user show --query "id" -o tsv)
    az ad app owner add --id $($appRegistration.id) --owner-object-id $currentUserObjectId
} else {
    Write-Host "App already exists [$appRegistrationName]."
}

Write-Host "`nGetting Entra App Registration Client Id and Secrets ..."
$paramEntraAppRegistrationClientId = $($appRegistration.appId)
if (-not $paramEntraAppRegistrationClientId) {
    Write-Error "Failed to retrieve App Registration Client ID. Ensure the app was created successfully."
}
$paramEntraAppRegistrationSecret = az ad app credential reset --id $paramEntraAppRegistrationClientId --append --query password -o tsv
#$paramEntraAppRegistrationSecret_MicrosoftProvider = az ad app credential reset --id $paramEntraAppRegistrationClientId --append --display-name "MICROSOFT_PROVIDER_AUTHENTICATION_SECRET" --query password -o tsv

# --- Create Azure Cosmos DB account ---
Write-Host "`n=====> Creating Azure Cosmos DB account: $($cosmosDbName)..."
$account = az cosmosdb show --name $cosmosDbName --resource-group $resourceGroupName --query "name" --output tsv 2>$null
if (-not $account) {
    Write-Host "Cosmos DB account does not exist. Creating..."
    az cosmosdb create --name $cosmosDbName `
    --resource-group $resourceGroupName `
    --locations regionName=$paramLocation `
    --kind $paramCosmosDbKind `
    --enable-multiple-write-locations false `
    --public-network-access Enabled `
    --default-consistency-level 'Session' `
    --tags $tagsJson `
    --enable-burst-capacity True

    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create Azure Cosmos DB account '$($cosmosDbName)'." }
    else { Write-Host "Azure Cosmos DB account '$($cosmosDbName)' created successfully." }
} else {
    Write-Host "Cosmos DB account '$cosmosDbName' already exists."
}

az resource update --resource-group $resourceGroupName --name $cosmosDbName --resource-type "Microsoft.DocumentDB/databaseAccounts" --set properties.disableLocalAuth=false

# Create cosmos db database and collection
# TODO: SHOULD I DO THIS OR NOT? Web UI creates this.
# Write-Host "`n=====> Creating Azure Cosmos DB database ..."
# $databaseName = "SimpleChatDb"
# $resourceObject = az cosmosdb sql database show --account-name $cosmosDbName --resource-group $resourceGroupName --name $databaseName --query "name" --output tsv 2>$null
# if (-not $resourceObject) {
#     Write-Host "Database '$databaseName' does not exist. Creating..."
#     az cosmosdb sql database create --account-name $cosmosDbName --resource-group $resourceGroupName --name $databaseName --throughput 1000
# } else {
#     Write-Host "Database '$databaseName' already exists."
# }

# $containerName = "messages"
# CosmosDb_CreateContainer $databaseName $containerName
# $containerName = "documents"
# CosmosDb_CreateContainer $databaseName $containerName
# $containerName = "group_documents"
# CosmosDb_CreateContainer $databaseName $containerName
# $containerName = "settings"
# CosmosDb_CreateContainer $databaseName $containerName
# $containerName = "feedback"
# CosmosDb_CreateContainer $databaseName $containerName
# $containerName = "archived_conversations"
# CosmosDb_CreateContainer $databaseName $containerName

# --- Create Azure OpenAI Service and model deployments ---
# Note: Azure OpenAI requires registration and sometimes specific SKU availability.
# The account resource uses the Cognitive Services account SKU, while each model deployment uses its own deployment type and capacity.

$openAiUrl = $null
$openAiAccountName = if ($param_UseExisting_OpenAi_Instance -eq $true) { $param_Existing_AzureOpenAi_ResourceName } else { $openAIName }
$openAiResourceGroupName = if ($param_UseExisting_OpenAi_Instance -eq $true) { $param_Existing_AzureOpenAi_ResourceGroupName } else { $resourceGroupName }
$openAiSubscriptionId = if ($param_UseExisting_OpenAi_Instance -eq $true) { $resolvedExistingOpenAiSubscriptionId } else { $script:CurrentSubscriptionId }
if ($param_UseExisting_OpenAi_Instance -eq $true) {
    Write-Host "`n=====> Using existing Azure OpenAI Service: $($param_Existing_AzureOpenAi_ResourceName)..."
    #Write-Host "SubscriptionId: $param_Existing_AzureOpenAi_SubscriptionId"
    Write-Host "Resource Group name: $param_Existing_AzureOpenAi_ResourceGroupName"
    $openAiUrl = $param_AzureOpenAi_Url -f $param_Existing_AzureOpenAi_ResourceName
    
} else {
    Write-Host "`n=====> Creating Azure OpenAI Service: $($openAIName)..."
    # Check if the Cognitive Services account exists
    $account = az cognitiveservices account show --name $openAIName --resource-group $resourceGroupName --query "name" --output tsv 2>$null
    if (-not $account) {
        Write-Host "Cognitive Services account does not exist. Creating..."
        az cognitiveservices account create --name $openAIName --resource-group $resourceGroupName --location $paramLocation --kind "OpenAI" --sku $paramCognitiveServicesSku --tags $tagsJson
        if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to create Azure OpenAI Service '$($openAIName)'. Ensure your subscription is approved for OpenAI and the SKU/region is available in Azure Government." }
        else { Write-Host "Azure OpenAI Service '$($openAIName)' created successfully." }
    } else {
        Write-Host "Cognitive Services account '$openAIName' already exists."
    }
    $openAiUrl = $param_AzureOpenAi_Url -f $openAIName
}

Write-Host "Open Ai Url: $openAiUrl"

if ($param_DeployAzureOpenAiModels) {
    $openAiAccount = az cognitiveservices account show --name $openAiAccountName --resource-group $openAiResourceGroupName --subscription $openAiSubscriptionId --query "name" --output tsv 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($openAiAccount)) {
        Write-Warning "Skipping Azure OpenAI model deployment creation because the Azure OpenAI account '$openAiAccountName' is not available."
    } else {
        $openAiModelDeployments = Get-OpenAiModelDeploymentDefinitions
        foreach ($modelDeployment in $openAiModelDeployments) {
            $deploymentCreated = Ensure-OpenAiModelDeployment \
                -AccountName $openAiAccountName \
                -ResourceGroupName $openAiResourceGroupName \
                -SubscriptionId $openAiSubscriptionId \
                -ModelDeployment $modelDeployment

            if (-not $deploymentCreated) {
                Write-Warning "Simple Chat will still deploy, but review the Azure OpenAI deployment '$($modelDeployment.DeploymentName)' before using $($modelDeployment.Kind.ToLower()) features."
            }
        }
    }
} else {
    Write-Host "Skipping Azure OpenAI model deployment creation because param_DeployAzureOpenAiModels is set to false." -ForegroundColor Yellow
}

# --- Create Document Intelligence Service ---
Write-Host "`n=====> Creating Document Intelligence Service: $($docIntelName)..."
$cogServicesAccount = az cognitiveservices account show --name $docIntelName --resource-group $resourceGroupName 2>$null | ConvertFrom-Json
if (-not $cogServicesAccount) {
    Write-Host "Cognitive Services account does not exist. Creating..."
    $cogServicesAccount = az cognitiveservices account create --name $docIntelName --resource-group $resourceGroupName --location $paramLocation --kind "FormRecognizer" --custom-domain $docIntelName --sku $paramCognitiveServicesSku --tags $tagsJson | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to create Document Intelligence Service '$($docIntelName)'." }
    else { Write-Host "Document Intelligence Service '$($docIntelName)' created successfully." }
} else {
    Write-Host "Cognitive Services account '$docIntelName' already exists."
}

# --- Create Azure AI Search Service ---
Write-Host "`n=====> Creating Azure AI Search Service: $($searchServiceName)..."
# Check if the search service exists
$searchService = az search service show --name $searchServiceName --resource-group $resourceGroupName 2>$null | ConvertFrom-Json
if (-not $searchService) {
    Write-Host "Search service does not exist. Creating..."
    $searchService = az search service create --name $searchServiceName --resource-group $resourceGroupName --location $paramLocation --sku $paramSearchSku --replica-count $paramSearchReplicaCount --partition-count $paramSearchPartitionCount --public-network-access enabled | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to create Azure AI Search Service '$($searchServiceName)'. Check SKU availability and naming uniqueness." }
    else { Write-Host "Azure AI Search Service '$($searchServiceName)' created successfully." }

    # This doesn't work. Do this manually.
    #Deploy index as json files to Azure Search
    # az search index create `
    # --name "simplechat-group-index" `
    # --service-name $searchServiceName `
    # --resource-group $resourceGroupName `
    # --body '@ai_search-index-group.json'

    #Deploy index as json files to Azure Search
    # az search index create `
    # --name "simplechat-user-index" `
    # --service-name $searchServiceName `
    # --resource-group $resourceGroupName `
    # --body '@ai_search-index-user.json'

} else {
    Write-Host "Search service '$searchServiceName' already exists."
}

$searchServiceUrl = $param_AiSearch_Url -f $searchServiceName

# --- Create Azure Video Indexer Service ---
if ($param_DeployVideoIndexerService) {
    Write-Host "`n=====> Creating Azure Video Indexer Service: $($videoIndexerName)..."
    $videoIndexerSubscriptionId = az account show --query id --output tsv
    $videoIndexerArmBaseUrl = $paramArmUrl.TrimEnd('/')
    $videoIndexerUri = "$videoIndexerArmBaseUrl/subscriptions/$videoIndexerSubscriptionId/resourceGroups/$resourceGroupName/providers/Microsoft.VideoIndexer/accounts/$videoIndexerName?api-version=$param_VideoIndexerArmApiVersion"
    $existingVideoIndexer = az rest --method get --uri $videoIndexerUri 2>$null | ConvertFrom-Json

    if (-not $existingVideoIndexer) {
        $videoIndexerProperties = @{
            storageServices = @{
                resourceId = $(az storage account show --name $storageAccountName --resource-group $resourceGroupName --query id --output tsv)
            }
        }

        if ($param_VideoIndexerArmApiVersion -eq '2025-04-01') {
            $openAiVideoIndexerResourceId = if ($param_UseExisting_OpenAi_Instance -eq $true) {
                az resource show --name $param_Existing_AzureOpenAi_ResourceName --resource-group $param_Existing_AzureOpenAi_ResourceGroupName --resource-type 'Microsoft.CognitiveServices/accounts' --subscription $resolvedExistingOpenAiSubscriptionId --query "id" --output tsv
            } else {
                az cognitiveservices account show --name $openAIName --resource-group $resourceGroupName --query "id" --output tsv
            }

            $videoIndexerProperties.publicNetworkAccess = if ($param_EnablePrivateNetworking) { 'Disabled' } else { 'Enabled' }
            if (-not [string]::IsNullOrWhiteSpace($openAiVideoIndexerResourceId)) {
                $videoIndexerProperties.openAiServices = @{
                    resourceId = $openAiVideoIndexerResourceId
                }
            }
        }

        $videoIndexerBody = @{
            location = $paramLocation
            identity = @{
                type = 'SystemAssigned'
            }
            properties = $videoIndexerProperties
            tags = $tags
        } | ConvertTo-Json -Depth 10 -Compress

        az rest --method put --uri $videoIndexerUri --headers 'Content-Type=application/json' --body $videoIndexerBody | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Failed to create Azure Video Indexer Service '$($videoIndexerName)'."
        } else {
            Write-Host "Azure Video Indexer Service '$($videoIndexerName)' created successfully."
            $existingVideoIndexer = az rest --method get --uri $videoIndexerUri 2>$null | ConvertFrom-Json
        }
    } else {
        Write-Host "Azure Video Indexer Service '$videoIndexerName' already exists."
    }
}

# --- Create App Service Settings ---
Write-Host "`n=====> Setting Azure App Service App Settings : $($appServiceName)..."
$paramCosmosDbPrimaryKey = $(az cosmosdb keys list --name $cosmosDbName --resource-group $resourceGroupName --query primaryMasterKey --output tsv)

$fileName = ".\appSettings.json"
$jsonAsText = Get-Content -Path $fileName -Raw
$jsonAsText = $jsonAsText.Replace("<TOKEN_AZURE_ENVIRONMENT>", "$param_AppService_Environment")
$jsonAsText = $jsonAsText.Replace("<TOKEN_AZURE_COSMOS_AUTHENTICATION_TYPE>", "key")
$jsonAsText = $jsonAsText.Replace("<TOKEN_AZURE_COSMOS_ENDPOINT>", "$paramCosmosDbUrl")
$jsonAsText = $jsonAsText.Replace("<TOKEN_AZURE_COSMOS_KEY>", "$paramCosmosDbPrimaryKey")
$jsonAsText = $jsonAsText.Replace("<TOKEN_TENANT_ID>", "$paramTenantId")
$jsonAsText = $jsonAsText.Replace("<TOKEN_CLIENT_ID>", "$paramEntraAppRegistrationClientId")
$jsonAsText = $jsonAsText.Replace("<TOKEN_SECRET_KEY>", "$paramEntraAppRegistrationSecret")
$jsonAsText = $jsonAsText.Replace("<TOKEN_WEBSITE_AUTH_AAD_ALLOWED_TENANTS>", "$paramTenantId")
$jsonAsText = $jsonAsText.Replace("<TOKEN_DOCKER_REGISTRY_SERVER_URL>", "$paramRegistryServer")
$jsonAsText = $jsonAsText.Replace("<TOKEN_DOCKER_REGISTRY_SERVER_USERNAME>", "$paramRegistryServerUsername")
$jsonAsText = $jsonAsText.Replace("<TOKEN_DOCKER_REGISTRY_SERVER_PASSWORD>", "$paramRegistryServerPassword")
$jsonAsText = $jsonAsText.Replace("<TOKEN_AZURE_OPENAI_ENDPOINT>", "$openAiUrl")
$jsonAsText = $jsonAsText.Replace("<TOKEN_AZURE_DOCUMENTINTELLIGENCE_ENDPOINT>", "$($cogServicesAccount.properties.endpoint)")
$jsonAsText = $jsonAsText.Replace("<TOKEN_AZURE_SEARCH_SERVICE_ENDPOINT>", "$searchServiceUrl")
$jsonAsText = $jsonAsText.Replace("<TOKEN_AZURE_KEY_VAULT_ENDPOINT>", "$($vault.properties.vaultUri)")
$jsonAsText | Out-File -FilePath ".\appsettings-temp.json" -ErrorAction Stop
az webapp config appsettings set --resource-group $resourceGroupName --name $appServiceName --settings '@appsettings-temp.json'
if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to update Azure App Service App Settings." }
else { Write-Host "Azure App Service App Settings configured." }

$additionalAppSettings = @(
    "VIDEO_INDEXER_ARM_API_VERSION=$param_VideoIndexerArmApiVersion"
)

if ($param_AppService_Environment -eq 'custom') {
    $additionalAppSettings += @(
        "CUSTOM_GRAPH_URL_VALUE=$param_CustomGraphUrl",
        "CUSTOM_IDENTITY_URL_VALUE=$param_CustomIdentityUrl",
        "CUSTOM_RESOURCE_MANAGER_URL_VALUE=$param_CustomResourceManagerUrl",
        "CUSTOM_COGNITIVE_SERVICES_URL_VALUE=$param_CustomCognitiveServicesScope",
        "CUSTOM_SEARCH_RESOURCE_MANAGER_URL_VALUE=$param_CustomSearchResourceUrl",
        "CUSTOM_VIDEO_INDEXER_ENDPOINT=$param_VideoIndexerEndpoint"
    )
}

az webapp config appsettings set --resource-group $resourceGroupName --name $appServiceName --settings $additionalAppSettings | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Failed to update additional Video Indexer or custom cloud app settings."
}

$openAiResourceIdForNetworking = ""
if ($param_UseExisting_OpenAi_Instance -eq $false) {
    $openAiResourceIdForNetworking = az cognitiveservices account show --name $openAIName --resource-group $resourceGroupName --query "id" --output tsv 2>$null
} elseif (-not [string]::IsNullOrWhiteSpace($param_Existing_AzureOpenAi_ResourceName) -and -not [string]::IsNullOrWhiteSpace($param_Existing_AzureOpenAi_ResourceGroupName)) {
    $openAiResourceIdForNetworking = az resource show --name $param_Existing_AzureOpenAi_ResourceName --resource-group $param_Existing_AzureOpenAi_ResourceGroupName --resource-type 'Microsoft.CognitiveServices/accounts' --subscription $resolvedExistingOpenAiSubscriptionId --query "id" --output tsv 2>$null
}

Configure-PrivateNetworkingForDeployment -OpenAiResourceId $openAiResourceIdForNetworking


##############################################################
# RBAC ASSIGNMENTS
##############################################################
Write-Host "`n`n=====> Performing RBAC Assignments ..." -ForegroundColor Yellow

Write-Host "`nGetting Managed Identity Principal Id"
$managedIdentity_PrincipalId = az identity show --name $managedIdentityName --resource-group $resourceGroupName --query "principalId" --output tsv 2>$null
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to get Managed Identity [$managedIdentityName]." }
else { Write-Host "Found Managed Identity [$managedIdentityName] with Principal Id: [$managedIdentity_PrincipalId]." }

Write-Host "`nGetting Entra App Registration App Id for [$appRegistrationName]"
$appRegistrationIdentity_AppId = az ad app list --display-name "$appRegistrationName" --query "[0].appId" --output tsv
Write-Host "Getting Entra App Registration Service Principal App Id [$appRegistrationIdentity_AppId]"
$appRegistrationIdentity_SP_AppId = az ad sp show --id $appRegistrationIdentity_AppId --query "id" -o tsv
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to get App Registration Service Principal [$appRegistrationName]." }
else { Write-Host "Found App Registration Service Principal [$appRegistrationName] with Principal Id: [$appRegistrationIdentity_SP_AppId]." }

Write-Host "`nGetting App Service System Managed Identity Object Id for [$appServiceName]"
$appService_SystemManagedIdentity_ObjectId = az webapp identity show --name $appServiceName --resource-group $resourceGroupName --query "principalId" --output tsv
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to get App Service SMI [$appServiceName]." }
else { Write-Host "Found App Service SMI [$appServiceName] with Principal/Object Id: [$appService_SystemManagedIdentity_ObjectId]." }


#-------------------------------------------------------------
Write-Host "`nGetting Cognitive Services Account Open AI"
#-------------------------------------------------------------
if ($param_UseExisting_OpenAi_Instance -eq $false) {
    $resourceId = az cognitiveservices account show --name $openAIName --resource-group $resourceGroupName --query "id" --output tsv
} else {
    $resourceId = az resource show --name $param_Existing_AzureOpenAi_ResourceName --resource-group $param_Existing_AzureOpenAi_ResourceGroupName `
        --resource-type 'Microsoft.CognitiveServices/accounts' --subscription $resolvedExistingOpenAiSubscriptionId --query "id" --output tsv

}
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to find Open AI resource [$openAIName]." }
else { Write-Host "Found Open AI resource [$openAIName]." }

$roleName = "Cognitive Services Contributor"
$assigneeObjectId = $managedIdentity_PrincipalId
# Check if the role assignment already exists
Write-Host "Getting RBAC settings for Cognitive Services Open AI Account [$assigneeObjectId]"
$assignment = az role assignment list `
  --assignee $assigneeObjectId `
  --scope "$resourceId" `
  --query "[?roleDefinitionName=='$roleName']" `
  --output json | ConvertFrom-Json

if (-not $assignment) {
    Write-Host "RBAC assignment not found. Creating..."
    az role assignment create `
      --assignee $assigneeObjectId `
      --role "$roleName" `
      --scope "$resourceId"
} else {
    Write-Host "RBAC assignment already exists."
}

$roleName = "Cognitive Services User"
$assigneeObjectId = $managedIdentity_PrincipalId
# Check if the role assignment already exists
Write-Host "Getting RBAC settings for Cognitive Services Open AI Account"
$assignment = az role assignment list `
  --assignee $assigneeObjectId `
  --scope "$resourceId" `
  --query "[?roleDefinitionName=='$roleName']" `
  --output json | ConvertFrom-Json

if (-not $assignment) {
    Write-Host "RBAC assignment not found. Creating..."
    az role assignment create `
      --assignee $assigneeObjectId `
      --role "$roleName" `
      --scope "$resourceId"
} else {
    Write-Host "RBAC assignment already exists."
}

$roleName = "Cognitive Services OpenAI Contributor"
$assigneeObjectId = $appRegistrationIdentity_SP_AppId
# Check if the role assignment already exists
Write-Host "Checking RBAC on Cognitive Services Open AI Account [$assigneeObjectId]"
$assignment = az role assignment list `
  --assignee $assigneeObjectId `
  --scope "$resourceId" `
  --query "[?roleDefinitionName=='$roleName']" `
  --output json | ConvertFrom-Json

if (-not $assignment) {
    Write-Host "RBAC assignment not found. Creating..."
    az role assignment create `
      --assignee $assigneeObjectId `
      --role "$roleName" `
      --scope "$resourceId"
} else {
    Write-Host "RBAC assignment already exists."
}

$assigneeObjectId = $managedIdentity_PrincipalId
# Check if the role assignment already exists
Write-Host "Checking RBAC on Cognitive Services Open AI Account [$assigneeObjectId]"
$assignment = az role assignment list `
  --assignee $assigneeObjectId `
  --scope "$resourceId" `
  --query "[?roleDefinitionName=='$roleName']" `
  --output json | ConvertFrom-Json

if (-not $assignment) {
    Write-Host "RBAC assignment not found. Creating..."
    az role assignment create `
      --assignee $assigneeObjectId `
      --role "$roleName" `
      --scope "$resourceId"
} else {
    Write-Host "RBAC assignment already exists."
}

$roleName = "Cognitive Services OpenAI User"
$assigneeObjectId = $appRegistrationIdentity_SP_AppId
# Check if the role assignment already exists
Write-Host "Checking RBAC on Cognitive Services Open AI User for [$assigneeObjectId]"
$assignment = az role assignment list `
  --assignee $assigneeObjectId `
  --scope "$resourceId" `
  --query "[?roleDefinitionName=='$roleName']" `
  --output json | ConvertFrom-Json

if (-not $assignment) {
    Write-Host "RBAC assignment not found. Creating..."
    az role assignment create `
      --assignee $assigneeObjectId `
      --role "$roleName" `
      --scope "$resourceId"
} else {
    Write-Host "RBAC assignment already exists."
}

$assigneeObjectId = $appService_SystemManagedIdentity_ObjectId
# Check if the role assignment already exists
Write-Host "Checking RBAC on Cognitive Services Open AI Account [$assigneeObjectId]"
$assignment = az role assignment list `
  --assignee $assigneeObjectId `
  --scope "$resourceId" `
  --query "[?roleDefinitionName=='$roleName']" `
  --output json | ConvertFrom-Json

if (-not $assignment) {
    Write-Host "RBAC assignment not found. Creating..."
    az role assignment create `
      --assignee $assigneeObjectId `
      --role "$roleName" `
      --scope "$resourceId"
} else {
    Write-Host "RBAC assignment already exists."
}

$assigneeObjectId = $appService_SystemManagedIdentity_ObjectId
# Check if the role assignment already exists
Write-Host "Checking RBAC on Cognitive Services Open AI Account [$assigneeObjectId]"
$assignment = az role assignment list `
  --assignee $assigneeObjectId `
  --scope "$resourceId" `
  --query "[?roleDefinitionName=='$roleName']" `
  --output json | ConvertFrom-Json

if (-not $assignment) {
    Write-Host "RBAC assignment not found. Creating..."
    az role assignment create `
      --assignee $assigneeObjectId `
      --role "$roleName" `
      --scope "$resourceId"
} else {
    Write-Host "RBAC assignment already exists."
}

if ($param_DeployVideoIndexerService) {
    Write-Host "`nGetting Azure Video Indexer principal"
    $videoIndexerResourceId = az resource show --name $videoIndexerName --resource-group $resourceGroupName --resource-type 'Microsoft.VideoIndexer/accounts' --query "id" --output tsv 2>$null
    $videoIndexerPrincipalId = az resource show --ids $videoIndexerResourceId --api-version $param_VideoIndexerArmApiVersion --query "identity.principalId" --output tsv 2>$null

    if (-not [string]::IsNullOrWhiteSpace($videoIndexerPrincipalId)) {
        $storageResourceId = az storage account show --name $storageAccountName --resource-group $resourceGroupName --query "id" --output tsv
        $assignment = az role assignment list --assignee $videoIndexerPrincipalId --scope "$storageResourceId" --query "[?roleDefinitionName=='Storage Blob Data Contributor']" --output json | ConvertFrom-Json
        if (-not $assignment) {
            az role assignment create --assignee $videoIndexerPrincipalId --role "Storage Blob Data Contributor" --scope "$storageResourceId" | Out-Null
        }

        if ($param_VideoIndexerArmApiVersion -eq '2025-04-01') {
            $assignment = az role assignment list --assignee $videoIndexerPrincipalId --scope "$resourceId" --query "[?roleDefinitionName=='Cognitive Services Contributor']" --output json | ConvertFrom-Json
            if (-not $assignment) {
                az role assignment create --assignee $videoIndexerPrincipalId --role "Cognitive Services Contributor" --scope "$resourceId" | Out-Null
            }

            $assignment = az role assignment list --assignee $videoIndexerPrincipalId --scope "$resourceId" --query "[?roleDefinitionName=='Cognitive Services User']" --output json | ConvertFrom-Json
            if (-not $assignment) {
                az role assignment create --assignee $videoIndexerPrincipalId --role "Cognitive Services User" --scope "$resourceId" | Out-Null
            }
        }
    } else {
        Write-Warning "Azure Video Indexer principal ID could not be resolved. Skipping Video Indexer RBAC assignments."
    }
}


#-------------------------------------------------------------
Write-Host "Getting Cosmos DB: Resource ID"
#-------------------------------------------------------------
Write-Host "Getting RBAC settings for Cosmos DB Account"
$resourceId = az cosmosdb show --name $cosmosDbName --resource-group $resourceGroupName --query "id" --output tsv
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to find Cosmos DB resource [$cosmosDbName]." }
else { Write-Host "Found Cosmos DB resource [$cosmosDbName]." }

$roleName = "Contributor"
$assigneeObjectId = $managedIdentity_PrincipalId
# Check if the role assignment already exists
Write-Host "Checking RBAC on Cosmos DB Account"
$assignment = az role assignment list `
  --assignee $assigneeObjectId `
  --scope "$resourceId" `
  --query "[?roleDefinitionName=='$roleName']" `
  --output json | ConvertFrom-Json

if (-not $assignment) {
    Write-Host "RBAC assignment not found. Creating..."
    az role assignment create `
      --assignee $assigneeObjectId `
      --role "$roleName" `
      --scope "$resourceId"
} else {
    Write-Host "RBAC assignment already exists."
}

#-------------------------------------------------------------
#Write-Host "Getting Key Vault: Resource ID"
#-------------------------------------------------------------
# This is stubbed out for now. Nothing to do.
# Maybe assign RBAC > Key Vault Administrator to > deployer ServicePrincipal in order for secrets to be created.
# Key Vault Secrets User

#-------------------------------------------------------------
Write-Host "Getting Storage Account: Resource ID"
#-------------------------------------------------------------
Write-Host "Getting RBAC settings for Storage Account"
$resourceId = az storage account show --name $storageAccountName --resource-group $resourceGroupName --query "id" --output tsv
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to find Storage Account resource [$storageAccountName]." }
else { Write-Host "Found Storage Account resource [$storageAccountName]." }

$roleName = "Storage Blob Data Contributor"
$assigneeObjectId = $managedIdentity_PrincipalId
# Check if the role assignment already exists
Write-Host "Checking RBAC on Storage Account [$assigneeObjectId]"
$assignment = az role assignment list `
  --assignee $assigneeObjectId `
  --scope "$resourceId" `
  --query "[?roleDefinitionName=='$roleName']" `
  --output json | ConvertFrom-Json

if (-not $assignment) {
    Write-Host "RBAC assignment not found. Creating..."
    az role assignment create `
      --assignee $assigneeObjectId `
      --role "$roleName" `
      --scope "$resourceId"
} else {
    Write-Host "RBAC assignment already exists."
}

$assigneeObjectId = $appService_SystemManagedIdentity_ObjectId
Write-Host "Checking RBAC on Storage Account [$assigneeObjectId]"
$assignment = az role assignment list `
  --assignee $assigneeObjectId `
  --scope "$resourceId" `
  --query "[?roleDefinitionName=='$roleName']" `
  --output json | ConvertFrom-Json

if (-not $assignment) {
    Write-Host "RBAC assignment not found. Creating..."
    az role assignment create `
      --assignee $assigneeObjectId `
      --role "$roleName" `
      --scope "$resourceId"
} else {
    Write-Host "RBAC assignment already exists."
}

$paramDateTime_ScriptEnd = Get-Date
$timeSpan_ScriptExecution = $paramDateTime_ScriptEnd - $paramDateTime_ScriptStart
$formattedDateTime_ScriptExecution = "{0:00}:{1:00}:{2:00}" -f $timeSpan_ScriptExecution.Hours, $timeSpan_ScriptExecution.Minutes, $timeSpan_ScriptExecution.Seconds

Write-Host "---------------------------------------------------------------------------------------------" -ForegroundColor Green
Write-Host "Azure Resource Deployment Script Finished." -ForegroundColor Green
Write-Host "Script Started Date Time: [$paramDateTimeStamp]" -ForegroundColor Green
Write-Host "Script Completed Date Time: [$(($paramDateTime_ScriptEnd).ToString("yyyy-MM-dd HH:mm:ss"))]" -ForegroundColor Green
Write-Host "Script Execution Time: [$formattedDateTime_ScriptExecution]" -ForegroundColor Green
Write-Host "Review any warnings above for resources that may not have been created or configured fully." -ForegroundColor Green
Write-Host "Deployed to Resource Group: $($resourceGroupName) in $($paramLocation)" -ForegroundColor Green
Write-Host "---------------------------------------------------------------------------------------------" -ForegroundColor Green
