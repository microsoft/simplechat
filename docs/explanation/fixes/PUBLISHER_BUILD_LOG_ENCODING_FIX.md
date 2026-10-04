# Publisher Build Log Encoding Fix (Deployer 1.0.34)

Fixed/Implemented in version: **deployer 1.0.34**.

Application version: **0.261.042** in `application/single_app/config.py`, unchanged.
Deployment-only version tracking increments `deployers/version.txt`. Refs #1518.

## Issue and Root Cause

Streaming ACR build logs through Azure CLI on Windows could raise
`UnicodeEncodeError` when Colorama wrote a Unicode arrow through a `cp1252` output
stream. The publisher already supplied `--only-show-errors`, but that option
suppresses CLI warnings rather than the build's streamed output. A client-side
logging failure does not establish whether the remote build failed or stopped.

## Changes

- `deployers/azurecli/publish-simplechat.ps1` uses `az acr build --no-logs` without
  `--no-wait`. Azure CLI handles run-status polling until completion.
- The publisher captures structured run metadata and requires `Succeeded`, the
  requested registry/repository/tag output, and a valid SHA-256 digest before
  changing App Service. Native CLI failures still stop subsequent steps.
- New builds deploy their run's output digest instead of resolving the tag after
  completion. This prevents a concurrent build replacing `latest` from changing
  which artifact the current invocation deploys.
- `.vscode/tasks.json` provides a shared `repository:tag` prompt defaulting to
  `simplechat:latest`, and explicit beta/dev tasks. All tasks retain confirmation
  and dirty-source approval. The preview task remains read-only.
- `-ImageName` supports the same combined input for automation. Separate
  `-ImageRepository` and `-ImageTag` parameters remain supported, but cannot be
  combined with `-ImageName`. Direct calls without a tag retain generated tags.

Build-only mode checks the completed run without touching an app. Existing-image
deployment with `-SkipBuild` still resolves the requested tag's digest. No login,
permission, pull-authentication, or networking settings change. Application
routing and inference behavior are unaffected.

## Usage and Recovery

Run **Tasks: Run Task**, select the beta or dev publish task, and accept
`simplechat:latest` or enter a distinct reference such as `simplechat:dev-20260925`.
The `latest` tag is replaced when the build pushes, but App Service is digest-pinned.

During a build, the terminal waits without streaming logs. Use the ACR run view
in the Azure portal to inspect progress and logs. The publisher prints the run ID
and status when the command returns. Inspect any run affected by the earlier
encoding error before retrying; it may still be running or may have succeeded.
There is no automatic retry or rollback. The previous app image is printed before
an update, and startup health/version must still be verified after deployment.

Webhook-based beta/dev publishing was added in deployer 1.0.35. See
[PUBLISHER_WEBHOOK_DEPLOYMENT_FIX.md](PUBLISHER_WEBHOOK_DEPLOYMENT_FIX.md) for why
that mode leaves an already-configured image tag unchanged.

See the [publisher reference](../../../deployers/azurecli/README.md#interactive-container-publishing)
for target IDs, parameters, prerequisites, and rollback commands.

## Validation

The new log-suppression regression failed against the previous publisher before
implementation. All 24 offline check groups in
`functional_tests/test_azurecli_publish_script.ps1` passed after the change. They
cover synchronous log-free build arguments, unsuccessful/missing run results,
missing output images, malformed digests, concurrent tag replacement, combined
image validation, beta/dev task configuration, and existing safety checks.

The tests fake Azure CLI, Git, and prompts; they do not bootstrap SimpleChat,
read credentials, or contact Azure. No live build or deployment was performed for
this fix, so the customer's original Unicode log stream and runtime startup have
not been reproduced or verified live.