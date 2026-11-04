# Existing staging UI validation

Version: **0.261.400**, tracked in `application/single_app/config.py`.

Fixed/Implemented in version: **0.261.399**; isolated runner-local validation
implemented in **0.261.400**.

## Purpose and scope

The staging Actions workflow checks an already deployed SimpleChat application.
It does not deploy the checked-out commit, run `azd`, restore deployment
configuration, provision resources, or grant permissions.

This distinction matters when interpreting a successful run: the smoke tests
verify the currently deployed application using the checked-out test code.
Offline functional checks validate source changes separately. Deploying a new
application version remains an explicit, separate operation.

The workflow is `.github/workflows/staging-ui-smoke.yml`, named **Staging UI
Smoke Tests**. The former `staging-azd-ui-tests.yml` deployment workflow is
disabled rather than receiving replacement-tenant deployment credentials.
The new workflow uses the separate **Staging-Validation** GitHub Environment.

It runs on pushes to `Staging` and on same-repository pull requests into
`Staging` or the temporary V2 integration branch when the workflow or its smoke
tests change. Fork pull requests cannot run the authenticated job. Manual
dispatch is also defined; GitHub requires that dispatchable workflow to exist
on the default branch before it can be invoked there. The trusted PR event
allows initial validation without a protected-branch promotion.

The `azd_command` dispatch input is removed; `pytest_target` remains available.

For this repository's current environment split:

| Environment | Target | Automation |
|---|---|---|
| Staging | `https://simplechat-2026stage-app.azurewebsites.net/` | Existing-deployment validation through `Staging-Validation` |
| Beta | `https://simplechat-2026beta-app.azurewebsites.net/` | Manual development; no automatic beta target is added |
| Local | The developer's explicitly configured loopback origin | Separate local configuration and signed-in state |

No tenant identifiers, application secrets, or deployment connection strings
belong in shared workflow defaults.

## Dependencies and identities

Both the JavaScript and Python Playwright smoke tests launch Chromium directly
on the GitHub runner. No paid Azure browser workspace, workspace endpoint or
Azure subscription role is required. The separately retained
`test:staging:azure` command is optional and is not invoked by this workflow.

Application authentication uses a dedicated test identity through OIDC or
approved browser state. OIDC login uses `allow-no-subscriptions: true`: the
identity needs permission to the staging application, not Contributor,
User Access Administrator or deployment access to Azure resources.

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
caller before establishing a browser session. Its default required role remains
`Admin`; this staging installation explicitly uses **User** and allowlists only
its dedicated CI application. App Service Easy Auth remains enabled.

The authorized setup registered the staging API audience, enabled application
assignment for its existing User role, and assigned only that role to the
secretless CI service principal. Its federation uses the repository's actual
OIDC subject template, which includes immutable owner/repository IDs and the
`Staging-Validation` Environment. It has no client secret, Admin role or Azure
RBAC grants. This permits ordinary chat smoke
testing without exposing administrative settings or acting as a real user.
The workflow itself does not create identities, alter authentication or grant
permissions.

An authorized dedicated test user's Playwright storage state remains the
alternative to CI bearer-session authentication. State is a credential: keep it
in the approved secret store, never in source control or diagnostic output.
Old-tenant tokens and browser state do not become valid merely by changing a
tenant variable.

## GitHub Environment configuration

Set values on the repository's **Staging-Validation** GitHub Environment:

| Value | Meaning |
|---|---|
| `AZURE_CLIENT_ID` | Dedicated GitHub OIDC workload application; required for bearer authentication |
| `AZURE_TENANT_ID` | That workload's current tenant; required for bearer authentication |
| `SIMPLECHAT_UI_BASE_URL` | Explicit staging HTTPS base URL |
| `SIMPLECHAT_UI_AUTH_RESOURCE` | Registered staging API audience for bearer authentication |

Also configure one supported application-authentication path:

- `SIMPLECHAT_UI_AUTH_RESOURCE` for an already approved CI bearer-session
  configuration; or
- `SIMPLECHAT_UI_STORAGE_STATE_B64` / `SIMPLECHAT_UI_ADMIN_STORAGE_STATE_B64`
  containing appropriately authorized, current browser state.

