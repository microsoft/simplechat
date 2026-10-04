# Webhook-Based Container Publishing (Deployer 1.0.35)

Fixed/Implemented in version: **deployer 1.0.35**.

Application version: **0.261.042** in `application/single_app/config.py`, unchanged.
Deployment-only version tracking increments `deployers/version.txt`. Refs #1518.

## Issue and Root Cause

The beta App Service already used
`simplechat2026betaacr.azurecr.io/simplechat:latest`, and an ACR push webhook was
configured for `simplechat:latest`. The publisher built and pushed that tag, then
attempted to change the app to a digest reference with `az webapp config set`.
That setting change was not needed for webhook delivery and failed with Azure CLI
exit code 255. The reported wrapper exception did not include the underlying CLI
or service error, so the specific reason that API request failed is not asserted
here.

## Changes

- The beta and dev VS Code tasks opt into `-UseWebhook`.
- Before building, the publisher requires the app to already use the exact ACR
  repository/tag supplied by the task and requires an enabled matching ACR push
  webhook. A mismatch stops before the build.
- After a successful remote build and digest verification, webhook mode leaves
  App Service configuration unchanged. It reports the digest and reminds the
  operator to verify webhook delivery and application health.
- Ordinary publishing retains its existing digest-pinned App Service update.
- Deployer version is **1.0.35**; application version remains **0.261.042**.

Webhook mode tracks a mutable tag such as `latest`; it does not pin App Service to
the run's digest and tag replacement is not a rollback mechanism. Prefer unique
tags and ordinary digest-pinned updates where direct rollback is important. Do not
enable publishing credentials solely to work around a webhook `401`; correct or
remove the failing hook if another correctly scoped webhook is accepting the push.

## Validation

All 26 offline check groups in `functional_tests/test_azurecli_publish_script.ps1`
passed. They verify image/tag and hook-scope preflight, no App Service config
mutation in webhook mode, and the existing build, digest, safety, and task
contracts. No application bootstrap or Azure mutations were performed by tests.

Read-only Azure checks on 2026-09-25 confirmed:

- Beta and dev apps were configured to their respective registry's
  `simplechat:latest` tag.
- Both registries had enabled `push` webhooks scoped to `simplechat:latest`.
- The beta build digest
  `sha256:00e072a606f7f63dc623e0c7b0f722665726d8ec9f62360e19c04a44662557c6`
  produced a webhook event accepted with HTTP 202 by the beta App Service SCM
  hostname. A second hook for the same target returned HTTP 401.

The accepted webhook event confirms delivery, not container startup, application
version, or health. Inspect the app after deployment. No live build was run as
part of this change.