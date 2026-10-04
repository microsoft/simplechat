# test_azurecli_publish_script.ps1
<#
Functional tests for interactive ACR publishing, using an offline Azure CLI fake.
Version: 0.261.042
Implemented in: deployer 1.0.32
Automatic-variable regression fixed in: deployer 1.0.33
Task image selection and log-free build completion implemented in: deployer 1.0.34
Webhook-based App Service refresh implemented in: deployer 1.0.35
No application bootstrap, credentials, network, or Azure processes are used.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$publisher = Join-Path $PSScriptRoot '../deployers/azurecli/publish-simplechat.ps1'
if (-not (Test-Path $publisher)) {
    throw 'Missing interactive publisher.'
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$publisherTokens = $null
$publisherErrors = $null
$publisherAst = [System.Management.Automation.Language.Parser]::ParseFile($publisher, [ref]$publisherTokens, [ref]$publisherErrors)
Assert-True ($publisherErrors.Count -eq 0) 'Publisher must parse cleanly.'
$automaticVariableAssignments = @($publisherAst.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $node.Left -is [System.Management.Automation.Language.VariableExpressionAst] -and
        $node.Left.VariablePath.UserPath -imatch '(^|:)matches$'
}, $true))
Assert-True ($automaticVariableAssignments.Count -eq 0) 'Publisher must not assign to the automatic $Matches variable.'
Write-Host 'PASS: no assignments to the automatic $Matches variable'

function Invoke-Scenario {
    param(
        [hashtable]$Options,
        [string]$Failure = '',
        [string[]]$Answers = @(),
        [bool]$Dirty = $false,
        [string]$ContainerMode = 'classic',
        [string]$CurrentRegistry = 'registry.example',
        [string]$CurrentImage = '',
        [string]$ManifestDigest = ('sha256:' + ('a' * 64)),
        [string]$BuildStatus = 'Succeeded',
        [string]$BuildDigest = ('sha256:' + ('a' * 64)),
        [string]$WebhookScope = 'simplechat:latest',
        [switch]$MissingBuildResult,
        [switch]$MissingBuildImage,
        [switch]$NoMatchingWebhooks,
        [switch]$IgnoreUpdate,
        [switch]$EmptyRegistries
    )
    $calls = [System.Collections.Generic.List[string[]]]::new()
    $answerQueue = [System.Collections.Generic.Queue[string]]::new()
    foreach ($answer in $Answers) { $answerQueue.Enqueue($answer) }
    $initialImage = if ($CurrentImage) { $CurrentImage } else { "$CurrentRegistry/simplechat:previous" }
    $state = @{ Image = $initialImage; Error = ''; Dirty = $Dirty }

    function Read-Host {
        param([string]$Prompt)
        if ($answerQueue.Count -eq 0) { throw "Unexpected prompt: $Prompt" }
        return $answerQueue.Dequeue()
    }
    function git {
        $global:LASTEXITCODE = 0
        if ($args -contains 'status') {
            if ($state.Dirty) { ' M application/single_app/app.py' }
        } else { 'abcdef1234567890' }
    }
    function az {
        $arguments = [string[]]$args
        $calls.Add($arguments)
        $command = $arguments -join ' '
        $global:LASTEXITCODE = 0
        if ($Failure -and $command.StartsWith($Failure)) {
            $global:LASTEXITCODE = 1
            return
        }
        switch -Regex ($command) {
            '^account list' { '[{"id":"sub-1","name":"Test subscription","tenantId":"tenant-1","state":"Enabled"}]'; break }
            '^acr list' {
                if ($EmptyRegistries) { '[]' }
                else { '[{"name":"testacr","resourceGroup":"registry-rg","loginServer":"registry.example"}]' }
                break
            }
            '^acr webhook list' {
                if ($NoMatchingWebhooks) { '[]' }
                else { "[{`"name`":`"app-hook`",`"scope`":`"$WebhookScope`",`"actions`":[`"push`"],`"status`":`"enabled`"}]" }
                break
            }
            '^webapp list' { '[{"name":"testapp","resourceGroup":"app-rg","kind":"app,linux,container"}]'; break }
            '^webapp show' { '{"name":"testapp","resourceGroup":"app-rg","defaultHostName":"app.example","reserved":true}'; break }
            '^webapp config show' {
                $linuxFxVersion = switch ($ContainerMode) {
                    'classic' { "DOCKER|$($state.Image)" }
                    'sidecar' { 'sitecontainers' }
                    default { 'PYTHON|3.12' }
                }
                @{ linuxFxVersion = $linuxFxVersion } | ConvertTo-Json -Compress
                break
            }
            '^webapp config set' {
                if (-not $IgnoreUpdate) {
                    $state.Image = $arguments[$arguments.IndexOf('--linux-fx-version') + 1].Substring(7)
                }
                break
            }
            '^acr build' {
                if ($MissingBuildResult) { 'null'; break }
                $imageParts = $arguments[$arguments.IndexOf('--image') + 1] -split ':', 2
                $outputImages = @()
                if (-not $MissingBuildImage) {
                    $outputImages += @{
                        registry = 'registry.example'; repository = $imageParts[0]
                        tag = $imageParts[1]; digest = $BuildDigest
                    }
                }
                @{ runId = 'run-123'; status = $BuildStatus; outputImages = $outputImages } | ConvertTo-Json -Depth 5 -Compress
                break
            }
            '^acr repository show ' { @{ digest = $ManifestDigest } | ConvertTo-Json -Compress; break }
            default { throw "Unexpected Azure CLI call: $command" }
        }
    }
    try { & $publisher @Options | Out-Null }
    catch { $state.Error = $_.Exception.Message }
    return @{ Calls = $calls; Error = $state.Error; Image = $state.Image; AnswersLeft = $answerQueue.Count }
}

