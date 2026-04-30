<#
.SYNOPSIS
    Creates an Entra Enterprise Application with API permissions and client secret.

.DESCRIPTION
    This script automates the creation of an Entra Enterprise Application (App Registration) 
    with the required Microsoft Graph API permissions, app roles, and generates a client secret.
    It performs dependency checks before execution and provides detailed error handling.

.PARAMETER AppName
    Base name for the application (Required)

.PARAMETER Environment
    Environment identifier such as dev, qa, prod (Required)

.PARAMETER AppServiceName
    Name of the App Service for redirect URI construction (Optional, defaults to "$AppName-$Environment-app")

.PARAMETER SecretExpirationDays
    Days until secret expires (Optional, default: 180)

.PARAMETER AppRolesJsonPath
    Path to appRegistrationRoles.json file (Optional, default: ./appRegistrationRoles.json)

.PARAMETER AzureCloudEnvironment
    Optional Azure cloud name. You can pass AzureCloud, AzureUSGovernment, or a custom Azure CLI cloud name.
    If omitted during interactive use, the script prompts for the target cloud before login.

.EXAMPLE
    .\Initialize-EntraApplication.ps1 -AppName "simplechat" -Environment "dev" 

.EXAMPLE
    .\Initialize-EntraApplication.ps1 -AppName "simplechat" -Environment "dev" -AppRolesJsonPath "./azurecli/appRegistrationRoles.json"

    .EXAMPLE
    .\Initialize-EntraApplication.ps1 -AppName "simplechat" -Environment "prod" -AppServiceName "simplechat-prod-app" -SecretExpirationDays 365

.NOTES
    - Requires Azure CLI to be installed and authenticated
    - Auto-detects cloud environment (AzureCloud/AzureUSGovernment)
    - Auto-detects tenant ID from current Azure CLI session
    - Admin consent must be granted manually in Azure Portal after script completes
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$AppName,

    [Parameter(Mandatory = $false)]
    [string]$Environment,

    [Parameter(Mandatory = $false)]
    [string]$AppServiceName,

    [Parameter(Mandatory = $false)]
    [int]$SecretExpirationDays = 180,

    [Parameter(Mandatory = $false)]
    [string]$AppRolesJsonPath = "./appRegistrationRoles.json",

    [Parameter(Mandatory = $false)]
    [string]$AzureCloudEnvironment
)

# Script configuration
$ErrorActionPreference = "Stop"

#region Helper Functions

function Write-InfoMessage {
    param([string]$Message)
    Write-Host "INFO: $Message" -ForegroundColor Cyan
}

function Write-SuccessMessage {
    param([string]$Message)
    Write-Host "SUCCESS: $Message" -ForegroundColor Green
}

function Write-ErrorMessage {
    param([string]$Message)
    Write-Host "ERROR: $Message" -ForegroundColor Red
}

function Write-WarningMessage {
    param([string]$Message)
    Write-Host "WARNING: $Message" -ForegroundColor Yellow
}

function Get-CommandOutputText {
    param($CommandOutput)

    if ($null -eq $CommandOutput) {
        return ""
    }

    return (($CommandOutput | Out-String).Trim())
}

function Test-PermissionGrantRequiredMessage {
    param([string]$Message)

    return ($Message -match 'az ad app permission grant' -and $Message -match 'needed to make the change effective')
}

