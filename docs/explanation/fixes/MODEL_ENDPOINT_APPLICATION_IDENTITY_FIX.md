# Model Endpoint Application Identity Fix

Fixed in version: **0.261.140**

## Issue

Personal and group model endpoints are configured by people who aren't
administrators: any user when `allow_user_custom_endpoints` is on, and group
Owners and Admins when `allow_group_custom_endpoints` is on.

When an endpoint's authentication resolves to the **application's own
credential**, Simple Chat requests a token with `DefaultAzureCredential`. That
covers **Managed Identity**, a missing authentication type, or any type other
than an API key or a service principal. Before this fix, the endpoint's own
configuration decided three things:

- **Where the token was sent.** The endpoint URL came from the endpoint, with no
  host allowlist.
- **What the token was for.** The audience could be changed with
  `auth.foundry_scope`. The authority could be changed with
  `auth.custom_authority` or a `custom` management cloud.
- **Which identity issued it.** `auth.managed_identity_client_id` selected any
  user-assigned identity attached to the App Service.

There were two ways to use this:

- **Unsaved requests.** Model discovery and the model test, sent without an
  `endpoint_id`, take the connection and authentication from the request. This
  applied to the legacy `/api/user/models/{fetch,test-model}` and
  `/api/group/models/{fetch,test-model}` routes.
- **Saved endpoints.** Saving such an endpoint first, then testing or fetching it
  by `endpoint_id`, bypassed any check on the request. So did letting any member
  chat through an agent bound to it. Either one sends the application's token to
  that host, for that audience.

## Root cause

Using the application identity for an endpoint whose owner isn't an
administrator was allowed with no rule on the destination, the token audience,
the authority, or the identity selection. Admin-managed global endpoints are
deliberately free to choose all of these. The same freedom had been extended to
personal and group endpoints.

## The rule

`functions_model_endpoint_app_identity.py` holds one predicate,
`application_identity_violation`. It applies to scopes `user` and `group` only.
An endpoint uses the application identity unless its provider is a custom
connection or its authentication is an API key or a service principal. Such an
endpoint must meet three conditions:

1. **The host is an Azure AI service host of the deployment's cloud.** The
   suffixes are `AZURE_AI_ENDPOINT_SUFFIXES` in
   `functions_azure_endpoint_validation.py`, checked by
   `validate_azure_ai_endpoint_host`:

   | Cloud | Allowed host suffixes |
   | --- | --- |
   | Public | `openai.azure.com`, `services.ai.azure.com`, `cognitiveservices.azure.com`, `api.cognitive.microsoft.com` |
   | Government | `openai.azure.us`, `services.ai.azure.us`, `cognitiveservices.azure.us`, `api.cognitive.microsoft.us` |
   | Custom | None |

   Azure API Management hosts (`azure-api.net`) aren't on the list. Anyone can
   create one, and the gateway sees the token.
2. **No audience or authority override.** A `foundry_scope`, `custom_authority`
   or `custom` management cloud that differs from the deployment's own is
   refused. The management cloud, audience and authority are then taken from
   server settings only. A value equal to the deployment's own is accepted.
3. **No identity selection.** `managed_identity_client_id` isn't honoured. The
   deployment's own identity selection is used.

### Where it applies

| Stage | Behaviour |
| --- | --- |
| Unsaved discovery and model tests (no `endpoint_id`) on the legacy user and group routes and the native group routes | A breach is refused with a stable 400. Otherwise the request runs with the server's values. |
| Saves: the native group create and PATCH (inside the conditional write, before anything is staged), the legacy group save, and the personal saves | A new endpoint, or one whose rule-relevant settings changed, that breaks the rule is refused with a stable 400. An unchanged endpoint stored before the rule doesn't block an unrelated edit. |
| Use: `keyvault_model_endpoint_get_helper` VALUE hydration, the step every stored-configuration consumer takes | A record stored before the rule **fails closed**, with a `[MODELS]` warning and the stable message. A stored identity selection is dropped. This runs whether or not Key Vault storage is on. |

The use-time check covers every stored-configuration consumer:

- model discovery, the model test and Foundry discovery by `endpoint_id`;
- chat streaming;
- the Semantic Kernel loader;
- workflows;
- conversation summaries;
- `resolve_model_endpoint_from_context`.