$explicit = @{
    SubscriptionId = 'sub-1'; AcrName = 'testacr'; WebAppName = 'testapp'
    ImageRepository = 'simplechat'; ImageTag = 'test-unique'
    NonInteractive = $true; Yes = $true
}

$result = Invoke-Scenario -Options $explicit
Assert-True (-not $result.Error) "Explicit publish failed: $($result.Error)"
Assert-True ($result.Image -eq 'registry.example/simplechat@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa') 'Deployment must pin the built digest.'
foreach ($call in $result.Calls) {
    if ($call[0] -ne 'account') {
        Assert-True ($call -contains '--subscription') 'Every resource command must scope its subscription.'
        Assert-True ($call[$call.IndexOf('--subscription') + 1] -eq 'sub-1') 'Wrong subscription.'
    }
}
$builds = @($result.Calls | Where-Object { $_[0] -eq 'acr' -and $_[1] -eq 'build' })
Assert-True ($builds.Count -eq 1) 'Expected exactly one remote build.'
Assert-True (($builds[0] -contains '--file') -and ($builds[0] -contains (Resolve-Path (Join-Path $PSScriptRoot '..')).Path)) 'Build must use the repository root.'
Assert-True ($builds[0] -contains '--no-logs') 'Build must suppress Unicode log streaming with --no-logs.'
Assert-True (-not ($builds[0] -contains '--no-wait')) 'Build must wait for the CLI status poller to finish.'
Assert-True ($builds[0][$builds[0].IndexOf('--output') + 1] -eq 'json') 'Build must return structured completion metadata.'
$joinedCalls = ($result.Calls | ForEach-Object { $_ -join ' ' }) -join "`n"
Assert-True ($joinedCalls -notmatch 'credential|account set|cloud set|acr update|appsettings|role assignment') 'Publisher must not change authentication, settings, roles, or default context.'
Write-Host 'PASS: explicit publish, remote build, digest pinning, subscription scoping'

$result = Invoke-Scenario -Options $explicit -Failure 'acr build'
Assert-True ($result.Error -like '*Azure CLI*') 'Build failure must be reported.'
Assert-True ($result.Image -eq 'registry.example/simplechat:previous') 'Failed build must not update the app.'
Write-Host 'PASS: build failure stops deployment'

foreach ($status in @('Failed', 'Canceled', 'Error', 'Timeout', 'Queued', 'Running', '')) {
    $result = Invoke-Scenario -Options $explicit -BuildStatus $status
    Assert-True ($result.Error -like '*did not succeed*') "Non-success build result accepted: $status"
    Assert-True ($result.Image -eq 'registry.example/simplechat:previous') 'Unsuccessful runs must not update the app.'
    Assert-True (-not (@($result.Calls | Where-Object { $_ -contains 'repository' -or $_ -contains 'set' }).Count)) 'Unsuccessful runs must not resolve an old tag or change the app.'
}
$result = Invoke-Scenario -Options $explicit -MissingBuildResult
Assert-True ($result.Error -like '*did not succeed*') 'Missing build metadata must fail closed.'
$result = Invoke-Scenario -Options $explicit -MissingBuildImage
Assert-True ($result.Error -like '*output image*') 'A successful run without the requested output image must fail closed.'
Assert-True ($result.Image -eq 'registry.example/simplechat:previous') 'Missing output image must preserve the app.'
Write-Host 'PASS: build completion status and output image required'

