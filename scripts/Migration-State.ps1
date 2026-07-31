# Migration-State.ps1

function Get-MigrationStateUtcTimestamp {
    return [DateTime]::UtcNow.ToString(
        "o",
        [System.Globalization.CultureInfo]::InvariantCulture
    )
}

function Get-MigrationStateFingerprint {
    param(
        [System.Collections.IDictionary]$Configuration
    )

    $configurationJson = ConvertTo-Json `
        -InputObject $Configuration `
        -Depth 100 `
        -Compress
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha256.ComputeHash(
            [System.Text.Encoding]::UTF8.GetBytes($configurationJson)
        )
    }
    finally {
        $sha256.Dispose()
    }
    return [Convert]::ToHexString($hash).ToLowerInvariant()
}

function ConvertTo-MigrationStateResult {
    param(
        [AllowNull()]
        [object]$Result
    )

    $converted = [ordered]@{}
    if ($null -eq $Result) {
        return $converted
    }

    if ($Result -is [System.Collections.IDictionary]) {
        foreach ($key in $Result.Keys) {
            $converted[[string]$key] = $Result[$key]
        }
        return $converted
    }

    foreach ($property in $Result.PSObject.Properties) {
        $converted[$property.Name] = $property.Value
    }
    return $converted
}

function Save-MigrationState {
    param(
        [object]$Context
    )

    $Context.Data["updatedUtc"] = Get-MigrationStateUtcTimestamp
    $stateDirectory = [IO.Path]::GetDirectoryName($Context.Path)
    if (-not [string]::IsNullOrWhiteSpace($stateDirectory)) {
        [IO.Directory]::CreateDirectory($stateDirectory) | Out-Null
    }

    $temporaryPath = "$($Context.Path).$PID.tmp"
    $stateJson = ConvertTo-Json `
        -InputObject $Context.Data `
        -Depth 100
    try {
        [IO.File]::WriteAllText(
            $temporaryPath,
            "$stateJson`n",
            [System.Text.UTF8Encoding]::new($false)
        )
        [IO.File]::Move($temporaryPath, $Context.Path, $true)
    }
    finally {
        if ([IO.File]::Exists($temporaryPath)) {
            [IO.File]::Delete($temporaryPath)
        }
    }
}

