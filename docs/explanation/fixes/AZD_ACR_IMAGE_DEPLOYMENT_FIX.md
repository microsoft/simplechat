# AZD ACR Image Deployment Fix - Version 0.261.394

## Issue and root cause

The existing `predeploy` hook built and pushed a container image in Azure Container
Registry, but the `web` service declared `language: python` and an unsupported
`dockerfile` property. With azd 1.37.2, that service selects Python ZIP deployment
instead of updating the App Service container image. Building a new image alone
also cannot update an app that remains pinned to an earlier image digest.

**Fixed in version: 0.261.394**, recorded in
`application/single_app/config.py`. **Deployer version: 1.0.35**, recorded in
`deployers/version.txt`.

## Technical details

`deployers/azure.yaml` now declares the web service as `language: docker`, sets
`image` to `${var_containerRegistry}/${var_imageName}:latest`, and enables
`docker.imagePassthrough`. The existing Windows and POSIX hooks remain responsible
for building the root repository context with `application/single_app/Dockerfile`
and publishing both timestamped and `latest` tags.

Image passthrough tells azd to roll out that already-built image without ZIP
packaging, a second build, or a local Docker daemon. App Service still pulls the
image using its existing registry authentication. The Dockerfile remains
responsible for Gunicorn startup and the compiled same-origin React V2 bundle.

This configuration requires an azd release supporting `docker.imagePassthrough`;
it was validated against 1.37.2. No infrastructure provisioning, application
authentication changes, or database changes are part of the fix.

## Usage and impact

From `deployers`, select the existing local environment and run:

```powershell
azd env select <environment>
azd deploy
```

The environment must contain the matching `var_containerRegistry`, `var_imageName`,
and the other outputs consumed by the existing predeploy hook. Use the existing
app's environment, not values copied from a different deployment.

The hook still stops the app during the remote build. After a successful build,
azd updates App Service to the published `latest` image. Record the resulting
digest and retain the prior exact image reference for rollback. Restoring a pinned
digest deliberately stops following `latest` until the next successful rollout.

## Testing and validation

`functional_tests/test_azd_acr_image_deployment.py` parses the actual manifest and
checks the container-image deployment contract and both platforms' ACR build tags.
The deployment-contract test fails against the old Python service declaration.
Existing ACR archive and Windows-hook tests cover build context exclusions and
persisted environment hydration.

```powershell
python -m pytest .\functional_tests\test_azd_acr_image_deployment.py .\functional_tests\test_acr_build_context.py .\functional_tests\test_azd_windows_hook_environment.py .\functional_tests\test_azd_windows_hooks.py -q
```

Before the fix, a successful ACR build could be followed by ZIP deployment without
adopting the built image. After the fix, azd selects the remote container artifact
for App Service deployment. Operational validation must still correlate the ACR
digest, App Service image configuration, and successful application startup;
unauthenticated HTTP 401 responses are not proof that the new build is ready.