$latest = $explicit.Clone(); $latest.ImageTag = 'latest'
$result = Invoke-Scenario -Options $latest -ManifestDigest ('sha256:' + ('b' * 64))
Assert-True (-not $result.Error) "Latest publish failed: $($result.Error)"
Assert-True ($result.Image -eq 'registry.example/simplechat@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa') 'Latest must deploy this run digest, not a concurrently overwritten tag.'
Assert-True (-not (@($result.Calls | Where-Object { $_ -contains 'repository' }).Count)) 'New builds must use the run output, not resolve a mutable tag.'
Write-Host 'PASS: latest builds pin their own output digest'

$webhookOptions = @{
    SubscriptionId = 'sub-1'; AcrName = 'testacr'; WebAppName = 'testapp'
    ImageName = 'simplechat:latest'; UseWebhook = $true; Yes = $true
}
$result = Invoke-Scenario -Options $webhookOptions -CurrentImage 'registry.example/simplechat:latest'
Assert-True (-not $result.Error) "Webhook publish failed: $($result.Error)"
Assert-True ($result.Image -eq 'registry.example/simplechat:latest') 'Webhook deployment must leave the configured tag in place.'
Assert-True (-not (@($result.Calls | Where-Object { $_[0] -eq 'webapp' -and $_ -contains 'set' }).Count)) 'Webhook deployment must skip az webapp config set.'
Assert-True ((@($result.Calls | Where-Object { $_[0] -eq 'acr' -and $_[1] -eq 'webhook' -and $_[2] -eq 'list' }).Count) -eq 1) 'Webhook deployment must check for an enabled push hook.'
Write-Host 'PASS: matching webhook deployment preserves the configured image tag'

$result = Invoke-Scenario -Options $webhookOptions
Assert-True ($result.Error -like '*existing image*') 'Webhook deployment must reject an app using a different tag.'
Assert-True (-not (@($result.Calls | Where-Object { $_ -contains 'build' -or $_ -contains 'set' }).Count)) 'Image mismatch must fail before build or app update.'
$result = Invoke-Scenario -Options $webhookOptions -CurrentImage 'registry.example/simplechat:latest' -NoMatchingWebhooks
Assert-True ($result.Error -like '*enabled ACR push webhook*') 'Webhook deployment must require a matching enabled push hook.'
Assert-True (-not (@($result.Calls | Where-Object { $_ -contains 'build' -or $_ -contains 'set' }).Count)) 'Missing webhook must fail before build or app update.'
$webhookSkipBuild = $webhookOptions.Clone(); $webhookSkipBuild.SkipBuild = $true
$result = Invoke-Scenario -Options $webhookSkipBuild -CurrentImage 'registry.example/simplechat:latest'
Assert-True ($result.Error -like '*cannot be combined*') 'Webhook deployment must reject SkipBuild.'
Write-Host 'PASS: webhook mode fails closed for mismatched target or missing hook'

$namedImage = $explicit.Clone(); $namedImage.Remove('ImageRepository'); $namedImage.Remove('ImageTag'); $namedImage.ImageName = 'team/simplechat:release-42'
$result = Invoke-Scenario -Options $namedImage
Assert-True (-not $result.Error) "Combined image reference failed: $($result.Error)"
$namedBuild = @($result.Calls | Where-Object { $_[0] -eq 'acr' -and $_[1] -eq 'build' })[0]
Assert-True ($namedBuild[$namedBuild.IndexOf('--image') + 1] -eq 'team/simplechat:release-42') 'ImageName must preserve the requested repository and tag.'
Assert-True ($result.Image -like 'registry.example/team/simplechat@sha256:*') 'Deployment must use the requested repository.'
$namedImage.SkipBuild = $true
$result = Invoke-Scenario -Options $namedImage
Assert-True (-not $result.Error) "Combined reference for existing image failed: $($result.Error)"
Assert-True (-not (@($result.Calls | Where-Object { $_ -contains 'build' }).Count)) 'Existing image reference must skip the build.'
$conflictingImage = $explicit.Clone(); $conflictingImage.ImageName = 'simplechat:latest'
$result = Invoke-Scenario -Options $conflictingImage
Assert-True ($result.Error -like '*cannot be combined*') 'Ambiguous image options must be rejected.'
foreach ($badImage in @('simplechat', ':latest', 'simplechat:', 'simplechat:bad/tag', 'simplechat@sha256:abc', 'simplechat:tag:extra', 'SimpleChat:latest')) {
    $badImageOptions = $namedImage.Clone(); $badImageOptions.Remove('SkipBuild'); $badImageOptions.ImageName = $badImage
    $result = Invoke-Scenario -Options $badImageOptions
    Assert-True ([bool]$result.Error) "Invalid combined image reference accepted: $badImage"
    Assert-True (-not (@($result.Calls | Where-Object { $_ -contains 'build' -or $_ -contains 'set' }).Count)) 'Invalid image input must not mutate Azure.'
}
Write-Host 'PASS: combined image reference and validation'

