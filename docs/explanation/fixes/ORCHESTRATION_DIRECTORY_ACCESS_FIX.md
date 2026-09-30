# Orchestration directory access

**Version: 0.261.204**

**Fixed in version: 0.261.204**, tracked by `VERSION` in
`application/single_app/config.py`. The deployer changes ship in deployer version
**1.0.33**, tracked in `deployers/version.txt`.

## Issue

An orchestrated V2 chat that planned a web search failed with "A required
retained result is unavailable or changed. No preview was substituted." The same
failure hit every user, whatever app roles they had, and every step that used web
search, linked pages, deep research, agents, or actions. Nothing in Admin
Settings or the notification bell pointed to a cause, and the message suggested
stale content rather than a configuration problem.

## Root cause

Before a plan uses one of those external sources, Chat Orchestration rereads the
user's current app roles from Microsoft Graph with the application's own
client-credential identity. It doesn't trust the roles in the user's session,
because they can be hours old. That read needs the Microsoft Graph
`Directory.Read.All` **application** permission with administrator consent. The
affected app registration had only the delegated sign-in scopes, so Graph
answered 403.

Three gaps hid the cause:

- The identity reader reported Graph's 403 as `external_identity_access_denied`,
  the same code it uses when a user really lacks access.
- The executor turned every refusal into the generic `result_unavailable` step
  failure, so Application Insights recorded only that code.
- None of the deployers requested the permission, and the manual setup guide
  didn't list it.

## Technical details

### The application's refusals have their own reasons

`functions_orchestration_directory_access.py` defines two reasons for failures
that belong to the application rather than to the user:

| Reason | Raised when |
| --- | --- |
| `external_identity_directory_permission_missing` | Graph returns 403 to the application's directory read. |
| `external_identity_directory_sign_in_failed` | Graph returns 401, or Microsoft Entra ID refuses the client-credential sign-in with an error such as `invalid_client` after a client secret expires. |

`functions_orchestration_external_identity.py` raises these only for the
application's own directory reads. A decision about the user, such as a missing
app role or a user-settings refusal, stays `external_identity_access_denied`.
Graph outages and throttling stay retryable service failures and are never
reported as a missing permission.

`OrchestrationInvocationDeniedError` in
`functions_orchestration_invocation_capture.py` now carries the refusal's stable
code as `authority_reason`. It keeps only a snake_case code, never exception text
or an identifier. The first reason recorded for an invocation wins.

The Graph token source moved from `functions_orchestration_bootstrap.py` to
`graph_directory_token_provider` in
`functions_orchestration_directory_readiness.py`, so live requests and the admin
check sign in exactly the same way. It still mints only the application's own
Graph `.default` token.

### Users are told what to do

`functions_orchestration_schema.py` adds the step failure code
`directory_access_unavailable`. It's used only for the two reasons above; every
other refusal is still `result_unavailable`. The executor applies it when a step
is refused, when a saved wait is resumed, and when retained content is
reauthorized for the final answer. `functions_orchestration_composition.py`
applies it when a retained input is rechecked while content is prepared.

When the executor records a failed step, it names that step's source, so the
message says what the user was trying to do:

> Unable to verify your permission to use web search because this application
> doesn't have access to Microsoft Entra ID. Please contact your administrator.

Linked pages, deep research, agents, and actions use "read linked web pages",
"use deep research", "use agents", and "use actions". Any other step, and a
refusal during final-answer reauthorization, uses "use web search and other
external sources".

### Administrators are told first

- **Notification.** When a live request is refused,
  `report_directory_access_failure` sends an
  `orchestration_directory_access_unavailable` notification to users with the
  Admin role, linked to `/admin/settings#chat-orchestration`. Each server process
  sends it at most once per reason and UTC day. Its idempotency key keeps other
  instances from adding duplicates. A notification that couldn't be saved is
  retried by the next failure, and a notification failure never replaces the
  user's own failure message. The V2 bell labels it **Directory access**.
- **Settings check.** `POST /api/admin/settings/orchestration/directory-access-check`
  in `route_frontend_admin_settings.py` is admin-only. When Chat Orchestration is
  on and at least one of these sources is enabled, it runs the same Graph read for
  the signed-in administrator; otherwise it reads nothing. A ready result is reused
  for five minutes, and `{"refresh": true}` bypasses that. A missing permission or
  a refused sign-in is never cached, and it's also reported to administrators.
  Graph outages report the access as unverified.
- **Warning.** `static/js/admin/admin_orchestration_directory_access.js` runs the
  check when Admin Settings opens. Under **Enable Chat Orchestration**, a warning
  names the affected sources, gives the portal steps, and shows the
  `az ad app permission add` and `az ad app permission admin-consent` commands
  for this app registration. A refused sign-in shows client-secret guidance
  instead. **Check again** reruns the check. When web search is affected, the
  **Web Search** card shows a shorter warning that links to the full one. The
  module writes text only and loads from a local static path.

