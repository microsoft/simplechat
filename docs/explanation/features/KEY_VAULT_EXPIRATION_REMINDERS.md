# Key Vault Expiration Reminders

Implemented in version: **0.250.121**
External telemetry added in version: **0.250.122**
Contact email telemetry opt-in added in version: **0.250.123**

## Overview

Key Vault expiration reminders let action owners add expiration metadata when storing Key Vault-backed secrets. SimpleChat records an inventory entry that maps the generated Key Vault secret name back to the action, scope, field, contact email, expiration date, and rotation notes.

## Dependencies

- Azure Key Vault secret storage must be configured for SimpleChat secret storage.
- Azure Monitor or Event Grid should be configured outside SimpleChat for email alerts on Key Vault near-expiry or expired events.
- SimpleChat in-app notifications supplement Azure alerts through the background reminder sweep.

## Technical Specifications

- **Inventory storage**: `key_vault_secret_reminders` Cosmos container partitioned by `scope_key`.
- **Metadata contract**: action metadata uses `key_vault_secret_reminders.__all__` for the action-modal "track all action secrets" control.
- **Admin APIs**:
  - `GET /api/admin/settings/key-vault/secret-reminders`
  - `POST /api/admin/settings/key-vault/secret-reminders/run`
- **Background sweep**: `run_key_vault_secret_reminder_loop()` checks due reminders under a distributed lock.
- **Notifications**: `key_vault_secret_expiring` in-app notifications target personal owners, groups, public workspaces, or configured admin roles for global secrets.
- **External telemetry**: each created reminder notification emits the Application Insights event `key_vault_secret_expiration_reminder_triggered` with queryable dimensions for Azure Monitor scheduled query alerts and downstream automation. Contact email is included only when the admin explicitly enables the external telemetry opt-in.

## Usage Instructions

1. Enable Key Vault secret storage in Admin Settings > Security > Key Vault.
2. Enable SimpleChat expiration reminder tracking.
3. Configure default lead days, default contact email, scan interval, and global admin notification roles.
4. Optionally enable **Include reminder contact email in external telemetry** when Azure Monitor, Logic Apps, Functions, or webhook automation must route messages directly to the configured reminder contact.
5. In an action's Advanced step, enable expiration tracking and enter:
   - expiration date,
   - reminder email,
   - lead days,
   - friendly label,
   - optional rotation notes.
6. Use the admin Key Vault reminder inventory to map expiring Key Vault secret names or reminder IDs back to their SimpleChat source and owner context.

## External Notification Options

### Azure Key Vault native events

Configure Azure Monitor or Event Grid on the Key Vault for native secret near-expiry and expired events. These alerts can send email through Azure action groups, but they only identify the vault and secret. Use the SimpleChat reminder inventory to map the secret name back to owner, source, field, contact email, and rotation notes.

### SimpleChat Application Insights event

When the SimpleChat reminder sweep creates an in-app notification, it also emits a queryable Application Insights trace event named:

```text
key_vault_secret_expiration_reminder_triggered
```

Recommended Application Insights query:

```kusto
traces
| where customDimensions.sc_event_name == 'key_vault_secret_expiration_reminder_triggered'
| project timestamp,
          reminder_id = tostring(customDimensions.sc_event_reminder_id),
          scope = tostring(customDimensions.sc_event_scope),
          source_type = tostring(customDimensions.sc_event_source_type),
          days_until_expiry = toint(customDimensions.sc_event_days_until_expiry),
          expires_on = tostring(customDimensions.sc_event_expires_on),
          contact_email = tostring(customDimensions.sc_event_contact_email),
          notification_scope = tostring(customDimensions.sc_event_notification_scope)
```

Use this query in an Azure Monitor scheduled query alert, then attach an action group, Logic App, Azure Function, or webhook for external notification or ticketing workflows. By default, external automation should notify a fixed admin channel and use `reminder_id` with the admin inventory when human-friendly context is needed. If direct owner routing is required, enable the contact-email telemetry opt-in so downstream automation can use `contact_email`.

## Testing and Validation

- Functional coverage: `functional_tests/test_sql_plugin_key_vault_secret_storage.py`
- External telemetry coverage: `functional_tests/test_keyvault_external_notification_telemetry.py`
- UI contract coverage: `ui_tests/test_admin_key_vault_reminders_ui.py`
- Route policy coverage applies to the new admin APIs.

## Limitations

- SimpleChat does not send email directly. Use Azure Monitor or Event Grid action groups for email alert delivery.
- Contact email is omitted from external telemetry by default. Admins must opt in before Azure Monitor or downstream automation can route directly to reminder contacts.
- The first UI pass supports a single action-level reminder configuration that applies to all Key Vault-backed secrets in that action.
