---
layout: latest-release-feature
title: Key Vault Secret Expiration Reminders
description: Admins can track action secret expirations and route reminder signals before Key Vault-backed integrations break.
section: Latest Release
generated_from_catalog: true
---

Current release version for Key Vault Secret Expiration Reminders: **0.261.001**

The reminder inventory stores per-action secret expiration dates, lead days, contact emails, and rotation notes. A background sweep emits key_vault_secret_expiring in-app notifications and can also emit Application Insights telemetry for Azure Monitor alert routing, while secret replacement reliably writes a new Key Vault version.

## Why It Matters

This matters because expiring integration secrets become visible operational work instead of surprise outages.

## How to Try It

1. Open Admin Settings > Secrets and review Key Vault-backed action secret usage.
2. Record expiration dates, reminder lead days, contact emails, and rotation notes for managed action secrets.
3. Connect the optional Application Insights telemetry event to Azure Monitor alerts if central operations teams need escalation.
4. After rotating a secret, confirm the replacement creates a new Key Vault version and update the reminder inventory.

## Where to Find It

- **Open Secrets** &mdash; Review Key Vault secret storage and reminder configuration.
- **Open Logging** &mdash; Review telemetry routing for secret-expiration reminders.
