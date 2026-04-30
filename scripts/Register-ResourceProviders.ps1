<#
.SYNOPSIS
Registers Azure resource providers required to deploy Simple Chat.

.DESCRIPTION
Scans a predefined list of provider namespaces derived from the deployer Bicep templates
and registers any that are not already registered. Optionally waits for registration
completion and supports retries with exponential backoff.

.PARAMETER SubscriptionId
Optional subscription ID to target. If provided, the script will set the active subscription.

.PARAMETER Providers
Optional list of provider namespaces to register. Defaults to the providers required by Simple Chat.

.PARAMETER Wait
If specified, waits for each provider to reach the "Registered" state.

.PARAMETER MaxWaitMinutes
Maximum time to wait for a provider registration to complete.

.PARAMETER MaxRetries
Maximum number of retries for transient registration failures.

.PARAMETER RetryDelaySeconds
Initial delay (in seconds) between retries. Uses exponential backoff.

.EXAMPLE
# Register all required providers in the current subscription
.\Register-ResourceProviders.ps1 -Wait

.EXAMPLE
# Register providers in a specific subscription
.\Register-ResourceProviders.ps1 -SubscriptionId "00000000-0000-0000-0000-000000000000" -Wait
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string] $SubscriptionId,

    [Parameter(Mandatory = $false)]
    [string[]] $Providers = @(
        'Microsoft.Authorization',
        'Microsoft.Cache',
        'Microsoft.CognitiveServices',
        'Microsoft.ContainerRegistry',
        'Microsoft.DocumentDB',
        'Microsoft.Insights',
        'Microsoft.KeyVault',
        'Microsoft.ManagedIdentity',
        'Microsoft.Network',
        'Microsoft.OperationalInsights',
        'Microsoft.Resources',
        'Microsoft.Search',
        'Microsoft.Storage',
        'Microsoft.VideoIndexer',
        'Microsoft.Web'
    ),

    [Parameter(Mandatory = $false)]
    [switch] $Wait,

    [Parameter(Mandatory = $false)]
    [int] $MaxWaitMinutes = 20,

    [Parameter(Mandatory = $false)]
    [int] $MaxRetries = 3,

    [Parameter(Mandatory = $false)]
    [int] $RetryDelaySeconds = 5
)

$ErrorActionPreference = 'Stop'

function Write-Log {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Message,

        [Parameter(Mandatory = $false)]
        [ValidateSet('INFO', 'WARN', 'ERROR')]
        [string] $Level = 'INFO'
    )

    $timestamp = (Get-Date).ToString('u')
    Write-Host "[$timestamp][$Level] $Message"
}

function Ensure-AzCli {
    if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
        throw 'Azure CLI (az) is required but was not found in PATH. Install Azure CLI and run "az login".'
    }
}

function Get-ProviderState {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Namespace
    )

    $state = az provider show --namespace $Namespace --query "registrationState" -o tsv
    if (-not $state) {
        return 'NotRegistered'
    }

    return $state
}

function Register-ProviderWithRetry {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Namespace
    )

    $attempt = 0
    $delay = $RetryDelaySeconds

    while ($attempt -lt $MaxRetries) {
        try {
            $attempt++
            Write-Log "Registering provider: $Namespace (attempt $attempt/$MaxRetries)"
            az provider register --namespace $Namespace | Out-Null
            return
        }
        catch {
            if ($attempt -ge $MaxRetries) {
                throw
            }

            Write-Log "Retrying provider registration for $Namespace in $delay seconds..." 'WARN'
            Start-Sleep -Seconds $delay
            $delay = [Math]::Min($delay * 2, 60)
        }
    }
}

function Wait-ForProvider {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Namespace
    )

    $deadline = (Get-Date).AddMinutes($MaxWaitMinutes)
    while ((Get-Date) -lt $deadline) {
        $state = Get-ProviderState -Namespace $Namespace
        if ($state -eq 'Registered') {
            Write-Log "Provider registered: $Namespace"
            return
        }

        Write-Log "Waiting for provider $Namespace to register (current: $state)..." 'INFO'
        Start-Sleep -Seconds 10
    }

    throw "Timed out waiting for provider $Namespace to register."
}

try {
    Ensure-AzCli

    if ($SubscriptionId) {
        Write-Log "Setting subscription to $SubscriptionId"
        az account set --subscription $SubscriptionId | Out-Null
    }

    foreach ($provider in $Providers) {
        $state = Get-ProviderState -Namespace $provider
        if ($state -eq 'Registered') {
            Write-Log "Already registered: $provider"
            continue
        }

        Register-ProviderWithRetry -Namespace $provider

        if ($Wait) {
            Wait-ForProvider -Namespace $provider
        }
    }

    Write-Log 'Provider registration complete.'
}
catch {
    Write-Log $_.Exception.Message 'ERROR'
    throw
}