Directory refusals are logged with `sc_failure_code` set to
`directory_access_unavailable` and `sc_authority_reason` set to the reason.
Notifier and admin-check events use the new `[ORCHESTRATION_DIRECTORY]` tag. See
[Logging tags](../../reference/logging-tags.md#directory-access-events).

### Deployers request the permission and consent to it

| Deployer | Change |
| --- | --- |
| Bicep/azd, `deployers/Initialize-EntraApplication.ps1` | Requests `Directory.Read.All` as an application (Role) permission, then `Grant-GraphApplicationPermission` assigns the app role to the app's service principal, which is administrator consent. An existing assignment is left alone. If the signed-in account can't grant consent, the script warns, continues, and lists it as a manual step. |
| Azure CLI, `deployers/azurecli/deploy-simplechat.ps1` | Adds the permission and posts the app role assignment through `az rest`. If consent fails, it warns and points to STEP 2 of the manual checklist. |
| Terraform, `deployers/terraform/main.tf` | Adds the role to `azuread_application_api_access` and grants it with `azuread_app_role_assignment.msgraph_directory_read_all`. |

Granting consent needs a Global Administrator or Privileged Role Administrator. A
Terraform identity can hold the `AppRoleAssignment.ReadWrite.All` Graph
permission instead. The running application never requests consent or changes
permissions.

### Files modified

| Area | Files |
| --- | --- |
| New modules | `functions_orchestration_directory_access.py`, `functions_orchestration_directory_readiness.py`, `static/js/admin/admin_orchestration_directory_access.js` |
| Refusal reasons and messages | `functions_orchestration_external_identity.py`, `functions_orchestration_invocation_capture.py`, `functions_orchestration_schema.py`, `functions_orchestration_executor.py`, `functions_orchestration_composition.py`, `functions_orchestration_bootstrap.py` |
| Notifications and admin check | `functions_notifications.py`, `route_frontend_admin_settings.py`, `templates/admin/_panes/chat-orchestration.html`, `templates/admin/_panes/web-research.html`, `templates/admin_settings.html`, `application/v2_ui/src/lib/notifications.ts` |
| Deployers | `deployers/Initialize-EntraApplication.ps1`, `deployers/azurecli/deploy-simplechat.ps1`, `deployers/terraform/main.tf`, the Azure CLI, Bicep and Terraform READMEs, `deployers/version.txt` |
| Documentation | `docs/admin/orchestration.md`, `docs/deploy/manual/application-specific-configuration.md`, `docs/reference/logging-tags.md`, `docs/explanation/features/ORCHESTRATION_EXTERNAL_SOURCE_ACCESS.md` |
| Version | `config.py` |
| Test support | `functional_tests/test_support/orchestration_research.py` seeds the real failure code when it loads the failure schema offline |

## Validation

### Tests

`functional_tests/test_orchestration_directory_access.py` covers:

- how Graph and MSAL refusals map to reasons;
- the notifier's once-per-day and retry behavior;
- the admin check's caching and route authorization, including that no private
  values are returned;
- the templates and the browser module, run in Node;
- the Entra initializer's consent logic, run in PowerShell 7 and Windows
  PowerShell 5.1;
- the Azure CLI and Terraform deployer changes.

Real-runtime seam tests in the existing harnesses cover the rest:

- `test_orchestration_external_preflight_adapter.py`: a refusal keeps only its
  reason and stops before any external call.
- `test_orchestration_dependency_runtime.py`: a refused web search step,
  final-answer reauthorization, and composition each report the right code and
  message.
- `test_orchestration_source_authority_runtime.py`: a refused saved wait is
  explained to the user.

Every Graph, MSAL, and storage call in these tests is simulated. To check that
the tests catch regressions, 27 deliberate breakages were applied one at a time
across the Python modules, the browser module, and the Entra initializer. Every
one was caught.

### Before and after

| | Before | After |
| --- | --- | --- |
| User message | "A required retained result is unavailable or changed. No preview was substituted." | "Unable to verify your permission to use web search because this application doesn't have access to Microsoft Entra ID. Please contact your administrator." |
| Step failure code | `result_unavailable` | `directory_access_unavailable`, with `sc_authority_reason` |
| Admin Settings | No indication | A warning with the fix, the exact commands, and **Check again** |
| Notifications | None | Admin notification, at most once per reason per server each day |
| New deployments | Permission never requested | Requested, with consent granted where the deploying account can |

### Existing deployments

Deploying this version doesn't grant the permission. On an existing app
registration, follow the warning in Admin Settings, or run these with the
application (client) ID:

```powershell
az ad app permission add --id <application-client-id> --api 00000003-0000-0000-c000-000000000000 --api-permissions 7ab1d382-f21e-4acd-a863-ba3e13f7da61=Role
az ad app permission admin-consent --id <application-client-id>
```

Then select **Check again** in Admin Settings, and retry the failed step. A new
grant can take a few minutes to take effect.
