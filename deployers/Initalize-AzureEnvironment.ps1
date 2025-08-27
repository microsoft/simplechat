<#
.SYNOPSIS
This script initializes an Azure environment by creating and configuring necessary resources for deployment pipelines.

.DESCRIPTION
The `Initialize-AzureEnvironment.ps1` script performs the following tasks:
1. Verifies the user has "Owner" permissions on the current Azure subscription.
2. Creates an Azure resource group if it does not already exist.
3. Deploys an Azure Container Registry (ACR) and retrieves its credentials.
4. Deploys an Azure OpenAI instance.
5. Outputs configuration details required for GitHub Actions secrets.

.PARAMETER ResourceGroupName
The name of the Azure resource group to create or use.

.PARAMETER AzureRegion
The Azure region where resources will be deployed.

.PARAMETER ACRName
The name of the Azure Container Registry to create or use.

.PARAMETER OpenAiName
The name of the Azure OpenAI instance to create or use.

.EXAMPLE
.\Initialize-AzureEnvironment.ps1 -ResourceGroupName "myResourceGroup" -AzureRegion "eastus" -ACRName "myACR" -OpenAiName "myOpenAI"

This command initializes the Azure environment with the specified resource group, region, ACR, and OpenAI instance.

.NOTES
- Ensure that the Azure CLI is installed and available on the `PATH` before running this script.
- The script requires the user to have "Owner" permissions on the Azure subscription.
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory = $true)]
    [string]$AzureRegion,

    [Parameter(Mandatory = $true)]
    [string]$ACRName,

    [Parameter(Mandatory = $true)]
    [string]$OpenAiName
)

# Ensure Azure CLI is installed
if (-not (Get-Command "az" -ErrorAction SilentlyContinue)) {
    Write-Error "Azure CLI is not installed. Please install it before running this script."
    exit 1
}
Write-Host "***************************************************"
# Step 1: Verify the user is an owner of the subscription
$subscription = az account show --query id -o tsv
$userObjectId = az ad signed-in-user show --query id -o tsv

$ownerAssignments = az role assignment list --assignee $userObjectId --subscription $subscription --query "[?roleDefinitionName=='Owner']" -o json
if (($ownerAssignments | ConvertFrom-Json).Count -eq 0) {
    Write-Error "You are not an Owner of the current subscription ($subscription)."
    exit 1
} else {
    Write-Host "Verified: You are an Owner on subscription $subscription."
}

# Check if the ACR name is available
$ACRNameAvailable = az acr check-name --name $ACRName -o json | ConvertFrom-Json
$acrExists = az acr show --name $ACRName --resource-group $ResourceGroupName --query "name" -o tsv 2>$null
if ($ACRNameAvailable.nameAvailable -eq $false -and -not $acrExists) {
    Write-Error "Azure Container Registry name '$ACRName' is not available."
    Write-Error $ACRNameAvailable.message
    exit 1
}

# Step 2: Create a resource group (if it doesn't exist)
$rgExists = az group exists --name $ResourceGroupName
if ($rgExists -eq "false") {
    az group create --name $ResourceGroupName --location $AzureRegion | Out-Null
    Write-Host "Resource group '$ResourceGroupName' created in region '$AzureRegion'."
} else {
    Write-Warning "Resource group '$ResourceGroupName' already exists."
}

# Step 3: Deploy Azure Container Registry
$acrExists = az acr show --name $ACRName --resource-group $ResourceGroupName --query "name" -o tsv 1> $null 2>$null
if (-not $acrExists) {
    az acr create --name $ACRName --resource-group $ResourceGroupName --location $AzureRegion --sku Standard --admin-enabled true | Out-Null
    Write-Host "Azure Container Registry '$ACRName' deployed."
} else {
    Write-Warning "Azure Container Registry '$ACRName' already exists."
    # Ensure admin is enabled for credential retrieval
    az acr update --name $ACRName --resource-group $ResourceGroupName --admin-enabled true | Out-Null
}

# Retrieve ACR credentials
$acrCreds = az acr credential show --name $ACRName --resource-group $ResourceGroupName | ConvertFrom-Json
$acrUsername = $acrCreds.username
$acrPassword = $acrCreds.passwords[0].value
$acrLoginServer = az acr show --name $ACRName --resource-group $ResourceGroupName --query "loginServer" -o tsv

# Step 4: Deploy Azure OpenAI instance
$openAiExists = az cognitiveservices account show --name $OpenAiName --resource-group $ResourceGroupName --query "name" -o tsv 2>$null
if (-not $openAiExists) {
        $cmdOutput = az cognitiveservices account create `
            --name $OpenAiName `
            --resource-group $ResourceGroupName `
            --kind OpenAI `
            --sku S0 `
            --location $AzureRegion `
            --yes 2>&1
        $exitCode = $LASTEXITCODE
        $errMsg = $cmdOutput
        if ($exitCode -ne 0) {
            if ($errMsg -match "deleted"){
                write-warning "Cognitive Services account '$OpenAiName' appears to be soft-deleted. Attempting recovery..."
                $recoverOutput = az cognitiveservices account recover --name $OpenAiName --resource-group $ResourceGroupName --location $AzureRegion 2>&1
                if ($LASTEXITCODE -ne 0) {
                    Write-Error "Failed to recover Cognitive Services account '$OpenAiName'. Error: $($recoverOutput | Out-String)"
                    exit 1
                } else {
                    write-host "Recovered soft-deleted Cognitive Services account '$OpenAiName'."
                }
            } else {
                write-error "Failed to create Cognitive Services account '$OpenAiName'. Error: $($errMsg | Out-String)"
            }
            
        } else {
            Write-Host "Azure OpenAI instance '$OpenAiName' deployed."
        }    
} else {
    Write-Warning "Azure OpenAI instance '$OpenAiName' already exists."
}

Write-Host "***************************************************"
Write-Host "The information provided below must be configured"
Write-Host "   as secrets in the target Github Repo."
Write-Host "***************************************************"
Write-Host "ACR_LOGIN_SERVER: $acrLoginServer"
Write-Host "ACR_PASSWORD: $acrPassword"
Write-Host "ACR_USERNAME: $acrUsername"
Write-Host "***************************************************"
Write-Host "Azure environment initialization complete."