$dryRun = $explicit.Clone(); $dryRun.WhatIf = $true
$result = Invoke-Scenario -Options $dryRun
Assert-True (-not $result.Error) "Dry run failed: $($result.Error)"
Assert-True (-not (@($result.Calls | Where-Object { $_ -contains 'build' -or $_ -contains 'set' }).Count)) 'WhatIf must not mutate Azure.'
Write-Host 'PASS: WhatIf is read-only'

$missing = $explicit.Clone(); $missing.Remove('SubscriptionId')
$result = Invoke-Scenario -Options $missing
Assert-True ($result.Error -like '*SubscriptionId*') 'Noninteractive mode must reject missing selection without prompting.'
Write-Host 'PASS: noninteractive missing target rejected'

$unconfirmed = $explicit.Clone(); $unconfirmed.Remove('Yes')
$result = Invoke-Scenario -Options $unconfirmed
Assert-True ($result.Error -like '*Yes*') 'Noninteractive mutation requires Yes.'
Write-Host 'PASS: noninteractive mutation requires explicit confirmation'

$result = Invoke-Scenario -Options $explicit -Dirty $true
Assert-True ($result.Error -like '*AllowDirty*') 'Uncommitted sources must require opt-in.'
Assert-True ($result.Image -eq 'registry.example/simplechat:previous') 'Dirty rejection must preserve the app.'
$dirtyAllowed = $explicit.Clone(); $dirtyAllowed.AllowDirty = $true
$result = Invoke-Scenario -Options $dirtyAllowed -Dirty $true
Assert-True (-not $result.Error) "Dirty opt-in failed: $($result.Error)"
Write-Host 'PASS: dirty source opt-in'

$result = Invoke-Scenario -Options @{ ImageRepository = 'simplechat'; ImageTag = 'interactive' } -Answers @('wrong', '1', '1', '1', 'y')
Assert-True (-not $result.Error) "Interactive publish failed: $($result.Error)"
Assert-True ($result.AnswersLeft -eq 0) 'Interactive selections and confirmation were not consumed.'
Write-Host 'PASS: interactive menus and invalid selection retry'

$result = Invoke-Scenario -Options @{ ImageRepository = 'simplechat'; ImageTag = 'cancel' } -Answers @('q')
Assert-True ($result.Error -like '*cancel*') 'Menu cancellation should stop safely.'
Write-Host 'PASS: menu cancellation'

$buildOnly = $explicit.Clone(); $buildOnly.BuildOnly = $true; $buildOnly.Remove('WebAppName')
$result = Invoke-Scenario -Options $buildOnly
Assert-True (-not $result.Error) "Build-only failed: $($result.Error)"
Assert-True (-not (@($result.Calls | Where-Object { $_[0] -eq 'webapp' }).Count)) 'Build-only must not access a web app.'
Write-Host 'PASS: build-only mode'

$rollback = $explicit.Clone(); $rollback.SkipBuild = $true; $rollback.ImageTag = 'previous'
$result = Invoke-Scenario -Options $rollback
Assert-True (-not $result.Error) "Existing-image deploy failed: $($result.Error)"
Assert-True (-not (@($result.Calls | Where-Object { $_ -contains 'build' }).Count)) 'Existing-image deployment must skip the build.'
Write-Host 'PASS: deploy existing image for rollback'

$result = Invoke-Scenario -Options $explicit -ContainerMode 'runtime'
Assert-True ($result.Error -like '*container*') 'Non-container apps must fail preflight.'
Assert-True (-not (@($result.Calls | Where-Object { $_ -contains 'build' }).Count)) 'Unsupported app must fail before build.'
Write-Host 'PASS: unsupported app rejected before build'

