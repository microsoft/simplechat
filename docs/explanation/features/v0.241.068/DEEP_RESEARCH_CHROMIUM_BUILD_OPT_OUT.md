# Deep Research Chromium Build Opt-Out

Version implemented: **0.241.068**

Fixed/Implemented in version: **0.241.068**

## Overview

SimpleChat deployments can now opt out of packaging Playwright Chromium into the application container image. This keeps the existing distroless final image pattern while giving operators a deployment-time choice for environments that do not want a browser runtime in the app container.

## Dependencies

- `application/single_app/config.py` version `0.241.068`
- `application/single_app/Dockerfile` build argument: `INSTALL_PLAYWRIGHT_CHROMIUM`
- `deployers/azure.yaml` predeploy ACR build hook
- `deployers/version.txt` deployer version `1.0.3`

## Technical Specifications

- The Dockerfile defaults `INSTALL_PLAYWRIGHT_CHROMIUM=true`.
- When true, the builder stage installs Chromium native dependencies, downloads Playwright Chromium, preserves sandbox helper permissions, and copies browser runtime files into the final distroless image.
- When false, the builder stage skips Chromium native packages and skips the Playwright Chromium browser download. The app still includes the Python Playwright package, but no Chromium browser bundle is packaged into the image.
- The final distroless image remains `mcr.microsoft.com/azurelinux/distroless/python:3.12` in both modes.
- Source Review runtime probing continues to report whether JavaScript rendering is actually available after deployment.

## Usage Instructions

To skip Chromium during azd deployment, set the deployment environment value before running `azd up` or `azd deploy`:

```powershell
azd env set SIMPLECHAT_INSTALL_CHROMIUM false
azd deploy
```

For a one-off local shell override:

```powershell
$env:SIMPLECHAT_INSTALL_CHROMIUM = "false"
azd deploy
```

On POSIX shells:

```sh
SIMPLECHAT_INSTALL_CHROMIUM=false azd deploy
```

Set the value back to `true` or remove it to return to the default browser-enabled image build.

## Security and Operations Notes

Skipping Chromium is the lowest browser-risk container posture: the app image does not include a browser binary or the extra native rendering dependencies. Deep Research still works through plain HTTP/HTML extraction paths, but JavaScript rendering fallback will show as unavailable in Admin Settings.

Installing Chromium remains useful for JavaScript-heavy source archives. When enabled, keep Chromium sandboxing on, restrict Deep Research users/domains where practical, and monitor CPU and memory because browser rendering is heavier than plain source fetches.

## Testing and Validation

- `functional_tests/test_deep_research_chromium_build_opt_out.py` validates the Dockerfile build argument, azd ACR build wiring, and deployer version bump.
- `functional_tests/test_source_review_security.py` continues to validate runtime capability reporting and graceful degradation when rendering is unavailable.

## Known Limitations

The deployment hook does not prompt interactively by default because azd deploys often run in CI/CD. Operators should set `SIMPLECHAT_INSTALL_CHROMIUM=false` before deployment when they want to prevent Chromium from being packaged.