function Initialize-MigrationState {
    param(
        [string]$MigrationType,
        [string]$StateFilePath,
        [System.Collections.IDictionary]$Configuration,
        [string]$MigrationId = "",
        [switch]$Reset
    )

    if ([string]::IsNullOrWhiteSpace($StateFilePath)) {
        throw "StateFilePath cannot be empty when migration state tracking is enabled."
    }

    $requestedMigrationId = [Guid]::Empty
    if (
        -not [string]::IsNullOrWhiteSpace($MigrationId) -and
        -not [Guid]::TryParse($MigrationId, [ref]$requestedMigrationId)
    ) {
        throw "MigrationId must be a valid GUID."
    }

    $absoluteStatePath = [IO.Path]::GetFullPath(
        [Environment]::ExpandEnvironmentVariables($StateFilePath.Trim())
    )
    if ($Reset -and [IO.File]::Exists($absoluteStatePath)) {
        [IO.File]::Delete($absoluteStatePath)
    }

    $fingerprint = Get-MigrationStateFingerprint -Configuration $Configuration
    if ([IO.File]::Exists($absoluteStatePath)) {
        try {
            $state = [IO.File]::ReadAllText($absoluteStatePath) |
                ConvertFrom-Json -AsHashtable -Depth 100
        }
        catch {
            throw "Migration state file '$absoluteStatePath' is not valid JSON. Use -ResetState after preserving it for investigation."
        }

        if ([int]$state["schemaVersion"] -ne 1) {
            throw "Migration state file '$absoluteStatePath' uses an unsupported schema version."
        }
        if (-not [string]::Equals(
            [string]$state["migrationType"],
            $MigrationType,
            [System.StringComparison]::Ordinal
        )) {
            throw "Migration state file '$absoluteStatePath' belongs to a different migration type."
        }
        if (-not [string]::Equals(
            [string]$state["configurationFingerprint"],
            $fingerprint,
            [System.StringComparison]::Ordinal
        )) {
            throw "Migration state file '$absoluteStatePath' does not match the current source, destination, or mode. Use a different -StateFilePath or pass -ResetState."
        }
        if ($null -eq $state["resources"]) {
            $state["resources"] = [ordered]@{}
        }
        $storedMigrationId = [Guid]::Empty
        if (
            -not [string]::IsNullOrWhiteSpace([string]$state["migrationId"]) -and
            -not [Guid]::TryParse([string]$state["migrationId"], [ref]$storedMigrationId)
        ) {
            throw "Migration state file '$absoluteStatePath' contains an invalid migrationId. Use -ResetState after preserving it for investigation."
        }
        if ($storedMigrationId -eq [Guid]::Empty) {
            $storedMigrationId = if ($requestedMigrationId -eq [Guid]::Empty) {
                [Guid]::NewGuid()
            }
            else {
                $requestedMigrationId
            }
            $state["migrationId"] = $storedMigrationId.ToString("D")
        }
        elseif (
            $requestedMigrationId -ne [Guid]::Empty -and
            $storedMigrationId -ne $requestedMigrationId
        ) {
            throw "Migration state file '$absoluteStatePath' belongs to migration ID '$($storedMigrationId.ToString("D"))'. Use a different -StateFilePath or pass -ResetState."
        }
        else {
            $state["migrationId"] = $storedMigrationId.ToString("D")
        }
        if ([string]::IsNullOrWhiteSpace([string]$state["migrationStartedUtc"])) {
            $state["migrationStartedUtc"] = [string]$state["createdUtc"]
        }
        $state["status"] = "in_progress"
        $state["lastError"] = $null
        $state["currentResource"] = $null
        $state["resumeCount"] = [int]$state["resumeCount"] + 1
    }
    else {
        $timestamp = Get-MigrationStateUtcTimestamp
        $generatedMigrationId = if ($requestedMigrationId -eq [Guid]::Empty) {
            [Guid]::NewGuid()
        }
        else {
            $requestedMigrationId
        }
        $state = [ordered]@{
            schemaVersion = 1
            migrationType = $MigrationType
            migrationId = $generatedMigrationId.ToString("D")
            migrationStartedUtc = $timestamp
            configurationFingerprint = $fingerprint
            configuration = $Configuration
            status = "in_progress"
            createdUtc = $timestamp
            updatedUtc = $timestamp
            completedUtc = $null
            resumeCount = 0
            currentResource = $null
            lastError = $null
            resources = [ordered]@{}
            summary = [ordered]@{}
        }
    }

    $context = [pscustomobject]@{
        Path = $absoluteStatePath
        Data = $state
    }
    Save-MigrationState -Context $context
    return $context
}

function Get-MigrationResourceCheckpoint {
    param(
        [object]$Context,
        [string]$ResourceName
    )

    $resources = $Context.Data["resources"]
    if ($resources.Contains($ResourceName)) {
        return $resources[$ResourceName]
    }
    return $null
}

function Test-MigrationResourceCompleted {
    param(
        [object]$Context,
        [string]$ResourceName
    )

    $checkpoint = Get-MigrationResourceCheckpoint `
        -Context $Context `
        -ResourceName $ResourceName
    return (
        $null -ne $checkpoint -and
        [string]::Equals(
            [string]$checkpoint["status"],
            "completed",
            [System.StringComparison]::Ordinal
        )
    )
}

