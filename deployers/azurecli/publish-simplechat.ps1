#requires -Version 7.2
<#
.SYNOPSIS
    Select existing Azure resources, build in ACR, and publish SimpleChat.
.DESCRIPTION
    Uses az acr build with the local repository root as context. Docker does not
    run locally. Omitted targets are selected from numbered menus; explicit
    parameters and -NonInteractive support automation. Requires an existing
    Linux single-container App Service already configured to pull from the ACR.
    Preserves cloud, default subscription, app settings, and pull credentials.
.EXAMPLE
    ./publish-simplechat.ps1
.EXAMPLE
    ./publish-simplechat.ps1 -SubscriptionId <id> -AcrName <acr> -WebAppName <app> -ImageRepository simplechat -NonInteractive -Yes -AllowDirty
.EXAMPLE
    ./publish-simplechat.ps1 -SubscriptionId <id> -AcrName <acr> -WebAppName <app> -WhatIf
.NOTES
    Deployer version: 1.0.35. Application version at introduction: 0.261.042.
    Sign in with az login in the desired Azure cloud before running this script.
    No provisioning, registry credential changes, or automatic rollback occurs.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$SubscriptionId,
    [string]$AcrName,
    [string]$WebAppName,
    [string]$ResourceGroupName,
    [string]$ImageRepository,
    [string]$ImageTag,
    [string]$Slot,
    [switch]$NonInteractive,
    [switch]$Yes,
    [switch]$AllowDirty,
    [switch]$BuildOnly,
    [switch]$SkipBuild,
    [ValidateNotNullOrEmpty()]
    [string]$ImageName,
    [switch]$UseWebhook
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path

function Invoke-PublishAz {
    param([string[]]$Arguments, [switch]$NoOutput)
    $cliArguments = $Arguments + @('--only-show-errors')
    if ($Arguments[0] -ne 'account') {
        $cliArguments += @('--subscription', $SubscriptionId)
    }
    if ($NoOutput) {
        & az @cliArguments --output none | Out-Host
    } else {
        $output = & az @cliArguments --output json
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI failed (exit $LASTEXITCODE): az $($Arguments -join ' '). No later deployment steps were run."
    }
    if (-not $NoOutput -and $output) {
        return ($output -join [Environment]::NewLine) | ConvertFrom-Json -Depth 50
    }
}

function Select-PublishTarget {
    param([object[]]$Items, [string]$ParameterName, [string]$Requested, [string]$Key, [scriptblock]$Label)
    if ($Requested) {
        $matchingTargets = @($Items | Where-Object { $_.$Key -eq $Requested })
        if ($matchingTargets.Count -ne 1) {
            throw "-$ParameterName '$Requested' did not match exactly one accessible resource in the selected scope."
        }
        return $matchingTargets[0]
    }
    if ($NonInteractive) { throw "-$ParameterName is required with -NonInteractive." }
    if ($Items.Count -eq 0) { throw "No accessible choices for -$ParameterName. Check your Azure cloud, login, and permissions." }
    Write-Host "`nSelect $ParameterName (q to cancel):" -ForegroundColor Cyan
    for ($index = 0; $index -lt $Items.Count; $index++) {
        Write-Host ('  {0}. {1}' -f ($index + 1), (& $Label $Items[$index]))
    }
    while ($true) {
        $answer = Read-Host 'Number'
        if ($answer -eq 'q') { throw 'Publish cancelled.' }
        $selection = 0
        if ([int]::TryParse($answer, [ref]$selection) -and $selection -ge 1 -and $selection -le $Items.Count) {
            return $Items[$selection - 1]
        }
        Write-Host "Enter a number from 1 to $($Items.Count), or q."
    }
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw 'Azure CLI is required. Install it and run az login first.' }
if ($ImageName) {
    if ($ImageRepository -or $ImageTag) { throw '-ImageName cannot be combined with -ImageRepository or -ImageTag.' }
    $imageParts = $ImageName -split ':', 2
    if ($imageParts.Count -ne 2 -or -not $imageParts[0] -or -not $imageParts[1]) {
        throw '-ImageName must contain a repository and tag, for example simplechat:latest.'
    }
    $ImageRepository = $imageParts[0]
    $ImageTag = $imageParts[1]
}
if ($BuildOnly -and $SkipBuild) { throw '-BuildOnly and -SkipBuild cannot be combined.' }
if ($SkipBuild -and -not $ImageTag) { throw '-SkipBuild requires an explicit -ImageTag for the existing image.' }
if ($UseWebhook -and ($BuildOnly -or $SkipBuild)) { throw '-UseWebhook requires a new build and cannot be combined with -BuildOnly or -SkipBuild.' }
if ($UseWebhook -and -not $ImageTag) { throw '-UseWebhook requires an explicit image tag, such as -ImageName simplechat:latest.' }
if ($NonInteractive) {
    foreach ($required in @('SubscriptionId', 'AcrName')) {
        if (-not (Get-Variable $required -ValueOnly)) { throw "-$required is required with -NonInteractive." }
    }
    if (-not $BuildOnly -and -not $WebAppName) { throw '-WebAppName is required with -NonInteractive.' }
    if (-not $Yes -and -not $WhatIfPreference) { throw '-NonInteractive requires -Yes to authorize build/deployment, or -WhatIf for a read-only preview.' }
}

