# Staging UI CI/CD with GitHub Actions (v0.241.014)

## Overview

SimpleChat now includes a repeatable staging CI/CD pattern for repository administrators who want to validate the full Azure deployment path before promoting changes to `main`.

Implemented in version: **0.241.014**

Updated in version: **0.241.016** for the App Service warm-up wait behavior.
Updated in version: **0.241.017** for Microsoft Playwright Workspaces provisioning and Azure-hosted browser execution.
Updated in version: **0.241.018** for CI bearer session authentication with the GitHub Actions OIDC service principal.

This feature adds:

- A GitHub Actions workflow that runs on the `Staging` branch.
- Azure OIDC authentication for `azd up` or `azd deploy` without storing an Azure client secret in GitHub.
- A reusable PowerShell bootstrap script for creating the CI app registration, federated credential, Azure role assignments, and GitHub Environment values.
- An authenticated Playwright smoke test that starts a chat conversation, waits for an assistant response, and cleans up the created conversation.
- A Microsoft Playwright Workspaces resource for running the staging smoke path on Azure-hosted browsers.
- A disabled-by-default `/ci-auth/session` endpoint that lets staging CI exchange a freshly minted app-only bearer token for a Flask browser session.

The related version update is tracked in `application/single_app/config.py`.

## Dependencies

- Azure CLI authenticated as an administrator for bootstrap setup.
- Azure Developer CLI (`azd`).
- GitHub CLI (`gh`) authenticated with permission to manage repository environments, variables, and secrets.
- A protected GitHub Environment named `Staging`.
- A staging `azd` environment, normally named `staging`.
- A SimpleChat Enterprise App registration with the `Admin` app role assignable to the GitHub Actions service principal, or a Playwright storage state file for a dedicated staging test user/admin.

## Architecture

The account model uses the same GitHub OIDC service principal for deployment and staging UI automation, but keeps the browser login path tightly scoped:

- The GitHub workflow uses an Entra app registration and service principal with a GitHub OIDC federated credential. This identity deploys Azure resources and runs `azd`.
- For CI bearer auth, the workflow mints a short-lived token for the SimpleChat Enterprise App resource (`api://<client-id>`), calls `/ci-auth/session`, and receives a normal Flask session cookie for the test run.
- Browser storage state remains supported as a fallback for workflows that must test a real user session.

The workflow file is located at:

```text
.github/workflows/staging-azd-ui-tests.yml
```

The bootstrap script is located at:

```text
deployers/Initialize-GitHubActionsStaging.ps1
```

The staging smoke test is located at:

```text
ui_tests/test_staging_chat_smoke.py
```

## GitHub Environment Values

The bootstrap script writes these GitHub Environment variables:

```text
AZURE_CLIENT_ID
AZURE_TENANT_ID
AZURE_SUBSCRIPTION_ID
AZURE_LOCATION
AZURE_ENV_NAME
DEPLOYMENT_APPNAME
SIMPLECHAT_UI_BASE_URL
SIMPLECHAT_UI_AUTH_RESOURCE
PLAYWRIGHT_SERVICE_URL
PLAYWRIGHT_WORKSPACE_NAME
PLAYWRIGHT_WORKSPACE_RESOURCE_ID
```

The bootstrap script writes these GitHub Environment secrets when values are available:

```text
AZD_ENV_FILE_B64
SIMPLECHAT_UI_STORAGE_STATE_B64
SIMPLECHAT_UI_ADMIN_STORAGE_STATE_B64
```

`AZD_ENV_FILE_B64` contains the base64-encoded `azd env get-values` output for the target environment. This keeps the workflow reusable without requiring every `azd env set` value to be represented as a separate GitHub secret.

## Bootstrap Usage

From the repository root or the `deployers` folder, sign in first:

```powershell
az login
azd auth login
gh auth login
```

Create or refresh the staging CI/CD identity and GitHub Environment values:

```powershell
cd deployers
.\Initialize-GitHubActionsStaging.ps1 `
    -GitHubRepository "microsoft/simplechat" `
    -GitHubEnvironment "Staging" `
    -AzdEnvironmentName "staging" `
    -AppName "simplechat" `
    -AzureLocation "eastus" `
    -UiStorageStatePath "..\ui_tests\artifacts\auth\storage_state.json"
```

For an admin-only smoke test session, use `-AdminUiStorageStatePath` instead of `-UiStorageStatePath`.

By default, the bootstrap script also configures CI bearer auth for staging when it can resolve `ENTERPRISE_APP_CLIENT_ID` from the azd environment. It allows the SimpleChat `Admin` app role to be assigned to applications, assigns that role to the GitHub Actions service principal, sets `ENABLE_CI_BEARER_SESSION_AUTH=true` and `CI_BEARER_SESSION_ALLOWED_APP_IDS=<github-actions-client-id>` on the staging App Service, and writes `SIMPLECHAT_UI_AUTH_RESOURCE=api://<simplechat-enterprise-app-client-id>` to the GitHub Environment.

Use `-SkipCiBearerSessionAuth` if you want the workflow to require browser storage state instead.

