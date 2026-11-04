# Existing staging UI validation

Version: **0.261.399**, tracked in `application/single_app/config.py`.

Fixed/Implemented in version: **0.261.399**.

## Purpose and scope

The staging Actions workflow checks an already deployed SimpleChat application.
It does not deploy the checked-out commit, run `azd`, restore deployment
configuration, provision resources, or grant permissions.

This distinction matters when interpreting a successful run: the smoke tests
verify the currently deployed application using the checked-out test code.
Offline functional checks validate source changes separately. Deploying a new
application version remains an explicit, separate operation.

The workflow retains its existing file path,
`.github/workflows/staging-azd-ui-tests.yml`, but is named **Staging UI Smoke
Tests**. It runs on pushes to `Staging` and supports manual dispatch. The
`azd_command` dispatch input has been removed; `pytest_target` remains available.

For this repository's current environment split:

| Environment | Target | Automation |
|---|---|---|
| Staging | `https://simplechat-2026stage-app.azurewebsites.net/` | Existing-deployment validation through the `Staging` GitHub Environment |
| Beta | `https://simplechat-2026beta-app.azurewebsites.net/` | Manual development; no automatic beta target is added |
| Local | The developer's explicitly configured loopback origin | Separate local configuration and signed-in state |

No tenant identifiers, application secrets, or deployment connection strings
belong in shared workflow defaults.

## Dependencies and identities

The existing validation path uses Azure OIDC login, Microsoft Playwright
Workspaces, and the Python Playwright smoke test. An already authorized
test identity and browser workspace must exist before a live run.

Keep these identities distinct:

- The application's `TENANT_ID` and `CLIENT_ID` identify its sign-in registration.
- Actions' `AZURE_TENANT_ID` and `AZURE_CLIENT_ID` identify the workload used by
  `azure/login`. The Actions client ID is not automatically the application's
  sign-in client ID.
- `SIMPLECHAT_UI_AUTH_RESOURCE` identifies the audience for the optional CI
  bearer-session exchange. Verify its actual registered value; do not construct
  an audience from an unrelated client ID.

The existing `/ci-auth/session` path is disabled by default. When explicitly
configured, it validates the token, required application role and allowed
caller before establishing a browser session. Its default required role is
`Admin`. The validation workflow does not enable this endpoint, change app
roles, grant a CI identity Admin access, or bypass App Service Easy Auth.

An authorized dedicated test user's Playwright storage state remains the
alternative to CI bearer-session authentication. State is a credential: keep it
in the approved secret store, never in source control or diagnostic output.
Old-tenant tokens and browser state do not become valid merely by changing a
tenant variable.

## GitHub Environment configuration

Set values on the repository's `Staging` GitHub Environment, or the explicitly
selected `STAGING_GITHUB_ENVIRONMENT`. The job requires:

| Value | Meaning |
|---|---|
| `AZURE_CLIENT_ID` | Existing GitHub OIDC workload application |
| `AZURE_TENANT_ID` | That workload's current tenant |
| `AZURE_SUBSCRIPTION_ID` | Existing Azure login context |
| `SIMPLECHAT_UI_BASE_URL` | Explicit staging HTTPS base URL |
| `PLAYWRIGHT_SERVICE_URL` | Existing, accessible Playwright workspace endpoint |

Also configure one supported application-authentication path:

- `SIMPLECHAT_UI_AUTH_RESOURCE` for an already approved CI bearer-session
  configuration; or
- `SIMPLECHAT_UI_STORAGE_STATE_B64` / `SIMPLECHAT_UI_ADMIN_STORAGE_STATE_B64`
  containing appropriately authorized, current browser state.

Missing required values, missing authentication, and a non-HTTPS Actions target
fail configuration validation. There is no inferred deployment name or beta
fallback. Tokens acquired by the job are masked and remain job-scoped.

The workflow no longer consumes `AZD_ENV_FILE_B64`, `AZD_CONFIG_FILE_B64`,
`AZURE_ENV_NAME`, `AZURE_LOCATION`, or `DEPLOYMENT_APPNAME` to prepare a
deployment. Unused legacy secrets are not automatically deleted.

### Replacement-tenant transition

First land the validation-only workflow and confirm no older deploy-and-test run
is still active. Only then change the Environment's tenant, workload identity,
subscription, app audience, browser workspace and target URL as a coherent,
verified configuration.

Do not refresh credentials under an older workflow that can still run `azd up`:
doing so could unintentionally reactivate deployment. Verify access to the
actual staging resource rather than relying on the CLI's cached subscription
list or copying beta's settings.

If the new tenant lacks an approved test identity, application consent/role
assignment, browser state, or Playwright workspace, report that prerequisite.
Creating accounts/resources, changing application authentication, or granting
access requires a separate approval; a validation job is not a provisioning
mechanism.

## Validation behavior

The job validates configuration, logs in with OIDC, obtains application
authentication when configured, and checks endpoint reachability with normal
TLS certificate validation.

A redirect, 401, or 403 can establish that an authentication boundary is
reachable; it does not prove that the application is ready or the test identity
is authorized. Both subsequent authenticated smoke paths must succeed:

- `npm run test:staging:azure` in `ui_tests/playwright-workspaces`;
- `python -m pytest "$PYTEST_TARGET" -m ui -ra`, defaulting to
  `ui_tests/test_staging_chat_smoke.py`.

The smoke tests create their own conversation, send a short prompt, verify an
assistant response, and attempt cleanup of that conversation. These are real
staging writes and model calls, not read-only health probes. Use a dedicated test
identity and the intended staging data boundary.

Failure screenshots and traces are collected under `ui_tests/artifacts/` and
the existing Playwright report directories. Treat authenticated artifacts as
sensitive and retain them according to the repository's access policy.

## Local development

Use the [local development guide](../running_simplechat_locally.md) for a
repo-local Python environment, ignored application `.env`, matching local OAuth
callback, and current-tenant data access. The smoke-test base URL and storage
state must match the local origin; staging/beta cookies are not local sessions.

The offline Cosmos contract workflow has no dependency on these live settings.
It continues to block network access before collection. Do not add Azure login
or a live staging URL to make its fixtures pass.

## Testing and limitations

`functional_tests/test_staging_ui_cicd_workflow.py` checks parsed workflow
configuration, pinned actions, required authentication, TLS behavior, absence
of deployment commands, and the existing Python/Playwright smoke wiring:

```powershell
python -m pytest .\functional_tests\test_staging_ui_cicd_workflow.py -q
```

These configuration tests do not establish that a live tenant is configured or
that a hosted application is healthy. Live success requires actual
authenticated smoke results. Missing access must be reported as blocked, not
replaced with a login redirect, skipped test, or a beta result.

The [historical deployment guide](v0.241.014/STAGING_UI_CICD.md) describes the
older provisioning pattern and standalone
`deployers/Initialize-GitHubActionsStaging.ps1`. That script remains unchanged
and is not invoked by this validation-only workflow.
