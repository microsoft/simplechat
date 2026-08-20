---
layout: page
title: "Security settings"
description: "Security covers access roles, Key Vault integration, Content Safety, idle session behavior, and Front Door-aware network URLs."
section: "Administration"
audience: admin
admin_tab: security
redirect_from:
  - /admin/safety/
---


# Security settings

## What this group controls

Security covers access roles, Key Vault integration, Content Safety, idle session behavior, and Front Door-aware network URLs.

## Why it matters

This group protects who can enter the app, what secrets the app can use, what content is blocked, and which hostnames are trusted for redirects. Treat changes as security controls.

{% include media.html src="admin-settings/security.png" alt="Screenshot of the Security group in Admin Settings." title="Security settings" %}

{% include media.html src="admin-settings/safety.png" alt="Screenshot of the Security group in Admin Settings." title="Security settings" %}

{% include media.html type="video" title="Security settings walkthrough" poster="video-posters/admin-security.png" capture="Recording planned. Walk through each tab in the Security group and explain when to change each setting." %}

## Before you change anything

- Create Entra app roles before requiring them.
- Provision Key Vault or Content Safety resources before enabling integrations.
- Validate Front Door hostnames and OAuth redirects before switching users to the routed URL.

## Access & Roles {#access-roles}

### Permissions {#permissions-section}

The Permissions section belongs to the Access & Roles tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### App Role Requirements {#app-role-requirements-section}

The App Role Requirements section belongs to the Access & Roles tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Access Denied Message {#access-denied-message-section}

The Access Denied Message section belongs to the Access & Roles tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Access Denied Message | Shown to signed-in users who lack the required roles. Use Enter for line breaks. | You are logged in but do not have the required permissions to access this application. Please contact an administrator for access. | `access_denied_message` |
| Require SafetyViolationAdmin App Role | Requires the `SafetyViolationAdmin` app role before users can use this capability or view. | Off | `require_member_of_safety_violation_admin` |

## Secrets {#secrets}

### Key Vault {#keyvault-section}

The Key Vault section belongs to the Secrets tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

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
| Key Vault Reminders Search | Defines behavior for the related admin workflow; verify the affected feature after saving. | N/A (runtime control) | Runtime UI control |
| Key Vault Reminders Status | Defines behavior for the related admin workflow; verify the affected feature after saving. | Empty | Runtime UI control |

## Content Safety {#content-safety}

### Content Safety {#content-safety-section}

The Content Safety section belongs to the Content Safety tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Content Safety | Routes chat content through Azure AI Content Safety so blocked messages use the configured violation message instead of continuing through the normal chat flow. | Off | `enable_content_safety`; capability toggle |
| Use APIM instead of direct Content Safety endpoint | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_content_safety_apim`; capability toggle |
| Content Safety Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Empty | `content_safety_endpoint` |
| Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `content_safety_authentication_type` |
| Content Safety Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `content_safety_key` |
| Azure APIM Content Safety Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Empty | `azure_apim_content_safety_endpoint` |
| Azure APIM Content Safety Subscription Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_apim_content_safety_subscription_key` |
| Safety Violation Message (Markdown supported) | Displayed when Content Safety blocks a chat message. | Not specified in defaults | `content_safety_violation_message` |
| Include Trigger Information | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `content_safety_include_trigger_information` |

## Session {#session}

### Idle Session Timeout {#idle-timeout-section}

The Idle Session Timeout section belongs to the Session tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Idle Session Timeout and Warning | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_idle_timeout`; capability toggle |
| Idle Logout Timeout (Minutes) | Users are logged out locally after this many minutes of inactivity. Minimum value: 10 minutes. | 30 | `idle_timeout_minutes` |
| Idle Warning Time (Minutes) | Show the warning modal after this many minutes of inactivity. Set this equal to the logout timeout to disable the warning dialog window. | 28 | `idle_warning_minutes` |
| Idle Warning Message | Custom text shown at the top of the idle warning dialog. | You've been inactive for a while. | `idle_warning_message` |

## Network {#network}

### Azure Front Door {#front-door-section}

The Azure Front Door section belongs to the Network tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Front Door Support | Generates user-facing and OAuth redirect URLs using the configured Front Door or load-balancer base URL. | Off | `enable_front_door`; capability toggle |
| Front Door URL | The base URL of your Front Door or load balancer. The system will automatically generate: Home redirect: https://your-frontdoor.azurefd.net OAuth2 redirect: https://your-frontdoor.azurefd.net/getAToken | Empty | `front_door_url` |

## Common tasks

1. **Require roles.** Enable a role requirement and test with assigned and unassigned users. Outcome to verify: Only assigned users can enter the protected surface.
2. **Move secrets to Key Vault.** Enable Key Vault storage, set access details, and rotate a low-risk secret. Outcome to verify: The app reads the secret from Key Vault.
3. **Turn on Content Safety.** Set routing, authentication, and violation message, then submit a blocked test prompt. Outcome to verify: Blocked content shows the configured message.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Sign-in redirects use the wrong host | Front Door support is off or the base URL is wrong. | Correct the URL and test sign-in through the routed domain. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Governance settings]({{ '/admin/governance/' | relative_url }})
- [Knowledge settings]({{ '/admin/knowledge/' | relative_url }})
