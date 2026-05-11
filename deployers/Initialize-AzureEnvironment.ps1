<#
.SYNOPSIS
This script initializes an Azure environment by creating and configuring necessary resources for deployment pipelines.

.DESCRIPTION
The `Initialize-AzureEnvironment.ps1` script performs the following tasks:
1. Verifies the user has "Owner" permissions on the current Azure subscription.
2. Creates an Azure resource group if it does not already exist.
3. Deploys an Azure Container Registry (ACR) and retrieves its credentials.
4. Deploys a new Azure OpenAI instance or reuses an existing one.
5. Outputs configuration details required for deployment scripts, ACR-based image builds, and GitHub Actions secrets.

.PARAMETER ResourceGroupName
The name of the Azure resource group to create or use.

.PARAMETER AzureRegion
The Azure region where resources will be deployed.

.PARAMETER ACRName
The name of the Azure Container Registry to create or use.

.PARAMETER OpenAiName
The name of the Azure OpenAI instance to create or use.

.PARAMETER UseExistingOpenAI
Reuse an existing Azure OpenAI resource or endpoint instead of creating a new Azure OpenAI resource.

.PARAMETER ExistingOpenAIEndpoint
Optional existing Azure OpenAI endpoint to use. If not provided and `UseExistingOpenAI` is specified,
the script attempts to resolve the endpoint from the existing Azure OpenAI resource metadata.

.PARAMETER ExistingOpenAIResourceGroup
Optional resource group containing the existing Azure OpenAI resource. Defaults to `ResourceGroupName`.

.PARAMETER ExistingOpenAISubscriptionId
Optional subscription ID containing the existing Azure OpenAI resource. Defaults to the current Azure subscription.

.PARAMETER AzureCloudEnvironment
Optional Azure cloud name. You can pass `AzureCloud`, `AzureUSGovernment`, or a custom Azure CLI cloud name.
If omitted during interactive use, the script prompts for the target cloud before login.

.EXAMPLE
.\Initialize-AzureEnvironment.ps1 -ResourceGroupName "myResourceGroup" -AzureRegion "eastus" -ACRName "myACR" -OpenAiName "myOpenAI"

This command initializes the Azure environment with the specified resource group, region, ACR, and OpenAI instance.

.EXAMPLE
.\Initialize-AzureEnvironment.ps1 -ResourceGroupName "myResourceGroup" -AzureRegion "eastus" -ACRName "myACR" -OpenAiName "sharedOpenAI" -UseExistingOpenAI -ExistingOpenAIResourceGroup "shared-ai-rg" -ExistingOpenAISubscriptionId "00000000-0000-0000-0000-000000000000"

This command initializes the Azure environment while reusing an existing Azure OpenAI resource.

.NOTES
- Ensure that the Azure CLI is installed and available on the `PATH` before running this script.
- The script requires the user to have "Owner" permissions on the Azure subscription.
- If you plan to use `az acr build`, the deployment identity must also be able to submit ACR Tasks in the target registry.
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory = $true)]
    [string]$AzureRegion,

    [Parameter(Mandatory = $true)]
    [string]$ACRName,

    [Parameter(Mandatory = $true)]
    [string]$OpenAiName,

    [Parameter(Mandatory = $false)]
    [switch]$UseExistingOpenAI,

    [Parameter(Mandatory = $false)]
    [string]$ExistingOpenAIEndpoint,

    [Parameter(Mandatory = $false)]
    [string]$ExistingOpenAIResourceGroup,

    [Parameter(Mandatory = $false)]
    [string]$ExistingOpenAISubscriptionId,

    [Parameter(Mandatory = $false)]
    [string]$AzureCloudEnvironment
)

function Write-InfoMessage {
    param([string]$Message)
    Write-Host "INFO: $Message" -ForegroundColor Cyan
}

function Write-SuccessMessage {
    param([string]$Message)
    Write-Host "SUCCESS: $Message" -ForegroundColor Green
}

function Write-WarningMessage {
    param([string]$Message)
    Write-Host "WARNING: $Message" -ForegroundColor Yellow
}