function Try-GrantAppPermissions {
    param(
        [string]$AppId,
        [string]$ApiId
    )

    $grantOutput = az ad app permission grant --id $AppId --api $ApiId --only-show-errors 2>&1
    $grantExitCode = $LASTEXITCODE
    $grantOutputText = Get-CommandOutputText -CommandOutput $grantOutput

    return [PSCustomObject]@{
        Succeeded  = ($grantExitCode -eq 0)
        OutputText = $grantOutputText
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

function Get-ValidationMessage {
    param(
        [string]$Value,
        [string]$DisplayName,
        [int]$MinLength,
        [int]$MaxLength,
        [string]$AllowedPattern,
        [string]$AllowedPatternDescription
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return "$DisplayName is required."
    }

    $validationIssues = @()

    if ($Value.Length -lt $MinLength -or $Value.Length -gt $MaxLength) {
        $validationIssues += "$DisplayName must be between $MinLength and $MaxLength characters long"
    }

    if ($Value -notmatch $AllowedPattern) {
        $validationIssues += "$DisplayName must use only $AllowedPatternDescription"
    }

    if ($validationIssues.Count -eq 0) {
        return $null
    }

    return ($validationIssues -join '; ') + '.'
}

function Resolve-ValidatedInput {
    param(
        [string]$InitialValue,
        [string]$DisplayName,
        [int]$MinLength,
        [int]$MaxLength,
        [string]$AllowedPattern,
        [string]$AllowedPatternDescription,
        [string]$PromptExample
    )

    $candidateValue = $InitialValue

    while ($true) {
        $validationMessage = Get-ValidationMessage `
            -Value $candidateValue `
            -DisplayName $DisplayName `
            -MinLength $MinLength `
            -MaxLength $MaxLength `
            -AllowedPattern $AllowedPattern `
            -AllowedPatternDescription $AllowedPatternDescription

        if (-not $validationMessage) {
            return $candidateValue
        }

        if (-not [Environment]::UserInteractive) {
            throw "$validationMessage Example: $PromptExample"
        }

        if (-not [string]::IsNullOrWhiteSpace($candidateValue)) {
            Write-WarningMessage "$DisplayName '$candidateValue' is incompatible. $validationMessage"
        } else {
            Write-WarningMessage $validationMessage
        }

        Write-InfoMessage "$DisplayName requirements: $MinLength-$MaxLength characters, $AllowedPatternDescription. Example: $PromptExample"
        $candidateValue = Read-Host "Enter $DisplayName"
    }
}

function Test-AzureCliInstalled {
    try {
        $azVersion = az version 2>&1 | Out-Null
        return $?
    }
    catch {
        return $false
    }
}

function Test-AzureCliAuthenticated {
    try {
        $account = az account show 2>&1
        return $?
    }
    catch {
        return $false
    }
}

function Get-CloudEnvironment {
    try {
        $cloudInfo = az cloud show --output json | ConvertFrom-Json
        return $cloudInfo.name
    }
    catch {
        throw "Failed to detect cloud environment: $_"
    }
}

function Get-GraphUrl {
    param([string]$CloudName)
    
    switch ($CloudName) {
        "AzureCloud" { return "https://graph.microsoft.com" }
        "AzureUSGovernment" { return "https://graph.microsoft.us" }
        default { return "https://graph.microsoft.com" }
    }
}

function Get-AppServiceDomain {
    param([string]$CloudName)
    
    switch ($CloudName) {
        "AzureCloud" { return "azurewebsites.net" }
        "AzureUSGovernment" { return "azurewebsites.us" }
        default { return "azurewebsites.net" }
    }
}

function Ensure-AzureCliAuthenticated {
    param([string]$RequestedCloudName)

    $targetCloudName = Resolve-AzureCloudEnvironment -RequestedCloudName $RequestedCloudName
    $currentCloudName = Get-CloudEnvironment

    if ($currentCloudName -ne $targetCloudName) {
        Write-InfoMessage "Switching Azure CLI cloud from '$currentCloudName' to '$targetCloudName'..."
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

#endregion

#region Main Script

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Entra Application Registration Setup" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

try {
    #region Dependency Checks

    $AppName = Resolve-ValidatedInput `
        -InitialValue $AppName `
        -DisplayName "AppName" `
        -MinLength 3 `
        -MaxLength 12 `
        -AllowedPattern '^[a-zA-Z0-9]+$' `
        -AllowedPatternDescription "letters and numbers only, with no spaces or hyphens" `
        -PromptExample "simplechat"

    $Environment = Resolve-ValidatedInput `
        -InitialValue $Environment `
        -DisplayName "Environment" `
        -MinLength 2 `
        -MaxLength 10 `
        -AllowedPattern '^[a-zA-Z0-9]+$' `
        -AllowedPatternDescription "letters and numbers only, with no spaces or hyphens" `
        -PromptExample "dev"

    if ([string]::IsNullOrWhiteSpace($AppServiceName)) {
        $AppServiceName = "$AppName-$Environment-app"
    }

    $appRegistrationName = "$AppName-$Environment-ar"
    
    Write-InfoMessage "Performing dependency checks..."
    
    # Check Azure CLI installation
    if (-not (Test-AzureCliInstalled)) {
        throw "Azure CLI is not installed. Please install Azure CLI from https://aka.ms/azure-cli"
    }
    Write-SuccessMessage "Azure CLI is installed"
    
    $cloudEnvironment = Ensure-AzureCliAuthenticated -RequestedCloudName $AzureCloudEnvironment
    
    # Check app roles JSON file exists
    if (-not (Test-Path $AppRolesJsonPath)) {
        throw "App roles JSON file not found at: $AppRolesJsonPath"
    }
    Write-SuccessMessage "App roles JSON file found: $AppRolesJsonPath"
    
    #endregion
    
    #region Detect Environment
    
    Write-InfoMessage "Detecting Azure environment..."
    
    # Get tenant ID
    $accountInfo = az account show --output json | ConvertFrom-Json
    $tenantId = $accountInfo.tenantId
    Write-InfoMessage "Tenant ID: $tenantId"
    
    Write-InfoMessage "Cloud Environment: $cloudEnvironment"
    
    # Get Graph URL
    $graphUrl = Get-GraphUrl -CloudName $cloudEnvironment
    Write-InfoMessage "Graph URL: $graphUrl"
    
    # Get App Service domain
    $appServiceDomain = Get-AppServiceDomain -CloudName $cloudEnvironment
    Write-InfoMessage "App Service Domain: $appServiceDomain"
    
    #endregion
    
    #region Construct Redirect URIs
    
    Write-InfoMessage "Constructing redirect URIs..."
    
    $redirectUri1 = "https://$AppServiceName.$appServiceDomain/.auth/login/aad/callback"
    $redirectUri2 = "https://$AppServiceName.$appServiceDomain/getAToken"
    $redirectUri3 = "https://$AppServiceName.$appServiceDomain"
    $logoutUrl = "https://$AppServiceName.$appServiceDomain/logout"
    
    Write-InfoMessage "Redirect URI 1: $redirectUri1"
    Write-InfoMessage "Redirect URI 2: $redirectUri2"
    Write-InfoMessage "Redirect URI 3: $redirectUri3"
    Write-InfoMessage "Logout URL: $logoutUrl"
    
    #endregion
    
    #region Create or Update App Registration
    
    Write-InfoMessage "Checking if app registration already exists: $appRegistrationName"
    
    $existingApp = az ad app list --display-name $appRegistrationName --output json | ConvertFrom-Json
    
    if ($existingApp -and $existingApp.Count -gt 0) {
        Write-WarningMessage "App registration '$appRegistrationName' already exists"
        $appRegistration = $existingApp[0]
        Write-InfoMessage "Existing App ID: $($appRegistration.appId)"
    }
    else {
        Write-InfoMessage "Creating new app registration: $appRegistrationName"
        
        $appRegistration = az ad app create `
            --display-name $appRegistrationName `
            --web-redirect-uris $redirectUri1 $redirectUri2 $redirectUri3 `
            --output json | ConvertFrom-Json
        
        if (-not $appRegistration) {
            throw "Failed to create app registration"
        }
        
        Write-SuccessMessage "App registration created: $appRegistrationName"
        Write-InfoMessage "App ID: $($appRegistration.appId)"
        Write-InfoMessage "Object ID: $($appRegistration.id)"
    }
    
    #endregion
    
    #region Create Service Principal
    
    Write-InfoMessage "Checking if service principal exists..."
    
    $existingSp = az ad sp list --filter "appId eq '$($appRegistration.appId)'" --output json | ConvertFrom-Json
    
    if ($existingSp -and $existingSp.Count -gt 0) {
        Write-InfoMessage "Service principal already exists"
        $servicePrincipal = $existingSp[0]
    }
    else {
        Write-InfoMessage "Creating service principal..."
        
        $servicePrincipal = az ad sp create --id $appRegistration.appId --output json | ConvertFrom-Json
        
        if (-not $servicePrincipal) {
            throw "Failed to create service principal"
        }
        
        Write-SuccessMessage "Service principal created"
    }
    
    Write-InfoMessage "Service Principal Object ID: $($servicePrincipal.id)"
    
    #endregion
    
    #region Configure App Roles
    
    Write-InfoMessage "Configuring app roles from: $AppRolesJsonPath"
    
    try {
        az ad app update --id $appRegistration.id --app-roles "@$AppRolesJsonPath"
        Write-SuccessMessage "App roles configured successfully"
    }
    catch {
        Write-WarningMessage "Failed to configure app roles: $_"
        Write-InfoMessage "App roles can be configured manually in Azure Portal"
    }
    
    #endregion
    
    #region Configure Web Settings
    
    Write-InfoMessage "Configuring logout URL..."
    
    try {
        $body = @{ web = @{ logoutUrl = $logoutUrl } } | ConvertTo-Json -Compress

        $logoutResult = az rest --method PATCH `
            --uri "$graphUrl/v1.0/applications/$($appRegistration.id)" `
            --headers "Content-Type=application/json" `
            --body ($body -replace '"', '\"') 2>&1

        if ($LASTEXITCODE -ne 0) {
            throw "Failed to configure logout URL. Azure CLI returned: $(Get-CommandOutputText -CommandOutput $logoutResult)"
        }

        Write-SuccessMessage "Logout URL configured"
    }
    catch {
        Write-WarningMessage "Failed to configure logout URL: $_"
        Write-InfoMessage "Logout URL can be configured manually in Azure Portal"
    }
    
    #endregion
    
    #region Enable Token Issuance
    
    Write-InfoMessage "Enabling ID token and access token issuance..."
    
    try {
        az ad app update --id $appRegistration.id `
            --enable-id-token-issuance true `
            --enable-access-token-issuance true
        
        Write-SuccessMessage "Token issuance enabled"
    }
    catch {
        Write-WarningMessage "Failed to enable token issuance: $_"
        Write-InfoMessage "Token settings can be configured manually in Azure Portal"
    }
    
    #endregion
    
    #region Add API Permissions
    
    Write-InfoMessage "Adding Microsoft Graph API permissions..."
    
    $microsoftGraphId = "00000003-0000-0000-c000-000000000000"
    
    # Define required permissions (all delegated)
    $permissions = @(
        @{ Name = "User.Read"; Id = "e1fe6dd8-ba31-4d61-89e7-88639da4683d" },
        @{ Name = "profile"; Id = "14dad69e-099b-42c9-810b-d002981feec1" },
        @{ Name = "email"; Id = "64a6cdd6-aab1-4aaf-94b8-3cc8405e90d0" },
        @{ Name = "Group.Read.All"; Id = "5f8c59db-677d-491f-a6b8-5f174b11ec1d" },
        @{ Name = "offline_access"; Id = "7427e0e9-2fba-42fe-b0c0-848c9e6a8182" },
        @{ Name = "openid"; Id = "37f7f235-527c-4136-accd-4a02d197296e" },
        @{ Name = "People.Read.All"; Id = "b340eb25-3456-403f-be2f-af7a0d370277" },
        @{ Name = "User.ReadBasic.All"; Id = "b4e74841-8e56-480b-be8b-910348b18b4c" }
    )
    
    $permissionErrors = @()
    $permissionsRequiringPortalConsent = @()
    $permissionGrantAttempted = $false
    $permissionGrantSucceeded = $false
    $permissionGrantOutput = ""
    
    foreach ($permission in $permissions) {
        try {
            Write-InfoMessage "Adding permission: $($permission.Name)"

            $permissionResult = az ad app permission add `
                --id $appRegistration.appId `
                --api $microsoftGraphId `
                --only-show-errors `
                --api-permissions "$($permission.Id)=Scope" 2>&1

            $permissionResultText = Get-CommandOutputText -CommandOutput $permissionResult

            if ($LASTEXITCODE -ne 0) {
                if (Test-PermissionGrantRequiredMessage -Message $permissionResultText) {
                    Write-SuccessMessage "Added: $($permission.Name)"

                    if (-not $permissionGrantAttempted) {
                        Write-InfoMessage "Azure CLI indicates that a permission grant is needed. Attempting 'az ad app permission grant'..."
                        $grantResult = Try-GrantAppPermissions -AppId $appRegistration.appId -ApiId $microsoftGraphId
                        $permissionGrantAttempted = $true
                        $permissionGrantSucceeded = $grantResult.Succeeded
                        $permissionGrantOutput = $grantResult.OutputText

                        if ($permissionGrantSucceeded) {
                            Write-SuccessMessage "Permission grant command completed successfully."
                        } else {
                            Write-WarningMessage "Permission grant command did not complete successfully."
                            if (-not [string]::IsNullOrWhiteSpace($permissionGrantOutput)) {
                                Write-WarningMessage $permissionGrantOutput
                            }
                        }
                    }

                    if (-not $permissionGrantSucceeded) {
                        $permissionsRequiringPortalConsent += $permission.Name
                        Write-InfoMessage "Permission '$($permission.Name)' still needs portal approval or admin consent to become effective."
                    }

                    continue
                }

                throw $permissionResultText
            }

            Write-SuccessMessage "Added: $($permission.Name)"

            if (-not [string]::IsNullOrWhiteSpace($permissionResultText) -and (Test-PermissionGrantRequiredMessage -Message $permissionResultText)) {
                if (-not $permissionGrantAttempted) {
                    Write-InfoMessage "Azure CLI indicates that a permission grant is needed. Attempting 'az ad app permission grant'..."
                    $grantResult = Try-GrantAppPermissions -AppId $appRegistration.appId -ApiId $microsoftGraphId
                    $permissionGrantAttempted = $true
                    $permissionGrantSucceeded = $grantResult.Succeeded
                    $permissionGrantOutput = $grantResult.OutputText

                    if ($permissionGrantSucceeded) {
                        Write-SuccessMessage "Permission grant command completed successfully."
                    } else {
                        Write-WarningMessage "Permission grant command did not complete successfully."
                        if (-not [string]::IsNullOrWhiteSpace($permissionGrantOutput)) {
                            Write-WarningMessage $permissionGrantOutput
                        }
                    }
                }

                if (-not $permissionGrantSucceeded) {
                    $permissionsRequiringPortalConsent += $permission.Name
                    Write-InfoMessage "Permission '$($permission.Name)' still needs portal approval or admin consent to become effective."
                }
            }
        }
        catch {
            $permissionErrorMessage = "Failed to add $($permission.Name): $_"
            $permissionErrors += $permissionErrorMessage
            Write-WarningMessage $permissionErrorMessage
        }
    }

    if ($permissionsRequiringPortalConsent.Count -gt 0) {
        $uniquePermissionsRequiringPortalConsent = $permissionsRequiringPortalConsent | Sort-Object -Unique
        Write-WarningMessage "Some permissions still require portal approval or admin consent to become effective."
        Write-InfoMessage "Permissions awaiting approval: $($uniquePermissionsRequiringPortalConsent -join ', ')"
        Write-InfoMessage "Open Azure Portal > Entra ID > App registrations > $appRegistrationName > API permissions, then grant admin consent if required by your tenant."
    }
    
    if ($permissionErrors.Count -eq 0) {
        Write-SuccessMessage "All API permissions added successfully"
    }
    else {
        Write-WarningMessage "Some permissions could not be added automatically"
        Write-InfoMessage "Review the warnings above, then add or approve any missing permissions in Azure Portal if needed."
    }
    
    #endregion
    
    #region Generate Client Secret
    
    Write-InfoMessage "Generating client secret (expires in $SecretExpirationDays days)..."
    
    # Calculate expiration date
    $expirationDate = (Get-Date).AddDays($SecretExpirationDays).ToString("yyyy-MM-dd")
    
    $clientSecret = az ad app credential reset `
        --id $appRegistration.appId `
        --append `
        --end-date $expirationDate `
        --query password `
        --output tsv
    
    if (-not $clientSecret) {
        throw "Failed to generate client secret"
    }
    
    Write-SuccessMessage "Client secret generated successfully"
    
    #endregion
    
    #region Display Results
    
    Write-Host "`n========================================" -ForegroundColor Green
    Write-Host "App Registration Created Successfully!" -ForegroundColor Green
    Write-Host "========================================`n" -ForegroundColor Green
    
    Write-Host "Application Name:       $appRegistrationName" -ForegroundColor White
    Write-Host "Client ID:              $($appRegistration.appId)" -ForegroundColor White
    Write-Host "Tenant ID:              $tenantId" -ForegroundColor White
    Write-Host "Service Principal ID:   $($servicePrincipal.id)" -ForegroundColor White
    Write-Host "Client Secret:          $clientSecret" -ForegroundColor Yellow
    Write-Host "Secret Expiration:      $expirationDate" -ForegroundColor White
    
    Write-Host "`n========================================" -ForegroundColor Yellow
    Write-Host "MANUAL STEPS REQUIRED" -ForegroundColor Yellow
    Write-Host "========================================`n" -ForegroundColor Yellow
    
    Write-Host "1. Grant Admin Consent for API Permissions:" -ForegroundColor White
    Write-Host "   - Navigate to Azure Portal > Entra ID > App registrations" -ForegroundColor Gray
    Write-Host "   - Find app: $appRegistrationName" -ForegroundColor Gray
    Write-Host "   - Go to API permissions" -ForegroundColor Gray
    Write-Host "   - Click 'Grant admin consent for [Tenant]'" -ForegroundColor Gray
    
    Write-Host "`n2. Assign Users/Groups to Enterprise Application:" -ForegroundColor White
    Write-Host "   - Navigate to Azure Portal > Entra ID > Enterprise applications" -ForegroundColor Gray
    Write-Host "   - Find app: $appRegistrationName" -ForegroundColor Gray
    Write-Host "   - Go to Users and groups" -ForegroundColor Gray
    Write-Host "   - Add user/group assignments with appropriate app roles" -ForegroundColor Gray
    
    Write-Host "`n3. Store the Client Secret Securely:" -ForegroundColor White
    Write-Host "   - Save the client secret in Azure Key Vault or secure credential store" -ForegroundColor Gray
    Write-Host "   - The secret value is shown above and will not be displayed again" -ForegroundColor Gray
    
    Write-Host "`n========================================`n" -ForegroundColor Cyan
    
    #endregion
}
catch {
    Write-Host "`n========================================" -ForegroundColor Red
    Write-Host "Script Execution Failed" -ForegroundColor Red
    Write-Host "========================================`n" -ForegroundColor Red
    
    Write-ErrorMessage $_.Exception.Message
    Write-Host "`nStack Trace:" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor Gray
    
    Write-Host "`nTroubleshooting Tips:" -ForegroundColor Yellow
    Write-Host "- Ensure you have appropriate permissions in Entra ID (Application Administrator or Global Administrator)" -ForegroundColor Gray
    Write-Host "- Verify Azure CLI is up to date: az upgrade" -ForegroundColor Gray
    Write-Host "- Check you're logged into the correct tenant: az account show" -ForegroundColor Gray
    Write-Host "- Verify the app service name is correct and follows naming conventions" -ForegroundColor Gray
    
    exit 1
}

#endregion
