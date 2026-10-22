# SQL managed identity authentication fix

Fixed in version: **0.261.372**

Validation follow-up in version: **0.261.373**

## Issue and root cause

SQL connection checks and action execution could use different authentication
settings. SQL query and schema actions did not recognize the canonical managed
identity manifest for the `sqlserver` engine, even though it worked for the Azure
SQL aliases. A reusable identity's configured user-assigned client ID was also
lost before reaching the driver. Finally, inactive username/password fields
could override an explicitly selected managed identity during action execution.

These are application configuration and connection-building defects. Correct
application-side selection does not create a SQL database user or grant access.

## Technical details

The existing `sql_odbc_utils.py` boundary resolves managed identity consistently
and builds the native ODBC authentication settings:

| Configuration | Parameter-based SQL Server connection |
| --- | --- |
| Managed identity without a client ID | `Authentication=ActiveDirectoryMsi`, without `UID` |
| Managed identity with a user-assigned client ID | `Authentication=ActiveDirectoryMsi;UID=<client-id>` |
| Managed identity with leftover SQL username/password values | The managed identity settings above; inactive password fields are not used |
| Complete connection string | Its own authentication settings remain authoritative |

A selector supplied to the parameter builder must be a non-zero GUID. Blank
values select the system-assigned identity; malformed nonblank values fail
before connecting with the safe `sql_configuration_rejected` error code.
There is no retry with a different identity or password when authentication fails.

User-assigned client-ID selection here follows the ODBC contract for Azure App
Service. The identity must already be attached to the host and authorized in
the target database. This does not add a separate Azure Identity SDK token path
or change the platform-specific ODBC identity-selection contract.

### Files modified

- `functions_workspace_identities.py` carries the selected reusable identity's
  client ID into the transient SQL manifest. A system-assigned identity clears
  an inactive selector from that transient manifest, without rewriting storage.
- `route_backend_plugins.py` carries the selector through classic and V2
  connection checks and does not resolve inactive SQL passwords in
  parameter-based managed identity mode.
- `sql_query_plugin.py` and `sql_schema_plugin.py` use the same authentication
  normalization and builder. The existing companion-schema manifest copy
  preserves the selection without a loader change.
- `sql_plugin_factory.py` accepts an optional `managed_identity_client_id` for
  `create_azure_sql_plugins`, retaining the system-assigned default.
- `sql_connection_diagnostics.py` records managed identity as the effective
  mode even when inactive password fields remain and preserves safe
  application-owned configuration failures.
- Both SQL additional-settings schemas declare `managed_identity_client_id`.
- `application/single_app/config.py` records version **0.261.373**, including
  the test-loading and network-guard follow-up.

## Configuration and compatibility

Use a compatible reusable managed identity, or a SQL action with canonical
`auth.type` of `identity` and `auth.identity` of `managed_identity`. For an
explicit user-assigned identity, configure its client ID in the reusable
identity's `credentials.managed_identity_client_id`, or in
`additionalFields.managed_identity_client_id` for an inline SQL action.

The current V2 identity editor preserves an existing API-configured
user-assigned client ID; this fix does not add a new identity-editor control.
Do not supply a workspace identity record ID or an Entra principal/object ID
as the user-assigned client-ID selector.

Existing SQL-password and integrated connections, complete connection strings,
connection timeouts, connection reuse, and the bounded missing-Driver-17
fallback remain supported. PostgreSQL, MySQL, and SQLite connection behavior is
unchanged. No SQL service-principal implementation, automatic grants, weaker
TLS setting, or credential fallback is introduced.

## Validation

`functional_tests/test_sql_managed_identity_authentication.py` exercises real
identity hydration and query/schema plugin classes with external I/O replaced
and network access blocked. Its coverage includes scoped identities,
system-assigned and user-assigned selection, SQL Server/Azure SQL aliases,
classic/V2 draft and saved-action checks, saved-action normalization, companion
schema connections, inactive password handling, malformed selectors, unchanged
complete connection strings, and no authentication retry.

Before the fix, a user-assigned request connected without its client-ID selector,
canonical SQL Server identity manifests omitted managed identity authentication,
and leftover passwords selected SQL authentication. After the fix, the
regressions require the explicitly configured identity at the driver boundary
for both query and schema actions.

Related SQL diagnostics, driver compatibility, scoped identity, authoring,
route policy, and Cosmos response-contract checks provide compatibility
coverage. These offline checks are not proof of a successful connection from a
deployed managed identity; that additionally requires the deployment's own
network and database access prerequisites.

The focused SQL selection passed **256 tests**. A separate scoped
identity/companion-loader selection passed **108 tests**, and the affected
identity/action-route SDK owner evidence passed **45 tests**. These selections
overlap and are not a count of unique tests. The three route-policy scripts
passed all **28 checks**, and documentation coverage/quality passed all
**13 checks**.

These focused results do not assert that the full repository runtime suite is
green or that a deployed database login has succeeded.

### Portable test loading and explicit network guard

Version **0.261.373** makes the shared SQL/authoring module loaders resolve
relative filename components with the host's path implementation. A fixture
reference containing Windows separators therefore identifies the same source
file on Linux CI instead of treating the backslash as a filename character.
The SQL suite also explicitly installs the existing autouse network guard,
rather than relying on an apparently unused fixture import. Regressions
exercise both loader entry points with POSIX path semantics and confirm that
DNS access is refused before external I/O. No assertion, network guard, or CI
check is removed or weakened.

The follow-up passed **261 focused SQL tests** and **57 affected SDK
owner/CI-fixture cases**, including the twelve identity-hydration cases that
previously failed during setup on the hosted Linux runner.