function Test-AzureCliAuthenticated {
    try {
        az account show --output none 2>$null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Test-AzureCloudExists {
    param([string]$CloudName)

    try {
        az cloud show --name $CloudName --output none 2>$null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Get-CurrentAzureCloudName {
    try {
        return (az cloud show --query name -o tsv 2>$null)
    }
    catch {
        return $null
    }
}

function Read-AzureCloudMenuSelection {
    param([int]$TimeoutSeconds = 10)

    $options = @(
        [PSCustomObject]@{ Key = '1'; Label = 'Public Azure'; Value = 'AzureCloud' },
        [PSCustomObject]@{ Key = '2'; Label = 'Azure Government'; Value = 'AzureUSGovernment' },
        [PSCustomObject]@{ Key = '3'; Label = 'Custom Azure CLI cloud'; Value = '__custom__' }
    )

    if (-not [Environment]::UserInteractive) {
        return $options[0].Value
    }

    try {
        $selectedIndex = 0
        $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
        $bufferWidth = 120
        $lastStatusLine = ""

        Write-Host "Select the Azure cloud to use:" -ForegroundColor Cyan
        for ($index = 0; $index -lt $options.Count; $index++) {
            Write-Host ("  [{0}] {1}" -f $options[$index].Key, $options[$index].Label)
        }
        Write-Host ""

        while ($true) {
            $remainingSeconds = [Math]::Max(0, [int][Math]::Ceiling(($deadline - [DateTime]::UtcNow).TotalSeconds))

            $statusLine = "Current selection: [{0}] {1}. Use Up/Down to change, Enter to confirm, or press 1-3. Default is #1 in {2}s." -f $options[$selectedIndex].Key, $options[$selectedIndex].Label, $remainingSeconds
            if ($statusLine -ne $lastStatusLine) {
                Write-Host (("`r" + $statusLine).PadRight($bufferWidth)) -NoNewline -ForegroundColor Green
                $lastStatusLine = $statusLine
            }

            if ($remainingSeconds -le 0) {
                Write-Host ""
                return $options[$selectedIndex].Value
            }

            $pollUntil = [DateTime]::UtcNow.AddMilliseconds(250)
            while ([DateTime]::UtcNow -lt $pollUntil) {
                if ([Console]::KeyAvailable) {
                    $key = [Console]::ReadKey($true)

                    switch ($key.Key) {
                        'UpArrow' {
                            $selectedIndex = if ($selectedIndex -eq 0) { $options.Count - 1 } else { $selectedIndex - 1 }
                            break
                        }
                        'DownArrow' {
                            $selectedIndex = if ($selectedIndex -eq ($options.Count - 1)) { 0 } else { $selectedIndex + 1 }
                            break
                        }
                        'Enter' {
                            Write-Host ""
                            return $options[$selectedIndex].Value
                        }
                        'D1' { Write-Host ""; return $options[0].Value }
                        'NumPad1' { Write-Host ""; return $options[0].Value }
                        'D2' { Write-Host ""; return $options[1].Value }
                        'NumPad2' { Write-Host ""; return $options[1].Value }
                        'D3' { Write-Host ""; return $options[2].Value }
                        'NumPad3' { Write-Host ""; return $options[2].Value }
                    }

                    switch ($key.KeyChar) {
                        '1' {
                            Write-Host ""
                            return $options[0].Value
                        }
                        '2' {
                            Write-Host ""
                            return $options[1].Value
                        }
                        '3' {
                            Write-Host ""
                            return $options[2].Value
                        }
                    }
                }

                Start-Sleep -Milliseconds 50
            }
        }
    }
    catch {
        Write-Host "Select the Azure cloud to use:" -ForegroundColor Cyan
        Write-Host "1. Public Azure (AzureCloud)"
        Write-Host "2. Azure Government (AzureUSGovernment)"
        Write-Host "3. Custom Azure CLI cloud"
        $selection = Read-Host "Enter 1, 2, or 3"

        switch ($selection.Trim()) {
            '1' { return 'AzureCloud' }
            '2' { return 'AzureUSGovernment' }
            '3' { return '__custom__' }
            default { return $null }
        }
    }
}

function Resolve-AzureCloudEnvironment {
    param([string]$RequestedCloudName)

    $candidateCloudName = $RequestedCloudName

    while ($true) {
        if ([string]::IsNullOrWhiteSpace($candidateCloudName)) {
            if (-not [Environment]::UserInteractive) {
                return 'AzureCloud'
            }

            $menuSelection = Read-AzureCloudMenuSelection

            if ($menuSelection -eq '__custom__') {
                $candidateCloudName = Read-Host "Enter the registered Azure CLI custom cloud name"
            } elseif (-not [string]::IsNullOrWhiteSpace($menuSelection)) {
                $candidateCloudName = $menuSelection
            } else {
                Write-WarningMessage "Invalid cloud selection."
                $candidateCloudName = $null
                continue
            }
        }

        if (Test-AzureCloudExists -CloudName $candidateCloudName) {
            return $candidateCloudName
        }

        if (-not [Environment]::UserInteractive) {
            throw "Azure CLI cloud '$candidateCloudName' is not registered. Register it first with 'az cloud register' or provide AzureCloud/AzureUSGovernment."
        }

        Write-WarningMessage "Azure CLI cloud '$candidateCloudName' is not registered on this machine."
        Write-InfoMessage "Use 'az cloud list -o table' to see available clouds, or 'az cloud register' for a custom cloud."
        $candidateCloudName = $null
    }
}

function Ensure-AzureCliAuthenticated {
    param([string]$RequestedCloudName)

    $targetCloudName = Resolve-AzureCloudEnvironment -RequestedCloudName $RequestedCloudName
    $currentCloudName = Get-CurrentAzureCloudName

    if ([string]::IsNullOrWhiteSpace($currentCloudName)) {
        Write-InfoMessage "Setting Azure CLI cloud to '$targetCloudName'."
        az cloud set --name $targetCloudName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to set Azure CLI cloud to '$targetCloudName'."
        }
    } elseif ($currentCloudName -ne $targetCloudName) {
        Write-InfoMessage "Switching Azure CLI cloud from '$currentCloudName' to '$targetCloudName'."
        az cloud set --name $targetCloudName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to switch Azure CLI cloud to '$targetCloudName'."
        }
    }

    if (Test-AzureCliAuthenticated) {
        Write-SuccessMessage "Azure CLI is authenticated"
        return $targetCloudName
    }

    if (-not [Environment]::UserInteractive) {
        throw "Azure CLI is not authenticated. Run 'az login' first or provide an authenticated non-interactive context."
    }

    Write-WarningMessage "Azure CLI is not authenticated for cloud '$targetCloudName'."
    Write-InfoMessage "Running 'az login'..."
    az login | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI login failed for cloud '$targetCloudName'."
    }

    if (-not (Test-AzureCliAuthenticated)) {
        throw "Azure CLI authentication could not be verified after login."
    }

    Write-SuccessMessage "Azure CLI is authenticated"
    return $targetCloudName
}

# Ensure Azure CLI is installed
if (-not (Get-Command "az" -ErrorAction SilentlyContinue)) {
    Write-Error "Azure CLI is not installed. Please install it before running this script."
    exit 1
}

Write-Host "***************************************************"
Write-Host "Initialize Azure Environment" -ForegroundColor Cyan
Write-Host "- Creates or validates the resource group, ACR, and Azure OpenAI"
Write-Host "- Enables ACR admin access for deployment credential retrieval"
Write-Host "- Produces values used by Azure CLI, AZD/Bicep, Terraform, and GitHub workflows"
Write-Host "***************************************************"

$AzureCloudEnvironment = Ensure-AzureCliAuthenticated -RequestedCloudName $AzureCloudEnvironment

Write-Host "***************************************************"
# Step 1: Verify the user is an owner of the subscription
$subscription = az account show --query id -o tsv
$userObjectId = az ad signed-in-user show --query id -o tsv

$existingOpenAiResourceGroupResolved = if ($ExistingOpenAIResourceGroup) { $ExistingOpenAIResourceGroup } else { $ResourceGroupName }
$existingOpenAiSubscriptionIdResolved = if ($ExistingOpenAISubscriptionId) { $ExistingOpenAISubscriptionId } else { $subscription }
$resolvedOpenAiEndpoint = $ExistingOpenAIEndpoint

$ownerAssignments = az role assignment list --assignee $userObjectId --subscription $subscription --query "[?roleDefinitionName=='Owner']" -o json
if (($ownerAssignments | ConvertFrom-Json).Count -eq 0) {
    Write-Error "You are not an Owner of the current subscription ($subscription)."
    exit 1
} else {
    Write-Host "Verified: You are an Owner on subscription $subscription."
}

Write-Host "Current Azure cloud: $AzureCloudEnvironment"
Write-Host "Current subscription: $subscription"

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
$acrResourceId = az acr show --name $ACRName --resource-group $ResourceGroupName --query "id" -o tsv

# Step 4: Deploy or reuse Azure OpenAI instance
if ($UseExistingOpenAI) {
    $openAiExists = az cognitiveservices account show --name $OpenAiName --resource-group $existingOpenAiResourceGroupResolved --subscription $existingOpenAiSubscriptionIdResolved --query "name" -o tsv 2>$null
    if (-not $openAiExists) {
        Write-Error "Existing Azure OpenAI instance '$OpenAiName' was not found in resource group '$existingOpenAiResourceGroupResolved' and subscription '$existingOpenAiSubscriptionIdResolved'."
        exit 1
    }

    if (-not $resolvedOpenAiEndpoint) {
        $resolvedOpenAiEndpoint = az cognitiveservices account show --name $OpenAiName --resource-group $existingOpenAiResourceGroupResolved --subscription $existingOpenAiSubscriptionIdResolved --query "properties.endpoint" -o tsv 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $resolvedOpenAiEndpoint) {
            Write-Error "Unable to resolve the endpoint for existing Azure OpenAI instance '$OpenAiName'."
            exit 1
        }
    }

    Write-Host "Using existing Azure OpenAI instance '$OpenAiName'."
    Write-Host "Azure OpenAI endpoint: $resolvedOpenAiEndpoint"
} else {
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
                    exit 1
                }
            } else {
                Write-Host "Azure OpenAI instance '$OpenAiName' deployed."
            }
    } else {
        Write-Warning "Azure OpenAI instance '$OpenAiName' already exists."
    }

    $resolvedOpenAiEndpoint = az cognitiveservices account show --name $OpenAiName --resource-group $ResourceGroupName --query "properties.endpoint" -o tsv 2>$null
}

