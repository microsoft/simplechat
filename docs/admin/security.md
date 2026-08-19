---
layout: page
title: "Security Settings"
description: "Controls Key Vault secret storage and SimpleChat secret expiration reminder tracking."
section: "Administration"
audience: admin
admin_tab: security
---

## What this tab controls

Controls Key Vault secret storage and SimpleChat secret expiration reminder tracking.

## Why it matters

This tab moves sensitive agent and action secrets into Key Vault and controls expiration reminder tracking. It changes the operational model from secrets stored only in app settings to secrets managed by Azure Key Vault, so identity permissions and reminder routing must be correct before users depend on it.

{% include media.html src="admin/security-overview.png" alt="Screenshot of the Security settings tab showing security tab." title="Security tab" capture="Capture the Security tab for Security tab. Show relevant controls and redact secrets." %}

{% include media.html type="video" title="Security settings walkthrough" poster="video-posters/admin-security.png" capture="Recording planned. Walk through every setting on the Security tab and explain when to change each one." %}

## Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Key Vault for Agent and Action Secrets | Places agent and action secrets in Azure Key Vault through the configured vault identity. | Off | `enable_key_vault_secret_storage`; capability toggle |
| Key Vault Name | Provides the secret credential used when the selected authentication mode requires one. | Empty | `key_vault_name` |
| Key Vault Managed Identity Client ID | Provides the secret credential used when the selected authentication mode requires one. | Empty | `key_vault_identity` |
| Enable SimpleChat expiration reminder tracking | Tracks expiration metadata for stored secrets so admins can review or route reminders before secrets expire. | Off | `enable_key_vault_secret_expiration_reminders`; capability toggle |
| Default lead days | Provides the secret credential used when the selected authentication mode requires one. | 30 | `key_vault_secret_expiration_default_lead_days` |
| Default reminder email | Provides the secret credential used when the selected authentication mode requires one. | Empty | `key_vault_secret_expiration_default_contact_email` |
| Admin notification roles | Comma-separated roles for global-scope reminder notifications. | Admin | `key_vault_secret_expiration_admin_roles` |
| Scan interval seconds | Provides the secret credential used when the selected authentication mode requires one. | 21600 | `key_vault_secret_expiration_scan_interval_seconds` |
| Require expiration dates when users enable tracking on new secrets | Provides the secret credential used when the selected authentication mode requires one. | Off | `key_vault_secret_expiration_require_expiration` |
| Include reminder contact email in external telemetry | Default off. Enable only when Azure Monitor, Logic Apps, Functions, or webhook automation needs the email address to route notifications directly. | Off | `key_vault_secret_expiration_emit_contact_email_in_telemetry` |
| Key Vault Reminders Search | Controls how SimpleChat uses key vault reminders search on this tab. | N/A (runtime control) | Runtime UI control |
| Key Vault Reminders Status | Controls how SimpleChat uses key vault reminders status on this tab. | Empty | Runtime UI control |

### Key Vault secret storage

When enabled, agent and action secrets are stored in Azure Key Vault instead of only in SimpleChat settings records. The configured identity must have Key Vault access before users save secrets that depend on it.

### Secret expiration reminders

Reminder tracking lets SimpleChat record expiration metadata for secrets and notify configured roles or contacts before they expire. Requiring expiration dates is useful for governance, but it changes the save workflow for users creating new secrets.

## Before you change anything

- Create the Azure Key Vault before enabling Key Vault-backed secrets.
- Grant the configured managed identity permission to read and write the secrets SimpleChat stores.
- Decide who receives expiration reminders before requiring expiration dates.
- Confirm policy before enabling contact email emission in external telemetry.

## Common tasks

1. **Enable Key Vault-backed secrets.**
    1. Enable **Enable Key Vault for Agent and Action Secrets**.
    2. Enter **Key Vault Name**.
    3. Enter **Key Vault Managed Identity Client ID** if using a user-assigned identity.
    4. Save and create a test action secret.
    Outcome to verify: The secret is stored through the configured vault path.

{% include media.html src="admin/security-enable-key-vault-backed-secrets.png" alt="Screenshot of the Security settings tab showing enable key vault-backed secrets." title="Security: Enable Key Vault-backed secrets" capture="Capture the Security tab while performing Enable Key Vault-backed secrets. Show the relevant controls and redact secrets." %}

2. **Turn on expiration reminders.**
    1. Enable **Enable SimpleChat expiration reminder tracking**.
    2. Set **Default lead days**, **Default reminder email**, and **Admin notification roles**.
    3. Choose whether expiration dates are required for new secrets.
    4. Save and review reminder entries.
    Outcome to verify: Tracked secrets have reminder metadata.

{% include media.html src="admin/security-turn-on-expiration-reminders.png" alt="Screenshot of the Security settings tab showing turn on expiration reminders." title="Security: Turn on expiration reminders" capture="Capture the Security tab while performing Turn on expiration reminders. Show the relevant controls and redact secrets." %}

3. **Control reminder telemetry.**
    1. Leave **Include reminder contact email in external telemetry** off unless automation needs it.
    2. If enabled, confirm the telemetry destination is approved.
    3. Save and verify downstream routing.
    Outcome to verify: Contact emails are emitted only when intentionally required.

{% include media.html src="admin/security-control-reminder-telemetry.png" alt="Screenshot of the Security settings tab showing control reminder telemetry." title="Security: Control reminder telemetry" capture="Capture the Security tab while performing Control reminder telemetry. Show the relevant controls and redact secrets." %}

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Contact email is missing from telemetry | Email emission is off by default. | Enable contact email in external telemetry only if routing automation requires it. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Agents]({{ '/admin/agents/' | relative_url }})
- [Backup, Migrate & Restore]({{ '/admin/data-management/' | relative_url }})
