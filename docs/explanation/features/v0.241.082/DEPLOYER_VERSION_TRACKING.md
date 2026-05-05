# Deployer Version Tracking

Version: 0.241.082

Fixed/Implemented in version: **0.241.082**

Dependencies: `deployers/version.txt`, `.github/instructions/update_deployer_version.instructions.md`, `CLAUDE.md`, `functional_tests/test_deployer_version_tracking.py`, `docs/explanation/features/index.md`

## Overview

This feature adds a standalone deployer version marker at `deployers/version.txt`.

The deployer version is intentionally separate from the application version in `application/single_app/config.py`. It is meant for CI/CD logic tracking, deployment workflow compatibility checks, and future automation that needs to detect deployer changes without coupling that logic to app feature releases.

## Technical Specifications

The deployer version marker uses a plain text semantic version string with no prefixes, labels, or extra metadata.

Current value:

```text
1.0.0
```

This format keeps the file easy to consume from shell scripts, PowerShell, GitHub Actions, Azure DevOps pipelines, or `azd`-adjacent helper scripts.

The initial tracking model is:

- bump the deployer version when CI/CD logic, deployer scripts, deployer configuration structure, or deployment workflow assumptions change
- keep the deployer version independent from the app version in `config.py`
- use the plain file content as the single source of truth for deployment-logic version checks

The repository also includes a targeted instruction file at `.github/instructions/update_deployer_version.instructions.md` so agent-driven edits under `deployers/**` are expected to bump `deployers/version.txt` in the same change.

## Usage Instructions

Example reads from the repository root:

```powershell
Get-Content .\deployers\version.txt
```

```bash
cat deployers/version.txt
```

CI/CD systems can compare this value against known-compatible deployer logic or stamp it into build metadata independently from the app container version.

## Testing And Validation

Coverage for this feature includes:

- `functional_tests/test_deployer_version_tracking.py` to validate the standalone version file, the current app-version wiring for this feature, and the related documentation references
- the targeted deployer instruction file and repo guidance that require `deployers/version.txt` bumps when deployer files change
- direct repository inspection to verify the file lives under `deployers/` and stays separate from the application version source

Known limitation:

- the deployer version file is a tracking artifact only in this change; existing deployment scripts and pipelines are not yet auto-reading it unless they are updated to do so.