$result = Invoke-Scenario -Options $explicit -ContainerMode 'sidecar'
Assert-True ($result.Error -like '*Sidecar*') 'Sidecar apps must fail preflight rather than silently change hosting modes.'
Assert-True (-not (@($result.Calls | Where-Object { $_ -contains 'build' }).Count)) 'Sidecar rejection must precede the build.'
Write-Host 'PASS: sidecar guard'

$result = Invoke-Scenario -Options $explicit -CurrentRegistry 'other.example'
Assert-True ($result.Error -like '*different registry*') 'Publisher must not replace registry configuration implicitly.'
Assert-True (-not (@($result.Calls | Where-Object { $_ -contains 'build' }).Count)) 'Registry mismatch must fail before build.'
Write-Host 'PASS: registry authentication boundary'

foreach ($failure in @('account list', 'acr list', 'webapp config set')) {
    $result = Invoke-Scenario -Options $explicit -Failure $failure
    Assert-True ($result.Error -like '*Azure CLI failed*') "Failure not propagated: $failure"
    Assert-True ($result.Image -eq 'registry.example/simplechat:previous') "Unexpected image update after failure: $failure"
}
$result = Invoke-Scenario -Options $rollback -Failure 'acr repository show'
Assert-True ($result.Error -like '*Azure CLI failed*') 'Existing image lookup failure must be reported.'
Assert-True ($result.Image -eq 'registry.example/simplechat:previous') 'Existing image lookup failure must preserve the app.'
Write-Host 'PASS: discovery, manifest, and update errors stop the flow'

$result = Invoke-Scenario -Options $explicit -BuildDigest 'invalid'
Assert-True ($result.Error -like '*digest*') 'Malformed build digest must fail.'
Assert-True ($result.Image -eq 'registry.example/simplechat:previous') 'Malformed build digest must not update the app.'
$result = Invoke-Scenario -Options $rollback -ManifestDigest 'invalid'
Assert-True ($result.Error -like '*digest*') 'Malformed existing image digest must fail.'
Assert-True ($result.Image -eq 'registry.example/simplechat:previous') 'Malformed existing image digest must not update the app.'
$result = Invoke-Scenario -Options $explicit -IgnoreUpdate
Assert-True ($result.Error -like '*verification failed*') 'Configuration mismatch must not report success.'
Write-Host 'PASS: digest and post-update verification'

$slotOptions = $explicit.Clone(); $slotOptions.Slot = 'staging'; $slotOptions.ResourceGroupName = 'app-rg'
$result = Invoke-Scenario -Options $slotOptions
Assert-True (-not $result.Error) "Slot publish failed: $($result.Error)"
foreach ($call in $result.Calls) {
    if ($call[0] -eq 'webapp' -and $call[1] -ne 'list') {
        Assert-True (($call -contains '--slot') -and $call[$call.IndexOf('--slot') + 1] -eq 'staging') 'Every target-app operation must address the selected slot.'
    }
}
Write-Host 'PASS: deployment slot scoping'

$automatic = $explicit.Clone(); $automatic.Remove('ImageRepository'); $automatic.Remove('ImageTag'); $automatic.AllowDirty = $true
$result = Invoke-Scenario -Options $automatic -Dirty $true
Assert-True (-not $result.Error) "Automatic image defaults failed: $($result.Error)"
$generatedBuild = @($result.Calls | Where-Object { $_[0] -eq 'acr' -and $_[1] -eq 'build' })[0]
$generatedTag = $generatedBuild[$generatedBuild.IndexOf('--image') + 1]
Assert-True ($generatedTag -match '^simplechat:build-\d{8}T\d{9}Z-abcdef1234567890-dirty$') 'Generated image tag must record UTC build time, source revision, and dirty status.'
Write-Host 'PASS: current repository inference and generated dirty tag'

$result = Invoke-Scenario -Options @{ ImageRepository = 'simplechat'; ImageTag = 'cancel' } -Answers @('1', '1', '1', 'n')
Assert-True ($result.Error -like '*cancel*') 'Declining confirmation should cancel.'
Assert-True (-not (@($result.Calls | Where-Object { $_ -contains 'build' -or $_ -contains 'set' }).Count)) 'Cancellation must make no changes.'
$result = Invoke-Scenario -Options @{ ImageRepository = 'simplechat' } -Answers @('1') -EmptyRegistries
Assert-True ($result.Error -like '*No accessible choices*') 'An empty registry list must give an actionable error.'
Write-Host 'PASS: final confirmation refusal and empty choices'