$subscriptions = @(Invoke-PublishAz -Arguments @(
    'account', 'list', '--query', "[?state=='Enabled'].{id:id,name:name,tenantId:tenantId}"
) | Sort-Object name, id)
$subscription = Select-PublishTarget -Items $subscriptions -ParameterName SubscriptionId -Requested $SubscriptionId -Key id -Label {
    param($item) "$($item.name) | $($item.id) | tenant $($item.tenantId)"
}
$SubscriptionId = $subscription.id

$registries = @(Invoke-PublishAz -Arguments @('acr', 'list', '--query', '[].{name:name,resourceGroup:resourceGroup,loginServer:loginServer}') | Sort-Object name)
$registry = Select-PublishTarget -Items $registries -ParameterName AcrName -Requested $AcrName -Key name -Label {
    param($item) "$($item.name) | $($item.resourceGroup)"
}
$AcrName = $registry.name
if (-not $registry.loginServer) { throw 'Selected registry has no login server.' }

$previousImage = $null
$appArguments = @()
$app = $null
if (-not $BuildOnly) {
    $listArguments = @('webapp', 'list', '--query', '[].{name:name,resourceGroup:resourceGroup,kind:kind}')
    if ($ResourceGroupName) { $listArguments += @('--resource-group', $ResourceGroupName) }
    $apps = @(Invoke-PublishAz -Arguments $listArguments | Where-Object { $_.kind -match 'linux' } | Sort-Object name)
    $selectedApp = Select-PublishTarget -Items $apps -ParameterName WebAppName -Requested $WebAppName -Key name -Label {
        param($item) "$($item.name) | $($item.resourceGroup)"
    }
    $WebAppName = $selectedApp.name
    $ResourceGroupName = $selectedApp.resourceGroup
    $appArguments = @('--name', $WebAppName, '--resource-group', $ResourceGroupName)
    if ($Slot) { $appArguments += @('--slot', $Slot) }
    $app = Invoke-PublishAz -Arguments (@('webapp', 'show') + $appArguments + @('--query', '{name:name,defaultHostName:defaultHostName,reserved:reserved}'))
    $configuration = Invoke-PublishAz -Arguments (@('webapp', 'config', 'show') + $appArguments + @('--query', '{linuxFxVersion:linuxFxVersion}'))
    if (-not $app.reserved -or $configuration.linuxFxVersion -notlike 'DOCKER|*') {
        throw 'Target must be an existing Linux single-container app (DOCKER| image). Sidecar, Compose, and code-based apps are not changed by this publisher.'
    }
    $previousImage = $configuration.linuxFxVersion.Substring(7)
    if (-not $previousImage.StartsWith("$($registry.loginServer)/", [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The selected app currently uses a different registry. Configure and verify its pull access separately, or use -BuildOnly. This script does not change registry authentication.'
    }
    if (-not $ImageRepository) {
        $ImageRepository = ($previousImage.Substring($registry.loginServer.Length + 1) -split '[:@]', 2)[0]
    }
}

if (-not $ImageRepository) {
    if ($NonInteractive) { throw '-ImageRepository is required for noninteractive build-only mode.' }
    $ImageRepository = Read-Host 'Image repository [simplechat]'
    if (-not $ImageRepository) { $ImageRepository = 'simplechat' }
}
if ($ImageRepository -cnotmatch '^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$') {
    throw '-ImageRepository must be a lowercase repository path, without a registry hostname, tag, or digest.'
}
if ($UseWebhook) {
    $webhookImage = "$($registry.loginServer)/${ImageRepository}:${ImageTag}"
    if ($previousImage -cne $webhookImage) {
        throw "-UseWebhook requires the app's existing image to be '$webhookImage'; found '$previousImage'. No build was run."
    }
    $webhooks = @(Invoke-PublishAz -Arguments @(
        'acr', 'webhook', 'list', '--registry', $AcrName, '--resource-group', $registry.resourceGroup,
        '--query', '[].{name:name,scope:scope,actions:actions,status:status}'
    ))
    $matchingWebhooks = @($webhooks | Where-Object {
        $scopeMatches = -not $_.scope -or $_.scope -ceq "${ImageRepository}:${ImageTag}" -or $_.scope -ceq "${ImageRepository}:*"
        $scopeMatches -and $_.status -eq 'enabled' -and $_.actions -contains 'push'
    })
    if ($matchingWebhooks.Count -eq 0) {
        throw "-UseWebhook requires an enabled ACR push webhook scoped to '${ImageRepository}:${ImageTag}', '${ImageRepository}:*', or all images. No build was run."
    }
}

$revision = 'unknown'
$dirty = $false
if (-not $SkipBuild) {
    foreach ($requiredFile in @('application/single_app/Dockerfile', '.dockerignore')) {
        if (-not (Test-Path (Join-Path $repoRoot $requiredFile) -PathType Leaf)) { throw "Build context is missing $requiredFile." }
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is required to identify the source revision and uncommitted changes.' }
    $revision = & git -C $repoRoot rev-parse --short=12 HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Unable to identify the source revision.' }
    $changes = & git -C $repoRoot status --porcelain --untracked-files=normal
    if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect uncommitted source changes.' }
    $dirty = -not [string]::IsNullOrWhiteSpace(($changes -join "`n"))
    if ($dirty -and -not $AllowDirty -and -not $WhatIfPreference) {
        if ($NonInteractive) { throw 'Uncommitted changes found. Review the local build context and pass -AllowDirty to include them.' }
        if ((Read-Host 'Include uncommitted/local files in the ACR source upload? [y/N]') -ne 'y') { throw 'Publish cancelled: local source changes were not approved.' }
    }
}
if (-not $ImageTag) {
    $sourceSuffix = if ($dirty) { '-dirty' } else { '' }
    $ImageTag = 'build-{0}-{1}{2}' -f ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')), $revision, $sourceSuffix
}
if ($ImageTag -cnotmatch '^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$') {
    throw 'Use a valid -ImageTag with up to 128 letters, digits, underscores, dots, or hyphens; it cannot start with a dot or hyphen.'
}
$taggedImage = "$($registry.loginServer)/${ImageRepository}:${ImageTag}"

Write-Host "`nSubscription: $($subscription.name) ($SubscriptionId)"
Write-Host "Registry:     $AcrName ($($registry.resourceGroup))"
Write-Host "Image:        $taggedImage"
if (-not $SkipBuild -and $ImageTag -eq 'latest') {
    if ($UseWebhook) {
        Write-Warning 'This build replaces latest; App Service remains configured to that mutable tag and depends on webhook delivery.'
    } else {
        Write-Warning 'This build will replace the latest tag. App Service will be pinned to this run output digest.'
    }
}
if (-not $SkipBuild) {
    Write-Host "Source:       $repoRoot"
    Write-Host "Revision:     $revision (uncommitted changes: $dirty)"
    Write-Host 'Build:        remote ACR Tasks; local source uploaded using the root .dockerignore'
}
if (-not $BuildOnly) {
    $slotLabel = if ($Slot) { $Slot } else { 'production' }
    Write-Host "Target:       $WebAppName / $ResourceGroupName / $slotLabel"
    Write-Host "Previous:     $previousImage"
}
if ($UseWebhook) {
    Write-Host "Webhook:      $($matchingWebhooks.name -join ', ')"
    Write-Host 'App Service already uses the pushed tag; the webhook will request its refresh.'
}
if (-not $Yes -and -not $WhatIfPreference) {
    if ((Read-Host 'Proceed with this build/deployment? [y/N]') -ne 'y') { throw 'Publish cancelled.' }
}
$publishAction = if ($UseWebhook) { 'Build in ACR and notify App Service through its ACR webhook' } else { 'Build in ACR and/or update the selected App Service image' }
if (-not $PSCmdlet.ShouldProcess($taggedImage, $publishAction)) { return }

if (-not $SkipBuild) {
    Write-Host 'Building in ACR; waiting for completion with log streaming disabled.'
    $buildResult = Invoke-PublishAz -Arguments @(
        'acr', 'build', '--registry', $AcrName, '--resource-group', $registry.resourceGroup,
        '--file', (Join-Path $repoRoot 'application/single_app/Dockerfile'),
        '--image', "${ImageRepository}:${ImageTag}", '--platform', 'linux/amd64', '--no-logs',
        '--query', '{runId:runId,status:status,outputImages:outputImages}', $repoRoot
    )
    if ($buildResult) { Write-Host "ACR run: $($buildResult.runId) ($($buildResult.status))" }
    if (-not $buildResult -or $buildResult.status -ne 'Succeeded') {
        throw 'ACR build did not succeed. App Service was not changed. Check the ACR run status in the portal.'
    }
    $builtImages = @($buildResult.outputImages | Where-Object {
        $_.registry -eq $registry.loginServer -and $_.repository -ceq $ImageRepository -and $_.tag -ceq $ImageTag
    })
    if ($builtImages.Count -ne 1) { throw 'Unable to verify the requested output image from this ACR run. App Service was not changed.' }
    $manifest = $builtImages[0]
} else {
    $manifest = Invoke-PublishAz -Arguments @(
        'acr', 'repository', 'show', '--name', $AcrName, '--image', "${ImageRepository}:${ImageTag}", '--query', '{digest:digest}'
    )
}
if ($manifest.digest -cnotmatch '^sha256:[a-f0-9]{64}$') { throw 'Unable to verify the image digest. App Service was not changed.' }
$pinnedImage = "$($registry.loginServer)/${ImageRepository}@$($manifest.digest)"
if ($BuildOnly) {
    Write-Host "`nBuild complete: $pinnedImage" -ForegroundColor Green
    return
}
if ($UseWebhook) {
    Write-Host "`nBuild complete: $pinnedImage" -ForegroundColor Green
    Write-Host "App Service remains configured to: $webhookImage"
    Write-Host 'ACR webhook delivery is asynchronous. Check webhook events and verify the app health/version before accepting the deployment.'
    Write-Host "URL: https://$($app.defaultHostName)"
    return
}

Write-Host "`nRollback image: $previousImage" -ForegroundColor Yellow
Write-Host 'To restore it, use az webapp config set with the same subscription/name/resource-group/slot and --linux-fx-version "DOCKER|<previous-image>".'
Invoke-PublishAz -NoOutput -Arguments (@('webapp', 'config', 'set') + $appArguments + @('--linux-fx-version', "DOCKER|$pinnedImage"))
$updated = Invoke-PublishAz -Arguments (@('webapp', 'config', 'show') + $appArguments + @('--query', '{linuxFxVersion:linuxFxVersion}'))
if ($updated.linuxFxVersion -ne "DOCKER|$pinnedImage") {
    throw "App image verification failed. Check the app configuration before retrying. Previous image: $previousImage"
}
Write-Host "`nApp Service image configuration verified: $pinnedImage" -ForegroundColor Green
Write-Host "URL: https://$($app.defaultHostName)"
Write-Host 'App Service will pull/start the image. Startup health and the running application version have NOT been verified; check them before accepting the deployment.'