# V2 Key Vault Configuration Visibility Fix

**Fixed in version: 0.261.396**

The application patch version is recorded in `application/single_app/config.py`.

## Issue

Key Vault configuration looked absent from V2 Admin Settings. Administrators could
reach a Key Vault card without seeing the storage switch, vault resource name,
optional managed-identity client ID or connection-test action. Switching to classic
settings should not be necessary to configure this integration.

## Root cause

The definitions and V2 API routes already existed. The storage switch was declared
inside an ordinary, initially collapsed **Vault connection** group instead of as the
section's capability. The connection fields used a bare group label without the
`connection` variant that opens incomplete connections. Consequently, even an enabled
card saying **Needs configuration** could keep every control behind a closed group.

Browser regressions against the unchanged production SPA reproduced the hidden
switch on both disabled and enabled-but-unconfigured settings. This establishes a
local presentation defect; it does not establish which server or frontend build was
running in a separately deployed application, or diagnose a historical save 404.

## Changes

`application/single_app/admin_settings_fields.py` now places the existing storage
switch outside disclosures with `role: capability`. Its one-way warning is unchanged.
The existing vault name, identity and test fields share an explicit `connection`
group, and the vault name carries the required-configuration indicator.

The generic V2 renderer opens that group when an administrator enables storage with
no vault name. Fields remain conditional on the draft storage switch, so disabling
storage hides them without clearing saved configuration. Configured connections can
still be expanded for editing.

There are no new settings keys, Flask routes, authentication policies, credential
formats, SDK behavior or Azure infrastructure changes.

## Configuration workflow

In **V2 Admin Settings > Security > Key Vault**, enable **Store agent and action
secrets in Key Vault**. Supply the vault resource name, not a URL. An empty managed
identity client ID selects the App Service system-assigned identity; otherwise use
the client ID of the attached user-assigned identity.

**Test Key Vault connection** posts the unsaved values through
`POST /api/v2/admin/settings/test-connection`, retaining the shared permission probe.
**Save changes** commits the draft through `PATCH /api/v2/admin/settings`. A failed
test or rejected save leaves the draft available for correction.

Enabling storage remains effectively one-way once credentials have been saved as
vault references. Hiding or disabling the controls does not migrate those secrets.
The identity still needs the documented vault permissions and network access.

## Validation

`functional_tests/test_v2_admin_key_vault_configuration.py` checks the real field
definitions, normalization for both identity modes, partial/disabled updates and
credential redaction.

`ui_tests/test_v2_admin_key_vault_configuration.py` uses the real built SPA and field
normalizer through the shared local/Azure Playwright fixture. It covers the reachable
switch and warning, newly enabled and stored incomplete connections, search, draft
test payloads, save/reload, identity clearing, failed tests and saves, disabled
behavior, and desktop/light plus mobile/dark layouts. All service calls are intercepted;
no live Key Vault, secret or settings document is changed.

The existing classic/V2 permission-test fixture in
`ui_tests/fixtures/admin_diagnostics.py` selects connection fields by settings key and
test type rather than the old group-label representation, keeping its busy-state,
cleanup-error and safe-rendering regressions active.

The two initial visibility regressions failed before the metadata change. After the
fix, the focused functional/settings/permission suites pass **55 checks**, and the
new configuration plus existing classic/V2 diagnostic suites pass **18 browser
cases**. The production V2 build succeeds. Documentation inventory coverage passes
all seven checks and documentation quality passes all six checks.

The wider schema/security suites still report the same three unrelated failures
observed before this change: the classic Content Screening form marker, the Microsoft
365 trusted-hosts default type, and an orchestration completeness dependency. Those
are not changed by this fix.

## Related documentation

- [Security settings](../../admin/security.md#keyvault-section)
- [V2 Admin Security Settings](../features/V2_ADMIN_SECURITY_SETTINGS.md)
