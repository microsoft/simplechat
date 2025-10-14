#requires -Module Az.CosmosDB
#requires -Module Az.Accounts
param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    [Parameter(Mandatory=$true)]
    [string]$AccountName,
    [string]$DatabaseName = "SimpleChat",
    [ValidateRange(1000, 1000000)]
    [int]$NewMaxRU = 1000,
    [Parameter(Mandatory=$false, HelpMessage="Azure Cloud Environment: AzureCloud, AzureUSGovernment, Custom")]
    [ValidateSet("AzureCloud", "AzureUSGovernment", "Custom")]
    [string]$AzureCloudEnvironment = "AzureCloud"
)
$CloudEndpoint = ""
if ($AzureCloudEnvironment -eq "Custom")
{
    $CloudEndpoint = Read-Host "Enter the custom Azure Cloud Environment endpoint (e.g. https://management.azurecustom.you/)"
    if ([string]::IsNullOrEmpty($CloudEndpoint))
    {
        throw "Custom environment selected but no endpoint provided."
    }
    Write-Host "Using custom Azure Cloud Environment endpoint: $CloudEndpoint"
    $AzureCloudEnvironment = New-AzEnvironment -Name "Custom" -ActiveDirectoryAuthority "https://login.microsoftonline.com/" -ResourceManagerEndpoint $CloudEndpoint -GraphEndpoint "https://graph.windows.net/" -GalleryEndpoint "https://gallery.azure.com/" -ManagementEndpoint $CloudEndpoint -StorageEndpointSuffix "core.windows.net" -SqlDatabaseDnsSuffix "database.windows.net" -TrafficManagerDnsSuffix "trafficmanager.net" -KeyVaultDnsSuffix "vault.azure.net" -ServiceManagementUrl $CloudEndpoint
}

if ($(Get-AzContext)?.Account)
{
    Write-Host "Logged in as $((Get-AzContext).Account.Name)"
}
else
{
    Login-AzAccount -Environment $AzureCloudEnvironment -UseDeviceAuthentication
}

$subscriptionName = $(Get-AzContext)?.Subscription?.Name
while ($subChoice -notin ("Y","y","N","n"))
{
    $subChoice = Read-Host "Use subscription '$subscriptionName'? (Y/N)"
    if ($subChoice -eq "N")
    {
        $subscriptions = Get-AzSubscription
        $subscriptions | ForEach-Object { Write-Host "$($_.SubscriptionId): $($_.Name)" }
        $subId = Read-Host "Enter SubscriptionId to use"
        Set-AzContext -SubscriptionId $subId
        $subscriptionName = $(Get-AzContext)?.Subscription?.Name
        Write-Host "Using subscription '$subscriptionName'"
    }
    elseif ($subChoice -ne "Y")
    {
        Write-Host "Please enter Y or N."
    }
}

# Get all containers in the database
$containers = Get-AzCosmosDBSqlContainer -ResourceGroupName $ResourceGroup -AccountName $AccountName -DatabaseName $DatabaseName

foreach ($container in $containers) {
    $containerName = $container.Name
    Write-Host "Processing container: $containerName..."

    # Get current throughput settings
    $throughput = Get-AzCosmosDBSqlContainerThroughput -ResourceGroupName $ResourceGroup -AccountName $AccountName -DatabaseName $DatabaseName -Name $containerName -ErrorAction SilentlyContinue

    Write-Host "  Current Throughput Type: $($throughput.Throughput)"

    if ($null -eq $throughput) {
        Write-Warning "No throughput found for $containerName. Skipping."
        continue
    }

    if ($throughput.AutoscaleSettings.MaxThroughput -eq 0) {
        Write-Host "  Migrating $containerName from Manual to Autoscale (max $NewMaxRU RU/s)..."
        Invoke-AzCosmosDBSqlContainerThroughputMigration `
            -ResourceGroupName $ResourceGroup `
            -AccountName $AccountName `
            -DatabaseName $DatabaseName `
            -Name $containerName `
            -ThroughputType "Autoscale"
        Write-Host "Updating $containerName to $NewMaxRU RU/s"
        Update-AzCosmosDBSqlContainerThroughput `
            -ResourceGroupName $ResourceGroup `
            -AccountName $AccountName `
            -DatabaseName $DatabaseName `
            -Name $containerName `
            -AutoscaleMaxThroughput $NewMaxRU
        Write-Host "Updated $containerName to $NewMaxRU RU/s"
    } else {
        Write-Host "  $containerName already Autoscale. Updating max RU/s to $NewMaxRU..."
        Update-AzCosmosDBSqlContainerThroughput `
            -ResourceGroupName $ResourceGroup `
            -AccountName $AccountName `
            -DatabaseName $DatabaseName `
            -Name $containerName `
            -AutoscaleMaxThroughput $NewMaxRU
    }
}

Write-Host "All containers processed for autoscale ($($NewMaxRU*.10)-$NewMaxRU RU/s)."