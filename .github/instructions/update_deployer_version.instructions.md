---
applyTo: 'deployers/**'
---

# Deployer Version Management

When a change modifies files under `deployers/`, include an update to `deployers/version.txt` in the same change.

## Rules

- Keep the deployer version separate from `application/single_app/config.py`.
- `deployers/version.txt` must contain only a plain semantic version string in the format `X.Y.Z`.
- Default to a patch increment when a deployer change is made: `1.0.0` -> `1.0.1`.
- Use a minor or major increment only when the deployer workflow or CI/CD compatibility contract changes intentionally.
- If the only deployer file being changed is `deployers/version.txt`, do not add an extra bump beyond the intended version update.

## Applies To

This rule covers deployer scripts, `azure.yaml`, `.azure` environment helpers, Bicep/Terraform deployer files, and other deployment workflow assets under `deployers/`.