foreach ($badTag in @('bad/tag', '--bad', ('a' * 129))) {
    $badOptions = $explicit.Clone(); $badOptions.ImageTag = $badTag
    $result = Invoke-Scenario -Options $badOptions
    Assert-True ($result.Error -like '*ImageTag*') "Invalid tag accepted: $badTag"
    Assert-True (-not (@($result.Calls | Where-Object { $_ -contains 'build' }).Count)) 'Invalid tag must fail before build.'
}
$badOptions = $explicit.Clone(); $badOptions.ImageRepository = 'simplechat:tag'
$result = Invoke-Scenario -Options $badOptions
Assert-True ($result.Error -like '*ImageRepository*') 'Repository input must not contain a tag.'
Write-Host 'PASS: image reference validation'

$taskConfig = Get-Content (Join-Path $PSScriptRoot '../.vscode/tasks.json') -Raw | ConvertFrom-Json
Assert-True ($taskConfig.tasks.Count -eq 4) 'Expected interactive, preview, beta, and dev tasks.'
Assert-True ($taskConfig.inputs.Count -eq 1) 'Tasks must share one image input.'
$imageInput = $taskConfig.inputs[0]
Assert-True ($imageInput.type -eq 'promptString' -and $imageInput.default -eq 'simplechat:latest') 'Tasks must prompt for an image reference defaulting to simplechat:latest.'
foreach ($task in $taskConfig.tasks) {
    Assert-True ($task.type -eq 'process' -and $task.command -eq 'pwsh') 'Tasks must use PowerShell without shell interpolation.'
    Assert-True ($task.args -contains '${workspaceFolder}/deployers/azurecli/publish-simplechat.ps1') 'Tasks must share the publisher.'
    Assert-True (-not ($task.args -contains '-Yes' -or $task.args -contains '-AllowDirty')) 'Tasks must retain deployment and dirty-source confirmation.'
    $inputReference = '${input:' + $imageInput.id + '}'
    Assert-True (($task.args -contains '-ImageName') -and $task.args[$task.args.IndexOf('-ImageName') + 1] -eq $inputReference) 'Every task must pass the prompted image reference as one argument.'
}
Assert-True ($taskConfig.tasks[1].args -contains '-WhatIf') 'Preview task must be read-only.'
foreach ($target in @(
    @{ Environment = 'beta'; Subscription = '8a60416d-813d-4904-b115-2cebaaf63fea' },
    @{ Environment = 'dev'; Subscription = '8c7e0020-34d5-4be4-ac62-5c744df2700b' }
)) {
    $targetTask = @($taskConfig.tasks | Where-Object { $_.label -eq "SimpleChat: Publish $($target.Environment) container (confirm)" })
    Assert-True ($targetTask.Count -eq 1) 'Each environment must have one explicit task.'
    $targetArguments = $targetTask[0].args
    $expected = @{
        '-SubscriptionId' = $target.Subscription
        '-ResourceGroupName' = "simplechat-2026$($target.Environment)-rg"
        '-AcrName' = "simplechat2026$($target.Environment)acr"
        '-WebAppName' = "simplechat-2026$($target.Environment)-app"
    }
    foreach ($parameter in $expected.Keys) {
        Assert-True (($targetArguments -contains $parameter) -and $targetArguments[$targetArguments.IndexOf($parameter) + 1] -eq $expected[$parameter]) "Wrong $parameter in $($target.Environment) task."
    }
    Assert-True ($targetArguments -contains '-UseWebhook') "The $($target.Environment) task must use the matching registry webhook."
}
$tokens = $null
$parseErrors = $null
$syntaxTree = [System.Management.Automation.Language.Parser]::ParseFile($publisher, [ref]$tokens, [ref]$parseErrors)
Assert-True ($null -ne $syntaxTree -and $parseErrors.Count -eq 0) 'Publisher must parse cleanly.'
$parameterNames = @($syntaxTree.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath })
Assert-True (($parameterNames[0..11] -join ',') -eq 'SubscriptionId,AcrName,WebAppName,ResourceGroupName,ImageRepository,ImageTag,Slot,NonInteractive,Yes,AllowDirty,BuildOnly,SkipBuild') 'Existing positional parameter order must remain unchanged.'
Write-Host 'PASS: shared task wiring and PowerShell syntax'

Write-Host 'All interactive publisher regression checks passed.'