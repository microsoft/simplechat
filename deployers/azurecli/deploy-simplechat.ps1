<#
.SYNOPSIS
    Deploys the Simple Chat web application to Azure Government.
.DESCRIPTION
    This PowerShell script uses Azure CLI commands to provision a set of resources.
    It is designed to be highly configurable. Please review and update the
    Configuration Variables section before running.
.NOTES
    Author: Microsoft Federal
    Date: 2025-05-14
    Version: 1.0
    Prerequisites:
        - Azure CLI installed and authenticated. Run `az login` and `az account set --subscription <YourSubscriptionId>`
        - Permissions to create resources in the specified subscription and Entra ID tenant.

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
- Create a new Azure Open AI instance with the needed model deployments.
- Have an Azure Container Registry (ACR) created, admin user enabled, and the name is set in the script.
- Deploy an application image to the ACR.
- LOGIN to Azure Cli before running this script. See "LOGIN NOTES" above.

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
    - Configure a custom domain on you Azure OpenAI resources.  Otherwise, you will not be able to retrieve your OpenAI models
    and add your OpenAI endpoint. 

STEP 8) Test Web UI fully.
#>

$PSModuleAutoloadingPreference = "All"
Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

#---------------------------------------------------------------------------------------------
# Configuration Variables - MODIFY THESE VALUES AS NEEDED
#---------------------------------------------------------------------------------------------
$globalWhichAzurePlatform = "AzureCloud" # Set to "AzureUSGovernment" for Azure Government, "AzureCloud" for Azure Commercial
$paramTenantId = "" # Tenant ID
$paramLocation = "EastUS2" # Primary Azure region for deployments (e.g., eastus, eastus2, usgovvirginia, usgovarizona, usgovtexas)
$paramResourceOwnerId = "" # used for tagging resources
$paramEnvironment = "dev"  # Environment identifier (e.g., dev, test, prod, uat)
$paramBaseName = "simplechatexp"  # A short base name for your organization or project (e.g., contoso1, projectx2)
$ACR_NAME = "registrysimplechatexperimental" # Replace with your ACR name (must be globally unique, lowercase alphanumeric)
$IMAGE_NAME = "simplechatexp" # Replace with your image name

$param_UseExisting_OpenAi_Instance = $true
$param_Existing_AzureOpenAi_ResourceName = "aoai-global-team" # Azure OpenAI resource name
$param_Existing_AzureOpenAi_ResourceGroupName = "RG-AVD-East-Prod" # Azure OpenAI resource group name
$param_Existing_AzureOpenAi_SubscriptionId = "9698dd71-9367-49c2-bede-fd0deecfad62" # In case the resource is in another subscription
#$param_Existing_AzureOpenAi_Deployment_Model = "gpt-4o" # Azure OpenAI deployment name
#$param_Existing_AzureOpenAi_Deployment_Embeddings = "text-embedding-ada-002" # Azure OpenAI deployment model name

$paramCreateEntraSecurityGroups = $true # Set to true to create Entra ID security groups
$param_Existing_ResourceGroupName = "RG-SimpleChat-Experiemental" # Leave empty if not using an existing resource group name, one will be dynamically generated



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
} elseif ($globalWhichAzurePlatform -eq "AzureUSGovernment") {
    $paramCosmosDbUrlTemplate = "https://{0}.documents.azure.us:443/"
    $ACR_BASE_URL = "$ACR_NAME.azurecr.us"
    $paramRegistryServer = "https://$ACR_NAME.azurecr.us"
    $APPREG_REDIRECT_URI = "https://{0}.azurewebsites.us/.auth/login/aad/callback"
    $APPREG_REDIRECT_URI1 = "https://{0}.azurewebsites.us/getAToken"
    $APPREG_LOGOUT_URL = "https://{0}.azurewebsites.us/logout"
    $paramGraphUrl = "https://graph.microsoft.us"
    $paramArmUrl = "https://management.core.usgovcloudapi.net/"
    $param_AzureOpenAi_Url = "https://{0}.openai.azure.us/"
    $param_AiSearch_Url = "https://{0}.search.azure.us"
    $param_AppService_Environment = "usgovernment"
} elseif ($globalWhichAzurePlatform -eq "AzureSecret") {
    # SET THESE VALUES FOR il6 (information is tented)
    $paramCosmosDbUrlTemplate = ""
    $ACR_BASE_URL = ""
    $paramRegistryServer = ""
    $APPREG_REDIRECT_URI = ""
    $APPREG_REDIRECT_URI1 = ""
    $APPREG_LOGOUT_URL = ""
    $paramGraphUrl = ""
    $param_AzureOpenAi_Url = ""
} else {
    Write-Error "Invalid Azure platform specified. Please set to 'AzureUSGovernment', 'AzureCloud', or 'AzureSecret"
    exit 1
}

$paramDateTime_ScriptStart = Get-Date
$paramDateTimeStamp = ($paramDateTime_ScriptStart).ToString("yyyy-MM-dd HH:mm:ss")

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

# Check the ACR configuration
Write-Host "`n=====> Checking ACR: $($ACR_NAME) for admin user enabled..."
if ((az acr show --name $ACR_NAME --query "adminUserEnabled" --output tsv) -eq 'false') {
    Write-Host "Enabling admin user for ACR: $($ACR_NAME)..."
    az acr update --name $ACR_NAME --admin-enabled true
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to enable admin user for ACR '$($ACR_NAME)'. Ensure you have permissions." ; exit 1 } # Basic error check
} else {
    Write-Host "ACR: $($ACR_NAME) admin user is already enabled."
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

# --- Create Azure OpenAI Service ---
# Note: Azure OpenAI requires registration and sometimes specific SKU availability.
# This command might fail if the subscription is not enabled for OpenAI or if the SKU isn't available in the region.

$openAiUrl = $null
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
        --resource-type 'Microsoft.CognitiveServices/accounts' --subscription $param_Existing_AzureOpenAi_SubscriptionId --query "id"--output tsv

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