`resolve_endpoint_by_id` now carries each endpoint's stored scope, so a global
endpoint reached through a group route is judged, and hydrated, as global.

### Messages

| `code` | Message |
| --- | --- |
| `server_credential_endpoint_refused` | The application identity can be used only with an Azure AI endpoint in this cloud. Use an API key or a service principal for other endpoints. |
| `server_credential_override_refused` | The application identity uses this deployment's own token audience and authority. Remove the Foundry scope, custom authority and custom cloud, or use an API key or a service principal. |
| `server_credential_identity_refused` | The application identity is selected by this deployment. Remove the managed identity client ID, or use an API key or a service principal. |

Responses use the connection-error shape, `{"error": <message>, "code": <code>}`.

### What didn't change

- Endpoints that use an API key or a service principal, and custom connections.
- Admin-managed global endpoints and the admin routes.

## Technical details

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_model_endpoint_app_identity.py` | New. The predicate and its three enforcement helpers |
| `application/single_app/functions_azure_endpoint_validation.py` | `AZURE_AI_ENDPOINT_SUFFIXES` and `validate_azure_ai_endpoint_host` |
| `application/single_app/functions_keyvault.py` | The use-time check in `keyvault_model_endpoint_get_helper` for the `group` and `user` scopes |
| `application/single_app/route_backend_models.py` | The unsaved-request check, the legacy save check through `save_scoped_endpoint_secrets`, and stored scope in `resolve_endpoint_by_id` |
| `application/single_app/functions_group_endpoint_access.py` | The native save check |
| `functional_tests/test_model_discovery_server_credential_policy.py` | New |
| `functional_tests/test_model_endpoint_app_identity_rule.py` | New |

### Impact on existing endpoints

These changes can stop an existing personal or group endpoint from working:

| Endpoint | After this fix | What to do |
| --- | --- | --- |
| Uses the application identity with a host outside the list, such as an APIM gateway or a proxy | Fails closed | Switch it to an API key or a service principal, or ask an administrator for a global endpoint |
| Stores a Foundry scope, custom authority or custom cloud | Fails closed | Remove those settings, or switch to a service principal |
| Stores a managed identity client ID | Works with the deployment's default identity selection | Grant that identity access to the resource, or switch to a service principal |
| Deployed in a custom cloud | Can't use the application identity at all, because no host qualifies | Use an API key or a service principal, or a global endpoint |

### Known limitation

Azure OpenAI model discovery with the application identity lists deployments
through Azure Resource Manager, using the subscription ID and resource group the
endpoint names. The token goes only to Azure Resource Manager. Still, someone
allowed custom endpoints can list the deployments of an Azure OpenAI account in
any subscription and resource group the application identity can read.

## Validation

| Suite | Cases | Coverage |
| --- | --- | --- |
| `functional_tests/test_model_discovery_server_credential_policy.py` | 69 | The host allowlist; refused hosts and overrides on all six unsaved-request routes; allowed Azure hosts with server-derived values; an Azure Government deployment; the unaffected cases; admin routes; stored configuration failing closed; Foundry discovery has no unsaved path. 37 fail on the code before the unsaved-request check |
| `functional_tests/test_model_endpoint_app_identity_rule.py` | 55 | The predicate. Every enforcement point uses the one module. Every runtime consumer hydrates under its stored scope. Save refusals on the native, legacy group and personal saves. An unchanged older record doesn't block edits but still can't be used. Use-time fail-closed on the native and legacy test and fetch, native and legacy Foundry, personal, a stored audience, and the hydration step with Key Vault on and off. A stored identity selection is dropped. Global endpoints and admin routes are unchanged. 23 fail with the save and use checks removed |

| Case | Before | After |
| --- | --- | --- |
| Personal endpoint, managed identity, `https://attacker.example.com` | Application token sent to that host | 400 on save or test; fails closed at use |
| Group endpoint, managed identity, `https://contoso.openai.azure.com` | Works | Works, with the server's audience and authority |
| Group endpoint with `foundry_scope` for another audience | Token issued for that audience | Refused |
| Personal endpoint with `managed_identity_client_id` | That identity issues the token | Refused on save; ignored at use |
| Global endpoint, any of the above | Allowed | Allowed |
