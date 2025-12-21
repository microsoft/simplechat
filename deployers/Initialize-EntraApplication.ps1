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
    [Parameter(Mandatory = $true)]
    [ValidateLength(3, 12)]                # Length between 3 and 12
    [ValidatePattern('^[a-zA-Z0-9]+$')]    # Only letters and numbers
    [string]$AppName,

    [Parameter(Mandatory = $true)]
    [ValidateLength(2, 10)]                # Length between 2 and 10
    [ValidatePattern('^[a-zA-Z0-9]+$')]    # Only letters and numbers
    [string]$Environment,

    [Parameter(Mandatory = $false)]
    [string]$AppServiceName = "$AppName-$Environment-app",

    [Parameter(Mandatory = $false)]
    [int]$SecretExpirationDays = 180,

    [Parameter(Mandatory = $false)]
    [string]$AppRolesJsonPath = "./appRegistrationRoles.json"
)

# Script configuration
$ErrorActionPreference = "Stop"
$appRegistrationName = "$AppName-$Environment-ar"

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

#endregion

#region Main Script

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Entra Application Registration Setup" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

try {
    #region Dependency Checks
    
    Write-InfoMessage "Performing dependency checks..."
    
    # Check Azure CLI installation
    if (-not (Test-AzureCliInstalled)) {
        throw "Azure CLI is not installed. Please install Azure CLI from https://aka.ms/azure-cli"
    }
    Write-SuccessMessage "Azure CLI is installed"
    
    # Check Azure CLI authentication
    if (-not (Test-AzureCliAuthenticated)) {
        throw "Azure CLI is not authenticated. Please run 'az login' first"
    }
    Write-SuccessMessage "Azure CLI is authenticated"
    
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
    
    # Get cloud environment
    $cloudEnvironment = Get-CloudEnvironment
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
        
        az rest --method PATCH `
            --uri "$graphUrl/v1.0/applications/$($appRegistration.id)" `
            --headers "Content-Type=application/json" `
            --body $body | Out-Null
        
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
    
    foreach ($permission in $permissions) {
        try {
            Write-InfoMessage "Adding permission: $($permission.Name)"
            
            az ad app permission add `
                --id $appRegistration.id `
                --api $microsoftGraphId `
                --api-permissions "$($permission.Id)=Scope" 2>&1 | Out-Null
            
            Write-SuccessMessage "Added: $($permission.Name)"
        }
        catch {
            $permissionErrors += "Failed to add $($permission.Name): $_"
            Write-WarningMessage "Failed to add permission $($permission.Name)"
        }
    }
    
    if ($permissionErrors.Count -eq 0) {
        Write-SuccessMessage "All API permissions added successfully"
    }
    else {
        Write-WarningMessage "Some permissions could not be added automatically"
        Write-InfoMessage "Missing permissions can be added manually in Azure Portal"
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