Write-Host "***************************************************"
Write-Host "Deployment bootstrap values"
Write-Host "These values are useful for deployment scripts, ACR builds,"
Write-Host "and GitHub Actions secrets."
Write-Host "***************************************************"
Write-Host "ACR_NAME: $ACRName"
Write-Host "ACR_RESOURCE_GROUP: $ResourceGroupName"
Write-Host "ACR_RESOURCE_ID: $acrResourceId"
Write-Host "ACR_LOGIN_SERVER: $acrLoginServer"
Write-Host "ACR_PASSWORD: $acrPassword"
Write-Host "ACR_USERNAME: $acrUsername"
Write-Host "AZURE_CLOUD_ENVIRONMENT: $AzureCloudEnvironment"
Write-Host "AZURE_OPENAI_NAME: $OpenAiName"
Write-Host "AZURE_OPENAI_ENDPOINT: $resolvedOpenAiEndpoint"
Write-Host "AZURE_OPENAI_RESOURCE_GROUP: $(if ($UseExistingOpenAI) { $existingOpenAiResourceGroupResolved } else { $ResourceGroupName })"
Write-Host "AZURE_OPENAI_SUBSCRIPTION_ID: $(if ($UseExistingOpenAI) { $existingOpenAiSubscriptionIdResolved } else { $subscription })"
Write-Host "***************************************************"
Write-Host "Example ACR build command from the repository root:"
Write-Host "az acr build --registry $ACRName --file application/single_app/Dockerfile --image simple-chat:latest ."
Write-Host "***************************************************"
Write-Host "Azure environment initialization complete."