function Start-MigrationResourceCheckpoint {
    param(
        [object]$Context,
        [string]$ResourceName
    )

    $existingCheckpoint = Get-MigrationResourceCheckpoint `
        -Context $Context `
        -ResourceName $ResourceName
    $attempt = if ($null -eq $existingCheckpoint) {
        1
    }
    else {
        [int]$existingCheckpoint["attempt"] + 1
    }
    $progress = if (
        $null -ne $existingCheckpoint -and
        $null -ne $existingCheckpoint["progress"]
    ) {
        $existingCheckpoint["progress"]
    }
    else {
        [ordered]@{}
    }
    $timestamp = Get-MigrationStateUtcTimestamp
    $Context.Data["resources"][$ResourceName] = [ordered]@{
        status = "in_progress"
        attempt = $attempt
        startedUtc = $timestamp
        updatedUtc = $timestamp
        completedUtc = $null
        lastError = $null
        progress = $progress
        result = [ordered]@{}
    }
    $Context.Data["currentResource"] = $ResourceName
    Save-MigrationState -Context $Context
}

function Update-MigrationResourceCheckpoint {
    param(
        [object]$Context,
        [string]$ResourceName,
        [System.Collections.IDictionary]$Progress
    )

    $checkpoint = Get-MigrationResourceCheckpoint `
        -Context $Context `
        -ResourceName $ResourceName
    if ($null -eq $checkpoint) {
        throw "Migration resource '$ResourceName' was updated before it was started."
    }
    if ($checkpoint["status"] -eq "completed") {
        throw "Migration resource '$ResourceName' cannot be updated after completion."
    }

    $checkpoint["progress"] = ConvertTo-MigrationStateResult -Result $Progress
    $checkpoint["updatedUtc"] = Get-MigrationStateUtcTimestamp
    Save-MigrationState -Context $Context
}

function Complete-MigrationResourceCheckpoint {
    param(
        [object]$Context,
        [string]$ResourceName,
        [AllowNull()]
        [object]$Result = $null
    )

    $checkpoint = Get-MigrationResourceCheckpoint `
        -Context $Context `
        -ResourceName $ResourceName
    if ($null -eq $checkpoint) {
        throw "Migration resource '$ResourceName' was completed before it was started."
    }

    $timestamp = Get-MigrationStateUtcTimestamp
    $checkpoint["status"] = "completed"
    $checkpoint["updatedUtc"] = $timestamp
    $checkpoint["completedUtc"] = $timestamp
    $checkpoint["lastError"] = $null
    $checkpoint["result"] = ConvertTo-MigrationStateResult -Result $Result
    $Context.Data["currentResource"] = $null
    Save-MigrationState -Context $Context
}

function Set-MigrationStateFailure {
    param(
        [object]$Context,
        [AllowNull()]
        [string]$ResourceName,
        [string]$ErrorMessage
    )

    $timestamp = Get-MigrationStateUtcTimestamp
    if (-not [string]::IsNullOrWhiteSpace($ResourceName)) {
        $checkpoint = Get-MigrationResourceCheckpoint `
            -Context $Context `
            -ResourceName $ResourceName
        if ($null -ne $checkpoint -and $checkpoint["status"] -ne "completed") {
            $checkpoint["status"] = "failed"
            $checkpoint["updatedUtc"] = $timestamp
            $checkpoint["lastError"] = $ErrorMessage
        }
    }
    $Context.Data["status"] = "failed"
    $Context.Data["currentResource"] = $ResourceName
    $Context.Data["lastError"] = $ErrorMessage
    Save-MigrationState -Context $Context
}

function Complete-MigrationState {
    param(
        [object]$Context,
        [AllowNull()]
        [object]$Summary = $null
    )

    $timestamp = Get-MigrationStateUtcTimestamp
    $Context.Data["status"] = "completed"
    $Context.Data["completedUtc"] = $timestamp
    $Context.Data["currentResource"] = $null
    $Context.Data["lastError"] = $null
    $Context.Data["summary"] = ConvertTo-MigrationStateResult -Result $Summary
    Save-MigrationState -Context $Context
}