For browser-state authentication, the Azure identity/resource values are not
required and Azure login is skipped. Missing required values, missing
authentication, and a non-HTTPS Actions target fail configuration validation.
There is no inferred deployment name or beta fallback. Tokens acquired by the
job are masked and remain job-scoped.

### GitHub OIDC subject and platform authorization

Do not assume the standard `repo:<owner>/<repo>:environment:<name>` subject.
This repository customizes its subject with `repository_owner_id`,
`repository_id` and `context`. Inspect
`gh api repos/microsoft/simplechat/actions/oidc/customization/sub` and the
Azure login step's non-secret subject details, then configure Entra federation
to match exactly. The verified staging subject is
`repository_owner_id:6154722:repository_id:890680638:environment:Staging-Validation`.
Changing GitHub's organization policy to accommodate an incorrect federation
is unnecessary.

App Service Easy Auth also needs an explicit client-application allowlist that
includes the existing web-app client and the dedicated CI client. Keep tenant
and audience validation and the application's CI caller/role checks intact.
During setup, a valid User token was authenticated but rejected with platform
substatus **403.76** because its client was not allowed. The effective
`WEBSITE_AUTH_AAD_ACL` confirmed the repaired client list. Do not interpret
empty-looking ARM policy values as proof that a client is accepted.

### Test-identity onboarding

Authentication success does not imply that chat is ready. A new CI identity can
still be redirected to the application's Terms of Use page. Complete that
identity's onboarding only after the operator approves its consent. Do not
disable the terms requirement globally, silently accept future terms, or
record acceptance on a real user's behalf to make a smoke test pass.

The staging browser run now passes the CI session exchange and reaches this
onboarding page. A missing chat composer at that point is not an authentication
or model failure. Full chat/model validation remains pending approved
onboarding and a subsequent successful run.

The workflow no longer consumes `AZD_ENV_FILE_B64`, `AZD_CONFIG_FILE_B64`,
`AZURE_ENV_NAME`, `AZURE_LOCATION`, or `DEPLOYMENT_APPNAME` to prepare a
deployment. Unused legacy secrets are not automatically deleted.

### Replacement-tenant transition

Disable the older deploy-and-test workflow and confirm no deployment run is
active before changing access. Keep its deployment Environment and legacy
secrets separate from the new validation Environment.

Configure the validation Environment's verified tenant, workload identity,
registered app audience and target URL together. Its deployment policies allow
`Staging`, the approved feature branch for dispatch, and PR merge refs; the
workflow's same-repository guard rejects fork execution. Do not copy beta's
settings or refresh credentials under an older workflow that can still run
`azd up`.

For bearer authentication, configure the existing staging endpoint with
`ENABLE_CI_BEARER_SESSION_AUTH=true`,
`CI_BEARER_SESSION_ALLOWED_APP_IDS=<dedicated-ci-client-id>`, and
`CI_BEARER_SESSION_REQUIRED_ROLE=User`. Apply these coherently so the enabled
endpoint is never left without its intended caller restriction. App-setting
changes can restart staging; they are not application deployments.

Identity and authentication changes require operator approval; a validation
job is not a provisioning mechanism. The current staging-only setup was
explicitly authorized. It does not configure beta, production or local sign-in.

## Validation behavior

The job validates configuration, logs in with OIDC, obtains application
authentication when configured, and checks endpoint reachability with normal
TLS certificate validation.

A redirect, 401, or 403 can establish that an authentication boundary is
reachable; it does not prove that the application is ready or the test identity
is authorized. Both subsequent authenticated smoke paths must succeed:

- `npm run test:staging` in `ui_tests/playwright-workspaces`;
- `python -m pytest "$PYTEST_TARGET" -m ui -ra`, defaulting to
  `ui_tests/test_staging_chat_smoke.py`.

The smoke tests create their own conversation, send a short prompt, verify an
assistant response, and attempt cleanup of that conversation. These are real
staging writes and model calls, not read-only health probes. Use a dedicated test
identity and the intended staging data boundary.

Only failure PNG screenshots are uploaded, with seven-day retention. Raw
traces, browser storage state and HTML reports are excluded because they can
contain authentication headers or cookies. Local diagnostic files remain
sensitive even when they are not uploaded.

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
of deployment commands, same-repository execution, runner-local browsers and
credential-safe artifact selection:

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
