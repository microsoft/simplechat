# Migration-Provenance.ps1

function Get-MigrationProvenancePropertyValue {
    param(
        [AllowNull()]
        [object]$Source,
        [string]$Name
    )

    if ($null -eq $Source) {
        return $null
    }

    if ($Source -is [System.Collections.IDictionary]) {
        foreach ($key in $Source.Keys) {
            if ([string]::Equals([string]$key, $Name, [System.StringComparison]::OrdinalIgnoreCase)) {
                return $Source[$key]
            }
        }
        return $null
    }

    foreach ($property in $Source.PSObject.Properties) {
        if ([string]::Equals($property.Name, $Name, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $property.Value
        }
    }
    return $null
}

function New-MigrationProvenanceContext {
    param(
        [string]$MigrationId = "",
        [string]$MigratedAtUtc = "",
        [ValidateRange(0, 8760)]
        [int]$SkipMigratedWithinHours = 24
    )

    $parsedMigrationId = [Guid]::Empty
    if ([string]::IsNullOrWhiteSpace($MigrationId)) {
        $parsedMigrationId = [Guid]::NewGuid()
    }
    elseif (-not [Guid]::TryParse($MigrationId, [ref]$parsedMigrationId)) {
        throw "MigrationId must be a valid GUID."
    }

    [DateTimeOffset]$parsedMigratedAtUtc = [DateTimeOffset]::UtcNow
    if (-not [string]::IsNullOrWhiteSpace($MigratedAtUtc)) {
        if (-not [DateTimeOffset]::TryParse($MigratedAtUtc, [ref]$parsedMigratedAtUtc)) {
            throw "MigratedAtUtc must be a valid ISO 8601 timestamp."
        }
        $parsedMigratedAtUtc = $parsedMigratedAtUtc.ToUniversalTime()
    }

    return [pscustomobject]@{
        MigrationId = $parsedMigrationId.ToString("D")
        MigratedAtUtc = $parsedMigratedAtUtc.ToString(
            "o",
            [System.Globalization.CultureInfo]::InvariantCulture
        )
        SkipMigratedWithinHours = $SkipMigratedWithinHours
    }
}

function New-MigrationProvenanceRecord {
    param(
        [object]$Context
    )

    return [ordered]@{
        migrationId = [string]$Context.MigrationId
        migratedAtUtc = [string]$Context.MigratedAtUtc
        status = "succeeded"
    }
}

function Test-MigrationProvenanceSkip {
    param(
        [AllowNull()]
        [object]$Provenance,
        [object]$Context
    )

    if ($null -eq $Provenance) {
        return $false
    }

    $status = [string](Get-MigrationProvenancePropertyValue `
        -Source $Provenance `
        -Name "status")
    if (-not [string]::Equals($status, "succeeded", [System.StringComparison]::OrdinalIgnoreCase)) {
        return $false
    }

    $migrationId = [string](Get-MigrationProvenancePropertyValue `
        -Source $Provenance `
        -Name "migrationId")
    if ([string]::Equals($migrationId, [string]$Context.MigrationId, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }

    if ([int]$Context.SkipMigratedWithinHours -le 0) {
        return $false
    }

    $migratedAtUtc = [string](Get-MigrationProvenancePropertyValue `
        -Source $Provenance `
        -Name "migratedAtUtc")
    [DateTimeOffset]$parsedMigratedAtUtc = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse($migratedAtUtc, [ref]$parsedMigratedAtUtc)) {
        return $false
    }

    $cutoffUtc = [DateTimeOffset]::UtcNow.AddHours(-[int]$Context.SkipMigratedWithinHours)
    return $parsedMigratedAtUtc.ToUniversalTime() -ge $cutoffUtc
}

function Add-CosmosMigrationProvenance {
    param(
        [System.Collections.IDictionary]$Document,
        [object]$Context
    )

    $Document["simplechatMigration"] = New-MigrationProvenanceRecord -Context $Context
}

function Get-CosmosMigrationProvenance {
    param(
        [AllowNull()]
        [object]$Document
    )

    return Get-MigrationProvenancePropertyValue `
        -Source $Document `
        -Name "simplechatMigration"
}

function Get-AISearchMigrationProvenanceFieldDefinitions {
    return @(
        [ordered]@{
            name = "simplechatMigrationId"
            type = "Edm.String"
            searchable = $false
            filterable = $true
            sortable = $true
            facetable = $false
            retrievable = $true
        },
        [ordered]@{
            name = "simplechatMigratedAtUtc"
            type = "Edm.DateTimeOffset"
            filterable = $true
            sortable = $true
            facetable = $false
            retrievable = $true
        },
        [ordered]@{
            name = "simplechatMigrationStatus"
            type = "Edm.String"
            searchable = $false
            filterable = $true
            sortable = $true
            facetable = $false
            retrievable = $true
        }
    )
}

function Add-AISearchMigrationProvenance {
    param(
        [object]$Document,
        [object]$Context
    )

    $provenance = New-MigrationProvenanceRecord -Context $Context
    $fieldValues = [ordered]@{
        simplechatMigrationId = $provenance["migrationId"]
        simplechatMigratedAtUtc = $provenance["migratedAtUtc"]
        simplechatMigrationStatus = $provenance["status"]
    }

    foreach ($fieldName in $fieldValues.Keys) {
        if ($Document -is [System.Collections.IDictionary]) {
            $Document[$fieldName] = $fieldValues[$fieldName]
        }
        else {
            $Document | Add-Member `
                -MemberType NoteProperty `
                -Name $fieldName `
                -Value $fieldValues[$fieldName] `
                -Force
        }
    }
}

function Get-AISearchMigrationProvenance {
    param(
        [AllowNull()]
        [object]$Document
    )

    return [ordered]@{
        migrationId = Get-MigrationProvenancePropertyValue `
            -Source $Document `
            -Name "simplechatMigrationId"
        migratedAtUtc = Get-MigrationProvenancePropertyValue `
            -Source $Document `
            -Name "simplechatMigratedAtUtc"
        status = Get-MigrationProvenancePropertyValue `
            -Source $Document `
            -Name "simplechatMigrationStatus"
    }
}

function Merge-StorageMigrationProvenance {
    param(
        [AllowNull()]
        [object]$Metadata,
        [object]$Context
    )

    $mergedMetadata = [ordered]@{}
    if ($null -ne $Metadata) {
        if ($Metadata -is [System.Collections.IDictionary]) {
            foreach ($key in $Metadata.Keys) {
                $mergedMetadata[[string]$key] = $Metadata[$key]
            }
        }
        else {
            foreach ($property in $Metadata.PSObject.Properties) {
                $mergedMetadata[$property.Name] = $property.Value
            }
        }
    }

    $provenance = New-MigrationProvenanceRecord -Context $Context
    $mergedMetadata["simplechatMigrationId"] = $provenance["migrationId"]
    $mergedMetadata["simplechatMigratedAtUtc"] = $provenance["migratedAtUtc"]
    $mergedMetadata["simplechatMigrationStatus"] = $provenance["status"]
    return $mergedMetadata
}

function Get-StorageMigrationProvenance {
    param(
        [AllowNull()]
        [object]$Metadata
    )

    return [ordered]@{
        migrationId = Get-MigrationProvenancePropertyValue `
            -Source $Metadata `
            -Name "simplechatMigrationId"
        migratedAtUtc = Get-MigrationProvenancePropertyValue `
            -Source $Metadata `
            -Name "simplechatMigratedAtUtc"
        status = Get-MigrationProvenancePropertyValue `
            -Source $Metadata `
            -Name "simplechatMigrationStatus"
    }
}