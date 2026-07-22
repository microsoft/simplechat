# Migration-StorageAccount.ps1
#Requires -Version 7.0

[CmdletBinding()]
param(
    [string]$SourceStorageAccount = "<source-account>",

    [string]$SourceSubscriptionId = "<source-subscription-id>",

    [string]$DestinationStorageAccount = "<destination-account>",

    [string]$DestinationSubscriptionId = "<destination-subscription-id>",

    [ValidateNotNullOrEmpty()]
    [string[]]$Containers = @(
        "user-documents",
        "group-documents",
        "public-documents",
        "group-chat",
        "personal-chat"
    ),

    [bool]$DifferentialMigration = $true,

    [bool]$ShowProgress = $true,

    [ValidateRange(1, 168)]
    [int]$SasExpiryHours = 48,

    [string]$StateFilePath = "",

    [switch]$ResetState
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Migration-State.ps1")

function Write-StorageMigrationProgress {
    param(
        [int]$CompletedCount,
        [int]$TotalCount,
        [string]$CurrentContainer = "",
        [switch]$Completed
    )

    if (-not $ShowProgress) {
        return
    }

    if ($Completed) {
        Write-Progress -Id 0 -Activity "Storage account migration" -Completed
        return
    }

    $percentComplete = if ($TotalCount -eq 0) {
        100
    }
    else {
        [int][Math]::Floor(($CompletedCount / $TotalCount) * 100)
    }
    $remainingCount = [Math]::Max(0, $TotalCount - $CompletedCount)
    $progressParameters = @{
        Id = 0
        Activity = "Storage account migration"
        Status = "Containers: $CompletedCount/$TotalCount | Remaining: $remainingCount | $percentComplete%"
        PercentComplete = $percentComplete
    }
    if (-not [string]::IsNullOrWhiteSpace($CurrentContainer)) {
        $progressParameters.CurrentOperation = "Current container: $CurrentContainer"
    }

    Write-Progress @progressParameters
}

function Test-StorageMigrationConfiguration {
    $configuredValues = [ordered]@{
        SourceStorageAccount = $SourceStorageAccount
        SourceSubscriptionId = $SourceSubscriptionId
        DestinationStorageAccount = $DestinationStorageAccount
        DestinationSubscriptionId = $DestinationSubscriptionId
    }
    foreach ($entry in $configuredValues.GetEnumerator()) {
        if (
            [string]::IsNullOrWhiteSpace($entry.Value) -or
            $entry.Value -match '^<[^>]+>$'
        ) {
            throw "Set '$($entry.Key)' in the script or supply it as a parameter."
        }
    }

    foreach ($accountName in @($SourceStorageAccount, $DestinationStorageAccount)) {
        if ($accountName -notmatch '^[a-z0-9]{3,24}$') {
            throw "Storage account name '$accountName' must contain 3-24 lowercase letters or numbers."
        }
    }

    foreach ($subscriptionId in @($SourceSubscriptionId, $DestinationSubscriptionId)) {
        $parsedSubscriptionId = [Guid]::Empty
        if (-not [Guid]::TryParse($subscriptionId, [ref]$parsedSubscriptionId)) {
            throw "Subscription ID '$subscriptionId' must be a valid GUID."
        }
    }

    if ([string]::Equals(
        $SourceStorageAccount,
        $DestinationStorageAccount,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Source and destination storage accounts must be different."
    }

    $containerNames = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($container in $Containers) {
        if (
            [string]::IsNullOrWhiteSpace($container) -or
            $container -notmatch '^(?!.*--)[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$'
        ) {
            throw "Container name '$container' is not a valid Azure Blob container name."
        }
        if (-not $containerNames.Add($container)) {
            throw "Container '$container' is listed more than once."
        }
    }
}

$migrationMode = if ($DifferentialMigration) { "differential" } else { "full" }
if ([string]::IsNullOrWhiteSpace($StateFilePath)) {
    $StateFilePath = Join-Path $PSScriptRoot "Migration-StorageAccount.state.json"
}
$migrationState = $null
$activeMigrationResource = $null

try {
    Test-StorageMigrationConfiguration

    $stateConfiguration = [ordered]@{
        sourceAccount = $SourceStorageAccount
        sourceSubscriptionId = $SourceSubscriptionId
        destinationAccount = $DestinationStorageAccount
        destinationSubscriptionId = $DestinationSubscriptionId
        containers = @($Containers)
        mode = $migrationMode
    }
    $migrationState = Initialize-MigrationState `
        -MigrationType "storage" `
        -StateFilePath $StateFilePath `
        -Configuration $stateConfiguration `
        -Reset:$ResetState
    Write-Host "Migration state: $($migrationState.Path)"

    foreach ($requiredCommand in @(
        "Connect-AzAccount",
        "Set-AzContext",
        "New-AzStorageContext",
        "Get-AzStorageContainer",
        "New-AzStorageContainer",
        "New-AzStorageContainerSASToken",
        "azcopy"
    )) {
        if (-not (Get-Command $requiredCommand -ErrorAction SilentlyContinue)) {
            throw "Required command '$requiredCommand' is not available."
        }
    }

    Connect-AzAccount | Out-Null

    Set-AzContext -SubscriptionId $SourceSubscriptionId | Out-Null
    $sourceContext = New-AzStorageContext `
        -StorageAccountName $SourceStorageAccount `
        -UseConnectedAccount

    Set-AzContext -SubscriptionId $DestinationSubscriptionId | Out-Null
    $destinationContext = New-AzStorageContext `
        -StorageAccountName $DestinationStorageAccount `
        -UseConnectedAccount

    $completedContainerCount = 0
    Write-Host "Starting $migrationMode storage account migration. Destination-only blobs will not be deleted."
    Write-StorageMigrationProgress `
        -CompletedCount 0 `
        -TotalCount $Containers.Count

    foreach ($container in $Containers) {
        Write-StorageMigrationProgress `
            -CompletedCount $completedContainerCount `
            -TotalCount $Containers.Count `
            -CurrentContainer $container
        Write-Host "Migrating container in $migrationMode mode: $container"

        if (Test-MigrationResourceCompleted `
            -Context $migrationState `
            -ResourceName $container) {
            $completedContainerCount++
            Write-Host "Skipping completed container from migration state: $container"
            Write-StorageMigrationProgress `
                -CompletedCount $completedContainerCount `
                -TotalCount $Containers.Count `
                -CurrentContainer $container
            continue
        }

        Start-MigrationResourceCheckpoint `
            -Context $migrationState `
            -ResourceName $container
        $activeMigrationResource = $container

        Set-AzContext -SubscriptionId $SourceSubscriptionId | Out-Null
        $sourceContainer = Get-AzStorageContainer `
            -Name $container `
            -Context $sourceContext
        if ($null -eq $sourceContainer) {
            throw "Source container '$container' does not exist in storage account '$SourceStorageAccount'."
        }

        $sasStartTime = (Get-Date).ToUniversalTime().AddMinutes(-15)
        $sasExpiryTime = (Get-Date).ToUniversalTime().AddHours($SasExpiryHours)
        $sourceSasUrl = New-AzStorageContainerSASToken `
            -Name $container `
            -Context $sourceContext `
            -Permission "rlt" `
            -Protocol HttpsOnly `
            -StartTime $sasStartTime `
            -ExpiryTime $sasExpiryTime `
            -FullUri

        Set-AzContext -SubscriptionId $DestinationSubscriptionId | Out-Null
        $destinationContainer = Get-AzStorageContainer `
            -Name $container `
            -Context $destinationContext
        if ($null -eq $destinationContainer) {
            New-AzStorageContainer `
                -Name $container `
                -Context $destinationContext | Out-Null
            Write-Host "Created destination container: $container"
        }

        $destinationSasUrl = New-AzStorageContainerSASToken `
            -Name $container `
            -Context $destinationContext `
            -Permission "racwdlt" `
            -Protocol HttpsOnly `
            -StartTime $sasStartTime `
            -ExpiryTime $sasExpiryTime `
            -FullUri

        if ($DifferentialMigration) {
            $azCopyArguments = @(
                "sync"
                $sourceSasUrl
                $destinationSasUrl
                "--recursive=true"
                "--delete-destination=false"
                "--s2s-preserve-blob-tags=true"
            )
        }
        else {
            $azCopyArguments = @(
                "copy"
                $sourceSasUrl
                $destinationSasUrl
                "--recursive=true"
                "--overwrite=true"
                "--s2s-preserve-properties=true"
                "--s2s-preserve-blob-tags=true"
            )
        }

        & azcopy @azCopyArguments

        if ($LASTEXITCODE -ne 0) {
            throw "AzCopy failed for container '$container' with exit code $LASTEXITCODE."
        }

        Complete-MigrationResourceCheckpoint `
            -Context $migrationState `
            -ResourceName $container `
            -Result ([ordered]@{
                Mode = $migrationMode
            })
        $activeMigrationResource = $null
        $completedContainerCount++
        Write-StorageMigrationProgress `
            -CompletedCount $completedContainerCount `
            -TotalCount $Containers.Count `
            -CurrentContainer $container
    }

    Complete-MigrationState `
        -Context $migrationState `
        -Summary ([ordered]@{
            ContainerCount = $completedContainerCount
        })
    Write-Host "Storage account migration completed successfully. Containers processed: $completedContainerCount"
}
catch {
    $migrationErrorMessage = $_.Exception.Message
    if ($null -ne $migrationState) {
        try {
            Set-MigrationStateFailure `
                -Context $migrationState `
                -ResourceName $activeMigrationResource `
                -ErrorMessage $migrationErrorMessage
        }
        catch {
            Write-Warning "Failed to update migration state after an error: $($_.Exception.Message)"
        }
    }
    Write-Error "Storage account migration failed: $migrationErrorMessage" -ErrorAction Continue
    throw
}
finally {
    Write-StorageMigrationProgress -CompletedCount 0 -TotalCount 0 -Completed
}