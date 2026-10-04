# Publisher Automatic Variable Fix (Deployer 1.0.33)

Fixed in version: **deployer 1.0.33**. Application version: **0.261.042**.
Refs #1518.

## Issue and root cause

The beta publish task exposed a PowerShell analyzer warning because
`Select-PublishTarget` assigned resource-selection results to `$matches`.
PowerShell variable names are case-insensitive, so this name collides with the
automatic `$Matches` variable used for regular-expression match results.
The warning alone does not establish that an ACR build failed.

## Changes and impact

- Renamed the local collection and its references to `$matchingTargets` in
  `deployers/azurecli/publish-simplechat.ps1`.
- Added an AST regression check in
  `functional_tests/test_azurecli_publish_script.ps1` for assignments to
  `$Matches`, including case and scope variants.
- Updated `deployers/version.txt` from 1.0.32 to 1.0.33. The independent
  application version in `application/single_app/config.py` remains unchanged.

Resource selection, confirmation, image builds, and deployment behavior are
unchanged. No task configuration changes are required.

## Validation

The new regression check failed against the original assignment. Run it together
with the existing offline publisher checks using:

```powershell
pwsh -NoProfile -File ./functional_tests/test_azurecli_publish_script.ps1
```

The tests use scoped fakes for Azure CLI, Git, and user prompts. No live build or
deployment is needed to validate this rename.