To assign a dedicated test user or group to the SimpleChat Enterprise App during bootstrap, provide the Enterprise App client ID and principal object ID:

```powershell
.\Initialize-GitHubActionsStaging.ps1 `
    -GitHubRepository "microsoft/simplechat" `
    -EnterpriseAppClientId "<simplechat-enterprise-app-client-id>" `
    -UiTestPrincipalObjectId "<user-or-group-object-id>" `
    -UiTestAppRoleValue "User"
```

The script performs that assignment with your current Azure/Graph permissions during bootstrap. The GitHub Actions deployment identity does not need ongoing Graph write permissions for normal staging deployments.

## UI Authentication Options

The preferred staging CI path is CI bearer auth. The workflow acquires a fresh app-only token during each run with:

```bash
az account get-access-token --resource "$SIMPLECHAT_UI_AUTH_RESOURCE"
```

That token is masked in the job logs, exported only for the current job, and used by both the Azure Playwright Workspaces smoke test and the Python smoke test to establish a browser session through `/ci-auth/session`.

### Capturing Playwright Storage State

A staging browser session can be captured locally with Playwright:

```powershell
cd ui_tests
..\.venv\Scripts\python.exe -m playwright codegen "$env:SIMPLECHAT_UI_BASE_URL/chats" --save-storage artifacts\auth\storage_state.json
```

Sign in as the dedicated staging test user, then close the browser. Rerun the bootstrap script with `-UiStorageStatePath` to update the GitHub Environment secret. This is only needed when you want to test a real user session instead of the OIDC-backed CI service principal session.

GitHub secrets have a size limit. If the base64-encoded storage state becomes too large, store the state in Azure Key Vault and extend the workflow to retrieve it with the OIDC identity.

## Workflow Behavior

On a push to `Staging`, the workflow:

1. Authenticates to Azure using GitHub OIDC.
2. Restores the `azd` environment from `AZD_ENV_FILE_B64`.
3. Runs `azd up --no-prompt` by default.
4. Resolves or uses `SIMPLECHAT_UI_BASE_URL`.
5. Acquires a short-lived SimpleChat UI access token when `SIMPLECHAT_UI_AUTH_RESOURCE` is configured.
6. Waits up to 15 minutes for App Service warm-up. It checks `/external/healthcheckz`, `/external/healthcheck`, and the authenticated `/chats` route so normal post-deploy 503 responses during cold start do not fail the job too early.
7. Installs Playwright dependencies.
8. Restores the authenticated browser storage state when storage-state secrets are present.
9. Runs `npm run test:staging:azure` from `ui_tests/playwright-workspaces` against Microsoft Playwright Workspaces.
10. Runs `python -m pytest ui_tests/test_staging_chat_smoke.py -m ui -ra` as the existing Python smoke validation path.
11. Uploads UI test artifacts, screenshots, and traces if present.

Manual dispatch can choose `azd deploy` for code-only validation:

```text
azd_command: deploy
```

## Azure Permissions

Because `deployers/bicep/main.bicep` is subscription-scoped and creates role assignments, a full `azd up` workflow generally requires the CI service principal to have:

- `Contributor`
- `User Access Administrator`

The bootstrap script assigns these at subscription scope by default so `azd up` can fully validate staging infrastructure before `main`.

The same script also creates or updates a Microsoft Playwright Workspaces resource named `<AppName>-<AzdEnvironmentName>-pw` in the staging resource group, assigns the GitHub Actions service principal `Playwright Workspace Contributor` at that workspace scope, and writes `PLAYWRIGHT_SERVICE_URL` to the GitHub Environment. Playwright Workspaces are not available in every Azure region, so the script defaults the workspace region to `eastus` while keeping the resource in the staging resource group.

For UI authentication, the service principal is assigned the SimpleChat Enterprise App `Admin` app role. The app only accepts that token through `/ci-auth/session` when `ENABLE_CI_BEARER_SESSION_AUTH=true` and the caller app ID is explicitly listed in `CI_BEARER_SESSION_ALLOWED_APP_IDS`.

For a narrower deploy-only pattern against existing staging infrastructure, pass a resource group scope with `-RoleAssignmentScope` and run the workflow with `azd_command: deploy`.

## Testing and Validation

Coverage added in this version:

- `functional_tests/test_staging_ui_cicd_workflow.py` validates that the workflow, bootstrap script, and smoke test are present and connected to OIDC, `azd`, GitHub Environment secrets, and Playwright.
- `ui_tests/test_staging_chat_smoke.py` validates a real browser chat loop against the deployed staging environment.
- `ui_tests/playwright-workspaces/staging-chat-smoke.spec.js` validates the same path through Microsoft Playwright Workspaces.

Known limitations:

- `gh` is required to write GitHub Environment secrets automatically. Without it, the script can still create Azure OIDC assets when run with `-SkipGitHubConfiguration`.
- Storage state expires and must be refreshed periodically when storage-state authentication is used.
- Private-network-only staging environments require a runner and browser execution path with network access to the App Service.
